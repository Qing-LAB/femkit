"""A project's computed definitions run in the person's `model_prep` (models.md § 3; testing.md
§ 1): femkit's program there, through the environment's own `run`, from the clean start, its functions reading
numpy and scipy, its values kept as `project check` and `study prep` read them."""

from __future__ import annotations

import math
from fractions import Fraction

from femkit.models import definitions
from femkit.projects import checking
from tests import kit

TABLE = ('\n[definitions.circle]\ntype = "float"\nfunction = "circle"\nunit = "m"\n\n'
         '[definitions.root]\ntype = "float"\nfunction = "root"\nunit = "m"\n\n'
         '[definitions.turns]\ntype = "int"\nfunction = "turns"\nunit = "1"\n\n'
         '[definitions.phase]\ntype = "complex"\nfunction = "phase"\nunit = "V"\n')
FUNCTIONS = ("\n\ndef circle():\n    return constants.pi * defs.side\n\n\n"
             "def root():\n    return float(np.sqrt(defs.circle * defs.side / constants.pi))\n\n\n"
             "def turns():\n    return np.int64(defs.side * 3)\n\n\n"
             "def phase():\n    return defs.bias * np.exp(1j * constants.pi / 2)\n")


def test_project_check_runs_the_functions_in_model_prep_with_numpy_and_scipy(tmp_path):
    """Fails if a project's computed definitions — reading numpy and scipy, each in its order — do
    not run in the person's `model_prep` through femkit's program, each value of its type in SI as
    its function returned it, with no finding of `project check` (models.md § 3)."""
    folder = kit.copy_template(tmp_path / "projects", "laplace_square")
    with open(folder / "project.toml", "a") as f:
        f.write(TABLE)
    with open(folder / "definitions.py", "a") as f:
        f.write(FUNCTIONS)
    found = [i for i in kit.run("project.check", project="laplace_square").issues if i.severity == "error"]
    assert found == [], found
    opened = kit.opened(folder)
    c = checking.Checking.of(opened, kit.ctx(), definitions.defined(opened, kit.ctx(), compute=True))
    assert c.definitions["circle"].value == Fraction(math.pi)
    assert c.definitions["root"].value == 1 and c.definitions["turns"].value == 3
    assert "phase" in c.complex
