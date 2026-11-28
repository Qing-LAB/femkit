"""A component's contract, `components/<name>/component.toml` (geometry.md § 3), and its check.

The contract wraps the person's geometry script: the frame it draws in, the project's definitions
and the files it reads, the mesh it writes too where it meshes as well, and the named groups it
promises — the only groups every other part may name. Its `[assign]` table, and that table's
check, are the `materials` package's (materials.md § 5; `femkit/materials/assign.py`), registered
for this schema after this check.

The check of a component alone (models.md § 11.1) finds, each at its key (core.md § 10):
- `not-a-length-unit`: a frame's unit that is no unit of length — the lengths of the unit table
  its choices, smallest first;
- `symmetry-not-2d`: an axis of revolution in a frame that is not 2-D (geometry.md § 3);
- `impossible-dimension`: a group whose dimension no place has in the frame — the dimensions
  some place has its choices (geometry.md § 7);
- `no-such-definition`: an input the project defines no definition of — the project's definitions
  its choices; none while the project file does not load;
- `wrong-dimension`: an input that is not what the contract declares it to be — a complex
  definition, which no script reads, among them — the kind its dimension is its right value,
  where it is one;
- `digest-differs`: an input file whose SHA-256 is not the one declared — the digest it has
  now its right value (a file not there is the door's finding).
Whether a 2-D frame states the axis an axisymmetric physics revolves it about is the pairing's,
a study's check (models.md § 5.1).
"""

from __future__ import annotations

from typing import Iterator, Literal

from pydantic import Field

from femkit.core.issues import Issue
from femkit.core.schema import LENGTH, Model, as_quantity, as_reference
from femkit.definitions.meshers import Order
from femkit.definitions.places import FRAMES, possible
from femkit.materials import assign as assignments
from femkit.projects.addresses import Address
from femkit.projects.checking import Checking, Registration
from femkit.projects.door import Part
from femkit.projects.schemas import PartFile

KEY = assignments.COMPONENT   # the key the layout names this schema by (projects.md § 4)

#: What a definition the script reads must be, and the dimension that is (geometry.md §§ 2, 3).
INPUTS = {"length": LENGTH, "angle": (("angle", 1),), "number": ()}
Input = Literal[tuple(INPUTS)]

#: The meaning of a 2-D physics that revolves the drawing about an axis: a component a study pairs
#: with one states that axis, `[frame.symmetry]` (geometry.md § 3; models.md § 3).
AXISYMMETRIC = "axisymmetric"


class Symmetry(Model):
    """The axis a 2-D geometry is revolved about, for an axisymmetric physics (geometry.md § 3)."""

    axis: Literal["x", "y"] = Field(description="the axis of revolution, in the drawing's plane; the drawing lies on "
                                                "one side of it")


class Frame(Model):
    """The script's space (geometry.md § 3): its dimension and its unit; its origin is where the
    script's coordinates are zero; for an axisymmetric physics, the axis it is revolved about."""

    dimension: Literal[FRAMES] = Field(description="the geometry's dimension, drawn in the x-y plane when 2")
    unit: str = as_quantity("the length unit of every number the script writes and of every length handed to it",
                            "unit")
    symmetry: Symmetry | None = Field(default=None, description="for a 2-D geometry a physics treats as axisymmetric: "
                                                                "the axis it is revolved about")


class Inputs(Model):
    """What the script reads beside its own numbers (geometry.md §§ 2, 3)."""

    definitions: dict[str, Input] = as_reference(
        "the project's definitions the script reads, by name, each with what it must be — a length reaches the "
        "script in the frame's unit, an angle in degrees, a number as itself", {"key": "definition"},
        default_factory=dict)
    files: dict[str, str] = as_reference("the files beside the script that it reads, each by its path from the "
                                         "component's folder, with its SHA-256", {"key": "file"}, default_factory=dict)


class DeclaredMesh(Model):
    """A mesh the script writes too (geometry.md § 3): its geometry order."""

    order: Order = Field(description="its geometry order, as a mesh recipe's — 2 for elements bent to follow a "
                                     "curved surface")


class Outputs(Model):
    """What the script writes beside the geometry (geometry.md § 3)."""

    mesh: DeclaredMesh | None = Field(default=None, description="a mesh it writes too, every promised group a named "
                                      "group of it — for a mesh no recipe can state; a mesh recipe names the `given` "
                                      "mesher to take it on unchanged")


class Component(PartFile):
    """`components/<name>/component.toml`: the contract of the geometry script beside it, and the
    material of each body group it promises (geometry.md § 3; materials.md § 5)."""

    frame: Frame = Field(description="the space the script draws in: its dimension and its unit; its origin is where "
                                     "the script's coordinates are zero, and every point another file gives is "
                                     "measured from it", json_schema_extra={"doc": "geometry.md § 3"})
    inputs: Inputs = Field(default_factory=Inputs, description="what the script reads beside its own numbers")
    outputs: Outputs = Field(default_factory=Outputs, description="what the script writes beside the geometry: a "
                             "mesh, only for a script that meshes too", json_schema_extra={"doc": "geometry.md § 3"})
    groups: dict[str, int] = Field(description="the named groups the script promises, each with its dimension — the "
                                               "frame's for a body, one less for a face, 1 for an edge in 3-D, 0 for "
                                               "a point; every other part names only these")
    assign: dict[str, assignments.Assignment] = assignments.table()


def check(checking: Checking, part: Part) -> Iterator[Issue]:
    """The findings on a component alone (module docstring), from the check frame (projects.md
    § 6): the project as opened, the unit table, the kinds of place and the project's definitions
    resolved."""
    component: Component = part.data
    frame = component.frame
    lengths = checking.units.of(LENGTH)
    if frame.unit not in lengths:
        yield checking.issue(part, "frame", "unit", code="not-a-length-unit",
                             choices=sorted(lengths, key=lambda u: (checking.units.unit(u).value, u)),
                             message=f"the frame's unit `{frame.unit}` is no unit of length, as `nm` or `m` is")
    if frame.symmetry is not None and frame.dimension != 2:
        yield checking.issue(part, "frame", "symmetry", code="symmetry-not-2d",
                             message=f"an axis of revolution turns a 2-D drawing into a solid; this frame is "
                                     f"{frame.dimension}-D")
    fitting = sorted({d for place in checking.places.values() for f, d in place.dimension.items()
                      if f == frame.dimension})
    for group, dimension in component.groups.items():
        if not possible(checking.places, frame.dimension, dimension):
            yield checking.issue(part, "groups", group, code="impossible-dimension", choices=fitting,
                                 message=f"no place of a {frame.dimension}-D geometry has the dimension {dimension} "
                                         f"the group `{group}` promises")
    yield from _definitions(checking, part, component.inputs)
    held = checking.opened.held_by(part.address)
    for path, digest in component.inputs.files.items():
        if path in held and held[path].sha256 != digest:
            yield checking.issue(part, "inputs", "files", path, code="digest-differs", right=held[path].sha256,
                                 message=f"the SHA-256 of {held[path].file} is not the one its contract declares")


def _definitions(checking: Checking, part: Part, inputs: Inputs) -> Iterator[Issue]:
    """Each definition the script reads: one the project defines, and what it is declared to be
    (geometry.md § 3) — a real number, which a script reads as a JSON number. While the project
    file does not load, what it defines is not known."""
    opened = checking.opened
    project = opened.parts.get(str(Address(opened.layout.project_kind, None)))
    if project is None or project.data is None:
        return
    defined = sorted({*checking.definitions, *checking.unresolved, *checking.complex})
    for name, kind in inputs.definitions.items():
        if name not in defined:
            yield checking.issue(part, "inputs", "definitions", name, code="no-such-definition", choices=defined,
                                 message=f"the script reads the definition `{name}`, which the project does not "
                                         "define")
        elif name in checking.complex:
            yield checking.issue(part, "inputs", "definitions", name, code="wrong-dimension",
                                 message=f"the script reads `{name}`, a complex definition: a script reads a real "
                                         "number")
        elif name in checking.dimensions and checking.dimensions[name] != INPUTS[kind]:
            right = next((k for k, dimension in INPUTS.items() if dimension == checking.dimensions[name]), None)
            yield checking.issue(part, "inputs", "definitions", name, code="wrong-dimension", right=right,
                                 message=f"the script reads `{name}` as a {kind}, which the project's {name} is not")


REGISTERS = Registration(schemas={KEY: Component}, checks={KEY: check})
