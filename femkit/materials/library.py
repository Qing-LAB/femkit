"""The global library's offer (materials.md § 4): femkit's shipped materials are copied into a new
projects root's library by `project new`, and are the person's from then on; while femkit's
shipped material no longer has the digest the library's record holds for its copy, and the
person's copy differs from femkit's file as it is now, a project using that library material is
told so — offered, never applied: femkit never writes the person's copy (projects.md § 7). Once
the copy matches femkit's file, nothing is said. The check is declared here, beside the
material's schema key, and registered at femkit's start after the material's own (projects.md
§ 6; api.md § 6).

Its finding, on the library material the project uses (core.md § 10):
- `shipped-changed` (info): the keys at which the person's copy and femkit's shipped file
  differ — some may be the person's own edits — and where femkit's file is.
"""

from __future__ import annotations

from typing import Any, Iterator

from femkit.core.issues import Issue
from femkit.core.schema import key_path, load_text
from femkit.definitions import catalogue
from femkit.materials.material import KEY
from femkit.projects import door, names
from femkit.projects.checking import Checking, Registration
from femkit.projects.door import Part

_ABSENT = object()   # a key one side holds and the other does not


def differing(mine: Any, theirs: Any, at: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """The key paths at which two materials, each as its schema loads it, differ: a value either holds otherwise, or a key
    one holds and the other does not — a table one lacks named once, by its own key."""
    if isinstance(mine, dict) and isinstance(theirs, dict):
        return [p for k in sorted(set(mine) | set(theirs))
                for p in differing(mine.get(k, _ABSENT), theirs.get(k, _ABSENT), (*at, k))]
    return [] if mine == theirs else [at]


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """A library material the project uses whose femkit's shipped original changed since it was
    copied, while the person's copy is not femkit's file as it is now (module docstring); nothing
    for the project's own, for one the library's record does not name, for one femkit ships no
    more, or for a copy whose files are femkit's now — each compared by the digest of its folder's
    files, as the record holds it (`door.shipped`)."""
    if not part.library:
        return
    listed = c.opened.libraries.get(part.address.kind)
    name = names.bare(part.address.name)
    recorded = listed.shipped.get(name) if listed is not None else None
    now = door.shipped(c.opened.layout, part.address.kind).get(name) if recorded is not None else None
    if now is None or now.digest == recorded or listed.digests.get(name) == now.digest:
        return
    theirs = load_text(catalogue.shipped(now.file), type(part.data), now.file, {"units": c.units}) \
        if part.data is not None else None
    keys = differing(part.data.model_dump(by_alias=True), theirs.model_dump(by_alias=True)) if theirs else []
    which = (f"these keys differ from your copy, and some may be your own edits: "
             f"{', '.join(f'`{key_path(k)}`' for k in keys)}" if keys
             else "its keys are your copy's; its comments or its other files differ")
    yield c.issue(part, code="shipped-changed", severity="info",
                  message=f"femkit's shipped `{name}` has changed since it was copied into your library, and is "
                          f"offered, never applied: {which}; femkit's file is {now.file}")


REGISTERS = Registration(checks={KEY: check})
