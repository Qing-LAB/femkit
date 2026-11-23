"""The flask application: the routes of api.md § 5.1, built from the registry.

Nothing here knows an operation: each is served from its declaration, as the
command line serves it (api.md § 4).
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Iterator

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from femkit import registry
from femkit.core import eventlog
from femkit.core.errors import PlanStale, Refusal
from femkit.core.operations import Context, Operation, Plan, SilentObserver, Step, operations_root
from femkit.core.process import tail
from femkit.server import health
from femkit.server.protocol import Listen
from femkit.web import access

STATIC = Path(__file__).parent / "static"
SUBJECT = re.compile(r"[a-z0-9][a-z0-9._-]*")
TIME = re.compile(r"\d{8}T\d{6}\.\d{6}Z")
STEP = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]*")
STREAMS = 8              # open event streams at most, below the thread pool's size (api.md § 5.5)
POLL = 0.25              # seconds between looks at a growing event log
KEEPALIVE = 5.0          # seconds of quiet after which a stream sends an empty line
TAIL_LINES = 40

REFUSAL_STATUS = 409


def _refused(exc: Refusal) -> Response:
    response = jsonify({"refused": type(exc).__name__, "message": str(exc), "next": list(exc.next)})
    response.status_code = REFUSAL_STATUS
    return response


def _defect(exc: BaseException, app: Flask) -> Response:
    """A defect: the reason and the operation's log, never a stack trace (api.md § 5.5)."""
    app.logger.error("defect: %s", "".join(traceback.format_exception(exc)))
    response = jsonify({"defect": type(exc).__name__, "message": "an error femkit did not expect; "
                        "the server's log has the detail", "log": getattr(exc, "femkit_log", None)})
    response.status_code = 500
    return response


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise _BadBody()
    return data


class _BadBody(Exception):
    pass


class _Started(SilentObserver):
    """Tells the route each run's operation directory as it starts: an operation over
    several subjects runs once per subject (core.md § 6)."""

    def __init__(self) -> None:
        self.where: queue.Queue[Path] = queue.Queue()

    def operation_start(self, plan: Plan, where: Path) -> None:
        self.where.put(where)


def _address(where: Path) -> str:
    """`<subject>/<time>`: the operation directory as the event routes take it."""
    return f"{where.parent.name}/{where.name}"


def _operation_dir(subject: str, at: str) -> Path:
    if not SUBJECT.fullmatch(subject) or not TIME.fullmatch(at):
        abort(404)
    root = operations_root("").resolve()
    where = (root / subject / at).resolve()
    if root not in where.parents or not (where / "events.jsonl").is_file():
        abort(404)
    return where


def create_app(token: str, listen: Listen, *, operations: dict[str, Operation] | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    access.install(app, token, listen)
    ops = operations if operations is not None else registry.operations()
    streams = threading.BoundedSemaphore(STREAMS)
    stopping = threading.Event()  # set when the server stops: every event stream ends
    app.extensions["femkit.stopping"] = stopping

    def lookup(name: str) -> Operation:
        op = ops.get(name.replace("/", "."))
        if op is None:
            abort(404)
        return op

    @app.errorhandler(Refusal)
    def refused(exc: Refusal):
        return _refused(exc)

    @app.errorhandler(_BadBody)
    def bad_body(_):
        return access.refusal(400, "body", "the body is one JSON object: the request")

    # ------------------------------------------------------------ the routes

    @app.get("/api/health")
    def health_route():
        nonce = request.args.get("nonce", "")
        if not 8 <= len(nonce) <= 128:
            return access.refusal(400, "nonce", "send a nonce of 8 to 128 characters")
        return jsonify({"proof": health.proof(token, nonce)})

    @app.get("/api/operations")
    def list_operations():
        return jsonify([{"name": op.name, "description": op.doc, "changes": op.changes,
                         "request": op.request.model_json_schema(), "result": op.result.model_json_schema()}
                        for op in ops.values()])

    @app.post("/api/<path:name>/plan")
    def plan_route(name: str):
        op = lookup(name)
        if not op.changes:
            abort(404)
        req = op.request_from(_body())  # a refusal of the body is the client's, never a defect
        try:
            plan = op.plan(req, Context.from_process())
        except Refusal:
            raise
        except Exception as exc:
            return _defect(exc, app)
        return jsonify({"plan": plan.model_dump(mode="json"), "digest": plan.digest(), "text": plan.text()})

    @app.post("/api/<path:name>/apply")
    def apply_route(name: str):
        op = lookup(name)
        if not op.changes:
            abort(404)
        body = _body()
        req = op.request_from(body.get("request") if isinstance(body.get("request"), dict) else {})
        ctx = Context.from_process()
        try:
            plan = op.plan(req, ctx)
        except Refusal:
            raise
        except Exception as exc:
            return _defect(exc, app)
        if plan.digest() != body.get("digest"):
            raise PlanStale("what this would do changed since you saw the plan; look at the new plan",
                            ())
        observer, done = _Started(), queue.Queue(maxsize=1)

        def work() -> None:  # runs to its end whether or not the page still reads (api.md § 5.1)
            try:
                done.put(("outcome", op.apply(plan, ctx, observer)))
            except BaseException as exc:  # noqa: BLE001 — handed to the route
                done.put(("error", exc))

        threading.Thread(target=work, name=f"apply {op.name}", daemon=True).start()
        while True:  # until the run starts, or ends before starting (a refusal, a held lock)
            try:
                where = observer.where.get(timeout=0.05)
                break
            except queue.Empty:
                if not done.empty():
                    kind, value = done.get()
                    if kind == "outcome":
                        return jsonify({"ok": value.ok(), "outcome": value.model_dump(mode="json")})
                    if isinstance(value, Refusal):
                        return _refused(value)
                    return _defect(value, app)

        def answer() -> Iterator[str]:
            yield json.dumps({"operation": _address(where)}) + "\n"
            while True:  # each later run's directory as it starts, until the apply ends
                try:
                    kind, value = done.get(timeout=0.2)
                    break
                except queue.Empty:
                    pass
                while not observer.where.empty():
                    yield json.dumps({"operation": _address(observer.where.get())}) + "\n"
            while not observer.where.empty():
                yield json.dumps({"operation": _address(observer.where.get())}) + "\n"
            if kind == "outcome":
                yield json.dumps({"ok": value.ok(), "outcome": value.model_dump(mode="json")}) + "\n"
            elif isinstance(value, Refusal):
                yield json.dumps({"refused": type(value).__name__, "message": str(value),
                                  "next": list(value.next)}) + "\n"
            else:
                app.logger.error("defect: %s", "".join(traceback.format_exception(value)))
                yield json.dumps({"defect": type(value).__name__, "log": getattr(value, "femkit_log", None),
                                  "message": "an error femkit did not expect; the server's log has the detail"}) + "\n"

        return Response(answer(), mimetype="application/x-ndjson")

    @app.post("/api/<path:name>")
    def run_route(name: str):
        op = lookup(name)
        if op.changes:
            return access.refusal(405, "method", f"{op.name} changes things: POST to its /plan, then /apply")
        req = op.request_from(_body())
        try:
            result = op.run(req, Context.from_process())
        except Refusal:
            raise
        except Exception as exc:
            return _defect(exc, app)
        return jsonify({"ok": result.ok(), "result": result.model_dump(mode="json")})

    @app.get("/api/events/<subject>/<at>")
    def events_route(subject: str, at: str):
        where = _operation_dir(subject, at)

        def stream() -> Iterator[str]:
            # The slot is taken here, when the stream is read, so a response never read (HEAD)
            # holds none; a client that went away is found by the next keep-alive line.
            if not streams.acquire(blocking=False):
                yield json.dumps({"refused": "streams", "message": f"at most {STREAMS} event streams are open "
                                                                    "at once"}) + "\n"
                return
            try:
                sent, quiet = 0, 0.0
                while not stopping.is_set():
                    records = eventlog.EventLog(where / "events.jsonl").events()
                    for record in records[sent:]:
                        yield json.dumps(record) + "\n"
                        quiet = 0.0
                    sent = len(records)
                    folded = eventlog.fold(records)
                    if folded.ended or folded.interrupted:
                        return
                    if quiet >= KEEPALIVE:
                        yield "\n"
                        quiet = 0.0
                    stopping.wait(POLL)
                    quiet += POLL
            finally:
                streams.release()

        return Response(stream(), mimetype="application/x-ndjson")

    @app.get("/api/tail/<subject>/<at>/<step>")
    def tail_route(subject: str, at: str, step: str):
        where = _operation_dir(subject, at)
        if not STEP.fullmatch(step):
            abort(404)
        logs = [r["log"] for r in eventlog.EventLog(where / "events.jsonl").events()
                if r.get("step") == step and r.get("log") and r.get("kind") in ("step-log", "step-end")]
        if not logs:
            return jsonify({"lines": []})
        path = Path(logs[-1]).resolve()
        if where not in path.parents or not path.is_file():
            abort(404)
        return jsonify({"lines": tail(path, TAIL_LINES)})

    # ------------------------------------------------------------ the page

    @app.get("/")
    def page():
        if not (STATIC / "index.html").is_file():
            return Response("femkit: the front end is not built yet (api.md § 5.3); the /api routes serve.\n",
                            mimetype="text/plain")
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_file(name: str):
        return send_from_directory(STATIC, name)

    return app
