"""A dataset's three forms and the lists they rest on (materials.md §§ 1–3, 6; models.md § 4.2):
the variables and dispersion models of `femkit/data/dispersion.toml`, the step kinds of
`femkit/data/step_kinds.toml` and the property list, each refused at load when it misstates
itself; a value, a table or a model checked by `project check`, each finding at its key; a
dataset held under an equivalent form answering the property a formulation reads; and a
stationary step refusing a dataset that varies. On copies of the two-material template, changed
as their person would change them, and on the test's own copy of the definitions."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import pytest

from tests import kit
from tests.kit import slab  # noqa: F401 -- a fixture
from femkit.core.errors import Refused
from femkit.core.persist import write_toml
from femkit.core.schema import DefinitionError
from femkit.definitions import catalogue
from femkit.definitions.dispersion import CONDITIONS

COMPONENT = "components/slab/component.toml"
HIGH = "materials/dielectric_2/material.toml"
GLASS = "materials/glass/material.toml"
STUDY = "studies/benchmark.toml"
ROWS = "wavelength,n,k\n0.5,1.5,0\n0.6,1.4,0.1\n"
VARIABLES = ('"wavelength"', '"frequency"', '"photon_energy"', '"temperature"')   # the permittivity's, in order


def checked(slab: Path, *files: str) -> list[tuple]:
    """Every finding `project check` makes on ``files``: its code, file, key, right value and choices."""
    return [(i.code, i.file, i.key, i.right, i.choices) for i in kit.run("project.check", project=slab.name).issues
            if i.file in files]


def glass(slab: Path, datasets: str, **files: str) -> None:
    """The project's own material `glass`, unassigned: ``datasets`` as its file writes them, and
    each file beside it."""
    folder = slab / "materials/glass"
    folder.mkdir(exist_ok=True)
    (folder / "material.toml").write_text('schema = 1\ndisplay = "Glass"\n\n' + datasets)
    for name, text in files.items():
        (folder / name.replace("_", ".")).write_text(text)


def named(slab: Path, dataset: str) -> None:
    """The slab's `high` body assigned its material's permittivity ``dataset`` by name."""
    kit.rewrite(slab / COMPONENT, 'material = "dielectric_2"\n# for each property whose material holds several '
                                  'datasets, the one used, by its name\n# datasets = { relative_permittivity = '
                                  '"benchmark" }', f'material = "dielectric_2"\ndatasets = {{ relative_permittivity = '
                                                  f'"{dataset}" }}')


def a_table(rows: str = ROWS, prop: str = "refractive_index", name: str = "measured",
            range_: str = '{value = [0.5, 0.6], unit = "um"}', convention: str = "exp(-iwt)") -> str:
    """A table dataset of ``prop`` in µm, its file `measured.csv` holding ``rows``."""
    return (f'[properties.{prop}.{name}]\ntable = "measured.csv"\nsha256 = "{hashlib.sha256(rows.encode()).hexdigest()}"\n'
            f'variable = {{ name = "wavelength", unit = "um" }}\ninterpolation = "linear"\nconvention = "{convention}"\n'
            f'source = "a test\'s own"\nrange = {range_}\n\n')


MALITSON = ('[properties.relative_permittivity.malitson]\nmodel = "sellmeier"\nconvention = "real"\n'
            'source = "I. H. Malitson, J. Opt. Soc. Am. 55, 1205 (1965), doi:10.1364/JOSA.55.001205"\n'
            'range = {value = [0.21, 3.71], unit = "um"}\n\n'
            '[properties.relative_permittivity.malitson.parameters]\nA = 0\n\n'
            '[[properties.relative_permittivity.malitson.parameters.terms]]\nB = 0.6961663\n'
            'C = {value = 0.0684043, unit = "um"}\n\n'
            '[[properties.relative_permittivity.malitson.parameters.terms]]\nB = 0.4079426\n'
            'C = {value = 0.01351206307396, unit = "um^2"}\n\n'
            '[[properties.relative_permittivity.malitson.parameters.terms]]\nB = 0.8974794\n'
            'C = {value = 9.896161, unit = "um"}\n\n')
AT = "properties.refractive_index.measured"
MODEL = "properties.relative_permittivity.malitson"


# ------------------------------------------------------------------ the lists, at load

def _changed(definitions: Path, file: str, keys: tuple, value) -> Path:
    path = definitions / file
    data = tomllib.loads(path.read_text())
    held = data
    for key in keys[:-1]:
        held = held[key]
    held[keys[-1]] = value
    write_toml(path, data)
    return path


@pytest.mark.parametrize("keys, value, at", [
    (("models", "sellmeier", "variable"), "colour", "models.sellmeier.variable"),
    (("models", "sellmeier", "gives"), "conductivity", "models.sellmeier.gives"),
    (("models", "sellmeier", "section"), "9-nowhere", "models.sellmeier.section"),
    (("variables", "wavelength", "unit"), "s", "variables.wavelength.unit"),
    (("variables", "photon_energy", "spectral", "constant"), "boltzmann", "variables.photon_energy.spectral.constant"),
    (("models", "drude_lorentz", "parameters", "plasma", "units"), ["furlong"],
     "models.drude_lorentz.parameters.plasma.units[0]"),
    (("models", "drude_lorentz", "parameters", "plasma"), {"description": "E_p", "units": ["eV"]},
     "models.drude_lorentz.parameters.plasma"),                     # a missing key is said at its table (core.md § 2)
    (("models", "drude_lorentz", "sums", "oscillators", "parameters", "gamma", "sign"), "small",
     "models.drude_lorentz.sums.oscillators.parameters.gamma.sign"),
], ids=["a model's variable not on the list", "a model giving no property of the list", "a formula's section missing",
        "a spectral unit its relation does not give", "a spectral constant not declared", "a unit the table does not read",
        "a parameter with no sign", "a sign not of the list"])
def test_a_dispersion_list_that_misstates_itself_does_not_load(definitions, keys, value, at):
    """Fails if dispersion.toml loads with a model written in no listed variable, giving no
    property of the list, or pointing to a section its science document lacks; a spectral
    variable whose unit is not of the dimension its relation to the frequency gives it, or that
    names no declared constant; a unit the unit table does not read; or a parameter declaring no
    sign, or one none of the signs (materials.md § 2: "a closed list … its parameters with their
    dimensions and their signs … the section of material-data.md that states it")."""
    path = _changed(definitions, "dispersion.toml", keys, value)
    with kit.refused(DefinitionError, "definition-invalid", str(path)) as caught:
        catalogue.load_dispersion()
    assert at in [where for where, _ in caught.value.problems], caught.value.problems


def test_a_dispersion_list_without_a_variable_for_a_condition_a_dataset_states_does_not_load(definitions):
    """Fails if dispersion.toml loads without a variable for each condition a dataset states —
    `CONDITIONS`, the one declaration a dataset's fields and an importer's conditions are made
    from — so that a dataset's `temperature` would be read in no declared unit (materials.md §§ 2,
    3: "the `temperature` its data holds at")."""
    path = definitions / "dispersion.toml"
    data = tomllib.loads(path.read_text())
    for name in CONDITIONS:
        del data["variables"][name]
    write_toml(path, data)
    with kit.refused(DefinitionError, "definition-invalid", str(path)) as caught:
        catalogue.load_dispersion()
    assert "variables" in [where for where, _ in caught.value.problems], caught.value.problems


def test_a_property_or_a_step_kind_naming_no_variable_and_a_formulation_naming_no_kind_do_not_load(definitions):
    """Fails if the property list loads with a `depends_on` naming no variable of dispersion.toml,
    the step kinds with a `supplies` naming none, or a formulation with a kind the step kinds do
    not declare (materials.md § 1: "`depends_on` names the variables (§ 2)"; models.md § 4.2: "Both
    lists are closed: what is not declared is refused")."""
    _changed(definitions, "formulations/electrostatics.toml", ("kinds",), ["stationary", "frequency"])
    with pytest.raises(catalogue.CatalogueError) as caught:
        catalogue.load_formulations()
    assert [where for e in caught.value.errors for where, _ in e.problems] == ["kinds[1]"]
    path = _changed(definitions, "properties.toml", ("relative_permittivity", "depends_on"), ["colour"])
    with kit.refused(DefinitionError, "definition-invalid", str(path)) as caught:
        catalogue.load_properties()
    assert [where for where, _ in caught.value.problems] == ["relative_permittivity.depends_on[0]"]
    path = _changed(definitions, "step_kinds.toml", ("stationary", "supplies"), ["time"])
    with kit.refused(DefinitionError, "definition-invalid", str(path)) as caught:
        catalogue.load_step_kinds()
    assert [where for where, _ in caught.value.problems] == ["stationary.supplies[0]"]


# ------------------------------------------------------------------ a dataset's form

@pytest.mark.parametrize("dataset", [
    'value = 2\ntable = "measured.csv"\nconvention = "real"\nsource = "s"\nrange = "all"\n',
    'convention = "real"\nsource = "s"\nrange = "all"\n',
], ids=["two forms", "none"])
def test_a_dataset_is_exactly_one_of_a_value_a_table_and_a_model(slab, dataset):
    """Fails if a dataset stating two of `value`, `table` and `model`, or none, loads, or is a
    finding at another key than the dataset's (materials.md § 3: "A dataset is exactly one of")."""
    glass(slab, "[properties.relative_permittivity.mine]\n" + dataset)
    assert [f[:3] for f in checked(slab, GLASS)] == [
        ("unloadable", GLASS, "properties.relative_permittivity.mine")]


def test_a_table_is_its_file_with_its_digest_its_variable_and_a_range_within_its_rows(slab):
    """Fails if a table that states its file, digest, variable and range rightly is a finding; or
    if one without its `sha256`, or with another, is not a finding at `sha256` whose right value
    is the file's digest; its file not there not one at `table`; a variable its property does not
    vary with not one at `variable.name` naming its property's; a unit not of its variable's
    dimension not one at `variable.unit` naming the units that are; a range reaching beyond its
    first and last rows, or given in no form of its variable, not one at `range` — while one
    given in another form of it, inside them, is none (materials.md § 3)."""
    digest = f'"{hashlib.sha256(ROWS.encode()).hexdigest()}"'
    glass(slab, a_table(), measured_csv=ROWS)
    assert checked(slab, GLASS) == []
    glass(slab, a_table().replace(f"sha256 = {digest}\n", ""))
    assert checked(slab, GLASS) == [("not-stated", GLASS, f"{AT}.sha256", digest, ())]
    glass(slab, a_table().replace(digest, f'"{"0" * 64}"'))
    assert checked(slab, GLASS) == [("digest-differs", GLASS, f"{AT}.sha256", digest, ())]
    glass(slab, a_table(range_='{value = [0.45, 0.6], unit = "um"}'))
    assert checked(slab, GLASS) == [("outside-table", GLASS, f"{AT}.range", None, ())]
    glass(slab, a_table(range_='{value = [2.1, 2.4], unit = "eV"}'))
    assert checked(slab, GLASS) == []
    glass(slab, a_table(range_='{value = [300, 400], unit = "K"}'))
    assert checked(slab, GLASS) == [("wrong-dimension", GLASS, f"{AT}.range", None, ())]
    glass(slab, a_table().replace('name = "wavelength"', 'name = "colour"'))
    assert checked(slab, GLASS) == [("no-such-variable", GLASS, f"{AT}.variable.name", None, VARIABLES)]
    glass(slab, a_table().replace('unit = "um"', 'unit = "eV"'))
    ((code, file, key, right, choices),) = checked(slab, GLASS)
    assert (code, key) == ("wrong-dimension", f"{AT}.variable.unit") and '"um"' in choices and '"eV"' not in choices
    (slab / "materials/glass/measured.csv").unlink()
    glass(slab, a_table())
    assert [f[:3] for f in checked(slab, GLASS)] == [("missing-file", GLASS, f"{AT}.table")]


@pytest.mark.parametrize("rows, convention", [
    ("wavelength,n,k\n0.6,1.4,0.1\n0.5,1.5,0\n", "exp(-iwt)"),
    ("wavelength,n,k\n0.5,1.5,0\n0.6,1.4,0.1\n", "real"),
    ("wavelength,n,k\n0.5,1.5,0\n0.6,1.4,1/10\n", "exp(-iwt)"),
    ("0.5,1.5,0\n0.6,1.4,0.1\n", "exp(-iwt)"),
], ids=["the variable decreasing", "3 columns of real data", "a fraction", "a first row of numbers"])
def test_a_table_file_of_another_shape_is_a_finding_at_its_table(slab, rows, convention):
    """Fails if a table's file whose variable does not increase, whose columns do not fit its
    convention, which holds a value that is no decimal number, or whose first row holds numbers —
    its point lost as the columns' names — is not a finding at `table` (materials.md § 3: "A table
    whose file is … not of the shape above is a finding at `table`"; "a first row of numbers is a
    finding")."""
    glass(slab, a_table(rows, convention=convention), measured_csv=rows)
    assert checked(slab, GLASS) == [("bad-table", GLASS, f"{AT}.table", None, ())]


def test_a_tables_shape_is_found_before_its_digest(slab):
    """Fails if a table whose file does not read, and whose SHA-256 is not the one stated, is a
    finding at `sha256` — offering the digest of a file still to change — rather than at `table`
    alone; or if, once the file reads — blank lines at its end ignored — its digest is not then
    the finding, the file's digest its right value (materials.md § 3: "a table's shape before its
    digest, so the digest offered is that of a table that reads")."""
    glass(slab, a_table(), measured_csv="0.5,1.5,0\n0.6,1.4,0.1\n")
    assert checked(slab, GLASS) == [("bad-table", GLASS, f"{AT}.table", None, ())]
    fixed = ROWS + "\n\n"
    (slab / "materials/glass/measured.csv").write_text(fixed)
    assert checked(slab, GLASS) == [("digest-differs", GLASS, f"{AT}.sha256",
                                     f'"{hashlib.sha256(fixed.encode()).hexdigest()}"', ())]


@pytest.mark.parametrize("range_, code, right", [
    ('"all"', "outside-table", None),
    ('{value = [0.6, 0.5], unit = "um"}', "range-reversed", None),
    ('{value = [2.4, 2.1], unit = "eV"}', "range-reversed", None),
    ('{value = [0.5, 0.6], unit = "1"}', "wrong-dimension", '{value = [0.5, 0.6], unit = "um"}'),
], ids=["all", "reversed", "reversed in another form", "no unit"])
def test_a_tables_range_runs_from_below_to_within_its_rows(slab, range_, code, right):
    """Fails if a table's range of `all` — which a table never holds, being never extrapolated —
    one whose first bound is not below its second, in the form it is written in, or one with no
    unit is not a finding at `range` with its code — the range in its table's unit its right value
    (materials.md § 3: "A table's range is `[from, to]`, from below to, within its first and last
    rows — `all`, or a range beyond them, is a finding at `range`")."""
    glass(slab, a_table(range_=range_), measured_csv=ROWS)
    assert checked(slab, GLASS) == [(code, GLASS, f"{AT}.range", right, ())]


def test_a_table_row_whose_loss_gives_energy_is_a_finding_at_its_table(slab):
    """Fails if a refractive-index table under exp(-iwt) holding a row whose kappa is negative —
    or one under exp(+iwt) whose imaginary part is positive — is not a finding at `table`,
    `active`, while the same rows under the other convention are none (materials.md § 3, "Passive
    data": "a table's row … is a finding, naming the row"; material-data.md §§ 2, 3)."""
    gives = "wavelength,n,k\n0.5,1.5,0\n0.6,1.4,-0.1\n"
    glass(slab, a_table(gives), measured_csv=gives)
    assert checked(slab, GLASS) == [("active", GLASS, f"{AT}.table", None, ())]
    glass(slab, a_table(gives, convention="exp(+iwt)"), measured_csv=gives)
    assert checked(slab, GLASS) == []
    glass(slab, a_table(convention="exp(+iwt)"), measured_csv=ROWS)
    assert checked(slab, GLASS) == [("active", GLASS, f"{AT}.table", None, ())]


DRUDE = ('[properties.relative_permittivity.metal]\nmodel = "drude_lorentz"\nconvention = "exp(-iwt)"\nsource = "s"\n'
         'range = "all"\n\n[properties.relative_permittivity.metal.parameters]\neps_inf = 1\n'
         'plasma = {value = 9, unit = "eV"}\nf0 = 1\ngamma0 = {value = 0.05, unit = "eV"}\n\n'
         '[[properties.relative_permittivity.metal.parameters.oscillators]]\nf = 0.5\n'
         'energy = {value = 2, unit = "eV"}\ngamma = {value = 0.25, unit = "eV"}\n')
METAL = "properties.relative_permittivity.metal.parameters"


@pytest.mark.parametrize("old, new, at, code, right", [
    ('gamma0 = {value = 0.05, unit = "eV"}', 'gamma0 = {value = -0.05, unit = "eV"}', "gamma0", "wrong-sign", None),
    ("f = 0.5", "f = -0.5", "oscillators", "wrong-sign", None),
    ('plasma = {value = 9, unit = "eV"}', 'plasma = {value = 0, unit = "eV"}', "plasma", "wrong-sign", None),
    ('energy = {value = 2, unit = "eV"}', 'energy = {value = -2, unit = "eV"}', "oscillators", "wrong-sign", None),
    ('plasma = {value = 9, unit = "eV"}', "plasma = 14.98", "plasma", "wrong-dimension",
     '{value = 14.98, unit = "eV"}'),
], ids=["a negative damping", "an oscillator's negative strength", "a plasma energy of zero",
        "a negative resonance energy", "a plasma energy with no unit"])
def test_a_models_parameter_is_of_the_sign_and_dimension_its_model_declares(slab, old, new, at, code, right):
    """Fails if a `drude_lorentz` model with positive parameters is a finding; or if one with a
    negative damping, an oscillator's negative strength, a plasma energy of zero, a negative
    resonance energy, or a plasma energy with no unit, is not a finding at its parameter's key — a
    term's at its list's — with its code (materials.md § 3: "each a quantity in its declared
    dimension and of its declared sign"; "a model's negative damping — is a finding, naming … the
    parameter"; material-data.md § 6.2)."""
    glass(slab, DRUDE)
    assert checked(slab, GLASS) == []
    glass(slab, DRUDE.replace(old, new))
    assert checked(slab, GLASS) == [(code, GLASS, f"{METAL}.{at}", right, ())]


def test_a_parameters_sign_is_its_declaration(definitions, tmp_path):
    """Fails if the sign a model's parameter must have is anything but its declaration in
    dispersion.toml: declared of any sign, a negative damping is no finding; declared positive,
    Sellmeier's A of zero is one (materials.md § 2: the models' "parameters with their dimensions
    and their signs", declared as data)."""
    _changed(definitions, "dispersion.toml", ("models", "drude_lorentz", "parameters", "gamma0", "sign"), "any")
    _changed(definitions, "dispersion.toml", ("models", "sellmeier", "parameters", "A", "sign"), "positive")
    slab = kit.copy_template(tmp_path / "projects", "two_material", "slab")
    glass(slab, DRUDE.replace('gamma0 = {value = 0.05, unit = "eV"}', 'gamma0 = {value = -0.05, unit = "eV"}'))
    assert checked(slab, GLASS) == []
    glass(slab, MALITSON)
    assert checked(slab, GLASS) == [("wrong-sign", GLASS, f"{MODEL}.parameters.A", None, ())]


def test_a_model_is_one_of_the_list_with_its_parameters_in_their_dimensions_and_its_convention(slab):
    """Fails if Malitson's silica as a `sellmeier` model — its poles stated as wavelengths and as
    a square — is a finding; or if a model the list lacks, or one giving another property, is not
    a finding at `model` naming the models that give it; a parameter missing, one the model lacks,
    or one outside its dimensions not one at its key; or a convention other than its model's not
    one at `convention` whose right value is the model's (materials.md §§ 2, 3: "A model's dataset
    states the convention its model is written in, and another is a finding naming the
    model's")."""
    glass(slab, MALITSON)
    assert checked(slab, GLASS) == []
    glass(slab, MALITSON.replace('model = "sellmeier"', 'model = "cauchy"'))
    assert checked(slab, GLASS) == [("no-such-model", GLASS, f"{MODEL}.model", None,
                                     ('"drude_lorentz"', '"sellmeier"'))]
    glass(slab, MALITSON.replace("relative_permittivity", "refractive_index"))
    assert checked(slab, GLASS) == [
        ("no-such-model", GLASS, "properties.refractive_index.malitson.model", None, ())]
    glass(slab, MALITSON.replace('convention = "real"', 'convention = "exp(-iwt)"'))
    assert checked(slab, GLASS) == [("wrong-convention", GLASS, f"{MODEL}.convention", '"real"', ())]
    glass(slab, MALITSON.replace("A = 0\n", "D = 0\n").replace('C = {value = 9.896161, unit = "um"}',
                                                                'C = {value = 9.896161, unit = "eV"}'))
    assert checked(slab, GLASS) == [
        ("no-such-parameter", GLASS, f"{MODEL}.parameters.D", None, ('"A"', '"terms"')),
        ("wrong-dimension", GLASS, f"{MODEL}.parameters.terms", None, ()),
        ("parameter-missing", GLASS, f"{MODEL}.parameters.A", None, ())]


def test_one_dataset_name_under_a_property_and_under_its_equivalent_form_is_a_finding_naming_both(slab):
    """Fails if a material holding one dataset's name under `relative_permittivity` and under its
    equivalent form `refractive_index` is not a finding on the material at the form's dataset
    (materials.md § 1: "one name held under both the property and an equivalent is a finding on
    the material, naming both")."""
    glass(slab, a_table(name="same") + '[properties.relative_permittivity.same]\nvalue = 2\nconvention = "real"\n'
                                       'source = "s"\nrange = "all"\n', measured_csv=ROWS)
    assert checked(slab, GLASS) == [("dataset-twice", GLASS, "properties.refractive_index.same", None, ())]


# ------------------------------------------------------------------ an equivalent form answers its property

def _one(slab: Path, dataset: str, **files: str) -> None:
    """The two-material benchmark's second material, filling `high`, holding ``dataset`` alone, and
    each file beside it."""
    (slab / HIGH).write_text('schema = 1\ndisplay = "Dielectric 2"\n\n' + dataset)
    for name, held in files.items():
        (slab / "materials/dielectric_2" / name.replace("_", ".")).write_text(held)


FORM = ('[properties.refractive_index.johnson]\nvalue = 2\nconvention = "real"\nsource = "a test\'s own"\n'
        'range = "all"\n')


def test_a_material_holding_only_an_equivalent_form_provides_the_property_read(slab):
    """Fails if a material holding a formulation's property only under its equivalent form is
    found missing it, or a material holding neither is not; or if `study prep` takes the form's
    data as the property's before a case converts it (materials.md § 1: "a formulation reading
    `relative_permittivity` takes a dataset held under an equivalent"; § 6)."""
    _one(slab, FORM)
    found = kit.run("project.check", project=slab.name).issues
    assert [(i.code, i.file, i.key) for i in found if i.severity == "error"] == [
        ("form-unconverted", COMPONENT, "assign.high.datasets.relative_permittivity")]
    with kit.refused(Refused, "has-findings", "component:slab"):
        kit.apply("study.prep", project=slab.name, study="benchmark")
    _one(slab, "")
    assert checked(slab, HIGH) == [("property-missing", HIGH, "properties.relative_permittivity", None, ())]


def test_an_assignment_names_a_dataset_held_under_an_equivalent_form_by_the_property_read(slab):
    """Fails if a dataset held under an equivalent form is not among those the assignment chooses
    from for the property a formulation reads, cannot be named by it, or can be named by its form
    (materials.md § 1: "An assignment names the dataset by the property the formulation reads";
    § 5)."""
    (slab / HIGH).write_text((slab / HIGH).read_text() + "\n" + FORM)
    at = "assign.high.datasets"
    assert checked(slab, COMPONENT) == [("dataset-unchosen", COMPONENT, f"{at}.relative_permittivity", None,
                                         ('"benchmark"', '"johnson"'))]
    named(slab, "johnson")
    assert checked(slab, COMPONENT) == [("form-unconverted", COMPONENT, f"{at}.relative_permittivity", None,
                                         ('"benchmark"',))]
    kit.rewrite(slab / COMPONENT, '{ relative_permittivity = "johnson" }', '{ refractive_index = "johnson" }')
    assert checked(slab, COMPONENT) == [
        ("no-such-property", COMPONENT, f"{at}.refractive_index", None, ('"relative_permittivity"',)),
        ("dataset-unchosen", COMPONENT, f"{at}.relative_permittivity", None, ('"benchmark"', '"johnson"'))]


# ------------------------------------------------------------------ a stationary step and a dataset that varies

VARIES = ("dataset-varies", COMPONENT, "assign.high.datasets.relative_permittivity", None, ())


def test_a_stationary_step_refuses_a_table_or_a_model_and_takes_a_value(slab):
    """Fails if a table, or a dispersion model, filling a body of a study whose step is
    `stationary` — which supplies no variable — is not an error at the component's
    `assign.<group>.datasets.<property>`, or `study prep` writes a case resting on it; or if a
    value is a finding (materials.md § 6: "a table or a model for a `stationary` step … `project
    check` gives it as an error … and `study prep` refuses a case resting on it")."""
    _one(slab, a_table(ROWS, "relative_permittivity"), measured_csv=ROWS)
    found = kit.run("project.check", project=slab.name).issues
    assert [(i.severity, *f) for i in found if (f := (i.code, i.file, i.key, i.right, i.choices)) == VARIES] == [
        ("error", *VARIES)]
    with kit.refused(Refused, "has-findings", "component:slab"):
        kit.apply("study.prep", project=slab.name, study="benchmark")
    assert not (slab / "cases").exists()
    _one(slab, MALITSON)
    assert checked(slab, COMPONENT) == [VARIES]
    _one(slab, FORM.replace("refractive_index", "relative_permittivity"))
    assert checked(slab, COMPONENT, HIGH) == []


def test_a_dataset_an_axis_names_in_a_stationary_study_is_refused_when_it_varies(slab):
    """Fails if a study whose axis takes a material's dataset in turn, one of them a table, under
    a `stationary` step, is not an error at the component's key for that dataset, while the
    assignment's own names a value (materials.md § 6; models.md § 5.1: "A study may vary a dataset
    as an axis")."""
    (slab / HIGH).write_text((slab / HIGH).read_text() + "\n" + a_table(ROWS, "relative_permittivity"))
    (slab / "materials/dielectric_2/measured.csv").write_text(ROWS)
    named(slab, "benchmark")
    assert checked(slab, COMPONENT) == []
    (slab / STUDY).write_text((slab / STUDY).read_text() + '\n[axes."component:slab:assign.high.datasets.'
                              'relative_permittivity"]\nclass = "physical sweep"\nvalues = ["benchmark", "measured"]\n')
    assert checked(slab, COMPONENT) == [(*VARIES[:4], ('"benchmark"',))]


def test_what_a_step_kind_supplies_is_its_declaration(definitions, tmp_path):
    """Fails if a step kind's declaration stating it supplies the wavelength does not let a table
    in the wavelength — or a model in the photon energy, another form of it — fill a body under
    it, or lets one in the temperature: what a kind supplies is data, never its name
    (models.md § 4.2: "Each kind states, as data: … the variable it supplies")."""
    _changed(definitions, "step_kinds.toml", ("stationary", "supplies"), ["wavelength"])
    slab = kit.copy_template(tmp_path / "projects", "two_material", "slab")
    _one(slab, a_table(ROWS, "relative_permittivity"), measured_csv=ROWS)
    assert checked(slab, COMPONENT) == []
    drude = ('[properties.relative_permittivity.metal]\nmodel = "drude_lorentz"\nconvention = "exp(-iwt)"\n'
             'source = "s"\nrange = "all"\n\n[properties.relative_permittivity.metal.parameters]\neps_inf = 1\n'
             'plasma = {value = 9, unit = "eV"}\nf0 = 1\ngamma0 = {value = 0.05, unit = "eV"}\n')
    _one(slab, drude)
    assert checked(slab, COMPONENT) == []
    hot = "temperature,eps\n300,2\n400,3\n"
    _one(slab, a_table(hot, "relative_permittivity", range_='{value = [300, 400], unit = "K"}', convention="real").replace(
        'name = "wavelength", unit = "um"', 'name = "temperature", unit = "K"'), measured_csv=hot)
    assert checked(slab, COMPONENT) == [VARIES]

