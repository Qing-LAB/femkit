"""Gmsh's mesher (workflow.md § 2.3; geometry.md §§ 5, 6), the mesh stage's program in the `gmsh`
environment:

    python mesh.py RECIPE GEOMETRY MESH REGIONS

A program run in the stage's job with `documents.py` beside it (framework.md § 1): it imports the
standard library, Gmsh's Python module, NumPy and `documents` only.

RECIPE is a `recipe` document, GEOMETRY the geometry stage's shapes, `geometry.xao`. It meshes them
as the recipe says, in Gmsh's terms (§ 6), and writes MESH as the type its definition writes,
`mesh/msh-2.2` — Gmsh's MSH 2.2, as text, where Gmsh's own default is MSH 4.1 — every promised
group the geometry holds a named group of it, and no other group; and REGIONS, a `regions`
document, the region map (`documents.py` defines both):

- `elements`: the elements of its dimension the group holds;
- `measure`: its length, area or volume in the mesh, integrated over each element's own shape —
  its Jacobian's determinant at Gauss points — never Gmsh's per-element `volume`, which reads a
  second-order edge as straight (§ 5, measured);
- `geometry`: its measure in the geometry, OpenCASCADE's;
- `difference`: |measure - geometry| / geometry;
- `quality`: its worst element's signed inverse condition number (SICN), for a group of the
  mesh's dimension; null for one of lower dimension, whose elements bound the cells judged.
A point group's measures are null. A promised group the geometry lacks is left out of both.

It judges nothing: one check judges every mesher's mesh from its region map (`check_mesh.py`,
geometry.md § 5). It exits 0 when MESH and REGIONS are written; 1 when the geometry is not there,
does not open, or Gmsh cannot mesh it, its last line the reason; 2 for a malformed call or
RECIPE. What a recipe's value may be is `project check`'s; this program checks only the
document's shape.
"""

import math
import os
import sys

import gmsh
import numpy

import documents

#: Gmsh's option naming a field's entities of each dimension.
LISTS = {0: "PointsList", 1: "CurvesList", 2: "SurfacesList", 3: "VolumesList"}
#: Gmsh's own default sampling of a curve or a surface in a distance field: the least taken.
SAMPLING = 20
#: The most samples a distance field takes along each direction of a curve (one direction) or a
#: surface (two, so the square of it): past this, its cost outgrows the meshing it steers.
MOST_SAMPLES = {1: 10000, 2: 1000}
#: Elements per call when integrating: bounds the memory a large mesh's Jacobians take.
CHUNK = 100_000


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        return stop("usage: python mesh.py RECIPE GEOMETRY MESH REGIONS", 2)
    recipe_file, geometry, mesh_file, regions_file = argv
    try:
        recipe = documents.read(recipe_file, "recipe")
    except documents.Malformed as exc:
        return stop(str(exc), 2)
    if not os.path.isfile(geometry):
        return stop(f"there is no geometry at {geometry}")

    # No option file of the person's is read, so a mesh depends on the geometry and the recipe
    # alone (§ 5); Gmsh's messages go to the run's log.
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        try:
            gmsh.open(geometry)
            groups = mesh(recipe, locate(recipe["groups"]), mesh_file)
        except Exception as exc:
            return stop(f"Gmsh did not mesh {os.path.basename(geometry)}: {exc}")
    finally:
        gmsh.finalize()
    documents.write(regions_file, "regions", documents.make(
        "regions", dimension=recipe["dimension"], order=recipe["order"], groups=groups))
    return 0


def locate(promised: dict) -> dict:
    """Each promised group's dimension and entities in the open geometry, every other group taken
    out so the mesh holds the promised ones alone."""
    located, others = {}, []
    for d, tag in gmsh.model.getPhysicalGroups():
        name = gmsh.model.getPhysicalName(d, tag)
        if promised.get(name) == d:
            located.setdefault(name, (d, []))[1].extend(int(e) for e in gmsh.model.getEntitiesForPhysicalGroup(d, tag))
        else:
            others.append((d, tag))
    if others:  # given none, Gmsh removes every group
        gmsh.model.removePhysicalGroups(others)
    return located


def mesh(recipe: dict, located: dict, mesh_file: str) -> dict:
    """Mesh the open geometry as the recipe says, in Gmsh's terms (§ 6), write it, and measure
    each group against the geometry."""
    dimension, order = recipe["dimension"], recipe["order"]
    # The largest size anywhere, and no size taken from points, curvature or the boundary, so the
    # recipe alone sets it.
    gmsh.option.setNumber("Mesh.MeshSizeMax", recipe["size"])
    for option in ("Mesh.MeshSizeFromPoints", "Mesh.MeshSizeFromCurvature", "Mesh.MeshSizeExtendFromBoundary"):
        gmsh.option.setNumber(option, 0)
    size_fields(recipe, located)
    gmsh.model.mesh.generate(dimension)
    if order > 1:  # Gmsh places the added nodes on the geometry's true curves and surfaces
        gmsh.model.mesh.setOrder(order)

    # As the type its definition writes, `mesh/msh-2.2`: MSH 2.2 as text. Gmsh writes only the
    # elements of named groups (its default), which are the promised ones alone. Gmsh takes the
    # format from the file's extension, so the part written first carries it, and is renamed in
    # whole.
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    gmsh.option.setNumber("Mesh.Binary", 0)
    part = os.path.join(os.path.dirname(os.path.abspath(mesh_file)), ".mesh.part.msh")
    gmsh.write(part)
    os.replace(part, mesh_file)

    groups = {}
    for name, (d, entities) in sorted(located.items()):
        tags = [int(t) for e in entities for ts in gmsh.model.mesh.getElements(d, e)[1] for t in ts]
        row = {"dimension": d, "elements": len(tags), "measure": None, "geometry": None, "difference": None,
               "quality": None}
        groups[name] = row
        if tags and d > 0:
            row["measure"] = measure(d, entities, order, dimension)
            row["geometry"] = sum(gmsh.model.occ.getMass(d, e) for e in entities)
            row["difference"] = abs(row["measure"] - row["geometry"]) / row["geometry"]
        if tags and d == dimension:
            row["quality"] = float(min(gmsh.model.mesh.getElementQualities(tags, "minSICN")))
    return groups


def size_fields(recipe: dict, located: dict) -> None:
    """Each of the recipe's `sizes` as a size field (§ 6): one that starts at its group — the
    distance from a point, an edge or a face group, or a constant size inside a body group and the
    distance from that body — and grows at `growth` until it reaches `size`; the smallest of them
    applies where they meet. A group the geometry lacks, or that holds nothing, has none: the
    check refuses it, naming it."""
    size, made = recipe["size"], []
    for name, small in sorted(recipe["sizes"].items()):
        if small >= size or not located.get(name, (0, []))[1]:  # never finer than everywhere: nothing to refine
            continue
        d, entities = located[name]
        if d == recipe["dimension"]:  # a body: its size inside, grown from its boundary outward
            made.append(field("Constant", VIn=small, VOut=size, IncludeBoundary=1, **{LISTS[d]: entities}))
            d, entities = d - 1, sorted({abs(int(t)) for _, t in gmsh.model.getBoundary(
                [(d, e) for e in entities], combined=True, oriented=False)})
        distance = field("Distance", **{LISTS[d]: entities}, **({"Sampling": sampling(d, entities, small)} if d else {}))
        # Linear from `small` at the group to `size` at the distance where it reaches it: the
        # size added per unit of distance is `growth`.
        made.append(field("Threshold", InField=distance, SizeMin=small, SizeMax=size, DistMin=0,
                          DistMax=(size - small) / recipe["growth"]))
    if made:
        gmsh.model.mesh.field.setAsBackgroundMesh(field("Min", FieldsList=made))


def sampling(d: int, entities: list[int], small: float) -> int:
    """Samples along each direction of a curve or surface, so their spacing is near the size at
    the group — Gmsh measures a distance to the nearest sample."""
    extent = max(math.dist(box[:3], box[3:]) for box in (gmsh.model.getBoundingBox(d, e) for e in entities))
    return min(max(SAMPLING, math.ceil(extent / small) + 1), MOST_SAMPLES[d])


def field(kind: str, **options) -> int:
    tag = gmsh.model.mesh.field.add(kind)
    for key, value in options.items():
        if isinstance(value, list):
            gmsh.model.mesh.field.setNumbers(tag, key, value)
        else:
            gmsh.model.mesh.field.setNumber(tag, key, value)
    return tag


def measure(d: int, entities: list[int], order: int, dimension: int) -> float:
    """A group's measure in the mesh, integrated over each element's own shape: the sum over its
    elements of the Jacobian's determinant at Gauss points, times their weights."""
    total = 0.0
    for entity in entities:
        for kind in gmsh.model.mesh.getElementTypes(d, entity):
            points, weights = gmsh.model.mesh.getIntegrationPoints(kind, rule(d, order, dimension))
            count = len(gmsh.model.mesh.getElementsByType(kind, entity)[0])
            tasks = max(1, math.ceil(count / CHUNK))
            for task in range(tasks):
                _, determinants, _ = gmsh.model.mesh.getJacobians(kind, points, entity, task, tasks)
                total += float(numpy.dot(numpy.reshape(determinants, (-1, len(weights))), weights).sum())
    return total


def rule(d: int, order: int, dimension: int) -> str:
    """The Gauss rule that integrates an element's measure: exactly where the determinant is a
    polynomial — a straight element, or one of the frame's dimension, whose determinant has degree
    d(order - 1) — and for a curved edge or face, whose determinant is a root, a rule well past
    where the sum stops changing (measured 2026-11-25: a second-order circle's length agrees to
    1e-15 from Gauss8 to Gauss20)."""
    if order == 1 or d == dimension:
        return f"Gauss{max(1, d * (order - 1))}"
    return "Gauss12"


def stop(reason: str, status: int = 1) -> int:
    """The reason, as the last line of the program's output (jobs.md § 2)."""
    sys.stdout.flush()
    print(reason, file=sys.stderr, flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
