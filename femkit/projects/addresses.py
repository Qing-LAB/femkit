"""Addresses (projects.md § 5): one grammar names every part and every value in it,

    <kind>:<name>[:<dotted path>]

The kinds are the layout's; a kind with one unnamed part (the project file) is written
`<kind>:<dotted path>`. A name opens with `GLOBAL/` only for a kind the layout declares with a
library (projects.md § 4). A dotted path's keys are bare (`[A-Za-z0-9_-]+`) or quoted as TOML
quotes them: `study:sweeps/gap_sweep:axes."project:definitions.gap"`. Entries are keyed by
name, never by position.

The same grammar names a file of a folder part, by its path from the part's folder —
`<kind>:<name>@<file>`, `component:bowtie@geometry.py`; the part's own file is named by the part's
address alone — and what femkit makes, each by a form no part kind can take (`MADE`): a stage,
`stage:<study>/<kind>/<id>`, its last two steps its kind and ID (workflow.md § 4); a launch
folder, `launch:<study>/<name>` (jobs.md § 1.2); a job launched from this machine, `job:<id>`
(jobs.md § 5.4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Collection, Mapping

from femkit.core.errors import UsageError
from femkit.core.persist import BARE, plain_value
from femkit.core.schema import key_path
from femkit.projects import names

#: A stage's ID: the SHA-256 of what it is made from, in hexadecimal (workflow.md § 4).
ID = re.compile(r"[0-9a-f]{64}")
#: A launch folder's name or a job's ID: one step of a file's path, so never `..` nor hidden.
FILE_STEP = re.compile(names.FILE_STEP)


def _refuse(text: str, why: str) -> UsageError:
    return UsageError(f"{text!r} is no address: {why}; an address is <kind>:<name>[:<dotted path>], "
                      f"<kind>:<name>@<file>, or one of {', '.join(f'{form}:…' for form in MADE)}",
                      code="bad-address", subject=text)


def split_path(text: str, whole: str | None = None) -> tuple[str, ...]:
    """A dotted path's keys: bare, or double-quoted as TOML quotes a key, read as TOML reads it —
    by the core's reader of a TOML value (core.md § 4)."""
    keys, i = [], 0
    while i < len(text):
        if text[i] == '"':
            end = i + 1
            while end < len(text) and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            if end >= len(text):
                raise _refuse(whole or text, "a quoted key is not closed")
            try:
                keys.append(plain_value(text[i:end + 1]))
            except ValueError as exc:
                raise _refuse(whole or text, f"a quoted key is not one TOML reads: {exc}") from None
            i = end + 1
        else:
            match = BARE.match(text, i)
            if not match:
                raise _refuse(whole or text, f"a key must be bare or quoted, at {text[i:]!r}")
            keys.append(match.group())
            i = match.end()
        if i < len(text):
            if text[i] != ".":
                raise _refuse(whole or text, f"keys are joined by `.`, at {text[i:]!r}")
            i += 1
            if i == len(text):
                raise _refuse(whole or text, "a dotted path does not end with `.`")
    return tuple(keys)


@dataclass(frozen=True)
class Address:
    kind: str
    name: str | None            # None: the kind's one unnamed part, the project file
    path: tuple[str, ...] = ()  # the value's keys inside the part; () the part itself
    file: str | None = None     # a file of a folder part, by its path from the part's folder

    def __str__(self) -> str:
        head = self.kind if self.name is None else f"{self.kind}:{self.name}"
        if self.file is not None:
            return f"{head}@{self.file}"
        return f"{head}:{key_path(self.path)}" if self.path else head

    @property
    def part(self) -> "Address":
        return Address(self.kind, self.name)


@dataclass(frozen=True)
class Stage:
    """A stage (workflow.md § 4): its study's name, its kind and its ID."""

    study: str
    kind: str
    id: str

    def __str__(self) -> str:
        return f"stage:{self.study}/{self.kind}/{self.id}"


@dataclass(frozen=True)
class Launch:
    """A launch folder of a study (jobs.md § 1.2): the study's name and the folder's."""

    study: str
    name: str

    def __str__(self) -> str:
        return f"launch:{self.study}/{self.name}"


@dataclass(frozen=True)
class Job:
    """A job launched from this machine (jobs.md § 5.4), by its ID."""

    id: str

    def __str__(self) -> str:
        return f"job:{self.id}"


Made = Stage | Launch | Job


def _stage(text: str, rest: str) -> Stage:
    steps = rest.split("/")
    study = "/".join(steps[:-2])
    if len(steps) < 3 or not names.valid(study):
        raise _refuse(text, "a stage is named by its study's name, then its kind and its ID")
    kind, id_ = steps[-2:]
    if not re.fullmatch(names.STEP, kind):
        raise _refuse(text, f"{kind!r} is no stage kind's name: one step of the name rule")
    if not ID.fullmatch(id_):
        raise _refuse(text, f"{id_!r} is no stage's ID: a SHA-256, in 64 hexadecimal digits")
    return Stage(study, kind, id_)


def _launch(text: str, rest: str) -> Launch:
    study, _, name = rest.rpartition("/")
    if not names.valid(study):
        raise _refuse(text, "a launch folder is named by its study's name, then its own")
    if not FILE_STEP.fullmatch(name):
        raise _refuse(text, f"{name!r} is no launch folder's name: letters, digits, `.`, `_` and `-`, not starting "
                            "with `.` or `-`")
    return Launch(study, name)


def _job(text: str, rest: str) -> Job:
    if not FILE_STEP.fullmatch(rest):
        raise _refuse(text, f"{rest!r} is no job's ID: letters, digits, `.`, `_` and `-`, not starting with `.` or "
                            "`-`")
    return Job(rest)


#: What femkit makes, each by the form that names it (projects.md § 5): forms no part kind may take.
MADE = {"stage": _stage, "launch": _launch, "job": _job}


def parse(text: str, kinds: Mapping[str, bool], libraries: Collection[str] = (),
          folders: Mapping[str, str] | None = None) -> Address | Made:
    """``text`` as an address; ``kinds`` maps each of the layout's kinds to whether its parts
    are named (the project file's is not), ``libraries`` names the kinds whose names may open
    with `GLOBAL/`, and ``folders`` maps each kind whose parts are folders to its parts' own file,
    which the part's address alone names."""
    kind, sep, rest = text.partition(":")
    if kind in MADE:
        return MADE[kind](text, rest)
    if kind not in kinds:
        raise _refuse(text, f"no kind {kind!r}; kinds: {', '.join(sorted(kinds))}")
    if not kinds[kind]:
        return Address(kind, None, split_path(rest, text) if sep and rest else ())
    if not sep or not rest:
        raise _refuse(text, f"a {kind} is named")
    head, at, file = rest.partition("@")
    name, sep, path = head.partition(":")
    bare = name.removeprefix(names.GLOBAL)
    if bare != name and kind not in libraries:
        raise _refuse(text, f"only a name of a kind with a global library opens with {names.GLOBAL!r}: "
                            f"{', '.join(sorted(libraries)) or 'none'}")
    if not names.valid(bare):
        raise _refuse(text, f"{name!r} breaks the name rule: lowercase steps joined by `/`")
    if not at:
        return Address(kind, name, split_path(path, text) if sep and path else ())
    own = (folders or {}).get(kind)
    if own is None or sep:
        raise _refuse(text, f"only a part that is a folder holds files, each named after the part's name: "
                            f"{', '.join(sorted(folders or {})) or 'none'}")
    if not names.FILE.fullmatch(file):
        raise _refuse(text, f"{file!r} is no file of a part's folder: steps of letters, digits, `.`, `_` and `-`, "
                            "none starting with `.` or `-`")
    if file == own:
        raise _refuse(text, f"{own} is the {kind}'s own file, which `{kind}:{name}` names")
    return Address(kind, name, file=file)
