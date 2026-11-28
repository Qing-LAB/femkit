"""An environment's state (envs.md § 3): observed, never stored, by the rules
`femkit/data/states/environment.toml` declares over the facts gathered and named here.

Facts are read from disk, but what the manager lists and names — the environment's prefix, and,
where it names none, a folder in its way — asked once per invocation (envs.md §§ 1, 3.1); observing
needs no network.

What femkit's code does to an environment is the table's own `[tasks]`, given each state by its
`[does]` (core.md § 7): `use`, which a program run in it asks — only a state that lists it allows
the environment to be used (`usable`, `allows_use`), and any other is refused with that state's own
next steps — what `env install` does, each where its guard holds over the facts it observes
beside the state: whether it is asked `--clean`, whether the last install can be resumed, and
whether the projects declare a package it lacks — and what `env clean` does. A row of the table
allows a command in a state and says nothing of what it does there.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Literal

from femkit.config import settings
from femkit.core import locks, states, text, view
from femkit.core.errors import Refused, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.definitions.models import CONSTRAINT, EnvironmentDefinition
from femkit.envs import checks, fingerprints, layout, manager

from femkit.core.persist import read_record
from femkit.envs.records import ChecksRecord, Manifest
from femkit.envs.requests import ENV_LIST

#: An environment's GPU qualification (envs.md § 5): a summary of its device checks' outcomes —
#: none declared, some without one, every one passed, or not — which allows and refuses nothing
#: itself, so no machine of its own (core.md § 7); the environment's machine says what may be done.
Gpu = Literal["none", "not-run", "passed", "failed"]
#: The GPU qualification of an environment whose device checks all passed: what a GPU ask needs
#: (envs.md § 5; jobs.md § 3, step 4).
QUALIFIED: Gpu = "passed"


@dataclass(frozen=True)
class EnvFacts:
    name: str
    prefix: Path | None   # as the manager lists it, naming it so (envs.md § 1); none where it lists none
    locked: bool
    prefix_kind: Literal["absent", "directory", "environment"]   # what is at that prefix: nothing, a folder, an environment
    manifest: Manifest | None
    install_fingerprint: str | None   # none: no manifest and no manager named to say what would build it
    checks: ChecksRecord | None
    check_fingerprint: str
    declared_checks: frozenset[str]
    device_checks: frozenset[str]
    orphan: Path | None = None  # where it lists none: a folder of its name where the manager keeps environments
    clean: bool = False        # `env install`'s: it is asked to discard the saved lock (`--clean`)
    resumable: bool = False    # `env install`'s: the last install had the current fingerprint and did not end done
    lacking: bool = False      # `env install`'s: the projects declare a package for it its manifest does not record

    @property
    def current_checks(self) -> ChecksRecord | None:
        """The check results, when they are for the current check fingerprint and cover every check
        without device = true — the ones a plain validate runs (envs.md § 5)."""
        record = self.checks
        if record is None or record.check_fingerprint != self.check_fingerprint:
            return None
        if not self.declared_checks - self.device_checks <= {o.id for o in record.outcomes}:
            return None
        return record

    @property
    def cpu_failed(self) -> bool:
        record = self.current_checks
        return bool(record) and any(o.outcome != "passed" for o in record.outcomes
                                    if o.id in self.declared_checks - self.device_checks)

    @property
    def gpu(self) -> Gpu | None:
        """GPU qualification (envs.md § 5): none, not-run, passed, failed; None while unchecked."""
        record = self.current_checks
        if record is None:
            return None
        if not self.device_checks:
            return "none"
        device = [o for o in record.outcomes if o.id in self.device_checks]
        if len(device) < len(self.device_checks):
            return "not-run"
        return QUALIFIED if all(o.outcome == "passed" for o in device) else "failed"


#: What femkit's code does to an environment, by the names its table's `[tasks]` gives them (envs.md
#: § 3.3): a program run in it, `use`; what `env install` does — validate it, deliver into it the
#: packages the projects declare that it lacks, resume its install,
#: build it from nothing or an old build, after an install that cannot resume, or anew over a working
#: one, and discard its saved lock first; and what `env clean` does, remove its prefix.
USE = "use"
VALIDATE, RESUME, BUILD, RESTART, REBUILD, DISCARD = "validate", "resume", "build", "restart", "rebuild", "discard"
#: What `env install` does to an installed environment the projects declare a package for that it
#: lacks: deliver it into the prefix as it stands (envs.md §§ 3.3, 4.1).
DELIVER = "deliver"
BUILDS = (BUILD, RESTART, REBUILD)    # each builds it from its definition, its prefix removed first where there is one
REMOVE = "remove"
#: The action of a state that validates the environment's GPU checks (envs.md §§ 3.3, 5): what a
#: prepare offers for an environment a record lists not GPU-qualified (jobs.md § 3, step 4).
VALIDATE_GPU = "validate --gpu"
#: The action of a state that installs the environment: what an install a step of which the system
#: killed offers again, for the state it left (envs.md § 6.2).
INSTALL = "install"

BINDING = states.Binding("environment", {
    "locked": lambda f: f.locked,
    "listed": lambda f: f.prefix is not None,
    "orphan": lambda f: f.orphan is not None,
    "folder": lambda f: f.prefix_kind != "absent",
    "environment": lambda f: f.prefix_kind == "environment",
    "manifest": lambda f: f.manifest is not None,
    "built_as_now": lambda f: f.manifest is not None and f.manifest.install_fingerprint == f.install_fingerprint,
    "checked": lambda f: f.current_checks is not None,
    "cpu_failed": lambda f: f.cpu_failed,
    "clean": lambda f: f.clean,
    "resumable": lambda f: f.resumable,
    "lacking": lambda f: f.lacking,
}, values={"name": lambda f: f.name,   # and each folder its remedy names, as a shell line names it
            "prefix": lambda f: shlex.quote(str(f.prefix)) if f.prefix else None,
            "orphan": lambda f: shlex.quote(str(f.orphan)) if f.orphan else None},
   reads=frozenset({"busy", "absent", "failing", "ready"}),   # read by envs, jobs and server
   acts=frozenset({"clean", INSTALL, "install --clean", "validate", VALIDATE_GPU}),
   tasks=frozenset({USE, VALIDATE, DELIVER, RESUME, BUILD, RESTART, REBUILD, DISCARD, REMOVE}))


def machine(ctx: Context) -> states.Machine:
    """The machine `femkit/data/states/environment.toml` declares, bound to these facts (envs.md § 3)."""
    return catalogue.machine(ctx, BINDING)


def require(ctx: Context, f: EnvFacts, state: Enum, action: str) -> None:
    """Refused before anything starts where ``state`` does not allow the environment of ``f`` the
    action ``action``, by its name in the table: by the lock's `Busy`, naming its holder and what
    ends its hold (core.md § 5), while another command holds the environment (`busy`); by the
    table's refusal, with what the state allows, otherwise (envs.md § 3.3). What is done where it
    is allowed is the table's tasks (`machine(ctx).does`), never its row (core.md § 7)."""
    m, name = machine(ctx), f.name
    if state is m.states.busy:
        locks.require_free(layout.subject(name))
    m.require(state, action, f, name)


def alone(name: str) -> None:
    """Refused, by the lock's `Busy` naming its holder and what ends its hold (core.md § 5), while
    another process holds the environment ``name`` at all — a program using it, as a running web
    server uses `web`, holds it shared: what a command needs before it plans a task that changes the
    environment (envs.md § 3.1)."""
    locks.require_free(layout.subject(name))


def allows_use(ctx: Context, state: Enum) -> bool:
    """Whether ``state`` allows a program to run in the environment: its table lists `use` there
    (envs.md § 3.3) — a task no fact guards, so a state another machine's record lists is read as
    one observed here."""
    return USE in machine(ctx).done.get(state.value, ())


@dataclass(frozen=True)
class _Named:
    """An environment known by its name alone — one another machine's record lists: what its next
    steps' requests take of it; no folder of it is known here."""

    name: str
    prefix: Path | None = None
    orphan: Path | None = None


def steps(ctx: Context, name: str, state: Enum, where: view.Machine | None = None) -> tuple[view.Action, ...]:
    """What ``state`` allows the environment ``name``, as its table gives each step (envs.md § 3.3)
    — for the machine ``where``, where it is another's record that lists it in that state, as
    `view.at` takes each step there."""
    return tuple(view.at(a, where) for a in machine(ctx).next(state, _Named(name)))


def step(ctx: Context, name: str, state: Enum, action: str,
         where: view.Machine | None = None) -> tuple[view.Action, ...]:
    """The one step the row ``action`` of ``state`` is for the environment ``name``, as its table
    gives it (envs.md § 3.3) — for the machine ``where``, as `steps` takes it; none where the state
    allows no such action."""
    allowed = machine(ctx).allowed(state).get(action)
    found = allowed.next(_Named(name)) if allowed is not None else None
    return (view.at(found, where),) if found is not None else ()


def usable(ctx: Context, name: str, by: str) -> EnvFacts:
    """The facts of the environment ``name``, which ``by`` — a program, as a refusal says it — is to
    run in; refused where its state does not allow its use (envs.md § 3.3): while another command
    holds it, by the lock's `Busy`, naming what holds it and what ends its hold (core.md § 5);
    otherwise `Refused` · `not-allowed`, about the environment, with that state's own next steps."""
    f, state = observe(ctx, name)
    if allows_use(ctx, state):
        return f
    m = machine(ctx)
    if state is m.states.busy:
        locks.require_free(layout.subject(name))
    raise Refused(f"{by} runs in {name}, which is {state.value}", m.next(state, f), code="not-allowed",
                  subject=name)


@dataclass(frozen=True)
class Declared:
    """What the projects under the projects root declare for an environment that takes their
    packages (definitions.md § 4.7): each package as a project writes it, and a note at each project
    file whose packages could not be read — it adds none."""

    packages: list[str] = field(default_factory=list)
    notes: list[Issue] = field(default_factory=list)


#: What gives, for a context, what the projects under the projects root declare (definitions.md
#: § 4.7): the projects lie above this domain, so femkit's start hands it here (api.md § 6), as it
#: hands the door the part schemas.
_DECLARED: list[Callable[[Context], Declared]] = []


def provide(declared: Callable[[Context], Declared]) -> None:
    """``declared`` gives, for a context, what the projects under the projects root declare
    (definitions.md § 4.7); providing it again replaces it."""
    _DECLARED[:] = [declared]


def projects(ctx: Context) -> Declared:
    """What the projects under the projects root declare — each package once, in order — read once
    per invocation (definitions.md § 4.7): what an environment that takes them is installed with
    beside its own, and delivered into as it stands (envs.md §§ 3.3, 4.1). Observing an environment
    never reads it: no package a project declares changes an environment's state (envs.md § 3.1)."""
    if not _DECLARED:
        raise RuntimeError("no one has handed the envs domain what the projects declare: femkit's start does "
                           "(registry.operations)")
    return ctx.cached("projects' packages", lambda: _once(_DECLARED[0](ctx)))


def _once(declared: Declared) -> Declared:
    return Declared(packages=list(dict.fromkeys(sorted(declared.packages))), notes=declared.notes)


def definition(ctx: Context, name: str) -> EnvironmentDefinition:
    """The environment ``name`` as femkit declares it — femkit's own set, which its install
    fingerprint covers (envs.md § 2); refused, naming the environments, for a name femkit has none
    of."""
    envs = catalogue.environments(ctx)
    if name not in envs:
        raise UsageError(f"no environment {name!r}; environments: {', '.join(sorted(envs))}",
                         (view.command(ENV_LIST),), code="no-such-environment", subject=name)
    return envs[name]


def added(ctx: Context, name: str) -> list[str]:
    """The packages the projects under the projects root declare that ``name`` is installed with
    beside its own (envs.md § 4.3; definitions.md § 4.7): none for an environment that takes no
    project's packages, and only new ones — none femkit's recipe declares or pins for it, under any
    version, since what goes into it is the recipe's alone (envs.md § 4.4)."""
    env = definition(ctx, name)
    held = env.held
    return [p for p in projects(ctx).packages
            if (found := CONSTRAINT.match(p)) is None or found.group("name") not in held] if env.projects else []


def lacking(ctx: Context, name: str, manifest: Manifest | None) -> list[str]:
    """The packages the projects declare for ``name`` that its manifest does not record it was
    installed with: what `env install` delivers into it as it stands (envs.md §§ 3.3, 4.1)."""
    held = set(manifest.projects) if manifest is not None else set()
    return [p for p in added(ctx, name) if p not in held]


def delivering(ctx: Context, f: EnvFacts, state: Enum) -> list[str]:
    """The packages the projects declare for the environment of ``f`` that `env install` would
    deliver into it as it stands (envs.md §§ 3.3, 4.1): the one `lacking` answer, where its state's
    tasks deliver what it lacks; none elsewhere — an environment not made yet takes them with its
    create."""
    if f.manifest is None or DELIVER not in machine(ctx).does(state, replace(f, lacking=True)):
        return []
    return lacking(ctx, f.name, f.manifest)


def to_deliver(ctx: Context, f: EnvFacts, state: Enum, packages: list[str]) -> Issue | None:
    """That the environment of ``f`` lacks ``packages`` the projects declare for it, with its state's
    step that delivers them, `env install` (envs.md § 6); none where it lacks none."""
    if not packages:
        return None
    return Issue(severity="warning", code="packages-to-deliver", subject=f.name,
                 message=f"{f.name} lacks what the projects declare for it: {', '.join(packages)}; "
                         "`env install` delivers it", next=step(ctx, f.name, state, INSTALL))


def orphaned(ctx: Context, f: EnvFacts, state: Enum) -> Issue | None:
    """A folder of the environment's name where the manager keeps environments, which it does not
    list as one, said with that folder and its state's own steps (envs.md § 3): femkit never makes
    an environment over it; none where there is none."""
    if f.orphan is None:
        return None
    return Issue(severity="warning", code="orphan", subject=f.name, file=str(f.orphan),
                 message=f"{text.path(f.orphan)} is a folder of {f.name}'s name where the manager keeps "
                         "environments, which it does not list as one: femkit never makes an environment over it",
                 next=machine(ctx).next(state, f))


def install_fingerprint(ctx: Context, name: str, manager_kind: str | None) -> str | None:
    """What an install of ``name`` by a ``manager_kind`` manager is fingerprinted as; None
    without a manager kind."""
    if manager_kind is None:
        return None
    return fingerprints.install(definition(ctx, name), catalogue.control(ctx),
                                settings.load(ctx).config.build.cuda_architectures, manager_kind)


def _built_by(manifest: Manifest | None, ctx: Context) -> str | None:
    """The manager kind an environment's fingerprint is read with: the one its manifest says built
    it — so another manager named now leaves it as built — else the one the invocation names, which
    would build it (envs.md § 2)."""
    return manifest.manager_kind if manifest is not None else manager.named_kind(ctx)


def facts(ctx: Context, name: str) -> EnvFacts:
    """What is observed of the environment ``name``: its prefix as the manager lists it under the
    environment's name (envs.md § 1), refused while no manager is named; its lock as another process
    holds it — this process's own hold reads as free (core.md § 5)."""
    env = definition(ctx, name)
    m, managed = manager.resolve(ctx), catalogue.managed(ctx, name)
    where = m.prefix(managed)
    kind = "absent" if where is None or not where.exists() else \
        "environment" if manager.made(where, catalogue.managers(ctx)) else "directory"
    manifest = read_record(layout.manifest_file(where), Manifest).value if where is not None else None
    return EnvFacts(
        name=name,
        prefix=where,
        locked=locks.is_held(layout.subject(name)),
        prefix_kind=kind,
        orphan=m.orphan(managed) if where is None else None,
        manifest=manifest,
        install_fingerprint=install_fingerprint(ctx, name, _built_by(manifest, ctx)),
        checks=read_record(layout.checks_file(where), ChecksRecord).value if where is not None else None,
        check_fingerprint=fingerprints.check(env, checks.code(env)),
        declared_checks=frozenset(c.id for c in env.checks),
        device_checks=frozenset(c.id for c in env.checks if c.device),
    )


def observe(ctx: Context, name: str) -> tuple[EnvFacts, Enum]:
    """The environment's facts, and its state by the machine's rules."""
    f = facts(ctx, name)
    return f, machine(ctx).observe(f)


def gpu(ctx: Context, f: EnvFacts, state: Enum) -> Gpu | None:
    """The GPU qualification an environment reports: only while it is `failing` or `ready` (envs.md § 3.2)."""
    m = machine(ctx)
    return f.gpu if state in (m.states.failing, m.states.ready) else None
