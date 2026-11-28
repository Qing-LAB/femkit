"""The documents a stage's programs are handed and leave (geometry.md §§ 2–8; workflow.md § 2;
jobs.md §§ 2, 5.1; models.md § 9.1): each defined once, here, with its `schema` number — built and
checked by this module, written and read through it by every program that runs inside an
environment.

Standard library only: it lies beside each femkit program that runs in a job, which imports it as
`documents` (framework.md § 1) — `job prepare` copies it into the calculation folder with the
programs a request names (jobs.md § 1.1); femkit's control process imports it as
`femkit.engines.stages.documents`, builds a document with `make` and writes it with its own writer
(`core.persist`), and checks one it reads with `check`. This folder has no `__init__.py`, so the
discovery of engine adapters (`femkit/engines/__init__.py`), which takes every package here for
one, passes it by; Python imports it all the same, as a namespace package.

The documents, each `{"schema": <its number>, …}` — 1, but where `CHANGES` raises it — and the
fields below:

- `inputs` — `inputs.json`, what the person's script is handed (geometry.md § 2), schema 2:
  `definitions`, each declared definition's value as a number, a length in the frame's unit, an
  angle in degrees;
- `contract` — `contract.json`, what the geometry stage's check is handed (geometry.md § 3): the
  frame's `dimension`, its axis of revolution `axis` (`x`, `y`, or null), the `groups` it
  promises, each with its dimension, `mesh`, the geometry order of the mesh the script writes too
  where the contract declares one (null where it does not), and `brep`, whether the check writes
  the geometry's shapes as BREP too, for a mesher that reads them (geometry.md § 8);
- `groups` — `groups.json`, what the geometry stage's check observed (geometry.md § 7): each
  promised group's `pieces` — the geometry's entities in it, each by its dimension and tag with
  its measure (a length, area or volume in the frame's unit; null for a point); `unpromised`, each
  group the script made that the contract does not promise, alike with its name; `bodies`, every
  entity of the frame's dimension; `faces`, every entity of one dimension less, with the bodies
  it bounds and the bodies it lies inside (`embedded_in`);
- `recipe` — `recipe.json`, what the mesh stage is handed (geometry.md §§ 5, 6): the frame's
  `dimension` and promised `groups`, and the recipe resolved in the frame's unit — `size`,
  `order`, `tolerance`, `growth` and `quality` (null where unset), `sizes`;
- `regions` — `regions.json`, a mesher's region map (geometry.md § 5): the mesh's `dimension`
  and `order`, and each group's `dimension`, `elements`, `measure` in the mesh, `geometry` (its
  measure in the geometry), `difference` (relative) and `quality` (its worst element's, for a
  group of the mesh's dimension), each measure null for a point;
- `handover` — `handover.json`, what an engine's hand-over is handed (geometry.md § 8): the
  `groups` it hands the engine, each with its dimension;
- `report` — `report.json`, what NGSolve's hand-over found (geometry.md § 8): the mesh's
  `dimension`, and each group's `dimension`, the `region` NGSolve holds it as, its `elements`
  and its `measure` as NGSolve integrates it (null for a point);
- `checked` — a run's `checked.json`, a stage's check's verdict (jobs.md §§ 2, 5.1): `passed`,
  and its `reason`, null when passed;
- `outputs` — a run's `outputs.json`, written by a stage's check when it passed (jobs.md § 2):
  `files`, each output the stage wrote, by its path from the run, with its SHA-256.

A program checks only a document's shape — its keys and the kind of each value; what a value
may be is checked where the person wrote it (`project check`), before anything runs. A document of
another schema than its kind's is refused before its shape is read, saying what it is: the schema
it states, the one read, and what changed between them (models.md § 2).
"""

from __future__ import annotations

import hashlib
import json
import math
import os

#: What changed in a kind's shape, by the schema that changed it: a kind's documents are written
#: under its last, 1 where none is listed, and a document of another is told what changed between
#: them (models.md § 2).
CHANGES: dict[str, dict[int, str]] = {
    "inputs": {2: "`definitions` in place of `parameters`, each definition the contract declares by its name"},
}


def schema(kind: str) -> int:
    """The schema ``kind``'s documents are written and read under."""
    return max(CHANGES.get(kind, {}), default=1)


class Malformed(ValueError):
    """A document that is not of its kind's shape, with what is wrong."""


# A shape: `int`, `float` (any finite number), `str`, `bool`; `None` (null); a tuple, one of its
# shapes; a list of one shape, a list of it; `Each(shape)`, an object keyed by names, each value of
# the shape; a dict, an object with exactly those keys.
class Each:
    def __init__(self, shape):
        self.shape = shape


NUMBER = float
#: The records a stage's check writes into its run (jobs.md §§ 2, 5.1), each a document of this
#: module's: its verdict, and, when passed, each output's SHA-256 — named here once, for the
#: programs beside it and for femkit, which reads the kinds of a stage, its run's catalogue and
#: its run's records by them; each written by `judged`.
CHECKED, OUTPUTS = "checked", "outputs"
RECORDS = (CHECKED, OUTPUTS)
PIECE = {"dimension": int, "tag": int, "measure": (NUMBER, None)}
GROUPS = Each(int)   # each group by name, with its dimension

SHAPES = {
    "inputs": {"definitions": Each(NUMBER)},
    "contract": {"dimension": int, "axis": (str, None), "groups": GROUPS, "mesh": (int, None), "brep": bool},
    "groups": {"dimension": int, "groups": Each({"dimension": int, "pieces": [PIECE]}),
               "unpromised": [{"name": str, "dimension": int, "pieces": [PIECE]}],
               "bodies": [int], "faces": [{"tag": int, "bodies": [int], "embedded_in": [int]}]},
    "recipe": {"dimension": int, "groups": GROUPS, "size": NUMBER, "order": int, "tolerance": NUMBER,
               "growth": (NUMBER, None), "quality": (NUMBER, None), "sizes": Each(NUMBER)},
    "regions": {"dimension": int, "order": int,
                "groups": Each({"dimension": int, "elements": int, "measure": (NUMBER, None),
                                "geometry": (NUMBER, None), "difference": (NUMBER, None),
                                "quality": (NUMBER, None)})},
    "handover": {"groups": GROUPS},
    "report": {"dimension": int, "groups": Each({"dimension": int, "region": str, "elements": int,
                                                 "measure": (NUMBER, None)})},
    CHECKED: {"passed": bool, "reason": (str, None)},
    OUTPUTS: {"files": Each(str)},
}


def make(kind: str, **fields) -> dict:
    """A document of ``kind`` holding ``fields``, under its kind's schema, checked; Malformed,
    naming what is wrong."""
    return check(kind, {"schema": schema(kind), **fields})


def check(kind: str, document) -> dict:
    """``document`` itself when it is of ``kind``'s shape under its kind's schema; Malformed
    otherwise: one of another schema saying what it is — the schema it states, the one read and
    what changed between them — any other naming the first place that is not of the shape."""
    current = schema(kind)
    stated = document.get("schema") if isinstance(document, dict) else None
    if isinstance(stated, int) and not isinstance(stated, bool) and stated != current:
        changed = [f"since schema {n}, {what}" for n, what in sorted(CHANGES.get(kind, {}).items())
                   if min(stated, current) < n <= max(stated, current)]
        raise Malformed(f"the {kind} document is of schema {stated}, and this program reads schema {current}"
                        + (f": {'; '.join(changed)}" if changed else ""))
    wrong = _wrong(document, {"schema": int, **SHAPES[kind]}, kind)
    if wrong is not None:
        raise Malformed(f"not a {kind} document of schema {current}: {wrong}")
    return document


def read(path: str, kind: str) -> dict:
    """The document of ``kind`` at ``path``; Malformed when it is missing, is no JSON, or is not
    of the shape."""
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, ValueError) as exc:
        raise Malformed(f"{os.path.basename(path)} does not read: {exc}") from None
    return check(kind, document)


def write(path: str, kind: str, document: dict) -> None:
    """The one writer of a program's documents: checked, then written whole or not at all — to a
    name beside it, renamed into place — with sorted keys, two-space indent and a final newline,
    as femkit writes JSON everywhere."""
    check(kind, document)
    part = f"{path}.part"
    with open(part, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(part, path)


def judged(checked: str, outputs: str, reason: str | None, files: list[str]) -> None:
    """A stage's check's two records (jobs.md §§ 2, 5.1): when ``reason`` is None, each of
    ``files`` — the stage's outputs, by their paths as given — with its SHA-256, into ``outputs``,
    each made read-only; then the verdict into ``checked``, passed, or failed with ``reason``. The
    verdict is written last, so a passed one is never read without what it recorded."""
    if reason is None:
        write(outputs, OUTPUTS, make(OUTPUTS, files={f: sha256(f) for f in files}))
        for f in files:   # what a workflow shares is never changed where it was made (jobs.md § 2)
            os.chmod(f, os.stat(f).st_mode & ~0o222)
    write(checked, CHECKED, make(CHECKED, passed=reason is None, reason=reason))


def sha256(path: str) -> str:
    """A file's SHA-256, read in blocks: a mesh may be large."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _wrong(value, shape, at: str) -> str | None:
    """Where ``value`` first departs from ``shape``, in words; None when it does not."""
    if isinstance(shape, tuple):
        if any(_wrong(value, s, at) is None for s in shape):
            return None
        return f"{at} is {_kind(value)}, not {' or '.join(_kind_of(s) for s in shape)}"
    if shape is None:
        return None if value is None else f"{at} is {_kind(value)}, not null"
    if shape is NUMBER:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        return None if ok else f"{at} is {_kind(value)}, not a finite number"
    if shape in (int, str, bool):
        ok = isinstance(value, shape) and (shape is bool or not isinstance(value, bool))
        return None if ok else f"{at} is {_kind(value)}, not {_kind_of(shape)}"
    if isinstance(shape, list):
        if not isinstance(value, list):
            return f"{at} is {_kind(value)}, not a list"
        return next((w for i, v in enumerate(value) if (w := _wrong(v, shape[0], f"{at}[{i}]"))), None)
    if not isinstance(value, dict):
        return f"{at} is {_kind(value)}, not an object"
    if isinstance(shape, Each):
        return next((w for k, v in value.items() if (w := _wrong(v, shape.shape, f"{at}.{k}"))), None)
    missing, extra = sorted(shape.keys() - value.keys()), sorted(value.keys() - shape.keys())
    if missing or extra:
        return f"{at} lacks {', '.join(missing)}" if missing else f"{at} holds {', '.join(extra)}, no key of it"
    return next((w for k, s in shape.items() if (w := _wrong(value[k], s, f"{at}.{k}"))), None)


def _kind(value) -> str:
    return {bool: "true or false", int: "a whole number", float: "a number", str: "a text", list: "a list",
            dict: "an object", type(None): "null"}.get(type(value), type(value).__name__)


def _kind_of(shape) -> str:
    if shape is None:
        return "null"
    if shape is NUMBER:
        return "a finite number"
    return {int: "a whole number", str: "a text", bool: "true or false"}.get(shape, "of its shape")
