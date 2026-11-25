"""A study's cases (models.md § 5.3): one `case.json` per axis point, complete and exact, in the
study's own folder, named by the SHA-256 of its canonical JSON — so two spellings of one value are
one case of the study, and two studies never share one; refused while a part the study uses does
not load or has a finding; listed under the study that made them, with whether each study expands
and why not. On copies of the templates."""

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
from femkit.models import cases
from femkit.projects import door

AXIS = '[axes."mesh:uniform:size"]\n# why it varies: one of `numerical convergence`, `geometry convergence`, `physical sweep`\nclass = "numerical convergence"\n# its values, in order, each written as the value the axis varies is written in its own file\nvalues = ["0.1 m", "0.05 m", "0.025 m"]\n'


def written(folder: Path, study: str = "check") -> dict[str, dict]:
    """Every case.json in the study's folder of the project's cases/, by the folder it is in."""
    return {p.parent.name: json.loads(p.read_text())
            for p in sorted((folder / "cases" / study).glob("*/case.json"))}


def expand(name: str = "laplace_square", study: str = "check"):
    return kit.apply("study.expand", project=name, study=study)


def test_expand_writes_one_complete_case_per_point_named_by_its_content(laplace):
    """Fails if `study expand` does not write the Laplace study's three cases in the study's own
    folder, each `case.json` in the shape models.md § 5.3 states — every quantity exact, every
    other number its exact text, every default written, nothing of the study's own beyond its
    numerics — under the SHA-256 of its canonical JSON; or writes one again (models.md § 5.3)."""
    outcome = expand()
    cases_there = written(laplace)
    assert outcome.ok() and sorted(outcome.added) == sorted(cases_there) and len(cases_there) == 3
    assert sorted(p.relative_to(laplace).as_posix() for p in (laplace / "cases").rglob("case.json")) == sorted(
        cases.path("check", i) for i in cases_there)
    for name, data in cases_there.items():
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        assert hashlib.sha256(canonical).hexdigest() == name
        assert sorted(data) == ["component", "mesh", "numerics", "point", "schema", "steps"]
        assert cases.read(json.dumps(data), name).schema_ == 1
    assert len({json.dumps(d["point"]) for d in cases_there.values()}) == 3
    one = next(iter(cases_there.values()))
    assert one["numerics"] == {"element": {"family": "lagrange", "degree": "1"},
                               "solver": {"kind": "direct", "tolerance": None}}
    assert one["component"]["inputs"] == {"side": {"value": "1", "dimension": {"length": 1}}}
    assert one["steps"]["solve"]["physics"]["conditions"]["right"] == {
        "kind": "potential", "value": {"value": "1", "dimension": {"current": -1, "length": 2, "mass": 1, "time": -3}}}
    assert one["steps"]["solve"]["physics"]["meaning"] == "per unit depth"
    assert one["component"]["assign"]["domain"]["properties"]["relative_permittivity"] == {
        "dataset": "definition", "data": {"value": {"value": "1", "dimension": {}}, "convention": "real",
                                          "source": "the definition of vacuum: its relative permittivity is exactly 1",
                                          "range": "all"}}
    again = expand()
    assert again.added == [] and sorted(again.kept) == sorted(cases_there)


@pytest.mark.parametrize("values, cases_made", [
    ('["500 nm", "0.5 µm"]', 1),        # two spellings of one length: one case
    ('["500 nm", "0.6 µm"]', 2),        # two lengths: two
])
def test_two_spellings_of_one_value_give_one_case(laplace, values, cases_made):
    """Fails if "500 nm" and "0.5 µm" give two cases of one study — a value read through a binary
    float, or held as it is spelled — or two different lengths give one (models.md § 5.3: "500 nm"
    and "0.5 µm" give the same ID)."""
    kit.rewrite(laplace / "studies" / "check.toml", AXIS,
                f'[axes."project:parameters.side"]\nclass = "physical sweep"\nvalues = {values}\n')
    assert len(expand().added) == cases_made == len(written(laplace))


def test_two_studies_of_one_content_each_write_their_own_cases(laplace):
    """Fails if two studies whose cases have the same content share a case folder, or if
    expanding one keeps, rather than writes, a case the other wrote (models.md § 5.3: each
    study's cases are its own; nothing is shared between studies)."""
    (laplace / "studies" / "again.toml").write_text((laplace / "studies" / "check.toml").read_text())
    kit.rewrite(laplace / "project.toml", 'studies = ["check"]', 'studies = ["check", "again"]')
    first, second = expand(study="check"), expand(study="again")
    assert len(first.added) == len(second.added) == 3 and second.kept == []
    assert sorted(written(laplace, "check")) == sorted(written(laplace, "again")) == sorted(first.added)
    listed = {s.name: [c.id for c in s.written] for s in kit.run("case.list", project="laplace_square").studies}
    assert listed == {"again": sorted(second.added), "check": sorted(first.added)}


def test_every_parameter_is_computed_again_from_an_axis_value(laplace):
    """Fails if a parameter using the one an axis varies is not computed again from each value —
    `half = "side / 2"` holding half of each `side` in the case the component reads it in
    (models.md § 5.1: "a parameter's value with every parameter computed again from it"; § 5.3)."""
    kit.rewrite(laplace / "project.toml", 'bias = "1 V"', 'bias = "1 V"\nhalf = "side / 2"')
    kit.rewrite(laplace / "components" / "square" / "component.toml", 'side = "length"', 'side = "length"\n'
                                                                                         'half = "length"')
    kit.rewrite(laplace / "studies" / "check.toml", AXIS,
                '[axes."project:parameters.side"]\nclass = "physical sweep"\nvalues = ["1 m", "30 cm", "4 mm"]\n')
    assert len(expand().added) == 3
    inputs = [d["component"]["inputs"] for d in written(laplace).values()]
    held = sorted((Fraction(i["side"]["value"]), Fraction(i["half"]["value"])) for i in inputs)
    assert held == [(Fraction(1, 250), Fraction(1, 500)), (Fraction(3, 10), Fraction(3, 20)),
                    (Fraction(1), Fraction(1, 2))]


def test_a_number_written_two_ways_gives_one_case_and_an_observable_none(tmp_path):
    """Fails if a number's spelling — `1e-9` or `"1.0e-9"`, a material's `"1"` or `"1.0"` —
    changes a case's ID, if adding an observable does, or if a material's value does not
    (models.md § 5.3: "Every quantity — … a material's value or range, a mesh size — is written as
    {value, dimension}"; observable sets never enter a case)."""
    a = kit.copy_template(tmp_path / "projects", "laplace_square", "a")
    b = kit.copy_template(tmp_path / "projects", "laplace_square", "b")
    kit.rewrite(b / "mesh" / "uniform.toml", "tolerance = 1e-9", 'tolerance = "1.0e-9"')
    kit.rewrite(b / "materials" / "vacuum" / "material.toml", 'value = "1"', 'value = "1.0"')
    kit.rewrite(b / "observables" / "midpoint.toml", "[observables.potential_middle]",
                '[observables.field]\nquantity = "electric_field"\npoint = ["0 m", "0 m"]\nreduction = "value"\n'
                'unit = "V/m"\n\n[observables.potential_middle]')
    assert sorted(expand("a").added) == sorted(expand("b").added)
    kit.rewrite(b / "materials" / "vacuum" / "material.toml", 'value = "1.0"', 'value = "2"')
    changed = expand("b").added
    assert len(changed) == 3 and set(changed).isdisjoint(written(a))


@pytest.mark.parametrize("file, old, new, code, subject", [
    ("physics/electrostatics.toml", 'kind = "insulating"', 'kind = "grounded"', "has-findings",
     "physics:electrostatics"),
    ("studies/check.toml", AXIS, AXIS + '\n[axes."project:parameters.bias"]\nclass = "physical sweep"\n'
                                         'values = ["1 V", "2 V"]\n', "has-findings", "study:check"),
    ("project.toml", 'studies = ["check"]', "studies = []", "not-named", "study:check"),
    ("project.toml", 'components = ["square"]', "components = []", "not-named", "component:square"),
    ("physics/electrostatics.toml", 'value = "0 V"', 'value = "0 V', "unloadable", "physics:electrostatics"),
    ("mesh/uniform.toml", 'size = "0.1 m"', 'sise = "0.1 m"', "unloadable", "mesh:uniform"),
    ("project.toml", "[parameters]", "[parameters", "unloadable", "project"),
], ids=["a physics' finding", "the study's own finding", "the study not named", "its component not named",
        "a physics not loading", "a recipe not loading", "the project file not loading"])
def test_a_study_with_findings_or_not_named_is_refused_and_nothing_is_written(laplace, file, old, new, code,
                                                                              subject):
    """Fails if `study expand` writes cases, or fails otherwise than by a refusal naming the part,
    while a part the study uses does not load or has a finding — axes of different classes crossed
    without a `[crossing]` among them — or while the project file does not name the study or its
    component (models.md § 5.3; projects.md § 3: "inert, never loaded into a case")."""
    kit.rewrite(laplace / file, old, new)
    with kit.refused(Refused, code, subject):
        expand()
    assert not (laplace / "cases").exists()


@pytest.mark.parametrize("file, old, new, why", [
    ("physics/electrostatics.toml", 'value = "0 V"', 'value = "0 V', "the physics `electrostatics` does not load"),
    ("mesh/uniform.toml", 'size = "0.1 m"', 'sise = "0.1 m"', "the mesh `uniform` does not load"),
], ids=["a physics with an unclosed quote", "a recipe with a misspelled key"])
def test_a_study_using_a_part_that_does_not_load_lists_as_not_expanding_and_is_not_complete(laplace, file, old,
                                                                                           new, why):
    """Fails if `study list` or `case list` does not say a study using a part that does not load
    does not expand, naming that part, or if `project check` shows the study complete then
    (models.md § 11.1: "a study that does not expand, and why"; projects.md § 8)."""
    kit.rewrite(laplace / file, old, new)
    for verb in ("study.list", "case.list"):
        assert [(s.name, s.expands, s.why) for s in kit.run(verb, project="laplace_square").studies] == [
            ("check", False, why)]
    assert {p.part: p.state for p in kit.run("project.check", project="laplace_square").parts}["study:check"] \
        == "unchecked"


def test_case_list_shows_each_studys_cases_their_point_and_a_study_that_does_not_expand(laplace):
    """Fails if `case list` does not show each written case under its study, with its point and
    whether the study makes it now — one it no longer makes kept, with its point as its file holds
    it — or a study that does not expand and why (models.md § 5.3, § 11.1)."""
    expand()
    (study,) = kit.run("case.list", project="laplace_square").studies
    assert (study.name, study.expands, study.cases) == ("check", True, 3)
    assert sorted((c.point["mesh:uniform:size"], c.made) for c in study.written) == [
        (v, True) for v in ("0.025 m", "0.05 m", "0.1 m")]
    kit.rewrite(laplace / "studies" / "check.toml", 'mesh = "uniform"', 'mesh = "fine"')
    (study,) = kit.run("case.list", project="laplace_square").studies
    units = catalogue.units(kit.ctx())
    assert sorted((c.id, c.point, c.made) for c in study.written) == [
        (i, {k: cases.shown(v, units) for k, v in d["point"].items()}, False) for i, d in written(laplace).items()]
    assert (study.name, study.expands, study.cases) == ("check", False, 0) and study.why
    assert [(s.name, s.expands) for s in kit.run("study.list", project="laplace_square").studies] == [("check", False)]


def test_a_recipe_value_an_axis_varies_is_exact_in_the_case_and_in_its_dimension(laplace):
    """Fails if a value of the recipe an axis varies, written as a quantity, is not read in the
    dimension of the value it replaces, or the case holds it — in its point and its recipe — as
    it is spelled rather than exactly (models.md §§ 5.1, 5.3)."""
    kit.rewrite(laplace / "studies" / "check.toml", 'values = ["0.1 m", "0.05 m", "0.025 m"]',
                'values = ["100 mm", "0.1 m", "1 V"]')
    issues = kit.run("project.check", project="laplace_square").issues
    assert [(i.code, i.label) for i in issues if i.severity == "error"] == [("bad-axis-value", "1 V")]
    kit.rewrite(laplace / "studies" / "check.toml", '"1 V"]', '"0.05 m"]')
    assert len(expand().added) == 2
    tenth = {"value": "1/10", "dimension": {"length": 1}}
    assert any(d["point"] == {"mesh:uniform:size": tenth} and d["mesh"]["size"] == tenth
               for d in written(laplace).values())


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
