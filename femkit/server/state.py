"""The server state machine (api.md § 5.4), observed from its lock, its pidfile and the
processes the pidfile names. Observing starts no process and sends nothing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from femkit.core import dirs, locks, text
from femkit.core.errors import Busy, Refused
from femkit.core.states import Action, Machine, Rule
from femkit.server import protocol
from femkit.server.protocol import Pidfile


class ServerState(str, Enum):
    elsewhere = "elsewhere"
    stopped = "stopped"
    stale = "stale"
    running = "running"
    starting = "starting"


@dataclass(frozen=True)
class ServerFacts:
    name: str
    here: str                  # this host
    locked: bool               # the server's lock is held: its supervisor, or a start, runs
    pidfile_exists: bool
    pidfile: Pidfile | None    # None when absent or unreadable

    @property
    def supervisor_alive(self) -> bool:
        return self.pidfile is not None and self.pidfile.supervisor.alive()


def facts(name: str, *, mine: bool = False) -> ServerFacts:
    """``mine``: this process holds the server's lock (a start applying), so it reads it as free."""
    path = protocol.pidfile(name)
    return ServerFacts(name=name, here=dirs.host(),
                       locked=not mine and locks.is_held(protocol.subject(name)),
                       pidfile_exists=path.exists(), pidfile=protocol.read_pidfile(path))


def option(name: str) -> str:
    """How a command names this server: `--port 8000`, or `--socket`."""
    return "--socket" if name == protocol.SOCKET_NAME else f"--port {name}"


START = f"{text.PROG} serve start {{name}}"
STOP = f"{text.PROG} serve stop {{name}}"
RESTART = f"{text.PROG} serve restart {{name}}"
STATUS = f"{text.PROG} serve status {{name}}"

_start = Action("start", START)
_stop = Action("stop", STOP)
_restart = Action("restart", RESTART)

MACHINE: Machine[ServerFacts, ServerState] = Machine(
    name="server",
    states=ServerState,
    rules=(
        Rule("the pidfile was written on another host", ServerState.elsewhere,
             lambda f: f.pidfile is not None and f.pidfile.host != f.here),
        Rule("the lock is free, and no pidfile", ServerState.stopped,
             lambda f: not f.locked and not f.pidfile_exists),
        Rule("the lock is free, and a pidfile is left", ServerState.stale,
             lambda f: not f.locked),
        Rule("the lock is held, and the pidfile names its supervisor, alive", ServerState.running,
             lambda f: f.supervisor_alive),
        Rule("otherwise: the lock is held, and no pidfile names its holder yet", ServerState.starting),
    ),
    actions={
        ServerState.elsewhere: {},
        ServerState.stopped: {"start": _start, "stop": Action("nothing to do", "")},
        ServerState.stale: {"start": Action("remove the stale files, start", START),
                            "stop": Action("remove the stale files", STOP)},
        ServerState.running: {"stop": _stop, "restart": _restart, "status": Action("look", STATUS)},
        ServerState.starting: {},
    },
)


def observe(name: str) -> tuple[ServerFacts, ServerState]:
    f = facts(name)
    return f, MACHINE.observe(f)


def require(f: ServerFacts, state: ServerState, action: str) -> None:
    """Refused, with the commands the state allows; `elsewhere` and `starting` name why."""
    if state is ServerState.elsewhere and action not in MACHINE.allowed(state):
        raise Refused(f"the server {option(f.name)} runs on {f.pidfile.host}, not here: act on it there")
    if state is ServerState.starting and action not in MACHINE.allowed(state):
        raise Busy(f"the server {option(f.name)} is being started or stopped by another command; "
                   f"look again in a moment", (STATUS.replace("{name}", option(f.name)),))
    MACHINE.require(state, action, option(f.name))
