"""`project check` over the parts the models package owns (models.md §§ 3, 5, 11.1; projects.md
§ 3): each part's own rules, its formulation's, and each study's pairing read from the contracts —
every finding at the file and key the person opens, with what would be right. On copies of the
templates."""

from __future__ import annotations

import pytest

from tests import kit
from tests.kit import laplace  # noqa: F401 -- a fixture
from femkit.definitions import catalogue
from femkit.projects import door

CONDITIONS = ('"potential"', '"insulating"', '"surface_charge"', '"normal_flux"', '"interface"')
AXIS = 'values = ["0.1 m", "0.05 m", "0.025 m"]\n'   # the Laplace study's one axis's values, after which an axis is added
STEP = 'kind = "stationary"\n'                        # the Laplace study's one step's last key


def check(tmp_path, template: str, file: str, old: str, new: str):
    """``template`` copied, ``file`` of it changed, and checked."""
    folder = kit.copy_template(tmp_path / "projects", template)
    kit.rewrite(folder / file, old, new)
    return kit.run("project.check", project=template).issues


def found(issues) -> list[tuple]:
    return [(i.code, i.subject, i.file, i.key, i.right, i.choices) for i in issues]


@pytest.mark.parametrize("template, file, old, new, finding", [
    # a physics: its formulation, its meanings, each condition's kind and the parameters it lists
    ("laplace_square", "physics/electrostatics.toml", 'formulation = "electrostatics"', 'formulation = "magnetics"',
     ("no-such-formulation", "physics:electrostatics:formulation", "formulation", None, ('"electrostatics"',))),
    ("laplace_square", "physics/electrostatics.toml", '2 = "per unit depth"', '2 = "flat"',
     ("no-such-meaning", "physics:electrostatics:meaning.2", "meaning.2", None, ('"per unit depth"', '"axisymmetric"'))),
    ("laplace_square", "physics/electrostatics.toml", '2 = "per unit depth"', '4 = "per unit depth"',
     ("no-such-dimension", "physics:electrostatics:meaning.4", "meaning.4", None, ('"2"', '"3"'))),
    ("laplace_square", "physics/electrostatics.toml", 'kind = "insulating"', 'kind = "grounded"',
     ("no-such-kind", "physics:electrostatics:conditions.sides.kind", "conditions.sides.kind", None, CONDITIONS)),
    ("laplace_square", "physics/electrostatics.toml", 'kind = "insulating"', 'kind = "insulating"\ncharge = "1 C"',
     ("unknown-parameter", "physics:electrostatics:conditions.sides.charge", "conditions.sides.charge", None, ())),
    ("laplace_square", "physics/electrostatics.toml", 'value = "bias"', "",
     ("missing-parameter", "physics:electrostatics:conditions.right.value", "conditions.right.value", None, ())),
    ("laplace_square", "physics/electrostatics.toml", 'value = "0 V"', 'value = "0 m"',
     ("wrong-dimension", "physics:electrostatics:conditions.left.value", "conditions.left.value", None, ())),
    ("laplace_square", "physics/electrostatics.toml", 'value = "bias"', 'value = "bias * nothing"',
     ("bad-quantity", "physics:electrostatics:conditions.right.value", "conditions.right.value", None, ())),
    # an observable set: its reduction where it is read, its unit, its point's lengths
    ("laplace_square", "observables/midpoint.toml", 'reduction = "value"', 'reduction = "integral"',
     ("wrong-reduction", "observables:midpoint:observables.potential_middle.reduction",
      "observables.potential_middle.reduction", '"value"', ())),
    ("laplace_square", "observables/midpoint.toml", 'unit = "V"', 'unit = "Vx"',
     ("bad-unit", "observables:midpoint:observables.potential_middle.unit", "observables.potential_middle.unit",
      None, ())),
    ("laplace_square", "observables/midpoint.toml", 'point = ["side / 2", "side / 2"]', 'point = ["side / 2", "1 V"]',
     ("wrong-dimension", "observables:midpoint:observables.potential_middle.point",
      "observables.potential_middle.point", None, ())),
    ("two_material", "observables/benchmark.toml", 'group = "low"', 'group = "low"\npoint = ["0 m", "0 m"]',
     ("unloadable", "observables:benchmark", "observables.energy_low", None, ())),        # read at two places
    # the project file: the parts it names, a part it does not, a parameter named like a unit
    ("laplace_square", "project.toml", 'components = ["square"]', 'components = ["square", "round"]',
     ("no-such-part", "project:components", "components", None, ('"square"',))),
    ("laplace_square", "project.toml", 'studies = ["check"]', "studies = []",
     ("not-named", "project:studies", "studies", '["check"]', ())),
    ("laplace_square", "project.toml", 'bias = "1 V"', 'bias = "1 V"\nm = "2 m"',
     ("named-like-a-unit", "project:parameters.m", "parameters.m", None, ())),
])
def test_a_part_breaking_its_own_rule_is_a_finding_at_its_file_and_key(tmp_path, template, file, old, new, finding):
    """Fails if a physics, an observable set or the project file breaking a rule of its own or
    its formulation's is not one finding with its code, at its file and key, with the one value
    that would be right or the choices (models.md §§ 3, 5.2; projects.md § 3; core.md § 10)."""
    code, subject, key, right, choices = finding
    assert (code, subject, file, key, right, choices) in found(check(tmp_path, template, file, old, new))


@pytest.mark.parametrize("template, file, old, new, key", [
    ("two_material", "observables/benchmark.toml", 'group = "high"', 'group = "high"\nunits = "J/m"',
     "observables.energy_high.units"),                                    # in one member of a union
    ("laplace_square", "studies/check.toml", "[steps.solve]", "[steps.Solve]", "steps.Solve"),   # a table's key
    ("laplace_square", "studies/check.toml", AXIS, "values = [[1]]\n",
     'axes."mesh:uniform:size".values[0]'),                              # a quoted key; no member of a union fits
    ("two_material", "materials/dielectric_2/material.toml", 'value = "4"', "value = [4]",
     "properties.relative_permittivity.benchmark.value"),
], ids=["a discriminated member", "a table's key", "a quoted key, no member fitting", "a material's value"])
def test_a_part_that_does_not_load_is_one_finding_at_each_key_its_file_writes(tmp_path, template, file, old, new,
                                                                               key):
    """Fails if a part that does not load is not one finding at each key that is wrong, written as
    its file writes it — no mark of the validator's own, a union's member (`int`,
    `literal['all']`, a discriminator's tag) or `[key]`, in it; a key TOML quotes, quoted — or
    if the members of a union that each refuse a value are several findings at one key (core.md
    §§ 2, 10: "the key in that file, its dotted path")."""
    issues = check(tmp_path, template, file, old, new)
    assert [(i.code, i.file, i.key) for i in issues if i.code == "unloadable"] == [("unloadable", file, key)]


@pytest.mark.parametrize("file, old, new, key, right, choices", [
    ("mesh/uniform.toml", 'size = "0.1 m"', 'szie = "0.1 m"', "szie", None, ("size", "sizes")),
    ("studies/check.toml", 'family = "lagrange"', 'family = "lagrnge"', "numerics.element.family", None,
     ('"lagrange"', '"nedelec"')),
    ("mesh/uniform.toml", "schema = 1", "schema = 2", "schema", "1", ()),
    ("mesh/uniform.toml", "order = 1", "order = 3", "order", None, ("1", "2")),
    ("studies/check.toml", 'family = "lagrange"', "", "numerics.element", None, ()),
], ids=["a misspelled key", "a misspelled value", "the one value that is right", "a value outside its list",
        "a missing key"])
def test_a_part_that_does_not_load_says_at_the_key_what_would_be_right(laplace, file, old, new, key, right, choices):
    """Fails if a part that does not load is not one finding at the key the person wrote wrong,
    with what would be right: a misspelled key at itself, not also a missing one, with the keys
    its table may still take, the closest first; a value outside its list with those values, the
    closest first, or the one that is right; a missing key at its table; or if its sentence names
    its file again, which the finding carries once (models.md § 13: "an unknown key | the key |
    the schema's key"; core.md §§ 2, 10)."""
    kit.rewrite(laplace / file, old, new)
    issues = [i for i in kit.run("project.check", project="laplace_square").issues if i.code == "unloadable"]
    assert [(i.file, i.key, i.right) for i in issues] == [(file, key, right)]
    assert issues[0].choices[:len(choices)] == choices and file not in issues[0].message


@pytest.mark.parametrize("old, new, finding", [
    ('mesh = "uniform"', 'mesh = "fine"', ("no-such-part", "study:check:mesh", "mesh", None, ('"uniform"',))),
    ('display = ["m", "V", "V/m"]', 'display = ["m", "Vx"]', ("bad-unit", "study:check:display", "display", None, ())),
    (STEP, 'kind = "frequency"\n',
     ("unsupported-kind", "study:check:steps.solve.kind", "steps.solve.kind", None, ('"stationary"',))),
    # steps taking from each other (models.md § 4.5)
    (STEP, STEP + 'takes = { charge_density = "nowhere.potential" }\n',
     ("no-such-step", "study:check:steps.solve.takes.charge_density", "steps.solve.takes.charge_density", None, ())),
    (STEP, STEP + 'takes = { a = "again.heat" }\n\n[steps.again]\nphysics = "electrostatics"\n' + STEP,
     ("no-such-quantity", "study:check:steps.solve.takes.a", "steps.solve.takes.a", None,
      ('"again.potential"', '"again.electric_field"', '"again.displacement"', '"again.energy_density"'))),
    (STEP, STEP + 'takes = { a = "again.potential" }\n\n[steps.again]\nphysics = "electrostatics"\n' + STEP
     + 'takes = { b = "solve.potential" }\n',
     ("step-circle", "study:check:steps.solve.takes", "steps.solve.takes", None, ())),
    # axes, each by the address of what it varies, and their crossing (models.md § 5.1)
    ('[axes."mesh:uniform:size"]', '[axes."mesh:uniform:nowhere"]',
     ("bad-axis", 'study:check:axes."mesh:uniform:nowhere"', 'axes."mesh:uniform:nowhere"', None, ())),
    ('[axes."mesh:uniform:size"]', '[axes.bias]',                    # no address: the one it most likely means
     ("bad-axis", "study:check:axes.bias", "axes.bias", '"project:parameters.bias"', ())),
    (AXIS, AXIS + '\n[axes."project:parameters.side"]\nclass = "numerical convergence"\nvalues = ["1 m", "1 V"]\n',
     ("bad-axis-value", 'study:check:axes."project:parameters.side".values', 'axes."project:parameters.side".values',
      None, ())),
    (AXIS, AXIS + '\n[axes."study:check:numerics.element.degree"]\nclass = "numerical convergence"\nvalues = [1, 0]\n',
     ("bad-axis-value", 'study:check:axes."study:check:numerics.element.degree".values',
      'axes."study:check:numerics.element.degree".values', None, ())),
    (AXIS, AXIS + '\n[axes."component:square:assign.domain.datasets.relative_permittivity"]\nclass = '
                  '"numerical convergence"\nvalues = ["definition", "other"]\n',
     ("bad-axis-value", 'study:check:axes."component:square:assign.domain.datasets.relative_permittivity".values',
      'axes."component:square:assign.domain.datasets.relative_permittivity".values', None, ('"definition"',))),
    (AXIS, AXIS + '\n[axes."project:parameters.bias"]\nclass = "physical sweep"\nvalues = ["1 V", "2 V"]\n',
     ("crossing-missing", "study:check:crossing", "crossing", None, ())),
    (AXIS, AXIS + '\n[axes."project:parameters.bias"]\nclass = "physical sweep"\nvalues = ["1 V", "2 V"]\n\n'
                  '[crossing]\naxes = ["mesh:uniform:size"]\nreason = "at every bias"\n',
     ("crossing-incomplete", "study:check:crossing.axes", "crossing.axes",
      '["mesh:uniform:size", "project:parameters.bias"]', ())),
])
def test_a_study_breaking_its_own_rule_is_a_finding_at_its_key(tmp_path, old, new, finding):
    """Fails if a study naming a part the project lacks or a unit that does not read, asking a kind
    its formulation does not support, taking from a step that is not there, a quantity it does
    not derive or in a circle, or with an axis that does not resolve, whose value its target
    refuses, or crossed with another class without a whole `[crossing]`, is not that finding at
    the study's key (models.md §§ 4.5, 5.1)."""
    code, subject, key, right, choices = finding
    assert (code, subject, "studies/check.toml", key, right, choices) in found(
        check(tmp_path, "laplace_square", "studies/check.toml", old, new))


def test_a_binding_for_an_environment_femkit_does_not_declare_is_a_finding(tmp_path):
    """Fails if a study binding resources in an environment no definition declares is not a
    finding at its key, the declared environments its choices (models.md § 5.1)."""
    issues = check(tmp_path, "laplace_square", "studies/check.toml", "[environments.elmer.resources]",
                   "[environments.elmers.resources]")
    names = tuple(f'"{n}"' for n in sorted(catalogue.environments(kit.ctx())))
    assert ("no-such-environment", "study:check:environments.elmers", "studies/check.toml", "environments.elmers",
            None, names) in found(issues)


FACES = ('"left"', '"right"', '"sides"')   # the square's groups that may be an outer boundary


@pytest.mark.parametrize("old, new, finding, meant", [
    ("[conditions.sides]", "[conditions.side]",
     ("not-promised", "physics:electrostatics:conditions.side", "conditions.side", "side", FACES), "sides"),
    ("[conditions.sides]", "[conditions.top]",
     ("not-promised", "physics:electrostatics:conditions.top", "conditions.top", "top", FACES), None),
    ('kind = "insulating"\n', 'kind = "insulating"\n\n[conditions.domain]\nkind = "insulating"\n',
     ("wrong-place", "physics:electrostatics:conditions.domain", "conditions.domain", "domain", FACES), None),
    ('kind = "insulating"\n',
     'kind = "insulating"\n\n[sources.charge]\nkind = "charge_density"\non = "left"\nvalue = "1 C/m^3"\n',
     ("wrong-place", "physics:electrostatics:sources.charge.on", "sources.charge.on", "left", ('"domain"',)), None),
    ('2 = "per unit depth"', '3 = "full"',
     ("no-meaning", "physics:electrostatics:meaning.2", "meaning.2", None, ('"per unit depth"', '"axisymmetric"')),
     None),
], ids=["a misspelled group", "a group not promised", "a condition on a body", "a source on a face",
        "no meaning for the dimension"])
def test_what_the_pairing_finds_in_a_physics_is_said_once_at_the_physics_key(tmp_path, old, new, finding, meant):
    """Fails if a physics a study pairs with a component that does not promise a group it names,
    whose group cannot be the place its condition or source stands on, or which states no meaning
    for the component's dimension, is not one finding at the physics' key that names it — the
    groups or meanings that would do its choices, the closest group offered in its message — or
    is said on the study as well, so the physics shows complete (models.md § 5.1: "said once, in
    the file that needs changing, at the key that names what is wrong"; geometry.md § 7)."""
    folder = kit.copy_template(tmp_path / "projects", "laplace_square")
    kit.rewrite(folder / "physics" / "electrostatics.toml", old, new)
    result = kit.run("project.check", project="laplace_square")
    code, subject, key, label, choices = finding
    assert [(i.code, i.subject, i.file, i.key, i.label, i.choices) for i in result.issues if i.severity == "error"] == [
        (code, subject, "physics/electrostatics.toml", key, label, choices)]
    assert (f"did you mean `{meant}`?" in result.issues[0].message) == (meant is not None)
    states = {p.part: p.state for p in result.parts}
    assert states["physics:electrostatics"] == "findings" and states["study:check"] != "findings"


MESH, STUDY, PROJECT = "mesh/uniform.toml", "studies/check.toml", "project.toml"
VACUUM = "materials/vacuum/material.toml"
SIDE = '[axes."project:parameters.side"]\nclass = "numerical convergence"\nvalues = '
DEGREE = '[axes."study:check:numerics.element.degree"]\nclass = "numerical convergence"\nvalues = '
DATASET = ('[axes."component:square:assign.domain.datasets.relative_permittivity"]\nclass = "numerical convergence"\n'
           'values = ')


@pytest.mark.parametrize("changes, wrong", [
    # a recipe's value: the key it varies holds a value that does not read; another key does not;
    # the recipe does not load
    ([(MESH, 'size = "0.1 m"', 'size = "0.1 furlong"')], []),
    ([(MESH, 'size = "0.1 m"', 'size = "0.1"')], []),
    ([(MESH, "tolerance = 1e-9", 'tolerance = "1 furlong"'), (STUDY, '"0.05 m"', '"1 V"')], ["1 V"]),
    ([(MESH, "order = 1", "order = 7")], []),
    # a parameter: the one it varies does not read; another does not
    ([(PROJECT, 'side = "1 m"', 'side = "1 furlong"'), (STUDY, AXIS, AXIS + SIDE + '["1 m", "2 m"]\n')], []),
    ([(PROJECT, 'bias = "1 V"', 'bias = "1 furlong"'), (STUDY, AXIS, AXIS + SIDE + '["1 m", "1 V"]\n')], ["1 V"]),
    # a numerics field: the study's own other key is wrong
    ([(STUDY, 'display = ["m", "V", "V/m"]', 'display = ["Vx"]'), (STUDY, AXIS, AXIS + DEGREE + "[1, 2]\n")], []),
    ([(STUDY, 'display = ["m", "V", "V/m"]', 'display = ["Vx"]'), (STUDY, AXIS, AXIS + DEGREE + "[1, 0]\n")], ["0"]),
    # a material's dataset: its material's value does not read; the material does not load
    ([(VACUUM, 'value = "1"', 'value = "1 furlong"'), (STUDY, AXIS, AXIS + DATASET + '["definition"]\n')], []),
    ([(VACUUM, 'display = "Vacuum"', "display = 1"), (STUDY, AXIS, AXIS + DATASET + '["definition"]\n')], []),
    ([(VACUUM, 'value = "1"', 'value = "1 furlong"'), (STUDY, AXIS, AXIS + DATASET + '["definition", "x"]\n')],
     ["x"]),
], ids=["recipe: its own key", "recipe: its own key, no unit", "recipe: another key", "recipe: not loading", "parameter: its own",
        "parameter: another", "numerics: another key", "numerics: a wrong value", "dataset: its material's value",
        "dataset: its material not loading", "dataset: a wrong one"])
def test_an_axis_is_blamed_only_for_a_value_that_fails_in_its_keys_place(tmp_path, changes, wrong):
    """Fails if an axis value is a finding because the part it varies has a finding of its own —
    its file does not load, another of its keys, or the value it holds now, does not read — which
    that part's own finding already names; or if a value that itself fails in its key's place —
    another dimension, a dataset the material does not hold, a degree below 1 — is not one; for
    every kind of axis: a parameter, a recipe's value, a numerics field, a material's dataset
    (models.md § 5.1: an axis's values checked against what they vary)."""
    folder = kit.copy_template(tmp_path / "projects", "laplace_square")
    for file, old, new in changes:
        kit.rewrite(folder / file, old, new)
    issues = kit.run("project.check", project="laplace_square").issues
    assert [i.label for i in issues if i.code in ("bad-axis", "bad-axis-value")] == wrong
    assert any(i.severity == "error" and not i.subject.startswith("study:check:axes") for i in issues)


@pytest.mark.parametrize("template, study, groups", [
    ("laplace_square", "check", "`left`, `right` and `sides` are each an outer boundary"),
    ("two_material", "benchmark", "`left`, `right` and `sides` are each an outer boundary, and `middle` an interface,"),
])
def test_what_only_the_built_geometry_can_tell_is_one_note_on_the_study(tmp_path, template, study, groups):
    """Fails if a condition on a face — which may be an outer boundary, an interface or an
    embedded face until the geometry exists — is checked as fitting, or as not, rather than said
    to be not checked yet; if that is said other than once for the study, naming its groups and
    their places in the person's words; or if the study's state does not say so (projects.md
    §§ 6, 8; geometry.md § 7)."""
    kit.copy_template(tmp_path / "projects", template)
    result = kit.run("project.check", project=template)
    assert [(i.code, i.severity, i.file, i.key, i.message) for i in result.issues] == [
        (door.UNCHECKED, "info", f"studies/{study}.toml", "component",
         f"whether {groups} is checked once the geometry of `{'square' if study == 'check' else 'slab'}` is built")]
    assert {p.part: p.state for p in result.parts}[f"study:{study}"] == "unchecked" and result.ok()


FINDINGS_FIRST = ('[[rules]]\nstate = "findings"\nwhen = "findings"\n\n'
                  '[[rules]]\nstate = "unchecked"\nwhen = "unchecked"\n')
UNCHECKED_FIRST = ('[[rules]]\nstate = "unchecked"\nwhen = "unchecked"\n\n'
                   '[[rules]]\nstate = "findings"\nwhen = "findings"\n')


def test_each_parts_state_is_observed_by_the_rules_its_table_declares(definitions, tmp_path):
    """Fails if `project check` gives a part's state otherwise than by the first rule that holds
    of those `femkit/data/states/part.toml` declares, in their order: a study with a finding and
    what cannot be checked yet is `findings` by the shipped table, and `unchecked` once a table
    of the test's own puts that rule first (projects.md § 8: "observed ... by the rules
    `femkit/data/states/part.toml` declares, in this order"; core.md § 7)."""
    folder = kit.copy_template(tmp_path / "projects", "laplace_square")
    kit.rewrite(folder / "studies" / "check.toml", 'display = ["m", "V", "V/m"]', 'display = ["Vx"]')

    def states() -> dict[str, str]:
        return {p.part: p.state for p in kit.run("project.check", project="laplace_square").parts}

    assert (states()["study:check"], states()["physics:electrostatics"]) == ("findings", "complete")
    kit.rewrite(definitions / "states" / "part.toml", FINDINGS_FIRST, UNCHECKED_FIRST)
    assert (states()["study:check"], states()["physics:electrostatics"]) == ("unchecked", "complete")


DERIVED = ('"potential"', '"electric_field"', '"displacement"', '"energy_density"')


@pytest.mark.parametrize("template, file, old, new, code, key, choices", [
    ("laplace_square", "observables/midpoint.toml", 'point = ["side / 2", "side / 2"]',
     'point = ["side / 2", "side / 2", "0 m"]', "wrong-point", "observables.potential_middle.point", ()),
    ("laplace_square", "observables/midpoint.toml", 'quantity = "potential"', 'quantity = "temperature"',
     "no-such-quantity", "observables.potential_middle.quantity", DERIVED),
    ("laplace_square", "observables/midpoint.toml", 'unit = "V"', 'unit = "V/m"', "wrong-unit",
     "observables.potential_middle.unit", ()),
    ("two_material", "observables/benchmark.toml", 'group = "low"', 'group = "low"\nside = "middle"', "wrong-side",
     "observables.energy_low.side", ('"low"', '"high"')),
    ("two_material", "observables/benchmark.toml", 'group = "high"', 'group = "top"', "not-promised",
     "observables.energy_high.group", ('"low"', '"high"', '"middle"', '"left"', '"right"', '"sides"')),
])
def test_an_observable_its_study_cannot_read_is_a_finding_at_the_observables_key(tmp_path, template, file, old, new,
                                                                                code, key, choices):
    """Fails if an observable whose point has another number of lengths than the paired frame's
    axes, whose quantity the study's physics do not derive, whose unit is not one of its quantity
    — times what it is integrated over — whose side is no body, or whose group the component does
    not promise, is not one finding at the observable's own key, the values that would do its
    choices, and none on the study (models.md §§ 5.1, 5.2)."""
    issues = check(tmp_path, template, file, old, new)
    observables = file.removesuffix(".toml").replace("/", ":", 1)
    assert [(i.code, i.subject, i.file, i.key, i.choices) for i in issues if i.severity == "error"] == [
        (code, f"{observables}:{key}", file, key, choices)]


@pytest.mark.parametrize("point", ['["side / 2", "side / 2"]', '["side / 2", "side"]'], ids=["alike", "unlike"])
def test_lengths_of_a_point_wrong_one_way_are_one_finding_at_its_key(tmp_path, point):
    """Fails if a point whose lengths are wrong one way — each using `side`, a parameter that is no
    length — is said more than once at the point's key, whether its lengths read alike or not: one
    finding per key and code, as a finding is told apart by them (core.md §§ 9, 10; models.md
    § 5.2)."""
    folder = kit.copy_template(tmp_path / "projects", "laplace_square")
    kit.rewrite(folder / "project.toml", 'side = "1 m"', 'side = "1 V"')
    kit.rewrite(folder / "observables" / "midpoint.toml", 'point = ["side / 2", "side / 2"]', f"point = {point}")
    at = "observables:midpoint:observables.potential_middle.point"
    assert [i.code for i in kit.run("project.check", project="laplace_square").issues if i.subject == at] == [
        "wrong-dimension"]


@pytest.mark.parametrize("file, old, new, subject", [
    ("project.toml", 'bias = "1 V"', 'bias = "1 V"\nhalf = "sied / 2"', "project:parameters.half"),
    ("observables/midpoint.toml", 'point = ["side / 2", "side / 2"]', 'point = ["sied / 2", "side / 2"]',
     "observables:midpoint:observables.potential_middle.point"),
], ids=["in the project file", "in an observable's point"])
def test_a_misspelled_parameter_is_said_one_way_with_the_one_it_most_likely_means(tmp_path, file, old, new, subject):
    """Fails if a name that is neither a unit nor a parameter — a parameter misspelled, in the
    project file or in a value that may use the parameters — is said otherwise than one way: the
    name once; "did you mean" the parameter closest to it; the parameters given (core.md § 11:
    "a symbol that is neither a unit nor a name given"; models.md § 3)."""
    (finding,) = [i for i in check(tmp_path, "laplace_square", file, old, new) if i.subject == subject]
    assert finding.code == "bad-quantity"
    assert finding.message.count("`sied`") == 1 and "did you mean `side`?" in finding.message
    assert "`bias`" in finding.message


def test_an_observable_name_two_sets_of_a_study_share_is_a_finding_on_the_study(tmp_path):
    """Fails if two observable sets one study reports may share an observable's name — a
    reference or an analysis names an observable by its name alone (models.md § 5.2)."""
    folder = kit.copy_template(tmp_path / "projects", "two_material")
    (folder / "observables" / "again.toml").write_text((folder / "observables" / "benchmark.toml").read_text())
    kit.rewrite(folder / "studies" / "benchmark.toml", 'observables = ["benchmark"]',
                'observables = ["benchmark", "again"]')
    issues = kit.run("project.check", project="two_material").issues
    assert sorted(i.label for i in issues if i.code == "observable-twice") == [
        "energy_high", "energy_low", "potential_high", "potential_low", "potential_middle"]


def test_a_material_lacking_a_property_the_physics_reads_is_a_finding_on_the_material(tmp_path):
    """Fails if a study pairs a physics with a component whose material holds no dataset of a
    property the formulation reads, and `project check` does not say so at the material's key for
    that property (models.md §§ 3, 5.1: the materials' properties the formulation needs, said in
    the file that needs changing)."""
    folder = kit.copy_template(tmp_path / "projects", "laplace_square")
    (folder / "materials" / "vacuum" / "material.toml").write_text('schema = 1\ndisplay = "Vacuum"\n\n[properties]\n')
    issues = kit.run("project.check", project="laplace_square").issues
    assert [(i.subject, i.file, i.key) for i in issues if i.severity == "error"] == [
        ("material:vacuum:properties.relative_permittivity", "materials/vacuum/material.toml",
         "properties.relative_permittivity")]


def test_a_broken_part_is_a_finding_and_every_other_part_is_still_checked(tmp_path):
    """Fails if a part that does not load stops the others being read and checked, or its finding
    does not name its file and key (models.md § 11.1: "A part that does not load ... is a finding
    on it, and every other part is still read")."""
    folder = kit.copy_template(tmp_path / "projects", "laplace_square")
    kit.rewrite(folder / "physics" / "electrostatics.toml", 'value = "0 V"', "value = [")
    kit.rewrite(folder / "observables" / "midpoint.toml", 'unit = "V"', 'unit = "Vx"')
    result = kit.run("project.check", project="laplace_square")
    assert [(i.code, i.file) for i in result.issues if i.severity == "error"] == [
        ("bad-unit", "observables/midpoint.toml"), ("unloadable", "physics/electrostatics.toml")]
    assert {p.part: p.state for p in result.parts}["physics:electrostatics"] == "unloadable" and not result.ok()


def test_a_project_file_that_does_not_load_is_its_own_finding_alone(tmp_path):
    """Fails if, while the project file does not load, a part using a parameter — a physics'
    value, an observable's point, a recipe's size — has a finding of its own about it: what the
    parameters hold is not known, and the project file's own finding says why (models.md § 3:
    "one using a parameter that does not resolve does not resolve either, and has no finding of
    its own")."""
    folder = kit.copy_template(tmp_path / "projects", "laplace_square")
    kit.rewrite(folder / "mesh" / "uniform.toml", 'size = "0.1 m"', 'size = "side / 10"')
    kit.rewrite(folder / "project.toml", "[parameters]", "[parameters")
    result = kit.run("project.check", project="laplace_square")
    assert [(i.code, i.file) for i in result.issues if i.severity != "info"] == [("unloadable", "project.toml")]
    states = {p.part: p.state for p in result.parts}
    assert {states[p] for p in ("physics:electrostatics", "observables:midpoint", "mesh:uniform")} == {"complete"}


def test_a_name_the_project_file_misspells_has_the_list_put_right_as_its_one_finding(tmp_path):
    """Fails if a study the project file names that has no file, close to one there, is not one
    finding whose right value is the list with the misspelling replaced — `["check"]`, never
    `["chek", "check"]` — or the study it means is said, besides, to be not named (projects.md
    § 3: "a name with no file is a finding with its fix"; core.md § 10)."""
    issues = check(tmp_path, "laplace_square", "project.toml", 'studies = ["check"]', 'studies = ["chek"]')
    assert [(i.code, i.key, i.right, i.choices) for i in issues if i.severity != "info"] == [
        ("no-such-part", "studies", '["check"]', ())]
    assert issues[0].message.endswith("did you mean `check`?")


def test_a_step_taking_from_no_other_step_offers_the_others_as_its_choices(tmp_path):
    """Fails if a step taking from a step the study does not have is not a finding whose choices
    are the study's other steps, each with the quantity it names (core.md § 10: "where several
    would do … they are `choices`"; models.md § 4.5)."""
    issues = check(tmp_path, "laplace_square", "studies/check.toml", STEP,
                   STEP + 'takes = { charge_density = "solv.potential" }\n\n[steps.other]\nphysics = "electrostatics"\n'
                   + STEP + '\n[steps.third]\nphysics = "electrostatics"\n' + STEP)
    assert [(i.code, i.key, i.choices) for i in issues if i.code == "no-such-step"] == [
        ("no-such-step", "steps.solve.takes.charge_density", ('"other.potential"', '"third.potential"'))]


def test_a_step_kind_its_formulation_does_not_support_is_a_finding_whatever_the_component(tmp_path):
    """Fails if a step asking a kind its physics' formulation does not support is a finding only
    while the study's component is there to pair: the kind is the step's and the physics' alone
    (models.md § 4.2)."""
    folder = kit.copy_template(tmp_path / "projects", "laplace_square")
    kit.rewrite(folder / "studies" / "check.toml", STEP, 'kind = "frequency"\n')
    kit.rewrite(folder / "studies" / "check.toml", 'component = "square"', 'component = "round"')
    issues = kit.run("project.check", project="laplace_square").issues
    assert "component" in [i.key for i in issues if i.code == "no-such-part"]
    assert [(i.key, i.choices) for i in issues if i.code == "unsupported-kind"] == [
        ("steps.solve.kind", ('"stationary"',))]
