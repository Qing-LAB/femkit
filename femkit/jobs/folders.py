"""Calculation folders and launch folders (jobs.md §§ 1, 3, 5.5): the one writer of one, what
`job prepare` leaves in it, a launch folder's records, and a folder's state by the rules
`femkit/data/states/calculation.toml` declares.

femkit writes a folder through `write` alone — the request, its inputs and the maker's files —
a launch folder's `maker.json` from the action its maker names — before its first prepare, and,
where a maker planned the folder's prepare in memory, the files that prepare writes, with them,
whole (jobs.md § 3); its maker writes its request again, its resources alone, through `restate`;
nothing else writes into it but `job prepare`, `job launch`, a run's script and a run's records
(jobs.md § 1.1). A request's text is `request_text`'s, whoever writes it, so a prepare planned in
memory records the SHA-256 of the very text written. A maker reads its own file of a folder
through `maker_file` and `read_made` — the jobs domain alone forms a path inside a calculation
folder (framework.md § 1, rule 2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator, Mapping

from pydantic import Field

from femkit.core import persist, states, view
from femkit.core.errors import Refused, UsageError
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, Model, validate
from femkit.definitions import catalogue
from femkit.jobs import addresses, layout, record, runs
from femkit.jobs.request import JobRequest, Resources, context
from femkit.jobs.runs import Job


# ------------------------------------------------------------------ what a folder holds

class Prepared(Model):
    """`prepared.json`, written last by `job prepare` (jobs.md § 3, step 7)."""

    target: str = Field(description="the machine record it was prepared for, by name")
    request: str = Field(description="the SHA-256 of job.toml as prepared: a launch refuses one changed since")
    environment: str | None = Field(default=None, description="the environment its run enters; none for a launch "
                                                              "folder")
    install_fingerprint: str | None = Field(default=None, description="that environment's install fingerprint, as "
                                                                      "the record lists it")
    resources: Resources = Field(description="the resources resolved")
    files: dict[str, str] = Field(description="each script, program and module it wrote, and machine.toml, with its "
                                              "SHA-256: a launch refuses any changed since")
    launch: str | None = Field(default=None, description="for a member of a batch or a part of a sequence, the "
                                                         "launch folder it is prepared with, by its path from here")


class Maker(Model):
    """`maker.json`, a launch folder's maker's file: the action that writes it again, which `job
    status` and a launch refused once it was launched offer, knowing nothing of what wrote it
    (jobs.md § 1.2)."""

    action: view.Action = Field(description="the action that writes the launch folder again")


class Listed(Model):
    """A launch record's member or part: its folder, and the runs launched of it."""

    folder: str = Field(description="the member or part, by its path from the launch folder")
    runs: list[str] = Field(default_factory=list, description="each run launched of it, by its path from the launch "
                                                              "folder; a sequence's part has none until it is reached")


class LaunchRecord(Model):
    """`launch.json`, a launch folder's launch record, written by `job launch` (jobs.md § 5.1): when
    it went, the job, its members or parts in order, and each one's runs once launched."""

    time: str = Field(description="when it went")
    identity: str = Field(description="the identity of the machine it was launched from")
    job: Job = Field(description="the job: the walk's process")
    listed: list[Listed] = Field(description="its members or parts, in order")


def request_text(ctx: Context, request: JobRequest) -> str:
    """The text of ``request`` as its folder holds it, `job.toml`: checked by the request's schema,
    its names held to the catalogue's (jobs.md § 2) — the one text, whoever writes it, so a prepare
    planned in memory records its SHA-256 before it is written (jobs.md § 3)."""
    named = layout.read_once(ctx)
    req = validate(JobRequest, request.model_dump(mode="json", exclude_defaults=True), named.name("request"),
                   context(named.reserved()))
    return persist.toml_text(req.model_dump(mode="json", exclude_defaults=True))


def write(ctx: Context, folder: Path, request: JobRequest, files: Mapping[str, bytes],
          prepared: Mapping[str, bytes] | None = None, maker: view.Action | None = None) -> Path:
    """The one writer of a calculation or launch folder (jobs.md § 1.1): a new folder at ``folder``,
    written whole — its request, its inputs and its maker's files, each by its path from the folder
    with its bytes; given ``maker``, the action that writes it again, as its `maker.json`, which the
    catalogue names — and, given ``prepared``, the files its prepare planned in memory writes, by
    their names, with them (jobs.md § 3: "the folder and its prepared files are then written
    together"). An input the request lists that ``files`` does not hold, or a file of ``files``
    taking a name a folder or a run holds of femkit's own, is a defect of the maker; so is a folder
    there already. A maker's file named by its maker — a stage's `stage.json`, as the workflow
    declares it — is written as any other."""
    named = layout.read_once(ctx)
    text = request_text(ctx, request)
    held = {Path(p).parts[0] for p in files}
    missing = [i for i in request.inputs if i not in files and Path(i).parts[0] not in held]
    if missing:
        raise ValueError(f"{folder}: the request lists {', '.join(missing)}, which no file given is")
    taken = sorted(p for p in files if Path(p).parts[0] in named.reserved())
    if taken:
        raise ValueError(f"{folder}: {', '.join(taken)} take a name of femkit's own")
    again = {named.name("maker_action"): persist.json_text(Maker(action=maker).model_dump(mode="json")).encode(
        "utf-8")} if maker is not None else {}
    return persist.write_folder(folder, {named.name("request"): text.encode("utf-8"), **files, **again,
                                         **(prepared or {})})


def restated(ctx: Context, folder: Path, resources: Resources) -> JobRequest:
    """The request of the existing folder ``folder`` stated again, its resources alone ``resources``,
    as `restate` writes it (jobs.md § 1.1) — what a maker plans a prepare in memory with."""
    named = layout.read_once(ctx)
    held = runs.request_of(ctx, folder).model_dump(mode="json", exclude_defaults=True)
    return validate(JobRequest, {**held, "resources": resources.model_dump(mode="json", exclude_defaults=True)},
                    named.name("request"), context(named.reserved()))


def restated_job(ctx: Context, launch: Path, job: Resources, member: Resources) -> dict[Path, JobRequest]:
    """A job not launched yet, stated again whole (jobs.md §§ 1.1, 1.2): where a launch folder of
    ``launch``'s tree states other resources than ``job`` — each launch folder's request stated
    again with ``job``, and each member's or part's that runs a command, a calculation folder, with
    ``member``, what runs inside the job — each one that states other resources than its own, by its
    folder, as `restate` writes it; none where every launch folder of the tree states ``job``."""
    held = {f: runs.request_of(ctx, f) for f in tree(ctx, launch)}
    if all(r.resources == job for r in held.values() if r.walk):
        return {}
    return {f: restated(ctx, f, job if r.walk else member) for f, r in held.items()
            if r.resources != (job if r.walk else member)}


def restate(ctx: Context, folder: Path, resources: Resources) -> Path:
    """The maker writes the request of the existing folder ``folder`` again, its resources alone
    ``resources`` (jobs.md § 1.1): how a folder runs may change, never what it runs, so it then
    reads `stale`, and is prepared again (§ 3). Refused, `not-allowed`, with what its state allows,
    while a job holds the folder or a run of it goes — in a state that allows no prepare, which a
    request stated again needs (§ 5.5)."""
    m = machine(ctx)
    f, state = observe(ctx, folder)
    if PREPARE not in m.allowed(state):
        raise Refused(f"{folder} is {state.value}: its request is stated again only while no job holds it and no run "
                      "of it goes", m.next(state, f), code="not-allowed", subject=str(folder))
    named = layout.read_once(ctx)
    return persist.atomic_write_text(folder / named.name("request"),
                                     request_text(ctx, restated(ctx, folder, resources)))


def prepared(ctx: Context, folder: Path) -> persist.Read:
    return persist.read_record(folder / layout.read_once(ctx).name("prepared"), Prepared)


def maker_file(folder: Path, name: str) -> Path:
    """Where the file ``name`` its maker keeps beside the request lies in ``folder`` — a stage's
    `stage.json`, as the workflow declares it (jobs.md § 1.1)."""
    return folder / name


def read_made(folder: Path, name: str, model: type[Model]) -> persist.Read:
    """The maker's file ``name`` of ``folder``, read by ``model``: there or not, and why it does not
    read (jobs.md § 1.1)."""
    return persist.read_record(maker_file(folder, name), model)


def launch_record(ctx: Context, folder: Path) -> persist.Read:
    return persist.read_record(folder / layout.read_once(ctx).name("launch_record"), LaunchRecord)


@dataclass(frozen=True)
class Again:
    """What writes a launch folder again, as its `maker.json` names it (jobs.md § 1.2): the action
    offered — none where it names none or does not read — and, where it names an operation femkit
    does not have, that operation, `unknown`: never offered, and no other in its place."""

    action: view.Action | None
    unknown: str | None = None


def maker(ctx: Context, folder: Path) -> Again:
    """What writes a launch folder again, as its `maker.json` names it (`Again`): the action, none
    where it names none or it does not read; one naming an operation femkit does not have never
    offered, but named as `unknown`."""
    held = persist.read_record(folder / layout.read_once(ctx).name("maker_action"), Maker)
    if not held.reads:
        return Again(None)
    action = held.value.action
    if action.call is not None and action.call.operation not in {v.name for v in view.verbs()}:
        return Again(None, unknown=action.call.operation)
    return Again(action)


def at(folder: Path, relative: str) -> Path:
    """Another folder, by its path from ``folder``, as a request names it."""
    return Path(os.path.normpath(Path(folder) / relative))


def from_here(folder: Path, other: Path) -> str:
    """``other``'s path from ``folder``, as a record or a request writes it."""
    return os.path.relpath(other, folder)


def differs(ctx: Context, folder: Path, p: Prepared) -> str | None:
    """The first file `prepared.json` records whose SHA-256 is not what it recorded — its request
    first — by its name; None when none differs (jobs.md § 3, step 7)."""
    recorded = {layout.read_once(ctx).name("request"): p.request, **p.files}
    return next((name for name, sha in recorded.items() if persist.sha256(folder / name) != sha), None)


# ------------------------------------------------------------------ a folder's state (jobs.md § 5.5)

#: The action of a state that allows the folder prepared: where a request may be stated again too.
PREPARE = "prepare"
#: The action of a state that allows the folder launched (jobs.md § 5).
LAUNCH = "launch"


@dataclass
class FolderFacts:
    """What is observed of one calculation or launch folder."""

    folder: Path
    prepared: persist.Read                          # prepared.json
    differs: str | None                     # the first file it records that differs
    holding: addresses.Holding | None       # a job still going that holds it
    launched: bool                          # a launch folder's launch.json is there
    apart: Path | None                      # a member or part it names — or one of theirs — prepared apart
    launch: Path | None                     # the launch folder that holds it, not launched yet
    newest: runs.Seen | None                # its newest run, observed

    def newest_is(self, state: str) -> bool:
        return self.newest is not None and self.newest.state.value == state


BINDING = states.Binding("calculation", {
    "prepared": lambda f: f.prepared.reads,
    "stale": lambda f: f.differs is not None,
    "held": lambda f: f.holding is not None,
    "launched": lambda f: f.launched,
    "regrouped": lambda f: f.apart is not None,
    "in_launch": lambda f: f.launch is not None,
    "no_run": lambda f: f.newest is None,
    **{f"newest_{s}": (lambda s: lambda f: f.newest_is(s))(s)
       for s in ("pending", "queued", "running", "finished", "failed", "unreadable")},
}, values={"dir": lambda f: str(f.folder),                                  # by its full path (jobs.md § 1)
           "job": lambda f: f.holding.address.id if f.holding else None,    # what `job cancel` names
           "launch": lambda f: str(f.launch) if f.launch else None},        # the launch folder that holds it
   reads=frozenset({"unprepared", "stale", "held", "launched", "regrouped", "in_launch", "prepared", "pending",
                    "queued", "running", "finished", "failed", "unreadable"}),
   acts=frozenset({PREPARE, LAUNCH}), drawn=True)     # what `job prepare`, `restate` and `job launch` ask


def machine(ctx: Context) -> states.Machine:
    """The machine `femkit/data/states/calculation.toml` declares, bound to these facts (jobs.md § 5.5)."""
    return catalogue.machine(ctx, BINDING)


def request(ctx: Context, folder: Path, named: str, given: Mapping[Path, JobRequest] = {}) -> JobRequest:
    """The folder's request: the one given in memory, by the folder's full path, else its `job.toml`
    (jobs.md § 3, step 1); refused, `no-request`, for a folder that holds none, and as its file is
    where it does not load."""
    if folder in given:
        return given[folder]
    name = layout.read_once(ctx).name("request")
    if not (folder / name).is_file():
        raise UsageError(f"{named} holds no {name}: it is no calculation folder", code="no-request", subject=named)
    return runs.request_of(ctx, folder)


def listed(ctx: Context, folder: Path) -> list[Path]:
    """Each member or part a launch folder's request names, by its full path; none for a calculation
    folder, or one whose request does not read."""
    try:
        return [at(folder, name) for name in runs.request_of(ctx, folder).listed]
    except DefinitionError:
        return []


@dataclass(frozen=True)
class Visit:
    """One folder of a launch folder's tree (`walk`): its full path; the launch folder that names it,
    and the name that one's request lists it by — none for the first; how deep it lies, the first
    at 0; and its request — the one given in memory, else its `job.toml` — none where it has none that
    reads, whose reader says why (`request`)."""

    folder: Path
    above: Path | None
    listed: str | None
    depth: int
    request: JobRequest | None


def walk(ctx: Context, folder: Path, given: Mapping[Path, JobRequest] = {}) -> Iterator[Visit]:
    """A launch folder's tree (jobs.md § 1.2), the one walk of it, its requests given in memory, by
    their folders' full paths, or read from disk: the folder first, then each member or part it
    names and each of theirs, down every level, in order. A calculation folder, or one whose request
    does not read, is a tree of itself alone."""
    def read(here: Path) -> JobRequest | None:
        try:
            return request(ctx, here, str(here), given)
        except (UsageError, DefinitionError):
            return None

    def below(here: Path, held: JobRequest | None, depth: int) -> Iterator[Visit]:
        for name in held.listed if held is not None else ():
            member = at(here, name)
            mine = read(member)
            yield Visit(member, here, name, depth, mine)
            yield from below(member, mine, depth + 1)

    top = at(folder, ".")
    held = read(top)
    yield Visit(top, None, None, 0, held)
    yield from below(top, held, 1)


def tree(ctx: Context, folder: Path) -> list[Path]:
    """Every folder of ``folder``'s tree (`walk`), the folder first."""
    return [v.folder for v in walk(ctx, folder)]


def apart(ctx: Context, folder: Path) -> Path | None:
    """The first member or part the launch folder ``folder`` names — or one of theirs, down its
    parts (`walk`) — that is not prepared with the launch folder naming it: prepared apart since,
    taken out, or not there (jobs.md § 5.5, `regrouped`); None for a launch folder whole — every
    member and part it names, and each of theirs, still prepared with it — or a calculation
    folder."""
    for v in walk(ctx, folder):
        p = prepared(ctx, v.folder) if v.above is not None else None
        if p is not None and not (p.reads and p.value.launch and at(v.folder, p.value.launch) == v.above):
            return v.folder
    return None


def holder(ctx: Context, folder: Path, p: persist.Read) -> Path | None:
    """The launch folder that holds ``folder`` while it is not launched (jobs.md §§ 1.2, 5.5): the one
    its prepared.json ``p`` names — or, for a part of a sequence, the sequence that one is prepared
    with — by its full path; None for a folder prepared apart, once that launch folder went, or
    where any launch folder of that chain is not there, does not name the folder below it, or is not
    whole — a prep cut short before it wrote it, the sequence missing while its batch is there, a
    member taken out since — so the folder is in no job, and placed again."""
    record_name = layout.read_once(ctx).name("launch_record")
    below = at(folder, ".")
    held = at(below, p.value.launch) if p.reads and p.value.launch else None
    while held is not None:
        if not held.is_dir() or (held / record_name).exists() or below not in listed(ctx, held) \
                or apart(ctx, held) is not None:
            return None
        above = prepared(ctx, held)
        if not (above.reads and above.value.launch):
            return held
        below, held = held, at(held, above.value.launch)
    return None


def facts(ctx: Context, folder: Path) -> FolderFacts:
    p = prepared(ctx, folder)
    return FolderFacts(folder=folder, prepared=p, differs=differs(ctx, folder, p.value) if p.reads else None,
                       holding=addresses.holding(ctx, folder, record.host_identity()),
                       launched=(folder / layout.read_once(ctx).name("launch_record")).exists(),
                       apart=apart(ctx, folder) if p.reads else None,
                       launch=holder(ctx, folder, p), newest=runs.newest(ctx, folder))


def observe(ctx: Context, folder: Path) -> tuple[FolderFacts, Enum]:
    """A folder's facts and its state, by the machine's rules."""
    f = facts(ctx, folder)
    return f, machine(ctx).observe(f)


def next_steps(ctx: Context, state: Enum, f: FolderFacts) -> tuple[view.Action, ...]:
    """What a folder's state allows (jobs.md § 5.5): its table's next steps — and, where a row of the
    state says its operation is its subject's (`subject`, core.md § 7), a launch folder launched or
    whose members changed, beside them the action its `maker.json` names, which writes it again,
    offered without knowing what wrote it (§ 1.2)."""
    allowed = machine(ctx).allowed(state).values()
    steps = [a.next(f) for a in allowed]
    again = maker(ctx, f.folder).action if any(a.subject for a in allowed) else None
    return tuple({s.command: s for s in [*steps, again] if s is not None}.values())


def launch_step(ctx: Context, state: Enum, f: FolderFacts) -> view.Action | None:
    """The launch a folder's state allows, as its table gives it (jobs.md § 5.5): the one step a
    maker offers for a job it holds the stages of, ready (workflow.md § 7); none where its state
    allows no launch."""
    action = machine(ctx).allowed(state).get(LAUNCH)
    return action.next(f) if action is not None else None


def unreadable(ctx: Context, f: FolderFacts) -> Path | None:
    """The record a folder's state reads `unreadable` by (jobs.md § 5.5): its newest run's launch
    record; none for a folder with no run."""
    return f.newest.run / layout.read_once(ctx).name("launched") if f.newest is not None else None
