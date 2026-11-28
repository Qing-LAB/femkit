"""The project as a graph (models.md § 11.2): a node per part and per object inside one, typed
wires read from the schemas' `ref` annotations and the definitions a quantity uses, each finding on
the node it names, each part's node with a field for every key its file may hold (web.md § 8.3) —
read-only. On a copy of a template."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import get_args

import pytest

from tests import kit
from tests.kit import laplace, slab  # noqa: F401 -- fixtures
from femkit.core import persist, schema, text, view
from femkit.projects import layout


def test_the_graph_holds_each_part_and_object_and_every_reference_between_them(laplace):
    """Fails if a part or an object the layout declares has no node — of its family, `part` or
    `object`, with its kind within it, its rank, the files it opens as — an object its part's, by
    `part` — and, for a part, its state —
    or a reference a schema's `ref` annotation or a quantity's definition makes is no wire, typed as
    the annotation types it, from what is named to the port of what names it (models.md § 11.2:
    "Ports are typed by the schema ... the loader reads the same annotation, so the graph and the
    check cannot disagree"; web.md § 7.6: a wire "in one direction everywhere: from what gives or is
    named to what takes or names it" — a study into the observables part reading it; web.md
    § 2.2)."""
    before = {p: p.read_bytes() for p in laplace.rglob("*") if p.is_file()}
    result = kit.run("project.graph", project="laplace_square")
    nodes = {n.address: n for n in result.graph.nodes}
    kinds = layout.read().kinds
    assert {a: (n.family, n.kind, n.rank, n.state) for a, n in nodes.items() if n.part is None} == {
        a: ("part", a.split(":")[0], kinds[a.split(":")[0]].rank, "unchecked" if a.startswith("study:") else "complete")
        for a in ("project", "material:vacuum", "component:square", "physics:electrostatics", "mesh:uniform",
                  "observables:midpoint", "study:check")}
    left = nodes["physics:electrostatics:conditions.left"]
    assert (left.family, left.kind, left.type, left.part) == ("object", "condition", "potential",
                                                             "physics:electrostatics")
    assert left.files == [] and left.part in nodes              # an object opens as its part's file, by `part`
    assert [f.address for f in nodes["component:square"].files] == ["component:square",
                                                                    "component:square@geometry.py"]
    assert {"project:definitions.side", 'study:check:axes."mesh:uniform:size"',
            "study:check:steps.potential", "component:square:groups.left"} <= set(nodes)
    wires = {(w.source, w.source_port, w.target, w.target_port, w.type, w.address) for w in result.graph.wires}
    assert wires >= {("component:square", None, "study:check", "component", "component", "study:check:component"),
                     ("study:check", None, "project", "studies", "study", "project:studies"),
                     ("physics:electrostatics", None, "study:check:steps.potential", "physics", "physics",
                      "study:check:steps.potential.physics"),
                     ("study:check", None, "observables:midpoint", "studies", "study",
                      "observables:midpoint:studies"),
                     ("project:definitions.bias", None, "physics:electrostatics:conditions.right", None, "definition",
                      "physics:electrostatics:conditions.right.value")}
    assert all(w.checked for w in result.graph.wires)
    assert len([w for w in result.graph.wires if w.source == "project:definitions.bias" and w.target_port is None]) == 1
    ports = {p.name: (p.side, p.accepts, p.names) for p in nodes["physics:electrostatics"].ports}
    assert ports["conditions"] == ("in", ["group:outer_boundary", "group:interface"], ["left", "right", "sides"])
    assert {p: p.read_bytes() for p in laplace.rglob("*") if p.is_file()} == before


def test_each_finding_sits_on_the_node_it_names_and_one_on_no_part_stays_apart(laplace):
    """Fails if a finding is not among the issues of the most specific node its subject names — a
    condition's, not its physics' — or one on a file that is no part's is on a node (models.md
    § 11.2: "Each node carries the findings that name it"; web.md § 7.6: `issues`, one name)."""
    kit.rewrite(laplace / "physics" / "electrostatics.toml", 'kind = "insulating"', 'kind = "grounded"')
    (laplace / "notes.txt").write_text("")
    result = kit.run("project.graph", project="laplace_square")
    held = {n.address: [i.code for i in n.issues] for n in result.graph.nodes if n.issues}
    assert held["physics:electrostatics:conditions.sides"] == ["no-such-kind"]
    assert "physics:electrostatics" not in held
    assert [(i.code, i.subject) for i in result.issues] == [("stray", "notes.txt")]


def test_mermaid_draws_each_part_with_its_objects_and_the_wires(laplace):
    """Fails if `--mermaid` does not give the graph as Mermaid text — each part a box holding its
    objects, each wire an arrow — as the result's text (models.md § 11.1)."""
    result = kit.run("project.graph", project="laplace_square", mermaid=True)
    lines = result.text().splitlines()
    holding = {n.part for n in result.graph.nodes if n.part is not None}       # each part holding objects
    assert lines[0] == "flowchart LR" and sum(line.strip().startswith("subgraph") for line in lines) == len(holding)
    assert len(holding) == 6 and "study:check" in holding
    assert sum("-->" in line for line in lines) == len(result.graph.wires)


def test_mermaid_is_a_rendering_of_the_one_graph_never_a_second_copy(laplace):
    """Fails if `project graph --mermaid` holds the graph twice — as its graph and again as Mermaid
    text in a field of its own — rather than its one graph and that it is to be written as Mermaid,
    its report rendering that one graph (web.md § 7.7: a report "computed from its fields";
    PROJECT_CONTRACT.md § 1: one home)."""
    result = kit.run("project.graph", project="laplace_square", mermaid=True)
    assert result.model_dump(mode="json")["mermaid"] is True
    assert result.report.blocks == [view.Code(text=text.mermaid(result.graph))]


def test_mermaid_counts_a_nodes_findings_as_every_count_is_written(laplace):
    """Fails if `--mermaid` writes the count of a node's findings in another plural than every
    count a person reads — `(1 findings)` (models.md § 11.2; api.md § 4.4)."""
    kit.rewrite(laplace / "observables" / "midpoint" / "observables.toml", 'unit = "V"', 'unit = "Vx"')
    result = kit.run("project.graph", project="laplace_square", mermaid=True)
    counted = {len(n.issues) for n in result.graph.nodes if n.issues}
    assert 1 in counted
    assert all(f"({n} finding{'' if n == 1 else 's'})" in result.text() for n in counted)
    assert "(1 findings)" not in result.text()


def test_mermaid_prints_only_the_diagram_on_the_command_line(laplace):
    """Fails if `project graph --mermaid` on the command line prints anything but the Mermaid text —
    a tag such as `[project graph]` on its first line keeps it from being pasted as it is (web.md
    § 7.6: a `Code` block is printed untouched)."""
    from click.testing import CliRunner
    from femkit.cli import build
    out = CliRunner().invoke(build(), ["project", "graph", "--project", "laplace_square", "--mermaid"])
    assert out.exit_code == 0 and out.output.splitlines()[0] == "flowchart LR"


def test_a_definition_the_script_reads_is_wired_to_it(laplace):
    """Fails if a definition a component's script reads, named by its contract's `inputs.definitions`
    — a `ref` to a definition, an object of the project file — has no wire to that definition's node
    (models.md § 11.2: "Wires are the references between parts")."""
    result = kit.run("project.graph", project="laplace_square")
    assert ("project:definitions.side", "component:square", "inputs.definitions", "definition") in {
        (w.source, w.target, w.target_port, w.type) for w in result.graph.wires}


def test_a_definition_an_observable_takes_is_wired_to_it(laplace):
    """Fails if a definition an observable takes — named in its `takes.definitions`, a `ref` to a
    definition, an object of the project file — has no wire from that definition's node to the
    observable's (models.md § 11.2: "Inside an observables part: each observable, what it takes —
    its definitions and groups, each wired as any reference")."""
    result = kit.run("project.graph", project="laplace_square")
    assert ("project:definitions.side", "observables:midpoint:observables.potential_middle", "takes.definitions",
            "definition") in {(w.source, w.target, w.target_port, w.type) for w in result.graph.wires}


# ------------------------------------------------------------------ the reading order and the block words

READING = ["project", "material:dielectric_1", "material:dielectric_2", "component:slab", "physics:electrostatics",
           "mesh:uniform", "study:benchmark", "observables:benchmark"]


def test_the_parts_are_listed_by_section_in_the_sections_order_wherever_a_person_reads_them(slab):
    """Fails if the two-material template's description graph, `project check`'s parts table or
    `project graph`'s text and Mermaid text lists its parts in another order than the reading
    order — by section, Definitions, Component, Physics, Mesh, Study, Results, then rank, then the
    kind's place, then name — the observables part under Results, after the studies it reads; or a
    part's or an object's node lacks its section, an object its part's (projects.md § 4; models.md
    § 11.2; plan § 4, X acceptance)."""
    graph = kit.run("project.graph", project="slab").graph
    assert [n.address for n in graph.nodes if n.part is None] == READING
    sections = {n.address: n.section for n in graph.nodes}
    assert [sections[a] for a in READING] == ["Definitions", "Definitions", "Definitions", "Component", "Physics",
                                              "Mesh", "Study", "Results"]
    assert all(n.section == sections[n.part] for n in graph.nodes if n.part is not None)
    checked = kit.run("project.check", project="slab")
    assert [p.part for p in checked.parts] == READING
    table = next(b for b in checked.report.blocks if isinstance(b, view.Table))
    assert [r["part"] for r in table.rows] == READING
    drawn = next(b for b in kit.run("project.graph", project="slab").report.blocks if isinstance(b, view.Graph))
    rows = text.drawn(drawn)[0].rows
    assert [r["address"] for r in rows if r["address"] in READING] == READING
    mermaid = kit.run("project.graph", project="slab", mermaid=True).text()
    boxes = [line.split('"')[1] for line in mermaid.splitlines() if line.strip().startswith("subgraph")]
    assert boxes == [a for a in READING if any(n.part == a for n in graph.nodes)]


def test_every_part_carries_one_word_and_one_with_an_error_needs_attention(slab):
    """Fails if a part's node carries no word of the vocabulary's closed list, or its word is not
    its state's as `part.toml` declares it — a part with an error *needs attention*, one checked
    whole *up to date* — or an object carries one (projects.md § 8; web.md § 7.6; plan § 4, X
    acceptance)."""
    kit.rewrite(slab / "observables" / "benchmark" / "observables.toml", 'groups = ["high"]', 'groups = ["higher"]')
    nodes = {n.address: n for n in kit.run("project.graph", project="slab").graph.nodes}
    words = set(get_args(view.Shows))
    assert all(nodes[a].shows in words for a in READING)
    assert (nodes["observables:benchmark"].state, nodes["observables:benchmark"].shows) == ("errors",
                                                                                          "needs attention")
    assert (nodes["mesh:uniform"].state, nodes["mesh:uniform"].shows) == ("complete", "up to date")
    assert all(n.shows is None for n in nodes.values() if n.part is not None)


def test_each_axis_is_wired_to_what_it_varies_and_a_group_to_each_axis_it_steps(laplace):
    """Fails if a study's axis has no wire from the node of what it varies — the recipe whose value
    it is, the definition — or a group of axes that step together none from each axis it names
    (models.md § 11.2: "its axes, each wired to what it varies ... and its groups that step
    together"; web.md § 7.6: from what is named to what names it)."""
    kit.rewrite(laplace / "studies" / "check.toml", '# [together]\n',
                '[axes."project:definitions.bias"]\nclass = "numerical convergence"\nvalues = [1, 2, 3]\nunit = "V"\n\n'
                '[together.paired]\naxes = ["mesh:uniform:size", "project:definitions.bias"]\nreason = "as measured"\n')
    wires = {(w.source, w.target, w.type) for w in kit.run("project.graph", project="laplace_square").graph.wires}
    size, bias = 'study:check:axes."mesh:uniform:size"', 'study:check:axes."project:definitions.bias"'
    assert {("mesh:uniform", size, "mesh"), ("project:definitions.bias", bias, "definition"),
            (size, "study:check:together.paired", "axis"), (bias, "study:check:together.paired", "axis")} <= wires


# ------------------------------------------------------------------ the graph's shape (web.md § 7.6)

def test_each_file_a_node_opens_as_carries_its_text_and_digest_as_the_project_was_read(laplace):
    """Fails if a node's files are not each a `File` — its address, its text as the file holds it,
    comments kept, and its SHA-256 — read once from the opened project: a component's contract and
    its script, a part's own file; or an object repeats its part's text rather than naming its part,
    or a node keeps a text of its own beside them (web.md § 7.6: "`files` each file it opens as, a
    `File {address, text, sha256}` ... an object none of its own: the page shows its part's, the node
    `part` names, so a file's text is sent once"; projects.md § 6)."""
    nodes = {n.address: n for n in kit.run("project.graph", project="laplace_square").graph.nodes}
    folder = laplace / "components" / "square"
    held = {f.address: (f.text, f.sha256) for f in nodes["component:square"].files}
    for address, path in (("component:square", folder / "component.toml"),
                          ("component:square@geometry.py", folder / "geometry.py")):
        assert held[address] == (path.read_text(), hashlib.sha256(path.read_bytes()).hexdigest())
    (own,) = nodes["mesh:uniform"].files
    assert (own.address, own.text) == ("mesh:uniform", (laplace / "mesh" / "uniform.toml").read_text())
    left = nodes["physics:electrostatics:conditions.left"]
    assert left.files == [] and nodes[left.part].files[0].address == "physics:electrostatics"
    assert "text" not in view.GraphNode.model_fields


def test_each_finding_at_a_file_is_at_one_its_node_or_its_part_opens_as_by_its_path(slab):
    """Fails if a finding a node carries names a file — by its path, as the person opens it — that
    no file its node opens as, or its part's for an object, names by the same path, so the page could
    not mark the finding at its line of that file's text (web.md § 2.2: "Below are the part's
    findings"; § 9.2, `Listing`: "its lines marked where a finding points"; core.md § 10)."""
    kit.rewrite(slab / "components" / "slab" / "component.toml", 'material = "dielectric_2"',
                'material = "dielectric_3"')
    kit.rewrite(slab / "physics" / "electrostatics.toml", 'kind = "insulating"', 'kind = "insulting"')
    nodes = {n.address: n for n in kit.run("project.graph", project="slab").graph.nodes}
    at = [(n, i) for n in nodes.values() for i in n.issues if i.file is not None]
    assert {i.file for _, i in at} >= {"components/slab/component.toml", "physics/electrostatics.toml"}
    for node, issue in at:
        opens = nodes[node.part].files if node.part is not None else node.files
        (file,) = [f for f in opens if f.path == issue.file]
        assert issue.line is not None and file.text is not None and issue.line <= len(file.text.splitlines())


def test_a_studys_node_says_its_cases_written_those_it_makes_now_and_the_engines_that_can_solve_it(laplace):
    """Fails if a study's node does not carry, as facts its operation builds, how many of its cases
    are written, how many `study prep` makes now and the engines that can solve it — or a part of
    another kind carries them (web.md § 7.6: "`facts` what a person reads of it ... a study's cases
    written and the cases `study prep` makes now, and the engines that can solve it"; models.md
    § 11.2: "each study, with its cases prepared and done and the engines that can solve it, as
    facts")."""

    def facts() -> dict[str, list[tuple[str, str]]]:
        return {n.address: [(f.label, f.value) for f in n.facts]
                for n in kit.run("project.graph", project="laplace_square").graph.nodes if n.family == "part" and n.facts}

    before = facts()
    assert list(before) == ["study:check"]
    assert [v for _, v in before["study:check"]] == ["0", "3", "elmer, ngsolve"]
    kit.apply("study.prep", project="laplace_square", study="check")
    assert [v for _, v in facts()["study:check"]] == ["3", "3", "elmer, ngsolve"]


def test_a_definitions_node_says_its_value_in_its_unit(slab):
    """Fails if a definition's node does not carry, as the fact its operation builds, its value as a
    person reads it — in the unit its definition declares — or an object of another kind carries a
    fact (web.md § 7.6: "`facts` ... in `project graph` ... a definition's value in the unit it
    declares"; models.md § 11.2: "The definitions, each with its value in its unit")."""
    said = {n.address: [f.value for f in n.facts]
            for n in kit.run("project.graph", project="slab").graph.nodes if n.family == "object" and n.facts}
    assert said == {"project:definitions.length": ["1 m"], "project:definitions.height": ["1 m"],
                    "project:definitions.interface": ["0.5 m"], "project:definitions.bias": ["1 V"]}


def test_a_components_groups_are_its_out_ports_and_a_name_of_a_group_an_in_port_unwired_without_a_study(slab):
    """Fails if a component's node lacks an `out` port for each group its contract promises — typed
    by the places the group may be — or a field naming a group is not an `in` port; or, with no
    study in view, a wire reaches a group's port a physics or a recipe names, which only a study's
    pairing joins (web.md § 7.6: "A component's groups are its `out` ports; a condition, a source, a
    recipe's size, a group an observable takes … are `in` ports … without a study, drawn unwired")."""
    graph = kit.run("project.graph", project="slab").graph
    nodes = {n.address: n for n in graph.nodes}
    out = {p.name: (p.side, p.accepts) for p in nodes["component:slab"].ports if p.side == "out"}
    assert out["low"] == ("out", ["group:body"])
    assert set(out["middle"][1]) == {"group:outer_boundary", "group:interface", "group:embedded"}
    assert set(out) == {"low", "high", "middle", "left", "right", "sides"}
    group = {p.name: p.side for p in nodes["observables:benchmark:observables.energy_low"].ports}
    assert group["takes.groups"] == "in"
    assert not [w for w in graph.wires if w.source == "component:slab" and w.source_port is not None
                and not w.target.startswith("observables:")]


def test_each_group_an_observable_takes_is_wired_from_the_component_of_the_studies_it_reads(slab):
    """Fails if, with no study in view, each group an observable takes is not wired from the
    group's port on the component of the studies its part reads to its `takes.groups`: the part names its studies, so its pairing is its own (web.md § 7.6;
    models.md § 11.2; the person's page, 2026-11-27: two_material's `energy_low` and `energy_high`)."""
    graph = kit.run("project.graph", project="slab").graph
    wired = [(w.source_port, w.target, w.target_port) for w in graph.wires
             if w.source == "component:slab" and w.target.startswith("observables:")]
    assert sorted(wired) == [("high", "observables:benchmark:observables.energy_high", "takes.groups"),
                             ("low", "observables:benchmark:observables.energy_low", "takes.groups")]


def test_a_study_names_no_engine_so_its_node_has_no_engine_port(laplace):
    """Fails if a study's node holds a port, or a tag, naming an engine — a study names none, the
    engine chosen when it is solved — or the command line's graph writes an engine beside it, while
    what a port names that is no node, a recipe's mesher, is still written so (web.md § 7.6: `engine`
    "none for a study, which names none"; ADR 0025 decision 1)."""
    result = kit.run("project.graph", project="laplace_square")
    (study,) = [n for n in result.graph.nodes if n.address == "study:check"]
    assert study.engine is None and "engine" not in {p.name for p in study.ports}
    lines = result.text().splitlines()
    assert not any("engine:" in line for line in lines)
    assert any("mesh:uniform" in line and "mesher: gmsh" in line for line in lines)


def test_with_a_study_each_group_its_pairing_names_is_wired_and_one_its_geometry_must_tell_not_checked(slab):
    """Fails if, with a study in view, a group its paired physics or recipe names, or an observables
    part reading it takes, is not wired from the component's port of that group to the port that
    names it, at the value that names it — or such a wire is `checked` where whether the group is the place the statement
    stands on waits on the built geometry, or not `checked` where it does not (web.md § 7.6:
    "wired to the group through the study's pairing (`project graph --study S`)"; "`checked` false
    for a wire through a group whose kind waits on the built geometry"; models.md §§ 5.1, 11.2)."""
    kit.rewrite(slab / "mesh" / "uniform.toml", "tolerance = 1e-9\n",
                'tolerance = 1e-9\n\n[sizes]\nmiddle = {value = 0.05, unit = "m"}\n')
    graph = kit.run("project.graph", project="slab", study="benchmark").graph
    wired = {(w.source_port, w.target, w.target_port, w.address): w.checked for w in graph.wires
             if w.source == "component:slab" and w.source_port is not None}
    assert wired == {
        ("left", "physics:electrostatics", "conditions", "physics:electrostatics:conditions.left"): False,
        ("right", "physics:electrostatics", "conditions", "physics:electrostatics:conditions.right"): False,
        ("sides", "physics:electrostatics", "conditions", "physics:electrostatics:conditions.sides"): False,
        ("middle", "physics:electrostatics", "conditions", "physics:electrostatics:conditions.middle"): False,
        ("middle", "mesh:uniform", "sizes", "mesh:uniform:sizes.middle"): True,
        ("low", "observables:benchmark:observables.energy_low", "takes.groups",
         "observables:benchmark:observables.energy_low.takes.groups"): True,
        ("high", "observables:benchmark:observables.energy_high", "takes.groups",
         "observables:benchmark:observables.energy_high.takes.groups"): True}


def test_the_command_line_says_each_wire_not_checked_yet_and_mermaid_dashes_it(slab):
    """Fails if the command line's table of a graph's wires does not say, in words, which wires are
    not checked yet — a column shown only where some wire is not — or the Mermaid text draws such a
    wire as it draws a checked one (web.md § 7.5: "On the command line a graph is written as its
    tables"; § 7.6: `checked`; models.md § 11.2: a wire not checked yet "is shown as not checked yet,
    never hidden")."""
    graph = kit.run("project.graph", project="slab", study="benchmark").graph
    wires = text.drawn(graph)[1]
    assert [row.get("checked", "") for row in wires.rows] == ["" if w.checked else "not checked yet"
                                                              for w in graph.wires]
    assert not all(w.checked for w in graph.wires) and "checked" in [c.label for c in wires.columns]
    alone = kit.run("project.graph", project="slab").graph
    assert all(w.checked for w in alone.wires) and "checked" not in [c.key for c in text.drawn(alone)[1].columns]
    lines = text.mermaid(graph).splitlines()
    assert sum("-.->" in line for line in lines) == sum(not w.checked for w in graph.wires)
    assert sum("-->" in line for line in lines) == sum(w.checked for w in graph.wires)


def test_the_command_lines_wire_table_names_the_ports_a_wire_joins(slab):
    """Fails if the command line's table of a graph's wires leaves out the port each wire leaves by and
    the one it reaches, where a wire has them — so the wires a study's pairing draws from one
    component's groups to one physics read alike, the group each runs through unsaid (web.md § 7.5: a
    graph "written as its tables"; § 7.6: `Wire {source, source_port, target, target_port, …}`)."""
    graph = kit.run("project.graph", project="slab", study="benchmark").graph
    wires = text.drawn(graph)[1]
    assert [(row.get("source_port", ""), row.get("target_port", "")) for row in wires.rows] == [
        (w.source_port or "", w.target_port or "") for w in graph.wires]
    assert any(w.source_port for w in graph.wires) and {"from port", "to port"} <= {c.label for c in wires.columns}


# ------------------------------------------------------------------ a node's keys (web.md §§ 7.3, 8.3)

def keys(project: str, address: str) -> dict[str, view.Field]:
    """The keys the node ``address`` of ``project``'s graph carries, by the key path each names."""
    (node,) = [n for n in kit.run("project.graph", project=project).graph.nodes if n.address == address]
    return {k.key: k for k in node.keys}


def test_each_part_node_carries_a_field_for_every_key_its_part_may_hold_from_the_loaders_schema(laplace):
    """Fails if a part's node lacks a `Field` for a key its part may hold — each key its schema
    fixes, each key of an entry its text writes in a table whose keys the person chooses, a written
    one or one shown commented out, and each key its formulation declares: a condition's kind and
    the parameters that kind lists — or carries one for a key whose name the person chooses; or a
    field's fragment is not the loader's own, joined with what the formulation declares — its
    families and kinds as `enum`, a parameter's unit, its dimension and the unit table's symbols for
    it — or it misses whether it is required, its value as the file writes it, or where it is
    explained (web.md § 8.3: "a `Field` for every key it may hold, built from the schema and, for
    what a formulation or the property list declares, from those, by one builder of fragments — the
    very fragments the loader's schema states"; § 7.3)."""
    held = keys("laplace_square", "physics:electrostatics")
    assert set(held) == {"schema", "formulation", "meaning", "conditions", "sources",
                         "conditions.left.kind", "conditions.left.value", "conditions.right.kind",
                         "conditions.right.value", "conditions.sides.kind",
                         "sources.charge.kind", "sources.charge.on", "sources.charge.value"}
    formulation = held["formulation"]
    assert (formulation.json_schema["type"], formulation.json_schema["enum"]) == ("string", ["electrostatics"])
    assert formulation.required and formulation.value == '"electrostatics"'
    assert formulation.help.doc.document == "docs/manual/3-write-each-part.md"
    value = held["conditions.left.value"]
    assert value.required and value.value == '{value = 0, unit = "V"}' and value.help.doc is None
    assert value.help.sentence == "the potential the boundary is held at, in V"
    assert value.json_schema["unit"] == "V" and {"V", "mV", "kV"} <= set(value.json_schema["units"])
    assert value.json_schema["dimension"] == {"current": -1, "length": 2, "mass": 1, "time": -3}
    assert held["conditions.right.value"].value == '"bias"' and held["sources.charge.value"].value is None
    assert held["conditions.sides.kind"].json_schema["enum"] == ["potential", "insulating", "surface_charge",
                                                                 "normal_flux", "interface"]
    assert held["sources.charge.kind"].json_schema["enum"] == ["charge_density"]
    assert "anyOf" in held["sources.charge.value"].json_schema           # the quantity form the loader reads
    assert held["sources.charge.on"].json_schema["ref"] == "group" and held["sources.charge.on"].required
    assert not held["sources"].required and held["sources"].value is None


@pytest.mark.parametrize("template", ["laplace_square", "two_material"])
def test_the_help_beside_each_key_is_the_help_its_templates_comment_shows(tmp_path, template):
    """Fails if, for any key of any part of a template that carries its help as the comment above
    it, the node's field for that key says another help — its sentence, then where the manual
    explains it — than the comment: two builders of a key's help, or a key whose help the field
    lacks (web.md § 8.3: the keys built "by one builder of fragments"; projects.md § 7: "A key's
    help is the comment above it"; core.md § 2: `help_text` "the one builder of a help")."""
    kit.copy_template(tmp_path / "projects", template)
    graph = kit.run("project.graph", project=template).graph
    compared = 0
    for node in (n for n in graph.nodes if n.family == "part"):
        text = node.files[0].text
        held = {k.key: k for k in node.keys}
        for entry in persist.key_comments(text):
            field = held.get(schema.key_path(entry.path))
            if field is None or not entry.comment:
                continue
            doc = field.help.doc
            said = field.help.sentence + (f" {schema.pointer(Path(doc.document).name)}" if doc else "")
            assert said == entry.comment, (node.address, entry.path)
            compared += 1
    assert compared > 40


def test_a_key_the_property_list_or_the_step_kinds_declare_is_a_key_like_any_other(laplace):
    """Fails if a material's node lacks a field for each property of the property list — its
    sentence and unit the list's — or a written dataset's keys, or a study's step lacks its kind
    among the step kinds its formulations support (web.md § 7.3: "a condition's parameters and a
    material's properties are keys like any other"; § 8.3)."""
    held = keys("laplace_square", "material:vacuum")
    assert {"properties.relative_permittivity", "properties.refractive_index"} <= set(held)
    permittivity = held["properties.relative_permittivity"]
    assert permittivity.help.sentence == "the material's relative permittivity, in 1"
    assert permittivity.json_schema["unit"] == "1" and not permittivity.required and permittivity.value is None
    assert held["properties.relative_permittivity.definition.value"].required
    step = keys("laplace_square", "study:check")["steps.potential.kind"]
    assert step.json_schema["enum"] == ["stationary"] and step.required and step.value == '"stationary"'


def test_a_part_that_does_not_load_still_carries_the_keys_its_text_names(laplace):
    """Fails if a part whose file does not load carries no keys, so the person fixing it in the
    page's editor is offered no help: what its schema fixes, and the keys of the entries its text
    writes, are known from the text alone (web.md § 8.3; projects.md § 6: "a part that does not load
    is a finding on that part")."""
    kit.rewrite(laplace / "physics" / "electrostatics.toml", 'formulation = "electrostatics"', "formulation = 3")
    nodes = {n.address: n for n in kit.run("project.graph", project="laplace_square").graph.nodes}
    node = nodes["physics:electrostatics"]
    held = {k.key: k for k in node.keys}
    assert node.state == "unloadable"
    assert {"formulation", "conditions.left.kind", "conditions.sides.kind"} <= set(held)
    assert "conditions.left.value" not in held                  # its kind's parameters: no formulation is named
    assert held["formulation"].json_schema["enum"] == ["electrostatics"]


def test_a_quantity_key_carries_its_dimension_and_the_unit_tables_symbols_for_it(laplace):
    """Fails if a key the schema declares a quantity of a fixed dimension carries no dimension, or
    not the unit table's symbols for it, or a closed list is not its fragment's `enum`, or a key
    whose schema states no `doc` is said to be explained somewhere (web.md § 7.3: "a quantity's
    carries its dimension and the unit table's symbols for it; a closed list carries `enum`";
    core.md § 2)."""
    held = keys("laplace_square", "mesh:uniform")
    size = held["size"]
    assert size.json_schema["dimension"] == {"length": 1} and {"m", "mm", "nm", "um"} <= set(size.json_schema["units"])
    assert size.json_schema["quantity"] == "length" and size.required
    assert held["order"].json_schema["enum"] == [1, 2] and held["tolerance"].help.doc is None
    assert "sizes" in held and "units" not in held["tolerance"].json_schema


def test_each_file_a_node_opens_as_carries_the_action_that_saves_it_exactly_as_typed(laplace):
    """Fails if a file the graph gives a node is not given the action that saves it — `project save`
    of its address and of the SHA-256 the project was read with, its new text the one value left to
    fill — so the page would name an operation or a field of its own to save a file (web.md § 7.6,
    `File.save`; projects.md § 7: "Its request states the file's SHA-256 when the page opened it")."""
    nodes = {n.address: n for n in kit.run("project.graph", project="laplace_square").graph.nodes}
    for f in nodes["component:square"].files:
        assert f.save is not None and f.save.call.operation == "project.save"
        assert f.save.call.request == {"project": "laplace_square", "address": f.address, "sha256": f.sha256}
        assert [x.field for x in f.save.fills] == ["text"]


def test_each_reference_wire_says_the_key_that_names_it_within_its_file_as_a_finding_does(laplace):
    """Fails if a wire for a reference does not carry the key that names it within the naming part's
    file, written as a finding writes its key — so the page would say a wire by its whole address, or
    cut the address's grammar itself (web.md § 7.6, `Wire.key`; core.md § 10, `Issue.key`)."""
    graph = kit.run("project.graph", project="laplace_square", study="check").graph
    held = {(w.source, w.address): w.key for w in graph.wires if w.address}
    assert held[("project:definitions.side", "component:square:inputs.definitions.side")] == "inputs.definitions.side"
    assert held[("mesh:uniform", 'study:check:axes."mesh:uniform:size"')] == 'axes."mesh:uniform:size"'
    assert all(key for key in held.values())
