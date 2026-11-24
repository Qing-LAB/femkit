"""Each engine environment's toolchain on this machine, with its real manager (envs.md § 4.1,
§ 4.5; testing.md § 1).

For each, the environment's packages are solved by the install's own `create` step into the
test's own directory, then put through the install's own `toolchain` step: what that engine's
build on this machine stands on. It needs the network for the solves, as the field tier does.
"""

from __future__ import annotations

import pytest

from femkit.core.operations import Context
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
    steps = {s.id: s for s in install.plan_steps(t, remove_first=False, discard_lock=True)}
    said: list[str] = []
    for step in (steps["create"], steps["toolchain"]):           # the install's own door: femkit's places only
        outcome, log = install.run_step(t, step, tmp_path, said.append)
        assert outcome == "done", log.read_text() + "\n".join(said)
