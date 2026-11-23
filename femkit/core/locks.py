"""Per-subject locks (core.md § 5): held alone or shared, non-blocking, released by the kernel."""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from femkit.core import dirs
from femkit.core.errors import Busy


def lock_path(subject: str):
    return dirs.data_dir() / "locks" / f"{subject}.lock"


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


def _label(fd: int, by: str | None = None, next: tuple[str, ...] = ()) -> None:
    """This process's line in the lock's file: a holder alone rewrites it, a shared holder (its
    descriptor opened to append) adds its line."""
    line = json.dumps({"pid": os.getpid(), "by": by or " ".join(sys.argv), "next": list(next)}) + "\n"
    if not fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_APPEND:
        os.ftruncate(fd, 0)
    os.pwrite(fd, line.encode(), 0)                       # with O_APPEND, at the end


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


OLD_LINE = re.compile(r"pid (\d+): (.*)")


def _busy(subject: str, fd: int) -> Busy:
    """Busy naming the holders the file names that still run — each one's last line — and
    offering the commands that end their holds; what the file says only names, never decides."""
    said: dict[object, dict] = {}
    for raw in os.pread(fd, 1 << 16, 0).decode("utf-8", "replace").splitlines():
        try:
            line = json.loads(raw)
            said[int(line["pid"])] = line
        except (ValueError, KeyError, TypeError):
            old = OLD_LINE.fullmatch(raw.strip())          # written before holders named their ends
            if old:
                said[int(old[1])] = {"by": old[2], "next": []}
            elif raw.strip():
                said[raw] = {"by": raw.strip(), "next": []}
    live = [(k, v) for k, v in said.items() if not isinstance(k, int) or _alive(k)]
    who = "; ".join(f"{v.get('by')} (pid {k})" if isinstance(k, int) else str(v["by"]) for k, v in live)
    next_ = tuple(dict.fromkeys(str(c) for _, v in live for c in v.get("next") or []))
    return Busy(f"{subject} is in use by {who or 'another process'}", next_)


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


def adopt(fd: int, by: str | None = None, next: tuple[str, ...] = ()) -> None:
    """Take over a lock handed to this process, or name a hold anew: its file now names this
    process as ``by``, with the commands that end its hold."""
    _label(fd, by, next)


def holders() -> dict[str, int]:
    """Each subject whose lock a process holds now, and that process's ID, as the kernel's
    lock table says — never read from a lock file's text."""
    root = dirs.data_dir() / "locks"
    if not root.is_dir():
        return {}
    by_inode = {}
    for path in root.glob("*.lock"):
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
