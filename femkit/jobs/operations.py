"""Job operations (jobs.md § 8): the machine record's — `job probe`, `job machines` — and a
folder's and a job's — `job prepare`, `job launch`, `job status`, `job list`, `job cancel`."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from femkit.config import settings
from femkit.core import persist, text, view
from femkit.core.errors import Unstated, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.schema import DefinitionError, Model, pointer
from femkit.jobs import addresses, folders, launch, layout, prepare, probe, record, runs
from femkit.jobs.record import LOCAL, Record, shown
from femkit.jobs.request import JobRequest
from femkit.jobs.requests import (CancelRequest, LaunchRequest, ListRequest, MachinesRequest, PrepareRequest,
                                  ProbeRequest, StatusRequest)
from femkit.jobs.requests import (JOB_CANCEL, JOB_LAUNCH, JOB_LIST, JOB_MACHINES, JOB_PREPARE, JOB_PROBE,
                                  JOB_STATUS)


class PartitionRow(Model):
    """One partition of a record, as a person reads it (jobs.md § 9.1)."""

    partition: str = Field(description="the partition")
    policy: str = Field(description="its limits: MaxTime, MaxCPUsPerNode, its default memory, the QOS it allows and "
                                    "denies")
    nodes: str = Field(description="its nodes, grouped: how many alike, their cores, memory, GPUs and architecture")


class FoundRow(Model):
    """One command the probe looked for (jobs.md § 9.1)."""

    role: str = Field(description="what the command is for")
    where: str = Field(description="where it was found")


class EnvironmentRow(Model):
    """One environment a record lists (jobs.md § 9.1), beside its state here now where it differs."""

    name: str = Field(description="the environment")
    state: str = Field(description="its state when the probe ran", json_schema_extra={"doc": "envs.md § 3.2"})
    gpu: str = Field(description="its GPU qualification, when ready or failing",
                     json_schema_extra={"doc": "envs.md § 5"})
    now: str = Field(description="its state here now, where it differs from the record's")


class SettingRow(Model):
    """One setting a record copies from this machine's config.toml (jobs.md § 9)."""

    key: str = Field(description="the setting, by its dotted key")
    value: str = Field(description="its value, as the record holds it")


class SourceRow(Model):
    """One part of a record, and what measured it (jobs.md § 9.1)."""

    part: str = Field(description="the part of the record, by its dotted path")
    by: str = Field(description="what measured it")


def _record(r: Record, now: dict[str, tuple[str | None, str]] | None = None) -> list[view.Text | view.Table]:
    """A record as a person reads it (api.md § 4.4), every part jobs.md § 9.1 names; ``now``: for a
    record of this machine, each environment whose state here differs from the record's, beside it.
    Each table's columns are its row model's fields."""
    def mib(value) -> str:
        return f"{value} MiB" if isinstance(value, int) else shown(value)

    def gpus(g: record.NodeGroup) -> str:
        if isinstance(g.gpus, dict):
            return "".join(f", {n} {t}" for t, n in g.gpus.items())
        return f", GPUs {shown(g.gpus)}"

    def nodes(p: record.Partition) -> str:
        return "; ".join(f"{g.count}× {shown(g.cores)} cores, {mib(g.memory_mib)}{gpus(g)}, {shown(g.architecture)}"
                         for g in p.node_groups) or "no nodes listed"

    def policy(p: record.Partition) -> str:
        memory = [f"{name} {mib(v)}" for name, v in (("DefMemPerCPU", p.def_mem_per_cpu_mib),
                                                      ("DefMemPerNode", p.def_mem_per_node_mib)) if v is not None]
        return "; ".join([f"MaxTime {shown(p.max_time)}", f"MaxCPUsPerNode {shown(p.max_cpus_per_node)}", *memory,
                          f"AllowQos {shown(p.allow_qos)}", f"DenyQos {shown(p.deny_qos) if p.deny_qos else 'none'}"])

    m, now = r.manager, now or {}
    blocks = [view.Text(text=f"identity: {shown(r.identity)}, measured {r.measured.time} on a {r.measured.where}"),
              view.Text(text=f"host: {r.host.os}, {r.host.architecture}, {shown(r.host.cores)} cores, "
                             f"{mib(r.host.memory_mib)}"),
              *([view.Text(text=f"gpu: {g.model} (compute {g.compute_capability}, {g.memory_mib} MiB)")
                 for g in r.host.gpus] if isinstance(r.host.gpus, list) else
                [view.Text(text=f"gpus: {shown(r.host.gpus)}")]),
              view.Text(text=f"manager: {shown(m.kind)} {shown(m.version)} at {shown(m.path)}; "
                             f"platform {shown(m.platform)}; run enters: {shown(m.run_enters)}"),
              view.Text(text=f"scheduler: {r.scheduler.kind}"),
              view.Table.of(FoundRow, [{"role": role, "where": shown(where)}
                                       for role, where in {**r.scheduler.commands, **r.scheduler.probe}.items()],
                            "role", "where")]
    if not isinstance(r.partitions, dict):
        blocks.append(view.Text(text=f"partitions: {shown(r.partitions)}"))
    elif r.partitions:
        blocks += [view.Text(text="partitions"), view.Table.of(
            PartitionRow, [{"partition": name, "policy": policy(p), "nodes": nodes(p)}
                           for name, p in r.partitions.items()], "partition", "policy", "nodes")]
    if not isinstance(r.queues, list):
        blocks.append(view.Text(text=f"queues: {shown(r.queues)}"))
    elif r.queues:
        blocks += [view.Text(text="queues"), view.Table.of(
            record.Queue, [{"partition": q.partition, "qos": q.qos or "(no QOS)", "max_time": shown(q.max_time),
                            "max_cpus": shown(q.max_cpus), "max_memory_mib": mib(q.max_memory_mib),
                            "max_gpus": shown(q.max_gpus),
                            "max_submit_jobs_per_user": shown(q.max_submit_jobs_per_user)} for q in r.queues],
            "partition", "qos", "max_time", "max_cpus", "max_memory_mib", "max_gpus", "max_submit_jobs_per_user")]
    if not isinstance(r.environments, dict):
        blocks.append(view.Text(text=f"environments: {shown(r.environments)}"))
    elif r.environments or now:
        blocks += [view.Text(text="environments"), view.Table.of(
            EnvironmentRow, [{"name": n, "state": e.state if e else "none", "gpu": e.gpu if e and e.gpu else "",
                              "now": f"{now[n][1]} here now" if n in now else ""}
                             for n, e in sorted({**dict.fromkeys(now), **r.environments}.items())],
            "name", "state", "gpu", "now")]
    else:
        blocks.append(view.Text(text="environments: none installed"))
    blocks += [view.Text(text="settings"), view.Table.of(SettingRow, [
        {"key": d, "value": settings.key(d).shown(record.copied(r.settings, d))} for d in record.COPIED],
        "key", "value")]
    return [b for b in blocks if not isinstance(b, view.Table) or b.rows]   # no command found: no table


# ------------------------------------------------------------------ job probe

class ProbeOutcome(Outcome):
    record: Record = Field(description="the record, as measured")
    file: str | None = Field(default=None, description="the file written; none when not written")
    write: view.Action | None = Field(default=None, description="what writes the record shown")

    @property
    def report(self) -> view.Report:
        head = (f"wrote {text.path(self.file)}" if self.file else "measured; nothing written") \
            if self.status == "done" else "writing the record failed"
        blocks = [view.Text(text=head), *_record(self.record)]
        if not self.file and self.status == "done" and self.write:
            blocks.append(view.Next(label="to write it", actions=[self.write]))
        return view.Report(blocks=blocks)


def _name(req: ProbeRequest) -> str:
    return req.name or LOCAL    # `local` itself is refused by the request's schema


@operation(JOB_PROBE, result=ProbeOutcome, subject=lambda req: [f"machine-{req.name or LOCAL}"])
class JobProbe:
    """Measure this machine — scheduler, queues, node groups, environments — into its record; writes only with --write."""

    def plan(self, req: ProbeRequest, ctx: Context) -> Plan:
        name = _name(req)
        file = record.path(name)
        declared = probe.declarations(req.set)
        if req.write and (unset := settings.unstated(settings.load(ctx).config, record.COPIED)):
            raise Unstated(f"every job prepared for this record needs {' and '.join(unset)}, unset here "
                           f"{pointer(settings.MANUAL)}", settings.steps(unset),
                           code="setting-unset", subject=", ".join(unset))
        new = probe.measure(ctx, req.scheduler, declared)
        if req.write and isinstance(new.scheduler.commands.get("submit"), record.Unknown):
            raise Unstated(f"the {new.scheduler.kind} submit command was not found",
                          (view.command(JOB_PROBE, write=True, scheduler=new.scheduler.kind,
                                        fills=[view.Fill(field="set", label="scheduler.commands.submit",
                                                                example="scheduler.commands.submit=PATH")]),),
                          code="command-not-found", subject="scheduler.commands.submit")
        issues = [Issue(severity="info", code="note", subject=name, message=n) for n in new.notes]
        issues += [Issue(severity="info", code="not-measured", subject=where, message=f"{where}: {why}")
                   for where, why in record.unknowns(new)]
        steps: tuple[Step, ...] = ()
        if req.write:
            describe = f"write {text.path(file)}"
            if file.exists():
                try:
                    changed = record.differences(record.read(file), new)
                    describe += f" — {text.count(len(changed), 'difference')} from the record there"
                    issues += [Issue(severity="info", code="changed", subject=name, message=c) for c in changed]
                except DefinitionError as exc:  # a file there that does not load is said, and replaced only on consent
                    describe += " — replacing a file that does not load"
                    issues.append(Issue(severity="warning", code="unreadable", subject=str(file), message=str(exc)))
            else:
                describe += " — a new record"
            steps = (Step(id="write", describe=describe),)
        return Plan(holds={"record": new.data(), "file": str(file)}, steps=steps, issues=issues)

    def observe(self, req: ProbeRequest, ctx: Context) -> dict:
        """The record file as it is now: what a write replaces."""
        return {"existing_sha256": record.sha256(record.path(_name(req)))}

    def apply(self, plan: Plan, ctx: Context, observer) -> ProbeOutcome:
        req = ProbeRequest.model_validate(plan.request)
        file = Path(plan.holds["file"])
        new = Record.model_validate(plan.holds["record"])

        def do(step: Step, where):
            record.write(file, new)
            return "done", None

        status, log = run_steps(plan, ctx, observer, do)   # its event log is written, steps or none (api.md § 3)
        return ProbeOutcome(plan=plan, status=status, log=str(log), record=new,
                            file=str(file) if plan.steps and status == "done" else None,
                            write=_write(req))


def _write(req: ProbeRequest) -> view.Action:
    """The probe that writes what ``req`` showed: the same request, writing."""
    return view.command(JOB_PROBE, **{**req.model_dump(exclude_defaults=True), "write": True})


# ------------------------------------------------------------------ job machines

class MachineRow(Model):
    name: str = Field(description="the record's name; `local` is this machine")
    path: str = Field(description="its file")
    status: Literal["ok", "stale", "does not load"] = Field(
        description="`ok` for a record that loads and is current, or cannot be compared from here")
    detail: str = Field(default="", description="when and where it was measured, or why it does not load")
    summary: str = Field(default="", description="scheduler, node groups and queues")


class MachinesResult(Result):
    rows: list[MachineRow] = Field(default_factory=list, description="every record listed")
    record: Record | None = Field(default=None, description="the one record asked for")
    now: dict[str, tuple[str | None, str]] = Field(
        default_factory=dict, description="for the one record asked for, of this machine: each environment whose "
                                          "state here differs from the record's — its state there, and now")
    directory: str = Field(default="", description="where the machine records are")

    @property
    def report(self) -> view.Report:
        if self.record is not None:
            r, row = self.record, self.rows[0]
            return view.Report(blocks=[view.Text(text=f"{row.name}: {row.status} — {text.path(row.path)}"),
                                       *_record(r, self.now), view.Text(text="sources"),
                                       view.Table.of(SourceRow, [{"part": k, "by": v} for k, v in r.sources.items()],
                                                     "part", "by")])
        if not self.rows:
            return view.Report(blocks=[view.Text(text=f"no machine records in {text.path(self.directory)}")])
        return view.Report(blocks=[view.Text(text=text.count(len(self.rows), "machine record")), view.Table.of(
            MachineRow, [{"name": r.name, "status": r.status, "summary": r.summary, "detail": r.detail}
                         for r in self.rows], "name", "status", "summary", "detail")])


@operation(JOB_MACHINES, result=MachinesResult)
def job_machines(req: MachinesRequest, ctx: Context) -> MachinesResult:
    """Every machine record — or one, with the source of each fact; a record that does not load is listed and marked."""
    config = settings.load(ctx).config
    found = record.listing()
    if req.name is not None:
        found = [f for f in found if f[0] == req.name]
        if not found:
            raise UsageError(f"no machine record `{req.name}` in {text.path(record.machines_dir())}",
                             (view.command(JOB_MACHINES),), code="no-such-record", subject=req.name)
    m = record.machine(ctx)
    said = {m.states.unloadable: "does not load", m.states.stale: "stale", m.states.current: "ok"}  # jobs.md § 9.3
    rows, issues, now = [], [], {}
    for name, file, r, problem in found:
        summary = detail = ""
        if r is not None:
            groups = sum(len(p.node_groups) for p in r.partitions.values()) if isinstance(r.partitions, dict) else 0
            queues = len(r.queues) if isinstance(r.queues, list) else 0
            summary = f"{r.scheduler.kind}, {text.count(groups, 'node group')}, {text.count(queues, 'queue')}"
            detail = f"measured {r.measured.time} on a {r.measured.where}"
        if r is not None and not record.of_this_machine(r):
            # Another machine's record cannot be compared from here, and is never marked (§ 9.3).
            rows.append(MachineRow(name=name, path=str(file), status="ok", detail=detail, summary=summary))
            continue
        state, why, f = record.status(ctx, file, config)   # this machine's, or one whose machine cannot be read
        rows.append(MachineRow(name=name, path=str(file), status=said[state], detail=problem or detail,
                               summary=summary))
        if state is not m.states.current:
            issues.append(Issue(severity="error" if r is None and name == req.name else "warning",
                                code=state.value, subject=name, message=why, next=m.next(state, f)))
        if r is not None and name == req.name and (now := record.environments_now(ctx, r)):
            changed = ", ".join(f"{env} {was or 'none'} -> {here}" for env, (was, here) in now.items())
            issues.append(Issue(severity="info", code="environments-changed", subject=name,
                                message=f"the environments here are not as the record lists them: {changed}",
                                next=m.next(state, f)))     # its probe, as the record's table gives its state
    one = found[0][2] if req.name is not None else None
    return MachinesResult(rows=rows, record=one, now=now, directory=str(record.machines_dir()), issues=issues)


# ------------------------------------------------------------------ a folder's lock

def _subjects(paths) -> tuple[str, ...]:
    """The lock subjects of the folders an operation writes in, each once: each folder's own,
    wherever it lies (jobs.md § 5; core.md § 5)."""
    return tuple(sorted({runs.subject(Path(p)) for p in paths}))


def _basis(ctx: Context, paths) -> dict:
    """What a plan over these folders rests on: each one's request, preparation and runs."""
    out, files = {}, layout.read_once(ctx)
    for p in map(Path, paths):
        out[str(p)] = {"request": persist.sha256(p / files.name("request")),
                       "prepared": persist.sha256(p / files.name("prepared")),
                       "launched": persist.sha256(p / files.name("launch_record")),
                       "runs": [r.name for r in runs.runs(ctx, p)]}
    return out


# ------------------------------------------------------------------ job prepare

class PreparedRow(Model):
    folder: str = Field(description="a folder prepared")
    environment: str = Field(description="the environment its run enters; none for a launch folder")
    script: str = Field(description="its run script; none for a launch folder, whose walk its launch writes")


class PrepareOutcome(Outcome):
    target: str = Field(default="", description="the machine record it was prepared for")
    folder: str = Field(default="", description="the folder, as named")
    rows: list[PreparedRow] = Field(default_factory=list, description="each folder prepared: a launch folder's "
                                                                      "members and parts first")
    next: list[view.Action] = Field(default_factory=list, description="the launch its folder's state allows, by "
                                    "its full path; none for another machine's target, or one a launch here cannot "
                                    "send a job to", json_schema_extra={"doc": "jobs.md § 5.5"})

    @property
    def report(self) -> view.Report:
        head = f"prepared for {self.target}" if self.status == "done" else f"preparing for {self.target} failed"
        return view.Report(blocks=[
            view.Text(text=f"{head}: {self.folder}"),
            view.Table.of(PreparedRow, [r.model_dump() for r in self.rows], "folder", "environment", "script"),
            *([view.Next(label="to start it", actions=self.next)] if self.next else [])])


@operation(JOB_PREPARE, result=PrepareOutcome, subject="plan")
class JobPrepare:
    """Write a calculation folder's run script for its machine — a launch folder's members' and parts' too — from its job.toml and the calculation's own copy of the machine's record; show how the request fits it."""

    def plan(self, req: PrepareRequest, ctx: Context) -> Plan:
        p = prepare.prepare(ctx, req.dir, req.target)
        steps = tuple(Step(id=f"prepare:{i}", describe=f"write {', '.join(_written(ctx, w))} in {text.path(w.folder)}")
                      for i, w in enumerate(p.folders))
        return Plan(subjects=_subjects(w.folder for w in p.folders), steps=steps,
                    holds={"target": p.target, "folders": [w.held() for w in p.folders], "launches": p.launches},
                    issues=p.issues)

    def observe(self, req: PrepareRequest, ctx: Context) -> dict:
        """The folders it prepares, every machine record and every program it copies, as they are now."""
        return {"folders": _basis(ctx, folders.tree(ctx, Path(req.dir).resolve())),
                "records": {name: record.sha256(file) for name, file, *_ in record.listing()},
                "programs": {str(s): persist.sha256(s) for s in layout.read_once(ctx).beside().values()}}

    def apply(self, plan: Plan, ctx: Context, observer) -> PrepareOutcome:
        held, files = plan.holds["folders"], layout.read_once(ctx)

        def do(step: Step, where: Path):
            prepare.commit(ctx, prepare.Writing.of(held[int(step.id.split(":")[1])]))
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return PrepareOutcome(plan=plan, status=status, log=str(where), target=plan.holds["target"],
                              folder=plan.request["dir"],
                              next=_launch(ctx, Path(plan.request["dir"])) if status == "done" and
                              plan.holds["launches"] else [],
                              rows=[PreparedRow(folder=w["named"], environment=w["prepared"].get("environment") or "",
                                                script=text.path(Path(w["path"]) / files.name("script"))
                                                if w["script"] is not None else "") for w in held])


def _launch(ctx: Context, folder: Path) -> list[view.Action]:
    """The launch a prepared folder's state allows, as its table gives it, by its full path (jobs.md
    §§ 1, 5.5); none where its state allows none."""
    f, state = folders.observe(ctx, folder.resolve())
    step = folders.launch_step(ctx, state, f)
    return [step] if step is not None else []


def _written(ctx: Context, w: prepare.Writing) -> list[str]:
    files = layout.read_once(ctx)
    return [*([files.name("machine")] if w.copy else []), *w.sources,
            *([files.name("script")] if w.script is not None else []), files.name("prepared")]


# ------------------------------------------------------------------ job launch

class RunRow(Model):
    run: str = Field(description="the run, by its path")
    state: str = Field(description="its state", json_schema_extra={"doc": "jobs.md § 5.2"})
    words: str = Field(default="", description="what its records say of it")


class LaunchOutcome(Outcome):
    folder: str = Field(default="", description="the folder launched, as named")
    how: Literal["background", "waited on", "in a sequence"] = Field(default="background",
                                                                     description="how the job went")
    job: str = Field(default="", description="the job, as `job list` names it")
    runs: list[RunRow] = Field(default_factory=list, description="each run it started; waited on, as each ended")
    closed: bool = Field(default=True, description="waited on: whether its runs closed before the launch read them")
    next: list[view.Action] = Field(default_factory=list, description="to follow it: `job status` of its folder, by "
                                    "its full path, and, for a job in the background, the line that stops it — for "
                                    "one not closed at its terminal, `job list`",
                                    json_schema_extra={"doc": "jobs.md § 5"})

    def ok(self) -> bool:
        if self.how != "waited on":
            return super().ok()
        return super().ok() and self.closed and all(r.state == "finished" for r in self.runs)

    @property
    def report(self) -> view.Report:
        if self.status != "done":
            return view.Report(blocks=[view.Text(text=f"launching {self.folder} failed")])
        said = {"background": f"started in the background, as job {self.job}",
                "waited on": f"ran here, waited on, as job {self.job}" if self.closed
                else f"stopped at its terminal; job {self.job} has not closed yet",
                "in a sequence": f"ran inside the sequence's job {self.job}"}[self.how]
        blocks: list = [view.Text(text=f"{said}: {self.folder}")]
        if self.runs:     # in the background, each run only: its state is read by `job status`
            keys = ("run",) if self.how == "background" else ("run", "state", "words")
            blocks.append(view.Table.of(RunRow, [{k: text.path(r.run) if k == "run" else getattr(r, k) for k in keys}
                                                 for r in self.runs], *keys))
        if self.next:
            blocks.append(view.Next(label="to follow it", actions=self.next))
        return view.Report(blocks=blocks)


def _opening(o: dict) -> launch.Opening:
    return launch.Opening(folder=Path(o["folder"]), named=o["named"], run=Path(o["run"]), refill=o["refill"],
                          files={n: Path(s) for n, s in o["files"].items()}, script=o["script"])


@operation(JOB_LAUNCH, result=LaunchOutcome, subject="plan")
class JobLaunch:
    """Start a prepared folder's job on this machine — a new run, or a batch's or a sequence's walk — in the background, or waited on with --foreground."""

    def plan(self, req: LaunchRequest, ctx: Context) -> Plan:
        l = launch.launching(ctx, req)
        steps = [Step(id=f"open:{i}", describe=f"{'fill again' if o.refill else 'open'} {text.path(o.run)}: "
                                               f"{text.count(len(o.files) + 1, 'file')} copied in")
                 for i, o in enumerate(l.openings)]
        how = "waited on" if req.foreground else "in the background"
        if l.request.walk is not None or l.openings:
            where = l.started
            script = where / layout.read_once(ctx).name("script")
            steps.append(Step(id="start", describe=f"start {text.path(script)} {how}",
                              argv=("bash", str(script), str(where))))
        held = {"folder": str(l.folder), "named": l.named, "request": l.request.model_dump(mode="json"),
                "target": l.target, "identity": l.identity, "walk": l.walk,
                "listed": [[name, str(path)] for name, path in l.listed],
                "left": [[x.named, x.why] for x in l.left],
                "inside": {"folder": str(l.inside.folder), "record": l.inside.record.model_dump(mode="json")}
                if l.inside else None,
                "openings": [{"folder": str(o.folder), "named": o.named, "run": str(o.run), "refill": o.refill,
                              "files": {n: str(s) for n, s in o.files.items()}, "script": o.script}
                             for o in l.openings]}
        issues = [Issue(severity="info", code="left-out", subject=x.named, message=x.why) for x in l.left]
        return Plan(subjects=_subjects([l.folder, *(p for _, p in l.listed), *(o.folder for o in l.openings)]),
                    steps=tuple(steps), holds=held, issues=issues)

    def observe(self, req: LaunchRequest, ctx: Context) -> dict:
        """The folders it launches, as they are now."""
        return {"folders": _basis(ctx, folders.tree(ctx, Path(req.dir).resolve()))}

    def apply(self, plan: Plan, ctx: Context, observer) -> LaunchOutcome:
        req = LaunchRequest.model_validate(plan.request)
        h = plan.holds
        inside = h["inside"]
        l = launch.Launching(folder=Path(h["folder"]), named=h["named"], request=JobRequest.model_validate(h["request"]),
                             target=h["target"], identity=h["identity"], walk=h["walk"],
                             openings=[_opening(o) for o in h["openings"]],
                             left=[launch.Left(n, w) for n, w in h["left"]],
                             listed=[(n, Path(p)) for n, p in h["listed"]],
                             inside=launch.Inside(Path(inside["folder"]), folders.LaunchRecord.model_validate(
                                 inside["record"])) if inside else None)
        how = "in a sequence" if l.inside else "waited on" if req.foreground else "background"
        got: dict = {"job": "", "runs": [], "closed": True}

        def do(step: Step, where: Path):
            if step.id.startswith("open:"):
                launch.fill(ctx, l.openings[int(step.id.split(":")[1])])
                return "done", None
            s = launch.start(ctx, l, req.foreground)
            got.update(job=s.job.id, runs=[RunRow(run=str(r), state="") for r in s.runs])
            ctx.release()            # every write done: the hold ends before it waits (api.md § 3)
            if req.foreground:
                seen, closed = launch.waited(ctx, s)
                got.update(closed=closed, runs=[RunRow(run=str(x.run), state=x.state.value, words=x.words)
                                                for x in seen])
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return LaunchOutcome(plan=plan, status=status, log=str(where), folder=l.named, how=how,
                             next=_following(l.folder, how, got["job"], got["closed"]) if status == "done" else [],
                             **got)


def _following(folder: Path, how: str, job: str, closed: bool) -> list[view.Action]:
    """What follows a launch (jobs.md § 5): `job status` of its folder, by its full path; for a job
    left in the background, the line that stops it; for one waited on and not closed at its
    terminal, `job list`, which keeps its address."""
    steps = [view.command(JOB_STATUS, dir=str(folder))]
    if how == "background":
        steps.append(view.command(JOB_CANCEL, id=job))
    elif not closed:
        steps.append(view.command(JOB_LIST))
    return steps


# ------------------------------------------------------------------ job status

class MemberRow(Model):
    folder: str = Field(description="a member or part of a launch folder, by its path")
    state: str = Field(description="its state", json_schema_extra={"doc": "jobs.md § 5.5"})
    run: str = Field(default="", description="its newest run")
    words: str = Field(default="", description="what its newest run's records say")


class FileRun(RunRow):
    files: list[str] = Field(default_factory=list, description="the files it left")


class JobStatusResult(Result):
    folder: str = Field(description="the folder, as named")
    state: str = Field(description="its state", json_schema_extra={"doc": "jobs.md § 5.5"})
    describe: str = Field(default="", description="its state in words")
    runs: list[FileRun] = Field(default_factory=list, description="each run, oldest first, and the files it left")
    members: list[MemberRow] = Field(default_factory=list, description="a launch folder's members or parts")
    next: list[view.Action] = Field(default_factory=list, description="what its state allows")

    @property
    def report(self) -> view.Report:
        blocks: list = [view.Text(text=f"{self.folder}: {self.state} — {self.describe}")]
        if self.members:
            blocks.append(view.Table.of(MemberRow, [{"folder": text.path(m.folder), "state": m.state, "run": m.run,
                                                     "words": m.words} for m in self.members],
                                        "folder", "state", "run", "words"))
        if self.runs:
            blocks.append(view.Table.of(FileRun, [{"run": r.run, "state": r.state, "words": r.words,
                                                   "files": " ".join(r.files)} for r in self.runs],
                                        "run", "state", "words", "files"))
        if self.next:
            blocks.append(view.Next(label="what its state allows", actions=self.next))
        return view.Report(blocks=blocks)


@operation(JOB_STATUS, result=JobStatusResult)
def job_status(req: StatusRequest, ctx: Context) -> JobStatusResult:
    """A calculation or launch folder's state, each run's beside it and the files each left; a launch folder's members' or parts'."""
    folder = Path(req.dir).resolve()
    request = layout.read_once(ctx).name("request")
    if not (folder / request).is_file():
        raise UsageError(f"{req.dir} holds no {request}: it is no calculation folder",
                         code="no-request", subject=req.dir)
    m = folders.machine(ctx)
    f, state = folders.observe(ctx, folder)
    rows = [FileRun(run=r.name, state=(x := runs.observe(ctx, r)).state.value, words=x.words,
                    files=runs.own_files(ctx, r)) for r in runs.runs(ctx, folder)]
    members = []
    for v in folders.walk(ctx, folder):
        if v.depth != 1:                  # its own members or parts
            continue
        member = v.folder
        mf, ms = folders.observe(ctx, member)
        members.append(MemberRow(folder=str(member), state=ms.value, run=mf.newest.run.name if mf.newest else "",
                                 words=mf.newest.words if mf.newest else (mf.holding.why if mf.holding else "")))
    unknown = folders.maker(ctx, folder).unknown
    said = [Issue(severity="warning", code="maker-unknown", subject=str(folder / layout.read_once(ctx).name(
        "maker_action")), message=f"{req.dir} was written by `{unknown}`, an operation femkit does not have: nothing "
                                  "is offered to write it again")] if unknown else []
    return JobStatusResult(folder=req.dir, state=state.value, describe=_said(m, state, f), runs=rows, members=members,
                           next=list(folders.next_steps(ctx, state, f)), issues=said)


def _said(m, state, f: folders.FolderFacts) -> str:
    """A folder's state in words: the table's sentence, and what its newest run's records say."""
    words = next(r.describe for r in m.rules if r.state is state)
    if f.holding is not None and state is m.states.held:
        return f"{words}: {f.holding.why}"
    if f.newest is not None and f.newest.words and state.value == f.newest.state.value:
        return f"{words}: {f.newest.words}"
    return words


# ------------------------------------------------------------------ job list

class JobRow(Model):
    id: str = Field(description="the job, as `job cancel` names it")
    how: str = Field(description="how and when it went")
    folder: str = Field(description="the calculation or launch folder")
    going: str = Field(description="whether it still goes: going, ended, or asked on another host")
    runs: list[RunRow] = Field(default_factory=list, description="each run it started, with its state")
    waiting: list[str] = Field(default_factory=list, description="a sequence's parts not launched yet")
    next: list[view.Action] = Field(default_factory=list, description="its `job status`, and while it goes its cancel")


class JobListResult(Result):
    jobs: list[JobRow] = Field(default_factory=list, description="every job launched from this machine")
    unreadable: list[str] = Field(default_factory=list, description="each address that does not read, by its path")

    @property
    def report(self) -> view.Report:
        if not self.jobs and not self.unreadable:
            return view.Report(blocks=[view.Text(text="no job launched from this machine")])
        blocks: list = [view.Text(text=text.count(len(self.jobs), "job"))]
        for j in self.jobs:
            blocks.append(view.Text(text=f"{j.id}  {j.how}, {j.folder} -- {j.going}"))
            rows = [{"run": text.path(r.run), "state": r.state, "words": r.words} for r in j.runs]
            rows += [{"run": text.path(p), "state": "not launched yet", "words": ""} for p in j.waiting]
            if rows:
                blocks.append(view.Table.of(RunRow, rows, "run", "state", "words"))
            if j.next:
                blocks.append(view.Next(label=f"for {j.id}", actions=j.next))
        blocks += [view.Text(text=f"{text.path(p)} does not read: kept") for p in self.unreadable]
        return view.Report(blocks=blocks)


@operation(JOB_LIST, result=JobListResult)
def job_list(req: ListRequest, ctx: Context) -> JobListResult:
    """Every job launched from this machine, and each of its runs' states; a job that has ended is shown once, and its address removed."""
    here = record.host_identity()
    jobs, unreadable = [], []
    for file, held in addresses.listing():
        if not held.reads:
            unreadable.append(str(file))
            continue
        a: addresses.Address = held.value
        going = addresses.going(a, here)
        if going is None:
            jobs.append(JobRow(id=a.id, how=f"{a.how}, {a.time}", folder=a.folder, going=f"on {a.host}: ask there"))
            continue
        seen = [runs.observe(ctx, Path(r)) for r in a.runs]
        reached = {Path(r).parent for r in a.runs}
        waiting = [p for p in a.sequence or [] if not _reached(ctx, Path(p), reached)]
        steps = [view.command(JOB_STATUS, dir=a.folder)]
        if going:
            steps.append(view.command(JOB_CANCEL, id=a.id))
        jobs.append(JobRow(id=a.id, how=f"{a.how}, {a.time}", folder=a.folder,
                           going="going" if going else "ended -- said once; its address is removed",
                           runs=[RunRow(run=str(x.run), state=x.state.value, words=x.words) for x in seen],
                           waiting=waiting, next=steps))
        if not going:
            addresses.remove(a.id)
    return JobListResult(jobs=jobs, unreadable=unreadable)


def _reached(ctx: Context, part: Path, reached: set[Path]) -> bool:
    """Whether a sequence has launched a part: a run of it, or of one of its members."""
    if part in reached or (part / layout.read_once(ctx).name("launch_record")).exists():
        return True
    return False


# ------------------------------------------------------------------ job cancel

class CancelOutcome(Outcome):
    job: str = Field(default="", description="the job")
    stopped: bool = Field(default=False, description="whether it was going when the signal came")
    runs: list[str] = Field(default_factory=list, description="each run it held that had not ended")
    next: list[view.Action] = Field(default_factory=list, description="to see how it ended: `job list`",
                                    json_schema_extra={"doc": "jobs.md § 5.4"})

    @property
    def report(self) -> view.Report:
        said = f"cancelled {self.job}: SIGTERM to its process group" if self.stopped else f"{self.job} had ended already"
        return view.Report(blocks=[view.Text(text=said),
                                   *([view.Next(label="to see how it ended", actions=self.next)] if self.next else [])])


@operation(JOB_CANCEL, result=CancelOutcome, subject=lambda req: [])
class JobCancel:
    """Stop one job `job list` shows: one SIGTERM to its process group, which its run script answers."""

    def plan(self, req: CancelRequest, ctx: Context) -> Plan:
        c = launch.cancelling(ctx, req.id)
        if not c.going:
            return Plan(holds={"runs": []}, issues=[Issue(severity="info", code="ended", subject=req.id,
                                                          message=f"{req.id} has ended already: nothing to stop")])
        return Plan(holds={"runs": [str(r) for r in c.runs]}, steps=(Step(
            id="cancel", describe=f"send SIGTERM once to the process group of {req.id} (process {c.address.job.pid}), "
                                  f"on {c.address.folder}; {layout.read_once(ctx).name('cancel')} into "
                                  f"{text.count(len(c.runs), 'run')} it holds"),))

    def observe(self, req: CancelRequest, ctx: Context) -> dict:
        """The job's address, and whether it goes, as they are now."""
        held = addresses.find(req.id)
        return {"address": persist.sha256(addresses.path(req.id)),
                "going": bool(held.reads and held.value.job.identity().alive())}

    def apply(self, plan: Plan, ctx: Context, observer) -> CancelOutcome:
        req = CancelRequest.model_validate(plan.request)
        stopped: list[bool] = []

        def do(step: Step, where: Path):
            stopped.append(launch.cancel(ctx, launch.cancelling(ctx, req.id)))
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return CancelOutcome(plan=plan, status=status, log=str(where), job=req.id, stopped=bool(stopped and stopped[0]),
                             runs=plan.holds["runs"], next=[view.command(JOB_LIST)])
