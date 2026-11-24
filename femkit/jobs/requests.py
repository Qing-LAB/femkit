"""The jobs domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.config.requests import InitRequest
from femkit.core.commandline import ARGUMENT
from femkit.core.locks import SUBJECT
from femkit.core.schema import Model
from typing import Annotated

from pydantic import Field

#: A machine record's name: a file name in machines/, nothing more, and a lock subject's name
#: (`machine-<name>`, core.md § 5) — the subjects' own grammar (jobs.md § 9.2).
MACHINE_NAME = f"^{SUBJECT.pattern}$"
#: What `--set` may declare: where a scheduler command is, never a measured fact (jobs.md § 9.2).
DECLARATION = r"^scheduler\.(commands|probe)\.[a-z_]+=.+$"


class ProbeRequest(Model):
    """What to measure, and where to write it."""

    write: bool = Field(default=False, description="write the record", json_schema_extra={"doc": "jobs.md § 9.2"})
    name: str | None = Field(default=None, pattern=MACHINE_NAME,
                             description="write machines/NAME.toml, the record another machine prepares this "
                                         "one by; without it, machines/local.toml")
    set: list[Annotated[str, Field(pattern=DECLARATION)]] = Field(
        default_factory=list, description="scheduler.commands.ROLE=PATH or scheduler.probe.ROLE=PATH: declare "
                                          "where a scheduler command is")
    scheduler: str | None = Field(default=None, description="name the scheduler kind instead of detecting it")


class MachinesRequest(Model):
    """One record by name, or every record."""

    name: str | None = Field(default=None, pattern=MACHINE_NAME, description="the record to show; without it, "
                                                                            "every record", json_schema_extra=ARGUMENT)


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
