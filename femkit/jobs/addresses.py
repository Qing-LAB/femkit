"""The jobs launched from this machine (jobs.md § 5.4): every launch leaves an address, one file per
job in `<state>/jobs/` (config.md § 2), the way a server leaves its pidfile. It holds an address,
never a state: what the job is doing is read fresh each time — whether its process still runs —
and its runs' states through the run door.

A part's launch inside a sequence writes no address of its own: it adds the runs it started to
the sequence's. A job still going holds the folders it will run — a run it opened that has not
started, a part it has not reached, that part's members — and nothing but its own sequence
prepares or launches them (jobs.md §§ 1.2, 3, 5).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from femkit.core import dirs, persist
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, Model
from femkit.jobs import layout, runs
from femkit.jobs.runs import Job

HOW = Literal["background", "waited on"]


class Address(Model):
    """`<state>/jobs/<id>.json`: one job launched from this machine (jobs.md § 5.4)."""

    id: str = Field(description="what `job list` shows and `job cancel` names: `<host>-<pid>` for a job here")
    how: HOW = Field(description="how it went: here in the background, or here waited on")
    host: str = Field(description="the host it was launched on: a process ID means something only there")
    job: Job = Field(description="its process: host, process ID, start time and boot ID")
    folder: str = Field(description="the calculation or launch folder it was launched for")
    runs: list[str] = Field(default_factory=list, description="each run it started, by its path; a sequence's "
                                                              "parts add theirs as they go")
    sequence: list[str] | None = Field(default=None, description="for a sequence, each part in order, by its path")
    time: str = Field(description="when it went")


def folder() -> Path:
    """`<state>/jobs/`: every address of a job launched from this machine."""
    return dirs.state_dir() / "jobs"


def path(job_id: str) -> Path:
    return folder() / f"{job_id}.json"


def write(address: Address) -> Path:
    return runs.write(path(address.id), address)


def remove(job_id: str) -> None:
    """An ended job's address removed: the one other write a read makes (api.md § 2)."""
    persist.remove(path(job_id))


def listing() -> list[tuple[Path, persist.Read]]:
    """Every address there, oldest first by its file's name, each read or not."""
    if not folder().is_dir():
        return []
    return [(p, persist.read_record(p, Address)) for p in sorted(folder().glob("*.json"))]


def find(job_id: str) -> persist.Read:
    return persist.read_record(path(job_id), Address)


def going(a: Address, here: str) -> bool | None:
    """Whether the job still goes: its process, the same host, ID and start (jobs.md § 5.4);
    None for a job launched on another host, which cannot be asked from here."""
    if a.host != here:
        return None
    return a.job.identity().alive()


def add_runs(job_id: str, started: list[Path]) -> bool:
    """A part's launch inside a sequence adds the runs it started to the sequence's address; False
    when there is no address to add them to."""
    held = find(job_id)
    if not held.reads:
        return False
    a: Address = held.value
    write(a.model_copy(update={"runs": [*a.runs, *(str(r) for r in started if str(r) not in a.runs)]}))
    return True


@dataclass(frozen=True)
class Holding:
    """A job still going that holds a folder, and why."""

    address: Address
    why: str


def holding(ctx: Context, folder_: Path, here: str) -> Holding | None:
    """The job still going that holds ``folder_`` — a run of it opened and not started, a part it
    has not reached, or a member of such a part (jobs.md § 5.5, rule 3); None when none does. A job
    this machine cannot ask about holds nothing."""
    target = Path(folder_).resolve()
    for _, held in listing():
        if not held.reads or not going(held.value, here):
            continue
        a: Address = held.value
        for run in map(Path, a.runs):
            if run.parent.resolve() == target and not (run / layout.read_once(ctx).name("started")).exists():
                return Holding(a, f"goes in job {a.id}")
        for part in map(Path, a.sequence or []):
            if _reached(ctx, part, a):
                continue
            if part.resolve() == target or target in _members(ctx, part):
                return Holding(a, f"goes in job {a.id}, when its sequence reaches it")
    return None


def running(ctx: Context, folder_: Path, here: str) -> Address | None:
    """The job still going that runs ``folder_`` — a run of it on the job's address — or holds it
    to run (`holding`); None when none does: what a change's impact says of a stage it replaces
    (workflow.md § 10). A job this machine cannot ask about runs nothing."""
    target = Path(folder_).resolve()
    for _, held in listing():
        if held.reads and going(held.value, here) and any(Path(r).parent.resolve() == target for r in held.value.runs):
            return held.value
    found = holding(ctx, folder_, here)
    return found.address if found is not None else None


def _reached(ctx: Context, part: Path, a: Address) -> bool:
    """Whether a sequence has launched ``part``: a run of it, or of its members, is on the address."""
    inside = {part.resolve(), *_members(ctx, part)}
    return any(Path(r).parent.resolve() in inside for r in a.runs) or \
        (part / layout.read_once(ctx).name("launch_record")).exists()


def _members(ctx: Context, part: Path) -> set[Path]:
    """A batch part's members, resolved; none for a calculation folder or one whose request does
    not read."""
    try:
        req = runs.request_of(ctx, part)
    except DefinitionError:
        return set()
    return {Path(os.path.normpath(part / m)).resolve() for m in req.members or []}
