"""The project file, `project.toml` (projects.md §§ 2–3, models.md § 3): what the project is, the
components and studies it names, and its definitions — the `models.project` part schema and its
check. The definitions themselves are read, checked and resolved once, by the models domain's
definitions (`femkit/models/definitions.py`), and handed to the check frame
(`femkit/projects/checking.py`), whose findings carry theirs.

Its findings, each at the project file's key:
- `package-held` (`postprocess.packages`): a package femkit's recipe declares or pins for the
  environment that takes the projects' packages — what goes into it is the recipe's alone, so the
  entry is never delivered (definitions.md § 4.7): a warning for its name alone, which that
  environment holds already; an error for a version it is held to, which the recipe decides;
- `no-such-part` (error): a component or study it names has no file; its right value the list
  with the closest name there put in its place, or, with none close, its choices the ones there;
- `not-named` (warning): a component or study is in its folder but the project file does not name
  it, nor a name close to it — inert, `study prep` makes no case of it; right: the list with it named;
- `made-step` (error), at `studies`: a study's name with a step a stage's or a launch folder's path
  takes after a study's name — a stage kind, or `launch` — so its folder under `runs/` would lie
  inside another study's (projects.md § 5); the stage kinds read from their declaration.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Iterator

from pydantic import Field

from femkit.core.errors import Refusal
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.schema import (DefinitionError, Model, as_reference, field_extras, matching, parse_text, validate,
                                whole)
from femkit.definitions.models import CONSTRAINT
from femkit.envs import state as env_state
from femkit.models.definitions import Definition
from femkit.models.parts import cited, missing
from femkit.projects import door, location, names
from femkit.projects import layout as layouts
from femkit.projects.addresses import Address
from femkit.projects.checking import Checking, Registration
from femkit.projects.door import Part
from femkit.projects.project import PROJECT_FILE
from femkit.projects.schemas import PartFile

#: A conda package as the project file names it: its name, and the version it is held to, as conda
#: reads a constraint (`scikit-image`, `scikit-image>=0.24`) — the one form of a constraint.
PACKAGE = CONSTRAINT
#: A module's name, as `import` names it: `skimage`, `scipy.signal`.
MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")


class Package(Model):
    """A package whose module a script imports by a name other than the package's own."""

    conda: str = matching(PACKAGE, description="the conda package, by its name, with the version it is held to if "
                                               "any, as conda reads a constraint: `scikit-image>=0.24`")
    module: str = matching(MODULE, description="the name a script imports it by: `skimage`")


class Postprocess(Model):
    """What the project's observables scripts need beyond femkit's `postprocess` environment
    (models.md § 2)."""

    packages: list[Annotated[str, Field(pattern=whole(PACKAGE.pattern))] | Package] = Field(
        default_factory=list, description="the conda packages its scripts import beyond what femkit's `postprocess` "
        "environment holds, each installed into it on every machine: a package by its name, which a script imports "
        "by that name, or `{ conda = \"scikit-image\", module = \"skimage\" }` for one it imports by another")


class ProjectFile(PartFile):
    """`project.toml`: what the project is, the components and studies it names, and its
    definitions (projects.md § 3, models.md § 3)."""

    description: str = Field(description="what the project is, in a sentence or two")
    components: list[str] = as_reference("the project's components, by name: each the folder `components/<name>/`, "
                                         "holding `component.toml` and `geometry.py`", "component",
                                         default_factory=list)
    studies: list[str] = as_reference("the project's studies, by name: each the file `studies/<name>.toml`", "study",
                                      default_factory=list)
    definitions: dict[str, Definition] = Field(default_factory=dict, description="the project's definitions, by "
                                               "name: each a number of its type with its unit, written as its value "
                                               "or computed by a function in `definitions.py`; every other part uses "
                                               "one by its name", json_schema_extra={"doc": "models.md § 3"})
    postprocess: Postprocess | None = Field(default=None, description="what the project's observables scripts need "
                                            "beyond femkit's `postprocess` environment, so a copy of the project "
                                            "carries it", json_schema_extra={"doc": "models.md § 2"})


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """The project file's own rules (projects.md § 3, models.md § 3). A part the project file does
    not name, but which a name it holds without a file most likely misspells, is that name's
    finding alone (`parts.cited`): one mistake, said once, its right value the list with the name
    put right."""
    data: ProjectFile = part.data
    yield from cited(c, part)
    meant_by = {m.near for m in missing(c, part) if m.near is not None}
    for name, field in ProjectFile.model_fields.items():
        kind, key = field_extras(field).get("ref"), field.alias or name
        if kind not in c.opened.layout.kinds:
            continue
        named = getattr(data, name)
        for other in sorted(p.address.name for p in c.opened.parts.values() if p.address.kind == kind):
            if other not in named and other not in meant_by:
                yield c.issue(part, key, code="not-named", severity="warning", label=other, right=[*named, other],
                              message=f"the {kind} `{other}` is not named in the project file: it is inert, "
                                      "`study prep` makes no case of it")
    for entry in (data.postprocess.packages if data.postprocess is not None else ()):
        constraint = PACKAGE.fullmatch(_name(entry))
        if constraint is not None and constraint.group("name") in c.held:
            name, version = constraint.group("name"), constraint.group("version")
            yield c.issue(part, POSTPROCESS, "packages", code="package-held", label=_name(entry),
                          severity="error" if version else "warning",
                          message=f"femkit's recipe declares {name} for the environment where the observables run, "
                                  + ("and decides its version: a project cannot hold it to another, and the entry is "
                                     "never delivered" if version else
                                     "so it is there already, and the entry is never delivered"))
    taken = door.made_steps(c.opened.layout, c.stages)
    for name in data.studies:
        steps = sorted(set(names.steps(name)) & taken) if names.valid(name) else []
        if steps:
            yield c.issue(part, "studies", code="made-step", label=name,
                          message=f"the study `{name}` has the step `{steps[0]}`, which a stage's or a launch folder's "
                                  f"path under {door.holder(c.opened.layout)}/ takes after a study's name, so its "
                                  "folder would lie inside another study's: name the study otherwise")


def _name(entry: str | Package) -> str:
    """The conda constraint an entry declares."""
    return entry.conda if isinstance(entry, Package) else entry


def modules(data: Any) -> list[str]:
    """The names a project's scripts import its declared packages by (models.md §§ 2, 5.2): each
    package's own name, or the module its entry states; none for a project file that does not load
    or declares none."""
    held = data.postprocess.packages if isinstance(data, ProjectFile) and data.postprocess is not None else []
    return [e.module if isinstance(e, Package) else PACKAGE.fullmatch(e).group("name") for e in held]


#: The project file's table of what its observables scripts need: its field's key, as the file writes it.
POSTPROCESS = ProjectFile.model_fields["postprocess"].alias or "postprocess"
#: That table's list of packages: its field's key, as the file writes it.
PACKAGES = Postprocess.model_fields["packages"].alias or "packages"


def adding(module: str) -> str:
    """What would let a project's observables script import ``module``, which neither `postprocess`
    nor the project gives (models.md §§ 2, 5.2): its conda package added to the project file's
    `[postprocess] packages`, the line said whole — the package by the module's own name, or a table
    naming both where the package is named otherwise."""
    return (f"to import it, add its conda package to the project file's `[{POSTPROCESS}] {PACKAGES}`: "
            f'`{PACKAGES} = ["{module}"]`, or `{{ conda = "NAME", module = "{module}" }}` in that list where '
            "its conda name differs")


def declared(ctx: Context) -> env_state.Declared:
    """Every conda package the projects under the projects root declare in their project files'
    `[postprocess]` tables, as each writes it (definitions.md § 4.7): what `postprocess` is installed
    with on this machine beside femkit's own set — each project file read alone, by the door's read
    of one part's file on its own (`door.read_alone`, projects.md § 6), and its table through the
    project file's schema (`Postprocess`), never by opening the project, so a project whose other
    parts or keys do not load still declares its packages. None where no projects root is stated or
    made; a project file whose table does not load, or which is no TOML, declares nothing, and a
    note at it says why (envs.md § 3.1)."""
    try:
        found = location.projects(ctx)
    except Refusal:
        return env_state.Declared()
    layout = layouts.read_once(ctx)
    packages: list[str] = []
    notes: list[Issue] = []
    for project in found:
        file = project.path(PROJECT_FILE)
        try:
            text = door.read_alone(project, layout, Address(layout.project_kind, None))
            data = parse_text(text, file) if text is not None else {}
            held = validate(Postprocess, data.get(POSTPROCESS, {}), file)
        except (DefinitionError, OSError) as exc:
            why = "; ".join(f"{POSTPROCESS}.{p.path}: {p.reason}" if p.path else p.reason for p in exc.problems) \
                if isinstance(exc, DefinitionError) else exc.strerror
            notes.append(Issue(severity="info", code="packages-unread", subject=project.name, file=str(file),
                               message=f"the project {project.name} adds no package: its project file's "
                                       f"`[{POSTPROCESS}]` does not read — {why}"))
            continue
        packages += [_name(e) for e in held.packages]
    return env_state.Declared(packages=packages, notes=notes)


REGISTERS = Registration(schemas={"models.project": ProjectFile}, checks={"models.project": check},
                         packages=declared)
