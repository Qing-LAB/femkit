"""`job probe`: measure the machine this runs on into a record (jobs.md § 9.1, § 9.2).

Every outside command runs through `core.process`;
one that is missing or fails makes the facts it measures unknown, with the reason —
never an exception, never a guess.
"""

from __future__ import annotations

import getpass
import os
import platform
import re
import shutil
import socket
from pathlib import Path
from typing import Any

from femkit.config import probe as config_probe
from femkit.config import settings
from femkit.core import clock, dirs, persist, process, view
from femkit.core.errors import Refusal, Unstated, UsageError
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.definitions.models import SchedulerKind
from femkit.envs.manager import confined, resolve
from femkit.envs.state import gpu, observe
from femkit import schedulers
from femkit.jobs.record import SCHEMA, Record, settings_now
from femkit.jobs.requests import JOB_PROBE

MEMINFO = Path("/proc/meminfo")


def unknown(reason: str) -> dict:
    return {"unknown": reason}


def declarations(pairs: list[str]) -> dict[str, str]:
    """`--set KEY=VALUE` -> {key: value}; the request's schema admits only where a scheduler
    command is (jobs.md § 9.2): a queue list typed on another machine is a guess."""
    return dict(pair.partition("=")[::2] for pair in pairs)


def scheduler_kind(ctx: Context, named: str | None, declared: dict[str, str]) -> tuple[str, SchedulerKind, str]:
    """The kind: named, or detected by its submit command (jobs.md § 9.2)."""
    kinds = catalogue.schedulers(ctx)
    if named is not None:
        if named not in kinds:
            raise UsageError(f"no scheduler kind {named!r}; kinds: {', '.join(sorted(kinds))}", code="no-such-kind",
                             subject=named)
        return named, kinds[named], "named by --scheduler"
    if declared:
        raise UsageError("--set declares a scheduler command; name its kind with --scheduler", code="unnamed",
                         subject="scheduler")
    name, why = config_probe.detect_scheduler(kinds)
    if name is None:
        raise Unstated(why, (view.command(JOB_PROBE,
                                         fills=[view.Fill(field="scheduler", label="the scheduler's kind", example="KIND")]),),
                      code="scheduler-unknown", subject="scheduler")
    return name, kinds[name], why


def locate(roles: dict[str, str], part: str, declared: dict[str, str], sources: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for role, command in roles.items():
        key = f"scheduler.{part}.{role}"
        if key in declared:
            out[role] = declared[key]
            sources[key] = "declared"
        else:
            found = shutil.which(command)
            out[role] = found or unknown(f"{command} not found on PATH")
    return out


def _memory() -> Any:
    """This machine's memory in MiB, from the kernel's MemTotal; unknown, with why, otherwise."""
    try:
        held = persist.read_text(MEMINFO)
    except OSError as exc:
        return unknown(f"{MEMINFO} does not read: {exc.strerror}")
    if held is None:
        return unknown(f"no {MEMINFO}")
    m = re.search(r"^MemTotal:\s+(\d+)\s+kB", held, re.M)
    return int(m.group(1)) // 1024 if m else unknown(f"{MEMINFO} has no MemTotal line in kB")


def _host() -> dict:
    found, why = config_probe.gpus()
    return {"os": f"{platform.system()} {platform.release()}", "architecture": platform.machine(),
            "cores": os.cpu_count() or unknown("os.cpu_count() gave nothing"), "memory_mib": _memory(),
            "gpus": unknown(why) if found is None else found}


def _manager(ctx: Context) -> dict:
    try:
        m = resolve(ctx)
    except Refusal as exc:
        why = unknown(str(exc))
        return {"kind": why, "path": why, "version": why, "root": why, "platform": why, "run_enters": why}

    def answer(found: tuple[Any, str | None]) -> Any:
        value, why = found
        return unknown(why) if why else value

    version = answer(m.version())
    root = answer(m.query(m.kind.root))
    plat = answer(m.query(m.kind.platform)) if m.kind.platform else \
        unknown(f"the {m.kind_name} kind declares no platform query")
    control = dirs.control_prefix()
    if not (control / "conda-meta").is_dir():
        enters: Any = unknown(f"no control environment at {control}")
    else:
        ran = process.run(m.in_prefix(control, ["python", "-c", "import sys; print(sys.prefix)"]),
                          env=confined(m.environment), timeout=120)  # as every command in a prefix runs (envs.md § 4.4)
        enters = ran.ok and Path(ran.stdout.strip().splitlines()[-1] if ran.stdout.strip() else "/").resolve() == control.resolve()
    return {"kind": m.kind_name, "path": str(m.path), "version": version, "root": root,
            "platform": plat, "run_enters": enters}


def _environments(ctx: Context) -> Any:
    try:
        out = {}
        for name in sorted(catalogue.load(ctx).environments):
            f, state = observe(ctx, name)
            out[name] = {"state": state.value, "gpu": gpu(ctx, f, state),
                         "install_fingerprint": f.manifest.install_fingerprint if f.manifest else None,
                         "solver_version": f.manifest.solver_version if f.manifest else None}
        return {k: {kk: vv for kk, vv in v.items() if vv is not None} for k, v in out.items()}
    except Refusal as exc:
        return unknown(f"env list could not run: {exc}")


def measure(ctx: Context, scheduler: str | None, declared: dict[str, str]) -> Record:
    """The record of this machine, as measured here now."""
    kind_name, kind, why = scheduler_kind(ctx, scheduler, declared)
    for key in declared:                      # a role is the kind's: a mistyped one is never dropped silently
        _, part, role = key.split(".")
        if role not in getattr(kind, part):
            raise UsageError(f"{key}: the {kind_name} kind has no {part} role {role!r}; "
                             f"it has {', '.join(getattr(kind, part)) or 'none'}", code="no-such-role", subject=key)
    sources: dict[str, str] = {"scheduler.kind": why, "host": f"platform, {MEMINFO}, {config_probe.GPU_QUERY[0]}",
                               "manager": "the manager kind's queries", "environments": "env list",
                               "settings": "config.toml"}
    commands = locate(kind.commands, "commands", declared, sources)
    probe_paths = locate(kind.probe, "probe", declared, sources)
    where = config_probe.where(kind, ctx.env)

    notes: list[str] = []
    if kind.commands:
        module = schedulers.readers(kind_name)
        if module is None:
            found = {"identity": unknown(f"femkit has no readers for {kind_name}"),
                     "partitions": unknown(f"femkit has no readers for {kind_name}"),
                     "queues": unknown(f"femkit has no readers for {kind_name}"), "notes": [], "sources": {}}
        else:
            found = module.probe(probe_paths, getpass.getuser())
        identity, partitions, queues = found["identity"], found["partitions"], found["queues"]
        notes += found["notes"]
        sources.update(found["sources"])
    else:
        identity, partitions, queues = socket.gethostname(), {}, []
        sources["identity"] = "the host name"

    data = {
        "schema": SCHEMA,
        "measured": {"time": clock.stamp(ctx.now()), "where": where},
        "identity": identity,
        "host": _host(),
        "manager": _manager(ctx),
        "scheduler": {"kind": kind_name, "commands": commands, "probe": probe_paths},
        "partitions": partitions,
        "queues": queues,
        "environments": _environments(ctx),
        "settings": settings_now(settings.load(ctx).config).model_dump(exclude_none=True),
        "sources": sources,
        "notes": notes,
    }
    return Record.model_validate(data)
