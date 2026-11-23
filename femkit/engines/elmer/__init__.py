"""The Elmer adapter: its version probe, its log reader and check programs (definitions.md § 1)."""

from __future__ import annotations

from femkit.engines.elmer.readers import VERSION, solver_log

ENGINE = "elmer"

#: Run inside the environment; ElmerSolver states its version and stops.
VERSION_COMMAND = ["ElmerSolver", "-v"]

READERS = {"elmer-solver-log": solver_log}


def read_version(stdout: str, stderr: str) -> str | None:
    """`major.minor` from ElmerSolver's `Version: 26.2-…` line, on either stream."""
    found = VERSION.search(stdout) or VERSION.search(stderr)
    return found.group(1) if found else None
