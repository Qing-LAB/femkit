"""Listing and opening a project (projects.md §§ 2, 3, 6): each part kind's tree read from its
folder as the layout declares it; each part loaded through its registered schema on its own —
a part that does not load is a finding on that part, and every other part is still read; a
folder part's other files — those its kind fixes, those it may hold, those its own file declares —
and the files the project file may hold at the project's top (its `definitions.py`), read once,
each with its bytes and digest; a file no part kind declares is a finding, never read. A part's text
— or a folder part's file's — is the file as it holds it, comments kept (`text`), and with its
SHA-256 the file a node of the project's graph opens as (`file`). The references between parts are read from the
schemas' `ref` annotations. A project may be opened with one file's text in place of the file's,
in memory (`open_project`'s `texts`): a save's impact (projects.md § 7). One part's file may be
read on its own, never the project opened (`read_alone`): a reader that needs one table of it
alone, through that table's schema — each project file's `[postprocess]` (projects.md § 6).

The door writes a file the person wrote only as they typed it in the page's text editor
(`save_text`, projects.md § 7): exactly the text, refused, `Refused` · `file-changed`, when the
file's SHA-256 is not the one it had when it was opened. femkit's own outputs — a case's file —
it reads and writes itself, `read_output` and `write_output` — and a file femkit made elsewhere,
copied in whole, `copy_output` — each in a folder the layout declares femkit writes, refused
elsewhere: `UsageError`, code `not-femkits`. What it forms inside a folder that holds no part — a
case's file (`case_file`, and the cases written, `cases`), a study's kept definitions
(`definitions_file`), a stage's calculation folder (`stage_folder`, and a study's stages, `stages`)
and a launch folder (`launch_folder`), where the jobs domain writes — it forms as the layout declares (projects.md
§§ 2, 4, 6); the steps such a path takes after a study's name, which no study's name may take
(`made_steps`), are what `project check` holds a study's name to (§ 5). A new folder part the person
brings — a material `material import` writes from another source's file (materials.md § 7) — it
writes whole where nothing is, in a project or a global library (`new_part`, `write_part`), never
over or into one: `Refused`, code `exists` or `inside-part`, its subject the new part's name. A
file an editor keeps beside what it edits (the layout's `editor_files`) is not looked at: no part,
no stray, never copied.

The global library of each kind the layout declares with one (materials.md § 4) is read when a
project opens: whether the root holds it yet, the parts it holds, by name, and its record of what
`project new` copied into it from femkit's shipped parts (`materials/.femkit/shipped.json`); and
each part of it a loaded part of the project names — `GLOBAL/<name>`, or a name the project holds
no part of — loaded as the project's own are, its address `<kind>:GLOBAL/<name>` and its files
named by their full paths, since they lie outside the project, with the digest of its folder's
files, as femkit's shipped parts are digested. A part of it the project no longer names — one a
case holds — is loaded the same way when an operation asks (`load_library`). `named` finds the
part a name names: `GLOBAL/<name>` the library's; any other the project's own first, then the
library's. femkit's shipped parts (`femkit/data/materials/`) are read as a library is
(`shipped`), and `seed` writes them into a new library with its record, one folder written whole
— never over anything there, and never a library without its record.

The findings opening makes, each an `Issue` (core.md § 10) carrying the file the person opens
and, where there is one, the key, each message a plain sentence that leaves both to the finding:
- `unloadable` (error), subject the part's address, one for each problem at its key path, with
  what would be right there (`schema.problems`, core.md § 2): its file does not load;
- `missing-file` (error): a file the part's kind fixes, or its own file declares, is not there —
  subject the part's address and file the missing one's path, or subject the declaring key's
  address and file the part's own;
- `unreadable` (error), likewise: such a file is there and cannot be read;
- `outside-part` (error), subject the declaring key's address: a declared file whose path
  leaves the part's folder, or is hidden;
- `now-a-folder` (error), subject the file's path in the project: a file of the form a folder
  kind's parts once had, `observables/<o>.toml` — its part is now a folder (projects.md § 4);
- `stray` (warning), subject the file's path in the project: a file in the tree no part kind
  declares, or in a loaded part's folder that neither its kind fixes nor its file declares —
  never read; its message names the folder the person's own files go in. A library's folders are
  not the project's tree, and hold no stray;
- `unloadable` (warning), subject the record's full path: a library's record of femkit's copies
  that does not load — read as recording none.

A check says what it cannot check yet as an `info` finding, code `not-checked-yet` (`UNCHECKED`,
projects.md § 6), which a part's state reads (projects.md § 8).

A refusal met in a project becomes a finding one way, `finding_of`: `Issue.of`, placed at its part's
file, key and line where its subject is a part's address or a value's in it (core.md § 10).

A part's text, or a value's, that cannot be given is refused: `UsageError` `unloadable`, subject
the address asked for — a part that could not be read, a value in a part that is not TOML. A text
in place of a file the project does not hold is refused: `UsageError` `no-such-file`, subject its
address.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Literal, Mapping

from pydantic import Field

from femkit.core import persist, view
from femkit.core.errors import Refusal, Refused, UsageError
from femkit.core.text import path as shown_path
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.schema import (DefinitionError, Model, Problem, key_path, load_text, parsed, references as cited,
                                render)
from femkit.core.view import Action
from femkit.definitions import catalogue
from femkit.projects import layout as layouts
from femkit.projects import addresses, names, schemas
from femkit.projects.requests import PROJECT_SAVE
from femkit.projects.addresses import Address
from femkit.projects.layout import Layout, PartKind
from femkit.projects.project import PROJECT_FILE, Library, Project
from femkit.projects.requests import PROJECT_NEW

FILE_REF = "file"               # a `ref` naming a file in the part's own folder, by its path from it (projects.md § 6)
UNCHECKED = "not-checked-yet"   # the finding of what cannot be checked yet (projects.md § 6)
SHIPPED = ".femkit/shipped.json"   # a library's record of femkit's copies, from its folder (materials.md § 4)

Home = Project | Library        # where a part's files lie: the project, or a global library


def in_library(address: Address) -> bool:
    """Whether ``address`` names a global library's part: its name opens with `GLOBAL/`
    (projects.md § 5)."""
    return address.name is not None and address.name.startswith(names.GLOBAL)


@dataclass(frozen=True)
class Part:
    address: Address
    file: str                    # its own file: from the project's folder; a library's by its full path
    data: Model | None           # None: it does not load (its finding says why)
    folder: str | None = None    # a folder part's folder, as its file is named; None for a part that is one file

    @property
    def library(self) -> bool:
        """Whether it is a global library's, which the project names (materials.md § 4)."""
        return in_library(self.address)


@dataclass(frozen=True)
class Held:
    """A folder part's other file — one its kind fixes, or its own file declares — as read once
    when the project opened (projects.md § 6): the case's digest of a script and the page's view
    of it read these bytes."""

    part: Address
    name: str                    # its path from the part's folder, as fixed or declared
    file: str                    # as its part's file is named: from the project's folder, or by its full path
    key: tuple[str, ...]         # the key in the part's own file that declares it; () for one its kind fixes
    data: bytes
    sha256: str


@dataclass(frozen=True)
class Listed:
    """A global library as read when the project opened (materials.md § 4): where it lies, whether
    the root holds it yet, the parts it holds by name, its record of each part copied into it from
    femkit's shipped parts, with the digest of femkit's files then, and, for each of its parts
    loaded, the digest of its folder's files now — each digest as `shipped` digests femkit's."""

    library: Library
    there: bool
    names: tuple[str, ...]
    shipped: dict[str, str]
    digests: dict[str, str] = field(default_factory=dict)


@dataclass
class Opened:
    """A project as read once: every operation receives it, none reads a file again on its own."""

    project: Project
    layout: Layout
    parts: dict[str, Part] = field(default_factory=dict)          # by str(address): the project's, and the
                                                                  # library parts it names
    issues: list[Issue] = field(default_factory=list)             # what opening found
    texts: dict[str, str] = field(default_factory=dict)           # every part's file as read
    sha256: dict[str, str] = field(default_factory=dict)          # each of those files' SHA-256, as read
    files: tuple[str, ...] = ()                                   # every file of the tree
    held: dict[str, Held] = field(default_factory=dict)           # each folder part's other files, by path
    libraries: dict[str, Listed] = field(default_factory=dict)    # each kind's global library, by the kind

    def part(self, address: Address) -> Part:
        found = self.parts.get(str(address.part))
        if found is None:
            raise UsageError(f"no {address.kind} {address.name!r} in the project {self.project.name}",
                             code="no-such-part", subject=str(address.part))
        return found

    def owner(self, subject: str) -> Part | None:
        """The part a finding's subject names — its address, a value's in it, or a file of it,
        `<kind>:<name>@<file>` (projects.md § 5): `observe.py`'s findings are its part's; none for a
        file that is no part's."""
        return next((p for a, p in self.parts.items() if subject == a or subject.startswith((a + ":", a + "@"))),
                    None)

    def held_by(self, address: Address) -> dict[str, Held]:
        """A folder part's other files as read, by their paths from its folder."""
        return {h.name: h for h in self.held.values() if h.part == address.part}


def named(opened: Opened, kind: str, name: str) -> Part | None:
    """The part a name of ``kind`` names, loaded or not (materials.md § 4): for a kind the layout
    declares with a global library, `GLOBAL/<name>` names the library's, and any other name the
    project's own first, then the library's; for any other kind, the project's own. None where
    neither holds it."""
    k = opened.layout.kinds.get(kind)
    if k is None:
        return None
    if not name.startswith(names.GLOBAL) and (own := opened.parts.get(str(Address(kind, name)))) is not None:
        return own
    return opened.parts.get(str(Address(kind, names.GLOBAL + name.removeprefix(names.GLOBAL)))) if k.library else None


def known(opened: Opened, kind: str) -> list[str]:
    """Every name of ``kind`` a part may cite, as it would write it: the project's own parts, and
    `GLOBAL/<name>` for each its global library holds (materials.md § 4)."""
    own = sorted(p.address.name for p in opened.parts.values() if p.address.kind == kind and not p.library)
    listed = opened.libraries.get(kind)
    return own + [names.GLOBAL + n for n in listed.names] if listed is not None else own


def finding(opened: Opened, at: Address, *, code: str, message: str, severity: str = "error",
            right: str | None = None, choices: Iterable[str] = (), label: str | None = None,
            next: Iterable[Action] = ()) -> Issue:
    """A finding on a part, or a value in it (core.md § 10): its subject the address, its file the
    part's own — read here from the address, never formed by the domain that found it — its key the
    address's dotted path, and the line that key stands at, read from the file's text as it opened;
    ``right`` and ``choices`` as the file would write them."""
    part = opened.part(at)
    key = key_path(at.path) or None
    return Issue(severity=severity, code=code, subject=str(at), label=label, message=message, file=part.file,
                 key=key, line=line_of(opened, part.file, key), right=right, choices=tuple(choices),
                 next=tuple(next))


def finding_of(opened: Opened, refusal: Refusal, severity: str, message: str | None = None) -> Issue:
    """``refusal`` as a finding in the project (core.md § 10): by the one way, `Issue.of` — its code,
    its subject and its next steps kept, its message its own unless one is given, a refusal naming
    no subject refused there — and, where its subject is a part's address or a value's in it,
    placed where the person opens it: the part's file, the address's key and the line that key
    stands at, read here (`line_of`), never formed by the domain that met it."""
    issue = Issue.of(refusal, severity, message)
    part = opened.owner(issue.subject)
    if part is None:
        return issue
    key = key_path(opened.layout.address(issue.subject).path) or None
    return issue.model_copy(update={"file": part.file, "key": key, "line": line_of(opened, part.file, key)})


def line_of(opened: Opened, file: str, key: str | None) -> int | None:
    """The line a key stands at in a part's TOML file, read from its text as the project opened
    (core.md § 10); None for no key, or a file whose text was not read."""
    text = opened.texts.get(file)
    return persist.key_line(text, key) if key and text is not None else None


# ------------------------------------------------------------------ the tree

def _inventory(project: Project, layout: Layout) -> list[str]:
    """Every file in the project's folder, as POSIX paths from it, but those an editor keeps
    beside what it edits."""
    return _files(project.folder, project.relative, layout)


def _files(folder: Path, relative, layout: Layout) -> list[str]:
    """Every file in ``folder``, as ``relative`` names it, but those an editor keeps beside what
    it edits."""
    return sorted({f for p in folder.rglob("*") if p.is_file() and not layout.edited(f := relative(p))}
                  if folder.is_dir() else set())


def _classify(layout: Layout, files: list[str]) -> tuple[dict[str, tuple[str, str | None]], list[str],
                                                          dict[str, list[str]]]:
    """Each part's own file → (kind, name); the files no part kind declares — a file of the form a
    folder kind's parts once had among them, which `_was` tells apart; and each folder part's own
    file → the other files in its folder, which its kind and its file judge. A written folder's
    files are its writer's, never read. Whether a folder is a part or a group is the layout's."""
    parts: dict[str, tuple[str, str | None]] = {}
    folders: dict[str, str] = {}                                     # a part's folder, ending in `/` → its own file
    for kind, k in layout.kinds.items():
        if k.shape != "folder":
            continue
        own = [f for f in files if PurePosixPath(f).name == k.file and PurePosixPath(f).parts[0] == k.folder
               and len(PurePosixPath(f).parts) > 2]
        for f in sorted(own, key=lambda f: len(PurePosixPath(f).parts)):   # the shallowest first: a part's
            name = "/".join(PurePosixPath(f).parts[1:-1])                    # folder holds no part — never both
            if names.valid(name) and not any(f.startswith(folder) for folder in folders):
                parts[f] = (kind, name)
                folders[f"{k.folder}/{name}/"] = f
    stray: list[str] = []
    inside: dict[str, list[str]] = {own: [] for own in folders.values()}
    for f in files:
        if f in parts:
            continue
        rel = PurePosixPath(f)
        top = rel.parts[0]
        if f == PROJECT_FILE:
            parts[f] = (layout.project_kind, None)
            continue
        if f in layout.kinds[layout.project_kind].optional:            # the project file's, at the top
            inside.setdefault(PROJECT_FILE, []).append(f)
            continue
        if len(rel.parts) > 1 and top in layout.folders:
            continue
        holder = next((own for folder, own in folders.items() if f.startswith(folder)), None)
        if holder is not None:
            inside[holder].append(f)
            continue
        owner = next((kind for kind, k in layout.kinds.items() if k.folder == top), None)
        if owner and len(rel.parts) > 1 and layout.kinds[owner].shape == "file" and rel.suffix == ".toml":
            name = PurePosixPath(*rel.parts[1:]).with_suffix("").as_posix()
            if names.valid(name):
                parts[f] = (owner, name)
                continue
        stray.append(f)
    return parts, stray, inside


def listing(project: Project, layout: Layout) -> dict[str, list[str]]:
    """Each named kind's parts by name — a group's in its name — read from the folders."""
    parts, _, _ = _classify(layout, _inventory(project, layout))
    out: dict[str, list[str]] = {kind: [] for kind, k in layout.kinds.items() if k.named}
    for kind, name in parts.values():
        if name is not None:
            out[kind].append(name)
    return {kind: sorted(found) for kind, found in out.items()}


# ------------------------------------------------------------------ opening

def open_project(project: Project, ctx: Context, layout: Layout | None = None,
                 texts: Mapping[Address, str] | None = None) -> Opened:
    """Every part, each on its own, read as every declared file is: by `schema.load_text`, its
    numbers exact and the unit table in its validation context (projects.md § 6); and each folder
    part's other files. ``layout`` is one bound to the registered schemas (`layout.load`), the
    shipped one by default, read once per invocation (`layout.load_once`). ``texts`` holds, by its address — a part's, its own file; or a folder
    part's file's — a text read in place of a file's, in memory (projects.md § 7: a save's impact);
    one naming no file the project holds is refused, `UsageError` `no-such-file`."""
    layout = layout or layouts.load_once(ctx)
    files = _inventory(project, layout)
    found, stray, inside = _classify(layout, files)
    opened = Opened(project=project, layout=layout, files=tuple(files))
    context = {"units": catalogue.units(ctx)}
    given = dict(texts or {})
    for file, (kind, name) in sorted(found.items(), key=lambda item: layout.chain(*item[1])):   # the chain's order
        _load(opened, project, file, Address(kind, name), inside.get(file, []), context, given)
    opened.issues += [_was(opened, f, kind) if (kind := _once(layout, f)) is not None else
                      _stray(opened, f, "femkit reads only the project's parts, and this file is none of them")
                      for f in stray]
    for kind, folder in layout.libraries().items():
        _library(opened, kind, Library(project.root, folder), context, given)
    for address in given:
        raise UsageError(f"{address} names no file the project {project.name} holds, so no text stands in its place",
                         code="no-such-file", subject=str(address))
    return opened


def _load(opened: Opened, home: Home, file: str, address: Address, others: list[str], context: dict,
          given: dict[Address, str] | None = None) -> None:
    """One part, ``file`` of ``home`` — the project, or a global library — loaded on its own by its
    registered schema, or from the text ``given`` holds for it in place of its file's, which it
    takes; a folder part's other files read (`_hold`). Each finding names its file as ``home``
    shows it."""
    given = {} if given is None else given
    k = opened.layout.kinds[address.kind]
    shown = home.shown(file)
    data, problems = None, []
    try:
        content = given.pop(address) if address in given else persist.read_text(home.path(file))
        opened.texts[shown], opened.sha256[shown] = content, persist.digest(content)
        data = load_text(content, schemas.registered()[k.schema_], shown, context)
    except DefinitionError as exc:
        problems = exc.problems
    except UnicodeDecodeError as exc:                      # a part that cannot be read is a finding on it
        problems = [Problem("", f"this is not text written in UTF-8: byte {exc.start + 1} is not")]
    except OSError as exc:
        problems = [Problem("", f"femkit cannot read this file: {exc.strerror or exc}")]
    opened.issues += [Issue(severity="error", code=schemas.UNLOADABLE, subject=str(address), file=shown,
                            key=p.path or None, line=p.line if p.line is not None else line_of(opened, shown, p.path),
                            message=p.reason, right=p.right, choices=p.choices)
                      for p in problems]
    folder = str(PurePosixPath(file).parent) if k.shape == "folder" else None
    part = Part(address=address, file=shown, data=data, folder=None if folder is None else home.shown(folder))
    opened.parts[str(address)] = part
    if folder is not None or k.optional:
        _hold(opened, part, k, others, home, folder, given)


def _library(opened: Opened, kind: str, library: Library, context: dict,
             given: dict[Address, str] | None = None) -> None:
    """The global library of ``kind`` (materials.md § 4): whether the root holds it, the parts it
    holds and its record of femkit's copies; and each of its parts a loaded part of the project
    names, loaded as `GLOBAL/<name>` (`_take`)."""
    held = _held(opened, kind, library)
    opened.libraries[kind] = Listed(library=library, there=library.place.is_dir(), names=tuple(sorted(held)),
                                    shipped=_record(opened, library))
    _take(opened, kind, _wanted(opened, kind), context, held, given)


def _held(opened: Opened, kind: str, library: Library) -> dict[str, tuple[str, list[str]]]:
    """Each part of ``kind`` a library holds, by name: its own file, and its folder's other files."""
    found, _, inside = _classify(opened.layout, _files(library.place, library.relative, opened.layout))
    return {name: (file, inside[file]) for file, (k, name) in found.items() if k == kind}


def _take(opened: Opened, kind: str, wanted: Iterable[str], context: dict,
          held: Mapping[str, tuple[str, list[str]]] | None = None, given: dict[Address, str] | None = None) -> None:
    """Each part ``wanted``, by its name in the library of ``kind``, that the library holds —
    ``held``, as `_held` reads it — and is not loaded yet: loaded as `GLOBAL/<name>` (`_load`),
    with the digest of its folder's files, as `shipped` digests femkit's."""
    listed = opened.libraries[kind]
    new = sorted(n for n in set(wanted)
                 if n in listed.names and str(Address(kind, names.GLOBAL + n)) not in opened.parts)
    held = held if held is not None or not new else _held(opened, kind, listed.library)
    for name in (n for n in new if n in held):                 # one gone since the library was listed is not
        file, others = held[name]
        _load(opened, listed.library, file, Address(kind, names.GLOBAL + name), others, context, given)
        listed.digests[name] = _digest(listed.library, str(PurePosixPath(file).parent), [file, *others])


def seeding() -> Action:
    """What makes a projects root's global library, where it has none yet: the next `project new`,
    which makes it holding femkit's shipped parts (materials.md § 4)."""
    return view.command(PROJECT_NEW, note="a new project makes the global library, holding femkit's shipped materials",
                        fills=[view.Fill(field="name", label="the new project's name"),
                               view.Fill(field="source", label="a template, or a project to copy")])


def load_library(opened: Opened, kind: str, wanted: Iterable[str], units: Any) -> None:
    """Each part of the global library of ``kind`` ``wanted`` by its name there, that it holds and
    the project does not name, loaded as opening loads one the project names: a material a case
    holds, which the project no longer names (materials.md § 6). ``units``: the unit table
    opening reads numbers with."""
    if kind in opened.libraries:
        _take(opened, kind, wanted, {"units": units})


def _wanted(opened: Opened, kind: str) -> set[str]:
    """The name in its library of each part of ``kind`` a loaded part of the project cites by a
    field's `ref` (projects.md § 3): `GLOBAL/<name>`, or a name the project holds no part of."""
    out: set[str] = set()
    for part in [p for p in opened.parts.values() if p.data is not None and not p.library]:
        for _, ref, name, _ in cited(part.data):
            if kind in ref.split("|") and (name.startswith(names.GLOBAL) or str(Address(kind, name)) not in opened.parts):
                out.add(name.removeprefix(names.GLOBAL))
    return out


class ShippedRecord(Model):
    """`<library>/.femkit/shipped.json` (materials.md § 4): what `project new` copied into a new
    root's library from femkit's shipped parts — femkit's own side file, never a part."""

    schema_: Literal[1] = Field(alias="schema", description="the shape this file is written in, raised when it "
                                                            "changes")
    copied: dict[str, str] = Field(default_factory=dict, description="each part copied, by its name, with the "
                                                                     "digest of femkit's files it was copied from")


def _record(opened: Opened, library: Library) -> dict[str, str]:
    """A library's record of femkit's copies, read by the one reader of a file femkit writes
    (`persist.read_record`, core.md § 4); none where it has none. One that does not read is a
    warning on it, and records none."""
    path = library.path(f"{library.folder}/{SHIPPED}")
    try:
        held = persist.read_record(path, ShippedRecord)
    except (OSError, UnicodeDecodeError) as exc:               # there, and not to be read as text
        held = persist.Read(True, None, f"femkit cannot read it: {exc}")
    if held.reads:
        return held.value.copied
    if held.there:
        opened.issues.append(Issue(severity="warning", code=schemas.UNLOADABLE, subject=str(path), file=str(path),
                                   message=f"femkit's record of what it copied into your library does not load, so "
                                           f"no change to femkit's shipped parts is offered: {held.problem}"))
    return {}


#: The finding of a file of the form a folder kind's parts once had (projects.md § 4).
NOW_A_FOLDER = "now-a-folder"


def _once(layout: Layout, file: str) -> str | None:
    """The folder kind whose parts were once each one file of the form ``file`` has —
    `<folder>/<name>.toml`, as the kind's `was` declares (projects.md § 4); None for any other."""
    rel = PurePosixPath(file)
    if len(rel.parts) < 2 or rel.suffix != ".toml" or not names.valid(PurePosixPath(*rel.parts[1:]).with_suffix("")
                                                                     .as_posix()):
        return None
    return next((kind for kind, k in layout.kinds.items() if k.was == "file" and k.folder == rel.parts[0]), None)


def _was(opened: Opened, file: str, kind: str) -> Issue:
    """A file of the form ``kind``'s parts once had — one file each — told that its part is now a
    folder, holding its own file and the files its kind fixes, as the templates show (projects.md
    § 4): never a stray; its finding the door's, `now-a-folder`."""
    k = opened.layout.kinds[kind]
    name = PurePosixPath(*PurePosixPath(file).parts[1:]).with_suffix("").as_posix()
    holds = " and ".join(f"`{f}`" for f in [k.file, *k.files])
    return Issue(severity="error", code=NOW_A_FOLDER, subject=file, file=file,
                 message=f"a part of the kind {kind} is now a folder, `{k.folder}/{name}/`, holding {holds}, as "
                         "femkit's templates show: this file is no longer read")


def _stray(opened: Opened, file: str, why: str) -> Issue:
    """A file femkit does not read (projects.md § 6): why, and where the person's own files go."""
    own = opened.layout.person_writes()
    return Issue(severity="warning", code="stray", subject=file, file=file,
                 message=why + (f"; your own files go in {own[0]}/" if own else ""))


def _hold(opened: Opened, part: Part, kind: PartKind, others: list[str], home: Home, folder: str | None,
          given: dict[Address, str]) -> None:
    """A part's other files (projects.md § 6): those its kind fixes, those it may hold where they
    are there, and — once its own file loads — those it declares by a `file` reference; each read
    once from ``folder`` of ``home`` — the project's top, for the project file, ``folder`` None —
    or taken from the text ``given`` holds for it, with its bytes and SHA-256. One fixed or
    declared that is missing, one unreadable or one outside the part's folder is a finding; once
    the part loads, a file of its folder neither fixes nor declares is a stray, never read — in the
    project's tree alone. A part that does not load declares nothing that can be known, so its
    folder's other files are neither read nor strays."""
    declared: dict[str, tuple[str, ...]] = {name: () for name in [*kind.files, *kind.optional]}
    if part.data is not None:
        for location, ref, name, _held in cited(part.data):
            if ref == FILE_REF:
                declared.setdefault(name, _citing(part, location).path)
    the = f"the {part.address.kind} {part.address.name}"
    for name, keys in declared.items():
        at = Address(part.address.kind, part.address.name, keys)
        relative = f"{folder}/{name}" if folder is not None else name
        path = home.shown(relative) if names.FILE.fullmatch(name) else relative

        def problem(code: str, message: str) -> Issue:
            if keys:
                return finding(opened, at, code=code, message=message)
            return Issue(severity="error", code=code, subject=str(at), file=path, message=message)

        if not names.FILE.fullmatch(name):
            opened.issues.append(problem("outside-part", f"{name!r} is no file of the folder {part.folder}/: a file "
                                                         "here is named by its path from that folder, in steps of "
                                                         "letters, digits, `.`, `_` and `-`, none starting with `.` "
                                                         "or `-`"))
            continue
        try:
            text = given.pop(Address(part.address.kind, part.address.name, file=name), None)
            data = text.encode("utf-8") if text is not None else persist.read_bytes(home.path(relative))
        except OSError as exc:
            opened.issues.append(problem("unreadable", f"femkit cannot read {shown_path(path)}: "
                                                       f"{exc.strerror or exc}"))
            continue
        if data is None:
            if name not in kind.optional:
                opened.issues.append(problem("missing-file", f"{shown_path(path)} is not there" if keys
                                             else f"{the} has no {name}: every {part.address.kind} holds one"))
            continue
        opened.held[path] = Held(part=part.address, name=name, file=path, key=keys, data=data,
                                 sha256=persist.digest(data))
    if part.data is not None and home == opened.project:
        opened.issues += [_stray(opened, f, f"femkit reads only the files {the} names, and this is none of them")
                          for f in others if f not in opened.held]


def _output(opened: Opened, relative: str) -> Path:
    """Where one of femkit's own outputs lies in the project (projects.md § 7), by its POSIX path
    from the project's folder: in a folder the layout declares femkit writes, never a file the
    person wrote. Refused otherwise: `UsageError`, code `not-femkits`, subject ``relative``."""
    top = PurePosixPath(relative).parts[0] if relative else ""
    folder = opened.layout.folders.get(top)
    if folder is None or folder.writer != "femkit" or relative == top:
        raise UsageError(f"{relative!r} is no file in a folder femkit writes: "
                         f"{', '.join(f for f, v in opened.layout.folders.items() if v.writer == 'femkit')}",
                         code="not-femkits", subject=relative)
    return opened.project.path(relative)


def read_output(opened: Opened, relative: str, *, binary: bool = False) -> str | bytes | None:
    """One of femkit's own outputs in the project read — a case's file; with ``binary``, a file
    of another program's format, a study's kept definitions — by its POSIX path from the project's
    folder (projects.md §§ 6, 7): its text, or its bytes; None when it is not there; refused,
    `not-femkits`, outside a folder femkit writes."""
    path = _output(opened, relative)
    return persist.read_bytes(path) if binary else persist.read_text(path)


def read_record(opened: Opened, relative: str, model: type) -> persist.Read:
    """One of femkit's own outputs in the project, by its model — a case's file — read by the core's
    one reader of a file femkit writes (`persist.read_record`, core.md § 4), by its POSIX path from
    the project's folder: absent, read, or why it does not; refused, `not-femkits`, outside a folder
    femkit writes (projects.md §§ 6, 7)."""
    return persist.read_record(_output(opened, relative), model)


def write_output(opened: Opened, relative: str, data: Any) -> Path:
    """One of femkit's own outputs written into the project — a case's file — by its POSIX path
    from the project's folder, as JSON, atomically (core.md § 4; projects.md § 7); refused,
    `not-femkits`, outside a folder femkit writes, so never over a file the person wrote."""
    return persist.write_json(_output(opened, relative), data)


def copy_output(opened: Opened, relative: str, source: Path) -> Path:
    """One of femkit's own outputs that femkit made elsewhere — a study's kept definitions, made in
    femkit's cache — copied into the project whole, atomically, by its POSIX path from the
    project's folder (core.md § 4; projects.md § 7); refused, `not-femkits`, outside a folder
    femkit writes."""
    return persist.copy_file(source, _output(opened, relative))


#: What each step of a path the door forms may be (projects.md §§ 3, 5): a study, by its name; a
#: stage's kind, one step of the name rule; an ID, a SHA-256 in hexadecimal; a launch folder's name,
#: one step of a file's path.
STEPS = {"study": names.NAME.pattern, "kind": names.STEP, "id": addresses.ID.pattern, "name": names.FILE_STEP}


def _formed(opened: Opened, what: str, **steps: str) -> str:
    """The path, from the project's folder, of ``what`` the door forms — a stage's folder, a
    launch folder, a case's file — from ``steps``, as the layout declares it (projects.md § 6)."""
    return render(opened.layout.formed(what), steps)


def _named(opened: Opened, made: addresses.Made) -> None:
    """``made`` as its address reads back, whole: each of its steps keeps its grammar
    (projects.md § 5); refused, `UsageError` `bad-address`, otherwise."""
    if opened.layout.address(str(made), made=True) != made:
        raise UsageError(f"{str(made)!r} reads back as another address: a step of it breaks its grammar",
                         code="bad-address", subject=str(made))


def holder(layout: Layout) -> str:
    """The folder that holds stages, as the layout declares it (projects.md § 4): `runs`."""
    return next(f for f, v in layout.folders.items() if "stage" in v.holds)


def made_steps(layout: Layout, kinds: Iterable[str]) -> frozenset[str]:
    """Each step a path the folder holding stages forms takes right after a study's name
    (projects.md § 5): a fixed one as itself — a launch folder's `launch`; a stage's kind as each
    of ``kinds``, the stage kinds declared — which no step of a study's name may be, so no study's
    folder under `runs/` lies inside another's."""
    steps: set[str] = set()
    for path in layout.folders[holder(layout)].holds.values():
        after = path.split("/")[1]
        held = parsed(after)
        steps |= {after} if not held else set(kinds) if held[0].name == "kind" else set()
    return frozenset(steps)


def stage_folder(opened: Opened, study: str, kind: str, id: str) -> Path:
    """A stage's calculation folder (projects.md §§ 2, 6; workflow.md § 4), by its study, its kind
    and its ID, as the layout declares the folder that holds it: `runs/<study>/<kind>/<id>/`.
    Formed by the door alone; the jobs domain writes inside it (jobs.md § 1.1)."""
    _named(opened, addresses.Stage(study, kind, id))
    return opened.project.path(_formed(opened, "stage", study=study, kind=kind, id=id))


def launch_folder(opened: Opened, study: str, name: str) -> Path:
    """A launch folder of a study (projects.md §§ 2, 6; jobs.md § 1.2), by its name, as the layout
    declares the folder that holds it: `runs/<study>/launch/<name>/`. Formed by the door alone; the
    jobs domain writes inside it."""
    _named(opened, addresses.Launch(study, name))
    return opened.project.path(_formed(opened, "launch", study=study, name=name))


def case_file(opened: Opened, study: str, id: str) -> str:
    """A study's case's file, from the project's folder (projects.md § 2; models.md § 5.3), by its
    study and its ID, as the layout declares the folder that holds it: `cases/<study>/<id>/case.json`
    — what `read_output` and `write_output` take."""
    names.check(study, what="a study's name")
    if not addresses.ID.fullmatch(id):
        raise ValueError(f"{id!r} is no case's ID: a SHA-256, in 64 hexadecimal digits")
    return _formed(opened, "case", study=study, id=id)


def definitions_file(opened: Opened, study: str) -> str:
    """A study's kept definitions, from the project's folder (projects.md § 2; models.md § 3), by
    its study, as the layout declares the folder that holds them: `computed/<study>/definitions.nc`
    — what `read_output` and `copy_output` take."""
    names.check(study, what="a study's name")
    return _formed(opened, "definitions", study=study)


def cases(opened: Opened) -> dict[str, dict[str, str]]:
    """Every case's file the project holds, by its study, then its ID: each file of the project
    where the layout declares a case's file is formed (projects.md § 2)."""
    path = opened.layout.formed("case")
    pattern, at = [], 0
    for p in parsed(path):
        pattern += [re.escape(path[at:p.span[0]]), f"(?P<{p.name}>{STEPS[p.name]})"]
        at = p.span[1]
    case = re.compile("".join(pattern) + re.escape(path[at:]))
    found: dict[str, dict[str, str]] = {}
    for f in opened.files:
        if match := case.fullmatch(f):
            found.setdefault(match["study"], {})[match["id"]] = f
    return found


def stages(opened: Opened, study: str) -> dict[tuple[str, str], Path]:
    """Every stage's calculation folder of ``study`` the project holds, by its kind and its ID:
    each folder, holding a file, where the layout declares a stage's folder is formed (projects.md
    § 2) — what `case list` reads a stage's `stage.json` in, whichever machine made it (workflow.md
    § 4)."""
    path = opened.layout.formed("stage")
    pattern, at = [], 0
    for p in parsed(path):
        pattern += [re.escape(path[at:p.span[0]]),
                    re.escape(study) if p.name == "study" else f"(?P<{p.name}>{STEPS[p.name]})"]
        at = p.span[1]
    stage = re.compile("".join(pattern) + re.escape(path[at:]) + "/")
    found: dict[tuple[str, str], Path] = {}
    for f in opened.files:
        if match := stage.match(f):
            found.setdefault((match["kind"], match["id"]), opened.project.path(f[:match.end() - 1]))
    return found


def save_text(ctx: Context, home: Home, address: Address, text: str, sha256: str) -> Path:
    """The file ``address`` names — a part's own file, or a folder part's file — written exactly as
    ``text``, its bytes its UTF-8, through the core's one writer (projects.md § 7: the page's text
    editor), where it lies and as it is refused (`unchanged`): nothing is written over a file whose
    SHA-256 is not ``sha256``. The operation that saves holds the project's lock."""
    path = unchanged(ctx, home, address, sha256)
    persist.write_stream(path, io.BytesIO(text.encode("utf-8")))
    return path


def unchanged(ctx: Context, home: Home, address: Address, sha256: str) -> Path:
    """Where the file ``address`` names lies in ``home`` — a part's own file, or a folder part's
    file — as the layout, read once in the invocation ``ctx``, puts it, while its SHA-256 is still
    ``sha256``, the one it had when the page opened it (projects.md § 7). Refused, `Refused` ·
    `file-changed`, naming it, where it changed since, or is gone; an address of a value, or of a
    part ``home`` does not hold, `UsageError` `bad-address`: what a save's plan and its write ask
    alike."""
    k = layouts.read_once(ctx).kinds[address.kind]
    if address.path or in_library(address) != isinstance(home, Library) or (address.file and k.shape != "folder"):
        raise UsageError(f"{address} names no file saved here: a part's own file, or a file of a part's folder — "
                         "the project's, or the global library's", code="bad-address", subject=str(address))
    path = home.path(_where(k, address))
    now = persist.sha256(path)
    if now != sha256:
        raise Refused(f"{shown_path(path)} {'is gone' if now is None else 'changed'} since it was opened, so the "
                      "text is not saved over it: open it again", code="file-changed", subject=str(address))
    return path


def _where(k: PartKind, address: Address) -> str:
    """Where the file ``address`` names lies, from its home, as the layout declares its kind ``k``: a
    part's own file, or a folder part's file by its path from the part's folder."""
    name = names.bare(address.name) if address.name is not None else None
    return {"single": PROJECT_FILE, "file": f"{k.folder}/{name}.toml",
            "folder": f"{k.folder}/{name}/{address.file or k.file}"}[k.shape]


def read_alone(project: Project, layout: Layout, address: Address) -> str | None:
    """The text of the one file ``address`` names in ``project`` — a part's own file — where
    ``layout`` puts it, read on its own, never the project opened (projects.md § 6): what a reader
    that needs one table of it alone, through that table's schema, takes it by — each project file's
    `[postprocess]`, for `env install` (models.md § 2). None where it is not there; an `OSError`, or
    a `UnicodeDecodeError` for a file that is not UTF-8 text, for the reader to say."""
    return persist.read_text(project.path(_where(layout.kinds[address.kind], address)))


def new_part(home: Home, layout: Layout, kind: str, name: str) -> Path:
    """Where the new folder part ``name`` of ``kind`` goes in ``home`` — a project, or a global
    library (projects.md § 7; materials.md § 7): a folder nothing holds yet, its name the name
    rule's (`UsageError` `bad-name`). Refused, `Refused` with ``name`` its subject: `exists` where
    a file or folder is there already — a part or a group alike — or a file stands along it, since
    a new part never lands over one; `inside-part` where a folder along it is a part of ``kind``,
    since a new part is never made into one."""
    names.check(name, what=f"a {kind}'s name")
    k = layout.kinds[kind]
    if k.shape != "folder":
        raise ValueError(f"a {kind} is no folder part")
    steps = names.steps(name)
    for i in range(len(steps) + 1):
        relative = "/".join([k.folder, *steps[:i]])
        there = home.path(relative)
        if 0 < i < len(steps) and home.path(f"{relative}/{k.file}").is_file():
            raise Refused(f"{shown_path(there)} is the {kind} {'/'.join(steps[:i])}: a new {kind} is never made "
                          "into it", code="inside-part", subject=name)
        if there.is_symlink() or (there.exists() and (i == len(steps) or not there.is_dir())):
            raise Refused(f"{shown_path(there)} is there already: a new {kind} is never made over it",
                          code="exists", subject=name)
    return home.path(f"{k.folder}/{name}")


def write_part(home: Home, layout: Layout, kind: str, name: str, files: Mapping[str, bytes]) -> Path:
    """The new folder part ``name`` of ``kind`` written into ``home`` whole, where `new_part` puts
    it and as it refuses: its folder holding ``files``, each by its path from it — its own file
    among them — built apart and moved into place (core.md § 4), never over or into a part there."""
    folder = new_part(home, layout, kind, name)
    outside = [f for f in files if not names.FILE.fullmatch(f)]
    if outside or layout.kinds[kind].file not in files:
        raise ValueError(f"a {kind}'s folder holds its own file, {layout.kinds[kind].file}, and files of its folder: "
                         f"{', '.join(outside) or 'not ' + layout.kinds[kind].file}")
    return persist.write_folder(folder, files)


def unloadable(opened: Opened, part: Part, why: str, next: Iterable[Action] = (), *,
               subject: Address | None = None) -> UsageError:
    """The one refusal of a part that does not load, or cannot be read (projects.md § 6): `UsageError`
    `unloadable`, its subject the address asked for — the part's, by default — carrying the findings
    on the part that say why (core.md § 9), with ``next``."""
    return UsageError(f"`{part.address}` {why}", tuple(next), code=schemas.UNLOADABLE, subject=str(subject or part.address),
                      issues=[i for i in opened.issues if opened.owner(i.subject) is part])


def loaded(opened: Opened, part: Part, next: Iterable[Action] = ()) -> Part:
    """``part``, or refused, `unloadable` (`unloadable`), where it does not load: what every command
    that needs a part's content asks, and nothing else does."""
    if part.data is None:
        raise unloadable(opened, part, "does not load", next)
    return part


def text(opened: Opened, address: Address) -> str:
    """The text of the file an address names, as the project read it, comments kept: a part's own
    file, or a folder part's file (`component:bowtie@geometry.py`, projects.md § 5); a value's text
    is its TOML. Refused, `unloadable` (`unloadable`), for a file that could not be read — or is not
    UTF-8 text — or a value in a part that is not TOML."""
    part = opened.part(address)
    if address.file is not None:
        held = opened.held_by(part.address).get(address.file)
        if held is None:
            raise unloadable(opened, part, f"holds no file {address.file} that could be read", subject=address)
        try:
            return held.data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise unloadable(opened, part, f"holds {address.file}, which is not text written in UTF-8: byte "
                                           f"{exc.start + 1} is not", subject=address) from None
    held = opened.texts.get(part.file)
    if held is None:
        raise unloadable(opened, part, "could not be read", subject=address)
    if not address.path:
        return held
    try:
        doc = persist.toml_document(held)
    except ValueError as exc:
        raise unloadable(opened, part, f"is not TOML, so {address} cannot be read: {exc}", subject=address) from None
    if not persist.document_has(doc, address.path):
        raise UsageError(f"{address} holds no value", code="no-such-value", subject=str(address))
    return persist.document_text(doc, address.path)


def file(opened: Opened, address: Address) -> view.File:
    """The file ``address`` names — a part's own, or a folder part's file — as the project read it,
    once (projects.md § 6): its text and the SHA-256 of its bytes the opened project keeps, what a
    save sends back (§ 7); neither where it could not be read (web.md § 7.6); and its path as a
    finding names it (core.md § 10), so a finding is marked at its line: the part's file, or the
    folder part's file by its path from the part's folder; and the action that saves it, exactly as
    the person types it — `project save` of its address and that SHA-256, its text the one value to
    fill — none where it could not be read (`File.save`, projects.md § 7)."""
    part = opened.part(address)
    held = opened.held_by(part.address).get(address.file) if address.file is not None else None
    path = part.file if address.file is None else held.file if held is not None else f"{part.folder}/{address.file}"
    try:
        read = text(opened, Address(address.kind, address.name, file=address.file))
    except UsageError:
        return view.File(address=str(address), path=path)
    kept = held.sha256 if held is not None else opened.sha256[part.file]
    save = view.command(PROJECT_SAVE, label=f"save {path}", note="writes it exactly as typed, its impact shown first",
                        project=opened.project.name, address=str(address), sha256=kept,
                        fills=[view.Fill(field="text", label="the file's new text, as typed")])
    return view.File(address=str(address), path=path, text=read, sha256=kept, save=save)


# ------------------------------------------------------------------ references

def _kinds_of(ref: str, layout: Layout) -> list[str]:
    """The part kinds a `ref` names — a type may offer alternatives; a group's is no part kind."""
    return [t for t in ref.split("|") if t in layout.kinds]


def _citations(opened: Opened) -> list[tuple[Part, tuple, str, Address]]:
    """Every citation of a part: (the citing part, the location, how it is held, the part cited,
    as `named` finds it — a global library's by its `GLOBAL/` name). A `ref` offering
    alternatives cites the kind that has a part of that name — the first, when none has: a
    citation naming no part."""
    out = []
    for part in opened.parts.values():
        if part.data is None:
            continue
        for location, ref, name, held in cited(part.data):
            kinds = _kinds_of(ref, opened.layout)
            if kinds:
                found = next((p for k in kinds if (p := named(opened, k, name)) is not None), None)
                out.append((part, location, held, found.address if found is not None else Address(kinds[0], name)))
    return out


def _citing(part: Part, location: tuple) -> Address:
    """The value that cites: a list's item by its list — entries are keyed by name, never by position."""
    keys = tuple(str(p) for p in location if not isinstance(p, int))
    return Address(part.address.kind, part.address.name, keys)


def references(opened: Opened) -> list[tuple[Address, Address]]:
    """Every citation: (the value that cites, the part it names)."""
    return [(_citing(part, location), target) for part, location, held, target in _citations(opened)]


# ------------------------------------------------------------------ femkit's shipped parts

@dataclass(frozen=True)
class Shipped:
    """One of femkit's shipped parts of a kind with a global library (materials.md § 4)."""

    name: str
    file: Path                   # its own file
    files: tuple[str, ...]       # every file of its folder, by its path from femkit's data
    digest: str                  # the digest of those files (`_digest`)


def shipped_library(folder: str) -> Library:
    """femkit's shipped parts of the kind whose folder is ``folder``, read as a library is:
    `femkit/data/materials/`, femkit's shipped materials (materials.md § 4)."""
    return Library(catalogue.data_root(), folder)


def shipped(layout: Layout, kind: str) -> dict[str, Shipped]:
    """femkit's shipped parts of ``kind``, each by its name: its own file, every file of its
    folder, and their digest — what a new library records it copied (materials.md § 4)."""
    library = shipped_library(layout.kinds[kind].folder)
    found, _, inside = _classify(layout, _files(library.place, library.relative, layout))
    out: dict[str, Shipped] = {}
    for file, (k, name) in sorted(found.items()):
        if k == kind:
            files = tuple(sorted([file, *inside.get(file, [])]))
            out[name] = Shipped(name=name, file=library.path(file), files=files,
                                digest=_digest(library, str(PurePosixPath(file).parent), files))
    return out


def _digest(library: Library, folder: str, files: Iterable[str]) -> str:
    """The digest of a part's files: the SHA-256 of the canonical JSON of each file's SHA-256, by
    its path from the part's ``folder`` — so where the part lies changes nothing."""
    return persist.canonical_sha256({PurePosixPath(f).relative_to(folder).as_posix(): persist.sha256(library.path(f))
                                     for f in files})


def seed(library: Library, source: Library, files: Iterable[str], copied: Mapping[str, str]) -> None:
    """A new global library (materials.md § 4; projects.md § 7): ``files`` of ``source`` — femkit's
    shipped parts, each by its path from femkit's data — and its record of each part copied, by
    name, with the digest of femkit's files then, written as ``library``'s folder, which is not
    there yet: one folder built apart and moved into place whole (core.md § 4), so an interruption
    leaves no library, never one without its record. Never over anything there: a folder there
    already is a `FileExistsError`; a file of ``files`` gone meanwhile, a `FileNotFoundError`."""
    record = ShippedRecord(schema=1, copied=dict(copied)).model_dump(mode="json", by_alias=True)
    written = {SHIPPED: persist.json_text(record).encode("utf-8")}
    for f in files:
        data = persist.read_bytes(source.path(f))
        if data is None:
            raise FileNotFoundError(f"{source.path(f)} is gone")
        written[PurePosixPath(f).relative_to(source.folder).as_posix()] = data
    persist.write_folder(library.place, written)
