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
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.definitions.models import SchedulerKind

GPU_QUERY = ("nvidia-smi", "--query-gpu=name,compute_cap,memory.total", "--format=csv,noheader,nounits")


def gpus() -> tuple[list[dict] | None, str]:
    """This machine's GPUs as the driver lists them — each one's model, compute capability and
    memory in MiB — or None and why not. The one GPU query: `config init`'s proposal and the
    machine record both read it."""
    if shutil.which(GPU_QUERY[0]) is None:
        return None, f"{GPU_QUERY[0]} not found on PATH"
    result = process.run(GPU_QUERY, timeout=30)
    if not result.ok:
        said = (result.stderr or result.stdout).strip().splitlines()
        return None, f"{GPU_QUERY[0]} failed" + (f": {said[0][:200]}" if said else "")
    found = []
    for line in filter(str.strip, result.stdout.splitlines()):
        parts = [p.strip() for p in line.rsplit(",", 2)]     # a model's name may hold a comma; the numbers do not
        if len(parts) != 3 or not parts[1].replace(".", "", 1).isdigit() or not parts[2].isdigit():
            return None, f"{GPU_QUERY[0]} printed a line that does not read: {line.strip()[:200]}"
        found.append({"model": parts[0], "compute_capability": parts[1], "memory_mib": int(parts[2])})
    return found, GPU_QUERY[0]


def gpu_architectures() -> tuple[list[str] | None, str]:
    """The CUDA architectures of this machine's GPUs, or None and why not."""
    found, why = gpus()
    if found is None:
        return None, why
    if not found:
        return None, f"{GPU_QUERY[0]} lists no GPU"
    return sorted({g["compute_capability"].replace(".", "") for g in found}), why


def detect_scheduler(kinds: dict[str, SchedulerKind], submit_declared: bool = False) -> tuple[str | None, str]:
    """The kind whose submit command is found, or declared (jobs.md § 9.2) — a declared one
    stands for every kind with commands; a kind without commands when none is. A login node may
    lack the kind's other commands; they are located apart."""
    found = [name for name, kind in kinds.items()
             if kind.commands and (submit_declared or shutil.which(kind.commands["submit"]))]
    if len(found) > 1:
        return None, f"more than one scheduler kind found: {', '.join(found)}"
    if found:
        return found[0], ("its submit command is declared" if submit_declared
                          else f"{kinds[found[0]].commands['submit']} is on PATH")
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


# ------------------------------------------------------------------ what config init proposes

def _gpu_architectures(ctx: Context) -> tuple[list[str] | None, str]:
    archs, source = gpu_architectures()
    return archs, f"measured by {source}"


def _scheduler_launcher(ctx: Context) -> tuple[list[str] | None, str]:
    kinds = catalogue.schedulers(ctx)
    kind, why = detect_scheduler(kinds)
    return (kinds[kind].mpi_launch, f"the {kind} scheduler kind's launcher ({why})") if kind else (None, why)


#: What `config init` proposes a key from, by the name the key's field gives it (`propose`,
#: config.md § 3.1): the value, or None and why not, and where it came from.
PROPOSALS = {"gpu-architectures": _gpu_architectures, "scheduler-launcher": _scheduler_launcher}
