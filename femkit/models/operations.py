"""The `model` verbs (models.md § 11.1)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import Field

from femkit.core import text, view
from femkit.core.errors import PlanStale, Refusal, Refused, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.persist import inline_text, write_json
from femkit.core.schema import Model, field_extras
from femkit.config import settings
from femkit.definitions import catalogue
from femkit.models import cases, check, graph
from femkit.models.schema import ModelFile
from femkit.models.project import load_model, load_study, studies, study_file
from femkit.models.requests import GraphRequest, NewProjectRequest, ProjectRequest, ProjectsRequest, StudyRequest
from femkit.config.requests import CONFIG_SET
from femkit.models.requests import CASE_LIST, MODEL_CHECK, MODEL_GRAPH, PROJECT_LIST, PROJECT_NEW, STUDY_EXPAND, STUDY_LIST


class CheckResult(Result):
    project: str = Field(description="the project checked")

    def text(self) -> str:
        if not self.issues:
            return f"{self.project}: the model is complete; nothing its formulation refuses"
        lines = [f"{self.project}: {text.count(len(self.issues), 'finding')}"]
        return "\n".join(lines + text.findings(self.issues))


@operation(MODEL_CHECK, result=CheckResult)
def model_check(req: ProjectRequest, ctx: Context) -> CheckResult:
    """Every rule of the model and its formulation but region coverage, which needs the
    geometry built; changes nothing (models.md § 3, § 11.1)."""
    project = _project(req)
    model = load_model(project, ctx)
    issues: list[Issue] = check.findings(model, catalogue.formulations(ctx), catalogue.units(ctx), project)
    return CheckResult(project=str(project), issues=issues)


# ------------------------------------------------------------------ studies and cases

def _project(req) -> Path:
    return req.project.expanduser().resolve()


def _subject(project: Path) -> str:
    """One lock per project: its writers never overlap (core.md § 5)."""
    return "project-" + hashlib.sha256(str(project).encode()).hexdigest()[:16]


def _expanded(project: Path, study: str, ctx: Context) -> list[cases.Case]:
    model = load_model(project, ctx)
    if not study_file(project, study).is_file():
        raise UsageError(f"{project} has no study {study!r} (it has: {', '.join(studies(project)) or 'none'})")
    s = load_study(project, study, ctx, model)
    return cases.expand(model, s, catalogue.formulations(ctx), catalogue.units(ctx), project)


class ExpandOutcome(Outcome):
    added: list[str] = Field(default_factory=list, description="cases written")
    kept: list[str] = Field(default_factory=list, description="cases already there")

    def text(self) -> str:
        lines = [f"{text.count(len(self.added), 'case')} added, {len(self.kept)} kept"]
        return "\n".join(lines + text.findings(self.issues))


@operation(STUDY_EXPAND, result=ExpandOutcome, changes=True,
           subject=lambda req: [_subject(_project(req))])
class StudyExpand:
    """Write one case.json for each point of the study that lacks one (models.md § 5)."""

    def plan(self, req: StudyRequest, ctx: Context) -> Plan:
        project = _project(req)
        produced = _expanded(project, req.study, ctx)
        written = cases.written_cases(project)
        ids = {c.id for c in produced}
        steps = tuple(Step(id=c.id, describe=f"write cases/{c.id[:12]}…/case.json — "
                                             + ", ".join(f"{k} = {v}" for k, v in c.point.items()) or "the one case")
                      for c in produced if c.id not in written)
        return Plan(steps=steps, basis={"produced": sorted(ids), "kept": sorted(ids & set(written))})

    def apply(self, plan: Plan, ctx: Context, observer) -> ExpandOutcome:
        req = StudyRequest.model_validate(plan.request)
        project = _project(req)
        produced = {c.id: c for c in _expanded(project, req.study, ctx)}
        if sorted(produced) != plan.basis["produced"]:
            raise PlanStale("the model or the study changed since the plan; plan again",
                            (view.command(STUDY_EXPAND, project=str(project), study=req.study),))

        def do(step: Step, where: Path):
            write_json(cases.case_dir(project, step.id) / "case.json", produced[step.id].data)
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return ExpandOutcome(plan=plan, status=status, log=str(where), added=[s.id for s in plan.steps],
                             kept=plan.basis["kept"], issues=plan.issues)


class CaseRow(Model):
    id: str = Field(description="the case's ID")
    studies: list[str] = Field(description="the studies that produce it")
    point: dict[str, str] = Field(description="its axis values, as a study writes them")


class CaseListResult(Result):
    cases: list[CaseRow] = Field(default_factory=list)
    expand: list[view.Action] = Field(default_factory=list, description="what writes each study's cases")

    def text(self) -> str:
        if not self.cases:
            return "no case is written: study expand writes them"
        return "\n".join(text.table([(c.id[:12], ", ".join(c.studies) or "(no study)",
                                      ", ".join(f"{k} = {v}" for k, v in c.point.items()) or "—")
                                     for c in self.cases]))


@operation(CASE_LIST, result=CaseListResult)
def case_list(req: ProjectRequest, ctx: Context) -> CaseListResult:
    """Every written case, with the studies that produce it and its axis values (models.md § 5)."""
    project = _project(req)
    written = cases.written_cases(project)
    by_case: dict[str, tuple[list[str], dict[str, str]]] = {cid: ([], {}) for cid in written}
    for name in studies(project):
        try:
            produced = _expanded(project, name, ctx)
        except Refusal:
            continue  # a study that does not expand now produces nothing listed
        for c in produced:
            if c.id in by_case:
                by_case[c.id][0].append(name)
                by_case[c.id][1].update({k: str(v) for k, v in c.point.items()})
    return CaseListResult(cases=[CaseRow(id=cid, studies=s, point=p) for cid, (s, p) in sorted(by_case.items())],
                          expand=[view.command(STUDY_EXPAND, label=f"expand {name}", project=str(project),
                                               study=name) for name in studies(project)])


# ------------------------------------------------------------------ edits

class GraphResult(Result):
    project: str = Field(description="the project")
    study: str | None = Field(default=None, description="the study shown")
    formulation: str | None = Field(default=None, description="the model's formulation")
    choices: list[view.Field] = Field(default_factory=list, description="the model's fields that take one of a list")
    nodes: list[graph.GraphNode] = Field(default_factory=list)
    edges: list[graph.GraphEdge] = Field(default_factory=list)
    next: Issue | None = Field(default=None, description="the model's next step: the first finding, in the chain's order")
    mermaid: str | None = Field(default=None, description="the graph as Mermaid text, when asked")

    def text(self) -> str:
        if self.mermaid is not None:
            return self.mermaid
        lines = [f"{text.count(len(self.nodes), 'node')}, {text.count(len(self.edges), 'reference')}"]
        lines += text.table([(n.address, n.kind + (f": {n.type}" if n.type else ""),
                              f"{len(n.findings)} findings" if n.findings else "") for n in self.nodes])
        return "\n".join(lines + text.findings(self.issues))


@operation(MODEL_GRAPH, result=GraphResult)
def model_graph(req: GraphRequest, ctx: Context) -> GraphResult:
    """The model and a study as nodes and typed wires, with `model check`'s findings on each
    node and the formulation's palette (models.md § 11.2); `--mermaid` for a terminal."""
    project = _project(req)
    formulations, units = catalogue.formulations(ctx), catalogue.units(ctx)
    model = load_model(project, ctx)
    s = load_study(project, req.study, ctx, model) if req.study else None
    issues = check.findings(model, formulations, units, project)
    f = formulations.get(model.formulation or "")
    nodes, edges, loose = graph.build(model, req.study, s, issues, project, f, units)
    formulation = ModelFile.model_fields["formulation"]
    choice = check.formulation_choice(formulations)
    return GraphResult(
        project=str(project), study=req.study, formulation=model.formulation,
        choices=[view.Field(label="formulation", value=inline_text(model.formulation) if model.formulation else None,
                            json_schema=choice, help=view.Help.of(formulation.description,
                                                                  field_extras(formulation).get("doc")))],
        nodes=nodes, edges=edges, issues=loose,
        next=issues[0] if issues else None,
        mermaid=graph.mermaid(nodes, edges) if req.mermaid else None)


# ------------------------------------------------------------------ projects and studies (web.md § 8.6)

class ProjectRow(Model):
    name: str = Field(description="its folder's name")
    path: str = Field(description="its folder")
    studies: list[str] = Field(default_factory=list, description="its studies")


class ProjectList(Result):
    root: str | None = Field(default=None, description="the projects folder, paths.projects; none while it is unset")
    projects: list[ProjectRow] = Field(default_factory=list)

    def text(self) -> str:
        if self.root is None:
            return "\n".join(["no projects folder"] + text.findings(self.issues))
        rows = [(p.name, ", ".join(p.studies) or "no study") for p in self.projects]
        return "\n".join([f"{text.count(len(rows), 'project')} in {text.path(self.root)}"] + text.table(rows))


def _projects_folder(ctx: Context) -> Path | None:
    return settings.load(ctx).config.paths.projects


def _state_the_folder() -> view.Action:
    return view.command(CONFIG_SET, key="paths.projects", label="choose the projects folder",
                        fills=[view.Fill(field="value", label="the projects folder", example='"/path/to/projects"')])


@operation(PROJECT_LIST, result=ProjectList)
def project_list(req: ProjectsRequest, ctx: Context) -> ProjectList:
    """The projects under paths.projects, each with its studies (web.md § 8.6)."""
    root = _projects_folder(ctx)
    if root is None:
        return ProjectList(issues=[Issue(severity="info", code="projects-unset", subject="paths.projects",
                                         label="the projects folder",
                                         message="paths.projects is unset, so no project is listed; a project is named "
                                                 "by its folder.", next=(_state_the_folder(),))])
    folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")) if root.is_dir() else []
    return ProjectList(root=str(root), projects=[ProjectRow(name=p.name, path=str(p), studies=studies(p))
                                                 for p in folders])


class StudyList(Result):
    studies: list[str] = Field(default_factory=list, description="the project's studies")

    def text(self) -> str:
        return "\n".join(self.studies) or "no study"


@operation(STUDY_LIST, result=StudyList)
def study_list(req: ProjectRequest, ctx: Context) -> StudyList:
    """A project's studies, under studies/ (models.md § 2)."""
    return StudyList(studies=studies(_project(req)))


class NewProjectOutcome(Outcome):
    path: str | None = Field(default=None, description="the new project's folder")

    def text(self) -> str:
        return f"made {text.path(self.path)}" if self.path else "nothing made"


@operation(PROJECT_NEW, result=NewProjectOutcome, changes=True,
           subject=lambda req: ["projects"])
class ProjectNew:
    """Make a new, empty project under paths.projects (web.md § 8.6)."""

    def plan(self, req: NewProjectRequest, ctx: Context) -> Plan:
        root = _projects_folder(ctx)
        if root is None:
            raise Refused("paths.projects is unset: there is no projects folder to make a project in",
                          (_state_the_folder(),))
        target = root / req.name
        if target.exists():
            raise Refused(f"{text.path(target)} is there already")
        return Plan(basis={"path": str(target)},
                    steps=(Step(id="make", describe=f"make {text.path(target)}"),))

    def apply(self, plan: Plan, ctx: Context, observer) -> NewProjectOutcome:
        target = Path(plan.basis["path"])
        if target.exists():
            raise PlanStale(f"{text.path(target)} appeared since the plan")

        def do(step: Step, where: Path):
            target.mkdir(parents=True)
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return NewProjectOutcome(plan=plan, status=status, log=str(where), path=str(target))
