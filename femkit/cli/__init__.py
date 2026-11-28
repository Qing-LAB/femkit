"""The generic command-line adapter (api.md § 4).

Every command is built from the registry: its options from the request model,
its help from the docstring and field descriptions. Nothing here knows an
operation. A request the model refuses is refused by the operation's own
`request_from`, as the page's routes refuse it: each field by its argument or
option (`STUDY`, `--as NAME`), with what it takes, a closed list's choices named,
and the command again as its next step.
"""

from __future__ import annotations

import re
import shutil
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
from pydantic.fields import FieldInfo

from femkit.core import commandline, process, text, view
from femkit.core.errors import ConsentDeclined, Refusal, UsageError
from femkit.core.operations import Ask, Context, Operation, Plan, PlanAnswer, Result, Step
from femkit.core.schema import described, pointer
from femkit.registry import GROUPS, Group, group, offered, operations


# ------------------------------------------------------------ fields to params

def _manual(op: Operation) -> str | None:
    """The chapter of the manual the command group of ``op`` declares (api.md § 4); None for an
    operation of no declared group, a test's own."""
    found = group(op.name)
    return found.manual if found is not None else None


class _Option(click.Option):
    """A request field's option, its help the field's (api.md § 4.1), made when it is shown: the
    names a declaration holds are read then, never when the command is built (core.md § 2,
    `choices`)."""

    def __init__(self, decls: list[str], field: FieldInfo, manual: str | None, **attrs: Any) -> None:
        super().__init__(decls, **attrs)
        self.field, self.manual = field, manual

    def get_help_record(self, ctx: click.Context) -> tuple[str, str] | None:
        self.help = described(self.field, self.manual)
        return super().get_help_record(ctx)


def _param(name: str, field: FieldInfo, manual: str | None = None) -> click.Parameter:
    """A field's parameter (api.md § 4.1). It takes the words as typed — no type, nothing
    required — so every problem with them is the request model's, said as it is typed
    (`Operation.request_from`)."""
    s = commandline.spelling(name, field)
    if s.kind == "argument":   # its usage says what the request requires, which click is not asked to check
        shown = name.upper() if field.is_required() else f"[{name.upper()}]"
        return click.Argument([name], nargs=-1 if s.many else 1, required=False,
                              metavar=shown + ("..." if s.many else ""))
    if s.kind == "flag":
        return _Option([s.flag, name], field, manual, is_flag=True, default=False)
    return _Option([s.flag, name], field, manual, multiple=s.many, default=None,
                   metavar={int: "INTEGER", float: "FLOAT"}.get(s.element))


def _help(op: Operation) -> str:
    """The command's help: the operation's docstring, then each argument with its field's help —
    a positional argument has no help of its own (api.md § 4.1)."""
    arguments = [(name.upper(), described(field, _manual(op))) for name, field in op.request.model_fields.items()
                 if commandline.spelling(name, field).kind == "argument"]
    if not arguments:
        return op.doc
    width = max(len(name) for name, _ in arguments)
    return op.doc + "\n\n\b\nArguments:\n" + "\n".join(f"  {name:<{width}}  {says}" for name, says in arguments)


class _Ending:
    """A command's or a group's help, ending with the chapter of the manual its group declares
    (api.md § 4), read when the help is shown."""

    manual: str | None = None

    def format_epilog(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        self.epilog = pointer(self.manual) if self.manual else None
        super().format_epilog(ctx, formatter)   # type: ignore[misc]


class _Command(_Ending, click.Command):
    """An operation's command: its help — the operation's docstring and each argument's help — made
    when it is shown, so the names a declaration holds are read then (`_Option`)."""

    def __init__(self, verb: str, op: Operation, **attrs: Any) -> None:
        super().__init__(verb, **attrs)
        self.op, self.manual = op, _manual(op)

    def format_help_text(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        self.help = _help(self.op)
        super().format_help_text(ctx, formatter)


class _Group(_Ending, click.Group):
    """A command group: its one sentence, as the registry declares it (api.md § 6)."""

    def __init__(self, name: str, declared: Group | None) -> None:
        super().__init__(name, help=declared.sentence if declared is not None else None)
        self.manual = declared.manual if declared is not None else None


def _again(op: Operation, req: Any) -> str:
    """The command that asked for ``req``, as a person types it (api.md § 4.4)."""
    return commandline.typed(commandline.words(op.name, op.request, req.model_dump(mode="json", exclude_defaults=True)))


def _request(op: Operation, values: dict) -> Any:
    """The request from the words given, validated by the request model alone (api.md § 4.1); a
    field given none is left to the model: its default, or its refusal as missing — the one
    refusal of a bad request, which the page's routes give too (`Operation.request_from`)."""
    data = {}
    for name in op.request.model_fields:
        value = values.get(name)
        if value is None or value == ():
            continue
        if isinstance(value, tuple):
            value = list(value)
        data[name] = value
    return op.request_from(data)


# ------------------------------------------------------------------- output

def _tagged(tag: str, text: str) -> str:
    """The text with its first line tagged `[group verb]` (api.md § 4.4)."""
    first, _, rest = text.partition("\n")
    return f"[{tag}] {first}" + (f"\n{rest}" if rest else "")


def _emit(as_json: bool, model: Result | Plan, tag: str) -> None:
    """A result, or a plan — under `--json`, the one plan answer the page's `/plan` gives too
    (api.md § 4.4)."""
    if as_json:
        click.echo((PlanAnswer.of(model) if isinstance(model, Plan) else model).model_dump_json(indent=2))
    elif isinstance(model, Result) and model.report.blocks[:1] and isinstance(model.report.blocks[0], view.Code):
        click.echo(model.text())   # text to copy as it is, untagged (web.md § 7.7)
    else:
        click.echo(_tagged(tag, model.text()))


def _tail(log: Path) -> list[str]:
    try:
        return [line.rstrip() for line in process.tail(log, process.TAIL_LINES)]   # as the page shows it
    except OSError:
        return []


CONTROL = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\x00-\x1f\x7f]")  # a terminal's escapes and control characters
EVERY = 1.0  # seconds between two refreshes of the live line


def last_line(log: Path) -> str:
    """The log's last line as a person reads it: a progress bar's last frame, without the
    terminal's codes."""
    try:
        lines = [CONTROL.sub("", part).strip() for line in process.tail(log, 3) for part in line.split("\r")]
    except OSError:
        return ""
    return next((line for line in reversed(lines) if line), "")


class TerminalObserver:
    """Progress to stderr, so stdout holds only the result (api.md § 4.4): each operation says how many steps it has and where its logs are; each
    step is numbered, says what it does, and ends with its outcome and how long it took; a
    step that did not finish shows where its log is and how the log ends. An operation run
    inside another's step is indented under it. On a terminal, a running step whose log it
    was told of shows one live line — its time so far and its log's last line — rewritten in
    place and erased before anything else is printed."""

    def __init__(self, live: bool | None = None) -> None:
        self.runs: list[dict] = []  # one per operation in progress, innermost last
        self.live = sys.stderr.isatty() if live is None else live
        self.lock = threading.Lock()
        self.shown = False  # a live line is on the screen
        self.watching: tuple[Path, float, str] | None = None  # (log, started, indent)
        self.stop = threading.Event()
        self.ticker: threading.Thread | None = None

    def _erase(self) -> None:
        if self.shown:
            click.echo("\r\x1b[K", nl=False, err=True, color=True)  # its codes kept: shown only on a terminal
            self.shown = False

    def _say(self, text: str) -> None:
        with self.lock:
            self._erase()
            click.echo("    " * (len(self.runs) - 1) + text, err=True)

    def refresh(self) -> None:
        """Rewrite the live line: the running step's time so far and its log's last line."""
        with self.lock:
            if not self.watching:
                return
            log, started, indent = self.watching
            line = f"{indent}{text.duration(time.monotonic() - started)} | {last_line(log)}"
            width = shutil.get_terminal_size().columns - 1
            click.echo("\r\x1b[K" + (line if len(line) <= width else line[:width - 1] + "…"), nl=False, err=True, color=True)
            self.shown = True

    def _tick(self) -> None:
        while not self.stop.wait(EVERY):
            self.refresh()

    def step_log(self, log: Path) -> None:
        if not self.live:
            return
        self.watching = (log, self.runs[-1].get("started", time.monotonic()), "    " * (len(self.runs) - 1) + "      ")
        if self.ticker is None:
            self.ticker = threading.Thread(target=self._tick, daemon=True)
            self.ticker.start()

    def _unwatch(self) -> None:
        with self.lock:
            self.watching = None
            self._erase()

    def operation_start(self, plan: Plan, where: Path) -> None:
        self._unwatch()  # the live line belongs to the innermost running step
        self.runs.append({"total": len(plan.steps)})
        if plan.steps:  # `[group verb]`, as a refusal reads; the log folder names what it acts on
            n = len(plan.steps)
            self._say(f"[{plan.operation.replace('.', ' ')}] {text.count(n, 'step')}; "
                      f"logs in {text.path(where)}")

    def step_start(self, step: Step, index: int, total: int) -> None:
        run = self.runs[-1]
        run.update(head=f"[{index:>{len(str(total))}}/{total}]", started=time.monotonic())
        self._say(f"{run['head']} {step.describe}")

    def step_end(self, step: Step, outcome: str, log: Path | None) -> None:
        self._unwatch()
        run = self.runs[-1]
        seconds = time.monotonic() - run.get("started", time.monotonic())
        if outcome == "done":
            if seconds >= 1:  # a step done at once needs no second line
                self._say(f"{run['head']} done in {text.duration(seconds)}")
            return
        self._say(f"{run['head']} {outcome.upper()} after {text.duration(seconds)}" + (f"; log: {text.path(log)}" if log else ""))
        for line in _tail(log) if log else []:
            self._say(f"      | {line}")

    def note(self, text: str) -> None:
        self._say(f"      {text}")

    def operation_end(self, plan: Plan, status: str) -> None:
        self._unwatch()
        self.runs.pop()
        if not self.runs and self.ticker is not None:
            self.stop.set()
            self.ticker = None
            self.stop = threading.Event()


def _can_ask() -> bool:
    return sys.stdin.isatty()


def _read(is_list: bool) -> Any:
    """One answer as typed: a line, or for a list a line per item ended by an empty line."""
    if not is_list:
        return click.prompt(" ", default="", show_default=False, err=True).strip() or None
    lines = []
    while given := click.prompt(" ", default="", show_default=False, err=True).strip():
        lines.append(given)
    return lines or None


def _answer(op: Operation, ask: Ask, req: Any) -> Any:
    """Ask one question on the terminal (api.md § 3.1); an empty answer is no answer. An answer
    is checked as it is given: one holding characters that are not text — an arrow or erase key
    the terminal passed through — or one the request refuses is said, visibly, and asked again."""
    is_list = commandline.spelling(ask.key, op.request.model_fields[ask.key]).many
    click.echo("", err=True)
    for line in ask.context:
        click.echo(f"  {line}", err=True)
    while True:
        click.echo(f"{ask.question}  ({'a line each, then an empty line; ' if is_list else ''}nothing typed: no answer)",
                   err=True)
        given = _read(is_list)
        if given is None:
            return None
        if bad := [v for v in (given if is_list else [given]) if not v.isprintable()]:
            click.echo(f"  ! {bad[0]!r} holds characters that are not text (an arrow or erase key?); "
                       "type it again, or nothing for no answer", err=True)
            continue
        try:
            _request(op, {**req.model_dump(), ask.key: given})
            return given
        except UsageError as exc:
            click.echo(f"  ! {exc}; type it again, or nothing for no answer", err=True)


def _asked(op: Operation, req: Any, plan: Plan, ctx: Context) -> tuple[Any, Plan]:
    """The plan's questions answered, and the plan made again from the answers."""
    answers = {a.key: v for a in plan.asks if (v := _answer(op, a, req)) is not None}
    if not answers:
        return req, plan
    req = _request(op, {**req.model_dump(), **answers})
    return req, op.plan(req, ctx)


def _consent(plan: Plan, yes: bool, tag: str, again: str) -> None:
    """An empty plan needs no consent; otherwise --yes, or a yes on a terminal. The plan is
    shown either way: what is about to run is the context of everything printed after it. Without
    a terminal, refused, offering the command again with each of the command line's own options
    that does without one, as `OWN` declares them."""
    if not plan.steps:
        return
    if yes:  # the steps alone: the findings come again with the outcome
        click.echo(_tagged(tag, plan.text(brief=True)), err=True)
        return
    if not _can_ask():
        raise ConsentDeclined("there is no terminal to ask on",
                              tuple(view.shell(f"{again} {OWN[o].flags[0]}", note=OWN[o].help) for o in WITHOUT_ASKING),
                              code="no-terminal", subject=plan.operation)
    click.echo(_tagged(tag, plan.text()), err=True)
    if not click.confirm("Proceed?", default=False, err=True):
        raise ConsentDeclined("declined; nothing was changed", code="declined", subject=plan.operation)


def _execute(op: Operation, values: dict) -> int:
    tag = op.name.replace(".", " ")
    as_json = values.pop("json_output", False)
    dry_run = values.pop("dry_run", False)
    yes = values.pop("yes", False)
    ctx = Context.from_process()
    try:
        req = _request(op, values)
        if not op.changes:
            result = op.run(req, ctx)
            _emit(as_json, result, tag)
            return 0 if result.ok() else 1
        plan = op.plan(req, ctx)
        if dry_run:
            _emit(as_json, plan, tag)
            return 0
        if plan.asks and not yes and _can_ask():
            req, plan = _asked(op, req, plan, ctx)
        _consent(plan, yes, tag, _again(op, req))
        outcome = op.apply(plan, ctx, TerminalObserver())  # an empty plan too: the result is always an outcome
        _emit(as_json, outcome, tag)
        return 0 if outcome.ok() else 1
    except Refusal as exc:
        if as_json:
            click.echo(view.RefusalAnswer.of(exc).model_dump_json(indent=2))
        else:   # the findings it rests on before its sentence (core.md § 9)
            lines = [f"refused: {exc}"] + text.next_block("instead", exc.next)
            click.echo("\n".join([*text.findings(exc.issues), _tagged(tag, "\n".join(lines))]), err=True)
        return 2
    except Exception as exc:  # a defect or an unavailable system (core.md § 9): the surface's one report of it
        click.echo(traceback.format_exc(), err=True)
        if getattr(exc, "femkit_log", None):
            click.echo(f"log: {exc.femkit_log}", err=True)
        if as_json:   # stdout holds exactly one document (api.md § 4.2)
            click.echo(view.DefectAnswer.of(exc).model_dump_json(indent=2))
        return 1


@dataclass(frozen=True)
class Own:
    """One of the command line's own options (api.md § 4.2): its spellings, its help, and whether
    only a changing command has it."""

    flags: tuple[str, ...]
    help: str
    changing: bool


#: The command line's own options, by the name its callback is handed each by (api.md § 4.2): the
#: one declaration every command's options are built from and a refusal names them by.
OWN = {
    "json_output": Own(("--json",), "print one JSON document on stdout", changing=False),
    "dry_run": Own(("--dry-run",), "print the plan; change nothing", changing=True),
    "yes": Own(("--yes", "-y"), "consent in advance", changing=True),
}
#: Those that let a changing command go on without a terminal to ask on.
WITHOUT_ASKING = ("dry_run", "yes")


def _command(verb: str, op: Operation) -> click.Command:
    params = [_param(name, field, _manual(op)) for name, field in op.request.model_fields.items()]
    params += [click.Option([*own.flags, name], is_flag=True, help=own.help)
               for name, own in OWN.items() if op.changes or not own.changing]

    def callback(**values: Any) -> None:
        sys.exit(_execute(op, values))

    return _Command(verb, op, params=params, callback=callback, short_help=op.doc.split(". ")[0])


def build(ops: dict[str, Operation] | None = None) -> click.Group:
    """femkit's command line: one group per name prefix, one command per operation (api.md § 4) —
    femkit's own group, `""`, holding the commands of none."""
    root = _Group("femkit", GROUPS.get(""))
    for name, op in offered(ops if ops is not None else operations(), "cli").items():
        group_name, _, verb = name.rpartition(".")
        if not group_name:
            root.add_command(_command(verb, op))
            continue
        holding = root.commands.get(group_name)
        if holding is None:
            holding = _Group(group_name, GROUPS.get(group_name))
            root.add_command(holding)
        holding.add_command(_command(verb, op))
    return root


def main() -> None:
    build()(prog_name=commandline.PROG)  # the form every printed command uses (api.md § 4.4)
