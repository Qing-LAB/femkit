"""A study is the problem's design and names no engine; its observables come after it (ADR 0025;
models.md §§ 2, 5.1, 5.2, 11; projects.md § 4): a file writing `engine` told the engine is chosen
when the study is solved; the engines that can solve a study shown as a fact, and alone offered as
the engine its prep asks for; each part kind's second shape, an earlier one told what changed; the mesh recipe's `mesher`;
the observables part — a folder, its file and its script read without running it, ranked after
the studies it reads, the wire from each study to it; and an error in it holding back nothing a
study makes. On copies of the templates."""

from __future__ import annotations

import pytest

from femkit.core.errors import Refused
from tests import kit
from tests.kit import laplace, slab  # noqa: F401 -- fixtures

STUDY = "studies/check.toml"
PART = "observables/midpoint"


def checked(name: str = "laplace_square"):
    """`project check` of the project ``name``."""
    return kit.run("project.check", project=name)


def at(result, code: str, file: str | None = None, key: str | None = None) -> list:
    """The findings of ``code``, at ``file`` and ``key`` where given."""
    return [i for i in result.issues if i.code == code and (file is None or i.file == file)
            and (key is None or i.key == key)]


def state(result, part: str) -> str:
    """A part's state, as `project check`'s table gives it."""
    return {r.part: r.state for r in result.parts}[part]


# ------------------------------------------------------------------ a study names no engine

def test_a_study_writing_engine_is_told_the_engine_is_chosen_when_it_is_solved(laplace):
    """Fails if a study's file that writes `engine` loads, or is not one finding at `engine` saying
    that the engine is chosen when the study is solved, with the command that chooses it (models.md
    § 5.1: "A study's file that writes `engine` does not load: its finding, at `engine`, says that
    the engine is chosen when the study is solved, and the command that chooses it"; ADR 0025
    decision 1)."""
    kit.rewrite(laplace / STUDY, 'component = "square"', 'component = "square"\nengine = "elmer"')
    (found,) = at(checked(), "unloadable", STUDY, "engine")
    assert "chosen when the study is solved" in found.message
    assert "femkit study prep STUDY --engine ENGINE" in found.message
    assert kit.opened(laplace).parts["study:check"].data is None


def test_the_engines_that_can_solve_a_study_are_a_fact_of_project_check_and_study_list(laplace):
    """Fails if `project check` and `study list` do not show, for each study, the engines that can
    solve it — each an engine a hand-over gives the mesh its recipe's mesher writes at each geometry
    order of its cases: Gmsh's at order 1 both Elmer and NGSolve, at order 2 Elmer alone — or if an
    engine that cannot is a finding, since no engine is chosen in the file (models.md §§ 5.1, 11.1;
    workflow.md § 2.2)."""
    def engines():
        rows = {r.part: r for r in checked().parts}
        listed = {s.name: s for s in kit.run("study.list", project="laplace_square").studies}
        return rows["study:check"].engines, listed["check"].engines

    assert engines() == (["elmer", "ngsolve"], ["elmer", "ngsolve"])
    kit.rewrite(laplace / "mesh/uniform.toml", "order = 1", "order = 2")
    assert engines() == (["elmer"], ["elmer"])
    assert not at(checked(), "no-input") and {r.part: r.state for r in checked().parts}["study:check"] != "errors"


def test_the_prep_a_study_offers_asks_for_one_of_the_engines_that_can_solve_it(laplace):
    """Fails if the `study prep` a study's state offers — the part's next step in `project check`,
    `study list` and the graph, as the page's prepare action — does not ask for the engine that solves
    it, a fill of the request's `engine` which may be left unset, its choices the engines that can
    solve the study, by the one rule `study.solvers` — at order 1 Elmer and NGSolve, at order 2 Elmer
    alone — never every engine femkit declares, which the command line would refuse (workflow.md § 7:
    "its choices are the engines that can solve the study, by the one rule `solvers` … the page offers
    no engine the command line would refuse"; core.md § 7; web.md § 7.2)."""
    def offered() -> list[list[str] | None]:
        (prep,) = checked().next
        (listed,) = kit.run("study.list", project="laplace_square").next
        node = next(n for n in kit.run("project.graph", project="laplace_square").graph.nodes
                    if n.address == "study:check")
        out = []
        for action in (prep, listed, *node.actions):
            (fill,) = action.fills
            assert action.call.operation == "study.prep" and (fill.field, fill.required) == ("engine", False)
            out.append(next((s["enum"] for s in [fill.json_schema, *fill.json_schema.get("anyOf", ())]
                             if "enum" in s), None))
        return out

    assert offered() == [["elmer", "ngsolve"]] * 3
    kit.rewrite(laplace / "mesh/uniform.toml", "order = 1", "order = 2")
    assert offered() == [["elmer"]] * 3


# ------------------------------------------------------------------ the second shapes

@pytest.mark.parametrize("file, what", [
    (STUDY, "environments"),
    ("mesh/uniform.toml", "mesher"),
    (f"{PART}/observables.toml", "observe.py"),
])
def test_a_file_of_an_earlier_shape_is_told_what_changed(laplace, file, what):
    """Fails if a study's, a recipe's or an observables part's file stating its first shape,
    `schema = 1`, is not one finding at `schema` naming the shape it states, the one femkit reads,
    and what changed between them (models.md § 2)."""
    kit.rewrite(laplace / file, "schema = 2", "schema = 1")
    (found,) = at(checked(), "unloadable", file, "schema")
    assert "shape 1" in found.message and "schema = 2" in found.message and what in found.message


def test_a_recipe_states_the_mesher_that_makes_its_mesh(laplace):
    """Fails if a recipe naming a mesher femkit does not declare is not a finding at its `mesher`,
    the meshers its choices (geometry.md § 6)."""
    kit.rewrite(laplace / "mesh/uniform.toml", 'mesher = "gmsh"', 'mesher = "gmhs"')
    (found,) = at(checked(), "no-such-mesher", "mesh/uniform.toml", "mesher")
    assert set(found.choices) == {'"gmsh"', '"given"'}


# ------------------------------------------------------------------ the observables part

def test_an_observables_part_of_its_first_shape_is_told_it_is_now_a_folder(laplace):
    """Fails if a file of the observables part's first shape, `observables/<o>.toml`, is left a stray
    or read, rather than told, as an error, that the part is now a folder holding `observables.toml`
    and `observe.py` (projects.md § 4)."""
    (laplace / "observables" / "old.toml").write_text("schema = 1\n")
    result = checked()
    (found,) = at(result, "now-a-folder", "observables/old.toml")
    assert found.severity == "error" and "observables/old/" in found.message and "observe.py" in found.message
    assert not at(result, "stray", "observables/old.toml")


OBSERVABLES, SCRIPT = f"{PART}/observables.toml", f"{PART}/observe.py"


@pytest.mark.parametrize("file, old, new, code, where", [
    (OBSERVABLES, 'studies = ["check"]', 'studies = ["check", "nowhere"]',
     "no-such-part", (OBSERVABLES, "studies")),
    (OBSERVABLES, 'function = "potential_middle"', 'function = "potential_centre"', "no-such-function",
     (OBSERVABLES, "observables.potential_middle.function")),
    (SCRIPT, "def potential_middle(case):", "def potential_middle(case, where):", "takes-arguments",
     (OBSERVABLES, "observables.potential_middle.function")),
    (OBSERVABLES, 'definitions = ["side"]', 'definitions = ["sid"]', "no-such-definition",
     (OBSERVABLES, "observables.potential_middle.takes.definitions")),
    (OBSERVABLES, '# groups = ["left"]', 'groups = ["top"]', "not-promised",
     (OBSERVABLES, "observables.potential_middle.takes.groups")),
    (OBSERVABLES, 'unit = "V"', 'unit = "Volt"', "bad-unit", (OBSERVABLES, "observables.potential_middle.unit")),
    (OBSERVABLES, 'type = "float"', 'type = "int"', "bad-unit", (OBSERVABLES, "observables.potential_middle.unit")),
    (SCRIPT, "def potential_middle(case):", "import os\n\n\ndef potential_middle(case):", "bad-import",
     (SCRIPT, None)),
    (SCRIPT, "def potential_middle(case):", "THRESHOLD = 1\n\n\ndef potential_middle(case):", "top-level",
     (SCRIPT, None)),
])
def test_an_observables_part_is_checked_before_anything_runs(laplace, file, old, new, code, where):
    """Fails if an observables part naming a study the project lacks, an observable whose function
    `observe.py` lacks or that takes other than one argument, which takes a definition the project
    lacks or a group the component of a study it reads does not promise, whose unit does not read
    or an `int`'s that is not `1`, or an `observe.py` importing what neither `postprocess` nor its
    project's packages give, or running a statement at its top level, is not a finding at its key or
    line — `observe.py` read without running it (models.md §§ 5.2, 13)."""
    kit.rewrite(laplace / file, old, new)
    assert at(checked(), code, *where), [(i.code, i.file, i.key) for i in checked().issues]


def test_an_observables_part_may_import_what_its_project_declares(laplace):
    """Fails if `observe.py` may not import a module its project's packages give, by the name the
    project states it is imported by (models.md §§ 2, 5.2)."""
    kit.rewrite(laplace / f"{PART}/observe.py", "def potential_middle(case):",
                "import skimage\n\n\ndef potential_middle(case):")
    assert at(checked(), "bad-import", f"{PART}/observe.py")
    with (laplace / "project.toml").open("a") as f:
        f.write('\n[postprocess]\npackages = [{ conda = "scikit-image", module = "skimage" }]\n')
    assert not at(checked(), "bad-import", f"{PART}/observe.py")


def test_a_forbidden_import_in_observe_py_says_what_would_be_right(laplace):
    """Fails if an import `observe.py` may not make is not a finding at its line that says what would
    be right — its package named in the project file's `[postprocess] packages`, with the line to
    write — or a module of Python's own standard library, which no package brings, or a script whose
    environment takes no project's packages, `definitions.py`, is told so (models.md §§ 2, 5.2;
    core.md § 10: a finding says what would be right)."""
    kit.rewrite(laplace / SCRIPT, "def potential_middle(case):",
                "import skimage.filters\nimport os\n\n\ndef potential_middle(case):")
    found = {(laplace / SCRIPT).read_text().splitlines()[i.line - 1]: i for i in at(checked(), "bad-import", SCRIPT)}
    assert set(found) == {"import skimage.filters", "import os"}
    said = found["import skimage.filters"].message
    assert "`[postprocess] packages`" in said and '`packages = ["skimage"]`' in said
    assert "[postprocess]" not in found["import os"].message
    kit.rewrite(laplace / "definitions.py", "import numpy as np", "import numpy as np\nimport skimage")
    (other,) = at(checked(), "bad-import", "definitions.py")
    assert "[postprocess]" not in other.message


def test_two_parts_reading_one_study_name_an_observable_once(laplace):
    """Fails if two observables parts reading one study that give an observable the same name are
    not one finding, at the later part's observable in the reading order (models.md § 5.2)."""
    import shutil
    shutil.copytree(laplace / PART, laplace / "observables" / "second")
    (found,) = at(checked(), "observable-twice")
    assert (found.file, found.key) == ("observables/second/observables.toml", "observables.potential_middle")


def test_an_observables_part_comes_after_the_studies_it_reads(laplace):
    """Fails if an observables part does not come after the studies it reads in the chain's order —
    an error of its own said after a study's, the studies checked first — and in the reading order —
    `project check`'s table, the graph's nodes — so a person reads it where the work puts it
    (projects.md § 4; ADR 0025)."""
    kit.rewrite(laplace / OBSERVABLES, 'unit = "V"', 'unit = "Volt"')
    kit.rewrite(laplace / STUDY, 'display = ["m", "V", "V/m"]', 'display = ["Vx"]')
    assert [i.file for i in checked().issues if i.code == "bad-unit"] == [STUDY, OBSERVABLES]
    rows = [r.part for r in checked().parts]
    assert rows.index("observables:midpoint") > rows.index("study:check")
    nodes = [n.address for n in kit.run("project.graph", project="laplace_square").graph.nodes if n.family == "part"]
    assert nodes.index("observables:midpoint") > nodes.index("study:check")


def test_the_wire_runs_from_each_study_into_the_observables_part_that_reads_it(laplace):
    """Fails if the graph's wire between a study and the observables part reading it does not run
    from the study to the part, by the data itself — the part's `studies` naming it (models.md
    § 11.2; web.md § 2.2)."""
    graph = kit.run("project.graph", project="laplace_square").graph
    wired = {(w.source, w.target, w.target_port) for w in graph.wires if w.target == "observables:midpoint"}
    assert ("study:check", "observables:midpoint", "studies") in wired


def test_an_error_in_an_observables_part_holds_back_no_study_it_reads(laplace):
    """Fails if an error in an observables part stops `study prep` making the cases of a study it
    reads — it is no part a study uses (models.md §§ 5.2, 5.3; workflow.md § 7)."""
    kit.rewrite(laplace / f"{PART}/observables.toml", 'unit = "V"', 'unit = "Volt"')
    assert at(checked(), "bad-unit")
    outcome = kit.apply("study.prep", project="laplace_square", study="check")
    assert len(outcome.added) == 3


def test_a_finding_in_observe_py_is_its_parts(laplace):
    """Fails if a finding in an observables part's `observe.py` — an import it may not make — is not
    counted by the part's state, which reads `errors`, and held by its node in the graph: a file of
    a part, `<part>@<file>`, is the part's (projects.md §§ 5, 8; core.md § 10)."""
    kit.rewrite(laplace / SCRIPT, "def potential_middle(case):", "import os\n\n\ndef potential_middle(case):")
    result = checked()
    (found,) = at(result, "bad-import", SCRIPT)
    assert found.subject == "observables:midpoint@observe.py" and state(result, "observables:midpoint") == "errors"
    graph = kit.run("project.graph", project="laplace_square").graph
    (node,) = [n for n in graph.nodes if n.address == "observables:midpoint"]
    assert [i.code for i in node.issues] == ["bad-import"]


def test_an_observables_check_is_one_finding_per_key_and_code_naming_every_study_it_reads(laplace):
    """Fails if a group an observable takes that the component of the studies the part reads does
    not promise — two groups, two studies — is said more than once at its `takes.groups`, or its one
    message does not name each group and each study (core.md § 10: "One problem is one finding: a
    check says it once per key and code"; models.md § 5.2; the person, 2026-11-27)."""
    (laplace / "studies" / "second.toml").write_text((laplace / STUDY).read_text())
    kit.rewrite(laplace / "project.toml", 'studies = ["check"]', 'studies = ["check", "second"]')
    kit.rewrite(laplace / OBSERVABLES, 'studies = ["check"]', 'studies = ["check", "second"]')
    kit.rewrite(laplace / OBSERVABLES, '# groups = ["left"]', 'groups = ["top", "bottom"]')
    (found,) = at(checked(), "not-promised", OBSERVABLES, "observables.potential_middle.takes.groups")
    assert all(w in found.message for w in ("`top`", "`bottom`", "`check`", "`second`"))


@pytest.mark.parametrize("old, new, key", [
    ("    middle = case.defs.side / 2", "    middle = case.defs.side / 2 + 0 * case.defs.bias",
     "observables.potential_middle.takes.definitions"),
    ("    middle = case.defs.side / 2", "    middle = case.defs.side / 2 + 0 * len(case.groups.left.regions)",
     "observables.potential_middle.takes.groups"),
    ("def potential_middle(case):", "def lookup(case):\n    return case.defs.bias\n\n\n"
     "def potential_middle(case):\n    lookup(case)",
     "observables.potential_middle.takes.definitions"),          # a function it calls, handed `case`
])
def test_a_function_reading_what_its_takes_does_not_list_is_a_finding_before_any_solve(laplace, old, new, key):
    """Fails if an observable's function — or a function of `observe.py` it calls, handed `case` —
    reading `case.defs.<name>` or `case.groups.<name>` that its `takes` does not list is not a finding
    at that `takes` key before anything runs, read without running the file: `takes` is the one
    statement of what it uses (models.md § 5.2: "and nothing else"; conventions.md § 7)."""
    kit.rewrite(laplace / SCRIPT, old, new)
    (found,) = at(checked(), "not-taken", OBSERVABLES, key)
    assert found.severity == "error" and ("`bias`" in found.message or "`left`" in found.message)


def test_a_second_step_is_refused_until_steps_are_built(laplace):
    """Fails if a study holding a second step is not an error at its steps, saying several steps in
    one study are not built yet, so `study prep` refuses it (models.md § 5.1: "one step until M9")."""
    kit.rewrite(laplace / STUDY, "[numerics]", '[steps.again]\nphysics = "electrostatics"\nkind = "stationary"\n\n'
                                               "[numerics]")
    (found,) = at(checked(), "not-built", STUDY, "steps.again")
    assert found.severity == "error" and "not built yet" in found.message
    with kit.refused(Refused, "has-findings"):
        kit.planned("study.prep", project="laplace_square", study="check")
