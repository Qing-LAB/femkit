"""The check frame (projects.md § 6; models.md §§ 3, 11.1): what each part kind's check is handed,
the project's parameters resolved once, a finding made at its part's file and key, and the run in
the chain's order — on a copy of a template, with checks of the test's own registered as a
package's are."""

from __future__ import annotations

import importlib
from fractions import Fraction

import pytest

from tests import kit
from tests.kit import slab  # noqa: F401 -- a fixture
from femkit import registry
from femkit.core.units import Quantity
from femkit.projects import checking, door, schemas
from femkit.projects import state as part_state

METRE = (("length", 1),)


def test_each_loaded_part_is_checked_and_the_findings_come_errors_first_each_in_the_chains_order(slab):
    """Fails if a registered check is not handed each loaded part of its kind with the frame, is
    handed a part that does not load, or if the findings — the door's, the checks', what cannot
    be checked yet — do not come the errors first, then the warnings, then the notes, each part
    by part in the chain's order, those on no part last; or if a check's finding does not carry
    its part's file, its key and what would be right as the file writes it (models.md § 11.2:
    "orders its findings by the chain ... the first is the project's next step"; core.md § 10)."""
    (slab / "mesh/uniform.toml").write_text("size = \n")                        # unloadable
    (slab / "notes.txt").write_text("")                                         # a stray
    seen: list[str] = []

    def study(c: checking.Checking, part: door.Part):
        seen.append(str(part.address))
        yield c.issue(part, "steps", "solve", "kind", code="no-such-kind", message="m", choices=["stationary"])

    def physics(c: checking.Checking, part: door.Part):
        seen.append(str(part.address))
        assert c.opened.part(part.address) is part and c.places and c.properties and c.formulations
        return [c.issue(part, "conditions", "left", "kind", code="wrong-kind", message="m", right="potential")]

    def mesh(c, part):
        raise AssertionError("a part that does not load is never checked")

    def material(c: checking.Checking, part: door.Part):
        seen.append(str(part.address))
        return [c.unchecked(part, "properties", message="m"),
                *([c.issue(part, "display", code="a-warning", message="m", severity="warning")]
                  if part.address.name == "dielectric_1" else [])]

    with kit.own_parts(checks={"models.study": study, "models.physics": physics, "geometry.recipe": mesh,
                               "materials.material": material}):
        opened = kit.opened(slab)
        found = checking.run(opened, kit.ctx())
    states = part_state.observe(kit.ctx(), opened, found)
    mine = [i for i in found if i.message == "m" or i.code in ("unloadable", "stray")]   # the test's own, the door's
    assert [(i.code, i.subject, i.file, i.key, i.right, i.choices, i.severity) for i in mine] == [
        ("unloadable", "mesh:uniform", "mesh/uniform.toml", None, None, (), "error"),
        ("wrong-kind", "physics:electrostatics:conditions.left.kind", "physics/electrostatics.toml",
         "conditions.left.kind", '"potential"', (), "error"),
        ("no-such-kind", "study:benchmark:steps.solve.kind", "studies/benchmark.toml", "steps.solve.kind", None,
         ('"stationary"',), "error"),
        ("a-warning", "material:dielectric_1:display", "materials/dielectric_1/material.toml", "display", None, (),
         "warning"),
        ("stray", "notes.txt", "notes.txt", None, None, (), "warning"),
        (door.UNCHECKED, "material:dielectric_1:properties", "materials/dielectric_1/material.toml", "properties",
         None, (), "info"),
        (door.UNCHECKED, "material:dielectric_2:properties", "materials/dielectric_2/material.toml", "properties",
         None, (), "info")]
    assert [i.severity for i in found] == sorted((i.severity for i in found), key=checking.SEVERITIES.index)
    assert sorted(seen) == ["material:dielectric_1", "material:dielectric_2", "physics:electrostatics", "study:benchmark"]
    assert (states["material:dielectric_1"], states["mesh:uniform"], states["physics:electrostatics"]) == \
        ("findings", "unloadable", "findings")


@pytest.mark.parametrize("changes, head", [
    ([], "slab: every part loads and checks; 1 note"),
    ([("notes.txt", "")], "slab: no errors; 1 warning, 1 note; the first is the next step"),
    ([("notes.txt", ""), ("mesh/uniform.toml", "size = \n")],
     "slab: 1 error, 1 warning, 2 notes; the first is the next step"),
], ids=["notes alone", "a warning", "an error and a warning"])
def test_the_first_line_of_project_check_says_what_findings_stand_and_no_more(slab, changes, head):
    """Fails if `project check`'s first line claims every part loads and checks while a warning
    stands, or counts its findings otherwise than as errors, warnings and notes (models.md § 11.2:
    "the first is the project's next step")."""
    for file, text in changes:
        (slab / file).write_text(text)
    assert kit.run("project.check", project="slab").report().blocks[0].text == head


def test_the_parameters_resolve_by_name_in_any_order_and_a_circle_is_a_finding_naming_it(slab):
    """Fails if a parameter using one written below it does not resolve, exactly; if parameters
    using each other in a circle are not one finding naming the circle, or one whose own text does
    not read is not a finding at its key; or if one using a parameter that does not resolve
    resolves, or is a finding of its own (models.md § 3: "An expression may use any other
    parameter, in any order in the file; parameters that use each other in a circle are a finding
    naming the circle")."""
    kit.rewrite(slab / "project.toml", 'bias = "1 V"', 'bias = "1 V"\nwide = "length * 3 / 2"\n'
                                                       'c = "d + 1 m"\nd = "c"\ne = "c * 2"\nf = "1 m + 1 V"\n')
    c = checking.Checking.of(kit.opened(slab), kit.ctx())
    assert c.parameters["wide"] == Quantity(Fraction(3, 2), METRE) and c.parameters["interface"] == Quantity(Fraction(1, 2), METRE)
    assert c.unresolved == {"c", "d", "e", "f"}
    assert [(i.code, i.subject, i.file, i.key) for i in c.issues] == [
        ("parameter-circle", "project:parameters.c", "project.toml", "parameters.c"),
        ("bad-quantity", "project:parameters.f", "project.toml", "parameters.f")]
    assert "c → d → c" in c.issues[0].message
    assert c.quantity("wide - interface") == Quantity(Fraction(1), METRE)


def test_the_registry_registers_each_part_schema_and_check_its_packages_declare_once():
    """Fails if a schema or a check a module of PARTS declares beside it (`PART_SCHEMAS`,
    `PART_CHECKS`) is not registered with the door or the check frame under its key at femkit's
    start — a project's parts would then load unchecked, and every template pass — or a second
    start registers a check again (api.md § 6; models.md § 11.1)."""
    registry.operations()
    registry.operations()                                           # every start registers each once
    declared: dict[str, list] = {}
    for name in registry.PARTS:
        module = importlib.import_module(name)
        assert all(schemas.registered()[key] is model for key, model in module.PART_SCHEMAS.items()), name
        for key, check in module.PART_CHECKS.items():
            declared.setdefault(key, []).append(check)
    assert {key: list(checking.registered()[key]) for key in declared} == declared
