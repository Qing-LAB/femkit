"""`femkit/data/properties.toml`: the property list — every material property femkit knows,
named once, with its unit, its form, and its name in each engine and each source
(materials.md § 1). The one place a property is named: a formulation lists the names it reads,
a material holds datasets under them, a translator writes an engine's name from here.

Its model lives here, with the shipped definitions' others, since the catalogue that loads it
sits below the `materials` package that owns the rule (framework.md § 1)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import ConfigDict, Field, RootModel, ValidationInfo, model_validator

from femkit.core.schema import Model, as_quantity, refuse
from femkit.core.units import UnitError

NAME = re.compile(r"[a-z][a-z0-9_]*")   # a property's plain name with underscores; a symbol is never a name


class Property(Model):
    """One material property (materials.md § 1)."""

    description: str = Field(description="what it is, in one plain sentence")
    unit: str = as_quantity("its unit, as the unit table reads it; `1` for a plain number", "unit")
    values: Literal["real", "complex"] = Field(description="whether its values are real or may be complex")
    shape: Literal["scalar", "tensor"] = Field(description="one value, or a 3 x 3 tensor in the component's frame")
    depends_on: list[str] = Field(default_factory=list, description="the variables a dataset of it may vary with, "
                                  "each by its name in femkit's list of variables",
                                  json_schema_extra={"doc": "materials.md § 2"})
    equivalents: list[str] = Field(default_factory=list, description="the properties of this list convertible to "
                                   "it, each by its name; the science documents state each conversion and its sign")
    names: dict[str, str | dict[str, str]] = Field(default_factory=dict, description="its name in each engine and "
                                                   "each source that has one, by the engine's or source's ID; a "
                                                   "table of names where one writes the value as several")

    @model_validator(mode="after")
    def _unit(self, info: ValidationInfo) -> "Property":
        units = (info.context or {}).get("units")
        variables = (info.context or {}).get("variables")   # dispersion.toml's, where it loads (materials.md § 2)
        problems: list[tuple[tuple, str]] = []
        if units is not None:
            try:
                units.parse(self.unit)
            except UnitError as exc:
                problems.append((("unit",), str(exc)))
        problems += [(("depends_on", i), f"{v!r} is none of the variables: {', '.join(sorted(variables))}"
                      if variables is not None else f"{v!r} is no variable's name")
                     for i, v in enumerate(self.depends_on)
                     if not NAME.fullmatch(v) or variables is not None and v not in variables]
        problems += [(("names", k), f"{k!r} is no engine's or source's ID") for k in self.names if not NAME.fullmatch(k)]
        refuse("Property", problems)
        return self


class PropertyList(RootModel[dict[str, Property]]):
    """`properties.toml`: each property by its name."""

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def _names(self) -> "PropertyList":
        problems: list[tuple[tuple, str]] = []
        for name, p in self.root.items():
            if not NAME.fullmatch(name):
                problems.append(((name,), f"{name!r} is no property's name: its plain name, lowercase, with `_`"))
            problems += [((name, "equivalents", i), f"{e!r} is {'itself' if e == name else 'no property of this list'}")
                         for i, e in enumerate(p.equivalents) if e == name or e not in self.root]
        refuse("PropertyList", problems)
        return self
