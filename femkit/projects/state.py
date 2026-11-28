"""A part's state (projects.md § 8): observed, never stored, by the rules
`femkit/data/states/part.toml` declares over the facts gathered and named here — whether the
part's file loads, the errors `project check` has on it, and what it names that cannot be checked
yet; a warning or a note changes no state — and its next steps, the rows its state's table gives
it: a study whose cases `study prep` can make, its prep, asking the engine of those that can solve
it, which a layer above the door says, since only it reads a study's cases — none of them while an error stands anywhere in the project, the
first error being the project's next step: the one filter every reader of the parts' steps reads
through (`observe`). The errors on a part are one predicate, `errors`: its state reads it, and so
does what refuses the prep of a study that uses the part (models.md § 5.3) — the findings on it, by
their subject (`on`). A project's state is a count over its parts, never a machine of its own."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, NamedTuple, Sequence

from femkit.core import states, view
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.view import Shows
from femkit.definitions import catalogue
from femkit.projects.door import UNCHECKED, Opened, Part


@dataclass(frozen=True)
class PartFacts:
    """What is observed of one part."""

    loads: bool          # its file loads
    errors: int          # the errors on it
    unchecked: int       # what it names that cannot be checked yet
    project: str         # its project, by its name: what its steps name
    prepares: str | None = None   # for a study whose cases `study prep` can make, its name; none for any other
    engines: tuple[str, ...] | None = None   # for such a study, the engines that can solve it: what its prep's
                                             # engine may be; none where that cannot be told, or for any other


BINDING = states.Binding("part", {
    "loads": lambda f: f.loads,
    "errors": lambda f: f.errors > 0,
    "unchecked": lambda f: f.unchecked > 0,
}, values={"project": lambda f: f.project, "study": lambda f: f.prepares},
   choices={"engine": lambda f: f.engines}, drawn=True)


def on(opened: Opened, part: Part, issues: Iterable[Issue]) -> list[Issue]:
    """The findings among ``issues`` on ``part``, by their subject — a file of it, `<kind>:<name>@<file>`,
    among them (`Opened.owner`; projects.md § 8)."""
    return [i for i in issues if opened.owner(i.subject) is part]


def errors(opened: Opened, part: Part, issues: Iterable[Issue]) -> list[Issue]:
    """The errors among ``issues`` on ``part`` (`on`): what stops what it would stop — its state
    `errors`, and the prep of a study that uses it (projects.md § 8; models.md § 5.3). A warning or
    a note stops nothing."""
    return [i for i in on(opened, part, issues) if i.severity == "error"]


def facts(opened: Opened, part: Part, issues: Iterable[Issue],
          prepares: Mapping[str, Sequence[str] | None] | None = None) -> PartFacts:
    """The part's facts, from the project as opened, the findings on its parts, and the studies
    whose cases `study prep` can make, by their addresses, each with the engines that can solve it —
    none where that cannot be told."""
    mine = on(opened, part, issues)
    prepares = prepares or {}
    held = prepares.get(str(part.address))
    return PartFacts(loads=part.data is not None, errors=sum(i.severity == "error" for i in mine),
                     unchecked=sum(i.code == UNCHECKED for i in mine),
                     project=opened.project.name,
                     prepares=part.address.name if str(part.address) in prepares else None,
                     engines=tuple(held) if held is not None else None)


class Seen(NamedTuple):
    """A part's state, by its name, its block's word, and its next steps (projects.md § 8; web.md
    § 7.6)."""

    state: str
    shows: Shows
    next: tuple[view.Action, ...] = ()


def erred(issues: Iterable[Issue]) -> bool:
    """Whether an error stands among ``issues``, the project's findings: then the first error is
    the project's next step, and no part's next step is offered beside it — a warning or a note is
    never the next step (projects.md § 8; models.md § 11.2)."""
    return any(i.severity == "error" for i in issues)


def observe(ctx: Context, opened: Opened, issues: Iterable[Issue],
            prepares: Mapping[str, Sequence[str] | None] | None = None) -> dict[str, Seen]:
    """Each part's state, its word and its next steps, by its address, from the project's findings
    ``issues`` and the studies whose cases `study prep` can make, ``prepares``, by their addresses,
    each with the engines that can solve it, which its prep asks of — every part's next steps none while an error stands among ``issues`` (`erred`): the one filter of
    every reader of the parts' steps, `project check`, `project graph`, `study list` and `case list`
    (projects.md § 8)."""
    machine = catalogue.machine(ctx, BINDING)
    issues, prepares = list(issues), dict(prepares or {})
    offered = not erred(issues)
    out = {}
    for address, part in opened.parts.items():
        f = facts(opened, part, issues, prepares)
        state = machine.observe(f)
        out[address] = Seen(state.value, machine.word(state), machine.next(state, f) if offered else ())
    return out


def steps(seen: dict[str, Seen], order: Iterable[str]) -> list[view.Action]:
    """Every part's next steps, the parts in ``order``, each step once (projects.md § 8)."""
    return list({a.command: a for address in order if address in seen for a in seen[address].next}.values())
