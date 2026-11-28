"""Machine records — `<config>/machines/<name>.toml` (jobs.md § 9).

The one model of a record, its one reader and writer, and its state against this machine's
config.toml, by the rules `femkit/data/states/record.toml` declares. Reading a record never probes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationInfo, create_model, model_validator

from femkit.config import settings
from femkit.config.probe import Where
from femkit.core import dirs, persist, states, text
from femkit.core.errors import Unstated, UsageError
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, Model, key_path, load_toml, refuse
from femkit.definitions import catalogue
from femkit.envs import state as env_state
from femkit.jobs.requests import LOCAL, MACHINE_NAME

SCHEMA = 4
#: The unit a record keeps memory in, whole, as the scheduler reports it (jobs.md § 9.1), as the unit
#: table names it.
MEBIBYTE = "MiB"

NAME = re.compile(MACHINE_NAME)   # the request's own grammar: a name typed in a request or found as a file


class Unknown(Model):
    """A fact that could not be measured, and why. Never read as zero or none."""

    unknown: str = Field(description="why it could not be measured")


def shown(value: Any) -> str:
    """One fact of a record as a person reads it: an unknown with its reason (api.md § 4.4)."""
    if isinstance(value, dict) and set(value) == {"unknown"}:
        value = Unknown.model_validate(value)
    return f"unknown ({value.unknown})" if isinstance(value, Unknown) else text.show(value)


# A limit has three answers (jobs.md § 9.1): a number, `unlimited` (asked; none stated),
# or unknown. Neither of the last two is counted against a request.
Limit = int | Literal["unlimited"] | Unknown
Wall = Literal["unlimited"] | Unknown | str  # str: the scheduler's own spelling, e.g. 7-00:00:00


class Measured(Model):
    time: str = Field(description="when the probe ran, UTC")
    where: Where = Field(description="where it ran")


class HostGPU(Model):
    model: str = Field(description="as the driver reports it; shown, never compared")
    compute_capability: str = Field(description="e.g. 8.0")
    memory_mib: int = Field(description="its memory")


class Host(Model):
    os: str = Field(description="operating system and release")
    architecture: str = Field(description="e.g. x86_64")
    cores: int | Unknown = Field(description="the machine's logical CPUs")
    memory_mib: int | Unknown = Field(description="its memory")
    gpus: list[HostGPU] | Unknown = Field(description="its GPUs, as the driver reports them")


class ManagerFacts(Model):
    kind: str | Unknown = Field(description="the manager kind (femkit/data/managers/)")
    path: str | Unknown = Field(description="the manager executable")
    version: str | Unknown = Field(description="its version")
    root: str | Unknown = Field(description="its root (base) prefix")
    platform: str | Unknown = Field(description="what an environment built here is for, e.g. linux-64")
    run_enters: bool | Unknown = Field(description="whether `<manager> run -n femkit` runs inside the prefix the manager lists for the control environment here")


class SchedulerFacts(Model):
    kind: str = Field(description="the scheduler kind (femkit/data/schedulers/)")
    commands: dict[str, str | Unknown] = Field(default_factory=dict, description="each job command by role: where it is")
    probe: dict[str, str | Unknown] = Field(default_factory=dict, description="each probe command by role: where it is")


class NodeGroup(Model):
    count: int = Field(description="how many nodes are alike in the four facts below")
    cores: int | Unknown = Field(description="cores per node")
    memory_mib: int | Unknown = Field(description="memory per node")
    gpus: dict[str, int] | Unknown = Field(default_factory=dict, description="GPUs per node, {type: count}; {} is none")
    architecture: str | Unknown = Field(description="e.g. x86_64, aarch64")


class Partition(Model):
    max_time: Wall = Field(description="MaxTime")
    max_cpus_per_node: Limit = Field(description="MaxCPUsPerNode")
    def_mem_per_cpu_mib: Limit | None = Field(default=None, description="DefMemPerCPU, when the partition states it")
    def_mem_per_node_mib: Limit | None = Field(default=None, description="DefMemPerNode, when the partition states it")
    allow_qos: Literal["all"] | list[str] = Field(description="AllowQos")
    deny_qos: list[str] = Field(default_factory=list, description="DenyQos")
    node_groups: list[NodeGroup] = Field(default_factory=list, description="its nodes, grouped")


class Queue(Model):
    partition: str = Field(description="the partition")
    qos: str | None = Field(default=None, description="the QOS; absent when the account's QOS list could not be read")
    max_time: Wall = Field(description="the shorter of the partition's MaxTime and the QOS's MaxWall")
    max_cpus: Limit = Field(description="the QOS's per-job cpu cap (MaxTRESPerJob)")
    max_memory_mib: Limit = Field(description="the QOS's per-job memory cap")
    max_gpus: Limit = Field(description="the QOS's per-job GPU cap")
    max_submit_jobs_per_user: Limit = Field(description="MaxSubmitJobsPerUser; shown, never counted")


class EnvSnapshot(Model):
    state: str = Field(description="its state when the probe ran", json_schema_extra={"doc": "envs.md § 3.2"})
    gpu: str | None = Field(default=None, description="its GPU qualification, when ready or failing")
    install_fingerprint: str | None = Field(default=None, description="from its manifest")
    solver_version: str | None = Field(default=None, description="from its manifest")


#: The keys of this machine's config.toml a job run here needs, copied into its record (jobs.md § 9.1).
COPIED = ("launch.mpi", "activation.preamble", "activation.command")


def _copied() -> type[Model]:
    """The record's `settings`: each key of COPIED by its own name, type and help — its field of
    `UserConfig` (config.md § 3.1) — in its own table, as config.toml writes it."""
    tables: dict[str, dict[str, Any]] = {}
    for k in map(settings.key, COPIED):
        tables.setdefault(k.section, {})[k.name] = (k.annotation, k.field)
    models = {section: create_model(f"Copied{section.title()}", __base__=settings.Section, **fields)
              for section, fields in tables.items()}
    return create_model("Settings", __base__=Model, __doc__="config.toml's values a job run here needs, copied",
                        **{section: (model, Field(default_factory=model,
                                                  description=settings.UserConfig.model_fields[section].description))
                           for section, model in models.items()})


Settings = _copied()


class Record(Model):
    """One machine's record, as measured on it (jobs.md § 9.1). Its file states the record's
    schema version, `schema`, first; a record of another version does not load."""

    measured: Measured = Field(description="when and where the probe ran")
    identity: str | Unknown = Field(description="the scheduler's cluster name, or the host name")
    host: Host = Field(description="the machine the probe ran on; on a cluster, never what a job is fit against")
    manager: ManagerFacts = Field(description="the package manager here")
    scheduler: SchedulerFacts = Field(description="the scheduler kind, and where its commands are")
    partitions: dict[str, Partition] | Unknown = Field(description="each partition's limits and node groups")
    queues: list[Queue] | Unknown = Field(description="each (partition, QOS) pair this account may submit to")
    environments: dict[str, EnvSnapshot] | Unknown = Field(description="`env list` here when the probe ran")
    settings: Settings = Field(description="this machine's config.toml values a job run here needs, copied")
    sources: dict[str, str] = Field(default_factory=dict, description="dotted part -> what measured it")
    notes: list[str] = Field(default_factory=list, description="what the probe could not do, and why")

    @model_validator(mode="before")
    @classmethod
    def _version(cls, data: Any, info: ValidationInfo) -> Any:
        """The schema version its file states, read before anything else: a record of another
        version, or of none, is refused naming its version and the probe that rewrites it (jobs.md
        § 9.1). A record a result holds, as femkit wrote it there, states none."""
        stated = isinstance(data, dict) and "schema" in data
        if not stated and not (info.context or {}).get(FILE):
            return data
        written = data.get("schema") if isinstance(data, dict) else None
        if written != SCHEMA:
            refuse("Record", [(("schema",), f"written with schema {text.show(written)}; this femkit reads {SCHEMA}: "
                                           "rewrite it with `job probe --write` on that machine")])
        return {k: v for k, v in data.items() if k != "schema"}

    def data(self) -> dict:
        """The record as its file holds it: its schema version first, no nulls."""
        return {"schema": SCHEMA, **self.model_dump(mode="json", exclude_none=True)}


# ------------------------------------------------------------------ files

def machines_dir() -> Path:
    return dirs.config_dir() / "machines"


def path(name: str) -> Path:
    if not NAME.fullmatch(name):
        raise UsageError(f"`{name}` is not a machine name: letters, digits, `.`, `_` and `-`", code="bad-name",
                         subject=name)
    return machines_dir() / f"{name}.toml"


FILE = "file"   # the validation context of a record read from its file, which states its schema version


def read(file: Path) -> Record:
    """The record, or DefinitionError naming what is wrong, by the one TOML reader (core.md § 2) —
    a record of another schema version names that version and the probe that rewrites it."""
    return load_toml(file, Record, {FILE: True})


def write(file: Path, record: Record) -> Path:
    return persist.write_toml(file, record.data())


def sha256(file: Path) -> str | None:
    return persist.sha256(file)


def listing() -> list[tuple[str, Path, Record | None, str]]:
    """Every record: (name, path, the record or None, why it does not load)."""
    out = []
    for file in sorted(machines_dir().glob("*.toml")) if machines_dir().is_dir() else []:
        try:
            out.append((file.stem, file, read(file), ""))
        except DefinitionError as exc:
            out.append((file.stem, file, None, exc.summary()))
    return out


def host_identity() -> str:
    """This host's name: a machine's identity when it has no scheduler (jobs.md § 9.1), what the
    probe records there, and the host a job launched here is asked about by (jobs.md § 5.1); the
    one host name femkit reads (core.md § 3). Never what tells whether a record is this machine's
    (`of_this_machine`): a cluster's identity is its scheduler's cluster name, no host's."""
    return dirs.host()


def own() -> Record | None:
    """This machine's own record, `local` — always the machine a command runs on (jobs.md § 9.3) —
    where it is there and loads: what every other record is told this machine's by
    (`of_this_machine`)."""
    file = path(LOCAL)
    if not file.is_file():
        return None
    try:
        return read(file)
    except DefinitionError:
        return None


def of_this_machine(r: Record | str) -> bool:
    """Whether a record describes this machine — told by its identity of the host, never its name
    nor this host's name, here alone (jobs.md § 9.3; workflow.md § 7). A record, by what it holds:
    this machine's own (`own`) does, and any naming its identity — so on a cluster its own record
    `cluster-a` is this machine's, as `local` is, though its identity is the scheduler's cluster
    name and no host's, and a calculation's copy of a `local` measured on another machine is not;
    two identities neither probe could read name no machine. A record of `<config>/machines/`, by
    its name: `local`, always the machine a command runs on, whatever its file holds; any other by
    what its file holds — one not there, or that does not load, another machine's, whose machine
    cannot be told."""
    if isinstance(r, str):
        if r == LOCAL:
            return True
        try:
            r = read(path(r))
        except DefinitionError:
            return False
    local = own()
    return local is not None and (r == local or isinstance(r.identity, str) and r.identity == local.identity)


def copied(values: Settings | settings.UserConfig, dotted: str) -> Any:
    """The value a record's settings, or a config.toml, hold for one key of COPIED."""
    return settings.value_of(values, settings.key(dotted))


def settings_now(config: settings.UserConfig) -> Settings:
    """This machine's settings as a record copies them (jobs.md § 9.1), each key as config.toml holds it."""
    now = {d: copied(config, d) for d in COPIED}
    tables: dict[str, dict[str, Any]] = {}
    for d, value in now.items():
        k = settings.key(d)
        tables.setdefault(k.section, {})[k.name] = value
    return Settings.model_validate(tables)


def stale(record: Record, config: settings.UserConfig) -> list[str]:
    """The settings a record of this machine no longer shares with its config.toml (jobs.md § 9.3)."""
    now = settings_now(config)
    return [f"{d}: recorded {settings.key(d).shown(copied(record.settings, d))}, now {settings.key(d).shown(copied(now, d))}"
            for d in COPIED if copied(record.settings, d) != copied(now, d)]


@dataclass(frozen=True)
class Listing:
    """What a record lists of one environment (jobs.md § 9.1): whether it could list its
    environments at all — and, where not, why — what it lists of this one, none where it lists it
    not, and as what: its state, the environment machine's member — none where it lists it not, or
    in a state that machine does not have — and whether it lists it GPU-qualified."""

    known: bool
    why: str | None
    snapshot: EnvSnapshot | None
    state: Enum | None
    qualified: bool


def listed(ctx: Context, r: Record, name: str) -> Listing:
    """Whether the record ``r`` lists the environment ``name``, and as what (jobs.md § 9.1): the one
    reader of a record's environments, for a stage's identity and a prepare's warning alike — each
    comparing the state it lists by the environment machine's member, never by its name."""
    if not isinstance(r.environments, dict):
        return Listing(known=False, why=r.environments.unknown, snapshot=None, state=None, qualified=False)
    snap = r.environments.get(name)
    named = {s.value: s for s in env_state.machine(ctx).states}
    return Listing(known=True, why=None, snapshot=snap, state=named.get(snap.state) if snap else None,
                   qualified=snap is not None and snap.gpu == env_state.QUALIFIED)


def environments_now(ctx: Context, r: Record) -> dict[str, tuple[str | None, str]]:
    """Each environment whose state here now differs from what a record of this machine holds of
    it: (its state in the record, or None for one it lists not; its state now) — `env list` now
    against the record's snapshot (jobs.md § 9.3), which never makes the record stale; none where no
    manager is named here to ask where they are (envs.md § 3.1)."""
    held = r.environments if isinstance(r.environments, dict) else {}
    m = env_state.machine(ctx)
    out = {}
    for name in sorted(catalogue.load(ctx).environments):
        try:
            state = env_state.observe(ctx, name)[1]
        except Unstated:
            return {}
        was = held[name].state if name in held else None
        if was != state.value and not (was is None and state is m.states.absent):   # never installed: no change
            out[name] = (was, state.value)
    return out


@dataclass(frozen=True)
class RecordFacts:
    """What is observed of a record of this machine."""

    name: str             # the record's name
    there: bool           # its file is there
    problem: str | None   # why the file does not load; None when it loads, or is not there
    drift: list[str]      # the settings it no longer shares with this machine's config.toml
    installs: bool = False   # `env bootstrap`'s: it installs an environment, which the record would list as it was


def probe_name(name: str) -> str | None:
    """The name a probe writing the record ``name`` is given: none for `local`, this machine's own
    record and the probe's default, which takes no `--name` (jobs.md § 9.2) — decided here alone.
    Which file the probe writes, never which machine it runs on (`of_this_machine`)."""
    return None if name == LOCAL else name


#: The action of a record's state that writes it, measuring the machine it describes (jobs.md § 9.3).
PROBE = "probe"
#: What `env bootstrap` does to this machine's record, by the names its table's `[tasks]` gives them
#: (envs.md § 6.2): measure the machine and write it; measure a current one again where it installs
#: environments.
WRITE, RENEW = "write", "renew"

BINDING = states.Binding("record", {
    "there": lambda f: f.there,
    "loads": lambda f: f.problem is None,
    "drifted": lambda f: bool(f.drift),
    "installs": lambda f: f.installs,
}, values={"name": lambda f: probe_name(f.name)},
   reads=frozenset({"absent", "unloadable", "stale", "current"}), acts=frozenset({PROBE}),
   tasks=frozenset({WRITE, RENEW}))


def machine(ctx: Context) -> states.Machine:
    """The machine `femkit/data/states/record.toml` declares, bound to these facts (jobs.md § 9.3)."""
    return catalogue.machine(ctx, BINDING)


def facts(file: Path, config: settings.UserConfig | None) -> RecordFacts:
    """What is observed of the record ``file``: a record of this machine, against this config.toml;
    with no ``config``, a record not compared — another machine's, or one only probed again — whose
    settings never drift (jobs.md § 9.3)."""
    name = file.stem
    if not file.exists():
        return RecordFacts(name=name, there=False, problem=None, drift=[])
    try:
        held = read(file)
    except DefinitionError as exc:
        return RecordFacts(name=name, there=True, problem=exc.summary(), drift=[])
    return RecordFacts(name=name, there=True, problem=None, drift=stale(held, config) if config is not None else [])


def status(ctx: Context, file: Path, config: settings.UserConfig) -> tuple[Enum, str, RecordFacts]:
    """A record of this machine against this config.toml (jobs.md § 9.3): its state by the
    machine's rules, the detail — what drifted, or what is wrong — and its facts."""
    f = facts(file, config)
    return machine(ctx).observe(f), f.problem or "; ".join(f.drift), f


def unknowns(record: Record) -> list[tuple[str, str]]:
    """Every fact the record holds as unknown: (its key path, why)."""
    found: list[tuple[str, str]] = []

    def walk(value: Any, where: tuple) -> None:
        if isinstance(value, dict):
            if set(value) == {"unknown"}:
                found.append((key_path(where), value["unknown"]))
                return
            for k, v in value.items():
                walk(v, (*where, k))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, (*where, i))

    walk(record.data(), ())
    return found


def differences(old: Record, new: Record) -> list[str]:
    """What changed, part by part, leaving out when it was measured."""
    a, b = _flat(old.data()), _flat(new.data())
    skip = ("measured.", "sources.")   # key paths, as core writes them
    return [f"{k}: {shown(a[k]) if k in a else '(absent)'} -> {shown(b[k]) if k in b else '(absent)'}"
            for k in sorted(set(a) | set(b)) if not k.startswith(skip) and a.get(k) != b.get(k)]


def _flat(value: Any, where: tuple = ()) -> dict[str, Any]:
    """Every value of a record at its key path; a list of tables' items at their index — a queue
    is `queues[0].max_time` — so a change names the one value that changed."""
    items = value.items() if isinstance(value, dict) and set(value) != {"unknown"} else \
        enumerate(value) if isinstance(value, list) and value and isinstance(value[0], dict) else None
    if not items:
        return {key_path(where): value}
    out: dict[str, Any] = {}
    for k, v in items:
        out.update(_flat(v, (*where, k)))
    return out
