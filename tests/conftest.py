"""Isolation for every tier (testing.md § 2).

Every test runs with its own FEMKIT_CONFIG_DIR, FEMKIT_DATA_DIR,
FEMKIT_CACHE_DIR and FEMKIT_STATE_DIR. Three session canaries fingerprint the person's real
configuration, environments and checkout at the start and the end of the run;
a difference fails the run in teardown, naming what changed.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import pytest

from femkit.config import settings
from femkit.core import dirs
from femkit.core.errors import Refusal
from femkit.core.operations import Context
from femkit.definitions.catalogue import load_environments
from tools.testrun import code_now

REPO = Path(__file__).resolve().parent.parent

# The person's real places, resolved once, before any isolation is set (§ 2.2).
REAL_CONFIG = dirs.config_dir()
REAL_CONTROL = dirs.control_prefix()


def _real_engine_root() -> Path:
    """Where femkit itself would put engine environments for this person (config.md § 3)."""
    try:
        return settings.environments_root(settings.load(Context.from_process(), fresh=True).config)
    except Refusal as exc:
        warnings.warn(f"environments canary partly DISARMED: {exc}", stacklevel=1)
        return dirs.environments_dir()


REAL_ENVIRONMENTS = [REAL_CONTROL] + [_real_engine_root() / name for name in load_environments()]


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
    (`FEMKIT_DEFINITIONS_DIR`, § 2.1): a test edits a definition there, never a function of femkit's."""
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
            "checkout": lambda: code_now(str(REPO))}


@pytest.fixture(scope="session", autouse=True)
def the_run_leaves_your_machine_alone():
    """The config, environments and checkout canaries (§ 2.2)."""
    before = {name: _measure(name, read) for name, read in CANARIES.items()}
    yield
    after = {name: _measure(name, read) for name, read in CANARIES.items()}
    changed = [name for name in before if before[name] is not None and before[name] != after[name]]
    where = {"config": str(REAL_CONFIG), "environments": ", ".join(map(str, REAL_ENVIRONMENTS)),
             "checkout": str(REPO)}
    if changed:
        raise AssertionError("canary: the run changed " + "; ".join(f"{n} ({where[n]})" for n in changed))


# ------------------------------------------------------------------ next steps

@pytest.fixture(scope="session", autouse=True)
def every_next_step_names_its_operation():
    """Every next step the run builds names a registered operation, with that operation's own
    request model (web.md § 7.2): a renamed verb, or a request model taken for another's, fails
    here, wherever the step was made. Steps of operations a test declares itself are its own."""
    from femkit import registry
    from femkit.core import view
    made: dict[view.Verb, None] = {}
    real = view.command

    def recording(verb, **kw):
        made[verb] = None
        return real(verb, **kw)

    patch = pytest.MonkeyPatch()
    patch.setattr(view, "command", recording)
    yield
    patch.undo()
    ops = registry.operations()
    wrong = sorted(f"{v.name} with {v.request.__name__}" for v in made
                   if v.request.__module__.startswith("femkit.") and (v.name not in ops or ops[v.name].request is not v.request))
    assert not wrong, f"next steps naming no operation, or another's request: {wrong}"
