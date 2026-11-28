"""What the models package reads of a project's parts and checks in each alike (models.md §§ 3, 5).

A component's contract, a material's properties and a recipe's sizes are read through the
layout's object types (projects.md § 4) — `layout.held` on whatever schema loaded the part — so
a study is paired from the contracts before anything runs (geometry.md § 3). Every part kind of
this package checks alike each part its fields cite (projects.md § 3); a value written as a
quantity is read by the check frame (`Checking.measure`, projects.md § 6). `quantities` is the
one walk of a part's quantities, by the `quantity` annotation (core.md § 2) and the parameters a
declaration lists.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable, Iterator, Mapping

from pydantic import BaseModel, ConfigDict, Field

from femkit.core.issues import Issue
from femkit.core.schema import (Measured, Model, allowed, classes, field_extras, field_named, meant, nearest,
                                references, values_of)
from femkit.definitions.places import PlaceKind, possible
from femkit.materials.assign import ASSIGNMENT, DATASETS, DIMENSION, FRAME, GROUP, PROPERTY
from femkit.materials.material import Answer, answering
from femkit.projects import door
from femkit.projects.addresses import Address
from femkit.projects.checking import Checking
from femkit.projects.door import Opened, Part
from femkit.projects.layout import held

#: The object types this package reads of other parts, by their names in the layout, beside those
#: the materials package reads of a component and a material (`femkit/materials/assign.py`).
INPUT, SIZE = "input", "size"
SYMMETRY, AXIS = "symmetry", "axis"   # the frame's axis of revolution, as its file writes it (geometry.md § 3)


class Parameterized(Model):
    """A model whose keys beyond its fields are the parameters a declaration lists for its kind —
    a condition's or a source's, as its formulation lists them (models.md § 3) — each a quantity
    in the one form (core.md § 11)."""

    model_config = ConfigDict(extra="allow", frozen=True)
    __pydantic_extra__: dict[str, Measured] = Field(init=False)

    @property
    def parameters(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


# ------------------------------------------------------------------ reading other parts

def table(value: Any) -> dict[str, Any]:
    """A loaded table as its keys and values, whatever schema loaded it; unset ones left out."""
    if isinstance(value, BaseModel):
        fields = {f.alias or n: getattr(value, n) for n, f in type(value).model_fields.items()}
        return {k: v for k, v in {**fields, **(value.model_extra or {})}.items() if v is not None}
    return dict(value) if isinstance(value, dict) else {}


def integer(value: Any) -> int | None:
    """A whole number as a file writes it — a dimension, a count — or None."""
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    return int(value) if Fraction(value).denominator == 1 else None


def objects(opened: Opened, part: Part, kind: str) -> dict[str, Any]:
    """The entries of object type ``kind`` in a loaded part; none when the layout has no such type."""
    found = opened.layout.objects.get(kind)
    return found.entries(part.data) if found and part.data is not None and found.part == part.address.kind else {}


@dataclass(frozen=True)
class Assigned:
    """One body group's assignment (materials.md § 5): its material by name, and the dataset each
    property uses where its material holds several."""

    material: str | None
    datasets: dict[str, str]


@dataclass(frozen=True)
class Contract:
    """A component's contract as its file states it (geometry.md § 3), with its assignment."""

    part: Part
    frame: Any                    # the frame, as loaded
    dimension: int | None         # the frame's dimension: 2 or 3
    axis: str | None              # the axis it is revolved about, for an axisymmetric physics
    groups: dict[str, int]        # each promised group, with its dimension
    inputs: dict[str, Any]        # each project definition the script reads, with what it must be
    assign: dict[str, Assigned]   # each body group's material

    def places(self, group: str, places: Mapping[str, PlaceKind]) -> list[str]:
        """The places ``group`` may be before the geometry exists (geometry.md § 7): none for a
        group it does not promise."""
        if self.dimension is None or group not in self.groups:
            return []
        return possible(places, self.dimension, self.groups[group])

    def standing(self, on: Iterable[str] | None, places: Mapping[str, PlaceKind]) -> list[str]:
        """The groups it promises that may be one of the places ``on`` names — every group, given
        none (geometry.md § 7)."""
        return [g for g in self.groups if on is None or set(self.places(g, places)) & set(on)]


def contract(opened: Opened, part: Part) -> Contract | None:
    """The contract a loaded component states; None for one that does not load."""
    if part.data is None:
        return None
    frame = next(iter(objects(opened, part, FRAME).values()), None)
    groups = {g: d for g, v in objects(opened, part, GROUP).items() if (d := integer(v)) is not None}
    assign = {g: Assigned(material=m if isinstance(m := held(v, "material"), str) else None,
                          datasets={k: d for k, d in table(held(v, DATASETS)).items() if isinstance(d, str)})
              for g, v in objects(opened, part, ASSIGNMENT).items()}
    axis = held(held(frame, SYMMETRY), AXIS)
    return Contract(part=part, frame=frame, dimension=integer(held(frame, DIMENSION)),
                    axis=axis if isinstance(axis, str) else None, groups=groups, inputs=objects(opened, part, INPUT),
                    assign=assign)


def material(opened: Opened, name: str) -> Part | None:
    """The material ``name`` names, loaded (materials.md § 4): `GLOBAL/<name>` the global
    library's; any other the project's own first, then the library's. None for one in neither, or
    one that does not load."""
    found = door.named(opened, opened.layout.objects[PROPERTY].part, name)
    return found if found is not None and found.data is not None else None


def datasets(c: Checking, part: Part) -> dict[str, dict[str, Answer]]:
    """A loaded material's datasets, by the property each answers and then by name, each with the
    property it is held under — the one it answers, or an equivalent form of it (materials.md
    §§ 1, 3; `material.answering`)."""
    return answering(c.properties, {prop: table(sets) for prop, sets in objects(c.opened, part, PROPERTY).items()})


# ------------------------------------------------------------------ what every part of this package checks

def called(address: Address) -> str:
    """A part as a sentence names it: `the project file`; any other by its address, as a person
    names it in a command and `project check` lists it — `` `observables:benchmark` `` — so a
    kind named in the plural, as an observables part's is, never reads as many (projects.md § 5)."""
    if address.name is None:
        return "the project file"
    return f"`{address}`"


def listed(items: Iterable[str], form: str = "`{}`") -> str:
    """Names as a person lists them: `` `a` ``, `` `a` and `b` ``, `` `a`, `b` and `c` `` — each
    in ``form``."""
    shown = [form.format(i) for i in items]
    return " and ".join(shown) if len(shown) < 3 else ", ".join(shown[:-1]) + " and " + shown[-1]


@dataclass(frozen=True)
class Missing:
    """A name a part cites, by a field's `ref`, that names no part of the project."""

    location: tuple               # where it is written, a list's index included
    held: str                     # how: `key`, `value` or `item` (core.md § 2, `references`)
    name: str
    kinds: list[str]              # the part kinds it may name
    there: list[str]              # the names of those kinds the project holds
    near: str | None              # the closest of them: what a misspelling most likely meant

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(str(p) for p in self.location if not isinstance(p, int))


def missing(c: Checking, part: Part) -> Iterator[Missing]:
    """Each name a field of ``part`` cites, by its `ref`, that names no part — of the project, or
    of the global library of a kind with one (projects.md § 3; materials.md § 4)."""
    layout = c.opened.layout
    for location, ref, name, how in references(part.data):
        kinds = [t for t in ref.split("|") if t in layout.kinds]
        if not kinds or any(door.named(c.opened, k, name) is not None for k in kinds):
            continue
        there = sorted({n for k in kinds for n in door.known(c.opened, k)})
        yield Missing(location, how, name, kinds, there, nearest(name, there))


def cited(c: Checking, part: Part) -> Iterator[Issue]:
    """Each name a field of ``part`` cites that names no part (projects.md § 3): a finding at the
    key — its right value, where one name it may give is close, the value with that name put in
    place; else the names it may give its choices: the project's parts of that kind, and, of a
    kind with a global library, the library's, `GLOBAL/<name>` (materials.md § 4)."""
    for m in missing(c, part):
        right: Any = None
        if m.near is not None and m.held == "value":
            right = m.near
        elif m.near is not None and m.held == "item":
            right = [m.near if n == m.name else n for n in _value(part.data, m.keys)]
        yield c.issue(part, *m.keys, code="no-such-part", label=m.name, right=right,
                      choices=() if right is not None else m.there,
                      message=f"the project holds no {' or '.join(m.kinds)} `{m.name}`" + meant(m.name, m.there))


def _value(data: Any, keys: tuple[str, ...]) -> Any:
    """What a loaded part holds at ``keys``, as its file writes them."""
    for key in keys:
        data = held(data, key)
    return data


def quantities(value: Any, at: tuple = ()) -> Iterator[tuple[tuple, str, Any]]:
    """Every value ``value`` writes as a quantity, as ``(location, kind, value)``: each field's by
    its `quantity` annotation — itself, a list's items, a table's values, but a closed value the
    field allows beside them, a range's `all` — and each parameter a declaration lists
    (`Parameterized`), of kind `any`."""
    if isinstance(value, BaseModel):
        for name, field in type(value).model_fields.items():
            kind, inner, key = field_extras(field).get("quantity"), getattr(value, name), field.alias or name
            if kind is None:
                yield from quantities(inner, (*at, key))
            elif inner not in allowed(field.annotation):
                yield from _each(inner, (*at, key), kind)
        if isinstance(value, Parameterized):
            yield from (((*at, k), "any", v) for k, v in value.parameters.items())
    elif isinstance(value, dict):
        for k, inner in value.items():
            yield from quantities(inner, (*at, k))
    elif isinstance(value, (list, tuple)):
        for i, inner in enumerate(value):
            yield from quantities(inner, (*at, i))


def _each(value: Any, at: tuple, kind: str) -> Iterator[tuple[tuple, str, Any]]:
    if isinstance(value, dict):
        for k, inner in value.items():
            yield from _each(inner, (*at, k), kind)
    elif isinstance(value, (list, tuple)):
        for i, inner in enumerate(value):
            yield from _each(inner, (*at, i), kind)
    elif value is not None:
        yield at, kind, value


def quantity_kind(model: type[BaseModel], path: tuple[str, ...]) -> str | None:
    """The `quantity` kind of the value at ``path`` in a file ``model`` reads: its field's, or that
    of the field whose table or list holds it; None where the schema writes no quantity there, or
    does not name the key."""
    annotation: Any = model
    for key in path:
        named = next((found for m in classes(annotation) if (found := field_named(m, key))), None)
        if named is not None:
            kind = field_extras(named[1]).get("quantity")
            if kind is not None:
                return kind
            annotation = named[1].annotation
        elif values_of(annotation) is not None:
            annotation = values_of(annotation)
        else:
            return None
    return None
