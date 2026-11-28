"""A project's definitions (models.md § 3; ADR 0021, amended by ADR 0022): `project.toml`'s
`[definitions]`, each a typed number with its unit, written as its value or computed by a function
of `definitions.py`; that file read without running it; every constant in SI, exactly; femkit's
program in `model_prep`, its logic run here on the control environment's Python, which holds what it
imports but xarray, through which the one store writes — so what it computes and writes is the
engine tier's (tests/engine/test_person.py), and here what it refuses, writing nothing; and where the
functions run — `project check`, in memory — each failure a finding at its definition's key with its
file and line. On copies of the Laplace template; `model_prep` a prefix left as an install leaves it,
entered by a stand-in manager that runs the program on this Python (testing.md § 3)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

import pytest

from tests import kit
from tests.kit import laplace  # noqa: F401 -- a fixture
from femkit.core import text
from femkit.core.units import Quantity
from femkit.models import definitions
from femkit.projects import checking

METRE = (("length", 1),)
CHECKOUT = Path(__file__).resolve().parents[2]


def define(project: Path, table: str = "", functions: str = "") -> None:
    """Definitions of the test's own added to a project — its project file's tables, and functions
    at the end of its `definitions.py` — as the person writes them."""
    with open(project / "project.toml", "a", encoding="utf-8") as f:
        f.write("\n" + table)
    with open(project / "definitions.py", "a", encoding="utf-8") as f:
        f.write("\n" + functions)


def check(project: str = "laplace_square"):
    """`project check`'s findings: each as (code, file, key or line)."""
    return [(i.code, i.file, i.key or i.line) for i in kit.run("project.check", project=project).issues]


def frame(folder: Path, compute: bool = False) -> checking.Checking:
    """The check frame of the project at ``folder``, its definitions resolved as `project check`
    resolves them (``compute``) or as every other reader does."""
    opened = kit.opened(folder)
    return checking.Checking.of(opened, kit.ctx(), definitions.defined(opened, kit.ctx(), compute=compute))


# ------------------------------------------------------------------ the table

@pytest.mark.parametrize("table, code, key", [
    ('[definitions.x]\ntype = "float"\nvalue = 1\nfunction = "x"\nunit = "m"\n', "value-or-function",
     "definitions.x"),
    ('[definitions.x]\ntype = "float"\nunit = "m"\n', "value-or-function", "definitions.x"),
    ('[definitions.x]\ntype = "int"\nvalue = 4.5\nunit = "1"\n', "wrong-type", "definitions.x.value"),
    ('[definitions.x]\ntype = "float"\nvalue = [1, 2]\nunit = "m"\n', "wrong-type", "definitions.x.value"),
    ('[definitions.x]\ntype = "float"\nvalue = inf\nunit = "m"\n', "wrong-type", "definitions.x.value"),
    ('[definitions.x]\ntype = "complex"\nvalue = [1]\nunit = "V"\n', "wrong-type", "definitions.x.value"),
    ('[definitions.x]\ntype = "int"\nvalue = 4\nunit = "m"\n', "bad-unit", "definitions.x.unit"),
    ('[definitions.x]\ntype = "float"\nvalue = 1\nunit = "furlong"\n', "bad-unit", "definitions.x.unit"),
    ('[definitions.x]\ntype = "float"\nvalue = 1\nunit = "2 m"\n', "bad-unit", "definitions.x.unit"),
    ('[definitions.x]\ntype = "float"\nvalue = 1\nunit = "m + m"\n', "bad-unit", "definitions.x.unit"),
    ('[definitions.x]\ntype = "float"\nfunction = "nowhere"\nunit = "m"\n', "no-such-function",
     "definitions.x.function"),
], ids=["both", "neither", "an int not whole", "a float as a list", "a float not finite", "a complex not a pair",
        "an int with a unit", "a unit not in the table", "a unit with a number", "a unit that is a sum",
        "a function the file lacks"])
def test_each_rule_of_a_definition_is_a_finding_at_its_key(laplace, table, code, key):
    """Fails if a definition breaking a rule checked before anything runs — both or neither of
    `value` and `function`, a value not of its type, a unit outside the table or not a product of
    its units, an `int`'s unit other than `1`, a function the file lacks — is not a finding at its
    key in the project file (models.md § 3: "Checked before anything runs, each a finding at the
    definition or the line")."""
    define(laplace, table)
    assert (code, "project.toml", key) in check()


@pytest.mark.parametrize("kind, value, said", [
    ("float", '"10 nm"', "a number of its type (`float`); its unit is written apart, in `unit`"),
    ("float", "true", "a number of its type (`float`); its unit is written apart, in `unit`"),
    ("int", "4.5", "a whole number of its type (`int`); its unit is written apart, in `unit`"),
    ("complex", '"1 + 2i"', "a pair of numbers of its type (`complex`), `[real, imaginary]`; its unit is written "
                            "apart, in `unit`"),
], ids=["a float as a quantity's text", "a float as a truth value", "an int not whole", "a complex as text"])
def test_a_value_not_of_its_type_says_so_in_plain_words_and_the_project_file_loads(laplace, kind, value, said):
    """Fails if a definition's value not of its type stops the project file loading, or is said in
    pydantic's own words ("Input should be an instance of …") rather than a finding at its key in
    plain words: a number of its type, its unit written apart (models.md § 3: "a value not of its
    type"; core.md § 2: "A problem's reason is a sentence for a person, never pydantic's words")."""
    define(laplace, f'[definitions.x]\ntype = "{kind}"\nvalue = {value}\nunit = "1"\n')
    issues = kit.run("project.check", project="laplace_square").issues
    assert not [i for i in issues if i.code == "unloadable"]
    (wrong,) = [i for i in issues if i.key == "definitions.x.value"]
    assert wrong.code == "wrong-type" and said in wrong.message and "Input should" not in wrong.message


@pytest.mark.parametrize("kind, value", [("float", "10"), ("float", "0.5"), ("int", "4"), ("int", "4.0")])
def test_a_whole_number_is_a_float_and_a_whole_number_written_with_a_point_an_int(laplace, kind, value):
    """Fails if a whole number written for a `float`, or a whole number for an `int` — written `4`
    or `4.0`, each the number 4 — is a finding (models.md § 3: "an `int` holds a whole number, a
    `float` may be written `10` and is a double")."""
    define(laplace, f'[definitions.x]\ntype = "{kind}"\nvalue = {value}\nunit = "1"\n')
    assert not [c for c in check() if c[2] and str(c[2]).startswith("definitions.x")]


def test_each_constant_reaches_the_parts_in_si_exactly_and_an_int_and_a_complex_as_typed(laplace):
    """Fails if a constant is not its written value in SI, exactly — a length in metres, an angle
    in degrees, read from its decimal text, never a binary float — if an `int` written `4` is not
    the count 4, or a complex one is a value a real field may name (models.md § 3:
    "every constant converted ... into SI ... a plain number of its type"; core.md § 11)."""
    define(laplace, '[definitions.gap]\ntype = "float"\nvalue = 10.1\nunit = "nm"\n\n'
                    '[definitions.tilt]\ntype = "float"\nvalue = 0.5\nunit = "deg"\n\n'
                    '[definitions.layers]\ntype = "int"\nvalue = 4\nunit = "1"\n\n'
                    '[definitions.amplitude]\ntype = "complex"\nvalue = [1, 0.5]\nunit = "V/m"\n')
    c = frame(laplace)
    assert c.definitions["gap"] == Quantity(Fraction(101, 10 ** 10), METRE)
    assert c.definitions["tilt"] == Quantity(Fraction(1, 2), (("angle", 1),))
    assert c.definitions["layers"] == Quantity(Fraction(4))
    assert c.definitions["side"] == Quantity(Fraction(1), METRE)
    assert "amplitude" in c.complex and "amplitude" not in c.definitions
    kit.rewrite(laplace / "mesh" / "uniform.toml", 'size = {value = 0.1, unit = "m"}', 'size = "amplitude"')
    assert ("bad-quantity", "mesh/uniform.toml", "size") in check()


# ------------------------------------------------------------------ definitions.py, read without running it

def test_definitions_py_is_read_without_running_it_each_fault_at_its_line(laplace, tmp_path):
    """Fails if `definitions.py` is run to be checked — a statement at its top level would leave its
    mark — or if a statement at its top level that is no import or function, an import of what
    `model_prep` does not provide, a definition's function that takes arguments, or a `defs.<name>`
    naming no definition is not a finding at the file and its line (models.md § 3: "anything at
    the file's top level but imports and functions", "an import of anything but
    project.definitions, numpy, scipy, math and cmath", "a `defs.<name>` naming no definition";
    core.md § 10, a finding's line)."""
    mark = tmp_path / "ran"
    define(laplace, '[definitions.half]\ntype = "float"\nfunction = "half"\nunit = "m"\n\n'
                    '[definitions.third]\ntype = "float"\nfunction = "third"\nunit = "m"\n',
           f"open({str(mark)!r}, 'w')\nimport os\nfrom scipy import constants as c\nimport math\n\n\n"
           "def half():\n    return defs.side / 2 + defs.sied\n\n\ndef third(n):\n    return defs.side / n\n")
    lines = (laplace / "definitions.py").read_text().splitlines()
    at = {text: lines.index(text) + 1 for text in (f"open({str(mark)!r}, 'w')", "import os",
                                                   "    return defs.side / 2 + defs.sied", "def third(n):")}
    found = check()
    assert ("top-level", "definitions.py", at[f"open({str(mark)!r}, 'w')"]) in found
    assert ("bad-import", "definitions.py", at["import os"]) in found
    assert ("no-such-definition", "definitions.py", at["    return defs.side / 2 + defs.sied"]) in found
    assert ("takes-arguments", "definitions.py", at["def third(n):"]) in found
    assert [c for c, _, _ in found].count("bad-import") == 1          # scipy and math are allowed
    assert not mark.exists()
    shown = text.findings(kit.run("project.check", project="laplace_square").issues)
    assert f"definitions.py, line {at['import os']}" in [line.strip() for line in shown], shown


def test_computed_definitions_are_ordered_by_their_reads_through_each_function_called_and_a_circle_is_a_finding(
        laplace):
    """Fails if a computed definition is not computed after every one its function reads — through
    a function of the file it calls — or definitions computed from each other in a circle are not
    one finding naming the circle, at the key where it was met (models.md § 3: "each function's
    `defs.<name>` reads give the order and the circles")."""
    define(laplace, '[definitions.outer]\ntype = "float"\nfunction = "outer"\nunit = "m"\n\n'
                    '[definitions.inner]\ntype = "float"\nfunction = "inner"\nunit = "m"\n\n'
                    '[definitions.a]\ntype = "float"\nfunction = "a"\nunit = "m"\n\n'
                    '[definitions.b]\ntype = "float"\nfunction = "b"\nunit = "m"\n',
           "def helper():\n    return defs.inner * 2\n\n\ndef outer():\n    return helper()\n\n\n"
           "def inner():\n    return defs.side / 4\n\n\ndef a():\n    return defs.b\n\n\ndef b():\n    return defs.a\n")
    d = definitions.declared(kit.opened(laplace), kit.ctx())
    assert d.order == ("inner", "outer")
    circles = [i for i in check() if i[0] == "definition-circle"]
    assert circles == [("definition-circle", "project.toml", "definitions.a")]


def test_the_templates_definitions_py_holds_its_header_and_a_copy_takes_it(laplace):
    """Fails if a template's copy does not hold `definitions.py`, its header importing
    `project.definitions` as `defs` beside numpy and scipy's constants, or if that header is a
    finding (projects.md § 2: "its header written once by the template")."""
    held = definitions.held(kit.opened(laplace))
    assert held is not None
    written = definitions.read(held.data.decode(), definitions.provided(kit.ctx()))
    assert written.faults == () and written.functions == {}
    assert any(line.startswith("import project.definitions as defs") for line in held.data.decode().splitlines())
    assert not [i for i in check() if i[1] == "definitions.py"]


def test_a_project_without_definitions_py_has_no_finding_for_it(laplace):
    """Fails if a project with no computed definition and no `definitions.py` has a finding for the
    missing file: the file is optional (projects.md § 2)."""
    (laplace / "definitions.py").unlink()
    assert not [i for i in check() if "definitions" in (i[1] or "") or i[0] == "missing-file"]


# ------------------------------------------------------------------ femkit's program in model_prep

PROGRAM = "femkit.engines.person.definitions"


def program(work: Path, file: str, document: dict) -> subprocess.CompletedProcess:
    """femkit's program, run on this Python as `model_prep` runs it, in ``work`` holding the
    person's ``file`` and the ``document`` femkit writes."""
    (work / "definitions.py").write_text(file)
    (work / "document.json").write_text(json.dumps(document))
    return subprocess.run([sys.executable, "-P", "-m", PROGRAM, "document.json", "values.nc"], cwd=work,
                          capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(CHECKOUT)})


def said(result) -> dict:
    """The program's last line, its failures."""
    return json.loads(result.stdout.strip().splitlines()[-1])


def document(definitions_: dict, order: list[str], sets: list[dict]) -> dict:
    """The document femkit hands the program, in its one shape (`program.document`)."""
    from femkit.engines.person import definitions as program_
    return program_.document("definitions.py", definitions_, order, sets,
                             {"study": "check", "script_sha256": "a" * 64, "definitions_sha256": "b" * 64,
                              "environment": "model_prep", "fingerprint": "c" * 64})


@pytest.mark.parametrize("kind, body, reason", [
    ("int", "    return 2.5", "returned 2.5, which is no whole number, and an `int` is one"),
    ("float", "    return float('nan')", "returned nan, which is no finite number"),
    ("float", "    return defs.gap / 0", "raised ZeroDivisionError"),
    ("float", "    return np.array([1.0])", "which is no float"),
], ids=["a float for an int", "not finite", "an exception", "an array"])
def test_a_result_not_a_finite_number_of_its_type_is_a_failure_at_its_line_and_nothing_is_written(tmp_path, kind,
                                                                                                    body, reason):
    """Fails if a function's result that is no finite number of its definition's type, or an
    exception it raises, is not a failure naming its definition and the line of the person's file;
    if a definition reading one that failed is called anyway; or if anything is written (models.md
    § 3: "When it runs, each at the file and the line: a result not a finite number of its declared
    type, an exception")."""
    file = "import numpy as np\nimport project.definitions as defs\n\n\ndef bad():\n" + body + \
           "\n\n\ndef after():\n    return defs.bad * 2\n"
    spec = {"gap": {"type": "float", "units": "m", "declared_unit": "m"},
            "bad": {"type": kind, "units": "m", "declared_unit": "m", "function": "bad", "line": 5, "needs": []},
            "after": {"type": "float", "units": "m", "declared_unit": "m", "function": "after", "line": 9,
                      "needs": ["bad"]}}
    result = program(tmp_path, file, document(spec, ["bad", "after"], [{"gap": 1.0}, {"gap": 2.0}]))
    (failure,) = said(result)["failures"]
    assert result.returncode == 1 and not (tmp_path / "values.nc").exists()
    assert failure["definition"] == "bad" and failure["point"] == 0 and reason in failure["reason"]
    assert failure["line"] == 6


# ------------------------------------------------------------------ where they run: project check

COMPUTED = ('[definitions.half]\ntype = "float"\nfunction = "half"\nunit = "m"\n',
            "def half():\n    return defs.side / 2\n")


def test_a_computed_definition_checked_where_model_prep_is_not_installed_names_its_install(laplace):
    """Fails if `project check` of a project with a computed definition, where `model_prep` is not
    installed, does not say so in a finding naming its install, as the environment's table gives
    an absent one's next steps — or tries to run it (models.md § 3; envs.md § 3.3: "one `envs`
    check refuses any other state with that state's own next steps")."""
    define(laplace, *COMPUTED)
    (found,) = [i for i in kit.run("project.check", project="laplace_square").issues if i.code == "not-allowed"]
    assert found.subject == "model_prep" and found.severity == "error"
    assert {a.call.operation for a in found.next} == {"env.install"}
    assert all(a.call.request["names"] == ["model_prep"] for a in found.next)


def test_a_value_naming_a_computed_definition_not_at_hand_rests_on_its_finding(laplace):
    """Fails if a value naming a computed definition whose value is not at hand — `model_prep` not
    installed — is a finding of its own at its key, rather than resting on the one that says why
    (projects.md § 6; models.md § 3: "a computed value not at hand ... one finding says why";
    core.md § 11: a quantity may be a definition's name)."""
    define(laplace, *COMPUTED)
    kit.rewrite(laplace / "mesh" / "uniform.toml", 'size = {value = 0.1, unit = "m"}', 'size = "half"')
    found = check()
    assert "not-allowed" in [code for code, _, _ in found]
    assert not [f for f in found if f[1] == "mesh/uniform.toml"]


@pytest.fixture
def model_prep(laplace, running_manager):
    """`model_prep` left as an install leaves it, entered by the stand-in manager, which runs what it
    is asked to on this Python — which holds numpy and netCDF4, what femkit's program imports there,
    but not scipy: the Laplace copy's `definitions.py` imports no scipy here."""
    kit.installed("model_prep", outcomes=[])   # ready: no check to run, its validate recorded
    kit.rewrite(laplace / "definitions.py", "from scipy import constants\n", "")
    return running_manager


def test_an_int_refuses_a_number_not_whole_both_written_and_returned(laplace, model_prep):
    """Fails if an `int` definition written `4.5`, or computed by a function returning `4.5`, is not
    a finding at its definition: the table's check and the program in `model_prep` hold an `int` to
    one rule, the whole number it takes however written being the engine tier's to show computed
    (models.md § 3: "an `int` holds a whole number ... a result not a finite number of its declared
    type")."""
    define(laplace, '[definitions.layers]\ntype = "int"\nvalue = 4.5\nunit = "1"\n\n'
                    '[definitions.count]\ntype = "int"\nfunction = "count"\nunit = "1"\n',
                    "def count():\n    return 4.5\n")
    found = {(code, key) for code, _, key in check()}
    assert {("wrong-type", "definitions.layers.value"), ("function-failed", "definitions.count")} <= found


def test_a_call_past_the_time_limit_is_a_finding_at_its_definition(definitions, laplace, model_prep):
    """Fails if a function that does not return within the time limit the declaration of femkit's
    program in `model_prep` states is not stopped there, and said as a finding at its definition's
    key (models.md § 3: "a call past the time limit ... a finding at the definition's key", "within
    the time limit its declaration states")."""
    kit.rewrite(definitions / "programs.toml", "timeout = 60", "timeout = 1")
    define(laplace, COMPUTED[0], "def half():\n    while True:\n        pass\n")
    started = time.monotonic()
    (failure,) = [i for i in kit.run("project.check", project="laplace_square").issues if i.code == "function-failed"]
    assert failure.key == "definitions.half" and "within 1 s" in failure.message
    assert time.monotonic() - started < 30           # stopped at the declared second, far below any other limit


def test_a_definition_resting_on_a_fault_of_the_file_is_not_run(laplace, model_prep):
    """Fails if femkit runs `definitions.py` while a fault of the file — an import it may not make —
    stands: the file is checked before anything runs (models.md § 3)."""
    define(laplace, *COMPUTED)
    with open(laplace / "definitions.py", "a") as f:
        f.write("\nimport os\n")
    check()
    assert not model_prep.exists() or "run --no-capture-output" not in model_prep.read_text()


def test_an_axis_sweeps_a_definition_written_as_its_value_never_a_computed_one(laplace):
    """Fails if an axis of a computed definition is not a finding at its key — what is computed
    from a swept constant is computed again by its function — or an axis of a constant is
    (models.md § 3: "an axis sweeps a constant, never a computed definition")."""
    define(laplace, *COMPUTED)
    study = laplace / "studies" / "check.toml"
    kit.rewrite(study, '[axes."mesh:uniform:size"]', '[axes."project:definitions.half"]')
    assert ("bad-axis", "studies/check.toml", 'axes."project:definitions.half"') in check()
    kit.rewrite(study, '[axes."project:definitions.half"]', '[axes."project:definitions.side"]')
    assert not [i for i in check() if i[1] == "studies/check.toml" and i[0].startswith("bad-axis")]
