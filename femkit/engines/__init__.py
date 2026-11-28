"""Engine adapters, one package per engine (definitions.md § 1).

An engine package registers its ID as ``ENGINE`` and its output readers as ``READERS``
(definitions.md § 5.3), and, only where its version command prints the version irregularly,
``read_version`` (definitions.md § 4); ``GENERIC`` holds the readers every engine has.
Discovery imports the packages only when asked; importing them probes and starts nothing.
Everything under this package imports only the standard library and ``femkit.core.process``:
check programs run from it inside engine environments, which hold no femkit dependency.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from femkit.engines import junit, summary


@dataclass(frozen=True)
class Output:
    """What a reader is given about one finished check (definitions.md § 5.3): what the check
    wrote in this run, read for the reader by the runner — a reader opens no file — and what the
    check was run with."""

    written: Callable[[str], dict[str, bytes]]   # the files matching a glob pattern in the folder the
    #   check writes into — its own, or a ctest's working directory — written since it started, by name
    ranks: int
    threads: int
    product: str            # what the pinned version is a version of: the engine, or a tool environment
    version: str            # the version the environment's definition pins
    tests: tuple[str, ...] = ()    # pytest: the test node IDs the check names
    upstream_verdict: bool = True  # ctest: whether the test's own pass or fail counts (definitions.md § 5.1)


Reader = Callable[[Output], dict]

#: The readers every engine has, run by the check runner itself (definitions.md § 5.3).
GENERIC: dict[str, Reader] = {"summary": summary.read, "junit": junit.read}


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


def reader(engine: str | None, read: str) -> Reader:
    """The reader ``read`` names: a generic one, or its engine's; a tool environment has no
    engine, and its checks name generic readers only (definitions.md § 4.7)."""
    return GENERIC[read] if read in GENERIC else module(engine).READERS[read]


def last_line(stdout: str, stderr: str) -> str | None:
    """The version a version command printed, as most print it: the last non-empty line of its
    standard output — its standard error may carry MPI or library warnings (definitions.md § 4)."""
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None


def version_reader(engine: str | None) -> Callable[[str, str], str | None]:
    """How an environment's version command's output is read: by its engine's own reader where
    the engine registers one, for output too irregular for the last line — Elmer's — else by
    its last line."""
    return getattr(module(engine), "read_version", last_line) if engine is not None else last_line
