"""The engine tier (testing.md § 1): femkit's programs that run inside an environment — the
geometry step's check, the mesh step, each engine's hand-over, the `gmsh` environment's check —
run inside the person's installed environments, on the person's word
(`python tools/testrun.py run engine`).

Each test keeps its own six directories (§ 2.1). The environments are the person's own, named
`femkit-<name>` where their package manager keeps them, found by asking the manager the invocation
names (envs.md § 1), and only read: no install, no validate, nothing written into a prefix. Every
program it starts there begins from the clean start (envs.md § 4.4), which passes `HOME`: the test's
own, here, since Gmsh writes its preferences under `HOME` (measured: Gmsh 4.15.2 writes
`~/.fltk/fltk.org/fltk.prefs` with no window open).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def a_home_of_its_own(tmp_path, monkeypatch):
    """The test's own `HOME`, which every program it starts in an environment is handed."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
