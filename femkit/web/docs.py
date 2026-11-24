"""What the document viewer may show (web.md § 2): the repository's own Markdown files, and
the images they show — a list made by walking those folders without following a link. A path
is served only when it is on that list, so no spelling of a path reaches anything else."""

from __future__ import annotations

import os
from pathlib import Path

from femkit.core import dirs

MARKDOWN = (".md",)
IMAGES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".gif": "image/gif"}
LIMIT = 2 * 1024 * 1024  # bytes: a document or an image larger is not served
# The repository's own documents at its root (PROJECT_CONTRACT.md § 2): named, never globbed,
# so a local file beside them is never shown.
ROOT_DOCUMENTS = ("README.md", "PROJECT_CONTRACT.md", "CONTRIBUTING.md", "SECURITY.md")


def _walk(root: Path, top: Path) -> list[str]:
    out = []
    for folder, subfolders, files in os.walk(root, followlinks=False):
        subfolders[:] = sorted(d for d in subfolders if not d.startswith(".") and not os.path.islink(Path(folder, d)))
        for name in sorted(files):
            path = Path(folder, name)
            if not os.path.islink(path) and path.suffix.lower() in (*MARKDOWN, *IMAGES):
                out.append(path.relative_to(top).as_posix())
    return out


def listing() -> list[str]:
    """Every document and image the viewer may show, as paths from the repository's root:
    the root's own documents, and everything under docs/ and examples/."""
    top = dirs.checkout()
    found = [name for name in ROOT_DOCUMENTS if (top / name).is_file() and not (top / name).is_symlink()]
    for folder in ("docs", "examples"):
        if (top / folder).is_dir() and not (top / folder).is_symlink():
            found += _walk(top / folder, top)
    return found


def read(path: str) -> tuple[str, bytes] | None:
    """The kind (`markdown` or an image's type) and bytes of a listed file; None otherwise."""
    if path not in listing():
        return None
    file = dirs.checkout() / path
    if file.stat().st_size > LIMIT:
        return None
    suffix = file.suffix.lower()
    return ("markdown" if suffix in MARKDOWN else IMAGES[suffix]), file.read_bytes()
