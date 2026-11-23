"""`femkit/data/formulations/<id>.toml`: one physical problem, stated for every engine
(models.md § 4, definitions.md § 1)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationInfo, model_validator

from femkit.core import dirs
from femkit.core.schema import Model, refuse
from femkit.core.units import UnitError

Place = Literal["domain", "boundary", "interface"]


class Unknown(Model):
    """What the formulation solves for."""
    name: str = Field(description="its name (`potential`)")
    space: Literal["H1", "Hcurl"] = Field(description="its function space")
    unit: str = Field(description="its unit")


class PropertySpec(Model):
    """A material property the formulation reads."""
    unit: str = Field(description="its unit; `1` for a plain number")
    complex: bool = Field(description="whether its values may be complex")


class KindSpec(Model):
    """A condition or source kind: where it may stand, and its parameters with their units."""
    on: list[Place] = Field(min_length=1, description="the region kinds it may be stated on")
    parameters: dict[str, str] = Field(default_factory=dict, description="each parameter and its unit")


class FormulationDefinition(Model):
    """One physical problem, stated without reference to any engine (models.md § 4)."""
    description: str = Field(description="one line: what it solves")
    science: str = Field(description="its science document, from the checkout's root")
    unknown: Unknown = Field(description="what it solves for")
    meanings: dict[Literal["2", "3"], list[str]] = Field(description="what each dimension may mean; a model "
                                                                        "chooses one")
    conventions: list[Literal["phasor", "amplitude"]] = Field(default_factory=list,
                                                               description="the conventions a model must choose")
    properties: dict[str, PropertySpec] = Field(description="the material properties it reads")
    conditions: dict[str, KindSpec] = Field(description="the condition kinds it allows")
    sources: dict[str, KindSpec] = Field(default_factory=dict, description="the source kinds it allows")
    derived: dict[str, str] = Field(description="each quantity an observable may name, and its unit")

    @model_validator(mode="after")
    def _units_and_science(self, info: ValidationInfo) -> "FormulationDefinition":
        units = (info.context or {}).get("units")
        problems: list[tuple[tuple, str]] = []
        if not (dirs.checkout() / self.science).is_file():
            problems.append((("science",), f"{self.science} does not exist"))
        texts = [(("unknown", "unit"), self.unknown.unit)]
        texts += [(("properties", n, "unit"), p.unit) for n, p in self.properties.items()]
        texts += [((table, k, "parameters", p), u) for table in ("conditions", "sources")
                  for k, spec in getattr(self, table).items() for p, u in spec.parameters.items()]
        texts += [(("derived", n), u) for n, u in self.derived.items()]
        for at, text in texts if units is not None else []:
            try:
                units.parse(text)
            except UnitError as exc:
                problems.append((at, str(exc)))
        if self.unknown.name not in self.derived:
            problems.append((("derived",), f"names the unknown, {self.unknown.name!r}, as an observable may"))
        refuse("FormulationDefinition", problems)
        return self
