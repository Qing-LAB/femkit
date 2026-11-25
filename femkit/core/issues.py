"""Findings a person should act on (core.md § 10)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

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
