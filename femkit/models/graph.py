"""The project as a graph (models.md § 11.2): derived from the parts as opened, the layout and the
schemas, never stored — the vocabulary's one graph document (web.md § 7.6), its nodes, wires and
boxes the vocabulary's.

One node per part, of the family `part`, in the reading order — by its kind's section, then rank,
then the kind's place in the layout, then name (the layout's `reading`) — and one per object inside
a loaded part, of the family `object`, as the layout's object types declare them, right after its
part, in its part's place; each with its kind within its family, its rank and section, the files
it opens as — each with its text and SHA-256 as the project read it (`door.file`); an object none,
the page showing its part's, which `part` names — a part's keys, every key its file may hold with
its help and fragment, by the check frame's one builder (`checking.keys`; web.md § 8.3) — its state
and its block's word, the facts its operation builds, and the issues that name it. Its ports: its
fields that name another part or a group, `in`, typed by their `ref` annotations — the ones the
checks read — and, on a component, each group its contract promises, `out`, typed by the places it
may be before the geometry exists (geometry.md § 7).

Every wire runs one way, from what is named to what names it (web.md § 7.6): each name a field
cites, to the port of that field; each definition a quantity names; each axis of a study from what
it varies — the node its address lies in — and each axis to each group of axes that step together
naming it. A group is no node: a part that names the studies it reads — an observables part — has each group it names
wired from the component of each study it reads; with a study in view, each group a part the study
pairs names is wired from the component's port of that group to the port naming it, at the value
that names it, not checked where whether it is the place the statement stands on waits on the
built geometry — the pairing's own word (`study.waits_on_geometry`); with none, the groups a
physics or a recipe names stay unwired. The
person's grouping folders are boxes around their parts. A global library's material the project
names is a node too, its address `material:GLOBAL/<name>` and its box `GLOBAL`: the library's,
said so; an assignment's wire comes from the material its name finds (materials.md § 4). A surface
draws it all from this document and changes nothing; the command line writes it as its tables, or
as Mermaid text, by the one renderer (`core/text.py`).
"""

from __future__ import annotations

from typing import Mapping

from femkit.core.errors import UsageError
from femkit.core.issues import Issue
from femkit.core.schema import QUANTITIES, names_in, references
from femkit.core.view import FOLDER, IN, OBJECT, OUT, PART, Box, Fact, File, Graph, GraphNode, GraphPort, Wire
from femkit.materials.assign import GROUP
from femkit.models import axes, study as studies
from femkit.models.parts import contract, quantities
from femkit.projects import checking, door, names
from femkit.projects import state as part_state
from femkit.projects.addresses import Address
from femkit.projects.checking import DEFINITION, Checking
from femkit.projects.door import Opened, Part
from femkit.projects.layout import held


def _objects(opened: Opened, part: Part) -> list[tuple[Address, str, str | None]]:
    """Each object inside a loaded part: its address, its object type, and its type within that."""
    out = []
    for kind, o in opened.layout.objects.items():
        if o.part != part.address.kind or part.data is None:
            continue
        for key, value in o.entries(part.data).items():
            typed = held(value, o.typed) if o.typed else None
            path = (*o.keys, key) if o.named else o.keys
            out.append((Address(part.address.kind, part.address.name, path), kind,
                        typed if isinstance(typed, str) else None))
    return out


def _files(opened: Opened, address: Address) -> list[File]:
    """The files a part opens as (web.md § 7.6), as the project read them: its own file, and each
    its kind fixes — a component's contract and its script."""
    return [door.file(opened, address), *(door.file(opened, Address(address.kind, address.name, file=f))
                                          for f in opened.layout.kinds[address.kind].files)]


def _a_group(ref: str) -> bool:
    """Whether a `ref` type names a group a component promises — `group`, or `group:<place>` with
    its alternatives (core.md § 2) — the object type a group is, which no node of its own stands
    for."""
    return all(t.partition(":")[0] == GROUP for t in ref.split("|"))


def _groups(c: Checking, part: Part) -> list[GraphPort]:
    """A component's `out` ports: each group its contract promises, typed by the places it may be
    before the geometry exists (geometry.md § 7); none for a part that promises none."""
    k = contract(c.opened, part)
    return [GraphPort(name=g, side=OUT, accepts=[f"{GROUP}:{p}" for p in k.places(g, c.places)] or [GROUP],
                      many=False) for g in (k.groups if k is not None else ())]


def _named(opened: Opened, kind: str, name: str) -> str:
    """The node a name of ``kind`` refers to: a part of that kind, as the door finds it — a
    material the project's own first, then the global library's, `<kind>:GLOBAL/<name>`
    (materials.md § 4); or an object of the project file's — a definition — the one part whose
    objects a name reaches without knowing a pairing."""
    layout = opened.layout
    o = layout.objects.get(kind)
    if o is not None and o.part == layout.project_kind and o.named:
        return str(Address(o.part, None, (*o.keys, name)))
    found = door.named(opened, kind, name)
    return str(found.address if found is not None else Address(kind, name))


def _key(part: str, written: str) -> str:
    """The key a value at ``written`` stands at within the part ``part``'s file: its address with the
    part's own taken away — what a finding names as its key (`Issue.key`)."""
    return written[len(part):].lstrip(":")


def _varied(opened: Opened, part: Part, addresses: list[str]) -> list[tuple[str, str, str]]:
    """A study's wires of what its axes vary (models.md § 11.2): from the node an axis's address
    lies in to the axis; and from each axis a group of axes that step together names to the group
    — (source, target, the value that names it). An axis keyed by no address reaches nothing: its
    finding says so."""
    if part.data is None or opened.layout.kinds[part.address.kind].schema_ != studies.KEY:
        return []
    out = []
    kind, name = part.address.kind, part.address.name
    axes_at, together_at = (opened.layout.objects[t].keys for t in (axes.AXIS, axes.TOGETHER))
    for key in part.data.axes:
        axis = str(Address(kind, name, (*axes_at, key)))
        try:
            varied = opened.layout.address(key)
        except UsageError:
            continue
        source = _owner(addresses, str(varied))
        if source is not None:
            out.append((source, axis, axis))
    for group, held_axes in part.data.together.items():
        target = str(Address(kind, name, (*together_at, group)))
        out += [(str(Address(kind, name, (*axes_at, key))), target,
                 str(Address(kind, name, (*together_at, group, "axes")))) for key in held_axes.axes]
    return out


def _owner(addresses: list[str], written: str) -> str | None:
    """The most specific node a value at ``written`` lies in — a file of a part, `<part>@<file>`, its
    part's."""
    inside = [a for a in addresses if written == a or written.startswith((a + ":", a + ".", a + "@"))]
    return max(inside, key=len) if inside else None


def _boxes(opened: Opened, parts: list[Part]) -> list[Box]:
    """A box for each of the person's grouping folders, around the parts in it and the folders in
    it (models.md § 11.2), each by its folder's path from its kind's: `studies/sweeps`."""
    boxes: dict[str, Box] = {}
    for part in parts:
        name = part.address.name
        member, group = str(part.address), names.group(name) if name else None
        while group is not None:
            where = f"{opened.layout.kinds[part.address.kind].folder}/{group}"
            box = boxes.setdefault(where, Box(address=where, label=group, kind=FOLDER))
            if member not in box.members:
                box.members.append(member)
            member, group = where, names.group(group)
    return list(boxes.values())


#: A field naming a group, by the part holding it and its key: the node and the port it lies in,
#: its `ref` type, the group's name, and the address of the value that names it.
Naming = tuple[str, str, str, str, str]


def _wired(c: Checking, study: Part, naming: dict[tuple[str, tuple[str, ...]], Naming],
           ports: dict[str, dict[tuple[str, str], GraphPort]], parts: set[str],
           waits: set[tuple[str, tuple[str, ...]]] = frozenset()) -> dict[tuple[str, str, str], Wire]:
    """Each group one of ``parts`` names, wired from the port of that group on the component
    ``study`` solves to the port naming it (web.md § 7.6; models.md § 11.2) — not checked where its
    fit waits on the built geometry, ``waits``, as the pairing tells it; nothing for a study whose
    component cannot be read."""
    holder = studies.cites(c, "component", study.data.component) if study.data is not None else None
    k = contract(c.opened, holder) if holder is not None else None
    if k is None:
        return {}
    component = str(holder.address)
    wires = {}
    for (part, keys), (node, port, ref, group, at) in naming.items():
        if part in parts - {component} and group in k.groups and (component, node, at) not in wires:
            wires[(component, node, at)] = Wire(source=component, source_port=group, target=node, target_port=port,
                                                type=ref, address=at, key=_key(part, at),
                                                checked=(part, keys) not in waits)
            ports[component][(group, OUT)].names.append(node)
    return wires


def _paired(c: Checking, study: Part | None, naming: dict[tuple[str, tuple[str, ...]], Naming],
            ports: dict[str, dict[tuple[str, str], GraphPort]]) -> list[Wire]:
    """Each group a part names wired from the component that promises it (web.md § 7.6; models.md
    § 11.2): a part naming the studies it reads — an observables part — through each study it reads,
    its pairing its own, whatever study is in view; and, with ``study`` in view, each group a part it
    pairs names — its physics, its recipe."""
    kind = c.opened.layout.kind_of(studies.KEY)
    reads: dict[str, set[str]] = {}
    for at, cited in door.references(c.opened):
        if cited.kind == kind and at.kind != kind:
            reads.setdefault(str(cited), set()).add(str(at.part))
    wires: dict[tuple[str, str, str], Wire] = {}
    for address, readers in reads.items():
        read = c.opened.parts.get(address)
        if read is not None:
            wires |= _wired(c, read, naming, ports, readers)
    if study is not None and study.data is not None:
        used = {str(p.address) for _, p in studies.used(c, study)}
        wires |= {k: w for k, w in _wired(c, study, naming, ports, used, studies.waits_on_geometry(c, study)).items()
                  if k not in wires}
    return list(wires.values())


def build(c: Checking, issues: list[Issue], states: dict[str, part_state.Seen], facts: Mapping[str, list[Fact]],
          study: Part | None = None) -> tuple[Graph, list[Issue]]:
    """The graph, each node with its issues and the facts ``facts`` holds for it, each group wired
    through ``study``'s pairing where one is in view; and the findings no node holds."""
    opened = c.opened
    layout = opened.layout
    parts = sorted(opened.parts.values(), key=lambda p: layout.reading(p.address.kind, p.address.name))
    nodes: list[GraphNode] = []
    ports: dict[str, dict[tuple[str, str], GraphPort]] = {}
    for part in parts:
        a, name = part.address, part.address.name
        files, k = _files(opened, a), layout.kind(a.kind)
        seen = states.get(str(a))
        nodes.append(GraphNode(address=str(a), family=PART, kind=a.kind, label=names.last(name) if name else a.kind,
                               rank=k.rank, section=k.section, state=seen.state if seen else None,
                               shows=seen.shows if seen else None, files=files, keys=checking.keys(c, part),
                               facts=list(facts.get(str(a), [])), actions=list(seen.next) if seen else []))
        ports[str(a)] = {(p.name, p.side): p for p in (_groups(c, part) if part.data is not None else [])}
        nodes += [GraphNode(address=str(o), family=OBJECT, kind=kind, type=typed, label=o.path[-1], part=str(a),
                            rank=k.rank, section=k.section, facts=list(facts.get(str(o), [])))
                  for o, kind, typed in _objects(opened, part)]
    addresses = [n.address for n in nodes]
    by_address = {n.address: n for n in nodes}
    wires: dict[tuple[str, str, str], Wire] = {}
    naming: dict[tuple[str, tuple[str, ...]], Naming] = {}
    project = layout.objects.get(DEFINITION)
    for part in parts:
        if part.data is None:
            continue
        for location, ref, name, how in references(part.data):
            keys = tuple(str(p) for p in location if not isinstance(p, int))
            field = keys[:-1] if how == "key" else keys
            written = str(Address(part.address.kind, part.address.name, field))
            at = str(Address(part.address.kind, part.address.name, keys))      # the value that names it
            node = _owner(addresses, written) or str(part.address)
            port_name = written[len(node):].lstrip(":.") or field[-1]
            port = ports.setdefault(node, {}).setdefault((port_name, IN), GraphPort(
                name=port_name, side=IN, accepts=ref.split("|"), many=how != "value"))
            port.names.append(name)
            if _a_group(ref):
                naming[(str(part.address), keys)] = (node, port_name, ref, name, at)
                continue
            source = next((t for k in ref.split("|") if (t := _named(opened, k, name)) in by_address), None)
            if source is not None:
                wires.setdefault((source, node, at), Wire(source=source, target=node, target_port=port_name, type=ref,
                                                          address=at, key=_key(str(part.address), at)))
        for source, target, written in _varied(opened, part, addresses):   # typed by what is named
            if source in by_address:
                wires.setdefault((source, target, written), Wire(source=source, target=target,
                                                                 type=by_address[source].kind, address=written,
                                                                 key=_key(str(part.address), written)))
        for at_keys, kind, value in quantities(part.data) if project is not None else ():
            path = tuple(str(k) for k in at_keys if not isinstance(k, int))
            if not QUANTITIES[kind].cites:
                continue                                     # a unit, or a value that names no definition
            written = str(Address(part.address.kind, part.address.name, path))
            target = _owner(addresses, written) or str(part.address)
            for name in names_in(value):                     # alone, or among a `{value, unit}`'s numbers
                source = str(Address(project.part, None, (*project.keys, name)))
                if source in by_address and source != target:
                    wires.setdefault((source, target, written), Wire(source=source, target=target, type=DEFINITION,
                                                                     address=written,
                                                                     key=_key(str(part.address), written)))
    paired = _paired(c, study, naming, ports)
    held_issues: dict[str, list[Issue]] = {}
    loose: list[Issue] = []
    for issue in issues:
        owner = _owner(addresses, issue.subject)
        (held_issues.setdefault(owner, []) if owner else loose).append(issue)
    nodes = [n.model_copy(update={"issues": held_issues.get(n.address, []),
                                  "ports": list(ports.get(n.address, {}).values())}) for n in nodes]
    return Graph(nodes=nodes, wires=[*wires.values(), *paired], boxes=_boxes(opened, parts)), loose

