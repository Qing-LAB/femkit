"""`serve start`, `foreground`, `status`, `restart`, `stop` (web.md § 4): each but `status` offered on
the command line alone, since run from the page it would stop, replace or hold the very server the
page talks to (api.md § 2, `surfaces`)."""

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

from pydantic import Field

from femkit.config import settings
from femkit.config.probe import place
from femkit.core import dirs, locks, persist, process, text, view
from femkit.core.errors import PlanStale, Refused, UsageError
from femkit.core.operations import CLI_ALONE, Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.persist import open_private, private_dir
from femkit.core.process import GRACE, TAIL_LINES, Identity, end, start_detached, tail
from femkit.core.schema import DefinitionError, Model
from femkit.definitions import catalogue
from femkit.envs import start
from femkit.server import health, protocol, startup, supervisor
from femkit.server.protocol import LOOPBACK, Listen
from femkit.server.state import CLEAN, NEW_CHILD, RESTART, START, STOP, does, facts, machine, require
from femkit.config.requests import CONFIG_SHOW
from femkit.server.requests import (DEFAULT_PORT, SERVE_FOREGROUND, SERVE_RESTART, SERVE_START, SERVE_STATUS,
                                    SERVE_STOP, ServeRequest, StatusRequest, TargetRequest)

ANSWER_WAIT = 30.0     # seconds a start or a restart waits for the child to answer
STOP_WAIT = GRACE + 5.0


# ------------------------------------------------------------------ requests

def _target(req: TargetRequest | StatusRequest) -> Listen:
    """The server a request names: on the socket, or on its port (its schema refuses both)."""
    return Listen.unix() if req.socket else Listen(port=req.port or DEFAULT_PORT)


def _holds(listen: Listen) -> tuple[str, list[dict]]:
    """What the server's locks' files say holds them, and what ends the hold, as its JSON
    (core.md § 5): written by `serve start` and handed to the supervisor, which writes it."""
    return (f"the web server on {listen.describe()}",
            [view.command(SERVE_STOP, **protocol.target(listen.name)).model_dump(mode="json")])


def _listen(req: ServeRequest, ctx: Context) -> Listen:
    """A Unix socket when asked, or on a cluster's login node unless TCP is asked (web.md § 4)."""
    login = place(catalogue.schedulers(ctx), ctx.env).where == "login node"
    if req.socket or (login and not req.tcp):
        if req.port is not None:  # a port stated is never dropped
            raise UsageError(f"the server would listen on a Unix socket here, not on port {req.port}",
                             (view.command(SERVE_START, tcp=True, port=req.port), view.command(SERVE_START, socket=True)),
                             code="port-without-tcp", subject="port")
        return Listen.unix()
    return Listen(port=req.port or DEFAULT_PORT)


# ------------------------------------------------------------------ what start refuses

SERVER = "server"   # the server's child, by its name in programs.toml: its environment and module (envs.md § 4.4)


def _child(ctx: Context):
    """The server's child as `programs.toml` declares it: the environment it runs in, its module."""
    from femkit.envs import inside
    return inside.program(ctx, SERVER)


def _uses(ctx: Context) -> tuple[str, ...]:
    """The environments a running server uses, each held shared for as long as it runs (web.md § 4):
    the web environment, which runs its child, and the control environment, which runs its
    supervisor — its subject the control environment's name (envs.md § 7.3)."""
    from femkit.envs import layout
    return (layout.subject(_child(ctx).environment), dirs.CONTROL)


def web_python(ctx: Context) -> str:
    """The Python of the environment the server's child runs in, `web`; refused where that
    environment's state does not allow its use, with that state's own next steps (web.md § 4;
    envs.md § 3.3)."""
    from femkit.envs.state import usable
    return str(usable(ctx, _child(ctx).environment, "the web server").prefix / "bin" / "python")


def _preflight(listen: Listen, ctx: Context) -> None:
    """Everything `start` refuses, refused before it detaches (web.md § 4): first what a fresh
    child meets first, config.toml, which everything after it reads; then each declared file the
    child loads before it serves (`startup`) — the project layout, and the page's declaration the
    registry handed this domain at femkit's start (web.md § 8.1)."""
    try:
        settings.load(ctx, fresh=True)
    except (DefinitionError, OSError) as exc:
        raise Refused(f"config.toml does not load, so the server could not start: {exc}",
                      (view.command(CONFIG_SHOW),), code="config-does-not-load", subject="config.toml") from None
    for declared in startup.registered():
        try:
            declared.load()
        except DefinitionError as exc:
            raise Refused(f"{declared.what} does not load, so the server could not start: {exc}", declared.next,
                          code=declared.code, subject=exc.file) from None
    web_python(ctx)
    private_dir(dirs.runtime_dir(), make=False)   # made by the apply, never by a plan
    if listen.socket and len(listen.socket.encode()) > protocol.SOCKET_PATH_MAX:
        raise UsageError(f"the socket's path is longer than a Unix socket's {protocol.SOCKET_PATH_MAX} bytes: "
                         f"{listen.socket}", (view.shell(
                             f"export {dirs.VARIABLES['runtime']}={{path}}",
                             fills=[view.Fill(field="path", label="a runtime directory with a shorter absolute path",
                                              example="/a/shorter/path")]),),
                         code="socket-path-too-long", subject=listen.socket)


def _clear_left_socket(path: Path) -> None:
    """A socket file no server answers on — its server ended without removing it — is
    removed; one a program answers on, or a file that is not a socket, is refused."""
    if not path.exists() and not path.is_symlink():
        return
    if not stat.S_ISSOCK(path.lstat().st_mode):
        raise Refused(f"{path} is in the way and is not a socket; remove it, or set {dirs.VARIABLES['runtime']}",
                      code="not-a-socket", subject=str(path))
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(path))
    except (ConnectionRefusedError, FileNotFoundError):
        persist.remove(path)
        return
    finally:
        probe.close()
    raise Refused(f"{path} is held by another program", (view.command(SERVE_STATUS),), code="address-held",
                  subject=str(path))


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
            raise Refused(f"{listen.socket} cannot be listened on: {exc.strerror}", code="cannot-listen",
                          subject=listen.socket) from None
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
                                            fills=[view.Fill(field="port", label="another port")])),
                              code="address-held", subject=listen.describe()) from None
            raise
    sock.listen(128)
    sock.set_inheritable(True)
    return sock


def _write_token(listen: Listen) -> str:
    """A new token. Written under the server's lock, so one left there is an ended server's —
    one it could not remove — and is replaced."""
    token = secrets.token_urlsafe(32)
    persist.remove(protocol.token_file(listen.name))
    with open_private(protocol.token_file(listen.name), "x") as fh:  # exclusively, never through a link
        fh.write(token)
    return token


def _read_token(name: str) -> str | None:
    """The server's token; None when its file is gone — a stop may remove it as this reads."""
    try:
        held = persist.read_text(protocol.token_file(name))
    except OSError:
        return None
    return held.strip() if held is not None else None


def address(listen: Listen, token: str) -> str:
    port = listen.port or DEFAULT_PORT    # a socket's: the local port its forwarding line names
    return f"http://{LOOPBACK}:{port}/#token={token}"


def forwarding(listen: Listen) -> str | None:
    if not listen.socket:
        return None
    return f"ssh -o ExitOnForwardFailure=yes -L {LOOPBACK}:{DEFAULT_PORT}:{listen.socket} {dirs.host()}"


def _end_stale(f) -> list[str]:
    """A stale server's leftovers: a child it names that still runs is ended, the files removed."""
    said = []
    if f.pidfile is not None and f.pidfile.child is not None and f.pidfile.child.alive():
        end(f.pidfile.child, group=True)   # a child leads its own group, as every child femkit starts
        said.append(f"ended the child still running, pid {f.pidfile.child.pid}")
    listen = f.pidfile.listen if f.pidfile else Listen.named(f.name)
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

def _serving(listen: str, forwarding: view.Action | None, address: str) -> list:
    """What a person reads once a server answers: where it listens; for a socket, the line to
    run on their own machine, an action as every command to run is; the address to open."""
    blocks: list = [view.Text(text=f"serving on {listen}")]
    if forwarding:
        blocks.append(view.Next(label="on your own machine", actions=[forwarding]))
    return blocks + [view.Text(text=f"open:  {address}")]


class ServeOutcome(Outcome):
    listen: str | None = Field(default=None, description="where it listens")
    address: str | None = Field(default=None, description="the address to open, with its token")
    forwarding: view.Action | None = Field(default=None, description="for a socket: the line to run on your own "
                                                                     "machine")
    server_log: str | None = Field(default=None, description="the server's log")

    @property
    def report(self) -> view.Report:
        blocks: list = []
        if self.status == "failed":
            blocks += [view.Text(text=line) for line in self.plan.text(brief=True).splitlines()]
        if self.address and self.status == "done":
            blocks += _serving(self.listen or "", self.forwarding, self.address)
        if self.server_log:
            blocks.append(view.Text(text=f"log: {self.server_log}"))
        return view.Report(blocks=blocks)


def _forwarding(listen: Listen) -> view.Action | None:
    """For a socket, the line to run on the person's own machine, as every step a person runs is."""
    line = forwarding(listen)
    return view.shell(line) if line else None


def _outcome(plan: Plan, status: str, where: Path, listen: Listen, token: str | None) -> ServeOutcome:
    return ServeOutcome(plan=plan, status=status, log=str(where), listen=listen.describe(),
                        address=address(listen, token) if token else None, forwarding=_forwarding(listen),
                        server_log=str(protocol.log_file(listen.name)))


# ------------------------------------------------------------------ start and foreground

def _start_basis(req: ServeRequest, ctx: Context) -> dict:
    """Where it would listen, that server's state, and the state of the environment it runs
    in: what a start rests on."""
    from femkit.envs.state import observe
    listen, environment = _listen(req, ctx), _child(ctx).environment
    return {"state": machine(ctx).observe(facts(listen.name)).value, "listen": listen.as_json(),
            environment: observe(ctx, environment)[1].value}


def _start_plan(req: ServeRequest, ctx: Context, detached: bool) -> Plan:
    listen = _listen(req, ctx)
    f = facts(listen.name)
    m = machine(ctx)
    state = m.observe(f)
    require(ctx, f, state, "start")
    _preflight(listen, ctx)
    done = does(ctx, f, state)     # what its table gives the state: a stale one's files removed first
    steps = [Step(id="clean", describe="remove the stale server's files, ending a child it left")] \
        if CLEAN in done else []
    if START not in done:
        return Plan(subjects=(protocol.subject(listen.name),), steps=tuple(steps))
    steps += [Step(id="listen", describe=f"listen on {listen.describe()}"),
              Step(id="token", describe=f"write the access token to {text.path(protocol.token_file(listen.name))}")]
    uses, module = _uses(ctx), _child(ctx).module
    if detached:
        shown = supervisor.argv(sys.executable, web_python(ctx), module, listen,
                                {"socket": "<socket>", "lock": "<lock>", "use": [f"<{s}>" for s in uses]},
                                json.dumps(_holds(listen)), req.log_max_mb * 1024 * 1024, req.log_keep)
        steps += [Step(id="supervise", describe="start the supervisor, detached, which runs the web application",
                       argv=tuple(shown)),
                  Step(id="answer", describe="wait until it answers with the token")]
    else:
        steps += [Step(id="supervise", describe="run the supervisor here, until Ctrl-C or `serve stop`, which "
                                                "runs the web application", argv=tuple(supervisor.child_argv(
                                                    web_python(ctx), module, listen, "<socket>", "<this process>")))]
    return Plan(subjects=(protocol.subject(listen.name),), shared=uses, steps=tuple(steps))


def _started(plan: Plan) -> tuple[Listen, object]:
    """Where it listens, as the plan rested on it, and its facts read by the start that holds its lock."""
    listen = Listen.from_json(plan.basis["listen"])
    return listen, facts(listen.name)


@operation(SERVE_START, result=ServeOutcome, subject="plan", surfaces=CLI_ALONE)
class ServeStart:
    """Start the web server in the background, supervised; print the address to open."""

    def plan(self, req: ServeRequest, ctx: Context) -> Plan:
        return _start_plan(req, ctx, detached=True)

    def observe(self, req: ServeRequest, ctx: Context) -> dict:
        return _start_basis(req, ctx)

    def apply(self, plan: Plan, ctx: Context, observer) -> ServeOutcome:
        # the runner holds the server's lock (subject "plan")
        listen, f = _started(plan)
        held: dict = {}

        def do(step: Step, where: Path):
            if step.id == "clean":
                for line in _end_stale(f):
                    observer.note(line)
            elif step.id == "listen":
                private_dir(dirs.runtime_dir())
                held["socket"] = _bind(listen)
            elif step.id == "token":
                held["token"] = _write_token(listen)
            elif step.id == "supervise":
                sock, lock_fd = held["socket"], locks.held_fd(protocol.subject(listen.name))
                use_fds = {f"<{s}>": locks.held_fd(s) for s in plan.shared}
                fds = {"<socket>": str(sock.fileno()), "<lock>": str(lock_fd), **{k: str(v) for k, v in use_fds.items()}}
                argv = [fds.get(a, a) for a in step.argv]   # the plan's command, its descriptors now known
                held["supervisor"] = start_detached(argv, keep_fds=(sock.fileno(), lock_fd, *use_fds.values()),
                                                    env=dirs.femkit_env(start.clean(ctx)), cwd=dirs.checkout(),
                                                    log=protocol.supervisor_log(listen.name))
                sock.close()  # the supervisor holds it now
            elif step.id == "answer":
                ok, said = _wait_answer(listen, held["token"], held["supervisor"].alive)
                observer.note(said)
                if not ok:
                    for log in (protocol.supervisor_log(listen.name), protocol.log_file(listen.name)):
                        for line in (tail(log, TAIL_LINES) if log.exists() else []):
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


@operation(SERVE_FOREGROUND, result=ServeOutcome, subject="plan", surfaces=CLI_ALONE)
class ServeForeground:
    """Run the web server in this terminal, supervised; Ctrl-C stops it. `serve status`,
    `restart` and `stop` act on it from another terminal."""

    def plan(self, req: ServeRequest, ctx: Context) -> Plan:
        return _start_plan(req, ctx, detached=False)

    def observe(self, req: ServeRequest, ctx: Context) -> dict:
        return _start_basis(req, ctx)

    def apply(self, plan: Plan, ctx: Context, observer) -> ServeOutcome:
        req = ServeRequest.model_validate(plan.request)
        # the runner holds the server's lock (subject "plan") for as long as the supervisor runs
        listen, f = _started(plan)
        held: dict = {}

        def announce(child: Identity) -> None:
            def wait() -> None:
                ok, said = _wait_answer(listen, held["token"], lambda: True)
                if ok:   # the report `start` ends with, written as every report is (web.md § 7.6)
                    served = view.Report(blocks=_serving(listen.describe(), _forwarding(listen),
                                                         address(listen, held["token"])))
                    for line in text.report(served).splitlines():
                        observer.note(line)
            threading.Thread(target=wait, daemon=True).start()

        def do(step: Step, where: Path):
            if step.id == "clean":
                for line in _end_stale(f):
                    observer.note(line)
            elif step.id == "listen":
                private_dir(dirs.runtime_dir())
                held["socket"] = _bind(listen)
            elif step.id == "token":
                held["token"] = _write_token(listen)
            elif step.id == "supervise":
                for subject in (protocol.subject(listen.name), *plan.shared):  # the runner's holds, named as the server
                    locks.adopt(locks.held_fd(subject), *_holds(listen))
                code = supervisor.supervise(listen, held["socket"].fileno(), step.argv[0],  # the plan's Python
                                            _child(ctx).module, start.clean(ctx),
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

def _child_locks(f, force: bool, verb: view.Verb) -> None:
    """Refused while the child holds an operation's lock, unless forced, naming each."""
    child = f.pidfile.child if f.pidfile else None
    if child is None or force or not child.alive():   # a process ID alone names no child: its start time too
        return
    own = protocol.subject(f.name)  # the kernel names the process that took a lock; the server's was taken by `start`
    held = sorted(s for s, pid in locks.holders().items() if pid == child.pid and s != own)
    if held:
        raise Refused(f"the server's child holds {', '.join(held)}: an operation started from the page runs, "
                      f"and would stop with it",
                      (view.command(verb, force=True, **protocol.target(f.name)),), code="operation-running",
                      subject=f.name)


def _signal(f, sig: int) -> Identity:
    """Signal the supervisor the pidfile names, only when it is that process (core.md § 8)."""
    who = f.pidfile.supervisor
    if not process.signal(who, sig):
        raise PlanStale("the supervisor ended since the plan; plan again", (view.command(SERVE_STATUS),),
                        code="supervisor-ended", subject=f.name)
    return who


@operation(SERVE_RESTART, result=ServeOutcome, surfaces=CLI_ALONE)
class ServeRestart:
    """Replace the server's child with a fresh one, keeping its address and token: how a
    change to the application's code takes effect."""

    def plan(self, req: TargetRequest, ctx: Context) -> Plan:
        name = _target(req).name
        f = facts(name)
        state = machine(ctx).observe(f)
        require(ctx, f, state, "restart")
        if NEW_CHILD not in does(ctx, f, state):   # what its table gives the state
            return Plan()
        _preflight(f.pidfile.listen, ctx)
        _child_locks(f, req.force, SERVE_RESTART)
        return Plan(steps=(Step(id="signal", describe=f"ask the supervisor, pid {f.pidfile.supervisor.pid}, "
                                                      "for a new child (SIGHUP)"),
                           Step(id="answer", describe="wait until the new child answers with the token")))

    def observe(self, req: TargetRequest, ctx: Context) -> dict:
        """The supervisor the pidfile names: the one a restart signals."""
        f = facts(_target(req).name)
        return {"supervisor": f.pidfile.supervisor.as_json() if f.pidfile else None}

    def apply(self, plan: Plan, ctx: Context, observer) -> ServeOutcome:
        req = TargetRequest.model_validate(plan.request)
        f = facts(_target(req).name)
        _child_locks(f, req.force, SERVE_RESTART)  # again: the page may have started one since the plan
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


@operation(SERVE_STOP, result=ServeOutcome, subject="plan", surfaces=CLI_ALONE)
class ServeStop:
    """Stop the server: its child, then its supervisor; the pidfile, the token and the
    socket go with them."""

    def plan(self, req: TargetRequest, ctx: Context) -> Plan:
        name = _target(req).name
        f = facts(name)
        state = machine(ctx).observe(f)
        require(ctx, f, state, "stop")
        done = does(ctx, f, state)    # what its table gives the state: nothing, a stale one's files, a stop
        if CLEAN in done:
            return Plan(subjects=(protocol.subject(name),),   # free since its supervisor ended: held while cleaning
                        steps=(Step(id="clean", describe="remove the stale server's files, ending a child it left"),))
        steps: tuple[Step, ...] = ()
        if STOP in done:
            _child_locks(f, req.force, SERVE_STOP)
            steps = (Step(id="signal", describe=f"stop the supervisor, pid {f.pidfile.supervisor.pid} (SIGTERM)"),
                     Step(id="gone", describe="wait until it has ended and released its lock"))
        return Plan(steps=steps)   # the running supervisor holds the server's lock

    def observe(self, req: TargetRequest, ctx: Context) -> dict:
        """The server's state: what a stop does depends on it — read under the lock it holds on a
        stale server as under none (core.md § 5)."""
        return {"state": machine(ctx).observe(facts(_target(req).name)).value}

    def apply(self, plan: Plan, ctx: Context, observer) -> ServeOutcome:
        req = TargetRequest.model_validate(plan.request)
        name = _target(req).name
        f = facts(name)
        listen = f.pidfile.listen if f.pidfile else Listen.named(name)
        if any(s.id == "signal" for s in plan.steps):
            _child_locks(f, req.force, SERVE_STOP)  # again: the page may have started one since the plan

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
                    end(f.pidfile.supervisor, grace=0)   # alone: in a terminal it may share a group with others
                    if f.pidfile.child:
                        end(f.pidfile.child, grace=0, group=True)
                    supervisor.remove_files(listen)
                    observer.note("it did not end in time: killed")
            return "done", None

        status, where = run_steps(plan, ctx, observer, do)
        return _outcome(plan, status, where, listen, None)


# ------------------------------------------------------------------ status

class ServerRow(Model):
    name: str = Field(description="the port, or `sock`")
    host: str = Field(description="the host its pidfile was written on")
    state: str = Field(description="its state, observed", json_schema_extra={"doc": "web.md § 4"})
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
    next: list[view.Action] = Field(default_factory=list, description="for each server up and not answering: the "
                                    "line that dumps its child's stacks into the stacks log, and its restart")

    @property
    def report(self) -> view.Report:
        if not self.servers:
            return view.Report(blocks=[view.Text(text="no server is running")])
        rows = [{"listen": s.listen or s.name,
                 "state": s.state + (" (foreground)" if s.foreground else ""),
                 "supervisor": (f"pid {s.supervisor}" + (f", child {s.child}" if s.child else ""))
                 if s.supervisor else "",
                 "answers": "" if s.answers is None else "answers" if s.answers else f"NOT ANSWERING: {s.said}"}
                for s in self.servers]
        blocks: list = [view.Table.of(ServerRow, rows, "listen", "state", "supervisor", "answers")]
        if self.address:
            blocks.append(view.Text(text=f"open:  {self.address}"))
        if self.next:
            blocks.append(view.Next(label="up and not answering: dump its child's stacks into the stacks log, "
                                          "then decide on a restart", actions=self.next))
        return view.Report(blocks=blocks)


def _not_answering(ctx: Context, servers: list[ServerRow]) -> list[view.Action]:
    """For each server up and not answering: the line that dumps its child's stacks into the stacks
    log, and its restart, as its state's table gives it (web.md § 4)."""
    m, actions = machine(ctx), []
    for s in servers:
        if s.answers is False:
            f = facts(s.name)
            actions += [view.shell(f"kill -USR1 {s.child}")] if s.child else []
            restart = m.allowed(m.observe(f)).get(RESTART)
            actions += [restart.next(f)] if restart is not None else []
    return actions


def _row(ctx: Context, name: str) -> ServerRow:
    f = facts(name)
    m = machine(ctx)
    state = m.observe(f)
    p = f.pidfile
    row = ServerRow(name=name, host=p.host if p else dirs.host(), state=state.value,
                    listen=p.listen.describe() + (f" on {p.host}" if state is m.states.elsewhere else "") if p else None,
                    supervisor=p.supervisor.pid if p else None,
                    child=p.child.pid if p and p.child else None,
                    foreground=bool(p and p.foreground), log=str(protocol.log_file(name)))
    if state is m.states.running and p is not None:
        token = _read_token(name)
        ok, said = health.ask(p.listen, token or "") if token else (False, "its token file is gone")
        row = row.model_copy(update={"answers": ok, "said": said})
    return row


@operation(SERVE_STATUS, result=StatusResult)
def serve_status(req: StatusRequest, ctx: Context) -> StatusResult:
    """Every server this account runs here, each with two answers kept apart: is it up, and
    does it answer as itself. The address with its token only for one named server."""
    if req.port is not None or req.socket:
        name = _target(req).name
        row = _row(ctx, name)
        token = _read_token(name) if row.answers else None
        p = protocol.read_pidfile(protocol.pidfile(name))
        return StatusResult(servers=[row], address=address(p.listen, token) if token and p else None,
                            next=_not_answering(ctx, [row]))
    runtime = dirs.runtime_dir()
    names = sorted(p.name[len("serve-"):-len(".pid")] for p in runtime.glob("serve-*.pid")) if runtime.is_dir() else []
    rows = [_row(ctx, n) for n in names]
    return StatusResult(servers=rows, next=_not_answering(ctx, rows))
