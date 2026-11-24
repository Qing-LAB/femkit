"""The generic command-line adapter (api.md § 4).

Every command is built from the registry: its options from the request model,
its help from the docstring and field descriptions. Nothing here knows an
operation.
"""

from __future__ import annotations

import re
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import click
from pydantic.fields import FieldInfo

from femkit.core import commandline, process, text, view
from femkit.core.errors import ConsentDeclined, Refusal, UsageError
from femkit.core.operations import Ask, Context, Operation, Plan, Result, Step
from femkit.core.schema import described
from femkit.registry import operations


# ------------------------------------------------------------ fields to params

def _param(name: str, field: FieldInfo) -> click.Parameter:
    s = commandline.spelling(name, field)
    help_text = described(field)
    if s.kind == "argument":
        return click.Argument([name], nargs=-1 if s.many else 1, required=field.is_required())
    if s.kind == "flag":
        return click.Option([s.flag, name], is_flag=True, default=False, help=help_text)
    kind = {int: click.INT, float: click.FLOAT}.get(s.element, click.STRING)
    return click.Option([s.flag, name], type=kind, multiple=s.many, required=field.is_required(), default=None,
                        help=help_text)


def _again(op: Operation, req: Any) -> str:
    """The command that asked for ``req``, as a person types it (api.md § 4.4)."""
    return commandline.typed(commandline.words(op.name, op.request, req.model_dump(mode="json")))


def _request(op: Operation, values: dict) -> Any:
    data = {}
    for name, field in op.request.model_fields.items():
        value = values.get(name)
        if value is None or (isinstance(value, tuple) and not value and not field.is_required()):
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
    if as_json:
        click.echo(model.model_dump_json(indent=2))
    else:
        click.echo(_tagged(tag, model.text()))


TAIL = 12  # log lines shown under a step that did not finish


def took(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s:02d} s"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"


def _tail(log: Path) -> list[str]:
    try:
        return [line.rstrip() for line in process.tail(log, TAIL)]
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
            line = f"{indent}{took(time.monotonic() - started)} | {last_line(log)}"
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
                self._say(f"{run['head']} done in {took(seconds)}")
            return
        self._say(f"{run['head']} {outcome.upper()} after {took(seconds)}" + (f"; log: {text.path(log)}" if log else ""))
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
        click.echo(ask.question, err=True)
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
    shown either way: what is about to run is the context of everything printed after it."""
    if not plan.steps:
        return
    if yes:  # the steps alone: the findings come again with the outcome
        click.echo(_tagged(tag, plan.text(brief=True)), err=True)
        return
    if not _can_ask():
        raise ConsentDeclined("there is no terminal to ask on",
                              (view.shell(f"{again} --dry-run"), view.shell(f"{again} --yes")))
    click.echo(_tagged(tag, plan.text()), err=True)
    if not click.confirm("Proceed?", default=False, err=True):
        raise ConsentDeclined("declined; nothing was changed")


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
        else:
            lines = [f"refused: {exc}"] + text.next_block("instead", exc.next)
            click.echo(_tagged(tag, "\n".join(lines)), err=True)
        return 2
    except Exception as exc:  # a defect or an unavailable system (core.md § 9)
        click.echo(traceback.format_exc(), err=True)
        if getattr(exc, "femkit_log", None):
            click.echo(f"log: {exc.femkit_log}", err=True)
        return 1


def _command(verb: str, op: Operation) -> click.Command:
    params = [_param(name, field) for name, field in op.request.model_fields.items()]
    params.append(click.Option(["--json", "json_output"], is_flag=True, help="print one JSON document on stdout"))
    if op.changes:
        params.append(click.Option(["--dry-run"], is_flag=True, help="print the plan; change nothing"))
        params.append(click.Option(["--yes", "-y"], is_flag=True, help="consent in advance"))

    def callback(**values: Any) -> None:
        sys.exit(_execute(op, values))

    return click.Command(verb, params=params, callback=callback, help=op.doc, short_help=op.doc.split(". ")[0])


def build(ops: dict[str, Operation] | None = None) -> click.Group:
    root = click.Group("femkit", help="femkit — a solver-neutral finite-element workbench.")
    for name, op in (ops if ops is not None else operations()).items():
        group_name, _, verb = name.rpartition(".")
        if not group_name:
            root.add_command(_command(verb, op))
            continue
        group = root.commands.get(group_name)
        if group is None:
            group = click.Group(group_name)
            root.add_command(group)
        group.add_command(_command(verb, op))
    return root


def main() -> None:
    build()(prog_name=commandline.PROG)  # the form every printed command uses (api.md § 4.4)
