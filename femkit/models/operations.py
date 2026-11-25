"""The verbs of a project's parts above the door (models.md § 11.1): `project check`, `project
graph`, `study list`, `study expand` and `case list`. Each opens the project once, by its path
from the projects root or by the folder the command runs in (projects.md § 1), and runs every
check once; only `study expand` writes, and only femkit's own cases, each study's in its own
folder (models.md § 5.3). The rules each applies: `project check`, models.md § 11.1 and
projects.md § 8; `project graph`, models.md § 11.2; the studies and their cases, models.md § 5.3.
An operation's docstring is its command's help, in the person's words."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from femkit.core import text, view
from femkit.core.errors import Refusal, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.schema import Model
from femkit.models import cases, graph, study
from femkit.models.requests import (CASE_LIST, PROJECT_CHECK, PROJECT_GRAPH, STUDY_EXPAND, STUDY_LIST, GraphRequest,
                                    ProjectRequest, StudyRequest)
from femkit.projects import checking, door, location
from femkit.projects import state as part_state
from femkit.projects.addresses import Address
from femkit.projects.door import Opened



def _opened(req: ProjectRequest, ctx: Context) -> Opened:
    """The project the request names, or the one the command runs in, opened once."""
    return door.open_project(location.locate(ctx, req.project, Path.cwd()), ctx)


def _checked(req: ProjectRequest, ctx: Context) -> tuple[Opened, checking.Checking, list[Issue]]:
    """The project opened, its check frame, and every finding, in the chain's order."""
    opened = _opened(req, ctx)
    c = checking.Checking.of(opened, ctx)
    return opened, c, checking.findings(c)


# ------------------------------------------------------------------ project check

class PartRow(Model):
    part: str = Field(description="the part, by its address")
    file: str = Field(description="its file, from the project's folder")
    state: str = Field(description="its state", json_schema_extra={"doc": "projects.md § 8"})


class CheckResult(Result):
    project: str = Field(description="the project checked, by its path from the projects root")
    parts: list[PartRow] = Field(default_factory=list, description="each part, with its state; what a part rests "
                                                                   "on comes before it")

    def report(self) -> view.Report:
        """Its first line says what the findings are — errors, warnings, notes, as many as stand,
        the first the next step (models.md § 11.2) — and claims no more."""
        counts = {s: sum(i.severity == s for i in self.issues) for s in checking.SEVERITIES}
        said = ", ".join(text.count(n, word) for (s, n), word in zip(counts.items(), ("error", "warning", "note")) if n)
        if counts["error"] or counts["warning"]:
            head = f"{self.project}: {'' if counts['error'] else 'no errors; '}{said}; the first is the next step"
        else:
            head = f"{self.project}: every part loads and checks" + (f"; {said}" if said else "")
        return view.Report(blocks=[view.Text(text=head), view.Table(
            columns=view.columns("part", "file", "state", part="part", file="file", state="state"),
            rows=[{"part": p.part, "file": p.file, "state": p.state} for p in self.parts])])


@operation(PROJECT_CHECK, result=CheckResult)
def project_check(req: ProjectRequest, ctx: Context) -> CheckResult:
    """Check every file of the project before anything runs, and say what is wrong: each finding
    with its file, its key and what would be right, the first being what to do next. What needs
    the geometry built is said to be checked later. Changes nothing."""
    opened, _, found = _checked(req, ctx)
    states = part_state.observe(ctx, opened, found)
    rank = {k: v.rank for k, v in opened.layout.kinds.items()}
    rows = [PartRow(part=a, file=p.file, state=states[a])
            for a, p in sorted(opened.parts.items(), key=lambda i: (rank[i[1].address.kind], i[1].file))]
    return CheckResult(project=opened.project.name, parts=rows, issues=found)


# ------------------------------------------------------------------ project graph

class GraphResult(Result):
    project: str = Field(description="the project, by its path from the projects root")
    nodes: list[graph.GraphNode] = Field(default_factory=list, description="each part, then the objects inside it; "
                                                                           "what a part rests on comes before it")
    edges: list[graph.GraphEdge] = Field(default_factory=list, description="each reference between them")
    mermaid: str | None = Field(default=None, description="the graph as Mermaid text, when asked")

    def report(self) -> view.Report:
        if self.mermaid is not None:
            return view.Report(blocks=[view.Code(text=self.mermaid)])
        return view.Report(blocks=[
            view.Text(text=f"{self.project}: {text.count(len(self.nodes), 'node')}, "
                           f"{text.count(len(self.edges), 'wire')}"),
            view.Table(columns=view.columns("node", "kind", "state", "findings", node="node", kind="kind",
                                            state="state", findings="findings"),
                       rows=[{"node": n.address, "kind": n.kind + (f": {n.type}" if n.type else ""),
                              "state": n.state or "", "findings": len(n.findings) or ""} for n in self.nodes]),
            view.Table(columns=view.columns("source", "target", "where", source="from", target="to",
                                            where="written at"),
                       rows=[{"source": e.source, "target": e.target, "where": e.address} for e in self.edges])])


@operation(PROJECT_GRAPH, result=GraphResult)
def project_graph(req: GraphRequest, ctx: Context) -> GraphResult:
    """Show the project as a graph: each file and what is inside it, the findings on each, and
    every wire — where one file names another, or uses a parameter. Changes nothing."""
    opened, _, found = _checked(req, ctx)
    nodes, edges, loose = graph.build(opened, found, part_state.observe(ctx, opened, found))
    return GraphResult(project=opened.project.name, nodes=nodes, edges=edges, issues=loose,
                       mermaid=graph.mermaid(nodes, edges) if req.mermaid else None)


# ------------------------------------------------------------------ studies

class StudyRow(Model):
    name: str = Field(description="the study, by its name")
    expands: bool = Field(description="whether it expands into cases now")
    cases: int = Field(default=0, description="how many cases it makes")
    why: str | None = Field(default=None, description="why it does not expand")


STUDY_COLUMNS = dict(study="study", expands="expands", cases="cases", why="why it does not expand")


def _studies(opened: Opened, c: checking.Checking, found: list[Issue]
             ) -> list[tuple[StudyRow, list[cases.Expanded]]]:
    """Each study of the project, whether it expands — its cases, or why not."""
    out = []
    kind = opened.layout.kind_of(study.KEY)
    for part in sorted((p for p in opened.parts.values() if p.address.kind == kind), key=lambda p: p.file):
        if part.data is None:
            out.append((StudyRow(name=part.address.name, expands=False, why="its file does not load"), []))
            continue
        try:
            made = cases.expand(c, part, found)
        except Refusal as exc:
            out.append((StudyRow(name=part.address.name, expands=False, why=str(exc)), []))
            continue
        out.append((StudyRow(name=part.address.name, expands=True, cases=len(made)), made))
    return out


class StudyList(Result):
    project: str = Field(description="the project, by its path from the projects root")
    studies: list[StudyRow] = Field(default_factory=list, description="each study, whether it expands and, if not, "
                                                                      "why")

    def report(self) -> view.Report:
        return view.Report(blocks=[
            view.Text(text=f"{self.project}: {text.count(len(self.studies), 'study')}"),
            view.Table(columns=view.columns(*STUDY_COLUMNS, **STUDY_COLUMNS),
                       rows=[{"study": s.name, "expands": "yes" if s.expands else "no", "cases": s.cases,
                              "why": s.why or ""} for s in self.studies])])


@operation(STUDY_LIST, result=StudyList)
def study_list(req: ProjectRequest, ctx: Context) -> StudyList:
    """List the project's studies: whether each expands into cases now and, if not, why. Changes
    nothing."""
    opened, c, found = _checked(req, ctx)
    return StudyList(project=opened.project.name, studies=[row for row, _ in _studies(opened, c, found)])


class ExpandOutcome(Outcome):
    study: str = Field(description="the study, by its name")
    added: list[str] = Field(default_factory=list, description="each case written, by its ID")
    kept: list[str] = Field(default_factory=list, description="each case it makes that was written already")

    def report(self) -> view.Report:
        return view.Report(blocks=[
            view.Text(text=f"{self.study}: {text.count(len(self.added), 'case')} written, {len(self.kept)} kept"),
            view.Table(columns=view.columns("case", "written", case="case", written="written"),
                       rows=[{"case": i, "written": "now"} for i in self.added]
                       + [{"case": i, "written": "before"} for i in self.kept])])


def _expansion(req: StudyRequest, ctx: Context) -> tuple[Opened, list[cases.Expanded]]:
    """The study's cases; refused for a study the project lacks, or one that does not expand."""
    opened, c, found = _checked(req, ctx)
    asked = Address(opened.layout.kind_of(study.KEY), req.study)
    part = opened.parts.get(str(asked))
    if part is None:
        raise UsageError(f"the project {opened.project.name} has no study `{req.study}`",
                         (view.command(STUDY_LIST, project=opened.project.name),), code="no-such-part",
                         subject=str(asked))
    if part.data is None:
        raise UsageError(f"the study `{req.study}` does not load; `project check` says why",
                         (view.command(PROJECT_CHECK, project=opened.project.name),), code="unloadable",
                         subject=str(part.address))
    return opened, cases.expand(c, part, found)


@operation(STUDY_EXPAND, result=ExpandOutcome, changes=True, subject="plan")
class StudyExpand:
    """Write the study's cases: one `case.json` for each point of its axes it has not written yet,
    in the study's own folder of `cases/`. Refused while a file it uses does not load or has a
    finding to resolve."""

    def observe(self, req: StudyRequest, ctx: Context) -> dict:
        """The cases the study makes, and those it wrote already."""
        opened, made = _expansion(req, ctx)
        return {"cases": sorted(m.id for m in made), "written": sorted(cases.written(opened).get(req.study, {}))}

    def plan(self, req: StudyRequest, ctx: Context) -> Plan:
        opened, made = _expansion(req, ctx)
        there = cases.written(opened).get(req.study, {})
        steps = tuple(Step(id=m.id, describe=f"write {cases.path(req.study, m.id[:12] + '…')}: "
                                             + (", ".join(f"{k} = {_shown(v)}" for k, v in m.point.items())
                                                or "the one case"))
                      for m in made if m.id not in there)
        return Plan(subjects=(opened.project.subject,), steps=steps,
                    holds={"project": opened.project.name, "cases": {m.id: m.data for m in made if m.id not in there},
                           "kept": sorted(m.id for m in made if m.id in there)})

    def apply(self, plan: Plan, ctx: Context, observer) -> ExpandOutcome:
        req = StudyRequest.model_validate(plan.request)
        opened = _opened(req, ctx)

        def do(step: Step, where: Path):
            cases.write(opened, req.study, cases.Expanded(step.id, {}, plan.holds["cases"][step.id]))
            return "done", None

        status, log = run_steps(plan, ctx, observer, do)
        return ExpandOutcome(plan=plan, status=status, log=str(log), study=req.study,
                             added=[s.id for s in plan.steps] if status == "done" else [], kept=plan.holds["kept"])


def _shown(value: Any) -> str:
    """An axis value as the study writes it."""
    return value if isinstance(value, str) else str(value)


# ------------------------------------------------------------------ case list

class CaseRow(Model):
    id: str = Field(description="the case's ID: the SHA-256 of its content", json_schema_extra={"doc": "models.md § 5.3"})
    point: dict[str, str] = Field(default_factory=dict, description="its axis values, as its study writes them — as "
                                                                    "its file holds them for a case the study no "
                                                                    "longer makes")
    made: bool = Field(default=False, description="whether its study makes it now; one it no longer makes is kept")
    why: str | None = Field(default=None, description="why its file does not load")


class StudyCases(StudyRow):
    written: list[CaseRow] = Field(default_factory=list, description="every case of the study written, by its ID")


class CaseList(Result):
    project: str = Field(description="the project, by its path from the projects root")
    studies: list[StudyCases] = Field(default_factory=list, description="each study, whether it expands and, if "
                                                                        "not, why, with the cases written for it")

    def report(self) -> view.Report:
        blocks: list[Any] = [view.Text(text=f"{self.project}: "
                                            f"{text.count(sum(len(s.written) for s in self.studies), 'case')} written")]
        for s in self.studies:
            state = f"makes {text.count(s.cases, 'case')}" if s.expands else f"does not expand: {s.why}"
            blocks.append(view.Text(text=f"{s.name}: {text.count(len(s.written), 'case')} written; {state}"))
            if s.written:
                blocks.append(view.Table(
                    columns=view.columns("case", "point", "now", case="case", point="point", now="made now"),
                    rows=[{"case": w.id[:12], "now": "yes" if w.made else "no",
                           "point": w.why or ", ".join(f"{k} = {v}" for k, v in w.point.items()) or "the one point"}
                          for w in s.written]))
        return view.Report(blocks=blocks)


@operation(CASE_LIST, result=CaseList)
def case_list(req: ProjectRequest, ctx: Context) -> CaseList:
    """List each study's cases: those written for it, with their axis values and whether the study
    still makes them; and whether it expands now and, if not, why. Changes nothing."""
    opened, c, found = _checked(req, ctx)
    on_disk = cases.written(opened)
    out: list[StudyCases] = []
    studies = {row.name: (row, made) for row, made in _studies(opened, c, found)}
    for name in sorted({*studies, *on_disk}):
        row, made = studies.get(name, (StudyRow(name=name, expands=False, why="no such study"), []))
        now = {m.id: m for m in made}
        rows = []
        for case_id, held in sorted(on_disk.get(name, {}).items()):
            if isinstance(held, str):
                rows.append(CaseRow(id=case_id, why=held))
            elif case_id in now:
                rows.append(CaseRow(id=case_id, made=True, point={k: _shown(v) for k, v in now[case_id].point.items()}))
            else:
                rows.append(CaseRow(id=case_id, point={k: cases.shown(v, c.units) for k, v in held.point.items()}))
        out.append(StudyCases(**row.model_dump(), written=rows))
    return CaseList(project=opened.project.name, studies=out)
