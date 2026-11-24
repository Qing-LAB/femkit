"""The engine environment state machine and its operations' plans (envs.md § 2, § 3, § 6)."""

from __future__ import annotations

import os

import pytest

from tests.kit import ctx, hold, installed, refused
from femkit.config.operations import ConfigSet
from femkit.core.errors import Refused
from femkit.core.locks import subject_lock
from femkit.core.persist import write_json
from femkit.definitions.models import Check
from femkit.core import dirs
from femkit.definitions.catalogue import CUDA_SUFFIX
from femkit.envs import layout, manager
from femkit.envs.manager import resolve
from femkit.envs.operations import EnvClean
from femkit.jobs.setup import doctor
from femkit.envs.records import CheckOutcome
from femkit.envs.state import MACHINE, EnvState, facts, observe

NAME = "ngsolve"
CUDA = NAME + CUDA_SUFFIX   # the environment the device check belongs to
CPU = Check(id="cpu", kind="command", run=["true"], read="summary")
GPU = Check(id="gpu", kind="command", run=["true"], read="summary", device=True)


@pytest.fixture(autouse=True)
def with_checks(give_checks):
    """The shipped definition with one CPU and one device check, in the test's own copy: its CPU
    environment runs the first, its CUDA environment both."""
    give_checks(NAME, [CPU, GPU])


def state(name: str = NAME) -> EnvState:
    return observe(ctx(), name)[1]


def passed(id_: str) -> CheckOutcome:
    return CheckOutcome(id=id_, outcome="passed")


def test_absent_and_incomplete_are_observed_from_disk():
    """Fails if a missing prefix, wreckage, or a prefix without a readable manifest reads
    as anything but absent or incomplete (envs.md § 3.2 rules 2–3)."""
    assert state() is EnvState.absent
    prefix = facts(ctx(), NAME).prefix
    prefix.mkdir(parents=True)
    assert state() is EnvState.incomplete
    (prefix / "conda-meta").mkdir()
    assert state() is EnvState.incomplete
    write_json(layout.manifest_file(prefix), {"not": "a manifest"})
    assert state() is EnvState.incomplete


def test_a_manifest_in_a_folder_that_is_not_a_manager_environment_is_incomplete():
    """Fails if a manifest alone makes wreckage look installed (envs.md § 3.2 rule 3)."""
    f = installed(NAME, outcomes=[passed("cpu")])
    (f.prefix / "conda-meta").rmdir()
    assert state() is EnvState.incomplete


@pytest.mark.parametrize("setup, expected, gpu", [
    (dict(fingerprint="old"), EnvState.outdated, None),
    (dict(), EnvState.unchecked, None),
    (dict(outcomes=[passed("cpu"), passed("gpu")], stale_checks=True), EnvState.unchecked, None),
    (dict(outcomes=[passed("gpu")]), EnvState.unchecked, None),                       # a declared check never ran
    (dict(outcomes=[CheckOutcome(id="cpu", outcome="failed"), passed("gpu")]), EnvState.failing, "passed"),
    (dict(outcomes=[passed("cpu"), CheckOutcome(id="gpu", outcome="failed")]), EnvState.ready, "failed"),
    (dict(outcomes=[passed("cpu")]), EnvState.ready, "not-run"),                      # no GPU asked for yet
    (dict(outcomes=[passed("cpu"), passed("gpu")]), EnvState.ready, "passed"),
], ids=["outdated", "unchecked", "stale-checks", "cpu-never-ran", "failing", "gpu-failed", "gpu-not-run", "ready"])
def test_installed_states_follow_the_fingerprints_and_every_cpu_check(setup, expected, gpu):
    """Fails if a changed definition, missing, stale or partial CPU check results, or a failed
    CPU check do not decide the state as envs.md § 3.2 rules 4–7 say, or a device check —
    failed or never asked for — makes an environment unusable (§ 5)."""
    installed(CUDA, **setup)
    assert state(CUDA) is expected
    if expected in (EnvState.failing, EnvState.ready):
        assert facts(ctx(), CUDA).gpu == gpu


def test_an_environment_is_looked_at_with_no_manager_named_and_as_the_manager_that_built_it(monkeypatch):
    """Fails if looking at an environment needs a package manager named, writes anything, or reads
    one built by a manager as out of date because another is named now (envs.md §§ 2, 3.1)."""
    installed(NAME, outcomes=[passed("cpu")])
    for variable in (*manager.ACTIVATION_VARIABLES, manager.VARIABLE):
        monkeypatch.delenv(variable, raising=False)
    assert state() is EnvState.ready
    assert not any(dirs.cache_dir().iterdir())                    # no manager folder made by looking
    monkeypatch.setenv(manager.VARIABLE, "/opt/mamba/bin/mamba")
    assert state() is EnvState.ready


def test_a_held_lock_reads_busy_and_refuses_every_action():
    """Fails if a second command can act on an environment another holds (envs.md § 3.2 rule 1, § 3.3)."""
    with subject_lock(layout.subject(NAME)):
        assert state() is EnvState.busy
        with pytest.raises(Refused):
            EnvClean.plan(EnvClean.request(name=NAME), ctx())


def test_an_environment_in_use_stays_ready_and_refuses_what_needs_it_alone(manager):
    """Fails if a program holding an environment's lock shared — as a running web server holds
    `web`'s — makes it read busy, or lets install, clean or validate run under it instead of
    refusing with what ends that use (envs.md § 3.2, web.md § 4)."""
    from femkit.core.errors import Busy
    from femkit.envs.operations import EnvInstall, EnvValidate
    user = hold(layout.subject(NAME), "shared")
    try:
        with pytest.raises(Busy) as caught:                 # absent: an install has steps
            EnvInstall.plan(EnvInstall.request(names=[NAME]), ctx())
        assert [n.command for n in caught.value.next] == ["end it"]
        installed(NAME, outcomes=[passed("cpu")])
        assert state() is EnvState.ready
        for op, request in ((EnvClean, EnvClean.request(name=NAME)), (EnvValidate, EnvValidate.request(name=NAME))):
            with refused(Busy, "busy", layout.subject(NAME)):
                op.plan(request, ctx())
    finally:
        user.communicate("")
    EnvClean.plan(EnvClean.request(name=NAME), ctx())       # its use ended: allowed


def test_changing_the_cuda_targets_makes_a_cuda_build_outdated():
    """Fails if build.cuda_architectures does not enter the install fingerprint of an
    environment with a CUDA build, or enters one without (envs.md § 2)."""
    installed(CUDA, outcomes=[passed("cpu"), passed("gpu")])
    installed(NAME, outcomes=[passed("cpu")])
    c = ctx()
    ConfigSet.apply(ConfigSet.plan(ConfigSet.request(key="build.cuda_architectures", value='["90"]'), c), c)
    assert state(CUDA) is EnvState.outdated and state() is EnvState.ready


def test_install_never_discards_a_failing_build_on_its_own():
    """Fails if `install` is allowed on a failing environment instead of offering validate
    and install --clean (envs.md § 3.3)."""
    with pytest.raises(Refused) as caught:
        MACHINE.require(EnvState.failing, "install", NAME)
    offered = {n.command for n in caught.value.next}
    assert {"python -m femkit env validate ngsolve", "python -m femkit env install ngsolve --clean"} <= offered
    assert "python -m femkit env install ngsolve" not in offered


def test_doctor_reports_an_environment_that_is_not_ready():
    """Fails if doctor counts an environment ready that is not (envs.md § 6.1)."""
    result = doctor.run(doctor.request(), ctx())
    assert {r.subject: r.ready for r in result.rows}[NAME] is False and not result.ok()


def test_clean_removes_the_prefix_through_the_manager_while_holding_its_lock(manager):
    """Fails if clean's apply mistakes its own lock for another holder, or removes the
    prefix other than by the manager's declared command (envs.md § 3.3, § 6)."""
    f = installed(NAME, outcomes=[passed("cpu")])
    c = ctx()
    outcome = EnvClean.apply(EnvClean.plan(EnvClean.request(name=NAME), c), c)
    assert outcome.status == "done" and not f.prefix.exists()
    from femkit.definitions.catalogue import load_control
    assert manager.read_text().split() == resolve(ctx()).remove(f.prefix, load_control().channels)[1:]


def test_in_the_activated_control_environment_the_manager_is_the_one_activation_named(manager, monkeypatch):
    """Fails if femkit run day to day — `conda activate`, then `python -m femkit` — cannot
    find the manager the activation named, and every report refuses (envs.md § 7.1)."""
    path = os.environ["FEMKIT_ENV_MANAGER"]
    monkeypatch.delenv("FEMKIT_ENV_MANAGER")
    monkeypatch.delenv("MAMBA_EXE", raising=False)
    monkeypatch.setenv("CONDA_EXE", path)
    assert str(resolve(ctx()).path) == path


def test_doctor_reads_the_control_environment_by_the_install_scripts_rules():
    """Fails if doctor calls wreckage at the control prefix anything but broken, or offers a
    command the install script refuses there (envs.md § 6.1, § 7.2, § 7.3)."""
    from femkit.core import dirs
    from femkit.definitions.catalogue import control_digest
    records = dirs.control_prefix() / ".femkit"
    records.mkdir(parents=True)  # a current stamp, in a folder that is no environment
    (records / "control.sha256").write_text(control_digest())
    row = next(r for r in doctor.run(doctor.request(), ctx()).rows if r.subject == "control environment")
    assert row.state == "broken" and [n.command for n in row.next] == ["bash scripts/install-env.sh bootstrap"]
