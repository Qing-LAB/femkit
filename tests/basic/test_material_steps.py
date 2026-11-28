"""A material's data under a study's steps (materials.md § 6): until a case converts a dataset or
takes it at a variable's value, a dataset held under an equivalent form, one that varies with a
variable the step does not supply, and a value whose range is not `all` under a step that supplies
none are each an error of `project check` at the assignment, saying what would be right, and
`study prep` refuses a case resting on one. On copies of the two-material template; the forms
themselves and their checks are tests/basic/test_material_forms.py's."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests import kit
from tests.kit import slab  # noqa: F401 -- a fixture
from femkit.core.errors import Refused

COMPONENT = "components/slab/component.toml"
HIGH = "materials/dielectric_2/material.toml"     # the material filling the slab's `high`
AT = "assign.high.datasets.relative_permittivity"  # where an assignment names the dataset the physics reads
STATED = 'convention = "real"\nsource = "a test\'s own"\n'
ROWS = "wavelength,eps\n0.5,2.25\n0.6,2.2\n"


def value(name: str, held: str = "4", form: str = "relative_permittivity", range_: str = '"all"') -> str:
    """A dataset that is a value, as a material's file writes it."""
    return f'[properties.{form}.{name}]\nvalue = {held}\n{STATED}range = {range_}\n\n'


def table(name: str) -> str:
    """A dataset that is a table in the wavelength, as a material's file writes it; its file is
    `ROWS`, beside it."""
    return (f'[properties.relative_permittivity.{name}]\ntable = "{name}.csv"\n'
            f'sha256 = "{hashlib.sha256(ROWS.encode()).hexdigest()}"\ninterpolation = "linear"\n{STATED}'
            f'range = {{value = [0.5, 0.6], unit = "um"}}\n\n[properties.relative_permittivity.{name}.variable]\n'
            'name = "wavelength"\n'
            'unit = "um"\n\n')


def holding(slab: Path, *datasets: str, named: str | None = None) -> None:
    """The material filling `high` holding ``datasets`` alone, a table's file beside it, and the
    assignment of `high` naming the dataset ``named``, where one is."""
    (slab / HIGH).write_text('schema = 1\ndisplay = "Dielectric 2"\n\n' + "".join(datasets))
    (slab / "materials/dielectric_2/measured.csv").write_text(ROWS)
    text = (slab / COMPONENT).read_text()
    (slab / COMPONENT).write_text(text[:text.index("[assign.high]")] + '[assign.high]\nmaterial = "dielectric_2"\n'
                                  + (f'datasets = {{ relative_permittivity = "{named}" }}\n' if named else ""))


def at_assignment(slab: Path) -> list[tuple]:
    """Every finding `project check` makes on the component: its severity, code, key, right value
    and choices."""
    return [(i.severity, i.code, i.key, i.right, i.choices)
            for i in kit.run("project.check", project=slab.name).issues if i.file == COMPONENT]


def test_a_dataset_held_under_an_equivalent_form_is_an_error_at_the_assignment_before_prep(slab):
    """Fails if a dataset held under an equivalent form of the property the physics reads passes
    `project check`, to be refused only by `study prep` — rather than an error `form-unconverted`
    at the assignment's `datasets.<property>`, whose choices are the datasets held as the property
    itself, what would be right — or if `study prep` writes a case resting on it, or refuses it
    as a statement missing rather than a state that does not allow it (materials.md § 6: "one held
    under an equivalent form is a finding of `project check` at the assignment's
    `datasets.<property>`, `form-unconverted`, saying what would be right — a dataset of the
    property the formulation reads — and `study prep` refuses a case resting on it"; core.md
    § 9)."""
    holding(slab, value("johnson", "2", "refractive_index"))
    assert at_assignment(slab) == [("error", "form-unconverted", AT, None, ())]
    with kit.refused(Refused, "has-findings", "component:slab"):
        kit.apply("study.prep", project=slab.name, study="benchmark")
    assert not (slab / "cases").exists()
    holding(slab, value("benchmark"), value("johnson", "2", "refractive_index"), named="johnson")
    assert at_assignment(slab) == [("error", "form-unconverted", AT, None, ('"benchmark"',))]


@pytest.mark.parametrize("datasets, named, choices", [
    ((table("measured"),), None, ()),
    ((value("benchmark"), table("measured")), "measured", ('"benchmark"',)),
    ((value("benchmark", range_='{value = [400, 800], unit = "nm"}'),), None, ()),
    ((value("benchmark", range_='{value = [400, 800], unit = "nm"}'), value("static"), table("measured")), "benchmark",
     ('"static"',)),
], ids=["a table alone", "a table, a value beside it", "a value over a range", "a value over a range, beside others"])
def test_a_dataset_that_does_not_hold_under_a_stationary_step_is_an_error_naming_those_that_would(slab, datasets,
                                                                                                    named, choices):
    """Fails if a dataset the stationary step would take that varies with a variable it does not
    supply — a table in the wavelength — or a value whose range is not `all`, which holds only
    there and never at zero frequency, is not an error `dataset-varies` at the assignment's
    `datasets.<property>`, whose choices are the material's datasets that would hold there — a
    value of the property, its range `all`; or if a value whose range is `all` is (materials.md
    § 6: "saying what would be right — a dataset that holds there: for a static step, a `value`
    of the property at zero frequency, its range `all`"; "A `value` whose range is not `all` …
    is refused under a static step the same way"; material-data.md § 7)."""
    holding(slab, *datasets, named=named)
    assert at_assignment(slab) == [("error", "dataset-varies", AT, None, choices)]
    holding(slab, value("benchmark"))
    assert at_assignment(slab) == []
