"""The verbs of a project's parts above the door (models.md § 11.1): `project check`, `project
graph`, `study list`, `study expand` and `case list`. Each opens the project once, by its path
from the projects root or by the folder the command runs in (projects.md § 1), and runs every
check once; only `study expand` writes, and only femkit's own cases, each study's in its own
folder (models.md § 5.3). The rules each applies: `project check`, models.md § 11.1 and
projects.md § 8; `project graph`, models.md § 11.2; the studies and their cases, models.md § 5.3.
A case written before its materials' data changed is flagged by `case list`, and the plan of `study
expand` names it beside each case it writes in its place (materials.md § 6). An operation's
docstring is its command's help, in the person's words."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

from pydantic import Field

from femkit.core import text, view
from femkit.core.errors import Refusal, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.schema import Model
from femkit.models import cases, graph, study
from femkit.models.parts import PROPERTY
from femkit.models.requests import (CASE_LIST, PROJECT_CHECK, PROJECT_GRAPH, STUDY_EXPAND, STUDY_LIST, GraphRequest,
                                    ProjectRequest, StudyRequest)
from femkit.projects import checking, door, location, names
from femkit.projects import state as part_state
from femkit.projects.addresses import Address
from femkit.projects.door import Opened, Part



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
    file: str = Field(description="its file, from the project's folder; a global library's by its full path, shown "
                                  "from `~` where it lies under the home folder")
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
            rows=[{"part": p.part, "file": text.path(p.file), "state": p.state} for p in self.parts])])


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


def _expansion(req: StudyRequest, ctx: Context) -> tuple[Opened, checking.Checking, Part, list[cases.Expanded]]:
    """The project, its check frame, the study and its cases; refused for a study the project
    lacks, or one that does not expand."""
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
    return opened, c, part, cases.expand(c, part, found)


@operation(STUDY_EXPAND, result=ExpandOutcome, changes=True, subject="plan")
class StudyExpand:
    """Write the study's cases: one `case.json` for each point of its axes it has not written yet,
    in the study's own folder of `cases/`. Refused while a file it uses does not load or has a
    finding to resolve."""

    def observe(self, req: StudyRequest, ctx: Context) -> dict:
        """The cases the study makes, and those it wrote already."""
        opened, _, _, made = _expansion(req, ctx)
        return {"cases": sorted(m.id for m in made), "written": sorted(cases.written(opened).get(req.study, {}))}

    def plan(self, req: StudyRequest, ctx: Context) -> Plan:
        """One step for each case the study lacks, each saying, where it is so, that it is written
        because its materials' data changed since the case it takes the place of (materials.md
        § 6) — held, by its ID, as `renewed`: each new case's ID, with the case written before."""
        opened, c, part, made = _expansion(req, ctx)
        there = cases.written(opened).get(req.study, {})
        ids = {m.id for m in made}
        renewed = {new: (old, filled) for old, (filled, new) in _now(c, part, there, ids).items()
                   if new != old and new in ids and new not in there}

        def describe(m: cases.Expanded) -> str:
            said = (f"write {cases.path(req.study, m.id[:12] + '…')}: "
                    + (", ".join(f"{k} = {_shown(v)}" for k, v in m.point.items()) or "the one case"))
            if m.id not in renewed:
                return said
            old, filled = renewed[m.id]
            return (f"{said} — in place of {old[:12]}…, its materials' data changed: "
                    + "; ".join(f"{f.group}'s {f.material}, dataset {f.dataset}: {', '.join(map(str, f.differs))}"
                                for f in filled if f.differs))

        steps = tuple(Step(id=m.id, describe=describe(m)) for m in made if m.id not in there)
        return Plan(subjects=(opened.project.subject,), steps=steps,
                    holds={"project": opened.project.name, "cases": {m.id: m.data for m in made if m.id not in there},
                           "kept": sorted(m.id for m in made if m.id in there),
                           "renewed": {new: old for new, (old, _) in sorted(renewed.items())}})

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

class CaseMaterial(Model):
    """One property of one body's material in a case, where its material is found now, and how
    its data differs from what the material holds now (materials.md §§ 4, 6)."""

    group: str = Field(description="the body group it fills")
    material: str = Field(description="the material, by its name in its library")
    found: str | None = Field(default=None, description="where that name finds it now, by the name that names it "
                                                        "exactly: the project's own as it is, the global library's as "
                                                        "`GLOBAL/<name>`; none where neither holds it")
    property: str = Field(description="the property")
    dataset: str = Field(description="the dataset the case used, by its name")
    source: str | None = Field(default=None, description="the dataset's source, as the case holds it")
    changed: list[cases.DataChange] = Field(default_factory=list, description="for a case its study no longer "
                                            "makes, each way the dataset's data differs from what its material holds "
                                            "now; none where it holds the same",
                                            json_schema_extra={"doc": "materials.md § 6"})


#: The columns of `case list`'s materials, each with its heading (materials.md §§ 4, 6).
MATERIAL_COLUMNS = dict(case="case", group="body", material="material", found="found now", property="property",
                        dataset="dataset", source="source", changed="changed since")


class CaseRow(Model):
    id: str = Field(description="the case's ID: the SHA-256 of its content", json_schema_extra={"doc": "models.md § 5.3"})
    point: dict[str, str] = Field(default_factory=dict, description="its axis values, as its study writes them — for "
                                                                    "a case the study no longer makes, as its file "
                                                                    "holds them, exactly, in canonical units")
    made: bool = Field(default=False, description="whether its study makes it now; one it no longer makes is kept")
    why: str | None = Field(default=None, description="why its file does not load")
    materials: list[CaseMaterial] = Field(default_factory=list, description="each body's material, with the dataset "
                                          "and source of each property, as the case holds them, where its material "
                                          "is found now, and, for a case its study no longer makes, how that data "
                                          "differs from what the material holds now",
                                          json_schema_extra={"doc": "materials.md §§ 4, 6"})


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
            changed = [w for w in s.written if any(m.changed for m in w.materials)]
            if changed:
                verb = "holds" if len(changed) == 1 else "hold"
                blocks.append(view.Text(text=f"{text.count(len(changed), 'case')} of {s.name} no longer made {verb} "
                                             "material data that has changed since; expanding the study again writes "
                                             "new ones, and keeps these"))
            filled = [(w.id[:12], m) for w in s.written for m in w.materials]
            if filled:
                blocks.append(view.Table(
                    columns=view.columns(*MATERIAL_COLUMNS, **MATERIAL_COLUMNS),
                    rows=[{"case": case, "group": m.group, "material": m.material, "found": m.found or "nowhere",
                           "property": m.property, "dataset": m.dataset, "source": m.source or "",
                           "changed": "; ".join(map(str, m.changed))}
                          for case, m in filled]))
        return view.Report(blocks=blocks)


@operation(CASE_LIST, result=CaseList)
def case_list(req: ProjectRequest, ctx: Context) -> CaseList:
    """List each study's cases: those written for it, with their axis values and whether the study
    still makes them; each body's material, where it is found now, and the dataset and source the
    case used — and, for a case no longer made, how that data differs from what the material holds
    now; and whether the study expands now and, if not, why. Changes nothing."""
    opened, c, found = _checked(req, ctx)
    on_disk = cases.written(opened)
    out: list[StudyCases] = []
    studies = {row.name: (row, made) for row, made in _studies(opened, c, found)}
    kind = opened.layout.kind_of(study.KEY)
    for name in sorted({*studies, *on_disk}):
        row, made = studies.get(name, (StudyRow(name=name, expands=False, why="no such study"), []))
        now = {m.id: m for m in made}
        part = opened.parts.get(str(Address(kind, name)))
        held_now = _now(c, part, on_disk.get(name, {}), set(now))
        rows = []
        for case_id, held in _in_order(part, made, on_disk.get(name, {})):
            if isinstance(held, str):
                rows.append(CaseRow(id=case_id, why=held))
                continue
            point = ({k: _shown(v) for k, v in now[case_id].point.items()} if case_id in now
                     else {k: cases.shown(v, c.units) for k, v in held.point.items()})
            rows.append(CaseRow(id=case_id, made=case_id in now, point=point, materials=[
                CaseMaterial(group=f.group, material=f.material, found=f.found, property=f.property, dataset=f.dataset,
                             source=f.source, changed=list(f.differs))
                for f in held_now[case_id][0]]))
        out.append(StudyCases(**row.model_dump(), written=rows))
    return CaseList(project=opened.project.name, studies=out)


def _in_order(part: Part | None, made: list[cases.Expanded], written: dict[str, cases.Case | str]
              ) -> list[tuple[str, cases.Case | str]]:
    """A study's written cases in the order `case list` shows them (models.md § 5.3): those the
    study makes now, then those it no longer makes, each group by its point — axis by axis as the
    study declares its axes, each value where the study lists it (`made`, in the order its points
    are made, holds each listed value as a case does), a value it no longer lists after those, by
    its value — then by ID; a case whose file does not load last."""
    axes = list(part.data.axes) if part is not None and part.data is not None else sorted(
        {k for held in written.values() if not isinstance(held, str) for k in held.point})
    listed: dict[str, list[Any]] = {k: [] for k in axes}
    for m in made:
        for k, held in m.data["point"].items():
            if k in listed and held not in listed[k]:
                listed[k].append(held)

    def value(held: Any) -> tuple:
        """A value the study no longer lists, by its value: a quantity's or a number's, else its text."""
        number = held["value"] if isinstance(held, dict) and set(held) == {"value", "dimension"} else held
        try:
            return 0, Fraction(number)
        except (TypeError, ValueError):
            return 1, str(held)

    now = {m.id for m in made}

    def place(item: tuple[str, cases.Case | str]) -> tuple:
        case_id, held = item
        if isinstance(held, str):
            return 2, (), case_id
        point = tuple((0, listed[k].index(held.point[k])) if held.point.get(k) in listed[k]
                      else (1, *value(held.point[k])) if k in held.point else (2,) for k in axes)
        return 0 if case_id in now else 1, point, case_id

    return sorted(written.items(), key=place)


def _now(c: checking.Checking, part: Part | None, written: dict[str, cases.Case | str], made: set[str]
         ) -> dict[str, tuple[list[cases.Filled], str]]:
    """Each case of a study written and loading: each body's material and dataset as the case holds
    them, where its material is found now — the global library's read where the project no longer
    names it — and, for one ``made`` lacks, how its data differs from what the material holds now;
    and the ID the case would have with that data (`cases.held_now`; materials.md §§ 4, 6)."""
    loaded = {i: case for i, case in written.items() if not isinstance(case, str)}
    door.load_library(c.opened, c.opened.layout.objects[PROPERTY].part,
                      {names.bare(f["material"]) for case in loaded.values()
                       for f in case.component.get("assign", {}).values()}, c.units)
    out = {}
    for i, case in loaded.items():
        filled, renewed = cases.held_now(c, part, case)
        out[i] = ([f if i not in made else replace(f, differs=()) for f in filled], renewed if i not in made else i)
    return out
