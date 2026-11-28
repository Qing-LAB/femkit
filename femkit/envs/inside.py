"""The one door into an environment (envs.md § 4.4): every command femkit runs inside an
environment — a femkit program declared in `femkit/data/programs.toml`, a check, a build step, a
version command — starts here.

`entered` resolves the manager the invocation names, the environment's name with it
(`catalogue.managed`) and its prefix, asked of the manager by that name (envs.md § 1); the command
runs through the manager kind's own `run`, by the name (`Inside.argv`) — the one place a fallback
that enters by the kind's shell hook would go, where a machine's `run` cannot start a command (not
built yet, plan § 4, M1) — from the clean start every process for an environment begins with
(`envs/start.py`, the manager's `environment`), with the checkout alone as its import path for
femkit's own programs, and the variables the program's declaration sets, each file one of them
names that it reads made empty where there is none (`Inside.run`). A program's own command is its
declaration's: femkit's module started the one way femkit starts its programs (`dirs.femkit_argv`,
envs.md § 7), or a tool's command (`Inside.program`). Whether an environment may be used at all is
its state's, asked before (`state.usable`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from femkit.core import dirs, persist, process
from femkit.core.operations import Context
from femkit.core.schema import render
from femkit.definitions import catalogue
from femkit.definitions.programs import Program
from femkit.envs.manager import Manager, resolve


def program(ctx: Context, name: str) -> Program:
    """The femkit program ``name``, as `programs.toml` declares it (envs.md § 4.4)."""
    return catalogue.programs(ctx)[name]


@dataclass(frozen=True)
class Inside:
    """One environment, to run commands in: its name, its name with the manager (envs.md § 1), its
    prefix as the manager lists it — none while there is none — and the manager that enters it."""

    name: str
    managed: str
    prefix: Path | None
    manager: Manager

    def argv(self, command: Sequence[str]) -> list[str]:
        """``command`` as it runs inside the environment: through the manager kind's own `run`, by
        its name, the environment's activation adding its own settings (envs.md § 4.4)."""
        return self.manager.in_environment(self.managed, command)

    def program(self, declared: Program, *arguments: str) -> list[str]:
        """A declared program's command with ``arguments``, as it runs inside the environment:
        femkit's own module on the environment's `python` (`dirs.femkit_argv`), or the tool's
        command."""
        own = dirs.femkit_argv("python", declared.module, *arguments) if declared.module else \
            [*declared.command, *arguments]
        return self.argv(own)

    def variables(self, declared: Program | None = None, *, checkout: bool = False,
                  work: Path | None = None, more: Mapping[str, str] | None = None) -> dict[str, str]:
        """What a command inside the environment starts with (envs.md § 4.4): the clean start; the
        checkout alone as its import path for femkit's own program — ``checkout``, or a declared
        one's module; the variables ``declared`` sets, ``work`` the folder its values name as
        `{work}`; then ``more``, what its caller declares besides — a check's thread and fixed
        variables."""
        out = self.manager.environment
        if checkout or (declared is not None and declared.module):
            out = dirs.femkit_env(out)
        if declared is not None:
            out |= {k: render(v, {"work": str(work)} if work is not None else {}) for k, v in declared.sets.items()}
        return out | dict(more or {})

    def run(self, argv: Sequence[str], *, declared: Program | None = None, checkout: bool = False,
            work: Path | None = None, more: Mapping[str, str] | None = None, timeout: float | None = None,
            cwd: Path | None = None, log: Path | None = None) -> process.ProcessResult:
        """The one way a command starts inside an environment (envs.md § 4.4): ``argv``, as `argv`
        or `program` wrote it, with its `variables`; each file a variable of ``declared`` names that
        it reads made empty where there is none; within ``declared``'s time limit, or ``timeout``
        for a command no program declares — a check's own, a version command's."""
        variables = self.variables(declared, checkout=checkout, work=work, more=more)
        for name in declared.files if declared is not None else ():
            if not Path(variables[name]).exists():
                persist.touch(Path(variables[name]))
        limit = declared.timeout if declared is not None else timeout
        return process.run(list(argv), env=variables, timeout=limit, cwd=cwd, log=log)


def entered(ctx: Context, name: str) -> Inside:
    """The environment ``name`` to run commands in — the control environment's name among them
    (`dirs.CONTROL`): the manager the invocation names, refused while none is named (§ 7.1), and the
    prefix it lists under the environment's name, none where it lists none (envs.md § 1)."""
    m, managed = resolve(ctx), catalogue.managed(ctx, name)
    return Inside(name, managed, m.prefix(managed), m)
