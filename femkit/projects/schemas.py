"""The part schemas (projects.md § 6): the layout names each part kind's schema by a key; the
package that owns the schema declares it, and the registry registers it here when femkit starts
(api.md § 6), so the door, a lower layer, imports no package above it. A test registers its own,
and takes them back.

Every part schema is a `PartFile`: its first key, `schema`, states the shape its file is written
in (models.md § 2) — one field, here, which every part kind's package imports."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from femkit.core.schema import Model

_REGISTERED: dict[str, type[Model]] = {}


class PartFile(Model):
    """A part's file (models.md § 2): its first key, `schema`, the number of its part kind's
    shape."""

    schema_: Literal[1] = Field(alias="schema", description="the version of this file's format, which femkit raises "
                                "when it changes how files of this kind are written",
                                json_schema_extra={"doc": "models.md § 2"})


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
