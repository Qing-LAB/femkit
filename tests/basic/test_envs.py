"""The engine environment state machine and its operations' plans (envs.md § 2, § 3, § 6)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests import kit
from tests.kit import apply, ctx, hold, installed, laplace, made, planned, refused, rewrite, run  # noqa: F401 -- a fixture
from femkit import registry
from femkit.core.errors import Busy, PlanStale, Refused, Unstated, UsageError
from femkit.core.persist import write_json
from femkit.definitions.models import Check
from femkit.core import dirs
from femkit.definitions.catalogue import CUDA_SUFFIX, load_environments, load_managers
from femkit.engines import package_dir, summary
from femkit.envs import checks, install, layout
from femkit.envs import manager as manager_module
from femkit.envs.manager import resolve
from femkit.envs.records import CheckOutcome
from femkit.envs.state import facts, machine, observe

NAME = "ngsolve"
CUDA = NAME + CUDA_SUFFIX   # the environment the device check belongs to
CPU = Check(id="cpu", kind="command", run=["true"], read="summary")
GPU = Check(id="gpu", kind="command", run=["true"], read="summary", device=True)


@pytest.fixture(autouse=True)
def with_checks(give_checks):
    """The shipped definition with one CPU and one device check, in the test's own copy: its CPU
    environment runs the first, its CUDA environment both."""
    give_checks(NAME, [CPU, GPU])


def state(name: str = NAME) -> str:
    return observe(ctx(), name)[1].value


def passed(id_: str) -> CheckOutcome:
    return CheckOutcome(id=id_, outcome="passed")


def test_absent_and_incomplete_are_observed_from_the_managers_list_and_disk(tmp_path):
    """Fails if an environment the manager does not list, or one it lists without a readable
    manifest, reads as anything but absent or incomplete (envs.md § 1; § 3.2)."""
    assert state() == "absent" and facts(ctx(), NAME).prefix is None
    prefix = made(NAME)
    assert state() == "incomplete" and facts(ctx(), NAME).prefix == prefix
    write_json(layout.manifest_file(prefix), {"not": "a manifest"})
    assert state() == "incomplete"


def test_a_manifest_in_a_prefix_the_manager_lists_that_is_no_manager_environment_is_broken():
    """Fails if a manifest alone makes wreckage look installed: a prefix the manager lists that holds
    no folder a manager kind marks its environments with is the earlier tool's BROKEN, which femkit
    never installs into nor removes, naming the folder for the person (envs.md § 3.2)."""
    wreck = kit.manager_root() / "envs" / "femkit-ngsolve"
    kit.listed(wreck)
    write_json(layout.manifest_file(wreck), {"install_fingerprint": "x", "lock_sha256": "0" * 64, "manager_kind": "conda",
                                             "manager_version": "0", "solver_version": "0", "time": "t"})
    assert state() == "broken" and facts(ctx(), NAME).prefix == wreck
    for name, request in (("env.install", {"names": [NAME]}), ("env.clean", {"name": NAME})):
        with refused(Refused, "not-allowed", NAME) as caught:
            planned(name, **request)
        assert [n.command for n in caught.value.next] == [f"rm -rf {wreck}"]


@pytest.mark.parametrize("setup, expected, gpu", [
    (dict(fingerprint="old"), "outdated", None),
    (dict(), "unchecked", None),
    (dict(outcomes=[passed("cpu"), passed("gpu")], stale_checks=True), "unchecked", None),
    (dict(outcomes=[passed("gpu")]), "unchecked", None),                       # a declared check never ran
    (dict(outcomes=[CheckOutcome(id="cpu", outcome="failed"), passed("gpu")]), "failing", "passed"),
    (dict(outcomes=[passed("cpu"), CheckOutcome(id="gpu", outcome="failed")]), "ready", "failed"),
    (dict(outcomes=[passed("cpu")]), "ready", "not-run"),                      # no GPU asked for yet
    (dict(outcomes=[passed("cpu"), passed("gpu")]), "ready", "passed"),
], ids=["outdated", "unchecked", "stale-checks", "cpu-never-ran", "failing", "gpu-failed", "gpu-not-run", "ready"])
def test_installed_states_follow_the_fingerprints_and_every_cpu_check(setup, expected, gpu):
    """Fails if a changed definition, missing, stale or partial CPU check results, or a failed
    CPU check do not decide the state as envs.md § 3.2 rules 4–7 say, or a device check —
    failed or never asked for — makes an environment unusable (§ 5)."""
    installed(CUDA, **setup)
    assert state(CUDA) == expected
    if expected in ("failing", "ready"):
        assert facts(ctx(), CUDA).gpu == gpu


def test_an_environment_is_looked_at_through_the_manager_named_and_as_the_manager_that_built_it(monkeypatch,
                                                                                                tmp_path):
    """Fails if looking at an environment with no manager named does anything but refuse, naming the
    install script — no manager, no place to look — writes anything, or reads one built by a manager
    as out of date because another is named now (envs.md §§ 2, 3.1, 7.1)."""
    installed(NAME, outcomes=[passed("cpu")])
    conda = Path(os.environ[manager_module.VARIABLE])
    for variable in (*(k.activate.executable for k in load_managers().values()), manager_module.VARIABLE):
        monkeypatch.delenv(variable, raising=False)
    with refused(Unstated, "manager-unnamed") as caught:
        state()
    assert [n.command for n in caught.value.next] == [f"bash {dirs.install_script()} list"]
    assert not any(dirs.cache_dir().iterdir())                    # nothing made by looking
    mamba = tmp_path / "other" / "mamba"                           # another kind, listing the same environments
    mamba.parent.mkdir()
    mamba.write_text(conda.read_text())
    mamba.chmod(0o755)
    monkeypatch.setenv(manager_module.VARIABLE, str(mamba))
    assert state() == "ready"


def test_a_held_lock_reads_busy_and_refuses_every_action_naming_its_holder(manager):
    """Fails if a second command can act on an environment another holds, or is refused as a state
    that allows nothing instead of by the lock — `Busy`, naming the command that holds it and what
    ends its hold (envs.md § 3.2 rule 1, § 3.3; core.md §§ 5, 9)."""
    other = hold(layout.subject(NAME), "alone")                     # another command, changing it
    try:
        assert state() == "busy"
        for name, request in (("env.clean", {"name": NAME}), ("env.validate", {"name": NAME}),
                              ("env.install", {"names": [NAME]}), ("env.install", {"names": [NAME], "clean": True})):
            with refused(Busy, "held", layout.subject(NAME)) as caught:
                planned(name, **request)
            assert [n.command for n in caught.value.next] == ["end it"], name
    finally:
        other.stdin.close()
        other.wait()


def test_an_environment_in_use_stays_ready_and_refuses_what_needs_it_alone(manager):
    """Fails if a program holding an environment's lock shared — as a running web server holds
    `web`'s — makes it read busy, or lets install, clean or validate run under it instead of
    refusing with what ends that use (envs.md § 3.2, web.md § 4)."""
    from femkit.core.errors import Busy
    user = hold(layout.subject(NAME), "shared")
    try:
        with refused(Busy, "held", layout.subject(NAME)) as caught:   # absent: an install has steps
            planned("env.install", names=[NAME])[1]
        assert [n.command for n in caught.value.next] == ["end it"]
        installed(NAME, outcomes=[passed("cpu")])
        assert state() == "ready"
        for name in ("env.clean", "env.validate"):
            with refused(Busy, "held", layout.subject(NAME)):
                planned(name, name=NAME)
    finally:
        user.communicate("")
    planned("env.clean", name=NAME)       # its use ended: allowed


def test_changing_the_cuda_targets_makes_a_cuda_build_outdated():
    """Fails if build.cuda_architectures does not enter the install fingerprint of an
    environment with a CUDA build, or enters one without (envs.md § 2)."""
    installed(CUDA, outcomes=[passed("cpu"), passed("gpu")])
    installed(NAME, outcomes=[passed("cpu")])
    c = ctx()
    apply("config.set", key="build.cuda_architectures", value='["90"]')
    assert state(CUDA) == "outdated" and state() == "ready"


def test_install_never_discards_a_failing_build_on_its_own():
    """Fails if `install` is allowed on a failing environment instead of offering validate
    and install --clean (envs.md § 3.3)."""
    with refused(Refused, "not-allowed", NAME) as caught:
        m = machine(ctx())
        m.require(m.states.failing, "install", facts(ctx(), NAME), NAME)
    offered = {n.command for n in caught.value.next}
    assert {"femkit env validate ngsolve", "femkit env install ngsolve --clean"} <= offered
    assert "femkit env install ngsolve" not in offered


def test_doctor_reports_an_environment_that_is_not_ready():
    """Fails if doctor counts an environment ready that is not (envs.md § 6.1)."""
    result = run("doctor")
    assert {r.subject: r.ready for r in result.rows}[NAME] is False and not result.ok()


def test_a_result_carries_its_report_as_the_blocks_a_page_draws():
    """Fails if `env list`'s JSON lacks its report, or the report's table does not name each
    environment with its state — what the page draws with no code of its own (web.md § 7.6)."""
    result = run("env.list")
    (table,) = [b for b in result.model_dump(mode="json")["report"]["blocks"] if b["kind"] == "table"]
    assert {"name", "state"} <= {c["key"] for c in table["columns"]}
    shown = {row["name"]: row["state"] for row in table["rows"]}
    assert shown == {r.name: r.state for r in result.rows} and shown[NAME] == "absent"


def test_clean_removes_the_environment_by_its_name_through_the_manager_while_holding_its_lock(manager):
    """Fails if clean's apply mistakes its own lock for another holder, or removes the environment
    other than by the manager's declared command, by its name with the manager (envs.md §§ 1, 3.3, 6)."""
    f = installed(NAME, outcomes=[passed("cpu")])
    outcome = apply("env.clean", name=NAME)
    assert outcome.status == "done" and not f.prefix.exists()
    from femkit.definitions.catalogue import load_control
    assert manager.read_text().splitlines()[-1].split() == \
        resolve(ctx()).remove("femkit-ngsolve", load_control().channels)[1:]
    assert state() == "absent"


def test_a_change_made_while_a_plan_is_read_is_seen_though_the_command_read_it_before(manager, tmp_path):
    """Fails if core checks a plan's basis again through the reads its invocation cached — what the
    manager listed of its environments among them: the environment moved while the person read the
    plan, and clean would act on the old place (api.md § 3)."""
    import shutil
    f = installed(NAME, outcomes=[passed("cpu")])
    op, plan, c = planned("env.clean", name=NAME)                  # the command line, waiting at "Proceed?"
    shutil.rmtree(f.prefix / "conda-meta")                         # another shell: the manager lists it no more
    with refused(PlanStale, "basis-changed"):
        op.apply(plan, c)
    assert f.prefix.exists() and "remove" not in manager.read_text()


def test_in_a_shell_where_the_manager_is_initialised_the_manager_is_the_one_its_hook_named(manager, monkeypatch):
    """Fails if femkit run day to day — `femkit` in a shell where conda is initialised, or the
    control environment activated — cannot find the manager its hook named, and every report
    refuses (envs.md § 7.1)."""
    path = os.environ["FEMKIT_ENV_MANAGER"]
    monkeypatch.delenv("FEMKIT_ENV_MANAGER")
    monkeypatch.delenv("MAMBA_EXE", raising=False)
    monkeypatch.setenv("CONDA_EXE", path)
    assert str(resolve(ctx()).path) == path


def test_doctor_reads_the_control_environment_by_the_install_scripts_rules():
    """Fails if doctor calls wreckage in the control environment the manager lists, `femkit`,
    anything but broken, or offers a command the install script refuses there (envs.md §§ 1, 6.1,
    7.2, 7.3)."""
    from femkit.core.dirs import CONTROL
    from femkit.definitions.catalogue import control_digest
    records = made(CONTROL) / ".femkit"
    records.mkdir(parents=True)  # a current stamp, in an environment with no python
    (records / "control.sha256").write_text(control_digest())
    row = next(r for r in run("doctor").rows if r.subject == "control environment")
    assert row.state == "broken" and [n.command for n in row.next] == [f"bash {dirs.install_script()} bootstrap"]


def test_what_install_does_in_a_state_is_the_tasks_the_table_gives_it(definitions, manager):
    """Fails if what `install` does in a state comes from femkit's code, or from a next step's row
    run as code, instead of the tasks the environment's table gives that state, each where its
    guard holds — in `unchecked`, validate; with `--clean`, discard the saved lock and build
    (core.md § 7: `[tasks]`, `[does]`; envs.md § 3.3)."""
    apply("config.set", key="launch.mpi", value='["mpirun", "-np", "{ranks}"]')   # its toolchain runs MPI
    installed(NAME)                                                               # unchecked

    def steps(**request) -> list[str]:
        return [s.id.split("/", 1)[1] for s in planned("env.install", names=[NAME], **request)[1].steps]

    assert steps() == ["validate"]
    cleaned = steps(clean=True)
    assert cleaned[:3] == ["remove", "discard-lock", "create"] and cleaned[-1] == "validate"
    table = definitions / "states" / "environment.toml"
    rewrite(table, 'unchecked = ["deliver", "validate", "discard", "rebuild", "remove"]', 'unchecked = ["build", "remove"]')
    built = steps()
    assert built[:2] == ["remove", "create"] and built[-1] == "validate" and "discard-lock" not in built


def test_what_clean_does_in_a_state_is_the_tasks_the_table_gives_it(definitions, manager):
    """Fails if what `env clean` does in a state is read from the row that allows it there — whether
    the row names an operation — instead of the tasks the environment's table gives that state: its
    prefix removed where the state lists `remove`, nothing done where it does not, though the row
    still allows the request (core.md § 7: "or neither: the request is allowed and asks nothing of a
    person … what is done there is the machine's `[does]`"; "What code does in a state is never an
    action"; envs.md § 3.3)."""
    installed(NAME, outcomes=[passed("cpu")])                                     # ready
    assert [s.id for s in planned("env.clean", name=NAME)[1].steps] == ["remove"]
    rewrite(definitions / "states" / "environment.toml", 'ready = ["use", "deliver", "discard", "rebuild", "remove"]',
            'ready = ["use", "deliver", "discard", "rebuild"]')
    assert planned("env.clean", name=NAME)[1].steps == ()


@pytest.mark.parametrize("held", ["failing", "busy"])
@pytest.mark.parametrize("user", ["web.build", "serve.start", "project.check", "study.prep"])
def test_where_an_environment_may_not_be_used_each_step_offered_is_one_its_table_allows(user, held, give_checks,
                                                                                         laplace):
    """Fails if a command that runs femkit's program in an environment — `web build` and `serve` in
    `web`, the definitions in `model_prep` for `project check` and `study prep` — offers, where that
    environment's state does not allow its use, a step its own table refuses in that state: an
    `env install` written by hand for a `failing` one, whose working build install never discards
    on its own, or any step of it for a `busy` one, which another command holds alone (envs.md
    § 3.3: "one `envs` check refuses any other state with that state's own next steps, never an
    `env install` written by hand"; web.md § 4; models.md § 3)."""
    name = "model_prep" if user in ("project.check", "study.prep") else "web"
    give_checks(name, [CPU])
    if name == "model_prep":                          # a computed definition: the project runs femkit's program there
        with open(laplace / "project.toml", "a") as f:
            f.write('\n[definitions.half]\ntype = "float"\nfunction = "half"\nunit = "m"\n')
        with open(laplace / "definitions.py", "a") as f:
            f.write("\n\ndef half():\n    return defs.side / 2\n")
    other = None
    if held == "failing":
        installed(name, outcomes=[CheckOutcome(id="cpu", outcome="failed")])
    else:
        other = hold(layout.subject(name), "alone")
    c = ctx()
    try:
        f, state = observe(c, name)
        assert state.value == held
        if user == "project.check":
            found = run(user, project=laplace.name).issues      # the environment's finding: its, or its lock's
            offered = [a for i in found if i.subject in (name, layout.subject(name)) for a in i.next]
        else:
            first = run("study.list", project=laplace.name).studies[0].name if user == "study.prep" else None
            request = {"project": laplace.name, "study": first} if user == "study.prep" else {}
            with pytest.raises(Busy if held == "busy" else Refused) as caught:
                planned(user, **request)
            offered = list(caught.value.next)
    finally:
        if other is not None:
            other.stdin.close()
            other.wait()
    assert offered
    allowed = {s.command for s in machine(c).next(state, f)}
    assert {a.command for a in offered if a.call and a.call.operation.startswith("env.")} <= allowed


def test_a_manager_and_its_environments_are_known_by_what_its_kind_file_declares(definitions, manager, monkeypatch):
    """Fails if femkit knows a prefix for a manager's environment, asks the manager where its
    environments are, or finds the manager in a shell where it is initialised, by a name of its own
    code instead of what the manager's kind file declares (definitions.md § 6; envs.md §§ 1, 3.1,
    7.1)."""
    installed(NAME, outcomes=[passed("cpu")])                                     # it holds conda-meta/
    assert state() == "ready"
    for kind in load_managers():
        rewrite(definitions / "managers" / f"{kind}.toml", 'environment = "conda-meta"', 'environment = "made-here"')
    assert state() == "broken"
    (facts(ctx(), NAME).prefix / "made-here").mkdir()
    assert state() == "ready"
    path = os.environ[manager_module.VARIABLE]
    for variable in (manager_module.VARIABLE, *(k.activate.executable for k in load_managers().values())):
        monkeypatch.delenv(variable, raising=False)
    conda = definitions / "managers" / "conda.toml"
    rewrite(conda, 'executable = "CONDA_EXE"', 'executable = "THE_CONDA"')
    monkeypatch.setenv("THE_CONDA", path)
    assert str(resolve(ctx()).path) == path and state() == "ready"
    rewrite(conda, 'environments = { argv = ["{exe}", "env", "list", "--json"], key = "envs" }',
            'environments = { argv = ["{exe}", "env", "list", "--json"], key = "listed" }')
    with refused(Refused, "no-environments"):
        state()


def test_an_environment_is_observed_though_a_definition_of_another_kind_does_not_load(definitions):
    """Fails if a shipped definition that observing an environment does not need — a formulation —
    makes every environment command refuse when it does not load (envs.md § 3.1)."""
    (definitions / "formulations" / "broken.toml").write_text("this is = not TOML [")
    assert {r.name: r.state for r in run("env.list").rows}[NAME] == "absent"


@pytest.mark.parametrize("request_", [{"names": [NAME], "all": True}, {}], ids=["both", "neither"])
def test_an_install_names_its_environments_or_asks_for_the_defaults_never_both_nor_neither(request_):
    """Fails if an install request naming environments and asking for every default one, or
    doing neither, passes the request's own validation — every surface's — and is refused only
    by the operation's code (api.md § 4.1)."""
    op = registry.operations()["env.install"]
    with refused(UsageError, "invalid-request", "env.install"):
        op.request_from(request_)


def test_an_environments_report_writes_a_path_under_home_from_tilde(manager, monkeypatch):
    """Fails if the report of `env log` prints a path under the home directory in full, instead of
    from `~` (api.md § 4.4)."""
    installed(NAME, outcomes=[passed("cpu")])
    apply("env.clean", name=NAME)                               # an operation, its logs under femkit's state
    home = Path(os.environ["FEMKIT_STATE_DIR"]).parent
    monkeypatch.setenv("HOME", str(home))
    shown = run("env.log", name=NAME).text()
    assert "~/" in shown and f"{home}/" not in shown, shown


def test_the_check_fingerprint_covers_what_each_check_runs_and_reads_and_nothing_else():
    """Fails if the code a check fingerprint covers misses a file of the package a check's program
    is in — the `gmsh` environment's, in no engine's package — or a reader a check names, or takes
    in a file no check runs or reads: an engine's hand-over (envs.md § 2)."""
    envs, root = load_environments(), dirs.checkout()
    (check,) = envs["gmsh"].checks
    package = root.joinpath(*check.run[check.run.index("-m") + 1].split(".")).parent
    runs = {str(p.relative_to(root)) for p in package.rglob("*.py") if "__pycache__" not in p.parts}
    runner = str(Path(checks.__file__).resolve().relative_to(root))
    reader = str(Path(summary.__file__).resolve().relative_to(root))
    assert runs | {runner, reader} <= set(checks.code(envs["gmsh"]))
    assert str((package_dir("ngsolve") / "handover.py").relative_to(root)) not in checks.code(envs["ngsolve"])
    assert set(checks.code(envs["web"])) == {runner}             # no check: the runner alone


def test_whether_an_environment_provides_python_enters_its_install_fingerprint(definitions, manager):
    """Fails if a change to what an install's create solves — a tool environment that stops
    providing Python, so its create adds no Python — leaves it read as built (envs.md § 2)."""
    before = facts(ctx(), "gmsh").install_fingerprint
    rewrite(definitions / "environments" / "gmsh.toml", 'executables = ["python", "gmsh"]', 'executables = ["gmsh"]')
    assert facts(ctx(), "gmsh").install_fingerprint != before


def test_each_environment_is_the_managers_own_by_its_name_and_its_prefix_the_one_it_names(manager, manager_doing):
    """Fails if an environment is made at a prefix femkit chooses rather than by its name with the
    manager — `femkit` for the control environment, `femkit-<name>` for every other — where the
    manager keeps environments; if its prefix is formed, or taken from a listed prefix the manager
    does not name so — one made by its path elsewhere, whose last step only happens to be the name —
    whether the manager says its own name for each or only where it keeps them; or if two it names
    so are taken for either (envs.md § 1)."""
    plan = planned("env.install", names=["gmsh"])[1]
    (create,) = [s for s in plan.steps if s.id == "gmsh/create"]
    assert create.argv[1:5] == ("create", "-y", "-n", "femkit-gmsh") and "-p" not in create.argv
    assert {r.name: r.managed for r in run("env.list").rows}["elmer-cuda"] == "femkit-elmer-cuda"
    apply("env.install", names=["gmsh"])
    listed = {r.name: r for r in run("env.list").rows}
    assert listed["gmsh"].prefix == str(made("gmsh")) and listed["gmsh"].state != "absent"
    elsewhere = kit.manager_root() / "elsewhere" / "femkit-ngsolve"   # made by its path, where none are kept by name
    (elsewhere / "conda-meta").mkdir(parents=True)
    for says_names in (True, False):
        if not says_names:
            (kit.manager_root() / "no-names").touch()                   # a manager that says no name of its own
        assert facts(ctx(), NAME).prefix is None and state() == "absent"
        assert facts(ctx(), "gmsh").prefix == made("gmsh")
    first, second = made(NAME), kit.manager_root() / "other" / "femkit-ngsolve"
    manager_doing(f'  "env list") printf \'{{"envs": ["{first}", "{second}"], "envs_details": {{"{first}": '
                  f'{{"name": "femkit-ngsolve"}}, "{second}": {{"name": "femkit-ngsolve"}}}}}}\' ;;')
    with refused(Refused, "named-twice", "femkit-ngsolve"):
        state()


def started_clean(env: dict[str, str]) -> None:
    """``env`` begins as the clean start declares (envs.md § 4.4): the person's own kept, nothing of
    the outside, `PATH` the system's, no user site-packages, none of the manager's own variables set
    by femkit."""
    assert kit.kept(env), env
    assert not set(kit.POLLUTED) & set(env), kit.leaked(env)
    assert env["PATH"] == "/usr/bin:/bin" and env["PYTHONNOUSERSITE"] == "1"


def test_the_managers_own_commands_start_clean_and_run_as_the_person_set_it_up(manager, monkeypatch):
    """Fails if a manager command — a create, a lock's export, a removal, the query of where its
    environments are — sees another active environment, outside Python, injected libraries or an
    outside toolchain, any `PATH` but the system's, or runs anywhere but as the person set the
    manager up: their home, their `.condarc`, their package cache, their list of environments, a
    proxy they set (envs.md § 4.4)."""
    kit.polluted(monkeypatch)
    apply("env.install", names=["gmsh"])
    apply("env.clean", name="gmsh")
    commands = [line.split()[:2] for line in manager.read_text().splitlines()]
    assert ["env", "list"] in commands and ["create", "-y"] in commands and ["remove", "--all"] in commands
    for env in kit.calls_env(manager):
        started_clean(env)


def test_a_command_inside_an_environment_starts_clean_and_enters_by_the_managers_run(running_manager, monkeypatch,
                                                                                     give_checks, tmp_path):
    """Fails if a command femkit runs inside an environment — a check program, here — sees anything of
    the shell femkit was typed in but what the clean start passes, or enters other than by the
    manager's own `run`, by the environment's name (envs.md § 4.4)."""
    seen = tmp_path / "seen.env"
    give_checks(NAME, [Check(id="cpu", kind="command", run=["bash", "-c", f"env > {seen}; exit 1"], read="summary")])
    installed(NAME)                                                 # unchecked
    kit.polluted(monkeypatch)
    apply("env.validate", name=NAME)
    runs = [line.split() for line in running_manager.read_text().splitlines() if line.startswith("run ")]
    assert runs and runs[-1][:4] == ["run", "--no-capture-output", "-n", "femkit-ngsolve"]
    env = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)
    assert kit.kept(env) and not kit.leaked(env)
    assert env["PYTHONPATH"] == str(dirs.checkout())                # femkit's own program: the checkout alone
    assert env["PYTHONNOUSERSITE"] == "1" and "/outside/env/bin" not in env["PATH"]


def test_the_persons_script_starts_clean_through_the_one_door(manager_doing, monkeypatch, give_checks, laplace,
                                                              tmp_path):
    """Fails if the person's `definitions.py`, run by femkit's program in `model_prep` for `project
    check`, starts with anything of the shell femkit was typed in but what the clean start passes,
    or enters `model_prep` other than by the manager's own `run`, by its name (envs.md § 4.4;
    models.md § 3)."""
    seen = tmp_path / "definitions.env"
    log = manager_doing(f'  "run --no-capture-output") env > {seen}; echo \'{{"failures": [{{"definition": "half", '
                  '"point": null, "line": null, "reason": "the stand-in computes nothing"}]}\'; exit 1 ;;')
    give_checks("model_prep", [CPU])
    installed("model_prep", outcomes=[passed("cpu")])
    with open(laplace / "project.toml", "a") as f:
        f.write('\n[definitions.half]\ntype = "float"\nfunction = "half"\nunit = "m"\n')
    with open(laplace / "definitions.py", "a") as f:
        f.write("\n\ndef half():\n    return defs.side / 2\n")
    kit.polluted(monkeypatch)
    run("project.check", project=laplace.name)
    env = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)
    assert kit.kept(env) and not kit.leaked(env), kit.leaked(env)
    assert env["PATH"] == "/usr/bin:/bin" and env["PYTHONPATH"] == str(dirs.checkout())
    assert any(line.startswith("run --no-capture-output -n femkit-model_prep ") for line in log.read_text().splitlines())


# ------------------------------------------------------------------ the earlier tool's presence states (envs.md § 3)

def test_a_folder_of_its_name_the_manager_does_not_list_is_an_orphan_femkit_never_makes_over(manager):
    """Fails if a folder of an environment's name where the manager keeps environments, which it does
    not list as one — where its create would make it, and where its `run` would find it — reads as
    absent, so an install makes the environment over it; or if femkit says so without the folder and
    its remedy (envs.md § 3; the earlier tool's ORPHAN)."""
    folder = kit.manager_root() / "envs" / "femkit-ngsolve"
    folder.mkdir(parents=True)                                      # no conda-meta/: the manager lists none
    assert state() == "orphan" and facts(ctx(), NAME).orphan == folder
    for name, request in (("env.install", {"names": [NAME]}), ("env.install", {"names": [NAME], "clean": True}),
                          ("env.clean", {"name": NAME})):
        with refused(Refused, "not-allowed", NAME) as caught:
            planned(name, **request)
        assert [n.command for n in caught.value.next] == [f"rm -rf {folder}"], name
    (said,) = [i for i in run("env.list").issues if i.code == "orphan"]
    assert said.file == str(folder) and [n.command for n in said.next] == [f"rm -rf {folder}"]
    assert not [line for line in manager.read_text().splitlines() if line.startswith(("create", "remove"))] \
        if manager.exists() else True


def test_a_listed_folder_that_is_gone_is_a_ghost_made_afresh_only_when_asked(manager):
    """Fails if an environment the manager lists at a folder that is not there reads as absent or
    installed, if a plain install acts on it, or if `install --clean` removes before it makes it
    afresh (envs.md § 3; the earlier tool's GHOST)."""
    gone = kit.listed(kit.manager_root() / "envs" / "femkit-gmsh")
    gone.rmdir()
    assert state("gmsh") == "ghost"
    with refused(Refused, "not-allowed", "gmsh") as caught:
        planned("env.install", names=["gmsh"])
    assert [n.call.request for n in caught.value.next] == [{"names": ["gmsh"], "clean": True}]
    steps = [s.id for s in planned("env.install", names=["gmsh"], clean=True)[1].steps]
    assert "gmsh/create" in steps and "gmsh/remove" not in steps


# ------------------------------------------------------------------ the recipe decides (envs.md § 4.4)

def condarc(settings: dict) -> Path:
    """The person's own settings, as the stand-in manager reads them (`kit.answering`): its file."""
    import json
    kit.manager_root().mkdir(parents=True, exist_ok=True)
    (kit.manager_root() / "condarc.json").write_text(json.dumps(settings))
    return kit.manager_root() / "condarc.json"


def test_the_persons_settings_that_change_what_goes_in_are_set_aside_and_recorded(manager):
    """Fails if a create leaves the person's own pinned packages, default packages, channels,
    channel alias or custom channels able to change what goes into an environment — each set aside
    by the kind's own flags, every channel named by its full address — or if what its manifest
    records does not say which of them were found, and where (envs.md §§ 4.3, 4.4: conda manages,
    the recipe decides)."""
    file = condarc({"pinned_packages": ["numpy<2"], "channel_alias": "https://mirror.example/conda",
                    "custom_channels": {"conda-forge": "https://mirror.example"}, "channels": ["defaults"]})
    plan = planned("env.install", names=["gmsh"])[1]
    (create,) = [list(s.argv) for s in plan.steps if s.id == "gmsh/create"]
    channels = [create[i + 1] for i, word in enumerate(create) if word == "-c"]
    assert {"--override-channels", "--no-default-packages", "--no-pin"} <= set(create)
    assert channels and all(c.startswith("https://conda.anaconda.org/") for c in channels)
    recorded = install.target(ctx(), "gmsh").settings                # what its manifest step writes
    assert recorded == {k: [str(file)] for k in ("channel_alias", "channels", "custom_channels", "pinned_packages")}


@pytest.mark.parametrize("held, refuses", [(False, True), (True, False)], ids=["disabled", "enabled"])
def test_a_setting_nothing_sets_aside_refuses_an_install_before_any_create(manager, held, refuses):
    """Fails if an install goes on while a setting of the person's that nothing femkit's commands
    carry sets aside holds — conda refusing `--override-channels`, by which femkit names its own
    channels — instead of refusing before any create, naming the setting, its file and what to
    change; or refuses one set harmlessly (envs.md § 4.4)."""
    file = condarc({"override_channels_enabled": held})
    if refuses:
        with refused(Refused, "setting-refused", str(file)) as caught:
            planned("env.install", names=["gmsh"])
        (issue,) = caught.value.issues
        assert issue.file == str(file) and "override_channels_enabled" in issue.message
    else:
        assert any(s.id == "gmsh/create" for s in planned("env.install", names=["gmsh"])[1].steps)
    assert not manager.exists() or not [l for l in manager.read_text().splitlines() if l.startswith("create")]


# ------------------------------------------------------------------ a project's packages (definitions.md § 4.7)

def test_a_project_package_femkits_recipe_holds_is_never_delivered_and_said_at_its_entry(manager, laplace):
    """Fails if a project's `[postprocess]` entry naming a package femkit's recipe declares or pins for
    the environment where observables run — numpy, with or without a version — is delivered, so a
    project could change femkit's environment; or if it is not said at that entry of the project file,
    an error for a version, which the recipe decides (definitions.md § 4.7; envs.md § 4.4)."""
    with open(laplace / "project.toml", "a") as f:
        f.write('\n[postprocess]\npackages = ["numpy<2", "python", "scikit-image"]\n')
    installed("postprocess", outcomes=[])
    found = {i.label: i for i in run("project.check", project=laplace.name).issues if i.code == "package-held"}
    assert {k: v.severity for k, v in found.items()} == {"numpy<2": "error", "python": "warning"}
    assert all(i.key == "postprocess.packages" and i.file.endswith("project.toml") for i in found.values())
    (deliver,) = [s for s in planned("env.install", names=["postprocess"])[1].steps if s.id == "postprocess/deliver"]
    assert deliver.argv[-1] == "scikit-image" and "numpy<2" not in deliver.argv and "python" not in deliver.argv


def test_env_list_and_doctor_say_what_a_project_added_is_to_be_delivered(manager, laplace):
    """Fails if, after a project adds a package, `env list` and `doctor` say nothing of it — the
    environment reads ready though a project's script would not find its module — or name another
    step than `env install` of that environment, from the one answer of what it lacks (envs.md §§ 4.1,
    6.1)."""
    installed("postprocess", outcomes=[])
    assert {r.name: r.deliver for r in run("env.list").rows}["postprocess"] == []
    with open(laplace / "project.toml", "a") as f:
        f.write('\n[postprocess]\npackages = ["scikit-image"]\n')
    listed = run("env.list")
    assert {r.name: (r.state, r.deliver) for r in listed.rows}["postprocess"] == ("ready", ["scikit-image"])
    (said,) = [i for i in listed.issues if i.code == "packages-to-deliver"]
    assert [n.call.request for n in said.next] == [{"names": ["postprocess"]}]
    row = next(r for r in run("doctor").rows if r.subject == "postprocess")
    assert not row.ready and "scikit-image" in row.detail
    assert [(n.call.operation, n.call.request) for n in row.next] == [("env.install", {"names": ["postprocess"]})]
