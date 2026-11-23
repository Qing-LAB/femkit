"""The `model` verbs (models.md § 11.1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field, model_validator

from femkit.core import text
from femkit.core.errors import PlanStale, Refusal, Refused, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.persist import atomic_write_text, write_document, write_json
from femkit.core.schema import Model
from femkit.definitions import catalogue
from femkit.models import address, cases, check, edit, graph
from femkit.models.project import load_model, load_study, model_file, studies, study_file


class ProjectRequest(Model):
    """Which project."""

    project: Path = Field(Path("."), description="the project's folder, holding model.toml")


class CheckResult(Result):
    project: str = Field(description="the project checked")

    def text(self) -> str:
        if not self.issues:
            return f"{self.project}: the model is complete; nothing its formulation refuses"
        lines = [f"{self.project}: {text.count(len(self.issues), 'finding')}"]
        for issue in self.issues:
            lines += text.findings([issue.model_copy(update={"message": f"{issue.subject} {issue.message}"})])
        return "\n".join(lines)


@operation("model.check", request=ProjectRequest, result=CheckResult)
def model_check(req: ProjectRequest, ctx: Context) -> CheckResult:
    """Every rule of the model and its formulation but region coverage, which needs the
    geometry built; changes nothing (models.md § 3, § 11.2)."""
    project = req.project.expanduser().resolve()
    model = load_model(project, ctx)
    issues: list[Issue] = check.findings(model, catalogue.formulations(ctx), catalogue.units(ctx))
    return CheckResult(project=str(project), issues=issues)


# ------------------------------------------------------------------ studies and cases

class StudyRequest(Model):
    """Which study of which project."""

    project: Path = Field(Path("."), description="the project's folder, holding model.toml")
    study: str = Field(description="the study's name, under studies/")


class CopyRequest(StudyRequest):
    """A study to start another from."""

    to: str = Field(pattern=r"[a-z][a-z0-9_-]*", description="the new study's name")


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


@operation("study.expand", request=StudyRequest, result=ExpandOutcome, changes=True,
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
        return Plan(operation="study.expand", request=req.model_dump(mode="json"), steps=steps, issues=issues,
                    basis={"produced": sorted(ids), "kept": sorted(ids & set(written)), "orphaned": orphaned})

    def apply(self, plan: Plan, ctx: Context, observer) -> ExpandOutcome:
        req = StudyRequest.model_validate(plan.request)
        project = _project(req)
        produced = {c.id: c for c in _expanded(project, req.study, ctx)}
        if sorted(produced) != plan.basis["produced"]:
            raise PlanStale("the model or the study changed since the plan; plan again",
                            (text.typed("study", "expand", "--study", req.study),))

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


@operation("study.copy", request=CopyRequest, result=CopyOutcome, changes=True,
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
        return Plan(operation="study.copy", request=req.model_dump(mode="json"),
                    steps=(Step(id="copy", describe=f"copy studies/{req.study}/study.toml to studies/{req.to}/"),))

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

    def text(self) -> str:
        if not self.cases:
            return "no case is written: study expand writes them"
        return "\n".join(text.table([(c.id[:12], ", ".join(c.studies) or "(no study)",
                                      ", ".join(f"{k} = {v}" for k, v in c.point.items()) or "—")
                                     for c in self.cases]))


@operation("case.list", request=ProjectRequest, result=CaseListResult)
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
    return CaseListResult(cases=[CaseRow(id=cid, studies=s, point=p) for cid, (s, p) in sorted(by_case.items())])


# ------------------------------------------------------------------ edits

class SetRequest(ProjectRequest):
    """One value of the model or a study."""

    address: str = Field(description="what to set, `model:<path>` or `study:<study>:<path>` (models.md § 11.1)",
                         json_schema_extra={"cli": "argument"})
    value: str = Field(description="a TOML inline value: '\"1 nm\"', '2', '[0, 0]', '{ kind = \"potential\" }'",
                       json_schema_extra={"cli": "argument"})


class UnsetRequest(ProjectRequest):
    """One entry of the model or a study to remove."""

    address: str = Field(description="what to remove (models.md § 11.1)", json_schema_extra={"cli": "argument"})


class RenameRequest(ProjectRequest):
    """A named object and its new name."""

    address: str = Field(description="the object: a parameter, shape, region, material, source, observable or "
                                     "binding", json_schema_extra={"cli": "argument"})
    name: str = Field(description="its new name", json_schema_extra={"cli": "argument"})


class EditOutcome(Outcome):
    written: list[str] = Field(default_factory=list, description="the files the edit changed")

    def text(self) -> str:
        lines = [f"wrote {', '.join(Path(w).name for w in self.written) or 'nothing'}"]
        findings = [i for i in self.issues if i.code.startswith("model-")]
        lines.append(f"{text.count(len(findings), 'finding')} left" if findings else "the model is complete")
        return "\n".join(lines + text.findings([i.model_copy(update={"message": f"{i.subject} {i.message}"})
                                                for i in findings]))


def _edited(req, ctx: Context) -> "edit.Project":
    project = edit.Project.read(_project(req), catalogue.units(ctx),
                                extra_study=_address_of(req).study if isinstance(req, SetRequest) else None)
    a = _address_of(req)
    if isinstance(req, SetRequest):
        edit.set_value(project, a, req.value)
    elif isinstance(req, RenameRequest):
        edit.rename(project, a, req.name)
    else:
        edit.unset(project, a)
    return project


def _address_of(req) -> address.Address:
    return address.parse(req.address)


def _findings_after(project: "edit.Project", ctx: Context) -> list[Issue]:
    """What `model check` would find once the edit is made: shown, never refused (§ 11.2)."""
    model, _ = project.load()
    return [i.model_copy(update={"severity": "info"})
            for i in check.findings(model, catalogue.formulations(ctx), catalogue.units(ctx))]


class _Edit:
    verb = ""

    def plan(self, req, ctx: Context) -> Plan:
        project = _edited(req, ctx)
        changed = edit.written(project)
        what = {"set": f"set {req.address} = {getattr(req, 'value', '')}", "unset": f"remove {req.address}",
                "rename": f"rename {req.address} to {getattr(req, 'name', '')}, and every reference to it"}[self.verb]
        steps = tuple(Step(id=str(p.relative_to(project.root)), describe=f"{p.relative_to(project.root)}: {what}")
                      for p in changed)
        return Plan(operation=f"model.{self.verb}", request=req.model_dump(mode="json"), steps=steps,
                    issues=_findings_after(project, ctx),
                    basis={"files": {str(k): v for k, v in edit.Project.read(project.root, project.units,
                                                                            None).digests.items()}})

    def apply(self, plan: Plan, ctx: Context, observer) -> EditOutcome:
        req = type(self).request_model.model_validate(plan.request)
        now = {str(k): v for k, v in edit.Project.read(_project(req), catalogue.units(ctx), None).digests.items()}
        if now != plan.basis["files"]:
            raise PlanStale("a file of the project changed since the plan; plan again")
        project = _edited(req, ctx)
        files = {str(p.relative_to(project.root)): p for p in edit.written(project)}

        def do(step: Step, where: Path):
            study = next(s for s in project.docs if project.path(s) == files[step.id])
            write_document(files[step.id], project.docs[study])
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return EditOutcome(plan=plan, status=status, log=str(where), written=[str(p) for p in files.values()],
                           issues=_findings_after(project, ctx))


@operation("model.set", request=SetRequest, result=EditOutcome, changes=True,
           subject=lambda req: [_subject(_project(req))])
class ModelSet(_Edit):
    """Set one value of the model or a study, keeping the file's comments; refused when the
    file would no longer load (models.md § 11.1). The first set in an empty folder creates
    model.toml."""
    verb, request_model = "set", SetRequest


@operation("model.unset", request=UnsetRequest, result=EditOutcome, changes=True,
           subject=lambda req: [_subject(_project(req))])
class ModelUnset(_Edit):
    """Remove one entry of the model or a study; refused while anything refers to it, listing
    each place (models.md § 11.1)."""
    verb, request_model = "unset", UnsetRequest


@operation("model.rename", request=RenameRequest, result=EditOutcome, changes=True,
           subject=lambda req: [_subject(_project(req))])
class ModelRename(_Edit):
    """Rename a named object, and every reference to it: in the model, in every study, in
    every expression using a renamed parameter (models.md § 11.1)."""
    verb, request_model = "rename", RenameRequest


# ------------------------------------------------------------------ the graph

class GraphRequest(ProjectRequest):
    """The model, and optionally one study, as a graph."""

    study: str | None = Field(default=None, description="a study to show beside the model")
    mermaid: bool = Field(default=False, description="also as Mermaid text")


class GraphResult(Result):
    project: str = Field(description="the project")
    study: str | None = Field(default=None, description="the study shown")
    formulation: str | None = Field(default=None, description="the model's formulation")
    choices: list[graph.GraphChoice] = Field(default_factory=list, description="the fields that take one of a list")
    studies: list[str] = Field(default_factory=list, description="the project's studies")
    science: str | None = Field(default=None, description="its science document, for the palette's sections")
    nodes: list[graph.GraphNode] = Field(default_factory=list)
    edges: list[graph.GraphEdge] = Field(default_factory=list)
    palette: list[graph.PaletteEntry] = Field(default_factory=list)
    mermaid: str | None = Field(default=None, description="the graph as Mermaid text, when asked")

    def text(self) -> str:
        if self.mermaid is not None:
            return self.mermaid
        lines = [f"{text.count(len(self.nodes), 'node')}, {text.count(len(self.edges), 'reference')}"]
        lines += text.table([(n.address, n.kind + (f": {n.type}" if n.type else ""),
                              f"{len(n.findings)} findings" if n.findings else "") for n in self.nodes])
        return "\n".join(lines + text.findings(self.issues))


@operation("model.graph", request=GraphRequest, result=GraphResult)
def model_graph(req: GraphRequest, ctx: Context) -> GraphResult:
    """The model and a study as nodes and typed wires, with `model check`'s findings on each
    node and the formulation's palette (models.md § 11.2); `--mermaid` for a terminal."""
    project = _project(req)
    formulations = catalogue.formulations(ctx)
    if not model_file(project).is_file():
        return GraphResult(project=str(project), study=req.study, palette=graph.palette(None, req.study),
                           choices=graph.choices(None, sorted(formulations)), studies=studies(project))
    model = load_model(project, ctx)
    s = load_study(project, req.study, ctx, model) if req.study else None
    issues = check.findings(model, formulations, catalogue.units(ctx))
    nodes, edges, loose = graph.build(model, req.study, s, issues, project)
    f = formulations.get(model.formulation or "")
    return GraphResult(project=str(project), study=req.study, formulation=model.formulation,
                       choices=graph.choices(model, sorted(formulations)), studies=studies(project),
                       science=f.science if f else None, nodes=nodes, edges=edges, issues=loose,
                       palette=graph.palette(f, req.study),
                       mermaid=graph.mermaid(nodes, edges) if req.mermaid else None)


class LayoutRequest(ProjectRequest):
    """Where the page placed nodes."""

    positions: dict[str, list[float]] = Field(description="each node's address and its [x, y]")

    @model_validator(mode="before")
    @classmethod
    def _from_text(cls, data):
        if isinstance(data, dict) and isinstance(data.get("positions"), str):
            data = {**data, "positions": json.loads(data["positions"])}
        return data


class LayoutOutcome(Outcome):
    def text(self) -> str:
        return "positions saved" if self.status == "done" else "positions not saved"


@operation("model.layout", request=LayoutRequest, result=LayoutOutcome, changes=True,
           subject=lambda req: [_subject(_project(req))])
class ModelLayout:
    """Save where the page placed the graph's nodes, in .femkit/layout.json; read by no other
    step (models.md § 11.2)."""

    def plan(self, req: LayoutRequest, ctx: Context) -> Plan:
        project = _project(req)
        model = load_model(project, ctx)
        known = {n.address for n in graph.build(model, None, None, [], project)[0]}
        for name in studies(project):
            s = load_study(project, name, ctx, model)
            known |= {n.address for n in graph.build(model, name, s, [], project)[0]}
        unknown = sorted(set(req.positions) - known)
        if unknown:
            raise UsageError(f"no node is at {', '.join(unknown)}")
        return Plan(operation="model.layout", request=req.model_dump(mode="json"),
                    steps=(Step(id="layout", describe=f"save {text.count(len(req.positions), 'position')} in "
                                                      f"{graph.LAYOUT}"),),
                    basis={"known": sorted(known)})

    def apply(self, plan: Plan, ctx: Context, observer) -> LayoutOutcome:
        req = LayoutRequest.model_validate(plan.request)
        project = _project(req)

        def do(step: Step, where: Path):
            kept = {a: p for a, p in graph.positions(project).items() if a in set(plan.basis["known"])}
            write_json(project / graph.LAYOUT, {"schema": 1, "positions": {**kept, **req.positions}})
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return LayoutOutcome(plan=plan, status=status, log=str(where))
