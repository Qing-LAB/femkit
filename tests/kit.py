"""What tests share, written once (testing.md § 3): a context for one command, an operation called
through the registry as a surface calls it, a lock held by another process, an environment left as
an install leaves it, and a machine record. Each test file takes these from here, never from
another test file."""

from __future__ import annotations

import subprocess
import sys

from femkit import registry
from femkit.core.operations import Context
from femkit.core.persist import write_json
from femkit.envs import layout
from femkit.envs.records import CheckOutcome, ChecksRecord, Manifest
from femkit.envs.state import EnvFacts, facts
from femkit.jobs.record import Record


def ctx() -> Context:
    """One command's context, read from the process as the command line reads it."""
    return Context.from_process()


def run(name: str, **request):
    """A read-only operation, its request given as JSON values, run as a surface runs it."""
    op = registry.operations()[name]
    return op.run(op.request_from(request), ctx())


def apply(name: str, **request):
    """A changing operation planned and applied in one context, as `--yes` applies it."""
    op = registry.operations()[name]
    c = ctx()
    return op.apply(op.plan(op.request_from(request), c), c)


HOLDER = """
import sys
from femkit.core import locks, view
with locks.subject_lock(sys.argv[1], shared=sys.argv[2] == "shared"):
    locks.adopt(locks.held_fd(sys.argv[1]), "a user of " + sys.argv[1], [view.shell("end it").model_dump(mode="json")])
    print("held", flush=True)
    sys.stdin.read()
"""


def hold(subject: str, mode: str) -> subprocess.Popen:
    """Another process holding ``subject``'s lock, ``mode`` shared or alone, until its stdin closes."""
    p = subprocess.Popen([sys.executable, "-c", HOLDER, subject, mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True)
    assert p.stdout.readline().strip() == "held"
    return p


def installed(name: str, *, fingerprint: str | None = None, outcomes: list[CheckOutcome] | None = None,
              stale_checks: bool = False) -> EnvFacts:
    """The environment ``name`` left as an install leaves it — and, given ``outcomes``, as a
    validate then leaves it — in the test's own data directory (envs.md § 4.3)."""
    f = facts(ctx(), name)
    (f.prefix / "conda-meta").mkdir(parents=True)
    write_json(layout.manifest_file(f.prefix), Manifest(
        install_fingerprint=fingerprint or f.install_fingerprint, lock_sha256="0" * 64, manager_kind="conda",
        manager_version="0", solver_version="0", time="t").model_dump())
    if outcomes is not None:
        write_json(layout.checks_file(f.prefix), ChecksRecord(
            check_fingerprint="stale" if stale_checks else f.check_fingerprint, outcomes=outcomes, time="t").model_dump())
    return f


def a_record(**changes) -> Record:
    """A cluster's record with every kind of value: numbers, `unlimited`, unknowns, walls."""
    data = {
        "schema": 1,
        "measured": {"time": "2026-01-01T00:00:00Z", "where": "login node"},
        "identity": "cluster-a",
        "host": {"os": "Linux 5", "architecture": "x86_64", "cores": 8, "memory_mib": 16000,
                 "gpus": {"unknown": "nvidia-smi not found on PATH"}},
        "manager": {"kind": "conda", "path": "/opt/conda/bin/conda", "version": "25.1", "root": "/opt/conda",
                    "platform": "linux-64", "run_enters": False},
        "scheduler": {"kind": "slurm", "commands": {"submit": "/usr/bin/sbatch", "query": {"unknown": "squeue not found"}},
                      "probe": {"control": "/usr/bin/scontrol"}},
        "partitions": {"p1": {"max_time": "7-00:00:00", "max_cpus_per_node": "unlimited", "def_mem_per_cpu_mib": 2048,
                              "allow_qos": "all", "deny_qos": [],
                              "node_groups": [{"count": 3, "cores": 48, "memory_mib": 515000, "gpus": {"t1": 4},
                                               "architecture": "x86_64"}]}},
        "queues": [{"partition": "p1", "qos": "q1", "max_time": "1-00:00:00", "max_cpus": 128,
                    "max_memory_mib": "unlimited", "max_gpus": {"unknown": "capped per GPU type: gres/gpu:t1=2"},
                    "max_submit_jobs_per_user": "unlimited"}],
        "environments": {"ngsolve": {"state": "ready", "gpu": "not-run", "install_fingerprint": "abc"}},
        "settings": {"environments": "/scratch/envs", "preamble": ["module load x"]},
        "sources": {"partitions": "scontrol show partition, scontrol show node"},
        "notes": [],
    }
    data.update(changes)
    return Record.model_validate(data)
