"""The state-machine primitive (core.md § 7, framework.md § 3).

A machine is one closed table: an enumeration of states, an ordered list of
observation rules whose last is ``otherwise`` (so no observation falls
through), and the actions each state allows. State is computed from facts
every time it is asked; it is never stored.

A machine is declared as data, `femkit/data/states/<machine>.toml` (its schema `StateTable`):
its states, its rules as conditions over named facts, its actions — and, for a subject the page
draws as a block, each state's word (`[shows]`); its own tasks, each with its sentence: what its
code does to the subject, said in a plan and an outcome, never a next step — and, optionally, its
guard, a condition over the machine's facts where it is done (`[tasks]`); a machine past another
ends its rules there (`past`): where none holds, the subject is in that machine's state, with that
machine's actions and words; what its own code does in each state — its own, and every state of the
tables down its `past` chain, every one named, none named by two of them — is the list of its own
tasks its table gives that very state, each done where its guard holds, an empty list where it does
none (`[does]`); a state whose next steps are another subject's, by the name the binding hands that
subject, in place of its own actions (`[next_from.<state>]`).
Code gives it only what code must: each named predicate over the facts its domain's one function
gathers, the values a request takes from the subject, read from those facts — and, for a field a
row asks of the person, the names it may take for the subject where they are narrower than its
declaration, read from them too — the states, actions
and tasks its code reads by name, whether its subject is drawn, the facts it hands the machine it
is past, and each other subject it hands by name (`Binding`); `load` reads the file and binds it,
the one loader; every machine femkit has is declared so (`femkit/data/states/`).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generic, Mapping, Sequence, TypeVar

from pydantic import Field, ValidationInfo, model_validator

from femkit.core import view
from femkit.core.errors import Refused
from femkit.core.schema import DefinitionError, Model, key_path, load_toml, parsed, refuse, render

F = TypeVar("F")
S = TypeVar("S", bound=Enum)


@dataclass(frozen=True)
class Rule(Generic[F, S]):
    """``when`` is None for the closing ``otherwise`` rule."""

    describe: str
    state: S
    when: Callable[[F], bool] | None = None


def _nothing(facts: Any) -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class Allowed:
    """What a state allows: the verb that does it and its request's values, read from the facts
    of the subject the machine describes; or a shell line that is no operation; or neither — the
    request allowed, nothing asked of a person, never a next step — save where its operation is its
    subject's own (`subject`), which that subject's code offers in its place (core.md § 7)."""

    describe: str
    verb: view.Verb | None = None
    values: Callable[[Any], dict[str, Any]] = _nothing
    shell: str | None = None
    subject: bool = False      # naming neither: its operation is its subject's own — a launch folder's maker's
    fills: tuple[str, ...] = ()   # the fields of its request it asks of the person before it runs
    # for a field it fills, the names it may take for the subject, read from its facts (`Binding.choices`)
    choices: Mapping[str, Callable[[Any], Sequence[str] | None]] = field(default_factory=dict)
    given: Callable[[Any], dict[str, Any]] = _nothing   # each value the subject gives, which a shell line names

    def next(self, facts: Any) -> view.Action | None:
        """The next step it is for the subject of ``facts``, as every surface shows one — a shell line
        with each value it names the subject's; none where it names neither an operation nor a shell
        line — one whose operation is its subject's is that subject's code to offer — or where the
        subject leaves unset a value its operation's request requires — a key it leaves unset is left
        out (core.md § 7), and such a step is none the subject can take. Each value it asks is its
        field's whole fill, its choices the names the subject's facts give where the binding narrows
        them (`Binding.choices`)."""
        if self.shell is not None:
            return view.shell(render(self.shell, {k: str(v) for k, v in self.given(facts).items()}))
        if self.verb is None:
            return None
        values = self.values(facts)
        if any(f.is_required() and n not in values and n not in self.fills
               for n, f in self.verb.request.model_fields.items()):
            return None
        fills = [view.Fill.of(self.verb.request, f, choices=self.choices[f](facts) if f in self.choices else None)
                 for f in self.fills]
        return view.command(self.verb, label=self.describe, fills=fills, **values)


@dataclass(frozen=True)
class Machine(Generic[F, S]):
    """One machine: its own states, its rules, the actions and the word of each own state — and,
    where it is past another, that machine and the facts it is handed: a state past the
    machine's own is that machine's member, its actions, its next steps and its word read from
    that machine (core.md § 7)."""

    name: str
    states: type[S]
    rules: tuple[Rule[F, S], ...]
    actions: Mapping[S, Mapping[str, Allowed]] = field(default_factory=dict)
    shows: Mapping[S, str] = field(default_factory=dict)
    past: "Machine | None" = None
    hands: Callable[[F], Any] | None = None
    done: Mapping[str, tuple[str, ...]] = field(default_factory=dict)   # each state, its own or down `past`, by
                                                                        # its name: the own tasks done in it
    tasks: Mapping[str, str] = field(default_factory=dict)    # its own tasks, each with its sentence
    guards: Mapping[str, Callable[[F], bool]] = field(default_factory=dict)   # a task's guard, where it has one
    next_from: Mapping[S, str] = field(default_factory=dict)  # a state whose next steps are another subject's: its name
    subjects: Mapping[str, Callable[[F], Any]] = field(default_factory=dict)   # each other subject, by its name

    def __post_init__(self) -> None:
        if self.past is None and (not self.rules or self.rules[-1].when is not None):
            raise ValueError(f"{self.name}: the last observation rule must be `otherwise`")
        if self.past is not None and (self.hands is None or any(r.when is None for r in self.rules)):
            raise ValueError(f"{self.name}: a machine past another has no `otherwise`, and hands it its facts")
        if any(r.when is None for r in self.rules[:-1]):
            raise ValueError(f"{self.name}: only the last observation rule may be `otherwise`")
        foreign = [r.describe for r in self.rules if r.state not in set(self.states)]
        if foreign:
            raise ValueError(f"{self.name}: rules produce states outside {self.states.__name__}: {foreign}")
        unreachable = set(self.states) - {r.state for r in self.rules}
        if unreachable:
            raise ValueError(f"{self.name}: no rule observes {sorted(s.value for s in unreachable)}")
        missing = set(self.states) - set(self.actions)
        if missing:
            raise ValueError(f"{self.name}: no action row for {sorted(s.value for s in missing)}")

    def own(self, state: Enum) -> bool:
        """Whether ``state`` is one of this machine's own, not one of the machine it is past."""
        return isinstance(state, self.states)

    def observe(self, facts: F) -> Enum:
        for rule in self.rules:
            if rule.when is None or rule.when(facts):
                return rule.state
        if self.past is None:
            raise AssertionError("unreachable: the last rule is otherwise")
        return self.past.observe(self.hands(facts))

    def allowed(self, state: Enum) -> Mapping[str, Allowed]:
        return self.actions[state] if self.own(state) else self.past.allowed(state)

    def does(self, state: Enum, facts: F) -> tuple[str, ...]:
        """What this machine's code does to the subject of ``facts`` in ``state`` — its own, or one
        down its `past` chain (`[does]`, core.md § 7): the list of its own tasks its table gives that
        very state, each kept where its guard holds over ``facts``, the machine's own."""
        return tuple(t for t in self.done.get(state.value, ()) if t not in self.guards or self.guards[t](facts))

    def idle(self, state: Enum) -> bool:
        """Whether its table gives ``state`` an empty list: its code does nothing there, and refuses,
        naming the state (core.md § 7) — never a state whose tasks are all guarded off, where it does
        nothing and goes on."""
        return not self.done.get(state.value)

    def word(self, state: Enum) -> str | None:
        """The state's block word (web.md § 7.6); None for a machine whose subject is not drawn."""
        return self.shows.get(state) if self.own(state) else self.past.word(state)

    def next(self, state: Enum, facts: F) -> tuple[view.Action, ...]:
        """What the state allows the subject of ``facts``, each step once, in table order — for a
        state whose next steps are another subject's (`[next_from.<state>]`), that subject's, as
        this machine observes the facts the binding hands by its name."""
        if not self.own(state):
            return self.past.next(state, self.hands(facts))
        if state in self.next_from:
            other = self.subjects[self.next_from[state]](facts)
            return self.next(self.observe(other), other) if other is not None else ()
        steps = (a.next(facts) for a in self.actions[state].values())
        return tuple({s.command: s for s in steps if s is not None}.values())

    def require(self, state: Enum, action: str, facts: F, name: str, label: str | None = None) -> Allowed:
        """The action, or refused with what the state allows the subject of ``facts``, named
        ``name`` — ``label`` how the refusal names it, where its name is not that."""
        allowed = self.allowed(state)
        if action not in allowed:
            raise Refused(f"{label or name} is {state.value}: `{action}` is not allowed", self.next(state, facts),
                          code="not-allowed", subject=name)
        return allowed[action]


# ------------------------------------------------------------------ a machine declared as data

OTHERWISE = "otherwise"   # the last rule's condition, and only its
NAME = re.compile(r"[a-z][a-z0-9_]*")
GRAMMAR = "names of facts joined by `and`, `or`, `not` and parentheses"


def condition_names(text: str) -> list[str]:
    """The fact names a condition uses, in order; a ValueError for a text outside the grammar —
    names joined by `and`, `or`, `not` and parentheses — read by the standard library's parser."""
    try:
        tree = ast.parse(text, mode="eval").body
    except SyntaxError:
        raise ValueError(f"{text!r} is no condition: {GRAMMAR}") from None
    names: list[str] = []

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.BoolOp):
            for value in node.values:
                walk(value)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            walk(node.operand)
        elif isinstance(node, ast.Name) and NAME.fullmatch(node.id):
            names.append(node.id)
        else:
            raise ValueError(f"{text!r} holds {ast.unparse(node)!r}, which is outside the grammar: {GRAMMAR}")

    walk(tree)
    return names


def _holds(node: ast.AST, facts: Any, predicates: Mapping[str, Callable[[Any], bool]]) -> bool:
    if isinstance(node, ast.BoolOp):
        test = all if isinstance(node.op, ast.And) else any
        return test(_holds(v, facts, predicates) for v in node.values)
    if isinstance(node, ast.UnaryOp):
        return not _holds(node.operand, facts, predicates)
    return bool(predicates[node.id](facts))


class RuleRow(Model):
    """One observation rule: the state it gives, and when."""

    state: str = Field(description="the state it gives, one of `states`")
    when: str = Field(description=f"the condition on the machine's named facts that gives it — {GRAMMAR}; "
                                  f"`{OTHERWISE}` for the last rule, and only for it")


class ActionRow(Model):
    """One action a state allows: an operation with its request, a shell line, or neither — nothing
    asked of a person, or, where it says so, its subject's own operation."""

    describe: str = Field(description="what a person reads on it")
    operation: str | None = Field(default=None, description="the registered operation it runs, by its name, "
                                                            "`env.install`")
    request: dict[str, Any] = Field(default_factory=dict, description="the operation's request values; a text that "
                                    "is one placeholder alone, `{name}`, is the value the subject gives it, and a key "
                                    "whose value the subject leaves unset is left out")
    shell: str | None = Field(default=None, description="a line a person types, for what is no operation; each "
                              "placeholder in it, `{name}`, is the value the subject gives")
    subject: bool = Field(default=False, description="with neither an operation nor a shell line: its operation is "
                                                     "its subject's own, which that subject's code offers — a launch "
                                                     "folder's maker's, read from `maker.json`; otherwise the request "
                                                     "is allowed, asks nothing of a person and is never a next step")
    fills: list[str] = Field(default_factory=list, description="with an operation: the fields of its request it asks "
                             "of the person before it runs, each its field's whole fill — one the request does not "
                             "require left unset at will")

    @model_validator(mode="after")
    def _one(self) -> "ActionRow":
        if self.operation is not None and self.shell is not None:
            raise ValueError("an action runs an operation or is a shell line, not both")
        if self.request and self.operation is None:
            raise ValueError("a request goes with the operation it fills")
        if self.subject and (self.operation is not None or self.shell is not None):
            raise ValueError("an action whose operation is its subject's own names no operation or shell line of its "
                             "own")
        if self.fills and self.operation is None:
            raise ValueError("the values an action asks go with the operation it fills")
        return self

    def placeholders(self) -> list[tuple[tuple, str]]:
        """Each placeholder in its request, with its location: a text that is a placeholder
        alone; a ValueError for a text that holds one beside other text."""
        found: list[tuple[tuple, str]] = []

        def walk(value: Any, at: tuple) -> None:
            if isinstance(value, dict):
                for k, v in value.items():
                    walk(v, (*at, k))
            elif isinstance(value, list):
                for i, v in enumerate(value):
                    walk(v, (*at, i))
            elif isinstance(value, str) and (held := parsed(value)):
                whole = held[0]
                if len(held) > 1 or whole.span != (0, len(value)) or whole.optional or whole.argument is not None:
                    raise ValueError(f"{value!r}: a request value is one placeholder alone, `{{name}}`, or holds none")
                found.append((at, whole.name))

        walk(self.request, ("request",))
        found += [(("shell",), held.name) for held in parsed(self.shell or "")]
        return found


class TaskRow(Model):
    """One of a machine's own tasks: what its code does to the subject, and where."""

    describe: str = Field(description="its sentence, said in a plan and an outcome")
    when: str | None = Field(default=None, description=f"its guard, the condition on the machine's named facts where "
                                                       f"it is done — {GRAMMAR}; none: wherever its state lists it")


class NextFrom(Model):
    """A state whose next steps are another subject's (core.md § 7, `[next_from.<state>]`)."""

    subject: str = Field(description="the subject whose next steps they are, by the name the machine's binding hands "
                                     "it — a waiting stage's: the stage it waits on")


class StateTable(Model):
    """`femkit/data/states/<machine>.toml`: one state machine, a closed table (core.md § 7). Its
    validation context may hold `predicates`, the fact names its domain gives, `values`, the
    names a request may take from the subject, `reads`, the states its domain's code reads by
    name — of its own, or of the machine it is past — `acts`, the actions its code reads by name,
    `tasks`, the tasks its code does by name, `drawn`, whether the page draws its subject as a
    block, `subjects`, the other subjects its binding hands by name, and `operations`, each
    registered operation's request model by its name: each, when given, is checked."""

    past: str | None = Field(default=None, description="another machine, by its file's stem: where none of the rules "
                                                       "holds, the subject is in that machine's state, observed over "
                                                       "the facts its domain's code hands it, with that machine's "
                                                       "actions and words; none: the last rule is the otherwise")
    states: dict[str, str] = Field(min_length=1, description="each state, in order, with the sentence saying when "
                                                             "it is observed")
    rules: list[RuleRow] = Field(min_length=1, description="the observation rules, in order: the first that holds "
                                                           "gives the state; the last is the otherwise, unless the "
                                                           "machine is past another")
    shows: dict[str, view.Shows] | None = Field(default=None, description="for a machine whose subject the page draws "
                                                "as a block, each state's block word; none for any other",
                                                json_schema_extra={"doc": "web.md § 7.6"})
    actions: dict[str, dict[str, ActionRow]] = Field(description="for each state, each action it allows by its name; "
                                                                 "an empty table: none")
    tasks: dict[str, TaskRow] | None = Field(
        default=None, description="its own tasks, each with its sentence — what its code does to the subject, said in "
                                  "a plan and an outcome; no state's action, never a next step — and its guard")
    does: dict[str, list[str]] | None = Field(
        default=None, description="for a machine with tasks: each of its states and of the tables down its "
                                  "`past` chain, every one named, with its own tasks its code does there — an empty "
                                  "list where it does none, and its code refuses, naming the state")
    next_from: dict[str, NextFrom] | None = Field(
        default=None, description="each state whose next steps are another subject's, by the name the binding hands "
                                  "it, in place of its own actions")

    @model_validator(mode="after")
    def _closed_and_total(self, info: ValidationInfo) -> "StateTable":
        context = info.context or {}
        problems: list[tuple[tuple, str]] = []
        problems += [(("states", s), f"{s!r} is no state's name: lowercase letters, digits and `_`")
                     for s in self.states if not NAME.fullmatch(s)]
        if self.past is None:
            problems += [(("states",), f"femkit's code reads the state {s!r}, which this table does not declare")
                         for s in sorted(context.get("reads", ())) if s not in self.states]
        last = len(self.rules) - 1
        for i, rule in enumerate(self.rules):
            at = ("rules", i)
            if rule.state not in self.states:
                problems.append(((*at, "state"), f"{rule.state!r} is none of the states"))
            if rule.when == OTHERWISE:
                if self.past is not None:
                    problems.append(((*at, "when"), f"a machine past {self.past} has no `{OTHERWISE}`: where no rule "
                                                    f"holds, the subject is in {self.past}'s state"))
                elif i != last:
                    problems.append(((*at, "when"), f"`{OTHERWISE}` is the last rule's alone"))
                continue
            if i == last and self.past is None:
                problems.append(((*at, "when"), f"the last rule is `{OTHERWISE}`, so no observation falls through — "
                                                "or the machine is past another, `past`"))
            try:
                used = condition_names(rule.when)
            except ValueError as exc:
                problems.append(((*at, "when"), str(exc)))
                continue
            known = context.get("predicates")
            problems += [((*at, "when"), f"{name!r} is no fact this machine's domain names "
                                         f"(it names {', '.join(sorted(known)) or 'none'})")
                         for name in used if known is not None and name not in known]
        observed = {r.state for r in self.rules}
        problems += [(("states", s), "no rule gives it") for s in self.states if s not in observed]
        problems += [(("actions", s), "every state has its row of actions, an empty table for none")
                     for s in self.states if s not in self.actions]
        problems += [(("actions", s), f"{s!r} is none of the states") for s in self.actions if s not in self.states]
        for state, row in self.actions.items():
            for name, action in row.items():
                problems += _action_problems(("actions", state, name), action, context)
        if self.does is not None and not self.tasks:
            problems.append((("does",), "a machine with no tasks of its own does nothing in a state: `[does]` goes "
                                        "with `[tasks]`"))
        if self.tasks and self.does is None:
            problems.append((("does",), "its code does tasks of its own: what it does in each state — its own, and "
                                        "each of the tables down its `past` chain — is named, an empty list where it "
                                        "does none"))
        declared = {name for row in self.actions.values() for name in row}
        own = set(self.tasks or {})
        problems += [(("does", state), f"{task!r} is none of this table's own tasks (it has "
                                       f"{', '.join(sorted(own)) or 'none'}): what its code does is its own tasks, "
                                       "`[tasks]`")
                     for state, done in (self.does or {}).items() for task in done if task not in own]
        if self.past is None and self.does is not None:
            problems += [(("does", state), f"{state!r} is none of the states") for state in self.does
                         if state not in self.states]
            problems += [(("does",), f"{state!r} is not named: what is done in each state is said, an empty list "
                                     "where nothing is") for state in self.states if state not in self.does]
        for task, row in (self.tasks or {}).items():
            if row.when is None:
                continue
            try:
                used = condition_names(row.when)
            except ValueError as exc:
                problems.append((("tasks", task, "when"), str(exc)))
                continue
            known = context.get("predicates")
            problems += [(("tasks", task, "when"), f"{name!r} is no fact this machine's domain names "
                                                   f"(it names {', '.join(sorted(known)) or 'none'})")
                         for name in used if known is not None and name not in known]
        subjects = context.get("subjects")
        for state, held in (self.next_from or {}).items():
            if state not in self.states:
                problems.append((("next_from", state), f"{state!r} is none of the states"))
            elif self.actions.get(state):
                problems.append((("actions", state), f"{state!r} takes its next steps from {held.subject}, in place "
                                                     "of actions of its own"))
            if subjects is not None and held.subject not in subjects:
                problems.append((("next_from", state, "subject"), f"{held.subject!r} is no subject this machine's "
                                 f"code hands (it hands {', '.join(sorted(subjects)) or 'none'})"))
        problems += [(("actions",), f"femkit's code reads the action {a!r}, which no state of this table declares")
                     for a in sorted(context.get("acts", ())) if a not in declared]
        problems += [(("tasks",), f"femkit's code does the task {t!r}, which this table's `[tasks]` does not declare")
                     for t in sorted(context.get("tasks", ())) if t not in own]
        problems += _shows_problems(self, context.get("drawn"))
        refuse("StateTable", problems)
        return self


def _shows_problems(table: StateTable, drawn: bool | None) -> list[tuple[tuple, str]]:
    """The words of a table's states (core.md § 7): for a subject drawn as a block, one word of
    the vocabulary's list for every state; for one not drawn, none — each where ``drawn`` says
    which; each word's state one of the table's."""
    if drawn is False and table.shows is not None:
        return [(("shows",), "the page draws no block of this machine's subject, so its states have no words")]
    if drawn and table.shows is None:
        return [(("shows",), "the page draws this machine's subject as a block: each state has its word")]
    shows = table.shows or {}
    return [(("shows",), f"{s!r} has no word: each state of a subject drawn as a block has one")
            for s in table.states if drawn and s not in shows] + \
        [(("shows", s), f"{s!r} is none of the states") for s in shows if s not in table.states]


def _action_problems(at: tuple, action: ActionRow, context: dict) -> list[tuple[tuple, str]]:
    """An action's placeholders against the values the subject gives, and its operation and
    request against the registered operations — each when the context names them."""
    problems: list[tuple[tuple, str]] = []
    try:
        held = action.placeholders()
    except ValueError as exc:
        return [((*at, "request"), str(exc))]
    values = context.get("values")
    problems += [((*at, *where), f"{{{name}}} is no value the subject gives (it gives "
                                 f"{', '.join('{%s}' % v for v in sorted(values))})")
                 for where, name in held if values is not None and name not in values]
    operations = context.get("operations")
    if operations is not None and action.operation is not None:
        request = operations.get(action.operation)
        if request is None:
            problems.append(((*at, "operation"), f"{action.operation!r} is no registered operation"))
        else:
            problems += [((*at, "request", key), f"{action.operation}'s request has no field {key!r}")
                         for key in action.request if key not in request.model_fields]
            problems += [((*at, "fills"), f"{action.operation}'s request has no field {key!r} to ask")
                         for key in action.fills if key not in request.model_fields]
    return problems


@dataclass(frozen=True)
class Binding(Generic[F]):
    """What code gives a machine declared as data (core.md § 7): its name — its file's stem —
    each predicate over its facts by the name a condition uses; each value a request takes from
    the subject, read from its facts; for a field a row asks of the person, the names it may take
    for the subject, read from its facts, where narrower than its declaration — a study's prep
    asking the engine of those that can solve it — None where the facts narrow nothing (`choices`);
    the states and the actions code reads by name,
    `m.states.ready`, wherever it reads them, and the tasks it does by name — a table lacking one
    is refused when it loads, never met first by the code; whether the page draws its subject as a
    block, so its table gives each state a word; for a machine past another, the facts it hands that
    machine; and each other subject it hands by name, whose facts a state's next steps may be
    read from (`[next_from.<state>]`), as this machine observes them.
    Each is known here as it is made, so `schema check` loads every machine bound (`bindings`),
    and a machine past another finds that machine's binding."""

    machine: str
    predicates: Mapping[str, Callable[[F], bool]]
    values: Mapping[str, Callable[[F], Any]] = field(default_factory=dict)
    choices: Mapping[str, Callable[[F], Sequence[str] | None]] = field(default_factory=dict)
    reads: frozenset[str] = frozenset()
    acts: frozenset[str] = frozenset()
    tasks: frozenset[str] = frozenset()
    drawn: bool = False
    hands: Callable[[F], Any] | None = None
    subjects: Mapping[str, Callable[[F], Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _BINDINGS[self.machine] = self


_BINDINGS: dict[str, Binding] = {}


def bindings() -> list[Binding]:
    """Every machine's binding made so far, the last of each name: what `schema check` loads each
    table bound to (core.md § 7)."""
    return list(_BINDINGS.values())


def _filled(template: Any, values: Mapping[str, Any]) -> Any:
    """A request's template with each placeholder replaced by its value; a key whose value is
    None is left out."""
    if isinstance(template, dict):
        filled = {k: _filled(v, values) for k, v in template.items()}
        return {k: v for k, v in filled.items() if v is not None}
    if isinstance(template, list):
        return [_filled(v, values) for v in template]
    held = parsed(template) if isinstance(template, str) else []
    if len(held) == 1 and held[0].span == (0, len(template)):
        return values[held[0].name]
    return template


def load(path: Path, binding: Binding[F], _within: tuple[str, ...] = ()) -> Machine[F, Enum]:
    """The machine `path` declares, bound to the predicates, values and facts ``binding`` gives:
    the one loader (core.md § 7). Refused, a `DefinitionError` at each key path, when a state is
    unreachable, the otherwise is not the last rule alone — or is there beside `past` — a state
    has no action row, a condition leaves the grammar or names a fact the binding does not, a
    request names a value the subject does not give, an action names an operation no verb
    declares or a field its request lacks, a state, an action or a task the binding's code reads is
    not declared, a subject drawn as a block lacks a state's word or one not drawn has words, a
    task's guard leaves the grammar or names a fact the binding does not, `[does]` names other than
    every state of its own and of the tables down its `past` chain — or the chain holds a state's
    name twice — or a task its `[tasks]` lacks, `[next_from]` names a state it lacks, one with
    actions of its own or a subject the binding hands none by, or the machine it is past — its file
    beside this one — does not load bound to its own binding, is past this one, or is handed no
    facts."""
    verbs = {v.name: v for v in view.verbs()}
    table = load_toml(path, StateTable, {"predicates": frozenset(binding.predicates),
                                         "values": frozenset(binding.values), "reads": binding.reads,
                                         "acts": binding.acts, "tasks": binding.tasks, "drawn": binding.drawn,
                                         "subjects": frozenset(binding.subjects),
                                         "operations": {name: v.request for name, v in verbs.items()}})
    past = _past(path, table, binding, _within)
    unread = sorted(set(binding.reads) - set(table.states) - (set(past.states) if past else set()))
    if past is not None and unread:   # a state the code reads: its own, or the machine's it is past
        raise DefinitionError(path, [("states", f"femkit's code reads the state {s!r}, which neither this table nor "
                                                f"{table.past}'s declares") for s in unread])
    if past is not None and table.does is not None:   # every state of its own and down its `past` chain, and none else
        chain = [list(table.states), *_chain_states(past)]
        every = [state for names in chain for state in names]
        lacking = [("does", f"{state!r} is a state of two tables of its `past` chain: `[does]` cannot tell which it "
                            "names") for state in sorted({s for s in every if every.count(s) > 1})]
        lacking += [(key_path(("does", state)), f"{state!r} is no state of its own, nor of {table.past}'s or a table "
                                                f"it is past (they have {', '.join(sorted(every))})")
                    for state in table.does if state not in every]
        lacking += [("does", f"{state!r} is not named: what is done in each state, its own and each of "
                             f"{table.past}'s and of each table it is past, is said, an empty list where nothing is")
                    for state in sorted(set(every) - set(table.does))]
        if lacking:
            raise DefinitionError(path, lacking)
    states = Enum(binding.machine, {s: s for s in table.states}, type=str)

    def when(text: str) -> Callable[[F], bool]:
        tree = ast.parse(text, mode="eval").body
        return lambda facts: _holds(tree, facts, binding.predicates)

    def values(row: ActionRow) -> Callable[[Any], dict[str, Any]]:
        return lambda facts: _filled(row.request, {k: give(facts) for k, give in binding.values.items()})

    rules = tuple(Rule(table.states[r.state], states(r.state), None if r.when == OTHERWISE else when(r.when))
                  for r in table.rules)
    def given(facts: Any) -> dict[str, Any]:
        return {k: give(facts) for k, give in binding.values.items()}

    actions = {states(state): {name: Allowed(a.describe, verbs[a.operation] if a.operation else None, values(a),
                                             a.shell, a.subject, tuple(a.fills),
                                             {f: binding.choices[f] for f in a.fills if f in binding.choices}, given)
                               for name, a in row.items()}
               for state, row in table.actions.items()}
    return Machine(binding.machine, states, rules, actions, {states(s): w for s, w in (table.shows or {}).items()},
                   past, binding.hands if past is not None else None,
                   {state: tuple(done) for state, done in (table.does or {}).items()},
                   {task: row.describe for task, row in (table.tasks or {}).items()},
                   {task: when(row.when) for task, row in (table.tasks or {}).items() if row.when is not None},
                   {states(s): held.subject for s, held in (table.next_from or {}).items()}, dict(binding.subjects))


def _chain_states(m: Machine | None) -> list[list[str]]:
    """The states of the machine ``m`` and of each machine down its `past` chain, by their names,
    one list for each table."""
    found: list[list[str]] = []
    while m is not None:
        found.append([s.value for s in m.states])
        m = m.past
    return found


def _past(path: Path, table: StateTable, binding: Binding, within: tuple[str, ...]) -> Machine | None:
    """The machine ``table`` is past, loaded from its file beside ``path`` bound to its own binding;
    None for a table past none. Refused at `past` when the binding hands facts to none, or the
    table names one its binding hands none; when it names no machine of femkit's, one that does
    not load, or one past this one."""
    if table.past is None:
        if binding.hands is not None:
            raise DefinitionError(path, [("past", f"femkit's code hands {binding.machine}'s facts to a machine it is "
                                                  "past, and this table names none")])
        return None
    if binding.hands is None:
        raise DefinitionError(path, [("past", f"femkit's code hands {table.past} no facts, so {binding.machine} is "
                                              "past no machine")])
    if table.past == binding.machine or table.past in within:
        raise DefinitionError(path, [("past", f"{table.past} is past {binding.machine} itself: one machine is past "
                                              "the other, never both")])
    other = _BINDINGS.get(table.past)
    if other is None or not path.with_name(f"{table.past}.toml").is_file():
        raise DefinitionError(path, [("past", f"{table.past!r} is no machine of femkit's")])
    try:
        return load(path.with_name(f"{table.past}.toml"), other, (*within, binding.machine))
    except DefinitionError as exc:
        raise DefinitionError(path, [("past", f"{table.past} does not load: {exc.summary()}")]) from None
