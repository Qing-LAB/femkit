"""Cases (models.md § 5.3): the component, the steps' physics, the materials' data, the mesh
recipe, the numerics and one axis point, each resolved, every quantity in its exact form and every
other number as its exact text. Each study's cases are its own, in its own folder,
`cases/<study>/<id>/case.json`, where the door forms it, the ID the SHA-256 of the case's canonical
JSON, by which `study prep` of the same study knows a case it wrote already; nothing is shared or
compared between studies. `study prep` writes one for each point it lacks; it is refused while a
part the study uses does not load, or `project check` has a finding on one.

`case.json` is a typed model, `Case`: its component, steps, mesh, numerics and point each a model
of its own, which its writer (`build`) and every reader — the workflow's, a stage's `stage.json`,
the reference page — read by its fields, never as a table by its keys' names. A part's value in a
case is the model of it in a case (`in_case`), derived from the part's own schema, so each of its
fields is declared once, there: every quantity an `Exact`, every other number its exact text,
every field written.

What `study prep`'s first two steps decide is here, each a function of its own, which `makes`
runs in one for every other reader — the cases a study makes now (workflow.md § 7): its
definitions step — the study ready to make cases (`ready`) and every value resolved and validated
at every point of its sweep, the computed definitions computed (`values`, models.md § 3) — and its
cases step, each case built from them (`made`), with the words its plan says each case it writes in
(`described`). Every other reader takes a computed value as `study prep` keeps it, where it is kept
in sync: a case resting on one not at hand at its point waits for `study prep` (`Waits`), said in
one finding (`waiting`), never made from a value used silently.

A case holds each body's material by its name in its library, never `GLOBAL/`, and the data of
each dataset it used, never where it was found (materials.md § 6): a case written before a
material's data changed is told by comparing what it holds with what its material holds now
(`held_now`, `now`) — shown by `case list`, and by the plan of `study prep` for each case it
writes in its place (`renewed`)."""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model

from femkit.core import persist, view
from femkit.core.errors import Refused, Unstated
from femkit.core.issues import Issue
from femkit.core.schema import QUANTITIES, Measure, Model, field_extras, key_path, names_in
from femkit.core.units import Quantity, UnitError, Units, decimal
from femkit.geometry.component import Frame
from femkit.geometry.recipe import Recipe
from femkit.materials.material import FORMS
from femkit.models import axes
from femkit.models import definitions as defined
from femkit.models.parts import (PROPERTY, Contract, Parameterized, called, contract, datasets, material,
                                 quantities, table)
from femkit.models.physics import Physics
from femkit.projects.requests import PROJECT_CHECK
from femkit.models.study import Numerics, Step, Study, cites, used
from femkit.projects import door, names
from femkit.projects import state as part_state
from femkit.projects.addresses import Address
from femkit.projects.checking import DEFINITION, Checking
from femkit.projects.door import Part
from femkit.projects.schemas import PartFile


# ------------------------------------------------------------------ the exact form

class Exact(Model):
    """A quantity as a case holds it (models.md § 5.3): its exact value in its dimension's
    canonical units, and that dimension (core.md § 11), so two spellings of one value are one."""

    value: str = Field(description="its exact value in its dimension's canonical units: a whole number, or `p/q`")
    dimension: dict[str, int] = Field(description="its dimension: each base quantity by its name, with its power; "
                                                  "none for a plain number")


def exact(q: Quantity | list) -> Exact | list:
    """A quantity as a case holds it: its exact value in canonical units, and its dimension — each
    of a point's, a line's or a range's, a list of them."""
    if isinstance(q, list):
        return [exact(each) for each in q]
    return Exact(value=str(q.value), dimension=dict(q.dimension))


def quantity(held: Any) -> Quantity | None:
    """A value as a case holds it, read back (models.md § 5.3): an `Exact`, as the exact quantity it
    is in canonical units; None for any other value — a number's exact text, a name. The one reader
    of a case's quantities, the inverse of `exact`."""
    if not isinstance(held, Exact):
        return None
    return Quantity(Fraction(held.value), tuple(sorted(held.dimension.items())))


def plain(tree: Any) -> Any:
    """Every number in one form, its exact text: `-1`, `-1.0` and a degree of `2` alike."""
    if isinstance(tree, dict):
        return {k: plain(v) for k, v in tree.items()}
    if isinstance(tree, (list, tuple)):
        return [plain(v) for v in tree]
    if isinstance(tree, (int, Decimal, Fraction)) and not isinstance(tree, bool):
        return str(Fraction(tree))
    return tree


# ------------------------------------------------------------------ a part's value in a case

class _Parameters(Model):
    """A model in a case whose keys beyond its fields are the parameters its kind lists, each an
    `Exact` (`Parameterized`)."""

    model_config = ConfigDict(extra="allow", frozen=True)
    __pydantic_extra__: dict[str, Exact] = Field(init=False)


#: Each part's model in a case, by the part's model: one each (`in_case`).
_IN_CASE: dict[type[BaseModel], type[Model]] = {}

#: What a field of a part keeps in its model in a case, beside its description: where it is
#: documented, and what it names (core.md § 2).
_KEPT = ("doc", "ref")


def in_case(model: type[BaseModel], **fields: Any) -> type[Model]:
    """The model of a part's value as a case holds it (`content`; models.md § 5.3), named
    `Case<its name>`, derived from the part's own, so every field it holds is declared there alone:
    each field but its file's shape (`PartFile`), required, since a case writes every default; a
    quantity of a kind read as one (`QUANTITIES`) an `Exact` — a range's a list of them — beside
    any closed value the field allows; every other number its exact text; a model, its own model in
    a case; a table's values and a list's items, theirs; each parameter a
    declaration lists for its kind (`Parameterized`), an `Exact`. Its fields keep their
    descriptions, their `doc` and their `ref`. ``fields``, each `(annotation, Field(...))`, are the
    fields a case states in place of the part's — a physics' `meaning`, for the case's frame
    alone — given where the model in a case is declared, once: one model in a case per part's."""
    if model in _IN_CASE:
        if fields:
            raise TypeError(f"the model of {model.__name__} in a case is declared already")
        return _IN_CASE[model]
    own = PartFile.model_fields if issubclass(model, PartFile) else {}
    made: dict[str, Any] = {}
    for name, f in model.model_fields.items():
        if name in own:
            continue
        kind = field_extras(f).get("quantity")
        kept = {k: v for k, v in field_extras(f).items() if k in _KEPT}
        made[name] = (_in_case(f.annotation, kind is not None and QUANTITIES[kind].reads == "quantity"),
                      Field(alias=f.alias, description=f.description, json_schema_extra=kept or None))
    listed = issubclass(model, Parameterized)
    doc = " ".join((model.__doc__ or "").split())
    _IN_CASE[model] = create_model(
        f"Case{model.__name__}", __base__=_Parameters if listed else Model, __module__=__name__,
        **{**made, **fields},
        __doc__=f"{doc} As a case holds it (models.md § 5.3): every quantity exact, every other number its exact "
                "text, every field written" + ("; each key beyond its fields a parameter its kind lists, an "
                                               "`Exact`." if listed else "."))
    return _IN_CASE[model]


def _in_case(annotation: Any, measured: bool) -> Any:
    """What a value of ``annotation`` is in a case (`in_case`), ``measured`` where its field is a
    quantity read as one."""
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Annotated:
        return _in_case(args[0], measured)
    if origin in (typing.Union, types.UnionType):
        return Union[tuple(dict.fromkeys(_in_case(a, measured) for a in args))]
    if origin is typing.Literal:
        return Literal[tuple(dict.fromkeys(plain(v) for v in args))]
    if origin is dict:
        return dict[args[0], _in_case(args[1], measured)]
    if origin in (list, tuple):
        return list[_in_case(args[0], measured)]
    if annotation is type(None):
        return annotation
    if measured:
        return _measured(annotation.__pydantic_generic_metadata__["args"][0]) \
            if isinstance(annotation, type) and issubclass(annotation, Measure) else Exact
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return in_case(annotation)
    return str if annotation in (int, Decimal, Fraction) else annotation


def _measured(value: Any) -> Any:
    """What a `{value, unit}` of numbers ``value`` is in a case: an `Exact`; for a list of them — a
    range — a list of those."""
    return list[_measured(typing.get_args(value)[0])] if typing.get_origin(value) is list else Exact


#: The models in a case of the parts a case holds (models.md § 5.3): the component's frame, the mesh
#: recipe, the numerics, a step and its physics, and each form of a dataset.
CaseFrame = in_case(Frame)
CaseRecipe = in_case(Recipe)
CaseNumerics = in_case(Numerics)
CasePhysics = in_case(Physics, meaning=(str | None, Field(
    description="what the component's dimension means for its formulation, as the physics states it for that "
                "dimension alone; none where it states none", json_schema_extra={"doc": "models.md § 3"})))
CaseStep = in_case(Step, physics=(CasePhysics, Field(
    description="the physics it solves, resolved: every condition's and source's parameters exact")))
CaseData = Union[tuple(in_case(form) for form in FORMS.values())]


class Drawing(Model):
    """The component as its geometry script draws it, in a case (models.md § 5.3): all of the
    case's component but its assignment — what a geometry stage is made from of it (workflow.md
    § 4)."""

    frame: CaseFrame = Field(description="its frame: its dimension and its unit, and, for an axisymmetric physics, "
                                         "the axis it is revolved about", json_schema_extra={"doc": "geometry.md § 3"})
    inputs: dict[str, Exact] = Field(description="the value of each definition its contract declares the script "
                                                 "reads, by the definition's name")
    files: dict[str, str] = Field(description="each of its files — its script's among them — by its name, with its "
                                              "SHA-256")
    groups: dict[str, str] = Field(description="each group it promises, with its dimension")


class CaseDataset(Model):
    """One property's dataset in a case (materials.md § 6): its name in its material, and its data,
    worked out for the case — never where it was found."""

    dataset: str = Field(description="the dataset, by its name in its material")
    data: CaseData = Field(description="its data: a value, a table or a dispersion model, every quantity exact",
                           json_schema_extra={"doc": "materials.md § 3"})


class CaseAssignment(Model):
    """One body's material in a case (materials.md §§ 4, 6): by its name in its library, never
    `GLOBAL/`, so one material written either way is one case, with the dataset of every property
    the steps' physics read."""

    material: str = Field(description="the material, by its name in its library")
    properties: dict[str, CaseDataset] = Field(description="each property the steps' physics read, by its name in "
                                                           "the property list: the dataset the case uses")


class CaseComponent(Drawing):
    """The component in a case (models.md § 5.3): its frame, the values of the inputs its contract
    declares, each of its files with its SHA-256 — its script's among them — its promised groups,
    and each body's material with the dataset of every property the steps' physics read."""

    assign: dict[str, CaseAssignment] = Field(description="each body group's material, by the group")

    def drawing(self) -> Drawing:
        """All of it but its assignment, as its script draws it (`Drawing`)."""
        return Drawing(**{name: getattr(self, name) for name in Drawing.model_fields})


#: The shape `case.json` is written in (models.md § 2): raised when a step's `takes` became
#: `takes_from` and the recipe held its mesher, so a case of the first shape reads as one whose file
#: does not load, never as one of this.
SHAPE = 2


class Case(Model):
    """`cases/<study>/<id>/case.json` (models.md § 5.3): one resolved case of one study, every quantity
    `{"value": "<p/q>", "dimension": {"<base>": <power>}}` in its dimension's canonical units and
    every other number its exact text."""

    schema_: Literal[SHAPE] = Field(alias="schema", description="the shape this file is written in, raised when it "
                                                                "changes")
    component: CaseComponent = Field(description="the component: what its script draws, and each body's material")
    steps: dict[str, CaseStep] = Field(description="each step by its name: its kind, its physics resolved — the "
                                                   "meaning of the component's dimension alone — and what it takes")
    mesh: CaseRecipe = Field(description="the mesh recipe, resolved, every default written",
                             json_schema_extra={"doc": "geometry.md § 6"})
    numerics: CaseNumerics = Field(description="the numerics, every default written")
    point: dict[str, Exact | str] = Field(description="each axis's address and its value: a quantity exact; a "
                                                      "dataset's name, or a plain number's exact text, as itself")


def case_id(case: Case) -> str:
    """A case's ID: the SHA-256 of its canonical JSON — keys sorted, no whitespace, UTF-8
    (models.md § 5.3)."""
    return persist.canonical_sha256(_json(case))


#: How many hexadecimal digits of an ID a person reads where the whole would crowd a line (`short`).
SHORT = 12


def short(id: str) -> str:
    """An ID — a case's, or a stage's, each a SHA-256 — as a person reads it where the whole would
    crowd a line: a table's cell, a box's label, a plan's step: its first `SHORT` hexadecimal
    digits (models.md § 5.3)."""
    return id[:SHORT]


def _json(case: Case) -> dict:
    """``case`` as its file holds it."""
    return case.model_dump(mode="json", by_alias=True)


class Waits(Exception):
    """A case's value resting on computed definitions whose values are not at hand at its point —
    not kept in sync (models.md § 3): their names."""

    def __init__(self, names: Any):
        super().__init__(", ".join(names))
        self.names = tuple(names)


def content(value: BaseModel, names: dict[str, Quantity], units: Units, where: Address,
            waits: frozenset[str] = frozenset(), **stated: Any) -> Model:
    """A part's value as a case holds it, its model in a case (`in_case`): every field, defaults
    too; each quantity its schema writes in its exact form — read with the case's definitions
    where its kind may cite one, alone where it names none (core.md §§ 2, 11) — a unit's text as
    written; every other number its exact text; ``stated``, the fields its model in a case states
    in place of the part's. A part's file shape is its own, never the case's. One naming a
    definition of ``waits`` is not made: `Waits`, naming it."""
    tree = plain(value.model_dump(mode="python", by_alias=True))
    for at, kind, written in quantities(value):
        if QUANTITIES[kind].reads == "unit":
            continue
        node = tree
        for key in at[:-1]:
            node = node[key]
        node[at[-1]] = exact(_read(written, names if QUANTITIES[kind].cites else None, units,
                                   Address(where.kind, where.name, tuple(map(str, at))), waits))
    for name, f in (PartFile.model_fields.items() if isinstance(value, PartFile) else ()):
        tree.pop(f.alias or name)
    return in_case(type(value)).model_validate({**tree, **stated})


def _read(given: Any, names: dict[str, Quantity] | None, units: Units, where: Address,
          waits: frozenset[str] = frozenset()) -> Any:
    """A value written in the one quantity form, exactly, by the units' one reader — with
    ``names``, a definition's name, alone or among its numbers; one naming a definition of
    ``waits``, `Waits`."""
    waiting = [n for n in names_in(given) if n in waits] if names is not None else []
    if waiting:
        raise Waits(waiting)
    try:
        return units.measure(given, names)
    except UnitError as exc:
        raise Refused(f"{where} does not read at this point: {exc}", code="bad-quantity", subject=str(where)) from None


# ------------------------------------------------------------------ one case

def build(c: Checking, study: Part, point: dict[str, Any], applied: axes.Applied) -> Case:
    """The case ``study`` makes at ``point`` (models.md § 5.3), its axis point applied, every
    value resolved at it, ``applied``; `Waits` where a value rests on a computed definition not at
    hand there."""
    data: Study = study.data
    names, units, waits = applied.definitions, c.units, applied.waits
    holder = cites(c, "component", data.component)
    k = contract(c.opened, holder)
    steps, read = {}, []
    for name, step in data.steps.items():
        p = cites(c, "physics", step.physics, type(step))
        physics, f = p.data, c.formulations[p.data.formulation]
        read.append(f)
        steps[name] = content(step, names, units, study.address, waits, physics=content(
            physics, names, units, p.address, waits, meaning=physics.meaning.get(str(k.dimension))))
    recipe = cites(c, "mesh", data.mesh)
    changed = applied.parts.get(str(study.address))
    return Case(schema=SHAPE, component=_component(c, k, applied, sorted({p for f in read for p in f.properties})),
                steps=steps,
                mesh=content(applied.parts.get(str(recipe.address), recipe.data), names, units, recipe.address, waits),
                numerics=content((changed or data).numerics, names, units, study.address, waits),
                point={key: _value(c, study, key, value, applied) for key, value in point.items()})


def _value(c: Checking, study: Part, key: str, value: Any, applied: axes.Applied) -> Exact | str:
    """An axis's value as a case holds it: a quantity in its exact form — a definition's in SI,
    exactly; a name or a number as its exact text."""
    found = axes.target(c, study, key)
    if found.how == "definition":
        return exact(applied.definitions[found.address.path[-1]])
    kind = QUANTITIES.get(found.quantity) if found.quantity is not None else None
    if kind is not None and kind.reads != "unit":
        return exact(_read(value, None, c.units, found.address, applied.waits))
    return plain(value)


def _component(c: Checking, k: Contract, applied: axes.Applied, needed: list[str]) -> CaseComponent:
    """The component as a case holds it: its frame, its inputs' values, its files' digests, its
    groups, and each body's material — the project's own, or the global library's, as its name
    finds it (materials.md § 4) — by its name in its library, never `GLOBAL/`, so one material
    written either way is one case, with the dataset of every property the physics read (§ 6),
    never where it was found; a dataset its assignment leaves to choose among several is
    unstated. A material found nowhere, or that does not load, has refused the cases already:
    the component's finding, or its own (`makes`); one held under an equivalent form is
    refused, `Refused`, until a case converts it (plan § 4, M9) — `project check` has said so at
    the assignment (`study.py`)."""
    where = k.part.address
    inputs = {}
    for name in k.inputs:
        if name in applied.waits:
            raise Waits([name])
        if name not in applied.definitions:
            raise Unstated(f"{where} reads the definition {name}, whose value is not at hand at this point",
                           code="definition-unresolved", subject=f"{where}:inputs.definitions.{name}")
        inputs[name] = exact(applied.definitions[name])
    assign = {}
    for group, assigned in k.assign.items():
        held = material(c.opened, assigned.material)
        sets, properties = datasets(c, held), {}
        for prop in needed:
            named = sets.get(prop, {})
            chosen = applied.datasets.get((group, prop)) or assigned.datasets.get(prop) or (
                next(iter(named)) if len(named) == 1 else None)
            if chosen not in named:
                raise Unstated(f"{group}'s material {assigned.material} holds {', '.join(named) or 'no dataset'} for "
                               f"{prop}, and the assignment names none of them", code="dataset-unstated",
                               subject=f"{where}:assign.{group}.datasets.{prop}")
            if named[chosen].form != prop:
                raise Refused(f"{group}'s dataset {chosen} is held as {named[chosen].form}, a form of the {prop} read, "
                              f"and no case converts one yet: a dataset held as the {prop} itself would do",
                              code="form-unconverted", subject=f"{where}:assign.{group}.datasets.{prop}")
            properties[prop] = CaseDataset(dataset=chosen, data=content(named[chosen].data, applied.definitions,
                                                                        c.units, held.address))
        assign[group] = CaseAssignment(material=names.bare(held.address.name), properties=properties)
    return CaseComponent(frame=content(k.frame, applied.definitions, c.units, where), inputs=inputs,
                         files={h.name: h.sha256 for h in c.opened.held_by(where).values()},
                         groups={g: str(d) for g, d in k.groups.items()}, assign=assign)


# ------------------------------------------------------------------ a study's cases

@dataclass(frozen=True)
class MadeCase:
    """One case a study makes: its ID, its point as the study writes it, and the case."""

    id: str
    point: dict[str, Any]
    case: Case


@dataclass(frozen=True)
class Valued:
    """One point of a study's sweep, as the study writes it, and every value resolved at it."""

    point: dict[str, Any]
    applied: axes.Applied


def makes(c: Checking, study: Part, issues: list[Issue], source: defined.Values
          ) -> tuple[list[MadeCase], list[Valued]]:
    """Every case ``study`` makes, one per axis point — two spellings of one point are one case
    (models.md § 5.3) — as `study prep`'s first two steps decide them (`ready`, `values`,
    `made`), the computed definitions taken from ``source``; refused as they refuse. Beside them,
    each point whose case waits for a computed value not at hand there."""
    ready(c, study, issues)
    return made(c, study, values(c, study, source))


def readable(c: Checking, study: Part) -> Part:
    """``study``, loaded; refused, `unloadable`, where its file does not load (`door.loaded`), its
    next step `project check`."""
    return door.loaded(c.opened, study, (view.command(PROJECT_CHECK, project=c.opened.project.name),))


def _findings(c: Checking, study: Part, errors: list[Issue], again: tuple[view.Action, ...]) -> None:
    """Refused, `has-findings`, naming the part the first of ``errors`` counts for, while any stands —
    every finding it rests on carried, shown before its sentence (core.md § 9)."""
    if errors:
        first = c.opened.owner(errors[0].subject)
        raise Refused(f"the parts {called(study.address)} uses have findings to resolve", again,
                      code="has-findings", subject=str(first.address), issues=errors)


def ready(c: Checking, study: Part, issues: list[Issue]) -> None:
    """Refused, naming the part, while a part ``study`` uses does not load or has an error on it —
    its state `errors`, by the one predicate (`projects.state.errors`); a warning or a note stops
    nothing — and while the
    project file does not name the study or its component: inert, never made into a case
    (models.md § 5.3; projects.md §§ 3, 8)."""
    again = (view.command(PROJECT_CHECK, project=c.opened.project.name),)
    rests = [study, *(p for _, p in used(c, study))]
    parts = {str(p.address): p for p in rests}
    for _, p in used(c, study):
        door.loaded(c.opened, p, again)
    counted = {id(i) for p in parts.values() for i in part_state.errors(c.opened, p, issues)}
    _findings(c, study, [i for i in issues if id(i) in counted], again)
    project = c.opened.parts[c.opened.layout.project_kind].data
    component = field_extras(Study.model_fields["component"])["ref"]
    for kind, name, named in ((study.address.kind, study.address.name, project.studies),
                              (component, study.data.component, project.components)):
        if name not in named:
            raise Refused(f"the project file does not name the {kind} {name}: it is inert, `study prep` makes no case of it",
                          again, code="not-named", subject=str(Address(kind, name)))


def values(c: Checking, study: Part, source: defined.Values) -> list[Valued]:
    """Every point of ``study``'s sweep, in its order, with every value resolved at it — the
    constants an axis sets put in place, and each computed definition as ``source`` gives it for
    that set of constants, computed in `model_prep` or as kept (models.md § 3) — what `study
    prep`'s definitions step decides (workflow.md § 7). A computed definition ``source`` holds
    no value of at a point waits there."""
    d = source.d
    points = axes.points(study)
    applied = [axes.apply(c, study, point) for point in points]
    computed = source.at([d.constants(a.constants) for a in applied])
    out = []
    for point, a, got in zip(points, applied, computed):
        known = {**d.exact, **a.constants, **(defined.quantities(d, got) if got is not None else {})}
        out.append(Valued(point, replace(a, definitions=known, waits=frozenset(d.order) if got is None
                                         else frozenset())))
    return out


def made(c: Checking, study: Part, valued: list[Valued]) -> tuple[list[MadeCase], list[Valued]]:
    """Every case ``study`` makes, one per point of ``valued`` — two spellings of one point are one
    case (models.md § 5.3) — what `study prep`'s cases step decides (workflow.md § 7); and each
    point whose case rests on a computed definition not at hand there, which waits."""
    found: dict[str, MadeCase] = {}
    waiting: list[Valued] = []
    for v in valued:
        try:
            case = build(c, study, v.point, v.applied)
        except Waits as exc:
            waiting.append(replace(v, applied=replace(v.applied, waits=frozenset(exc.names))))
            continue
        found.setdefault(case_id(case), MadeCase(case_id(case), v.point, case))
    return list(found.values()), waiting


def waiting(c: Checking, study: Part, waits: list[Valued]) -> Issue | None:
    """What the cases of ``study`` that wait say (models.md § 3; workflow.md § 3): one finding,
    `not-kept`, at the first computed definition they rest on, naming how many points wait and
    on what — their values computed and kept by `study prep`; none where none waits."""
    if not waits:
        return None
    names = sorted({n for v in waits for n in v.applied.waits})
    kind = c.opened.layout.project_kind
    keys = c.opened.layout.objects[DEFINITION].keys
    return door.finding(c.opened, Address(kind, None, (*keys, names[0])), code="not-kept", severity="info",
                        message=f"the cases of {called(study.address)} at {len(waits)} "
                                f"{'point' if len(waits) == 1 else 'points'} rest on "
                                f"{', '.join(f'`{n}`' for n in names)}, computed by definitions.py, whose values "
                                "`study prep` has not kept for them: their stages are not formed until `study prep` "
                                "computes them")


# ------------------------------------------------------------------ the cases written

def written(opened: door.Opened) -> dict[str, dict[str, Case | str]]:
    """Every case written in the project, by its study, then by its ID: its `case.json` as loaded,
    or why it does not load."""
    found: dict[str, dict[str, Case | str]] = {}
    for study, held in door.cases(opened).items():
        for case, f in held.items():
            got = door.read_record(opened, f, Case)      # the one reader of a file femkit writes (core.md § 4)
            found.setdefault(study, {})[case] = got.value if got.reads else got.problem or "there is no such file"
    return found


def write(opened: door.Opened, study: str, made: MadeCase) -> None:
    """``made``'s `case.json`, in its folder named by its ID, in its study's."""
    door.write_output(opened, door.case_file(opened, study, made.id), _json(made.case))


def at_point(point: dict[str, Any]) -> str:
    """Every value of a case's point, as the study writes it — `mesh:uniform:size = 0.1 m` — or, for
    a study with no axis, `the one case` (workflow.md § 7)."""
    return ", ".join(f"{k} = {as_written(v)}" for k, v in point.items()) or "the one case"


def as_written(value: Any) -> str:
    """An axis value as the study writes it: a number its exact decimal, with its axis's unit where
    it states one — `0.1 m` — a dataset's name as itself."""
    return axes.written(value)


def now(c: Checking, part: Part | None, written: dict[str, Case | str], making: set[str]
        ) -> dict[str, tuple[list[Filled], str]]:
    """Each case of a study written and loading: each body's material and dataset as the case holds
    them, where its material is found now — the global library's read where the project no longer
    names it — and, for one ``making`` lacks, how its data differs from what the material holds
    now; and the ID the case would have with that data (`held_now`; materials.md §§ 4, 6)."""
    loaded = {i: case for i, case in written.items() if not isinstance(case, str)}
    door.load_library(c.opened, c.opened.layout.objects[PROPERTY].part,
                      {names.bare(f.material) for case in loaded.values() for f in case.component.assign.values()},
                      c.units)
    out = {}
    for i, case in loaded.items():
        filled, renewed_as = held_now(c, part, case)
        out[i] = ([f if i not in making else replace(f, differs=()) for f in filled],
                  renewed_as if i not in making else i)
    return out


def renewed(c: Checking, part: Part, written: dict[str, Case | str], making: set[str]
            ) -> dict[str, tuple[str, list[Filled]]]:
    """Each case ``part`` makes now and has not written that takes the place of a case written
    before its materials' data changed (materials.md § 6), by its ID: the case it takes the place
    of, and each body's data as that case holds it, with how it differs now."""
    return {new: (old, filled) for old, (filled, new) in now(c, part, written, making).items()
            if new != old and new in making and new not in written}


def described(opened: door.Opened, study: str, case: MadeCase, renewing: dict[str, tuple[str, list[Filled]]]) -> str:
    """What `study prep`'s plan says of a case it writes (workflow.md § 7): its file and every value
    of its point, as the study writes it — and, where it takes the place of a case written before
    its materials' data changed, that case, and how each dataset's data changed (materials.md
    § 6)."""
    file = door.case_file(opened, study, case.id).replace(case.id, short(case.id) + '…')
    said = f"write {file}: {at_point(case.point)}"
    if case.id not in renewing:
        return said
    old, filled = renewing[case.id]
    return (f"{said} — in place of {short(old)}…, its materials' data changed: "
            + "; ".join(f"{f.group}'s {f.material}, dataset {f.dataset}: {', '.join(map(str, f.differs))}"
                        for f in filled if f.differs))


class DataChange(Model):
    """One way a dataset's data in a case differs from what its material holds now (materials.md
    § 6), each value as a person reads it: `value`, `1`, `1.0006`."""

    key: str = Field(description="the dataset's key where it differs, its dotted path; empty for the dataset as a "
                                 "whole")
    case: str = Field(description="the value there as the case holds it")
    now: str = Field(description="the value there as the material holds it now; for the dataset as a whole, why "
                                 "there is none to compare")

    def __str__(self) -> str:
        return f"{self.key} {self.case} → {self.now}" if self.key else self.now


@dataclass(frozen=True)
class Filled:
    """One property of one body's material, as a case holds it (materials.md §§ 4, 6): the body
    group, the material by its name in its library, the property, and the dataset used with its
    source — from the case's own data, which holds it; where the material's name finds it now, by
    the name that names it exactly, none where nothing does; and how the dataset's data differs
    from what the material holds now — nothing, for a case its study makes now."""

    group: str
    material: str
    property: str
    dataset: str
    source: str | None
    found: str | None = None
    differs: tuple[DataChange, ...] = ()


def held_now(c: Checking, study: Part | None, case: Case) -> tuple[list[Filled], str]:
    """Each body's material and each property's dataset as ``case`` holds them, each with where
    its material is found now and how the dataset's data differs from what it holds now
    (`Filled`); and the ID the case would have with each dataset's data as its material now holds
    it — its own ID, where none differs (materials.md § 6; models.md § 5.3). The material a body's
    name is now is the one ``study``'s component assigns that body now, where it is that material
    written either way, and otherwise the one the name finds, the project's own first (§ 4)."""
    out, assign = [], {}
    for group, held in sorted(case.component.assign.items()):
        part = _material_now(c, study, group, held.material)
        properties = {}
        for prop, used in sorted(held.properties.items()):
            now, why = _data_now(c, part, prop, used.dataset)
            differs = ((DataChange(key="", case="", now=why),) if why is not None
                       else tuple(_differs(used.data, now, c.units)))
            out.append(Filled(group=group, material=held.material, property=prop, dataset=used.dataset,
                              source=used.data.source, found=part.address.name if part is not None else None,
                              differs=differs))
            properties[prop] = used if now is None else used.model_copy(update={"data": now})
        assign[group] = held.model_copy(update={"properties": properties})
    return out, case_id(case.model_copy(update={"component": case.component.model_copy(update={"assign": assign})}))


def _material_now(c: Checking, study: Part | None, group: str, name: str) -> Part | None:
    """The material a case's ``name`` for ``group`` is now, loaded or not (`held_now`); None where
    neither the project nor the global library holds it."""
    kind = c.opened.layout.objects[PROPERTY].part
    holder = cites(c, "component", study.data.component) if study is not None and study.data is not None else None
    k = contract(c.opened, holder) if holder is not None else None
    assigned = k.assign.get(group) if k is not None else None
    if assigned is not None and assigned.material is not None and names.bare(assigned.material) == name:
        return door.named(c.opened, kind, assigned.material)
    return door.named(c.opened, kind, name)


def _data_now(c: Checking, part: Part | None, prop: str, dataset: str) -> tuple[Model | None, str | None]:
    """The data ``dataset`` of ``prop`` holds now in the material ``part``, as a case holds it
    (`content`); or None, and why there is none to compare."""
    if part is None:
        return None, "the material is found nowhere now"
    if part.data is None:
        return None, "the material does not load now"
    answers = datasets(c, part).get(prop, {})
    if dataset not in answers:
        return None, f"the material holds no dataset `{dataset}` of its {prop} now"
    try:
        return content(answers[dataset].data, {}, c.units, part.address), None
    except Refused as exc:
        return None, f"the dataset does not read now: {exc}"


def _keyed(value: Any) -> dict[str, Any] | None:
    """A value a case holds as its keys and their values, as its file writes them (`table`): a
    model's fields and the parameters beyond them, a table's own; None for a quantity, or any
    other value."""
    return table(value) if isinstance(value, (BaseModel, dict)) and not isinstance(value, Exact) else None


def _differs(was: Any, now: Any, units: Units, at: tuple[str, ...] = ()) -> list[DataChange]:
    """Where two datasets' data, as a case holds it, differ: each key's value, a quantity whole."""
    a, b = _keyed(was), _keyed(now)
    if a is not None and b is not None:
        return [d for k in sorted(set(a) | set(b)) for d in _differs(a.get(k), b.get(k), units, (*at, k))]
    return [] if was == now else [DataChange(key=key_path(at) or "data", case=_said(was, units),
                                             now=_said(now, units))]


def _said(value: Any, units: Units) -> str:
    """A value a case holds, as a person reads it: a quantity as `shown`, a list in brackets, a
    table in braces, none as `none`."""
    if value is None:
        return "none"
    if isinstance(value, list):
        return "[" + ", ".join(_said(v, units) for v in value) + "]"
    keyed = _keyed(value)
    if keyed is not None:
        return "{" + ", ".join(f"{k} = {_said(v, units)}" for k, v in keyed.items()) + "}"
    return shown(value, units)


def shown(value: Any, units: Units, display: Iterable[str] = ()) -> str:
    """A value a case holds, for a person, by the core's one formatter (`Units.shown`): a quantity
    in the first of ``display`` — its study's display units — of its dimension, else in its
    canonical unit, exactly, its decimal where it has one — `0.1 m` — else `p/q`, `1/3 m`."""
    q = quantity(value)
    return units.shown(q, display) if q is not None else str(value)
