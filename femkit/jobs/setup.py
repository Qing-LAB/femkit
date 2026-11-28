"""This machine's setup: `doctor` and `env bootstrap` (envs.md § 6.1, § 6.2).

They live in `jobs`, the top domain, because both read or write this machine's record
(jobs.md § 9) besides the configuration and the environments below it. `env bootstrap`
does configuration first, every default environment
installed one after another — a failed one does not stop the next — this machine's
record, then `doctor`, the entry line, and one verdict.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal
from pathlib import Path

from pydantic import Field

from femkit.config import settings
from femkit.config.operations import ConfigInit
from femkit.config.probe import place
from femkit.config.requests import CONFIG_INIT
from femkit.core import dirs, text, view
from femkit.core.errors import Refusal, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.schema import DefinitionError, Model, closed
from femkit.definitions import catalogue
from femkit.envs import control
from femkit.envs.manager import form, resolve
from femkit.envs.operations import EnvInstall, default_environments
from femkit.envs import state as env_state
from femkit.jobs import prepare, record
from femkit.jobs.operations import JobProbe
from femkit.jobs.record import LOCAL
from femkit.jobs.requests import BootstrapRequest, DoctorRequest
from femkit.envs.requests import ENV_LOG
from femkit.jobs.requests import DOCTOR, ENV_BOOTSTRAP


# ------------------------------------------------------------------ doctor

class DoctorRow(Model):
    subject: str = Field(description="what is checked")
    state: str = Field(description="its state, as its machine observes it; for config.toml, whether it is found")
    detail: str = Field(default="", description="what the state rests on, or why it could not be observed")
    ready: bool = Field(description="whether it is ready")
    next: list[view.Action] = Field(default_factory=list, description="what makes it ready")


class DoctorResult(Result):
    rows: list[DoctorRow] = Field(description="every subject doctor checks, each with its state and what makes it "
                                              "ready", json_schema_extra={"doc": "envs.md § 6.1"})

    def ok(self) -> bool:
        return all(r.ready for r in self.rows) and super().ok()

    @property
    def report(self) -> view.Report:
        return view.Report(blocks=[
            view.Text(text="this machine is ready" if self.ok() else "this machine is not ready"),
            view.Table.of(DoctorRow, [{"ready": "-" if r.ready else "!", "subject": r.subject, "state": r.state,
                                       "detail": r.detail} for r in self.rows], "ready", "subject", "state", "detail"),
            *(view.Next(label=f"for {r.subject}", actions=r.next) for r in self.rows if not r.ready and r.next)])


CONTROL = "control environment"   # doctor's row for it
UNKNOWN = "unknown"             # a row that cannot be observed: its detail says why (envs.md § 6.1)


def _control_row(ctx: Context) -> DoctorRow:
    """The control environment, observed by the rules `femkit/data/states/control.toml` declares
    (envs.md § 7.2) in the prefix the manager lists under its name, ready when current, with the
    command its state allows (§ 7.3); `unknown` while no manager is named to ask where it is."""
    m = control.machine(ctx)
    try:
        facts, state = control.observe(ctx)
    except Refusal as exc:
        return DoctorRow(subject=CONTROL, state=UNKNOWN, detail=str(exc), ready=False, next=list(exc.next))
    detail = ("" if not facts.prefix else "no femkit command" if facts.launcher is None
              else ("femkit runs this checkout" if facts.linked else
                    f"femkit runs this checkout, and {text.path(control.link())} does not link it")
              if facts.launcher == facts.ours
              else "an older form of the femkit command" if control.names_this_checkout(facts.launcher)
              else "femkit runs another checkout")
    return DoctorRow(subject=CONTROL, state=state.value, detail=detail,
                     ready=state is m.states.current, next=list(m.next(state, facts)))


def _config_row(loaded: settings.Loaded) -> DoctorRow:
    """config.toml: there, and stating how this machine enters an environment; while a key of it is
    unset, `config init`, which asks for it in words (workflow.md § 7; config.md § 3.2)."""
    unset = settings.unstated(loaded.config, record.COPIED)
    return DoctorRow(
        subject="config.toml", state="found" if loaded.file else "absent",
        detail=", ".join(f"{d} {'unset' if d in unset else 'stated'}" for d in settings.person_states(record.COPIED)),
        ready=loaded.file is not None and not unset, next=list(settings.steps(unset)))


def _record_row(ctx: Context, config: settings.UserConfig) -> DoctorRow:
    """This machine's record: present, loads, and not stale (jobs.md § 9.3); while it is not, what
    writes it, from the one source every reader of it says it from — `config init` first while a
    key a person states is unset, since the probe is refused until then (`prepare.record_steps`)."""
    m = record.machine(ctx)
    state, detail, _ = record.status(ctx, record.path(LOCAL), config)
    ready = state is m.states.current
    return DoctorRow(subject=RECORD, state=state.value, detail=detail, ready=ready,
                     next=[] if ready else list(prepare.record_steps(ctx, LOCAL)))


RECORD = "this machine's record"   # doctor's row for it, and the part bootstrap writes last
ENGINES = "engine environments"  # the one row for them all while none can be observed


@operation(DOCTOR, result=DoctorResult)
def doctor(req: DoctorRequest, ctx: Context) -> DoctorResult:
    """Whether this machine is ready: control environment, configuration, this machine's record, every engine environment."""
    rows = [_control_row(ctx)]
    try:
        loaded = settings.load(ctx)
    except DefinitionError as exc:  # said as the row's state: doctor always reports (envs.md § 6.1)
        unloaded = "config.toml does not load"
        return DoctorResult(rows=[*rows, DoctorRow(subject="config.toml", state="does not load", detail=exc.summary(),
                                                   ready=False),
                                  DoctorRow(subject=RECORD, state=UNKNOWN, detail=unloaded, ready=False),
                                  DoctorRow(subject=ENGINES, state=UNKNOWN, detail=unloaded, ready=False)])
    rows += [_config_row(loaded), _record_row(ctx, loaded.config)]
    try:
        resolve(ctx)  # every environment's install fingerprint names the manager's kind
    except Refusal as exc:
        return DoctorResult(rows=[*rows, DoctorRow(subject=ENGINES, state=UNKNOWN, detail=str(exc), ready=False,
                                                   next=list(exc.next))])
    m = env_state.machine(ctx)
    for name, env in catalogue.load(ctx).environments.items():
        f, state = env_state.observe(ctx, name)
        on_request = not env.default and state is m.states.absent  # never installed: not this machine's lack
        deliver = env_state.delivering(ctx, f, state)   # what the projects add that it lacks (envs.md § 6.1)
        ready = (state is m.states.ready or on_request) and not deliver
        detail = "installed on request" if on_request else \
            f"to deliver: {', '.join(deliver)}" if deliver else \
            f"a folder of its name the manager does not list: {text.path(f.orphan)}" if f.orphan else ""
        rows.append(DoctorRow(subject=name, state=state.value, detail=detail, ready=ready,
                              next=[] if ready else list(env_state.step(ctx, name, state, env_state.INSTALL))
                              if deliver else list(m.next(state, f))))
    return DoctorResult(rows=rows)


# ------------------------------------------------------------------ env bootstrap


class BootstrapRow(Model):
    part: str = Field(description="config.toml, an environment, or this machine's record")
    status: Literal["done", "failed", "killed", "refused", "left alone"] = Field(description="how the part ended")
    detail: str = Field(default="", description="its state afterwards, its file, or why it did not finish")
    log: str | None = Field(default=None, description="its operation directory")


class BootstrapOutcome(Outcome):
    rows: list[BootstrapRow] = Field(default_factory=list, description="each part, in order")
    doctor: DoctorResult | None = Field(default=None, description="doctor, run last")
    entry: list[view.Action] = Field(default_factory=list, description="the lines that enter femkit day to day here")

    def ok(self) -> bool:
        return super().ok() and self.doctor is not None and self.doctor.ok()

    @property
    def report(self) -> view.Report:
        failed = [r.part for r in self.rows if r.status not in ("done", "left alone")]
        problems = ([f"{text.count(len(failed), 'part')} did not finish ({', '.join(failed)})"]
                    if failed else []) + (["doctor reports a problem"] if self.doctor and not self.doctor.ok() else [])
        blocks = [view.Text(text="bootstrap did not finish: " + "; ".join(problems) if problems
                            else "bootstrap complete: every part done and this machine is ready"),
                  view.Table.of(BootstrapRow, [{"part": r.part, "status": r.status, "detail": r.detail,
                                                "log": r.log or ""} for r in self.rows],
                                "part", "status", "detail", "log")]
        if self.doctor is not None:
            verdict, *rest = self.doctor.report.blocks
            blocks += [view.Text(text=f"doctor: {verdict.text}"), *rest]
        if self.entry:
            blocks.append(view.Next(label="enter femkit day to day on this machine", actions=self.entry))
        return view.Report(blocks=blocks)


def _as_bootstrap(issue: Issue) -> Issue:
    """A config init finding as bootstrap says it: bootstrap takes config init's options, so
    the `config init …` it names is `env bootstrap …`."""
    def as_bootstrap(step: view.Action) -> view.Action:
        if step.call is None or step.call.operation != CONFIG_INIT.name:
            return step
        return view.command(ENV_BOOTSTRAP, note=step.note, fills=step.fills, **step.call.request)
    return issue.model_copy(update={"next": tuple(as_bootstrap(n) for n in issue.next)})


def _login_node(ctx: Context, req: BootstrapRequest) -> list[Issue]:
    """A machine with a scheduler, outside any job: most likely a login node, whose limits
    kill large builds (envs.md § 6.2)."""
    here = place(catalogue.schedulers(ctx), ctx.env)
    if here.where != "login node" or not here.kind.interactive:
        return []
    return [Issue(severity="warning", code="login-node", subject=here.scheduler,
                  message=f"this {here.scheduler} machine runs no job here, so this is most likely a login node, "
                          "whose limits kill large builds; run bootstrap inside an interactive allocation",
                  next=(view.shell(here.kind.interactive, note="an interactive allocation"),
                        view.command(ENV_BOOTSTRAP, note="inside it", **req.model_dump(exclude_defaults=True))))]


def _enters(ctx: Context, req: BootstrapRequest, command: str | None) -> None:
    """Refused before anything runs: no manager named, which every environment is found and made by
    (envs.md §§ 1, 7.1); an `activation.command` the named manager's kind has no form of, since the
    entry lines bootstrap ends with, and every run script here, enter an environment by it
    (config.md § 3.1; envs.md § 6.2)."""
    m = resolve(ctx)
    if command is None or form(m.kind, command) is not None:
        return
    forms = [f for f in closed(settings.key(settings.COMMAND).annotation) if form(m.kind, f) is not None]
    given = req.model_dump(exclude_defaults=True)
    instead = ([view.command(ENV_BOOTSTRAP, **{**given, "command": f}) for f in forms] if "command" in given else
               list(settings.setting_to(settings.COMMAND, forms)))
    raise UsageError(f"{settings.COMMAND} `{command}` is no form of the {m.kind_name} kind's: it enters an "
                     f"environment by {', '.join(f'`{f}`' for f in forms)}", tuple(instead),
                     code="activation-unusable", subject=settings.COMMAND)


def entry_lines(ctx: Context, config: settings.UserConfig) -> list[view.Action]:
    """The lines that enter femkit's control environment as a person enters any of the manager's,
    which a new shell does not need (envs.md § 6.2): the preamble, then the activation the person
    stated of the control environment, by its name — which puts `femkit` on the path too — both
    written by the one writer of an environment's entry lines (`manager.entering`), or, while the
    activation is unstated, the step that states it; then `femkit doctor`. The lines are written
    with the manager's kind: refused while the invocation names none."""
    command = config.activation.command
    enter = [view.shell(line) for line in resolve(ctx).activation(catalogue.managed(ctx, dirs.CONTROL),
                                                                   config.activation.preamble or (), command)]
    return [*enter, *(() if command else settings.steps([settings.COMMAND])), view.command(DOCTOR)]


@operation(ENV_BOOTSTRAP, result=BootstrapOutcome, subject=lambda req: ["bootstrap"])
class EnvBootstrap:
    """Set up this machine: config init, every default environment installed (a failed one does not stop the next), this machine's record, then doctor."""

    def plan(self, req: BootstrapRequest, ctx: Context) -> Plan:
        init = ConfigInit.request.model_validate(req.model_dump(exclude={"clean"}))
        config_plan = ConfigInit.plan(init, ctx)
        values = config_plan.holds["values"]
        planned = settings.as_planned(ctx, values)  # every install is planned against config.toml as it will be
        _enters(ctx, req, settings.load(planned).config.activation.command)
        steps, issues = [], [_as_bootstrap(i) for i in config_plan.issues]
        if config_plan.steps:
            added = [s.id.removeprefix("add:") for s in config_plan.steps]  # config init's steps, without their whys
            steps.append(Step(id="config", describe="config.toml: add " + "; ".join(
                f"{k} = {text.show(values[k])}" for k in added)))
        installs, refused = {}, {}
        for name in default_environments(ctx):
            try:
                sub = EnvInstall.plan(EnvInstall.request(names=[name], clean=req.clean), planned)
            except Refusal as exc:  # said now, not after the other installs
                refused[name] = str(exc)
                issues.append(Issue.of(exc, "error", f"{name} will not be installed: {exc}"))
                continue
            if not sub.steps:
                issues.append(Issue(severity="info", code="ready", subject=name, message=f"{name} is ready; left alone"))
                continue
            installs[name] = sub.model_dump(mode="json")
            f, state = env_state.observe(planned, name)
            steps.append(Step(id=f"install:{name}", describe=f"install {name} ({state.value}) as "
                                                             f"{catalogue.managed(ctx, name)}: "
                                                             f"{text.count(len(sub.steps), 'step')}"))
        if installs:
            issues += _login_node(ctx, req)
        will_be = settings.load(planned).config
        file = record.path(LOCAL)
        m = record.machine(ctx)
        state, _, f = record.status(ctx, file, will_be)
        # What bootstrap does to the record is what its table gives the record's state (jobs.md § 9.3;
        # core.md § 7): a current one is measured again only where environments are installed,
        # which it would list as they were.
        why = [m.tasks[t] for t in m.does(state, replace(f, installs=bool(installs)))]
        probe: Plan | None = None
        if not why:   # its step, measuring it again, the one its table's row gives its state
            issues.append(Issue(severity="info", code="record-kept", subject=RECORD,
                                message=f"this machine's record is kept: {text.path(file)}", next=m.next(state, f)))
        elif not settings.unstated(will_be, record.COPIED):   # while unset, config init's findings say the probe is refused
            try:   # measured now, so what it could not measure and how it differs are shown before consent
                probe = JobProbe.plan(JobProbe.request(write=True), planned)
            except Refusal as exc:
                refused[RECORD] = str(exc)
                issues.append(Issue.of(exc, "error", f"this machine's record will not be written: {exc}"))
            else:
                issues += probe.issues
                steps.append(Step(id="record", describe=f"{why[0]}, {text.path(file)}"))
        return Plan(holds={"config_plan": config_plan.model_dump(mode="json"), "installs": installs,
                           "refused": refused, "probe": probe.model_dump(mode="json") if probe else None},
                    steps=tuple(steps), issues=issues, asks=config_plan.asks)

    def observe(self, req: BootstrapRequest, ctx: Context) -> dict:
        """What the plan decided on: the keys config.toml holds, each default environment's
        state, and this machine's record — each part's own apply checks its own besides."""
        return {"present": sorted(settings.load(ctx, fresh=True).present()),
                "environments": {name: env_state.observe(ctx, name)[1].value for name in default_environments(ctx)},
                "record": record.sha256(record.path(LOCAL))}

    def apply(self, plan: Plan, ctx: Context, observer) -> BootstrapOutcome:
        config_plan = Plan.model_validate(plan.holds["config_plan"])
        rows = [BootstrapRow(part=name, status="refused", detail=why) for name, why in plan.holds["refused"].items()]
        issues: list[Issue] = []   # the plan's findings come with the outcome, carried by the runner (api.md § 4.4)

        def again() -> Context:
            return ctx.fresh()  # a new invocation's view: reads config.toml as written

        def do(step: Step, where: Path):
            if step.id == "config":
                out = ConfigInit.apply(config_plan, ctx, observer)
                rows.append(BootstrapRow(part="config.toml", status=out.status, detail=text.path(out.file), log=out.log))
                return out.status, Path(out.log) if out.log else None
            if step.id.startswith("install:"):
                name = step.id.split(":", 1)[1]
                try:  # the install plan shown, applied as the config now written reads (PlanStale otherwise)
                    out = EnvInstall.apply(Plan.model_validate(plan.holds["installs"][name]), again(), observer)
                except Refusal as exc:
                    rows.append(BootstrapRow(part=name, status="refused", detail=str(exc)))
                    issues.append(Issue.of(exc, "error", f"{name}: {exc}"))
                    return "failed", None   # the step did not do its work; the next one still runs
                env = out.environments[0]
                status = "killed" if any(i.code == "killed" for i in out.issues) else \
                    "done" if out.ok() else "failed"
                rows.append(BootstrapRow(part=name, status=status, detail=env.state or "",
                                         log=env.validation or env.log))
                issues.extend(out.issues)
                if env.status == "failed":
                    issues.append(Issue(severity="error", code="failed", subject=name, message=f"{name}: a step failed",
                                        next=(view.command(ENV_LOG, name=name),)))
                return status, Path(env.log) if env.log else None
            c = again()  # the record: after the installs, so its environments are what is here now
            try:     # measured again: what it could not measure, and each difference from the record there
                out = JobProbe.apply(JobProbe.plan(JobProbe.request(write=True), c), c, observer)
            except Refusal as exc:
                rows.append(BootstrapRow(part=RECORD, status="refused", detail=str(exc)))
                issues.append(Issue.of(exc, "error"))
                return "failed", None
            rows.append(BootstrapRow(part=RECORD, status=out.status, detail=text.path(out.file) if out.file else "",
                                     log=out.log))
            issues.extend(out.issues)
            return out.status, Path(out.log) if out.log else None

        status, where = run_steps(plan, ctx, observer, do, keep_going=True)
        rows += [BootstrapRow(part=i.subject, status="left alone", detail="ready") for i in plan.issues if i.code == "ready"]
        order = ["config.toml", *default_environments(ctx), RECORD]
        rows.sort(key=lambda r: order.index(r.part))
        c = again()
        entry = entry_lines(c, settings.load(c).config)   # its manager named, as its plan required
        return BootstrapOutcome(plan=plan, status=status, log=str(where), rows=rows, issues=issues,
                                doctor=doctor.run(doctor.request(), c), entry=entry)
