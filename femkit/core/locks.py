"""Per-subject locks (core.md § 5): exclusive, non-blocking, released by the kernel."""

from __future__ import annotations

import fcntl
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from femkit.core import dirs
from femkit.core.errors import Busy


def lock_path(subject: str):
    return dirs.data_dir() / "locks" / f"{subject}.lock"


def is_held(subject: str) -> bool:
    """Whether a live process holds the subject's lock — observed, never decided from the file's text."""
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


_held: dict[str, int] = {}  # subject -> the descriptor this process holds its lock on


def _label(fd: int) -> None:
    os.ftruncate(fd, 0)
    os.pwrite(fd, f"pid {os.getpid()}: {' '.join(sys.argv)}\n".encode(), 0)


@contextmanager
def subject_lock(subject: str) -> Iterator[None]:
    path = lock_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = os.pread(fd, 4096, 0).decode("utf-8", "replace").strip() or "unknown"
            raise Busy(f"{subject} is in use by {holder}") from None
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


def adopt(fd: int) -> None:
    """Take over a lock handed to this process: its file now names this process."""
    _label(fd)


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
