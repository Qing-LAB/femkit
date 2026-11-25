"""The check frame (projects.md § 6; models.md §§ 3, 11.1): what `project check` hands each part
kind's check, and the run over a project's parts in the chain's order.

It sits with the door, below every package that owns a part kind — `materials`, `geometry`,
`models` — so each imports it and types its checks by it (framework.md § 1). Each part kind's
check is declared by the module that owns it, beside its schema, as `PART_CHECKS = {"<schema
key>": check}`, `check(checking, part) -> Iterable[Issue]`; the registry registers each here when
femkit starts (api.md § 6), so this module imports no package of a part. A key may have checks
from several modules — a component's assignment is the materials package's (projects.md § 2) —
run in the registry's order.

A check finds; it never refuses: what it finds is a finding at the part's file and key, made by
`Checking.issue`; a value written as a quantity is read by `Checking.measure`; what it cannot
check yet is said so by `Checking.unchecked`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any, Callable, Iterable, Mapping

from femkit.core import persist
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.units import Dimension, Quantity, UnitError, Units, name_spans
from femkit.core.view import Action
from femkit.definitions import catalogue
from femkit.definitions.formulations import FormulationDefinition
from femkit.definitions.places import PlaceKind
from femkit.definitions.properties import Property
from femkit.projects import door
from femkit.projects.addresses import Address
from femkit.projects.door import Opened, Part

PARAMETER = "parameter"   # the object type the project file holds its parameters as (projects.md § 4)

Check = Callable[["Checking", Part], Iterable[Issue]]
_CHECKS: dict[str, tuple[Check, ...]] = {}


def register(key: str, check: Check) -> None:
    """``check`` checks each part loaded with the schema the layout calls ``key``; registering it
    again changes nothing."""
    held = _CHECKS.get(key, ())
    if check not in held:
        _CHECKS[key] = (*held, check)


def unregister(key: str) -> None:
    _CHECKS.pop(key, None)


def registered() -> dict[str, tuple[Check, ...]]:
    return dict(_CHECKS)


@dataclass(frozen=True)
class Checking:
    """What each part kind's check is handed: the project as opened, the definitions its rules
    read, and the project's parameters resolved once (projects.md § 6; models.md § 3)."""

    opened: Opened
    units: Units
    formulations: Mapping[str, FormulationDefinition]
    properties: Mapping[str, Property]
    places: Mapping[str, PlaceKind]
    environments: frozenset[str]          # the engine environments a study may bind (models.md § 5.1)
    parameters: Mapping[str, Quantity]   # each parameter that resolves, by name, exactly
    unresolved: frozenset[str]           # each that does not: its own finding, or one it uses, says why
    issues: tuple[Issue, ...]            # what resolving them found, each on the project file's parameter
    known: bool = True                   # whether the parameters are known: the project file loads

    @classmethod
    def of(cls, opened: Opened, ctx: Context) -> "Checking":
        units = catalogue.units(ctx)
        kind, table = opened.layout.project_kind, opened.layout.objects.get(PARAMETER)
        project = opened.parts.get(kind)
        held = table.entries(project.data) if table and project and project.data is not None else {}
        texts = {name: value if isinstance(value, str) else str(value) for name, value in held.items()}
        parameters, circles, wrong = resolve(texts, units)

        def at(name: str) -> Address:
            return Address(kind, None, (*table.keys, name))

        found = [door.finding(opened, at(circle[0]), code="parameter-circle",
                              message=f"the parameters {' → '.join(circle)} use each other in a circle")
                 for circle in circles]
        found += [door.finding(opened, at(name), code="bad-quantity", message=f"the parameter {name} does not read: {why}")
                  for name, why in wrong.items()]
        return cls(opened=opened, units=units, formulations=catalogue.formulations(ctx),
                   properties=catalogue.properties(ctx), places=catalogue.places(ctx),
                   environments=frozenset(catalogue.environments(ctx)), parameters=parameters,
                   unresolved=frozenset(texts) - set(parameters), issues=tuple(found),
                   known=project is not None and project.data is not None)

    def unresolved_in(self, text: str) -> bool:
        """Whether ``text`` uses a parameter that does not resolve — or, while the project file
        does not load, any name that is no unit: what it holds is not known, and the project
        file's own finding says why (models.md § 3)."""
        used = {n for _, _, n in name_spans(text)}
        return bool(used & self.unresolved) or (not self.known and bool(used - set(self.units.symbols())))

    def quantity(self, text: str) -> Quantity:
        """``text`` read as a quantity or an expression of the project's parameters (core.md § 11);
        a `UnitError` naming what does not read."""
        return self.units.parse(text, self.parameters)

    def measure(self, part: Part, keys: tuple[str, ...], value: Any, dimension: Dimension | None = None,
                what: str = "", *, parameters: bool = True) -> tuple[Quantity | None, list[Issue]]:
        """The value at ``keys`` of ``part``, written as a quantity — a number as itself, a text by
        the one grammar (core.md § 11) — read exactly and, given a ``dimension``, in it, ``what``
        saying that dimension to a person: the quantity, or the finding at its key. With
        ``parameters``, it may be an expression of the project's parameters, and one using a
        parameter that does not resolve — any, while the project file does not load — is neither,
        the parameter's or the project file's own finding saying why (models.md § 3); without, it
        names none — a material's (projects.md § 3). The findings:
        `bad-quantity`, a value that is no quantity or does not read; `wrong-dimension`, one
        outside ``dimension``."""
        if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
            text = str(Fraction(value))
        elif isinstance(value, str):
            text = value
        else:
            return None, [self.issue(part, *keys, code="bad-quantity", message=f"{persist.inline_text(value)} is no "
                                     "quantity: write a number, or a value with its unit in quotes")]
        if parameters and self.unresolved_in(text):
            return None, []
        try:
            found = self.quantity(text) if parameters else self.units.parse(text)
        except UnitError as exc:
            return None, [self.issue(part, *keys, code="bad-quantity", message=f"{text!r} does not read: {exc}")]
        if dimension is not None and found.dimension != dimension:
            return None, [self.issue(part, *keys, code="wrong-dimension", message=f"{text!r} is not {what}")]
        return found, []

    def issue(self, part: Part, *keys: str, code: str, message: str, severity: str = "error", right: Any = None,
              choices: Iterable[Any] = (), label: str | None = None, next: Iterable[Action] = ()) -> Issue:
        """A finding at ``part``'s file and the key ``keys`` name (core.md § 10): ``right``, the one
        value that would be right, or ``choices``, the values that would — each a plain value,
        written as the file would write it."""
        return door.finding(self.opened, Address(part.address.kind, part.address.name, keys), code=code,
                            message=message, severity=severity, label=label, next=next,
                            right=None if right is None else persist.inline_text(right),
                            choices=[persist.inline_text(c) for c in choices])

    def unchecked(self, part: Part, *keys: str, message: str) -> Issue:
        """What cannot be checked yet, said so (projects.md § 6): an `info` finding the part's state
        reads as `unchecked` (projects.md § 8)."""
        return self.issue(part, *keys, code=door.UNCHECKED, message=message, severity="info")


def resolve(texts: Mapping[str, str], units: Units) -> tuple[dict[str, Quantity], list[list[str]], dict[str, str]]:
    """The parameters resolved by name, in any order (models.md § 3): each that resolves, exactly;
    each circle of parameters using each other, from where it was met back to it; and each
    parameter whose own text does not read, with why. One using a parameter that does not
    resolve does not resolve either, and has no finding of its own."""
    uses = {name: [n for _, _, n in name_spans(text) if n in texts] for name, text in texts.items()}
    values: dict[str, Quantity] = {}
    failed: set[str] = set()
    circles: list[list[str]] = []
    wrong: dict[str, str] = {}
    walking: list[str] = []

    def visit(name: str) -> None:
        if name in values or name in failed:
            return
        if name in walking:
            circle = walking[walking.index(name):]
            circles.append([*circle, name])
            failed.update(circle)
            return
        walking.append(name)
        for used in uses[name]:
            visit(used)
        walking.pop()
        if name in failed or any(used in failed for used in uses[name]):
            failed.add(name)
            return
        try:
            values[name] = units.parse(texts[name], {n: values[n] for n in uses[name]})
        except UnitError as exc:
            wrong[name] = str(exc)
            failed.add(name)

    for name in texts:
        visit(name)
    return values, circles, wrong


#: The order findings come in, by severity: the first finding is the next step (models.md § 11.2).
SEVERITIES = ("error", "warning", "info")


def run(opened: Opened, ctx: Context) -> list[Issue]:
    """Every finding on the project (projects.md § 6; models.md §§ 11.1, 11.2): the door's, the
    parameters', and each loaded part's registered checks' — the errors first, then the warnings,
    then the notes, so the first is the next step; each in the chain's order, part by part as the
    layout ranks their kinds, those on files that are no part's last."""
    return findings(Checking.of(opened, ctx))


def findings(checking: Checking) -> list[Issue]:
    """Every finding on the project ``checking`` holds, as `run` gives them, from a frame made once."""
    opened = checking.opened
    found = [*opened.issues, *checking.issues]
    kinds = opened.layout.kinds

    def place(part: Part) -> tuple[int, str]:
        return kinds[part.address.kind].rank, part.file

    for part in sorted(opened.parts.values(), key=place):
        if part.data is not None:
            for check in _CHECKS.get(kinds[part.address.kind].schema_, ()):
                found += list(check(checking, part))

    def order(issue: Issue) -> tuple[int, int, int, str]:
        owner = opened.owner(issue.subject)
        return (SEVERITIES.index(issue.severity), *((1, 0, "") if owner is None else (0, *place(owner))))

    return sorted(found, key=order)
