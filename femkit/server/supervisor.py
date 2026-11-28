"""The supervisor: runs the web application as its child, and outlives it (web.md § 4).

`python -m femkit.server.supervisor` when `serve start` detaches it; called in
place by `serve foreground`. It imports only the standard library and the
core's file and process building blocks, through `protocol`: a change that
breaks the application leaves the supervisor running, to start the fixed child
at the next `serve restart`.

Signals: `SIGHUP` replaces the child (`restart`); `SIGTERM`, and `SIGINT` in a
terminal, stop the child and the supervisor (`stop`, Ctrl-C).
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
import signal
import threading
import time
from pathlib import Path
from typing import BinaryIO, Callable

from femkit.core import dirs, locks, persist
from femkit.core.process import Child, Identity, identify
from femkit.server import protocol
from femkit.server.protocol import Listen, LogRoll, Pidfile, event_line


MODULE = "femkit.server.supervisor"   # started as `python -m femkit.server.supervisor`
TICK = 0.2   # seconds between two looks for a stop or a restart a signal asked for: a person sees no delay


def argv(python: str, web_python: str, module: str, listen: Listen, fds: dict, hold: str, log_max_bytes: int,
         log_keep: int) -> list[str]:
    """The supervisor's command, as `serve start` runs it and its plan shows it: ``module`` its
    child's, as its declaration names it (envs.md § 4.4); ``fds`` the descriptors it inherits — the
    listening socket, the server's lock, and each environment it uses, held shared: the web
    environment, which runs its child, and the control environment, which runs it."""
    uses = [word for fd in fds["use"] for word in ("--use-fd", str(fd))]
    return dirs.femkit_argv(python, MODULE, "--python", web_python, "--module", module,
                            "--listen", json.dumps(listen.as_json()),
                            "--fd", str(fds["socket"]), "--lock-fd", str(fds["lock"]), *uses,
                            "--hold", hold, "--log-max-bytes", str(log_max_bytes), "--log-keep", str(log_keep))


def child_env(start: Mapping[str, str]) -> dict[str, str]:
    """The child's environment: femkit's own program on the web environment's Python, from the clean
    start ``start`` (envs.md §§ 4.4, 7)."""
    return dirs.femkit_env(start)


def child_argv(python: str, module: str, listen: Listen, fd: int | str, parent: int | str) -> list[str]:
    """The web application's command, its ``module`` on the web environment's ``python``: it serves
    on the inherited socket ``fd`` and ends when ``parent`` does (web.md § 4)."""
    return dirs.femkit_argv(python, module, "--fd", str(fd), "--parent", str(parent),
                            "--listen", json.dumps(listen.as_json()))


def remove_files(listen: Listen) -> None:
    """The pidfile, the token and the socket: what `stop` and a supervisor that gives up remove."""
    paths = [protocol.pidfile(listen.name), protocol.token_file(listen.name)]
    if listen.socket:
        paths.append(Path(listen.socket))
    for path in paths:
        persist.remove(path)


def supervise(listen: Listen, fd: int, python: str, module: str, start: Mapping[str, str], *, log_max_bytes: int,
              log_keep: int, echo: BinaryIO | None = None, on_child: Callable[[Identity], None] | None = None) -> int:
    """Run the child until a stop, a child that exits by itself, or two deaths by a signal
    within the flap window. Returns the supervisor's exit code. ``start``: the clean start each
    child begins from (envs.md § 4.4) — `serve foreground`'s, or the detached supervisor's own
    environment, which `serve start` began so; ``echo``: a terminal the child's output also goes to
    (`serve foreground`); ``on_child``: told each child started."""
    roll = LogRoll(protocol.log_file(listen.name), max_bytes=log_max_bytes, keep=log_keep)
    me = identify(os.getpid())
    assert me is not None
    asked = {"restart": False, "stop": False}

    def write(data: bytes) -> None:
        roll.write(data)
        if echo is not None:
            echo.write(data)
            echo.flush()

    def note(message: str) -> None:
        write(event_line("supervisor", message).encode())

    def copy(child: Child) -> None:
        """The child's output into the log as it comes — read beside the main thread, so a
        child stopping is never held up by a full pipe."""
        for chunk in child.chunks():
            write(chunk)

    # A signal only says what was asked: the main thread acts on it, so the child is never
    # touched from inside a handler that may have interrupted a wait on it.
    def on_restart(signum, frame):
        asked["restart"] = True

    def on_stop(signum, frame):
        asked["stop"] = True

    signal.signal(signal.SIGHUP, on_restart)
    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGINT, on_stop)
    deaths: list[float] = []
    child: Child | None = None
    reader: threading.Thread | None = None
    try:
        while not asked["stop"]:
            asked["restart"] = False
            child = Child.start(child_argv(python, module, listen, fd, me.pid), keep_fds=(fd,), output="pipe",
                                cwd=dirs.checkout(),  # femkit, from the checkout
                                env=child_env(start))
            Pidfile(me, child.identity, dirs.host(), listen, echo is not None).write()
            note(f"child started: pid {child.identity.pid}")   # before its output: one writer at a time
            if on_child is not None:
                on_child(child.identity)
            reader = threading.Thread(target=copy, args=(child,), daemon=True)
            reader.start()
            code = child.wait(TICK)
            while code is None:   # a stop or a restart asked stops it: SIGTERM, SIGKILL after the grace
                code = child.stop() if asked["stop"] or asked["restart"] else child.wait(TICK)
            reader.join()
            child = reader = None
            if asked["stop"]:
                break
            if protocol.child_exit_action(code, asked=asked["restart"]) == "exit":
                note(f"child exited with code {code} by itself; not respawned")
                return code or 1
            if asked["restart"]:
                note("restart asked: starting a new child")
                continue
            now = time.monotonic()
            deaths.append(now)
            if protocol.flapping(deaths, now):
                note(f"child died by signal {-code}, the second time within {protocol.FLAP_WINDOW:g} s: "
                     "giving up")
                return 1
            note(f"child died by signal {-code}: starting a new child")
        note("stopped")
        return 0
    finally:
        if child is not None:
            child.stop()
        if reader is not None:
            reader.join()
        remove_files(listen)
        roll.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"python -m {MODULE}")
    parser.add_argument("--listen", required=True, help="where it listens, as JSON")
    parser.add_argument("--fd", type=int, required=True, help="the listening socket, inherited")
    parser.add_argument("--python", required=True, help="the web environment's Python, which runs the child")
    parser.add_argument("--module", required=True, help="the child's module, as its declaration names it")
    parser.add_argument("--lock-fd", type=int, required=True, help="the server's lock, inherited")
    parser.add_argument("--use-fd", type=int, action="append", required=True,
                        help="an environment's lock, held shared, inherited: once for each environment it uses")
    parser.add_argument("--hold", required=True, help="what its locks' files name as their holder, and the "
                                                       "actions that end the hold, as JSON written by `serve start`")
    parser.add_argument("--log-max-bytes", type=int, required=True)
    parser.add_argument("--log-keep", type=int, required=True)
    args = parser.parse_args(argv)
    listen = Listen.from_json(persist.json_value(args.listen))
    by, next = persist.json_value(args.hold)
    for fd in (args.lock_fd, *args.use_fd):  # held from here for as long as this process runs
        locks.adopt(fd, by, next)
    # started by `serve start` from the clean start, femkit's checkout its import path (envs.md § 4.4)
    begun = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return supervise(listen, args.fd, args.python, args.module, begun,
                     log_max_bytes=args.log_max_bytes, log_keep=args.log_keep)


if __name__ == "__main__":
    raise SystemExit(main())
