"""The models domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from pydantic import Field

from femkit.core.commandline import ARGUMENT
from femkit.core.schema import Model
from femkit.core.view import Verb


class ProjectRequest(Model):
    """Which project (projects.md § 1): by its path from the projects root, or the one the
    command runs in."""

    project: str | None = Field(default=None, description="the project, by its path from the projects root; unset, "
                                                          "the project the command runs in",
                                json_schema_extra={"context": "project"})


class GraphRequest(ProjectRequest):
    """A project as a graph (models.md § 11.2)."""

    mermaid: bool = Field(default=False, description="print the graph as Mermaid text instead of the tables, to "
                                                    "paste into a document that draws Mermaid diagrams")


class StudyRequest(ProjectRequest):
    """One study of a project."""

    study: str = Field(description="the study, by its name", json_schema_extra={**ARGUMENT, "context": "study"})


# ------------------------------------------------------------------ the operations these requests are for

PROJECT_CHECK = Verb("project.check", ProjectRequest)
PROJECT_GRAPH = Verb("project.graph", GraphRequest)
STUDY_LIST = Verb("study.list", ProjectRequest)
STUDY_EXPAND = Verb("study.expand", StudyRequest)
CASE_LIST = Verb("case.list", ProjectRequest)
