"""The jobs domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.config.requests import InitRequest
from femkit.core.commandline import ARGUMENT
from femkit.core.schema import Model
from pydantic import Field


class ProbeRequest(Model):
    """What to measure, and where to write it."""

    write: bool = Field(default=False, description="write the record", json_schema_extra={"doc": "jobs.md § 9.2"})
    name: str | None = Field(default=None, description="write machines/NAME.toml, the record another machine "
                                                        "prepares this one by; without it, machines/local.toml")
    set: list[str] = Field(default_factory=list, description="KEY=VALUE: declare where a scheduler command is, "
                                                             "e.g. scheduler.commands.submit=PATH")
    scheduler: str | None = Field(default=None, description="name the scheduler kind instead of detecting it")


class MachinesRequest(Model):
    """One record by name, or every record."""

    name: str | None = Field(default=None, description="the record to show; without it, every record",
                             json_schema_extra=ARGUMENT)


class DoctorRequest(Model):
    """No inputs."""


class BootstrapRequest(InitRequest):
    """config init's values, and whether to rebuild every environment."""

    clean: bool = Field(default=False, description="remove and rebuild every default environment")


# ------------------------------------------------------------------ the operations these requests are for

DOCTOR = Verb("doctor", DoctorRequest)
ENV_BOOTSTRAP = Verb("env.bootstrap", BootstrapRequest)
JOB_MACHINES = Verb("job.machines", MachinesRequest)
JOB_PROBE = Verb("job.probe", ProbeRequest)
