"""The core building blocks (core.md)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from enum import Enum
from typing import Any, Literal

import pytest

from tests.kit import hold, refused
from femkit.core import persist, text, view
from pydantic import Field, ValidationError
from femkit.core.schema import DefinitionError, Model, described, help_findings, load_text, load_toml

from femkit.core import process
from femkit.core.errors import Busy, Refused
from femkit.core.issues import Issue
from femkit.core.eventlog import EventLog, fold
from femkit.core.locks import subject_lock
from femkit.core import states
from femkit.core.states import Action, Machine, Rule


class Light(Enum):
    on = "on"
    off = "off"


def test_a_state_table_that_could_fall_through_or_strand_a_state_is_rejected():
    """Fails if a table with no `otherwise`, an `otherwise` before the last rule, an unreachable
    state, a state with no action row, or a rule producing another machine's state could be built
    (core.md § 7). Each table breaks one rule only, so each rejection is that rule's."""
    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("lit", Light.on, lambda f: f), Rule("dark", Light.off, lambda f: not f)),
                {Light.on: {}, Light.off: {}})
    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("always", Light.on), Rule("dark", Light.off)), {Light.on: {}, Light.off: {}})
    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("always", Light.on),), {Light.on: {}, Light.off: {}})
    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("lit", Light.on, lambda f: f), Rule("else", Light.off)), {Light.on: {}})

    class Other(Enum):
        x = "x"

    with pytest.raises(ValueError):
        Machine("m", Light, (Rule("lit", Light.on, lambda f: f), Rule("x", Other.x, lambda f: f),
                             Rule("else", Light.off)), {Light.on: {}, Light.off: {}})


def test_a_disallowed_action_is_refused_with_the_allowed_commands():
    """Fails if a refusal does not carry the commands the state allows, read from the
    same table (core.md § 7: one source of "next")."""
    class Switch(Model):
        lamp: str = Field(json_schema_extra={"cli": "argument"})
        dim: bool = False

    m = Machine("light", Light, (Rule("lit", Light.on, lambda f: f), Rule("dark", Light.off)),
                {Light.on: {"off": Action("switch off", view.Verb("light.off", Switch), lambda name: {"lamp": name}),
                            "dim": Action("dim", view.Verb("light.off", Switch), lambda name: {"lamp": name, "dim": True}),
                            "nothing": Action("nothing to do")},
                 Light.off: {}})
    assert m.observe(True) is Light.on and m.observe(False) is Light.off
    with refused(Refused, "not-allowed", "hall") as caught:
        m.require(Light.on, "on", "hall")
    assert [n.command for n in caught.value.next] == ["femkit light off hall",
                                                      "femkit light off hall --dim"]
    assert caught.value.next[1].call.request == {"lamp": "hall", "dim": True}


TABLE = """\
[states]
broken = "its bulb is broken"
on = "it is lit"
off = "otherwise"

[[rules]]
state = "broken"
when = "not bulb"

[[rules]]
state = "on"
when = "power and (switch or not timer)"

[[rules]]
state = "off"
when = "otherwise"

[actions.broken.replace]
describe = "replace the bulb"
shell = "replace the bulb"

[actions.on.off]
describe = "switch off"
operation = "lamp.off"
request = { lamp = "{name}", room = "{room}" }

[actions.on.dim]
describe = "dim"
operation = "lamp.off"
request = { lamp = "{name}", dim = true }

[actions.off]
"""


class LampFacts(Model):
    bulb: bool
    power: bool
    switch: bool
    timer: bool


class LampOff(Model):
    lamp: str = Field(json_schema_extra={"cli": "argument"})
    room: str | None = None
    dim: bool = False


LAMP_OFF = view.Verb("lamp.off", LampOff)
LAMP = states.Binding("lamp", {"bulb": lambda f: f.bulb, "power": lambda f: f.power, "switch": lambda f: f.switch,
                               "timer": lambda f: f.timer},
                      {"name": lambda name: name, "room": lambda name: "hall" if name.startswith("hall") else None})


def lamp(tmp_path, text: str = TABLE):
    path = tmp_path / "lamp.toml"
    path.write_text(text)
    return states.load(path, LAMP)


def test_a_machine_declared_as_data_observes_by_its_first_rule_that_holds_and_offers_its_actions(tmp_path):
    """Fails if a machine read from its table observes by any rule but the first whose condition
    holds over the named facts — `and`, `or`, `not` and parentheses as written — or offers other
    next steps than its table's: an operation with its request filled from the subject, a value
    the subject leaves unset left out, a shell line (core.md § 7)."""
    m = lamp(tmp_path)
    facts = dict(bulb=True, power=True, switch=False, timer=False)
    assert m.observe(LampFacts(**{**facts, "bulb": False})) == "broken"
    assert m.observe(LampFacts(**facts)) == "on"                              # not timer
    assert m.observe(LampFacts(**{**facts, "timer": True})) == "off"          # power, but neither
    assert m.observe(LampFacts(**{**facts, "power": False, "switch": True})) == "off"
    assert [(a.command, a.call.request) for a in m.next(m.states("on"), "hall-1")] == [
        ("femkit lamp off hall-1 --room hall", {"lamp": "hall-1", "room": "hall"}),
        ("femkit lamp off hall-1 --dim", {"lamp": "hall-1", "dim": True})]
    assert m.next(m.states("on"), "porch")[0].call.request == {"lamp": "porch"}
    assert [a.command for a in m.next(m.states("broken"), "porch")] == ["replace the bulb"]
    with refused(Refused, "not-allowed", "porch") as caught:
        m.require(m.states("off"), "off", "porch")
    assert caught.value.next == ()


@pytest.mark.parametrize("old, new, at", [
    ('[[rules]]\nstate = "on"\nwhen = "power and (switch or not timer)"\n', "", "states.on"),
    ('when = "not bulb"', 'when = "otherwise"', "rules[0].when"),
    ('state = "off"\nwhen = "otherwise"', 'state = "off"\nwhen = "power"', "rules[2].when"),
    ('when = "not bulb"', 'when = "not lamp_bulb"', "rules[0].when"),
    ('when = "not bulb"', 'when = "bulb == 1"', "rules[0].when"),
    ('when = "not bulb"', 'when = "bulb()"', "rules[0].when"),
    ("[actions.off]\n", "", "actions.off"),
    ('room = "{room}"', 'room = "{floor}"', "actions.on.off.request.room"),
    ('room = "{room}"', 'room = "the {room}"', "actions.on.off.request"),
    ('operation = "lamp.off"\nrequest = { lamp = "{name}", dim', 'operation = "lamp.dim"\nrequest = { lamp = "{name}", dim',
     "actions.on.dim.operation"),
    ("dim = true", "bright = true", "actions.on.dim.request.bright"),
], ids=["a state no rule gives", "otherwise before the last rule", "a last rule that is no otherwise",
        "a fact the domain does not name", "a comparison", "a call", "a state with no row of actions",
        "a value the subject does not give", "a placeholder inside a text", "an operation no verb declares",
        "a request field the operation lacks"])
def test_a_state_table_breaking_its_rules_is_refused_at_its_key(tmp_path, old, new, at):
    """Fails if a machine's table loads while a state is unreachable, the otherwise is not the last
    rule alone, a condition leaves its grammar or names a fact its domain does not, a state has no
    row of actions, or an action's request names a value the subject does not give, an operation
    no verb declares or a field that operation's request lacks — each refused at its key path
    (core.md § 7: "Closed and total, checked when the machine loads"). The table as written
    loads (the test above), so each refusal is the one change's."""
    assert old in TABLE
    with refused(DefinitionError, "definition-invalid") as caught:
        lamp(tmp_path, TABLE.replace(old, new))
    assert at in [where for where, _ in caught.value.problems], caught.value.problems


def test_a_second_holder_of_a_subject_is_refused_not_queued():
    """Fails if a second command changing one subject waits or proceeds instead of being refused
    at once, or if one process's own nested hold is taken for a second holder (core.md § 5)."""
    first = hold("env-x", "alone")                       # another command, changing it
    try:
        with refused(Busy, "held", "env-x"):
            with subject_lock("env-x"):
                pass
    finally:
        first.stdin.close()
        first.wait()
    with subject_lock("env-x"):  # released when the first holder left; held again inside, one hold
        with subject_lock("env-x"):
            pass


def test_users_share_a_lock_and_a_change_is_refused_naming_each_and_what_ends_it():
    """Fails if two users cannot hold a subject shared at once, if something can take it alone
    while one does — or one join while it is held alone — or if the refusal does not name each
    live user and offer what ends its hold — a next step it cannot read offering nothing, never a
    crash (core.md § 5)."""
    from femkit.core.locks import is_held, require_free
    from femkit.core.locks import lock_path
    lock_path("env-x").parent.mkdir(parents=True, exist_ok=True)
    gone = {"pid": 999999999, "start": 1, "boot": process.boot_id()}
    lock_path("env-x").write_text(json.dumps({"process": gone, "by": "a holder long gone", "next": []}) + "\n"
                                  + json.dumps({"process": process.identify(os.getpid()).as_json(),
                                                "by": "a holder of another shape", "next": [{"no": "action"}]}) + "\n")
    users = [hold("env-x", "shared"), hold("env-x", "shared")]
    try:
        assert not is_held("env-x")                         # a use is not a change
        with refused(Busy, "held", "env-x") as caught:
            with subject_lock("env-x"):
                pass
        assert str(caught.value).count("a user of env-x") == 2 and [n.command for n in caught.value.next] == ["end it"]
        assert "long gone" not in str(caught.value)            # a holder that ended is not named
        with refused(Busy, "held", "env-x"):
            require_free("env-x")
        with subject_lock("env-x", shared=True):            # one more user
            pass
    finally:
        for p in users:
            p.communicate("")
    require_free("env-x")
    changer = hold("env-x", "alone")
    try:
        assert is_held("env-x")
        with refused(Busy, "held", "env-x"):
            with subject_lock("env-x", shared=True):
                pass
    finally:
        changer.communicate("")


def test_the_event_log_fold_reads_progress_interruption_and_a_torn_line(tmp_path):
    """Fails if resume could skip an unfinished step, a dead writer's run read as in
    progress, a run told alive by its process ID alone, the steps not told as the log
    tells them, or a torn last line break the read (core.md §§ 6, 8)."""
    writer = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    gone = process.identify(writer.pid)
    writer.kill()
    writer.wait()
    log = EventLog.of(tmp_path)
    log.append("operation-start", operation="env.install", process=gone.as_json())
    log.append("step-start", step="a")
    log.append("step-end", step="a", outcome="done")
    log.append("step-start", step="b")
    log.append("step-end", step="b", outcome="failed")
    log.append("step-start", step="b")
    with open(log.path, "a") as fh:
        fh.write('{"kind": "step-end", "step": "b", "outc')  # the writer died mid-line
    state = fold(log.events())
    assert state.finished_steps == ("a",)
    assert state.failed_step == "b"
    assert [(s.id, s.outcome) for s in state.steps] == [("a", "done"), ("b", "running")]
    assert state.interrupted and not state.ended
    me = process.identify(os.getpid())
    assert not fold([{"kind": "operation-start", "process": me.as_json()}]).interrupted
    reused = {**me.as_json(), "start": me.start + 1}           # this process's ID, another process's start
    assert fold([{"kind": "operation-start", "process": reused}]).interrupted


def test_an_interrupted_copy_of_a_folder_leaves_nothing_in_its_place(tmp_path):
    """Fails if a folder copy that stops part way leaves a half folder where the copy goes, or
    anything beside it (core.md § 4: "Every write is atomic")."""
    source, place = tmp_path / "source", tmp_path / "place"
    (source / "a").mkdir(parents=True)
    (source / "a" / "one").write_text("1")
    (source / "two").write_text("2")
    (source / "two").chmod(0)                              # the copy stops here
    place.mkdir()
    try:
        with pytest.raises(OSError):
            persist.copy_tree(source, place / "copy")
    finally:
        (source / "two").chmod(0o644)
    assert list(place.iterdir()) == []
    persist.copy_tree(source, place / "copy")
    assert (place / "copy" / "a" / "one").read_text() == "1" and (place / "copy" / "two").read_text() == "2"


@pytest.mark.parametrize("written", [None, b"# caf\xe9\n"], ids=["no file", "not UTF-8"])
def test_a_declared_file_that_is_absent_or_not_text_is_refused_at_the_file(tmp_path, written):
    """Fails if a declared file that is not there, or not UTF-8 text, fails as a defect instead of
    a `DefinitionError` naming the file (core.md § 2: "One TOML reader")."""
    path = tmp_path / "declared.toml"
    if written is not None:
        path.write_bytes(written)
    with refused(DefinitionError, "definition-invalid", str(path)):
        load_toml(path, Model)


def test_a_findings_code_is_kebab_case_or_refused_when_made():
    """Fails if a finding can be made with a code that is not kebab-case — the code tests and
    programs match on (core.md § 10)."""
    assert Issue(severity="error", code="preamble-unset", subject="x", message="m").code == "preamble-unset"
    for code in ("Preamble_unset", "preamble unset", "-preamble", ""):
        with pytest.raises(ValidationError):
            Issue(severity="error", code=code, subject="x", message="m")


def test_a_finding_says_where_and_what_would_be_right_and_never_chooses():
    """Fails if a finding's file and key, the one value that would be right, or the values that
    would, do not reach the text a person reads under it — or a finding can name one right value
    and choices at once, so that a fix would choose among them (core.md § 10; api.md § 4.4)."""
    one = Issue(severity="error", code="wrong-dimension", subject="component:slab:groups.left", message="m",
                file="components/slab/component.toml", key="groups.left", right="1")
    several = Issue(severity="error", code="no-such-group", subject="physics:p:conditions.lft", message="n",
                    file="physics/p.toml", key="conditions.lft", choices=('"left"', '"right"'))
    assert text.findings([one, several]) == [
        "  x m", "      components/slab/component.toml: groups.left", "      right: 1",
        "  x n", "      physics/p.toml: conditions.lft", '      one of: "left", "right"']
    with pytest.raises(ValidationError):
        Issue(severity="error", code="both", subject="x", message="m", right="1", choices=("2", "3"))


@pytest.mark.parametrize("n, noun, said", [
    (1, "study", "1 study"),
    (2, "study", "2 studies"),        # -y after a consonant
    (0, "study", "0 studies"),
    (2, "key", "2 keys"),             # -y after a vowel
    (2, "mesh", "2 meshes"),
    (2, "case", "2 cases"),
])
def test_a_count_writes_its_noun_in_the_one_plural_english_has(n, noun, said):
    """Fails if a count a person reads writes its noun's plural otherwise than English does —
    `2 studys`, `2 meshs` — the one plural every command's text is built with (api.md § 4.4: the
    text a person reads, built from core/text.py)."""
    assert text.count(n, noun) == said


def test_a_timeout_stops_the_whole_process_group(tmp_path):
    """Fails if a timed-out command leaves its children running (core.md § 8)."""
    pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time;"
        f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        f"open({str(pid_file)!r}, 'w').write(str(c.pid)); time.sleep(60)"
    )
    started = time.time()
    result = process.run([sys.executable, "-c", script], timeout=2, log=tmp_path / "out.log")
    assert result.timed_out and result.returncode is None
    assert time.time() - started < 20
    child = int(pid_file.read_text())
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with open(f"/proc/{child}/stat") as fh:
                if fh.read().split()[2] == "Z":
                    break
        except FileNotFoundError:
            break
        time.sleep(0.1)
    else:
        pytest.fail(f"child {child} still running after the timeout")


# ------------------------------------------------------------------ a template's help (core.md § 2; projects.md § 7)

class Element(Model):
    family: Literal["lagrange", "nedelec"] = Field(description="the element family")
    degree: int = Field(default=1, description="its polynomial degree")


class Solver(Model):
    kind: Literal["direct", "iterative"] = Field(description="how it is solved")


class Numerics(Model):
    element: Element = Field(description="the finite element")
    solver: Solver = Field(description="the linear solver")


class Resources(Model):
    ranks: int = Field(default=1, description="MPI ranks")


class Step(Model):
    physics: str = Field(description="the physics it solves")
    order: Literal[1, 2] | None = Field(default=None, description="the geometry order")
    resources: Resources = Field(default_factory=Resources, description="its resources")


class Part(Model):
    schema_: int = Field(alias="schema", description="the shape", json_schema_extra={"doc": "models.md § 2"})
    description: str = Field(description="what it is")
    numerics: Numerics = Field(description="the discrete problem")
    steps: dict[str, Step] = Field(default_factory=dict, description="its steps, by name")
    kinds: dict[str, Literal["length", "angle"]] = Field(default_factory=dict, description="what each must be")
    limit: int | Literal["unlimited"] = Field(default="unlimited", description="the most it may take")
    display: list[str] = Field(default_factory=list, description="the units values are shown in")
    notes: dict[str, Any] = Field(default_factory=dict, description="anything kept beside it")


#: A stand-in template of a `Part`, every finding of it marked by its line below.
A_PART = '''\
# A stand-in part: prose, followed by a blank line, is not compared.

# the shape (manual: 3 · Write each part)
schema = 1

# what it is
description = """
units = "a line of the text, not a key"
"""

# the most it may take
limit = 4

# the finite element
[numerics.element]
# the element family: one of `lagrange`,
# `nedelec`
family = "lagrange"
# its polynomial degree, wrongly
# degree = 2
# a colour
colour = "red"

# the linear solver
# [numerics.solver]
# how it is solved: one of `direct`, `iterative`
# kind = "direct"

# its steps, by name
[steps]

# a note on a step, never compared
[steps.solve]
physics = "electrostatics"
# the geometry order: one of `1`, `2`
# order = 1
# its resources
resources = { ranks = 2 }
# the potential it is held at, in V
value = "1 V"

[kinds]
# a note on a name the person chose
side = "length"

# anything kept beside it
# [notes]
# kept = "x"
'''


def test_a_fields_help_is_its_description_its_closed_values_and_its_manuals_chapter():
    """Fails if a field's help leaves out the values a closed list allows — its own or a table's
    values, numbers too — or lists them for a value that is not only a closed list; or if a field
    stating a `doc` does not end with the chapter of the manual its file declares, by the
    chapter's title, a field stating none ends with one, or a help cites the `doc`, a contract
    (core.md § 2: "where the field states a `doc`, … `(manual: <chapter>)`"; docs/README.md § 3.1,
    M5)."""
    fields = [*Element.model_fields.items(), *Step.model_fields.items(), *Part.model_fields.items()]
    help = {name: described(f, "6-materials.md") for name, f in fields}
    assert help["family"] == "the element family: one of `lagrange`, `nedelec`"
    assert help["order"] == "the geometry order: one of `1`, `2`"
    assert help["kinds"] == "what each must be: one of `length`, `angle`"
    assert help["limit"] == "the most it may take"
    assert help["schema_"] == "the shape (manual: 6 · Materials)"
    assert described(Part.model_fields["schema_"]) == "the shape"   # no chapter declared: none named


def test_a_templates_comment_above_each_key_is_its_help():
    """Fails if a template's comment directly above a key the schema names is not held to its
    help — wrapped over lines, a key shown commented out under it, under a shown table header —
    or if prose, a name the person chose and its note, or a multi-line value's lines are taken for
    help or keys; if a key the schema does not allow, a table it names without a header of its
    own, keys it names written inline, or a key neither set nor shown passes; or if a key a
    declaration outside the schema states is not held to the help it gives, or a key stating a
    `doc` to the chapter of the manual its file declares (projects.md § 7; core.md § 2)."""
    def line(text: str) -> int:
        return next(n for n, written in enumerate(A_PART.splitlines(), 1) if written == text)

    def declared(path: tuple[str, ...]) -> str | None:
        return "the potential it is held at, in V" if path[0] == "steps" and path[-1] == "value" else None

    manual = "3-write-each-part.md"
    assert {(f.line, f.key) for f in help_findings(A_PART, Part, declared, manual)} == {
        (line("[numerics.element]"), "numerics"),                       # no header of its own
        (line("# degree = 2"), "numerics.element.degree"),              # its comment is not its help
        (line('colour = "red"'), "numerics.element.colour"),            # no key of the schema
        (line('physics = "electrostatics"'), "steps.solve.physics"),    # no help above it
        (line("resources = { ranks = 2 }"), "steps.solve.resources"),   # its keys written inline
        (line("[kinds]"), "kinds"),                                     # no help above it
        (None, "display"),                                              # neither set nor shown
    }
    assert (line('value = "1 V"'), "steps.solve.value") in {(f.line, f.key)
                                                            for f in help_findings(A_PART, Part, manual=manual)}
    assert (line("schema = 1"), "schema") in {(f.line, f.key) for f in help_findings(A_PART, Part, declared,
                                                                                     "6-materials.md")}


# ------------------------------------------------------------------ a file that does not load, in plain words (core.md § 2)

#: A `Part` that loads; each case below changes it once.
LOADS = 'schema = 1\ndescription = "d"\n\n[numerics.element]\nfamily = "lagrange"\n\n[numerics.solver]\nkind = "direct"\n'


@pytest.mark.parametrize("old, new, path, reason, right, choices", [
    ('description = "d"', 'descripton = "d"', "descripton",
     "`descripton` is no key here; did you mean `description`?", None, ("description",)),
    ('family = "lagrange"', 'family = "lagrnge"', "numerics.element.family",
     '`family` is "lagrnge"; did you mean "lagrange"?', None, ('"lagrange"', '"nedelec"')),
    ('kind = "direct"', 'kind = "by hand"', "numerics.solver.kind",
     '`kind` is "by hand"; it should be `direct` or `iterative`', None, ('"direct"', '"iterative"')),
    ('kind = "direct"\n', 'kind = "direct"\n\n[steps.a]\nphysics = "p"\norder = 3\n', "steps.a.order",
     "`order` is 3; it should be `1` or `2`", None, ("1", "2")),
    ("schema = 1", 'schema = 1\nlimit = "unlimted"', "limit",
     '`limit` is "unlimted"; did you mean "unlimited"?', None, ('"unlimited"',)),
    ('family = "lagrange"', "family = 1", "numerics.element.family",
     "`family` is 1; it should be `lagrange` or `nedelec`", None, ('"lagrange"', '"nedelec"')),
    ("schema = 1", 'schema = "one"', "schema", '`schema` is "one"; it should be a whole number', None, ()),
    ('\n[numerics.solver]\nkind = "direct"\n', "", "numerics", "`solver` is missing", None, ()),
], ids=["a misspelled key", "a misspelled value", "a value outside its list", "a number outside its list",
        "a misspelled value in a union", "a value of the wrong kind in a list", "a value of the wrong kind",
        "a missing table"])
def test_a_file_that_does_not_load_says_each_problem_plainly_at_its_key_with_what_would_be_right(
        old, new, path, reason, right, choices):
    """Fails if a declared file that does not load reads as pydantic's own words — `Field
    required` and `Extra inputs are not permitted` at two keys for one misspelling — rather than
    one problem at the key the person wrote, said plainly, with what would be right there: the
    keys its table may still take or the values its list allows, the closest first (core.md § 2;
    models.md § 13: "an unknown key | the key | the schema's key")."""
    assert LOADS.count(old) == 1
    with refused(DefinitionError, "definition-invalid", "part.toml") as caught:
        load_text(LOADS.replace(old, new), Part, "part.toml")
    assert [(p.path, p.reason, p.right) for p in caught.value.problems] == [(path, reason, right)]
    assert caught.value.problems[0].choices[:len(choices)] == choices


def test_a_value_outside_a_list_of_one_says_the_one_value_that_is_right():
    """Fails if a value that only one value would replace — a file's `schema` — gives choices
    rather than that one value (core.md §§ 2, 10: "where one value would be right ... it is
    `right`")."""
    class Shaped(Model):
        schema_: Literal[1] = Field(alias="schema", description="the shape")

    with refused(DefinitionError, "definition-invalid", "x.toml") as caught:
        load_text("schema = 2\n", Shaped, "x.toml")
    assert [(p.path, p.reason, p.right, p.choices) for p in caught.value.problems] == [
        ("schema", "`schema` is 2; it should be `1`", "1", ())]


@pytest.mark.parametrize("text, path, reason", [
    ('schema = 1\ndescription = "d\n', "", "line 2: a quoted text is not closed before the line ends"),
    ('schema = 1\n[steps.a]\nphysics = "p"\n\nphysics = "q"\n', "steps.a.physics",
     "`physics` is set twice (lines 3 and 5)"),
    ('[steps.a]\nphysics = "p"\n[steps.b]\n[steps.a]\n', "steps.a",
     "the table `[steps.a]` is written twice (lines 1 and 4)"),
    ("description = d e\n", "", "line 1: a value does not read: a text goes in quotes, a list in `[ ]`, a table in "
                                "`{ }`"),
    ('display = ["m"\n', "", "at the end of the file: a list opened with `[` is not closed with `]`"),
], ids=["a quoted text not closed", "a key set twice", "a table written twice", "a text not in quotes",
        "a list not closed"])
def test_a_text_that_is_no_toml_says_why_plainly_at_its_line(text, path, reason):
    """Fails if a text that is no TOML reads as tomllib's own words — `Illegal character '\\n'`,
    `Cannot overwrite a value` — rather than a plain sentence with its line, a key set twice
    at that key with both its lines (core.md § 2: "One TOML reader")."""
    with refused(DefinitionError, "definition-invalid", "part.toml") as caught:
        load_text(text, Part, "part.toml")
    assert [(p.path, p.reason) for p in caught.value.problems] == [(path, reason)]
