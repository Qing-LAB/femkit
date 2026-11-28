"""Load every shipped definition (definitions.md § 2.2).

Loading reads only definition files: it probes nothing and starts nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

from femkit.core import persist, view
from femkit.core.dirs import CONTROL, checkout, folder_from
from femkit.core.locks import SUBJECT
from femkit.core.operations import Context
from femkit.core import states
from femkit.core.schema import DefinitionError, key_path, load_toml, parsed, render, validate
from femkit.core.states import StateTable
from femkit.core.units import UnitTable, Units
from femkit.engines import package_dir, registered
from femkit.definitions.dispersion import Dispersion
from femkit.definitions.formulations import FormulationDefinition, StepKind, StepKindList
from femkit.definitions.importers import Importer, TableRecord, property_of
from femkit.definitions.meshers import HandOver, MesherDefinition
from femkit.definitions.places import PlaceKind, PlaceList
from femkit.definitions.programs import Program, ProgramList
from femkit.definitions.properties import Property, PropertyList
from femkit.definitions.stages import PYTHON, RECORDS, Artifact, ArtifactList, StageKind, Stages, late_why, taken_late
from femkit.engines.stages import documents
from femkit.schedulers import readers as scheduler_readers
from femkit.definitions.models import (ControlDefinition, EnvironmentDefinition, ManagerKind, Naming, ProcessStart,
                                       SchedulerKind)
from femkit.definitions.requests import SCHEMA_CHECK


VARIABLE = "FEMKIT_DEFINITIONS_DIR"   # a test's own definitions, read in place of the shipped ones


def data_root() -> Path:
    """`femkit/data/`, the shipped definitions — or the folder FEMKIT_DEFINITIONS_DIR names, which
    only a test sets (testing.md § 2.1); read when asked, never at import."""
    own = os.environ.get(VARIABLE)
    if not own:
        return Path(__file__).resolve().parent.parent / "data"
    return folder_from(VARIABLE, own, "the definitions folder")   # read as the directories' variables are


class CatalogueError(DefinitionError):
    """Several shipped files that do not load: every file's problems (core.md § 9)."""

    def __init__(self, errors: list[DefinitionError]):
        self.errors = errors
        super().__init__(
            data_root(),
            [(f"{Path(e.file).relative_to(data_root()) if Path(e.file).is_relative_to(data_root()) else e.file}"
              f":{p.where}", p.reason) for e in errors for p in e.problems],
            (view.command(SCHEMA_CHECK),),
        )


def shipped(file: Path, read: Callable[[Path], Any] = persist.read_text) -> Any:
    """A shipped file's text — or, read with `persist.read_bytes`, its bytes; one that is not
    there, or does not read, is refused, naming it."""
    try:
        held = read(file)
    except OSError as exc:
        raise DefinitionError(file, [("", f"does not read: {exc.strerror}")]) from None
    if held is None:
        raise DefinitionError(file, [("", "is not there")])
    return held


def control_files() -> tuple[Path, Path]:
    """The control environment's two files: the channel order every environment is solved with,
    and the control environment's packages (definitions.md § 3)."""
    return data_root() / "channels.txt", data_root() / "control.txt"


def control_digest() -> str:
    """What the install script's stamp holds: the SHA-256 of both files, channels first (envs.md § 7.2)."""
    return persist.digest(b"".join(shipped(file, persist.read_bytes) for file in control_files()))


def load_control() -> ControlDefinition:
    """channels.txt is taken line by line as it stands, as the install script reads it; in
    control.txt, blank lines and `#` comments are skipped, as conda skips them."""
    channels_file, packages_file = control_files()
    channels = shipped(channels_file).splitlines()
    packages = [line.strip() for line in shipped(packages_file).splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    try:
        return validate(ControlDefinition, {"channels": channels, "dependencies": packages}, packages_file.parent)
    except DefinitionError as exc:                         # each problem named by the file it is in
        files = {"channels": channels_file, "dependencies": packages_file}
        found: dict[Path, list[tuple[str, str]]] = {}
        for where, why in exc.problems:
            found.setdefault(files.get(where.split(".")[0].split("[")[0], packages_file.parent), []).append((where, why))
        errors = [DefinitionError(file, problems) for file, problems in found.items()]
        raise (errors[0] if len(errors) == 1 else CatalogueError(errors)) from None


def load_managers() -> dict[str, ManagerKind]:
    return _load_dir(data_root() / "managers", ManagerKind)


def load_process() -> ProcessStart:
    """How every process femkit starts for an environment begins (envs.md § 4.4)."""
    return load_toml(data_root() / "process.toml", ProcessStart)


def process(ctx: Context) -> ProcessStart:
    """The clean start, loaded once per invocation."""
    return _cached(ctx, "process")


def load_naming() -> Naming:
    """Every environment's name with the package manager (envs.md § 1)."""
    return load_toml(data_root() / "naming.toml", Naming)


def naming(ctx: Context) -> Naming:
    """The naming rule, loaded once per invocation."""
    return _cached(ctx, "naming")


def managed_by(rule: Naming, name: str) -> str:
    """The name the package manager knows the environment ``name`` by, under ``rule``: the control
    environment's, `femkit`, or every other's, `femkit-<name>` (envs.md § 1)."""
    return rule.control if name == CONTROL else render(rule.other, {"name": name})


def managed(ctx: Context, name: str) -> str:
    """The name the package manager knows the environment ``name`` by (envs.md § 1) — the one rule,
    `naming.toml`'s, which every command that creates, asks for or enters an environment reads."""
    return managed_by(naming(ctx), name)


def load_schedulers() -> dict[str, SchedulerKind]:
    """Every scheduler kind, each with commands or probe roles checked against its reader in
    `femkit/schedulers/` (jobs.md § 7): a kind without one, or naming roles it does not read, is refused."""
    directory = data_root() / "schedulers"
    kinds, errors = _load_dir(directory, SchedulerKind), []
    for name, kind in kinds.items():
        module = scheduler_readers(name)
        if module is None and (kind.commands or kind.probe):
            errors.append(DefinitionError(directory / f"{name}.toml", [("", f"no reader in femkit/schedulers/ "
                                                                            f"reads the {name} kind's commands")]))
        elif module is not None and set(kind.probe) != set(module.PROBES):
            errors.append(DefinitionError(directory / f"{name}.toml", [("probe", f"its reader reads the roles "
                                                                                 f"{', '.join(module.PROBES)}")]))
    if errors:
        raise CatalogueError(errors)
    return kinds


def load_units() -> UnitTable:
    return load_toml(data_root() / "units.toml", UnitTable)


def load_formulations() -> dict[str, FormulationDefinition]:
    """Every formulation, its units read by the unit table, its places by the vocabulary of places,
    its step kinds by their list, its properties by the property list and its benchmarks'
    projects among the project templates (models.md § 4; materials.md § 1)."""
    return _load_dir(data_root() / "formulations", FormulationDefinition,
                     {"units": Units(load_units()), "places": frozenset(load_places()), "templates": load_templates(),
                      **_names("kinds", load_step_kinds), **_names("properties", load_properties)})


def _names(key: str, load: Callable[[], Any]) -> dict[str, frozenset[str]]:
    """``{key: the names ``load`` declares}``, what another file's validation context checks its
    references by; nothing while that file does not load — its own loading says why, once."""
    return {k: frozenset(loaded) for k, loaded in _loaded(key, load).items()}


def _loaded(key: str, load: Callable[[], Any]) -> dict[str, Any]:
    """``{key: what ``load`` loads}``, what another file's validation context checks it by; nothing
    while that file does not load — its own loading says why, once."""
    try:
        return {key: load()}
    except DefinitionError:
        return {}


CUDA_SUFFIX = "-cuda"  # a definition's CUDA environment is named after it with this (definitions.md § 4.5)


def environment_context() -> dict:
    """What an environment definition's validators are given beside its file (core.md § 2): the
    registered engines, each with the reader IDs it registers."""
    return {"engines": registered()}


def load_environments() -> dict[str, EnvironmentDefinition]:
    """Every environment: one per definition, built without CUDA, and a second, `<name>-cuda`,
    for a definition with a [cuda] part (definitions.md § 4.5)."""
    directory = data_root() / "environments"
    found = _load_dir(directory, EnvironmentDefinition, environment_context())
    taken = {name: f"{CONTROL!r} names the control environment (control.txt)" for name in found if name == CONTROL}
    taken |= {name: f"{name!r} is no environment name: a letter or digit, then letters, digits, '.', '_' or '-' — "
                    "it names the environment's lock and folders" for name in found if not SUBJECT.fullmatch(name)}
    taken |= {name: f"a name ending in {CUDA_SUFFIX!r} is a definition's CUDA environment"
              for name in found if name.endswith(CUDA_SUFFIX)}
    engines: dict[str, list[str]] = {}
    for name, definition in found.items():                 # one refused for its name declares nothing
        if definition.engine is not None and name not in taken:
            engines.setdefault(definition.engine, []).append(name)
    clash = {name: ("engine", f"{' and '.join(names)} both declare the engine {engine}: an engine names one "
                              "environment") for engine, names in engines.items() if len(names) > 1 for name in names}
    projects = [name for name, d in found.items() if d.projects and name not in taken]
    clash |= {name: ("projects", f"{' and '.join(projects)} both take the packages projects declare: a project's "
                                 "scripts run in one environment") for name in projects if len(projects) > 1}
    if taken or clash:
        raise CatalogueError([DefinitionError(directory / f"{name}.toml", [("", why)]) for name, why in taken.items()]
                             + [DefinitionError(directory / f"{name}.toml", [held])
                                for name, held in clash.items() if name not in taken])
    out = {}
    control = load_control().dependencies if any(d.control_packages for d in found.values()) else []
    for name, definition in found.items():
        out[name] = definition.built(cuda=False)
        if definition.control_packages:  # femkit's own libraries, by reference (definitions.md § 4.7)
            built = out[name]
            out[name] = built.model_copy(update={"packages": built.packages.model_copy(
                update={"conda": [*control, *built.packages.conda]})})
        if definition.cuda is not None:
            out[name + CUDA_SUFFIX] = definition.built(cuda=True)
    return dict(sorted(out.items()))


def environments(ctx: Context) -> dict[str, EnvironmentDefinition]:
    """Every environment, loaded once per invocation: what observing one needs, and nothing
    else's loading — a formulation that does not load leaves the environments' commands
    working."""
    return _cached(ctx, "environments")


def _engines(envs: dict[str, EnvironmentDefinition]) -> dict[str, str]:
    """Each engine ``envs`` declare, by its name, with the environment whose definition declares it."""
    return dict(sorted((env.engine, name) for name, env in envs.items()
                       if env.engine is not None and not name.endswith(CUDA_SUFFIX)))


def load_engines() -> dict[str, str]:
    """Each engine `study prep --engine` may name, with the environment it resolves to (`engines`),
    read from the environments' files: what names the engines in a help (api.md § 6)."""
    return _engines(load_environments())


def engines(ctx: Context) -> dict[str, str]:
    """Each engine `study prep --engine` may name, with the environment it resolves to: the engine
    environment whose definition declares it — one alone, two declaring one refused when they load
    (definitions.md § 2.2; framework.md § 5)."""
    return _engines(environments(ctx))


def with_gpus(ctx: Context, name: str, gpus: int) -> str | None:
    """The environment ``name`` runs as where ``gpus`` are asked (definitions.md § 4.5): itself
    with none; with any, its CUDA environment, `<name>-cuda` — None where its definition has no
    CUDA part. The one home of the twin by GPUs: a job's (jobs.md § 3, step 4), the one a GPU
    validate names (envs.md § 5)."""
    if gpus <= 0:
        return name
    twin = name + CUDA_SUFFIX
    return twin if twin in environments(ctx) else None


def control(ctx: Context) -> ControlDefinition:
    """The channel order and the control environment's packages, loaded once per invocation."""
    return _cached(ctx, "control")


def managers(ctx: Context) -> dict[str, ManagerKind]:
    """The manager kinds, loaded once per invocation."""
    return _cached(ctx, "managers")


def load(ctx: Context) -> Catalogue:
    """The shipped catalogue, every type loaded once per invocation (api.md § 2.4) — each by the
    one cached loader its own reader shares — or every problem with every file."""
    return ctx.cached("catalogue", lambda: _whole(lambda kind: _cached(ctx, kind)))


def _cached(ctx: Context, kind: str) -> Any:
    """One type of shipped definition, by its field of `Catalogue`, loaded once per invocation."""
    return ctx.cached(f"definitions/{kind}", _loader(kind))


def _loader(kind: str) -> Callable[[], Any]:
    """The loader of one type of shipped definition, by its field of `Catalogue`."""
    return next(f.metadata["load"] for f in fields(Catalogue) if f.name == kind)


def schedulers(ctx: Context) -> dict[str, SchedulerKind]:
    """The scheduler kinds, loaded once per invocation; they need no engine registry."""
    return _cached(ctx, "schedulers")


def _environment_names() -> set[str]:
    """Every environment's name, what a definition naming one is checked by: each file's, and its
    CUDA twin's, while the environments do not load — their own loading says why, once."""
    try:
        return set(load_environments())
    except CatalogueError:
        directory = data_root() / "environments"
        return {n for p in directory.glob("*.toml") for n in (p.stem, p.stem + CUDA_SUFFIX)}


def _of_the_checkout(module: str) -> bool:
    """Whether ``module`` is one of femkit's checkout: a package's folder, or a file of one."""
    where = checkout().joinpath(*module.split("."))
    return (where / "__init__.py").is_file() or where.with_suffix(".py").is_file()


def load_programs() -> dict[str, Program]:
    """Every femkit program that runs inside an environment (envs.md § 4.4): each in an environment
    that exists, its module one of the checkout."""
    return dict(load_toml(data_root() / "programs.toml", ProgramList,
                          {"environments": _environment_names(), "modules": _of_the_checkout}).root)


def programs(ctx: Context) -> dict[str, Program]:
    """The programs that run inside an environment, loaded once per invocation."""
    return _cached(ctx, "programs")


def stage_programs() -> frozenset[str]:
    """femkit's stage programs, by their files' names (framework.md § 1): the programs of
    `femkit/engines/stages/`, the documents they share beside them aside."""
    shared = Path(documents.__file__)
    return frozenset(p.name for p in shared.parent.glob("*.py") if p != shared)


def load_artifacts() -> dict[str, Artifact]:
    """The artifact types (workflow.md § 2.2), each opened in an environment that exists."""
    return dict(load_toml(data_root() / "artifacts.toml", ArtifactList, {"environments": _environment_names()}).root)


def artifacts(ctx: Context) -> dict[str, Artifact]:
    """The artifact types, loaded once per invocation."""
    return _cached(ctx, "artifacts")


def load_stages(parts: dict[str, list[str]] | None = None) -> Stages:
    """The stage kinds (workflow.md § 2.1), and the name of a study's meshing sequence (§ 7): each
    environment, artifact type, document and check program the kinds name is one that exists; and,
    given ``parts`` — the project layout's part kinds, each with the files every part of it holds by
    a fixed name, as the layout's one reader reads it — each part a kind brings one the layout
    declares, its program a stage program of femkit's or a file every such part holds. The layout's
    model and reader are the projects domain's, above this one, so `schema check` gives them
    (definitions.md §§ 2.2, 2.3)."""
    return load_toml(data_root() / "stages.toml", Stages,
                     {"environments": _environment_names(), **_names("artifacts", load_artifacts),
                      "programs": stage_programs(), "documents": frozenset(documents.SHAPES),
                      **({"parts": parts} if parts is not None else {})})


def stages(ctx: Context) -> Stages:
    """The stage kinds and the meshing sequence's name, loaded once per invocation."""
    return _cached(ctx, "stages")


def load_handovers() -> dict[str, HandOver]:
    """Every hand-over (geometry.md § 8): each reads an artifact type that exists, hands an engine
    an adapter registers through a program of its package, and keeps places of the vocabulary;
    two that give one engine one type at one order are refused, each in its file."""
    directory = data_root() / "handovers"
    found = _load_dir(directory, HandOver, {**_names("artifacts", load_artifacts), **_names("places", load_places),
                                            "engine_packages": {e: package_dir(e) for e in registered()}})
    taken: dict[tuple[str, str, int], list[str]] = {}
    for name, h in found.items():
        for order in h.orders:
            taken.setdefault((h.engine, h.reads, order), []).append(name)
    clashes: dict[str, list[str]] = {}
    for (engine, typ, order), names in taken.items():
        for name in names if len(names) > 1 else ():
            clashes.setdefault(name, []).append(f"{' and '.join(names)} both give {engine} the type {typ} at order "
                                                f"{order}: the order a case asks for would not choose one")
    if clashes:
        raise CatalogueError([DefinitionError(directory / f"{n}.toml", [("orders", "; ".join(w))])
                              for n, w in sorted(clashes.items())])
    return found


def handovers(ctx: Context) -> dict[str, HandOver]:
    """The hand-overs, loaded once per invocation."""
    return _cached(ctx, "handovers")


def load_meshers() -> dict[str, MesherDefinition]:
    """Every mesher (workflow.md § 2.3): each names the environment that provides it, one of
    femkit's stage programs and artifact types that exist, hands its program only the documents
    the stage kind it fills is handed, and writes every file that kind's check names
    (definitions.md § 2.2)."""
    directory = data_root() / "meshers"
    held = _loaded("stages", load_stages).get("stages")
    kinds = held.kinds if held is not None else None
    filled = [k for k in kinds.values() if k.filled_by == "mesher"] if kinds is not None else []
    found = _load_dir(directory, MesherDefinition, {
        "environments": _environment_names(), **_names("artifacts", load_artifacts), "programs": stage_programs(),
        **({"documents": frozenset(d for k in filled for d in k.documents)} if kinds is not None else {})})
    wanted = {p.name for k in filled for a in k.check for p in parsed(a)} - {*RECORDS, PYTHON} \
        - {d for k in filled for d in k.documents}
    problems: dict[str, list[tuple[str, str]]] = {}
    for name, m in found.items():
        if wanted - set(m.writes):
            problems.setdefault(name, []).append(("writes", f"the mesh stage's check reads "
                                                  f"{', '.join('{%s}' % r for r in sorted(wanted - set(m.writes)))}: "
                                                  "every mesher writes it by that name"))
    errors = [DefinitionError(directory / f"{n}.toml", sorted(set(p))) for n, p in sorted(problems.items())]
    if kinds is not None:
        errors += _taken_late(kinds, found)
    if errors:
        raise CatalogueError(errors)
    return found


def _taken_late(kinds: dict[str, StageKind], meshers: dict[str, MesherDefinition]) -> list[DefinitionError]:
    """`stages.toml`'s kinds held to their order, the kind the meshers fill among them: each kind
    takes only from kinds before it (workflow.md § 7) — the kind a mesher fills taking what every
    mesher reads, and writing what every mesher writes. Its own kinds alone, `Stages` holds."""
    filled = {n for n, k in kinds.items() if k.filled_by == "mesher"}
    reads = {n: {*(k.inputs or {}).values()} | ({t for m in meshers.values() for t in m.reads.values()}
                                                  if n in filled else set()) for n, k in kinds.items()}
    writes = {n: k.writes() | ({t for m in meshers.values() for t in m.writes.values()} if n in filled else set())
              for n, k in kinds.items()}
    problems = [(f"kinds.{name}", late_why(later, types))
                for name, later, types in taken_late(list(kinds), reads, writes) if name in filled or later in filled]
    return [DefinitionError(data_root() / "stages.toml", problems)] if problems else []


def meshers(ctx: Context) -> dict[str, MesherDefinition]:
    """The meshers, loaded once per invocation."""
    return _cached(ctx, "meshers")


def formulations(ctx: Context) -> dict[str, FormulationDefinition]:
    """The formulations, loaded once per invocation; they need no engine registry."""
    return _cached(ctx, "formulations")


def units(ctx: Context) -> Units:
    """The unit table, read once per invocation (core.md § 11); it needs no engine registry."""
    return ctx.cached("units", lambda: Units(load_units()))


def load_places() -> dict[str, PlaceKind]:
    """The kinds of place a group may be (geometry.md § 7)."""
    return dict(load_toml(data_root() / "geometry" / "kinds.toml", PlaceList).root)


def places(ctx: Context) -> dict[str, PlaceKind]:
    """The kinds of place, loaded once per invocation."""
    return _cached(ctx, "places")


def load_properties() -> dict[str, Property]:
    """The property list, each unit read by the unit table and each variable it depends on one of
    dispersion.toml's (materials.md §§ 1, 2)."""
    return dict(load_toml(data_root() / "properties.toml", PropertyList,
                          {"units": Units(load_units()), **_names("variables", lambda: load_dispersion().variables)}).root)


def properties(ctx: Context) -> dict[str, Property]:
    """The property list, loaded once per invocation."""
    return _cached(ctx, "properties")


def load_dispersion() -> Dispersion:
    """The variables and the dispersion models, each unit read by the unit table and each model's
    property one of the property list's — the list read by its own rules alone, since its own
    variables are checked against this file (materials.md § 2)."""
    units = Units(load_units())
    listed = _names("properties", lambda: load_toml(data_root() / "properties.toml", PropertyList,
                                                    {"units": units}).root)
    return load_toml(data_root() / "dispersion.toml", Dispersion, {"units": units, **listed})


def dispersion(ctx: Context) -> Dispersion:
    """The variables and the dispersion models, loaded once per invocation."""
    return _cached(ctx, "dispersion")


def load_importers() -> dict[str, Importer]:
    """Every importer, by its source's ID — its file's stem (materials.md § 7): its units read by
    the unit table, its variables and models dispersion.toml's, and each table's property the one
    the property list's `names` gives the source's name for it — exactly one, which depends on the
    variable the source writes its data in."""
    directory = data_root() / "importers"
    units = Units(load_units())
    context = {"units": units, **_loaded("dispersion", load_dispersion)}
    found = _load_dir(directory, Importer, context)
    listed = _loaded("properties", load_properties).get("properties")
    errors = []
    for source, importer in found.items() if listed is not None else ():
        problems = []
        for kind, record in importer.records.items():
            if not isinstance(record, TableRecord):
                continue
            named = property_of(listed, source, record.property)
            if len(named) != 1:
                problems.append((key_path(("records", kind, "property")),
                                 f"the property list's names give {source}'s {record.property!r} "
                                 f"{'to ' + ', '.join(named) if named else 'to no property'}: one, exactly"))
            elif importer.variable.name not in listed[named[0]].depends_on:
                problems.append(("variable.name", f"the {named[0]} depends on no {importer.variable.name}"))
        if problems:
            errors.append(DefinitionError(directory / f"{source}.toml", problems))
    if errors:
        raise CatalogueError(errors)
    return found


def importers(ctx: Context) -> dict[str, Importer]:
    """The importers, loaded once per invocation."""
    return _cached(ctx, "importers")


def load_step_kinds() -> dict[str, StepKind]:
    """The step kinds, each variable it supplies one of dispersion.toml's (models.md § 4.2)."""
    return dict(load_toml(data_root() / "step_kinds.toml", StepKindList,
                          _names("variables", lambda: load_dispersion().variables)).root)


def step_kinds(ctx: Context) -> dict[str, StepKind]:
    """The step kinds, loaded once per invocation."""
    return _cached(ctx, "step_kinds")


def states_dir() -> Path:
    """`states/`: one table per state machine (core.md § 7)."""
    return data_root() / "states"


def state_file(machine: str) -> Path:
    """`states/<machine>.toml`: one machine's table."""
    return states_dir() / f"{machine}.toml"


def load_states(context: dict | None = None) -> dict[str, StateTable]:
    """Every machine's table, each closed and total by its own rules; ``context`` adds what is
    known beside it — the registered operations, for `schema check` (core.md § 7)."""
    return _load_dir(states_dir(), StateTable, context)


def machine(ctx: Context, binding: states.Binding) -> states.Machine:
    """The machine ``binding`` names, read from its table and bound to the predicates and values
    its domain gives, once per invocation (core.md § 7)."""
    return ctx.cached(f"states/{binding.machine}", lambda: states.load(state_file(binding.machine), binding))


def templates_dir() -> Path:
    """`templates/`: the settings file's template, and one folder per project template (projects.md § 7)."""
    return data_root() / "templates"


def load_templates() -> dict[str, Path]:
    """Each project template by its bare name — a folder of `templates/` — and its folder. Each is
    a project, read through the parts' own schemas; what makes one a project, and its name, are
    the projects domain's to check (projects.md § 7)."""
    return {p.name: p for p in sorted(templates_dir().iterdir()) if p.is_dir()}


def templates(ctx: Context) -> dict[str, Path]:
    """The project templates, listed once per invocation."""
    return _cached(ctx, "templates")


def _type(files: str, model: type | None, load: Callable[[], Any]) -> Any:
    return field(metadata={"files": files, "model": model, "load": load})


@dataclass(frozen=True)
class Catalogue:
    """Every shipped definition, one field per type, each with where its files are under
    `femkit/data/`, its model and its loader: the one list the catalogue, `schema check`,
    `schema docs` and the reference read (definitions.md § 1). A template has no model of its
    own: it is a project, read through the part schemas (projects.md § 7)."""

    control: ControlDefinition = _type("channels.txt, control.txt", ControlDefinition, load_control)
    environments: dict[str, EnvironmentDefinition] = _type("environments/<name>.toml", EnvironmentDefinition,
                                                           load_environments)
    managers: dict[str, ManagerKind] = _type("managers/<kind>.toml", ManagerKind, load_managers)
    process: ProcessStart = _type("process.toml", ProcessStart, load_process)
    naming: Naming = _type("naming.toml", Naming, load_naming)
    programs: dict[str, Program] = _type("programs.toml", Program, load_programs)
    schedulers: dict[str, SchedulerKind] = _type("schedulers/<kind>.toml", SchedulerKind, load_schedulers)
    units: UnitTable = _type("units.toml", UnitTable, load_units)
    formulations: dict[str, FormulationDefinition] = _type("formulations/<family>.toml", FormulationDefinition,
                                                           load_formulations)
    artifacts: dict[str, Artifact] = _type("artifacts.toml", Artifact, load_artifacts)
    stages: Stages = _type("stages.toml", Stages, load_stages)
    handovers: dict[str, HandOver] = _type("handovers/<name>.toml", HandOver, load_handovers)
    meshers: dict[str, MesherDefinition] = _type("meshers/<id>.toml", MesherDefinition, load_meshers)
    places: dict[str, PlaceKind] = _type("geometry/kinds.toml", PlaceKind, load_places)
    properties: dict[str, Property] = _type("properties.toml", Property, load_properties)
    dispersion: Dispersion = _type("dispersion.toml", Dispersion, load_dispersion)
    step_kinds: dict[str, StepKind] = _type("step_kinds.toml", StepKind, load_step_kinds)
    importers: dict[str, Importer] = _type("importers/<source>.toml", Importer, load_importers)
    states: dict[str, StateTable] = _type("states/<machine>.toml", StateTable, load_states)
    templates: dict[str, Path] = _type("templates/<name>/", None, load_templates)


def load_catalogue() -> Catalogue:
    """Every definition, or every problem with every file."""
    return _whole(lambda kind: _loader(kind)())


def _whole(load_kind: Callable[[str], Any]) -> Catalogue:
    """Every type of definition, each by ``load_kind`` given its field's name — or every problem
    with every file, together."""
    errors: list[DefinitionError] = []
    parts: dict = {}
    for kind in fields(Catalogue):
        try:
            parts[kind.name] = load_kind(kind.name)
        except CatalogueError as exc:
            errors.extend(exc.errors)
        except DefinitionError as exc:
            errors.append(exc)
    if errors:
        raise CatalogueError(errors)
    return Catalogue(**parts)


def _load_dir(directory: Path, model, context: dict | None = None) -> dict:
    out, errors = {}, []
    for path in sorted(directory.glob("*.toml")):
        try:
            out[path.stem] = load_toml(path, model, context)
        except DefinitionError as exc:
            errors.append(exc)
    if errors:
        raise CatalogueError(errors)
    return out
