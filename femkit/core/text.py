"""The text a person reads (api.md § 4.4).

One way to show a value, a table, a finding and a "next" block, so every
command reads alike. A result's ``text()`` builds its lines with these; the
command line adds the `[group verb]` tag.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Iterable, Sequence

from femkit.core.issues import Issue
from femkit.core.schema import PLACEHOLDER

PAD = "    "

#: How a person runs femkit: in the activated control environment, from the
#: repository folder (envs.md § 7). Every printed command starts with it.
PROG = "python -m femkit"
MARK = {"error": "x", "warning": "!", "info": "-"}


def word(value: Any) -> str:
    """One word of a command line, quoted for the shell only when it needs it; a
    placeholder (`{ranks}`) is part of the template, written as it is typed."""
    shown = str(value)
    bare = PLACEHOLDER.sub(lambda m: "x" if m.group(1).isidentifier() and m.group(2) is None else m.group(0), shown)
    return shown if shlex.quote(bare) == bare else shlex.quote(shown)


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


def typed(*args: str) -> str:
    """A femkit command as a person types it, quoted for the shell: `python -m femkit ARGS`."""
    return f"{PROG} {shlex.join(args)}"


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


def commands(lines: Iterable[str]) -> list[str]:
    """Commands a person can paste: one a line, indented, prose after `#`."""
    return [PAD + line for line in lines]


def next_block(sentence: str, lines: Sequence[str]) -> list[str]:
    """`next -- <sentence>:` and the commands under it; nothing when there are none."""
    if not lines:
        return []
    return [f"next -- {sentence}:"] + commands(lines)


def findings(issues: Iterable[Issue]) -> list[str]:
    """Each finding on its line, indented and marked by severity, its commands under it."""
    out = []
    for issue in issues:
        out.append(f"  {MARK[issue.severity]} {issue.message}")
        out += [f"  {line}" for line in commands(issue.next)]
    return out
