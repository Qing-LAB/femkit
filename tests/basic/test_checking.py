"""The check frame (projects.md § 6; models.md §§ 3, 11.1): what each part kind's check is handed,
the project's definitions resolved once, a finding made at its part's file and key, and the run in
the chain's order — on a copy of a template, with checks of the test's own registered as a
package's are."""

from __future__ import annotations

import sys
import types

import pytest

from tests import kit
from tests.kit import slab  # noqa: F401 -- a fixture
from femkit import registry
from femkit.models import definitions
from femkit.projects import checking, door, schemas
from femkit.projects import state as part_state

def test_each_loaded_part_is_checked_and_the_findings_come_errors_first_each_in_the_chains_order(slab):
    """Fails if a registered check is not handed each loaded part of its kind with the frame, is
    handed a part that does not load, or if the findings — the door's, the checks', what cannot
    be checked yet — do not come the errors first, then the warnings, then the notes, each part
    by part in the chain's order — by rank, then the kind's place, then name — those on no part
    last; or if a check's finding does not carry its part's file, its key and what would be right
    as the file writes it, or a part's state is moved by a warning (models.md § 11.2: "orders its
    findings by the chain ... the first is the project's next step"; projects.md § 4: "the chain's
    order, by rank, then the kind's place in this file, then name"; § 8: a warning or a note
    "changes no part's state"; core.md § 10)."""
    (slab / "mesh/uniform.toml").write_text("size = \n")                        # unloadable
    (slab / "notes.txt").write_text("")                                         # a stray
    seen: list[str] = []

    def study(c: checking.Checking, part: door.Part):
        seen.append(str(part.address))
        yield c.issue(part, "steps", "potential", "kind", code="no-such-kind", message="m", choices=["stationary"])

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
        found = checking.run(opened, kit.ctx(), definitions.defined(opened, kit.ctx(), compute=False))
    states = part_state.observe(kit.ctx(), opened, found)
    mine = [i for i in found if i.message == "m" or i.code in ("unloadable", "stray")]   # the test's own, the door's
    assert [(i.code, i.subject, i.file, i.key, i.right, i.choices, i.severity) for i in mine] == [
        ("wrong-kind", "physics:electrostatics:conditions.left.kind", "physics/electrostatics.toml",
         "conditions.left.kind", '"potential"', (), "error"),
        ("unloadable", "mesh:uniform", "mesh/uniform.toml", None, None, (), "error"),
        ("no-such-kind", "study:benchmark:steps.potential.kind", "studies/benchmark.toml",
         "steps.potential.kind", None, ('"stationary"',), "error"),
        ("a-warning", "material:dielectric_1:display", "materials/dielectric_1/material.toml", "display", None, (),
         "warning"),
        ("stray", "notes.txt", "notes.txt", None, None, (), "warning"),
        (door.UNCHECKED, "material:dielectric_1:properties", "materials/dielectric_1/material.toml", "properties",
         None, (), "info"),
        (door.UNCHECKED, "material:dielectric_2:properties", "materials/dielectric_2/material.toml", "properties",
         None, (), "info")]
    assert [i.severity for i in found] == sorted((i.severity for i in found), key=checking.SEVERITIES.index)
    assert sorted(seen) == ["material:dielectric_1", "material:dielectric_2", "physics:electrostatics",
                            "study:benchmark"]
    assert (states["material:dielectric_1"][:2], states["mesh:uniform"][:2], states["physics:electrostatics"][:2]) == (
        ("unchecked", "waiting"), ("unloadable", "needs attention"), ("errors", "needs attention"))


def test_every_finding_at_a_key_of_a_toml_part_names_the_line_its_key_stands_at(slab):
    """Fails if a finding at a key of a part's TOML file — a check's, or the door's for a key its
    schema does not allow — does not carry the line that key stands at, read from the file's own
    text as a Python file's line is, or carries one for a finding at no key (core.md § 10: `line`,
    "every finding at a key, a TOML file's as a Python file's, the door reading it from the file's
    text"; web.md § 7.4)."""
    physics = slab / "physics/electrostatics.toml"
    mesh = slab / "mesh/uniform.toml"
    mesh.write_text(mesh.read_text() + "\nszie = 1\n")
    (slab / "notes.txt").write_text("")                                          # a stray: at no key

    def check(c: checking.Checking, part: door.Part):
        return [c.issue(part, "conditions", "left", "kind", code="wrong-kind", message="m")]

    with kit.own_parts(checks={"models.physics": check}):
        opened = kit.opened(slab)
        found = {i.code: i for i in checking.run(opened, kit.ctx(), definitions.defined(opened, kit.ctx(),
                                                                                       compute=False))}
    lines = physics.read_text().splitlines()
    left = next(n for n, line in enumerate(lines, 1) if line.strip() == "[conditions.left]")
    kind = next(n for n, line in enumerate(lines[left:], left + 1) if line.strip().startswith("kind"))
    assert found["wrong-kind"].line == kind
    assert found["unloadable"].line == len(mesh.read_text().splitlines()) and found["unloadable"].key == "szie"
    assert found["stray"].line is None


def test_a_part_that_is_not_toml_is_a_finding_at_the_line_toml_stops_reading_it(slab):
    """Fails if the finding on a part whose file is not TOML carries no line, though tomllib says
    where it stopped reading it: the person opens the file at that line as at any finding's
    (core.md § 10: `line`; § 2: "Why a text is not TOML is said in plain words at its line")."""
    mesh = slab / "mesh/uniform.toml"
    lines = mesh.read_text().splitlines()
    lines.insert(3, 'note = "not closed')
    mesh.write_text("\n".join(lines) + "\n")
    (found,) = [i for i in kit.opened(slab).issues if i.code == "unloadable" and i.subject == "mesh:uniform"]
    assert (found.file, found.line) == ("mesh/uniform.toml", 4)


def test_a_refusal_becomes_a_finding_one_way_placed_where_the_person_opens_its_part(slab):
    """Fails if a refusal made a finding in a project loses its code, its subject or its next
    steps, or — about a part or a value in it — is not placed where the person opens it: the part's
    file, the key and the line it stands at, read by the door; or one about no part is given a
    file; or one naming no subject becomes a finding at all (core.md § 10: `Issue.of`, "the one way,
    never by hand"; § 9: every refusal names its subject; projects.md § 6)."""
    from femkit.core import view
    from femkit.core.errors import Refused, Unstated
    from femkit.projects.requests import PROJECT_CHECK
    opened = kit.opened(slab)
    about = Unstated("no engine takes the mesh", (view.command(PROJECT_CHECK, project="slab"),),
                     code="no-input", subject="study:benchmark:mesh")
    found = door.finding_of(opened, about, "warning", "its stages wait")
    lines = (slab / "studies/benchmark.toml").read_text().splitlines()
    assert (found.severity, found.code, found.subject, found.message, found.next) == (
        "warning", "no-input", "study:benchmark:mesh", "its stages wait", about.next)
    assert (found.file, found.key, found.line) == (
        "studies/benchmark.toml", "mesh", lines.index('mesh = "uniform"') + 1)
    elsewhere = door.finding_of(opened, Refused("the record is stale", code="stale", subject="local"), "warning")
    assert (elsewhere.subject, elsewhere.file, elsewhere.key, elsewhere.line) == ("local", None, None, None)
    with pytest.raises(TypeError):
        door.finding_of(opened, Refused("about nothing", code="stale"), "warning")


@pytest.mark.parametrize("changes, head", [
    ([], "slab: every part loads and checks; 1 note"),
    ([("notes.txt", "")], "slab: no errors; 1 warning, 1 note"),
    ([("notes.txt", ""), ("mesh/uniform.toml", "size = \n")],
     "slab: 1 error, 1 warning, 2 notes; the first is the next step"),
], ids=["notes alone", "a warning", "an error and a warning"])
def test_the_first_line_of_project_check_says_what_findings_stand_and_no_more(slab, changes, head):
    """Fails if `project check`'s first line claims every part loads and checks while a warning
    stands, calls the first finding the next step while no error stands — a warning or a note is
    never the next step — or counts its findings otherwise than as errors, warnings and notes
    (models.md § 11.2: "the first is the project's next step"; projects.md § 8; web.md § 8.4: "its
    first error in the chain's order, else the parts' next steps")."""
    for file, text in changes:
        (slab / file).write_text(text)
    assert kit.run("project.check", project="slab").report.blocks[0].text == head


def test_the_next_steps_follow_the_findings_in_the_text_a_person_reads(slab):
    """Fails if `project check`'s text writes the parts' next steps — a study's prep, offered while
    only notes stand — before its findings, rather than after them (models.md § 11.2: "with none,
    the parts' next steps follow the findings"; api.md § 4.4)."""
    lines = kit.run("project.check", project="slab").text().splitlines()
    first_next = next(i for i, line in enumerate(lines) if line.startswith("next --"))
    findings = [i for i, line in enumerate(lines) if line.startswith("  - ")]
    assert findings and max(findings) < first_next


def test_the_registry_registers_each_part_schema_and_check_its_packages_declare_once():
    """Fails if a schema or a check a module of PARTS registers (`REGISTERS`: its `schemas`, its
    `checks`) is not registered with the door or the check frame under its key at femkit's start —
    a project's parts would then load unchecked, and every template pass — or a second start
    registers a check again (api.md § 6; models.md § 11.1)."""
    registry.operations()
    registry.operations()                                           # every start registers each once
    declared: dict[str, list] = {}
    for name, registers in registry.registrations():
        assert all(schemas.registered()[key] is model for key, model in registers.schemas.items()), name
        for key, check in registers.checks.items():
            declared.setdefault(key, []).append(check)
    assert {key: list(checking.registered()[key]) for key in declared} == declared


def test_a_module_of_parts_declares_only_what_it_registers(monkeypatch):
    """Fails if a module of PARTS must declare what it does not have — an empty table of checks or
    of keys — for its schema to be registered with the door and its check with the check
    frame at femkit's start: what a module registers is one shape it fills only with what it has
    (api.md § 6)."""
    module = types.ModuleType("own_parts")

    def check(c, part):
        return iter(())

    module.REGISTERS = checking.Registration(schemas={"tests.own": kit.StandIn}, checks={"tests.own": check})
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(registry, "PARTS", (*registry.PARTS, module.__name__))
    try:
        registry.part_checks()
        assert schemas.registered()["tests.own"] is kit.StandIn and checking.registered()["tests.own"] == (check,)
    finally:
        schemas.unregister("tests.own")
        checking.unregister("tests.own")