"""The models domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.core.commandline import ARGUMENT
from femkit.core.schema import Model, matching
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


class GraphRequest(ProjectRequest):
    """The model, and optionally one study, as a graph."""

    study: str | None = Field(default=None, description="a study to show beside the model",
                              json_schema_extra={"context": "study"})
    mermaid: bool = Field(default=False, description="also as Mermaid text")


class ProjectsRequest(Model):
    """No inputs."""


class NewProjectRequest(Model):
    """A new project, under the projects folder (web.md § 8.6)."""

    name: str = matching(NAME, description="its folder's name", json_schema_extra=ARGUMENT)


# ------------------------------------------------------------------ the operations these requests are for

CASE_LIST = Verb("case.list", ProjectRequest)
MODEL_CHECK = Verb("model.check", ProjectRequest)
MODEL_GRAPH = Verb("model.graph", GraphRequest)
PROJECT_LIST = Verb("project.list", ProjectsRequest)
PROJECT_NEW = Verb("project.new", NewProjectRequest)
STUDY_EXPAND = Verb("study.expand", StudyRequest)
STUDY_LIST = Verb("study.list", ProjectRequest)
