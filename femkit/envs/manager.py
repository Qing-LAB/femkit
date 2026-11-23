"""The package manager in use, and the command lines its kind declares (definitions.md § 6).

The install script finds the manager and passes it as FEMKIT_ENV_MANAGER
(envs.md § 7.1); Python never searches.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from femkit.core import dirs, process
from femkit.core.errors import Refusal
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
    # The invocation's variables: the manager's own commands run with them, and a command inside a
    # prefix is cut from them (§ 4.4) — one source for every command this manager starts.
    environment: dict[str, str] = field(compare=False, repr=False)
    printed: dict = field(default_factory=dict, compare=False, repr=False)  # a query's command -> what it printed

    def argv(self, template: list[str], **values: str) -> list[str]:
        return [render(arg, {"exe": str(self.path), **values}) for arg in template]

    def create(self, prefix: Path, channels: list[str], packages: list[str]) -> list[str]:
        argv = self.argv(self.kind.create, prefix=str(prefix))
        for channel in channels:
            argv += [render(arg, {"channel": channel}) for arg in self.kind.channel]
        return argv + list(packages)

    def in_prefix(self, prefix: Path, command: list[str]) -> list[str]:
        """``command`` run inside ``prefix`` through the manager's own mechanism (envs.md § 4.4)."""
        return self.argv(self.kind.run, prefix=str(prefix)) + list(command)

    def query(self, q: JsonQuery) -> tuple[Any, str | None]:
        """(the answer, None), or (None, why there is none): one key of the JSON the
        manager prints."""
        argv = self.argv(q.argv)
        if tuple(argv) not in self.printed:  # one run per command: root and platform may share one
            self.printed[tuple(argv)] = process.run(argv, env=self.environment, timeout=60)
        result = self.printed[tuple(argv)]
        if not result.ok:
            return None, f"`{shlex.join(argv[1:])}` failed"
        try:
            data = json.loads(result.stdout)
        except ValueError:
            return None, f"`{shlex.join(argv[1:])}` printed no JSON"
        keys = [q.key] if isinstance(q.key, str) else q.key
        found = next((k for k in keys if k in data), None)
        return (data[found], None) if found else (None, f"`{shlex.join(argv[1:])}` has no {' or '.join(keys)}")

    def activation(self, prefix: Path) -> list[str]:
        """The shell lines that enter ``prefix`` (envs.md § 4.4, § 6.2): the kind's hook,
        sourced when its file exists under the manager's root, then the line that needs
        it; else the line that needs none."""
        a = self.kind.activate
        root, why = self.query(self.kind.root)
        hook = Path(render(a.hook, {"root": str(root)})) if root else None
        if hook is not None and hook.is_file():
            return [f"source {shlex.quote(str(hook))}",
                    shlex.join(render(x, {"prefix": str(prefix)}) for x in a.with_hook)]
        line = shlex.join(render(x, {"prefix": str(prefix)}) for x in a.without_hook)
        return [line + (f"   # {why}, so no hook was looked for" if why else "")]


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


def resolve(ctx: Context) -> Manager:
    """The manager: FEMKIT_ENV_MANAGER (set by the install script), else the variable the
    manager's activation sets (envs.md § 7.1). Refused when none names a known kind."""
    kinds = catalogue.load_managers()
    activated = [ctx.env[v] for v in ACTIVATION_VARIABLES if ctx.env.get(v)]
    # The variable the install script set wins; else the first activation variable naming a
    # manager femkit has a kind file for (envs.md § 7.1), so a mamba beside conda is passed over.
    named = ctx.env.get(VARIABLE) or next((v for v in activated if Path(v).name in kinds), None) \
        or next(iter(activated), None)
    if not named:
        raise Refusal("no package manager is named: run femkit in the activated control environment, "
                      "or through scripts/install-env.sh", ("bash scripts/install-env.sh list",))
    path = Path(named)
    if path.name not in kinds:
        raise Refusal(f"{path} is a manager femkit has no kind file for (it has: {', '.join(sorted(kinds))})")
    return Manager(path, path.name, kinds[path.name], dict(ctx.env))
