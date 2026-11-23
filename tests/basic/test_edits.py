"""`model set`, `unset`, `rename` (models.md § 11.1, § 11.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from femkit import registry
from femkit.core.errors import PlanStale, Refused, UsageError
from femkit.core.operations import Context
from femkit.models.project import load_model, model_file, study_file

from tests.basic.test_models import examples


def ctx() -> Context:
    return Context.from_process()


def edit(verb: str, project: Path, *args: str):
    op = registry.operations()[f"model.{verb}"]
    fields = {"set": ("address", "value"), "unset": ("address",), "rename": ("address", "name")}[verb]
    req = op.request_from({"project": str(project), **dict(zip(fields, args))})
    return op.apply(op.plan(req, ctx()), ctx())


def findings(project: Path) -> int:
    op = registry.operations()["model.check"]
    return len(op.run(op.request_from({"project": str(project)}), ctx()).issues)


LAPLACE = [
    ("model:formulation", '"electrostatics"'),
    ("model:parameters.bias", '"1 V"'),
    ("model:frame.unit", '"m"'),
    ("model:geometry.dimension", "2"),
    ("model:geometry.meaning", '"per unit depth"'),
    ("model:geometry.shapes.square", '{ kind = "rectangle", corner = [0, 0], size = [1, 1] }'),
    ("model:regions.domain", '{ kind = "domain", shapes = ["square"] }'),
    ("model:regions.left", '{ kind = "boundary", plane = { point = [0, 0], normal = [-1, 0] } }'),
    ("model:regions.right", '{ kind = "boundary", plane = { point = [1, 0], normal = [1, 0] } }'),
    ("model:regions.sides", '{ kind = "boundary", rest = true }'),
    ("model:materials.vacuum.relative_permittivity.value", '"1"'),
    ("model:materials.vacuum.relative_permittivity.convention", '"real"'),
    ("model:materials.vacuum.relative_permittivity.source", '"definition of vacuum"'),
    ("model:materials.vacuum.relative_permittivity.range", '"all"'),
    ("model:assign.domain", '"vacuum"'),
    ("model:conditions.left", '{ kind = "potential", value = "0 V" }'),
    ("model:conditions.right", '{ kind = "potential", value = "bias" }'),
    ("model:conditions.sides", '{ kind = "insulating" }'),
]


def test_the_laplace_model_is_built_from_an_empty_folder_by_model_set_alone(tmp_path):
    """Fails if `model set` cannot build the contract's Laplace model from nothing, one edit at
    a time with every state loadable, its findings ending at none — the plan's acceptance for
    the graph's edits (plan § 3, M5)."""
    seen = []
    for address, value in LAPLACE:
        edit("set", tmp_path, address, value)
        load_model(tmp_path, ctx())             # every intermediate state loads
        seen.append(findings(tmp_path))
    assert seen[-1] == 0 and max(seen) > 0
    built = load_model(tmp_path, ctx())
    example = tmp_path / "example"
    example.mkdir()
    model_file(example).write_text(examples()[0])
    assert built == load_model(example, ctx())  # the very model models.md writes


@pytest.fixture
def project(tmp_path) -> Path:
    model, study = examples()
    model_file(tmp_path).write_text(model)
    study_file(tmp_path, "check").parent.mkdir(parents=True)
    study_file(tmp_path, "check").write_text(study)
    return tmp_path


def test_an_edit_keeps_the_files_comments_and_order(project):
    """Fails if an edit rewrites the person's file: its comments and its order stay (core.md § 4)."""
    before = model_file(project).read_text()
    edit("set", project, "model:parameters.bias", '"2 V"')
    after = model_file(project).read_text()
    assert after == before.replace('bias = "1 V"', 'bias = "2 V"')


def test_an_edit_that_would_leave_a_file_unloadable_is_refused_and_writes_nothing(project):
    """Fails if an edit that would leave the model or a study unloadable is written (§ 11.2)."""
    before = model_file(project).read_text()
    with pytest.raises(UsageError, match="unloadable"):
        edit("set", project, "model:regions.left", '{ kind = "domain", rest = true }')
    with pytest.raises(UsageError, match="unloadable"):
        edit("set", project, "model:assign.domain", '"gold"')
    assert model_file(project).read_text() == before


def test_removing_what_others_refer_to_is_refused_naming_each_place(project):
    """Fails if an object is removed while the model or a study still names it (§ 11.1)."""
    with pytest.raises(Refused) as caught:
        edit("unset", project, "model:regions.left")
    assert "model:conditions.left" in str(caught.value) and "study:check:numerics.mesh.regions.left" in str(caught.value)
    with pytest.raises(Refused, match="model:assign.domain"):
        edit("unset", project, "model:materials.vacuum")
    with pytest.raises(Refused, match="model:conditions.right.value"):
        edit("unset", project, "model:parameters.bias")
    edit("unset", project, "model:conditions.sides")      # nothing names a condition: removed
    assert "sides" not in load_model(project, ctx()).conditions


def test_a_rename_changes_every_reference_and_expression_with_it(project):
    """Fails if a rename leaves a reference, an expression or a study axis naming the old name,
    or loses the file's comments (§ 11.1)."""
    text = model_file(project).read_text().replace('[regions]', '[regions]   # where things are')
    text = text.replace('bias = "1 V"', 'bias = "1 V"\nhalf = "bias / 2"')
    model_file(project).write_text(text)
    study = study_file(project, "check").read_text()
    study_file(project, "check").write_text(study.replace(
        "[observables.midpoint]", '[axes."parameters.bias"]\nclass = "physical sweep"\nvalues = ["1 V"]\n\n'
                                  "[observables.midpoint]"))
    edit("rename", project, "model:regions.left", "west")
    edit("rename", project, "model:parameters.bias", "voltage")
    edit("rename", project, "model:materials.vacuum", "air")   # its properties are tables of their own
    model = load_model(project, ctx())
    assert model.assign == {"domain": "air"} and "[materials.air.relative_permittivity]" in model_file(project).read_text()
    assert set(model.conditions) == {"west", "right", "sides"} and "west" in model.regions
    assert model.conditions["right"].model_extra["value"] == "voltage" and model.parameters["half"] == "voltage / 2"
    assert "# where things are" in model_file(project).read_text()
    study = study_file(project, "check").read_text()
    assert 'regions = { west = "0.01 m" }' in study and '[axes."parameters.voltage"]' in study


def test_a_plan_made_before_a_file_changed_is_stale(project):
    """Fails if an edit applies over a file someone changed after its plan was made (api.md § 3)."""
    op = registry.operations()["model.set"]
    req = op.request_from({"project": str(project), "address": "model:parameters.bias", "value": '"2 V"'})
    plan = op.plan(req, ctx())
    model_file(project).write_text(model_file(project).read_text() + "\n# an edit by hand\n")
    with pytest.raises(PlanStale):
        op.apply(plan, ctx())


# ------------------------------------------------------------------ the graph

def graph(project: Path, **request):
    op = registry.operations()["model.graph"]
    return op.run(op.request_from({"project": str(project), **request}), ctx())


def test_the_graph_holds_every_object_and_every_reference_the_loader_checks(project):
    """Fails if a reference the loader checks is not a wire of the graph, or an object not a
    node: the graph and the check read one annotation and cannot disagree (models.md § 11.2)."""
    from femkit.core.schema import references
    from femkit.models.project import load_study
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


def test_a_finding_sits_on_the_node_it_names_and_the_palette_comes_from_the_formulation(project):
    """Fails if `model check`'s finding is not shown on its node, or the palette lists anything
    but the formulation's kinds and the schema's shapes, each with its sentence (models.md § 11.2)."""
    text = model_file(project).read_text()
    model_file(project).write_text(text.replace('sides = { kind = "insulating" }\n', ""))
    g = graph(project)
    sides = next(n for n in g.nodes if n.address == "model:regions.sides")
    assert sides.findings and "no condition" in sides.findings[0].message
    conditions = {p.kind: p for p in g.palette if p.group == "conditions"}
    assert set(conditions) == {"potential", "insulating", "surface_charge", "normal_flux", "interface"}
    assert conditions["surface_charge"].section == "3-conditions-on-an-outer-boundary"
    assert "sigma" in conditions["surface_charge"].parameters["value"]
    from femkit.definitions.meshers import ShapeKind
    import typing
    assert {p.kind for p in g.palette if p.group == "geometry"} == set(typing.get_args(ShapeKind))


def test_positions_are_saved_for_known_nodes_only(project):
    """Fails if a position is lost, or one is saved for a node that does not exist (§ 11.2)."""
    op = registry.operations()["model.layout"]
    req = op.request_from({"project": str(project), "positions": {"model:regions.left": [10, 20]}})
    op.apply(op.plan(req, ctx()), ctx())
    assert next(n for n in graph(project).nodes if n.address == "model:regions.left").position == [10, 20]
    with pytest.raises(UsageError, match="no node"):
        op.plan(op.request_from({"project": str(project), "positions": {"model:regions.nowhere": [0, 0]}}), ctx())
