"""The schema base and the one loader (definitions.md § 2).

Every declared file — shipped definition, user configuration, machine record —
is a ``Model``. The model is the only place a field, its default, its allowed
values and its description are defined; the loader turns any failure into one
``DefinitionError`` naming the file, the key path and the reason.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from femkit.core.errors import Refusal

M = TypeVar("M", bound="Model")


class Model(BaseModel):
    """Unknown keys are refused; a loaded value never changes."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DefinitionError(Refusal):
    """A declared file that does not load: every problem, each with its key path."""

    def __init__(self, file: Path | str, problems: Iterable[tuple[str, str]], next: tuple[str, ...] = ()):
        self.file = str(file)
        self.problems = list(problems)
        lines = [f"{self.file}: {path or '<file>'}: {reason}" for path, reason in self.problems]
        super().__init__("\n".join(lines), next)

    def summary(self) -> str:
        """Every problem on one line, each at its key path: for a row or a listing that names the file apart."""
        return "; ".join(f"{path or '<file>'}: {reason}" for path, reason in self.problems)


def refuse(model: str, problems: list[tuple[tuple, str]]) -> None:
    """Raise every cross-reference problem at once, each at its own key path.

    For a model validator (core.md § 2): ``problems`` are ``(location, reason)``
    with the location relative to the model, e.g. ``("builds", 1, "source")``.
    """
    if problems:
        raise ValidationError.from_exception_data(model, [
            InitErrorDetails(type=PydanticCustomError("reference", "{reason}", {"reason": reason}),
                             loc=loc, input=None)
            for loc, reason in problems
        ])


def _key_path(loc: tuple) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def validate(model: type[M], data: Any, file: Path | str, context: dict | None = None) -> M:
    try:
        return model.model_validate(data, context=context)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            # pydantic adds the validator kind (function-after, …) to a location; drop it
            loc = tuple(p for p in err["loc"] if not (isinstance(p, str) and p.startswith("function-")))
            problems.append((_key_path(loc), err["msg"].removeprefix("Value error, ")))
        raise DefinitionError(file, problems) from None


def load_toml(path: Path, model: type[M], context: dict | None = None) -> M:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise DefinitionError(path, [("", f"not TOML: {exc}")]) from None
    return validate(model, data, path, context)


# ---------------------------------------------------------------- placeholders
#
# One grammar everywhere (definitions.md § 4.3): `{name}` or `{name:argument}`.
# Which names a field accepts is declared by that field, never guessed.

PLACEHOLDER = re.compile(r"\{([^{}:]*)(?::([^{}]*))?\}")


def placeholders(text: str) -> list[tuple[str, str | None]]:
    return [(m.group(1), m.group(2)) for m in PLACEHOLDER.finditer(text)]


def check_placeholders(text: str, allowed: frozenset[str]) -> str:
    """Return ``text`` when every placeholder in it is one ``allowed`` names."""
    for name, _arg in placeholders(text):
        if name not in allowed:
            names = ", ".join("{%s}" % n for n in sorted(allowed)) or "none"
            raise ValueError(f"placeholder {{{name}}} is not allowed here (allowed: {names})")
    return text


def render(text: str, values: dict[str, str]) -> str:
    """Substitute placeholders; ``values`` keys are `name` or `name:argument`."""

    def one(m: re.Match) -> str:
        key = m.group(1) if m.group(2) is None else f"{m.group(1)}:{m.group(2)}"
        return values[key]

    return PLACEHOLDER.sub(one, text)
