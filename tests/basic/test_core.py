"""The core building blocks (core.md)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from enum import Enum

import pytest

from tests.kit import hold, refused
from femkit.core import persist, view
from pydantic import Field, ValidationError
from femkit.core.schema import DefinitionError, Model, load_toml

from femkit.core import process
from femkit.core.errors import Busy, Refused
from femkit.core.issues import Issue
from femkit.core.eventlog import EventLog, fold
from femkit.core.locks import subject_lock
from femkit.core.states import Action, Machine, Rule


class Light(Enum):
    on = "on"
    off = "off"


def test_a_state_table_that_could_fall_through_or_strand_a_state_is_rejected():
    """Fails if a table with no `otherwise`, an `otherwise` before the last rule, an unreachable
    state, a state with no action row, or a rule producing another machine's state could be built
    (core.md § 7). Each table breaks one rule only, so each rejection is that rule's."""
    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("lit", Light.on, lambda f: f), Rule("dark", Light.off, lambda f: not f)),
                {Light.on: {}, Light.off: {}})
    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("always", Light.on), Rule("dark", Light.off)), {Light.on: {}, Light.off: {}})
    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("always", Light.on),), {Light.on: {}, Light.off: {}})
    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("lit", Light.on, lambda f: f), Rule("else", Light.off)), {Light.on: {}})

    class Other(Enum):
        x = "x"

    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("lit", Light.on, lambda f: f), Rule("x", Other.x, lambda f: f),
                             Rule("else", Light.off)), {Light.on: {}, Light.off: {}})


def test_a_disallowed_action_is_refused_with_the_allowed_commands():
    """Fails if a refusal does not carry the commands the state allows, read from the
    same table (core.md § 7: one source of "next")."""
    class Switch(Model):
        lamp: str = Field(json_schema_extra={"cli": "argument"})
        dim: bool = False

    m = Machine("light", Light, (Rule("lit", Light.on, lambda f: f), Rule("dark", Light.off)),
                {Light.on: {"off": Action("switch off", view.Verb("light.off", Switch), lambda name: {"lamp": name}),
                            "dim": Action("dim", view.Verb("light.off", Switch), lambda name: {"lamp": name, "dim": True}),
                            "nothing": Action("nothing to do")},
                 Light.off: {}})
    assert m.observe(True) is Light.on and m.observe(False) is Light.off
    with refused(Refused, "not-allowed", "hall") as caught:
        m.require(Light.on, "on", "hall")
    assert [n.command for n in caught.value.next] == ["python -m femkit light off hall",
                                                      "python -m femkit light off hall --dim"]
    assert caught.value.next[1].call.request == {"lamp": "hall", "dim": True}


def test_a_second_holder_of_a_subject_is_refused_not_queued():
    """Fails if a second command changing one subject waits or proceeds instead of being refused
    at once, or if one process's own nested hold is taken for a second holder (core.md § 5)."""
    first = hold("env-x", "alone")                       # another command, changing it
    try:
        with refused(Busy, "held", "env-x"):
            with subject_lock("env-x"):
                pass
    finally:
        first.stdin.close()
        first.wait()
    with subject_lock("env-x"):  # released when the first holder left; held again inside, one hold
        with subject_lock("env-x"):
            pass


def test_users_share_a_lock_and_a_change_is_refused_naming_each_and_what_ends_it():
    """Fails if two users cannot hold a subject shared at once, if something can take it alone
    while one does — or one join while it is held alone — or if the refusal does not name each
    live user and offer what ends its hold — a next step it cannot read offering nothing, never a
    crash (core.md § 5)."""
    from femkit.core.locks import is_held, require_free
    from femkit.core.locks import lock_path
    lock_path("env-x").parent.mkdir(parents=True, exist_ok=True)
    gone = {"pid": 999999999, "start": 1, "boot": process.boot_id()}
    lock_path("env-x").write_text(json.dumps({"process": gone, "by": "a holder long gone", "next": []}) + "\n"
                                  + json.dumps({"process": process.identify(os.getpid()).as_json(),
                                                "by": "a holder of another shape", "next": [{"no": "action"}]}) + "\n")
    users = [hold("env-x", "shared"), hold("env-x", "shared")]
    try:
        assert not is_held("env-x")                         # a use is not a change
        with refused(Busy, "held", "env-x") as caught:
            with subject_lock("env-x"):
                pass
        assert str(caught.value).count("a user of env-x") == 2 and [n.command for n in caught.value.next] == ["end it"]
        assert "long gone" not in str(caught.value)            # a holder that ended is not named
        with refused(Busy, "held", "env-x"):
            require_free("env-x")
        with subject_lock("env-x", shared=True):            # one more user
            pass
    finally:
        for p in users:
            p.communicate("")
    require_free("env-x")
    changer = hold("env-x", "alone")
    try:
        assert is_held("env-x")
        with refused(Busy, "held", "env-x"):
            with subject_lock("env-x", shared=True):
                pass
    finally:
        changer.communicate("")


def test_the_event_log_fold_reads_progress_interruption_and_a_torn_line(tmp_path):
    """Fails if resume could skip an unfinished step, a dead writer's run read as in
    progress, a run told alive by its process ID alone, the steps not told as the log
    tells them, or a torn last line break the read (core.md §§ 6, 8)."""
    writer = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    gone = process.identify(writer.pid)
    writer.kill()
    writer.wait()
    log = EventLog.of(tmp_path)
    log.append("operation-start", operation="env.install", process=gone.as_json())
    log.append("step-start", step="a")
    log.append("step-end", step="a", outcome="done")
    log.append("step-start", step="b")
    log.append("step-end", step="b", outcome="failed")
    log.append("step-start", step="b")
    with open(log.path, "a") as fh:
        fh.write('{"kind": "step-end", "step": "b", "outc')  # the writer died mid-line
    state = fold(log.events())
    assert state.finished_steps == ("a",)
    assert state.failed_step == "b"
    assert [(s.id, s.outcome) for s in state.steps] == [("a", "done"), ("b", "running")]
    assert state.interrupted and not state.ended
    me = process.identify(os.getpid())
    assert not fold([{"kind": "operation-start", "process": me.as_json()}]).interrupted
    reused = {**me.as_json(), "start": me.start + 1}           # this process's ID, another process's start
    assert fold([{"kind": "operation-start", "process": reused}]).interrupted


def test_an_interrupted_copy_of_a_folder_leaves_nothing_in_its_place(tmp_path):
    """Fails if a folder copy that stops part way leaves a half folder where the copy goes, or
    anything beside it (core.md § 4: "Every write is atomic")."""
    source, place = tmp_path / "source", tmp_path / "place"
    (source / "a").mkdir(parents=True)
    (source / "a" / "one").write_text("1")
    (source / "two").write_text("2")
    (source / "two").chmod(0)                              # the copy stops here
    place.mkdir()
    try:
        with pytest.raises(OSError):
            persist.copy_tree(source, place / "copy")
    finally:
        (source / "two").chmod(0o644)
    assert list(place.iterdir()) == []
    persist.copy_tree(source, place / "copy")
    assert (place / "copy" / "a" / "one").read_text() == "1" and (place / "copy" / "two").read_text() == "2"


@pytest.mark.parametrize("written", [None, b"# caf\xe9\n"], ids=["no file", "not UTF-8"])
def test_a_declared_file_that_is_absent_or_not_text_is_refused_at_the_file(tmp_path, written):
    """Fails if a declared file that is not there, or not UTF-8 text, fails as a defect instead of
    a `DefinitionError` naming the file (core.md § 2: "One TOML reader")."""
    path = tmp_path / "declared.toml"
    if written is not None:
        path.write_bytes(written)
    with refused(DefinitionError, "definition-invalid", str(path)):
        load_toml(path, Model)


def test_a_findings_code_is_kebab_case_or_refused_when_made():
    """Fails if a finding can be made with a code that is not kebab-case — the code tests and
    programs match on (core.md § 10)."""
    assert Issue(severity="error", code="preamble-unset", subject="x", message="m").code == "preamble-unset"
    for code in ("Preamble_unset", "preamble unset", "-preamble", ""):
        with pytest.raises(ValidationError):
            Issue(severity="error", code=code, subject="x", message="m")


def test_a_timeout_stops_the_whole_process_group(tmp_path):
    """Fails if a timed-out command leaves its children running (core.md § 8)."""
    pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time;"
        f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        f"open({str(pid_file)!r}, 'w').write(str(c.pid)); time.sleep(60)"
    )
    started = time.time()
    result = process.run([sys.executable, "-c", script], timeout=2, log=tmp_path / "out.log")
    assert result.timed_out and result.returncode is None
    assert time.time() - started < 20
    child = int(pid_file.read_text())
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with open(f"/proc/{child}/stat") as fh:
                if fh.read().split()[2] == "Z":
                    break
        except FileNotFoundError:
            break
        time.sleep(0.1)
    else:
        pytest.fail(f"child {child} still running after the timeout")
