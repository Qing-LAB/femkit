"""Readers of each scheduler kind's answers (jobs.md § 7): one module per kind with commands.

A kind's module is named after its kind file (`femkit/data/schedulers/<kind>.toml`) and
exports ``PROBES``, the probe roles it reads, and ``probe(paths, user)``, which runs that kind's
probe commands and reads their answers into the parts of a machine record (jobs.md § 9.1) as
plain data. The kind file is checked against it when it loads. Nothing here runs at import.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def registered() -> frozenset[str]:
    """The kinds that have readers."""
    return frozenset(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_"))


def readers(kind: str) -> ModuleType | None:
    """The kind's module, or None when it has none."""
    return importlib.import_module(f"{__name__}.{kind}") if kind in registered() else None
