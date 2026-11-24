"""`model set`, `unset`, `rename` (models.md § 11.1, § 11.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from femkit import registry
from femkit.core.errors import PlanStale, Refused, UsageError
from femkit.core.operations import Context
from femkit.models.project import load_model, load_study, model_file, study_file

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
    """Fails if `model set` cannot build the Laplace model from nothing, one edit at
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
    """Fails if `model check`'s finding is not shown on its node, the palette lists anything but
    the object types it offers with the formulation's kinds, or an add's text starts from other
    than its template — its type held, every key it may hold written, its sentence beside it —
    or the palette offers geometry, which is made outside femkit (web.md § 8.3, ADR 0010)."""
    text = model_file(project).read_text()
    model_file(project).write_text(text.replace('sides = { kind = "insulating" }\n', ""))
    g = graph(project)
    sides = next(n for n in g.nodes if n.address == "model:regions.sides")
    assert sides.findings and "no condition" in sides.findings[0].message
    conditions = {e.type: e for e in g.palette if e.kind == "condition"}
    assert set(conditions) == {"potential", "insulating", "surface_charge", "normal_flux", "interface"}
    assert conditions["surface_charge"].help.doc.section == "3-conditions-on-an-outer-boundary"
    template = next(f for f in conditions["surface_charge"].add.fills if f.field == "text").template
    assert 'kind = "surface_charge"' in template.splitlines()
    assert any(line.startswith('# value = "… C/m^2"') and "required" in line for line in template.splitlines())
    assert not any(e.kind == "shape" for e in g.palette)


def perform(action, **given):
    """Run an action as a surface does: each value given — a hole's by its name, a whole
    field's by the field — then plan and apply it (web.md § 9.1)."""
    request = dict(action.call.request)
    for f in action.fills:
        key = f.hole.strip('"<>') if f.hole else f.field
        request[f.field] = request[f.field].replace(f.hole, given[key]) if f.hole else given[key]
    op = registry.operations()[action.call.operation]
    req = op.request_from(request)
    return op.apply(op.plan(req, ctx()), ctx()) if op.changes else op.run(req, ctx())


def test_every_text_the_graph_shows_written_back_changes_nothing_it_holds(project):
    """Fails if a node's text, written back by its own action as the editor shows it, is refused,
    changes what the files hold, or loses a comment the person wrote (web.md § 8.3)."""
    text = model_file(project).read_text().replace('convention = "real"', 'convention = "real"   # never complex')
    text = text.replace('bias = "1 V"', 'bias = "1 V"   # the plate voltage')
    model_file(project).write_text(text)
    nodes = graph(project, study="check").nodes
    before = (load_model(project, ctx()), load_study(project, "check", ctx(), load_model(project, ctx())))
    for n in nodes:
        perform(n.write, text=n.text)
    model = load_model(project, ctx())
    assert (model, load_study(project, "check", ctx(), model)) == before
    assert "# never complex" in model_file(project).read_text()
    assert "# the plate voltage" in model_file(project).read_text()             # a value's own line's comment


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


def test_a_wire_drawn_through_a_port_writes_what_the_loader_reads(project):
    """Fails if setting a port's address to a name, or adding one to a list port, as a wire
    does, does not give the reference the port names (models.md § 11.2)."""
    edit("set", project, "model:materials.air", '{ relative_permittivity = { value = "1", convention = "real", '
                                                 'source = "s", range = "all" } }')
    edit("set", project, "model:geometry.shapes.extra", '{ kind = "rectangle", corner = [1, 0], size = [1, 1] }')
    domain = {p.name: p for p in next(n for n in graph(project).nodes if n.address == "model:regions.domain").ports}
    edit("set", project, domain["material"].address, '"air"')
    edit("set", project, domain["shapes"].address, '["square", "extra"]')
    model = load_model(project, ctx())
    assert model.assign["domain"] == "air" and model.regions["domain"].shapes == ["square", "extra"]


def test_a_parameter_used_twice_in_one_value_is_one_wire(project):
    """Fails if one value naming a parameter twice gives two wires, which a surface cannot tell
    apart (models.md § 11.2)."""
    text = model_file(project).read_text().replace('value = "bias"', 'value = "bias * 2 - bias"')
    model_file(project).write_text(text)
    wires = [e for e in graph(project).edges if e.target == "model:parameters.bias" and e.source == "model:conditions.right"]
    assert len(wires) == 1



def test_the_graph_names_what_a_surface_needs_and_no_surface_list(project):
    """Fails if the order, the names an add needs, or the choices a surface offers are not in
    the graph document — a surface would have to keep a list of its own (web.md § 8)."""
    g = graph(project)
    ranks = {n.kind: n.rank for n in g.nodes}
    assert ranks["parameter"] < ranks["shape"] < ranks["region"] < ranks["material"] == ranks["condition"]
    assert {n.address for n in g.nodes if n.rename} >= {"model:regions.left", "model:parameters.bias"}
    assert next(n for n in g.nodes if n.address == "model:conditions.left").rename is None
    potential = next(e for e in g.palette if e.kind == "condition" and e.type == "potential")
    assert next(f for f in potential.add.fills if f.field == "address").accepts == ["region:boundary"]
    assert all(e.needs for e in g.palette if e.kind == "observable")             # no study chosen
    assert all(not e.needs for e in graph(project, study="check").palette)
    (choice,) = g.choices
    assert choice.set.call.request["address"] == "model:formulation" and choice.value == '"electrostatics"'
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
ANSWERS = {"model:geometry.dimension": "2", "model:geometry.meaning": '"per unit depth"', "model:frame.unit": '"m"'}


def written(template: str, **values: str) -> str:
    """A template as a person fills it: each key given uncommented with its value; every other
    line as the template wrote it."""
    out = []
    for line in template.splitlines():
        key = line[2:].split(" = ", 1)[0] if line.startswith("# ") and " = " in line else None
        out.append(f"{key} = {values.pop(key)}" if key in values else line)
    assert not values, f"the template has no line for {sorted(values)}"
    return "\n".join(out) + "\n"


def test_the_laplace_model_is_built_from_an_empty_folder_with_what_the_graph_document_offers(tmp_path):
    """Fails if the page could not build the Laplace model from an empty folder by the
    graph document's actions alone — its choice, the findings' fixes, its palette's templates, a
    port's connect, a node's text — and what a person writes: the names, each choice a fix
    leaves, each template filled, the geometry's text (plan § 3, M7 item 3)."""
    def page():
        return graph(tmp_path)

    def add(kind: str, type_: str, **given: str) -> None:
        entry = next(e for e in page().palette if (e.kind, e.type) == (kind, type_))
        names = {f.hole.strip('"<>'): given.pop(f.hole.strip('"<>')) for f in entry.add.fills if f.hole}
        template = next(f for f in entry.add.fills if f.field == "text").template
        text = given.pop("text") if "text" in given else written(template, **given)
        perform(entry.add, text=text, **names)

    def fix() -> None:
        for issue in [*page().issues, *(i for n in page().nodes for i in n.findings)]:
            step = next((n for n in issue.next if n.call), None)
            if step is not None and issue.subject in ANSWERS:
                perform(step, value=ANSWERS[issue.subject])

    (choice,) = page().choices
    perform(choice.set, value='"electrostatics"')
    fix(); fix()                                          # the dimension, then its meaning
    add("parameter", None, name="bias", text='"1 V"')
    geometry = next(n for n in page().nodes if n.kind == "geometry")
    perform(geometry.write, text=geometry.text + '\n[shapes.square]\nkind = "rectangle"\ncorner = [0, 0]\nsize = [1, 1]\n')
    fix()                                                 # bare coordinates: the frame's unit
    add("region", "domain", name="domain", shapes='["square"]')
    add("region", "boundary", name="left", plane="{ point = [0, 0], normal = [-1, 0] }")
    add("region", "boundary", name="right", plane="{ point = [1, 0], normal = [1, 0] }")
    add("region", "boundary", name="sides", rest="true")
    add("material", "relative_permittivity", material="vacuum", value='"1"', convention='"real"',
        source='"definition of vacuum"', range='"all"')
    domain = next(n for n in page().nodes if n.address == "model:regions.domain")
    perform(next(p for p in domain.ports if "material" in p.accepts).connect, name="vacuum")   # the wire
    add("condition", "potential", region="left", value='"0 V"')
    add("condition", "potential", region="right", value='"bias"')
    add("condition", "insulating", region="sides")
    assert findings(tmp_path) == 0
    example = tmp_path / "example"
    example.mkdir()
    model_file(example).write_text(examples()[0])
    assert load_model(tmp_path, ctx()) == load_model(example, ctx())


def test_a_table_set_over_a_table_keeps_the_files_form_and_comments(project):
    """Fails if setting a node's whole value — as the page commits a node's form, in one edit —
    rewrites its table into another form or loses its comments (models.md § 11.1)."""
    text = model_file(project).read_text().replace('convention = "real"', 'convention = "real"   # never complex here')
    model_file(project).write_text(text)
    edit("set", project, "model:materials.vacuum.relative_permittivity",
         '{ value = "2", convention = "real", source = "definition of vacuum", range = "all" }')
    after = model_file(project).read_text()
    assert after == text.replace('value = "1"\nconvention', 'value = "2"\nconvention')
    edit("set", project, "model:regions.left", '{ kind = "boundary", plane = { point = [0, 0], normal = [-1, 0] } }')
    assert model_file(project).read_text() == after                    # the same value: nothing changes


def test_an_edit_is_taken_back_and_made_again_and_never_over_a_hand_edit(project):
    """Fails if `model undo` does not restore each file an edit changed to its text before it,
    `model redo` does not make it again, a new edit leaves an undone one redoable, or either
    acts over a file changed by hand since (models.md § 11.1)."""
    def turn(verb: str):
        op = registry.operations()[f"model.{verb}"]
        return op.apply(op.plan(op.request_from({"project": str(project)}), ctx()), ctx())
    first = model_file(project).read_text()
    edit("rename", project, "model:parameters.bias", "voltage")
    renamed = model_file(project).read_text()
    turn("undo")
    assert model_file(project).read_text() == first
    turn("redo")
    assert model_file(project).read_text() == renamed
    turn("undo")
    edit("set", project, "model:parameters.bias", '"2 V"')            # a new edit: the undone one is gone
    assert not turn("redo").plan.steps
    turn("undo")
    assert model_file(project).read_text() == first and not turn("undo").plan.steps   # nothing older stands
    turn("redo")
    model_file(project).write_text(model_file(project).read_text() + "\n# by hand\n")
    with pytest.raises(Refused, match="changed since"):
        turn("undo")


def test_projects_are_listed_under_the_projects_folder_and_made_there(tmp_path):
    """Fails if a project is listed or made anywhere but under web.projects, the list does not
    name what sets the folder while it is unset, or a project is made over one already there
    (web.md § 8.6)."""
    from femkit.config.operations import ConfigSet
    from femkit.core.errors import Refused
    def run(operation: str, **request):
        op = registry.operations()[operation]
        req = op.request_from(request)
        return op.apply(op.plan(req, ctx()), ctx()) if op.changes else op.run(req, ctx())
    unset = run("project.list")
    assert unset.root is None and unset.issues[0].next[0].call.request == {"key": "web.projects"}
    with pytest.raises(Refused, match="unset"):
        run("project.new", name="first")
    root = tmp_path / "projects"
    root.mkdir()
    c = ctx()
    ConfigSet.apply(ConfigSet.plan(ConfigSet.request(key="web.projects", value=f'"{root}"'), c), c)
    run("project.new", name="first")
    assert (root / "first").is_dir()
    edit("set", root / "first", "study:check:numerics.geometry_order", "1")
    assert [(p.name, p.studies) for p in run("project.list").projects] == [("first", ["check"])]
    assert run("study.list", project=str(root / "first")).studies == ["check"]
    with pytest.raises(Refused, match="there already"):
        run("project.new", name="first")
    with pytest.raises(UsageError):
        run("project.new", name="../outside")


def test_a_text_is_written_as_one_edit_keeping_its_comments_or_not_at_all(project):
    """Fails if `model write` writes a text that would leave a file unloadable, loses a comment
    the text carries, or is more than one step to take back (models.md § 11.1)."""
    def run(operation: str, **request):
        op = registry.operations()[operation]
        return op.apply(op.plan(op.request_from(request), ctx()), ctx())
    before = model_file(project).read_text()
    with pytest.raises(UsageError, match="unloadable"):
        run("model.write", project=str(project), address="model:conditions.left", text='kind = 3\n')
    assert model_file(project).read_text() == before
    text = '# held at ground\nkind = "potential"\nvalue = "0 V"   # the left plate\n'
    run("model.write", project=str(project), address="model:conditions.left", text=text)
    node = next(n for n in graph(project).nodes if n.address == "model:conditions.left")
    assert node.text == text
    run("model.undo", project=str(project))
    assert model_file(project).read_text() == before


def test_a_finding_offers_a_value_only_from_a_closed_list_and_sits_in_its_object(tmp_path):
    """Fails if a finding's fix asks a value to write — a quantity, a name — which belongs in its
    object's text, rather than one to choose from a closed list; or a finding about a part of an
    object sits on no node (web.md § 8.3, § 7.4)."""
    edit("set", tmp_path, "model:formulation", '"electrostatics"')
    edit("set", tmp_path, "model:geometry.dimension", "2")
    edit("set", tmp_path, "model:geometry.meaning", '"per unit depth"')
    edit("set", tmp_path, "model:regions.left", '{ kind = "boundary", rest = true }')
    edit("set", tmp_path, "model:conditions.left", '{ kind = "potential" }')
    g = graph(tmp_path)
    nodes = {n.address: n for n in g.nodes}
    assert any("no shape" in i.message for i in nodes["model:geometry"].findings)
    (missing,) = [i for i in nodes["model:conditions.left"].findings if "states no value" in i.message]
    assert not missing.next                                         # written in the condition's text
    for issue in [*g.issues, *(i for n in g.nodes for i in n.findings)]:
        for step in issue.next:
            for fill in step.fills:
                if fill.field == "value" and not fill.hole:
                    options = [fill.json_schema, *fill.json_schema.get("anyOf", [])]
                    assert any(o.get("enum") for o in options), (issue.message, fill)
