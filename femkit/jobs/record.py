"""Machine records — `<config>/machines/<name>.toml` (jobs.md § 9).

The one model of a record, and its one reader and writer. Reading a record never probes.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from femkit.config import settings
from femkit.config.probe import Where
from femkit.core import dirs, persist
from femkit.core.errors import UsageError
from femkit.core.schema import DefinitionError, Model, load_toml

SCHEMA = 1
LOCAL = "local"  # always the machine the command runs on
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class Unknown(Model):
    """A fact that could not be measured, and why. Never read as zero or none."""

    unknown: str = Field(description="why it could not be measured")


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
    run_enters: bool | Unknown = Field(description="whether `<manager> run -p <control prefix>` runs inside that prefix here")


class SchedulerFacts(Model):
    kind: str = Field(description="the scheduler kind (femkit/data/schedulers/)")
    commands: dict[str, str | Unknown] = Field(default_factory=dict, description="each job command by role: where it is")
    probe: dict[str, str | Unknown] = Field(default_factory=dict, description="each probe command by role: where it is")


class NodeGroup(Model):
    count: int = Field(description="how many nodes are alike in the four facts below")
    cores: int | Unknown = Field(description="cores per node")
    memory_mib: int | Unknown = Field(description="memory per node")
    gpus: dict[str, int] = Field(default_factory=dict, description="GPUs per node, {type: count}; {} is none")
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
    state: str = Field(description="its state when the probe ran (envs.md § 3.2)")
    gpu: str | None = Field(default=None, description="its GPU qualification, when ready or failing")
    install_fingerprint: str | None = Field(default=None, description="from its manifest")
    solver_version: str | None = Field(default=None, description="from its manifest")


class Settings(Model):
    environments: str = Field(description="paths.environments, as in effect")
    mpi: list[str] | None = Field(default=None, description="launch.mpi; absent when unset")
    preamble: list[str] | None = Field(default=None, description="activation.preamble; absent when unset")


class Record(Model):
    """One machine's record, as measured on it (jobs.md § 9.1)."""

    schema_: Literal[1] = Field(alias="schema", description="the record's schema version")
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

    model_config = {**Model.model_config, "populate_by_name": True}

    def data(self) -> dict:
        """The record as TOML-ready data: no nulls."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


# ------------------------------------------------------------------ files

def machines_dir() -> Path:
    return dirs.config_dir() / "machines"


def path(name: str) -> Path:
    if not NAME.fullmatch(name):
        raise UsageError(f"{name!r} is not a machine name: letters, digits, '.', '_' and '-'")
    return machines_dir() / f"{name}.toml"


def read(file: Path) -> Record:
    """The record, or DefinitionError naming what is wrong — a record of another schema
    version names that version and the probe that rewrites it."""
    try:
        raw = persist.read_toml(file)
    except (OSError, ValueError) as exc:
        raise DefinitionError(file, [("", f"does not read: {exc}")]) from None
    if raw.get("schema") != SCHEMA:
        raise DefinitionError(file, [("schema", f"written with schema {raw.get('schema')!r}; this femkit reads "
                                                f"{SCHEMA}: rewrite it with `job probe --write` on that machine")])
    return load_toml(file, Record)


def write(file: Path, record: Record) -> Path:
    return persist.write_toml(file, record.data())


def sha256(file: Path) -> str | None:
    return hashlib.sha256(file.read_bytes()).hexdigest() if file.exists() else None


def listing() -> list[tuple[str, Path, Record | None, str]]:
    """Every record: (name, path, the record or None, why it does not load)."""
    out = []
    for file in sorted(machines_dir().glob("*.toml")) if machines_dir().is_dir() else []:
        try:
            out.append((file.stem, file, read(file), ""))
        except DefinitionError as exc:
            out.append((file.stem, file, None, exc.summary()))
    return out


def settings_now(config: settings.UserConfig) -> Settings:
    """This machine's settings as a record copies them (jobs.md § 9.1)."""
    return Settings(environments=str(settings.environments_root(config)),
                    mpi=list(config.launch.mpi) if config.launch.mpi else None,
                    preamble=list(config.activation.preamble) if config.activation.preamble is not None else None)


def stale(record: Record, config: settings.UserConfig) -> list[str]:
    """The settings a record of this machine no longer shares with its config.toml (jobs.md § 9.3)."""
    now = settings_now(config)
    return [f"{k}: recorded {getattr(record.settings, k)!r}, now {getattr(now, k)!r}"
            for k in Settings.model_fields if getattr(record.settings, k) != getattr(now, k)]


def status(file: Path, config: settings.UserConfig) -> tuple[str, str]:
    """A machine's record against this config.toml (jobs.md § 9.3): `absent`, `current`,
    `stale` or `does not load`, and the detail — what drifted, or what is wrong."""
    if not file.exists():
        return "absent", ""
    try:
        drift = stale(read(file), config)
    except DefinitionError as exc:
        return "does not load", exc.summary()
    return ("stale", "; ".join(drift)) if drift else ("current", "")


def unknowns(record: Record) -> list[tuple[str, str]]:
    """Every fact the record holds as unknown: (dotted part, why)."""
    found: list[tuple[str, str]] = []

    def walk(value: Any, where: str) -> None:
        if isinstance(value, dict):
            if set(value) == {"unknown"}:
                found.append((where, value["unknown"]))
                return
            for k, v in value.items():
                walk(v, f"{where}.{k}" if where else str(k))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{where}[{i}]")

    walk(record.data(), "")
    return found


def differences(old: Record, new: Record) -> list[str]:
    """What changed, part by part, leaving out when it was measured."""
    a, b = _flat(old.data()), _flat(new.data())
    skip = ("measured.", "sources.")
    return [f"{k}: {a.get(k, '(absent)')} -> {b.get(k, '(absent)')}"
            for k in sorted(set(a) | set(b)) if not k.startswith(skip) and a.get(k) != b.get(k)]


def _flat(value: Any, where: str = "") -> dict[str, Any]:
    if isinstance(value, dict) and value and set(value) != {"unknown"}:
        out: dict[str, Any] = {}
        for k, v in value.items():
            out.update(_flat(v, f"{where}.{k}" if where else str(k)))
        return out
    return {where: value}
