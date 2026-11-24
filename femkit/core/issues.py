"""Findings a person should act on (core.md § 10)."""

from __future__ import annotations

from typing import Literal

from femkit.core.schema import Model
from femkit.core.view import Action


class Issue(Model):
    """One finding: what it is about, what is wrong, and what a person may do next."""

    severity: Literal["error", "warning", "info"]
    code: str
    subject: str
    label: str | None = None    # what a person calls the subject, where its address is not that
    message: str
    next: tuple[Action, ...] = ()
