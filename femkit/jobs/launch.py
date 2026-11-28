"""Launching a prepared folder (jobs.md § 5), and cancelling a job (§ 5.4), on a machine without a
scheduler; a scheduler's submission, query and cancel are plan § 4, M4.

A launch opens the folder's next run — or fills again, emptied whole first, a run opened and never
launched — and copies into it, from the calculation folder, its request, its inputs, its run
script with the paths of what it shares written in, and the programs `job prepare` copied there;
each shared file is found in the newest run of the folder that made it, which must be finished,
and checked by its SHA-256. For a batch it opens a run for each member and writes the walk; for a
sequence the walk alone. Then it starts the job — in the background, in a session of its own, or
waited on, in its own process group — with its claim set, and writes `launched.json` into each run
it started, a launch folder's launch record, and the job's address. Everything is decided first
(`launching`, `cancelling`) and done after, so a refusal leaves every folder as it was.
"""

from __future__ import annotations

import os
import signal
from dataclasses import dataclass, field
from pathlib import Path

from femkit.core import clock, dirs, persist, process, view
from femkit.core.errors import Refused, UsageError
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.engines.stages.documents import OUTPUTS
from femkit.jobs import addresses, folders, layout, record, runs, script
from femkit.jobs.folders import LaunchRecord, Listed, Prepared
from femkit.jobs.prepare import record_steps, script_target, sends, target_environment
from femkit.jobs.record import LOCAL
from femkit.jobs.request import JobRequest
from femkit.jobs.requests import JOB_LIST, JOB_PREPARE, JOB_STATUS, LaunchRequest
from femkit.jobs.runs import Job, Launched

#: How long a launch waited on and stopped at its terminal waits for its runs to close: twice the
#: run script's own wait for its monitor (jobs.md § 5).
CLOSE = 2 * script.MONITOR_CLOSE
SEQUENCE_FLAGS = ("--in-sequence", "--in-job")


@dataclass
class Opening:
    """One run a launch fills: where, from which folder, with what."""

    folder: Path
    named: str
    run: Path
    refill: bool                          # a run opened and never launched, emptied whole first
    files: dict[str, Path]                # each file copied in, by its path in the run, from its source
    script: str                           # the run's copy of run.sh, the paths of what it shares written in


@dataclass
class Left:
    """A member a launch inside a sequence leaves out, and why (jobs.md § 1.2)."""

    named: str
    why: str


@dataclass
class Launching:
    """What a launch opens and starts."""

    folder: Path
    named: str
    request: JobRequest
    target: str
    identity: str                          # the host it is launched from, as the run door asks of its job
    openings: list[Opening] = field(default_factory=list)
    left: list[Left] = field(default_factory=list)
    listed: list[tuple[str, Path]] = field(default_factory=list)   # a launch folder's members or parts
    walk: str | None = None                # a launch folder's walk
    inside: "Inside | None" = None         # the sequence and job it runs inside

    @property
    def started(self) -> Path:
        """What the launch starts: the run of a calculation folder, or the walk in a launch folder."""
        return self.folder if self.request.walk else self.openings[0].run


@dataclass
class Inside:
    """The sequence whose job a launch runs inside, and that job (jobs.md § 4.2)."""

    folder: Path
    record: LaunchRecord


# ------------------------------------------------------------------ refusals

def _flags(req: LaunchRequest) -> None:
    """`--in-sequence` and `--in-job`, which a sequence's walk alone types, go together, waited on."""
    given = {"--in-sequence": req.in_sequence, "--in-job": req.in_job}
    for flag, value in given.items():
        if value is not None and not req.foreground:
            raise UsageError(f"{flag} is a sequence's walk's, which waits on each part: it goes with --foreground",
                             code="in-sequence-alone", subject=flag)
    missing = [f for f, v in given.items() if v is None]
    if len(missing) == 1:
        raise UsageError(f"{SEQUENCE_FLAGS[0]} and {SEQUENCE_FLAGS[1]} go together: {missing[0]} is missing",
                         code="in-sequence-alone", subject=missing[0])


def _inside(ctx: Context, req: LaunchRequest) -> Inside | None:
    if req.in_sequence is None:
        return None
    seq = Path(req.in_sequence).resolve()
    held = folders.launch_record(ctx, seq)
    if not held.reads:
        raise Refused(f"the sequence {req.in_sequence} has no launch record that reads: "
                      f"{held.problem or 'there is none'}", code="unreadable",
                      subject=str(seq / layout.read_once(ctx).name("launch_record")))
    return Inside(folder=seq, record=held.value)


def launchable(ctx: Context, folder: Path, named: str, inside: Inside | None, whole: Path | None = None
               ) -> folders.FolderFacts:
    """The folder's state allows a launch, or the refusal its state names (jobs.md §§ 5, 5.3, 5.5): not
    prepared, prepared and changed since, held by a job still going — but the sequence launching it
    — a launch folder launched before, a launch folder whose members changed — a member or part
    prepared apart from it since, named — a member going whole with a launch folder not launched
    yet — but ``whole``, that launch folder, launching it — a newest run whose launch record does
    not read, or one that goes."""
    m, files = folders.machine(ctx), layout.read_once(ctx)
    f, state = folders.observe(ctx, folder)
    s = m.states
    if state is s.unprepared:
        raise Refused(f"{named} is not prepared: no {files.name('prepared')} that reads",
                      (view.command(JOB_PREPARE, dir=named),), code="not-prepared", subject=named)
    if state is s.stale:
        raise Refused(f"{named}'s {f.differs} changed since it was prepared", (view.command(JOB_PREPARE, dir=named),),
                      code="prepared-stale", subject=str(folder / f.differs))
    if state is s.held and not (inside and Path(f.holding.address.folder).resolve() == inside.folder):
        raise Refused(f"{named} {f.holding.why}: nothing but that job runs it", m.next(state, f),
                      code="held", subject=named)
    if state is s.launched:
        raise Refused(f"{named} was launched once, and holds that job's walk, launch record and log: to go on, what is "
                      "left is written again as a new launch folder", folders.next_steps(ctx, state, f),
                      code="launched-once", subject=named)
    if state is s.regrouped:
        raise Refused(f"{f.apart} was prepared apart from {named} since: its members changed, and a launch folder goes "
                      "whole or not at all", folders.next_steps(ctx, state, f), code="prepared-apart",
                      subject=str(f.apart))
    if state is s.in_launch and f.launch != whole:
        m.require(state, folders.LAUNCH, f, named)
    if state is s.unreadable:
        raise Refused(f"{named}'s {f.newest.run.name}: {f.newest.words}", code="unreadable",
                      subject=str(folders.unreadable(ctx, f)))
    if state in (s.queued, s.running):
        raise Refused(f"{named}'s {f.newest.run.name} is {state.value}: a run is one start",
                      (view.command(JOB_STATUS, dir=named), view.command(JOB_LIST)), code="not-allowed",
                      subject=str(f.newest.run))
    return f


def _apart(folder: Path, named: str, p: Prepared, launch: Path, target: str) -> None:
    """A member or part is prepared with its launch folder, for its target (jobs.md § 5)."""
    with_ = folders.at(folder, p.launch) if p.launch else None
    if p.target != target or with_ != launch:
        why = f"for {p.target}" if p.target != target else ("apart from it" if with_ is None else f"with {with_}")
        raise Refused(f"{named} was prepared {why}: a member or part runs the script its launch folder prepared",
                      (view.command(JOB_PREPARE, dir=str(launch)),), code="prepared-apart", subject=named)


# ------------------------------------------------------------------ what a launch opens

def opening(ctx: Context, folder: Path, named: str, f: folders.FolderFacts, inside: Inside | None) -> Opening | Left:
    """The run a launch fills for the calculation folder ``folder``: its next, or its newest when
    that was opened and never launched; its inputs and what it shares, each checked — inside a
    sequence, a share whose folder has no finished run leaves the member out (jobs.md §§ 1.2, 5)."""
    req, names = runs.request_of(ctx, folder), layout.read_once(ctx)
    pending = f.newest is not None and f.newest.state.value == "pending"
    run = f.newest.run if pending else runs.next_run(ctx, folder)
    files: dict[str, Path] = {names.name("request"): folder / names.name("request")}
    for i in req.inputs:
        if not (folder / i).exists():
            raise UsageError(f"{named} lists the input {i}, which is not in it", code="no-such-input",
                             subject=str(folder / i))
        files[i] = folder / i
    for name in [*req.programs, *names.beside(), names.name("submit")]:
        if (folder / name).is_file():
            files[name] = folder / name
    paths = []
    for share in req.shares:
        made = folders.at(folder, share.folder)
        newest = runs.newest(ctx, made)
        if newest is None or newest.state.value != "finished":
            said = "has no run" if newest is None else f"has its newest run {newest.state.value}"
            if inside is not None:
                return Left(named, f"it shares {share.file} from {share.folder}, which {said}")
            raise Refused(f"{named} shares {share.file} from {share.folder}, which {said}: a share is read from a "
                          "finished run", (view.command(JOB_STATUS, dir=str(made)),), code="shares-unfinished",
                          subject=str(made))
        outputs = persist.read_record(newest.run / names.record(OUTPUTS), runs.CHECKS[OUTPUTS])
        want = outputs.value.files.get(share.file) if outputs.reads else None
        have = persist.sha256(newest.run / share.file)
        if want is None or have != want:
            said = "records no SHA-256 of it" if want is None else f"recorded {want}, and it is {have or 'not there'} now"
            raise Refused(f"{share.file} in {share.folder}'s {newest.run.name} is not what that run made: it {said}",
                          code="shares-changed", subject=str(newest.run / share.file))
        paths.append(os.path.relpath(newest.run / share.file, run))
    text_ = persist.read_text(folder / names.name("script")) or ""
    return Opening(folder=folder, named=named, run=run, refill=pending, files=files,
                   script=script.with_shares(text_, paths))


def launching(ctx: Context, req: LaunchRequest) -> Launching:
    """What `job launch` opens and starts for the folder ``req.dir`` (jobs.md § 5), refused whole
    before anything is written."""
    _flags(req)
    inside = _inside(ctx, req)
    folder, named, files = Path(req.dir).resolve(), req.dir, layout.read_once(ctx)
    if not (folder / files.name("request")).is_file():
        raise UsageError(f"{named} holds no {files.name('request')}: it is no calculation folder",
                         code="no-request", subject=named)
    request = runs.request_of(ctx, folder)
    f = launchable(ctx, folder, named, inside)
    p: Prepared = f.prepared.value
    copy = record.read(folder / files.name("machine"))
    kind = catalogue.schedulers(ctx).get(copy.scheduler.kind)
    if kind is None:
        raise UsageError(f"{named} is prepared for {p.target}, whose scheduler kind {copy.scheduler.kind!r} femkit has "
                         "no kind file for", code="no-such-kind", subject=copy.scheduler.kind)
    if not sends(kind) and inside is None:
        if req.foreground:
            raise UsageError(f"{named} is prepared for {p.target}, which has a scheduler: its job is not waited on here",
                             code="foreground-scheduler", subject="--foreground")
        raise Refused(f"{named} is prepared for {p.target}, which has the scheduler {copy.scheduler.kind}: submitting "
                      "to a scheduler is not built yet", code="not-built", subject=p.target)
    if not record.of_this_machine(copy):
        local = record.own()
        this = f"this is {record.shown(local.identity)}" if local is not None else \
            "this machine has no record of its own that loads"
        raise Refused(f"{named} is prepared for {p.target}, the machine {record.shown(copy.identity)}; {this}",
                      record_steps(ctx, LOCAL) if local is None else (), code="not-this-machine", subject=p.target)
    out = Launching(folder=folder, named=named, request=request, target=p.target, identity=record.host_identity(),
                    inside=inside)
    if request.walk is None:
        o = opening(ctx, folder, named, f, inside)
        if isinstance(o, Left):
            out.left.append(o)
        else:
            out.openings.append(o)
        return out
    for v in folders.walk(ctx, folder):
        if v.depth != 1:                  # its own members and parts: each part's are its own launch's
            continue
        listed, member, member_named = v.listed, v.folder, str(v.folder)
        if v.request is None:
            folders.request(ctx, member, member_named)          # refused, as its reader says
        try:
            mf = launchable(ctx, member, member_named, inside, folder)
        except Refused as exc:
            if inside is not None and exc.code == "held":
                out.left.append(Left(member_named, str(exc)))
                continue
            raise
        _apart(member, member_named, mf.prepared.value, folder, p.target)
        out.listed.append((listed, member))
        if request.members is not None:
            o = opening(ctx, member, member_named, mf, inside)
            if isinstance(o, Left):
                out.left.append(o)
                out.listed.pop()
            else:
                out.openings.append(o)
    target = script_target(p.target, copy, kind)
    if request.members is not None:
        out.walk = script.render(script.Batch(name=request.name, target=target, files=files,
                                              resources=request.resources,
                                              members=tuple((name, o.run) for (name, _), o in
                                                            zip(out.listed, out.openings))))
    else:
        control = target_environment(ctx, p.target, copy, dirs.CONTROL)   # femkit's own, by its name (jobs.md § 4.2)
        out.walk = script.render(script.Sequence(name=request.name, target=target, files=files,
                                                 resources=request.resources,
                                                 control=control, folder=folder, parts=tuple(out.listed)))
    return out


# ------------------------------------------------------------------ doing it

def fill(ctx: Context, o: Opening) -> None:
    """One run filled: a pending one emptied whole first; every file a real copy (jobs.md § 2)."""
    if o.refill:
        persist.empty_folder(o.run)
    else:
        persist.make_folder(o.run)
    for name, source in o.files.items():
        (persist.copy_tree if source.is_dir() else persist.copy_file)(source, o.run / name)
    persist.atomic_write_text(o.run / layout.read_once(ctx).name("script"), o.script)


def environment(ctx: Context) -> dict[str, str]:
    """What a job is started in: the launch's own environment, the claim set (jobs.md § 4, block 3)."""
    return {**ctx.env, script.LAUNCHED_BY: script.CLAIM}


@dataclass
class Started:
    """What a launch started, and the records it wrote."""

    job: Job
    child: process.Child | None           # the job waited on; None in the background
    runs: list[Path]
    address: str | None                   # the address written; None inside a sequence


def start(ctx: Context, l: Launching, foreground: bool) -> Started:
    """The job started — the run script in its run, or the walk in its launch folder — in the
    background in a session of its own, or waited on in this launch's own process group; then
    `launched.json` into each run, a launch folder's launch record, and the job's address (§ 5.4)."""
    where, files = l.started, layout.read_once(ctx)
    if l.walk is not None:
        persist.atomic_write_text(l.folder / files.name("walk"), l.walk)
    argv = ["bash", str(where / files.name("script")), str(where)]
    child = None
    if foreground:
        child = process.Child.start(argv, env=environment(ctx), cwd=where, own_group=False)
        identity = child.identity
    else:
        identity = process.start_detached(argv, env=environment(ctx), cwd=where)
    own = Job.of(record.host_identity(), identity)
    job = l.inside.record.job if l.inside else own        # a part's runs ride the sequence's job
    when = clock.stamp(ctx.now())
    started = [o.run for o in l.openings]
    for run in started:
        runs.write(run / files.name("launched"), Launched(time=when, identity=l.identity, job=job))
    if l.request.members is not None:
        listed = [Listed(folder=name, runs=[folders.from_here(l.folder, o.run)])
                  for (name, _), o in zip(l.listed, l.openings)]
    else:
        listed = [Listed(folder=name) for name, _ in l.listed]
    if l.request.walk is not None:
        runs.write(l.folder / files.name("launch_record"),
                   LaunchRecord(time=when, identity=l.identity, job=job, listed=listed))
    if l.inside is not None:
        _ridden(ctx, l)
        addresses.add_runs(l.inside.record.job.id, started)
        return Started(job=job, child=child, runs=started, address=None)
    a = addresses.Address(id=own.id, how="waited on" if foreground else "background", host=own.host, job=own,
                          folder=str(l.folder), runs=[str(r) for r in started],
                          sequence=[str(p) for _, p in l.listed] if l.request.sequence is not None else None,
                          time=when)
    addresses.write(a)
    return Started(job=own, child=child, runs=started, address=a.id)


def _ridden(ctx: Context, l: Launching) -> None:
    """A part's launch inside a sequence adds the runs it started to that part's entry of the
    sequence's launch record, from which each reader reads them as runs of its job (§ 4.2)."""
    seq = l.inside.folder
    held = folders.launch_record(ctx, seq)
    if not held.reads:
        return
    rec: LaunchRecord = held.value
    started = [folders.from_here(seq, o.run) for o in l.openings]
    listed = [e.model_copy(update={"runs": [*e.runs, *started]}) if folders.at(seq, e.folder) == l.folder else e
              for e in rec.listed]
    runs.write(seq / layout.read_once(ctx).name("launch_record"), rec.model_copy(update={"listed": listed}))


def waited(ctx: Context, s: Started) -> tuple[list[runs.Seen], bool]:
    """A job waited on, to its end: each run read once, and whether it closed. Stopped at its
    terminal, it waits up to twice the run script's 10 seconds for the run to close; a run not
    closed by then keeps its address for `job list` (jobs.md § 5)."""
    closed = True
    try:
        s.child.wait()
    except KeyboardInterrupt:
        try:
            closed = s.child.wait(CLOSE) is not None
        except KeyboardInterrupt:
            closed = False
    every = s.runs
    if s.address is not None:
        held = addresses.find(s.address)
        if held.reads:
            every = [Path(r) for r in held.value.runs]
    seen = [runs.observe(ctx.fresh(), run) for run in every]
    if closed and s.address is not None:
        addresses.remove(s.address)
    return seen, closed


# ------------------------------------------------------------------ cancel (jobs.md § 5.4)

@dataclass
class Cancelling:
    """The job a cancel stops: its address, and the runs it holds that have not ended."""

    address: addresses.Address
    going: bool
    runs: list[Path]


def cancelling(ctx: Context, job_id: str) -> Cancelling:
    """The job ``job_id`` names, checked to be the process launched; refused for no such job, one
    launched on another host, one waited on, or a process that is not the one launched."""
    held = addresses.find(job_id)
    if not held.there:
        raise UsageError(f"no job {job_id} was launched from this machine", (view.command(JOB_LIST),),
                         code="no-such-job", subject=job_id)
    if not held.reads:
        raise Refused(f"the address of {job_id} does not read: {held.problem}", code="unreadable",
                      subject=str(addresses.path(job_id)))
    a: addresses.Address = held.value
    if a.host != record.host_identity():
        raise Refused(f"{job_id} was launched on {a.host}: ask there", code="other-host", subject=a.host)
    if a.how == "waited on":
        raise Refused(f"{job_id} is waited on at its terminal: stop it there, with Ctrl-C", code="waited-on",
                      subject=job_id)
    now = process.identify(a.job.pid)
    if now is not None and now != a.job.identity():
        raise Refused(f"process {a.job.pid} is not the one launched as {job_id}: that job has ended",
                      (view.command(JOB_LIST),), code="not-the-job", subject=job_id)
    going = a.job.identity().alive()
    left = [Path(r) for r in a.runs if not (Path(r) / layout.read_once(ctx).name("ended")).exists()]
    return Cancelling(address=a, going=going, runs=left)


def cancel(ctx: Context, c: Cancelling) -> bool:
    """One SIGTERM to the job's process group, through the core's one signal for a run launched
    earlier; then `cancel.json` into each run it holds that has not ended. False when it had ended."""
    if not process.signal(c.address.job.identity(), signal.SIGTERM, group=True):
        return False
    when, files = runs.Cancelled(time=clock.stamp(ctx.now())), layout.read_once(ctx)
    for run in c.runs:
        if run.is_dir() and not (run / files.name("ended")).exists():
            runs.write(run / files.name("cancel"), when)
    return True
