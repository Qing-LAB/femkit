"""Serving the web application: the server's state machine, its verbs and its supervisor
(web.md § 4), and every request checked (§ 5). These start real processes on a free
loopback port, with this test's own directories."""

from __future__ import annotations

import gzip
import json
import os
import signal
import socket
import stat
import time
from pathlib import Path

import pytest

from tests.kit import apply, run
from femkit import registry
from femkit.core import clock, locks
from femkit.core.eventlog import EventLog
from femkit.core.errors import Busy, Refused
from femkit.core.operations import Context, OperationAddress, operations_root
from femkit.core.view import Verb
from femkit.core.process import GRACE, Identity, end, identify
from femkit.server import health, protocol
from femkit.server.protocol import Listen, LogRoll, Pidfile
from femkit.server.state import MACHINE, ServerFacts, ServerState, facts

HERE = socket.gethostname()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(check, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def server():
    """A started server on a free port, stopped (or its processes ended) after the test."""
    port = free_port()
    outcome = apply("serve.start", port=port, tcp=True)
    assert outcome.ok(), outcome.text()
    yield port
    ended(str(port))


def ended(name: str) -> None:
    """Every process of the server ``name`` ended, whatever state the test left it in."""
    p = protocol.read_pidfile(protocol.pidfile(name))
    if p is not None:
        for who in (p.child, p.supervisor):
            if who is not None:
                end(who, grace=2)


# ------------------------------------------------------------------ the state machine

def _pidfile(alive: bool, host: str = HERE) -> Pidfile:
    me = identify(os.getpid())
    supervisor = me if alive else Identity(me.pid, me.start + 1, me.boot)  # a recycled pid: another start time
    return Pidfile(supervisor, None, host, Listen(port=8000), False)


@pytest.mark.parametrize("locked, exists, pidfile, state", [
    (False, False, None, ServerState.stopped),
    (False, True, "alive", ServerState.stale),           # the lock is free: its supervisor is gone, whatever the pid says
    (False, True, None, ServerState.stale),              # an unreadable pidfile left behind
    (True, True, "alive", ServerState.running),
    (True, True, "recycled", ServerState.starting),      # the pid runs, but not with the start time recorded
    (True, False, None, ServerState.starting),
    (False, True, "elsewhere", ServerState.elsewhere),
])
def test_the_server_state_is_observed_from_its_lock_and_pidfile(locked, exists, pidfile, state):
    """Fails if a server's state is guessed from a process ID alone, or the rules of web.md
    § 4 apply out of their order: the lock is the supervisor's liveness."""
    p = {"alive": _pidfile(True), "recycled": _pidfile(False), "elsewhere": _pidfile(True, host="other-host"),
         None: None}[pidfile]
    assert MACHINE.observe(ServerFacts("8000", HERE, locked, exists, p)) is state


# ------------------------------------------------------------------ the verbs, live

def test_start_serves_with_its_token_and_a_second_start_is_refused(server):
    """Fails if `start` returns before its child answers as itself, leaves the server's lock
    free, or lets a second server start on the same address (web.md § 4)."""
    name = str(server)
    f = facts(name)
    assert MACHINE.observe(f) is ServerState.running and f.locked
    token = protocol.token_file(name).read_text().strip()
    assert health.ask(Listen(port=server), token)[0]
    assert not health.ask(Listen(port=server), "another token")[0]  # an impostor's proof would not match
    assert stat.S_IMODE(protocol.token_file(name).stat().st_mode) == 0o600
    with pytest.raises(Refused):
        apply("serve.start", port=server, tcp=True)


def test_a_running_server_holds_its_environment_until_it_stops(server):
    """Fails if the web environment can be changed under a running server — its supervisor not
    holding `env-web` shared — or the refusal does not offer this server's stop, or the hold
    outlives the server (web.md § 4, core.md § 5)."""
    with pytest.raises(Busy) as caught:
        locks.require_free("env-web")
    assert f"the web server on 127.0.0.1:{server}" in str(caught.value)
    assert [n.command for n in caught.value.next] == [f"python -m femkit serve stop --port {server}"]
    assert apply("serve.stop", port=server).ok()
    locks.require_free("env-web")


def test_stop_ends_both_processes_and_removes_its_files(server):
    """Fails if `stop` leaves the supervisor, the child, the pidfile or the token behind."""
    name = str(server)
    p = protocol.read_pidfile(protocol.pidfile(name))
    assert apply("serve.stop", port=server).ok()
    assert not p.supervisor.alive() and not p.child.alive()
    assert not protocol.pidfile(name).exists() and not protocol.token_file(name).exists()
    assert MACHINE.observe(facts(name)) is ServerState.stopped


def test_restart_replaces_the_child_and_keeps_the_token(server):
    """Fails if `restart` does not bring up a new child, or changes the address's token."""
    name = str(server)
    before = protocol.read_pidfile(protocol.pidfile(name))
    token = protocol.token_file(name).read_text()
    assert apply("serve.restart", port=server).ok()
    after = protocol.read_pidfile(protocol.pidfile(name))
    assert after.child != before.child and after.supervisor == before.supervisor
    assert protocol.token_file(name).read_text() == token and health.ask(Listen(port=server), token.strip())[0]


def test_a_child_killed_by_a_signal_is_respawned_and_twice_in_30_s_the_supervisor_gives_up(server):
    """Fails if a killed child is not replaced, or a child dying again at once is respawned
    in a loop instead of the supervisor giving up and removing its files (web.md § 4)."""
    name = str(server)
    first = protocol.read_pidfile(protocol.pidfile(name))
    os.kill(first.child.pid, signal.SIGKILL)
    assert wait_until(lambda: (p := protocol.read_pidfile(protocol.pidfile(name))) is not None
                      and p.child not in (None, first.child))
    second = protocol.read_pidfile(protocol.pidfile(name))
    os.kill(second.child.pid, signal.SIGKILL)
    assert wait_until(lambda: not first.supervisor.alive())
    assert not protocol.pidfile(name).exists() and not protocol.token_file(name).exists()
    assert "giving up" in protocol.log_file(name).read_text()


def test_a_supervisor_killed_outright_leaves_a_stale_server_its_child_ends_with(server):
    """Fails if a supervisor's death goes unobserved, or leaves its child serving: the lock is
    released by the kernel, the child ends by its parent-death signal, and `start` clears
    what was left (web.md § 4, core.md § 8)."""
    name = str(server)
    p = protocol.read_pidfile(protocol.pidfile(name))
    os.kill(p.supervisor.pid, signal.SIGKILL)
    assert wait_until(lambda: not p.child.alive())
    assert MACHINE.observe(facts(name)) is ServerState.stale
    assert apply("serve.start", port=server, tcp=True).ok()
    assert MACHINE.observe(facts(name)) is ServerState.running


def test_an_address_held_by_another_program_is_refused_before_anything_detaches():
    """Fails if `start` detaches a supervisor that cannot serve, instead of refusing in the
    terminal (web.md § 4)."""
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        with pytest.raises(Refused, match="held by another program"):
            apply("serve.start", port=port, tcp=True)
    assert not protocol.pidfile(str(port)).exists() and not protocol.token_file(str(port)).exists()


def test_restart_over_a_configuration_that_does_not_load_is_refused_and_the_server_left_alone(server):
    """Fails if `restart` signals the supervisor when a fresh child could not load
    config.toml — the server would then be down (web.md § 4)."""
    from femkit.core import dirs
    (dirs.config_dir()).mkdir(parents=True, exist_ok=True)
    (dirs.config_dir() / "config.toml").write_text("[no_such_section]\nx = 1\n")
    before = protocol.read_pidfile(protocol.pidfile(str(server)))
    with pytest.raises(Refused, match="config.toml does not load"):
        apply("serve.restart", port=server)
    assert protocol.read_pidfile(protocol.pidfile(str(server))).child == before.child


def test_stop_is_refused_while_the_child_holds_an_operation_lock_unless_forced(server):
    """Fails if `stop` would end an operation the page started without saying so; which
    locks the child holds is read from the kernel, never from a lock file (web.md § 4)."""
    import fcntl
    p = protocol.read_pidfile(protocol.pidfile(str(server)))
    path = locks.lock_path("env-demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        holders = locks.holders()
        assert holders.get("env-demo") == os.getpid()
        # the test process plays the child: the pidfile names it as the child
        Pidfile(p.supervisor, identify(os.getpid()), p.host, p.listen, p.foreground).write()
        with pytest.raises(Refused, match="env-demo"):
            apply("serve.stop", port=server)
        op, ctx = registry.operations()["serve.stop"], Context.from_process()
        Pidfile(p.supervisor, p.child, p.host, p.listen, p.foreground).write()
        planned = op.plan(op.request_from({"port": server}), ctx)  # planned while the child held nothing
        Pidfile(p.supervisor, identify(os.getpid()), p.host, p.listen, p.foreground).write()
        with pytest.raises(Refused, match="env-demo"):  # and checked again when applying
            op.apply(planned, ctx)
        assert apply("serve.stop", port=server, force=True).ok()  # forced, it stops all the same
    finally:
        os.close(fd)
    assert not p.supervisor.alive()


def test_status_tells_up_from_answering(server):
    """Fails if `status` calls a server healthy because its process is up: a child that is
    alive and not answering is reported, and noted in the log (web.md § 4)."""
    name = str(server)
    p = protocol.read_pidfile(protocol.pidfile(name))
    row = run("serve.status").servers[0]
    assert (row.state, row.answers) == ("running", True)
    os.kill(p.child.pid, signal.SIGSTOP)  # up, and silent
    try:
        row = run("serve.status", port=server).servers[0]
        assert (row.state, row.answers) == ("running", False)
        assert "not answering" in protocol.log_file(name).read_text()
    finally:
        os.kill(p.child.pid, signal.SIGCONT)


def test_a_process_is_signalled_only_when_it_is_the_one_identified():
    """Fails if `end` signals a process ID that names another process now (core.md § 8)."""
    me = identify(os.getpid())
    recycled = Identity(me.pid, me.start + 1, me.boot)
    assert not recycled.alive() and end(recycled) is False  # it would have killed this test


# ------------------------------------------------------------------ the log

def test_the_log_is_private_capped_and_rotated(tmp_path):
    """Fails if the log can be read by others, grows without bound, or keeps more archives
    than asked (web.md § 4)."""
    path = tmp_path / "logs" / "serve-1.log"
    roll = LogRoll(path, max_bytes=100, keep=2)
    for i in range(10):
        roll.write(f"line {i:03d} ".encode() * 10)
    roll.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert sorted(p.name for p in path.parent.iterdir()) == ["serve-1.log", "serve-1.log.1.gz", "serve-1.log.2.gz"]
    assert gzip.decompress((path.parent / "serve-1.log.1.gz").read_bytes()).startswith(b"line 008")


# ------------------------------------------------------------------ every request checked

@pytest.fixture
def client():
    from femkit.web.app import create_app
    app = create_app("the-token", Listen(port=8000))
    return app.test_client()


AUTH = {"Authorization": "Bearer the-token", "Host": "127.0.0.1:8000"}


@pytest.mark.parametrize("method, path, headers, body, status", [
    ("GET", "/api/operations", {"Host": "127.0.0.1:8000"}, None, 401),                        # no token
    ("GET", "/api/operations", {**AUTH, "Authorization": "Bearer other"}, None, 401),         # another token
    ("GET", "/api/operations", {**AUTH, "Host": "localhost:8000"}, None, 403),                # not the printed host
    ("GET", "/api/operations", {**AUTH, "Host": "attacker.example:8000"}, None, 403),         # a rebound name
    ("POST", "/api/config/path", AUTH, "{}", 415),                                            # a write that is not JSON
    ("POST", "/api/config/path", {**AUTH, "Content-Type": "application/json", "Origin": "null"}, "{}", 403),
    ("POST", "/api/config/path", {**AUTH, "Content-Type": "application/json",
                                  "Origin": "http://attacker.example"}, "{}", 403),
    ("POST", "/api/config/path", {**AUTH, "Content-Type": "application/json"}, "x" * (1024 * 1024 + 1), 413),
    ("POST", "/api/config/path", {**AUTH, "Content-Type": "application/json",
                                  "Origin": "http://127.0.0.1:8000"}, "{}", 200),
], ids=["no-token", "other-token", "localhost", "rebound-name", "not-json", "origin-null", "other-origin",
        "too-large", "same-origin"])
def test_every_request_is_checked_before_any_handler_runs(client, method, path, headers, body, status):
    """Fails if a request without this server's token, naming another host, writing without
    JSON, from another origin, or over the size limit reaches an operation (web.md § 5)."""
    response = client.open(path, method=method, headers=headers, data=body)
    assert response.status_code == status
    assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_the_health_route_proves_the_server_without_the_token(client):
    """Fails if the health route needs the token, or answers with anything but the HMAC of the
    client's nonce keyed by the token (web.md § 5)."""
    response = client.get("/api/health?nonce=0123456789abcdef", headers={"Host": "127.0.0.1:8000"})
    assert response.status_code == 200
    assert response.get_json() == {"proof": health.proof("the-token", "0123456789abcdef")}


def test_apply_answers_with_the_run_address_first_and_refuses_a_stale_digest(client):
    """Fails if an apply does not tell the page its operation directory before the outcome,
    or applies a plan other than the one the person saw (web.md § 1)."""
    headers = {**AUTH, "Content-Type": "application/json"}
    plan = client.post("/api/schema/docs/plan", headers=headers, data="{}").get_json()
    stale = client.post("/api/schema/docs/apply", headers=headers,
                        data=json.dumps({"request": {}, "digest": "0" * 64}))
    assert stale.status_code == 409 and stale.get_json()["refused"] == "PlanStale"
    lines = client.post("/api/schema/docs/apply", headers=headers,
                        data=json.dumps({"request": {}, "digest": plan["digest"]})).get_data(as_text=True).splitlines()
    first, last = json.loads(lines[0]), json.loads(lines[-1])
    assert first["operation"].startswith("reference-docs/") and last["ok"] is True
    events = client.get(f"/api/events/{first['operation']}", headers=AUTH).get_data(as_text=True).splitlines()
    assert [json.loads(e)["kind"] for e in events][-1] == "operation-end"


# ------------------------------------------------------------------ stopping and streams

def test_stop_is_prompt_with_an_event_stream_open(server):
    """Fails if an open event stream holds up `stop`: the child ends its streams, and the
    supervisor kills a child that has not gone within its grace (web.md § 4)."""
    import http.client
    address = OperationAddress.at("demo", clock.now())
    EventLog.of(address.folder()).append("operation-start", process=identify(os.getpid()).as_json())  # running: this test
    token = protocol.token_file(str(server)).read_text().strip()
    conn = http.client.HTTPConnection("127.0.0.1", server, timeout=30)
    conn.request("GET", f"/api/events/{address}", headers={"Authorization": f"Bearer {token}"})
    response = conn.getresponse()
    assert json.loads(response.readline())["kind"] == "operation-start"
    began = time.monotonic()
    assert apply("serve.stop", port=server).ok()
    assert time.monotonic() - began < GRACE + 3
    conn.close()


def test_a_child_that_does_not_end_is_killed_after_the_grace(server):
    """Fails if a child that ignores its SIGTERM (hung, or stopped) holds up `stop`: the
    supervisor sends SIGKILL after its grace (web.md § 4)."""
    p = protocol.read_pidfile(protocol.pidfile(str(server)))
    os.kill(p.child.pid, signal.SIGSTOP)  # it cannot act on SIGTERM
    began = time.monotonic()
    assert apply("serve.stop", port=server).ok()
    assert not p.child.alive() and time.monotonic() - began < GRACE + 3


def fake_operation(runs: int, step_log: bool = False):
    """A changing operation that runs ``runs`` times, as an install over several environments
    does; with ``step_log``, its step reports a log to the apply's own observer and waits."""
    import threading as _t
    from femkit.core.operations import Operation, Plan, Step, run_steps
    from femkit.core.operations import Outcome
    from femkit.core.schema import Model
    release = _t.Event()

    class Req(Model):
        """No inputs."""

    class Impl:
        def plan(self, req, ctx):
            return Plan(operation="demo.multi", request={}, steps=(Step(id="work", describe="work"),))

        def apply(self, plan, ctx, observer):
            for i in range(runs):
                def do(step, where):
                    if step_log:
                        log = where / "work.log"
                        log.write_text("first line\nsecond line\n")
                        observer.step_log(log)
                        release.wait(20)
                    return "done", None
                run_steps(plan.model_copy(update={"subjects": (f"demo-{i}",)}), ctx, observer, do)
            return Outcome(plan=plan, status="done")

    return Operation(Verb("demo.multi", Req), Outcome, True, "a test operation", Impl()), release


def test_an_apply_over_several_runs_reports_each_and_ends():
    """Fails if the apply route blocks on a second run's start — an install of several
    environments would hang holding its locks (web.md § 1)."""
    from femkit.web.app import create_app
    op, _ = fake_operation(runs=3)
    client = create_app("t", Listen(port=8000), operations={**registry.operations(), op.name: op}).test_client()
    headers = {"Authorization": "Bearer t", "Host": "127.0.0.1:8000", "Content-Type": "application/json"}
    digest = client.post("/api/demo/multi/plan", headers=headers, data="{}").get_json()["digest"]
    lines = [json.loads(l) for l in client.post("/api/demo/multi/apply", headers=headers,
             data=json.dumps({"request": {}, "digest": digest})).get_data(as_text=True).splitlines()]
    assert [l["operation"].split("/")[0] for l in lines[:-1]] == ["demo-0", "demo-1", "demo-2"]
    assert lines[-1]["ok"] is True


def test_a_running_steps_log_is_found_while_it_runs():
    """Fails if a step that reports its log to the apply's observer leaves no `step-log` record,
    so the page's live line has nothing to show (web.md § 1, core.md § 6)."""
    import threading as _t
    from femkit.core.operations import Context as Ctx
    from femkit.web.app import create_app
    op, release = fake_operation(runs=1, step_log=True)
    client = create_app("t", Listen(port=8000), operations={**registry.operations(), op.name: op}).test_client()
    auth = {"Authorization": "Bearer t", "Host": "127.0.0.1:8000"}
    plan = op.plan(op.request_from({}), Ctx.from_process())
    worker = _t.Thread(target=op.apply, args=(plan, Ctx.from_process()))
    worker.start()
    try:
        assert wait_until(lambda: any(operations_root("demo-0").glob("*/work.log")))
        at = next(operations_root("demo-0").iterdir()).name
        assert wait_until(lambda: client.get(f"/api/tail/demo-0/{at}/work", headers=auth).get_json()["lines"]
                          == ["first line", "second line"])
    finally:
        release.set()
        worker.join()


def test_a_run_on_a_subject_named_with_capitals_can_be_followed(client):
    """Fails if the event routes turn away a subject a lock may have — a machine named `Sol` —
    so the page cannot follow its run (core.md § 5, web.md § 1)."""
    address = OperationAddress.at("machine-Sol", clock.now())
    log = EventLog.of(address.folder())
    log.append("operation-start", process=identify(os.getpid()).as_json())
    log.append("step-start", step="probe")
    log.append("operation-end", outcome="done")
    lines = client.get(f"/api/events/{address}", headers=AUTH).get_data(as_text=True).splitlines()
    assert json.loads(lines[-1])["kind"] == "operation-end"
    assert client.get(f"/api/tail/{address}/probe", headers=AUTH).status_code == 200


def test_unread_event_streams_hold_no_slot(client):
    """Fails if a stream answered but never read (HEAD) keeps one of the few stream slots,
    until no page can follow an operation (web.md § 5)."""
    from femkit.web.app import STREAMS
    address = OperationAddress.at("demo", clock.now())
    log = EventLog.of(address.folder())
    log.append("operation-start", process=identify(os.getpid()).as_json())
    log.append("operation-end", outcome="done")
    for _ in range(STREAMS + 2):
        client.head(f"/api/events/{address}", headers=AUTH)
    lines = client.get(f"/api/events/{address}", headers=AUTH).get_data(as_text=True).splitlines()
    assert json.loads(lines[-1])["kind"] == "operation-end"


def in_process_server(monkeypatch, timeout: float):
    """A BoundedServer on a free port in this process, with a short read limit."""
    import threading as _t
    from femkit.web import serving
    from femkit.web.app import create_app
    monkeypatch.setattr(serving, "READ_TIMEOUT", timeout)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    port = listener.getsockname()[1]
    server = serving.BoundedServer(Listen(port=port), create_app("t", Listen(port=port)), listener.fileno())
    _t.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def test_a_request_is_read_in_bounded_time_and_a_malformed_one_answered(monkeypatch):
    """Fails if a client sending its headers a byte at a time holds a thread past the read
    limit, if a malformed request gets no answer, or a response names the server's versions
    (web.md § 4, § 5)."""
    server, port = in_process_server(monkeypatch, timeout=1.0)
    try:
        with socket.create_connection(("127.0.0.1", port)) as slow:
            began = time.monotonic()
            closed = False
            for ch in b"GET /api/health?nonce=0123456789 HTTP/1.1\r\nHost: 127.0.0.1\r\n":
                try:
                    slow.sendall(bytes([ch]))
                    time.sleep(0.1)
                    if slow.recv(1, socket.MSG_DONTWAIT | socket.MSG_PEEK) == b"":
                        closed = True
                        break
                except BlockingIOError:
                    continue
                except OSError:
                    closed = True
                    break
            assert closed and time.monotonic() - began < 4
        with socket.create_connection(("127.0.0.1", port)) as bad:
            bad.sendall(b"GET /x HTTP/1.1 junk\r\n\r\n")
            answer = bad.recv(4096)  # an unknown HTTP version is answered without a status line, as 0.9
            assert b"Error code: 400" in answer and b"Werkzeug" not in answer
        with socket.create_connection(("127.0.0.1", port)) as good:
            good.sendall(f"GET /api/health?nonce=0123456789 HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
            head = good.recv(4096).decode()
            assert "Server: femkit\r\n" in head and "Werkzeug" not in head and "Python" not in head
    finally:
        server.shutdown()
        server.close()


def test_a_runtime_folder_others_could_replace_is_refused(tmp_path):
    """Fails if a private folder is accepted below a folder anyone may write: another account
    could swap in its own and receive the token (web.md § 4, core.md § 4)."""
    from femkit.core.errors import UsageError
    from femkit.core.persist import private_dir
    open_folder = tmp_path / "open"
    open_folder.mkdir()
    open_folder.chmod(0o777)
    with pytest.raises(UsageError, match="lets other accounts replace"):
        private_dir(open_folder / "run")
    assert stat.S_IMODE(private_dir(tmp_path / "closed" / "run").stat().st_mode) == 0o700


def test_a_socket_file_left_by_an_ended_server_is_cleared_and_a_live_one_refused(monkeypatch):
    """Fails if a socket file no server answers on blocks every later `start`, or one another
    program answers on is taken over (web.md § 4)."""
    import shutil
    import tempfile
    from femkit.core import dirs
    short = Path(tempfile.mkdtemp(prefix="fk", dir="/tmp"))  # a socket's path has a length limit
    monkeypatch.setenv(dirs.VARIABLES["runtime"], str(short))
    path = protocol.socket_path()
    try:
        with socket.socket(socket.AF_UNIX) as left:
            left.bind(str(path))                                 # closed: the file stays, nothing answers
        started = apply("serve.start", socket=True)
        assert started.ok(), started.text()
        assert apply("serve.stop", socket=True).ok()
        path.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX) as live:
            live.bind(str(path))
            live.listen(1)
            with pytest.raises(Refused, match="held by another program"):
                apply("serve.start", socket=True)
        assert not protocol.pidfile(protocol.SOCKET_NAME).exists()
    finally:
        ended(protocol.SOCKET_NAME)
        shutil.rmtree(short)
