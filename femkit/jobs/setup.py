"""This machine's setup: `doctor` and `env bootstrap` (envs.md § 6.1, § 6.2).

They live in `jobs`, the top domain, because both read or write this machine's record
(jobs.md § 9) besides the configuration and the environments below it. `env bootstrap`
does configuration first, every default environment
installed one after another — a failed one does not stop the next — this machine's
record, then `doctor`, the entry line, and one verdict.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from femkit.config import settings
from femkit.config.operations import ConfigInit, stating, where_environments_go
from femkit.config.probe import place
from femkit.config.requests import CONFIG_INIT
from femkit.core import dirs, persist, states, text, view
from femkit.core.errors import Refusal
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.schema import DefinitionError, Model
from femkit.definitions import catalogue
from femkit.envs import layout
from femkit.envs.manager import resolve
from femkit.envs.operations import EnvInstall, default_environments
from femkit.envs import state as env_state
from femkit.jobs import record
from femkit.jobs.operations import JobProbe
from femkit.jobs.record import LOCAL
from femkit.jobs.requests import BootstrapRequest, DoctorRequest
from femkit.envs.requests import ENV_LOG
from femkit.jobs.requests import DOCTOR, ENV_BOOTSTRAP, JOB_PROBE


# ------------------------------------------------------------------ doctor

class DoctorRow(Model):
    subject: str = Field(description="what is checked")
    state: str = Field(description="its state")
    ready: bool = Field(description="whether it is ready")
    next: list[view.Action] = Field(default_factory=list, description="what makes it ready")


class DoctorResult(Result):
    rows: list[DoctorRow] = Field(description="every subject of envs.md § 6.1")

    def ok(self) -> bool:
        return all(r.ready for r in self.rows) and super().ok()

    def report(self) -> view.Report:
        return view.Report(blocks=[
            view.Text(text="this machine is ready" if self.ok() else "this machine is not ready"),
            view.Table(columns=view.columns("mark", "subject", "state"),
                       rows=[{"mark": "-" if r.ready else "!", "subject": r.subject, "state": r.state}
                             for r in self.rows]),
            *(view.Next(label=f"for {r.subject}", actions=r.next) for r in self.rows if not r.ready and r.next)])


CONTROL_STAMP = "control.sha256"  # in the control prefix's records; written last by the install script
LAUNCHER = Path("bin") / "femkit"  # in the control prefix: the `femkit` command the install script writes (envs.md § 7)
LAUNCHER_SOURCE = "launcher.sh"    # in femkit/data/: that command's one source, which the install script fills


def shell_word(value: str) -> str:
    """``value`` as one single-quoted shell word, each `'` in it written `'\\''`: as the install
    script quotes what it fills the launcher's text with."""
    return "'" + value.replace("'", "'\\''") + "'"


def launcher_text(checkout: Path, python: Path) -> str:
    """The `femkit` command that runs femkit from ``checkout`` on ``python`` (envs.md § 7):
    femkit/data/launcher.sh with `{checkout}` and then `{python}` each replaced by a shell word,
    as the install script fills it."""
    source = catalogue.shipped(catalogue.data_root() / LAUNCHER_SOURCE)
    return source.replace("{checkout}", shell_word(str(checkout))).replace("{python}", shell_word(str(python)))


@dataclass(frozen=True)
class ControlFacts:
    """What is observed of the control environment (envs.md § 7.2), and its `femkit` command (§ 7)."""

    prefix: bool           # the control prefix is there
    environment: bool      # it holds conda-meta/
    python: bool           # its bin/python can be run
    stamp: str | None      # the stamp's text; None: no stamp
    digest: str | None     # the SHA-256 of channels.txt then control.txt, read beside a stamp
    launcher: bytes | None   # its `femkit` command's bytes (envs.md § 7); None: there is none


CONTROL_BINDING = states.Binding("control", {
    "prefix": lambda f: f.prefix,
    "environment": lambda f: f.environment,
    "python": lambda f: f.python,
    "stamp": lambda f: f.stamp is not None,
    "stamp_matches": lambda f: f.stamp is not None and f.stamp.strip() == f.digest,
}, reads=frozenset({"current"}))


def control_facts() -> ControlFacts:
    """The control environment's facts, read from its prefix as the install script reads them."""
    prefix = dirs.control_prefix()
    stamp = persist.read_text(layout.records(prefix) / CONTROL_STAMP)   # None: there is none
    return ControlFacts(prefix=prefix.exists(), environment=(prefix / "conda-meta").is_dir(),
                        python=os.access(prefix / "bin" / "python", os.X_OK), stamp=stamp,
                        digest=catalogue.control_digest() if stamp is not None else None,
                        launcher=persist.read_bytes(prefix / LAUNCHER))


def _control_row(ctx: Context) -> DoctorRow:
    """The control environment, observed by the rules `femkit/data/states/control.toml` declares
    (envs.md § 7.2), with the command its state allows (§ 7.3); a current one is ready when its
    `femkit` command is the one the install script writes from this checkout (§ 7), and its row
    says whether it is."""
    m = catalogue.machine(ctx, CONTROL_BINDING)
    facts = control_facts()
    state = m.observe(facts)
    shown, ready = state.value, False
    if state is m.states.current:
        prefix = dirs.control_prefix()
        ours = launcher_text(dirs.checkout(), prefix / "bin" / "python").encode("utf-8", "surrogateescape")
        ready = facts.launcher == ours
        shown += (", femkit runs this checkout" if ready else ", no femkit command" if facts.launcher is None
                  else ", femkit is not this checkout's")
    return DoctorRow(subject="control environment", state=shown, ready=ready,
                     next=[] if ready else list(m.next(state, dirs.CONTROL)))


def _config_row(loaded: settings.Loaded) -> DoctorRow:
    unset = settings.unstated(loaded.config)
    return DoctorRow(
        subject="config.toml",
        state=("found" if loaded.file else "absent") + "".join(
            f", {d} {'unset' if d in unset else 'stated'}" for d in settings.STATED),
        ready=loaded.file is not None and not unset, next=list(stating(CONFIG_INIT, unset)))


def _record_row(ctx: Context, config: settings.UserConfig) -> DoctorRow:
    """This machine's record: present, loads, and not stale (jobs.md § 9.3). The probe that
    writes it is refused while a key a person states is unset, so that comes first."""
    m = record.machine(ctx)
    state, detail = record.status(ctx, record.path(LOCAL), config)
    if state is m.states.current:
        return DoctorRow(subject="this machine's record", state=state.value, ready=True)
    first = list(stating(CONFIG_INIT, settings.unstated(config)))
    return DoctorRow(subject="this machine's record", state=f"{state.value}: {detail}" if detail else state.value,
                     ready=False, next=[*first, *m.next(state, LOCAL)])


ENGINES = "engine environments"  # the one row for them all while none can be observed


@operation(DOCTOR, result=DoctorResult)
def doctor(req: DoctorRequest, ctx: Context) -> DoctorResult:
    """Whether this machine is ready: control environment, configuration, this machine's record, every engine environment."""
    rows = [_control_row(ctx)]
    try:
        loaded = settings.load(ctx)
    except DefinitionError as exc:  # said as the row's state: doctor always reports (envs.md § 6.1)
        unknown = "unknown: config.toml does not load"
        return DoctorResult(rows=[*rows, DoctorRow(subject="config.toml", state=f"does not load: {exc.summary()}",
                                                   ready=False),
                                  DoctorRow(subject="this machine's record", state=unknown, ready=False),
                                  DoctorRow(subject=ENGINES, state=unknown, ready=False)])
    rows += [_config_row(loaded), _record_row(ctx, loaded.config)]
    try:
        resolve(ctx)  # every environment's install fingerprint names the manager's kind
    except Refusal as exc:
        return DoctorResult(rows=[*rows, DoctorRow(subject=ENGINES, state=f"unknown: {exc}", ready=False,
                                                   next=list(exc.next))])
    m = env_state.machine(ctx)
    for name, env in catalogue.load(ctx).environments.items():
        _, state = env_state.observe(ctx, name)
        on_request = not env.default and state is m.states.absent  # never installed: not this machine's lack
        rows.append(DoctorRow(subject=name, state=state.value + (", installed on request" if on_request else ""),
                              ready=state is m.states.ready or on_request,
                              next=[] if state is m.states.ready or on_request else list(m.next(state, name))))
    return DoctorResult(rows=rows)


# ------------------------------------------------------------------ env bootstrap

class BootstrapRow(Model):
    part: str = Field(description="config.toml, an environment, or this machine's record")
    status: str = Field(description="done, failed, killed, refused, or left alone")
    detail: str = Field(default="", description="its state afterwards, its file, or why it did not finish")
    log: str | None = Field(default=None, description="its operation directory")


class BootstrapOutcome(Outcome):
    rows: list[BootstrapRow] = Field(default_factory=list, description="each part, in order")
    doctor: DoctorResult | None = Field(default=None, description="doctor, run last")
    entry: list[view.Action] = Field(default_factory=list, description="the lines that enter femkit day to day here")

    def ok(self) -> bool:
        return super().ok() and self.doctor is not None and self.doctor.ok()

    def report(self) -> view.Report:
        failed = [r.part for r in self.rows if r.status not in ("done", "left alone")]
        problems = ([f"{text.count(len(failed), 'part')} did not finish ({', '.join(failed)})"]
                    if failed else []) + (["doctor reports a problem"] if self.doctor and not self.doctor.ok() else [])
        blocks = [view.Text(text="bootstrap did not finish: " + "; ".join(problems) if problems
                            else "bootstrap complete: every part done and this machine is ready"),
                  view.Table(columns=view.columns("part", "status", "detail", "log"),
                             rows=[{"part": r.part, "status": r.status, "detail": r.detail, "log": r.log or ""}
                                   for r in self.rows])]
        if self.doctor is not None:
            verdict, *rest = self.doctor.report().blocks
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


def _login_node(ctx: Context) -> list[Issue]:
    """A machine with a scheduler, outside any job: most likely a login node, whose limits
    kill large builds (envs.md § 6.2)."""
    here = place(catalogue.schedulers(ctx), ctx.env)
    if here.where != "login node" or not here.kind.interactive:
        return []
    return [Issue(severity="warning", code="login-node", subject=here.scheduler,
                  message=f"this {here.scheduler} machine runs no job here, so this is most likely a login node, "
                          "whose limits kill large builds; run bootstrap inside an interactive allocation",
                  next=(view.shell(here.kind.interactive, note="then, inside it: bash scripts/install-env.sh bootstrap"),))]


def entry_lines(ctx: Context, config: settings.UserConfig) -> list[view.Action]:
    """This machine's day-to-day entry (envs.md § 6.2): the preamble, the activation the person
    stated for the real control prefix — which puts `femkit` on the path, for any folder — and
    `femkit doctor`. A stated activation is written with the manager's kind: refused while the
    invocation names none."""
    command = config.activation.command
    enter = [view.shell(line) for line in resolve(ctx).activation(dirs.control_prefix(), command)] if command else [
        a.model_copy(update={"note": f"activation.command is unset; {a.note}"})
        for a in stating(CONFIG_INIT, [settings.COMMAND])]
    return [*(view.shell(line) for line in config.activation.preamble or []), *enter, view.command(DOCTOR)]


@operation(ENV_BOOTSTRAP, result=BootstrapOutcome, changes=True,
           subject=lambda req: ["bootstrap"])
class EnvBootstrap:
    """Set up this machine: config init, every default environment installed (a failed one does not stop the next), this machine's record, then doctor."""

    def plan(self, req: BootstrapRequest, ctx: Context) -> Plan:
        init = ConfigInit.request.model_validate(req.model_dump(exclude={"clean"}))
        config_plan = ConfigInit.plan(init, ctx)
        values = config_plan.holds["values"]
        planned = settings.as_planned(ctx, values)  # every install is planned against config.toml as it will be
        steps, issues = [], [_as_bootstrap(i) for i in config_plan.issues
                             if i.code != "stated-unset"]  # said below, with what it blocks
        if config_plan.steps:
            added = [s.id.removeprefix("add:") for s in config_plan.steps]  # config init's steps, without their whys
            steps.append(Step(id="config", describe="config.toml: add " + "; ".join(
                f"{k} = {text.show(values[k])}" for k in added)))
        if not any(i.code == "default" for i in issues):
            root = settings.environments_root(settings.load(planned).config)
            issues.append(Issue(severity="info", code="environments", subject="paths.environments",
                                message=f"environments go to {where_environments_go(root)}"))
        installs, refused = {}, {}
        for name in default_environments(ctx):
            try:
                sub = EnvInstall.plan(EnvInstall.request(names=[name], clean=req.clean), planned)
            except Refusal as exc:  # said now, not after the other installs
                refused[name] = str(exc)
                issues.append(Issue(severity="error", code="refused", subject=name,
                                    message=f"{name} will not be installed: {exc}", next=exc.next))
                continue
            if not sub.steps:
                issues.append(Issue(severity="info", code="ready", subject=name, message=f"{name} is ready; left alone"))
                continue
            installs[name] = sub.model_dump(mode="json")
            f, state = env_state.observe(planned, name)
            steps.append(Step(id=f"install:{name}", describe=f"install {name} ({state.value}) into {text.path(f.prefix)}: "
                                                             f"{text.count(len(sub.steps), 'step')}"))
        if installs:
            issues += _login_node(ctx)
        will_be = settings.load(planned).config
        file = record.path(LOCAL)
        m = record.machine(ctx)
        state, detail = record.status(ctx, file, will_be)
        why = {m.states.absent: "a new record", m.states.stale: f"measured again: stale, {detail}",
               m.states.unloadable: "measured again: the file there does not load",
               m.states.current: "measured again: environments are installed" if installs else ""}[state]
        if not why:
            issues.append(Issue(severity="info", code="record-kept", subject=str(file),
                                message=f"this machine's record is kept: {file}",
                                next=(view.command(JOB_PROBE, write=True, note="to measure it again"),)))
        elif unset := settings.unstated(will_be):
            issues.append(Issue(severity="warning", code="no-record", subject=", ".join(unset),
                                message=f"{' and '.join(unset)} {'stays' if len(unset) == 1 else 'stay'} unset, so this "
                                        "machine's record is not written and no job can be prepared for it",
                                next=stating(ENV_BOOTSTRAP, unset)))
        else:
            steps.append(Step(id="record", describe=f"write this machine's record, {text.path(file)} ({why})"))
        return Plan(holds={"config_plan": config_plan.model_dump(mode="json"), "installs": installs,
                           "refused": refused},
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
        # The plan's findings come with the outcome, as api.md § 4 says for --yes; a ready environment is a
        # row of its own.
        issues: list[Issue] = [i for i in plan.issues if i.code != "ready"]

        def again() -> Context:
            return ctx.fresh()  # a new invocation's view: reads config.toml as written

        def do(step: Step, where: Path):
            if step.id == "config":
                out = ConfigInit.apply(config_plan, ctx, observer)
                rows.append(BootstrapRow(part="config.toml", status=out.status, detail=out.file, log=out.log))
                return out.status, Path(out.log) if out.log else None
            if step.id.startswith("install:"):
                name = step.id.split(":", 1)[1]
                try:  # the install plan shown, applied as the config now written reads (PlanStale otherwise)
                    out = EnvInstall.apply(Plan.model_validate(plan.holds["installs"][name]), again(), observer)
                except Refusal as exc:
                    rows.append(BootstrapRow(part=name, status="refused", detail=str(exc)))
                    issues.append(Issue(severity="error", code="refused", subject=name, message=f"{name}: {exc}",
                                        next=exc.next))
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
            try:
                out = JobProbe.apply(JobProbe.plan(JobProbe.request(write=True), c), c, observer)
            except Refusal as exc:
                rows.append(BootstrapRow(part="this machine's record", status="refused", detail=str(exc)))
                issues.append(Issue(severity="error", code="refused", subject="record", message=str(exc), next=exc.next))
                return "failed", None
            rows.append(BootstrapRow(part="this machine's record", status=out.status, detail=out.file or ""))
            return out.status, None

        status, where = run_steps(plan, ctx, observer, do, keep_going=True)
        rows += [BootstrapRow(part=i.subject, status="left alone", detail="ready") for i in plan.issues if i.code == "ready"]
        order = ["config.toml", *default_environments(ctx), "this machine's record"]
        rows.sort(key=lambda r: order.index(r.part))
        c = again()
        config = settings.load(c).config
        try:
            entry = entry_lines(c, config)
        except Refusal as exc:   # no manager to write the activation with: said, never left out unsaid
            entry = []
            issues.append(Issue(severity="warning", code="no-entry", subject=settings.COMMAND,
                                message=f"the lines that enter femkit day to day here are not written: {exc}",
                                next=exc.next))
        return BootstrapOutcome(plan=plan, status=status, log=str(where), rows=rows, issues=issues,
                                doctor=doctor.run(doctor.request(), c), entry=entry)
