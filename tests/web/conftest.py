"""The web tier (testing.md § 1): run on the web environment's own Python, which holds flask
(`<data>/environments/web/bin/python tools/testrun.py run web`)."""

from __future__ import annotations

import sys

import pytest

# The tripwires hold here as in the basic tier: a web test reaches no manager, scheduler or solver,
# nor the Node.js a build runs (testing.md § 2.1).
from tests.kit import installed, tripwire_dir, tripwires  # noqa: F401


@pytest.fixture(autouse=True)
def web_environment():
    """The `web` environment as an install and a validate leave it, in the test's own data
    folder, its Python the one this tier runs on — the web environment's own."""
    f = installed("web", outcomes=[])
    (f.prefix / "bin").mkdir()
    (f.prefix / "bin" / "python").symlink_to(sys.executable)
    return f
