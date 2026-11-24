"""`env bootstrap`, `doctor`'s record row, and what `config init` asks (envs.md § 6; config.md § 3.2).

Installs and the probe are replaced by stand-ins that record their order: what is tested
here is the orchestration — the installs themselves are tests/basic/test_install.py's, the
probe tests/field/test_job_probe.py's.
"""

from __future__ import annotations

import json
import shlex

import pytest

from femkit.config import settings
from femkit.config.operations import ConfigInit, ConfigSet
from femkit.core import dirs
from femkit.core.operations import Context, Plan, Step
from femkit.definitions.catalogue import load_catalogue
from femkit.engines import registered
from femkit.envs.operations import EnvResult, InstallOutcome
from femkit.envs.state import EnvState
from femkit.jobs import setup
from femkit.jobs.operations import ProbeOutcome

GIVEN = {"cuda_architectures": ["80"], "mpi": ["mpirun", "-np", "{ranks}"]}  # nothing measured (basic tier)
STATED = {"no_preamble": True, "activation": "source activate"}  # what only a person can state (config.md § 3.1)
DEFAULT = sorted(n for n, e in load_catalogue(engines=registered()).environments.items() if e.default)


def ctx() -> Context:
    return Context.from_process()


class StandIns:
    """EnvInstall and JobProbe, each applying nothing but a line in `done`."""

    def __init__(self, failing: set[str]):
        self.failing, self.done = failing, []
        self.request = setup.EnvInstall.request

    def plan(self, req, c):
        return Plan(operation="env.install", request=req.model_dump(), steps=(Step(id=f"{req.names[0]}/create", describe="create"),))

    def apply(self, plan, c, observer):
        name = plan.request["names"][0]
        self.done.append(name)
        status = "failed" if name in self.failing else "done"
        state = EnvState.incomplete if name in self.failing else EnvState.ready
        return InstallOutcome(plan=plan, status=status, environments=[EnvResult(name=name, status=status, state=state)])


class Probe:
    request = setup.JobProbe.request

    def __init__(self, done: list[str]):
        self.done = done

    def plan(self, req, c):
        return Plan(operation="job.probe", request=req.model_dump(), steps=(Step(id="write", describe="write"),))

    def apply(self, plan, c, observer):
        self.done.append("record")
        return ProbeOutcome(plan=plan, status="done", file="machines/local.toml")


def test_bootstrap_installs_every_default_environment_past_a_failure_then_records_and_checks(manager, monkeypatch):
    """Fails if a failed environment stops the next one, if this machine's record is written
    before the installs it lists, if the verdict calls a failed bootstrap complete, if the
    plan's findings — where environments go, say — do not come with the outcome, as `--yes`
    shows no others (api.md § 4), or if the entry line is not the stated activation of the
    real control prefix (envs.md § 6.2)."""
    installs = StandIns(failing={DEFAULT[0]})
    monkeypatch.setattr(setup, "EnvInstall", installs)
    monkeypatch.setattr(setup, "JobProbe", Probe(installs.done))
    ready = setup.DoctorResult(rows=[])  # doctor content to itself, so the verdict rests on the failure alone
    monkeypatch.setattr(setup, "doctor", type("Doctor", (), {"request": staticmethod(lambda: None),
                                                              "run": staticmethod(lambda req, c: ready)}))
    first = ctx()  # a value bootstrap keeps, written by an earlier invocation
    ConfigSet.apply(ConfigSet.plan(ConfigSet.request(key="build.jobs", value="4"), first), first)
    c = ctx()
    plan = setup.EnvBootstrap.plan(setup.EnvBootstrap.request.model_validate({**GIVEN, **STATED}), c)
    outcome = setup.EnvBootstrap.apply(plan, c)
    assert installs.done == [*DEFAULT, "record"]
    assert {r.part: r.status for r in outcome.rows}[DEFAULT[0]] == "failed" and not outcome.ok()
    assert {i.code for i in plan.issues if i.code != "ready"} <= {i.code for i in outcome.issues}
    assert shlex.join(["source", "activate", str(dirs.control_prefix())]) in [e.command for e in outcome.entry]


def test_bootstrap_plans_each_install_against_the_configuration_it_will_write(manager, monkeypatch):
    """Fails if an install is planned against config.toml as it is rather than as bootstrap
    will write it — a launcher given to bootstrap then reads as unset — or if an install
    that will be refused is not said before anything runs, or does not count against the
    exit (envs.md § 6.2)."""
    from femkit.config import probe
    monkeypatch.setattr(probe, "detect_scheduler", lambda kinds: (None, "no scheduler here"))  # no launcher proposed
    without = setup.EnvBootstrap.plan(setup.EnvBootstrap.request.model_validate(  # no launch.mpi: two-rank checks
        {"cuda_architectures": GIVEN["cuda_architectures"]}), ctx())
    refused = {i.subject for i in without.issues if i.code == "refused"}  # ngsolve: its checks run mpirun
    assert refused and refused.isdisjoint(s.id.removeprefix("install:") for s in without.steps)
    given = setup.EnvBootstrap.plan(setup.EnvBootstrap.request.model_validate(GIVEN), ctx())
    assert [s.id for s in given.steps if s.id.startswith("install:")] == [f"install:{n}" for n in DEFAULT]
    assert not settings.config_file().exists()  # planning wrote nothing
    ready = setup.DoctorResult(rows=[])  # even with doctor content, a refused install is no success
    monkeypatch.setattr(setup, "doctor", type("Doctor", (), {"request": staticmethod(lambda: None),
                                                              "run": staticmethod(lambda req, c: ready)}))
    assert not setup.EnvBootstrap.apply(without, ctx()).ok()


@pytest.mark.parametrize("in_job", [False, True], ids=["login node", "inside a job"])
def test_bootstrap_warns_on_a_login_node_and_only_there(in_job, monkeypatch):
    """Fails if bootstrap plans installs on a login node without naming the scheduler's
    interactive allocation, or warns inside an allocation already (envs.md § 6.2)."""
    from femkit.definitions.catalogue import load_schedulers
    slurm = load_schedulers()["slurm"]
    if in_job:
        monkeypatch.setenv(slurm.job_variables["id"], "1")  # set by hand: sbatch is on PATH, so a SLURM machine
    monkeypatch.setattr(setup, "EnvInstall", StandIns(failing=set()))
    plan = setup.EnvBootstrap.plan(setup.EnvBootstrap.request.model_validate({**GIVEN, **STATED}), ctx())
    warned = [i.next[0].command for i in plan.issues if i.code == "login-node"]
    assert warned == ([] if in_job else [slurm.interactive])


def test_bootstrap_names_its_own_command_for_config_init_s_options():
    """Fails if bootstrap's plan sends the person to `config init` for a value bootstrap itself
    takes, such as where environments go (envs.md § 6.2)."""
    plan = setup.EnvBootstrap.plan(setup.EnvBootstrap.request.model_validate({**GIVEN, **STATED}), ctx())
    named = [n.call.operation for i in plan.issues for n in i.next if n.call]
    assert "env.bootstrap" in named and "config.init" not in named


def test_init_asks_for_what_nothing_reveals_and_never_writes_a_default():
    """Fails if config init proposes or writes a default paths.environments — an unattended
    run would fix builds in a home directory for good — or does not ask for the preamble, the
    activation and the environments' place while they are unset (config.md § 3.2)."""
    c = ctx()
    plan = ConfigInit.plan(ConfigInit.request.model_validate(GIVEN), c)
    assert {a.key for a in plan.asks} == {"environments", "preamble", "activation"}
    ConfigInit.apply(plan, c)
    assert "paths.environments" not in settings.load(ctx(), fresh=True).present()
    answered = ConfigInit.plan(ConfigInit.request.model_validate({**GIVEN, "environments": "/x", **STATED}), ctx())
    assert answered.asks == ()


def _row(subject: str):
    return next(r for r in setup.doctor.run(setup.doctor.request(), ctx()).rows if r.subject == subject)


def test_doctor_names_the_probe_while_this_machine_has_no_record_and_states_the_activation_first():
    """Fails if doctor counts a machine ready that has no record of itself, or names a probe
    that would be refused: `job probe --write` needs the preamble and the activation command
    stated first (envs.md § 6.1)."""
    probe = "python -m femkit job probe --write"
    unset = _row("this machine's record")
    assert not unset.ready and unset.next == [*_row("config.toml").next, unset.next[-1]]  # state both, then probe
    assert unset.next[-1].command == probe
    c = ctx()
    ConfigSet.apply(ConfigSet.plan(ConfigSet.request(key="activation.preamble", value="[]"), c), c)
    assert [str(n) for n in _row("this machine's record").next[-2:]] == [
        "python -m femkit config init --activation 'source activate'   # or 'conda activate', 'mamba activate'", probe]
    ConfigSet.apply(ConfigSet.plan(ConfigSet.request(key="activation.command", value="source activate"), c), c)
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
    result = setup.doctor.run(setup.doctor.request(), ctx())
    assert not result.ok() and {"control environment", "config.toml", setup.ENGINES} <= {r.subject for r in result.rows}


def test_doctor_holds_only_a_default_environment_against_the_machine():
    """Fails if doctor calls a machine not ready for a CUDA environment nobody asked for,
    or stops counting a default environment that is absent (envs.md § 6.1)."""
    rows = {r.subject: r.ready for r in setup.doctor.run(setup.doctor.request(), ctx()).rows}
    on_request = [n for n, e in load_catalogue(engines=registered()).environments.items() if not e.default]
    assert on_request and all(rows[n] for n in on_request) and not any(rows[n] for n in DEFAULT)


@pytest.mark.parametrize("step", ["create", "lock", "toolchain", "compile:ngsolve", "audit", "manifest"])
@pytest.mark.parametrize("code", [-9, 137])
def test_a_step_ended_by_sigkill_is_killed_and_names_the_interactive_allocation(step, code, tmp_path, monkeypatch):
    """Fails if any install step whose command the system killed reads as an ordinary failure,
    or the finding does not name the scheduler kind's interactive allocation (envs.md § 6.2)."""
    from femkit.core.process import ProcessResult
    from femkit.definitions.catalogue import load_environments, load_schedulers
    from femkit.envs import install, operations
    from femkit.envs.manager import resolve
    monkeypatch.setattr(install.process, "run", lambda argv, log=None, **kw: ProcessResult(tuple(argv), code, "", "", log))
    t = install.Target(name="ngsolve", env=load_environments(None, registered())["ngsolve"], prefix=tmp_path / "p",
                       manager=resolve(ctx()), channels=[], python_minor="3.12", cuda_architectures=None, jobs=1,
                       install_fingerprint="f", launcher=["mpirun", "-np", "{ranks}"])
    assert install.run_step(t, Step(id=step, describe="", argv=("x",)), tmp_path / "logs")[0] == install.KILLED
    issue = operations._killed(ctx(), "ngsolve", [step])  # sbatch is on PATH: a SLURM login node
    assert issue.next[0].command == load_schedulers()["slurm"].interactive


@pytest.mark.parametrize("log_line, expected", [
    ("x86_64-conda-linux-gnu-gfortran: fatal error: Killed signal terminated program f951", "killed"),
    ("nvcc error   : 'cudafe++' died due to signal 9 (Kill signal)", "killed"),
    ("Acoustics.F90:12:3: Error: Symbol 'x' at (1) has no IMPLICIT type", "failed"),
], ids=["gcc compiler killed", "nvcc front end killed", "compile error"])
def test_a_compiler_killed_under_the_build_tool_makes_its_step_killed(log_line, expected, tmp_path, monkeypatch):
    """Fails if a compile whose compiler the system killed reads as an ordinary failure, so the
    login-node advice never shows, or if a real compile error reads as killed: make exits 2 either
    way, and only the log tells (envs.md § 6.2; the line as measured on a cluster's login node)."""
    from femkit.core.process import ProcessResult
    from femkit.definitions.catalogue import load_environments
    from femkit.envs import install
    from femkit.envs.manager import resolve

    def make(argv, log=None, **kw):
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"[ 63%] Built target CoilSolver\n{log_line}\ngmake: *** [Makefile:166: all] Error 2\n")
        return ProcessResult(tuple(argv), 2, "", "", log)

    monkeypatch.setattr(install.process, "run", make)
    t = install.Target(name="elmer", env=load_environments(None, registered())["elmer"], prefix=tmp_path / "p",
                       manager=resolve(ctx()), channels=[], python_minor="3.12", cuda_architectures=None, jobs=1,
                       install_fingerprint="f", launcher=["mpirun", "-np", "{ranks}"])
    assert install.run_step(t, Step(id="compile:elmer", describe="", argv=("x",)), tmp_path / "logs")[0] == expected


def test_a_step_killed_inside_an_allocation_is_not_sent_to_another(monkeypatch):
    """Fails if a step the allocation's own memory limit killed is told to run inside an
    interactive allocation, which it already is (envs.md § 6.2)."""
    from femkit.definitions.catalogue import load_schedulers
    from femkit.envs import operations
    monkeypatch.setenv(load_schedulers()["slurm"].job_variables["id"], "1")  # sbatch is on PATH: inside a SLURM job
    assert [n.command for n in operations._killed(ctx(), "ngsolve", ["compile:ngsolve"]).next] == [
        "python -m femkit env install ngsolve"]


class NothingToInstall(StandIns):
    """EnvInstall with every environment ready: nothing to install."""

    def plan(self, req, c):
        return Plan(operation="env.install", request=req.model_dump(), steps=())


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
    c = ctx()
    for key, value in {"activation.preamble": "[]", "activation.command": "source activate", **({"launch.mpi": json.dumps(GIVEN["mpi"])} if mpi_set else {})}.items():
        ConfigSet.apply(ConfigSet.plan(ConfigSet.request(key=key, value=value), c), c)
    unknown = {"unknown": "not measured in a test"}
    now = record.settings_now(settings.load(ctx()).config).model_dump(exclude_none=True)
    record.write(record.path(record.LOCAL), record.Record.model_validate({
        "schema": 1, "measured": {"time": "t", "where": "workstation"}, "identity": "here",
        "host": {"os": "Linux", "architecture": "x86_64", "cores": 1, "memory_mib": 1, "gpus": unknown},
        "manager": dict.fromkeys(("kind", "path", "version", "root", "platform", "run_enters"), unknown),
        "scheduler": {"kind": "local"}, "partitions": {}, "queues": [], "environments": {}, "settings": now}))
    assert record.status(record.path(record.LOCAL), settings.load(ctx()).config)[0] == "current"  # until bootstrap
    monkeypatch.setattr(setup, "EnvInstall", (StandIns if installs else NothingToInstall)(failing=set()))
    plan = setup.EnvBootstrap.plan(setup.EnvBootstrap.request.model_validate({**GIVEN, **STATED}), ctx())
    assert ("record" in [s.id for s in plan.steps]) == measured
