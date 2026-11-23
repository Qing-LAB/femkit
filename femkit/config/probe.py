"""Measurements of this machine: what `config init` proposes from (config.md § 3.2), which
scheduler kind it is, and where this process runs on it (jobs.md § 9.1; envs.md § 6.2).

The machine probe itself is `femkit/jobs/probe.py` (jobs.md § 9); it uses these too.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from femkit.core import process
from femkit.definitions.models import SchedulerKind

GPU_QUERY = ("nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader")


def gpu_architectures() -> tuple[list[str] | None, str]:
    """The CUDA architectures of this machine's GPUs, or None and why not."""
    if shutil.which(GPU_QUERY[0]) is None:
        return None, f"{GPU_QUERY[0]} not found"
    result = process.run(GPU_QUERY, timeout=30)
    if not result.ok:
        return None, f"{GPU_QUERY[0]} failed: {(result.stderr or result.stdout).strip()[:200]}"
    caps = sorted({line.strip().replace(".", "") for line in result.stdout.splitlines() if line.strip()})
    if not caps or not all(c.isdigit() for c in caps):
        return None, f"{GPU_QUERY[0]} gave no compute capability"
    return caps, GPU_QUERY[0]


def detect_scheduler(kinds: dict[str, SchedulerKind]) -> tuple[str | None, str]:
    """The kind whose submit command is found (jobs.md § 9.2); a kind without commands
    when none is. A login node may lack the kind's other commands; they are located apart."""
    found = [name for name, kind in kinds.items()
             if kind.commands and shutil.which(kind.commands["submit"])]
    if len(found) > 1:
        return None, f"more than one scheduler kind found: {', '.join(found)}"
    if found:
        return found[0], f"{kinds[found[0]].commands['submit']} is on PATH"
    plain = [name for name, kind in kinds.items() if not kind.commands]
    if len(plain) != 1:
        return None, f"{len(plain)} kinds have no commands; cannot tell which applies"  # never one: 0 or 2+
    return plain[0], "no scheduler's commands are on PATH"


Where = Literal["workstation", "login node", "scheduler job"]  # where this process runs (jobs.md § 9.1)


def where(kind: SchedulerKind, env: Mapping[str, str]) -> Where:
    """Where this process runs on a machine of ``kind``: inside one of its jobs (its job-ID
    variable is set in ``env``); on one of its machines outside any job — most likely a login
    node; or, for a kind without commands, a workstation."""
    job_id = kind.job_variables.get("id")
    if job_id and env.get(job_id):
        return "scheduler job"
    return "login node" if kind.commands else "workstation"


@dataclass(frozen=True)
class Place:
    """Where this process runs, with the scheduler kind detected here (envs.md § 6.2)."""

    where: Where
    scheduler: str | None = None
    kind: SchedulerKind | None = None


def place(kinds: dict[str, SchedulerKind], env: Mapping[str, str]) -> Place:
    """Where this process runs on the detected kind; where no kind can be told apart, a workstation."""
    name, _ = detect_scheduler(kinds)
    return Place(where(kinds[name], env), name, kinds[name]) if name else Place("workstation")
