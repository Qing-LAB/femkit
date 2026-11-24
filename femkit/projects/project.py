"""A project: one folder under the projects root, named by its path from the root (projects.md § 1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from femkit.core.errors import UsageError
from femkit.projects import names

PROJECT_FILE = "project.toml"   # what makes a folder a project (projects.md § 2)
LOCAL = ".femkit"               # undo history, uploads, the page's view file: never moves (projects.md § 2)


@dataclass(frozen=True)
class Project:
    """A project under ``root``, named by its path from it — the name rule's (projects.md § 3)."""

    root: Path
    name: str

    def __post_init__(self) -> None:
        names.check(self.name, what="a project's name")

    @property
    def folder(self) -> Path:
        return self.root / self.name

    @property
    def subject(self) -> str:
        """Its lock subject (core.md § 5): a name's steps never hold a `.`, so `/` becomes one."""
        return "project-" + self.name.replace("/", ".")

    def path(self, relative: str) -> Path:
        """The one place a path inside the project is formed: ``relative`` is a POSIX path from
        the project's folder — never absolute, never stepping out with `..` — so every path the
        project holds is relative, and the project moves whole (projects.md § 1)."""
        rel = PurePosixPath(relative)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts or relative != str(rel):
            raise UsageError(f"{relative!r} is no path inside a project: relative, with no `..`",
                             code="outside-project", subject=relative)
        return self.folder.joinpath(*rel.parts)

    def relative(self, path: Path) -> str:
        """``path``, inside the project, as the POSIX path from its folder."""
        return PurePosixPath(Path(path).relative_to(self.folder)).as_posix()
