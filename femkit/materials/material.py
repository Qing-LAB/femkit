"""A material's file, `materials/<name>/material.toml` (materials.md § 3), and its check.

A material holds each property by its name in the property list (§ 1), and each property one or
more datasets, each named by its source. In step D a dataset is a fixed `value`; a table and a
dispersion model are step E's (plan § 4, E). A dataset's `convention`, `source` and `range` are
`stated` fields (core.md § 2): a file being written may lack them, and `project check` asks for
each. Its value and its range's bounds are quantities naming no parameter, since a material cites
nothing (projects.md § 3): the `quantity` kind `constant` (core.md § 2).

The check of a material alone (models.md § 11.1) finds, each at its key (core.md § 10):
- `no-such-property`: a property the property list does not name — the list's names its choices;
- `bad-quantity`: a dataset's value, or a bound of its range, that does not read as a quantity
  naming no parameter (core.md § 11);
- `wrong-dimension`: a dataset's value outside its property's dimension, the list's unit's;
- `not-stated`: a dataset missing a stated field, at that field's key.
A range's dimension is its variable's, which step E states (plan § 4, E).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Iterator, Literal, Mapping, Union

from pydantic import Field

from femkit.core.issues import Issue
from femkit.core.schema import Declared, Model, as_quantity, field_extras, help_text
from femkit.definitions.properties import Property
from femkit.projects.checking import Checking
from femkit.projects.door import Part
from femkit.projects.schemas import PartFile

KEY = "materials.material"   # the key the layout names this schema by (projects.md § 4)
PROPERTIES = "properties"    # the table holding each property, by its name in the property list


class Dataset(Model):
    """One dataset of a property, named by its source (materials.md § 3): until step E, a fixed value."""

    value: Union[int, Decimal, str] = as_quantity("a constant, with its unit where it has one", "constant")
    convention: Literal["real", "exp(-iwt)", "exp(+iwt)"] | None = Field(
        default=None, description="the convention of the source's complex values", json_schema_extra={"stated": True})
    source: str | None = Field(default=None, description="where the data comes from: a citation a reader can check, "
                                                         "with its DOI where there is one",
                               json_schema_extra={"stated": True})
    range: Literal["all"] | Annotated[list[str], Field(min_length=2, max_length=2)] | None = as_quantity(
        "where the data holds: `all`, or `[from, to]` in its variable", "constant", default=None,
        extra={"stated": True})


#: Each field a dataset states, as its file writes it (core.md § 2, `stated`).
STATED = tuple(field.alias or name for name, field in Dataset.model_fields.items() if field_extras(field).get("stated"))


class Material(PartFile):
    """`materials/<name>/material.toml`: a material — each property, by its name in the property
    list, holding its datasets by the names of their sources (materials.md § 3)."""

    display: str = Field(description="the name shown to a person; nothing refers to the material by it, since its "
                                     "folder's name is its name")
    formula: str | None = Field(default=None, description="its chemical formula, as `Au` or `SiO2`")
    aliases: list[str] = Field(default_factory=list, description="other names a search of a library finds it by; "
                                                                 "nothing refers to the material by them")
    properties: dict[str, dict[str, Dataset]] = Field(
        default_factory=dict, description="each property, by its name in femkit's list of material properties, "
                                          "holding its datasets, each named by its source",
        json_schema_extra={"doc": "materials.md § 3"})
    notes: dict[str, Any] = Field(default_factory=dict, description="anything kept beside the material; read by no step")


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """The findings on a material alone (module docstring), from the check frame's property list
    and unit table (projects.md § 6)."""
    material: Material = part.data
    for name, datasets in material.properties.items():
        listed = c.properties.get(name)
        if listed is None:
            yield c.issue(part, PROPERTIES, name, code="no-such-property", choices=sorted(c.properties),
                          message=f"femkit's list of material properties names no property `{name}`")
            continue
        dimension = c.units.parse(listed.unit).dimension
        for dataset, held in datasets.items():
            at = (PROPERTIES, name, dataset)
            yield from c.measure(part, (*at, "value"), held.value, dimension,
                                 f"in the dimension of its property's unit, {listed.unit!r}", parameters=False)[1]
            for bound in held.range if isinstance(held.range, list) else ():
                yield from c.measure(part, (*at, "range"), bound, parameters=False)[1]
            for key in STATED:
                if getattr(held, key) is None:
                    yield c.issue(part, *at, key, code="not-stated",
                                  message=f"the dataset `{dataset}` of {name} does not state its {key}; no case can "
                                          "rest on it until it does")


def declared(properties: Mapping[str, Property]) -> Declared:
    """The help of each key of a material's file the property list declares (core.md § 2;
    projects.md § 7): a property's own key, `properties.<name>`, as the list states it — its
    sentence, then `, in` and its unit (`help_text`); None for every other key."""

    def help_of(path: tuple[str, ...]) -> str | None:
        if len(path) == 2 and path[0] == PROPERTIES and path[1] in properties:
            listed = properties[path[1]]
            return help_text(listed.description, unit=listed.unit)
        return None

    return help_of


PART_SCHEMAS = {KEY: Material}
PART_CHECKS = {KEY: check}
