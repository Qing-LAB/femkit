"""User configuration — `<config>/config.toml` (config.md § 3).

Choices for this machine, set by the person. The model below is the one home
of every key, its type and what its absence means; `config show`, `config
init`, the command-line options and the reference page all read it.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import tomlkit
from pydantic import AfterValidator, ConfigDict, Field, PositiveInt
from typing import Annotated

from femkit.core import dirs, paths, view
from femkit.core.errors import Unstated, UsageError
from femkit.core.operations import Context
from femkit.core.persist import document_set, read_document, write_document
from femkit.core.schema import DefinitionError, Model, classes, field_extras, load_toml, validate
from femkit.definitions.catalogue import data_root
from femkit.definitions.models import Launcher

FILE_NAME = "config.toml"


def _unset(text: str) -> dict:
    return {"unset": text}


def _absolute(path: Path) -> Path:
    """`~` is expanded; anything else relative is refused: no place is taken from
    the working directory (config.md § 2)."""
    path = path.expanduser()
    if not path.is_absolute():
        raise ValueError(f"{path} is relative; give an absolute path")
    return path


AbsolutePath = Annotated[Path, AfterValidator(_absolute)]


class Section(Model):
    """A config.toml section: TOML gives native types, so none is converted."""

    model_config = ConfigDict(strict=True)


class Paths(Section):
    environments: AbsolutePath | None = Field(
        default=None,
        strict=False,  # TOML has no path type: the text becomes a path
        description="where engine environment prefixes are created (the control environment's place is "
        "fixed) — on a cluster, typically project storage rather than a small home quota",
        json_schema_extra=_unset("<data>/environments"),
    )
    projects: AbsolutePath | None = Field(
        default=None,
        strict=False,  # TOML has no path type: the text becomes a path
        description="the projects root: the person's global material library and their projects",
        json_schema_extra={**_unset("no project is listed, made or named; each says so, naming this key"),
                           "doc": "projects.md § 1"},
    )


class BuildChoices(Section):
    cuda_architectures: list[str] | None = Field(
        default=None,
        description='GPU architectures the CUDA environments (<name>-cuda) target, e.g. ["80", "90"]',
        json_schema_extra=_unset("installing an environment with a build compiled for CUDA is refused, naming this key"),
    )
    jobs: PositiveInt | None = Field(
        default=None,
        description="parallel compile jobs",
        json_schema_extra=_unset("the CPUs this process may use (its CPU affinity: on a cluster, the allocation's share, never the whole login node)"),
    )


class Launch(Section):
    mpi: Launcher | None = Field(
        default=None,
        description='how a multi-rank process starts, e.g. ["mpirun", "-np", "{ranks}"]; must pass {ranks}',
        json_schema_extra=_unset("a multi-rank check or job, and installing an environment with MPI, "
                                 "are refused, naming this key"),
    )


class Activation(Section):
    preamble: list[str] | None = Field(
        default=None,
        description="shell lines a run script runs on this machine before it enters an environment "
        "(module load lines, for instance); [] states that none are needed",
        json_schema_extra=_unset("`job probe --write` and `job prepare` are refused, naming this key"),
    )
    command: Literal["source activate", "conda activate", "mamba activate"] | None = Field(
        default=None,
        description="how a shell on this machine enters an environment, after the preamble: `source activate`, "
        "the activate script on PATH (a cluster's module puts it there); or `conda activate` / `mamba activate`, "
        "the manager's shell function, its hook file sourced first",
        json_schema_extra=_unset("`job probe --write` and `job prepare` are refused, naming this key"),
    )


class UserConfig(Model):
    """`<config>/config.toml` — choices for this machine (config.md § 3)."""

    paths: Paths = Field(default_factory=Paths, description="where things go")
    build: BuildChoices = Field(default_factory=BuildChoices, description="how builds are made")
    launch: Launch = Field(default_factory=Launch, description="how processes start")
    activation: Activation = Field(default_factory=Activation, description="how a job's shell gets ready")


# ------------------------------------------------------------------ the keys

@dataclass(frozen=True)
class Key:
    section: str
    name: str
    annotation: Any
    description: str
    unset: str

    @property
    def dotted(self) -> str:
        return f"{self.section}.{self.name}"


def keys() -> list[Key]:
    """Every key, read from the model."""
    out = []
    for section, field in UserConfig.model_fields.items():
        for name, sub in classes(field.annotation)[0].model_fields.items():
            out.append(Key(section, name, sub.annotation, sub.description or "", field_extras(sub)["unset"]))
    return out


def key(dotted: str) -> Key:
    for k in keys():
        if k.dotted == dotted:
            return k
    raise UsageError(f"no key {dotted!r}; keys: {', '.join(k.dotted for k in keys())}", code="no-such-key",
                     subject=dotted)


#: What nothing on a machine reveals: a person states it, and it is never proposed (config.md § 3.1).
PREAMBLE = "activation.preamble"
COMMAND = "activation.command"
STATED = (PREAMBLE, COMMAND)


def unstated(config: UserConfig) -> list[str]:
    """The keys of STATED that ``config`` leaves unset."""
    return [d for d in STATED if getattr(getattr(config, key(d).section), key(d).name) is None]


def config_file() -> Path:
    return dirs.config_dir() / FILE_NAME


def environments_root(config: UserConfig) -> Path:
    return config.paths.environments or dirs.environments_dir()


# ------------------------------------------------------------- loading

@dataclass(frozen=True)
class Loaded:
    config: UserConfig
    file: Path | None  # None: no file, every key unset

    def present(self) -> dict[str, Any]:
        """Keys the file sets, with their values."""
        out = {}
        for k in keys():
            section = getattr(self.config, k.section)
            if k.section in self.config.model_fields_set and k.name in section.model_fields_set:
                out[k.dotted] = plain(getattr(section, k.name))
        return out


def _read() -> Loaded:
    path = config_file()
    if not path.exists():
        return Loaded(UserConfig(), None)
    return Loaded(load_toml(path, UserConfig), path)


def load(ctx: Context, *, fresh: bool = False) -> Loaded:
    """The configuration, read once per invocation; ``fresh`` reads the file again
    without touching the cache (apply re-observes with it)."""
    return _read() if fresh else ctx.cached("config", _read)


def launcher(ctx: Context, needed_by: str) -> list[str]:
    """launch.mpi, or a refusal saying what needs it and how to set it (config.md § 3.1)."""
    mpi = load(ctx).config.launch.mpi
    if mpi is None:
        from femkit.config.requests import CONFIG_SET  # the requests are built from this module's keys
        raise Unstated(f"{needed_by}, and launch.mpi is unset",
                      (view.command(CONFIG_SET, key="launch.mpi", note="this machine's launcher",
                                    fills=[view.Fill(field="value", label="launch.mpi",
                                                              example='["mpirun", "-np", "{ranks}"]')]),),
                  code="setting-unset", subject="launch.mpi")
    return mpi


def value_of(config: UserConfig, k: Key) -> Any:
    return getattr(getattr(config, k.section), k.name)


def plain(value: Any) -> Any:
    return str(value) if isinstance(value, Path) else value


def as_planned(ctx: Context, values: dict[str, Any]) -> Context:
    """A context that reads the configuration as it will be once ``values`` are written,
    for planning what a config write is followed by (`env bootstrap`). Writes nothing."""
    if not values:
        return ctx
    planned = Loaded(config=validate(UserConfig, with_values(values).unwrap(), config_file()), file=config_file())
    c = ctx.fresh()
    c.cached("config", lambda: planned)
    return c


# ------------------------------------------------------------- writing

def template_text() -> str:
    return (data_root() / "templates" / FILE_NAME).read_text(encoding="utf-8")


def with_values(values: dict[str, Any]) -> tomlkit.TOMLDocument:
    """The file (or the template) as a document that keeps its comments, with
    ``values`` (dotted key -> value) set and the whole validated. A value the
    model rejects is a request that does not validate: `UsageError`."""
    path = config_file()
    doc = read_document(path, empty=template_text())
    for dotted, value in values.items():
        k = key(dotted)
        document_set(doc, (k.section, k.name), value)
    try:
        validate(UserConfig, doc.unwrap(), path)
    except DefinitionError as exc:
        raise UsageError(exc.summary(), code="invalid-value", subject=", ".join(values)) from None
    return doc


def write(doc: tomlkit.TOMLDocument) -> Path:
    return write_document(config_file(), doc)


def free_space(path: Path) -> int | None:
    """Free bytes on the file system that holds ``path`` (its nearest existing parent)."""
    existing = paths.nearest_existing(path)
    return shutil.disk_usage(existing).free if existing else None
