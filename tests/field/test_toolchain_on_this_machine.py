"""Each engine environment's toolchain on this machine, with its real manager (envs.md § 4.1,
§ 4.5; testing.md § 1).

For each, the environment's packages are solved by the install's own `create` step — into an
environment the manager keeps by a name of the test's own, never one of the person's femkit
environments, and removed after — then put through the install's own `toolchain` step: what that
engine's build on this machine stands on. It needs the network for the solves, as the field tier
does.
"""

from __future__ import annotations

import pytest

from femkit.core import process
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.envs import install
from tests.kit import apply, rewrite

LAUNCHER = '["mpirun", "-np", "{ranks}"]'   # as config.toml writes it


@pytest.mark.parametrize("name", sorted(n for n, e in catalogue.load_environments().items()
                                         if e.default and e.proven_toolchain))
def test_each_environments_toolchain_is_proven_on_this_machine(name, tmp_path, definitions):
    """Fails if, on this machine, an engine's environment cannot compile, link and run a program
    in each language its toolchain names, or build and run an MPI program on two ranks: that
    engine's build here would then fail later, deep inside a configure."""
    rewrite(definitions / "naming.toml", 'other = "femkit-{name}"', 'other = "femkit-fieldtest-{name}"')
    apply("config.set", key="launch.mpi", value=LAUNCHER)
    c = Context.from_process()
    t = install.target(c, name)
    steps = {s.id: s for s in install.plan_steps(t, remove_first=False, discard_lock=True)}
    said: list[str] = []
    try:
        outcome, log = install.run_step(t, steps["create"], tmp_path, said.append)
        assert outcome == "done", log.read_text() + "\n".join(said)
        t = install.target(c, name)                              # where the manager made it
        outcome, log = install.run_step(t, steps["toolchain"], tmp_path, said.append)
        assert outcome == "done", log.read_text() + "\n".join(said)
    finally:                                                     # the test's own environment, removed
        process.run(t.manager.remove(t.managed, catalogue.load_control().channels), env=t.manager.environment)
