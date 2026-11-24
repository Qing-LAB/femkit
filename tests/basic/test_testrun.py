"""The test runner and its progress log (testing.md § 4.8).

Logs in the runner's own record format are fair input: the format is femkit's.
The rules only a live run shows run a real pytest session through the plugin.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools import testrun

REPO = Path(testrun.REPO)


def write_log(path: Path, records: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def start(run="r1", pid=None, code="c0"):
    return {"event": "start", "run": run, "pid": pid if pid is not None else dead_pid(),
            "time": 100.0, "code": code, "asked": []}


def rec(nodeid, outcome="passed", run="r1", reason=""):
    return {"event": "test", "run": run, "nodeid": nodeid, "outcome": outcome, "reason": reason, "time": 101.0}


COLLECTED = {"event": "collected", "run": "r1", "n": 2, "time": 100.5}


def done(status=0, run="r1"):
    return {"event": "done", "run": run, "exitstatus": status, "time": 102.0}


# --- one test per row of the state table (§ 4.4) --------------------------------

@pytest.mark.parametrize("records, state", [
    ([], "no-data"),
    ([rec("a"), done()], "unusable"),                                  # cut under a writer: no start
    ([start(), rec("a"), done()], "unusable"),                         # collection never finished
    ([start(), COLLECTED, rec("a"), rec("b", run="r2"), done()], "interleaved"),
    ([start(), COLLECTED, rec("a"), done(1)], "partial"),
    ([start(), COLLECTED, rec("a"), rec("b"), done(1)], "unexplained"),   # a canary fired
    ([start(), COLLECTED, rec("a"), rec("b"), done()], "done"),
    ([start(), COLLECTED, rec("a")], "abandoned"),                     # the writer is gone
], ids=["no-data", "no-start", "no-collected", "interleaved", "partial", "unexplained", "done", "abandoned"])
def test_each_state_is_observed_from_the_log(tmp_path, records, state):
    """Fails if any row of the batch state table reads wrong — above all, a count printed
    as a result from a log that is not one complete run (testing.md § 4.4)."""
    path = tmp_path / "b.jsonl"
    if records:
        write_log(path, records)
    assert testrun.summarise("b", str(path))["state"] == state


def test_a_live_writer_is_running_until_its_log_falls_silent(tmp_path):
    """Fails if a live run reads as dead, or a log silent past the limit still reads as
    running because its pid was reused (testing.md § 4.4)."""
    path = write_log(tmp_path / "b.jsonl", [start(pid=os.getpid()), COLLECTED, rec("a")])
    assert testrun.summarise("b", str(path))["state"] == "running"
    later = time.time() + testrun.SILENCE_LIMIT + 1
    assert testrun.summarise("b", str(path), now=later)["state"] == "abandoned"


def test_counting_rules():
    """Fails if a teardown failure counts as a second test, a collection failure is not a
    failure, or a skip or expected failure counts as a pass (testing.md § 4.4)."""
    records = [start(), {**COLLECTED, "n": 3},
               rec("a"), rec("a [teardown]", "failed"),
               {"event": "collect", "run": "r1", "nodeid": "t_broken.py", "outcome": "failed", "reason": "ImportError"},
               rec("b", "skipped", reason="no GPU"), rec("c", "xfailed", reason="known"), done(1)]
    path = Path(os.environ["FEMKIT_CACHE_DIR"]) / "b.jsonl"
    s = testrun.summarise("b", str(write_log(path, records)))
    assert s["ran"] == 3
    assert (s["passed"], s["failed"], s["skipped"], s["xfailed"]) == (1, 2, 1, 1)
    assert s["state"] == "done"
    assert dict(s["not_run"]) == {"no GPU": 1, "known": 1}


def test_a_done_of_other_or_unknown_code_is_not_todays_result(tmp_path):
    """Fails if a finished run of different code reads as a result about this code
    (testing.md § 4.5)."""
    s = testrun.summarise("b", str(write_log(tmp_path / "b.jsonl", [start(code="old"), COLLECTED, rec("a"), rec("b"), done()])))
    assert testrun.code_verdict(s, "new") == "other"
    assert testrun.code_verdict(s, None) == "unknown"
    assert testrun.code_verdict(s, "old") is None


def test_a_second_run_of_a_batch_is_refused(tmp_path):
    """Fails if two runs of one batch can hold its lock together (testing.md § 4.3)."""
    held = testrun.acquire_batch_lock("basic", str(tmp_path))
    assert held is not None
    assert testrun.acquire_batch_lock("basic", str(tmp_path)) is None
    held.close()
    assert testrun.acquire_batch_lock("basic", str(tmp_path)) is not None


# --- live runs through the plugin -------------------------------------------------

def pytest_session(tmp_path: Path, files: dict[str, str], log: Path, *extra: str) -> int:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    for name, text in files.items():
        (project / name).write_text(text)
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(project), "-p", "tools.progress_plugin",
         f"--progress-file={log}", "-p", "no:cacheprovider", "-q", *extra],
        cwd=project, env=env, capture_output=True, text=True, timeout=120,
    ).returncode


def test_a_log_is_emptied_only_after_a_finished_run(tmp_path):
    """Fails if a new run wipes the records of a run that did not finish (testing.md § 4.2)."""
    log = write_log(tmp_path / "b.jsonl", [start(run="killed"), COLLECTED, rec("old")])
    pytest_session(tmp_path, {"test_one.py": "def test_x():\n    pass\n"}, log)
    runs = [r["run"] for r in testrun.read_records(str(log)) if r["event"] == "start"]
    assert runs[0] == "killed" and len(runs) == 2
    pytest_session(tmp_path, {"test_one.py": "def test_x():\n    pass\n"}, log)
    starts = [r for r in testrun.read_records(str(log)) if r["event"] == "start"]
    assert len(starts) == 1  # the previous run reached `done`, so its log was emptied


def test_a_teardown_failure_is_recorded(tmp_path):
    """Fails if a failure in teardown — where the session canaries fire — leaves no record
    (testing.md § 4.2)."""
    files = {"test_t.py": (
        "import pytest\n"
        "@pytest.fixture\n"
        "def breaks_after():\n    yield\n    raise RuntimeError('teardown')\n"
        "def test_x(breaks_after):\n    pass\n")}
    log = tmp_path / "b.jsonl"
    pytest_session(tmp_path, files, log)
    s = testrun.summarise("b", str(log))
    assert s["failed"] == 1 and s["ran"] == 1 and s["state"] == "done"


def test_a_spread_run_reads_as_one_run(tmp_path):
    """Fails if workers write their own generations, or IDs keep xdist's group suffix
    (testing.md § 4.2, § 4.6)."""
    files = {f"test_{i}.py": "import pytest\n@pytest.mark.xdist_group('g')\ndef test_x():\n    pass\n"
             for i in range(4)}
    log = tmp_path / "b.jsonl"
    pytest_session(tmp_path, files, log, "-n", "2", "--dist", "loadgroup")
    s = testrun.summarise("b", str(log))
    assert s["state"] == "done" and s["ran"] == 4
    assert all("@" not in r["nodeid"] for r in testrun.read_records(str(log)) if r["event"] == "test")


def test_a_dead_worker_leaves_the_run_partial(tmp_path):
    """Fails if a run whose worker died reads as done (testing.md § 4.6)."""
    files = {"test_a.py": "import os\ndef test_dies():\n    os._exit(3)\n",
             "test_b.py": "def test_1():\n    pass\ndef test_2():\n    pass\n"}
    log = tmp_path / "b.jsonl"
    pytest_session(tmp_path, files, log, "-n", "1", "--max-worker-restart", "0")
    s = testrun.summarise("b", str(log))
    assert s["state"] == "partial" and s["failed"] == 1


def test_rerunning_failures_with_none_recorded_runs_nothing(tmp_path, monkeypatch):
    """Fails if `run lf` with no recorded failure runs every test, as pytest's own
    --last-failed would (testing.md § 4.7)."""
    monkeypatch.setattr(testrun, "REPO", str(tmp_path))
    monkeypatch.setattr(testrun, "PROGRESS_DIR", str(tmp_path / ".test-progress"))
    assert testrun.main(["run", "lf"]) == 0
    assert not (tmp_path / ".test-progress").exists()


def test_field_and_engine_run_in_one_process_even_in_part():
    """Fails if field or engine tests — whole or a hand-picked part — are spread over
    workers, so two installs or calculations compete (testing.md § 4.6)."""
    assert testrun.select("field", [], 8)[2] == 1
    assert testrun.select("tests/engine/test_x.py", [], 8) == (["tests/engine/test_x.py"], "custom", 1)
    assert testrun.select("basic", [], 8)[2] == 8
