"""A change's impact (workflow.md § 10): what saving one file's new text would do, shown before it
writes. The door opens the project as it would be — that one file's text in place of the file's,
in memory (`door.open_project`'s `texts`) — and the project as it is, and these comparisons run, in
this order, each its owner's, each reading only what its owner declares:

- **the file** — the door, through the part's schema: whether the new text loads, and where not
  each problem at its key, as opening it says (projects.md § 6);
- **the project's findings** — the one check `project check` runs (models.md § 11.2), on both: each
  finding new, told by its code, file and key, as it is — its severity, its next steps — a broken
  promise among them, a group the contract no longer promises that a part names; each resolved,
  `resolved`; and, where what a study's kept computed values rest on changes — the `[definitions]`
  table, `definitions.py` — the computed definitions the next `study prep` computes again,
  `computed-again` (models.md § 3);
- **a built geometry's promise** — the geometry's reading of a finished geometry stage's
  `groups.json` (geometry.md § 7): each group the saved contract promises that a geometry built of
  it holds not, `promise-not-held`;
- **each study's cases** — the rule `study prep` makes them by (models.md § 5.3): those no longer
  made, `cases-no-longer-made`, and the new, `cases-new`; cases `study prep` can no longer make,
  `cases-not-made`; cases waiting on computed values not kept for them, `cases-wait`;
- **each study's workflow** — the graph on both (§ 3), for each machine whose stages the study has,
  by its record here: each stage made anew, `made-anew` — the stage it replaces, where one, and
  whether that one's finished run is no longer used; each made impossible, its environment's input
  written by no stage (§ 2.2), `made-impossible`; each no longer needed, `no-longer-needed`; a
  machine whose stages the study has and whose record is not here, `not-compared`;
- **the jobs going** — the jobs domain's addresses (jobs.md § 5.4): a job still going that runs a
  stage the change replaces, `job-going` — it runs on with what it was given, and its result serves
  no case of the study as changed.

Each line is a finding of its severity with its next step. It runs no tool — no script, mesher or
solver, and no function of `definitions.py`: both sides check the project as `project check` does
without computing them — and reads no run but the records these comparisons name.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from femkit.core import view
from femkit.core.errors import Refusal
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.geometry import steps as geometry
from femkit.jobs import addresses, prepare, record
from femkit.jobs.requests import JOB_CANCEL
from femkit.materials.assign import GROUP
from femkit.models import cases, definitions, study as studies
from femkit.models.operations import kept
from femkit.projects import state as part_state
from femkit.models.parts import contract
from femkit.projects import checking, door
from femkit.projects.addresses import Address, Job as JobAddress, Stage as StageAddress
from femkit.projects.checking import DEFINITION, Checking
from femkit.projects.door import Opened, Part
from femkit.projects.project import Project
from femkit.projects.requests import PROJECT_CHECK
from femkit.workflow import graph, identity, state
from femkit.workflow.requests import CASE_LIST, STUDY_PREP

#: Each line's code, by the comparison that says it (workflow.md § 10); a new finding keeps its own.
RESOLVED, COMPUTED_AGAIN, PROMISE_NOT_HELD = "resolved", "computed-again", "promise-not-held"
CASES_NOT_MADE, CASES_GONE, CASES_NEW, CASES_WAIT = "cases-not-made", "cases-no-longer-made", "cases-new", "cases-wait"
MADE_ANEW, MADE_IMPOSSIBLE, NO_LONGER_NEEDED = "made-anew", "made-impossible", "no-longer-needed"
NOT_COMPARED, JOB_GOING = "not-compared", "job-going"


@dataclass
class Side:
    """The project as it is, or as it would be with the new text: opened, its check frame — its
    computed definitions not computed (§ 10, "Quick") — every finding of the one check, and each
    study's cases, made once."""

    opened: Opened
    c: Checking
    found: list[Issue]
    made: dict[str, tuple[list[cases.MadeCase], int] | Refusal] = field(default_factory=dict)

    @classmethod
    def of(cls, ctx: Context, opened: Opened) -> "Side":
        c = checking.Checking.of(opened, ctx, definitions.defined(opened, ctx, compute=False))
        return cls(opened, c, checking.findings(c))

    def studies(self) -> dict[str, Part]:
        """Each study, by its name."""
        kind = self.opened.layout.kind_of(studies.KEY)
        return {p.address.name: p for p in self.opened.parts.values() if p.address.kind == kind}

    def cases(self, ctx: Context, study: Part) -> tuple[list[cases.MadeCase], int] | Refusal:
        """The cases ``study`` makes, and how many of its points wait for computed values `study prep`
        has not kept for them — or why it makes none (models.md § 5.3)."""
        name = study.address.name
        if name not in self.made:
            try:
                made, waits = cases.makes(self.c, study, self.found, kept(ctx, self.opened, name))
                self.made[name] = (made, len(waits))
            except Refusal as exc:
                self.made[name] = exc
        return self.made[name]


def of(ctx: Context, project: Project, address: Address, text: str) -> list[Issue]:
    """Every line of the impact of saving ``text`` as the file ``address`` names in ``project``
    (workflow.md § 10), each comparison's in the table's order."""
    before = Side.of(ctx, door.open_project(project, ctx))
    after = Side.of(ctx, door.open_project(project, ctx, texts={address: text}))
    said = _file(after, address)
    lines = [*said, *_findings(before, after, said), *_computed_again(ctx, before, after),
             *_promise(ctx, after, address)]
    held = before.studies()                         # one file changed: both sides hold the same parts
    pairs = [(held[name], part) for name, part in sorted(after.studies().items())]
    for was, now in pairs:
        lines += _cases(ctx, before, after, was, now)
    replaced: list[tuple[str, graph.Made]] = []
    for was, now in pairs:
        found, gone = _workflow(ctx, before, after, was, now)
        lines += found
        replaced += [(now.address.name, s) for s in gone]
    return lines + _jobs(ctx, after, replaced)


# ------------------------------------------------------------------ the file, and the findings

def _file(after: Side, address: Address) -> list[Issue]:
    """Whether the new text loads (projects.md § 6): where not, each problem the door finds at the
    saved file, at its key, as opening it says."""
    part = after.opened.part(address)
    saved = door.file(after.opened, address).path
    return [i for i in after.opened.issues if i.file == saved and after.opened.owner(i.subject) is part]


def _told(issue: Issue) -> tuple:
    """A finding as a change's impact tells it: by its code, file and key (workflow.md § 10) — by its
    subject where it is at no key."""
    return issue.code, issue.file, issue.key if issue.key is not None else issue.subject


def _findings(before: Side, after: Side, said: list[Issue]) -> list[Issue]:
    """Each finding of the one check new with the text, as it is — its severity, its next steps —
    but those the file's comparison says; and each resolved, `resolved`, a note at its file and key,
    at the line that key stands at in the new text."""
    was, now, told = {_told(i) for i in before.found}, {_told(i) for i in after.found}, {_told(i) for i in said}
    new = [i for i in after.found if _told(i) not in was and _told(i) not in told]
    gone = [i.model_copy(update={"severity": "info", "code": RESOLVED, "message": f"resolved: {i.message}",
                                 "right": None, "choices": (), "next": (),
                                 "line": door.line_of(after.opened, i.file, i.key) if i.file else None})
            for i in before.found if _told(i) not in now]
    return new + gone


def _computed_again(ctx: Context, before: Side, after: Side) -> list[Issue]:
    """The computed definitions the next `study prep` computes again (models.md § 3), where what a
    study's kept values rest on — `definitions.py`, the `[definitions]` table — changes: one note,
    at the first of them."""
    was, now = definitions.declared(before.opened, ctx), definitions.declared(after.opened, ctx)
    if not now.order or definitions.attributes(ctx, was, None) == definitions.attributes(ctx, now, None):
        return []
    kind, keys = after.opened.layout.project_kind, after.opened.layout.objects[DEFINITION].keys
    return [door.finding(after.opened, Address(kind, None, (*keys, now.order[0])), code=COMPUTED_AGAIN, severity="info",
                         message=f"what the kept values of {', '.join(f'`{n}`' for n in now.order)} rest on changes: "
                                 "the next `study prep` of each study computes them again",
                         next=(view.command(PROJECT_CHECK, project=after.opened.project.name),))]


# ------------------------------------------------------------------ a built geometry's promise

def _promise(ctx: Context, after: Side, address: Address) -> list[Issue]:
    """Each group the saved contract promises that a finished geometry stage of a study pairing it
    holds not, as that stage's newest finished run's `groups.json` says (geometry.md § 7) — each
    stage found by its `stage.json`, whichever machine made it (workflow.md § 4)."""
    holder = after.opened.part(address)
    k = contract(after.opened, holder)
    if k is None:
        return []
    first = graph.Definitions.of(after.c).made_first()
    keys = after.opened.layout.objects[GROUP].keys
    out: list[Issue] = []
    for name, part in sorted(after.studies().items()):
        if part.data is None or studies.cites(after.c, "component", part.data.component) is not holder:
            continue
        for (kind, sid), folder in sorted(door.stages(after.opened, name).items()):
            if kind != first or not identity.read(ctx, folder).reads:
                continue
            seen = state.observe(ctx, str(StageAddress(name, kind, sid)), folder, project=after.opened.project.name,
                                 study=name, target=None, takes_from=[])
            built = geometry.built(ctx, seen.facts.calculation.newest.run) if state.finished(ctx, seen) else None
            for group in geometry.unheld(k.groups, built) if built is not None else ():
                out.append(door.finding(
                    after.opened, Address(holder.address.kind, holder.address.name, (*keys, group)),
                    code=PROMISE_NOT_HELD, severity="warning",
                    message=f"the geometry built for {name} ({cases.short(sid)}) holds no group `{group}` of dimension "
                            f"{k.groups[group]}: whether the script keeps this promise is seen when the geometry is "
                            "made anew",
                    next=(view.command(STUDY_PREP, project=after.opened.project.name, study=name),)))
    return out


# ------------------------------------------------------------------ each study's cases

def _cases(ctx: Context, before: Side, after: Side, was: Part, now: Part) -> list[Issue]:
    """A study's cases on both sides (models.md § 5.3): those no longer made and the new ones; or
    that `study prep` can no longer make them, and why; and those that wait for computed values
    `study prep` has not kept for them, whose cases are known once it computes them."""
    name, project = now.address.name, after.opened.project.name
    held, made = before.cases(ctx, was), after.cases(ctx, now)

    def line(code: str, severity: str, message: str, *next_: view.Action) -> Issue:
        return door.finding(after.opened, now.address, code=code, severity=severity, message=message, next=next_)

    if isinstance(made, Refusal):
        return [] if isinstance(held, Refusal) else [line(
            CASES_NOT_MADE, "warning", f"`study prep` can no longer make the cases of {name}: {made}",
            *made.next)]
    old = {m.id for m in held[0]} if not isinstance(held, Refusal) else set()
    out = []
    if made[1]:
        out.append(line(CASES_WAIT, "info", f"the cases of {name} at {made[1]} {'point' if made[1] == 1 else 'points'} "
                                            "wait for `study prep` to compute their definitions",
                        view.command(STUDY_PREP, project=project, study=name)))
    gone = sorted(old - {m.id for m in made[0]}) if not made[1] else []
    new = [m.id for m in made[0] if m.id not in old]
    if gone:
        out.append(line(CASES_GONE, "info", f"{len(gone)} {'case' if len(gone) == 1 else 'cases'} of {name} no longer "
                                            f"made, kept as written: {', '.join(cases.short(i) for i in gone)}",
                        view.command(CASE_LIST, project=project)))
    if new:
        out.append(line(CASES_NEW, "info", f"{len(new)} new {'case' if len(new) == 1 else 'cases'} of {name}, which "
                                           f"`study prep` writes: {', '.join(cases.short(i) for i in new)}",
                        view.command(STUDY_PREP, project=project, study=name)))
    return out


# ------------------------------------------------------------------ each study's workflow

def _machines(ctx: Context, after: Side, name: str) -> tuple[list[prepare.Target], list[str]]:
    """Each machine whose stages study ``name`` has — the target each `stage.json` names, by its
    record's identity of the host (workflow.md § 4) — by the first record here naming it; and those
    no record here names."""
    first = graph.Definitions.of(after.c).made_first()
    wanted = []
    for (kind, _), folder in sorted(door.stages(after.opened, name).items()):
        held = identity.read(ctx, folder)
        if kind == first and held.reads and held.value.target not in wanted:
            wanted.append(held.value.target)
    named = {r.identity: n for n, _, r, _ in reversed(record.listing()) if r is not None}
    found, lacking = [], []
    for target in wanted:
        if target not in named:
            lacking.append(record.shown(target))
            continue
        try:
            found.append(prepare.choose(ctx, named[target], lambda n: view.command(STUDY_PREP, study=name, target=n)))
        except Refusal:
            lacking.append(named[target])
    return found, lacking


def _derived(ctx: Context, side: Side, study: Part, t: prepare.Target) -> graph.Derived | None:
    """A study's workflow graph on one side for the machine ``t`` (workflow.md § 3); none where its
    cases cannot be made, or no stage's identity can be formed."""
    made = side.cases(ctx, study)
    if isinstance(made, Refusal):
        return None
    try:
        return graph.derive(ctx, side.opened, side.c, study, made[0], t)
    except Refusal:
        return None


def _points(side: Side, ctx: Context, study: Part, derived: graph.Derived | None) -> dict[str, set[str]]:
    """Each stage of ``derived``, by its address, with the points of the cases it serves."""
    if derived is None:
        return {}
    made = side.cases(ctx, study)
    point = {m.id: cases.at_point(m.point) for m in made[0]} if not isinstance(made, Refusal) else {}
    out: dict[str, set[str]] = {}
    for case_id, members in derived.cases:
        for member in members:
            out.setdefault(member, set()).add(point.get(case_id, case_id))
    return out


def _workflow(ctx: Context, before: Side, after: Side, was: Part, now: Part) -> tuple[list[Issue], list[graph.Made]]:
    """A study's workflow on both sides, for each machine whose stages it has (workflow.md §§ 3, 10):
    each stage made anew, with the one it replaces — of its own kind and environment, serving a
    point of its own — and whether that one's finished run is no longer used; each one no longer the
    study's, made impossible where its mesh has no input (§ 2.2), else
    no longer needed; and the stages replaced or dropped, for the jobs going."""
    name, project = now.address.name, after.opened.project.name
    targets, lacking = _machines(ctx, after, name)
    out = [door.finding(after.opened, now.address, code=NOT_COMPARED, severity="info",
                        message=f"the stages of {name} made for {machine} are not compared: no record of that machine "
                                "is here")
           for machine in lacking]
    dropped: list[graph.Made] = []
    for t in targets:
        old, new = _derived(ctx, before, was, t), _derived(ctx, after, now, t)
        if old is None:
            continue
        stages, seen = (new.stages if new is not None else {}), graph.observed(ctx, old, t.name)
        old_points, new_points = _points(before, ctx, was, old), _points(after, ctx, now, new)
        impossible = next((i for i in part_state.on(after.opened, now, after.found) if i.code == graph.NO_INPUT),
                          None)          # the study's error: its mesh has no input (§ 2.2)
        prep = view.command(STUDY_PREP, project=project, study=name, target=t.name)

        def finished(s: graph.Made) -> bool:
            return state.finished(ctx, seen[s.address])

        def replaced_by(s: graph.Made) -> list[graph.Made]:
            return [o for a, o in old.stages.items() if a not in stages
                    and (o.kind, o.filled.environment) == (s.kind, s.filled.environment)
                    and old_points.get(a, set()) & new_points.get(s.address, set())]

        for address, s in stages.items():
            if address in old.stages:
                continue
            gone = replaced_by(s)
            what = f"the {s.kind} {cases.short(s.id)} is made anew for {t.name}"
            if gone:
                what += f", in place of {cases.short(gone[0].id)}" + (", whose finished run is no longer used"
                                                                       if finished(gone[0]) else "")
            out.append(_stage_line(gone[0].address if gone else address, MADE_ANEW, "info", what, prep))
        replacing = {o.address for s in stages.values() if s.address not in old.stages for o in replaced_by(s)}
        for address, o in old.stages.items():
            if address in stages:
                continue
            dropped.append(o)
            if address in replacing:
                continue
            if impossible is not None:
                out.append(_stage_line(address, MADE_IMPOSSIBLE, "warning",
                                       f"the {o.kind} {cases.short(o.id)} is made impossible: {impossible.message}",
                                       view.command(PROJECT_CHECK, project=project)))
            else:
                out.append(_stage_line(address, NO_LONGER_NEEDED, "info",
                                       f"the {o.kind} {cases.short(o.id)} is no longer needed by any case of {name}"
                                       + (", its finished run kept" if finished(o) else ""), prep))
    return out, dropped


def _stage_line(subject: str, code: str, severity: str, message: str, *next_: view.Action) -> Issue:
    """A line about a stage, by its address: the stage diagram marks it there (web.md § 2.4)."""
    return Issue(severity=severity, code=code, subject=subject, message=message, next=next_)


# ------------------------------------------------------------------ the jobs going

def _jobs(ctx: Context, after: Side, dropped: list[tuple[str, graph.Made]]) -> list[Issue]:
    """Each job still going that runs a stage the change replaces or drops (jobs.md § 5.4): it runs
    on with what it was given, and its result serves no case of the study as changed — its `job
    cancel` where it went in the background, which stops it."""
    here, out, said = record.host_identity(), [], set()
    for name, s in dropped:
        job = addresses.running(ctx, s.folder, here)
        if job is None or job.id in said:
            continue
        said.add(job.id)
        out.append(Issue(severity="warning", code=JOB_GOING, subject=str(JobAddress(job.id)),
                         message=f"the job {job.id} still runs the {s.kind} {cases.short(s.id)}: it "
                                 f"runs on with what it was given, and its result serves no case of {name} as changed",
                         next=(view.command(JOB_CANCEL, id=job.id),) if job.how == "background" else ()))
    return out
