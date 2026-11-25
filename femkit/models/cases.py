"""Cases (models.md § 5.3): the component, the steps' physics, the materials' data, the mesh
recipe, the numerics and one axis point, each resolved, every quantity in its exact form and every
other number as its exact text. Each study's cases are its own, in its own folder,
`cases/<study>/<id>/case.json` (`path`), the ID the SHA-256 of the case's canonical JSON, by which
`study expand` of the same study knows a case it wrote already; nothing is shared or compared
between studies. `study expand` writes one for each point it lacks; it is refused while a part
the study uses does not load, or `project check` has a finding on one."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel, Field

from femkit.core import view
from femkit.core.errors import Refused, Unstated
from femkit.core.issues import Issue
from femkit.core.schema import QUANTITIES, DefinitionError, Model, field_extras, validate
from femkit.core.units import Quantity, UnitError, Units
from femkit.models import axes
from femkit.models.parts import Contract, called, contract, datasets, material, quantities
from femkit.models.requests import PROJECT_CHECK
from femkit.models.study import Study, cites, used
from femkit.projects import door, names
from femkit.projects.addresses import Address
from femkit.projects.checking import Checking
from femkit.projects.door import Part

CASES = "cases"            # the folder femkit writes the cases in (projects.md § 2)
CASE_FILE = "case.json"    # each case's file, in its folder named by its ID, in its study's folder
CASE = re.compile(rf"{CASES}/(?P<study>{names.NAME.pattern})/(?P<id>[0-9a-f]{{64}})/{re.escape(CASE_FILE)}")


def path(study: str, case: str) -> str:
    """Where a study's case is written, from the project's folder: `cases/<study>/<id>/case.json`
    (models.md § 5.3) — the one home of the form, which `written` reads back by `CASE`."""
    return f"{CASES}/{study}/{case}/{CASE_FILE}"


class Case(Model):
    """`cases/<study>/<id>/case.json` (models.md § 5.3): one resolved case of one study, every quantity
    `{"value": "<p/q>", "dimension": {"<base>": <power>}}` in its dimension's canonical units and
    every other number its exact text."""

    schema_: Literal[1] = Field(alias="schema", description="the shape this file is written in, raised when it "
                                                            "changes")
    component: dict[str, Any] = Field(description="the component: its frame, the values of the inputs its contract "
                                                  "declares, each of its files with its SHA-256 — its script's among "
                                                  "them — its promised groups, and each body's material with the "
                                                  "dataset of every property the steps' physics read")
    steps: dict[str, Any] = Field(description="each step by its name: its kind, its physics resolved — the meaning "
                                              "of the component's dimension alone — and what it takes")
    mesh: dict[str, Any] = Field(description="the mesh recipe, resolved, every default written")
    numerics: dict[str, Any] = Field(description="the numerics, every default written")
    point: dict[str, Any] = Field(description="each axis's address and its value")


# ------------------------------------------------------------------ the exact form

def exact(q: Quantity) -> dict:
    """A quantity as a case holds it: its exact value in canonical units, and its dimension."""
    return {"value": str(q.value), "dimension": dict(q.dimension)}


def plain(tree: Any) -> Any:
    """Every number in one form, its exact text: `-1`, `-1.0` and a degree of `2` alike."""
    if isinstance(tree, dict):
        return {k: plain(v) for k, v in tree.items()}
    if isinstance(tree, (list, tuple)):
        return [plain(v) for v in tree]
    if isinstance(tree, (int, Decimal, Fraction)) and not isinstance(tree, bool):
        return str(Fraction(tree))
    return tree


def canonical(data: dict) -> bytes:
    """The canonical JSON: keys sorted, no whitespace, UTF-8 (models.md § 5.3)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def case_id(data: dict) -> str:
    """A case's ID: the SHA-256 of its canonical JSON."""
    return hashlib.sha256(canonical(data)).hexdigest()


def content(value: Any, names: dict[str, Quantity], units: Units, where: Address) -> Any:
    """A part's value as a case holds it: every field, defaults too; each quantity its schema
    writes in its exact form — read with the case's parameters where its kind may be an
    expression of them, alone where it names none (core.md § 2) — a unit's text as written;
    every other number its exact text. A part's file shape is its own, never the case's."""
    if not isinstance(value, BaseModel):
        return plain(value)
    tree = plain(value.model_dump(mode="python", by_alias=True))
    for at, kind, given in quantities(value):
        if QUANTITIES[kind].reads == "unit":
            continue
        node = tree
        for key in at[:-1]:
            node = node[key]
        node[at[-1]] = exact(_read(given, names if QUANTITIES[kind].reads == "expression" else {}, units,
                                   Address(where.kind, where.name, tuple(map(str, at)))))
    if isinstance(tree, dict):
        tree.pop("schema", None)
    return tree


def _read(given: Any, names: dict[str, Quantity], units: Units, where: Address) -> Quantity:
    try:
        return units.parse(axes.text(given), names)
    except UnitError as exc:
        raise Refused(f"{where} does not read at this point: {exc}", code="bad-quantity", subject=str(where)) from None


# ------------------------------------------------------------------ one case

def build(c: Checking, study: Part, point: dict[str, Any]) -> dict:
    """The case ``study`` makes at ``point`` (models.md § 5.3), its axis point applied."""
    data: Study = study.data
    applied = axes.apply(c, study, point)
    names, units = applied.parameters, c.units
    holder = cites(c, "component", data.component)
    k = contract(c.opened, holder)
    steps, read = {}, []
    for name, step in data.steps.items():
        p = cites(c, "physics", step.physics, type(step))
        physics, f = p.data, c.formulations[p.data.formulation]
        read.append(f)
        resolved = content(physics, names, units, p.address)
        resolved["meaning"] = physics.meaning.get(str(k.dimension))
        steps[name] = {"kind": step.kind, "physics": resolved, "takes": dict(step.takes)}
    recipe = cites(c, "mesh", data.mesh)
    changed = applied.parts.get(str(study.address))
    return {
        "schema": 1,
        "component": _component(c, k, applied, sorted({p for f in read for p in f.properties})),
        "steps": steps,
        "mesh": content(applied.parts.get(str(recipe.address), recipe.data), names, units, recipe.address),
        "numerics": content((changed or data).numerics, names, units, study.address),
        "point": {key: _value(c, study, key, value, applied) for key, value in point.items()},
    }


def _value(c: Checking, study: Part, key: str, value: Any, applied: axes.Applied) -> Any:
    """An axis's value as a case holds it: a quantity in its exact form, read with every
    parameter computed again; a name or a number as its exact text."""
    found = axes.target(c, study, key)
    if found.how == "parameter":
        return exact(applied.parameters[found.address.path[-1]])
    kind = QUANTITIES.get(found.quantity) if found.quantity is not None else None
    if kind is not None and kind.reads != "unit":
        return exact(_read(value, applied.parameters if kind.reads == "expression" else {}, c.units, found.address))
    return plain(value)


def _component(c: Checking, k: Contract, applied: axes.Applied, needed: list[str]) -> dict:
    """The component as a case holds it: its frame, its inputs' values, its files' digests, its
    groups, and each body's material with the dataset of every property the physics read
    (materials.md § 6) — a dataset its assignment leaves to choose among several is unstated."""
    where = k.part.address
    inputs = {}
    for name in k.inputs:
        if name not in applied.parameters:
            raise Unstated(f"{where} reads the parameter {name}, which does not resolve at this point",
                           code="parameter-unresolved", subject=f"{where}:inputs.parameters.{name}")
        inputs[name] = exact(applied.parameters[name])
    assign = {}
    for group, assigned in k.assign.items():
        held = material(c.opened, assigned.material) if assigned.material else None
        if held is None:
            raise Unstated(f"the material `{assigned.material}` of `{group}` is not the project's own, and the global "
                           "material library is not read yet", code="material-unread",
                           subject=f"{where}:assign.{group}.material")
        sets, properties = datasets(c.opened, held), {}
        for prop in needed:
            named = sets.get(prop, {})
            chosen = applied.datasets.get((group, prop)) or assigned.datasets.get(prop) or (
                next(iter(named)) if len(named) == 1 else None)
            if chosen not in named:
                raise Unstated(f"{group}'s material {assigned.material} holds {', '.join(named) or 'no dataset'} for "
                               f"{prop}, and the assignment names none of them", code="dataset-unstated",
                               subject=f"{where}:assign.{group}.datasets.{prop}")
            properties[prop] = {"dataset": chosen, "data": content(named[chosen], applied.parameters, c.units,
                                                                   held.address)}
        assign[group] = {"material": assigned.material, "properties": properties}
    return {"frame": content(k.frame, applied.parameters, c.units, where), "inputs": inputs,
            "files": {h.name: h.sha256 for h in c.opened.held_by(where).values()},
            "groups": {g: str(d) for g, d in k.groups.items()}, "assign": assign}


# ------------------------------------------------------------------ a study's cases

@dataclass(frozen=True)
class Expanded:
    """One case a study makes: its ID, its point as the study writes it, and its content."""

    id: str
    point: dict[str, Any]
    data: dict


def expand(c: Checking, study: Part, issues: list[Issue]) -> list[Expanded]:
    """Every case ``study`` makes, one per axis point — two spellings of one point are one case
    (models.md § 5.3). Refused, naming the part, while a part the study uses does not load or has
    a finding that is an error; and while the project file does not name the study or its
    component: inert, never expanded (projects.md § 3)."""
    again = (view.command(PROJECT_CHECK, project=c.opened.project.name),)
    parts = {str(p.address): p for _, p in [((), study), *used(c, study)]}
    unloaded = [p for p in parts.values() if p.data is None]
    if unloaded:
        raise Refused(f"{called(unloaded[0].address)} does not load", again, code="unloadable",
                      subject=str(unloaded[0].address))
    errors = [i for i in issues if i.severity == "error" and (o := c.opened.owner(i.subject)) is not None
              and str(o.address) in parts]
    if errors:
        first = c.opened.owner(errors[0].subject)
        more = f"; {len(errors)} in all on the parts the study uses" if len(errors) > 1 else ""
        raise Refused(f"{called(first.address)} has a finding to resolve: {errors[0].message}{more}", again,
                      code="has-findings", subject=str(first.address))
    project = c.opened.parts[c.opened.layout.project_kind].data
    component = field_extras(Study.model_fields["component"])["ref"]
    for kind, name, named in ((study.address.kind, study.address.name, project.studies),
                              (component, study.data.component, project.components)):
        if name not in named:
            raise Refused(f"the project file does not name the {kind} {name}: it is inert, never expanded into a case",
                          again, code="not-named", subject=str(Address(kind, name)))
    made: dict[str, Expanded] = {}
    for point in axes.points(study):
        data = build(c, study, point)
        made.setdefault(case_id(data), Expanded(case_id(data), point, data))
    return list(made.values())


# ------------------------------------------------------------------ the cases written

def written(opened: door.Opened) -> dict[str, dict[str, Case | str]]:
    """Every case written in the project, by its study, then by its ID: its `case.json` as loaded,
    or why it does not load."""
    found: dict[str, dict[str, Case | str]] = {}
    for f in opened.files:
        if match := CASE.fullmatch(f):
            text = door.read_output(opened, f)
            held = found.setdefault(match["study"], {})
            try:
                held[match["id"]] = read(text, f)
            except DefinitionError as exc:
                held[match["id"]] = exc.summary()
    return found


def read(text: str | None, file: str) -> Case:
    """A case's file read by its schema; one that is no JSON, or not there, does not load."""
    try:
        data = json.loads(text) if text is not None else None
    except json.JSONDecodeError as exc:
        raise DefinitionError(file, [("", f"not JSON: {exc}")]) from None
    if data is None:
        raise DefinitionError(file, [("", "there is no such file")])
    return validate(Case, data, file)


def write(opened: door.Opened, study: str, case: Expanded) -> None:
    """``case``'s `case.json`, in its folder named by its ID, in its study's."""
    door.write_output(opened, path(study, case.id), case.data)


def shown(value: Any, units: Units) -> str:
    """A value a case holds, for a person: a quantity in its canonical units, `1/10 m`."""
    if isinstance(value, dict) and set(value) == {"value", "dimension"}:
        unit = " ".join((units.canonical(((n, 1),)) or n) + ("" if p == 1 else f"^{p}")
                        for n, p in value["dimension"].items())
        return f"{value['value']} {unit}".strip()
    return str(value)
