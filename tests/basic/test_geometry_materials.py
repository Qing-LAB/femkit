"""A component's contract, a mesh recipe, a material and a component's assignment (geometry.md §§ 3,
6, 7; materials.md §§ 1, 3–5): each part's check, on a copy of a template changed as its person
would change it, through `project check`. That each template passes, and carries each key's help,
is tests/basic/test_templates.py's."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from tests import kit
from femkit.core.persist import read_json
from femkit.core.schema import LENGTH
from femkit.definitions import catalogue
from femkit.projects.addresses import Address
from tests.kit import slab  # noqa: F401 -- a fixture

COMPONENT = "components/slab/component.toml"
MESH = "mesh/uniform.toml"
LOW, HIGH = "materials/dielectric_1/material.toml", "materials/dielectric_2/material.toml"
KINDS = ("component", "mesh", "material")    # the part kinds these checks find on


def checked(slab: Path) -> list[tuple]:
    """Every finding `project check` makes on the project's components, recipes and materials: its
    code, file, key, right value and choices."""
    found = kit.run("project.check", project=slab.name).issues
    return [(i.code, i.file, i.key, i.right, i.choices) for i in found if i.subject.partition(":")[0] in KINDS]


# ------------------------------------------------------------------ the component's contract

def test_a_frames_unit_is_a_unit_of_length(slab):
    """Fails if a frame's unit that is no unit of length — every length handed to the script is
    converted to it — is not a finding at it whose choices are the unit table's lengths, smallest
    first (geometry.md § 3: "Its `unit` is the unit of every number the script writes and of every
    length handed to it"; core.md § 10: "where several would do … they are `choices`")."""
    units = catalogue.units(kit.ctx())
    lengths = units.of(LENGTH)
    kit.rewrite(slab / COMPONENT, 'unit = "m"', 'unit = "V"')
    ((code, file, key, right, choices),) = checked(slab)
    assert (code, file, key, right) == ("not-a-length-unit", COMPONENT, "frame.unit", None)
    assert sorted(choices) == sorted(f'"{u}"' for u in lengths)
    sizes = [units.unit(c.strip('"')).value for c in choices]
    assert sizes == sorted(sizes) and choices.index('"nm"') < choices.index('"m"') < choices.index('"km"')
    kit.rewrite(slab / COMPONENT, 'unit = "V"', 'unit = "2 nm"')
    assert [f[:3] for f in checked(slab)] == [("not-a-length-unit", COMPONENT, "frame.unit")]


def test_an_axisymmetric_physics_needs_its_components_axis_and_only_a_2d_frame_has_one(slab):
    """Fails if a study pairing a physics whose 2-D meaning is axisymmetric with a component whose
    frame states no axis of revolution is not a finding at that frame's key, the axes its choices;
    if one that states it is; or if an axis of revolution in a 3-D frame is not a finding
    (geometry.md § 3: "symmetry = { axis = "y" } — for an axisymmetric 2-D physics: the axis of
    revolution")."""
    kit.rewrite(slab / "physics/electrostatics.toml", '2 = "per unit depth"', '2 = "axisymmetric"')
    assert checked(slab) == [("no-axis", COMPONENT, "frame.symmetry.axis", None, ('"x"', '"y"'))]
    kit.rewrite(slab / COMPONENT, 'unit = "m"\n', 'unit = "m"\n\n[frame.symmetry]\naxis = "y"\n')
    assert checked(slab) == []
    kit.rewrite(slab / COMPONENT, "dimension = 2", "dimension = 3")
    assert ("symmetry-not-2d", COMPONENT, "frame.symmetry", None, ()) in checked(slab)


def test_a_groups_place_is_known_as_far_as_its_dimension_tells_and_none_is_a_finding(slab):
    """Fails if a group promising a dimension no place has in its frame is not a finding naming the
    dimensions that would do; or if a group whose dimension fits is a finding on the component — a
    face's place is said on the study that pairs a condition with it (geometry.md § 7: "Before the
    geometry exists, a group's place is known as far as its promised dimension tells")."""
    assert checked(slab) == []
    kit.rewrite(slab / COMPONENT, "sides = 1\n", "sides = 1\ntip = 3\n")
    assert checked(slab) == [("impossible-dimension", COMPONENT, "groups.tip", None, ("0", "1", "2"))]


def test_a_contract_declares_the_mesh_its_script_writes_at_a_geometry_order_a_recipe_may_have(slab):
    """Fails if a component may not declare that its script meshes too, at geometry order 1 or 2
    as a recipe's — what the pass-through takes on — or declares one at an order no recipe may
    have and loads, rather than being a finding at that key (geometry.md § 3: "`[outputs] mesh = {
    order = N }` says the script meshes too and writes `MESH` at geometry order `N`, 1 or 2 as a
    recipe's")."""
    text = (slab / COMPONENT).read_text()
    assert kit.opened(slab).part(Address("component", "slab")).data.outputs.mesh is None
    (slab / COMPONENT).write_text(text + "\n[outputs.mesh]\norder = 2\n")
    assert checked(slab) == []
    assert kit.opened(slab).part(Address("component", "slab")).data.outputs.mesh.order == 2
    (slab / COMPONENT).write_text(text + "\n[outputs.mesh]\norder = 3\n")
    assert [f[:3] for f in checked(slab)] == [("unloadable", COMPONENT, "outputs.mesh.order")]


DEF = ('[definitions.bias]', '[definitions.broken]\ntype = "float"\nvalue = 1\nunit = "furlong"\n\n[definitions.bias]')


def test_each_definition_the_script_reads_is_the_projects_and_what_the_contract_declares(slab):
    """Fails if a definition the script reads that the project does not define is not a finding
    naming the project's definitions, or one that is not what the contract declares it to be is not
    a finding whose right value is what it is; or if one whose own unit does not read, or any while
    the project file does not load, is a finding on the component (geometry.md § 3: "every declared
    parameter exists in the project and is what it is declared to be"; models.md § 3)."""
    kit.rewrite(slab / "project.toml", *DEF)
    kit.rewrite(slab / COMPONENT, 'height = "length"\n',
                'height = "angle"\ngap = "length"\nbias = "number"\nbroken = "length"\n')
    assert checked(slab) == [
        ("wrong-dimension", COMPONENT, "inputs.definitions.height", '"length"', ()),
        ("no-such-definition", COMPONENT, "inputs.definitions.gap", None,
         ('"bias"', '"broken"', '"height"', '"interface"', '"length"')),
        ("wrong-dimension", COMPONENT, "inputs.definitions.bias", None, ())]
    kit.rewrite(slab / "project.toml", "[definitions]\n", "[definitions\n")
    assert checked(slab) == []


def test_the_definitions_a_script_reads_are_named_definitions_and_parameters_is_no_key(slab):
    """Fails if a contract's `[inputs.definitions]` is not where the definitions its script reads
    are named, or if `[inputs.parameters]` — their name before definitions — still loads, rather
    than being no key with `definitions` meant; one name, no alias (geometry.md § 3; plan § 4, X:
    "the component's `[inputs.parameters]` … named `definitions`")."""
    component = kit.opened(slab).part(Address("component", "slab")).data
    assert component.inputs.definitions == {"length": "length", "height": "length", "interface": "length"}
    kit.rewrite(slab / COMPONENT, "[inputs.definitions]", "[inputs.parameters]")
    (problem,) = [f for f in checked(slab) if f[0] == "unloadable"]
    assert problem[2] == "inputs.parameters" and "definitions" in problem[4]


def test_a_declared_file_whose_digest_differs_is_a_finding_whose_right_value_is_its_digest(slab):
    """Fails if a file the script reads whose SHA-256 is not the one its contract declares is not a
    finding whose right value is the digest it has now, or one whose digest matches is, or one
    not there is besides the door's finding (geometry.md § 3: "a file whose digest differs is a
    finding whose right value is the digest it has now")."""
    folder = slab / "components/slab"
    (folder / "data").mkdir()
    (folder / "profile.csv").write_text("x,y\n0,1\n")
    (folder / "data/same.csv").write_text("x\n")
    same = hashlib.sha256(b"x\n").hexdigest()
    kit.rewrite(slab / COMPONENT, "# [inputs.files]\n", f'[inputs.files]\n"profile.csv" = "{same}"\n"data/same.csv" = '
                                                f'"{same}"\n"gone.csv" = "{same}"\n')
    digest = hashlib.sha256(b"x,y\n0,1\n").hexdigest()
    assert checked(slab) == [("missing-file", COMPONENT, 'inputs.files."gone.csv"', None, ()),
                             ("digest-differs", COMPONENT, 'inputs.files."profile.csv"', f'"{digest}"', ())]


# ------------------------------------------------------------------ the assignment

def test_a_material_fills_a_body_group_the_component_promises(slab):
    """Fails if a material assigned to a face, or to a group the component does not promise, is
    not a finding on the component naming its body groups (materials.md § 5; geometry.md § 7: "a
    material assigned to a face is a finding on the component at once")."""
    kit.rewrite(slab / COMPONENT, "[assign.high]", '[assign.middle]\nmaterial = "dielectric_1"\n\n[assign.void]\n'
                                           'material = "dielectric_1"\n\n[assign.high]')
    assert checked(slab) == [("not-a-body", COMPONENT, "assign.middle", None, ('"high"', '"low"')),
                             ("not-a-body", COMPONENT, "assign.void", None, ('"high"', '"low"'))]


def library_names(slab: Path) -> tuple[str, ...]:
    """The materials the global library at the project's root holds, as an assignment names each
    explicitly: `GLOBAL/<name>` (materials.md § 4)."""
    return tuple(f'"GLOBAL/{p.parent.relative_to(slab.parent / "materials").as_posix()}"'
                 for p in sorted((slab.parent / "materials").rglob("material.toml")))


def on_component(slab: Path) -> list[tuple]:
    """Every finding `project check` makes on the component: its severity, code, key, right value
    and choices, and the operations its next steps run."""
    found = kit.run("project.check", project=slab.name).issues
    return [(i.severity, i.code, i.key, i.right, i.choices, [a.call.operation for a in i.next])
            for i in found if i.file == COMPONENT]


def test_a_material_in_neither_place_is_an_error_whose_choices_are_the_materials_each_holds(slab):
    """Fails if a `GLOBAL/` material the global library lacks, or a name neither the project nor
    the library holds — close to none of theirs — is other than an error `no-such-material` at the
    assignment's `material` key, its choices the materials each holds, the library's as
    `GLOBAL/<name>`; or if, where the projects root has no library yet, the finding does not offer
    the `project new` that makes it, or offers it where the library is there (materials.md § 4:
    "a name in neither is a finding of `project check` on the assignment's `material` key,
    `no-such-material` … with the materials each holds as its choices"; "where the root has no
    library yet, the finding says so, and that the next `project new` makes it")."""
    kit.rewrite(slab / COMPONENT, 'material = "dielectric_1"', 'material = "GLOBAL/metals/gold"')
    kit.rewrite(slab / COMPONENT, 'material = "dielectric_2"', 'material = "gold"')
    choices = ('"dielectric_1"', '"dielectric_2"', *library_names(slab))
    assert on_component(slab) == [("error", "no-such-material", "assign.low.material", None, choices, []),
                                  ("error", "no-such-material", "assign.high.material", None, choices, [])]
    shutil.rmtree(slab.parent / "materials")
    own = ('"dielectric_1"', '"dielectric_2"')
    assert on_component(slab) == [
        ("error", "no-such-material", "assign.low.material", None, own, ["project.new"]),
        ("error", "no-such-material", "assign.high.material", None, own, ["project.new"])]


@pytest.mark.parametrize("name, meant", [("GLOBAL/../gold", '"GLOBAL/gold"'), ("Global/vacuum", '"GLOBAL/vacuum"'),
                                         ("Dielectric 2", '"dielectric_2"'), ("metals//2gold", None)],
                         ids=["a step leaving the folder", "the prefix in other letters", "capitals and a space",
                              "an empty step and a digit first"])
def test_a_material_name_the_name_rule_refuses_is_an_error_whose_right_value_is_the_name_it_meant(slab, name, meant):
    """Fails if a material's name that breaks the name rule makes the component not load — so
    nothing else of it is checked — or is other than one error `bad-name` at the assignment's
    `material`, its right value the name it most likely meant, by the rule, where there is one
    (materials.md § 4: "A name the name rule refuses — `Global/gold` — says what in it breaks the
    rule and the name it most likely meant"; projects.md § 3)."""
    kit.rewrite(slab / COMPONENT, 'material = "dielectric_2"', f'material = "{name}"')
    assert on_component(slab) == [("error", "bad-name", "assign.high.material", meant, (), [])]


def test_a_material_name_close_to_one_either_place_holds_is_an_error_whose_right_value_is_it(slab):
    """Fails if a material name in neither place, close to one the project or the global library
    holds by its whole name or its last step — a misspelling, or a group left out, most likely —
    is not an error at the assignment's `material` whose right value is the one meant, written as
    the assignment would write it, the library's as `GLOBAL/<name>`; or if one close to none has a
    right value rather than the materials each place holds as its choices (materials.md § 4: "did
    you mean" the closest, "by its whole name or its last step, in either place, written as the
    choice would be"; core.md § 10)."""
    (slab.parent / "materials" / "metals" / "gold").mkdir(parents=True)
    shutil.copy(slab.parent / "materials" / "vacuum" / "material.toml", slab.parent / "materials/metals/gold")
    for written, meant in [("dielectrc_2", '"dielectric_2"'), ("GLOBAL/vacum", '"GLOBAL/vacuum"'),
                           ("gold", '"GLOBAL/metals/gold"'), ("GLOBAL/gold", '"GLOBAL/metals/gold"'),
                           ("metal/gold", '"GLOBAL/metals/gold"')]:
        kit.rewrite(slab / COMPONENT, 'material = "dielectric_2"', f'material = "{written}"')
        assert on_component(slab) == [("error", "no-such-material", "assign.high.material", meant, (), [])], written
        kit.rewrite(slab / COMPONENT, f'material = "{written}"', 'material = "dielectric_2"')
    kit.rewrite(slab / COMPONENT, 'material = "dielectric_2"', 'material = "copper"')
    assert on_component(slab) == [("error", "no-such-material", "assign.high.material", None,
                                   ('"dielectric_1"', '"dielectric_2"', *library_names(slab)), [])]


def test_a_property_holding_several_datasets_names_the_one_used_and_each_name_is_held(slab):
    """Fails if a property of the assigned material holding several datasets, none named, is not a
    finding naming its datasets; or if a named property or dataset the material does not hold is
    not a finding naming what it holds; or a dataset named and held is (materials.md § 5: "A
    property with several datasets names one; there is no default dataset")."""
    (slab / LOW).write_text((slab / LOW).read_text() + '\n[properties.relative_permittivity.other]\n'
                                   'value = 2\nconvention = "real"\nsource = "s"\nrange = "all"\n')
    assert checked(slab) == [("dataset-unchosen", COMPONENT, "assign.low.datasets.relative_permittivity",
                                      None, ('"benchmark"', '"other"'))]
    kit.rewrite(slab / COMPONENT, '# datasets = { relative_permittivity = "benchmark" }\n\n[assign.high]',
         'datasets = { relative_permittivity = "missing", conductivity = "x" }\n\n[assign.high]')
    assert checked(slab) == [
        ("no-such-dataset", COMPONENT, "assign.low.datasets.relative_permittivity", None,
                 ('"benchmark"', '"other"')),
        ("no-such-property", COMPONENT, "assign.low.datasets.conductivity", None, ('"relative_permittivity"',))]
    kit.rewrite(slab / COMPONENT, '"missing", conductivity = "x"', '"other"')
    assert checked(slab) == []
    (slab / LOW).write_text("schema = \n")              # its own finding says why; nothing to name
    assert checked(slab) == [("unloadable", LOW, None, None, ())]


# ------------------------------------------------------------------ the mesh recipe

def test_a_recipes_values_are_each_what_it_is_its_own_numbers_or_definitions(slab):
    """Fails if a recipe's size, or a size on a group, that is no length — a plain number among
    them, offered as the length it would be — a tolerance, growth or quality that is no plain
    number, or a value that does not read is not a finding at its key; if a definition's name of
    the right dimension is, or one whose own finding says it does not resolve; if sizes without a
    growth, a growth not above 0 or a quality above 1 are not (geometry.md § 6; core.md § 11;
    projects.md § 6: "nothing for one using a parameter that does not resolve, whose own finding
    says why")."""
    kit.rewrite(slab / "project.toml", *DEF)
    (slab / MESH).write_text('schema = 2\nmesher = "gmsh"\nsize = "length"\norder = 2\ntolerance = {value = 1, unit = "m"}\n'
                             'quality = 1.5\n[sizes]\nmiddle = 0.05\nleft = {value = 0.05, unit = "furlong"}\n'
                             'right = "broken"\nsides = "interface"\n')
    assert checked(slab) == [
        ("wrong-dimension", MESH, "sizes.middle", '{value = 0.05, unit = "m"}', ()),
        ("bad-quantity", MESH, "sizes.left", None, ()),
        ("wrong-dimension", MESH, "tolerance", None, ()),
        ("growth-required", MESH, "growth", None, ()),
        ("out-of-range", MESH, "quality", None, ())]
    (slab / MESH).write_text('schema = 2\nmesher = "gmsh"\nsize = {value = 2, unit = "V"}\norder = 1\ntolerance = 1e-3\ngrowth = 0\n'
                             'quality = 1\n[sizes]\nmiddle = {value = 0.05, unit = "m"}\n')
    assert checked(slab) == [("wrong-dimension", MESH, "size", None, ()),
                             ("out-of-range", MESH, "growth", None, ())]



def test_a_recipes_sizes_and_tolerance_out_of_their_range_are_findings_at_their_keys(slab):
    """Fails if a recipe's size or a size on a group not above 0, or a tolerance below 0, passes
    `project check` — to fail only once the mesh step runs — or is a finding at another key
    (geometry.md § 6: each rule of a recipe's values is the recipe's check's)."""
    (slab / MESH).write_text('schema = 2\nmesher = "gmsh"\nsize = {value = 0, unit = "m"}\norder = 1\ntolerance = -1\ngrowth = 0.5\n'
                             '[sizes]\nleft = {value = -0.02, unit = "m"}\nright = {value = 0.02, unit = "m"}\n')
    assert checked(slab) == [("out-of-range", MESH, "size", None, ()),
                             ("out-of-range", MESH, "sizes.left", None, ()),
                             ("out-of-range", MESH, "tolerance", None, ())]
    (slab / MESH).write_text('schema = 2\nmesher = "gmsh"\nsize = {value = 0.1, unit = "m"}\norder = 1\ntolerance = 0\n')
    assert checked(slab) == []


# ------------------------------------------------------------------ the stages' documents and the mesh's check

RECIPE = {"dimension": 2, "groups": {"domain": 2, "left": 1}, "size": 0.1, "order": 1, "tolerance": 1e-9,
          "growth": None, "quality": None, "sizes": {}}


@pytest.mark.parametrize("document, wrong", [
    ({k: v for k, v in RECIPE.items() if k != "sizes"}, "recipe lacks sizes"),
    (RECIPE | {"mesher": "gmsh"}, "recipe holds mesher, no key of it"),
    (RECIPE | {"size": "0.1 m"}, "recipe.size is a text, not a finite number"),
    (RECIPE | {"sizes": {"left": True}}, "recipe.sizes.left is true or false, not a finite number"),
    (RECIPE | {"groups": {"domain": 2.0}}, "recipe.groups.domain is a number, not a whole number"),
    (RECIPE | {"quality": float("nan")}, "recipe.quality is a number, not a finite number or null"),
], ids=["a key missing", "a key of no shape", "a length as text", "a flag for a size", "a dimension not whole",
        "no number"])
def test_a_stage_document_not_of_its_shape_is_refused_naming_where(document, wrong):
    """Fails if a stage's document — here the mesh stage's recipe — that lacks a key, holds one its
    shape has not, or a value of another kind is built or read as if it were whole, or the refusal
    does not say where (models.md § 9.1: each document crossing into an environment defined once,
    with its schema number)."""
    import re
    from femkit.engines.stages import documents
    with pytest.raises(documents.Malformed, match=re.escape(wrong)):
        documents.make("recipe", **document)
    with pytest.raises(documents.Malformed, match="schema"):
        documents.check("recipe", {"schema": 2, **RECIPE})
    assert documents.make("recipe", **RECIPE) == {"schema": 1, **RECIPE}


def test_a_stage_document_of_an_earlier_shape_is_refused_saying_what_it_is_and_what_changed():
    """Fails if the script's inputs — whose shape changed, `definitions` in place of `parameters` —
    are not written under their raised schema, or one of the earlier schema is read, or refused
    without saying what it is: the schema it states, the one read, and what changed between them
    (models.md § 2: "Every file carries its shape ... a finding naming the shape the file states,
    the shape femkit reads, and what changed between them"; geometry.md § 2)."""
    from femkit.engines.stages import documents
    assert documents.make("inputs", definitions={"side": 1.0}) == {"schema": 2, "definitions": {"side": 1.0}}
    with pytest.raises(documents.Malformed) as caught:
        documents.check("inputs", {"schema": 1, "parameters": {"side": 1.0}})
    said = str(caught.value)
    assert "schema 1" in said and "schema 2" in said and "`definitions` in place of `parameters`" in said


# The region map of a mesh like its geometry: every promised group, its measure within the
# recipe's tolerance, no element inverted — femkit's own document, as a mesher writes it.
REGIONS = {"dimension": 2, "order": 1, "groups": {
    "domain": {"dimension": 2, "elements": 32, "measure": 1.0, "geometry": 1.0, "difference": 0.0, "quality": 0.7},
    "left": {"dimension": 1, "elements": 4, "measure": 1.0, "geometry": 1.0, "difference": 0.0, "quality": None}}}
LEFT_OFF = {"elements": 4, "measure": 1.1, "geometry": 1.0, "difference": 0.1}


def mesh_check(work: Path, regions: dict, recipe: dict = RECIPE, mesh: bool = True):
    """The mesh stage's check run in ``work`` on ``regions``, as a run holds it — the program and
    the modules beside it copied in — on the python running the tests, since it imports the
    standard library alone (framework.md § 1): its result, its verdict and its outputs' record."""
    import json
    import subprocess
    import sys
    from femkit.engines.stages import documents
    programs = kit.files().programs_folder
    (work / "recipe.json").write_text(json.dumps(documents.make("recipe", **recipe)))
    (work / "regions.json").write_text(json.dumps({"schema": 1, **regions}))
    if mesh:
        (work / "mesh.msh").write_bytes(b"the mesher's mesh, which the check records and never reads\n")
    result = subprocess.run([sys.executable, kit.program(programs() / "check_mesh.py", work), "recipe.json",
                             "regions.json", "checked.json", "outputs.json", "mesh.msh"],
                            cwd=work, capture_output=True, text=True)
    outputs = work / "outputs.json"
    return result, read_json(work / "checked.json"), read_json(outputs) if outputs.exists() else None


def test_the_mesh_check_passes_a_mesh_like_its_geometry_and_records_its_outputs(tmp_path):
    """Fails if the one check of every mesher's mesh refuses a region map holding every promised
    group, measured like the geometry within the recipe's tolerance, with no element inverted; or
    passes without its verdict, `passed`, and the SHA-256 of the region map and the mesh, by their
    paths as given — what a later stage's launch checks what it shares against (geometry.md § 5;
    jobs.md § 2)."""
    result, verdict, outputs = mesh_check(tmp_path, REGIONS)
    assert result.returncode == 0, result.stderr
    assert verdict == {"schema": 1, "passed": True, "reason": None}
    assert outputs == {"schema": 1, "files": {f: hashlib.sha256((tmp_path / f).read_bytes()).hexdigest()
                                              for f in ("regions.json", "mesh.msh")}}


@pytest.mark.parametrize("change, recipe, said", [
    ({"left": None}, {}, "`left` is promised and not in the mesh"),
    ({"left": REGIONS["groups"]["left"] | {"dimension": 0}}, {},
     "`left` is a group of dimension 0 in the mesh; its contract promises 1"),
    ({"left": REGIONS["groups"]["left"] | {"elements": 0}}, {}, "`left` holds no element of the mesh"),
    ({"left": REGIONS["groups"]["left"] | LEFT_OFF}, {}, "`left` measures 1.1 in the mesh against 1 in the geometry, "
                                                         "1.00e-01 apart, beyond the recipe's tolerance 1e-09"),
    ({"domain": REGIONS["groups"]["domain"] | {"quality": 0.1}}, {"quality": 0.2},
     "`domain` holds an element of quality 0.1, below the recipe's 0.2"),
    ({"domain": REGIONS["groups"]["domain"] | {"quality": -0.5}}, {},
     "`domain` holds an inverted element, of quality -0.5"),
], ids=["a group missing", "a group at another dimension", "a group holding nothing", "a measure beyond the tolerance",
        "an element below the quality", "an inverted element"])
def test_the_mesh_check_refuses_a_mesh_unlike_its_geometry_naming_the_group(tmp_path, change, recipe, said):
    """Fails if the one check of every mesher's mesh passes a region map missing a promised group,
    holding it at another dimension or empty, measuring it beyond the recipe's tolerance from the
    geometry, or holding an element below the recipe's quality — or, with none stated, an inverted
    one; or fails without naming the group in its verdict and its last line, or records outputs
    (geometry.md § 5; jobs.md § 2: "passed, or failed with its reason")."""
    groups = {n: g for n, g in (REGIONS["groups"] | change).items() if g is not None}
    result, verdict, outputs = mesh_check(tmp_path, REGIONS | {"groups": groups}, RECIPE | recipe)
    assert result.returncode == 1 and result.stderr.splitlines()[-1] == said
    assert verdict == {"schema": 1, "passed": False, "reason": said} and outputs is None


def test_the_mesh_check_refuses_a_mesh_that_is_not_there_or_a_region_map_not_of_its_shape(tmp_path):
    """Fails if the mesh check passes when the mesher wrote no mesh, or reads a region map not of
    its shape as if it were whole, or ends either without a verdict saying why (geometry.md § 5;
    jobs.md § 5.2: a check stated and no `checked.json` reads as stopped before its verdict)."""
    result, verdict, _ = mesh_check(tmp_path, REGIONS, mesh=False)
    assert result.returncode == 1 and verdict["reason"] == "the mesher wrote no mesh.msh"
    result, verdict, _ = mesh_check(tmp_path, REGIONS | {"order": "1"})
    assert result.returncode == 2 and verdict["passed"] is False and "regions.order is a text" in verdict["reason"]


# ------------------------------------------------------------------ the material

def test_a_materials_properties_are_the_lists_each_value_a_quantity_naming_no_parameter(slab):
    """Fails if a property the property list does not name is not a finding naming the list's; if
    a dataset's value outside its property's dimension, one that does not read, one naming a
    definition — a material cites nothing — or a range whose unit does not read is not a finding
    at it; or if a range of other than two bounds under one unit passes, or its finding is at
    another key than the range's (materials.md § 1: "only the property list names a material
    property"; § 3; § 4: "every value's unit, read by the one unit grammar"; projects.md § 3;
    core.md §§ 2, 11)."""
    kit.rewrite(slab / LOW, "value = 1", 'value = {value = 1, unit = "m"}')
    (slab / LOW).write_text((slab / LOW).read_text() + '\n[properties.conductivity.mine]\n'
                            'value = 1\nconvention = "real"\nsource = "s"\nrange = "all"\n')
    kit.rewrite(slab / HIGH, "value = 4", 'value = {value = 4, unit = "furlong"}')
    assert checked(slab) == [
        ("wrong-dimension", LOW, "properties.relative_permittivity.benchmark.value", None, ()),
        ("no-such-property", LOW, "properties.conductivity", None, ('"refractive_index"', '"relative_permittivity"')),
        ("bad-quantity", HIGH, "properties.relative_permittivity.benchmark.value", None, ())]
    kit.rewrite(slab / HIGH, 'value = {value = 4, unit = "furlong"}', 'value = "length"')
    kit.rewrite(slab / HIGH, 'range = "all"', 'range = {value = [400, 800], unit = "furlong"}')
    assert [f for f in checked(slab) if f[1] == HIGH] == [
        ("bad-quantity", HIGH, "properties.relative_permittivity.benchmark.value", None, ()),
        ("bad-quantity", HIGH, "properties.relative_permittivity.benchmark.range", None, ())]
    kit.rewrite(slab / HIGH, 'range = {value = [400, 800], unit = "furlong"}', 'range = {value = [400], unit = "nm"}')
    assert [f[:3] for f in checked(slab) if f[1] == HIGH] == [
        ("bad-quantity", HIGH, "properties.relative_permittivity.benchmark.value"),
        ("bad-quantity", HIGH, "properties.relative_permittivity.benchmark.range")]


def test_a_dataset_missing_a_stated_field_is_a_finding_at_that_fields_key(slab):
    """Fails if a dataset that does not state its convention, its source or its range is not a
    finding at each missing key (materials.md § 3: "These are `stated` fields: a dataset being
    written may lack them, a finding of `project check`")."""
    for line in ('convention = "real"\n', 'range = "all"\n'):
        kit.rewrite(slab / HIGH, line, "")
    kit.rewrite(slab / HIGH, 'source = "the two-material', '# source = "the two-material')
    assert checked(slab) == [
        *[("not-stated", HIGH, f"properties.relative_permittivity.benchmark.{key}", None, ())
          for key in ("convention", "source", "range")]]


def test_a_material_may_state_its_formula_and_the_names_a_library_search_finds_it_by(slab):
    """Fails if a material stating `formula` and `aliases`, as materials.md § 3 writes them, does
    not load, or if either is a finding (materials.md § 3: `formula = "Au"`, `aliases = ["Au"]`)."""
    kit.rewrite(slab / LOW, 'display = "Dielectric 1"', 'display = "Dielectric 1"\nformula = "SiO2"\n'
                                                       'aliases = ["silica", "quartz glass"]')
    assert checked(slab) == []
