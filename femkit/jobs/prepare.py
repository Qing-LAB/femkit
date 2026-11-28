"""Preparing a calculation folder, or a launch folder whole, for its target (jobs.md § 3).

The target is the calculation's own copy of its machine's record, `machine.toml`, taken at its
first prepare and never changed: a later prepare reads the copy. Every missing statement, and one
that contradicts the record, is refused; what the record says of the request — an environment not
installed there, a request no node holds — is shown as a warning, and the folder is prepared as
asked (framework.md § 4). Nothing here probes, and only `commit` writes: `prepare` returns what
`job prepare`'s apply writes, so a refusal writes nothing. A batch or a sequence is prepared whole:
every member and part for the launch folder's target, each with its own run script and, for a
launch folder, its record copy and `prepared.json` alone — its walk is written by the launch that
sends it.

A prepare planned in memory (`planned`) runs the same steps on requests a maker holds, for folders
it has not written yet or whose requests it states again — each given, by its folder, the rest read
from disk — so a maker that writes many folders, `study prep`, plans every prepare before it writes
any; it writes each new folder whole with the files its prepare writes (`files_of`, through
`folders.write`), and commits each existing one's as `job prepare` does (`commit`). What every job
on a target needs of its record, whatever it runs — its activation stated, a manager kind femkit
has — is `record_checked`, the step a maker checks the machine by before anything else. What writes
this machine's record is said from one source, `record_steps`, which `doctor`, the target's
refusals and a stage's missing fingerprint read — `config init` first while a key the person states
is unset, by config's one builder of that step (`settings.steps`, config.md § 3.2). The codes of
the target's refusals are exported here, where they are raised, so a maker tells them apart by kind
and code (core.md § 9).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Callable, Iterable, Mapping

from femkit.config import settings
from femkit.core import persist, text, view
from femkit.core.errors import Refused, Unstated, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.schema import Measure, Number
from femkit.core.units import MEMORY_LETTERS
from femkit.definitions import catalogue
from femkit.definitions.models import SchedulerKind
from femkit.envs import start, state as env_state
from femkit.envs.manager import entering
from femkit.envs.requests import ENV_LIST
from femkit.jobs import folders, layout, record, script
from femkit.jobs.folders import Prepared
from femkit.jobs.record import LOCAL, Record, Unknown
from femkit.jobs.request import QUEUE, SCHEDULER, SHARED, JobRequest, Resources, wall_seconds
from femkit.jobs.requests import JOB_MACHINES, JOB_PREPARE

TARGET = "--target"   # how a refusal names the option that chose a target (jobs.md § 3)
#: The codes of the target's refusals (jobs.md § 3, step 2): another machine's record there and none
#: named; no record of the target — the one `--target` names, or this machine's; this machine's
#: record stale.
TARGET_UNCHOSEN, NO_RECORD, STALE = "target-unchosen", "no-record", "stale"


@dataclass(frozen=True)
class Target:
    """The machine a folder is prepared for: its record's name, the record, and the record file a
    first prepare copies — None when the folder holds its copy already."""

    name: str
    record: Record
    copy: Path | None
    here: bool                     # the record is this machine's

    @property
    def machine(self) -> view.Machine | None:
        """The machine a step for the target is for, where it is not this one (web.md § 7.2): what
        `view.command` takes a step there by."""
        return None if self.here else view.Machine(self.name)


@dataclass
class Writing:
    """One folder, prepared: what apply writes into it — the record's copy on a first prepare, the
    programs, the run script, then prepared.json, last."""

    folder: Path
    named: str
    copy: Path | None              # the record the first prepare copies; None: the folder's copy stays
    sources: dict[str, Path]       # each program and module copied in, by its name, from its source
    script: str | None             # the run script; none for a launch folder, whose walk its launch writes
    prepared: Prepared

    def held(self) -> dict:
        """As a plan holds it, JSON (api.md § 3, `holds`)."""
        return {"path": str(self.folder), "named": self.named, "copy": str(self.copy) if self.copy else None,
                "sources": {n: str(s) for n, s in self.sources.items()}, "script": self.script,
                "prepared": self.prepared.model_dump(mode="json")}

    @classmethod
    def of(cls, held: dict) -> "Writing":
        """As `held` gave it."""
        return cls(folder=Path(held["path"]), named=held["named"], copy=Path(held["copy"]) if held["copy"] else None,
                   sources={n: Path(s) for n, s in held["sources"].items()}, script=held["script"],
                   prepared=Prepared.model_validate(held["prepared"]))


@dataclass
class Preparation:
    """What `job prepare` writes, for which target, every finding it shows, and whether a launch here
    can send the job it prepares — never for another machine's target, nor one whose scheduler
    femkit cannot submit to yet (`launches`)."""

    target: str
    folders: list[Writing] = field(default_factory=list)    # members and parts first, the folder named last
    issues: list[Issue] = field(default_factory=list)
    launches: bool = False


def probe(ctx: Context, name: str) -> view.Action:
    """The probe that writes the record ``name``, run on the machine it describes, as the record's
    table declares it for its state (jobs.md § 9.3) — observed without comparing its settings, which
    only a record of this machine has: every state's, a current one's measuring it again — on that
    machine, for any record not this machine's (`record.of_this_machine`): on a cluster, its own
    record `cluster-a` is probed there, where the step is typed."""
    m = record.machine(ctx)
    f = record.facts(record.path(name), None)
    step = m.allowed(m.observe(f))[record.PROBE].next(f)
    return view.at(step, None if record.of_this_machine(name) else view.Machine(name))


def record_steps(ctx: Context, name: str) -> tuple[view.Action, ...]:
    """What writes this machine's record ``name`` (envs.md § 6.1; workflow.md § 7) — the one source
    `doctor`'s row, the target's refusals and a stage's missing fingerprint read: `config init`
    first, asking each key the person states that is unset, since the probe is refused until then
    (jobs.md § 9.2); then the steps the record machine's table gives its state — a current
    record's, measuring it again where its environments changed since (jobs.md § 9.3)."""
    config = settings.load(ctx).config
    state, _, f = record.status(ctx, record.path(name), config)
    return (*settings.steps(settings.unstated(config, record.COPIED)), *record.machine(ctx).next(state, f))


# ------------------------------------------------------------------ step 2: the target

def target(ctx: Context, folder: Path, named: str, asked: str | None) -> Target:
    """The calculation's own copy of its target's record (jobs.md § 3, step 2): read from the folder
    once a prepare has committed; else taken from the record `--target` names, or `local` when no
    record of another machine is there."""
    p = folders.prepared(ctx, folder)
    if p.reads:
        copy = record.read(folder / layout.read_once(ctx).name("machine"))
        name = p.value.target
        if asked is not None and asked != name:
            other = record.read(_named_record(ctx, asked))
            if other.identity != copy.identity:
                raise Refused(f"{named} is prepared for {name}; {asked} is another machine, and a second target is a "
                              "second calculation", (view.command(JOB_PREPARE, dir=named),),
                              code="target-other", subject=TARGET)
        return Target(name=name, record=copy, copy=None, here=record.of_this_machine(copy))
    return choose(ctx, asked, lambda n: view.command(JOB_PREPARE, dir=named, target=n))


def choose(ctx: Context, asked: str | None, again: Callable[[str], view.Action]) -> Target:
    """The record a first prepare takes (jobs.md § 3, step 2) — the jobs domain's one choice of a
    target, which a stage's identity is formed with too (workflow.md § 3): the one `--target`
    names, or `local` when no record of another machine is there — another machine's being one
    whose identity of the host is not this machine's (`record.of_this_machine`), or one that does
    not load, whose machine cannot be told; refused, `target-unchosen`, when one is, each record's
    ``again`` its next step — the command typed again naming it; a target with no record, or a
    record of this machine that is `stale`, refused."""
    if asked is None:
        found = record.listing()
        others = sorted(n for n, *_ in found if not record.of_this_machine(n))
        if others:
            raise Unstated(f"records of other machines are here ({', '.join(others)}): name the machine to prepare "
                           "for", tuple(again(n) for n, *_ in found), code=TARGET_UNCHOSEN, subject=TARGET)
        file = record.path(LOCAL)
        if not file.is_file():
            raise Unstated(f"there is no record of this machine in {text.path(record.machines_dir())}",
                           record_steps(ctx, LOCAL), code=NO_RECORD, subject=LOCAL)
        name = LOCAL
    else:
        file, name = _named_record(ctx, asked), asked
    r = record.read(file)
    here = record.of_this_machine(r)
    if here and (drift := record.stale(r, settings.load(ctx).config)):
        raise Refused(f"the record {name} is stale — {'; '.join(drift)}", record_steps(ctx, name), code=STALE,
                      subject=name)
    return Target(name=name, record=r, copy=file, here=here)


def _named_record(ctx: Context, asked: str) -> Path:
    file = record.path(asked)
    if not file.is_file():
        raise UsageError(f"there is no record {asked!r} in {text.path(record.machines_dir())}",
                         (view.command(JOB_MACHINES), probe(ctx, asked)), code=NO_RECORD, subject=TARGET)
    return file


def _member_target(ctx: Context, t: Target, folder: Path, named: str) -> Target:
    """A member's or part's own copy: the launch folder's target, the same machine."""
    p = folders.prepared(ctx, folder)
    if not p.reads:
        return Target(name=t.name, record=t.record, copy=t.copy or record.path(t.name), here=t.here)
    copy = record.read(folder / layout.read_once(ctx).name("machine"))
    if copy.identity != t.record.identity:
        raise Refused(f"{named} is prepared for {p.value.target}, another machine than {t.name}: a second target is a "
                      "second calculation", (view.command(JOB_PREPARE, dir=named),), code="target-other",
                      subject=named)
    return Target(name=p.value.target, record=copy, copy=None, here=t.here)


# ------------------------------------------------------------------ step 3: statements

def _kind(ctx: Context, t: Target) -> SchedulerKind:
    kinds = catalogue.schedulers(ctx)
    if t.record.scheduler.kind not in kinds:
        raise UsageError(f"the record {t.name} names the scheduler kind {t.record.scheduler.kind!r}, which femkit has "
                         f"no kind file for (it has: {', '.join(sorted(kinds))})", code="no-such-kind",
                         subject=t.record.scheduler.kind)
    return kinds[t.record.scheduler.kind]


def sends(kind: SchedulerKind) -> bool:
    """Whether a launch outside a job can send a job to a target of the scheduler kind ``kind``: one
    with no scheduler; submitting through one is not built yet (jobs.md §§ 5, 7; plan § 4, M4)."""
    return not kind.commands


def launches(ctx: Context, t: Target) -> bool:
    """Whether a launch can send a job to the target ``t`` (`sends`): what a maker offers as a next
    step, never a launch the target cannot make (workflow.md § 7)."""
    return sends(_kind(ctx, t))


def _activation(ctx: Context, t: Target) -> None:
    """Refused, `setting-unstated`: a record whose activation is unset (jobs.md § 3, step 3)."""
    unset = settings.unstated(t.record.settings, record.COPIED)
    if unset:
        raise Unstated(f"the record {t.name} holds no {' and no '.join(unset)}: every run script runs the preamble "
                       "and enters its environment by them", (*settings.steps(unset, machine=t.machine), probe(ctx, t.name)),
                       code="setting-unstated", subject=unset[0])


def record_checked(ctx: Context, t: Target) -> None:
    """What every job on the target needs of its record, whatever it runs (jobs.md § 3, steps 3, 6;
    workflow.md § 7, the machine step): its activation stated, and a manager kind femkit has —
    each refused as `job prepare` refuses it."""
    _activation(ctx, t)
    _manager(ctx, t.name, t.record)


def statements(ctx: Context, t: Target, kind: SchedulerKind, req: JobRequest, where: str) -> list[Issue]:
    """Refused: a resource the target needs stated nowhere, a queue the record does not list, a
    record whose activation is unset, more than one rank with no `launch.mpi`, or one process
    with more than one rank (jobs.md § 3, step 3). What is not read is said."""
    r, res = t.record, req.resources
    _activation(ctx, t)
    if res.ranks > 1 and req.walk is None and not r.settings.launch.mpi:   # a walk's members are what run ranks
        raise Unstated(f"{res.ranks} ranks are asked for, and the record {t.name} holds no launch.mpi",
                       (*settings.steps(["launch.mpi"], machine=t.machine), probe(ctx, t.name)),
                       code="setting-unstated", subject="launch.mpi")
    if req.one_process and res.ranks != 1:
        raise Refused(f"{where} runs one process, and states {res.ranks} ranks: a request that runs one process "
                      "states `ranks = 1`", code="one-process", subject="resources.ranks")
    if not kind.commands:
        stated = [k for k in Resources.holding(SCHEDULER) if getattr(res, k) is not None]
        return [Issue(severity="info", code="not-read", subject=where,
                      message=f"{t.name} has no scheduler: {', '.join(stated)} {'is' if len(stated) == 1 else 'are'} "
                              "not read")] if stated else []
    missing = [k for k in Resources.holding(SHARED) if k not in Resources.holding(QUEUE) and getattr(res, k) is None]
    if missing:
        raise Unstated(f"{t.name} has a scheduler, and {where} states no {', '.join(missing)}: nothing is defaulted",
                       code="resource-unstated", subject=f"resources.{missing[0]}")
    if res.partition is None:
        raise Unstated(f"{t.name} has a scheduler, and {where} names no queue: `partition`, and `qos` where the "
                       "record lists one for it", code="queue-unstated", subject="resources.partition")
    if not isinstance(r.queues, list) or not r.queues:
        why = r.queues.unknown if isinstance(r.queues, Unknown) else "it lists none"
        raise Unstated(f"the record {t.name} names no queue this account may submit to: {why}", (probe(ctx, t.name),),
                       code="queue-unstated", subject="resources.partition")
    if not any(q.partition == res.partition and q.qos == res.qos for q in r.queues):
        listed = ", ".join(f"{q.partition}/{q.qos or '(no QOS)'} ({_queue_fit(ctx, q, res)})" for q in r.queues)
        known = any(q.partition == res.partition for q in r.queues)
        raise Refused(f"{res.partition}/{res.qos or '(no QOS)'} is not one of {t.name}'s queues: {listed}",
                      code="queue-unknown", subject="resources.qos" if known else "resources.partition")
    return []


def within(member: Resources, job: Resources, named: str) -> None:
    """A member or part of a launch folder runs with what its job holds (jobs.md § 1.2): its queue,
    wall and memory are the job's, and its counts fit inside the job's."""
    differ = [f"{k} {getattr(member, k) or 'unset'}, the job's {getattr(job, k) or 'unset'}"
              for k in Resources.holding(SHARED) if getattr(member, k) != getattr(job, k)]
    if member.cores > job.cores:
        differ.append(f"ranks × threads {member.ranks} × {member.threads} = {member.cores} cores, over the job's "
                      f"{job.cores}")
    if member.gpus > job.gpus:
        differ.append(f"gpus {member.gpus}, over the job's {job.gpus}")
    if differ:
        raise Refused(f"{named} does not run within its job: {'; '.join(differ)}", code="member-differs",
                      subject=named)


# ------------------------------------------------------------------ step 5: the fit

def _mib(ctx: Context, memory: str) -> int:
    """A request's memory in whole MiB, rounded up, as a record keeps memory: its number and its
    letter's unit — the binary multiple it means (`MEMORY_LETTERS`) — read and converted by the unit
    table, the one reader of a quantity (core.md § 11; framework.md § 1, rule 3)."""
    units = catalogue.units(ctx)
    held = units.measure(Measure[Number](value=int(memory[:-1]), unit=MEMORY_LETTERS[memory[-1]]))
    return math.ceil(units.convert(held, record.MEBIBYTE))


def _over_queue(ctx: Context, q: record.Queue, res: Resources) -> list[str]:
    """Each limit of the queue the request is over, with its numbers; a limit not stated, or
    stated `unlimited` or unknown, is not counted (jobs.md § 3, step 5)."""
    over = []
    asked = wall_seconds(res.wall or "")
    limit = wall_seconds(q.max_time) if isinstance(q.max_time, str) else None
    if asked is not None and limit is not None and asked > limit:
        over.append(f"wall {res.wall} over its {q.max_time}")
    for what, wanted, cap in (("cores", res.cores, q.max_cpus),
                              (record.MEBIBYTE, _mib(ctx, res.memory) if res.memory else None, q.max_memory_mib),
                              ("GPUs", res.gpus, q.max_gpus)):
        if isinstance(cap, int) and wanted is not None and wanted > cap:
            over.append(f"{wanted} {what} over its {cap}")
    return over


def _queue_fit(ctx: Context, q: record.Queue, res: Resources) -> str:
    over = _over_queue(ctx, q, res)
    return "within its limits" if not over else "; ".join(over)


def fit(ctx: Context, t: Target, kind: SchedulerKind, res: Resources, where: str) -> list[Issue]:
    """How the request sits on the record, one node holding all of it: a misfit is a warning,
    never a refusal, and the request is never changed (jobs.md § 3, step 5)."""
    r, name = t.record, t.name
    cores, gpus = res.cores, res.gpus
    asked = f"{res.ranks} × {res.threads} = {cores} cores, {text.count(gpus, 'GPU')}"
    if not kind.commands:
        h = r.host
        has_gpus = len(h.gpus) if isinstance(h.gpus, list) else None
        lacks = ([f"{cores} cores, and it has {h.cores}"] if isinstance(h.cores, int) and cores > h.cores else []) + \
                ([f"{gpus} GPUs, and it has {has_gpus}"] if has_gpus is not None and gpus > has_gpus else [])
        shown = f"{asked} on {name}, the host {r.identity if isinstance(r.identity, str) else name}: " \
                f"{h.cores if isinstance(h.cores, int) else 'unknown'} cores, " \
                f"{text.count(has_gpus, 'GPU') if has_gpus is not None else 'GPUs unknown'}"
        return [Issue(severity="warning" if lacks else "info", code="over-host" if lacks else "fit", subject=where,
                      message=shown + (f"; it asks for {', and '.join(lacks)}" if lacks else ""))]
    partitions = r.partitions if isinstance(r.partitions, dict) else {}
    part = partitions.get(res.partition)
    queue = next(q for q in r.queues if q.partition == res.partition and q.qos == res.qos)
    issues = [Issue(severity="warning", code="over-queue", subject=where,
                    message=f"{res.partition}/{res.qos or '(no QOS)'}: {o}") for o in _over_queue(ctx, queue, res)]
    if part is None:
        return issues + [Issue(severity="info", code="fit", subject=where,
                               message=f"{asked}: the record lists no nodes of {res.partition}")]
    memory = _mib(ctx, res.memory) if res.memory else None
    holding, total, lacks = 0, 0, []
    for g in part.node_groups:
        lack = ([f"{g.cores} cores"] if isinstance(g.cores, int) and g.cores < cores else []) + \
               ([f"{g.memory_mib} MiB"] if isinstance(g.memory_mib, int) and memory and g.memory_mib < memory else []) + \
               ([f"{sum(g.gpus.values())} GPUs"] if gpus and isinstance(g.gpus, dict) and sum(g.gpus.values()) < gpus
                else [])   # GPUs the record could not read are no limit (framework.md § 4)
        total += g.count
        holding += 0 if lack else g.count
        lacks += [f"{text.count(g.count, 'node')} with only {', '.join(lack)}"] if lack else []
    share = f"{holding} of {total} nodes of {res.partition} hold it"
    if holding == 0 and total:
        return issues + [Issue(severity="warning", code="fits-no-node", subject=where,
                               message=f"{asked}: no node of {res.partition} holds it — {'; '.join(lacks)}")]
    return issues + [Issue(severity="info", code="fit", subject=where, message=f"{asked}: {share}")]


# ------------------------------------------------------------------ step 4: the environment

def environment(ctx: Context, t: Target, req: JobRequest, where: str) -> tuple[str, str | None, list[Issue]]:
    """The environment the run enters — `<name>-cuda` with GPUs, as the catalogue resolves it
    (`catalogue.with_gpus`, definitions.md § 4.5); refused where it has none — its install
    fingerprint as the record lists it, and what the record says of it (jobs.md § 3, step 4), read
    through the record's one reader of its environments (`record.listed`): not listed — not
    installed there — or listed in a state that does not allow its use, or not GPU-qualified where
    GPUs are asked, each a warning with the next steps the environment's own table gives that state
    — the last, its row that validates the GPU checks — on that machine (envs.md § 3.3)."""
    r, name = t.record, t.name
    env_state.definition(ctx, req.environment)     # refused when femkit has no such environment
    env = catalogue.with_gpus(ctx, req.environment, req.resources.gpus)
    if env is None:
        raise UsageError(f"the request asks {text.count(req.resources.gpus, 'GPU')}, and {req.environment} has no CUDA "
                         "environment", (view.command(ENV_LIST),), code="no-such-environment", subject=req.environment)
    held = record.listed(ctx, r, env)
    if not held.known:
        return env, None, []
    m, there = env_state.machine(ctx), t.machine
    issues: list[Issue] = []
    if held.snapshot is None:
        issues.append(Issue(severity="warning", code="not-installed", subject=where,
                            message=f"{env} is not installed on {name}, as the record measured it at "
                                    f"{r.measured.time}", next=env_state.steps(ctx, env, m.states.absent, there)))
    elif held.state is None or not env_state.allows_use(ctx, held.state):
        issues.append(Issue(severity="warning", code="not-ready", subject=where,
                            message=f"{env} is {held.snapshot.state} on {name}, as the record measured it at "
                                    f"{r.measured.time}",
                            next=env_state.steps(ctx, env, held.state, there) if held.state is not None else ()))
    elif req.resources.gpus and not held.qualified:
        issues.append(Issue(severity="warning", code="not-gpu-qualified", subject=where,
                            message=f"{env}'s GPU checks are {held.snapshot.gpu or 'not run'} on {name}",
                            next=env_state.step(ctx, env, held.state, env_state.VALIDATE_GPU, there)))
    try:   # where no manager is named here, there is no place to look: the record alone is shown (envs.md § 3.1)
        now = env_state.observe(ctx, env)[1] if t.here else None
    except Unstated:
        now = None
    if now is not None:
        if now is not held.state:
            issues.append(Issue(severity="info", code="record-environments", subject=where,
                                message=f"{env} is {now.value} here now; the record {name} has "
                                        f"{held.snapshot.state if held.snapshot else 'none'}",
                                next=(probe(ctx, name),)))
    return env, held.snapshot.install_fingerprint if held.snapshot else None, issues


# ------------------------------------------------------------------ step 6: render

def script_target(name: str, r: Record, kind: SchedulerKind) -> script.Target:
    """What a script needs of the target ``name``'s record."""
    return script.Target(name=name, kind=kind,
                         mpi=tuple(r.settings.launch.mpi) if r.settings.launch.mpi else None)


def _manager(ctx: Context, name: str, r: Record):
    """The manager kind the record ``name`` names, by its name and its kind file; refused,
    `manager-unknown`, where femkit has none for it (jobs.md § 3)."""
    managers = catalogue.load(ctx).managers
    kind_name = r.manager.kind
    if isinstance(kind_name, Unknown) or kind_name not in managers:
        why = kind_name.unknown if isinstance(kind_name, Unknown) else f"femkit has no kind file for {kind_name}"
        raise Unstated(f"the record {name} names no manager femkit can enter an environment with: {why}",
                       (probe(ctx, name),), code="manager-unknown", subject=name)
    return kind_name, managers[kind_name]


def target_environment(ctx: Context, name: str, r: Record, env: str) -> script.Environment:
    """How a job on the target ``name`` enters the environment ``env`` — an engine's or a tool's, or
    femkit's control one (`dirs.CONTROL`): its record's preamble, then its activation of the
    environment by its name with the manager there (envs.md § 1), by its manager's kind
    (definitions.md § 6; jobs.md § 4, block 8), the lines `entering` writes; where it lies there is
    the manager's, asked by the activation."""
    kind_name, kind = _manager(ctx, name, r)
    exe = r.manager.path if isinstance(r.manager.path, str) else None
    managed = catalogue.managed(ctx, env)
    entry = entering(kind_name, kind, exe, managed, r.settings.activation.preamble or (),
                     r.settings.activation.command)
    if entry.problem:
        raise UsageError(f"the record {name}'s activation.command, `{r.settings.activation.command}`, cannot enter "
                         f"an environment there: {entry.problem}", (probe(ctx, name),), code="activation-unusable",
                         subject="activation.command")
    kinds = catalogue.schedulers(ctx)
    held = [kinds[r.scheduler.kind]] if r.scheduler.kind in kinds else []
    return script.Environment(name=env, managed=managed, entry=entry, active=kind.activate.active,
                              start=tuple(start.lines(catalogue.process(ctx), start.jobs(held),
                                                      start.functions(held))))


def sources(ctx: Context, named: Iterable[str]) -> dict[str, Path]:
    """Each of femkit's programs ``named`` and every file a run has beside them — the monitor, the
    modules each program runs with — by its name in a calculation folder, with its source in femkit
    (jobs.md § 1.1): what a folder that runs them holds; refused, `no-such-program`, for a program
    femkit lacks."""
    files = layout.read_once(ctx)
    out: dict[str, Path] = {}
    for name in named:
        source = files.programs_folder() / name
        if not source.is_file():
            raise UsageError(f"femkit has no program {name!r} in {files.programs_folder()}", code="no-such-program",
                             subject=name)
        out[name] = source
    return {**out, **files.beside()}


# ------------------------------------------------------------------ the whole

@dataclass
class Plan:
    """What preparing goes through: the target, its kind, every folder in order, and the requests
    given in memory, each by its folder's full path (`planned`)."""

    target: Target
    kind: SchedulerKind
    out: Preparation
    given: Mapping[Path, JobRequest] = field(default_factory=dict)


def _job(ctx: Context, p: Plan, t: Target, folder: Path, named: str, req: JobRequest, launch: Path | None) -> None:
    """A calculation folder prepared: its run script and programs, for the target."""
    issues = statements(ctx, t, p.kind, req, named)
    issues += fit(ctx, t, p.kind, req.resources, named)
    env, fingerprint, more = environment(ctx, t, req, named)
    issues += more
    job = script.Job(name=req.name, target=script_target(t.name, t.record, p.kind), files=layout.read_once(ctx),
                     resources=req.resources,
                     environment=target_environment(ctx, t.name, t.record, env),
                     definition=env_state.definition(ctx, env),
                     command=tuple(req.command), check=tuple(req.check) if req.check else None,
                     outputs=tuple(req.outputs), shares=tuple(req.shares))
    _written(ctx, p, t, folder, named, req, sources(ctx, req.programs), script.render(job), env, fingerprint, launch,
             issues)


def _written(ctx: Context, p: Plan, t: Target, folder: Path, named: str, req: JobRequest, sources: dict[str, Path],
             text_: str | None, env: str | None, fingerprint: str | None, launch: Path | None,
             issues: list[Issue]) -> None:
    """A folder's writing, and what its prepared.json records: the SHA-256 of each file written."""
    files = layout.read_once(ctx)
    hashes = {name: persist.sha256(source) for name, source in sources.items()}
    hashes[files.name("machine")] = persist.sha256(t.copy or folder / files.name("machine"))
    request = (persist.digest(folders.request_text(ctx, p.given[folder])) if folder in p.given
               else persist.sha256(folder / files.name("request")))
    if text_ is not None:
        hashes[files.name("script")] = persist.digest(text_)
    p.out.issues += issues
    p.out.folders.append(Writing(folder=folder, named=named, copy=t.copy, sources=sources, script=text_,
                                 prepared=Prepared(
        target=t.name, request=request, environment=env,
        install_fingerprint=fingerprint, resources=req.resources, files=hashes,
        launch=folders.from_here(folder, launch) if launch else None)))


def _tree(ctx: Context, p: Plan, t: Target, folder: Path, named: str) -> None:
    """A folder prepared for the target ``t`` — a launch folder whole, by the one walk of its tree
    (`folders.walk`), its requests given in memory or read from disk: each member or part a folder of
    the kind its launch folder holds, within the job's resources, for that one's target; each in a
    state that allows a prepare; a calculation folder's run script and programs, and a launch
    folder's own copy and prepared.json after every folder below it (`Preparation.folders`)."""
    targets: dict[Path, Target] = {}
    requests: dict[Path, JobRequest] = {}
    launches: list[Callable[[], None]] = []         # each launch folder's writing, after every one below it
    for v in folders.walk(ctx, folder, p.given):
        here = named if v.above is None else str(v.folder)
        req = v.request or folders.request(ctx, v.folder, here, p.given)   # refused, as its reader says
        mine = t
        if v.above is not None:
            above = requests[v.above]
            if above.members is not None and req.walk is not None:
                raise UsageError(f"{v.listed} is a launch folder: a batch's members are calculation folders",
                                 code="member-is-launch", subject=here)
            if req.sequence is not None:
                raise UsageError(f"{v.listed} is a sequence: a sequence's parts are batches or calculation folders",
                                 code="part-is-sequence", subject=here)
            within(req.resources, above.resources, here)
            mine = _member_target(ctx, targets[v.above], v.folder, here)
        targets[v.folder], requests[v.folder] = mine, req
        allowed(ctx, v.folder, here)
        if req.walk is None:
            _job(ctx, p, mine, v.folder, here, req, v.above)
            continue
        issues = statements(ctx, mine, p.kind, req, here) + fit(ctx, mine, p.kind, req.resources, here)
        launches.append(partial(_written, ctx, p, mine, v.folder, here, req, {}, None, None, None, v.above, issues))
    for written in reversed(launches):
        written()


def allowed(ctx: Context, folder: Path, named: str) -> None:
    """Refused while a job still going holds the folder, and in a state that allows no prepare —
    a run that goes, a launch folder launched (jobs.md §§ 3, 5.5)."""
    m = folders.machine(ctx)
    f, state = folders.observe(ctx, folder)
    if f.holding is not None:
        raise Refused(f"{named} {f.holding.why}: nothing but that job runs it", m.next(m.states.held, f),
                      code="held", subject=named)
    m.require(state, folders.PREPARE, f, named)


def prepare(ctx: Context, named: str, asked: str | None) -> Preparation:
    """Everything `job prepare` decides for the folder ``named`` (jobs.md § 3): refused whole, or
    what to write and what to show."""
    return planned(ctx, named, asked, {})


def planned(ctx: Context, named: str, asked: str | None, given: Mapping[Path, JobRequest]) -> Preparation:
    """A prepare planned in memory (jobs.md § 3): everything `job prepare` decides for the folder
    ``named`` — the same steps and refusals — on the requests ``given``, each by its folder's path,
    a folder not written yet among them, every other request read from disk; refused whole, or what
    to write and what to show, each prepared folder's `prepared.json` recording the SHA-256 of the
    request text its folder is written with (`folders.request_text`). It writes nothing."""
    folder = Path(named).resolve()
    held = {Path(k).resolve(): v for k, v in given.items()}
    folders.request(ctx, folder, named, held)                 # refused first where there is none
    t = target(ctx, folder, named, asked)
    kind = _kind(ctx, t)
    p = Plan(target=t, kind=kind, out=Preparation(target=t.name, launches=t.here and sends(kind)), given=held)
    if kind.commands:
        p.out.issues.append(Issue(severity="info", code="no-header", subject=named,
                                  message=f"the {t.record.scheduler.kind} kind declares no scheduler header yet: "
                                          f"{layout.read_once(ctx).name('submit')} is not written, and a launch "
                                          "cannot submit"))
    _tree(ctx, p, t, folder, named)
    return p.out


# ------------------------------------------------------------------ writing what was prepared

def files_of(ctx: Context, w: Writing) -> dict[str, bytes]:
    """The files a prepare writes into a folder not written yet, by their names, with their bytes:
    the record's copy, the programs, the run script and `prepared.json` — written with the folder,
    whole, by its one writer (`folders.write`; jobs.md § 3: "the folder and its prepared files are
    then written together")."""
    files = layout.read_once(ctx)
    out = {files.name("machine"): persist.read_bytes(w.copy)} if w.copy else {}
    out |= {name: persist.read_bytes(source) for name, source in w.sources.items()}
    if w.script is not None:
        out[files.name("script")] = w.script.encode("utf-8")
    out[files.name("prepared")] = persist.json_text(w.prepared.model_dump(mode="json")).encode("utf-8")
    return out


def commit(ctx: Context, w: Writing) -> None:
    """A prepare written into its folder, there already (jobs.md § 3, step 7): the record's copy on a
    first prepare, the programs and the modules they run with, the run script, then
    `prepared.json`, last — the commit (core.md § 4)."""
    files = layout.read_once(ctx)
    if w.copy:
        persist.copy_file(w.copy, w.folder / files.name("machine"))
    for name, source in w.sources.items():
        persist.copy_file(source, w.folder / name)
    if w.script is not None:
        persist.atomic_write_text(w.folder / files.name("script"), w.script)
    persist.write_json(w.folder / files.name("prepared"), w.prepared.model_dump(mode="json"))
