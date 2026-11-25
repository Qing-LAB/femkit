"""The one mapping between a request's fields and a command's arguments (api.md § 4.1).

The command line builds its parameters by it, and an `Action` (core/view.py) is written as the
command a person types by it — so a next step, wherever it is made, is the command the adapter
would accept.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from femkit.core.schema import PLACEHOLDER, alternatives, field_extras, items_of

#: How a person runs femkit: the `femkit` command the activated control environment puts on the
#: path, in any folder (envs.md § 7). Every printed command starts with it (api.md § 4.4).
PROG = "femkit"

#: A request field's annotation that makes it a positional argument (api.md § 4.1).
ARGUMENT = {"cli": "argument"}


def unwrap(annotation: Any) -> tuple[Any, bool]:
    """(the type of one value, whether it takes several): a list's items, else the one
    alternative there is, else the annotation as it is."""
    items = items_of(annotation)
    if items is not None:
        return unwrap(items)[0], True
    options = alternatives(annotation)
    return (options[0] if len(options) == 1 else annotation), False


@dataclass(frozen=True)
class Spelling:
    """How one request field is written on the command line."""

    kind: Literal["argument", "flag", "option"]
    flag: str                     # `--name`; unused for an argument
    many: bool                    # an argument taking several values, or an option that repeats
    element: Any                  # the type of one value


def spelling(name: str, field: FieldInfo) -> Spelling:
    """The table of api.md § 4.1: an argument where the field says so, a flag for a boolean, an
    option otherwise; underscores become dashes, unless the field spells its option itself
    (`{"cli": "--from"}`), where its name cannot be the word."""
    element, many = unwrap(field.annotation)
    cli = field_extras(field).get("cli")
    flag = cli if isinstance(cli, str) and cli.startswith("--") else "--" + name.replace("_", "-")
    if cli == "argument":
        return Spelling("argument", flag, many, element)
    if element is bool:
        return Spelling("flag", flag, False, element)
    return Spelling("option", flag, many, element)


def word(value: Any) -> str:
    """One word of a command line, quoted for the shell only when it needs it; a placeholder
    (`{ranks}`) is part of the template, written as it is typed."""
    shown = str(value)
    bare = PLACEHOLDER.sub(lambda m: "x" if m.group(1).isidentifier() and m.group(2) is None else m.group(0), shown)
    return shown if shlex.quote(bare) == bare else shlex.quote(shown)


def words(operation: str, request: type[BaseModel], values: Mapping[str, Any],
          fills: Mapping[str, str] = {}) -> list[str]:
    """The command for ``operation`` with ``values``, as its words after `femkit`: the
    verb, each argument, each flag and option a value differs from its default for, and each
    value still to fill as its placeholder (``fills``: field → what stands in its place)."""
    out = operation.split(".")
    for name, field in request.model_fields.items():
        s = spelling(name, field)
        if name in fills:
            given = [fills[name]]
        else:
            value = values.get(name, field.default)
            if value is None or value is False or value == field.default:
                continue
            given = [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]
        if s.kind == "argument":
            out += given
        elif s.kind == "flag":
            out.append(s.flag)
        else:
            for v in given:
                out += [s.flag, v]
    return out


def typed(args: list[str]) -> str:
    """A femkit command as a person types it: `femkit ARGS`, each word quoted only when it
    needs it."""
    return " ".join([PROG, *(word(a) for a in args)])
