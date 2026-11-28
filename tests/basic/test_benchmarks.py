"""The formulation's benchmark set (models.md §§ 4.3, 6.3; docs/science/electrostatics.md § 9).
Protected (testing.md § 3): a science test's design may change, its existence may not."""

from __future__ import annotations

import pytest

from tests import kit
from femkit.definitions import catalogue
from femkit.models import parts
from femkit.models import definitions
from femkit.projects import checking
from femkit.projects.layout import held


def test_the_two_material_reference_follows_from_its_own_template():
    """Fails if a reference value of `two_material` is not what the physics of its own template
    gives — the template's definitions `interface`, `length`, `height` and `bias`, the materials its
    component assigns to each layer, and, for each observable of its observables part, where the
    science document places it: a potential halfway up, in the middle of the first layer, on the
    interface, in the middle of the second; an energy over the group it takes — or names an
    observable the part does not give — so a slip in the declaration, or in the template, would make
    every engine's proof fail, or pass wrongly (docs/science/electrostatics.md § 9.1; models.md § 2:
    "a test computes the reference from the template itself"; § 4.3: the reference names the
    part's observables)."""
    ctx = kit.ctx()
    f = catalogue.formulations(ctx)["electrostatics"]
    bench = f.benchmarks["two_material"]
    opened = kit.opened(catalogue.templates(ctx)[bench.project])
    c = checking.Checking.of(opened, ctx, definitions.defined(opened, ctx, compute=False))
    a, length, height, v = (c.definitions[n].value for n in ("interface", "length", "height", "bias"))
    (component,) = [p for p in opened.parts.values() if p.address.kind == "component"]
    contract = parts.contract(opened, component)

    def permittivity(layer: str):
        (dataset,) = parts.datasets(c, parts.material(opened, contract.assign[layer].material))[
            "relative_permittivity"].values()
        return c.units.measure(held(dataset.data, "value")).value

    eps = {layer: permittivity(layer) for layer in ("low", "high")}
    eps0 = c.units.measure(f.constants["vacuum_permittivity"].value).value
    d = v / (a / eps["low"] + (length - a) / eps["high"])                 # D / eps_0, the same in both layers
    phi = lambda x: d * x / eps["low"] if x <= a else d * a / eps["low"] + d * (x - a) / eps["high"]  # noqa: E731
    width = {"low": a, "high": length - a}
    where = {"potential_low": a / 2, "potential_middle": a, "potential_high": (a + length) / 2}   # § 9.1's table
    (observed,) = [p.data for p in opened.parts.values() if p.address.kind == "observables"]
    expected = {}
    for name, o in observed.observables.items():
        if o.takes.groups:                                                # (1/2) eps E^2 over the layer's area
            (group,) = o.takes.groups
            expected[name] = eps0 * eps[group] * (d / eps[group]) ** 2 / 2 * width[group] * height
        else:
            expected[name] = phi(where[name])
    declared = {k: c.units.measure(t).value for k, t in bench.reference.items()}
    assert declared == expected
    assert (expected["potential_middle"], phi(length)) == (phi(a), v)     # the bias across, the interface between


@pytest.mark.parametrize("file, old, new", [
    ("templates/two_material/physics/electrostatics.toml", 'kind = "interface"', 'kind = "interfaces"'),  # a fault
    ("formulations/electrostatics.toml", 'potential_middle = {value = 0.8, unit = "V"}',
     'potential_middle = {value = 0.8, unit = "V"}\nnowhere = {value = 1, unit = "V"}'),
    ("formulations/electrostatics.toml", 'potential_low = {value = 0.4, unit = "V"}',
     'potential_low = {value = 0.4, unit = "m"}'),  # another dimension
])
def test_schema_check_refuses_a_benchmark_that_is_not_complete_or_misnames_its_reference(definitions, file, old,
                                                                                         new):
    """Fails if a benchmark whose template `project check` faults, or whose reference names no
    observable of the observables part reading its studies, or is in another dimension, passes
    `schema check` (models.md § 4.3)."""
    kit.rewrite(definitions / file, old, new)
    result = kit.run("schema.check")
    assert not result.ok() and any(i.code == "benchmark-invalid" and i.subject.endswith("benchmarks.two_material")
                                   for i in result.issues)
