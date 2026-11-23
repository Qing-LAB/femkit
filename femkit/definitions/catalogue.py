"""Load every shipped definition (definitions.md § 2.2).

Loading reads only definition files: it probes nothing and starts nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from femkit.core.dirs import CONTROL
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, load_toml, validate
from femkit.core.units import UnitTable, Units
from femkit.definitions.formulations import FormulationDefinition
from femkit.definitions.meshers import MesherDefinition
from femkit.definitions.models import ControlDefinition, EnvironmentDefinition, ManagerKind, SchedulerKind


def data_root() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Catalogue:
    control: ControlDefinition
    environments: dict[str, EnvironmentDefinition]
    managers: dict[str, ManagerKind]
    schedulers: dict[str, SchedulerKind]
    units: UnitTable
    formulations: dict[str, FormulationDefinition]
    meshers: dict[str, MesherDefinition]


class CatalogueError(DefinitionError):
    """Several shipped files that do not load: every file's problems (core.md § 9)."""

    def __init__(self, errors: list[DefinitionError]):
        self.errors = errors
        super().__init__(
            data_root(),
            [(f"{Path(e.file).relative_to(data_root()) if Path(e.file).is_relative_to(data_root()) else e.file}"
              f":{path}", reason) for e in errors for path, reason in e.problems],
            ("python -m femkit schema check",),
        )


def control_files(root: Path | None = None) -> tuple[Path, Path]:
    """The control environment's two files: the channel order every environment is solved with,
    and the control environment's packages (definitions.md § 3)."""
    return (root or data_root()) / "channels.txt", (root or data_root()) / "control.txt"


def control_digest(root: Path | None = None) -> str:
    """What the install script's stamp holds: the SHA-256 of both files, channels first (envs.md § 7.2)."""
    digest = hashlib.sha256()
    for path in control_files(root):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_control(root: Path | None = None) -> ControlDefinition:
    """channels.txt is taken line by line as it stands, as the install script reads it; in
    control.txt, blank lines and `#` comments are skipped, as conda skips them."""
    channels_file, packages_file = control_files(root)
    try:
        channels = channels_file.read_text(encoding="utf-8").splitlines()
        packages = [line.strip() for line in packages_file.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    except OSError as exc:
        raise DefinitionError(exc.filename or packages_file, [("", f"does not read: {exc.strerror}")]) from None
    return validate(ControlDefinition, {"channels": channels, "dependencies": packages}, packages_file.parent)


def load_managers(root: Path | None = None) -> dict[str, ManagerKind]:
    return _load_dir((root or data_root()) / "managers", ManagerKind)


def load_schedulers(root: Path | None = None) -> dict[str, SchedulerKind]:
    return _load_dir((root or data_root()) / "schedulers", SchedulerKind)


def load_units(root: Path | None = None) -> UnitTable:
    return load_toml((root or data_root()) / "units.toml", UnitTable)


def load_formulations(root: Path | None = None) -> dict[str, FormulationDefinition]:
    """Every formulation, its units read by the unit table (models.md § 4)."""
    return _load_dir((root or data_root()) / "formulations", FormulationDefinition,
                     {"units": Units(load_units(root))})


CUDA_SUFFIX = "-cuda"  # a definition's CUDA environment is named after it with this (definitions.md § 4.5)


def load_environments(root: Path | None, engines: Mapping[str, frozenset[str]]) -> dict[str, EnvironmentDefinition]:
    """Every environment: one per definition, built without CUDA, and a second, `<name>-cuda`,
    for a definition with a [cuda] part (definitions.md § 4.5). ``engines``: each registered
    engine ID with its reader IDs (femkit.engines.registered())."""
    directory = (root or data_root()) / "environments"
    found = _load_dir(directory, EnvironmentDefinition, {"engines": engines})
    taken = {name: f"{CONTROL!r} names the control environment (control.txt)" for name in found if name == CONTROL}
    taken |= {name: f"a name ending in {CUDA_SUFFIX!r} is a definition's CUDA environment"
              for name in found if name.endswith(CUDA_SUFFIX)}
    if taken:
        raise CatalogueError([DefinitionError(directory / f"{name}.toml", [("", why)]) for name, why in taken.items()])
    out = {}
    for name, definition in found.items():
        out[name] = definition.built(cuda=False)
        if definition.cuda is not None:
            out[name + CUDA_SUFFIX] = definition.built(cuda=True)
    return dict(sorted(out.items()))


def load(ctx: Context, *, engines: Mapping[str, frozenset[str]]) -> Catalogue:
    """The shipped catalogue, loaded once per invocation (api.md § 2.4)."""
    key = ";".join(f"{e}:{','.join(sorted(r))}" for e, r in sorted(engines.items()))
    return ctx.cached(f"catalogue:{key}", lambda: load_catalogue(engines=engines))


def schedulers(ctx: Context) -> dict[str, SchedulerKind]:
    """The scheduler kinds, loaded once per invocation; they need no engine registry."""
    return ctx.cached("schedulers", load_schedulers)


def load_meshers(root: Path | None = None) -> dict[str, MesherDefinition]:
    """Every mesher; each names an engine environment that provides it (models.md § 6.5)."""
    environments = {p.stem for p in ((root or data_root()) / "environments").glob("*.toml")}
    return _load_dir((root or data_root()) / "meshers", MesherDefinition, {"environments": environments})


def meshers(ctx: Context) -> dict[str, MesherDefinition]:
    """The meshers, loaded once per invocation."""
    return ctx.cached("meshers", load_meshers)


def formulations(ctx: Context) -> dict[str, FormulationDefinition]:
    """The formulations, loaded once per invocation; they need no engine registry."""
    return ctx.cached("formulations", load_formulations)


def units(ctx: Context) -> Units:
    """The unit table, read once per invocation (core.md § 11); it needs no engine registry."""
    return ctx.cached("units", lambda: Units(load_units()))


def load_catalogue(root: Path | None = None, *, engines: Mapping[str, frozenset[str]]) -> Catalogue:
    """Every definition, or every problem with every file."""
    errors: list[DefinitionError] = []
    parts: dict = {}
    loaders = {
        "control": lambda: load_control(root),
        "environments": lambda: load_environments(root, engines),
        "managers": lambda: load_managers(root),
        "schedulers": lambda: load_schedulers(root),
        "units": lambda: load_units(root),
        "formulations": lambda: load_formulations(root),
        "meshers": lambda: load_meshers(root),
    }
    for name, load in loaders.items():
        try:
            parts[name] = load()
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
