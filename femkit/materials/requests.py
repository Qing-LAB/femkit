"""The materials domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from femkit.core.commandline import ARGUMENT
from femkit.core.schema import Model
from femkit.core.view import Verb


class ImportRequest(Model):
    """A new material from another source's file, in the global library or a project's
    `materials/` (materials.md § 7)."""

    source: str = Field(description="the source the file comes from, by its importer's name",
                        json_schema_extra={**ARGUMENT, "doc": "materials.md § 7", "choices": "importers"})
    file: str = Field(description="the source's file: its path, from the folder the command runs in",
                      json_schema_extra=ARGUMENT)
    name: str = Field(description="the new material's name: its path in the library or the project's materials",
                      json_schema_extra={"cli": "--as"})
    into: Literal["library", "project"] = Field(description="where the new material goes: the global library, or a "
                                                            "project's own materials")
    project: str | None = Field(default=None, description="with `--into project`, the project, by its path from the "
                                                          "projects root; unset, the project the command runs in",
                                json_schema_extra={"context": "project"})


# ------------------------------------------------------------------ the operations these requests are for

MATERIAL_IMPORT = Verb("material.import", ImportRequest)
