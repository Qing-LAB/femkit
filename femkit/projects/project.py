"""A project: one folder under the projects root, named by its path from the root (projects.md § 1);
and a global library: the folder at the root of a part kind the layout declares with one (§§ 1, 4;
materials.md § 4). Each is the one place a path inside it is formed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from femkit.core import text
from femkit.core.errors import UsageError
from femkit.projects import names

PROJECT_FILE = "project.toml"   # what makes a folder a project (projects.md § 2)


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

    def shown(self, relative: str) -> str:
        """A file of the project as a finding names it: by its path from the project's folder
        (core.md § 10)."""
        return relative


@dataclass(frozen=True)
class Library:
    """A global library (projects.md §§ 1, 4; materials.md § 4): the folder ``folder`` — its part
    kind's, `materials` — at ``root``: the projects root, where the person's lies; or femkit's own
    data, where femkit's shipped parts lie as a library does. It holds no project; a part in it is
    named by its path from its folder, as a project's own is (projects.md § 3)."""

    root: Path
    folder: str

    @property
    def place(self) -> Path:
        return self.root / self.folder

    @property
    def subject(self) -> str:
        """Its lock subject (core.md § 5), held alone by every write into it (materials.md § 4)."""
        return f"library-{self.folder}"

    def path(self, relative: str) -> Path:
        """The one place a path inside the library is formed: ``relative`` is a POSIX path from
        the root, inside the library's folder — never absolute, never stepping out with `..`."""
        rel = PurePosixPath(relative)
        if rel.is_absolute() or ".." in rel.parts or rel.parts[:1] != (self.folder,) or relative != str(rel):
            raise UsageError(f"{relative!r} is no path inside the library {text.path(self.place)}",
                             code="outside-library", subject=relative)
        return self.root.joinpath(*rel.parts)

    def relative(self, path: Path) -> str:
        """``path``, inside the library, as the POSIX path from the root."""
        return PurePosixPath(Path(path).relative_to(self.root)).as_posix()

    def shown(self, relative: str) -> str:
        """A file of the library as a finding names it: by its full path, since it lies outside
        every project (materials.md § 4)."""
        return str(self.path(relative))
