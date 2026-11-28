"""The server domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.core.schema import Model
from pydantic import Field, model_validator


DEFAULT_PORT = 8000


class ServeRequest(Model):
    """Where the server listens, and how its log is kept."""

    port: int | None = Field(None, ge=1, le=65535, description=f"the TCP port on 127.0.0.1; {DEFAULT_PORT} when not given")
    socket: bool = Field(False, description="listen on a Unix socket only this account can open — the default "
                                            "on a cluster's login node")
    tcp: bool = Field(False, description="listen on TCP, even on a cluster's login node")
    log_max_mb: int = Field(20, ge=1, description="past this size the log is compressed and a new one begun")
    log_keep: int = Field(5, ge=0, description="how many compressed logs are kept")

    @model_validator(mode="after")
    def _one_way(self) -> "ServeRequest":
        if self.socket and self.tcp:
            raise ValueError("--socket and --tcp exclude each other")
        return self


def _one_server(req):
    """`--socket` names the server on the Unix socket, `--port` one on TCP: a request naming both
    is refused by its schema, never one of them dropped (web.md § 4)."""
    if req.socket and req.port is not None:
        raise ValueError("--socket and --port name two servers: give one")
    return req


class TargetRequest(Model):
    """Which server."""

    port: int | None = Field(None, ge=1, le=65535, description=f"the server on this TCP port; {DEFAULT_PORT} when not given")
    socket: bool = Field(False, description="the server on the Unix socket")
    force: bool = Field(False, description="even while the server's child holds an operation's lock "
                                           "(an install started from the page), which then stops with it")
    _one = model_validator(mode="after")(_one_server)


class StatusRequest(Model):
    """Every server of this account, or the one named."""

    port: int | None = Field(None, ge=1, le=65535, description="only the server on this TCP port")
    socket: bool = Field(False, description="only the server on the Unix socket")
    _one = model_validator(mode="after")(_one_server)


class BuildRequest(Model):
    """How to build the page."""

    relock: bool = Field(False, description="solve frontend/package-lock.json again from package.json first, "
                                            "and write it into the checkout")


# ------------------------------------------------------------------ the operations these requests are for

SERVE_FOREGROUND = Verb("serve.foreground", ServeRequest, on_machine=True, effect="changes")
SERVE_RESTART = Verb("serve.restart", TargetRequest, on_machine=True, effect="changes")
SERVE_START = Verb("serve.start", ServeRequest, on_machine=True, effect="changes")
SERVE_STATUS = Verb("serve.status", StatusRequest, on_machine=True, effect="reads")
SERVE_STOP = Verb("serve.stop", TargetRequest, on_machine=True, effect="changes")
WEB_BUILD = Verb("web.build", BuildRequest, on_machine=True, effect="changes")
