"""A study's workflow graph (workflow.md § 3): derived for one machine's record from the opened
project, the cases the study makes now — written by `study prep` or not, so a change shows at
once — the declared stage kinds, meshers and hand-overs; never stored. For each case, in its
study's order: one geometry stage and one mesh stage, by the mesher its recipe states, each the
study's own, holding nothing of an engine and serving every engine (§ 4) — the cases whose content
is the same share it. Each stage is a node of the vocabulary's one graph document (web.md § 7.6), of the family
`stage` — its address, kind, typed ports, state, word and actions, and `made_from`, the parts and
stages it is made from; each output port with the file the stage's newest finished run holds and
the lines that open it (`outputs`, workflow.md § 8); a wire joins each output to the input of the
same artifact type it feeds; each case is a box around the stages it alone needs, and the stages
several cases share lie in a box of their own, which serves them, so boxes of one kind never
overlap. A geometry or a mesh stage's node names no engine (web.md § 7.6): the engine is a solve
stage's alone, which joins with each engine's input writer (plan § 4, M6).

Two kinds of stage are read by their declarations, never by their names: the kind that reads no
stage's output — the geometry's — and the kind a mesher fills — the mesh's (workflow.md §§ 2.1,
2.3).

A mesher whose input no stage before it writes — the pass-through for a component that declares no
mesh — or that makes no mesh at a case's geometry order, is a finding at the study's `mesh`,
`no-input` (§ 2.2): an error, whatever engine solves, which this module's part check gives `project
check` at each case's geometry order before anything runs, so the study's state is `errors` and
`study prep` refuses it at its first step, `has-findings`, whatever machine record is there; the
graph draws no stage of a case whose mesh has none. Whether an engine takes the mesh — a hand-over
gives it what the mesher writes at the mesh's order, the models' one rule (`study.takes`) — is
asked when an engine is chosen, `study prep --engine`, said in that prep's refusal in the same
words (`taking`; § 7).

Where the target's record cannot form the stages' identity — it lacks the install fingerprint of
the environment one of them runs in, `no-fingerprint` (§ 4) — that refusal stands (§ 7). A
refusal said as a finding is made so by the door's one way (`door.finding_of`).

A step for another machine's target of an operation that acts on the machine it runs on, as its
verb declares it — `job launch` of a job, a stage's missing fingerprint's `env install` and probe —
and the line that opens an output carry that machine (`Action.on`, web.md § 7.2): `there` sets
it, for `study flow`'s steps and `study prep`'s alike, giving each field the request's model
declares names a folder or a file (`schema.path_fields`), and no other, by its path from the
project's folder (`located`), never an operation this machine runs; `study prep`, `study flow` and
`job prepare` run here for any target, and stay operations (workflow.md § 7; jobs.md § 1).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Iterator, Mapping

from femkit.core import text, view
from femkit.core.errors import Refusal, Unstated
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.schema import field_extras, render_arguments
from femkit.core.view import CASE, IN, OUT, SHARED, STAGE, Box, Fact, Graph, GraphNode, GraphPort, Wire
from femkit.definitions import catalogue
from femkit.definitions.meshers import HandOver, MesherDefinition
from femkit.definitions.stages import PYTHON, StageKind
from femkit.geometry.component import Component, Outputs
from femkit.jobs import prepare, runs
from femkit.models import cases, study as studies
from femkit.projects import door
from femkit.projects.addresses import Stage as StageAddress
from femkit.projects.checking import Checking, Registration
from femkit.projects.door import Opened, Part
from femkit.workflow import identity, state

NO_INPUT = "no-input"   # a stage's input no stage before it writes (workflow.md § 2.2)


@dataclass(frozen=True)
class Definitions:
    """What the graph reads of the shipped definitions: the stage kinds, the meshers, the
    hand-overs, and each engine `study prep --engine` may name, with the environment it resolves to."""

    stages: Mapping[str, StageKind]
    meshers: Mapping[str, MesherDefinition]
    handovers: Mapping[str, HandOver]
    engines: Mapping[str, str]

    @classmethod
    def of(cls, c: Checking) -> "Definitions":
        """As the check frame hands them (projects.md § 6)."""
        return cls(c.stages, c.meshers, c.handovers, c.engines)

    def made_first(self) -> str:
        """The kind that reads no stage's output: a case's first stage, the geometry's."""
        (found,) = [k for k, v in self.stages.items() if v.made and v.filled_by is None and not v.inputs]
        return found

    def filled(self) -> str:
        """The kind a mesher fills: a case's mesh stage."""
        (found,) = [k for k, v in self.stages.items() if v.filled_by is not None]
        return found


# ------------------------------------------------------------------ the mesher and the hand-over

@dataclass(frozen=True)
class Meshed:
    """How a case's mesh is made: its mesher, by name, its definition, and the geometry order of
    its mesh (workflow.md § 2.3)."""

    mesher: str
    definition: MesherDefinition
    order: int


@dataclass(frozen=True)
class NoInput:
    """Why a case's mesh has no input, or reaches not the engine chosen: said at the study's
    `mesh` (workflow.md § 2.2)."""

    message: str


def asked(d: Definitions, contract: Component, read: set[str]) -> dict[str, bool]:
    """Whether a case's first stage gives each output it writes only when asked, by its role — the
    one place that is decided (workflow.md § 2.1): one the component's contract may declare under
    `[outputs]`, by that role, where the contract declares it; any other, where a stage after it
    reads its type, one of ``read``."""
    own = set(Outputs.model_fields)
    return {role: getattr(contract.outputs, role) is not None if role in own else ty in read
            for role, ty in d.stages[d.made_first()].asked.items()}


def given(kind: StageKind, asks: Mapping[str, bool]) -> dict[str, str]:
    """The outputs a stage of ``kind`` gives, by role, each with its artifact type: those it always
    writes, and each it writes only when asked that ``asks`` says is asked."""
    return {**(kind.outputs or {}), **{role: ty for role, ty in kind.asked.items() if asks.get(role)}}


def gives(d: Definitions, contract: Component, read: set[str]) -> dict[str, str]:
    """The outputs a case's first stage gives, by role, the stage after it reading ``read``."""
    return given(d.stages[d.made_first()], asked(d, contract, read))


def meshed(d: Definitions, engine: str | None, mesher: str, order: int, contract: Component
           ) -> Meshed | NoInput | None:
    """How a case's mesh is made at the recipe's geometry ``order``: the mesher its recipe states,
    and its order — the recipe's, or the contract's mesh's (`study.meshed_order`). Its finding where
    the mesher reads what no stage before it writes, or, given an ``engine`` chosen to solve, no
    hand-over gives that engine its mesh at that order (`study.takes`; workflow.md § 2.2); None for
    a mesher femkit lacks — the recipe's own finding — or an engine femkit lacks."""
    if mesher not in d.meshers or (engine is not None and engine not in d.engines):
        return None
    m = d.meshers[mesher]
    used = studies.meshed_order(m, order, contract)
    lacking = sorted(t for t in m.reads.values() if t not in gives(d, contract, set(m.reads.values())).values())
    if used is None or lacking:
        return NoInput(f"the mesher {mesher} reads {', '.join(lacking) or 'the mesh the script writes'}, which no stage "
                       "before it writes: the component's contract declares no mesh its script writes")
    if used not in m.orders:
        return NoInput(f"the mesher {mesher} makes no mesh at geometry order {used}")
    if engine is not None and not studies.takes(d.handovers, engine, m, used):
        return NoInput(f"no hand-over gives {engine} the mesh {mesher} writes at geometry order {used}: the engine "
                       f"{engine} cannot take this recipe's mesh")
    return Meshed(mesher=mesher, definition=m, order=used)


def _meshes(c: Checking, study: Part, engine: str | None) -> NoInput | None:
    """Why the study's recipe gives it no mesh — at a case's geometry order, the mesher the recipe
    states reads what no stage before it writes or makes no mesh at that order, or, given an
    ``engine``, no hand-over gives that engine its mesh (`meshed`) — the first case's alone; None
    where it gives one, or a part it names does not load, whose own finding says why."""
    holder = studies.cites(c, "component", study.data.component)
    recipe = studies.cites(c, "mesh", study.data.mesh)
    if holder is None or recipe is None or not isinstance(holder.data, Component):
        return None
    d = Definitions.of(c)
    return next((found for order in studies.orders(c, study, recipe)
                 if isinstance(found := meshed(d, engine, recipe.data.mesher, order, holder.data), NoInput)), None)


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """A study's recipe gives it a mesh, whatever engine solves (workflow.md § 2.2): at each case's
    geometry order, the mesher the recipe states reads what the geometry gives — its finding,
    `no-input`, an error at the study's `mesh`, once, since an error is what refuses prep
    (projects.md § 8; models.md § 5.3)."""
    found = _meshes(c, part, None)
    if found is not None:
        yield c.issue(part, "mesh", code=NO_INPUT, message=found.message)


def taking(c: Checking, study: Part, engine: str) -> str:
    """Why ``engine`` cannot take the mesh the study's recipe makes, in the words a finding at its
    `mesh` says it (workflow.md § 2.2) — what `study prep --engine` refuses with."""
    found = _meshes(c, study, engine)
    return found.message if found is not None else f"the engine {engine} cannot take this recipe's mesh"


REGISTERS = Registration(checks={studies.KEY: check})


# ------------------------------------------------------------------ the stages

@dataclass
class Made:
    """One stage, as the graph derives it: its kind, filled by its mesher where one fills it; what it
    is made from and its ID; the artifacts it gives and those it takes, each from the stage and
    output that feed it; what the person brings to it — the files of the part its kind brings, the
    component's script among them; the case whose content makes it; its folder."""

    kind: str
    filled: StageKind
    mesher: str | None
    made: identity.MadeFrom
    id: str
    address: str
    folder: Path
    gives: dict[str, str]                                     # each output it gives, by role: its type
    asked: dict[str, bool]                                    # each output it gives only when asked: given?
    takes_from: dict[str, tuple[str, "Made", str]] = field(default_factory=dict)   # role: (type, from, its role)
    brings: dict[str, bytes] = field(default_factory=dict)    # what the person brings, copied in by its name
    case: cases.Case | None = None
    made_from: list[str] = field(default_factory=list)


@dataclass
class Derived:
    """A study's stages for one machine: each by its address, in the order its cases need them —
    a stage before every stage that takes from it; each case's stages; the study's findings; and
    the engines that can solve it, which a stage's prep may name (`study.solvers`; workflow.md § 7)."""

    opened: Opened
    study: Part
    target: prepare.Target
    stages: dict[str, Made]
    cases: list[tuple[str, list[str]]]
    issues: list[Issue]
    engines: list[str] | None = None


def fill(kind: StageKind, m: MesherDefinition) -> StageKind:
    """A stage kind with the slots its mesher fills (workflow.md § 2.3): its environment, what it
    reads and writes, and its program — `{python}`, the mesher's program, its arguments."""
    return kind.model_copy(update={"environment": m.provided_by, "inputs": dict(m.reads), "outputs": dict(m.writes),
                                   "asked": {}, "program": ["{" + PYTHON + "}", m.program, *m.arguments]})


def brought(c: Checking, study: Part, kind: StageKind) -> Part | None:
    """The part a stage of ``kind`` brings the files of (`brings`, workflow.md § 2.1): the one of its
    kind the study names — its component, by the study's field whose `ref` is that kind; none for a
    kind that brings none."""
    if kind.brings is None:
        return None
    field = next(n for n, f in type(study.data).model_fields.items() if field_extras(f).get("ref") == kind.brings)
    return studies.cites(c, field, getattr(study.data, field))


def derive(ctx: Context, opened: Opened, c: Checking, study: Part, made_now: list[cases.MadeCase],
           t: prepare.Target) -> Derived:
    """The stages the cases ``study`` makes now need — written by `study prep` or not — for the
    machine ``t``, chosen as `job prepare` chooses it (workflow.md §§ 3, 4): for each case, its
    geometry and its mesh, by the mesher its recipe states, the study's own, serving every engine —
    none where a case's mesh has no input: the study's error, `no-input`, its part check's (`check`,
    § 2.2)."""
    d = Definitions.of(c)
    data = study.data
    component = studies.cites(c, "component", data.component)
    recipe = studies.cites(c, "mesh", data.mesh)
    contract: Component = component.data
    first, then = d.made_first(), d.filled()
    issues: list[Issue] = []
    routes: dict[str, Meshed] = {}
    for m in made_now:
        found = meshed(d, None, m.case.mesh.mesher, int(Fraction(m.case.mesh.order)), contract)
        if isinstance(found, Meshed):
            routes[m.id] = found
    geometry_kind = d.stages[first]
    programs = catalogue.stage_programs()
    stages: dict[str, Made] = {}
    order: list[tuple[str, list[str]]] = []

    def placed(kind: str, filled: StageKind, mesher: str | None, of: dict, case: cases.Case, asks: dict[str, bool],
               takes_from: dict[str, tuple[str, Made, str]] | None = None, **more) -> Made:
        took = {role: identity.Took(kind=source.kind, id=source.id)
                for role, (_, source, _) in (takes_from or {}).items()}
        made = identity.made(ctx, kind, filled.femkits(programs), t, filled.environment, took, **of)
        sid = identity.identity(made)
        address = str(StageAddress(study.address.name, kind, sid))
        if address not in stages:
            part = brought(c, study, filled)
            brings = {h.name: h.data for h in opened.held_by(part.address).values()} if part is not None else {}
            stages[address] = Made(kind=kind, filled=filled, mesher=mesher, made=made, id=sid, address=address,
                                   folder=door.stage_folder(opened, study.address.name, kind, sid),
                                   gives=given(filled, asks), asked={r: bool(asks.get(r)) for r in filled.asked},
                                   brings=brings, case=case, takes_from=takes_from or {}, **more)
        return stages[address]

    try:
        for m in made_now:
            case, r = m.case, routes.get(m.id)
            if r is None:
                order.append((m.id, []))
                continue
            asks = asked(d, contract, set(r.definition.reads.values()))
            geometry = placed(first, geometry_kind, None, dict(
                component=case.component.drawing(),
                mesh_order=contract.outputs.mesh.order if contract.outputs.mesh is not None else None,
                outputs=list(given(geometry_kind, asks).values())),
                case, asks, made_from=[str(component.address), str(study.address)])
            filled = fill(d.stages[then], r.definition)
            took = {role: (ty, geometry, next(o for o, g in geometry.gives.items() if g == ty))
                    for role, ty in r.definition.reads.items()}
            mesh = placed(then, filled, r.mesher, dict(recipe=case.mesh, mesher=r.mesher), case, {}, takes_from=took,
                          made_from=[geometry.address, str(recipe.address), str(study.address)])
            order.append((m.id, list(dict.fromkeys((geometry.address, mesh.address)))))
    except Unstated as exc:
        if exc.code != identity.NO_FINGERPRINT:
            raise
        raise there_all(opened, t, exc) from None
    return Derived(opened=opened, study=study, target=t, stages=stages, cases=order, issues=issues,
                   engines=studies.solvers(c, study))


def observed(ctx: Context, derived: Derived, target: str | None) -> dict[str, state.Seen]:
    """Each stage observed (workflow.md § 6), by its address, in the order derived — a stage after
    every stage it takes from — its next steps named for the study's project and the target asked,
    the engine its prep asks for one of those that can solve the study (workflow.md § 7)."""
    out: dict[str, state.Seen] = {}
    for s in derived.stages.values():
        out[s.address] = state.observe(ctx, s.address, s.folder, project=derived.opened.project.name,
                                       study=derived.study.address.name, target=target,
                                       takes_from=[out[source.address] for _, source, _ in s.takes_from.values()],
                                       engines=derived.engines)
    return out


# ------------------------------------------------------------------ a step on the target's machine

def located(opened: Opened, t: prepare.Target, path: Path) -> str:
    """A folder or a file of the project as a line on the target's machine names it: on this
    machine, by its full path (jobs.md § 1); on another, by its path from the project's folder,
    which that line is typed in, as the project forms it (workflow.md § 7)."""
    return str(path) if t.here or not Path(path).is_relative_to(opened.project.folder) \
        else opened.project.relative(Path(path))


def there(opened: Opened, t: prepare.Target, action: view.Action) -> view.Action:
    """A next step as the target's machine takes it (workflow.md § 7; web.md § 7.2), by the core's
    one way (`view.at`): for another machine's target, a step of an operation that acts on the
    machine it runs on, or a shell line — the one that opens an output — carrying that machine, each
    path field of its request from the project's folder; any other — `study prep`, `study flow`,
    `job prepare` — runs here for any target, and stays the operation it is."""
    return view.at(action, None if t.here else view.Machine(t.name, opened.project.folder))


def there_all(opened: Opened, t: prepare.Target, exc: Refusal) -> Refusal:
    """A refusal whose next steps are each taken as the target's machine takes it (`there`)."""
    exc.next = tuple(there(opened, t, a) for a in exc.next)
    return exc


# ------------------------------------------------------------------ the outputs, opened

@dataclass(frozen=True)
class Output:
    """A stage's output as its newest finished run holds it (workflow.md § 8): its file, and the
    lines that open it."""

    file: Path
    actions: list[view.Action]


def outputs(ctx: Context, derived: Derived, seen: Mapping[str, state.Seen]
            ) -> tuple[dict[tuple[str, str], Output], list[Issue]]:
    """Each output a stage's newest finished run holds, by the stage's address and the output's
    role (workflow.md § 8): its file, opened as its artifact type says — where it names an
    environment and a command, a `shell` line entering that environment on the target as its
    record says, as a run script enters it, its preamble then its activation (jobs.md § 4, block 8),
    then the command on the file, named as a line on the target's machine names it (`located`); a
    type it names none for, the file alone. Where the record cannot enter that environment, the
    file alone, and why as a finding, once: the graph is shown all the same (workflow.md § 7)."""
    artifacts, t = catalogue.artifacts(ctx), derived.target
    out: dict[tuple[str, str], Output] = {}
    said: dict[tuple, Issue] = {}
    for s in derived.stages.values():
        now = seen[s.address]
        run = now.facts.calculation.newest.run if state.finished(ctx, now) else None
        for role, ty in s.gives.items() if run is not None else ():
            a, file, actions = artifacts[ty], runs.output(run, artifacts[ty].file), []
            if a.opened is not None:
                env = a.opened.environment
                try:
                    entry = prepare.target_environment(ctx, t.name, t.record, env).entry
                except Refusal as exc:
                    said.setdefault((exc.code, exc.subject), door.finding_of(
                        derived.opened, exc, "warning",
                        f"the outputs made in {env} are shown without the line that opens them: {exc}"))
                else:
                    actions = [there(derived.opened, t, view.shell(" && ".join([*entry.lines, shlex.join(
                        render_arguments(a.opened.command, {"file": located(derived.opened, t, file)}))])))]
            out[(s.address, role)] = Output(file=file, actions=actions)
    return out, list(said.values())


# ------------------------------------------------------------------ the graph document

def _boxes(derived: Derived) -> list[Box]:
    """Each case a box around the stages it alone needs, and the stages several cases share in a
    box of their own for each set of cases they serve, its `serves` those cases' boxes — so boxes of
    one kind never overlap (web.md § 7.6)."""
    study = derived.study.address.name
    address = {case_id: door.case_file(derived.opened, study, case_id) for case_id, _ in derived.cases}
    serving: dict[str, list[str]] = {}
    for case_id, members in derived.cases:
        for m in members:
            serving.setdefault(m, []).append(address[case_id])
    boxes = [Box(address=address[case_id], label=cases.short(case_id), kind=CASE,
                 members=[m for m in members if len(serving[m]) == 1]) for case_id, members in derived.cases]
    shared: dict[tuple[str, ...], list[str]] = {}
    for m, served in serving.items():
        if len(served) > 1:
            shared.setdefault(tuple(served), []).append(m)
    return [*boxes, *(Box(address="+".join(served), label=f"shared by {text.count(len(served), 'case')}", kind=SHARED,
                          members=members, serves=list(served)) for served, members in shared.items())]


def facts(environment: str, folder: Path) -> list[Fact]:
    """What a person reads of a stage (web.md § 7.6): the environment it runs in, and its calculation
    folder — each said once here, for every surface; a geometry's or a mesh's names no engine."""
    return [Fact(label="environment", value=environment), Fact(label="folder", value=text.path(folder))]


def graph(ctx: Context, derived: Derived, seen: Mapping[str, state.Seen],
          made: Mapping[tuple[str, str], Output]) -> Graph:
    """The workflow graph's document (web.md § 7.6; workflow.md § 3): each stage, of the family
    `stage`, with its state, its word and its state's next steps, its ports typed by the artifacts
    it takes, `in`, and gives, `out` — each output with the file its newest finished run holds and
    the lines that open it, as ``made`` holds them (workflow.md § 8) — a wire from each output to the
    input it feeds; each case a box around its own stages, and the stages cases share a box of their
    own (`_boxes`)."""
    m = state.machine(ctx)
    feeds: dict[tuple[str, str], list[str]] = {}
    wires = []
    for s in derived.stages.values():
        for role, (ty, source, out) in s.takes_from.items():
            feeds.setdefault((source.address, out), []).append(s.address)
            wires.append(Wire(source=source.address, source_port=out, target=s.address, target_port=role, type=ty))
    nodes = []
    for s in derived.stages.values():
        now = seen[s.address]
        ports = [GraphPort(name=role, side=IN, accepts=[ty], many=False, names=[source.address])
                 for role, (ty, source, _) in s.takes_from.items()]
        for role, ty in s.gives.items():
            o = made.get((s.address, role))
            ports.append(GraphPort(name=role, side=OUT, accepts=[ty], many=False,
                                   names=feeds.get((s.address, role), []), file=str(o.file) if o else None,
                                   actions=o.actions if o else []))
        nodes.append(GraphNode(address=s.address, family=STAGE, kind=s.kind, type=s.mesher,
                               label=s.kind, state=now.state.value, shows=m.word(now.state),
                               ports=ports, made_from=s.made_from,
                               actions=[there(derived.opened, derived.target, a) for a in state.next_steps(ctx, now)],
                               environment=s.filled.environment, folder=str(s.folder),
                               facts=facts(s.filled.environment, s.folder)))
    return Graph(nodes=nodes, wires=wires, boxes=_boxes(derived))
