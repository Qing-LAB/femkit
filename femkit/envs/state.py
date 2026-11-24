"""The engine environment state machine (envs.md § 3).

Facts are read from disk; observing starts no process and needs no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

from femkit.config import settings
from femkit.core import locks, view
from femkit.core.errors import UsageError
from femkit.core.operations import Context
from femkit.core.states import Action, Machine, Rule
from femkit.definitions import catalogue
from femkit.definitions.models import EnvironmentDefinition
from femkit.engines import package_dir, registered
from femkit.envs import checks, fingerprints, layout
from femkit.envs.manager import resolve
from femkit.envs.records import ChecksRecord, Manifest, read
from femkit.envs.requests import CleanRequest, InstallRequest, ListRequest, ValidateRequest
from femkit.envs.requests import ENV_CLEAN, ENV_INSTALL, ENV_LIST, ENV_VALIDATE


class EnvState(str, Enum):
    busy = "busy"
    absent = "absent"
    incomplete = "incomplete"
    outdated = "outdated"
    unchecked = "unchecked"
    failing = "failing"
    ready = "ready"


@dataclass(frozen=True)
class EnvFacts:
    name: str
    prefix: Path
    locked: bool
    prefix_kind: Literal["absent", "directory", "environment"]
    manifest: Manifest | None
    install_fingerprint: str
    checks: ChecksRecord | None
    check_fingerprint: str
    declared_checks: frozenset[str]
    device_checks: frozenset[str]

    @property
    def current_checks(self) -> ChecksRecord | None:
        """The check results, when they are for the current check fingerprint and cover every check
        without device = true — the ones a plain validate runs (envs.md § 5)."""
        record = self.checks
        if record is None or record.check_fingerprint != self.check_fingerprint:
            return None
        if not self.declared_checks - self.device_checks <= {o.id for o in record.outcomes}:
            return None
        return record

    @property
    def cpu_failed(self) -> bool:
        record = self.current_checks
        return bool(record) and any(o.outcome != "passed" for o in record.outcomes
                                    if o.id in self.declared_checks - self.device_checks)

    @property
    def gpu(self) -> str | None:
        """GPU qualification (envs.md § 5): none, not-run, passed, failed; None while unchecked."""
        record = self.current_checks
        if record is None:
            return None
        if not self.device_checks:
            return "none"
        device = [o for o in record.outcomes if o.id in self.device_checks]
        if len(device) < len(self.device_checks):
            return "not-run"
        return "passed" if all(o.outcome == "passed" for o in device) else "failed"


def _names(name: str) -> dict:
    return {"names": [name]}


def _named(name: str) -> dict:
    return {"name": name}


_install = Action("install", ENV_INSTALL, _names)
_resume = Action("resume the install", ENV_INSTALL, _names)
_replace = Action("remove, install", ENV_INSTALL, _names)
_rebuild = Action("remove, install, discarding the saved lock", ENV_INSTALL,
                  lambda name: {"names": [name], "clean": True})
_validate = Action("validate", ENV_VALIDATE, _named)
_validate_gpu = Action("validate the GPU checks", ENV_VALIDATE,
                       lambda name: {"name": name, "gpu": True})
_remove = Action("remove", ENV_CLEAN, _named)
_nothing = Action("nothing to do")

MACHINE: Machine[EnvFacts, EnvState] = Machine(
    "environment",
    EnvState,
    (
        Rule("the lock is held", EnvState.busy, lambda f: f.locked),
        Rule("no prefix", EnvState.absent, lambda f: f.prefix_kind == "absent"),
        Rule("no readable manifest, or the prefix is not a manager environment", EnvState.incomplete,
             lambda f: f.manifest is None or f.prefix_kind != "environment"),
        Rule("the manifest's install fingerprint is not the current one", EnvState.outdated,
             lambda f: f.manifest.install_fingerprint != f.install_fingerprint),
        Rule("no check results for the current check fingerprint", EnvState.unchecked,
             lambda f: f.current_checks is None),
        Rule("a check without device = true did not pass", EnvState.failing, lambda f: f.cpu_failed),
        Rule("otherwise", EnvState.ready),
    ),
    {   # envs.md § 3.3: the actions each state allows
        EnvState.absent: {"install": _install, "install --clean": _install, "clean": _nothing},
        EnvState.busy: {},
        EnvState.incomplete: {"install": _resume, "install --clean": _rebuild, "clean": _remove},
        EnvState.outdated: {"install": _replace, "install --clean": _rebuild, "clean": _remove},
        EnvState.unchecked: {"install": _validate, "install --clean": _rebuild, "validate": _validate, "clean": _remove},
        EnvState.failing: {"install --clean": _rebuild, "validate": _validate, "validate --gpu": _validate_gpu,
                           "clean": _remove},
        EnvState.ready: {"install": _nothing, "install --clean": _rebuild, "validate": _validate,
                         "validate --gpu": _validate_gpu, "clean": _remove},
    },
)


def definition(ctx: Context, name: str) -> EnvironmentDefinition:
    envs = catalogue.load(ctx, engines=registered()).environments
    if name not in envs:
        raise UsageError(f"no environment {name!r}; environments: {', '.join(sorted(envs))}",
                         (view.command(ENV_LIST),))
    return envs[name]


def install_fingerprint(ctx: Context, name: str) -> str:
    env = definition(ctx, name)
    cat = catalogue.load(ctx, engines=registered())
    return fingerprints.install(env, cat.control, settings.load(ctx).config.build.cuda_architectures,
                                resolve(ctx).kind_name)


def facts(ctx: Context, name: str, *, holding_lock: bool = False) -> EnvFacts:
    """``holding_lock``: the caller holds this environment's lock (an apply re-observing),
    so the lock says nothing about anyone else."""
    env = definition(ctx, name)
    where = layout.prefix(ctx, name)
    kind = "absent" if not where.exists() else ("environment" if (where / "conda-meta").is_dir() else "directory")
    return EnvFacts(
        name=name,
        prefix=where,
        locked=False if holding_lock else locks.is_held(layout.subject(name)),
        prefix_kind=kind,
        manifest=read(layout.manifest_file(where), Manifest),
        install_fingerprint=install_fingerprint(ctx, name),
        checks=read(layout.checks_file(where), ChecksRecord),
        check_fingerprint=fingerprints.check(env, package_dir(env.engine) if env.engine else None, checks.JUDGING),
        declared_checks=frozenset(c.id for c in env.checks),
        device_checks=frozenset(c.id for c in env.checks if c.device),
    )


def observe(ctx: Context, name: str, *, holding_lock: bool = False) -> tuple[EnvFacts, EnvState]:
    f = facts(ctx, name, holding_lock=holding_lock)
    return f, MACHINE.observe(f)


INSTALLED = (EnvState.failing, EnvState.ready)  # the states that report a GPU qualification
