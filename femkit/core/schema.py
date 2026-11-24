"""The schema base and the one loader (definitions.md § 2).

Every declared file — shipped definition, user configuration, machine record —
is a ``Model``. The model is the only place a field, its default, its allowed
values and its description are defined; the loader turns any failure into one
``DefinitionError`` naming the file, the key path and the reason.
"""

from __future__ import annotations

import re
import tomllib
import types
import typing
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import InitErrorDetails, PydanticCustomError

from femkit.core.errors import Refusal

if TYPE_CHECKING:
    from femkit.core.view import Action

M = TypeVar("M", bound="Model")

SHA256 = re.compile(r"[0-9a-f]{64}")   # a SHA-256 digest, as its hex text


class Model(BaseModel):
    """Unknown keys are refused; a loaded value never changes. What it writes holds every field,
    so its serialization schema marks every field present, defaults too."""

    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_serialization_defaults_required=True)


class DefinitionError(Refusal):
    """A declared file that does not load: every problem, each with its key path."""

    def __init__(self, file: Path | str, problems: Iterable[tuple[str, str]], next: Iterable[Action] = ()):
        self.file = str(file)
        self.problems = list(problems)
        super().__init__("\n".join(self.lines()), next)

    def lines(self) -> list[str]:
        """Each problem on its own line, with its file and key path."""
        return [f"{self.file}: {path or '<file>'}: {reason}" for path, reason in self.problems]

    def summary(self) -> str:
        """Every problem on one line, each at its key path: for a row or a listing that names the file apart."""
        return "; ".join(f"{path or '<file>'}: {reason}" for path, reason in self.problems)


def refuse(model: str, problems: list[tuple[tuple, str]]) -> None:
    """Raise every cross-reference problem at once, each at its own key path.

    For a model validator (core.md § 2): ``problems`` are ``(location, reason)``
    with the location relative to the model, e.g. ``("builds", 1, "source")``.
    """
    if problems:
        raise ValidationError.from_exception_data(model, [
            InitErrorDetails(type=PydanticCustomError("reference", "{reason}", {"reason": reason}),
                             loc=loc, input=None)
            for loc, reason in problems
        ])


def key_path(loc: tuple) -> str:
    """A validation error's location as a key path: dots between keys, `[i]` for a list's item."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def validate(model: type[M], data: Any, file: Path | str, context: dict | None = None) -> M:
    try:
        return model.model_validate(data, context=context)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            # pydantic adds the validator kind (function-after, …) to a location; drop it
            loc = tuple(p for p in err["loc"] if not (isinstance(p, str) and p.startswith("function-")))
            problems.append((key_path(loc), err["msg"].removeprefix("Value error, ")))
        raise DefinitionError(file, problems) from None


def load_toml(path: Path, model: type[M], context: dict | None = None, *, exact: bool = False) -> M:
    """``exact``: every TOML float is read from its decimal text as a ``Decimal``, never a
    binary float — a model's numbers enter a case ID exactly (core.md § 11)."""
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh, parse_float=Decimal) if exact else tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise DefinitionError(path, [("", f"not TOML: {exc}")]) from None
    return validate(model, data, path, context)


# ---------------------------------------------------------------- placeholders
#
# One grammar everywhere (definitions.md § 4.3): `{name}` or `{name:argument}`.
# Which names a field accepts is declared by that field, never guessed.

PLACEHOLDER = re.compile(r"\{([^{}:]*)(?::([^{}]*))?\}")


def placeholders(text: str) -> list[tuple[str, str | None]]:
    return [(m.group(1), m.group(2)) for m in PLACEHOLDER.finditer(text)]


def check_placeholders(text: str, allowed: frozenset[str]) -> str:
    """Return ``text`` when every placeholder in it is one ``allowed`` names."""
    for name, _arg in placeholders(text):
        if name not in allowed:
            names = ", ".join("{%s}" % n for n in sorted(allowed)) or "none"
            raise ValueError(f"placeholder {{{name}}} is not allowed here (allowed: {names})")
    return text


def render(text: str, values: dict[str, str]) -> str:
    """Substitute placeholders; ``values`` keys are `name` or `name:argument`."""

    def one(m: re.Match) -> str:
        key = m.group(1) if m.group(2) is None else f"{m.group(1)}:{m.group(2)}"
        return values[key]

    return PLACEHOLDER.sub(one, text)


# ---------------------------------------------------------------- annotations
#
# The one reading of a field's annotation: what it may hold, the model classes among that, a
# table's values, the closed values of a `Literal`. Every walk of a schema goes through these.

def alternatives(annotation: Any) -> list[Any]:
    """What an annotation may hold, through `Annotated`, `Optional` and unions; never `None`."""
    if typing.get_origin(annotation) is typing.Annotated:
        return alternatives(typing.get_args(annotation)[0])
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return [a for arg in typing.get_args(annotation) for a in alternatives(arg)]
    return [] if annotation is type(None) else [annotation]


def optional(annotation: Any) -> bool:
    """Whether an annotation allows `None`, through `Annotated` and unions."""
    if typing.get_origin(annotation) is typing.Annotated:
        return optional(typing.get_args(annotation)[0])
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return any(optional(a) for a in typing.get_args(annotation))
    return annotation is type(None)


def classes(annotation: Any) -> list[type[BaseModel]]:
    """The model classes an annotation may hold."""
    return [a for a in alternatives(annotation) if isinstance(a, type) and issubclass(a, BaseModel)]


def keys_of(annotation: Any) -> Any:
    """A table's keys' annotation; None when it holds no table."""
    tables = [a for a in alternatives(annotation) if typing.get_origin(a) is dict]
    return typing.get_args(tables[0])[0] if tables else None


def values_of(annotation: Any) -> Any:
    """A table's values' annotation; None when it holds no table."""
    tables = [a for a in alternatives(annotation) if typing.get_origin(a) is dict]
    return typing.get_args(tables[0])[1] if tables else None


def items_of(annotation: Any) -> Any:
    """A list's items' annotation; None when it holds no list."""
    lists = [a for a in alternatives(annotation) if typing.get_origin(a) in (list, tuple)]
    return (typing.get_args(lists[0]) or (str,))[0] if lists else None


def allowed(annotation: Any) -> list[Any]:
    """Every value a `Literal` among its alternatives allows, text or not."""
    return [v for a in alternatives(annotation) if typing.get_origin(a) is typing.Literal for v in typing.get_args(a)]


def closed(annotation: Any) -> list[str]:
    """The text values a `Literal` among its alternatives allows."""
    return [v for v in allowed(annotation) if isinstance(v, str)]


def whole(pattern: re.Pattern[str] | str) -> str:
    """``pattern`` tied to the whole value, as a schema's pattern must be: pydantic and JSON
    Schema search inside a value, so a name's pattern left open would take `../outside`."""
    return f"^(?:{pattern.pattern if isinstance(pattern, re.Pattern) else pattern})$"


def matching(pattern: re.Pattern[str] | str, **field: Any) -> Any:
    """A text field whose whole value matches ``pattern`` — a name, a digest, an ID — with
    pydantic's other ``Field`` arguments."""
    return Field(pattern=whole(pattern), **field)


def field_named(cls: type[BaseModel], key: str) -> tuple[str, FieldInfo] | None:
    """The field a file writes as ``key``: by its alias, else its name."""
    return next(((n, f) for n, f in cls.model_fields.items() if (f.alias or n) == key), None)


# ---------------------------------------------------------------- field annotations

def field_extras(field: FieldInfo) -> dict:
    """A field's json_schema_extra, merged with any inside its (Annotated, optional) type."""
    found: dict = {}

    def walk(annotation: Any) -> None:
        if typing.get_origin(annotation) is typing.Annotated:
            for meta in typing.get_args(annotation)[1:]:
                if isinstance(meta, FieldInfo) and isinstance(meta.json_schema_extra, dict):
                    found.update(meta.json_schema_extra)
        for arg in typing.get_args(annotation):
            walk(arg)

    walk(field.annotation)
    for meta in field.metadata:
        if isinstance(meta, FieldInfo) and isinstance(meta.json_schema_extra, dict):
            found.update(meta.json_schema_extra)
    if isinstance(field.json_schema_extra, dict):
        found.update(field.json_schema_extra)
    return found


def described(field: FieldInfo) -> str:
    """A field's sentence as a text says it: its description, and where it is defined after it
    (its `doc` annotation, core.md § 2)."""
    doc = field_extras(field).get("doc")
    return (field.description or "") + (f" ({doc})" if doc else "")


def references(instance: BaseModel, at: tuple = ()) -> Iterator[tuple[tuple, str, str, str]]:
    """Every name ``instance`` refers to, as ``(location, type, name, held)``, from its fields' `ref`
    annotations (core.md § 2): on a text or a list of texts, ``ref`` is the type its values
    name; on a table, ``ref`` is ``{"key": type, "value": type}``, either part optional. A
    type may offer alternatives, `region:boundary|region:interface`. ``held`` says how: `key`
    (the table key at the location), `value` (the text there) or `item` (a list's item)."""
    for name, field in type(instance).model_fields.items():
        value = getattr(instance, name)
        key = field.alias or name
        ref = field_extras(field).get("ref")
        if isinstance(ref, str):
            listed = isinstance(value, (list, tuple))
            for i, item in enumerate(value if listed else [value]):
                if isinstance(item, str):
                    yield ((*at, key, i) if listed else (*at, key)), ref, item, ("item" if listed else "value")
        elif isinstance(ref, dict) and isinstance(value, dict):
            for k, v in value.items():
                if "key" in ref:
                    yield (*at, key, k), ref["key"], k, "key"
                if "value" in ref and isinstance(v, str):
                    yield (*at, key, k), ref["value"], v, "value"
        for loc, item in _children(value, (*at, key)):
            yield from references(item, loc)


def _children(value: Any, at: tuple) -> Iterator[tuple[tuple, BaseModel]]:
    if isinstance(value, BaseModel):
        yield at, value
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            yield from _children(item, (*at, i))
    elif isinstance(value, dict):
        for k, item in value.items():
            yield from _children(item, (*at, k))
