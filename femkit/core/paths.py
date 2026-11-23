"""Paths as femkit compares them (core.md § 3).

One answer to "does this lie inside that", used wherever a prefix or a build tree must hold
what femkit found: a compiler, a module, a test's directory; and one to "where would this
land", for a place that does not exist yet.
"""

from __future__ import annotations

from pathlib import Path


def inside(path: str | Path | None, root: str | Path) -> bool:
    """Whether ``path`` resolves to ``root`` or below it; nothing, or an empty path, is not inside."""
    if not path:
        return False
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def nearest_existing(path: Path) -> Path | None:
    """``path``, or its nearest parent that exists: what a place not made yet would be made in."""
    return next((p for p in (path, *path.parents) if p.exists()), None)
