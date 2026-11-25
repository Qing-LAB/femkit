"""A study, `studies/<s>.toml` (models.md § 5.1): it pairs a component with the physics of its
steps, a mesh recipe and observable sets, and holds everything that is not the physics — the
`models.study` part schema and its check: its own rules, and its pairing, read from the
contracts before anything runs (projects.md § 3, geometry.md § 3).

What the pairing finds wrong is said once, in the file that needs changing, at the key that names
what is wrong (models.md § 5.1): a group the component does not promise at the physics', the
recipe's or the observable's key that names it; a meaning the physics lacks at its `meaning`; an
axis of revolution the component lacks at its frame; a property a material lacks at the
material's. What only the built geometry can tell is one note on the study.

Its findings:
- on the study, at its key: `bad-unit` (error), at `display`: a unit the unit table does not read;
  `no-such-environment` (error), at `environments.<e>`: choices, the declared environments;
  `unsupported-kind` (error), at `steps.<s>.kind`: choices, the step kinds the formulation
  supports; `no-such-step` (error), at `steps.<s>.takes.<what>`: a step it takes from that is not
  another of the study's — the others, with the quantity, its choices; `no-such-quantity`
  (error), there: a quantity the step's formulation does not derive, its choices those it does;
  `step-circle` (error), at `steps.<s>.takes`: steps taking from each other in a circle
  (models.md § 4.5); `observable-twice` (error), at `observables`: two of its sets share an
  observable's name; the axes' and the crossing's (`axes.py`); each name it cites that names no
  part (`parts.cited`);
- `not-checked-yet` (info), on the study: at the key naming a part it uses that does not load —
  at the file, for the project file — what is paired with it checked once it loads; at
  `component`, once for the study, whether its groups are the places its physics' statements
  stand on, known once the geometry is built (geometry.md § 7);
- on the paired parts, at their keys: `not-promised` (error), at the physics', recipe's or
  observable's key naming a group the component does not promise — the groups that would do its
  choices; `wrong-place` (error), at a condition's or source's group: one that cannot be a place
  its kind stands on — the groups that may be, its choices; `no-meaning` (error), at the physics'
  `meaning.<d>`: nothing stated for the component's dimension — the formulation's meanings for it,
  its choices; `no-axis` (error), at the component's `frame.symmetry.axis`: an axisymmetric
  physics paired with a frame stating no axis of revolution — the axes, its choices;
  `no-such-quantity`, `wrong-point`, `wrong-side`, `wrong-unit` (error), at the observable's key;
  `property-missing` (error), at the material's `properties.<p>`: a property a formulation reads.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Any, Iterator, Literal, Mapping

from pydantic import Field, model_validator

from femkit.core.issues import Issue
from femkit.core.schema import (LENGTH, Declared, Model, as_quantity, as_reference, closed, field_extras, help_text,
                                whole)
from femkit.core.units import Quantity, UnitError
from femkit.definitions.formulations import FormulationDefinition
from femkit.geometry.component import AXISYMMETRIC, Symmetry
from femkit.jobs.request import Resources
from femkit.models import axes
from femkit.models.observables import AlongLine, OverGroup, points, support
from femkit.models.parts import (PROPERTY, SIZE, Contract, called, cited, contract, datasets, listed, material, meant,
                                 objects)
from femkit.models.physics import TABLES, Physics, kinds
from femkit.projects.addresses import Address
from femkit.projects.checking import Checking
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
    takes: dict[str, str] = Field(default_factory=dict, description="when several physics are solved in turn, what "
                                  "it takes from a step that runs before it — a heat step taking an optics step's "
                                  "absorbed power, say: each by what it is to its own physics, then the step's name "
                                  "and a quantity that step derives")


class Element(Model):
    """The finite element (models.md § 6.4)."""

    family: Literal["lagrange", "nedelec"] = Field(description="the element family")
    degree: int = Field(ge=1, description="its polynomial degree: a whole number, 1 or more")


class Solver(Model):
    """The linear solver (models.md § 5.1)."""

    kind: Literal["direct", "iterative"] = Field(description="how the linear system is solved, exactly or to a "
                                                             "tolerance")
    tolerance: Decimal | None = Field(default=None, gt=0, description="the relative tolerance an iterative solver "
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
    """One axis: its class and its values (models.md § 5.1)."""

    class_: Literal["numerical convergence", "geometry convergence", "physical sweep"] = Field(
        alias="class", description="why it varies")
    values: list[str | int | Decimal] = Field(min_length=1, description="its values, in order, each written as the "
                                                                         "value the axis varies is written in its own "
                                                                         "file")


class Crossing(Model):
    """Why axes of more than one class are crossed (models.md § 5.1)."""

    axes: list[str] = Field(description="the address of every axis of the study")
    reason: str = Field(description="why the full product is needed, in a sentence")


class Binding(Model):
    """One engine environment's settings for the study (models.md § 5.1): its job's resources, for
    now."""

    resources: Resources = Field(description="the job's resources in this environment",
                                 json_schema_extra={"doc": "jobs.md § 2"})


class Study(PartFile):
    """`studies/<s>.toml`: a component paired with the physics of its steps, a mesh recipe and
    observable sets; what varies; each environment's settings (models.md § 5.1)."""

    component: str = as_reference("the component it solves, by name", "component")
    mesh: str = as_reference("the mesh recipe it meshes with, by name", "mesh")
    observables: list[str] = as_reference("the observable sets it reports, by name", "observables",
                                          default_factory=list)
    display: list[str] = as_quantity("the units values are shown in: each value in the first listed unit of its "
                                     "dimension, else in SI units, angles in degrees", "unit", default_factory=list)
    steps: dict[StepName, Step] = Field(min_length=1, description="its steps, by name: each solves its physics as a "
                                        "kind of calculation, after any step it takes from; the order they are "
                                        "written in means nothing", json_schema_extra={"doc": "models.md § 4.5"})
    numerics: Numerics = Field(description="how the equations are discretized and solved — the finite element and "
                                           "the linear solver — the same in every environment",
                               json_schema_extra={"doc": "models.md § 6.4"})
    axes: dict[str, Axis] = Field(default_factory=dict, description="what varies, each axis keyed by the address of "
                                  "what it varies — a parameter, `project:parameters.side`; a value of the mesh "
                                  "recipe, `mesh:uniform:size`; a numerics field; or a material's dataset — every "
                                  "axis crossed with every other", json_schema_extra={"doc": "models.md § 5.1"})
    crossing: Crossing | None = Field(default=None, description="when the axes are of more than one class: every "
                                                                "axis, and why their full product is needed")
    environments: dict[str, Binding] = as_reference("each engine environment's settings for this study, by the "
                                                    "environment's name", {"key": "environment"}, default_factory=dict,
                                                    extra={"doc": "models.md § 5.1"})


def declared(formulations: Mapping[str, FormulationDefinition]) -> Declared:
    """The help of each key of a study that a declaration states, not its schema (core.md § 2): a
    step's `kind`, one of the step kinds the formulations support (models.md § 4.2)."""
    supported = list(dict.fromkeys(k for f in formulations.values() for k in f.kinds))
    field = Step.model_fields["kind"]

    def help_of(path: tuple[str, ...]) -> str | None:
        if len(path) == 3 and path[0] == "steps" and path[2] == "kind":
            return help_text(field.description, supported, field_extras(field).get("doc"))
        return None

    return help_of


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
    file, at none; its component, its steps' physics, its recipe and its observable sets; and the
    project's own materials its component assigns, at `component` (models.md § 5.3)."""
    data: Study = study.data
    found = [((), c.opened.parts.get(c.opened.layout.project_kind)),
             (("component",), named(c, "component", data.component)), (("mesh",), named(c, "mesh", data.mesh)),
             *((("steps", n, "physics"), named(c, "physics", s.physics, Step)) for n, s in data.steps.items()),
             *((("observables",), named(c, "observables", o)) for o in data.observables)]
    holder = found[1][1]
    k = contract(c.opened, holder) if holder is not None else None
    for assigned in k.assign.values() if k else ():
        held = c.opened.parts.get(str(Address(c.opened.layout.objects[PROPERTY].part, assigned.material))) \
            if assigned.material else None
        found.append((("component",), held))
    return [(keys, p) for keys, p in found if p is not None]


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """The study's own rules, then its pairing (models.md § 5.1, projects.md § 3)."""
    data: Study = part.data
    yield from cited(c, part)
    for unit in data.display:
        try:
            c.units.parse(unit)
        except UnitError as exc:
            yield c.issue(part, "display", code="bad-unit", label=unit, message=f"the display unit `{unit}` does "
                                                                                 f"not read: {exc}")
    for name in data.environments:
        if name not in c.environments:
            yield c.issue(part, "environments", name, code="no-such-environment", choices=sorted(c.environments),
                          message=f"`{name}` is no engine environment femkit declares" + meant(name, c.environments))
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
    component it is paired with."""
    for name, step in data.steps.items():
        physics, f = formulation(c, step)
        if f is not None and step.kind not in f.kinds:
            yield c.issue(part, "steps", name, "kind", code="unsupported-kind", choices=f.kinds,
                          message=f"{physics.formulation} does not support the `{step.kind}` kind of calculation")


def _takes(c: Checking, part: Part, data: Study) -> Iterator[Issue]:
    """Each hand-off between steps: the step taken from is another of the study's, and derives the
    quantity; no steps take from each other in a circle (models.md § 4.5)."""
    after: dict[str, list[str]] = {}
    for name, step in data.steps.items():
        after[name] = []
        for what, given in step.takes.items():
            source, _, quantity = given.partition(".")
            if source not in data.steps or source == name:
                others = [s for s in data.steps if s != name]
                yield c.issue(part, "steps", name, "takes", what, code="no-such-step", label=source,
                              choices=[f"{s}.{quantity}" for s in others],
                              message=f"the step {name} takes {what} from `{source}`, which is no other step of the "
                                      f"study: {listed(others) or 'it has none'}")
                continue
            after[name].append(source)
            f = formulation(c, data.steps[source])[1]
            if f is not None and quantity not in f.derived:
                yield c.issue(part, "steps", name, "takes", what, code="no-such-quantity",
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
            yield c.issue(part, "steps", circle[0], "takes", code="step-circle",
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
    """The component, physics, recipe and observable sets the study pairs, read from the contract
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
        for table, (noun, _) in TABLES.items():
            for key, entry in getattr(physics, table).items():
                spec = kinds(f, table).get(entry.kind)
                at, group = ((table, key), key) if table == "conditions" else ((table, key, "on"), entry.on)
                yield from _placed(c, p, at, k, group, here, f"a {entry.kind} {noun}",
                                   spec.on if spec is not None else None, uncertain)
    recipe = cites(c, "mesh", data.mesh)
    for group in objects(c.opened, recipe, SIZE) if recipe is not None else {}:
        yield from _placed(c, recipe, ("sizes", group), k, group,
                           f"{pairs} this recipe with the component `{k.part.address.name}`", "a size", None, {})
    if uncertain:
        yield c.unchecked(part, "component", message=_uncertain(uncertain, k))
    yield from _observed(c, part, data, k, read)
    yield from _filled(c, part, k, read)


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
    may = k.places(group, c.places)
    fits = [p for p in may if p in on]
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


def _observed(c: Checking, part: Part, data: Study, k: Contract,
              read: list[FormulationDefinition]) -> Iterator[Issue]:
    """Each observable of the study's sets (models.md § 5.2), at its own key: a quantity the
    steps' formulations derive, a group the component promises, a point with one length per axis
    of its frame, a side that is a body, and a unit of its quantity — times what it is integrated
    over for an integral. Its name once across the sets is the study's own."""
    derived = {q: d for f in read for q, d in f.derived.items()}
    bodies = [g for g, d in k.groups.items() if d == k.dimension]
    comp = k.part.address.name
    seen: dict[str, str] = {}
    for set_name in data.observables:
        held = cites(c, "observables", set_name)
        observables = held.data.observables if held is not None else {}
        here = f"the study `{part.address.name}` pairs this set with the component `{comp}`"
        for name, o in observables.items():
            at = ("observables", name)
            if name in seen:
                yield c.issue(part, "observables", code="observable-twice", label=name,
                              message=f"the observable `{name}` is in both {seen[name]} and {set_name}")
            seen.setdefault(name, set_name)
            if isinstance(o, OverGroup):
                yield from _placed(c, held, (*at, "group"), k, o.group, here, f"`{name}`", None, {})
                if o.side is not None and o.side not in bodies:
                    yield c.issue(held, *at, "side", code="wrong-side", label=o.side, choices=bodies,
                                  message=f"`{name}` is read from the side `{o.side}`, which is no body `{comp}` "
                                          "promises" + meant(o.side, bodies))
            for point in points(o):
                if k.dimension is not None and len(point) != k.dimension:
                    yield c.issue(held, *at, support(o), code="wrong-point", label=name,
                                  message=f"{here}: `{name}` gives {len(point)} lengths for a point, and the frame of "
                                          f"`{comp}` has {k.dimension} axes")
                    break
            if read and o.quantity not in derived:
                yield c.issue(held, *at, "quantity", code="no-such-quantity", label=o.quantity,
                              choices=list(derived),
                              message=f"`{name}` reads `{o.quantity}`, which the physics of the study "
                                      f"`{part.address.name}` do not derive" + meant(o.quantity, derived))
            elif o.quantity in derived:
                yield from _unit(c, held, k, (*at, "unit"), name, o, derived[o.quantity].unit)


def _unit(c: Checking, held: Part, k: Contract, at: tuple[str, ...], name: str, o: Any, unit: str) -> Iterator[Issue]:
    """An observable's unit: one of its quantity, times the length, area or volume it is
    integrated over for an integral."""
    measure = 0
    if o.reduction == "integral" and isinstance(o, OverGroup):
        if o.group not in k.groups:
            return                                                  # its group's own finding says why
        measure = k.groups[o.group]
    elif o.reduction == "integral" and isinstance(o, AlongLine):
        measure = 1
    try:
        wanted = c.units.parse(unit) * Quantity(Fraction(1), LENGTH) ** measure
        given = c.units.parse(o.unit)
    except UnitError:
        return                                                      # the set's own finding says why
    if given.dimension != wanted.dimension:
        over = {1: " times a length", 2: " times an area", 3: " times a volume"}.get(measure, "")
        yield c.issue(held, *at, code="wrong-unit", label=o.unit,
                      message=f"`{name}` reads {o.quantity}, in {unit}{over}, and is reported in {o.unit}, which is "
                              "not a unit of that")


def _filled(c: Checking, part: Part, k: Contract, read: list[FormulationDefinition]) -> Iterator[Issue]:
    """Each material of the project's own the component assigns holds every property the steps'
    formulations read, said at the material's own key; one the project does not hold is the
    component's own finding (materials.md § 4)."""
    needed = sorted({p for f in read for p in f.properties})
    for group, assigned in k.assign.items():
        m = material(c.opened, assigned.material) if assigned.material is not None else None
        if m is None:
            continue
        held = datasets(c.opened, m)
        for prop in needed:
            if not held.get(prop):
                yield c.issue(m, "properties", prop, code="property-missing", label=prop,
                              message=f"the study `{part.address.name}` solves physics reading the {prop} of "
                                      f"`{group}` in `{k.part.address.name}`, which this material fills, and it "
                                      f"holds no {prop}")


KEY = "models.study"   # the key the layout names this schema by (projects.md § 4)
PART_SCHEMAS = {KEY: Study}
PART_CHECKS = {KEY: check}
