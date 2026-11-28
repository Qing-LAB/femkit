"""The toolchain's own program, run inside an environment (definitions.md § 4.6; envs.md § 4.1).

It measures and reports, as one JSON object on stdout; femkit judges the report. Like every
program under `femkit/engines/`, it imports only the standard library and `femkit.core.process`.
What it is asked (`spec`) and what it reports (`read`) are defined here alone, the control side
building the one and reading the other through them.

    python -m femkit.engines.toolchain check SPEC WORK
        before any source is fetched: where each tool and compiler resolves, and whether a
        trivial program in each language compiles, links and runs — with MPI, built with the
        environment's wrappers and run with the launcher SPEC gives. SPEC is a JSON file:
        {"compilers": {language: variable}, "mpi": {language: wrapper},
         "launcher": argv, its ranks filled in | null, "tools": [executable]}
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from femkit.core import process


@dataclass(frozen=True)
class Language:
    name: str                   # as a person reads it
    flags: str                  # the variable the activation sets to its flags, as CMake reads it
    program: tuple[str, str]    # (file, a program that prints ok)
    mpi: tuple[str, str]        # (file, a program that starts and stops MPI)


_MPI_C = "#include <mpi.h>\nint main(int c, char **v) { MPI_Init(&c, &v); MPI_Finalize(); return 0; }\n"
# Every language a toolchain may name — the one list, which the definitions' schema reads; a test
# runs the program on each of them.
LANGUAGES = {
    "c": Language("C", "CFLAGS", ("t.c", '#include <stdio.h>\nint main(void) { puts("ok"); return 0; }\n'),
                  ("m.c", _MPI_C)),
    "cxx": Language("C++", "CXXFLAGS",
                    ("t.cpp", '#include <iostream>\nint main() { std::cout << "ok" << std::endl; return 0; }\n'),
                    ("m.cpp", _MPI_C)),
    "fortran": Language("Fortran", "FFLAGS", ("t.f90", 'program t\n  print *, "ok"\nend program t\n'),
                        ("m.f90", "program m\n  use mpi\n  integer :: e\n  call MPI_Init(e)\n"
                                  "  call MPI_Finalize(e)\nend program m\n")),
}
SAID = 300  # characters of a failure's first line kept in the report


def _first_line(result: process.ProcessResult) -> str:
    for line in (result.stderr + "\n" + result.stdout).splitlines():
        if line.strip():
            return line.strip()[:SAID]
    return f"exit {result.returncode}"


def _flags(variable: str) -> list[str]:
    return shlex.split(os.environ.get(variable, ""))


def _launch(argv: list[str], work: Path, timeout: float) -> process.ProcessResult | str:
    """What ``argv`` did, or why it could not start — not found, not executable, a file the
    kernel cannot run: said as a finding, so the findings made before it are still reported."""
    try:
        return process.run(argv, cwd=work, timeout=timeout)
    except OSError as exc:
        return f"{argv[0]}: {exc.strerror or exc}"


def _start(argv: list[str], work: Path, timeout: float) -> tuple[bool, str]:
    """Whether ``argv`` exits 0, and its first error line; one that cannot start fails too."""
    result = _launch(argv, work, timeout)
    if isinstance(result, str):
        return False, result
    return result.ok, "" if result.ok else _first_line(result)


def _try(build: list[str], run: list[str], work: Path) -> dict:
    """Compile and link with ``build``, then run ``run``: what happened at each."""
    compiled, error = _start(build, work, 300)
    if not compiled:
        return {"compiled": False, "ran": False, "error": error}
    ran, error = _start(run, work, 120)
    return {"compiled": True, "ran": ran, "error": error}


def check(spec: dict, work: Path) -> dict:
    report: dict = {"tools": {t: shutil.which(t) for t in spec["tools"]}, "compilers": {}, "mpi": {}}
    for language, variable in spec["compilers"].items():
        name, source = LANGUAGES[language].program
        (work / name).write_text(source, encoding="utf-8")
        value = os.environ.get(variable, "")
        command = shutil.which(value) if value else None
        entry: dict = {"variable": variable, "value": value, "command": command, "version": ""}
        if command:
            version = _launch([command, "--version"], work, 60)
            entry["version"] = version.stdout.splitlines()[0] \
                if not isinstance(version, str) and version.ok and version.stdout else ""
            exe = f"./{language}.out"
            entry.update(_try([command, *_flags(LANGUAGES[language].flags), name, *_flags("LDFLAGS"), "-o", exe],
                              [exe], work))
        report["compilers"][language] = entry
    for language, wrapper in spec["mpi"].items():
        name, source = LANGUAGES[language].mpi
        (work / name).write_text(source, encoding="utf-8")
        command = shutil.which(wrapper)
        entry = {"wrapper": wrapper, "command": command}
        if command:
            exe = f"./mpi-{language}.out"
            entry.update(_try([command, name, *_flags("LDFLAGS"), "-o", exe], [*spec["launcher"], exe], work))
        report["mpi"][language] = entry
    if spec["mpi"]:
        report["launcher"] = shutil.which(spec["launcher"][0])
    return report


def spec(compilers: dict[str, str], mpi: dict[str, str], launcher: list[str] | None, tools: list[str]) -> dict:
    """What the program is asked to measure: each language's compiler variable, each language's MPI
    wrapper, the launcher that runs an MPI program — its ranks filled in — and the build tools."""
    return {"compilers": compilers, "mpi": mpi, "launcher": launcher, "tools": tools}


def read(stdout: str) -> dict | None:
    """The report the program printed — its last line — or None where it printed none."""
    lines = stdout.strip().splitlines()
    try:
        report = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    return report if isinstance(report, dict) and {"tools", "compilers", "mpi"} <= set(report) else None


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "check":
        print(json.dumps(check(json.loads(Path(argv[1]).read_text(encoding="utf-8")), Path(argv[2]))))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
