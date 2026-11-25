"""Where projects are (projects.md § 1): one projects root, `paths.projects` in config.toml,
holding the global library of each kind the layout declares with one (`materials/`) and the
projects. A command names a project as a whole: by its path from the root, or, with none named,
by the folder it runs in, when that folder is the project or lies inside it. A project is the
folder holding `project.toml`; every path inside it is relative, so it moves whole. The first
`project new` makes the root; every other command refuses a root that is no folder, naming it.

Paths in a project are formed by `Project.path` alone.
"""

from __future__ import annotations

from pathlib import Path

from femkit.config import settings
from femkit.config.requests import CONFIG_SET
from femkit.core import view
from femkit.core.errors import Refused, Unstated, UsageError
from femkit.core.operations import Context
from femkit.projects import layout as layouts
from femkit.projects import names
from femkit.projects.project import PROJECT_FILE, Project
from femkit.projects.requests import PROJECT_NEW

KEY = "paths.projects"         # the setting that names the root (config.md § 3)


def _state_root() -> view.Action:
    return view.command(CONFIG_SET, key=KEY, note="the folder that holds your projects",
                        fills=[view.Fill(field="value", label=KEY, example='"/path/to/projects"')])


def _make_root() -> view.Action:
    return view.command(PROJECT_NEW, note="the first project makes the root",
                        fills=[view.Fill(field="name", label="the new project's name"),
                               view.Fill(field="source", label="a template, or a project to copy")])


def stated(ctx: Context) -> Path:
    """`paths.projects`, whether a folder is there or not yet; `Unstated` (code `setting-unset`,
    subject `paths.projects`, with the `config set` that states it) while unset."""
    folder = settings.load(ctx).config.paths.projects
    if folder is None:
        raise Unstated(f"{KEY} is unset: no projects root is stated", (_state_root(),),
                       code="setting-unset", subject=KEY)
    return folder


def root(ctx: Context) -> Path:
    """The projects root, `paths.projects` (`stated`); `Refused` (code `no-root`, naming the
    `project new` that makes it and the `config set` that states another) when it is no folder."""
    folder = stated(ctx)
    if not folder.is_dir():
        raise Refused(f"the projects root {folder} ({KEY}) is no folder: the first project new makes it",
                      (_make_root(), _state_root()), code="no-root", subject=str(folder))
    return folder


def libraries() -> frozenset[str]:
    """The folders at the root that hold a global library, never a project: one for each kind the
    layout declares with one (projects.md §§ 1, 4)."""
    return frozenset(layouts.read().libraries().values())


def _holds_none(steps: tuple[str, ...], held: frozenset[str]) -> bool:
    """A folder, by its steps from the root, that holds no project: a global library at the root,
    or a `.`-folder (projects.md § 1)."""
    return (len(steps) == 1 and steps[0] in held) or steps[-1].startswith(".")


def project_at(top: Path, name: str) -> Project | None:
    """The project ``name`` names under ``top`` — a projects root, or femkit's templates — when its
    folder holds the project file, what makes a folder a project (projects.md § 2); None when it
    does not, or ``name`` breaks the name rule. The one test of whether a folder is a project."""
    if not names.valid(name):
        return None
    candidate = Project(top, name)
    return candidate if candidate.path(PROJECT_FILE).is_file() else None


def _is_project(top: Path, steps: tuple[str, ...]) -> Project | None:
    """The project the folder at ``steps`` from the root is, when it holds `project.toml`."""
    return project_at(top, "/".join(steps))


def along(top: Path, steps: tuple[str, ...]) -> Project | None:
    """The project a folder, by its steps from the root ``top``, is or lies inside: the first
    folder from the root down that holds `project.toml` — a project inside another's folder is not
    looked for, and a global library, a `.`-folder or a folder the name rule cannot name holds none."""
    held = libraries()
    for i in range(1, len(steps) + 1):
        if _holds_none(steps[:i], held) or not names.valid(steps[i - 1]):
            return None
        if found := _is_project(top, steps[:i]):
            return found
    return None


def projects(ctx: Context) -> list[Project]:
    """Every project under the root, by name; the global libraries and `.`-folders are none."""
    top = root(ctx)
    held = libraries()
    found: list[Project] = []

    def look(folder: Path, steps: tuple[str, ...]) -> None:
        for child in folder.iterdir():
            here = (*steps, child.name)
            if not child.is_dir() or _holds_none(here, held) or not names.valid(child.name):
                continue                                       # a folder the name rule cannot name holds none
            if project := _is_project(top, here):
                found.append(project)                          # what lies inside it is the project's
            else:
                look(child, here)                              # a group folder

    look(top, ())
    return sorted(found, key=lambda p: p.name)


def locate(ctx: Context, name: str | None, cwd: Path) -> Project:
    """The project ``name`` names from the root; with none, the one ``cwd`` is or lies inside
    (the nearest folder holding `project.toml`, below the root; a project inside another's folder
    is not looked for). `UsageError` (code `no-such-project`, subject the name) for a name with no
    project; (code `not-in-a-project`, subject ``cwd``) when none is named and ``cwd`` is in none."""
    top = root(ctx)
    if name is not None:
        wanted = Project(top, name)   # the name rule: `bad-name`
        if along(top, tuple(names.steps(name))) != wanted:
            raise UsageError(f"no project {name!r} under the projects root {top}", code="no-such-project",
                             subject=name)
        return wanted
    # The root and the folder compared as the file system has them: a command runs in a real path,
    # and the root may be stated through a link.
    here, real = cwd.resolve(), top.resolve()
    found = along(top, here.relative_to(real).parts) if here.is_relative_to(real) else None
    if found is None:
        raise UsageError(f"{cwd} is in no project under the projects root {top}: name the project, or run "
                         "the command in its folder", code="not-in-a-project", subject=str(cwd))
    return found
