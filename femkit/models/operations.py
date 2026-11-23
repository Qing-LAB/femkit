"""The `model` verbs (models.md § 11.1)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import Field

from femkit.core import text
from femkit.core.errors import PlanStale, Refusal, Refused, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.persist import atomic_write_text, write_json
from femkit.core.schema import Model
from femkit.definitions import catalogue
from femkit.models import cases, check
from femkit.models.project import load_model, load_study, studies, study_file


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
