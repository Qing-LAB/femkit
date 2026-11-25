"""The projects domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from pydantic import Field

from femkit.core.commandline import ARGUMENT
from femkit.core.schema import Model
from femkit.core.view import Verb


class ListRequest(Model):
    """No inputs."""


class NewRequest(Model):
    """A new project under the projects root: a copy of one of femkit's templates, or of one of
    your projects (projects.md § 7)."""

    name: str = Field(description="its name: its path from the projects root", json_schema_extra=ARGUMENT)
    source: str | None = Field(default=None, description="what it copies: a template by its bare name, or one of "
                                                         "your projects by its path from the projects root",
                               json_schema_extra={"cli": "--from"})


# ------------------------------------------------------------------ the operations these requests are for

PROJECT_LIST = Verb("project.list", ListRequest)
PROJECT_NEW = Verb("project.new", NewRequest)
