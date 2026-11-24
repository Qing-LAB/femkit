"""Transactions and undo (projects.md § 7).

A change is one transaction: a list of file steps — create, change, move, delete — computed in
the plan with nothing written. The plan reads the project as the change would leave it (the
caller's ``check``) and refuses a change that would leave a part it touches unloadable or a
reference into one broken, naming each problem. Apply holds the project's lock, refuses when a
file the plan read changed since (by its hash), and writes every step or none. A group folder is
made by the first part written into it and removed with the last part moved or removed out of it.
Each transaction records each file's text before and after, and each move, in
`.femkit/history/`; `undo` and `redo` move through as many as `projects.undo` says, refused when
a file has changed since by hand. A record names files by their path in the project.

Every path is formed by `Project.path`; every write goes through `core/persist.py`; the lock is
`core/locks.subject_lock(project.subject)`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Literal

from pydantic import Field, model_validator

from femkit.config import settings
from femkit.core import locks, persist
from femkit.core.errors import PlanStale, Refused, UsageError
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, Model, validate
from femkit.projects.project import LOCAL, Project

#: The overlay a check reads: each touched path's text as the change leaves it, None when deleted.
Overlay = dict[str, "str | None"]
#: What a check finds: (where — an address or a path — and why), each a reason to refuse.
Check = Callable[[Overlay], "list[tuple[str, str]]"]

Kind = Literal["create", "change", "move", "delete"]
#: Whether each kind of step gives its text, and whether it gives a `to`.
SHAPE: dict[str, tuple[bool, bool]] = {"create": (True, False), "change": (True, False),
                                       "move": (False, True), "delete": (False, False)}
HISTORY = f"{LOCAL}/history/history.json"   # local to this copy of the project (projects.md § 2)


@dataclass(frozen=True)
class FileStep:
    kind: Kind
    path: str                   # POSIX, relative to the project's folder
    text: str | None = None     # create, change: the file's whole new text
    to: str | None = None       # move: where it goes, relative too


@dataclass(frozen=True)
class Transaction:
    project: Project
    steps: tuple[FileStep, ...]
    basis: dict[str, str | None] = field(default_factory=dict)   # each file read: its sha256, None if absent
    describe: str = ""                                           # one line a person reads: what the change does


class Done(Model):
    """One step as a transaction wrote it, with its file's text before and after — a move, its
    file's hash, whatever the file holds (projects.md § 7)."""

    kind: Kind
    path: str = Field(description="its file, by its path in the project")
    to: str | None = Field(default=None, description="a move's new path in the project")
    before: str | None = Field(default=None, description="the file's text before the step; none: no file was there")
    after: str | None = Field(default=None, description="its text after the step; none: removed")
    sha: str | None = Field(default=None, description="a move's file: its sha256, its bytes as they are")

    @model_validator(mode="after")
    def _shape(self) -> "Done":
        if (self.kind == "move") != (self.to is not None and self.sha is not None):
            raise ValueError("a move, and only a move, names where it goes and its file's hash")
        if self.kind in ("create", "change") and self.after is None or self.kind in ("change", "delete") and self.before is None:
            raise ValueError(f"a {self.kind} records its file's text {'before' if self.kind == 'delete' else 'after'}")
        return self


class Record(Model):
    describe: str = Field(description="what the transaction did, as its plan says it")
    steps: list[Done] = Field(description="each step, in the order written")


class Pending(Model):
    """A change begun and not yet done: written before its first file, so a process killed
    midway leaves what puts every file back (projects.md § 7: every step or none)."""

    steps: list[Done] = Field(description="the steps as recorded, in the order taken")
    back: bool = Field(description="taken back, as undo takes a transaction back")


class History(Model):
    """`.femkit/history/history.json`: a project's transactions, for undo and redo (projects.md § 7)."""

    transactions: list[Record] = Field(default_factory=list, description="oldest first")
    at: int = Field(default=0, ge=0, description="how many of them stand: the rest were undone")
    pending: Pending | None = Field(default=None, description="a change begun and not done; put back first")


def digest(path: Path) -> str | None:
    """A file's sha256 over its bytes, None when no file is there: what a transaction's basis
    holds for each file read (projects.md § 7)."""
    return persist.sha256(path)


def sha(text: str | None) -> str | None:
    """A text's sha256 as its file holds it — UTF-8 — the same as `digest` of that file."""
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan(project: Project, steps: list[FileStep], *, read: dict[str, str | None], check: Check,
         describe: str = "") -> Transaction:
    """The transaction of ``steps``, nothing written. ``read`` holds the hash of every file the
    caller read to compute the steps (the opened project's); the touched files' are added. Refused
    (`Refused`, code `change-breaks`) when ``check`` finds a problem in the project as the change
    leaves it; a step outside the project, a create over a file, a change or delete of no file,
    or a move onto a file is refused (`UsageError`, code `bad-step`)."""
    traced = _trace(project, steps)
    before, after = _states(traced)
    sources = {d.to: d.path for d in traced if d.kind == "move"}
    problems = check({p: _readable(project, sources[p]) if isinstance(t, Moved) else t for p, t in after.items()})
    if problems:
        raise Refused("the change would leave " + "; ".join(f"{where}: {why}" for where, why in problems),
                      code="change-breaks", subject=", ".join(dict.fromkeys(where for where, _ in problems)))
    basis = dict(read)
    for path, held in before.items():
        basis.setdefault(path, str(held) if isinstance(held, Moved) else sha(held))
    return Transaction(project, tuple(steps), basis, describe)


def apply(tx: Transaction, ctx: Context) -> None:
    """Every step or none, under the project's lock; `PlanStale` (code `files-changed`, naming
    the files) when a file in ``tx.basis`` changed since; recorded for undo, the history kept to
    `projects.undo` transactions (config.md § 3)."""
    project, limit = tx.project, settings.undo_limit(settings.load(ctx).config)
    with locks.subject_lock(project.subject):                  # held already by its operation's runner: kept
        changed = sorted(p for p, sha in tx.basis.items() if digest(project.path(p)) != sha)
        if changed:
            raise PlanStale(f"{', '.join(changed)} changed since the plan; plan the change again",
                            code="files-changed", subject=", ".join(changed))
        history = _history(project, limit)
        kept = [*history.transactions[:history.at], Record(describe=tx.describe, steps=_trace(project, tx.steps))]
        kept = kept[-limit:]
        _write(project, kept[-1].steps, back=False, history=History(transactions=kept, at=len(kept)), before=history)


def undo(project: Project, ctx: Context) -> Transaction:
    """The newest transaction not undone, taken back, under the project's lock, and returned as
    what was done. Refused (`Refused`, code `nothing-to-undo`) when none is left within
    `projects.undo`; (`Refused`, code `changed-by-hand`, naming the files) when a file differs
    from what that transaction left."""
    return _turn(project, ctx, back=True)


def redo(project: Project, ctx: Context) -> Transaction:
    """The newest undone transaction, done again; refused as `undo` is (`nothing-to-redo`,
    `changed-by-hand`). A new transaction after an undo drops what could be redone."""
    return _turn(project, ctx, back=False)


# ------------------------------------------------------------------ the steps

def _bad(step: FileStep, why: str) -> UsageError:
    return UsageError(f"the {step.kind} of {step.path!r} {why}", code="bad-step", subject=str(step.path))


def _trace(project: Project, steps: list[FileStep] | tuple[FileStep, ...]) -> list[Done]:
    """Each step as it would be written, read from the files as they are and as the steps before
    it leave them; a step that cannot be written is refused (`bad-step`)."""
    now: dict[str, str | None] = {}
    opaque: dict[str, str] = {}                                # a file holding no text: its hash, where it is now

    def text(step: FileStep, path: str) -> str | None:
        if path in opaque and step.kind != "move":
            raise _bad(step, f"meets {path!r}, which holds no text")
        if path not in now:
            try:
                where = project.path(path)
            except UsageError:
                raise _bad(step, f"names {path!r}, no path inside the project") from None
            if PurePosixPath(path).parts[0] == LOCAL:          # femkit's own: the history a change is recorded in
                raise _bad(step, f"names {path!r}, in {LOCAL}/, which no change writes")
            if where.exists() and not where.is_file():
                raise _bad(step, f"meets {path!r}, which is no file")
            try:
                now[path] = _text(where)
            except UnicodeDecodeError:
                if not (step.kind == "move" and path == step.path):
                    raise _bad(step, f"meets {path!r}, which holds no text") from None
                now[path], opaque[path] = "", digest(where)      # a move takes the file whatever it holds
        return now[path]

    done = []
    for step in steps:
        if (step.text is not None, step.to is not None) != SHAPE.get(step.kind):
            raise _bad(step, "is malformed: a create or a change gives its text, a move its `to`, a delete neither")
        before = text(step, step.path)
        if step.kind == "create" and before is not None:
            raise _bad(step, "would write over a file")
        if step.kind != "create" and before is None:
            raise _bad(step, "finds no file")
        if step.kind == "move":
            if text(step, step.to) is not None:
                raise _bad(step, f"would move it onto the file {step.to!r}")
            held = opaque.pop(step.path, None) or sha(before)
            if step.path in opaque or held != sha(before):
                opaque[step.to] = held
            now[step.path], now[step.to] = None, before
            done.append(Done(kind="move", path=step.path, to=step.to, sha=held))
            continue
        after = {"create": step.text, "change": step.text, "delete": None}[step.kind]
        now[step.path] = after
        done.append(Done(kind=step.kind, path=step.path, before=before, after=after))
    return done


class Moved(str):
    """A moved file's expected content: its hash, not its text — it may hold anything."""


def _states(steps: list[Done]) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """Each file a transaction touches, by its path: its text before the transaction, and after
    — a moved file's, its hash (`Moved`)."""
    before: dict[str, str | None] = {}
    after: dict[str, str | None] = {}
    for d in steps:
        before.setdefault(d.path, Moved(d.sha) if d.kind == "move" else d.before)
        after[d.path] = None if d.kind in ("move", "delete") else d.after
        if d.kind == "move":
            before.setdefault(d.to, None)
            after[d.to] = Moved(d.sha)
    return before, after


def _matches(project: Project, path: str, expected: str | None) -> bool:
    found = digest(project.path(path))
    return found == (str(expected) if isinstance(expected, Moved) else sha(expected))


def _forward(d: Done) -> FileStep:
    return FileStep(d.kind, d.path, text=d.after if d.kind in ("create", "change") else None, to=d.to)


def _backward(d: Done) -> FileStep:
    if d.kind == "move":
        return FileStep("move", d.to, to=d.path)
    if d.kind == "create":
        return FileStep("delete", d.path)
    return FileStep("create" if d.kind == "delete" else "change", d.path, text=d.before)


def _act(project: Project, step: FileStep) -> None:
    where = project.path(step.path)
    if step.kind == "move":
        persist.move(where, project.path(step.to))
    elif step.kind == "delete":
        persist.remove(where)
    else:
        persist.atomic_write_text(where, step.text)


def _prune(project: Project, steps: list[FileStep]) -> None:
    """Each folder a step moved or removed the last file out of, removed, and each emptied above
    it — never a top-level folder of the project: no empty group is left behind (projects.md § 7)."""
    for step in steps:
        if step.kind in ("move", "delete"):
            top = PurePosixPath(step.path).parts[0]
            persist.remove_empty_folders(project.path(step.path).parent, project.path(top))


def _write(project: Project, steps: list[Done], *, back: bool, history: History, before: History) -> None:
    """``steps`` written in order — or taken back, newest first. The change is recorded as pending
    first, and ``history`` saved last, the commit point: when the file system refuses any of it,
    each step already written is put back and the error raised; when the process is killed
    midway, the next change puts every file back first (`_history`) — every step or none
    (projects.md § 7)."""
    order = steps[::-1] if back else steps
    there, again = (_backward, _forward) if back else (_forward, _backward)
    written: list[Done] = []
    persist.write_json(project.path(HISTORY), before.model_copy(
        update={"pending": Pending(steps=steps, back=back)}).model_dump(mode="json"))
    try:
        for d in order:
            _act(project, there(d))
            written.append(d)
        _prune(project, [there(d) for d in order])
        persist.write_json(project.path(HISTORY), history.model_dump(mode="json"))
    except OSError:
        for d in reversed(written):
            _act(project, again(d))
        _prune(project, [again(d) for d in written])
        persist.write_json(project.path(HISTORY), before.model_dump(mode="json"))
        raise


def _put_back(project: Project, pending: Pending) -> None:
    """A change a killed process left half done, undone whatever part of it was written: each
    file made as it was before the change began (projects.md § 7)."""
    steps = pending.steps
    if not pending.back:                                   # it was going forward: back to each `before`
        for d in reversed(steps):
            if d.kind == "move":
                if project.path(d.to).exists() and not project.path(d.path).exists():
                    persist.move(project.path(d.to), project.path(d.path))
            elif d.before is None:
                persist.remove(project.path(d.path))
            else:
                persist.atomic_write_text(project.path(d.path), d.before)
    else:                                                  # it was going back: forward to each `after`
        for d in steps:
            if d.kind == "move":
                if project.path(d.path).exists() and not project.path(d.to).exists():
                    persist.move(project.path(d.path), project.path(d.to))
            elif d.after is None:
                persist.remove(project.path(d.path))
            else:
                persist.atomic_write_text(project.path(d.path), d.after)
    _prune(project, [FileStep("delete", d.to if d.kind == "move" else d.path) for d in steps])


# ------------------------------------------------------------------ undo and redo

def _history(project: Project, limit: int) -> History:
    """The project's history — a change a killed process left half done put back first — the
    newest ``limit`` transactions that stand kept, and those undone after them while room is
    left. Read under the project's lock."""
    path = project.path(HISTORY)
    if not path.is_file():
        return History()
    try:
        held = validate(History, persist.read_json(path), path)
    except (ValueError, DefinitionError) as exc:
        raise Refused(f"{project.name}'s undo history does not load, so no change is made: {exc}",
                      code="history-unreadable", subject=HISTORY) from None
    if held.pending is not None:
        _put_back(project, held.pending)
        held = held.model_copy(update={"pending": None})
        persist.write_json(path, held.model_dump(mode="json"))
    standing = held.transactions[:held.at][-limit:]
    undone = held.transactions[held.at:][:limit - len(standing)]
    return History(transactions=[*standing, *undone], at=len(standing))


def _turn(project: Project, ctx: Context, *, back: bool) -> Transaction:
    """Undo (``back``) or redo: one transaction taken back or done again, when every file it
    touched is as it left it — or, to redo, as it found it (projects.md § 7)."""
    limit = settings.undo_limit(settings.load(ctx).config)
    what = "undo" if back else "redo"
    with locks.subject_lock(project.subject):
        history = _history(project, limit)
        i = history.at - 1 if back else history.at
        if not 0 <= i < len(history.transactions):
            raise Refused(f"{project.name} has nothing to {what} within its last {limit} transactions "
                          "(projects.undo)", code=f"nothing-to-{what}", subject=project.name)
        record = history.transactions[i]
        before, after = _states(record.steps)
        expected = after if back else before
        # each path formed by Project.path before anything is written: a record names no file outside
        changed = sorted(p for p, held in expected.items() if not _matches(project, p, held))
        if changed:
            raise Refused(f"{', '.join(changed)} changed by hand since `{record.describe}`, so it is not "
                          f"{'undone' if back else 'redone'}", code="changed-by-hand", subject=", ".join(changed))
        _write(project, record.steps, back=back, history=history.model_copy(update={"at": i if back else i + 1}),
               before=history)
    steps = [_backward(d) for d in reversed(record.steps)] if back else [_forward(d) for d in record.steps]
    return Transaction(project, tuple(steps), {p: str(t) if isinstance(t, Moved) else sha(t)
                                               for p, t in expected.items()}, record.describe)


# ------------------------------------------------------------------ reading

def _text(path: Path) -> str | None:
    return persist.read_text(path)


def _readable(project: Project, path: str) -> str:
    """A moved file's text, as a check reads a part; a file holding no text, as no part does, empty."""
    try:
        return _text(project.path(path)) or ""
    except UnicodeDecodeError:
        return ""
