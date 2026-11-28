"""femkit's programs for the person's Python inside the environments that hold xarray (models.md § 3;
framework.md § 5; testing.md § 1): the one store's writer, through xarray in `model_prep`, its file
read back by the one reader in the control process; the one check of an array a function returns,
in `postprocess`; and `project check` computing a project's definitions through them."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from femkit.core import persist
from femkit.core.units import Quantity
from femkit.engines.person import definitions as program
from femkit.models import definitions
from femkit.projects import checking
from tests import kit

CHECKOUT = Path(__file__).resolve().parents[2]

FILE = """import math
import numpy as np
import project.definitions as defs


def half():
    return defs.gap / 2


def doubled():
    return defs.amplitude * 2


def count():
    return np.int64(defs.layers * 3)
"""

SPEC = {"gap": {"type": "float", "units": "m", "declared_unit": "nm", "long_name": "the gap"},
        "layers": {"type": "int", "units": "1", "declared_unit": "1", "long_name": "layers"},
        "amplitude": {"type": "complex", "units": "kg m s^-3 A^-1", "declared_unit": "V/m", "long_name": "amplitude"},
        "half": {"type": "float", "units": "m", "declared_unit": "nm", "long_name": "half the gap", "function": "half",
                 "line": 6, "needs": []},
        "doubled": {"type": "complex", "units": "kg m s^-3 A^-1", "declared_unit": "V/m", "long_name": "doubled",
                    "function": "doubled", "line": 10, "needs": []},
        "count": {"type": "int", "units": "1", "declared_unit": "1", "long_name": "count", "function": "count",
                  "line": 14, "needs": []}}
ATTRIBUTES = {"study": "check", "script_sha256": "a" * 64, "definitions_sha256": "b" * 64,
              "environment": "model_prep", "fingerprint": "c" * 64}


def test_the_program_keeps_each_set_through_the_one_store_with_its_metadata_and_no_time(tmp_path):
    """Fails if femkit's program in `model_prep` does not keep, along `point`, one variable per
    constant and per computed definition of its declared type — a complex one by netCDF4's
    convention — its values in SI with `units`, `declared_unit`, `long_name` and its declared type,
    the file's `schema` and provenance as its attributes and no time — read back by the one reader —
    or if the same values written twice are not the same bytes (models.md § 3: "One store …
    the same result is the same bytes"; "The kept values")."""
    sets = [{"gap": 1e-8, "layers": 2, "amplitude": [1.0, 0.5]}, {"gap": 3e-8, "layers": 5, "amplitude": [0.0, -1.0]}]
    (tmp_path / "definitions.py").write_text(FILE)
    (tmp_path / "document.json").write_text(json.dumps(program.document(
        "definitions.py", SPEC, ["half", "doubled", "count"], sets, ATTRIBUTES)))
    argv = ["python", "-P", "-m", program.__name__, "document.json", "values.nc"]
    first = kit.inside("model_prep", argv, tmp_path, checkout=True)
    assert first.ok, first.stdout
    once = (tmp_path / "values.nc").read_bytes()
    assert kit.inside("model_prep", argv, tmp_path, checkout=True).ok
    assert (tmp_path / "values.nc").read_bytes() == once
    held = persist.read_record(tmp_path / "values.nc", definitions.KeptValues)
    assert held.reads, held.problem
    assert held.value.entries() == [
        {"gap": 1e-8, "layers": 2, "amplitude": 1 + 0.5j, "half": 5e-9, "doubled": 2 + 1j, "count": 6},
        {"gap": 3e-8, "layers": 5, "amplitude": -1j, "half": 1.5e-8, "doubled": -2j, "count": 15}]
    assert held.value.rests_on() == ATTRIBUTES
    assert {n: v.attributes for n, v in held.value.variables.items()} == {
        n: {"units": s["units"], "declared_unit": s["declared_unit"], "long_name": s["long_name"],
            "declared_type": s["type"]} for n, s in SPEC.items()}


ARRAY = """
import sys, numpy, xarray
from femkit.engines.person import values
line = xarray.DataArray(numpy.array([1.0, 2.0]), dims=("x",), coords={"x": [0.0, 1e-9]})
said = {}
for name, value, dims in [("kept", line, {"x": "nm"}), ("other dims", line, {"y": "nm"}),
                          ("no coordinate", xarray.DataArray(numpy.array([1.0]), dims=("x",)), {"x": "nm"}),
                          ("not finite", line * numpy.inf, {"x": "nm"}), ("a number", 1.0, {"x": "nm"}),
                          ("an array where a number is declared", line, None)]:
    try:
        values.checked("float", value, 3, dims)
        said[name] = "kept"
    except values.Failed as exc:
        said[name] = exc.reason
print(__import__("json").dumps(said))
"""


def test_an_array_returned_is_held_to_its_declared_dimensions_each_with_a_coordinate_every_value_finite(tmp_path):
    """Fails if the one check of a typed value keeps an array not over exactly the dimensions its
    declaration names, one without a coordinate for each, one holding a value that is not finite, a
    number where an array is declared, or an array where a number is (models.md § 3: "One check
    holds what a function returns to its declaration — its type, its dimensions by name, a
    coordinate for each, every value finite")."""
    result = kit.inside("postprocess", ["python", "-P", "-c", ARRAY], tmp_path, checkout=True)
    assert result.ok, result.stdout
    said = json.loads(result.stdout.strip().splitlines()[-1])
    assert said["kept"] == "kept"
    assert all(said[n] != "kept" for n in said if n != "kept"), said


COMPUTED = ('[definitions.half]\ntype = "float"\nfunction = "half"\nunit = "m"\n',
            "def half():\n    return defs.side / 2\n")


def define(project: Path, table: str = "", functions: str = "") -> None:
    with open(project / "project.toml", "a", encoding="utf-8") as f:
        f.write("\n" + table)
    with open(project / "definitions.py", "a", encoding="utf-8") as f:
        f.write("\n" + functions)


def test_project_check_computes_each_function_and_says_a_failure_at_its_key_with_its_file_and_line(tmp_path):
    """Fails if `project check` does not run a project's computed definitions in `model_prep` — a
    value its function returns reaching every check that reads it, a whole number returned for an
    `int` the count it holds, a failure a finding at the definition's key with its file and line
    said — or writes anything into the project (models.md § 3: "in `project check`, which computes
    and validates them and writes nothing")."""
    laplace = kit.copy_template(tmp_path / "projects", "laplace_square")
    define(laplace, COMPUTED[0] + '\n[definitions.count]\ntype = "int"\nfunction = "count"\nunit = "1"\n',
           COMPUTED[1] + "\n\ndef count():\n    return 4.0\n")
    kit.rewrite(laplace / "definitions.py", "return defs.side / 2", "return defs.side / 2 - 1")
    kit.rewrite(laplace / "mesh" / "uniform.toml", 'size = {value = 0.1, unit = "m"}', 'size = "half"')
    before = kit.tree(laplace)
    found = [(i.code, i.file, i.key) for i in kit.run("project.check", project=laplace.name).issues]
    assert ("out-of-range", "mesh/uniform.toml", "size") in found       # 1/2 m - 1 m: the computed value used
    assert kit.tree(laplace) == before
    opened = kit.opened(laplace)
    c = checking.Checking.of(opened, kit.ctx(), definitions.defined(opened, kit.ctx(), compute=True))
    assert c.definitions["count"] == Quantity(Fraction(4))
    kit.rewrite(laplace / "definitions.py", "return defs.side / 2 - 1", "return defs.side / 0")
    (failure,) = [i for i in kit.run("project.check", project=laplace.name).issues if i.code == "function-failed"]
    line = (laplace / "definitions.py").read_text().splitlines().index("    return defs.side / 0") + 1
    assert (failure.file, failure.key) == ("project.toml", "definitions.half")
    assert "ZeroDivisionError" in failure.message and f"definitions.py, line {line}" in failure.message
