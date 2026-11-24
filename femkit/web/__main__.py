"""`python -m femkit.web`: the supervisor's child (web.md § 4). Started only by the
supervisor, never by a person: it serves on the socket the supervisor opened, reads its
token from the token file, and ends when its supervisor does."""

from __future__ import annotations

import argparse
import ctypes
import faulthandler
import json
import os
import signal
import sys
import threading

PR_SET_PDEATHSIG = 1


def _end_with_parent(parent: int) -> None:
    """Ends when the supervisor does: the kernel's parent-death signal, then a check that the
    parent had not already gone before it was set."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG)")
    if os.getppid() != parent:
        sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m femkit.web")
    parser.add_argument("--fd", type=int, required=True)
    parser.add_argument("--parent", type=int, required=True)
    parser.add_argument("--listen", required=True)
    args = parser.parse_args(argv)
    _end_with_parent(args.parent)

    from femkit.core.operations import Context
    from femkit.core.persist import open_private
    from femkit.server import protocol
    from femkit.server.protocol import Listen

    listen = Listen.from_json(json.loads(args.listen))
    stacks = open_private(protocol.stacks_log(listen.name), "a")
    faulthandler.register(signal.SIGUSR1, file=stacks, all_threads=True)  # `kill -USR1`: every thread's stack

    from femkit.config import settings
    from femkit.core.schema import DefinitionError
    try:
        settings.load(Context.from_process(), fresh=True)
    except (DefinitionError, OSError) as exc:  # a configuration that does not load: exit, not respawned
        print(protocol.event_line("error", f"config.toml does not load: {exc}"), end="", flush=True)
        return 2
    token = protocol.token_file(listen.name).read_text(encoding="utf-8").strip()

    from femkit.web.app import create_app
    from femkit.web.serving import BoundedServer

    app = create_app(token, listen)
    server = BoundedServer(listen, app, args.fd)

    def stop(signum, frame) -> None:  # streams end, no new request starts; the supervisor kills after its grace
        app.extensions["femkit.stopping"].set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(protocol.event_line("child", f"serving on {listen.describe()}, pid {os.getpid()}"), end="", flush=True)
    server.serve_forever()
    server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
