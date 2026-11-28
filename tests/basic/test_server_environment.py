"""The web server (web.md § 4): it runs on the `web` environment, refuses before anything starts
what its child could not load, and says where a server it cannot reach runs."""

from __future__ import annotations

import os

import pytest

from tests.kit import ctx, planned, refused, rewrite, run
from femkit import registry
from femkit.core.errors import Refused
from femkit.core import dirs
from femkit.core.operations import Context
from femkit.core.process import identify
from femkit.core.schema import DefinitionError
from femkit.server import state as server_state
from femkit.server.protocol import Listen, Pidfile


@pytest.mark.parametrize("verb", ["serve.start", "serve.foreground"])
def test_the_server_is_refused_while_the_web_environment_is_not_ready(verb):
    """Fails if `start` or `foreground` plans a server while the environment its child runs on
    is not installed, instead of refusing with the install that makes it ready (web.md § 4: "refuse
    while that environment's state does not allow its use, with that state's own next steps")."""
    op = registry.operations()[verb]
    with refused(Refused, "not-allowed", "web") as caught:
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


A_SHADOW = "raise SystemExit('the person\\'s own package was imported in femkit\\'s place')\n"


def test_femkits_own_program_imports_femkit_whatever_python_path_the_person_set(tmp_path):
    """Fails if femkit's own program — the server's supervisor, its child, a check program — started
    the one way femkit starts them, takes a module from the person's own `PYTHONPATH` in place of
    femkit's; the `femkit` command exports no path, so nothing else keeps it out (envs.md § 7:
    "no file of the person's stands in for a module femkit imports"). The same start with the
    person's environment as it is shows the shadow would be taken."""
    import subprocess
    import sys
    from femkit.core import dirs
    shadow = tmp_path / "persons" / "femkit"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text(A_SHADOW)
    persons = {**os.environ, "PYTHONPATH": str(shadow.parent)}
    argv = dirs.femkit_argv(sys.executable, "femkit.server.supervisor", "--help")
    taken = subprocess.run(argv, env=persons, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert taken.returncode != 0 and "in femkit's place" in taken.stderr
    ran = subprocess.run(argv, env=dirs.femkit_env(persons), cwd=tmp_path, capture_output=True, text=True,
                         timeout=60)
    assert ran.returncode == 0, ran.stderr


def test_the_supervisor_its_child_and_a_prefixs_check_programs_start_as_femkits_own_programs(manager):
    """Fails if the server's supervisor, its child or a check program inside a prefix is started
    otherwise than as femkit's own program — a second form beside `femkit_argv` and `femkit_env`
    (envs.md § 7; conventions.md § 2: one way)."""
    from femkit.core import dirs
    from femkit.envs import start
    from femkit.envs.inside import Inside
    from femkit.envs.manager import resolve
    from femkit.server import supervisor
    listen = Listen.from_json({"port": 8000})
    shown = supervisor.argv("/control/python", "/web/python", "femkit.web", listen,
                            {"socket": 3, "lock": 4, "use": []}, "{}", 1, 1)
    assert shown[:4] == dirs.femkit_argv("/control/python", supervisor.MODULE)
    child = supervisor.child_argv("/web/python", "femkit.web", listen, 3, 1)
    assert child[:4] == dirs.femkit_argv("/web/python", "femkit.web")
    base = {"HOME": "/home/p", "PYTHONNOUSERSITE": "1"}
    assert supervisor.child_env(base) == dirs.femkit_env(base)
    inside = Inside("gmsh", "femkit-gmsh", None, resolve(ctx()))
    assert inside.variables(checkout=True) == dirs.femkit_env(start.clean(ctx()))


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
    Pidfile(supervisor=identify(os.getpid()), child=None, host="other-host", listen=Listen(port=8000),
            foreground=False).write()
    row, = run("serve.status", port=8000).servers
    assert (row.state, row.listen) == ("elsewhere", f"{Listen(port=8000).describe()} on other-host")


def test_a_servers_pidfile_states_its_shape_and_one_stating_none_does_not_read():
    """Fails if the pidfile a server's supervisor writes does not state its shape, `schema`, or is read
    otherwise than by the one reader of a file femkit writes — one stating no shape, or another,
    read as if it were this one (core.md § 4: "Every file femkit writes states its shape (`schema`),
    and is read back by one reader")."""
    from femkit.core import persist
    from femkit.server import protocol
    written = Pidfile(supervisor=identify(os.getpid()), child=None, host="h", listen=Listen(port=8000),
                      foreground=False).write()
    held = persist.read_json(written)
    assert held["schema"] == 1 and protocol.read_pidfile(written).listen == Listen(port=8000)
    for shape in ({k: v for k, v in held.items() if k != "schema"}, {**held, "schema": 2}):
        persist.write_json(written, shape)
        assert protocol.read_pidfile(written) is None


def test_a_state_table_lacking_a_state_the_code_reads_is_refused_when_it_loads_and_by_schema_check(definitions):
    """Fails if a machine's table that loads by its own rules but lacks a state femkit's code reads
    by name — `m.states.elsewhere` — loads, so the code would first meet the lack while it runs, or
    `schema check` passes it (core.md § 7: "Closed and total, checked when the machine loads")."""
    table = definitions / "states" / "server.toml"
    for old in ('elsewhere = "the pidfile', 'state = "elsewhere"', "elsewhere = []", "[actions.elsewhere]"):
        rewrite(table, old, old.replace("elsewhere", "away"))
    with refused(DefinitionError, "definition-invalid", str(table)) as caught:
        server_state.machine(ctx())
    assert [where for where, _ in caught.value.problems] == ["states"]
    assert [(i.code, i.subject) for i in run("schema.check").issues] == [("definition-invalid", str(table))]


def test_what_stop_does_to_a_stale_server_is_the_tasks_the_table_gives_it(definitions):
    """Fails if what `serve stop` does in a state comes from femkit's code naming the state instead
    of the tasks the server's table gives it — a stale server's files removed, a child it left
    ended — so a table that gives the state another task changes nothing (core.md § 7: `[tasks]`,
    `[does]`; web.md § 4)."""
    Pidfile(identify(os.getpid()), None, dirs.host(), Listen(port=8000), False).write()   # no lock held: stale
    assert [s.id for s in planned("serve.stop", port=8000)[1].steps] == ["clean"]
    rewrite(definitions / "states" / "server.toml", 'stale = ["clean", "start"]', 'stale = ["start"]')
    assert [s.id for s in planned("serve.stop", port=8000)[1].steps] == []


def test_the_servers_supervisor_and_child_hold_nothing_of_the_shell_femkit_was_typed_in(tmp_path, monkeypatch):
    """Fails if the web server's supervisor or its child, femkit's own programs on an environment's
    Python, start with anything of the shell femkit was typed in but what the clean start passes —
    injected libraries, another active environment and its folder on `PATH`, an outside compiler —
    rather than through the one door every process for an environment goes through (envs.md § 4.4;
    web.md § 4)."""
    from tests import kit
    seen = tmp_path / "child.env"
    prefix = kit.installed("web", outcomes=[]).prefix                 # ready: it declares no check
    (prefix / "bin").mkdir(exist_ok=True)
    (prefix / "bin" / "python").write_text(f"#!/bin/bash\nenv > {seen}\nexit 3\n")   # the child: says what it got
    (prefix / "bin" / "python").chmod(0o755)
    kit.polluted(monkeypatch)
    outcome = kit.apply("serve.start")
    assert outcome.status == "failed" and kit.wait_until(seen.exists), outcome   # the child ran, and never answered
    env = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)
    assert kit.kept(env) and not kit.leaked(env), kit.leaked(env)
    assert env["PATH"] == "/usr/bin:/bin" and env["PYTHONPATH"] == str(dirs.checkout())
