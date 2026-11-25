"""What tests share, written once (testing.md § 3): a context for one command, an operation called
through the registry as a surface calls it, a refusal told apart by its code, a lock held by
another process, an environment left as an install leaves it, a machine record, part schemas and
checks of a test's own, a project opened as femkit's start leaves the door, a projects root
stated, a copy of a project template — the Laplace and the two-material one as fixtures — a
folder's files, a file of a test's own changed, and the tripwires the basic and web tiers stand
behind. Each test file takes these from here, never from another test file; a tier's conftest.py
takes the tripwire fixtures it applies."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from pydantic import ConfigDict

from femkit import registry
from femkit.config.probe import GPU_QUERY, place
from femkit.core.errors import Refusal
from femkit.core.operations import Context
from femkit.core.persist import write_json
from femkit.core.schema import Model
from femkit.definitions.catalogue import load_environments, load_managers, load_schedulers
from femkit.envs import layout
from femkit.envs.records import CheckOutcome, ChecksRecord, Manifest
from femkit.envs.state import EnvFacts, facts
from femkit.jobs.record import Record
from femkit.projects import checking, door
from femkit.projects import schemas as part_schemas
from femkit.projects.project import Project


def ctx() -> Context:
    """One command's context, read from the process as the command line reads it."""
    return Context.from_process()


def run(name: str, /, **request):
    """A read-only operation, its request given as JSON values, run as a surface runs it."""
    op = registry.operations()[name]
    return op.run(op.request_from(request), ctx())


def apply(name: str, /, **request):
    """A changing operation planned and applied in one context, as `--yes` applies it."""
    op = registry.operations()[name]
    c = ctx()
    return op.apply(op.plan(op.request_from(request), c), c)


def planned(name: str, /, **request):
    """A changing operation, its plan, and the one context the plan was made in — held, as the
    command line holds them while the person reads the plan; ``op.apply(plan, c)`` applies it."""
    op = registry.operations()[name]
    c = ctx()
    return op, op.plan(op.request_from(request), c), c


HOLDER = """
import sys
from femkit.core import locks, view
with locks.subject_lock(sys.argv[1], shared=sys.argv[2] == "shared"):
    locks.adopt(locks.held_fd(sys.argv[1]), "a user of " + sys.argv[1], [view.shell("end it").model_dump(mode="json")])
    print("held", flush=True)
    sys.stdin.read()
"""


@contextmanager
def refused(kind: type[Refusal], code: str, subject: str | None = None):
    """The block refused with ``kind`` and ``code`` — and, given one, about ``subject``: a refusal
    told apart by its code, never its wording (core.md § 9)."""
    with pytest.raises(kind) as caught:
        yield caught
    assert caught.value.code == code, (caught.value.code, str(caught.value))
    assert subject is None or caught.value.subject == subject, (caught.value.subject, str(caught.value))


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


class StandIn(Model):
    """A part schema of a test's own, for a kind no package of femkit's declares: it takes any key,
    as written."""

    model_config = ConfigDict(extra="allow", frozen=True)


@contextmanager
def own_parts(schemas: dict[str, type[Model]] | None = None, checks: dict[str, checking.Check] | None = None):
    """Part schemas and checks of a test's own, each by its key, registered with the door and the
    check frame as the registry registers a package's at femkit's start (api.md § 6) — a check
    beside those registered for its key — and taken back after, those held before kept."""
    held = part_schemas.registered(), checking.registered()
    for key, model in (schemas or {}).items():
        part_schemas.register(key, model)
    for key, check in (checks or {}).items():
        checking.register(key, check)
    try:
        yield
    finally:
        for key in schemas or {}:
            part_schemas.unregister(key)
            if key in held[0]:
                part_schemas.register(key, held[0][key])
        for key in checks or {}:
            checking.unregister(key)
            for check in held[1].get(key, ()):
                checking.register(key, check)


def opened(folder: Path) -> door.Opened:
    """The project at ``folder`` — a template in place, or a test's own — opened through the one
    door as an operation opens it after femkit's start: every part schema and check registered
    (api.md § 6)."""
    registry.operations()
    return door.open_project(Project(folder.parent, folder.name), ctx())


def set_root(folder: Path) -> None:
    """``folder`` stated as the projects root, `paths.projects`, as `config set` states it (projects.md § 1)."""
    apply("config.set", key="paths.projects", value=f'"{folder}"')


def copy_template(root: Path, template: str, name: str | None = None) -> Path:
    """A copy of one of femkit's project templates, made by `project new` under ``root``, the
    projects root this states: what a test that needs a project starts from (projects.md § 7)."""
    set_root(root)
    apply("project.new", name=name or template, source=template)
    return root / (name or template)


@pytest.fixture
def laplace(tmp_path) -> Path:
    """A copy of the Laplace template, `laplace_square`, under a projects root of the test's own."""
    return copy_template(tmp_path / "projects", "laplace_square")


@pytest.fixture
def slab(tmp_path) -> Path:
    """A copy of the two-material template, as the project `slab`, under a projects root of the test's own."""
    return copy_template(tmp_path / "projects", "two_material", "slab")


def tree(folder: Path) -> dict[str, bytes]:
    """Every file of a folder, by its path from it, with its bytes."""
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def rewrite(path: Path, old: str, new: str) -> None:
    """A file of a test's own — of its project, or its copy of the definitions — changed as its
    person would change it: ``old`` there, once, made ``new``."""
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} is in {path} {text.count(old)} times"
    path.write_text(text.replace(old, new), encoding="utf-8")


# ------------------------------------------------------------------ the tripwires (testing.md § 2.1)
#
# PATH starts with a directory holding a tripwire for every outside program femkit can start; a
# test that reaches one fails, naming the call.

# Programs the tests' own process needs; never tripwired.
NEEDED_BY_THE_TEST_PROCESS = frozenset({"python", "bash", "git"})
# Named by testing.md § 2.1 or started by code, but listed in no definition file:
# the GPU query, and CTest (the `ctest` check kind, definitions.md § 5.1).
NAMED_IN_CODE = frozenset({GPU_QUERY[0], "ctest"})


def tripwire_names() -> frozenset[str]:
    names = set(load_managers()) | NAMED_IN_CODE
    for kind in load_schedulers().values():
        names |= set(kind.commands.values()) | set(kind.probe.values()) | {kind.mpi_launch[0]}
    for env in load_environments().values():
        names |= set(env.provides.executables) | set(env.toolchain.mpi.values() if env.toolchain else ())
    return frozenset(names - NEEDED_BY_THE_TEST_PROCESS)


#: The machine the basic and web tiers stand on (testing.md § 2.1): the tripwires put every scheduler
#: kind's commands on PATH and clear its job variables, so femkit finds SLURM's submit command and no
#: job. A test that needs another place says so in its own environment, for its own run.
MACHINE = "login node"

REACHED = "reached.log"  # in the tripwire directory: every call a tripwire took during the current test


def tripwire_text(log: Path) -> str:
    """A tripwire's text. The log's path is written into it, not passed in a variable: a command
    run in a prefix sees only the confined variables (envs.md § 4.4)."""
    return f'#!/bin/sh\necho "$0 $*" >> {shlex.quote(str(log))}\nexit 97\n'


@pytest.fixture(scope="session")
def tripwire_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("tripwires")
    for name in tripwire_names():
        script = d / name
        script.write_text(tripwire_text(d / REACHED))
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return d


@pytest.fixture(autouse=True)
def tripwires(tripwire_dir, monkeypatch):
    log = tripwire_dir / REACHED
    log.unlink(missing_ok=True)
    for kind in load_schedulers().values():  # run inside an allocation, a test still sees none of its job
        for variable in kind.job_variables.values():
            monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("PATH", f"{tripwire_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FEMKIT_ENV_MANAGER", str(tripwire_dir / sorted(load_managers())[0]))
    stood_on = place(load_schedulers(), os.environ).where
    assert stood_on == MACHINE, f"the tests stand on a {stood_on}, not the stated {MACHINE} (testing.md § 2.1)"
    yield log
    if log.exists() and log.read_text().strip():
        pytest.fail("a test reached an outside program: " + log.read_text().strip())
