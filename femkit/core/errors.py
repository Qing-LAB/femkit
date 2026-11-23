"""Refusals: refused before acting, exit 2 (core.md § 9).

Any exception that is not a ``Refusal`` is a defect or an unavailable system.
"""

from __future__ import annotations


class Refusal(Exception):
    """Refused before acting. ``next`` lists commands a person may run instead."""

    def __init__(self, message: str, next: tuple[str, ...] = ()):
        super().__init__(message)
        self.next = tuple(next)


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
