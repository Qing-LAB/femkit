"""The state-machine primitive (framework.md § 3).

A machine is one closed table: an enumeration of states, an ordered list of
observation rules whose last is ``otherwise`` (so no observation falls
through), and the actions each state allows. State is computed from facts
every time it is asked; it is never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generic, Mapping, TypeVar

from femkit.core import view
from femkit.core.errors import Refused

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
    """What a state allows: the verb that does it, and its request's values for the subject the
    machine describes. No verb: allowed, with nothing to do."""

    describe: str
    verb: view.Verb | None = None
    values: Callable[[str], dict[str, Any]] = _nothing

    def next(self, name: str) -> view.Action | None:
        """The next step it is for ``name``, as every surface shows one."""
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
