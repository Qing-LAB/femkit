"""The core building blocks (core.md)."""

from __future__ import annotations

import subprocess
import sys
import time
from enum import Enum

import pytest

from femkit.core import process
from femkit.core.errors import Busy, Refused
from femkit.core.eventlog import EventLog, fold
from femkit.core.locks import subject_lock
from femkit.core.states import Action, Machine, Rule


class Light(Enum):
    on = "on"
    off = "off"


def test_a_state_table_that_could_fall_through_or_strand_a_state_is_rejected():
    """Fails if a table with no `otherwise`, an unreachable state, a state with no action
    row, or a rule producing another machine's state could be built (core.md § 7)."""
    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("lit", Light.on, lambda f: f),), {Light.on: {}, Light.off: {}})
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
    m = Machine("light", Light, (Rule("lit", Light.on, lambda f: f), Rule("dark", Light.off)),
                {Light.on: {"off": Action("switch off", "light off")}, Light.off: {}})
    assert m.observe(True) is Light.on and m.observe(False) is Light.off
    with pytest.raises(Refused) as caught:
        m.require(Light.on, "on", "the light")
    assert caught.value.next == ("light off",)


def test_a_second_holder_of_a_subject_is_refused_not_queued():
    """Fails if a second mutation of one subject waits or proceeds instead of being
    refused immediately (core.md § 5)."""
    with subject_lock("env-x"):
        with pytest.raises(Busy):
            with subject_lock("env-x"):
                pass
    with subject_lock("env-x"):  # released when the first holder left
        pass


def test_the_event_log_fold_reads_progress_interruption_and_a_torn_line(tmp_path):
    """Fails if resume could skip an unfinished step, a dead writer's run read as in
    progress, or a torn last line break the read (core.md § 6)."""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    log = EventLog(tmp_path / "events.jsonl")
    log.append("operation-start", operation="env.install", pid=dead.pid)
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
    assert state.interrupted and not state.ended


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
