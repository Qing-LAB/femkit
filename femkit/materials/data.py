"""A property's data at one value of its variable (materials.md § 6; what each step means is
docs/science/material-data.md): a spectral position stated as the variable a dataset is written
in, a table interpolated, a dispersion model evaluated, an equivalent form converted to the
property a formulation reads, complex data stated in the physics' convention and held to the
passive sign, and the range checked — each a function of a dataset and the variable's value,
and `taken` all of them in order. Every number is exact: a rational, and a complex number an
exact pair of rationals, `Complex`; no binary float enters anywhere. No case calls these until a
step supplies a variable — the `frequency` kind (plan § 4, M9).

`taken` trusts nothing `project check` found: it applies the material's own rules,
`material.faults`, and refuses the first a dataset breaks, with the code its finding carries —
`not-stated` as `Unstated` (core.md § 9), each other as `Refused` — then its own. Each refusal
has its code and the subject it is about, the dataset's address as its caller names it:
- each code of `material.faults` (`bad-quantity`, `wrong-dimension`, `wrong-sign`, `bad-table`,
  `active`, `digest-differs`, `no-such-variable`, `outside-table`, `range-reversed`,
  `no-such-model`, `parameter-missing`, `no-such-parameter`, `wrong-convention`, `not-stated`);
- `no-such-property`: a dataset held under a property the list lacks (materials.md § 1);
- `missing-file`: a table taken without its file;
- `dataset-varies`: a table, a model, or a value whose range is not `all`, taken where the step
  supplies no variable (§ 6; material-data.md § 7);
- `not-a-form`: a value in none of the forms of the variable a dataset is written in;
- `out-of-range`: a value outside a dataset's range, or beyond a table's first and last rows,
  which is never extrapolated (material-data.md § 5);
- `no-formula`: a model femkit's list declares and femkit has no formula for — a defect a basic
  test holds the list and `FORMULAS` against (materials.md § 2);
- `no-value`: a value at which a formula divides by zero, as a model does at its pole;
- `no-conversion`: a dataset held under a property that is no equivalent form of the one read;
- `not-real`: complex data where real data is read;
- `active`: a passive material whose loss, in the physics' convention, has the sign of one that
  gives energy, naming its source's convention (material-data.md § 2).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any, Callable, Mapping

from femkit.core.errors import Refused, Unstated
from femkit.core.units import Quantity, UnitError, Units, decimal
from femkit.definitions.dispersion import REAL, Convention, Dispersion, active
from femkit.definitions.properties import Property
from femkit.materials.material import (Fault, Modelled, Rows, Span, Table, Value, bounds, faults, measured, model_of,
                                       parameters, rows, spoken)


@dataclass(frozen=True)
class Complex:
    """An exact complex number: its real and imaginary parts, each a rational."""

    re: Fraction
    im: Fraction = Fraction(0)

    @staticmethod
    def of(value: Any) -> "Complex":
        """``value`` as a `Complex`: a rational, a whole number or a decimal as itself. A binary
        float is never taken — it is not exact (core.md § 11) — nor anything else: a `TypeError`."""
        if isinstance(value, Complex):
            return value
        if isinstance(value, bool) or not isinstance(value, (int, Fraction, Decimal)):
            raise TypeError(f"{value!r} is no exact number: a binary float, or anything but a rational, is never taken")
        return Complex(Fraction(value))

    def __add__(self, other: Any) -> "Complex":
        o = Complex.of(other)
        return Complex(self.re + o.re, self.im + o.im)

    __radd__ = __add__

    def __neg__(self) -> "Complex":
        return Complex(-self.re, -self.im)

    def __sub__(self, other: Any) -> "Complex":
        return self + -Complex.of(other)

    def __rsub__(self, other: Any) -> "Complex":
        return Complex.of(other) - self

    def __mul__(self, other: Any) -> "Complex":
        o = Complex.of(other)
        return Complex(self.re * o.re - self.im * o.im, self.re * o.im + self.im * o.re)

    __rmul__ = __mul__

    def __truediv__(self, other: Any) -> "Complex":
        o = Complex.of(other)
        size = o.re * o.re + o.im * o.im
        if size == 0:
            raise ZeroDivisionError("division by zero")
        return Complex((self.re * o.re + self.im * o.im) / size, (self.im * o.re - self.re * o.im) / size)

    def __rtruediv__(self, other: Any) -> "Complex":
        return Complex.of(other) / self

    def conjugate(self) -> "Complex":
        return Complex(self.re, -self.im)


def _refused(fault: Fault, subject: str) -> Refused | Unstated:
    """A dataset's fault as a case refuses it (core.md § 9): what it does not state, `Unstated`;
    anything else, `Refused` — each with the fault's code, about ``subject``."""
    kind = Unstated if fault.code == "not-stated" else Refused
    return kind(fault.message, code=fault.code, subject=subject)


# ------------------------------------------------------------------ the variable

def stated_as(value: Quantity, variable: str, dispersion: Dispersion, units: Units, *, subject: str) -> Quantity:
    """``value`` — a value of ``variable`` in any of its forms, told by its dimension — stated as
    ``variable``, exactly: a spectral position converted among the wavelength, the frequency and
    the photon energy by the exact c0, h and e (material-data.md § 4); any other value as it is.
    Refused, `not-a-form`, for a value in none of its forms, or of a variable the list lacks;
    `no-value`, for a spectral position of zero."""
    if variable not in dispersion.variables:
        raise Refused(f"`{variable}` is none of the variables: {', '.join(dispersion.variables)}", code="not-a-form",
                      subject=subject)
    try:
        found = dispersion.stated_as(value, variable, units)
    except ZeroDivisionError:
        raise Refused(f"a spectral position of zero is no {spoken(variable)}", code="no-value",
                      subject=subject) from None
    if found is None:
        raise Refused(f"the value given is no {' or '.join(spoken(f) for f in dispersion.forms(variable))}",
                      code="not-a-form", subject=subject)
    return found


def within(value: Quantity, bounds: tuple[Quantity, Quantity], variable: str, dispersion: Dispersion, units: Units,
           *, subject: str) -> None:
    """Refused, `out-of-range`, unless ``value`` lies between ``bounds`` — each in any form of
    ``variable``, compared as ``variable`` states them (materials.md § 6; material-data.md § 7)."""
    low, high = sorted(stated_as(b, variable, dispersion, units, subject=subject).value for b in bounds)
    at = stated_as(value, variable, dispersion, units, subject=subject).value
    if not low <= at <= high:
        raise Refused(f"the {spoken(variable)} asked lies outside the range its data holds in", code="out-of-range",
                      subject=subject)


# ------------------------------------------------------------------ a table

def interpolate(table: Rows, x: Fraction, *, subject: str) -> tuple[Fraction, ...]:
    """Each value column of ``table`` at ``x``, its variable in its column's unit: a row's own
    values at a row, and between two rows each column interpolated linearly in the table's own
    variable (material-data.md § 5). Refused, `out-of-range`, beyond its first and last rows: a
    table is never extrapolated."""
    xs = [point[0] for point in table.points]
    if not xs[0] <= x <= xs[-1]:
        raise Refused(f"{decimal(x)} lies beyond the table's first and last rows, {decimal(xs[0])} and "
                      f"{decimal(xs[-1])}", code="out-of-range", subject=subject)
    i = bisect.bisect_left(xs, x)
    if xs[i] == x:
        return table.points[i][1:]
    low, high = table.points[i - 1], table.points[i]
    t = (x - low[0]) / (high[0] - low[0])
    return tuple(a + (b - a) * t for a, b in zip(low[1:], high[1:]))


# ------------------------------------------------------------------ the dispersion models

def sellmeier(p: Mapping[str, Any], wavelength: Quantity) -> Complex:
    """eps = 1 + A + sum of B lambda^2 / (lambda^2 - C) (material-data.md § 6.1): each term's C a
    length squared, or a resonance wavelength whose square it is — its dimension tells which."""
    square = wavelength.value ** 2
    eps = 1 + p["A"].value
    for term in p["terms"]:
        pole = term["C"].value if term["C"].dimension == (wavelength ** 2).dimension else term["C"].value ** 2
        eps += term["B"].value * square / (square - pole)
    return Complex(eps)


def drude_lorentz(p: Mapping[str, Any], energy: Quantity) -> Complex:
    """eps = eps_inf - f0 Ep^2 / (E^2 + i Gamma0 E) + sum of f Ep^2 / (Ej^2 - E^2 - i Gamma E),
    under exp(-iwt) (material-data.md § 6.2), every energy in its canonical unit."""
    e, plasma = energy.value, p["plasma"].value ** 2
    eps = Complex(p["eps_inf"].value) - p["f0"].value * plasma / Complex(e * e, p["gamma0"].value * e)
    for o in p["oscillators"]:
        eps += o["f"].value * plasma / Complex(o["energy"].value ** 2 - e * e, -o["gamma"].value * e)
    return eps


#: Each dispersion model's formula, by its name in dispersion.toml: a function of its parameters —
#: each a `Quantity`, and each list of terms the model sums a list of tables of them, every name
#: its declaration's — and of the value of the variable it is written in. A basic test holds this
#: table and the declared list to each other (materials.md § 2).
FORMULAS: dict[str, Callable[[Mapping[str, Any], Quantity], Complex]] = {
    "sellmeier": sellmeier,
    "drude_lorentz": drude_lorentz,
}


def evaluate(dataset: Modelled, held: str, at: Quantity, dispersion: Dispersion, units: Units, *,
             subject: str) -> Complex:
    """A model's dataset, held under the property ``held``, at ``at``, the value of its model's
    variable (materials.md § 2): its model and its parameters held to their declaration
    (`material.model_of`, `material.parameters`), then its formula. Refused with the first
    fault's code; `no-formula` for a model declared with no formula here; `no-value` where the
    formula divides by zero."""
    model = model_of(dataset, held, dispersion)
    if isinstance(model, Fault):
        raise _refused(model, subject)
    if dataset.model not in FORMULAS:
        raise Refused(f"`{dataset.model}` is declared in femkit's list of dispersion models, and femkit has no formula "
                      "for it", code="no-formula", subject=subject)
    read, found = parameters(dataset, model, units, dispersion)
    if found:
        raise _refused(found[0], subject)
    try:
        return FORMULAS[dataset.model](read, at)
    except ZeroDivisionError:
        raise Refused(f"`{dataset.model}` has no value at this {spoken(model.variable)}: it divides by zero there",
                      code="no-value", subject=subject) from None


# ------------------------------------------------------------------ the form and the convention

def from_form(value: Complex) -> Complex:
    """An equivalent form's value as the property it is a form of (material-data.md § 3):
    eps_r = n~^2, in the convention n~ is written in — exact, the source's numbers squared. The
    reverse needs a square root, and is never done."""
    return value * value


def in_convention(value: Complex, source: Convention, target: Convention, *, subject: str) -> Complex:
    """``value``, written in ``source``'s convention, as ``target``'s: conjugated between
    `exp(-iwt)` and `exp(+iwt)`, which describe one field with conjugate phasors (material-data.md
    § 2); `real` data, with no imaginary part, alike in each. Refused, `not-real`, for complex data
    where real data is read."""
    if source == target:
        return value
    if REAL in (source, target):
        if value.im != 0:
            raise Refused(f"the data is complex, {decimal(value.re)} + {decimal(value.im)} i, and real data is read",
                          code="not-real", subject=subject)
        return value
    return value.conjugate()


def passive(value: Complex, convention: Convention, source: Convention, *, subject: str) -> Complex:
    """``value``, in ``convention``, held to the passive sign — eps'' >= 0 under `exp(-iwt)`, <= 0
    under `exp(+iwt)` (material-data.md § 2; `dispersion.active`). Refused, `active`, naming its
    source's convention, for a loss of the sign of a material that gives energy."""
    if active(value.im, convention):
        raise Refused(f"its loss, {decimal(value.im)}, has the sign of a material that gives energy under "
                      f"{convention}; its source writes its data under {source}", code="active", subject=subject)
    return value


# ------------------------------------------------------------------ all of them

def taken(dataset: Value | Table | Modelled, held: str, read: str, at: Quantity | None, convention: Convention, *,
          file: bytes | None, properties: Mapping[str, Property], dispersion: Dispersion, units: Units,
          subject: str) -> Complex:
    """What a dataset, held under the property ``held``, gives a formulation reading ``read``
    stated in ``convention``, at ``at`` — the value of a variable the step supplies, in any of its
    forms; None where it supplies none (materials.md § 6): held to the material's own rules
    (`material.faults`), whatever `project check` found; taken at that value, converted exactly
    to the dataset's variable, within its range; an equivalent form converted to the property
    read; stated in the physics' convention — a model's is its declaration's; held to the passive
    sign. ``file`` is a table's file, as the door read it. Each failure refused, with its code and
    ``subject`` (module docstring)."""
    listed = properties.get(held)
    if listed is None:
        raise Refused(f"femkit's list of material properties names no property `{held}`", code="no-such-property",
                      subject=subject)
    for fault in faults(dataset, held, listed, file, units, dispersion):
        raise _refused(fault, subject)
    if isinstance(dataset, Table) and file is None:
        raise Refused(f"the table {dataset.table} is taken without its file", code="missing-file", subject=subject)
    model = model_of(dataset, held, dispersion) if isinstance(dataset, Modelled) else None
    variable = dataset.variable.name if isinstance(dataset, Table) else model.variable if model else None
    variables = [variable] if variable else [v for v in listed.depends_on if v in dispersion.variables]
    span = bounds(dataset, variables, None, units, dispersion)
    if at is None and variable is not None:
        raise Refused(f"the data varies with the {spoken(variable)}, and the step supplies none",
                      code="dataset-varies", subject=subject)
    if at is None and isinstance(span, Span):
        raise Refused(f"the value holds only within its range, {dataset.range[0]} to {dataset.range[1]}, never at zero "
                      "frequency, and the step supplies no variable", code="dataset-varies", subject=subject)
    if at is not None and isinstance(span, Span):
        within(at, span.bounds, span.variable, dispersion, units, subject=subject)
    if isinstance(dataset, Value):
        value = Complex(measured(dataset.value, "`value`", [listed.unit], units, dispersion).value)
    elif isinstance(dataset, Table):
        try:
            x = units.convert(stated_as(at, variable, dispersion, units, subject=subject), dataset.variable.unit)
        except UnitError as exc:
            raise Refused(str(exc), code="not-a-form", subject=subject) from None
        columns = interpolate(rows(file, dataset.convention), x, subject=subject)
        value = Complex(*columns) * units.parse(listed.unit).value
    else:
        value = evaluate(dataset, held, stated_as(at, variable, dispersion, units, subject=subject), dispersion, units,
                         subject=subject)
    if held != read:
        if held not in getattr(properties.get(read), "equivalents", ()):
            raise Refused(f"the data is held as the {spoken(held)}, which is no equivalent form of the {spoken(read)} "
                          "read", code="no-conversion", subject=subject)
        value = from_form(value)
    source = model.convention if model is not None else dataset.convention
    return passive(in_convention(value, source, convention, subject=subject), convention, source, subject=subject)
