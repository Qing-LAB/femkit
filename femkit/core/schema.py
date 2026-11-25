"""The schema base and the one loader (core.md § 2).

Every declared file — shipped definition, user configuration, machine record, a project's
part — is a ``Model``. The model is the only place a field, its default, its allowed values
and its description are defined; the one reader, ``load_text``, turns any failure into one
``DefinitionError`` naming the file, the key path and the reason.
"""

from __future__ import annotations

import difflib
import json
import re
import tomllib
import types
import typing
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator, Literal, NamedTuple, TypeVar

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import InitErrorDetails, PydanticCustomError

from femkit.core import persist
from femkit.core.errors import Refusal

if TYPE_CHECKING:
    from femkit.core.view import Action

M = TypeVar("M", bound="Model")

SHA256 = re.compile(r"[0-9a-f]{64}")   # a SHA-256 digest, as its hex text


class Model(BaseModel):
    """Unknown keys are refused; a loaded value never changes. What it writes holds every field,
    so its serialization schema marks every field present, defaults too."""

    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_serialization_defaults_required=True)


class Problem(tuple):
    """One problem of a file that does not load (core.md § 2): the pair every reader unpacks — its
    key path, as the file writes it ("" for the file as a whole), and its reason, one plain
    sentence — and what would be right there: ``right``, the one value, or ``choices``, the values
    or keys that would do, closest first, each as the file would write it."""

    right: str | None
    choices: tuple[str, ...]

    def __new__(cls, path: str, reason: str, *, right: str | None = None, choices: Iterable[str] = ()) -> "Problem":
        made = super().__new__(cls, (path, reason))
        made.right, made.choices = right, tuple(choices)
        return made

    @property
    def path(self) -> str:
        return self[0]

    @property
    def reason(self) -> str:
        return self[1]


class DefinitionError(Refusal):
    """A declared file that does not load: every problem, each with its key path."""

    def __init__(self, file: Path | str, problems: Iterable[tuple[str, str]], next: Iterable[Action] = ()):
        self.file = str(file)
        self.problems = [p if isinstance(p, Problem) else Problem(*p) for p in problems]
        super().__init__("\n".join(self.lines()), next, code="definition-invalid", subject=self.file)

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
    """A location as the key path a file writes: dots between keys, each bare or quoted as TOML
    quotes it (`axes."mesh:fine:size"`), `[i]` for a list's item."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            key = part if persist.BARE.fullmatch(str(part)) else json.dumps(str(part))
            out += f".{key}" if out else key
    return out


def problem_path(model: type[BaseModel], loc: tuple) -> str:
    """Where a validation error of ``model`` lies, as the key path its file writes (core.md § 2):
    the keys alone (`_walk`)."""
    return key_path(_walk(model, loc)[0])


def _walk(model: type[BaseModel], loc: tuple) -> tuple[tuple, list | None]:
    """A validation error's location as the keys its file writes, and what the schema allows at
    the last of them — its annotations, None where the schema does not say. pydantic adds marks
    of its own to a location — a validator's kind (`function-after[…]`), the member of a union it
    tried (`int`, `literal['all']`, a model's name, a discriminator's tag) and `[key]` on a table's
    key — which a file never writes; each is left out, and a union narrowed to the member a mark
    names, read by walking the schema beside the location."""
    keys: list = []
    members: list | None = [model]
    for part in loc:
        if isinstance(part, str) and (part.startswith("function-") or part == "[key]"):
            continue
        if members is not None and len(members) == 1 and len(alternatives(members[0])) > 1:
            members = _member(members[0], part)         # `part` names the member pydantic tried
            continue
        keys.append(part)
        inner = _within(members, part) if members is not None else None
        members = [inner] if inner is not None else None
    return tuple(keys), members


def _member(annotation: Any, mark: Any) -> list:
    """The alternatives of a union a location's mark names — a member tagged so, a model of that
    name, or one whose literal field holds the tag a discriminator reads; all of them when the
    mark names none (`int`, `literal[…]`)."""
    tagged = []
    for arg in _union_args(annotation):
        inner, metadata = (typing.get_args(arg)[0], typing.get_args(arg)[1:]) \
            if typing.get_origin(arg) is typing.Annotated else (arg, ())
        if any(getattr(m, "tag", None) == mark for m in metadata):
            tagged.append(inner)
        elif isinstance(inner, type) and issubclass(inner, BaseModel) and (
                inner.__name__ == mark or any(mark in allowed(f.annotation) for f in inner.model_fields.values())):
            tagged.append(inner)
    return tagged or alternatives(annotation)


def _union_args(annotation: Any) -> list:
    """A union's members as written, each with its own annotations kept, through an outer `Annotated`."""
    if typing.get_origin(annotation) is typing.Annotated:
        return _union_args(typing.get_args(annotation)[0])
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return list(typing.get_args(annotation))
    return [annotation]


def _within(members: list, key: Any) -> Any:
    """The annotation of ``key`` in a value of one of ``members``: a model's field — a root model's
    root read through — a table's values or a list's items; None where the schema does not say."""
    for annotation in members:
        for cls in classes(annotation):
            if issubclass(cls, RootModel):
                return _within([cls.model_fields["root"].annotation], key)
            if named := field_named(cls, str(key)):
                return named[1].annotation
    for annotation in members:
        found = items_of(annotation) if isinstance(key, int) else values_of(annotation)
        if found is not None:
            return found
    return None


def validate(model: type[M], data: Any, file: Path | str, context: dict | None = None) -> M:
    """``data`` validated by ``model`` with ``context``: every problem at once, each at its key
    path, in plain words with what would be right (`problems`), in a `DefinitionError` naming
    ``file``."""
    try:
        return model.model_validate(data, context=context)
    except ValidationError as exc:
        raise DefinitionError(file, problems(model, data, exc.errors())) from None


#: What a value of each of pydantic's type errors should have been, as a person writes it.
WANTED = {
    "string_type": "a text, in quotes", "int_type": "a whole number", "int_parsing": "a whole number",
    "int_from_float": "a whole number", "float_type": "a number", "float_parsing": "a number",
    "decimal_type": "a number", "decimal_parsing": "a number", "bool_type": "`true` or `false`",
    "bool_parsing": "`true` or `false`", "list_type": "a list, in `[ ]`", "tuple_type": "a list, in `[ ]`",
    "set_type": "a list, in `[ ]`", "dict_type": "a table", "model_type": "a table",
    "model_attributes_type": "a table", "string_pattern_mismatch": "written in the form its help gives",
}
NEAR = 0.6   # how alike a misspelling and what it meant are, at least: difflib's own default


@dataclass(frozen=True)
class _Said:
    """One of pydantic's errors as a person reads it: where it is said, and either a whole reason
    or what the value there should have been (``wanted``), with the values that would do."""

    path: tuple                      # the keys it is said at
    reason: str | None = None        # a whole reason
    wanted: str | None = None        # what the value should be, for a value of the wrong kind
    given: Any = None                # the value written, for one of the wrong kind
    values: tuple = ()               # the values that would do, for a closed list
    missing: tuple | None = None     # a missing key's path, said at its table
    meant: tuple | None = None       # the missing key an unknown key most nearly spells


def problems(model: type[BaseModel], data: Any, errors: Iterable[dict]) -> list[Problem]:
    """pydantic's errors in validating ``data`` by ``model`` as the problems a person reads (core.md
    § 2; models.md § 13), each at the key path its file writes: an unknown key, at it, with the
    keys its table may still take, closest first — `szie` is no key here; did you mean `size`?; a
    value outside a closed list, with those values, or the one that is right; a value of the wrong
    kind, with what it should be; a missing key, at its table — said once, at the unknown key, when
    one beside it most nearly spells it. The problems at one key are joined into one, as the
    members of a union each give theirs."""
    said = [_said(model, data, err) for err in errors]
    meant = {s.meant for s in said if s.meant is not None}
    said = [s for s in said if s.missing is None or s.missing not in meant]
    grouped: dict[tuple, list[_Said]] = {}
    for s in said:
        grouped.setdefault(s.path, []).append(s)
    return [_joined(path, group) for path, group in grouped.items()]


def _said(model: type[BaseModel], data: Any, err: dict) -> _Said:
    keys, members = _walk(model, err["loc"])
    kind, name = err["type"], keys[-1] if keys else None
    if kind == "extra_forbidden" and name is not None:
        table = keys[:-1]
        written = _at(data, table)
        free = [k for k in _keys_of(_walk(model, err["loc"][:-1])[1])
                if not isinstance(written, dict) or k not in written]
        ranked = _closest(str(name), free)
        near = ranked[0] if ranked and _alike(str(name), ranked[0]) >= NEAR else None
        return _Said(keys, f"`{name}` is no key here" + (f"; did you mean `{near}`?" if near else ""),
                     values=tuple(key_path((k,)) for k in ranked), meant=(*table, near) if near else None)
    if kind == "missing" and name is not None:
        return _Said(keys[:-1], missing=keys)
    if "[key]" in err["loc"] and name is not None:       # a table's key, not its value, is wrong
        return _Said(keys, f"`{name}` cannot name an entry of this table: its help says how one is named")
    values = [v for m in members or () for v in allowed(m)] if kind == "literal_error" else []
    if values:
        return _Said(keys, wanted=_either([f"`{v if isinstance(v, str) else _shown(v)}`" for v in values]),
                     given=err["input"], values=tuple(values))         # each value as its help names it
    if kind in WANTED:
        return _Said(keys, wanted=WANTED[kind], given=err["input"])
    return _Said(keys, err["msg"].removeprefix("Value error, "))


def _joined(path: tuple, said: list[_Said]) -> Problem:
    """The problems at one key as one: a value of the wrong kind says what it should be — what
    each member of a union takes — with the closed values that would do, the one that is right
    when there is one."""
    reasons = list(dict.fromkeys(s.reason for s in said if s.reason is not None))
    gone = list(dict.fromkeys(f"`{s.missing[-1]}`" for s in said if s.missing is not None))
    if gone:
        reasons.append(f"{_either(gone)} {'is' if len(gone) == 1 else 'are'} missing")
    wanted = [s for s in said if s.wanted is not None]
    choices: list[str] = next((list(s.values) for s in said if s.reason is not None and s.values), [])
    if wanted:
        given = wanted[0].given
        values = [v for s in wanted for v in s.values]
        kinds = list(dict.fromkeys(s.wanted for s in wanted))
        ranked = _closest(given, values) if isinstance(given, str) else values
        near = next((v for v in ranked if isinstance(v, str) and _alike(given, v) >= NEAR), None) \
            if isinstance(given, str) else None
        reasons.insert(0, f"{_named(path)} is {_shown(given)}; " + (f"did you mean {_shown(near)}?" if near is not None
                                                                    else f"it should be {_either(kinds)}"))
        if len(values) == 1 and len(kinds) == 1:
            return Problem(key_path(path), reasons[0], right=_shown(values[0]))
        choices = [_shown(v) for v in ranked]
    return Problem(key_path(path), "; ".join(reasons), choices=choices)


def _named(path: tuple) -> str:
    """How a reason names the key at ``path``: its last key, with the items after it — `values[0]`."""
    last = max((i for i, k in enumerate(path) if not isinstance(k, int)), default=None)
    return f"`{key_path(path[last:])}`" if last is not None else "the file"


def _either(options: list[str]) -> str:
    """`a`, `a or b`, `a, b or c`."""
    return options[0] if len(options) == 1 else ", ".join(options[:-1]) + " or " + options[-1]


def _keys_of(members: list | None) -> list[str]:
    """The keys the models among ``members`` take, as a file writes them, in their order."""
    return list(dict.fromkeys(f.alias or n for m in members or () for cls in classes(m)
                              for n, f in cls.model_fields.items()))


def _at(data: Any, keys: tuple) -> Any:
    """What ``data`` holds at ``keys``: a table's entry, a list's item; None where it holds none."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list) and isinstance(key, int) and key < len(data):
            data = data[key]
        else:
            return None
    return data


def _alike(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _closest(written: str, candidates: Iterable[Any]) -> list[Any]:
    """``candidates``, the most like ``written`` first, the rest in their own order."""
    listed = list(candidates)
    return sorted(listed, key=lambda c: -_alike(written, c) if isinstance(c, str) else 0)


def _shown(value: Any) -> str:
    """A value as the file writes it, on one line, cut short when long."""
    try:
        shown = str(value) if isinstance(value, Decimal) else persist.inline_text(value)
    except (TypeError, ValueError):
        shown = repr(value)
    return shown if len(shown) <= 60 else shown[:57] + "…"


def load_text(text: str, model: type[M], file: Path | str, context: dict | None = None, *,
              exact: bool = False) -> M:
    """The one TOML reader (core.md § 2): ``text``, as the file ``file`` holds it, validated by
    ``model`` with ``context`` — the outside facts its validators read. ``exact``: every TOML
    float is read from its decimal text as a ``Decimal``, never a binary float — a model's
    numbers enter a case ID exactly (core.md § 11). A text that is not TOML says why in plain
    words, at its line (`not_toml`)."""
    try:
        data = tomllib.loads(text, parse_float=Decimal) if exact else tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DefinitionError(file, [not_toml(text, exc)]) from None
    return validate(model, data, file, context)


#: Where tomllib says its error is: `<what> (at line L, column C)`, or at the end of the text.
_AT = re.compile(r"(?P<what>.*) \(at (?:line (?P<line>\d+), column \d+|end of document)\)", re.S)
#: tomllib's own words, each read as what a person reads: the first that matches says it.
_PLAIN_TOML = (
    (re.compile(r"Illegal character '\\n'"), "a quoted text is not closed before the line ends"),
    (re.compile(r"Illegal character"), "a quoted text holds a character it cannot: write it as an escape, "
                                       "such as `\\t`"),
    (re.compile(r"Unterminated string"), "a quoted text is not closed"),
    (re.compile(r"Unescaped '\\' in a string"), "a `\\` in a quoted text: write `\\\\`, or put the text in "
                                                "single quotes"),
    (re.compile(r"Invalid hex value|Escaped character is not a Unicode"), "an escape `\\u…` in a quoted text is "
                                                                         "no character"),
    (re.compile(r"Unclosed array"), "a list opened with `[` is not closed with `]`"),
    (re.compile(r"Unclosed inline table"), "a table opened with `{` is not closed with `}`"),
    (re.compile(r"Expected '\]' at the end of a table"), "a table's header is not closed with `]`"),
    (re.compile(r"Expected '\]\]' at the end of an array"), "a header `[[…]]` is not closed with `]]`"),
    (re.compile(r"Expected '=' after a key"), "a key has no `=` and value after it"),
    (re.compile(r"Expected newline or end of document"), "more follows a value on its line: one `key = value` a "
                                                         "line, and a text with spaces in quotes"),
    (re.compile(r"Invalid value"), "a value does not read: a text goes in quotes, a list in `[ ]`, a table in "
                                   "`{ }`"),
    (re.compile(r"Invalid statement|Invalid initial character for a key"), "a line is neither `key = value` nor "
                                   "a `[table]` header: a key holding other than letters, digits, `_` and `-` goes "
                                   "in quotes"),
    (re.compile(r"Invalid date or datetime"), "a date or time does not read"),
)
_TWICE = re.compile(r"Cannot overwrite a value|Cannot declare .* twice|Cannot mutate immutable namespace|"
                    r"Cannot redefine namespace|Duplicate inline table key '(?P<inline>.*)'")


def not_toml(text: str, exc: tomllib.TOMLDecodeError) -> Problem:
    """Why ``text`` is not TOML, in plain words and at its line (core.md § 2): a key or table set
    twice, at that key, with both its lines — "`side` is set twice (lines 23 and 27)"; each other
    error tomllib names as a sentence a person reads; tomllib's own words kept only where none
    fits."""
    found = _AT.fullmatch(str(exc))
    if found is None:
        return Problem("", f"this is not TOML ({exc})")
    what, line = found["what"], int(found["line"]) if found["line"] else None
    where = f"line {line}" if line else "at the end of the file"
    if twice := _TWICE.match(what):
        if twice["inline"] is not None:
            return Problem("", f"{where}: `{twice['inline']}` is set twice in one table")
        written = [e for e in persist.key_comments(text) if not e.shown and (line is None or e.line <= line)]
        if written:
            last = written[-1]
            first = next((e for e in written if e.path == last.path and e.line < last.line), None)
            lines = f"lines {first.line} and {last.line}" if first else where
            if last.header and (first is None or first.header):
                return Problem(key_path(last.path), f"the table `[{key_path(last.path)}]` is written twice ({lines})")
            return Problem(key_path(last.path), f"`{key_path(last.path[-1:])}` is set twice ({lines})")
        return Problem("", f"{where}: a key or a table is set twice")
    plain = next((said for pattern, said in _PLAIN_TOML if pattern.match(what)), None)
    return Problem("", f"{where}: {plain}" if plain else f"{where}: this is not TOML ({what})")


def load_toml(path: Path, model: type[M], context: dict | None = None, *, exact: bool = False) -> M:
    """The file at ``path``, read by persist and then by ``load_text``; a file that is not
    there, or not UTF-8 text, does not load either (core.md § 2)."""
    try:
        text = persist.read_text(path)
    except UnicodeDecodeError as exc:
        raise DefinitionError(path, [("", f"this is not text written in UTF-8: byte {exc.start + 1} is not")]) from None
    if text is None:
        raise DefinitionError(path, [("", "there is no such file")])
    return load_text(text, model, path, context, exact=exact)


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


# ---------------------------------------------------------------- quantities and references
#
# Two annotations a field may carry (core.md § 2): `quantity`, a value written as a quantity
# (core.md § 11), and `ref`, the type of object it names.

LENGTH = (("length", 1),)   # a length's dimension (core.md § 11)


class QuantityKind(NamedTuple):
    """A `quantity` kind (core.md § 2): what its value is read as — `expression`, a quantity or
    an expression of the project's parameters; `quantity`, a quantity alone, naming no
    parameter; `unit`, a unit's text — its dimension, when fixed, and what a reader is told it
    takes."""

    reads: Literal["expression", "quantity", "unit"]
    dimension: tuple[tuple[str, int], ...] | None
    sentence: str


#: Each `quantity` kind — the one table the loaders, the cases, the forms' units and the
#: reference pages read.
QUANTITIES: dict[str, QuantityKind] = {
    "any": QuantityKind("expression", None, "a quantity with its unit, or an expression of parameters"),
    "length": QuantityKind("expression", LENGTH, "a length"),
    "constant": QuantityKind("quantity", None, "a quantity with its unit where it has one, naming no parameter"),
    "unit": QuantityKind("unit", None, "a unit"),
}
DIMENSIONS = {kind: k.dimension for kind, k in QUANTITIES.items() if k.dimension}


def as_quantity(description: str, kind: str = "any", *, extra: dict | None = None, **field: Any) -> Any:
    """A field written as a quantity of ``kind``, one of `QUANTITIES`, with any other annotation
    in ``extra`` and pydantic's other ``Field`` arguments."""
    return Field(description=description, json_schema_extra={"quantity": kind, **(extra or {})}, **field)


def as_reference(description: str, target: str | dict, *, extra: dict | None = None, **field: Any) -> Any:
    """A field naming objects of ``target``'s type — on a table, ``{"key": type, "value": type}`` —
    with any other annotation in ``extra`` and pydantic's other ``Field`` arguments."""
    return Field(description=description, json_schema_extra={"ref": target, **(extra or {})}, **field)


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
    """A field's help, one text (core.md § 2): its description; then, when its value — or a
    table's values — is a closed list, `: one of` and each allowed value in backticks; then
    where it is defined, its `doc` annotation, in parentheses."""
    values = _closed_list(field.annotation) or _closed_list(values_of(field.annotation))
    return help_text(field.description, values, field_extras(field).get("doc"))


def help_text(sentence: str | None, values: Iterable[Any] = (), doc: str | None = None, *,
              unit: str | None = None) -> str:
    """A help, one text (core.md § 2; projects.md § 7): ``sentence``; then, for a key a
    declaration states with its ``unit`` — a formulation's parameter, the property list's
    property — `, in` and the unit; then, when ``values`` — a closed list — are given, `: one of`
    and each in backticks; then ``doc`` in parentheses. The one builder of a help: what
    `described` makes of a field, and what each `declared` makes of a declaration's key."""
    shown = [f"`{v if isinstance(v, str) else persist.inline_text(v)}`" for v in values]
    closed_list = shown and "one of " + ", ".join(shown)
    said = f"{sentence}, in {unit}" if sentence and unit else sentence
    return ": ".join(part for part in (said, closed_list) if part) + (f" (see {doc})" if doc else "")


def _closed_list(annotation: Any) -> list[Any]:
    """Every value ``annotation`` allows, when it allows nothing but a `Literal`'s values."""
    options = alternatives(annotation) if annotation is not None else []
    return allowed(annotation) if options and all(typing.get_origin(a) is typing.Literal for a in options) else []


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


# ---------------------------------------------------------------- a template's help
#
# A template's comment above each key is that key's help as its schema states it
# (projects.md § 7): `persist.key_comments` reads the comments, `help_findings` compares them.

Declared = Callable[[tuple[str, ...]], str | None]


@dataclass(frozen=True)
class HelpFinding:
    """Where a template breaks the rule that a key's comment is its help (projects.md § 7)."""

    line: int | None    # the line it is on, from 1; None: the text as a whole
    key: str            # the key's path, `numerics.solver.kind`; "" for the text as a whole
    problem: str        # what is wrong, and what would be right

    def __str__(self) -> str:
        return f"line {self.line or '-'}: {self.key or '<text>'}: {self.problem}"


def help_findings(text: str, model: type[BaseModel], declared: Declared = lambda path: None) -> list[HelpFinding]:
    """Where ``text``, a template of a file ``model`` reads, breaks projects.md § 7: a key the
    schema names — a key whose name it fixes, or a table header ending in one — whose comment
    is not its help (`described`); a key the schema does not allow; a table the schema names
    that is not written as its own header, or one holding such keys written inline; a key of
    a table the text writes that it neither sets nor shows commented out. A key whose name the
    person chooses carries a note, never compared. ``declared`` gives, by its path, the help of
    a key a declaration outside the schema states — a formulation's parameter, the property
    list's property: its sentence, then `, in` and its unit — and None for every other key."""
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [HelpFinding(None, "", not_toml(text, exc).reason)]
    entries = persist.key_comments(text)
    written = {e.path[:n] for e in entries for n in range(1, len(e.path) + 1)}
    headed: set[tuple[str, ...]] = set()
    findings: list[HelpFinding] = []

    def help_of(path: tuple[str, ...]) -> tuple[str | None, bool]:
        """Its help, None when the person names it; and whether the schema allows it."""
        if (sentence := declared(path)) is not None:
            return sentence, True
        how, field, _ = _place(model, path)
        return (described(field) if field is not None else None), how != "unknown"

    for e in entries:
        key = key_path(e.path)
        sentence, allowed_here = help_of(e.path)
        if not allowed_here:
            findings.append(HelpFinding(e.line, key, "not a key its schema allows"))
            continue
        if sentence is not None and e.comment != sentence:
            findings.append(HelpFinding(e.line, key, f"its comment reads {e.comment!r}; its help is {sentence!r}"
                                        if e.comment else f"no help above it; its help is {sentence!r}"))
        for table in (e.path[:n] for n in range(1, len(e.path))):
            if table not in headed and help_of(table)[0] is not None:
                headed.add(table)   # said once
                findings.append(HelpFinding(e.line, key_path(table), "not written as its own table header, "
                                            "where its help would stand above it"))
        if e.header:
            headed.add(e.path)
        elif _tables_within(e.value) and _models_within(_place(model, e.path)[2]):
            findings.append(HelpFinding(e.line, key, "holds keys its schema names inline, with no help above "
                                        "them; write each table under its own header"))
    for line, table in [(None, ())] + [(e.line, e.path) for e in entries if e.header]:
        if len(models := _models_within(_place(model, table)[2], tables=False)) == 1:
            for name, field in models[0].model_fields.items():
                if (path := (*table, field.alias or name)) not in written:
                    findings.append(HelpFinding(line, key_path(path), f"neither set nor shown; show it commented "
                                                f"out under its help, {described(field)!r}"))
    return findings


def _place(model: type[BaseModel], path: tuple[str, ...]) -> tuple[str, FieldInfo | None, Any]:
    """Where ``path`` leads in ``model``'s schema, and what may stand there: `fixed`, with its
    field, when the schema names its last key; `chosen` when the person names it, a table's
    key; `open` under a value whose keys the schema leaves free; `unknown` when the schema has
    no such key."""
    how: str = "fixed"
    field: FieldInfo | None = None
    annotation: Any = model
    for key in path:
        if how == "open":
            break
        if models := _models_within(annotation, tables=False):
            named = next((found for m in models if (found := field_named(m, key))), None)
            if named is None:
                return "unknown", None, None
            how, field, annotation = "fixed", named[1], named[1].annotation
        elif keys_of(annotation) is not None:
            how, field, annotation = "chosen", None, values_of(annotation)
        elif any(a is Any or a is dict for a in alternatives(annotation)):
            how, field, annotation = "open", None, None
        else:
            return "unknown", None, None
    return how, field, annotation


def _models_within(annotation: Any, tables: bool = True) -> list[type[BaseModel]]:
    """The models a value of ``annotation`` is written as tables of: itself, a list's items and,
    with ``tables``, a table's values."""
    if annotation is None:
        return []
    return classes(annotation) or classes(items_of(annotation)) or (classes(values_of(annotation)) if tables else [])


def _tables_within(value: Any) -> bool:
    """Whether a value, as TOML reads it, holds a table: an inline one, or a list of them."""
    return isinstance(value, dict) and bool(value) or isinstance(value, list) and any(isinstance(v, dict) for v in value)
