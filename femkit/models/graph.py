"""The model as a graph (models.md § 11.2): derived from the files and the schemas, never stored.

Nodes are the objects of the model and a study, at their addresses; edges are the references
between them, typed by the schema's `ref` annotations — the very ones the loader checks — and
each parameter an expression uses. The palette comes from the formulation and the schema.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from femkit.core.issues import Issue
from femkit.core.schema import Model, references
from femkit.core.units import name_spans
from femkit.definitions.formulations import FormulationDefinition
from femkit.models.address import Address
from femkit.models.schema import RULES, ModelFile, Shape, StudyFile, quantities

LAYOUT = Path(".femkit") / "layout.json"


class GraphNode(Model):
    address: str = Field(description="the object's address (models.md § 11.1)")
    kind: str = Field(description="what it is: parameter, shape, region, material, condition, source, frame, "
                                  "geometry, conventions, radiation, numerics, axis, observable, binding")
    type: str | None = Field(default=None, description="its kind within that: a region's, a shape's, a condition's")
    label: str = Field(description="its name, as a person reads it")
    values: dict[str, Any] = Field(default_factory=dict, description="its own values, as the file holds them")
    findings: list[Issue] = Field(default_factory=list, description="`model check`'s findings that name it")
    position: list[float] | None = Field(default=None, description="where `model layout` placed it")


class GraphEdge(Model):
    source: str = Field(description="the node that refers")
    target: str = Field(description="the node referred to")
    port: str = Field(description="the field that holds the reference, from the source node")
    type: str = Field(description="the reference's type: shape, region:boundary, material, parameter, …")
    address: str = Field(description="where the reference is written: what `model unset` removes to cut it")


class PaletteEntry(Model):
    group: Literal["geometry", "regions", "materials", "conditions", "sources", "study"]
    kind: str = Field(description="what a drop adds")
    description: str = Field(description="the sentence a person reads beside it")
    section: str | None = Field(default=None, description="its section of the formulation's science document")
    on: list[str] = Field(default_factory=list, description="for a condition or source: the region kinds it may "
                                                            "stand on")
    parameters: dict[str, str] = Field(default_factory=dict, description="each parameter: its unit, and what it is")
    address: str = Field(description="the address a drop writes, its names to fill as <…>")


def _value(v: Any) -> Any:
    return json.loads(json.dumps(v, default=str))


def _nodes(m: ModelFile, study: str | None, s: StudyFile | None) -> list[GraphNode]:
    model = lambda *p: str(Address(None, p))  # noqa: E731
    out = [GraphNode(address=model("parameters", n), kind="parameter", label=n, values={"value": t})
           for n, t in m.parameters.items()]
    for key in ("frame", "conventions", "radiation"):
        part = getattr(m, key)
        if part is not None:
            out.append(GraphNode(address=model(key), kind=key, label=key,
                                 values=_value(part.model_dump(mode="json", by_alias=True, exclude_none=True))))
    if m.geometry is not None:
        out.append(GraphNode(address=model("geometry"), kind="geometry", label="geometry",
                             values={"dimension": m.geometry.dimension, "meaning": m.geometry.meaning}))
        out += [GraphNode(address=model("geometry", "shapes", n), kind="shape", type=sh.kind, label=n,
                          values=_value(sh.model_dump(mode="json", exclude_none=True)))
                for n, sh in m.geometry.shapes.items()]
    out += [GraphNode(address=model("regions", n), kind="region", type=r.kind, label=n,
                      values=_value(r.model_dump(mode="json", exclude_none=True))) for n, r in m.regions.items()]
    out += [GraphNode(address=model("materials", n), kind="material", label=n,
                      values=_value({p: v.model_dump(mode="json", exclude_none=True) for p, v in props.items()}))
            for n, props in m.materials.items()]
    out += [GraphNode(address=model("conditions", n), kind="condition", type=c.kind, label=f"{c.kind} on {n}",
                      values=_value(c.model_dump(mode="json"))) for n, c in m.conditions.items()]
    out += [GraphNode(address=model("sources", n), kind="source", type=src.kind, label=n,
                      values=_value(src.model_dump(mode="json"))) for n, src in m.sources.items()]
    if s is not None:
        here = lambda *p: str(Address(study, p))  # noqa: E731
        if s.numerics is not None:
            out.append(GraphNode(address=here("numerics"), kind="numerics", label="numerics",
                                 values=_value(s.numerics.model_dump(mode="json", exclude_none=True))))
        out += [GraphNode(address=here("axes", k), kind="axis", type=a.class_, label=k,
                          values=_value(a.model_dump(mode="json", by_alias=True)))
                for k, a in s.axes.items() if not isinstance(a, str)]
        out += [GraphNode(address=here("observables", n), kind="observable", type=o.quantity, label=n,
                          values=_value(o.model_dump(mode="json", exclude_none=True)))
                for n, o in s.observables.items()]
        out += [GraphNode(address=here("environments", n), kind="binding", label=n,
                          values=_value(b.model_dump(mode="json", exclude_none=True)))
                for n, b in s.environments.items()]
    return out


def _owner(addresses: list[str], study: str | None, at: tuple) -> str | None:
    """The node that holds the location ``at``: the longest node address it lies under."""
    full = str(Address(study, tuple(str(p) for p in at)))
    best = None
    for a in addresses:
        if (full == a or full.startswith(a + ".")) and (best is None or len(a) > len(best)):
            best = a
    return best


TARGET = {"shape": ("geometry", "shapes"), "region": ("regions",), "material": ("materials",),
          "parameter": ("parameters",)}


def _edges(m: ModelFile, study: str | None, s: StudyFile | None, nodes: list[GraphNode]) -> list[GraphEdge]:
    addresses = [n.address for n in nodes]
    out: list[GraphEdge] = []
    for where, instance in [(None, m), *([(study, s)] if s is not None else [])]:
        for at, target, name, held in references(instance):
            family = target.split("|")[0].split(":")[0]
            to = str(Address(None, (*TARGET[family], name))) if family in TARGET else None
            written = str(Address(where, tuple(str(p) for p in at)))
            if at[0] == "assign":           # an assignment is no object: the region's material
                if held == "value":
                    out.append(GraphEdge(source=str(Address(None, ("regions", at[1]))), target=to, port="material",
                                         type=target, address=written))
                continue
            source = _owner(addresses, where, at)
            if source is not None and to is not None and to in addresses:
                port = written[len(source) + 1:] if written != source else "on"  # a condition is named by its region
                out.append(GraphEdge(source=source, target=to, port=port, type=target, address=written))
        for at, _, value in quantities(instance):
            if not isinstance(value, str):
                continue
            for _, _, name in name_spans(value):
                to = str(Address(None, ("parameters", name)))
                source = _owner(addresses, where, at)
                if name in m.parameters and source is not None and source != to:
                    written = str(Address(where, tuple(str(p) for p in at)))
                    out.append(GraphEdge(source=source, target=to, port=written[len(source) + 1:] or "value",
                                         type="parameter", address=written))
        if where is not None:
            for key in s.axes:
                if key.startswith("parameters.") and key.split(".", 1)[1] in m.parameters:
                    out.append(GraphEdge(source=str(Address(study, ("axes", key))), port="varies", type="parameter",
                                         target=str(Address(None, ("parameters", key.split(".", 1)[1]))),
                                         address=str(Address(study, ("axes", key)))))
    return out


def palette(f: FormulationDefinition | None, study: str | None) -> list[PaletteEntry]:
    shapes = typing.get_args(typing.get_args(Shape)[0])
    out = [PaletteEntry(group="geometry", kind=kind, description=" ".join((cls.__doc__ or "").split()),
                        address="model:geometry.shapes.<name>")
           for cls in shapes for kind in typing.get_args(cls.model_fields["kind"].annotation)]
    rules = {kind: [r for r, k in RULES.items() if k == kind] for kind in ("domain", "boundary", "interface")}
    out += [PaletteEntry(group="regions", kind=kind, description=f"a {kind}, selected by one rule: {', '.join(rs)}",
                         address="model:regions.<name>") for kind, rs in rules.items()]
    if f is not None:
        out += [PaletteEntry(group="materials", kind=n, description=p.description, section=p.section,
                             address=f"model:materials.<material>.{n}") for n, p in f.properties.items()]
        out += [PaletteEntry(group="conditions", kind=n, description=k.description, section=k.section, on=list(k.on),
                             parameters={p: f"{s.unit} — {s.description}" for p, s in k.parameters.items()},
                             address="model:conditions.<region>") for n, k in f.conditions.items()]
        out += [PaletteEntry(group="sources", kind=n, description=k.description, section=k.section, on=list(k.on),
                             parameters={p: f"{s.unit} — {s.description}" for p, s in k.parameters.items()},
                             address="model:sources.<name>") for n, k in f.sources.items()]
        out += [PaletteEntry(group="study", kind=n, description=d.description, section=d.section,
                             address=f"study:{study or '<study>'}:observables.<name>") for n, d in f.derived.items()]
    return out


def positions(project: Path) -> dict[str, list[float]]:
    try:
        return json.loads((project / LAYOUT).read_text(encoding="utf-8"))["positions"]
    except (OSError, ValueError, KeyError):
        return {}


def build(m: ModelFile, study: str | None, s: StudyFile | None, issues: list[Issue], project: Path
          ) -> tuple[list[GraphNode], list[GraphEdge], list[Issue]]:
    """The nodes with their findings and positions, the edges, and the findings no node holds."""
    nodes = _nodes(m, study, s)
    addresses = [n.address for n in nodes]
    placed = positions(project)
    held: dict[str, list[Issue]] = {}
    loose = []
    for issue in issues:
        owner = _owner(addresses, None, tuple(issue.subject.removeprefix("model:").split(".")))
        (held.setdefault(owner, []) if owner else loose).append(issue)
    nodes = [n.model_copy(update={"findings": held.get(n.address, []), "position": placed.get(n.address)})
             for n in nodes]
    return nodes, _edges(m, study, s, nodes), loose


def mermaid(nodes: list[GraphNode], edges: list[GraphEdge]) -> str:
    """The graph as Mermaid text, for a terminal or a document."""
    ids = {n.address: f"n{i}" for i, n in enumerate(nodes)}
    lines = ["flowchart LR"]
    for n in nodes:
        mark = f" ({len(n.findings)} findings)" if n.findings else ""
        what = f"{n.kind}: {n.type}" if n.type else n.kind
        lines.append(f'    {ids[n.address]}["{n.label}<br/>{what}{mark}"]')
    lines += [f'    {ids[e.source]} -->|"{e.port}"| {ids[e.target]}' for e in edges
              if e.source in ids and e.target in ids]
    return "\n".join(lines)
