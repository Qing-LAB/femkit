"""`femkit/data/meshers/<id>.toml`: a mesher, and what it can build and write (models.md § 6.5).

A mesher states only what is measured or cited, in `basis`; what is not known is left out.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationInfo, model_validator

from femkit.core.schema import Model, refuse

Control = Literal["size", "regions"]   # the study's mesh policy keys (models.md § 5)


class Tolerance(Model):
    """How close two points must be for the mesher to merge them."""
    kind: Literal["absolute", "relative"] = Field(description="in the length unit geometry is handed over in, "
                                                              "or relative to the model's size")
    value: str = Field(description="a plain number")


class Writes(Model):
    """The mesh file it writes."""
    format: str = Field(description="the format (`msh`, `vol`)")
    version: str | None = Field(default=None, description="the format's version, where it has several")
    encoding: Literal["ascii", "binary"] | None = Field(default=None, description="text or binary")


class MesherDefinition(Model):
    """One mesher (models.md § 6.5)."""
    description: str = Field(description="one line")
    provided_by: str = Field(description="the engine environment it runs in")
    dimensions: list[Literal[2, 3]] = Field(min_length=1, description="the dimensions it meshes")
    builds: list[str] = Field(description="the model's shape kinds it can build; `schema check` refuses one the "
                                          "model has not")
    imports: list[Literal["step", "iges", "brep", "stl"]] = Field(default_factory=list,
                                                                  description="the CAD formats an `import` may be in")
    controls: list[Control] = Field(description="the mesh policy's keys it honors")
    tolerance: Tolerance | None = Field(default=None, description="its geometric tolerance; absent: not known, "
                                                                  "and no feature can be checked against it")
    writes: Writes = Field(description="the mesh it writes")
    orders: list[int] = Field(min_length=1, description="the geometry orders it writes")
    keeps_region_names: bool = Field(description="whether the mesh's parts keep the model's region names")
    basis: str = Field(description="where these facts come from: what was measured, on which version, or a citation")

    @model_validator(mode="after")
    def _known_environment(self, info: ValidationInfo) -> "MesherDefinition":
        known = (info.context or {}).get("environments")
        problems = []
        if known is not None and self.provided_by not in known:
            problems.append((("provided_by",), f"{self.provided_by!r} is not an engine environment "
                                               f"(they are: {', '.join(sorted(known))})"))
        if "import" in self.builds and not self.imports:
            problems.append((("imports",), "builds `import`, and names no format it imports"))
        refuse("MesherDefinition", problems)
        return self
