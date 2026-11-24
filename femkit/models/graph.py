"""The model as a graph (models.md § 11.2): derived from the files and the schemas, never stored.

Nodes are the objects of the model and a study, at their addresses, each with its text as its
file holds it, the help of every key it may hold, and its ports: the fields that name another
object, typed by the schema's `ref` annotations — the very ones the loader checks. Edges are
the references between them, and each parameter an expression uses. The palette comes from
the table of object types, the schema and the formulation. A surface draws all of it from this
document and names no field of its own (web.md § 2, § 8.3).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from femkit.core import view
from femkit.core.issues import Issue
from femkit.core.persist import document_text, read_document
from femkit.core.schema import Model, classes, field_extras, items_of, references
from femkit.core.units import Units, name_spans
from femkit.definitions.formulations import FormulationDefinition
from femkit.models import fields
from femkit.models.address import Address, parse
from femkit.models.project import NEW_FILE, model_file, study_file
from femkit.models.schema import OBJECTS, ModelFile, ObjectType, StudyFile, locate, object_type, quantities



class GraphPort(Model):
    name: str = Field(description="the field that names another object, from the node")
    address: str = Field(description="where its names are written")
    accepts: list[str] = Field(description="the node kinds it takes, as `kind` or `kind:type`: `material`, "
                                           "`region:boundary`; a port accepts only these (models.md § 11.2)")
    many: bool = Field(description="a list: a wire adds a name to it; else a wire sets it")
    names: list[str] = Field(default_factory=list, description="the names it holds now")
    help: view.Help | None = Field(default=None, description="its sentence, from the schema")


class GraphNode(Model):
    address: str = Field(description="the object's address", json_schema_extra={"doc": "models.md § 11.1"})
    kind: str = Field(description="its object type, from the table of object types",
                      json_schema_extra={"doc": "models.md § 11.2"})
    type: str | None = Field(default=None, description="its type within that: a region's, a condition's")
    label: str = Field(description="its name, as a person reads it")
    name: str | None = Field(default=None, description="the name another object refers to it by")
    rank: int = Field(description="its place in the chain's order: what it is made from comes first",
                      json_schema_extra={"doc": "models.md § 11.2"})
    help: view.Help | None = Field(default=None, description="what it is")
    text: str = Field(description="its text as its file holds it, comments kept: its table as a TOML document of "
                                  "its own, or a value's inline text", json_schema_extra={"doc": "web.md § 8.3"})
    keys: list[view.Field] = Field(default_factory=list, description="every key it may hold, the help beside its "
                                                                     "text; required first")
    ports: list[GraphPort] = Field(default_factory=list, description="its fields that name another object")
    findings: list[Issue] = Field(default_factory=list, description="`model check`'s findings that name it")


class GraphEdge(Model):
    source: str = Field(description="the node that refers")
    target: str = Field(description="the node referred to")
    port: str | None = Field(default=None, description="the source node's port it leaves by; none: from the node "
                                                        "itself — a key naming it, a name in a text")
    type: str = Field(description="the reference's type: shape, region:boundary, material, parameter, …")
    address: str = Field(description="where the reference is written")
    held: Literal["key", "value", "item", "text"] = Field(
        description="how: a table's key, a value, a list's item, or a name used inside a value's text")


def _objects(m: ModelFile, study: str | None, s: StudyFile | None
             ) -> Iterator[tuple[Address, ObjectType, str | None, str, BaseModel | None]]:
    """Each object of the model and the study, as the one table of object types says
    (models.md § 11.2): its address, its type, its type within that, its label, and its
    instance — None for a value or a table the schema does not model as one."""
    for o in OBJECTS:
        root = m if o.file == "model" else s
        if root is None:
            continue
        for key, value in o.entries(root).items():
            if o.typed and not isinstance(value, BaseModel):
                continue                                   # a note beside the entries: `axes.reason`
            address = Address(None if o.file == "model" else study, (*o.table, key) if o.many else o.table)
            type_ = o.type_of(value)
            yield address, o, type_, o.label_of(key, value), value if isinstance(value, BaseModel) else None


def _referring(cls: type[BaseModel], at: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str, bool, Any]]:
    """Each field of ``cls``, and of the one model inside a field, that names another object:
    its path, its target type, whether it holds a list, and the type of its object it is `for`."""
    for name, field in cls.model_fields.items():
        key = field.alias or name
        extras = field_extras(field)
        if isinstance(extras.get("ref"), str):
            yield (*at, key), extras["ref"], items_of(field.annotation) is not None, extras.get("for")
        elif len(inner := classes(field.annotation)) == 1:
            yield from _referring(inner[0], (*at, key))


def _keyed(cls: type[BaseModel]) -> dict[str, dict]:
    """The tables of ``cls`` whose keys name one object and whose values another: `assign`."""
    return {field.alias or name: ref for name, field in cls.model_fields.items()
            if isinstance(ref := field_extras(field).get("ref"), dict) and "key" in ref and "value" in ref}


def _takes(accepts: list[str], kind: str, type_: str | None) -> bool:
    return kind in accepts or f"{kind}:{type_}" in accepts


def _ports(project: Path, address: Address, o: ObjectType, type_: str | None, instance: BaseModel | None,
           root: BaseModel, schema: dict[str, Any]) -> list[GraphPort]:
    """The node's ports: each of its fields that names another object — one that belongs to
    another type of its object left out — and, for a table naming this node by key (`assign`),
    the value it names."""
    out = []

    def port(name: str, at: str, accepts: list[str], many: bool, names: list[str], help: view.Help | None) -> None:
        out.append(GraphPort(name=name, address=at, accepts=accepts, many=many, names=names, help=help))

    if instance is not None:
        for path, target, many, for_type in _referring(type(instance)):
            if for_type not in (None, type_):
                continue
            held: Any = instance
            for step in path:
                held = getattr(held, step, None) if isinstance(held, BaseModel) else None
            port(".".join(path), str(address.child(*path)), target.split("|"), many,
                 [h for h in (held if isinstance(held, list) else [held]) if isinstance(h, str)],
                 fields.help_of(fields.leaf(schema, path)))
    for key, ref in _keyed(type(root)).items():
        if _takes(ref["key"].split("|"), o.kind, type_):
            held = getattr(root, key).get(address.path[-1])
            port(ref["value"], str(Address(address.study, (key, address.path[-1]))), ref["value"].split("|"), False,
                 [held] if isinstance(held, str) else [], view.Help.of(type(root).model_fields[key].description))
    return out


def ports(project: Path, m: ModelFile, address: Address, f: FormulationDefinition | None, units: Units
          ) -> list[GraphPort]:
    """The ports of the model's object at ``address``, as its node carries them: what a finding
    about a missing relation offers to draw."""
    o, key = locate("model", address.path)
    value = o.entries(m).get(key if o.many else o.table[-1])
    type_ = o.type_of(value)
    return _ports(project, address, o, type_, value if isinstance(value, BaseModel) else None, m,
                  fields.entry(o, type_, f, units))


def _nodes(m: ModelFile, study: str | None, s: StudyFile | None, docs: dict[str | None, Any],
           f: FormulationDefinition | None, units: Units, project: Path) -> list[GraphNode]:
    out = []
    for address, o, type_, label, instance in _objects(m, study, s):
        root = m if address.study is None else s
        schema = fields.entry(o, type_, f, units)
        here = str(address)
        out.append(GraphNode(
            address=here, kind=o.kind, type=type_, label=label, name=address.path[-1] if o.named else None,
            rank=o.rank, help=fields.help_of(schema), text=document_text(docs[address.study], address.path),
            keys=fields.keys(schema), ports=_ports(project, address, o, type_, instance, root, schema)))
    return out


def owner(study: str | None, at: tuple) -> str | None:
    """The address of the object a location lies in, by the table of object types; none for a
    location in no object — a table itself, or the file's own keys."""
    found = locate("model" if study is None else "study", at)
    if found is None:
        return None
    o, key = found
    if o.many and key is None:
        return None
    return str(Address(study, (*o.table, key) if o.many else o.table))


def _edges(m: ModelFile, study: str | None, s: StudyFile | None, nodes: list[GraphNode]) -> list[GraphEdge]:
    by_address = {n.address: n for n in nodes}
    out: dict[tuple[str, str, str], GraphEdge] = {}           # an expression naming a parameter twice is one wire

    def add(source: str | None, target: str, port: str | None, type_: str, written: str, held: str) -> None:
        if source in by_address and target in by_address and source != target:
            out.setdefault((source, target, written), GraphEdge(source=source, target=target, port=port, type=type_,
                                                               address=written, held=held))

    def port_of(source: str, written: str) -> str | None:
        return next((p.name for p in by_address[source].ports if written == p.address
                     or written.startswith(p.address + ".")), None) if source in by_address else None

    for where, instance in [(None, m), *([(study, s)] if s is not None else [])]:
        keyed = _keyed(type(instance))
        for at, target, name, held in references(instance):
            to = str(Address(None, (*object_type(target.split("|")[0].split(":")[0]).table, name)))
            written = str(Address(where, tuple(str(p) for p in at)))
            if at[0] in keyed:                                 # a table naming its key's object: that object's port
                if held == "value":
                    family = keyed[at[0]]["key"].split("|")[0].split(":")[0]
                    source = str(Address(where, (*object_type(family).table, str(at[1]))))
                    add(source, to, keyed[at[0]]["value"], target, written, held)
                continue
            source = owner(where, at)
            add(source, to, port_of(source, written) if source else None, target, written, held)
        for at, _, value in quantities(instance):
            if isinstance(value, str):
                for _, _, name in name_spans(value):
                    if name in m.parameters:
                        add(owner(where, at), str(Address(None, ("parameters", name))), None, "parameter",
                            str(Address(where, tuple(str(p) for p in at))), "text")
        if where is not None:
            for key in s.axes:
                if key.startswith("parameters.") and key.split(".", 1)[1] in m.parameters:
                    add(str(Address(study, ("axes", key))), str(Address(None, ("parameters", key.split(".", 1)[1]))),
                        None, "parameter", str(Address(study, ("axes", key))), "key")
    return list(out.values())


def build(m: ModelFile, study: str | None, s: StudyFile | None, issues: list[Issue], project: Path,
          f: FormulationDefinition | None, units: Units) -> tuple[list[GraphNode], list[GraphEdge], list[Issue]]:
    """The nodes with their findings, the edges, and the findings no node holds."""
    docs = {None: read_document(model_file(project), empty=NEW_FILE)}
    if study is not None:
        docs[study] = read_document(study_file(project, study), empty=NEW_FILE)
    nodes = _nodes(m, study, s, docs, f, units, project)
    held: dict[str, list[Issue]] = {}
    loose = []
    shown = {n.address for n in nodes}
    for issue in issues:
        subject = parse(issue.subject)
        holder = owner(subject.study, subject.path)
        (held.setdefault(holder, []) if holder in shown else loose).append(issue)
    nodes = [n.model_copy(update={"findings": held.get(n.address, [])})
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
    lines += [f'    {ids[e.source]} -->{f"|{chr(34)}{e.port}{chr(34)}|" if e.port else ""} {ids[e.target]}'
              for e in edges if e.source in ids and e.target in ids]
    return "\n".join(lines)
