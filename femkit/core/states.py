"""The state-machine primitive (framework.md § 3).

A machine is one closed table: an enumeration of states, an ordered list of
observation rules whose last is ``otherwise`` (so no observation falls
through), and the actions each state allows. State is computed from facts
every time it is asked; it is never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Generic, Mapping, TypeVar

from femkit.core.errors import Refused

F = TypeVar("F")
S = TypeVar("S", bound=Enum)


@dataclass(frozen=True)
class Rule(Generic[F, S]):
    """``when`` is None for the closing ``otherwise`` rule."""

    describe: str
    state: S
    when: Callable[[F], bool] | None = None


@dataclass(frozen=True)
class Action:
    describe: str
    command: str  # the command a person types, shown as a "next" line; `{name}` is what the machine describes;
    #               empty for an allowed action that has nothing to do

    def typed(self, name: str) -> str:
        return self.command.replace("{name}", name)


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

    def next_commands(self, state: S, name: str) -> tuple[str, ...]:
        """The commands the state allows, each once, in table order."""
        return tuple(dict.fromkeys(a.typed(name) for a in self.actions[state].values() if a.command))

    def require(self, state: S, action: str, name: str) -> Action:
        allowed = self.actions[state]
        if action not in allowed:
            raise Refused(f"{name} is {state.value}: `{action}` is not allowed",
                          self.next_commands(state, name))
        return allowed[action]
