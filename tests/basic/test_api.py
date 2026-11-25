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

    def report(self) -> view.Report:
        return view.Report(blocks=[view.Text(text=self.said)])


@operation(view.Verb("toy.echo", EchoRequest), result=EchoResult)
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
    noop: bool = Field(default=False, description="be in a state with nothing to do")


class WriteOutcome(Outcome):
    def report(self) -> view.Report:
        return view.Report(blocks=[view.Text(text="written")])


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


SHELF: dict = {}


class BookRequest(Model):
    """A book."""

    book: str = Field(default="book", description="the book")


@operation(view.Verb("toy.shelve", BookRequest), result=WriteOutcome, changes=True, subject=lambda r: ["toy"])
class Shelve:
    """Shelve the book as it stands."""

    def observe(self, req: BookRequest, ctx: Context) -> dict:
        return {"state": SHELF.get(req.book)}

    def plan(self, req: BookRequest, ctx: Context) -> Plan:
        return Plan(steps=(Step(id="shelve", describe=f"shelve {req.book}"),))

    def apply(self, plan: Plan, ctx: Context, observer) -> WriteOutcome:
        status, where = run_steps(plan, ctx, observer, lambda step, where: ("done", None))
        return WriteOutcome(plan=plan, status=status, log=str(where))


@operation(view.Verb("toy.logged", BookRequest), result=WriteOutcome, changes=True, subject=lambda r: ["toy-inner"])
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


@operation(view.Verb("toy.nest", BookRequest), result=WriteOutcome, changes=True, subject=lambda r: ["toy-outer"])
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
    (again,) = refused("study", "expand")["next"]
    assert (again["call"], [f["field"] for f in again["fills"]], again["label"]) == (
        {"operation": "study.expand", "request": {}}, ["study"], "study expand STUDY")


@pytest.mark.parametrize("request_model", [LoudRequest, QuietRequest], ids=["defaulting to True", "required"])
def test_a_bool_field_that_does_not_default_to_false_is_refused_when_declared(request_model):
    """Fails if an operation could declare a bool field the command line cannot write: a flag only
    sets it, so one defaulting to True could never be False, and a required one never be omitted
    (api.md § 4.1)."""
    field = next(iter(request_model.model_fields))
    with pytest.raises(TypeError, match=field):
        @operation(view.Verb(f"toy.{field}", request_model), result=EchoResult)
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
    assert later["call"] == {"operation": "toy.write", "request": {"word": "later"}} and "command" not in later
    assert "femkit toy write later" in run("toy", "write", "a", "--refuse", "--yes").output   # written from it
    assert WRITTEN == []


# --- the registry -------------------------------------------------------------

def test_a_second_verb_of_one_name_with_another_request_is_refused():
    """Fails if a verb already declared could be declared again with another request: every next
    step naming the operation would then be written with the wrong request (api.md § 2)."""
    with pytest.raises(TypeError):
        view.Verb("toy.echo", WriteRequest)
    assert view.Verb("toy.echo", EchoRequest).request is EchoRequest     # the same declaration again is the same


STRAY_VERB = """
from femkit.config.requests import SetRequest
from femkit.core import view
view.Verb("config.put", SetRequest)
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


def test_an_operation_whose_result_builds_no_report_or_a_text_of_its_own_is_refused():
    """Fails if an operation could be declared with a result a terminal cannot read, or one whose
    text is not its report's — a second path the page would not draw (api.md § 2.3: every result
    builds its `report()`)."""
    class Bare(Result):
        """A result with no report."""

    class Own(EchoResult):
        """A result writing a text of its own beside its report."""

        def text(self) -> str:
            return self.said

    for result, match in ((Bare, "builds no report"), (Own, "text of its own")):
        with pytest.raises(TypeError, match=match):
            @operation(view.Verb("toy.bare", EchoRequest), result=result)
            def bare(req, ctx):
                """Answers with nothing a person can read on the page."""
                return result()


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


def test_a_refused_request_names_a_lists_item_as_a_files_problem_does():
    """Fails if a request that does not validate names a list's item otherwise than a file's
    problems do — `names[0]`, one key-path form on every surface (core.md § 2)."""
    with refused(UsageError, "invalid-request", "env.install") as caught:
        operations()["env.install"].request_from({"names": [1]})
    assert str(caught.value).startswith("names[0]: ")            # the field, at its key path


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
    assert "the environments to install; the environments: `elmer`, `elmer-cuda`, `ngsolve`, `ngsolve-cuda`, " \
           "`tools`, `web`" in said("env", "install", "--help")
    assert "your projects by its path from the projects root; the templates: `laplace_square`, `square_too`, " \
           "`two_material`" in said("project", "new", "--help")
    assert "SOURCE is missing: the source the file comes from, by its importer's name; the importers: `another`, " \
           "`refractiveindex_info`" in refusal("material", "import")
    assert refusal("env", "install") == ("name an environment, or --all; the environments: elmer, elmer-cuda, "
                                         "ngsolve, ngsolve-cuda, tools, web")
