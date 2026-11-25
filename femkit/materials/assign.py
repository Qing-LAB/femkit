"""A component's `[assign]` table (materials.md § 5): for each body group its contract promises, the
material that fills it and, for each property whose material holds several datasets, the one
used. The table is this package's part of the component's schema (projects.md § 2), and so is its
check: declared here, beside the table, for the component's schema key (`PART_CHECKS`), and
registered at femkit's start after the component's own (api.md § 6; projects.md § 6). It reads
the component's frame and groups through the layout's object types (projects.md § 4), since the
`geometry` package that owns them sits above this one (framework.md § 1).

A material is named as materials.md § 4 says: `GLOBAL/<name>` names the global library's; any
other name, the project's own first, then the global library's. Until the global library is read
(plan § 4, E), a name the project lacks, and every `GLOBAL/` name, is not checked yet.

The findings, each at its key (core.md § 10):
- `not-a-body`: an assigned group that is not a body group the component promises — the body
  groups its choices;
- `no-such-material` (warning), at `material`: a name the project lacks that is close to one it
  holds, a misspelling, most likely — the project's materials its choices;
- `not-checked-yet` (info), at `material`: any other name the global library may hold;
- `no-such-property`, at `datasets.<property>`: a property the material does not hold — its
  properties the choices;
- `no-such-dataset`, at `datasets.<property>`: a dataset the property does not hold — its
  datasets the choices;
- `dataset-unchosen`, at `datasets.<property>`: a property holding several datasets, none named —
  its datasets the choices; there is no default dataset.
"""

from __future__ import annotations

import difflib
from typing import Any, Iterator

from femkit.core.issues import Issue
from femkit.core.schema import Model, as_reference, whole
from femkit.definitions.places import possible
from femkit.materials import material as materials
from femkit.projects import names
from femkit.projects.checking import Checking
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

#: A material's name: the project's own first, then the global library's; or the global library's,
#: opening with `GLOBAL/` (materials.md § 4; projects.md § 3).
MATERIAL = rf"(?:{names.GLOBAL})?{names.NAME.pattern}"


class Assignment(Model):
    """The material of one body group, and the dataset of each property that holds several
    (materials.md § 5)."""

    material: str = as_reference("the material, by name: the project's own, else the global library's; `GLOBAL/` "
                                 "names the global library's", "material", pattern=whole(MATERIAL))
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
    (projects.md § 6): each assigned group a body the component promises, and each material the
    project's own, with the datasets it names."""
    can = places(checking, part)
    bodies = sorted(group for group, there in can.items() if BODY in there)
    opened = checking.opened
    kind = opened.layout.objects[PROPERTY].part
    own = {p.address.name: p for p in opened.parts.values() if p.address.kind == kind}
    for group, assignment in opened.layout.objects[ASSIGNMENT].entries(part.data).items():
        if BODY not in can.get(group, ()):
            what = f"is {' or '.join(can[group])}" if can.get(group) else "is no group the component promises"
            yield checking.issue(part, TABLE, group, code="not-a-body", choices=bodies,
                                 message=f"a material fills a body; `{group}` {what}")
        name = assignment.material
        if name not in own:                           # a `GLOBAL/` name never is: it names the library's
            yield _elsewhere(checking, part, group, name, sorted(own))
            continue
        loaded: materials.Material | None = own[name].data
        if loaded is not None:                        # one that does not load: its own finding says why
            yield from _datasets(checking, part, group, assignment, loaded)


def _elsewhere(checking: Checking, part: Part, group: str, name: str, own: list[str]) -> Issue:
    """A material the project does not hold: a misspelling of one it does, most likely, when its
    name is close to one; else one the global library, not read yet, may hold (materials.md § 4)."""
    at = (TABLE, group, "material")
    near = difflib.get_close_matches(name, own, n=1) if not name.startswith(names.GLOBAL) else []
    if near:
        return checking.issue(part, *at, code="no-such-material", severity="warning", label=name, choices=own,
                              message=f"no material `{name}` in this project; did you mean `{near[0]}`?")
    library = "" if name.startswith(names.GLOBAL) else f"the project holds no material `{name}`, and "
    return checking.unchecked(part, *at, message=f"`{name}` is not checked: {library}the global material library is "
                                                 "not read yet")


def _datasets(checking: Checking, part: Part, group: str, assignment: Assignment,
              loaded: materials.Material) -> Iterator[Issue]:
    """The dataset of each property the material holds: named where it holds several, and every
    name one it holds."""
    for name, dataset in assignment.datasets.items():
        if name not in loaded.properties:
            yield checking.issue(part, TABLE, group, DATASETS, name, code="no-such-property",
                                 choices=sorted(loaded.properties),
                                 message=f"the material `{assignment.material}` holds no property `{name}`")
        elif dataset not in loaded.properties[name]:
            yield checking.issue(part, TABLE, group, DATASETS, name, code="no-such-dataset",
                                 choices=sorted(loaded.properties[name]),
                                 message=f"the {name} of `{assignment.material}` holds no dataset `{dataset}`")
    for name, datasets in loaded.properties.items():
        if len(datasets) > 1 and name not in assignment.datasets:
            yield checking.issue(part, TABLE, group, DATASETS, name, code="dataset-unchosen", choices=sorted(datasets),
                                 message=f"the {name} of `{assignment.material}` holds several datasets; name the "
                                         "one used, as there is no default")


PART_SCHEMAS: dict[str, type[Model]] = {}   # the table is a field of the component's schema, not a schema
PART_CHECKS = {COMPONENT: check}
