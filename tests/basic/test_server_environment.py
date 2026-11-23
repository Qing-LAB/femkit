"""The web server runs on the `web` environment (api.md § 5.4)."""

from __future__ import annotations

import pytest

from femkit import registry
from femkit.core.errors import Refused
from femkit.core.operations import Context


@pytest.mark.parametrize("verb", ["serve.start", "serve.foreground"])
def test_the_server_is_refused_while_the_web_environment_is_not_ready(verb):
    """Fails if `start` or `foreground` plans a server while the environment its child runs on
    is not installed, instead of refusing with the install that makes it ready (api.md § 5.4)."""
    op = registry.operations()[verb]
    with pytest.raises(Refused) as caught:
        op.plan(op.request_from({"port": 8000}), Context.from_process())
    assert "web" in str(caught.value) and any("env install web" in n for n in caught.value.next)
