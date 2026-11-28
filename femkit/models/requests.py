"""The models domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from pydantic import Field

from femkit.core.commandline import ARGUMENT
from femkit.core.schema import Model
from femkit.core.view import Verb
from femkit.projects.requests import ProjectRequest


class GraphRequest(ProjectRequest):
    """A project as a graph (models.md § 11.2)."""

    study: str | None = Field(default=None, description="a study in view, by its name: each group the parts it pairs "
                                                        "name is wired from its component through its pairing; unset, "
                                                        "no group is wired", json_schema_extra={"context": "study"})
    mermaid: bool = Field(default=False, description="print the graph as Mermaid text instead of the tables, to "
                                                    "paste into a document that draws Mermaid diagrams")


class StudyRequest(ProjectRequest):
    """One study of a project."""

    study: str = Field(description="the study, by its name", json_schema_extra={**ARGUMENT, "context": "study"})


# ------------------------------------------------------------------ the operations these requests are for
#
# `project check` and `project graph` run the one check (models.md § 11.1) and read no stage, so
# both are implemented in this domain (`femkit/models/operations.py`); `project check`'s verb stands
# beside its request, the projects domain's one request of a project (`femkit/projects/requests.py`),
# so `project new` and `material import`, below this domain, name it as their next step.

PROJECT_GRAPH = Verb("project.graph", GraphRequest, on_machine=False, effect="reads")
STUDY_LIST = Verb("study.list", ProjectRequest, on_machine=False, effect="reads")
