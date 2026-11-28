"""The jobs domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.config.requests import InitRequest
from femkit.core.commandline import ARGUMENT
from femkit.core.locks import SUBJECT
from femkit.core.schema import Model, as_path
from typing import Annotated, Any

from pydantic import Field, model_validator

#: A machine record's name: a file name in machines/, nothing more, and a lock subject's name
#: (`machine-<name>`, core.md § 5) — the subjects' own grammar (jobs.md § 9.2).
MACHINE_NAME = f"^{SUBJECT.pattern}$"
#: What `--set` may declare: where a scheduler command is, never a measured fact (jobs.md § 9.2).
DECLARATION = r"^scheduler\.(commands|probe)\.[a-z_]+=.+$"
#: The record of the machine a command runs on, always (jobs.md § 9.3): the probe's own, never named.
LOCAL = "local"


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

    @model_validator(mode="after")
    def _not_local(self) -> "ProbeRequest":
        if self.name == LOCAL:
            raise ValueError(f"`{LOCAL}` is this machine's own record: write it with `job probe --write`, no --name")
        return self


class MachinesRequest(Model):
    """One record by name, or every record."""

    name: str | None = Field(default=None, pattern=MACHINE_NAME, description="the record to show; without it, "
                                                                            "every record", json_schema_extra=ARGUMENT)


# A calculation folder, as a command names it (jobs.md § 8): each request its own field.
def folder() -> Any:
    return as_path("the calculation folder: its path, from the folder the command runs in", "folder",
                   extra={**ARGUMENT, "doc": "jobs.md § 1"})


#: Which record a command takes where it names none (jobs.md § 3, step 2): the rule every request
#: field naming a target states in its help, written once here.
TARGET_RULE = "without it, `local` when no record of another machine is there"


def target(what: str, more: str = "", **extra: Any) -> Any:
    """A request field naming the machine record ``what`` is for, by its name: its help that and the
    one rule a record is chosen by where it names none (`TARGET_RULE`), then ``more``."""
    return Field(default=None, pattern=MACHINE_NAME, description=f"{what}; {TARGET_RULE}{more}",
                 json_schema_extra=extra or None)


class PrepareRequest(Model):
    """A calculation or launch folder, and the machine to prepare it for."""

    dir: str = folder()
    target: str | None = target("the machine record to prepare it for at its first prepare",
                                ". A later prepare reads the folder's own copy", doc="jobs.md § 3")


class LaunchRequest(Model):
    """A prepared calculation or launch folder, and how to wait for it."""

    dir: str = folder()
    foreground: bool = Field(default=False, description="wait for the job here, in this terminal, which Ctrl-C "
                                                        "stops; exit 0 when every run finished, 1 otherwise",
                             json_schema_extra={"doc": "jobs.md § 5"})
    in_sequence: str | None = as_path("the launch folder of the sequence whose job this launch runs inside: typed by "
                                      "a sequence's walk alone", "folder", extra={"doc": "jobs.md § 4.2"}, default=None)
    in_job: str | None = Field(default=None, description="the job this launch runs inside: typed by a sequence's "
                                                         "walk alone", json_schema_extra={"doc": "jobs.md § 4.2"})


class StatusRequest(Model):
    """A calculation or launch folder."""

    dir: str = folder()


class ListRequest(Model):
    """No inputs."""


class CancelRequest(Model):
    """A job `job list` shows."""

    id: str = Field(description="the job, as `job list` names it", json_schema_extra={**ARGUMENT, "doc": "jobs.md § 5.4"})


class DoctorRequest(Model):
    """No inputs."""


class BootstrapRequest(InitRequest):
    """config init's values, and whether to rebuild every environment."""

    clean: bool = Field(default=False, description="remove and rebuild every default environment")


# ------------------------------------------------------------------ the operations these requests are for

DOCTOR = Verb("doctor", DoctorRequest, on_machine=True, effect="reads")
ENV_BOOTSTRAP = Verb("env.bootstrap", BootstrapRequest, on_machine=True, effect="changes")
JOB_MACHINES = Verb("job.machines", MachinesRequest, on_machine=True, effect="reads")
JOB_PROBE = Verb("job.probe", ProbeRequest, on_machine=True, effect="changes")
JOB_PREPARE = Verb("job.prepare", PrepareRequest, on_machine=False, effect="changes")
JOB_LAUNCH = Verb("job.launch", LaunchRequest, on_machine=True, effect="changes")
JOB_STATUS = Verb("job.status", StatusRequest, on_machine=False, effect="reads")
JOB_LIST = Verb("job.list", ListRequest, on_machine=True, effect="reads")
JOB_CANCEL = Verb("job.cancel", CancelRequest, on_machine=True, effect="changes")
