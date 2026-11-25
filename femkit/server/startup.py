"""What `serve start` and `serve restart` load before anything detaches or is signalled, beyond
the server's own checks (web.md § 4): each declared file the child loads before it serves. The
project layout, bound to the part schemas registered at femkit's start — what the child opens
every project with (projects.md § 6) — is this domain's own to name, as it lies below it; the
page's declaration (web.md § 8.1), which names every domain's operations, lives above it, so the
registry hands it here when femkit starts (api.md § 6), as it hands the part schemas to the
door, and this domain imports nothing above it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from femkit.core import view
from femkit.core.view import Action
from femkit.definitions.requests import SCHEMA_CHECK
from femkit.projects import layout as layouts


@dataclass(frozen=True)
class Load:
    """One declared file the child loads before it serves."""

    what: str                     # what a person calls it: "the page's declaration"
    code: str                     # the refusal's code when it does not load
    load: Callable[[], Any]       # loads it; a `DefinitionError`, naming the file, when it does not
    next: tuple[Action, ...]      # what a person may do instead


_LOADS: dict[str, Load] = {}


def register(load: Load) -> None:
    """``load`` is loaded before the server starts; registering one of its code again replaces it,
    so every start of femkit hands the current one."""
    _LOADS[load.code] = load


def registered() -> tuple[Load, ...]:
    """Every file loaded before the server starts, in order: the project layout first, as the
    page's declaration names its kinds."""
    layout = Load(what="the project layout", code="layout-does-not-load", load=layouts.load,
                  next=(view.command(SCHEMA_CHECK),))
    return (layout, *_LOADS.values())
