"""The layout, declared as data (projects.md § 4): `femkit/data/project/layout.toml` — or the
test's own, by `FEMKIT_DEFINITIONS_DIR` — declares each part kind, each folder that holds no
part, and the object types inside the parts. The door, the graph, the checks and the page read
this one declaration; adding a part kind is an entry there and its schema, registered at start
(projects.md § 6).

It is read two ways: by its own rules alone (`read`) — what finding projects, `project new`'s
names and `schema check` need — and bound to the part schemas the registry registered (`load`),
a key no package registered refused — what opening a project needs."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, model_validator

from femkit.core.schema import Model, chapter_name, field_named, load_toml, refuse
from femkit.definitions.catalogue import data_root
from femkit.projects import addresses, schemas
from femkit.projects.addresses import Address
from femkit.projects.names import FILE, STEP

Writer = Literal["person", "femkit", "run"]
Moves = Literal["yes", "regenerated", "local"]
KEY = re.compile(r"[a-z][a-z0-9_]*")   # a key a part's file writes bare


class PartKind(Model):
    """One part kind: where its parts live, how each is held, what it loads with, who writes it."""

    folder: str = Field(default="", description="its folder at the project's top, e.g. `studies`; empty for the "
                                                "project file, which lies at the project's top")
    shape: Literal["file", "folder", "single"] = Field(
        description="`file`: each part is `<folder>/<name>.toml`; `folder`: each part is a folder "
                    "`<folder>/<name>/` holding its own file; `single`: the one unnamed part, the project file, "
                    "`project.toml`")
    file: str | None = Field(default=None, description="a `folder` part's own file: `component.toml`")
    files: list[str] = Field(default_factory=list, description="the other files every part of a `folder` kind "
                                                               "holds by a fixed name, from its folder: "
                                                               "`geometry.py`")
    schema_: str = Field(alias="schema", description="the schema it loads with, by the key its owning package "
                                                     "registers it with")
    rank: int = Field(description="its place in the chain's order: what a part is made from comes before it")
    library: bool = Field(default=False, description="whether the projects root holds a global library of its kind, "
                                                     "in a folder of its folder's name; only its names may open "
                                                     "with `GLOBAL/`")
    writer: Writer = Field(default="person", description="who writes its files")
    moves: Moves = Field(default="yes", description="whether it moves with the project, is regenerated, or stays local")
    manual: str | None = Field(default=None, description="for a kind the person writes, the chapter of the user "
                                                         "manual that explains it, by its file's name in "
                                                         "`docs/manual/`, `6-materials.md`: the help of its keys ends "
                                                         "with it (core.md § 2); none: its keys' help names none")

    @model_validator(mode="after")
    def _shape(self) -> "PartKind":
        if self.shape == "file" and (self.file is not None or not self.folder):
            raise ValueError("a `file` part kind has a folder and no `file`: each part is <folder>/<name>.toml")
        if self.shape == "folder" and (self.file is None or not self.folder):
            raise ValueError("a `folder` part kind has a folder and names its parts' own `file`")
        if self.shape == "single" and (self.file is not None or self.folder):
            raise ValueError("the `single` part kind is the project file, project.toml: it names no file or folder")
        if self.files and self.shape != "folder":
            raise ValueError("only a `folder` part holds other files by a fixed name")
        bad = [f for f in self.files if not FILE.fullmatch(f) or f == self.file]
        if bad:
            raise ValueError(f"a fixed file is a path from the part's folder, other than its own file: {', '.join(bad)}")
        if self.library and self.shape == "single":
            raise ValueError("the project file has no library")
        return self

    @property
    def named(self) -> bool:
        return self.shape != "single"


class Folder(Model):
    """A folder that holds no part (projects.md § 4): what femkit or a run writes — cases, runs,
    results, `.femkit` — or the person's own, `custom`. Its files are never read as parts, and
    none is a stray finding."""

    writer: Writer = Field(description="who writes it: femkit, a run, or the person")
    moves: Moves = Field(description="whether it moves with the project, is regenerated, or stays local")


class ObjectType(Model):
    """A type of object inside a part (projects.md § 4): a condition of a physics, a promised group
    of a component, an axis of a study — where it lives, whether it is named, what holds its type,
    and its place in the chain's order."""

    part: str = Field(description="the part kind whose file holds it")
    table: str = Field(description="the table it lives in, as the part's file writes its keys: `conditions`, "
                                   "`inputs.parameters`")
    named: bool = Field(description="whether it is a table of entries, each by its name; else the one object "
                                    "at `table`")
    typed: str | None = Field(default=None, description="the key of an entry holding its type: a condition's `kind`")
    rank: int = Field(description="its place in the chain's order: what it is made from comes before it")

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self.table.split("."))

    def entries(self, data: BaseModel) -> dict[str, Any]:
        """Its entries in a part's loaded file, by key — the one object, under its table's last
        key, when it is not named."""
        found: Any = data
        for key in self.keys:
            found = held(found, key)
        if self.named:
            return dict(found or {})
        return {} if found is None else {self.keys[-1]: found}


def held(value: Any, key: str) -> Any:
    """What a loaded part's value holds under ``key``, as its file writes the key: a model's field
    by its alias or name, or a key it takes beyond its fields; a table's entry; None where there is
    none. The one reading of a part's value by key, whatever schema loaded it."""
    if isinstance(value, BaseModel):
        found = field_named(type(value), key)
        return getattr(value, found[0]) if found else (value.model_extra or {}).get(key)
    return value.get(key) if isinstance(value, dict) else None


class Layout(Model):
    """`project/layout.toml`: every part kind, every folder that holds no part, and the object types
    inside the parts (projects.md § 4). Its validation context may hold `schemas`, the keys the
    packages registered (projects.md § 6): given, each kind's schema is one of them."""

    kinds: dict[str, PartKind] = Field(description="each part kind by the name addresses give it")
    folders: dict[str, Folder] = Field(default_factory=dict, description="each folder that holds no part, by its "
                                                                         "name at the project's top")
    objects: dict[str, ObjectType] = Field(default_factory=dict, description="each type of object inside a part, by "
                                                                             "the name a graph's node gives it")
    editor_files: list[str] = Field(default_factory=list, description="the names of the files an editor keeps beside "
                                    "the one it edits — a backup, a swap file, a lock — each a pattern, `*~`: such a "
                                    "file is no part and no stray, and a copy leaves it out")
    listed: str | None = Field(default=None, description="the part kind whose parts `project list` names beside each "
                                                         "project, its studies (web.md § 8.6); none: no part is named")

    @model_validator(mode="after")
    def _whole(self, info: ValidationInfo) -> "Layout":
        problems: list[tuple[tuple, str]] = []
        problems += [(("kinds", k), "a kind's name is one step of the name rule") for k in self.kinds
                     if not re.fullmatch(STEP, k)]
        single = [k for k, v in self.kinds.items() if v.shape == "single"]
        if len(single) != 1:
            problems.append((("kinds",), f"one part kind is the project file (`shape = \"single\"`); here {len(single)}"))
        places = [v.folder for v in self.kinds.values() if v.folder] + list(self.folders)
        problems += [(("folders",), f"a folder is one step at the project's top: {p}") for p in sorted(places)
                     if "/" in p or p in ("", ".", "..")]
        problems += [(("folders",), f"a folder holds one kind of thing: {p} declared twice")
                     for p in sorted({p for p in places if places.count(p) > 1})]
        for name, o in self.objects.items():
            at = ("objects", name)
            if not re.fullmatch(STEP, name) or name in self.kinds:
                problems.append((at, "an object type's name is one step of the name rule, and no part kind's"))
            if o.part not in self.kinds:
                problems.append(((*at, "part"), f"{o.part!r} is no part kind"))
            if not all(KEY.fullmatch(k) for k in o.keys):
                problems.append(((*at, "table"), f"{o.table!r} is no table: bare keys joined by `.`"))
        problems += [(("editor_files",), f"{p!r} is no pattern of a file's name: not empty, and no `/`")
                     for p in self.editor_files if not p or "/" in p]
        if self.listed is not None and not (self.listed in self.kinds and self.kinds[self.listed].named):
            problems.append((("listed",), f"{self.listed!r} is no part kind whose parts are named"))
        problems += [(("kinds", k, "manual"), f"{v.manual!r} is no chapter of the manual: a file's name in "
                                               "docs/manual/, ending in .md")
                     for k, v in self.kinds.items() if v.manual is not None and not chapter_name(v.manual)]
        registered = (info.context or {}).get("schemas")
        problems += [(("kinds", k, "schema"), f"no package registered the schema {v.schema_!r}")
                     for k, v in self.kinds.items() if registered is not None and v.schema_ not in registered]
        refuse("Layout", problems)
        return self

    @property
    def project_kind(self) -> str:
        return next(k for k, v in self.kinds.items() if v.shape == "single")

    def kind_of(self, schema: str) -> str:
        """The part kind loaded with the schema registered as ``schema`` (projects.md § 4): how a
        package names the kind its own schema is, by its key, never by the kind's name. A
        `KeyError` for a key no kind loads with, a defect."""
        found = [k for k, v in self.kinds.items() if v.schema_ == schema]
        if len(found) != 1:
            raise KeyError(f"{len(found)} part kinds load with the schema {schema!r}, not one")
        return found[0]

    def edited(self, file: str) -> bool:
        """Whether ``file``, a path in a project, is one an editor keeps beside what it edits
        (`editor_files`): no part, no stray, never copied."""
        name = PurePosixPath(file).name
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self.editor_files)

    def person_writes(self) -> list[str]:
        """The folders holding no part that the person writes — where their own files go."""
        return [f for f, v in self.folders.items() if v.writer == "person"]

    def named(self) -> dict[str, bool]:
        """Each kind, and whether its parts are named — what an address is parsed against."""
        return {k: v.named for k, v in self.kinds.items()}

    def address(self, text: str) -> Address:
        """``text`` read as an address against these kinds (projects.md § 5)."""
        return addresses.parse(text, self.named(), self.libraries())

    def libraries(self) -> dict[str, str]:
        """Each kind the projects root holds a global library of, and that library's folder at the
        root (projects.md §§ 1, 4)."""
        return {k: v.folder for k, v in self.kinds.items() if v.library}


def file() -> Path:
    return data_root() / "project" / "layout.toml"


def read() -> Layout:
    """The layout by its own rules: what finding projects, `project new`'s names and `schema
    check` read, before or whether any part schema is registered (projects.md § 4)."""
    return load_toml(file(), Layout)


def load() -> Layout:
    """The layout bound to the part schemas registered at start (projects.md § 6): what opening a
    project reads. A `DefinitionError` names each problem at its key path — a schema no package
    registered among them."""
    return load_toml(file(), Layout, {"schemas": frozenset(schemas.registered())})
