"""The text a person reads (api.md § 4.4).

One way to show a value, a table, a graph, a finding, a step and a "next" block, so every
command reads alike. A result's ``text()`` writes its report with these; the command line adds the
`[group verb]` tag.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

from femkit.core.commandline import word
from femkit.core.issues import Issue
from femkit.core.view import (OUT, Action, Box, Code, Graph, GraphNode, GraphPort, Next, Report, Table, Text, Wire,
                              column)

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


def duration(seconds: float) -> str:
    """A length of time as a person reads it, to the second: `42 s`, `3 min 05 s`, `2 h 07 min`."""
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s:02d} s"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"


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
    """`next -- <sentence>:` and the commands under it, each written as every step is, its label and
    its remarks after `#` (`Action.__str__`); nothing when there are none (api.md § 4.4)."""
    return [f"next -- {sentence}:", *commands(steps)] if steps else []


def findings(issues: Iterable[Issue]) -> list[str]:
    """Each finding on its line, indented and marked by severity; under it, where the person
    opens it — its file, a global library's from `~` where it lies under the home folder, its line
    where it has one, and its key — and what would be right, then its next steps (api.md § 4.4)."""
    out = []
    for issue in issues:
        out.append(f"  {MARK[issue.severity]} {issue.message}")
        if issue.file is not None:
            out.append(f"  {PAD}{path(issue.file)}" + (f", line {issue.line}" if issue.line else "")
                       + (f": {issue.key}" if issue.key else ""))
        if issue.right is not None:
            out.append(f"  {PAD}right: {issue.right}")
        if issue.choices:
            out.append(f"  {PAD}one of: {', '.join(issue.choices)}")
        out += [f"  {line}" for line in commands(issue.next)]
    return out


def rows(shown: Table) -> list[str]:
    """A table as the command line writes it (web.md § 7.5): its rows under its columns' labels, an
    action in a cell as every step is written (`Action.__str__`)."""
    cells = [[str(row.get(c.key, "")) for c in shown.columns] for row in shown.rows]
    return table([[c.label for c in shown.columns]] + cells) if shown.rows else []


def typed(node: GraphNode) -> str:
    """A node's kind as a person reads it, with its type where it has one — `condition: potential`:
    the one writer of it, for its table and its Mermaid box alike."""
    return f"{node.kind}: {node.type}" if node.type else node.kind


#: Where a wire that is not checked yet says so, in words (models.md § 11.2: "shown as not checked
#: yet, never hidden").
NOT_CHECKED = "not checked yet"

#: A graph's nodes, wires and the files its outputs hold, as the command line writes them (web.md
#: § 7.7: "a graph as its tables"), each column a field of the node's, the box's, the wire's or the
#: port's model — by that model and its key — and its cell as a person reads it, given the node and
#: the box it sits in — shown only where some row holds a value for it.
NODE = {(GraphNode, "address"): lambda n, b: n.address, (GraphNode, "kind"): lambda n, b: typed(n),
        (GraphNode, "engine"): lambda n, b: n.engine or "", (GraphNode, "state"): lambda n, b: n.state or "",
        (GraphNode, "shows"): lambda n, b: n.shows or "", (Box, "label"): lambda n, b: b.label if b else "",
        (GraphNode, "folder"): lambda n, b: path(n.folder) if n.folder else "",
        (GraphNode, "issues"): lambda n, b: len(n.issues) or ""}
WIRE = {(Wire, "source"): lambda w: w.source, (Wire, "source_port"): lambda w: w.source_port or "",
        (Wire, "target"): lambda w: w.target, (Wire, "target_port"): lambda w: w.target_port or "",
        (Wire, "address"): lambda w: w.address or "", (Wire, "checked"): lambda w: "" if w.checked else NOT_CHECKED}
OUTPUT = {"name": lambda n, p: f"{p.name} ({', '.join(p.accepts)})", "file": lambda n, p: path(p.file),
          "actions": lambda n, p: p.actions[0] if p.actions else ""}


def _held(cells: dict, written: list[dict]) -> list:
    return [k for k in cells if any(row[k] != "" for row in written)]


def _sits(graph: Graph) -> dict[str, Box]:
    """The box each node sits in, by the node's address: the box whose members name it — boxes of
    one kind never overlap, and a box inside another is a member of it, never its nodes (web.md
    § 7.6)."""
    return {m: b for b in graph.boxes for m in b.members}


def _table(cells: dict, written: list[dict]) -> Table:
    """The rows ``written``, each cell by its model and key, under the columns some row holds a
    value for (`column`)."""
    held = _held(cells, written)
    return Table.over([column(model, key) for model, key in held],
                      [{key: row[(model, key)] for model, key in held} for row in written])


def tags(graph: Graph) -> dict[str, str]:
    """What each node's ports name that is no node of ``graph``, by the node's address: a port none
    of whose types — each by its kind, before any place — is a kind of node, a type a port gives or a
    wire carries — a recipe's mesher — said beside its node as the page's card says it on its kind
    line (web.md § 2.2): `mesher: gmsh`."""
    given = {n.kind for n in graph.nodes} | {w.type.split(":")[0] for w in graph.wires} | \
            {t.split(":")[0] for n in graph.nodes for p in n.ports if p.side == OUT for t in p.accepts}
    return {n.address: "; ".join(f"{p.name}: {', '.join(p.names)}" for p in n.ports
                                 if p.accepts and all(t.split(":")[0] not in given for t in p.accepts))
            for n in graph.nodes}


def drawn(graph: Graph) -> list[Table]:
    """A graph as the tables the command line writes it as: its nodes, each with the box it sits in
    and what its ports name that is no node (`tags`); its wires, each not checked yet said so; then
    each output that holds a file, with the line that opens it."""
    named = tags(graph)
    cells = {k: v for key, cell in NODE.items()
             for k, v in [(key, cell), *([((GraphPort, "names"), lambda n, b: named[n.address])]
                                         if key == (GraphNode, "engine") else [])]}
    sits = _sits(graph)
    out = [_table(cells, [{k: cell(n, sits.get(n.address)) for k, cell in cells.items()} for n in graph.nodes]),
           _table(WIRE, [{k: cell(w) for k, cell in WIRE.items()} for w in graph.wires])]
    files = [(n, p) for n in graph.nodes for p in n.ports if p.side == OUT and p.file is not None]
    if files:
        written = [{"address": n.address, **{k: cell(n, p) for k, cell in OUTPUT.items()}} for n, p in files]
        held = _held(OUTPUT, written)
        out.append(Table.over([column(GraphNode, "address"), *(column(GraphPort, k) for k in held)],
                              [{k: row[k] for k in ("address", *held)} for row in written]))
    return out


def mermaid(graph: Graph) -> str:
    """A graph as Mermaid text, for a terminal or a document (models.md § 11.1): each node a box
    holding the objects inside it, labelled by its kind as its table writes it (`typed`), with the
    count of its findings; each wire an arrow from what gives or is named to what takes or names
    it, labelled by the port it reaches — dashed where it is not checked yet."""
    nodes = graph.nodes
    ids = {n.address: f"n{i}" for i, n in enumerate(nodes)}
    lines = ["flowchart LR"]

    def box(n: GraphNode) -> str:
        mark = f" ({count(len(n.issues), 'finding')})" if n.issues else ""
        return f'{ids[n.address]}["{n.label}<br/>{typed(n)}{mark}"]'

    for n in nodes:
        if n.part is not None:
            continue
        inner = [o for o in nodes if o.part == n.address]
        if inner:
            lines.append(f'    subgraph {ids[n.address]}box["{n.address}"]')
            lines += [f"        {box(n)}"] + [f"        {box(o)}" for o in inner] + ["    end"]
        else:
            lines.append(f"    {box(n)}")
    for w in graph.wires:
        port = w.target_port or w.source_port
        arrow = "-->" if w.checked else "-.->"
        lines.append(f'    {ids[w.source]} {arrow}{f"|{port}|" if port else ""} {ids[w.target]}')
    return "\n".join(lines)


def report(shown: Report, issues: Iterable[Issue] = ()) -> str:
    """A result's report as the command line writes it (web.md § 7.7): each line; each table's
    rows under its columns' labels; a graph as its tables; then the findings; then each next block,
    the next steps following the findings (models.md § 11.2)."""
    out: list[str] = []
    for block in shown.blocks:
        if isinstance(block, (Text, Code)):
            out.append(block.text)
        elif isinstance(block, Table):
            out += rows(block)
        elif isinstance(block, Graph):
            written = [rows(t) for t in drawn(block)]
            out += [line for i, lines in enumerate(w for w in written if w) for line in ([""] if i else []) + lines]
    after = [line for block in shown.blocks if isinstance(block, Next) for line in next_block(block.label, block.actions)]
    return "\n".join(out + findings(issues) + after)
