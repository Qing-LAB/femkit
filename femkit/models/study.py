"""A study, `studies/<s>.toml` (models.md § 5.1): it pairs a component with the physics of its
steps and a mesh recipe, and holds everything that is not the physics, with the resources of the
jobs that solve it and that make its geometries and meshes — the `models.study` part schema and
its check: its own rules, and its pairing, read from the contracts before anything runs
(projects.md § 3, geometry.md § 3).

A study is the problem's design and names no engine: the engine that solves it is chosen when it
is solved, `study prep --engine` (ADR 0025 decision 1). A file writing `engine` is told so, in the
schema's own words (`Study.WITHDRAWN`). Which engines can solve it — those a hand-over gives the mesh
its recipe's mesher writes, at each geometry order of its cases (`solvers`, by `takes`) — is a fact
`project check`, `study list`, the graph and `study prep --engine` read alike (models.md §§ 5.1,
11.1; workflow.md § 2.2).

What the pairing finds wrong is said once, in the file that needs changing, at the key that names
what is wrong (models.md § 5.1): a group the component does not promise at the physics' or the
recipe's key that names it; a meaning the physics lacks at its `meaning`; an axis of revolution
the component lacks at its frame; a property a material lacks at the material's. What only the
built geometry can tell is one note on the study. Each statement a physics makes on a group
(`statements`), and which of them only the built geometry tells (`waits_on_geometry`), the
project's graph reads too, to wire each group through the pairing (models.md § 11.2).

Its findings:
- on the study, at its key: `bad-unit` (error), at `display`: a unit the unit table does not read;
  `unsupported-kind` (error), at `steps.<s>.kind`: choices, the step kinds the formulation
  supports; `not-built` (error), at `steps.<s>`: each step after the first, several steps in one
  study not built yet; `no-such-step` (error), at `steps.<s>.takes_from.<what>`: a step it takes from that is
  not another of the study's — the others, with the quantity, its choices; `no-such-quantity`
  (error), there: a quantity the step's formulation does not derive, its choices those it does;
  `step-circle` (error), at `steps.<s>.takes_from`: steps taking from each other in a circle
  (models.md § 4.5); the axes' and the crossing's (`axes.py`); each name it cites that names no
  part (`parts.cited`);
- `not-checked-yet` (info), on the study: at the key naming a part it uses that does not load —
  at the file, for the project file — what is paired with it checked once it loads; at
  `component`, once for the study, whether its groups are the places its physics' statements
  stand on, known once the geometry is built (geometry.md § 7);
- on the paired parts, at their keys: `not-promised` (error), at the physics' or recipe's key
  naming a group the component does not promise — the groups that would do its choices;
  `wrong-place` (error), at a condition's or source's group: one that cannot be a place its kind
  stands on — the groups that may be, its choices; `no-meaning` (error), at the physics'
  `meaning.<d>`: nothing stated for the component's dimension — the formulation's meanings for it,
  its choices; `no-axis` (error), at the component's `frame.symmetry.axis`: an axisymmetric
  physics paired with a frame stating no axis of revolution — the axes, its choices;
  `property-missing` (error), at the material's `properties.<p>`: a property a formulation reads,
  held neither under it nor under an equivalent form of it; at the component's
  `assign.<group>.datasets.<p>`, a dataset a step takes that no case can take yet (materials.md
  § 6): `form-unconverted` (error), one held under an equivalent form, which no case converts
  yet — the datasets held under the property itself its choices; `dataset-varies` (error), one
  that varies with a variable the step's kind does not supply, or, under a kind that supplies
  none, a `value` whose range is not `all` — naming the step and the variable, and what would be
  right, the datasets the material holds that would do its choices.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Annotated, Any, Iterator, Literal, Mapping

from pydantic import Field, model_validator

from femkit.core.issues import Issue
from femkit.core.schema import (DeclaredKey, Model, Number, as_quantity, as_reference, closed, field_extras, meant,
                                whole, written_keys)
from femkit.core.units import UnitError
from femkit.definitions.formulations import FormulationDefinition
from femkit.definitions.meshers import MesherDefinition, handover
from femkit.geometry.component import AXISYMMETRIC, Component, Symmetry
from femkit.geometry.recipe import ORDER
from femkit.jobs.request import Resources
from femkit.materials.material import Value, varies_with
from femkit.models import axes
from femkit.models.parts import (ASSIGNMENT, DATASETS, PROPERTY, SIZE, Contract, called, cited, contract, datasets,
                                 listed, material, objects)
from femkit.models.physics import TABLES, Physics, kinds
from femkit.projects import door
from femkit.projects.addresses import Address
from femkit.projects.checking import Checking, Registration
from femkit.projects.door import Part
from femkit.projects.names import STEP
from femkit.projects.schemas import PartFile

StepName = Annotated[str, Field(pattern=whole(STEP))]   # a step's name: one step of the name rule


class Step(Model):
    """One step: the physics it solves and the kind of calculation, after any step it takes from
    (models.md §§ 4.2, 4.5)."""

    physics: str = as_reference("the physics it solves, by name", "physics")
    kind: str = Field(description="the kind of calculation, which the physics' formulation must support",
                      json_schema_extra={"doc": "models.md § 4.2"})
    takes_from: dict[str, str] = Field(default_factory=dict, description="when several physics are solved in turn, "
                                       "what it takes from a step that runs before it — a heat step taking an optics "
                                       "step's absorbed power, say: each by what it is to its own physics, then the "
                                       "step's name and a quantity that step derives; not built yet, since a study "
                                       "solves one step until several are")


class Element(Model):
    """The finite element (models.md § 6.4)."""

    family: Literal["lagrange", "nedelec"] = Field(description="the element family")
    degree: int = Field(ge=1, description="its polynomial degree: a whole number, 1 or more")


class Solver(Model):
    """The linear solver (models.md § 5.1)."""

    kind: Literal["direct", "iterative"] = Field(description="how the linear system is solved, exactly or to a "
                                                             "tolerance")
    tolerance: Number | None = Field(default=None, gt=0, description="the relative tolerance an iterative solver "
                                                                     "stops at: a plain number; required with "
                                                                     "`iterative`")

    @model_validator(mode="after")
    def _tolerance(self) -> "Solver":
        if (self.kind == "iterative") != (self.tolerance is not None):
            raise ValueError("an iterative solver states its tolerance, and a direct one none")
        return self


class Numerics(Model):
    """How the equations are discretized and solved, the same in every environment, the mesh apart
    (models.md § 6.4)."""

    element: Element = Field(description="the finite element")
    solver: Solver = Field(description="the linear solver")


class Axis(Model):
    """One axis: its class, its values and the one unit they are in (models.md § 5.1)."""

    class_: Literal["numerical convergence", "geometry convergence", "physical sweep"] = Field(
        alias="class", description="why it varies")
    values: list[Number | str] = Field(min_length=1, description="its values, in order: plain numbers — in its `unit` "
                                                                 "where what it varies has one — or, for a material's "
                                                                 "dataset, each dataset by its name")
    unit: str | None = as_quantity("the unit its values are in, where what it varies has one: a unit of its "
                                   "dimension", "unit", default=None)


class Together(Model):
    """A group of axes that step together (models.md § 5.1): the n-th case takes each one's n-th
    value."""

    axes: list[str] = Field(min_length=2, description="the address of each axis of the study it steps together, two or "
                                                      "more, of one class, with as many values each")
    reason: str = Field(description="why their values belong together, in a sentence")


class Crossing(Model):
    """Why axes of more than one class are crossed (models.md § 5.1)."""

    axes: list[str] = Field(description="the address of every axis of the study")
    reason: str = Field(description="why the full product is needed, in a sentence")


class Solve(Model):
    """What belongs to the solve, whatever engine solves it (models.md § 5.1): its job's resources.
    What only one engine has — its options, decisions, customizations and truncations — goes under
    that engine's name, `[solve.<engine>]`, as each is built."""

    resources: Resources = Field(description="the resources of the job that solves the study's cases, each in turn "
                                             "within it, stated, never derived",
                                 json_schema_extra={"doc": "jobs.md § 2"})


class Meshing(Model):
    """The job that makes the study's geometries and meshes (models.md § 5.1; workflow.md § 5):
    its resources alone, nothing of an engine's."""

    resources: Resources = Field(description="the resources of the job that makes the study's geometries and "
                                             "meshes, each in turn within it, stated, never derived",
                                 json_schema_extra={"doc": "workflow.md § 5"})


class Study(PartFile):
    """`studies/<s>.toml`: a component paired with the physics of its steps and a mesh recipe;
    what varies; what belongs to its solve, whatever engine solves it; and the job that makes its
    geometries and meshes (models.md § 5.1). It names no engine: the engine is chosen when it is
    solved."""

    CHANGES = {2: "what belongs to its solve is under `[solve]` and its meshing job under `[meshing]`, in place of "
                  "`[environments.<e>]`, naming no engine — the engine is chosen when the study is solved, `femkit "
                  "study prep STUDY --engine ENGINE` — and it names no `observables`: an observables part names the "
                  "studies it reads"}
    WITHDRAWN = {"engine": "the engine is chosen when the study is solved, `femkit study prep STUDY --engine ENGINE`"}

    schema_: Literal[2] = Field(alias="schema", description="the version of this file's format, which femkit raises "
                                "when it changes how files of this kind are written",
                                json_schema_extra={"doc": "models.md § 2"})
    component: str = as_reference("the component it solves, by name", "component")
    mesh: str = as_reference("the mesh recipe it meshes with, by name: the recipe states the mesher that makes its "
                             "mesh, which the engine chosen to solve the study must take", "mesh")
    display: list[str] = as_quantity("the units values are shown in: each value in the first listed unit of its "
                                     "dimension, else in SI units, angles in degrees", "unit", default_factory=list)
    steps: dict[StepName, Step] = Field(min_length=1, description="its steps, by name: each solves its physics as a "
                                        "kind of calculation, after any step it takes from; the order they are "
                                        "written in means nothing; one step for now, several in one study not built "
                                        "yet", json_schema_extra={"doc": "models.md § 4.5"})
    numerics: Numerics = Field(description="how the equations are discretized and solved — the finite element and "
                                           "the linear solver — the same whatever the engine",
                               json_schema_extra={"doc": "models.md § 6.4"})
    axes: dict[str, Axis] = Field(default_factory=dict, description="what varies, each axis keyed by the address of "
                                  "what it varies — a definition written as its value, `project:definitions.side`; a "
                                  "value of the mesh recipe, `mesh:uniform:size`; a numerics field; or a material's "
                                  "dataset — every axis crossed with every other, but those a group steps together, "
                                  "which cross as one; a value one formula gives is that formula, not an axis",
                                  json_schema_extra={"doc": "models.md § 5.1"})
    together: dict[StepName, Together] = Field(default_factory=dict, description="groups of axes that step together, "
                                               "each by its name: the n-th case takes each one's n-th value — for "
                                               "values no formula relates, such as each sample's measured sizes",
                                               json_schema_extra={"doc": "models.md § 5.1"})
    crossing: Crossing | None = Field(default=None, description="when what is crossed holds axes of more than one "
                                                                "class: every axis, and why their full product is "
                                                                "needed")
    solve: Solve | None = Field(default=None, description="what belongs to the solve, whatever engine solves it: "
                                                          "the resources of the job that solves its cases",
                                json_schema_extra={"doc": "models.md § 5.1"})
    meshing: Meshing = Field(description="the job that makes its geometries and meshes: its resources alone",
                             json_schema_extra={"doc": "models.md § 5.1"})


#: The study's object type its steps are, by the name the layout declares it under; the layout's
#: declaration names its table (`layout.objects[...]`), as it does its axes' (`axes.AXIS`).
STEP_TYPE = "step"


def _stated(c: Checking, text: str, manual: str | None) -> list[DeclaredKey]:
    """The keys a study's text holds that a declaration states, not its schema (core.md § 2; web.md
    § 8.3): each step's `kind`, one of the step kinds the formulations support (models.md § 4.2), its
    help ending with ``manual``, the chapter of the manual its kind declares — for each step the text
    writes, set or shown commented out, in the table the layout declares its steps in."""
    supported = tuple(dict.fromkeys(k for f in c.formulations.values() for k in f.kinds))
    field = Step.model_fields["kind"]
    steps = c.opened.layout.objects[STEP_TYPE].keys
    named = sorted({p[len(steps)] for p in written_keys(text) if len(p) > len(steps) and p[:len(steps)] == steps})
    return [DeclaredKey((*steps, step, "kind"), field.description, values=supported, required=field.is_required(),
                        manual=manual if field_extras(field).get("doc") else None) for step in named]


def named(c: Checking, field: str, name: str, model: type[Model] = Study) -> Part | None:
    """The part ``name`` names, through ``model``'s ``field`` and its `ref`, loaded or not; None for
    one the project lacks — its own finding says why."""
    return c.opened.parts.get(str(Address(field_extras(model.model_fields[field])["ref"], name)))


def cites(c: Checking, field: str, name: str, model: type[Model] = Study) -> Part | None:
    """The loaded part ``name`` names, through ``model``'s ``field`` and its `ref`; None for one the
    project lacks or that does not load — its own finding says why."""
    found = named(c, field, name, model)
    return found if found is not None and found.data is not None else None


def used(c: Checking, study: Part) -> list[tuple[tuple[str, ...], Part]]:
    """Every part ``study`` uses, loaded or not, with the key of the study naming it: the project
    file, at none; its component, its steps' physics and its recipe; and the materials its component
    assigns — the project's own, or the global library's — at `component` (models.md § 5.3;
    materials.md § 4) — never an observables part reading it (models.md § 5.2)."""
    data: Study = study.data
    holder = named(c, "component", data.component)
    steps = c.opened.layout.objects[STEP_TYPE].keys
    found = [((), c.opened.parts.get(c.opened.layout.project_kind)),
             (("component",), holder), (("mesh",), named(c, "mesh", data.mesh)),
             *(((*steps, n, "physics"), named(c, "physics", s.physics, Step)) for n, s in data.steps.items())]
    k = contract(c.opened, holder) if holder is not None else None
    for assigned in k.assign.values() if k else ():
        held = door.named(c.opened, c.opened.layout.objects[PROPERTY].part, assigned.material) \
            if assigned.material else None
        found.append((("component",), held))
    return [(keys, p) for keys, p in found if p is not None]


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """The study's own rules, then its pairing (models.md § 5.1, projects.md § 3)."""
    data: Study = part.data
    yield from cited(c, part)
    for unit in data.display:
        try:
            c.units.unit(unit)
        except UnitError as exc:
            yield c.issue(part, "display", code="bad-unit", label=unit, message=f"the display unit `{unit}` does "
                                                                                 f"not read: {exc}")
    yield from _kinds(c, part, data)
    yield from _takes(c, part, data)
    yield from axes.check(c, part)
    yield from _unloaded(c, part)
    yield from _pairing(c, part, data)


def formulation(c: Checking, step: Step) -> tuple[Physics | None, FormulationDefinition | None]:
    """A step's physics, loaded, and its formulation; None where either is missing."""
    p = cites(c, "physics", step.physics, Step)
    return (p.data, c.formulations.get(p.data.formulation)) if p is not None else (None, None)


def _kinds(c: Checking, part: Part, data: Study) -> Iterator[Issue]:
    """Each step's kind, one its physics' formulation supports (models.md § 4.2) — whatever the
    component it is paired with; and each step after the first, `not-built`: a study solves one step
    until several in one study are built (models.md § 5.1)."""
    steps = c.opened.layout.objects[STEP_TYPE].keys
    first = next(iter(data.steps))
    for name in list(data.steps)[1:]:
        yield c.issue(part, *steps, name, code="not-built",
                      message=f"the study holds the step `{name}` beside `{first}`, and a study solves one step: "
                              "several steps in one study, solved in turn or together, are not built yet")
    for name, step in data.steps.items():
        physics, f = formulation(c, step)
        if f is not None and step.kind not in f.kinds:
            yield c.issue(part, *c.opened.layout.objects[STEP_TYPE].keys, name, "kind", code="unsupported-kind",
                          choices=f.kinds, message=f"{physics.formulation} does not support the `{step.kind}` kind of calculation")


def _takes(c: Checking, part: Part, data: Study) -> Iterator[Issue]:
    """Each hand-off between steps: the step taken from is another of the study's, and derives the
    quantity; no steps take from each other in a circle (models.md § 4.5)."""
    after: dict[str, list[str]] = {}
    steps = c.opened.layout.objects[STEP_TYPE].keys
    for name, step in data.steps.items():
        after[name] = []
        for what, given in step.takes_from.items():
            source, _, quantity = given.partition(".")
            if source not in data.steps or source == name:
                others = [s for s in data.steps if s != name]
                yield c.issue(part, *steps, name, "takes_from", what, code="no-such-step", label=source,
                              choices=[f"{s}.{quantity}" for s in others],
                              message=f"the step {name} takes {what} from `{source}`, which is no other step of the "
                                      f"study: {listed(others) or 'it has none'}")
                continue
            after[name].append(source)
            f = formulation(c, data.steps[source])[1]
            if f is not None and quantity not in f.derived:
                yield c.issue(part, *steps, name, "takes_from", what, code="no-such-quantity",
                              choices=[f"{source}.{q}" for q in f.derived],
                              message=f"the step {source} derives no `{quantity}`" + meant(quantity, f.derived))
    walking: list[str] = []
    done: set[str] = set()

    def visit(name: str) -> Iterator[Issue]:
        if name in done:
            return
        if name in walking:
            circle = [*walking[walking.index(name):], name]
            done.update(circle)
            yield c.issue(part, *steps, circle[0], "takes_from", code="step-circle",
                          message=f"the steps {' → '.join(circle)} take from each other in a circle")
            return
        walking.append(name)
        for source in after[name]:
            yield from visit(source)
        walking.pop()
        done.add(name)

    for name in data.steps:
        yield from visit(name)


def _unloaded(c: Checking, part: Part) -> Iterator[Issue]:
    """Each part the study uses that does not load, said once on the study, at the key naming it:
    what the study pairs with it is checked once it loads; its own finding says why it does not."""
    seen: set[str] = set()
    for keys, used_part in used(c, part):
        if used_part.data is None and str(used_part.address) not in seen:
            seen.add(str(used_part.address))
            yield c.unchecked(part, *keys, message=f"what the study pairs with {called(used_part.address)} is "
                                                   "checked once that file loads")


def _pairing(c: Checking, part: Part, data: Study) -> Iterator[Issue]:
    """The component, physics and recipe the study pairs, read from the contract
    (projects.md § 3): every group they name is one the component promises, at a place each
    statement may stand on — said at the key naming it, in its own file; what only the built
    geometry can tell, one note on the study."""
    holder = cites(c, "component", data.component)
    k = contract(c.opened, holder) if holder is not None else None
    if k is None:
        return
    pairs = f"the study `{part.address.name}` pairs"
    uncertain: dict[str, list[str]] = {}
    read: list[FormulationDefinition] = []
    for step in data.steps.values():
        p = cites(c, "physics", step.physics, Step)
        f = c.formulations.get(p.data.formulation) if p is not None else None
        if f is None:
            continue
        read.append(f)
        physics: Physics = p.data
        here = f"{pairs} this physics with the component `{k.part.address.name}`"
        dimension = str(k.dimension)
        if k.dimension is not None and dimension not in physics.meaning:
            yield c.issue(p, "meaning", dimension, code="no-meaning", choices=f.meanings.get(dimension, []),
                          message=f"{here}, which is {dimension}-D, and this physics states nothing of what "
                                  f"{dimension}-D means for {physics.formulation}")
        elif physics.meaning.get(dimension) == AXISYMMETRIC and k.axis is None:
            yield c.issue(holder, "frame", "symmetry", "axis", code="no-axis",
                          choices=closed(Symmetry.model_fields["axis"].annotation),
                          message=f"{pairs} this component with the physics `{step.physics}`, which is axisymmetric "
                                  f"in {dimension}-D: the frame states no axis the drawing is revolved about")
        for at, group, what, on in statements(f, physics):
            yield from _placed(c, p, at, k, group, here, what, on, uncertain)
    recipe = cites(c, "mesh", data.mesh)
    for group in objects(c.opened, recipe, SIZE) if recipe is not None else {}:
        yield from _placed(c, recipe, ("sizes", group), k, group,
                           f"{pairs} this recipe with the component `{k.part.address.name}`", "a size", None, {})
    if uncertain:
        yield c.unchecked(part, "component", message=_uncertain(uncertain, k))
    yield from _filled(c, part, k, read)
    yield from _varies(c, part, data, k)


def statements(f: FormulationDefinition, physics: Physics
               ) -> Iterator[tuple[tuple[str, ...], str, str, list[str] | None]]:
    """Each statement of ``physics`` that stands on a group (models.md §§ 3, 5.1) — a condition on
    the group it is keyed by, a source on its `on` — with its key, the group, what it is as a person
    says it, and the places its kind stands on as ``f`` declares it; None for a kind ``f`` lacks,
    whose own finding says so."""
    for table, (noun, _) in TABLES.items():
        for key, entry in getattr(physics, table).items():
            spec = kinds(f, table).get(entry.kind)
            at, group = ((table, key), key) if table == "conditions" else ((table, key, "on"), entry.on)
            yield at, group, f"a {entry.kind} {noun}", spec.on if spec is not None else None


def fitting(c: Checking, k: Contract, group: str, on: list[str]) -> tuple[list[str], list[str]]:
    """The places ``group`` may be before the geometry exists, and those of them a statement that
    stands ``on`` those places may stand on: none of them, the statement is on a wrong place; fewer,
    which it is waits on the built geometry (geometry.md § 7)."""
    may = k.places(group, c.places)
    return may, [p for p in may if p in on]


def waits_on_geometry(c: Checking, part: Part) -> set[tuple[str, tuple[str, ...]]]:
    """Each statement the study's pairing names a group in whose fit only the built geometry tells
    — the part holding it, by its address, and its key — the one fact a wire through that group
    reads as not checked yet (models.md §§ 5.1, 11.2; web.md § 7.6), told as `project check`'s note
    tells it (`_placed`)."""
    holder = cites(c, "component", part.data.component)
    k = contract(c.opened, holder) if holder is not None else None
    found: set[tuple[str, tuple[str, ...]]] = set()
    for step in part.data.steps.values() if k is not None else ():
        p = cites(c, "physics", step.physics, Step)
        f = c.formulations.get(p.data.formulation) if p is not None else None
        for at, group, _, on in statements(f, p.data) if f is not None else ():
            if group in k.groups and on is not None:
                may, fits = fitting(c, k, group, on)
                if fits and len(fits) < len(may):
                    found.add((str(p.address), at))
    return found


def _placed(c: Checking, holder: Part, at: tuple[str, ...], k: Contract, group: str, here: str, what: str,
            on: list[str] | None, uncertain: dict[str, list[str]]) -> Iterator[Issue]:
    """``what`` stands on ``group``, named at ``at`` of ``holder``: a group the component
    promises and, given the places it may stand ``on``, one that may be such a place — certainly,
    or, noted in ``uncertain``, once the geometry exists (geometry.md § 7)."""
    if group not in k.groups:
        would = k.standing(on, c.places) or list(k.groups)
        yield c.issue(holder, *at, code="not-promised", label=group, choices=would,
                      message=f"{here}, which promises no group `{group}`" + meant(group, would))
        return
    if on is None:
        return
    may, fits = fitting(c, k, group, on)
    if not fits:
        would = k.standing(on, c.places)
        yield c.issue(holder, *at, code="wrong-place", label=group, choices=would,
                      message=f"{what} stands on {' or '.join(_word(p) for p in on)}, and `{group}`, of dimension "
                              f"{k.groups[group]} in `{k.part.address.name}`, is "
                              f"{' or '.join(_word(p) for p in may) or 'no place'}")
    elif len(fits) < len(may):
        uncertain.setdefault(" or ".join(_word(p) for p in fits), []).append(group)


def _word(place: str) -> str:
    """A place as a person says it, with its article: `an outer boundary`, `a body`."""
    words = place.replace("_", " ")
    return ("an " if words[0] in "aeiou" else "a ") + words


def _uncertain(uncertain: dict[str, list[str]], k: Contract) -> str:
    """One note for every group whose place only the built geometry tells: `whether `left` and
    `right` are each an outer boundary, and `middle` an interface, is checked once …`."""
    said = []
    for i, (place, groups) in enumerate(uncertain.items()):
        groups = list(dict.fromkeys(groups))
        verb = "is " if len(groups) == 1 else "are each "
        said.append(f"{listed(groups)} {verb if i == 0 else ('each ' if len(groups) > 1 else '')}{place}")
    whole_list = said[0] if len(said) == 1 else ", ".join(said[:-1]) + ", and " + said[-1]
    return (f"whether {whole_list}{',' if len(said) > 1 else ''} is checked once the geometry of "
            f"`{k.part.address.name}` is built")


def _filled(c: Checking, part: Part, k: Contract, read: list[FormulationDefinition]) -> Iterator[Issue]:
    """Each material the component assigns — the project's own, or the global library's, as its
    name finds it (materials.md § 4) — provides every property the steps' formulations read, held
    under it or under an equivalent form of it (§ 1): said at the material's own key, in its own
    file; one found nowhere is the component's own finding (`materials/assign.py`)."""
    needed = sorted({p for f in read for p in f.properties})
    for group, assigned in k.assign.items():
        m = material(c.opened, assigned.material) if assigned.material is not None else None
        if m is None:
            continue
        held = datasets(c, m)
        for prop in needed:
            if not held.get(prop):
                yield c.issue(m, "properties", prop, code="property-missing", label=prop,
                              message=f"the study `{part.address.name}` solves physics reading the {prop} of "
                                      f"`{group}` in `{k.part.address.name}`, which this material fills, and it "
                                      f"holds no {prop}, nor a form of it")


def _varies(c: Checking, part: Part, data: Study, k: Contract) -> Iterator[Issue]:
    """Each dataset a step would take that no case can take yet (materials.md § 6) — the dataset the
    assignment names, or the one the property has, and each one an axis of the study names in its
    place — an error at the component's `assign.<group>.datasets.<property>`:
    - `form-unconverted`, said once: one held under an equivalent form of the property the
      formulation reads, which no case converts yet (plan § 4, M9) — what would be right, a
      dataset held under the property itself, its choices;
    - `dataset-varies`: one that varies with a variable the step's kind does not supply — a table
      or a model under a `stationary` step, which supplies none — or, under a kind that supplies
      none, a `value` whose range is not `all`, which holds only where its range says, never at
      zero frequency (material-data.md § 7); naming the step and the variable, saying what would
      be right — under a kind that supplies none, a `value` of the property at zero frequency, its
      range `all` — the datasets the material holds that would do its choices, and, where no kind
      femkit declares supplies that variable, that none does yet.
    What a kind supplies is its declaration's (`femkit/data/step_kinds.toml`)."""
    assign = c.opened.layout.objects[ASSIGNMENT].keys
    by_axes: dict[tuple[str, str], list[str]] = {}
    for key, axis in data.axes.items():
        found = axes.target(c, part, key)
        if isinstance(found, axes.Target) and found.how == "dataset" and found.address.part == k.part.address:
            by_axes.setdefault((found.address.path[-3], found.address.path[-1]), []).extend(map(str, axis.values))
    anywhere = {v for kind in c.step_kinds.values() for v in _supplied(c, kind.supplies)}
    said: set[tuple[str, str, str]] = set()
    for name, step in data.steps.items():
        f, kind = formulation(c, step)[1], c.step_kinds.get(step.kind)
        if f is None or kind is None:
            continue
        supplied = _supplied(c, kind.supplies)
        solves = (f"the study `{part.address.name}` solves its step `{name}` as a {step.kind} calculation, which "
                  + (f"supplies {_variables(kind.supplies)}" if kind.supplies else "supplies no variable"))
        for group, assigned in k.assign.items():
            m = material(c.opened, assigned.material) if assigned.material is not None else None
            held = datasets(c, m) if m is not None else {}
            for prop in f.properties:
                named = held.get(prop, {})
                taken = [assigned.datasets.get(prop) or (next(iter(named)) if len(named) == 1 else None),
                         *by_axes.get((group, prop), [])]
                at = (*assign, group, DATASETS, prop)
                for dataset in dict.fromkeys(d for d in taken if d in named):
                    answer, of = named[dataset], f"the dataset `{dataset}` of `{assigned.material}`"
                    if answer.form != prop and (group, prop, dataset) not in said:
                        said.add((group, prop, dataset))
                        yield c.issue(k.part, *at, code="form-unconverted", label=dataset,
                                      choices=[d for d, a in named.items() if a.form == prop],
                                      message=f"{of} is held as the {_words(answer.form)}, a form of the "
                                              f"{_words(prop)} the study `{part.address.name}` reads, and no case "
                                              f"converts one yet: a dataset held as the {_words(prop)} itself "
                                              "would do")
                    variable = varies_with(answer.data, c.dispersion)
                    if variable is not None and variable not in supplied:
                        why = f"{of} varies with the {_words(variable)}"
                        yet = "" if variable in anywhere else \
                            f"; no step femkit has yet supplies the {_words(variable)}"
                    elif variable is None and not supplied and isinstance(answer.data, Value) \
                            and answer.data.range not in (None, "all"):
                        why = f"{of} is a value that holds only over its range, never at zero frequency"
                        yet = "" if anywhere else "; no step femkit has yet supplies a variable"
                    else:
                        continue
                    yield c.issue(k.part, *at, code="dataset-varies", label=dataset,
                                  choices=[d for d, a in named.items()
                                           if a.form == prop and _holds(c, a.data, supplied)],
                                  message=f"{solves}, and {why}: {_would(kind.supplies, prop)}{yet}")


def _would(supplies: list[str], prop: str) -> str:
    """What would hold under a step supplying ``supplies`` (materials.md § 6)."""
    if not supplies:
        return f"a `value` of the {_words(prop)} at zero frequency, its range `all`, would hold there"
    return f"a dataset of the {_words(prop)} that varies with {_variables(supplies)}, or with none, would hold there"


def _supplied(c: Checking, variables: list[str]) -> set[str]:
    """Every form of each variable in ``variables`` — the wavelength, the frequency and the photon
    energy each state one spectral position (materials.md § 2)."""
    return {form for v in variables if v in c.dispersion.variables for form in c.dispersion.forms(v)}


def _holds(c: Checking, dataset: Any, supplied: set[str]) -> bool:
    """Whether a dataset holds under a step supplying ``supplied``: it varies with one of them, or
    with none — and, under a step supplying none, it is a value whose range is `all` (§ 6)."""
    variable = varies_with(dataset, c.dispersion)
    if variable is not None:
        return variable in supplied
    return bool(supplied) or not isinstance(dataset, Value) or dataset.range == "all"


def _words(name: str) -> str:
    """A declared name — a variable's, a property's — in a sentence, as words: `photon_energy`, the
    photon energy."""
    return name.replace("_", " ")


def _variables(variables: list[str]) -> str:
    """Variables in a sentence: `the wavelength`, `the wavelength and the frequency`."""
    return listed(map(_words, variables), "the {}")


# ------------------------------------------------------------------ the engines that can solve it

def orders(c: Checking, study: Part, recipe: Part) -> list[int]:
    """Each geometry order the study's cases have (workflow.md § 2.2): the recipe's, and each value
    an axis of the study gives the recipe's `order`, read from the axis's declared address."""
    found = [recipe.data.order]
    for key, axis in study.data.axes.items():
        target = axes.target(c, study, key)
        if isinstance(target, axes.Target) and target.address == Address(recipe.address.kind, recipe.address.name,
                                                                         (ORDER,)):
            for value in axis.values:
                try:
                    found.append(int(Fraction(str(value))))
                except (ValueError, ZeroDivisionError):
                    continue                          # the axis's own finding says why
    return list(dict.fromkeys(found))


def meshed_order(m: MesherDefinition, order: int, contract: Component) -> int | None:
    """The geometry order of a case's mesh, its recipe's at ``order``: the recipe's, or, for a mesher
    whose order is the contract's — the pass-through — the order of the mesh the component's script
    writes; None where the contract declares none (workflow.md § 2.3)."""
    if m.order == "recipe":
        return order
    return contract.outputs.mesh.order if contract.outputs.mesh is not None else None


def takes(handovers: Mapping[str, Any], engine: str, m: MesherDefinition, order: int | None) -> bool:
    """Whether ``engine`` takes the mesh the mesher ``m`` writes at geometry ``order``: a hand-over
    gives it that mesh (geometry.md § 8) — the one rule `solvers` and the workflow's prep read."""
    return order is not None and handover(handovers, engine, order, m.writes.values()) is not None


def solvers(c: Checking, study: Part) -> list[str] | None:
    """The engines that can solve ``study`` (models.md § 5.1): each engine femkit declares that takes
    the mesh its recipe's mesher writes at every geometry order of its cases (`takes`), by name;
    None where that cannot be told — its component or its recipe does not load, or the recipe names
    a mesher femkit lacks, each its own finding."""
    holder = cites(c, "component", study.data.component)
    recipe = cites(c, "mesh", study.data.mesh)
    if holder is None or recipe is None or not isinstance(holder.data, Component) or recipe.data.mesher not in c.meshers:
        return None
    m = c.meshers[recipe.data.mesher]
    used = [meshed_order(m, order, holder.data) for order in orders(c, study, recipe)]
    return [engine for engine in sorted(c.engines) if all(takes(c.handovers, engine, m, u) for u in used)]


KEY = "models.study"   # the key the layout names this schema by (projects.md § 4)
REGISTERS = Registration(schemas={KEY: Study}, checks={KEY: check}, keys={KEY: _stated})
