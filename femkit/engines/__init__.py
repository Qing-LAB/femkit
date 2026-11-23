"""Engine adapters, one package per engine (definitions.md § 1).

An engine package registers its ID as ``ENGINE`` and its output readers as
``READERS`` (definitions.md § 5.3). Discovery imports the packages only when
asked; importing them probes and starts nothing. Everything under this package
imports only the standard library and ``femkit.core.process``: check programs
run from it inside engine environments, which hold no femkit dependency.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Output:
    """What a reader is given about one finished check (definitions.md § 5.3)."""

    work: Path              # the check's own fresh folder; its program ran there
    log: Path               # stdout and stderr of the check, together
    test_dir: Path | None   # ctest: the test's working directory in the build tree
    started: float          # when the check started, by the clock of the file system holding its outputs
    ranks: int
    threads: int
    version: str            # the version the environment's definition pins
    upstream_verdict: bool = True  # ctest: whether the test's own pass or fail counts (definitions.md § 5.1)


Reader = Callable[[Output], dict]


def _packages():
    for info in pkgutil.iter_modules(__path__):
        if info.ispkg:
            yield importlib.import_module(f"{__name__}.{info.name}")


def package_dir(engine: str) -> Path:
    """The folder of the engine package that registers ``engine``."""
    return Path(module(engine).__file__).parent


def module(engine: str):
    """The engine package that registers ``engine``."""
    for found in _packages():
        if found.ENGINE == engine:
            return found
    raise KeyError(engine)


def registered() -> dict[str, frozenset[str]]:
    """Every registered engine ID, with the reader IDs it registers."""
    return {m.ENGINE: frozenset(m.READERS) for m in _packages()}


def reader(engine: str, read: str) -> Reader:
    return module(engine).READERS[read]
