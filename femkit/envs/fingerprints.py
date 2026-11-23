"""The two fingerprints (envs.md § 2): what was built, and what was checked."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from femkit.definitions.models import ControlDefinition, EnvironmentDefinition


def _digest(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def install(env: EnvironmentDefinition, control: ControlDefinition, cuda_architectures: list[str] | None,
            manager_kind: str) -> str:
    """Packages, sources and builds; Python minor and channels; CUDA targets when a build needs them; manager kind."""
    needs_cuda = any(b.cuda_architectures for b in env.builds)
    return _digest({
        "packages": env.packages.model_dump(mode="json"),
        "sources": [s.model_dump(mode="json") for s in env.sources],
        "builds": [b.model_dump(mode="json") for b in env.builds],
        "python": control.python_minor,
        "channels": control.channels,
        "cuda_architectures": sorted(cuda_architectures or []) if needs_cuda else None,
        "manager": manager_kind,
    })


def check(env: EnvironmentDefinition, engine_package: Path, judging: tuple[Path, ...]) -> str:
    """The checks and agreements, the thread and fixed variables, every file of the engine
    package, and the shared code that runs and judges checks (``judging``)."""
    files = {}
    for path in sorted(engine_package.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files[str(path.relative_to(engine_package))] = hashlib.sha256(path.read_bytes()).hexdigest()
    shared = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(judging)}
    return _digest({
        "checks": [c.model_dump(mode="json") for c in env.checks],
        "agreements": {k: v.model_dump(mode="json") for k, v in env.agreements.items()},
        "thread_variables": env.thread_variables,
        "fixed_variables": env.fixed_variables,
        "engine": files,
        "judging": shared,
    })
