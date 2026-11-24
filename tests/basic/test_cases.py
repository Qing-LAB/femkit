"""Cases: resolved, named by their content, expanded from a study (models.md § 2, § 5)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from femkit import registry
from femkit.core.errors import Refused
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.models import cases
from femkit.models.project import load_model, load_study, model_file, study_file

from tests.basic.test_models import edit, examples


@pytest.fixture
def project(tmp_path) -> Path:
    model, study = examples()
    model_file(tmp_path).write_text(model)
    study_file(tmp_path, "check").parent.mkdir(parents=True)
    study_file(tmp_path, "check").write_text(study)
    return tmp_path


def ctx() -> Context:
    return Context.from_process()


def set_axes(project: Path, block: str) -> None:
    """The study's axes replaced by ``block``."""
    path = study_file(project, "check")
    text = path.read_text()
    start = text.index('[axes."numerics.mesh.size"]')
    end = text.index("[observables.midpoint]")
    path.write_text(text[:start] + block.strip() + "\n\n" + text[end:])


def produced(project: Path, study: str = "check") -> list[cases.Case]:
    m = load_model(project, ctx())
    return cases.expand(m, load_study(project, study, ctx(), m), catalogue.formulations(ctx()),
                        catalogue.units(ctx()), project)


def ids(project: Path, study: str = "check") -> list[str]:
    return [c.id for c in produced(project, study)]


def apply(name: str, **request):
    op = registry.operations()[name]
    plan = op.plan(op.request_from(request), ctx())
    return op.apply(plan, ctx())


def run(name: str, **request):
    op = registry.operations()[name]
    return op.run(op.request_from(request), ctx())


def test_two_spellings_of_one_value_give_one_case(project):
    """Fails if "500 nm" and "0.5 µm", or a coordinate or a direction written two ways, give two
    case IDs: a sweep would solve one case twice (models.md § 2, § 5)."""
    edit(model_file(project), 'bias = "1 V"', 'bias = "1 V"\ngap = "500 nm"')
    set_axes(project, '[axes."parameters.gap"]\nclass = "physical sweep"\nvalues = ["500 nm", "0.5 µm", "5e-7 m"]')
    assert len(set(ids(project))) == 1 and len(produced(project)) == 1
    before = ids(project)
    edit(model_file(project), "normal = [-1, 0]", "normal = [-1.0, 0]")
    edit(model_file(project), "size = [1, 1]", 'size = ["1 m", 1.0]')
    assert ids(project) == before
    edit(model_file(project), 'unit = "m"', 'unit = "mm"')  # the same geometry, its bare numbers in millimetres
    edit(model_file(project), 'size = ["1 m", 1.0]', 'size = ["1 m", 1000]')
    edit(model_file(project), "point = [1, 0]", "point = [1000, 0]")
    assert ids(project) == before


def test_what_differs_in_the_physics_gives_another_case_and_the_studys_own_choices_none(project):
    """Fails if a case ID ignores a change of the physics — a value, a renamed region — or
    changes with what never enters a case: observables, display units, bindings (models.md § 5)."""
    before = ids(project)
    edit(study_file(project, "check"), 'display = ["m", "V", "V/m"]', 'display = ["nm"]')
    edit(study_file(project, "check"), 'reduction = "value"', 'reduction = "maximum"')
    edit(study_file(project, "check"), 'memory = "2G" }   # jobs.md', 'memory = "4G" }   # jobs.md')
    assert ids(project) == before
    edit(model_file(project), 'bias = "1 V"', 'bias = "2 V"')
    assert set(ids(project)).isdisjoint(before)
    after_value = ids(project)
    for path in (model_file(project), study_file(project, "check")):  # the study's mesh size names it too
        path.write_text(path.read_text().replace("left", "west"))
    assert set(ids(project)).isdisjoint(after_value)


def test_a_parameter_axis_recomputes_the_parameters_that_depend_on_it(project):
    """Fails if a parameter swept by an axis leaves the parameters computed from it at their
    old value (models.md § 5)."""
    edit(model_file(project), 'bias = "1 V"', 'bias = "1 V"\ngap = "100 nm"\nhalf = "gap / 2"')
    set_axes(project, '[axes."parameters.gap"]\nclass = "physical sweep"\nvalues = ["300 nm"]')
    (case,) = produced(project)
    assert case.data["model"]["parameters"]["half"]["value"] == "3/20000000"


def test_an_incomplete_model_or_unexplained_crossed_classes_expand_to_nothing(project):
    """Fails if cases are written from a model `model check` faults, or a study crosses axes of
    different classes without saying why (models.md § 5)."""
    mesh = '[axes."numerics.mesh.size"]\nclass = "numerical convergence"\nvalues = ["0.1 m", "0.05 m", "0.025 m"]'
    degree = '[axes."numerics.element.degree"]\nclass = "physical sweep"\nvalues = [1, 2]'
    set_axes(project, mesh + "\n\n" + degree)
    with pytest.raises(Refused, match="different classes"):
        produced(project)
    set_axes(project, '[axes]\nreason = "the convergence rate per degree"\n\n' + mesh + "\n\n" + degree)
    assert len(produced(project)) == 6
    edit(model_file(project), 'sides = { kind = "insulating" }\n', "")
    with pytest.raises(Refused, match="finding"):
        produced(project)


def test_expand_writes_each_case_once(project):
    """Fails if a second expansion writes again, or a case.json's content is not its ID
    (models.md § 5)."""
    first = apply("study.expand", project=str(project), study="check")
    assert len(first.added) == 3 and first.kept == []
    for cid in first.added:
        data = json.loads((cases.case_dir(project, cid) / "case.json").read_text())
        assert cases.case_id(data) == cid
        assert data["numerics"]["mesh"]["size"] == data["point"]["numerics.mesh.size"]  # the axis is applied
    second = apply("study.expand", project=str(project), study="check")
    assert second.added == [] and sorted(second.kept) == sorted(first.added)
    listed = run("case.list", project=str(project)).cases
    assert {c.id for c in listed} == set(first.added) and all(c.studies == ["check"] for c in listed)


def test_study_copy_keeps_the_text_and_never_overwrites(project):
    """Fails if a copied study loses its comments, or a copy replaces a study already there."""
    apply("study.copy", project=str(project), study="check", to="sweep")
    assert study_file(project, "sweep").read_text() == study_file(project, "check").read_text()
    with pytest.raises(Refused):
        apply("study.copy", project=str(project), study="check", to="sweep")


def table_model(project: Path, rows: str, convention: str, phasor: str = "exp(-iwt)"):
    model_file(project).write_text(examples()[0])
    table = project / "custom" / "gold.csv"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(rows)
    digest = hashlib.sha256(table.read_bytes()).hexdigest()
    model_file(project).write_text(model_file(project).read_text().replace(
        '[materials.vacuum.relative_permittivity]',
        f'[conventions]\nphasor = "{phasor}"\n\n[materials.gold.relative_permittivity]\ntable = "custom/gold.csv"\n'
        f'sha256 = "{digest}"\nvariable = {{ name = "wavelength", unit = "nm" }}\ninterpolation = "linear"\n'
        f'convention = "{convention}"\nsource = "test"\nrange = ["500 nm", "700 nm"]\n\n'
        '[materials.vacuum.relative_permittivity]'))
    return load_model(project, ctx())


def test_a_table_is_converted_to_the_models_convention_and_a_gain_medium_refused(project):
    """Fails if a tabulated property keeps its source's convention, loses its rows' exact values,
    or a passive material made active by a convention mismatch is accepted (materials.md § 6)."""
    m = table_model(project, "500, -5.5, -2.1\n700, -16.5, -1.1\n", "exp(+iwt)")
    m = m.model_copy(update={"parameters": {**m.parameters, "wavelength": "600 nm"}})
    resolved = cases.resolve(m, None, {}, catalogue.units(ctx()), project)
    gold = resolved["model"]["materials"]["gold"]["relative_permittivity"]
    assert gold["rows"][0] == ["1/2000000", "-11/2", "21/10"] and gold["converted"].startswith("conjugated")
    m = table_model(project, "500, -5.5, -2.1\n", "exp(-iwt)")  # already the model's: loss would be negative
    m = m.model_copy(update={"parameters": {**m.parameters, "wavelength": "600 nm"}})
    with pytest.raises(Refused, match="wrong sign"):
        cases.resolve(m, None, {}, catalogue.units(ctx()), project)
    (project / "custom" / "gold.csv").write_text("500, -5.5, 2.1\n")  # changed since it was named
    with pytest.raises(Refused, match="sha256"):
        cases.resolve(m, None, {}, catalogue.units(ctx()), project)


def test_a_case_outside_a_propertys_range_is_refused(project):
    """Fails if a case is resolved at a value of a property's variable outside the range its
    source covers, or with no value for that variable at all (materials.md § 6)."""
    m = table_model(project, "500, -5.5, 2.1\n700, -16.5, 1.1\n", "exp(-iwt)")
    units = catalogue.units(ctx())
    with pytest.raises(Refused, match="states no parameter 'wavelength'"):
        cases.resolve(m, None, {}, units, project)
    m = m.model_copy(update={"parameters": {**m.parameters, "wavelength": "600 nm"}})
    cases.resolve(m, None, {}, units, project)
    with pytest.raises(Refused, match="outside its range"):
        cases.resolve(m, None, {"parameters.wavelength": "800 nm"}, units, project)
