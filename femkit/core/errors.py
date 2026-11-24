"""Refusals: refused before acting, exit 2 (core.md § 9).

Any exception that is not a ``Refusal`` is a defect or an unavailable system.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:  # core/view.py sits above this module: its type is named, never imported
    from femkit.core.view import Action


class Refusal(Exception):
    """Refused before acting. Like a finding (core/issues.py), it carries a ``code`` that tells
    it apart from other refusals of its kind — a surface, a script or a test reads the code, never
    the wording — and the ``subject`` it is about; ``next`` holds what a person may do instead,
    each an `Action` (core/view.py) the surface renders: a command, or a button. Without a code
    of its own, a refusal's code is its kind's."""

    def __init__(self, message: str, next: Iterable[Action] = (), *, code: str | None = None,
                 subject: str | None = None):
        super().__init__(message)
        self.code = code or re.sub(r"(?<!^)(?=[A-Z])", "-", type(self).__name__).lower()  # PlanStale: plan-stale
        self.subject = subject
        self.next = tuple(next)
        if self.next:  # held at the door: a next step is never bare text; a refusal with none needs no vocabulary
            from femkit.core.view import Action
            if not all(isinstance(n, Action) for n in self.next):
                raise TypeError(f"a refusal's next steps are Actions, not {[type(n).__name__ for n in self.next]}")


class Refused(Refusal):
    """A state does not allow the action (core.md § 7) — making what exists already among them."""


class Unstated(Refusal):
    """Something the work needs is not stated, and femkit never guesses it (framework.md § 4): a
    setting, the package manager, a scheduler's kind or command."""


class Busy(Refusal):
    """The subject's lock is held (core.md § 5)."""


class ConsentDeclined(Refusal):
    """The person said no, or there is no terminal and no --yes."""


class PlanStale(Refusal):
    """The state changed between plan and apply (api.md § 3)."""


class UsageError(Refusal):
    """A request that does not validate: bad usage — naming what does not exist among it."""
