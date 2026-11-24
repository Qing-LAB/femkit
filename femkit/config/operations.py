"""Configuration operations: `config path|show|set|init` (config.md § 2–3)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tomlkit
from pydantic import Field

from femkit.config import probe, settings
from femkit.core import dirs, paths, text, view
from femkit.core.errors import PlanStale, UsageError
from femkit.core.issues import Issue
from femkit.core.operations import Ask, Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.persist import parse_value
from femkit.core.schema import Model
from femkit.definitions import catalogue
from femkit.config.requests import OPTION_KEYS, PathRequest, SetRequest, ShowRequest, option_name
from femkit.config.requests import CONFIG_INIT, CONFIG_PATH, CONFIG_SET, CONFIG_SHOW



# ------------------------------------------------------------------ config path

class DirectoryRow(Model):
    name: str = Field(description="config, data, cache or state")
    path: str = Field(description="the directory")
    rule: str = Field(description="what chose it: a FEMKIT_* variable, an XDG variable, or the default")
    entries: list[str] = Field(description="every file under the config directory; the top-level entries of the others")


class PathResult(Result):
    directories: list[DirectoryRow] = Field(description="the four directories, in the order config, data, cache, state")

    def text(self) -> str:
        lines = ["the four femkit directories"]
        lines += text.table((d.name, d.path, f"# from {d.rule}") for d in self.directories)
        for d in self.directories:
            lines.append(f"  in {d.name}:")
            lines += [f"{text.PAD}{e}" for e in d.entries] or [f"{text.PAD}(empty)"]
        return "\n".join(lines)


@operation(CONFIG_PATH, result=PathResult)
def config_path(req: PathRequest, ctx: Context) -> PathResult:
    """Print the four femkit directories, what chose each, and what is in them."""
    rows = []
    for name, (path, rule) in dirs.directory_sources().items():
        if not path.exists():
            entries: list[str] = []
        elif name == "config":
            entries = sorted(str(p.relative_to(path)) for p in path.rglob("*") if p.is_file())
        else:
            entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        rows.append(DirectoryRow(name=name, path=str(path), rule=rule, entries=entries))
    return PathResult(directories=rows)


# ------------------------------------------------------------------ config show

class ShowRow(Model):
    key: str = Field(description="the dotted key")
    value: Any = Field(default=None, description="its value; none when unset")
    source: str = Field(description="`config.toml`, or `unset`")
    unset: str = Field(description="what the key's absence means")


class ShowResult(Result):
    file: str | None = Field(description="the file that answered; none when absent")
    rows: list[ShowRow] = Field(description="every key, in the model's order")

    def text(self) -> str:
        lines = [f"read {self.file}" if self.file else "no config.toml: every key is unset"]
        lines += text.table((r.key, text.show(r.value)) if r.value is not None
                            else (r.key, f"unset  # {r.unset}") for r in self.rows)
        return "\n".join(lines)


@operation(CONFIG_SHOW, result=ShowResult)
def config_show(req: ShowRequest, ctx: Context) -> ShowResult:
    """Print every configuration key with its value and where it came from, or what its absence means."""
    loaded = settings.load(ctx)
    rows = []
    for k in settings.keys():
        value = settings.value_of(loaded.config, k)
        rows.append(ShowRow(key=k.dotted, value=settings.plain(value),
                            source="config.toml" if value is not None else "unset", unset=k.unset))
    return ShowResult(file=str(loaded.file) if loaded.file else None, rows=rows)


# ------------------------------------------------------------------ config set

class SetOutcome(Outcome):
    file: str = Field(default="", description="the file written")

    def text(self) -> str:
        if not self.plan.steps:
            return f"nothing to change in {self.file}"
        return f"{self.plan.steps[0].describe}\n  in {self.file}"


def _value(raw: str) -> Any:
    """The value its TOML text gives — `8`, `"text"`, `["80", "90"]`, `[]` — as the file writes it;
    a bare word is refused, never guessed to be text (web.md § 7.3)."""
    try:
        return parse_value(raw).unwrap()
    except ValueError as exc:
        raise UsageError(str(exc)) from None


@operation(CONFIG_SET, result=SetOutcome, changes=True,
           subject=lambda req: ["config"])
class ConfigSet:
    """Validate and write one configuration key, keeping the file's comments and layout."""

    def plan(self, req: SetRequest, ctx: Context) -> Plan:
        settings.key(req.key)
        old = settings.load(ctx).present().get(req.key)  # a broken file is refused here, naming it
        new = _value(req.value)
        settings.with_values({req.key: new})  # an invalid new value is refused before anything is asked
        steps = () if old == new else (
            Step(id=f"set:{req.key}", describe=f"set {req.key}: {text.show(old)} -> {text.show(new)}"),)
        return Plan(basis={"old": old}, steps=steps)

    def apply(self, plan: Plan, ctx: Context, observer) -> SetOutcome:
        req = SetRequest.model_validate(plan.request)
        if settings.load(ctx, fresh=True).present().get(req.key) != plan.basis["old"]:
            raise PlanStale(f"{req.key} changed since the plan", (view.command(CONFIG_SET, key=req.key, value=req.value),))

        def do(step: Step, where):
            settings.write(settings.with_values({req.key: _value(req.value)}))
            return "done", None

        status, log = run_steps(plan, ctx, observer, do)
        return SetOutcome(plan=plan, status=status, log=str(log), file=str(settings.config_file()))


# ------------------------------------------------------------------ config init

PREAMBLE, COMMAND = settings.PREAMBLE, settings.COMMAND


def stating(verb: view.Verb, dotted: list[str]) -> tuple[view.Action, ...]:
    """What states each of these keys of settings.STATED, as ``operation`` takes them."""
    out: list[view.Action] = []
    if PREAMBLE in dotted:
        preamble = settings.key(PREAMBLE)
        out += [view.command(verb, note="once per line",
                             fills=[view.Fill(field="preamble", label=preamble.dotted, example="LINE",
                                                          help=view.Help.of(preamble.description))]),
                view.command(verb, no_preamble=True, note="none is needed here")]
    if COMMAND in dotted:
        command = settings.key(COMMAND)
        out += [view.command(verb, note="or 'conda activate', 'mamba activate'",
                             fills=[view.Fill(field=option_name(command), label=command.dotted, example="source activate",
                                                                    help=view.Help.of(command.description))])]
    return tuple(out)

class InitRow(Model):
    key: str = Field(description="the dotted key")
    status: str = Field(description="added, kept or unset")
    value: Any = Field(default=None, description="the value added or kept")
    note: str = Field(default="", description="for an unset key, what its absence means")


class InitOutcome(Outcome):
    file: str = Field(default="", description="the file written")
    rows: list[InitRow] = Field(default_factory=list, description="every key, in the model's order")

    def text(self) -> str:
        added = sum(r.status == "added" for r in self.rows)
        lines = [f"{self.file}: {text.count(added, 'key')} added"]
        lines += text.table((r.status, r.key, text.show(r.value) if r.status != "unset" else "unset", f"# {r.note}" if r.note else "")
                            for r in self.rows)
        return "\n".join(lines + text.findings(self.issues))


def _given(req) -> dict[str, Any]:
    given = {k.dotted: settings.plain(getattr(req, name)) for name, k in OPTION_KEYS.items()
             if getattr(req, name) is not None}
    if req.no_preamble:
        if PREAMBLE in given:
            raise UsageError("--preamble and --no-preamble contradict each other")
        given[PREAMBLE] = []
    return given


ENVIRONMENTS = "paths.environments"


def where_environments_go(path: Path) -> str:
    """A place for environments as a person weighs it: writable, and its free space."""
    existing = paths.nearest_existing(path)
    free = settings.free_space(path)
    return (f"{path}  ({'writable' if existing and os.access(existing, os.W_OK) else 'NOT writable'}"
            + (f", {free / 1e9:.0f} GB free" if free is not None else "") + ")")


def _proposals(ctx: Context, given: dict[str, Any], present: dict[str, Any]) -> dict[str, tuple[Any, str]]:
    """dotted key -> (value, where it came from), for every key the file lacks. A default
    is never proposed: it applies while the key is unset (config.md § 3.2)."""
    out = {k: (v, "given") for k, v in given.items() if k not in present}
    if "build.cuda_architectures" not in present and "build.cuda_architectures" not in out:
        archs, source = probe.gpu_architectures()
        if archs:
            out["build.cuda_architectures"] = (archs, f"measured by {source}")
    if "launch.mpi" not in present and "launch.mpi" not in out:
        kinds = catalogue.schedulers(ctx)
        kind, why = probe.detect_scheduler(kinds)
        if kind is not None:
            out["launch.mpi"] = (kinds[kind].mpi_launch, f"the {kind} scheduler kind's launcher ({why})")
    return out


def _issues(given: dict[str, Any], present: dict[str, Any], adding: dict[str, Any]) -> list[Issue]:
    issues = [Issue(severity="info", code="key-kept", subject=k, message=f"kept {k} = {text.show(v)}")
              for k, v in present.items()]
    issues += [Issue(severity="warning", code="value-ignored", subject=k,
                     message=f"{k} is already {text.show(present[k])}; the value given is ignored",
                     next=(view.command(CONFIG_SET, key=k, value=tomlkit.item(given[k]).as_string()),))
               for k in given if k in present and given[k] != present[k]]
    for dotted in settings.STATED:
        if dotted not in present and dotted not in adding:
            issues.append(Issue(severity="warning", code="stated-unset", subject=dotted,
                                message=f"{dotted} is unset; state it before preparing jobs on this machine",
                                next=stating(CONFIG_INIT, [dotted])))
    return issues


def _asks(ctx: Context, given: dict[str, Any], present: dict[str, Any]) -> tuple[Ask, ...]:
    """What config init asks on a terminal: the two values nothing on the machine reveals
    (config.md § 3.2). Neither is proposed; an empty answer leaves the key unset."""
    asks = []
    if ENVIRONMENTS not in present and ENVIRONMENTS not in given:
        asks.append(Ask(key=settings.key(ENVIRONMENTS).name, question="Where should engine environments go? (empty: the default)",
                        context=(f"default: {where_environments_go(dirs.environments_dir())}",
                                 "each takes gigabytes; on a cluster, project storage is usual, not a home quota")))
    if PREAMBLE not in present and PREAMBLE not in given:
        modules = ctx.env.get("LOADEDMODULES", "")
        asks.append(Ask(key=settings.key(PREAMBLE).name,
                        question="Which shell lines must a job here run before it enters an environment? "
                                 "One per line, then an empty line (none typed: it stays unset)",
                        context=(f"loaded modules: {modules.replace(':', ' ')}" if modules else
                                 "loaded modules: none listed by this shell",
                                 "a batch job starts a fresh shell: a `module load` that puts the manager on PATH "
                                 "belongs here; if nothing is needed, give --no-preamble instead")))
    if COMMAND not in present and COMMAND not in given:
        asks.append(Ask(key=option_name(settings.key(COMMAND)),
                        question="How does a shell here enter an environment, after those lines? "
                                 "source activate, conda activate or mamba activate (empty: it stays unset)",
                        context=("source activate: the activate script on PATH -- what a cluster's "
                                 "`module load mamba` provides",
                                 "conda activate / mamba activate: the manager's shell function; femkit sources "
                                 "its hook file first (<root>/etc/profile.d/conda.sh or mamba.sh)")))
    return tuple(asks)


@operation(CONFIG_INIT, result=InitOutcome, changes=True,
           subject=lambda req: ["config"])
class ConfigInit:
    """Write config.toml from its template, adding only keys it lacks; never replaces a value."""

    def plan(self, req, ctx: Context) -> Plan:
        present = settings.load(ctx).present()
        given = _given(req)
        proposals = _proposals(ctx, given, present)
        values = {k: v for k, (v, _) in proposals.items()}
        settings.with_values(values)  # refuses an invalid value before anything is asked
        steps = tuple(Step(id=f"add:{k}", describe=f"add {k} = {text.show(v)}  # {why}")
                      for k, (v, why) in proposals.items())
        issues = _issues(given, present, values)
        if ENVIRONMENTS not in present and ENVIRONMENTS not in values:
            issues.append(Issue(severity="info", code="default", subject=ENVIRONMENTS,
                                message=f"{ENVIRONMENTS} unset: environments go to the default, "
                                        f"{where_environments_go(dirs.environments_dir())}",
                                next=(view.command(CONFIG_INIT, note="to choose",
                                                   fills=[view.Fill(field="environments", label=ENVIRONMENTS, example="PATH")]),)))
        return Plan(basis={"present": sorted(present), "values": values},
                    steps=steps, issues=issues, asks=_asks(ctx, given, present))

    def apply(self, plan: Plan, ctx: Context, observer) -> InitOutcome:
        present = settings.load(ctx, fresh=True).present()
        if sorted(present) != plan.basis["present"]:
            raise PlanStale("config.toml changed since the plan", (view.command(CONFIG_INIT),))
        values = plan.basis["values"]

        def do(step: Step, where):
            dotted = step.id.removeprefix("add:")
            settings.write(settings.with_values({dotted: values[dotted]}))
            return "done", None

        status, log = run_steps(plan, ctx, observer, do)
        rows = []
        for k in settings.keys():
            if k.dotted in present:
                rows.append(InitRow(key=k.dotted, status="kept", value=present[k.dotted]))
            elif k.dotted in values:
                rows.append(InitRow(key=k.dotted, status="added", value=values[k.dotted]))
            else:
                rows.append(InitRow(key=k.dotted, status="unset", note=k.unset))
        return InitOutcome(plan=plan, status=status, log=str(log), file=str(settings.config_file()),
                           rows=rows, issues=[i for i in plan.issues if i.code != "key-kept"])
