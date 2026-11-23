"""Atomic writes and reads (core.md § 4). Every file femkit writes goes through here."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomlkit


def atomic_write_text(path: Path, text: str) -> Path:
    """Write ``text`` so a reader sees the old file or the new one, never a part."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
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


def write_json(path: Path, data: Any) -> Path:
    return atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_toml(path: Path, data: dict) -> Path:
    return atomic_write_text(path, tomlkit.dumps(data))


def read_toml(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
