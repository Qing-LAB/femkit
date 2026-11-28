"""The install step machine (envs.md § 4).

`plan_steps` lists every step with its command; `STEP_KINDS` runs one step of
each kind. The CMake framework options are femkit's own (definitions.md § 4.2: not
declarable).
"""

from __future__ import annotations

import tarfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from datetime import datetime
from typing import Callable, Mapping

from femkit.config import settings
from femkit.core import clock, paths, persist, process, text
from femkit.core.errors import Refused
from femkit.core.eventlog import StepOutcome
from femkit.core.issues import Issue
from femkit.core.operations import Context, Step
from femkit.core.persist import atomic_write_text, read_record, write_json
from femkit.core.schema import render
from femkit.definitions import catalogue
from femkit.definitions.models import FRAMEWORK_OPTIONS, Build, EnvironmentDefinition
from femkit.definitions.programs import Program
from femkit import engines
from femkit.engines import audit
from femkit.envs import layout, toolchain
from femkit.envs.inside import Inside
from femkit.envs.manager import Manager, resolve
from femkit.envs.records import Manifest

#: The time limit of an environment's version command, in seconds (envs.md § 4.1: a quick step): the
#: limit femkit has kept for it, not measured.
VERSION_TIMEOUT = 120

Say = Callable[[str], None]  # hears what a step reports while it runs
#: femkit's programs an install runs inside the prefix, by their names in programs.toml (envs.md § 4.4).
AUDIT, TOOLCHAIN = "audit", "toolchain"

COMPILER_KEYS = ("CMAKE_C_COMPILER", "CMAKE_CXX_COMPILER", "CMAKE_Fortran_COMPILER", "CMAKE_CUDA_COMPILER",
                 "CMAKE_CUDA_HOST_COMPILER")


@dataclass(frozen=True)
class Target:
    """Everything a step of one environment's install reads."""

    name: str
    managed: str                              # its name with the manager, by which every command names it (envs.md § 1)
    env: EnvironmentDefinition
    prefix: Path | None                       # as the manager lists it (envs.md § 1); none before its create
    manager: Manager
    channels: list[str]
    python_minor: str
    cuda_architectures: list[str] | None
    jobs: int
    install_fingerprint: str
    programs: Mapping[str, Program]           # femkit's programs an install runs inside the prefix (envs.md § 4.4)
    launcher: list[str] | None = None        # launch.mpi: the toolchain check's MPI runs with it
    now: Callable[[], datetime] = clock.now   # the invocation's clock (core.md § 6): what the manifest is stamped with
    projects: list[str] = field(default_factory=list)   # the packages the projects declare, beside its own (envs.md § 4.3)
    lacking: list[str] = field(default_factory=list)    # of them, those its manifest does not record (envs.md § 4.1)
    settings: dict[str, list[str]] | None = None        # the person's settings its commands set aside, each with where
                                                        # the manager read it; none where they cannot be read (§ 4.4)

    @property
    def at(self) -> Path:
        """Its prefix: as the manager lists it, or — in a plan made before the environment exists —
        `<prefix of femkit-NAME>`, which each step that needs it runs with the listed one in place
        of (`rendered`, envs.md § 4.1)."""
        return self.prefix if self.prefix is not None else layout.unmade(self.managed)

    @property
    def inside(self) -> Inside:
        """The environment, entered through the one door (envs.md § 4.4): every step that runs in it."""
        return Inside(self.name, self.managed, self.prefix, self.manager)

    def source_dir(self, source_id: str) -> Path:
        return layout.source_dir(self.at, self.env, source_id)

    def build_dir(self, build_id: str) -> Path:
        return layout.build_dir(self.at, build_id)

    @property
    def lock(self) -> Path:
        return layout.lock_file(self.name, self.install_fingerprint)


def target(ctx: Context, name: str) -> Target:
    """An install of ``name`` by the manager the invocation names, fingerprinted as that manager
    builds it — what its manifest records — at the prefix the manager lists for it now (envs.md § 1)."""
    from femkit.envs.state import added, definition, install_fingerprint, lacking
    control = catalogue.control(ctx)
    config = settings.load(ctx).config
    m = resolve(ctx)
    managed = catalogue.managed(ctx, name)
    where = m.prefix(managed)
    found = m.settings()
    return Target(
        name=name, managed=managed, env=definition(ctx, name), prefix=where, manager=m,
        channels=control.channels, python_minor=control.python_minor,
        cuda_architectures=config.build.cuda_architectures, jobs=settings.build_jobs(config),
        install_fingerprint=install_fingerprint(ctx, name, m.kind_name), programs=catalogue.programs(ctx),
        launcher=config.launch.mpi, now=ctx.now, projects=added(ctx, name),
        lacking=lacking(ctx, name, read_record(layout.manifest_file(where), Manifest).value if where else None),
        settings=found.neutralised if found.read else None,
    )


def refuse_settings(t: Target) -> None:
    """Refused before any create or delivery, while a setting of the person's that nothing the
    manager's commands carry sets aside is set so (envs.md § 4.4): each named, with the file the
    manager read it from and what to change there."""
    refused = t.manager.settings().refused
    if not refused:
        return
    issues = [Issue(severity="error", code="setting-refused", subject=r.source, file=r.source,
                    message=f"your setting {r.key} ({persist.inline_text(r.value)}), in {r.source}: {r.change}")
              for r in refused]
    raise Refused(f"{t.managed} is not made while your own settings would change what goes into it: "
                  f"{', '.join(f'{r.key} in {r.source}' for r in refused)}", code="setting-refused",
                  subject=refused[0].source, issues=issues)


# ------------------------------------------------------------------ CMake

def cmake_options(t: Target, build: Build) -> list[tuple[str, str, str]]:
    """(key, type, value): the framework's options, then the declared ones (definitions.md § 4.2)."""
    p = str(t.at)
    framework = {"prefix": p, "rpath": ";".join(str(t.at / r) for r in build.rpath),
                 "cuda_architectures": ";".join(t.cuda_architectures or [])}
    options = [(k, o.type, render(o.value, framework)) for k, o in FRAMEWORK_OPTIONS.items()
               if o is not None and (build.cuda_architectures or not o.cuda)]
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


def _text(file: Path) -> str | None:
    """What a build tool or a step's command wrote, as text — any byte that is not UTF-8
    replaced, never refused; None when the file is not there."""
    held = persist.read_bytes(file)
    return None if held is None else held.decode("utf-8", errors="replace")


def _cache(build_dir: Path) -> dict[str, str] | None:
    """The entries of a build's CMakeCache.txt; None when configure wrote none."""
    written = _text(build_dir / "CMakeCache.txt")
    if written is None:
        return None
    out = {}
    for line in written.splitlines():
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
    m, p = t.manager, t.at
    steps: list[Step] = []
    if remove_first:
        steps.append(Step(id="remove", describe=f"remove {t.managed}, at {text.path(p)}",
                          argv=tuple(m.remove(t.managed, t.channels))))
    if discard_lock:
        steps.append(Step(id="discard-lock", describe=f"discard the saved lock {text.path(t.lock)}"))
    from_lock = t.lock.exists() and not discard_lock
    if from_lock:
        create = m.create_from_lock(t.managed, t.lock, t.channels)
        how = "from the saved lock"
    else:
        # every environment that holds Python holds the minor control.txt names: femkit's own programs
        # run in an engine's prefix and in the mesh step's alike. One that takes the control
        # environment's packages has that line already; a tool that provides no Python gets none
        # (definitions.md §§ 3, 4.7). The install fingerprint holds both facts (envs.md § 2); the
        # packages the projects declare are solved with its own, outside it (definitions.md § 4.7).
        python = [f"python={t.python_minor}"] if t.env.holds_python and not t.env.control_packages else []
        create = m.create(t.managed, t.channels, [*t.env.packages.conda, *t.projects, *python])
        how = "from the declared constraints"
    steps.append(Step(id="create", describe=f"create {t.managed}, where the manager keeps environments, {how}",
                      argv=tuple(create)))
    if from_lock and t.projects:      # a lock saved before a project declared a package may lack it
        steps.append(_deliver(t, t.projects))
    steps.append(_lock(t))
    steps.append(Step(id="forbid", describe=f"refuse a lock holding {', '.join(t.env.packages.forbid) or 'nothing forbidden'}"))
    if t.env.proven_toolchain:  # before any source is fetched (envs.md § 4.1)
        steps.append(Step(id="toolchain", describe=toolchain.describe(t.env.proven_toolchain)))
    for s in t.env.sources:
        steps.append(Step(id=f"fetch:{s.id}", describe=f"download {s.id} {s.release} and verify its SHA-256"))
    for s in sorted(t.env.sources, key=lambda s: len(PurePosixPath(s.into).parts)):
        steps.append(Step(id=f"unpack:{s.id}", describe=f"unpack {s.id} into {text.path(t.source_dir(s.id))}"))
    inside = t.inside
    for b in _order_builds(t.env.builds):
        steps.append(Step(id=f"configure:{b.id}", describe=f"configure {b.id}",
                          argv=tuple(inside.argv(configure_argv(t, b)))))
        steps.append(Step(id=f"compile:{b.id}", describe=f"compile {b.id} with {text.count(t.jobs, 'job')}",
                          argv=tuple(inside.argv(["cmake", "--build", str(t.build_dir(b.id)), "--parallel", str(t.jobs)]))))
        steps.append(Step(id=f"install:{b.id}", describe=f"install {b.id} into {text.path(p)}",
                          argv=tuple(inside.argv(["cmake", "--install", str(t.build_dir(b.id))]))))
    proven = t.env.proven_toolchain
    found = (inside.program(t.programs[AUDIT], *audit.arguments(
        t.env.provides.modules, list(proven.compilers.values()) if proven else []))
        if t.env.provides.modules or proven else None)      # nothing for Python to find: no command
    steps.append(Step(id="audit", describe="find every provided executable and module inside the prefix",
                      argv=tuple(found) if found else None))
    steps.append(Step(id="manifest", describe="probe the version and write the manifest"))
    return steps


def _deliver(t: Target, packages: list[str]) -> Step:
    """The step that installs ``packages``, the projects', into the prefix as it stands (envs.md § 4.1)."""
    return Step(id="deliver", describe=f"install what the projects declare into {t.managed}: "
                                       f"{' '.join(packages)}",
                argv=tuple(t.manager.install(t.managed, t.channels, packages)))


def _lock(t: Target) -> Step:
    return Step(id="lock", describe=f"save the exact package list to {text.path(t.lock)}",
                argv=tuple(t.manager.export_lock(t.managed)))


def deliver_steps(t: Target) -> list[Step]:
    """What delivers into an installed environment, as it stands, the packages the projects declare
    that its manifest does not record (envs.md §§ 3.3, 4.1): installed into its prefix, its lock
    saved again, its manifest written again recording them — never a removal or a create."""
    return [_deliver(t, t.lacking), _lock(t), Step(id="manifest", describe="probe the version and write the manifest")]


# ------------------------------------------------------------------ the steps

KILLED: StepOutcome = "killed"
SIGKILL_CODES = (-9, 137)  # killed by SIGKILL: directly, or as a shell reports it


#: What a compiler driver prints when a compiler it started is ended by SIGKILL, each as measured on
#: a cluster (envs.md § 6.2): GCC's — `x86_64-conda-linux-gnu-gfortran: fatal error: Killed signal
#: terminated program f951` — and NVCC's — `nvcc error   : 'cudafe++' died due to signal 9 (Kill
#: signal)`. The build tool then exits with its own code; only the log tells.
COMPILER_KILLED = ("Killed signal terminated program", "died due to signal 9 (Kill signal)")


def _compiler_killed(log: Path) -> str | None:
    """The line of ``log`` that says a compiler was ended by SIGKILL, if one does."""
    lines = (_text(log) or "").splitlines()   # no log: no line says so
    return next((line.strip() for line in lines if any(k in line for k in COMPILER_KILLED)), None)


def _ended(result: process.ProcessResult, log: Path) -> str:
    """What a step's command ending means: done, failed, or `killed` — it, or a compiler under
    it, ended by SIGKILL, on a cluster most often a login node's limits (envs.md § 6.2)."""
    if result.ok:
        return "done"
    if result.returncode in SIGKILL_CODES:
        _note(log, f"killed (exit {result.returncode}): SIGKILL, most often a memory limit")
        return KILLED
    if line := _compiler_killed(log):
        _note(log, f"killed: a compiler under the build tool was ended by SIGKILL, most often a memory limit: {line}")
        return KILLED
    return "failed"


def _run(t: Target, step: Step, log: Path, *, inside: bool = False) -> str:
    """A step's command. ``inside``: it runs inside the environment, through the one door (envs.md
    § 4.4); the manager's own commands from the same clean start."""
    ran = t.inside.run(step.argv, log=log) if inside else process.run(step.argv, log=log, env=t.manager.environment)
    return _ended(ran, log)


def _note(log: Path, text: str) -> None:
    persist.append_text(log, text + "\n")


def step_remove(t: Target, step: Step, log: Path, say: Say) -> str:
    try:
        return _run(t, step, log)
    finally:
        t.manager.forget()   # where its environments are, asked again


def step_discard_lock(t: Target, step: Step, log: Path, say: Say) -> str:
    persist.remove(t.lock)
    return "done"


def step_create(t: Target, step: Step, log: Path, say: Say) -> str:
    try:
        return _run(t, step, log)
    finally:
        t.manager.forget()   # where its environments are, asked again


def step_deliver(t: Target, step: Step, log: Path, say: Say) -> str:
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
    held = persist.read_text(t.lock)
    if held is None:
        _note(log, f"no saved lock at {t.lock}")
        return "failed"
    names = locked(held)
    hits = [f for f in t.env.packages.forbid
            if any(n == f.lower() or n.startswith(f.lower() + "-") for n in names)]
    for family in hits:
        _note(log, f"forbidden package family in the lock: {family}")
    return "failed" if hits else "done"


def step_toolchain(t: Target, step: Step, log: Path, say: Say) -> str:
    """Prove the toolchain inside the prefix before any source is fetched (envs.md § 4.1): the
    program measures, `envs/toolchain.py` judges, and each finding is said and logged."""
    work = persist.empty_folder(layout.toolchain_dir(t.prefix))
    spec = write_json(work / "spec.json", toolchain.spec(t.env.proven_toolchain, t.launcher))
    report, result = toolchain.run(t.inside, t.programs[TOOLCHAIN], "check", str(spec), str(work))
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
    if persist.sha256(target_file) == source.sha256:
        _note(log, f"cached: {target_file}")
        return "done"
    got: dict = {}

    def matches(written: Path) -> bool:
        got["sha256"] = persist.sha256(written)
        return got["sha256"] == source.sha256

    with urllib.request.urlopen(source.archive, timeout=120) as response:
        if not persist.write_stream(target_file, response, accept=matches):
            _note(log, f"{source.archive}: SHA-256 {got['sha256']}, expected {source.sha256}")
            return "failed"
    _note(log, f"downloaded {source.archive} -> {target_file}")
    return "done"


def step_unpack(t: Target, step: Step, log: Path, say: Say) -> str:
    source = next(s for s in t.env.sources if s.id == step.id.split(":", 1)[1])
    destination = t.source_dir(source.id)
    if destination.exists():
        if any(destination.iterdir()):
            _note(log, f"{destination} already holds files")
            return "failed"
        persist.remove(destination)  # an empty placeholder, as a parent's submodule folder
    if not persist.unpack_single(layout.archive_cache(source.sha256), destination):
        _note(log, "the archive does not hold exactly one top folder")
        return "failed"
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
    if cache is None:
        _note(log, f"configure wrote no CMakeCache.txt into {t.build_dir(build.id)}")
        return "failed"
    unread = sorted(set(build.options) & unused_options(_text(log) or ""))
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


def step_audit(t: Target, step: Step, log: Path, say: Say) -> str:
    """Every provided executable and module, and the compilers, found inside the prefix (envs.md
    § 4.1): the executables here, the rest by the audit's program, run in it."""
    inside = lambda path: paths.inside(path, t.prefix)  # noqa: E731
    proven = t.env.proven_toolchain
    problems = [f"executable not in the prefix: {e}" for e in t.env.provides.executables
                if not (t.prefix / "bin" / e).exists()]
    if not t.env.provides.modules and not proven:  # nothing for Python to find inside the prefix
        for p in problems:
            _note(log, p)
        return "failed" if problems else "done"
    result = t.inside.run(step.argv, declared=t.programs[AUDIT])   # the plan's command, as its program is declared
    _note(log, result.stdout + result.stderr)
    if not result.ok:
        return _ended(result, log)
    found = audit.read(result.stdout)
    if found is None:
        _note(log, "the audit program gave no report")
        return "failed"
    problems += [f"module {m} does not import inside the prefix: {found['failures'][m]}" if m in found["failures"]
                 else f"module not found inside the prefix: {m} ({o})" for m, o in found["modules"].items() if not inside(o)]
    if proven:
        problems += [f"compiler ${v} does not resolve inside the prefix: {c}" for v, c in found["compilers"].items()
                     if not inside(c)]
    for p in problems:
        _note(log, p)
    return "failed" if problems else "done"


def step_manifest(t: Target, step: Step, log: Path, say: Say) -> str:
    """The version its declared command states — read by its last line, or by its engine's reader
    where that output is irregular (definitions.md § 4) — the pinned one; then the manifest."""
    result = t.inside.run(t.inside.argv(t.env.version_command), timeout=VERSION_TIMEOUT)
    _note(log, result.stdout + result.stderr)
    if _ended(result, log) == KILLED:
        return KILLED
    version = engines.version_reader(t.env.engine)(result.stdout, result.stderr)
    if version != t.env.version:
        _note(log, f"the version probe reported {version!r}; the definition requires {t.env.version!r}")
        return "failed"
    manager_version, why = t.manager.version()
    if manager_version is None:   # the manifest holds the manager's version (envs.md § 4.3): never a guess
        _note(log, f"the manager's version did not read: {why}")
        return "failed"
    lock_sha256 = persist.sha256(t.lock)
    if lock_sha256 is None:
        _note(log, f"no saved lock at {t.lock}")
        return "failed"
    write_json(layout.manifest_file(t.prefix), Manifest(
        install_fingerprint=t.install_fingerprint, lock_sha256=lock_sha256, manager_kind=t.manager.kind_name,
        manager_version=manager_version, solver_version=version, projects=t.projects, settings=t.settings,
        time=clock.stamp(t.now()),
    ).model_dump())
    return "done"


STEP_KINDS: dict[str, Callable[[Target, Step, Path, Say], str]] = {
    "remove": step_remove, "discard-lock": step_discard_lock, "create": step_create, "deliver": step_deliver,
    "lock": step_lock,
    "forbid": step_forbid, "toolchain": step_toolchain, "fetch": step_fetch, "unpack": step_unpack,
    "configure": step_configure, "compile": step_compile, "install": step_install, "audit": step_audit,
    "manifest": step_manifest,
}


#: The steps that make or remove the environment: after each, the manager is asked again where it is
#: (`target`), and the steps that build in it run with that prefix (`rendered`, envs.md § 4.1).
MAKES = frozenset({"remove", "create"})
#: The steps whose commands hold paths within the prefix: what `rendered` writes again.
IN_PREFIX = frozenset({"configure", "compile", "install"})


def rendered(t: Target, step: Step) -> Step:
    """``step`` as it runs: a build step's command written again with the prefix the manager lists
    now — the plan, made before the environment existed, held `<prefix of femkit-NAME>` in its
    place (envs.md § 4.1); any other step as planned."""
    if t.prefix is None or step.id.split(":", 1)[0] not in IN_PREFIX:
        return step
    now = {s.id: s for s in plan_steps(t, remove_first=False, discard_lock=False)}
    return step.model_copy(update={"argv": now[step.id].argv})


def run_step(t: Target, step: Step, where: Path, say: Say = lambda line: None,
             watch: Callable[[Path], None] = lambda log: None) -> tuple[str, Path]:
    """The one door every install step goes through; ``say`` hears what a step reports as it
    runs, and ``watch`` where its log grows. A file, network or archive error is the step's
    failure, said in its log; anything else is a defect and propagates."""
    log = where / f"{step.id.replace(':', '-')}.log"
    watch(log)
    step = rendered(t, step)
    try:
        return STEP_KINDS[step.id.split(":", 1)[0]](t, step, log, say), log
    except (OSError, tarfile.TarError, urllib.error.URLError) as exc:
        _note(log, f"{type(exc).__name__}: {exc}")
        return "failed", log
