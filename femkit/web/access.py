"""Every request checked, every response marked (web.md § 5), before any handler runs.

Token mode only: sign-in, TLS and `--no-auth` are not built yet (plan § 4, M7's remainder).
"""

from __future__ import annotations

import hmac
import re

from flask import Flask, Response, jsonify, request

from femkit.core import view
from femkit.core.errors import Refusal, Refused, UsageError
from femkit.server.protocol import HEALTH_ROUTE, LOOPBACK, Listen

JSON_LIMIT = 1024 * 1024  # bytes: a request body larger is refused, 413

HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; "
                               "base-uri 'none'; object-src 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

OPEN = (HEALTH_ROUTE,)  # the one /api route that needs no token

# Each HTTP error flask raises before or in a route — routing, reading the body, sending a file —
# as the door's refusal: its code and what it says (web.md § 5). Any other is a defect.
HTTP_ERRORS = {
    400: ("body", "the request's body did not arrive whole, or cannot be read"),
    404: ("route", "no such route"),
    405: ("method", "this route does not take that method"),
    413: ("size", f"a request body is at most {JSON_LIMIT // 1024} KiB"),
    416: ("range", "the range asked for is not in the file"),
}


def answer(exc: Refusal, status: int) -> Response:
    """A refusal as its HTTP answer: the vocabulary's one refusal answer (web.md § 7), with
    ``status``."""
    response = jsonify(view.RefusalAnswer.of(exc).model_dump(mode="json", by_alias=True))
    response.status_code = status
    return response


def refusal(status: int, code: str, subject: str | None, message: str) -> Response:
    """A refusal at the door (web.md § 5): who may not ask (401, 403) is `Refused`, a request
    the door cannot take a `UsageError`; ``code`` says which, ``subject`` what it is about."""
    kind = Refused if status in (401, 403) else UsageError
    return answer(kind(message, code=code, subject=subject), status)


def host_allowed(host: str, listen: Listen) -> bool:
    """The `Host` header names this server: on TCP its address and port, printed as
    127.0.0.1; on a Unix socket, whose local port the person picks when forwarding it,
    127.0.0.1, localhost or [::1] with any port."""
    if listen.socket:
        return re.fullmatch(r"(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?", host) is not None
    return host == f"{LOOPBACK}:{listen.port}"


def install(app: Flask, token: str, listen: Listen) -> None:
    app.config["MAX_CONTENT_LENGTH"] = JSON_LIMIT

    @app.before_request
    def check():
        host = request.headers.get("Host", "")
        if not host_allowed(host, listen):
            return refusal(403, "host", "Host", "this server does not answer to that host name")
        if request.method not in ("GET", "HEAD"):
            if request.mimetype != "application/json":
                return refusal(415, "content-type", "Content-Type", "a write carries Content-Type: application/json")
            origin = request.headers.get("Origin")
            if origin is not None and origin != f"http://{host}":
                return refusal(403, "origin", "Origin", "a write from another origin is refused")
        if request.path.startswith("/api/") and request.path not in OPEN:
            given = request.headers.get("Authorization", "")
            scheme, _, value = given.partition(" ")
            if scheme != "Bearer" or not hmac.compare_digest(value.encode(), token.encode()):
                return refusal(401, "token", "Authorization", "this server needs its access token: open the "
                                                              "address `serve start` printed, or send "
                                                              "Authorization: Bearer <token>")
        return None

    @app.after_request
    def mark(response: Response) -> Response:
        for name, value in HEADERS.items():
            response.headers[name] = value
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
