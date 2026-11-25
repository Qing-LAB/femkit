"""The old model's graph and project listing, read-only (models.md § 11.2): what replaces them is
plan § 4, D; nothing here edits a person's file (projects.md § 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.kit import apply, ctx, run
from femkit import registry
from femkit.core.errors import Refused, UsageError
from femkit.core.operations import Context
from femkit.models.project import load_model, load_study, model_file, study_file

from tests.basic.test_models import examples


def ctx() -> Context:
    return Context.from_process()


def findings(project: Path) -> int:
    op = registry.operations()["model.check"]
    return len(op.run(op.request_from({"project": str(project)}), ctx()).issues)


@pytest.fixture
def project(tmp_path) -> Path:
    model, study = examples()
    model_file(tmp_path).write_text(model)
    study_file(tmp_path, "check").parent.mkdir(parents=True)
    study_file(tmp_path, "check").write_text(study)
    return tmp_path


def graph(project: Path, **request):
    op = registry.operations()["model.graph"]
    return op.run(op.request_from({"project": str(project), **request}), ctx())


def test_the_graph_holds_every_object_and_every_reference_the_loader_checks(project):
    """Fails if a reference the loader checks is not a wire of the graph, or an object not a
    node: the graph and the check read one annotation and cannot disagree (models.md § 11.2)."""
    from femkit.core.schema import references
    g = graph(project, study="check")
    nodes = {n.address for n in g.nodes}
    assert {"model:regions.left", "model:geometry.shapes.square", "model:materials.vacuum", "model:parameters.bias",
            "model:conditions.left", "study:check:observables.midpoint", "study:check:numerics"} <= nodes
    written = {e.address for e in g.edges}
    model = load_model(project, ctx())
    study = load_study(project, "check", ctx(), model)
    for where, instance in (("model", model), ("study:check", study)):
        for at, _, _, _ in references(instance):
            assert f"{where}:{'.'.join(map(str, at))}" in written
    edges = {(e.source, e.target, e.type) for e in g.edges}
    assert ("model:regions.domain", "model:materials.vacuum", "material") in edges        # the assignment
    assert ("model:conditions.right", "model:parameters.bias", "parameter") in edges      # an expression's use



def test_a_finding_sits_on_the_node_it_names_and_offers_no_edit(project):
    """Fails if `model check`'s finding is not shown on its node, or offers to change the file:
    the person writes the fix (web.md § 8.3; projects.md § 7)."""
    text = model_file(project).read_text()
    model_file(project).write_text(text.replace('sides = { kind = "insulating" }\n', ""))
    g = graph(project)
    sides = next(n for n in g.nodes if n.address == "model:regions.sides")
    finding = sides.findings[0]
    assert finding.code == "model-incomplete" and finding.next == ()


def test_every_reference_a_wire_is_drawn_into_is_under_a_port_of_its_node(project):
    """Fails if a reference held as a value or a list item — what a wire is drawn into — has no
    port on the node it starts from, or a port accepts other than the schema's type: the page
    could not draw it, or would draw what the loader refuses (models.md § 11.2)."""
    g = graph(project, study="check")
    by = {n.address: n for n in g.nodes}
    held = [e for e in g.edges if e.held in ("value", "item")]
    assert held
    for e in held:
        ports = [p for p in by[e.source].ports if e.address == p.address or e.address.startswith(p.address + ".")]
        target = by[e.target]
        assert ports, e
        assert any(target.kind in p.accepts or f"{target.kind}:{target.type}" in p.accepts for p in ports), e
    domain = {p.name: p for p in by["model:regions.domain"].ports}
    assert (domain["shapes"].many, domain["shapes"].names) == (True, ["square"])
    assert (domain["material"].address, domain["material"].accepts) == ("model:assign.domain", ["material"])
    assert {p.name for p in by["model:regions.left"].ports} == {"faces_of"}    # a boundary's own rules only
    assert {k.label for k in by["model:regions.left"].keys} == {"kind", "plane", "box", "faces_of", "rest"}


def test_a_parameter_used_twice_in_one_value_is_one_wire(project):
    """Fails if one value naming a parameter twice gives two wires, which a surface cannot tell
    apart (models.md § 11.2)."""
    text = model_file(project).read_text().replace('value = "bias"', 'value = "bias * 2 - bias"')
    model_file(project).write_text(text)
    wires = [e for e in graph(project).edges if e.target == "model:parameters.bias" and e.source == "model:conditions.right"]
    assert len(wires) == 1



def test_the_graph_names_what_a_surface_needs_and_no_surface_list(project):
    """Fails if the order or the choices a surface shows are not in the graph document — a
    surface would have to keep a list of its own (web.md § 8)."""
    g = graph(project)
    ranks = {n.kind: n.rank for n in g.nodes}
    assert ranks["parameter"] < ranks["shape"] < ranks["region"] < ranks["material"] == ranks["condition"]
    (choice,) = g.choices
    assert choice.set is None and choice.value == '"electrostatics"'
    assert "electrostatics" in choice.json_schema["enum"]



def test_every_key_and_port_carries_its_sentence_and_the_formulations_their_section(project):
    """Fails if a key or a port the help shows has no sentence, or a key the formulation declares
    — a condition's parameter, a material's property — carries the schema's words instead of the
    formulation's and no section to link to (models.md § 11.2, web.md § 8.3)."""
    from femkit.definitions import catalogue
    f = catalogue.formulations(ctx())["electrostatics"]
    nodes = {n.address: n for n in graph(project, study="check").nodes}
    assert all(x.help for n in nodes.values() for x in [*n.keys, *n.ports])
    value = next(x for x in nodes["model:conditions.right"].keys if x.label == "value")
    spec = f.conditions["potential"]
    assert value.help.sentence == spec.parameters["value"].description and value.help.doc.section == spec.section
    assert value.required and value.json_schema["unit"] == "V"
    eps = next(x for x in nodes["model:materials.vacuum"].keys if x.label == "relative_permittivity")
    assert eps.help.sentence == f.properties["relative_permittivity"].description
    assert eps.help.doc.anchor == f.properties["relative_permittivity"].section


#: What a person answers where a fix leaves a choice: the dimension, its meaning, the frame's unit.
def test_projects_are_listed_under_the_projects_folder_and_made_there(tmp_path):
    """Fails if a project is listed or made anywhere but under paths.projects, the list does not
    name what sets the folder while it is unset, or a project is made over one already there
    (web.md § 8.6)."""
    def run(operation: str, **request):
        op = registry.operations()[operation]
        req = op.request_from(request)
        return op.apply(op.plan(req, ctx()), ctx()) if op.changes else op.run(req, ctx())
    unset = run("project.list")
    assert unset.root is None and unset.issues[0].next[0].call.request == {"key": "paths.projects"}
    with pytest.raises(Refused, match="unset"):
        run("project.new", name="first")
    root = tmp_path / "projects"
    root.mkdir()
    c = ctx()
    apply("config.set", key="paths.projects", value=f'"{root}"')
    run("project.new", name="first")
    assert (root / "first").is_dir()
    study_file(root / "first", "check").parent.mkdir(parents=True)                 # written by the person
    study_file(root / "first", "check").write_text("[numerics]\ngeometry_order = 1\n")
    assert [(p.name, p.studies) for p in run("project.list").projects] == [("first", ["check"])]
    assert run("study.list", project=str(root / "first")).studies == ["check"]
    with pytest.raises(Refused, match="there already"):
        run("project.new", name="first")
    with pytest.raises(UsageError):
        run("project.new", name="../outside")

