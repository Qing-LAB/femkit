"""The operation layer and its generic command line (api.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import Field

from femkit.cli import build
from femkit.core.errors import Refused
from femkit.core.eventlog import EventLog, fold
from femkit.core.operations import Ask, Context, Outcome, Plan, Result, SilentObserver, Step, operation, run_steps
from femkit.core.schema import Model
from femkit.registry import operations

# --- two toy operations, standing for any domain's ---------------------------

WRITTEN: list[str] = []


class EchoRequest(Model):
    """Say something."""

    words: list[str] = Field(description="what to say", json_schema_extra={"cli": "argument"})
    shout: bool = Field(default=False, description="in capitals")
    fail: bool = Field(default=False, description="report a failure")


class EchoResult(Result):
    said: str

    def ok(self) -> bool:
        return self.said != "FAIL"

    def text(self) -> str:
        return self.said


@operation("toy.echo", request=EchoRequest, result=EchoResult)
def echo(req: EchoRequest, ctx: Context) -> EchoResult:
    """Repeat the words."""
    said = " ".join(req.words)
    return EchoResult(said="FAIL" if req.fail else said.upper() if req.shout else said)


class WriteRequest(Model):
    """Write a word."""

    word: str = Field(description="the word", json_schema_extra={"cli": "argument"})
    refuse: bool = Field(default=False, description="be in a state that refuses")
    noop: bool = Field(default=False, description="be in a state with nothing to do")


class WriteOutcome(Outcome):
    def text(self) -> str:
        return "written"


@operation("toy.write", request=WriteRequest, result=WriteOutcome, changes=True, subject=lambda r: ["toy"])
class Write:
    """Write the word down."""

    def plan(self, req: WriteRequest, ctx: Context) -> Plan:
        if req.refuse:
            raise Refused("the toy is busy", ("femkit toy write --later",))
        steps = () if req.noop else (Step(id="w", describe=f"write {req.word}"),)
        return Plan(operation="toy.write", request=req.model_dump(), steps=steps)

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        WRITTEN.append(plan.request["word"])
        return WriteOutcome(plan=plan, status="done")


class SignRequest(Model):
    """Sign the book."""

    name: str | None = Field(default=None, description="who signs; asked on a terminal when not given")


@operation("toy.sign", request=SignRequest, result=WriteOutcome, changes=True, subject=lambda r: ["toy"])
class Sign:
    """Sign the book, asking who signs."""

    def plan(self, req: SignRequest, ctx: Context) -> Plan:
        asks = (Ask(key="name", question="Who signs?"),) if req.name is None else ()
        return Plan(operation="toy.sign", request=req.model_dump(), steps=(Step(id="s", describe="sign"),), asks=asks)

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        WRITTEN.append(plan.request["name"])
        return WriteOutcome(plan=plan, status="done")


def run(*args: str, input: str | None = None):
    WRITTEN.clear()
    return CliRunner().invoke(build({"toy.echo": echo, "toy.write": Write, "toy.sign": Sign}), list(args), input=input)


# --- the adapter, once --------------------------------------------------------

def test_request_fields_become_arguments_and_flags_and_results_set_the_exit_code():
    """Fails if the adapter maps fields wrongly or exit codes stop following ok()
    (api.md § 4.1, § 4.3)."""
    assert json.loads(run("toy", "echo", "hello", "there", "--shout", "--json").stdout)["said"] == "HELLO THERE"
    assert run("toy", "echo", "x", "--fail").exit_code == 1
    assert run("toy", "echo").exit_code == 2  # a required argument is missing


def test_json_prints_exactly_the_result_model():
    """Fails if --json prints anything but one JSON document of the result (api.md § 4.2)."""
    out = run("toy", "echo", "hi", "--json")
    assert json.loads(out.stdout)["said"] == "hi"


def test_dry_run_and_missing_consent_change_nothing():
    """Fails if --dry-run, or a changing operation without a terminal and without --yes,
    applies anything (api.md § 4.2)."""
    dry = run("toy", "write", "a", "--dry-run")
    assert dry.exit_code == 0 and WRITTEN == []
    no_consent = run("toy", "write", "a")  # CliRunner gives no terminal
    assert no_consent.exit_code == 2 and WRITTEN == []
    assert run("toy", "write", "a", "--yes").exit_code == 0 and WRITTEN == ["a"]


def test_a_refusal_exits_2_with_its_next_commands():
    """Fails if a refusal is reported as a failure or loses its next commands (api.md § 4.3)."""
    out = run("toy", "write", "a", "--refuse", "--yes", "--json")
    assert out.exit_code == 2
    assert json.loads(out.stdout)["next"] == ["femkit toy write --later"]
    assert WRITTEN == []


# --- the registry -------------------------------------------------------------

def test_every_registered_operation_renders_text_and_is_expressible_on_the_web():
    """Fails if an operation's result cannot render text, or its request and result
    models cannot produce the JSON schema the web adapter needs (api.md § 2.3, § 5)."""
    ops = operations()
    assert ops
    for name, op in ops.items():
        assert op.result.text is not Result.text, f"{name}: {op.result.__name__} has no text()"
        op.request.model_json_schema()
        op.result.model_json_schema()


def test_a_changing_operation_must_have_plan_and_apply():
    """Fails if a changing operation could be declared without the plan the person consents to
    (api.md § 2.2)."""
    with pytest.raises(TypeError):
        @operation("toy.bad", request=WriteRequest, result=WriteOutcome, changes=True)
        class Bad:
            """Plans, then has no way to apply."""

            def plan(self, req, ctx):
                return Plan(operation="toy.bad", request={})


def test_steps_write_the_event_log_and_stop_at_the_first_failure():
    """Fails if applying steps leaves no event log, runs past a failed step, or loses the
    log of a step that raised (api.md § 3, core.md § 6, § 9)."""
    ctx = Context.from_process()
    plan = Plan(operation="toy.steps", request={}, subjects=("toy",),
                steps=tuple(Step(id=i, describe=i) for i in ("a", "b", "c")))
    ran = []

    def do(step, where):
        ran.append(step.id)
        return ("failed" if step.id == "b" else "done"), None

    status, where = run_steps(plan, ctx, SilentObserver(), do)
    state = fold(EventLog(where / "events.jsonl").events())
    assert status == "failed" and ran == ["a", "b"]
    assert state.finished_steps == ("a",) and state.failed_step == "b" and state.outcome == "failed"

    def boom(step, where):
        raise RuntimeError("defect")

    with pytest.raises(RuntimeError) as caught:
        run_steps(plan, ctx, SilentObserver(), boom)
    assert fold(EventLog(Path(caught.value.femkit_log) / "events.jsonl").events()).failed_step == "a"


def test_nothing_to_do_still_answers_with_the_outcome_and_asks_no_consent():
    """Fails if a changing command with nothing to do answers with its plan instead of its
    outcome, or asks for consent to do nothing (api.md § 3, § 4.2)."""
    out = run("toy", "write", "a", "--noop", "--json")  # no terminal, no --yes
    assert out.exit_code == 0
    assert json.loads(out.stdout)["status"] == "done"


def test_a_refusal_offers_the_command_as_typed_so_it_can_be_pasted():
    """Fails if the commands a refusal offers lose the person's arguments, so pasting
    them is a usage error (api.md § 4.4)."""
    out = run("toy", "write", "two words", "--json")  # no terminal, no --yes
    assert json.loads(out.stdout)["next"] == ["python -m femkit toy write 'two words' --dry-run",
                                              "python -m femkit toy write 'two words' --yes"]


def test_a_plans_question_is_asked_on_a_terminal_and_never_under_yes(monkeypatch):
    """Fails if a question a plan asks is not put to the person on a terminal, its answer
    does not reach the plan applied, or it is asked although --yes said not to ask
    (api.md § 3.1)."""
    import femkit.cli
    monkeypatch.setattr(femkit.cli, "_can_ask", lambda: True)
    assert run("toy", "sign", input="Ada\ny\n").exit_code == 0 and WRITTEN == ["Ada"]
    assert run("toy", "sign", "--yes", input="Ada\n").exit_code == 0 and WRITTEN == [None]
