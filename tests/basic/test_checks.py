"""The generic check runner and `env validate` (definitions.md § 5; envs.md § 4.1, § 5).

The checks here are real programs run through the stand-in manager, which runs
what it is given (`running_manager`); a GPU check program stands in for a CUDA one. The engines' own
check programs and readers run against real solvers in the engine tier.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from pathlib import Path

from tests.kit import apply, ctx, installed, planned, refused
from femkit.core.errors import Refused, Unstated, UsageError
from femkit.core.operations import SilentObserver
from femkit.definitions.models import Agreement, Check, Expectation
from femkit.engines import junit
from femkit.core.schema import render
from femkit.definitions.catalogue import CUDA_SUFFIX, load_managers
from femkit.envs import checks, layout, state as state_module
from femkit.envs.records import CheckOutcome, ChecksRecord, read
from femkit.envs.state import facts, observe

DEFINITION = "ngsolve"  # thread_variables NGS_NUM_THREADS, fixed_variables OMP_NUM_THREADS = "1"
NAME = DEFINITION + CUDA_SUFFIX  # its CUDA environment: it runs CPU and device checks alike

# A check program for femkit: reports what it was started with, and the value it is given.
PROGRAM = ("import os, sys; from femkit.engines import summary; summary.write(sys.argv[1], dict("
           "threads=int(os.environ['NGS_NUM_THREADS']), omp=int(os.environ['OMP_NUM_THREADS']), "
           "ranks=int(os.environ.get('RANKS', '1')), nousersite=int(os.environ.get('PYTHONNOUSERSITE', '0')), "
           "value=float(sys.argv[2])), dict())")


def program(id_: str, value: float = 1.0, **fields) -> Check:
    return Check(id=id_, kind="command", run=["python", "-c", PROGRAM, "{work}", str(value)], read="summary", **fields)


def set_key(key: str, value: str) -> None:
    c = ctx()
    apply("config.set", key=key, value=value)


@pytest.fixture
def declared(give_checks, running_manager):
    """Give the definition these checks, in the test's own copy, and its environment installed
    and unchecked."""
    def declare(*declared_checks: Check, agreements: dict | None = None, launcher: bool = True, name: str = NAME):
        give_checks(DEFINITION, list(declared_checks), agreements)
        if launcher:
            set_key("launch.mpi", '["env", "RANKS={ranks}"]')  # a launcher that starts nothing else
        return installed(name)
    return declare


def validate(name: str = NAME, **fields):
    return apply("env.validate", name=name, **fields)


def recorded() -> dict[str, CheckOutcome]:
    record = read(layout.checks_file(facts(ctx(), NAME).prefix), ChecksRecord)
    return {o.id: o for o in record.outcomes}


def test_a_check_runs_in_its_environment_with_its_threads_ranks_and_fixed_variables(declared, running_manager):
    """Fails if a check does not run through the manager in the prefix, or misses its thread
    variables, the fixed ones, the launcher for several ranks, or runs with the user's own
    site-packages on (definitions.md § 5.1)."""
    f = declared(program("serial", expect={"threads": Expectation(equals=1)}),
                 program("threaded", threads=2, expect={"threads": Expectation(equals=2)}),
                 program("mpi", ranks=2, expect={"ranks": Expectation(equals=2)}))
    outcome = validate()
    assert outcome.ok() and outcome.state == "ready"
    got = recorded()
    assert {i: o.outcome for i, o in got.items()} == {"serial": "passed", "threaded": "passed", "mpi": "passed"}
    assert all(o.quantities["omp"] == 1 and o.quantities["nousersite"] == 1 for o in got.values())
    run_form = " ".join(render(a, {"exe": "", "prefix": str(f.prefix)}) for a in load_managers()["conda"].run[1:])
    ran = [line for line in running_manager.read_text().splitlines() if line.startswith(run_form.split()[0] + " ")]
    assert len(ran) == len(got) and all(line.startswith(run_form + " ") for line in ran)   # each check, in the prefix


def test_every_check_runs_and_a_failed_one_makes_the_environment_failing(declared):
    """Fails if a failed check stops the rest — leaving the environment unchecked instead of
    failing — a missing quantity counts as met, or a check that ran another version of the
    engine than the pinned one passes (envs.md § 5; definitions.md § 5.2, § 5.3)."""
    other_version = Check(id="other-version", kind="command", read="summary", run=[
        "python", "-c", "import sys; from femkit.engines import summary; "
        "summary.write(sys.argv[1], dict(value=1.0), dict(ngsolve='0.0'))", "{work}"])
    declared(program("too-big", value=2.0, expect={"value": Expectation(max=1.0)}),
             program("missing", expect={"absent": Expectation(min=0)}),
             other_version,
             program("fine", expect={"value": Expectation(max=1.0)}))
    outcome = validate()
    assert not outcome.ok() and outcome.state == "failing"
    assert {i: o.outcome for i, o in recorded().items()} == {
        "too-big": "failed", "missing": "failed", "other-version": "failed", "fine": "passed"}


# A GPU check program for femkit: fails, as a CUDA program does, where no GPU is allocated.
GPU_PROGRAM = ("import os, sys; from femkit.engines import summary\n"
               "if not os.environ.get('CUDA_VISIBLE_DEVICES'): sys.exit('no CUDA device is visible')\n"
               "summary.write(sys.argv[1], dict(value=1.0), dict())")


def gpu_program(id_: str, **fields) -> Check:
    return Check(id=id_, kind="command", run=["python", "-c", GPU_PROGRAM, "{work}"], read="summary", device=True,
                 **fields)


def test_validate_runs_the_gpu_checks_only_when_asked_and_reports_what_the_machine_did(declared, monkeypatch):
    """Fails if a plain validate runs a GPU check the user did not ask for, if a GPU check that
    was asked for is skipped rather than run, or if its failure where no GPU is allocated is
    not its own failure in the result — or makes a CPU environment unusable (envs.md § 5)."""
    declared(program("cpu"), gpu_program("gpu"))
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    outcome = validate()
    assert outcome.ok() and outcome.state == "ready" and outcome.gpu == "not-run"
    assert set(recorded()) == {"cpu"}
    outcome = validate(gpu=True)
    assert not outcome.ok() and outcome.state == "ready" and outcome.gpu == "failed"
    assert recorded()["gpu"].reason == "exited with 1"
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    assert validate(gpu=True).gpu == "passed"


def test_each_validate_keeps_the_outcomes_of_the_checks_it_did_not_run(declared, monkeypatch):
    """Fails if `validate --gpu` drops the CPU outcomes it did not rerun — the environment then
    unchecked — or judges an agreement against a stale reference; or if a plain validate drops
    the GPU outcomes (envs.md § 5)."""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    declared(program("cpu-only"), program("reference", agree="pair"), gpu_program("gpu", agree="pair"),
             agreements={"pair": Agreement(quantity="value", rtol=1e-9)})
    validate()
    first = recorded()
    validate(gpu=True)
    after = recorded()
    assert after["cpu-only"] == first["cpu-only"] and after["reference"].log != first["reference"].log
    assert observe(ctx(), NAME)[1] == "ready"
    validate()
    assert recorded()["gpu"] == after["gpu"] and facts(ctx(), NAME).gpu == "passed"


def test_a_reference_that_fails_later_fails_the_gpu_result_kept_with_it(declared, monkeypatch, tmp_path):
    """Fails if a GPU outcome kept from an earlier `validate --gpu` stays passed after its CPU
    reference fails, or if `validate --gpu` that leaves the environment failing — through a
    reference it ran again — says only that the GPU path failed (definitions.md § 5.2; envs.md § 5)."""
    broken = tmp_path / "reference-broken"  # a flag file: a check sees no variable of the invocation (envs.md § 4.4)
    reference = Check(id="reference", kind="command", read="summary", agree="pair", run=[
        "python", "-c", "import os, sys; from femkit.engines import summary\n"
        f"if os.path.exists({str(broken)!r}): sys.exit('broken')\n"
        "summary.write(sys.argv[1], dict(value=1.0), dict())", "{work}"])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    declared(reference, gpu_program("gpu", agree="pair"), agreements={"pair": Agreement(quantity="value", rtol=1e-9)})
    validate()
    assert validate(gpu=True).gpu == "passed"
    broken.touch()
    outcome = validate()
    assert outcome.state == "failing" and outcome.gpu == "failed"
    assert [i.code for i in outcome.issues] == ["not-ready"]
    outcome = validate(gpu=True)
    assert sorted(i.code for i in outcome.issues) == ["gpu-not-qualified", "not-ready"]


@pytest.mark.parametrize("members, results, failed", [
    ({"a": False, "b": False}, {"a": 1.0, "b": 1.0 + 1e-6}, {"a", "b"}),                   # CPU only: every member
    ({"a": False, "g": True}, {"a": 1.0, "g": 1.0 + 1e-6}, {"g"}),                         # the device side is charged
    ({"a": False, "g": True}, {"a": None, "g": 1.0}, {"a", "g"}),                          # reference failed: device too
    ({"a": False, "b": False}, {"a": [1.0, 2.0], "b": [1.0]}, {"a", "b"}),                 # cannot be compared
    ({"a": False, "b": False}, {"a": [1.0, 2.0], "b": [1.0, 2.0 + 1e-12]}, set()),          # within rtol
    ({"a": False, "b": False, "c": False}, {"a": 1.0, "b": 1.0 + 8e-10, "c": 1.0 - 8e-10}, {"a", "b", "c"}),  # pairs
], ids=["cpu-group", "device-group", "lost-reference", "list-lengths", "agree", "every-pair"])
def test_a_disagreement_fails_the_members_the_contract_charges(members, results, failed):
    """Fails if an agreement group misjudges values, or charges a disagreement to the wrong
    members (definitions.md § 5.2). A result of None is a check that failed on its own."""
    env = state_module.definition(ctx(), NAME).model_copy(update={
        "checks": [Check(id=i, kind="command", run=["x"], read="summary", agree="g1", device=d) for i, d in members.items()],
        "agreements": {"g1": Agreement(quantity="q", rtol=1e-9)}})
    outcomes = {i: CheckOutcome(id=i, outcome="failed") if v is None else CheckOutcome(id=i, outcome="passed", quantities={"q": v})
                for i, v in results.items()}
    judged = checks.agree(env, outcomes)
    assert {i for i, o in judged.items() if o.outcome == "failed"} == failed


def test_validate_gpu_is_refused_without_current_cpu_results(declared):
    """Fails if `validate --gpu` runs on an unchecked environment, recording GPU results that
    cannot qualify it and reporting no GPU qualification at all (envs.md § 5)."""
    declared(program("cpu"), gpu_program("gpu"))
    with refused(Refused, "not-allowed", NAME):
        validate(gpu=True)


def test_validate_gpu_is_refused_where_no_gpu_check_is_declared(declared):
    """Fails if `validate --gpu` on an environment that declares no GPU check runs and reports
    success, as if its GPU path were qualified, or on a CPU environment does not name its CUDA
    environment — before its first validate too, not after sending the person through a CPU
    one (envs.md § 5; definitions.md § 4.5)."""
    declared(program("cpu"), name=DEFINITION)
    for when in ("before its first validate", "once validated"):
        with refused(UsageError, "no-gpu-check", DEFINITION) as caught:
            validate(DEFINITION, gpu=True)
        assert [n.command for n in caught.value.next] == [f"python -m femkit env validate {NAME} --gpu"], when
        validate(DEFINITION)


@pytest.mark.parametrize("value, ready", [(1.0, True), (2.0, False)], ids=["passes", "fails"])
def test_an_unchecked_environment_installs_by_validating(declared, value, ready):
    """Fails if `install` on an installed, unchecked environment does anything but validate,
    does not run it, runs a GPU check nobody asked for, or succeeds when it leaves the
    environment failing — without naming the check (envs.md § 3.3, § 4.1, § 5)."""
    declared(program("cpu", value=value, expect={"value": Expectation(max=1.0)}), gpu_program("gpu"))
    op, plan, c = planned("env.install", names=[NAME])
    assert [s.id for s in plan.steps] == [f"{NAME}/validate"]
    result = op.apply(plan, c)
    assert result.ok() is ready
    assert result.environments[0].state == ("ready" if ready else "failing")
    assert ready or [i.subject for i in result.issues] == [NAME]
    assert set(recorded()) == {"cpu"}


class Recorder(SilentObserver):
    """What a surface is told: each operation's name and step count, and each step's start
    and end, in order."""

    def __init__(self):
        self.said = []

    def operation_start(self, plan, where):
        self.said.append(("start", plan.operation, len(plan.steps)))

    def step_start(self, step, index, total):
        self.said.append(("step", step.id, index, total))

    def step_end(self, step, outcome, log):
        self.said.append(("end", step.id, outcome))

    def operation_end(self, plan, status):
        self.said.append(("stop", plan.operation))


def test_install_numbers_its_validate_as_its_last_step_with_the_checks_run_under_it(declared):
    """Fails if an install runs a different number of steps than its plan shows, or runs its
    validate anywhere but inside its own last step (envs.md § 4.1; api.md § 4.4)."""
    declared(program("cpu", value=2.0, expect={"value": Expectation(max=1.0)}))
    seen = Recorder()
    op, plan, c = planned("env.install", names=[NAME])
    result = op.apply(plan, c, seen)
    n = len(plan.steps)
    assert seen.said[0] == ("start", "env.install", n)
    assert seen.said[1] == ("step", "validate", n, n) and seen.said[2] == ("start", "env.validate", 2)
    assert seen.said[-3:] == [("stop", "env.validate"), ("end", "validate", "done"), ("stop", "env.install")]
    assert result.environments[0].state == "failing" and not result.ok()  # done, not ready


def test_a_check_on_several_ranks_is_refused_before_anything_runs_without_a_launcher(declared):
    """Fails if validate or install starts with launch.mpi unset and an MPI check to run,
    finding out only when that check fails (envs.md § 5)."""
    declared(program("mpi", ranks=2), launcher=False)
    with refused(Unstated, "setting-unset", "launch.mpi"):
        planned("env.validate", name=NAME)
    with refused(Unstated, "setting-unset", "launch.mpi"):
        planned("env.install", names=[NAME])


def _junit(tmp_path, body: str, nodes: list[str]) -> dict:
    """Run real pytest on a real test file; read its real JUnit report."""
    tests = tmp_path / "src" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_x.py").write_text(body)
    report = tmp_path / junit.FILE
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "junit_family=xunit2",
                    "--rootdir", str(tests), "--junitxml", str(report), *[str(tests / n.split("/")[-1]) for n in nodes]],
                   cwd=tmp_path, capture_output=True, env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
    return junit.read(tmp_path, nodes)


def test_the_junit_reader_passes_only_exactly_the_named_tests_all_passing(tmp_path):
    """Fails if a skipped, missing or extra upstream test counts as passed (definitions.md § 5.3)."""
    body = "import pytest\ndef test_a(): pass\ndef test_b(): pass\n@pytest.mark.skip\ndef test_s(): pass\n"
    named = ["tests/test_x.py::test_a", "tests/test_x.py::test_b"]
    assert _junit(tmp_path / "1", body, named) == {"tests": 2, "passed": 2}
    with pytest.raises(ValueError):
        _junit(tmp_path / "2", body, named + ["tests/test_x.py::test_s"])
    with pytest.raises(ValueError):
        junit.read(tmp_path / "1", named[:1])


def test_a_passing_test_inside_a_class_counts_as_passed(tmp_path):
    """Fails if an upstream test written inside a class is judged failed though it passed: pytest's
    report names it `module.Class::test`, as the reader must (definitions.md § 5.3)."""
    body = "class TestC:\n    def test_m(self): pass\n"
    assert _junit(tmp_path, body, ["tests/test_x.py::TestC::test_m"]) == {"tests": 1, "passed": 1}



def test_validate_runs_the_commands_its_plan_shows(declared, running_manager):
    """Fails if `env validate` runs a check's command other than its plan's — built again when
    it runs — beyond the check's own folder, known only then; or if the plan shows the command
    without the launcher a check on several ranks runs under (api.md § 3, definitions.md § 5.1)."""
    import re
    declared(program("serial"), program("spread", ranks=2))
    op, shown, c = planned("env.validate", name=NAME)
    commands = {s.id.split(":", 1)[1]: list(s.argv) for s in shown.steps if s.argv}
    assert set(commands) == {"serial", "spread"} and "RANKS=2" in commands["spread"]   # the launcher, in the plan
    op.apply(shown, c)
    calls = running_manager.read_text().splitlines()           # each call to the manager: its arguments
    for check, argv in commands.items():
        pattern = re.escape(" ".join(argv[1:])).replace(re.escape(checks.WORK), r"(\S+)")
        hits = [m for line in calls if (m := re.fullmatch(pattern, line))]
        assert len(hits) == 1 and {Path(w).name for w in hits[0].groups()} == {check}, (check, calls)
