"""Where projects are, and how a command names one (projects.md § 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.kit import ctx, refused, rewrite, set_root
from femkit.core.errors import Refused, Unstated, UsageError
from femkit.projects import location
from femkit.projects.project import PROJECT_FILE, Project


def make(folder: Path, files: dict[str, str] | None = None) -> Path:
    """A project as a person leaves one: its folder, its project file, and ``files`` by their path in it."""
    for rel, text in {PROJECT_FILE: 'description = "a test project"\n', **(files or {})}.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text)
    return folder


@pytest.fixture
def root(tmp_path) -> Path:
    """A projects root, stated: a project at its top, two in groups, one in another's folder, the
    global library and a `.`-folder each holding a project file, a group with no project."""
    top = tmp_path / "projects"
    make(top / "bowtie", {"studies/sweeps/gap_sweep.toml": "", "components/bowtie/geometry.py": ""})
    make(top / "bowtie" / "inner")
    make(top / "groups" / "dimer")
    make(top / "groups" / "deep" / "er")
    make(top / "materials" / "old")
    (top / "materials" / "vacuum").mkdir()
    (top / "materials" / "vacuum" / "material.toml").write_text("")
    make(top / ".trash" / "gone")
    (top / "empty").mkdir()
    (top / "notes.txt").write_text("")
    set_root(top)
    return top


def test_an_unset_root_is_refused_naming_the_setting_and_how_to_state_it(tmp_path):
    """Fails if, with `paths.projects` unset, finding or naming a project guesses a root instead of
    refusing as unstated, or the refusal does not offer the step its field's declaration chooses:
    `config init`, which asks for it, since the key declares its question (projects.md § 1;
    config.md § 3.2: "a setting's next step is built in one place … its step is `config init`")."""
    for call in (lambda c: location.root(c), lambda c: location.projects(c),
                 lambda c: location.locate(c, "bowtie", tmp_path), lambda c: location.locate(c, None, tmp_path)):
        with refused(Unstated, "setting-unset", "paths.projects") as caught:
            call(ctx())
        assert [(a.call.operation, a.call.request) for a in caught.value.next] == [("config.init", {})]


def test_a_root_that_is_no_folder_is_refused_naming_project_new(tmp_path):
    """Fails if a projects root that does not exist, or is a file, is taken as a root with no
    projects instead of refused, or the refusal does not name `project new`, which makes the root,
    before the `config set` that states another (projects.md § 1: "every other command refuses a
    root that is no folder, naming `project new`")."""
    (tmp_path / "a-file").write_text("")
    for stated in (tmp_path / "absent", tmp_path / "a-file"):
        set_root(stated)
        with refused(Refused, "no-root", str(stated)) as caught:
            location.projects(ctx())
        assert [(a.call.operation, a.call.request, [f.field for f in a.fills]) for a in caught.value.next] == [
            ("project.new", {}, ["name", "source"]), ("config.set", {"key": "paths.projects"}, ["value"])]


def test_the_projects_are_listed_by_name_with_grouped_ones_and_nothing_else(root):
    """Fails if the listing misses a project in a group folder, names one otherwise than by its path
    from the root, or takes for a project the global library, a `.`-folder, a group with none, or a
    project file inside another project's folder (projects.md § 1)."""
    (root / "My Project").mkdir()                                  # a name the rule cannot name: none to list,
    (root / "My Project" / "project.toml").write_text("")           # and no reason to refuse the others
    listed = location.projects(ctx())
    assert [p.name for p in listed] == ["bowtie", "groups/deep/er", "groups/dimer"]
    assert [p.folder for p in listed] == [root / "bowtie", root / "groups/deep/er", root / "groups/dimer"]


def test_the_folders_holding_a_global_library_are_the_layouts(root, definitions):
    """Fails if which folder at the root holds a global library — and so no project — is known
    otherwise than from the layout's kinds declared with a library: a library's folder renamed in
    the layout is passed by under its new name, and the old one is a folder like any other
    (projects.md §§ 1, 4: "the root's search for projects passes it by")."""
    rewrite(definitions / "project" / "layout.toml", 'folder = "materials"', 'folder = "library"')
    make(root / "library" / "kept")
    assert [p.name for p in location.projects(ctx())] == ["bowtie", "groups/deep/er", "groups/dimer", "materials/old"]


def test_a_project_is_named_by_its_path_from_the_root(root, tmp_path):
    """Fails if a project named by its path from the root, in a group or not, is not found there
    — wherever the command runs (projects.md § 1)."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert location.locate(ctx(), "bowtie", elsewhere) == Project(root, "bowtie")
    assert location.locate(ctx(), "groups/dimer", root / "bowtie") == Project(root, "groups/dimer")


def test_with_none_named_the_project_is_the_folder_the_command_runs_in(root):
    """Fails if, with no project named, the project is not found from its own folder, from a folder
    deep inside it, or from a group's project; or if a project file inside a project's folder is
    taken for a project of its own (projects.md § 1)."""
    for cwd, name in [(root / "bowtie", "bowtie"), (root / "bowtie/studies/sweeps", "bowtie"),
                      (root / "bowtie/inner", "bowtie"), (root / "groups/deep/er", "groups/deep/er")]:
        assert location.locate(ctx(), None, cwd) == Project(root, name), cwd


def test_a_root_stated_through_a_link_finds_the_project_a_command_runs_in(root, tmp_path):
    """Fails if a root stated through a symbolic link misses the project a command runs in — the
    folder a process runs in is its real path (projects.md § 1)."""
    link = tmp_path / "link"
    link.symlink_to(root)
    set_root(link)
    assert location.locate(ctx(), None, (root / "bowtie" / "studies").resolve()) == Project(link, "bowtie")


def test_a_folder_in_no_project_is_refused(root, tmp_path):
    """Fails if, with no project named, a folder in no project — the root itself, a group, the
    global library, a `.`-folder, a folder the name rule cannot name, a folder outside the root —
    yields a project, or another refusal, instead of a refusal naming that folder (projects.md
    §§ 1, 3: a project is named by its path from the root)."""
    outside = tmp_path / "outside"
    make(outside)
    make(root / "groups" / "My Project")
    for cwd in (root, root / "groups", root / "materials/old", root / ".trash/gone", root / "groups/My Project",
                outside):
        with refused(UsageError, "not-in-a-project", str(cwd)):
            location.locate(ctx(), None, cwd)


def test_a_name_with_no_project_is_refused(root):
    """Fails if a name that is no project — none there, a group, the global library, a project
    file inside another project's folder — yields a project instead of a refusal naming it
    (projects.md § 1)."""
    for name in ("nothing", "groups", "materials", "materials/old", "bowtie/inner"):
        with refused(UsageError, "no-such-project", name):
            location.locate(ctx(), name, root)


def test_a_name_breaking_the_name_rule_is_refused(root):
    """Fails if a project's name that breaks the name rule — capitals, a step out of the root — is
    looked for instead of refused (projects.md §§ 1, 3)."""
    make(root / "Bowtie")
    make(root.parent / "escaped")
    for name in ("Bowtie", "../escaped"):
        with refused(UsageError, "bad-name", name):
            location.locate(ctx(), name, root)


def test_a_path_in_a_project_is_relative_and_stays_inside(root):
    """Fails if a path in a project is formed from an absolute path or one stepping out with `..`
    — a project holding such a path would not move whole (projects.md § 1)."""
    project = location.locate(ctx(), "bowtie", root)
    assert project.path("studies/sweeps/gap_sweep.toml") == root / "bowtie/studies/sweeps/gap_sweep.toml"
    for bad in ("/etc/hosts", "../groups/dimer/project.toml", "studies/../../groups"):
        with refused(UsageError, "outside-project", bad):
            project.path(bad)


def test_the_doors_refusals_of_a_project_offer_the_projects_there(root):
    """Fails if naming a project the root does not hold, or running a command in a folder of no
    project, is refused with nothing to do instead — the person left to guess the names there
    (projects.md § 8: "the door's refusals fill their `next`")."""
    for call, code in ((lambda c: location.locate(c, "nowhere", root), "no-such-project"),
                       (lambda c: location.locate(c, None, root), "not-in-a-project")):
        with refused(UsageError, code) as caught:
            call(ctx())
        assert [a.call.operation for a in caught.value.next] == ["project.list"]
