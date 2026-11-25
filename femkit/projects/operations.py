"""The `project` verbs that need nothing above the door (models.md § 11.1): `project list`, the
projects under the root (projects.md § 1), and `project new`, a copy of one of femkit's templates
or of one of the person's projects — what the person writes, and nothing femkit or a run wrote
(projects.md § 7)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from femkit.core import persist, text, view
from femkit.core.errors import Refused, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.schema import Model
from femkit.definitions import catalogue
from femkit.projects import door, location, names
from femkit.projects import layout as layouts
from femkit.projects.door import Opened
from femkit.projects.layout import Layout
from femkit.projects.project import Project
from femkit.projects.requests import PROJECT_LIST, PROJECT_NEW, ListRequest, NewRequest


# ------------------------------------------------------------------ project list

class ProjectRow(Model):
    name: str = Field(description="its name: its path from the projects root")
    path: str = Field(description="its folder")
    studies: list[str] = Field(default_factory=list, description="its studies, by name, as its folders hold them")


class ProjectList(Result):
    root: str = Field(description="the projects root, `paths.projects`")
    projects: list[ProjectRow] = Field(default_factory=list, description="each project under the root, by name")

    def report(self) -> view.Report:
        return view.Report(blocks=[
            view.Text(text=f"{text.count(len(self.projects), 'project')} in {text.path(self.root)}"),
            view.Table(columns=view.columns("name", "studies"),
                       rows=[{"name": p.name, "studies": text.show(p.studies)} for p in self.projects])])


@operation(PROJECT_LIST, result=ProjectList)
def project_list(req: ListRequest, ctx: Context) -> ProjectList:
    """The projects under the projects root, each with its studies — the parts of the kind the
    layout lists (projects.md §§ 1, 4)."""
    top = location.root(ctx)
    layout = layouts.read()
    return ProjectList(root=str(top), projects=[
        ProjectRow(name=p.name, path=str(p.folder),
                   studies=door.listing(p, layout).get(layout.listed, []) if layout.listed else [])
        for p in location.projects(ctx)])


# ------------------------------------------------------------------ project new

class NewOutcome(Outcome):
    name: str = Field(description="the new project's name: its path from the projects root")
    path: str = Field(description="its folder")
    source: str = Field(description="what it copies: a template by its bare name, or a project by its path from "
                                    "the projects root")
    copied: list[str] = Field(default_factory=list, description="each file copied, by its path from the project's "
                                                                "folder")

    def report(self) -> view.Report:
        if self.status != "done":
            return view.Report(blocks=[view.Text(text=f"{text.path(self.path)} is not made")])
        return view.Report(blocks=[
            view.Text(text=f"made {text.path(self.path)} from {self.source}: {text.count(len(self.copied), 'file')}"),
            view.Table(columns=view.columns("file"), rows=[{"file": f} for f in self.copied])])


def _choose(templates: dict[str, Path], name: str) -> list[view.Action]:
    """`project new` of the project ``name`` from each template."""
    return [view.command(PROJECT_NEW, name=name, source=template) for template in templates]


def _source(ctx: Context, given: str | None, top: Path, name: str) -> Project:
    """What ``given`` names: a template by its bare name, or a project by its path from the root —
    refused when it is none, both, or not given, offering the new project ``name`` from each
    template (projects.md § 7)."""
    templates = catalogue.templates(ctx)
    if given is None:
        raise UsageError(f"project new copies a template or one of your projects, named with --from; the "
                         f"templates: {', '.join(templates) or 'none'}", _choose(templates, name),
                         code="no-source", subject="source")
    names.check(given, what="a template's or a project's name")
    project = location.along(top, tuple(names.steps(given))) if top.is_dir() else None
    project = project if project == Project(top, given) else None
    template = Project(templates[given].parent, given) if given in templates else None
    if project is not None and template is not None:
        raise UsageError(f"{given!r} names both femkit's template {given} and your project {project.folder}",
                         code="ambiguous-source", subject=given)
    if project is None and template is None:
        raise UsageError(f"no template or project is named {given!r}; the templates: {', '.join(templates) or 'none'}",
                         (view.command(PROJECT_LIST), *_choose(templates, name)), code="no-such-source", subject=given)
    return project or template


def _target(top: Path, name: str, layout: Layout) -> Project:
    """The new project ``name`` names under the root ``top`` — refused, naming it, when it breaks
    the name rule, opens with a global library's folder, lies inside a project, or would replace a
    file or folder (projects.md § 7)."""
    names.check(name, what="a project's name")
    steps = names.steps(name)
    if steps[0] in layout.libraries().values():
        raise UsageError(f"{name!r} would lie in {steps[0]}/, a global library at the projects root, which holds "
                         "no project", code="in-library", subject=name)
    inner = location.along(top, tuple(steps[:-1])) if top.is_dir() else None
    if inner is not None:
        raise UsageError(f"{name!r} would lie inside the project {inner.name}", code="inside-project", subject=name)
    target = Project(top, name)
    for i in range(1, len(steps) + 1):
        there = Project(top, "/".join(steps[:i])).folder
        if there.is_symlink() or (there.exists() and (i == len(steps) or not there.is_dir())):
            raise Refused(f"{there} is there already: a new project is never made over it", code="exists",
                          subject=name)
    return target


#: Who writes what a copy leaves out, as a sentence says it (projects.md § 4).
WRITTEN_BY = {"femkit": "femkit writes", "run": "a run writes"}


def _written(opened: Opened) -> tuple[list[str], list[Issue]]:
    """What the person writes, by its path from the project's folder (projects.md §§ 4, 7): each
    part of a kind the person writes with the files it fixes and declares — all its folder's, for
    a folder part that does not load, whose declarations cannot be read — and each folder the
    person writes; never what femkit or a run writes, nor a stray. And each file left out, as an
    `info` finding `not-copied` saying why — a folder femkit or a run writes once, with how many
    files it holds."""
    layout = opened.layout
    def writer(kind: str) -> str:
        return layout.kinds[kind].writer

    theirs = [p for p in opened.parts.values() if writer(p.address.kind) == "person"]
    kept = {p.file for p in theirs} | {h.file for h in opened.held.values() if writer(h.part.kind) == "person"}
    unread = tuple(p.folder + "/" for p in theirs if p.folder is not None and p.data is None)
    kept |= {f for f in opened.files if unread and f.startswith(unread)}
    kept |= {f for f in opened.files if "/" in f and (top := f.split("/")[0]) in layout.folders
             and layout.folders[top].writer == "person"}
    kinds = {p.file: p.address.kind for p in opened.parts.values()} | {h.file: h.part.kind for h in opened.held.values()}
    left: list[Issue] = []
    folders: dict[str, int] = {}
    for f in (f for f in opened.files if f not in kept):
        top = f.split("/")[0]
        if "/" in f and top in layout.folders:
            folders[top] = folders.get(top, 0) + 1
            continue
        why = (f"{WRITTEN_BY[writer(kinds[f])]} this file" if f in kinds
               else "femkit does not read this file, as it is none of the project's parts")
        left.append(Issue(severity="info", code="not-copied", subject=f, file=f, message=f"not copied: {why}"))
    left += [Issue(severity="info", code="not-copied", subject=f"{top}/", file=f"{top}/",
                   message=f"not copied: {WRITTEN_BY[layout.folders[top].writer]} what this folder holds "
                           f"({text.count(n, 'file')})")
             for top, n in sorted(folders.items())]
    return sorted(kept), left


def _planned(req: NewRequest, ctx: Context) -> tuple[Path, Project, Project, list[str], list[Issue]]:
    """The root, the new project, what it copies, the files it copies, and each it leaves out."""
    top = location.stated(ctx)
    if top.exists() and not top.is_dir():
        raise Refused(f"the projects root {top} ({location.KEY}) is no folder", code="no-root", subject=str(top))
    target = _target(top, req.name, layouts.read())
    source = _source(ctx, req.source, top, req.name)
    return top, target, source, *_written(door.open_project(source, ctx))


@operation(PROJECT_NEW, result=NewOutcome, changes=True, subject="plan")
class ProjectNew:
    """Make a new project under the projects root, a copy of one of femkit's templates or of one of
    your projects: every part, the files each fixes and declares, and your own folder — nothing
    femkit or a run wrote; the first makes the root (projects.md § 7)."""

    def observe(self, req: NewRequest, ctx: Context) -> dict:
        """Whether the root is there, and each file the copy takes with its digest."""
        top, _, source, files, _ = _planned(req, ctx)
        return {"root": top.is_dir(), "files": {f: persist.sha256(source.path(f)) for f in files}}

    def plan(self, req: NewRequest, ctx: Context) -> Plan:
        """The steps, and each file the copy leaves out with why, as a note (projects.md § 7)."""
        top, target, source, files, left = _planned(req, ctx)
        steps = [] if top.is_dir() else [Step(id="root", describe=f"make the projects root {text.path(top)}")]
        steps.append(Step(id="copy", describe=f"copy {text.count(len(files), 'file')} of {req.source} to "
                                              f"{text.path(target.folder)}"
                                              + (", leaving out what each note below names" if left else "")))
        return Plan(subjects=(target.subject,), steps=tuple(steps), issues=left,
                    holds={"root": str(top), "path": str(target.folder), "from": str(source.folder), "files": files})

    def apply(self, plan: Plan, ctx: Context, observer) -> NewOutcome:
        req, held = NewRequest.model_validate(plan.request), plan.holds

        def do(step: Step, where: Path):
            if step.id == "root":
                persist.make_folder(Path(held["root"]))
            else:
                persist.copy_tree(Path(held["from"]), Path(held["path"]), only=held["files"])
            return "done", None

        status, log = run_steps(plan, ctx, observer, do)
        return NewOutcome(plan=plan, status=status, log=str(log), name=req.name, path=held["path"],
                          source=req.source or "", copied=held["files"] if status == "done" else [],
                          issues=list(plan.issues))
