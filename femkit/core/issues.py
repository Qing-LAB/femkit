"""Findings a person should act on (core.md § 10)."""

from __future__ import annotations

from typing import Literal

from femkit.core.schema import Model


class Issue(Model):
    """One finding: what it is about, what is wrong, and the commands allowed next."""

    severity: Literal["error", "warning", "info"]
    code: str
    subject: str
    message: str
    next: tuple[str, ...] = ()
