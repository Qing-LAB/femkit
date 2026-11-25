"""The project as a graph (models.md § 11.2): a node per part and per object inside one, typed
wires read from the schemas' `ref` annotations and the parameters a quantity uses, each finding on
the node it names — read-only. On a copy of a template."""

from __future__ import annotations

import pytest

from tests import kit
from tests.kit import laplace  # noqa: F401 -- a fixture
from femkit.projects import layout


def test_the_graph_holds_each_part_and_object_and_every_reference_between_them(laplace):
    """Fails if a part or an object the layout declares has no node — with its kind, its rank, its
    text and, for a part, its state — or a reference a schema's `ref` annotation or a quantity's
    parameter makes is no wire, typed as the annotation types it (models.md § 11.2: "Ports are
    typed by the schema ... the loader reads the same annotation, so the graph and the check
    cannot disagree")."""
    before = {p: p.read_bytes() for p in laplace.rglob("*") if p.is_file()}
    result = kit.run("project.graph", project="laplace_square")
    nodes = {n.address: n for n in result.nodes}
    kinds = layout.read().kinds
    assert {a: (n.kind, n.rank, n.state) for a, n in nodes.items() if n.part is None} == {
        a: (a.split(":")[0], kinds[a.split(":")[0]].rank, "unchecked" if a == "study:check" else "complete")
        for a in ("project", "material:vacuum", "component:square", "physics:electrostatics", "mesh:uniform",
                  "observables:midpoint", "study:check")}
    left = nodes["physics:electrostatics:conditions.left"]
    assert (left.kind, left.type, left.part) == ("condition", "potential", "physics:electrostatics")
    assert left.text.splitlines()[1:] == ['kind = "potential"', "# the potential the boundary is held at, in V",
                                          'value = "0 V"']                                  # comments kept
    assert nodes["observables:midpoint"].text == (laplace / "observables" / "midpoint.toml").read_text()
    assert {"project:parameters.side", 'study:check:axes."mesh:uniform:size"', "study:check:steps.solve",
            "component:square:groups.left"} <= set(nodes)
    wires = {(e.source, e.target, e.port, e.type, e.held) for e in result.edges}
    assert wires >= {("study:check", "component:square", "component", "component", "value"),
                     ("project", "study:check", "studies", "study", "item"),
                     ("study:check:steps.solve", "physics:electrostatics", "physics", "physics", "value"),
                     ("observables:midpoint:observables.potential_middle", "project:parameters.side", None, "parameter",
                      "text")}
    assert len([e for e in result.edges if e.target == "project:parameters.side" and e.held == "text"]) == 1
    ports = {p.name: (p.accepts, p.names) for p in nodes["physics:electrostatics"].ports}
    assert ports["conditions"] == (["group:outer_boundary", "group:interface"], ["left", "right", "sides"])
    assert {p: p.read_bytes() for p in laplace.rglob("*") if p.is_file()} == before


def test_each_finding_sits_on_the_node_it_names_and_one_on_no_part_stays_apart(laplace):
    """Fails if a finding is not on the most specific node its subject names — a condition's, not
    its physics' — or one on a file that is no part's is on a node (models.md § 11.2: "Each node
    carries the findings that name it")."""
    kit.rewrite(laplace / "physics" / "electrostatics.toml", 'kind = "insulating"', 'kind = "grounded"')
    (laplace / "notes.txt").write_text("")
    result = kit.run("project.graph", project="laplace_square")
    held = {n.address: [i.code for i in n.findings] for n in result.nodes if n.findings}
    assert held["physics:electrostatics:conditions.sides"] == ["no-such-kind"]
    assert "physics:electrostatics" not in held
    assert [(i.code, i.subject) for i in result.issues] == [("stray", "notes.txt")]


def test_mermaid_draws_each_part_with_its_objects_and_the_wires(laplace):
    """Fails if `--mermaid` does not give the graph as Mermaid text — each part a box holding its
    objects, each wire an arrow — as the result's text (models.md § 11.1)."""
    result = kit.run("project.graph", project="laplace_square", mermaid=True)
    lines = result.mermaid.splitlines()
    assert lines[0] == "flowchart LR" and sum(line.strip().startswith("subgraph") for line in lines) == 6
    assert sum("-->" in line for line in lines) == len(result.edges)
    assert result.text().splitlines() == lines


def test_mermaid_prints_only_the_diagram_on_the_command_line(laplace):
    """Fails if `project graph --mermaid` on the command line prints anything but the Mermaid text —
    a tag such as `[project graph]` on its first line keeps it from being pasted as it is (web.md
    § 7.6: a `Code` block is printed untouched)."""
    from click.testing import CliRunner
    from femkit.cli import build
    out = CliRunner().invoke(build(), ["project", "graph", "--project", "laplace_square", "--mermaid"])
    assert out.exit_code == 0 and out.output.splitlines()[0] == "flowchart LR"


def test_a_parameter_the_script_reads_is_wired_to_it(laplace):
    """Fails if a parameter a component's script reads, named by its contract's `inputs.parameters`
    — a `ref` to a parameter, an object of the project file — has no wire to that parameter's node
    (models.md § 11.2: "Wires are the references between parts")."""
    result = kit.run("project.graph", project="laplace_square")
    assert ("component:square", "project:parameters.side", "inputs.parameters", "parameter", "key") in {
        (e.source, e.target, e.port, e.type, e.held) for e in result.edges}


@pytest.mark.parametrize("verb", ["project.check", "project.graph", "study.list", "case.list"])
def test_every_table_a_command_reports_has_its_headings_and_the_graph_lists_its_wires(laplace, verb):
    """Fails if a table the models' commands report — in the text and in the `--json` report the
    page draws — has a column without its heading, or if the graph's report does not list each
    wire beside its nodes (models.md § 11.2; web.md § 7.5)."""
    kit.apply("study.expand", project="laplace_square", study="check")
    result = kit.run(verb, project="laplace_square")
    tables = [b for b in result.model_dump(mode="json")["report"]["blocks"] if b["kind"] == "table"]
    assert tables and all(c["label"] for t in tables for c in t["columns"])
    if verb == "project.graph":
        assert [(r["source"], r["target"]) for r in tables[-1]["rows"]] == [(e.source, e.target) for e in result.edges]
