"""Operations: the one shape of everything femkit does for a person (api.md § 2–3).

A domain declares an operation with ``@operation``; the registry collects the
declarations and the surfaces serve them. Nothing here knows a domain.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol, TypeVar

from pydantic import Field, ValidationError, model_serializer

from femkit.core import clock, commandline, dirs, text, view
from femkit.core.errors import PlanStale, UsageError
from femkit.core.eventlog import OUTCOMES, EventLog
from femkit.core.issues import Issue
from femkit.core.locks import SUBJECT, subject_lock
from femkit.core.process import identify
from femkit.core.view import Verb
from femkit.core.schema import Model, key_path

T = TypeVar("T")


# --------------------------------------------------------------------- context

@dataclass
class Context:
    """One per invocation (api.md § 2.4)."""

    env: Mapping[str, str]
    now: Callable[[], datetime] = clock.now
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    def cached(self, key: str, factory: Callable[[], T]) -> T:
        if key not in self._cache:
            self._cache[key] = factory()
        return self._cache[key]

    @classmethod
    def from_process(cls) -> "Context":
        return cls(env=dict(os.environ))

    def fresh(self) -> "Context":
        """The same invocation's variables and clock, with nothing read yet: the world as it is now."""
        return Context(env=self.env, now=self.now)


# --------------------------------------------------------------------- results

class Result(Model):
    """Every operation's result (api.md § 2.3)."""

    issues: list[Issue] = Field(default_factory=list, description="findings a person should act on")

    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def report(self) -> view.Report:
        """What a person reads, as data, built from the result's fields alone (api.md § 2.3)."""
        raise NotImplementedError(f"{type(self).__name__} builds no report")

    def text(self) -> str:
        """The report as the command line writes it."""
        return text.report(self.report(), self.issues)

    @model_serializer(mode="wrap")
    def _with_report(self, handler):
        """The report goes with the result's JSON: the page draws it (web.md § 7.6)."""
        data = handler(self)
        if type(self).report is not Result.report:
            data["report"] = self.report().model_dump(mode="json")
        return data


class Step(Model):
    id: str = Field(description="stable within the plan; what the event log records")
    describe: str = Field(description="one line for a person")
    argv: tuple[str, ...] | None = Field(default=None, description="the command it will run, when it runs one")


class Ask(Model):
    """A question a surface asks the person on a terminal before consent (api.md § 3.1)."""

    key: str = Field(description="the request field the answer fills")
    question: str = Field(description="the question, one line")
    context: tuple[str, ...] = Field(default=(), description="what the person should see beside it")


class Plan(Model):
    operation: str = Field(default="", description="the operation's name; `Operation.plan` writes it")
    request: dict = Field(default_factory=dict, description="the request, as JSON; `Operation.plan` writes it")
    subjects: tuple[str, ...] = Field(default=(), description="the lock subjects apply holds alone: what it changes")
    shared: tuple[str, ...] = Field(default=(), description="those it holds shared: what it uses and does not change "
                                                            "(core.md § 5)")
    basis: dict = Field(default_factory=dict, description="the facts the plan rests on, observed before it was made; "
                                                          "apply refuses when they differ then (api.md § 3)")
    holds: dict = Field(default_factory=dict, description="what the plan decided that apply uses as decided: values "
                                                          "measured, a record, other operations' plans")
    steps: tuple[Step, ...] = Field(default=(), description="every step, in order; empty: nothing to do")
    issues: list[Issue] = Field(default_factory=list, description="findings a person should know before consenting")
    asks: tuple[Ask, ...] = Field(default=(), description="request fields to ask for on a terminal; unanswered, "
                                                          "the plan stands as it is")

    def text(self, brief: bool = False) -> str:
        """The plan as a person reads it; ``brief``: the steps alone, without their command
        lines and the findings (what `--yes` prints before applying, api.md § 4.2)."""
        n = len(self.steps)
        lines = [f"plan: {text.count(n, 'step')}" if n else "plan: nothing to do"]
        for i, step in enumerate(self.steps, 1):
            lines.append(f"  {i}. {step.describe}")
            if step.argv and not brief:
                lines.append(f"       $ {text.show(list(step.argv))}")
        return "\n".join(lines + ([] if brief else text.findings(self.issues)))

    def digest(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class PlanAnswer(Model):
    """A changing operation's plan, and the digest its apply must carry."""

    plan: Plan
    digest: str
    text: str = Field(description="the plan as a person reads it")


class Outcome(Result):
    """The result of ``apply``."""

    plan: Plan = Field(description="the plan that was applied")
    status: Literal["done", "failed"] = Field(description="whether every step finished")
    log: str | None = Field(default=None, description="the operation directory holding its event log")

    def ok(self) -> bool:
        return self.status == "done" and super().ok()


class Observer(Protocol):
    """What a surface is told while steps run (api.md § 3): where the logs are, each step
    with its place in the run, and how each ended."""

    def operation_start(self, plan: Plan, where: Path) -> None: ...
    def step_start(self, step: Step, index: int, total: int) -> None: ...
    def step_log(self, log: Path) -> None: ...
    def step_end(self, step: Step, outcome: str, log: Path | None) -> None: ...
    def note(self, text: str) -> None: ...
    def operation_end(self, plan: Plan, status: str) -> None: ...


class SilentObserver:
    def operation_start(self, plan: Plan, where: Path) -> None:
        pass

    def step_start(self, step: Step, index: int, total: int) -> None:
        pass

    def step_log(self, log: Path) -> None:
        pass

    def step_end(self, step: Step, outcome: str, log: Path | None) -> None:
        pass

    def note(self, text: str) -> None:
        pass

    def operation_end(self, plan: Plan, status: str) -> None:
        pass


class _Recording:
    """The surface's observer, with each step's log also recorded in its run's event log as
    the step reports it (`step-log`), so another surface can find a running step's log.
    Wraps every apply's observer (`Operation.apply`), so a step that reports to the apply's
    observer is recorded as one that reports to `run_steps`'s."""

    def __init__(self, observer: Observer, now: Callable[[], datetime]) -> None:
        self._observer, self._now = observer, now
        self._runs: list[list] = []      # each run in progress, innermost last: [its event log, its step]

    def __getattr__(self, name: str):
        return getattr(self._observer, name)

    def operation_start(self, plan: Plan, where: Path) -> None:
        self._runs.append([EventLog.of(where, self._now), None])
        self._observer.operation_start(plan, where)

    def step_start(self, step: Step, index: int, total: int) -> None:
        if self._runs:
            self._runs[-1][1] = step.id
        self._observer.step_start(step, index, total)

    def step_log(self, log: Path) -> None:
        if self._runs and self._runs[-1][1] is not None:
            self._runs[-1][0].append("step-log", step=self._runs[-1][1], log=str(log))
        self._observer.step_log(log)

    def operation_end(self, plan: Plan, status: str) -> None:
        if self._runs:
            self._runs.pop()
        self._observer.operation_end(plan, status)


def operations_root(subject: str | None = None) -> Path:
    """`<state>/operations/<subject>/`: every operation on a subject; with none, every subject's
    (core.md § 6)."""
    if subject is not None and not SUBJECT.fullmatch(subject):
        raise ValueError(f"{subject!r} is no subject (core.md § 5)")
    return dirs.state_dir() / "operations" / (subject or "")


#: An operation folder's name: the moment its run started, in UTC to the microsecond (core.md § 6).
TIME_FORMAT = "%Y%m%dT%H%M%S.%fZ"
TIME = re.compile(r"\d{8}T\d{6}\.\d{6}Z")


@dataclass(frozen=True)
class OperationAddress:
    """`<subject>/<time>`: one operation's folder under `<state>/operations/` (core.md § 6) — how a
    surface names a run, and the event routes take it."""

    subject: str
    time: str

    def __str__(self) -> str:
        return f"{self.subject}/{self.time}"

    def folder(self) -> Path:
        return operations_root(self.subject) / self.time

    @classmethod
    def at(cls, subject: str, moment: datetime) -> "OperationAddress":
        return cls(subject, moment.astimezone(timezone.utc).strftime(TIME_FORMAT))

    @classmethod
    def of(cls, folder: Path) -> "OperationAddress":
        return cls(Path(folder).parent.name, Path(folder).name)

    @classmethod
    def parse(cls, subject: str, time: str) -> "OperationAddress | None":
        """The address these name; None when either breaks its grammar (core.md §§ 5–6)."""
        return cls(subject, time) if SUBJECT.fullmatch(subject) and TIME.fullmatch(time) else None


def operation_dir(plan: Plan, now: datetime) -> Path:
    """`<state>/operations/<subject>/<time>/` (core.md § 6)."""
    return OperationAddress.at(plan.subjects[0] if plan.subjects else plan.operation, now).folder()


def run_steps(
    plan: Plan,
    ctx: Context,
    observer: Observer,
    do: Callable[[Step, Path], tuple[str, Path | None]],
    *,
    keep_going: bool = False,
) -> tuple[Literal["done", "failed"], Path]:
    """Run the plan's steps in order, writing the event log (api.md § 3).

    ``do(step, where)`` performs one step — ``where`` is the operation
    directory, the home of its logs — and returns its outcome, one of
    ``eventlog.OUTCOMES``, and its log. The first step that is not done stops the run, unless
    ``keep_going``: for steps that do not depend on each other, every step runs
    and the run fails if any did. An exception is recorded as the step's
    failure and re-raised carrying the operation directory as ``femkit_log``.
    """
    where = operation_dir(plan, ctx.now())
    log = EventLog.of(where, ctx.now)
    log.append("operation-start", operation=plan.operation, request=plan.request, basis=plan.basis,
               process=identify(os.getpid()).as_json())
    failed = False
    observer.operation_start(plan, where)
    for index, step in enumerate(plan.steps, 1):
        observer.step_start(step, index, len(plan.steps))
        log.append("step-start", step=step.id)
        try:
            outcome, step_log = do(step, where)
            if outcome not in OUTCOMES:
                raise ValueError(f"step {step.id}: {outcome!r} is no step outcome; they are {', '.join(OUTCOMES)}")
        except BaseException as exc:
            log.append("step-end", step=step.id, outcome="failed", log=None)
            log.append("operation-end", outcome="failed")
            observer.step_end(step, "failed", None)
            observer.operation_end(plan, "failed")
            exc.femkit_log = str(where)
            raise
        log.append("step-end", step=step.id, outcome=outcome, log=str(step_log) if step_log else None)
        observer.step_end(step, outcome, step_log)
        if outcome != "done":
            failed = True
            if not keep_going:
                break
    status = "failed" if failed else "done"
    log.append("operation-end", outcome=status)
    observer.operation_end(plan, status)
    return status, where


# ----------------------------------------------------------------- declaration

@dataclass(frozen=True)
class Operation:
    """A declared operation. Surfaces call ``run`` / ``plan`` / ``apply``. A changing operation
    whose plan rests on facts declares ``observe(req, ctx)``: core observes them before the
    plan is made, and again under the subjects' locks before any step runs (api.md § 3)."""

    verb: Verb
    result: type[Result]
    changes: bool
    doc: str
    impl: Any  # a function (read-only) or an instance with plan/apply (changing)
    subject: Callable[[Any], list[str]] | Literal["plan"] | None = None  # "plan": the plan names them

    @property
    def name(self) -> str:
        return self.verb.name

    @property
    def request(self) -> type[Model]:
        return self.verb.request

    def request_from(self, data: dict) -> Model:
        """The request model from its JSON form; one that does not validate is a `UsageError`
        naming each field's problem — on every surface alike."""
        try:
            return self.request.model_validate(data)
        except ValidationError as exc:
            problems = "; ".join(f"{key_path(e['loc']) or 'request'}: {e['msg']}" for e in exc.errors())
            raise UsageError(problems, code="invalid-request", subject=self.name) from None

    def run(self, req: Model, ctx: Context) -> Result:
        assert not self.changes, f"{self.name} changes things: plan, then apply"
        return self.impl(req, ctx)

    def plan(self, req: Model, ctx: Context) -> Plan:
        """The implementation's plan, with what the declaration knows written in: the
        operation's name, the request, and the subjects it locks."""
        assert self.changes, f"{self.name} is read-only: run it"
        observed = self.impl.observe(req, ctx) if hasattr(self.impl, "observe") else None
        plan = self.impl.plan(req, ctx)
        known = {"operation": self.name, "request": req.model_dump(mode="json")}
        if observed is not None:
            known["basis"] = observed
        if self.subject != "plan":
            known["subjects"] = tuple(self.subject(req)) if self.subject else ()
        return plan.model_copy(update=known)

    def apply(self, plan: Plan, ctx: Context, observer: Observer | None = None) -> Outcome:
        """Hold every subject's lock — alone, or shared — refuse a plan whose facts changed since,
        then apply (core.md § 5, api.md § 3)."""
        assert self.changes, f"{self.name} is read-only: run it"
        with ExitStack() as stack:
            for subject in plan.subjects:
                stack.enter_context(subject_lock(subject))
            for subject in plan.shared:
                stack.enter_context(subject_lock(subject, shared=True))
            if hasattr(self.impl, "observe"):
                req = self.request.model_validate(plan.request)
                if self.impl.observe(req, ctx.fresh()) != plan.basis:  # never a read cached since the plan
                    raise PlanStale(f"{', '.join(plan.subjects) or self.name} changed since the plan; plan it again",
                                    (view.command(self.verb, **req.model_dump(mode="json", exclude_defaults=True)),),
                                    code="basis-changed", subject=", ".join(plan.subjects) or self.name)
            recording = observer if isinstance(observer, _Recording) else _Recording(observer or SilentObserver(), ctx.now)
            return self.impl.apply(plan, ctx, recording)   # an apply inside another's records its steps once


def operation(
    verb: Verb,
    *,
    result: type[Result],
    changes: bool = False,
    subject: Callable[[Any], list[str]] | Literal["plan"] | None = None,
) -> Callable[[Any], Operation]:
    """Declare an operation (api.md § 2): decorate a function, or a class with plan/apply. Its
    name and request model are its `Verb`'s, declared beside the request."""
    name, request = verb.name, verb.request

    def declare(target: Any) -> Operation:
        doc = " ".join((target.__doc__ or "").split())
        if not doc:
            raise TypeError(f"{name}: an operation's docstring is its help; write one")
        if result.text is Result.text and result.report is Result.report:
            raise TypeError(f"{name}: {result.__name__} builds no report(); a result is read on a terminal too")
        flags = [n for n, f in request.model_fields.items()
                 if commandline.spelling(n, f).kind == "flag" and (f.is_required() or f.default is not False)]
        if flags:   # a flag only says yes: a field it cannot set back is one the command line cannot write
            raise TypeError(f"{name}: a bool field is a flag and defaults to False (api.md § 4.1): {', '.join(flags)}")
        if changes:
            if not isinstance(target, type) or not all(hasattr(target, m) for m in ("plan", "apply")):
                raise TypeError(f"{name}: a changing operation is a class with plan and apply")
            impl = target()
            impl.verb = verb                # its request model, for reading a plan's request back
        else:
            if subject is not None:
                raise TypeError(f"{name}: a read-only operation takes no lock")
            impl = target
        return Operation(verb, result, changes, doc, impl, subject)

    return declare
