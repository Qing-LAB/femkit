"""The server's state (web.md § 4): observed, never stored, by the rules
`femkit/data/states/server.toml` declares over the facts gathered and named here — its lock, its
pidfile and the processes the pidfile names. Observing starts no process and sends nothing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from femkit.core import dirs, locks, states, view
from femkit.core.errors import Busy, Refused
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.server import protocol
from femkit.server.protocol import Pidfile
from femkit.server.requests import SERVE_STATUS


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


def facts(name: str) -> ServerFacts:
    """What is observed of the server ``name``; its lock as another process holds it — this
    process's own hold, a start applying, reads as free (core.md § 5)."""
    path = protocol.pidfile(name)
    return ServerFacts(name=name, here=dirs.host(),
                       locked=locks.is_held(protocol.subject(name)),
                       pidfile_exists=path.exists(), pidfile=protocol.read_pidfile(path))


BINDING = states.Binding("server", {
    "another_host": lambda f: f.pidfile is not None and f.pidfile.host != f.here,
    "locked": lambda f: f.locked,
    "pidfile": lambda f: f.pidfile_exists,
    "supervisor_alive": lambda f: f.supervisor_alive,
}, values={  # how a request names the server: its port, or its socket — the one the name is
    "port": lambda name: protocol.target(name).get("port"),
    "socket": lambda name: protocol.target(name).get("socket"),
}, reads=frozenset({"elsewhere", "stopped", "stale", "running", "starting"}))


def machine(ctx: Context) -> states.Machine:
    """The machine `femkit/data/states/server.toml` declares, bound to these facts (web.md § 4)."""
    return catalogue.machine(ctx, BINDING)


def label(name: str) -> str:
    """How a sentence names this server: `the server on port 8000`, or on the socket."""
    return "the server on the socket" if name == protocol.SOCKET_NAME else f"the server on port {name}"


def require(ctx: Context, f: ServerFacts, state: Enum, action: str) -> None:
    """Refused, with what the state allows; `elsewhere` and `starting` name why."""
    m = machine(ctx)
    if state is m.states.elsewhere and action not in m.allowed(state):
        raise Refused(f"{label(f.name)} runs on {f.pidfile.host}, not here: act on it there", code="elsewhere",
                      subject=f.name)
    if state is m.states.starting and action not in m.allowed(state):
        holder = locks.holders().get(protocol.subject(f.name))   # as the kernel's lock table names it
        by = f"process {holder}" if holder is not None else "another command"
        raise Busy(f"{label(f.name)} is being started or stopped by {by}; look again in a moment",
                   (view.command(SERVE_STATUS, **protocol.target(f.name)),), code="starting", subject=f.name)
    m.require(state, action, f.name, label(f.name))
