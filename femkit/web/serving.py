"""The HTTP server the child runs (web.md § 4): on the socket its supervisor opened, with
a bounded pool of threads and a time limit for reading a request, so a slow or silent
client can neither stall nor exhaust it. No debugger or reloader is ever served."""

from __future__ import annotations

import os
import socket
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler

from femkit.server.protocol import LOOPBACK, Listen

THREADS = 16          # above the app's cap on event streams (app.STREAMS)
READ_TIMEOUT = 15.0   # seconds a connection may take to send a request, and stay idle


class _Handler(WSGIRequestHandler):
    """One line per request on stdout, which the supervisor writes to the log: method, path
    without its query, status, time — never a header, a token or a body (web.md § 4)."""

    server_version = "femkit"  # no version string reaches a response (web.md § 5)
    sys_version = ""

    def version_string(self) -> str:
        return "femkit"

    def log_request(self, code="-", size="-") -> None:
        path = (getattr(self, "path", "") or "").split("?", 1)[0].encode("unicode_escape").decode("ascii")
        elapsed = (time.monotonic() - getattr(self, "_began", time.monotonic())) * 1000
        print(f"[serve-request] {time.strftime('%Y-%m-%dT%H:%M:%S%z')} {getattr(self, 'command', None) or '-'} "
              f"{path or '-'} {getattr(code, 'value', code)} {elapsed:.0f} ms", flush=True)

    def log_error(self, format: str, *args) -> None:
        print(f"[serve-error] {time.strftime('%Y-%m-%dT%H:%M:%S%z')} " + (format % args), flush=True)

    def log_message(self, format: str, *args) -> None:
        pass  # werkzeug's own lines would carry the full request line

    def handle_one_request(self) -> None:
        """A request's line and headers must all arrive within READ_TIMEOUT, not each read:
        a client sending one byte at a time would otherwise hold a thread for ever."""
        self._began = time.monotonic()
        self._deadline = threading.Timer(READ_TIMEOUT, self._expire)
        self._deadline.daemon = True
        self._deadline.start()
        try:
            super().handle_one_request()
        finally:
            self._deadline.cancel()

    def parse_request(self) -> bool:
        parsed = super().parse_request()
        self._deadline.cancel()  # the headers are in: the body and the answer have their own limits
        return parsed

    def _expire(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class BoundedServer(BaseWSGIServer):
    multithread = True  # HTTP/1.1, as werkzeug enables for a threaded server

    def __init__(self, listen: Listen, app, fd: int) -> None:
        self.listen_on = listen
        self.pool = ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix="request")
        host = f"unix://{listen.socket}" if listen.socket else LOOPBACK
        super().__init__(host, listen.port or 0, app, handler=_Handler, fd=fd)

    def verify_request(self, request, client_address) -> bool:
        """On a Unix socket, only its owner's processes are served (`SO_PEERCRED`)."""
        if self.listen_on.socket:
            creds = request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _, uid, _ = struct.unpack("3i", creds)
            if uid != os.getuid():
                print(f"[serve-error] a connection from uid {uid} refused", flush=True)
                return False
        return True

    def process_request(self, request, client_address) -> None:
        request.settimeout(READ_TIMEOUT)
        self.pool.submit(self._serve, request, client_address)

    def _serve(self, request, client_address) -> None:
        try:
            self.finish_request(request, client_address)
        except Exception:  # noqa: BLE001 — one connection's failure never ends the server
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def handle_error(self, request, client_address) -> None:
        print(f"[serve-error] {time.strftime('%Y-%m-%dT%H:%M:%S%z')} {sys.exc_info()[1]!r}", flush=True)

    def close(self) -> None:
        """After `serve_forever` returns: no new request starts; those running are left to end."""
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.server_close()
