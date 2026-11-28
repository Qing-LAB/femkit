"""Findings a person should act on (core.md § 10)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from femkit.core.errors import Refusal
from femkit.core.schema import Model, matching
from femkit.core.view import Action

CODE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")   # kebab-case: what tests and programs match on


class Issue(Model):
    """One finding: what it is about, what is wrong, where the person opens it, what would be
    right, and what a person may do next."""

    severity: Literal["error", "warning", "info"] = Field(description="how much it matters")
    code: str = matching(CODE, description="which finding it is: what tests and programs match on, kebab-case")
    subject: str = Field(description="what it is about: an environment, a key, a file, an address")
    label: str | None = Field(default=None, description="what a person calls the subject, where its address is "
                                                        "not that")
    message: str = Field(description="one whole sentence for a person")
    file: str | None = Field(default=None, description="the file it is about, as the person opens it in their "
                                                       "editor: a project's, by its path from the project's folder")
    key: str | None = Field(default=None, description="the key in that file, its dotted path: `conditions.left.kind`")
    line: int | None = Field(default=None, ge=1, description="the line of that file, from 1, where its key stands: "
                                                             "every finding at a key, a TOML file's as a Python "
                                                             "file's, read from the file's own text")
    right: str | None = Field(default=None, description="the one value that would be right, as the file would "
                                                        "write it (TOML text)")
    choices: tuple[str, ...] = Field(default=(), description="the values that would be right, when more than one "
                                                             "would do, each as the file would write it (TOML text)")
    next: tuple[Action, ...] = Field(default=(), description="what would resolve it: operations that exist, never "
                                                             "an edit of a file the person wrote")

    @model_validator(mode="after")
    def _right_or_choices(self) -> "Issue":
        if self.right is not None and self.choices:
            raise ValueError("one value that would be right, or the choices among several — not both")
        return self

    @classmethod
    def of(cls, refusal: Refusal, severity: Literal["error", "warning", "info"], message: str | None = None) -> "Issue":
        """``refusal`` as a finding (core.md § 10): its code, its subject and its next steps kept —
        the one way a refusal becomes an issue, never by hand — its message its own unless one is
        given. A refusal names its subject (core.md § 9); one that names none is a defect here."""
        if refusal.subject is None:
            raise TypeError(f"the refusal {refusal.code!r} names no subject, so no finding can be made of it: every "
                            "refusal names its subject (core.md § 9)")
        return cls(severity=severity, code=refusal.code, subject=refusal.subject,
                   message=message if message is not None else str(refusal), next=refusal.next)
