"""A study's cases (models.md § 5.3): one `case.json` per axis point, complete and exact, in the
study's own folder, named by the SHA-256 of its canonical JSON — so two spellings of one value are
one case of the study, and two studies never share one; a typed model in every key, as what a
stage keeps of it is; refused while a part the study uses does not load or has a finding; listed
under the study that made them, with whether `study prep` can make each study's cases now and why
not. On copies of the templates."""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

import pytest

from tests import kit
from tests.kit import laplace  # noqa: F401 -- a fixture
from femkit.core.errors import Refused, UsageError
from femkit.definitions import catalogue
from femkit.core import view
from femkit.models import cases
from femkit.models.operations import ALLOWED
from femkit.projects import door
from femkit.workflow.identity import MadeFrom

AXIS = ('[axes."mesh:uniform:size"]\n# why it varies: one of `numerical convergence`, `geometry convergence`, '
        '`physical sweep`\nclass = "numerical convergence"\n# its values, in order: plain numbers — in its `unit` '
        "where what it varies has one — or, for a material's dataset, each dataset by its name\n"
        'values = [0.1, 0.05, 0.025]\n# the unit its values are in, where what it varies has one: a unit of its '
        'dimension\nunit = "m"\n')
SIZE = 'size = {value = 0.1, unit = "m"}'           # the Laplace recipe's size
LEFT = 'value = {value = 0, unit = "V"}'             # the Laplace physics' left side's potential


def by_name(result) -> dict:
    """A listing's studies — `case list`'s, `study list`'s — by their names."""
    return {s.name: s for s in result.studies}


def written(folder: Path, study: str = "check") -> dict[str, dict]:
    """Every case.json in the study's folder of the project's cases/, by the folder it is in."""
    return {p.parent.name: json.loads(p.read_text())
            for p in sorted((folder / "cases" / study).glob("*/case.json"))}


def prepped(name: str = "laplace_square", study: str = "check"):
    """`study prep` of the study, on a machine with no record: its cases written, its stages left
    waiting for one (workflow.md § 7)."""
    return kit.apply("study.prep", project=name, study=study)


def test_prep_writes_one_complete_case_per_point_named_by_its_content(laplace):
    """Fails if `study prep` does not write the Laplace study's three cases in the study's own
    folder, each `case.json` in the shape models.md § 5.3 states — every quantity exact, every
    other number its exact text, every default written, nothing of the study's own beyond its
    numerics — under the SHA-256 of its canonical JSON; or writes one again (models.md § 5.3)."""
    outcome = prepped()
    cases_there = written(laplace)
    assert outcome.ok() and sorted(outcome.added) == sorted(cases_there) and len(cases_there) == 3
    assert sorted(p.relative_to(laplace).as_posix() for p in (laplace / "cases").rglob("case.json")) == sorted(
        door.case_file(kit.opened(laplace), "check", i) for i in cases_there)
    for name, data in cases_there.items():
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        assert hashlib.sha256(canonical).hexdigest() == name
        assert sorted(data) == ["component", "mesh", "numerics", "point", "schema", "steps"]
        assert door.read_record(kit.opened(laplace), door.case_file(kit.opened(laplace), "check", name),
                                cases.Case).value.schema_ == cases.SHAPE
    assert len({json.dumps(d["point"]) for d in cases_there.values()}) == 3
    one = next(iter(cases_there.values()))
    assert one["numerics"] == {"element": {"family": "lagrange", "degree": "1"},
                               "solver": {"kind": "direct", "tolerance": None}}
    assert one["component"]["inputs"] == {"side": {"value": "1", "dimension": {"length": 1}}}
    assert one["steps"]["potential"]["physics"]["conditions"]["right"] == {
        "kind": "potential", "value": {"value": "1", "dimension": {"current": -1, "length": 2, "mass": 1, "time": -3}}}
    assert one["steps"]["potential"]["physics"]["meaning"] == "per unit depth"
    assert one["component"]["assign"]["domain"]["properties"]["relative_permittivity"] == {
        "dataset": "definition", "data": {"value": {"value": "1", "dimension": {}}, "convention": "real",
                                          "source": "the definition of vacuum: its permittivity is the vacuum "
                                                    "electric permittivity ε0 itself, so its relative permittivity "
                                                    "is exactly 1",
                                          "range": "all", "temperature": None, "uncertainty": None}}
    again = prepped()
    assert again.added == [] and sorted(again.kept) == sorted(cases_there)


@pytest.mark.parametrize("values, cases_made", [
    ('[500, 500.0]', 1),        # two spellings of one length: one case
    ('[500, 600]', 2),          # two lengths: two
])
def test_two_spellings_of_one_value_give_one_case(laplace, values, cases_made):
    """Fails if 500 and 500.0 nm give two cases of one study — a value read through a binary float,
    or held as it is spelled — or two different lengths give one (models.md § 5.3: "500 nm" and
    "0.5 µm" give the same ID)."""
    kit.rewrite(laplace / "studies" / "check.toml", AXIS,
                f'[axes."project:definitions.side"]\nclass = "physical sweep"\nvalues = {values}\nunit = "nm"\n')
    assert len(prepped().added) == cases_made == len(written(laplace))


def test_one_length_in_two_units_gives_one_case(tmp_path):
    """Fails if a length an axis gives in nanometres and the same length another gives in
    micrometres make two cases — a value held as it is spelled, or read through a binary float
    (models.md § 5.3: "500 nm" and "0.5 µm" give the same ID; core.md § 11)."""
    made = []
    for name, values, unit in (("a", "[500]", "nm"), ("b", "[0.5]", "µm")):
        folder = kit.copy_template(tmp_path / "projects", "laplace_square", name)
        kit.rewrite(folder / "studies" / "check.toml", AXIS, f'[axes."project:definitions.side"]\nclass = '
                                                             f'"physical sweep"\nvalues = {values}\nunit = "{unit}"\n')
        made.append(prepped(name).added)
    assert made[0] == made[1] and len(made[0]) == 1


def test_two_studies_of_one_content_each_write_their_own_cases(laplace):
    """Fails if two studies whose cases have the same content share a case folder, or if
    prepping one keeps, rather than writes, a case the other wrote (models.md § 5.3: each
    study's cases are its own; nothing is shared between studies)."""
    (laplace / "studies" / "again.toml").write_text((laplace / "studies" / "check.toml").read_text())
    kit.rewrite(laplace / "project.toml", 'studies = ["check"]', 'studies = ["check", "again"]')
    first, second = prepped(study="check"), prepped(study="again")
    assert len(first.added) == len(second.added) == 3 and second.kept == []
    assert sorted(written(laplace, "check")) == sorted(written(laplace, "again")) == sorted(first.added)
    listed = {s.name: sorted(c.id for c in s.written) for s in kit.run("case.list", project="laplace_square").studies}
    assert listed == {"again": sorted(second.added), "check": sorted(first.added)}


def test_a_number_written_two_ways_gives_one_case_and_an_observable_none(tmp_path):
    """Fails if a number's spelling — `1e-9` or `1.0e-9`, a material's `1` or `1.0` —
    changes a case's ID, if adding an observable does, or if a material's value does not
    (models.md § 5.3: "Every quantity — … a material's value or range, a mesh size — is written as
    {value, dimension}"; § 5.2: an observables part enters no case)."""
    a = kit.copy_template(tmp_path / "projects", "laplace_square", "a")
    b = kit.copy_template(tmp_path / "projects", "laplace_square", "b")
    kit.rewrite(b / "mesh" / "uniform.toml", "tolerance = 1e-9", "tolerance = 1.0e-9")
    kit.rewrite(b / "materials" / "vacuum" / "material.toml", "value = 1", "value = 1.0")
    kit.rewrite(b / "observables" / "midpoint" / "observables.toml", "[observables.potential_middle]\n",
                '[observables.field]\nfunction = "field"\ntype = "float"\nunit = "V/m"\n\n'
                '[observables.potential_middle]\n')
    with (b / "observables" / "midpoint" / "observe.py").open("a") as f:
        f.write("\n\ndef field(case):\n    return 0.0\n")
    assert sorted(prepped("a").added) == sorted(prepped("b").added)
    kit.rewrite(b / "materials" / "vacuum" / "material.toml", "value = 1.0", "value = 2")
    changed = prepped("b").added
    assert len(changed) == 3 and set(changed).isdisjoint(written(a))


@pytest.mark.parametrize("file, old, new, code, subject", [
    ("physics/electrostatics.toml", 'kind = "insulating"', 'kind = "grounded"', "has-findings",
     "physics:electrostatics"),
    ("studies/check.toml", AXIS, AXIS + '\n[axes."project:definitions.bias"]\nclass = "physical sweep"\n'
                                         'values = [1, 2]\nunit = "V"\n', "has-findings", "study:check"),
    ("project.toml", 'studies = ["check"]', "studies = []", "not-named", "study:check"),
    ("project.toml", 'components = ["square"]', "components = []", "not-named", "component:square"),
    ("physics/electrostatics.toml", LEFT, LEFT.removesuffix('"}'), "unloadable", "physics:electrostatics"),
    ("mesh/uniform.toml", SIZE, SIZE.replace("size", "sise", 1), "unloadable", "mesh:uniform"),
    ("project.toml", "[definitions]\n", "[definitions\n", "unloadable", "project"),
], ids=["a physics' finding", "the study's own finding", "the study not named", "its component not named",
        "a physics not loading", "a recipe not loading", "the project file not loading"])
def test_a_study_with_findings_or_not_named_is_refused_and_nothing_is_written(laplace, file, old, new, code,
                                                                              subject):
    """Fails if `study prep` writes cases, or fails otherwise than by a refusal naming the part,
    while a part the study uses does not load or has a finding — axes of different classes crossed
    without a `[crossing]` among them — or while the project file does not name the study or its
    component, or says so by the command `study prep` replaced (models.md § 5.3; projects.md § 3:
    "inert, never loaded into a case"); or if a part that does not load is refused otherwise than
    the one way the door refuses one, `UsageError` `unloadable` (projects.md § 6; plan § 4, X: "a
    refused part that does not load one kind")."""
    kit.rewrite(laplace / file, old, new)
    with kit.refused(UsageError if code == "unloadable" else Refused, code, subject) as caught:
        prepped()
    assert not (laplace / "cases").exists()
    said = [str(caught.value), *(i.message for i in kit.run("project.check", project="laplace_square").issues)]
    assert not [s for s in said if "expand" in s]


@pytest.mark.parametrize("file, old, new, why", [
    ("physics/electrostatics.toml", LEFT, LEFT.removesuffix('"}'), "`physics:electrostatics` does not load"),
    ("mesh/uniform.toml", SIZE, SIZE.replace("size", "sise", 1), "`mesh:uniform` does not load"),
], ids=["a physics with an unclosed quote", "a recipe with a misspelled key"])
def test_a_study_using_a_part_that_does_not_load_lists_as_making_no_case_and_is_not_complete(laplace, file, old,
                                                                                           new, why):
    """Fails if `study list` or `case list` does not say that `study prep` cannot make the cases of
    a study using a part that does not load, naming that part by its address — never by its kind's
    name, which reads as many for a kind named in the plural (models.md §§ 5.1, 11.1; projects.md
    §§ 5, 8)."""
    kit.rewrite(laplace / file, old, new)
    for verb in ("study.list", "case.list"):
        assert [(s.name, s.makes, s.why) for s in kit.run(verb, project="laplace_square").studies] == [
            ("check", False, why)]
    assert {p.part: p.state for p in kit.run("project.check", project="laplace_square").parts}["study:check"] \
        == "unchecked"


def test_case_list_shows_each_studys_cases_their_point_and_a_study_whose_cases_prep_cannot_make(laplace):
    """Fails if `case list` does not show each written case under its study, with its point and
    whether the study makes it now — one it no longer makes kept, with its point as its file holds
    it, exactly, its decimal where it has one, so the same value reads the same — or a study whose
    cases `study prep` cannot make now, and why (models.md § 5.3, § 11.1; core.md § 11)."""
    prepped()
    study = by_name(kit.run("case.list", project="laplace_square"))["check"]
    assert (study.name, study.makes, study.cases) == ("check", True, 3)
    assert sorted((c.point["mesh:uniform:size"], c.made) for c in study.written) == [
        (v, True) for v in ("0.025 m", "0.05 m", "0.1 m")]
    kit.rewrite(laplace / "studies" / "check.toml", 'mesh = "uniform"', 'mesh = "fine"')
    study = by_name(kit.run("case.list", project="laplace_square"))["check"]
    units = catalogue.units(kit.ctx())
    assert sorted((c.id, c.point, c.made) for c in study.written) == [
        (i, {k: cases.shown(v, units) for k, v in cases.Case.model_validate(d).point.items()}, False)
        for i, d in written(laplace).items()]
    assert sorted(c.point["mesh:uniform:size"] for c in study.written) == ["0.025 m", "0.05 m", "0.1 m"]
    assert (study.name, study.makes, study.cases) == ("check", False, 0) and study.why
    assert [(s.name, s.makes) for s in kit.run("study.list", project="laplace_square").studies] == [
        ("check", False)]
    for verb in ("study.list", "case.list"):     # said by what `study prep` can do, never by a command withdrawn
        assert "expand" not in kit.run(verb, project="laplace_square").text()


def test_case_list_orders_a_studys_cases_by_their_point_as_the_study_lists_it(laplace):
    """Fails if `case list` orders a study's cases otherwise than by their point — axis by axis as
    the study declares its axes, each value where the study lists it, neither by ID nor by value —
    those the study makes now first, then those it no longer makes in that order, a value it no
    longer lists after those it does, by its value (models.md § 5.3)."""
    size, degree = "mesh:uniform:size", "study:check:numerics.element.degree"
    study = laplace / "studies" / "check.toml"
    kit.rewrite(study, f'[axes."{size}"]',                             # declared first, though it sorts last
                f'[axes."{degree}"]\nclass = "numerical convergence"\nvalues = [2, 1]\n\n[axes."{size}"]')
    kit.rewrite(study, "[0.1, 0.05, 0.025]", "[0.05, 0.1, 0.025]")
    prepped()

    def listed() -> list[tuple[str, str, bool]]:
        held = by_name(kit.run("case.list", project="laplace_square"))["check"]
        return [(c.point[degree], c.point[size], c.made) for c in held.written]

    points = [(d, s) for d in ("2", "1") for s in ("0.05 m", "0.1 m", "0.025 m")]
    assert listed() == [(d, s, True) for d, s in points]
    kit.rewrite(laplace / "mesh" / "uniform.toml", "tolerance = 1e-9", "tolerance = 1e-8")   # each point anew
    prepped()
    assert listed() == [(d, s, True) for d, s in points] + [(d, s, False) for d, s in points]
    kit.rewrite(study, "[0.05, 0.1, 0.025]", "[0.2, 0.05]")
    no_longer = ("0.05 m", "0.025 m", "0.025 m", "0.1 m", "0.1 m")    # listed first; the others by value
    assert listed() == [(d, "0.05 m", True) for d in ("2", "1")] + [(d, s, False) for d in ("2", "1")
                                                                    for s in no_longer]


def test_a_recipe_value_an_axis_varies_is_exact_in_the_case_and_in_its_dimension(laplace):
    """Fails if a value of the recipe an axis varies, a number in the axis's unit, is not read in
    the dimension of the value it replaces, or the case holds it — in its point and its recipe —
    as it is spelled rather than exactly: 100 and 100.0 mm one case, 0.1 m (models.md §§ 5.1,
    5.3)."""
    kit.rewrite(laplace / "studies" / "check.toml", "values = [0.1, 0.05, 0.025]", "values = [100, 100.0, 50]")
    kit.rewrite(laplace / "studies" / "check.toml", 'unit = "m"\n\n# groups', 'unit = "mm"\n\n# groups')
    assert not [i for i in kit.run("project.check", project="laplace_square").issues if i.severity == "error"]
    assert len(prepped().added) == 2
    tenth = {"value": "1/10", "dimension": {"length": 1}}
    assert any(d["point"] == {"mesh:uniform:size": tenth} and d["mesh"]["size"] == tenth
               for d in written(laplace).values())



def test_an_axis_value_out_of_its_recipes_range_is_a_finding_and_prep_makes_nothing(laplace):
    """Fails if an axis giving a recipe's size a value its recipe's own rules refuse — 0 m — passes
    `project check` and `study prep`, to fail only once the mesh step runs (models.md § 5.1: a
    recipe's value "checked again by its own rules at that key"; geometry.md § 6)."""
    kit.rewrite(laplace / "studies" / "check.toml", "values = [0.1, 0.05, 0.025]", "values = [0.1, 0]")
    issues = kit.run("project.check", project="laplace_square").issues
    assert [(i.code, i.label) for i in issues if i.severity == "error"] == [("bad-axis-value", "0 m")]
    with kit.refused(Refused, "has-findings", "study:check"):
        prepped()


def test_femkit_reads_and_writes_its_outputs_only_in_a_folder_the_layout_says_it_writes(laplace):
    """Fails if the door reads or writes one of femkit's own outputs outside the folders the
    layout declares femkit writes — over a file the person wrote — or writes one otherwise than
    whole, as JSON (projects.md §§ 6, 7: "only this package ... opens a project's file, or writes
    one"; "No file the person wrote")."""
    opened = kit.opened(laplace)
    assert door.read_output(opened, "cases/x/case.json") is None
    door.write_output(opened, "cases/x/case.json", {"b": 1, "a": [2]})
    assert json.loads((laplace / "cases" / "x" / "case.json").read_text()) == {"a": [2], "b": 1}
    assert json.loads(door.read_output(opened, "cases/x/case.json")) == {"a": [2], "b": 1}
    before = kit.tree(laplace)
    for relative in ("physics/electrostatics.toml", "custom/x", "cases"):
        with kit.refused(UsageError, "not-femkits", relative):
            door.write_output(opened, relative, {})
        with kit.refused(UsageError, "not-femkits", relative):
            door.read_output(opened, relative)
    assert kit.tree(laplace) == before


# ------------------------------------------------------------------ axes that step together (models.md § 5.1)

#: Two axes of one class the Laplace study steps together, three values each: the side as built and
#: the bias it was measured at.
TOGETHER = ('[axes."project:definitions.side"]\nclass = "physical sweep"\nvalues = [1, 2, 3]\nunit = "m"\n\n'
            '[axes."project:definitions.bias"]\nclass = "physical sweep"\nvalues = [1, 2, 3]\nunit = "V"\n\n'
            '[together.samples]\naxes = ["project:definitions.side", "project:definitions.bias"]\n'
            'reason = "each square as built, with the bias it was measured at"\n')


def step_together(folder: Path, text: str = TOGETHER) -> None:
    """The Laplace study's mesh axis taken out, and ``text`` — two axes stepping together — written
    in its place."""
    study = folder / "studies" / "check.toml"
    held = study.read_text()
    start = held.index('[axes."mesh:uniform:size"]')
    study.write_text(held[:start] + text + held[held.index("\n\n", start):])


def test_axes_that_step_together_make_as_many_cases_as_each_has_values_crossed_as_one(laplace):
    """Fails if two axes a group steps together are crossed — nine cases where the n-th case takes
    each one's n-th value — or the group is not crossed as one axis with the others, at its first
    axis's place in the cases' order, which `case list` shows (models.md §§ 5.1, 5.3; plan § 4, X
    acceptance: a study stepping two axes together makes as many cases as each has values)."""
    step_together(laplace, TOGETHER.replace("[together", '[axes."mesh:uniform:size"]\nclass = "physical sweep"\n'
                                                     'values = [0.1, 0.2]\nunit = "m"\n\n[together'))
    assert not [i for i in kit.run("project.check", project="laplace_square").issues if i.severity == "error"]
    prepped()
    points = sorted((p["project:definitions.side"]["value"], p["project:definitions.bias"]["value"])
                    for p in (case["point"] for case in written(laplace).values()))
    assert points == [("1", "1"), ("1", "1"), ("2", "2"), ("2", "2"), ("3", "3"), ("3", "3")]
    listed = by_name(kit.run("case.list", project="laplace_square"))["check"].written
    assert [(w.point["project:definitions.side"], w.point["mesh:uniform:size"]) for w in listed] == [
        ("1 m", "0.1 m"), ("1 m", "0.2 m"), ("2 m", "0.1 m"), ("2 m", "0.2 m"), ("3 m", "0.1 m"), ("3 m", "0.2 m")]


@pytest.mark.parametrize("text, code", [
    (TOGETHER.replace('axes = ["project:definitions.side", "project:definitions.bias"]',
                      'axes = ["project:definitions.side", "project:definitions.gap"]'), "together-unknown"),
    (TOGETHER + '\n[together.again]\naxes = ["project:definitions.bias", "project:definitions.side"]\nreason = "again"\n',
     "together-twice"),
    (TOGETHER.replace('class = "physical sweep"\nvalues = [1, 2, 3]\nunit = "V"',
                      'class = "numerical convergence"\nvalues = [1, 2, 3]\nunit = "V"'), "together-classes"),
    (TOGETHER.replace('values = [1, 2, 3]\nunit = "V"', 'values = [1, 2]\nunit = "V"'), "together-lengths"),
], ids=["an address no axis has", "an axis in two groups", "axes of two classes", "different numbers of values"])
def test_a_group_breaking_its_rule_is_a_finding_at_its_key_and_prep_makes_nothing(laplace, text, code):
    """Fails if a group of axes stepping together that names an address no axis of the study has,
    an axis an earlier group names, axes of two classes, or axes holding different numbers of
    values is not an error at the group's key, `together.<name>`, which `study prep` refuses
    (models.md §§ 5.1, 13; plan § 4, X acceptance: "each of its four findings is shown at its
    key")."""
    step_together(laplace, text)
    found = [(i.code, i.key) for i in kit.run("project.check", project="laplace_square").issues if i.code == code]
    assert found and found[0][1].startswith("together.")
    with kit.refused(Refused, "has-findings"):
        prepped()


# ------------------------------------------------------------------ an axis's values and its unit (models.md § 5.1)

def test_an_axis_states_its_values_as_plain_numbers_and_its_unit_once(laplace):
    """Fails if an axis's values — plain numbers, its `unit` stated once — do not reach each case
    exactly in what it varies: a recipe's size in its unit, a definition in its unit's dimension,
    a dimensionless numerics field as itself, a dataset by its name; or if `case list` does not
    show each value with its axis's unit (models.md § 5.1: "its values plain numbers and its
    `unit` stated once on the axis"; core.md § 11)."""
    kit.rewrite(laplace / "studies" / "check.toml", 'values = [0.1, 0.05, 0.025]\n# the unit its values are in, '
                'where what it varies has one: a unit of its dimension\nunit = "m"',
                'values = [100, 50]\nunit = "mm"\n\n[axes."project:definitions.bias"]\nclass = "physical sweep"\n'
                'values = [1, 2.5]\nunit = "kV"\n\n[axes."study:check:numerics.element.degree"]\n'
                'class = "numerical convergence"\nvalues = [2]\n\n'
                '[axes."component:square:assign.domain.datasets.relative_permittivity"]\nclass = "physical sweep"\n'
                'values = ["definition"]\n\n[crossing]\naxes = ["mesh:uniform:size", "project:definitions.bias", '
                '"study:check:numerics.element.degree", '
                '"component:square:assign.domain.datasets.relative_permittivity"]\nreason = "every pairing"\n')
    assert not [i for i in kit.run("project.check", project="laplace_square").issues
                if i.severity == "error" and i.file == "studies/check.toml"]
    prepped()
    held = sorted((d["point"]["mesh:uniform:size"]["value"], d["mesh"]["size"]["value"],
                   d["point"]["project:definitions.bias"]["value"],
                   d["steps"]["potential"]["physics"]["conditions"]["right"]["value"]["value"],
                   d["numerics"]["element"]["degree"], d["point"]["study:check:numerics.element.degree"],
                   d["point"]["component:square:assign.domain.datasets.relative_permittivity"])
                  for d in written(laplace).values())
    assert held == [(size, size, bias, bias, "2", "2", "definition")
                    for size in ("1/10", "1/20") for bias in ("1000", "2500")]
    listed = by_name(kit.run("case.list", project="laplace_square"))["check"].written
    assert [(w.point["mesh:uniform:size"], w.point["project:definitions.bias"]) for w in listed] == [
        ("100 mm", "1 kV"), ("100 mm", "2.5 kV"), ("50 mm", "1 kV"), ("50 mm", "2.5 kV")]


@pytest.mark.parametrize("axis, right", [
    ('values = [0.1, 0.05, 0.025]\n', '"m"'),                                       # none where a length is varied
    ('values = [0.1, 0.05, 0.025]\nunit = "V"\n', '"m"'),                           # one of another dimension
    ('values = [0.1, 0.05, 0.025]\nunit = "furlong"\n', '"m"'),                     # one that does not read
    ('values = ["0.1 m"]\nunit = "m"\n', None),                                     # a text, never a quantity
], ids=["no unit", "a unit of another dimension", "a unit that does not read", "a value written as text"])
def test_an_axis_whose_unit_or_value_does_not_fit_what_it_varies_is_a_finding_at_its_key(laplace, axis, right):
    """Fails if an axis varying a length states no unit, one of another dimension or one that does
    not read — or gives a value as a text — and `project check` does not say so at its key, the
    unit what it varies is written in its right value (models.md § 5.1: "an axis over a
    definition in a unit of its dimension, over a dataset its names, over a dimensionless field
    plain numbers with no unit"; core.md § 11: no quantity is written as a text)."""
    study = laplace / "studies" / "check.toml"
    text = study.read_text()
    start = text.index("values = [0.1")
    study.write_text(text[:start] + axis + text[text.index('unit = "m"\n', start) + len('unit = "m"\n'):])
    issues = [i for i in kit.run("project.check", project="laplace_square").issues if i.severity == "error"]
    if right is None:
        assert [(i.code, i.key) for i in issues] == [("bad-axis-value", 'axes."mesh:uniform:size".values')]
    else:
        assert [(i.code, i.key, i.right) for i in issues] == [
            ("bad-axis-unit", 'axes."mesh:uniform:size".unit', right)]


@pytest.mark.parametrize("axis", [
    '[axes."component:square:assign.domain.datasets.relative_permittivity"]\nclass = "physical sweep"\n'
    'values = ["definition"]\nunit = "m"\n',
    '[axes."study:check:numerics.element.degree"]\nclass = "numerical convergence"\nvalues = [1, 2]\nunit = "m"\n',
], ids=["over a dataset", "over a dimensionless field"])
def test_an_axis_over_what_has_no_unit_states_none(laplace, axis):
    """Fails if an axis over a dataset, or over a field with no dimension, states a unit and
    `project check` takes it (models.md § 5.1: "over a dataset its names, over a dimensionless
    field plain numbers with no unit")."""
    kit.rewrite(laplace / "studies" / "check.toml", "[solve]\n", axis + "\n[crossing]\naxes = ["
                '"mesh:uniform:size", ' + f'"{axis[7:axis.index("]") - 1]}"]\nreason = "every pairing"\n\n'
                "[solve]\n")
    issues = [i for i in kit.run("project.check", project="laplace_square").issues
              if i.severity == "error" and i.file == "studies/check.toml"]
    assert [(i.code, i.key) for i in issues] == [("bad-axis-unit", f'axes."{axis[7:axis.index("]") - 1]}".unit')]


#: Each template's cases, as `study prep` wrote them before every quantity was written in the one
#: form — written as quantities in text, their axis values as text — each the SHA-256 of its
#: canonical JSON with its script's digest left out, which changed only as each script reads its
#: inputs as `definitions` (geometry.md §§ 2, 3); taken again at `case.json`'s second shape, its
#: step `potential` taking from others under `takes_from` and its mesh holding the recipe's mesher,
#: the content of the cases changed (models.md § 5.3).
BEFORE = {
    ("laplace_square", "check"): ["3c541c14a7d20abfe8dd9718123e53eb903b53f11d08ab628cfc100bade6e558",
                                        "60b5326ffc395ccbff6cb2dda8aad69024ee3ac8de4e1e708af3474e31b3899e",
                                        "d000dfcd377d1d7b6d0a0954d42bcdaa15c93db4f17236002f85ee98aa9d3632"],
    ("two_material", "benchmark"): ["6e9b4a42f11c9b9405d60c4057e18ca7ee6e613e91dfda0e26c8c7ac886ac3e1"],
}


@pytest.mark.parametrize("template, study", sorted(BEFORE))
def test_each_templates_cases_hold_the_values_they_held_before_the_one_quantity_form(tmp_path, template, study):
    """Fails if a template's cases, its quantities now written in the one form, differ in any value
    from those it made when they were written as text — the same exact numbers, the same
    dimensions, every default (models.md § 5.3: "Every value in exact form"; core.md § 11, "One
    quantity form")."""
    folder = kit.copy_template(tmp_path / "projects", template)
    kit.apply("study.prep", project=template, study=study)
    content = []
    for name, data in written(folder, study).items():
        data["component"]["files"].pop("geometry.py")
        content.append(cases.case_id(cases.Case.model_validate(data)))
    assert sorted(content) == BEFORE[(template, study)]


#: Each template's cases as `study prep` wrote them before `case.json` was read through a typed model
#: of its component, steps, mesh, numerics and point: the SHA-256 of each one's canonical JSON —
#: taken again at `case.json`'s second shape, as `BEFORE` was.
TYPED = {
    ("laplace_square", "check"): ["a7bd2bbbd6240462207b1fd80387c174672506d512c01c0f09c8ef07ddbc2fb7",
                                        "bbcdf9cfa4fae5c404e6ee6489f806560e4bcba96614d8521f41bd003dd056bb",
                                        "d69ecd9977189415ff0e6960c048165d1a2656159b2e7dde8ead86016bb22ceb"],
    ("two_material", "benchmark"): ["e3eea3efb026bbab7251ea8e7ecf07d18350ae4bb942d334e3aa1d34b2ae2f1f"],
}


@pytest.mark.parametrize("template, study", sorted(TYPED))
def test_each_templates_case_ids_are_those_written_before_the_case_was_a_typed_model(tmp_path, template, study):
    """Fails if a template's cases, written through `case.json`'s typed model, are not the very
    cases written before it — their canonical JSON changed by a change of femkit's own and not of
    the case's content, so every case written before reads as no longer made and its
    preparations `orphaned` (models.md § 5.3: "the case ID is the SHA-256 of `case.json`'s
    canonical JSON"; "`case.json` is a typed model")."""
    kit.copy_template(tmp_path / "projects", template)
    assert sorted(kit.apply("study.prep", project=template, study=study).added) == TYPED[(template, study)]


#: What a JSON schema node states that types its value: without one of these, it takes any value.
TYPED_BY = {"type", "$ref", "anyOf", "oneOf", "allOf", "enum", "const"}


def untyped(node: dict, at: str = "") -> list[str]:
    """Each place a model's JSON schema takes any value — a value of no type of its own, or a
    table whose keys may hold anything — by its path."""
    found = [] if TYPED_BY & set(node) else [at or "<the file>"]
    found += [f"{at}.*"] if node.get("additionalProperties") is True else []
    for key, inner in node.get("properties", {}).items():
        found += untyped(inner, f"{at}.{key}")
    for name, inner in node.get("$defs", {}).items():
        found += untyped(inner, name)
    for key in ("items", "additionalProperties"):
        found += untyped(node[key], f"{at}[]") if isinstance(node.get(key), dict) else []
    for inner in [*node.get("anyOf", []), *node.get("oneOf", []), *node.get("allOf", [])]:
        found += untyped(inner, at)
    return found


@pytest.mark.parametrize("model", ["case", "stage"])
def test_case_json_and_what_a_stage_is_made_from_of_it_are_typed_in_every_key(model):
    """Fails if a key of `case.json` — of its component, steps, mesh, numerics or point — or of the
    component and recipe a stage's `stage.json` keeps of a case is held by no field of a model: a
    table read back by its keys' names, which takes a misspelled key, and which its reference page
    cannot document (models.md § 5.3: "`case.json` is a typed model — its component, steps, mesh,
    numerics and point each a model of their own, which its writer, the workflow's readers, a
    stage's `stage.json` and the reference page read"; workflow.md § 4)."""
    assert untyped({"case": cases.Case, "stage": MadeFrom}[model].model_json_schema()) == []


def test_a_projects_next_steps_are_its_parts_states_prep_for_each_study_whose_cases_it_can_make(laplace):
    """Fails if `project check`, `study list`, `case list` and the project's graph do not offer
    `study prep` for each study whose cases prep can make — the step the part's state table gives,
    never one a result writes — or offer it for a study whose cases prep cannot make, a part it uses
    having a finding (projects.md § 8: "a project whose parts are `complete` offers `study prep` for
    each study whose cases prep can make; `project check`, `study list`, … `case list` … fill their
    `next` from those rows")."""
    def offered() -> dict[str, list]:
        results = {name: kit.run(name, project="laplace_square") for name in ("project.check", "study.list",
                                                                              "case.list")}
        assert all(b.label == ALLOWED for r in results.values() for b in r.report.blocks if isinstance(b, view.Next))
        steps = {name: r.next for name, r in results.items()}
        steps["project.graph"] = [a for n in kit.run("project.graph", project="laplace_square").graph.nodes
                                  for a in n.actions]
        return {name: [(a.call.operation, a.call.request) for a in held] for name, held in steps.items()}

    names = ("project.check", "study.list", "case.list", "project.graph")
    assert offered() == dict.fromkeys(names, [("study.prep", {"project": "laplace_square", "study": s})
                                              for s in ("check",)])
    kit.rewrite(laplace / "physics/electrostatics.toml", 'kind = "insulating"', 'kind = "grounded"')
    assert offered() == dict.fromkeys(names, [])


def test_a_refusal_on_findings_carries_every_finding_it_rests_on(laplace):
    """Fails if `study prep`, refused while parts its study uses have findings, carries only the first
    of them, or none, so the person learns of them one at a time (core.md § 9: `Refusal.issues`, "the
    findings it rests on"; plan § 4, X: "`has-findings` with every finding, not the first and a
    count")."""
    kit.rewrite(laplace / "physics/electrostatics.toml", 'kind = "insulating"', 'kind = "grounded"')
    kit.rewrite(laplace / "studies" / "check.toml", "values = [0.1, 0.05, 0.025]", "values = [0.1, 0]")
    errors = [i for i in kit.run("project.check", project="laplace_square").issues if i.severity == "error"]
    with kit.refused(Refused, "has-findings") as caught:
        prepped()
    assert len({i.subject.split(":")[1] for i in errors}) == 2 and list(caught.value.issues) == errors
