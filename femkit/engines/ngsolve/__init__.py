"""The NGSolve adapter: its version probe and check programs (definitions.md § 1).

Its check programs write the common summary, so it registers no reader of its own.
"""

from __future__ import annotations

ENGINE = "ngsolve"

#: Run inside the environment; prints the installed NGSolve version.
VERSION_COMMAND = ["python", "-c", "import ngsolve; print(ngsolve.__version__)"]

READERS: dict = {}


def read_version(stdout: str, stderr: str) -> str | None:
    """The version VERSION_COMMAND printed: the last non-empty line of stdout (stderr may carry
    MPI or library warnings)."""
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None
