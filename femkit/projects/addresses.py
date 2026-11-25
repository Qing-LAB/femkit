"""Addresses (projects.md § 5): one grammar names every part and every value in it,

    <kind>:<name>[:<dotted path>]

The kinds are the layout's; a kind with one unnamed part (the project file) is written
`<kind>:<dotted path>`. A dotted path's keys are bare (`[A-Za-z0-9_-]+`) or quoted as TOML
quotes them: `study:sweeps/gap_sweep:axes."project:parameters.gap"`. Entries are keyed by
name, never by position.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from femkit.core.errors import UsageError
from femkit.projects import names

BARE = re.compile(r"[A-Za-z0-9_-]+")


def _refuse(text: str, why: str) -> UsageError:
    return UsageError(f"{text!r} is no address: {why}; an address is <kind>:<name>[:<dotted path>]",
                      code="bad-address", subject=text)


def split_path(text: str, whole: str | None = None) -> tuple[str, ...]:
    """A dotted path's keys: bare, or double-quoted as TOML quotes a key."""
    keys, i = [], 0
    while i < len(text):
        if text[i] == '"':
            end = i + 1
            while end < len(text) and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            if end >= len(text):
                raise _refuse(whole or text, "a quoted key is not closed")
            keys.append(json.loads(text[i:end + 1]))
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


def join_path(keys: tuple[str, ...]) -> str:
    return ".".join(k if BARE.fullmatch(k) else json.dumps(k) for k in keys)


@dataclass(frozen=True)
class Address:
    kind: str
    name: str | None            # None: the kind's one unnamed part, the project file
    path: tuple[str, ...] = ()  # the value's keys inside the part; () the part itself

    def __str__(self) -> str:
        head = self.kind if self.name is None else f"{self.kind}:{self.name}"
        return f"{head}:{join_path(self.path)}" if self.path else head

    @property
    def part(self) -> "Address":
        return Address(self.kind, self.name)


def parse(text: str, kinds: dict[str, bool]) -> Address:
    """``text`` as an address; ``kinds`` maps each of the layout's kinds to whether its parts
    are named (the project file's is not)."""
    kind, sep, rest = text.partition(":")
    if kind not in kinds:
        raise _refuse(text, f"no kind {kind!r}; kinds: {', '.join(sorted(kinds))}")
    if not kinds[kind]:
        return Address(kind, None, split_path(rest, text) if sep and rest else ())
    if not sep or not rest:
        raise _refuse(text, f"a {kind} is named")
    name, sep, path = rest.partition(":")
    bare = name.removeprefix(names.GLOBAL)
    if not names.valid(bare):
        raise _refuse(text, f"{name!r} breaks the name rule: lowercase steps joined by `/`")
    return Address(kind, name, split_path(path, text) if sep and path else ())
