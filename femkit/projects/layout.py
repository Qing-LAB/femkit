"""The layout, declared as data (projects.md § 4): `femkit/data/project/layout.toml` — or the
test's own, by `FEMKIT_DEFINITIONS_DIR` — declares each part kind and each folder femkit writes.
The door, the graph, the checks, the templates and the page read this one declaration; adding a
part kind is an entry there and its schema."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from femkit.core.schema import Model, load_toml
from femkit.definitions.catalogue import data_root
from femkit.projects import schemas
from femkit.projects.names import STEP
from femkit.projects.project import PROJECT_FILE

Moves = Literal["yes", "regenerated", "local"]


class PartKind(Model):
    """One part kind: where its parts live, how each is held, and what it loads with."""

    folder: str = Field(default="", description="its folder in the project, e.g. `studies`; empty for the "
                                                "project file, which lies at the project's top")
    shape: Literal["file", "folder", "single"] = Field(
        description="`file`: each part is `<folder>/<name>.toml`; `folder`: each part is a folder "
                    "`<folder>/<name>/` holding its own file; `single`: the one unnamed part, the project file")
    file: str | None = Field(default=None, description="a part's own file: `component.toml` in a `folder` part, "
                                                       "`project.toml` for the `single` one")
    schema_: str = Field(alias="schema", description="the schema it loads with, as its owning package registers it")
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
        if self.shape == "single" and (self.file is None or self.folder):
            raise ValueError("the `single` part kind names its `file` and has no folder")
        return self

    @property
    def named(self) -> bool:
        return self.shape != "single"


class WrittenFolder(Model):
    """A folder femkit writes that holds no part: runs, cases, results, `.femkit`."""

    writer: str = Field(description="who writes it")
    moves: Moves = Field(description="whether it moves with the project, is regenerated, or stays local")


class Layout(Model):
    """`project/layout.toml`: every part kind, and every folder femkit writes (projects.md § 4)."""

    kinds: dict[str, PartKind] = Field(description="each part kind by the name addresses give it")
    folders: dict[str, WrittenFolder] = Field(default_factory=dict, description="each folder femkit writes "
                                                                                "that holds no part, by its path")

    @model_validator(mode="after")
    def _whole(self) -> "Layout":
        import re
        bad = [k for k in self.kinds if not re.fullmatch(STEP, k)]
        if bad:
            raise ValueError(f"a kind's name is one step of the name rule: {', '.join(bad)}")
        single = [k for k, v in self.kinds.items() if v.shape == "single"]
        if len(single) != 1:
            raise ValueError(f"one part kind is the project file (`shape = \"single\"`); here {len(single)}")
        if self.kinds[single[0]].file != PROJECT_FILE:
            raise ValueError(f"the project file is {PROJECT_FILE}: what makes a folder a project (projects.md § 2)")
        places = [v.folder for v in self.kinds.values() if v.folder] + list(self.folders)
        twice = sorted({p for p in places if places.count(p) > 1})
        if twice:
            raise ValueError(f"a folder holds one kind of thing: {', '.join(twice)} declared twice")
        unknown = sorted({v.schema_ for v in self.kinds.values()} - set(schemas.registered()))
        if unknown:
            raise ValueError(f"no package registered the schema {', '.join(unknown)}")
        return self

    @property
    def project_kind(self) -> str:
        return next(k for k, v in self.kinds.items() if v.shape == "single")

    def named(self) -> dict[str, bool]:
        """Each kind, and whether its parts are named — what an address is parsed against."""
        return {k: v.named for k, v in self.kinds.items()}

    def ordered(self) -> list[str]:
        """The kinds in the chain's order."""
        return sorted(self.kinds, key=lambda k: (self.kinds[k].rank, k))


def file() -> Path:
    return data_root() / "project" / "layout.toml"


def load() -> Layout:
    """The layout, or a DefinitionError naming each problem at its key path."""
    return load_toml(file(), Layout)
