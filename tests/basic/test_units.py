"""Exact quantities, the one quantity form and the unit table (core.md §§ 2, 4, 11)."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from femkit.core import persist
from femkit.core.schema import DefinitionError, Measure, Measured, Model, Number, NumberOrName, load_text, validate
from femkit.core.units import Quantity, UnitError, UnitTable, Units
from femkit.definitions.catalogue import load_units


@pytest.fixture(scope="module")
def units() -> Units:
    return Units(load_units())


LENGTH = (("length", 1),)


class Written(Model):
    """A file of the test's own, written in the one quantity form."""

    size: Measured
    plain: Number
    point: Measure[list[Number]]


def test_a_toml_number_is_read_exactly_from_the_text_written():
    """Fails if a TOML number reaches a declared file's model through a binary float — `0.1` must
    be 1/10, `1e-9` one billionth, `633e-9` 633 billionths — whichever file it is, a definition
    of femkit's as a person's part, or if a text, a truth value or TOML's `inf` is taken for a
    number (core.md § 11, "Exact": "a TOML number by the text the person wrote, which `persist`
    keeps"; § 2, "One TOML reader")."""
    held = load_text('size = { value = 633e-9, unit = "m" }\nplain = 0.1\npoint = { value = [1e-9, 1_000.5], '
                     'unit = "m" }\n', Written, "written.toml")
    assert (held.size.value, held.size.unit) == (Fraction(633, 10 ** 9), "m")
    assert held.plain == Fraction(1, 10) and held.point.value == [Fraction(1, 10 ** 9), Fraction(2001, 2)]
    assert persist.exact_number("0.1") == Fraction(1, 10)
    for wrong in ('"0.1"', "true", "inf"):
        with pytest.raises(DefinitionError) as caught:
            load_text(f'size = 1\nplain = {wrong}\npoint = {{ value = [1], unit = "m" }}\n', Written, "written.toml")
        assert [p.path for p in caught.value.problems] == ["plain"]
        assert "instance" not in caught.value.problems[0].reason    # never pydantic's own words


def test_one_quantity_is_one_exact_value_however_its_unit_is_written(units):
    """Fails if a quantity in the one form — `{value, unit}` — goes through a binary float, or a
    micro spelling reads differently: 500 nm and 0.5 µm must give one case ID (core.md § 11,
    models.md § 2)."""
    expected = Quantity(Fraction(1, 2_000_000), LENGTH)
    for value, unit in [("500", "nm"), ("0.5", "µm"), ("0.5", "μm"), ("0.5", "um"), ("5e-7", "m"), ("0.0005", "mm")]:
        written = Measure[Number](value=Decimal(value), unit=unit)
        assert units.measure(written) == expected, (value, unit)
    assert units.measure(Measure[Number](value=633, unit="nm")) == Quantity(Fraction(633, 10**9), LENGTH)
    assert units.measure(Fraction(3, 2)) == Quantity(Fraction(3, 2))                     # a plain number
    assert units.measure(Measure[list[Number]](value=[0, Decimal("0.5")], unit="mm")) == [
        Quantity(Fraction(0), LENGTH), Quantity(Fraction(1, 2000), LENGTH)]               # a point, under one unit


@pytest.mark.parametrize("written, right", [
    ("0.1 m", '{value = 0.1, unit = "m"}'),          # a quantity written as text: the table to write
    ("4", "4"),                                       # a plain number written as text
    ("gap / 2", None),                                # an expression: never read
    ("500nm", None),
])
def test_a_text_is_never_read_as_a_quantity_and_says_the_table_to_write(units, written, right):
    """Fails if a text where a quantity belongs is read as one — the expression grammar retired — or
    if its error does not name the table to write where the text reads as a number and a unit
    (core.md § 11: "No quantity is written as a text, no expression anywhere but a function in
    `definitions.py`; a text where a quantity belongs is a finding saying the table to write")."""
    with pytest.raises(UnitError) as caught:
        units.measure(written)
    assert (caught.value.right if right is None else persist.inline_text(caught.value.right)) == right


def test_a_definitions_name_is_read_only_where_a_definition_may_stand(units):
    """Fails if a definition's name is read where the field's kind cites none — a material's — or
    is not read as the definition's value where one may stand (core.md § 11: "or, where the
    field may cite one, a definition's name")."""
    gap = Quantity(Fraction(1, 10 ** 8), LENGTH)
    assert units.measure("gap", {"gap": gap}) == gap
    with pytest.raises(UnitError):
        units.measure("gap")
    with pytest.raises(UnitError):
        units.measure("gap", {"gip": gap})


def test_a_number_of_a_points_value_may_be_a_definitions_name_read_as_its_own_value(units):
    """Fails if a definition's name among a point's or a line's numbers is not read as that
    definition's value — the unit stating the other numbers, each definition its own — if it is
    read where the field cites none, or if one the project does not define is not refused with the
    whole value, the name put right, as what would be right (core.md § 11: "where it may, any
    number in `value` may be a definition's name instead ..., the unit stating the numbers, each
    definition its own, so a point follows a swept definition")."""
    interface = Quantity(Fraction(1, 4), LENGTH)
    point = Measure[list[NumberOrName]](value=["interface", Decimal("500")], unit="mm")
    assert units.measure(point, {"interface": interface}) == [interface, Quantity(Fraction(1, 2), LENGTH)]
    line = Measure[list[list[NumberOrName]]](value=[[0, "interface"], ["interface", 1]], unit="m")
    assert units.measure(line, {"interface": interface}) == [[Quantity(Fraction(0), LENGTH), interface],
                                                             [interface, Quantity(Fraction(1), LENGTH)]]
    with pytest.raises(UnitError):
        units.measure(point)                                      # a field that cites none: a material's range
    with pytest.raises(UnitError) as caught:
        units.measure(point, {"interfaces": interface})
    assert persist.inline_text(caught.value.right) == '{value = ["interfaces", 500], unit = "mm"}'


@pytest.mark.parametrize("unit, factor, base", [
    ("Hz", 1, "1/s"),
    ("N", 1, "kg m/s^2"),
    ("Pa", 1, "kg/(m s^2)"),
    ("J", 1, "kg m^2/s^2"),
    ("W", 1, "kg m^2/s^3"),
    ("C", 1, "A s"),
    ("V", 1, "kg m^2/(s^3 A)"),
    ("F", 1, "s^4 A^2/(kg m^2)"),
    ("Ω", 1, "kg m^2/(s^3 A^2)"),
    ("ohm", 1, "kg m^2/(s^3 A^2)"),
    ("S", 1, "s^3 A^2/(kg m^2)"),
    ("Wb", 1, "kg m^2/(s^2 A)"),
    ("T", 1, "kg/(s^2 A)"),
    ("H", 1, "kg m^2/(s^2 A^2)"),
    ("eV", "1.602176634e-19", "kg m^2/s^2"),
    ("Å", "1e-10", "m"),
    ("angstrom", "1e-10", "m"),
    ("kg", 1000, "g"),
])
def test_each_unit_in_the_table_is_what_the_si_defines(units, unit, factor, base):
    """Fails if an entry of units.toml misstates a unit — every value written in it would be
    wrong by that factor or dimension. The right side is each unit in SI base units, as the
    SI Brochure (9th edition) states it (core.md § 11)."""
    one, of = units.unit(unit), units.unit(base)
    assert (one.value, one.dimension) == (Fraction(factor) * of.value, of.dimension)


def test_a_unit_reads_as_a_product_left_to_right(units):
    """Fails if a unit is read otherwise than core.md § 11 says: `*`, `/` and juxtaposition, left
    to right, parentheses, `^` with an integer on a symbol; `1` for a plain number."""
    assert units.unit("W/m^2") == units.unit("kg/s^3")
    assert units.unit("mS/cm") == Quantity(Fraction(1, 10) * units.unit("S/m").value, units.unit("S/m").dimension)
    assert units.unit("J/(kg K)") == units.unit("m^2/(s^2 K)")
    assert units.unit("1") == Quantity(Fraction(1)) and units.unit("1/s") == units.unit("Hz")
    assert units.unit("um^2") == Quantity(Fraction(1, 10 ** 12), (("length", 2),))


@pytest.mark.parametrize("text", [
    "V + m",            # a sum
    "nmm",              # no unit
    "2^3",              # a power on a number
    "(m)^2",            # a power on a group
    "m^0.5",            # a power that is not an integer
    "500 nm",           # a number in a unit: a quantity written as text
    "1 − 2",            # a character outside the grammar (U+2212)
    "nm²",              # a superscript is not a power
    "",                 # nothing
    "m (",              # unfinished
    "m)",               # unbalanced
])
def test_what_the_grammar_does_not_read_as_a_unit_is_refused(units, text):
    """Fails if any text core.md § 11 does not read as a unit is read as one: the grammar reads a
    unit, and nothing else."""
    with pytest.raises(UnitError):
        units.unit(text)


def test_a_conversion_is_exact_and_refused_across_dimensions(units):
    """Fails if a conversion rounds, answers for a unit of another dimension, or keeps a dimension
    raised to the power zero (core.md § 11)."""
    assert units.convert(units.unit("m"), "nm") == 10**9
    assert units.convert(units.measure(Measure[Number](value=633, unit="nm")), "µm") == Fraction(633, 1000)
    with pytest.raises(UnitError):
        units.convert(units.unit("V"), "m")
    assert units.unit("m^0") == units.unit("1")                      # a zero power leaves no dimension


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


@pytest.mark.parametrize("value, shown", [(Fraction(1, 40), "0.025"), (Fraction(-3, 2), "-1.5"), (Fraction(5), "5"),
                                          (Fraction(-1, 40), "-0.025"), (Fraction(1, 10**6), "0.000001"),
                                          (Fraction(1, 3), "1/3"), (Fraction(-2, 7), "-2/7")])
def test_a_value_is_shown_as_its_exact_decimal_where_it_has_one(value, shown):
    """Fails if a value a case holds is shown other than exactly — its decimal where its
    denominator has no prime but 2 and 5, else `p/q` — or its decimal does not read back as the
    same value (core.md § 11: every operation keeps a value exact)."""
    from femkit.core.units import decimal, number
    assert decimal(value) == shown
    if "/" not in shown:
        assert number(shown) == value
        assert persist.exact_number(shown) == value and persist.inline_text(value) == shown


def test_a_value_is_shown_in_the_first_display_unit_of_its_dimension_else_its_canonical_one():
    """Fails if a value shown to a person is not in the first of a study's display units that
    measures its dimension — or, with none, in its canonical unit, exactly — or a plain number is
    given a unit (core.md § 11: "A value is shown to a person only by a surface: in a study's display
    units, else in its canonical unit"; models.md § 5, `display`)."""
    units = Units(load_units())
    gap = Quantity(Fraction(5, 10**9), (("length", 1),))
    assert units.shown(gap, ["V", "nm", "um"]) == "5 nm"
    assert units.shown(gap) == units.shown(gap, ["V"]) == "0.000000005 m"
    assert units.shown(Quantity(Fraction(3, 2)), ["nm"]) == "1.5"
