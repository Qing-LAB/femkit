"""The envs domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.core.commandline import ARGUMENT
from femkit.core.schema import Model
from pydantic import Field

#: An argument naming environments, by their names in the definitions (core.md § 2, `choices`).
ENVIRONMENTS = {**ARGUMENT, "choices": "environments"}


class ListRequest(Model):
    """No inputs."""


class CleanRequest(Model):
    """One environment to remove."""

    name: str = Field(description="the environment", json_schema_extra=ENVIRONMENTS)


class LogRequest(Model):
    """One environment."""

    name: str = Field(description="the environment", json_schema_extra=ENVIRONMENTS)


class InstallRequest(Model):
    """Environments to install; an environment already ready is left alone unless --clean."""

    names: list[str] = Field(default_factory=list, description="the environments to install",
                             json_schema_extra=ENVIRONMENTS)
    all: bool = Field(default=False, description="every environment whose definition has default = true")
    clean: bool = Field(default=False, description="remove and rebuild, discarding the saved lock")


class ValidateRequest(Model):
    """One environment to validate."""

    name: str = Field(description="the environment", json_schema_extra=ENVIRONMENTS)
    gpu: bool = Field(default=False, description="run the GPU checks and the checks they agree with, "
                      "instead of the CPU checks")


# ------------------------------------------------------------------ the operations these requests are for

ENV_CLEAN = Verb("env.clean", CleanRequest)
ENV_INSTALL = Verb("env.install", InstallRequest)
ENV_LIST = Verb("env.list", ListRequest)
ENV_LOG = Verb("env.log", LogRequest)
ENV_VALIDATE = Verb("env.validate", ValidateRequest)
