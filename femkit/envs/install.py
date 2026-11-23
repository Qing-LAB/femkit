"""The install step machine (envs.md § 4).

`plan_steps` lists every step with its command; `STEP_KINDS` runs one step of
each kind. The CMake framework options are femkit's own (definitions.md § 4.2: not
declarable).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from femkit.config import settings
from femkit.core import paths, process, text
from femkit.core.operations import Context, Step
from femkit.core.persist import atomic_write_text, write_json
from femkit.core.schema import render
from femkit.definitions import catalogue
from femkit.definitions.models import FRAMEWORK_OPTIONS, Build, EnvironmentDefinition
from femkit import engines
from femkit.envs import layout, manager, toolchain
from femkit.envs.manager import Manager, resolve
from femkit.envs.records import Manifest

Say = Callable[[str], None]  # hears what a step reports while it runs

COMPILER_KEYS = ("CMAKE_C_COMPILER", "CMAKE_CXX_COMPILER", "CMAKE_Fortran_COMPILER", "CMAKE_CUDA_COMPILER",
                 "CMAKE_CUDA_HOST_COMPILER")


@dataclass(frozen=True)
class Target:
    """Everything a step of one environment's install reads."""

    name: str
    env: EnvironmentDefinition
    prefix: Path
    manager: Manager
    channels: list[str]
    python_minor: str
    cuda_architectures: list[str] | None
    jobs: int
    install_fingerprint: str
    launcher: list[str] | None = None        # launch.mpi: the toolchain check's MPI runs with it

    def source_dir(self, source_id: str) -> Path:
        return layout.source_dir(self.prefix, self.env, source_id)

    def build_dir(self, build_id: str) -> Path:
        return layout.build_dir(self.prefix, build_id)

    @property
    def lock(self) -> Path:
        return layout.lock_file(self.name, self.install_fingerprint)


def target(ctx: Context, name: str, install_fingerprint: str) -> Target:
    from femkit.envs.state import definition
    cat = catalogue.load(ctx, engines=engines.registered())
    config = settings.load(ctx).config
    return Target(
        name=name, env=definition(ctx, name), prefix=layout.prefix(ctx, name), manager=resolve(ctx),
        channels=cat.control.channels, python_minor=cat.control.python_minor,
        cuda_architectures=config.build.cuda_architectures, jobs=config.build.jobs or len(os.sched_getaffinity(0)),  # config.md § 3.1
        install_fingerprint=install_fingerprint,
        launcher=config.launch.mpi,
    )


# ------------------------------------------------------------------ CMake

def cmake_options(t: Target, build: Build) -> list[tuple[str, str, str]]:
    """(key, type, value): the framework's options, then the declared ones (definitions.md § 4.2)."""
    p = str(t.prefix)
    options = [
        ("CMAKE_BUILD_TYPE", "STRING", "Release"),
        ("BUILD_TESTING", "BOOL", "ON"),
        ("CMAKE_INSTALL_PREFIX", "PATH", p),
        ("CMAKE_PREFIX_PATH", "PATH", p),
        ("CMAKE_FIND_ROOT_PATH", "PATH", p),
        ("CMAKE_FIND_ROOT_PATH_MODE_PACKAGE", "STRING", "ONLY"),
        ("CMAKE_FIND_ROOT_PATH_MODE_LIBRARY", "STRING", "ONLY"),
        ("CMAKE_FIND_ROOT_PATH_MODE_INCLUDE", "STRING", "ONLY"),
        ("CMAKE_FIND_ROOT_PATH_MODE_PROGRAM", "STRING", "ONLY"),
        ("CMAKE_FIND_USE_PACKAGE_REGISTRY", "BOOL", "OFF"),
        ("CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY", "BOOL", "OFF"),
        ("CMAKE_INSTALL_RPATH_USE_LINK_PATH", "BOOL", "ON"),
        ("CMAKE_INSTALL_RPATH", "STRING", ";".join(str(t.prefix / r) for r in build.rpath)),
    ]
    if build.cuda_architectures:
        options.append(("CMAKE_CUDA_ARCHITECTURES", "STRING", ";".join(t.cuda_architectures or [])))
    assert {k for k, _, _ in options} <= FRAMEWORK_OPTIONS, "a framework option missing from FRAMEWORK_OPTIONS"
    values = {"prefix": p}
    values.update({f"source:{s.id}": str(t.source_dir(s.id)) for s in t.env.sources})
    values.update({f"build:{b.id}": str(t.build_dir(b.id)) for b in t.env.builds})
    for key, value in build.options.items():
        if isinstance(value, bool):
            options.append((key, "BOOL", "ON" if value else "OFF"))
        else:
            options.append((key, "STRING", render(str(value), values)))
    return options


def configure_argv(t: Target, build: Build) -> list[str]:
    defs = [f"-D{k}:{kind}={v}" for k, kind, v in cmake_options(t, build)]
    # No generator is named: each project builds with CMake's own default, as it builds itself (ADR 0007).
    return ["cmake", "-S", str(t.source_dir(build.source)), "-B", str(t.build_dir(build.id)), *defs]


def _cache(build_dir: Path) -> dict[str, str]:
    out = {}
    for line in (build_dir / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace").splitlines():
        if line and not line.startswith(("#", "//")) and ":" in line and "=" in line:
            key, _, rest = line.partition(":")
            out[key] = rest.partition("=")[2]
    return out


# ------------------------------------------------------------------ the plan

def _order_builds(builds: list[Build]) -> list[Build]:
    """Each build after those its `after` names, otherwise as declared."""
    done: list[Build] = []
    pending = list(builds)
    while pending:
        ready = [b for b in pending if all(a in {d.id for d in done} for a in b.after)]
        if not ready:  # loading refuses this (definitions.md § 2.2); never loop on it
            raise ValueError(f"builds waiting on builds this environment does not have: "
                             f"{', '.join(f'{b.id} after {b.after}' for b in pending)}")
        done += ready
        pending = [b for b in pending if b not in ready]
    return done


def plan_steps(t: Target, *, remove_first: bool, discard_lock: bool) -> list[Step]:
    m, p = t.manager, t.prefix
    steps: list[Step] = []
    if remove_first:
        steps.append(Step(id="remove", describe=f"remove {text.path(p)}", argv=tuple(m.argv(m.kind.remove, prefix=str(p)))))
    if discard_lock:
        steps.append(Step(id="discard-lock", describe=f"discard the saved lock {text.path(t.lock)}"))
    if t.lock.exists() and not discard_lock:
        create = m.argv(m.kind.create_from_lock, prefix=str(p), file=str(t.lock))
        how = "from the saved lock"
    else:
        create = m.create(p, t.channels, [*t.env.packages.conda, f"python={t.python_minor}"])
        how = "from the declared constraints"
    steps.append(Step(id="create", describe=f"create {text.path(p)} {how}", argv=tuple(create)))
    steps.append(Step(id="lock", describe=f"save the exact package list to {text.path(t.lock)}",
                      argv=tuple(m.argv(m.kind.export_lock, prefix=str(p)))))
    steps.append(Step(id="forbid", describe=f"refuse a lock holding {', '.join(t.env.packages.forbid) or 'nothing forbidden'}"))
    if t.env.proven_toolchain:  # before any source is fetched (envs.md § 4.1)
        steps.append(Step(id="toolchain", describe=toolchain.describe(t.env.proven_toolchain)))
    for s in t.env.sources:
        steps.append(Step(id=f"fetch:{s.id}", describe=f"download {s.id} {s.release} and verify its SHA-256"))
    for s in sorted(t.env.sources, key=lambda s: len(PurePosixPath(s.into).parts)):
        steps.append(Step(id=f"unpack:{s.id}", describe=f"unpack {s.id} into {text.path(t.source_dir(s.id))}"))
    for b in _order_builds(t.env.builds):
        steps.append(Step(id=f"configure:{b.id}", describe=f"configure {b.id}",
                          argv=tuple(m.in_prefix(p, configure_argv(t, b)))))
        steps.append(Step(id=f"compile:{b.id}", describe=f"compile {b.id} with {text.count(t.jobs, 'job')}",
                          argv=tuple(m.in_prefix(p, ["cmake", "--build", str(t.build_dir(b.id)), "--parallel", str(t.jobs)]))))
        steps.append(Step(id=f"install:{b.id}", describe=f"install {b.id} into {text.path(p)}",
                          argv=tuple(m.in_prefix(p, ["cmake", "--install", str(t.build_dir(b.id))]))))
    steps.append(Step(id="audit", describe="find every provided executable and module inside the prefix"))
    steps.append(Step(id="manifest", describe="probe the solver version and write the manifest"))
    return steps


# ------------------------------------------------------------------ the steps

KILLED = "killed"
SIGKILL_CODES = (-9, 137)  # killed by SIGKILL: directly, or as a shell reports it


def _ended(result: process.ProcessResult, log: Path) -> str:
    """What a step's command ending means: done, failed, or `killed` — ended by SIGKILL, on a
    cluster most often a login node's memory limit (envs.md § 6.2)."""
    if result.ok:
        return "done"
    if result.returncode in SIGKILL_CODES:
        _note(log, f"killed (exit {result.returncode}): SIGKILL, most often a memory limit")
        return KILLED
    return "failed"


def _run(t: Target, step: Step, log: Path, *, inside: bool = False) -> str:
    """A step's command. ``inside``: it runs inside the prefix, from the confined variables
    (envs.md § 4.4); the manager's own commands keep the invocation's."""
    env = manager.confined(t.manager.environment) if inside else t.manager.environment
    return _ended(process.run(step.argv, log=log, env=env), log)


def _note(log: Path, text: str) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def step_remove(t: Target, step: Step, log: Path, say: Say) -> str:
    return _run(t, step, log)


def step_discard_lock(t: Target, step: Step, log: Path, say: Say) -> str:
    t.lock.unlink(missing_ok=True)
    return "done"


def step_create(t: Target, step: Step, log: Path, say: Say) -> str:
    return _run(t, step, log)


def step_lock(t: Target, step: Step, log: Path, say: Say) -> str:
    result = process.run(step.argv, env=t.manager.environment)
    _note(log, result.stdout + result.stderr)
    if not result.ok:
        return _ended(result, log)
    lock = explicit(result.stdout)
    if lock == EXPLICIT:
        _note(log, "the package list holds no package URL")
        return "failed"
    atomic_write_text(t.lock, lock)
    return "done"


EXPLICIT = "@EXPLICIT\n"


def explicit(listing: str) -> str:
    """The exact package list as every manager's `create --file` reads it: `@EXPLICIT`, then one
    URL a line (envs.md § 4.1). The manager's own header goes: mamba 2's is not a comment, and its
    create reads it as a constraint and fails (measured, 2.9.0)."""
    urls = [line.strip() for line in listing.splitlines() if line.strip().startswith(("https://", "http://", "file://"))]
    return EXPLICIT + "".join(f"{u}\n" for u in urls)


def locked(lock_text: str) -> set[str]:
    """The package names in an explicit lock: each URL's file is `name-version-build.ext`."""
    names = set()
    for line in lock_text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("@") and "/" in line:
            file = PurePosixPath(urllib.parse.urlsplit(line).path).name
            names.add(file.removesuffix(".conda").removesuffix(".tar.bz2").rsplit("-", 2)[0].lower())
    return names


def step_forbid(t: Target, step: Step, log: Path, say: Say) -> str:
    names = locked(t.lock.read_text(encoding="utf-8"))
    hits = [f for f in t.env.packages.forbid
            if any(n == f.lower() or n.startswith(f.lower() + "-") for n in names)]
    for family in hits:
        _note(log, f"forbidden package family in the lock: {family}")
    return "failed" if hits else "done"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def step_toolchain(t: Target, step: Step, log: Path, say: Say) -> str:
    """Prove the toolchain inside the prefix before any source is fetched (envs.md § 4.1): the
    program measures, `envs/toolchain.py` judges, and each finding is said and logged."""
    work = layout.toolchain_dir(t.prefix)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    spec = write_json(work / "spec.json", toolchain.spec(t.env.proven_toolchain, t.launcher))
    report, result = toolchain.run(t.manager, t.prefix, "check", str(spec), str(work))
    _note(log, result.stdout + result.stderr)
    if report is None:
        if _ended(result, log) == KILLED:
            return KILLED
        _note(log, "the toolchain program gave no report")
        say("the toolchain program gave no report; see the log")
        return "failed"
    verdict = toolchain.judge(report, t.prefix)
    for line in verdict.lines + [f"x {p}" for p in verdict.problems]:
        _note(log, line)
        say(line)
    return "failed" if verdict.problems else "done"


def step_fetch(t: Target, step: Step, log: Path, say: Say) -> str:
    source = next(s for s in t.env.sources if s.id == step.id.split(":", 1)[1])
    target_file = layout.archive_cache(source.sha256)
    if target_file.exists() and _sha256(target_file) == source.sha256:
        _note(log, f"cached: {target_file}")
        return "done"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target_file.name}.", dir=target_file.parent)
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(source.archive, timeout=120) as response:
            shutil.copyfileobj(response, out, length=1 << 20)
        got = _sha256(Path(tmp))
        if got != source.sha256:
            _note(log, f"{source.archive}: SHA-256 {got}, expected {source.sha256}")
            return "failed"
        os.replace(tmp, target_file)
    finally:
        Path(tmp).unlink(missing_ok=True)
    _note(log, f"downloaded {source.archive} -> {target_file}")
    return "done"


def step_unpack(t: Target, step: Step, log: Path, say: Say) -> str:
    source = next(s for s in t.env.sources if s.id == step.id.split(":", 1)[1])
    destination = t.source_dir(source.id)
    if destination.exists():
        if any(destination.iterdir()):
            _note(log, f"{destination} already holds files")
            return "failed"
        destination.rmdir()  # an empty placeholder, as a parent's submodule folder
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as scratch, \
            tarfile.open(layout.archive_cache(source.sha256), "r:gz") as bundle:
        bundle.extractall(scratch, filter="data")
        roots = list(Path(scratch).iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            _note(log, "the archive does not hold exactly one top folder")
            return "failed"
        roots[0].rename(destination)
    if source.version_text is not None:
        atomic_write_text(destination / "version.txt", source.version_text + "\n")
    _note(log, f"unpacked {source.id} into {destination}")
    return "done"


UNUSED = "Manually-specified variables were not used by the project:"  # CMake's own report


def unused_options(configure_log: str) -> set[str]:
    """The variables a configure was given and never read, as CMake lists them."""
    names, listing, seen = set(), False, False
    for line in configure_log.splitlines():
        if UNUSED in line:
            listing, seen = True, False
        elif listing and line.strip():
            names.add(line.strip())
            seen = True
        elif listing and seen:
            listing = False
    return names


def step_configure(t: Target, step: Step, log: Path, say: Say) -> str:
    if (outcome := _run(t, step, log, inside=True)) != "done":
        return outcome
    build = next(b for b in t.env.builds if b.id == step.id.split(":", 1)[1])
    cache = _cache(t.build_dir(build.id))
    unread = sorted(set(build.options) & unused_options(log.read_text(encoding="utf-8", errors="replace")))
    missing = [k for k in build.options if k not in cache]
    outside = [f"{k}={cache[k]}" for k in COMPILER_KEYS
               if Path(cache.get(k, "")).is_absolute()  # NOTFOUND and empty values name no compiler
               and not paths.inside(cache[k], t.prefix)]
    for k in unread:
        _note(log, f"declared option {k} was never read by the project: misspelt, or dead where it is declared")
    for k in missing:
        _note(log, f"declared option {k} is not in CMakeCache.txt: the project removed it")
    for k in outside:
        _note(log, f"compiler outside the prefix: {k}")
    return "failed" if unread or missing or outside else "done"


def step_compile(t: Target, step: Step, log: Path, say: Say) -> str:
    return _run(t, step, log, inside=True)


def step_install(t: Target, step: Step, log: Path, say: Say) -> str:
    return _run(t, step, log, inside=True)


_AUDIT = """import importlib, json, os, shutil, sys
modules, variables = json.loads(sys.argv[1]), json.loads(sys.argv[2])
origins = {}
for m in modules:
    try:
        origins[m] = getattr(importlib.import_module(m), "__file__", None)
    except Exception:
        origins[m] = None
compilers = {v: shutil.which(os.environ[v]) if os.environ.get(v) else None for v in variables}
print(json.dumps({"modules": origins, "compilers": compilers}))
"""


def step_audit(t: Target, step: Step, log: Path, say: Say) -> str:
    """Every provided executable and module, and the compilers, found inside the prefix (envs.md § 4.1)."""
    inside = lambda path: paths.inside(path, t.prefix)  # noqa: E731
    proven = t.env.proven_toolchain
    problems = [f"executable not in the prefix: {e}" for e in t.env.provides.executables
                if not (t.prefix / "bin" / e).exists()]
    result = process.run(t.manager.in_prefix(t.prefix, [
        "python", "-c", _AUDIT, json.dumps(t.env.provides.modules),
        json.dumps(list(proven.compilers.values()) if proven else [])]),
        env=manager.confined(t.manager.environment), timeout=300)
    _note(log, result.stdout + result.stderr)
    if not result.ok:
        return _ended(result, log)
    found = json.loads(result.stdout.strip().splitlines()[-1])
    problems += [f"module not found inside the prefix: {m} ({o})" for m, o in found["modules"].items() if not inside(o)]
    if proven:
        problems += [f"compiler ${v} does not resolve inside the prefix: {c}" for v, c in found["compilers"].items()
                     if not inside(c)]
    for p in problems:
        _note(log, p)
    return "failed" if problems else "done"


def step_manifest(t: Target, step: Step, log: Path, say: Say) -> str:
    engine = engines.module(t.env.engine)
    result = process.run(t.manager.in_prefix(t.prefix, engine.VERSION_COMMAND), env=manager.confined(t.manager.environment),
                         timeout=120)
    _note(log, result.stdout + result.stderr)
    if _ended(result, log) == KILLED:
        return KILLED
    version = engine.read_version(result.stdout, result.stderr)
    if version != t.env.version:
        _note(log, f"the version probe reported {version!r}; the definition requires {t.env.version!r}")
        return "failed"
    manager_version = process.run(t.manager.argv(t.manager.kind.version), env=t.manager.environment, timeout=60)
    found = re.search(t.manager.kind.version_pattern, manager_version.stdout + manager_version.stderr)
    write_json(layout.manifest_file(t.prefix), Manifest(
        install_fingerprint=t.install_fingerprint, lock_sha256=_sha256(t.lock), manager_kind=t.manager.kind_name,
        manager_version=found.group(1) if found else "unknown", solver_version=version,
        time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ).model_dump())
    return "done"


STEP_KINDS: dict[str, Callable[[Target, Step, Path, Say], str]] = {
    "remove": step_remove, "discard-lock": step_discard_lock, "create": step_create, "lock": step_lock,
    "forbid": step_forbid, "toolchain": step_toolchain, "fetch": step_fetch, "unpack": step_unpack,
    "configure": step_configure, "compile": step_compile, "install": step_install, "audit": step_audit,
    "manifest": step_manifest,
}


def run_step(t: Target, step: Step, where: Path, say: Say = lambda line: None) -> tuple[str, Path]:
    """The one door every install step goes through; ``say`` hears what a step reports as it
    runs. A file, network or archive error is the step's failure, said in its log; anything
    else is a defect and propagates."""
    log = where / f"{step.id.replace(':', '-')}.log"
    try:
        return STEP_KINDS[step.id.split(":", 1)[0]](t, step, log, say), log
    except (OSError, tarfile.TarError, urllib.error.URLError) as exc:
        _note(log, f"{type(exc).__name__}: {exc}")
        return "failed", log
