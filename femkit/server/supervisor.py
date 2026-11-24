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
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import BinaryIO, Callable

from femkit.core import dirs, locks
from femkit.core.process import GRACE, Identity, identify
from femkit.server import protocol
from femkit.server.protocol import Listen, LogRoll, Pidfile, event_line


MODULE = "femkit.server.supervisor"   # started as `python -m femkit.server.supervisor`


def argv(python: str, web_python: str, listen: Listen, fds: dict, hold: str, log_max_bytes: int,
         log_keep: int) -> list[str]:
    """The supervisor's command, as `serve start` runs it and its plan shows it: ``fds`` the
    descriptors it inherits — the listening socket, the server's lock, the web environment's use."""
    return [python, "-m", MODULE, "--python", web_python, "--listen", json.dumps(listen.as_json()),
            "--fd", str(fds["socket"]), "--lock-fd", str(fds["lock"]), "--use-fd", str(fds["use"]),
            "--hold", hold, "--log-max-bytes", str(log_max_bytes), "--log-keep", str(log_keep)]


def child_argv(python: str, listen: Listen, fd: int | str, parent: int | str) -> list[str]:
    """The web application's command, on the web environment's ``python``: it serves on the
    inherited socket ``fd`` and ends when ``parent`` does (web.md § 4)."""
    return [python, "-m", protocol.CHILD_MODULE, "--fd", str(fd), "--parent", str(parent),
            "--listen", json.dumps(listen.as_json())]


def remove_files(listen: Listen) -> None:
    """The pidfile, the token and the socket: what `stop` and a supervisor that gives up remove."""
    paths = [protocol.pidfile(listen.name), protocol.token_file(listen.name)]
    if listen.socket:
        paths.append(Path(listen.socket))
    for path in paths:
        path.unlink(missing_ok=True)


def supervise(listen: Listen, fd: int, python: str, *, log_max_bytes: int, log_keep: int,
              echo: BinaryIO | None = None, on_child: Callable[[Identity], None] | None = None) -> int:
    """Run the child until a stop, a child that exits by itself, or two deaths by a signal
    within the flap window. Returns the supervisor's exit code. ``echo``: a terminal the
    child's output also goes to (`serve foreground`); ``on_child``: told each child started."""
    roll = LogRoll(protocol.log_file(listen.name), max_bytes=log_max_bytes, keep=log_keep)
    me = identify(os.getpid())
    assert me is not None
    state: dict = {"child": None, "restart": False, "stop": False}

    def note(message: str) -> None:
        line = event_line("supervisor", message).encode()
        roll.write(line)
        if echo is not None:
            echo.write(line)
            echo.flush()

    def end_child() -> None:
        """SIGTERM now, SIGKILL after the grace: a child held up by a request in flight never
        holds up a stop or a restart."""
        child = state["child"]
        if child is None or child.poll() is not None:
            return
        child.terminate()
        timer = threading.Timer(GRACE, lambda: child.poll() is None and child.kill())
        timer.daemon = True
        timer.start()

    def on_restart(signum, frame):
        state["restart"] = True
        end_child()

    def on_stop(signum, frame):
        state["stop"] = True
        end_child()

    signal.signal(signal.SIGHUP, on_restart)
    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGINT, on_stop)
    deaths: list[float] = []
    code = 0
    try:
        while not state["stop"]:
            state["restart"] = False
            child = subprocess.Popen(child_argv(python, listen, fd, me.pid), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, pass_fds=(fd,),
                                     start_new_session=True, cwd=dirs.checkout(),  # femkit, from the checkout
                                     env={**os.environ, "PYTHONNOUSERSITE": "1"})
            state["child"] = child
            who = identify(child.pid)
            Pidfile(me, who, dirs.host(), listen, echo is not None).write()
            note(f"child started: pid {child.pid}")
            if who is not None and on_child is not None:
                on_child(who)
            assert child.stdout is not None
            for chunk in iter(lambda: child.stdout.read1(65536), b""):
                roll.write(chunk)
                if echo is not None:
                    echo.write(chunk)
                    echo.flush()
            code = child.wait()
            state["child"] = None
            if state["stop"]:
                break
            if protocol.child_exit_action(code, asked=state["restart"]) == "exit":
                note(f"child exited with code {code} by itself; not respawned")
                return code or 1
            if state["restart"]:
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
        live = state["child"]
        if live is not None and live.poll() is None:
            live.terminate()
            try:
                live.wait(timeout=GRACE)
            except subprocess.TimeoutExpired:
                live.kill()
                live.wait()
        remove_files(listen)
        roll.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"python -m {MODULE}")
    parser.add_argument("--listen", required=True, help="where it listens, as JSON")
    parser.add_argument("--fd", type=int, required=True, help="the listening socket, inherited")
    parser.add_argument("--python", required=True, help="the web environment's Python, which runs the child")
    parser.add_argument("--lock-fd", type=int, required=True, help="the server's lock, inherited")
    parser.add_argument("--use-fd", type=int, required=True, help="the web environment's lock, held shared, inherited")
    parser.add_argument("--hold", required=True, help="what its locks' files name as their holder, and the "
                                                       "actions that end the hold, as JSON written by `serve start`")
    parser.add_argument("--log-max-bytes", type=int, required=True)
    parser.add_argument("--log-keep", type=int, required=True)
    args = parser.parse_args(argv)
    listen = Listen.from_json(json.loads(args.listen))
    by, next = json.loads(args.hold)
    for fd in (args.lock_fd, args.use_fd):  # held from here for as long as this process runs
        locks.adopt(fd, by, next)
    return supervise(listen, args.fd, args.python,
                     log_max_bytes=args.log_max_bytes, log_keep=args.log_keep)


if __name__ == "__main__":
    raise SystemExit(main())
