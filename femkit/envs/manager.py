"""The package manager in use, and the command lines its kind declares (definitions.md § 6).

The install script finds the manager and passes it as FEMKIT_ENV_MANAGER
(envs.md § 7.1); Python never searches.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from femkit.core import dirs, persist, process, view
from femkit.core.errors import Unstated, UsageError
from femkit.core.operations import Context
from femkit.core.schema import render
from femkit.definitions import catalogue
from femkit.definitions.models import JsonQuery, ManagerKind

VARIABLE = "FEMKIT_ENV_MANAGER"


@dataclass(frozen=True)
class Manager:
    path: Path
    kind_name: str
    kind: ManagerKind
    # The invocation's variables, from which every command this manager starts takes its own (§ 4.4).
    base: Mapping[str, str] = field(compare=False, repr=False)
    printed: dict = field(default_factory=dict, compare=False, repr=False)  # a query's command -> what it printed

    @property
    def environment(self) -> dict[str, str]:
        """The variables its commands run with, in femkit's own places — made now, as a command
        is about to start; looking at an environment or planning makes none of them."""
        variables = in_femkit_places(self.base)
        for name in ("HOME", "CONDA_PKGS_DIRS", "TMPDIR"):
            persist.make_folder(Path(variables[name]))
        return variables

    def argv(self, template: list[str], **values: str) -> list[str]:
        return [render(arg, {"exe": str(self.path), **values}) for arg in template]

    def create(self, prefix: Path, channels: list[str], packages: list[str]) -> list[str]:
        argv = self.argv(self.kind.create, prefix=str(prefix))
        for channel in channels:
            argv += [render(arg, {"channel": channel}) for arg in self.kind.channel]
        return argv + list(packages)

    def create_from_lock(self, prefix: Path, lock: Path, channels: list[str]) -> list[str]:
        """The kind's `create_from_lock`, naming the declared channels where the kind does (envs.md § 4.4)."""
        return self._named(self.argv(self.kind.create_from_lock, prefix=str(prefix), file=str(lock)),
                           "create_from_lock", channels)

    def remove(self, prefix: Path, channels: list[str]) -> list[str]:
        """The kind's `remove`, naming the declared channels where the kind does (envs.md § 4.4)."""
        return self._named(self.argv(self.kind.remove, prefix=str(prefix)), "remove", channels)

    def _named(self, argv: list[str], command: str, channels: list[str]) -> list[str]:
        for channel in channels if command in self.kind.channels_named else []:
            argv += [render(arg, {"channel": channel}) for arg in self.kind.channel]
        return argv

    def in_prefix(self, prefix: Path, command: list[str]) -> list[str]:
        """``command`` run inside ``prefix`` through the manager's own mechanism (envs.md § 4.4)."""
        return self.argv(self.kind.run, prefix=str(prefix)) + list(command)

    def version(self) -> tuple[str | None, str | None]:
        """(the manager's version, None), or (None, why it did not read): the first group of
        the kind's `version_pattern` in what its `version` command printed."""
        argv = self.argv(self.kind.version)
        result = process.run(argv, env=self.environment, timeout=60)
        if not result.ok:
            return None, _failed(argv, result)
        found = re.search(self.kind.version_pattern, result.stdout)
        if found is None:
            return None, f"`{shlex.join(argv[1:])}` printed nothing that {self.kind.version_pattern!r} matches"
        return found.group(1), None

    def query(self, q: JsonQuery) -> tuple[Any, str | None]:
        """(the answer, None), or (None, why there is none): one key of the JSON the
        manager prints."""
        argv = self.argv(q.argv)
        if tuple(argv) not in self.printed:  # one run per command: root and platform may share one
            self.printed[tuple(argv)] = process.run(argv, env=self.environment, timeout=60)
        result = self.printed[tuple(argv)]
        if not result.ok:
            return None, _failed(argv, result)
        try:
            data = json.loads(result.stdout)
        except ValueError:
            return None, f"`{shlex.join(argv[1:])}` printed no JSON"
        keys = [q.key] if isinstance(q.key, str) else q.key
        found = next((k for k in keys if k in data), None)
        return (data[found], None) if found else (None, f"`{shlex.join(argv[1:])}` has no {' or '.join(keys)}")

    def activation(self, prefix: Path, command: str) -> list[str]:
        """The shell lines that enter ``prefix`` with the activation the person stated for this
        machine (config.md § 3.1; envs.md § 6.2). The kind's script form is one line; its
        shell-function form needs the kind's hook sourced first, from its file under the
        manager's root, checked on disk. A command that is neither of the kind's forms is
        written as stated, and says so."""
        a = self.kind.activate
        words = command.split()
        line = shlex.join([*words, str(prefix)])
        if words == [x for x in a.without_hook if x != "{prefix}"]:
            return [line]
        if words != [x for x in a.with_hook if x != "{prefix}"]:
            return [line + f"   # not one of the {self.kind_name} kind's forms"]
        root, why = self.query(self.kind.root)
        hook = Path(render(a.hook, {"root": str(root)})) if root else None
        if hook is not None and hook.is_file():
            return [f"source {shlex.quote(str(hook))}", line]
        return [line + f"   # {why or f'no hook file at {hook}'}: `{command}` needs the manager's hook sourced first"]


def _failed(argv: list[str], result: process.ProcessResult) -> str:
    """Why a manager command gave no answer: how it ended."""
    ended = "did not end in time" if result.timed_out else f"failed (exit {result.returncode})"
    return f"`{shlex.join(argv[1:])}` {ended}"


# What every command run inside a prefix starts from (envs.md § 4.4): this allow-list, and the
# manager's activation then adds the prefix's own settings. Whatever else a shell, a module or a
# site profile set — compilers, flags, search paths, package roots — never reaches the command.
CONFINED = frozenset({"HOME", "USER", "LOGNAME", "LANG", "TERM", "TMPDIR", "CUDA_VISIBLE_DEVICES",
                      # OpenMPI refuses to run as root unless both are set: a root container needs them
                      "OMPI_ALLOW_RUN_AS_ROOT", "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM"})
SYSTEM_PATH = "/usr/bin:/bin"  # the manager's own wrapper needs a shell; the prefix's bin comes first


def confined(base: Mapping[str, str], *, checkout: bool = False) -> dict[str, str]:
    """``base`` cut to the allow-list, with the system `PATH` and no user site-packages.
    ``checkout``: the checkout alone as `PYTHONPATH`, for femkit's own programs run inside a
    prefix (the toolchain check, the check programs)."""
    kept = {k: v for k, v in base.items() if k in CONFINED or k.startswith("LC_")}
    return {**kept, "PATH": SYSTEM_PATH, "PYTHONNOUSERSITE": "1",
            **({"PYTHONPATH": str(dirs.checkout())} if checkout else {})}


ACTIVATION_VARIABLES = ("MAMBA_EXE", "CONDA_EXE")  # set by the manager's own activation


# Where a person's own configuration and caches are named apart from `HOME`: the manager reads a
# `condarc` and writes its caches through these (measured 2026-11-23, conda 26.7.1 reads both
# `$XDG_CONFIG_HOME/conda/.condarc` and `$CONDARC` under femkit's `HOME`), so none reaches it.
PERSONS_OWN = ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "CONDARC", "MAMBARC")
# A manager's own settings, named in the environment: measured 2026-11-24, conda 26.7.1 reads any
# `CONDA_<KEY>` as its configuration — `CONDA_CHANNEL_PRIORITY=disabled` turns `conda config --show
# channel_priority` from flexible to disabled. So none of the person's `CONDA_*`, nor `MAMBA_*`
# (mamba's, by the same naming; not measured), reaches a manager command: only those femkit sets.
MANAGERS_OWN = ("CONDA_", "MAMBA_")


def in_femkit_places(base: Mapping[str, str]) -> dict[str, str]:
    """``base`` as every manager command runs with it (envs.md § 4.4): its `HOME`, package
    cache, list of environments and temporary files in femkit's cache, never in the person's
    home or the system's temporary folder, and none of the person's own configuration read."""
    home, packages, tmp = (dirs.cache_dir() / d for d in ("manager-home", "pkgs", "tmp"))
    kept = {k: v for k, v in base.items() if k not in PERSONS_OWN and not k.startswith(MANAGERS_OWN)}
    return {**kept, "HOME": str(home), "CONDA_PKGS_DIRS": str(packages), "CONDA_REGISTER_ENVS": "false",
            "TMPDIR": str(tmp)}


def named(ctx: Context) -> str | None:
    """The manager the invocation names: FEMKIT_ENV_MANAGER (set by the install script), else the
    first variable a manager's activation sets that names one femkit has a kind file for, so a
    mamba beside conda is passed over (envs.md § 7.1); None when none is named."""
    kinds = catalogue.load(ctx).managers
    activated = [ctx.env[v] for v in ACTIVATION_VARIABLES if ctx.env.get(v)]
    return ctx.env.get(VARIABLE) or next((v for v in activated if Path(v).name in kinds), None) \
        or next(iter(activated), None)


def resolve(ctx: Context) -> Manager:
    """The manager the invocation names, to run its commands; refused when none names a known kind."""
    kinds = catalogue.load(ctx).managers
    named_here = named(ctx)
    if not named_here:
        raise Unstated("no package manager is named: run femkit in the activated control environment, "
                      "or through scripts/install-env.sh", (view.shell("bash scripts/install-env.sh list"),),
                      code="manager-unnamed", subject=VARIABLE)
    path = Path(named_here)
    if path.name not in kinds:
        raise UsageError(f"{path} is a manager femkit has no kind file for (it has: {', '.join(sorted(kinds))})",
                         code="no-such-kind", subject=str(path))
    return Manager(path, path.name, kinds[path.name], ctx.env)
