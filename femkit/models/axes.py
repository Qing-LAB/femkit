"""A study's axes (models.md § 5.1): each keyed by the address of what it varies (projects.md
§ 5) — a parameter of the project file, a value of the study's mesh recipe, one of its own
numerics, or the dataset a material of its component uses — with its values and one class; axes
of different classes crossed only with a `[crossing]` naming them all.

An axis's values are checked against what they vary, each value in its key's place alone: a
parameter's, read with every parameter computed again from it, in its dimension; a part's value
put in place and the part loaded again by its own schema — the numerics' and the recipe's alike —
and, for another part than the study, checked again by its own checks at that key; a dataset,
one its material holds. What the varied part finds wrong of its own — a file that does not load,
another key that does not read, a value it holds now that does not read — is its own finding,
never the axis's (models.md § 5.1). `apply` puts a point in place, for a case.

Its findings, each on the study:
- `bad-axis` (error), at `axes."<address>"`: an address that does not read, resolve, or name what
  an axis may vary — its right value, the address of what it may vary that the key most likely
  means, where one is close;
- `bad-axis-value` (error), at `axes."<address>".values`: a value its target refuses — for a
  dataset, the datasets its material holds its choices;
- `crossing-missing` (error), at `crossing`: axes of more than one class, and no `[crossing]`;
- `crossing-incomplete` (error), at `crossing.axes`: right, every axis's address.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterator

from pydantic import BaseModel

from femkit.core.errors import UsageError
from femkit.core.issues import Issue
from femkit.core.schema import QUANTITIES, DefinitionError, field_extras, key_path, validate
from femkit.core.units import Quantity, UnitError
from femkit.models.parts import ASSIGNMENT, DATASETS, contract, datasets, material, quantity_kind
from femkit.projects import checking
from femkit.projects.addresses import Address
from femkit.projects.checking import PARAMETER, Checking, resolve
from femkit.projects.door import Part
from femkit.projects.layout import held
from femkit.projects.names import nearest

NUMERICS = "numerics"   # the study's own table an axis may vary (models.md § 5.1)


@dataclass(frozen=True)
class Target:
    """What an axis varies: its address, the part holding it, how a point is put in place —
    `parameter`, `value` or `dataset` — what it holds now — None for a parameter that does not
    resolve now — and the `quantity` kind its schema writes it as (core.md § 2); None for a value
    no quantity."""

    address: Address
    part: Part
    how: str
    current: Any
    quantity: str | None = None


def text(value: Any) -> str:
    """A value as a quantity's text: a number written bare is its exact decimal."""
    return value if isinstance(value, str) else str(Fraction(value))


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
    parameters = layout.objects[PARAMETER]
    if address.part not in (Address(parameters.part, None), Address(refs["mesh"], data.mesh), study.address,
                            Address(refs["component"], data.component)):
        return _none(key)
    if part.data is None:
        return None
    if address.kind == parameters.part and path[:-1] == parameters.keys and path[-1] in _parameter_texts(c):
        return Target(address, part, "parameter", c.parameters.get(path[-1]), "any")
    if (address.part == Address(refs["mesh"], data.mesh) or (address.part == study.address and path[:1] == (NUMERICS,))) \
            and (now := _at(part.data, path)) is not None:
        return Target(address, part, "value", now, quantity_kind(type(part.data), path))
    assign = layout.objects[ASSIGNMENT]
    if address.part == Address(refs["component"], data.component) and len(path) == len(assign.keys) + 3 \
            and path[:len(assign.keys)] == assign.keys and path[-2] == DATASETS:
        return Target(address, part, "dataset", None)
    return _none(key)


def _none(key: str) -> str:
    return (f"`{key}` is none of what an axis varies: a parameter, a value of the study's mesh recipe, one of its "
            f"{NUMERICS}, or the dataset a material of its component uses")


def varied(c: Checking, study: Part) -> list[str]:
    """The address of everything an axis of ``study`` may vary now (models.md § 5.1): each
    parameter; each value of its recipe and of its numerics; the dataset of each property of each
    body's material, the project's own or the global library's, where it loads."""
    data, layout = study.data, c.opened.layout
    refs = {name: field_extras(f).get("ref") for name, f in type(data).model_fields.items()}
    parameters, assign = layout.objects[PARAMETER], layout.objects[ASSIGNMENT]
    found = [str(Address(parameters.part, None, (*parameters.keys, n))) for n in _parameter_texts(c)]
    recipe = c.opened.parts.get(str(Address(refs["mesh"], data.mesh)))
    for holder, root in ((recipe, ()), (study, (NUMERICS,))):
        if holder is not None and holder.data is not None:
            tree = holder.data.model_dump(mode="json", by_alias=True)
            found += [str(Address(holder.address.kind, holder.address.name, path))
                      for path in _leaves(_under(tree, root), root)]
    component = c.opened.parts.get(str(Address(refs["component"], data.component)))
    k = contract(c.opened, component) if component is not None else None
    for group, assigned in k.assign.items() if k else ():
        m = material(c.opened, assigned.material) if assigned.material else None
        found += [str(Address(component.address.kind, component.address.name, (*assign.keys, group, DATASETS, prop)))
                  for prop in (datasets(c, m) if m is not None else {})]
    return found


def _under(tree: Any, root: tuple[str, ...]) -> Any:
    for key in root:
        tree = tree.get(key) if isinstance(tree, dict) else None
    return tree


def _leaves(tree: Any, at: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Every key path of a value in ``tree`` that is no table or list, `schema` left out."""
    if isinstance(tree, dict):
        return [p for k, v in tree.items() if k != "schema" for p in _leaves(v, (*at, str(k)))]
    return [at] if at and tree is not None and not isinstance(tree, list) else []


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
    for key in path:
        data = held(data, key)
    return None if isinstance(data, (BaseModel, dict, list)) else data


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
    """Each axis's address and values, and the crossing of axes of different classes."""
    data = study.data
    for key, axis in data.axes.items():
        found = target(c, study, key)
        if found is None:
            continue                                        # its part does not load: its own finding says why
        if isinstance(found, str):
            near = address_meant(c, study, key)
            yield c.issue(study, "axes", key, code="bad-axis", right=near,
                          message=f"`{key}` is no address of what an axis may vary; did you mean `{near}`?" if near
                          else found)
            continue
        for value in axis.values:
            why = refused(c, study, found, value)
            if why is not None:
                yield c.issue(study, "axes", key, "values", code="bad-axis-value", label=text(value),
                              choices=_held_datasets(c, found) if found.how == "dataset" else (),
                              message=f"the axis `{key}` cannot take `{text(value)}`: {why}")
    classes = {axis.class_ for axis in data.axes.values()}
    if len(classes) > 1 and data.crossing is None:
        yield c.issue(study, "crossing", code="crossing-missing",
                      message=f"the axes are of {len(classes)} classes ({', '.join(sorted(classes))}), crossed with "
                              "no `[crossing]` saying why their full product is needed")
    elif data.crossing is not None and sorted(data.crossing.axes) != sorted(data.axes):
        yield c.issue(study, "crossing", "axes", code="crossing-incomplete", right=list(data.axes),
                      message="the crossing names every axis of the study, and nothing else")


def refused(c: Checking, study: Part, found: Target, value: Any) -> str | None:
    """Why ``found`` cannot take ``value`` in its key's place; None when it can, or when only what
    its part finds wrong of its own stands in the way — that part's own finding says why."""
    if found.how == "parameter":
        name = found.address.path[-1]
        resolved, circles, wrong = resolve({**_parameter_texts(c), name: text(value)}, c.units)
        if name in wrong:
            return wrong[name]
        if any(name in circle for circle in circles):
            return "the parameters would use each other in a circle"
        if name not in resolved or found.current is None:
            return None                                     # what it uses, or holds now, has its own finding
        return None if resolved[name].dimension == found.current.dimension else "it is not in the parameter's dimension"
    if found.how == "dataset":
        return _dataset(c, found, value)
    try:
        data = replaced(found.part, found.address.path, value, {"units": c.units})
    except DefinitionError as exc:
        return exc.summary()
    if found.part.address != study.address:                 # the study's own checks are the ones running
        changed = Part(found.part.address, found.part.file, data, found.part.folder)
        mine = _own(c, changed, found.address.path)
        if mine is not None:
            return mine
        if _own(c, found.part, found.address.path) is not None:
            return None                                     # what it holds now has its own finding, at that key
    kind = QUANTITIES.get(found.quantity) if found.quantity is not None else None
    if kind is None or kind.reads == "unit":
        return None
    read = c.quantity if kind.reads == "expression" else c.units.parse
    if kind.reads == "expression" and c.unresolved_in(text(value)):
        return None                                         # a parameter it uses has its own finding
    try:
        given = read(text(value))
    except UnitError as exc:
        return str(exc)
    try:
        now = read(text(found.current))
    except UnitError:
        return None                                         # what it holds now has its part's own finding
    return None if now.dimension == given.dimension else f"it is not in the dimension of {found.current!r}"


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


def _parameter_texts(c: Checking) -> dict[str, str]:
    table = c.opened.layout.objects[PARAMETER]
    project = c.opened.parts.get(c.opened.layout.project_kind)
    held_now = table.entries(project.data) if project is not None and project.data is not None else {}
    return {name: text(value) for name, value in held_now.items()}


def points(study: Part) -> list[dict[str, Any]]:
    """Every axis point (models.md § 5.1): every value of each axis with every value of the others,
    in the order the study writes them; one point of no axis when it has none."""
    axes = study.data.axes
    return [dict(zip(axes, values)) for values in itertools.product(*(a.values for a in axes.values()))]


@dataclass(frozen=True)
class Applied:
    """A point put in place: every parameter computed again, and each part with its value."""

    parameters: dict[str, Quantity]
    parts: dict[str, BaseModel]          # each part a point changes, by its address, as loaded again
    datasets: dict[tuple[str, str], str]  # (group, property) -> the dataset the point names


def apply(c: Checking, study: Part, point: dict[str, Any]) -> Applied:
    """``point`` put in place: a parameter's value replaced and every parameter computed again
    from it; a part's value set and the part loaded again; a dataset named (models.md § 5.3)."""
    texts, parts, chosen = _parameter_texts(c), {}, {}
    for key, value in point.items():
        found = target(c, study, key)
        if found.how == "parameter":
            texts[found.address.path[-1]] = text(value)
        elif found.how == "dataset":
            chosen[(found.address.path[-3], found.address.path[-1])] = value
        else:
            at = str(found.address.part)
            holder = Part(found.part.address, found.part.file, parts.get(at, found.part.data), found.part.folder)
            parts[at] = replaced(holder, found.address.path, value, {"units": c.units})
    return Applied(parameters=resolve(texts, c.units)[0], parts=parts, datasets=chosen)

