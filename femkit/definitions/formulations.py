"""`femkit/data/formulations/<id>.toml`: one physical problem, stated for every engine
(models.md § 4, definitions.md § 1)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationInfo, model_validator

from femkit.core import dirs, persist
from femkit.core.markdown import headings
from femkit.core.schema import Model, refuse
from femkit.core.units import UnitError

Place = Literal["domain", "boundary", "interface"]


class Unknown(Model):
    """What the formulation solves for."""
    name: str = Field(description="its name (`potential`)")
    space: Literal["H1", "Hcurl"] = Field(description="its function space")
    unit: str = Field(description="its unit")


class Described(Model):
    """What a person reads beside a choice — a tooltip, a hint, a line of the reference: one
    plain sentence, and the section of the science document that defines it."""
    description: str = Field(description="one plain sentence: what it is or states")
    section: str = Field(description="the science document's section that defines it, as its link anchor "
                                     "(`3-conditions-on-an-outer-boundary`)")


class PropertySpec(Described):
    """A material property the formulation reads."""
    unit: str = Field(description="its unit; `1` for a plain number")
    complex: bool = Field(description="whether its values may be complex")


class ParameterSpec(Model):
    """One parameter of a condition or source."""
    unit: str = Field(description="its unit")
    description: str = Field(description="one plain sentence: what the value is")


class KindSpec(Described):
    """A condition or source kind: where it may stand, and its parameters."""
    on: list[Place] = Field(min_length=1, description="the region kinds it may be stated on")
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict, description="each parameter")


class DerivedSpec(Described):
    """A quantity an observable may name."""
    unit: str = Field(description="its unit")


class Constant(Described):
    """A physical constant the formulation's equation uses, as every engine must be given it."""
    value: str = Field(description="its value, with its unit")


class Benchmark(Described):
    """A problem with a known answer (models.md § 4, § 6.3): a project of its own, and the
    exact value each of its observables must reproduce."""
    project: str = Field(description="its folder, from femkit/data/formulations/, holding model.toml and "
                                     "study.toml")
    exercises: list[str] = Field(min_length=1, description="the formulation's condition, source and property "
                                                           "kinds it exercises")
    tolerance: str = Field(description="the relative difference a run may show from each reference value, a plain "
                                       "number; its basis is in the science document's section")
    reference: dict[str, str] = Field(min_length=1, description="each observable of its study, and its exact value")


class FormulationDefinition(Model):
    """One physical problem, stated without reference to any engine (models.md § 4)."""
    description: str = Field(description="one line: what it solves")
    science: str = Field(description="its science document, from the checkout's root")
    unknown: Unknown = Field(description="what it solves for")
    meanings: dict[Literal["2", "3"], list[str]] = Field(description="what each dimension may mean; a model "
                                                                        "chooses one")
    conventions: list[Literal["phasor", "amplitude"]] = Field(default_factory=list,
                                                               description="the conventions a model must choose")
    constants: dict[str, Constant] = Field(default_factory=dict, description="the physical constants its equation "
                                           "uses, each given to every engine as stated here")
    properties: dict[str, PropertySpec] = Field(description="the material properties it reads")
    conditions: dict[str, KindSpec] = Field(description="the condition kinds it allows")
    sources: dict[str, KindSpec] = Field(default_factory=dict, description="the source kinds it allows")
    derived: dict[str, DerivedSpec] = Field(description="each quantity an observable may name")
    benchmarks: dict[str, Benchmark] = Field(default_factory=dict, description="its benchmark set: problems with "
                                             "known answers (models.md § 6.3)")

    @model_validator(mode="after")
    def _units_and_science(self, info: ValidationInfo) -> "FormulationDefinition":
        units = (info.context or {}).get("units")
        problems: list[tuple[tuple, str]] = []
        science = persist.read_text(dirs.checkout() / self.science)
        if science is None:
            problems.append((("science",), f"{self.science} does not exist"))
        texts = [(("unknown", "unit"), self.unknown.unit)]
        texts += [(("properties", n, "unit"), p.unit) for n, p in self.properties.items()]
        texts += [((table, k, "parameters", p, "unit"), spec.unit) for table in ("conditions", "sources")
                  for k, kind in getattr(self, table).items() for p, spec in kind.parameters.items()]
        texts += [(("derived", n, "unit"), d.unit) for n, d in self.derived.items()]
        texts += [(("constants", n, "value"), c.value) for n, c in self.constants.items()]
        texts += [(("benchmarks", b, "reference", o), v) for b, spec in self.benchmarks.items()
                  for o, v in spec.reference.items()]
        texts += [(("benchmarks", b, "tolerance"), spec.tolerance) for b, spec in self.benchmarks.items()]
        for at, text in texts if units is not None else []:
            try:
                units.parse(text)
            except UnitError as exc:
                problems.append((at, str(exc)))
        if self.unknown.name not in self.derived:
            problems.append((("derived",), f"names the unknown, {self.unknown.name!r}, as an observable may"))
        anchors = {h.anchor for h in headings(science)} if science is not None else set()
        described = [((t, k), d) for t in ("constants", "properties", "conditions", "sources", "derived",
                                            "benchmarks")
                     for k, d in getattr(self, t).items()]
        kinds = set(self.conditions) | set(self.sources) | set(self.properties)
        root = (info.context or {}).get("root")
        for name, b in self.benchmarks.items():
            problems += [(("benchmarks", name, "exercises", i), f"{e!r} is none of this formulation's kinds or "
                          "properties") for i, e in enumerate(b.exercises) if e not in kinds]
            if root is not None and not all((root / b.project / f).is_file() for f in ("model.toml", "study.toml")):
                problems.append((("benchmarks", name, "project"), f"{b.project} holds no model.toml and study.toml"))
        for at, d in described if anchors else []:
            if d.section not in anchors:
                problems.append(((*at, "section"), f"{self.science} has no section #{d.section}"))
        refuse("FormulationDefinition", problems)
        return self

