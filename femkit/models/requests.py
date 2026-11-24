"""The models domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.core.commandline import ARGUMENT
from femkit.core.schema import Model
from femkit.models.schema import NAME, STUDY
from pathlib import Path
from pydantic import Field


class ProjectRequest(Model):
    """Which project."""

    project: Path = Field(Path("."), description="the project's folder, holding model.toml",
                          json_schema_extra={"context": "project"})


class StudyRequest(Model):
    """Which study of which project."""

    project: Path = Field(Path("."), description="the project's folder, holding model.toml",
                          json_schema_extra={"context": "project"})
    study: str = Field(description="the study's name, under studies/", json_schema_extra={"context": "study"})


class CopyRequest(StudyRequest):
    """A study to start another from."""

    to: str = Field(pattern=f"^{STUDY.pattern}$", description="the new study's name")


class SetRequest(ProjectRequest):
    """One value of the model or a study."""

    address: str = Field(description="what to set, `model:<path>` or `study:<study>:<path>`",
                         json_schema_extra={**ARGUMENT, "doc": "models.md § 11.1"})
    value: str = Field(description="a TOML inline value: '\"1 nm\"', '2', '[0, 0]', '{ kind = \"potential\" }'",
                       json_schema_extra={**ARGUMENT, "toml": "whole"})


class UnsetRequest(ProjectRequest):
    """One entry of the model or a study to remove."""

    address: str = Field(description="what to remove", json_schema_extra={**ARGUMENT, "doc": "models.md § 11.1"})


class RenameRequest(ProjectRequest):
    """A named object and its new name."""

    address: str = Field(description="the object: a parameter, shape, region, material, source, observable or "
                                     "binding", json_schema_extra=ARGUMENT)
    name: str = Field(description="its new name", json_schema_extra=ARGUMENT)


class GraphRequest(ProjectRequest):
    """The model, and optionally one study, as a graph."""

    study: str | None = Field(default=None, description="a study to show beside the model",
                              json_schema_extra={"context": "study"})
    mermaid: bool = Field(default=False, description="also as Mermaid text")


class ProjectsRequest(Model):
    """No inputs."""


class NewProjectRequest(Model):
    """A new project, under the projects folder (web.md § 8.6)."""

    name: str = Field(description="its folder's name", pattern=f"^{NAME.pattern}$", json_schema_extra=ARGUMENT)


class WriteRequest(ProjectRequest):
    """An object's text, written whole."""

    address: str = Field(description="the object", json_schema_extra={**ARGUMENT, "doc": "models.md § 11.1"})
    text: str = Field(description="its text: its table as a TOML document of its own, comments and all, or a "
                                  "value's TOML inline text", json_schema_extra=ARGUMENT)


# ------------------------------------------------------------------ the operations these requests are for

CASE_LIST = Verb("case.list", ProjectRequest)
MODEL_CHECK = Verb("model.check", ProjectRequest)
MODEL_GRAPH = Verb("model.graph", GraphRequest)
MODEL_REDO = Verb("model.redo", ProjectRequest)
MODEL_RENAME = Verb("model.rename", RenameRequest)
MODEL_SET = Verb("model.set", SetRequest)
MODEL_UNDO = Verb("model.undo", ProjectRequest)
MODEL_UNSET = Verb("model.unset", UnsetRequest)
MODEL_WRITE = Verb("model.write", WriteRequest)
PROJECT_LIST = Verb("project.list", ProjectsRequest)
PROJECT_NEW = Verb("project.new", NewProjectRequest)
STUDY_COPY = Verb("study.copy", CopyRequest)
STUDY_EXPAND = Verb("study.expand", StudyRequest)
STUDY_LIST = Verb("study.list", ProjectRequest)
