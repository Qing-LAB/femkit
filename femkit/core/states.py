"""The state-machine primitive (core.md § 7, framework.md § 3).

A machine is one closed table: an enumeration of states, an ordered list of
observation rules whose last is ``otherwise`` (so no observation falls
through), and the actions each state allows. State is computed from facts
every time it is asked; it is never stored.

A machine is declared as data, `femkit/data/states/<machine>.toml` (its schema `StateTable`):
its states, its rules as conditions over named facts, its actions. Code gives it only what
code must: each named predicate over the facts its domain's one function gathers, and the
values a request takes from the subject (`Binding`); `load` reads the file and binds it, the
one loader; every machine femkit has is declared so (`femkit/data/states/`).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generic, Mapping, TypeVar

from pydantic import Field, ValidationInfo, model_validator

from femkit.core import view
from femkit.core.errors import Refused
from femkit.core.schema import PLACEHOLDER, Model, load_toml, refuse

F = TypeVar("F")
S = TypeVar("S", bound=Enum)


@dataclass(frozen=True)
class Rule(Generic[F, S]):
    """``when`` is None for the closing ``otherwise`` rule."""

    describe: str
    state: S
    when: Callable[[F], bool] | None = None


def _nothing(name: str) -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class Action:
    """What a state allows: the verb that does it and its request's values for the subject the
    machine describes; or a shell line that is no operation; neither: allowed, with nothing to do."""

    describe: str
    verb: view.Verb | None = None
    values: Callable[[str], dict[str, Any]] = _nothing
    shell: str | None = None

    def next(self, name: str) -> view.Action | None:
        """The next step it is for ``name``, as every surface shows one."""
        if self.shell is not None:
            return view.shell(self.shell)
        if self.verb is None:
            return None
        return view.command(self.verb, label=self.describe, **self.values(name))


@dataclass(frozen=True)
class Machine(Generic[F, S]):
    name: str
    states: type[S]
    rules: tuple[Rule[F, S], ...]
    actions: Mapping[S, Mapping[str, Action]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rules or self.rules[-1].when is not None:
            raise ValueError(f"{self.name}: the last observation rule must be `otherwise`")
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

    def observe(self, facts: F) -> S:
        for rule in self.rules:
            if rule.when is None or rule.when(facts):
                return rule.state
        raise AssertionError("unreachable: the last rule is otherwise")

    def allowed(self, state: S) -> Mapping[str, Action]:
        return self.actions[state]

    def next(self, state: S, name: str) -> tuple[view.Action, ...]:
        """What the state allows ``name``, each step once, in table order."""
        steps = (a.next(name) for a in self.actions[state].values())
        return tuple({s.command: s for s in steps if s is not None}.values())

    def require(self, state: S, action: str, name: str, label: str | None = None) -> Action:
        """The action, or refused with what the state allows ``name``; ``label`` is how the
        refusal names it, where its name is not that."""
        allowed = self.actions[state]
        if action not in allowed:
            raise Refused(f"{label or name} is {state.value}: `{action}` is not allowed", self.next(state, name),
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
    """One action a state allows: an operation with its request, a shell line, or nothing to do."""

    describe: str = Field(description="what a person reads on it")
    operation: str | None = Field(default=None, description="the registered operation it runs, by its name, "
                                                            "`env.install`")
    request: dict[str, Any] = Field(default_factory=dict, description="the operation's request values; a text that "
                                    "is one placeholder alone, `{name}`, is the value the subject gives it, and a key "
                                    "whose value the subject leaves unset is left out")
    shell: str | None = Field(default=None, description="a line a person types, for what is no operation")

    @model_validator(mode="after")
    def _one(self) -> "ActionRow":
        if self.operation is not None and self.shell is not None:
            raise ValueError("an action runs an operation or is a shell line, not both")
        if self.request and self.operation is None:
            raise ValueError("a request goes with the operation it fills")
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
            elif isinstance(value, str) and PLACEHOLDER.search(value):
                whole = PLACEHOLDER.fullmatch(value)
                if whole is None or whole.group(2) is not None:
                    raise ValueError(f"{value!r}: a request value is one placeholder alone, `{{name}}`, or holds none")
                found.append((at, whole.group(1)))

        walk(self.request, ("request",))
        return found


class StateTable(Model):
    """`femkit/data/states/<machine>.toml`: one state machine, a closed table (core.md § 7). Its
    validation context may hold `predicates`, the fact names its domain gives, `values`, the
    names a request may take from the subject, `reads`, the states its domain's code reads by
    name, and `operations`, each registered operation's request model by its name: each, when
    given, is checked."""

    states: dict[str, str] = Field(min_length=1, description="each state, in order, with the sentence saying when "
                                                             "it is observed")
    rules: list[RuleRow] = Field(min_length=1, description="the observation rules, in order: the first that holds "
                                                           "gives the state; the last is the otherwise")
    actions: dict[str, dict[str, ActionRow]] = Field(description="for each state, each action it allows by its name; "
                                                                 "an empty table: none")

    @model_validator(mode="after")
    def _closed_and_total(self, info: ValidationInfo) -> "StateTable":
        context = info.context or {}
        problems: list[tuple[tuple, str]] = []
        problems += [(("states", s), f"{s!r} is no state's name: lowercase letters, digits and `_`")
                     for s in self.states if not NAME.fullmatch(s)]
        problems += [(("states",), f"femkit's code reads the state {s!r}, which this table does not declare")
                     for s in sorted(context.get("reads", ())) if s not in self.states]
        last = len(self.rules) - 1
        for i, rule in enumerate(self.rules):
            at = ("rules", i)
            if rule.state not in self.states:
                problems.append(((*at, "state"), f"{rule.state!r} is none of the states"))
            if rule.when == OTHERWISE:
                if i != last:
                    problems.append(((*at, "when"), f"`{OTHERWISE}` is the last rule's alone"))
                continue
            if i == last:
                problems.append(((*at, "when"), f"the last rule is `{OTHERWISE}`, so no observation falls through"))
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
        refuse("StateTable", problems)
        return self


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
    return problems


def _named(name: str) -> str:
    return name


@dataclass(frozen=True)
class Binding(Generic[F]):
    """What code gives a machine declared as data (core.md § 7): its name — its file's stem —
    each predicate over its facts by the name a condition uses, each value a request takes from
    the subject's name — by default `name`, the name itself — and the states code reads by name,
    `m.states.ready`, wherever it reads them: a table lacking one is refused when it loads, never
    met first by the code. Each is known here as it is made, so `schema check` loads every
    machine bound (`bindings`)."""

    machine: str
    predicates: Mapping[str, Callable[[F], bool]]
    values: Mapping[str, Callable[[str], Any]] = field(default_factory=lambda: {"name": _named})
    reads: frozenset[str] = frozenset()

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
    if isinstance(template, str) and (whole := PLACEHOLDER.fullmatch(template)):
        return values[whole.group(1)]
    return template


def load(path: Path, binding: Binding[F]) -> Machine[F, Enum]:
    """The machine `path` declares, bound to the predicates and values ``binding`` names: the one
    loader (core.md § 7). Refused, a `DefinitionError` at each key path, when a state is
    unreachable, the otherwise is not the last rule alone, a state has no action row, a condition
    leaves the grammar or names a fact the binding does not, a request names a value the subject
    does not give, an action names an operation no verb declares or a field its request lacks, or
    a state the binding's code reads is not declared."""
    verbs = {v.name: v for v in view.verbs()}
    table = load_toml(path, StateTable, {"predicates": frozenset(binding.predicates),
                                         "values": frozenset(binding.values), "reads": binding.reads,
                                         "operations": {name: v.request for name, v in verbs.items()}})
    states = Enum(binding.machine, {s: s for s in table.states}, type=str)

    def when(text: str) -> Callable[[F], bool]:
        tree = ast.parse(text, mode="eval").body
        return lambda facts: _holds(tree, facts, binding.predicates)

    def values(row: ActionRow) -> Callable[[str], dict[str, Any]]:
        return lambda name: _filled(row.request, {k: give(name) for k, give in binding.values.items()})

    rules = tuple(Rule(table.states[r.state], states(r.state), None if r.when == OTHERWISE else when(r.when))
                  for r in table.rules)
    actions = {states(state): {name: Action(a.describe, verbs[a.operation] if a.operation else None, values(a),
                                            a.shell)
                               for name, a in row.items()}
               for state, row in table.actions.items()}
    return Machine(binding.machine, states, rules, actions)
