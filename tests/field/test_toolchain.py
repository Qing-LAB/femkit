"""Each engine environment's toolchain on this machine, with its real manager (envs.md § 4.1,
§ 4.5; testing.md § 1).

For each, the environment's packages are solved by the install's own `create` step into the
test's own directory, then put through the install's own `toolchain` step: what that engine's
build on this machine stands on. It needs the network for the solves, as the field tier does.
"""

from __future__ import annotations

import pytest

from femkit.core import process
from femkit.core.operations import Context, Step
from femkit.definitions import catalogue
from femkit.engines import registered
from femkit.envs import install
from femkit.envs.manager import resolve

LAUNCHER = ["mpirun", "-np", "{ranks}"]


@pytest.mark.parametrize("name", sorted(n for n, e in catalogue.load_environments(None, registered()).items()
                                         if e.default and e.proven_toolchain))
def test_each_environments_toolchain_is_proven_on_this_machine(name, tmp_path):
    """Fails if, on this machine, an engine's environment cannot compile, link and run a program
    in each language its toolchain names, or build and run an MPI program on two ranks: that
    engine's build here would then fail later, deep inside a configure."""
    m = resolve(Context.from_process())
    control = catalogue.load_control()
    env = catalogue.load_environments(None, registered())[name]
    t = install.Target(name=f"toolchain-{name}", env=env, prefix=tmp_path / "prefix", manager=m,
                       channels=control.channels, python_minor=control.python_minor, cuda_architectures=None,
                       jobs=1, install_fingerprint="field-test", launcher=LAUNCHER)
    create = next(s for s in install.plan_steps(t, remove_first=False, discard_lock=True) if s.id == "create")
    created = process.run(list(create.argv), log=tmp_path / "create.log", timeout=3600)
    assert created.ok, created.stdout
    said: list[str] = []
    outcome = install.step_toolchain(t, Step(id="toolchain", describe=""), tmp_path / "toolchain.log", said.append)
    assert outcome == "done", "\n".join(said)
