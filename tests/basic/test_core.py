"""The core building blocks (core.md)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from enum import Enum
from typing import Any, Literal

import pytest

from tests.kit import hold, refused, wait_until
from femkit.core import persist, text, view
from pydantic import Field, ValidationError
from femkit.core.schema import DefinitionError, Model, described, help_findings, load_text, load_toml

from femkit.core import process
from femkit.core.errors import Busy, Refused
from femkit.core.issues import Issue
from femkit.core.eventlog import EventLog, fold
from femkit.core.locks import subject_lock
from femkit.core import states
from femkit.core.states import Allowed, Machine, Rule


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
                {Light.on: {"off": Allowed("switch off", view.Verb("light.off", Switch, on_machine=False, effect="changes"), lambda f: {"lamp": "hall"}),
                            "dim": Allowed("dim", view.Verb("light.off", Switch, on_machine=False, effect="changes"), lambda f: {"lamp": "hall", "dim": True}),
                            "nothing": Allowed("nothing to do")},
                 Light.off: {}})
    assert m.observe(True) is Light.on and m.observe(False) is Light.off
    with refused(Refused, "not-allowed", "hall") as caught:
        m.require(Light.on, "on", True, "hall")
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
    name: str = "porch"


class LampOff(Model):
    lamp: str = Field(json_schema_extra={"cli": "argument"})
    room: str | None = None
    dim: bool = False


LAMP_OFF = view.Verb("lamp.off", LampOff, on_machine=False, effect="changes")
LAMP = states.Binding("lamp", {"bulb": lambda f: f.bulb, "power": lambda f: f.power, "switch": lambda f: f.switch,
                               "timer": lambda f: f.timer},
                      {"name": lambda f: f.name, "room": lambda f: "hall" if f.name.startswith("hall") else None},
                      acts=frozenset({"off", "dim"}))


def lamp(tmp_path, text: str = TABLE):
    path = tmp_path / "lamp.toml"
    path.write_text(text)
    return states.load(path, LAMP)


def test_a_machine_declared_as_data_observes_by_its_first_rule_that_holds_and_offers_its_actions(tmp_path):
    """Fails if a machine read from its table observes by any rule but the first whose condition
    holds over the named facts — `and`, `or`, `not` and parentheses as written — or offers other
    next steps than its table's: an operation with its request filled from the subject, a value
    the subject leaves unset left out — each value read from the subject's facts — a shell line
    (core.md § 7)."""
    m = lamp(tmp_path)
    facts = dict(bulb=True, power=True, switch=False, timer=False)
    assert m.observe(LampFacts(**{**facts, "bulb": False})) == "broken"
    assert m.observe(LampFacts(**facts)) == "on"                              # not timer
    assert m.observe(LampFacts(**{**facts, "timer": True})) == "off"          # power, but neither
    assert m.observe(LampFacts(**{**facts, "power": False, "switch": True})) == "off"
    assert [(a.command, a.call.request) for a in m.next(m.states("on"), LampFacts(**facts, name="hall-1"))] == [
        ("femkit lamp off hall-1 --room hall", {"lamp": "hall-1", "room": "hall"}),
        ("femkit lamp off hall-1 --dim", {"lamp": "hall-1", "dim": True})]
    assert m.next(m.states("on"), LampFacts(**facts))[0].call.request == {"lamp": "porch"}
    assert [a.command for a in m.next(m.states("broken"), LampFacts(**facts))] == ["replace the bulb"]
    with refused(Refused, "not-allowed", "porch") as caught:
        m.require(m.states("off"), "off", LampFacts(**facts), "porch")
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
    ('operation = "lamp.off"\nrequest = { lamp = "{name}", dim',
     'subject = true\noperation = "lamp.off"\nrequest = { lamp = "{name}", dim', "actions.on.dim"),
    ('describe = "replace the bulb"\nshell', 'describe = "replace the bulb"\nsubject = true\nshell',
     "actions.broken.replace"),
    ('request = { lamp = "{name}", dim = true }', 'request = { lamp = "{name}", dim = true }\nfills = ["colour"]',
     "actions.on.dim.fills"),
    ('describe = "replace the bulb"\nshell', 'describe = "replace the bulb"\nfills = ["room"]\nshell',
     "actions.broken.replace"),
], ids=["a state no rule gives", "otherwise before the last rule", "a last rule that is no otherwise",
        "a fact the domain does not name", "a comparison", "a call", "a state with no row of actions",
        "a value the subject does not give", "a placeholder inside a text", "an operation no verb declares",
        "a request field the operation lacks", "its subject's operation beside one of its own",
        "its subject's operation beside a shell line", "a fill the operation's request lacks",
        "a fill with no operation"])
def test_a_state_table_breaking_its_rules_is_refused_at_its_key(tmp_path, old, new, at):
    """Fails if a machine's table loads while a state is unreachable, the otherwise is not the last
    rule alone, a condition leaves its grammar or names a fact its domain does not, a state has no
    row of actions, or an action's request names a value the subject does not give, an operation
    no verb declares or a field that operation's request lacks, or a row says its operation is its
    subject's beside an operation or a shell line of its own, or asks a fill its operation's request
    lacks, or names no operation to fill — each refused at its key path
    (core.md § 7: "Closed and total, checked when the machine loads"; "or neither … save where the
    row says its operation is its subject's (`subject = true` …)"). The table as written loads (the
    test above), so each refusal is the one change's."""
    assert old in TABLE
    with refused(DefinitionError, "definition-invalid") as caught:
        lamp(tmp_path, TABLE.replace(old, new))
    assert at in [where for where, _ in caught.value.problems], caught.value.problems


#: The lamp's table with two rows of `off` that name neither an operation nor a shell line: one that
#: asks nothing, and one whose operation is its subject's own (core.md § 7, `subject = true`).
NEITHER = TABLE.replace("[actions.off]\n", '[actions.off]\nrest = { describe = "nothing to do" }\n'
                                           'again = { describe = "what made it, again", subject = true }\n')


def test_an_action_of_neither_operation_nor_shell_is_allowed_and_no_next_step_its_subjects_marked(tmp_path):
    """Fails if a row naming neither an operation nor a shell line is offered as a next step or is
    not allowed — its request refused — or loses the mark that its operation is its subject's, which
    that subject's own code reads in place of the row's name (core.md § 7: "or neither: the request
    is allowed and asks nothing of a person, never offered as a next step … save where the row says
    its operation is its subject's (`subject = true` …)")."""
    m = lamp(tmp_path, NEITHER)
    off, facts = m.states("off"), LampFacts(bulb=True, power=False, switch=False, timer=False)
    assert m.observe(facts) is off and m.next(off, facts) == ()
    assert [(n, m.require(off, n, facts, "porch").subject) for n in ("rest", "again")] == [("rest", False),
                                                                                         ("again", True)]


def test_a_tables_action_asks_the_fills_its_row_declares_each_its_fields_whole_fill(tmp_path):
    """Fails if a state table's action does not ask, before it runs, the values its row's `fills`
    names — each its request field's whole fill, one the request does not require marked so, to be
    left unset at will — or its command line does not write each as what it asks for (core.md § 7:
    "and `fills`, the fields of its request it asks of the person before it runs, each its field's
    whole fill, one the request does not require left unset at will"; web.md § 7.2)."""
    m = lamp(tmp_path, TABLE.replace('request = { lamp = "{name}", dim = true }',
                                     'request = { lamp = "{name}", dim = true }\nfills = ["room"]'))
    facts = LampFacts(bulb=True, power=True, switch=False, timer=False)
    dim = m.next(m.states("on"), facts)[1]
    assert [(f.field, f.required) for f in dim.fills] == [("room", False)]
    assert dim.command == "femkit lamp off porch --room ROOM --dim"


GRID = """\
[states]
dark = "the grid is down"
live = "otherwise: the grid is live"

[[rules]]
state = "dark"
when = "down"

[[rules]]
state = "live"
when = "otherwise"

[shows]
dark = "failed"
live = "up to date"

[actions.dark.report]
describe = "report the outage"
operation = "lamp.off"
request = { lamp = "{feeder}" }

[actions.live]
"""

PORCH = """\
past = "grid"

[states]
broken = "its bulb is broken"

[[rules]]
state = "broken"
when = "not bulb"

[shows]
broken = "needs attention"

[actions.broken.replace]
describe = "replace the bulb"
shell = "replace the bulb"
"""


class GridFacts(Model):
    down: bool
    feeder: str


class PorchFacts(Model):
    bulb: bool
    down: bool
    name: str


GRID_BINDING = states.Binding("grid", {"down": lambda f: f.down}, {"feeder": lambda f: f.feeder}, drawn=True,
                              acts=frozenset({"report"}))
PORCH_BINDING = states.Binding("porch", {"bulb": lambda f: f.bulb}, drawn=True,
                               hands=lambda f: GridFacts(down=f.down, feeder=f"feeder-{f.name}"))


def porch(tmp_path, grid: str = GRID, text: str = PORCH, binding: states.Binding = PORCH_BINDING):
    (tmp_path / "grid.toml").write_text(grid)
    (tmp_path / "porch.toml").write_text(text)
    return states.load(tmp_path / "porch.toml", binding)


def test_a_state_past_the_machines_own_is_the_other_machines_with_its_actions_and_words(tmp_path):
    """Fails if, where none of its own rules holds, a machine past another does not observe that
    machine's state over the facts its binding hands it — with that machine's actions, its next
    steps' values read from the facts handed, and its word — or its own states lose their own
    actions and words (core.md § 7: `past`, `[shows]`)."""
    m = porch(tmp_path)
    broken = m.observe(PorchFacts(bulb=False, down=True, name="hall"))
    assert broken is m.states.broken and m.word(broken) == "needs attention"
    assert [a.command for a in m.next(broken, PorchFacts(bulb=False, down=True, name="hall"))] == ["replace the bulb"]
    dark = m.observe(PorchFacts(bulb=True, down=True, name="hall"))
    assert dark.value == "dark" and not isinstance(dark, m.states)
    assert m.word(dark) == "failed" and list(m.allowed(dark)) == ["report"]
    assert [a.call.request for a in m.next(dark, PorchFacts(bulb=True, down=True, name="hall"))] == [
        {"lamp": "feeder-hall"}]
    live = m.observe(PorchFacts(bulb=True, down=False, name="hall"))
    assert live.value == "live" and m.word(live) == "up to date" and m.next(live, PorchFacts(
        bulb=True, down=False, name="hall")) == ()
    with refused(Refused, "not-allowed", "hall"):
        m.require(live, "report", PorchFacts(bulb=True, down=False, name="hall"), "hall")


NOT_DRAWN = states.Binding("porch_unseen", {"bulb": lambda f: f.bulb},
                           hands=lambda f: GridFacts(down=f.down, feeder=f.name))
UNHANDED = states.Binding("porch_alone", {"bulb": lambda f: f.bulb}, drawn=True)
READS_MORE = states.Binding("porch_more", {"bulb": lambda f: f.bulb}, drawn=True, acts=frozenset({"fix"}),
                            hands=lambda f: GridFacts(down=f.down, feeder=f.name))


@pytest.mark.parametrize("grid, old, new, binding, at", [
    (GRID, "[shows]\nbroken = \"needs attention\"\n", "", PORCH_BINDING, "shows"),
    (GRID, 'broken = "needs attention"', 'broken = "broken"', PORCH_BINDING, "shows.broken"),
    (GRID, "", "", NOT_DRAWN, "shows"),
    (GRID, "", "", READS_MORE, "actions"),
    (GRID, 'past = "grid"', 'past = "pylon"', PORCH_BINDING, "past"),
    (GRID.replace("[states]", 'past = "porch"\n\n[states]').replace(
        '[[rules]]\nstate = "live"\nwhen = "otherwise"\n', ""), "", "", PORCH_BINDING, "past"),
    (GRID, 'past = "grid"\n', "", PORCH_BINDING, "rules[0].when"),
    (GRID, "", "", UNHANDED, "past"),
    (GRID, 'when = "not bulb"\n', 'when = "not bulb"\n\n[[rules]]\nstate = "broken"\nwhen = "otherwise"\n',
     PORCH_BINDING, "rules[1].when"),
    (GRID.replace("[shows]\ndark = \"failed\"\nlive = \"up to date\"\n", ""), "", "", PORCH_BINDING, "past"),
], ids=["a drawn subject's table with no words", "a word outside the vocabulary's list",
        "words for a subject not drawn", "an action the code reads that no state declares",
        "past a machine that is none", "past a machine past it", "no otherwise and nothing past",
        "past, with no facts handed it", "an otherwise beside past", "past a machine that does not load"])
def test_a_table_breaking_past_shows_or_acts_is_refused_at_its_key(tmp_path, grid, old, new, binding, at):
    """Fails if a machine's table loads while its subject is drawn as a block and a state has no
    word of the vocabulary's list, or a subject not drawn has words; an action the code reads is
    declared by no state; it is past a machine that does not load, or that is past it, or names
    one that its code hands no facts — or none while its last rule is no otherwise, or an
    otherwise beside `past` — each refused at its key (core.md § 7: "Closed and total, checked
    when the machine loads"). The tables as written load (the test above), so each refusal is the
    one change's."""
    assert old in PORCH
    with refused(DefinitionError, "definition-invalid") as caught:
        porch(tmp_path, grid, PORCH.replace(old, new), binding)
    assert at in [where for where, _ in caught.value.problems], caught.value.problems


#: The porch's own tasks, each with its sentence, `tell` done only where its guard holds over the
#: porch's facts (core.md § 7, `[tasks]`).
PORCH_TASKS = PORCH + ('\n[tasks.tell]\ndescribe = "tells the house it is out"\nwhen = "loud"\n'
                       '\n[tasks.log]\ndescribe = "logs it"\n')
#: What the porch's operation does in each state — its own, and each of the grid it is past, every
#: one named: an empty list where it does none (core.md § 7, `[does]`).
PORCH_DOES = PORCH_TASKS + '\n[does]\nbroken = ["log"]\ndark = ["tell", "log"]\nlive = []\n'


class LoudFacts(Model):
    bulb: bool
    down: bool
    name: str
    loud: bool = False


LOUD_BINDING = states.Binding("porch", {"bulb": lambda f: f.bulb, "loud": lambda f: f.loud}, drawn=True,
                              tasks=frozenset({"tell"}),
                              hands=lambda f: GridFacts(down=f.down, feeder=f"feeder-{f.name}"))


def test_what_a_machine_does_in_a_state_is_its_tables_list_each_task_where_its_guard_holds(tmp_path):
    """Fails if what a machine's code does in a state — its own, or one of the machine it is past —
    is not the list of its own tasks `[does]` gives that very state, each kept only where its
    guard, a condition over the machine's own facts, holds; or a state given an empty list is not
    told from one whose tasks are all guarded off: the code refuses in the first and does nothing
    in the second (core.md § 7: "`[does]` … with the tasks its code does there, an empty list where
    it does none, and code refuses, naming the state (`Machine.does(state, facts)`, each task's
    guard applied)"; workflow.md § 6)."""
    m = porch(tmp_path, GRID, PORCH_DOES, LOUD_BINDING)

    def facts(**more) -> LoudFacts:
        return LoudFacts(**{"bulb": True, "down": True, "name": "hall", **more})

    assert m.does(m.observe(facts(bulb=False)), facts(bulb=False)) == ("log",)
    dark = m.observe(facts())
    assert dark.value == "dark" and m.does(dark, facts(loud=True)) == ("tell", "log")
    assert m.does(dark, facts()) == ("log",) and not m.idle(dark)
    live = m.observe(facts(down=False))
    assert m.does(live, facts(down=False)) == () and m.idle(live)
    assert dict(m.tasks) == {"tell": "tells the house it is out", "log": "logs it"}
    assert not {"tell", "log"} & {name for row in m.actions.values() for name in row}


@pytest.mark.parametrize("text, at", [
    (PORCH_DOES + 'fix = ["log"]\n', "does.fix"),
    (PORCH_DOES.replace('broken = ["log"]\n', ""), "does"),
    (PORCH_DOES.replace("live = []\n", ""), "does"),
    (PORCH_DOES.replace('dark = ["tell", "log"]', 'dark = ["tell", "mend"]'), "does.dark"),
    (PORCH_DOES.replace('dark = ["tell", "log"]', 'dark = ["report"]'), "does.dark"),
    (PORCH_DOES.replace('dark = ["tell", "log"]', 'dark = ["replace"]'), "does.dark"),
    (PORCH_TASKS, "does"),
    (PORCH + '\n[does]\nbroken = []\ndark = []\nlive = []\n', "does"),
    (PORCH_DOES.replace('when = "loud"', 'when = "loud or"'), "tasks.tell.when"),
    (PORCH_DOES.replace('when = "loud"', 'when = "shy"'), "tasks.tell.when"),
    (PORCH_DOES.replace('[states]\nbroken', '[states]\nlive = "it is on"\nbroken').replace(
        '[[rules]]\nstate = "broken"', '[[rules]]\nstate = "live"\nwhen = "bulb and loud"\n\n[[rules]]\n'
                                       'state = "broken"').replace(
        '[shows]\n', '[shows]\nlive = "up to date"\n').replace(
        '[actions.broken.replace]', '[actions.live]\n\n[actions.broken.replace]'), "does"),
], ids=["a key that is no state of its own nor down its past chain", "its own state not named",
        "a state down its chain not named", "a task neither machine has",
        "a task that is the other machine's action, not its own", "its own state's action, which is no task",
        "own tasks, and nothing said of what is done in each state", "what is done, and no tasks",
        "a guard outside the grammar", "a guard naming no fact of its machine's",
        "a state's name two tables of the chain share"])
def test_a_does_not_naming_each_state_with_its_own_guarded_tasks_is_refused_at_its_key(tmp_path, text, at):
    """Fails if a table's `[does]` loads while a key is no state of its own nor of the tables down
    its `past` chain, a state of those tables is not named, a task is not one of its own `[tasks]`
    — the other machine's action, or an action of its own states, among them — a machine with
    tasks of its own says nothing of what it does in each state, or says so with no tasks; a
    task's guard leaves the grammar or names a fact its machine's code does not give; or a state's
    name is two tables' of the chain, so `[does]` could not tell which it means — each refused at
    its key (core.md § 7: "`[tasks]` … optionally, `when`, its guard over the binding's facts";
    "`[does]` … every one named, a name two tables of the chain share refused … each key and task
    checked at load"). Each table loads without the one change (the test above)."""
    with refused(DefinitionError, "definition-invalid") as caught:
        porch(tmp_path, GRID, text, LOUD_BINDING)
    assert at in [where for where, _ in caught.value.problems], caught.value.problems


#: Three machines, each past the next: a porch light past its street's grid, past the mains.
MAINS = GRID.replace("the grid is down", "the mains are down").replace(
    "otherwise: the grid is live", "otherwise: the mains are live").replace("[actions.dark.report]",
                                                                            "[actions.dark.call]")
CHAIN_GRID = 'past = "chain_mains"\n\n' + GRID.replace('[[rules]]\nstate = "live"\nwhen = "otherwise"\n', "").replace(
    '[[rules]]\nstate = "dark"\nwhen = "down"\n', '[[rules]]\nstate = "faulty"\nwhen = "fault"\n').replace(
    '[states]\ndark = "the grid is down"\nlive = "otherwise: the grid is live"\n',
    '[states]\nfaulty = "its own feeder is down"\n').replace(
    '\n[shows]\ndark = "failed"\nlive = "up to date"\n', '\n[shows]\nfaulty = "failed"\n').replace(
    "\n[actions.live]\n", "\n").replace("[actions.dark.report]", "[actions.faulty.report]")
#: The porch past the grid past the mains: what it does in each state of all three, every one named.
CHAIN_PORCH = (PORCH_TASKS.replace('past = "grid"', 'past = "chain_grid"')
               + '\n[does]\nbroken = []\nfaulty = []\ndark = ["tell", "log"]\nlive = ["log"]\n')
CHAIN_MAINS_BINDING = states.Binding("chain_mains", {"down": lambda f: f.down}, {"feeder": lambda f: f.feeder},
                                     drawn=True)
CHAIN_GRID_BINDING = states.Binding("chain_grid", {"fault": lambda f: False}, {"feeder": lambda f: f.feeder},
                                    drawn=True, hands=lambda f: f)
CHAIN_PORCH_BINDING = states.Binding("chain_porch", {"bulb": lambda f: f.bulb, "loud": lambda f: f.loud},
                                     drawn=True, tasks=frozenset({"tell"}),
                                     hands=lambda f: GridFacts(down=f.down, feeder=f"feeder-{f.name}"))


def chained(tmp_path, porch_text: str = CHAIN_PORCH, binding: states.Binding = CHAIN_PORCH_BINDING):
    for name, text in (("chain_mains", MAINS), ("chain_grid", CHAIN_GRID)):
        (tmp_path / f"{name}.toml").write_text(text)
    (tmp_path / "chain_porch.toml").write_text(porch_text)
    return states.load(tmp_path / "chain_porch.toml", binding)


def test_does_names_every_state_down_a_past_chain_and_gives_their_tasks_in_them(tmp_path):
    """Fails if a machine's `[does]` must not, or may not, name the states of a table further down
    its `past` chain than the one it names, or does not give its tasks in them, each where its
    guard holds — while the next steps there stay that table's actions (core.md § 7: "`[does]` …
    for a machine `past` another, each state of the tables down the `past` chain — every one
    named")."""
    m = chained(tmp_path)
    loud = LoudFacts(bulb=True, down=True, name="hall", loud=True)
    dark = m.observe(loud)
    assert dark.value == "dark" and m.does(dark, loud) == ("tell", "log")
    quiet = LoudFacts(bulb=True, down=False, name="hall")
    assert m.does(m.observe(quiet), quiet) == ("log",)
    assert [a.call.request for a in m.next(dark, loud)] == [{"lamp": "feeder-hall"}]
    with refused(DefinitionError, "definition-invalid") as caught:
        chained(tmp_path, CHAIN_PORCH.replace("live = [\"log\"]\n", ""))
    assert "does" in [where for where, _ in caught.value.problems], caught.value.problems


def test_a_task_the_code_does_that_its_table_does_not_declare_is_refused_at_tasks(tmp_path):
    """Fails if a machine whose code does a task by name loads while its table's `[tasks]` lacks
    it, so it would be met first while the code runs (core.md § 7: "every state and every action
    the binding's code reads is declared"; "`[tasks]` … what its code does to the subject")."""
    with refused(DefinitionError, "definition-invalid") as caught:
        chained(tmp_path, CHAIN_PORCH.replace('\n[tasks.tell]\ndescribe = "tells the house it is out"\nwhen = "loud"\n',
                                              "").replace('dark = ["tell", "log"]', 'dark = ["log"]'))
    assert "tasks" in [where for where, _ in caught.value.problems], caught.value.problems


#: A relay of lamps: one waits while the lamp it takes its power from is off, and its next steps are
#: that lamp's (core.md § 7, `[next_from.<state>]`).
RELAY = """\
[states]
waiting = "the lamp it takes its power from is out"
lit = "otherwise: it is lit"

[[rules]]
state = "waiting"
when = "source_out"

[[rules]]
state = "lit"
when = "otherwise"

[actions.waiting]

[actions.lit.off]
describe = "switch it off"
operation = "lamp.off"
request = { lamp = "{name}" }

[next_from.waiting]
subject = "source"
"""


class RelayFacts(Model):
    name: str
    source: "RelayFacts | None" = None


RELAY_BINDING = states.Binding("relay", {"source_out": lambda f: f.source is not None},
                               {"name": lambda f: f.name}, subjects={"source": lambda f: f.source})


def relay(tmp_path, text: str = RELAY):
    path = tmp_path / "relay.toml"
    path.write_text(text)
    return states.load(path, RELAY_BINDING)


def test_a_states_next_steps_declared_from_another_subject_are_that_subjects(tmp_path):
    """Fails if a state the table declares `[next_from.<state>]` for does not give, as its next
    steps, those of the subject the binding hands by that name — observed by the same machine,
    down any number of such states — rather than its own actions, or a branch in code (core.md
    § 7: "`[next_from.<state>]` a state whose next steps are another subject's, by the name the
    binding hands it … in place of its actions"; workflow.md § 6: a waiting stage's next steps are
    the stage it waits on's, declared)."""
    m = relay(tmp_path)
    lit = RelayFacts(name="c")
    one, two = RelayFacts(name="b", source=lit), RelayFacts(name="a", source=RelayFacts(name="b", source=lit))
    assert m.observe(one) is m.states.waiting
    assert [a.call.request for a in m.next(m.observe(one), one)] == [{"lamp": "c"}]
    assert [a.call.request for a in m.next(m.observe(two), two)] == [{"lamp": "c"}]
    assert [a.call.request for a in m.next(m.observe(lit), lit)] == [{"lamp": "c"}]


@pytest.mark.parametrize("old, new, at", [
    ('[next_from.waiting]', '[next_from.asleep]', "next_from.asleep"),
    ('subject = "source"', 'subject = "feeder"', "next_from.waiting.subject"),
    ("[actions.waiting]\n", '[actions.waiting.off]\ndescribe = "switch it off"\noperation = "lamp.off"\n'
                            'request = { lamp = "{name}" }\n', "actions.waiting"),
], ids=["a state the table lacks", "a subject the binding hands none by", "a state with actions of its own"])
def test_a_next_from_naming_what_is_not_there_is_refused_at_its_key(tmp_path, old, new, at):
    """Fails if a table's `[next_from.<state>]` loads while it names a state the table lacks, a
    subject the binding hands none by, or a state that keeps actions of its own beside it — each
    refused at its key (core.md § 7: "by the name the binding hands it … in place of its
    actions"; "Closed and total, checked when the machine loads"). The table loads as written (the
    test above)."""
    assert old in RELAY
    with refused(DefinitionError, "definition-invalid") as caught:
        relay(tmp_path, RELAY.replace(old, new))
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


def test_the_event_log_fold_names_the_step_running_while_its_run_goes_on_and_none_once_it_ends(tmp_path):
    """Fails if a surface following a run could not tell which step's last lines to show, or
    were told a step runs in a run that ended or whose writer is gone (core.md § 6)."""
    me = {"kind": "operation-start", "process": process.identify(os.getpid()).as_json()}
    going = [me, {"kind": "step-start", "step": "a"}, {"kind": "step-end", "step": "a", "outcome": "done"},
             {"kind": "step-start", "step": "b"}]
    assert fold(going).running == "b"
    assert fold(going + [{"kind": "step-end", "step": "b", "outcome": "done"}]).running is None
    assert fold(going + [{"kind": "operation-end", "outcome": "done"}]).running is None
    gone = {**me, "process": {**me["process"], "start": me["process"]["start"] + 1}}   # another process's start
    assert fold([gone, *going[1:]]).running is None


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


def test_a_refusal_becomes_an_issue_one_way_keeping_its_code_subject_and_next():
    """Fails if a refusal turned into a finding loses its code — said as a code of its own, as
    `refused` once was — its subject or its next steps, or takes a message other than its own unless
    one is given (core.md § 10: `Issue.of`, "a refusal as an issue — its code, subject and next
    kept; the one way, never by hand")."""
    step = view.command(LAMP_OFF, lamp="hall")
    exc = Refused("the lamp is out of reach", (step,), code="out-of-reach", subject="lamp:hall")
    made = Issue.of(exc, "warning")
    assert (made.severity, made.code, made.subject, made.message, made.next) == (
        "warning", "out-of-reach", "lamp:hall", "the lamp is out of reach", (step,))
    assert Issue.of(exc, "error", "the hall stays lit: the lamp is out of reach").message == \
        "the hall stays lit: the lamp is out of reach"


class Shelf(Model):
    """A row of a table of the test's own."""

    book: str = Field(description="the book on it", json_schema_extra={"doc": "core.md § 10"})
    count: int = Field(description="how many there are")
    on_loan: bool = Field(title="lent", description="whether it is out")
    shelf_mark: str = Field(description="where it stands")
    unsaid: str = ""


def test_a_tables_columns_are_its_row_models_fields_each_labelled_and_helped_by_its_description():
    """Fails if a table's column takes a heading a report writes by hand rather than its row model's
    field — its short name as its label, the `title` its declaration gives or else its key, and its
    description as its help, the field's `doc` beside it — or if a column a row model lacks, or one
    whose field says nothing, is made at all (web.md § 7.5: "each column's label the field's short
    name — the `title` its declaration gives, else its key, spaces for underscores — and its help the
    field's description and `doc` … never a heading written by hand in a `report()`")."""
    table = view.Table.of(Shelf, [{"book": "atlas", "count": 2, "on_loan": False, "shelf_mark": "A1"}],
                          "book", "count", "on_loan", "shelf_mark")
    assert [(c.key, c.label, c.help.sentence, c.help.doc.document if c.help.doc else None)
            for c in table.columns] == [("book", "book", "the book on it", "docs/contracts/core.md"),
                                        ("count", "count", "how many there are", None),
                                        ("on_loan", "lent", "whether it is out", None),
                                        ("shelf_mark", "shelf mark", "where it stands", None)]
    table = view.Table.of(Shelf, [{"book": "atlas", "count": 2}], "book", "count")
    assert table.rows == [{"book": "atlas", "count": 2}]
    assert [c.key for c in view.Table.of(Shelf, [], "count").columns] == ["count"]
    with pytest.raises(ValueError, match="cover"):
        view.Table.of(Shelf, [], "cover")
    with pytest.raises(ValueError, match="unsaid"):
        view.Table.of(Shelf, [], "unsaid")
    with pytest.raises(ValueError, match="title"):
        view.Table.of(Shelf, [{"book": "atlas", "title": "?"}], "book")


def test_a_graph_in_a_report_is_written_on_the_command_line_as_its_tables():
    """Fails if a graph, a block of a report like any other, is not written by the command line's one
    renderer as the tables it shows — each node with its kind, state, word, folder and findings where
    a node holds them, each wire from where to where, each output holding a file with the line that
    opens it, each heading the person's word its field declares — or if a report cannot hold a graph
    at all (web.md § 7.7: "each block a `Text`, a `Code`, a `Table`, a `Graph`, or a `Next` … a
    graph as its tables"; § 7.5)."""
    found = Issue(severity="error", code="x", subject="part:a", message="m")
    opens = view.shell("gmsh run/geometry.xao")
    graph = view.Graph(nodes=[view.GraphNode(address="part:a", family=view.PART, kind="part", type="kind-a", label="a",
                                             state="errors", shows="needs attention", issues=[found]),
                              view.GraphNode(address="part:b", family=view.PART, kind="part", label="b",
                                             state="complete", shows="up to date"),
                              view.GraphNode(address="stage:g", family=view.STAGE, kind="geometry", label="g",
                                             ports=[view.GraphPort(name="output", side=view.OUT,
                                                                   accepts=["geometry/xao"], many=False,
                                                                   file="run/geometry.xao", actions=[opens]),
                                                    view.GraphPort(name="log", side=view.OUT, accepts=["text/log"],
                                                                   many=False)])],
                       wires=[view.Wire(source="part:a", target="part:b", type="part", address="part:b:names")])
    report = view.Report(blocks=[view.Text(text="three nodes"), graph])
    assert view.Report.model_validate(report.model_dump(mode="json")) == report
    lines = text.report(report).splitlines()
    cells = lambda line: [c.strip() for c in line.split("  ") if c.strip()]
    assert lines[0] == "three nodes"
    assert cells(lines[1]) == ["node", "kind", "state", "shows", "findings"]
    assert cells(lines[2]) == ["part:a", "part: kind-a", "errors", "needs attention", "1"]
    assert cells(lines[3]) == ["part:b", "part", "complete", "up to date"]
    assert cells(lines[4]) == ["stage:g", "geometry"]
    assert lines[5] == "", "each of a graph's tables stands apart"
    assert cells(lines[6]) == ["from", "to", "written at"]
    assert cells(lines[7]) == ["part:a", "part:b", "part:b:names"]
    assert lines[8] == ""
    assert cells(lines[9]) == ["node", "name", "file", "actions"]
    assert cells(lines[10]) == ["stage:g", "output (geometry/xao)", "run/geometry.xao", str(opens)]
    assert len(lines) == 11, "an output that holds no file is not written"


@pytest.mark.parametrize("key, line", [
    ("name", 1),                         # a key at the top
    ("conditions.left.kind", 5),         # a key of a table
    ("conditions.left.value", 4),        # one its table leaves out: the table's header
    ("conditions.right.kind", 8),        # one inside an inline table: the line that writes it
    ('axes."mesh:uniform:size".values', 10),
    ("builds[1].id", 14),                # the second of a list of tables
    ("nowhere.at.all", None),
    ("", None),
])
def test_the_line_a_toml_text_writes_a_key_at_is_read_from_the_text(key, line):
    """Fails if a finding at a key of a TOML file cannot be given the line its key stands at — read
    from the file's own text, as a Python file's line is — or a key the text leaves out is given no
    line where the table it belongs to stands (core.md § 10: `line`, "every finding at a key, a TOML
    file's as a Python file's, the door reading it from the file's text")."""
    toml = ('name = "slab"\n'
            "# the conditions\n"
            "\n"
            "[conditions.left]\n"
            'kind = "potential"\n'
            "\n"
            "[conditions]\n"
            'right = { kind = "insulating" }\n'
            '[axes."mesh:uniform:size"]\n'
            "values = [1, 2]\n"
            "[[builds]]\n"
            'id = "a"\n'
            "[[builds]]\n"
            'id = "b"\n')
    assert persist.key_line(toml, key) == line


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


# A process that starts another in its group, which ignores SIGTERM when it is the one named
# deaf, and says that one's ID once both are ready: on its output, or into the file named.
A_GROUP = """
import signal, subprocess, sys, time
deaf, said = sys.argv[1], sys.argv[2]
grandchild = subprocess.Popen([sys.executable, "-c", "import signal, sys, time;"
    "sys.argv[1] == 'grandchild' and signal.signal(signal.SIGTERM, signal.SIG_IGN);"
    "print(flush=True); time.sleep(60)", deaf], stdout=subprocess.PIPE)
grandchild.stdout.readline()
if deaf == "leader":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if said == "-":
    print(grandchild.pid, flush=True)
else:
    open(said, "w").write(str(grandchild.pid))
time.sleep(60)
"""


@pytest.mark.parametrize("deaf, status", [("leader", -signal.SIGKILL), ("grandchild", -signal.SIGTERM)])
def test_stopping_a_child_ends_its_whole_group_and_kills_what_ignores_sigterm_after_the_grace(deaf, status):
    """Fails if stopping a child spares a process it started in its group, sends SIGKILL before
    the grace has passed, or never sends it to what ignores SIGTERM — the child itself, or a
    process it started that outlives it (core.md § 8: "SIGTERM to the whole process group, then
    SIGKILL after GRACE")."""
    child = process.Child.start([sys.executable, "-c", A_GROUP, deaf, "-"], output="pipe")
    grandchild = None
    try:
        said = b""
        for chunk in child.chunks():
            said += chunk
            if said.endswith(b"\n"):
                break
        grandchild = process.identify(int(said))
        began = time.monotonic()
        assert child.stop(grace=1) == status
        assert 1 <= time.monotonic() - began < 4
        assert wait_until(lambda: not grandchild.alive(), timeout=3)
    finally:                                                 # nothing left running, whatever failed
        child.stop(grace=0)
        if grandchild is not None:
            process.end(grandchild, grace=0)


def test_a_group_started_earlier_is_ended_through_its_leaders_identity_alone(tmp_path):
    """Fails if a run launched earlier, known by the identity its record keeps, is ended without
    the processes it started in its group, or a process that leads no group has a group
    signalled in its name (core.md § 8: "a group is signalled only through its leader's
    `Identity`")."""
    said = tmp_path / "grandchild.pid"
    kept = process.start_detached([sys.executable, "-c", A_GROUP, "grandchild", str(said)]).as_json()
    leader, grandchild = process.Identity.from_json(kept), None
    try:
        assert wait_until(lambda: said.exists() and said.read_text().isdigit())
        grandchild = process.identify(int(said.read_text()))
        with pytest.raises(ValueError):
            process.end(grandchild, group=True)              # a member of the group, not its leader
        assert grandchild.alive() and leader.alive()         # nothing was signalled
        assert process.end(leader, grace=1, group=True)
        assert wait_until(lambda: not grandchild.alive() and not leader.alive(), timeout=3)
    finally:                                                 # nothing left running, whatever failed
        for who in (leader, grandchild):
            if who is not None:
                process.end(who, grace=0)


def test_a_run_launched_earlier_gets_one_signal_never_escalated(tmp_path):
    """Fails if the signal for a run launched earlier waits and escalates to SIGKILL — a run's own
    handler answers the signal — reaches past its group's leader's identity, or says it signalled a
    process that was not running (core.md § 8: "A run launched earlier is never escalated: it gets
    one signal")."""
    said = tmp_path / "grandchild.pid"
    kept = process.start_detached([sys.executable, "-c", A_GROUP, "leader", str(said)]).as_json()
    leader, grandchild = process.Identity.from_json(kept), None
    try:
        assert wait_until(lambda: said.exists() and said.read_text().isdigit())
        grandchild = process.identify(int(said.read_text()))
        with pytest.raises(ValueError):
            process.signal(grandchild, signal.SIGTERM, group=True)   # a member of the group, not its leader
        began = time.monotonic()
        assert process.signal(leader, signal.SIGTERM, group=True)
        assert time.monotonic() - began < 1                          # sent, not waited on
        assert wait_until(lambda: not grandchild.alive(), timeout=3)  # the group heard it
        time.sleep(0.5)
        assert leader.alive()                                        # the leader ignores it: nothing followed
    finally:
        for who in (leader, grandchild):
            if who is not None:
                process.end(who, grace=0)
    ended = process.Child.start([sys.executable, "-c", "pass"])
    ended.wait()                                                     # ended and reaped
    assert not process.signal(ended.identity, signal.SIGTERM)       # gone: nothing is sent


def test_a_child_kept_in_its_starters_group_shares_it_and_is_stopped_alone():
    """Fails if a run waited on is started in a session of its own — so Ctrl-C at its launch, or
    a stop sent to a sequence's walk, would never reach it — if any other child shares its
    starter's group, or if stopping a child kept in its starter's group does not stop it alone by
    the one escalation — signalling a group it does not lead, then waiting on it unbounded
    (core.md § 8: `own_group`)."""
    kept = process.Child.start([sys.executable, "-c", "import time; time.sleep(60)"], own_group=False)
    own = process.Child.start([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert os.getpgid(kept.identity.pid) == os.getpgrp()
        assert os.getpgid(own.identity.pid) == own.identity.pid != os.getpgrp()
    finally:
        own.stop(grace=0)
    began = time.monotonic()
    assert kept.stop(grace=1) == -signal.SIGTERM               # stopped alone, by the one escalation
    assert time.monotonic() - began < 2 and os.getpgrp() == os.getpgid(0)   # and this process untouched


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
[steps.potential]
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
        (line('physics = "electrostatics"'), "steps.potential.physics"),    # no help above it
        (line("resources = { ranks = 2 }"), "steps.potential.resources"),   # its keys written inline
        (line("[kinds]"), "kinds"),                                     # no help above it
        (None, "display"),                                              # neither set nor shown
    }
    assert (line('value = "1 V"'), "steps.potential.value") in {(f.line, f.key)
                                                            for f in help_findings(A_PART, Part, manual=manual)}
    assert (line("schema = 1"), "schema") in {(f.line, f.key) for f in help_findings(A_PART, Part, declared,
                                                                                     "6-materials.md")}


# ------------------------------------------------------------------ placeholders (core.md § 2.1)

ARGS = ["{python}", "geometry.py", "{inputs}", "{output}", "{mesh?}"]


def test_an_optional_placeholder_alone_in_an_argument_is_left_out_when_its_value_is_absent():
    """Fails if `{name?}` is not one of the grammar's placeholders, if an argument holding it alone
    is kept when its value is absent — a geometry script would be handed a mesh path its contract
    never declared — or dropped when present, or if a placeholder without `?` may be absent
    (core.md § 2.1)."""
    from femkit.core.schema import check_arguments, check_placeholders, render_arguments
    allowed = frozenset({"python", "inputs", "output", "mesh"})
    assert check_arguments(ARGS, allowed) == ARGS
    for misplaced in (["--mesh={mesh?}"], ["{mesh?:x}"], ["{mesh?}{output}"]):
        with pytest.raises(ValueError):                                 # refused at load, not when rendered
            check_arguments(misplaced, allowed)
    with pytest.raises(ValueError):
        check_placeholders("{mesh?}", allowed)                          # outside an argument list: nowhere
    given = {"python": "/p/bin/python", "inputs": "inputs.json", "output": "geometry.xao"}
    assert render_arguments(ARGS, {**given, "mesh": None}) == ["/p/bin/python", "geometry.py", "inputs.json",
                                                               "geometry.xao"]
    assert render_arguments(ARGS, {**given, "mesh": "mesh.msh"})[-1] == "mesh.msh"
    with pytest.raises(ValueError):
        render_arguments(ARGS, {**given, "output": None, "mesh": None})     # only `?` may be absent
    with pytest.raises(ValueError):
        render_arguments(["{output:stem}"], {"output:stem": None})          # an argument's value, too


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


@pytest.mark.parametrize("text, path, reason, line, said", [
    ('schema = 1\ndescription = "d\n', "", "a quoted text is not closed before the line ends", 2,
     "part.toml: line 2: a quoted text is not closed before the line ends"),
    ('schema = 1\n[steps.a]\nphysics = "p"\n\nphysics = "q"\n', "steps.a.physics",
     "`physics` is set twice (lines 3 and 5)", 5, "part.toml: steps.a.physics: `physics` is set twice (lines 3 and 5)"),
    ('[steps.a]\nphysics = "p"\n[steps.b]\n[steps.a]\n', "steps.a",
     "the table `[steps.a]` is written twice (lines 1 and 4)", 4,
     "part.toml: steps.a: the table `[steps.a]` is written twice (lines 1 and 4)"),
    ("description = d e\n", "", "a value does not read: a text goes in quotes, a list in `[ ]`, a table in `{ }`", 1,
     "part.toml: line 1: a value does not read: a text goes in quotes, a list in `[ ]`, a table in `{ }`"),
    ('display = ["m"\n', "", "at the end of the file: a list opened with `[` is not closed with `]`", None,
     "part.toml: <file>: at the end of the file: a list opened with `[` is not closed with `]`"),
], ids=["a quoted text not closed", "a key set twice", "a table written twice", "a text not in quotes",
        "a list not closed"])
def test_a_text_that_is_no_toml_says_why_plainly_and_its_line_once(text, path, reason, line, said):
    """Fails if a text that is no TOML reads as tomllib's own words — `Illegal character '\\n'`,
    `Cannot overwrite a value` — rather than a plain sentence, a key set twice at that key with both
    its lines; or if its line is not carried as the problem's own, the finding's, or is said twice —
    in the reason as well — or not at all where the refusal is written as text (core.md § 2: "One
    TOML reader", "Why a text is not TOML is said in plain words at its line"; § 10: `line`)."""
    with refused(DefinitionError, "definition-invalid", "part.toml") as caught:
        load_text(text, Part, "part.toml")
    assert [(p.path, p.reason, p.line) for p in caught.value.problems] == [(path, reason, line)]
    assert str(caught.value) == said


def test_a_toml_text_is_read_as_its_file_is_read_comments_and_order_kept(tmp_path):
    """Fails if a TOML text a person typed is read otherwise than `read_document` reads the same
    text in a file — its comments, order and layout kept — or a text that is not TOML is read at
    all rather than refused: the door's text is read by persist alone, the one reader of a TOML
    text (core.md § 4: "`toml_document(text)` a TOML text as read_document reads a file")."""
    typed = '# the help\nsize = "1 nm"   # its own\n\n[mesh]\norder = 2\n'
    (tmp_path / "part.toml").write_text(typed)
    held = persist.toml_document(typed)
    assert held == persist.read_document(tmp_path / "part.toml") and held.as_string() == typed
    assert persist.document_text(held, ("mesh",)) == "order = 2\n"
    with pytest.raises(ValueError):
        persist.toml_document('size = "1 nm\n')


def test_one_reader_says_whether_a_file_femkit_writes_is_absent_reads_or_why_not(tmp_path):
    """Fails if a file femkit writes is not read by its one reader, telling a file that is not there
    from one that reads and from one that does not — no JSON, or another shape, a file stating
    another `schema` among them — and saying why (core.md § 4: "read back by one reader,
    `read_record(file, model)` — absent, read, or why it does not read")."""
    class Shaped(Model):
        schema_: Literal[1] = Field(alias="schema")
        word: str

    file = tmp_path / "record.json"
    assert not persist.read_record(file, Shaped).there
    for held, reads in (('{"schema": 1, "word": "w"}', True), ('{"schema": 2, "word": "w"}', False),
                        ("{", False), ('{"word": "w"}', False)):
        file.write_text(held)
        got = persist.read_record(file, Shaped)
        assert (got.there, got.reads, got.problem is None) == (True, reads, reads), held
    file.write_text('{"schema": 1, "word": "w"}')
    assert persist.read_record(file, Shaped).value.word == "w"
