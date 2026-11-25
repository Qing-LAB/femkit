"""Listing and opening a project (projects.md §§ 2, 3, 6): each part kind's tree read from its
folder as the layout declares it; each part loaded through its registered schema on its own —
a part that does not load is a finding on that part, and every other part is still read; a
folder part's other files — those its kind fixes, those its own file declares — read once, each
with its bytes and digest; a file no part kind declares is a finding, never read. A part's text
is its file as it holds it, comments kept. The references between parts are read from the
schemas' `ref` annotations. The door reads the person's files and never writes one (projects.md
§ 7); femkit's own outputs — a case's file — it reads and writes itself, `read_output` and
`write_output`, each in a folder the layout declares femkit writes, refused elsewhere:
`UsageError`, code `not-femkits`. A file an editor keeps beside what it edits (the layout's
`editor_files`) is not looked at: no part, no stray, never copied.

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
  never read; its message names the folder the person's own files go in.

A check says what it cannot check yet as an `info` finding, code `not-checked-yet` (`UNCHECKED`,
projects.md § 6), which a part's state reads (projects.md § 8).

A part's text, or a value's, that cannot be given is refused: `UsageError` `unloadable`, subject
the address asked for — a part that could not be read, a value in a part that is not TOML.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import tomlkit

from femkit.core import persist
from femkit.core.errors import UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, Model, Problem, key_path, load_text, references as cited
from femkit.core.view import Action
from femkit.definitions import catalogue
from femkit.projects import layout as layouts
from femkit.projects import names, schemas
from femkit.projects.addresses import Address
from femkit.projects.layout import Layout, PartKind
from femkit.projects.project import PROJECT_FILE, Project

FILE_REF = "file"               # a `ref` naming a file in the part's own folder, by its path from it (projects.md § 6)
UNCHECKED = "not-checked-yet"   # the finding of what cannot be checked yet (projects.md § 6)


@dataclass(frozen=True)
class Part:
    address: Address
    file: str                    # its own file, relative to the project
    data: Model | None           # None: it does not load (its finding says why)
    folder: str | None = None    # a folder part's folder, relative to the project; None for a part that is one file


@dataclass(frozen=True)
class Held:
    """A folder part's other file — one its kind fixes, or its own file declares — as read once
    when the project opened (projects.md § 6): the case's digest of a script and the page's view
    of it read these bytes."""

    part: Address
    name: str                    # its path from the part's folder, as fixed or declared
    file: str                    # its path from the project's folder
    key: tuple[str, ...]         # the key in the part's own file that declares it; () for one its kind fixes
    data: bytes
    sha256: str


@dataclass
class Opened:
    """A project as read once: every operation receives it, none reads a file again on its own."""

    project: Project
    layout: Layout
    parts: dict[str, Part] = field(default_factory=dict)          # by str(address)
    issues: list[Issue] = field(default_factory=list)             # what opening found
    texts: dict[str, str] = field(default_factory=dict)           # every part's file as read
    files: tuple[str, ...] = ()                                   # every file of the tree
    held: dict[str, Held] = field(default_factory=dict)           # each folder part's other files, by path

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
    return sorted({f for p in project.folder.rglob("*") if p.is_file() and not layout.edited(f := project.relative(p))}
                  if project.folder.is_dir() else set())


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
    registered = schemas.registered()
    context = {"units": catalogue.units(ctx)}
    for file, (kind, name) in sorted(found.items(), key=lambda item: (layout.kinds[item[1][0]].rank, item[0])):
        address, k = Address(kind, name), layout.kinds[kind]
        data, problems = None, []
        try:
            content = persist.read_text(project.path(file))
            opened.texts[file] = content
            data = load_text(content, registered[k.schema_], file, context, exact=True)
        except DefinitionError as exc:
            problems = exc.problems
        except UnicodeDecodeError as exc:                      # a part that cannot be read is a finding on it
            problems = [Problem("", f"this is not text written in UTF-8: byte {exc.start + 1} is not")]
        except OSError as exc:
            problems = [Problem("", f"femkit cannot read this file: {exc.strerror or exc}")]
        opened.issues += [Issue(severity="error", code="unloadable", subject=str(address), file=file,
                                key=p.path or None, message=p.reason, right=p.right, choices=p.choices)
                          for p in problems]
        part = Part(address=address, file=file, data=data,
                    folder=str(PurePosixPath(file).parent) if k.shape == "folder" else None)
        opened.parts[str(address)] = part
        if part.folder is not None:
            _hold(opened, part, k, inside[file])
    opened.issues += [_stray(opened, f, "femkit reads only the project's parts, and this file is none of them")
                      for f in stray]
    return opened


def _stray(opened: Opened, file: str, why: str) -> Issue:
    """A file femkit does not read (projects.md § 6): why, and where the person's own files go."""
    own = opened.layout.person_writes()
    return Issue(severity="warning", code="stray", subject=file, file=file,
                 message=why + (f"; your own files go in {own[0]}/" if own else ""))


def _hold(opened: Opened, part: Part, kind: PartKind, others: list[str]) -> None:
    """A folder part's other files (projects.md § 6): those its kind fixes, and — once its own file
    loads — those it declares by a `file` reference; each read once, with its bytes and SHA-256.
    One missing, unreadable or outside the part's folder is a finding; once the part loads, a file
    of its folder neither fixes nor declares is a stray, never read. A part that does not load
    declares nothing that can be known, so its folder's other files are neither read nor strays."""
    declared: dict[str, tuple[str, ...]] = {name: () for name in kind.files}
    if part.data is not None:
        for location, ref, name, _held in cited(part.data):
            if ref == FILE_REF:
                declared.setdefault(name, _citing(part, location).path)
    the = f"the {part.address.kind} {part.address.name}"
    for name, keys in declared.items():
        at = Address(part.address.kind, part.address.name, keys)
        path = f"{part.folder}/{name}"

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
            data = persist.read_bytes(opened.project.path(path))
        except OSError as exc:
            opened.issues.append(problem("unreadable", f"femkit cannot read {path}: {exc.strerror or exc}"))
            continue
        if data is None:
            opened.issues.append(problem("missing-file", f"{path} is not there" if keys
                                         else f"{the} has no {name}: every {part.address.kind} holds one"))
            continue
        opened.held[path] = Held(part=part.address, name=name, file=path, key=keys, data=data,
                                 sha256=hashlib.sha256(data).hexdigest())
    if part.data is not None:
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
    """Every citation of a part: (the citing part, the location, how it is held, the part cited).
    A `ref` offering alternatives cites the kind that has a part of that name — the first, when
    none has: a citation naming no part."""
    out = []
    for part in opened.parts.values():
        if part.data is None:
            continue
        for location, ref, name, held in cited(part.data):
            kinds = _kinds_of(ref, opened.layout)
            if kinds:
                kind = next((k for k in kinds if str(Address(k, name)) in opened.parts), kinds[0])
                out.append((part, location, held, Address(kind, name)))
    return out


def _citing(part: Part, location: tuple) -> Address:
    """The value that cites: a list's item by its list — entries are keyed by name, never by position."""
    keys = tuple(str(p) for p in location if not isinstance(p, int))
    return Address(part.address.kind, part.address.name, keys)


def references(opened: Opened) -> list[tuple[Address, Address]]:
    """Every citation: (the value that cites, the part it names)."""
    return [(_citing(part, location), target) for part, location, held, target in _citations(opened)]
