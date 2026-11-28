"""`femkit/data/stages.toml` and `femkit/data/artifacts.toml` (workflow.md §§ 2.1, 2.2): the kinds
of stage a case's pipeline is made of, and the typed artifacts that flow between them.

An artifact type is named `<what>/<form>` — `geometry/xao`, `mesh/msh-2.2` — and declares its
file's name, its format in words and, where femkit opens it, the environment and the command.

A stage kind declares the documents femkit writes for it, each with its file's name; the
artifacts it reads and writes — each by the name its program and its check call it, a role — where
the environment it runs in comes from: a fixed one by its name, or `engine`, the environment the
engine chosen to solve resolves to (`ENGINE`), the one home of a stage's environment; its program and its
check as argument lists in the core's one grammar (core.md § 2.1); the part whose fixed files a
stage of it gets in its folder (`brings`) — the component, its script among them, which its
program runs — or none; the batch a meshing job holds its stages in; and whether it runs as one
process. A kind declared before its stages are made (`made`) — the observe kind, until the solve's
(M6) — states where it runs and what it brings alone: the one home of the environment its part's
script runs in, which the check frame reads what that script may import from. Each placeholder names `{python}`, the environment's own (jobs.md § 4, block
9); a document it is handed (`femkit/engines/stages/documents.py`); one of the two records its
check writes, `{checked}` and `{outputs}` (jobs.md § 5.1); or one of its files by its role — one
it writes only when asked, alone and optional, `{mesh?}`. A kind its mesher fills — the mesh
stage — leaves its environment, the artifacts it reads and writes and its program to the
mesher's definition (workflow.md § 2.3; `meshers.py`), and its check may name the roles every
mesher writes, which the catalogue holds the meshers to.

Their models live here, with the shipped definitions' others, since the catalogue that loads them
sits below the `workflow` package that reads them (framework.md § 1).
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Mapping

from pydantic import ConfigDict, Field, RootModel, ValidationInfo, model_validator

from femkit.core.schema import Model, check_arguments, parsed, refuse, whole
from femkit.engines.stages.documents import RECORDS   # the records a check writes, by its documents' kinds

#: An artifact type's name: what it is, then its form (workflow.md § 2.2).
TYPE = re.compile(r"[a-z]+/[a-z0-9][a-z0-9.-]*")
ArtifactType = Annotated[str, Field(pattern=whole(TYPE.pattern))]
#: A role: the name a program and its check call one of their files by.
ROLE = r"[a-z][a-z0-9_]*"
Role = Annotated[str, Field(pattern=whole(ROLE))]
#: A file's name in a stage's run: no folder, never hidden.
FILE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
#: What every program and check of a stage may name beside its own files: the environment's own
#: `python` (jobs.md § 4, block 9).
PYTHON = "python"
#: The slots of a stage kind a filler fills (workflow.md § 2.3).
SLOTS = ("environment", "inputs", "outputs", "asked", "program")
#: What a stage kind's `environment` takes for the environment the engine chosen to solve resolves to
#: (workflow.md § 2.1; framework.md § 5) — the solve kind's alone; no environment takes the name.
ENGINE = "engine"


class Opened(Model):
    """How an artifact is opened: the environment its command runs in, and the command."""

    environment: str = Field(description="the environment the command runs in, by name")
    command: list[str] = Field(min_length=1, description="the command, `{file}` the artifact's file",
                               json_schema_extra={"placeholders": ["file"]})


class Artifact(Model):
    """One artifact type (workflow.md § 2.2): what flows between stages."""

    file: str = Field(description="its file's name in the run of the stage that writes it")
    format: str = Field(description="its format, in words")
    opened: Opened | None = Field(default=None, description="how femkit opens it; none for a document femkit reads, "
                                                            "or one whose opening is not measured yet")


class ArtifactList(RootModel[dict[ArtifactType, Artifact]]):
    """`artifacts.toml`: each artifact type by its name, `<what>/<form>`. Its validation context may
    hold `environments`, the environments' names: given, each `opened` runs in one of them."""

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def _references(self, info: ValidationInfo) -> "ArtifactList":
        environments = (info.context or {}).get("environments")
        problems: list[tuple[tuple, str]] = []
        for name, artifact in self.root.items():
            if not FILE.fullmatch(artifact.file):
                problems.append(((name, "file"), f"{artifact.file!r} is no file's name in a run: letters, digits, "
                                                  "`.`, `_` and `-`, in no folder and not hidden"))
            if artifact.opened is None:
                continue
            if environments is not None and artifact.opened.environment not in environments:
                problems.append(((name, "opened", "environment"), f"{artifact.opened.environment!r} is no "
                                 f"environment (they are: {', '.join(sorted(environments))})"))
            try:
                check_arguments(artifact.opened.command, frozenset({"file"}))
            except ValueError as exc:
                problems.append(((name, "opened", "command"), str(exc)))
        refuse("ArtifactList", problems)
        return self


class StageKind(Model):
    """One kind of stage (workflow.md § 2.1): what it reads and writes, where and how it runs, and
    the check that judges what it wrote."""

    description: str = Field(description="what the stage does, in one sentence")
    filled_by: Literal["mesher"] | None = Field(default=None, description="what fills the slots it leaves unset — "
                                                "its environment, the artifacts it reads and writes, its program: "
                                                "`mesher`, the mesher its mesh recipe states; none: it states each "
                                                "itself", json_schema_extra={"doc": "workflow.md § 2.3"})
    environment: str | None = Field(default=None, description="where the environment it runs in comes from: a fixed "
                                                              "one, by its name, or `engine`, the environment the "
                                                              "engine chosen to solve resolves to",
                                    json_schema_extra={"doc": "workflow.md § 2.1"})
    documents: dict[str, str] = Field(default_factory=dict, description="the documents femkit writes for it, each by "
                                      "its kind, with its file's name in the stage's folder: what its program and its "
                                      "check are handed")
    brings: str | None = Field(default=None, description="the part kind whose fixed files a stage of it gets in its "
                                                         "folder, as the project layout declares them — `component`, "
                                                         "its script and the files its contract declares; none: it "
                                                         "runs femkit's program on what stages before it made",
                               json_schema_extra={"doc": "workflow.md § 2.1"})
    batch: str | None = Field(default=None, pattern=whole(ROLE), description="the name of the batch of its stages a "
                              "meshing job holds; none for a kind whose stages ride no meshing job",
                              json_schema_extra={"doc": "workflow.md § 7"})
    inputs: dict[Role, ArtifactType] | None = Field(default=None, description="the artifacts it reads from the "
                                                    "stages before it, each by the name its program calls it")
    outputs: dict[Role, ArtifactType] | None = Field(default=None, description="the artifacts it always writes, "
                                                     "each by the name its program and its check call it")
    asked: dict[Role, ArtifactType] = Field(default_factory=dict, description="the artifacts it writes only when "
                                            "asked — a stage after it reads them, or the component's contract "
                                            "declares them under `[outputs]` by this name")
    program: list[str] | None = Field(default=None, description="its program: `{python}`, the file it runs, and its "
                                      "arguments — each placeholder a document it is handed, `{checked}` or "
                                      "`{outputs}`, or one of its files by its name here, `{mesh?}` one written only "
                                      "when asked")
    check: list[str] | None = Field(default=None, description="its contract's check: `{python}`, one of femkit's "
                                    "stage programs, and its arguments, named as its program's are; it writes the "
                                    "run's verdict, `{checked}`, and, when passed, each output's SHA-256, `{outputs}`; "
                                    "none for a kind declared before its stages are made")
    one_process: bool = Field(default=False, description="whether it runs as one process, `ranks = 1`, whatever its "
                              "job holds", json_schema_extra={"doc": "jobs.md § 1.1"})

    @property
    def made(self) -> bool:
        """Whether its stages are made: it runs something — a check of its own, its program its
        filler's or its own; a kind declared before its stages are made states where it runs and
        what it brings alone (workflow.md § 2.1)."""
        return self.check is not None

    def femkits(self, programs: frozenset[str]) -> list[str]:
        """femkit's own programs a stage of this kind runs (jobs.md § 1.1), among ``programs``,
        femkit's stage programs: the file its check runs, and the file its program runs where that
        is one of them, not a file of the part it brings — each the file its argument list runs, as
        the grammar of a stage's program declares it (`ran`)."""
        return sorted({ran(self.check), *([ran(self.program)] if self.program and ran(self.program) in programs
                                          else [])})

    def roles(self) -> dict[str, str]:
        """Each of its own files by its role: what it reads, writes, and writes when asked."""
        return {**(self.inputs or {}), **(self.outputs or {}), **self.asked}

    def writes(self) -> set[str]:
        """Each artifact type it writes, always or when asked; none for a kind a filler fills."""
        return {*(self.outputs or {}).values(), *self.asked.values()}


class Stages(Model):
    """`stages.toml`: each stage kind by its name — the name its folders are formed by
    (projects.md § 2) — the name of the sequence a study's meshing job is, beside the batches each
    kind names (workflow.md § 7), and the file a stage's folder keeps what it is made from in
    (§ 4). Its validation context may hold `environments`, `artifacts`
    (the artifact types' names), `programs` (femkit's stage programs, by their files' names),
    `documents` (the kinds of document a stage may be handed) and `parts` (each part kind of the
    project layout with the files every part of it holds by a fixed name): given, what each kind
    names is one of them."""

    sequence: str = Field(pattern=whole(ROLE), description="the name of the sequence `study prep` writes for a "
                          "study — of the batches each kind's `batch` names — before `-<study>-NNN`",
                          json_schema_extra={"doc": "workflow.md § 7"})
    made_from: str = Field(pattern=whole(FILE.pattern), description="the file a stage's folder keeps what the stage "
                           "is made from in, whose SHA-256 as canonical JSON is its ID, and by which every reader "
                           "finds a case's stages", json_schema_extra={"doc": "workflow.md § 4"})
    kinds: dict[Annotated[str, Field(pattern=whole(ROLE))], StageKind] = Field(
        description="each stage kind by its name, the name its folders are formed by",
        json_schema_extra={"doc": "workflow.md § 2.1"})

    @model_validator(mode="after")
    def _whole(self, info: ValidationInfo) -> "Stages":
        """Each kind whole, each batch a kind's own, the sequence no batch; and the kinds in the
        order a study's meshing sequence runs their batches, each taking only from kinds before it
        (workflow.md § 7) — a kind a filler fills takes what its fillers read, which the catalogue
        holds to this order when it loads them (`taken_late`)."""
        context = info.context or {}
        problems: list[tuple[tuple, str]] = []
        for name, kind in self.kinds.items():
            problems += [(("kinds", name, *at), why) for at, why in _kind_problems(kind, context)]
        batches = [k.batch for k in self.kinds.values() if k.batch is not None]
        problems += [(("kinds", name, "batch"), f"{kind.batch!r} is another kind's batch too: each kind's stages a "
                                                "batch of their own")
                     for name, kind in self.kinds.items() if kind.batch is not None and batches.count(kind.batch) > 1]
        if self.sequence in batches:
            problems.append((("sequence",), f"{self.sequence!r} is a kind's batch too: a launch folder's name is "
                                            "one job's"))
        late = taken_late(list(self.kinds), {n: set((k.inputs or {}).values()) for n, k in self.kinds.items()},
                          {n: k.writes() for n, k in self.kinds.items()})
        problems += [(("kinds", name, "inputs", role), late_why(later, [ty])) for name, later, types in late
                     for role, ty in (self.kinds[name].inputs or {}).items() if ty in types]
        refuse("Stages", problems)
        return self


def taken_late(order: list[str], reads: Mapping[str, set[str]], writes: Mapping[str, set[str]]
               ) -> list[tuple[str, str, list[str]]]:
    """Each kind, in ``order`` — the order a study's meshing sequence runs their batches — that
    takes artifacts a kind after it writes: the kind, that later kind, and the types (workflow.md
    § 7: "each kind taking only from kinds before it"). ``reads`` and ``writes`` give each kind's
    types; a kind a filler fills, its fillers'."""
    return [(name, later, types) for i, name in enumerate(order) for later in order[i + 1:]
            if (types := sorted(reads.get(name, set()) & writes.get(later, set())))]


def late_why(later: str, types: list[str]) -> str:
    """Why a kind may not take ``types`` from the kind ``later`` after it."""
    return (f"it takes {', '.join(types)}, which the kind {later} after it writes: a study's meshing sequence "
            "runs the kinds' batches in their order, so a kind takes only from kinds before it")


def _kind_problems(kind: StageKind, context: dict) -> list[tuple[tuple, str]]:
    """What is wrong with one stage kind, each at its key: a slot its filler fills stated too, or
    one left unset with no filler; a name the catalogue does not declare; a placeholder naming none
    of its files, documents or records, or one optional where its file is always there."""
    problems: list[tuple[tuple, str]] = []
    stated = [slot for slot in SLOTS if getattr(kind, slot) not in (None, {})]
    if kind.filled_by is not None and stated:
        problems.append(((), f"its {kind.filled_by} fills {', '.join(stated)}: one home for each, never two"))
    if kind.filled_by is None:
        wanted = ("environment", "inputs", "outputs", "program", "batch") if kind.made else ("environment",)
        unset = [s for s in wanted if getattr(kind, s) is None]
        if unset:
            problems.append(((), f"with no filler, it states {', '.join(unset)}"))
    if not kind.made and any(getattr(kind, s) not in (None, {}) for s in ("program", "inputs", "outputs", "asked")):
        problems.append((("check",), "a kind that reads, writes or runs anything states the check that judges it: "
                                     "one declared before its stages are made states where it runs alone"))
    if kind.filled_by is not None and (not kind.made or kind.batch is None):
        problems.append(((), "a kind its filler fills states its check and its batch"))
    environments, artifacts = context.get("environments"), context.get("artifacts")
    programs, documents, parts = context.get("programs"), context.get("documents"), context.get("parts")
    if environments is not None and kind.environment not in (None, ENGINE, *environments):
        problems.append((("environment",), f"{kind.environment!r} is neither an environment nor `{ENGINE}`, the "
                                           "environment the engine chosen to solve resolves to"))
    if parts is not None and kind.brings is not None and kind.brings not in parts:
        problems.append((("brings",), f"{kind.brings!r} is no part kind of the project layout (they are: "
                                      f"{', '.join(sorted(parts))})"))
    for table in ("inputs", "outputs", "asked"):
        for role, typ in (getattr(kind, table) or {}).items():
            if artifacts is not None and typ not in artifacts:
                problems.append(((table, role), f"{typ!r} is no artifact type `artifacts.toml` declares"))
    problems += [(("documents", d), f"{f!r} is no file's name in a run: letters, digits, `.`, `_` and `-`, in no "
                                    "folder and not hidden") for d, f in kind.documents.items() if not FILE.fullmatch(f)]
    if documents is not None and set(kind.documents) - documents:
        problems.append((("documents",), f"{', '.join(sorted(set(kind.documents) - documents))}: no document a stage "
                                         f"is handed (they are: {', '.join(sorted(documents))})"))
    roles = kind.roles()
    if len(roles) != sum(len(getattr(kind, t) or {}) for t in ("inputs", "outputs", "asked")):
        problems.append(((), "a role names one file of the stage, never two"))
    for table in ("inputs", "outputs", "asked"):
        problems += [((table, role), f"`{role}` names a document or a check's record: one placeholder, one file")
                     for role in sorted(set(getattr(kind, table) or {}) & reserved(kind.documents))]
    named = {PYTHON, *kind.documents, *RECORDS, *roles}
    for field in ("program", "check"):
        template = getattr(kind, field)
        if template is None:
            continue
        why = arguments_problem(template, named, set(kind.asked), open_names=kind.filled_by is not None)
        # A program runs one of femkit's stage programs, or a file every part the kind brings holds
        # by its fixed name — the component's script; a check, one of femkit's alone.
        brings = kind.brings if field == "program" else None
        known = None if programs is None else set(programs)
        if known is not None and brings is not None:
            known = None if parts is None else known | set(parts.get(brings, ()))
        if why is None and known is not None and ran(template) not in known:
            why = f"{ran(template)!r} is none of femkit's stage programs (they are: {', '.join(sorted(programs))})" \
                  + (f", nor a file every {brings} holds" if brings else "")
        if why is not None:
            problems.append(((field,), why))
    return problems


#: Where a stage's argument list names the file it runs: after `{python}`, the environment's own
#: python (workflow.md § 2.1; jobs.md § 4, block 9) — the grammar `arguments_problem` holds every
#: program and check to.
RUNS = 1


def ran(template: list[str]) -> str:
    """The file a stage's program or check runs, by its name: what its argument list names after
    `{python}`, as `arguments_problem` holds it."""
    return template[RUNS]


def reserved(documents) -> set[str]:
    """The names no role may take, since its placeholder names another file: `{python}`, the
    documents a stage is handed, and the records its check writes."""
    return {PYTHON, *RECORDS, *documents}


def arguments_problem(template: list[str], named: set[str], asked: set[str] = frozenset(),
                      open_names: bool = False, run: bool = True) -> str | None:
    """Why an argument list is not one a stage runs, or None: with ``run``, `{python}`, then a
    file's name, then its arguments; each placeholder a whole argument, naming one of ``named`` —
    or, with ``open_names``, any role, held to its filler by the catalogue — optional exactly when
    it names one of ``asked``, the files written only when asked, and never with an argument."""
    try:
        check_arguments(template, frozenset(named) | frozenset(asked) if not open_names else
                        frozenset({p.name for a in template for p in parsed(a)}))
    except ValueError as exc:
        return str(exc)
    if run and (len(template) <= RUNS or template[0] != "{" + PYTHON + "}" or parsed(ran(template))
                or not FILE.fullmatch(ran(template))):
        return "a stage's program runs on its environment's own python: `{python}`, then the file it runs"
    for argument in template[RUNS + 1:] if run else template:
        for p in parsed(argument):
            if p.argument is not None or p.span != (0, len(argument)):
                return f"{argument!r}: a placeholder is a whole argument, with no argument of its own"
            if open_names and not re.fullmatch(ROLE, p.name):
                return f"{argument!r}: {{{p.name}}} is no role"
            if p.optional != (p.name in asked):
                return (f"{argument!r}: {{{p.name}?}} is optional exactly when its file is written only when asked"
                        if not p.optional else f"{argument!r}: {{{p.name}}} is always there, so never optional")
    return None
