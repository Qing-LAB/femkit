"""`femkit/data/formulations/<id>.toml`: one physical problem, stated for every engine
(models.md § 4, definitions.md § 1)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, RootModel, ValidationInfo, model_validator

from femkit.core import dirs, persist
from femkit.core.markdown import headings
from femkit.core.schema import Measure, Model, Number, as_quantity, refuse
from femkit.core.units import UnitError
from femkit.definitions.properties import NAME


class StepKind(Model):
    """One kind of calculation a study's step asks of a formulation family (models.md § 4.2), from
    `femkit/data/step_kinds.toml`: one list, closed, each kind read by its name."""

    description: str = Field(description="the calculation, in one plain sentence")
    supplies: list[str] = Field(default_factory=list, description="the variables it supplies a value of, each by its "
                                "name in femkit's list of variables: what a material's data may vary with under it; "
                                "none for a calculation that supplies none", json_schema_extra={"doc": "materials.md § 6"})

    @model_validator(mode="after")
    def _variables(self, info: ValidationInfo) -> "StepKind":
        variables = (info.context or {}).get("variables")
        refuse("StepKind", [(("supplies", i), f"{v!r} is none of the variables: {', '.join(sorted(variables))}")
                            for i, v in enumerate(self.supplies) if variables is not None and v not in variables])
        return self


class StepKindList(RootModel[dict[str, StepKind]]):
    """`step_kinds.toml`: each step kind by its name."""

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def _names(self) -> "StepKindList":
        refuse("StepKindList", [((name,), f"{name!r} is no step kind's name: its calculation, lowercase, with `_`")
                                for name in self.root if not NAME.fullmatch(name)])
        return self


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


class PropertySpec(Model):
    """A material property the formulation reads, named by its key from the property list
    (materials.md § 1; models.md § 4.3): its sentence and its unit are the list's, never
    repeated here."""
    note: str | None = Field(default=None, description="what this formulation adds to the property list's sentence, "
                                                       "where it adds anything")
    section: str = Field(description="the science document's section that defines it, as its link anchor "
                                     "(`1-terms-and-symbols`)")
    complex: bool = Field(description="whether it allows complex values; false where it needs them real")


class ParameterSpec(Model):
    """One parameter of a condition or source."""
    unit: str = Field(description="its unit")
    description: str = Field(description="one plain sentence: what the value is")


class KindSpec(Described):
    """A condition or source kind: where it may stand, and its parameters."""
    on: list[str] = Field(min_length=1, description="the places it may stand on, by their names in the one "
                                                    "vocabulary of places, `femkit/data/geometry/kinds.toml` "
                                                    "(geometry.md § 7)")
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict, description="each parameter")


class DerivedSpec(Described):
    """A quantity the formulation derives from its unknown, which a later step may take."""
    unit: str = Field(description="its unit")


class Constant(Described):
    """A physical constant the formulation's equation uses, as every engine must be given it."""
    value: Measure[Number] = as_quantity("its value, with its unit", "constant")


class Benchmark(Described):
    """A problem with a known answer (models.md § 4, § 6.3): a project of its own, and the
    exact value each of its observables must reproduce."""
    project: str = Field(description="its project: one of femkit's project templates, by its bare name, a "
                                     "folder of `femkit/data/templates/` (projects.md § 7)")
    exercises: list[str] = Field(min_length=1, description="the formulation's condition, source and property "
                                                           "kinds it exercises")
    tolerance: Number = Field(description="the relative difference a run may show from each reference value, a "
                                          "plain number; its basis is in the science document's section")
    reference: dict[str, Measure[Number]] = as_quantity("each observable of the observables part reading its "
                                                        "studies, by its name, and its exact value, with its unit",
                                                        "constant", min_length=1)


class FormulationDefinition(Model):
    """One physical problem, stated without reference to any engine (models.md § 4)."""
    description: str = Field(description="one line: what it solves")
    science: str = Field(description="its science document, from the checkout's root")
    kinds: list[str] = Field(min_length=1, description="the step kinds it supports, each by its name in the list of "
                                                       "step kinds (models.md § 4.2)")
    unknown: Unknown = Field(description="what it solves for")
    meanings: dict[Literal["2", "3"], list[str]] = Field(description="what each dimension may mean; a model "
                                                                        "chooses one")
    conventions: list[Literal["phasor", "amplitude"]] = Field(default_factory=list,
                                                               description="the conventions a model must choose")
    constants: dict[str, Constant] = Field(default_factory=dict, description="the physical constants its equation "
                                           "uses, each given to every engine as stated here")
    properties: dict[str, PropertySpec] = Field(description="the material properties it reads, each by its name in "
                                                "femkit's list of material properties",
                                                json_schema_extra={"doc": "materials.md § 1"})
    conditions: dict[str, KindSpec] = Field(description="the condition kinds it allows")
    sources: dict[str, KindSpec] = Field(default_factory=dict, description="the source kinds it allows")
    derived: dict[str, DerivedSpec] = Field(description="each quantity it derives, which a later step of a study may "
                                                         "take from the step that solves it")
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
        texts += [((table, k, "parameters", p, "unit"), spec.unit) for table in ("conditions", "sources")
                  for k, kind in getattr(self, table).items() for p, spec in kind.parameters.items()]
        texts += [(("derived", n, "unit"), d.unit) for n, d in self.derived.items()]
        texts += [(("constants", n, "value", "unit"), c.value.unit) for n, c in self.constants.items()]
        texts += [(("benchmarks", b, "reference", o, "unit"), v.unit) for b, spec in self.benchmarks.items()
                  for o, v in spec.reference.items()]
        for at, text in texts if units is not None else []:
            try:
                units.unit(text)
            except UnitError as exc:
                problems.append((at, str(exc)))
        if self.unknown.name not in self.derived:
            problems.append((("derived",), f"names the unknown, {self.unknown.name!r}, as a step taking it does"))
        anchors = {h.anchor for h in headings(science)} if science is not None else set()
        described = [((t, k), d) for t in ("constants", "properties", "conditions", "sources", "derived",
                                            "benchmarks")
                     for k, d in getattr(self, t).items()]
        places = (info.context or {}).get("places")
        problems += [((table, k, "on", i), f"{p!r} is no place: {', '.join(sorted(places))}")
                     for table in ("conditions", "sources") for k, kind in getattr(self, table).items()
                     for i, p in enumerate(kind.on) if places is not None and p not in places]
        declared = (info.context or {}).get("kinds")
        problems += [(("kinds", i), f"{k!r} is no step kind: {', '.join(sorted(declared))}")
                     for i, k in enumerate(self.kinds) if declared is not None and k not in declared]
        listed = (info.context or {}).get("properties")     # the property list's names (materials.md § 1)
        problems += [(("properties", p), f"{p!r} is no property of femkit's list: {', '.join(sorted(listed))}")
                     for p in self.properties if listed is not None and p not in listed]
        kinds = set(self.conditions) | set(self.sources) | set(self.properties)
        templates = (info.context or {}).get("templates")
        for name, b in self.benchmarks.items():
            problems += [(("benchmarks", name, "exercises", i), f"{e!r} is none of this formulation's kinds or "
                          "properties") for i, e in enumerate(b.exercises) if e not in kinds]
            if templates is not None and b.project not in templates:
                problems.append((("benchmarks", name, "project"), f"{b.project!r} is none of femkit's project "
                                                                  f"templates: {', '.join(sorted(templates))}"))
        for at, d in described if anchors else []:
            if d.section not in anchors:
                problems.append(((*at, "section"), f"{self.science} has no section #{d.section}"))
        refuse("FormulationDefinition", problems)
        return self

