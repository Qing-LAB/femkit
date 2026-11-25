"""Listing and opening a project (projects.md §§ 2, 3, 6): each part kind's tree read from its
folder as the layout declares it; each part loaded through its registered schema on its own —
a part that does not load is a finding on that part, and every other part is still read; a file
in the tree that no part kind declares is a finding, never read. A part's text is its file as it
holds it, comments kept. The references between parts are read from the schemas' `ref`
annotations. The door only reads: femkit changes no file the person wrote (projects.md § 7).

The findings opening makes, each an `Issue` (core.md § 10):
- `unloadable` (error), subject the part's address: its file does not load — the message names
  the file and each problem at its key path;
- `stray` (warning), subject the file's path in the project: a file in the tree no part kind
  declares, never read.

A part's text, or a value's, that cannot be given is refused: `UsageError` `unloadable`, subject
the address asked for — a part that could not be read, a value in a part that is not TOML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

import tomlkit

from femkit.core import persist
from femkit.core.errors import UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, Model, load_text, references as cited
from femkit.definitions import catalogue
from femkit.projects import layout as layouts
from femkit.projects import names, schemas
from femkit.projects.addresses import Address
from femkit.projects.layout import Layout
from femkit.projects.project import PROJECT_FILE, Project


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
    texts: dict[str, str] = field(default_factory=dict)           # every part's file as read
    files: tuple[str, ...] = ()                                   # every file of the tree

    def part(self, address: Address) -> Part:
        found = self.parts.get(str(address.part))
        if found is None:
            raise UsageError(f"no {address.kind} {address.name!r} in the project {self.project.name}",
                             code="no-such-part", subject=str(address.part))
        return found


# ------------------------------------------------------------------ the tree

def _inventory(project: Project) -> list[str]:
    """Every file in the project's folder, as POSIX paths from it."""
    return sorted({project.relative(p) for p in project.folder.rglob("*") if p.is_file()}
                  if project.folder.is_dir() else set())


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
        if f == PROJECT_FILE:
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
    parts, _ = _classify(layout, _inventory(project))
    out: dict[str, list[str]] = {kind: [] for kind, k in layout.kinds.items() if k.named}
    for kind, name in parts.values():
        if name is not None:
            out[kind].append(name)
    return {kind: sorted(found) for kind, found in out.items()}


# ------------------------------------------------------------------ opening

def open_project(project: Project, ctx: Context, layout: Layout | None = None) -> Opened:
    """Every part, each on its own, read as every declared file is: by `schema.load_text`, its
    numbers exact and the unit table in its validation context (projects.md § 6)."""
    layout = layout or layouts.load()
    files = _inventory(project)
    found, stray = _classify(layout, files)
    opened = Opened(project=project, layout=layout, files=tuple(files))
    registered = schemas.registered()
    context = {"units": catalogue.units(ctx)}
    for file, (kind, name) in sorted(found.items(), key=lambda item: (layout.kinds[item[1][0]].rank, item[0])):
        address = Address(kind, name)
        data = None
        try:
            content = persist.read_text(project.path(file))
            opened.texts[file] = content
            data = load_text(content, registered[layout.kinds[kind].schema_], file, context, exact=True)
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
