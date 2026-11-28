"""Exact quantities: the unit table, one grammar of units, the one quantity form read, conversion
(core.md § 11).

A value is written in one form — `{value, unit}`, a plain number where it has no unit, or, where a
field may cite one, a definition's name, alone or in place of any number of a `{value, unit}` —
its number read from its decimal text as an exact rational; it is held in its dimension's
canonical unit, and no binary float is ever involved. The grammar reads a unit, and nothing else:
no quantity and no expression is read from a text.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable

from pydantic import Field, model_validator

from femkit.core import persist
from femkit.core.schema import Measure, Model, meant, nearest, refuse


class UnitError(ValueError):
    """A value or a unit not read: names what is written and what in it is wrong — and, where one
    value would be right, that value, a plain one, as the file would hold it (`right`)."""

    def __init__(self, message: str, right: Any = None):
        super().__init__(message)
        self.right = right


Dimension = tuple[tuple[str, int], ...]


def _combine(a: Dimension, b: Dimension, sign: int) -> Dimension:
    powers: dict[str, int] = dict(a)
    for name, power in b:
        powers[name] = powers.get(name, 0) + sign * power
    return tuple(sorted((n, p) for n, p in powers.items() if p))


@dataclass(frozen=True)
class Quantity:
    value: Fraction
    dimension: Dimension = ()

    def __mul__(self, other: Quantity) -> Quantity:
        return Quantity(self.value * other.value, _combine(self.dimension, other.dimension, 1))

    def __truediv__(self, other: Quantity) -> Quantity:
        return Quantity(self.value / other.value, _combine(self.dimension, other.dimension, -1))

    def __pow__(self, power: int) -> Quantity:
        return Quantity(self.value ** power, tuple((n, p * power) for n, p in self.dimension if p * power))  # m^0: none


# ------------------------------------------------------------------ the table

DIMENSION_NAME = re.compile(r"[a-z][a-z_]*")
SYMBOL = re.compile(r"[^\W\d]\w*")          # a unit symbol or a name: a letter or `_`, then word characters
PREFIX = re.compile(r"[^\W\d_]+")           # letters only

#: The letter a memory amount's number is written with — a job request's `memory` (jobs.md § 2), and
#: a scheduler's answer, as SLURM writes one (jobs.md § 9.1) — each the binary multiple of the byte
#: the unit table names (`femkit/data/units.toml`), through which the amount is read and converted. A
#: scheduler's reader takes it from here, the one module of femkit's it may read a quantity by
#: (framework.md § 1).
MEMORY_LETTERS = {"K": "KiB", "M": "MiB", "G": "GiB", "T": "TiB", "P": "PiB"}


class UnitEntry(Model):
    """One unit: a base dimension times an exact factor, or an expression of units above it."""

    dimension: str | None = Field(None, description="the base dimension this unit measures, when it is "
                                  "defined by one; with `factor`")
    factor: str = Field("1", description="with `dimension`: how many of the dimension's canonical unit one "
                        "of this unit is, an exact number (`1/1000`)")
    equals: str | None = Field(None, description="otherwise: what one of this unit is, an expression of "
                               "units above it (`W/A`, `1.602176634e-19 J`)")
    prefixes: bool = Field(description="whether SI prefixes apply to it (`nm`, `kV`)")

    @model_validator(mode="after")
    def _one_definition(self) -> UnitEntry:
        if (self.dimension is None) == (self.equals is None):
            raise ValueError("give either `dimension` or `equals`")
        if self.equals is not None and "factor" in self.model_fields_set:
            raise ValueError("`factor` goes with `dimension`; an `equals` states its own")
        return self


class UnitTable(Model):
    """The units a value may be written in (`femkit/data/units.toml`)."""

    dimensions: dict[str, str] = Field(description="each base dimension and its canonical unit, as written; "
                                       "every value of the dimension is held in it")
    prefixes: dict[str, int] = Field(description="each SI prefix and its power of ten")
    units: dict[str, UnitEntry] = Field(description="each unit symbol, in order: an `equals` may use only "
                                        "the units above it")

    @model_validator(mode="after")
    def _reads_one_way(self) -> UnitTable:
        refuse("UnitTable", _build(self)[1])
        return self


def _build(table: UnitTable) -> tuple[dict[str, Quantity], list[tuple[tuple, str]]]:
    """Every symbol the table reads, prefixed ones included, and every problem with the table."""
    problems: list[tuple[tuple, str]] = []
    symbols: dict[str, Quantity] = {}
    readings: dict[str, list[str]] = defaultdict(list)

    for name in table.dimensions:
        if not DIMENSION_NAME.fullmatch(name):
            problems.append((("dimensions", name), "a dimension's name is lower-case letters and `_`"))
    for prefix, power in table.prefixes.items():
        if not PREFIX.fullmatch(prefix) or power == 0:
            problems.append((("prefixes", prefix), "a prefix is letters, with a power of ten other than 0"))

    for symbol, entry in table.units.items():
        if not SYMBOL.fullmatch(symbol):
            problems.append((("units", symbol), "not a symbol the grammar reads: a letter, then letters, digits or `_`"))
            continue
        if entry.dimension is not None and entry.dimension not in table.dimensions:
            problems.append((("units", symbol, "dimension"),
                             f"{entry.dimension!r} is not a dimension (the dimensions: {', '.join(table.dimensions)})"))
            continue
        field, text = ("factor", entry.factor) if entry.dimension is not None else ("equals", entry.equals)
        try:
            quantity = _Parser(symbols, text).parse()
        except UnitError as exc:
            problems.append((("units", symbol, field), str(exc)))
            continue
        if entry.dimension is not None:
            if quantity.dimension:
                problems.append((("units", symbol, "factor"), f"{entry.factor!r} is not a plain number"))
                continue
            quantity = Quantity(quantity.value, ((entry.dimension, 1),))
        if quantity.value <= 0:
            problems.append((("units", symbol), "a unit is positive"))
            continue
        readings[symbol].append(f"the unit {symbol!r}")
        symbols.setdefault(symbol, quantity)
        if entry.prefixes:
            for prefix, power in table.prefixes.items():
                readings[prefix + symbol].append(f"{prefix!r} with {symbol!r}")
                symbols.setdefault(prefix + symbol, Quantity(quantity.value * Fraction(10) ** power, quantity.dimension))

    for text, ways in readings.items():
        if len(ways) > 1:
            problems.append((("units",), f"{text!r} reads two ways: {' and '.join(ways)}"))
    for name, canonical in table.dimensions.items():
        if symbols.get(canonical) != Quantity(Fraction(1), ((name, 1),)):
            problems.append((("dimensions", name), f"its canonical unit {canonical!r} is not exactly one {name}"))
    return symbols, problems


# ---------------------------------------------------------------- the grammar

NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"   # a decimal number, as the grammar reads one
_TOKEN = re.compile(rf"""\s*(?:
      (?P<number>{NUMBER})
    | (?P<name>[^\W\d]\w*)
    | (?P<op>[-+*/()^])
    )""", re.VERBOSE)
_INTEGER = re.compile(r"\d+")
_SIGNED = re.compile(rf"[-+]?{NUMBER}")


def decimal(value: Fraction) -> str:
    """``value`` for a person, still exact: its decimal where it has one — `1/40` is `0.025` —
    else `p/q`, as `1/3`; the inverse of `number` where the decimal exists."""
    return persist.number_text(Fraction(value)) or str(value)


def number(text: str) -> Fraction:
    """A decimal number alone, a sign before it where it has one — `-0.25`, `1.602176634e-19` —
    read exactly, never through a binary float: a cell of a material's table (materials.md § 3),
    a number a source's file writes as text (§ 7); a `UnitError` naming the text for anything
    else, a unit or an expression among it."""
    if not _SIGNED.fullmatch(text):
        raise UnitError(f"{text!r} is no decimal number")
    return Fraction(text)


@dataclass(frozen=True)
class _Token:
    kind: str           # number | name | op
    text: str
    start: int
    end: int


def _tokens(text: str) -> list[_Token]:
    out, at = [], 0
    while at < len(text):
        if text[at:].strip() == "":
            break
        match = _TOKEN.match(text, at)
        if not match or match.lastgroup is None:
            bad = text[at:].lstrip()[0]
            raise UnitError(f"{text!r}: {bad!r} is not part of a quantity")
        kind = match.lastgroup
        out.append(_Token(kind, match.group(kind), match.start(kind), match.end(kind)))
        at = match.end()
    return out


class _Parser:
    """What a unit is, as the table and a unit's text write it:

    expression = term {("+" | "-") term}
    term       = unary {("*" | "/") unary | atom}        -- juxtaposition multiplies
    unary      = "-" unary | atom
    atom       = number | symbol ["^" ["-"] integer] | "(" expression ")"

    A unit's text (`Units.unit`) takes no number but a power's and the `1` of a plain number, and
    no sum; the table's own `factor` and `equals` take numbers (`1.602176634e-19 J`)."""

    def __init__(self, symbols: Mapping[str, Quantity], text: str):
        self.symbols, self.text = symbols, text
        self.tokens = _tokens(text)
        self.at = 0

    def unknown(self, name: str) -> UnitError:
        """A symbol that is no unit, with the unit it most likely means."""
        return UnitError(f"`{name}` is not a unit" + meant(name, self.symbols))

    def parse(self) -> Quantity:
        if not self.tokens:
            raise UnitError(f"{self.text!r} holds no quantity")
        value, _, _ = self.expression()
        if self.at < len(self.tokens):
            raise UnitError(f"{self.text!r}: {self.tokens[self.at].text!r} does not follow")
        return value

    def _peek(self) -> _Token | None:
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def _take(self) -> _Token:
        token = self._peek()
        if token is None:
            raise UnitError(f"{self.text!r} ends too early")
        self.at += 1
        return token

    def _is(self, *ops: str) -> bool:
        token = self._peek()
        return token is not None and token.kind == "op" and token.text in ops

    def expression(self) -> tuple[Quantity, int, int]:
        left, start, end = self.term()
        while self._is("+", "-"):
            op = self._take().text
            right, right_start, right_end = self.term()
            if left.dimension != right.dimension:
                raise UnitError(f"{self.text!r}: {self.text[start:end]!r} and "
                                f"{self.text[right_start:right_end]!r} have different dimensions")
            left = Quantity(left.value + right.value if op == "+" else left.value - right.value, left.dimension)
            end = right_end
        return left, start, end

    def term(self) -> tuple[Quantity, int, int]:
        left, start, end = self.unary()
        while True:
            token = self._peek()
            if self._is("*", "/"):
                op = self._take().text
                right, _, end = self.unary()
            elif token is not None and (token.kind != "op" or token.text == "("):
                op = "*"
                right, _, end = self.atom()
            else:
                return left, start, end
            if op == "/" and right.value == 0:
                raise UnitError(f"{self.text!r} divides by zero")
            left = left * right if op == "*" else left / right

    def unary(self) -> tuple[Quantity, int, int]:
        if self._is("-"):
            start = self._take().start
            value, _, end = self.unary()
            return Quantity(-value.value, value.dimension), start, end
        return self.atom()

    def atom(self) -> tuple[Quantity, int, int]:
        token = self._take()
        if token.kind == "number":
            value, end = Quantity(Fraction(token.text)), token.end
        elif token.kind == "name":
            value = self.symbols.get(token.text)
            if value is None:
                raise self.unknown(token.text)
            if not self._is("^"):
                return value, token.start, token.end
            self._take()
            sign = 1
            if self._is("-"):
                self._take()
                sign = -1
            power = self._take()
            if power.kind != "number" or not _INTEGER.fullmatch(power.text):
                raise UnitError(f"{self.text!r}: a power is an integer, not {power.text!r}")
            return value ** (sign * int(power.text)), token.start, power.end
        elif token.text == "(":
            value, _, _ = self.expression()
            close = self._take()
            if close.text != ")":
                raise UnitError(f"{self.text!r}: {close.text!r} where ')' closes")
            end = close.end
        else:
            raise UnitError(f"{self.text!r}: {token.text!r} where a value belongs")
        if self._is("^"):
            raise UnitError(f"{self.text!r}: a power applies to a unit symbol only, not {self.text[token.start:end]!r}")
        return value, token.start, end


class Units:
    """The unit table, read: every symbol it holds, each prefixed form included."""

    def __init__(self, table: UnitTable):
        self._symbols = _build(table)[0]    # the table validated itself when it loaded
        self._canonical = {((name, 1),): symbol for name, symbol in table.dimensions.items()}
        self._of: dict[Dimension, list[str]] = {}

    def canonical(self, dimension: Dimension) -> str | None:
        """The canonical unit of a base dimension, as the table writes it: `m` for a length."""
        return self._canonical.get(dimension)

    def of(self, dimension: Dimension) -> list[str]:
        """Every symbol of ``dimension``, prefixed ones included: what a quantity of it may be
        written in."""
        if dimension not in self._of:  # the table never changes: each dimension is read once
            self._of[dimension] = sorted(s for s, q in self._symbols.items() if q.dimension == dimension)
        return list(self._of[dimension])

    def unit(self, text: str) -> Quantity:
        """A unit alone — one of the table, or a product of them, `1` for a plain number (`nm`,
        `F/m`, `C^2/(N m^2)`, `1/s`): what one of it is, exactly. A `UnitError` naming the text
        for any other: one that does not read, or a number in it but a power's and the `1` of a
        plain number or of `1/s`, or a sum — the one reading of a unit (core.md § 11)."""
        if not isinstance(text, str):
            raise UnitError(f"{_written(text)} is no unit: a unit is a text, in quotes")
        found = _Parser(self._symbols, text).parse()
        tokens = _tokens(text)
        for i, token in enumerate(tokens):
            power = i > 0 and tokens[i - 1].text == "^" or i > 1 and tokens[i - 2].text == "^" and \
                tokens[i - 1].text == "-"
            one = token.text == "1" and i == 0 and (len(tokens) == 1 or tokens[1].text == "/")
            if token.kind == "number" and not (power or one):
                raise UnitError(f"{text!r} is no unit: it holds the number {token.text}, and a unit is one of the "
                                "table's or a product of them, `1` for a plain number")
            if token.kind == "op" and token.text in "+-" and not (token.text == "-" and i > 0
                                                                    and tokens[i - 1].text == "^"):
                raise UnitError(f"{text!r} is no unit: a unit is one of the table's or a product of them, never a "
                                "sum")
        return found

    def shown(self, quantity: Quantity, display: Iterable[str] = ()) -> str:
        """``quantity`` as a person reads it — the one formatter wherever a value is shown (core.md
        § 11; models.md § 5): in the first unit of ``display``, a study's display units, that
        measures its dimension, else in its canonical unit — SI, an angle in degrees — exactly: its
        decimal where it has one, else `p/q` (`decimal`); a plain number bare. A display unit the
        table does not read is passed by: the study's check says so."""
        for unit in display:
            try:
                one = self.unit(unit)
            except UnitError:
                continue
            if one.dimension == quantity.dimension:
                return decimal(quantity.value / one.value) + ("" if unit == "1" else f" {unit}")
        return f"{decimal(quantity.value)} {self.si(quantity.dimension)}" if quantity.dimension else \
            decimal(quantity.value)

    def si(self, dimension: Dimension) -> str:
        """The SI unit of ``dimension`` as text — each base dimension's canonical unit with its
        power, `kg^-1 m^-3 s^4 A^2`; `1` for a plain number (core.md § 11)."""
        return " ".join((self.canonical(((n, 1),)) or n) + ("" if p == 1 else f"^{p}") for n, p in dimension) or "1"

    def convert(self, quantity: Quantity, unit: str) -> Fraction:
        """The quantity's value in ``unit``; refused when the unit measures another dimension."""
        one = self.unit(unit)
        if one.dimension != quantity.dimension:
            raise UnitError(f"a value of dimension {_show(quantity.dimension)} is not in {unit!r}, "
                            f"of dimension {_show(one.dimension)}")
        return quantity.value / one.value

    def measure(self, written: Any, names: Mapping[str, Quantity] | None = None) -> Any:
        """A value written in the one quantity form, exactly (core.md § 11): `{value, unit}`, its
        number times one of its unit — each of its numbers, for a range, as a
        list of quantities; a plain number as itself, of no dimension; and, where ``names`` is
        given — the definitions a field of a kind that may cite one may name, each with its value —
        a definition's name, as its value, alone or in place of any number of a `{value, unit}`,
        where the unit states the other numbers and each definition its own. The one reader of
        every field written as a quantity.

        A `UnitError` otherwise, saying what is written and what would be right: a unit that does
        not read; a text naming no definition given, or where none may stand — never read as a
        quantity, but where it reads as a number and a unit, the table to write as its `right`
        value, and, among a `{value, unit}`'s numbers, the whole table with a name put right; a
        binary float — TOML's `inf` or `nan` — a truth value, a list, a table of other keys."""
        if isinstance(written, Measure):
            one = self.unit(written.unit)

            def each(value: Any) -> Any:
                if isinstance(value, list):
                    return [each(v) for v in value]
                if isinstance(value, str):
                    return self._named(value, names, within=written)
                return Quantity(Fraction(self._number(value))) * one
            return each(written.value)
        if isinstance(written, str):
            return self._named(written, names)
        return Quantity(Fraction(self._number(written)))

    def _named(self, text: str, names: Mapping[str, Quantity] | None, within: Measure | None = None) -> Quantity:
        """The value of the definition ``text`` names, among ``names``; a `UnitError` saying why it
        is no value here — and, ``within`` a `{value, unit}`, what would be right, the whole table
        with the name put right."""
        if names is not None and text in names:
            return names[text]
        if within is None:
            raise self._text(text, names)
        wrong = self._text(text, names, among=True)
        right = None
        if isinstance(wrong.right, str):

            def put(value: Any) -> Any:
                return [put(v) for v in value] if isinstance(value, list) else wrong.right if value == text else value
            right = {"value": put(within.value), "unit": within.unit}
        raise UnitError(str(wrong), right=right)

    def _number(self, value: Any) -> Fraction | int | Decimal:
        """A number as a file writes it, or as femkit computed it: a whole number, a decimal read
        exactly from its text, an exact rational."""
        if isinstance(value, bool) or not isinstance(value, (int, Fraction, Decimal)) or \
                isinstance(value, Decimal) and not value.is_finite():
            raise UnitError(f"{_written(value)} is no number"
                            + (", and a number is finite" if isinstance(value, float) else
                               ": write a number, or `{value = <number>, unit = \"<unit>\"}`"))
        return value

    def _text(self, text: str, names: Mapping[str, Quantity] | None, among: bool = False) -> UnitError:
        """Why a text is no value here — ``among`` the numbers of a `{value, unit}` or alone: no
        definition of that name, or none may stand here; never a quantity read from it — and,
        alone, the table it would be where it reads as a number and a unit."""
        head, _, unit = text.strip().partition(" ")
        try:
            value = number(head)
            right: Any = value if not unit.strip() or self.unit(unit.strip()) == Quantity(Fraction(1)) \
                else {"value": value, "unit": unit.strip()}
        except UnitError:
            right = None
        if right is not None and among:
            return UnitError(f"{_written(text)} among the numbers of `value` is a text, and a quantity is never "
                             "written as one: each is a number, in its `unit`")
        if right is not None:
            return UnitError(f"{_written(text)} is a text, and a quantity is never written as one: write "
                             f"{_written(right)}", right=right)
        if names is None and among:
            return UnitError(f"{_written(text)} among the numbers of `value` is a text, and each is a number, in its "
                             "`unit`: no definition's name stands here")
        if names is None:
            return UnitError(f"{_written(text)} is a text, and a quantity here is written as `{{value = <number>, "
                             'unit = "<unit>"}`, a plain number where it has no unit: it names no definition')
        if not text.isidentifier():
            return UnitError(f"{_written(text)} is a text that names no definition, and no expression is read: a "
                             "value computed from others is a definition its function in definitions.py computes")
        return UnitError(f"the project defines no `{text}`" + meant(text, names), right=nearest(text, names))


def _written(value: Any) -> str:
    """A value as its file writes it, for a sentence."""
    try:
        return persist.inline_text(value)
    except (TypeError, ValueError):
        return repr(value)


def _show(dimension: Dimension) -> str:
    return " ".join(n if p == 1 else f"{n}^{p}" for n, p in dimension) or "none (a plain number)"
