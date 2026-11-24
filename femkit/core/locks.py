"""Per-subject locks (core.md § 5): held alone or shared, non-blocking, released by the kernel."""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from femkit.core import dirs
from femkit.core.errors import Busy
from femkit.core.process import Identity, identify

#: A subject's name — `env-ngsolve`, `machine-Sol`, `server-<host>-8000` — which its lock file and its
#: operations' folder are called (core.md § 5).
SUBJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def root() -> Path:
    """`<data>/locks/`: every subject's lock file (core.md § 5)."""
    return dirs.data_dir() / "locks"


def lock_path(subject: str) -> Path:
    if not SUBJECT.fullmatch(subject):
        raise ValueError(f"{subject!r} is no subject (core.md § 5)")
    return root() / f"{subject}.lock"


def is_held(subject: str) -> bool:
    """Whether a live process holds the subject's lock alone — is changing it; observed, never
    decided from the file's text. A shared hold is a use, and leaves this False."""
    path = lock_path(subject)
    if not path.exists():
        return False
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def require_free(subject: str) -> None:
    """Refused, naming every live holder and the commands that end its hold, while any process
    holds the subject's lock — alone or shared; takes nothing. The process that holds it is
    not refused by its own lock."""
    path = lock_path(subject)
    if subject in _held or not path.exists():
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise _busy(subject, fd) from None
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


_held: dict[str, int] = {}  # subject -> the descriptor this process holds its lock on


def _label(fd: int, by: str | None = None, next: Iterable[dict] = ()) -> None:
    """This process's line in the lock's file: a holder alone rewrites it, a shared holder (its
    descriptor opened to append) adds its line. ``next``: each action that ends the hold, as
    its JSON — so a process that writes one need not import the vocabulary."""
    line = json.dumps({"process": identify(os.getpid()).as_json(), "by": by or " ".join(sys.argv),
                       "next": list(next)}) + "\n"
    if not fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_APPEND:
        os.ftruncate(fd, 0)
    os.pwrite(fd, line.encode(), 0)                       # with O_APPEND, at the end


def _busy(subject: str, fd: int) -> Busy:
    """Busy naming the holders the file names that still run — each one's last line — and
    offering the commands that end their holds; what the file says only names, never decides."""
    from pydantic import ValidationError
    from femkit.core.view import Action
    said: dict[object, dict] = {}
    for raw in os.pread(fd, 1 << 16, 0).decode("utf-8", "replace").splitlines():
        try:
            line = json.loads(raw)
            said[Identity.from_json(line["process"])] = line
        except (ValueError, KeyError, TypeError):
            if raw.strip():
                said[raw] = {"by": raw.strip()}          # a line it cannot read: named as it is
    live = [(k, v) for k, v in said.items() if not isinstance(k, Identity) or k.alive()]
    who = "; ".join(f"{v.get('by')} (pid {k.pid})" if isinstance(k, Identity) else str(v["by"]) for k, v in live)
    steps: list[Action] = []
    for _, v in live:
        written = v.get("next")
        for c in written if isinstance(written, list) else []:
            try:
                steps.append(Action.model_validate(c))
            except ValidationError:                      # one it cannot read offers nothing
                pass
    return Busy(f"{subject} is in use by {who or 'another process'}", {s.command: s for s in steps}.values(),
                code="held", subject=subject)


@contextmanager
def subject_lock(subject: str, *, shared: bool = False) -> Iterator[None]:
    """The subject's lock, held alone — to change the subject — or ``shared``, to use it while
    others may use it too (core.md § 5)."""
    path = lock_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | (os.O_APPEND if shared else 0), 0o644)
    try:
        try:
            fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise _busy(subject, fd) from None
        _label(fd)
        _held[subject] = fd
        yield
    finally:
        _held.pop(subject, None)
        os.close(fd)  # closing releases the lock, unless a process it was handed to still holds it


def held_fd(subject: str) -> int:
    """The descriptor this process holds ``subject``'s lock on, to hand to a process it
    starts (`process.start_detached(keep_fds=...)`): the lock then stays held for as long
    as either holds it, and the receiver ``adopt``s it."""
    return _held[subject]


def adopt(fd: int, by: str | None = None, next: Iterable[dict] = ()) -> None:
    """Take over a lock handed to this process, or name a hold anew: its file now names this
    process as ``by``, with the actions that end its hold, each as its JSON."""
    _label(fd, by, next)


def holders() -> dict[str, int]:
    """Each subject whose lock a process holds now, and that process's ID, as the kernel's
    lock table says — never read from a lock file's text."""
    folder = root()
    if not folder.is_dir():
        return {}
    by_inode = {}
    for path in folder.glob("*.lock"):
        try:
            info = path.stat()
        except OSError:
            continue
        by_inode[(os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)] = path.stem
    found: dict[str, int] = {}
    for line in Path("/proc/locks").read_text().splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[1] != "FLOCK" or parts[0].endswith("->"):
            continue  # "->" marks a waiter, not a holder
        major, minor, inode = parts[5].split(":")
        subject = by_inode.get((int(major, 16), int(minor, 16), int(inode)))
        if subject is not None:
            found[subject] = int(parts[4])
    return found
