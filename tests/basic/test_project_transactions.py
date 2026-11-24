"""Transactions and undo (projects.md § 7): a change planned as file steps with nothing written,
applied whole or not at all under the project's lock, and taken back and done again through the
project's history."""

from __future__ import annotations

import hashlib

import pytest

from femkit.core.errors import Busy, PlanStale, Refused, UsageError
from femkit.projects.project import Project
from femkit.projects.transactions import FileStep, apply, plan, redo, undo
from tests.kit import apply as operate
from tests.kit import ctx, hold, refused

FILES = {"project.toml": "name = 'demo'\n", "studies/a.toml": "a = 1\n", "studies/b.toml": "b = 1\n",
         "physics/p.toml": "p = 1\n"}

#: One change of every kind; the moved file is changed again where it lands.
CHANGE = [FileStep("change", "project.toml", text="name = 'renamed'\n"),
          FileStep("create", "studies/g/c.toml", text="c = 1\n"),
          FileStep("move", "studies/a.toml", to="studies/g/a.toml"),
          FileStep("change", "studies/g/a.toml", text="a = 2\n"),
          FileStep("delete", "physics/p.toml")]

#: The project as CHANGE leaves it: every file's text, every folder as None.
AFTER = {"physics": None, "project.toml": "name = 'renamed'\n", "studies": None, "studies/b.toml": "b = 1\n",
         "studies/g": None, "studies/g/a.toml": "a = 2\n", "studies/g/c.toml": "c = 1\n"}


def a_project(tmp_path, files: dict[str, str] = FILES) -> Project:
    project = Project(root=tmp_path / "root", name="demo")
    project.folder.mkdir(parents=True)
    for relative, text in files.items():
        project.path(relative).parent.mkdir(parents=True, exist_ok=True)
        project.path(relative).write_text(text)
    return project


def tree(project: Project) -> dict[str, str | None]:
    """Every file's text and every folder (None), by its path in the project; `.femkit` aside."""
    return {p.relative_to(project.folder).as_posix(): p.read_text() if p.is_file() else None
            for p in sorted(project.folder.rglob("*")) if p.relative_to(project.folder).parts[0] != ".femkit"}


def planned(project: Project, steps: list[FileStep], read: dict | None = None, check=lambda overlay: []):
    return plan(project, steps, read=read or {}, check=check, describe="the change")


def change(project: Project, *steps: FileStep) -> None:
    apply(planned(project, list(steps)), ctx())


def sha256(project: Project, relative: str) -> str:
    return hashlib.sha256(project.path(relative).read_bytes()).hexdigest()


def test_a_plan_writes_nothing_and_checks_the_project_as_the_change_leaves_it(tmp_path):
    """Fails if planning a change writes anything, or if its check reads the project otherwise
    than as the change leaves it — each step read after the ones before it (projects.md § 7)."""
    project = a_project(tmp_path)
    before = tree(project)
    seen = []
    planned(project, CHANGE, check=lambda overlay: seen.append(overlay) or [])
    assert tree(project) == before and not project.path(".femkit").exists()
    assert seen == [{"project.toml": "name = 'renamed'\n", "studies/g/c.toml": "c = 1\n", "studies/a.toml": None,
                     "studies/g/a.toml": "a = 2\n", "physics/p.toml": None}]


def test_a_change_the_check_finds_breaking_is_refused_naming_each_problem(tmp_path):
    """Fails if a change that would leave a part unloadable or a reference broken is planned, or
    its refusal does not name each problem the check found (projects.md § 7)."""
    project = a_project(tmp_path)

    def check(overlay):
        return [(path, "does not load") for path, text in overlay.items() if text is not None and "broken" in text]

    steps = [FileStep("change", "studies/a.toml", text="broken"), FileStep("change", "studies/b.toml", text="b = 2\n"),
             FileStep("create", "studies/c.toml", text="broken")]
    with refused(Refused, "change-breaks", "studies/a.toml, studies/c.toml"):
        planned(project, steps, check=check)
    planned(project, steps[1:2], check=check)


BAD = {
    "outside": ([FileStep("create", "../x.toml", text="")], "../x.toml"),
    "absolute": ([FileStep("create", "/etc/x.toml", text="")], "/etc/x.toml"),
    "moved outside": ([FileStep("move", "studies/a.toml", to="../a.toml")], "studies/a.toml"),
    "create over a file": ([FileStep("create", "studies/a.toml", text="")], "studies/a.toml"),
    "change of no file": ([FileStep("change", "studies/z.toml", text="")], "studies/z.toml"),
    "delete of no file": ([FileStep("delete", "studies/z.toml")], "studies/z.toml"),
    "move of no file": ([FileStep("move", "studies/z.toml", to="studies/y.toml")], "studies/z.toml"),
    "move onto a file": ([FileStep("move", "studies/a.toml", to="studies/b.toml")], "studies/a.toml"),
    "create over a folder": ([FileStep("create", "studies", text="")], "studies"),
    "move onto a folder": ([FileStep("move", "studies/a.toml", to="physics")], "studies/a.toml"),
    "no text": ([FileStep("create", "studies/c.toml")], "studies/c.toml"),
    "change of a file deleted before": ([FileStep("delete", "studies/a.toml"),
                                         FileStep("change", "studies/a.toml", text="")], "studies/a.toml"),
}


@pytest.mark.parametrize("steps, subject", BAD.values(), ids=BAD.keys())
def test_a_step_that_cannot_be_written_is_refused(tmp_path, steps, subject):
    """Fails if a step outside the project, a create over a file, a change, delete or move of no
    file, a move onto a file, a step meeting a folder, or one missing what its kind needs is
    planned — each step read as the steps before it leave the files (projects.md § 7)."""
    project = a_project(tmp_path)
    with refused(UsageError, "bad-step", subject):
        planned(project, steps)
    planned(project, [FileStep("create", "studies/c.toml", text=""), FileStep("change", "studies/c.toml", text="c"),
                      FileStep("move", "studies/c.toml", to="studies/d.toml"), FileStep("delete", "studies/d.toml")])


def test_apply_writes_every_step(tmp_path):
    """Fails if applying a transaction leaves any of its steps unwritten (projects.md § 7)."""
    project = a_project(tmp_path)
    apply(planned(project, CHANGE), ctx())
    assert tree(project) == AFTER


@pytest.mark.parametrize("where", ["a step", "the record"])
def test_a_failure_midway_leaves_every_file_as_it_was(tmp_path, where):
    """Fails if a transaction the file system refuses midway — at a step, or at its record for
    undo — leaves any step written, a folder made, or a transaction to undo (projects.md § 7)."""
    project = a_project(tmp_path)
    steps = list(CHANGE)
    if where == "a step":
        steps.append(FileStep("create", "studies/b.toml/x.toml", text=""))   # its folder would be a file
    else:
        project.path(".femkit/history").parent.mkdir()
        project.path(".femkit/history").write_text("")                     # no record can be written below it
    before = tree(project)
    tx = planned(project, steps)
    with pytest.raises(OSError):
        apply(tx, ctx())
    assert tree(project) == before
    with refused(Refused, "nothing-to-undo", project.name):
        undo(project, ctx())


@pytest.mark.parametrize("path", ["studies/b.toml", "studies/a.toml", "studies/g/c.toml"],
                         ids=["read by the caller", "touched", "made where it creates"])
def test_a_file_changed_since_the_plan_refuses_apply(tmp_path, path):
    """Fails if a transaction is applied after a file its plan read changed: one the caller read,
    one it touches, or one appearing where it creates (projects.md § 7)."""
    project = a_project(tmp_path)
    tx = planned(project, CHANGE, read={"studies/b.toml": sha256(project, "studies/b.toml")})
    project.path(path).parent.mkdir(exist_ok=True)
    project.path(path).write_text("by hand\n")
    before = tree(project)
    with refused(PlanStale, "files-changed", path):
        apply(tx, ctx())
    assert tree(project) == before


def test_apply_undo_and_redo_are_refused_while_another_process_holds_the_project(tmp_path):
    """Fails if a transaction, an undo or a redo goes ahead while another process holds the
    project's lock (projects.md § 7, core.md § 5)."""
    project = a_project(tmp_path)
    tx = planned(project, CHANGE)
    for turn in (lambda: apply(tx, ctx()), lambda: undo(project, ctx()), lambda: redo(project, ctx())):
        before = tree(project)
        holder = hold(project.subject, "alone")
        try:
            with refused(Busy, "held", project.subject):
                turn()
            assert tree(project) == before
        finally:
            holder.stdin.close()
            holder.wait()
        turn()


def test_a_group_folder_is_made_by_its_first_part_and_removed_with_its_last(tmp_path):
    """Fails if a part written into a group that is not there fails or leaves no folder, or if a
    group emptied by a move or a delete is left behind — or a top-level folder, or the project's,
    removed with its last file (projects.md § 7)."""
    project = a_project(tmp_path, {"project.toml": "", "studies/a.toml": "",
                                   "components/c/component.toml": "", "components/c/geometry.py": ""})
    change(project, FileStep("create", "studies/g/h/x.toml", text=""))
    change(project, FileStep("create", "studies/g/y.toml", text=""))
    change(project, FileStep("move", "studies/g/h/x.toml", to="studies/x.toml"))
    assert not project.path("studies/g/h").exists() and project.path("studies/g").is_dir()
    change(project, FileStep("delete", "studies/g/y.toml"))
    assert not project.path("studies/g").exists()
    change(project, FileStep("delete", "studies/x.toml"), FileStep("delete", "studies/a.toml"))
    assert project.path("studies").is_dir() and not any(project.path("studies").iterdir())
    change(project, FileStep("move", "components/c/component.toml", to="components/g/c/component.toml"),
           FileStep("move", "components/c/geometry.py", to="components/g/c/geometry.py"))
    assert not project.path("components/c").exists() and project.path("components/g/c/geometry.py").is_file()
    undo(project, ctx())
    assert not project.path("components/g").exists() and project.path("components/c/geometry.py").is_file()
    change(project, FileStep("delete", "project.toml"))
    assert project.folder.is_dir()


def test_undo_and_redo_restore_texts_and_moves(tmp_path):
    """Fails if an undo leaves any file — changed, made, moved or removed — otherwise than before
    its transaction, or a redo otherwise than after it (projects.md § 7)."""
    project = a_project(tmp_path)
    before = tree(project)
    apply(planned(project, CHANGE), ctx())
    assert undo(project, ctx()).describe == "the change"
    assert tree(project) == before
    assert redo(project, ctx()).describe == "the change"
    assert tree(project) == AFTER
    undo(project, ctx())
    assert tree(project) == before


def test_undo_reaches_back_exactly_projects_undo_transactions(tmp_path):
    """Fails if undo reaches past `projects.undo` transactions, as it says when undoing, or if
    the history keeps more than it said when each was recorded (projects.md § 7, config.md § 3)."""
    project = a_project(tmp_path, {"n.toml": "n = 0\n"})

    def n() -> str:
        return project.path("n.toml").read_text()

    for i in (1, 2, 3):
        change(project, FileStep("change", "n.toml", text=f"n = {i}\n"))
    operate("config.set", key="projects.undo", value="2")
    undo(project, ctx())
    undo(project, ctx())
    assert n() == "n = 1\n"
    with refused(Refused, "nothing-to-undo", project.name):
        undo(project, ctx())
    redo(project, ctx())
    redo(project, ctx())
    change(project, FileStep("change", "n.toml", text="n = 4\n"))   # kept: the newest two
    operate("config.set", key="projects.undo", value="5")
    undo(project, ctx())
    undo(project, ctx())
    assert n() == "n = 2\n"
    with refused(Refused, "nothing-to-undo", project.name):
        undo(project, ctx())


def test_undo_reaches_back_a_hundred_transactions_while_the_setting_is_unset(tmp_path):
    """Fails if, with `projects.undo` unset, undo reaches back any other number than 100
    (config.md § 3, projects.md § 7)."""
    project = a_project(tmp_path, {"n.toml": "n = 0\n"})
    for i in range(1, 102):
        change(project, FileStep("change", "n.toml", text=f"n = {i}\n"))
    for _ in range(100):
        undo(project, ctx())
    assert project.path("n.toml").read_text() == "n = 1\n"
    with refused(Refused, "nothing-to-undo", project.name):
        undo(project, ctx())


def test_undo_and_redo_are_refused_when_a_file_changed_by_hand(tmp_path):
    """Fails if an undo or a redo goes ahead over a file changed by hand since — edited, or made
    where the transaction would create — or does not name it (projects.md § 7)."""
    project = a_project(tmp_path)
    apply(planned(project, CHANGE), ctx())
    project.path("studies/g/a.toml").write_text("by hand\n")
    with refused(Refused, "changed-by-hand", "studies/g/a.toml"):
        undo(project, ctx())
    assert tree(project) == {**AFTER, "studies/g/a.toml": "by hand\n"}
    project.path("studies/g/a.toml").write_text("a = 2\n")
    undo(project, ctx())
    before = tree(project)
    project.path("studies/g").mkdir()
    project.path("studies/g/c.toml").write_text("by hand\n")
    with refused(Refused, "changed-by-hand", "studies/g/c.toml"):
        redo(project, ctx())
    assert tree(project) == {**before, "studies/g": None, "studies/g/c.toml": "by hand\n"}


def test_a_new_transaction_after_an_undo_drops_the_redo(tmp_path):
    """Fails if what was undone can still be redone after a new transaction, or the new one is
    not the next undone (projects.md § 7)."""
    project = a_project(tmp_path, {"n.toml": "n = 0\n"})
    change(project, FileStep("change", "n.toml", text="n = 1\n"))
    change(project, FileStep("change", "n.toml", text="n = 2\n"))
    undo(project, ctx())
    change(project, FileStep("create", "m.toml", text="m = 1\n"))
    with refused(Refused, "nothing-to-redo", project.name):
        redo(project, ctx())
    undo(project, ctx())
    assert not project.path("m.toml").exists() and project.path("n.toml").read_text() == "n = 1\n"
    undo(project, ctx())
    assert project.path("n.toml").read_text() == "n = 0\n"
    with refused(Refused, "nothing-to-undo", project.name):
        undo(project, ctx())


def test_a_record_naming_a_file_outside_the_project_is_refused(tmp_path):
    """Fails if an undo follows a history whose record names a file by a path that leaves the
    project — a record names files by their path in the project, checked to lie inside it
    (projects.md § 7)."""
    project = a_project(tmp_path, {"project.toml": ""})
    change(project, FileStep("create", "studies/x.toml", text="x = 1\n"))
    for record in project.path(".femkit/history").rglob("*"):
        if record.is_file():
            record.write_text(record.read_text().replace('"studies/x.toml"', '"../victim.toml"'))
    victim = project.folder.parent / "victim.toml"
    victim.write_text("x = 1\n")
    with refused(UsageError, "outside-project", "../victim.toml"):
        undo(project, ctx())
    assert victim.read_text() == "x = 1\n"


def test_no_change_writes_into_femkits_own_folder(tmp_path):
    """Fails if a change may write into `.femkit/`, where the history it is recorded in lives: the
    record would overwrite it, or undo would take back its own history (projects.md §§ 2, 7)."""
    project = Project(tmp_path / "root", "p")
    project.folder.mkdir(parents=True)
    with refused(UsageError, "bad-step", ".femkit/history/history.json"):
        plan(project, [FileStep("create", ".femkit/history/history.json", text="{}")], read={}, check=lambda o: [])


# ------------------------------------------------------------------ what the review of C found

@pytest.mark.parametrize("held", ["{not json", '{"transactions": [{"describe": "x", "steps": [{"kind": "move", '
                                                '"path": "studies/a.toml"}]}], "at": 1}'],
                         ids=["no JSON", "a move with nowhere to go"])
def test_a_history_that_does_not_load_is_a_refusal_and_changes_nothing(tmp_path, held):
    """Fails if a history edited or broken by hand makes a change fail as a defect, or lets it
    write anything, instead of refusing it (projects.md § 7; core.md § 9)."""
    project = a_project(tmp_path)
    project.path(".femkit/history").mkdir(parents=True)
    project.path(".femkit/history/history.json").write_text(held)
    before = tree(project)
    with refused(Refused, "history-unreadable", ".femkit/history/history.json"):
        change(project, FileStep("change", "studies/b.toml", text="b = 2\n"))
    for turn in (undo, redo):
        with refused(Refused, "history-unreadable", ".femkit/history/history.json"):
            turn(project, ctx())
    assert tree(project) == before


def test_redo_after_the_reach_is_lowered_does_the_next_change_again(tmp_path):
    """Fails if lowering `projects.undo` while changes are undone makes redo skip to a later one,
    then refuse it as changed by hand (projects.md § 7)."""
    project = a_project(tmp_path)
    for n in range(2, 7):
        change(project, FileStep("change", "studies/b.toml", text=f"b = {n}\n"))
    for _ in range(4):
        undo(project, ctx())
    assert project.path("studies/b.toml").read_text() == "b = 2\n"
    operate("config.set", key="projects.undo", value="2")
    redo(project, ctx())
    assert project.path("studies/b.toml").read_text() == "b = 3\n"


def test_a_change_a_killed_process_left_half_written_is_put_back_first(tmp_path):
    """Fails if a change interrupted between its steps — its first file written, the rest not —
    stays half written: the next change must put every file back first (projects.md § 7:
    "writes every step or none")."""
    from femkit.core import persist
    from femkit.projects.transactions import HISTORY, History, Pending, _trace
    project = a_project(tmp_path)
    before = tree(project)
    steps = [FileStep("change", "project.toml", text="name = 'half'\n"),
             FileStep("move", "studies/a.toml", to="studies/g/a.toml"), FileStep("delete", "physics/p.toml")]
    pending = Pending(steps=_trace(project, steps), back=False)        # what apply records before its first file
    persist.write_json(project.path(HISTORY), History(pending=pending).model_dump(mode="json"))
    project.path("project.toml").write_text("name = 'half'\n")                     # its first step, then killed
    project.path("studies/g").mkdir()
    project.path("studies/a.toml").rename(project.path("studies/g/a.toml"))      # and its second
    change(project, FileStep("create", "studies/z.toml", text="z = 1\n"))
    assert tree(project) == {**before, "studies/z.toml": "z = 1\n"}


def test_a_change_inside_the_hold_its_runner_took_is_not_refused_by_it(tmp_path):
    """Fails if a change applied while this process already holds the project's lock — as an
    operation's runner will — is refused as busy by its own hold (core.md § 5)."""
    from femkit.core.locks import subject_lock
    project = a_project(tmp_path)
    with subject_lock(project.subject):
        change(project, FileStep("change", "studies/b.toml", text="b = 2\n"))
        undo(project, ctx())
    assert project.path("studies/b.toml").read_text() == "b = 1\n"
