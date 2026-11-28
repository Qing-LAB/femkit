"""The pass-through, the `given` mesher's program (workflow.md § 2.3; geometry.md §§ 3, 5), in the
`gmsh` environment:

    python pass_mesh.py GIVEN GROUPS MESH REGIONS

A program run in the stage's job with `documents.py` beside it (framework.md § 1): it imports the
standard library, Gmsh's Python module, NumPy and `documents` only.

GIVEN is the mesh the component's script wrote, `mesh.msh`, which its contract declares
(`[outputs] mesh`); GROUPS the geometry stage's `groups` document, what its check observed of the
geometry. The program passes GIVEN on unchanged as MESH — its bytes copied to a name beside MESH
and renamed in whole — and writes REGIONS, a `regions` document, the region map, in the one shape
every mesher's is (`documents.py`; geometry.md § 5): for each promised group the mesh holds at its
promised dimension, its elements of that dimension; its measure in the mesh, integrated over each
element's own shape — its Jacobian's determinant at Gauss points, never Gmsh's per-element
`volume`, which reads a second-order edge as straight (geometry.md § 5, measured); its measure
in the geometry, the sum of its pieces' measures in GROUPS; their relative difference; and, for a
group of the mesh's dimension, its worst element's signed inverse condition number (SICN). A
point group's measures are null. The map's `order` is the mesh's own: the highest order of its
elements. It judges nothing: one check judges every mesher's mesh (`check_mesh.py`).

It exits 0 when MESH and REGIONS are written; 1 when GIVEN is not there or does not open in Gmsh,
its last line the reason; 2 for a malformed call or GROUPS.
"""

import math
import os
import shutil
import sys

import gmsh
import numpy

import documents

#: Elements per call when integrating: bounds the memory a large mesh's Jacobians take.
CHUNK = 100_000


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        return stop("usage: python pass_mesh.py GIVEN GROUPS MESH REGIONS", 2)
    given, groups_file, mesh_file, regions_file = argv
    try:
        observed = documents.read(groups_file, "groups")
    except documents.Malformed as exc:
        return stop(str(exc), 2)
    if not os.path.isfile(given):
        return stop(f"the script wrote no {os.path.basename(given)}")

    # No option file of the person's is read, so what is measured depends on the mesh alone;
    # Gmsh's messages go to the run's log.
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        try:
            gmsh.open(given)
        except Exception as exc:
            return stop(f"{os.path.basename(given)} does not open in Gmsh: {exc}")
        mapped, order = regions(observed)
    finally:
        gmsh.finalize()

    part = os.path.join(os.path.dirname(os.path.abspath(mesh_file)), f".{os.path.basename(mesh_file)}.part")
    shutil.copyfile(given, part)
    os.replace(part, mesh_file)
    documents.write(regions_file, "regions", documents.make(
        "regions", dimension=observed["dimension"], order=order, groups=mapped))
    return 0


def regions(observed: dict) -> tuple[dict, int]:
    """Each promised group the open mesh holds at its promised dimension, measured against its
    pieces in the geometry; and the mesh's order, the highest of its elements'."""
    dimension = observed["dimension"]
    located: dict[str, list[int]] = {}
    for d, tag in gmsh.model.getPhysicalGroups():
        name = gmsh.model.getPhysicalName(d, tag)
        promised = observed["groups"].get(name)
        if promised is not None and promised["dimension"] == d:
            located.setdefault(name, []).extend(int(e) for e in gmsh.model.getEntitiesForPhysicalGroup(d, tag))
    out = {}
    for name, entities in sorted(located.items()):
        d = observed["groups"][name]["dimension"]
        tags = [int(t) for e in entities for ts in gmsh.model.mesh.getElements(d, e)[1] for t in ts]
        row = {"dimension": d, "elements": len(tags), "measure": None, "geometry": None, "difference": None,
               "quality": None}
        out[name] = row
        if tags and d > 0:
            row["measure"] = measure(d, entities, dimension)
            row["geometry"] = sum(p["measure"] for p in observed["groups"][name]["pieces"])
            row["difference"] = abs(row["measure"] - row["geometry"]) / row["geometry"]
        if tags and d == dimension:
            row["quality"] = float(min(gmsh.model.mesh.getElementQualities(tags, "minSICN")))
    order = max((gmsh.model.mesh.getElementProperties(t)[2] for t in gmsh.model.mesh.getElementTypes()), default=1)
    return out, max(int(order), 1)


def measure(d: int, entities: list[int], dimension: int) -> float:
    """A group's measure in the mesh, integrated over each element's own shape: the sum over its
    elements of the Jacobian's determinant at Gauss points, times their weights."""
    total = 0.0
    for entity in entities:
        for kind in gmsh.model.mesh.getElementTypes(d, entity):
            order = gmsh.model.mesh.getElementProperties(kind)[2]
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
