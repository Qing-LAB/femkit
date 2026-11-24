"""model.toml and study.toml: the first tier of validity (models.md § 3, § 5, § 11.2)."""

from __future__ import annotations

import re
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from femkit.core.operations import Context
from femkit.core.schema import DefinitionError
from femkit.definitions import catalogue
from femkit.models.project import load_model, load_study, model_file, study_file

LAPLACE = Path(__file__).resolve().parent / "data" / "laplace"


def examples() -> tuple[str, str]:
    """The Laplace check's model and study in today's one-file shape, until the project layout
    replaces it (plan § 3, R steps C and D)."""
    return (LAPLACE / "model.toml").read_text(), (LAPLACE / "study.toml").read_text()


@pytest.fixture
def project(tmp_path) -> Path:
    model, study = examples()
    model_file(tmp_path).write_text(model)
    study_file(tmp_path, "check").parent.mkdir(parents=True)
    study_file(tmp_path, "check").write_text(study)
    return tmp_path


def ctx() -> Context:
    return Context.from_process()


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new))


def refused_at(project: Path, *, study: bool = False) -> list[str]:
    with pytest.raises(DefinitionError) as caught:
        m = load_model(project, ctx())
        if study:
            load_study(project, "check", ctx(), m)
    return [path for path, _ in caught.value.problems]


def test_the_laplace_model_and_study_load(project):
    """Fails if the schema and the Laplace example disagree on a key."""
    m = load_model(project, ctx())
    s = load_study(project, "check", ctx(), m)
    assert sorted(m.regions) == ["domain", "left", "right", "sides"] and list(s.observables) == ["midpoint"]


def test_values_are_exact_whatever_their_spelling(project):
    """Fails if a parameter or a bare-number coordinate passes through a binary float: "500 nm"
    and "0.5 µm" must be one value, and 0.1 exactly one tenth (models.md § 2, core.md § 11)."""
    edit(model_file(project), 'bias = "1 V"', 'bias = "1 V"\na = "500 nm"\nb = "0.5 µm"\nc = "a / 2 + 1 nm"')
    edit(model_file(project), "corner = [0, 0]", "corner = [0.12345678901234567890123, 0]")  # past a float's 17 digits
    m = load_model(project, ctx())
    values = m.parameter_values(catalogue.units(ctx()))
    assert values["a"] == values["b"] and values["c"].value == Fraction(251, 10**9)
    assert m.geometry.shapes["square"].corner[0] == Decimal("0.12345678901234567890123")


def test_an_incomplete_model_loads(tmp_path):
    """Fails if a model being built — no regions, no conditions, a material not yet assigned —
    is refused instead of loading with its findings to come (models.md § 11.2)."""
    model_file(tmp_path).write_text('schema = 1\n[materials.vacuum.relative_permittivity]\nvalue = "1"\n'
                                    '[geometry.shapes.square]\nkind = "rectangle"\ncorner = [0, 0]\nsize = [1, 1]\n')
    m = load_model(tmp_path, ctx())  # no dimension, no regions, no assignment yet
    assert list(m.materials) == ["vacuum"] and m.geometry.dimension is None


@pytest.mark.parametrize("old, new, at", [
    ("sides  = { kind", "sides  = { colour = 1, kind", "regions.sides.colour"),                # an unknown key
    ('rest = true }', 'rest = true, faces_of = "square" }', "regions.sides"),                   # two selection rules
    ('{ kind = "boundary", rest = true }', '{ kind = "domain", rest = true }', "regions.sides"),  # a rule of another kind
    ('domain = "vacuum"', 'domain = "gold"', "assign.domain"),                                  # no such material
    ('left  = { kind = "potential"', 'domain = { kind = "potential"', "conditions.domain"),     # a condition on a domain
    ('bias = "1 V"', 'nm = "1 V"', "parameters.nm"),                                           # a parameter named like a unit
    ('bias = "1 V"', 'bias = "half + 1 V"\nhalf = "1 V"', "parameters.bias"),                  # a parameter used before it is defined
    ('bias = "1 V"', 'bias = "5 nmm"', "parameters.bias"),                                      # a unit the grammar does not read
    ('unit = "m"', 'unit = "V"', "frame.unit"),                                                 # a frame unit that is no length
    ("corner = [0, 0]", 'corner = ["1 V", 0]', "geometry.shapes.square.corner[0]"),            # a coordinate that is no length
    ('shapes = ["square"]', 'shapes = ["circle"]', "regions.domain.shapes[0]"),                # no such shape
])
def test_a_model_that_would_not_load_is_refused_at_the_place(project, old, new, at):
    """Fails if a wrong type, an unknown key, a quantity the grammar does not read or a name
    that refers to nothing loads — or is reported anywhere but its key path (models.md
    § 11.2, core.md § 2)."""
    edit(model_file(project), old, new)
    assert at in refused_at(project)


@pytest.mark.parametrize("old, new, at", [
    ('[axes."numerics.mesh.size"]', '[axes."frame.unit"]', 'axes.frame.unit'),           # varies neither a parameter nor numerics
    ('[axes."numerics.mesh.size"]', '[axes."parameters.gap"]', 'axes.parameters.gap'),    # a parameter the model lacks
    ('support = { point = [0.5, 0.5] }', 'support = { region = "nowhere" }', 'observables.midpoint.support.region'),
    ('unit = "V"\n', 'unit = "V"\nside = "left"\n', 'observables.midpoint.side'),          # a side that is no domain
    ('size = "0.05 m"', 'size = "0.05 V"', 'numerics.mesh.size'),                         # a mesh size that is no length
    ('gmsh"\nresources = { ranks = 1, threads = 1, gpus = 0, wall = "00:10:00"',
     'gmsh"\nresources = { ranks = 1, threads = 1, gpus = 0, wall = "10:00"',
     'environments.elmer.resources.wall'),                                                     # two parts: minutes to SLURM
])
def test_a_study_that_would_not_load_is_refused_at_the_place(project, old, new, at):
    """Fails if a study axis varies anything but a parameter or numerics, a study names an
    object its model lacks, or a size or a resource is misspelled (models.md § 5, jobs.md § 2)."""
    edit(study_file(project, "check"), old, new)
    assert at in refused_at(project, study=True)


# ------------------------------------------------------------------ the second tier: model check

def check(project: Path) -> list[str]:
    from femkit.core.operations import Context
    from femkit import registry
    op = registry.operations()["model.check"]
    return [i.subject for i in op.run(op.request_from({"project": str(project)}), Context.from_process()).issues]


def test_the_laplace_model_has_no_findings(project):
    """Fails if `model check` finds fault with the complete Laplace example."""
    assert check(project) == []


@pytest.mark.parametrize("old, new, subject", [
    ('formulation = "electrostatics"\n', "", "model:formulation"),
    ('formulation = "electrostatics"', 'formulation = "acoustics"', "model:formulation"),
    ('meaning = "per unit depth"', 'meaning = "full"', "model:geometry.meaning"),
    ('[geometry.shapes]\n', '[geometry.shapes]\nball = { kind = "sphere", center = [0, 0, 0], radius = 1 }\n',
     "model:geometry.shapes.ball"),                                               # a 3-D shape in a 2-D model
    ('[assign]\ndomain = "vacuum"\n', "", "model:regions.domain"),                  # a domain with no material
    ('sides = { kind = "insulating" }\n', "", "model:regions.sides"),               # a boundary with no condition
    ('kind = "insulating"', 'kind = "grounded"', "model:conditions.sides.kind"),    # a kind not allowed
    ('kind = "insulating"', 'kind = "interface"', "model:conditions.sides"),        # a kind for another region kind
    ('{ kind = "potential", value = "0 V" }', '{ kind = "potential" }', "model:conditions.left.value"),
    ('value = "0 V" }', 'value = "0 V", colour = "red" }', "model:conditions.left.colour"),
    ('value = "0 V" }', 'value = "0 m" }', "model:conditions.left.value"),          # a value of another dimension
    ('source = "definition of vacuum"\n', "", "model:materials.vacuum.relative_permittivity.source"),
    ('convention = "real"', 'convention = "exp(-iwt)"', "model:materials.vacuum.relative_permittivity.convention"),
    ('value = "1"\nconvention', 'value = "1 m"\nconvention', "model:materials.vacuum.relative_permittivity.value"),
    ('[materials.vacuum.relative_permittivity]', '[materials.vacuum.permeability]', "model:materials.vacuum.permeability"),
])
def test_model_check_names_what_is_missing_or_refused_by_the_formulation(project, old, new, subject):
    """Fails if `model check` passes a model that lacks a part, or asks what its formulation
    does not allow — or names anything but the object at fault (models.md § 3, § 13)."""
    edit(model_file(project), old, new)
    assert subject in check(project)
