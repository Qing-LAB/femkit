"""Each engine's hand-over of the mesh stage's mesh, run inside the person's environments
(geometry.md § 8; testing.md § 1): Elmer through ElmerGrid, NGSolve through femkit's own layer,
each by the hand-over declared for the geometry order asked, every group it hands by its name."""

from __future__ import annotations

from pathlib import Path

import pytest

from femkit.core.persist import read_json, write_json
from femkit.definitions import catalogue
from femkit.engines import package_dir
from femkit.engines.stages import documents
from femkit.workflow.graph import handover
from tests.kit import ctx, hand_over, inside, mesh, program, said, template_geometry


def route(engine: str, order: int):
    """The hand-over ``engine`` receives Gmsh's mesh by at geometry ``order`` (geometry.md § 8)."""
    c = ctx()
    name = handover(catalogue.handovers(c), engine, order, catalogue.meshers(c)["gmsh"].writes.values())
    return None if name is None else catalogue.handovers(c)[name]

# A unit square with a point group at its corner, a script of the test's own written to the
# hand-over (geometry.md § 2): a point is a place both hand-overs are asked about.
CORNER = """
import sys
import gmsh
gmsh.initialize()
square = gmsh.model.occ.addRectangle(0, 0, 0, 1, 1)
gmsh.model.occ.synchronize()
sides = [tag for _, tag in gmsh.model.getBoundary([(2, square)], oriented=False)]
corner = [tag for _, tag in gmsh.model.getEntities(0) if max(map(abs, gmsh.model.getValue(0, tag, []))) < 1e-12]
gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [square]), "domain")
gmsh.model.setPhysicalName(1, gmsh.model.addPhysicalGroup(1, sides), "outer")
gmsh.model.setPhysicalName(0, gmsh.model.addPhysicalGroup(0, corner), "corner")
gmsh.write(sys.argv[2])
gmsh.finalize()
"""
CORNER_CONTRACT = documents.make("contract", dimension=2, axis=None, groups={"domain": 2, "outer": 1, "corner": 0},
                                 mesh=None, brep=False)

# Two unit cubes side by side: two bodies, the face between them, their outer faces, an edge
# and a point of the outside — in 3-D, the groups that made ElmerGrid drop every name (measured).
BLOCKS = """
import sys
import gmsh
gmsh.initialize()
a = gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
b = gmsh.model.occ.addBox(1, 0, 0, 1, 1, 1)
gmsh.model.occ.fragment([(3, a)], [(3, b)])
gmsh.model.occ.synchronize()
faces = {d: set(t for _, t in gmsh.model.getBoundary([(3, d)], oriented=False)) for d in (a, b)}
middle = sorted(faces[a] & faces[b])
outer = sorted((faces[a] | faces[b]) - set(middle))
edge = [t for _, t in gmsh.model.getEntities(1) if gmsh.model.occ.getMass(1, t) > 0
        and max(abs(c - v) for c, v in zip(gmsh.model.occ.getCenterOfMass(1, t), (0.5, 0, 0))) < 1e-9]
point = [t for _, t in gmsh.model.getEntities(0) if max(map(abs, gmsh.model.getValue(0, t, []))) < 1e-12]
for dim, tags, name in ((3, [a], "left"), (3, [b], "right"), (2, middle, "middle"), (2, outer, "outside"),
                        (1, edge, "rim"), (0, point, "tip")):
    gmsh.model.setPhysicalName(dim, gmsh.model.addPhysicalGroup(dim, tags), name)
gmsh.write(sys.argv[2])
gmsh.finalize()
"""
BLOCKS_CONTRACT = documents.make("contract", dimension=3, axis=None, groups={
    "left": 3, "right": 3, "middle": 2, "outside": 2, "rim": 1, "tip": 0}, mesh=None, brep=False)


def meshed(work: Path, which: str, order: int) -> dict:
    """Gmsh's `mesh.msh` of the slab template, the corner square or the two blocks, at ``order``,
    in ``work``, passed by the mesh's check: the groups it holds, by name, from its region map."""
    work.mkdir()
    if which == "slab":
        contract = template_geometry("two_material", work)
    else:
        (work / "geometry.py").write_text({"corner": CORNER, "blocks": BLOCKS}[which])
        write_json(work / "inputs.json", documents.make("inputs", definitions={}))
        built = inside("gmsh", ["python", "geometry.py", "inputs.json", "geometry.xao"], work)
        assert built.ok, built.stdout
        contract = {"corner": CORNER_CONTRACT, "blocks": BLOCKS_CONTRACT}[which]
    result = mesh(work, contract, size=0.5 if which == "blocks" else 0.25, order=order, tolerance=1e-9)
    assert result.ok, result.stdout
    return read_json(work / "regions.json")["groups"]


def header_types(folder: Path) -> set[int]:
    """The element types ElmerGrid wrote, from its `mesh.header`: after the counts line and the
    number of types, one type and its count a line."""
    lines = (folder / "mesh.header").read_text().split("\n")
    return {int(line.split()[0]) for line in lines[2:] if line.strip()}


def names(folder: Path) -> set[str]:
    """Every name in ElmerGrid's `mesh.names`, bodies' and boundaries' alike."""
    return {line.split("=")[0].strip("$ ").strip() for line in (folder / "mesh.names").read_text().splitlines()
            if line.startswith("$")}


@pytest.mark.parametrize("order, types", [(1, {202, 303}), (2, {203, 306})])
def test_elmer_receives_every_group_by_its_name_at_its_order(tmp_path, order, types):
    """Fails if Elmer's hand-over loses a group's name — ElmerGrid run otherwise than `14 2`, or
    its names looked for where it does not write them — or the mesh reaches Elmer at another order
    than it was made, though its hand-over declares orders 1 and 2 kept (geometry.md § 8, measured)."""
    regions = meshed(tmp_path / "slab", "slab", order)
    result, chosen = hand_over("elmer", tmp_path / "slab", order)
    assert result.ok, result.stdout
    assert chosen.outputs == ["mesh"] and header_types(tmp_path / "slab" / "mesh") == types
    assert names(tmp_path / "slab" / "mesh") == set(regions)


def test_elmer_receives_a_3d_meshs_bodies_and_faces_by_name_beside_an_edge_and_a_point(tmp_path):
    """Fails if Elmer's hand-over hands ElmerGrid a 3-D mesh's edge or point group — which makes it
    read the mesh as 2-D and drop every body's and face's name (measured) — rather than the bodies
    and faces alone its hand-over keeps, or the mesh stage's mesh loses those groups for the
    other hand-overs (geometry.md § 8)."""
    regions = meshed(tmp_path / "blocks", "blocks", 1)
    assert set(regions) == set(BLOCKS_CONTRACT["groups"])          # every promised group, in the mesh
    result, chosen = hand_over("elmer", tmp_path / "blocks", 1)
    assert result.ok, result.stdout
    assert read_json(tmp_path / "blocks" / "handover.json")["groups"] == {
        "left": 3, "right": 3, "middle": 2, "outside": 2}
    assert names(tmp_path / "blocks" / "mesh") == {"left", "right", "middle", "outside"}
    assert header_types(tmp_path / "blocks" / "mesh") == {303, 504}


def test_a_name_elmergrid_drops_is_refused_naming_it(tmp_path):
    """Fails if Elmer's hand-over passes a mesh whose handed group ElmerGrid did not keep by name —
    a point group, measured, handed here against its hand-over — or fails without naming it
    (geometry.md § 8)."""
    work = tmp_path / "corner"
    meshed(work, "corner", 1)
    write_json(work / "handover.json", documents.make("handover", groups=CORNER_CONTRACT["groups"]))
    chosen = route("elmer", 1)
    result = inside("elmer", ["python", program(package_dir("elmer") / chosen.program, work), "mesh.msh",
                              "handover.json", "mesh"], work)
    assert not result.ok
    assert said(result, "did not keep the name of", "`corner`") and not said(result, "`domain`"), result.stdout


@pytest.mark.parametrize("which", ["slab", "corner"])
def test_ngsolve_receives_every_group_by_its_name_and_its_measure(tmp_path, which):
    """Fails if NGSolve's hand-over loses a group's name — a point of a 2-D mesh among them, which
    Netgen's own region call files among the edges (measured) — or builds a mesh whose regions
    measure otherwise than the region map's: the slab's two layers together exactly 1
    (geometry.md § 8)."""
    regions = meshed(tmp_path / which, which, 1)
    result, chosen = hand_over("ngsolve", tmp_path / which, 1)
    assert result.ok, result.stdout
    (report,) = chosen.outputs
    received = documents.check("report", read_json(tmp_path / which / report))["groups"]
    assert set(received) == set(regions)
    for name, region in regions.items():
        assert received[name]["elements"] == region["elements"], name
        if region["measure"] is not None:
            assert abs(received[name]["measure"] - region["measure"]) <= 1e-12 * region["measure"], name
    if which == "slab":
        assert {n: received[n]["region"] for n in ("low", "high", "middle")} == {
            "low": "material", "high": "material", "middle": "boundary"}
        assert abs(received["low"]["measure"] + received["high"]["measure"] - 1) <= 1e-12


def test_ngsolve_has_no_hand_over_at_order_two_and_its_layer_refuses_a_second_order_mesh(tmp_path):
    """Fails if a hand-over is declared handing NGSolve a second-order mesh — straight, since
    NGSolve cannot curve it (geometry.md § 8, measured) — or if NGSolve's layer, handed one
    anyway, builds it instead of refusing it, naming its cells."""
    assert route("ngsolve", 2) is None
    work = tmp_path / "slab"
    regions = meshed(work, "slab", 2)
    write_json(work / "handover.json", documents.make(
        "handover", groups={n: r["dimension"] for n, r in regions.items()}))
    chosen = route("ngsolve", 1)
    result = inside("ngsolve", ["python", program(package_dir("ngsolve") / chosen.program, work), "mesh.msh",
                                "handover.json", "report.json"], work)
    assert not result.ok and not (work / "report.json").exists()
    assert said(result, "triangle6", "femkit's layer builds"), result.stdout
