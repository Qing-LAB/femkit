"""`femkit/data/dispersion.toml`: the variables a material's data may vary with, and the
dispersion models (materials.md § 2) — two closed lists, declared as data. A property's
`depends_on` names its variables (materials.md § 1), a step kind the variables it supplies
(models.md § 4.2), a table the variable its first column is written in and a model's dataset its
model (materials.md § 3). What each means — the exact relations among the spectral variables,
the constants they are converted by, each model's formula, the convention it is written in and
the sign each of its parameters must have — is the science document it names
(docs/science/material-data.md §§ 1, 4, 6); loading refuses a section the document lacks, as a
formulation's does (models.md § 4.3). The conventions, the signs a parameter may have and the
variables a dataset states the value its data holds at are declared here once each, with what
each means to the rules that read them (`CONVENTIONS`, `SIGNS`, `CONDITIONS`); loading refuses a
list without a variable for each of those conditions.

Its model lives here, beside the property list's, since the catalogue that loads it sits below
the `materials` package that owns the rule (framework.md § 1)."""

from __future__ import annotations

from fractions import Fraction
from typing import Callable, Literal

from pydantic import Field, ValidationInfo, model_validator

from femkit.core import dirs, persist
from femkit.core.markdown import headings
from femkit.core.schema import Measure, Model, Number, as_quantity, refuse
from femkit.core.units import Quantity, UnitError, Units
from femkit.definitions.formulations import Described
from femkit.definitions.properties import NAME

REAL = "real"
#: The conventions complex data is written in (material-data.md § 2), each with the sign of
#: i omega t in its phasor's exponent — the sign a passive material's loss, the imaginary part,
#: never has under it; `real` data has no imaginary part, and its sign is 0. The one declaration:
#: `Convention` is its names, and `active` reads its signs.
CONVENTIONS: dict[str, int] = {REAL: 0, "exp(-iwt)": -1, "exp(+iwt)": 1}
Convention = Literal[tuple(CONVENTIONS)]

#: The variables a dataset states the value its data holds at, each as its field of that name
#: (materials.md § 3): the one declaration — a dataset's fields are made from it
#: (`Stated`, femkit/materials/material.py), and a source's condition may become only one of
#: them (`Condition`, femkit/definitions/importers.py).
CONDITIONS: tuple[str, ...] = ("temperature",)


def active(loss: Fraction, convention: Convention) -> bool:
    """Whether ``loss``, the imaginary part of complex data written in ``convention``, has the sign
    of a material that gives energy rather than absorbs it (material-data.md § 2): eps'' < 0 under
    `exp(-iwt)`, > 0 under `exp(+iwt)` — and, for a refractive index with n > 0, kappa alike
    (material-data.md § 3)."""
    return CONVENTIONS[convention] * loss > 0


#: The signs a model's parameter is declared to have (material-data.md § 6.2), each with whether a
#: value has it: the one declaration, `Sign` its names.
SIGNS: dict[str, Callable[[Fraction], bool]] = {
    "positive": lambda value: value > 0,
    "not negative": lambda value: value >= 0,
    "any": lambda value: True,
}
Sign = Literal[tuple(SIGNS)]


class Constant(Described):
    """A physical constant the spectral variables are converted by (material-data.md § 1)."""

    value: Measure[Number] = as_quantity("its exact value, with its unit", "constant")


class Spectral(Model):
    """How a spectral variable states the spectral position: a constant times the frequency
    raised to a power (material-data.md § 4) — so each converts to the others exactly."""

    constant: str | None = Field(default=None, description="the constant, by its name among the constants; none "
                                                           "for the frequency itself")
    power: Literal[1, -1] = Field(description="the power the frequency is raised to: -1 for a variable inversely "
                                              "proportional to it, as the wavelength is")


class Variable(Model):
    """One variable a material's data may vary with (materials.md § 2)."""

    description: str = Field(description="what it is, in one plain sentence")
    unit: str = as_quantity("a unit of its dimension, as the unit table reads it; a dataset may write it in any unit "
                            "of that dimension", "unit")
    spectral: Spectral | None = Field(default=None, description="for one of the spectral variables — one spectral "
                                      "position stated three ways — how it states it",
                                      json_schema_extra={"doc": "material-data.md § 4"})


class Parameter(Model):
    """One parameter of a dispersion model, or of each term it sums."""

    description: str = Field(description="what it is, in one plain sentence")
    units: list[str] = as_quantity("a unit of each dimension it may have, as the unit table reads it — `1` for a "
                                   "plain number; where it may have two, the formula tells which by its dimension",
                                   "unit", min_length=1)
    sign: Sign = Field(description="the sign its value must have, checked on its own, since a term that gives energy "
                                   "can hide in the sum", json_schema_extra={"doc": "material-data.md § 6.2"})


class Sum(Model):
    """A list of terms a dispersion model sums, each term a table of its own parameters."""

    description: str = Field(description="what each term is, in one plain sentence")
    parameters: dict[str, Parameter] = Field(min_length=1, description="each term's parameters, by name")


class DispersionModel(Described):
    """One dispersion model (materials.md § 2): its formula is its section of the science
    document."""

    gives: str = Field(description="the property it gives, by its name in femkit's list of material properties")
    variable: str = Field(description="the variable its formula is written in, by its name among the variables")
    convention: Convention = Field(description="the convention its formula is written in")
    parameters: dict[str, Parameter] = Field(default_factory=dict, description="its parameters, by name; each is "
                                                                               "given")
    sums: dict[str, Sum] = Field(default_factory=dict, description="each list of terms it sums, by the key a dataset "
                                                                   "writes it under; a list may be empty")


class Dispersion(Model):
    """`dispersion.toml`: the variables a material's data may vary with, and the dispersion
    models (materials.md § 2)."""

    science: str = Field(description="the science document that states what each means, from the checkout's root")
    constants: dict[str, Constant] = Field(default_factory=dict, description="the exact constants the spectral "
                                                                             "variables are converted by")
    variables: dict[str, Variable] = Field(description="the variables, by name")
    models: dict[str, DispersionModel] = Field(description="the dispersion models, by name: a closed list")

    @model_validator(mode="after")
    def _declared(self, info: ValidationInfo) -> "Dispersion":
        units = (info.context or {}).get("units")
        properties = (info.context or {}).get("properties")
        problems: list[tuple[tuple, str]] = []
        science = persist.read_text(dirs.checkout() / self.science)
        if science is None:
            problems.append((("science",), f"{self.science} does not exist"))
        anchors = {h.anchor for h in headings(science)} if science is not None else set()
        for table in ("constants", "variables", "models"):
            problems += [((table, n), f"{n!r} is no name: its plain name, lowercase, with `_`")
                         for n in getattr(self, table) if not NAME.fullmatch(n)]
        problems += [(("variables",), f"no variable {n!r}: a dataset states the {n} its data holds at as a value of it")
                     for n in CONDITIONS if n not in self.variables]
        problems += [((t, n, "section"), f"{self.science} has no section #{d.section}") for t in ("constants", "models")
                     for n, d in getattr(self, t).items() if anchors and d.section not in anchors]
        for name, v in self.variables.items():
            if v.spectral is not None and v.spectral.constant is not None and v.spectral.constant not in self.constants:
                problems.append((("variables", name, "spectral", "constant"),
                                 f"{v.spectral.constant!r} is none of the constants: {', '.join(self.constants)}"))
        bases = [n for n, v in self.variables.items() if v.spectral and v.spectral == Spectral(power=1)]
        if any(v.spectral for v in self.variables.values()) and len(bases) != 1:
            problems.append((("variables",), "exactly one spectral variable is the frequency itself — no constant, "
                                             "power 1 — and the others are stated from it"))
        for name, m in self.models.items():
            if m.variable not in self.variables:
                problems.append((("models", name, "variable"), f"{m.variable!r} is none of the variables: "
                                                               f"{', '.join(self.variables)}"))
            if properties is not None and m.gives not in properties:
                problems.append((("models", name, "gives"), f"{m.gives!r} is no property of femkit's list: "
                                                            f"{', '.join(sorted(properties))}"))
            problems += [(("models", name, "sums", s), f"{s!r} is also one of its parameters")
                         for s in m.sums if s in m.parameters]
        if units is not None and not problems:
            problems += self._dimensions(units, bases[0] if bases else None)
        refuse("Dispersion", problems)
        return self

    def _dimensions(self, units: Units, base: str | None) -> list[tuple[tuple, str]]:
        """Every value and unit read by the unit table, and each spectral variable's unit of the
        dimension its relation to the frequency gives it."""
        problems: list[tuple[tuple, str]] = []
        texts = [(("constants", n, "value", "unit"), c.value.unit) for n, c in self.constants.items()]
        texts += [(("variables", n, "unit"), v.unit) for n, v in self.variables.items()]
        texts += [(("models", n, "parameters", p, "units", i), u) for n, m in self.models.items()
                  for p, spec in m.parameters.items() for i, u in enumerate(spec.units)]
        texts += [(("models", n, "sums", s, "parameters", p, "units", i), u) for n, m in self.models.items()
                  for s, terms in m.sums.items() for p, spec in terms.parameters.items() for i, u in enumerate(spec.units)]
        for at, text in texts:
            try:
                units.unit(text)
            except UnitError as exc:
                problems.append((at, str(exc)))
        if problems or base is None:
            return problems
        frequency = units.unit(self.variables[base].unit)
        for name, v in self.variables.items():
            if v.spectral is not None:
                given = self.constant(v.spectral, units) * Quantity(Fraction(1), frequency.dimension) ** v.spectral.power
                if units.unit(v.unit).dimension != given.dimension:
                    problems.append((("variables", name, "unit"), f"{v.unit!r} is not of the dimension its relation to "
                                                                  f"the frequency, {base}, gives it"))
        return problems

    # ------------------------------------------------------------ the spectral variables

    def constant(self, spectral: Spectral, units: Units) -> Quantity:
        """The constant a spectral variable is the frequency's multiple of: 1 for the frequency."""
        return units.measure(self.constants[spectral.constant].value) if spectral.constant else Quantity(Fraction(1))

    def forms(self, variable: str) -> list[str]:
        """The variables a value of ``variable`` may be stated as (materials.md § 3, `range`): every
        spectral variable for a spectral one, since they state one position three ways; else the
        variable alone."""
        if self.variables[variable].spectral is None:
            return [variable]
        return [n for n, v in self.variables.items() if v.spectral is not None]

    def form(self, value: Quantity, variable: str, units: Units) -> str | None:
        """The form of ``variable`` that ``value`` is stated as, told by its dimension; None for a
        value in none of them."""
        return next((f for f in self.forms(variable) if units.unit(self.variables[f].unit).dimension == value.dimension),
                    None)

    def stated_as(self, value: Quantity, variable: str, units: Units) -> Quantity | None:
        """``value``, stated as any form of ``variable``, stated as ``variable`` itself, exactly: a
        spectral position converted among the spectral variables — each a constant ``k`` times the
        frequency to the power ``p``, ``p`` being 1 or -1, so the frequency is ``(value / k) ** p``
        (material-data.md § 4); any other value as it is. None for a value in none of its forms; a
        `ZeroDivisionError` for a spectral position of zero, which no variable states."""
        source = self.form(value, variable, units)
        if source is None or source == variable:
            return None if source is None else value
        given, wanted = self.variables[source].spectral, self.variables[variable].spectral
        frequency = (value / self.constant(given, units)) ** given.power
        return self.constant(wanted, units) * frequency ** wanted.power
