"""What the supervisor, its child and the `serve` verbs agree on (web.md § 4).

The supervisor imports this module, so it imports only the standard library and
the core's file and process building blocks: a change that breaks the web
application or a domain must leave the supervisor running.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from pathlib import Path

from femkit.core import clock, dirs
from femkit.core.persist import open_private, read_bytes, read_json, remove, write_json
from femkit.core.process import Identity

SOCKET_NAME = "sock"          # <name> of a server on a Unix socket; a TCP server's is its port
LOOPBACK = "127.0.0.1"        # printed and bound as this, never `localhost` (web.md § 5)
SOCKET_PATH_MAX = 107         # bytes a Unix socket's path may hold, its terminating NUL aside
FLAP_WINDOW = 30.0            # two deaths by a signal within this many seconds: the supervisor gives up
CHILD_MODULE = "femkit.web"   # what the supervisor runs
HEALTH_ROUTE = "/api/health"  # what `start` and `status` ask; it needs no token, and an answer is never logged


def target(name: str) -> dict:
    """How a request names the server called ``name``: its port, or its socket."""
    return {"socket": True} if name == SOCKET_NAME else {"port": int(name)}


def subject(name: str) -> str:
    """The server's lock subject (core.md § 5): host-keyed, as its runtime folder is."""
    return f"server-{dirs.host()}-{name}"


def pidfile(name: str) -> Path:
    return dirs.runtime_dir() / f"serve-{name}.pid"


def token_file(name: str) -> Path:
    return dirs.runtime_dir() / f"serve-{name}.token"


def socket_path() -> Path:
    return dirs.runtime_dir() / f"serve-{SOCKET_NAME}.sock"


def log_file(name: str) -> Path:
    return dirs.state_dir() / "logs" / f"serve-{name}.log"


def supervisor_log(name: str) -> Path:
    """The detached supervisor's own output: what it says before or outside the server's log
    (a traceback, an import that failed)."""
    return dirs.state_dir() / "logs" / f"serve-{name}.supervisor.log"


def stacks_log(name: str) -> Path:
    return dirs.state_dir() / "logs" / f"serve-{name}.stacks.log"


# ------------------------------------------------------------------ the pidfile

@dataclass(frozen=True)
class Listen:
    """Where a server listens: TCP on the loopback address and a port, or a Unix socket."""

    port: int | None = None
    socket: str | None = None

    @classmethod
    def unix(cls) -> "Listen":
        """On femkit's Unix socket."""
        return cls(socket=str(socket_path()))

    @classmethod
    def named(cls, name: str) -> "Listen":
        """The server called ``name``, as `name` writes it: on the socket, or on that port."""
        return cls.unix() if name == SOCKET_NAME else cls(port=int(name))

    @property
    def name(self) -> str:
        return SOCKET_NAME if self.socket else str(self.port)

    def describe(self) -> str:
        return self.socket if self.socket else f"{LOOPBACK}:{self.port}"

    def as_json(self) -> dict:
        return {"socket": self.socket} if self.socket else {"port": self.port}

    @classmethod
    def from_json(cls, data: dict) -> "Listen":
        return cls(socket=data["socket"]) if data.get("socket") else cls(port=int(data["port"]))


@dataclass(frozen=True)
class Pidfile:
    """`serve-<name>.pid`: written by the supervisor at its start and at each child it starts."""

    supervisor: Identity
    child: Identity | None
    host: str
    listen: Listen
    foreground: bool

    def as_json(self) -> dict:
        return {"supervisor": self.supervisor.as_json(),
                "child": self.child.as_json() if self.child else None,
                "host": self.host, "listen": self.listen.as_json(), "foreground": self.foreground}

    @classmethod
    def from_json(cls, data: dict) -> "Pidfile":
        return cls(Identity.from_json(data["supervisor"]),
                   Identity.from_json(data["child"]) if data.get("child") else None,
                   str(data["host"]), Listen.from_json(data["listen"]), bool(data["foreground"]))

    def write(self) -> Path:
        return write_json(pidfile(self.listen.name), self.as_json(), private=True)


def read_pidfile(path: Path) -> Pidfile | None:
    """The pidfile at ``path``; None when it is absent or cannot be read as one."""
    try:
        return Pidfile.from_json(read_json(path))
    except (OSError, ValueError, KeyError, TypeError):
        return None


# ------------------------------------------------------------- respawn policy

def child_exit_action(code: int, *, asked: bool) -> str:
    """What the supervisor does when its child exits with ``code``: ``"respawn"`` after a
    death by a signal it did not send, or a restart it was asked for; ``"exit"`` otherwise —
    a child that exits by itself, with an error or not, cannot serve, and is not respawned."""
    if asked or code < 0:
        return "respawn"
    return "exit"


def flapping(deaths: list[float], now: float) -> bool:
    """Two deaths by a signal within FLAP_WINDOW seconds: respawning would be a loop."""
    return len([t for t in deaths if now - t <= FLAP_WINDOW]) >= 2


# -------------------------------------------------------------------- the log

def event_line(source: str, message: str) -> str:
    """One line of the server's log: `[serve-<source>] <time> <message>`, its moment as femkit
    writes one (core/clock.py); every writer of the log — the supervisor, the child — builds it here."""
    return f"[serve-{source}] {clock.stamp()} {message}\n"


class LogRoll:
    """The server's log: appended by one writer, 0600; over ``max_bytes`` it is compressed
    to `<log>.1.gz`, older archives shift up, and only ``keep`` archives are kept."""

    def __init__(self, path: Path, *, max_bytes: int, keep: int) -> None:
        self.path, self.max_bytes, self.keep = Path(path), int(max_bytes), int(keep)
        self._fh = open_private(self.path, "ab")

    def write(self, data: bytes) -> None:
        if not data:
            return
        self._fh.write(data)
        self._fh.flush()
        if self._fh.tell() >= self.max_bytes:
            self._rotate()

    def _archive(self, i: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{i}.gz")

    def _rotate(self) -> None:
        """The oldest archive gone, each other one place up, the log compressed into the first,
        and the log begun again — each file through the core (core.md § 4)."""
        self._fh.close()
        if self.keep > 0:
            remove(self._archive(self.keep))
            for i in range(self.keep - 1, 0, -1):
                held = read_bytes(self._archive(i))
                if held is not None:
                    _put(self._archive(i + 1), held)
            _put(self._archive(1), gzip.compress(read_bytes(self.path) or b""))
        self._fh = open_private(self.path, "wb")

    def close(self) -> None:
        self._fh.close()


def _put(path: Path, data: bytes) -> None:
    """``data`` as the whole of ``path``, readable by this account alone."""
    with open_private(path, "wb") as fh:
        fh.write(data)
