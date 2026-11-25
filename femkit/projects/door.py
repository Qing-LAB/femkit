"""Listing and opening a project (projects.md §§ 2, 3, 6): each part kind's tree read from its
folder as the layout declares it; each part loaded through its registered schema on its own —
a part that does not load is a finding on that part, and every other part is still read; a
folder part's other files — those its kind fixes, those its own file declares — read once, each
with its bytes and digest; a file no part kind declares is a finding, never read. A part's text
is its file as it holds it, comments kept. The references between parts are read from the
schemas' `ref` annotations. The door reads the person's files and never writes one (projects.md
§ 7); femkit's own outputs — a case's file — it reads and writes itself, `read_output` and
`write_output`, each in a folder the layout declares femkit writes, refused elsewhere:
`UsageError`, code `not-femkits`. A new folder part the person brings — a material `material
import` writes from another source's file (materials.md § 7) — it writes whole where nothing is,
in a project or a global library (`new_part`, `write_part`), never over or into one: `Refused`,
code `exists` or `inside-part`, its subject the new part's name. A file an editor keeps beside
what it edits (the layout's `editor_files`) is not looked at: no part, no stray, never copied.

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
- `stray` (warning), subject the file's path in the project: a file in the tree no part kind
  declares, or in a loaded part's folder that neither its kind fixes nor its file declares —
  never read; its message names the folder the person's own files go in. A library's folders are
  not the project's tree, and hold no stray;
- `unloadable` (warning), subject the record's full path: a library's record of femkit's copies
  that does not load — read as recording none.

A check says what it cannot check yet as an `info` finding, code `not-checked-yet` (`UNCHECKED`,
projects.md § 6), which a part's state reads (projects.md § 8).

A part's text, or a value's, that cannot be given is refused: `UsageError` `unloadable`, subject
the address asked for — a part that could not be read, a value in a part that is not TOML.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Literal, Mapping

import tomlkit
from pydantic import Field

from femkit.core import persist, view
from femkit.core.errors import Refused, UsageError
from femkit.core.text import path as shown_path
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, Model, Problem, key_path, load_text, references as cited, validate
from femkit.core.view import Action
from femkit.definitions import catalogue
from femkit.projects import layout as layouts
from femkit.projects import names, schemas
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
        """The part a finding's subject names — its address, or a value's in it; none for a file
        that is no part's."""
        return next((p for a, p in self.parts.items() if subject == a or subject.startswith(a + ":")), None)

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
    part's own — read here from the address, never formed by the domain that found it — and its
    key the address's dotted path; ``right`` and ``choices`` as the file would write them."""
    part = opened.part(at)
    return Issue(severity=severity, code=code, subject=str(at), label=label, message=message, file=part.file,
                 key=key_path(at.path) or None, right=right, choices=tuple(choices), next=tuple(next))


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
    """Each part's own file → (kind, name); the files no part kind declares; and each folder
    part's own file → the other files in its folder, which its kind and its file judge. A written
    folder's files are its writer's, never read. Whether a folder is a part or a group is the
    layout's."""
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

def open_project(project: Project, ctx: Context, layout: Layout | None = None) -> Opened:
    """Every part, each on its own, read as every declared file is: by `schema.load_text`, its
    numbers exact and the unit table in its validation context (projects.md § 6); and each folder
    part's other files. ``layout`` is one bound to the registered schemas (`layout.load`), the
    shipped one by default."""
    layout = layout or layouts.load()
    files = _inventory(project, layout)
    found, stray, inside = _classify(layout, files)
    opened = Opened(project=project, layout=layout, files=tuple(files))
    context = {"units": catalogue.units(ctx)}
    for file, (kind, name) in sorted(found.items(), key=lambda item: (layout.kinds[item[1][0]].rank, item[0])):
        _load(opened, project, file, Address(kind, name), inside.get(file, []), context)
    opened.issues += [_stray(opened, f, "femkit reads only the project's parts, and this file is none of them")
                      for f in stray]
    for kind, folder in layout.libraries().items():
        _library(opened, kind, Library(project.root, folder), context)
    return opened


def _load(opened: Opened, home: Home, file: str, address: Address, others: list[str], context: dict) -> None:
    """One part, ``file`` of ``home`` — the project, or a global library — loaded on its own by its
    registered schema; a folder part's other files read (`_hold`). Each finding names its file as
    ``home`` shows it."""
    k = opened.layout.kinds[address.kind]
    shown = home.shown(file)
    data, problems = None, []
    try:
        content = persist.read_text(home.path(file))
        opened.texts[shown] = content
        data = load_text(content, schemas.registered()[k.schema_], shown, context, exact=True)
    except DefinitionError as exc:
        problems = exc.problems
    except UnicodeDecodeError as exc:                      # a part that cannot be read is a finding on it
        problems = [Problem("", f"this is not text written in UTF-8: byte {exc.start + 1} is not")]
    except OSError as exc:
        problems = [Problem("", f"femkit cannot read this file: {exc.strerror or exc}")]
    opened.issues += [Issue(severity="error", code="unloadable", subject=str(address), file=shown,
                            key=p.path or None, message=p.reason, right=p.right, choices=p.choices)
                      for p in problems]
    folder = str(PurePosixPath(file).parent) if k.shape == "folder" else None
    part = Part(address=address, file=shown, data=data, folder=None if folder is None else home.shown(folder))
    opened.parts[str(address)] = part
    if folder is not None:
        _hold(opened, part, k, others, home, folder)


def _library(opened: Opened, kind: str, library: Library, context: dict) -> None:
    """The global library of ``kind`` (materials.md § 4): whether the root holds it, the parts it
    holds and its record of femkit's copies; and each of its parts a loaded part of the project
    names, loaded as `GLOBAL/<name>` (`_take`)."""
    held = _held(opened, kind, library)
    opened.libraries[kind] = Listed(library=library, there=library.place.is_dir(), names=tuple(sorted(held)),
                                    shipped=_record(opened, library))
    _take(opened, kind, _wanted(opened, kind), context, held)


def _held(opened: Opened, kind: str, library: Library) -> dict[str, tuple[str, list[str]]]:
    """Each part of ``kind`` a library holds, by name: its own file, and its folder's other files."""
    found, _, inside = _classify(opened.layout, _files(library.place, library.relative, opened.layout))
    return {name: (file, inside[file]) for file, (k, name) in found.items() if k == kind}


def _take(opened: Opened, kind: str, wanted: Iterable[str], context: dict,
          held: Mapping[str, tuple[str, list[str]]] | None = None) -> None:
    """Each part ``wanted``, by its name in the library of ``kind``, that the library holds —
    ``held``, as `_held` reads it — and is not loaded yet: loaded as `GLOBAL/<name>` (`_load`),
    with the digest of its folder's files, as `shipped` digests femkit's."""
    listed = opened.libraries[kind]
    new = sorted(n for n in set(wanted)
                 if n in listed.names and str(Address(kind, names.GLOBAL + n)) not in opened.parts)
    held = held if held is not None or not new else _held(opened, kind, listed.library)
    for name in (n for n in new if n in held):                 # one gone since the library was listed is not
        file, others = held[name]
        _load(opened, listed.library, file, Address(kind, names.GLOBAL + name), others, context)
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
    """A library's record of femkit's copies; none where it has none. One that does not load is a
    warning on it, and records none."""
    path = library.path(f"{library.folder}/{SHIPPED}")
    try:
        return validate(ShippedRecord, persist.read_json(path), str(path)).copied
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, DefinitionError) as exc:      # not JSON, not UTF-8, not of its shape
        opened.issues.append(Issue(severity="warning", code="unloadable", subject=str(path), file=str(path),
                                   message=f"femkit's record of what it copied into your library does not load, so "
                                           f"no change to femkit's shipped parts is offered: {exc}"))
        return {}


def _stray(opened: Opened, file: str, why: str) -> Issue:
    """A file femkit does not read (projects.md § 6): why, and where the person's own files go."""
    own = opened.layout.person_writes()
    return Issue(severity="warning", code="stray", subject=file, file=file,
                 message=why + (f"; your own files go in {own[0]}/" if own else ""))


def _hold(opened: Opened, part: Part, kind: PartKind, others: list[str], home: Home, folder: str) -> None:
    """A folder part's other files (projects.md § 6): those its kind fixes, and — once its own file
    loads — those it declares by a `file` reference; each read once from ``folder`` of ``home``,
    with its bytes and SHA-256. One missing, unreadable or outside the part's folder is a finding;
    once the part loads, a file of its folder neither fixes nor declares is a stray, never read —
    in the project's tree alone. A part that does not load declares nothing that can be known, so
    its folder's other files are neither read nor strays."""
    declared: dict[str, tuple[str, ...]] = {name: () for name in kind.files}
    if part.data is not None:
        for location, ref, name, _held in cited(part.data):
            if ref == FILE_REF:
                declared.setdefault(name, _citing(part, location).path)
    the = f"the {part.address.kind} {part.address.name}"
    for name, keys in declared.items():
        at = Address(part.address.kind, part.address.name, keys)
        relative = f"{folder}/{name}"
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
            data = persist.read_bytes(home.path(relative))
        except OSError as exc:
            opened.issues.append(problem("unreadable", f"femkit cannot read {shown_path(path)}: "
                                                       f"{exc.strerror or exc}"))
            continue
        if data is None:
            opened.issues.append(problem("missing-file", f"{shown_path(path)} is not there" if keys
                                         else f"{the} has no {name}: every {part.address.kind} holds one"))
            continue
        opened.held[path] = Held(part=part.address, name=name, file=path, key=keys, data=data,
                                 sha256=hashlib.sha256(data).hexdigest())
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


def read_output(opened: Opened, relative: str) -> str | None:
    """One of femkit's own outputs in the project read — a case's file — by its POSIX path from
    the project's folder (projects.md §§ 6, 7): its text, None when it is not there; refused,
    `not-femkits`, outside a folder femkit writes."""
    return persist.read_text(_output(opened, relative))


def write_output(opened: Opened, relative: str, data: Any) -> Path:
    """One of femkit's own outputs written into the project — a case's file — by its POSIX path
    from the project's folder, as JSON, atomically (core.md § 4; projects.md § 7); refused,
    `not-femkits`, outside a folder femkit writes, so never over a file the person wrote."""
    return persist.write_json(_output(opened, relative), data)


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


def text(opened: Opened, address: Address) -> str:
    """The part's file as it holds it, comments kept; a value's text is its TOML. Refused,
    `unloadable`, for a part that could not be read, or a value in a part that is not TOML."""
    part = opened.part(address)
    held = opened.texts.get(part.file)
    if held is None:
        raise UsageError(f"{part.address} could not be read: its finding says why", code="unloadable",
                         subject=str(address))
    if not address.path:
        return held
    try:
        doc = tomlkit.parse(held)
    except tomlkit.exceptions.ParseError as exc:
        raise UsageError(f"{part.address} is not TOML, so {address} cannot be read: {exc}", code="unloadable",
                         subject=str(address)) from None
    if not persist.document_has(doc, address.path):
        raise UsageError(f"{address} holds no value", code="no-such-value", subject=str(address))
    return persist.document_text(doc, address.path)


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
