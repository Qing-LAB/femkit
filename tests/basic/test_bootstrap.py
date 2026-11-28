"""`env bootstrap`, `doctor`'s record row, and what `config init` asks (envs.md § 6; config.md § 3.2).

Installs and the probe are replaced by stand-ins that record their order: what is tested
here is the orchestration — the installs themselves are tests/basic/test_install.py's, the
probe tests/field/test_job_probe.py's.
"""

from __future__ import annotations

import json
import os
import shlex

import pytest

from tests.kit import a_record, apply, ctx, installed, made, manager_root, planned, refused, rewrite, run, workstation  # noqa: F401 -- a fixture
from femkit.envs.records import CheckOutcome
from femkit.config import settings
from femkit.core import dirs
from femkit.core.errors import PlanStale, Unstated, UsageError
from femkit.definitions.catalogue import load_catalogue
from femkit.envs import layout
from femkit.jobs import setup

GIVEN = {"cuda_architectures": ["80"], "mpi": ["mpirun", "-np", "{ranks}"]}  # nothing measured (basic tier)
STATED = {"no_preamble": True, "command": "source activate"}  # what only a person can state (config.md § 3.1)
DEFAULT = sorted(n for n, e in load_catalogue().environments.items() if e.default)


def test_bootstrap_installs_every_default_environment_past_a_failure_then_records_and_checks(manager, workstation):
    """Fails if a failed environment stops the next one, if this machine's record is written
    before the installs it lists, if the verdict calls a failed bootstrap complete, if the
    plan's findings do not come with the outcome, as `--yes` shows no others (api.md § 4), or if
    the lines that enter femkit's control environment are other than the preamble, the stated
    activation of the control environment by its name with the manager, `femkit`, and `femkit
    doctor` — with a `cd` to the checkout among them, which the `femkit` command makes needless
    (envs.md §§ 1, 6.2, 7)."""
    from femkit.jobs import record
    apply("config.set", key="build.jobs", value="4")           # a value bootstrap keeps, written earlier
    op, plan, c = planned("env.bootstrap", **GIVEN, **STATED)
    outcome = op.apply(plan, c)                                 # each install fails: the stand-in lists no package
    rows = {r.part: r.status for r in outcome.rows}
    assert [rows[n] for n in DEFAULT] == ["failed"] * len(DEFAULT) and not outcome.ok()
    assert rows["this machine's record"] == "done"
    measured = record.read(record.path(record.LOCAL)).environments  # after the installs: what they left
    assert {n: measured[n]["state"] if isinstance(measured[n], dict) else measured[n].state for n in DEFAULT} == \
        {n: "incomplete" for n in DEFAULT}
    assert {i.code for i in plan.issues if i.code != "ready"} <= {i.code for i in outcome.issues}
    assert [e.command for e in outcome.entry] == ["source activate femkit", "femkit doctor"]   # STATED: no preamble


def test_bootstrap_shows_what_the_probe_could_not_measure_and_each_difference_from_the_record(manager, workstation):
    """Fails if bootstrap's plan, before the one consent, or its outcome leaves out what this
    machine's probe could not measure and why, or a difference from the record there it will
    replace (jobs.md § 9.2: the probe prints "any facts it could not measure and why", and
    "Every difference from the existing record is shown"; envs.md § 6.2)."""
    from femkit.jobs import record
    record.write(record.path(record.LOCAL), a_record())       # another measurement: what changes is shown
    op, plan, c = planned("env.bootstrap", **GIVEN, **STATED)
    measured = ("not-measured", "host.gpus")                    # this workstation's nvidia-smi finds no GPU
    changed = ("changed", record.LOCAL)
    assert {measured, changed} <= {(i.code, i.subject) for i in plan.issues}
    outcome = op.apply(plan, c)
    assert {measured, changed} <= {(i.code, i.subject) for i in outcome.issues}


def test_bootstrap_refuses_an_activation_the_named_managers_kind_has_no_form_of(manager):
    """Fails if bootstrap goes on with an `activation.command` the named manager's kind cannot
    enter an environment by — `mamba activate` with conda — so the entry lines it ends with, and
    every run script here, could never work, instead of refusing before anything runs and naming
    the forms the kind has (config.md § 3.1; envs.md § 6.2)."""
    with refused(UsageError, "activation-unusable", settings.COMMAND) as caught:
        planned("env.bootstrap", **GIVEN, no_preamble=True, command="mamba activate")
    assert [n.call.request["command"] for n in caught.value.next] == ["source activate", "conda activate"]
    assert not settings.config_file().exists()


def test_bootstrap_with_no_manager_named_is_refused_naming_the_install_script(monkeypatch):
    """Fails if bootstrap plans anything while no package manager is named: no environment can be
    found, nor made, but by the manager (envs.md §§ 1, 6.2, 7.1)."""
    for variable in ("FEMKIT_ENV_MANAGER", "MAMBA_EXE", "CONDA_EXE"):
        monkeypatch.delenv(variable, raising=False)
    with refused(Unstated, "manager-unnamed") as caught:
        planned("env.bootstrap", **GIVEN, command=STATED["command"])
    assert [n.command for n in caught.value.next] == [f"bash {dirs.install_script()} list"]
    assert not settings.config_file().exists()


def test_bootstrap_plans_each_install_against_the_configuration_it_will_write(manager, workstation, definitions):
    """Fails if an install is planned against config.toml as it is rather than as bootstrap
    will write it — a launcher given to bootstrap then reads as unset — or if an install
    that will be refused is not said before anything runs, or does not count against the
    exit (envs.md § 6.2)."""
    kinds = definitions / "schedulers"                       # two kinds without commands: which applies cannot be
    (kinds / "second.toml").write_text((kinds / "local.toml").read_text())   # told, and no launcher is proposed
    op, without, c = planned("env.bootstrap", cuda_architectures=GIVEN["cuda_architectures"])
    refused = set(without.holds["refused"])          # ngsolve: its checks run mpirun, and launch.mpi is unset
    assert refused and refused.isdisjoint(s.id.removeprefix("install:") for s in without.steps)
    kept = [i for i in without.issues if (i.code, i.subject) == ("setting-unset", "launch.mpi")]
    assert len(kept) == len(refused)                 # each said as the refusal it is (core.md § 10, `Issue.of`)
    given = planned("env.bootstrap", **GIVEN)[1]
    assert [s.id for s in given.steps if s.id.startswith("install:")] == [f"install:{n}" for n in DEFAULT]
    assert not settings.config_file().exists()  # planning wrote nothing
    assert not op.apply(without, c).ok()


def test_a_part_refused_while_bootstrap_runs_is_said_and_the_next_still_runs(manager_doing):
    """Fails if an install refused at its turn — its environment changed since the plan, as
    another shell would change it — ends bootstrap as a defect, or stops the installs after
    it (envs.md § 6.2, core.md § 6)."""
    first, second, *rest = DEFAULT
    envs = manager_root() / "envs"
    manager_doing(f'  "create -y") [ "$4" = femkit-{first} ] && mkdir -p {shlex.quote(str(envs / f"femkit-{second}"))}'
                  f'/conda-meta; mkdir -p {shlex.quote(str(envs))}/"$4"/conda-meta ;;')
    outcome = apply("env.bootstrap", **GIVEN)       # nothing stated: no record step
    rows = {r.part: r.status for r in outcome.rows}
    assert rows[second] == "refused" and ("basis-changed", layout.subject(second)) in {
        (i.code, i.subject) for i in outcome.issues}      # the refusal it is, kept (core.md § 10, `Issue.of`)
    assert all(rows[name] != "refused" for name in [first, *rest]) and not outcome.ok()


def test_bootstrap_refuses_its_plan_when_an_environment_changed_since(manager):
    """Fails if bootstrap applies a plan whose decisions no longer hold — an environment it
    planned to install was changed meanwhile — instead of refusing it before any step (api.md § 3)."""
    op, plan, c = planned("env.bootstrap", **GIVEN)
    made(DEFAULT[1])                                                        # another shell, meanwhile
    with refused(PlanStale, "basis-changed"):
        op.apply(plan, c)
    assert not settings.config_file().exists()


@pytest.mark.parametrize("in_job", [False, True], ids=["login node", "inside a job"])
def test_bootstrap_warns_on_a_login_node_and_only_there(in_job, monkeypatch):
    """Fails if bootstrap plans installs on a login node without naming the scheduler's
    interactive allocation, or warns inside an allocation already (envs.md § 6.2)."""
    from femkit.definitions.catalogue import load_schedulers
    slurm = load_schedulers()["slurm"]
    if in_job:
        monkeypatch.setenv(slurm.job_variables["id"], "1")  # set by hand: sbatch is on PATH, so a SLURM machine
    plan = planned("env.bootstrap", **GIVEN)[1]   # nothing stated: the record, which a probe measures, waits
    warned = [i.next[0].command for i in plan.issues if i.code == "login-node"]
    assert warned == ([] if in_job else [slurm.interactive])


def test_bootstrap_names_its_own_command_for_config_init_s_options():
    """Fails if bootstrap's plan sends the person to `config init` for a value bootstrap itself
    takes, such as the activation (envs.md § 6.2)."""
    plan = planned("env.bootstrap", **GIVEN)[1]
    named = [n.call.operation for i in plan.issues for n in i.next if n.call]
    assert "env.bootstrap" in named and "config.init" not in named


def test_init_asks_for_what_nothing_reveals_and_never_writes_a_default():
    """Fails if config init writes a default — `build.jobs`, measured on this machine, fixed into
    the file for good — asks for where environments go, which is the package manager's (envs.md
    § 1), or does not ask for the projects root, the preamble and the activation while they are
    unset, each beside its help and what its absence blocks (config.md § 3.2)."""
    op, plan, c = planned("config.init", **GIVEN)
    asks = {a.key: a for a in plan.asks}
    assert set(asks) == {"projects", "preamble", "command"}
    for k in map(settings.key, ("paths.projects", "activation.preamble", "activation.command")):
        assert {k.help, f"when unset: {k.unset}"} <= set(asks[k.name].context)
    op.apply(plan, c)
    assert "build.jobs" not in settings.load(ctx(), fresh=True).present()
    assert planned("config.init", **GIVEN, projects="/p", **STATED)[1].asks == ()
    with refused(UsageError, "invalid-request"):
        apply("config.set", key="paths.environments", value='"/x"')


def _row(subject: str):
    return next(r for r in run("doctor").rows if r.subject == subject)


def test_doctor_names_the_probe_while_this_machine_has_no_record_and_states_the_activation_first():
    """Fails if doctor counts a machine ready that has no record of itself, or names a probe
    that would be refused: `job probe --write` needs the preamble and the activation command
    stated first (envs.md § 6.1) — by `config init`, which asks each unset key in words, never a
    key's example written as if it were the person's, nor each of its alternatives a step of its
    own (workflow.md § 7: "the command that asks for it in words (`config init`)"); or if a way to
    state one is a note's text rather than a step of its own (web.md § 7.2: "Every next step is an
    Action … It holds no command text")."""
    probe = "femkit job probe --write"
    unset = _row("this machine's record")
    assert not unset.ready and unset.next == [*_row("config.toml").next, unset.next[-1]]  # state both, then probe
    (asking,) = _row("config.toml").next
    assert (asking.call.operation, asking.call.request, asking.fills) == ("config.init", {}, [])
    assert unset.next[-1].command == probe
    apply("config.set", key="activation.preamble", value="[]")
    assert [(n.call.operation, n.call.request, n.fills) for n in _row("this machine's record").next] == [
        ("config.init", {}, []), ("job.probe", {"write": True}, [])]
    apply("config.set", key="activation.command", value='"source activate"')
    assert [n.command for n in _row("this machine's record").next] == [probe]


@pytest.mark.parametrize("breaks", ["config.toml does not load", "no package manager is named"])
def test_doctor_reports_every_row_when_it_cannot_observe_one(breaks, monkeypatch):
    """Fails if doctor stops with an error instead of reporting, when config.toml does not load
    or no package manager is named: a person asking whether the machine is ready gets no
    answer (envs.md § 6.1)."""
    if breaks == "config.toml does not load":
        settings.config_file().parent.mkdir(parents=True, exist_ok=True)
        settings.config_file().write_text("[paths]\nenvironments = 7\n")
    else:
        for variable in ("FEMKIT_ENV_MANAGER", "MAMBA_EXE", "CONDA_EXE"):
            monkeypatch.delenv(variable, raising=False)
    result = run("doctor")
    assert not result.ok() and {"control environment", "config.toml", setup.ENGINES} <= {r.subject for r in result.rows}


def test_doctor_holds_only_a_default_environment_against_the_machine():
    """Fails if doctor calls a machine not ready for a CUDA environment nobody asked for,
    or stops counting a default environment that is absent (envs.md § 6.1)."""
    rows = {r.subject: r.ready for r in run("doctor").rows}
    on_request = [n for n, e in load_catalogue().environments.items() if not e.default]
    assert on_request and all(rows[n] for n in on_request) and not any(rows[n] for n in DEFAULT)


LISTED = "printf '@EXPLICIT\\nhttps://conda.anaconda.org/conda-forge/linux-64/xz-5.8.1-h0_0.conda\\n'"  # a lock to go on with


@pytest.mark.parametrize("step, name", [("create", "ngsolve"), ("lock", "ngsolve"), ("toolchain", "ngsolve"),
                                        ("audit", "web")])
@pytest.mark.parametrize("ends", ["kill -9 $$", "exit 137"], ids=["by SIGKILL", "exit 137"])
def test_a_step_ended_by_sigkill_is_killed(step, name, ends, manager_doing):
    """Fails if an install step whose command the system killed — the manager's own, or one run
    in the prefix — reads as an ordinary failure: the advice on where to run it again would never
    show (envs.md § 6.2)."""
    kills = {"create": [f'  "create -y") {ends} ;;'], "lock": [f'  "list --explicit") {ends} ;;'],
             "toolchain": [f'  "list --explicit") {LISTED} ;;', f'  "run --no-capture-output") {ends} ;;']}
    manager_doing("\n".join(kills.get(step, kills["toolchain"])))       # the audit: web's first command in its prefix
    apply("config.set", key="launch.mpi", value='["mpirun", "-np", "{ranks}"]')
    apply("env.install", names=[name])
    assert [(s.id, s.outcome) for s in run("env.log", name=name).steps][-1] == (step, "killed")


@pytest.mark.parametrize("log_line, expected", [
    ("x86_64-conda-linux-gnu-gfortran: fatal error: Killed signal terminated program f951", "killed"),
    ("nvcc error   : 'cudafe++' died due to signal 9 (Kill signal)", "killed"),
    ("Acoustics.F90:12:3: Error: Symbol 'x' at (1) has no IMPLICIT type", "failed"),
], ids=["gcc compiler killed", "nvcc front end killed", "compile error"])
def test_a_compiler_killed_under_the_build_tool_makes_its_step_killed(log_line, expected, manager_doing):
    """Fails if a step whose compiler the system killed reads as an ordinary failure, so the
    login-node advice never shows, or if a real compile error reads as killed: make exits 2 either
    way, and only the log tells (envs.md § 6.2; the line as measured on a cluster's login node).
    Every step that runs a command reads its log alike: here the first one."""
    lines = ["[ 63%] Built target CoilSolver", log_line, "gmake: *** [Makefile:166: all] Error 2"]
    manager_doing(f'  "create -y") printf "%s\\n" {" ".join(shlex.quote(x) for x in lines)}; exit 2 ;;')
    apply("env.install", names=["web"])
    assert [(s.id, s.outcome) for s in run("env.log", name="web").steps] == [("create", expected)]


@pytest.mark.parametrize("inside_a_job", [False, True], ids=["login node", "scheduler job"])
def test_an_install_the_system_killed_says_where_to_run_it_again(inside_a_job, manager_doing, monkeypatch):
    """Fails if an install whose command the system killed does not report it killed, or tells a
    login node anything but the scheduler kind's interactive allocation and then the install, each
    a next step of its own, or a step already inside an allocation — whose own memory limit
    killed it — to start another (envs.md § 6.2; web.md § 7.2); or if that install is a step
    written by hand rather than the environment table's row for the state the killed step left it
    in, its words among them (framework.md § 3: "One source of next"; envs.md § 3.3)."""
    from femkit.definitions.catalogue import load_schedulers
    slurm = load_schedulers()["slurm"]                   # sbatch is on PATH: a SLURM machine
    if inside_a_job:
        monkeypatch.setenv(slurm.job_variables["id"], "1")
    manager_doing('  "create -y") kill -9 $$ ;;')
    outcome = apply("env.install", names=["web"])
    (killed,) = [i for i in outcome.issues if i.code == "killed"]
    again = "femkit env install web"
    assert not outcome.ok() and killed.subject == "web"
    assert [n.command for n in killed.next] == ([again] if inside_a_job else [slurm.interactive, again])
    from femkit.envs import state
    c = ctx()
    (row,) = state.step(c, "web", state.observe(c, "web")[1], "install")
    assert killed.next[-1].label == row.label != "env install web"


@pytest.mark.parametrize("mpi_set, installs, measured", [
    (False, False, True),  # bootstrap writes launch.mpi, which the record lacks: stale once it does
    (True, True, True),    # current, but environments are installed: the record's would be the old ones
    (True, False, False),  # current, and nothing is installed: kept
], ids=["made-stale", "installs", "kept"])
def test_bootstrap_measures_the_record_again_unless_it_stays_current_and_nothing_is_installed(
        mpi_set, installs, measured, manager, workstation):   # a workstation: its probe reaches no scheduler
    """Fails if bootstrap keeps this machine's record although the config.toml it writes makes
    the record stale, or although it installs environments the record would then list as they
    were before; or if it measures again a record nothing changes (envs.md § 6.2; jobs.md § 9.3)."""
    from femkit.jobs import record
    for key, value in {"activation.preamble": "[]", "activation.command": '"source activate"', **({"launch.mpi": json.dumps(GIVEN["mpi"])} if mpi_set else {})}.items():
        apply("config.set", key=key, value=value)
    now = record.settings_now(settings.load(ctx()).config).model_dump(exclude_none=True)
    record.write(record.path(record.LOCAL), a_record(settings=now))      # measured under these settings
    assert record.status(ctx(), record.path(record.LOCAL), settings.load(ctx()).config)[0] == "current"  # until bootstrap
    if not installs:                                     # every default environment ready: nothing to install
        for name, env in load_catalogue().environments.items():
            if env.default:
                installed(name, outcomes=[CheckOutcome(id=c.id, outcome="passed") for c in env.checks if not c.device])
    plan = planned("env.bootstrap", **GIVEN, **STATED)[1]
    assert ("record" in [s.id for s in plan.steps]) == measured


def test_what_bootstrap_does_to_this_machines_record_is_the_tasks_its_table_gives_it(manager, workstation,
                                                                                    definitions):
    """Fails if whether bootstrap measures this machine's current record again is decided by its own
    code instead of the tasks the record's table gives that state, each where its guard holds —
    measured again where bootstrap installs environments, which the record would list as they were
    (core.md § 7: `[tasks]`, `[does]`; jobs.md § 9.3; envs.md § 6.2)."""
    from femkit.jobs import record
    for key, value in {"activation.preamble": "[]", "activation.command": '"source activate"',
                       "launch.mpi": json.dumps(GIVEN["mpi"])}.items():
        apply("config.set", key=key, value=value)
    now = record.settings_now(settings.load(ctx()).config).model_dump(exclude_none=True)
    record.write(record.path(record.LOCAL), a_record(settings=now))      # current; the environments to install
    assert "record" in [s.id for s in planned("env.bootstrap", **GIVEN, **STATED)[1].steps]
    rewrite(definitions / "states" / "record.toml", 'current = ["renew"]', "current = []")
    assert "record" not in [s.id for s in planned("env.bootstrap", **GIVEN, **STATED)[1].steps]


def test_the_probe_a_kept_record_offers_is_the_record_tables_action_never_one_written_by_hand(manager, workstation,
                                                                                            definitions):
    """Fails if the step bootstrap offers beside this machine's record it keeps — current, nothing
    installed — is written by hand rather than read from the record table's action for that state:
    its words the table's, its request the one the table fills (jobs.md § 9.3: "Every state allows
    `job probe --write` … declared in each state's row"; core.md § 7: "One source of 'next' … no
    message writes a remedy by hand")."""
    from femkit.jobs import record
    for key, value in {"activation.preamble": "[]", "activation.command": '"source activate"',
                       "launch.mpi": json.dumps(GIVEN["mpi"])}.items():
        apply("config.set", key=key, value=value)
    now = record.settings_now(settings.load(ctx()).config).model_dump(exclude_none=True)
    record.write(record.path(record.LOCAL), a_record(settings=now))      # current
    for name, env in load_catalogue().environments.items():                # nothing to install: kept
        if env.default:
            installed(name, outcomes=[CheckOutcome(id=c.id, outcome="passed") for c in env.checks if not c.device])
    rewrite(definitions / "states" / "record.toml", '[actions.current]\nprobe = { describe = "measure this machine '
            'again, and write its record"', '[actions.current]\nprobe = { describe = "measure it again"')
    (kept,) = [i for i in planned("env.bootstrap", **GIVEN, **STATED)[1].issues if i.code == "record-kept"]
    assert [(a.label, a.call.operation, a.call.request) for a in kept.next] == [
        ("measure it again", "job.probe", {"write": True})]
