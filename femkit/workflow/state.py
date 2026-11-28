"""A stage's state (workflow.md § 6): observed, never stored, by the rules
`femkit/data/states/stage.toml` declares over the facts gathered and named here — a stage's own
states first: whether a stage it takes from has no finished newest run while its folder does not
read `in_launch`, whether its folder is there for the machine its identity is formed with; past
them, its calculation folder's state, as the jobs domain's machine observes it (jobs.md § 5.5),
with that machine's actions and words — `stage.toml` is past `calculation` (core.md § 7), and the
facts handed it are the folder's. A stage whose folder is there reads its folder's state, whatever
case first needed it; one whose folder reads `in_launch` — prepared with a job not launched yet,
whatever runs it made before — is in that state, whatever it takes from: that job makes it. The
stage reads that state as its folder's machine observes it, never computing it again.

What `study prep` does to a stage is the stage table's own `[tasks]`, each with its sentence
(`said`), each the code does by name checked when the table loads: `WRITE` its folder, `PREPARE`
it, `RESTATE` its request's resources, `PLACE` it in its study's job (`tasks`). They are the
tasks the table's `[does]` gives the stage's state — its own, or its folder's past them — each where
its guard holds over the stage's facts: whether its folder is there, whether it is to be prepared,
and, as prep observes them, whether its request states other resources than its job's
(`restated`) and whether it waits on a stage the same prep places in no job (`held_back`). Where
the table gives the state none, prep refuses, keyed on that state, with its next steps; the code
decides nothing the table does not say. A stage's values — its project, study and target — are
read from its facts, and the engine its prep asks for is one of those that can solve its study,
where they are told (`engines`, workflow.md § 7); a waiting stage's next steps are the stage it waits on's, which the table
declares (`[next_from.waiting]`) and the binding hands as `source`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Collection, Iterable, Sequence

from femkit.core import states, text
from femkit.core.errors import Refused
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.jobs import folders, runs

#: What `study prep` does to a stage that the code does by name, as the stage table's `[tasks]`
#: names them (workflow.md § 6): write its folder, prepare it, state its request's resources again,
#: place it in its study's job — each checked when the table loads.
WRITE, PREPARE, RESTATE, PLACE = "write", "prepare", "restate", "place"
#: The code of a stage that cannot be read: its `stage.json`, or its newest run's launch record
#: (workflow.md §§ 4, 7).
UNREADABLE = "unreadable"
#: The code of prep's refusal of a stage in a state the stage table gives no task for (core.md § 7).
NOT_ALLOWED = "not-allowed"
#: The subject a waiting stage's next steps are read from, as the stage table names it
#: (`[next_from.waiting]`): the stage it waits on.
SOURCE = "source"


@dataclass(frozen=True)
class StageFacts:
    """What is observed of one stage: its study's project, its study and the target its identity
    is formed with — what its next steps take — and the engines that can solve its study, which its
    prep may name, where they are told; its folder and whether it is there; each stage it
    takes from that has no finished newest run; where its folder is there, the folder's facts,
    which the machine it is past observes; whether it is to be prepared; and, as `study prep`
    observes them, whether its request states other resources than its job's and whether it waits
    on a stage that prep places in no job."""

    project: str
    study: str
    target: str | None
    folder: Path
    there: bool
    waits_on: tuple["Seen", ...] = ()
    calculation: folders.FolderFacts | None = None
    observed: Enum | None = None          # its folder's state, as the machine it is past observes it
    in_launch: bool = False               # that state is `in_launch` (jobs.md § 5.5)
    unready: bool = True                  # no folder, or one whose state allows prepare and not launch
    restated: bool = False                # prep's: its request states other resources than its job's
    held_back: bool = False               # prep's: it waits on a stage prep places in no job
    engines: tuple[str, ...] | None = None    # the engines that can solve its study; none: not told here


@dataclass(frozen=True)
class Seen:
    """One stage observed: its address, its facts and its state — its own, or its folder's."""

    address: str
    facts: StageFacts
    state: Enum


BINDING = states.Binding("stage", {
    "waits": lambda f: bool(f.waits_on),
    "in_launch": lambda f: f.in_launch,
    "folder": lambda f: f.there,
    "unready": lambda f: f.unready,
    "restated": lambda f: f.restated,
    "held_back": lambda f: f.held_back,
}, values={"project": lambda f: f.project, "study": lambda f: f.study, "target": lambda f: f.target},
   choices={"engine": lambda f: f.engines}, reads=frozenset({"in_launch", "unreadable"}), tasks=frozenset({WRITE, PREPARE, RESTATE, PLACE}), drawn=True,
   hands=lambda f: f.calculation, subjects={SOURCE: lambda f: f.waits_on[0].facts if f.waits_on else None})


def machine(ctx: Context) -> states.Machine:
    """The machine `femkit/data/states/stage.toml` declares, bound to these facts (workflow.md § 6)."""
    return catalogue.machine(ctx, BINDING)


def finished(ctx: Context, seen: Seen) -> bool:
    """Whether a stage's newest run finished: what a stage taking from it waits on (§ 6)."""
    newest = seen.facts.calculation.newest if seen.facts.calculation is not None else None
    return newest is not None and newest.state is runs.machine(ctx).states.finished


def observe(ctx: Context, address: str, folder: Path, *, project: str, study: str, target: str | None,
            takes_from: Iterable[Seen] = (), engines: Sequence[str] | None = None) -> Seen:
    """A stage's facts and its state, by the machine's rules — its folder's read through the run
    door, which writes a job's word it finds (jobs.md § 5.1), and observed by the folder's machine
    — given what is observed of each stage it takes from, ``takes_from``, and the engines that can
    solve its study, ``engines``, where its next steps are offered."""
    m, there = machine(ctx), folder.is_dir()
    calculation = folders.facts(ctx, folder) if there else None
    held = m.past.observe(calculation) if calculation is not None else None
    allows = m.past.allowed(held) if held is not None else {}
    f = StageFacts(project=project, study=study, target=target, folder=folder, there=there,
                   waits_on=tuple(s for s in takes_from if not finished(ctx, s)), calculation=calculation,
                   observed=held, in_launch=held is m.past.states.in_launch,
                   unready=held is None or (folders.PREPARE in allows and folders.LAUNCH not in allows),
                   engines=tuple(engines) if engines is not None else None)
    return Seen(address=address, facts=f, state=m.observe(f))


def next_steps(ctx: Context, seen: Seen) -> tuple:
    """A stage's next steps (§ 6): what its state allows — a waiting stage's, the stage it waits
    on's, as the table declares it."""
    return machine(ctx).next(seen.state, seen.facts)


def tasks(ctx: Context, seen: Seen, placed: Collection[str], restated: bool) -> list[str]:
    """What `study prep` does to a stage (§ 6): the tasks the stage table's `[does]` gives its state,
    each where its guard holds over its facts as prep observes them — ``restated``, its request
    states other resources than its job's; held back where it waits on a stage this prep does not
    place, ``placed``, so a later prep places it. Refused, keyed on its state, where the table gives
    that state none — with what that state allows: `unreadable`, naming the record that does not
    read, for the state of that name; `not-allowed`, naming the folder, for any other (workflow.md
    § 7)."""
    m = machine(ctx)
    if m.idle(seen.state):
        state, steps = seen.state, m.next(seen.state, seen.facts)
        if state is m.past.states.unreadable:
            where = folders.unreadable(ctx, seen.facts.calculation)
            raise Refused(f"{seen.address} is {state.value}: {text.path(where)} does not read", steps,
                          code=UNREADABLE, subject=str(where))
        raise Refused(f"{seen.address} is {state.value}: `study prep` does nothing to a stage in it", steps,
                      code=NOT_ALLOWED, subject=str(seen.facts.folder))
    f = replace(seen.facts, restated=restated,
                held_back=any(w.address not in placed for w in seen.facts.waits_on))
    return list(m.does(seen.state, f))


def said(ctx: Context, task: str) -> str:
    """What `study prep` does to a stage, ``task``, in the stage table's own sentence (§ 6)."""
    return machine(ctx).tasks[task]
