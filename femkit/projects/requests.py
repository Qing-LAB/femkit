"""The projects domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from pydantic import Field

from femkit.core.commandline import ARGUMENT
from femkit.core.schema import SHA256, Model, matching
from femkit.core.view import Verb


class ListRequest(Model):
    """No inputs."""


class ProjectRequest(Model):
    """Which project (projects.md § 1): by its path from the projects root, or the one the
    command runs in — the one request every command on a project takes, declared here, with the
    door that finds it."""

    project: str | None = Field(default=None, description="the project, by its path from the projects root; unset, "
                                                          "the project the command runs in",
                                json_schema_extra={"context": "project"})


class NewRequest(Model):
    """A new project under the projects root: a copy of one of femkit's templates, or of one of
    your projects (projects.md § 7)."""

    name: str = Field(description="its name: its path from the projects root", json_schema_extra=ARGUMENT)
    source: str | None = Field(default=None, description="what it copies: a template by its bare name, or one of "
                                                         "your projects by its path from the projects root",
                               json_schema_extra={"cli": "--from", "choices": "templates"})


# ------------------------------------------------------------------ the operations these requests are for

PROJECT_LIST = Verb("project.list", ListRequest, on_machine=False, effect="reads")
class SaveRequest(ProjectRequest):
    """A file of the project saved exactly as the person typed it in the page's text editor
    (projects.md § 7): the request is the text they typed, so the page alone offers it (api.md § 2)."""

    address: str = Field(description="the file, by its address: a part's own, `physics:heat`, or a file of a folder "
                                     "part's, `component:bowtie@geometry.py`",
                         json_schema_extra={**ARGUMENT, "doc": "projects.md § 5"})
    text: str = Field(description="the file's new text, exactly as typed: written as it is, its bytes its UTF-8")
    sha256: str = matching(SHA256, description="the SHA-256 of the file's bytes when the page opened it: a file "
                                               "changed since is not saved over",
                           json_schema_extra={"doc": "projects.md § 7"})


# `project check`, implemented by the models domain beside `project graph` (models.md § 11.1), is
# declared here, beside the request it takes, so `project new` and `material import` name it.
PROJECT_CHECK = Verb("project.check", ProjectRequest, on_machine=False, effect="reads")
# `project save`, implemented by the workflow — the lowest layer that reads every comparison of a
# change's impact (projects.md § 7; workflow.md § 10) — is declared here, beside its request, so the
# door gives each file it reads the action that saves it (web.md § 7.6, `File.save`).
PROJECT_SAVE = Verb("project.save", SaveRequest, on_machine=False, effect="changes")
PROJECT_NEW = Verb("project.new", NewRequest, on_machine=False, effect="changes")
