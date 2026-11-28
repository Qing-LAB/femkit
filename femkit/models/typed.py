"""One typed value (models.md § 3): a definition's and an observable's alike — the type of its
numbers and its unit, declared once here, and the one rule its unit follows.

- `type`: `int` (a whole number, a count), `float` (a 64-bit double) or `complex` (a pair of
  them);
- `unit`: a unit of femkit's table or a product of them — `nm`, `F/m`, `C^2/(N m^2)` — or `1` for a
  plain number, never left out, an `int` taking `1` alone. Its dimension is the person's promise,
  which no check reads from a value.

`unit_said` is that rule's one reading: the unit's dimension, or why it does not read — said at the
key `unit` of whichever table declares the value.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from pydantic import Field

from femkit.core.schema import Model, as_quantity
from femkit.core.units import Dimension, UnitError, Units

#: The types a typed value's numbers may be.
Type = Literal["int", "float", "complex"]
ONE = "1"   # the unit of a plain number, an `int`'s alone


class Typed(Model):
    """A typed value's declaration (models.md § 3): the type of its numbers and its unit."""

    type: Type = Field(description="the number's type: an `int` a whole number, a `float` a 64-bit double, a "
                                   "`complex` a pair of them")
    unit: str = as_quantity("its unit: a unit femkit reads, or a product of them — `nm`, `F/m`, `C^2/(N m^2)` — and "
                            "`1` for a plain number, an `int`'s alone", "unit")


class UnitSaid(NamedTuple):
    """What a typed value's unit reads as: its dimension, or why not, with the one unit that would
    be right where there is one."""

    dimension: Dimension | None
    problem: str | None = None
    right: str | None = None


def unit_said(units: Units, typed: Typed, name: str) -> UnitSaid:
    """``typed``'s unit, read by the unit table (core.md § 11): its dimension; or, said of the value
    ``name``, why it does not read, or why an `int`'s is not `1` — a count has no unit."""
    try:
        one = units.unit(typed.unit)
    except UnitError as exc:
        return UnitSaid(None, f"`{name}`'s unit does not read: {exc}")
    if typed.type == "int" and typed.unit != ONE:
        return UnitSaid(one.dimension, f"`{name}` is an `int`, a count, and its unit is `{ONE}`", ONE)
    return UnitSaid(one.dimension)
