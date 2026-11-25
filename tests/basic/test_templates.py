"""femkit's templates (projects.md § 7; ADR 0015): each project template a whole, working project
that `project check` passes, as a copy `project new` makes of it does; and every template file —
each part of each project template, and the settings file's — carrying above each key its help as
its schema, or the declaration beside it, states it (core.md § 2)."""

from __future__ import annotations

import pytest

from tests import kit
from femkit.config import settings
from femkit.config.settings import UserConfig
from femkit.core.schema import Declared, help_findings
from femkit.definitions import catalogue
from femkit.materials import material
from femkit.models import physics, study
from femkit.projects import door, schemas

TEMPLATES = ("laplace_square", "two_material")

#: What each template's `project check` cannot check before its geometry exists, by the key it is
#: at: whether the faces its conditions stand on are outer boundaries or interfaces (geometry.md
#: § 7) — said once, on the study that pairs the physics with the component.
NOT_CHECKED_YET = {
    "laplace_square": [("studies/check.toml", "component")],
    "two_material": [("studies/benchmark.toml", "component")],
}


@pytest.mark.parametrize("template", TEMPLATES)
def test_each_template_and_its_copy_pass_project_check(tmp_path, template):
    """Fails if a template, or the copy `project new` makes of it, has a finding of `project
    check` — an error, a warning, or a note other than what needs its geometry built — or the two
    are checked otherwise (projects.md § 7: "Each passes `project check` in a test")."""
    templates = catalogue.templates(kit.ctx())[template].parent
    kit.set_root(templates)                                                     # the templates, as they ship
    shipped = kit.run("project.check", project=template)
    kit.copy_template(tmp_path / "projects", template)
    copied = kit.run("project.check", project=template)
    assert shipped.ok() and copied.ok() and copied.issues == shipped.issues and copied.parts == shipped.parts
    assert [(i.severity, i.code, i.file, i.key) for i in shipped.issues] == [
        ("info", door.UNCHECKED, file, key) for file, key in NOT_CHECKED_YET[template]]


def declared(model: type, text: str) -> Declared:
    """The help of each key of ``text`` a declaration beside ``model``'s schema states: a
    physics' formulation, kinds and parameters; a study's step kinds; a material's properties."""
    ctx = kit.ctx()
    if model is physics.Physics:
        return physics.declared(catalogue.formulations(ctx), text)
    if model is study.Study:
        return study.declared(catalogue.formulations(ctx))
    if model is material.Material:
        return material.declared(catalogue.properties(ctx))
    return lambda path: None


def test_the_comment_above_each_key_of_every_template_is_its_help():
    """Fails if, in any template file — every part of every project template, of every part kind,
    and the settings file's template — the comment above a key is not that key's help as its
    schema states it, or, for a key a formulation or the property list declares, as it states it;
    or a key its schema names is neither set nor shown commented out; or a part kind escapes the
    comparison (projects.md § 7: "the comment above each key is that key's help as its schema
    states it, held so by a test"; core.md § 2; config.md § 3.2)."""
    findings = {"config.toml": [str(f) for f in help_findings(settings.template_text(), UserConfig)]}
    compared: set[str] = set()
    for name, folder in catalogue.templates(kit.ctx()).items():
        opened = kit.opened(folder)
        for part in opened.parts.values():
            key = opened.layout.kinds[part.address.kind].schema_
            model, text = schemas.registered()[key], opened.texts[part.file]
            findings[f"{name}/{part.file}"] = [str(f) for f in help_findings(text, model, declared(model, text))]
            compared.add(key)
    assert {file: found for file, found in findings.items() if found} == {}
    assert compared == {k.schema_ for k in opened.layout.kinds.values()}
    vacuum = catalogue.templates(kit.ctx())["laplace_square"] / "materials/vacuum/material.toml"
    text = vacuum.read_text().replace("# the material's relative permittivity, in 1\n", "# its permittivity\n")
    assert [(f.key, f.problem) for f in help_findings(text, material.Material, declared(material.Material, text))] \
        == [("properties.relative_permittivity",
             "its comment reads 'its permittivity'; its help is \"the material's relative permittivity, in 1\"")]
