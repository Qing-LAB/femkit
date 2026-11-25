"""Append-only operation event logs and their fold (core.md § 6)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, get_args

from femkit.core import clock, persist
from femkit.core.process import Identity
from pydantic import Field

from femkit.core.schema import Model

FILE = "events.jsonl"   # in its operation's folder; nothing else names it
KINDS = ("operation-start", "step-start", "step-log", "step-end", "operation-end")
#: How a step ends: it did what it says, it failed, or the system killed it — a signal, the memory limit.
StepOutcome = Literal["done", "failed", "killed"]
OUTCOMES: tuple[str, ...] = get_args(StepOutcome)


class EventLog:
    def __init__(self, path: Path, now: Callable[[], datetime] = clock.now):
        self.path = Path(path)
        self._now = now

    @classmethod
    def of(cls, folder: Path, now: Callable[[], datetime] = clock.now) -> "EventLog":
        """The event log of the operation in ``folder``, its moments read from ``now``."""
        return cls(Path(folder) / FILE, now)

    def append(self, kind: str, **fields) -> None:
        """One record, one JSON line, by the one appender: flushed and fsynced (core.md §§ 4, 6)."""
        if kind not in KINDS:
            raise ValueError(f"unknown event kind {kind!r}")
        record = {"kind": kind, "time": clock.stamp(self._now()), **fields}
        persist.append_text(self.path, json.dumps(record, sort_keys=True, default=str) + "\n")

    def events(self) -> list[dict]:
        """Every complete record, in order; a torn last line — its writer died mid-write — ends them."""
        held = persist.read_bytes(self.path) or b""
        *lines, _torn = held.decode("utf-8", errors="replace").split("\n")   # after the last newline: torn, or nothing
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                break
        return out


class StepState(Model):
    """One step of an operation, as its event log tells it."""

    id: str = Field(description="the step's ID")
    outcome: StepOutcome | Literal["running"] = Field(description="how it ended; running: started, never ended")
    log: str | None = Field(default=None, description="its log file")


class LogState(Model):
    operation: str | None = None   # the operation that wrote the log, as its start names it
    basis: dict = {}               # the facts its plan rested on, as its start records them
    started: bool
    ended: bool
    outcome: Literal["done", "failed"] | None
    steps: tuple[StepState, ...]
    finished_steps: tuple[str, ...]
    failed_step: str | None
    interrupted: bool


def _runs(start: dict) -> bool:
    """Whether the process that started the operation runs now, by its identity (core.md § 8)."""
    try:
        return Identity.from_json(start["process"]).alive()
    except (KeyError, TypeError, ValueError):
        return False   # none recorded: none to find running


def fold(events: list[dict]) -> LogState:
    start = next((e for e in events if e["kind"] == "operation-start"), None)
    end = next((e for e in reversed(events) if e["kind"] == "operation-end"), None)
    steps: dict[str, StepState] = {}
    failed = None
    for e in events:
        if e["kind"] == "step-start":
            steps[e["step"]] = StepState(id=e["step"], outcome="running")
        elif e["kind"] == "step-log" and e["step"] in steps:
            steps[e["step"]] = steps[e["step"]].model_copy(update={"log": e.get("log")})
        elif e["kind"] == "step-end":
            held = steps.get(e["step"], StepState(id=e["step"], outcome="running"))
            steps[e["step"]] = held.model_copy(update={"outcome": e.get("outcome"), "log": e.get("log") or held.log})
            if e.get("outcome") != "done":
                failed = e["step"]
    return LogState(
        operation=start.get("operation") if start else None,
        basis=(start.get("basis") or {}) if start else {},
        started=start is not None,
        ended=end is not None,
        outcome=end.get("outcome") if end else None,
        steps=tuple(steps.values()),
        finished_steps=tuple(s.id for s in steps.values() if s.outcome == "done"),
        failed_step=failed,
        interrupted=start is not None and end is None and not _runs(start),
    )
