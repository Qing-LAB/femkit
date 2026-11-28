"""The schema base and the one loader (core.md § 2).

Every declared file — shipped definition, user configuration, machine record, a project's
part — is a ``Model``. The model is the only place a field, its default, its allowed values
and its description are defined; the one reader, ``load_text``, turns any failure into one
``DefinitionError`` naming the file, the key path and the reason.
"""

from __future__ import annotations

import difflib
import functools
import json
import re
import tomllib
import types
import typing
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Any, Callable, ClassVar, Generic, Iterable, Iterator, Literal, NamedTuple, TypeVar

from pydantic import BaseModel, ConfigDict, Field, RootModel, Strict, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import InitErrorDetails, PydanticCustomError

from femkit.core import dirs, persist
from femkit.core.errors import Refusal
from femkit.core.markdown import headings

if TYPE_CHECKING:
    from femkit.core.view import Action

M = TypeVar("M", bound="Model")

SHA256 = re.compile(r"[0-9a-f]{64}")   # a SHA-256 digest, as its hex text


class Model(BaseModel):
    """Unknown keys are refused; a loaded value never changes. What it writes holds every field,
    so its serialization schema marks every field present, defaults too. A key a model no longer
    takes may be declared in `WITHDRAWN`, with what a file writing it is told (core.md § 2)."""

    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_serialization_defaults_required=True)

    #: Each key the model no longer takes, by its name, with what a file writing it is told — said
    #: in place of the keys the table may still take (`problems`).
    WITHDRAWN: ClassVar[dict[str, str]] = {}


class Problem(tuple):
    """One problem of a file that does not load (core.md § 2): the pair every reader unpacks — its
    key path, as the file writes it ("" for the file as a whole), and its reason, one plain
    sentence — and what would be right there: ``right``, the one value, or ``choices``, the values
    or keys that would do, closest first, each as the file would write it; and ``line``, for a text
    that is not TOML, where it stops reading — the line tomllib names, a key set twice's second —
    none where none is said, a problem at a key's line then read from the text by its key (core.md
    § 10); a reason names no line `line` holds, which a finding and a message each say once
    (`where`)."""

    right: str | None
    choices: tuple[str, ...]
    line: int | None

    def __new__(cls, path: str, reason: str, *, right: str | None = None, choices: Iterable[str] = (),
                line: int | None = None) -> "Problem":
        made = super().__new__(cls, (path, reason))
        made.right, made.choices, made.line = right, tuple(choices), line
        return made

    @property
    def path(self) -> str:
        return self[0]

    @property
    def reason(self) -> str:
        return self[1]

    @property
    def where(self) -> str:
        """Where a message places it: its key path; for a problem at no key, its line, `line 23`,
        where it has one — said there once, never in its reason too; else nothing, the file as a
        whole."""
        return self.path or (f"line {self.line}" if self.line is not None else "")


class DefinitionError(Refusal):
    """A declared file that does not load: every problem, each with its key path."""

    def __init__(self, file: Path | str, problems: Iterable[tuple[str, str]], next: Iterable[Action] = ()):
        self.file = str(file)
        self.problems = [p if isinstance(p, Problem) else Problem(*p) for p in problems]
        super().__init__("\n".join(self.lines()), next, code="definition-invalid", subject=self.file)

    def lines(self) -> list[str]:
        """Each problem on its own line, with its file and where it lies (`Problem.where`)."""
        return [f"{self.file}: {p.where or '<file>'}: {p.reason}" for p in self.problems]

    def summary(self) -> str:
        """Every problem on one line, each where it lies: for a row or a listing that names the file apart."""
        return "; ".join(f"{p.where or '<file>'}: {p.reason}" for p in self.problems)


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
#: What a value of a type pydantic checks by `isinstance` should have been: an exact number's.
INSTANCES = {"Decimal": "a number"}
NEAR = 0.6   # how alike a misspelling and what it meant are, at least: difflib's own default


def nearest(name: str, among: Iterable[str], forms: Callable[[str], Iterable[str]] = lambda c: (c,)) -> str | None:
    """The one of ``among`` closest to ``name`` — what a misspelling most likely meant — or None
    where none is close: each compared by each of its ``forms`` (itself, unless given), by the
    standard library's measure and at least as alike as `NEAR` asks; the first of equals, so
    ``among`` in the order a person looks wins a tie. The one reading of "did you mean" (core.md
    § 2): a schema's unknown key, a unit, a name a part cites."""
    best, score = None, NEAR
    for candidate in among:
        alike = max((_alike(name, form) for form in forms(candidate)), default=0.0)
        if alike > score or (best is None and alike >= score):
            best, score = candidate, alike
    return best


def meant(name: str, among: Iterable[str], forms: Callable[[str], Iterable[str]] = lambda c: (c,),
          shown: Callable[[str], str] = lambda n: n) -> str:
    """`; did you mean `x`?` for the one of ``among`` closest to ``name`` (`nearest`), as ``shown``
    writes it — `defs.x` for a definition a function reads — the end of a sentence a finding says;
    nothing where none is close."""
    near = nearest(name, among, forms)
    return f"; did you mean `{shown(near)}`?" if near is not None else ""


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
    keys its table may still take, closest first — `szie` is no key here; did you mean `size`? — or,
    for a key its model no longer takes, what its `WITHDRAWN` tells a file writing it; a value
    outside a closed list, with those values, or the one that is right; a value of the wrong
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
        withdrawn = [getattr(cls, "WITHDRAWN", {}) for m in _walk(model, err["loc"][:-1])[1] or () for cls in classes(m)]
        gone = next((w[str(name)] for w in withdrawn if str(name) in w), None)
        if gone is not None:                              # a key the model no longer takes, said in its words
            return _Said(keys, f"`{name}` is no key here: {gone}")
        written = _at(data, table)
        free = [k for k in _keys_of(_walk(model, err["loc"][:-1])[1])
                if not isinstance(written, dict) or k not in written]
        ranked = _closest(str(name), free)
        near = nearest(str(name), ranked)
        return _Said(keys, f"`{name}` is no key here" + meant(str(name), ranked),
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
    if kind == "is_instance_of" and (err.get("ctx") or {}).get("class") in INSTANCES:
        return _Said(keys, wanted=INSTANCES[err["ctx"]["class"]], given=err["input"])
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
        near = nearest(given, [v for v in ranked if isinstance(v, str)]) if isinstance(given, str) else None
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
        shown = persist.inline_text(value)
    except (TypeError, ValueError):
        shown = repr(value)
    return shown if len(shown) <= 60 else shown[:57] + "…"


def load_text(text: str, model: type[M], file: Path | str, context: dict | None = None) -> M:
    """The one TOML reader (core.md § 2): ``text``, as the file ``file`` holds it, read
    (`parse_text`) and validated by ``model`` with ``context`` — the outside facts its validators
    read."""
    return validate(model, parse_text(text, file), file, context)


def parse_text(text: str, file: Path | str) -> dict[str, Any]:
    """``text``, as the file ``file`` holds it, read as TOML before any model validates it — a
    project file's table read alone (models.md § 2). Every TOML number is read from
    the text written, exactly (`persist.exact_number`; core.md § 11): a model's numbers enter a case
    ID exactly. A text that is not TOML says why in plain words, at its line (`not_toml`)."""
    try:
        return tomllib.loads(text, parse_float=persist.exact_number)
    except tomllib.TOMLDecodeError as exc:
        raise DefinitionError(file, [not_toml(text, exc)]) from None


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
    fits. The line it stops at is the problem's `line`, said once: its reason names no line of its
    own, but where tomllib stops at the end of the text, which no line holds."""
    found = _AT.fullmatch(str(exc))
    if found is None:
        return Problem("", f"this is not TOML ({exc})")
    what, line = found["what"], int(found["line"]) if found["line"] else None
    end = "" if line else "at the end of the file: "
    if twice := _TWICE.match(what):
        if twice["inline"] is not None:
            return Problem("", f"{end}`{twice['inline']}` is set twice in one table", line=line)
        written = [e for e in persist.key_comments(text) if not e.shown and (line is None or e.line <= line)]
        if written:
            last = written[-1]
            first = next((e for e in written if e.path == last.path and e.line < last.line), None)
            lines = f" (lines {first.line} and {last.line})" if first else ""
            if last.header and (first is None or first.header):
                return Problem(key_path(last.path), f"the table `[{key_path(last.path)}]` is written twice{lines}",
                               line=last.line)
            return Problem(key_path(last.path), f"`{key_path(last.path[-1:])}` is set twice{lines}", line=last.line)
        return Problem("", f"{end}a key or a table is set twice", line=line)
    plain = next((said for pattern, said in _PLAIN_TOML if pattern.match(what)), None)
    return Problem("", f"{end}{plain}" if plain else f"{end}this is not TOML ({what})", line=line)


def load_toml(path: Path, model: type[M], context: dict | None = None) -> M:
    """The file at ``path``, read by persist and then by ``load_text``; a file that is not
    there, or not UTF-8 text, does not load either (core.md § 2)."""
    try:
        text = persist.read_text(path)
    except UnicodeDecodeError as exc:
        raise DefinitionError(path, [("", f"this is not text written in UTF-8: byte {exc.start + 1} is not")]) from None
    if text is None:
        raise DefinitionError(path, [("", "there is no such file")])
    return load_text(text, model, path, context)


# ---------------------------------------------------------------- placeholders
#
# One grammar everywhere (core.md § 2.1): `{name}`, `{name:argument}`, and, alone in an argument
# of an argument list, `{name?}`. Which names a field accepts is declared by that field, never
# guessed.

_PLACEHOLDER = re.compile(r"\{([^{}:?]*)(\?)?(?::([^{}]*))?\}")


@dataclass(frozen=True)
class Placeholder:
    """One placeholder as written: its name, whether it is optional, its argument; ``key`` is
    what its value is found by."""

    name: str
    optional: bool
    argument: str | None
    span: tuple[int, int]

    @property
    def key(self) -> str:
        return self.name if self.argument is None else f"{self.name}:{self.argument}"


def parsed(text: str) -> list[Placeholder]:
    """Every placeholder in ``text``, in order: the grammar's one reader."""
    return [Placeholder(m.group(1), m.group(2) is not None, m.group(3), m.span()) for m in _PLACEHOLDER.finditer(text)]


def placeholders(text: str) -> list[tuple[str, str | None]]:
    return [(p.name, p.argument) for p in parsed(text)]


def _check(text: str, allowed: frozenset[str], optional_alone: bool) -> str:
    found = parsed(text)
    for p in found:
        if p.name not in allowed:
            names = ", ".join("{%s}" % n for n in sorted(allowed)) or "none"
            raise ValueError(f"placeholder {{{p.name}}} is not allowed here (allowed: {names})")
        if p.optional and not (optional_alone and p.argument is None and p.span == (0, len(text))):
            raise ValueError(f"{text}: an optional placeholder, {{{p.name}?}}, stands alone in an argument of an "
                             "argument list, or nowhere")
    return text


def check_placeholders(text: str, allowed: frozenset[str]) -> str:
    """Return ``text`` when every placeholder in it is one ``allowed`` names, none optional."""
    return _check(text, allowed, optional_alone=False)


def check_arguments(arguments: list[str], allowed: frozenset[str]) -> list[str]:
    """Return an argument list when every placeholder in it is one ``allowed`` names, an optional
    one only alone in its argument (core.md § 2.1)."""
    for argument in arguments:
        _check(argument, allowed, optional_alone=True)
    return arguments


def render(text: str, values: dict[str, str]) -> str:
    """Substitute placeholders; ``values`` keys are `name` or `name:argument`."""
    out, at = [], 0
    for p in parsed(text):
        out += [text[at:p.span[0]], values[p.key]]
        at = p.span[1]
    return "".join(out) + text[at:]


def render_arguments(arguments: list[str], values: dict[str, str | None]) -> list[str]:
    """An argument list with its placeholders substituted (core.md § 2.1): an argument that is
    one optional placeholder alone, `{name?}`, is left out when its value is None; any other
    placeholder whose value is None is a defect where the values were made."""
    out = []
    for argument in arguments:
        found = parsed(argument)
        if len(found) == 1 and found[0].optional and values.get(found[0].key) is None:
            continue
        absent = [p.key for p in found if values.get(p.key, "") is None]
        if absent:
            raise ValueError(f"{argument}: no value for {', '.join('{%s}' % a for a in absent)}, which only "
                             "an optional placeholder alone in its argument may lack")
        out.append(render(argument, {k: v for k, v in values.items() if v is not None}))
    return out


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

#: A number as a file writes it (core.md § 11): a whole number, or a decimal one read exactly from
#: the text written (`persist.exact_number`) — never a binary float, a truth value or a text.
Number = Annotated[int, Strict()] | Annotated[Decimal, Strict()]

V = TypeVar("V")


class Measure(Model, Generic[V]):
    """A quantity in the one form a file writes it in (core.md § 11): its number — or, for a
    point, a line or a range, its numbers — and the one unit they are in."""

    value: V = Field(description="its number; for a point, a line or a range, its numbers, all in its unit")
    unit: str = Field(description="the unit its number is in: a unit femkit reads, or a product of them",
                      json_schema_extra={"quantity": "unit"})

    @classmethod
    def model_parametrized_name(cls, params: tuple[Any, ...]) -> str:
        """`Measure` for one number; `MeasureList` for a point or a range, `MeasureListList` for a
        line: a name a reference page heads it with."""
        depth, held = 0, params[0]
        while typing.get_origin(held) is list:
            depth, held = depth + 1, typing.get_args(held)[0]
        return cls.__name__ + "List" * depth


#: What a field written as one quantity holds (core.md § 11): its `{value, unit}`; a plain number,
#: where it has no unit; or a text — the name of a definition, where its kind may cite one, and a
#: finding saying the table to write anywhere else.
Measured = Measure[Number] | Number | str

#: Each number of a range's `{value, unit}` as a file writes it (core.md
#: § 11): a number in its unit, or a text — the name of a definition, its own value, where the
#: field's kind may cite one, and a finding anywhere else.
NumberOrName = Number | str


def names_in(written: Any) -> list[str]:
    """Each name a value written in the one quantity form gives in place of a number (core.md
    § 11): itself, where it is a text; each text among a `{value, unit}`'s numbers. Whether a name
    may stand there is the field's kind's (`QUANTITIES`)."""
    if isinstance(written, str):
        return [written]
    if not isinstance(written, Measure):
        return []
    out: list[str] = []
    walking = [written.value]
    while walking:
        now = walking.pop(0)
        if isinstance(now, list):
            walking[:0] = now
        elif isinstance(now, str) and now not in out:
            out.append(now)
    return out


class QuantityKind(NamedTuple):
    """A `quantity` kind (core.md §§ 2, 11): what its value is read as — `quantity`, the one
    quantity form; `unit`, a unit's text — whether a definition's name may stand for its value,
    its dimension, when fixed, and what a reader is told it takes."""

    reads: Literal["quantity", "unit"]
    cites: bool
    dimension: tuple[tuple[str, int], ...] | None
    sentence: str


#: Each `quantity` kind — the one table the loaders, the cases, the forms' units and the
#: reference pages read.
QUANTITIES: dict[str, QuantityKind] = {
    "any": QuantityKind("quantity", True, None, "a quantity, `{value, unit}` — a plain number where it has no unit — "
                                                "or a definition's name"),
    "length": QuantityKind("quantity", True, LENGTH, "a length, `{value, unit}`, or a definition's name"),
    "constant": QuantityKind("quantity", False, None, "a quantity, `{value, unit}` — a plain number where it has no "
                                                      "unit — naming no definition"),
    "unit": QuantityKind("unit", False, None, "a unit"),
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


#: The annotation of a field that names a folder or a file by its path, with what it names: a step
#: for another machine gives it by its path from the project's folder (`path_fields`; workflow.md § 7).
PATH = "path"


def as_path(description: str, names: Literal["folder", "file"], *, extra: dict | None = None, **field: Any) -> Any:
    """A field naming a folder or a file, ``names``, by its path — the `path` annotation — with any
    other annotation in ``extra`` and pydantic's other ``Field`` arguments."""
    return Field(description=description, json_schema_extra={PATH: names, **(extra or {})}, **field)


def path_fields(model: type[BaseModel]) -> list[str]:
    """The fields of ``model`` that name a folder or a file, as their `path` annotation declares —
    never told from a value (workflow.md § 7)."""
    return [name for name, f in model.model_fields.items() if field_extras(f).get(PATH)]


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


def described(field: FieldInfo, manual: str | None = None) -> str:
    """A field's help, one text (core.md § 2): its description; then, when its value — or a
    table's values — is a closed list, `: one of` and each allowed value in backticks; then, for
    a field whose values a declaration holds (`choices`), the names it holds now; then, where the
    field states a `doc`, the chapter of the manual that explains it — ``manual``, the chapter its
    file or command declares — as `(manual: <title>)`. The `doc` itself is the reference pages':
    a help never cites a contract."""
    values = _closed_list(field.annotation) or _closed_list(values_of(field.annotation))
    return help_text(field.description, values, manual if field_extras(field).get("doc") else None,
                     among=choices(field))


def help_text(sentence: str | None, values: Iterable[Any] = (), manual: str | None = None, *,
              unit: str | None = None, among: tuple[str, list[str]] | None = None) -> str:
    """A help, one text (core.md § 2; projects.md § 7): ``sentence``; then, for a key a
    declaration states with its ``unit`` — a formulation's parameter, the property list's
    property — `, in` and the unit; then, when ``values`` — a closed list — are given, `: one of`
    and each in backticks; then, for ``among`` — a declaration's name and the names it holds —
    `; the <declaration>:` and each in backticks; then the manual's chapter ``manual``, by its
    title, `(manual: 6 · Materials)`. The one builder of a help: what `described` makes of a
    field, and what each `declared` makes of a declaration's key."""
    shown = [f"`{v if isinstance(v, str) else persist.inline_text(v)}`" for v in values]
    closed_list = shown and "one of " + ", ".join(shown)
    said = f"{sentence}, in {unit}" if sentence and unit else sentence
    text = ": ".join(part for part in (said, closed_list) if part)
    if among is not None:
        text += f"; the {among[0]}: " + ", ".join(f"`{name}`" for name in among[1])
    return text + (f" {pointer(manual)}" if manual else "")


def pointer(manual: str) -> str:
    """Where a help sends the person: the manual's chapter ``manual`` by its title, `(manual: 6 ·
    Materials)` — what ends a field's help and a command's (core.md § 2; api.md § 4)."""
    return f"(manual: {chapter(manual)})"


#: The user manual's folder, from the checkout's root (docs/README.md § 3.1): where a help sends
#: the person, by a chapter's title.
MANUAL_DIR = PurePosixPath("docs/manual")


@functools.cache
def chapter_name(file: str) -> bool:
    """Whether ``file`` is written as a chapter of the manual is named: a file's name alone in
    `docs/manual/`, ending in `.md` — what a declaration naming one must be where it loads."""
    named = PurePosixPath(file)
    return named.name == file and named.suffix == ".md" and file != ".md"


def chapter(file: str) -> str:
    """The manual's chapter ``file`` — a file of the checkout's `docs/manual/`, `6-materials.md` —
    as a help names it: its title, the file's first heading, `6 · Materials` (core.md § 2). Where
    the checkout holds no such file, or it opens with no heading, the file's own name: a help is
    never refused for a document, and the basic tests hold every declared chapter to one the
    manual has. A `ValueError` for a name no chapter could have (`chapter_name`)."""
    if not chapter_name(file):
        raise ValueError(f"{file!r} is no chapter of the manual: a file's name in {MANUAL_DIR}/, ending in .md")
    text = persist.read_text(dirs.checkout() / MANUAL_DIR / file)
    found = headings(text) if text is not None else []
    return found[0].text if found else file


# ---------------------------------------------------------------- values a declaration holds
#
# A request field whose values are the names a declaration holds — the importers, the
# environments, the templates — names that declaration in `choices` (core.md § 2). What gives its
# names is registered at start (api.md § 6) and called only when a help is built, never at import:
# a help names the declarations of that moment, those `FEMKIT_DEFINITIONS_DIR` points at.

_PROVIDERS: dict[str, Callable[[], Iterable[str]]] = {}


def provide(declaration: str, names: Callable[[], Iterable[str]]) -> None:
    """Register ``names``, what gives the names ``declaration`` holds, for every field naming it in
    `choices`."""
    _PROVIDERS[declaration] = names


def choices(field: FieldInfo) -> tuple[str, list[str]] | None:
    """The declaration ``field`` names in `choices`, and the names it holds now; None for a field
    naming none, for a declaration none is registered for, and while the declarations do not load
    — what reads them says why — or hold no name."""
    declaration = field_extras(field).get("choices")
    names = _PROVIDERS.get(declaration) if isinstance(declaration, str) else None
    if names is None:
        return None
    try:
        held = [str(name) for name in names()]
    except DefinitionError:
        return None
    return (declaration, held) if held else None


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


def help_findings(text: str, model: type[BaseModel], declared: Declared = lambda path: None,
                  manual: str | None = None) -> list[HelpFinding]:
    """Where ``text``, a template of a file ``model`` reads, breaks projects.md § 7: a key the
    schema names — a key whose name it fixes, or a table header ending in one — whose comment
    is not its help (`described`, ending, where the field states a `doc`, with ``manual``, the
    chapter of the manual the file declares); a key the schema does not allow; a table the schema
    names that is not written as its own header, or one holding such keys written inline; a key
    of a table the text writes that it neither sets nor shows commented out. A key whose name the
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
        return (described(field, manual) if field is not None else None), how != "unknown"

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
                                                f"out under its help, {described(field, manual)!r}"))
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
    with ``tables``, a table's values — never a quantity's `{value, unit}`, which is one value,
    written on its key's line (core.md § 11)."""
    if annotation is None:
        return []
    found = classes(annotation) or classes(items_of(annotation)) or (classes(values_of(annotation)) if tables else [])
    return [m for m in found if not issubclass(m, Measure)]


def _tables_within(value: Any) -> bool:
    """Whether a value, as TOML reads it, holds a table: an inline one, or a list of them."""
    return isinstance(value, dict) and bool(value) or isinstance(value, list) and any(isinstance(v, dict) for v in value)


# ---------------------------------------------------------------- the keys a file may hold
#
# A part's keys (web.md §§ 7.3, 8.3): every key its file may hold, at its path — each key its schema
# fixes, in the tables it fixes and in each entry the text names in a table whose keys the person
# chooses (`may_hold`), and each key a declaration beside the schema states (`DeclaredKey`) — each
# with the fragment of the loader's own schema at that path (`fragment`). One builder of the
# fragments, `view.Field.keys`, reads these; the help of a declared key is `help_text`'s, the one
# builder of a help, so the help beside a key and a template's comment above it are one text.

@dataclass(frozen=True)
class DeclaredKey:
    """A key a declaration beside a file's schema states (core.md § 2; web.md § 8.3) — a physics'
    formulation and each condition's kind, among the families and the kinds the formulations declare,
    and each parameter its kind lists; a step's kind; a material's property, as the property list
    states it, and its model's parameters — at its path in the text: its sentence, the units it is
    written in, the values it may take, whether it must be stated, and the manual's chapter its
    help ends with. Its help is `help_text`'s: what a template's comment above it reads, and what
    is shown beside it."""

    path: tuple[str, ...]
    sentence: str | None
    units: tuple[str, ...] = ()
    values: tuple[Any, ...] = ()
    required: bool = False
    manual: str | None = None

    @property
    def unit(self) -> str | None:
        """Its unit as its help says it: its units joined by ` or `; none for a key of no unit."""
        return " or ".join(self.units) or None

    def help(self, manual: bool = True) -> str:
        """Its help, by the one builder (`help_text`): its sentence, `, in` and its unit, `: one of`
        its values — and, with ``manual``, the manual's chapter it ends with."""
        return help_text(self.sentence, self.values, self.manual if manual else None, unit=self.unit)


def declared_by(keys: Iterable[DeclaredKey]) -> Declared:
    """The help of each key ``keys`` states, by its path, and None for every other: the `declared`
    `help_findings` reads, and a file femkit writes for the person comments with (core.md § 2)."""
    helps = {k.path: k.help() for k in keys}
    return helps.get


def written_keys(text: str | None) -> dict[tuple[str, ...], Any]:
    """Every key path ``text`` writes or shows commented out — a table's header, a key, a key inside
    an inline table — with the value it holds there as TOML reads it: a set key's, a shown one's as
    shown, none for a header. What a declaration reads its entries from — a condition's kind, a
    dataset's model, set or shown — and the entries a table of chosen keys holds (`may_hold`). None
    for no text; a text that is not TOML gives what its lines show."""
    found: dict[tuple[str, ...], Any] = {}
    if text is None:
        return found
    for e in persist.key_comments(text):
        found.setdefault(e.path, None if e.header else e.value)
    try:
        data = tomllib.loads(text, parse_float=persist.exact_number)
    except tomllib.TOMLDecodeError:
        return found

    def walk(value: Any, at: tuple[str, ...]) -> None:
        for key, inner in value.items():
            found[(*at, key)] = inner
            if isinstance(inner, dict):
                walk(inner, (*at, key))

    walk(data, ())
    return found


@dataclass(frozen=True)
class SchemaKey:
    """A key a file of a schema may hold (`may_hold`): its path, the model whose field it is, and
    that field."""

    path: tuple[str, ...]
    model: type[BaseModel]
    field: FieldInfo

    @property
    def leaf(self) -> bool:
        """Whether it holds one value — a quantity's `{value, unit}` among them — not a table of keys."""
        return not _models_within(self.field.annotation) and keys_of(self.field.annotation) is None


def may_hold(model: type[BaseModel], written: Iterable[tuple[str, ...]]) -> list[SchemaKey]:
    """Every key a file of ``model`` may hold that its schema names (web.md § 8.3), in the schema's
    order: each key it fixes, in each table it fixes, and, in a table whose keys the person chooses
    — a group's condition, a step, a material's dataset — those of each entry ``written``, the key
    paths the text writes, names there. A quantity's `{value, unit}` is one value, never a table; a
    value of several models — a dataset, a value, a table or a model — takes the keys of those its
    written keys all belong to, each key once, from the first that names it, as a key's help is read
    (`_place`); of every one, where none fits."""
    written = set(written)
    out: list[SchemaKey] = []

    def under(at: tuple[str, ...]) -> list[str]:
        return sorted({p[len(at)] for p in written if len(p) > len(at) and p[:len(at)] == at})

    def walk(annotation: Any, at: tuple[str, ...]) -> None:
        held = _models_within(annotation, tables=False)
        if held:
            keys = under(at)
            fits = [m for m in held if all(field_named(m, k) for k in keys)] or held
            seen: set[str] = set()
            for m in fits:
                for name, f in m.model_fields.items():
                    key = f.alias or name
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(SchemaKey((*at, key), m, f))
                    walk(f.annotation, (*at, key))
        elif keys_of(annotation) is not None:
            for chosen in under(at):
                walk(values_of(annotation), (*at, chosen))

    walk(model, ())
    return out


@functools.lru_cache(maxsize=None)
def _json_schema(model: type[BaseModel]) -> dict:
    """A model's JSON schema, as its loader states it: made once."""
    return model.model_json_schema()


def fragment(model: type[BaseModel], path: tuple[str, ...]) -> dict[str, Any]:
    """The JSON schema fragment of what a file of ``model`` holds at ``path`` — a request's field, a
    part's key — as the loader's own schema states it (web.md §§ 7.2, 7.3), whole: each definition
    it names carried with it. A key under a table whose keys the person chooses is that table's
    values'; one the schema leaves open — a parameter a declaration lists — what the open table
    holds; the empty fragment where the schema says nothing there. The one builder of a fragment."""
    schema = _json_schema(model)
    defs = schema.get("$defs", {})
    at: dict | None = schema
    for key in path:
        at = _step(at, key, defs)
        if at is None:
            return {}
    return {**at, "$defs": defs} if defs and "$ref" in json.dumps(at) else dict(at)


def narrowed(fragment: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    """``fragment`` holding ``names`` alone — its closed list, `enum`, on each alternative that is no
    `null`, where it may be left out: what a field may take for one subject, narrower than its
    declaration (the engines that can solve a study; web.md § 7.2). The one narrowing of a fragment."""
    held = list(names)
    alternatives = fragment.get("anyOf")
    if alternatives and any(a.get("type") == "null" for a in alternatives):
        return {**fragment, "anyOf": [a if a.get("type") == "null" else {**a, "enum": held} for a in alternatives]}
    return {**fragment, "enum": held}


def _step(at: dict, key: str, defs: dict) -> dict | None:
    """What ``at``, a JSON schema, holds under ``key``: a property, else what one of its
    alternatives holds there, else what an open table holds; None where it says nothing."""
    while "$ref" in at:
        at = defs[at["$ref"].rsplit("/", 1)[-1]]
    if key in at.get("properties", {}):
        return at["properties"][key]
    for alternative in (*at.get("anyOf", ()), *at.get("oneOf", ()), *at.get("allOf", ())):
        found = _step(alternative, key, defs)
        if found is not None:
            return found
    extra = at.get("additionalProperties")
    return extra if isinstance(extra, dict) else None
