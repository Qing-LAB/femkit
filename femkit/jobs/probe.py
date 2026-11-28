"""`job probe`: measure the machine this runs on into a record (jobs.md § 9.1, § 9.2).

Every outside command runs through `core.process`, one in an environment through its one door;
one that is missing or fails makes the facts it measures unknown, with the reason —
never an exception, never a guess.
"""

from __future__ import annotations

import getpass
import os
import platform
import re
import shlex
import shutil
from pathlib import Path
from typing import Any

from femkit.config import probe as config_probe
from femkit.config import settings
from femkit.core import clock, dirs, persist, view
from femkit.core.errors import Refusal, Unstated, UsageError
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.definitions.models import SchedulerKind
from femkit.envs import inside
from femkit.envs.manager import made, resolve
from femkit.envs.state import gpu, observe
from femkit import schedulers
from femkit.jobs.record import SCHEMA, Record, host_identity, settings_now
from femkit.jobs.requests import JOB_PROBE

MEMINFO = Path("/proc/meminfo")
ENTERS = "enters"   # the program that says which prefix the manager's `run` enters, by its name in programs.toml


def unknown(reason: str) -> dict:
    return {"unknown": reason}


def declarations(pairs: list[str]) -> dict[str, str]:
    """`--set KEY=VALUE` -> {key: value}; the request's schema admits only where a scheduler
    command is (jobs.md § 9.2): a queue list typed on another machine is a guess."""
    return dict(pair.partition("=")[::2] for pair in pairs)


SCHEDULER = "scheduler"   # the record's part whose command paths `--set` declares (jobs.md § 9.2)


def scheduler_kind(ctx: Context, named: str | None, declared: dict[str, str]) -> tuple[str, SchedulerKind, str]:
    """The kind: named, or detected by its submit command, found or declared (jobs.md § 9.2)."""
    kinds = catalogue.schedulers(ctx)
    if named is not None:
        if named not in kinds:
            raise UsageError(f"no scheduler kind `{named}`; kinds: {', '.join(sorted(kinds))}", code="no-such-kind",
                             subject=named)
        return named, kinds[named], "named by --scheduler"
    name, why = config_probe.detect_scheduler(kinds, submit_declared=f"{SCHEDULER}.commands.submit" in declared)
    if name is None:
        raise Unstated(why, (view.command(JOB_PROBE, note=f"one of: {', '.join(sorted(kinds))}",
                                         fills=[view.Fill(field="scheduler", label="the scheduler's kind")]),),
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
    return {"kind": m.kind_name, "path": str(m.path), "version": version, "root": root,
            "platform": plat, "run_enters": _run_enters(ctx, m)}


def _run_enters(ctx: Context, m) -> Any:
    """Whether `<manager> run -n femkit` runs inside the prefix the manager lists for the control
    environment here (jobs.md § 9.1): true or false only when it ran and said which prefix it ran in;
    unknown, with why, otherwise. The program that says so is declared, `enters`, and runs through the
    one door into the control environment, as every command in an environment runs (envs.md § 4.4)."""
    try:
        there = inside.entered(ctx, dirs.CONTROL)
    except Refusal as exc:
        return unknown(str(exc))
    control = there.prefix
    if control is None or not made(control, catalogue.managers(ctx)):
        return unknown(f"the manager lists no control environment, {there.managed}")
    declared = inside.program(ctx, ENTERS)
    argv = there.program(declared)
    ran = there.run(argv, declared=declared)
    said = ran.stdout.strip().splitlines()
    if not ran.ok:
        how = "did not end in time" if ran.timed_out else f"failed (exit {ran.returncode})"
        first = (ran.stderr or ran.stdout).strip().splitlines()
        return unknown(f"`{shlex.join(argv[1:])}` {how}" + (f": {first[0][:200]}" if first else ""))
    if not said:
        return unknown(f"`{shlex.join(argv[1:])}` printed no prefix")
    return Path(said[-1]).resolve() == control.resolve()


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
            raise UsageError(f"{key}: the {kind_name} kind has no {part} role `{role}`; "
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
            found = module.probe(probe_paths, getpass.getuser(), catalogue.units(ctx))
        identity, partitions, queues = found["identity"], found["partitions"], found["queues"]
        notes += found["notes"]
        sources.update(found["sources"])
    else:
        identity, partitions, queues = host_identity(), {}, []
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
