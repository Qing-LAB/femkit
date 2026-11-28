"""The geometry stage's check (geometry.md §§ 3, 7, 8), run after the person's script, in the
`gmsh` environment:

    python check_geometry.py CONTRACT GEOMETRY GROUPS CHECKED OUTPUTS [MESH] [BREP]

A program run in the stage's job with `documents.py` beside it (framework.md § 1): it imports the
standard library, Gmsh's Python module and `documents` only.

CONTRACT is a `contract` document — the frame's dimension and axis of revolution, the groups the
component's contract promises, the order of the mesh it declares the script writes too, and
whether the stage writes the shapes as BREP; MESH, given exactly when the contract declares a mesh,
is the mesh the script wrote; BREP, given exactly when the contract document asks for it, is where
the check writes the geometry's shapes as BREP, with Gmsh, for a mesher that reads them — named
beside it and renamed in whole. GROUPS, written once GEOMETRY opens, is a `groups` document: what
the geometry holds, observed (`documents.py` defines each). Each group the script made that the
contract does not promise — a name at another dimension than its promised one among them — is
listed as `unpromised`: reported, never used downstream; an unnamed one is named `unnamed
<dimension>-D group <tag>`. A face's bodies are Gmsh's adjacencies: those it bounds, one for a face
on the outside, two for a face between two bodies; and those it lies inside, embedded, which it
bounds on neither side (measured 2026-11-25 on Gmsh 4.15.2). Which place each group is, read from
these by the vocabulary of places, is femkit's (geometry.md § 7), never this program's.

It passes when every promised group is in the geometry at its dimension and holds a piece, the
geometry holds nothing of a dimension above its frame's, and, for a frame with an axis of
revolution, the drawing lies on one side of that axis (geometry.md § 3); and, for a declared mesh,
when every promised group is a named group of it at its dimension holding elements. It writes its
two records (`documents.judged`): its verdict, CHECKED, and, when it passed, OUTPUTS, the SHA-256
of GEOMETRY, GROUPS, and MESH and BREP where given (jobs.md § 2). It exits 0 when it passed,
otherwise 1, its last line the reason, naming each group that does not hold; a CONTRACT not of its
shape, or files given otherwise than it says, fail it with that reason, exit 2; and a call naming
no CHECKED exits 2, writing nothing.
"""

import os
import sys

import gmsh

import documents

#: The coordinate across each axis of revolution, by its index in a point: the axis `y` is the
#: line x = 0, so a drawing on one side of it has all its x on one side of 0; the axis `x`, its y.
ACROSS = {"x": 1, "y": 0}


USAGE = "usage: python check_geometry.py CONTRACT GEOMETRY GROUPS CHECKED OUTPUTS [MESH] [BREP]"


def main(argv: list[str]) -> int:
    if len(argv) < 5:
        return stop(USAGE, 2)
    contract_file, geometry, groups_file, checked, outputs, *rest = argv
    try:
        contract = documents.read(contract_file, "contract")
        if len(rest) != (contract["mesh"] is not None) + contract["brep"]:
            raise documents.Malformed(f"{USAGE}: MESH given exactly when the contract declares a mesh, BREP when it "
                                      "asks for the shapes as BREP")
    except documents.Malformed as exc:
        return verdict(checked, outputs, str(exc), [], 2)
    mesh = rest[0] if contract["mesh"] is not None else None
    brep = rest[-1] if contract["brep"] else None
    if not os.path.isfile(geometry):
        return verdict(checked, outputs, f"the script wrote no {os.path.basename(geometry)}", [])

    # No option file of the person's is read, so the check sees what any run sees; Gmsh's own
    # messages stay out of the log, whose last line is the reason.
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        try:
            gmsh.open(geometry)
        except Exception as exc:
            return verdict(checked, outputs, f"{os.path.basename(geometry)} does not open in Gmsh: {exc}", [])
        observed = observe(contract["dimension"])
        crossed = crossing(contract["axis"]) if contract["axis"] is not None else None
        if brep is not None:
            write_brep(brep)
        meshed = in_mesh(mesh, contract["groups"]) if mesh is not None else []
    finally:
        gmsh.finalize()

    promised = contract["groups"]
    made = observed.pop("made")
    problems = [f"the geometry holds {d}-D pieces; its frame is {contract['dimension']}-D"
                for d in observed.pop("above")]
    problems += [crossed] if crossed else []
    groups, unpromised = {}, []
    for (name, dimension), pieces in sorted(made.items()):
        if promised.get(name) == dimension:
            groups[name] = {"dimension": dimension, "pieces": pieces}
        else:
            unpromised.append({"name": name, "dimension": dimension, "pieces": pieces})
    for name, dimension in promised.items():
        if name in groups:
            if not groups[name]["pieces"]:
                problems.append(f"`{name}` is in the geometry and holds nothing")
            continue
        other = sorted(d for n, d in made if n == name)
        problems.append(f"`{name}` is a group of dimension {' and '.join(map(str, other))} in the geometry; its "
                        f"contract promises {dimension}" if other else f"`{name}` is promised and not in the geometry")

    documents.write(groups_file, "groups", documents.make("groups", dimension=contract["dimension"], groups=groups,
                                                          unpromised=unpromised, **observed))
    if unpromised:
        print("made by the script and not promised, so never used downstream: "
              + ", ".join(f"`{g['name']}` ({g['dimension']}-D)" for g in unpromised), flush=True)
    return verdict(checked, outputs, "; ".join(problems + meshed) or None,
                   [f for f in (geometry, groups_file, mesh, brep) if f is not None])


def write_brep(brep: str) -> None:
    """The open geometry's shapes written as BREP, for a mesher that reads them (geometry.md § 8):
    by Gmsh, whose format it is, to a name beside BREP carrying its extension, renamed in whole."""
    part = os.path.join(os.path.dirname(os.path.abspath(brep)), ".geometry.part.brep")
    gmsh.write(part)
    os.replace(part, brep)


def in_mesh(mesh: str, promised: dict) -> list[str]:
    """What does not hold of the mesh the script wrote (geometry.md § 3): every promised group a
    named group of it at its promised dimension, holding elements — each that does not, named."""
    if not os.path.isfile(mesh):
        return [f"the script wrote no {os.path.basename(mesh)}, which its contract declares"]
    gmsh.clear()   # the geometry, observed, leaves; the mesh is read alone
    try:
        gmsh.open(mesh)
    except Exception as exc:
        return [f"{os.path.basename(mesh)} does not open in Gmsh: {exc}"]
    elements: dict[tuple[str, int], int] = {}
    for d, tag in gmsh.model.getPhysicalGroups():
        key = (gmsh.model.getPhysicalName(d, tag), d)
        elements[key] = elements.get(key, 0) + sum(
            len(ts) for e in gmsh.model.getEntitiesForPhysicalGroup(d, tag) for ts in gmsh.model.mesh.getElements(d, e)[1])
    problems = []
    for name, dimension in promised.items():
        if (name, dimension) not in elements:
            problems.append(f"`{name}` is promised and not a group of dimension {dimension} in the script's mesh")
        elif elements[(name, dimension)] == 0:
            problems.append(f"`{name}` is in the script's mesh and holds no element")
    return problems


def verdict(checked: str, outputs: str, reason: str | None, files: list[str], status: int = 1) -> int:
    """The check's two records written — its verdict and, when it passed, each output's SHA-256
    (`documents.judged`) — and its exit status: 0 when it passed, else ``status``, the reason its
    last line."""
    documents.judged(checked, outputs, reason, files)
    return 0 if reason is None else stop(reason, status)


def observe(dimension: int) -> dict:
    """What the open geometry holds: each group by name and dimension with its pieces, every body,
    every face with the bodies it bounds and those it is embedded in, and any dimension above the
    frame's."""
    made: dict[tuple[str, int], list[dict]] = {}
    for d, tag in gmsh.model.getPhysicalGroups():
        name = gmsh.model.getPhysicalName(d, tag) or f"unnamed {d}-D group {tag}"
        pieces = made.setdefault((name, d), [])
        for entity in gmsh.model.getEntitiesForPhysicalGroup(d, tag):
            pieces.append({"dimension": d, "tag": int(entity),
                           "measure": gmsh.model.occ.getMass(d, int(entity)) if d > 0 else None})
    bodies = sorted(int(t) for _, t in gmsh.model.getEntities(dimension))
    inside: dict[int, list[int]] = {}
    for body in bodies:
        for d, face in gmsh.model.mesh.getEmbedded(dimension, body):
            if d == dimension - 1:
                inside.setdefault(int(face), []).append(body)
    faces = []
    for _, face in gmsh.model.getEntities(dimension - 1):
        up, _ = gmsh.model.getAdjacencies(dimension - 1, face)
        faces.append({"tag": int(face), "bodies": sorted(int(b) for b in up), "embedded_in": inside.get(int(face), [])})
    faces.sort(key=lambda f: f["tag"])
    return {"made": made, "above": sorted({d for d, _ in gmsh.model.getEntities() if d > dimension}),
            "bodies": bodies, "faces": faces}


def crossing(axis: str) -> str | None:
    """The reason the drawing crosses its axis of revolution, or None when it lies on one side of
    it — touching it is lying on one side. Read from Gmsh's bounding box of the whole drawing,
    which lies BOX_SLACK beyond the drawing itself."""
    i = ACROSS[axis]
    box = gmsh.model.getBoundingBox(-1, -1)
    low, high = box[i], box[i + 3]
    if low >= -BOX_SLACK or high <= BOX_SLACK:
        return None
    coordinate = "xyz"[i]
    return (f"the drawing crosses its axis of revolution `{axis}`: its {coordinate} runs from {low:.10g} to "
            f"{high:.10g}, on both sides of {coordinate} = 0")


#: How far Gmsh's bounding box of a curve or a surface lies beyond it, in the frame's unit:
#: OpenCASCADE's own tolerance, added on every side. Measured 2026-11-25 on Gmsh 4.15.2: a unit
#: square's edge at x = 0 reads from x = -1e-7, a disk touching x = 0 likewise, a point exactly.
#: Gmsh's tighter box (`Geometry.OCCBoundsUseStl`) is drawn from a triangulation that cuts inside
#: a curve — the same disk read from x = 1.07e-4 — so a bulge across the axis could hide in it.
BOX_SLACK = 1e-7


def stop(reason: str, status: int = 1) -> int:
    """The reason, as the last line of the check's output (jobs.md § 2)."""
    sys.stdout.flush()
    print(reason, file=sys.stderr, flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
