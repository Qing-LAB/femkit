"""The part schemas (projects.md § 6): the layout names each part kind's schema by a key; the
package that owns the schema declares it, and the registry registers it here when femkit starts
(api.md § 6), so the door, a lower layer, imports no package above it. A test registers its own,
and takes them back."""

from __future__ import annotations

from femkit.core.schema import Model

_REGISTERED: dict[str, type[Model]] = {}


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
