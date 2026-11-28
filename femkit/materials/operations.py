"""The `material` verbs (models.md § 11.1): `material import`, a new material from another
source's file, in the global library or a project's `materials/` — never over one there, and
never into one (materials.md § 7; projects.md § 7). Its plan rests on the file's digest, so a file
changed before the import is applied is refused, `PlanStale`; it names what it writes and where,
and holds the lock of what it writes into — the library's or the project's (materials.md § 4;
core.md § 5). The file is read through `core/persist.py`, and the new material written through
the door, built apart and moved into place (projects.md § 6).

Its refusals, besides the importer's (`importer.py`), the door's and those of finding the
projects root and a project (`projects/location.py`), each with its code and subject, and what to
do instead (core.md § 9; materials.md § 7):
- `no-such-source` (`UsageError`, subject the source given): no importer is declared for it — the
  import as each declared source's file its next steps;
- `unreadable` (`UsageError`, subject the file given): the file is there and cannot be read;
- `no-library` (`Refused`, subject the library's folder): the projects root holds no global
  library yet, which the next `project new` makes (materials.md § 4) — that its next step;
- the door's `exists` and `inside-part` (`Refused`, subject the name given): a material, a group
  or a file is there, or the name lies inside a material — the import under another name its
  next step, a name free there its example, and the dataset's lines copied into the material
  there the way to add it to that one.

Its plan says, as a warning `found-first` about the new material, when the global library holds
a material of the name an import into a project takes: the project's is found first from then
on, for every assignment naming it (materials.md §§ 4, 7).
"""

from __future__ import annotations

import builtins

from pathlib import Path
from typing import Callable

from pydantic import Field

from femkit.core import persist, text, view
from femkit.core.errors import Refusal, Refused, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Step, operation, run_steps
from femkit.definitions import catalogue
from femkit.materials import importer, material
from femkit.materials.importer import Imported
from femkit.materials.requests import MATERIAL_IMPORT, ImportRequest
from femkit.projects import door, location, names
from femkit.projects import layout as layouts
from femkit.projects.addresses import Address
from femkit.projects.door import Home
from femkit.projects.layout import Layout
from femkit.projects.project import Library
from femkit.projects.requests import PROJECT_CHECK, PROJECT_NEW


class ImportOutcome(Outcome):
    name: str = Field(description="the new material, by the name an assignment gives it: `GLOBAL/<name>` in the "
                                  "global library")
    path: str = Field(description="its folder")
    property: str = Field(description="the property its dataset is held under")
    dataset: str = Field(description="its dataset, by its name")
    files: list[str] = Field(default_factory=list, description="each file written, by its path from the material's "
                                                               "folder")
    next: list[view.Action] = Field(default_factory=list, description="its next step: imported into a project, the "
                                    "project checked; into the library, none — a project naming it is checked as any "
                                    "other", json_schema_extra={"doc": "projects.md § 8"})

    @builtins.property      # `property`, above, is the field naming the material's property
    def report(self) -> view.Report:
        if self.status != "done":
            return view.Report(blocks=[view.Text(text=f"{text.path(self.path)} is not made")])
        return view.Report(blocks=[
            view.Text(text=f"made the material {self.name} in {text.path(self.path)}: its {self.property}, the "
                           f"dataset {self.dataset}"),
            view.Table.of(ImportOutcome, [{"files": f} for f in self.files], "files"),
            *([view.Next(label="check the project it is in", actions=self.next)] if self.next else [])])


def _library(req: ImportRequest, ctx: Context, layout: Layout, kind: str) -> Home:
    """The global library of ``kind`` at the projects root; refused, `no-library`, where the root
    holds none yet."""
    library = Library(location.root(ctx), layout.libraries()[kind])
    if not library.place.is_dir():
        raise Refused(f"the projects root holds no global library yet, {library.place}: the next project new makes it, "
                      "holding femkit's shipped materials, and an import can go into it from then on",
                      (view.command(PROJECT_NEW, note="a new project makes the global library, holding femkit's "
                                                      "shipped materials",
                                    fills=[view.Fill(field="name", label="the new project's name"),
                                           view.Fill(field="source", label="a template, or a project to copy")]),),
                      code="no-library", subject=str(library.place))
    return library


def _project(req: ImportRequest, ctx: Context, layout: Layout, kind: str) -> Home:
    """The project the request names, or the one the command runs in (projects.md § 1)."""
    return location.locate(ctx, req.project, Path.cwd())


#: Where each `--into` puts the new material.
INTO: dict[str, Callable[[ImportRequest, Context, Layout, str], Home]] = {"library": _library, "project": _project}


def _target(req: ImportRequest, ctx: Context) -> tuple[Home, Layout, str]:
    """What the new material goes into, the layout, and the material's part kind in it."""
    layout = layouts.read_once(ctx)
    kind = layout.kind_of(material.KEY)
    return INTO[req.into](req, ctx, layout, kind), layout, kind


def _again(req: ImportRequest, note: str, fill: view.Fill | None = None, **changes) -> view.Action:
    """The import as ``req`` asks it but for ``changes``, and for the value ``fill`` asks for."""
    values = {k: v for k, v in req.model_dump(mode="json").items() if v is not None} | changes
    if fill is not None:
        values.pop(fill.field, None)
    return view.command(MATERIAL_IMPORT, note=note, fills=[fill] if fill is not None else [], **values)


#: How many names `_free` tries, `<name>_2` onward.
TRIED = 98


def _free(home: Home, layout: Layout, kind: str, name: str) -> str | None:
    """The first of `<name>_2`, `<name>_3`, … a new material may take in ``home``; None where none
    of the first `TRIED` may."""
    for n in range(2, 2 + TRIED):
        try:
            door.new_part(home, layout, kind, f"{name}_{n}")
        except Refusal:
            continue
        return f"{name}_{n}"
    return None


def _new(home: Home, layout: Layout, kind: str, req: ImportRequest) -> Path:
    """Where the new material goes (`door.new_part`): never over or into one there. Refused as the
    door refuses, with what to do instead: import it under another name — one free there, where
    one is — and, to add its dataset to the material there, copy its lines (materials.md § 7)."""
    try:
        return door.new_part(home, layout, kind, req.name)
    except Refused as exc:
        free = _free(home, layout, kind, req.name)
        fill = view.Fill(field="name", label="another name for the new material", example=free)
        raise Refused(f"{exc}. Import it under another name{f', as {free}' if free else ''}; to add its dataset to a "
                      "material you have, copy the dataset's lines and its table from the new material into yours, "
                      "and project check checks them",
                      (_again(req, "the import under another name", fill),), code=exc.code,
                      subject=exc.subject) from None


def _found_first(home: Home, kind: str, req: ImportRequest, ctx: Context) -> list[Issue]:
    """A warning, `found-first`, where the import goes into a project and the global library holds
    a material of its name: the project's is found first from then on, for every assignment
    naming it, and `GLOBAL/<name>` names the library's (materials.md §§ 4, 7)."""
    if isinstance(home, Library):
        return []
    listed = door.open_project(home, ctx).libraries.get(kind)
    if listed is None or req.name not in listed.names:
        return []
    return [Issue(severity="warning", code="found-first", subject=str(Address(kind, req.name)),
                  message=f"the global library holds a material {req.name} too: from now on the project's is found "
                          f"first, for every assignment naming {req.name}, and {names.GLOBAL}{req.name} names the "
                          "library's")]


def _read(req: ImportRequest) -> bytes | None:
    """The source's file, from the folder the command runs in; None where no file is there."""
    try:
        return persist.read_bytes(Path.cwd() / req.file)
    except OSError as exc:
        raise UsageError(f"{req.file}: femkit cannot read it: {exc.strerror or exc}", code="unreadable",
                         subject=req.file) from None


def _planned(req: ImportRequest, ctx: Context) -> tuple[Home, Layout, str, Path, Imported]:
    """What the new material goes into, the layout, its kind, its folder — refused where it cannot
    be new — and what the file becomes."""
    importers = catalogue.importers(ctx)
    if req.source not in importers:
        raise UsageError(f"femkit has no importer for {req.source!r}; it has {', '.join(importers) or 'none'}",
                         tuple(_again(req, f"the file read as {s}'s", source=s) for s in importers),
                         code="no-such-source", subject=req.source)
    home, layout, kind = _target(req, ctx)
    folder = _new(home, layout, kind, req)
    made = importer.imported(importers[req.source], req.source, req.file, _read(req), name=req.name,
                             own=layout.kinds[kind].file, properties=catalogue.properties(ctx),
                             dispersion=catalogue.dispersion(ctx), units=catalogue.units(ctx),
                             manual=layout.kinds[kind].manual)
    return home, layout, kind, folder, made


@operation(MATERIAL_IMPORT, result=ImportOutcome, subject="plan")
class MaterialImport:
    """Make a new material from another source's file, in your global library or a project's
    materials: its one dataset, with its source, convention, range and conditions, and a table's
    file. Never over or into a material there: to add the dataset to a material you have, copy its
    lines and its table into yours, and project check checks them."""

    def observe(self, req: ImportRequest, ctx: Context) -> dict:
        """The file's digest, which the plan rests on."""
        data = _read(req)
        return {"file": persist.digest(data) if data is not None else None}

    def plan(self, req: ImportRequest, ctx: Context) -> Plan:
        """One step, writing the new material's folder whole, under the lock of what it goes into."""
        home, _, kind, folder, made = _planned(req, ctx)
        named = (names.GLOBAL if isinstance(home, Library) else "") + req.name
        step = Step(id="write", describe=f"write the new material {named} in {text.path(folder)}: "
                                         f"{', '.join(made.files)}")
        return Plan(subjects=(home.subject,), steps=(step,), issues=_found_first(home, kind, req, ctx),
                    holds={"name": named, "path": str(folder), "property": made.property, "dataset": made.dataset,
                           "files": {f: data.decode("utf-8") for f, data in made.files.items()}})

    def apply(self, plan: Plan, ctx: Context, observer) -> ImportOutcome:
        req, held = ImportRequest.model_validate(plan.request), plan.holds
        home, layout, kind = _target(req, ctx)
        _new(home, layout, kind, req)                   # never over or into one: refused before any step

        def do(step: Step, where: Path):
            door.write_part(home, layout, kind, req.name, {f: t.encode("utf-8") for f, t in held["files"].items()})
            return "done", None

        status, log = run_steps(plan, ctx, observer, do)
        return ImportOutcome(plan=plan, status=status, log=str(log), name=held["name"], path=held["path"],
                             property=held["property"], dataset=held["dataset"],
                             files=list(held["files"]) if status == "done" else [],
                             next=[view.command(PROJECT_CHECK, **({"project": req.project} if req.project else {}))]
                             if status == "done" and req.into == "project" else [])
