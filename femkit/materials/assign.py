"""A component's `[assign]` table (materials.md § 5): for each body group its contract promises, the
material that fills it and, for each property whose material holds several datasets, the one
used. The table is this package's part of the component's schema (projects.md § 2), and so is its
check: declared here, beside the table, for the component's schema key (`REGISTERS`, `checks`), and
registered at femkit's start after the component's own (api.md § 6; projects.md § 6). It reads
the component's frame and groups through the layout's object types (projects.md § 4), since the
`geometry` package that owns them sits above this one (framework.md § 1).

A material is named as materials.md § 4 says: `GLOBAL/<name>` names the global library's; any
other name, the project's own first, then the global library's — found by the door, which loads
each library material the project names (`door.named`). The name rule is checked here, where it
can say what in a name breaks it, so the component still loads (projects.md § 3).

The findings, each at its key (core.md § 10):
- `not-a-body`: an assigned group that is not a body group the component promises — the body
  groups its choices;
- `bad-name`, at `material`: a name the name rule refuses, saying what in it breaks the rule —
  the name it most likely meant, by the rule (`names.mended`), its right value;
- `no-such-material`, at `material`: a name in neither place, naming both places looked in —
  the library alone for a `GLOBAL/` name — or, where the projects root has no library yet,
  saying so, with the `project new` that makes it; its right value the name either place holds
  closest to it by its whole name or its last step, written as the choice would be — `gold`
  meaning `GLOBAL/metals/gold`; else the materials each holds its choices, the library's as
  `GLOBAL/<name>`;
- `no-such-property`, at `datasets.<property>`: a property the material does not provide, or an
  equivalent form named in place of the property a formulation reads — the properties it
  provides the choices;
- `no-such-dataset`, at `datasets.<property>`: a dataset the property is not provided by — its
  datasets the choices;
- `dataset-unchosen`, at `datasets.<property>`: a property provided by several datasets, none
  named — its datasets the choices; there is no default dataset.
A material provides a property by the datasets held under it and under each of its equivalent
forms (materials.md § 1; `material.answering`).
"""

from __future__ import annotations

from typing import Any, Iterator

from femkit.core import text
from femkit.core.issues import Issue
from femkit.core.schema import Model, as_reference, meant, nearest
from femkit.definitions.places import possible
from femkit.materials import material as materials
from femkit.projects import door, names
from femkit.projects.checking import Checking, Registration
from femkit.projects.door import Part
from femkit.projects.layout import held

COMPONENT = "geometry.component"   # the schema key of the component whose table this is (projects.md § 4)
TABLE = "assign"                   # the component's table holding the assignment (projects.md § 2)
DATASETS = "datasets"              # an assignment's key naming the dataset each property uses
BODY = "body"                      # the place an assigned group is (geometry.md § 7)
#: The layout's object types of a component this check reads (projects.md § 4): its frame, its
#: promised groups, its assignment; and a material's properties.
FRAME, GROUP, ASSIGNMENT, PROPERTY = "frame", "group", "assignment", "property"
DIMENSION = "dimension"            # the frame's key stating the geometry's dimension (geometry.md § 3)


class Assignment(Model):
    """The material of one body group, and the dataset of each property that holds several
    (materials.md § 5)."""

    material: str = as_reference("the material, by name: the project's own, else the global library's; `GLOBAL/` "
                                 "names the global library's", "material")
    datasets: dict[str, str] = as_reference("for each property whose material holds several datasets, the one "
                                            "used, by its name", {"key": "property"}, default_factory=dict)


def table() -> Any:
    """The component's `[assign]` field: an `Assignment` for each body group, keyed by the group."""
    return as_reference("the material that fills each body group, keyed by the group", {"key": f"group:{BODY}"},
                        extra={"doc": "materials.md § 5"}, default_factory=dict)


def places(checking: Checking, part: Part) -> dict[str, list[str]]:
    """Each group the component promises, with the places it may be before its geometry exists
    (geometry.md § 7); none where its frame states no dimension it can have."""
    layout = checking.opened.layout
    frame = next(iter(layout.objects[FRAME].entries(part.data).values()), None)
    dimension = held(frame, DIMENSION)
    groups = layout.objects[GROUP].entries(part.data)
    return {g: possible(checking.places, dimension, d) if isinstance(d, int) and isinstance(dimension, int) else []
            for g, d in groups.items()}


def check(checking: Checking, part: Part) -> Iterator[Issue]:
    """The findings on a component's assignment (module docstring), from the check frame
    (projects.md § 6): each assigned group a body the component promises, and each material found
    — the project's own, or the global library's — with the datasets it names."""
    can = places(checking, part)
    bodies = sorted(group for group, there in can.items() if BODY in there)
    opened = checking.opened
    kind = opened.layout.objects[PROPERTY].part
    for group, assignment in opened.layout.objects[ASSIGNMENT].entries(part.data).items():
        if BODY not in can.get(group, ()):
            what = f"is {' or '.join(can[group])}" if can.get(group) else "is no group the component promises"
            yield checking.issue(part, TABLE, group, code="not-a-body", choices=bodies,
                                 message=f"a material fills a body; `{group}` {what}")
        if (why := names.broken(assignment.material)) is not None:
            meant = names.mended(assignment.material)
            yield checking.issue(part, TABLE, group, "material", code="bad-name", label=assignment.material,
                                 right=meant, message=f"`{assignment.material}` is no material's name: {why}"
                                                      + (f"; it most likely means `{meant}`" if meant else ""))
            continue
        found = door.named(opened, kind, assignment.material)
        if found is None:
            yield _nowhere(checking, part, group, assignment.material, kind)
            continue
        loaded: materials.Material | None = found.data
        if loaded is not None:                        # one that does not load: its own finding says why
            yield from _datasets(checking, part, group, assignment, loaded)


def _nowhere(checking: Checking, part: Part, group: str, name: str, kind: str) -> Issue:
    """A material in neither place a name is looked for (materials.md § 4): the project's own
    materials — not for a `GLOBAL/` name — and the global library's, or none where the projects
    root holds none yet, which the next `project new` makes. The name either place holds closest
    to it, by its whole name or its last step — the place the name points at first — is what it
    most likely meant, its right value, written as the choice would be; else the materials each
    holds are its choices."""
    opened = checking.opened
    listed = opened.libraries.get(kind)
    explicit = name.startswith(names.GLOBAL)
    there, missing = listed is not None and listed.there, listed is not None and not listed.there
    looked = ([] if explicit else [f"the project's {opened.layout.kinds[kind].folder}/"]) + (
        [f"the global library {text.path(listed.library.place)}"] if there else [])
    choices = door.known(opened, kind)
    pool = sorted(choices, key=lambda c: c.startswith(names.GLOBAL) != explicit)   # where the name points first
    near = nearest(names.bare(name), pool, names.whole_or_last)
    none = (f"; your projects root has no global library yet, {text.path(listed.library.place)}: the next project "
            "new makes it, holding femkit's shipped materials" if missing else "")
    return checking.issue(part, TABLE, group, "material", code="no-such-material", label=name, right=near,
                          choices=choices if near is None else (), next=(door.seeding(),) if missing else (),
                          message=f"no material `{name}`" + (f" in {' or in '.join(looked)}" if looked else "") + none
                                  + meant(names.bare(name), pool, names.whole_or_last))


def _datasets(checking: Checking, part: Part, group: str, assignment: Assignment,
              loaded: materials.Material) -> Iterator[Issue]:
    """The dataset of each property the material provides — held under it, or under an
    equivalent form of it (materials.md § 1): named where it provides several, by the property
    a formulation reads, and every name one it provides."""
    answered = materials.answering(checking.properties, loaded.properties)
    for name, dataset in assignment.datasets.items():
        if name not in answered:
            of = [p for p, listed in checking.properties.items() if name in listed.equivalents and p in answered]
            said = (f"`{name}` is a form of the {of[0]}, and a dataset is named by the property a formulation reads"
                    if of else f"the material `{assignment.material}` holds no property `{name}`")
            yield checking.issue(part, TABLE, group, DATASETS, name, code="no-such-property", choices=sorted(answered),
                                 message=said)
        elif dataset not in answered[name]:
            yield checking.issue(part, TABLE, group, DATASETS, name, code="no-such-dataset",
                                 choices=sorted(answered[name]),
                                 message=f"the {name} of `{assignment.material}` holds no dataset `{dataset}`")
    for name, datasets in answered.items():
        if len(datasets) > 1 and name not in assignment.datasets:
            yield checking.issue(part, TABLE, group, DATASETS, name, code="dataset-unchosen", choices=sorted(datasets),
                                 message=f"the {name} of `{assignment.material}` holds several datasets; name the "
                                         "one used, as there is no default")


REGISTERS = Registration(checks={COMPONENT: check})
