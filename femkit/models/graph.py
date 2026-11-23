"""The model as a graph (models.md § 11.2): derived from the files and the schemas, never stored.

Nodes are the objects of the model and a study, at their addresses, each with its fields as
the file writes them and its ports: the fields that name another object, typed by the schema's
`ref` annotations — the very ones the loader checks. Edges are the references between them, and
each parameter an expression uses. The palette comes from the formulation and the schema. A
surface draws all of it from this document and names no field of its own (api.md § 5.2).
"""

from __future__ import annotations

import json
import types
import typing
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Literal

import tomlkit
from pydantic import BaseModel, Field

from femkit.core.issues import Issue
from femkit.core.persist import read_document
from femkit.core.schema import Model, field_extras, references
from femkit.core.units import name_spans
from femkit.definitions.formulations import FormulationDefinition
from femkit.models.address import Address
from femkit.models.edit import NEW_FILE, named
from femkit.models.project import model_file, study_file
from femkit.models.schema import RULES, ModelFile, Shape, StudyFile, quantities

LAYOUT = Path(".femkit") / "layout.json"


class GraphField(Model):
    name: str = Field(description="the field, from the node: `size`, `plane.point`; a node that is one value, its name")
    address: str = Field(description="where `model set` writes it")
    text: str = Field(description="its value as the file writes it, in TOML")


class GraphPort(Model):
    name: str = Field(description="the field that names another object, from the node")
    address: str = Field(description="where a wire drawn from it is written, by `model set`")
    accepts: list[str] = Field(description="the node kinds it takes, as `kind` or `kind:type`: `material`, "
                                           "`region:boundary`; a port accepts only these (models.md § 11.2)")
    many: bool = Field(description="a list: a wire adds a name to it; else a wire sets it")
    names: list[str] = Field(default_factory=list, description="the names it holds now")


class GraphNode(Model):
    address: str = Field(description="the object's address (models.md § 11.1)")
    kind: str = Field(description="what it is: parameter, shape, region, material, condition, source, frame, "
                                  "geometry, conventions, radiation, numerics, axis, observable, binding")
    type: str | None = Field(default=None, description="its kind within that: a region's, a shape's, a condition's")
    label: str = Field(description="its name, as a person reads it")
    name: str | None = Field(default=None, description="the name another object refers to it by")
    rank: int = Field(description="its place in the chain's order: parameters and geometry, shapes, regions, "
                                  "materials and conditions, the study (models.md § 11.2)")
    renamable: bool = Field(default=False, description="whether `model rename` takes it")
    fields: list[GraphField] = Field(default_factory=list, description="its own values, as the file writes them")
    ports: list[GraphPort] = Field(default_factory=list, description="its fields that name another object")
    findings: list[Issue] = Field(default_factory=list, description="`model check`'s findings that name it")
    position: list[float] | None = Field(default=None, description="where `model layout` placed it")


class GraphEdge(Model):
    source: str = Field(description="the node that refers")
    target: str = Field(description="the node referred to")
    port: str = Field(description="the field that holds the reference, from the source node")
    type: str = Field(description="the reference's type: shape, region:boundary, material, parameter, …")
    address: str = Field(description="where the reference is written")
    held: Literal["key", "value", "item", "text"] = Field(
        description="how: a table's key or a value — `model unset` of the address cuts it; a list's item — the "
                    "list set without it; a name used inside a value's text, cut only by editing that value")


class PaletteEntry(Model):
    group: Literal["geometry", "regions", "materials", "conditions", "sources", "study"]
    kind: str = Field(description="what a drop adds")
    description: str = Field(description="the sentence a person reads beside it")
    section: str | None = Field(default=None, description="its section of the formulation's science document")
    on: list[str] = Field(default_factory=list, description="for a condition or source: the region kinds it may "
                                                            "stand on")
    parameters: dict[str, str] = Field(default_factory=dict, description="each parameter: its unit, and what it is")
    address: str = Field(description="the address an add writes, its names to fill as <…>")
    names: dict[str, list[str]] = Field(default_factory=dict,
                                        description="each <…> of the address: the node kinds whose names may fill it, "
                                                    "as a port's `accepts`; none: a new name")
    needs: str | None = Field(default=None, description="what must be chosen before it can be added")
    template: str = Field(description="the TOML value an add starts from, its placeholders to fill")


class GraphChoice(Model):
    """A field of the model or the study that takes one of a known list: the formulation."""
    address: str = Field(description="where `model set` writes it; `model unset` clears it")
    label: str = Field(description="what a person reads beside it")
    description: str = Field(description="what it is, from the schema")
    value: str | None = Field(default=None, description="what it holds now")
    options: list[str] = Field(description="what it may hold")


def choices(m: ModelFile | None, formulations: list[str]) -> list[GraphChoice]:
    field = ModelFile.model_fields["formulation"]
    return [GraphChoice(address=str(Address(None, ("formulation",))), label="formulation",
                        description=field.description or "", value=m.formulation if m else None, options=formulations)]


# The chain's order, in which a surface lays the nodes out (models.md § 11.2).
RANK = {"parameter": 0, "frame": 0, "geometry": 0, "conventions": 0, "shape": 1, "region": 2, "material": 3,
        "condition": 3, "source": 3, "radiation": 3, "numerics": 4, "axis": 4, "observable": 4, "binding": 4}


def _objects(m: ModelFile, study: str | None, s: StudyFile | None
             ) -> Iterator[tuple[Address, str, str | None, str, BaseModel | None]]:
    """Each object: its address, kind, type, label and instance (None: a value, or a table of
    tables the schema does not model as one)."""
    for n in m.parameters:
        yield Address(None, ("parameters", n)), "parameter", None, n, None
    for key in ("frame", "conventions", "radiation"):
        if getattr(m, key) is not None:
            yield Address(None, (key,)), key, None, key, getattr(m, key)
    if m.geometry is not None:
        yield Address(None, ("geometry",)), "geometry", None, "geometry", None
        for n, sh in m.geometry.shapes.items():
            yield Address(None, ("geometry", "shapes", n)), "shape", sh.kind, n, sh
    for n, r in m.regions.items():
        yield Address(None, ("regions", n)), "region", r.kind, n, r
    for n in m.materials:
        yield Address(None, ("materials", n)), "material", None, n, None
    for n, c in m.conditions.items():
        yield Address(None, ("conditions", n)), "condition", c.kind, f"{c.kind} on {n}", c
    for n, src in m.sources.items():
        yield Address(None, ("sources", n)), "source", src.kind, n, src
    if s is not None:
        if s.numerics is not None:
            yield Address(study, ("numerics",)), "numerics", None, "numerics", s.numerics
        for k, a in s.axes.items():
            if not isinstance(a, str):
                yield Address(study, ("axes", k)), "axis", a.class_, k, a
        for n, o in s.observables.items():
            yield Address(study, ("observables", n)), "observable", o.quantity, n, o
        for n, b in s.environments.items():
            yield Address(study, ("environments", n)), "binding", None, n, b


def _at(doc: Any, path: tuple[str, ...]) -> Any:
    for step in path:
        if not isinstance(doc, Mapping) or step not in doc:
            return None
        doc = doc[step]
    return doc


def _fields(doc: Any, address: Address, nodes: set[str]) -> list[GraphField]:
    """The node's values as its file writes them, leaf by leaf; a part that is a node of its
    own — a geometry's shapes — is that node's."""
    out: list[GraphField] = []

    def walk(item: Any, rel: tuple[str, ...]) -> None:
        here = address.child(*rel)
        if rel and str(here) in nodes:
            return
        if isinstance(item, Mapping):
            for k, v in item.items():
                walk(v, (*rel, str(k)))
        else:
            text = item.as_string() if hasattr(item, "as_string") else tomlkit.item(item).as_string()
            out.append(GraphField(name=".".join(rel) or address.path[-1], address=str(here), text=text.strip()))

    item = _at(doc, address.path)
    if item is not None:
        walk(item, ())
    return out


def _unwrap(annotation: Any) -> list[Any]:
    """An annotation's alternatives, through `Optional` and `Annotated`."""
    if typing.get_origin(annotation) is typing.Annotated:
        return _unwrap(typing.get_args(annotation)[0])
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return [a for arg in typing.get_args(annotation) for a in _unwrap(arg)]
    return [annotation]


def _referring(cls: type[BaseModel], at: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str, bool]]:
    """Each field of ``cls``, and of the one model inside a field, that names another object:
    its path, its target type and whether it holds a list."""
    for name, field in cls.model_fields.items():
        key = field.alias or name
        ref = field_extras(field).get("ref")
        options = [a for a in _unwrap(field.annotation) if a is not type(None)]
        if isinstance(ref, str):
            yield (*at, key), ref, any(typing.get_origin(a) is list for a in options)
        elif len(options) == 1 and isinstance(options[0], type) and issubclass(options[0], BaseModel):
            yield from _referring(options[0], (*at, key))


def _ports(address: Address, kind: str, type_: str | None, instance: BaseModel | None,
           root: BaseModel, roots: list[tuple[str, dict]]) -> list[GraphPort]:
    out = []
    if instance is not None:
        for path, target, many in _referring(type(instance)):
            if kind == "region" and RULES.get(path[0], type_) != type_:
                continue                                   # a rule of another region kind
            held: Any = instance
            for step in path:
                held = getattr(held, step, None) if isinstance(held, BaseModel) else None
            names = [h for h in (held if isinstance(held, list) else [held]) if isinstance(h, str)]
            out.append(GraphPort(name=".".join(path), address=str(address.child(*path)), accepts=target.split("|"),
                                 many=many, names=names))
    for key, ref in roots:                                 # a table naming this node by key: `assign.<region>`
        if _takes(ref["key"].split("|"), kind, type_):
            held = getattr(root, key).get(address.path[-1])
            out.append(GraphPort(name=ref["value"], address=str(Address(address.study, (key, address.path[-1]))),
                                 accepts=ref["value"].split("|"), many=False,
                                 names=[held] if isinstance(held, str) else []))
    return out


def _takes(accepts: list[str], kind: str, type_: str | None) -> bool:
    return kind in accepts or f"{kind}:{type_}" in accepts


def _keyed(cls: type[BaseModel]) -> list[tuple[str, dict]]:
    """The tables of ``cls`` whose keys name one object and whose values another."""
    out = []
    for name, field in cls.model_fields.items():
        ref = field_extras(field).get("ref")
        if isinstance(ref, dict) and "key" in ref and "value" in ref:
            out.append((field.alias or name, ref))
    return out


def _nodes(m: ModelFile, study: str | None, s: StudyFile | None, docs: dict[str | None, Any]) -> list[GraphNode]:
    objects = list(_objects(m, study, s))
    addresses = {str(a) for a, *_ in objects}
    out = []
    for address, kind, type_, label, instance in objects:
        root = m if address.study is None else s
        out.append(GraphNode(address=str(address), kind=kind, type=type_, label=label,
                             name=address.path[-1] if named(address) else None, rank=RANK.get(kind, max(RANK.values()) + 1),
                             renamable=named(address) is not None,
                             fields=_fields(docs.get(address.study), address, addresses),
                             ports=_ports(address, kind, type_, instance, root, _keyed(type(root)))))
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
    seen: set[tuple[str, str, str]] = set()

    def add(edge: GraphEdge) -> None:                     # an expression naming a parameter twice is one wire
        if (edge.source, edge.target, edge.address) not in seen:
            seen.add((edge.source, edge.target, edge.address))
            out.append(edge)

    for where, instance in [(None, m), *([(study, s)] if s is not None else [])]:
        for at, target, name, held in references(instance):
            family = target.split("|")[0].split(":")[0]
            to = str(Address(None, (*TARGET[family], name))) if family in TARGET else None
            written = str(Address(where, tuple(str(p) for p in at)))
            if at[0] == "assign":           # an assignment is no object: the region's material
                if held == "value":
                    add(GraphEdge(source=str(Address(None, ("regions", at[1]))), target=to, port="material",
                                  type=target, address=written, held="value"))
                continue
            source = _owner(addresses, where, at)
            if source is not None and to is not None and to in addresses:
                port = written[len(source) + 1:] if written != source else "on"  # a condition is named by its region
                add(GraphEdge(source=source, target=to, port=port, type=target, address=written, held=held))
        for at, _, value in quantities(instance):
            if not isinstance(value, str):
                continue
            for _, _, name in name_spans(value):
                to = str(Address(None, ("parameters", name)))
                source = _owner(addresses, where, at)
                if name in m.parameters and source is not None and source != to:
                    written = str(Address(where, tuple(str(p) for p in at)))
                    add(GraphEdge(source=source, target=to, port=written[len(source) + 1:] or "value",
                                  type="parameter", address=written, held="text"))
        if where is not None:
            for key in s.axes:
                if key.startswith("parameters.") and key.split(".", 1)[1] in m.parameters:
                    add(GraphEdge(source=str(Address(study, ("axes", key))), port="varies", type="parameter",
                                  target=str(Address(None, ("parameters", key.split(".", 1)[1]))),
                                  address=str(Address(study, ("axes", key))), held="key"))
    return out


def _placeholder(name: str, annotation: Any, dimension: int) -> str:
    """A field's starting value in a template: what a person replaces."""
    text = str(annotation)
    if "list[list" in text:
        return "[" + ", ".join(["[" + ", ".join(["0"] * dimension) + "]"] * 3) + "]"
    if "list[str]" in text:
        return '["<shape>", "<shape>"]'
    if "list" in text:
        return "[" + ", ".join(["0"] * dimension) + "]"
    if name == "sha256":
        return '"<sha256>"'
    if name == "file":
        return '"custom/<file>"'
    return "1"


def _shape_template(cls: type, kind: str) -> str:
    dimension = 3 if kind in ("box", "sphere", "cylinder", "extrusion") else 2
    parts = [f'kind = "{kind}"'] + [f"{n} = {_placeholder(n, f.annotation, dimension)}"
                                     for n, f in cls.model_fields.items() if n != "kind"]
    return "{ " + ", ".join(parts) + " }"


REGION_TEMPLATES = {
    "domain": '{ kind = "domain", shapes = ["<shape>"] }',
    "boundary": '{ kind = "boundary", plane = { point = [0, 0], normal = [1, 0] } }',
    "interface": '{ kind = "interface", between = ["<domain>", "<domain>"] }',
}


def palette(f: FormulationDefinition | None, study: str | None) -> list[PaletteEntry]:
    shapes = typing.get_args(typing.get_args(Shape)[0])
    out = [PaletteEntry(group="geometry", kind=kind, description=" ".join((cls.__doc__ or "").split()),
                        address="model:geometry.shapes.<name>", names={"<name>": []},
                        template=_shape_template(cls, kind))
           for cls in shapes for kind in typing.get_args(cls.model_fields["kind"].annotation)]
    rules = {kind: [r for r, k in RULES.items() if k == kind] for kind in ("domain", "boundary", "interface")}
    out += [PaletteEntry(group="regions", kind=kind, description=f"a {kind}, selected by one rule: {', '.join(rs)}",
                         address="model:regions.<name>", names={"<name>": []}, template=REGION_TEMPLATES[kind])
            for kind, rs in rules.items()]
    if f is not None:
        out += [PaletteEntry(group="materials", kind=n, description=p.description, section=p.section,
                             address=f"model:materials.<material>.{n}", names={"<material>": ["material"]},
                             template='{ value = "<value>", convention = "real", source = "<where it comes from>", '
                                      'range = "all" }') for n, p in f.properties.items()]
        for group, kinds in (("conditions", f.conditions), ("sources", f.sources)):
            out += [PaletteEntry(group=group, kind=n, description=k.description, section=k.section, on=list(k.on),
                                 parameters={p: f"{s.unit} — {s.description}" for p, s in k.parameters.items()},
                                 address="model:conditions.<region>" if group == "conditions" else "model:sources.<name>",
                                 names={"<region>": [f"region:{r}" for r in k.on]} if group == "conditions"
                                 else {"<name>": []},
                                 template="{ " + ", ".join([f'kind = "{n}"'] + (['on = "<region>"'] if group == "sources"
                                                                                  else [])
                                                           + [f'{p} = "<{s.unit}>"' for p, s in k.parameters.items()])
                                          + " }") for n, k in kinds.items()]
        out += [PaletteEntry(group="study", kind=n, description=d.description, section=d.section,
                             address=f"study:{study or '<study>'}:observables.<name>", names={"<name>": []},
                             needs=None if study else "a study, chosen in the top bar",
                             template=f'{{ quantity = "{n}", support = {{ point = [0, 0] }}, reduction = "value", '
                                      f'unit = "{d.unit}" }}') for n, d in f.derived.items()]
    return out


def positions(project: Path) -> dict[str, list[float]]:
    try:
        return json.loads((project / LAYOUT).read_text(encoding="utf-8"))["positions"]
    except (OSError, ValueError, KeyError):
        return {}


def build(m: ModelFile, study: str | None, s: StudyFile | None, issues: list[Issue], project: Path
          ) -> tuple[list[GraphNode], list[GraphEdge], list[Issue]]:
    """The nodes with their findings and positions, the edges, and the findings no node holds."""
    docs = {None: read_document(model_file(project), empty=NEW_FILE)}
    if study is not None:
        docs[study] = read_document(study_file(project, study), empty=NEW_FILE)
    nodes = _nodes(m, study, s, docs)
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
