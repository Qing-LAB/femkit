"""Templates: the text a new object starts from (web.md § 8.3), generated from its fragment
(`models/fields.py`), never written by hand. Its type is held; every other key it may hold is a
comment — an example of what it takes, required or not, its sentence, its unit or its choices —
which the person uncomments and fills. A value that is no table starts as an example of itself.
"""

from __future__ import annotations

from typing import Any

import tomlkit

#: What a key's example is, by the JSON type its fragment states: the one table of them.
EXAMPLES = {"string": "…", "number": 0, "integer": 0, "boolean": False}


def text(schema: dict[str, Any], held: dict[str, Any] | None = None) -> str:
    """The template of an object whose fragment is ``schema``, ``held`` its keys already
    decided — its type; a value's template when ``schema`` is no table."""
    if "properties" not in _one(schema):
        return _inline(_example(schema))
    return "\n".join(_lines(_one(schema), held or {}, "")) + "\n"


def _lines(schema: dict[str, Any], held: dict[str, Any], header: str) -> list[str]:
    """An object's lines: its sentence, its held keys, then each other key commented — a key
    that is a table of optional keys as a table of its own, after the rest, as TOML orders them."""
    lines = [f"# {schema['description']}"] if schema.get("description") and not header else []
    lines += [f"{tomlkit.key(k).as_string()} = {_inline(v)}" for k, v in held.items()]
    required = set(schema.get("required", []))
    tables = []
    for name, node in sorted(schema["properties"].items(), key=lambda kv: kv[0] not in required):
        if name in held:
            continue
        note = f"{'required' if name in required else 'to state' if node.get('stated') else 'optional'}: {_hint(node)}"
        own = _one(node)
        if own.get("type") == "object" and set(own.get("properties", {})) - set(own.get("required", [])):
            tables += ["", f"# [{header}{tomlkit.key(name).as_string()}]    # {note}",
                       *(f"#{line[1:]}" if line.startswith("# ") and " = " in line else line
                         for line in _lines(own, {}, f"{header}{name}."))]
        else:
            lines.append(f"# {tomlkit.key(name).as_string()} = {_inline(_example(node))}    # {note}")
    return lines + tables


def _one(node: dict[str, Any]) -> dict[str, Any]:
    """A fragment's own alternative: of an optional value, the one that is not null."""
    options = [o for o in node.get("anyOf", []) if o.get("type") != "null"]
    return {**{k: v for k, v in node.items() if k != "anyOf"}, **options[0]} if options else node


def _example(node: dict[str, Any]) -> Any:
    node = _one(node)
    if "const" in node:
        return node["const"]
    if node.get("enum"):
        return node["enum"][0]
    kind = node.get("type")
    if kind == "object":
        props = node.get("properties", {})
        required = node.get("required", list(props))
        return {k: _example(v) for k, v in props.items() if k in required}
    if kind == "array":
        items = node.get("items", {})
        return [_example(items)] * max(node.get("minItems", 1), 1) if items else []
    if node.get("unit"):                                    # a quantity, in its unit
        return f"… {node['unit']}"
    return EXAMPLES.get(kind, "…")


def _hint(node: dict[str, Any]) -> str:
    """The key's sentence, then what it takes: its choices, or the unit its quantity is in."""
    node = _one(node)
    said = node.get("description", "")
    if node.get("enum"):
        said += " — one of " + ", ".join(_inline(e) for e in node["enum"])
    elif node.get("unit"):
        said += f" — a quantity in {node['unit']}, or another unit of its dimension"
    return said


def _inline(value: Any) -> str:
    return tomlkit.item(value).as_string() if not isinstance(value, dict) else \
        "{ " + ", ".join(f"{tomlkit.key(k).as_string()} = {_inline(v)}" for k, v in value.items()) + " }"
