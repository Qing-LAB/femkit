"""A component's contract, a mesh recipe, a material and a component's assignment (geometry.md §§ 3,
6, 7; materials.md §§ 1, 3–5): each part's check, on a copy of a template changed as its person
would change it, through `project check`. That each template passes, and carries each key's help,
is tests/basic/test_templates.py's."""

from __future__ import annotations

import hashlib
from pathlib import Path

from tests import kit
from femkit.core.schema import LENGTH
from femkit.definitions import catalogue
from tests.kit import slab  # noqa: F401 -- a fixture
from femkit.projects import door

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
    sizes = [units.parse(c.strip('"')).value for c in choices]
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


def test_each_parameter_the_script_reads_is_the_projects_and_what_the_contract_declares(slab):
    """Fails if a parameter the script reads that the project does not define is not a finding
    naming the project's parameters, or one that is not what the contract declares it to be is not
    a finding whose right value is what it is; or if one whose own text does not resolve, or any
    while the project file does not load, is a finding on the component (geometry.md § 3: "every
    declared parameter exists in the project and is what it is declared to be"; models.md § 3)."""
    kit.rewrite(slab / "project.toml", 'bias = "1 V"', 'bias = "1 V"\nbroken = "1 furlong"')
    kit.rewrite(slab / COMPONENT, 'height = "length"\n',
                'height = "angle"\ngap = "length"\nbias = "number"\nbroken = "length"\n')
    assert checked(slab) == [
        ("wrong-dimension", COMPONENT, "inputs.parameters.height", '"length"', ()),
        ("no-such-parameter", COMPONENT, "inputs.parameters.gap", None,
         ('"bias"', '"broken"', '"height"', '"interface"', '"length"')),
        ("wrong-dimension", COMPONENT, "inputs.parameters.bias", None, ())]
    kit.rewrite(slab / "project.toml", "[parameters]", "[parameters")
    assert checked(slab) == []


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


def test_a_material_the_project_lacks_is_not_checked_yet_and_a_name_off_the_rule_does_not_load(slab):
    """Fails if a `GLOBAL/` material, or one the project lacks, is other than not checked yet until
    the global library is read, or a material's name that breaks the name rule loads
    (materials.md § 4: "a name the project lacks, and every `GLOBAL/` name, is not checked yet";
    projects.md § 3)."""
    kit.rewrite(slab / COMPONENT, 'material = "dielectric_1"', 'material = "GLOBAL/metals/gold"')
    kit.rewrite(slab / COMPONENT, 'material = "dielectric_2"', 'material = "gold"')
    assert checked(slab) == [(door.UNCHECKED, COMPONENT, "assign.low.material", None, ()),
                             (door.UNCHECKED, COMPONENT, "assign.high.material", None, ())]
    kit.rewrite(slab / COMPONENT, 'material = "gold"', 'material = "GLOBAL/../gold"')
    assert [f[:3] for f in checked(slab)] == [("unloadable", COMPONENT, "assign.high.material")]


def test_a_material_name_close_to_one_the_project_holds_is_a_warning_naming_it(slab):
    """Fails if a material the project lacks whose name is close to one it holds — a misspelling,
    most likely — is not a warning at the assignment's `material` naming the one meant, the
    project's materials its choices; or if one close to none is, rather than not checked yet
    (materials.md § 4: "a name in neither is a finding … with the materials each holds as its
    choices"; core.md § 10)."""
    kit.rewrite(slab / COMPONENT, 'material = "dielectric_2"', 'material = "dielectrc_2"')
    found = kit.run("project.check", project=slab.name).issues
    assert [(i.severity, i.code, i.key, i.choices) for i in found if i.file == COMPONENT] == [
        ("warning", "no-such-material", "assign.high.material", ('"dielectric_1"', '"dielectric_2"'))]
    assert found[0].message.endswith("did you mean `dielectric_2`?")
    kit.rewrite(slab / COMPONENT, 'material = "dielectrc_2"', 'material = "gold"')
    assert [(i.severity, i.code) for i in kit.run("project.check", project=slab.name).issues
            if i.file == COMPONENT] == [("info", door.UNCHECKED)]


def test_a_property_holding_several_datasets_names_the_one_used_and_each_name_is_held(slab):
    """Fails if a property of the assigned material holding several datasets, none named, is not a
    finding naming its datasets; or if a named property or dataset the material does not hold is
    not a finding naming what it holds; or a dataset named and held is (materials.md § 5: "A
    property with several datasets names one; there is no default dataset")."""
    (slab / LOW).write_text((slab / LOW).read_text() + '\n[properties.relative_permittivity.other]\n'
                                   'value = "2"\nconvention = "real"\nsource = "s"\nrange = "all"\n')
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

def test_a_recipes_values_are_each_what_it_is_its_own_numbers_or_expressions_of_parameters(slab):
    """Fails if a recipe's size, or a size on a group, that is no length, a tolerance, growth or
    quality that is no plain number, or a value that does not read is not a finding at its key;
    if an expression of the project's parameters is, or one using a parameter that does not
    resolve; if sizes without a growth, a growth not above 0 or a quality above 1 are not
    (geometry.md § 6; models.md § 3: "One using a parameter that does not resolve does not
    resolve either, and has no finding of its own")."""
    kit.rewrite(slab / "project.toml", 'bias = "1 V"', 'bias = "1 V"\nbroken = "1 furlong"')
    (slab / MESH).write_text('schema = 1\nsize = "length / 4"\norder = 2\ntolerance = "1 m"\nquality = 1.5\n'
                                    '[sizes]\nmiddle = "0.05"\nleft = "0.05 furlong"\nright = "broken / 2"\n'
                                    'sides = "interface / 10"\n')
    assert checked(slab) == [

        ("wrong-dimension", MESH, "sizes.middle", None, ()),
        ("bad-quantity", MESH, "sizes.left", None, ()),
        ("wrong-dimension", MESH, "tolerance", None, ()),
        ("growth-required", MESH, "growth", None, ()),
        ("out-of-range", MESH, "quality", None, ())]
    (slab / MESH).write_text('schema = 1\nsize = "2 V"\norder = 1\ntolerance = 1e-3\ngrowth = "0"\n'
                                    'quality = 1\n[sizes]\nmiddle = "0.05 m"\n')
    assert checked(slab) == [("wrong-dimension", MESH, "size", None, ()),
                             ("out-of-range", MESH, "growth", None, ())]


# ------------------------------------------------------------------ the material

def test_a_materials_properties_are_the_lists_each_value_a_quantity_naming_no_parameter(slab):
    """Fails if a property the property list does not name is not a finding naming the list's; if
    a dataset's value outside its property's dimension, one that does not read, one naming a
    parameter — a material cites nothing — or a range's bound that does not read is not a finding
    at it; or if a range other than `all` or `[from, to]` loads, or its finding is at another key
    than the range's (materials.md § 1: "only the property list names a material property"; § 3;
    § 4: "every value's unit, read by the one unit grammar"; projects.md § 3; core.md § 2)."""
    kit.rewrite(slab / LOW, 'value = "1"', 'value = "1 m"')
    (slab / LOW).write_text((slab / LOW).read_text() + '\n[properties.conductivity.mine]\n'
                            'value = "1"\nconvention = "real"\nsource = "s"\nrange = "all"\n')
    kit.rewrite(slab / HIGH, 'value = "4"', 'value = "4 furlong"')
    assert checked(slab) == [
        ("wrong-dimension", LOW, "properties.relative_permittivity.benchmark.value", None, ()),
        ("no-such-property", LOW, "properties.conductivity", None, ('"relative_permittivity"',)),
        ("bad-quantity", HIGH, "properties.relative_permittivity.benchmark.value", None, ())]
    kit.rewrite(slab / HIGH, 'value = "4 furlong"', 'value = "length / height"')
    kit.rewrite(slab / HIGH, 'range = "all"', 'range = ["400 nm", "800 furlong"]')
    assert [f for f in checked(slab) if f[1] == HIGH] == [
        ("bad-quantity", HIGH, "properties.relative_permittivity.benchmark.value", None, ()),
        ("bad-quantity", HIGH, "properties.relative_permittivity.benchmark.range", None, ())]
    kit.rewrite(slab / HIGH, 'range = ["400 nm", "800 furlong"]', 'range = ["400 nm"]')
    assert [f[:3] for f in checked(slab) if f[1] == HIGH] == [
        ("unloadable", HIGH, "properties.relative_permittivity.benchmark.range")]


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
