"""Every request checked, every response marked (web.md § 5), before any handler runs.

Token mode only: sign-in, TLS and `--no-auth` are not built yet (plan § 3, M7).
"""

from __future__ import annotations

import hmac
import re

from flask import Flask, Response, jsonify, request

from femkit.server.protocol import LOOPBACK, Listen

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

OPEN = ("/api/health",)  # the one /api route that needs no token


def refusal(status: int, kind: str, message: str) -> Response:
    response = jsonify({"refused": kind, "message": message, "next": []})
    response.status_code = status
    return response


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
            return refusal(403, "host", "this server does not answer to that host name")
        if request.method not in ("GET", "HEAD"):
            if request.mimetype != "application/json":
                return refusal(415, "content-type", "a write carries Content-Type: application/json")
            origin = request.headers.get("Origin")
            if origin is not None and origin != f"http://{host}":
                return refusal(403, "origin", "a write from another origin is refused")
        if request.path.startswith("/api/") and request.path not in OPEN:
            given = request.headers.get("Authorization", "")
            scheme, _, value = given.partition(" ")
            if scheme != "Bearer" or not hmac.compare_digest(value.encode(), token.encode()):
                return refusal(401, "token", "this server needs its access token: open the address "
                                             "`serve start` printed, or send Authorization: Bearer <token>")
        return None

    @app.after_request
    def mark(response: Response) -> Response:
        for name, value in HEADERS.items():
            response.headers[name] = value
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(413)
    def too_large(_):
        return refusal(413, "size", f"a request body is at most {JSON_LIMIT // 1024} KiB")

    @app.errorhandler(404)
    def not_found(_):
        return refusal(404, "route", "no such route")

    @app.errorhandler(405)
    def wrong_method(_):
        return refusal(405, "method", "this route does not take that method")
