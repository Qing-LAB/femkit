"""Job operations (jobs.md § 8). Today: the machine record's — `job probe`, `job machines`."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from femkit.config import settings
from femkit.config.operations import stating
from femkit.config.requests import CONFIG_INIT
from femkit.core import text, view
from femkit.core.errors import Unstated, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.schema import DefinitionError, Model, pointer
from femkit.jobs import probe, record
from femkit.jobs.record import LOCAL, Record
from femkit.jobs.requests import ProbeRequest, MachinesRequest
from femkit.jobs.requests import JOB_MACHINES, JOB_PROBE



def _table(rows: list[dict], *keys: str) -> view.Table:
    """Rows under columns with no heading: each cell says what it is."""
    return view.Table(columns=view.columns(*keys), rows=rows)


def _pairs(pairs) -> view.Table:
    """Each name beside its value."""
    return _table([{"key": k, "value": v} for k, v in pairs], "key", "value")


def _record(r: Record) -> list[view.Text | view.Table]:
    """A record as a person reads it (api.md § 4.4)."""
    def show(v) -> str:
        return f"unknown ({v.unknown})" if isinstance(v, record.Unknown) else text.show(v)

    def nodes(p: record.Partition) -> str:
        groups = "; ".join(f"{g.count}× {show(g.cores)} cores, {show(g.memory_mib)} MiB"
                           + (", " + " ".join(f"{n} {t}" for t, n in g.gpus.items()) if g.gpus else "")
                           + f", {show(g.architecture)}" for g in p.node_groups)
        return f"max {show(p.max_time)}; {groups or 'no nodes listed'}"

    m, s = r.manager, r.settings
    blocks = [view.Text(text=f"identity: {show(r.identity)}, measured {r.measured.time} on a {r.measured.where}"),
              view.Text(text=f"host: {r.host.os}, {r.host.architecture}, {show(r.host.cores)} cores, "
                             f"{show(r.host.memory_mib)} MiB"),
              _pairs([("gpu", f"{g.model} (compute {g.compute_capability}, {g.memory_mib} MiB)") for g in r.host.gpus]
                     if isinstance(r.host.gpus, list) else [("gpus", show(r.host.gpus))]),
              view.Text(text=f"manager: {show(m.kind)} {show(m.version)} at {show(m.path)}; "
                             f"platform {show(m.platform)}; run enters: {show(m.run_enters)}"),
              view.Text(text=f"scheduler: {r.scheduler.kind}"),
              _pairs((role, show(where)) for role, where in {**r.scheduler.commands, **r.scheduler.probe}.items())]
    if not isinstance(r.partitions, dict):
        blocks.append(view.Text(text=f"partitions: {show(r.partitions)}"))
    elif r.partitions:
        blocks += [view.Text(text="partitions"), _pairs((name, nodes(p)) for name, p in r.partitions.items())]
    if not isinstance(r.queues, list):
        blocks.append(view.Text(text=f"queues: {show(r.queues)}"))
    elif r.queues:
        blocks += [view.Text(text="queues"), _table(
            [{"partition": q.partition, "qos": q.qos or "(no QOS)", "time": f"max {show(q.max_time)}",
              "cpus": f"cpus {show(q.max_cpus)}", "gpus": f"gpus {show(q.max_gpus)}"} for q in r.queues],
            "partition", "qos", "time", "cpus", "gpus")]
    if not isinstance(r.environments, dict):
        blocks.append(view.Text(text=f"environments: {show(r.environments)}"))
    elif r.environments:
        blocks += [view.Text(text="environments"), _table(
            [{"name": n, "state": e.state, "gpu": f"gpu {e.gpu}" if e.gpu else ""} for n, e in r.environments.items()],
            "name", "state", "gpu")]
    else:
        blocks.append(view.Text(text="environments: none installed"))
    blocks.append(view.Text(text=f"settings: environments {s.environments}; mpi {text.show(s.mpi) if s.mpi else 'unset'}; "
                                 f"preamble {text.show(s.preamble) if s.preamble is not None else 'unset'}"))
    return [b for b in blocks if not isinstance(b, view.Table) or b.rows]   # no GPU, no command found: no table


# ------------------------------------------------------------------ job probe

class ProbeOutcome(Outcome):
    record: dict = Field(default_factory=dict, description="the record, as measured")
    file: str | None = Field(default=None, description="the file written; none when not written")
    write: view.Action | None = Field(default=None, description="what writes the record shown")

    def report(self) -> view.Report:
        head = (f"wrote {self.file}" if self.file else "measured; nothing written") \
            if self.status == "done" else "writing the record failed"
        blocks = [view.Text(text=head), *_record(Record.model_validate(self.record))]
        if not self.file and self.status == "done" and self.write:
            blocks.append(view.Next(label="to write it", actions=[self.write]))
        return view.Report(blocks=blocks)


def _name(req: ProbeRequest) -> str:
    if req.name == LOCAL:
        raise UsageError("`local` is this machine's own record: write it with `job probe --write`, no --name",
                         code="reserved-name", subject=LOCAL)
    return req.name or LOCAL


@operation(JOB_PROBE, result=ProbeOutcome, changes=True,
           subject=lambda req: [f"machine-{req.name or LOCAL}"])
class JobProbe:
    """Measure this machine — scheduler, queues, node groups, environments — into its record; writes only with --write."""

    def plan(self, req: ProbeRequest, ctx: Context) -> Plan:
        name = _name(req)
        file = record.path(name)
        declared = probe.declarations(req.set)
        if req.write and (unset := settings.unstated(settings.load(ctx).config)):
            raise Unstated(f"{' and '.join(unset)} {'is' if len(unset) == 1 else 'are'} unset, and every job "
                          f"prepared for this record needs it {pointer(settings.MANUAL)}", stating(CONFIG_INIT, unset),
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

        status, log = run_steps(plan, ctx, observer, do)
        return ProbeOutcome(plan=plan, status=status, log=str(log) if plan.steps else None,
                            record=plan.holds["record"], file=str(file) if plan.steps and status == "done" else None,
                            write=_write(req), issues=plan.issues)


def _write(req: ProbeRequest) -> view.Action:
    """The probe that writes what ``req`` showed: the same request, writing."""
    return view.command(JOB_PROBE, **{**req.model_dump(exclude_defaults=True), "write": True})


# ------------------------------------------------------------------ job machines

class MachineRow(Model):
    name: str = Field(description="the record's name; `local` is this machine")
    path: str = Field(description="its file")
    status: str = Field(description="ok, stale, or does not load")
    detail: str = Field(default="", description="when and where it was measured, or why it does not load")
    summary: str = Field(default="", description="scheduler, node groups and queues")


class MachinesResult(Result):
    rows: list[MachineRow] = Field(default_factory=list, description="every record listed")
    record: dict | None = Field(default=None, description="the one record asked for")
    directory: str = Field(default="", description="where the machine records are")

    def report(self) -> view.Report:
        if self.record is not None:
            r, row = Record.model_validate(self.record), self.rows[0]
            return view.Report(blocks=[view.Text(text=f"{row.name}: {row.status} — {row.path}"), *_record(r),
                                       view.Text(text="sources"), _pairs(r.sources.items())])
        if not self.rows:
            return view.Report(blocks=[view.Text(text=f"no machine records in {self.directory}")])
        return view.Report(blocks=[view.Text(text=text.count(len(self.rows), "machine record")), _table(
            [{"name": r.name, "status": r.status, "summary": r.summary, "detail": r.detail} for r in self.rows],
            "name", "status", "summary", "detail")])


@operation(JOB_MACHINES, result=MachinesResult)
def job_machines(req: MachinesRequest, ctx: Context) -> MachinesResult:
    """Every machine record — or one, with the source of each fact; a record that does not load is listed and marked."""
    config = settings.load(ctx).config
    found = record.listing()
    if req.name is not None:
        found = [f for f in found if f[0] == req.name]
        if not found:
            raise UsageError(f"no machine record {req.name!r} in {record.machines_dir()}",
                             (view.command(JOB_MACHINES),), code="no-such-record", subject=req.name)
    rows, issues = [], []
    local = next((r for n, _, r, _ in found if n == LOCAL and r is not None), None)
    for name, file, r, problem in found:
        if r is None:
            rows.append(MachineRow(name=name, path=str(file), status="does not load", detail=problem))
            continue
        # A record of this machine — local, or one naming local's identity — is compared with
        # this machine's config.toml; another machine's cannot be, and is never marked (§ 9.3).
        mine = name == LOCAL or (local is not None and isinstance(r.identity, str) and r.identity == local.identity)  # two unknowns name no machine
        drift = record.stale(r, config) if mine else []
        if drift:
            m = record.machine(ctx)
            issues.append(Issue(severity="warning", code="stale", subject=name, message="; ".join(drift),
                                next=m.next(m.states.stale, name)))
        groups = sum(len(p.node_groups) for p in r.partitions.values()) if isinstance(r.partitions, dict) else 0
        queues = len(r.queues) if isinstance(r.queues, list) else 0
        rows.append(MachineRow(name=name, path=str(file), status="stale" if drift else "ok",
                               detail=f"measured {r.measured.time} on a {r.measured.where}",
                               summary=f"{r.scheduler.kind}, {text.count(groups, 'node group')}, "
                                       f"{text.count(queues, 'queue')}"))
    one = found[0][2].data() if req.name is not None and found[0][2] is not None else None
    if req.name is not None and found[0][2] is None:
        issues.append(Issue(severity="error", code="unreadable", subject=req.name, message=found[0][3]))
    return MachinesResult(rows=rows, record=one, directory=str(record.machines_dir()), issues=issues)
