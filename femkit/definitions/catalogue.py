"""Load every shipped definition (definitions.md § 2.2).

Loading reads only definition files: it probes nothing and starts nothing.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

from femkit.core import view
from femkit.core.dirs import CONTROL
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, load_toml, validate
from femkit.core.units import UnitTable, Units
from femkit.definitions.formulations import FormulationDefinition
from femkit.definitions.meshers import MesherDefinition
from femkit.schedulers import readers as scheduler_readers
from femkit.definitions.models import ControlDefinition, EnvironmentDefinition, ManagerKind, SchedulerKind
from femkit.definitions.requests import SCHEMA_CHECK


VARIABLE = "FEMKIT_DEFINITIONS_DIR"   # a test's own definitions, read in place of the shipped ones


def data_root() -> Path:
    """`femkit/data/`, the shipped definitions — or the folder FEMKIT_DEFINITIONS_DIR names, which
    only a test sets (testing.md § 2.1); read when asked, never at import."""
    own = os.environ.get(VARIABLE)
    return Path(own) if own else Path(__file__).resolve().parent.parent / "data"


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


def control_files() -> tuple[Path, Path]:
    """The control environment's two files: the channel order every environment is solved with,
    and the control environment's packages (definitions.md § 3)."""
    return data_root() / "channels.txt", data_root() / "control.txt"


def control_digest() -> str:
    """What the install script's stamp holds: the SHA-256 of both files, channels first (envs.md § 7.2)."""
    digest = hashlib.sha256()
    for path in control_files():
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_control() -> ControlDefinition:
    """channels.txt is taken line by line as it stands, as the install script reads it; in
    control.txt, blank lines and `#` comments are skipped, as conda skips them."""
    channels_file, packages_file = control_files()
    try:
        channels = channels_file.read_text(encoding="utf-8").splitlines()
        packages = [line.strip() for line in packages_file.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    except OSError as exc:
        raise DefinitionError(exc.filename or packages_file, [("", f"does not read: {exc.strerror}")]) from None
    return validate(ControlDefinition, {"channels": channels, "dependencies": packages}, packages_file.parent)


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
    """Every formulation, its units read by the unit table (models.md § 4)."""
    return _load_dir(data_root() / "formulations", FormulationDefinition,
                     {"units": Units(load_units()), "root": data_root() / "formulations"})


CUDA_SUFFIX = "-cuda"  # a definition's CUDA environment is named after it with this (definitions.md § 4.5)


def load_environments() -> dict[str, EnvironmentDefinition]:
    """Every environment: one per definition, built without CUDA, and a second, `<name>-cuda`,
    for a definition with a [cuda] part (definitions.md § 4.5)."""
    directory = data_root() / "environments"
    found = _load_dir(directory, EnvironmentDefinition)
    taken = {name: f"{CONTROL!r} names the control environment (control.txt)" for name in found if name == CONTROL}
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


def load(ctx: Context) -> Catalogue:
    """The shipped catalogue, loaded once per invocation (api.md § 2.4)."""
    return ctx.cached("catalogue", load_catalogue)


def schedulers(ctx: Context) -> dict[str, SchedulerKind]:
    """The scheduler kinds, loaded once per invocation; they need no engine registry."""
    return ctx.cached("schedulers", load_schedulers)


def load_meshers() -> dict[str, MesherDefinition]:
    """Every mesher; each names an engine environment that provides it (models.md § 6.5)."""
    environments = {p.stem for p in (data_root() / "environments").glob("*.toml")}
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


def _type(files: str, model: type, load: Callable[[], Any]) -> Any:
    return field(metadata={"files": files, "model": model, "load": load})


@dataclass(frozen=True)
class Catalogue:
    """Every shipped definition, one field per type, each with where its files are under
    `femkit/data/`, its model and its loader: the one list the catalogue, `schema check`,
    `schema docs` and the reference read (definitions.md § 1)."""

    control: ControlDefinition = _type("channels.txt, control.txt", ControlDefinition, load_control)
    environments: dict[str, EnvironmentDefinition] = _type("environments/<name>.toml", EnvironmentDefinition,
                                                           load_environments)
    managers: dict[str, ManagerKind] = _type("managers/<kind>.toml", ManagerKind, load_managers)
    schedulers: dict[str, SchedulerKind] = _type("schedulers/<kind>.toml", SchedulerKind, load_schedulers)
    units: UnitTable = _type("units.toml", UnitTable, load_units)
    formulations: dict[str, FormulationDefinition] = _type("formulations/<family>.toml", FormulationDefinition,
                                                           load_formulations)
    meshers: dict[str, MesherDefinition] = _type("meshers/<id>.toml", MesherDefinition, load_meshers)


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
