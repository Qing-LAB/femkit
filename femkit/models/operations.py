"""The verbs of a project's parts above the door that read no stage (models.md § 11.1): `project
check`, `project graph` and `study list`. Each opens the project once, by its path from the projects
root or by the folder the command runs in (projects.md § 1), and runs every check once; none
writes. `case list`, `study flow` and `study prep` read or make stages, so the workflow declares
them (workflow.md § 7), with what they share of these: the project opened and checked (`checked`)
— its computed definitions computed by `project check`, `project graph` and `study prep` alone,
every other reader taking them as `study prep` keeps them (models.md § 3) — each study and whether
`study prep` can make its cases now (`studies`), one study by its name (`study_of`, `named_study`).
`project check` and `project graph` run one check, `check`: the project checked with its
definitions computed, each study's cases and each part's state, once per invocation — a built
geometry's groups a part check like any other, registered through the registry's part modules.
While an error stands, no part's next step is offered by any of the four that offer them — `project
check`, `project graph`, `study list`, `case list` — the first error being the project's next step:
one filter, the parts' states' own (`part_state.observe`; projects.md § 8). The rules each applies:
`project graph`, models.md § 11.2; the studies and their cases, models.md § 5.3. An operation's
docstring is its command's help, in the person's words."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from femkit.core import text, view
from femkit.core.errors import Refusal, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Result, operation
from femkit.core.schema import Model
from femkit.models import cases, definitions, graph, study
from femkit.models.requests import PROJECT_GRAPH, STUDY_LIST, GraphRequest, StudyRequest
from femkit.projects.requests import PROJECT_CHECK
from femkit.projects.requests import ProjectRequest
from femkit.projects import checking, door, location
from femkit.projects import state as part_state
from femkit.projects.addresses import Address
from femkit.projects.door import Opened, Part


def opened_of(req: ProjectRequest, ctx: Context) -> Opened:
    """The project the request names, or the one the command runs in, opened once."""
    return door.open_project(location.locate(ctx, req.project, Path.cwd()), ctx)


def checked(req: ProjectRequest, ctx: Context, *, compute: bool = False
            ) -> tuple[Opened, checking.Checking, list[Issue]]:
    """The project opened, its check frame, and every finding, in the chain's order. With
    ``compute``, its computed definitions computed for the constants as written, in `model_prep` —
    `project check`'s and `study prep`'s alone (models.md § 3)."""
    opened = opened_of(req, ctx)
    c = checking.Checking.of(opened, ctx, definitions.defined(opened, ctx, compute=compute))
    return opened, c, checking.findings(c)


# ------------------------------------------------------------------ project check

class PartRow(Model):
    part: str = Field(description="the part, by its address")
    file: str = Field(description="its file, from the project's folder; a global library's by its full path, shown "
                                  "from `~` where it lies under the home folder")
    section: str = Field(description="where a person finds it", json_schema_extra={"doc": "projects.md § 4"})
    state: str = Field(description="its state", json_schema_extra={"doc": "projects.md § 8"})
    shows: view.Shows = Field(description="its block's one plain word", json_schema_extra={"doc": "web.md § 7.6"})
    engines: list[str] | None = Field(default=None, description="for a study, the engines that can solve it: those "
                                      "that take its recipe's mesh at each geometry order of its cases; none where "
                                      "that cannot be told, or for another part", title="engines that can solve it",
                                      json_schema_extra={"doc": "models.md § 5.1"})


class CheckResult(Result):
    project: str = Field(description="the project checked, by its path from the projects root")
    parts: list[PartRow] = Field(default_factory=list, description="each part, with its state, in the reading order: "
                                 "by section, then what a part rests on before it",
                                 json_schema_extra={"doc": "projects.md § 4"})
    next: list[view.Action] = Field(default_factory=list, description="what its parts' states allow, each step once, "
                                    "in the reading order: the prep of each study whose cases it can make — none "
                                    "while an error stands, the first error being the next step",
                                    json_schema_extra={"doc": "models.md § 11.2"})

    @property
    def report(self) -> view.Report:
        """Its first line says what the findings are — errors, warnings, notes, as many as stand,
        the first the next step only while an error stands, a warning or a note never (models.md
        § 11.2; projects.md § 8) — and claims no more."""
        counts = {s: sum(i.severity == s for i in self.issues) for s in checking.SEVERITIES}
        said = ", ".join(text.count(n, word) for (s, n), word in zip(counts.items(), ("error", "warning", "note")) if n)
        if part_state.erred(self.issues):
            head = f"{self.project}: {said}; the first is the next step"
        elif counts["warning"]:
            head = f"{self.project}: no errors; {said}"
        else:
            head = f"{self.project}: every part loads and checks" + (f"; {said}" if said else "")
        return view.Report(blocks=[view.Text(text=head), view.Table.of(
            PartRow, [{"section": p.section, "part": p.part, "file": text.path(p.file), "state": p.state,
                       "engines": ", ".join(p.engines) if p.engines is not None else ""}
                      for p in self.parts], "section", "part", "file", "state", "engines"),
            *([view.Next(label=ALLOWED, actions=self.next)] if self.next else [])])


@operation(PROJECT_CHECK, result=CheckResult)
def project_check(req: ProjectRequest, ctx: Context) -> CheckResult:
    """Check every file of the project before anything runs, and say what is wrong: each finding
    with its file, its key and what would be right, the first being what to do next. Its computed
    definitions are computed, in model_prep, to see that each gives a number of its type. What
    needs the geometry built is said to be checked later. Each study shows the engines that can
    solve it. Changes nothing."""
    whole = check(req, ctx)
    opened, observed, layout = whole.opened, whole.observed, whole.opened.layout
    kind = layout.kind_of(study.KEY)
    solvers = {str(Address(kind, row.name)): row.engines for row, _, _ in whole.listed}
    rows = [PartRow(part=a, file=p.file, section=layout.kind(p.address.kind).section, state=observed[a].state,
                    shows=observed[a].shows, engines=solvers.get(a))
            for a, p in sorted(opened.parts.items(), key=lambda i: layout.reading(i[1].address.kind,
                                                                                   i[1].address.name))]
    return CheckResult(project=opened.project.name, parts=rows, issues=whole.found,
                       next=part_state.steps(observed, [r.part for r in rows]))


# ------------------------------------------------------------------ project graph

#: What a study's node says of its cases (web.md § 7.6, `facts`; models.md § 11.2): how many are
#: written, and how many `study prep` makes now — or why it cannot — and the engines that can solve
#: it; and what a definition's says.
WRITTEN, MAKES, ENGINES, VALUE = "cases written", "cases `study prep` makes now", "engines that can solve it", "value"


def facts(whole: Checked, ctx: Context) -> dict[str, list[view.Fact]]:
    """Each study's facts, by its address: its cases written, those `study prep` makes now, or why
    it cannot, and the engines that can solve it (web.md § 7.6; models.md §§ 5.1, 5.3); and each
    definition's value where one is at
    hand — a constant's as written, a computed one's as `project check` computed it — in the unit
    it declares, by the definitions' own formatter (models.md §§ 3, 11.2)."""
    written = cases.written(whole.opened)
    kind = whole.opened.layout.kind_of(study.KEY)
    out = {str(Address(kind, row.name)): [
        view.Fact(label=WRITTEN, value=str(len(written.get(row.name, {})))),
        view.Fact(label=MAKES, value=str(row.cases) if row.makes else row.why or ""),
        *([view.Fact(label=ENGINES, value=", ".join(row.engines))] if row.engines is not None else [])]
        for row, _, _ in whole.listed}
    o = whole.opened.layout.objects.get(checking.DEFINITION)
    if o is None:
        return out
    d = definitions.declared(whole.opened, ctx)
    values = {**d.constants(), **{n: float(q.value) for n, q in whole.c.definitions.items()}}
    return out | {str(Address(o.part, None, (*o.keys, n))): [
        view.Fact(label=VALUE, value=definitions.shown(whole.c.units, d, n, v))] for n, v in values.items() if n in d.table}


class GraphResult(Result):
    project: str = Field(description="the project, by its path from the projects root")
    study: str | None = Field(default=None, description="the study in view, through whose pairing each group is "
                                                        "wired; none: no group is wired")
    graph: view.Graph = Field(default_factory=view.Graph, description="each part, then the objects inside it — what "
                              "a part rests on before it — each reference between them, and the grouping folders",
                              json_schema_extra={"doc": "web.md § 7.6"})
    mermaid: bool = Field(default=False, description="whether its graph is written as Mermaid text, to paste into a "
                                                    "document that draws Mermaid diagrams")

    @property
    def report(self) -> view.Report:
        """Its graph, as a count and the graph itself; or, asked for as Mermaid, the one graph
        rendered as Mermaid text to copy as it is (web.md § 7.7)."""
        if self.mermaid:
            return view.Report(blocks=[view.Code(text=text.mermaid(self.graph))])
        nodes, wires = self.graph.nodes, self.graph.wires
        return view.Report(blocks=[
            view.Text(text=f"{self.project}: {text.count(len(nodes), 'node')}, {text.count(len(wires), 'wire')}"),
            self.graph])


@operation(PROJECT_GRAPH, result=GraphResult)
def project_graph(req: GraphRequest, ctx: Context) -> GraphResult:
    """Show the project as a graph: each file and what is inside it, the findings on each, and
    every wire — where one file names another, or uses a definition; with --study, each group its
    files name wired from the component that promises it, through that study's pairing. Its
    computed definitions are computed, as project check computes them. Changes nothing."""
    whole = check(req, ctx)
    paired = named_study(whole.opened, req.study) if req.study is not None else None
    built, loose = graph.build(whole.c, whole.found, whole.observed, facts(whole, ctx), paired)
    return GraphResult(project=whole.opened.project.name, study=req.study, graph=built, issues=loose,
                       mermaid=req.mermaid)


# ------------------------------------------------------------------ studies

class StudyRow(Model):
    name: str = Field(description="the study, by its name", title="study")
    makes: bool = Field(description="whether `study prep` can make its cases now", title="prep can make its cases")
    cases: int = Field(default=0, description="how many cases it makes")
    why: str | None = Field(default=None, description="why `study prep` cannot make them now", title="why not")
    engines: list[str] | None = Field(default=None, description="the engines that can solve it: those that take its "
                                      "recipe's mesh at each geometry order of its cases; none where that cannot be "
                                      "told", title="engines that can solve it",
                                      json_schema_extra={"doc": "models.md § 5.1"})


def kept(ctx: Context, opened: Opened, name: str) -> definitions.Keeping:
    """A study's computed definitions as `study prep` keeps them: what every reader but `project
    check` and `study prep` takes them from (models.md § 3)."""
    return definitions.Keeping(ctx, opened, definitions.declared(opened, ctx), name)


def studies(ctx: Context, opened: Opened, c: checking.Checking, found: list[Issue]
            ) -> list[tuple[StudyRow, list[cases.MadeCase], Issue | None]]:
    """Each study of the project, whether `study prep` can make its cases now — its cases, or why
    not — the engines that can solve it (`study.solvers`), and what the cases that rest on a
    computed value not kept for them say (`cases.waiting`): `study prep` computes them."""
    out = []
    kind = opened.layout.kind_of(study.KEY)
    for part in sorted((p for p in opened.parts.values() if p.address.kind == kind), key=lambda p: p.file):
        engines = study.solvers(c, part) if part.data is not None else None
        try:
            made, waits = cases.makes(c, cases.readable(c, part), found, kept(ctx, opened, part.address.name))
        except Refusal as exc:
            out.append((StudyRow(name=part.address.name, makes=False, why=str(exc), engines=engines), [], None))
            continue
        out.append((StudyRow(name=part.address.name, makes=True, cases=len(made), engines=engines), made,
                    cases.waiting(c, part, waits)))
    return out


def seen(ctx: Context, opened: Opened, c: checking.Checking, found: list[Issue],
         listed: list[tuple[StudyRow, list[cases.MadeCase], Issue | None]] | None = None
         ) -> dict[str, part_state.Seen]:
    """Each part's state, its word and its next steps, as its state's table gives them (projects.md
    § 8): a study whose cases `study prep` can make now offering its prep, the engine it asks for
    one of those that can solve the study (`study.solvers`; workflow.md § 7) — told here, the layer
    that reads a study's cases (``listed``, `studies`, where it is at hand) — and none while an
    error stands anywhere in the project (`part_state.observe`)."""
    listed = studies(ctx, opened, c, found) if listed is None else listed
    kind = opened.layout.kind_of(study.KEY)
    return part_state.observe(ctx, opened, found,
                              {str(Address(kind, row.name)): row.engines for row, _, _ in listed if row.makes})


#: The heading of the next steps the parts' states allow (projects.md § 8).
ALLOWED = "what the parts' states allow"


class StudyList(Result):
    project: str = Field(description="the project, by its path from the projects root")
    studies: list[StudyRow] = Field(default_factory=list, description="each study, whether `study prep` can make its "
                                                                      "cases now and, if not, why")
    next: list[view.Action] = Field(default_factory=list, description="what the studies' states allow, each step "
                                    "once: the prep of each study whose cases it can make — none while an error "
                                    "stands, the first error being the next step",
                                    json_schema_extra={"doc": "projects.md § 8"})

    @property
    def report(self) -> view.Report:
        return view.Report(blocks=[
            view.Text(text=f"{self.project}: {text.count(len(self.studies), 'study')}"),
            view.Table.of(StudyRow, [{"name": s.name, "makes": "yes" if s.makes else "no", "cases": s.cases,
                                      "engines": ", ".join(s.engines) if s.engines is not None else "",
                                      "why": s.why or ""} for s in self.studies],
                          "name", "makes", "cases", "engines", "why"),
            *([view.Next(label=ALLOWED, actions=self.next)] if self.next else [])])


@operation(STUDY_LIST, result=StudyList)
def study_list(req: ProjectRequest, ctx: Context) -> StudyList:
    """List the project's studies: whether `study prep` can make each one's cases now and, if not,
    why, and the engines that can solve each. Changes nothing."""
    opened, c, found = checked(req, ctx)
    listed = studies(ctx, opened, c, found)
    kind = opened.layout.kind_of(study.KEY)
    return StudyList(project=opened.project.name, studies=[row for row, _, _ in listed],
                     next=part_state.steps(seen(ctx, opened, c, found, listed),
                                           [str(Address(kind, row.name)) for row, _, _ in listed]),
                     issues=[w for _, _, w in listed if w is not None])


def named_study(opened: Opened, name: str) -> Part:
    """The study ``name`` names in the project, loaded or not; refused, `no-such-part`, for one the
    project lacks, offering the list of its studies."""
    asked = Address(opened.layout.kind_of(study.KEY), name)
    part = opened.parts.get(str(asked))
    if part is None:
        raise UsageError(f"the project {opened.project.name} has no study `{name}`",
                         (view.command(STUDY_LIST, project=opened.project.name),), code="no-such-part",
                         subject=str(asked))
    return part


def study_of(req: StudyRequest, ctx: Context, *, compute: bool = False
             ) -> tuple[Opened, checking.Checking, Part, list[Issue]]:
    """The project, its check frame, the study the request names and every finding — what each
    command on one study reads, ``compute`` as `checked` takes it; refused for a study the project
    lacks, or one not read whole (`cases.readable`)."""
    opened, c, found = checked(req, ctx, compute=compute)
    return opened, c, cases.readable(c, named_study(opened, req.study)), found


# ------------------------------------------------------------------ the check `project check` and `project graph` run

@dataclass
class Checked:
    """The project as `project check` checks it (models.md § 11.1): opened once, its check frame,
    every finding — its computed definitions computed — each study with whether `study prep` can
    make its cases now, and each part's state, its word and its next steps — none while an error
    stands (`seen`)."""

    opened: Opened
    c: checking.Checking
    found: list[Issue]
    listed: list[tuple[StudyRow, list[cases.MadeCase], Issue | None]]
    observed: dict[str, part_state.Seen]


def check(req: ProjectRequest, ctx: Context) -> Checked:
    """The very check `project check` runs, which `project graph` runs too (models.md § 11.1): the
    project opened, its computed definitions computed in `model_prep` for the constants as written,
    every finding, each study's cases and each part's state — one function, run once per
    invocation."""
    opened, c, found = checked(req, ctx, compute=True)
    listed = studies(ctx, opened, c, found)
    return Checked(opened, c, found, listed, seen(ctx, opened, c, found, listed))
