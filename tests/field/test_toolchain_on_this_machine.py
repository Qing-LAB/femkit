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
from femkit.envs import install
from tests.kit import apply

LAUNCHER = '["mpirun", "-np", "{ranks}"]'   # as config.toml writes it


@pytest.mark.parametrize("name", sorted(n for n, e in catalogue.load_environments().items()
                                         if e.default and e.proven_toolchain))
def test_each_environments_toolchain_is_proven_on_this_machine(name, tmp_path):
    """Fails if, on this machine, an engine's environment cannot compile, link and run a program
    in each language its toolchain names, or build and run an MPI program on two ranks: that
    engine's build here would then fail later, deep inside a configure."""
    apply("config.set", key="launch.mpi", value=LAUNCHER)
    t = install.target(Context.from_process(), name)            # in the test's own data directory
    create = next(s for s in install.plan_steps(t, remove_first=False, discard_lock=True) if s.id == "create")
    created = process.run(list(create.argv), log=tmp_path / "create.log", timeout=3600)
    assert created.ok, created.stdout
    said: list[str] = []
    outcome = install.step_toolchain(t, Step(id="toolchain", describe=""), tmp_path / "toolchain.log", said.append)
    assert outcome == "done", "\n".join(said)
