"""A new project from a template or from one of the person's projects, and the projects under the
root (projects.md §§ 1, 7; models.md § 11.1) — on the shipped layout and templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import kit
from femkit.core.errors import PlanStale, Refused, UsageError
from femkit.definitions import catalogue


@pytest.fixture
def root(tmp_path) -> Path:
    """A projects root stated, not made yet."""
    folder = tmp_path / "projects"
    kit.set_root(folder)
    return folder


def opened(folder: Path) -> tuple[dict, list]:
    """A project as opened: each part's file and data, and the findings."""
    o = kit.opened(folder)
    return {a: (p.file, p.data) for a, p in o.parts.items()}, o.issues


def test_the_first_project_new_makes_the_root_and_copies_a_template_whole(root):
    """Fails if `project new` from a template does not make the missing projects root as the first
    step of its plan, copies other than every file of the template — each part and the script its
    kind fixes — or the copy opens otherwise than the template does; or if, the root there, it
    makes it again (projects.md § 1: "The first project makes the root"; § 7)."""
    op, plan, c = kit.planned("project.new", name="first", source="laplace_square")
    assert (plan.steps[0].id, plan.steps[-1].id) == ("root", "copy") and not root.exists()
    outcome = op.apply(plan, c)
    template = catalogue.templates(kit.ctx())["laplace_square"]
    assert outcome.ok() and kit.tree(root / "first") == kit.tree(template) and outcome.copied == sorted(kit.tree(template))
    assert opened(root / "first") == opened(template)
    assert opened(root / "first")[1] == []
    assert [s.id for s in kit.planned("project.new", name="groups/second", source="two_material")[1].steps] == ["copy"]


def test_a_copy_of_a_project_takes_what_the_person_writes_and_names_each_file_it_leaves_out(root):
    """Fails if `project new` from one of the person's projects copies what femkit or a run wrote —
    `.femkit/`, `cases/`, `runs/`, `results/` — a stray, or a file an editor keeps beside what it
    edits, or leaves out a part, a grouped part, a file a component declares, or the person's own
    `custom/`; or if its plan and its outcome do not name each file it leaves out, and why — a
    folder femkit or a run writes once, with how many files it holds (projects.md § 7: "What it
    copies"; § 4: the editor's own files)."""
    kit.apply("project.new", name="source", source="two_material")
    source = root / "source"
    kit.rewrite(source / "components/slab/component.toml", "[inputs]\n", '[inputs]\nfiles = { "data/tip.csv" = "x" }\n')
    theirs = {"components/slab/data/tip.csv": "x,y\n", "custom/solver.sif": "! mine\n", "custom/deep/note.txt": "n\n",
              "studies/sweeps/later.toml": "schema = 1\n"}
    written = {".femkit/view.json": "{}", "cases/abc/case.json": "{}", "cases/def/case.json": "{}", "runs/r1/run.log": "",
               "results/a/x.csv": ""}
    strays = {"notes.txt": "a stray\n", "components/slab/old.msh": "a stray\n"}
    editors = {"project.toml~": "", "physics/.electrostatics.toml.swp": "", "#notes.txt#": "", "custom/x~": ""}
    for rel, text in {**theirs, **written, **strays, **editors}.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_text(text)
    op, plan, c = kit.planned("project.new", name="copy", source="source")
    left = [(i.code, i.severity, i.subject, i.file) for i in plan.issues]
    assert left == [("not-copied", "info", f, f) for f in sorted(strays)] + [
        ("not-copied", "info", f"{folder}/", f"{folder}/") for folder in (".femkit", "cases", "results", "runs")]
    assert [i.message for i in plan.issues if i.subject == "cases/"] == ["not copied: femkit writes what this folder "
                                                                          "holds (2 files)"]
    outcome = op.apply(plan, c)
    assert outcome.issues == plan.issues
    left_out = {**written, **strays, **editors}
    assert kit.tree(root / "copy") == {rel: data for rel, data in kit.tree(source).items() if rel not in left_out}
    assert set(outcome.copied) == set(kit.tree(root / "copy"))


def test_a_part_kind_the_layout_says_femkit_writes_is_never_copied(definitions, root):
    """Fails if `project new` copies the parts of a kind the layout declares femkit writes: what a
    copy takes is the writer's to decide, read from the layout (projects.md § 4: "The writer
    decides what a copy takes")."""
    kit.rewrite(definitions / "project" / "layout.toml", 'schema = "models.study"\n',
                'schema = "models.study"\nwriter = "femkit"\n')
    outcome = kit.apply("project.new", name="first", source="laplace_square")
    assert outcome.ok() and "studies/check.toml" not in outcome.copied \
        and "physics/electrostatics.toml" in outcome.copied
    assert not (root / "first/studies").exists()
    assert [(i.code, i.subject, i.message) for i in outcome.issues] == [
        ("not-copied", f"studies/{name}.toml", "not copied: femkit writes this file")
        for name in ("check",)]


def test_a_source_changed_between_plan_and_apply_is_refused_and_nothing_made(root):
    """Fails if the copy goes ahead when a file it takes changed after the plan was shown, so the
    person would get other than what they agreed to (api.md § 3; projects.md § 7)."""
    kit.apply("project.new", name="source", source="laplace_square")
    op, plan, c = kit.planned("project.new", name="copy", source="source")
    (root / "source/project.toml").write_text((root / "source/project.toml").read_text() + "# changed\n")
    with kit.refused(PlanStale, "basis-changed"):
        op.apply(plan, c)
    assert not (root / "copy").exists()


@pytest.mark.parametrize("name, kind, code", [
    ("Bowtie", UsageError, "bad-name"),
    ("groups/.hidden", UsageError, "bad-name"),
    ("materials/mine", UsageError, "in-library"),
    ("held/inner", UsageError, "inside-project"),
    ("held", Refused, "exists"),
    ("groups", Refused, "exists"),
    ("notes/x", Refused, "exists"),
], ids=["capitals", "a dot-folder", "in the global library's folder", "inside a project", "a project there",
        "a group there", "a file along it"])
def test_a_new_projects_name_is_refused_as_the_contract_lists(root, name, kind, code):
    """Fails if `project new` makes a project whose name breaks the name rule, opens with a global
    library's folder, lies inside another project, or would land where a file or folder already is
    — a project or a group alike — instead of refusing as `UsageError` or `Refused`, naming it
    (projects.md § 7: "Which names are refused")."""
    kit.apply("project.new", name="held", source="laplace_square")
    kit.apply("project.new", name="groups/one", source="laplace_square")
    (root / "notes").write_text("")
    with kit.refused(kind, code, name):
        kit.planned("project.new", name=name, source="laplace_square")


def test_without_a_source_the_refusal_offers_each_template_for_the_name_given(root):
    """Fails if `project new` without `--from` makes anything, or its refusal does not offer each
    template as the `project new` of the very name given that copies it (projects.md § 7:
    "without `--from`, the refusal lists the templates")."""
    with kit.refused(UsageError, "no-source", "source") as caught:
        kit.planned("project.new", name="first")
    assert [(a.call.operation, a.call.request, a.fills) for a in caught.value.next] == [
        ("project.new", {"name": "first", "source": t}, []) for t in catalogue.templates(kit.ctx())]
    assert not root.exists()


def test_a_source_that_names_both_a_template_and_a_project_or_neither_is_refused(root):
    """Fails if `project new --from` a name that is both a template and one of the person's
    projects picks one, or one that is neither is looked for elsewhere, instead of refusing,
    naming it, with nothing to do instead (projects.md § 7: "a name that is both is refused, naming
    both"; § 8: "the door's refusals fill their `next`")."""
    kit.apply("project.new", name="laplace_square", source="two_material")
    with kit.refused(UsageError, "ambiguous-source", "laplace_square") as caught:
        kit.planned("project.new", name="first", source="laplace_square")
    assert [a.call.operation for a in caught.value.next][0] == "project.list"
    with kit.refused(UsageError, "no-such-source", "nowhere"):
        kit.planned("project.new", name="first", source="nowhere")
    kit.apply("project.new", name="first", source="two_material")        # a project alone: copied
    assert kit.tree(root / "first") == kit.tree(root / "laplace_square")


def test_a_refusal_writes_a_place_under_home_from_home(root, tmp_path, monkeypatch):
    """Fails if a refusal about a place under the projects root — a project there already, one of
    two a source names, a name with no project, a root that is no folder — writes a path under the
    home folder otherwise than from `~`, as every path a person reads is written (api.md § 4.4:
    "Paths under the home directory are written from `~`"; projects.md §§ 1, 7)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    kit.apply("project.new", name="laplace_square", source="two_material")

    def said(kind, code, subject, call) -> str:
        with kit.refused(kind, code, subject) as caught:
            call()
        return str(caught.value)

    for shown in (said(Refused, "exists", "laplace_square",
                       lambda: kit.planned("project.new", name="laplace_square", source="two_material")),
                  said(UsageError, "ambiguous-source", "laplace_square",
                       lambda: kit.planned("project.new", name="first", source="laplace_square")),
                  said(UsageError, "no-such-project", "nowhere", lambda: kit.run("project.check", project="nowhere"))):
        assert "~/projects" in shown and str(tmp_path) not in shown, shown
    (tmp_path / "a-file").write_text("")
    kit.set_root(tmp_path / "a-file")
    for call in (lambda: kit.run("project.list"), lambda: kit.planned("project.new", name="x", source="two_material")):
        shown = said(Refused, "no-root", str(tmp_path / "a-file"), call)
        assert "~/a-file" in shown and str(tmp_path) not in shown, shown


def test_the_projects_are_listed_each_with_its_studies(root):
    """Fails if `project list` refuses otherwise than naming `project new` while the root is not
    made, or misses a project — one in a group too — names one otherwise than by its path from the
    root, or lists other studies than its folders hold (projects.md § 1; web.md § 8.6)."""
    with kit.refused(Refused, "no-root", str(root)):
        kit.run("project.list")
    kit.apply("project.new", name="square", source="laplace_square")
    kit.apply("project.new", name="groups/slab", source="two_material")
    (root / "groups/slab/studies/sweeps").mkdir()
    (root / "groups/slab/studies/sweeps/later.toml").write_text("schema = 1\n")
    listed = kit.run("project.list")
    assert listed.root == str(root)
    assert [(p.name, p.path, p.studies) for p in listed.projects] == [
        ("groups/slab", str(root / "groups/slab"), ["benchmark", "sweeps/later"]),
        ("square", str(root / "square"), ["check"])]


def test_the_parts_named_beside_each_project_are_of_the_kind_the_layout_lists(definitions, root):
    """Fails if `project list` names beside each project the parts of a kind its code names, not
    the kind the layout lists: the framework names no part kind (projects.md § 4; web.md § 8.6)."""
    kit.apply("project.new", name="square", source="laplace_square")
    kit.rewrite(definitions / "project" / "layout.toml", 'listed = "study"', 'listed = "physics"')
    assert [(p.name, p.studies) for p in kit.run("project.list").projects] == [("square", ["electrostatics"])]


def test_a_new_project_offers_project_check_of_it_as_the_next_step(root):
    """Fails if `project new` does not end with `project check` of the new project as its next
    step — what writing a project's files leads to, the check then giving the project's own next
    step (plan.md § 2, rows 3–5; models.md § 11.2: "a new project is checked as any other")."""
    from femkit.core import text
    outcome = kit.apply("project.new", name="first", source="laplace_square")
    (step,) = outcome.next
    assert (step.call.operation, step.call.request) == ("project.check", {"project": "first"})
    assert str(step) in text.report(outcome.report)
