"""The basic tier (testing.md § 1): behind the tripwires (§ 2.1, tests/kit.py), with a stand-in
package manager for a test that needs one."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

from tests.kit import REACHED, tripwire_dir, tripwire_text, tripwires  # noqa: F401


@pytest.fixture
def tripwire_script(tripwire_dir) -> str:
    """A tripwire's text, for a test that places one of its own."""
    return tripwire_text(tripwire_dir / REACHED)


# A stand-in manager: it records each call, the places and the manager's own variables it was
# handed, and makes the folders a create would, with a `python` that records how it was called
# and the Python path it was given (the install script's forward);
# `running_manager`'s also runs what it is asked to run in a prefix.
# The stand-in prints nothing, so no manager output is typed in; the real managers run
# the same forms in the field tier. Its own settings are written into it, as a real manager's
# are its installation: femkit hands commands run in a prefix only the confined variables
# (envs.md § 4.4), and a stand-in that read its log path from them would lose it.
STAND_IN = r"""#!/bin/sh
printf '%s\n' "$*" >> @LOG@
printf '%s %s %s %s person=%s managers=%s\n' "$HOME" "${CONDA_PKGS_DIRS:-unset}" "${CONDA_REGISTER_ENVS:-unset}" \
  "${TMPDIR:-unset}" "${XDG_CONFIG_HOME-}${XDG_CACHE_HOME-}${XDG_DATA_HOME-}${XDG_STATE_HOME-}${CONDARC-}${MAMBARC-}" \
  "$(env | sed -n 's/^\(CONDA_[^=]*\)=.*/\1/p; s/^\(MAMBA_[^=]*\)=.*/\1/p' | sort | tr '\n' ,)" >> @LOG@.places
case "$1 $2" in
RUN_LINE
  "create -y") prefix="$4"; mkdir -p "$prefix/conda-meta" "$prefix/bin"
                printf '#!/bin/sh\necho "python $*" >> %s\necho "${PYTHONPATH-unset} ${PYTHONNOUSERSITE-unset}" >> %s.python\n' \
                  @LOG@ @LOG@ > "$prefix/bin/python"
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


def _stand_in(tmp_path, monkeypatch, tripwires: Path, runs: bool, case: str = "") -> Path:
    fake = tmp_path / "stand-in" / "conda"
    fake.parent.mkdir()
    log = tmp_path / "manager.log"
    script = STAND_IN.replace("RUN_LINE\n", (RUNS + "\n" if runs else "") + (case + "\n" if case else ""))
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
def manager_doing(tmp_path, monkeypatch, tripwire_dir):
    """The stand-in with one case of the test's own before its others — a shell `case` line:
    what a command did to the machine besides, as another shell working meanwhile would."""
    return lambda case, runs=False: _stand_in(tmp_path, monkeypatch, tripwire_dir, runs=runs, case=case)


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
