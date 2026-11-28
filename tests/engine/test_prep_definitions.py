"""`study prep`'s definitions step and its readers, against the person's installed `model_prep`
(models.md § 3; workflow.md §§ 3, 7, 10; testing.md § 1): the definitions' program writes a
study's kept values through the one store's writer, by xarray, which only `model_prep` holds — so
these run in the engine tier, on the person's word, in the person's own named environments. Each
test keeps its own six directories, and a record of this machine of its own listing `gmsh` with a
fingerprint of the test's: forming a stage's identity
reads it, no stage runs. A run of the program is told by femkit's cache, where each run's values
are kept by the SHA-256 of what they rest on (models.md § 3): a file there not written again is a
run not made again."""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

import pytest

from tests import kit
from femkit.config import settings
from femkit.core import dirs, persist
from femkit.jobs import record

FINGERPRINT = "f" * 64
HALF = ('\n[definitions.half]\ntype = "float"\nfunction = "half"\nunit = "m"\n',
        "\n\ndef half():\n    return defs.side / 2\n")
SIDE_AXIS = '[axes."project:definitions.side"]\nclass = "physical sweep"\nvalues = [1, 2, 3]\nunit = "m"\n'


@pytest.fixture
def laplace(tmp_path) -> Path:
    """A copy of the Laplace template given a computed definition its script reads, `half`, its study
    swept over the side it is computed from; this machine's configuration and a record of it of
    the test's own."""
    kit.apply("config.init", no_preamble=True, command="conda activate",
              mpi=["mpirun", "-np", "{ranks}"], cuda_architectures=["80"])
    config = settings.load(kit.ctx(), fresh=True).config
    r = kit.a_record(identity=record.host_identity(), scheduler={"kind": "local"}, partitions={}, queues=[],
                     manager={"kind": "conda", "path": "/x/bin/conda", "version": "26.7", "root": "/x",
                              "platform": "linux-64", "run_enters": True},
                     environments={"gmsh": {"state": "ready", "install_fingerprint": FINGERPRINT}},
                     settings=record.settings_now(config).model_dump(exclude_none=True))
    record.write(record.path("local"), r)
    folder = kit.copy_template(tmp_path / "projects", "laplace_square")
    with open(folder / "project.toml", "a") as f:
        f.write(HALF[0])
    with open(folder / "definitions.py", "a") as f:
        f.write(HALF[1])
    kit.rewrite(folder / "components" / "square" / "component.toml", 'side = "length"',
                'side = "length"\nhalf = "length"')
    study = folder / "studies" / "check.toml"
    text = study.read_text()
    start = text.index('[axes."mesh:uniform:size"]')
    study.write_text(text[:start] + SIDE_AXIS + text[text.index("\n\n", start):])
    return folder


def runs_kept() -> dict[str, int]:
    """Each run of the definitions' program femkit's cache keeps, by its file, with when it was
    written: one written again is a run made again."""
    cache = dirs.cache_dir() / "definitions"
    return {p.name: p.stat().st_mtime_ns for p in cache.glob("*.nc")} if cache.is_dir() else {}


def test_prep_computes_its_definitions_at_every_point_once_and_keeps_them_whole(laplace):
    """Fails if prep's definitions step does not compute each computed definition at every distinct
    set of the constants its sweep gives, in one run per plan — its preview and its apply, and a
    later one, reading femkit's cache — or does not write `computed/<study>/definitions.nc` whole
    with every value, saying each in its declared unit in its plan; if a case does not hold the
    value it got, its script's input among them; or if a second prep writes the values again
    though nothing they rest on changed (models.md § 3: "keeps their values for its study", "A
    plan runs them once, cached in femkit's cache by what they rest on", "each case records the
    values it got — the one source of a case's values, a geometry script's included"; workflow.md
    § 7)."""
    from femkit.models import definitions
    op, plan, c = kit.planned("study.prep", project="laplace_square", study="check")
    (step,) = [s for s in plan.steps if s.id.startswith("definitions:")]
    assert step.describe == ("write computed/check/definitions.nc: at side = 1 m: half = 0.5 m; at side = 2 m: "
                             "half = 1 m; at side = 3 m: half = 1.5 m")
    ran = runs_kept()
    assert ran
    op.apply(plan, c)
    assert runs_kept() == ran
    held = persist.read_record(laplace / "computed" / "check" / "definitions.nc", definitions.KeptValues)
    assert held.reads, held.problem
    values = held.value.entries()
    assert [v["half"] for v in values] == [0.5, 1.0, 1.5] and [v["side"] for v in values] == [1.0, 2.0, 3.0]
    inputs = [json.loads(f.read_text())["component"]["inputs"]["half"]
              for f in (laplace / "cases" / "check").glob("*/case.json")]
    assert sorted(Fraction(h["value"]) for h in inputs) == [Fraction(1, 2), 1, Fraction(3, 2)]
    again = kit.planned("study.prep", project="laplace_square", study="check")[1]
    assert not [s for s in again.steps if s.id.startswith("definitions:")] and runs_kept() == ran


def test_readers_take_computed_values_kept_in_sync_and_otherwise_the_cases_wait(laplace):
    """Fails if `study flow`, `case list` or `study list` runs a function, takes a computed value
    whose kept SHA-256s are not those of now, or makes a case resting on one not kept without a
    finding saying its stages wait for `study prep` — never a value used silently (models.md § 3:
    "Every other reader ... takes a computed value from the kept values where they are in sync";
    workflow.md § 3)."""
    def flow():
        return kit.run("study.flow", project="laplace_square", study="check")

    before = flow()
    assert [i.code for i in before.issues if i.code == "not-kept"] == ["not-kept"] and not before.graph.nodes
    assert "not-kept" in {i.code for i in kit.run("study.list", project="laplace_square").issues}
    assert runs_kept() == {}
    kit.apply("study.prep", project="laplace_square", study="check")
    ran = runs_kept()
    after = flow()
    assert not [i for i in after.issues if i.code == "not-kept"]
    assert len([b for b in after.graph.boxes if b.kind == "case"]) == 3
    listed = {s.name: s for s in kit.run("case.list", project="laplace_square").studies}["check"]
    assert len(listed.written) == 3
    kit.rewrite(laplace / "definitions.py", "return defs.side / 2", "return defs.side * 0.5")
    assert [i.code for i in flow().issues if i.code == "not-kept"] == ["not-kept"]
    assert runs_kept() == ran


def test_a_saves_plan_names_the_computed_definitions_the_change_computes_again_and_runs_none(laplace):
    """Fails if a change to what a study's kept computed values rest on — the `[definitions]` table
    — does not name, before it writes, the computed definitions the next `study prep` computes again
    and the cases that wait for it, or runs a function of `definitions.py` to find out (workflow.md
    § 10, "Quick": "it runs no tool — no ... function of `definitions.py`, whose computed values it
    takes as they are kept and names those the change will compute again"; models.md § 3)."""
    kit.apply("study.prep", project="laplace_square", study="check")
    ran = runs_kept()
    held = (laplace / "project.toml").read_text()
    at = held.index("value = 1", held.index("[definitions.bias]"))
    typed = held[:at] + "value = 2" + held[at + len("value = 1"):]
    sha = hashlib.sha256((laplace / "project.toml").read_bytes()).hexdigest()
    plan = kit.planned("project.save", project="laplace_square", address="project", text=typed, sha256=sha)[1]
    (again,) = [i for i in plan.issues if i.code == "computed-again"]
    assert (again.severity, again.file, again.key) == ("info", "project.toml", "definitions.half")
    assert [(i.code, i.file) for i in plan.issues if i.code in ("cases-wait", "cases-no-longer-made")] == [
        ("cases-wait", "studies/check.toml")]
    assert runs_kept() == ran
