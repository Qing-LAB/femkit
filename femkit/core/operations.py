"""Operations: the one shape of everything femkit does for a person (api.md § 2–3).

A domain declares an operation with ``@operation``; the registry collects the
declarations and the surfaces serve them. Nothing here knows a domain.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol, TypeVar

from pydantic import Field

from femkit.core import dirs, text
from femkit.core.eventlog import EventLog
from femkit.core.issues import Issue
from femkit.core.locks import subject_lock
from femkit.core.schema import Model

T = TypeVar("T")


# --------------------------------------------------------------------- context

@dataclass
class Context:
    """One per invocation (api.md § 2.4)."""

    env: Mapping[str, str]
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    def cached(self, key: str, factory: Callable[[], T]) -> T:
        if key not in self._cache:
            self._cache[key] = factory()
        return self._cache[key]

    @classmethod
    def from_process(cls) -> "Context":
        return cls(env=dict(os.environ))


# --------------------------------------------------------------------- results

class Result(Model):
    """Every operation's result (api.md § 2.3)."""

    issues: list[Issue] = Field(default_factory=list, description="findings a person should act on")

    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def text(self) -> str:
        raise NotImplementedError(f"{type(self).__name__} must render its own text")


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
    operation: str = Field(description="the operation's name")
    request: dict = Field(description="the request, as JSON")
    subjects: tuple[str, ...] = Field(default=(), description="the lock subjects apply holds")
    basis: dict = Field(default_factory=dict, description="the observed facts the plan was made from")
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
    def step_end(self, step: Step, outcome: str, log: Path | None) -> None: ...
    def note(self, text: str) -> None: ...
    def operation_end(self, plan: Plan, status: str) -> None: ...


class SilentObserver:
    def operation_start(self, plan: Plan, where: Path) -> None:
        pass

    def step_start(self, step: Step, index: int, total: int) -> None:
        pass

    def step_end(self, step: Step, outcome: str, log: Path | None) -> None:
        pass

    def note(self, text: str) -> None:
        pass

    def operation_end(self, plan: Plan, status: str) -> None:
        pass


def operations_root(subject: str) -> Path:
    """`<state>/operations/<subject>/`: every operation on a subject (core.md § 6)."""
    return dirs.state_dir() / "operations" / subject


def operation_dir(plan: Plan, now: datetime) -> Path:
    """`<state>/operations/<subject>/<time>/` (core.md § 6)."""
    return operations_root(plan.subjects[0] if plan.subjects else plan.operation) / now.strftime("%Y%m%dT%H%M%S.%fZ")


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
    directory, the home of its logs — and returns ``("done" | any other outcome,
    its log)``. The first step that is not done stops the run, unless
    ``keep_going``: for steps that do not depend on each other, every step runs
    and the run fails if any did. An exception is recorded as the step's
    failure and re-raised carrying the operation directory as ``femkit_log``.
    """
    where = operation_dir(plan, ctx.now())
    log = EventLog(where / "events.jsonl")
    log.append("operation-start", operation=plan.operation, request=plan.request, basis=plan.basis,
               pid=os.getpid())
    failed = False
    observer.operation_start(plan, where)
    for index, step in enumerate(plan.steps, 1):
        observer.step_start(step, index, len(plan.steps))
        log.append("step-start", step=step.id)
        try:
            outcome, step_log = do(step, where)
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
    """A declared operation. Surfaces call ``run`` / ``plan`` / ``apply``."""

    name: str
    request: type[Model]
    result: type[Result]
    changes: bool
    doc: str
    impl: Any  # a function (read-only) or an instance with plan/apply (changing)
    subject: Callable[[Any], list[str]] | None = None

    def run(self, req: Model, ctx: Context) -> Result:
        assert not self.changes, f"{self.name} changes things: plan, then apply"
        return self.impl(req, ctx)

    def plan(self, req: Model, ctx: Context) -> Plan:
        assert self.changes, f"{self.name} is read-only: run it"
        plan = self.impl.plan(req, ctx)
        subjects = tuple(self.subject(req)) if self.subject else ()
        return plan.model_copy(update={"subjects": subjects})

    def apply(self, plan: Plan, ctx: Context, observer: Observer | None = None) -> Outcome:
        """Hold every subject's lock, then apply (core.md § 5, api.md § 3)."""
        assert self.changes, f"{self.name} is read-only: run it"
        with ExitStack() as stack:
            for subject in plan.subjects:
                stack.enter_context(subject_lock(subject))
            return self.impl.apply(plan, ctx, observer or SilentObserver())


def operation(
    name: str,
    *,
    request: type[Model],
    result: type[Result],
    changes: bool = False,
    subject: Callable[[Any], list[str]] | None = None,
) -> Callable[[Any], Operation]:
    """Declare an operation (api.md § 2): decorate a function, or a class with plan/apply."""

    def declare(target: Any) -> Operation:
        doc = " ".join((target.__doc__ or "").split())
        if not doc:
            raise TypeError(f"{name}: an operation's docstring is its help; write one")
        if changes:
            if not isinstance(target, type) or not all(hasattr(target, m) for m in ("plan", "apply")):
                raise TypeError(f"{name}: a changing operation is a class with plan and apply")
            impl = target()
        else:
            if subject is not None:
                raise TypeError(f"{name}: a read-only operation takes no lock")
            impl = target
        return Operation(name, request, result, changes, doc, impl, subject)

    return declare
