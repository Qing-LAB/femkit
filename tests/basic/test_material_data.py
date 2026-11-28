"""What a material's dataset gives at one value of its variable (materials.md § 6), exactly: the
science checks of docs/science/material-data.md § 8, each on a dataset read as a material's file
holds it, taken through `femkit.materials.data` — and each refusal of § 6, told apart by its code,
the material's own rules among them, which a case applies whatever `project check` found. The
checks are science: their design may change, their existence may not (testing.md § 3)."""

from __future__ import annotations

import hashlib
import tomllib
from decimal import Decimal
from fractions import Fraction

import pytest

from tests import kit
from femkit.core.errors import Refused, Unstated
from femkit.core.persist import write_toml
from femkit.core.schema import Measure, Number, load_text
from femkit.core.units import Quantity, UnitError
from femkit.definitions import catalogue
from femkit.materials import data, material
from femkit.materials.data import Complex
from femkit.materials.material import Material, TableError, rows

SUBJECT = "material:m:properties.relative_permittivity.d"
#: Malitson's fused silica (I. H. Malitson, J. Opt. Soc. Am. 55, 1205 (1965), doi:10.1364/JOSA.55.001205):
#: each term's B, and its resonance wavelength in µm (material-data.md § 8).
MALITSON = (("0.6961663", "0.0684043"), ("0.4079426", "0.1162414"), ("0.8974794", "9.896161"))


def dataset(text: str, prop: str = "relative_permittivity"):
    """The dataset `d` of ``prop``, read from a material file holding it as the door reads one."""
    units = catalogue.units(kit.ctx())
    material = load_text(f'schema = 1\ndisplay = "m"\n\n[properties.{prop}.d]\n' + text, Material, "material.toml",
                         {"units": units})
    return material.properties[prop]["d"]


def q(value: str, unit: str) -> Quantity:
    """``value`` in ``unit``, exactly, as the one quantity form reads it (core.md § 11)."""
    return catalogue.units(kit.ctx()).measure(Measure[Number](value=Decimal(value), unit=unit))


def take(held, at: Quantity | None, convention: str = "exp(-iwt)", *, form: str = "relative_permittivity",
         read: str = "relative_permittivity", file: bytes | None = None) -> Complex:
    """``held``, held under ``form``, taken for a formulation reading ``read`` in ``convention``, at ``at``."""
    ctx = kit.ctx()
    units = catalogue.units(ctx)
    return data.taken(held, form, read, at, convention, file=file, properties=catalogue.properties(ctx),
                      dispersion=catalogue.dispersion(ctx), units=units, subject=SUBJECT)


def sellmeier(poles: list[tuple[str, str]], a: str = "0", terms: tuple = MALITSON):
    """Malitson's terms' strengths with ``poles``, each its number and its unit."""
    lines = "".join(f"[[properties.relative_permittivity.d.parameters.terms]]\nB = {b}\n"
                    f"C = {{value = {c}, unit = \"{unit}\"}}\n" for (b, _), (c, unit) in zip(terms, poles))
    return dataset('model = "sellmeier"\nconvention = "real"\nsource = "Malitson (1965)"\n'
                   f'range = {{value = [0.21, 3.71], unit = "um"}}\n\n'
                   f'[properties.relative_permittivity.d.parameters]\nA = {a}\n'
                   + lines)


def table(rows_text: str, convention: str = "exp(-iwt)", prop: str = "refractive_index", range_: str | None = None):
    """A table dataset of ``prop`` in µm, and its file's bytes; its range its rows' extent, unless given."""
    file = rows_text.encode()
    points = [line.split(",")[0] for line in rows_text.splitlines()[1:] if line.strip()]
    range_ = range_ or f'{{value = [{points[0]}, {points[-1]}], unit = "um"}}'
    held = dataset(f'table = "t.csv"\nsha256 = "{hashlib.sha256(file).hexdigest()}"\n'
                   f'variable = {{ name = "wavelength", unit = "um" }}\ninterpolation = "linear"\n'
                   f'convention = "{convention}"\nsource = "a test\'s own"\nrange = {range_}\n', prop)
    return held, file


def test_malitsons_silica_gives_its_index_and_its_poles_as_squares_the_same_value_exactly():
    """Fails if fused silica by Malitson's Sellmeier coefficients does not give n = 1.4585 at
    0.5876 µm to four decimals, if the same coefficients with each pole stated as its square give
    another value at all, or if the same position stated as a frequency or a photon energy does
    (material-data.md §§ 4, 6.1, 8)."""
    eps = take(sellmeier([(w, "um") for _, w in MALITSON]), q("0.5876", "um"), "real")
    assert eps.im == 0 and Fraction("1.45845") ** 2 <= eps.re < Fraction("1.45855") ** 2
    squares = [Decimal(w) ** 2 for _, w in MALITSON]
    assert [Fraction(s) for s in squares] == [Fraction(w) ** 2 for _, w in MALITSON]      # each written exactly
    assert take(sellmeier([(str(s), "um^2") for s in squares]), q("0.5876", "um"), "real") == eps
    held = sellmeier([(w, "um") for _, w in MALITSON])
    assert take(held, q("299792458", "m/s") / q("0.5876", "um"), "real") == eps
    assert take(held, q("6.62607015e-34", "J s") * q("299792458", "m/s") / q("0.5876", "um"), "real") == eps


def test_sellmeier_with_a_alone_is_one_plus_a_at_every_wavelength():
    """Fails if `sellmeier` with A = 1 and no term is not exactly 2 at every wavelength — its A
    dropped, or a term counted that is not there (material-data.md §§ 6.1, 8)."""
    held = sellmeier([], a="1", terms=())
    assert [take(held, q(w, "um"), "real") for w in ("0.21", "0.5876", "1", "3.71")] == [Complex(Fraction(2))] * 4


DRUDE = ('model = "drude_lorentz"\nconvention = "exp(-iwt)"\nsource = "a test\'s own"\nrange = "all"\n\n'
         '[properties.relative_permittivity.d.parameters]\neps_inf = {eps_inf}\nplasma = {plasma}\nf0 = {f0}\n'
         'gamma0 = {gamma0}\n')
EV = '{{value = {}, unit = "eV"}}'.format     # an energy in electronvolts, as a material's file writes it


def oscillators(*terms: tuple[str, str, str]) -> str:
    """Each oscillator's `f`, `energy` and `gamma`, as a material's file writes the list."""
    return "".join(f'[[properties.relative_permittivity.d.parameters.oscillators]]\nf = {f}\nenergy = {EV(e)}\n'
                   f'gamma = {EV(g)}\n' for f, e, g in terms)


def test_the_drude_limit_is_its_formula_and_zero_where_the_formula_says():
    """Fails if `drude_lorentz` with no oscillator and no damping — eps_inf = 4, Ep = 9 eV,
    f0 = 1/4 — is not eps_inf - f0 Ep^2 / E^2 exactly, or is not zero at exactly
    E = Ep sqrt(f0 / eps_inf) = 2.25 eV: f0 dropped or squared, or Ep not squared, each moves
    it (material-data.md §§ 6.2, 8)."""
    held = dataset(DRUDE.format(eps_inf=4, plasma=EV(9), f0="0.25", gamma0=EV(0)))
    for energy in ("3", "4.5", "9/7", "20"):
        at = Quantity(Fraction(energy)) * q("1", "eV")
        assert take(held, at) == Complex(4 - Fraction(81, 4) / Fraction(energy) ** 2)
    assert take(held, q("2.25", "eV")) == Complex(Fraction(0))


def test_one_oscillator_alone_gives_the_science_documents_values_exactly():
    """Fails if one bound oscillator alone — eps_inf = 2, Ep = 3 eV, f0 = 0, f = 1/2, Ej = 2 eV,
    Gamma = 1/4 eV — does not give 2 + 9i at 2 eV and 506/145 + 18/145 i at 1 eV exactly: its
    strength dropped, Ej^2 - E^2 turned round, or its damping's sign flipped, each moves one of
    them (material-data.md §§ 6.2, 8)."""
    held = dataset(DRUDE.format(eps_inf=2, plasma=EV(3), f0=0, gamma0=EV(0)) + oscillators(("0.5", "2", "0.25")))
    assert take(held, q("2", "eV")) == Complex(Fraction(2), Fraction(9))
    assert take(held, q("1", "eV")) == Complex(Fraction(506, 145), Fraction(18, 145))


def test_a_drude_lorentz_model_with_positive_parameters_absorbs_at_every_energy():
    """Fails if `drude_lorentz` with positive parameters — gold's free electrons and five
    oscillators, as Rakić et al. tabulate the model — gives a loss eps'' that is not positive
    under exp(-iwt), or not its conjugate's under exp(+iwt), at any of several energies
    (material-data.md §§ 2, 6.2, 8)."""
    held = dataset(DRUDE.format(eps_inf=1, plasma=EV(9.03), f0="0.760", gamma0=EV(0.053)) + oscillators(
        ("0.024", "0.415", "0.241"), ("0.010", "0.830", "0.345"), ("0.071", "2.969", "0.870"),
        ("0.601", "4.304", "2.494"), ("4.384", "13.32", "2.214")))
    for energy in ("0.2", "1", "2.1", "2.5", "4.3", "13.32", "40"):
        minus = take(held, q(energy, "eV"))
        assert minus.im > 0 and take(held, q(energy, "eV"), "exp(+iwt)") == minus.conjugate()


def test_johnson_and_christys_gold_as_a_refractive_index_gives_its_permittivity_exactly():
    """Fails if (n, kappa) = (0.29, 2.863) — Johnson and Christy's gold at 0.5821 µm, a row of a
    refractive-index table under exp(-iwt) — does not give eps_r = -8.112669 + 1.66054 i exactly
    under exp(-iwt), and its conjugate under exp(+iwt) (material-data.md §§ 2, 3, 8)."""
    held, file = table("wavelength,n,k\n0.5,1,1\n0.5821,0.29,2.863\n0.7,0.2,4\n")
    expected = Complex(Fraction("-8.112669"), Fraction("1.66054"))
    assert take(held, q("0.5821", "um"), form="refractive_index", file=file) == expected
    assert take(held, q("0.5821", "um"), "exp(+iwt)", form="refractive_index", file=file) == expected.conjugate()


def test_a_table_at_one_of_its_points_gives_its_row_and_halfway_between_two_their_mean():
    """Fails if a table read at one of its points does not give that point's row, halfway between
    two points their mean, or elsewhere between them the straight line through them, each column
    alike; or if an (n, kappa) table with rows (1 µm: 1, 0) and (3 µm: 3, 2) does not give 3 + 4i
    at 2 µm — n and kappa interpolated, then squared — but the 3 + 6i of squaring first
    (material-data.md §§ 3, 5, 8)."""
    held, file = table("wavelength,eps\n1,2\n3,6\n4,-1\n", "real", "relative_permittivity")
    assert [take(held, q(x, "um"), "real", file=file) for x in ("1", "1.5", "2", "3", "3.5", "4")] == [
        Complex(Fraction(v)) for v in ("2", "3", "4", "6", "5/2", "-1")]
    points = rows(b"x,re,im\n1,2,10\n3,6,20\n", "exp(-iwt)")
    assert data.interpolate(points, Fraction(2), subject=SUBJECT) == (Fraction(4), Fraction(15))
    assert data.interpolate(points, Fraction(3), subject=SUBJECT) == (Fraction(6), Fraction(20))
    held, file = table("wavelength,n,k\n1,1,0\n3,3,2\n")
    assert take(held, q("2", "um"), form="refractive_index", file=file) == Complex(Fraction(3), Fraction(4))


def test_a_source_written_under_exp_plus_iwt_converts_to_exp_minus_iwt_by_conjugation_exactly():
    """Fails if an (n, kappa) table a source writes under exp(+iwt) — n~ = n - i kappa, rows
    (1 µm: 1, 0) and (3 µm: 3, -2) — does not give exactly 3 + 4i at 2 µm for a physics under
    exp(-iwt), the conjugate of its own 3 - 4i, which it gives under exp(+iwt) (material-data.md
    §§ 2, 3)."""
    held, file = table("wavelength,n,k\n1,1,0\n3,3,-2\n", "exp(+iwt)")
    at = q("2", "um")
    assert take(held, at, "exp(-iwt)", form="refractive_index", file=file) == Complex(Fraction(3), Fraction(4))
    assert take(held, at, "exp(+iwt)", form="refractive_index", file=file) == Complex(Fraction(3), Fraction(-4))


def test_the_spectral_variables_convert_exactly_by_c0_h_and_the_unit_tables_electronvolt():
    """Fails if a vacuum wavelength stated as a frequency or a photon energy is not c0 / lambda
    and h c0 / lambda exactly — in electronvolts, h c0 / (e lambda 1 V), e being the unit table's
    — or does not come back to itself exactly (material-data.md § 4)."""
    ctx = kit.ctx()
    units, dispersion = catalogue.units(ctx), catalogue.dispersion(ctx)
    wavelength = q("0.5876", "um")
    frequency = data.stated_as(wavelength, "frequency", dispersion, units, subject=SUBJECT)
    energy = data.stated_as(frequency, "photon_energy", dispersion, units, subject=SUBJECT)
    assert frequency == q("299792458", "m/s") / q("0.5876", "um")
    assert units.convert(energy, "eV") == Fraction("6.62607015e-34") * 299792458 / (
        Fraction("1.602176634e-19") * Fraction("0.5876e-6"))
    assert data.stated_as(energy, "wavelength", dispersion, units, subject=SUBJECT) == wavelength


def test_each_declared_model_has_a_formula_reading_exactly_its_declared_names():
    """Fails if a dispersion model is declared with no formula, a formula stands for no declared
    model, or a formula reads a parameter or a list of terms its model does not declare, or leaves
    one it declares unread — a default standing in for a declared name among them (materials.md
    § 2: "a model declared without a formula, or a formula of no declared model, fails it")."""
    ctx = kit.ctx()
    units, dispersion = catalogue.units(ctx), catalogue.dispersion(ctx)
    assert set(data.FORMULAS) == set(dispersion.models)

    class Reading(dict):
        """A table of parameters noting each name a formula reads from it."""

        def __init__(self, values: dict, read: set):
            super().__init__(values)
            self.read = read

        def __getitem__(self, key):
            self.read.add(key)
            return super().__getitem__(key)

    for name, model in dispersion.models.items():
        read: set = set()
        terms: dict[str, set] = {s: set() for s in model.sums}
        given = {p: units.unit(spec.units[0]) for p, spec in model.parameters.items()}
        given |= {s: [Reading({p: units.unit(spec.units[0]) for p, spec in held.parameters.items()}, terms[s])]
                  for s, held in model.sums.items()}
        data.FORMULAS[name](Reading(given, read), q("3", dispersion.variables[model.variable].unit))
        assert (read, terms) == (set(model.parameters) | set(model.sums),
                                 {s: set(held.parameters) for s, held in model.sums.items()}), name


def test_a_model_declared_without_a_formula_is_refused_as_such(definitions):
    """Fails if a dataset of a model femkit's list declares, and femkit has no formula for, is
    taken, or is refused as a model the list lacks (materials.md § 2: "A model joins the list with
    its formula's code")."""
    path = definitions / "dispersion.toml"
    declared = tomllib.loads(path.read_text())
    declared["models"]["cauchy"] = declared["models"]["sellmeier"]
    write_toml(path, declared)
    held = dataset('model = "cauchy"\nconvention = "real"\nsource = "s"\nrange = "all"\n\n'
                   '[properties.relative_permittivity.d.parameters]\nA = 1\n')
    with kit.refused(Refused, "no-formula", SUBJECT):
        take(held, q("1", "um"), "real")


ROWS = "wavelength,n,k\n0.5,1.5,0\n0.6,1.4,0.1\n"


@pytest.mark.parametrize("make, at, read, code", [
    (lambda: table(ROWS), ("0.4", "um"), "relative_permittivity", "out-of-range"),
    (lambda: table(ROWS, range_='{value = [0.5, 0.55], unit = "um"}'), ("0.58", "um"), "relative_permittivity",
     "out-of-range"),
    (lambda: table(ROWS), None, "relative_permittivity", "dataset-varies"),
    (lambda: table("wavelength,n,k\n0.5,1.5,0\n0.6,-1.4,0.1\n"), ("0.6", "um"), "relative_permittivity", "active"),
    (lambda: table(ROWS), ("300", "K"), "relative_permittivity", "not-a-form"),
    (lambda: table(ROWS), ("0.55", "um"), "refractive_index", "no-conversion"),
], ids=["beyond the table's rows", "beyond its range", "no variable supplied", "a passive material made active",
        "a value of another variable", "read as no property it is a form of"])
def test_a_value_its_data_cannot_give_is_refused_with_its_code(make, at, read, code):
    """Fails if a table is extrapolated beyond its first and last rows, taken outside its stated
    range, taken where the step supplies no variable, taken where its loss converts to the sign of
    a material that gives energy, taken at a value of a variable it is not written in, or read as
    a property it is no equivalent form of — each other than refused with its code and the
    dataset as its subject (materials.md § 6; material-data.md §§ 2, 3, 5)."""
    held, file = make()
    form = "refractive_index" if read == "relative_permittivity" else "relative_permittivity"
    with kit.refused(Refused, code, SUBJECT):
        take(held, q(*at) if at else None, form=form, read=read, file=file)


def test_a_changed_table_and_a_model_off_the_list_are_refused():
    """Fails if a table whose file's SHA-256 is not the one its dataset states is taken, or a
    model the list lacks, other than refused with its code (materials.md §§ 2, 6: "the dataset is
    read and checked against its SHA-256"; "a model not on the list is refused")."""
    held, file = table(ROWS)
    with kit.refused(Refused, "digest-differs", SUBJECT):
        take(held, q("0.55", "um"), form="refractive_index", file=file.replace(b"1.4", b"1.3"))
    model = dataset('model = "cauchy"\nconvention = "real"\nsource = "s"\nrange = "all"\n')
    with kit.refused(Refused, "no-such-model", SUBJECT):
        take(model, q("0.55", "um"), "real")


@pytest.mark.parametrize("text, form, at, code", [
    (DRUDE.format(eps_inf=1, plasma="14.98", f0=1, gamma0=EV(0.05)), "relative_permittivity", ("1", "eV"),
     "wrong-dimension"),
    (DRUDE.format(eps_inf=1, plasma=EV(9), f0=1, gamma0=EV(-0.05)), "relative_permittivity", ("1", "eV"), "wrong-sign"),
    (DRUDE.format(eps_inf=1, plasma=EV(9), f0=1, gamma0=EV(0.05)) + oscillators(("-0.5", "2", "0.25")),
     "relative_permittivity", ("1", "eV"), "wrong-sign"),
    (DRUDE.format(eps_inf=1, plasma=EV(9), f0=1, gamma0=EV(0.05)).replace("gamma0", "damping"),
     "relative_permittivity", ("1", "eV"), "no-such-parameter"),
    (DRUDE.format(eps_inf=1, plasma=EV(9), f0=1, gamma0=EV(0.05)).replace(f"gamma0 = {EV(0.05)}\n", ""),
     "relative_permittivity", ("1", "eV"), "parameter-missing"),
    (DRUDE.format(eps_inf=1, plasma=EV(9), f0=1, gamma0=EV(0.05)).replace('"exp(-iwt)"', '"exp(+iwt)"'),
     "relative_permittivity", ("1", "eV"), "wrong-convention"),
    ('model = "sellmeier"\nconvention = "real"\nsource = "s"\nrange = "all"\n\n'
     '[properties.relative_permittivity.d.parameters]\nA = 0\n\n'
     '[[properties.relative_permittivity.d.parameters.terms]]\nB = 1\nC = {value = 9.896161, unit = "eV"}\n',
     "relative_permittivity", ("1", "um"), "wrong-dimension"),
    ('model = "sellmeier"\nconvention = "real"\nsource = "s"\nrange = "all"\n\n'
     '[properties.refractive_index.d.parameters]\nA = 0\n', "refractive_index", ("1", "um"), "no-such-model"),
    ('value = {value = 4, unit = "m"}\nconvention = "real"\nsource = "s"\nrange = "all"\n', "relative_permittivity",
     None,
     "wrong-dimension"),
    ('value = 4\nconvention = "real"\nsource = "s"\nrange = {value = [0.5, 0.6], unit = "um"}\n',
     "relative_permittivity", None,
     "dataset-varies"),
], ids=["a plasma energy with no unit", "a negative damping", "an oscillator's negative strength",
        "a parameter the model lacks", "a parameter missing", "a convention other than the model's",
        "a pole in an energy", "a model held under a property it does not give", "a value outside its dimension",
        "a value with a spectral range where none is supplied"])
def test_a_case_applies_the_materials_rules_whatever_project_check_found(text, form, at, code):
    """Fails if a dataset breaking a rule of its material — a parameter with no unit, in another
    dimension or of another sign than its model declares, one the model lacks or one missing, a
    convention other than its model's, a model held under a property it does not give, a value
    outside its property's dimension, or a value whose range is not `all` under a step supplying
    no variable — is taken by a case rather than refused with the code `project check` gives it
    (materials.md §§ 2, 3, 6; material-data.md §§ 6.2, 7)."""
    with kit.refused(Refused, code, SUBJECT):
        convention = "real" if "sellmeier" in text or "value" in text else "exp(-iwt)"
        take(dataset(text, form), q(*at) if at else None, convention, form=form)


def test_a_case_resting_on_a_dataset_that_does_not_state_its_source_is_refused_as_unstated():
    """Fails if a dataset not stating its source, its convention or its range is taken, or is
    refused otherwise than as a missing statement, `Unstated` (materials.md § 3: "`study prep`
    refuses a case resting on one that does"; core.md § 9)."""
    for key, line in (("source", 'source = "s"\n'), ("convention", 'convention = "real"\n'),
                      ("range", 'range = "all"\n')):
        held = dataset(('value = 2\nconvention = "real"\nsource = "s"\nrange = "all"\n').replace(line, ""))
        with kit.refused(Unstated, "not-stated", SUBJECT):
            take(held, None, "real")


def test_a_binary_float_never_enters_the_exact_arithmetic():
    """Fails if a binary float is taken as a material's quantity or into an exact complex number,
    rather than refused (core.md § 11: "never through a binary float")."""
    units = catalogue.units(kit.ctx())
    with pytest.raises(UnitError):
        material.quantity(0.1, units)
    assert material.quantity(Decimal("0.1"), units).value == Fraction(1, 10)
    with pytest.raises(TypeError):
        Complex(Fraction(1)) + 0.1
    with pytest.raises(TypeError):
        Complex.of(0.5)


@pytest.mark.parametrize("text, convention, line", [
    ("x,re,im\n2,1,1\n1,1,1\n", "exp(-iwt)", 3),
    ("x,re,im\n1,1,1\n1,2,2\n", "exp(-iwt)", 3),
    ("x,re\n1,1\n", "exp(-iwt)", 1),
    ("x,re,im\n1,1,1\n", "real", 1),
    ("x,re,im\n1,1,1/2\n", "exp(-iwt)", 2),
    ("x,re,im\n1,1,0.5 m\n", "exp(-iwt)", 2),
    ("x,re,im\n1,1\n", "exp(-iwt)", 2),
    ("x,re,im\n1,1,1\n\n2,2,2\n", "exp(-iwt)", 3),
    ("x,re,im\n", "exp(-iwt)", 2),
    ("0.5,1.5,0\n0.6,1.4,0.1\n", "exp(-iwt)", 1),
], ids=["the variable decreasing", "the variable repeated", "2 columns of complex data", "3 columns of real data",
        "a fraction", "a value with a unit", "a short row", "an empty line", "no point", "a first row of numbers"])
def test_a_table_file_of_another_shape_is_refused_naming_its_line(text, convention, line):
    """Fails if a table's file is read whose variable does not increase strictly, whose columns
    are not 2 for real data and 3 for complex, holds a value that is no decimal number, a short
    row, an empty line before a row, no point, or a first row of numbers — whose point would be
    lost as the columns' names — or if what refuses it names another line (materials.md § 3:
    "a first row of numbers is a finding"; "a finding at `table`, naming its line")."""
    with pytest.raises(TableError) as caught:
        rows(text.encode(), convention)
    assert caught.value.line == line


def test_blank_lines_at_a_tables_end_are_ignored():
    """Fails if a table's file ending in blank lines — as an editor often leaves it — is refused,
    or reads other points than without them (materials.md § 3: "blank lines at its end
    ignored")."""
    plain = rows(b"x,re,im\n1,1,1\n2,2,2\n", "exp(-iwt)")
    assert rows(b"x,re,im\n1,1,1\n2,2,2\n\n\n", "exp(-iwt)").points == plain.points
    assert rows(b"x,re,im\r\n1,1,1\r\n2,2,2\r\n  \r\n", "exp(-iwt)").points == plain.points
