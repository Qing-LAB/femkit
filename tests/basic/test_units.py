"""Exact quantities and the unit table (core.md § 11)."""

from __future__ import annotations

from fractions import Fraction

import pytest

from femkit.core.schema import DefinitionError, validate
from femkit.core.units import Quantity, UnitError, UnitTable, Units
from femkit.definitions.catalogue import load_units


@pytest.fixture(scope="module")
def units() -> Units:
    return Units(load_units())


LENGTH = (("length", 1),)


def test_one_length_written_several_ways_is_one_exact_value(units):
    """Fails if a number goes through a binary float, or a micro spelling reads differently:
    "500 nm" and "0.5 µm" must give one case ID (core.md § 11, models.md § 2)."""
    expected = Quantity(Fraction(1, 2_000_000), LENGTH)
    for text in ["500 nm", "0.5 µm", "0.5 μm", "0.5 um", "5e-7 m", "500nm", "0.0005 mm"]:
        assert units.parse(text) == expected, text
    assert units.parse("633 nm") == Quantity(Fraction(633, 10**9), LENGTH)  # 6.33e-07 as a float is not


@pytest.mark.parametrize("unit, base", [
    ("Hz", "1/s"),
    ("N", "kg m/s^2"),
    ("Pa", "kg/(m s^2)"),
    ("J", "kg m^2/s^2"),
    ("W", "kg m^2/s^3"),
    ("C", "A s"),
    ("V", "kg m^2/(s^3 A)"),
    ("F", "s^4 A^2/(kg m^2)"),
    ("Ω", "kg m^2/(s^3 A^2)"),
    ("ohm", "kg m^2/(s^3 A^2)"),
    ("S", "s^3 A^2/(kg m^2)"),
    ("Wb", "kg m^2/(s^2 A)"),
    ("T", "kg/(s^2 A)"),
    ("H", "kg m^2/(s^2 A^2)"),
    ("eV", "1.602176634e-19 kg m^2/s^2"),
    ("Å", "1e-10 m"),
    ("angstrom", "1e-10 m"),
    ("kg", "1000 g"),
])
def test_each_unit_in_the_table_is_what_the_si_defines(units, unit, base):
    """Fails if an entry of units.toml misstates a unit — every value written in it would be
    wrong by that factor or dimension. The right side is each unit in SI base units, as the
    SI Brochure (9th edition) states it (core.md § 11)."""
    assert units.parse(f"1 {unit}") == units.parse(f"1 {base}")


def test_an_expression_reads_left_to_right_with_juxtaposition_multiplying(units):
    """Fails if precedence, juxtaposition or a name given is read differently from core.md § 11:
    `*`, `/` and juxtaposition bind tighter than `+` and `-`, left to right."""
    gap = units.parse("500 nm")
    assert units.parse("gap / 2 + 1 nm", {"gap": gap}) == Quantity(Fraction(251, 10**9), LENGTH)
    assert units.parse("-gap + 1 um", {"gap": gap}) == Quantity(Fraction(1, 2_000_000), LENGTH)
    assert units.parse("(gap - 100 nm) * 3", {"gap": gap}) == Quantity(Fraction(12, 10**7), LENGTH)
    assert units.parse("1/2 nm") == Quantity(Fraction(1, 2 * 10**9), LENGTH)
    assert units.parse("5 W/m^2") == units.parse("5 kg/s^3")
    assert units.parse("2 mS/cm") == units.parse("0.2 S/m")
    assert units.parse("1 J/(kg K)") == units.parse("1 m^2/(s^2 K)")
    assert units.parse("1.5") == Quantity(Fraction(3, 2))


@pytest.mark.parametrize("text", [
    "1 V + 1 m",        # terms of different dimensions
    "5 nmm",            # neither a unit nor a name given
    "gap^2",            # a power on a name
    "2^3",              # a power on a number
    "(m)^2",            # a power on a group
    "1 m^0.5",          # a power that is not an integer
    "1 m / 0",          # a division by zero
    "1 − 2",            # a character outside the grammar (U+2212)
    "5 nm²",            # a superscript is not a power
    "",                 # nothing
    "5 (",              # unfinished
    "m)",               # unbalanced
])
def test_what_the_grammar_does_not_read_is_refused(units, text):
    """Fails if any text core.md § 11 refuses is read as some value instead."""
    with pytest.raises(UnitError):
        units.parse(text, {"gap": units.parse("500 nm")})


def test_a_conversion_is_exact_and_refused_across_dimensions(units):
    """Fails if a conversion rounds, answers for a unit of another dimension, or keeps a dimension
    raised to the power zero (core.md § 11)."""
    assert units.convert(units.parse("1 m"), "nm") == 10**9
    assert units.convert(units.parse("633 nm"), "µm") == Fraction(633, 1000)
    with pytest.raises(UnitError):
        units.convert(units.parse("1 V"), "m")
    assert units.parse("m^0 + 1") == units.parse("2")                      # a zero power leaves no dimension


BASE = {"dimensions": {"length": "m"}, "prefixes": {"m": -3, "k": 3},
        "units": {"m": {"dimension": "length", "prefixes": True}}}


@pytest.mark.parametrize("change, at", [
    ({"units": {"mm": {"equals": "1/1000 m", "prefixes": False}}}, "units"),           # a text two ways
    ({"units": {"x": {"equals": "-1 m", "prefixes": False}}}, "units.x"),               # not positive
    ({"units": {"y": {"equals": "1 z", "prefixes": False},
                "z": {"equals": "2 m", "prefixes": False}}}, "units.y.equals"),         # uses a unit below it
    ({"dimensions": {"length": "km"}}, "dimensions.length"),                            # canonical is not one
    ({"units": {"w": {"dimension": "width", "prefixes": False}}}, "units.w.dimension"),  # no such dimension
])
def test_a_table_that_reads_a_text_two_ways_or_states_a_wrong_unit_does_not_load(change, at):
    """Fails if a unit table loads when a text in it has two readings, a unit is not positive,
    an `equals` uses a unit below it, a canonical unit is not exactly one of its dimension, or
    a unit names no dimension (core.md § 11)."""
    data = {key: dict(BASE[key]) for key in BASE}
    for key, value in change.items():
        data[key] = {**data[key], **value}
    with pytest.raises(DefinitionError) as caught:
        validate(UnitTable, data, "units.toml")
    assert at in [path for path, _ in caught.value.problems]
