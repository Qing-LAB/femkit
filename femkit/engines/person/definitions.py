"""femkit's program for a project's `definitions.py` (models.md § 3; ADR 0021), run in
`model_prep`: a project's computed definitions, each computed by its function in the project's
`definitions.py`, at each set of the constants femkit hands it, and their values kept in one file
of the one store.

    python -P -m femkit.engines.person.definitions DOCUMENT VALUES

DOCUMENT is the JSON document femkit writes for one run, in the shape `document` gives it — the
one home of that shape, which femkit's control side builds it by: its `schema`; `file`, the
person's `definitions.py`, as femkit read it, copied beside the document; `definitions`, each
definition by its name — its `type` (`int`, `float` or `complex`), `units`, its SI unit as text,
`declared_unit`, its unit as the project file declares it, `long_name`, what it is — the comment
above its table, else its name — and, for a computed one, `function`, the function that computes
it, its `line` in the file, and `needs`, the computed definitions it reads, through any function it
calls; `order`, the computed ones in the order their reads give; `sets`, each set of the constants,
every constant by its name with its value in SI — a number of its type, a complex one `[real,
imaginary]`; and `attributes`, the file's provenance — the study, the SHA-256 of `definitions.py`,
the script that computes them, of the project file's `[definitions]` table, and the environment
with its install fingerprint — which VALUES carries as its own attributes, beside its `schema`. No
time: the run's records hold it, so the same values are the same bytes.

For each set it builds `project.definitions` — a module holding every constant of the set, then
each computed definition as its function returns it, in their order — imports the person's file
once, and calls each function. Each result is held to its definition's type by the one check of a
typed value (`values.checked`), as the project file's check holds a value written. Every value
written is in SI, as the function returned it; femkit converts it into its declared unit.

It prints, as it goes, one JSON line before each call — `{"computing": <name>, "point": <n>}` — so
a run stopped past its time limit names the call it was in; and, at its end, one JSON line holding
every failure, `{"failures": [...]}`, each with the definition, the point, the line of the person's
file it failed at and why; a definition reading one that failed at a point is not called there.
Those keys are named here alone (`COMPUTING`, `POINT`, `FAILURES`), which femkit reads them by.
With no failure it writes VALUES whole, through the one store's writer (`values.write`), and exits
0; otherwise it writes nothing and exits 1.

VALUES (models.md § 3, "The kept values"): along one dimension, `point`, one entry per set; one
variable per constant and per computed definition, of its declared type — a complex one by
netCDF4's complex convention — each with its metadata; the file's `schema`, `SHAPE`, and the
document's attributes, as its own.

It runs inside `model_prep`, through the environment's own `run`, from the clean start, femkit's checkout on its
import path: it imports the standard library, its own package's modules, and numpy and xarray, which
the environment provides, and nothing else of femkit's.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback
import types

from femkit.engines.person import values as typed
from femkit.engines.person.values import Failed

DOCUMENT = 2                   # the shape of the document femkit hands it
SHAPE = 2                      # the shape of the file of values, its `schema` (models.md § 2)
DIMENSION = "point"
#: The keys of what it says, one JSON object a line: before each call, the definition it computes and
#: the point; at its end, every failure.
COMPUTING, POINT, FAILURES = "computing", "point", "failures"


def document(file: str, definitions: dict, order: list[str], sets: list[dict], attributes: dict) -> dict:
    """The document femkit hands this program for one run, in its one shape (above): the person's
    file's name beside it, each definition, the computed ones' order, each set of the constants,
    and the provenance of the values."""
    return {"schema": DOCUMENT, "file": file, "definitions": definitions, "order": order, "sets": sets,
            "attributes": attributes}


def read(path: str) -> dict:
    """The document femkit wrote: a JSON object of its shape."""
    with open(path, encoding="utf-8") as f:
        document = json.load(f)
    if not isinstance(document, dict) or document.get("schema") != DOCUMENT:
        raise ValueError(f"{os.path.basename(path)} is not a document of schema {DOCUMENT}")
    return document


def number(kind: str, held):
    """A constant as the document holds it, as a plain number of its type."""
    if kind == "complex":
        return complex(held[0], held[1])
    return int(held) if kind == "int" else float(held)


def where(exc: BaseException, file: str, line: int | None) -> int | None:
    """The line of the person's file an exception was raised at — its innermost frame there — or
    the function's own line, where no frame is the file's."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if os.path.abspath(f.filename) == file]
    return frames[-1].lineno if frames else line


def imported(file: str, defs: types.ModuleType) -> types.ModuleType:
    """The person's file, imported once, `project.definitions` the module ``defs``."""
    package = types.ModuleType("project")
    package.__path__ = []
    package.definitions = defs
    sys.modules["project"], sys.modules["project.definitions"] = package, defs
    spec = importlib.util.spec_from_file_location("definitions", file)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise Failed(where(exc, file, None), f"importing it raised {type(exc).__name__}: {exc}") from None
    return module


def say(line: dict) -> None:
    print(json.dumps(line), flush=True)


def called(function) -> tuple[object, int | None]:
    """What ``function`` returns, called with no arguments, and the line it returned at — its own
    `return`, as Python's profiler sees the call end."""
    returned: dict[str, int] = {}

    def profile(frame, event, arg):
        if event == "return" and frame.f_code is function.__code__:
            returned["line"] = frame.f_lineno

    sys.setprofile(profile)
    try:
        value = function()
    finally:
        sys.setprofile(None)
    return value, returned.get("line")


def compute(document: dict, file: str) -> tuple[list[dict], list[dict]]:
    """Each set's values — every constant and every computed definition — and every failure."""
    declared, order = document["definitions"], document["order"]
    defs = types.ModuleType("project.definitions")
    try:
        module = imported(file, defs)
    except Failed as exc:
        return [], [{"definition": None, "point": None, "line": exc.line, "reason": exc.reason}]
    values, failures, failed_once = [], [], set()
    for point, constants in enumerate(document["sets"]):
        held = {name: number(declared[name]["type"], value) for name, value in constants.items()}
        defs.__dict__.clear()
        defs.__dict__.update(__name__="project.definitions", **held)
        failed: set[str] = set()
        for name in order:
            spec = declared[name]
            if failed & set(spec["needs"]):
                failed.add(name)
                continue
            say({COMPUTING: name, POINT: point})
            try:
                value, line = called(getattr(module, spec["function"]))
                held[name] = typed.checked(spec["type"], value, line or spec["line"])
            except Failed as exc:
                failed.add(name)
                failures += [] if name in failed_once else [
                    {"definition": name, "point": point, "line": exc.line, "reason": exc.reason}]
                failed_once.add(name)
                continue
            except Exception as exc:
                failed.add(name)
                failures += [] if name in failed_once else [
                    {"definition": name, "point": point, "line": where(exc, file, spec["line"]),
                     "reason": f"raised {type(exc).__name__}: {exc}"}]
                failed_once.add(name)
                continue
            setattr(defs, name, held[name])
        values.append(held)
    return values, failures


def write(path: str, document: dict, values: list[dict]) -> None:
    """The kept values, written whole by the one store's writer: along `point`, each definition a
    variable of its type with its metadata; the document's attributes the file's, beside its
    `schema`."""
    variables = {name: {"type": spec["type"], "dims": (DIMENSION,), "values": [v[name] for v in values],
                        "units": spec["units"], "declared_unit": spec["declared_unit"],
                        "long_name": spec["long_name"]}
                 for name, spec in document["definitions"].items()}
    typed.write(path, variables, {typed.SCHEMA: SHAPE, **document["attributes"]})


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -P -m femkit.engines.person.definitions DOCUMENT VALUES", file=sys.stderr)
        return 2
    sys.dont_write_bytecode = True           # the person's file is only read: nothing is cached beside it
    document = read(argv[0])
    file = os.path.abspath(os.path.join(os.path.dirname(argv[0]), document["file"]))
    values, failures = compute(document, file)
    say({FAILURES: failures})
    if failures:
        return 1
    write(argv[1], document, values)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
