"""Elmer's hand-over (geometry.md § 8): the mesh stage's mesh converted for Elmer by ElmerGrid, and
checked, inside Elmer's environment:

    python handover.py MESH HANDOVER OUT

MESH is the mesh stage's mesh, Gmsh's MSH 2.2 text format; HANDOVER a `handover` document, the
groups Elmer's hand-over hands it — its bodies and faces (`documents.py`). It writes MESH with those
groups alone, `elmer.msh`, beside OUT, runs `ElmerGrid 14 2 elmer.msh -out OUT`, and finds every
handed group's name in the converted mesh's `OUT/mesh.names`: a group of the mesh's dimension among
its bodies, one of one dimension less among its boundaries.

Why only those (measured 2026-11-25, ElmerGrid of Elmer 26.2): ElmerGrid drops a point group's
name, and in 3-D an edge or a point group makes it read the mesh as 2-D and drop every body's and
face's name. A group of a lower dimension stays in the mesh stage's mesh for the hand-overs that
keep it; a statement on one in Elmer is the match's to show, before anything runs (models.md § 6.2).
OUT is named without a dot, since ElmerGrid cuts an output name at its first dot (`-out a.b`
writes `a`; measured 2026-11-25).

A program run in the solve's job with `documents.py` and `process.py` beside it
(framework.md § 1): it imports the standard library, what the `elmer` environment holds — meshio
and NumPy — `documents`, and `process`, through which it starts ElmerGrid.

It exits 0 when every handed group's name is there; otherwise 1, its last line the reason naming
each group ElmerGrid did not keep. A malformed call or HANDOVER exits 2.
"""

import os
import re
import sys

import meshio
import numpy

import documents
import process

#: The two parts of ElmerGrid's `mesh.names`, by the comment line that opens each.
PARTS = {"names for bodies": "bodies", "names for boundaries": "boundaries"}
NAME = re.compile(r"^\$\s*(.+?)\s*=\s*\d+\s*$")
#: The mesh ElmerGrid is given, beside OUT: MESH with the handed groups alone.
HANDED = "elmer.msh"


def handed(mesh: str, groups: dict, path: str) -> None:
    """MESH with only the elements of ``groups``, written whole to ``path`` as MSH 2.2 text, its
    nodes as they are."""
    msh = meshio.read(mesh, file_format="gmsh")
    tags = {(int(dim), int(tag)) for name, (tag, dim) in msh.field_data.items() if name in groups}
    cells, data = [], {key: [] for key in msh.cell_data}
    for i, block in enumerate(msh.cells):
        keep = numpy.isin(msh.cell_data["gmsh:physical"][i], [t for d, t in tags if d == block.dim])
        if keep.any():
            cells.append(meshio.CellBlock(block.type, block.data[keep]))
            for key, values in data.items():
                values.append(msh.cell_data[key][i][keep])
    part = f"{path}.part"
    meshio.write(part, meshio.Mesh(msh.points, cells, cell_data=data,
                                   field_data={n: v for n, v in msh.field_data.items() if n in groups}),
                 file_format="gmsh22", binary=False)
    os.replace(part, path)


def kept(names_file: str) -> dict[str, set[str]]:
    """The names ElmerGrid wrote, in each part of `mesh.names`."""
    found: dict[str, set[str]] = {part: set() for part in PARTS.values()}
    part = None
    with open(names_file, encoding="utf-8") as f:
        for line in f:
            if line.startswith("!"):
                part = next((p for opening, p in PARTS.items() if opening in line), None)
            elif part and (match := NAME.match(line.strip())):
                found[part].add(match.group(1))
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        return stop("usage: python handover.py MESH HANDOVER OUT", 2)
    mesh, handover_file, out = argv
    if "." in os.path.basename(out):
        return stop(f"{out}: ElmerGrid cuts an output name at its first dot; name it without one", 2)
    try:
        groups = documents.read(handover_file, "handover")["groups"]
    except documents.Malformed as exc:
        return stop(str(exc), 2)
    given = os.path.join(os.path.dirname(os.path.abspath(out)), HANDED)
    handed(mesh, groups, given)
    # No time limit of its own: the run's wall time bounds it, and `job cancel` stops it.
    result = process.run(["ElmerGrid", "14", "2", given, "-out", out])
    print(result.stdout, result.stderr, sep="", end="", flush=True)   # into the run's log
    if not result.ok:
        return stop(f"ElmerGrid exited with {result.returncode}")
    names_file = os.path.join(out, "mesh.names")
    if not os.path.isfile(names_file):
        return stop(f"ElmerGrid wrote no {names_file}")
    found = kept(names_file)
    dimension = max(groups.values(), default=0)
    lost = sorted(name for name, d in groups.items()
                  if name not in found["bodies" if d == dimension else "boundaries"])
    if lost:
        return stop(f"ElmerGrid did not keep the name of {', '.join(f'`{n}`' for n in lost)} in {names_file}")
    return 0


def stop(reason: str, status: int = 1) -> int:
    """The reason, as the last line of the program's output."""
    sys.stdout.flush()
    print(reason, file=sys.stderr, flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
