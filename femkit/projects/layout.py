"""The layout, declared as data (projects.md § 4): `femkit/data/project/layout.toml` — or the
test's own, by `FEMKIT_DEFINITIONS_DIR` — declares each part kind, each folder that holds no
part, and the object types inside the parts. The door, the graph, the checks and the page read
this one declaration; adding a part kind is an entry there and its schema, registered at start
(projects.md § 6).

It is read two ways: by its own rules alone (`read`) — what finding projects, `project new`'s
names and `schema check` need — and bound to the part schemas the registry registered (`load`),
a key no package registered refused — what opening a project needs. An operation reads it each
way once per invocation, through its context (`read_once`, `load_once`; api.md § 2.4).

Its two orders are each one function here, every caller reading it (projects.md § 4): the
chain's order, `chain` — by rank, then the kind's place in the layout's file, then name: loading,
checking, the order of the findings — and the reading order, `reading` — by section, then rank,
then the kind's place, then name: everything a person reads lists parts so. An object type takes
its part kind's rank, section and place."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, model_validator

from femkit.core.errors import UsageError
from femkit.core.operations import Context
from femkit.core.schema import Model, chapter_name, field_named, load_toml, parsed, refuse
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
    optional: list[str] = Field(default_factory=list, description="the other files a part of its kind may hold by a "
                                "fixed name, read where they are there: from a `folder` part's folder, or, for the "
                                "project file, from the project's top — `definitions.py`")
    schema_: str = Field(alias="schema", description="the schema it loads with, by the key its owning package "
                                                     "registers it with")
    rank: int = Field(description="its place in the chain's order: what a part is made from comes before it")
    section: str = Field(description="where a person finds it: one of the layout's `sections`, which gives their "
                                     "order")
    library: bool = Field(default=False, description="whether the projects root holds a global library of its kind, "
                                                     "in a folder of its folder's name; only its names may open "
                                                     "with `GLOBAL/`")
    writer: Writer = Field(default="person", description="who writes its files")
    moves: Moves = Field(default="yes", description="whether it moves with the project, is regenerated, or stays local")
    was: Literal["file"] | None = Field(default=None, description="for a `folder` kind whose parts were once each "
                                        "one file, `<folder>/<name>.toml`: `file` — a file of that form is told that "
                                        "the kind is now a folder, never left a stray",
                                        json_schema_extra={"doc": "projects.md § 4"})
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
            raise ValueError("only a `folder` part holds other files by a fixed name that it must hold")
        if self.optional and self.shape == "file":
            raise ValueError("a `file` part has no folder to hold other files in")
        bad = [f for f in [*self.files, *self.optional] if not FILE.fullmatch(f) or f == self.file
               or (self.shape == "single" and "/" in f)]
        if bad:
            raise ValueError(f"a fixed file is a path from the part's folder, other than its own file — the project "
                             f"file's, a name at the project's top: {', '.join(bad)}")
        if both := sorted(set(self.files) & set(self.optional)):
            raise ValueError(f"a file is fixed or optional, never both: {', '.join(both)}")
        if self.library and self.shape == "single":
            raise ValueError("the project file has no library")
        if self.was is not None and self.shape != "folder":
            raise ValueError("only a `folder` kind was once another shape: its parts' files of that shape are told so")
        return self

    @property
    def named(self) -> bool:
        return self.shape != "single"


#: What the door forms inside a folder that holds no part (projects.md §§ 2, 6), each by what it is,
#: with the steps its path is formed from: a stage's calculation folder, by its study, its kind and
#: its ID (workflow.md § 4); a launch folder, by its study and its name (jobs.md § 1.2); a case's
#: file, by its study and its ID (models.md § 5.3); a study's computed definitions' values, kept,
#: by its study (models.md § 3). The layout declares each once.
FORMED = {"stage": ("study", "kind", "id"), "launch": ("study", "name"), "case": ("study", "id"),
          "definitions": ("study",)}


class Folder(Model):
    """A folder that holds no part (projects.md § 4): what femkit or a run writes — cases, runs,
    results, `.femkit` — or the person's own, `custom`. Its files are never read as parts, and
    none is a stray finding."""

    writer: Writer = Field(description="who writes it: femkit, a run, or the person")
    moves: Moves = Field(description="whether it moves with the project, is regenerated, or stays local")
    holds: dict[str, str] = Field(default_factory=dict, description="what the door forms inside it, each by what it "
                                  "is — a stage's calculation folder, `stage`; a launch folder, `launch`; a case's "
                                  "file, `case`; a study's kept definitions, `definitions` — with its path from this "
                                  "folder, each step it is formed from a placeholder of its own: `{study}/{kind}/{id}`",
                                  json_schema_extra={"placeholders": sorted({s for f in FORMED.values() for s in f})})


def _formed_problems(what: str, path: str) -> list[str]:
    """What is wrong with ``path``, the declared path of what the door forms as ``what``: a
    relative path of steps, each a placeholder of its own or a fixed name, naming each step
    ``what`` is formed from once and nothing else."""
    if what not in FORMED:
        return [f"the door forms no {what!r}: it forms {', '.join(FORMED)}"]
    problems = []
    steps = path.split("/")
    if any(s in ("", ".", "..") for s in steps):
        problems.append(f"{path!r} is no path inside its folder: steps joined by `/`, none `.` or `..`")
    found = [(s, p) for s in steps for p in parsed(s)]
    if any(p.optional or p.argument is not None or p.span != (0, len(s)) for s, p in found):
        problems.append(f"{path!r}: each placeholder is a whole step of its own, `{{study}}`, with no `?` or argument")
    named = sorted(p.name for _, p in found)
    if named != sorted(FORMED[what]):
        problems.append(f"{path!r} names {', '.join('{%s}' % n for n in named) or 'nothing'}; a {what} is formed "
                        f"from {', '.join('{%s}' % n for n in FORMED[what])}, each once")
    if not problems and not all(FILE.fullmatch(s) for s in steps if not parsed(s)):
        problems.append(f"{path!r}: a fixed step is a file's name: letters, digits, `.`, `_` and `-`")
    return problems


class ObjectType(Model):
    """A type of object inside a part (projects.md § 4): a condition of a physics, a promised group
    of a component, an axis of a study — where it lives, whether it is named and what holds its
    type; its place in both orders is its part kind's."""

    part: str = Field(description="the part kind whose file holds it")
    table: str = Field(description="the table it lives in, as the part's file writes its keys: `conditions`, "
                                   "`inputs.definitions`")
    named: bool = Field(description="whether it is a table of entries, each by its name; else the one object "
                                    "at `table`")
    typed: str | None = Field(default=None, description="the key of an entry holding its type: a condition's `kind`")

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

    sections: list[str] = Field(min_length=1, description="the sections a person finds the parts in, in their "
                                "order, from what is shared to what is computed: Definitions, Component, Physics, "
                                "Mesh, Study, Results", json_schema_extra={"doc": "projects.md § 4"})
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
        problems += [(("kinds", k), f"`{k}:` names what femkit makes, so no part kind is named {k!r} (they are: "
                                    f"{', '.join(addresses.MADE)})") for k in self.kinds if k in addresses.MADE]
        single = [k for k, v in self.kinds.items() if v.shape == "single"]
        if len(single) != 1:
            problems.append((("kinds",), f"one part kind is the project file (`shape = \"single\"`); here {len(single)}"))
        places = [v.folder for v in self.kinds.values() if v.folder] + list(self.folders)
        problems += [(("folders",), f"a folder is one step at the project's top: {p}") for p in sorted(places)
                     if "/" in p or p in ("", ".", "..")]
        problems += [(("folders",), f"a folder holds one kind of thing: {p} declared twice")
                     for p in sorted({p for p in places if places.count(p) > 1})]
        problems += [(("folders", f, "holds", what), problem) for f, v in self.folders.items()
                     for what, path in v.holds.items() for problem in _formed_problems(what, path)]
        declared = [what for v in self.folders.values() for what in v.holds]
        problems += [(("folders",), f"the door forms a {what} in one folder: declared "
                                    f"{'in none' if declared.count(what) == 0 else 'twice'}")
                     for what in FORMED if declared.count(what) != 1]
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
        problems += [(("sections",), f"{s!r} is declared twice: each section once, in its order")
                     for s in sorted({s for s in self.sections if self.sections.count(s) > 1})]
        problems += [(("kinds", k, "section"), f"{v.section!r} is none of the sections ({', '.join(self.sections)})")
                     for k, v in self.kinds.items() if v.section not in self.sections]
        problems += [(("kinds", k, "manual"), f"{v.manual!r} is no chapter of the manual: a file's name in "
                                               "docs/manual/, ending in .md")
                     for k, v in self.kinds.items() if v.manual is not None and not chapter_name(v.manual)]
        registered = (info.context or {}).get("schemas")
        problems += [(("kinds", k, "schema"), f"no package registered the schema {v.schema_!r}")
                     for k, v in self.kinds.items() if registered is not None and v.schema_ not in registered]
        refuse("Layout", problems)
        return self

    def part_kind(self, kind: str) -> str:
        """A part kind's name — for an object type, its part kind's, whose place it takes."""
        return self.objects[kind].part if kind in self.objects else kind

    def kind(self, kind: str) -> PartKind:
        """A part kind's declaration — for an object type, its part kind's, whose place it takes."""
        return self.kinds[self.part_kind(kind)]

    def chain(self, kind: str, name: str | None) -> tuple[int, int, str]:
        """A part's place — or an object's, its part's — in the chain's order (projects.md § 4):
        by its kind's rank, then the kind's place in the layout's file, then its name. What a part
        is made from comes before it: loading, checking, and the order of the findings."""
        return self.kind(kind).rank, list(self.kinds).index(self.part_kind(kind)), name or ""

    def reading(self, kind: str, name: str | None) -> tuple[int, int, int, str]:
        """A part's place — or an object's, its part's — in the reading order (projects.md § 4): by
        its kind's section, in the sections' order, then its rank, then the kind's place in the
        layout's file, then its name. Everything a person reads lists parts so."""
        return self.sections.index(self.kind(kind).section), *self.chain(kind, name)

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

    def formed(self, what: str) -> str:
        """Where the door forms ``what`` — a stage's folder, a launch folder, a case's file, a
        study's kept definitions — as the layout declares it: its folder at the project's top, then
        its path there, each step it is formed from a placeholder (`runs/{study}/{kind}/{id}`)."""
        return next(f"{f}/{v.holds[what]}" for f, v in self.folders.items() if what in v.holds)

    def person_writes(self) -> list[str]:
        """The folders holding no part that the person writes — where their own files go."""
        return [f for f, v in self.folders.items() if v.writer == "person"]

    def named(self) -> dict[str, bool]:
        """Each kind, and whether its parts are named — what an address is parsed against."""
        return {k: v.named for k, v in self.kinds.items()}

    def address(self, text: str, made: bool = False) -> Address | addresses.Made:
        """``text`` read as an address against these kinds (projects.md § 5): a part, a value in
        it, or a folder part's file; with ``made``, or what femkit makes — a stage, a launch
        folder, a job. Refused, `bad-address`, otherwise."""
        found = addresses.parse(text, self.named(), self.libraries(),
                                {k: v.file for k, v in self.kinds.items() if v.shape == "folder"})
        if not made and not isinstance(found, Address):
            raise UsageError(f"{text!r} names what femkit makes; a part, a value in one or a part's file is asked for "
                             "here", code="bad-address", subject=text)
        return found

    def fixed(self) -> dict[str, list[str]]:
        """Each part kind, with the files every part of it holds by a fixed name: what a stage
        kind's `brings`, and the file its program runs, are held to (definitions.md § 2.2)."""
        return {k: list(v.files) for k, v in self.kinds.items()}

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


def read_once(ctx: Context) -> Layout:
    """The layout by its own rules (`read`), read once per invocation (api.md § 2.4)."""
    return ctx.cached("project/layout", read)


def load_once(ctx: Context) -> Layout:
    """The layout bound to the registered part schemas (`load`), read once per invocation."""
    return ctx.cached("project/layout bound", load)
