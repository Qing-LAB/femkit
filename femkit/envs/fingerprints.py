"""The two fingerprints (envs.md § 2): what was built, and what was checked."""

from __future__ import annotations

from femkit.core import persist
from femkit.definitions.models import ControlDefinition, EnvironmentDefinition


def install(env: EnvironmentDefinition, control: ControlDefinition, cuda_architectures: list[str] | None,
            manager_kind: str) -> str:
    """Packages, sources and builds; the channels, and the Python minor when it provides Python —
    every fact its create's constraints are made of; CUDA targets when a build needs them; the
    manager kind."""
    needs_cuda = any(b.cuda_architectures for b in env.builds)
    return persist.canonical_sha256({
        "packages": env.packages.model_dump(mode="json"),
        "sources": [s.model_dump(mode="json") for s in env.sources],
        "builds": [b.model_dump(mode="json") for b in env.builds],
        "python": control.python_minor if env.holds_python else None,
        "channels": control.channels,
        "cuda_architectures": sorted(cuda_architectures or []) if needs_cuda else None,
        "manager": manager_kind,
    })


def check(env: EnvironmentDefinition, code: dict[str, str]) -> str:
    """The checks and agreements, the thread and fixed variables, and ``code``: each file of what
    runs the checks, what they run and what reads them, by its path, with its SHA-256."""
    return persist.canonical_sha256({
        "checks": [c.model_dump(mode="json") for c in env.checks],
        "agreements": {k: v.model_dump(mode="json") for k, v in env.agreements.items()},
        "thread_variables": env.thread_variables,
        "fixed_variables": env.fixed_variables,
        "code": code,
    })
