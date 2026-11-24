"""A Markdown document's headings and their link anchors, by GitHub's rule (web.md § 2).

One function, read by the formulation's section check (models.md § 4) and the document
viewer, so a section named in data and its address in the viewer always agree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ATX = re.compile(r" {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r" {0,3}(```+|~~~+)")


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    anchor: str


def anchor(title: str) -> str:
    """GitHub's anchor: lower case; every character but a letter, digit, `_`, `-` or space
    dropped; each space a hyphen. `5. The web application — femkit/web/` gives
    `5-the-web-application--femkitweb`."""
    return re.sub(r" ", "-", re.sub(r"[^\w\- ]", "", title.strip().lower()))


def headings(text: str) -> list[Heading]:
    """Every ATX heading outside a fenced code block, in order, each anchor unique as GitHub
    makes it: a repeat gains `-1`, `-2`, …"""
    out: list[Heading] = []
    seen: dict[str, int] = {}
    fence: str | None = None
    for line in text.splitlines():
        opened = FENCE.match(line)
        if fence is not None:
            if opened and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
            continue
        if opened:
            fence = opened.group(1)
            continue
        match = ATX.match(line)
        if match:
            title = re.sub(r"`([^`]*)`", r"\1", match.group(2))   # code spans count by their text
            base = anchor(title)
            n = seen.get(base, 0)
            seen[base] = n + 1
            out.append(Heading(len(match.group(1)), match.group(2), base if n == 0 else f"{base}-{n}"))
    return out
