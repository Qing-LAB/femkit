"""The workflow layer (workflow.md): a study's workflow graph for one machine's record — each
case's geometry and mesh stages, the study's own, holding nothing of an engine and shared by
identity within it, typed ports and wires, each case a box — a stage's identity and `stage.json`,
its folder writing into a calculation folder through the jobs domain's one writer, its state and its word, `study flow`, and `study prep` — its steps run in
order, every refusal before anything is written, what needs no machine written where the machine
step cannot go on; the one graph document of the vocabulary (web.md § 7.6); a study's name kept out
of the steps a stage's or launch folder's path takes (projects.md § 5); a request's shares named
among themselves alone (jobs.md § 2); `project save`, writing exactly what the page's editor holds, and
its plan, the change's impact (workflow.md § 10; projects.md § 7). On copies of the templates, with a
record of this machine of the test's own; one job `study prep` writes launched here, on a machine of
stand-ins."""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from fractions import Fraction
from pathlib import Path

import pytest

from tests import kit
from tests.kit import ctx, files, laplace, slab, workstation  # noqa: F401 -- fixtures
from femkit import registry
from femkit.config import settings
from femkit.core import persist, text, view
from femkit.core.errors import PlanStale, Refused, Unstated, UsageError
from femkit.core.operations import SilentObserver
from femkit.core.schema import DefinitionError
from femkit.jobs import folders, layout, record, runs
from femkit.jobs.request import JobRequest, context
from femkit.projects import door

FINGERPRINT = "f" * 64


def a_second_study(folder: Path, name: str = "second") -> None:
    """A second study of the project, written whole, the Laplace check's copy, and named by its
    project file."""
    (folder / "studies" / f"{name}.toml").write_text((folder / "studies" / "check.toml").read_text())
    kit.rewrite(folder / "project.toml", 'studies = ["check"]', f'studies = ["check", "{name}"]')


@pytest.fixture
def here(tmp_path):
    """This machine as config.toml and its record state it: activation by `conda activate`, the
    manager's root a folder of the test's own, and the `gmsh` environment listed with its install
    fingerprint — what forming a stage's identity reads (workflow.md § 4)."""
    kit.apply("config.init", no_preamble=True, command="conda activate",
              mpi=["mpirun", "-np", "{ranks}"], cuda_architectures=["80"])
    return write_record("local", gmsh=FINGERPRINT)


def write_record(name: str, identity: str | None = None, root: str = "/x", absent: tuple[str, ...] = (),
                 manager: str = "/x/bin/conda", **fingerprints: str | None) -> Path:
    """A record of a machine without a scheduler, its environments each listed with the install
    fingerprint given — none, for one listed with its fingerprint unknown — and those ``absent``
    listed not installed, as `job probe` lists them; its manager ``manager``, its root ``root`` and
    its control environment beside it."""
    config = settings.load(kit.ctx(), fresh=True).config
    r = kit.a_record(identity=identity or record.host_identity(), scheduler={"kind": "local"}, partitions={},
                     queues=[], manager={"kind": "conda", "path": manager, "version": "26.7", "root": root,
                                         "platform": "linux-64", "run_enters": True},
                     environments={**{e: {"state": "ready", **({"install_fingerprint": f} if f else {})}
                                      for e, f in fingerprints.items()}, **{e: {"state": "absent"} for e in absent}},
                     settings=record.settings_now(config).model_dump(exclude_none=True))
    return record.write(record.path(name), r)


def sequences(outcome) -> list[str]:
    """Each job `study prep` wrote, by its sequence's full path — none it stated again (workflow.md § 7)."""
    return [j.sequence for j in outcome.jobs if j.restated is None]


def flow(project: str = "laplace_square", study: str = "check", **more):
    return kit.run("study.flow", project=project, study=study, **more)


def by_kind(result) -> dict[str, list]:
    """The graph's stages by their kind."""
    out: dict[str, list] = {}
    for n in result.graph.nodes:
        out.setdefault(n.kind, []).append(n)
    return out


def stage_file() -> str:
    """The file a stage's folder keeps what it is made from in, as the workflow declares it
    (`stages.toml`; workflow.md § 4)."""
    from femkit.workflow import identity
    return identity.named(kit.ctx())


def made_of(folder: Path) -> dict:
    """What a stage's folder keeps it is made from, `stage.json`."""
    return json.loads((folder / stage_file()).read_text())


def tasks() -> dict[str, str]:
    """What `study prep` does to a stage, by the stage table's own tasks, each with its sentence
    (workflow.md § 6; core.md § 7, `[tasks]`): never an action of its states, which are next
    steps."""
    from femkit.workflow import state
    return dict(state.machine(kit.ctx()).tasks)


SIDE_AXIS = '[axes."project:definitions.side"]\nclass = "physical sweep"\nvalues = [1, 2, 3]\nunit = "m"\n'


def sweep_side(folder: Path) -> None:
    """The Laplace study swept over the definition its script reads, instead of the mesh's size."""
    study = folder / "studies" / "check.toml"
    text = study.read_text()
    start = text.index('[axes."mesh:uniform:size"]')
    end = text.index("\n\n", start)
    study.write_text(text[:start] + SIDE_AXIS + text[end:])


# ------------------------------------------------------------------ one graph document (web.md § 7.6)

def test_the_project_graph_is_the_vocabularys_one_graph_document(laplace):
    """Fails if `project graph` answers with a graph of models of its own rather than the
    vocabulary's one `Graph` — its nodes `GraphNode`s, its wires `Wire`s, its boxes `Box`es — or a
    part's node names no file it opens as, or a node carries `made_from` while it is no stage
    (web.md § 7.6: "every diagram the page draws, one shape"; models.md § 11.2)."""
    result = kit.run("project.graph", project="laplace_square")
    graph = result.graph
    assert type(graph) is view.Graph
    assert all(type(n) is view.GraphNode for n in graph.nodes) and all(type(w) is view.Wire for w in graph.wires)
    nodes = {n.address: n for n in graph.nodes}
    assert [f.address for f in nodes["component:square"].files] == ["component:square", "component:square@geometry.py"]
    assert [f.address for f in nodes["physics:electrostatics"].files] == ["physics:electrostatics"]
    assert all(not n.made_from for n in graph.nodes)
    assert nodes["mesh:uniform"].files[0].text == (laplace / "mesh" / "uniform.toml").read_text()
    assert "cases" not in view.GraphNode.model_fields


def test_a_grouping_folder_is_a_box_around_its_parts(laplace):
    """Fails if a part in a grouping folder is not a member of that folder's box, or a part at the
    top of its kind's folder is (web.md § 2.4: the description's boxes are "the person's grouping
    folders"; models.md § 11.2)."""
    (laplace / "studies" / "sweeps").mkdir()
    (laplace / "studies" / "check.toml").rename(laplace / "studies" / "sweeps" / "check.toml")
    kit.rewrite(laplace / "project.toml", '"check"', '"sweeps/check"')
    graph = kit.run("project.graph", project="laplace_square").graph
    boxes = {b.label: b for b in graph.boxes}
    assert list(boxes) == ["sweeps"] and boxes["sweeps"].members == ["study:sweeps/check"]


def test_the_command_lines_table_of_nodes_shows_the_box_each_sits_in_by_its_label(laplace):
    """Fails if the command line's table of a graph's nodes does not show the box each node sits
    in, by the box's label, under the heading the box's label declares — a part in a grouping
    folder that folder's, a part at the top of its kind's folder none (web.md § 7.5: "On the
    command line a graph is written as its tables"; § 7.6: `Box`)."""
    (laplace / "studies" / "sweeps").mkdir()
    (laplace / "studies" / "check.toml").rename(laplace / "studies" / "sweeps" / "check.toml")
    kit.rewrite(laplace / "project.toml", '"check"', '"sweeps/check"')
    nodes = text.drawn(kit.run("project.graph", project="laplace_square").graph)[0]
    box = next(c for c in nodes.columns if c.label == "box")
    sits = {row["address"]: row[box.key] for row in nodes.rows if row[box.key]}
    assert sits == {"study:sweeps/check": "sweeps"}


# ------------------------------------------------------------------ the workflow graph (workflow.md § 3)

def test_a_meshes_size_sweep_makes_one_geometry_and_a_mesh_for_each_size_the_studys_own(laplace, here):
    """Fails if the cases of a sweep of the mesh's size do not share their one geometry — a sweep of
    what the script does not read — or each case has not its own mesh, by the mesher its recipe
    states, wired from the geometry's output of the type that mesher reads; or a case is not a box
    around its stages; or a stage's `made_from` is not the parts and the stage it is made from; or
    two studies alike share a stage, each study's
    stages its own, in its own folder (workflow.md §§ 3, 4; plan § 4, X acceptance: "of one it does
    not read one in all")."""
    result = flow()
    stages = by_kind(result)
    (geometry,) = stages["geometry"]
    assert len(stages["mesh"]) == 3 and all(m.type == "gmsh" for m in stages["mesh"])
    assert geometry.address.startswith("stage:check/geometry/")
    assert geometry.made_from == ["component:square", "study:check"]
    assert {m.made_from[0] for m in stages["mesh"]} == {geometry.address}
    assert all(m.made_from[1:] == ["mesh:uniform", "study:check"] for m in stages["mesh"])
    wires = {(w.source, w.source_port, w.target, w.target_port, w.type) for w in result.graph.wires}
    assert wires == {(geometry.address, "output", m.address, "geometry", "geometry/xao") for m in stages["mesh"]}
    ports = {(p.name, p.side): p.accepts for p in stages["mesh"][0].ports}
    assert ports == {("geometry", "in"): ["geometry/xao"], ("mesh", "out"): ["mesh/msh-2.2"],
                     ("regions", "out"): ["mesh/regions"]}
    assert len([b for b in result.graph.boxes if b.kind == "case"]) == 3
    a_second_study(laplace)
    other = flow(study="second")
    assert len(other.graph.nodes) == 4 and all(n.address.startswith("stage:second/") for n in other.graph.nodes)
    assert {n.address for n in result.graph.nodes}.isdisjoint(n.address for n in other.graph.nodes)


def test_a_stage_several_cases_share_lies_in_a_shared_box_so_no_two_boxes_of_one_kind_overlap(laplace, here):
    """Fails if a stage the cases of a sweep share lies in each of their boxes — boxes of one kind
    overlapping — rather than in one box of kind `shared` whose `serves` are the boxes of the cases
    it serves, each case's box holding its own stages alone (web.md § 7.6: "Boxes of one kind never
    overlap: a stage several cases share lies in a box of kind `shared`, its `serves` the cases it
    serves")."""
    result = flow()
    boxes = {b.address: b for b in result.graph.boxes}
    held = [m for b in boxes.values() for m in b.members]
    for kind in {b.kind for b in boxes.values()}:
        members = [m for b in boxes.values() if b.kind == kind for m in b.members]
        assert len(members) == len(set(members)), kind
    geometries = {n.address for n in by_kind(result)["geometry"]}
    (shared,) = [b for b in boxes.values() if b.kind == "shared"]
    assert set(shared.members) == geometries and set(shared.serves) == {b.address for b in cases(result)}
    assert {boxes[c].kind for c in shared.serves} == {"case"}
    assert all(len(b.members) == 1 and geometries.isdisjoint(b.members) for b in cases(result))
    assert set(held) == {n.address for n in result.graph.nodes}


def test_a_geometry_or_mesh_stage_names_no_engine_and_the_table_shows_the_box_each_sits_in(laplace, here):
    """Fails if a geometry or a mesh stage's node names an engine — it is its study's, made for no
    engine; `engine` is a solve stage's alone, never read from a label — or the command line's table
    of the stages does not show the box each sits in, by its label: its case's, or the box of the
    stages several cases share (web.md § 7.5: "a graph is written as its tables"; § 7.6: `engine`,
    `Box`; ADR 0025 decision 1)."""
    result = flow()
    assert result.graph.nodes and all(n.engine is None and n.label == n.kind for n in result.graph.nodes)
    nodes = text.drawn(result.graph)[0]
    box = next(c for c in nodes.columns if c.label == "box")
    held = {m: b.label for b in result.graph.boxes for m in b.members}
    assert {row["address"]: row[box.key] for row in nodes.rows} == {n.address: held[n.address]
                                                                    for n in result.graph.nodes}
    assert {"shared by 3 cases"} < set(held.values())


def test_a_stage_and_a_part_of_one_kinds_name_are_told_apart_by_their_family(laplace, here):
    """Fails if a stage's node is not of the family `stage`, so the mesh stage and the mesh recipe —
    each of the kind `mesh` — cannot be told apart, each its own icon (web.md § 7.6: "`family` —
    `part`, `object` or `stage` — and `kind` within it ... so the mesh recipe (`part`, `mesh`) and
    the mesh stage (`stage`, `mesh`) are told apart")."""
    stages = {(n.family, n.kind) for n in flow().graph.nodes}
    parts = {(n.family, n.kind) for n in kit.run("project.graph", project="laplace_square").graph.nodes
             if n.address == "mesh:uniform"}
    assert stages == {("stage", "geometry"), ("stage", "mesh")} and parts == {("part", "mesh")}


def test_a_sweep_of_a_parameter_the_script_reads_makes_a_geometry_for_each_value(laplace, here):
    """Fails if a sweep of a parameter the component's script reads makes fewer geometries than
    values — the geometry stage is named by what it is made from, the value of each input its
    contract declares among it (workflow.md § 4; plan § 4, X acceptance: "a sweep of
    a parameter the script reads making one geometry and one mesh per value")."""
    sweep_side(laplace)
    stages = by_kind(flow())
    assert len(stages["geometry"]) == 3 and len(stages["mesh"]) == 3

def test_each_stage_reads_its_own_state_word_and_next_step_before_anything_is_made(laplace, here):
    """Fails if, before anything is made, a geometry does not read `to_prep`, *needs update*, its
    next step `study prep` of its study, and a mesh `waiting`, *waiting*, its next steps what the
    geometry it takes from allows; or a stage names a folder other than the one the door forms for
    it (workflow.md §§ 4, 6: "`to_prep` | it has no folder for this machine, or its identity cannot
    be formed yet … | `study prep`"; "a waiting stage's next steps are those of the stage it waits
    on, declared"; web.md § 7.6; ADR 0022 decision 7)."""
    result = flow()
    opened = kit.opened(laplace)
    for n in result.graph.nodes:
        kind, id_ = n.address.split("/")[-2:]
        assert (n.state, n.shows) == (("to_prep", "needs update") if kind == "geometry" else ("waiting", "waiting"))
        assert Path(n.folder) == door.stage_folder(opened, "check", kind, id_)
        assert [(a.call.operation, a.call.request["study"]) for a in n.actions] == [("study.prep", "check")]


def test_each_stage_says_its_environment_and_folder_as_facts_its_operation_builds(laplace, here):
    """Fails if a stage's node does not carry, as facts `study flow` builds, the environment it runs in
    and its calculation folder — so a surface would build them itself from the node's fields, a
    second home of what a person reads of a stage — or a geometry's or a mesh's says an engine,
    which is a solve's alone (web.md § 7.6: "`facts` what a person reads of it, each a `Fact {label,
    value, shows}` its operation builds, drawn generically"; workflow.md § 4)."""
    for n in flow().graph.nodes:
        assert [(f.label, f.value) for f in n.facts] == [("environment", n.environment),
                                                         ("folder", text.path(n.folder))]


def test_a_stage_whose_folder_is_there_reads_its_folders_state_whatever_case_first_needed_it(laplace, here):
    """Fails if, once the recipe changed, a geometry whose folder is there — made, finished, for the
    cases that first needed it — reads `to_prep` because the cases the study makes now are not
    written, rather than its folder's state, *up to date*; or the new cases' meshes, with no folder
    for this machine, read other than `to_prep`, their next step `study prep`; or prep writes that
    geometry again rather than using it (workflow.md § 6: "`to_prep` | it has no folder for this
    machine"; "a folder that is there is never written again, whichever case first needed it";
    § 3: the graph drawn from the cases the study makes now)."""
    outcome = prepped()
    (sequence,) = sequences(outcome)
    for g in by_kind(flow())["geometry"]:
        finish(Path(g.folder), Path(sequence))
    kit.rewrite(laplace / "mesh" / "uniform.toml", *TOLERANCE)
    nodes = flow().graph.nodes
    assert {(n.kind, n.state, n.shows) for n in nodes} == {("geometry", "finished", "up to date"),
                                                           ("mesh", "to_prep", "needs update")}
    assert {(a.call.operation, a.call.request["study"]) for n in nodes if n.kind == "mesh"
            for a in n.actions} == {("study.prep", "check")}
    again = prepped()
    assert again.ok() and len(again.added) == 3
    assert {(r.stage.split("/")[-2], tuple(r.does)) for r in again.stages} == {
        ("geometry", ("use",)), ("mesh", ("write", "prepare", "place"))}


# ------------------------------------------------------------------ identity (workflow.md § 4)

def test_a_stages_identity_is_its_machines_another_target_or_fingerprint_another_stage(laplace, here):
    """Fails if the same study formed with another target's record, or with this machine's
    record listing another install fingerprint of the stage's environment, keeps any stage's ID
    (workflow.md § 4: "a rebuilt environment makes a stage anew, a second machine its own")."""
    first = {n.address for n in flow().graph.nodes}
    write_record("other", identity="elsewhere", gmsh=FINGERPRINT)
    assert first.isdisjoint(n.address for n in flow(target="other").graph.nodes)
    write_record("local", gmsh="e" * 64)
    assert first.isdisjoint(n.address for n in flow(target="local").graph.nodes)


def test_the_target_is_chosen_as_job_prepare_chooses_it(laplace, here):
    """Fails if, with a record of another machine present and none named, `study flow` forms a
    stage's identity with this machine's record instead of refusing as `job prepare` does —
    `target-unchosen` — each record's next step `study flow` naming it (workflow.md § 3; jobs.md
    § 3, step 2)."""
    write_record("other", identity="elsewhere", gmsh=FINGERPRINT)
    with kit.refused(Unstated, "target-unchosen") as caught:
        flow()
    assert {(a.call.operation, a.call.request.get("target")) for a in caught.value.next} == {
        ("study.flow", "local"), ("study.flow", "other")}


def test_a_record_of_this_machine_by_another_name_is_this_machines_and_names_the_same_stages(
        laplace, tmp_path, manager, workstation):
    """Fails if, on a cluster whose own record `cluster-a` lies beside `local` — each written there
    by `job probe --write` — `study flow` with no `--target` is refused `target-unchosen`, as if
    `cluster-a` were another machine's, or the stages prepped for `cluster-a` read as other stages
    than `local`'s: the machine a record describes is told by its identity of the host, never its
    name, in one function (workflow.md § 7: "on the cluster, its own record `cluster-a` is this
    machine's, as `local` is"; § 4: "the target's machine, by its record's identity of the host,
    never the record's name"; jobs.md § 3, step 2)."""
    kit.apply("config.init", no_preamble=True, command="source activate",
              mpi=["mpirun", "-np", "{ranks}"], cuda_architectures=["80"])
    kit.installed("gmsh")
    kit.apply("job.probe", write=True)
    kit.apply("job.probe", write=True, name="cluster-a")
    prepped(target="cluster-a")
    result = flow()
    assert result.target == "local" and result.graph.nodes
    assert {n.address for n in result.graph.nodes} == {n.address for n in flow(target="cluster-a").graph.nodes}
    assert {n.state for n in result.graph.nodes} == {"in_launch"}


#: What the environment's table gives an absent one, as next steps (envs.md § 3.3): its install, and its
#: install discarding the saved lock.
INSTALLS = [("env.install", ["gmsh"]), ("env.install", ["gmsh"])]


@pytest.mark.parametrize("listed, steps", [
    ({}, [*INSTALLS, ("job.probe", None)]),
    ({"absent": ("gmsh",)}, [*INSTALLS, ("job.probe", None)]),
    ({"gmsh": None}, [("job.probe", None)]),
], ids=["not listed", "listed not installed", "listed, its fingerprint unknown"])
def test_an_identity_is_refused_without_the_fingerprint_of_its_environment(laplace, here, listed, steps):
    """Fails if a record that does not list the stage's environment, lists it not installed, or
    lists its fingerprint unknown, forms an ID instead of refusing `no-fingerprint`, naming the
    environment, its next steps first, where the record lists it not installed, what its table
    gives an absent one — its install, never written by hand — then the probe that writes the
    record (workflow.md §§ 4, 7; envs.md § 3.3)."""
    write_record("local", **listed)
    with kit.refused(Unstated, "no-fingerprint", "gmsh") as caught:
        flow()
    assert [(a.call.operation, a.call.request.get("names")) for a in caught.value.next] == steps
    assert all(a.note is None for a in caught.value.next)


def test_no_fingerprint_for_another_machines_target_says_its_steps_for_that_machine(laplace, here):
    """Fails if, for another machine's target whose record lists the stage's environment not
    installed, `no-fingerprint`'s next steps — `env install` of it, then the probe — do not carry
    the machine they run on (workflow.md § 7: "next, on that machine"; "every step … carries the
    machine it runs on (`Action.on`)"; web.md § 7.2)."""
    write_record("other", identity="elsewhere")
    with kit.refused(Unstated, "no-fingerprint", "gmsh") as caught:
        flow(target="other")
    assert [(a.call.operation, a.on) for a in caught.value.next] == \
        [("env.install", "other"), ("env.install", "other"), ("job.probe", "other")]


# ------------------------------------------------------------------ meshers and hand-overs (workflow.md §§ 2.2, 2.3)

def name_mesher(folder: Path, mesher: str) -> None:
    """The Laplace recipe stating ``mesher``, as its person would write it (geometry.md § 6)."""
    kit.rewrite(folder / "mesh" / "uniform.toml", 'mesher = "gmsh"', f'mesher = "{mesher}"')


def no_input(result) -> list[tuple]:
    """Each `no-input` among a result's findings: its file, key and severity."""
    return [(i.file, i.key, i.severity) for i in result.issues if i.code == "no-input"]


def refused_for_no_input(study: str = "check", file: str = "studies/check.toml", key: str = "mesh"):
    """`study prep` of ``study``, planned: refused at its first step, `has-findings`, carrying its
    `no-input` at ``file`` and ``key``, its next step `project check`; nothing written."""
    with kit.refused(Refused, "has-findings") as caught:
        kit.planned("study.prep", project="laplace_square", study=study)
    assert ("no-input", file, key) in [(i.code, i.file, i.key) for i in caught.value.issues]
    assert [a.call.operation for a in caught.value.next] == ["project.check"]


def test_a_pass_through_for_a_component_that_declares_no_mesh_has_no_input_and_prep_writes_nothing(laplace):
    """Fails if a recipe naming the pass-through for a component whose contract declares no mesh is
    not one error, `no-input`, at the study's `mesh` before anything runs, whatever engine solves —
    or `study prep` is not refused for it at its first step, carrying it, with no machine record as
    with one, before
    anything is written (workflow.md §§ 2.2, 7; models.md § 5.1; the person's decision, 2026-11-27:
    "`no-input` is an error")."""
    name_mesher(laplace, "given")
    checked = kit.run("project.check", project="laplace_square")
    assert no_input(checked) == [("studies/check.toml", "mesh", "error")]
    assert {p.part: p.state for p in checked.parts}["study:check"] == "errors"
    refused_for_no_input()                                     # no machine record yet
    write_record("local", gmsh=FINGERPRINT)
    refused_for_no_input()                                     # and with one: the same answer
    assert not (laplace / "cases").exists() and not (laplace / "runs").exists()


def refused_for_the_engine(engine: str) -> Refused:
    """`study prep --engine` of the Laplace check, planned: refused, `has-findings`, carrying one error,
    `no-input`, at the study's `mesh`, naming the engine — nothing written."""
    with kit.refused(Refused, "has-findings", "study:check:mesh") as caught:
        kit.planned("study.prep", project="laplace_square", study="check", engine=engine)
    (found,) = [i for i in caught.value.issues if i.code == "no-input"]
    assert (found.file, found.key, found.severity) == ("studies/check.toml", "mesh", "error") and engine in found.message
    return caught.value


def test_an_engine_that_cannot_take_the_recipes_mesh_refuses_its_prep_and_no_file_is_wrong(laplace, here):
    """Fails if a recipe whose mesher writes what no hand-over gives an engine at the recipe's order
    — Gmsh's mesh at order 2, which NGSolve does not take yet — is a finding of `project check`,
    which names no engine, rather than refusing `study prep --engine ngsolve` before anything is
    written, the error at the study's `mesh`, its next steps the prep with each engine that can take
    it; or the prep with an engine that takes it — Elmer — is refused (workflow.md §§ 2.2, 7;
    models.md § 5.1; ADR 0025 decision 1)."""
    kit.rewrite(laplace / "mesh" / "uniform.toml", "order = 1", "order = 2")
    assert not no_input(kit.run("project.check", project="laplace_square"))
    refusal = refused_for_the_engine("ngsolve")
    assert [(a.call.operation, a.call.request.get("engine")) for a in refusal.next] == [("study.prep", "elmer")]
    assert not (laplace / "runs").exists() and not (laplace / "cases").exists()
    assert prepped(engine="elmer").ok()


def test_an_engine_is_checked_at_each_geometry_order_the_cases_have(laplace, here):
    """Fails if an engine no hand-over reads at a geometry order an axis gives the recipe is not
    refused — read at each case's order, not the recipe's as written alone: NGSolve takes Gmsh's
    mesh at order 1 only — or `study list` shows it among the engines that can solve the study
    (workflow.md § 2.2; models.md § 5.1)."""
    kit.rewrite(laplace / "studies" / "check.toml", '[axes."mesh:uniform:size"]',
                '[axes."mesh:uniform:order"]\nclass = "numerical convergence"\nvalues = [1, 2]\n\n'
                '[axes."mesh:uniform:size"]')
    assert not no_input(kit.run("project.check", project="laplace_square"))
    refused_for_the_engine("ngsolve")
    (row,) = kit.run("study.list", project="laplace_square").studies
    assert row.engines == ["elmer"]


def test_an_engine_no_definition_declares_is_refused_with_the_one_it_may_mean(laplace, here):
    """Fails if `study prep --engine` naming an engine no engine environment declares — a tool's,
    `gmsh`, or a slip, `elmr` — is not refused, `UsageError` · `no-such-engine`, before anything is
    written, its message naming the closest it may mean, its next steps the prep with each engine
    that can solve the study (workflow.md § 7)."""
    with kit.refused(UsageError, "no-such-engine") as caught:
        kit.planned("study.prep", project="laplace_square", study="check", engine="elmr")
    assert "`elmer`" in str(caught.value)
    assert sorted(a.call.request["engine"] for a in caught.value.next) == ["elmer", "ngsolve"]
    with kit.refused(UsageError, "no-such-engine"):
        kit.planned("study.prep", project="laplace_square", study="check", engine="gmsh")
    assert not (laplace / "cases").exists()


def test_the_pass_through_takes_the_scripts_mesh_and_the_hand_over_is_chosen_by_its_order(laplace, here):
    """Fails if a component that declares its own mesh, with the pass-through its recipe's mesher,
    does not give the study a mesh stage reading the geometry stage's mesh and groups — the
    geometry asked for the mesh — or the order the contract declares does not choose the hand-over:
    NGSolve at order 2 reads no MSH 2.2, so the NGSolve study's mesh has no input (workflow.md
    §§ 2.2, 2.3; geometry.md § 8)."""
    kit.rewrite(laplace / "components" / "square" / "component.toml", "[groups]",
                "[outputs]\nmesh = { order = 2 }\n\n[groups]")
    name_mesher(laplace, "given")
    result = flow()
    stages = by_kind(result)
    (geometry,) = stages["geometry"]
    assert {p.name for p in geometry.ports} == {"output", "groups", "mesh"}
    assert stages["mesh"] and all(m.type == "given" for m in stages["mesh"])
    assert {(w.source_port, w.type) for w in result.graph.wires} == {("mesh", "mesh/msh-2.2"),
                                                                     ("groups", "geometry/groups")}
    assert not no_input(result)


def test_while_an_error_stands_no_reader_offers_a_parts_next_step(laplace):
    """Fails if `project check`, `project graph`, `study list` or `case list` offers a part's next
    step — a study's prep — while an error stands anywhere in the project, here on a part the study
    does not use, so prep could still make its cases: the findings, in the chain's order, come
    first, the first error is the next step, and one filter keeps the parts' steps out of every
    reader; without an error, each offers them (projects.md § 8: "While any part has an error, no
    part's next step is offered"; models.md § 11.2; web.md § 8.4: "its first error in the chain's
    order, else the parts' next steps")."""
    readers = ("project.check", "study.list", "case.list", "project.graph")

    def offered() -> dict[str, list[str]]:
        steps = {name: [a.call.operation for a in kit.run(name, project="laplace_square").next]
                 for name in readers[:3]}
        graph = kit.run("project.graph", project="laplace_square").graph
        steps["project.graph"] = [a.call.operation for n in graph.nodes for a in n.actions]
        return steps

    assert offered() == dict.fromkeys(readers, ["study.prep"])      # the one study's
    (laplace / "physics" / "other.toml").write_text("kind = \n")          # an error on a part no study uses
    checked = kit.run("project.check", project="laplace_square")
    assert (checked.issues[0].severity, checked.issues[0].subject) == ("error", "physics:other")
    assert [(s.name, s.makes) for s in kit.run("study.list", project="laplace_square").studies] == [
        ("check", True)]
    assert offered() == dict.fromkeys(readers, [])
    assert not [b for b in checked.report.blocks if isinstance(b, view.Next)]


# ------------------------------------------------------------------ study prep (workflow.md §§ 5, 7)

def prepped(project: str = "laplace_square", study: str = "check", **more):
    return kit.apply("study.prep", project=project, study=study, **more)


def nexts(outcome) -> list[view.Action]:
    """The next steps an outcome's report gives."""
    return [a for b in outcome.report.blocks if isinstance(b, view.Next) for a in b.actions]


def test_study_prep_writes_the_cases_then_the_stages_then_the_jobs_in_its_steps_order(laplace, here):
    """Fails if `study prep` of a study with nothing written does not, in one command, write its
    cases, each stage its cases need and the jobs that make them — its plan's steps the cases'
    first, then the stages', then the jobs', each step's own deciding within what the ones before
    it fixed (workflow.md § 7: "Its steps run in this order, each deciding within what the ones
    before it fixed"; ADR 0022 decisions 1–2)."""
    _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check")
    order = [s.id.partition(":")[0] for s in plan.steps]
    assert order == sorted(order, key=["cases", "stages", "jobs"].index) and set(order) == {"cases", "stages", "jobs"}
    assert not (laplace / "cases").exists() and not (laplace / "runs").exists()
    outcome = prepped()
    assert outcome.ok() and len(outcome.added) == 3 and outcome.kept == [] and outcome.target == "local"
    assert len(list((laplace / "cases" / "check").iterdir())) == 3
    assert {r.state for r in outcome.stages} == {"to_prep", "waiting"} and len(sequences(outcome)) == 1


def test_study_prep_writes_each_stage_through_the_one_writer_from_its_templates(laplace, here):
    """Fails if a geometry stage's folder is not its request — the kind's program and check
    rendered from its listed context, `{python}` left the run's own, the person's script and
    inputs and contract documents its inputs, each document the file its kind names, femkit's
    check among its programs, one process, one rank with the job's cores as threads and no GPU,
    the queue, wall and memory of the study's meshing job — beside `stage.json`, what it is made from — the
    target's machine by its record's identity of the host, never the record's name, and nothing of an
    engine — whose SHA-256 is its ID; or the script is not handed each
    length in the frame's unit; or a mesh stage does not share the geometry it reads from the
    folder that made it (workflow.md §§ 2.1, 4, 5; geometry.md § 2; jobs.md §§ 1.1, 2)."""
    sweep_side(laplace)
    kit.rewrite(laplace / "components" / "square" / "component.toml", 'unit = "m"', 'unit = "cm"')
    outcome = prepped()
    assert outcome.ok()
    runs_ = laplace / "runs" / "check"
    geometries = sorted((runs_ / "geometry").iterdir())
    assert len(geometries) == 3
    g = geometries[0]
    made = made_of(g)
    assert persist.canonical_sha256(made) == g.name
    assert made["target"] == record.host_identity() and made["fingerprint"] == FINGERPRINT
    assert "check_geometry.py" in made["programs"]
    req = tomllib.loads((g / "job.toml").read_text())
    assert req["environment"] == "gmsh" and req["one_process"] is True
    assert req["command"] == ["{python}", "geometry.py", "inputs.json", "geometry.xao"]
    assert req["check"] == ["{python}", "check_geometry.py", "contract.json", "geometry.xao", "groups.json",
                            "checked.json", "outputs.json"]
    assert req["programs"] == ["check_geometry.py"]
    assert sorted(req["inputs"]) == ["contract.json", "geometry.py", "inputs.json"]
    assert req["outputs"] == ["geometry.xao", "groups.json"]
    assert req["resources"] == {"ranks": 1, "threads": 1, "gpus": 0, "wall": "00:05:00", "memory": "1G"}
    handed = [json.loads((g / "inputs.json").read_text()) for g in geometries]
    assert all(set(h) == {"schema", "definitions"} for h in handed)        # one name: never `parameters`
    sides = sorted(h["definitions"]["side"] for h in handed)
    assert sides == [100.0, 200.0, 300.0]                             # 1 m, 2 m and 3 m, in the frame's cm
    contract = json.loads((g / "contract.json").read_text())
    assert contract["groups"] == {"domain": 2, "left": 1, "right": 1, "sides": 1} and contract["brep"] is False
    (m,) = [p for p in (runs_ / "mesh").iterdir() if {t["id"] for t in made_of(p)["takes_from"].values()} == {g.name}]
    assert "serves" not in made_of(m) and made_of(m)["mesher"] == "gmsh"
    mreq = tomllib.loads((m / "job.toml").read_text())
    assert mreq["shares"] == [{"folder": f"../../geometry/{g.name}", "file": "geometry.xao"}]
    assert mreq["command"] == ["{python}", "mesh.py", "recipe.json", "{share:geometry.xao}", "mesh.msh", "regions.json"]
    assert mreq["programs"] == ["check_mesh.py", "mesh.py"]
    recipe = json.loads((m / "recipe.json").read_text())
    assert recipe["size"] == 10.0 and recipe["order"] == 1          # 0.1 m, in the frame's cm


def test_a_stages_identity_hashes_its_programs_and_the_modules_they_run_with_never_the_monitor(laplace, here):
    """Fails if what a stage is made from hashes the monitor beside its run — which watches it and
    makes nothing, so a monitor changed would make every stage anew — or leaves out a program its
    kind runs or a module those programs run with (workflow.md § 4: "the SHA-256 of each program its
    folder runs — the stage's program and check and the modules they run with, never the monitor
    that watches it")."""
    prepped()
    made = {made_of(f)["kind"]: sorted(made_of(f)["programs"]) for kind in ("geometry", "mesh")
            for f in (laplace / "runs" / "check" / kind).iterdir()}
    modules = ["documents.py", "process.py"]
    assert made == {"geometry": sorted(["check_geometry.py", *modules]),
                    "mesh": sorted(["check_mesh.py", "mesh.py", *modules])}, made


def test_stage_json_carries_its_shape_and_names_each_field_for_what_it_is(laplace, here):
    """Fails if a stage's `stage.json` does not carry `schema`, or loads by no model of femkit's, or
    holds a stage kind's name as a key, or one key meaning two things across the kinds — the mesh
    a geometry's script writes and the recipe a mesh is made by — or names what a mesh takes from
    otherwise than by the stage that writes each of its inputs (models.md § 2: "every file carries
    its shape"; workflow.md § 4)."""
    from femkit.definitions import catalogue
    from femkit.workflow import identity
    prepped()
    runs_ = laplace / "runs" / "check"
    kinds = set(catalogue.stages(kit.ctx()).kinds)
    (g, *_), (m, *_) = (sorted((runs_ / k).iterdir()) for k in ("geometry", "mesh"))
    for folder in (g, m):
        held = made_of(folder)
        assert held["schema"] == 3 and not set(held) & kinds and "mesh" not in held
        assert identity.read(kit.ctx(), folder).value.model_dump(mode="json", by_alias=True) == held
    geometry = made_of(g)
    taken = made_of(m)["takes_from"]
    assert taken and all(t["kind"] in kinds and (runs_ / t["kind"] / t["id"]).is_dir() for t in taken.values())
    assert geometry["takes_from"] == {}


def test_study_prep_writes_the_studys_meshing_job_named_by_the_study(laplace, here):
    """Fails if `study prep` does not leave, for the study, a batch of its geometries, a batch of its
    meshes and the sequence of the two in `runs/<study>/launch/`, each named by the kind's batch, or
    the sequence, and the study — never by an engine — holding the study's stages and prepared with
    that job, for the target, with the study's meshing resources and its `maker.json` naming `study
    prep` as what writes it again; or its plan does not name every folder it writes or prepares, so
    the runner holds each, nor carry each prepare's findings, planned in memory before anything is
    written; or its next step is not `job launch` of the sequence by its full path, alone (workflow.md
    §§ 5, 7: "the study's meshing job … `geometries-<s>-NNN/`, `meshes-<s>-NNN/` … and `mesh-<s>-NNN/`";
    "its next steps are the launch each job not launched yet … allows"; jobs.md §§ 1.2, 3)."""
    _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check")
    assert "fit" in {i.code for i in plan.issues}                                # job prepare's, in the plan
    outcome = prepped()
    launch = laplace / "runs" / "check" / "launch"
    assert sorted(p.name for p in launch.iterdir()) == [
        "geometries-check-001", "mesh-check-001", "meshes-check-001"]
    stages = [*(laplace / "runs" / "check" / "geometry").iterdir(),
              *(laplace / "runs" / "check" / "mesh").iterdir()]
    assert set(plan.subjects) == {kit.opened(laplace).project.subject,
                                  *(runs.subject(f) for f in [*stages, *launch.iterdir()])}
    seq = tomllib.loads((launch / "mesh-check-001" / "job.toml").read_text())
    assert seq["sequence"] == ["../geometries-check-001", "../meshes-check-001"]
    assert seq["resources"] == {"ranks": 1, "threads": 1, "gpus": 0, "wall": "00:05:00", "memory": "1G"}
    held = []
    for batch in ("geometries", "meshes"):
        folder = launch / f"{batch}-check-001"
        members = [folders.at(folder, m) for m in tomllib.loads((folder / "job.toml").read_text())["members"]]
        assert members and all(folders.at(m, folders.prepared(ctx(), m).value.launch) == folder for m in members)
        assert {run_state(m) for m in members} == {"in_launch"}
        held += members
    assert sorted(held) == sorted(stages)
    maker = folders.maker(ctx(), launch / "mesh-check-001").action
    assert maker.call.operation == "study.prep" and maker.call.request["study"] == "check"
    for name in ("mesh-check-001", "geometries-check-001", "meshes-check-001"):
        assert folders.prepared(ctx(), launch / name).reads
        assert run_state(launch / name) in ("in_launch", "prepared")
    assert "fit" in {i.code for i in outcome.issues}                               # job prepare's, carried
    assert [(a.call.operation, a.call.request["dir"], a.on) for a in nexts(outcome)] == [
        ("job.launch", str(launch / "mesh-check-001"), None)]


def test_a_meshing_job_in_a_grouping_folder_is_named_by_the_last_step_of_its_study(laplace, here):
    """Fails if a study whose name holds a grouping folder's step names its meshing job's launch
    folders otherwise than by the last step of its name — a launch folder's name is one step
    (projects.md § 5; workflow.md § 7)."""
    (laplace / "studies" / "sweeps").mkdir()
    (laplace / "studies" / "check.toml").rename(laplace / "studies" / "sweeps" / "gap.toml")
    kit.rewrite(laplace / "project.toml", '"check"', '"sweeps/gap"')
    prepped(study="sweeps/gap")
    assert sorted(p.name for p in (laplace / "runs" / "sweeps" / "gap" / "launch").iterdir()) == [
        "geometries-gap-001", "mesh-gap-001", "meshes-gap-001"]


def test_the_sequence_study_prep_writes_is_named_as_the_stage_kinds_declare_it(laplace, here, definitions):
    """Fails if the sequence `study prep` writes for a study is named otherwise than `stages.toml`
    declares it, beside each kind's batch (workflow.md § 7)."""
    kit.rewrite(definitions / "stages.toml", 'sequence = "mesh"', 'sequence = "making"')
    names = sorted(Path(s).name for s in sequences(prepped()))
    assert names == ["making-check-001"]


def test_the_preview_shows_every_value_case_stage_folder_and_fit_and_writes_nothing(laplace, here):
    """Fails if `study prep --dry-run`, the preview, does not show each case it writes with every
    value of its point, each stage with its state and what prep does to it, each job's folders and
    each job's fit — or writes anything (workflow.md § 7: "`--dry-run` is the preview: every value,
    every folder it would write, every job's fit"; ADR 0022 decision 3)."""
    _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check")
    said = plan.text()
    for size in ("0.1 m", "0.05 m", "0.025 m"):
        assert f"mesh:uniform:size = {size}" in said
    staged = [s.describe for s in plan.steps if s.id.startswith("stages:")]
    assert len(staged) == 4 and all(tasks()["place"] in s for s in staged)
    assert "geometries-check-001" in said and "mesh-check-001" in said
    assert [i for i in plan.issues if i.code == "fit"] and "cores" in said
    assert not (laplace / "cases").exists() and not (laplace / "runs").exists()


def test_preps_plan_carries_the_report_its_outcome_shows_every_value_stage_and_folder_used_and_left_included(
        laplace, here):
    """Fails if `study prep`'s plan — its preview: `--dry-run`, the page's Preview — does not carry the
    report its outcome would show, built by the outcome's own code: each case with every value of its
    point, each stage with what prep does to it and its folder — one it leaves to the job that has
    it too, for which the plan holds no step — and each job with its launch folders (workflow.md § 7:
    "the report its outcome would show — every value, every stage with what prep would do to it, used
    and left ones included, every folder it would write, every job's fit — carried by its plan";
    api.md § 3: `report`)."""
    op, plan, c = kit.planned("study.prep", project="laplace_square", study="check")
    outcome = op.apply(plan, c)
    foreseen, done = plan.report.blocks, [b for b in outcome.report.blocks if not isinstance(b, view.Next)]
    assert len(foreseen) == len(done) and foreseen[2:] == done[2:]          # its first line and cases: tenses apart
    assert [(r["id"], r["point"]) for r in foreseen[1].rows] == [(r["id"], r["point"]) for r in done[1].rows]
    cells = [row for b in plan.report.blocks if isinstance(b, view.Table) for row in b.rows]
    points = {row["point"] for row in cells if "point" in row}
    assert points == {f"mesh:uniform:size = {s}" for s in ("0.1 m", "0.05 m", "0.025 m")}
    staged = {row["stage"]: row for row in cells if "stage" in row}
    assert len(staged) == 4 and all(row["folder"] and tasks()["place"] in row["does"] for row in staged.values())
    jobs = [row for row in cells if "sequence" in row]
    assert sorted(Path(j["sequence"]).name for j in jobs) == ["mesh-check-001"]
    assert all("geometries-" in j["batches"] and "meshes-" in j["batches"] for j in jobs)
    _, again, _ = kit.planned("study.prep", project="laplace_square", study="check")
    left = {row["stage"]: row["does"] for b in again.report.blocks if isinstance(b, view.Table) for row in b.rows
            if "stage" in row}
    assert not [s for s in again.steps if s.id.startswith("stages:")]
    assert left.keys() == staged.keys() and all(tasks()["leave"] in d for d in left.values())


def test_the_preview_says_what_prep_is_to_write_never_that_it_was_written(laplace, here):
    """Fails if the outcome `study prep`'s plan foresees — its preview: `--dry-run`, the page's
    Preview — says that a case or a job was written before anything is: its first line and its
    cases' rows say what it is to write, and only the outcome of its apply says written (api.md
    § 2.3: `Outcome.status`, `planned`, the outcome a plan foresees; workflow.md § 7)."""
    op, plan, c = kit.planned("study.prep", project="laplace_square", study="check")
    head = text.report(plan.report).splitlines()[0]
    cases = [b for b in plan.report.blocks if isinstance(b, view.Table) and b.columns[0].key == "id"][0]
    assert "to write" in head and "written" not in head
    assert {row["written"] for row in cases.rows} == {"to write"}
    outcome = op.apply(plan, c)
    assert outcome.status == "done" and "written" in outcome.text().splitlines()[0]
    assert "to write" not in outcome.text()


def test_a_stage_in_a_job_not_launched_yet_reads_its_folders_state_and_a_second_prep_writes_nothing(laplace, here):
    """Fails if, after `study prep`, a stage prepared with a launch folder not launched yet — a mesh
    too, whatever the geometry it takes from — does not read its folder's state, `in_launch`,
    *needs update*, its next steps `job launch` of the sequence that makes it by its full path, then
    `job prepare` of its own folder, which takes it out of that job; or a second `study prep`
    plans a step or writes any file — a case, a stage, a second job — instead of leaving each stage
    to the job that makes it, its next steps the launch of each job the first prep wrote, by its
    full path (workflow.md §§ 6, 7: "a stage it uses or leaves is shown in its outcome's table";
    "`job launch` of each job not launched yet that holds the study's stages — one it wrote, or
    one a prep before it wrote"; jobs.md § 5.5)."""
    prepped()
    launch = laplace / "runs" / "check" / "launch"
    for n in flow().graph.nodes:
        assert (n.state, n.shows) == ("in_launch", "needs update")
        assert [(a.call.operation, a.call.request["dir"]) for a in n.actions] == [
            ("job.launch", str(launch / "mesh-check-001")), ("job.prepare", n.folder)]
    written = {**kit.tree(laplace / "runs"), **kit.tree(laplace / "cases")}
    _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check")
    assert plan.steps == () and plan.asks == ()
    again = prepped()
    assert {**kit.tree(laplace / "runs"), **kit.tree(laplace / "cases")} == written
    assert sequences(again) == [] and again.added == [] and len(again.kept) == 3
    assert {r.state for r in again.stages} == {"in_launch"} and all(r.does == ["leave"] for r in again.stages)
    assert [(a.call.operation, a.call.request["dir"]) for a in nexts(again) if a.call.operation == "job.launch"] == [
        ("job.launch", str(launch / "mesh-check-001"))]


def ran(folder: Path, status: int) -> Path:
    """A run of a stage's folder that ended with ``status``, launched from another machine — so its
    job's word is not asked — its records written through femkit's own models as its launch and its
    run script write them (jobs.md §§ 5.1, 5.2)."""
    run = folder / files().run_name(1)
    run.mkdir()
    now = "2026-01-01T00:00:00+00:00"
    job = runs.Job(host="h", pid=1, start=1, boot="b")
    for role, model in (("launched", runs.Launched(time=now, identity="elsewhere", job=job)),
                        ("started", runs.Started(time=now, host="h")),
                        ("ended", runs.Ended(status=status, time=now))):
        persist.write_json(run / files().name(role), model.model_dump(mode="json", by_alias=True))
    return run


def test_a_stage_with_runs_of_its_own_in_a_job_not_launched_yet_reads_in_launch_not_waiting(laplace, here):
    """Fails if a mesh whose earlier run failed, in a job not launched yet while the geometry it
    takes from has no finished run, reads `waiting` — its own rule computing what its folder's
    state already says, and differing from it — rather than its folder's `in_launch`, its next step
    `job launch` of the job that makes it (workflow.md § 6: "a stage already in a job not launched
    yet reads its folder's `in_launch` ... whatever it takes from"; jobs.md § 5.5: "whatever runs
    it made before")."""
    prepped()
    mesh = by_kind(flow())["mesh"][0]
    ran(Path(mesh.folder), 1)
    (now,) = [n for n in flow().graph.nodes if n.address == mesh.address]
    assert (now.state, now.shows) == ("in_launch", "needs update")
    sequence = laplace / "runs" / "check" / "launch" / "mesh-check-001"
    assert [(a.call.operation, a.call.request["dir"]) for a in now.actions][0] == ("job.launch", str(sequence))


#: The Laplace study's statement of its solve's resources, and of its meshing job's, as the template
#: writes them, to their wall (models.md § 5.1).
SOLVE_RESOURCES, MESHING = (
    (f'[{table}.resources]\n# MPI ranks\nranks = 1\n# threads per rank\nthreads = 1\n'
     '# GPUs per node, a count; 0 states that none is used\ngpus = 0\n'
     f'# wall time, `[D-]HH:MM:SS`; read on a machine with a scheduler\nwall = "{wall}"')
    for table, wall in (("solve", "00:10:00"), ("meshing", "00:05:00")))


def test_preps_meshing_job_and_each_stage_in_it_state_the_studys_meshing_never_its_solves_resources(laplace,
                                                                                                    here):
    """Fails if prep's meshing job for the study — each of its launch folders' requests — states other
    resources than the study's `[meshing.resources]`, or a stage inside it other than a stage inside
    that job states, the solve's resources asked in their place; or the solve's resources,
    `[solve.resources]`, changed alone, make prep state any request again or write anything, as if
    prep read them (workflow.md § 5: "a study's meshing … asking the resources the study states for
    it, `[meshing.resources]`"; "a stage inside a meshing job states the job's queue, wall and
    memory, one rank, the job's cores … as its threads, and no GPU"; models.md § 5.1; ADR 0022
    decision 10)."""
    study = laplace / "studies" / "check.toml"
    kit.rewrite(study, MESHING, MESHING.replace("threads = 1", "threads = 2"))
    prepped()
    launch = laplace / "runs" / "check" / "launch"
    stated = lambda folder: tomllib.loads((folder / files().name("request")).read_text())["resources"]
    meshing = {"ranks": 1, "threads": 2, "gpus": 0, "wall": "00:05:00", "memory": "1G"}
    for batch in ("geometries", "meshes", "mesh"):
        assert stated(launch / f"{batch}-check-001") == meshing
    stages = [Path(n.folder) for n in flow().graph.nodes]
    assert stages and all(stated(s) == meshing for s in stages)
    written = {**kit.tree(laplace / "runs"), **kit.tree(laplace / "cases")}
    kit.rewrite(study, SOLVE_RESOURCES, SOLVE_RESOURCES.replace("threads = 1", "threads = 8")
                .replace("00:10:00", "02:00:00"))
    _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check")
    assert plan.steps == ()
    prepped()
    assert {**kit.tree(laplace / "runs"), **kit.tree(laplace / "cases")} == written


def test_study_prep_states_a_stages_resources_again_when_the_studys_statement_of_its_job_changed(laplace, here):
    """Fails if `study prep`, putting in a job a stage whose request states other resources than its
    job's — the study's statement of its meshing job's resources changed since the stage
    was written — refuses `member-differs` instead of stating the job's resources again in the stage's
    request, the stage itself unchanged, and preparing it again with the new job, planned in
    memory with its restated request; or prep's plan and outcome do not say so by the stage
    table's own task, `restate`, in that table's sentence, how the resources change beside it
    (workflow.md § 5: "`study prep` states them again in each stage's request it puts in a job";
    § 6: "`restate` (its request's resources stated again, § 5) … each with its own sentence, which
    prep's plan and outcome say"; jobs.md §§ 1.1, `restate`, 3)."""
    prepped()
    folder = Path(by_kind(flow())["geometry"][0].folder)
    kit.apply("job.prepare", dir=str(folder))                   # taken out of its job: prepared apart
    made = made_of(folder)
    kit.rewrite(laplace / "studies" / "check.toml", MESHING,
                MESHING.replace("threads = 1", "threads = 2").replace("00:05:00", "00:20:00"))
    _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check")
    outcome = prepped()
    assert outcome.ok()
    (row,) = [r for r in outcome.stages if Path(next(n.folder for n in flow().graph.nodes if n.address == r.stage))
              == folder]
    assert (row.does, row.describe) == (["restate", "place"], [tasks()["restate"], tasks()["place"]])
    (step,) = [s for s in plan.steps if s.id == f"stages:{row.stage}"]
    assert ": " + ", ".join(row.describe) in step.describe and "threads 1 → 2" in step.describe
    request = tomllib.loads((folder / files().name("request")).read_text())
    assert request["resources"] == {"ranks": 1, "threads": 2, "gpus": 0, "wall": "00:20:00", "memory": "1G"}
    assert made_of(folder) == made and folder.name == persist.canonical_sha256(made)
    batch = laplace / "runs" / "check" / "launch" / "geometries-check-002"
    assert folders.at(folder, folders.prepared(ctx(), folder).value.launch) == batch
    assert run_state(folder) == "in_launch"


def run_state(folder: Path) -> str:
    """A calculation folder's state, as `job status` says it."""
    return kit.run("job.status", dir=str(folder)).state


def test_a_tables_headings_are_the_persons_words_never_a_fields_key_that_reads_worse(laplace, here):
    """Fails if a table heading the command line prints is a field's key where a person calls it
    otherwise — `id` for a case, `made` for whether its study makes it now, `found` for where its
    material is found now, `changed` for how its data changed since, `name` for a study and `why`
    for why not, `address` for a node and `issues` for its findings, `source`, `target` and
    `address` for a wire's ends and the value that names it — rather than the `title` its field
    declares (web.md § 7.5: "each column's label the field's short name — the `title` its
    declaration gives, else its key"; docs/README.md M1: no internal name of femkit's)."""
    def headings(report: view.Report) -> list[list[str]]:
        return [[c.label for c in b.columns] for b in report.blocks if isinstance(b, view.Table)]

    assert headings(kit.run("study.list", project="laplace_square").report) == [
        ["study", "prep can make its cases", "cases", "engines that can solve it", "why not"]]
    assert headings(kit.planned("study.prep", project="laplace_square", study="check")[1].report)[0] == [
        "case", "point", "written"]
    prepped()
    assert headings(kit.run("case.list", project="laplace_square").report) == [
        ["case", "point", "made now"], ["case", "stage", "target", "state"],
        ["case", "body", "material", "found now", "property", "dataset", "source", "changed since"]]
    nodes, wires = text.drawn(kit.run("project.graph", project="laplace_square").graph)
    assert ([c.label for c in nodes.columns][0], [c.label for c in nodes.columns][-1]) == ("node", "findings")
    assert [c.label for c in wires.columns] == ["from", "to", "to port", "written at"]


def test_case_list_names_each_cases_stages_and_prep_for_another_machine_says_its_launch_from_the_project(laplace,
                                                                                                         here):
    """Fails if `case list` does not name each case's geometry and mesh, with its state and the
    machine it was made for, by its record's identity of the host, found by their
    `stage.json` — so those made for another machine's record are named too, never by forming an ID
    from this machine's facts; or `study prep` for another machine's target does not offer the
    launch of its job alone, carrying the machine it runs on, its folder by its path from the
    project's folder (workflow.md §§ 4, 7: "the target's machine, by its record's identity of the
    host, never the record's name"; "a step of an operation that acts on the machine it runs on …
    carries that machine (`Action.on`): a line for that machine, its `path` fields from the
    project's folder"; "its next steps are the launch each job not launched yet … allows"; web.md
    § 7.2; jobs.md § 1; models.md § 11.1)."""
    write_record("other", identity="elsewhere", gmsh=FINGERPRINT)
    outcome = prepped(target="other")
    assert [(a.call.operation, a.call.request, a.on) for a in nexts(outcome)] == [
        ("job.launch", {"dir": "runs/check/launch/mesh-check-001"}, "other")]
    listed = {s.name: s for s in kit.run("case.list", project="laplace_square").studies}["check"].written
    assert len(listed) == 3
    for w in listed:
        assert sorted(s.stage.split("/")[-2] for s in w.stages) == ["geometry", "mesh"]
        assert {(s.target, s.state, s.shows) for s in w.stages} == {("elsewhere", "in_launch", "needs update")}
    assert len({s.stage for w in listed for s in w.stages if s.stage.split("/")[-2] == "geometry"}) == 1


def test_a_job_study_prep_wrote_launched_here_runs_to_its_end_each_study_its_own(laplace, tmp_path, tripwire_dir):
    """Fails if, on a machine of stand-ins, `study prep` of two studies does not leave each its own
    job prepared, or the first, launched here and waited on, is refused — a stage prepared with the
    other study's job — or does not run to its end, every stage of it read in a state its runs ended
    in, the other study's stages untouched (workflow.md §§ 4, 5, 7: each stage its study's, so two
    studies' jobs share nothing; jobs.md §§ 1.2, 5; ADR 0022 decision 9: "Launch sends what prep
    wrote"). The basic tier has no `gmsh` environment: the stand-in's python holds no Gmsh, so each
    geometry run ends `failed` at the script's `import gmsh` and the meshes taking from it are left
    out — what this holds is the job's walk, not a stage's work, which the engine tier's runs
    hold."""
    root = kit.stand_in_machine(tmp_path, tripwire_dir, {"gmsh": {}})
    write_record("local", root=str(root), manager=os.environ["FEMKIT_ENV_MANAGER"], gmsh=FINGERPRINT)
    a_second_study(laplace)
    (first,), (second,) = (map(Path, sequences(prepped(study=s))) for s in ("check", "second"))
    assert folders.prepared(ctx(), first).reads and folders.prepared(ctx(), second).reads
    launched = kit.apply("job.launch", dir=str(first), foreground=True)
    assert launched.status == "done" and launched.how == "waited on" and launched.closed
    mine = flow().graph.nodes
    assert {(n.kind, n.state) for n in mine} == {("geometry", "failed"), ("mesh", "waiting")}
    (geometry,) = [n for n in mine if n.kind == "geometry"]
    (run,) = runs.runs(ctx(), Path(geometry.folder))
    assert "No module named 'gmsh'" in (run / files().name("log")).read_text()
    assert {n.state for n in flow(study="second").graph.nodes} == {"in_launch"}
    assert folders.prepared(ctx(), second).reads


def finish(folder: Path, sequence: Path) -> Path:
    """A stage's run that finished in the job of ``sequence``, its records written through femkit's
    own models as the launch, its run script and its check write them — launched from another
    machine, so its job's word is not asked — each output its request lists left beside them
    (jobs.md §§ 5.1, 5.2)."""
    run = folder / files().run_name(1)
    run.mkdir()
    req = runs.request_of(ctx(), folder)
    (run / files().name("request")).write_bytes((folder / files().name("request")).read_bytes())
    for output in req.outputs:
        (run / output).write_text(output)
    now = "2026-01-01T00:00:00+00:00"
    job = runs.Job(host="h", pid=1, start=1, boot="b")
    persist.write_json(sequence / files().name("launch_record"), folders.LaunchRecord(
        time=now, identity="elsewhere", job=job, listed=[]).model_dump(mode="json"))
    for role, model in (("launched", runs.Launched(time=now, identity="elsewhere", job=job)),
                        ("started", runs.Started(time=now, host="h")),
                        ("ended", runs.Ended(status=0, time=now)),
                        ("checked", runs.Checked.model_validate({"schema": 1, "passed": True})),
                        ("outputs", runs.Outputs.model_validate({"schema": 1, "files": {
                            o: persist.sha256(run / o) for o in req.outputs}}))):
        persist.write_json(run / files().name(role), model.model_dump(mode="json", by_alias=True))
    return run


def outputs(result, stage: str | None = None) -> dict[tuple[str, str], view.GraphPort]:
    """Each output port of the graph's stages — of ``stage`` alone, given one — by its stage's
    address and its name."""
    return {(n.address, p.name): p for n in result.graph.nodes if stage in (None, n.address) for p in n.ports
            if p.side == "out"}


def cases(result) -> list[view.Box]:
    """The graph's case boxes."""
    return [b for b in result.graph.boxes if b.kind == "case"]


def test_study_flow_shows_a_finished_stages_outputs_and_the_lines_that_open_them(laplace, here):
    """Fails if `study flow` does not show, on each output port of a stage whose newest run finished,
    its file in that run with, for a type opened in an environment, one shell line entering that
    environment on the target as its record says, then opening the file, and for one femkit opens
    no way, the file alone; or shows a file of a stage not finished (workflow.md § 8; § 2.2; web.md
    § 7.6: "for a stage's output, `file`, its path in its newest finished run, and `actions`, the
    lines that open it")."""
    outcome = prepped()
    (geometry,) = by_kind(flow())["geometry"]
    run = finish(Path(geometry.folder), Path(sequences(outcome)[0]))
    result = flow()
    assert {n.state for n in by_kind(result)["geometry"]} == {"finished"}
    shown = outputs(result, geometry.address)
    xao, groups = shown[(geometry.address, "output")], shown[(geometry.address, "groups")]
    assert (xao.accepts, groups.accepts) == (["geometry/xao"], ["geometry/groups"])
    assert (xao.file, groups.file) == (str(run / "geometry.xao"), str(run / "groups.json"))
    assert [a.shell for a in xao.actions] == [
        'eval "$(/x/bin/conda shell.bash hook)" && conda activate femkit-gmsh && gmsh ' + str(run / "geometry.xao")]
    assert groups.actions == []
    assert all(p.file is None and not p.actions for (stage, _), p in outputs(result).items()
               if stage != geometry.address)
    assert "outputs" not in type(result).model_fields


def test_the_line_that_opens_an_output_enters_by_the_machines_preamble_then_its_activation(laplace, here):
    """Fails if the line that opens a finished stage's output enters its environment otherwise than
    a run script does — the target's preamble, verbatim, then its activation of the environment by its
    name with the manager —
    leaving the preamble out (jobs.md § 4, block 8; workflow.md § 8: "a `shell` action carrying
    that environment's entry lines")."""
    kit.apply("config.set", key="activation.preamble", value='["module load y"]')
    write_record("local", gmsh=FINGERPRINT)
    outcome = prepped()
    (geometry,) = by_kind(flow())["geometry"]
    run = finish(Path(geometry.folder), Path(sequences(outcome)[0]))
    (line,) = outputs(flow(), geometry.address)[(geometry.address, "output")].actions
    assert line.shell == ('module load y && eval "$(/x/bin/conda shell.bash hook)" && conda activate femkit-gmsh && '
                          f"gmsh {run / 'geometry.xao'}")


def test_what_prep_does_past_a_stages_own_states_is_its_tables(laplace, here, definitions):
    """Fails if what `study prep` does to a stage past its own states is not what `stage.toml`
    declares for its folder's state: a finished stage used, never made again, as shipped, with no
    step in the plan; put in a job once the table gives `finished` `place` — but a priority chain
    in code, or a reading of the folder's actions (workflow.md § 6: "The table's `[does]` gives, for
    each of its own states and each state of its folder's — every one named — the tasks prep does
    there"; core.md § 7)."""
    outcome = prepped()
    (geometry,) = by_kind(flow())["geometry"]
    finish(Path(geometry.folder), Path(sequences(outcome)[0]))

    def done() -> tuple[list[str], list[str], list[str]]:
        """What prep does to the geometry, in the stage table's words, and its plan's steps of it."""
        _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check")
        (row,) = [r for r in prepped().stages if r.stage == geometry.address]
        return row.does, row.describe, [s.id for s in plan.steps if geometry.address in s.id]

    assert done() == (["use"], [tasks()["use"]], [])
    table = definitions / "states" / "stage.toml"
    kit.rewrite(table, 'finished = ["use"]', 'finished = ["place"]')
    does, describe, _ = done()
    assert (does, describe) == (["place"], [tasks()["place"]])


def test_where_prep_does_a_task_is_its_guard_in_the_stage_table(laplace, here, definitions):
    """Fails if where `study prep` does a task to a stage is decided by code rather than by the
    task's guard in `stage.toml`, over the stage's facts: a stage waiting on one this prep places
    in no job is written and prepared and not placed, as shipped — and placed once the table's
    `place` has no guard (workflow.md § 6: "a task's guard, its `when` over the stage's facts, says
    where it is done — `write` where it has no folder, … `place` unless it waits on a stage this
    prep places in no job … and code decides nothing the table does not say"; core.md § 7)."""
    prepped()
    kit.rewrite(laplace / "mesh" / "uniform.toml", *TOLERANCE)

    def meshes() -> set[str]:
        """What prep's plan says it does to each mesh, in the stage table's sentences."""
        steps = kit.planned("study.prep", project="laplace_square", study="check")[1].steps
        return {s.describe.split(": ", 1)[1] for s in steps if s.describe.startswith("mesh ")}

    said = tasks()
    assert meshes() == {f"{said['write']}, {said['prepare']}"}
    kit.rewrite(definitions / "states" / "stage.toml", 'when = "not held_back"\n', "")
    assert meshes() == {f"{said['write']}, {said['prepare']}, {said['place']}"}


# ------------------------------------------------------------------ prep run again (workflow.md §§ 5–7)

TOLERANCE = ("tolerance = 1e-9", "tolerance = 1e-8")


def running(folder: Path) -> Path:
    """A run of ``folder`` that has started and says nothing of its end, launched from another
    machine — so its job's word is not asked — its records written through femkit's own models as
    its launch and its run script write them (jobs.md §§ 5.1, 5.2)."""
    run = folder / files().run_name(1)
    run.mkdir()
    now = "2026-01-01T00:00:00+00:00"
    job = runs.Job(host="h", pid=1, start=1, boot="b")
    for role, model in (("launched", runs.Launched(time=now, identity="elsewhere", job=job)),
                        ("started", runs.Started(time=now, host="h"))):
        persist.write_json(run / files().name(role), model.model_dump(mode="json", by_alias=True))
    return run


def in_launch(folder: Path) -> Path | None:
    """The launch folder a stage's folder goes in, not launched yet; None for one in none
    (jobs.md § 5.5)."""
    return folders.facts(ctx(), folder).launch


@pytest.mark.parametrize("source", ["in a job not launched yet", "running"])
def test_a_waiting_stage_whose_source_another_job_has_is_written_prepared_and_left_waiting(laplace, here, source):
    """Fails if a stage whose source another job has — in a job not launched yet, or running — is
    placed in a job of its own by a later prep, which would run it before its source is made,
    rather than written and prepared as its state allows and left waiting, so a later prep places
    it; and prep's next steps the launch of the job that has the source (workflow.md § 6: "places
    it in a job only behind the stage it takes from, where this prep places that one in the same
    job — otherwise it waits, and a later prep places it"; § 7)."""
    first = prepped()
    launch = laplace / "runs" / "check" / "launch"
    if source == "running":
        for g in by_kind(flow())["geometry"]:
            kit.apply("job.prepare", dir=g.folder)                # taken out of its job, and run apart
            running(Path(g.folder))
    before = sorted(p.name for p in launch.iterdir())
    kit.rewrite(laplace / "mesh" / "uniform.toml", *TOLERANCE)
    again = prepped()
    assert again.ok() and sorted(p.name for p in launch.iterdir()) == before and sequences(again) == []
    meshes = [r for r in again.stages if r.stage.split("/")[-2] == "mesh"]
    assert len(meshes) == 3 and {(r.state, tuple(r.does)) for r in meshes} == {("waiting", ("write", "prepare"))}
    for r in meshes:
        folder = Path(next(n.folder for n in flow().graph.nodes if n.address == r.stage))
        assert run_state(folder) == "prepared" and in_launch(folder) is None
    assert {n.state for n in flow().graph.nodes if n.kind == "mesh"} == {"waiting"}
    if source == "running":                            # no job not launched yet holds a stage of the study
        assert [a.call.operation for a in nexts(again)] == ["study.flow"]
    else:
        assert [(a.call.operation, a.call.request["dir"]) for a in nexts(again)] == [
            ("job.launch", s) for s in sequences(first)]


def test_prep_states_a_job_not_launched_yet_again_when_the_studys_meshing_resources_changed(laplace, here):
    """Fails if, the study's meshing resources changed while its job is not launched yet, a second
    prep leaves that job's launch folders and members stating the old ones — so `job prepare` would
    be needed by hand, or the job would run with what the study no longer states — rather than
    stating each again and preparing the job again, its plan step naming the job and how they
    differ, and each stage in it, left to that job, its request stated again by a step of its own;
    or it touches another study's job, which shares nothing with it (workflow.md § 5: "in a job not
    launched yet whose launch folders state other resources than the study now does — each launch
    folder's request and each member's, then the job prepared again — so a job launched runs with
    what the study states"; § 6: "a stage `in_launch` whose job is restated reads `leave,
    restate`"; § 7: "Its plan holds a step for each thing it writes"; jobs.md §§ 1.1, 1.2)."""
    a_second_study(laplace)
    prepped()
    prepped(study="second")
    launch = laplace / "runs" / "check" / "launch"
    theirs = kit.tree(laplace / "runs" / "second")
    kit.rewrite(laplace / "studies" / "check.toml", MESHING,
                MESHING.replace("threads = 1", "threads = 2").replace("00:05:00", "00:20:00"))
    _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check")
    (step,) = [s for s in plan.steps if s.id.startswith("jobs:")]
    assert "mesh-check-001" in step.describe and "00:05:00 → 00:20:00" in step.describe
    mine = {n.address for n in flow().graph.nodes}
    assert {s.id.removeprefix("stages:") for s in plan.steps if not s.id.startswith("jobs:")} == mine
    outcome = prepped()
    rows = {r.stage: r for r in outcome.stages}
    assert outcome.ok() and {tuple(rows[a].does) for a in mine} == {("leave", "restate")}
    stated = lambda folder: tomllib.loads((folder / files().name("request")).read_text())["resources"]
    assert sorted(p.name for p in launch.iterdir()) == [
        "geometries-check-001", "mesh-check-001", "meshes-check-001"]
    for name in ("geometries-check-001", "meshes-check-001", "mesh-check-001"):
        assert stated(launch / name) == {"ranks": 1, "threads": 2, "gpus": 0, "wall": "00:20:00", "memory": "1G"}
        assert run_state(launch / name) in ("prepared", "in_launch")
    for n in flow().graph.nodes:
        assert stated(Path(n.folder)) == {"ranks": 1, "threads": 2, "gpus": 0, "wall": "00:20:00", "memory": "1G"}
        assert (n.state, in_launch(Path(n.folder))) == ("in_launch", launch / "mesh-check-001")
    assert kit.tree(laplace / "runs" / "second") == theirs


def test_a_text_changed_between_preps_plan_and_its_apply_refuses_the_apply_as_stale(laplace, here):
    """Fails if a study's meshing resources edited between prep's plan and its apply — between the
    page's Preview and Prep — are not refused as stale, `PlanStale`, before anything is written: its
    basis covers every text it would write (workflow.md § 7: "Its basis covers every text it would
    write, so a file changed between its plan and its apply … refuses the apply as stale"; api.md
    § 3)."""
    op, plan, c = kit.planned("study.prep", project="laplace_square", study="check")
    kit.rewrite(laplace / "studies" / "check.toml", MESHING, MESHING.replace("00:05:00", "00:20:00"))
    with kit.refused(PlanStale, "basis-changed"):
        op.apply(plan, c)
    assert not (laplace / "cases").exists() and not (laplace / "runs").exists()


def test_preps_outcome_names_its_machine_first_and_offers_the_launch_of_each_job_holding_its_stages(
        laplace, here):
    """Fails if `study prep`'s outcome does not name the machine it prepped for first, or its next
    steps are not, for each job not launched yet that holds the study's stages — one it wrote, or
    one a prep before it wrote — the launch that launch folder's state allows, alone, as its table
    gives it, by its full path — never `job prepare` beside it, nor a `job launch` composed apart
    from the table; or, with no such job, `study flow`; or the sentence heading them is decided by
    the report from their operations rather than held by the outcome (workflow.md § 7: "Its outcome
    names the machine it prepped for first, and its next steps are the launch each job not launched
    yet that holds the study's stages allows … read from that launch folder's state"; "With no such
    job, `study flow`"; api.md § 2.3: "`report()` builds only from fields of the model; it decides
    nothing")."""
    def launch(sequence: str) -> list[tuple[str, str, str]]:
        c = ctx()
        f, state = folders.observe(c, Path(sequence))
        return [(a.label, a.call.operation, a.call.request["dir"]) for a in folders.next_steps(c, state, f)
                if a.call.operation == "job.launch"]

    first = prepped()
    held = [step for s in sequences(first) for step in launch(s)]
    assert len(held) == len(sequences(first)) == 1
    assert [(a.label, a.call.operation, a.call.request["dir"]) for a in first.next] == held
    head, *_ = first.report.blocks
    assert head.text.startswith(f"for {first.target}") and first.target == "local"
    (block,) = [b for b in first.report.blocks if isinstance(b, view.Next)]
    assert block.label == first.heading and block.actions == first.next
    assert [(a.label, a.call.operation, a.call.request["dir"]) for a in prepped().next] == held
    (sequence,) = sequences(first)
    for n in flow().graph.nodes:
        finish(Path(n.folder), Path(sequence))
    last = prepped()
    assert {tuple(r.does) for r in last.stages} == {("use",)} and sequences(last) == []
    assert [a.call.operation for a in last.next] == ["study.flow"] and last.heading != first.heading


def test_study_flow_for_another_machine_says_a_launch_as_a_line_for_that_machine_and_a_prepare_as_its_own(
        laplace, here):
    """Fails if `study flow` for another machine's target offers `job launch` of the job a stage
    goes in — an operation that acts on the machine it runs on — without that machine, or by its
    full path here, rather than as a line for that machine, the folder by its path from the
    project's folder; or offers `job prepare` of a stage's folder — run here for any target — as a
    line for that machine rather than as the operation this machine runs, by its full path
    (workflow.md § 7: "a step of an operation that acts on the machine it runs on … carries that
    machine (`Action.on`): a line for that machine, its `path` fields from the project's folder";
    "`study prep`, `study flow` and `job prepare` run here for any target, and stay operations";
    api.md § 2.2, the verb; web.md § 7.2; jobs.md § 1)."""
    write_record("other", identity="elsewhere", gmsh=FINGERPRINT)
    prepped(target="other")
    result = flow(target="other")
    for n in result.graph.nodes:
        assert [(a.call.operation, a.call.request, a.on) for a in n.actions] == [
            ("job.launch", {"dir": "runs/check/launch/mesh-check-001"}, "other"),
            ("job.prepare", {"dir": n.folder}, None)]
    assert result.next and {(a.call.operation, a.on) for a in result.next} == {("job.launch", "other"),
                                                                               ("job.prepare", None)}
    lines = result.text().splitlines()
    shown = lines[lines.index(next(line for line in lines if line.startswith("next -- "))) + 1:]
    launches = [line for line in shown if line.strip().startswith("femkit job launch ")]
    assert launches and all(str(laplace) not in line for line in launches)


def test_study_flow_for_another_machine_offers_study_prep_as_an_operation_run_here(laplace, here):
    """Fails if, before any prep, `study flow --target <other>` offers `study prep … --target
    <other>` as a line for that machine, carrying it (`Action.on`), rather than as the operation
    this machine runs for that target: only a step of an operation that acts on the machine it runs
    on, as its verb declares it, carries that machine (workflow.md § 7: "`study prep`, `study flow`
    and `job prepare` run here for any target, and stay operations"; api.md § 2.2, the verb;
    web.md § 7.2)."""
    write_record("other", identity="elsewhere", gmsh=FINGERPRINT)
    result = flow(target="other")
    assert result.graph.nodes and {(a.call.operation, a.call.request.get("target"), a.on)
                                   for n in result.graph.nodes for a in n.actions} == {("study.prep", "other", None)}
    assert [(a.call.operation, a.on) for a in result.next] == [("study.prep", None)]


def test_preps_launch_step_says_where_and_how_it_runs(laplace, here):
    """Fails if `study prep`'s launch step does not say where and how it runs — on this machine, in
    the background — or, for another machine's target, says this machine rather than carrying the
    machine it runs on (workflow.md § 7: "the launch step says where and how it runs ("on this
    machine, in the background")"; web.md § 7.2)."""
    here_ = prepped()
    assert here_.next and {(a.call.operation, a.on, a.note) for a in here_.next} == {
        ("job.launch", None, "on this machine, in the background")}
    write_record("other", identity="elsewhere", gmsh=FINGERPRINT)
    there = prepped(target="other")
    assert there.next and all(a.call.operation == "job.launch" and a.on == "other" for a in there.next)
    assert all("in the background" in str(a) and "on this machine" not in str(a) for a in there.next)


def test_a_target_naming_no_record_is_refused_and_writes_nothing(laplace, here):
    """Fails if `--target` naming no record there is — the person's slip — is taken for a machine
    whose record is missing, so prep writes the cases and waits, rather than refusing it,
    `UsageError` · `no-record`, before anything is written (workflow.md § 7: "a `--target` naming
    no record is the person's slip, a `UsageError`, and writes nothing"; core.md § 9: refusals told
    apart by kind and code together)."""
    with kit.refused(UsageError, "no-record", "--target"):
        prepped(target="nowhere")
    assert not (laplace / "cases").exists() and not (laplace / "runs").exists()


def test_what_writes_this_machines_record_is_said_from_one_source_config_init_first(laplace, tmp_path):
    """Fails if, while a key of the activation the person states is unset and this machine has no
    record, prep's waiting outcome does not name `config init` first — the probe is refused until
    then — as the one step that asks for what is unset in words, never an example of it or a step
    for each of its alternatives; or names other steps than `doctor`'s row of the record does
    (workflow.md § 7: "A step that needs a value only the person knows … is the command that asks
    for it in words (`config init`)"; "`config init` first while a key the person states is unset
    — the one source `doctor`'s row reads too"; envs.md § 6.1)."""
    kit.apply("config.init", no_preamble=True, mpi=["mpirun", "-np", "{ranks}"],
              cuda_architectures=["80"])
    outcome = prepped()
    (waiting,) = [i for i in outcome.issues if i.code == "no-record"]
    first, *_ = waiting.next
    assert (first.call.operation, first.call.request, first.fills) == ("config.init", {}, [])
    assert [a.call.operation for a in waiting.next] == ["config.init", "job.probe"]
    (row,) = [r for r in kit.run("doctor").rows if r.subject == "this machine's record"]
    assert [a.command for a in waiting.next] == [a.command for a in row.next]


class Cut(Exception):
    """A prep cut short."""


class CutAfter(SilentObserver):
    """An observer that cuts prep's apply short after its ``n``-th step."""

    def __init__(self, n: int) -> None:
        self.n, self.done = n, 0

    def step_end(self, step, outcome, log) -> None:
        self.done += 1
        if self.done == self.n:
            raise Cut(step.id)


def completed(project: Path) -> None:
    """``project``'s study prepped whole: every stage of it in a job not launched yet, its one meshing
    job, none stale nor in none (workflow.md § 6; ADR 0022: "a prep cut short leaves a project a
    second prep completes")."""
    outcome = prepped(project.name)
    assert outcome.ok() and len(list((project / "cases" / "check").iterdir())) == 3
    held: set = set()
    for n in flow(project.name).graph.nodes:
        assert n.state == "in_launch", (n.address, n.state)
        held.add(in_launch(Path(n.folder)))
    assert len(held) == 1
    assert {str(h) for h in held} == {a.call.request["dir"] for a in nexts(outcome) if a.call.operation == "job.launch"}


def test_a_prep_cut_short_after_any_of_its_steps_is_completed_by_a_second_prep(tmp_path, here):
    """Fails if a prep cut short after any one of its plan's steps leaves a project a second prep
    does not complete — a stage left in no job, stale, or in a job of its own beside its study's — so
    the person would have to mend it by hand (ADR 0022: "a prep cut short leaves
    a project a second prep completes … A test cuts prep after each of its steps and checks that a
    second prep completes it"; workflow.md § 6; jobs.md § 5.5)."""
    root = tmp_path / "projects"
    _, plan, _ = kit.planned("study.prep", project=kit.copy_template(root, "laplace_square", "whole").name,
                             study="check")
    for n in range(1, len(plan.steps)):
        project = kit.copy_template(root, "laplace_square", f"cut{n}")
        op, planned, c = kit.planned("study.prep", project=project.name, study="check")
        with pytest.raises(Cut):
            op.apply(planned, c, CutAfter(n))
        completed(project)


class Blocking(SilentObserver):
    """An observer that, as a job's step starts, puts a file where the job's sequence goes: the
    sequence's write fails after its batches were written."""

    def __init__(self, sequence: Path) -> None:
        self.sequence = sequence

    def step_start(self, step, index, total) -> None:
        if step.id.startswith("jobs:"):
            self.sequence.parent.mkdir(parents=True, exist_ok=True)
            self.sequence.write_text("")


def test_a_member_of_a_launch_folder_whose_sequence_is_missing_goes_in_no_job_and_prep_places_it(laplace, here):
    """Fails if a stage prepared with a batch whose sequence is missing — a prep cut short between
    the two — reads as going in that batch, `in_launch`, rather than in none, so a second prep
    places it in a whole job of its study (jobs.md § 5.5: "one whose launch folder is not there, a
    prep cut short, is placed again"; workflow.md § 6)."""
    sequence = laplace / "runs" / "check" / "launch" / "mesh-check-001"
    op, plan, c = kit.planned("study.prep", project="laplace_square", study="check")
    with pytest.raises(FileExistsError):
        op.apply(plan, c, Blocking(sequence))
    sequence.unlink()
    batch = laplace / "runs" / "check" / "launch" / "geometries-check-001"
    assert batch.is_dir()
    (geometry,) = by_kind(flow())["geometry"]
    assert run_state(Path(geometry.folder)) == "prepared" and in_launch(Path(geometry.folder)) is None
    completed(laplace)


def test_a_job_whose_member_was_prepared_apart_reads_regrouped_and_prep_places_all_it_held_in_a_new_one(laplace,
                                                                                                      here):
    """Fails if, once `job prepare` took one stage out of the job prep wrote, that job — its
    sequence and the batch the stage was taken from — does not read `regrouped`, *needs update*,
    allowing only the action its `maker.json` names, its launch refused `prepared-apart` naming
    that stage before the job goes; or a stage it still names reads `in_launch` of it; or a second
    prep does not place every stage that job held in one new job of its study, leaving the
    old one `regrouped`, never offered among prep's or `study flow`'s next steps (jobs.md § 5.5,
    rows 5–6: "`regrouped` … the action its `maker.json` names … `job launch` refuses it
    `prepared-apart`"; "one whose launch folder is not there or not whole … is in no job, and placed
    again"; workflow.md §§ 6, 7)."""
    prepped()
    launch = laplace / "runs" / "check" / "launch"
    old, batch = launch / "mesh-check-001", launch / "geometries-check-001"
    held = [Path(n.folder) for n in flow().graph.nodes]
    (geometry,) = by_kind(flow())["geometry"]
    kit.apply("job.prepare", dir=geometry.folder)                 # taken out of its job: prepared apart
    c = ctx()
    m = folders.machine(c)
    for folder in (old, batch):
        f, state = folders.observe(c, folder)
        assert (state.value, m.word(state)) == ("regrouped", "needs update")
        assert [(a.call.operation, a.call.request["study"]) for a in folders.next_steps(c, state, f)] == [
            ("study.prep", "check")]
    assert all(in_launch(f) is None for f in held)
    with kit.refused(Refused, "prepared-apart", geometry.folder):
        kit.apply("job.launch", dir=str(old))
    assert not runs.runs(ctx(), Path(geometry.folder)) and not (old / files().name("launch_record")).exists()
    again = prepped()
    new = launch / "mesh-check-002"
    assert sequences(again) == [str(new)]
    assert {in_launch(f) for f in held} == {new}
    assert {run_state(launch / f"{n}-check-001") for n in ("mesh", "geometries", "meshes")} == {"regrouped"}
    assert all(str(launch / f"{n}-check-001") not in a.command for a in nexts(again)
               for n in ("mesh", "geometries", "meshes"))
    assert all(str(old) not in a.command for n in flow().graph.nodes for a in n.actions)


def test_prep_for_a_target_whose_scheduler_cannot_take_a_job_yet_offers_no_launch_and_says_why(laplace, here):
    """Fails if `study prep` for a target with a scheduler — whose submission is not built — offers
    the launch of a job it wrote among its next steps, which the target cannot make, rather than
    what else the job's state allows, with a finding saying a launch cannot submit (workflow.md § 7:
    "never a launch the target cannot make: while submitting through a scheduler is not built …
    a target with one is offered no launch, and its finding says so"; jobs.md § 5)."""
    config = settings.load(kit.ctx(), fresh=True).config
    record.write(record.path("cluster"), kit.a_record(
        identity="elsewhere", manager={"kind": "conda", "path": "/x/bin/conda", "version": "26.7", "root": "/x",
                                       "platform": "linux-64", "run_enters": True},
        environments={"gmsh": {"state": "ready", "install_fingerprint": FINGERPRINT}},
        settings=record.settings_now(config).model_dump(exclude_none=True)))
    study = laplace / "studies" / "check.toml"
    study.write_text(study.read_text().replace('# partition = "batch"', 'partition = "p1"')
                     .replace('# qos = "normal"', 'qos = "q1"'))
    outcome = prepped(target="cluster")
    assert outcome.ok() and len(sequences(outcome)) == 1
    assert not [a for a in nexts(outcome) if a.call is not None and a.call.operation == "job.launch"]
    assert "no-header" in {i.code for i in outcome.issues}


def test_a_step_for_another_machine_maps_the_fields_its_request_declares_a_path_and_no_other(laplace, here):
    """Fails if a next step for another machine's target is mapped by guessing from its values — a
    path of the project held in a field its request does not declare a path rewritten — or its
    label rewritten, or it does not carry the machine it runs on, rather than each field the
    request declares `path` given by its path from the project's folder (workflow.md § 7: "its
    `path` fields from the project's folder"; web.md § 7.2; core.md § 2: `path`)."""
    from femkit.jobs import prepare
    from femkit.jobs.requests import JOB_LAUNCH
    from femkit.workflow import graph
    write_record("other", identity="elsewhere", gmsh=FINGERPRINT)
    target = prepare.choose(ctx(), "other", lambda name: None)
    folder = laplace / "runs" / "check" / "launch" / "mesh-check-001"
    step = graph.there(kit.opened(laplace), target, view.command(
        JOB_LAUNCH, label="launch it", dir=str(folder), foreground=True, in_sequence=str(folder), in_job=str(folder)))
    relative = "runs/check/launch/mesh-check-001"
    assert (step.on, step.label) == ("other", "launch it")
    assert step.call.request == {"dir": relative, "foreground": True, "in_sequence": relative, "in_job": str(folder)}


def test_study_flow_for_another_machine_opens_an_output_by_its_path_from_the_project(laplace, here):
    """Fails if, for another machine's target, the line that opens a finished stage's output names
    the file by its full path on this machine rather than by its path from the project's folder, or
    does not carry the machine it runs on (workflow.md § 7: "every step — prep's, and `study flow`'s
    actions and the lines that open an output — carries the machine it runs on (`Action.on`)";
    web.md § 7.2)."""
    write_record("other", identity="elsewhere", gmsh=FINGERPRINT)
    outcome = prepped(target="other")
    (geometry,) = by_kind(flow(target="other"))["geometry"]
    (sequence,) = sequences(outcome)
    run = finish(Path(geometry.folder), Path(sequence))
    (opened,) = outputs(flow(target="other"), geometry.address)[(geometry.address, "output")].actions
    relative = (run / "geometry.xao").relative_to(laplace).as_posix()
    assert opened.shell.endswith(f"gmsh {relative}") and str(laplace) not in opened.shell
    assert opened.on == "other"


def test_the_file_a_stage_keeps_what_it_is_made_from_in_is_the_workflows_declaration(laplace, here, definitions):
    """Fails if the file a stage's folder keeps what it is made from in is named by the jobs
    catalogue — which knows nothing of stages — rather than by the workflow's own declaration,
    `stages.toml`, which every reader of a stage reads it by (jobs.md § 1: "This contract runs any
    calculation folder and knows nothing of geometry, meshes or projects"; workflow.md § 4)."""
    kit.rewrite(definitions / "stages.toml", 'made_from = "stage.json"', 'made_from = "made.json"')
    prepped()
    for n in flow().graph.nodes:
        assert (Path(n.folder) / "made.json").is_file() and not (Path(n.folder) / "stage.json").exists()
        assert n.state == "in_launch"
    study = {s.name: s for s in kit.run("case.list", project="laplace_square").studies}["check"]
    assert study.written and all(len(w.stages) == 2 for w in study.written)


# ------------------------------------------------------------------ what needs no machine (workflow.md § 7)

def no_record(laplace):
    record.path("local").unlink()


def unchosen(laplace):
    write_record("other", identity="elsewhere", gmsh=FINGERPRINT)


def no_fingerprint(laplace):
    write_record("local")


def stale(laplace):
    kit.apply("config.set", key="activation.preamble", value='["module load y"]')


@pytest.mark.parametrize("make, code, steps", [
    (no_record, "no-record", [("job.probe", None)]),
    (unchosen, "target-unchosen", [("study.prep", "local"), ("study.prep", "other")]),
    (no_fingerprint, "no-fingerprint", [("env.install", None), ("env.install", None), ("job.probe", None)]),
    (stale, "stale", [("job.probe", None)]),
], ids=["no record of this machine", "a target unchosen", "no fingerprint", "a stale record"])
def test_what_needs_no_machine_never_waits_for_one(laplace, here, make, code, steps):
    """Fails if, where the machine step cannot go on — no record of the target, a target unchosen
    among several, a record that is stale, or one lacking a stage's environment's fingerprint —
    `study prep` refuses, or writes a stage or a job, instead of
    writing its cases and saying what the stages wait for as one finding — its code, subject,
    message and the steps that settle it — in its plan, so the preview shows those steps, and in
    its outcome, once, never a second time as its next step (workflow.md § 7: "What needs no
    machine never waits for one … prep writes steps 1 and 2 and its outcome names what the stages
    wait for, with the steps that settle it"; "What its stages wait for is one finding of its plan
    and outcome … shown in the preview as in the outcome"; core.md § 10: an `Issue`'s `next`; ADR
    0022 decision 4)."""
    make(laplace)
    _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check", engine="elmer")
    (finding,) = plan.issues
    assert (finding.code, finding.severity) == (code, "warning")
    assert [(a.call.operation, a.call.request.get("target")) for a in finding.next] == steps
    assert all(a.command in plan.text() for a in finding.next)
    outcome = prepped(engine="elmer")
    assert outcome.ok() and len(outcome.added) == 3 and len(list((laplace / "cases" / "check").iterdir())) == 3
    assert not (laplace / "runs").exists() and outcome.stages == [] and sequences(outcome) == []
    assert [i for i in outcome.issues if i.code == code] == [finding]
    assert outcome.next == [] and nexts(outcome) == []
    said = [line.strip() for line in outcome.text().splitlines()]       # each step a line of its own
    assert all(said.count(str(a)) == 1 for a in finding.next)


def test_a_mesh_stage_runs_in_its_recipes_meshers_environment_and_waits_on_its_install(laplace, here, definitions):
    """Fails if a mesh stage runs in another environment than the one that provides the mesher its
    recipe states — so its identity is formed with `gmsh`'s fingerprint — rather than, where the
    target's record lacks that environment's install, the study's stages waiting, named why —
    `no-fingerprint`, the mesher's environment, and the steps that settle it — prep writing its
    cases alone and `study flow` refusing it, the stages having no identity (workflow.md §§ 2.1,
    2.3: "the mesh in its mesher's, the mesher … stated by the mesh recipe"; § 7: "so it does where
    the record lacks the install of an environment the study's stages run in, naming it"). Here a
    mesher run in `elmer` meshes; the record lists `gmsh` alone."""
    mesher = (definitions / "meshers" / "gmsh.toml").read_text()
    (definitions / "meshers" / "elmer_gmsh.toml").write_text(mesher.replace('provided_by = "gmsh"',
                                                                            'provided_by = "elmer"'))
    name_mesher(laplace, "elmer_gmsh")
    _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check")
    (waits,) = [i for i in plan.issues if i.code == "no-fingerprint"]
    assert waits.subject == "elmer" and [a.call.operation for a in waits.next] == ["env.install", "env.install",
                                                                                   "job.probe"]
    with kit.refused(Unstated, "no-fingerprint", "elmer"):
        flow()
    outcome = prepped()
    assert outcome.ok() and outcome.target is None and len(outcome.added) == 3
    assert outcome.stages == [] and sequences(outcome) == [] and not (laplace / "runs").exists()


def test_prep_without_an_engine_makes_the_stages_and_says_as_a_note_that_an_engine_is_chosen(laplace, here):
    """Fails if `study prep` without `--engine` is refused, or holds back its cases, geometry and mesh
    stages and the meshing job that makes them, or does not say, as one note, `no-engine`, at the
    study, that the engine is chosen when the study is solved — never that a solve waits, as if one
    would start — with the command that chooses it, the engine a fill which may be left out; or
    `study flow`, which takes no engine, says it (workflow.md § 7: "Without `--engine`, prep makes
    the study's cases, geometries and meshes as ever, and says, one note, `no-engine`, that they
    serve every engine and that the engine is chosen when the study is solved … never an error, and
    never words that a solve would start"; ADR 0025 decision 1)."""
    result = flow()
    assert {n.kind for n in result.graph.nodes} == {"geometry", "mesh"} and len(result.graph.nodes) == 4
    assert not [i for i in result.issues if i.code == "no-engine"]
    outcome = prepped()
    assert outcome.ok() and len(outcome.added) == 3 and len(outcome.stages) == 4
    assert [Path(s).name for s in sequences(outcome)] == ["mesh-check-001"]
    (said,) = [i for i in outcome.issues if i.code == "no-engine"]
    assert (said.severity, said.subject, said.file) == ("info", "study:check", "studies/check.toml")
    assert "chosen when the study is solved" in said.message and "waits" not in said.message
    (choose,) = said.next
    assert choose.call.operation == "study.prep" and [f.field for f in choose.fills] == ["engine"]
    assert "--engine ENGINE" in choose.command
    assert [a.call.operation for a in nexts(outcome)] == ["job.launch"]
    assert not [i for i in prepped(engine="elmer").issues if i.code == "no-engine"]


def test_prep_with_an_engine_names_it_and_says_solving_is_not_built_yet(laplace, here):
    """Fails if `study prep --engine` does not carry the engine it was given in its outcome, or its
    report does not say the study is prepared for that engine and that solving is not built yet, in
    plain words — or prep without one names an engine (workflow.md § 7: "its outcome names the engine
    and says the study is prepared for it, and that solving is not built yet"; docs/README.md M5)."""
    preview = kit.planned("study.prep", project="laplace_square", study="check", engine="ngsolve")[1].report
    outcome = prepped(engine="ngsolve")
    assert outcome.engine == "ngsolve"
    for report in (preview, outcome.report):
        said = [b.text for b in report.blocks if isinstance(b, view.Text)]
        assert [t for t in said if "ngsolve" in t and "not built yet" in t], said
    assert prepped().engine is None


def offered(action: view.Action) -> list[str] | None:
    """The engines an action's one fill offers: its fragment's closed list, where it states one."""
    (fill,) = action.fills
    held = [fill.json_schema, *fill.json_schema.get("anyOf", ())]
    return next((s["enum"] for s in held if "enum" in s), None)


def test_the_engine_prep_asks_for_offers_only_the_engines_that_can_solve_the_study(laplace, here):
    """Fails if the engine a `study prep` action asks for — a stage's next step in `study flow`, the
    `no-engine` note's next step — offers other choices than the engines that can solve the study, by
    the one rule its refusal's next steps follow (`study.solvers`): Gmsh's mesh at order 1 both Elmer
    and NGSolve, at order 2 Elmer alone (workflow.md § 7: "its choices are the engines that can solve
    the study, by the one rule `solvers` … as a refusal's next steps are"; web.md §§ 2.4, 7.2)."""
    def asked() -> list[list[str] | None]:
        stage = next(a for n in flow().graph.nodes for a in n.actions if a.call and a.call.operation == "study.prep")
        (note,) = [i for i in kit.planned("study.prep", project="laplace_square", study="check")[1].issues
                   if i.code == "no-engine"]
        return [offered(stage), offered(note.next[0])]

    assert asked() == [["elmer", "ngsolve"]] * 2
    kit.rewrite(laplace / "mesh" / "uniform.toml", "order = 1", "order = 2")
    assert asked() == [["elmer"]] * 2
    with kit.refused(Refused, "has-findings"):
        prepped(engine="ngsolve")


def test_the_geometry_and_mesh_stages_serve_every_engine(laplace, here):
    """Fails if a study's geometry or mesh stage is made from anything of an engine — its `stage.json`
    naming an engine or the environment it serves — so prep with another engine, or none, would make
    its geometries and meshes anew, rather than keep them, its stage IDs unchanged (workflow.md § 4:
    "A geometry or a mesh stage holds nothing of an engine: it is its study's, in its study's folder,
    serving every engine"; ADR 0025 decision 1)."""
    first = prepped(engine="elmer")
    before = {r.stage for r in first.stages}
    for n in flow().graph.nodes:
        held = made_of(Path(n.folder))
        assert not {"serves", "engine", "environment"} & set(held) and "elmer" not in json.dumps(held)
    assert {r.stage for r in prepped(engine="ngsolve").stages} == before
    assert {r.stage for r in prepped().stages} == before
    assert {n.state for n in flow().graph.nodes} == {"in_launch"}


def test_any_other_refusal_writes_nothing(laplace, here):
    """Fails if a refusal of the machine step that is none of those it waits on — another
    machine's record whose activation is unset — writes the cases, or anything else, rather than
    refusing before anything is written (workflow.md § 7: "every other refusal writes nothing")."""
    write_record("other", identity="elsewhere", gmsh=FINGERPRINT)
    data = tomllib.loads(record.path("other").read_text())
    del data["settings"]["activation"]["command"]
    persist.write_toml(record.path("other"), data)
    with kit.refused(Unstated, "setting-unstated", "activation.command"):
        prepped(target="other")
    assert not (laplace / "cases").exists() and not (laplace / "runs").exists()


def test_a_refusal_of_a_prepare_planned_in_memory_is_prep_s_and_comes_before_anything_is_written(laplace, here):
    """Fails if a refusal of `job prepare` that only preparing a job folder meets — a target with
    a scheduler and a job naming no queue — comes after anything is written, the cases included,
    rather than in prep's plan, each job folder's prepare planned from its request in memory; or
    it is re-coded rather than `job prepare`'s own kind, code and subject (workflow.md § 7: "the
    refusals of `job prepare`, planned in memory | theirs | theirs"; jobs.md § 3; ADR 0022
    decision 3)."""
    config = settings.load(kit.ctx(), fresh=True).config
    record.write(record.path("cluster"), kit.a_record(
        identity="elsewhere", manager={"kind": "conda", "path": "/x/bin/conda", "version": "26.7", "root": "/x",
                                       "platform": "linux-64", "run_enters": True},
        environments={"gmsh": {"state": "ready", "install_fingerprint": FINGERPRINT}},
        settings=record.settings_now(config).model_dump(exclude_none=True)))
    with kit.refused(Unstated, "queue-unstated", "resources.partition"):
        kit.planned("study.prep", project="laplace_square", study="check", target="cluster")
    with kit.refused(Unstated, "queue-unstated", "resources.partition"):
        prepped(target="cluster")
    assert not (laplace / "cases").exists() and not (laplace / "runs").exists()


@pytest.mark.parametrize("verb", ["study.prep", "study.flow"])
def test_study_prep_and_flow_pass_the_cases_refusal_through_unchanged(laplace, here, verb):
    """Fails if `study prep` or `study flow`, for a study whose component reads a parameter the
    project no longer defines, does not refuse as its cases refuse it — `case list`'s reason why
    `study prep` cannot make the study's cases — its kind, its code, its subject and its next steps unchanged, but
    re-codes it; or prep writes anything (workflow.md § 7: "the cases cannot be made … passed
    through as they are, kind, code and subject — `study flow` too"; core.md § 9: "a script, a
    surface or a test tells two refusals apart by kind, code and subject")."""
    kit.rewrite(laplace / "components" / "square" / "component.toml", 'side = "length"', 'width = "length"')
    with pytest.raises(Refused) as preparing:
        kit.planned("study.prep", project="laplace_square", study="check")
    with pytest.raises(Refused) as flowing:
        flow()
    theirs, ours = preparing.value, flowing.value
    assert (type(ours), ours.code, ours.subject, [a.command for a in ours.next]) == (
        type(theirs), theirs.code, theirs.subject, [a.command for a in theirs.next])
    study = {s.name: s for s in kit.run("study.list", project="laplace_square").studies}["check"]
    assert not study.makes and study.why == str(theirs)
    assert not (laplace / "cases").exists()


def test_a_stage_json_of_an_earlier_shape_is_a_finding_saying_what_it_is_never_a_stage(laplace, here):
    """Fails if a stage's `stage.json` in the shape femkit wrote before its `target` named the machine
    by its record's identity of the host — shape 1, whose `target` is a record's name, `local` — reads
    as a stage of the shape femkit writes now, `case list` showing that name as its machine, rather
    than a finding, `unreadable`, naming the file and saying what it is, wherever stages are listed
    (workflow.md § 4: "the target's machine, by its record's identity of the host, never the
    record's name"; "a stage folder whose `stage.json` … does not read … is a warning, `unreadable`,
    naming the file, wherever stages are listed"; models.md § 2: a file stating another shape "is a
    finding naming the shape the file states, the shape femkit reads")."""
    from femkit.workflow import identity
    prepped()
    folder = Path(by_kind(flow())["geometry"][0].folder)
    file = folder / stage_file()
    file.write_text(json.dumps({**made_of(folder), "schema": 1, "target": "local"}))
    said = identity.read(kit.ctx(), folder).problem
    assert said is not None and said.startswith("schema:")
    listed = kit.run("case.list", project="laplace_square")
    assert all(not s.stage.endswith(folder.name) for study in listed.studies for w in study.written for s in w.stages)
    for result in (listed, flow()):
        assert [(i.code, said in i.message) for i in result.issues if i.subject == str(file)] == [("unreadable", True)]


@pytest.mark.parametrize("held", ["{", json.dumps({"schema": 0})], ids=["no JSON", "another shape"])
def test_a_stage_whose_stage_json_does_not_read_is_a_finding_naming_it_wherever_it_is_listed(laplace, here, held):
    """Fails if a stage whose `stage.json` does not read — no JSON, or a shape femkit does not write
    — is dropped unsaid by `case list`, or passed over by `study flow`, rather than a finding naming
    that file (workflow.md §§ 4, 7; models.md § 2: "a file stating another shape does not load")."""
    prepped()
    file = Path(by_kind(flow())["geometry"][0].folder) / stage_file()
    file.write_text(held)
    for result in (kit.run("case.list", project="laplace_square"), flow()):
        assert [(i.code, i.subject) for i in result.issues if i.subject == str(file)] == [("unreadable", str(file))]


def test_study_prep_refuses_an_unreadable_stage_with_its_folders_next_steps(laplace, here):
    """Fails if `study prep`, meeting a stage whose newest run's launch record does not read, does
    not refuse `unreadable` naming that file, or offers next steps of its own writing rather than
    those the folder's table gives its state (workflow.md § 7: "next: `job status` of its folder";
    core.md § 7: "one source of next")."""
    prepped()
    folder = Path(by_kind(flow())["geometry"][0].folder)
    kit.apply("job.prepare", dir=str(folder))                   # taken out of its job: prepared apart
    run = folder / files().run_name(1)
    run.mkdir()
    (run / files().name("launched")).write_text("{")
    with kit.refused(Refused, "unreadable", str(run / files().name("launched"))) as caught:
        kit.planned("study.prep", project="laplace_square", study="check")
    c = ctx()
    m = folders.machine(c)
    f, state = folders.observe(c, folder)
    assert state is m.states.unreadable
    assert [(a.label, a.command) for a in caught.value.next] == [(a.label, a.command) for a in m.next(state, f)]


def test_study_flow_shows_a_finished_stage_whose_record_cannot_enter_its_environment(laplace, here):
    """Fails if `study flow` refuses where the target's record names a manager femkit cannot enter
    an environment with, instead of showing the graph — each finished output's file, with no line
    to open it — and saying why as a finding: it refuses only what workflow.md § 7 lists for it."""
    outcome = prepped()
    (geometry,) = by_kind(flow())["geometry"]
    finish(Path(geometry.folder), Path(sequences(outcome)[0]))
    data = tomllib.loads(record.path("local").read_text())
    data["manager"]["kind"] = "nowhere"
    persist.write_toml(record.path("local"), data)
    result = flow()
    xao = outputs(result, geometry.address)[(geometry.address, "output")]
    assert xao.file is not None and xao.actions == []
    assert "manager-unknown" in {i.code for i in result.issues}


def test_study_flows_next_steps_are_labelled_by_a_sentence_each_with_its_tables_words(laplace, here):
    """Fails if `study flow`'s next block is headed `next -- next:` rather than a sentence, or a step
    in it is printed without the words its state's table gives it (api.md § 4.4: "`next --
    <sentence>:` and the commands, one a line, indented, prose after `#`"; workflow.md § 6)."""
    lines = flow().text().splitlines()
    (head,) = [line for line in lines if line.startswith("next -- ")]
    assert head != "next -- next:"
    steps = lines[lines.index(head) + 1:]
    assert steps and all(line.strip().startswith("femkit study prep") and line.endswith("# make it") for line in steps)


def test_prep_says_what_it_does_by_the_stage_tables_own_tasks_never_a_folders_actions(laplace, here):
    """Fails if `study prep`'s plan or outcome names what it does to a stage otherwise than by the
    stage table's own tasks — `write`, `prepare`, `restate`, `place`, `use`, `leave` — each in
    that table's own sentence: by an action of the calculation folder's table — `launch` — or its
    sentence, or by a name the table's `[tasks]` does not declare; or the calculation folder's
    table keeps an action that is what code does rather than a next step (workflow.md § 6: "What
    `study prep` does to a stage is the stage table's own `[tasks]` … each with its own sentence,
    which prep's plan and outcome say"; core.md § 7: "What code does in a state is never an
    action: it is a task")."""
    own = tasks()
    assert set(own) == {"write", "prepare", "restate", "place", "use", "leave"}
    m = folders.machine(ctx())                    # each a next step: an operation, or its subject's — what wrote it
    assert all(a.verb is not None or a.subject for row in m.actions.values() for a in row.values())
    _, plan, _ = kit.planned("study.prep", project="laplace_square", study="check")
    first = prepped()
    assert {tuple(r.does) for r in first.stages} == {("write", "prepare", "place")}
    for outcome in (first, prepped()):
        assert all(r.describe == [own[d] for d in r.does] for r in outcome.stages)
        shown = {r["does"] for b in outcome.report.blocks if isinstance(b, view.Table) for r in b.rows if "does" in r}
        assert shown == {", ".join(r.describe) for r in outcome.stages}
    assert all(s.describe.endswith(": " + ", ".join(own[d] for d in ("write", "prepare", "place")))
               for s in plan.steps if s.id.startswith("stages:"))
    assert "launch" not in " ".join(s.describe for s in plan.steps if s.id.startswith("stages:"))


def test_prep_says_it_puts_a_stage_in_its_studys_job(laplace, here):
    """Fails if what prep says when it places a stage names the job otherwise than as its study's —
    an environment's job, of a study whose jobs went per environment, withdrawn: a study's meshing is
    one job, and its solves one more (workflow.md §§ 5, 6; ADR 0025 decision 1)."""
    place = tasks()["place"]
    assert "study's job" in place and "environment" not in place
    assert {tuple(r.describe) for r in prepped().stages} == {(tasks()["write"], tasks()["prepare"], place)}




# ------------------------------------------------------------------ a study's name (projects.md § 5)

@pytest.mark.parametrize("study", ["geometry", "sweeps/mesh", "launch"])
def test_a_studys_name_taking_a_step_a_stage_or_launch_folder_takes_is_a_finding(laplace, study):
    """Fails if a study whose name has a step that is a stage kind or `launch` — so its folder under
    `runs/` would lie inside another study's — is not an error of `project check` at the project
    file's `studies`, naming the step, which `study prep` refuses before anything is written
    (projects.md § 5)."""
    folder = laplace / "studies" / Path(f"{study}.toml")
    folder.parent.mkdir(parents=True, exist_ok=True)
    (laplace / "studies" / "check.toml").rename(folder)
    kit.rewrite(laplace / "project.toml", '"check"', f'"{study}"')
    kit.rewrite(laplace / "observables" / "midpoint" / "observables.toml", '"check"', f'"{study}"')
    checked = kit.run("project.check", project="laplace_square")
    assert [(i.code, i.key, i.label) for i in checked.issues if i.severity == "error"] == [
        ("made-step", "studies", study)]
    with kit.refused(Refused, "has-findings"):
        kit.planned("study.prep", project="laplace_square", study=study)


# ------------------------------------------------------------------ a request's shares (jobs.md § 2)

def test_a_shared_file_takes_no_name_in_the_run_but_two_shares_take_one_each():
    """Fails if a request sharing a file and writing one of the same name — the pass-through's
    `mesh.msh` — does not load, or one sharing two files of one name does: a shared file is read
    where it was made, never placed in the run, so the shares are named among themselves alone
    (jobs.md § 2)."""
    base = {"name": "given", "environment": "gmsh", "command": ["{python}", "pass_mesh.py"],
            "resources": {"ranks": 1, "threads": 1, "gpus": 0}, "outputs": ["mesh.msh"]}
    ctx_ = context(files().reserved())
    JobRequest.model_validate({**base, "shares": [{"folder": "../g", "file": "mesh.msh"}]}, context=ctx_)
    with pytest.raises(ValueError, match="shares"):
        JobRequest.model_validate({**base, "shares": [{"folder": "../g", "file": "mesh.msh"},
                                                       {"folder": "../h", "file": "mesh.msh"}]}, context=ctx_)


# ------------------------------------------------------------------ the page's models (web.md § 8.7)

def test_the_graphs_and_the_workflows_models_each_have_a_name_no_other_model_the_page_reads_has():
    """Fails if a model of the graph vocabulary, or a result of the workflow's or the models'
    operations, shares its name with another model the page reads — the vocabulary and every
    operation's result — which the page's types could not tell apart (api.md § 2.3; the names
    `reference.page_schemas` refuses twice)."""
    from pydantic import BaseModel
    from femkit import registry
    from femkit.core import operations as surface
    ops = registry.operations()
    every = {m for module in (view, surface) for m in vars(module).values()
             if isinstance(m, type) and issubclass(m, BaseModel) and m.__module__ == module.__name__}
    every |= {op.result for op in ops.values()}

    def inside(m: type) -> set[type]:
        found = {m}
        for f in m.model_fields.values():
            for t in (f.annotation, *getattr(f.annotation, "__args__", ())):
                if isinstance(t, type) and issubclass(t, BaseModel) and t not in found:
                    found |= inside(t)
        return found

    ours = {m for op in ops.values() if op.result.__module__.startswith(("femkit.workflow", "femkit.models"))
            for m in inside(op.result)} | {view.Graph, view.GraphNode, view.GraphPort, view.Wire, view.Box}
    names = [m.__name__ for m in {m for e in every for m in inside(e)}]
    assert not [m.__name__ for m in ours if names.count(m.__name__) > 1]


# ------------------------------------------------------------------ the definitions (models.md § 3)

HALF = ('\n[definitions.half]\ntype = "float"\nfunction = "half"\nunit = "m"\n',
        "\n\ndef half():\n    return defs.side / 2\n")


def computing(folder: Path) -> None:
    """The Laplace copy given a computed definition its script reads, `half`, and its study swept
    over the side it is computed from — `model_prep` installed, and the copy's `definitions.py`
    importing no scipy, which this Python, standing in for `model_prep`'s, does not hold."""
    kit.installed("model_prep", outcomes=[])   # ready: no check to run, its validate recorded
    kit.rewrite(folder / "definitions.py", "from scipy import constants\n", "")
    with open(folder / "project.toml", "a") as f:
        f.write(HALF[0])
    with open(folder / "definitions.py", "a") as f:
        f.write(HALF[1])
    kit.rewrite(folder / "components" / "square" / "component.toml", 'side = "length"',
                'side = "length"\nhalf = "length"')
    sweep_side(folder)


def program_runs(log: Path) -> int:
    """How many commands the stand-in manager ran in a prefix: each a run of femkit's program."""
    return log.read_text().count("run --no-capture-output") if log.exists() else 0


# Prep keeping its computed definitions, and their readers, run in the engine tier, on the person's
# `model_prep`: the one store writes through xarray, which the stand-in's python lacks
# (tests/engine/test_prep_definitions.py).


def test_prep_is_refused_where_model_prep_is_not_installed(laplace, here):
    """Fails if prep of a study whose project has a computed definition, where `model_prep` is not
    installed, is not refused about it with its install, as the environment's table gives an absent
    one's next steps, before anything is written (workflow.md § 7; envs.md § 3.3: "one `envs` check
    refuses any other state with that state's own next steps")."""
    with open(laplace / "project.toml", "a") as f:
        f.write(HALF[0])
    with open(laplace / "definitions.py", "a") as f:
        f.write(HALF[1])
    before = kit.tree(laplace)
    with kit.refused(Refused, "not-allowed", "model_prep") as caught:
        kit.planned("study.prep", project="laplace_square", study="check")
    assert {a.call.operation for a in caught.value.next} == {"env.install"} and kit.tree(laplace) == before
    assert all(a.call.request["names"] == ["model_prep"] for a in caught.value.next)


def test_project_graph_runs_the_very_check_project_check_runs_its_definitions_computed(laplace, here,
                                                                                      running_manager):
    """Fails if `project graph` gives other findings than `project check` — its computed definitions
    taken as kept instead of computed in `model_prep`, as `project check` computes them, so what only
    computing them finds is missing (models.md § 11.1: "the very check `project check` runs, its
    definitions computed")."""
    computing(laplace)
    kit.rewrite(laplace / "definitions.py", "return defs.side / 2", "return defs.side / 0")
    ran = program_runs(running_manager)
    checked = kit.run("project.check", project="laplace_square")
    assert program_runs(running_manager) == ran + 1
    result = kit.run("project.graph", project="laplace_square")
    assert program_runs(running_manager) == ran + 2
    held = [i for n in result.graph.nodes for i in n.issues] + list(result.issues)
    assert sorted((i.code, i.subject) for i in held) == sorted((i.code, i.subject) for i in checked.issues)
    assert any(i.severity == "error" and i.subject.startswith("project:definitions") for i in checked.issues)


# ------------------------------------------------------------------ a save and its impact (workflow.md § 10)

PHYSICS, PHYSICS_FILE = "physics:electrostatics", "physics/electrostatics.toml"


def saving(project: Path, address: str, relative: str, new: str, opened: str | None = None):
    """`project save` planned as the page plans it: the file an address names, its new text, and the
    SHA-256 the page opened the file with — its own now, unless one is given (projects.md § 7)."""
    sha = opened or hashlib.sha256((project / relative).read_bytes()).hexdigest()
    return kit.planned("project.save", project=project.name, address=address, text=new, sha256=sha)


def changed(project: Path, relative: str, old: str, new: str) -> str:
    """The text of ``relative`` with ``old`` replaced by ``new``, as the person types it in the page."""
    held = (project / relative).read_text()
    assert old in held, old
    return held.replace(old, new)


def lines(plan, *codes: str) -> list:
    """The plan's lines of the impact, those of ``codes`` alone, given some."""
    return [i for i in plan.issues if not codes or i.code in codes]


def test_project_save_writes_exactly_the_text_typed_under_the_projects_lock_on_the_page_alone(laplace):
    """Fails if `project save` is offered on the command line, holds not the project's lock, writes
    before it is applied, or writes other bytes than the text its request carries — its line ends,
    a last line without one — or formats it (projects.md § 7: "`project save`, an operation of the
    page alone ... writes the file an address names ... exactly as the text its request carries,
    through the door, under the project's lock"; api.md § 2, `surfaces`)."""
    ops = registry.operations()
    assert "project.save" in registry.offered(ops, "page") and "project.save" not in registry.offered(ops, "cli")
    typed = changed(laplace, PHYSICS_FILE, 'kind = "insulating"', 'kind = "insulating"   # as I like it').replace(
        "\n", "\r\n") + "# no line end"
    before = (laplace / PHYSICS_FILE).read_bytes()
    op, plan, c = saving(laplace, PHYSICS, PHYSICS_FILE, typed)
    assert plan.subjects == (kit.opened(laplace).project.subject,) and len(plan.steps) == 1
    assert (laplace / PHYSICS_FILE).read_bytes() == before
    outcome = op.apply(plan, c)
    assert outcome.status == "done" and (laplace / PHYSICS_FILE).read_bytes() == typed.encode("utf-8")


def test_project_save_writes_a_folder_parts_own_file_by_its_address(laplace):
    """Fails if a save of an address naming a folder part's file — `component:square@geometry.py` —
    writes another file, or other bytes (projects.md §§ 5, 7: "a part's, or a folder part's own file,
    `component:bowtie@geometry.py`")."""
    script = "components/square/geometry.py"
    typed = (laplace / script).read_text() + "# a note of mine\n"
    op, plan, c = saving(laplace, "component:square@geometry.py", script, typed)
    op.apply(plan, c)
    assert (laplace / script).read_text() == typed


def test_project_save_refuses_a_file_changed_since_the_page_opened_it_and_writes_nothing(laplace):
    """Fails if a save goes on over a file whose SHA-256 is no longer the one the page opened it with
    — changed before the plan, or between the plan and its apply — rather than refusing, `Refused` ·
    `file-changed`, naming it, and writing nothing (projects.md § 7; workflow.md § 10: "A file
    changed since the page opened it is refused, `file-changed`")."""
    path = laplace / PHYSICS_FILE
    opened_at = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_text(path.read_text() + "# changed in my own editor\n")
    meanwhile = path.read_bytes()
    with kit.refused(Refused, "file-changed", PHYSICS):
        saving(laplace, PHYSICS, PHYSICS_FILE, "anything\n", opened_at)
    op, plan, c = saving(laplace, PHYSICS, PHYSICS_FILE, meanwhile.decode() + "# mine\n")
    path.write_text(meanwhile.decode() + "# changed again\n")
    again = path.read_bytes()
    with kit.refused(Refused, "file-changed", PHYSICS):
        op.apply(plan, c)
    assert path.read_bytes() == again


def test_a_saves_plan_says_where_the_new_text_does_not_load_and_is_never_refused_for_it(laplace):
    """Fails if a save's plan does not say, as an error at its file and key, that the new text does
    not load, or refuses the save for what its text says (workflow.md § 10: the file, "whether it
    loads; where not, its file, key and reason"; "the file is the person's, so a save is never refused
    for what its text says")."""
    typed = changed(laplace, PHYSICS_FILE, 'formulation = "electrostatics"', "formulation = 3")
    op, plan, c = saving(laplace, PHYSICS, PHYSICS_FILE, typed)
    (said,) = lines(plan, "unloadable")
    assert (said.severity, said.file, said.key) == ("error", PHYSICS_FILE, "formulation") and said.line is not None
    op.apply(plan, c)
    assert (laplace / PHYSICS_FILE).read_text() == typed


def test_a_saves_plan_shows_each_finding_new_and_each_resolved_by_its_code_file_and_key(laplace):
    """Fails if a save's plan does not show each finding the new text brings, as `project check`
    makes it, or each it resolves, as a note at its file and key — or shows a finding that stands
    before and after (workflow.md § 10: "each finding new and each resolved, by its code, file and
    key")."""
    standing = {(i.code, i.key) for i in kit.run("project.check", project="laplace_square").issues}
    broken = changed(laplace, PHYSICS_FILE, 'kind = "insulating"', 'kind = "grounded"')
    op, plan, c = saving(laplace, PHYSICS, PHYSICS_FILE, broken)
    assert [(i.severity, i.code, i.file, i.key) for i in lines(plan)] == [
        ("error", "no-such-kind", PHYSICS_FILE, "conditions.sides.kind"),          # what the error stops: the cases
        ("warning", "cases-not-made", "studies/check.toml", None)]         # of each study using the physics
    op.apply(plan, c)
    op, plan, c = saving(laplace, PHYSICS, PHYSICS_FILE, broken.replace('kind = "grounded"', 'kind = "insulating"'))
    assert [(i.severity, i.code, i.file, i.key) for i in lines(plan)] == [
        ("info", "resolved", PHYSICS_FILE, "conditions.sides.kind"), ("info", "cases-new", "studies/check.toml", None)]
    assert not {(i.code, i.key) for i in lines(plan)} & standing


def test_a_promise_the_contract_no_longer_makes_is_shown_where_a_part_names_the_group(laplace):
    """Fails if removing a group from a component's contract does not show, before it writes, the
    finding at each key of another part that names the group (workflow.md § 10: "a broken promise
    among them: a group the contract no longer promises that a physics, a recipe, an observable set
    or an assignment names")."""
    contract = "components/square/component.toml"
    typed = changed(laplace, contract, "\n# the side at x = 0\nleft = 1\n", "\n")
    op, plan, c = saving(laplace, "component:square", contract, typed)
    assert {(i.severity, i.file, i.key) for i in lines(plan)} >= {("error", PHYSICS_FILE, "conditions.left")}


def test_a_saves_plan_shows_each_studys_cases_no_longer_made_and_new(laplace):
    """Fails if a change to what a study's sweep makes does not show, as notes on the study, the
    cases no longer made — kept as written — and the new ones (workflow.md § 10: each study's
    cases, "the cases no longer made, and the new ones")."""
    study = "studies/check.toml"
    fewer = changed(laplace, study, "values = [0.1, 0.05, 0.025]", "values = [0.1, 0.05]")
    gone = lines(saving(laplace, "study:check", study, fewer)[1], "cases-no-longer-made", "cases-new")
    assert [(i.code, i.severity, i.file) for i in gone] == [("cases-no-longer-made", "info", study)]
    more = changed(laplace, study, "values = [0.1, 0.05, 0.025]", "values = [0.1, 0.05, 0.025, 0.0125]")
    new = lines(saving(laplace, "study:check", study, more)[1], "cases-no-longer-made", "cases-new")
    assert [(i.code, i.severity, i.file) for i in new] == [("cases-new", "info", study)]
    assert new[0].next[0].call.operation == "study.prep"


def test_a_saves_plan_shows_each_stage_made_anew_in_place_of_the_one_it_replaces(laplace, here):
    """Fails if, for a study whose stages a machine has, a change to its mesh recipe does not show
    each mesh stage made anew, by the stage it replaces, with `study prep` for that machine — or
    shows a geometry, which the recipe does not reach, made anew (workflow.md § 10: each study's
    workflow, "the stages whose identity changes — made anew, their finished runs no longer
    used")."""
    prepped()
    meshes = {n.address for n in flow().graph.nodes if n.kind == "mesh"}
    typed = changed(laplace, "mesh/uniform.toml", "tolerance = 1e-9", "tolerance = 1e-8")
    anew = lines(saving(laplace, "mesh:uniform", "mesh/uniform.toml", typed)[1], "made-anew")
    assert {i.subject for i in anew} == meshes and len(anew) == len(meshes)
    assert all(i.next[0].call.request == {"project": "laplace_square", "study": "check", "target": "local"}
               for i in anew)


def test_a_saves_plan_shows_each_stage_no_longer_needed_and_each_made_impossible(laplace, here):
    """Fails if a value dropped from a study's sweep does not show the stages no case needs any more,
    or a recipe naming a mesher whose input no stage writes does not show the study's stages made
    impossible, a warning — rather than saying either as made anew (workflow.md § 10: "the stages made
    impossible — an input no stage writes (§ 2.2); the stages no longer needed")."""
    prepped()
    study = "studies/check.toml"
    meshes = {n.address: n for n in flow().graph.nodes if n.kind == "mesh"}
    fewer = changed(laplace, study, "values = [0.1, 0.05, 0.025]", "values = [0.1, 0.05]")
    dropped = lines(saving(laplace, "study:check", study, fewer)[1], "no-longer-needed", "made-anew")
    assert {i.code for i in dropped} == {"no-longer-needed"} and len(dropped) == 1
    assert {i.subject for i in dropped} <= set(meshes)
    given = changed(laplace, "mesh/uniform.toml", 'mesher = "gmsh"', 'mesher = "given"')
    impossible = lines(saving(laplace, "mesh:uniform", "mesh/uniform.toml", given)[1], "made-impossible")
    stages = {n.address for n in flow().graph.nodes}
    assert {i.subject for i in impossible} == stages and {i.severity for i in impossible} == {"warning"}


def test_a_saves_plan_shows_a_built_geometry_that_holds_not_a_group_the_contract_now_promises(laplace, here):
    """Fails if a group added to a component's contract that a finished geometry stage of a study
    pairing it holds not, as its `groups.json` says, is not shown as a warning at the group's key
    (workflow.md § 10: a built geometry's promise, "a group the contract now promises that a built
    geometry does not hold"; geometry.md § 7)."""
    outcome = prepped()
    (geometry,) = by_kind(flow())["geometry"]
    run = finish(Path(geometry.folder), Path(sequences(outcome)[0]))
    held = {g: {"dimension": d, "pieces": [{"dimension": d, "tag": 1, "measure": 1}]}
            for g, d in (("domain", 2), ("left", 1), ("right", 1), ("sides", 1))}
    persist.write_json(run / "groups.json", {"schema": 1, "dimension": 2, "groups": held, "unpromised": [],
                                             "bodies": [1], "faces": []})
    contract = "components/square/component.toml"
    typed = changed(laplace, contract, "sides = 1\n", "sides = 1\n# a corner\ncorner = 0\n")
    (said,) = lines(saving(laplace, "component:square", contract, typed)[1], "promise-not-held")
    assert (said.severity, said.file, said.key) == ("warning", contract, "groups.corner")


def test_a_saves_plan_shows_a_job_still_going_that_runs_a_stage_the_change_replaces(laplace, here):
    """Fails if a job still going that runs a stage the change makes anew is not shown, a warning on
    the job with its `job cancel` (workflow.md § 10: the jobs going, "a job still going that runs a
    stage the change makes anew: it runs on with what it was given"; jobs.md § 5.4)."""
    from femkit.core import dirs, process
    from femkit.jobs import addresses
    outcome = prepped()
    (mesh, *_) = by_kind(flow())["mesh"]
    own = process.identify(os.getpid())
    addresses.write(addresses.Address(id=f"{dirs.host()}-{own.pid}", how="background", host=dirs.host(),
                                      job=runs.Job.of(dirs.host(), own), folder=sequences(outcome)[0],
                                      runs=[str(Path(mesh.folder) / files().run_name(1))],
                                      time="2026-01-01T00:00:00+00:00"))
    typed = changed(laplace, "mesh/uniform.toml", "tolerance = 1e-9", "tolerance = 1e-8")
    (going,) = lines(saving(laplace, "mesh:uniform", "mesh/uniform.toml", typed)[1], "job-going")
    assert (going.severity, going.subject) == ("warning", f"job:{dirs.host()}-{own.pid}")
    assert going.next[0].call.operation == "job.cancel"
