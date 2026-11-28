"""The one catalogue of every file of a calculation folder, a launch folder and a run (jobs.md
§ 1.1): `femkit/data/jobs/files.toml`, read here and nowhere else, once per invocation through its
context (`read_once`). Every name the jobs domain writes or reads — the request, the run script,
each record of a run — is the catalogue's, looked up by its role; nothing here or in the domain
spells one a second time.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from femkit.core.operations import Context
from femkit.core.schema import Model, load_toml, refuse
from femkit.definitions import catalogue as definitions
from femkit.engines.stages import documents

FILE = Path("jobs") / "files.toml"   # under the shipped definitions (definitions.md § 1)
WHERE = Literal["calculation", "launch", "run"]
#: How the catalogue writes a run's folder's name: each `N` one digit of its number.
NUMBERED = re.compile(r"([^N]*)(N+)")


class FileRow(Model):
    """One file: its name, where it lies, who writes and reads it, and whether a run holds a copy."""

    name: str = Field(description="its name; one in angle brackets stands for the files the request or its maker "
                                  "names, `run-NNN` for each run's folder, each `N` a digit of its number")
    lies: list[WHERE] = Field(min_length=1, description="where it lies: a calculation folder, a launch folder, a run")
    writer: str = Field(description="who writes it, the one writer")
    readers: list[str] = Field(min_length=1, description="who reads it")
    copied: bool = Field(default=False, description="whether `job launch` copies it from the calculation folder "
                                                    "into each run")
    own: bool = Field(default=False, description="a write of the run's own, made while it runs: what tells how "
                                                 "long ago a run last wrote (jobs.md § 5.2, rule 6)")
    source: str | None = Field(default=None, description="for a program of femkit's, where `job prepare` copies it "
                                                         "from: its path from the femkit package")
    module: bool = Field(default=False, description="a module femkit's programs run with, beside them: hashed with "
                                                    "them into a stage's identity — the monitor, which watches a run "
                                                    "and makes nothing, is none", json_schema_extra={
                                                        "doc": "workflow.md § 4"})
    document: str | None = Field(default=None, description="for a record a stage's check writes, the stage programs' "
                                                           "document it holds, by its kind (`documents.py`): what "
                                                           "a stage's check names it by", json_schema_extra={
                                                               "doc": "jobs.md § 5.1"})
    says: str = Field(description="what it holds")


class Catalogue(Model):
    """`femkit/data/jobs/files.toml`: every file of a calculation folder, a launch folder and a run."""

    programs: str = Field(description="the folder of femkit's own programs, by its path from the femkit package: a "
                                      "request's `programs` name theirs in it")
    files: dict[str, FileRow] = Field(description="each file by its role, the name the jobs domain looks it up by")

    @model_validator(mode="after")
    def _documents(self) -> "Catalogue":
        """Each record a stage's check writes, as the stage programs' documents name them
        (`documents.RECORDS`), held by one file, and no file holding another document."""
        kinds = [r.document for r in self.files.values() if r.document is not None]
        refuse("Catalogue", [(("files", role, "document"), f"{r.document!r} is no record a stage's check writes "
                                                           f"(they are: {', '.join(documents.RECORDS)})")
                             for role, r in self.files.items()
                             if r.document is not None and r.document not in documents.RECORDS]
               + [(("files",), f"two files hold the record {k!r}") for k in sorted({k for k in kinds
                                                                                     if kinds.count(k) > 1})]
               + [(("files",), f"no file holds the record {k!r} a stage's check writes")
                  for k in documents.RECORDS if k not in kinds])
        return self

    def row(self, role: str) -> FileRow:
        return self.files[role]

    def name(self, role: str) -> str:
        """The name of the file of ``role``."""
        return self.row(role).name

    def programs_folder(self) -> Path:
        """The folder of femkit's own programs (framework.md § 1)."""
        return package() / self.programs

    def beside(self) -> dict[str, Path]:
        """Every file `job prepare` copies into a calculation folder from femkit itself — the monitor
        and the modules every program runs with — by its name there, with its source."""
        return {r.name: package() / r.source for r in self.files.values() if r.source is not None}

    def modules(self) -> frozenset[str]:
        """The names of the modules femkit's programs run with, which `beside` copies with them: what a
        stage's identity hashes beside its programs, never the monitor (workflow.md § 4)."""
        return frozenset(r.name for r in self.files.values() if r.module and r.source is not None)

    def copied(self) -> list[str]:
        """The names of the files of a calculation folder a run holds a copy of, those the catalogue
        names itself; the request's inputs and programs besides."""
        return [r.name for r in self.files.values() if r.copied and "calculation" in r.lies and self._named(r)]

    def own(self) -> frozenset[str]:
        """The names of the files a run writes of its own while it runs (jobs.md § 5.2, rule 6)."""
        return frozenset(r.name for r in self.files.values() if r.own and self._named(r))

    def documents(self) -> dict[str, str]:
        """Each record a stage's check writes into its run in the shape of a stage program's document,
        by that document's kind, with its file's name: what a stage kind's check names them by
        (jobs.md § 5.1; workflow.md § 2.1)."""
        return {r.document: r.name for r in self.files.values() if r.document is not None}

    def record(self, kind: str) -> str:
        """The name of the file holding the record a stage's check writes of ``kind`` — one of
        `documents.RECORDS`, the one place they are named (jobs.md § 5.1)."""
        return self.documents()[kind]

    def reserved(self) -> frozenset[str]:
        """Every name the catalogue gives a file itself: a request's input, output, program or shared
        file takes none of them, nor a run folder's."""
        return frozenset(r.name for r in self.files.values() if self._named(r))

    def _named(self, r: FileRow) -> bool:
        """Whether the catalogue names this file itself — not a stand-in for files named elsewhere."""
        return not r.name.startswith("<") and r.name != self.name("run")

    def _numbered(self) -> tuple[str, int]:
        """A run folder's name before its number, and the number's digits."""
        found = NUMBERED.fullmatch(self.name("run"))
        assert found, f"{file()}: files.run.name {self.name('run')!r} is no `<text>N…`"
        return found.group(1), len(found.group(2))

    def run_name(self, number: int) -> str:
        """The folder of a calculation folder's ``number``-th run, from 1."""
        before, digits = self._numbered()
        return f"{before}{number:0{digits}d}"

    def run_number(self, folder: str) -> int | None:
        """The number of the run whose folder is named ``folder``; None for a name no run has."""
        before, digits = self._numbered()
        found = re.fullmatch(re.escape(before) + rf"(\d{{{digits},}})", folder)
        return int(found.group(1)) if found else None


def file() -> Path:
    """The catalogue's file, under the shipped definitions — or a test's own (definitions.md § 1)."""
    return definitions.data_root() / FILE


def read() -> Catalogue:
    """The catalogue; a `DefinitionError` naming each problem when it does not load."""
    return load_toml(file(), Catalogue)


def read_once(ctx: Context) -> Catalogue:
    """The catalogue, read once per invocation (jobs.md § 1.1; api.md § 2.4): every name the jobs
    domain writes or reads is looked up in it."""
    return ctx.cached("jobs/files", read)


def package() -> Path:
    """The femkit package, which a program's `source` and the programs' folder are paths from."""
    return Path(definitions.__file__).resolve().parent.parent
