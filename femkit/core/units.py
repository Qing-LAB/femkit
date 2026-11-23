"""Exact quantities: the unit table, one grammar, conversion (core.md § 11).

A number is read from its decimal text as an exact rational and a value is held in
its dimension's canonical unit; no binary float is ever involved.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from pydantic import Field, model_validator

from femkit.core.schema import Model, refuse


class UnitError(ValueError):
    """A text the grammar or the table does not read: names the text and what in it is wrong."""


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
        return Quantity(self.value ** power, tuple((n, p * power) for n, p in self.dimension))


# ------------------------------------------------------------------ the table

DIMENSION_NAME = re.compile(r"[a-z][a-z_]*")
SYMBOL = re.compile(r"[^\W\d]\w*")          # a unit symbol or a name: a letter or `_`, then word characters
PREFIX = re.compile(r"[^\W\d_]+")           # letters only


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
            quantity = _Parser(symbols, text, {}).parse()
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

_TOKEN = re.compile(r"""\s*(?:
      (?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)
    | (?P<name>[^\W\d]\w*)
    | (?P<op>[-+*/()^])
    )""", re.VERBOSE)
_INTEGER = re.compile(r"\d+")


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
    """expression = term {("+" | "-") term}
    term       = unary {("*" | "/") unary | atom}        -- juxtaposition multiplies
    unary      = "-" unary | atom
    atom       = number | name | symbol ["^" ["-"] integer] | "(" expression ")"
    """

    def __init__(self, symbols: Mapping[str, Quantity], text: str, names: Mapping[str, Quantity]):
        self.symbols, self.text, self.names = symbols, text, names
        self.tokens = _tokens(text)
        self.at = 0

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
        elif token.kind == "name" and token.text in self.names:
            value, end = self.names[token.text], token.end
        elif token.kind == "name":
            value = self.symbols.get(token.text)
            if value is None:
                given = f" or a name given here ({', '.join(sorted(self.names))})" if self.names else ""
                raise UnitError(f"{self.text!r}: {token.text!r} is not a unit{given}")
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

    def symbols(self) -> list[str]:
        """Every symbol read, prefixed ones included."""
        return sorted(self._symbols)

    def parse(self, text: str, names: Mapping[str, Quantity] = {}) -> Quantity:
        """A quantity, a unit or an expression of the names given, exactly."""
        return _Parser(self._symbols, text, names).parse()

    def convert(self, quantity: Quantity, unit: str) -> Fraction:
        """The quantity's value in ``unit``; refused when the unit measures another dimension."""
        one = self.parse(unit)
        if one.dimension != quantity.dimension:
            raise UnitError(f"a value of dimension {_show(quantity.dimension)} is not in {unit!r}, "
                            f"of dimension {_show(one.dimension)}")
        return quantity.value / one.value


def _show(dimension: Dimension) -> str:
    return " ".join(n if p == 1 else f"{n}^{p}" for n, p in dimension) or "none (a plain number)"
