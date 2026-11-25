"""A Markdown document's headings and their link anchors, by GitHub's rule (web.md § 2); and a
Markdown text as one line of plain text.

`headings` is read by the formulation's section check (models.md § 4) and the document viewer,
so a section named in data and its address in the viewer always agree. `plain` is read by an
importer, which writes another library's citation as a dataset's `source` (materials.md § 7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

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


# ------------------------------------------------------------------ a text as plain text

#: A link, `[text](destination)`: its text may hold one level of brackets, and its destination
#: parentheses that balance, as a DOI's often does (`10.1016/S0022-3093(97)00438-9`).
LINK = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(((?:[^()\s]|\([^()\s]*\))*)\)")
#: Emphasis around a run of text: `*a*`, `**a**`, `***a***`; with `_`, only at a word's edges.
EMPHASIS = re.compile(r"(\*{1,3})(?=\S)(.+?)(?<=\S)\1|(?<!\w)(_{1,3})(?=\S)(.+?)(?<=\S)\3(?!\w)")
BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)        # an HTML line break
TAG = re.compile(r"</?[A-Za-z][^<>]*>")                # any other HTML tag
BULLET = re.compile(r"\A[*+-][ \t]+")                  # a bullet list's marker, at a line's start


def _unmarked(text: str) -> str:
    """``text`` without its emphasis marks, emphasis inside emphasis too."""
    while (bare := EMPHASIS.sub(lambda m: m.group(2) if m.group(1) else m.group(4), text)) != text:
        text = bare
    return text


def plain(text: str, link: Callable[[str, str], str] = lambda shown, destination: shown) -> str:
    """A Markdown text as one line of plain text: each link as ``link`` writes it from its text,
    itself plain, and its destination — its text alone, by default; emphasis marks, HTML tags and
    a bullet list's markers removed, an HTML line break a line's end; its lines joined, and every
    run of white space one space."""
    lines = [BULLET.sub("", line.strip(), count=1) for line in BREAK.sub("\n", text).splitlines()]
    joined = TAG.sub("", " ".join(line for line in lines if line))
    out, at = [], 0
    for found in LINK.finditer(joined):
        out += [_unmarked(joined[at:found.start()]), link(_unmarked(found.group(1)), found.group(2))]
        at = found.end()
    return " ".join("".join([*out, _unmarked(joined[at:])]).split())
