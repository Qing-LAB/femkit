"""The name rule (projects.md § 3): a part's name is its path inside its kind's folder, each
step matching `[a-z][a-z0-9_]*`, the steps joined by `/`; a global material's opens with
`GLOBAL/`. One rule for every name a request takes, a folder holds or `new` makes; for a name the
rule refuses, what in it breaks the rule and the name it would be (`broken`, `mended`); and a name
compared by its whole and by its last step (`whole_or_last`), a form the core's one reading of
what a name most likely meant compares it by (`schema.nearest`)."""

from __future__ import annotations

import re

from femkit.core.errors import UsageError

STEP = r"[a-z][a-z0-9_]*"
NAME = re.compile(rf"{STEP}(?:/{STEP})*")
GLOBAL = "GLOBAL/"   # opens a name that means the global library's (materials.md § 4)

#: A folder part's other file, by its path from the part's folder (projects.md § 6, geometry.md
#: § 3): steps of letters, digits, `.`, `_` and `-`, none starting with `.` or `-` — so none is
#: `..` or hidden — joined by `/`.
FILE_STEP = r"[A-Za-z0-9_][A-Za-z0-9._-]*"
FILE = re.compile(rf"{FILE_STEP}(?:/{FILE_STEP})*")


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


def bare(name: str) -> str:
    """A name as its library holds it, `GLOBAL/` left out: what a case holds a material by
    (materials.md § 6)."""
    return name.removeprefix(GLOBAL)


# ------------------------------------------------------------------ what a name most likely meant

def whole_or_last(name: str) -> tuple[str, ...]:
    """A name compared by its whole name and by its last step, `GLOBAL/` aside — `metals/gold`
    is what `gold` most likely meant (materials.md § 4)."""
    held = bare(name)
    return (held, last(held))


def broken(name: str) -> str | None:
    """What in ``name`` breaks the name rule, `GLOBAL/` allowed before it, as a plain sentence;
    None for a name that keeps it (materials.md § 4: "says what in it breaks the rule")."""
    for i, step in enumerate(bare(name).split("/")):
        if re.fullmatch(STEP, step):
            continue
        if not step:
            return "it has an empty step: two `/` together, or one at an end"
        if i == 0 and step != GLOBAL[:-1] and step.upper() == GLOBAL[:-1]:
            return (f"`{step}` is not `{GLOBAL[:-1]}`: a name is in lowercase, and `{GLOBAL}`, which names the "
                    "global library's, alone is in capitals")
        if step != step.lower():
            return f"`{step}` holds capital letters, and a name is in lowercase"
        if not step[0].isalpha():
            return f"`{step}` starts with `{step[0]}`, and each step starts with a lowercase letter"
        other = next(ch for ch in step if not re.fullmatch(r"[a-z0-9_]", ch))
        return f"`{step}` holds `{other}`, and a step holds lowercase letters, digits and `_` alone"
    return None


def mended(name: str) -> str | None:
    """The name ``name`` most likely meant, by the rule: `GLOBAL/` where its first step is that
    word in other letters, each step in lowercase, each run of other characters one `_`, an
    empty step left out; None where nothing of it keeps the rule."""
    held = [s for s in name.split("/") if s]
    prefix = ""
    if held and held[0].upper() == GLOBAL[:-1]:
        prefix, held = GLOBAL, held[1:]
    made = "/".join(s for s in (re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_") for s in held) if s)
    return prefix + made if valid(made) else None
