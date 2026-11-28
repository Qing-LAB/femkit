"""A study's axes (models.md § 5.1): each keyed by the address of what it varies (projects.md
§ 5) — a definition of the project file written as its value, a value of the study's mesh recipe,
one of its own numerics, or the dataset a material of its component uses — with its values and one
class; a
group of axes that step together crossed as one, at its first axis's place as the study writes
them (`crossed`, the cases' order); what is crossed, holding axes of more than one class, crossed
only with a `[crossing]` naming every axis.

An axis's values are plain numbers, its `unit` stated once — the values of a quantity in the one
form (core.md § 11) — or, over a material's dataset, the datasets' names: over what has a
dimension, a unit of it; over a dataset, or what has none, no unit. They are checked against what
they vary, each value in its key's place alone: a definition's, a number of its type in its unit
— what the definitions computed from it give is computed by `study prep` (models.md § 3); a
part's value, `{value, unit}` or a plain number, put in place and the part loaded again by its
own schema — the numerics' and the recipe's alike — and, for another part than the study,
checked again by its own checks at that key; a dataset, one its material holds. What the varied
part finds wrong of its own — a file that does not load, another key that does not read, a value
it holds now that does not read — is its own finding, never the axis's (models.md § 5.1). An axis
sweeps a definition written as its value, never one its function computes (models.md § 3).
`points` gives each point, each value of an axis stating a unit as `{value, unit}`; `apply` puts
a point in place, for a case.

Its findings, each on the study:
- `bad-axis` (error), at `axes."<address>"`: an address that does not read, resolve, or name what
  an axis may vary — its right value, the address of what it may vary that the key most likely
  means, where one is close;
- `bad-axis-unit` (error), at `axes."<address>".unit`: a unit missing where what it varies has a
  dimension, one that does not read or of another dimension — the unit what it varies is written
  in its right value — or one stated where what it varies has none;
- `bad-axis-value` (error), at `axes."<address>".values`: a value its target refuses — a text
  where a number belongs; for a dataset, the datasets its material holds its choices;
- `crossing-missing` (error), at `crossing`: what is crossed holds axes of more than one class,
  and no `[crossing]`;
- `crossing-incomplete` (error), at `crossing.axes`: right, every axis's address;
- at `together.<name>`, a group of axes that step together (error): `together-unknown`, it names
  an address no axis of the study has — the study's axes its choices; `together-twice`, it names
  an axis an earlier group names; `together-classes`, its axes are of more than one class;
  `together-lengths`, its axes hold different numbers of values.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Iterator

from pydantic import BaseModel

from femkit.core.errors import UsageError
from femkit.core.issues import Issue
from femkit.core.schema import (QUANTITIES, DefinitionError, Measure, Number, field_extras, key_path, nearest,
                                validate)
from femkit.core.units import Dimension, Quantity, UnitError, decimal
from femkit.models.parts import ASSIGNMENT, DATASETS, contract, datasets, material, quantity_kind
from femkit.projects import checking
from femkit.projects.addresses import Address
from femkit.projects.checking import DEFINITION, Checking
from femkit.projects.door import Part
from femkit.projects.layout import held

NUMERICS = "numerics"   # the study's own table an axis may vary (models.md § 5.1)
#: The study's object types whose tables its axes, their groups that step together and their
#: crossing live in, by the names the layout declares them under (projects.md § 4).
AXIS, TOGETHER, CROSSING = "axis", "together", "crossing"


@dataclass(frozen=True)
class Target:
    """What an axis varies: its address, the part holding it, how a point is put in place —
    `definition`, `value` or `dataset` — what it holds now — None for a definition whose value is
    not at hand now — and the `quantity` kind its schema writes it as (core.md § 2); None for a
    value no quantity."""

    address: Address
    part: Part
    how: str
    current: Any
    quantity: str | None = None


def written(value: Any) -> str:
    """An axis's value as a person reads it: a number its exact decimal, with its unit where its
    axis has one — `0.1 m`, `2` — a dataset's name as itself."""
    if isinstance(value, Measure):
        return f"{written(value.value)} {value.unit}"
    return value if isinstance(value, str) else decimal(Fraction(value))


def target(c: Checking, study: Part, key: str) -> Target | str | None:
    """What the axis ``key`` of ``study`` varies; or why it varies nothing an axis may; None for
    a part of the study's that does not load — the project file, its recipe, its component —
    whose own finding says why."""
    try:
        address = c.opened.layout.address(key)
    except UsageError as exc:
        return str(exc)
    part = c.opened.parts.get(str(address.part))
    if part is None:
        return f"{address.part} is no part of the project"
    data, layout, path = study.data, c.opened.layout, address.path
    refs = {name: field_extras(f).get("ref") for name, f in type(data).model_fields.items()}
    definitions = layout.objects[DEFINITION]
    if address.part not in (Address(definitions.part, None), Address(refs["mesh"], data.mesh), study.address,
                            Address(refs["component"], data.component)):
        return _none(key)
    if part.data is None:
        return None
    if address.kind == definitions.part and path[:-1] == definitions.keys and path[-1] in _table(c):
        held_now = _table(c)[path[-1]]
        if held_now.function is not None:
            return (f"`{key}` is computed by its function `{held_now.function}`: an axis sweeps a definition written "
                    "as its value, and `study prep` computes what is computed from it")
        return Target(address, part, "definition", c.definitions.get(path[-1]), "any")
    if (address.part == Address(refs["mesh"], data.mesh) or (address.part == study.address and path[:1] == (NUMERICS,))) \
            and (now := _at(part.data, path)) is not None:
        return Target(address, part, "value", now, quantity_kind(type(part.data), path))
    assign = layout.objects[ASSIGNMENT]
    if address.part == Address(refs["component"], data.component) and len(path) == len(assign.keys) + 3 \
            and path[:len(assign.keys)] == assign.keys and path[-2] == DATASETS:
        return Target(address, part, "dataset", None)
    return _none(key)


def _none(key: str) -> str:
    return (f"`{key}` is none of what an axis varies: a definition written as its value, a value of the study's "
            f"mesh recipe, one of its {NUMERICS}, or the dataset a material of its component uses")


def varied(c: Checking, study: Part) -> list[str]:
    """The address of everything an axis of ``study`` may vary now (models.md § 5.1): each
    definition written as its value; each value of its recipe and of its numerics; the dataset of
    each property of each body's material, the project's own or the global library's, where it
    loads."""
    data, layout = study.data, c.opened.layout
    refs = {name: field_extras(f).get("ref") for name, f in type(data).model_fields.items()}
    definitions, assign = layout.objects[DEFINITION], layout.objects[ASSIGNMENT]
    found = [str(Address(definitions.part, None, (*definitions.keys, n)))
             for n, d in _table(c).items() if d.function is None]
    recipe = c.opened.parts.get(str(Address(refs["mesh"], data.mesh)))
    for holder, root in ((recipe, ()), (study, (NUMERICS,))):
        if holder is not None and holder.data is not None:
            found += [str(Address(holder.address.kind, holder.address.name, path))
                      for path in _leaves(_under(holder.data, root), root)]
    component = c.opened.parts.get(str(Address(refs["component"], data.component)))
    k = contract(c.opened, component) if component is not None else None
    for group, assigned in k.assign.items() if k else ():
        m = material(c.opened, assigned.material) if assigned.material else None
        found += [str(Address(component.address.kind, component.address.name, (*assign.keys, group, DATASETS, prop)))
                  for prop in (datasets(c, m) if m is not None else {})]
    return found


def _under(data: Any, root: tuple[str, ...]) -> Any:
    for key in root:
        data = held(data, key)
    return data


def _leaves(data: Any, at: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Every key path of a value in ``data``, a part as loaded, that is no table or list — a
    quantity's `{value, unit}` one value (core.md § 11) — `schema` left out."""
    if isinstance(data, Measure):
        return [at]
    if isinstance(data, BaseModel):
        return [p for n, f in type(data).model_fields.items() if (f.alias or n) != "schema"
                for p in _leaves(getattr(data, n), (*at, f.alias or n))]
    if isinstance(data, dict):
        return [p for k, v in data.items() for p in _leaves(v, (*at, str(k)))]
    return [at] if at and data is not None and not isinstance(data, list) else []


def address_meant(c: Checking, study: Part, key: str) -> str | None:
    """The address an axis keyed ``key`` most likely means, of those it may vary: for an address
    of a part, the value of that part whose key path is closest to its own; for a key that is no
    address, the one whose last key it is, or whose last key is closest to it — where only one
    is."""
    found = varied(c, study)
    try:
        address = c.opened.layout.address(key)
    except UsageError:
        last = {a: a.replace(":", ".").rpartition(".")[2] for a in found}
        near = key if key in last.values() else nearest(key, sorted(set(last.values())))
        meant_by = [a for a, step in last.items() if step == near]
        return meant_by[0] if len(meant_by) == 1 else None
    head = f"{address.part}:"
    paths = {a.removeprefix(head): a for a in found if a.startswith(head)}
    near = nearest(key_path(address.path), paths)
    return paths[near] if near is not None else None


def _at(data: Any, path: tuple[str, ...]) -> Any:
    """The value at ``path`` of a part as loaded — a quantity's `{value, unit}` one value — or None
    where it holds a table or a list."""
    for key in path:
        data = held(data, key)
    return None if isinstance(data, (dict, list)) or isinstance(data, BaseModel) and not isinstance(data, Measure) \
        else data


def replaced(part: Part, path: tuple[str, ...], value: Any, context: dict) -> BaseModel:
    """``part``'s data with ``value`` at ``path``, loaded again by its own schema: a
    `DefinitionError` naming what it refuses."""
    tree = part.data.model_dump(mode="python", by_alias=True)
    node = tree
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = value
    return validate(type(part.data), tree, part.file, context)


def check(c: Checking, study: Part) -> Iterator[Issue]:
    """Each axis's address, its unit and its values, and the crossing of axes of different
    classes."""
    data = study.data
    for key, axis in data.axes.items():
        found = target(c, study, key)
        if found is None:
            continue                                        # its part does not load: its own finding says why
        if isinstance(found, str):
            near = address_meant(c, study, key)
            yield c.issue(study, *c.opened.layout.objects[AXIS].keys, key, code="bad-axis", right=near,
                          message=f"`{key}` is no address of what an axis may vary; did you mean `{near}`?" if near
                          else found)
            continue
        wrong = unit_refused(c, found, axis.unit)
        if wrong is not None:
            why, right = wrong
            yield c.issue(study, *c.opened.layout.objects[AXIS].keys, key, "unit", code="bad-axis-unit", right=right,
                          message=f"the axis `{key}` {why}")
            continue
        for value in axis.values:
            why = refused(c, study, found, value, axis.unit)
            if why is not None:
                said = written(given(value, axis.unit))
                yield c.issue(study, *c.opened.layout.objects[AXIS].keys, key, "values", code="bad-axis-value", label=said,
                              choices=_held_datasets(c, found) if found.how == "dataset" else (),
                              message=f"the axis `{key}` cannot take `{said}`: {why}")
    yield from _together(c, study)
    units = crossed(study)
    classes = {data.axes[a].class_ for unit in units for a in unit} if len(units) > 1 else set()
    if len(classes) > 1 and data.crossing is None:
        yield c.issue(study, *c.opened.layout.objects[CROSSING].keys, code="crossing-missing",
                      message=f"what is crossed holds axes of {len(classes)} classes ({', '.join(sorted(classes))}), "
                              "with no `[crossing]` saying why their full product is needed")
    elif data.crossing is not None and sorted(data.crossing.axes) != sorted(data.axes):
        yield c.issue(study, *c.opened.layout.objects[CROSSING].keys, "axes", code="crossing-incomplete", right=list(data.axes),
                      message="the crossing names every axis of the study, and nothing else")


def dimension(c: Checking, found: Target) -> tuple[Dimension, str | None] | None:
    """The dimension of what ``found`` varies, and the unit it is written in where it has one: a
    definition's, its unit's; a value written as a quantity, the value's it holds now, or its
    kind's; none — and no unit — for a dataset, or a value that is no quantity, which an axis gives
    plain. None where it is not known — a definition whose unit, or a value whose quantity, does
    not read — its own finding saying why."""
    if found.how == "definition":
        held = c.dimensions.get(found.address.path[-1])
        return None if held is None else (held, _table(c)[found.address.path[-1]].unit if held else None)
    kind = QUANTITIES.get(found.quantity) if found.quantity is not None else None
    if found.how == "dataset" or kind is None or kind.reads == "unit":
        return (), None
    current = found.current
    try:
        now = c.units.measure(current, c.definitions if kind.cites else None).dimension
    except UnitError:
        now = c.dimensions.get(current) if isinstance(current, str) and kind.cites else None
    held = kind.dimension or now                 # a kind's own dimension, whatever the value holds now
    if held is None:
        return None
    return held, current.unit if isinstance(current, Measure) and now == held else None


def unit_refused(c: Checking, found: Target, unit: str | None) -> tuple[str, Any] | None:
    """Why an axis over ``found`` cannot state ``unit`` — none stated where what it varies has a
    dimension, one that does not read or is of another dimension, or one stated where what it
    varies has none — with the one unit that would be right; None where it can, or where what it
    varies is not known, its own finding saying why (models.md § 5.1)."""
    held = dimension(c, found)
    if held is None:
        return None
    wanted, written_in = held
    if not wanted:
        if unit is None:
            return None
        try:
            if found.how != "dataset" and not c.units.unit(unit).dimension:
                return None
        except UnitError:
            pass
        said = "a material's dataset, by its name" if found.how == "dataset" else "a value with no unit"
        return f"varies {said}, and states a unit, `{unit}`: its values have none", None
    right = written_in or c.units.si(wanted)
    if unit is None:
        return f"states no unit, and its values are numbers in the unit it states: `unit = \"{right}\"`", right
    try:
        one = c.units.unit(unit)
    except UnitError as exc:
        return f"states a unit that does not read: {exc}", right
    if one.dimension != wanted:
        return f"states `{unit}`, which is not in the dimension of what it varies, {right}", right
    return None


def refused(c: Checking, study: Part, found: Target, value: Any, unit: str | None) -> str | None:
    """Why ``found`` cannot take ``value``, given in ``unit``, in its key's place; None when it can,
    or when only what its part finds wrong of its own stands in the way — that part's own finding
    says why."""
    if found.how == "dataset":
        return _dataset(c, found, value)
    if isinstance(value, str):
        return (f"it is a text, and an axis's values are plain numbers" + (f", in its unit, {unit}" if unit else "")
                + ": a quantity is never written as a text")
    if found.how == "definition":
        return _definition(c, _table(c)[found.address.path[-1]], given(value, unit))
    try:
        data = replaced(found.part, found.address.path, put(value, unit), {"units": c.units})
    except DefinitionError as exc:
        return exc.summary()
    if found.part.address != study.address:                 # the study's own checks are the ones running
        changed = Part(found.part.address, found.part.file, data, found.part.folder)
        return _own(c, changed, found.address.path)
    return None


def given(value: Any, unit: str | None) -> Any:
    """An axis's value as the one quantity form holds it: `{value, unit}` where its axis states a
    unit, else the value as written — a plain number, a dataset's name."""
    return Measure[Number](value=value, unit=unit) if unit is not None and not isinstance(value, str) else value


def put(value: Any, unit: str | None) -> Any:
    """An axis's value as a part's file would write it in its key's place."""
    held = given(value, unit)
    return held.model_dump() if isinstance(held, Measure) else held


def _own(c: Checking, part: Part, path: tuple[str, ...]) -> str | None:
    """The first error ``part``'s own checks find at ``path``; None where they find none."""
    at = key_path(path)
    for rule in checking.registered().get(c.opened.layout.kinds[part.address.kind].schema_, ()):
        mine = [i.message for i in rule(c, part) if i.key == at and i.severity == "error"]
        if mine:
            return mine[0]
    return None


def _held_datasets(c: Checking, found: Target) -> list[str]:
    """The datasets the material of a dataset axis's body holds for its property — the project's
    own, or the global library's; none where it is found nowhere or does not load."""
    k = contract(c.opened, c.opened.part(found.address))
    assigned = k.assign.get(found.address.path[-3]) if k else None
    m = material(c.opened, assigned.material) if assigned and assigned.material else None
    return sorted(datasets(c, m).get(found.address.path[-1], {})) if m is not None else []


def _dataset(c: Checking, found: Target, value: Any) -> str | None:
    """Why the dataset of a property of a body group's material cannot be ``value``: the group is
    assigned no material, or its material holds no such dataset; None where its material is found
    nowhere or does not load, the component's or the material's own finding saying why."""
    k = contract(c.opened, c.opened.part(found.address))
    g, prop = found.address.path[-3], found.address.path[-1]
    assigned = k.assign.get(g) if k else None
    m = material(c.opened, assigned.material) if assigned and assigned.material else None
    if m is None:
        return None if assigned is not None else f"{g} is assigned no material"
    held_sets = datasets(c, m).get(prop, {})
    return None if value in held_sets else f"its material holds {', '.join(held_sets) or 'no dataset'} for {prop}"


def _table(c: Checking) -> dict[str, Any]:
    """The project file's definitions, each as its table holds it; none while it does not load."""
    table = c.opened.layout.objects[DEFINITION]
    project = c.opened.parts.get(c.opened.layout.project_kind)
    return table.entries(project.data) if project is not None and project.data is not None else {}


def _definition(c: Checking, d: Any, value: Measure | Number) -> str | None:
    """Why the definition ``d``, written as its value, cannot take ``value``, as its axis gives it
    (models.md § 3): it is complex — a pair no axis's number gives — or, for an `int`, no whole
    number; None where it can. Its dimension is its axis's unit's (`unit_refused`)."""
    if d.type == "complex":
        return "a complex definition's value is a pair, `[real, imaginary]`, which an axis's number does not give"
    number = value.value if isinstance(value, Measure) else value
    if d.type == "int" and Fraction(number).denominator != 1:
        return "it is no whole number, and the definition is an `int`"
    return None


def _together(c: Checking, study: Part) -> Iterator[Issue]:
    """Each group of axes that step together (models.md § 5.1), at its key: an address no axis of
    the study has, an axis an earlier group names, axes of more than one class, axes holding
    different numbers of values."""
    data, seen = study.data, {}
    for name, group in data.together.items():
        unknown = [a for a in group.axes if a not in data.axes]
        if unknown:
            yield c.issue(study, *c.opened.layout.objects[TOGETHER].keys, name, code="together-unknown", label=unknown[0],
                          choices=[a for a in data.axes if a not in group.axes],
                          message=f"the group `{name}` names `{unknown[0]}`, which is no axis of the study")
        twice = [a for a in group.axes if a in seen]
        if twice:
            yield c.issue(study, *c.opened.layout.objects[TOGETHER].keys, name, code="together-twice", label=twice[0],
                          message=f"the axis `{twice[0]}` steps together in the group `{seen[twice[0]]}` already, and "
                                  "an axis is in one group")
        seen.update({a: name for a in group.axes if a not in seen})
        known = [a for a in group.axes if a in data.axes]
        classes = sorted({data.axes[a].class_ for a in known})
        if len(classes) > 1:
            yield c.issue(study, *c.opened.layout.objects[TOGETHER].keys, name, code="together-classes",
                          message=f"the group `{name}` steps axes of {len(classes)} classes together "
                                  f"({', '.join(classes)}): numerical convergence and a physical sweep are different "
                                  "studies, so a group's axes are of one class")
        counts = {a: len(data.axes[a].values) for a in known}
        if len(set(counts.values())) > 1:
            yield c.issue(study, *c.opened.layout.objects[TOGETHER].keys, name, code="together-lengths",
                          message=f"the group `{name}` steps axes holding different numbers of values together ("
                                  + ", ".join(f"`{a}` {n}" for a, n in counts.items())
                                  + "): the n-th case takes each one's n-th value, so each holds as many")


def crossed(study: Part) -> list[tuple[str, ...]]:
    """What a study's axes cross, in its cases' order (models.md § 5.1): each group that steps
    together as one — its axes as the group names them — at its first axis's place as the study
    writes its axes; each other axis alone, at its own. A group's address no axis has, or an axis
    an earlier group names, is its finding's, and left out here."""
    axes = list(study.data.axes)
    taken: set[str] = set()
    units: list[tuple[str, ...]] = []
    for group in study.data.together.values():
        unit = tuple(dict.fromkeys(a for a in group.axes if a in study.data.axes and a not in taken))
        taken |= set(unit)
        units += [unit] if unit else []
    units += [(a,) for a in axes if a not in taken]
    return sorted(units, key=lambda unit: min(axes.index(a) for a in unit))


def points(study: Part) -> list[dict[str, Any]]:
    """Every axis point (models.md § 5.1): each step of what is crossed with every step of the
    others, in the cases' order (`crossed`) — a group's n-th step each of its axes' n-th value, an
    axis's each of its values; one point of no axis when it has none. Each point holds every axis,
    in the order the study writes them, each value of an axis stating a unit `{value, unit}`."""
    axes = study.data.axes
    units = crossed(study)
    steps = [list(zip(*([given(v, axes[a].unit) for v in axes[a].values] for a in unit))) for unit in units]
    out = []
    for chosen in itertools.product(*steps):
        held = {a: v for unit, values in zip(units, chosen) for a, v in zip(unit, values)}
        out.append({a: held[a] for a in axes if a in held})
    return out


def place(units: list[tuple[str, ...]], listed: dict[tuple[str, ...], list[tuple]], point: dict[str, Any],
          value: Any) -> tuple:
    """A point's place in its study's cases' order (models.md § 5.3), unit by unit of what is
    crossed (`crossed`): at its step's place in ``listed`` — each unit's steps as the study makes
    them, each value as a case holds it — or, at a step the study no longer makes, after those, by
    ``value`` of each of its values; one lacking an axis last."""
    out: list[tuple] = []
    for unit in units:
        held = tuple(point.get(a) for a in unit)
        if held in listed.get(unit, []):
            out.append((0, listed[unit].index(held)))
        elif all(a in point for a in unit):
            out.append((1, *map(value, held)))
        else:
            out.append((2,))
    return tuple(out)


def steps(units: list[tuple[str, ...]], made: list[dict[str, Any]]) -> dict[tuple[str, ...], list[tuple]]:
    """Each unit's steps, in the order ``made`` — the points the study makes, in its cases' order,
    each value as a case holds it — first holds them: what `place` reads a point's place from."""
    out: dict[tuple[str, ...], list[tuple]] = {unit: [] for unit in units}
    for point in made:
        for unit in units:
            held = tuple(point.get(a) for a in unit)
            if held not in out[unit]:
                out[unit].append(held)
    return out


@dataclass(frozen=True)
class Applied:
    """A point put in place: each constant an axis sets, in SI exactly; each part with its value;
    each dataset it names — and, once its computed values are at hand, every real definition's
    value at the point, and each computed definition whose value there is not (models.md § 3)."""

    constants: dict[str, Quantity]       # each definition written as its value that an axis sets
    parts: dict[str, BaseModel]          # each part a point changes, by its address, as loaded again
    datasets: dict[tuple[str, str], str]  # (group, property) -> the dataset the point names
    definitions: dict[str, Quantity] = field(default_factory=dict)   # every real definition's value here
    waits: frozenset[str] = frozenset()  # each computed definition not at hand here


def apply(c: Checking, study: Part, point: dict[str, Any]) -> Applied:
    """``point`` put in place: a definition's value replaced, in SI exactly — what is computed from
    it is computed by the definitions' program (models.md § 3); a part's value set and the part
    loaded again; a dataset named (models.md § 5.3)."""
    constants, parts, chosen = {}, {}, {}
    for key, value in point.items():
        found = target(c, study, key)
        if found.how == "definition":
            constants[found.address.path[-1]] = c.units.measure(value)
        elif found.how == "dataset":
            chosen[(found.address.path[-3], found.address.path[-1])] = value
        else:
            at = str(found.address.part)
            holder = Part(found.part.address, found.part.file, parts.get(at, found.part.data), found.part.folder)
            parts[at] = replaced(holder, found.address.path,
                                 value.model_dump() if isinstance(value, Measure) else value, {"units": c.units})
    return Applied(constants=constants, parts=parts, datasets=chosen)

