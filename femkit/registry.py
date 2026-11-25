"""The one list of where operations live, and of where part schemas live (api.md § 6)."""

from __future__ import annotations

import importlib

from femkit.core import view
from femkit.core.operations import Operation
from femkit.core.schema import Model
from femkit.projects import schemas

DOMAINS = (
    "femkit.config.operations",
    "femkit.envs.operations",
    "femkit.jobs.operations",
    "femkit.jobs.setup",
    "femkit.reference",
    "femkit.models.operations",
    "femkit.server.operations",
    "femkit.server.build",
)

#: The modules that own part schemas (projects.md § 6), each declaring `PART_SCHEMAS`: the key a
#: layout names a schema by, and its model. None yet: step D adds the parts' packages.
PARTS: tuple[str, ...] = ()


def part_schemas() -> dict[str, type[Model]]:
    """Every part schema the modules of ``PARTS`` declare, by its key, each registered with the door
    (projects.md § 6), which refuses one key with two models; imports them only when called."""
    declared: dict[str, type[Model]] = {}
    for module_name in PARTS:
        for key, model in importlib.import_module(module_name).PART_SCHEMAS.items():
            schemas.register(key, model)
            declared[key] = model
    return declared


def operations() -> dict[str, Operation]:
    """Every declared operation by name; imports the domains' modules only when called. femkit's
    start (api.md § 6): every part schema is registered with the door first, and a verb of
    femkit's that names no registered operation, or another's request, is refused."""
    part_schemas()
    found: dict[str, Operation] = {}
    for module_name in DOMAINS:
        module = importlib.import_module(module_name)
        for value in vars(module).values():
            if isinstance(value, Operation):
                if value.name in found and found[value.name] is not value:
                    raise RuntimeError(f"operation {value.name!r} is declared twice")
                found[value.name] = value
    stray = sorted(f"{v.name} ({v.request.__name__})" for v in view.verbs()
                   if v.request.__module__.startswith("femkit.")       # a test's own operations are its own
                   and (v.name not in found or found[v.name].verb != v))
    if stray:
        raise RuntimeError(f"verbs naming no registered operation, or with another's request: {', '.join(stray)}")
    return dict(sorted(found.items()))
