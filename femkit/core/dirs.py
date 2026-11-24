"""The user's five directories (config.md § 2).

Each is read from the environment when asked, never at import.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

from femkit.core.errors import UsageError

#: Each of femkit's directories with the variable that names it outright (config.md § 2): every
#: place femkit writes on its own account is one of these, or under one.
VARIABLES = {
    "config": "FEMKIT_CONFIG_DIR", "data": "FEMKIT_DATA_DIR", "cache": "FEMKIT_CACHE_DIR",
    "state": "FEMKIT_STATE_DIR", "runtime": "FEMKIT_RUNTIME_DIR",
}
#: Where each but the runtime directory is found when its variable is unset: under the XDG
#: variable's folder, or under the home folder.
_XDG = {
    "config": ("XDG_CONFIG_HOME", ".config"), "data": ("XDG_DATA_HOME", ".local/share"),
    "cache": ("XDG_CACHE_HOME", ".cache"), "state": ("XDG_STATE_HOME", ".local/state"),
}


def _resolve(which: str) -> Path:
    """`~` is expanded; a relative directory is refused, never taken from where
    the command runs (config.md § 2). scripts/install-env.sh applies the same rule."""
    own, (xdg, fallback) = VARIABLES[which], _XDG[which]
    if os.environ.get(own):
        path = Path(os.environ[own]).expanduser()
    else:
        path = Path(os.environ.get(xdg) or str(Path.home() / fallback)).expanduser() / "femkit"
    if not path.is_absolute():
        from femkit.core import view  # here, not at the top: the supervisor imports this module (web.md § 4)
        raise UsageError(f"the {which} directory must be an absolute path, not {path}", (view.shell(f"export {own}=/absolute/path"),),
                         code="not-absolute", subject=own)
    return path


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
    path = Path(own).expanduser() if own else state_dir() / "run" / host()
    if not path.is_absolute():
        from femkit.core import view  # here, not at the top: the supervisor imports this module (web.md § 4)
        raise UsageError(f"the runtime directory must be an absolute path, not {path}",
                         (view.shell(f"export {VARIABLES['runtime']}=/absolute/path"),),
                         code="not-absolute", subject=VARIABLES["runtime"])
    return path


CONTROL = "control"  # the control environment's name (envs.md § 1)


def checkout() -> Path:
    """The checkout femkit runs from; it is never installed (envs.md § 7)."""
    return Path(__file__).resolve().parents[2]


def environments_dir() -> Path:
    """Where environments go unless `paths.environments` says otherwise (config.md § 3)."""
    return data_dir() / "environments"


def control_prefix() -> Path:
    """The control environment's fixed place (envs.md § 1)."""
    return environments_dir() / CONTROL


def directory_sources() -> dict[str, tuple[Path, str]]:
    """Each directory with the rule that chose it, for `config path`."""
    out = {}
    for which, (xdg, fallback) in _XDG.items():
        own = VARIABLES[which]
        rule = own if os.environ.get(own) else (xdg if os.environ.get(xdg) else f"~/{fallback}")
        out[which] = (_resolve(which), rule)
    out["runtime"] = (runtime_dir(), VARIABLES["runtime"] if os.environ.get(VARIABLES["runtime"])
                      else "<state>/run/<host>")
    return out
