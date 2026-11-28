"""NGSolve's hand-over (geometry.md § 8): femkit's own layer, which builds NGSolve's mesh element
by element from the mesh stage's mesh — Gmsh's MSH 2.2 text format — every handed group by its
name, so NGSolve never handles a file format.

A program run in the solve's job with `documents.py` beside it (framework.md § 1): it imports
the standard library, what the `ngsolve` environment holds — NGSolve, Netgen, meshio, NumPy — and
`documents`. A solve's program uses it as

    from handover import mesh
    m = mesh("mesh.msh", "handover.json")

and it is its own check, in the environment:

    python handover.py MESH HANDOVER REPORT

HANDOVER is a `handover` document, the groups NGSolve's hand-over hands it; the program builds the
mesh from them, finds every one's name in it, and writes REPORT, a `report` document: each group
with the kind of region NGSolve holds it as — `material`, `boundary`, `bboundary` or
`bbboundary`, by its dimension below the mesh's — its elements there, and its measure as NGSolve
integrates it (null for a point group). It exits 0 when every group is there, otherwise 1, its last
line the reason; a mesh this layer refuses exits 1 with the refusal; a malformed call or HANDOVER
exits 2.

The layer builds first-order simplices and points, and refuses any other cell by its name — a
second-order mesh's among them: from Gmsh's second-order nodes it would build a mesh that is not
curved, and NGSolve cannot curve it (geometry.md § 8, measured), so it hands over geometry order
1 alone. Two handed groups sharing elements are refused too, since NGSolve gives each element one
name — the hand-over's declared limit (geometry.md § 8).
"""

import os
import sys

import meshio
import numpy
from netgen import meshing
from ngsolve import BBBND, BBND, BND, VOL, CoefficientFunction, Integrate, Mesh

import documents

#: The cells this layer builds, by meshio's name: each its dimension. Every other cell — a
#: second-order one, a quadrilateral, a hexahedron — is refused, by name.
CELLS = {"vertex": 0, "line": 1, "triangle": 2, "tetra": 3}
#: How NGSolve holds a region of each dimension below the mesh's, and the integration over it.
REGIONS = {0: ("material", VOL), 1: ("boundary", BND), 2: ("bboundary", BBND), 3: ("bbboundary", BBBND)}
#: Netgen numbers its points from 1 (its PointIndex::BASE).
FIRST_POINT = 1


class NotHanded(Exception):
    """A mesh this layer does not build, with the reason in plain words."""


def read(path: str, handed: dict) -> tuple[int, numpy.ndarray, dict]:
    """The mesh's dimension, its nodes, and each handed group by name: its dimension and its cells,
    as node indices from 0. Not handed: a cell this layer does not build, a handed group the mesh does
    not hold, and two handed groups sharing a piece — NGSolve gives each element one name."""
    msh = meshio.read(path, file_format="gmsh")
    names = {(int(dim), int(tag)): name for name, (tag, dim) in msh.field_data.items() if name in handed}
    missing = sorted(set(handed) - set(names.values()))
    if missing:
        raise NotHanded(f"{os.path.basename(path)} holds no group {', '.join(f'`{n}`' for n in missing)}")
    others = sorted({b.type for b in msh.cells} - CELLS.keys())
    if others:
        raise NotHanded(f"{os.path.basename(path)} holds {', '.join(others)} cells; femkit's layer builds "
                        f"{', '.join(CELLS)} cells")
    groups: dict[str, tuple[int, list]] = {}
    held: dict[tuple[int, int], set[str]] = {}   # each geometric piece, by dimension and tag: its groups
    for block, physical, entity in zip(msh.cells, msh.cell_data["gmsh:physical"], msh.cell_data["gmsh:geometrical"]):
        d = CELLS[block.type]
        for tag in numpy.unique(physical):
            if (d, int(tag)) in names:
                groups.setdefault(names[d, int(tag)], (d, []))[1].append(block.data[physical == tag])
        for piece, tag in numpy.unique(numpy.stack([entity, physical]), axis=1).T:
            if (d, int(tag)) in names:
                held.setdefault((d, int(piece)), set()).add(names[d, int(tag)])
    # MSH 2.2 writes an element once for each group holding it: a piece in two groups of one
    # dimension would be one element with two names.
    shared = sorted(sorted(g) for g in held.values() if len(g) > 1)
    if shared:
        raise NotHanded(f"the groups {' and '.join(f'`{n}`' for n in shared[0])} share elements; NGSolve gives each "
                        "element one name")
    dimension = max((d for d, _ in groups.values()), default=0)
    return dimension, msh.points, {n: (d, numpy.concatenate(c)) for n, (d, c) in groups.items()}


def build(path: str, handed: dict) -> tuple[Mesh, dict]:
    """NGSolve's mesh of ``path`` from the ``handed`` groups, and each group's dimension and cells."""
    dimension, points, groups = read(path, handed)
    ng = meshing.Mesh(dim=dimension)
    ng.AddPoints(numpy.ascontiguousarray(points[:, :3], dtype=float))
    for name, (d, cells) in sorted(groups.items(), key=lambda g: (-g[1][0], g[0])):
        if (d, dimension) == (0, 2):
            # Netgen 6.2.2606's AddRegion files a point region of a 2-D mesh among the edges, so
            # NGSolve never sees its name (measured 2026-11-25); a 2-D mesh keeps point names apart.
            index = ng.GetNCD2Names() + 1
            ng.SetCD2Name(index, name)
        else:
            index = ng.AddRegion(name, d)
        if d == 0:
            for (node,) in cells:
                ng.Add(meshing.Element0D(meshing.PointId(int(node) + FIRST_POINT), index=index))
        else:
            ng.AddElements(d, index, numpy.ascontiguousarray(cells, dtype=numpy.int32), base=0)
    built = Mesh(ng)
    held = {name: names(built, dimension - d) for name, (d, _) in groups.items()}
    missing = sorted(name for name, found in held.items() if name not in found)
    if missing:
        raise NotHanded(f"NGSolve's mesh does not name {', '.join(f'`{n}`' for n in missing)}")
    return built, groups


def names(m: Mesh, codimension: int) -> set[str]:
    return set({0: m.GetMaterials, 1: m.GetBoundaries, 2: m.GetBBoundaries, 3: m.GetBBBoundaries}[codimension]())


def mesh(path: str, handover: str) -> Mesh:
    """NGSolve's mesh of the mesh stage's ``path``, every group the ``handover`` document hands a
    region of it by its name."""
    return build(path, documents.read(handover, "handover")["groups"])[0]


def report(path: str, handed: dict) -> dict:
    """Each handed group as NGSolve holds it: its kind of region, its elements, and its measure."""
    built, groups = build(path, handed)
    dimension = built.dim
    out = {}
    for name, (d, cells) in sorted(groups.items()):
        region, vorb = REGIONS[dimension - d]
        where = {0: built.Materials, 1: built.Boundaries, 2: built.BBoundaries, 3: built.BBBoundaries}[dimension - d]
        out[name] = {"dimension": d, "region": region, "elements": len(cells),
                     "measure": None if d == 0 else Integrate(CoefficientFunction(1), built, vorb,
                                                              definedon=where(name))}
    return documents.make("report", dimension=dimension, groups=out)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        return stop("usage: python handover.py MESH HANDOVER REPORT", 2)
    mesh_file, handover_file, report_file = argv
    try:
        handed = documents.read(handover_file, "handover")["groups"]
    except documents.Malformed as exc:
        return stop(str(exc), 2)
    try:
        document = report(mesh_file, handed)
    except NotHanded as exc:
        return stop(str(exc))
    documents.write(report_file, "report", document)
    return 0


def stop(reason: str, status: int = 1) -> int:
    """The reason, as the last line of the program's output."""
    sys.stdout.flush()
    print(reason, file=sys.stderr, flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
