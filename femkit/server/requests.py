"""The server domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

import socket
from femkit.core.schema import Model
from pydantic import Field, model_validator


class ServeRequest(Model):
    """Where the server listens, and how its log is kept."""

    port: int = Field(8000, ge=1, le=65535, description="the TCP port on 127.0.0.1")
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


class TargetRequest(Model):
    """Which server."""

    port: int = Field(8000, ge=1, le=65535, description="the server on this TCP port")
    socket: bool = Field(False, description="the server on the Unix socket")
    force: bool = Field(False, description="even while the server's child holds an operation's lock "
                                           "(an install started from the page), which then stops with it")


class StatusRequest(Model):
    """Every server of this account, or the one named."""

    port: int | None = Field(None, ge=1, le=65535, description="only the server on this TCP port")
    socket: bool = Field(False, description="only the server on the Unix socket")


class BuildRequest(Model):
    """How to build the page."""

    relock: bool = Field(False, description="solve frontend/package-lock.json again from package.json first, "
                                            "and write it into the checkout")


# ------------------------------------------------------------------ the operations these requests are for

SERVE_FOREGROUND = Verb("serve.foreground", ServeRequest)
SERVE_RESTART = Verb("serve.restart", TargetRequest)
SERVE_START = Verb("serve.start", ServeRequest)
SERVE_STATUS = Verb("serve.status", StatusRequest)
SERVE_STOP = Verb("serve.stop", TargetRequest)
WEB_BUILD = Verb("web.build", BuildRequest)
