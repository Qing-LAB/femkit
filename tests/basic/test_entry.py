"""scripts/install-env.sh and its control state table (envs.md § 7).

The `manager` fixture (tests/basic/conftest.py) is a stand-in that records each
call; the real managers run the same forms in the field tier.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from femkit.core import dirs
from femkit.core.errors import UsageError
from femkit.core.schema import render
from femkit.core.operations import Context
from femkit.definitions.catalogue import control_files, load_control, load_managers
from femkit.envs.manager import resolve

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "install-env.sh"


def install_env(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)


def calls(log: Path) -> list[list[str]]:
    return [line.split() for line in log.read_text().splitlines()] if log.exists() else []


def declared(*names: str) -> list[list[str]]:
    """The conda kind's commands for the control environment, without the executable: `create`
    assembled as femkit assembles every create — the declared channels, then control.txt."""
    kind = load_managers()["conda"]
    out = []
    for name in names:
        if name == "create":
            m = resolve(Context.from_process())
            out.append(m.create(dirs.control_prefix(), load_control().channels, ["--file", str(control_files()[1])])[1:])
        else:
            out.append([render(a, {"exe": "", "prefix": str(dirs.control_prefix())}) for a in getattr(kind, name)[1:]])
    return out


def forwarded(call: list[str]) -> list[str]:
    """The femkit arguments of the control environment's `python -m femkit env ...` (only
    the stand-in control's python writes a `python` line)."""
    assert call[:4] == ["python", "-m", "femkit", "env"]
    return call[4:]


def make_outdated(prefix: Path) -> None:
    (prefix / "conda-meta").mkdir(parents=True)
    (prefix / "bin").mkdir()
    (prefix / "bin" / "python").write_text("#!/bin/sh\n")
    (prefix / "bin" / "python").chmod(0o755)
    (prefix / ".femkit").mkdir()
    (prefix / ".femkit" / "control.sha256").write_text("not the hash of channels.txt and control.txt\n")


def test_bootstrap_creates_control_where_femkit_looks_and_forwards_to_python(manager):
    """Fails if the script and core/dirs.py disagree on the control prefix, the script's
    create differs from the conda kind's, the stamp is not written, or a verb is not
    forwarded to `python -m femkit env` (envs.md § 1, § 7)."""
    assert install_env("bootstrap", "--yes").returncode == 0
    assert calls(manager)[0] == declared("create")[0]
    assert forwarded(calls(manager)[1]) == ["bootstrap", "--yes"]
    assert install_env("install", "ngsolve", "--yes").returncode == 0  # the stamp made it current
    assert forwarded(calls(manager)[-1]) == ["install", "ngsolve", "--yes"]


@pytest.mark.parametrize("state", ["absent", "broken", "outdated"])
def test_a_verb_is_refused_until_control_is_current(manager, state):
    """Fails if a verb is forwarded while the control environment is absent, broken or
    outdated (envs.md § 7.3)."""
    prefix = dirs.control_prefix()
    if state == "broken":
        (prefix / "conda-meta").mkdir(parents=True)
    if state == "outdated":
        make_outdated(prefix)
    assert install_env("list", "--yes").returncode == 2
    assert calls(manager) == []


def test_plain_bootstrap_rebuilds_an_outdated_or_broken_control(manager):
    """Fails if a changed control.txt or a broken control environment is not rebuilt by
    plain `bootstrap`: the repair must never need --clean, which also rebuilds every engine
    environment (envs.md § 7.3)."""
    make_outdated(dirs.control_prefix())
    assert install_env("bootstrap", "--yes").returncode == 0
    assert calls(manager)[:2] == declared("remove", "create")

    manager.unlink()
    (dirs.control_prefix() / ".femkit" / "control.sha256").unlink()  # broken: no stamp
    assert install_env("bootstrap", "--yes").returncode == 0
    assert calls(manager)[:2] == declared("remove", "create")
    assert forwarded(calls(manager)[2]) == ["bootstrap", "--yes"]


def test_nothing_is_created_without_consent_or_on_a_dry_run(manager):
    """Fails if the script creates without a terminal and without --yes, or creates the
    control environment to answer --dry-run (envs.md § 7.3)."""
    assert install_env("bootstrap").returncode == 2
    assert install_env("bootstrap", "--dry-run").returncode == 2
    assert calls(manager) == [] and not dirs.control_prefix().exists()


@pytest.mark.parametrize("how", ["xdg", "tilde"])
def test_the_script_and_femkit_resolve_the_data_directory_alike(manager, monkeypatch, tmp_path, how):
    """Fails if the script and core/dirs.py put the control environment in different places
    when the data directory comes from XDG_DATA_HOME or holds `~` (config.md § 2)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    if how == "xdg":
        monkeypatch.delenv("FEMKIT_DATA_DIR")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    else:
        monkeypatch.setenv("FEMKIT_DATA_DIR", "~/femkit-data")
    assert install_env("bootstrap", "--yes").returncode == 0
    assert calls(manager)[0] == declared("create")[0]


def test_a_relative_data_directory_is_refused_by_both(manager, monkeypatch):
    """Fails if either the script or femkit takes the data directory from where the
    command runs (config.md § 2)."""
    monkeypatch.setenv("FEMKIT_DATA_DIR", "relative/data")
    assert install_env("bootstrap", "--yes").returncode == 2 and calls(manager) == []
    with pytest.raises(UsageError):
        dirs.control_prefix()


def make_current(manager: Path) -> None:
    assert install_env("bootstrap", "--yes").returncode == 0
    manager.unlink()


def test_on_a_current_control_bootstrap_only_forwards_and_looking_never_rebuilds(manager):
    """Fails if bootstrap rebuilds a current control environment unasked, or
    `bootstrap --clean --dry-run` removes anything instead of only forwarding the look
    (envs.md § 7.3)."""
    make_current(manager)
    assert install_env("bootstrap", "--yes").returncode == 0
    assert [forwarded(c) for c in calls(manager)] == [["bootstrap", "--yes"]]
    manager.unlink()
    assert install_env("bootstrap", "--clean", "--dry-run").returncode == 0
    assert [forwarded(c) for c in calls(manager)] == [["bootstrap", "--clean", "--dry-run"]]


def test_a_verb_that_changes_nothing_needs_no_confirmation(manager):
    """Fails if a read-only verb is refused for want of a terminal to confirm the manager on,
    while a verb that installs still asks (envs.md § 7.3)."""
    make_current(manager)
    assert install_env("list").returncode == 0
    assert [forwarded(c) for c in calls(manager)] == [["list"]]
    assert install_env("install", "ngsolve").returncode == 2
    assert len(calls(manager)) == 1


def test_a_manager_femkit_has_no_kind_file_for_is_refused_before_it_runs(manager, monkeypatch):
    """Fails if the script drives a manager Python has no kind file for (envs.md § 7.1):
    it would build control with one manager's syntax and Python would then refuse it."""
    other = manager.parent / "no-kind" / "mamba"
    other.parent.mkdir()
    other.write_text((manager.parent / "stand-in" / "conda").read_text())  # the same stand-in, renamed
    other.chmod(0o755)
    monkeypatch.setenv("FEMKIT_ENV_MANAGER", str(other))
    assert install_env("bootstrap", "--yes").returncode == 2
    assert calls(manager) == [] and not dirs.control_prefix().exists()


def test_the_manager_on_path_wins_over_a_leftover_conda_exe(manager, monkeypatch, tmp_path):
    """Fails if MAMBA_EXE/CONDA_EXE are looked at before PATH (envs.md § 7.1): a variable
    left by an old `conda init` would beat the manager loaded in this shell."""
    stale = tmp_path / "old-install" / "conda"
    stale.parent.mkdir()
    marker = tmp_path / "stale-was-used"
    stale.write_text(f"#!/bin/sh\ntouch {marker}\nexit 97\n")
    stale.chmod(0o755)
    on_path = manager.parent / "stand-in"
    monkeypatch.delenv("FEMKIT_ENV_MANAGER")
    monkeypatch.setenv("CONDA_EXE", str(stale))
    monkeypatch.setenv("PATH", f"{on_path}:/usr/bin:/bin")
    assert install_env("bootstrap", "--yes").returncode == 0
    assert not marker.exists() and calls(manager)[0] == declared("create")[0]


def test_help_before_control_exists_is_the_scripts_own_and_creates_nothing(manager):
    """Fails if `bootstrap --help` on a fresh machine refuses, or creates control to
    answer (envs.md § 7.3)."""
    assert install_env("bootstrap", "--help").returncode == 0
    assert calls(manager) == [] and not dirs.control_prefix().exists()
