"""The check frame (projects.md § 6; models.md §§ 3, 11.1): what `project check` hands each part
kind's check, and the run over a project's parts in the chain's order.

It sits with the door, below every package that owns a part kind — `materials`, `geometry`,
`models` — so each imports it and types its checks by it (framework.md § 1). What a module of
the registry's `PARTS` registers is one shape, `Registration`, declared beside its schemas as
`REGISTERS` and filled only with what the module has (api.md § 6). Each part kind's check is
declared by the module that owns it, `checks={"<schema key>": check}`, `check(checking, part) ->
Iterable[Issue]`; the registry registers each here when femkit starts, so this module imports no
package of a part. A key may have checks from several modules — a component's assignment is the
materials package's (projects.md § 2) — run in the registry's order.

The keys a part's file may hold (web.md § 8.3) are built here too, by the core's one builder of
fragments (`view.Field.keys`), from the part's registered schema and the keys a declaration beside
it states: each module that owns a schema declares those beside it, `keys={"<schema key>":
stated}`, `stated(checking, text, manual) -> list[DeclaredKey]` — a physics' formulation and its
kinds and parameters, a material's properties, a step's kind — registered here at start as a
check is (`keys`).

A check finds; it never refuses: what it finds is a finding at the part's file and key, made by
`Checking.issue`; a value written as a quantity is read by `Checking.measure`, by the core's one
reader of the one quantity form (core.md § 11); what it cannot check yet is said so by
`Checking.unchecked`. The project's definitions reach it resolved by the
models domain, which reads, checks and computes them (models.md § 3): this frame holds them as it
is handed them (`Defined`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping

from femkit.core import persist
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.schema import DeclaredKey, names_in
from femkit.core.units import Dimension, Quantity, UnitError, Units
from femkit.core.view import Action, Field
from femkit.definitions import catalogue
from femkit.definitions.dispersion import Dispersion
from femkit.definitions.formulations import FormulationDefinition, StepKind
from femkit.definitions.meshers import HandOver, MesherDefinition
from femkit.definitions.places import PlaceKind
from femkit.definitions import stages as stage_kinds
from femkit.definitions.properties import Property
from femkit.projects import door, schemas
from femkit.projects.addresses import Address
from femkit.projects.door import Held, Opened, Part
from femkit.engines.person.functions import Fault

DEFINITION = "definition"   # the object type the project file holds its definitions as (projects.md § 4)

Check = Callable[["Checking", Part], Iterable[Issue]]
_CHECKS: dict[str, tuple[Check, ...]] = {}
#: What states the keys a declaration beside a part schema gives (web.md § 8.3): from the frame, the
#: part's text and the manual's chapter its kind declares.
Stated = Callable[["Checking", str, "str | None"], list[DeclaredKey]]
_STATED: dict[str, tuple[Stated, ...]] = {}


@dataclass(frozen=True)
class Registration:
    """What a module of the registry's `PARTS` registers at femkit's start (api.md § 6) — one shape,
    which a module declares beside its schemas as `REGISTERS`, filled only with what it has: each
    part schema it owns by the key a layout names it by (`schemas`, projects.md § 4); the check
    of each schema it checks, another module's possibly (`checks`); what states the keys a
    declaration gives beside a schema (`keys`, web.md § 8.3); and what gives the conda packages the
    projects under the projects root declare for their scripts, which femkit's start hands the envs
    domain below it (`packages`, definitions.md § 4.7) — the project file's, one module's alone."""

    schemas: Mapping[str, type] = field(default_factory=dict)
    checks: Mapping[str, Check] = field(default_factory=dict)
    keys: Mapping[str, Stated] = field(default_factory=dict)
    packages: Callable[[Context], Any] | None = None


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


def register_keys(key: str, stated: Stated) -> None:
    """``stated`` gives the keys a declaration states beside the schema the layout calls ``key``;
    registering it again changes nothing."""
    held = _STATED.get(key, ())
    if stated not in held:
        _STATED[key] = (*held, stated)


def stated(c: "Checking", part: Part) -> list[DeclaredKey]:
    """The keys the declarations beside ``part``'s schema state in its text (web.md § 8.3): what
    each registered for its schema gives; none for a part whose text was not read."""
    text = c.opened.texts.get(part.file)
    kind = c.opened.layout.kinds[part.address.kind]
    return [] if text is None else [d for give in _STATED.get(kind.schema_, ()) for d in give(c, text, kind.manual)]


def keys(c: "Checking", part: Part) -> list[Field]:
    """Every key ``part``'s file may hold (web.md § 8.3), by the one builder of fragments
    (`view.Field.keys`): its registered schema's, and those the declarations beside it state — a
    part that does not load among them, from its text; none for one whose text was not read."""
    text = c.opened.texts.get(part.file)
    kind = c.opened.layout.kinds[part.address.kind]
    if text is None:
        return []
    return Field.keys(schemas.registered()[kind.schema_], text, stated(c, part), c.units, kind.manual)



@dataclass(frozen=True)
class Defined:
    """The project's definitions as the models domain resolves them for every check (models.md
    § 3): each real one whose value is at hand, by name, in SI exactly — a constant's as written,
    a computed one's as its function returned it; the names of those whose value is not — a
    finding of their own says why, or, for a computed one, its value is not computed here — and of
    the complex ones, which no field of a real number names; and what resolving them found,
    each finding at its definition's key or at its file and line — and each one's dimension, its
    unit's, the person's promise of what its value is."""

    values: Mapping[str, Quantity] = field(default_factory=dict)
    dimensions: Mapping[str, Dimension] = field(default_factory=dict)
    unresolved: frozenset[str] = frozenset()
    complex: frozenset[str] = frozenset()
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class Checking:
    """What each part kind's check is handed: the project as opened, the definitions its rules
    read, and the project's own definitions resolved once (projects.md § 6; models.md § 3)."""

    opened: Opened
    units: Units
    formulations: Mapping[str, FormulationDefinition]
    properties: Mapping[str, Property]
    dispersion: Dispersion               # the variables and the dispersion models (materials.md § 2)
    step_kinds: Mapping[str, StepKind]   # what each kind of calculation supplies (models.md § 4.2)
    places: Mapping[str, PlaceKind]
    engines: Mapping[str, str]            # each engine `study prep --engine` may name, with the environment it
                                          # resolves to (models.md § 5.1; framework.md § 5)
    meshers: Mapping[str, MesherDefinition]   # the meshers a mesh recipe may state (workflow.md § 2.3)
    handovers: Mapping[str, HandOver]     # how each engine receives a mesh (geometry.md § 8)
    running: Mapping[str, frozenset[str]]  # for each part kind a stage kind brings, the modules the environment
                                           # that kind runs in provides: what its script may import beside the
                                           # project's packages — `observe.py`'s, the observe kind's `postprocess`
                                           # (workflow.md § 2.1; models.md § 5.2)
    stages: Mapping[str, stage_kinds.StageKind]   # the stage kinds (workflow.md § 2.1)
    held: frozenset[str]                 # every package femkit's recipe declares or pins, by name, for the
                                         # environment that takes the projects' packages (definitions.md § 4.7)
    definitions: Mapping[str, Quantity]  # each real definition whose value is at hand, by name, in SI exactly
    dimensions: Mapping[str, Dimension]  # each definition whose unit reads, its unit's dimension
    unresolved: frozenset[str]           # each whose value is not: its own finding, or the run, says why
    complex: frozenset[str]              # each complex one: no field of a real number names it
    issues: tuple[Issue, ...]            # what resolving them found
    known: bool = True                   # whether the definitions are known: the project file loads

    @classmethod
    def of(cls, opened: Opened, ctx: Context, defined: Defined) -> "Checking":
        """The frame for ``opened``, its definitions as the models domain resolved them
        (``defined``, models.md § 3)."""
        project = opened.parts.get(opened.layout.project_kind)
        return cls(opened=opened, units=catalogue.units(ctx), formulations=catalogue.formulations(ctx),
                   properties=catalogue.properties(ctx), dispersion=catalogue.dispersion(ctx),
                   step_kinds=catalogue.step_kinds(ctx), places=catalogue.places(ctx),
                   engines=catalogue.engines(ctx), meshers=catalogue.meshers(ctx), handovers=catalogue.handovers(ctx),
                   running=_running(ctx), stages=catalogue.stages(ctx).kinds,
                   held=frozenset().union(*(e.held for e in catalogue.environments(ctx).values() if e.projects)),
                   definitions=dict(defined.values),
                   dimensions=dict(defined.dimensions),
                   unresolved=frozenset(defined.unresolved), complex=frozenset(defined.complex),
                   issues=tuple(defined.issues), known=project is not None and project.data is not None)

    def measure(self, part: Part, keys: tuple[str, ...], value: Any, dimension: Dimension | None = None,
                what: str = "", *, definitions: bool = True, unit: str | None = None
                ) -> tuple[Any, list[Issue]]:
        """The value at ``keys`` of ``part``, written in the one quantity form (core.md § 11) —
        `{value, unit}`, a plain number where it has no unit and, with ``definitions``, a
        definition's name, alone or in place of any number of a `{value, unit}` — read exactly by
        the units' one reader and, given a ``dimension``, in it, ``what`` saying that dimension to
        a person and ``unit`` the unit it is stated in: the quantity — each of a range's, a list —
        or the finding at its key. A definition's name is one the project
        defines, of the field's dimension; one whose value is not at hand — any, while the project
        file does not load — is neither, the definition's or the project file's own finding saying
        why (models.md § 3); a complex one is no value of a real field. Without ``definitions`` a
        text names none — a material's (projects.md § 3). The findings: `bad-quantity`, a value
        that does not read — a text saying the table to write, a name the project does not define
        with the definitions of the field's dimension its choices, or, among a `{value, unit}`'s
        numbers, the table with the name put right; `wrong-dimension`, one outside ``dimension`` —
        a plain number with the table it would be, in ``unit``; a definition named, naming it."""
        names = names_in(value) if definitions else []
        complex_ = next((n for n in names if n in self.complex), None)
        if complex_ is not None:
            return None, [self.issue(part, *keys, code="bad-quantity",
                                     message=f"`{complex_}` is a complex definition, and this value is a real number")]
        if any(n in self.unresolved for n in names) or names and not self.known:
            other = next((n for n in names if dimension is not None
                          and self.dimensions.get(n) not in (None, dimension)), None)
            if other is not None:
                return None, [self.issue(part, *keys, code="wrong-dimension",
                                         message=f"the definition `{other}` is not {what}")]
            return None, []
        try:
            found = self.units.measure(value, self.definitions if definitions else None)
        except UnitError as exc:
            named = definitions and isinstance(value, str) and value.isidentifier() and exc.right is None
            return None, [self.issue(part, *keys, code="bad-quantity", right=exc.right,
                                     choices=sorted(n for n, d in self.dimensions.items() if n not in self.complex
                                                    and (dimension is None or d == dimension)) if named else (),
                                     message=str(exc) if isinstance(value, str) else
                                     f"{_written(value)} does not read: {exc}")]
        if dimension is not None and any(q.dimension != dimension for q in _leaves(found)):
            plain = isinstance(value, (int, Decimal)) and not isinstance(value, bool)
            stated = unit or self.units.si(dimension)
            other = next((n for n in names if self.definitions[n].dimension != dimension), None)
            said = f"the definition `{other}`" if other is not None else _written(value)
            return None, [self.issue(part, *keys, code="wrong-dimension",
                                     right={"value": value, "unit": stated} if plain else None,
                                     message=f"{said} is not {what}"
                                             + (f": a number with no unit; it is {{value = {_written(value)}, "
                                                f'unit = "{stated}"}}' if plain else ""))]
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


def _running(ctx: Context) -> dict[str, frozenset[str]]:
    """For each part kind a stage kind brings, the modules the environment that kind declares it runs
    in provides (workflow.md § 2.1): the one home of where a part's script runs, read from the stage
    kinds, never from an environment's own name or flags."""
    environments = catalogue.environments(ctx)
    return {kind.brings: frozenset(environments[kind.environment].provides.modules)
            for kind in catalogue.stages(ctx).kinds.values()
            if kind.brings is not None and kind.environment in environments}


def _leaves(found: Any) -> list[Quantity]:
    """Each quantity a value read gives: itself, or each of a range's."""
    return [q for item in found for q in _leaves(item)] if isinstance(found, list) else [found]


def _written(value: Any) -> str:
    """A value as its file writes it, for a sentence: `{value = 0.1, unit = "m"}`, `"bias"`, `4`."""
    try:
        return persist.inline_text(value.model_dump() if hasattr(value, "model_dump") else value)
    except (TypeError, ValueError):
        return repr(value)


def at_line(opened: Opened, held: Held, fault: Fault) -> Issue:
    """What the one static reader of a file of the person's functions finds in it, a `Fault`
    (`engines/person/functions.py`), as a finding (core.md § 10): an error at that file and the line
    the fault names, its subject the file's address, `<kind>:<name>@<file>` — the project's
    `definitions.py`, a part's `observe.py` — so the part holding it counts it (`Opened.owner`). The
    one maker of a finding at a line of the person's Python (models.md §§ 3, 5.2)."""
    return Issue(severity="error", code=fault.code, subject=str(Address(held.part.kind, held.part.name, file=held.name)),
                 message=fault.message, file=held.file, line=fault.line)


#: The order findings come in, by severity: the first finding is the next step (models.md § 11.2).
SEVERITIES = ("error", "warning", "info")


def run(opened: Opened, ctx: Context, defined: Defined) -> list[Issue]:
    """Every finding on the project (projects.md § 6; models.md §§ 11.1, 11.2): the door's, the
    definitions' as ``defined`` holds them, and each loaded part's registered checks' — the errors
    first, then the warnings, then the notes, so the first is the next step; each in the chain's
    order, part by part as the layout orders them (`Layout.chain`: by rank, then the kind's place,
    then name), those on files that are no part's last."""
    return findings(Checking.of(opened, ctx, defined))


def findings(checking: Checking) -> list[Issue]:
    """Every finding on the project ``checking`` holds, as `run` gives them, from a frame made once."""
    opened = checking.opened
    found = [*opened.issues, *checking.issues]
    layout = opened.layout

    def place(part: Part) -> tuple[int, int, str]:
        return layout.chain(part.address.kind, part.address.name)

    for part in sorted(opened.parts.values(), key=place):
        if part.data is not None:
            for check in _CHECKS.get(layout.kinds[part.address.kind].schema_, ()):
                found.extend(check(checking, part))

    def order(issue: Issue) -> tuple[int, int, int, int, str]:
        owner = opened.owner(issue.subject)
        return (SEVERITIES.index(issue.severity), *((1, 0, 0, "") if owner is None else (0, *place(owner))))

    return sorted(found, key=order)
