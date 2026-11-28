"""The Elmer adapter: its log reader, the reader of its version command's irregular output, check
programs and the hand-over of a mesh (`handover.py`, geometry.md § 8; definitions.md § 1)."""

from __future__ import annotations

from femkit.engines.elmer.readers import VERSION, solver_log

ENGINE = "elmer"

READERS = {"elmer-solver-log": solver_log}


def read_version(stdout: str, stderr: str) -> str | None:
    """`major.minor` from the `Version: 26.2-…` line that `ElmerSolver -v`, the environment's
    version command, prints on either stream: no last line it prints is the version."""
    found = VERSION.search(stdout) or VERSION.search(stderr)
    return found.group(1) if found else None
