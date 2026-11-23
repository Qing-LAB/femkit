"""Atomic writes and reads (core.md § 4). Every file femkit writes goes through here."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import tomllib
from pathlib import Path
from typing import IO, Any

import tomlkit

from femkit.core.errors import UsageError

PRIVATE_FILE = 0o600
PRIVATE_DIR = 0o700


def atomic_write_text(path: Path, text: str, *, private: bool = False) -> Path:
    """Write ``text`` so a reader sees the old file or the new one, never a part;
    ``private``: readable by this account alone, from its first byte."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)  # 0600 as made
    try:
        if not private:
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(tmp, 0o666 & ~umask)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def write_json(path: Path, data: Any, *, private: bool = False) -> Path:
    return atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n", private=private)


def write_toml(path: Path, data: dict) -> Path:
    return atomic_write_text(path, tomlkit.dumps(data))


def read_toml(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _own_group(gid: int) -> bool:
    """The account's private group: its primary group, named after it, with no other member."""
    import grp
    import pwd
    try:
        group, me = grp.getgrgid(gid), pwd.getpwuid(os.getuid())
    except KeyError:
        return False
    return gid == os.getgid() and group.gr_name == me.pw_name and set(group.gr_mem) <= {me.pw_name}


def _replaceable_by_others(info: os.stat_result) -> bool:
    """Another account could rename or replace what this folder holds."""
    if info.st_uid not in (os.getuid(), 0):
        return True  # its owner is another account
    if info.st_mode & stat.S_ISVTX:
        return False  # sticky (/tmp): only an entry's owner may rename or remove it
    return bool(info.st_mode & stat.S_IWOTH) or bool(info.st_mode & stat.S_IWGRP and not _own_group(info.st_gid))


def private_dir(path: Path) -> Path:
    """``path``, made if absent — each folder made here 0700 — and entered by this account
    alone. Refused, naming the folder, when it is another account's, or a folder above it
    lets another account replace what is inside: owned by another account, or writable by
    others and not sticky (a group's write counts unless the group is this account's own)."""
    path = Path(path)
    missing = [p for p in [path, *path.parents] if not p.exists()]
    for folder in reversed(missing):
        folder.mkdir(mode=PRIVATE_DIR)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
        raise UsageError(f"{path} is not a folder of this account's own")
    if info.st_mode & 0o077:
        os.chmod(path, PRIVATE_DIR)
    for above in path.resolve().parents:
        if _replaceable_by_others(above.stat()):
            raise UsageError(f"{above} lets other accounts replace what is inside it, so {path} below it "
                             "cannot be kept private")
    return path


def open_private(path: Path, mode: str) -> IO:
    """``path`` opened readable by this account alone from its first byte, never through a
    link. ``mode``: ``"a"``/``"ab"`` appends, ``"w"``/``"wb"`` truncates, ``"x"``/``"xb"``
    creates and refuses a file already there."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    flags |= os.O_APPEND if "a" in mode else os.O_EXCL if "x" in mode else os.O_TRUNC
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, flags, PRIVATE_FILE)
    if os.fstat(fd).st_mode & 0o077:
        os.fchmod(fd, PRIVATE_FILE)
    binary = "b" in mode
    return os.fdopen(fd, "ab" if binary and "a" in mode else "wb" if binary else "a" if "a" in mode else "w",
                     **({} if binary else {"encoding": "utf-8"}))
