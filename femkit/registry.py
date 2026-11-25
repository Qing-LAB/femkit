"""The one list of where operations live, and of where part schemas and their checks live; what the
server loads before it starts, handed to it (api.md § 6)."""

from __future__ import annotations

import importlib

from femkit import page
from femkit.core import view
from femkit.core.operations import Operation
from femkit.core.schema import Model
from femkit.definitions.requests import SCHEMA_CHECK
from femkit.projects import checking, schemas
from femkit.server import startup

#: Each command group's one sentence, as `femkit --help` lists it (api.md § 6).
GROUPS = {
    "case": "the cases a study's expansion wrote, each with its study and point",
    "config": "this machine's settings, femkit's own",
    "env": "the engine environments: install, validate, list, clean, log",
    "job": "this machine's record and the jobs femkit runs",
    "project": "a project: start one from a template, check it, list them, see it as a graph",
    "schema": "femkit's own definitions and the reference pages written from them",
    "serve": "the web page's server: start, stop, status",
    "study": "a project's studies: list them, write their cases",
    "web": "the web page's bundle, built from its sources",
}

DOMAINS = (
    "femkit.config.operations",
    "femkit.envs.operations",
    "femkit.jobs.operations",
    "femkit.jobs.setup",
    "femkit.projects.operations",
    "femkit.reference",
    "femkit.models.operations",
    "femkit.server.operations",
    "femkit.server.build",
)

#: The modules that own part schemas or a part of one (projects.md § 6), each declaring
#: `PART_SCHEMAS`, the key a layout names a schema by and its model, and `PART_CHECKS`, the key of
#: each schema it checks and its check (projects/checking.py) — a component's assignment is the
#: materials package's, checked after the component's own.
PARTS: tuple[str, ...] = (
    "femkit.models.project",
    "femkit.materials.material",
    "femkit.geometry.component",
    "femkit.materials.assign",
    "femkit.models.physics",
    "femkit.geometry.recipe",
    "femkit.models.observables",
    "femkit.models.study",
)


def part_schemas() -> dict[str, type[Model]]:
    """Every part schema the modules of ``PARTS`` declare, by its key, each registered with the door
    (projects.md § 6), which refuses one key with two models; imports them only when called."""
    declared: dict[str, type[Model]] = {}
    for module_name in PARTS:
        for key, model in importlib.import_module(module_name).PART_SCHEMAS.items():
            schemas.register(key, model)
            declared[key] = model
    return declared


def part_checks() -> dict[str, tuple[checking.Check, ...]]:
    """Every check the modules of ``PARTS`` declare, by the key of the schema it checks, each
    registered with the check frame (projects/checking.py), in the order of ``PARTS``; a check of a
    schema no module of ``PARTS`` declares is refused, as a defect."""
    known = part_schemas()
    declared: dict[str, tuple[checking.Check, ...]] = {}
    for module_name in PARTS:
        for key, check in importlib.import_module(module_name).PART_CHECKS.items():
            if key not in known:
                raise RuntimeError(f"{module_name} checks the part schema {key!r}, which no module of PARTS declares")
            checking.register(key, check)
            declared[key] = (*declared.get(key, ()), check)
    return declared


def operations() -> dict[str, Operation]:
    """Every declared operation by name; imports the domains' modules only when called. femkit's
    start (api.md § 6): every part schema is registered with the door, and every part's check with
    the check frame, first; a verb of femkit's that names no registered operation, or another's
    request, is refused; and the server is handed what it loads before it starts — the page's
    declaration, against these operations (web.md §§ 4, 8.1)."""
    part_checks()
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
    found = dict(sorted(found.items()))
    startup.register(startup.Load(what="the page's declaration", code="page-does-not-load",
                                  load=lambda: page.load(found), next=(view.command(SCHEMA_CHECK),)))
    return found
