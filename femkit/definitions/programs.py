"""`femkit/data/programs.toml` (envs.md § 4.4): every femkit program that runs inside an
environment, declared once — the environment it runs in, its entry, its time limit and the
variables it is given beyond the clean start every command inside an environment begins from
(`femkit/data/process.toml`, envs.md § 4.4).

Its entry is femkit's own Python program, a module of the checkout started the one way femkit
starts its programs (`dirs.femkit_argv`, envs.md § 7), or a tool's command. Its variables are
those it is given set (`sets`), each value in the core's one grammar (core.md § 2.1), `{work}` the folder the operation that runs
it works in; a file one of them names that the program reads is made empty where there is none
(`files`), so it reads no file of the person's in its place. The checks are declared with their environment
(definitions.md § 5), the server's child with this one: its environment and its module.

The model lives here, beside the catalogue that loads it (definitions.md § 2.1).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field, RootModel, ValidationInfo, model_validator

from femkit.core.schema import Model, check_placeholders, refuse, whole

#: A program's name: the key a caller reads it by.
NAME = r"[a-z][a-z0-9_-]*"
ProgramName = Annotated[str, Field(pattern=whole(NAME))]
#: What a value of `sets` may name: the folder the operation that runs the program works in.
PLACES = frozenset({"work"})


class Program(Model):
    """One femkit program that runs inside an environment (envs.md § 4.4)."""

    describe: str = Field(description="what it does, as a person reads it")
    environment: str | None = Field(default=None, description="the environment it runs in, by name; none: the one "
                                                               "the operation that runs it acts on — an install's, a "
                                                               "validate's, the probe's control environment")
    module: str | None = Field(default=None, description="femkit's own Python program: a module of the checkout, "
                                                         "run on the environment's `python` with `-P` and the "
                                                         "checkout alone as its import path (envs.md § 7)")
    command: list[str] | None = Field(default=None, min_length=1, description="a tool's command, its arguments "
                                                                              "after it given where it runs")
    timeout: int | None = Field(default=None, gt=0, description="its time limit, in seconds; none: none — a build "
                                                                "takes as long as the machine needs (envs.md § 4.1)")
    sets: dict[str, str] = Field(default_factory=dict, description="variables it is given, each with its value; "
                                 "`{work}` is the folder the operation that runs it works in",
                                 json_schema_extra={"placeholders": sorted(PLACES)})
    files: list[str] = Field(default_factory=list, description="of `sets`, each variable whose value is a file the "
                                                               "program reads: made empty where there is none, so it "
                                                               "reads no file of the person's in its place")

    @model_validator(mode="after")
    def _one_entry(self) -> "Program":
        problems: list[tuple[tuple, str]] = []
        if (self.module is None) == (self.command is None):
            problems.append(((), "a program is femkit's own `module` or a tool's `command`: one of the two"))
        for name, value in self.sets.items():
            try:
                check_placeholders(value, PLACES)
            except ValueError as exc:
                problems.append((("sets", name), str(exc)))
        problems += [(("files",), f"{v!r} is none of the variables it sets") for v in self.files if v not in self.sets]
        refuse("Program", problems)
        return self


class ProgramList(RootModel[dict[ProgramName, Program]]):
    """`programs.toml`: each program by its name. Its validation context may hold `environments`,
    the environments' names, and `modules`, whether a module is one of the checkout: given, each
    program runs in one of them, and its module is there."""

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def _references(self, info: ValidationInfo) -> "ProgramList":
        context = info.context or {}
        environments, there = context.get("environments"), context.get("modules")
        problems: list[tuple[tuple, str]] = []
        for name, program in self.root.items():
            if environments is not None and program.environment is not None \
                    and program.environment not in environments:
                problems.append(((name, "environment"), f"{program.environment!r} is no environment (they are: "
                                                        f"{', '.join(sorted(environments))})"))
            if there is not None and program.module is not None and not there(program.module):
                problems.append(((name, "module"), f"{program.module!r} is no module of femkit's checkout"))
        refuse("ProgramList", problems)
        return self
