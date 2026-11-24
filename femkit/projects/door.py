"""Listing and opening a project (projects.md §§ 2, 3, 6): each part kind's tree read from its
folder as the layout declares it; each part loaded through its registered schema on its own —
a part that does not load is a finding on that part, and every other part is still read; a file
in the tree that no part kind declares is a finding, never read. A part's text is its file as it
holds it, comments kept. The references between parts are read from the schemas' `ref`
annotations; a rename is planned as file steps: the part's file moved, every address naming it
rewritten.

The findings opening makes, each an `Issue` (core.md § 10):
- `unloadable` (error), subject the part's address: its file does not load — the message names
  the file and each problem at its key path;
- `stray` (warning), subject the file's path in the project: a file in the tree no part kind
  declares, never read.
A transaction's check returns `(the address, why)` for each part the change leaves unloadable,
and for each citation the change leaves naming no part.

OWNER: the main line (layout, addresses, the door).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import tomlkit

from femkit.core import persist
from femkit.core.errors import Refused, UsageError
from femkit.core.issues import Issue
from femkit.core.schema import DefinitionError, Model, references as cited, validate
from femkit.projects import layout as layouts
from femkit.projects import names, schemas
from femkit.projects.addresses import Address
from femkit.projects.layout import Layout
from femkit.projects.project import Project
from femkit.projects.transactions import Check, FileStep, Overlay, sha


@dataclass(frozen=True)
class Part:
    address: Address
    file: str                    # its own file, relative to the project
    data: Model | None           # None: it does not load (its finding says why)


@dataclass
class Opened:
    """A project as read once: every operation receives it, none reads a file again on its own."""

    project: Project
    layout: Layout
    parts: dict[str, Part] = field(default_factory=dict)          # by str(address)
    issues: list[Issue] = field(default_factory=list)             # each part's that does not load; stray files
    hashes: dict[str, str | None] = field(default_factory=dict)   # every file read from disk: its sha256
    texts: dict[str, str] = field(default_factory=dict)           # every part's file as read, overlay included
    files: tuple[str, ...] = ()                                   # every file of the tree, as the overlay leaves it

    def part(self, address: Address) -> Part:
        found = self.parts.get(str(address.part))
        if found is None:
            raise UsageError(f"no {address.kind} {address.name!r} in the project {self.project.name}",
                             code="no-such-part", subject=str(address.part))
        return found


# ------------------------------------------------------------------ the tree

def _inventory(project: Project, overlay: Overlay) -> list[str]:
    """Every file in the project's folder, as POSIX paths from it, as ``overlay`` leaves it."""
    on_disk = ({project.relative(p) for p in project.folder.rglob("*") if p.is_file()}
               if project.folder.is_dir() else set())
    made = {p for p, t in overlay.items() if t is not None}
    gone = {p for p, t in overlay.items() if t is None}
    return sorted((on_disk | made) - gone)


def _classify(layout: Layout, files: list[str]) -> tuple[dict[str, tuple[str, str | None]], list[str]]:
    """Each part's own file → (kind, name), and the files no part kind declares. A folder
    part's other files — a component's script — are its own, never stray; a written folder's
    are its writer's, never read. Whether a folder is a part or a group is the layout's."""
    parts: dict[str, tuple[str, str | None]] = {}
    part_folders: list[str] = []
    for kind, k in layout.kinds.items():
        if k.shape != "folder":
            continue
        own = [f for f in files if PurePosixPath(f).name == k.file and PurePosixPath(f).parts[0] == k.folder
               and len(PurePosixPath(f).parts) > 2]
        for f in sorted(own, key=lambda f: len(PurePosixPath(f).parts)):   # the shallowest first: a part's
            name = "/".join(PurePosixPath(f).parts[1:-1])                    # folder holds no part — never both
            if names.valid(name) and not any(f.startswith(folder) for folder in part_folders):
                parts[f] = (kind, name)
                part_folders.append(f"{k.folder}/{name}/")
    stray: list[str] = []
    for f in files:
        if f in parts:
            continue
        rel = PurePosixPath(f)
        top = rel.parts[0]
        if f == layout.kinds[layout.project_kind].file:
            parts[f] = (layout.project_kind, None)
            continue
        if len(rel.parts) > 1 and top in layout.folders:
            continue
        owner = next((kind for kind, k in layout.kinds.items() if k.folder == top), None)
        if owner and len(rel.parts) > 1:
            k = layout.kinds[owner]
            if k.shape == "file" and rel.suffix == ".toml":
                name = PurePosixPath(*rel.parts[1:]).with_suffix("").as_posix()
                if names.valid(name):
                    parts[f] = (owner, name)
                    continue
            if k.shape == "folder" and any(f.startswith(folder) for folder in part_folders):
                continue
        stray.append(f)
    return parts, stray


def listing(project: Project, layout: Layout) -> dict[str, list[str]]:
    """Each named kind's parts by name — a group's in its name — read from the folders."""
    parts, _ = _classify(layout, _inventory(project, {}))
    out: dict[str, list[str]] = {kind: [] for kind, k in layout.kinds.items() if k.named}
    for kind, name in parts.values():
        if name is not None:
            out[kind].append(name)
    return {kind: sorted(found) for kind, found in out.items()}


# ------------------------------------------------------------------ opening

def _load(text: str, model: type[Model], file: str) -> Model:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DefinitionError(file, [("", f"not TOML: {exc}")]) from None
    return validate(model, data, file)


def open_project(project: Project, layout: Layout | None = None, overlay: Overlay | None = None,
                 known: dict[str, str] | None = None) -> Opened:
    """Every part, each on its own; ``overlay`` reads the project as a change would leave it
    (each path's new text, None for a file deleted) — what a transaction's check reads — and
    ``known`` the texts an opened project already read, so none is read again."""
    layout = layout or layouts.load()
    overlay = overlay or {}
    files = _inventory(project, overlay)
    found, stray = _classify(layout, files)
    opened = Opened(project=project, layout=layout, files=tuple(files))
    registered = schemas.registered()
    for file, (kind, name) in sorted(found.items(), key=lambda item: (layout.kinds[item[1][0]].rank, item[0])):
        address = Address(kind, name)
        data = None
        try:
            if file in overlay:
                content = overlay[file]
            elif known is not None and file in known:
                content = known[file]                          # as the opened project read it: no file read again
            else:
                content = persist.read_text(project.path(file))
                opened.hashes[file] = sha(content)             # of the text read, as a transaction checks it
            opened.texts[file] = content
            data = _load(content, registered[layout.kinds[kind].schema_], file)
        except DefinitionError as exc:
            problem = exc.summary()
        except (OSError, UnicodeDecodeError) as exc:           # a part that cannot be read is a finding on it
            problem = f"it cannot be read: {exc}"
        if data is None:
            opened.issues.append(Issue(severity="error", code="unloadable", subject=str(address),
                                       message=f"{address} does not load: {file}: {problem}"))
        opened.parts[str(address)] = Part(address=address, file=file, data=data)
    opened.issues += [Issue(severity="warning", code="stray", subject=f,
                            message=f"{f} is no part of any kind the layout declares; it is never read")
                      for f in stray]
    return opened


def text(opened: Opened, address: Address) -> str:
    """The part's file as it holds it, comments kept; a value's text is its TOML."""
    part = opened.part(address)
    held = opened.texts[part.file]
    if not address.path:
        return held
    doc = tomlkit.parse(held)
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


def check(opened: Opened) -> Check:
    """The check a transaction plans with: the problems the change would leave — a part it touches
    that does not load, a citation it leaves naming no part: one of a part the change took away,
    or a citation it wrote naming what no part was. A part broken elsewhere, or a citation
    naming nothing before the change, is no problem of the change."""
    missing_before = {str(target) for p, loc, held, target in _citations(opened) if str(target) not in opened.parts}

    def problems(overlay: Overlay) -> list[tuple[str, str]]:
        after = open_project(opened.project, opened.layout, overlay, known=opened.texts)
        touched = {str(p.address) for p in after.parts.values() if p.file in overlay}
        found = [(i.subject, i.message) for i in after.issues if i.code == "unloadable" and i.subject in touched]
        found += sorted({(str(_citing(p, loc)), f"names {target}, which the change leaves without a part")
                         for p, loc, held, target in _citations(after)
                         if str(target) not in after.parts
                         and (str(target) in opened.parts or (p.file in overlay and str(target) not in missing_before))})
        return found
    return problems


# ------------------------------------------------------------------ rename

def _rewrite(content: str, location: tuple, held: str, new: str) -> str:
    """``content`` with the name at ``location`` replaced by ``new``, its comments and order kept."""
    doc = tomlkit.parse(content)
    if held == "key":                                    # a table keyed by the name: the key renamed in place
        persist.document_rename(doc, tuple(location), new)
        return tomlkit.dumps(doc)
    node: Any = doc
    for key in location[:-1]:
        node = node[key]
    node[location[-1]] = new
    return tomlkit.dumps(doc)


def rename(opened: Opened, address: Address, new: str) -> list[FileStep]:
    """The steps renaming a part — moving it to another group is one: its file (or folder) moved,
    every address naming it rewritten, comments kept."""
    part = opened.part(address)
    kind = opened.layout.kinds[address.kind]
    if not kind.named:
        raise UsageError(f"the {address.kind} is the project's one, and has no name to change",
                         code="unnamed-part", subject=str(address.part))
    names.check(new, what=f"a {address.kind}'s name")
    target = Address(address.kind, new)
    others = [p.address.name for p in opened.parts.values() if p.address.kind == address.kind and p.address != address]
    if str(target) in opened.parts:
        raise Refused(f"there is a {address.kind} {new!r} already", code="name-taken", subject=str(target))
    if kind.shape == "folder" and any(o.startswith(new + "/") or new.startswith(o + "/") for o in others):
        raise Refused(f"{new!r} would make a {address.kind}'s folder a group as well, or put it inside "
                      "another's: a folder is a part or a group, never both", code="name-taken", subject=str(target))
    if kind.shape == "file":
        moves = {part.file: f"{kind.folder}/{new}.toml"}
    else:
        old, fresh = f"{kind.folder}/{address.name}/", f"{kind.folder}/{new}/"
        moves = {f: fresh + f.removeprefix(old) for f in opened.files if f.startswith(old)}
    rewritten: dict[str, str] = {}
    for citer, location, held, cited_part in _citations(opened):
        if cited_part == address.part:
            rewritten[citer.file] = _rewrite(rewritten.get(citer.file, opened.texts[citer.file]), location, held, new)
    steps = [FileStep(kind="move", path=f, to=to) for f, to in moves.items() if f not in rewritten]
    for source, new_text in sorted(rewritten.items()):
        if source in moves:                               # the part cites itself: its new text goes where it moves
            steps += [FileStep(kind="delete", path=source), FileStep(kind="create", path=moves[source], text=new_text)]
        else:
            steps.append(FileStep(kind="change", path=source, text=new_text))
    return steps
