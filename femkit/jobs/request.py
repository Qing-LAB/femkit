"""The job request, `job.toml` (jobs.md § 2): what one calculation asks of a machine, and nothing
about a machine. The model is the one authority for every field (`docs/reference/`).

A calculation folder's request runs one command in one environment — and, for a stage, names
femkit's programs it runs, what the run must leave, the check that judges it, and the files it
reads where another calculation folder made them. A launch folder's request runs other folders in
one job: a batch's `members`, a sequence's `sequence` (jobs.md § 1.2). Every path is relative to
the folder that holds the request, so a project moved whole keeps working.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated, Any

from pydantic import AfterValidator, Field, ValidationInfo, field_validator, model_validator

from femkit.core.schema import Model, check_arguments, field_extras, matching, parsed, refuse
from femkit.core.units import MEMORY_LETTERS

WALL = re.compile(r"(\d+-)?\d{1,2}:\d{2}:\d{2}")   # [D-]HH:MM:SS: never two parts, which a scheduler reads as MM:SS
#: A request's memory: a whole number with its letter, the unit table's binary multiple of the byte
#: it means, as a scheduler counts memory (`MEMORY_LETTERS`; jobs.md § 2) — a bare one is megabytes to
#: SLURM.
MEMORY = re.compile(rf"[1-9]\d*[{''.join(MEMORY_LETTERS)}]")
LETTERS = ", ".join(f"`{letter}`" for letter in list(MEMORY_LETTERS)[:-1]) + f" or `{list(MEMORY_LETTERS)[-1]}`"

# A path's step: letters, digits and `_ + = , . -`. Nothing a shell, a JSON text or a scheduler's
# header would have to quote, so a run script names it as written.
_STEP = r"[A-Za-z0-9_+=,.-]+"
#: A file of the calculation folder or of a run, by its path from it: never leaving it.
FILE = re.compile(rf"{_STEP}(?:/{_STEP})*")
#: A program of femkit's, by its name in femkit's programs' folder.
PROGRAM = re.compile(_STEP)
#: Another calculation folder, by its path from this one: it may step up, `../geometry/3f2a…`.
FOLDER = re.compile(rf"{_STEP}(?:/{_STEP})*")
#: A job's name, as a scheduler shows it.
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

#: The placeholders a command and a check take (core.md § 2.1): `{python}`, the environment's own
#: python (jobs.md § 2; § 4, block 9); `{share:FILE}`, the path from the run of a file it shares.
PYTHON = "python"
SHARE = "share"
PLACEHOLDERS = frozenset({PYTHON, SHARE})
#: The validation context's key for the names a request's files may not take: the catalogue's own
#: (jobs/layout.py), given by whoever loads a request.
RESERVED = "reserved"


def wall_seconds(wall: str) -> int | None:
    """A wall time `[D-]HH:MM:SS` in seconds — a request's, or a queue's limit in a scheduler's
    spelling where it is this one; None for any other spelling, which is then not counted."""
    if not WALL.fullmatch(wall):
        return None
    days, _, clock = wall.rpartition("-")
    h, m, s = (int(x) for x in clock.split(":"))
    return (int(days) if days else 0) * 86400 + h * 3600 + m * 60 + s


def _inside(text: str) -> str:
    if any(p in (".", "..") for p in text.split("/")):
        raise ValueError(f"{text!r} leaves the folder: a file is named by its path inside it, with no `.` or `..`")
    return text


def _folder(text: str) -> str:
    if "." in text.split("/"):
        raise ValueError(f"{text!r} holds a `.` step: name the folder by its path, `../geometry/<id>`")
    return text


File = Annotated[str, matching(FILE), AfterValidator(_inside)]
Folder = Annotated[str, matching(FOLDER), AfterValidator(_folder)]


#: The roles a `[resources]` field declares on itself (jobs.md § 2), each read where it says, never
#: a list of names written again: `shared`, a job's and every member's inside it alike — what a
#: member states as its job does, and a stage inside a job takes from it; `scheduler`, read only on
#: a machine with a scheduler — said not read on one without; `queue`, one of the two that name the
#: target's queue, refused on their own where it is not stated.
SHARED, SCHEDULER, QUEUE = "shared", "scheduler", "queue"
ROLES = "roles"   # the field's annotation that holds them


def _roles(*roles: str) -> dict:
    return {ROLES: list(roles)}


class Resources(Model):
    """What a job asks for; nothing about a machine (jobs.md § 2)."""

    ranks: int = Field(ge=1, description="MPI ranks")
    threads: int = Field(ge=1, description="threads per rank")
    gpus: int = Field(ge=0, description="GPUs per node, a count; 0 states that none is used")
    wall: str | None = Field(default=None, description="wall time, `[D-]HH:MM:SS`; read on a machine with a scheduler",
                             json_schema_extra=_roles(SHARED))
    memory: str | None = Field(default=None, description=f"memory per node, a whole number with {LETTERS}; "
                                                         "read on a machine with a scheduler",
                               json_schema_extra=_roles(SHARED, SCHEDULER))
    partition: str | None = Field(default=None, description="the queue, on a machine with a scheduler",
                                  json_schema_extra=_roles(SHARED, SCHEDULER, QUEUE))
    qos: str | None = Field(default=None, description="the quality of service, where the record lists one",
                            json_schema_extra=_roles(SHARED, SCHEDULER, QUEUE))

    @classmethod
    def holding(cls, role: str) -> tuple[str, ...]:
        """Each field that declares ``role``, in the model's order (jobs.md § 2)."""
        return tuple(name for name, f in cls.model_fields.items() if role in field_extras(f).get(ROLES, ()))

    def shared(self) -> dict[str, str | None]:
        """Each field a job and its members share, with its value here: what a stage inside a job
        takes from it (workflow.md § 5)."""
        return {name: getattr(self, name) for name in self.holding(SHARED)}

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
            raise ValueError(f"{value!r} is not a whole number with {LETTERS} (`16G`)")
        return value

    @property
    def cores(self) -> int:
        """The cores it uses: its ranks times the threads of each."""
        return self.ranks * self.threads


class Share(Model):
    """A file another calculation folder made, read where it was made (jobs.md § 2)."""

    folder: Folder = Field(description="the calculation folder that made it, by its path from this one")
    file: File = Field(description="the file, one of that folder's outputs: read in its newest run, which must be "
                                   "finished, by its path from the run, checked by its SHA-256 at launch; a command "
                                   "or a check names it `{share:FILE}`")


def _arguments(words: list[str] | None) -> list[str] | None:
    return words if words is None else check_arguments(words, PLACEHOLDERS)


class JobRequest(Model):
    """`job.toml`: a calculation folder's — one command in one environment — or a launch folder's,
    a batch's members or a sequence's parts, run in one job (jobs.md §§ 1.2, 2)."""

    name: str = matching(NAME, description="the job's name, as a scheduler shows it")
    environment: str | None = Field(default=None, description="the environment the command runs in, by name; with "
                                                              "`gpus > 0`, its CUDA environment `<name>-cuda`")
    command: list[str] | None = Field(default=None, min_length=1,
                                      description="the command, word by word: its first word resolves inside the "
                                                  "environment; `{python}` is the environment's own python")
    inputs: list[File] = Field(default_factory=list, description="files and folders of the calculation folder the "
                                                                 "command reads, copied into each run")
    resources: Resources = Field(description="what the job asks of the machine, every value stated; a launch "
                                             "folder's are its job's, which every member and part runs within")
    programs: list[Annotated[str, matching(PROGRAM)]] = Field(
        default_factory=list, description="femkit's own programs the command or the check runs, by their names in "
                                          "femkit's programs: `job prepare` copies each in, with the modules it runs "
                                          "with and the monitor")
    one_process: bool = Field(default=False, description="the command runs one process: it states `ranks = 1`; "
                                                         "inside a job that holds more, it runs with its own")
    outputs: list[File] = Field(default_factory=list, description="what the command promises to leave: once its "
                                                                  "check passed, each recorded with its SHA-256 and "
                                                                  "made read-only")
    check: list[str] | None = Field(default=None, min_length=1,
                                    description="the contract's check of what the command left, word by word: run "
                                                "after it, in the same environment and run, it exits 0 when it "
                                                "holds, its last line the reason when it does not")
    shares: list[Share] = Field(default_factory=list, description="files other calculation folders made, read where "
                                                                  "they were made")
    members: list[Folder] | None = Field(default=None, min_length=1,
                                         description="a batch's calculation folders, by their paths from its launch "
                                                     "folder: run one after another in one job, each in a new run")
    sequence: list[Folder] | None = Field(default=None, min_length=1,
                                          description="a sequence's parts — batches or calculation folders — by "
                                                      "their paths from its launch folder: each launched in turn, "
                                                      "inside one job")

    _command = field_validator("command", "check")(_arguments)

    @model_validator(mode="after")
    def _one_shape(self, info: ValidationInfo) -> "JobRequest":
        problems: list[tuple[tuple, str]] = []
        walks = [k for k in ("members", "sequence") if getattr(self, k) is not None]
        if len(walks) == 2:
            problems.append((("sequence",), "a launch folder holds a batch's `members` or a sequence's parts, "
                                            "not both"))
        if walks:
            problems += [((key,), f"a launch folder runs its {walks[0]}' own scripts and states no `{key}`")
                         for key in ("environment", "command", "inputs", "programs", "outputs", "check", "shares")
                         if getattr(self, key)]
            if self.one_process:
                problems.append((("one_process",), "a launch folder runs no process of its own"))
            listed = getattr(self, walks[0])
            problems += [((walks[0], i), f"{folder} is listed twice")
                         for i, folder in enumerate(listed) if folder in listed[:i]]
        else:
            problems += [((key,), f"`{key}` is missing: a calculation folder states the environment and the "
                                  "command it runs")
                         for key in ("environment", "command") if getattr(self, key) is None]
        problems += self._names((info.context or {}).get(RESERVED, frozenset()))
        problems += self._placeholders()
        refuse("JobRequest", problems)
        return self

    def _names(self, reserved: frozenset[str]) -> list[tuple[tuple, str]]:
        """A run holds one file of each name: an input, a program and an output each its own — an
        output may be an input the command writes over — and none of them a name of femkit's own.
        A shared file is read where it was made, never placed in the run, so it takes no name
        there: the shares are named one each among themselves alone, and a stage may share a file
        and write one of the same name (jobs.md § 2)."""
        problems: list[tuple[tuple, str]] = []
        for group in ((("inputs", self.inputs), ("programs", self.programs), ("outputs", self.outputs)),
                      (("shares", [s.file for s in self.shares]),)):
            named: dict[str, str] = {}
            for key, values in group:
                for i, value in enumerate(values):
                    where = (key, i, "file") if key == "shares" else (key, i)
                    top = PurePosixPath(value).parts[0]
                    if top in reserved:
                        problems.append((where, f"{value!r} takes a name a calculation folder or a run holds of "
                                                f"femkit's own: {', '.join(sorted(reserved))}"))
                    elif value in named and not (key == "outputs" and named[value] == "inputs"):
                        problems.append((where, f"{value} is named by {named[value]} too: a run holds one file of "
                                                "each name, and each share names its own"))
                    named.setdefault(value, key)
        return problems

    def _placeholders(self) -> list[tuple[tuple, str]]:
        """Each `{share:FILE}` names a file the request shares; `{share}` names one."""
        shared = {s.file for s in self.shares}
        problems: list[tuple[tuple, str]] = []
        for key in ("command", "check"):
            for i, word in enumerate(getattr(self, key) or []):
                for p in parsed(word):
                    if p.name == SHARE and p.argument not in shared:
                        problems.append(((key, i), f"{{share:{p.argument or ''}}} names no file the request shares "
                                                    f"({', '.join(sorted(shared)) or 'it shares none'})"))
                    elif p.name == PYTHON and p.argument is not None:
                        problems.append(((key, i), f"{{python}} takes no argument, not {p.argument!r}"))
        return problems

    @property
    def walk(self) -> str | None:
        """`members` for a batch's launch folder, `sequence` for a sequence's; None for a
        calculation folder."""
        return "members" if self.members is not None else "sequence" if self.sequence is not None else None

    @property
    def listed(self) -> list[str]:
        """A launch folder's members or parts, in order; none for a calculation folder."""
        return list(self.members or self.sequence or [])


def context(reserved: frozenset[str]) -> dict[str, Any]:
    """The validation context a request is loaded with: the names its files may not take."""
    return {RESERVED: reserved}
