"""The one list of where operations live, and of where part schemas and their checks live; what the
server loads before it starts, handed to it (api.md § 6)."""

from __future__ import annotations

import importlib
from typing import Callable, Iterable, NamedTuple

from femkit import page
from femkit.core import schema, view
from femkit.core.operations import Operation
from femkit.core.schema import Model
from femkit.definitions.requests import SCHEMA_CHECK
from femkit.envs import state as env_state
from femkit.projects import checking, schemas
from femkit.server import startup


class Group(NamedTuple):
    """A command group (api.md §§ 4, 6): its one sentence, as `femkit --help` lists it, and the
    chapter of the user manual that explains it, by its file's name in `docs/manual/` — the help of
    each of its commands ends with it (core.md § 2)."""

    sentence: str
    manual: str


#: Each command group by its name, the operations' names' prefix; `""` is femkit's own, the group
#: of the commands that have none (`doctor`).
GROUPS: dict[str, Group] = {
    "": Group("femkit — a solver-neutral finite-element workbench.", "1-install.md"),
    "case": Group("the cases a study's prep wrote, each with its study and point", "5-studies-and-cases.md"),
    "config": Group("this machine's settings, femkit's own", "1-install.md"),
    "env": Group("the engine environments: install, validate, list, clean, log", "1-install.md"),
    "job": Group("this machine's record and the jobs femkit runs", "7-geometries-and-meshes.md"),
    "material": Group("materials: make a new one from another source's file", "6-materials.md"),
    "project": Group("a project: start one from a template, check it, list them, see it as a graph",
                     "2-start-a-project.md"),
    "schema": Group("femkit's own definitions and the reference pages written from them", "1-install.md"),
    "serve": Group("the web page's server: start, stop, status", "1-install.md"),
    "study": Group("a project's studies: list them, prep each for its jobs — its cases, its geometries and meshes "
                   "and the jobs that make them — and show their workflow", "5-studies-and-cases.md"),
    "web": Group("the web page's bundle, built from its sources", "1-install.md"),
}


def group_name(operation: str) -> str:
    """The name of the command group an operation, by its name, belongs to: its name's prefix, `""`
    for femkit's own — what the command line and the page group it by."""
    return operation.rpartition(".")[0]


def group(operation: str) -> Group | None:
    """The command group an operation, by its name, belongs to; None for one of no declared group
    — a test's own."""
    return GROUPS.get(group_name(operation))


def _choices() -> dict[str, Callable[[], Iterable[str]]]:
    """Each declaration a request field may name its values by (`choices`, core.md § 2), and what
    gives the names it holds: a loader of the shipped definitions, called when a help is built —
    the importers, the environments, the templates, the meshers, the engines."""
    from femkit.definitions import catalogue
    return {"importers": catalogue.load_importers, "environments": catalogue.load_environments,
            "templates": catalogue.load_templates, "meshers": catalogue.load_meshers, "engines": catalogue.load_engines}


DOMAINS = (
    "femkit.config.operations",
    "femkit.envs.operations",
    "femkit.jobs.operations",
    "femkit.jobs.setup",
    "femkit.projects.operations",
    "femkit.materials.operations",
    "femkit.reference",
    "femkit.models.operations",
    "femkit.workflow.operations",
    "femkit.server.operations",
    "femkit.server.build",
)

#: The modules that own part schemas or a part of one (projects.md § 6), each declaring what it
#: registers in one shape, `REGISTERS` (`checking.Registration`), filled only with what it has: its
#: part schemas by the key a layout names each by, the check of each schema it checks (projects/checking.py), what
#: states the keys a declaration gives beside a schema (web.md § 8.3) — a physics' formulation and its
#: kinds, a step's kind, a material's properties — and, for the project file, what gives the packages
#: the projects declare (definitions.md § 4.7). A component's assignment is the materials package's,
#: checked after the component's own; a global library's material is offered what changed in
#: femkit's shipped one, after the material's own check; a study's recipe is checked by the workflow
#: for a mesh whose mesher has its input, after the study's own check.
PARTS: tuple[str, ...] = (
    "femkit.models.project",
    "femkit.materials.material",
    "femkit.materials.library",
    "femkit.geometry.component",
    "femkit.materials.assign",
    "femkit.models.physics",
    "femkit.geometry.recipe",
    "femkit.models.observables",
    "femkit.models.study",
    "femkit.workflow.graph",
)


def registrations() -> list[tuple[str, checking.Registration]]:
    """What each module of ``PARTS`` registers, by its name, in their order; imports them only when
    called."""
    return [(name, importlib.import_module(name).REGISTERS) for name in PARTS]


def part_schemas() -> dict[str, type[Model]]:
    """Every part schema the modules of ``PARTS`` declare, by its key, each registered with the door
    (projects.md § 6), which refuses one key with two models."""
    declared: dict[str, type[Model]] = {}
    for _, registers in registrations():
        for key, model in registers.schemas.items():
            schemas.register(key, model)
            declared[key] = model
    return declared


def part_checks() -> dict[str, tuple[checking.Check, ...]]:
    """Every check the modules of ``PARTS`` declare, by the key of the schema it checks, each
    registered with the check frame (projects/checking.py), in the order of ``PARTS``, and what
    states the keys a declaration gives beside a schema, registered there too (web.md § 8.3); a
    check, or keys, of a schema no module of ``PARTS`` declares is refused, as a defect."""
    known = part_schemas()
    declared: dict[str, tuple[checking.Check, ...]] = {}
    for module_name, registers in registrations():
        for key, check in registers.checks.items():
            if key not in known:
                raise RuntimeError(f"{module_name} checks the part schema {key!r}, which no module of PARTS declares")
            checking.register(key, check)
            declared[key] = (*declared.get(key, ()), check)
        for key, stated in registers.keys.items():
            if key not in known:
                raise RuntimeError(f"{module_name} states keys beside the part schema {key!r}, which no module of "
                                   "PARTS declares")
            checking.register_keys(key, stated)
    return declared


def _packages() -> Callable:
    """What gives the packages the projects under the projects root declare (definitions.md § 4.7):
    what the one module of ``PARTS`` that registers it declares — none or two, a defect."""
    given = [(name, r.packages) for name, r in registrations() if r.packages is not None]
    if len(given) != 1:
        raise RuntimeError(f"{len(given)} modules of PARTS give the packages the projects declare, not one: "
                           f"{', '.join(name for name, _ in given) or 'none'}")
    return given[0][1]


def operations() -> dict[str, Operation]:
    """Every declared operation by name; imports the domains' modules only when called. femkit's
    start (api.md § 6): every part schema is registered with the door, and every part's check with
    the check frame, first, and what gives the names of each declaration a request field may name
    in `choices`; a verb of femkit's that names no registered operation, or another's request, is
    refused; and the server is handed what it loads before it starts — the page's declaration,
    against these operations (web.md §§ 4, 8.1); and the envs domain is handed what gives the packages
    the projects under the projects root declare, as the module of PARTS that registers it declares
    it (definitions.md § 4.7)."""
    part_checks()
    env_state.provide(_packages())
    for declaration, names in _choices().items():
        schema.provide(declaration, names)
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
                                  load=lambda: page.load(offered(found, "page")), next=(view.command(SCHEMA_CHECK),)))
    return found


def offered(ops: dict[str, Operation], surface: str) -> dict[str, Operation]:
    """The operations a surface offers, by their declared `surfaces` (api.md § 2): the one place
    each surface's set is decided — the command line's commands, the page's routes and the page
    declaration's check."""
    return {name: op for name, op in ops.items() if surface in op.surfaces}
