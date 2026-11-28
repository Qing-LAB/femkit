"""The pytest plugin that writes a tier run's progress log (testing.md § 4.2).

One record per result, flushed at once, so the log is current while the run
goes. A log is emptied only when its last record is `done`; otherwise the new
run appends its own `start` after it, so a live or killed run's records are
never wiped. A run spread over xdist workers has one writer: the process the
runner started. Workers stay silent; their results are relayed to it.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from tools.testrun import code_now

_STATE = {"path": None, "run": None, "collected": False}


def pytest_addoption(parser):
    parser.addoption("--progress-file", action="store", default=None, help="the tier run's progress log")


def _write(record: dict) -> None:
    path = _STATE["path"]
    if not path:
        return
    record["run"] = _STATE["run"]
    record.setdefault("time", time.time())
    try:
        with open(path, "a") as fh:
            fh.write(json.dumps(record) + "\n")
            fh.flush()
    except OSError:
        pass  # progress logging never breaks a run


def _previous_run_finished(path: str) -> bool:
    try:
        with open(path) as fh:
            last = None
            for line in fh:
                if line.strip():
                    last = line
    except OSError:
        return True
    if last is None:
        return True
    try:
        return json.loads(last).get("event") == "done"
    except json.JSONDecodeError:
        return False


def pytest_configure(config):
    if hasattr(config, "workerinput"):
        return  # a worker is not a writer
    path = config.getoption("--progress-file")
    if not path:
        return
    _STATE.update(path=path, run=f"{os.getpid()}-{time.time_ns()}", collected=False)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if _previous_run_finished(path):
        open(path, "w").close()
    _write({"event": "start", "pid": os.getpid(), "code": code_now(),
            "asked": [str(a) for a in config.args]})


def _collected(n: int) -> None:
    if not _STATE["collected"]:
        _STATE["collected"] = True
        _write({"event": "collected", "n": n})


def pytest_collection_finish(session):
    if not hasattr(session.config, "workerinput"):
        _collected(len(session.items))


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_node_collection_finished(node, ids):
    # Every worker collects the whole run and xdist refuses workers that
    # disagree, so the first worker's count is the run's.
    _collected(len(ids))


def _nodeid(report) -> str:
    """The ID without xdist's `@group` suffix, which pytest does not accept back (§ 4.6).

    The suffix follows the whole ID; an `@` inside a parameter ID (`test_x[a@b]`)
    is followed by its closing bracket and stays.
    """
    head, at, tail = report.nodeid.rpartition("@")
    return head if at and not any(c in tail for c in "[]:") else report.nodeid


def _reason(report) -> str:
    lines = [ln for ln in (report.longreprtext or "").splitlines() if ln.strip()]
    return lines[-1][:300] if lines else ""


def _outcome_and_reason(report) -> tuple[str, str]:
    if report.outcome == "failed":
        return "failed", _reason(report)
    if report.outcome == "skipped" and hasattr(report, "wasxfail"):
        return "xfailed", str(report.wasxfail)[:300]
    if report.outcome == "skipped":
        longrepr = report.longrepr
        said = longrepr[2] if isinstance(longrepr, tuple) else str(longrepr)
        return "skipped", said.removeprefix("Skipped: ")[:300]
    return report.outcome, ""


def pytest_collectreport(report):
    # a file that fails to import, or skips itself whole: its tests never exist
    if report.failed or report.skipped:
        outcome, reason = _outcome_and_reason(report)
        _write({"event": "collect", "nodeid": _nodeid(report), "outcome": outcome, "reason": reason})


def pytest_runtest_logreport(report):
    # The call of every test; a setup that failed or skipped; a teardown that
    # failed (where the session canaries fire); and a worker crash, which xdist
    # reports under none of the three phases.
    is_call = report.when == "call"
    is_setup_end = report.when == "setup" and report.outcome in ("failed", "skipped")
    is_teardown_failure = report.when == "teardown" and report.outcome == "failed"
    is_crash = report.when not in ("setup", "call", "teardown")
    if not (is_call or is_setup_end or is_teardown_failure or is_crash):
        return
    outcome, reason = _outcome_and_reason(report)
    nodeid = _nodeid(report) + (" [teardown]" if is_teardown_failure else "")
    _write({"event": "test", "nodeid": nodeid, "outcome": outcome,
            "duration": round(getattr(report, "duration", 0.0), 2), "reason": reason})


def pytest_sessionfinish(session, exitstatus):
    if not hasattr(session.config, "workerinput"):
        _write({"event": "done", "exitstatus": int(exitstatus)})
