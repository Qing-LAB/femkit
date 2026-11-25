"""The engine environment's state (envs.md § 3): observed, never stored, by the rules
`femkit/data/states/environment.toml` declares over the facts gathered and named here.

Facts are read from disk; observing starts no process and needs no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

from femkit.config import settings
from femkit.core import locks, states, view
from femkit.core.errors import UsageError
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.definitions.models import EnvironmentDefinition
from femkit.engines import package_dir
from femkit.envs import checks, fingerprints, layout, manager

from femkit.envs.records import ChecksRecord, Manifest, read
from femkit.envs.requests import ENV_LIST


@dataclass(frozen=True)
class EnvFacts:
    name: str
    prefix: Path
    locked: bool
    prefix_kind: Literal["absent", "directory", "environment"]
    manifest: Manifest | None
    install_fingerprint: str | None   # none: no manifest and no manager named to say what would build it
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


BINDING = states.Binding("environment", {
    "locked": lambda f: f.locked,
    "prefix": lambda f: f.prefix_kind != "absent",
    "environment": lambda f: f.prefix_kind == "environment",
    "manifest": lambda f: f.manifest is not None,
    "built_as_now": lambda f: f.manifest is not None and f.manifest.install_fingerprint == f.install_fingerprint,
    "checked": lambda f: f.current_checks is not None,
    "cpu_failed": lambda f: f.cpu_failed,
}, reads=frozenset({"absent", "incomplete", "unchecked", "failing", "ready"}))   # read by envs, jobs and server


def machine(ctx: Context) -> states.Machine:
    """The machine `femkit/data/states/environment.toml` declares, bound to these facts (envs.md § 3)."""
    return catalogue.machine(ctx, BINDING)


def definition(ctx: Context, name: str) -> EnvironmentDefinition:
    envs = catalogue.load(ctx).environments
    if name not in envs:
        raise UsageError(f"no environment {name!r}; environments: {', '.join(sorted(envs))}",
                         (view.command(ENV_LIST),), code="no-such-environment", subject=name)
    return envs[name]


def install_fingerprint(ctx: Context, name: str, manager_kind: str | None) -> str | None:
    """What an install of ``name`` by a ``manager_kind`` manager is fingerprinted as; None
    without a manager kind."""
    if manager_kind is None:
        return None
    env = definition(ctx, name)
    cat = catalogue.load(ctx)
    return fingerprints.install(env, cat.control, settings.load(ctx).config.build.cuda_architectures, manager_kind)


def _built_by(manifest: Manifest | None, ctx: Context) -> str | None:
    """The manager kind an environment's fingerprint is read with: the one its manifest says built
    it — so looking needs no manager named, and another manager now leaves it as built — else the
    one the invocation names, which would build it (envs.md § 2)."""
    if manifest is not None:
        return manifest.manager_kind
    named = manager.named(ctx)
    return Path(named).name if named else None


def facts(ctx: Context, name: str) -> EnvFacts:
    """What is observed of the environment ``name``; its lock as another process holds it —
    this process's own hold reads as free (core.md § 5)."""
    env = definition(ctx, name)
    where = layout.prefix(ctx, name)
    kind = "absent" if not where.exists() else ("environment" if (where / "conda-meta").is_dir() else "directory")
    manifest = read(layout.manifest_file(where), Manifest)
    return EnvFacts(
        name=name,
        prefix=where,
        locked=locks.is_held(layout.subject(name)),
        prefix_kind=kind,
        manifest=manifest,
        install_fingerprint=install_fingerprint(ctx, name, _built_by(manifest, ctx)),
        checks=read(layout.checks_file(where), ChecksRecord),
        check_fingerprint=fingerprints.check(env, package_dir(env.engine) if env.engine else None, checks.JUDGING),
        declared_checks=frozenset(c.id for c in env.checks),
        device_checks=frozenset(c.id for c in env.checks if c.device),
    )


def observe(ctx: Context, name: str) -> tuple[EnvFacts, Enum]:
    """The environment's facts, and its state by the machine's rules."""
    f = facts(ctx, name)
    return f, machine(ctx).observe(f)


def gpu(ctx: Context, f: EnvFacts, state: Enum) -> str | None:
    """The GPU qualification an environment reports: only while it is `failing` or `ready` (envs.md § 3.2)."""
    m = machine(ctx)
    return f.gpu if state in (m.states.failing, m.states.ready) else None
