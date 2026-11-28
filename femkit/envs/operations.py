"""Environment operations (envs.md § 6)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

from pydantic import Field

from femkit.config import settings
from femkit.config.probe import place
from femkit.core import process, text, view
from femkit.core.errors import Unstated, UsageError
from femkit.core import eventlog
from femkit.core.eventlog import EventLog, StepState, fold
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.schema import Model
from femkit.definitions import catalogue
from femkit.envs import checks, layout, manager, toolchain
from femkit.envs.manager import resolve
from femkit.envs.records import CheckOutcome
from femkit.envs.state import (BUILDS, DELIVER, DISCARD, INSTALL, QUALIFIED, REMOVE, RESUME, VALIDATE, VALIDATE_GPU,
                               Gpu, added, alone, definition, delivering, gpu, install_fingerprint, lacking, machine,
                               observe, orphaned, projects, require, step, to_deliver)
from femkit.envs.requests import ListRequest, CleanRequest, LogRequest, InstallRequest, ValidateRequest
from femkit.envs.requests import ENV_CLEAN, ENV_INSTALL, ENV_LIST, ENV_LOG, ENV_VALIDATE


# ------------------------------------------------------------------ env list

class EnvRow(Model):
    name: str = Field(description="the environment")
    state: str = Field(description="its observed state", json_schema_extra={"doc": "envs.md § 3.2"})
    gpu: Gpu | None = Field(description="GPU qualification; absent unless ready or failing",
                            json_schema_extra={"doc": "envs.md § 5"})
    description: str = Field(description="what it holds")
    default: bool = Field(description="one of the default environments, which `env install` with `all`, and "
                                      "`env bootstrap`, install")
    managed: str = Field(description="its name with the package manager", json_schema_extra={"doc": "envs.md § 1"})
    prefix: str | None = Field(default=None, description="where it lives, as the manager lists it; none where it "
                                                         "lists none")
    deliver: list[str] = Field(default_factory=list, description="the packages the projects declare for it that it "
                               "does not hold yet, which `env install` delivers into it as it stands",
                               json_schema_extra={"doc": "envs.md § 4.1"})


class ListResult(Result):
    rows: list[EnvRow] = Field(description="every environment, an engine's or a tool's")

    @property
    def report(self) -> view.Report:
        return view.Report(blocks=[view.Text(text="environments"), view.Table.of(
            EnvRow, [{"name": r.name, "state": r.state, "gpu": f"gpu {r.gpu}" if r.gpu else "",
                      "description": r.description} for r in self.rows], "name", "state", "gpu", "description")])


@operation(ENV_LIST, result=ListResult)
def env_list(req: ListRequest, ctx: Context) -> ListResult:
    """Every environment — an engine's or a tool's — with its name with the manager, its state and GPU qualification."""
    defs = catalogue.environments(ctx)
    rows, issues = [], []
    for name in sorted(defs):
        f, state = observe(ctx, name)
        deliver = delivering(ctx, f, state)
        rows.append(EnvRow(name=name, state=state.value, gpu=gpu(ctx, f, state),
                           description=defs[name].description, default=defs[name].default,
                           managed=catalogue.managed(ctx, name), prefix=str(f.prefix) if f.prefix else None,
                           deliver=deliver))
        issues += [i for i in (to_deliver(ctx, f, state, deliver), orphaned(ctx, f, state)) if i is not None]
    return ListResult(rows=rows, issues=issues)


# ------------------------------------------------------------------ env clean

class CleanOutcome(Outcome):
    name: str = Field(default="", description="the environment")

    @property
    def report(self) -> view.Report:
        said = f"{self.name} is not installed; nothing to remove" if not self.plan.steps else \
            f"{self.name} removed; its lock is kept" if self.status == "done" else f"removing {self.name} failed"
        return view.Report(blocks=[view.Text(text=said)])


@operation(ENV_CLEAN, result=CleanOutcome, subject=lambda req: [layout.subject(req.name)])
class EnvClean:
    """Remove an environment's prefix, with its manifest and checks; keep its lock."""

    def plan(self, req: CleanRequest, ctx: Context) -> Plan:
        f, state = observe(ctx, req.name)
        require(ctx, f, state, "clean")
        if REMOVE not in machine(ctx).does(state, f):    # what its table gives the state (envs.md § 3.3)
            return Plan()
        alone(req.name)
        m, managed = resolve(ctx), catalogue.managed(ctx, req.name)
        argv = tuple(m.remove(managed, catalogue.control(ctx).channels))
        return Plan(steps=(Step(id="remove", describe=f"remove {managed}, at {text.path(f.prefix)}", argv=argv),))

    def observe(self, req: CleanRequest, ctx: Context) -> dict:
        f, state = observe(ctx, req.name)
        return {"state": state.value, "prefix": str(f.prefix) if f.prefix else None}

    def apply(self, plan: Plan, ctx: Context, observer) -> CleanOutcome:
        req = CleanRequest.model_validate(plan.request)

        def do(step: Step, where: Path):
            log, m = where / f"{step.id}.log", resolve(ctx)
            try:
                return ("done" if process.run(step.argv, log=log, env=m.environment).ok else "failed"), log
            finally:
                m.forget()   # where its environments are, asked again

        status, where = run_steps(plan, ctx, observer, do)
        return CleanOutcome(plan=plan, status=status, log=str(where), name=req.name)


# ------------------------------------------------------------------ env log

class LogResult(Result):
    operation: str | None = Field(default=None, description="the last operation's directory; none if never run")
    outcome: Literal["done", "failed"] | None = Field(default=None, description="how it ended; none when it did not")
    steps: list[StepState] = Field(default_factory=list, description="its steps, in order")

    @property
    def report(self) -> view.Report:
        if self.operation is None:
            return view.Report(blocks=[view.Text(text="no operation has run on it yet")])
        return view.Report(blocks=[
            view.Text(text=f"last operation: {self.outcome or 'did not end'} — {text.path(self.operation)}"),
            view.Table.of(StepState, [{"outcome": s.outcome, "id": s.id, "log": text.path(s.log) if s.log else ""}
                                      for s in self.steps], "outcome", "id", "log")])


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


def last_install(name: str) -> tuple[str | None, frozenset[str]]:
    """What a resume continues (envs.md § 4.2): the newest install's fingerprint, and every step
    that finished in the unbroken run of unfinished installs with that fingerprint — each resume
    continues the one before it. A validate between them is no install and breaks no run; an
    install that ended done ends the run, and leaves nothing to resume."""
    fingerprint, finished = None, set()
    for run in reversed(_runs(name)):
        state = fold(EventLog(run).events())
        if state.operation != ENV_INSTALL.name:
            continue
        this = state.basis.get("install_fingerprint")
        if state.outcome == "done" or (fingerprint is not None and this != fingerprint):
            break
        fingerprint = this
        finished |= set(state.finished_steps)
    return fingerprint, frozenset(finished)


def default_environments(ctx: Context) -> list[str]:
    """What `env install` with `all`, and `env bootstrap`, install (envs.md § 1)."""
    return sorted(n for n, e in catalogue.environments(ctx).items() if e.default)


def _requested(req: InstallRequest, ctx: Context) -> list[str]:
    """The environments the request names — every default one, for `all` — each once, in order;
    the request itself refuses both and neither (api.md § 4.1)."""
    return default_environments(ctx) if req.all else list(dict.fromkeys(req.names))


class EnvResult(Model):
    name: str = Field(description="the environment")
    status: Literal["done", "failed", "nothing to do", "not reached"] = Field(
        description="how its install ended; `not reached` when an earlier one failed")
    state: str | None = Field(default=None, description="its state afterwards; none when not reached",
                              json_schema_extra={"doc": "envs.md § 3.2"})
    log: str | None = Field(default=None, description="its install's operation directory")
    validation: str | None = Field(default=None, description="its validate's operation directory, when one ran")


class InstallOutcome(Outcome):
    environments: list[EnvResult] = Field(default_factory=list, description="each environment, in order")
    next: list[view.Action] = Field(default_factory=list, description="for each environment whose install failed, "
                                                                      "the command that shows its log")

    @property
    def report(self) -> view.Report:
        said = "installed" if self.ok() else "the install failed" if self.status == "failed" \
            else "installed; not every environment is ready"
        blocks = [view.Text(text=said), view.Table.of(
            EnvResult, [{"name": e.name, "status": e.status, "state": e.state or "",
                         "log": text.path(e.validation or e.log) if e.validation or e.log else ""}
                        for e in self.environments], "name", "status", "state", "log")]
        return view.Report(blocks=blocks + ([view.Next(label="read what failed", actions=self.next)]
                                            if self.next else []))


def _failed_checks(name: str, outcomes: list[CheckOutcome], ids: frozenset[str]) -> list[Issue]:
    """One finding for each of the checks ``ids`` that failed: its reason, and its log as the
    file the person opens (core.md § 10)."""
    return [Issue(severity="error", code="check-failed", subject=name, message=f"check {o.id} failed: {o.reason}",
                  file=o.log)
            for o in outcomes if o.outcome == "failed" and o.id in ids]


def _killed(ctx: Context, name: str, steps: list[str]) -> Issue:
    """A step ended by SIGKILL, with what to do about where it ran (envs.md § 6.2): the install
    again, as the environment table's row gives it for the state the killed step left it in — one
    source of a next step (framework.md § 3) — inside an allocation, where it ran on a login node
    of a scheduler that offers one."""
    here = place(catalogue.schedulers(ctx), ctx.env)
    again = step(ctx, name, observe(ctx, name)[1], INSTALL)
    advice, next_ = "free memory, or lower build.jobs", again
    if here.where == "scheduler job":
        advice = "ask the allocation for more memory, or lower build.jobs"
    elif here.where == "login node" and here.kind.interactive:
        advice = "run the install inside an interactive allocation, not on a login node"
        next_ = (view.shell(here.kind.interactive), *(a.model_copy(update={"note": "inside it"}) for a in again))
    elif here.where == "login node":
        advice = "run the install inside a job, not on a login node"
    return Issue(severity="error", code="killed", subject=name,
                 message=f"{name}: {', '.join(steps)} killed (SIGKILL), most often by a memory limit; {advice}",
                 next=next_)


def _not_ready(ctx: Context, f, state, outcomes: list[CheckOutcome]) -> list[Issue]:
    """Why an environment a command finished is not ready: that it is not, with what its state
    allows, and one finding for each CPU check that failed."""
    return [Issue(severity="error", code="not-ready", subject=f.name, message=f"{f.name} is {state.value}",
                  next=machine(ctx).next(state, f)),
            *_failed_checks(f.name, outcomes, f.declared_checks - f.device_checks)]


def _install_basis(ctx: Context, name: str) -> dict:
    """What an install of ``name`` rests on: its state, its install fingerprint, its place, the
    saved lock it would create from — none while no manager is named to fingerprint it — and the
    earlier install it would resume."""
    f, state = observe(ctx, name)
    fingerprint = install_fingerprint(ctx, name, manager.named_kind(ctx))
    resumed, finished = last_install(name)
    return {"state": state.value, "install_fingerprint": f.install_fingerprint,
            "prefix": str(f.prefix) if f.prefix else None,
            "launcher": settings.load(ctx).config.launch.mpi,   # in its toolchain check's and its checks' commands
            "saved_lock": fingerprint is not None and layout.lock_file(name, fingerprint).exists(),
            "resume": {"install_fingerprint": resumed, "finished": sorted(finished)},
            "projects": added(ctx, name), "recorded": f.manifest.projects if f.manifest is not None else []}


def _env_steps(ctx: Context, name: str, clean: bool) -> list[Step]:
    """What `install` (or `install --clean`) does in the environment's state, where its table allows
    it there (envs.md § 3.3): the tasks the table's `[does]` gives the state, each where its guard
    holds over the facts the install observes — asked `--clean`, its last install resumable, a
    package the projects declare that it lacks (core.md § 7): nothing; its validate; that package
    delivered into it as it stands, then its validate (§ 4.1); or the install, from the steps the
    last attempt finished for this fingerprint (§ 4.2) where it resumes, its prefix removed first
    where there is one otherwise, its saved lock discarded first where the table says so."""
    from femkit.envs.install import deliver_steps, plan_steps, target
    f, state = observe(ctx, name)
    require(ctx, f, state, "install --clean" if clean else "install")
    fingerprint, finished = last_install(name)
    now = install_fingerprint(ctx, name, manager.named_kind(ctx))     # what the manager named now would build
    f = replace(f, clean=clean, resumable=fingerprint is not None and fingerprint == now,
                lacking=f.manifest is not None and bool(lacking(ctx, name, f.manifest)))
    done = machine(ctx).does(state, f)
    if not any(v in done for v in (VALIDATE, DELIVER, RESUME, *BUILDS)):
        return []
    alone(name)
    if any(v in done for v in (DELIVER, RESUME, *BUILDS)):   # a create or a delivery: the recipe decides (§ 4.4)
        from femkit.envs.install import refuse_settings, target
        refuse_settings(target(ctx, name))
    env = definition(ctx, name)
    cpu = checks.selected(env, gpu=False)
    validate = Step(id="validate", describe=f"validate: run its {text.count(len(cpu), 'CPU check')} (env validate)"
                    if cpu else "validate: it has no checks; record that (env validate)")
    checks.refusals(ctx, cpu)
    if DELIVER in done:
        return [*deliver_steps(target(ctx, name)), validate]
    if VALIDATE in done:
        return [validate]
    t = target(ctx, name)
    if t.env.proven_toolchain and t.env.proven_toolchain.mpi:
        settings.launcher(ctx, f"{name}'s toolchain check runs MPI on {toolchain.RANKS} ranks")
    cuda_builds = [b.id for b in t.env.builds if b.cuda_architectures]
    if cuda_builds and not settings.load(ctx).config.build.cuda_architectures:
        raise Unstated(f"{name} builds {', '.join(cuda_builds)} with CUDA, and build.cuda_architectures is unset",
                      settings.steps(["build.cuda_architectures"]),
                      code="setting-unset", subject="build.cuda_architectures")
    resume = RESUME in done
    steps = plan_steps(t, remove_first=f.prefix_kind != "absent" and not resume, discard_lock=DISCARD in done)
    if resume:  # the toolchain check proves this machine, which a resume may not be on: it runs again
        steps = [s for s in steps if s.id not in finished or s.id == "toolchain"]
    return steps + [validate]


@operation(ENV_INSTALL, result=InstallOutcome, subject="plan")
class EnvInstall:
    """Install environments from their definitions; resumes an interrupted install."""

    def plan(self, req: InstallRequest, ctx: Context) -> Plan:
        names = _requested(req, ctx)
        steps = [s.model_copy(update={"id": f"{name}/{s.id}", "describe": f"{name}: {s.describe}"})
                 for name in names for s in _env_steps(ctx, name, req.clean)]
        validated = {s.id.split("/", 1)[0] for s in steps if s.id.endswith("/validate")}
        held = {name: [s.model_dump(mode="json") for s in checks.steps(
            checks.runner(ctx, name), checks.selected(definition(ctx, name), gpu=False))] for name in sorted(validated)}
        unread = projects(ctx).notes if any(definition(ctx, n).projects for n in names) else []
        return Plan(subjects=tuple(layout.subject(n) for n in names), holds={"checks": held},
                    steps=tuple(steps), issues=list(unread))   # what each validate runs, shown with the plan

    def observe(self, req: InstallRequest, ctx: Context) -> dict:
        """Each requested environment's install basis: every one re-observed before any is touched."""
        return {name: _install_basis(ctx, name) for name in _requested(req, ctx)}

    def apply(self, plan: Plan, ctx: Context, observer) -> InstallOutcome:
        from femkit.envs.install import KILLED, MAKES, run_step, target
        results, status, issues = [], "done", []
        for name, basis in plan.basis.items():
            if status == "failed":
                results.append(EnvResult(name=name, status="not reached"))
                continue
            mine = tuple(s.model_copy(update={"id": s.id.split("/", 1)[1]}) for s in plan.steps if s.id.startswith(f"{name}/"))
            env_status, where, killed, outcomes, validated = "done", None, [], [], None
            if mine:
                t = target(ctx, name)
                sub = plan.model_copy(update={"subjects": (layout.subject(name),), "steps": mine,
                                              "basis": {"install_fingerprint": t.install_fingerprint}})

                def do(step, where):
                    nonlocal outcomes, validated, t
                    if step.id == "validate":  # envs.md § 4.1: its own operation, shown under this step
                        ran, validated, outcomes = checks.run_validation(
                            ctx, name, False, tuple(Step.model_validate(s) for s in plan.holds["checks"][name]),
                            observer)
                        return ran, validated  # done once every check ran, whatever its verdict
                    outcome, log = run_step(t, step, where, observer.note, observer.step_log)
                    if step.id in MAKES:    # where the environment is now, asked of the manager (envs.md § 4.1)
                        t = target(ctx, name)
                    if outcome == KILLED:
                        killed.append(step.id)
                    return outcome, log

                env_status, where = run_steps(sub, ctx, observer, do)
                if killed:
                    issues.append(_killed(ctx, name, killed))
            after, state = observe(ctx, name)
            results.append(EnvResult(name=name, status=env_status if mine else "nothing to do", state=state.value,
                                     log=str(where) if where else None,
                                     validation=str(validated) if validated else None))
            if env_status == "done" and state is not machine(ctx).states.ready:
                issues += _not_ready(ctx, after, state, outcomes)
            status = "failed" if env_status == "failed" else status
        return InstallOutcome(plan=plan, status=status, environments=results, issues=issues,
                              next=[view.command(ENV_LOG, name=e.name) for e in results if e.status == "failed"])


# ------------------------------------------------------------------ env validate

class ValidateOutcome(Outcome):
    name: str = Field(default="", description="the environment")
    state: str | None = Field(default=None, description="its state afterwards", json_schema_extra={"doc": "envs.md § 3.2"})
    gpu: Gpu | None = Field(default=None, description="its GPU qualification afterwards",
                            json_schema_extra={"doc": "envs.md § 5"})
    outcomes: list[CheckOutcome] = Field(default_factory=list, description="every recorded check outcome")

    @property
    def report(self) -> view.Report:
        head = f"{self.name}: {self.state or 'not validated'}"
        return view.Report(blocks=[view.Text(text=head + (f", GPU {self.gpu}" if self.gpu else "")), view.Table.of(
            CheckOutcome, [{"outcome": o.outcome, "id": o.id, "reason": o.reason,
                            "log": text.path(o.log) if o.log and o.outcome == "failed" else ""}
                           for o in self.outcomes], "outcome", "id", "reason", "log")])


@operation(ENV_VALIDATE, result=ValidateOutcome, subject=lambda req: [layout.subject(req.name)])
class EnvValidate:
    """Run an environment's checks and record whether it is ready."""

    @staticmethod
    def _basis(f, state, ctx: Context) -> dict:
        return {"state": state.value, "install_fingerprint": f.install_fingerprint,
                "check_fingerprint": f.check_fingerprint, "prefix": str(f.prefix) if f.prefix else None,
                "launcher": settings.load(ctx).config.launch.mpi}   # in the checks' commands

    def plan(self, req: ValidateRequest, ctx: Context) -> Plan:
        f, state = observe(ctx, req.name)
        env = definition(ctx, req.name)
        chosen = checks.selected(env, req.gpu)
        if req.gpu and not any(c.device for c in chosen):  # envs.md § 5: nothing to run, whatever its state
            cuda = catalogue.with_gpus(ctx, req.name, gpus=1)   # its CUDA environment (definitions.md § 4.5)
            if cuda is not None:
                raise UsageError(f"{req.name} is built without CUDA; its CUDA build is {cuda}",
                                 (view.command(ENV_VALIDATE, name=cuda, gpu=True),), code="no-gpu-check",
                                 subject=req.name)
            raise UsageError(f"{req.name} declares no GPU check", (view.command(ENV_VALIDATE, name=req.name),),
                             code="no-gpu-check", subject=req.name)
        require(ctx, f, state, VALIDATE_GPU if req.gpu else "validate")  # envs.md § 3.3
        alone(req.name)
        checks.refusals(ctx, chosen)
        return Plan(steps=tuple(checks.steps(checks.runner(ctx, req.name), chosen)))

    def observe(self, req: ValidateRequest, ctx: Context) -> dict:
        f, state = observe(ctx, req.name)
        return self._basis(f, state, ctx)

    def apply(self, plan: Plan, ctx: Context, observer) -> ValidateOutcome:
        req = ValidateRequest.model_validate(plan.request)
        status, where, outcomes = checks.run_validation(ctx, req.name, req.gpu, plan.steps, observer)
        f, state = observe(ctx, req.name)
        issues = []
        if state is not machine(ctx).states.ready:  # with --gpu too: a CPU partner it ran again may fail
            issues += _not_ready(ctx, f, state, outcomes)
        if req.gpu and f.gpu != QUALIFIED:
            issues.append(Issue(severity="error", code="gpu-not-qualified", subject=req.name,
                                message=f"the GPU path is {f.gpu}"))
            issues += _failed_checks(req.name, outcomes, f.device_checks)
        return ValidateOutcome(plan=plan, status=status, log=str(where), name=req.name, state=state.value,
                               gpu=gpu(ctx, f, state), outcomes=outcomes, issues=issues)
