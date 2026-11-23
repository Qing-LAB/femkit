"""Append-only operation event logs and their fold (core.md § 6)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from femkit.core.schema import Model

KINDS = ("operation-start", "step-start", "step-end", "operation-end")


class EventLog:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, kind: str, **fields) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown event kind {kind!r}")
        record = {"kind": kind, "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.endswith("\n"):
                    break  # a torn last line: the writer died mid-write
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    break
        return out


class LogState(Model):
    started: bool
    ended: bool
    outcome: str | None
    finished_steps: tuple[str, ...]
    failed_step: str | None
    interrupted: bool


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def fold(events: list[dict]) -> LogState:
    start = next((e for e in events if e["kind"] == "operation-start"), None)
    end = next((e for e in reversed(events) if e["kind"] == "operation-end"), None)
    finished, failed = [], None
    for e in events:
        if e["kind"] == "step-end":
            if e.get("outcome") == "done":
                finished.append(e["step"])
            else:
                failed = e["step"]
    return LogState(
        started=start is not None,
        ended=end is not None,
        outcome=end.get("outcome") if end else None,
        finished_steps=tuple(finished),
        failed_step=failed,
        interrupted=start is not None and end is None and not _alive(start.get("pid")),
    )
