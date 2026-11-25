"""The project file, `project.toml` (projects.md §§ 2–3, models.md § 3): what the project is, the
components and studies it names, and the shared parameters — the `models.project` part schema and
its check. The parameters themselves are resolved once, by the check frame
(`femkit/projects/checking.py`).

Its findings, each at the project file's key:
- `no-such-part` (error): a component or study it names has no file; its right value the list
  with the closest name there put in its place, or, with none close, its choices the ones there;
- `not-named` (warning): a component or study is in its folder but the project file does not name
  it, nor a name close to it — inert, never expanded into a case; right: the list with it named;
- `named-like-a-unit` (error): a parameter named like a unit symbol, which a value using that unit
  would read instead.
"""

from __future__ import annotations

from typing import Iterator

from pydantic import Field

from femkit.core.issues import Issue
from femkit.core.schema import as_reference, field_extras
from femkit.models.parts import cited, missing
from femkit.projects.checking import Checking
from femkit.projects.door import Part
from femkit.projects.schemas import PartFile


class ProjectFile(PartFile):
    """`project.toml`: what the project is, the components and studies it names, and the shared
    parameters (projects.md § 3, models.md § 3)."""

    description: str = Field(description="what the project is, in a sentence or two")
    components: list[str] = as_reference("the project's components, by name: each the folder `components/<name>/`, "
                                         "holding `component.toml` and `geometry.py`", "component",
                                         default_factory=list)
    studies: list[str] = as_reference("the project's studies, by name: each the file `studies/<name>.toml`", "study",
                                      default_factory=list)
    parameters: dict[str, str] = Field(default_factory=dict, description="the shared parameters, by name: each a "
                                       "quantity with its unit, or an expression of other parameters with `+`, `-`, "
                                       "`*`, `/` and parentheses", json_schema_extra={"quantity": "any",
                                                                                      "doc": "core.md § 11"})


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """The project file's own rules (projects.md § 3, models.md § 3). A part the project file does
    not name, but which a name it holds without a file most likely misspells, is that name's
    finding alone (`parts.cited`): one mistake, said once, its right value the list with the name
    put right."""
    data: ProjectFile = part.data
    yield from cited(c, part)
    meant_by = {m.near for m in missing(c, part) if m.near is not None}
    for name, field in ProjectFile.model_fields.items():
        kind, key = field_extras(field).get("ref"), field.alias or name
        if kind not in c.opened.layout.kinds:
            continue
        named = getattr(data, name)
        for other in sorted(p.address.name for p in c.opened.parts.values() if p.address.kind == kind):
            if other not in named and other not in meant_by:
                yield c.issue(part, key, code="not-named", severity="warning", label=other, right=[*named, other],
                              message=f"the {kind} `{other}` is not named in the project file: it is inert, never "
                                      "expanded into a case")
    symbols = set(c.units.symbols())
    for name in data.parameters:
        if name in symbols:
            yield c.issue(part, "parameters", name, code="named-like-a-unit", label=name,
                          message=f"the parameter `{name}` is named like the unit {name}: a value written with that "
                                  "unit would read the parameter instead")


PART_SCHEMAS = {"models.project": ProjectFile}
PART_CHECKS = {"models.project": check}
