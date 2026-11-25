"""The layout, declared as data (projects.md § 4): `femkit/data/project/layout.toml` — or the
test's own, by `FEMKIT_DEFINITIONS_DIR` — declares each part kind and each folder that holds no
part. The door, the graph, the checks and the page read this one declaration; adding a part kind
is an entry there and its schema, registered at start (projects.md § 6)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, model_validator

from femkit.core.schema import Model, load_toml
from femkit.definitions.catalogue import data_root
from femkit.projects import schemas
from femkit.projects.names import STEP

Moves = Literal["yes", "regenerated", "local"]


class PartKind(Model):
    """One part kind: where its parts live, how each is held, and what it loads with."""

    folder: str = Field(default="", description="its folder at the project's top, e.g. `studies`; empty for the "
                                                "project file, which lies at the project's top")
    shape: Literal["file", "folder", "single"] = Field(
        description="`file`: each part is `<folder>/<name>.toml`; `folder`: each part is a folder "
                    "`<folder>/<name>/` holding its own file; `single`: the one unnamed part, the project file, "
                    "`project.toml`")
    file: str | None = Field(default=None, description="a `folder` part's own file: `component.toml`")
    schema_: str = Field(alias="schema", description="the schema it loads with, by the key its owning package "
                                                     "registers it with")
    rank: int = Field(description="its place in the chain's order: what a part is made from comes before it")
    owner: Literal["project", "global"] = Field(default="project", description="the project's, or the global library's")
    writer: str = Field(default="the person", description="who writes its files")
    moves: Moves = Field(default="yes", description="whether it moves with the project, is regenerated, or stays local")

    @model_validator(mode="after")
    def _shape(self) -> "PartKind":
        if self.shape == "file" and (self.file is not None or not self.folder):
            raise ValueError("a `file` part kind has a folder and no `file`: each part is <folder>/<name>.toml")
        if self.shape == "folder" and (self.file is None or not self.folder):
            raise ValueError("a `folder` part kind has a folder and names its parts' own `file`")
        if self.shape == "single" and (self.file is not None or self.folder):
            raise ValueError("the `single` part kind is the project file, project.toml: it names no file or folder")
        return self

    @property
    def named(self) -> bool:
        return self.shape != "single"


class Folder(Model):
    """A folder that holds no part (projects.md § 4): what femkit or a run writes — cases, runs,
    results, `.femkit` — or the person's own, `custom`. Its files are never read as parts, and
    none is a stray finding."""

    writer: str = Field(description="who writes it: femkit's operation, the run, or the person")
    moves: Moves = Field(description="whether it moves with the project, is regenerated, or stays local")


class Layout(Model):
    """`project/layout.toml`: every part kind, and every folder that holds no part (projects.md § 4).
    Its validation context holds `schemas`, the keys the packages registered (projects.md § 6)."""

    kinds: dict[str, PartKind] = Field(description="each part kind by the name addresses give it")
    folders: dict[str, Folder] = Field(default_factory=dict, description="each folder that holds no part, by its "
                                                                         "name at the project's top")

    @model_validator(mode="after")
    def _whole(self, info: ValidationInfo) -> "Layout":
        bad = [k for k in self.kinds if not re.fullmatch(STEP, k)]
        if bad:
            raise ValueError(f"a kind's name is one step of the name rule: {', '.join(bad)}")
        single = [k for k, v in self.kinds.items() if v.shape == "single"]
        if len(single) != 1:
            raise ValueError(f"one part kind is the project file (`shape = \"single\"`); here {len(single)}")
        places = [v.folder for v in self.kinds.values() if v.folder] + list(self.folders)
        deep = sorted(p for p in places if "/" in p or p in ("", ".", ".."))
        if deep:
            raise ValueError(f"a folder is one step at the project's top: {', '.join(deep)}")
        twice = sorted({p for p in places if places.count(p) > 1})
        if twice:
            raise ValueError(f"a folder holds one kind of thing: {', '.join(twice)} declared twice")
        unknown = sorted({v.schema_ for v in self.kinds.values()} - set((info.context or {}).get("schemas", ())))
        if unknown:
            raise ValueError(f"no package registered the schema {', '.join(unknown)}")
        return self

    @property
    def project_kind(self) -> str:
        return next(k for k, v in self.kinds.items() if v.shape == "single")

    def named(self) -> dict[str, bool]:
        """Each kind, and whether its parts are named — what an address is parsed against."""
        return {k: v.named for k, v in self.kinds.items()}


def file() -> Path:
    return data_root() / "project" / "layout.toml"


def load() -> Layout:
    """The layout, validated against the part schemas registered at start (projects.md § 6), or a
    DefinitionError naming each problem at its key path."""
    return load_toml(file(), Layout, {"schemas": frozenset(schemas.registered())})
