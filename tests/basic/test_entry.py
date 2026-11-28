"""scripts/install-env.sh, the control environment's states, and the `femkit` command the
script writes into it and links from `<bin>` (envs.md § 7).

The `manager` fixture (tests/basic/conftest.py) is a stand-in that records each call and keeps
its environments where a manager does, the control environment `femkit` among them; the real
managers run the same forms in the field tier.
"""

from __future__ import annotations

import itertools
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from femkit.core import dirs, text
from femkit.core.errors import UsageError
from tests import kit
from tests.kit import hold, laplace, refused, run  # noqa: F401 -- laplace: a fixture
from femkit.core.schema import render
from femkit.definitions.catalogue import control_digest, control_files, load_control, load_managers, load_states
from femkit.envs import control as control_env
from femkit.envs.manager import Manager

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "install-env.sh"


def install_env(*args: str, script: Path = SCRIPT) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)


#: How each query of the manager opens: where its environments are, where it keeps them, which of the
#: person's settings it read (envs.md §§ 1, 4.4).
QUERIES = ("env list", "info --json", "config --show-sources")


def calls(log: Path) -> list[list[str]]:
    """Each call that changed or ran something, in order: the manager's queries left out."""
    return [line.split() for line in log.read_text().splitlines() if not line.startswith(QUERIES)] \
        if log.exists() else []


def control() -> Path:
    """Where the stand-in manager keeps the control environment, `femkit` (envs.md § 1)."""
    return kit.manager_root() / "envs" / "femkit"


def link() -> Path:
    """The link that puts `femkit` on a shell's path: `<bin>/femkit` (envs.md § 7)."""
    return dirs.bin_dir() / "femkit"


def declared(*names: str) -> list[list[str]]:
    """The conda kind's commands for the control environment, by its name `femkit`, without the
    executable: `create` assembled as femkit assembles every create — the declared channels, then
    control.txt."""
    kind = load_managers()["conda"]
    m = Manager(Path("/the/conda"), "conda", kind, {})
    out = []
    for name in names:
        if name == "create":
            out.append(m.create("femkit", load_control().channels, ["--file", str(control_files()[1])])[1:])
        elif name == "remove":  # as femkit assembles every removal: with the channels, where the kind names them
            out.append(m.remove("femkit", load_control().channels)[1:])
        else:
            out.append([render(a, {"exe": "", "name": "femkit"}) for a in getattr(kind, name)[1:]])
    return out


def forwarded(call: list[str]) -> list[str]:
    """The femkit arguments of the control environment's `python -I <checkout>/femkit/__main__.py
    env ...` (only the stand-in control's python writes a `python` line) — the `femkit` command's
    own form, isolated, so the folder the script runs in is never on Python's import path
    (envs.md §§ 7, 7.3)."""
    assert call[:4] == ["python", "-I", str(REPO / "femkit" / "__main__.py"), "env"]
    return call[4:]


def make_outdated(prefix: Path) -> None:
    (prefix / "conda-meta").mkdir(parents=True)
    (prefix / "bin").mkdir()
    (prefix / "bin" / "python").write_text("#!/bin/sh\n")
    (prefix / "bin" / "python").chmod(0o755)
    (prefix / ".femkit").mkdir()
    (prefix / ".femkit" / "control.sha256").write_text("not the hash of channels.txt and control.txt\n")


def test_bootstrap_creates_control_by_its_name_where_the_manager_keeps_it_and_forwards_to_python(manager):
    """Fails if the script makes the control environment at a prefix of its own rather than by its
    name, `femkit`, where the manager keeps environments — so the manager would not list it, and
    femkit, asking the manager, would not find it — the script's create differs from the conda
    kind's, the stamp is not written, `femkit` is not linked from `<bin>`, or a verb is not
    forwarded to `python -m femkit env` (envs.md §§ 1, 7)."""
    assert install_env("bootstrap", "--yes").returncode == 0
    assert calls(manager)[0] == declared("create")[0] and calls(manager)[0][:4] == ["create", "-y", "-n", "femkit"]
    assert (control() / ".femkit" / "control.sha256").read_text().strip() == control_digest()
    assert link().is_symlink() and os.readlink(link()) == str(control() / LAUNCHER)
    assert forwarded(calls(manager)[1]) == ["bootstrap", "--yes"]
    assert install_env("install", "ngsolve", "--yes").returncode == 0  # the stamp made it current
    assert forwarded(calls(manager)[-1]) == ["install", "ngsolve", "--yes"]


@pytest.mark.parametrize("state", ["absent", "broken", "outdated"])
def test_a_verb_is_refused_until_control_is_current(manager, state):
    """Fails if a verb is forwarded while the control environment is absent, broken or
    outdated (envs.md § 7.3)."""
    prefix = control()
    if state == "broken":
        (prefix / "conda-meta").mkdir(parents=True)
    if state == "outdated":
        make_outdated(prefix)
    assert install_env("list", "--yes").returncode == 2
    assert calls(manager) == []


def stand(prefix: Path, environment: bool, python: int | None, stamp: str | None, command: Path | None = None,
          linked: bool = True) -> None:
    """The control prefix made to stand so: with or without conda-meta/ — without it, no environment
    the manager lists — a bin/python of this mode or none, a stamp — the one channels.txt and
    control.txt hash to, or another — a `femkit` command naming ``command``'s checkout, as the
    install script writes one there, or none, and `<bin>/femkit` linking it, or no link."""
    if prefix.exists():
        shutil.rmtree(prefix)
    if link().is_symlink():
        link().unlink()
    if linked:
        link().parent.mkdir(parents=True, exist_ok=True)
        link().symlink_to(prefix / LAUNCHER)
    prefix.mkdir(parents=True)
    if environment:
        (prefix / "conda-meta").mkdir()
    if python is not None:
        (prefix / "bin").mkdir()
        (prefix / "bin" / "python").write_text("#!/bin/sh\n")
        (prefix / "bin" / "python").chmod(python)
    if stamp is not None:
        (prefix / ".femkit").mkdir()
        (prefix / ".femkit" / "control.sha256").write_text(control_digest() if stamp == "its own" else stamp)
    if command is not None:
        (prefix / LAUNCHER).parent.mkdir(parents=True, exist_ok=True)
        (prefix / LAUNCHER).write_text(control_env.launcher_text(kit.ctx(), command, prefix / "bin" / "python"))


#: The states in which femkit runs from the control environment, so the script forwards every verb
#: to it — writing its `femkit` command where it is missing or another checkout's (envs.md § 7.3).
USABLE = {"current", "unlinked"}


def test_the_script_and_femkit_observe_the_control_environment_by_the_one_declared_table(manager, tmp_path):
    """Fails if the install script, which runs before femkit can, reads the control environment
    in another state than femkit/data/states/control.toml gives — the rules doctor reads it by —
    on any way its prefix can stand, its `femkit` command among them, or names another next step
    than that state allows; or if these ways leave a state of the table unseen (envs.md § 7.2,
    § 7.3)."""
    prefix, seen = control(), set()
    commands = (None, REPO, tmp_path / "another-checkout")
    ways = [None, *itertools.product((False, True), (None, 0o644, 0o755), (None, "another hash\n", "its own"),
                                     commands, (False, True))]
    for way in ways:
        if way is not None:
            stand(prefix, *way)
        row = control_row()
        ran = install_env("list", "--yes")
        lines = ran.stderr.splitlines()
        listed = (prefix / "conda-meta").is_dir()                     # what the manager lists
        if row.state in USABLE:
            assert ran.returncode == 0 and "refused" not in ran.stderr, (way, ran.stderr)
        else:
            said = f"[femkit] refused: the control environment femkit is {row.state}" + (f": {prefix}" if listed else "")
            assert ran.returncode == 2 and said in lines, (way, row.state, ran.stderr)
            assert lines[lines.index("next -- instead:") + 1:] == [f"    {n}" for n in row.next], (way, ran.stderr)
        seen.add(row.state)
    assert seen == set(load_states()["control"].states)


def control_row():
    return next(r for r in run("doctor").rows if r.subject == "control environment")


def test_plain_bootstrap_rebuilds_an_outdated_or_broken_control(manager):
    """Fails if a changed control.txt or a broken control environment is not rebuilt by
    plain `bootstrap`: the repair must never need --clean, which also rebuilds every engine
    environment (envs.md § 7.3)."""
    make_outdated(control())
    assert install_env("bootstrap", "--yes").returncode == 0
    assert calls(manager)[:2] == declared("remove", "create")

    manager.unlink()
    (control() / ".femkit" / "control.sha256").unlink()  # broken: no stamp
    assert install_env("bootstrap", "--yes").returncode == 0
    assert calls(manager)[:2] == declared("remove", "create")
    assert forwarded(calls(manager)[2]) == ["bootstrap", "--yes"]


def test_nothing_is_created_without_consent_or_on_a_dry_run(manager):
    """Fails if the script creates without a terminal and without --yes, or creates the
    control environment to answer --dry-run (envs.md § 7.3)."""
    assert install_env("bootstrap").returncode == 2
    assert install_env("bootstrap", "--dry-run").returncode == 2
    assert calls(manager) == [] and not control().exists() and not link().is_symlink()


@pytest.mark.parametrize("how", ["xdg", "tilde", "trailing slash", "dot step", "home's trailing slash"])
def test_the_script_and_femkit_resolve_the_data_directory_alike(manager, monkeypatch, tmp_path, how):
    """Fails if the script and core/dirs.py put the control environment in different places,
    or write its `femkit` command otherwise than doctor reads it as this checkout's, when the data
    directory comes from XDG_DATA_HOME, holds `~`, or is written with a `/` at its end or a `./`
    step, as Python's paths never write one (config.md § 2; envs.md § 7.2)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    if how in ("xdg", "dot step", "home's trailing slash"):
        monkeypatch.delenv("FEMKIT_DATA_DIR")
    if how == "xdg":
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    elif how == "dot step":
        monkeypatch.setenv("XDG_DATA_HOME", f"{tmp_path}/./xdg")
    elif how == "home's trailing slash":
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setenv("HOME", f"{tmp_path}/home/")
    elif how == "tilde":
        monkeypatch.setenv("FEMKIT_DATA_DIR", "~/femkit-data")
    else:
        monkeypatch.setenv("FEMKIT_DATA_DIR", f"{tmp_path}/data/")
    assert install_env("bootstrap", "--yes").returncode == 0
    assert calls(manager)[0] == declared("create")[0]
    assert control_row().state == "current"


def test_a_relative_data_directory_is_refused_by_both(manager, monkeypatch):
    """Fails if either the script or femkit takes the data directory from where the
    command runs (config.md § 2)."""
    monkeypatch.setenv("FEMKIT_DATA_DIR", "relative/data")
    assert install_env("bootstrap", "--yes").returncode == 2 and calls(manager) == []
    with refused(UsageError, "not-absolute", "FEMKIT_DATA_DIR"):
        dirs.data_dir()


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
    other = manager.parent / "no-kind" / "micromamba"
    other.parent.mkdir()
    other.write_text((manager.parent / "stand-in" / "conda").read_text())  # the same stand-in, renamed
    other.chmod(0o755)
    monkeypatch.setenv("FEMKIT_ENV_MANAGER", str(other))
    assert install_env("bootstrap", "--yes").returncode == 2
    assert calls(manager) == [] and not control().exists()


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


def test_a_manager_named_without_a_path_is_found_on_path(manager, monkeypatch):
    """Fails if FEMKIT_ENV_MANAGER=conda, a name rather than a path, is refused instead of
    being looked up on PATH and used by its full path (envs.md § 7.1)."""
    on_path = manager.parent / "stand-in"
    monkeypatch.setenv("FEMKIT_ENV_MANAGER", "conda")
    monkeypatch.setenv("PATH", f"{on_path}:/usr/bin:/bin")
    out = install_env("bootstrap", "--yes")
    assert out.returncode == 0 and f"env manager: {on_path / 'conda'}   # found by FEMKIT_ENV_MANAGER" in out.stderr
    assert calls(manager)[0] == declared("create")[0]


def test_a_manager_femkit_cannot_drive_is_listed_and_one_it_can_is_proposed(manager, monkeypatch):
    """Fails if a manager femkit cannot drive is chosen, or goes unmentioned, when one it can
    drive is in reach too (envs.md § 7.1)."""
    on_path = manager.parent / "stand-in"
    (on_path / "micromamba").write_text("#!/bin/sh\nexit 97\n")
    (on_path / "micromamba").chmod(0o755)
    monkeypatch.delenv("FEMKIT_ENV_MANAGER")
    monkeypatch.setenv("PATH", f"{on_path}:/usr/bin:/bin")
    out = install_env("bootstrap", "--yes")
    assert out.returncode == 0 and "femkit has no kind file for micromamba" in out.stderr
    assert calls(manager)[0] == declared("create")[0]


def test_control_is_created_and_removed_with_the_chosen_managers_own_commands(manager, monkeypatch):
    """Fails if the script spells conda's commands whatever the manager: mamba 2 refuses conda's
    --no-default-packages, so its control environment would never be created (definitions.md § 6)."""
    mamba = manager.parent / "stand-in" / "mamba"
    mamba.write_text((manager.parent / "stand-in" / "conda").read_text())  # the same stand-in, as mamba
    mamba.chmod(0o755)
    monkeypatch.setenv("FEMKIT_ENV_MANAGER", str(mamba))
    kind = load_managers()["mamba"]
    create = [render(a, {"exe": "", "name": "femkit"}) for a in kind.create[1:]]
    create += [render(a, {"channel": c}) for c in load_control().channels for a in kind.channel]
    assert install_env("bootstrap", "--yes").returncode == 0
    assert calls(manager)[0] == create + ["--file", str(control_files()[1])]
    (control() / ".femkit" / "control.sha256").write_text("outdated\n")
    assert install_env("bootstrap", "--yes").returncode == 0
    assert [render(a, {"exe": "", "name": "femkit"}) for a in kind.remove[1:]] in calls(manager)


@pytest.mark.parametrize("held", ["shared", "alone"])
def test_the_control_environment_is_never_rebuilt_while_femkit_runs_from_it(manager, held):
    """Fails if the install script removes the control environment while another process uses
    it — holding its lock, `control`, shared, as a running web server's supervisor does — or runs
    femkit from it while another holds it alone, as a rebuild does; or if its refusal does not
    name the holder and what ends its hold (envs.md § 7.3; core.md § 5: "a second is refused,
    never queued")."""
    make_outdated(control())
    holder = hold(dirs.CONTROL, held)
    try:
        ran = install_env("bootstrap", "--yes")
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    lines = ran.stderr.splitlines()
    assert ran.returncode == 2 and calls(manager) == [], ran.stderr     # nothing removed, nothing run
    assert f"a user of {dirs.CONTROL} (pid {holder.pid})" in ran.stderr
    assert lines[lines.index("next -- instead:") + 1] == "    end it"
    assert install_env("bootstrap", "--yes").returncode == 0           # once it has ended
    assert calls(manager)[:2] == declared("remove", "create")


def test_no_manager_femkit_can_drive_says_where_a_cluster_loads_one(manager, monkeypatch, tmp_path):
    """Fails if the script, finding only managers femkit cannot drive, refuses without saying
    that on a cluster the manager's module is loaded in this shell first (envs.md § 7.1)."""
    other = tmp_path / "only" / "micromamba"
    other.parent.mkdir()
    other.write_text("#!/bin/sh\nexit 97\n")
    other.chmod(0o755)
    monkeypatch.delenv("FEMKIT_ENV_MANAGER")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))       # no usual install root holds one
    for variable in ("MAMBA_EXE", "CONDA_EXE", "CONDA_PREFIX"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("PATH", f"{other.parent}:/usr/bin:/bin")
    ran = install_env("bootstrap", "--yes")
    assert ran.returncode == 2 and "on a cluster, load the manager's module in this shell first" in ran.stderr


def test_help_before_control_exists_is_the_scripts_own_and_creates_nothing(manager):
    """Fails if `bootstrap --help` on a fresh machine refuses, or creates control to
    answer (envs.md § 7.3)."""
    assert install_env("bootstrap", "--help").returncode == 0
    assert calls(manager) == [] and not control().exists()


def test_the_scripts_manager_commands_start_clean_as_the_declared_start_and_the_person_set_it_up(
        manager, monkeypatch):
    """Fails if the install script's create, removal or query of where the manager's environments
    are sees another active environment, outside Python, injected libraries or an outside toolchain,
    any `PATH` but the system's, or runs anywhere but as the person set the manager up — their home,
    their `.condarc`, their package cache, a proxy — reading the clean start otherwise than
    process.toml declares it, as femkit does (envs.md §§ 4.4, 7.1)."""
    kit.polluted(monkeypatch)
    monkeypatch.setenv("PATH", f"/outside/env/bin:{manager.parent / 'stand-in'}:/usr/bin:/bin")
    assert install_env("bootstrap", "--yes").returncode == 0
    (control() / ".femkit" / "control.sha256").write_text("outdated\n")
    assert install_env("bootstrap", "--yes").returncode == 0       # removed, and created again
    handed = [e for e, line in zip(kit.calls_env(manager), manager.read_text().splitlines())
              if not line.startswith("python ")]
    assert len(handed) >= 5                                         # queries, a create, a removal, a create
    for env in handed:
        assert kit.kept(env) and not kit.leaked(env), kit.leaked(env)
        assert env["PATH"] == "/usr/bin:/bin" and env["PYTHONNOUSERSITE"] == "1"


def test_the_control_python_is_run_isolated(manager, tmp_path, monkeypatch):
    """Fails if the script's forward runs femkit otherwise than isolated (`-I`) — the person's own
    PYTHONPATH or user site-packages would reach it, and femkit would import what they installed for
    themselves instead of its own control environment's packages (envs.md § 7.3: the `femkit`
    command's form)."""
    persons = str(tmp_path / "the-persons-packages")
    monkeypatch.setenv("PYTHONPATH", persons)
    monkeypatch.delenv("PYTHONNOUSERSITE", raising=False)
    assert install_env("bootstrap", "--yes").returncode == 0
    assert "-I" in calls(manager)[-1]


# ------------------------------------------------------------------ the `femkit` command (envs.md § 7)

LAUNCHER = Path("bin") / "femkit"   # in the control prefix: the `femkit` command, which `<bin>/femkit` links
#: The script's bootstrap, by the script's absolute path in this checkout, so it pastes from any folder (envs.md § 7).
BOOTSTRAP = [f"bash {shlex.quote(str(SCRIPT))} bootstrap"]


def a_checkout(folder: Path) -> Path:
    """A checkout of femkit's at ``folder``, as far as the install script and the `femkit` command
    read one — the script, femkit's shipped data, femkit's `__main__` — and its script."""
    shutil.copytree(REPO / "scripts", folder / "scripts")
    shutil.copytree(REPO / "femkit" / "data", folder / "femkit" / "data")
    shutil.copy2(REPO / "femkit" / "__main__.py", folder / "femkit" / "__main__.py")
    return folder / "scripts" / "install-env.sh"


def test_the_script_writes_the_femkit_command_doctor_reads_as_this_checkouts(manager, tmp_path):
    """Fails if the install script leaves a current control environment without its `femkit`
    command, or writes one that cannot be run or differs from femkit/data/launcher.sh filled for
    this checkout, the control environment's own Python and the clean start — as doctor fills it;
    or if doctor calls a control environment ready while that command is missing, or names anything
    but the script's bootstrap, by its path in this checkout, for it (envs.md §§ 4.4, 6.1, 7)."""
    stand(control(), True, 0o755, "its own", linked=False)   # made, as a script before the command left it
    row = control_row()
    assert (row.state, row.detail, row.ready, [n.command for n in row.next]) == (
        "unlinked", "no femkit command", False, BOOTSTRAP)
    assert install_env("list").returncode == 0
    written = control() / LAUNCHER
    assert os.access(written, os.X_OK)
    assert written.read_text() == control_env.launcher_text(kit.ctx(), REPO, control() / "bin" / "python")
    row = control_row()
    assert (row.state, row.detail, row.ready, row.next) == ("current", "femkit runs this checkout", True, [])
    link().unlink()                                       # the command there, but no longer on a shell's path
    row = control_row()
    assert (row.state, row.ready, [n.command for n in row.next]) == ("unlinked", False, BOOTSTRAP)
    assert f"{text.path(link())} does not link it" in row.detail
    assert install_env("list").returncode == 0 and os.readlink(link()) == str(written)
    link().unlink()
    link().write_text("a file of the person's\n")         # never replaced: the link is the script's alone
    ran = install_env("list")
    assert ran.returncode == 2 and link().read_text() == "a file of the person's\n" and str(link()) in ran.stderr


def test_doctor_tells_an_older_form_of_this_checkouts_command_from_another_checkouts(manager):
    """Fails if doctor tells a person whose `femkit` command names this checkout, in a form the
    script has since changed, that it runs another checkout — a false thing to tell every install
    when the command's form changes — or offers anything but the script's bootstrap that writes it
    again (envs.md § 7.2: "is not the one the script writes from this checkout")."""
    stand(control(), True, 0o755, "its own")
    assert install_env("list").returncode == 0
    written = control() / LAUNCHER
    written.write_text(written.read_text().replace(" -I ", " -P "))     # an earlier form, this checkout
    row = control_row()
    assert (row.state, row.detail, row.ready, [n.command for n in row.next]) == (
        "unlinked", "an older form of the femkit command", False, BOOTSTRAP)


def test_the_femkit_command_runs_femkit_from_its_checkout_in_the_folder_it_is_typed_in(
        manager, laplace, tmp_path, monkeypatch):
    """Fails if the `femkit` command runs femkit on another Python than the control environment's,
    not isolated from the person's own Python path, user site-packages and the folder it is typed
    in — so a file of the person's named like a module femkit imports would be loaded in its place
    — other than in the folder it is typed in — `femkit project check` typed inside a project would
    not name that project — if it changes the environment a process femkit starts inherits — a run
    would read femkit's checkout — or does not hand femkit its arguments as typed (envs.md § 7;
    projects.md § 1)."""
    assert install_env("bootstrap", "--yes").returncode == 0
    femkit, python = link(), control() / "bin" / "python"           # typed in a new shell: the link on its path
    persons = str(tmp_path / "the-persons-packages")
    monkeypatch.setenv("PYTHONPATH", persons)
    monkeypatch.delenv("PYTHONNOUSERSITE", raising=False)
    assert subprocess.run([str(femkit), "env", "list"], timeout=60).returncode == 0   # the stand-in's python
    assert calls(manager)[-1] == ["python", "-I", str(REPO / "femkit" / "__main__.py"), "env", "list"]

    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')   # a Python that runs femkit
    inside = laplace / "components"
    (inside / "click.py").write_text('raise SystemExit("the folder typed in was put on the import path")\n')
    checked = subprocess.run([str(femkit), "project", "check", "--json"], cwd=inside, capture_output=True,
                             text=True, timeout=120)
    assert json.loads(checked.stdout)["project"] == laplace.name, checked.stderr
    typed = "no such 'one'"
    named = subprocess.run([str(femkit), "project", "check", "--project", typed, "--json"], cwd=tmp_path,
                           capture_output=True, text=True, timeout=120)
    assert (named.returncode, json.loads(named.stdout)["subject"]) == (2, typed)


def test_the_femkit_command_names_the_checkout_the_script_ran_from_and_refuses_once_it_is_gone(manager, tmp_path):
    """Fails if a `femkit` command whose checkout is gone runs anything, or says other than one
    plain line naming that checkout and the script's bootstrap, run from the new place; if the
    script run from the checkout's new place leaves the command naming the old one; or if doctor
    calls another checkout's command this one's (envs.md § 6.1, § 7)."""
    old, moved = tmp_path / "old", tmp_path / "moved"
    assert install_env("bootstrap", "--yes", script=a_checkout(old)).returncode == 0
    femkit = control() / LAUNCHER
    row = control_row()                                              # this test runs from another checkout
    assert (row.state, row.detail, row.ready, [n.command for n in row.next]) == (
        "unlinked", "femkit runs another checkout", False, BOOTSTRAP)
    old.rename(moved)
    manager.unlink()
    gone = subprocess.run([str(femkit), "doctor"], capture_output=True, text=True, timeout=60)
    assert (gone.returncode, gone.stdout, calls(manager)) == (2, "", [])
    assert gone.stderr.splitlines() == [f"[femkit] refused: the femkit checkout {old.resolve()} is gone; "
                                        "from its new place, run: bash scripts/install-env.sh bootstrap"]
    assert install_env("list", script=moved / "scripts" / "install-env.sh").returncode == 0
    assert subprocess.run([str(femkit), "env", "list"], timeout=60).returncode == 0
    assert calls(manager)[-1][:3] == ["python", "-I", str(moved.resolve() / "femkit" / "__main__.py")]


# ------------------------------------------------------------------ the one door, from the install script (envs.md §§ 4.4, 7)

def started(log: Path) -> dict[str, str]:
    """Every variable the stand-in control environment's python began with, its last start."""
    return dict(line.split("=", 1) for line in Path(f"{log}.python.env").read_text().splitlines() if "=" in line)


def test_femkit_started_by_its_command_keeps_the_shell_but_what_changes_its_own_python(manager, monkeypatch):
    """Fails if the `femkit` command starts femkit's own Python with an injected library, or if it
    takes from femkit the shell it was typed in — its `PATH`, the module system's `module` — so
    femkit could not see the machine it probes as the person does: a scheduler's commands, the GPUs'
    tools, the loaded modules (envs.md § 7; process.toml's `femkit_sheds`). Every process femkit
    starts for an environment begins clean, which the one door's own tests hold."""
    assert install_env("bootstrap", "--yes").returncode == 0
    kit.polluted(monkeypatch)
    assert subprocess.run([str(link()), "env", "list"], timeout=60).returncode == 0   # the stand-in's python
    env = started(manager)
    assert "LD_PRELOAD" not in env
    assert "/outside/env/bin" in env["PATH"] and kit.kept(env), env.get("PATH")
    assert calls(manager)[-1][:2] == ["python", "-I"]


def test_the_scripts_clean_start_passes_what_a_job_of_each_scheduler_kind_sees(manager, monkeypatch):
    """Fails if the install script's own manager commands start from another clean start than
    femkit's — leaving out what a job of a scheduler kind sees, its job variables and the shell
    functions it declares, or keeping one no kind declares (envs.md §§ 4.4, 7.1: "each from the same
    clean start"; one reading of the same data). Its forward to femkit keeps the shell as the
    `femkit` command does, which that command's own test holds."""
    monkeypatch.setenv("SLURM_JOB_ID", "77")
    kit.polluted(monkeypatch)
    monkeypatch.setenv("PATH", f"{manager.parent / 'stand-in'}:/usr/bin:/bin")
    assert install_env("bootstrap", "--yes").returncode == 0
    handed = kit.calls_env(manager)
    assert len(handed) >= 2                                           # the queries and the create
    for env in handed:
        assert env.get("SLURM_JOB_ID") == "77" and kit.kept(env) and not kit.leaked(env), kit.leaked(env)


@pytest.mark.parametrize("says_names", [True, False], ids=["its own names", "where it keeps them"])
def test_the_control_environment_is_the_one_the_manager_names_femkit(manager, says_names):
    """Fails if the install script takes for the control environment a listed folder the manager
    does not name `femkit` — one made by its path elsewhere, whose last step only happens to be the
    name — whether the manager says its own name for each or only where it keeps them, instead of
    making the control environment by its name (envs.md § 1)."""
    if not says_names:
        kit.manager_root().mkdir(parents=True, exist_ok=True)
        (kit.manager_root() / "no-names").touch()
    elsewhere = kit.manager_root() / "elsewhere" / "femkit"
    make_outdated(elsewhere)
    (elsewhere / ".femkit" / "control.sha256").write_text(control_digest())
    ran = install_env("bootstrap", "--yes")
    assert ran.returncode == 0 and "control environment femkit: absent" in ran.stderr, ran.stderr
    assert calls(manager)[0] == declared("create")[0] and control().is_dir()


def test_a_setting_nothing_sets_aside_is_refused_before_the_control_environment_is_made(manager):
    """Fails if the install script creates the control environment while a setting of the person's
    that nothing its create carries sets aside holds — conda then refusing `--override-channels`,
    by which femkit names its own channels — instead of refusing first, naming the setting and the
    file the manager read it from (envs.md § 4.4)."""
    kit.manager_root().mkdir(parents=True, exist_ok=True)
    rc = kit.manager_root() / "condarc.json"
    rc.write_text('{"channels": ["defaults"], "override_channels_enabled": false}')
    ran = install_env("bootstrap", "--yes")
    assert ran.returncode == 2 and calls(manager) == [] and not control().exists()
    assert f"your setting override_channels_enabled, in {rc}" in ran.stderr, ran.stderr
    rc.write_text('{"channels": ["defaults"], "override_channels_enabled": true}')
    assert install_env("bootstrap", "--yes").returncode == 0


def test_bootstrap_says_how_a_new_shell_finds_femkit_where_its_folder_is_not_on_path(manager, monkeypatch):
    """Fails if bootstrap, where the folder it links `femkit` from is not on this shell's PATH, leaves
    the person to find out that a new shell does not find femkit, instead of printing the one line
    that puts the folder there, or the activation that enters the control environment (envs.md § 7)."""
    monkeypatch.setenv("PATH", f"{manager.parent / 'stand-in'}:/usr/bin:/bin")
    ran = install_env("bootstrap", "--yes")
    assert ran.returncode == 0
    assert f'    export PATH={shlex.quote(str(dirs.bin_dir()))}:"$PATH"' in ran.stderr.splitlines(), ran.stderr
    assert "conda activate femkit" in ran.stderr
    monkeypatch.setenv("PATH", f"{dirs.bin_dir()}:{manager.parent / 'stand-in'}:/usr/bin:/bin")
    assert "export PATH=" not in install_env("bootstrap", "--yes").stderr
