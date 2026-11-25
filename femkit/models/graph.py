"""The project as a graph (models.md § 11.2): derived from the parts as opened, the layout and the
schemas, never stored.

One node per part, in the chain's order — the layout's ranks — inside the person's grouping
folders, and one per object inside a loaded part, as the layout's object types declare them; each
with its text as its file holds it, its state, and the findings that name it. Its ports are its
fields that name another part or a group, typed by their `ref` annotations — the ones the checks
read — and the wires are the references between parts: each name a field cites, and each
parameter a quantity uses. A global library's material the project names is a node too, its
address `material:GLOBAL/<name>` and its group `GLOBAL`: the library's, said so; an assignment's
wire goes to the material its name finds (materials.md § 4). A surface draws it all from this
document and changes nothing.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from femkit.core.errors import UsageError
from femkit.core.issues import Issue
from femkit.core.schema import QUANTITIES, Model, references
from femkit.core.text import count
from femkit.core.units import name_spans
from femkit.models.parts import quantities
from femkit.projects import door, names
from femkit.projects.addresses import Address
from femkit.projects.checking import PARAMETER
from femkit.projects.door import Opened, Part
from femkit.projects.layout import held


class GraphPort(Model):
    """A field of a node that names another part or a group (models.md § 11.2)."""

    name: str = Field(description="the field, by its dotted path from the node")
    address: str = Field(description="where its names are written")
    accepts: list[str] = Field(description="the types it names, as its `ref` annotation states them: `physics`, "
                                           "`group:outer_boundary`")
    many: bool = Field(description="whether it names several: a list, or a table's keys")
    names: list[str] = Field(default_factory=list, description="the names it holds")


class GraphNode(Model):
    """A part, or an object inside one, as the graph shows it."""

    address: str = Field(description="its address", json_schema_extra={"doc": "projects.md § 5"})
    kind: str = Field(description="its part kind or object type, as the layout names it",
                      json_schema_extra={"doc": "projects.md § 4"})
    type: str | None = Field(default=None, description="its type within that, where its object type has one: a "
                                                       "condition's kind")
    label: str = Field(description="what a person calls it")
    name: str | None = Field(default=None, description="the name another refers to it by")
    part: str | None = Field(default=None, description="for an object, the address of the part holding it")
    group: str | None = Field(default=None, description="for a part, the grouping folder it lies in")
    rank: int = Field(description="its place in the chain's order: what it is made from comes first",
                      json_schema_extra={"doc": "models.md § 11.2"})
    state: str | None = Field(default=None, description="for a part, its state", json_schema_extra={"doc": "projects.md § 8"})
    text: str | None = Field(default=None, description="its text as its file holds it, comments kept; none for a "
                                                       "part that cannot be read")
    ports: list[GraphPort] = Field(default_factory=list, description="its fields that name another part or a group")
    findings: list[Issue] = Field(default_factory=list, description="the findings that name it, in the chain's order")


class GraphEdge(Model):
    """A reference from one node to another."""

    source: str = Field(description="the node that refers")
    target: str = Field(description="the node referred to")
    port: str | None = Field(default=None, description="the source's port it leaves by; none for a parameter a "
                                                       "quantity uses")
    type: str = Field(description="what it refers to, as the `ref` annotation states it, or `parameter`")
    address: str = Field(description="where the reference is written")
    held: Literal["key", "value", "item", "text"] = Field(
        description="how: a table's key, a value, a list's item, or a name used inside a value's text")


def _objects(opened: Opened, part: Part) -> list[tuple[Address, str, str | None, int]]:
    """Each object inside a loaded part: its address, its object type, its type within that, and
    its rank."""
    out = []
    for kind, o in opened.layout.objects.items():
        if o.part != part.address.kind or part.data is None:
            continue
        for key, value in o.entries(part.data).items():
            typed = held(value, o.typed) if o.typed else None
            path = (*o.keys, key) if o.named else o.keys
            out.append((Address(part.address.kind, part.address.name, path), kind,
                        typed if isinstance(typed, str) else None, o.rank))
    return out


def _text(opened: Opened, address: Address) -> str | None:
    try:
        return door.text(opened, address)
    except UsageError:
        return None


def _named(opened: Opened, kind: str, name: str) -> str:
    """The node a name of ``kind`` refers to: a part of that kind, as the door finds it — a
    material the project's own first, then the global library's, `<kind>:GLOBAL/<name>`
    (materials.md § 4); or an object of the project file's — a parameter — the one part whose
    objects a name reaches without knowing a pairing."""
    layout = opened.layout
    o = layout.objects.get(kind)
    if o is not None and o.part == layout.project_kind and o.named:
        return str(Address(o.part, None, (*o.keys, name)))
    found = door.named(opened, kind, name)
    return str(found.address if found is not None else Address(kind, name))


def _owner(addresses: list[str], written: str) -> str | None:
    """The most specific node a value at ``written`` lies in."""
    inside = [a for a in addresses if written == a or written.startswith(a + ":") or written.startswith(a + ".")]
    return max(inside, key=len) if inside else None


def build(opened: Opened, issues: list[Issue], states: dict[str, str]) -> tuple[list[GraphNode], list[GraphEdge],
                                                                                list[Issue]]:
    """The nodes, each with its findings; the wires; and the findings no node holds."""
    layout = opened.layout
    parts = sorted(opened.parts.values(), key=lambda p: (layout.kinds[p.address.kind].rank, p.file))
    nodes: list[GraphNode] = []
    for part in parts:
        a, name = part.address, part.address.name
        nodes.append(GraphNode(address=str(a), kind=a.kind, label=names.last(name) if name else a.kind, name=name,
                               group=names.group(name) if name else None, rank=layout.kinds[a.kind].rank,
                               state=states.get(str(a)), text=_text(opened, a)))
        nodes += [GraphNode(address=str(o), kind=kind, type=typed, label=o.path[-1], name=o.path[-1], part=str(a),
                            rank=rank, text=_text(opened, o)) for o, kind, typed, rank in _objects(opened, part)]
    addresses = [n.address for n in nodes]
    by_address = {n.address: n for n in nodes}
    edges: dict[tuple[str, str, str], GraphEdge] = {}
    ports: dict[str, dict[str, GraphPort]] = {}
    project = layout.objects.get(PARAMETER)
    for part in parts:
        if part.data is None:
            continue
        for location, ref, name, how in references(part.data):
            keys = tuple(str(p) for p in location if not isinstance(p, int))
            field = keys[:-1] if how == "key" else keys
            written = str(Address(part.address.kind, part.address.name, field))
            source = _owner(addresses, written) or str(part.address)
            port_name = written[len(source):].lstrip(":.") or field[-1]
            port = ports.setdefault(source, {}).setdefault(port_name, GraphPort(
                name=port_name, address=written, accepts=ref.split("|"), many=how != "value"))
            port.names.append(name)
            target = next((t for k in ref.split("|") if (t := _named(opened, k, name)) in by_address), None)
            if target is not None:
                edges.setdefault((source, target, written), GraphEdge(source=source, target=target, port=port_name,
                                                                      type=ref, address=written, held=how))
        for at, kind, value in quantities(part.data) if project is not None else ():
            if QUANTITIES[kind].reads != "expression":
                continue                                     # a unit, or a value naming no parameter
            written = str(Address(part.address.kind, part.address.name, tuple(str(k) for k in at
                                                                              if not isinstance(k, int))))
            source = _owner(addresses, written) or str(part.address)
            for _, _, used in name_spans(value if isinstance(value, str) else ""):
                target = str(Address(project.part, None, (*project.keys, used)))
                if target in by_address and target != source:
                    edges.setdefault((source, target, written), GraphEdge(source=source, target=target, type=PARAMETER,
                                                                          address=written, held="text"))
    held_findings: dict[str, list[Issue]] = {}
    loose: list[Issue] = []
    for issue in issues:
        owner = _owner(addresses, issue.subject)
        (held_findings.setdefault(owner, []) if owner else loose).append(issue)
    nodes = [n.model_copy(update={"findings": held_findings.get(n.address, []),
                                  "ports": list(ports.get(n.address, {}).values())}) for n in nodes]
    return nodes, list(edges.values()), loose


def mermaid(nodes: list[GraphNode], edges: list[GraphEdge]) -> str:
    """The graph as Mermaid text, for a terminal or a document: each part a box holding its objects."""
    ids = {n.address: f"n{i}" for i, n in enumerate(nodes)}
    lines = ["flowchart LR"]

    def box(n: GraphNode) -> str:
        mark = f" ({count(len(n.findings), 'finding')})" if n.findings else ""
        what = f"{n.kind}: {n.type}" if n.type else n.kind
        return f'{ids[n.address]}["{n.label}<br/>{what}{mark}"]'

    for n in nodes:
        if n.part is not None:
            continue
        inner = [o for o in nodes if o.part == n.address]
        if inner:
            lines.append(f'    subgraph {ids[n.address]}box["{n.address}"]')
            lines += [f"        {box(n)}"] + [f"        {box(o)}" for o in inner] + ["    end"]
        else:
            lines.append(f"    {box(n)}")
    lines += [f'    {ids[e.source]} -->{f"|{e.port}|" if e.port else ""} {ids[e.target]}' for e in edges]
    return "\n".join(lines)
