"""The one list of where operations live (api.md § 6)."""

from __future__ import annotations

import importlib

from femkit.core.operations import Operation

DOMAINS = (
    "femkit.config.operations",
    "femkit.envs.operations",
    "femkit.jobs.operations",
    "femkit.jobs.setup",
    "femkit.reference",
    "femkit.server.operations",
    "femkit.server.build",
)


def operations(modules: tuple[str, ...] = DOMAINS) -> dict[str, Operation]:
    """Every declared operation by name; imports the modules only when called."""
    found: dict[str, Operation] = {}
    for module_name in modules:
        module = importlib.import_module(module_name)
        for value in vars(module).values():
            if isinstance(value, Operation):
                if value.name in found and found[value.name] is not value:
                    raise RuntimeError(f"operation {value.name!r} is declared twice")
                found[value.name] = value
    return dict(sorted(found.items()))
