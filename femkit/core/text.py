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
from femkit.core.view import Action, Code, Next, Report, Table, Text

PAD = "    "
MARK = {"error": "x", "warning": "!", "info": "-"}


def show(value: Any) -> str:
    """A value as a person would type it: no quotes, no brackets; a path as `path` writes it."""
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        return path(value)
    if isinstance(value, (list, tuple)):
        return "none" if not value else " ".join(word(v) for v in value)
    return str(value)


def path(value: str | Path) -> str:
    """A path as a person reads it: under the home directory, written from `~`."""
    shown, home = str(value), str(Path.home())
    return "~" + shown[len(home):] if shown == home or shown.startswith(home + "/") else shown


def count(n: int, noun: str) -> str:
    """``n`` and ``noun``, plural unless it is one, as English writes it: `1 step`, `16 steps`;
    `-y` after a consonant becomes `-ies`, `2 studies`; after `s`, `x`, `z`, `ch` or `sh`, `-es`
    is added, `2 meshes`. The one plural of a count a person reads."""
    if n == 1:
        return f"{n} {noun}"
    if noun.endswith("y") and len(noun) > 1 and noun[-2] not in "aeiou":
        return f"{n} {noun[:-1]}ies"
    return f"{n} {noun}{'es' if noun.endswith(('s', 'x', 'z', 'ch', 'sh')) else 's'}"


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
    """Each finding on its line, indented and marked by severity; under it, where the person
    opens it — its file, a global library's from `~` where it lies under the home folder, and its
    key — and what would be right, then its next steps (api.md § 4.4)."""
    out = []
    for issue in issues:
        out.append(f"  {MARK[issue.severity]} {issue.message}")
        if issue.file is not None:
            out.append(f"  {PAD}{path(issue.file)}" + (f": {issue.key}" if issue.key else ""))
        if issue.right is not None:
            out.append(f"  {PAD}right: {issue.right}")
        if issue.choices:
            out.append(f"  {PAD}one of: {', '.join(issue.choices)}")
        out += [f"  {line}" for line in commands(issue.next)]
    return out


def report(shown: Report, issues: Iterable[Issue] = ()) -> str:
    """A result's report as the command line writes it (web.md § 7.6): each line; each table's
    rows under its headings, an action in a cell as its command; each next block; then the
    findings."""
    out: list[str] = []
    for block in shown.blocks:
        if isinstance(block, (Text, Code)):
            out.append(block.text)
        elif isinstance(block, Table):
            cells = [[str(row.get(c.key, "")) if not isinstance(row.get(c.key), Action) else str(row[c.key])
                      for c in block.columns] for row in block.rows]
            heads = [c.label for c in block.columns]
            out += table(([heads] if any(heads) else []) + cells)
        elif isinstance(block, Next):
            out += next_block(block.label, block.actions)
    return "\n".join(out + findings(issues))
