"""The JSON schema fragments of what a model holds (web.md § 7.3, § 8.3): built from the schema,
and for what a formulation declares — a condition's or a source's parameters, a material's
properties, an observable's quantity — from the formulation; each fragment self-contained, a
quantity's carrying the unit table's symbols for its dimension. One home: a node's keys and
help and the check's choices are all drawn from these."""

from __future__ import annotations

import copy
import functools
from typing import Any, Callable

from pydantic import BaseModel

from femkit.core import view
from femkit.core.units import Units
from femkit.definitions.formulations import FormulationDefinition
from femkit.models.schema import DIMENSIONS, ObjectType


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    """``node`` with each `$ref` replaced by its definition and no `title`: a fragment reads alone."""
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]), defs)
        return {k: _inline(v, defs) for k, v in node.items() if k not in ("title", "$defs")}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def _with_units(node: Any, units: Units) -> Any:
    """Each quantity of a fixed dimension given the symbols it may be written in."""
    if isinstance(node, dict):
        out = {k: _with_units(v, units) for k, v in node.items()}
        if isinstance(node.get("quantity"), str) and node["quantity"] in DIMENSIONS:  # the annotation, not a field
            out["units"] = units.of(DIMENSIONS[node["quantity"]])
            out["unit"] = units.canonical(DIMENSIONS[node["quantity"]])
        return out
    if isinstance(node, list):
        return [_with_units(v, units) for v in node]
    return node


@functools.lru_cache(maxsize=None)
def _inlined(cls: type[BaseModel]) -> dict[str, Any]:
    """The schema of ``cls``, self-contained: read once for a class, which never changes. Keyed
    on the class alone — a unit table is made per invocation, so a cache keyed on it never hits."""
    raw = cls.model_json_schema(mode="validation")
    return _inline(raw, raw.get("$defs", {}))


def fragment(cls: type[BaseModel], units: Units, *, const: dict[str, Any] | None = None,
             keep: Callable[[str], bool] | None = None) -> dict[str, Any]:
    """The schema of ``cls``, self-contained: a property ``const`` fixes held to its value,
    and with ``keep``, only the properties it keeps."""
    schema = _with_units(_inlined(cls), units)               # a new tree: the cached one is never changed
    props = schema.get("properties", {})
    if keep is not None:
        schema["properties"] = props = {k: v for k, v in props.items() if keep(k)}
        schema["required"] = [r for r in schema.get("required", []) if r in props]
    for key, value in (const or {}).items():
        props[key] = {**props.get(key, {}), "const": value}
        schema["required"] = list(dict.fromkeys([*schema.get("required", []), key]))
    return schema


def entry(o: ObjectType, type_: str | None, f: FormulationDefinition | None, units: Units) -> dict[str, Any]:
    """The fragment of one entry of ``o`` of type ``type_``: its class's, its type held and the
    fields that belong to another type dropped; what the formulation declares for the type —
    its sentence and section, its parameters — written in; for one value per type (a
    material), a key for each type the formulation declares. A value no model holds (a
    parameter) is its table's entry."""
    declared = dict(getattr(f, o.declared, None) or {}) if o.declared else {}
    cls = o.variant(type_)
    if o.declared and o.typed is None:                             # one value per type, by key
        each = fragment(cls, units)
        return {**_said(o.field().description), "type": "object", "additionalProperties": False,
                "properties": {t: {**each, **_said(spec.description, f, spec.section)} for t, spec in declared.items()}}
    if cls is None:
        return table(o.root(), o.table, units)
    schema = fragment(cls, units, const={o.typed: type_} if o.typed and type_ else None)
    if o.typed and type_:
        kept = {k: v for k, v in schema["properties"].items() if v.get("for", type_) == type_}
        schema["properties"], schema["required"] = kept, [r for r in schema.get("required", []) if r in kept]
    spec = declared.get(type_)
    if spec is not None:
        schema.update(_said(spec.description, f, spec.section))
        for name, p in getattr(spec, "parameters", {}).items():
            schema["properties"][name] = {"type": "string", "description": p.description, "quantity": "any",
                                          "unit": p.unit, "units": units.of(units.parse(p.unit).dimension),
                                          **_said(None, f, spec.section)}
            schema.setdefault("required", []).append(name)
        if getattr(spec, "parameters", None) is not None:
            schema["additionalProperties"] = False
    return schema


def _said(sentence: str | None, f: FormulationDefinition | None = None, section: str | None = None) -> dict:
    """A fragment's sentence and its `doc`: a section of the formulation's science document."""
    return {**({"description": sentence} if sentence else {}),
            **({"doc": f"{f.science} § {section}"} if f is not None and section else {})}


def help_of(node: dict[str, Any]) -> view.Help | None:
    """The help a fragment carries: its sentence, and where it is defined."""
    return view.Help.of(node.get("description"), node.get("doc"))


def keys(schema: dict[str, Any]) -> list[view.Field]:
    """Every key an object of ``schema`` may hold, as the help beside its text: its fragment, its
    sentence, whether it is required."""
    required = set(schema.get("required", []))
    return [view.Field(label=name, json_schema=node, help=help_of(node), required=name in required)
            for name, node in sorted(schema.get("properties", {}).items(), key=lambda kv: kv[0] not in required)]


def leaf(schema: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    """The fragment of the value at ``path`` within ``schema``; empty where the schema says
    nothing of it."""
    node = schema
    for step in path:
        props = node.get("properties", {})
        if step in props:
            node = props[step]
        elif isinstance(node.get("additionalProperties"), dict):
            node = node["additionalProperties"]
        else:
            return {}
    return node


def table(root: type[BaseModel], path: tuple[str, ...], units: Units) -> dict[str, Any]:
    """The fragment of one entry of the table at ``path`` in ``root`` — a parameter, a material —
    carrying the table's own `quantity` annotation where the entry has none."""
    node = leaf(fragment(root, units), path)
    entry = node.get("additionalProperties")
    if not isinstance(entry, dict):
        return node
    return {**({"quantity": node["quantity"]} if "quantity" in node else {}), "description": node.get("description"),
            **entry}

