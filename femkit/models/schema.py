"""`model.toml` and `study.toml` (models.md § 3, § 5).

Loading checks the first tier of validity (models.md § 11.2): types, unknown keys, every
quantity read by the unit grammar (core.md § 11) and every reference naming an object that
exists. An incomplete model loads; what it lacks, and what the formulation does not allow,
are `model check`'s findings.

A reference field carries `ref` (core.md § 2); a value written as a quantity carries
`quantity`: `any` (a quantity, or an expression of the parameters), `length`, `coordinate`
(a bare number in the frame's unit, or a length), or `unit` (a unit text alone).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Any, Iterator, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from femkit.core.schema import Model, field_extras, references, refuse
from femkit.core.units import Quantity, UnitError, Units
from femkit.jobs.request import Resources

NAME = re.compile(r"[a-z][a-z0-9_]*")
LENGTH = (("length", 1),)

Number = Union[int, Decimal]
Coordinate = Union[int, Decimal, str]  # a bare number, in the frame's unit; or a length, or an expression


def as_quantity(description: str, kind: str = "any", **kw: Any) -> Any:
    return Field(description=description, json_schema_extra={"quantity": kind}, **kw)


def as_reference(description: str, target: str | dict, **kw: Any) -> Any:
    return Field(description=description, json_schema_extra={"ref": target}, **kw)


# ------------------------------------------------------------------ geometry

class Rectangle(Model):
    """An axis-aligned rectangle (2-D)."""
    kind: Literal["rectangle"]
    corner: list[Coordinate] = as_quantity("its lower corner", "coordinate", min_length=2, max_length=2)
    size: list[Coordinate] = as_quantity("its width and height", "coordinate", min_length=2, max_length=2)


class Disk(Model):
    """A disk (2-D)."""
    kind: Literal["disk"]
    center: list[Coordinate] = as_quantity("its center", "coordinate", min_length=2, max_length=2)
    radius: Coordinate = as_quantity("its radius", "coordinate")


class Polygon(Model):
    """A polygon (2-D), its vertices in order."""
    kind: Literal["polygon"]
    points: list[list[Coordinate]] = as_quantity("its vertices", "coordinate", min_length=3)


class Box(Model):
    """An axis-aligned box (3-D)."""
    kind: Literal["box"]
    corner: list[Coordinate] = as_quantity("its lower corner", "coordinate", min_length=3, max_length=3)
    size: list[Coordinate] = as_quantity("its extent along each axis", "coordinate", min_length=3, max_length=3)


class Sphere(Model):
    """A sphere (3-D)."""
    kind: Literal["sphere"]
    center: list[Coordinate] = as_quantity("its center", "coordinate", min_length=3, max_length=3)
    radius: Coordinate = as_quantity("its radius", "coordinate")


class Cylinder(Model):
    """A cylinder (3-D): the center of one end, its axis (length and direction), its radius."""
    kind: Literal["cylinder"]
    base: list[Coordinate] = as_quantity("the center of one end", "coordinate", min_length=3, max_length=3)
    axis: list[Coordinate] = as_quantity("from that end to the other", "coordinate", min_length=3, max_length=3)
    radius: Coordinate = as_quantity("its radius", "coordinate")


class Extrusion(Model):
    """A planar polygon swept along a vector (3-D)."""
    kind: Literal["extrusion"]
    profile: list[list[Coordinate]] = as_quantity("the polygon's vertices, in one plane", "coordinate", min_length=3)
    along: list[Coordinate] = as_quantity("the sweep", "coordinate", min_length=3, max_length=3)


class Combined(Model):
    """The union, difference (the first less the others) or intersection of named shapes."""
    kind: Literal["union", "difference", "intersection"]
    of: list[str] = as_reference("the shapes, by name", "shape", min_length=2)


class Imported(Model):
    """A CAD file the person supplies, under `custom/`, with its SHA-256."""
    kind: Literal["import"]
    file: str = Field(description="its path under the project's `custom/`")
    sha256: str = Field(pattern=r"[0-9a-f]{64}", description="its SHA-256")


Shape = Annotated[Union[Rectangle, Disk, Polygon, Box, Sphere, Cylinder, Extrusion, Combined, Imported],
                  Field(discriminator="kind")]


class Frame(Model):
    """The coordinates' frame: Cartesian, right-handed, its origin where coordinates are zero."""
    unit: str = as_quantity("the length unit a bare-number coordinate is in", "unit")


class Geometry(Model):
    """The dimension, what it means for the formulation, and the shapes."""
    dimension: Literal[2, 3] | None = Field(default=None, description="2 or 3")
    meaning: str | None = Field(default=None, description="what this dimension means, one of the formulation's "
                                                          "(`per unit depth`)")
    shapes: dict[str, Shape] = Field(default_factory=dict, description="each shape by name")


class Plane(Model):
    """A plane: a point on it and its normal."""
    point: list[Coordinate] = as_quantity("a point on it", "coordinate", min_length=2, max_length=3)
    normal: list[Number] = Field(min_length=2, max_length=3, description="its normal, a direction")


class Window(Model):
    """An axis-aligned box that selects the boundaries inside it."""
    corner: list[Coordinate] = as_quantity("its lower corner", "coordinate", min_length=2, max_length=3)
    size: list[Coordinate] = as_quantity("its extent", "coordinate", min_length=2, max_length=3)


RULES = {"shapes": "domain", "plane": "boundary", "box": "boundary", "faces_of": "boundary", "rest": "boundary",
         "between": "interface"}


class Region(Model):
    """A named domain, outer boundary or interface, selected by exactly one rule (models.md § 3)."""
    kind: Literal["domain", "boundary", "interface"]
    shapes: list[str] | None = as_reference("a domain: the named shapes", "shape", default=None, min_length=1)
    plane: Plane | None = Field(default=None, description="a boundary: the outer faces on this plane")
    box: Window | None = Field(default=None, description="a boundary: the outer faces inside this box")
    faces_of: str | None = as_reference("a boundary: the outer faces of this shape", "shape", default=None)
    rest: Literal[True] | None = Field(default=None, description="a boundary: the outer faces no other region selects")
    between: list[str] | None = as_reference("an interface: the two domains it lies between", "region:domain",
                                    default=None, min_length=2, max_length=2)

    @model_validator(mode="after")
    def _one_rule(self) -> "Region":
        given = [r for r in RULES if getattr(self, r) is not None]
        if len(given) != 1:
            raise ValueError(f"give exactly one selection rule: {', '.join(RULES)}")
        if RULES[given[0]] != self.kind:
            raise ValueError(f"`{given[0]}` selects a {RULES[given[0]]}, not a {self.kind}")
        return self


# ------------------------------------------------------------------ physics

class Variable(Model):
    """The independent variable of a tabulated property."""
    name: str = Field(description="what it is (`wavelength`)")
    unit: str = as_quantity("the unit its column is in", "unit")


class Property(Model):
    """One material property: a constant or a table, with what it rests on (models.md § 3)."""
    value: str | None = as_quantity("a constant, with its unit where it has one", default=None)
    table: str | None = Field(default=None, description="a table under `custom/`: the variable, then the value's "
                                                        "real and imaginary parts")
    sha256: str | None = Field(default=None, pattern=r"[0-9a-f]{64}", description="the table's SHA-256")
    variable: Variable | None = Field(default=None, description="the table's independent variable")
    interpolation: Literal["linear"] | None = Field(default=None, description="between the table's rows")
    convention: Literal["real", "exp(-iwt)", "exp(+iwt)"] | None = Field(
        default=None, description="the complex-value convention of the source data")
    source: str | None = Field(default=None, description="where the data comes from")
    range: Literal["all"] | list[str] | None = Field(default=None, description="where it is valid: `all`, or "
                                                     "`[from, to]` in its variable", json_schema_extra={"quantity": "any"})

    @model_validator(mode="after")
    def _one_form(self) -> "Property":
        if self.value is not None and self.table is not None:
            raise ValueError("give a `value` or a `table`, not both")
        if isinstance(self.range, list) and len(self.range) != 2:
            raise ValueError("`range` is `all` or `[from, to]`")
        return self


class Conventions(Model):
    """What the formulation requires to be chosen; never defaulted."""
    phasor: Literal["exp(-iwt)", "exp(+iwt)"] | None = Field(default=None, description="the phasor's time factor")
    amplitude: Literal["peak", "rms"] | None = Field(default=None, description="whether amplitudes are peak or RMS")


class Kinded(Model):
    """A condition or source: its kind and the parameters the formulation lists for it, each
    a quantity; checked against the formulation by `model check`."""
    model_config = ConfigDict(extra="allow", frozen=True)  # its parameters are the formulation's, not the schema's
    kind: str = Field(description="one of the formulation's kinds")


class Condition(Kinded):
    """What holds on a boundary or interface."""


class Source(Kinded):
    """An excitation, attached to a region."""
    on: str = as_reference("the region it acts in or on", "region")


class Radiation(Model):
    """For an open problem: where waves leave, and the medium beyond."""
    boundaries: list[str] = as_reference("the outer boundaries waves leave through", "region:boundary", min_length=1)
    background: str | None = as_reference("the medium beyond them", "material", default=None)


class ModelFile(Model):
    """`model.toml`: the physics, and nothing about an engine (models.md § 3)."""
    schema_: Literal[1] = Field(alias="schema", description="this file's shape; raised when it changes")
    formulation: str | None = Field(default=None, description="one formulation ID (models.md § 4)")
    parameters: dict[str, str] = Field(default_factory=dict, description="each named quantity, or an expression of "
                                       "the ones above it", json_schema_extra={"quantity": "any"})
    frame: Frame | None = Field(default=None, description="the coordinates' unit")
    geometry: Geometry | None = Field(default=None, description="the dimension, its meaning, the shapes")
    regions: dict[str, Region] = Field(default_factory=dict, description="each named region")
    materials: dict[str, dict[str, Property]] = Field(default_factory=dict, description="each material, by its "
                                                      "properties")
    assign: dict[str, str] = as_reference("a material for each domain region", {"key": "region:domain", "value": "material"},
                                 default_factory=dict)
    conventions: Conventions | None = Field(default=None, description="the conventions the formulation requires")
    conditions: dict[str, Condition] = as_reference("a condition for each outer boundary and named interface",
                                           {"key": "region:boundary|region:interface"}, default_factory=dict)
    radiation: Radiation | None = Field(default=None, description="for an open problem")
    sources: dict[str, Source] = Field(default_factory=dict, description="each excitation, by name")

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _first_tier(self, info: ValidationInfo) -> "ModelFile":
        units = _units(info)
        problems: list[tuple[tuple, str]] = []
        problems += _names(self)
        values = _parameters(self, units, problems)
        if self.frame is not None:
            _unit_of(units, self.frame.unit, LENGTH, ("frame", "unit"), problems)
        problems += [p for p in _quantities(self, units, values) if p[0] != ("frame", "unit")]
        problems += _references(self, objects(self))
        refuse("ModelFile", problems)
        return self

    def parameter_values(self, units: Units) -> dict[str, Quantity]:
        problems: list = []
        return _parameters(self, units, problems)


# ------------------------------------------------------------------ the study

class Element(Model):
    """The element family and its degree."""
    family: str = Field(description="`lagrange`, `nedelec`, …: mapped per environment (models.md § 6.4)")
    degree: int = Field(ge=1, description="its polynomial degree")


class Mesh(Model):
    """The mesh policy (models.md § 6.5)."""
    unit: str | None = as_quantity("the length unit geometry is handed to the mesher in", "unit", default=None)
    size: str | None = as_quantity("the largest element size", "length", default=None)
    regions: dict[str, str] = Field(default_factory=dict, description="a size for each named region",
                                    json_schema_extra={"ref": {"key": "region"}, "quantity": "length"})


class Solver(Model):
    """The linear solver."""
    kind: Literal["direct", "iterative"] = Field(description="direct or iterative")
    tolerance: str | None = as_quantity("an iterative solver's relative tolerance, a plain number", default=None)


class Numerics(Model):
    """Everything numerical that is not an environment's own choice."""
    element: Element | None = Field(default=None, description="the element family and degree")
    geometry_order: int | None = Field(default=None, ge=1, description="the order of the geometry's elements")
    mesh: Mesh | None = Field(default=None, description="the mesh policy")
    solver: Solver | None = Field(default=None, description="the linear solver")


class Axis(Model):
    """What one axis varies, keyed by the case path it varies."""
    class_: Literal["numerical convergence", "geometry convergence", "physical sweep"] = Field(
        alias="class", description="its class (models.md § 5)")
    values: list[Union[int, Decimal, str]] = Field(min_length=1, description="the values, in order",
                                                   json_schema_extra={"quantity": "any"})
    model_config = ConfigDict(populate_by_name=True)


class Support(Model):
    """Where an observable is read: a point, a line, or a region."""
    point: list[Coordinate] | None = as_quantity("a point", "coordinate", default=None, min_length=2, max_length=3)
    line: list[list[Coordinate]] | None = as_quantity("a line, from its first point to its second", "coordinate",
                                                   default=None, min_length=2, max_length=2)
    region: str | None = as_reference("a region", "region", default=None)

    @model_validator(mode="after")
    def _one(self) -> "Support":
        if sum(x is not None for x in (self.point, self.line, self.region)) != 1:
            raise ValueError("give exactly one of `point`, `line`, `region`")
        return self


class Observable(Model):
    """A number the study reports (models.md § 5)."""
    quantity: str = Field(description="a quantity the formulation derives")
    support: Support = Field(description="where it is read")
    reduction: Literal["value", "average", "integral", "maximum", "norm"] = Field(description="how it is reduced")
    unit: str | None = as_quantity("the unit it is reported in", "unit", default=None)
    side: str | None = as_reference("on an interface, the domain it is read from", "region:domain", default=None)


class Binding(Model):
    """What a study binds for one environment (models.md § 5)."""
    mesher: str | None = Field(default=None, description="its mesher, or the study's shared one")
    resources: Resources | None = Field(default=None, description="its job's resources (jobs.md § 2)")


AXIS_PATH = re.compile(r"(parameters\.[a-z][a-z0-9_]*|numerics(\.[a-z_]+)+)")


class StudyFile(Model):
    """`studies/<study>/study.toml`: everything that is not the physics (models.md § 5)."""
    schema_: Literal[1] = Field(alias="schema", description="this file's shape; raised when it changes")
    display: list[str] = Field(default_factory=list, description="units numbers are shown in, the first of each "
                               "dimension", json_schema_extra={"quantity": "unit"})
    numerics: Numerics | None = Field(default=None, description="the numerics every case shares")
    axes: dict[str, Union[Axis, str]] = Field(default_factory=dict, description="each axis, keyed by the case path "
                                              "it varies; `reason`: why axes of different classes are crossed")
    observables: dict[str, Observable] = Field(default_factory=dict, description="each observable, by name")
    environments: dict[str, Binding] = Field(default_factory=dict, description="each engine environment's bindings")

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _first_tier(self, info: ValidationInfo) -> "StudyFile":
        units = _units(info)
        model: ModelFile | None = (info.context or {}).get("model")
        problems: list[tuple[tuple, str]] = []
        for key, axis in self.axes.items():
            if key == "reason":
                if not isinstance(axis, str):
                    problems.append((("axes", key), "the reason is a sentence"))
            elif not AXIS_PATH.fullmatch(key):
                problems.append((("axes", key), "an axis varies `parameters.<name>` or `numerics.<path>` only"))
            elif isinstance(axis, str):
                problems.append((("axes", key), "an axis is a table: its class and values"))
            elif key.startswith("parameters.") and model is not None and key.split(".", 1)[1] not in model.parameters:
                problems.append((("axes", key), f"the model has no parameter {key.split('.', 1)[1]!r}"))
        for name in self.observables:
            if not NAME.fullmatch(name):
                problems.append((("observables", name), "a name matches [a-z][a-z0-9_]*"))
        values = model.parameter_values(units) if model is not None else {}
        problems += _quantities(self, units, values)
        if model is not None:
            problems += _references(self, objects(model))
        refuse("StudyFile", problems)
        return self


# ------------------------------------------------------------------ the first tier

def _units(info: ValidationInfo) -> Units:
    units = (info.context or {}).get("units")
    if units is None:
        raise ValueError("loaded without the unit table: load it through femkit.models.project")
    return units


def _names(m: ModelFile) -> list[tuple[tuple, str]]:
    tables = {"parameters": m.parameters, "regions": m.regions, "materials": m.materials, "sources": m.sources}
    if m.geometry is not None:
        tables["geometry.shapes"] = m.geometry.shapes
    out = []
    for where, table in tables.items():
        for name in table:
            if not NAME.fullmatch(name):
                out.append(((*where.split("."), name), "a name matches [a-z][a-z0-9_]*"))
    return out


def _parameters(m: ModelFile, units: Units, problems: list) -> dict[str, Quantity]:
    """Each parameter's exact value, in order: an expression may use only the ones above it."""
    values: dict[str, Quantity] = {}
    symbols = set(units.symbols())
    for name, text in m.parameters.items():
        if name in symbols:
            problems.append((("parameters", name), f"{name!r} is a unit; a parameter is never named like one"))
            continue
        try:
            values[name] = units.parse(text, values)
        except UnitError as exc:
            problems.append((("parameters", name), str(exc)))
    return values


def _unit_of(units: Units, text: str, dimension: tuple, at: tuple, problems: list) -> bool:
    try:
        q = units.parse(text)
    except UnitError as exc:
        problems.append((at, str(exc)))
        return False
    if dimension is not None and q.dimension != dimension:
        problems.append((at, f"{text!r} is not a unit of length"))
        return False
    return True


def quantities(instance: BaseModel, at: tuple = ()) -> Iterator[tuple[tuple, str, Any]]:
    """Every value written as a quantity, as ``(location, kind, value)``, from its field's
    `quantity` annotation; a table's values, a list's items, a point's coordinates each apart."""
    for name, field in type(instance).model_fields.items():
        value = getattr(instance, name)
        key = field.alias or name
        kind = field_extras(field).get("quantity")
        if kind is not None and value is not None:
            yield from _leaves(value, (*at, key), kind)
        for loc, item in _models(value, (*at, key)):
            yield from quantities(item, loc)
    if isinstance(instance, Kinded):
        for key, value in (instance.model_extra or {}).items():
            yield from _leaves(value, (*at, key), "parameter")


def _leaves(value: Any, at: tuple, kind: str) -> Iterator[tuple[tuple, str, Any]]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _leaves(v, (*at, k), kind)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _leaves(v, (*at, i), kind)
    elif value != "all" or kind != "any":
        yield at, kind, value


def _models(value: Any, at: tuple) -> Iterator[tuple[tuple, BaseModel]]:
    if isinstance(value, BaseModel):
        yield at, value
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            yield from _models(item, (*at, i))
    elif isinstance(value, dict):
        for k, item in value.items():
            yield from _models(item, (*at, k))


def _quantities(instance: BaseModel, units: Units, names: dict[str, Quantity]) -> list[tuple[tuple, str]]:
    """Every quantity reads by the grammar; a length is a length; a unit is a unit."""
    out = []
    for at, kind, value in quantities(instance):
        if kind == "parameter" or (at and at[0] == "parameters"):
            continue  # a condition's parameters are the formulation's to judge (model check); parameters are read above
        if not isinstance(value, str):
            if kind == "coordinate" or isinstance(value, (int, Decimal)):
                continue  # a bare number: in the frame's unit, or a plain number
            out.append((at, "a quantity is written as text, with its unit (`\"1 nm\"`)"))
            continue
        try:
            q = units.parse(value, {} if kind == "unit" else names)
        except UnitError as exc:
            out.append((at, str(exc)))
            continue
        if kind in ("length", "coordinate") and q.dimension != LENGTH:
            out.append((at, f"{value!r} is not a length"))
    return out


def objects(m: ModelFile) -> dict[str, set[str]]:
    """The names each reference type may take, in this model."""
    found = {"shape": set(m.geometry.shapes) if m.geometry else set(), "material": set(m.materials),
             "parameter": set(m.parameters), "region": set(m.regions)}
    for kind in ("domain", "boundary", "interface"):
        found[f"region:{kind}"] = {n for n, r in m.regions.items() if r.kind == kind}
    return found


def _references(instance: BaseModel, known: dict[str, set[str]]) -> list[tuple[tuple, str]]:
    out = []
    for at, target, name, _held in references(instance):
        options = target.split("|")
        if any(o not in known for o in options):
            continue  # resolved against the formulation, by model check
        if not any(name in known[o] for o in options):
            out.append((at, f"no {' or '.join(options)} is named {name!r}"))
    return out
