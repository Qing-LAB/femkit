"""The `model` verbs (models.md § 11.1)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import Field

from femkit.core import text, view
from femkit.core.errors import PlanStale, Refusal, Refused, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.persist import atomic_write_text, write_document, write_json
from femkit.core.schema import Model, field_extras
from femkit.config import settings
from femkit.definitions import catalogue
from femkit.models import adds, address, cases, check, edit, graph, history
from femkit.models.schema import ModelFile
from femkit.models.project import file_of, load_model, load_study, model_file, studies, study_file
from femkit.models.requests import (CopyRequest, GraphRequest, MODEL_SET, NewProjectRequest, ProjectRequest, ProjectsRequest, RenameRequest, SetRequest, StudyRequest, UnsetRequest, WriteRequest)
from femkit.config.requests import CONFIG_SET
from femkit.models.requests import CASE_LIST, MODEL_CHECK, MODEL_GRAPH, MODEL_REDO, MODEL_RENAME, MODEL_UNDO, MODEL_UNSET, MODEL_WRITE, PROJECT_LIST, PROJECT_NEW, STUDY_COPY, STUDY_EXPAND, STUDY_LIST


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
    geometry built; changes nothing (models.md § 3, § 11.2)."""
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
    orphaned: list[str] = Field(default_factory=list, description="preparations of cases the study no longer produces")

    def text(self) -> str:
        lines = [f"{text.count(len(self.added), 'case')} added, {len(self.kept)} kept"]
        if self.orphaned:
            lines.append(f"{text.count(len(self.orphaned), 'preparation')} orphaned, kept with their runs: "
                         + ", ".join(o[:12] for o in self.orphaned))
        return "\n".join(lines + text.findings(self.issues))


@operation(STUDY_EXPAND, result=ExpandOutcome, changes=True,
           subject=lambda req: [_subject(_project(req))])
class StudyExpand:
    """Write one case.json for each point of the study that lacks one (models.md § 5)."""

    def plan(self, req: StudyRequest, ctx: Context) -> Plan:
        project = _project(req)
        produced = _expanded(project, req.study, ctx)
        written = cases.written_cases(project)
        prepared = project / "studies" / req.study / "prepared"
        ids = {c.id for c in produced}
        orphaned = sorted(p.name for p in prepared.iterdir() if p.is_dir() and p.name not in ids) \
            if prepared.is_dir() else []
        steps = tuple(Step(id=c.id, describe=f"write cases/{c.id[:12]}…/case.json — "
                                             + ", ".join(f"{k} = {v}" for k, v in c.point.items()) or "the one case")
                      for c in produced if c.id not in written)
        issues = [Issue(severity="info", code="case-orphaned", subject=f"study:{req.study}:prepared.{o}",
                        message=f"a preparation of {o[:12]}…, a case the study no longer produces: kept with its runs")
                  for o in orphaned]
        return Plan(steps=steps, issues=issues,
                    basis={"produced": sorted(ids), "kept": sorted(ids & set(written)), "orphaned": orphaned})

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
                             kept=plan.basis["kept"], orphaned=plan.basis["orphaned"], issues=plan.issues)


class CopyOutcome(Outcome):
    written: str | None = Field(default=None, description="the new study.toml")

    def text(self) -> str:
        return f"wrote {self.written}" if self.written else "nothing written"


@operation(STUDY_COPY, result=CopyOutcome, changes=True,
           subject=lambda req: [_subject(_project(req))])
class StudyCopy:
    """Start a study from another: its study.toml, comments and all (models.md § 5)."""

    def plan(self, req: CopyRequest, ctx: Context) -> Plan:
        project = _project(req)
        source, target = study_file(project, req.study), study_file(project, req.to)
        if not source.is_file():
            raise UsageError(f"{project} has no study {req.study!r} (it has: {', '.join(studies(project)) or 'none'})")
        if target.exists():
            raise Refused(f"the study {req.to!r} exists already; choose another name")
        return Plan(steps=(Step(id="copy", describe=f"copy studies/{req.study}/study.toml to studies/{req.to}/"),))

    def apply(self, plan: Plan, ctx: Context, observer) -> CopyOutcome:
        req = CopyRequest.model_validate(plan.request)
        project = _project(req)
        target = study_file(project, req.to)

        def do(step: Step, where: Path):
            if target.exists():
                raise PlanStale(f"the study {req.to!r} appeared since the plan")
            atomic_write_text(target, study_file(project, req.study).read_text(encoding="utf-8"))
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return CopyOutcome(plan=plan, status=status, log=str(where), written=str(target))


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

class EditOutcome(Outcome):
    written: list[str] = Field(default_factory=list, description="the files the edit changed")

    def text(self) -> str:
        lines = [f"wrote {', '.join(Path(w).name for w in self.written) or 'nothing'}"]
        lines.append(f"{text.count(len(self.issues), 'finding')} left" if self.issues else "the model is complete")
        return "\n".join(lines + text.findings(self.issues))


def _findings_after(project: "edit.Project", ctx: Context) -> list[Issue]:
    """What `model check` would find once the edit is made: shown, never refused (§ 11.2)."""
    model, _ = project.load()
    return [i.model_copy(update={"severity": "info"})
            for i in check.findings(model, catalogue.formulations(ctx), catalogue.units(ctx), project.root)]


class _Edit:
    """One edit of the model or a study (models.md § 11.1). Each kind says what it changes and
    how a person reads it; reading the files, checking them, writing them and recording the
    edit for undo are done here, once."""

    verb: view.Verb                         # its declaration's, written in by `@operation`

    def change(self, project: "edit.Project", req) -> None:
        raise NotImplementedError

    def label(self, req) -> str:
        raise NotImplementedError

    def _edited(self, req, ctx: Context) -> "edit.Project":
        project = edit.Project.read(_project(req), catalogue.units(ctx), extra_study=address.parse(req.address).study)
        self.change(project, req)
        return project

    def plan(self, req, ctx: Context) -> Plan:
        project = self._edited(req, ctx)
        steps = tuple(Step(id=str(p.relative_to(project.root)), describe=f"{p.relative_to(project.root)}: "
                                                                          f"{self.label(req)}")
                      for p in edit.written(project))
        return Plan(steps=steps, issues=_findings_after(project, ctx),
                    basis={"files": {str(k): v for k, v in edit.Project.read(project.root, project.units,
                                                                            None).digests.items()}})

    def apply(self, plan: Plan, ctx: Context, observer) -> EditOutcome:
        req = self.verb.request.model_validate(plan.request)
        now = {str(k): v for k, v in edit.Project.read(_project(req), catalogue.units(ctx), None).digests.items()}
        if now != plan.basis["files"]:
            raise PlanStale("a file of the project changed since the plan; plan again")
        project = self._edited(req, ctx)
        files = {str(p.relative_to(project.root)): p for p in edit.written(project)}
        study_of = {project.path(s): s for s in project.docs}
        before = {k: history.text_of(p) for k, p in files.items()}

        def do(step: Step, where: Path):
            write_document(files[step.id], project.docs[study_of[files[step.id]]])
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        if status == "done" and files:
            history.record(project.root, self.label(req),
                           [history.Change(study=study_of[p], before=before[k], after=history.text_of(p))
                            for k, p in files.items()])
        return EditOutcome(plan=plan, status=status, log=str(where), written=[str(p) for p in files.values()],
                           issues=_findings_after(project, ctx))


class _Turn:
    """Undo or redo: the last edit that stands taken back, or the next undone one made again —
    refused when a file it changed has changed since, by hand (models.md § 11.1)."""
    back: bool                              # undo; else redo

    def _edit(self, project: Path) -> tuple[history.History, history.Edit | None]:
        h = history.read(project)
        i = h.at - 1 if self.back else h.at
        return h, (h.edits[i] if 0 <= i < len(h.edits) else None)

    def plan(self, req: ProjectRequest, ctx: Context) -> Plan:
        project = _project(req)
        h, e = self._edit(project)
        if e is None:
            return Plan(basis={"at": h.at})
        for c in e.changes:
            path = file_of(project, c.study)
            if history.text_of(path) != (c.after if self.back else c.before):
                raise Refused(f"{path.relative_to(project)} has changed since `{e.label}`, so it is not "
                              f"{'undone' if self.back else 'redone'}")
        steps = tuple(Step(id=str(file_of(project, c.study).relative_to(project)),
                           describe=f"{file_of(project, c.study).relative_to(project)}: "
                                    f"{'take back' if self.back else 'make again'} {e.label}") for c in e.changes)
        return Plan(basis={"at": h.at}, steps=steps)

    def apply(self, plan: Plan, ctx: Context, observer) -> EditOutcome:
        project = _project(ProjectRequest.model_validate(plan.request))
        h, e = self._edit(project)
        if h.at != plan.basis["at"]:
            raise PlanStale("the project's edits changed since the plan; plan again")
        texts = {str(file_of(project, c.study).relative_to(project)): c.before if self.back else c.after
                 for c in (e.changes if e else [])}

        def do(step: Step, where: Path):
            target = project / step.id                     # the model's file or a study's: file_of made the id
            if texts[step.id] is None:
                target.unlink(missing_ok=True)
            else:
                atomic_write_text(target, texts[step.id])
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        if status == "done" and e is not None:
            history.write(project, h.model_copy(update={"at": h.at - 1 if self.back else h.at + 1}))
        after = _findings_after(edit.Project.read(project, catalogue.units(ctx)), ctx) if model_file(project).exists() else []
        return EditOutcome(plan=plan, status=status, log=str(where), written=[str(project / p) for p in texts],
                           issues=after)


@operation(MODEL_UNDO, result=EditOutcome, changes=True, confirm=False,
           subject=lambda req: [_subject(_project(req))])
class ModelUndo(_Turn):
    """Take back the last edit of the model or a study: each file it changed restored to its
    text before it; refused when one has changed since, by hand (models.md § 11.1)."""
    back = True


@operation(MODEL_REDO, result=EditOutcome, changes=True, confirm=False,
           subject=lambda req: [_subject(_project(req))])
class ModelRedo(_Turn):
    """Make again the last edit undone (models.md § 11.1)."""
    back = False


@operation(MODEL_SET, result=EditOutcome, changes=True, confirm=False, undoable=True,
           subject=lambda req: [_subject(_project(req))])
class ModelSet(_Edit):
    """Set one value of the model or a study, keeping the file's comments; refused when the
    file would no longer load (models.md § 11.1). The first set in an empty folder creates
    model.toml."""

    def change(self, project, req: SetRequest) -> None:
        edit.set_value(project, address.parse(req.address), req.value)

    def label(self, req: SetRequest) -> str:
        return f"set {req.address} = {req.value}"


@operation(MODEL_WRITE, result=EditOutcome, changes=True, confirm=False, undoable=True,
           subject=lambda req: [_subject(_project(req))])
class ModelWrite(_Edit):
    """Write an object's text — its table, comments and all, or a value — as one edit; refused
    when any file of the project would no longer load (models.md § 11.1)."""

    def change(self, project, req: WriteRequest) -> None:
        edit.write(project, address.parse(req.address), req.text)

    def label(self, req: WriteRequest) -> str:
        return f"write {req.address}"


@operation(MODEL_UNSET, result=EditOutcome, changes=True, confirm=False, undoable=True,
           subject=lambda req: [_subject(_project(req))])
class ModelUnset(_Edit):
    """Remove one entry of the model or a study; refused while anything refers to it, listing
    each place (models.md § 11.1)."""

    def change(self, project, req: UnsetRequest) -> None:
        edit.unset(project, address.parse(req.address))

    def label(self, req: UnsetRequest) -> str:
        return f"remove {req.address}"


@operation(MODEL_RENAME, result=EditOutcome, changes=True, confirm=False, undoable=True,
           subject=lambda req: [_subject(_project(req))])
class ModelRename(_Edit):
    """Rename a named object, and every reference to it: in the model, in every study, in
    every expression using a renamed parameter (models.md § 11.1)."""

    def change(self, project, req: RenameRequest) -> None:
        edit.rename(project, address.parse(req.address), req.name)

    def label(self, req: RenameRequest) -> str:
        return f"rename {req.address} to {req.name}, and every reference to it"


# ------------------------------------------------------------------ the graph

class GraphResult(Result):
    project: str = Field(description="the project")
    study: str | None = Field(default=None, description="the study shown")
    formulation: str | None = Field(default=None, description="the model's formulation")
    choices: list[view.Field] = Field(default_factory=list, description="the model's fields that take one of a list")
    nodes: list[graph.GraphNode] = Field(default_factory=list)
    edges: list[graph.GraphEdge] = Field(default_factory=list)
    palette: list[adds.Entry] = Field(default_factory=list, description="what may be added, in the chain's order")
    next: Issue | None = Field(default=None, description="the model's next step: the first finding, in the chain's order")
    undo: view.Action | None = Field(default=None, description="what takes back the last edit")
    redo: view.Action | None = Field(default=None, description="what makes the last undone edit again")
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
        choices=[view.Field(label="formulation", value=f'"{model.formulation}"' if model.formulation else None,
                            json_schema=choice, help=view.Help.of(formulation.description,
                                                                  field_extras(formulation).get("doc")),
                            set=view.command(MODEL_SET, label="choose the formulation", project=str(project),
                                             address="model:formulation",
                                             fills=[view.Fill(field="value", label="formulation", json_schema=choice)]))],
        nodes=nodes, edges=edges, issues=loose, palette=adds.palette(project, req.study, f, units),
        next=issues[0] if issues else None,
        undo=view.command(MODEL_UNDO, label="undo", project=str(project)),
        redo=view.command(MODEL_REDO, label="redo", project=str(project)),
        mermaid=graph.mermaid(nodes, edges) if req.mermaid else None)


# ------------------------------------------------------------------ projects and studies (web.md § 8.6)

class ProjectRow(Model):
    name: str = Field(description="its folder's name")
    path: str = Field(description="its folder")
    studies: list[str] = Field(default_factory=list, description="its studies")


class ProjectList(Result):
    root: str | None = Field(default=None, description="the projects folder, web.projects; none while it is unset")
    projects: list[ProjectRow] = Field(default_factory=list)

    def text(self) -> str:
        if self.root is None:
            return "\n".join(["no projects folder"] + text.findings(self.issues))
        rows = [(p.name, ", ".join(p.studies) or "no study") for p in self.projects]
        return "\n".join([f"{text.count(len(rows), 'project')} in {text.path(self.root)}"] + text.table(rows))


def _projects_folder(ctx: Context) -> Path | None:
    return settings.load(ctx).config.web.projects


def _state_the_folder() -> view.Action:
    return view.command(CONFIG_SET, key="web.projects", label="choose the projects folder",
                        fills=[view.Fill(field="value", label="the projects folder", example='"/path/to/projects"')])


@operation(PROJECT_LIST, result=ProjectList)
def project_list(req: ProjectsRequest, ctx: Context) -> ProjectList:
    """The projects under web.projects, each with its studies (web.md § 8.6)."""
    root = _projects_folder(ctx)
    if root is None:
        return ProjectList(issues=[Issue(severity="info", code="projects-unset", subject="web.projects",
                                         label="the projects folder",
                                         message="web.projects is unset, so no project is listed; a project is named "
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
    """Make a new, empty project under web.projects (web.md § 8.6)."""

    def plan(self, req: NewProjectRequest, ctx: Context) -> Plan:
        root = _projects_folder(ctx)
        if root is None:
            raise Refused("web.projects is unset: there is no projects folder to make a project in",
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
