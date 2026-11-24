"""Does the server at an address answer, as itself? (web.md § 5, the health route.)

The client sends a fresh nonce and checks the HMAC the server answers with, keyed
by the server's token: an answer from another program on the address is told
apart without the token ever being sent.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import secrets
import socket

from femkit.server.protocol import LOOPBACK, Listen


def proof(token: str, nonce: str) -> str:
    """What the server answers to ``nonce``: the one formula both sides use."""
    return hmac.new(token.encode(), nonce.encode(), hashlib.sha256).hexdigest()


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__(LOOPBACK, timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def connection(listen: Listen, timeout: float) -> http.client.HTTPConnection:
    """A connection straight to the server, through no proxy the shell names."""
    if listen.socket:
        return _UnixConnection(listen.socket, timeout)
    return http.client.HTTPConnection(LOOPBACK, listen.port, timeout=timeout)


def ask(listen: Listen, token: str, *, timeout: float = 5.0) -> tuple[bool, str]:
    """``(answers as itself, one line saying so)``."""
    nonce = secrets.token_hex(16)
    conn = connection(listen, timeout)
    try:
        conn.request("GET", f"/api/health?nonce={nonce}")
        response = conn.getresponse()
        body = response.read()
    except (OSError, http.client.HTTPException) as exc:
        return False, f"no answer at {listen.describe()} within {timeout:g} s ({exc})"
    finally:
        conn.close()
    try:
        answered = json.loads(body)["proof"]
    except (ValueError, KeyError, TypeError):
        return False, f"{listen.describe()} answered, but not as a femkit server (HTTP {response.status})"
    if not isinstance(answered, str) or not hmac.compare_digest(answered, proof(token, nonce)):
        return False, f"{listen.describe()} answered with another server's proof: not this server"
    return True, "answers with this server's token"
