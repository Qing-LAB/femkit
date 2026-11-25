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

from tests.kit import a_record, apply, ctx, installed, planned, refused, run
from femkit.envs.records import CheckOutcome
from femkit.config import settings
from femkit.config.requests import option_name
from femkit.core import dirs
from femkit.core.errors import PlanStale
from femkit.definitions.catalogue import load_catalogue
from femkit.envs import layout
from femkit.jobs import setup

GIVEN = {"cuda_architectures": ["80"], "mpi": ["mpirun", "-np", "{ranks}"]}  # nothing measured (basic tier)
STATED = {"no_preamble": True, "activation": "source activate"}  # what only a person can state (config.md § 3.1)
DEFAULT = sorted(n for n, e in load_catalogue().environments.items() if e.default)


@pytest.fixture
def workstation(definitions, tmp_path, monkeypatch):
    """This test's machine, stated in its own environment (testing.md § 2.1): no scheduler — its
    own definitions hold no SLURM kind — and no GPU, an `nvidia-smi` ahead of the tripwires
    finding none, as on a workstation without one."""
    (definitions / "schedulers" / "slurm.toml").unlink()
    own = tmp_path / "workstation"
    own.mkdir()
    (own / "nvidia-smi").write_text("#!/bin/sh\necho 'No devices were found' >&2\nexit 6\n")
    (own / "nvidia-smi").chmod(0o755)
    monkeypatch.setenv("PATH", f"{own}{os.pathsep}{os.environ['PATH']}")


def test_bootstrap_installs_every_default_environment_past_a_failure_then_records_and_checks(manager, workstation):
    """Fails if a failed environment stops the next one, if this machine's record is written
    before the installs it lists, if the verdict calls a failed bootstrap complete, if the
    plan's findings — where environments go, say — do not come with the outcome, as `--yes`
    shows no others (api.md § 4), or if the entry line is not the stated activation of the
    real control prefix (envs.md § 6.2)."""
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
    assert shlex.join(["source", "activate", str(dirs.control_prefix())]) in [e.command for e in outcome.entry]


def test_bootstrap_with_no_manager_named_says_why_it_gives_no_entry_line(monkeypatch):
    """Fails if bootstrap ends without the lines that enter femkit day to day and does not say
    why — no package manager is named, so the stated activation cannot be written (envs.md § 6.2)."""
    for variable in ("FEMKIT_ENV_MANAGER", "MAMBA_EXE", "CONDA_EXE"):
        monkeypatch.delenv(variable, raising=False)
    outcome = apply("env.bootstrap", **GIVEN, activation=STATED["activation"])   # no preamble: no record measured
    assert not outcome.entry and ("no-entry", settings.COMMAND) in {(i.code, i.subject) for i in outcome.issues}


def test_bootstrap_plans_each_install_against_the_configuration_it_will_write(manager, workstation, definitions):
    """Fails if an install is planned against config.toml as it is rather than as bootstrap
    will write it — a launcher given to bootstrap then reads as unset — or if an install
    that will be refused is not said before anything runs, or does not count against the
    exit (envs.md § 6.2)."""
    kinds = definitions / "schedulers"                       # two kinds without commands: which applies cannot be
    (kinds / "second.toml").write_text((kinds / "local.toml").read_text())   # told, and no launcher is proposed
    op, without, c = planned("env.bootstrap", cuda_architectures=GIVEN["cuda_architectures"])
    refused = {i.subject for i in without.issues if i.code == "refused"}  # ngsolve: its checks run mpirun
    assert refused and refused.isdisjoint(s.id.removeprefix("install:") for s in without.steps)
    given = planned("env.bootstrap", **GIVEN)[1]
    assert [s.id for s in given.steps if s.id.startswith("install:")] == [f"install:{n}" for n in DEFAULT]
    assert not settings.config_file().exists()  # planning wrote nothing
    assert not op.apply(without, c).ok()


def test_a_part_refused_while_bootstrap_runs_is_said_and_the_next_still_runs(manager_doing):
    """Fails if an install refused at its turn — its environment changed since the plan, as
    another shell would change it — ends bootstrap as a defect, or stops the installs after
    it (envs.md § 6.2, core.md § 6)."""
    first, second, *rest = DEFAULT
    c = ctx()
    manager_doing(f'  "create -y") [ "$4" = {shlex.quote(str(layout.prefix(c, first)))} ] && '
                  f'mkdir -p {shlex.quote(str(layout.prefix(c, second)))}; mkdir -p "$4/conda-meta" ;;')
    outcome = apply("env.bootstrap", **GIVEN)       # nothing stated: no record step
    rows = {r.part: r.status for r in outcome.rows}
    assert rows[second] == "refused" and ("refused", second) in {(i.code, i.subject) for i in outcome.issues}
    assert all(rows[name] != "refused" for name in [first, *rest]) and not outcome.ok()


def test_bootstrap_refuses_its_plan_when_an_environment_changed_since(manager):
    """Fails if bootstrap applies a plan whose decisions no longer hold — an environment it
    planned to install was changed meanwhile — instead of refusing it before any step (api.md § 3)."""
    op, plan, c = planned("env.bootstrap", **GIVEN)
    (layout.prefix(c, DEFAULT[1]) / "conda-meta").mkdir(parents=True)      # another shell, meanwhile
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
    plan = planned("env.bootstrap", **GIVEN, **STATED)[1]
    warned = [i.next[0].command for i in plan.issues if i.code == "login-node"]
    assert warned == ([] if in_job else [slurm.interactive])


def test_bootstrap_names_its_own_command_for_config_init_s_options():
    """Fails if bootstrap's plan sends the person to `config init` for a value bootstrap itself
    takes, such as where environments go (envs.md § 6.2)."""
    plan = planned("env.bootstrap", **GIVEN, **STATED)[1]
    named = [n.call.operation for i in plan.issues for n in i.next if n.call]
    assert "env.bootstrap" in named and "config.init" not in named


def test_init_asks_for_what_nothing_reveals_and_never_writes_a_default():
    """Fails if config init proposes or writes a default paths.environments — an unattended
    run would fix builds in a home directory for good — or does not ask for the projects root,
    the preamble, the activation and the environments' place while they are unset, each beside
    its help and what its absence blocks (config.md § 3.2)."""
    op, plan, c = planned("config.init", **GIVEN)
    asks = {a.key: a for a in plan.asks}
    assert set(asks) == {"projects", "environments", "preamble", "activation"}
    for k in map(settings.key, ("paths.projects", "paths.environments", "activation.preamble", "activation.command")):
        assert {k.help, f"when unset: {k.unset}"} <= set(asks[option_name(k)].context)
    op.apply(plan, c)
    assert "paths.environments" not in settings.load(ctx(), fresh=True).present()
    assert planned("config.init", **GIVEN, environments="/x", projects="/p", **STATED)[1].asks == ()


def _row(subject: str):
    return next(r for r in run("doctor").rows if r.subject == subject)


def test_doctor_names_the_probe_while_this_machine_has_no_record_and_states_the_activation_first():
    """Fails if doctor counts a machine ready that has no record of itself, or names a probe
    that would be refused: `job probe --write` needs the preamble and the activation command
    stated first (envs.md § 6.1)."""
    probe = "python -m femkit job probe --write"
    unset = _row("this machine's record")
    assert not unset.ready and unset.next == [*_row("config.toml").next, unset.next[-1]]  # state both, then probe
    assert unset.next[-1].command == probe
    apply("config.set", key="activation.preamble", value="[]")
    assert [str(n) for n in _row("this machine's record").next[-2:]] == [
        "python -m femkit config init --activation 'source activate'   # or 'conda activate', 'mamba activate'", probe]
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
    login node anything but the scheduler kind's interactive allocation, or a step already inside
    an allocation — whose own memory limit killed it — to start another (envs.md § 6.2)."""
    from femkit.definitions.catalogue import load_schedulers
    slurm = load_schedulers()["slurm"]                   # sbatch is on PATH: a SLURM machine
    if inside_a_job:
        monkeypatch.setenv(slurm.job_variables["id"], "1")
    manager_doing('  "create -y") kill -9 $$ ;;')
    outcome = apply("env.install", names=["web"])
    (killed,) = [i for i in outcome.issues if i.code == "killed"]
    again = "python -m femkit env install web"
    assert not outcome.ok() and killed.subject == "web"
    assert [n.command for n in killed.next] == ([again] if inside_a_job else [slurm.interactive])


@pytest.mark.parametrize("mpi_set, installs, measured", [
    (False, False, True),  # bootstrap writes launch.mpi, which the record lacks: stale once it does
    (True, True, True),    # current, but environments are installed: the record's would be the old ones
    (True, False, False),  # current, and nothing is installed: kept
], ids=["made-stale", "installs", "kept"])
def test_bootstrap_measures_the_record_again_unless_it_stays_current_and_nothing_is_installed(
        mpi_set, installs, measured, monkeypatch):
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
