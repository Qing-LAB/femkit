"""A material's file, `materials/<name>/material.toml` (materials.md § 3), its rules and its check.

A material holds each property by its name in the property list (§ 1), and each property one or
more datasets, each named by its source. A dataset is exactly one of three forms, told by the one
key of `FORMS` it states — one stating none, or several, does not load: a `value`, a real
constant; a `table`, a file beside this one with its digest, the variable its first column is
written in and how it is read between rows; a `model`, a dispersion model of femkit's list (§ 2)
with its parameters. Every dataset states its `convention`, `source` and `range` — `stated`
fields (core.md § 2): a file being written may lack them, and `project check` asks for each —
and, where they matter, the `temperature` its data holds at and the `uncertainty` its source
gives. Its value, its range's bounds, its temperature and its model's parameters are quantities
in the one form (core.md § 11) — `{value, unit}`, a plain number where it has no unit, a range's
two bounds `{value = [from, to], unit}` — naming no definition, since a material cites nothing
(projects.md § 3): the `quantity` kind `constant` (core.md § 2), read exactly by `quantity`. A
table's file is read by `rows`, the one reader of its shape.

A dataset held under an equivalent form answers the property it is a form of (§ 1): `answering`
is the one reading of which dataset answers which property, and `varies_with` of the variable a
dataset varies with (§ 6).

The rules a dataset keeps are written once, here, as `faults`: what `project check` finds on a
material, and what a case taking the dataset refuses (materials.md § 6; femkit/materials/data.py)
— the same rules, the same codes, never one trusting the other. Each fault is at its key from the
dataset's own (core.md § 10):
- `bad-quantity`: a value, a range, a temperature, a unit or a model's parameter that does not
  read as a quantity in the one form — a text saying the table to write — or a range of other than
  two bounds (core.md § 11);
- `wrong-dimension`: a value outside its property's dimension; a table's unit, a range, a
  temperature or a model's parameter outside the dimensions it may have — for a unit, the units
  of its variable's dimension its choices;
- `wrong-sign`, at `parameters.<p>`: a model's parameter of another sign than its model declares
  (material-data.md § 6.2);
- `not-stated`: a dataset missing a stated field, or a table its `sha256` — the file's digest its
  right value — at that field's key;
- `bad-table`, at `table`: a table's file not of the shape § 3 states, naming its line (one not
  there, or that cannot be read, is the door's finding);
- `active`, at `table`: a complex table's row whose loss has the sign of a material that gives
  energy under its convention, naming the row (material-data.md § 2);
- `digest-differs`, at `sha256`: a table whose file's SHA-256 is not the one stated — the digest
  it has now its right value; said once the file reads and holds passive data, so the digest
  offered is that of a table that reads;
- `no-such-variable`, at `variable.name`: a variable its property's data does not vary with —
  the property's variables its choices;
- `outside-table`, at `range`: a table's range of `all`, or one beyond its first and last rows,
  naming the rows' extent; `range-reversed`, at `range`: a table's range whose first bound is not
  below its second, naming the rows' extent;
- `no-such-model`, at `model`: a model the list lacks, or one that gives another property than
  the one its dataset is held under — the models giving this property its choices;
- `parameter-missing`, `no-such-parameter`, at `parameters.<p>`: a parameter of its model not
  given; one its model does not have — its model's its choices;
- `wrong-convention`, at `convention`: a model's dataset stating another convention than its
  model is written in — the model's its right value.

The check of a material alone (models.md § 11.1) finds each, and `dataset-twice`, at
`properties.<form>.<dataset>`: one dataset's name held under a property and under its equivalent
form, naming both.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from fractions import Fraction
from typing import Annotated, Any, Iterator, Literal, Mapping, NamedTuple, Sequence, Union

from pydantic import BaseModel, Discriminator, Field, Tag, create_model

from femkit.core import persist
from femkit.core.issues import Issue
from femkit.core.schema import (SHA256, DeclaredKey, Measure, Measured, Model, NumberOrName, as_quantity,
                                as_reference, field_extras, matching, written_keys)
from femkit.core.units import Dimension, Quantity, UnitError, Units, decimal, number
from femkit.definitions.dispersion import (CONDITIONS, REAL, SIGNS, Convention, Dispersion, DispersionModel, Parameter,
                                           Sign, active)
from femkit.definitions.properties import Property
from femkit.projects.checking import Checking, Registration
from femkit.projects.door import Held, Part
from femkit.projects.layout import held as holding
from femkit.projects.schemas import PartFile

KEY = "materials.material"   # the key the layout names this schema by (projects.md § 4)
PROPERTIES = "properties"    # the table holding each property, by its name in the property list
PARAMETERS = "parameters"    # a model's dataset's table of its parameters, by name (materials.md § 3)


#: What every dataset states, whatever its form (materials.md § 3), in this order: its convention,
#: source and range; the value of each variable its data holds at — a key for each of
#: `CONDITIONS`, named as its variable is (materials.md §§ 2, 3), made from that one declaration;
#: and the uncertainty its source gives.
Stated = create_model(
    "Stated", __base__=Model, __module__=__name__,
    __doc__="What every dataset states, whatever its form (materials.md § 3).",
    convention=(Convention | None, Field(default=None, description="the convention of the source's complex values",
                                         json_schema_extra={"stated": True})),
    source=(str | None, Field(default=None, description="where the data comes from: a citation a reader can check, "
                                                        "with its DOI where there is one",
                              json_schema_extra={"stated": True})),
    range=(Literal["all"] | Measure[list[NumberOrName]] | None, as_quantity(
        "where the data holds: `all`, or `{value = [from, to], unit = \"…\"}` in its variable", "constant",
        default=None, extra={"stated": True})),
    **{name: (Measured | None, as_quantity(f"the {name} its data holds at, where it matters", "constant",
                                           default=None))
       for name in CONDITIONS},
    uncertainty=(str | None, Field(default=None, description="the uncertainty its source gives, as the source "
                                                             "gives it")),
)


class Value(Stated):
    """A dataset that is a real constant (materials.md § 3)."""

    value: Measured = as_quantity("a real constant: `{value, unit}`, a plain number where it has no unit", "constant")


class Column(Model):
    """A table's first column: the variable it is written in, and its unit (materials.md § 3)."""

    name: str = Field(description="the variable, by its name in femkit's list of variables")
    unit: str = as_quantity("the unit its column is written in, of the variable's dimension", "unit")


class Table(Stated):
    """A dataset that is a table: a file beside the material's own (materials.md § 3)."""

    table: str = as_reference("the file holding it, by its path from the material's folder: comma-separated, a first "
                              "row naming its columns, then one row per point, the variable increasing", "file")
    sha256: str | None = matching(SHA256, default=None, description="its file's SHA-256, so a table changed under "
                                                                     "its material is seen")
    variable: Column = Field(description="the variable its first column is written in, and that column's unit")
    interpolation: Literal["linear"] = Field(description="how it is read between two rows",
                                             json_schema_extra={"doc": "material-data.md § 5"})


#: A dispersion model's parameter as a file writes it: a quantity in the one form, or, for a list of
#: terms the model sums, a list of tables of them.
ParameterValue = Union[Measured, list[dict[str, Measured]]]


class Modelled(Stated):
    """A dataset that is a dispersion model with its parameters (materials.md §§ 2, 3)."""

    model: str = Field(description="the dispersion model, by its name in femkit's list of models",
                       json_schema_extra={"doc": "materials.md § 2"})
    parameters: dict[str, ParameterValue] = as_quantity(
        "its parameters, each by its name in its model's declaration: a quantity in a dimension it declares, or, for "
        "a list of terms the model sums, a list of tables of them", "constant", default_factory=dict)


#: The three forms of a dataset, each by the key that states it: a dataset states exactly one.
FORMS: dict[str, type[Stated]] = {"value": Value, "table": Table, "model": Modelled}


def _form(value: Any) -> str | None:
    """Which form a dataset is: the one key of `FORMS` it states; None for none or several."""
    given = [key for key in FORMS if holding(value, key) is not None]
    return given[0] if len(given) == 1 else None


Dataset = Annotated[Union[tuple(Annotated[model, Tag(key)] for key, model in FORMS.items())],
                    Discriminator(_form, custom_error_type="dataset-form",
                                  custom_error_message="a dataset is exactly one of `value`, `table` and `model`: "
                                                       "give one of them")]

#: Each field a dataset states, as its file writes it (core.md § 2, `stated`).
STATED = tuple(field.alias or name for name, field in Stated.model_fields.items() if field_extras(field).get("stated"))


class Material(PartFile):
    """`materials/<name>/material.toml`: a material — each property, by its name in the property
    list, holding its datasets by the names of their sources (materials.md § 3)."""

    display: str = Field(description="the name shown to a person; nothing refers to the material by it, since its "
                                     "folder's name is its name")
    formula: str | None = Field(default=None, description="its chemical formula, as `Au` or `SiO2`")
    aliases: list[str] = Field(default_factory=list, description="other names it goes by, for a person; nothing "
                                                                 "refers to the material by them")
    properties: dict[str, dict[str, Dataset]] = Field(
        default_factory=dict, description="each property, by its name in femkit's list of material properties, "
                                          "holding its datasets, each named by its source",
        json_schema_extra={"doc": "materials.md § 3"})
    notes: dict[str, Any] = Field(default_factory=dict, description="anything kept beside the material; read by no step")


# ------------------------------------------------------------------ a table's file

class TableError(ValueError):
    """A table's file not of the shape materials.md § 3 states: the line it is at, from 1, and why."""

    def __init__(self, line: int, why: str):
        self.line, self.why = line, why
        super().__init__(f"line {line}: {why}")


@dataclass(frozen=True)
class Rows:
    """A table's file as read (materials.md § 3): its columns' names, and each point — its
    variable, in its column's unit, then its value's columns in the property's unit: the value,
    or its real and imaginary parts in the dataset's convention — every number exact; and the
    line each point is on, from 1."""

    names: tuple[str, ...]
    points: tuple[tuple[Fraction, ...], ...]
    lines: tuple[int, ...]


def _numbers(row: list[str]) -> bool:
    """Whether every cell of ``row`` reads as a decimal number."""
    try:
        for cell in row:
            number(cell.strip())
    except UnitError:
        return False
    return True


def rows(data: bytes, convention: Convention | None) -> Rows:
    """A table's file read (materials.md § 3): UTF-8 text, comma-separated; a first row naming its
    columns — one of numbers is refused, since its point would be lost — then one row per point,
    its variable increasing strictly, blank lines at its end ignored; each value a decimal number,
    read exactly (core.md § 11); 2 columns for `real` data and 3 for complex — either, while its
    convention is not stated. A `TableError` naming the line otherwise."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TableError(data[:exc.start].count(b"\n") + 1, "this is not text written in UTF-8") from None
    wanted = (2,) if convention == REAL else (3,) if convention is not None else (2, 3)
    shape = {2: "2 — the variable and the value", 3: "3 — the variable, then the real and imaginary parts"}
    reader = csv.reader(io.StringIO(text, newline=""))
    names: tuple[str, ...] | None = None
    points: list[tuple[Fraction, ...]] = []
    lines: list[int] = []
    blank: int | None = None                                # the first blank line since the last row
    for row in reader:
        line = reader.line_num
        if not any(cell.strip() for cell in row):
            blank = line if blank is None else blank
            continue
        if blank is not None:
            raise TableError(blank, "is empty, and a row follows it: each row after the first is one point")
        if names is None:
            if len(row) not in wanted:
                raise TableError(line, f"names {len(row)} columns; a table of {convention or 'such'} data has "
                                       f"{' or '.join(shape[n] for n in wanted)}")
            if _numbers(row):
                raise TableError(line, "holds numbers; the first row names the columns, as `wavelength,n,k` does, "
                                       "and each point is a row after it")
            names = tuple(cell.strip() for cell in row)
            continue
        if len(row) != len(names):
            raise TableError(line, f"holds {len(row)} values, and the first row names {len(names)} columns")
        try:
            point = tuple(number(cell.strip()) for cell in row)
        except UnitError as exc:
            raise TableError(line, str(exc)) from None
        if points and point[0] <= points[-1][0]:
            raise TableError(line, "its variable does not increase from the row before")
        points.append(point)
        lines.append(line)
    if names is None or not points:
        raise TableError(blank or reader.line_num + 1, "a first row names the columns, and one row follows for each "
                                                       "point")
    return Rows(names, tuple(points), tuple(lines))


# ------------------------------------------------------------------ what a dataset answers

class Answer(NamedTuple):
    """A dataset as it answers a property (materials.md § 1): the property it is held under — the
    one it answers, or an equivalent form of it — and the dataset, as loaded."""

    form: str
    data: Any


def answering(properties: Mapping[str, Property], held: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Answer]]:
    """A material's datasets, by the property each answers and then by name (materials.md § 1):
    a property's own, and those held under each of its equivalent forms. One held under an
    equivalent is listed under the property it is a form of, never its own, since no formulation
    reads an equivalent form; where one name is held under both, the property's own answers, and
    the material's check finds it (`dataset-twice`)."""
    out: dict[str, dict[str, Answer]] = {}
    for form, sets in held.items():
        for prop in [p for p, listed in properties.items() if form in listed.equivalents] or [form]:
            mine = out.setdefault(prop, {})
            for name, data in sets.items():
                if name not in mine or form == prop:
                    mine[name] = Answer(form, data)
    return out


def varies_with(dataset: Any, dispersion: Dispersion) -> str | None:
    """The variable a dataset varies with (materials.md § 6): a table's, a model's; None for a
    value, and for a model the list lacks — its own finding says why."""
    if isinstance(dataset, Table):
        return dataset.variable.name
    if isinstance(dataset, Modelled) and dataset.model in dispersion.models:
        return dispersion.models[dataset.model].variable
    return None


# ------------------------------------------------------------------ the rules a dataset keeps

class Fault(NamedTuple):
    """What is wrong at one key of a dataset (module docstring): its keys from the dataset's own,
    the code a finding of `project check` — or a case's refusal — carries, one sentence saying
    what is written and what would be right, and the one value, or the values, that would be —
    each a plain value, as the file would hold it."""

    keys: tuple[str, ...]
    code: str
    message: str
    right: Any = None
    choices: tuple[str, ...] = ()


class Span(NamedTuple):
    """A range read (materials.md § 3): the variable its bounds are given in the forms of — None
    where no variable is known to hold them to — and its two bounds, as written, in order."""

    variable: str | None
    bounds: tuple[Quantity, Quantity]


def spoken(name: str) -> str:
    """A declared name — a variable's, a property's — as a sentence says it: `photon energy`."""
    return name.replace("_", " ")


def written(value: Any) -> str:
    """A value as its file writes it: a number as itself, a text in quotes, a quantity's
    `{value, unit}` and a list as TOML."""
    try:
        return persist.inline_text(value.model_dump() if isinstance(value, BaseModel) else value)
    except (TypeError, ValueError):
        return repr(value)


def quantity(value: Any, units: Units) -> Quantity:
    """A value as a material's file writes it, read exactly by the units' one reader (core.md
    § 11): `{value, unit}`, or a plain number where it has no unit — naming no definition, since a
    material cites nothing. A `UnitError` saying what would be right for anything else — a text,
    the table to write; a binary float, TOML's `inf` or `nan`; a truth value, a list."""
    return units.measure(value)


def _a(words: str) -> str:
    return ("an " if words[0] in "aeiou" else "a ") + words


def kind(dimension: Dimension, units: Units, dispersion: Dispersion) -> str:
    """A dimension in a person's words: a number with no unit; one of the unit table's base
    dimensions, or its square or cube — `a length squared`; else the variable of that dimension —
    `a photon energy`; else its base dimensions with their powers."""
    if not dimension:
        return "a number with no unit"
    if len(dimension) == 1 and dimension[0][1] in (1, 2, 3):
        base, power = dimension[0]
        return _a(spoken(base) + ("", "", " squared", " cubed")[power])
    named = next((v for v, held in dispersion.variables.items() if units.unit(held.unit).dimension == dimension), None)
    if named is not None:
        return _a(spoken(named))
    return "a quantity of " + " ".join(n if p == 1 else f"{n}^{p}" for n, p in dimension)


def _either(words: Sequence[str]) -> str:
    """``words`` joined as a sentence offers a choice: `a, b or c`."""
    words = list(dict.fromkeys(words))
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} or {words[-1]}"


def measured(value: Any, what: str, allowed: Sequence[str], units: Units, dispersion: Dispersion,
             sign: Sign = "any") -> Quantity | Fault:
    """``value``, what the file writes as ``what``, read exactly and held to the dimensions of
    ``allowed`` — a unit of each its declaration gives it — and to its declared ``sign``
    (materials.md §§ 2, 3; material-data.md § 6.2): the quantity, or the fault — `bad-quantity`,
    `wrong-dimension` or `wrong-sign` — at no key of its own, its caller's."""
    try:
        found = quantity(value, units)
    except UnitError as exc:
        return Fault((), "bad-quantity", f"{what}: {exc}", right=exc.right)
    dimensions = [units.unit(u).dimension for u in allowed]
    if found.dimension not in dimensions:
        needs = _either([kind(d, units, dispersion) for d in dimensions])
        if not found.dimension and not isinstance(value, BaseModel):
            right = {"value": value, "unit": allowed[0]}
            said = f"a number with no unit; it needs {needs}, as {written(right)}"
            return Fault((), "wrong-dimension", f"{what} is {written(value)}, {said}", right=right)
        elif dimensions == [()]:
            said = f"{kind(found.dimension, units, dispersion)}; it needs a number with no unit"
        else:
            said = f"{kind(found.dimension, units, dispersion)}; it needs {needs}, in {_either(allowed)}"
        return Fault((), "wrong-dimension", f"{what} is {written(value)}, {said}")
    if not SIGNS[sign](found.value):
        below = "zero" if found.value == 0 else "below zero"
        return Fault((), "wrong-sign", f"{what} is {written(value)}, {below}; its model needs it {sign}, so that no "
                                       "term gives energy rather than absorb it (material-data.md § 6.2)")
    return found


def model_of(held: Modelled, prop: str, dispersion: Dispersion) -> DispersionModel | Fault:
    """A model's dataset's model (materials.md § 2): one of the list, giving the property ``prop``
    its dataset is held under; else the fault at `model`, `no-such-model`, the models giving
    ``prop`` its choices."""
    model = dispersion.models.get(held.model)
    if model is None or model.gives != prop:
        giving = tuple(sorted(n for n, m in dispersion.models.items() if m.gives == prop))
        said = f"gives the {spoken(model.gives)}, not the {spoken(prop)}" if model else "is no model of femkit's list"
        return Fault(("model",), "no-such-model", f"`{held.model}` {said}", choices=giving)
    return model


def _walk(name: str, declared: Mapping[str, Parameter], given: Mapping[str, Any], units: Units,
          dispersion: Dispersion, where: str = "") -> tuple[dict[str, Quantity], list[Fault]]:
    """Each parameter ``declared`` given, in a dimension and of the sign it declares, and none it
    does not declare: each that reads, and each fault, at the parameter's key; ``where`` says
    which term, for a list's."""
    read: dict[str, Quantity] = {}
    faults: list[Fault] = []
    within = f" in {where}" if where else ""
    for key, value in given.items():
        if key not in declared:
            faults.append(Fault((key,), "no-such-parameter", f"`{name}` has no parameter `{key}`{within}",
                                choices=tuple(declared)))
            continue
        spec = declared[key]
        found = measured(value, f"`{key}`{within}", spec.units, units, dispersion, spec.sign)
        if isinstance(found, Fault):
            faults.append(found._replace(keys=(key,)))
        else:
            read[key] = found
    faults += [Fault((key,), "parameter-missing", f"`{name}` needs the parameter `{key}` "
                                                  f"({declared[key].description}){within}; it is not given")
               for key in declared if key not in given]
    return read, faults


def parameters(held: Modelled, model: DispersionModel, units: Units,
               dispersion: Dispersion) -> tuple[dict[str, Any], list[Fault]]:
    """A model's dataset's parameters (materials.md §§ 2, 3), read and held to its model's
    declaration: each parameter it declares given, in a dimension and of the sign it declares;
    none it does not declare; each list of terms it sums a list of tables of the terms' own. What
    reads — each parameter a `Quantity`, each list of terms a list of tables of them, a list not
    given empty — and each fault, at its key from `parameters`: a term's at its list's key, its
    sentence saying which term, since an entry is keyed by name, never by position
    (projects.md § 5)."""
    lead = {k: v for k, v in held.parameters.items() if k not in model.sums}
    read, faults = _walk(held.model, model.parameters, lead, units, dispersion)
    faults = [f._replace(choices=(*model.parameters, *model.sums)) if f.code == "no-such-parameter" else f
              for f in faults]
    sums: dict[str, list[dict[str, Quantity]]] = {s: [] for s in model.sums}
    for key, terms in held.parameters.items():
        if key not in model.sums:
            continue
        if not isinstance(terms, list):
            faults.append(Fault((key,), "bad-quantity", f"`{key}` is {written(terms)}; it is a list of tables, one "
                                                        "per term"))
            continue
        for i, term in enumerate(terms, start=1):
            each, found = _walk(held.model, model.sums[key].parameters, term, units, dispersion, f"term {i} of `{key}`")
            sums[key].append(each)
            faults += [f._replace(keys=(key,)) for f in found]
    order = list(held.parameters)
    faults.sort(key=lambda f: order.index(f.keys[0]) if f.keys[0] in order else len(order))
    return {**read, **sums}, faults


def column(held: Table, prop: str, listed: Property, units: Units, dispersion: Dispersion) -> list[Fault]:
    """A table's variable (materials.md § 3): one its property ``prop``'s data varies with, and
    its column's unit one of that variable's dimension; else each fault, at `variable.name` or
    `variable.unit` — a unit of another variable the property varies with naming that one."""
    variable = held.variable
    if variable.name not in listed.depends_on or variable.name not in dispersion.variables:
        return [Fault(("variable", "name"), "no-such-variable", f"the {spoken(prop)} of a material varies with no "
                                                                f"variable called `{variable.name}`",
                      choices=tuple(listed.depends_on))]
    try:
        unit = units.unit(variable.unit)
    except UnitError as exc:
        return [Fault(("variable", "unit"), "bad-quantity", f"the unit {written(variable.unit)} does not read: {exc}")]
    wanted = units.unit(dispersion.variables[variable.name].unit).dimension
    if unit.dimension == wanted:
        return []
    other = next((v for v in listed.depends_on if v in dispersion.variables
                  and units.unit(dispersion.variables[v].unit).dimension == unit.dimension), None)
    said = f"`{variable.unit}` is a unit of {kind(unit.dimension, units, dispersion)}, "
    said += f"not of the {spoken(variable.name)}"
    said += (f'; a column written in it is of the {spoken(other)}: name = "{other}"' if other is not None
             else f"; the {spoken(variable.name)} is {kind(wanted, units, dispersion)}")
    return [Fault(("variable", "unit"), "wrong-dimension", said,
                  choices=tuple(sorted(units.of(wanted), key=lambda u: (units.unit(u).value, u))))]


def bounds(held: Stated, variables: Sequence[str], unit: str | None, units: Units,
           dispersion: Dispersion) -> Span | Fault | None:
    """A range read (materials.md § 3): its two bounds under its one unit, `{value = [from, to],
    unit}`, in the forms of one of ``variables`` — the dataset's own, or, for a value, those its
    property depends on — ``unit`` the one a fault's example writes them in. The span — its
    variable None where ``variables`` is empty; None for a range of `all`, or none; else the
    fault at `range`."""
    if not isinstance(held.range, Measure):
        return None
    if len(held.range.value) != 2:
        return Fault(("range",), "bad-quantity", f"the range is {written(held.range)}: it is two bounds, "
                                                 "`{value = [from, to], unit = \"…\"}`")
    try:
        low, high = quantity(held.range, units)
    except UnitError as exc:
        return Fault(("range",), "bad-quantity", f"the range is {written(held.range)}, which does not read: {exc}")
    span = (low, high)
    if not variables:
        return Span(None, span)
    variable = next((v for v in variables if all(dispersion.form(b, v, units) for b in span)), None)
    if variable is not None:
        return Span(variable, span)
    names = _either([spoken(v) for v in variables])
    if not low.dimension:
        example = {"value": held.range.value, "unit": unit} if unit else None
        return Fault(("range",), "wrong-dimension",
                     f"the range is {written(held.range)}, with no unit; it needs a unit of the {names}"
                     + (f", as {written(example)}" if example else ""), right=example)
    forms = [f for v in variables for f in dispersion.forms(v)]
    needs = _either([kind(units.unit(dispersion.variables[f].unit).dimension, units, dispersion) for f in forms])
    given = kind(low.dimension, units, dispersion)
    return Fault(("range",), "wrong-dimension", f"the range is {written(held.range)}, {given}; its bounds are of the "
                                                f"{names}: each {needs}")


def extent(held: Table, table: Rows, span: Span | None, units: Units, dispersion: Dispersion) -> Fault | None:
    """A table's range (materials.md § 3): `[from, to]`, from below to, within its first and last
    rows — a table is never extrapolated (material-data.md § 5). A range of `all`, one reversed
    and one beyond the rows are each a fault at `range` naming the rows' extent in the table's
    unit."""
    unit = held.variable.unit
    first, last = table.points[0][0], table.points[-1][0]
    rows_said = f"its rows run from {decimal(first)} {unit} to {decimal(last)} {unit}"
    if held.range == "all":
        return Fault(("range",), "outside-table", f"a table holds only between its first and last rows, and is never "
                                                  f"extrapolated: {rows_said}; its range is `all`")
    if span is None or span.variable is None:
        return None
    low, high = span.bounds
    try:
        form = dispersion.form(low, span.variable, units)
        if not low.value < dispersion.stated_as(high, form, units).value:
            return Fault(("range",), "range-reversed", f"the range is {written(held.range)}, its first bound not below "
                                                       f"its second; {rows_said}")
        stated = sorted(dispersion.stated_as(b, span.variable, units).value for b in span.bounds)
    except ZeroDivisionError:
        forms = _either([spoken(f) for f in dispersion.forms(span.variable)])
        return Fault(("range",), "bad-quantity", f"the range is {written(held.range)}, and a spectral position of "
                                                 f"zero is no {forms}")
    scale = units.unit(unit).value
    if stated[0] < first * scale or stated[1] > last * scale:
        return Fault(("range",), "outside-table", f"the range is {written(held.range)}, beyond the table's first and "
                                                  f"last rows, and a table is never extrapolated: {rows_said}")
    return None


def losses(table: Rows, convention: Convention | None) -> Fault | None:
    """A complex table's rows whose loss — the imaginary part, kappa for a refractive index under
    `exp(-iwt)` — has the sign of a material that gives energy under its convention (materials.md
    § 3, "Passive data"; material-data.md §§ 2, 3): the fault at `table`, naming the first such
    row's line, and how many more there are."""
    if convention is None or len(table.names) != 3:
        return None
    found = [(line, point[2]) for line, point in zip(table.lines, table.points) if active(point[2], convention)]
    if not found:
        return None
    (line, loss), more = found[0], len(found) - 1
    return Fault(("table",), "active", f"line {line}: its imaginary part, {decimal(loss)}, has the sign of a material "
                                       f"that gives energy under {convention}, and a passive one absorbs"
                                       + (f"; {more} rows more have it too" if more else ""))


def faults(held: Value | Table | Modelled, prop: str, listed: Property, file: bytes | None, units: Units,
           dispersion: Dispersion) -> Iterator[Fault]:
    """Every rule a dataset held under ``prop`` keeps (module docstring), each fault at its key from
    the dataset's own, in the order a person fixes them (materials.md § 3): its form's — a value's;
    a table's variable, its file's shape, its passive rows, its digest and its range; a model's,
    its parameters and its convention — then the value of each variable it holds at (`CONDITIONS`),
    then what it does not state.
    ``file`` is a table's file, as the door read it; None where it is not there — the door's
    finding — and its rules wait. The one rule `project check` finds and a case refuses."""
    if isinstance(held, Value):
        found = measured(held.value, "`value`", [listed.unit], units, dispersion)
        if isinstance(found, Fault):
            yield found._replace(keys=("value",))
        variables = [v for v in listed.depends_on if v in dispersion.variables]
        span = bounds(held, variables, dispersion.variables[variables[0]].unit if variables else None, units,
                      dispersion)
        if isinstance(span, Fault):
            yield span
    elif isinstance(held, Table):
        wrong = column(held, prop, listed, units, dispersion)
        yield from wrong
        span = bounds(held, [] if wrong else [held.variable.name], None if wrong else held.variable.unit, units,
                      dispersion)
        if isinstance(span, Fault):
            yield span
        if file is not None:
            try:
                table = rows(file, held.convention)
            except TableError as exc:
                yield Fault(("table",), "bad-table", f"{held.table}, {exc}")
                table = None
            passive = losses(table, held.convention) if table is not None else None
            if passive is not None:
                yield passive._replace(message=f"{held.table}, {passive.message}")
            if table is not None and passive is None:
                digest = persist.digest(file)
                if held.sha256 is None:
                    yield Fault(("sha256",), "not-stated", f"the table {held.table} states no SHA-256; no case can "
                                                           "rest on it until it does", right=digest)
                elif held.sha256 != digest:
                    yield Fault(("sha256",), "digest-differs", f"the SHA-256 of {held.table} is {digest}, not the "
                                                               "one its dataset states", right=digest)
            if table is not None and not wrong and not isinstance(span, Fault):
                out = extent(held, table, span, units, dispersion)
                if out is not None:
                    yield out
    else:
        model = model_of(held, prop, dispersion)
        if isinstance(model, Fault):
            yield model
            span = bounds(held, [], None, units, dispersion)
        else:
            yield from (f._replace(keys=(PARAMETERS, *f.keys)) for f in parameters(held, model, units, dispersion)[1])
            if held.convention is not None and held.convention != model.convention:
                yield Fault(("convention",), "wrong-convention",
                            f"the convention is {written(held.convention)}, and `{held.model}` is written in "
                            f"{model.convention}: its values are in it", right=model.convention)
            span = bounds(held, [model.variable], dispersion.variables[model.variable].unit, units, dispersion)
        if isinstance(span, Fault):
            yield span
    for name in CONDITIONS:                     # each a variable: the dispersion list refuses to load otherwise
        given = getattr(held, name)
        if given is not None:
            found = measured(given, f"the {name}", [dispersion.variables[name].unit], units, dispersion)
            if isinstance(found, Fault):
                yield found._replace(keys=(name,))
    for key in STATED:
        if getattr(held, key) is None:
            yield Fault((key,), "not-stated", f"the dataset does not state its {key}; no case can rest on it until it "
                                              "does")


# ------------------------------------------------------------------ the check

def check(c: Checking, part: Part) -> Iterator[Issue]:
    """The findings on a material alone (module docstring), from the check frame's property list,
    dispersion list and unit table, and the files the door read beside it (projects.md § 6): each
    dataset's `faults`, at its key, and the names held twice."""
    material: Material = part.data
    files: Mapping[str, Held] = c.opened.held_by(part.address)
    for name, datasets in material.properties.items():
        listed = c.properties.get(name)
        if listed is None:
            yield c.issue(part, PROPERTIES, name, code="no-such-property", choices=sorted(c.properties),
                          message=f"femkit's list of material properties names no property `{name}`")
            continue
        for dataset, held in datasets.items():
            file = files.get(held.table) if isinstance(held, Table) else None
            for fault in faults(held, name, listed, file.data if file is not None else None, c.units, c.dispersion):
                yield c.issue(part, PROPERTIES, name, dataset, *fault.keys, code=fault.code, message=fault.message,
                              right=fault.right, choices=fault.choices,
                              label=held.model if fault.code == "no-such-model" else None)
    yield from _twice(c, part, material)


def _twice(c: Checking, part: Part, material: Material) -> Iterator[Issue]:
    """One dataset's name held under a property and under an equivalent form of it (materials.md
    § 1): it answers the property twice."""
    for name, sets in material.properties.items():
        listed = c.properties.get(name)
        for form in listed.equivalents if listed is not None else ():
            for dataset in sorted(set(sets) & set(material.properties.get(form, {}))):
                yield c.issue(part, PROPERTIES, form, dataset, code="dataset-twice", label=dataset,
                              message=f"the dataset `{dataset}` is held under both {name} and {form}, its equivalent "
                                      f"form; an assignment naming the {name}'s `{dataset}` could mean either")


def keys(properties: Mapping[str, Property], dispersion: Dispersion, text: str) -> list[DeclaredKey]:
    """The keys of a material's file ``text`` that the property list or the dispersion list declares,
    not its schema (core.md § 2; projects.md § 7; web.md § 8.3): each property's own key,
    `properties.<name>`, as the list states it — its sentence and its unit — a key like any other,
    written or not; and, for each dataset the text writes, its model's parameters,
    `….parameters.<p>`, as its model states them — a parameter's sentence and its units, a list of
    terms' sentence alone, and each term's parameters as a parameter's, at
    `….parameters.<list>.<p>`. A dataset's model is read from the text as it writes it, set or shown
    commented out; a dataset whose model the text does not write holds each parameter every model
    declaring it agrees on, if they do."""
    written = written_keys(text)
    out = [DeclaredKey((PROPERTIES, name), listed.description, units=(listed.unit,))
           for name, listed in properties.items()]
    for at in sorted({p[:3] for p in written if len(p) > 2 and p[0] == PROPERTIES}):
        model = written.get((*at, "model"))
        named = dispersion.models.get(model) if isinstance(model, str) else None
        found: dict[tuple[str, ...], set[tuple[str, tuple[str, ...], bool]]] = {}
        for m in [named] if named is not None else list(dispersion.models.values()):
            for name, spec in m.parameters.items():
                found.setdefault((name,), set()).add((spec.description, tuple(spec.units), True))
            for name, listed in m.sums.items():
                found.setdefault((name,), set()).add((listed.description, (), False))
                for term, spec in listed.parameters.items():
                    found.setdefault((name, term), set()).add((spec.description, tuple(spec.units), True))
        out += [DeclaredKey((*at, PARAMETERS, *tail), sentence, units=units, required=required)
                for tail, agreed in found.items() if len(agreed) == 1 for sentence, units, required in agreed]
    return out


def _stated(c: Checking, text: str, manual: str | None) -> list[DeclaredKey]:
    """The keys the property list and the dispersion list state beside a material's schema
    (`keys`), as the frame hands them."""
    return keys(c.properties, c.dispersion, text)


REGISTERS = Registration(schemas={KEY: Material}, checks={KEY: check}, keys={KEY: _stated})
