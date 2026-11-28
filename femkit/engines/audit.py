"""The install's audit program, run inside an environment (envs.md § 4.1).

It finds where each module the environment provides imports from, and where each compiler
variable the activation set resolves, and reports both as one JSON object on stdout; femkit
judges the report. Like every program under `femkit/engines/`, it imports only the standard
library. What it is handed (`arguments`) and what it reports (`read`) are defined here alone, the
control side building the one and reading the other through them.

    python -m femkit.engines.audit MODULES VARIABLES
        MODULES, VARIABLES: JSON lists — the modules to import, the compiler variables to resolve.
        Prints {"modules": {module: its file | null}, "failures": {module: why it did not import},
                "compilers": {variable: the command it resolves to | null}}
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys


def audit(modules: list[str], variables: list[str]) -> dict:
    origins, failures = {}, {}
    for m in modules:
        try:
            origins[m] = getattr(importlib.import_module(m), "__file__", None)
        except Exception as exc:  # reported whole: a module in the prefix that fails to import says why
            origins[m], failures[m] = None, f"{type(exc).__name__}: {exc}"
    compilers = {v: shutil.which(os.environ[v]) if os.environ.get(v) else None for v in variables}
    return {"modules": origins, "failures": failures, "compilers": compilers}


def arguments(modules: list[str], variables: list[str]) -> list[str]:
    """What the program is handed: the modules to import and the compiler variables to resolve."""
    return [json.dumps(modules), json.dumps(variables)]


def read(stdout: str) -> dict | None:
    """The report the program printed — its last line — or None where it printed none."""
    lines = stdout.strip().splitlines()
    try:
        report = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    return report if isinstance(report, dict) and {"modules", "failures", "compilers"} <= set(report) else None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    print(json.dumps(audit(json.loads(argv[0]), json.loads(argv[1]))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
