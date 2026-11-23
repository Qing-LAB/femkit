"""The web tier (testing.md § 1): run on the web environment's own Python, which holds flask
(`<data>/environments/web/bin/python tools/testrun.py run web`)."""

from __future__ import annotations

import sys

import pytest

# The basic tier's tripwires hold here too: a web test reaches no manager, scheduler or solver,
# nor the Node.js a build runs (testing.md § 2.1).
from tests.basic.conftest import tripwire_dir, tripwire_script, tripwires  # noqa: F401


@pytest.fixture(autouse=True)
def web_python(monkeypatch):
    """The server's child runs on this very Python: the tier already runs in the web
    environment, while each test's own data folder holds no environment."""
    from femkit.server import operations
    monkeypatch.setattr(operations, "web_python", lambda ctx: sys.executable)
