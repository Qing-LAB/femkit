"""The name rule (projects.md § 3): a part's name is its path inside its kind's folder, each
step matching `[a-z][a-z0-9_]*`, the steps joined by `/`; a global material's opens with
`GLOBAL/`. One rule for every name a request takes, a folder holds or `new` makes."""

from __future__ import annotations

import re

from femkit.core.errors import UsageError

STEP = r"[a-z][a-z0-9_]*"
NAME = re.compile(rf"{STEP}(?:/{STEP})*")
GLOBAL = "GLOBAL/"   # opens a name that means the global library's (materials.md § 4)


def valid(name: str) -> bool:
    return bool(NAME.fullmatch(name))


def check(name: str, *, what: str = "a name") -> str:
    """``name``, or a refusal saying the rule."""
    if not isinstance(name, str) or not valid(name):
        raise UsageError(f"{name!r} is not {what}: steps of lowercase letters, digits and `_`, each starting "
                         "with a letter, joined by `/`", code="bad-name", subject=str(name))
    return name


def steps(name: str) -> list[str]:
    return name.split("/")


def group(name: str) -> str | None:
    """The group a name lies in, or None at the top of its kind's folder."""
    return name.rpartition("/")[0] or None


def last(name: str) -> str:
    return name.rpartition("/")[2]
