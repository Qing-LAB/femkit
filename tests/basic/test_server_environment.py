"""The web server runs on the `web` environment (web.md § 4)."""

from __future__ import annotations

import pytest

from tests.kit import refused
from femkit import registry
from femkit.core.errors import Refused
from femkit.core.operations import Context


@pytest.mark.parametrize("verb", ["serve.start", "serve.foreground"])
def test_the_server_is_refused_while_the_web_environment_is_not_ready(verb):
    """Fails if `start` or `foreground` plans a server while the environment its child runs on
    is not installed, instead of refusing with the install that makes it ready (web.md § 4)."""
    op = registry.operations()[verb]
    with refused(Refused, "environment-not-ready", "web") as caught:
        op.plan(op.request_from({}), Context.from_process())
    assert any(n.call and n.call.request == {"names": ["web"]} for n in caught.value.next)


def test_the_supervisor_loads_neither_pydantic_nor_any_domain():
    """Fails if the server's supervisor — its real entry point — imports pydantic, flask, the web
    package or another domain: a change that breaks those would break the supervisor too, and the
    server would not say why it stopped (web.md § 4)."""
    import subprocess
    import sys
    ran = subprocess.run([sys.executable, "-X", "importtime", "-m", "femkit.server.supervisor", "--help"],
                         capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stderr
    loaded = {line.rsplit("|", 1)[-1].strip() for line in ran.stderr.splitlines() if line.startswith("import time:")}
    outside = sorted(m for m in loaded if m.split(".")[0] in ("pydantic", "pydantic_core", "flask")
                     or m.startswith(("femkit.web", "femkit.envs", "femkit.jobs", "femkit.config", "femkit.definitions")))
    assert loaded and not outside, outside
