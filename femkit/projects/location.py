"""Where projects are (projects.md § 1): one projects root, `paths.projects` in config.toml,
holding the global material library (`materials/`) and the projects. A command names a project
as a whole: by its path from the root, or, with none named, by the folder it runs in, when that
folder is the project or lies inside it. A project is the folder holding `project.toml`; every
path inside it is relative, so it moves whole.

OWNER: the location piece. Paths in a project are formed by `Project.path` alone.
"""

from __future__ import annotations

from pathlib import Path

from femkit.config import settings
from femkit.config.requests import CONFIG_SET
from femkit.core import view
from femkit.core.errors import Refused, Unstated, UsageError
from femkit.core.operations import Context
from femkit.projects import names
from femkit.projects.project import PROJECT_FILE, Project

GLOBAL_LIBRARY = "materials"   # under the root: the person's global material library (materials.md § 4)
KEY = "paths.projects"         # the setting that names the root (config.md § 3)


def _state_root() -> view.Action:
    return view.command(CONFIG_SET, key=KEY, note="the folder that holds your projects",
                        fills=[view.Fill(field="value", label=KEY, example='"/path/to/projects"')])


def root(ctx: Context) -> Path:
    """`paths.projects`; `Unstated` (code `setting-unset`, subject `paths.projects`, with the
    `config set` that states it) while unset; `Refused` (code `no-root`) when it is no folder."""
    folder = settings.load(ctx).config.paths.projects
    if folder is None:
        raise Unstated(f"{KEY} is unset: no projects root is stated", (_state_root(),),
                       code="setting-unset", subject=KEY)
    if not folder.is_dir():
        raise Refused(f"the projects root {folder} ({KEY}) is no folder", (_state_root(),),
                      code="no-root", subject=str(folder))
    return folder


def _holds_none(steps: tuple[str, ...]) -> bool:
    """A folder, by its steps from the root, that holds no project: the root's global library,
    or a `.`-folder (projects.md § 1)."""
    return steps == (GLOBAL_LIBRARY,) or steps[-1].startswith(".")


def _along(top: Path, steps: tuple[str, ...]) -> Project | None:
    """The project a folder, by its steps from the root, is or lies inside: the first folder from
    the root down that holds `project.toml` — a project inside another's folder is not looked for."""
    for i in range(1, len(steps) + 1):
        if _holds_none(steps[:i]):
            return None
        if (top.joinpath(*steps[:i]) / PROJECT_FILE).is_file():
            return Project(top, "/".join(steps[:i]))
    return None


def projects(ctx: Context) -> list[Project]:
    """Every project under the root, by name; the global library and `.`-folders are none."""
    top = root(ctx)
    found: list[Project] = []

    def look(folder: Path, steps: tuple[str, ...]) -> None:
        for child in folder.iterdir():
            here = (*steps, child.name)
            if not child.is_dir() or _holds_none(here) or not names.valid(child.name):
                continue                                       # a folder the name rule cannot name holds none
            if (child / PROJECT_FILE).is_file():
                found.append(Project(top, "/".join(here)))   # what lies inside it is the project's
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
        if _along(top, tuple(names.steps(name))) != wanted:
            raise UsageError(f"no project {name!r} under the projects root {top}", code="no-such-project",
                             subject=name)
        return wanted
    # The root and the folder compared as the file system has them: a command runs in a real path,
    # and the root may be stated through a link.
    here, real = cwd.resolve(), top.resolve()
    found = _along(top, here.relative_to(real).parts) if here.is_relative_to(real) else None
    if found is None:
        raise UsageError(f"{cwd} is in no project under the projects root {top}: name the project, or run "
                         "the command in its folder", code="not-in-a-project", subject=str(cwd))
    return found
