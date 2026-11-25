"""A part's state (projects.md § 8): observed, never stored, by the rules
`femkit/data/states/part.toml` declares over the facts gathered and named here — whether the
part's file loads, and the findings `project check` has on it, those of what cannot be checked
yet apart. A project's state is a count over its parts, never a machine of its own."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from femkit.core import states
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.projects.door import UNCHECKED, Opened, Part


@dataclass(frozen=True)
class PartFacts:
    """What is observed of one part."""

    loads: bool          # its file loads
    findings: int        # the findings on it, but what cannot be checked yet
    unchecked: int       # what it names that cannot be checked yet


BINDING = states.Binding("part", {
    "loads": lambda f: f.loads,
    "findings": lambda f: f.findings > 0,
    "unchecked": lambda f: f.unchecked > 0,
})


def facts(opened: Opened, part: Part, issues: Iterable[Issue]) -> PartFacts:
    """The part's facts, from the project as opened and the findings on its parts."""
    on = [i for i in issues if opened.owner(i.subject) is part]
    return PartFacts(loads=part.data is not None, findings=sum(i.code != UNCHECKED for i in on),
                     unchecked=sum(i.code == UNCHECKED for i in on))


def observe(ctx: Context, opened: Opened, issues: Iterable[Issue]) -> dict[str, str]:
    """Each part's state, by its address, from the findings ``issues`` holds on it."""
    machine = catalogue.machine(ctx, BINDING)
    issues = list(issues)
    return {address: machine.observe(facts(opened, part, issues)).value for address, part in opened.parts.items()}
