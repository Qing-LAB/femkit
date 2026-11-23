"""Addresses: one grammar names every object, in edits, graph nodes, match lines, decisions
and `covers` (models.md § 11.1): `<file>:<dotted path>`, where `<file>` is `model` or
`study:<study>`, and each step is a table key, quoted when it is not a bare key —
`model:regions.left`, `study:sweep:axes."numerics.mesh.size"`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from femkit.core.errors import UsageError
from femkit.models.project import model_file, study_file

BARE = re.compile(r"[A-Za-z0-9_-]+")
STUDY = re.compile(r"[a-z][a-z0-9_-]*")


@dataclass(frozen=True)
class Address:
    study: str | None          # None: the model
    path: tuple[str, ...]

    @property
    def file(self) -> str:
        return "model" if self.study is None else f"study:{self.study}"

    def __str__(self) -> str:
        steps = [p if BARE.fullmatch(p) else '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"' for p in self.path]
        return f"{self.file}:{'.'.join(steps)}"

    def child(self, *steps: str) -> "Address":
        return Address(self.study, (*self.path, *steps))

    def on_disk(self, project: Path) -> Path:
        return model_file(project) if self.study is None else study_file(project, self.study)


def _steps(text: str, whole: str) -> tuple[str, ...]:
    steps, at = [], 0
    while at < len(text):
        if text[at] == '"':
            end, value = at + 1, []
            while end < len(text) and text[end] != '"':
                if text[end] == "\\" and end + 1 < len(text):
                    end += 1
                value.append(text[end])
                end += 1
            if end >= len(text):
                raise UsageError(f"{whole!r}: a quoted step is not closed")
            steps.append("".join(value))
            at = end + 1
        else:
            match = BARE.match(text, at)
            if not match:
                raise UsageError(f"{whole!r}: a step is a bare key ([A-Za-z0-9_-]+) or a quoted one")
            steps.append(match.group())
            at = match.end()
        if at < len(text):
            if text[at] != ".":
                raise UsageError(f"{whole!r}: steps are joined by dots")
            at += 1
            if at == len(text):
                raise UsageError(f"{whole!r} ends with a dot")
    return tuple(steps)


def parse(text: str) -> Address:
    """`model:<path>` or `study:<study>:<path>`."""
    if text.startswith("model:"):
        return Address(None, _steps(text[len("model:"):], text))
    if text.startswith("study:"):
        name, sep, rest = text[len("study:"):].partition(":")
        if not sep or not STUDY.fullmatch(name):
            raise UsageError(f"{text!r}: a study's address is study:<study>:<path>")
        return Address(name, _steps(rest, text))
    raise UsageError(f"{text!r}: an address starts with `model:` or `study:<study>:` (models.md § 11.1)")
