"""The job request's resources (jobs.md § 2): what one calculation asks of a machine.

A prepared case's study binds them per environment (models.md § 5); the job request
`job.toml` that holds them is built with local jobs (plan § 3, M3).
"""

from __future__ import annotations

import re

from pydantic import Field, field_validator

from femkit.core.schema import Model

WALL = re.compile(r"(\d+-)?\d{1,2}:\d{2}:\d{2}")   # [D-]HH:MM:SS: never two parts, which a scheduler reads as MM:SS
MEMORY = re.compile(r"[1-9]\d*[KMGT]")             # a whole number with its unit: a bare one is megabytes to SLURM


class Resources(Model):
    """What a job asks for; nothing about a machine (jobs.md § 2)."""

    ranks: int = Field(ge=1, description="MPI ranks")
    threads: int = Field(ge=1, description="threads per rank")
    gpus: int = Field(ge=0, description="GPUs per node, a count; 0 states that none is used")
    wall: str | None = Field(default=None, description="wall time, `[D-]HH:MM:SS`; read on a machine with a scheduler")
    memory: str | None = Field(default=None, description="memory per node, a whole number with `K`, `M`, `G` or `T`; "
                                                         "read on a machine with a scheduler")
    partition: str | None = Field(default=None, description="the queue, on a machine with a scheduler")
    qos: str | None = Field(default=None, description="the quality of service, where the record lists one")

    @field_validator("wall")
    @classmethod
    def _wall(cls, value: str | None) -> str | None:
        if value is not None and not WALL.fullmatch(value):
            raise ValueError(f"{value!r} is not [D-]HH:MM:SS (at least three parts: `04:30` would be four minutes "
                             "and thirty seconds)")
        return value

    @field_validator("memory")
    @classmethod
    def _memory(cls, value: str | None) -> str | None:
        if value is not None and not MEMORY.fullmatch(value):
            raise ValueError(f"{value!r} is not a whole number with K, M, G or T (`16G`)")
        return value
