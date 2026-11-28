"""The operation layer and its generic command line (api.md)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import Field

from femkit.cli import build
from femkit.core import text
from femkit.core import view
from femkit.core.errors import PlanStale, Refused, UsageError
from femkit.core.issues import Issue
from tests import kit
from tests.kit import refused
from femkit.core.eventlog import EventLog, fold
from femkit.core.operations import (Ask, Context, Outcome, Plan, Result, SilentObserver, Step, operation,
                                    operations_root, run_steps)
from femkit.core.schema import Model
from femkit.registry import operations

# --- two toy operations, standing for any domain's ---------------------------

WRITTEN: list[str] = []


class EchoRequest(Model):
    """Say something."""

    words: list[str] = Field(description="what to say", json_schema_extra={"cli": "argument"})
    shout: bool = Field(default=False, description="in capitals")
    fail: bool = Field(default=False, description="report a failure")
    times: int = Field(default=1, description="how many times")
    crash: bool = Field(default=False, description="raise an error femkit did not expect")


class EchoResult(Result):
    said: str

    def ok(self) -> bool:
        return self.said != "FAIL"

    @property
    def report(self) -> view.Report:
        return view.Report(blocks=[view.Text(text=self.said)])


#: The toys' verbs: what each declares besides its name and request (api.md § 2).
READS = dict(on_machine=False, effect="reads")
CHANGES = dict(on_machine=False, effect="changes")


@operation(view.Verb("toy.echo", EchoRequest, **READS), result=EchoResult)
def echo(req: EchoRequest, ctx: Context) -> EchoResult:
    """Repeat the words."""
    if req.crash:
        raise RuntimeError("a defect")
    said = " ".join(req.words * req.times)
    return EchoResult(said="FAIL" if req.fail else said.upper() if req.shout else said)


class WriteRequest(Model):
    """Write a word."""

    word: str = Field(description="the word", json_schema_extra={"cli": "argument"})
    refuse: bool = Field(default=False, description="be in a state that refuses")
    refuse_with_findings: bool = Field(default=False, description="be refused on two findings")
    noop: bool = Field(default=False, description="be in a state with nothing to do")


FOUND = [Issue(severity="error", code="one", subject="a", message="the first finding", file="f.toml", key="k"),
         Issue(severity="error", code="two", subject="b", message="the second finding")]


class WriteOutcome(Outcome):
    @property
    def report(self) -> view.Report:
        return view.Report(blocks=[view.Text(text="written")])


@operation(view.Verb("toy.write", WriteRequest, **CHANGES), result=WriteOutcome, subject=lambda r: ["toy"])
class Write:
    """Write the word down."""

    def plan(self, req: WriteRequest, ctx: Context) -> Plan:
        if req.refuse:
            raise Refused("the toy is busy", (view.command(view.Verb("toy.write", WriteRequest, **CHANGES), word="later"),))
        if req.refuse_with_findings:
            raise Refused("the findings stand", code="has-findings", subject="a", issues=FOUND)
        steps = () if req.noop else (Step(id="w", describe=f"write {req.word}"),)
        return Plan(operation="toy.write", request=req.model_dump(), steps=steps)

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        WRITTEN.append(plan.request["word"])
        return WriteOutcome(plan=plan, status="done")


class SignRequest(Model):
    """Sign the book."""

    name: str | None = Field(default=None, pattern=r"^[A-Z]", description="who signs, capitalized; asked on a terminal when not given")


@operation(view.Verb("toy.sign", SignRequest, **CHANGES), result=WriteOutcome, subject=lambda r: ["toy"])
class Sign:
    """Sign the book, asking who signs."""

    def plan(self, req: SignRequest, ctx: Context) -> Plan:
        asks = (Ask(key="name", question="Who signs?"),) if req.name is None else ()
        return Plan(operation="toy.sign", request=req.model_dump(), steps=(Step(id="s", describe="sign"),), asks=asks)

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        WRITTEN.append(plan.request["name"])
        return WriteOutcome(plan=plan, status="done")


SHELF: dict = {}


class BookRequest(Model):
    """A book."""

    book: str = Field(default="book", description="the book")


@operation(view.Verb("toy.shelve", BookRequest, **CHANGES), result=WriteOutcome, subject=lambda r: ["toy"])
class Shelve:
    """Shelve the book as it stands."""

    def observe(self, req: BookRequest, ctx: Context) -> dict:
        return {"state": SHELF.get(req.book)}

    def plan(self, req: BookRequest, ctx: Context) -> Plan:
        return Plan(steps=(Step(id="shelve", describe=f"shelve {req.book}"),))

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        status, where = run_steps(plan, ctx, observer, lambda step, where: ("done", None))
        return WriteOutcome(plan=plan, status=status, log=str(where))


@operation(view.Verb("toy.logged", BookRequest, **CHANGES), result=WriteOutcome, subject=lambda r: ["toy-inner"])
class Logged:
    """One step that reports its log."""

    def plan(self, req: BookRequest, ctx: Context) -> Plan:
        return Plan(steps=(Step(id="log", describe="write a log"),))

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        def do(step, where):
            observer.step_log(where / "log.txt")
            return "done", where / "log.txt"
        status, where = run_steps(plan, ctx, observer, do)
        return WriteOutcome(plan=plan, status=status, log=str(where))


@operation(view.Verb("toy.nest", BookRequest, **CHANGES), result=WriteOutcome, subject=lambda r: ["toy-outer"])
class Nest:
    """An apply that runs another's, as bootstrap runs each install."""

    def plan(self, req: BookRequest, ctx: Context) -> Plan:
        return Plan(steps=(Step(id="inner", describe="run the inner apply"), Step(id="after", describe="go on")))

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        inner = []

        def do(step, where):
            if step.id == "inner":
                inner.append(Logged.apply(Logged.plan(Logged.request(), ctx), ctx, observer))
            else:
                observer.step_log(where / "after.log")
            return "done", None
        status, where = run_steps(plan, ctx, observer, do)
        return WriteOutcome(plan=plan, status=status, log=f"{where}\n{inner[0].log}")


HOLDERS: list[set[str]] = []


@operation(view.Verb("toy.wait", BookRequest, **CHANGES), result=WriteOutcome, subject=lambda r: ["toy-wait"])
class Wait:
    """Write, then wait on what was written, as a launch waited on does."""

    def plan(self, req: BookRequest, ctx: Context) -> Plan:
        return Plan(steps=(Step(id="write", describe="write"),))

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        from femkit.core.locks import holders
        status, where = run_steps(plan, ctx, observer, lambda step, where: ("done", None))
        HOLDERS.append(set(holders()))
        ctx.release()
        HOLDERS.append(set(holders()))
        ctx.release()                                   # once is enough; again changes nothing
        return WriteOutcome(plan=plan, status=status, log=str(where))


@operation(view.Verb("toy.save", BookRequest, **CHANGES), result=WriteOutcome, subject=lambda r: ["toy"],
           surfaces=("page",))
class Save:
    """Save a text a person typed in the page."""

    def plan(self, req: BookRequest, ctx: Context) -> Plan:
        return Plan(steps=())

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        return WriteOutcome(plan=plan, status="done", log="")


class LoudRequest(Model):
    """Speak; loudly unless told otherwise — which a flag cannot say."""

    loud: bool = Field(default=True, description="shout")


class QuietRequest(Model):
    """Speak; whether quietly is required — which a flag cannot say either."""

    quiet: bool = Field(description="whisper")


TOYS = {"toy.echo": echo, "toy.write": Write, "toy.sign": Sign}


def run(*args: str, input: str | None = None):
    """The toy command line run in this process, its input not a terminal."""
    WRITTEN.clear()
    return CliRunner().invoke(build(TOYS), list(args), input=input)


ON_A_TERMINAL = """
import atexit, json, sys
from tests.basic import test_api as toy
atexit.register(lambda: print(json.dumps(toy.WRITTEN)))
toy.build(toy.TOYS)(sys.argv[1:], prog_name="femkit")
"""


def on_a_terminal(*args: str, typed: str) -> tuple[int, list, str]:
    """The toy command line run as a person runs it, in its own process, its input a terminal
    they type ``typed`` into: its exit code, what it wrote, and all it said."""
    import os
    import pty
    import subprocess
    import sys
    main, sub = pty.openpty()
    try:
        os.write(main, typed.encode())                  # held by the terminal until the command reads it
        p = subprocess.run([sys.executable, "-c", ON_A_TERMINAL, *args], stdin=sub, capture_output=True, text=True,
                           cwd=Path(__file__).resolve().parents[2], timeout=60)
    finally:
        os.close(sub)
        os.close(main)
    *said, written = p.stdout.splitlines()
    return p.returncode, json.loads(written), "\n".join(said) + p.stderr


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


def test_a_defect_under_json_prints_one_json_document_naming_it():
    """Fails if an error femkit did not expect prints no JSON under --json, so a program reading
    stdout reads nothing (api.md § 4.2: exactly one JSON document; core.md § 9: exit 1)."""
    out = run("toy", "echo", "x", "--crash", "--json")
    assert out.exit_code == 1
    assert json.loads(out.stdout)["defect"] == "RuntimeError"


def test_an_arguments_description_is_in_the_commands_help():
    """Fails if a positional argument's description — which a click argument cannot carry — is
    missing from its command's help (api.md § 4.1: "the field's description is the help")."""
    out = run("toy", "echo", "--help")
    assert out.exit_code == 0 and "WORDS" in out.output and "what to say" in out.output


@pytest.mark.parametrize("args, given, fills", [((), {}, ["words"]),
                                                 (("x", "--times", "many"), {"words": ["x"]}, ["times"])],
                         ids=["a missing argument", "a word that is no number"])
def test_a_word_the_request_refuses_is_a_refusal_offering_the_command_again_and_its_json(args, given, fills):
    """Fails if the command line checks a word's presence or type itself, so its error skips the
    request model and gives no refusal's JSON under --json; or if the refusal's next step is not
    the command again, what was given right kept and each word to give again still to fill
    (api.md §§ 4.1–4.2; core.md § 9: "its next steps say what to do")."""
    out = run("toy", "echo", *args, "--json")
    assert out.exit_code == 2
    answer = json.loads(out.stdout)
    assert (answer["refused"], answer["code"], answer["subject"]) == ("UsageError", "invalid-request", "toy.echo")
    assert [(a["call"], [f["field"] for f in a["fills"]]) for a in answer["next"]] == [
        ({"operation": "toy.echo", "request": given}, fills)]


def test_a_missing_option_or_a_wrong_choice_is_said_as_typed_with_the_command_again_for_each_choice():
    """Fails if a required option or argument left out, or a value outside its closed list, is
    refused otherwise than as the request's own refusal — `invalid-request`, exit 2 — or its next
    steps are not the command again as the person types it: what was given right kept, each value
    still to give a fill, and one command for each of a closed list's choices (api.md § 4.1:
    "a missing argument … the request's problems like any other"; core.md § 9)."""
    def refused(*args: str) -> dict:
        out = CliRunner().invoke(build(), [*args, "--json"])
        answer = json.loads(out.stdout)
        assert (out.exit_code, answer["refused"], answer["code"]) == (2, "UsageError", "invalid-request")
        return answer

    answer = refused("material", "import")
    assert [(a["call"]["request"], [f["field"] for f in a["fills"]], a["label"]) for a in answer["next"]] == [
        ({"into": into}, ["source", "file", "name"], f"material import SOURCE FILE --as NAME --into {into}")
        for into in ("library", "project")]
    answer = refused("material", "import", "refractiveindex_info", "x.yml", "--as", "gold", "--into", "lib")
    assert [(a["call"]["request"], a["fills"]) for a in answer["next"]] == [
        ({"source": "refractiveindex_info", "file": "x.yml", "name": "gold", "into": into}, [])
        for into in ("library", "project")]
    (again,) = refused("study", "prep")["next"]
    assert (again["call"], [f["field"] for f in again["fills"]], again["label"]) == (
        {"operation": "study.prep", "request": {}}, ["study"], "study prep STUDY")


@pytest.mark.parametrize("request_model", [LoudRequest, QuietRequest], ids=["defaulting to True", "required"])
def test_a_bool_field_that_does_not_default_to_false_is_refused_when_declared(request_model):
    """Fails if an operation could declare a bool field the command line cannot write: a flag only
    sets it, so one defaulting to True could never be False, and a required one never be omitted
    (api.md § 4.1)."""
    field = next(iter(request_model.model_fields))
    with pytest.raises(TypeError, match=field):
        @operation(view.Verb(f"toy.{field}", request_model, **READS), result=EchoResult)
        def speak(req, ctx):
            """Speak."""
            return EchoResult(said="")


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
    assert later["call"] == {"operation": "toy.write", "request": {"word": "later"}}
    assert later["command"] == "femkit toy write later"   # its line, as the command line writes it
    assert "femkit toy write later" in run("toy", "write", "a", "--refuse", "--yes").output
    assert WRITTEN == []


# --- the registry -------------------------------------------------------------

def test_a_second_verb_of_one_name_with_another_request_is_refused():
    """Fails if a verb already declared could be declared again with another request: every next
    step naming the operation would then be written with the wrong request (api.md § 2)."""
    with pytest.raises(TypeError):
        view.Verb("toy.echo", WriteRequest, **READS)
    assert view.Verb("toy.echo", EchoRequest, **READS).request is EchoRequest     # the same declaration again is the same


STRAY_VERB = """
from femkit.config.requests import SetRequest
from femkit.core import view
view.Verb("config.put", SetRequest, on_machine=False, effect="changes")
from femkit import registry
registry.operations()
"""


def test_femkit_refuses_to_start_while_one_of_its_verbs_names_no_registered_operation():
    """Fails if femkit starts while a verb over one of its request models names no registered
    operation — a renamed verb, whose next steps would offer a command that does not exist
    (api.md § 6). In a process of its own, as femkit starts."""
    p = subprocess.run([sys.executable, "-c", STRAY_VERB], capture_output=True, text=True,
                       cwd=Path(__file__).resolve().parents[2], timeout=60)
    assert p.returncode != 0 and "config.put" in p.stderr

def test_every_registered_operation_is_expressible_on_the_web():
    """Fails if an operation's request or result model cannot produce the JSON schema the web
    adapter needs (api.md § 2.3, web.md § 1)."""
    ops = operations()
    assert ops
    for op in ops.values():
        op.request.model_json_schema()
        op.result.model_json_schema()


def test_every_registered_results_schema_carries_its_report():
    """Fails if a result's report is not a field of its schema — computed from its fields, so the
    JSON a program or the page reads carries it, and the page's type of it is generated, never
    written by hand (web.md § 7.7: "`report` is a field of every result's schema, computed from its
    fields"; api.md § 2.3)."""
    report = view.Report.model_json_schema(mode="serialization")["title"]
    for name, op in operations().items():
        schema = op.result.model_json_schema(mode="serialization")
        assert "report" in schema["properties"] and "report" in schema["required"], name
        assert schema["properties"]["report"]["$ref"].endswith(f"/{report}"), name
    said = echo.run(EchoRequest(words=["hi"]), Context.from_process())
    assert said.model_dump(mode="json")["report"] == {"blocks": [{"kind": "text", "text": "hi"}]}


def test_an_operation_whose_result_builds_no_report_or_a_text_of_its_own_is_refused():
    """Fails if an operation could be declared with a result a terminal cannot read, one whose
    report is no computed field of its schema — a method, which the result's JSON cannot carry — or
    one whose text is not its report's — a second path the page would not draw (api.md § 2.3: every
    result builds its `report`, "a computed field of the result's schema")."""
    class Bare(Result):
        """A result with no report."""

    class Called(Result):
        """A result whose report is a method."""

        def report(self) -> view.Report:
            return view.Report()

    class Own(EchoResult):
        """A result writing a text of its own beside its report."""

        def text(self) -> str:
            return self.said

    for result, match in ((Bare, "builds no report"), (Called, "property"), (Own, "text of its own")):
        with pytest.raises(TypeError, match=match):
            @operation(view.Verb("toy.bare", EchoRequest, **READS), result=result)
            def bare(req, ctx):
                """Answers with nothing a person can read on the page."""
                return result()


def test_a_changing_operation_must_have_plan_and_apply():
    """Fails if a changing operation could be declared without the plan the person consents to
    (api.md § 2.2)."""
    with pytest.raises(TypeError):
        @operation(view.Verb("toy.bad", WriteRequest, **CHANGES), result=WriteOutcome)
        class Bad:
            """Plans, then has no way to apply."""

            def plan(self, req, ctx):
                return Plan(operation="toy.bad", request={})


def test_steps_write_the_event_log_and_stop_at_the_first_failure():
    """Fails if applying steps leaves no event log, runs past a failed step, loses the log of
    a step that raised, or takes an outcome no step can have (api.md § 3, core.md § 6, § 9)."""
    ctx = Context.from_process()
    plan = Plan(operation="toy.steps", request={}, subjects=("toy",),
                steps=tuple(Step(id=i, describe=i) for i in ("a", "b", "c")))
    ran = []

    def do(step, where):
        ran.append(step.id)
        return ("failed" if step.id == "b" else "done"), None

    status, where = run_steps(plan, ctx, SilentObserver(), do)
    state = fold(EventLog.of(where).events())
    assert status == "failed" and ran == ["a", "b"]
    assert state.finished_steps == ("a",) and state.failed_step == "b" and state.outcome == "failed"

    def boom(step, where):
        raise RuntimeError("defect")

    with pytest.raises(RuntimeError) as caught:
        run_steps(plan, ctx, SilentObserver(), boom)
    assert fold(EventLog.of(Path(caught.value.femkit_log)).events()).failed_step == "a"

    with pytest.raises(ValueError) as caught:
        run_steps(plan, ctx, SilentObserver(), lambda step, where: ("skipped", None))
    assert fold(EventLog.of(Path(caught.value.femkit_log)).events()).failed_step == "a"


def test_nothing_to_do_still_answers_with_the_outcome_and_asks_no_consent():
    """Fails if a changing command with nothing to do answers with its plan instead of its
    outcome, or asks for consent to do nothing (api.md § 3, § 4.2)."""
    out = run("toy", "write", "a", "--noop", "--json")  # no terminal, no --yes
    assert out.exit_code == 0
    assert json.loads(out.stdout)["status"] == "done"


def test_a_refusal_offers_the_command_as_typed_so_it_can_be_pasted():
    """Fails if the commands a refusal offers lose the person's arguments, so pasting
    them is a usage error (api.md § 4.4)."""
    out = run("toy", "write", "two words")  # no terminal, no --yes
    assert "femkit toy write 'two words' --dry-run" in out.output
    assert "femkit toy write 'two words' --yes" in out.output


def test_a_plans_question_is_asked_on_a_terminal_and_never_under_yes():
    """Fails if a question a plan asks is not put to the person on a terminal, its answer
    does not reach the plan applied, or it is asked although --yes said not to ask
    (api.md § 3.1)."""
    assert on_a_terminal("toy", "sign", typed="Ada\ny\n")[:2] == (0, ["Ada"])
    assert on_a_terminal("toy", "sign", "--yes", typed="Ada\n")[:2] == (0, [None])


@pytest.mark.parametrize("first", ["\x1b[A", "ada"], ids=["an arrow key's code", "a value the request refuses"])
def test_an_answer_that_is_not_text_or_is_refused_is_said_and_asked_again(first):
    """Fails if an answer holding a terminal's control characters, or one the request refuses,
    ends the command instead of being said and asked again — a bootstrap lost to one keystroke
    (api.md § 3.1)."""
    code, written, said = on_a_terminal("toy", "sign", typed=f"{first}\nAda\ny\n")
    assert code == 0 and written == ["Ada"] and said.count("Who signs?") == 2
    assert said.count("  ! ") == 1                         # said, visibly, once, before it is asked again


def test_a_command_line_is_shown_as_typed_its_placeholders_bare_and_its_shell_words_quoted():
    """Fails if a placeholder is shown quoted, so a template no longer reads as it was typed
    (`mpirun -np {ranks}`), or if a word the shell would split or expand loses its quotes
    (api.md § 4.4)."""
    assert text.show(["mpirun", "-np", "{ranks}"]) == "mpirun -np {ranks}"
    assert text.show(["srun", "--ntasks={ranks}", "{prefix}/bin/x"]) == "srun --ntasks={ranks} {prefix}/bin/x"
    assert text.show(["a b", "$HOME", "{a,b}", "{ranks} x", ""]) == "'a b' '$HOME' '{a,b}' '{ranks} x' ''"


def test_a_value_still_to_fill_is_written_as_what_it_asks_for_and_its_example_only_as_help():
    """Fails if a step with a value still to fill is written with that value's example in its
    place — as if it were the person's value — rather than as what it asks for, the field as the
    command line's help names it, its example said apart, after `#`, as help (workflow.md § 7: "a
    value only the person knows … never an example written as if it were theirs"; web.md § 7.2:
    `fills`)."""
    verb = view.Verb("toy.echo", EchoRequest, **READS)
    step = view.command(verb, words=["hi"], fills=[view.Fill(field="times", label="how many times", example="3")])
    assert step.command == "femkit toy echo hi --times TIMES" and step.fills[0].example == "3"
    command, _, help_ = str(step).partition("   # ")
    assert command == step.command and "3" in help_


def test_a_step_on_another_machine_is_a_line_for_that_machine_never_run_here():
    """Fails if a step that runs on another machine — `on`, by its record's name — is written by the
    command line as a step of this machine, with nothing saying where it is typed: a line for that
    machine, its request's path fields as given, from the project's folder (web.md § 7.2: "`on` —
    the machine it runs on … a surface writes it as a line for that machine, its paths — the
    request's fields declared `path` — from the project's folder, and never runs it here")."""
    from femkit.jobs.requests import JOB_LAUNCH, JOB_LIST
    here = view.command(JOB_LAUNCH, dir="runs/check/launch/mesh-elmer-001")
    there = here.model_copy(update={"on": "cluster"})
    assert there.command == here.command == "femkit job launch runs/check/launch/mesh-elmer-001"
    assert "cluster" not in str(here) and "cluster" in str(there).partition("   # ")[2]
    assert "project" in str(there).partition("   # ")[2]                       # a path field: from the project's folder
    assert "project" not in str(view.command(JOB_LIST).model_copy(update={"on": "cluster"}))


#: Every operation femkit registers: whether it acts on the machine it runs on, and why (api.md
#: § 2.2, the verb) — a step of one that does, for another machine, carries that machine (web.md
#: § 7.2); one that does not runs here for any target. An operation is added here as it is declared.
ACTS_ON_ITS_MACHINE = {
    "case.list": (False, "a project's cases and their stages, read from the project wherever it is"),
    "config.init": (True, "writes this machine's config.toml"),
    "config.path": (True, "where this machine's config.toml is"),
    "config.set": (True, "writes this machine's config.toml"),
    "config.show": (True, "this machine's config.toml"),
    "doctor": (True, "whether this machine is ready"),
    "env.bootstrap": (True, "sets this machine up: its config.toml, its environments, its record"),
    "env.clean": (True, "removes an environment of this machine"),
    "env.install": (True, "installs an environment on this machine"),
    "env.list": (True, "this machine's environments and their states"),
    "env.log": (True, "the last operation on an environment of this machine"),
    "env.validate": (True, "runs an environment's checks on this machine and records them in its prefix"),
    "job.cancel": (True, "stops a job launched from this machine"),
    "job.launch": (True, "starts a job on this machine"),
    "job.list": (True, "the jobs launched from this machine"),
    "job.machines": (True, "the machine records this machine keeps, its own set against its config.toml"),
    "job.prepare": (False, "a folder's run script, written here for any target (workflow.md § 7)"),
    "job.probe": (True, "measures this machine"),
    "job.status": (False, "a folder's state, read from its files wherever it runs"),
    "material.import": (False, "a material into the projects root's library or a project's own"),
    "project.check": (False, "a project's parts, read from the project wherever it is"),
    "project.graph": (False, "a project's parts as a graph"),
    "project.list": (False, "the projects under the projects root"),
    "project.new": (False, "a project written under the projects root"),
    "project.save": (False, "a file of a project written as typed, the project wherever it is"),
    "schema.check": (False, "femkit's shipped definitions, the same on every machine"),
    "schema.docs": (False, "the reference pages, rendered from the shipped definitions"),
    "serve.foreground": (True, "a web server on this machine"),
    "serve.restart": (True, "a web server on this machine"),
    "serve.start": (True, "a web server on this machine"),
    "serve.status": (True, "the web servers on this machine"),
    "serve.stop": (True, "a web server on this machine"),
    "study.flow": (False, "a study's stages for any target, drawn here (workflow.md § 7)"),
    "study.list": (False, "a project's studies"),
    "study.prep": (False, "a study prepped for any target, here (workflow.md § 7)"),
    "web.build": (True, "the page's bundle, built in this machine's `web` environment"),
}


def test_every_operation_declares_whether_it_acts_on_the_machine_it_runs_on():
    """Fails if an operation femkit registers declares on its verb otherwise than this file's list
    states, with its reason, whether it acts on the machine it runs on — `env validate`, `doctor` or
    `job cancel` left undeclared, so a step of it for another machine reads as one run here — or if
    one is registered that the list does not name: a new operation declares it before it is added
    (api.md § 2.2: the verb says "whether the operation acts on the machine it runs on …, so a step
    of it for another machine carries that machine"; web.md § 7.2)."""
    declared = {name: op.verb.on_machine for name, op in operations().items()}
    assert declared == {name: acts for name, (acts, _) in ACTS_ON_ITS_MACHINE.items()}


def _results_holding_what_once_decided_a_next_step():
    """Results whose fields once made their report decide a next step: an install that failed, a
    server up and not answering, a stage with its state's steps."""
    from femkit.envs.operations import EnvResult, InstallOutcome
    from femkit.server.operations import ServerRow, StatusResult
    from femkit.workflow.operations import FlowResult
    from femkit.jobs.requests import JOB_LIST
    step = view.command(JOB_LIST)
    return [InstallOutcome(plan=Plan(), status="failed", environments=[EnvResult(name="x", status="failed")]),
            StatusResult(servers=[ServerRow(name="8000", host="h", state="running", child=7, answers=False,
                                            log="l")]),
            FlowResult(project="p", study="s", target="t", graph=view.Graph(nodes=[view.GraphNode(
                address="stage:s/mesh/1", family="stage", kind="mesh", label="mesh", actions=[step])]))], step


def test_a_results_report_offers_the_next_steps_its_operation_filled_and_decides_none():
    """Fails if a result's report decides a next step of its own — from what failed, what does not
    answer, or a node's actions — rather than drawing the next steps its operation filled into a
    field of the result, and none where that field is empty (api.md § 2.3: "`report()` builds only
    from fields of the model; it decides nothing"; workflow.md § 7)."""
    results, step = _results_holding_what_once_decided_a_next_step()
    for result in results:
        assert not [b for b in result.report.blocks if isinstance(b, view.Next)], type(result).__name__
        filled = result.model_copy(update={"next": [step]})
        assert [a for b in filled.report.blocks if isinstance(b, view.Next) for a in b.actions] == [step]


def _example(annotation, whole: bool):
    """A value of ``annotation``, every field of a model filled — by its field's example where it
    declares one — every list, set and table one item long, or with ``whole`` false, empty; the
    first of a union's alternatives that is not none, a closed list's first value."""
    import enum
    import types
    import typing
    from pydantic import BaseModel
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Annotated:
        return _example(args[0], whole)
    if origin is typing.Literal:
        return args[0]
    if origin in (typing.Union, types.UnionType):
        return _example(next(a for a in args if a is not type(None)), whole)
    if origin is tuple and args and args[-1] is not Ellipsis:
        return tuple(_example(a, whole) for a in args)
    if origin in (list, tuple, set, frozenset):
        items = [_example(args[0], whole)] if whole and args else []
        return items if origin is list else tuple(items)
    if origin is dict:
        return {_example(args[0], whole): _example(args[1], whole)} if whole else {}
    if annotation is view.Action:
        return view.shell("a step a field holds")
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.model_construct(**{n: f.examples[0] if f.examples else _example(f.annotation, whole)
                                             for n, f in annotation.model_fields.items()})
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return next(iter(annotation))
    return {str: "x", bool: True, int: 1, float: 1.0, Path: Path("/x")}.get(annotation, "x")


def _held(value) -> list[view.Action]:
    """Every next step a value holds, through its fields, its items and its tables."""
    from pydantic import BaseModel
    if isinstance(value, view.Action):
        return [value]
    if isinstance(value, BaseModel):
        return [a for name in type(value).model_fields for a in _held(getattr(value, name, None))]
    if isinstance(value, dict):
        return [a for v in value.values() for a in _held(v)]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [a for v in value for a in _held(v)]
    return []


def test_every_registered_results_report_draws_its_next_steps_from_its_fields_alone():
    """Fails if the report of any registered operation's result shows a next step — under a heading,
    or in a table's cell — that none of the result's fields holds: a step its report composes or
    picks, rather than one its operation filled into a field from its subject's machine (api.md
    § 2.3: "`report()` builds only from fields of the model; it decides nothing"; plan § 4, X:
    "every outcome's `next` a field the operation fills"). Each result is built with every field
    filled, so each branch that offers a step is reached; a report that cannot read such made-up
    values is read again with every list and table empty."""
    wrong = []
    for name, op in sorted(operations().items()):
        try:
            result = _example(op.result, whole=True)
            shown = result.report
        except Exception:
            result = _example(op.result, whole=False)
            shown = result.report
        drawn = [a for b in shown.blocks if isinstance(b, view.Next) for a in b.actions] + \
                [c for b in shown.blocks if isinstance(b, view.Table) for row in b.rows for c in row.values()
                 if isinstance(c, view.Action)]
        held = _held(result)
        wrong += [f"{name}: {a.command}" for a in drawn if a not in held]
    assert not wrong, "\n".join(wrong)


class NextRow(Model):
    """A row of a table of the test's own: a step, the row's own next step."""

    step: view.Action = Field(description="what to do")


def test_a_steps_label_is_said_by_the_one_rendering_of_an_action_wherever_it_stands():
    """Fails if the command line writes a step — under a next block's heading, under a finding, or in
    a table's cell — otherwise than by one rendering: its command, then after `#` its label — the
    words its state's table gives it, what the page writes on its button — where it says more than
    the command, then its note; or says, as a label, the command's own words, which a step given no
    label carries (api.md § 4.4: "the commands, one a line, indented, prose after `#`"; web.md § 7.2:
    `label`, "what a person reads on it"; plan § 4, X: one renderer of an `Action`)."""
    from femkit.jobs.requests import JOB_LAUNCH, JOB_LIST
    labelled = view.command(JOB_LAUNCH, dir="/p/runs/check/launch/mesh-elmer-001", label="launch it",
                            note="on this machine")
    line = "femkit job launch /p/runs/check/launch/mesh-elmer-001   # launch it; on this machine"
    steps = [labelled, view.command(JOB_LIST), view.shell("ss -ltn")]
    lines = text.report(view.Report(blocks=[view.Next(label="what to do", actions=steps)])).splitlines()
    assert lines == ["next -- what to do:", f"    {line}", "    femkit job list", "    ss -ltn"]
    found = Issue(severity="error", code="x", subject="s", message="m", next=tuple(steps))
    assert text.findings([found])[1:] == [f"      {line}", "      femkit job list", "      ss -ltn"]
    cells = text.report(view.Report(blocks=[view.Table.of(NextRow, [{"step": s} for s in steps], "step")]))
    assert cells.splitlines()[1:] == [f"  {line}", "  femkit job list", "  ss -ltn"]
    assert str(labelled) == line


def test_an_actions_json_carries_its_command_and_its_verbs_effect_alone_and_reads_back():
    """Fails if an action's JSON lacks the line the command line writes for it — so the page would
    write commands of its own — or its operation's effect, from its verb's declaration, so the page
    would decide its button's tone and whether to ask itself; or if it carries a second fact beside
    the effect that the effect already says, whether it asks before applying; or if an action
    written so does not read back as itself — a lock's file and a launch folder's maker hold them
    (web.md § 7.2: "`command` … serialized with it"; "`effect` … from its operation's declaration";
    the page confirms an action whose effect is not `reads`; api.md § 2: one home, the verb)."""
    from femkit.envs.requests import ENV_CLEAN, ENV_LIST
    for step, effect in ((view.command(Write.verb, word="a"), "changes"),
                         (view.command(echo.verb, words=["a"]), "reads"),
                         (view.command(ENV_CLEAN, name="elmer"), "removes"), (view.command(ENV_LIST), "reads"),
                         (view.shell("ss -ltn"), None)):
        held = step.model_dump(mode="json")
        assert (held["command"], held["effect"]) == (step.command, effect)
        assert view.Action.model_validate(held) == step
    schema = view.Action.model_json_schema(mode="serialization")["properties"]
    assert {"command", "effect"} <= set(schema) and "confirms" not in schema


@pytest.mark.parametrize("effect, shape", [("reads", "planned"), ("changes", "run"), ("removes", "run")])
def test_an_operation_is_planned_and_applied_exactly_when_its_verb_does_more_than_read(effect, shape):
    """Fails if an operation's declaration may disagree with its verb's effect — one whose verb only
    reads declared as a plan and an apply, or one whose verb changes or removes declared as one
    function run with no plan the person consents to — so whether it changes things would have a
    second home beside the verb, which every action of it carries (api.md § 2: the verb's
    `effect`; web.md § 7.2: the page confirms an action whose effect is not `reads`); or a verb may
    leave its effect out."""
    verb = view.Verb(f"toy.shaped-{effect}", BookRequest, on_machine=False, effect=effect)

    class Planned:
        """Planned and applied."""

        def plan(self, req, ctx):
            return Plan()

        def apply(self, plan, ctx, observer):
            return WriteOutcome(plan=plan, status="done")

    def run(req, ctx):
        """Run once."""
        return WriteOutcome(plan=Plan(), status="done")

    with pytest.raises(TypeError):
        operation(verb, result=WriteOutcome, subject=(lambda r: ["toy"]) if effect != "reads" else None)(
            Planned if shape == "planned" else run)
    with pytest.raises(TypeError):
        view.Verb("toy.unsaid", BookRequest, on_machine=False)
    with pytest.raises(ValueError, match="effect"):
        view.Verb("toy.erases", BookRequest, on_machine=False, effect="erases")


class Foreseen(Outcome):
    """A toy's outcome, every field of it foreseen by its plan."""

    words: list[str] = Field(default_factory=list, description="each word written")

    @property
    def report(self) -> view.Report:
        return view.Report(blocks=[view.Text(text=f"{self.status}: {' '.join(self.words)}")])


@operation(view.Verb("toy.foresee", EchoRequest, **CHANGES), result=Foreseen, subject=lambda r: ["toy"])
class Foresee:
    """Write the words, the outcome foreseen by the plan."""

    def plan(self, req: EchoRequest, ctx: Context) -> Plan:
        return Plan(steps=tuple(Step(id=f"w{i}", describe=f"write {w}") for i, w in enumerate(req.words)))

    def outcome(self, plan: Plan, ctx: Context, status: str = "done", log: str | None = None) -> Foreseen:
        return Foreseen(plan=plan, status=status, log=log, words=plan.request["words"])

    def apply(self, plan: Plan, ctx: Context, observer) -> Foreseen:
        status, where = run_steps(plan, ctx, observer, lambda step, where: ("done", None))
        return self.outcome(plan, ctx, status, str(where))


def test_a_plan_carries_the_report_its_outcome_would_show_built_once_by_the_runner():
    """Fails if a plan does not carry the report its outcome would show — built by the runner from the
    outcome the operation's plan foresees, the same code its apply answers with, never a second
    report the operation writes — or if the plan the person reads, on a terminal or the page, does
    not show it; or if the digest an apply must carry rests on the report, which is drawn from what
    the plan rests on, rather than on the steps and the request alone (api.md § 3: `report`, "what
    its outcome would show, before anything is written — the page's Preview"; `digest`; web.md
    § 7.7)."""
    c = Context.from_process()
    plan = Foresee.plan(EchoRequest(words=["a", "b"]), c)
    assert plan.report == view.Report(blocks=[view.Text(text="done: a b")])
    assert Foresee.apply(plan, c).report == plan.report
    assert "done: a b" in plan.text() and "done: a b" not in plan.text(brief=True)
    assert plan.model_copy(update={"report": view.Report()}).digest() == plan.digest()
    assert plan.model_copy(update={"steps": plan.steps[:1]}).digest() != plan.digest()
    out = CliRunner().invoke(build({"toy.foresee": Foresee}), ["toy", "foresee", "a", "b", "--dry-run", "--json"])
    assert json.loads(out.stdout)["plan"]["report"] == plan.report.model_dump(mode="json")


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


@pytest.mark.parametrize("args, data", [
    (("material", "import"), {}),
    (("material", "import", "refractiveindex_info", "x.yml", "--as", "gold", "--into", "lib"),
     {"source": "refractiveindex_info", "file": "x.yml", "name": "gold", "into": "lib"}),
], ids=["what is missing", "a value outside its choices"])
def test_a_bad_request_is_refused_alike_from_the_page_and_the_command_line(args, data):
    """Fails if a request its model refuses is said otherwise from the page's JSON — which the
    routes read by `request_from` — than from the command line's words: two builders of one refusal;
    or if either says it in pydantic's words, without each field as the person writes it, its
    choices and the request offered again (core.md § 2: "a problem's reason is a sentence for a
    person, never pydantic's words"; § 9: "its next steps say what to do"; api.md § 4.1)."""
    out = CliRunner().invoke(build(), [*args, "--json"])
    with refused(UsageError, "invalid-request", "material.import") as caught:
        operations()["material.import"].request_from(data)
    assert view.RefusalAnswer.of(caught.value).model_dump(mode="json") == json.loads(out.stdout)
    assert caught.value.next and not {"Field required", "Input should"} & set(str(caught.value).split(": "))


def test_a_key_the_request_does_not_take_is_said_in_the_persons_words_with_the_request_again():
    """Fails if a request holding a key its model does not take — a page's JSON can hold one — is
    refused in pydantic's words, or without the request offered again, what was given right kept
    (core.md § 2: "an unknown key is one problem at it … did you mean"; § 9)."""
    with refused(UsageError, "invalid-request", "study.prep") as caught:
        operations()["study.prep"].request_from({"study": "check", "studdy": "x"})
    assert "Extra inputs" not in str(caught.value) and "`studdy` is no key here" in str(caught.value)
    assert [a.call.request for a in caught.value.next] == [{"study": "check"}]


def test_a_plan_whose_facts_changed_is_refused_before_any_step_and_offered_again():
    """Fails if a plan applies though the facts it rests on changed since it was made, runs a step
    first, or refuses without offering the same request planned again (api.md § 3)."""
    ctx = Context.from_process()
    SHELF["book"] = "draft"
    plan = Shelve.plan(Shelve.request(), ctx)
    SHELF["book"] = "revised"
    with refused(PlanStale, "basis-changed", "toy") as caught:
        Shelve.apply(plan, ctx)
    assert [a.call.operation for a in caught.value.next] == ["toy.shelve"]
    assert not operations_root("toy").exists()                     # no step ran
    SHELF["book"] = "draft"
    assert Shelve.apply(plan, ctx).ok()


def test_an_apply_inside_another_records_each_step_log_once_and_in_its_own_run():
    """Fails if an apply run inside another's — bootstrap's installs — records a step's log twice,
    or the outer run's later step in the inner run's log (core.md § 6)."""
    ctx = Context.from_process()
    outer, inner = Nest.apply(Nest.plan(Nest.request(), ctx), ctx).log.split("\n")
    kinds = lambda where: [(r["kind"], r.get("step")) for r in EventLog.of(Path(where)).events() if r["kind"] == "step-log"]
    assert kinds(inner) == [("step-log", "log")]
    assert kinds(outer) == [("step-log", "after")]


def test_an_apply_that_waits_ends_its_hold_first_and_holds_until_then():
    """Fails if the runner does not hold an operation's subjects while its apply writes, or keeps
    them once the apply ends its hold to wait — a launch waited on for hours would keep every other
    command on its folder busy (api.md § 3: `ctx.release()`; core.md § 5)."""
    HOLDERS.clear()
    ctx = Context.from_process()
    assert Wait.apply(Wait.plan(Wait.request(), ctx), ctx).ok()
    assert "toy-wait" in HOLDERS[0] and "toy-wait" not in HOLDERS[1]


def test_an_operation_of_one_surface_is_offered_there_alone():
    """Fails if an operation declared for the page alone — whose request is a text a person typed
    there — becomes a command whose option would carry a file's content; if one declared for the
    command line alone — the server's start, its run in the foreground, its stop and its restart,
    which run from the page would stop or hold the very server the page talks to — is offered to
    the page; or if an operation's surfaces are not both by default (api.md § 2, `surfaces`; § 4;
    web.md § 4)."""
    from femkit.registry import offered
    shout = operation(view.Verb("toy.shout", EchoRequest, **READS), result=EchoResult, surfaces=("cli",))(echo.impl)
    toys = {"toy.echo": echo, "toy.save": Save, "toy.shout": shout}
    assert set(build(toys).commands["toy"].commands) == {"echo", "shout"}
    assert (Save.surfaces, shout.surfaces, echo.surfaces) == (("page",), ("cli",), ("cli", "page"))
    assert set(offered(toys, "page")) == {"toy.echo", "toy.save"}
    ours, server = operations(), {"serve.start", "serve.foreground", "serve.stop", "serve.restart"}
    assert server <= set(offered(ours, "cli")) and not server & set(offered(ours, "page"))
    assert "serve.status" in offered(ours, "page")


def test_every_command_group_says_in_one_sentence_what_it_holds():
    """Fails if a command group of femkit's — its own, `""`, among them — has no sentence in
    `femkit --help`, or a sentence is kept for a group no operation has (api.md § 6: the registry's
    one list of command groups)."""
    from femkit import registry
    groups = {name.rpartition(".")[0] for name in registry.operations()}
    assert groups == set(registry.GROUPS) and all(g.sentence for g in registry.GROUPS.values())
    listing = " ".join(CliRunner().invoke(build(), ["--help"]).output.split())
    assert all(g.sentence[:40] in listing for g in registry.GROUPS.values())


def test_every_help_ends_with_its_groups_chapter_of_the_manual_and_cites_no_contract():
    """Fails if `--help` — femkit's own, a command group's, a command's — does not end with the
    chapter of the manual its group declares, by the chapter's title; or if any, the help of each
    argument and option it lists among it, cites a contract or the plan (api.md § 4: "a command's
    help ends with that chapter, `(manual: <chapter>)`"; docs/README.md § 3.1, M5)."""
    from femkit import registry
    from femkit.core.schema import chapter
    from tests.basic.test_templates import CITED
    cli = build()
    places = [((), "")] + [((g,), g) for g in registry.GROUPS if g] + [
        (path, ".".join(path[:-1])) for path in kit.commands()]
    ends, cited = {}, {}
    for path, group in places:
        lines = CliRunner().invoke(cli, [*path, "--help"]).output.rstrip().splitlines()
        ends[path] = lines[-1].strip()
        cited |= {path: found[0]} if (found := CITED.search("\n".join(lines))) else {}
    assert len(places) > 30 and cited == {}
    assert ends == {path: f"(manual: {chapter(registry.GROUPS[group].manual)})" for path, group in places}


def test_every_field_of_an_operation_is_a_sentence_and_names_where_it_is_defined_as_its_doc():
    """Fails if a field of an operation's request or result — or of a model inside one — cites a
    document in its description, which is a sentence and nothing else, or states a `doc` naming a
    document or a section the repository lacks: a field's help, a column's help and a reference
    page would cite a contract, or point nowhere (web.md § 7.1: "a schema's description is a
    sentence and nothing else; a reference to a document is a `doc` annotation beside it"; core.md
    § 2: `doc`, "where the field is defined")."""
    from pydantic import BaseModel
    from femkit.core import dirs
    from femkit.core.schema import classes, field_extras, items_of, values_of
    seen: set = set()
    cited, nowhere = [], []

    def inside(annotation) -> list[type[BaseModel]]:
        """The models a field holds: itself, a list's items, a table's values."""
        return [*classes(annotation), *(m for held in (items_of(annotation), values_of(annotation))
                                        if held is not None for m in inside(held))]

    def walk(model: type[BaseModel]) -> None:
        if model in seen:
            return
        seen.add(model)
        for name, field in model.model_fields.items():
            if "§" in (field.description or ""):
                cited.append(f"{model.__name__}.{name}")
            at = view.Help.of("a sentence", field_extras(field).get("doc"))
            if at is not None and at.doc is not None and not (
                    (dirs.checkout() / at.doc.document).is_file() and (at.doc.section is None or at.doc.anchor)):
                nowhere.append(f"{model.__name__}.{name}")
            for inner in inside(field.annotation):
                walk(inner)

    for op in operations().values():
        walk(op.request)
        walk(op.result)
    assert len(seen) > 50 and (cited, nowhere) == ([], [])


def test_a_value_a_declaration_holds_is_named_in_its_help_and_its_refusal_as_declared_now(definitions):
    """Fails if an argument or option whose values a declaration holds — `material import SOURCE`,
    the importers; `env install NAMES`, the environments; `project new --from`, the templates —
    does not name them in its help, or `SOURCE` or `NAMES` left out does not in its refusal; or if the names
    are read when the command line is built, or at import, not when the help is made — so a help
    misses a declaration of the definitions femkit is pointed at (core.md § 2, `choices`; api.md
    § 4: "a value not among its choices, is said … with the choices")."""
    import shutil
    cli = build()                                                       # before the definitions change
    shutil.copytree(definitions / "templates" / "laplace_square", definitions / "templates" / "square_too")
    shutil.copy(definitions / "importers" / "refractiveindex_info.toml", definitions / "importers" / "another.toml")
    kit.rewrite(definitions / "properties.toml", 'refractiveindex_info = "nk"',
                'refractiveindex_info = "nk", another = "nk"')                # the new source's name for n and k
    shutil.copy(definitions / "environments" / "web.toml", definitions / "environments" / "tools.toml")

    def said(*args: str) -> str:
        return " ".join(CliRunner().invoke(cli, list(args)).output.split())

    def refusal(*args: str) -> str:
        return json.loads(CliRunner().invoke(cli, [*args, "--json"]).output)["message"]

    assert "SOURCE the source the file comes from, by its importer's name; the importers: `another`, " \
           "`refractiveindex_info` (manual: 6 · Materials)" in said("material", "import", "--help")
    assert "the environments to install; the environments: `elmer`, `elmer-cuda`, `gmsh`, `model_prep`, " \
           "`ngsolve`, `ngsolve-cuda`, `postprocess`, `tools`, `web`" in said("env", "install", "--help")
    assert "your projects by its path from the projects root; the templates: `laplace_square`, `square_too`, " \
           "`two_material`" in said("project", "new", "--help")
    assert "SOURCE is missing: the source the file comes from, by its importer's name; the importers: `another`, " \
           "`refractiveindex_info`" in refusal("material", "import")
    assert "NAMES... is missing: the environments to install; the environments: `elmer`, `elmer-cuda`, `gmsh`, " \
           "`model_prep`, `ngsolve`, `ngsolve-cuda`, `postprocess`, `tools`, `web`" in refusal("env", "install")


class NotedRequest(Model):
    """A word, and whether the apply copies its plan's findings itself."""

    word: str = Field(default="w", description="the word")
    copies: bool = Field(default=False, description="the apply copies the plan's findings into its outcome")


NOTE = Issue(severity="warning", code="noted", subject="toy", message="the plan found this")


@operation(view.Verb("toy.noted", NotedRequest, **CHANGES), result=WriteOutcome,
           subject=lambda r: ["toy"])
class Noted:
    """Write, the plan finding one thing."""

    def plan(self, req: NotedRequest, ctx: Context) -> Plan:
        return Plan(steps=(Step(id="w", describe="write"),), issues=[NOTE])

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        status, where = run_steps(plan, ctx, observer, lambda step, where: ("done", None))
        return WriteOutcome(plan=plan, status=status, log=str(where),
                            issues=list(plan.issues) if plan.request["copies"] else [])


@pytest.mark.parametrize("copies", [False, True], ids=["left to the runner", "copied by the apply as well"])
def test_a_plans_findings_come_with_its_outcome_once_carried_by_the_runner(copies):
    """Fails if a plan's findings do not come with its outcome unless the apply copies them — so an
    operation whose apply forgets them, `material import`'s `found-first`, says nothing of them
    under `--yes`, which prints the plan's steps alone — or come twice where an apply copies them
    too (api.md § 4.4: "its findings come with the outcome — carried there by the runner, once, for
    every operation, never copied by each apply")."""
    op = Noted
    c = Context.from_process()
    outcome = op.apply(op.plan(op.request_from({"copies": copies}), c), c)
    assert outcome.issues == [NOTE]


def test_dry_run_json_prints_the_one_plan_answer_the_page_is_given():
    """Fails if `--dry-run --json` prints a shape of its own — the bare plan — rather than the one
    plan answer the page's `/plan` gives, the plan with its digest and its text, so a program reads
    two shapes for one plan (api.md § 4.4: "`--dry-run --json` and the page's `/plan` answer one
    shape"; web.md § 1)."""
    from femkit.core.operations import PlanAnswer
    result = run("toy", "write", "hello", "--dry-run", "--json")
    answer = PlanAnswer.model_validate_json(result.stdout)
    assert result.exit_code == 0 and answer.digest == answer.plan.digest() and answer.text == answer.plan.text()
    assert answer.plan.steps[0].describe == "write hello"


def test_a_refusal_shows_the_findings_it_rests_on_before_its_sentence_on_both_surfaces():
    """Fails if a refusal resting on findings drops them — a script's `--json` or the page given its
    sentence alone — or the command line writes them after its sentence, or only the first of them
    (core.md § 9: `Refusal.issues`, "the findings it rests on, each surface showing them before its
    sentence")."""
    refusal = Refused("the findings stand", code="has-findings", subject="a", issues=FOUND)
    assert view.RefusalAnswer.of(refusal).issues == FOUND
    shown = run("toy", "write", "x", "--refuse-with-findings")
    lines = shown.output.splitlines()
    first, second = (next(i for i, line in enumerate(lines) if said in line)
                     for said in ("the first finding", "the second finding"))
    sentence = next(i for i, line in enumerate(lines) if "refused:" in line)
    assert shown.exit_code == 2 and first < second < sentence and lines[sentence].startswith("[toy write] refused:")
    answer = json.loads(run("toy", "write", "x", "--refuse-with-findings", "--json").stdout)
    assert [i["code"] for i in answer["issues"]] == ["one", "two"]


def test_a_verb_states_whether_it_acts_on_its_machine_with_no_default():
    """Fails if a verb may leave out whether its operation acts on the machine it runs on, taking a
    default — so a new operation that does is offered for another machine as a step run here (api.md
    § 2, the verb; plan § 4, X: "`on_machine` declared by every verb with no default")."""
    with pytest.raises(TypeError):
        view.Verb("toy.undeclared", BookRequest)


def test_a_step_for_another_machine_is_made_by_the_one_core_function_from_its_verb():
    """Fails if a step made for another machine's target does not take that machine from its verb's
    declaration alone — a step of an operation acting on the machine it runs on, or a shell line,
    carrying it, `on`, each path field of its request from the project's folder; any other run here,
    as it is — or if a step for this machine is changed (web.md § 7.2; plan § 4, X: "`view.command(…)`
    sets `on` from the verb's declaration")."""
    from femkit.jobs.requests import JOB_LAUNCH, JOB_PREPARE
    project = Path("/p/square")
    folder = project / "runs/check/launch/mesh-elmer-001"
    cluster = view.Machine("cluster", project)
    launched = view.command(JOB_LAUNCH, dir=str(folder), machine=cluster)
    assert (launched.on, launched.call.request["dir"]) == ("cluster", "runs/check/launch/mesh-elmer-001")
    prepared = view.command(JOB_PREPARE, dir=str(folder), machine=cluster)
    assert (prepared.on, prepared.call.request["dir"]) == (None, str(folder))
    assert view.shell("gmsh mesh.msh", machine=cluster).on == "cluster"
    assert view.command(JOB_LAUNCH, dir=str(folder)) == view.at(view.command(JOB_LAUNCH, dir=str(folder)), None)
    assert view.at(view.command(JOB_LAUNCH, dir=str(folder)), cluster) == launched


def test_a_shell_line_needing_a_persons_value_writes_what_it_asks_for_never_an_example():
    """Fails if a shell line that needs a value only the person knows is written with an example in
    its place, as if it were theirs — `export FEMKIT_RUNTIME_DIR=/a/shorter/path` — rather than as
    what it asks for, its example said apart as help, as an operation's value still to fill is
    (web.md § 7.2: `fills`; plan § 4, X: "a step needing a person's value a fill, never an example
    in a shell line")."""
    from femkit.core import dirs
    from femkit.core.errors import UsageError
    step = view.shell("export X={path}", fills=[view.Fill(field="path", label="an absolute path",
                                                           example="/absolute/path")])
    assert step.command == "export X=PATH" and str(step) == "export X=PATH   # PATH e.g. /absolute/path"
    with refused(UsageError, "not-absolute", "FEMKIT_STATE_DIR") as caught:
        dirs.folder_from("FEMKIT_STATE_DIR", "relative/place", "the state directory")
    (offered,) = caught.value.next
    assert offered.command == "export FEMKIT_STATE_DIR=PATH" and offered.fills[0].example


def test_a_fill_built_for_a_request_field_carries_its_whole_schema_its_toml_its_help_and_whether_required():
    """Fails if the one builder of a fill leaves out a field's schema fragment with the definitions it
    names, whether the request takes its TOML text, its help, or whether its request requires it — so
    the page would build a fill of its own, or lose a value's form (web.md § 7.2: "`fills` — each request
    field the action still needs, whole")."""
    from pydantic import Field as F
    from femkit.config.requests import SetRequest
    from femkit.core.schema import Model as M

    class Inner(M):
        size: int = F(description="how large")

    class Asked(M):
        inner: Inner = F(description="a record of its own")
        maybe: str | None = F(default=None, description="a word, or none")

    held = view.Fill.of(Asked, "inner")
    assert held.required and "$defs" in held.json_schema and held.help.sentence == "a record of its own"
    assert not view.Fill.of(Asked, "maybe").required
    value = view.Fill.of(SetRequest, "value")
    assert value.toml == "whole"
