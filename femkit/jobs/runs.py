"""The run door (jobs.md §§ 5.1–5.3): a run's records, each read by its one model; the facts
gathered from them; its state by the rules `femkit/data/states/run.toml` declares; and the job's
word, asked once and written once.

Every reader of a run's state reads it here — `job status`, `job list`, a launch, and every
reader above the jobs domain. A run with no `ended.json`, launched from this machine, is asked
whether its job is still going — by its process: host, process ID, start time and boot ID — and
a job found over is written into the run as `gone.json`, under its calculation folder's lock
taken for that write alone, so the run reads `failed` from then on wherever the folder is copied.
A lock held, or a disk that refuses the write, is said on the run's words, never a crash. A run
launched from another machine is not asked, and reads as its files say.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field

from femkit.core import clock, persist, process, states, text
from femkit.core.errors import Busy
from femkit.core.locks import subject_lock
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, Model, load_toml
from femkit.definitions import catalogue
from femkit.engines.stages.documents import CHECKED, OUTPUTS
from femkit.engines.stages.monitor import CLOSED
from femkit.jobs import layout, record
from femkit.jobs.request import JobRequest, context, wall_seconds


# ------------------------------------------------------------------ the records (jobs.md § 5.1)

class Job(Model):
    """The job a run rides: on a machine without a scheduler, the process its launch started — the
    run script, or the walk of the batch or sequence it is a member or a part of."""

    host: str = Field(description="the host it runs on")
    pid: int = Field(description="its process ID")
    start: int = Field(description="its start time, in clock ticks since boot")
    boot: str = Field(description="the kernel's boot ID")

    def identity(self) -> process.Identity:
        return process.Identity(self.pid, self.start, self.boot)

    @classmethod
    def of(cls, host: str, identity: process.Identity) -> "Job":
        return cls(host=host, pid=identity.pid, start=identity.start, boot=identity.boot)

    @property
    def id(self) -> str:
        """How `job list` and `job cancel` name it: `<host>-<pid>` (jobs.md § 5.4)."""
        return f"{self.host}-{self.pid}"


class Launched(Model):
    """`launched.json`, written by `job launch` once the start succeeded."""

    time: str = Field(description="when it went")
    identity: str = Field(description="the identity of the machine it was launched from")
    job: Job = Field(description="the job it rides: the run script's process, or its walk's")
    wall: str | None = Field(default=None, description="the wall a queue job was sent with (plan § 4, M4); a run "
                                                       "here is sent with none")


class Started(Model):
    """`started.json`, written by the run script, its first write (jobs.md § 4, block 4): every
    value the scheduler granted as its variable held it."""

    time: str = Field(description="when the run started")
    host: str = Field(description="the host it runs on")
    id: str | None = Field(default=None, description="the scheduler's job ID")
    ranks: str | None = Field(default=None, description="the ranks granted")
    cores_per_rank: str | None = Field(default=None, description="the cores per rank granted")
    cores_on_node: str | None = Field(default=None, description="the cores on the node granted")
    gpus: str | None = Field(default=None, description="the GPUs granted")
    nodes: str | None = Field(default=None, description="the nodes granted")
    gpu_model: str | None = Field(default=None, description="the GPU model the driver reports; no count")


class Ended(Model):
    """`ended.json`, written by the run script: how the command ended, or why the script stopped
    before its end — never on a stop signal (jobs.md § 4, blocks 6 and 14)."""

    status: int = Field(description="the command's exit status, or the script's own when it stopped before its end")
    time: str = Field(description="when it ended")
    reason: str | None = Field(default=None, description="why it stopped before its end; null when it did not")


class Checked(Model):
    """`checked.json`, the contract's verdict on what the command left, written by the check
    (jobs.md § 2; § 4, block 13), in the shape of the stage programs' documents
    (`femkit/engines/stages/documents.py`, `checked`), the one home of its fields."""

    schema_: int = Field(alias="schema", description="the documents' schema it was written at")
    passed: bool = Field(description="whether the check held")
    reason: str | None = Field(default=None, description="why it did not; null when passed")


class Outputs(Model):
    """`outputs.json`, written by the check once it passed: each output's SHA-256 (jobs.md § 2), in
    the shape of the stage programs' documents (`outputs`)."""

    schema_: int = Field(alias="schema", description="the documents' schema it was written at")
    files: dict[str, str] = Field(description="each output the request lists, with its SHA-256")


class Gone(Model):
    """`gone.json`, the job's word, written once by the first reader that finds the job over
    with no `ended.json` (jobs.md § 5.1)."""

    time: str = Field(description="when it was asked")
    where: str = Field(description="the machine it was asked on")
    found: str = Field(description="what it found")


class Cancelled(Model):
    """`cancel.json`, written by `job cancel` once its signal was sent (jobs.md § 5.4)."""

    time: str = Field(description="when the signal was sent")


#: Each record a run's facts read that its launch, its run script and its readers write, by its role in
#: the catalogue: its model.
RECORDS: dict[str, type[Model]] = {"launched": Launched, "started": Started, "ended": Ended, "gone": Gone,
                                   "cancel": Cancelled}
#: Each record a stage's check writes, by the stage programs' document it holds — named there once,
#: `documents.RECORDS` — its file the one the catalogue says holds it (jobs.md § 5.1): its model.
CHECKS: dict[str, type[Model]] = {CHECKED: Checked, OUTPUTS: Outputs}


def write(file: Path, record: Model) -> Path:
    """A record, written whole by its one writer."""
    return persist.write_json(file, record.model_dump(mode="json", by_alias=True))


def request_of(ctx: Context, folder: Path) -> JobRequest:
    """A request — a calculation folder's, a launch folder's, a run's own copy — by the one
    reader, its names held to the catalogue's (jobs.md § 2); a `DefinitionError` when it does
    not load."""
    files = layout.read_once(ctx)
    return load_toml(folder / files.name("request"), JobRequest, context(files.reserved()))


# ------------------------------------------------------------------ a calculation folder's runs

def runs(ctx: Context, folder: Path) -> list[Path]:
    """Every run of the folder, oldest first."""
    if not folder.is_dir():
        return []
    files = layout.read_once(ctx)
    found = [(n, p) for p in folder.iterdir() if p.is_dir() and (n := files.run_number(p.name)) is not None]
    return [p for _, p in sorted(found)]


def next_run(ctx: Context, folder: Path) -> Path:
    """Where the folder's next start goes: one past its last."""
    taken, files = runs(ctx, folder), layout.read_once(ctx)
    return folder / files.run_name(files.run_number(taken[-1].name) + 1 if taken else 1)


def subject(folder: Path) -> str:
    """The lock of a calculation or launch folder, wherever it lies (jobs.md § 5; core.md § 5):
    `job-` and the first 16 hexadecimal digits of the SHA-256 of its resolved path."""
    return "job-" + persist.digest(str(Path(folder).resolve()))[:16]


# ------------------------------------------------------------------ facts and the state machine

@dataclass
class RunFacts:
    """What is observed of one run: its records, the job's word, and its own newest write."""

    run: Path
    here: str                                 # this machine's identity
    now: datetime
    files: layout.Catalogue                   # what each record of it is named
    records: dict[str, persist.Read] = field(default_factory=dict)
    check_stated: bool = True                 # its own job.toml states a check, or does not read
    closed: bool = False                      # the monitor's closing record is in monitor.log
    newest_write: float | None = None         # its newest own write, in seconds since the epoch
    asked: str | None = None                  # what asking for the job's word met that could not be written

    def __getitem__(self, role: str) -> persist.Read:
        return self.records[role]

    @property
    def launched(self) -> Launched | None:
        return self["launched"].value

    @property
    def wall_passed(self) -> bool:
        """Started, sent with a wall, and its newest own write older than that wall (jobs.md
        § 5.2, rule 6): a job cannot run past it, so a run silent that long is over."""
        launched = self.launched
        seconds = wall_seconds(launched.wall) if launched is not None and launched.wall else None
        if seconds is None or not self["started"].there or self.newest_write is None:
            return False
        return self.now.timestamp() - self.newest_write > seconds


BINDING = states.Binding("run", {
    "launched_unreadable": lambda f: f["launched"].there and not f["launched"].reads,
    "launched": lambda f: f["launched"].there,
    "ended_ok": lambda f: f["ended"].reads and f["ended"].value.status == 0,
    "ended_not_ok": lambda f: f["ended"].there and not (f["ended"].reads and f["ended"].value.status == 0),
    "checked_passed": lambda f: f[CHECKED].reads and f[CHECKED].value.passed,
    "checked_not_passed": lambda f: f[CHECKED].there and not (f[CHECKED].reads and f[CHECKED].value.passed),
    "checked": lambda f: f[CHECKED].there,
    "check_stated": lambda f: f.check_stated,
    "job_over": lambda f: f["gone"].there,
    "monitor_closed": lambda f: f.closed,
    "wall_passed": lambda f: f.wall_passed,
    "started": lambda f: f["started"].there,
}, values={"dir": lambda f: str(f.run.parent)},   # the run's calculation folder
   reads=frozenset({"pending", "queued", "running", "finished", "failed", "unreadable"}),
   drawn=True)


def machine(ctx: Context) -> states.Machine:
    """The machine `femkit/data/states/run.toml` declares, bound to these facts (jobs.md § 5.2)."""
    return catalogue.machine(ctx, BINDING)


def _records(files: layout.Catalogue, run: Path) -> dict[str, persist.Read]:
    return {**{role: persist.read_record(run / files.name(role), model) for role, model in RECORDS.items()},
            **{kind: persist.read_record(run / files.record(kind), model) for kind, model in CHECKS.items()}}


def _check_stated(ctx: Context, run: Path) -> bool:
    try:
        return request_of(ctx, run).check is not None
    except DefinitionError:
        return True        # a request that does not read cannot say it states none


def _closed(files: layout.Catalogue, run: Path) -> bool:
    held = persist.read_text(run / files.name("monitor_log"))
    return held is not None and any(CLOSED in line for line in held.splitlines())


def _newest_write(files: layout.Catalogue, run: Path) -> float | None:
    own = files.own()
    times = [p.stat().st_mtime for p in run.iterdir() if p.name in own and p.is_file()] if run.is_dir() else []
    return max(times) if times else None


def facts(ctx: Context, run: Path, here: str, now: datetime) -> RunFacts:
    """What is observed of ``run`` from its files alone."""
    files = layout.read_once(ctx)
    return RunFacts(run=run, here=here, now=now, files=files, records=_records(files, run),
                    check_stated=_check_stated(ctx, run), closed=_closed(files, run),
                    newest_write=_newest_write(files, run))


def ask(ctx: Context, f: RunFacts) -> RunFacts:
    """The job's word, asked once and written once (jobs.md § 5.1): for a run with no `ended.json`
    and no word yet, launched from this machine, whether its job is still going; a job found over
    is written into the run as `gone.json`, under its calculation folder's lock taken for that
    write alone. What the write could not do is kept, to be said; the word holds all the same."""
    launched = f.launched
    if f["ended"].there or f["gone"].there or launched is None or launched.identity != f.here:
        return f
    job = launched.job
    if job.identity().alive():
        return f
    found = (f"its process {job.pid} on {job.host} has ended" if f["started"].there
             else f"its process {job.pid} on {job.host} ended before the run started")
    gone = Gone(time=clock.stamp(f.now), where=f.here, found=found)
    try:
        with subject_lock(subject(f.run.parent)):
            if not (f.run / f.files.name("ended")).exists():   # read again under the lock: written since?
                write(f.run / f.files.name("gone"), gone)
    except Busy as exc:
        f.asked = f"the job's word is not written: {exc}"
    except OSError as exc:
        f.asked = f"the job's word is not written: {exc.strerror or exc}"
    return facts(ctx, f.run, f.here, f.now) if f.asked is None else _with_word(f, gone)


def _with_word(f: RunFacts, gone: Gone) -> RunFacts:
    """The facts, with the job's word that could not be written held as read."""
    records = {**f.records, "gone": persist.Read(True, gone)}
    return RunFacts(run=f.run, here=f.here, now=f.now, files=f.files, records=records, check_stated=f.check_stated,
                    closed=f.closed, newest_write=f.newest_write, asked=f.asked)


@dataclass(frozen=True)
class Seen:
    """One run as every reader shows it: its state, in its words."""

    run: Path
    state: Enum
    words: str
    facts: RunFacts


def observe(ctx: Context, run: Path) -> Seen:
    """A run's state and its words, the job's word asked and written once (jobs.md §§ 5.1, 5.2)."""
    f = ask(ctx, facts(ctx, run, record.host_identity(), ctx.now()))
    m = machine(ctx)
    state = m.observe(f)
    return Seen(run=run, state=state, words=words(f, state, m), facts=f)


def words(f: RunFacts, state: Enum, m: states.Machine) -> str:
    """What a person reads beside a run's state (jobs.md § 5.2): for `failed`, the evidence that
    says so — how it ended, its verdict, the job's word, the monitor's closing record — with
    *never started* or *cancelled* where its records say so."""
    out: list[str] = []
    if state is m.states.unreadable:
        out.append(f"{f.files.name('launched')} {f['launched'].problem}")
    elif state is m.states.pending:
        out.append("opened, never launched")
    elif state is m.states.queued:
        out.append("launched, not started yet")
    elif state is m.states.running:
        out.append(_running(f))
    elif state is m.states.finished:
        out.append("ended, exit 0" + (", its check passed" if f[CHECKED].reads else ""))
    else:
        out += _failed(f)
    if f.asked:
        out.append(f.asked)
    return "; ".join(out)


def _running(f: RunFacts) -> str:
    said = "running"
    if f.newest_write is not None:
        said += f", last wrote {text.duration(max(0.0, f.now.timestamp() - f.newest_write))} ago"
    launched = f.launched
    if launched is not None and launched.identity != f.here:
        said += f"; launched on {launched.identity}: ask on that machine"
    return said


def _failed(f: RunFacts) -> list[str]:
    """The evidence that a run failed, in the order of evidence."""
    out: list[str] = []
    ended, checked = f["ended"], f[CHECKED]
    if ended.there and not ended.reads:
        out.append(f"{f.files.name('ended')} {ended.problem}")
    elif ended.reads:
        e = ended.value
        out.append(f"exit {e.status}" + (f": {e.reason}" if e.reason else ""))
    if checked.there and not checked.reads:
        out.append(f"{f.files.record(CHECKED)} {checked.problem}")
    elif checked.reads and not checked.value.passed:
        out.append(f"its check did not hold: {checked.value.reason or 'no reason given'}")
    elif ended.reads and ended.value.status == 0 and f.check_stated and not checked.there:
        out.append("its check stopped before its verdict")
    if out:
        return out
    cancelled = f["cancel"].there
    if f["gone"].there:
        gone = f["gone"].value
        if not f["started"].there:
            out.append("never started" + (f": {gone.found}" if gone else ""))
        else:
            out.append("stopped before its end" + (f": {gone.found}" if gone else ""))
    elif f.closed:
        out.append("stopped before its end: no exit recorded")
    else:
        out.append("stopped before its end: nothing was written for longer than its time limit")
    if cancelled:
        out.append("cancelled")
    return out


def newest(ctx: Context, folder: Path) -> Seen | None:
    """The folder's newest run, observed; None when it has none."""
    found = runs(ctx, folder)
    return observe(ctx, found[-1]) if found else None


def output(run: Path, name: str) -> Path:
    """Where the output ``name`` a request lists lies in ``run``, by its name there (jobs.md § 2)."""
    return run / name


def own_files(ctx: Context, run: Path) -> list[str]:
    """The files a run left: everything in it but what its launch copied in."""
    copied = set(layout.read_once(ctx).copied())
    try:
        req = request_of(ctx, run)
        copied |= set(req.inputs) | set(req.programs)
    except DefinitionError:
        pass
    if not run.is_dir():
        return []
    return sorted(p.relative_to(run).as_posix() for p in run.rglob("*")
                  if p.is_file() and p.relative_to(run).parts[0] not in copied)

