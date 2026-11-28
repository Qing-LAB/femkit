"""Isolation for every tier (testing.md § 2).

Every test runs with its own directory for each variable core's `dirs.VARIABLES` names.
Session canaries fingerprint the person's real places at the start and the end of the run
(§ 2.2); a difference fails the run in teardown, naming what changed.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import pytest

from femkit.core import dirs, locks
from femkit.core.errors import Refusal
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.definitions.models import JsonQuery
from femkit.envs import manager
from tools.testrun import code_now

REPO = Path(__file__).resolve().parent.parent

# The person's real places, resolved once, before any isolation is set (§ 2.2).
REAL_CONFIG = dirs.config_dir()
REAL_SHALLOW = {"state": dirs.state_dir(), "cache": dirs.cache_dir(), "runtime": dirs.runtime_dir(),
                "locks": locks.root(), "bin": dirs.bin_dir()}


def _asked() -> tuple[list[Path], list[Path]]:
    """What the person's own package manager says, asked once before any isolation (envs.md § 1):
    every environment of femkit's it names so, `femkit` and `femkit-<name>`, by its prefix; and its
    list of environments and its package caches, which it names too (`pkgs_dirs`). Nothing formed
    from where its executable lies. Nothing where no manager is named here, or it does not answer:
    those canaries are then disarmed, and say so."""
    ctx = Context.from_process()
    try:
        m = manager.resolve(ctx)
        names = [catalogue.managed(ctx, n) for n in (dirs.CONTROL, *catalogue.environments(ctx))]
        prefixes = [p for p in (m.prefix(n) for n in names) if p is not None]
        caches, _ = m.query(JsonQuery(argv=["{exe}", "info", "--json"], key="pkgs_dirs"))
    except Refusal as exc:
        warnings.warn(f"environments and manager canaries DISARMED: the person's manager was not asked: {exc}",
                      stacklevel=2)
        return [], []
    return prefixes, [Path.home() / ".conda" / "environments.txt",
                      *(Path(c) for c in (caches if isinstance(caches, list) else []))]


REAL_ENVIRONMENTS, REAL_MANAGER = _asked()


# ------------------------------------------------------------------ isolation

@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Every test's own directories, each one femkit has (§ 2.1)."""
    for name, variable in dirs.VARIABLES.items():
        path = tmp_path / f"femkit-{name}"
        path.mkdir()
        monkeypatch.setenv(variable, str(path))
    yield


@pytest.fixture
def definitions(tmp_path, monkeypatch) -> Path:
    """The shipped definitions copied into the test's own folder, and femkit pointed at the copy
    (`FEMKIT_DEFINITIONS_DIR`, § 2.1): a test edits a definition there, never a function of femkit's,
    and writes only by the path returned here — never by one femkit forms, which would reach the
    shipped files if femkit stopped reading the variable."""
    import shutil
    from femkit.definitions import catalogue
    copy = tmp_path / "definitions"
    shutil.copytree(catalogue.data_root(), copy)
    monkeypatch.setenv(catalogue.VARIABLE, str(copy))
    return copy


# ------------------------------------------------------------------ canaries

def _tree(root: Path):
    if not root.exists():
        return ()
    return tuple(sorted(
        (str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*") if p.is_file()
    ))


def _shallow(root: Path):
    """Every entry within two levels of ``root``, with its modification time: anything added,
    removed or rewritten there — and anything made deeper, which changes its folder's time."""
    if not root.exists():
        return ()
    out = []
    for first in sorted(root.iterdir()):
        out.append((first.name, first.stat().st_mtime_ns))
        if first.is_dir() and not first.is_symlink():
            out += [(f"{first.name}/{p.name}", p.stat().st_mtime_ns) for p in sorted(first.iterdir())]
    return tuple(out)


def _environments():
    out = []
    for prefix in REAL_ENVIRONMENTS:
        for sub in ("conda-meta", ".femkit"):
            d = prefix / sub
            out.append((str(d), len(os.listdir(d)) if d.is_dir() else None,
                        d.stat().st_mtime_ns if d.exists() else None))
    return tuple(out)


def _measure(name: str, read):
    """A canary's fingerprint, or None — with a DISARMED warning — when its side cannot be read."""
    try:
        value = read()
    except OSError as exc:
        value = None
        warnings.warn(f"{name} canary DISARMED: {exc}", stacklevel=2)
    if value is None and name == "checkout":
        warnings.warn("checkout canary DISARMED: git could not list the checkout", stacklevel=2)
    return value


CANARIES = {"config": lambda: _tree(REAL_CONFIG), "environments": _environments,
            "checkout": lambda: code_now(str(REPO)),
            "manager": lambda: tuple((str(p), p.stat().st_mtime_ns if p.exists() else None) for p in REAL_MANAGER),
            **{name: (lambda root=root: _shallow(root)) for name, root in REAL_SHALLOW.items()}}


@pytest.fixture(scope="session", autouse=True)
def the_run_leaves_your_machine_alone():
    """The canaries of § 2.2: config, environments, checkout, the person's own package manager,
    and the real state, cache, runtime and lock folders."""
    before = {name: _measure(name, read) for name, read in CANARIES.items()}
    yield
    after = {name: _measure(name, read) for name, read in CANARIES.items()}
    changed = [name for name in before if before[name] is not None and before[name] != after[name]]
    where = {"config": str(REAL_CONFIG), "environments": ", ".join(map(str, REAL_ENVIRONMENTS)),
             "checkout": str(REPO), "manager": ", ".join(map(str, REAL_MANAGER)), **{name: str(root) for name, root in REAL_SHALLOW.items()}}
    if changed:
        raise AssertionError("canary: the run changed " + "; ".join(f"{n} ({where[n]})" for n in changed))
