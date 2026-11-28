"""The workflow domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from pydantic import Field

from femkit.core.view import Verb
from femkit.jobs.requests import target
from femkit.models.requests import StudyRequest
from femkit.projects.requests import ProjectRequest


class StagesRequest(StudyRequest):
    """One study's stages, for one machine: the record a stage's identity is formed with
    (workflow.md §§ 4, 7) — femkit's own option, never a value of the calculation (api.md § 4)."""

    target: str | None = target("the machine record a stage's identity is formed with", doc="workflow.md § 7",
                                context="target")


class PrepRequest(StagesRequest):
    """One study's prep, for one machine, and the engine that solves it (workflow.md § 7): which
    party solves — the person's decision, never a value of the calculation (api.md § 4; ADR 0025
    decision 1)."""

    engine: str | None = Field(default=None, description="the engine that solves the study, by name — chosen here, "
                               "never in the study's file, and switched at any time; left out, its cases, geometries "
                               "and meshes are made all the same, and the engine is chosen when the study is solved",
                               json_schema_extra={"doc": "workflow.md § 7", "choices": "engines"})


# ------------------------------------------------------------------ the operations these requests are for

CASE_LIST = Verb("case.list", ProjectRequest, on_machine=False, effect="reads")
STUDY_FLOW = Verb("study.flow", StagesRequest, on_machine=False, effect="reads")
STUDY_PREP = Verb("study.prep", PrepRequest, on_machine=False, effect="changes")
