"""What may be added to a model or a study, and how a relation is drawn and cut (web.md § 8.3,
models.md § 11.2): each an `Action` derived from the table of object types, the schema and the
formulation. An add names its new object — a hole to fill — and writes its text, which starts
as the object's template; the palette, a finding's fix and the graph's wires are these same
actions."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from femkit.core import view
from femkit.core.persist import inline_text
from femkit.core.schema import Model, whole
from femkit.core.units import Units
from femkit.definitions.formulations import FormulationDefinition
from femkit.models import fields, templates
from femkit.models.address import Address
from femkit.models.requests import MODEL_SET, MODEL_UNSET, MODEL_WRITE
from femkit.models.schema import NAME, OBJECTS, ObjectType


class Entry(Model):
    """One thing that may be added: of which object type and type, what it is, and the action
    that adds it."""

    kind: str = Field(description="the object type it adds", json_schema_extra={"doc": "models.md § 11.2"})
    type: str | None = Field(default=None, description="its type within that: `boundary`, `potential`; none "
                                                       "for an object type with no types")
    help: view.Help | None = Field(default=None, description="what it is")
    add: view.Action | None = Field(default=None, description="the action that adds it: its name to fill, its "
                                                              "text starting as its template; none until what it "
                                                              "needs is chosen")
    needs: Literal["study"] | None = Field(default=None, description="the context that must be chosen first")


def entry(project: Path, study: str | None, f: FormulationDefinition | None, units: Units, o: ObjectType,
          type_: str | None, name: str | None = None) -> Entry:
    """The entry adding an ``o`` of ``type_``: named ``name``, or by a hole the person fills — a
    new name, or for a table keyed by another object's name (a condition, by its region's), a
    name of that object; for one value per type (a material's property), the entry it joins."""
    schema = fields.entry(o, type_, f, units)
    help = fields.help_of(schema)
    if o.file == "study" and study is None:
        return Entry(kind=o.kind, type=type_, help=help, needs="study")
    keyed = o.keyed_by()
    spec = (getattr(f, o.declared, None) or {}).get(type_) if o.declared else None
    per_type = o.declared is not None and o.typed is None
    if keyed:
        what, accepts = keyed[0].split(":")[0], [k for k in keyed if k.split(":")[-1] in getattr(spec, "on", [])]
        accepts = accepts or keyed
    elif per_type:
        what, accepts = o.kind, [o.kind]
    else:
        what, accepts = "name", []
    hole = f"<{what}>"
    key = name if name is not None else hole
    address = Address(None if o.file == "model" else study, (*o.table, key, *((type_,) if per_type else ())))
    fills = [] if name is not None else [view.Fill(
        field="address", hole=str(Address(None, (hole,))).split(":", 1)[1],      # the step as the address writes it
        label=f"the {what}" if accepts else "its name", accepts=accepts,
        json_schema={"type": "string", "pattern": whole(NAME)})]
    held = {o.typed: type_} if o.typed and type_ else {}
    fills.append(view.Fill(field="text", label=f"the {(type_ or o.kind).replace('_', ' ')}",
                           template=templates.text(schema["properties"][type_] if per_type else schema, held)))
    return Entry(kind=o.kind, type=type_, help=help,
                 add=view.command(MODEL_WRITE, label=f"add {(type_ or o.kind).replace('_', ' ')}",
                                  project=str(project), address=str(address), fills=fills))


def palette(project: Path, study: str | None, f: FormulationDefinition | None, units: Units) -> list[Entry]:
    """Every entry, in the chain's order: each object type the palette offers, each of its types
    — the schema's, or the formulation's where it declares them."""
    return [entry(project, study, f, units, o, t)
            for o in sorted((o for o in OBJECTS if o.palette), key=lambda o: o.rank)
            for t in (o.types(f) or [None])
            if not (o.declared and f is None)]


def connect(project: Path, address: str, accepts: list[str], many: bool, names: list[str], label: str) -> view.Action:
    """What a wire drawn into a port does: the name it takes added to the list, or set."""
    hole = "<name>"
    value = inline_text([*names, hole] if many else hole)
    return view.command(MODEL_SET, label=f"connect {label}", project=str(project), address=address,
                        value=value, fills=[view.Fill(field="value", hole=hole, label=label, accepts=accepts)])


def cut(project: Path, at: str, held: str, name: str, names: list[str] | None = None) -> view.Action | None:
    """What removes a reference, by how it is held (models.md § 11.2): a key's or a value's entry
    unset; a list's item, the list set without it; a name used in a text, nothing — only the text
    can be changed. ``at`` is where it is written; for an item, the list's address."""
    if held == "text":
        return None
    if held == "item" and (rest := [n for n in names or [] if n != name]):
        return view.command(MODEL_SET, label=f"take {name} out of {at}", project=str(project),
                            address=at, value=inline_text(rest))
    return view.command(MODEL_UNSET, label=f"remove {at}", project=str(project), address=at)
