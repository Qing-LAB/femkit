"""Refusals: refused before acting, exit 2 (core.md § 9).

Any exception that is not a ``Refusal`` is a defect or an unavailable system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:  # core/view.py sits above this module: its type is named, never imported
    from femkit.core.view import Action


class Refusal(Exception):
    """Refused before acting. ``next`` holds what a person may do instead, each an `Action`
    (core/view.py) the surface renders: a command, or a button."""

    def __init__(self, message: str, next: Iterable[Action] = ()):
        super().__init__(message)
        self.next = tuple(next)
        from femkit.core.view import Action  # held at the door: a next step is never bare text
        if not all(isinstance(n, Action) for n in self.next):
            raise TypeError(f"a refusal's next steps are Actions, not {[type(n).__name__ for n in self.next]}")


class Refused(Refusal):
    """A state does not allow the action (core.md § 7)."""


class Busy(Refusal):
    """The subject's lock is held (core.md § 5)."""


class ConsentDeclined(Refusal):
    """The person said no, or there is no terminal and no --yes."""


class PlanStale(Refusal):
    """The state changed between plan and apply (api.md § 3)."""


class UsageError(Refusal):
    """A request that does not validate: bad usage."""
