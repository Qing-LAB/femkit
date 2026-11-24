"""How femkit writes a moment (core.md § 1): UTC, ISO 8601, to the second — in every record,
event log and server log line. Standard library only: the supervisor writes moments too."""

from __future__ import annotations

from datetime import datetime, timezone


def now() -> datetime:
    """This moment, in UTC."""
    return datetime.now(timezone.utc)


def stamp(moment: datetime | None = None) -> str:
    """``moment`` — now, when none is given — as femkit writes it: `2026-11-24T09:30:00+00:00`."""
    return (moment or now()).astimezone(timezone.utc).isoformat(timespec="seconds")
