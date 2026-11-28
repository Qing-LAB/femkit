"""femkit's templates (projects.md § 7; ADR 0015): each project template a whole, working project
that `project check` passes, as a copy `project new` makes of it does; every template file — each
part of each project template, and the settings file's — carrying above each key its help as its
schema, or the declaration beside it, states it, ending with the chapter of the manual its kind
declares, and no comment citing a contract or the plan; and every chapter a help names one the
manual has (core.md § 2; docs/README.md § 3.1, M5)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests import kit
from femkit.config import settings
from femkit.config.settings import UserConfig
from femkit.core.schema import Declared, DefinitionError, declared_by, help_findings, help_text, load_text
from femkit.definitions import catalogue
from femkit.materials import material
from femkit.projects import checking, door, layout, schemas

REPO = Path(__file__).resolve().parents[2]

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


def declared(opened: door.Opened, part: door.Part) -> Declared:
    """The help of each key of ``part``'s text a declaration beside its schema states — a
    physics' formulation, kinds and parameters; a study's step kinds; a material's properties and
    its models' parameters — as the declarations registered for its schema state them, ending, where
    it ends with one, with its kind's chapter of the manual (core.md § 2; web.md § 8.3)."""
    return declared_by(checking.stated(checking.Checking.of(opened, kit.ctx(), checking.Defined()), part))


def helps_of(text: str) -> Declared:
    """The help of each key of a material's text the property list and the dispersion list state
    (`material.keys`): a material femkit ships, which no project holds."""
    ctx = kit.ctx()
    return declared_by(material.keys(catalogue.properties(ctx), catalogue.dispersion(ctx), text))


def test_the_comment_above_each_key_of_every_template_is_its_help():
    """Fails if, in any template file — every part of every project template, of every part kind,
    the settings file's template, and every material femkit ships — the comment above a key is
    not that key's help as its schema states it, or, for a key a formulation, the property list or
    the dispersion list declares, as it states it; or a key its schema names is neither set nor
    shown commented out; or a part kind escapes the comparison (projects.md § 7: "the comment above each key is that
    key's help as its schema states it, held so by a test"; materials.md § 4: femkit's shipped
    materials "each written as a template is, the comment above each key its help"; core.md § 2;
    config.md § 3.2)."""
    findings = {"config.toml": [str(f) for f in help_findings(settings.template_text(), UserConfig,
                                                              manual=settings.MANUAL)]}
    compared: set[str] = set()
    for name, folder in catalogue.templates(kit.ctx()).items():
        opened = kit.opened(folder)
        for part in opened.parts.values():
            kind = opened.layout.kinds[part.address.kind]
            model, text = schemas.registered()[kind.schema_], opened.texts[part.file]
            helps = declared(opened, part)
            findings[f"{name}/{part.file}"] = [str(f) for f in help_findings(text, model, helps, kind.manual)]
            compared.add(kind.schema_)
    materials = opened.layout.kinds[opened.layout.kind_of(material.KEY)]
    shipped = door.shipped(opened.layout, opened.layout.kind_of(material.KEY))
    for name, held in shipped.items():
        text = held.file.read_text(encoding="utf-8")
        findings[str(held.file)] = [str(f) for f in help_findings(text, material.Material, helps_of(text),
                                                                   materials.manual)]
    assert shipped and {file: found for file, found in findings.items() if found} == {}
    assert compared == {k.schema_ for k in opened.layout.kinds.values()}
    vacuum = catalogue.templates(kit.ctx())["laplace_square"] / "materials/vacuum/material.toml"
    text = vacuum.read_text().replace("# the material's relative permittivity, in 1\n", "# its permittivity\n")
    assert [(f.key, f.problem) for f in help_findings(text, material.Material, helps_of(text), materials.manual)] \
        == [("properties.relative_permittivity",
             "its comment reads 'its permittivity'; its help is \"the material's relative permittivity, in 1\"")]


def test_each_template_holds_one_study_naming_no_engine_and_its_observables_part_reads_it():
    """Fails if a template holds more than one study, or a study naming an engine — one per engine,
    written twice — or its observables part reads other than that study: a study is the problem's
    design, the engine chosen when it is solved (ADR 0025 decision 1; projects.md § 7; models.md
    § 5.1)."""
    for folder in catalogue.templates(kit.ctx()).values():
        opened = kit.opened(folder)
        studies = [p for p in opened.parts.values() if p.address.kind == "study"]
        (study,) = studies
        assert "engine" not in type(study.data).model_fields
        readers = [p.data.studies for p in opened.parts.values() if p.address.kind == "observables"]
        assert readers == [[study.address.name]]


#: A contract or the plan, as a text a person reads would cite it: `models.md § 2`, `plan § 4`.
CITED = re.compile(r"\b(?:" + "|".join(re.escape(p.stem) for p in (REPO / "docs" / "contracts").glob("*.md"))
                   + r"|plan)(?:\.md)? §")


def test_no_template_comment_cites_a_contract_or_the_plan():
    """Fails if a comment of any template — the settings file's, each file of each project
    template, each material femkit ships — cites a contract or the plan, where it points to the
    manual (docs/README.md § 3.1, M5: "never a contract or the plan"; core.md § 2)."""
    files = [p for folder in (catalogue.templates_dir(), catalogue.data_root() / "materials")   # config.toml among them
             for p in folder.rglob("*") if p.is_file()]
    cited = [f"{p.relative_to(catalogue.data_root())}:{n}: {line}" for p in files
             for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if line.lstrip().startswith("#") and CITED.search(line)]
    assert len(files) > 10 and cited == []


def test_every_chapter_a_help_names_is_one_the_manual_has():
    """Fails if a chapter of the manual a help ends with — each part kind's the person writes,
    the settings file's, each command group's — is not declared, names no file of `docs/manual/`,
    or is shown by any title but that file's first heading; or a layout naming as a chapter what
    no chapter could be — a path, a file that is no Markdown — loads (core.md § 2: "a test holds
    every such chapter to one the manual has"; projects.md § 4; api.md § 6)."""
    from femkit import registry
    shipped = layout.read()
    declared = {f"kinds.{k}": v.manual for k, v in shipped.kinds.items() if v.writer == "person"}
    declared |= {"settings": settings.MANUAL} | {f"group {g!r}": v.manual for g, v in registry.GROUPS.items()}
    manual = REPO / "docs" / "manual"
    titles = {file: (manual / file).read_text(encoding="utf-8").splitlines()[0].removeprefix("# ")
              for file in set(declared.values()) if file is not None and (manual / file).is_file()}
    assert {at: titles.get(file) for at, file in declared.items() if titles.get(file) is None} == {}
    assert {file: help_text("a help", manual=file) for file in titles} == {
        file: f"a help (manual: {title})" for file, title in titles.items()}
    for wrong in ("../contracts/core.md", "README", "sub/6-materials.md"):
        text = layout.file().read_text(encoding="utf-8").replace('manual = "6-materials.md"', f'manual = "{wrong}"')
        with pytest.raises(DefinitionError) as refused:
            load_text(text, layout.Layout, layout.file())
        assert [p.path for p in refused.value.problems] == ["kinds.material.manual"]
