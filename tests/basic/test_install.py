"""Planning an install: steps, resume, the saved lock, CMake options (envs.md § 4; definitions.md § 4.2)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from femkit.config.operations import ConfigSet
from femkit.core.errors import Refusal
from femkit.core.operations import Context, Plan, SilentObserver, Step, run_steps
from femkit.envs import layout
from femkit.envs.operations import EnvInstall
from femkit.envs.state import facts

NAME = "ngsolve-cuda"  # the CUDA environment: its ngsolve build is compiled for CUDA


def ctx() -> Context:
    return Context.from_process()


def set_key(key: str, value: str) -> None:
    c = ctx()
    ConfigSet.apply(ConfigSet.plan(ConfigSet.request(key=key, value=value), c), c)


def plan(**fields) -> Plan:
    return EnvInstall.plan(EnvInstall.request(names=[NAME], **fields), ctx())


def ids(p: Plan) -> list[str]:
    return [s.id.split("/", 1)[1] for s in p.steps]


@pytest.fixture(autouse=True)
def launcher():
    """Its checks run on two MPI ranks, so a plan needs a launcher (envs.md § 5)."""
    set_key("launch.mpi", '["mpirun", "-np", "{ranks}"]')


@pytest.fixture
def cuda():
    set_key("build.cuda_architectures", '["89"]')


def test_a_cuda_build_is_refused_until_its_architectures_are_configured(manager):
    """Fails if a CUDA build is planned with no GPU architectures to target (config.md § 3.1)."""
    with pytest.raises(Refusal):
        plan()
    set_key("build.cuda_architectures", '["89"]')
    assert ids(plan())[0] == "create"


def test_resume_skips_only_the_steps_the_last_operation_finished_for_this_fingerprint(manager, cuda):
    """Fails if an interrupted install restarts from scratch, skips a step that did not
    finish, or resumes a log made for another fingerprint (envs.md § 4.2)."""
    f = facts(ctx(), NAME)
    (f.prefix / "conda-meta").mkdir(parents=True)  # incomplete: no manifest
    first = Plan(operation="env.install", request={}, subjects=(layout.subject(NAME),),
                 basis={"install_fingerprint": f.install_fingerprint},
                 steps=tuple(Step(id=i, describe=i) for i in ("create", "lock", "forbid")))
    run_steps(first, ctx(), SilentObserver(), lambda step, where: ("failed" if step.id == "forbid" else "done", None))
    resumed = ids(plan())
    assert resumed[0] == "forbid" and "create" not in resumed and "remove" not in resumed

    other = first.model_copy(update={"basis": {"install_fingerprint": "another"}})
    run_steps(other, ctx(), SilentObserver(), lambda step, where: ("done", None))
    assert ids(plan())[:2] == ["remove", "create"]


def test_the_saved_lock_is_reused_and_clean_discards_it(manager, cuda):
    """Fails if an install ignores the exact package list saved for its fingerprint, or
    --clean reuses it (envs.md § 4.1, § 4.3)."""
    lock = layout.lock_file(NAME, facts(ctx(), NAME).install_fingerprint)
    lock.parent.mkdir(parents=True)
    lock.write_text("@EXPLICIT\n")
    create = next(s for s in plan().steps if s.id.endswith("/create"))
    assert str(lock) in create.argv
    clean = plan(clean=True)
    assert "discard-lock" in ids(clean)
    assert str(lock) not in next(s for s in clean.steps if s.id.endswith("/create")).argv


def test_declared_options_reach_cmake_typed_and_rendered(manager, cuda):
    """Fails if a declared option loses its type or placeholder, or the CUDA targets do not
    reach a CUDA build (definitions.md § 4.2, § 4.3)."""
    prefix = facts(ctx(), NAME).prefix
    argv = next(s for s in plan().steps if s.id.endswith("/configure:ngsolve")).argv
    assert f"-DNETGEN_DIR:STRING={prefix}/lib/cmake/netgen" in argv
    assert "-DUSE_MPI:BOOL=ON" in argv and "-DUSE_MKL:BOOL=OFF" in argv
    assert "-DCMAKE_CUDA_ARCHITECTURES:STRING=89" in argv
    netgen = next(s for s in plan().steps if s.id.endswith("/configure:netgen")).argv
    assert not any(a.startswith("-DCMAKE_CUDA_ARCHITECTURES") for a in netgen)


def test_a_second_resume_skips_what_every_earlier_attempt_finished(manager, cuda):
    """Fails if a resume forgets the steps an earlier attempt with the same fingerprint
    finished, and restarts from create on a prefix that already holds them — or skips the
    toolchain check, which proves the machine the resume runs on (envs.md § 4.2)."""
    f = facts(ctx(), NAME)
    (f.prefix / "conda-meta").mkdir(parents=True)

    def attempt(steps, fails):
        p = Plan(operation="env.install", request={}, subjects=(layout.subject(NAME),),
                 basis={"install_fingerprint": f.install_fingerprint},
                 steps=tuple(Step(id=i, describe=i) for i in steps))
        run_steps(p, ctx(), SilentObserver(), lambda step, where: ("failed" if step.id == fails else "done", None))

    attempt(["create", "lock", "forbid"], fails="forbid")
    attempt(["forbid", "toolchain", "fetch:netgen"], fails="fetch:netgen")
    resumed = ids(plan())
    assert resumed[:2] == ["toolchain", "fetch:netgen"] and not {"create", "lock", "forbid"} & set(resumed)


def test_the_cpu_environment_installs_with_no_cuda_target_and_no_cuda_part(manager):
    """Fails if a default environment needs build.cuda_architectures, or plans a build only the
    CUDA environment has or a CUDA compile target: the CPU builds install on any machine
    (definitions.md § 4.5)."""
    steps = EnvInstall.plan(EnvInstall.request(names=["ngsolve", "elmer"]), ctx()).steps
    assert steps and not [s for s in steps if "amgx" in s.id]
    assert not [a for s in steps if s.argv for a in s.argv if a.startswith("-DCMAKE_CUDA_ARCHITECTURES")]


def test_an_engine_create_names_only_the_declared_channels(manager, cuda):
    """Fails if an engine create names any channel but those channels.txt declares, in its order:
    the create overrides the person's own conda channels with exactly these (envs.md § 4.4)."""
    from femkit.definitions.catalogue import load_control
    create = list(next(s for s in plan(clean=True).steps if s.id.endswith("/create")).argv)
    assert [create[i + 1] for i, a in enumerate(create) if a == "-c"] == load_control().channels


def test_a_step_writes_a_path_under_the_home_directory_from_tilde_and_its_command_in_full(manager, cuda, monkeypatch):
    """Fails if a step's line prints a path under the home directory in full, or if its
    command loses the full path a person pastes (api.md § 4.4)."""
    home = Path(os.environ["FEMKIT_DATA_DIR"]).parent
    monkeypatch.setenv("HOME", str(home))
    steps = plan(clean=True).steps
    assert not [s.describe for s in steps if f"{home}/" in s.describe]
    assert next(s for s in steps if s.id.endswith("/create")).describe.startswith(f"{NAME}: create ~/")
    assert f"{home}/" in " ".join(next(s for s in steps if s.id.endswith("/create")).argv)
