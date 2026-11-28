"""Folder writing (workflow.md §§ 5, 7): a stage becomes a calculation folder by its kind's
templates and the context its kind lists — nothing else reaches it — its request and its files,
which `study prep` writes through the jobs domain's one writer of a calculation folder
(`jobs.folders.write`, jobs.md § 1.1) at the path the door forms (`door.stage_folder`, projects.md
§ 6); and a study's stages become its meshing job's batches and sequence — the stages it places in
the batch its kind names, the batches in the kinds' order, each launch folder named by its batch or
the sequence, the study and the first number none of the job's folders takes (`placed`, `job`).

Its request: the command and the check rendered from the kind's — or its mesher's — templates
with the core's one grammar (`render_arguments`, core.md § 2.1), `{python}` left the run's own
(jobs.md § 2); the programs they name that are femkit's; `one_process` as the kind says; the
documents it is handed and the files of the part its kind brings — the component's — as its
inputs; the outputs it gives, those given only when asked among them where asked; a share for
each input, read where the stage before it made it; and the resources of the job it lies in — the
study's meshing job, as the study states it (§ 5): that job's queue, wall and memory, one rank, its
cores as threads, no GPU. Beside the request, the documents and `stage.json`, what it is made from
(§ 4).

Each document a stage is handed is built from the listed context alone, by its kind
(`femkit/engines/stages/documents.py`), the case read by its model's fields (`cases.Case`,
models.md § 5.3): `inputs`, the case's values of the definitions the contract
declares, a length in the frame's unit, an angle in degrees, a number as itself (geometry.md § 2);
`contract`, the component's frame, promised groups and declared mesh, and, by its role, whether
each output the stage gives only when a later stage asks is asked — the shapes as BREP; `recipe`,
the case's recipe resolved, each length in the frame's unit (geometry.md §§ 5, 6). Each document is
handed as the file its stage kind names it (`stages.toml`), the records its check writes as the
jobs domain names the files holding those documents (`layout.Catalogue.documents`), and what the
stage is made from is kept as `identity.kept` writes it. A path from one folder to another is the
jobs domain's (`folders.from_here`). The solve stage's folder joins with each engine's input
writer (plan § 4, M6).
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Callable

from femkit.core import persist
from femkit.core.operations import Context
from femkit.core.schema import LENGTH, render_arguments
from femkit.core.units import Units
from femkit.definitions import catalogue
from femkit.engines.stages import documents
from femkit.geometry.component import Outputs
from femkit.jobs import folders, layout, runs
from femkit.jobs.request import PYTHON, SHARE, JobRequest, Resources
from femkit.models import cases
from femkit.projects import door, names
from femkit.projects.door import Opened
from femkit.workflow import identity
from femkit.workflow.graph import Definitions, Made


def resources(job: Resources) -> Resources:
    """A stage inside a job (workflow.md § 5): the job's queue, wall and memory, one rank, the job's
    cores — its ranks × threads — as its threads, and no GPU."""
    return Resources(ranks=1, threads=job.cores, gpus=0, **job.shared())


def restated(ctx: Context, s: Made, job: Resources) -> JobRequest | None:
    """The request of the stage ``s``, whose folder is there, stated again with what a stage inside
    a job holding ``job`` holds (`resources`), where its folder's request states other resources —
    the one decision of whether a stage prep places is restated (workflow.md § 5); None where it
    states those already."""
    within = resources(job)
    return folders.restated(ctx, s.folder, within) if runs.request_of(ctx, s.folder).resources != within else None


def _number(held: cases.Exact | None) -> float | None:
    """A plain number as a case holds it, a quantity of no dimension, as the nearest double; none
    for none."""
    return float(cases.quantity(held).value) if held is not None else None


def _length(held: cases.Exact, unit: str, units: Units) -> float:
    """A length as a case holds it, in ``unit``, the nearest double (geometry.md § 2)."""
    return float(units.convert(cases.quantity(held), unit))


def _frame(s: Made) -> tuple[int, str, dict[str, int]]:
    """The case's frame — its dimension and unit — and its promised groups, each with its dimension."""
    component = s.case.component
    return (int(Fraction(component.frame.dimension)), component.frame.unit,
            {g: int(Fraction(d)) for g, d in component.groups.items()})


def _inputs(s: Made, units: Units) -> dict:
    dimension, unit, _ = _frame(s)
    values = {}
    for name, held in s.case.component.inputs.items():
        q = cases.quantity(held)
        values[name] = _length(held, unit, units) if q.dimension == LENGTH else float(q.value)
    return documents.make("inputs", definitions=values)


def _contract(s: Made, units: Units) -> dict:
    """The component's frame and promised groups, the order of the mesh its script writes, and,
    for each output the stage gives only when a stage after it asks — not one the component's
    contract declares — whether it is asked, by its role (geometry.md § 3; workflow.md § 2.1)."""
    dimension, _, groups = _frame(s)
    symmetry = s.case.component.frame.symmetry
    asked = {role: given for role, given in s.asked.items() if role not in Outputs.model_fields}
    return documents.make("contract", dimension=dimension, axis=symmetry.axis if symmetry is not None else None,
                          groups=groups, mesh=s.made.mesh_order, **asked)


def _recipe(s: Made, units: Units) -> dict:
    dimension, unit, groups = _frame(s)
    recipe = s.case.mesh
    return documents.make("recipe", dimension=dimension, groups=groups, size=_length(recipe.size, unit, units),
                          order=int(Fraction(recipe.order)), tolerance=_number(recipe.tolerance),
                          growth=_number(recipe.growth), quality=_number(recipe.quality),
                          sizes={g: _length(v, unit, units) for g, v in recipe.sizes.items()})


#: Each document a stage may be handed, by its kind (`documents.SHAPES`): what builds it.
BUILDERS: dict[str, Callable[[Made, Units], dict]] = {"inputs": _inputs, "contract": _contract, "recipe": _recipe}


def folder_of(ctx: Context, s: Made, job: Resources) -> tuple[JobRequest, dict[str, bytes]]:
    """The calculation folder of the stage ``s`` inside a job holding ``job`` (workflow.md § 5): its
    request, and every file beside it, by its name there."""
    kind, artifacts, units = s.filled, catalogue.artifacts(ctx), catalogue.units(ctx)
    recorded = layout.read_once(ctx).documents()        # each record its check writes, by the document it holds
    docs, made = dict(kind.documents), identity.kept(ctx, s.made)
    values: dict[str, str | None] = {PYTHON: "{" + PYTHON + "}", **docs, **recorded}
    values |= {role: artifacts[ty].file for role, ty in s.gives.items()}
    values |= {role: None for role, given in s.asked.items() if not given}
    values |= {role: "{" + f"{SHARE}:{artifacts[ty].file}" + "}" for role, (ty, _, _) in s.takes_from.items()}
    files = {name: persist.json_text(BUILDERS[d](s, units)).encode("utf-8") for d, name in docs.items()}
    files |= s.brings
    request = JobRequest(
        name=f"{s.kind}-{cases.short(s.id)}", environment=kind.environment,
        command=render_arguments(kind.program, values),
        inputs=sorted(files), resources=resources(job), programs=kind.femkits(catalogue.stage_programs()),
        one_process=kind.one_process, outputs=[artifacts[ty].file for ty in s.gives.values()],
        check=render_arguments(kind.check, values),
        shares=[{"folder": folders.from_here(s.folder, source.folder), "file": artifacts[ty].file}
                for ty, source, _ in s.takes_from.values()])
    return request, {**files, **made}


# ------------------------------------------------------------------ a study's stages into its jobs

def placed(d: Definitions, stages: list[Made]) -> dict[str, list[Made]]:
    """The batches of a study's meshing job that the stages `study prep` places go in (workflow.md
    §§ 5, 7), the one rule: each in the batch its kind names, the batches in the kinds' order, so a
    stage comes after every stage it takes from; a batch with none left out."""
    batches = {kind.batch: [s for s in stages if s.kind == name] for name, kind in d.stages.items()}
    return {batch: members for batch, members in batches.items() if members}


def launch_folder(opened: Opened, study: str, name: str, number: int) -> Path:
    """A launch folder of the study, as the door forms it, named `<name>-<study>-NNN` by the last
    step of the study's name, a launch folder's name one step (projects.md § 5): a batch by its
    kind's batch, the sequence by `stages.toml`'s (workflow.md § 7)."""
    return door.launch_folder(opened, study, f"{name}-{names.last(study)}-{number:03d}")


def job(opened: Opened, study: str, batches: dict[str, list[Made]], resources: Resources,
        sequence: str) -> tuple[Path, dict[Path, JobRequest]]:
    """The study's meshing job (workflow.md §§ 5, 7, the jobs step): a batch of each kind's stages it
    places, named by the kind's batch, and ``sequence``, the sequence of those batches — each launch
    folder numbered by the first number none of them takes yet, its request stating the job's
    ``resources``, its members or parts by their paths from it; the sequence's folder, and each
    launch folder's request, the batches' first."""
    number = 1
    while any(launch_folder(opened, study, n, number).exists() for n in [*batches, sequence]):
        number += 1
    launches: dict[Path, JobRequest] = {}
    for name, members in batches.items():
        folder = launch_folder(opened, study, name, number)
        launches[folder] = JobRequest(name=folder.name, resources=resources,
                                      members=[folders.from_here(folder, s.folder) for s in members])
    whole = launch_folder(opened, study, sequence, number)
    launches[whole] = JobRequest(name=whole.name, resources=resources,
                                 sequence=[folders.from_here(whole, f) for f in launches])
    return whole, launches
