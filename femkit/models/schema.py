"""`model.toml` and `study.toml` (models.md § 3, § 5).

Loading checks the first tier of validity (models.md § 11.1): types, unknown keys, every
quantity read by the unit grammar (core.md § 11) and every reference naming an object that
exists. An incomplete model loads; what it lacks, and what the formulation does not allow,
are `model check`'s findings.

A reference field carries `ref` (core.md § 2); a value written as a quantity carries
`quantity`: `any` (a quantity, or an expression of the parameters), `length`, `coordinate`
(a bare number in the frame's unit, or a length), or `unit` (a unit text alone). A field that
belongs to one type of its object carries `for` — a region's selection rule, the kind it selects;
a field a file may leave out but `model check` asks for carries `stated`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Iterator, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator
from pydantic.fields import FieldInfo

from femkit.core.schema import (DIMENSIONS, LENGTH, SHA256, Model, as_quantity, as_reference, classes, closed,
                                field_extras, field_named, matching, references, refuse, values_of)
from femkit.core.units import Quantity, UnitError, Units
from femkit.jobs.request import Resources

NAME = re.compile(r"[a-z][a-z0-9_]*")
STUDY = re.compile(r"[a-z][a-z0-9_-]*")  # a study's name: its folder's

Number = Union[int, Decimal]
Coordinate = Union[int, Decimal, str]  # a bare number, in the frame's unit; or a length, or an expression


# ------------------------------------------------------------------ geometry

SHAPE_KIND = Field(description="what shape it is")

class Rectangle(Model):
    """An axis-aligned rectangle (2-D)."""
    dimension: ClassVar[int | None] = 2  # the dimension it is drawn in
    kind: Literal["rectangle"] = SHAPE_KIND
    corner: list[Coordinate] = as_quantity("its lower corner", "coordinate", min_length=2, max_length=2)
    size: list[Coordinate] = as_quantity("its width and height", "coordinate", min_length=2, max_length=2)


class Disk(Model):
    """A disk (2-D)."""
    dimension: ClassVar[int | None] = 2  # the dimension it is drawn in
    kind: Literal["disk"] = SHAPE_KIND
    center: list[Coordinate] = as_quantity("its center", "coordinate", min_length=2, max_length=2)
    radius: Coordinate = as_quantity("its radius", "coordinate")


class Polygon(Model):
    """A polygon (2-D), its vertices in order."""
    dimension: ClassVar[int | None] = 2  # the dimension it is drawn in
    kind: Literal["polygon"] = SHAPE_KIND
    points: list[list[Coordinate]] = as_quantity("its vertices", "coordinate", min_length=3)


class Box(Model):
    """An axis-aligned box (3-D)."""
    dimension: ClassVar[int | None] = 3  # the dimension it is drawn in
    kind: Literal["box"] = SHAPE_KIND
    corner: list[Coordinate] = as_quantity("its lower corner", "coordinate", min_length=3, max_length=3)
    size: list[Coordinate] = as_quantity("its extent along each axis", "coordinate", min_length=3, max_length=3)


class Sphere(Model):
    """A sphere (3-D)."""
    dimension: ClassVar[int | None] = 3  # the dimension it is drawn in
    kind: Literal["sphere"] = SHAPE_KIND
    center: list[Coordinate] = as_quantity("its center", "coordinate", min_length=3, max_length=3)
    radius: Coordinate = as_quantity("its radius", "coordinate")


class Cylinder(Model):
    """A cylinder (3-D): the center of one end, its axis (length and direction), its radius."""
    dimension: ClassVar[int | None] = 3  # the dimension it is drawn in
    kind: Literal["cylinder"] = SHAPE_KIND
    base: list[Coordinate] = as_quantity("the center of one end", "coordinate", min_length=3, max_length=3)
    axis: list[Coordinate] = as_quantity("from that end to the other", "coordinate", min_length=3, max_length=3)
    radius: Coordinate = as_quantity("its radius", "coordinate")


class Extrusion(Model):
    """A planar polygon swept along a vector (3-D)."""
    dimension: ClassVar[int | None] = 3  # the dimension it is drawn in
    kind: Literal["extrusion"] = SHAPE_KIND
    profile: list[list[Coordinate]] = as_quantity("the polygon's vertices, in one plane", "coordinate", min_length=3)
    along: list[Coordinate] = as_quantity("the sweep", "coordinate", min_length=3, max_length=3)


class Combined(Model):
    """The union, difference (the first less the others) or intersection of named shapes."""
    dimension: ClassVar[int | None] = None  # the dimension it is drawn in; none: its parts'
    kind: Literal["union", "difference", "intersection"] = SHAPE_KIND
    of: list[str] = as_reference("the shapes, by name", "shape", min_length=2)


class Imported(Model):
    """A CAD file the person supplies, under `custom/`, with its SHA-256."""
    dimension: ClassVar[int | None] = None  # the dimension it is drawn in; none: its parts'
    kind: Literal["import"] = SHAPE_KIND
    file: str = Field(description="its path under the project's `custom/`")
    sha256: str = matching(SHA256, description="its SHA-256")


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


class Region(Model):
    """A named domain, outer boundary or interface, selected by exactly one rule (models.md § 3)."""
    kind: Literal["domain", "boundary", "interface"] = Field(description="a domain, an outer boundary or an interface")
    shapes: list[str] | None = as_reference("the named shapes", "shape", default=None, min_length=1,
                                            extra={"for": "domain"})
    plane: Plane | None = Field(default=None, description="the outer faces on this plane",
                                json_schema_extra={"for": "boundary"})
    box: Window | None = Field(default=None, description="the outer faces inside this box",
                               json_schema_extra={"for": "boundary"})
    faces_of: str | None = as_reference("the outer faces of this shape", "shape", default=None,
                                        extra={"for": "boundary"})
    rest: Literal[True] | None = Field(default=None, description="the outer faces no other region selects",
                                       json_schema_extra={"for": "boundary"})
    between: list[str] | None = as_reference("the two domains it lies between", "region:domain",
                                             default=None, min_length=2, max_length=2, extra={"for": "interface"})

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


#: Each selection rule and the region kind it selects: the `for` of Region's fields.
RULES = {(f.alias or n): field_extras(f)["for"] for n, f in Region.model_fields.items() if "for" in field_extras(f)}


class Property(Model):
    """One material property: a constant or a table, with what it rests on (models.md § 3)."""
    value: str | None = as_quantity("a constant, with its unit where it has one", default=None)
    table: str | None = Field(default=None, description="a table under `custom/`: the variable, then the value's "
                                                        "real and imaginary parts")
    sha256: str | None = matching(SHA256, default=None, description="the table's SHA-256")
    variable: Variable | None = Field(default=None, description="the table's independent variable")
    interpolation: Literal["linear"] | None = Field(default=None, description="between the table's rows")
    convention: Literal["real", "exp(-iwt)", "exp(+iwt)"] | None = Field(
        default=None, description="the complex-value convention of the source data", json_schema_extra={"stated": True})
    source: str | None = Field(default=None, description="where the data comes from", json_schema_extra={"stated": True})
    range: Literal["all"] | list[str] | None = Field(default=None, description="where it is valid: `all`, or "
                                                     "`[from, to]` in its variable",
                                                     json_schema_extra={"quantity": "any", "stated": True})

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
    formulation: str | None = Field(default=None, description="one formulation ID", json_schema_extra={"doc": "models.md § 4"})
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
    family: str = Field(description="`lagrange`, `nedelec`, …: mapped per environment", json_schema_extra={"doc": "models.md § 6.4"})
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
        alias="class", description="its class", json_schema_extra={"doc": "models.md § 5"})
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
    resources: Resources | None = Field(default=None, description="its job's resources", json_schema_extra={"doc": "jobs.md § 2"})


AXIS_PATH = re.compile(rf"(parameters\.{NAME.pattern}|numerics(\.[a-z_]+)+)")


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
                problems.append((("observables", name), f"a name matches {NAME.pattern}"))
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
                out.append(((*where.split("."), name), f"a name matches {NAME.pattern}"))
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
        if kind in DIMENSIONS and q.dimension != DIMENSIONS[kind]:
            out.append((at, f"{value!r} is not a length"))
    return out


# ------------------------------------------------------------------ the object types (models.md § 11.2)

@dataclass(frozen=True)
class ObjectType:
    """One type of object of the model or a study, declared once: edits, the graph, the checks,
    the palette and the page all read this table, so where an object lives, what names it,
    where its types are declared and its place in the chain's order are written nowhere else."""

    kind: str                       # what a person calls it: `region`
    file: Literal["model", "study"]
    table: tuple[str, ...]          # where its entries live; for a single object, where it lives
    many: bool                      # entries by key; else one object
    named: bool                     # its key is a name that `model rename` takes
    typed: str | None               # the field holding its type within the kind: `kind` of a region
    rank: int                       # its place in the chain's order: what it is made from comes first
    label: str = "{name}"           # what a person calls an entry: `{name}`, `{type}` and `{kind}` filled
    declared: str | None = None     # the formulation's table declaring its types: `conditions`; with no
    #                                 `typed` field, an entry holds one value per type, by key (a material)
    palette: bool = False           # the palette offers to add one

    def root(self) -> type[BaseModel]:
        return ModelFile if self.file == "model" else StudyFile

    def entries(self, root: BaseModel) -> dict[str, Any]:
        """Its entries in a loaded file — for a single object, its one entry under its key."""
        held: Any = root
        for step in self.table:
            if isinstance(held, BaseModel):
                found = field_named(type(held), step)
                held = getattr(held, found[0]) if found else None
            else:
                held = (held or {}).get(step)
        if not self.many:
            return {} if held is None else {self.table[-1]: held}
        return dict(held or {})

    def field(self) -> FieldInfo:
        """The field that holds it: the table's, or the single object's."""
        cls: type[BaseModel] = self.root()
        found = None
        for step in self.table:
            found = field_named(cls, step)
            cls = next(iter(classes(found[1].annotation)), cls)
        return found[1]

    def entry(self) -> Any:
        """The annotation of one entry."""
        annotation = self.field().annotation
        return values_of(annotation) if self.many else annotation

    def type_of(self, value: Any) -> str | None:
        if self.typed is None or not isinstance(value, BaseModel):
            return None
        found = field_named(type(value), self.typed)
        return getattr(value, found[0], None) if found else None

    def keyed_by(self) -> list[str]:
        """What its key names, when the key is another object's name: the table's `ref` key
        (a condition's key is its region's)."""
        ref = field_extras(self.field()).get("ref")
        return ref["key"].split("|") if isinstance(ref, dict) and "key" in ref and "value" not in ref else []

    def types(self, formulation: Any = None) -> list[str]:
        """Every type its entries may have: the formulation's, where it declares them, else the
        closed values of the field ``typed`` names, across the classes an entry may be."""
        if self.declared is not None:
            return list(getattr(formulation, self.declared, None) or {})
        if self.typed is None:
            return []
        out: list[str] = []
        for cls in classes(self.entry()):
            found = field_named(cls, self.typed)
            out += closed(found[1].annotation) if found else []
        return list(dict.fromkeys(out))

    def variant(self, type_: str | None) -> type[BaseModel] | None:
        """The class an entry of ``type_`` is: the one whose typed field allows it, or the one
        class there is; for one value per type, that value's class."""
        options = classes(values_of(self.entry())) if self.declared and self.typed is None else classes(self.entry())
        if self.typed is not None and type_ is not None and len(options) > 1:
            options = [c for c in options if (f := field_named(c, self.typed)) and type_ in closed(f[1].annotation)]
        return options[0] if len(options) == 1 else None

    def label_of(self, key: str, value: Any = None) -> str:
        return self.label.format(name=key, type=self.type_of(value), kind=self.kind)


OBJECTS: tuple[ObjectType, ...] = (
    ObjectType("parameter", "model", ("parameters",), many=True, named=True, typed=None, rank=0, palette=True),
    ObjectType("frame", "model", ("frame",), many=False, named=False, typed=None, rank=0),
    ObjectType("geometry", "model", ("geometry",), many=False, named=False, typed=None, rank=0),
    ObjectType("conventions", "model", ("conventions",), many=False, named=False, typed=None, rank=0),
    ObjectType("shape", "model", ("geometry", "shapes"), many=True, named=True, typed="kind", rank=1),
    ObjectType("region", "model", ("regions",), many=True, named=True, typed="kind", rank=2, palette=True),
    ObjectType("material", "model", ("materials",), many=True, named=True, typed=None, rank=3,
               declared="properties", palette=True),
    ObjectType("condition", "model", ("conditions",), many=True, named=False, typed="kind", rank=3,
               label="{type} on {name}", declared="conditions", palette=True),
    ObjectType("source", "model", ("sources",), many=True, named=True, typed="kind", rank=3, declared="sources",
               palette=True),
    ObjectType("radiation", "model", ("radiation",), many=False, named=False, typed=None, rank=3),
    ObjectType("numerics", "study", ("numerics",), many=False, named=False, typed=None, rank=4),
    ObjectType("axis", "study", ("axes",), many=True, named=False, typed="class", rank=4),
    ObjectType("observable", "study", ("observables",), many=True, named=True, typed="quantity", rank=4,
               declared="derived", palette=True),
    ObjectType("binding", "study", ("environments",), many=True, named=True, typed=None, rank=4),
)


def object_type(kind: str) -> ObjectType:
    return next(o for o in OBJECTS if o.kind == kind)


def locate(file: Literal["model", "study"], path: tuple) -> tuple[ObjectType, str | None] | None:
    """The object a location lies in — the type whose object holds it most closely — and the
    entry's key, none for a single object; for a location that is a table of entries itself and
    in no object, that table's type with no key."""
    path = tuple(str(p) for p in path)
    fits = [o for o in OBJECTS if o.file == file and path[:len(o.table)] == o.table]
    inside = [o for o in fits if not o.many or len(path) > len(o.table)]
    best = max(inside or fits, key=lambda o: len(o.table), default=None)
    if best is None:
        return None
    return best, (path[len(best.table)] if best.many and len(path) > len(best.table) else None)


def objects(m: ModelFile) -> dict[str, set[str]]:
    """The names each reference type may take, in this model: an object type's kind, and with
    its type, `region:domain`."""
    found: dict[str, set[str]] = {}
    for o in OBJECTS:
        if o.file != "model" or not o.named:
            continue
        found[o.kind] = set()
        for t in o.types():
            found[f"{o.kind}:{t}"] = set()
        for name, value in o.entries(m).items():
            found.setdefault(o.kind, set()).add(name)
            if (t := o.type_of(value)) is not None:
                found.setdefault(f"{o.kind}:{t}", set()).add(name)
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
