"""`femkit/data/importers/<source>.toml`: how another library's files map onto femkit's material
format (materials.md § 7) — one file per source, its stem the source's ID, the key the property
list's `names` holds the source's name for a property under (materials.md § 1). Declared as data
and read by `femkit/materials/importer.py`: a new source is a new file, never a branch in code.

A declaration states every key a file may hold (materials.md § 7): the format its files are
written in; the variable their data is written in and the unit the source writes it in; where
each fact a dataset states stands in a file — its citation, its notes (under today's name or an
older one), its conditions, its records and each record's type and range; each other key a file
may hold at its top, which femkit does not map, with what it can state; the addresses a link to
a DOI opens with; each condition the source states, with the variable it is a value of and its
unit; and each record type it maps, onto a table — the property, by the source's name for it,
the key holding its rows, its columns and convention — or onto a dispersion model of femkit's
list — the key holding its coefficients, and the parameters they give, in order, each with the
unit the source writes it in. Loading refuses a variable, a model, a parameter or a unit that
the variables, the models or the unit table do not hold, a condition that is no field a dataset
states (`dispersion.CONDITIONS`), and a table's columns that do not fit its convention; the catalogue
refuses a table's property that the property list's `names` do not give the source exactly once
(`property_of`).

Its model lives here, beside the property list's and the dispersion list's, since the catalogue
that loads it sits below the `materials` package that owns the rule (framework.md § 1)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Mapping, Union

from pydantic import Discriminator, Field, Tag, ValidationInfo, model_validator

from femkit.core.schema import Model, as_quantity, refuse
from femkit.core.units import UnitError, Units
from femkit.definitions.dispersion import CONDITIONS, REAL, Convention, Dispersion
from femkit.definitions.properties import Property


class Keys(Model):
    """Where a file of the source states each fact a dataset holds (materials.md § 7)."""

    references: str = Field(description="the key, at the file's top, holding the source's citation, which becomes the "
                                        "dataset's `source`")
    notes: list[str] = Field(min_length=1, description="the keys, at the file's top, that may hold the source's notes, "
                                                       "which become the material's `[notes]`: today's name, then "
                                                       "each name older files use; a file holds one of them")
    conditions: str = Field(description="the key, at the file's top, holding the conditions the data holds at, each "
                                        "by its name")
    records: str = Field(description="the key, at the file's top, holding its records, a list; one import is one "
                                     "record")
    type: str = Field(description="the key, in each record, naming its type")
    range: str = Field(description="the key, in each record, holding where its data holds: two numbers of the "
                                   "variable, separated by space")


class Written(Model):
    """A value as the source writes it: the variable it is a value of, and its unit."""

    name: str = Field(description="the variable, by its name among the variables",
                      json_schema_extra={"doc": "materials.md § 2"})
    unit: str = as_quantity("the unit the source writes it in, of the variable's dimension", "unit")


class Condition(Written):
    """A condition as the source writes it: the dataset's field it becomes — a variable its data
    holds at — and its unit."""

    name: Literal[CONDITIONS] = Field(description="the variable, by its name among the variables: the field of a "
                                                  "dataset it becomes",
                                      json_schema_extra={"doc": "materials.md § 3"})


class TableRecord(Model):
    """A record type that becomes a table (materials.md § 3): one row per line, the variable then
    the values, each number separated by space."""

    property: str = Field(description="the property it gives, by the source's name for it in femkit's list of "
                                      "material properties",
                          json_schema_extra={"doc": "materials.md § 1"})
    data: str = Field(description="the key, in the record, holding its rows")
    columns: list[str] = Field(min_length=1, max_length=2,
                               description="each column after the variable, by the name the table's first row gives "
                                           "it: one for real data, its real and imaginary parts for complex")
    convention: Convention = Field(description="the convention its values are written in")
    interpolation: Literal["linear"] = Field(description="how the table is read between two rows",
                                             json_schema_extra={"doc": "material-data.md § 5"})

    def holds(self) -> tuple[str, ...]:
        """The keys a record of this type holds, besides its type and its range."""
        return (self.data,)


class ModelRecord(Model):
    """A record type that becomes a dispersion model's dataset (materials.md §§ 2, 3): its
    coefficients, numbers separated by space, give the model's parameters in order, then each
    term of a list it sums, term after term."""

    model: str = Field(description="the dispersion model it becomes, by its name in femkit's list of models",
                       json_schema_extra={"doc": "materials.md § 2"})
    coefficients: str = Field(description="the key, in the record, holding its coefficients")
    parameters: dict[str, str] = as_quantity("the model's parameters the first coefficients give, in order, each with "
                                             "the unit the source writes it in", "unit")
    sum: str = Field(description="the list of terms the coefficients after them give, by its key in the model")
    term: dict[str, str] = as_quantity("each term's parameters, in the order its coefficients give them, each with "
                                       "the unit the source writes it in", "unit", min_length=1)

    def holds(self) -> tuple[str, ...]:
        """The keys a record of this type holds, besides its type and its range."""
        return (self.coefficients,)


#: The two forms a record type maps onto, each by the key that states it.
MAPS: dict[str, type[Model]] = {"property": TableRecord, "model": ModelRecord}


def _maps(value: Any) -> str | None:
    """Which form a record type maps onto: the one key of `MAPS` it states; None for none or both."""
    given = [key for key in MAPS if (key in value if isinstance(value, dict) else hasattr(value, key))]
    return given[0] if len(given) == 1 else None


Record = Annotated[Union[tuple(Annotated[model, Tag(key)] for key, model in MAPS.items())],
                   Discriminator(_maps, custom_error_type="record-form",
                                 custom_error_message="a record type maps onto a table, stating `property`, or onto "
                                                      "a model, stating `model`: give one of them")]


class Importer(Model):
    """`importers/<source>.toml`: one source's files and how they map onto femkit's material format
    (materials.md § 7)."""

    description: str = Field(description="the source and its files, in one plain sentence")
    format: Literal["yaml"] = Field(description="the format its files are written in")
    variable: Written = Field(description="the variable its data is written in, and the unit it writes it in")
    keys: Keys = Field(description="where a file states each fact a dataset holds")
    unmapped: dict[str, str] = Field(default_factory=dict, description="each other key a file may hold at its top, "
                                     "which femkit does not map, by its name: what it can state, said when a file "
                                     "holding it is refused — nothing a file says is dropped")
    doi: list[str] = Field(default_factory=list, description="the addresses a link to a DOI opens with: such a link "
                                                             "is kept as its DOI, every other as its text alone")
    conditions: dict[str, Condition] = Field(default_factory=dict, description="each condition a file may state, by "
                                             "its key: the variable it is a value of — the dataset states it under "
                                             "that name — and its unit; a file stating another is refused")
    records: dict[str, Record] = Field(description="each record type it maps, by the name a record's type gives it; "
                                                   "a record of another is refused")

    @property
    def mapped(self) -> tuple[str, ...]:
        """The keys a file may hold at its top that femkit maps, in the order `keys` gives them."""
        k = self.keys
        return (k.references, *k.notes, k.conditions, k.records)

    @model_validator(mode="after")
    def _declared(self, info: ValidationInfo) -> "Importer":
        """Each variable, model, parameter and unit is one the variables, the models and the unit
        table hold, and a table's columns fit its convention (module docstring)."""
        units: Units | None = (info.context or {}).get("units")
        dispersion: Dispersion | None = (info.context or {}).get("dispersion")
        problems: list[tuple[tuple, str]] = []
        written = [(("variable",), self.variable)] + [(("conditions", k), w) for k, w in self.conditions.items()]
        for at, w in written:
            problems += _written(at, w, units, dispersion)
        for kind, record in self.records.items():
            # its location as pydantic's own would be: the member of the union it is, by its tag
            at = ("records", kind, next(tag for tag, form in MAPS.items() if isinstance(record, form)))
            if isinstance(record, TableRecord):
                if (len(record.columns) == 1) != (record.convention == REAL):
                    problems.append(((*at, "columns"), f"`{record.convention}` data has "
                                                       f"{'one column' if record.convention == REAL else 'two columns'} "
                                                       "after the variable"))
            elif dispersion is not None:
                problems += _model(at, record, units, dispersion)
        refuse("Importer", problems)
        return self


def _written(at: tuple, w: Written, units: Units | None, dispersion: Dispersion | None) -> list[tuple[tuple, str]]:
    """A variable the variables hold, and a unit of its dimension."""
    if dispersion is not None and w.name not in dispersion.variables:
        return [((*at, "name"), f"{w.name!r} is none of the variables: {', '.join(dispersion.variables)}")]
    if units is None:
        return []
    try:
        given = units.unit(w.unit)
    except UnitError as exc:
        return [((*at, "unit"), str(exc))]
    if dispersion is not None and given.dimension != units.unit(dispersion.variables[w.name].unit).dimension:
        return [((*at, "unit"), f"{w.unit!r} is no unit of the {w.name}")]
    return []


def _model(at: tuple, record: ModelRecord, units: Units | None, dispersion: Dispersion) -> list[tuple[tuple, str]]:
    """A model the list holds; its every parameter given and no other, each term's likewise, in a
    unit of a dimension the model's declaration allows it."""
    model = dispersion.models.get(record.model)
    if model is None:
        return [((*at, "model"), f"{record.model!r} is no model of femkit's list: {', '.join(dispersion.models)}")]
    if record.sum not in model.sums:
        return [((*at, "sum"), f"`{record.model}` sums no list `{record.sum}`: {', '.join(model.sums) or 'none'}")]
    problems: list[tuple[tuple, str]] = []
    for key, declared, given in (("parameters", model.parameters, record.parameters),
                                 ("term", model.sums[record.sum].parameters, record.term)):
        if set(given) != set(declared):
            problems.append(((*at, key), f"`{record.model}` takes {', '.join(declared) or 'none'} here, each once"))
            continue
        for name, unit in given.items():
            if units is None:
                continue
            try:
                dimension = units.unit(unit).dimension
            except UnitError as exc:
                problems.append(((*at, key, name), str(exc)))
                continue
            if dimension not in [units.unit(u).dimension for u in declared[name].units]:
                problems.append(((*at, key, name), f"{unit!r} is in none of the dimensions of "
                                                    f"{', '.join(declared[name].units)}"))
    return problems


def property_of(properties: Mapping[str, Property], source: str, name: str) -> list[str]:
    """Every property the property list's `names` gives ``source``'s name ``name`` (materials.md
    § 1): the one an importer's table gives, when there is exactly one."""
    return [p for p, listed in properties.items() if listed.names.get(source) == name]
