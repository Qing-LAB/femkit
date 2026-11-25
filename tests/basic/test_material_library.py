"""The global material library (materials.md § 4; projects.md §§ 1, 7): seeded with femkit's
shipped materials by the first `project new` on a root without one, under its lock and with its
record; `GLOBAL/` naming the library's material and any other name the project's own first; each
library material a project names loaded and checked through the door, its findings naming its file
by its full path; a changed shipped material offered, never applied; and where each case's
material is found now shown by `case list`. On copies of the templates, under projects roots of the
tests' own. That a name in neither place is a finding is tests/basic/test_geometry_materials.py's."""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from pathlib import Path

from tests import kit
from tests.kit import laplace, slab  # noqa: F401 -- fixtures
from femkit.core.errors import Busy, PlanStale, Refused
from femkit.definitions import catalogue
from femkit.projects.project import Library

COMPONENT = "components/square/component.toml"     # the Laplace template's component
LIBRARY = "materials"                              # the global library's folder at the root (materials.md § 4)
VACUUM = f"{LIBRARY}/vacuum/material.toml"         # femkit's shipped vacuum, as the root's library holds it


def shipped_names() -> list[str]:
    """The materials femkit ships, by their names: their folders' paths in `femkit/data/materials/`."""
    folder = catalogue.data_root() / LIBRARY
    return sorted(p.parent.relative_to(folder).as_posix() for p in folder.rglob("material.toml"))


def expanded(project: Path) -> list[dict]:
    """The Laplace study expanded, and every case it makes now, as its file holds it."""
    outcome = kit.apply("study.expand", project=project.name, study="check")
    return [json.loads((project / "cases" / "check" / i / "case.json").read_text()) for i in outcome.added + outcome.kept]


def permittivity(project: Path) -> set[str]:
    """The exact relative permittivity each case of the Laplace study holds for its one body."""
    return {d["component"]["assign"]["domain"]["properties"]["relative_permittivity"]["data"]["value"]["value"]
            for d in expanded(project)}


# ------------------------------------------------------------------ the seed

def test_project_new_on_a_root_without_a_library_seeds_it_with_femkits_shipped_materials_and_their_record(tmp_path):
    """Fails if `project new` on a projects root without `materials/` — the root not made yet, or
    made before — does not make the library as a step of its plan, holding a copy of every
    material femkit ships and a record naming each with the digest of femkit's files; or if it
    seeds a root whose `materials/` is there, or changes anything in it (materials.md § 4: "When
    `project new` finds the root without `materials/`, it makes it and copies the shipped
    materials into it, and records … each copied material's name and the digest"; "They are the
    person's from then on"; projects.md § 7)."""
    shipped = catalogue.data_root() / LIBRARY
    root = tmp_path / "projects"
    kit.set_root(root)
    op, plan, c = kit.planned("project.new", name="first", source="laplace_square")
    assert len(plan.steps) == 3 and not root.exists()                     # the root, the library, the copy
    op.apply(plan, c)
    library = root / LIBRARY
    assert {f: b for f, b in kit.tree(library).items() if not f.startswith(".femkit/")} == kit.tree(shipped)
    record = json.loads((library / ".femkit" / "shipped.json").read_text())
    assert sorted(record["copied"]) == shipped_names() and "vacuum" in record["copied"]
    assert all(re.fullmatch("[0-9a-f]{64}", d) for d in record["copied"].values())
    kit.rewrite(library / "vacuum" / "material.toml", 'display = "Vacuum"', 'display = "My vacuum"')
    (library / "mine").mkdir()
    (library / "mine" / "material.toml").write_text((library / "vacuum" / "material.toml").read_text())
    theirs = kit.tree(library)
    assert [s.id for s in kit.planned("project.new", name="second", source="laplace_square")[1].steps] == ["copy"]
    kit.apply("project.new", name="second", source="laplace_square")
    assert kit.tree(library) == theirs                                    # the person's, from then on
    older = tmp_path / "older"
    (older / "kept").mkdir(parents=True)
    kit.set_root(older)
    assert len(kit.planned("project.new", name="first", source="laplace_square")[1].steps) == 2
    kit.apply("project.new", name="first", source="laplace_square")
    assert sorted(json.loads((older / LIBRARY / ".femkit" / "shipped.json").read_text())["copied"]) == shipped_names()


def test_the_seed_holds_the_librarys_lock_and_never_lands_over_what_came_meanwhile(tmp_path):
    """Fails if the seeding is applied while another process holds the global library's lock, or
    over a `materials/` made between its plan and its apply — the person's files there changed or
    lost (materials.md § 4: "A write to the global library — the seeding above … — holds the
    library's lock and is shown as its plan before it is applied"; api.md § 3)."""
    root = tmp_path / "projects"
    kit.set_root(root)
    subject = Library(root, LIBRARY).subject
    op, plan, c = kit.planned("project.new", name="first", source="laplace_square")
    assert subject in plan.subjects
    holder = kit.hold(subject, "alone")
    try:
        with kit.refused(Busy, "held", subject):
            op.apply(plan, c)
    finally:
        holder.stdin.close()
        holder.wait()
    assert not root.exists()
    (root / LIBRARY / "gold").mkdir(parents=True)
    (root / LIBRARY / "gold" / "material.toml").write_text("schema = 1\n")
    with kit.refused(PlanStale, "basis-changed"):
        op.apply(plan, c)
    assert kit.tree(root) == {f"{LIBRARY}/gold/material.toml": b"schema = 1\n"}


# ------------------------------------------------------------------ finding a material

def test_global_names_the_librarys_material_and_any_other_name_the_projects_own_first(laplace):
    """Fails if `GLOBAL/vacuum` does not take the global library's material where the project holds
    one of that name too, or `vacuum` does not take the project's own while it holds one and the
    library's once it does not — each as the case written from it holds its data (materials.md
    § 4: "`GLOBAL/metals/gold` names the global library's, explicitly"; "any other name … is the
    project's own first, then the global library's"; § 6)."""
    root = laplace.parent
    kit.rewrite(root / VACUUM, 'value = "1"', 'value = "2"')             # the library's differs from the project's
    assert permittivity(laplace) == {"1"}
    kit.rewrite(laplace / COMPONENT, 'material = "vacuum"', 'material = "GLOBAL/vacuum"')
    assert permittivity(laplace) == {"2"}
    kit.rewrite(laplace / COMPONENT, 'material = "GLOBAL/vacuum"', 'material = "vacuum"')
    shutil.rmtree(laplace / "materials" / "vacuum")
    assert permittivity(laplace) == {"2"}


def test_a_library_material_a_project_names_is_checked_and_its_findings_name_its_full_path(laplace):
    """Fails if a global library material the project names is not checked by the material check,
    its findings naming its file by its full path, or a study resting on it expands while it has
    one or does not load; or if a library material the project does not name is read (materials.md
    § 4: "A library material is loaded and checked when a project names it; its findings name its
    file by its full path"; models.md § 5.3)."""
    root = laplace.parent
    (root / LIBRARY / "broken").mkdir()
    (root / LIBRARY / "broken" / "material.toml").write_text("schema = \n")    # named by no project
    kit.rewrite(laplace / COMPONENT, 'material = "vacuum"', 'material = "GLOBAL/vacuum"')
    kit.rewrite(root / VACUUM, 'range = "all"\n', "")
    checked = kit.run("project.check", project="laplace_square")
    at = "properties.relative_permittivity.definition.range"
    assert [(i.code, i.subject, i.file, i.key) for i in checked.issues if i.severity != "info"] == [
        ("not-stated", f"material:GLOBAL/vacuum:{at}", str(root / VACUUM), at)]
    assert {p.part: (p.file, p.state) for p in checked.parts}["material:GLOBAL/vacuum"] == (str(root / VACUUM),
                                                                                              "findings")
    with kit.refused(Refused, "has-findings", "material:GLOBAL/vacuum"):
        kit.apply("study.expand", project="laplace_square", study="check")
    (root / VACUUM).write_text("schema = \n")
    assert [(i.code, i.subject, i.file) for i in kit.run("project.check", project="laplace_square").issues
            if i.severity != "info"] == [("unloadable", "material:GLOBAL/vacuum", str(root / VACUUM))]
    with kit.refused(Refused, "unloadable", "material:GLOBAL/vacuum"):
        kit.apply("study.expand", project="laplace_square", study="check")
    assert not (laplace / "cases").exists()


def test_each_material_femkit_ships_passes_its_check_where_a_project_names_it(laplace):
    """Fails if a material femkit ships, as `project new` copies it into the library, has a finding
    of `project check` when a project names it (materials.md § 4: "A shipped material is checked
    by the basic tests as well")."""
    found = {}
    for name in shipped_names():
        kit.rewrite(laplace / COMPONENT, 'material = "vacuum"', f'material = "GLOBAL/{name}"')
        issues = kit.run("project.check", project="laplace_square").issues
        found[name] = [(i.code, i.key) for i in issues if i.subject.startswith(f"material:GLOBAL/{name}")]
        kit.rewrite(laplace / COMPONENT, f'material = "GLOBAL/{name}"', 'material = "vacuum"')
    assert found and found == {name: [] for name in shipped_names()}


def test_a_moved_project_finds_its_global_materials_in_its_new_roots_library(tmp_path, slab):
    """Fails if a project carried to another projects root finds its `GLOBAL/` materials other
    than in that root's library, or one missing there is other than a finding naming it
    (materials.md § 4: "A moved project … finds its `GLOBAL/` materials in that root's library; one
    missing there is a finding naming it"; projects.md § 1)."""
    root = slab.parent
    (root / LIBRARY / "mine").mkdir()
    (root / LIBRARY / "mine" / "material.toml").write_text((root / VACUUM).read_text())
    component = slab / "components" / "slab" / "component.toml"
    kit.rewrite(component, 'material = "dielectric_1"', 'material = "GLOBAL/vacuum"')
    kit.rewrite(component, 'material = "dielectric_2"', 'material = "GLOBAL/mine"')
    assert [i for i in kit.run("project.check", project="slab").issues if i.severity == "error"] == []
    elsewhere = kit.copy_template(tmp_path / "elsewhere", "laplace_square")
    shutil.copytree(slab, elsewhere.parent / "slab")
    issues = kit.run("project.check", project="slab").issues
    assert [(i.code, i.key, i.label) for i in issues if i.severity == "error"] == [
        ("no-such-material", "assign.high.material", "GLOBAL/mine")]
    assert {p.part: p.file for p in kit.run("project.check", project="slab").parts}["material:GLOBAL/vacuum"] == \
        str(elsewhere.parent / VACUUM)


def test_a_copy_of_a_project_takes_none_of_the_library_materials_it_names(tmp_path):
    """Fails if `project new` from one of the person's projects copies a global library material
    the project names into the new project: the library is not the project's, and a copy takes
    what the project's own tree holds (projects.md § 7: "What it copies"; § 1)."""
    source = kit.copy_template(tmp_path / "projects", "laplace_square", "source")
    shutil.rmtree(source / "materials" / "vacuum")                           # `vacuum` is the library's now
    outcome = kit.apply("project.new", name="copy", source="source")
    assert outcome.ok() and kit.tree(source.parent / "copy") == kit.tree(source)


# ------------------------------------------------------------------ the offer

def test_a_changed_shipped_material_is_offered_while_the_copy_differs_and_never_applied(definitions, tmp_path):
    """Fails if, once femkit's shipped material no longer has the digest its copy recorded, and
    the person's copy differs from femkit's file as it is now, `project check` does not give an
    `info` finding `shipped-changed` on the library material the project uses, at its file; if it
    gives one while femkit's file is unchanged — the person's own edit is no offer — on a material
    the project does not use, or once the person's copy matches femkit's file; or if anything is
    written to the person's copy (materials.md § 4: "A changed shipped material is offered, never
    applied"; "Once the copy matches femkit's file, nothing is said")."""
    project = kit.copy_template(tmp_path / "projects", "laplace_square")
    root, theirs = project.parent, definitions / VACUUM
    kit.rewrite(project / COMPONENT, 'material = "vacuum"', 'material = "GLOBAL/vacuum"')

    def offers():
        return [(i.severity, i.code, i.subject, i.file, i.key, i.right, i.choices)
                for i in kit.run("project.check", project="laplace_square").issues if i.code == "shipped-changed"]

    kit.rewrite(root / VACUUM, 'display = "Vacuum"', 'display = "My vacuum"')       # the person's own edit
    assert offers() == []
    mine = kit.tree(root / LIBRARY)
    kit.rewrite(theirs, 'display = "Vacuum"', 'display = "The vacuum"')
    assert offers() == [("info", "shipped-changed", "material:GLOBAL/vacuum", str(root / VACUUM), None, None, ())]
    assert kit.tree(root / LIBRARY) == mine
    kit.rewrite(project / COMPONENT, 'material = "GLOBAL/vacuum"', 'material = "vacuum"')   # the project's own
    assert offers() == []
    kit.rewrite(project / COMPONENT, 'material = "vacuum"', 'material = "GLOBAL/vacuum"')
    shutil.copy(theirs, root / VACUUM)                                         # the person takes femkit's
    assert offers() == []


# ------------------------------------------------------------------ where each case's material came from

def test_case_list_shows_each_bodys_material_where_it_is_found_now_its_dataset_and_its_source(laplace):
    """Fails if `case list` does not show, for each case's assignment, the material, where its name
    finds it now — the project's own, or `GLOBAL` — and the dataset and source the case holds, in
    a table whose columns are headed; if an edited library material does not make new cases when
    the study is expanded again, the old ones kept and shown as no longer made; or if copying the
    library material into the project changes a case, rather than where it is found (materials.md
    § 4: "Where each material came from is always shown"; § 6: "copying a library material into
    the project … changes no case"; "A dataset edited after the case was written is new
    content")."""
    library = laplace.parent / LIBRARY
    shutil.rmtree(laplace / "materials" / "vacuum")                         # `vacuum` is the library's now
    first = sorted(kit.apply("study.expand", project="laplace_square", study="check").added)
    source = tomllib.loads((library / "vacuum" / "material.toml").read_text())[
        "properties"]["relative_permittivity"]["definition"]["source"]

    def listed():
        result = kit.run("case.list", project="laplace_square")
        (study,) = result.studies
        return result, {c.id: (c.made, {(m.group, m.material, m.found, m.property, m.dataset, m.source)
                                        for m in c.materials}) for c in study.written}

    result, cases = listed()
    assert cases == {i: (True, {("domain", "vacuum", "GLOBAL/vacuum", "relative_permittivity", "definition", source)})
                     for i in first}
    tables = [b for b in result.model_dump(mode="json")["report"]["blocks"] if b["kind"] == "table"]
    assert any({"material", "found", "dataset", "source"} <= {c["key"] for c in t["columns"]}
               and all(c["label"] for c in t["columns"]) and len(t["rows"]) == len(first) for t in tables)
    kit.rewrite(library / "vacuum" / "material.toml", 'value = "1"', 'value = "2"')
    assert {i: made for i, (made, _) in listed()[1].items()} == {i: False for i in first}
    again = kit.apply("study.expand", project="laplace_square", study="check")
    assert len(again.added) == len(first) and again.kept == [] and set(again.added).isdisjoint(first)
    assert {i: made for i, (made, _) in listed()[1].items()} == {**{i: False for i in first},
                                                                  **{i: True for i in again.added}}
    shutil.copytree(library / "vacuum", laplace / "materials" / "vacuum")
    kept = kit.apply("study.expand", project="laplace_square", study="check")
    assert kept.added == [] and sorted(kept.kept) == sorted(again.added)
    assert {found for _, rows in listed()[1].values() for _, _, found, *_ in rows} == {"vacuum"}


def test_case_list_finds_a_library_material_the_project_no_longer_names(laplace):
    """Fails if `case list` says a case's material is found nowhere while the global library holds
    it, because no part of the project names it any more — the door loads only what the project
    names (materials.md § 4: `case list` shows "where that name finds it now — the project, the
    library, or nowhere")."""
    root = laplace.parent
    shutil.rmtree(laplace / "materials" / "vacuum")
    kit.rewrite(laplace / COMPONENT, 'material = "vacuum"', 'material = "GLOBAL/vacuum"')
    first = sorted(kit.apply("study.expand", project="laplace_square", study="check").added)
    (laplace / "materials" / "other").mkdir()
    shutil.copy(root / VACUUM, laplace / "materials" / "other" / "material.toml")
    kit.rewrite(laplace / COMPONENT, 'material = "GLOBAL/vacuum"', 'material = "other"')
    (study,) = kit.run("case.list", project="laplace_square").studies
    assert {c.id: (c.made, [(m.material, m.found, m.changed) for m in c.materials]) for c in study.written} == {
        i: (False, [("vacuum", "GLOBAL/vacuum", [])]) for i in first}


def test_one_library_material_written_either_way_is_one_case_held_by_its_name_in_its_library(laplace):
    """Fails if an assignment's `GLOBAL/vacuum` and its `vacuum`, both finding the global library's
    material, make two cases of one study, or a case holds the material otherwise than by its name
    in its library (materials.md § 6: "each material by its name in its library, never `GLOBAL/`,
    so one material written either way is one case")."""
    shutil.rmtree(laplace / "materials" / "vacuum")                         # `vacuum` is the library's now
    first = sorted(kit.apply("study.expand", project="laplace_square", study="check").added)
    kit.rewrite(laplace / COMPONENT, 'material = "vacuum"', 'material = "GLOBAL/vacuum"')
    again = kit.apply("study.expand", project="laplace_square", study="check")
    assert again.added == [] and sorted(again.kept) == first
    assert {d["component"]["assign"]["domain"]["material"] for d in expanded(laplace)} == {"vacuum"}


def test_case_list_flags_each_case_whose_materials_data_changed_and_expand_says_it_writes_anew(laplace):
    """Fails if, for each case its study no longer makes, `case list` does not compare its
    materials' data with what they hold now — giving the body, the material, the dataset and what
    differs, the value as the case holds it and as the material holds it now, in its result and in
    its text — or flags a case whose materials hold what it holds; or if the plan of `study
    expand` does not say, for each case it writes because its materials' data changed, the case
    it takes the place of, or says so of one written for another reason (materials.md § 6: "`case
    list` flags each case whose data differs from what its materials now hold, naming the body,
    the material and dataset, and what differs"; "the plan of `study expand` says which cases it
    writes because their materials' data changed")."""
    first = sorted(kit.apply("study.expand", project="laplace_square", study="check").added)
    kit.rewrite(laplace / "materials" / "vacuum" / "material.toml", 'value = "1"', 'value = "1.0006"')

    def listed():
        result = kit.run("case.list", project="laplace_square")
        (study,) = result.studies
        rows = [r for b in result.model_dump(mode="json")["report"]["blocks"]
                if b["kind"] == "table" and "changed" in {c["key"] for c in b["columns"]} for r in b["rows"]]
        return ({c.id: (c.made, [(m.group, m.material, m.dataset, [(d.key, d.case, d.now) for d in m.changed])
                                 for m in c.materials]) for c in study.written},
                {r["case"]: bool(r["changed"]) for r in rows})

    cases, shown = listed()
    assert cases == {i: (False, [("domain", "vacuum", "definition", [("value", "1", "1.0006")])]) for i in first}
    assert shown == {i[:12]: True for i in first}
    op, plan, c = kit.planned("study.expand", project="laplace_square", study="check")
    assert sorted(plan.holds["renewed"].values()) == first and sorted(plan.holds["renewed"]) == sorted(
        s.id for s in plan.steps)
    second = op.apply(plan, c).added
    kit.rewrite(laplace / "mesh" / "uniform.toml", "tolerance = 1e-9", "tolerance = 1e-8")    # not the data
    cases, shown = listed()
    assert {i: changed for i, (_, [(*_, changed)]) in cases.items()} == {
        **{i: [("value", "1", "1.0006")] for i in first}, **{i: [] for i in second}}
    assert shown == {**{i[:12]: True for i in first}, **{i[:12]: False for i in second}}
    assert kit.planned("study.expand", project="laplace_square", study="check")[1].holds["renewed"] == {}


def test_project_check_shows_a_library_materials_file_from_home_as_femkit_shows_a_path(laplace, monkeypatch):
    """Fails if `project check`'s table of parts shows a global library material's file otherwise
    than from `~` where it lies under the home folder — as femkit shows a path to a person, so the
    table stays readable — or its result names the file otherwise than by its full path
    (materials.md § 4: "its findings name its file by its full path"; api.md § 4.4: a path shown
    as a person reads it)."""
    root = laplace.parent
    monkeypatch.setenv("HOME", str(root.parent))
    kit.rewrite(laplace / COMPONENT, 'material = "vacuum"', 'material = "GLOBAL/vacuum"')
    result = kit.run("project.check", project="laplace_square")
    assert {p.part: p.file for p in result.parts}["material:GLOBAL/vacuum"] == str(root / VACUUM)
    (table,) = [b for b in result.model_dump(mode="json")["report"]["blocks"] if b["kind"] == "table"]
    rows = {r["part"]: r["file"] for r in table["rows"]}
    assert (rows["material:GLOBAL/vacuum"], rows["component:square"]) == (f"~/{root.name}/{VACUUM}", COMPONENT)


def test_a_library_materials_finding_and_a_name_found_nowhere_write_the_library_from_home(laplace, monkeypatch):
    """Fails if the text a person reads of `project check` writes the global library's place
    otherwise than from `~` where it lies under the home folder — the file under a library
    material's finding, the library a name found nowhere was looked for in — or the finding names
    its file otherwise than by its full path (api.md § 4.4: "Paths under the home directory are
    written from `~`"; materials.md § 4: "its findings name its file by its full path")."""
    root = laplace.parent
    monkeypatch.setenv("HOME", str(root.parent))
    kit.rewrite(laplace / COMPONENT, 'material = "vacuum"', 'material = "GLOBAL/vacuum"')
    kit.rewrite(root / VACUUM, 'range = "all"\n', "")
    result = kit.run("project.check", project="laplace_square")
    assert [i.file for i in result.issues if i.code == "not-stated"] == [str(root / VACUUM)]
    shown = result.text()
    assert f"~/{root.name}/{VACUUM}: properties.relative_permittivity.definition.range" in shown
    assert str(root) not in shown
    kit.rewrite(laplace / COMPONENT, 'material = "GLOBAL/vacuum"', 'material = "GLOBAL/vacum"')
    (nowhere,) = [i for i in kit.run("project.check", project="laplace_square").issues if i.code == "no-such-material"]
    assert f"~/{root.name}/{LIBRARY}" in nowhere.message and str(root) not in nowhere.message


def test_the_graph_wires_an_assignment_to_the_library_material_its_name_finds(laplace):
    """Fails if an assignment whose name finds a global library material — `GLOBAL/vacuum`, or
    `vacuum` once the project holds none — is not wired to that material's node, which says it is
    the library's — its address `material:GLOBAL/<name>`, its group `GLOBAL` — and holds its
    file's text; or if `GLOBAL/vacuum` is wired to the project's own of the same name
    (materials.md § 4; models.md § 11.2: "Wires are the references between parts")."""
    root = laplace.parent

    def wired() -> set[str]:
        result = kit.run("project.graph", project="laplace_square")
        library = {n.address: n for n in result.nodes}["material:GLOBAL/vacuum"]
        assert (library.kind, library.group, library.text) == ("material", "GLOBAL", (root / VACUUM).read_text())
        return {e.target for e in result.edges if e.source == "component:square:assign.domain"}

    kit.rewrite(laplace / COMPONENT, 'material = "vacuum"', 'material = "GLOBAL/vacuum"')
    assert wired() == {"material:GLOBAL/vacuum"}
    kit.rewrite(laplace / COMPONENT, 'material = "GLOBAL/vacuum"', 'material = "vacuum"')
    shutil.rmtree(laplace / "materials" / "vacuum")
    assert wired() == {"material:GLOBAL/vacuum"}
