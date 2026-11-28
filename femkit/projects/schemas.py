"""The part schemas (projects.md § 6): the layout names each part kind's schema by a key; the
package that owns the schema declares it, and the registry registers it here when femkit starts
(api.md § 6), so the door, a lower layer, imports no package above it. A test registers its own,
and takes them back.

Every part schema is a `PartFile`: its first key, `schema`, states the shape its file is written
in (models.md § 2) — one field, here, which every part kind's package imports; a kind whose shape
was raised declares the shape it reads and, for each shape after its first, what changed (`CHANGES`),
so a file stating an earlier shape is told what changed since, never only that it differs; a key
a kind no longer takes it may declare with what a file writing it is told (`WITHDRAWN`, core.md
§ 2)."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import Field, ValidationInfo, field_validator

from femkit.core.schema import Model, allowed

_REGISTERED: dict[str, type[Model]] = {}


class PartFile(Model):
    """A part's file (models.md § 2): its first key, `schema`, the number of its part kind's
    shape. A kind whose shape was raised states it, `schema_: Literal[<n>]`, and what changed in
    each shape after its first, `CHANGES`."""

    #: What changed in each shape after the first, by its number: said to a file of an earlier one.
    CHANGES: ClassVar[dict[int, str]] = {}

    schema_: Literal[1] = Field(alias="schema", description="the version of this file's format, which femkit raises "
                                "when it changes how files of this kind are written",
                                json_schema_extra={"doc": "models.md § 2"})

    @field_validator("schema_", mode="before")
    @classmethod
    def _shape(cls, value: Any, info: ValidationInfo) -> Any:
        """A file of an earlier shape is told the shape femkit reads and what changed since
        (models.md § 2); any other value is the field's own to refuse."""
        (shape,) = allowed(cls.model_fields["schema_"].annotation)
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value < shape:
            changed = "; ".join(cls.CHANGES[n] for n in range(value + 1, shape + 1) if n in cls.CHANGES)
            raise ValueError(f"this file is written in shape {value}, and femkit reads shape {shape}, "
                             f"`schema = {shape}`" + (f": since shape {value}, {changed}" if changed else ""))
        return value


def register(key: str, model: type[Model]) -> None:
    """``model`` is the schema the layout calls ``key``; one owner per key."""
    held = _REGISTERED.get(key)
    if held is not None and held is not model:
        raise TypeError(f"the part schema {key!r} is registered twice: {held.__name__} and {model.__name__}")
    _REGISTERED[key] = model


def unregister(key: str) -> None:
    _REGISTERED.pop(key, None)


def registered() -> dict[str, type[Model]]:
    return dict(_REGISTERED)


UNLOADABLE = "unloadable"           # the finding of a part whose own file does not load (projects.md § 6)
