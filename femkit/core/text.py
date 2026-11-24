"""The text a person reads (api.md § 4.4).

One way to show a value, a table, a finding and a "next" block, so every
command reads alike. A result's ``text()`` builds its lines with these; the
command line adds the `[group verb]` tag.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

from femkit.core.commandline import word
from femkit.core.issues import Issue
from femkit.core.view import Action

PAD = "    "
MARK = {"error": "x", "warning": "!", "info": "-"}


def show(value: Any) -> str:
    """A value as a person would type it: no quotes, no brackets."""
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "none" if not value else " ".join(word(v) for v in value)
    return str(value)


def path(value: str | Path) -> str:
    """A path as a person reads it: under the home directory, written from `~`."""
    shown, home = str(value), str(Path.home())
    return "~" + shown[len(home):] if shown == home or shown.startswith(home + "/") else shown


def count(n: int, noun: str) -> str:
    """``n`` and ``noun``, plural unless it is one: `1 step`, `16 steps`."""
    return f"{n} {noun}{'' if n == 1 else 's'}"


def table(rows: Iterable[Sequence[str]], indent: str = "  ") -> list[str]:
    """Rows of cells, each column as wide as its widest cell; the last column is free."""
    rows = [list(map(str, r)) for r in rows]
    if not rows:
        return []
    widths = [max(len(r[i]) for r in rows if i < len(r)) for i in range(max(len(r) for r in rows) - 1)]
    out = []
    for r in rows:
        cells = [c.ljust(widths[i]) if i < len(widths) else c for i, c in enumerate(r)]
        out.append((indent + "  ".join(cells)).rstrip())
    return out


def commands(steps: Iterable[Action]) -> list[str]:
    """Next steps as commands a person can paste: one a line, indented, a note after `#`."""
    return [PAD + str(step) for step in steps]


def next_block(sentence: str, steps: Sequence[Action]) -> list[str]:
    """`next -- <sentence>:` and the commands under it; nothing when there are none."""
    if not steps:
        return []
    return [f"next -- {sentence}:"] + commands(steps)


def findings(issues: Iterable[Issue]) -> list[str]:
    """Each finding on its line, indented and marked by severity, its next steps under it."""
    out = []
    for issue in issues:
        out.append(f"  {MARK[issue.severity]} {issue.message}")
        out += [f"  {line}" for line in commands(issue.next)]
    return out
