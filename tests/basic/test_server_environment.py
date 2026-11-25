"""The web server (web.md § 4): it runs on the `web` environment, refuses before anything starts
what its child could not load, and says where a server it cannot reach runs."""

from __future__ import annotations

import os

import pytest

from tests.kit import ctx, refused, rewrite, run
from femkit import registry
from femkit.core.errors import Refused
from femkit.core.operations import Context
from femkit.core.process import identify
from femkit.core.schema import DefinitionError
from femkit.server import state as server_state
from femkit.server.protocol import Listen, Pidfile


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


def test_a_project_layout_that_does_not_load_is_refused_before_the_server_starts(definitions):
    """Fails if `start` plans a server whose child could open no project, its layout not loading,
    instead of refusing at once, naming the layout and `schema check` — before it would ask for
    the environment the child runs on (web.md § 4: "it refuses before it detaches"; projects.md
    § 6)."""
    layout = definitions / "project" / "layout.toml"
    rewrite(layout, 'folder = "physics"', 'folder = "studies"')       # two kinds on one folder
    op = registry.operations()["serve.start"]
    with refused(Refused, "layout-does-not-load", str(layout)) as caught:
        op.plan(op.request_from({}), Context.from_process())
    assert [a.call.operation for a in caught.value.next] == ["schema.check"]


def test_a_server_whose_pidfile_another_host_wrote_is_shown_with_that_host():
    """Fails if `status` shows a server another host started as if it listened here — its state
    read through the machine that observed it, never by its name's text (web.md § 4; core.md
    § 7)."""
    Pidfile(identify(os.getpid()), None, "other-host", Listen(port=8000), False).write()
    row, = run("serve.status", port=8000).servers
    assert (row.state, row.listen) == ("elsewhere", f"{Listen(port=8000).describe()} on other-host")


def test_a_state_table_lacking_a_state_the_code_reads_is_refused_when_it_loads_and_by_schema_check(definitions):
    """Fails if a machine's table that loads by its own rules but lacks a state femkit's code reads
    by name — `m.states.elsewhere` — loads, so the code would first meet the lack while it runs, or
    `schema check` passes it (core.md § 7: "Closed and total, checked when the machine loads")."""
    table = definitions / "states" / "server.toml"
    for old in ('elsewhere = "the pidfile', 'state = "elsewhere"', "[actions.elsewhere]"):
        rewrite(table, old, old.replace("elsewhere", "away"))
    with refused(DefinitionError, "definition-invalid", str(table)) as caught:
        server_state.machine(ctx())
    assert [where for where, _ in caught.value.problems] == ["states"]
    assert [(i.code, i.subject) for i in run("schema.check").issues] == [("definition-invalid", str(table))]
