"""The user's six directories (config.md § 2).

Each is read from the environment when asked, never at import.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from pathlib import Path

from femkit.core.errors import UsageError

#: Each of femkit's directories with the variable that names it outright (config.md § 2): every
#: place femkit writes on its own account is one of these, or under one.
VARIABLES = {
    "config": "FEMKIT_CONFIG_DIR", "data": "FEMKIT_DATA_DIR", "cache": "FEMKIT_CACHE_DIR",
    "state": "FEMKIT_STATE_DIR", "runtime": "FEMKIT_RUNTIME_DIR", "bin": "FEMKIT_BIN_DIR",
}
#: Where each but the runtime and bin directories is found when its variable is unset: under the
#: XDG variable's folder, or under the home folder.
_XDG = {
    "config": ("XDG_CONFIG_HOME", ".config"), "data": ("XDG_DATA_HOME", ".local/share"),
    "cache": ("XDG_CACHE_HOME", ".cache"), "state": ("XDG_STATE_HOME", ".local/state"),
}


def folder_from(variable: str, value: str, what: str) -> Path:
    """A folder a variable names: `~` expanded; a relative one refused, never taken from where
    the command runs (config.md § 2). scripts/install-env.sh applies the same rule."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        from femkit.core import view  # here, not at the top: the supervisor imports this module (web.md § 4)
        raise UsageError(f"{what} must be an absolute path, not {path}", (view.shell(
            f"export {variable}={{path}}", fills=[view.Fill(field="path", label=f"{what}, an absolute path",
                                                            example="/absolute/path")]),),
            code="not-absolute", subject=variable)
    return path


def _resolve(which: str) -> Path:
    own, (xdg, fallback) = VARIABLES[which], _XDG[which]
    if os.environ.get(own):
        return folder_from(own, os.environ[own], f"the {which} directory")
    return folder_from(xdg, str(Path(os.environ.get(xdg) or str(Path.home() / fallback)) / "femkit"),
                       f"the {which} directory")


def config_dir() -> Path:
    return _resolve("config")


def data_dir() -> Path:
    return _resolve("data")


def cache_dir() -> Path:
    return _resolve("cache")


def state_dir() -> Path:
    return _resolve("state")


def host() -> str:
    """This machine's name, as the runtime directory is keyed by it."""
    return socket.gethostname()


def runtime_dir() -> Path:
    """`<state>/run/<host>/`, or `FEMKIT_RUNTIME_DIR` (config.md § 2): a running server's
    pidfile, token and socket. Host-keyed, because a shared home is seen by every login node."""
    own = os.environ.get(VARIABLES["runtime"])
    return folder_from(VARIABLES["runtime"], own, "the runtime directory") if own else state_dir() / "run" / host()


CONTROL = "control"  # the control environment's name (envs.md § 1)
COMMAND = "femkit"   # the command a person types, as the install script writes it and links it (envs.md § 7)
BIN = ".local/bin"   # where the link that puts it on a shell's path lies when FEMKIT_BIN_DIR is unset


def bin_dir() -> Path:
    """`~/.local/bin`, or `FEMKIT_BIN_DIR` (config.md § 2): where the install script links `femkit`,
    a folder most shells put on their path once it exists (envs.md § 7)."""
    own = os.environ.get(VARIABLES["bin"])
    return folder_from(VARIABLES["bin"], own, "the bin directory") if own else Path.home() / BIN


def checkout() -> Path:
    """The checkout femkit runs from; it is never installed (envs.md § 7)."""
    return Path(__file__).resolve().parents[2]


INSTALL_SCRIPT = Path("scripts") / "install-env.sh"   # in the checkout: the install script (envs.md § 7)


def install_script() -> Path:
    """The install script, by its absolute path in the checkout femkit runs from: what every step
    that names it prints, so the line pastes from any folder (envs.md § 7)."""
    return checkout() / INSTALL_SCRIPT


def femkit_argv(python: str | Path, module: str, *arguments: str) -> list[str]:
    """How femkit starts one of its own Python programs, on any environment's Python — the web
    server's supervisor and its child, a check program inside a prefix (envs.md § 7): the module
    run with `-P`, so no folder it runs in is on its import path, with ``femkit_env``."""
    return [str(python), "-P", "-m", module, *arguments]


def femkit_env(start: Mapping[str, str]) -> dict[str, str]:
    """The environment of femkit's own Python program (envs.md § 7): ``start``, the clean start
    every process femkit starts for an environment begins from (envs/start.py, process.toml) — no
    Python setting of the person's in it, no user site-packages — with femkit's checkout alone as its
    import path, the door's one addition, so no module of the person's stands in for one femkit
    imports. A run is no program of femkit's: it starts clean and enters its environment by its run
    script (jobs.md § 4, block 8)."""
    return {**start, "PYTHONPATH": str(checkout())}


def directory_sources() -> dict[str, tuple[Path, str]]:
    """Each directory with the rule that chose it, for `config path`."""
    out = {}
    for which, (xdg, fallback) in _XDG.items():
        own = VARIABLES[which]
        rule = own if os.environ.get(own) else (xdg if os.environ.get(xdg) else f"~/{fallback}")
        out[which] = (_resolve(which), rule)
    out["runtime"] = (runtime_dir(), VARIABLES["runtime"] if os.environ.get(VARIABLES["runtime"])
                      else "<state>/run/<host>")
    out["bin"] = (bin_dir(), VARIABLES["bin"] if os.environ.get(VARIABLES["bin"]) else f"~/{BIN}")
    return out
