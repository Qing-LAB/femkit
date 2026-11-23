"""Per-subject locks (core.md § 5): exclusive, non-blocking, released by the kernel."""

from __future__ import annotations

import fcntl
import os
import sys
from contextlib import contextmanager
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
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"pid {os.getpid()}: {' '.join(sys.argv)}\n".encode(), 0)
        yield
    finally:
        os.close(fd)  # closing releases the lock
