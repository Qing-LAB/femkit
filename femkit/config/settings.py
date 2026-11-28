"""User configuration — `<config>/config.toml` (config.md § 3).

Choices for this machine, set by the person. The model below is the one home
of every key, its type, its help, what its absence means and the question
`config init` asks for it; `config show`, `config init`, the command-line
options, the reference page and the template's comments all read it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from pydantic import AfterValidator, ConfigDict, Field, PositiveInt, TypeAdapter
from pydantic.fields import FieldInfo
from typing import Annotated

from femkit.core import dirs, text, view
from femkit.core.errors import Unstated, UsageError
from femkit.core.operations import Context
from femkit.core.persist import TOMLDocument, document_set, inline_text, read_document, write_document
from femkit.core.schema import (DefinitionError, Model, classes, closed, described, field_extras, items_of, load_toml,
                                 validate)
from femkit.definitions.catalogue import data_root, shipped
from femkit.definitions.models import Launcher

FILE_NAME = "config.toml"

#: The chapter of the user manual that explains the settings file, by its file's name in
#: `docs/manual/`: the help of its keys ends with it (core.md § 2).
MANUAL = "1-install.md"


def _unset(text: str, **more: Any) -> dict:
    """A key's annotations (config.md § 3.1): ``text``, what its absence means — its default, or
    what it blocks; ``ask``, the question `config init` asks while it is unset; ``beside``, what is
    measured here and shown beside that question; ``propose``, what `config init` proposes it from;
    ``cli``, the option `config init` takes it by where its name is not that; ``empty``, for a list
    stated empty by a flag of `config init`'s, that flag's field and what an empty list says
    (config.md § 3.2); ``doc``."""
    return {"unset": text, **more}


#: A key's `empty` annotation (`_unset`): the field of `config init`'s request that states its list
#: empty, and what an empty list says.
EMPTY = "empty"


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
    projects: AbsolutePath | None = Field(
        default=None,
        strict=False,  # TOML has no path type: the text becomes a path
        description="the projects root: the person's global material library and their projects",
        examples=["/path/to/projects"],
        json_schema_extra=_unset("no project is listed, made or named; each says so, naming this key",
                                 ask="Which folder holds your projects and your material library?",
                                 doc="projects.md § 1"),
    )


class BuildChoices(Section):
    cuda_architectures: list[str] | None = Field(
        default=None,
        description='GPU architectures the CUDA environments (<name>-cuda) target, e.g. ["80", "90"]',
        examples=[["80", "90"]],
        json_schema_extra=_unset("installing an environment with a build compiled for CUDA is refused, naming this key",
                                 propose="gpu-architectures"),
    )
    jobs: PositiveInt | None = Field(
        default=None,
        description="parallel compile jobs",
        examples=[8],
        json_schema_extra=_unset("the CPUs this process may use (its CPU affinity: on a cluster, the allocation's share, never the whole login node)"),
    )


class Launch(Section):
    mpi: Launcher | None = Field(
        default=None,
        description='how a multi-rank process starts, e.g. ["mpirun", "-np", "{ranks}"]; must pass {ranks}',
        examples=[["mpirun", "-np", "{ranks}"]],
        json_schema_extra=_unset("a multi-rank check or job, and installing an environment with MPI, "
                                 "are refused, naming this key", propose="scheduler-launcher"),
    )


class Activation(Section):
    preamble: list[str] | None = Field(
        default=None,
        description="the shell lines a run script runs on this machine before it enters an environment — a batch "
        "job starts a fresh shell, so a `module load` that puts the manager on PATH belongs here; [] states that "
        "none are needed",
        examples=[["module load mamba"]],
        json_schema_extra=_unset("`job probe --write` is refused, naming this key",
                                 ask="Which shell lines must a job here run before it enters an environment? "
                                     "If none, give --no-preamble instead",
                                 beside="loaded-modules", empty={"field": "no_preamble",
                                                                 "says": "this machine needs none"},
                                 doc="config.md § 3.1"),
    )
    command: Literal["source activate", "conda activate", "mamba activate"] | None = Field(
        default=None,
        description="how a shell on this machine enters an environment after the preamble — by the activate "
        "script on PATH, which a cluster's module puts there, or by the manager's shell function, its own hook "
        "evaluated first",
        examples=["source activate"],
        json_schema_extra=_unset("`job probe --write` is refused, naming this key",
                                 ask="How does a shell here enter an environment, after those lines?",
                                 cli="--activation", doc="config.md § 3.1"),
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
    """One key of config.toml and its field: the one home of its help, of what its absence
    means and of the question `config init` asks for it (config.md § 3.1)."""

    section: str
    name: str
    field: FieldInfo

    @property
    def dotted(self) -> str:
        return f"{self.section}.{self.name}"

    @property
    def annotation(self) -> Any:
        return self.field.annotation

    @property
    def fragment(self) -> dict[str, Any]:
        """The JSON schema fragment of what the key holds (web.md § 7.3): a value to fill of it — `config
        set`'s, whose request takes the value's TOML text — is given as the key's own value, a list as a
        list."""
        return TypeAdapter(self.annotation).json_schema()

    @property
    def description(self) -> str:
        return self.field.description or ""

    @property
    def help(self) -> str:
        """Its help, as the template's comment above it reads (core.md § 2)."""
        return described(self.field, MANUAL)

    @property
    def unset(self) -> str:
        """What its absence means: its default, or what it blocks."""
        return field_extras(self.field)["unset"]

    @property
    def ask(self) -> str | None:
        """The question `config init` asks while it is unset; None for a key it does not ask for."""
        return field_extras(self.field).get("ask")

    @property
    def extras(self) -> dict:
        """Its annotations: what is measured beside its question (`beside`), what `config init`
        proposes it from (`propose`), its option's spelling (`cli`) — each read where it is used."""
        return field_extras(self.field)

    @property
    def empty(self) -> tuple[str, str] | None:
        """For a list a flag of `config init`'s states empty, that flag's request field and what an
        empty list says, as the key's field declares them (config.md § 3.2); None for any other."""
        held = field_extras(self.field).get(EMPTY)
        return (held["field"], held["says"]) if held else None

    @property
    def example(self) -> Any:
        """A value that would do, as its field declares one: what a step that states it shows."""
        return self.field.examples[0] if self.field.examples else None

    def shown(self, value: Any) -> str:
        """A value the key holds, as a person reads it (api.md § 4.4): read by the key's type, so a
        path is written from `~` where it lies under the home folder; unset in words."""
        return text.show(TypeAdapter(self.annotation).validate_python(value))


def keys() -> list[Key]:
    """Every key, read from the model."""
    out = []
    for section, field in UserConfig.model_fields.items():
        for name, sub in classes(field.annotation)[0].model_fields.items():
            out.append(Key(section, name, sub))
    return out


def key(dotted: str) -> Key:
    for k in keys():
        if k.dotted == dotted:
            return k
    raise UsageError(f"no key `{dotted}`; keys: {', '.join(k.dotted for k in keys())}", code="no-such-key",
                     subject=dotted)


#: How a job's shell gets ready on a machine and enters an environment, by their keys (config.md § 3.1).
PREAMBLE = "activation.preamble"
COMMAND = "activation.command"


def person_states(among: Iterable[str] | None = None) -> list[str]:
    """The keys only the person states, of ``among`` or of every key: their field declares the
    question `config init` asks (`ask`), and nothing is in effect while they are unset (`IN_EFFECT`)
    — read from the declarations, never a list of names (config.md §§ 3.1, 3.2)."""
    among = None if among is None else set(among)
    return [k.dotted for k in keys() if k.ask and k.dotted not in IN_EFFECT and (among is None or k.dotted in among)]


def unstated(values: Any, among: Iterable[str] | None = None) -> list[str]:
    """The keys only the person states (`person_states`), of ``among`` or of every key, that
    ``values`` — a config.toml, or what a machine record copied of one — leaves unset."""
    return [d for d in person_states(among) if value_of(values, key(d)) is None]


def steps(dotted: list[str], note: str | None = None, machine: view.Machine | None = None) -> tuple[view.Action, ...]:
    """The step that states each of these keys — for the machine ``machine``, where it is another's —
    chosen from its field's declaration (config.md § 3.2): a key `config init` asks for (`ask`) is
    `config init`, which asks for it in words (`asking`), once for all of them; any other — one
    `config init` proposes (`propose`) but cannot here — `config set`, its value to fill
    (`setting`). The one builder of a setting's step, wherever another command needs a key."""
    asked = [d for d in dotted if key(d).ask]
    return (*asking(asked, machine), *setting([d for d in dotted if d not in asked], note, machine))


def asking(unset: list[str], machine: view.Machine | None = None) -> tuple[view.Action, ...]:
    """The step for the keys `config init` asks for, ``unset`` — bare `config init`, which asks for
    each in words — for the machine ``machine``, where it is another's; none where none is unset —
    never an example written as if it were the person's (config.md § 3.2; workflow.md § 7)."""
    from femkit.config.requests import CONFIG_INIT  # the requests are built from this module's keys
    return (view.command(CONFIG_INIT, note=f"asks for {' and '.join(unset)}", machine=machine),) if unset else ()


def setting(dotted: list[str], note: str | None = None, machine: view.Machine | None = None
            ) -> tuple[view.Action, ...]:
    """`config set` for each of these keys — for the machine ``machine``, where it is another's — its
    value to fill as its TOML text, carrying the key's help and its example as help (config.md
    § 3.1), never written as if it were the person's (workflow.md § 7)."""
    from femkit.config.requests import CONFIG_SET  # the requests are built from this module's keys
    out: list[view.Action] = []
    for k in map(key, dotted):
        example = None if k.example is None else inline_text(k.example)
        out.append(view.command(CONFIG_SET, key=k.dotted, note=note, machine=machine, fills=[
            view.Fill(field="value", label=k.dotted, example=example, help=view.Help.of(k.description),
                      json_schema=k.fragment)]))
    return tuple(out)


def setting_to(dotted: str, values: list[Any], machine: view.Machine | None = None) -> tuple[view.Action, ...]:
    """`config set` of the key ``dotted`` to each of ``values`` — for the machine ``machine``, where it
    is another's — each written as its TOML text: the values its field allows that would do here,
    where the one set does not (config.md § 3.2), never an example written as if it were the person's."""
    from femkit.config.requests import CONFIG_SET  # the requests are built from this module's keys
    return tuple(view.command(CONFIG_SET, key=key(dotted).dotted, value=inline_text(v), machine=machine)
                 for v in values)


def options(dotted: list[str], note: str | None = None) -> tuple[view.Action, ...]:
    """Each form of `config init`'s option for each of these keys, one step for each form, each read
    from the key's field (config.md § 3.2): its value to fill, carrying its help; the alternatives
    of a closed list one step, their choices said beside it; and, for a list its field declares a
    flag stating empty (`empty`), that flag. A value to fill is written as what it asks for, its
    example only as help (workflow.md § 7)."""
    from femkit.config.requests import CONFIG_INIT  # the requests are built from this module's keys
    out: list[view.Action] = []
    for k in map(key, dotted):
        values, many = closed(k.annotation), items_of(k.annotation) is not None
        example = None if values or k.example is None else str(k.example[0] if many else k.example)
        said = note or (f"one of: {', '.join(values)}" if values else "once per value" if many else None)
        out.append(view.command(CONFIG_INIT, note=said, fills=[
            view.Fill(field=k.name, label=k.dotted, example=example, help=view.Help.of(k.description))]))
        if k.empty is not None:
            out.append(view.command(CONFIG_INIT, note=empty_said(k), **{k.empty[0]: True}))
    return tuple(out)


def empty_said(k: Key) -> str:
    """What the flag stating ``k``'s list empty says, as its field declares it (config.md § 3.2)."""
    return f"{k.dotted} = []: {k.empty[1]}"


def config_file() -> Path:
    return dirs.config_dir() / FILE_NAME


#: What is in effect while a key is unset, where something is (config.md § 3.1): the one home of
#: each such rule, beside the model that states it — `build.jobs`, the CPUs this process may use, its
#: CPU affinity: on a cluster, the allocation's share, never the whole login node. A key not here has
#: nothing in effect while unset.
IN_EFFECT: dict[str, Callable[[], Any]] = {
    "build.jobs": lambda: len(os.sched_getaffinity(0)),
}


def build_jobs(config: UserConfig) -> int:
    """build.jobs, or what is in effect while it is unset."""
    return config.build.jobs or IN_EFFECT["build.jobs"]()


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
        raise Unstated(f"{needed_by}, and launch.mpi is unset", steps(["launch.mpi"]),
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
    return shipped(data_root() / "templates" / FILE_NAME)


def with_values(values: dict[str, Any]) -> TOMLDocument:
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


def write(doc: TOMLDocument) -> Path:
    return write_document(config_file(), doc)

