"""The envs domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.core.commandline import ARGUMENT
from femkit.core.schema import Model
from pydantic import Field


class ListRequest(Model):
    """No inputs."""


class CleanRequest(Model):
    """One environment to remove."""

    name: str = Field(description="the environment", json_schema_extra=ARGUMENT)


class LogRequest(Model):
    """One environment."""

    name: str = Field(description="the environment", json_schema_extra=ARGUMENT)


class InstallRequest(Model):
    """Environments to install; an environment already ready is left alone unless --clean."""

    names: list[str] = Field(default_factory=list, description="environments", json_schema_extra=ARGUMENT)
    all: bool = Field(default=False, description="every environment whose definition has default = true")
    clean: bool = Field(default=False, description="remove and rebuild, discarding the saved lock")


class PlanRequest(Model):
    """Environments whose install is shown."""

    names: list[str] = Field(default_factory=list, description="environments", json_schema_extra=ARGUMENT)
    all: bool = Field(default=False, description="every environment whose definition has default = true")
    clean: bool = Field(default=False, description="as `install --clean` would")


class ValidateRequest(Model):
    """One environment to validate."""

    name: str = Field(description="the environment", json_schema_extra=ARGUMENT)
    gpu: bool = Field(default=False, description="run the GPU checks and the checks they agree with, "
                      "instead of the CPU checks")


# ------------------------------------------------------------------ the operations these requests are for

ENV_CLEAN = Verb("env.clean", CleanRequest)
ENV_INSTALL = Verb("env.install", InstallRequest)
ENV_LIST = Verb("env.list", ListRequest)
ENV_LOG = Verb("env.log", LogRequest)
ENV_PLAN = Verb("env.plan", PlanRequest)
ENV_VALIDATE = Verb("env.validate", ValidateRequest)
