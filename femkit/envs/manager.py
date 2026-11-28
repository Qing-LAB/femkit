"""The package manager in use, and the command lines its kind declares (definitions.md § 6).

The install script finds the manager and passes it as FEMKIT_ENV_MANAGER
(envs.md § 7.1); Python never searches. Every environment is one of the manager's own, named by
the catalogue's rule (`catalogue.managed`); its prefix is the one the manager names so
(`Manager.prefix`), and every command on it names it (envs.md § 1). Every command the manager
starts begins from the clean start (`envs/start.py`, envs.md § 4.4); what goes into an environment
is the recipe's, the person's settings that would change it set aside or refused (`Manager.settings`).
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from femkit.core import dirs, persist, process, view
from femkit.core.errors import Refused, Unstated, UsageError
from femkit.core.operations import Context
from femkit.core.schema import render
from femkit.definitions import catalogue
from femkit.definitions.models import JsonQuery, ManagerKind
from femkit.envs import start

VARIABLE = "FEMKIT_ENV_MANAGER"


@dataclass(frozen=True)
class Refusing:
    """A setting of the person's nothing sets aside, refused before any create (envs.md § 4.4)."""

    key: str          # the setting, as the manager names it
    source: str       # where the manager read it: a file, or its variables
    value: Any        # what it is set to
    change: str       # why it is refused, and what the person changes


@dataclass(frozen=True)
class Found:
    """The person's own settings a manager read that would change what goes into an environment
    (envs.md § 4.4): whether they could be read at all, those set aside — each with where it was read
    — and those refused."""

    read: bool
    neutralised: dict[str, list[str]] = field(default_factory=dict)
    refused: tuple[Refusing, ...] = ()


def _same(path: Path) -> str:
    """A folder as the file system resolves it, so two spellings of one folder compare equal."""
    return os.path.realpath(path)


@dataclass(frozen=True)
class Manager:
    path: Path
    kind_name: str
    kind: ManagerKind
    # The clean start every command it starts begins from (envs.md § 4.4): the invocation's variables
    # as `envs/start.py` keeps them, `PATH` the system's.
    begins: Mapping[str, str] = field(compare=False, repr=False)
    printed: dict = field(default_factory=dict, compare=False, repr=False)  # a query's command -> what it printed

    @property
    def environment(self) -> dict[str, str]:
        """The variables its own commands run with: the clean start, nothing of the manager's set by
        femkit — it runs as the person set it up (envs.md § 4.4)."""
        return dict(self.begins)

    def argv(self, template: list[str], **values: str) -> list[str]:
        return [render(arg, {"exe": str(self.path), **values}) for arg in template]

    def _channels(self, argv: list[str], channels: list[str]) -> list[str]:
        for channel in channels:
            argv += [render(arg, {"channel": channel}) for arg in self.kind.channel]
        return argv

    def create(self, name: str, channels: list[str], packages: list[str]) -> list[str]:
        """The kind's `create` of the environment ``name``, where the manager keeps environments, from
        the declared channels alone (envs.md §§ 1, 4.4)."""
        return self._channels(self.argv(self.kind.create, name=name), channels) + list(packages)

    def install(self, name: str, channels: list[str], packages: list[str]) -> list[str]:
        """The kind's `install` of ``packages`` into the environment ``name`` as it stands, from the
        declared channels alone (envs.md §§ 4.1, 4.4)."""
        return self._channels(self.argv(self.kind.install, name=name), channels) + list(packages)

    def create_from_lock(self, name: str, lock: Path, channels: list[str]) -> list[str]:
        """The kind's `create_from_lock`, naming the declared channels where the kind does (envs.md § 4.4)."""
        return self._named(self.argv(self.kind.create_from_lock, name=name, file=str(lock)), "create_from_lock",
                           channels)

    def remove(self, name: str, channels: list[str]) -> list[str]:
        """The kind's `remove`, naming the declared channels where the kind does (envs.md § 4.4)."""
        return self._named(self.argv(self.kind.remove, name=name), "remove", channels)

    def export_lock(self, name: str) -> list[str]:
        """The kind's `export_lock` of the environment ``name``: its exact package list (envs.md § 4.1)."""
        return self.argv(self.kind.export_lock, name=name)

    def _named(self, argv: list[str], command: str, channels: list[str]) -> list[str]:
        return self._channels(argv, channels if command in self.kind.channels_named else [])

    def in_environment(self, name: str, command: list[str]) -> list[str]:
        """``command`` run inside the environment ``name`` through the manager's own `run`, by the
        name (envs.md § 4.4)."""
        return self.argv(self.kind.run, name=name) + list(command)

    def version(self) -> tuple[str | None, str | None]:
        """(the manager's version, None), or (None, why it did not read): the first group of
        the kind's `version_pattern` in what its `version` command printed."""
        argv = self.argv(self.kind.version)
        result = process.run(argv, env=self.environment, timeout=60)
        if not result.ok:
            return None, _failed(argv, result)
        found = re.search(self.kind.version_pattern, result.stdout)
        if found is None:
            return None, f"`{shlex.join(argv[1:])}` printed nothing that {self.kind.version_pattern!r} matches"
        return found.group(1), None

    def printing(self, template: list[str]) -> tuple[Any, str | None]:
        """(the JSON the manager's command ``template`` prints, None), or (None, why it printed
        none): each command run once until the environments change (`forget`) — the root and the
        platform may share one."""
        argv = self.argv(template)
        if tuple(argv) not in self.printed:
            self.printed[tuple(argv)] = process.run(argv, env=self.environment, timeout=60)
        result = self.printed[tuple(argv)]
        if not result.ok:
            return None, _failed(argv, result)
        try:
            return persist.json_value(result.stdout), None
        except ValueError:
            return None, f"`{shlex.join(argv[1:])}` printed no JSON"

    def query(self, q: JsonQuery) -> tuple[Any, str | None]:
        """(the answer, None), or (None, why there is none): one key of the JSON the
        manager prints."""
        data, why = self.printing(q.argv)
        if why is not None:
            return None, why
        keys = [q.key] if isinstance(q.key, str) else q.key
        found = next((k for k in keys if isinstance(data, dict) and k in data), None)
        return (data[found], None) if found else (None, f"`{shlex.join(self.argv(q.argv)[1:])}` has no "
                                                        f"{' or '.join(keys)}")

    def _answer(self, q: JsonQuery, what: str, shape: type) -> Any:
        """The answer of the query ``q``, of the shape ``shape``; refused, naming ``what`` the manager
        does not say, where it gives none of that shape."""
        found, why = self.query(q)
        if why is not None or not isinstance(found, shape):
            raise Refused(f"the manager does not say {what}: {why or f'its answer is no {shape.__name__}'}",
                          code="no-environments", subject=str(self.path))
        return found

    def folders(self) -> list[Path]:
        """The folders where the manager keeps environments by their names, in its order (its
        `envs_dirs`): where it makes one, and where a listed one is named (envs.md § 1)."""
        return [Path(p) for p in self._answer(self.kind.envs_dirs, "where it keeps environments", list)
                if isinstance(p, str)]

    def prefix(self, name: str) -> Path | None:
        """Where the environment the manager knows as ``name`` lies: of the prefixes its
        `environments` query lists, the one it names so — its own name for it (`names`), or, where it
        says none, a listed one in one of the folders where it keeps environments, under its name
        there — asked once until the environments change (`forget`), never formed, and never a listed
        prefix elsewhere whose last step happens to be the name (envs.md § 1); None where it names
        none so. Refused where the manager gives no list, or names two so."""
        listed = [Path(p) for p in self._answer(self.kind.environments, "where its environments are", list)
                  if isinstance(p, str)]
        own = self.query(self.kind.names)[0] if self.kind.names is not None else None
        if isinstance(own, dict):
            said = {Path(p): e.get(self.kind.names.name) for p, e in own.items() if isinstance(e, dict)}
            found = [p for p in listed if said.get(p) == name]
        else:
            kept = {_same(d) for d in self.folders()}
            found = [p for p in listed if p.name == name and _same(p.parent) in kept]
        found = list(dict.fromkeys(found))
        if len(found) > 1:
            raise Refused(f"the manager lists two environments named {name}: {', '.join(map(str, found))}; "
                          "remove one with the manager", code="named-twice", subject=name)
        return found[0] if found else None

    def orphan(self, name: str) -> Path | None:
        """A folder of the name ``name`` in one of the folders where the manager keeps environments
        by their names — where its create would make the environment, and where its `run` and its
        activation would find it — that it does not list as an environment of that name: an ORPHAN,
        which femkit never creates over nor removes (envs.md § 3); None where there is none, or where
        the manager lists one so."""
        if self.prefix(name) is not None:
            return None
        return next((d / name for d in self.folders() if os.path.lexists(d / name)), None)

    def forget(self) -> None:
        """What the manager listed of its environments is forgotten, so the next `prefix` asks again:
        after a command that made or removed one."""
        for q in (self.kind.environments, self.kind.names):
            if q is not None:
                self.printed.pop(tuple(self.argv(q.argv)), None)

    def settings(self) -> Found:
        """The person's own settings of this manager that would change what a create, a delivery or a
        create from a lock puts into an environment, by where the manager says it read each (envs.md
        § 4.4): those its kind's commands set aside, and those it refuses; nothing read where the kind
        declares no way to read them. Refused where the manager does not answer."""
        declared = self.kind.settings
        if declared is None:
            return Found(read=False)
        sources, why = self.printing(declared.argv)
        if why is not None or not isinstance(sources, dict):
            raise Refused(f"the manager does not say which of your settings it read: {why or 'no object'}",
                          code="no-settings", subject=str(self.path))
        neutralised: dict[str, list[str]] = {}
        refused: list[Refusing] = []
        for source, held in sources.items():
            for key, value in (held.items() if isinstance(held, dict) else ()):
                if key in declared.neutralised:
                    neutralised.setdefault(key, []).append(str(source))
                elif key in declared.refused and declared.refused[key].when in (None, value):
                    refused.append(Refusing(key, str(source), value, declared.refused[key].change))
        return Found(read=True, neutralised=neutralised, refused=tuple(refused))

    def activation(self, name: str, preamble: Sequence[str], command: str | None) -> list[str]:
        """The shell lines that enter the environment ``name`` on this machine, its ``preamble``
        before the activation the person stated for it (config.md § 3.1; envs.md § 6.2): `entering`'s,
        with this manager — whose own hook the shell function needs — checked here; an activation that
        cannot enter as written says why after its line; none while unstated, the preamble alone."""
        entry = entering(self.kind_name, self.kind, str(self.path), name, preamble, command)
        problem = entry.problem or (f"no manager at {entry.manager}: `{command}` needs its hook evaluated first"
                                    if entry.manager and not os.access(entry.manager, os.X_OK) else None)
        return [*entry.preamble, entry.activation[-1] + f"   # {problem}"] if problem else list(entry.lines)


@dataclass(frozen=True)
class Entry:
    """The shell lines that enter one environment on a machine, by its name — its preamble, then the
    activation — and what they rest on (jobs.md § 4, block 8)."""

    preamble: tuple[str, ...]    # the machine's preamble, verbatim
    activation: tuple[str, ...]  # in order, the last entering the environment; none while the activation is unstated
    manager: str | None          # the manager whose own hook the activation evaluates, which must be there where
                                 # the lines run; none for the activate script's form
    script: str | None           # the script the activation sources from PATH, which must be found there once the
                                 # preamble ran; none for the shell function's form
    problem: str | None          # why the activation cannot enter as written; None when it can

    @property
    def lines(self) -> tuple[str, ...]:
        """Every line, in order: the preamble's, then the activation's."""
        return (*self.preamble, *self.activation)

    def sources(self) -> list[tuple[str, str]]:
        """Each absolute file the preamble sources, with what sources it — a bare `source X` or `. X`
        line of it, X written out — which a run checks readable before it enters (jobs.md § 4, block
        8): a preamble written for another machine fails there, not halfway. A relative path, or one
        built from a variable, is left as written."""
        return [(f, "the preamble") for line in self.preamble if (f := sourced(line))]


def sourced(line: str) -> str | None:
    """The file a bare `source X` or `. X` line names, when X is an absolute path written out: the
    one kind of preamble line checked before it runs (jobs.md § 4, block 8)."""
    try:
        found = shlex.split(line)
    except ValueError:
        return None
    if len(found) == 2 and found[0] in ("source", ".") and found[1].startswith("/") and "$" not in found[1]:
        return found[1]
    return None


def form(kind: ManagerKind, command: str) -> str | None:
    """Which of the kind's two forms ``command`` is (config.md § 3.1): `script`, the activate
    script on PATH; `hook`, the shell function the manager's own hook defines; None, neither."""
    words = command.split()
    if words == [x for x in kind.activate.without_hook if x != "{name}"]:
        return "script"
    if words == [x for x in kind.activate.with_hook if x != "{name}"]:
        return "hook"
    return None


def entering(kind_name: str, kind: ManagerKind, exe: str | None, name: str, preamble: Sequence[str],
             command: str | None) -> Entry:
    """The one writer of the lines that enter the environment the manager knows as ``name`` on a
    machine (envs.md § 1): its ``preamble``, its `activation.preamble` verbatim, then ``command``,
    its `activation.command`, with a manager of ``kind`` at ``exe`` — this machine's, or another's
    as its record holds it — so the day-to-day entry lines, a run script prepared for any machine and
    the line that opens a stage's output are written alike (definitions.md § 6; jobs.md § 4, block 8;
    workflow.md § 8). The script form is one line, its script found on PATH; the shell function's
    needs the manager's own hook evaluated first — `<exe> shell.bash hook` for conda, the kind's
    `activate.hook` — never a file guessed from where the manager lies, and the manager there, which
    the caller checks where the lines run: here, or in the run script before it evaluates it. No
    ``command``: the preamble alone, the activation unstated."""
    preamble = tuple(preamble)
    if command is None:
        return Entry(preamble, (), None, None, None)
    line = shlex.join([*command.split(), name])
    which = form(kind, command)
    if which == "script":
        return Entry(preamble, (line,), None, kind.activate.script, None)
    if which is None:
        return Entry(preamble, (line,), None, None, f"not one of the {kind_name} kind's forms")
    if not exe:
        return Entry(preamble, (line,), None, None,
                     f"the manager is not known: `{command}` needs its hook evaluated first")
    hook = shlex.join(render(a, {"exe": exe}) for a in kind.activate.hook)
    return Entry(preamble, (f'eval "$({hook})"', line), exe, None, None)


def _failed(argv: list[str], result: process.ProcessResult) -> str:
    """Why a manager command gave no answer: how it ended."""
    ended = "did not end in time" if result.timed_out else f"failed (exit {result.returncode})"
    return f"`{shlex.join(argv[1:])}` {ended}"


def kind_of(executable: str | Path) -> str:
    """The manager kind an executable is: its file's name, the kind file's stem (definitions.md § 6)."""
    return Path(executable).name


def named(ctx: Context) -> str | None:
    """The manager the invocation names: FEMKIT_ENV_MANAGER (set by the install script), else the
    first variable a kind's activation sets to its executable (`activate.executable`), in the
    order of the kinds' names, that names one femkit has a kind file for — so a micromamba in
    one is passed over — else the first set (envs.md § 7.1); None when none is named."""
    kinds = catalogue.managers(ctx)
    activated = [ctx.env[v] for v in dict.fromkeys(k.activate.executable for k in kinds.values()) if ctx.env.get(v)]
    return ctx.env.get(VARIABLE) or next((v for v in activated if kind_of(v) in kinds), None) \
        or next(iter(activated), None)


def named_kind(ctx: Context) -> str | None:
    """The kind of the manager the invocation names; None when none is named."""
    named_here = named(ctx)
    return kind_of(named_here) if named_here else None


def made(prefix: Path, kinds: Mapping[str, ManagerKind]) -> bool:
    """Whether ``prefix`` is an environment a package manager made: it holds the folder a kind
    marks every environment it makes with (`environment`) — any kind's (envs.md § 3.1)."""
    return any((prefix / kind.environment).is_dir() for kind in kinds.values())


def resolve(ctx: Context) -> Manager:
    """The manager the invocation names, to run its commands, once per invocation — what it lists of
    its environments asked once (`Manager.prefix`); refused when none names a known kind."""
    kinds = catalogue.managers(ctx)
    named_here = named(ctx)
    if not named_here:
        raise Unstated("no package manager is named: run femkit in a shell where the manager is initialised, "
                      "or through its install script",
                      (view.shell(f"bash {shlex.quote(str(dirs.install_script()))} list"),),
                      code="manager-unnamed", subject=VARIABLE)
    path, kind = Path(named_here), kind_of(named_here)
    if kind not in kinds:
        raise UsageError(f"{path} is a manager femkit has no kind file for (it has: {', '.join(sorted(kinds))})",
                         code="no-such-kind", subject=str(path))
    return ctx.cached(f"manager {path}", lambda: Manager(path, kind, kinds[kind], start.clean(ctx)))
