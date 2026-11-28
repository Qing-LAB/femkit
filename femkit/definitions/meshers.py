"""`femkit/data/meshers/<id>.toml` and `femkit/data/handovers/<name>.toml` (workflow.md § 2.3;
geometry.md § 8): a mesher, a program of the mesh stage, and a hand-over of a mesh to an engine.

A mesher fills the mesh stage's slots (`stages.py`): the environment that provides it, its
program and arguments, the artifacts it reads and writes — each by the name its program calls it
— the recipe keys it honours and where its mesh's geometry order comes from. A mesh stage's mesher
is the one its mesh recipe states, never the study's, and a mesher names no engine (geometry.md
§ 6). A hand-over is keyed by the artifact type it reads and the engine it hands to: the geometry
orders it hands over, the places whose groups it hands by name, its conversion in words, and its
program; which engine takes what a mesher writes is the hand-overs' one lookup (`handover`); the
catalogue refuses two hand-overs giving one engine one type at one order.

A mesher and a hand-over state only what is measured or cited, in `basis`; what is not known is
left out.
"""

from __future__ import annotations

from typing import Literal, Mapping

from pydantic import Field, ValidationInfo, field_validator, model_validator

from femkit.core.schema import Model, check_placeholders, placeholders, refuse
from femkit.definitions.places import FRAMES
from femkit.definitions.stages import ArtifactType, Role, arguments_problem, reserved

Order = Literal[1, 2]   # a geometry order (geometry.md § 6)
#: What a hand-over's arguments name: the mesh it reads, and the `handover` document femkit writes
#: for it — the groups it hands (geometry.md § 8).
HANDOVER_PLACEHOLDERS = frozenset({"mesh", "handover"})


class Tolerance(Model):
    """How close two points must be for the mesher to merge them."""
    kind: Literal["absolute", "relative"] = Field(description="in the length unit geometry is handed over in, "
                                                              "or relative to the model's size")
    value: str = Field(description="a plain number")


class MesherDefinition(Model):
    """One mesher, a program of the mesh stage (workflow.md § 2.3). Its validation context may hold
    `environments`, `artifacts`, `programs` — femkit's stage programs — and `documents`, those the
    stage it fills is handed: given, what it names is one of them."""

    description: str = Field(description="one line")
    provided_by: str = Field(description="the environment it runs in, which provides it")
    dimensions: list[Literal[FRAMES]] = Field(min_length=1, description="the dimensions it meshes")
    tolerance: Tolerance | None = Field(default=None, description="its geometric tolerance; absent: not known, "
                                                                  "and no feature can be checked against it")
    orders: list[Order] = Field(min_length=1, description="the geometry orders its mesh may have")
    order: Literal["recipe", "contract"] = Field(description="where its mesh's geometry order comes from: the "
                                                             "recipe's `order`, or, for a mesh the script wrote, the "
                                                             "order the component's contract declares")
    program: str = Field(description="its program, one of femkit's stage programs, run on its environment's own "
                                     "python")
    arguments: list[str] = Field(description="its program's arguments: each placeholder a document its stage is "
                                             "handed, `{recipe}`, or one of its files by its name in `reads` or "
                                             "`writes`")
    reads: dict[Role, ArtifactType] = Field(description="the artifacts it reads from the stages before it, each by "
                                                        "the name its program calls it")
    writes: dict[Role, ArtifactType] = Field(min_length=1, description="the artifacts it writes — its mesh and its "
                                             "region map — each by the name its program and the mesh's check call it")
    honours: list[str] = Field(description="the keys of a mesh recipe it honours; another the recipe states is not "
                                           "honoured", json_schema_extra={"doc": "models.md § 6.2"})
    basis: str = Field(description="where these facts come from: what was measured, on which version, or a citation")

    @model_validator(mode="after")
    def _references(self, info: ValidationInfo) -> "MesherDefinition":
        context = info.context or {}
        environments, artifacts = context.get("environments"), context.get("artifacts")
        programs, documents = context.get("programs"), context.get("documents")
        problems: list[tuple[tuple, str]] = []
        if environments is not None and self.provided_by not in environments:
            problems.append((("provided_by",), f"{self.provided_by!r} is not an environment "
                                               f"(they are: {', '.join(sorted(environments))})"))
        if programs is not None and self.program not in programs:
            problems.append((("program",), f"{self.program!r} is none of femkit's stage programs "
                                           f"(they are: {', '.join(sorted(programs))})"))
        for table in ("reads", "writes"):
            for role, typ in getattr(self, table).items():
                if artifacts is not None and typ not in artifacts:
                    problems.append(((table, role), f"{typ!r} is no artifact type `artifacts.toml` declares"))
        problems += [(("reads", role), f"`{role}` names a file it writes too: one name, one file")
                     for role in sorted(set(self.reads) & set(self.writes))]
        problems += [((table, role), f"`{role}` names a document or a check's record: one placeholder, one file")
                     for table in ("reads", "writes")
                     for role in sorted(set(getattr(self, table)) & reserved(documents or ()))]
        roles = {*self.reads, *self.writes}
        why = arguments_problem(self.arguments, roles | set(documents if documents is not None else ()),
                                run=False, open_names=documents is None)
        named = {p for a in self.arguments for p, _ in placeholders(a)}
        if why is None and roles - named:
            why = f"its program is handed no {', '.join('{%s}' % r for r in sorted(roles - named))}: every file it " \
                  "reads or writes is named"
        if why is not None:
            problems.append((("arguments",), why))
        refuse("MesherDefinition", problems)
        return self


class HandOver(Model):
    """How one engine receives a mesh of the type it reads, at the geometry orders it lists, inside
    the engine's own job, before the solve (geometry.md § 8). Its validation context may hold
    `artifacts`, `places` and `engine_packages` — each registered engine with its package's
    folder: given, what it names is one of them."""

    reads: ArtifactType = Field(description="the mesh it hands over, by its artifact type")
    engine: str = Field(description="the engine, by its registered adapter's ID")
    orders: list[Order] = Field(min_length=1, description="the geometry orders it hands over as written; an engine's "
                                                          "hand-overs of one type share none, so the order a case "
                                                          "asks for chooses one")
    names: list[str] = Field(min_length=1, description="the places whose groups it hands the engine, each by its name "
                                                       "(geometry.md § 7)")
    conversion: str = Field(description="how the mesh reaches the engine, in words")
    program: str = Field(description="the hand-over program, a file of the engine's package run inside its "
                                     "environment: it converts or builds the engine's mesh and finds every handed "
                                     "group's name in it")
    arguments: list[str] = Field(description="the program's arguments, as the run's files are named",
                                 json_schema_extra={"placeholders": sorted(HANDOVER_PLACEHOLDERS)})
    outputs: list[str] = Field(description="what the program leaves for the solve, a file or a folder, by its name in "
                                           "the run")
    basis: str = Field(description="what was measured, on which versions")

    @field_validator("arguments")
    @classmethod
    def _arguments(cls, arguments: list[str]) -> list[str]:
        for argument in arguments:
            check_placeholders(argument, HANDOVER_PLACEHOLDERS)
        named = {n for a in arguments for n, _ in placeholders(a)}
        if named != HANDOVER_PLACEHOLDERS:
            raise ValueError(f"names {', '.join('{%s}' % n for n in sorted(HANDOVER_PLACEHOLDERS - named))} nowhere: "
                             "a hand-over reads the mesh and the groups it hands")
        return arguments

    @model_validator(mode="after")
    def _references(self, info: ValidationInfo) -> "HandOver":
        context = info.context or {}
        artifacts, places, packages = context.get("artifacts"), context.get("places"), context.get("engine_packages")
        problems: list[tuple[tuple, str]] = []
        if artifacts is not None and self.reads not in artifacts:
            problems.append((("reads",), f"{self.reads!r} is no artifact type `artifacts.toml` declares"))
        if packages is not None and self.engine not in packages:
            problems.append((("engine",), f"no engine adapter registers {self.engine!r} "
                                          f"(registered: {', '.join(sorted(packages))})"))
        elif packages is not None and not (packages[self.engine] / self.program).is_file():
            problems.append((("program",), f"{self.engine}'s package holds no {self.program}"))
        for place in sorted(set(self.names) - places) if places is not None else ():
            problems.append((("names",), f"{place!r} is no place (they are: {', '.join(sorted(places))})"))
        refuse("HandOver", problems)
        return self


def handover(handovers: Mapping[str, HandOver], engine: str, order: int, types) -> str | None:
    """The hand-over by which ``engine`` receives a mesh of one of ``types`` at geometry ``order``
    (geometry.md § 8): keyed by the type it reads, the engine and the order — the one lookup; None
    where none is declared — a recipe whose mesh that engine cannot take, which refuses its prep
    (workflow.md § 2.2), a match line once matching is built (models.md § 6.2)."""
    types = set(types)
    return next((n for n, h in handovers.items() if h.engine == engine and order in h.orders and h.reads in types),
                None)
