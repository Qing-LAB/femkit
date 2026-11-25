"""Load every shipped definition (definitions.md § 2.2).

Loading reads only definition files: it probes nothing and starts nothing.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

from femkit.core import persist, view
from femkit.core.dirs import CONTROL, folder_from
from femkit.core.locks import SUBJECT
from femkit.core.operations import Context
from femkit.core import states
from femkit.core.schema import DefinitionError, key_path, load_toml, validate
from femkit.core.states import StateTable
from femkit.core.units import UnitTable, Units
from femkit.definitions.dispersion import Dispersion
from femkit.definitions.formulations import FormulationDefinition, StepKind, StepKindList
from femkit.definitions.importers import Importer, TableRecord, property_of
from femkit.definitions.meshers import MesherDefinition
from femkit.definitions.places import PlaceKind, PlaceList
from femkit.definitions.properties import Property, PropertyList
from femkit.schedulers import readers as scheduler_readers
from femkit.definitions.models import ControlDefinition, EnvironmentDefinition, ManagerKind, SchedulerKind
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
              f":{path}", reason) for e in errors for path, reason in e.problems],
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
    return hashlib.sha256(b"".join(shipped(file, persist.read_bytes) for file in control_files())).hexdigest()


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


def load_environments() -> dict[str, EnvironmentDefinition]:
    """Every environment: one per definition, built without CUDA, and a second, `<name>-cuda`,
    for a definition with a [cuda] part (definitions.md § 4.5)."""
    directory = data_root() / "environments"
    found = _load_dir(directory, EnvironmentDefinition)
    taken = {name: f"{CONTROL!r} names the control environment (control.txt)" for name in found if name == CONTROL}
    taken |= {name: f"{name!r} is no environment name: a letter or digit, then letters, digits, '.', '_' or '-' — "
                    "it names the environment's lock and folders" for name in found if not SUBJECT.fullmatch(name)}
    taken |= {name: f"a name ending in {CUDA_SUFFIX!r} is a definition's CUDA environment"
              for name in found if name.endswith(CUDA_SUFFIX)}
    if taken:
        raise CatalogueError([DefinitionError(directory / f"{name}.toml", [("", why)]) for name, why in taken.items()])
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
    """Every environment, loaded once per invocation."""
    return ctx.cached("environments", load_environments)


def load(ctx: Context) -> Catalogue:
    """The shipped catalogue, loaded once per invocation (api.md § 2.4)."""
    return ctx.cached("catalogue", load_catalogue)


def schedulers(ctx: Context) -> dict[str, SchedulerKind]:
    """The scheduler kinds, loaded once per invocation; they need no engine registry."""
    return ctx.cached("schedulers", load_schedulers)


def load_meshers() -> dict[str, MesherDefinition]:
    """Every mesher; each names an engine environment that provides it (models.md § 6.5)."""
    try:
        environments = set(load_environments())
    except CatalogueError:                          # said once, by the environments' own loading; each file's
        directory = data_root() / "environments"    # name stands for its environments meanwhile
        environments = {n for p in directory.glob("*.toml") for n in (p.stem, p.stem + CUDA_SUFFIX)}
    return _load_dir(data_root() / "meshers", MesherDefinition, {"environments": environments})


def meshers(ctx: Context) -> dict[str, MesherDefinition]:
    """The meshers, loaded once per invocation."""
    return ctx.cached("meshers", load_meshers)


def formulations(ctx: Context) -> dict[str, FormulationDefinition]:
    """The formulations, loaded once per invocation; they need no engine registry."""
    return ctx.cached("formulations", load_formulations)


def units(ctx: Context) -> Units:
    """The unit table, read once per invocation (core.md § 11); it needs no engine registry."""
    return ctx.cached("units", lambda: Units(load_units()))


def load_places() -> dict[str, PlaceKind]:
    """The kinds of place a group may be (geometry.md § 7)."""
    return dict(load_toml(data_root() / "geometry" / "kinds.toml", PlaceList).root)


def places(ctx: Context) -> dict[str, PlaceKind]:
    """The kinds of place, loaded once per invocation."""
    return ctx.cached("places", load_places)


def load_properties() -> dict[str, Property]:
    """The property list, each unit read by the unit table and each variable it depends on one of
    dispersion.toml's (materials.md §§ 1, 2)."""
    return dict(load_toml(data_root() / "properties.toml", PropertyList,
                          {"units": Units(load_units()), **_names("variables", lambda: load_dispersion().variables)}).root)


def properties(ctx: Context) -> dict[str, Property]:
    """The property list, loaded once per invocation."""
    return ctx.cached("properties", load_properties)


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
    return ctx.cached("dispersion", load_dispersion)


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
    return ctx.cached("importers", load_importers)


def load_step_kinds() -> dict[str, StepKind]:
    """The step kinds, each variable it supplies one of dispersion.toml's (models.md § 4.2)."""
    return dict(load_toml(data_root() / "step_kinds.toml", StepKindList,
                          _names("variables", lambda: load_dispersion().variables)).root)


def step_kinds(ctx: Context) -> dict[str, StepKind]:
    """The step kinds, loaded once per invocation."""
    return ctx.cached("step_kinds", load_step_kinds)


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
    return ctx.cached("templates", load_templates)


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
    schedulers: dict[str, SchedulerKind] = _type("schedulers/<kind>.toml", SchedulerKind, load_schedulers)
    units: UnitTable = _type("units.toml", UnitTable, load_units)
    formulations: dict[str, FormulationDefinition] = _type("formulations/<family>.toml", FormulationDefinition,
                                                           load_formulations)
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
    errors: list[DefinitionError] = []
    parts: dict = {}
    for kind in fields(Catalogue):
        try:
            parts[kind.name] = kind.metadata["load"]()
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
