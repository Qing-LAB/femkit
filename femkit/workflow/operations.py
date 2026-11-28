"""The commands that read or make stages (workflow.md § 7), each declared here, the lowest layer
that reads stages: `case list`, whose rules stay the models' (models.md § 11.1); `study flow`, a
study's workflow graph for one machine, each stage with its state, folder and actions; `study
prep`, the one step between a written study and its launch; and `project save`, of the page alone,
a file written exactly as the person typed it, its plan the change's impact (`impact`, § 10;
projects.md § 7). `project check` reads no stage, so the models declare it beside `project graph`
(models.md § 11.1). Each opens the project once, by its path from the projects root or by the
folder the command runs in (projects.md § 1). An operation's docstring is its command's help, in
the person's words.

`study prep`'s steps — definitions, cases, machine, stages, jobs — are one table, `PREP`, stated
once: its plan runs each in order, each deciding within what the ones before it fixed, every job
folder's prepare planned in memory (jobs.md § 3), so every refusal comes before anything is
written; its plan holds a step for each thing it writes, and its apply writes each by the step of
the table that planned it. What it does to a stage is the stage table's own tasks (workflow.md
§ 6) — which it does, whether a stage is placed behind what it waits on, the state's (`state.tasks`)
— and whether a stage's request, or a job's, is stated again, folder writing's and the jobs
domain's (`folder_writing.restated`, `folders.restated_job`); how its stages become its meshing
job's batches and sequence is folder writing's (`folder_writing.placed`, `folder_writing.job`): this
module conducts them. Where a step that needs the machine cannot go on — a refusal of `WAITS`, by
its kind and code — the steps after it wait, what needs no machine is written, and what the stages
wait for is one finding of its plan and its outcome, with the steps that settle it. The engine that
solves is the request's, `--engine`, which no file names: with one, it is checked first — one femkit
declares, `no-such-engine`, and one that takes the study's mesh, by the models' one rule
(`study.solvers`), its refusal the error `no-input` at the study's `mesh` (§ 2.2) — and its outcome
names it, saying solving is not built yet; with none, the geometries and meshes are made all the
same, serving every engine, and a note, `no-engine`, says the engine is chosen when the study is
solved, with the command that chooses it, its choices the engines that can solve the study by the
same rule (`_engine`). Its outcome names the machine first, and its next steps are the launch the state of
each job not launched yet that holds the study's stages allows, as the jobs domain reads it, its
heading the outcome's.

`case list` names each case's stages, found by their `stage.json` (workflow.md § 4) in the
door's listing of a study's stage folders, whichever machine made them; a stage whose `stage.json`
does not read is a finding naming that file wherever a stage is listed, never dropped unsaid.

The project's computed definitions are computed by `project check` and `project graph` — in
memory, writing nothing of the project's — and by prep's first step, which keeps their values for its study,
`computed/<study>/definitions.nc`, each run once per plan by what it rests on (models.md § 3);
`case list` and `study flow` take them as prep keeps them, and a case resting on one not kept in
sync waits for prep, said as a finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from pydantic import Field

from femkit.core import persist, text, view
from femkit.core.errors import Refusal, Refused, Unstated, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import PAGE_ALONE, Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.schema import Model, meant
from femkit.definitions import catalogue
from femkit.jobs import folders, prepare, record, runs
from femkit.jobs.request import JobRequest, Resources
from femkit.jobs.requests import JOB_PREPARE
from femkit.models import axes, cases, definitions
from femkit.models.operations import ALLOWED as PARTS_ALLOW, StudyRow, checked, kept, opened_of, seen, studies, study_of
from femkit.models import study
from femkit.projects import door
from femkit.projects import state as part_state
from femkit.projects.addresses import Address, Stage as StageAddress
from femkit.projects.checking import Checking
from femkit.projects.door import Opened, Part
from femkit.projects.project import Library, Project
from femkit.projects.requests import ProjectRequest
from femkit.workflow import folder_writing, graph, identity, impact, state
from femkit.workflow.requests import CASE_LIST, STUDY_FLOW, STUDY_PREP, PrepRequest, StagesRequest
from femkit.projects.requests import PROJECT_SAVE, SaveRequest


# ------------------------------------------------------------------ case list

class CaseMaterial(Model):
    """One property of one body's material in a case, where its material is found now, and how
    its data differs from what the material holds now (materials.md §§ 4, 6)."""

    group: str = Field(description="the body group it fills", title="body")
    material: str = Field(description="the material, by its name in its library")
    found: str | None = Field(default=None, description="where that name finds it now, by the name that names it "
                                                        "exactly: the project's own as it is, the global library's as "
                                                        "`GLOBAL/<name>`; none where neither holds it",
                              title="found now")
    property: str = Field(description="the property")
    dataset: str = Field(description="the dataset the case used, by its name")
    source: str | None = Field(default=None, description="the dataset's source, as the case holds it")
    changed: list[cases.DataChange] = Field(default_factory=list, description="for a case its study no longer "
                                            "makes, each way the dataset's data differs from what its material holds "
                                            "now; none where it holds the same", title="changed since",
                                            json_schema_extra={"doc": "materials.md § 6"})


class CaseStage(Model):
    """One stage of a case (workflow.md §§ 4, 6), found by its `stage.json`, whichever machine made
    it."""

    stage: str = Field(description="the stage, by its address", json_schema_extra={"doc": "workflow.md § 4"})
    target: str = Field(description="the machine it was made for, by its record's identity of the host",
                        json_schema_extra={"doc": "workflow.md § 4"})
    state: str = Field(description="its state", json_schema_extra={"doc": "workflow.md § 6"})
    shows: view.Shows = Field(description="its block's one plain word", json_schema_extra={"doc": "web.md § 7.6"})


class CaseRow(Model):
    id: str = Field(description="the case's ID: the SHA-256 of its content", title="case",
                    json_schema_extra={"doc": "models.md § 5.3"})
    point: dict[str, str] = Field(default_factory=dict, description="its axis values, as its study writes them — for "
                                                                    "a case the study no longer makes, as its file "
                                                                    "holds them, exactly, in its study's display "
                                                                    "units, else in canonical units")
    made: bool = Field(default=False, description="whether its study makes it now; one it no longer makes is kept",
                       title="made now")
    why: str | None = Field(default=None, description="why its file does not load")
    materials: list[CaseMaterial] = Field(default_factory=list, description="each body's material, with the dataset "
                                          "and source of each property, as the case holds them, where its material "
                                          "is found now, and, for a case its study no longer makes, how that data "
                                          "differs from what the material holds now",
                                          json_schema_extra={"doc": "materials.md § 6"})
    stages: list[CaseStage] = Field(default_factory=list, description="each stage made of it, for any machine, "
                                    "with its state", json_schema_extra={"doc": "workflow.md § 4"})


class StudyCases(StudyRow):
    written: list[CaseRow] = Field(default_factory=list, description="every case of the study written, by its ID")


class CaseList(Result):
    project: str = Field(description="the project, by its path from the projects root")
    studies: list[StudyCases] = Field(default_factory=list, description="each study, whether `study prep` can make "
                                                                        "its cases now and, if not, why, with the "
                                                                        "cases written for it")
    next: list[view.Action] = Field(default_factory=list, description="what the studies' states allow, each step "
                                    "once: the prep of each study whose cases it can make — none while an error "
                                    "stands, the first error being the next step",
                                    json_schema_extra={"doc": "projects.md § 8"})

    @property
    def report(self) -> view.Report:
        blocks: list[Any] = [view.Text(text=f"{self.project}: "
                                            f"{text.count(sum(len(s.written) for s in self.studies), 'case')} written")]
        for s in self.studies:
            state = f"makes {text.count(s.cases, 'case')}" if s.makes else f"`study prep` cannot make its cases: {s.why}"
            blocks.append(view.Text(text=f"{s.name}: {text.count(len(s.written), 'case')} written; {state}"))
            if s.written:
                blocks.append(view.Table.of(
                    CaseRow, [{"id": cases.short(w.id), "made": "yes" if w.made else "no",
                               "point": w.why or ", ".join(f"{k} = {v}" for k, v in w.point.items()) or "the one point"}
                              for w in s.written], "id", "point", "made"))
            changed = [w for w in s.written if any(m.changed for m in w.materials)]
            if changed:
                verb = "holds" if len(changed) == 1 else "hold"
                blocks.append(view.Text(text=f"{text.count(len(changed), 'case')} of {s.name} no longer made {verb} "
                                             "material data that has changed since; `study prep` writes "
                                             "new ones, and keeps these"))
            made = [(cases.short(w.id), g) for w in s.written for g in w.stages]
            if made:     # each stage beside its case, by the case's ID
                blocks.append(view.Table.over(
                    [view.column(CaseRow, "id"), *(view.column(CaseStage, k) for k in ("stage", "target", "state"))],
                    [{"id": case, "stage": g.stage, "target": g.target, "state": g.state}
                     for case, g in made]))
            filled = [(cases.short(w.id), m) for w in s.written for m in w.materials]
            if filled:   # each body's material beside its case, by the case's ID
                blocks.append(view.Table.over(
                    [view.column(CaseRow, "id"), *(view.column(CaseMaterial, k) for k in (
                        "group", "material", "found", "property", "dataset", "source", "changed"))],
                    [{"id": case, "group": m.group, "material": m.material, "found": m.found or "nowhere",
                      "property": m.property, "dataset": m.dataset, "source": m.source or "",
                      "changed": "; ".join(map(str, m.changed))}
                     for case, m in filled]))
        if self.next:
            blocks.append(view.Next(label=PARTS_ALLOW, actions=self.next))
        return view.Report(blocks=blocks)


@operation(CASE_LIST, result=CaseList)
def case_list(req: ProjectRequest, ctx: Context) -> CaseList:
    """List each study's cases: those written for it, with their axis values and whether the study
    still makes them; each body's material, where it is found now, and the dataset and source the
    case used — and, for a case no longer made, how that data differs from what the material holds
    now; each case's geometries and meshes, made for any machine, with their states; and whether
    `study prep` can make the study's cases now and, if not, why. Changes nothing but what reading
    a run writes once: that its job is over."""
    opened, c, found = checked(req, ctx)
    on_disk = cases.written(opened)
    out: list[StudyCases] = []
    unread: list[Issue] = []
    said = studies(ctx, opened, c, found)
    listed = {row.name: (row, made) for row, made, _ in said}
    unread += [w for _, _, w in said if w is not None]
    kind = opened.layout.kind_of(study.KEY)
    for name in sorted({*listed, *on_disk}):
        row, made = listed.get(name, (StudyRow(name=name, makes=False, why="no such study"), []))
        making = {m.id: m for m in made}
        part = opened.parts.get(str(Address(kind, name)))
        held_now = cases.now(c, part, on_disk.get(name, {}), set(making))
        staged = _stages(ctx, opened, name, unread)
        rows = []
        for case_id, held in _in_order(part, made, on_disk.get(name, {})):
            if isinstance(held, str):
                rows.append(CaseRow(id=case_id, why=held))
                continue
            point = ({k: cases.as_written(v) for k, v in making[case_id].point.items()} if case_id in making
                     else {k: cases.shown(v, c.units, part.data.display if part is not None and part.data else ())
                           for k, v in held.point.items()})
            rows.append(CaseRow(id=case_id, made=case_id in making, point=point, materials=[
                CaseMaterial(group=f.group, material=f.material, found=f.found, property=f.property, dataset=f.dataset,
                             source=f.source, changed=list(f.differs))
                for f in held_now[case_id][0]], stages=_of_case(ctx, name, held, staged)))
        out.append(StudyCases(**row.model_dump(), written=rows))
    return CaseList(project=opened.project.name, studies=out, issues=unread,
                    next=part_state.steps(seen(ctx, opened, c, found, said),
                                          [str(Address(kind, row.name)) for row, _, _ in said]))


def _made_from(ctx: Context, folder: Path, kind: str) -> tuple[identity.MadeFrom | None, Issue | None]:
    """What the stage of ``kind`` in ``folder`` is made from, as its `stage.json` says (workflow.md
    § 4); where it says nothing that reads — no such file, one that does not read in the shape
    femkit writes, or one naming another kind than its folder's — a finding naming that file
    instead, so no stage is passed over unsaid."""
    file = identity.file(ctx, folder)
    held = identity.read(ctx, folder)
    if held.reads and held.value.kind == kind:
        return held.value, None
    why = ("is not there" if not held.there else held.problem if not held.reads
           else f"names the stage kind {held.value.kind}, in a {kind} stage's folder")
    return None, Issue(severity="warning", code=state.UNREADABLE, subject=str(file),
                       message=f"{text.path(file)} {why}: what the stage in {text.path(folder)} is made from cannot "
                               "be read")


def _unread(ctx: Context, derived: graph.Derived) -> list[Issue]:
    """A finding for each stage of ``derived`` whose folder is there and whose `stage.json` does not
    read (workflow.md § 4)."""
    return [issue for s in derived.stages.values() if s.folder.is_dir()
            for issue in [_made_from(ctx, s.folder, s.kind)[1]] if issue is not None]


def _stages(ctx: Context, opened: Opened, study_name: str, unread: list[Issue]
            ) -> list[tuple[str, identity.MadeFrom, state.Seen]]:
    """A study's stages as its folders hold them (workflow.md § 4): each found by its `stage.json`,
    read by its model, whichever machine made it — never by forming an ID from this machine's facts
    — with what it is made from and its state; each observed, and listed, after every stage it
    takes from, as its `stage.json` names them. A folder whose `stage.json` does not read adds its
    finding to ``unread``."""
    found: dict[str, tuple[Path, identity.MadeFrom]] = {}
    for (kind, id_), folder in sorted(door.stages(opened, study_name).items()):
        made, issue = _made_from(ctx, folder, kind)
        if made is not None:
            found[str(StageAddress(study_name, kind, id_))] = (folder, made)
        else:
            unread.append(issue)
    seen: dict[str, state.Seen] = {}

    def observed(address: str) -> state.Seen:
        if address not in seen:
            folder, made = found[address]
            took = [str(StageAddress(study_name, t.kind, t.id)) for t in made.takes_from.values()]
            seen[address] = state.observe(ctx, address, folder, project=opened.project.name, study=study_name,
                                          target=None, takes_from=[observed(a) for a in dict.fromkeys(took) if a in found])
        return seen[address]

    for address in found:
        observed(address)
    return [(address, found[address][1], seen[address]) for address in seen]


def _of_case(ctx: Context, study_name: str, case: cases.Case,
             staged: list[tuple[str, identity.MadeFrom, state.Seen]]) -> list[CaseStage]:
    """The stages made of ``case``, by what each is made from (workflow.md § 4): a stage of the
    case's component but its assignment, or of its recipe resolved, every stage it takes from one
    of the case's too — ``staged`` listing each after every stage it takes from."""
    component, recipe = case.component.drawing(), case.mesh
    mine: dict[str, tuple[identity.MadeFrom, state.Seen]] = {}
    for a, m, s in staged:
        own = m.component == component if m.component is not None else m.recipe == recipe
        if own and all(str(StageAddress(study_name, t.kind, t.id)) in mine for t in m.takes_from.values()):
            mine[a] = (m, s)
    word = state.machine(ctx).word
    return [CaseStage(stage=a, target=record.shown(m.target), state=s.state.value,
                      shows=word(s.state))
            for a, (m, s) in mine.items()]


def _in_order(part: Part | None, made: list[cases.MadeCase], written: dict[str, cases.Case | str]
              ) -> list[tuple[str, cases.Case | str]]:
    """A study's written cases in the order `case list` shows them (models.md § 5.3): those the
    study makes now, then those it no longer makes, each group by its point's place in the cases'
    order (`axes.place`) — what is crossed unit by unit, a group stepping together as one, each
    step where the study makes it (`made`, in the order its points are made), a value it no longer
    makes after those, by its value — then by ID; a case whose file does not load last."""
    units = axes.crossed(part) if part is not None and part.data is not None else [
        (k,) for k in sorted({k for held in written.values() if not isinstance(held, str) for k in held.point})]
    listed = axes.steps(units, [m.case.point for m in made])

    def value(held: cases.Exact | str) -> tuple:
        """A value the study no longer lists, by its value: a quantity's or a number's, else its text."""
        q = cases.quantity(held)
        try:
            return 0, q.value if q is not None else Fraction(held)
        except (TypeError, ValueError):
            return 1, str(held)

    now = {m.id for m in made}

    def place(item: tuple[str, cases.Case | str]) -> tuple:
        case_id, held = item
        if isinstance(held, str):
            return 2, (), case_id
        return 0 if case_id in now else 1, axes.place(units, listed, held.point, value), case_id

    return sorted(written.items(), key=place)


# ------------------------------------------------------------------ a study's stages

def _again(req: StagesRequest, opened: Opened, verb: view.Verb, **more: Any) -> view.Action:
    """A command of the study, typed again — each value of the request the command takes, the
    project by its name, and what a refusal names in ``more``."""
    held = {name: getattr(req, name) for name in verb.request.model_fields if name in type(req).model_fields}
    return view.command(verb, **{**held, "project": opened.project.name, **more})


def _flowed(req: StagesRequest, ctx: Context) -> tuple[Opened, Checking, Part, list[cases.MadeCase], prepare.Target,
                                                       Issue | None]:
    """The project, its check frame, the study, the cases it makes now — each computed definition
    as prep keeps it — the machine a stage's identity is formed with, chosen as `job prepare`
    chooses it (workflow.md § 3), and what the cases resting on a computed value not kept in sync
    say: their stages wait for prep's definitions step (models.md § 3) — refused as the study's
    cases refuse it, unchanged: what stops a case stops its stages (models.md § 5.3; workflow.md
    § 7)."""
    opened, c, part, found = study_of(req, ctx)
    made, waits = cases.makes(c, part, found, kept(ctx, opened, req.study))
    t = prepare.choose(ctx, req.target, lambda name: _again(req, opened, STUDY_FLOW, target=name))
    return opened, c, part, made, t, cases.waiting(c, part, waits)


class FlowResult(Result):
    project: str = Field(description="the project, by its path from the projects root")
    study: str = Field(description="the study, by its name")
    target: str = Field(description="the machine record each stage's identity is formed with")
    graph: view.Graph = Field(default_factory=view.Graph, description="each case's stages, the artifacts "
                              "flowing between them — each output with the file its stage's newest finished run "
                              "holds and the lines that open it — each case a box, the stages cases share one of "
                              "their own", json_schema_extra={"doc": "workflow.md § 3"})
    next: list[view.Action] = Field(default_factory=list, description="what its stages' states allow, each step once, "
                                    "with the words its state's table gives it", json_schema_extra={"doc": "workflow.md § 6"})

    @property
    def report(self) -> view.Report:
        nodes = self.graph.nodes
        cases_ = [b for b in self.graph.boxes if b.kind == view.CASE]
        return view.Report(blocks=[
            view.Text(text=f"{self.study} for {self.target}: {text.count(len(nodes), 'stage')}, "
                           f"{text.count(len(cases_), 'case')}"),
            self.graph,
            *([view.Next(label="what its stages' states allow", actions=self.next)] if self.next else [])])


@operation(STUDY_FLOW, result=FlowResult)
def study_flow(req: StagesRequest, ctx: Context) -> FlowResult:
    """Show a study's workflow for a machine — this one's unless --target names another: each case's
    geometry and mesh, each with its state, its folder and what to do next,
    and the outputs a finished one holds with the line that opens each. Changes nothing but what
    reading a run writes once: that its job is over."""
    opened, c, part, made, t, waits = _flowed(req, ctx)
    derived = graph.derive(ctx, opened, c, part, made, t)
    seen = graph.observed(ctx, derived, req.target)
    made_now, unopened = graph.outputs(ctx, derived, seen)
    drawn = graph.graph(ctx, derived, seen, made_now)
    steps = {a.command: a for n in drawn.nodes for a in n.actions}       # each step once, with its table's words
    return FlowResult(project=opened.project.name, study=req.study, target=t.name, graph=drawn,
                      next=list(steps.values()),
                      issues=[*derived.issues, *_unread(ctx, derived), *unopened, *([waits] if waits else [])])


# ------------------------------------------------------------------ study prep

#: The refusals where prep's machine step cannot go on, each by its kind and its code — each code
#: exported by the code that raises it (workflow.md § 7; core.md § 9): the target's — another
#: machine's record there and none named, no record of this machine, this machine's record stale
#: (jobs.md § 3) — and a stage's identity's, no fingerprint of its environment (§ 4). Met by a step
#: that needs the machine, prep writes what needs none, and what
#: the stages wait for is that refusal as a finding. Every other refusal writes nothing — a
#: `--target` naming no record, the person's slip, `UsageError` · `no-record`, among them.
WAITS: frozenset[tuple[type[Refusal], str]] = frozenset({
    (Unstated, prepare.TARGET_UNCHOSEN), (Unstated, prepare.NO_RECORD), (Refused, prepare.STALE),
    (Unstated, identity.NO_FINGERPRINT)})


def _waits_on(exc: Refusal) -> bool:
    """Whether ``exc`` is a refusal prep's machine step waits on (`WAITS`), by its kind and code."""
    return any(isinstance(exc, kind) and exc.code == code for kind, code in WAITS)


class PrepCase(Model):
    """One case `study prep` makes, as its report shows it (workflow.md § 7)."""

    id: str = Field(description="the case, by its ID", title="case", json_schema_extra={"doc": "models.md § 5.3"})
    point: str = Field(description="every value of its point, as the study writes it")
    written: str = Field(description="whether it is written now, or was before")


class PrepValue(Model):
    """The project's computed definitions at one set of its constants, as `study prep` keeps them
    (models.md § 3)."""

    at: str = Field(default="", description="the constants that differ from one set to another, as they are at this "
                                            "one; none where one set is computed")
    values: str = Field(description="every constant and computed definition, each in its declared unit")


class PrepRow(Model):
    stage: str = Field(description="the stage, by its address", json_schema_extra={"doc": "workflow.md § 4"})
    state: str = Field(description="its state", json_schema_extra={"doc": "workflow.md § 6"})
    does: list[str] = Field(default_factory=list, description="what `study prep` does to it, each by the stage "
                                                              "table's own task", json_schema_extra={"doc": "workflow.md § 6"})
    describe: list[str] = Field(default_factory=list, description="the same, each in the stage table's sentence")
    folder: str = Field(description="its calculation folder, for the machine prepped for",
                        json_schema_extra={"doc": "projects.md § 2"})


class PrepJob(Model):
    """One job `study prep` writes, or states again (workflow.md §§ 5, 7): the sequence of its
    batches."""

    sequence: str = Field(description="the job, by its sequence's launch folder's full path",
                          json_schema_extra={"doc": "jobs.md § 1.2"})
    batches: list[str] = Field(default_factory=list, description="its batches, by their launch folders' names")
    restated: str | None = Field(default=None, description="for a job a prep before wrote, how its resources are "
                                                           "stated again; none for one written now")


#: What prep says of the engine it was given (workflow.md § 7): the study prepared for it — or, in its
#: plan, to be — and that solving is not built yet, in plain words (docs/README.md M5).
PREPARED = {"planned": "is to be prepared", "done": "is prepared"}
NOT_BUILT = "solving it is not built yet"


class PrepOutcome(Outcome):
    project: str = Field(default="", description="the project, by its path from the projects root")
    study: str = Field(default="", description="the study, by its name")
    engine: str | None = Field(default=None, description="the engine the study is prepared for, as `--engine` names "
                               "it; none where none is chosen", json_schema_extra={"doc": "workflow.md § 7"})
    target: str | None = Field(default=None, description="the machine record the stages were prepared for; none "
                                                         "where the machine step could not go on, and what the "
                                                         "stages wait for is a finding, with the steps that settle it",
                               json_schema_extra={"doc": "workflow.md § 7"})
    added: list[str] = Field(default_factory=list, description="each case written, by its ID — or, planned, to "
                                                               "write")
    kept: list[str] = Field(default_factory=list, description="each case it makes that was written already")
    points: dict[str, str] = Field(default_factory=dict, description="each case it makes, by its ID, with every value "
                                                                     "of its point, as the study writes it")
    values: list[PrepValue] = Field(default_factory=list, description="the project's computed definitions at each set "
                                    "of its constants the study's sweep reaches, as the study keeps them; none where "
                                    "it computes none", json_schema_extra={"doc": "models.md § 3"})
    stages: list[PrepRow] = Field(default_factory=list, description="each case's geometry and meshes, each with its "
                                                                    "state, what was done to it and its folder")
    jobs: list[PrepJob] = Field(default_factory=list, description="each job written, or stated again, with its "
                                                                  "launch folders — or, planned, to write")
    next: list[view.Action] = Field(default_factory=list, description="what to do next, once the machine step went "
                                    "on: the launch the state of each job not launched yet that holds the study's "
                                    "stages allows — one written now, or by a prep before — by its full path, or, for "
                                    "another machine's target, a line for that machine, by its path from the "
                                    "project's folder; no launch the target cannot make; with no such job, `study flow`",
                                    json_schema_extra={"doc": "workflow.md § 7"})
    heading: str = Field(default="", description="the sentence its next steps are headed by")

    @property
    def report(self) -> view.Report:
        """Its first line names the machine it prepped for first, where its machine step went on
        (workflow.md § 7); then, given an engine, that the study is prepared for it and that solving
        is not built yet; then every value, every stage with what prep does to it and its folder,
        and every job with its folders — what its plan shows before anything is written, where the
        outcome is the one its plan foresees, `planned`, saying what is to write, never written."""
        written = [j for j in self.jobs if j.restated is None]
        said, now = ("to write", "to write") if self.status == "planned" else ("written", "now")
        head = f"{self.study}: {text.count(len(self.added), 'case')} {said}, {len(self.kept)} kept"
        if self.target is not None:
            head = (f"for {self.target}, {head}; {text.count(len(self.stages), 'stage')}, "
                    f"{text.count(len(written), 'job')} {said}")
        blocks: list[Any] = [view.Text(text=head)]
        if self.engine is not None and self.status in PREPARED:
            blocks.append(view.Text(text=f"{self.study} {PREPARED[self.status]} for {self.engine}; {NOT_BUILT}"))
        blocks += [
            view.Table.of(PrepCase, [{"id": i, "point": self.points.get(i, ""), "written": now} for i in self.added]
                          + [{"id": i, "point": self.points.get(i, ""), "written": "before"} for i in self.kept],
                          "id", "point", "written")]
        if self.values:
            blocks.append(view.Table.of(PrepValue, [v.model_dump() for v in self.values], "at", "values"))
        if self.stages:
            blocks.append(view.Table.of(PrepRow, [{"stage": r.stage, "state": r.state, "does": ", ".join(r.describe),
                                                   "folder": text.path(r.folder)} for r in self.stages],
                                        "stage", "state", "does", "folder"))
        if self.jobs:
            blocks.append(view.Table.of(PrepJob, [{"sequence": text.path(j.sequence),
                                                   "batches": ", ".join(j.batches), "restated": j.restated or ""}
                                                  for j in self.jobs],
                                        "sequence", "batches", "restated"))
        if self.next:
            blocks.append(view.Next(label=self.heading, actions=self.next))
        return view.Report(blocks=blocks)


def _theirs(exc: Refusal, req: StagesRequest, opened: Opened) -> Refusal:
    """A refusal of `job prepare`'s, as `study prep`'s (workflow.md § 7): the refusal itself — its
    kind, code, subject and reason as they are — each next step that prepares a folder this
    command, with what it names."""
    exc.next = tuple(_again(req, opened, STUDY_PREP, target=a.call.request.get("target", req.target))
                     if a.call is not None and a.call.operation == JOB_PREPARE.name else a for a in exc.next)
    return exc


@dataclass
class Job:
    """The study's meshing job, as prep plans it (workflow.md §§ 5, 7, the jobs step): its sequence's
    launch folder; each launch folder's request it writes — the batches', then the
    sequence's — or, for a job a prep before wrote and not launched yet, each it states again, with
    each member's, and how its resources differ from the study's statement of its meshing job; and
    its prepare, planned in memory with every folder it prepares (jobs.md § 3)."""

    sequence: Path
    launches: dict[Path, JobRequest]
    preparation: prepare.Preparation
    members: dict[Path, JobRequest] = field(default_factory=dict)
    differs: str | None = None                # None: a job this prep writes


Row = tuple[graph.Made, state.Seen, list[str]]   # a stage, observed, and the tasks prep does to it


@dataclass
class Prep:
    """What `study prep` decides (workflow.md § 7), each step reading what the ones before it fixed
    and adding its own answer: the request; the project, its check frame, the study and every
    finding; the values at each point of the sweep; the cases it makes, those written, and those
    it writes in place of a case whose materials' data changed; the target, or the finding of what
    the stages wait for; its meshing job's resources, as the study states them —
    never its solves' (workflow.md § 5); each stage observed with the tasks prep does to it, the
    request of each stage folder it writes or states again and the files of each it writes, how
    each restated one's resources change, and the prepare of each it prepares in no job; each job
    it writes or states again; and every finding it carries."""

    req: PrepRequest
    opened: Opened
    c: Checking
    part: Part
    found: list[Issue]
    computing: definitions.Computing | None = None
    valued: list[cases.Valued] = field(default_factory=list)
    made: list[cases.MadeCase] = field(default_factory=list)
    written: dict[str, cases.Case | str] = field(default_factory=dict)
    renewed: dict[str, tuple[str, list[cases.Filled]]] = field(default_factory=dict)
    target: prepare.Target | None = None
    waits: Issue | None = None
    rows: list[Row] = field(default_factory=list)
    meshing: Resources | None = None
    requests: dict[Path, JobRequest] = field(default_factory=dict)
    files: dict[Path, dict[str, bytes]] = field(default_factory=dict)
    restated: dict[str, str] = field(default_factory=dict)
    apart: dict[Path, prepare.Preparation] = field(default_factory=dict)
    jobs: dict[str, Job] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    def preparations(self) -> list[prepare.Preparation]:
        """Every prepare it plans: each job's, and each stage's it prepares in no job."""
        return [*(j.preparation for j in self.jobs.values()), *self.apart.values()]

    def writing(self, folder: Path) -> prepare.Writing:
        """What the prepare planned for ``folder`` writes into it."""
        return next(w for p in self.preparations() for w in p.folders if w.folder == folder.resolve())

    def folders(self) -> list[Path]:
        """Every folder it writes or prepares: each stage's it writes, prepares or places, and each
        launch folder's of each job it writes or states again."""
        return list(dict.fromkeys([*(s.folder for s, _, does in self.rows if _writes(does)),
                                   *(w.folder for p in self.preparations() for w in p.folders)]))


def _writes(does: list[str]) -> bool:
    """Whether prep writes into a stage's folder on its own account (workflow.md § 7: "a step for
    each thing it writes"): it writes it, prepares it, or states its request again; a stage placed
    alone is the job's to prepare."""
    return bool({state.WRITE, state.PREPARE, state.RESTATE} & set(does))


def _alone(does: list[str]) -> bool:
    """Whether a stage is placed and neither written nor prepared on its own account — its request
    stated again, or not: what the job's prepare writes into it as a member is the job's
    (workflow.md § 6)."""
    return state.PLACE in does and not {state.WRITE, state.PREPARE} & set(does)


def _planned(p: Prep, ctx: Context, folder: Path, given: dict[Path, JobRequest]) -> prepare.Preparation:
    """A folder's prepare planned in memory for the target, on the requests ``given`` (jobs.md § 3) —
    every refusal of `job prepare`'s prep's — its findings carried."""
    try:
        planned = prepare.planned(ctx, str(folder), p.target.name, given)
    except Refusal as exc:
        raise _theirs(exc, p.req, p.opened) from None
    p.issues += planned.issues
    return planned


def _step_definitions(p: Prep, ctx: Context) -> None:
    """Prep's first step (workflow.md § 7): the study ready to make cases — refused while a part it
    uses does not load or has a finding — and every value resolved and validated at every point of
    its sweep, its computed definitions computed in `model_prep` at each distinct set of the
    constants, once per plan (models.md § 3): refused, `has-findings`, at a definition that does
    not compute, its file and line said; where `model_prep`'s state does not allow its use, by its
    one check, with that state's own next steps (envs.md § 3.3)."""
    cases.ready(p.c, p.part, p.found)
    p.computing = definitions.Computing(ctx, p.opened, definitions.declared(p.opened, ctx), study=p.req.study)
    p.valued = cases.values(p.c, p.part, p.computing)


def _computed(p: Prep, ctx: Context) -> list[PrepValue]:
    """The project's computed definitions at each set of its constants the sweep reaches, as prep
    computed them (models.md § 3): the constants that differ between the sets, and every computed
    definition, each said in its declared unit; none where it computes none."""
    ran = p.computing.ran if p.computing is not None else None
    if ran is None or ran.file is None:
        return []
    d, units = p.computing.d, catalogue.units(ctx)
    varies = [n for n in d.constants() if len({str(v[n]) for v in ran.values}) > 1]

    def said(values: dict, names: list[str]) -> str:
        return ", ".join(f"{n} = {definitions.shown(units, d, n, values[n])}" for n in names)

    return [PrepValue(at=said(v, varies), values=said(v, list(d.order))) for v in ran.values]


def _definitions_steps(p: Prep, ctx: Context) -> list[tuple[str, str]]:
    """One step where the study's kept values are not those just computed (models.md § 3): their
    file written whole, every value said in its declared unit; none for a project with no computed
    definition, or values kept as they are."""
    computed = _computed(p, ctx)
    if not computed or definitions.Keeping(ctx, p.opened, p.computing.d, p.req.study).entries() == \
            p.computing.ran.values:
        return []
    return [(p.req.study, f"write {door.definitions_file(p.opened, p.req.study)}: "
                          + "; ".join(f"at {v.at}: {v.values}" if v.at else v.values for v in computed))]


def _write_definitions(p: Prep, ctx: Context, key: str) -> None:
    """The study's kept values, written whole from what the plan computed (models.md § 3)."""
    door.copy_output(p.opened, door.definitions_file(p.opened, p.req.study), p.computing.ran.file)


def _step_cases(p: Prep, ctx: Context) -> None:
    """Its second: each case the study makes now, every value final; those written already; and
    each it writes in place of one whose materials' data changed (models.md § 5.3)."""
    p.made, waits = cases.made(p.c, p.part, p.valued)
    assert not waits, "every computed value is computed by prep's first step"
    p.written = cases.written(p.opened).get(p.req.study, {})
    p.renewed = cases.renewed(p.c, p.part, p.written, {m.id for m in p.made})


def _step_machine(p: Prep, ctx: Context) -> None:
    """Its third: the target's record, chosen as `job prepare` chooses it, and checked — it loads,
    is not stale, states its activation, names a manager kind femkit has (jobs.md § 3)."""
    p.target = prepare.choose(ctx, p.req.target, lambda name: _again(p.req, p.opened, STUDY_PREP, target=name))
    prepare.record_checked(ctx, p.target)


def _step_stages(p: Prep, ctx: Context) -> None:
    """Its fourth: the study's stages for the target, every case as the cases step fixed it — each
    observed with the tasks the stage table gives its state, each where its guard holds
    (`state.tasks`, § 6) — whether its request states other resources than its job's, as folder
    writing says (`folder_writing.restated`, § 5), and whether it waits on a stage this prep places
    in no job among its facts; the request and the files of each it writes, inside the study's
    meshing job as the study states it, `[meshing]`; the request of each it states again; and the
    prepare of each it prepares in no job. Refused at a stage prep does nothing to, keyed on its
    state; a study whose mesh has no input (§ 2.2) is refused at the first step, its error `no-input`
    among its findings."""
    derived = graph.derive(ctx, p.opened, p.c, p.part, p.made, p.target)
    seen = graph.observed(ctx, derived, p.req.target)
    p.meshing = p.part.data.meshing.resources
    placed: set[str] = set()
    for s in derived.stages.values():                # a stage after every stage it takes from
        now = seen[s.address]
        request = folder_writing.restated(ctx, s, p.meshing) \
            if now.facts.there and not state.machine(ctx).idle(now.state) else None   # idle: refused below
        does = state.tasks(ctx, now, placed, restated=request is not None)
        if state.WRITE in does:
            p.requests[s.folder], p.files[s.folder] = folder_writing.folder_of(ctx, s, p.meshing)
        if state.RESTATE in does:
            p.restated[s.address] = _differs(runs.request_of(ctx, s.folder).resources, request.resources)
            p.requests[s.folder] = request
        if state.PLACE in does:
            placed.add(s.address)
        elif state.PREPARE in does:                  # prepared in no job, left waiting
            p.apart[s.folder] = _planned(p, ctx, s.folder,
                                         {s.folder: p.requests[s.folder]} if s.folder in p.requests else {})
        p.rows.append((s, now, does))
    p.issues += [*derived.issues, *_unread(ctx, derived)]


def _step_jobs(p: Prep, ctx: Context) -> None:
    """Its fifth: each job a prep before wrote, not launched yet, holding a stage of the study, whose
    launch folders state other resources than the study's meshing now does, or a stage of which the
    stages step states again — each launch folder's request stated again, and each other member's,
    and the job's prepare planned again (§ 5); then the study's meshing job of the stages it places,
    as folder writing forms it — its batches, their sequence, each launch folder's request stating
    the study's meshing (`folder_writing.placed`, `folder_writing.job`) — and the job's prepare
    planned in memory, every folder it prepares, its stages', on the requests prep holds — so every
    refusal of `job prepare` comes before anything is written, as prep's (jobs.md § 3)."""
    job = p.meshing
    for sequence in _holding(p):
        stated = folders.restated_job(ctx, sequence, job, folder_writing.resources(job))
        tree = {f.resolve() for f in folders.tree(ctx, sequence)}
        theirs = {f: r for f, r in p.requests.items() if f.resolve() in tree}   # its stages prep states again
        if not stated and not theirs:
            continue
        p.jobs[sequence.name] = Job(sequence=sequence,
                                    launches={f: r for f, r in stated.items() if r.walk},
                                    members={f: r for f, r in stated.items()
                                             if not r.walk and f.resolve() not in {t.resolve() for t in theirs}},
                                    preparation=_planned(p, ctx, sequence, {**stated, **theirs}),
                                    differs=_differs(runs.request_of(ctx, sequence).resources, job))
    batches = folder_writing.placed(graph.Definitions.of(p.c), [s for s, _, does in p.rows if state.PLACE in does])
    if batches:
        sequence, launches = folder_writing.job(p.opened, p.req.study, batches, job, catalogue.stages(ctx).sequence)
        p.jobs[sequence.name] = Job(sequence=sequence, launches=launches,
                                    preparation=_planned(p, ctx, sequence, {**p.requests, **launches}))


def _holding(p: Prep) -> list[Path]:
    """Each launch folder not launched yet that a stage of the study goes in, `in_launch` — a prep's
    before (jobs.md § 5.5)."""
    return list(dict.fromkeys(now.facts.calculation.launch for _, now, _ in p.rows if now.facts.in_launch))


def _case_steps(p: Prep, ctx: Context) -> list[tuple[str, str]]:
    """One step for each case the study makes and has not written, each with its values."""
    return [(m.id, cases.described(p.opened, p.req.study, m, p.renewed)) for m in p.made if m.id not in p.written]


def _stage_steps(p: Prep, ctx: Context) -> list[tuple[str, str]]:
    """One step for each stage it writes into on its own account — writing, preparing, or stating
    its request again — its state and what prep does to it, in the stage table's sentences, how
    its resources change beside them where they are stated again (workflow.md §§ 6, 7); a stage it
    uses or leaves, or places alone, has none."""
    return [(s.address, f"{s.kind} {cases.short(s.id)}… {now.state.value}: "
             + ", ".join(state.said(ctx, v) for v in does)
             + (f" ({p.restated[s.address]})" if s.address in p.restated else ""))
            for s, now, does in p.rows if _writes(does)]


def _job_steps(p: Prep, ctx: Context) -> list[tuple[str, str]]:
    """One step for each job: one a prep before wrote, its launch folders' resources stated again —
    each stage in it whose request is stated again a step of the stages step — and the job prepared
    again; one it writes, its launch folders written and prepared, with each stage it places alone."""
    return [(key, f"state the resources of {key} and of the batches it holds again ({j.differs}), and prepare it "
                  f"again for {p.target.name}" if j.differs is not None else
             f"write {', '.join(f.name for f in j.launches)} in {text.path(j.sequence.parent)}, and prepare them for "
             f"{p.target.name}") for key, j in p.jobs.items()]


def _write_case(p: Prep, ctx: Context, key: str) -> None:
    cases.write(p.opened, p.req.study, next(m for m in p.made if m.id == key))


def _write_stage(p: Prep, ctx: Context, key: str) -> None:
    """A stage's folder, by its tasks (workflow.md §§ 5, 6): its request stated again where its job's
    resources changed — how it runs changes, never what it runs (jobs.md § 1.1); written whole with
    its prepared files where it has none; its prepare committed where prep prepares it — in its job,
    or in none."""
    s, _, does = next(row for row in p.rows if row[0].address == key)
    if state.RESTATE in does:
        folders.restate(ctx, s.folder, p.requests[s.folder].resources)
    if state.WRITE in does:
        folders.write(ctx, s.folder, p.requests[s.folder], p.files[s.folder],
                      prepared=prepare.files_of(ctx, p.writing(s.folder)))
    elif state.PREPARE in does:
        prepare.commit(ctx, p.writing(s.folder))


def _write_job(p: Prep, ctx: Context, key: str) -> None:
    """A job: one a prep before wrote — each launch folder's and member's request stated again, and
    every folder it prepares committed again; one it writes — each stage it places alone prepared
    as the job's member, then each launch folder written whole with its prepared files and the
    action that writes it again, this command, as its maker's (jobs.md §§ 1.1, 1.2)."""
    j = p.jobs[key]
    if j.differs is not None:
        for folder, request in [*j.members.items(), *j.launches.items()]:
            folders.restate(ctx, folder, request.resources)
        for w in j.preparation.folders:
            prepare.commit(ctx, w)
        return
    alone = {s.folder.resolve() for s, _, does in p.rows if _alone(does)}
    for w in j.preparation.folders:
        if w.folder in alone:
            prepare.commit(ctx, w)
    for folder, request in j.launches.items():
        folders.write(ctx, folder, request, {}, prepared=prepare.files_of(ctx, p.writing(folder)),
                      maker=_again(p.req, p.opened, STUDY_PREP))


@dataclass(frozen=True)
class PrepStep:
    """One step of prep (workflow.md § 7): its name; whether it needs the target's record — where
    one that does cannot go on, the steps after it wait (`WAITS`); what it decides, in the plan,
    within what the steps before it fixed; the plan's steps it adds, each by its key and its words
    — one for each thing it writes; and what apply writes for each of them."""

    name: str
    machine: bool
    decides: Callable[[Prep, Context], None]
    steps: Callable[[Prep, Context], list[tuple[str, str]]] = lambda p, ctx: []
    writes: Callable[[Prep, Context, str], None] | None = None


#: Prep's steps, in order, stated once (workflow.md § 7): its plan runs each, and its apply writes
#: each plan step by the one that planned it.
PREP = (
    PrepStep("definitions", machine=False, decides=_step_definitions, steps=_definitions_steps,
             writes=_write_definitions),
    PrepStep("cases", machine=False, decides=_step_cases, steps=_case_steps, writes=_write_case),
    PrepStep("machine", machine=True, decides=_step_machine),
    PrepStep("stages", machine=True, decides=_step_stages, steps=_stage_steps, writes=_write_stage),
    PrepStep("jobs", machine=True, decides=_step_jobs, steps=_job_steps, writes=_write_job),
)


def _waiting(p: Prep, exc: Refusal) -> Issue:
    """What the stages wait for, where prep's machine step could not go on (workflow.md § 7): the
    refusal as one finding, by the door's one way — its code, subject and the steps that settle it,
    a message saying the stages wait and why, its file, key and line where its subject is a part's
    (`door.finding_of`)."""
    return door.finding_of(p.opened, exc, "warning", f"its stages wait: {exc}")


#: The note of a prep naming no engine (workflow.md § 7): the engine is chosen when the study is solved.
NO_ENGINE = "no-engine"


def _engine(p: Prep) -> None:
    """The engine the request names, before prep's first step (workflow.md §§ 2.2, 7): refused,
    `UsageError` · `no-such-engine`, where no engine environment declares it, with the one closest
    it may mean; refused, `Refused` · `has-findings`, carrying the error `no-input` at the study's
    `mesh`, where it cannot take the mesh the study's recipe makes at a geometry order of its cases
    (`study.solvers`) — each refusal's next steps the prep with each engine that can solve the
    study. With none named, one note, `no-engine`, at the study: what prep makes serves every engine,
    and the engine is chosen when the study is solved, with the command that chooses it, the engine
    a fill whose choices are those that can solve the study, by the same rule."""
    engine, address = p.req.engine, p.part.address
    can = study.solvers(p.c, p.part)
    if engine is None:
        choose = view.Fill.of(PrepRequest, "engine", choices=can)
        p.issues.append(door.finding(p.opened, Address(address.kind, address.name), code=NO_ENGINE, severity="info",
                                     message=f"no engine is chosen for the study {address.name}: its cases, geometries "
                                             "and meshes serve every engine, and the engine is chosen when the study "
                                             "is solved",
                                     next=[_again(p.req, p.opened, STUDY_PREP, fills=[choose])]))
        return
    known = sorted(p.c.engines)
    steps = tuple(_again(p.req, p.opened, STUDY_PREP, engine=e) for e in (known if can is None else can))
    if engine not in p.c.engines:
        raise UsageError(f"`{engine}` is no engine femkit solves with: {', '.join(known)}" + meant(engine, known),
                         steps, code="no-such-engine", subject=engine)
    if can is not None and engine not in can:
        why = graph.taking(p.c, p.part, engine)
        mesh = Address(address.kind, address.name, ("mesh",))
        raise Refused(f"the engine {engine} cannot take the mesh the study {address.name}'s recipe makes", steps,
                      code="has-findings", subject=str(mesh),
                      issues=[door.finding(p.opened, mesh, code=graph.NO_INPUT, message=why)])


def prepped(req: PrepRequest, ctx: Context) -> Prep:
    """Everything `study prep` decides (workflow.md § 7), the engine it names checked first
    (`_engine`), its steps run in order — once per invocation, so its apply writes what its plan
    decided — or its refusal: where a step that needs the machine cannot go on (`WAITS`), the steps
    after it are not run, and what the stages wait for is said, one finding."""
    def decided() -> Prep:
        opened, c, part, found = study_of(req, ctx, compute=True)
        p = Prep(req=req, opened=opened, c=c, part=part, found=found)
        _engine(p)
        for step in PREP:
            try:
                step.decides(p, ctx)
            except Refusal as exc:
                if not (step.machine and _waits_on(exc)):
                    raise
                p.waits = _waiting(p, exc)
                break
        return p

    return ctx.cached(f"study.prep {persist.canonical_sha256(req.model_dump(mode='json'))}", decided)


def _stated(value: Any) -> str:
    """A resource as a request states it, or `unset`."""
    return "unset" if value is None else str(value)


def _differs(held: Resources, now: Resources) -> str:
    """How the resources a request states, ``held``, differ from those it states now, each changed
    one with its value before and after."""
    return ", ".join(f"{k} {_stated(getattr(held, k))} → {_stated(getattr(now, k))}"
                     for k in Resources.model_fields if getattr(held, k) != getattr(now, k))


#: The sentences `study prep`'s next steps are headed by (workflow.md § 7): the launch of each job
#: that makes its stages; or, with no such job, where to see them.
ALLOWED, SEE = "launch each job not launched yet that makes them", "to see them"
#: Where and how the launch it offers runs (workflow.md § 7): on this machine — for another
#: machine's target, the machine the step carries says where (`Action.on`) — in the background.
HERE, BACKGROUND = "on this machine", "in the background"


def _next(p: Prep, ctx: Context) -> tuple[str, list[view.Action]]:
    """What `study prep`'s outcome offers next, once its machine step went on, and the sentence it is
    headed by (workflow.md § 7): for each job not launched yet that holds the study's stages — one
    it wrote, or one a prep before wrote — the launch that launch folder's state allows, alone, as
    the jobs domain reads it (`folders.launch_step`), never a launch the target cannot make
    (`prepare.launches`), each saying where and how it runs, as the target's machine takes it
    (`graph.there`); with no such job, `study flow`."""
    written = {s.address: j.sequence for j in p.jobs.values() if j.differs is None
               for s, _, does in p.rows if state.PLACE in does}
    holding = list(dict.fromkeys(written.get(s.address) or now.facts.calculation.launch
                                 for s, now, _ in p.rows if s.address in written or now.facts.in_launch))
    if not holding:
        return SEE, [_again(p.req, p.opened, STUDY_FLOW)]
    launches, steps = prepare.launches(ctx, p.target), []
    for sequence in holding:
        f, now = folders.observe(ctx, sequence)
        step = folders.launch_step(ctx, now, f) if launches else None
        steps += [step] if step is not None else []
    how = ", ".join([HERE, BACKGROUND] if p.target.here else [BACKGROUND])
    said = [a.model_copy(update={"note": "; ".join(filter(None, (a.note, how)))}) for a in steps]
    return ALLOWED, [graph.there(p.opened, p.target, a) for a in said]


def _texts(p: Prep, ctx: Context) -> str:
    """A digest of every text prep would write (workflow.md § 7: "Its basis covers every text it
    would write"): each case's, each request and file of each folder it writes or states again, and
    every file each prepare it plans writes."""
    texts = {f"case {m.id}": cases.case_id(m.case) for m in p.made if m.id not in p.written}
    texts |= {"definitions": persist.sha256(p.computing.ran.file)} if _definitions_steps(p, ctx) else {}
    requests = {**p.requests, **{f: r for j in p.jobs.values() for f, r in [*j.launches.items(), *j.members.items()]}}
    texts |= {f"{f} request": persist.digest(folders.request_text(ctx, r)) for f, r in requests.items()}
    texts |= {f"{f}/{name}": persist.digest(data) for f, held in p.files.items() for name, data in held.items()}
    texts |= {f"{w.folder}/{name}": persist.digest(data)
              for prep_ in p.preparations() for w in prep_.folders for name, data in prepare.files_of(ctx, w).items()}
    return persist.canonical_sha256(texts)


@operation(STUDY_PREP, result=PrepOutcome, subject="plan")
class StudyPrep:
    """Take a study from its files to what its jobs run, for a machine — this one's unless --target
    names another: its values resolved at every point, its cases written, its geometries and meshes
    written and prepared, and one job that makes them, to launch with `job launch`. --engine names
    the engine that solves it, which no file names: it is checked to take the study's mesh, and
    solving it is not built yet; left out, the engine is chosen when the study is solved. Everything is
    planned before anything is written; --dry-run shows it. A stage already made is used, one a job
    holds or will make is left to it. Where there is no record of the machine, or it lacks an
    environment's install, the cases are written and the stages wait, with the steps that settle
    it."""

    def observe(self, req: PrepRequest, ctx: Context) -> dict:
        """The cases the study makes and those written, what the stages wait for, each stage and its
        state, each job, the record the stages are named by, and a digest of every text it would
        write — so a file changed between the plan and its apply refuses the apply (api.md § 3)."""
        p = prepped(req, ctx)
        return {"cases": sorted(m.id for m in p.made), "written": sorted(p.written),
                "waits": p.waits.code if p.waits is not None else None,
                "stages": {s.address: now.state.value for s, now, _ in p.rows},
                "jobs": sorted(p.jobs),
                "record": persist.sha256(record.path(p.target.name)) if p.target is not None else None,
                "texts": _texts(p, ctx)}

    def plan(self, req: PrepRequest, ctx: Context) -> Plan:
        """A step for each thing prep writes, in its steps' order (workflow.md § 7): each case it
        writes, each stage it writes into on its own account with its state and what it does to it,
        each job it writes or states again — and nothing else: a prep with nothing to write has no
        step. Its subjects: the project's, and every folder's it writes or prepares, so the runner
        holds each; its findings, each prepare's among them, and what the stages wait for, where
        they wait, with the steps that settle it."""
        p = prepped(req, ctx)
        steps = [Step(id=f"{s.name}:{key}", describe=said) for s in PREP for key, said in s.steps(p, ctx)]
        return Plan(subjects=tuple(dict.fromkeys([p.opened.project.subject, *(runs.subject(f) for f in p.folders())])),
                    steps=tuple(steps), issues=[*p.issues, *([p.waits] if p.waits is not None else [])])

    def outcome(self, plan: Plan, ctx: Context) -> PrepOutcome:
        """The outcome its plan foresees, `planned` (api.md § 3): what its preview shows — every
        value, every stage with what prep does to it, used and left ones included, every folder,
        every job, each case and job to write — built as its apply builds its outcome (`_outcome`);
        its next steps are read from the launch folders once they are written, so the preview offers
        none."""
        return _outcome(prepped(PrepRequest.model_validate(plan.request), ctx), ctx, plan, "planned", None)

    def apply(self, plan: Plan, ctx: Context, observer) -> PrepOutcome:
        req = PrepRequest.model_validate(plan.request)
        p = prepped(req, ctx)
        by_name = {s.name: s for s in PREP}

        def do(step: Step, where: Path):
            name, _, key = step.id.partition(":")
            by_name[name].writes(p, ctx, key)
            return "done", None

        status, log = run_steps(plan, ctx, observer, do)
        heading, steps = _next(p, ctx) if status == "done" and p.waits is None else ("", [])
        return _outcome(p, ctx, plan, status, str(log), heading, steps)


def _outcome(p: Prep, ctx: Context, plan: Plan, status: str, log: str | None, heading: str = "",
             steps: list[view.Action] | None = None) -> PrepOutcome:
    """What prep decided, as its outcome (workflow.md § 7) — the one builder of it, for the plan's
    preview, `planned`, and the apply alike: the engine it was given, the cases, each with its values, the computed
    definitions' values, each stage with what prep does to it and its folder, each job with its
    launch folders; the cases and jobs written — or, planned, to write — only where no step failed."""
    done = status != "failed"
    return PrepOutcome(
        plan=plan, status=status, log=log, project=p.opened.project.name, study=p.req.study, engine=p.req.engine,
        target=p.target.name if p.target and p.waits is None else None,
        added=[m.id for m in p.made if m.id not in p.written] if done else [],
        kept=[m.id for m in p.made if m.id in p.written],
        points={m.id: cases.at_point(m.point) for m in p.made}, values=_computed(p, ctx),
        stages=[PrepRow(stage=s.address, state=now.state.value, does=does, folder=str(s.folder),
                        describe=[state.said(ctx, v) for v in does]) for s, now, does in p.rows],
        jobs=[PrepJob(sequence=str(j.sequence), restated=j.differs,
                      batches=[f.name for f in j.launches if f != j.sequence])
              for j in p.jobs.values()] if done else [],
        next=steps or [], heading=heading)


# ------------------------------------------------------------------ project save

class SaveOutcome(Outcome):
    project: str = Field(default="", description="the project, by its path from the projects root")
    address: str = Field(default="", description="the file, by its address",
                         json_schema_extra={"doc": "projects.md § 5"})
    file: str = Field(default="", description="the file, as a finding names it: from the project's folder; a global "
                                              "library's by its full path, shown from `~` where it lies under the home "
                                              "folder")

    @property
    def report(self) -> view.Report:
        """Its one line says whether the file is saved — or, planned, is to be — exactly as typed; the
        change's impact is its findings."""
        said = {"planned": "to be saved exactly as typed", "done": "saved exactly as typed"}.get(self.status,
                                                                                                "not saved")
        return view.Report(blocks=[view.Text(text=f"{text.path(self.file)}: {said}")])


@dataclass(frozen=True)
class Saving:
    """What a save writes (projects.md § 7): the project, where the file lies — the project, or the
    global library holding a part it names — the file's address, and the project as it is."""

    project: Project
    home: Project | Library
    address: Address
    opened: Opened

    @property
    def file(self) -> str:
        """The file, as a finding names it."""
        return door.file(self.opened, self.address).path


def _saving(req: SaveRequest, ctx: Context) -> Saving:
    """The project the request names, opened once in the invocation, and the file its address names
    — refused, `bad-address`, for an address that names no file a save writes."""
    def made() -> Saving:
        opened = opened_of(req, ctx)
        address = opened.layout.address(req.address)
        home = opened.libraries[address.kind].library if door.in_library(address) else opened.project
        return Saving(opened.project, home, address, opened)

    return ctx.cached(f"project.save {req.project} {req.address}", made)


@operation(PROJECT_SAVE, result=SaveOutcome, subject="plan", surfaces=PAGE_ALONE)
class ProjectSave:
    """Save a file of the project exactly as you typed it in the page's text editor, after showing
    what the change does: what it breaks, which promise it breaks, what it makes impossible, which
    stages it makes anew, which cases it changes. A file changed since the page opened it is not
    saved over. Writes that one file, nothing else."""

    def observe(self, req: SaveRequest, ctx: Context) -> dict:
        """The SHA-256 of every other file of the project, as opened: a change's impact rests on them,
        so one changed between the plan and its apply refuses the apply as stale (api.md § 3); the
        file saved is held to the SHA-256 the page opened it with, `file-changed` (projects.md § 7)."""
        s = _saving(req, ctx)
        held = {**s.opened.sha256, **{f: h.sha256 for f, h in s.opened.held.items()}}
        return {"files": persist.canonical_sha256({f: sha for f, sha in held.items() if f != s.file})}

    def plan(self, req: SaveRequest, ctx: Context) -> Plan:
        """One step, the file written exactly as typed; its findings, the change's impact
        (workflow.md § 10), shown before it writes and decided by the person — never a refusal for
        what the text says; refused, `file-changed`, where the file changed since the page opened it.
        Its subjects: the project's — and a global library's, for a file of a part it holds
        (materials.md § 4)."""
        s = _saving(req, ctx)
        door.unchanged(ctx, s.home, s.address, req.sha256)
        subjects = [s.project.subject, *([s.home.subject] if s.home is not s.project else [])]
        return Plan(subjects=tuple(subjects), issues=impact.of(ctx, s.project, s.address, req.text),
                    steps=(Step(id=f"save:{req.address}", describe=f"write {text.path(s.file)} exactly as typed"),))

    def apply(self, plan: Plan, ctx: Context, observer) -> SaveOutcome:
        req = SaveRequest.model_validate(plan.request)
        s = _saving(req, ctx)

        def do(step: Step, where: Path):
            door.save_text(ctx, s.home, s.address, req.text, req.sha256)
            return "done", None

        status, log = run_steps(plan, ctx, observer, do)
        return SaveOutcome(plan=plan, status=status, log=str(log), project=s.project.name, address=req.address,
                           file=s.file)
