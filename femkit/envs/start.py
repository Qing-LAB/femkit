"""The clean start (envs.md § 4.4): how every process femkit starts for an environment begins.

Declared once, as data — `femkit/data/process.toml` — and read here alone, for every caller: of
the invocation's variables, only those its pass list names, with what each scheduler kind adds —
the variables a job of it sees (`passes`) and the shell functions it needs (`functions`) — and of
them none its remove list names; `PATH` the system's own; then what it sets. `begin` gives that
start to a process femkit starts — a manager command (`manager.Manager.environment`), a command
inside an environment (`inside.Inside.variables`), femkit's own program on an environment's Python
(`dirs.femkit_env` over it: the web server's supervisor and its child) — and `clean` is it for the
invocation; `lines` writes it as shell, for a run script, which starts clean before its preamble
and its activation (jobs.md § 4, block 8), and for the `femkit` command, which starts femkit's
control Python so (envs.md § 7) — the install script writes the same lines from the same data. What
enters the environment after it is the manager's own `run` or activation, by the environment's name;
nothing is filtered after that. No list of variables is kept in code.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase

from femkit.core.operations import Context
from femkit.core.schema import render
from femkit.definitions import catalogue
from femkit.definitions.models import ProcessStart, SchedulerKind


def jobs(kinds: Iterable[SchedulerKind]) -> tuple[str, ...]:
    """What a job of each scheduler kind in ``kinds`` sees that a clean start passes, each pattern
    once: only the kind whose job a process runs in has any of them set."""
    return tuple(dict.fromkeys(p for kind in kinds for p in kind.passes))


def functions(kinds: Iterable[SchedulerKind]) -> tuple[str, ...]:
    """The shell functions a job of each scheduler kind in ``kinds`` needs passed, each once."""
    return tuple(dict.fromkeys(f for kind in kinds for f in kind.functions))


def kept(start: ProcessStart, name: str, passes: Iterable[str] = (), shell: Iterable[str] = ()) -> bool:
    """Whether the variable ``name`` survives the start: a pattern of its pass list, or of
    ``passes``, names it — or it is how a function of ``shell`` is passed — and none of its remove
    list does."""
    named = (*start.passes, *passes, *(render(start.function, {"name": f}) for f in shell))
    return any(fnmatchcase(name, p) for p in named) and not any(fnmatchcase(name, p) for p in start.removes)


def begin(start: ProcessStart, base: Mapping[str, str], passes: Iterable[str] = (),
          shell: Iterable[str] = ()) -> dict[str, str]:
    """The variables a process femkit starts for an environment begins with, from the invocation's
    ``base``: those `kept`, `PATH` the system's own, then what the start sets."""
    passes, shell = tuple(passes), tuple(shell)
    return {**{k: v for k, v in base.items() if kept(start, k, passes, shell)}, "PATH": start.path, **start.sets}


def clean(ctx: Context) -> dict[str, str]:
    """The invocation's clean start, once per invocation: `begin` over its variables, with what a job
    of every scheduler kind adds — only the kind whose job it runs in has any of them set."""
    def made() -> dict[str, str]:
        kinds = catalogue.schedulers(ctx).values()
        return begin(catalogue.process(ctx), ctx.env, jobs(kinds), functions(kinds))
    return dict(ctx.cached("the clean start", made))


def lines(start: ProcessStart, passes: Iterable[str] = (), shell: Iterable[str] = ()) -> list[str]:
    """The start written as bash, for a run script (jobs.md § 4, block 8): every exported variable the start does not keep unset — those it removes first,
    whatever pattern passes them — every exported function but those ``shell`` names no longer
    exported, so no child inherits it while this shell keeps it, `PATH` the system's, then what it
    sets. A readonly variable the shell will not unset is left. scripts/install-env.sh writes the
    same lines from the same data (`start_lines`)."""
    shell = tuple(shell)
    kept_here = [*start.passes, *passes]
    return ["for exported in $(compgen -e); do",
            '  case "$exported" in',
            f'    {" | ".join(start.removes)}) unset "$exported" 2>/dev/null || true ;;',
            f"    {' | '.join(kept_here)}) ;;",
            '    *) unset "$exported" 2>/dev/null || true ;;',
            "  esac",
            "done",
            "while read -r _ _ exported; do",
            '  case "$exported" in',
            *([f"    {' | '.join(shell)}) ;;"] if shell else []),
            '    *) export -fn "$exported" ;;',
            "  esac",
            "done < <(declare -Fx)",
            f"export PATH={shlex.quote(start.path)}",
            *(f"export {k}={shlex.quote(v)}" for k, v in start.sets.items())]


def own_lines(start: ProcessStart) -> list[str]:
    """What the `femkit` command sheds of the shell it is typed in before femkit's own Python starts
    (envs.md § 7), written as bash: each name the start's `femkit_sheds` names, unset. femkit keeps
    the rest, so it sees the machine it reads and probes as the person does; every process it starts
    for an environment begins clean (`begin`). scripts/install-env.sh writes the same lines from the
    same data (`own_lines`)."""
    return [f"unset {name} 2>/dev/null || true" for name in start.femkit_sheds]
