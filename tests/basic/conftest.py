"""Tripwires for the basic tier (testing.md § 2.1).

PATH starts with a directory holding a tripwire for every outside program
femkit can start; a test that reaches one fails, naming the call.
"""

from __future__ import annotations

import os
import shlex
import stat
import sys
from pathlib import Path

import pytest

from femkit.config.probe import GPU_QUERY
from femkit.definitions.catalogue import load_environments, load_managers, load_schedulers

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


REACHED = "reached.log"  # in the tripwire directory: every call a tripwire took during the current test


def _tripwire(log: Path) -> str:
    """A tripwire's text. The log's path is written into it, not passed in a variable: a command
    run in a prefix sees only the confined variables (envs.md § 4.4)."""
    return f'#!/bin/sh\necho "$0 $*" >> {shlex.quote(str(log))}\nexit 97\n'


@pytest.fixture(scope="session")
def tripwire_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("tripwires")
    for name in tripwire_names():
        script = d / name
        script.write_text(_tripwire(d / REACHED))
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return d


@pytest.fixture
def tripwire_script(tripwire_dir) -> str:
    """A tripwire's text, for a test that places one of its own."""
    return _tripwire(tripwire_dir / REACHED)


@pytest.fixture(autouse=True)
def tripwires(tripwire_dir, monkeypatch):
    log = tripwire_dir / REACHED
    log.unlink(missing_ok=True)
    for kind in load_schedulers().values():  # run inside an allocation, a basic test still sees none of its job
        for variable in kind.job_variables.values():
            monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("PATH", f"{tripwire_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FEMKIT_ENV_MANAGER", str(tripwire_dir / sorted(load_managers())[0]))
    yield log
    if log.exists() and log.read_text().strip():
        pytest.fail("a basic test reached an outside program: " + log.read_text().strip())


# A stand-in manager: it records each call and makes the folders a create would, with a
# `python` that records how it was called (the install script's forward);
# `running_manager`'s also runs what it is asked to run in a prefix.
# The stand-in prints nothing, so no manager output is typed in; the real managers run
# the same forms in the field tier. Its own settings are written into it, as a real manager's
# are its installation: femkit hands commands run in a prefix only the confined variables
# (envs.md § 4.4), and a stand-in that read its log path from them would lose it.
STAND_IN = r"""#!/bin/sh
printf '%s\n' "$*" >> @LOG@
printf '%s %s %s %s person=%s\n' "$HOME" "${CONDA_PKGS_DIRS:-unset}" "${CONDA_REGISTER_ENVS:-unset}" "${TMPDIR:-unset}" \
  "${XDG_CONFIG_HOME-}${XDG_CACHE_HOME-}${XDG_DATA_HOME-}${XDG_STATE_HOME-}${CONDARC-}${MAMBARC-}" >> @LOG@.places
case "$1 $2" in
RUN_LINE
  "create -y") prefix="$4"; mkdir -p "$prefix/conda-meta" "$prefix/bin"
                printf '#!/bin/sh\necho "python $*" >> %s\n' @LOG@ > "$prefix/bin/python"
                chmod +x "$prefix/bin/python" ;;
  "env remove") rm -rf "$5" ;;
  "remove --all") rm -rf "$5" ;;
esac
exit 0
"""


# run COMMAND in the prefix: as an activation would, put the environment's own interpreter (here, the
# test process's) on PATH — after the tripwires, so a command run in a prefix that reaches an outside
# program still fails the test instead of finding the host's copy on the confined PATH.
RUNS = '  "run --no-capture-output") shift 4; PATH=@TRIPWIRES@:@ACTIVATION@:"$PATH" exec "$@" ;;'


def _stand_in(tmp_path, monkeypatch, tripwires: Path, runs: bool) -> Path:
    fake = tmp_path / "stand-in" / "conda"
    fake.parent.mkdir()
    log = tmp_path / "manager.log"
    script = STAND_IN.replace("RUN_LINE\n", RUNS + "\n" if runs else "")
    fake.write_text(script.replace("@LOG@", shlex.quote(str(log))).replace("@TRIPWIRES@", shlex.quote(str(tripwires)))
                    .replace("@ACTIVATION@", shlex.quote(str(Path(sys.executable).parent))))
    fake.chmod(0o755)
    monkeypatch.setenv("FEMKIT_ENV_MANAGER", str(fake))
    return log


@pytest.fixture
def manager(tmp_path, monkeypatch, tripwire_dir):
    """FEMKIT_ENV_MANAGER pointing at the stand-in; returns the file its calls go to."""
    return _stand_in(tmp_path, monkeypatch, tripwire_dir, runs=False)


@pytest.fixture
def running_manager(tmp_path, monkeypatch, tripwire_dir):
    """The stand-in, also running each command it is asked to run in a prefix."""
    return _stand_in(tmp_path, monkeypatch, tripwire_dir, runs=True)


@pytest.fixture
def give_checks(definitions):
    """Give a shipped definition these checks and agreements, in the test's own copy of the
    definitions, written as its file holds them: what its two environments then load."""
    import tomllib
    from femkit.core.persist import write_toml

    def give(name: str, checks: list, agreements: dict | None = None) -> None:
        path = definitions / "environments" / f"{name}.toml"
        data = tomllib.loads(path.read_text())
        data["checks"] = [c.model_dump(mode="json", exclude_defaults=True) for c in checks]
        data["agreements"] = {k: a.model_dump(mode="json", exclude_defaults=True) for k, a in (agreements or {}).items()}
        write_toml(path, data)
    return give
