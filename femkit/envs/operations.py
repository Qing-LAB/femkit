"""Environment operations (envs.md § 6)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from femkit.config import settings
from femkit.config.probe import place
from femkit.core import locks, process, text, view
from femkit.core.errors import Unstated, UsageError
from femkit.core import eventlog
from femkit.core.eventlog import EventLog, StepState, fold
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.schema import Model
from femkit.definitions import catalogue
from femkit.envs import checks, layout, toolchain
from femkit.envs.manager import resolve
from femkit.envs.records import CheckOutcome
from femkit.envs.state import INSTALLED, MACHINE, EnvState, definition, facts, observe
from femkit.envs.requests import ListRequest, CleanRequest, LogRequest, InstallRequest, ValidateRequest
from femkit.config.requests import CONFIG_SET
from femkit.envs.requests import ENV_CLEAN, ENV_INSTALL, ENV_LIST, ENV_LOG, ENV_VALIDATE



def _names(ctx: Context) -> list[str]:
    return sorted(catalogue.load(ctx).environments)


def _next(state: EnvState, name: str) -> list[view.Action]:
    return list(MACHINE.next(state, name))


# ------------------------------------------------------------------ env list

class EnvRow(Model):
    name: str = Field(description="the environment")
    state: EnvState = Field(description="its observed state", json_schema_extra={"doc": "envs.md § 3.2"})
    gpu: str | None = Field(description="GPU qualification; absent unless ready or failing")
    description: str = Field(description="what it holds")
    default: bool = Field(description="part of `env install --all`")
    prefix: str = Field(description="where it lives")


class ListResult(Result):
    rows: list[EnvRow] = Field(description="every engine environment")

    def text(self) -> str:
        return "\n".join(["environments"] + text.table(
            (r.name, r.state.value, f"gpu {r.gpu}" if r.gpu else "", f"# {r.description}") for r in self.rows))


@operation(ENV_LIST, result=ListResult)
def env_list(req: ListRequest, ctx: Context) -> ListResult:
    """Every engine environment with its state and GPU qualification."""
    defs = catalogue.load(ctx).environments
    rows = []
    for name in _names(ctx):
        f, state = observe(ctx, name)
        rows.append(EnvRow(name=name, state=state, gpu=f.gpu if state in INSTALLED else None,
                           description=defs[name].description,
                           default=defs[name].default, prefix=str(f.prefix)))
    return ListResult(rows=rows)


# ------------------------------------------------------------------ env clean

class CleanOutcome(Outcome):
    name: str = Field(default="", description="the environment")

    def text(self) -> str:
        if not self.plan.steps:
            return f"{self.name} is not installed; nothing to remove"
        return f"{self.name} removed; its lock is kept" if self.status == "done" else f"removing {self.name} failed"


@operation(ENV_CLEAN, result=CleanOutcome, changes=True,
           subject=lambda req: [layout.subject(req.name)])
class EnvClean:
    """Remove an environment's prefix, with its manifest and checks; keep its lock."""

    def plan(self, req: CleanRequest, ctx: Context) -> Plan:
        f, state = observe(ctx, req.name)
        if MACHINE.require(state, "clean", req.name).verb is None:
            return Plan()
        locks.require_free(layout.subject(req.name))      # a program using it — a web server — holds it shared
        manager = resolve(ctx)
        argv = tuple(manager.remove(f.prefix, catalogue.load_control().channels))
        return Plan(steps=(Step(id="remove", describe=f"remove {text.path(f.prefix)}", argv=argv),))

    def observe(self, req: CleanRequest, ctx: Context, held: bool) -> dict:
        f, state = observe(ctx, req.name, holding_lock=held)
        return {"state": state.value, "prefix": str(f.prefix)}

    def apply(self, plan: Plan, ctx: Context, observer) -> CleanOutcome:
        req = CleanRequest.model_validate(plan.request)

        def do(step: Step, where: Path):
            log = where / f"{step.id}.log"
            return ("done" if process.run(step.argv, log=log, env=resolve(ctx).environment).ok else "failed"), log

        status, where = run_steps(plan, ctx, observer, do)
        return CleanOutcome(plan=plan, status=status, log=str(where), name=req.name)


# ------------------------------------------------------------------ env log

class LogResult(Result):
    operation: str | None = Field(default=None, description="the last operation's directory; none if never run")
    outcome: Literal["done", "failed"] | None = Field(default=None, description="how it ended; none when it did not")
    steps: list[StepState] = Field(default_factory=list, description="its steps, in order")

    def text(self) -> str:
        if self.operation is None:
            return "no operation has run on it yet"
        lines = [f"last operation: {self.outcome or 'did not end'}   # {self.operation}"]
        return "\n".join(lines + text.table((s.outcome, s.id, s.log or "") for s in self.steps))


@operation(ENV_LOG, result=LogResult)
def env_log(req: LogRequest, ctx: Context) -> LogResult:
    """The last operation on an environment: its steps, how each ended, and their logs."""
    definition(ctx, req.name)  # an unknown name is refused, naming the environments
    runs = _runs(req.name)
    if not runs:
        return LogResult()
    state = fold(EventLog(runs[-1]).events())
    return LogResult(operation=str(runs[-1].parent), outcome=state.outcome,
                     steps=list(state.steps))


# ------------------------------------------------------------------ env install

def _runs(name: str) -> list[Path]:
    """Every operation on an environment, oldest first."""
    root = layout.operations_dir(name)
    return sorted(root.glob(f"*/{eventlog.FILE}")) if root.exists() else []


def last_operation(name: str) -> tuple[str | None, frozenset[str]]:
    """The newest operation's install fingerprint, and every step that finished in the
    unbroken run of operations with that fingerprint — each resume continues the one
    before it (envs.md § 4.2; core.md § 6)."""
    fingerprint, finished = None, set()
    for run in reversed(_runs(name)):
        events = EventLog(run).events()
        start = next((e for e in events if e["kind"] == "operation-start"), {})
        this = (start.get("basis") or {}).get("install_fingerprint")
        if fingerprint is None:
            fingerprint = this
        if this != fingerprint:
            break
        finished |= set(fold(events).finished_steps)
    return fingerprint, frozenset(finished)


def default_environments() -> list[str]:
    """What `env install --all` and `env bootstrap` install (envs.md § 1)."""
    return sorted(n for n, e in catalogue.load_catalogue().environments.items() if e.default)


def _requested(req) -> list[str]:
    if req.all:
        if req.names:
            raise UsageError("give environment names or --all, not both")
        return default_environments()
    if not req.names:
        raise UsageError("name an environment, or --all", (view.command(ENV_LIST),))
    return list(dict.fromkeys(req.names))


class EnvResult(Model):
    name: str = Field(description="the environment")
    status: str = Field(description="done, failed, nothing to do, or not reached")
    state: EnvState | None = Field(default=None, description="its state afterwards; none when not reached")
    log: str | None = Field(default=None, description="its install's operation directory")
    validation: str | None = Field(default=None, description="its validate's operation directory, when one ran")


class InstallOutcome(Outcome):
    environments: list[EnvResult] = Field(default_factory=list, description="each environment, in order")

    def text(self) -> str:
        lines = ["installed" if self.ok() else "the install failed" if self.status == "failed"
                 else "installed; not every environment is ready"]
        lines += text.table((e.name, e.status, e.state.value if e.state else "",
                             f"# {e.validation or e.log}" if e.validation or e.log else "")
                            for e in self.environments)
        lines += text.findings(self.issues)
        failed = [e for e in self.environments if e.status == "failed"]
        lines += text.next_block("read what failed", [view.command(ENV_LOG, name=e.name) for e in failed])
        return "\n".join(lines)


def _failures(outcomes, ids) -> str:
    """Each of the checks ``ids`` that failed, with its reason and log, one per line."""
    return "".join(f"\n    check {o.id} failed: {o.reason}" + (f"   # {o.log}" if o.log else "")
                   for o in outcomes if o.outcome == "failed" and o.id in ids)


def _killed(ctx: Context, name: str, steps: list[str]) -> Issue:
    """A step ended by SIGKILL, with what to do about where it ran (envs.md § 6.2)."""
    here = place(catalogue.schedulers(ctx), ctx.env)
    again = view.command(ENV_INSTALL, names=[name])
    advice, next_ = "free memory, or lower build.jobs", (again,)
    if here.where == "scheduler job":
        advice = "ask the allocation for more memory, or lower build.jobs"
    elif here.where == "login node" and here.kind.interactive:
        advice = "run the install inside an interactive allocation, not on a login node"
        next_ = (view.shell(here.kind.interactive, note=f"then, inside it: {again.command}"),)
    elif here.where == "login node":
        advice = "run the install inside a job, not on a login node"
    return Issue(severity="error", code="killed", subject=name,
                 message=f"{name}: {', '.join(steps)} killed (SIGKILL), most often by a memory limit; {advice}",
                 next=next_)


def _not_ready(f, state: EnvState, outcomes) -> Issue:
    """Why an environment a command finished is not ready: each CPU check that failed."""
    message = f"{f.name} is {state.value}" + _failures(outcomes, f.declared_checks - f.device_checks)
    return Issue(severity="error", code="not-ready", subject=f.name, message=message,
                 next=tuple(_next(state, f.name)))


def _install_basis(ctx: Context, name: str, held: bool) -> dict:
    """What an install of ``name`` rests on: its state, its install fingerprint and its place."""
    f, state = observe(ctx, name, holding_lock=held)
    return {"state": state.value, "install_fingerprint": f.install_fingerprint, "prefix": str(f.prefix)}


def _env_steps(ctx: Context, name: str, clean: bool) -> list[Step]:
    from femkit.envs.install import plan_steps, target
    f, state = observe(ctx, name)
    if MACHINE.require(state, "install --clean" if clean else "install", name).verb is None:
        return []
    locks.require_free(layout.subject(name))              # a program using it — a web server — holds it shared
    env = definition(ctx, name)
    cpu = checks.selected(env, gpu=False)
    validate = Step(id="validate", describe=f"validate: run its {text.count(len(cpu), 'CPU check')} (env validate)"
                    if cpu else "validate: it has no checks; record that (env validate)")
    checks.refusals(ctx, cpu)
    if state is EnvState.unchecked and not clean:
        return [validate]
    t = target(ctx, name, f.install_fingerprint)
    if t.env.proven_toolchain and t.env.proven_toolchain.mpi:
        settings.launcher(ctx, f"{name}'s toolchain check runs MPI on {toolchain.RANKS} ranks")
    cuda_builds = [b.id for b in t.env.builds if b.cuda_architectures]
    if cuda_builds and not settings.load(ctx).config.build.cuda_architectures:
        raise Unstated(f"{name} builds {', '.join(cuda_builds)} with CUDA, and build.cuda_architectures is unset",
                      (view.command(CONFIG_SET, key="build.cuda_architectures",
                                    fills=[view.Fill(field="value", label="the GPUs' architectures", example='["80"]')]),))
    fingerprint, finished = last_operation(name)
    resume = state is EnvState.incomplete and not clean and fingerprint == f.install_fingerprint
    remove_first = f.prefix_kind != "absent" and not resume
    steps = plan_steps(t, remove_first=remove_first, discard_lock=clean)
    if resume:  # the toolchain check proves this machine, which a resume may not be on: it runs again
        steps = [s for s in steps if s.id not in finished or s.id == "toolchain"]
    return steps + [validate]


@operation(ENV_INSTALL, result=InstallOutcome, changes=True,
           subject=lambda req: [layout.subject(n) for n in _requested(req)])
class EnvInstall:
    """Install environments from their definitions (envs.md § 4); resumes an interrupted install."""

    def plan(self, req: InstallRequest, ctx: Context) -> Plan:
        steps = [s.model_copy(update={"id": f"{name}/{s.id}", "describe": f"{name}: {s.describe}"})
                 for name in _requested(req) for s in _env_steps(ctx, name, req.clean)]
        return Plan(steps=tuple(steps))

    def observe(self, req: InstallRequest, ctx: Context, held: bool) -> dict:
        """Each requested environment's install basis: every one re-observed before any is touched."""
        return {name: _install_basis(ctx, name, held) for name in _requested(req)}

    def apply(self, plan: Plan, ctx: Context, observer) -> InstallOutcome:
        from femkit.envs.install import KILLED, run_step, target
        results, status, issues = [], "done", []
        for name, basis in plan.basis.items():
            if status == "failed":
                results.append(EnvResult(name=name, status="not reached"))
                continue
            f = facts(ctx, name, holding_lock=True)
            mine = tuple(s.model_copy(update={"id": s.id.split("/", 1)[1]}) for s in plan.steps if s.id.startswith(f"{name}/"))
            env_status, where, killed, outcomes, validated = "done", None, [], [], None
            if mine:
                sub = plan.model_copy(update={"subjects": (layout.subject(name),), "steps": mine,
                                              "basis": {"install_fingerprint": f.install_fingerprint}})
                t = target(ctx, name, f.install_fingerprint)

                def do(step, where):
                    nonlocal outcomes, validated
                    if step.id == "validate":  # envs.md § 4.1: its own operation, shown under this step
                        ran, validated, outcomes = checks.run_validation(
                            ctx, name, False, tuple(checks.steps(checks.selected(definition(ctx, name), gpu=False))),
                            observer)
                        return ran, validated  # done once every check ran, whatever its verdict
                    outcome, log = run_step(t, step, where, observer.note, observer.step_log)
                    if outcome == KILLED:
                        killed.append(step.id)
                    return outcome, log

                env_status, where = run_steps(sub, ctx, observer, do)
                if killed:
                    issues.append(_killed(ctx, name, killed))
            after, state = observe(ctx, name, holding_lock=True)
            results.append(EnvResult(name=name, status=env_status if mine else "nothing to do", state=state,
                                     log=str(where) if where else None,
                                     validation=str(validated) if validated else None))
            if env_status == "done" and state is not EnvState.ready:
                issues.append(_not_ready(after, state, outcomes))
            status = "failed" if env_status == "failed" else status
        return InstallOutcome(plan=plan, status=status, environments=results, issues=issues)


# ------------------------------------------------------------------ env validate

class ValidateOutcome(Outcome):
    name: str = Field(default="", description="the environment")
    state: EnvState | None = Field(default=None, description="its state afterwards")
    gpu: str | None = Field(default=None, description="its GPU qualification afterwards")
    outcomes: list[CheckOutcome] = Field(default_factory=list, description="every recorded check outcome")

    def text(self) -> str:
        head = f"{self.name}: {self.state.value if self.state else 'not validated'}"
        lines = [head + (f", GPU {self.gpu}" if self.gpu else "")]
        lines += text.table((o.outcome, o.id, o.reason, f"# {o.log}" if o.log and o.outcome == "failed" else "")
                            for o in self.outcomes)
        lines += text.findings(self.issues)
        return "\n".join(lines)


@operation(ENV_VALIDATE, result=ValidateOutcome, changes=True,
           subject=lambda req: [layout.subject(req.name)])
class EnvValidate:
    """Run an environment's checks and record whether it is ready (envs.md § 5)."""

    @staticmethod
    def _basis(f, state) -> dict:
        return {"state": state.value, "install_fingerprint": f.install_fingerprint,
                "check_fingerprint": f.check_fingerprint, "prefix": str(f.prefix)}

    def plan(self, req: ValidateRequest, ctx: Context) -> Plan:
        f, state = observe(ctx, req.name)
        env = definition(ctx, req.name)
        chosen = checks.selected(env, req.gpu)
        if req.gpu and not any(c.device for c in chosen):  # envs.md § 5: nothing to run, whatever its state
            cuda = req.name + catalogue.CUDA_SUFFIX
            if cuda in catalogue.load(ctx).environments:  # definitions.md § 4.5
                raise UsageError(f"{req.name} is built without CUDA; its CUDA build is {cuda}",
                                 (view.command(ENV_VALIDATE, name=cuda, gpu=True),))
            raise UsageError(f"{req.name} declares no GPU check", (view.command(ENV_VALIDATE, name=req.name),))
        MACHINE.require(state, "validate --gpu" if req.gpu else "validate", req.name)  # envs.md § 3.3
        locks.require_free(layout.subject(req.name))      # a program using it — a web server — holds it shared
        checks.refusals(ctx, chosen)
        return Plan(steps=tuple(checks.steps(chosen)))

    def observe(self, req: ValidateRequest, ctx: Context, held: bool) -> dict:
        f, state = observe(ctx, req.name, holding_lock=held)
        return self._basis(f, state)

    def apply(self, plan: Plan, ctx: Context, observer) -> ValidateOutcome:
        req = ValidateRequest.model_validate(plan.request)
        status, where, outcomes = checks.run_validation(ctx, req.name, req.gpu, plan.steps, observer)
        f, state = observe(ctx, req.name, holding_lock=True)
        issues = []
        if state is not EnvState.ready:  # with --gpu too: a CPU partner it ran again may fail
            issues.append(_not_ready(f, state, outcomes))
        if req.gpu and f.gpu != "passed":
            issues.append(Issue(severity="error", code="gpu-not-qualified", subject=req.name,
                                message=f"the GPU path is {f.gpu}" + _failures(outcomes, f.device_checks)))
        return ValidateOutcome(plan=plan, status=status, log=str(where), name=req.name, state=state,
                               gpu=f.gpu if state in INSTALLED else None, outcomes=outcomes, issues=issues)
