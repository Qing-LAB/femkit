"""The record of the model's edits, for undo and redo (models.md § 11.1): each edit's files with
their text before and after it, in `<project>/.femkit/history/history.json`; the last
`HISTORY` edits are kept."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from femkit.core.persist import read_json, write_json
from femkit.core.schema import Model, matching, validate
from femkit.models.schema import STUDY

HISTORY = 100  # the edits `model undo` reaches back through; to be the setting `projects.undo` (config.md § 3)
FILE = Path(".femkit") / "history" / "history.json"


class Change(Model):
    study: str | None = matching(STUDY, description="the file: a study's, by its name; none: the model's — never a "
                                                    "path, so a record cannot name a file outside its project")
    before: str | None = Field(description="its text before the edit; none: it did not exist")
    after: str | None = Field(description="its text after the edit; none: it was removed")


class Edit(Model):
    label: str = Field(description="what the edit did, as its plan says it")
    changes: list[Change] = Field(description="each file it changed")


class History(Model):
    edits: list[Edit] = Field(default_factory=list, description="the edits, oldest first")
    at: int = Field(default=0, description="how many of them stand: the rest were undone")


def read(project: Path) -> History:
    path = project / FILE
    return validate(History, read_json(path), path) if path.is_file() else History()


def write(project: Path, history: History) -> None:
    write_json(project / FILE, history.model_dump(mode="json"))


def record(project: Path, label: str, changes: list[Change]) -> None:
    """An edit made: what was undone past it can no longer be redone."""
    h = read(project)
    edits = [*h.edits[:h.at], Edit(label=label, changes=changes)][-HISTORY:]
    write(project, History(edits=edits, at=len(edits)))


def text_of(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None

