"""The formulation's benchmark set (models.md § 4, § 6.3; docs/science/electrostatics.md § 9)."""

from __future__ import annotations

from fractions import Fraction

import pytest

from tests.kit import ctx
from femkit import registry
from femkit.core.operations import Context
from femkit.definitions import catalogue


def test_the_two_material_reference_follows_from_its_own_model():
    """Fails if a reference value of `two_material` is not what the physics of its own model
    gives — a slip in the declaration would make every engine's proof fail, or pass wrongly
    (docs/science/electrostatics.md § 9.1)."""
    from femkit.models.project import load_model
    f = catalogue.formulations(ctx())["electrostatics"]
    bench = f.benchmarks["two_material"]
    units = catalogue.units(ctx())
    m = load_model(catalogue.data_root() / "formulations" / bench.project, ctx())
    a = Fraction(m.geometry.shapes["left_half"].size[0])                     # the interface, in metres
    e1 = units.parse(m.materials[m.assign["low"]]["relative_permittivity"].value).value
    e2 = units.parse(m.materials[m.assign["high"]]["relative_permittivity"].value).value
    v = units.parse(m.parameters["bias"]).value
    eps0 = units.parse(f.constants["vacuum_permittivity"].value).value
    d = v / (a / e1 + (1 - a) / e2)                                           # D / eps_0, continuous across
    phi = lambda x: d * x / e1 if x <= a else d * a / e1 + d * (x - a) / e2   # noqa: E731
    expected = {"potential_low": phi(Fraction(1, 4)), "potential_middle": phi(a),
                "potential_high": phi(Fraction(3, 4)),
                "energy_low": eps0 * e1 * (d / e1) ** 2 / 2 * a,               # (1/2) eps E^2 over the layer's area
                "energy_high": eps0 * e2 * (d / e2) ** 2 / 2 * (1 - a)}
    declared = {k: units.parse(t).value for k, t in bench.reference.items()}
    assert declared == expected


@pytest.mark.parametrize("old, new", [
    ('middle = { kind = "interface" }\n', ""),                                   # a named interface left bare
    ('potential_middle = "4/5 V"', 'potential_middle = "4/5 V"\nnowhere = "1 V"'),  # a reference to no observable
    ('potential_low = "2/5 V"', 'potential_low = "2/5 m"'),                      # a reference in another dimension
])
def test_schema_check_refuses_a_benchmark_that_is_not_complete_or_misnames_its_reference(definitions,
                                                                                         old, new):
    """Fails if a benchmark project `model check` faults, or a reference naming no observable,
    or in another dimension, passes `schema check` (models.md § 4)."""
    data = definitions
    for path in [data / "formulations" / "electrostatics.toml",
                 *(data / "formulations" / "electrostatics" / "benchmarks").rglob("*.toml")]:
        text = path.read_text()
        if old in text:
            path.write_text(text.replace(old, new))
            break
    else:
        pytest.fail(f"{old!r} is in no file")
    op = registry.operations()["schema.check"]
    result = op.run(op.request_from({}), Context.from_process())
    assert not result.ok() and any(i.code == "benchmark-invalid" and i.subject.endswith("benchmarks.two_material")
                                   for i in result.issues)
