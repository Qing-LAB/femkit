"""The operation layer and its generic command line (api.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import Field

from femkit.cli import build
from femkit.core import text
from femkit.core import view
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


@operation(view.Verb("toy.echo", EchoRequest), result=EchoResult)
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


@operation(view.Verb("toy.write", WriteRequest), result=WriteOutcome, changes=True, subject=lambda r: ["toy"])
class Write:
    """Write the word down."""

    def plan(self, req: WriteRequest, ctx: Context) -> Plan:
        if req.refuse:
            raise Refused("the toy is busy", (view.command(view.Verb("toy.write", WriteRequest), word="later"),))
        steps = () if req.noop else (Step(id="w", describe=f"write {req.word}"),)
        return Plan(operation="toy.write", request=req.model_dump(), steps=steps)

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        WRITTEN.append(plan.request["word"])
        return WriteOutcome(plan=plan, status="done")


class SignRequest(Model):
    """Sign the book."""

    name: str | None = Field(default=None, pattern=r"^[A-Z]", description="who signs, capitalized; asked on a terminal when not given")


@operation(view.Verb("toy.sign", SignRequest), result=WriteOutcome, changes=True, subject=lambda r: ["toy"])
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
    assert json.loads(out.stdout) == EchoResult(said="hi").model_dump(mode="json")


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
    (later,) = json.loads(out.stdout)["next"]
    assert later["command"] == "python -m femkit toy write later"
    assert later["call"] == {"operation": "toy.write", "request": {"word": "later"}}
    assert WRITTEN == []


# --- the registry -------------------------------------------------------------

def test_every_registered_operation_is_expressible_on_the_web():
    """Fails if an operation's request or result model cannot produce the JSON schema the web
    adapter needs (api.md § 2.3, web.md § 1)."""
    ops = operations()
    assert ops
    for op in ops.values():
        op.request.model_json_schema()
        op.result.model_json_schema()


def test_an_operation_whose_result_writes_no_text_is_refused():
    """Fails if an operation could be declared with a result a terminal cannot read (api.md § 2.3)."""
    class Bare(Result):
        """A result with no text of its own."""

    with pytest.raises(TypeError, match="writes no text"):
        @operation(view.Verb("toy.bare", EchoRequest), result=Bare)
        def bare(req, ctx):
            """Answers with nothing a person can read."""
            return Bare()


def test_a_changing_operation_must_have_plan_and_apply():
    """Fails if a changing operation could be declared without the plan the person consents to
    (api.md § 2.2)."""
    with pytest.raises(TypeError):
        @operation(view.Verb("toy.bad", WriteRequest), result=WriteOutcome, changes=True)
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
    assert [n["command"] for n in json.loads(out.stdout)["next"]] == ["python -m femkit toy write 'two words' --dry-run",
                                                                     "python -m femkit toy write 'two words' --yes"]


def test_a_plans_question_is_asked_on_a_terminal_and_never_under_yes(monkeypatch):
    """Fails if a question a plan asks is not put to the person on a terminal, its answer
    does not reach the plan applied, or it is asked although --yes said not to ask
    (api.md § 3.1)."""
    import femkit.cli
    monkeypatch.setattr(femkit.cli, "_can_ask", lambda: True)
    assert run("toy", "sign", input="Ada\ny\n").exit_code == 0 and WRITTEN == ["Ada"]
    assert run("toy", "sign", "--yes", input="Ada\n").exit_code == 0 and WRITTEN == [None]


@pytest.mark.parametrize("first", ["\x1b[A", "ada"], ids=["an arrow key's code", "a value the request refuses"])
def test_an_answer_that_is_not_text_or_is_refused_is_said_and_asked_again(first, monkeypatch):
    """Fails if an answer holding a terminal's control characters, or one the request refuses,
    ends the command instead of being said and asked again — a bootstrap lost to one keystroke
    (api.md § 3.1)."""
    import femkit.cli
    monkeypatch.setattr(femkit.cli, "_can_ask", lambda: True)
    out = run("toy", "sign", input=f"{first}\nAda\ny\n")
    assert out.exit_code == 0 and WRITTEN == ["Ada"] and out.output.count("Who signs?") == 2
    assert repr(first) in out.output or "pattern" in out.output


def test_a_command_line_is_shown_as_typed_its_placeholders_bare_and_its_shell_words_quoted():
    """Fails if a placeholder is shown quoted, so a template no longer reads as it was typed
    (`mpirun -np {ranks}`), or if a word the shell would split or expand loses its quotes
    (api.md § 4.4)."""
    assert text.show(["mpirun", "-np", "{ranks}"]) == "mpirun -np {ranks}"
    assert text.show(["srun", "--ntasks={ranks}", "{prefix}/bin/x"]) == "srun --ntasks={ranks} {prefix}/bin/x"
    assert text.show(["a b", "$HOME", "{a,b}", "{ranks} x", ""]) == "'a b' '$HOME' '{a,b}' '{ranks} x' ''"


def test_a_running_steps_live_line_shows_its_log_and_is_erased_before_anything_else(tmp_path, capsys):
    """Fails if a running step's live line does not show its log's last line without the terminal
    codes the log holds, if it stays on screen under the next line, or if output that is not a
    terminal gets it (api.md § 4.4)."""
    from femkit.cli import TerminalObserver
    plan = Plan(operation="env.install", request={}, steps=(Step(id="compile", describe="compile elmer"),))
    log = tmp_path / "compile.log"
    log.write_text("[ 62%] Building\n\x1b[1m[ 63%] Linking Fortran shared library CoilSolver.so\x1b[0m\n")
    for live in (True, False):
        obs = TerminalObserver(live=live)
        obs.operation_start(plan, tmp_path)
        obs.step_start(plan.steps[0], 1, 1)
        obs.step_log(log)
        obs.refresh() if live else None
        obs.note("verdict: passed")
        obs.step_end(plan.steps[0], "done", log)
        obs.operation_end(plan, "done")
        err = capsys.readouterr().err
        shown = "\r\x1b[K      0 s | [ 63%] Linking Fortran shared library CoilSolver.so"
        if live:
            assert shown in err and err.index(shown) < err.index("\r\x1b[K", err.index(shown) + 1) < err.index("verdict")
        else:
            assert "\x1b" not in err and "verdict: passed" in err
