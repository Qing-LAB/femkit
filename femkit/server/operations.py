"""`serve start`, `foreground`, `status`, `restart`, `stop` (web.md § 4)."""

from __future__ import annotations

import errno
import json
import os
import secrets
import signal
import socket
import stat
import sys
import threading
import time
from pathlib import Path

from pydantic import Field, model_validator

from femkit.config import settings
from femkit.config.probe import place
from femkit.config.requests import ShowRequest
from femkit.core import dirs, locks, text, view
from femkit.envs.requests import InstallRequest
from femkit.core.errors import PlanStale, Refused, UsageError
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.persist import open_private, private_dir
from femkit.core.process import Identity, end, start_detached, tail
from femkit.core.schema import Model
from femkit.definitions import catalogue
from femkit.server import health, protocol, supervisor
from femkit.server.protocol import LOOPBACK, Listen, event_line
from femkit.server.state import MACHINE, ServerState, facts, require, target
from femkit.server.requests import SERVE_RESTART, SERVE_STOP, ServeRequest, StatusRequest, TargetRequest
from femkit.config.requests import CONFIG_SHOW
from femkit.envs.requests import ENV_INSTALL
from femkit.server.requests import SERVE_FOREGROUND, SERVE_RESTART, SERVE_START, SERVE_STATUS, SERVE_STOP

ANSWER_WAIT = 30.0     # seconds a start or a restart waits for the child to answer
STOP_WAIT = protocol.STOP_GRACE + 5.0


# ------------------------------------------------------------------ requests

def _target_name(req: TargetRequest | StatusRequest) -> str:
    return protocol.SOCKET_NAME if req.socket else str(req.port)


def _listen(req: ServeRequest, ctx: Context) -> Listen:
    """A Unix socket when asked, or on a cluster's login node unless TCP is asked (web.md § 4)."""
    login = place(catalogue.schedulers(ctx), ctx.env).where == "login node"
    if req.socket or (login and not req.tcp):
        return Listen(socket=str(protocol.socket_path()))
    return Listen(port=req.port)


# ------------------------------------------------------------------ what start refuses

WEB = "web"  # the environment the server runs in (envs.md § 1)


def _web_subject() -> str:
    """The web environment's lock subject: a running server holds it shared (web.md § 4)."""
    from femkit.envs import layout
    return layout.subject(WEB)


def web_python(ctx: Context) -> str:
    """The web environment's Python, which runs the server's child; refused until that
    environment is `ready` (web.md § 4)."""
    from femkit.envs import layout
    from femkit.envs.state import EnvState, observe
    state = observe(ctx, WEB)[1]
    if state is not EnvState.ready:
        raise Refused(f"the {WEB} environment, which runs the server, is {state.value}",
                      (view.command(ENV_INSTALL, names=[WEB]),))
    return str(layout.prefix(ctx, WEB) / "bin" / "python")


def _preflight(listen: Listen, ctx: Context) -> None:
    """Everything `start` refuses, refused before it detaches (web.md § 4)."""
    web_python(ctx)
    private_dir(dirs.runtime_dir())
    if listen.socket and len(listen.socket.encode()) > protocol.SOCKET_PATH_MAX:
        raise UsageError(f"the socket's path is longer than a Unix socket's {protocol.SOCKET_PATH_MAX} bytes: "
                         f"{listen.socket}", (view.shell("export FEMKIT_RUNTIME_DIR=/a/shorter/path"),))
    try:
        settings.load(ctx, fresh=True)
    except Exception as exc:  # what a fresh child would meet reading it
        raise Refused(f"config.toml does not load, so the server could not start: {exc}",
                      (view.command(CONFIG_SHOW),)) from None


def _clear_left_socket(path: Path) -> None:
    """A socket file no server answers on — its server ended without removing it — is
    removed; one a program answers on, or a file that is not a socket, is refused."""
    if not path.exists() and not path.is_symlink():
        return
    if not stat.S_ISSOCK(path.lstat().st_mode):
        raise Refused(f"{path} is in the way and is not a socket; remove it, or set FEMKIT_RUNTIME_DIR")
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(path))
    except (ConnectionRefusedError, FileNotFoundError):
        path.unlink(missing_ok=True)
        return
    finally:
        probe.close()
    raise Refused(f"{path} is held by another program", (view.command(SERVE_STATUS),))


def _bind(listen: Listen) -> socket.socket:
    """The listening socket, opened once: the supervisor hands it to each child, so the address
    is never free between two children."""
    if listen.socket:
        _clear_left_socket(Path(listen.socket))
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)  # 0600 from the moment it exists
        try:
            sock.bind(listen.socket)
        except OSError as exc:
            sock.close()
            raise Refused(f"{listen.socket} cannot be listened on: {exc.strerror}") from None
        finally:
            os.umask(old)
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((LOOPBACK, listen.port))
        except OSError as exc:
            sock.close()
            if exc.errno == errno.EADDRINUSE:
                raise Refused(f"{listen.describe()} is held by another program",
                              (view.shell(f"ss -ltnp 'sport = :{listen.port}'", note="which one"),
                               view.command(SERVE_START, note="another port",
                                            fills=[view.Fill(field="port", label="another port")]))) from None
            raise
    sock.listen(128)
    sock.set_inheritable(True)
    return sock


def _write_token(listen: Listen) -> str:
    token = secrets.token_urlsafe(32)
    with open_private(protocol.token_file(listen.name), "x") as fh:  # exclusively, never through a link
        fh.write(token)
    return token


def _read_token(name: str) -> str | None:
    try:
        return protocol.token_file(name).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def address(listen: Listen, token: str) -> str:
    port = listen.port or 8000
    return f"http://{LOOPBACK}:{port}/#token={token}"


def forwarding(listen: Listen) -> str | None:
    if not listen.socket:
        return None
    return f"ssh -o ExitOnForwardFailure=yes -L {LOOPBACK}:8000:{listen.socket} {dirs.host()}"


def _end_stale(f) -> list[str]:
    """A stale server's leftovers: a child it names that still runs is ended, the files removed."""
    said = []
    if f.pidfile is not None and f.pidfile.child is not None and f.pidfile.child.alive():
        end(f.pidfile.child, grace=protocol.STOP_GRACE)
        said.append(f"ended the child still running, pid {f.pidfile.child.pid}")
    listen = f.pidfile.listen if f.pidfile else (Listen(socket=str(protocol.socket_path()))
                                                 if f.name == protocol.SOCKET_NAME else Listen(port=int(f.name)))
    supervisor.remove_files(listen)
    return said


def _wait_answer(listen: Listen, token: str, alive, *, previous: Identity | None = None) -> tuple[bool, str]:
    """Until the child answers as this server — a child other than ``previous`` — the
    supervisor ends, or ANSWER_WAIT runs out."""
    deadline = time.monotonic() + ANSWER_WAIT
    said = "it has not answered"
    while time.monotonic() < deadline:
        if not alive():
            return False, "the supervisor ended"
        current = protocol.read_pidfile(protocol.pidfile(listen.name))
        if current is not None and current.child is not None and current.child != previous:
            ok, said = health.ask(listen, token, timeout=2.0)
            if ok:
                return True, said
        time.sleep(0.2)
    return False, f"{said}, after {ANSWER_WAIT:g} s"


# ------------------------------------------------------------------ results

class ServeOutcome(Outcome):
    listen: str | None = Field(default=None, description="where it listens")
    address: str | None = Field(default=None, description="the address to open, with its token")
    forwarding: str | None = Field(default=None, description="for a socket: the line to run on your own machine")
    server_log: str | None = Field(default=None, description="the server's log")

    def text(self) -> str:
        lines = [self.plan.text(brief=True)] if self.status == "failed" else []
        if self.address and self.status == "done":
            lines.append(f"serving on {self.listen}")
            if self.forwarding:
                lines.append(f"on your own machine:  {self.forwarding}")
            lines.append(f"open:  {self.address}")
        lines += [f"log: {self.server_log}"] if self.server_log else []
        return "\n".join(lines + text.findings(self.issues)) or "nothing to do"


def _outcome(plan: Plan, status: str, where: Path, listen: Listen, token: str | None) -> ServeOutcome:
    return ServeOutcome(plan=plan, status=status, log=str(where), listen=listen.describe(),
                        address=address(listen, token) if token else None, forwarding=forwarding(listen),
                        server_log=str(protocol.log_file(listen.name)))


# ------------------------------------------------------------------ start and foreground

def _start_plan(name: str, req: ServeRequest, ctx: Context, detached: bool) -> Plan:
    listen = _listen(req, ctx)
    f = facts(listen.name)
    state = MACHINE.observe(f)
    require(f, state, "start")
    _preflight(listen, ctx)
    steps = [Step(id="clean", describe="remove the stale server's files, ending a child it left")] \
        if state is ServerState.stale else []
    steps += [Step(id="listen", describe=f"listen on {listen.describe()}"),
              Step(id="token", describe=f"write the access token to {text.path(protocol.token_file(listen.name))}")]
    if detached:
        steps += [Step(id="supervise", describe="start the supervisor, detached, which runs the web application",
                       argv=(sys.executable, "-m", "femkit.server.supervisor", "…")),
                  Step(id="answer", describe="wait until it answers with the token")]
    else:
        steps += [Step(id="supervise", describe="run the supervisor here, until Ctrl-C or `serve stop`",
                       argv=("<web>/bin/python", "-m", protocol.CHILD_MODULE, "…"))]
    return Plan(subjects=(protocol.subject(listen.name),),
                shared=(_web_subject(),), basis={"state": state.value, "listen": listen.as_json()}, steps=tuple(steps))


def _reobserve(plan: Plan) -> tuple[Listen, object]:
    listen = Listen.from_json(plan.basis["listen"])
    f = facts(listen.name, mine=True)
    if MACHINE.observe(f).value != plan.basis["state"]:
        raise PlanStale("the server's state changed since the plan; plan again",
                        (view.command(SERVE_STATUS),))
    return listen, f


@operation(SERVE_START, result=ServeOutcome, changes=True, subject="plan")
class ServeStart:
    """Start the web server in the background, supervised; print the address to open."""

    def plan(self, req: ServeRequest, ctx: Context) -> Plan:
        plan = _start_plan("serve.start", req, ctx, detached=True)
        return plan

    def apply(self, plan: Plan, ctx: Context, observer) -> ServeOutcome:
        req = ServeRequest.model_validate(plan.request)
        # the runner holds the server's lock (subject "plan")
        listen, f = _reobserve(plan)
        held: dict = {}

        def do(step: Step, where: Path):
            if step.id == "clean":
                for line in _end_stale(f):
                    observer.note(line)
            elif step.id == "listen":
                held["socket"] = _bind(listen)
            elif step.id == "token":
                held["token"] = _write_token(listen)
            elif step.id == "supervise":
                sock, lock_fd = held["socket"], locks.held_fd(protocol.subject(listen.name))
                use_fd = locks.held_fd(_web_subject())
                argv = [sys.executable, "-m", "femkit.server.supervisor", "--python", web_python(ctx),
                        "--listen", json.dumps(listen.as_json()), "--fd", str(sock.fileno()),
                        "--lock-fd", str(lock_fd), "--use-fd", str(use_fd),
                        "--log-max-bytes", str(req.log_max_mb * 1024 * 1024), "--log-keep", str(req.log_keep)]
                held["supervisor"] = start_detached(argv, keep_fds=(sock.fileno(), lock_fd, use_fd), cwd=dirs.checkout(),
                                                    log=protocol.supervisor_log(listen.name))
                sock.close()  # the supervisor holds it now
            elif step.id == "answer":
                ok, said = _wait_answer(listen, held["token"], held["supervisor"].alive)
                observer.note(said)
                if not ok:
                    for log in (protocol.supervisor_log(listen.name), protocol.log_file(listen.name)):
                        for line in (tail(log, 15) if log.exists() else []):
                            observer.note(f"  {line}")
                    return "failed", protocol.log_file(listen.name)
            return "done", None

        try:
            status, where = run_steps(plan, ctx, observer, do)
        finally:
            if "socket" in held and held["socket"].fileno() >= 0:
                held["socket"].close()
                if "supervisor" not in held:
                    supervisor.remove_files(listen)
        return _outcome(plan, status, where, listen, held.get("token") if status == "done" else None)


@operation(SERVE_FOREGROUND, result=ServeOutcome, changes=True, subject="plan")
class ServeForeground:
    """Run the web server in this terminal, supervised; Ctrl-C stops it. `serve status`,
    `restart` and `stop` act on it from another terminal."""

    def plan(self, req: ServeRequest, ctx: Context) -> Plan:
        if threading.current_thread() is not threading.main_thread():
            raise UsageError("serve foreground runs in a terminal; from here, use serve start")
        return _start_plan("serve.foreground", req, ctx, detached=False)

    def apply(self, plan: Plan, ctx: Context, observer) -> ServeOutcome:
        req = ServeRequest.model_validate(plan.request)
        # the runner holds the server's lock (subject "plan") for as long as the supervisor runs
        listen, f = _reobserve(plan)
        held: dict = {}

        def announce(child: Identity) -> None:
            def wait() -> None:
                ok, said = _wait_answer(listen, held["token"], lambda: True)
                if ok:
                    lines = [f"serving on {listen.describe()}"]
                    lines += [f"on your own machine:  {forwarding(listen)}"] if listen.socket else []
                    lines += [f"open:  {address(listen, held['token'])}"]
                    observer.note("\n".join(lines))
            threading.Thread(target=wait, daemon=True).start()

        def do(step: Step, where: Path):
            if step.id == "clean":
                for line in _end_stale(f):
                    observer.note(line)
            elif step.id == "listen":
                held["socket"] = _bind(listen)
            elif step.id == "token":
                held["token"] = _write_token(listen)
            elif step.id == "supervise":
                for subject in (protocol.subject(listen.name), _web_subject()):  # the runner's holds, named as the server
                    locks.adopt(locks.held_fd(subject), *listen.holds())
                code = supervisor.supervise(listen, held["socket"].fileno(), web_python(ctx),
                                            log_max_bytes=req.log_max_mb * 1024 * 1024,
                                            log_keep=req.log_keep, echo=sys.stdout.buffer,
                                            on_child=announce)
                return ("done" if code == 0 else "failed"), protocol.log_file(listen.name)
            return "done", None

        try:
            status, where = run_steps(plan, ctx, observer, do)
        finally:
            if "socket" in held:
                held["socket"].close()
            supervisor.remove_files(listen)
        return _outcome(plan, status, where, listen, None)


# ------------------------------------------------------------------ restart and stop

def _child_locks(f, force: bool, verb: str) -> None:
    """Refused while the child holds an operation's lock, unless forced, naming each."""
    child = f.pidfile.child if f.pidfile else None
    if child is None or force:
        return
    own = protocol.subject(f.name)  # the kernel names the process that took a lock; the server's was taken by `start`
    held = sorted(s for s, pid in locks.holders().items() if pid == child.pid and s != own)
    if held:
        raise Refused(f"the server's child holds {', '.join(held)}: an operation started from the page runs, "
                      f"and would stop with it",
                      (view.command({"restart": SERVE_RESTART, "stop": SERVE_STOP}[verb], force=True, **target(f.name)),))


def _signal(f, sig: int) -> Identity:
    """Signal the supervisor the pidfile names, only when it is that process."""
    who = f.pidfile.supervisor
    if not who.alive():
        raise PlanStale("the supervisor ended since the plan; plan again", (view.command(SERVE_STATUS),))
    os.kill(who.pid, sig)
    return who


@operation(SERVE_RESTART, result=ServeOutcome, changes=True)
class ServeRestart:
    """Replace the server's child with a fresh one, keeping its address and token: how a
    change to the application's code takes effect."""

    def plan(self, req: TargetRequest, ctx: Context) -> Plan:
        name = _target_name(req)
        f = facts(name)
        state = MACHINE.observe(f)
        require(f, state, "restart")
        _preflight(f.pidfile.listen, ctx)
        _child_locks(f, req.force, "restart")
        return Plan(basis={"state": state.value, "supervisor": f.pidfile.supervisor.as_json(),
                           "child": f.pidfile.child.as_json() if f.pidfile.child else None},
                    steps=(Step(id="signal", describe=f"ask the supervisor, pid {f.pidfile.supervisor.pid}, "
                                                      "for a new child (SIGHUP)"),
                           Step(id="answer", describe="wait until the new child answers with the token")))

    def apply(self, plan: Plan, ctx: Context, observer) -> ServeOutcome:
        req = TargetRequest.model_validate(plan.request)
        f = facts(_target_name(req))
        if f.pidfile is None or f.pidfile.supervisor.as_json() != plan.basis["supervisor"]:
            raise PlanStale("the server changed since the plan; plan again", (view.command(SERVE_STATUS),))
        _child_locks(f, req.force, "restart")  # again: the page may have started one since the plan
        listen, token, held = f.pidfile.listen, _read_token(f.name), {}

        def do(step: Step, where: Path):
            if step.id == "signal":
                held["supervisor"] = _signal(f, signal.SIGHUP)
            elif step.id == "answer":
                ok, said = _wait_answer(listen, token or "", held["supervisor"].alive, previous=f.pidfile.child)
                observer.note(said)
                return ("done" if ok else "failed"), protocol.log_file(listen.name)
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return _outcome(plan, status, where, listen, token if status == "done" else None)


@operation(SERVE_STOP, result=ServeOutcome, changes=True)
class ServeStop:
    """Stop the server: its child, then its supervisor; the pidfile, the token and the
    socket go with them."""

    def plan(self, req: TargetRequest, ctx: Context) -> Plan:
        name = _target_name(req)
        f = facts(name)
        state = MACHINE.observe(f)
        require(f, state, "stop")
        if state is ServerState.stopped:
            steps = ()
        elif state is ServerState.stale:
            steps = (Step(id="clean", describe="remove the stale server's files, ending a child it left"),)
        else:
            _child_locks(f, req.force, "stop")
            steps = (Step(id="signal", describe=f"stop the supervisor, pid {f.pidfile.supervisor.pid} (SIGTERM)"),
                     Step(id="gone", describe="wait until it has ended and released its lock"))
        return Plan(basis={"state": state.value,
                           "supervisor": f.pidfile.supervisor.as_json() if f.pidfile else None},
                    steps=steps)

    def apply(self, plan: Plan, ctx: Context, observer) -> ServeOutcome:
        req = TargetRequest.model_validate(plan.request)
        name = _target_name(req)
        f = facts(name)
        if MACHINE.observe(f).value != plan.basis["state"]:
            raise PlanStale("the server's state changed since the plan; plan again", (view.command(SERVE_STATUS),))
        listen = f.pidfile.listen if f.pidfile else (Listen(socket=str(protocol.socket_path()))
                                                     if name == protocol.SOCKET_NAME else Listen(port=int(name)))
        if plan.basis["state"] == ServerState.running.value:
            _child_locks(f, req.force, "stop")  # again: the page may have started one since the plan

        def do(step: Step, where: Path):
            if step.id == "clean":
                for line in _end_stale(f):
                    observer.note(line)
            elif step.id == "signal":
                _signal(f, signal.SIGTERM)
            elif step.id == "gone":
                deadline = time.monotonic() + STOP_WAIT
                while locks.is_held(protocol.subject(name)) and time.monotonic() < deadline:
                    time.sleep(0.1)
                if locks.is_held(protocol.subject(name)):
                    end(f.pidfile.supervisor, grace=0)
                    if f.pidfile.child:
                        end(f.pidfile.child, grace=0)
                    supervisor.remove_files(listen)
                    observer.note("it did not end in time: killed")
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return _outcome(plan, status, where, listen, None)


# ------------------------------------------------------------------ status

class ServerRow(Model):
    name: str = Field(description="the port, or `sock`")
    host: str = Field(description="the host its pidfile was written on")
    state: str = Field(description="stopped | stale | running | starting | elsewhere", json_schema_extra={"doc": "web.md § 4"})
    listen: str | None = Field(default=None, description="where it listens")
    supervisor: int | None = Field(default=None, description="the supervisor's process ID")
    child: int | None = Field(default=None, description="the child's process ID")
    foreground: bool = Field(default=False, description="run by `serve foreground` in a terminal")
    answers: bool | None = Field(default=None, description="whether it answers as itself; unknown unless running")
    said: str = Field(default="", description="what the health route said")
    log: str = Field(description="the server's log")


class StatusResult(Result):
    servers: list[ServerRow] = Field(default_factory=list)
    address: str | None = Field(default=None, description="for one named, running server: the address with its token")

    def text(self) -> str:
        if not self.servers:
            return "no server is running"
        rows = []
        for s in self.servers:
            pids = f"pid {s.supervisor}" + (f", child {s.child}" if s.child else "") if s.supervisor else ""
            where = s.listen or s.name
            mode = " (foreground)" if s.foreground else ""
            answers = "" if s.answers is None else ("answers" if s.answers else f"NOT ANSWERING: {s.said}")
            rows.append((where + (f" on {s.host}" if s.state == "elsewhere" else ""), s.state + mode, pids, answers))
        lines = text.table(rows, indent="")
        if self.address:
            lines.append(f"open:  {self.address}")
        if any(s.answers is False for s in self.servers):
            lines.append("a server that is up and not answering: `kill -USR1` its child to dump its stacks "
                         "into the stacks log, then decide on `serve restart`")
        return "\n".join(lines + text.findings(self.issues))


def _row(name: str) -> ServerRow:
    f = facts(name)
    state = MACHINE.observe(f)
    p = f.pidfile
    row = ServerRow(name=name, host=p.host if p else dirs.host(), state=state.value,
                    listen=p.listen.describe() if p else None,
                    supervisor=p.supervisor.pid if p else None,
                    child=p.child.pid if p and p.child else None,
                    foreground=bool(p and p.foreground), log=str(protocol.log_file(name)))
    if state is ServerState.running and p is not None:
        token = _read_token(name)
        ok, said = health.ask(p.listen, token or "") if token else (False, "its token file is gone")
        row = row.model_copy(update={"answers": ok, "said": said})
        if not ok:
            try:
                with open_private(protocol.log_file(name), "ab") as fh:
                    fh.write(event_line("status", f"up, pid {p.supervisor.pid}, but not answering: {said}"))
            except OSError:
                pass
    return row


@operation(SERVE_STATUS, result=StatusResult)
def serve_status(req: StatusRequest, ctx: Context) -> StatusResult:
    """Every server this account runs here, each with two answers kept apart: is it up, and
    does it answer as itself. The address with its token only for one named server."""
    if req.port is not None or req.socket:
        name = _target_name(req)
        row = _row(name)
        token = _read_token(name) if row.answers else None
        p = protocol.read_pidfile(protocol.pidfile(name))
        return StatusResult(servers=[row], address=address(p.listen, token) if token and p else None)
    runtime = dirs.runtime_dir()
    names = sorted(p.name[len("serve-"):-len(".pid")] for p in runtime.glob("serve-*.pid")) if runtime.is_dir() else []
    return StatusResult(servers=[_row(n) for n in names])
