"""Judging the toolchain (envs.md § 4.1, § 4.5).

`femkit/engines/toolchain.py` runs inside the environment and measures; this module decides
whether the toolchain is proven and says what a person reads. No source is fetched before it is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from femkit.core import paths, process
from femkit.core.schema import render
from femkit.definitions.models import Toolchain
from femkit.engines.toolchain import LANGUAGES
from femkit.envs import manager
from femkit.envs.manager import Manager

PROGRAM = ["python", "-m", "femkit.engines.toolchain"]
RANKS = 2  # the MPI program's run: two ranks prove the launcher starts more than one


def run(m: Manager, prefix: Path, *args: str, timeout: float = 1800) -> tuple[dict | None, process.ProcessResult]:
    """The toolchain program inside ``prefix``, confined (§ 4.4), with the checkout to import
    it from: (its report, or None when it gave none; what ran)."""
    result = process.run(m.in_prefix(prefix, [*PROGRAM, *args]),
                         env=manager.confined(m.environment, checkout=True), timeout=timeout)
    try:
        return json.loads(result.stdout.strip().splitlines()[-1]), result
    except (ValueError, IndexError):
        return None, result


@dataclass(frozen=True)
class Verdict:
    lines: list[str] = field(default_factory=list)     # what was proven, as a person reads it
    problems: list[str] = field(default_factory=list)  # why it is not proven; empty: proven


def describe(toolchain: Toolchain) -> str:
    """The plan's line for the step."""
    languages = ", ".join(LANGUAGES[lang].name for lang in toolchain.compilers)
    return f"check the toolchain: {languages}" + (f", MPI on {RANKS} ranks" if toolchain.mpi else "") + \
        " — compiled, linked and run inside the prefix"


def spec(toolchain: Toolchain, launcher: list[str] | None) -> dict:
    """What the program is asked to measure."""
    return {"compilers": toolchain.compilers, "mpi": toolchain.mpi,
            "launcher": [render(a, {"ranks": str(RANKS)}) for a in launcher] if toolchain.mpi and launcher else None,
            "tools": toolchain.tools}


def judge(report: dict, prefix: Path) -> Verdict:
    """Every tool and compiler inside the prefix; every trivial program compiled, linked and run
    on this machine — the machine the environment is built on and runs on."""
    v = Verdict()
    outside = [f"{tool} ({where or 'not found'})" for tool, where in report["tools"].items()
               if not paths.inside(where, prefix)]
    if outside:
        v.problems.append("build tools not inside the prefix: " + ", ".join(outside))
    for language, e in report["compilers"].items():
        name = LANGUAGES[language].name
        if not e["value"]:
            v.problems.append(f"{name}: ${e['variable']} is unset: the activation set no compiler")
        elif not e["command"]:
            v.problems.append(f"{name}: ${e['variable']} is {e['value']}, which is not found")
        elif not paths.inside(e["command"], prefix):
            v.problems.append(f"{name}: ${e['variable']} is {e['command']}, outside the prefix")
        elif not e["compiled"]:
            v.problems.append(f"{name}: a trivial program does not compile and link: {e['error']}")
        elif not e["ran"]:
            v.problems.append(f"{name}: a trivial program built here does not run: {e['error']}")
        else:
            version = e["version"].split()[-1] if e["version"] else "?"
            v.lines.append(f"{name:<8} {Path(e['command']).name} {version}: compiles, links and runs")
    if report["mpi"]:
        bad = []
        for language, e in report["mpi"].items():
            if not paths.inside(e["command"], prefix):
                bad.append(f"{e['wrapper']} is {e['command'] or 'not found'}, not inside the prefix")
            elif not e["compiled"]:
                bad.append(f"{e['wrapper']}: does not build an MPI program: {e['error']}")
            elif not e["ran"]:
                bad.append(f"{e['wrapper']}: its program does not run on {RANKS} ranks: {e['error']}")
        v.problems.extend(f"MPI: {b}" for b in bad)
        if not bad:
            v.lines.append(f"{'MPI':<8} {', '.join(e['wrapper'] for e in report['mpi'].values())}: "
                           f"build programs that run on {RANKS} ranks with {Path(report['launcher']).name}")
    return v
