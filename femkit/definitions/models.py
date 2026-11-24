"""Schema models of the shipped definitions (definitions.md).

Each class is the one home of its fields: type, default, allowed values and
description. `femkit schema docs` renders `docs/reference/` from them.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, FiniteFloat, PositiveInt, ValidationInfo, field_validator, model_validator

from femkit.core.schema import SHA256, Model, check_placeholders, matching, placeholders, refuse

# ------------------------------------------------- channels.txt and control.txt

_PYTHON_PIN = re.compile(r"^python\s*=\s*(\d+\.\d+)$")


class ControlDefinition(Model):
    """`femkit/data/channels.txt` and `control.txt` — the channel order, and the control
    environment's packages as `conda create --file` reads them (definitions.md § 3)."""

    channels: list[str] = Field(min_length=1, description="channels.txt: the channel order every environment is "
                                                          "solved with, one bare channel name a line")
    dependencies: list[str] = Field(min_length=1, description="control.txt: conda package constraints; exactly "
                                                              "one `python=X.Y`")

    @field_validator("channels")
    @classmethod
    def _bare_names(cls, channels: list[str]) -> list[str]:
        if any(not c or c != c.strip() or " " in c or c.startswith("#") for c in channels) \
                or len(set(channels)) != len(channels):
            raise ValueError("one bare channel name a line, none repeated: the install script passes each line "
                             "to the manager as it stands, so a blank line, a space or a comment would be a "
                             "channel")
        return channels


    @field_validator("dependencies")
    @classmethod
    def _one_python(cls, deps: list[str]) -> list[str]:
        pins = [d for d in deps if _PYTHON_PIN.match(d)]
        if len(pins) != 1:
            raise ValueError("needs exactly one `python=X.Y` line: it is the Python minor every environment shares")
        return deps

    @property
    def python_minor(self) -> str:
        return next(_PYTHON_PIN.match(d).group(1) for d in self.dependencies if _PYTHON_PIN.match(d))


# ---------------------------------------------------------- engine environment

_COMMIT = re.compile(r"[0-9a-f]{40}")
_ID = re.compile(r"[a-z][a-z0-9-]*")

Id = Annotated[str, matching(_ID)]


def _relative_path(text: str) -> str:
    p = PurePosixPath(text)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ValueError(f"{text!r} must be a relative path inside the tree")
    return text


RelativePath = Annotated[str, AfterValidator(_relative_path)]


class Maturity(str, Enum):
    production = "production"
    candidate = "candidate"
    experimental = "experimental"


class Packages(Model):
    conda: list[str] = Field(default_factory=list, description="conda constraints the manager solves")
    pip: list[str] = Field(default_factory=list, description="pip constraints solved after conda")
    forbid: list[str] = Field(
        default_factory=list, description="package families that must be absent from the solved lock"
    )


class Provides(Model):
    executables: list[str] = Field(default_factory=list, description="executables the install's audit step finds in the prefix")
    modules: list[str] = Field(default_factory=list, description="Python modules the install's audit step imports")


LANGUAGES = ("c", "cxx", "fortran")  # the toolchain program's languages (engines/toolchain.py), a test runs it on each


class Toolchain(Model):
    """`[toolchain]` — the compilers and build tools this environment's builds use, solved into
    it and proven before any source is fetched (definitions.md § 4.6). Each environment declares
    its own: environments may need different compilers, versions or patches."""

    packages: list[str] = Field(description="conda constraints: the compilers, the sysroot and every tool a "
                                            "build calls, solved with the environment's packages")
    tools: list[str] = Field(description="executables a build calls; each must resolve inside the prefix")
    compilers: dict[str, str] = Field(min_length=1, description=f"language ({', '.join(LANGUAGES)}) -> the "
                                                                "variable the activation sets to its compiler; "
                                                                "at least one")
    mpi: dict[str, str] = Field(default_factory=dict, description="language -> the MPI compiler wrapper the "
                                                                  "environment provides, for a language "
                                                                  "`compilers` names; when declared, the "
                                                                  "toolchain check builds with them and runs "
                                                                  "two ranks")

    @model_validator(mode="after")
    def _languages(self) -> "Toolchain":
        for part in ("compilers", "mpi"):
            unknown = sorted(set(getattr(self, part)) - set(LANGUAGES))
            if unknown:
                raise ValueError(f"{part}: unknown language {', '.join(unknown)}; languages: {', '.join(LANGUAGES)}")
        if set(self.mpi) - set(self.compilers):
            raise ValueError("mpi: a wrapper for a language the toolchain has no compiler for")
        return self


class Source(Model):
    id: Id = Field(description="the source's ID, referenced by builds as `{source:<id>}`")
    archive: str = Field(description="URL of the archive of exactly `commit`")
    sha256: str = matching(SHA256, description="SHA-256 of the archive")
    commit: str = matching(_COMMIT, description="the upstream commit the archive holds")
    release: str = Field(description="the upstream release name of that commit")
    into: RelativePath = Field(description="where the archive is unpacked, under the prefix's source tree")
    version_text: str | None = Field(
        default=None, description="stands in for `git describe` where the build asks git for a version"
    )


# Options the framework sets itself; a definition may not declare them (definitions.md § 4.2).
FRAMEWORK_OPTIONS = frozenset({
    "CMAKE_INSTALL_PREFIX", "CMAKE_GENERATOR", "CMAKE_BUILD_TYPE", "CMAKE_PREFIX_PATH",
    "CMAKE_FIND_ROOT_PATH", "CMAKE_FIND_ROOT_PATH_MODE_PACKAGE", "CMAKE_FIND_ROOT_PATH_MODE_LIBRARY",
    "CMAKE_FIND_ROOT_PATH_MODE_INCLUDE", "CMAKE_FIND_ROOT_PATH_MODE_PROGRAM",
    "CMAKE_INSTALL_RPATH", "CMAKE_BUILD_RPATH", "CMAKE_INSTALL_RPATH_USE_LINK_PATH",
    "CMAKE_SKIP_RPATH", "CMAKE_SKIP_INSTALL_RPATH", "BUILD_TESTING",
    "CMAKE_FIND_PACKAGE_NO_PACKAGE_REGISTRY", "CMAKE_EXPORT_NO_PACKAGE_REGISTRY",
    "CMAKE_FIND_USE_PACKAGE_REGISTRY", "CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY", "CMAKE_CUDA_ARCHITECTURES",
})

BUILD_OPTION_PLACEHOLDERS = frozenset({"prefix", "source", "build"})


def _option_value(value: Any) -> bool | int | float | str:
    if not isinstance(value, (bool, int, float, str)):
        raise ValueError("a CMake option is a boolean, a number or text")
    return value


OptionValue = Annotated[Any, AfterValidator(_option_value)]


class Build(Model):
    id: Id = Field(description="the build's ID")
    source: Id = Field(description="the source it builds")
    after: list[Id] = Field(default_factory=list, description="builds that must be installed first")
    cuda_architectures: bool = Field(default=False, description="in the CUDA environment, compiled for "
                                                                "`build.cuda_architectures`")
    rpath: list[RelativePath] = Field(default_factory=list, description="install RPATH entries, relative to the prefix")
    options: dict[str, OptionValue] = Field(
        default_factory=dict,
        description="CMake cache entries; a boolean becomes BOOL, anything else STRING. "
        "Strings may use placeholders",
        json_schema_extra={"placeholders": sorted(BUILD_OPTION_PLACEHOLDERS)},
    )
    cuda_options: dict[str, OptionValue] = Field(
        default_factory=dict,
        description="CMake cache entries added in the CUDA environment; in the other, each boolean among "
        "them is set false and the rest are left out",
        json_schema_extra={"placeholders": sorted(BUILD_OPTION_PLACEHOLDERS)},
    )

    @model_validator(mode="after")
    def _one_place_per_option(self) -> "Build":
        both = sorted(set(self.options) & set(self.cuda_options))
        if both:
            raise ValueError(f"in both options and cuda_options: {', '.join(both)}")
        return self

    @field_validator("options", "cuda_options")
    @classmethod
    def _options(cls, options: dict) -> dict:
        owned = sorted(set(options) & FRAMEWORK_OPTIONS)
        if owned:
            raise ValueError(f"framework-owned options cannot be declared: {', '.join(owned)}")
        for key, value in options.items():
            if isinstance(value, str):
                try:
                    check_placeholders(value, BUILD_OPTION_PLACEHOLDERS)
                except ValueError as exc:
                    raise ValueError(f"{key}: {exc}") from None
        return options


CHECK_PLACEHOLDERS = frozenset({"prefix", "work", "ranks", "threads"})
GENERIC_READERS = frozenset({"summary", "junit"})  # read by the check runner itself (definitions.md § 5.3)


class Expectation(Model):
    """What one quantity must be. At least one bound is given; a bound is a finite number, since
    an infinite one would bound nothing."""

    min: FiniteFloat | None = Field(default=None, description="the smallest value allowed")
    max: FiniteFloat | None = Field(default=None, description="the largest value allowed")
    equals: FiniteFloat | int | str | None = Field(default=None, description="the exact value required")

    @model_validator(mode="after")
    def _some_bound(self) -> "Expectation":
        if self.min is None and self.max is None and self.equals is None:
            raise ValueError("states no bound: give min, max or equals")
        return self


class Check(Model):
    """One bounded calculation and the numbers it must produce (definitions.md § 5)."""

    id: Id = Field(description="the check's ID")
    kind: Literal["command", "ctest", "pytest"] = Field(description="how it runs", json_schema_extra={"doc": "definitions.md § 5.1"})
    run: list[str] | None = Field(default=None, description="command: the program and its arguments",
                                  json_schema_extra={"placeholders": sorted(CHECK_PLACEHOLDERS)})
    build: Id | None = Field(default=None, description="ctest: the build whose test tree holds the test")
    test: str | None = Field(default=None, description="ctest: the test's name")
    source: Id | None = Field(default=None, description="pytest: the source tree holding the tests")
    tests: list[str] = Field(default_factory=list, description="pytest: the test node IDs, relative to the source tree")
    plugins: list[str] = Field(default_factory=list, description="pytest: modules loaded first, as `-p` plugins "
                               "(e.g. mpi4py.MPI, so MPI starts before the tests import an MPI build)")
    ranks: PositiveInt = Field(default=1, description="MPI ranks")
    threads: PositiveInt = Field(default=1, description="threads per rank")
    read: str = Field(description="the reader ID that turns its output into quantities")
    expect: dict[str, Expectation] = Field(default_factory=dict, description="quantity -> its bounds")
    agree: str | None = Field(default=None, description="the agreement group it belongs to")
    device: bool = Field(default=False, description="uses a GPU: exists only in the CUDA environment, and runs "
                                                    "only with `env validate --gpu`")
    upstream_verdict: bool = Field(default=True, description="ctest: the test's own pass or fail counts, besides "
                                   "`expect`; false where its stored reference does not hold for the pinned "
                                   "libraries — the definition says why — and only `expect` decides")
    timeout: PositiveInt = Field(default=600, description="seconds before it is stopped")

    @field_validator("run")
    @classmethod
    def _run(cls, argv: list[str] | None) -> list[str] | None:
        for arg in argv or []:
            check_placeholders(arg, CHECK_PLACEHOLDERS)
        return argv

    @model_validator(mode="after")
    def _kind_fields(self) -> "Check":
        needs = {"command": ("run",), "ctest": ("build", "test"), "pytest": ("source", "tests")}[self.kind]
        problems = [((name,), f"a {self.kind} check needs {name}") for name in needs if not getattr(self, name)]
        if not self.upstream_verdict and self.kind != "ctest":
            problems.append((("upstream_verdict",), "only a ctest has an upstream verdict to set aside"))
        refuse(type(self).__name__, problems)
        return self


class CudaPart(Model):
    """`[cuda]` — what the definition's CUDA environment, `<name>-cuda`, adds to it
    (definitions.md § 4.5); the other environment is the definition without it."""

    description: str = Field(description="what the CUDA build is for, appended to the description in `env list`")
    packages: list[str] = Field(default_factory=list, description="conda constraints solved only with CUDA")
    executables: list[str] = Field(default_factory=list, description="executables the audit finds only with CUDA")
    sources: list[Source] = Field(default_factory=list, description="pinned sources only the CUDA environment builds")
    builds: list[Build] = Field(default_factory=list, description="builds only the CUDA environment has; a build of "
                                                                 "the definition may name one in `after`")


class Agreement(Model):
    """Checks that must give the same quantity (definitions.md § 5.2)."""

    quantity: str = Field(description="the quantity compared")
    rtol: FiniteFloat = Field(gt=0, description="relative tolerance, element-wise for a list; finite")


class EnvironmentDefinition(Model):
    """`femkit/data/environments/<name>.toml` — one environment: an engine's (definitions.md § 4),
    or a tool's, which states its `version_command` instead of an `engine` (§ 4.7)."""

    engine: str | None = Field(default=None, description="the registered engine adapter ID; absent for a tool "
                                                         "environment")
    version_command: list[str] | None = Field(default=None, description="a tool environment's: the command, run "
                                              "in the prefix, whose last line of output is its version")
    version: str = Field(description="what the version probe must report")
    control_packages: bool = Field(default=False, description="a tool environment's: the control environment's "
                                   "packages (control.txt), solved with its own (definitions.md § 4.7)")
    description: str = Field(description="one line for `env list`")
    maturity: Maturity = Field(description="production, candidate or experimental")
    default: bool = Field(default=False, description="part of `env install --all`")
    thread_variables: list[str] = Field(
        default_factory=list, description="variables set to a run's threads per rank"
    )
    fixed_variables: dict[str, str] = Field(
        default_factory=dict, description="variables set to these values in every check and run"
    )
    toolchain: Toolchain | None = Field(default=None, description="the compilers and build tools its builds use; "
                                                                   "required with builds")
    packages: Packages = Field(default_factory=Packages, description="what the manager solves; in the environments "
                                                                     "the catalogue builds, the toolchain's packages "
                                                                     "are added to `conda`")
    provides: Provides = Field(default_factory=Provides, description="what the install's audit step finds inside the prefix")
    cuda: CudaPart | None = Field(default=None, description="what the CUDA environment, `<name>-cuda`, adds; "
                                                             "absent: there is none")
    sources: list[Source] = Field(default_factory=list, description="pinned source archives")
    builds: list[Build] = Field(default_factory=list, description="CMake builds; each installs after the builds "
                                                                  "its `after` names")
    checks: list[Check] = Field(default_factory=list, description="the checks that prove an install")
    agreements: dict[str, Agreement] = Field(default_factory=dict, description="agreement group -> what must agree")

    @property
    def proven_toolchain(self) -> Toolchain | None:
        """The toolchain an install proves before any source is fetched: an environment with
        builds has one (definitions.md § 4.6); one without builds proves none."""
        return self.toolchain if self.builds else None

    @property
    def cuda_part(self) -> CudaPart:
        """What the CUDA environment adds: the [cuda] part, or nothing."""
        return self.cuda or CudaPart(description="")

    @property
    def tool(self) -> bool:
        """A tool environment: it runs no engine (definitions.md § 4.7)."""
        return self.engine is None

    @field_validator("engine")
    @classmethod
    def _engine_registered(cls, engine: str | None, info: ValidationInfo) -> str | None:
        known = (info.context or {}).get("engines")
        if engine is not None and known is not None and engine not in known:
            raise ValueError(f"no engine adapter registers {engine!r} (registered: {', '.join(sorted(known)) or 'none'})")
        return engine

    @model_validator(mode="after")
    def _references(self, info: ValidationInfo) -> "EnvironmentDefinition":
        problems: list[tuple[tuple, str]] = []
        if (self.engine is None) == (self.version_command is None):
            problems.append((("engine",), "give an `engine`, or a tool's `version_command` (definitions.md § 4.7)"))
        if self.tool:
            for key in ("toolchain", "sources", "builds", "checks", "agreements", "cuda", "thread_variables",
                        "fixed_variables"):
                if getattr(self, key):
                    problems.append(((key,), "a tool environment has none: it runs no engine (definitions.md § 4.7)"))
            if self.default:
                problems.append((("default",), "a tool environment is installed when asked, never by default"))
        elif self.control_packages:
            problems.append((("control_packages",), "only a tool environment takes the control environment's "
                                                   "packages; an engine's are its own"))
        for var in sorted(set(self.thread_variables) & set(self.fixed_variables)):
            problems.append((("fixed_variables", var), "also in thread_variables; a variable is in one or the other"))
        part = self.cuda_part
        own = {"source": {s.id for s in self.sources}, "build": {b.id for b in self.builds}}
        known = {"source": own["source"] | {s.id for s in part.sources},
                 "build": own["build"] | {b.id for b in part.builds}}
        located = {field: [((field, n), i) for n, i in enumerate(getattr(self, field))]
                   + [(("cuda", field, n), i) for n, i in enumerate(getattr(part, field, []))]
                   for field in ("sources", "builds", "checks")}  # each item with its key path, [cuda]'s last
        for items in located.values():
            seen: set[str] = set()
            for where, item in items:
                if item.id in seen:
                    problems.append(((*where, "id"), f"ID {item.id!r} repeats"))
                seen.add(item.id)
        if (self.builds or part.builds) and self.toolchain is None:
            problems.append((("toolchain",), "an environment with builds declares the toolchain they use"))
        marked = any(b.cuda_architectures or b.cuda_options for b in self.builds) or any(c.device for c in self.checks)
        if self.cuda is None and marked:
            problems.append((("cuda",), "a build compiled for CUDA, a CUDA option or a device check needs the [cuda] part"))
        if self.cuda is not None and not (marked or part.packages or part.executables or part.sources or part.builds):
            problems.append((("cuda",), "adds nothing: its environment would be this one under another name"))
        for n, b in enumerate(part.builds):
            if b.cuda_options:
                problems.append((("cuda", "builds", n, "cuda_options"), "a [cuda] build exists only in the CUDA "
                                 "environment: its options go in `options`"))
        # A build of the definition builds the definition's sources, and names [cuda]'s ids only where the CUDA
        # environment alone reads them: in `after` (dropped without CUDA) and in `cuda_options`.
        for where, b in located["builds"]:
            reach = known if where[0] == "cuda" else own
            if b.source not in reach["source"]:
                problems.append(((*where, "source"), f"no source {b.source!r} is declared where this build may use it"))
            for m, dep in enumerate(b.after):
                if dep not in known["build"]:
                    problems.append(((*where, "after", m), f"no build {dep!r} is declared"))
            for field, scope, values in (("options", reach, b.options), ("cuda_options", known, b.cuda_options)):
                for key, value in values.items():
                    if not isinstance(value, str):
                        continue
                    for name, arg in placeholders(value):
                        at = (*where, field, key)
                        if name in known and arg is None:
                            problems.append((at, f"{{{name}}} needs an ID: {{{name}:<id>}}"))
                        elif name in known and arg not in scope[name]:
                            problems.append((at, f"{{{name}:{arg}}}: no {name} {arg!r} is declared where this "
                                                 "option may name it"))
                        elif name not in known and arg is not None:
                            problems.append((at, f"{{{name}:{arg}}}: {{{name}}} takes no argument"))
        members: dict[str, int] = {}
        for n, c in enumerate(self.checks):
            reach = known if c.device else own  # a check every environment runs uses what every one has
            if c.build is not None and c.build not in reach["build"]:
                problems.append((("checks", n, "build"), f"no build {c.build!r} is declared where this check runs"))
            if c.source is not None and c.source not in reach["source"]:
                problems.append((("checks", n, "source"), f"no source {c.source!r} is declared where this check runs"))
            if c.agree is not None:
                if c.agree not in self.agreements:
                    problems.append((("checks", n, "agree"), f"no agreement {c.agree!r} is declared"))
                members[c.agree] = members.get(c.agree, 0) + 1
        for group in self.agreements:
            if members.get(group, 0) < 2:
                problems.append((("agreements", group), "an agreement group needs at least two checks"))
        cycle = _cycle({b.id: b.after for b in [*self.builds, *part.builds]})
        if cycle:
            problems.append((("builds",), f"builds depend on each other in a cycle: {' -> '.join(cycle)}"))
        readers = ((info.context or {}).get("engines") or {}).get(self.engine)
        if readers is not None:
            for n, c in enumerate(self.checks):
                if c.read not in readers | GENERIC_READERS:
                    problems.append((("checks", n, "read"), f"no reader {c.read!r}: the generic readers and "
                                     f"{self.engine}'s are {', '.join(sorted(readers | GENERIC_READERS))}"))
        refuse(type(self).__name__, problems)
        return self

    def built(self, cuda: bool) -> "EnvironmentDefinition":
        """One of the definition's two environments (definitions.md § 4.5, § 4.6); both solve
        its toolchain's packages with its own. The CUDA one adds its [cuda] part — packages,
        executables, sources, builds and options — and is never a default; the other is the
        definition without it."""
        conda = [*(self.toolchain.packages if self.toolchain else []), *self.packages.conda]
        part = self.cuda_part
        if cuda:
            return self.model_copy(update={
                "default": False, "description": f"{self.description}; {part.description}",
                "packages": self.packages.model_copy(update={"conda": [*conda, *part.packages]}),
                "provides": self.provides.model_copy(update={"executables": [*self.provides.executables,
                                                                             *part.executables]}),
                "sources": [*self.sources, *part.sources],
                "builds": [*(b.model_copy(update={"options": {**b.options, **b.cuda_options}, "cuda_options": {}})
                             for b in self.builds), *part.builds],
                "cuda": None})
        cuda_builds = {b.id for b in part.builds}
        builds = [b.model_copy(update={"after": [a for a in b.after if a not in cuda_builds],
                                       "cuda_architectures": False,
                                       "options": {**b.options, **{k: False for k, v in b.cuda_options.items()
                                                                   if isinstance(v, bool)}},
                                       "cuda_options": {}})
                  for b in self.builds]
        checks = [c for c in self.checks if not c.device]
        members = {g: sum(c.agree == g for c in checks) for g in self.agreements}
        kept = {g for g, n in members.items() if n >= 2}  # a group left with one check compares nothing
        checks = [c if c.agree is None or c.agree in kept else c.model_copy(update={"agree": None}) for c in checks]
        return self.model_copy(update={
            "packages": self.packages.model_copy(update={"conda": conda}), "builds": builds, "checks": checks,
            "agreements": {g: a for g, a in self.agreements.items() if g in kept}, "cuda": None})


def _cycle(graph: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        path.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                return path[path.index(nxt):] + [nxt]
            if nxt in graph and state.get(nxt) is None:
                found = visit(nxt)
                if found:
                    return found
        state[node] = 2
        path.pop()
        return None

    for node in graph:
        if state.get(node) is None:
            found = visit(node)
            if found:
                return found
    return None


# ------------------------------------------------------------------- launchers

LAUNCH_PLACEHOLDERS = frozenset({"ranks"})


def _launcher(argv: list[str] | None) -> list[str] | None:
    """How a multi-rank process starts (config.md § 3.1): not empty, and passes {ranks}."""
    if argv is None:
        return None
    if not argv:
        raise ValueError("an empty launcher starts nothing; leave the key unset instead")
    for arg in argv:
        check_placeholders(arg, LAUNCH_PLACEHOLDERS)
    if not any("{ranks}" in a for a in argv):
        raise ValueError("the launcher must pass {ranks}, or every job runs on the wrong number of processes")
    return argv


Launcher = Annotated[list[str], AfterValidator(_launcher),
                     Field(json_schema_extra={"placeholders": sorted(LAUNCH_PLACEHOLDERS)})]


# ----------------------------------------------------------------------- kinds

MANAGER_PLACEHOLDERS = frozenset({"exe", "prefix", "file"})


def _manager_argv(argv: list[str]) -> list[str]:
    if not argv or argv[0] != "{exe}":
        raise ValueError("a manager command starts with {exe}")
    for arg in argv:
        check_placeholders(arg, MANAGER_PLACEHOLDERS)
    return argv


ManagerArgv = Annotated[
    list[str], AfterValidator(_manager_argv), Field(json_schema_extra={"placeholders": sorted(MANAGER_PLACEHOLDERS)})
]


class JsonQuery(Model):
    argv: ManagerArgv = Field(description="the command; it prints one JSON object")
    key: str | list[str] = Field(description="the key of the object that holds the answer; a list: the first "
                                             "of them the object has, where versions of a manager differ")


def _activation_line(argv: list[str]) -> list[str]:
    for arg in argv:
        check_placeholders(arg, frozenset({"prefix"}))
    if not any("{prefix}" in a for a in argv):
        raise ValueError("must pass {prefix}")
    return argv


ActivationLine = Annotated[list[str], AfterValidator(_activation_line),
                           Field(json_schema_extra={"placeholders": ["prefix"]})]


class Activation(Model):
    """The two ways a shell enters a prefix with this manager; this machine's activation.command
    chooses one (config.md § 3.1; envs.md § 6.2)."""

    hook: str = Field(description="the file whose sourcing defines the activation in a fresh shell, under {root} "
                                  "(the manager's root query); checked on disk, never derived from the "
                                  "executable's path, which on a cluster may be a module's wrapper",
                      json_schema_extra={"placeholders": ["root"]})
    with_hook: ActivationLine = Field(description="the shell function, e.g. `conda activate {prefix}`: it "
                                                  "exists once the hook is sourced, which femkit does first")
    without_hook: ActivationLine = Field(description="the activate script on PATH, `source activate {prefix}`, "
                                                     "which needs no hook — what a cluster's module provides")

    @field_validator("hook")
    @classmethod
    def _hook(cls, text: str) -> str:
        return check_placeholders(text, frozenset({"root"}))


class ManagerKind(Model):
    """`femkit/data/managers/<kind>.toml` — how to drive one package manager (definitions.md § 6).

    The kind's name is the file stem, and is the manager executable's name.
    """

    version: ManagerArgv = Field(description="prints the manager's version")
    version_pattern: str = Field(description="regular expression whose first group is the version in that output")
    root: JsonQuery = Field(description="where the manager's root (base) prefix is")
    platform: JsonQuery | None = Field(
        default=None, description="the platform an environment built by this manager is for, e.g. linux-64", json_schema_extra={"doc": "jobs.md § 9.1"}
    )
    run: ManagerArgv = Field(description="runs the command that follows inside {prefix}")
    activate: Activation = Field(description="how a shell enters a prefix: the day-to-day entry line, the run script")
    create: ManagerArgv = Field(
        description="creates {prefix} from constraints, overriding the person's own channels and default "
                    "packages; `channel` follows once per channel, then the constraints — for the control "
                    "environment, `--file` and its package list"
    )
    channel: list[str] = Field(description="the arguments that add one channel, e.g. [\"-c\", \"{channel}\"]")
    create_from_lock: ManagerArgv = Field(description="creates {prefix} from the exact package list in {file}")
    export_lock: ManagerArgv = Field(description="prints the exact package list of {prefix}, one URL a line")
    remove: ManagerArgv = Field(description="removes {prefix}")
    remove_channels: bool = Field(default=False, description="whether `remove` names the declared channels as "
                                  "`create` does, `channel` once per channel after it: conda 26 otherwise checks the "
                                  "terms of its base configuration's defaults; mamba 2.9.0 refuses channels on a "
                                  "removal (both measured, envs.md § 4.4)")

    @field_validator("channel")
    @classmethod
    def _channel(cls, argv: list[str]) -> list[str]:
        for arg in argv:
            check_placeholders(arg, frozenset({"channel"}))
        if not any("{channel}" in a for a in argv):
            raise ValueError("must pass {channel}")
        return argv

    @field_validator("version_pattern")
    @classmethod
    def _one_group(cls, pattern: str) -> str:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"not a regular expression: {exc}") from None
        if compiled.groups < 1:
            raise ValueError("needs a group that captures the version")
        return pattern


#: The job commands a scheduler kind names, by role (jobs.md § 7): send a job, ask
#: one job's state, cancel it, say which cluster answers. A kind with any has `submit`.
SCHEDULER_ROLES = ("submit", "query", "cancel", "cluster")
#: femkit's names for what a scheduler tells a running job (jobs.md § 7); a kind maps
#: its own variables onto these, and a kind with commands maps `id`.
JOB_ROLES = ("id", "ranks", "cores_per_rank", "cores_on_node", "gpus", "nodes")


class SchedulerKind(Model):
    """`femkit/data/schedulers/<kind>.toml` — how to talk to one scheduler (jobs.md § 7).

    A kind with commands is detected on a machine when its `submit` command is found.
    """

    commands: dict[str, str] = Field(
        default_factory=dict,
        description=f"role ({', '.join(SCHEDULER_ROLES)}) -> the command's usual name; "
                    "the probe records where each is found or declared",
    )
    probe: dict[str, str] = Field(
        default_factory=dict,
        description="role -> a command that measures a machine of this kind; its readers arrive with M4",
    )
    mpi_launch: Launcher = Field(
        description="the launcher `config init` proposes for `launch.mpi` on a machine of this kind",
    )
    job_variables: dict[str, str] = Field(
        default_factory=dict,
        description=f"role ({', '.join(JOB_ROLES)}) -> the variable a job sees; "
                    "`id` set means the process runs inside a job",
    )
    interactive: str | None = Field(
        default=None,
        description="the command that opens an interactive allocation, named by bootstrap's login-node "
                    "warning and when an install step on a login node of this kind is killed (envs.md § 6.2); "
                    "never with a partition",
    )

    @model_validator(mode="after")
    def _closed_roles(self) -> "SchedulerKind":
        for part, allowed in (("commands", SCHEDULER_ROLES), ("job_variables", JOB_ROLES)):
            unknown = sorted(set(getattr(self, part)) - set(allowed))
            if unknown:
                raise ValueError(f"{part}: unknown role {', '.join(unknown)}; roles: {', '.join(allowed)}")
        if self.commands and "submit" not in self.commands:
            raise ValueError("a kind with commands names its submit command")
        if self.commands and "id" not in self.job_variables:
            raise ValueError("a kind with commands declares job_variables.id")
        return self
