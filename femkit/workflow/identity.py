"""A stage's identity (workflow.md § 4): what it is made from — `stage.json`, its model `MadeFrom`,
written and read here alone (`kept`, `read`), by the name the workflow's own declaration gives it,
`stages.toml`'s `made_from` (`named`): to the jobs domain, which knows nothing of stages, it is a
maker's file of a calculation folder (jobs.md § 1.1), which that domain alone finds in a folder
(`folders.maker_file`, `file`) — and its ID, the SHA-256 of that as canonical JSON (core.md § 4).
Every kind's stage is made from each stage it takes from, by the role of the input that stage
writes, the SHA-256 of each program its folder runs, the target's machine by its record's identity
of the host — never the record's name, so two records of one machine name the same stages — and
the install fingerprint of the stage's environment as the target's record lists it; beside them,
what its kind lists — a geometry's component, all of the case's but its assignment
(`cases.Drawing`), the order of the mesh its script writes and the outputs it gives; a mesh's
recipe, the case's (`cases.CaseRecipe`), its mesher among it — each read through the case's model
(models.md § 5.3). So a changed program or a rebuilt environment makes a stage anew, a second
machine its own, and two studies never share one, each stage lying in its study's folder.

A geometry or a mesh stage holds nothing of an engine, serving every engine: a study whose solve
turns to GPUs, or to another engine, reuses its geometries and meshes. The environment a solve stage serves joins
what it is made from with its kind (plan § 4, M6).

Forming an ID needs the fingerprint: a record that does not list the stage's environment, or lists
its fingerprint unknown, is refused, `Unstated` · `no-fingerprint` (`NO_FINGERPRINT`), naming the
environment; its next steps, on that machine, where the record lists it not installed, what the
environment's own table gives an absent one — its install (envs.md § 3.3) — then what writes the
record — for this machine's, from the one source (`prepare.record_steps`) (workflow.md §§ 4, 7). Which record: the one the jobs
domain's one choice of a target gives (`prepare.choose`, jobs.md § 3, step 2), as `job prepare`
chooses it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from femkit.core import persist
from femkit.core.errors import Unstated
from femkit.core.operations import Context
from femkit.core.schema import Model
from femkit.definitions import catalogue
from femkit.envs import state as env_state
from femkit.jobs import folders, layout, prepare, record, runs
from femkit.models.cases import CaseRecipe, Drawing

#: The shape `stage.json` is written in (models.md § 2), raised whenever what one of its fields holds
#: changes, so a file of an earlier shape reads `unreadable`, saying the shape it states, never as a
#: stage of this one (workflow.md § 4).
SHAPE = 3
#: The code of the refusal of an identity its target's record gives no fingerprint for (workflow.md
#: §§ 4, 7), exported where it is raised: a refusal `study prep`'s machine step waits on.
NO_FINGERPRINT = "no-fingerprint"


class Took(Model):
    """A stage another takes an input from: its kind and its ID, what its address is formed by."""

    kind: str = Field(description="its stage kind")
    id: str = Field(description="its ID")


class MadeFrom(Model):
    """`stage.json`: what a stage is made from (workflow.md § 4), kept in its folder, whose SHA-256
    as canonical JSON is its ID. A field one kind's stages are not made from is none."""

    schema_: Literal[SHAPE] = Field(alias="schema", description="the shape of this file, raised when it changes",
                                    json_schema_extra={"doc": "models.md § 2"})
    kind: str = Field(description="its stage kind", json_schema_extra={"doc": "workflow.md § 2.1"})
    takes_from: dict[str, Took] = Field(description="each input it reads from a stage before it, by the role its "
                                                    "program calls it: the stage that writes it")
    component: Drawing | None = Field(description="the case's `component` but its assignment, for a stage that runs "
                                                  "the component's script: its SHA-256 among its files, each input's "
                                                  "value, the frame, the promised groups",
                                      json_schema_extra={"doc": "models.md § 5.3"})
    mesh_order: int | None = Field(description="the geometry order of the mesh the component's script writes, as its "
                                               "contract declares it; none where it writes none")
    outputs: list[str] | None = Field(description="the artifact types of the outputs a stage running the "
                                                  "component's script gives, those a later stage asks for among them")
    recipe: CaseRecipe | None = Field(description="the case's `mesh`, the recipe resolved, for a stage a mesher fills",
                                      json_schema_extra={"doc": "models.md § 5.3"})
    mesher: str | None = Field(description="the mesher that fills it")
    programs: dict[str, str] = Field(description="the SHA-256 of each program its folder runs, by its name there")
    target: str | record.Unknown = Field(description="the machine it is made for, by its record's identity of the "
                                                      "host — never the record's name",
                                          json_schema_extra={"doc": "workflow.md § 4"})
    fingerprint: str = Field(description="the install fingerprint of the environment it runs in, as that record "
                                         "lists it")


def fingerprint(ctx: Context, t: prepare.Target, environment: str) -> str:
    """The install fingerprint of ``environment`` as the target's record lists it, read through the
    record's one reader of its environments (`record.listed`); refused, `no-fingerprint`, where it
    lists none (workflow.md §§ 4, 7): its next steps, on that machine, `env install` of it where
    the record lists it not installed — not among the environments it lists, or in the state of
    one not installed — then what writes the record again; that alone where the record could not
    list its environments."""
    held = record.listed(ctx, t.record, environment)
    if held.snapshot is not None and held.snapshot.install_fingerprint is not None:
        return held.snapshot.install_fingerprint
    absent = env_state.machine(ctx).states.absent
    install = env_state.steps(ctx, environment, absent, t.machine) \
        if held.known and (held.snapshot is None or held.state is absent) else ()
    why = (f"could not list its environments ({held.why})" if not held.known
           else "does not list it" if held.snapshot is None
           else f"lists it {held.snapshot.state}, with no install fingerprint")
    written = prepare.record_steps(ctx, t.name) if t.here else (prepare.probe(ctx, t.name),)
    raise Unstated(f"the record {t.name} {why}, and a stage made in {environment} is named by it",
                   (*install, *written), code=NO_FINGERPRINT, subject=environment)


def programs(ctx: Context, named: list[str]) -> dict[str, str]:
    """The SHA-256 of each program a stage's folder runs, by its name there: each of femkit's
    programs ``named``, and the modules they run with, as the jobs domain finds and declares them
    (jobs.md § 1.1) — never the monitor that watches the run (workflow.md § 4)."""
    run = {*named, *layout.read_once(ctx).modules()}
    return {name: persist.sha256(source) for name, source in prepare.sources(ctx, named).items() if name in run}


def made(ctx: Context, kind: str, run: list[str], t: prepare.Target, environment: str,
         takes_from: dict[str, Took] | None = None, *, component: Drawing | None = None,
         mesh_order: int | None = None, outputs: list[str] | None = None, recipe: CaseRecipe | None = None,
         mesher: str | None = None) -> MadeFrom:
    """What a stage of ``kind`` is made from (workflow.md § 4): each stage it takes an input from,
    ``takes_from``; what its kind lists; the SHA-256 of each program its folder runs, ``run``
    naming femkit's own; the target's machine, by its record's identity of the host; and the
    install fingerprint of its ``environment``, the one it runs in, as the target's record lists
    it."""
    return MadeFrom(schema=SHAPE, kind=kind, takes_from=takes_from or {}, component=component,
                    mesh_order=mesh_order, outputs=sorted(outputs) if outputs is not None else None, recipe=recipe,
                    mesher=mesher, programs=programs(ctx, run), target=t.record.identity,
                    fingerprint=fingerprint(ctx, t, environment))


def _held(made_from: MadeFrom) -> dict[str, Any]:
    return made_from.model_dump(mode="json", by_alias=True)


def identity(made_from: MadeFrom) -> str:
    """A stage's ID: the SHA-256 of the canonical JSON of what it is made from (core.md § 4)."""
    return persist.canonical_sha256(_held(made_from))


def named(ctx: Context) -> str:
    """The name of the file a stage's folder keeps what it is made from in, `stage.json`, as the
    workflow declares it (`stages.toml`; workflow.md § 4)."""
    return catalogue.stages(ctx).made_from


def kept(ctx: Context, made_from: MadeFrom) -> dict[str, bytes]:
    """`stage.json`, as its folder keeps it — a maker's file to the jobs domain's one writer (jobs.md
    § 1.1) — its text the JSON whose canonical form names the stage."""
    return {named(ctx): persist.json_text(_held(made_from)).encode("utf-8")}


def file(ctx: Context, folder) -> Path:
    """Where the stage in ``folder`` keeps what it is made from, `stage.json`, as the jobs domain finds
    a maker's file (jobs.md § 1.1)."""
    return folders.maker_file(folder, named(ctx))


def read(ctx: Context, folder) -> persist.Read:
    """What the stage in ``folder`` is made from, as its `stage.json` says — whichever machine made it
    (workflow.md § 4): there or not, and, where it does not read in the shape femkit writes, why — a
    file stating another shape does not load (models.md § 2)."""
    return folders.read_made(folder, named(ctx), MadeFrom)
