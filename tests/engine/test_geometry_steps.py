"""The geometry's check, Gmsh's meshing, the pass-through and the mesh's check, run inside the
person's `gmsh` environment (geometry.md §§ 3, 5, 6, 7, 8; workflow.md § 2.3; testing.md § 1): on the
templates' geometries, and on shapes whose measures are known exactly."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from femkit.core.persist import read_json, write_json
from femkit.definitions import catalogue
from femkit.engines.stages import documents
from femkit.geometry.steps import places_of
from tests.kit import ctx, files, inside, mesh, program, said, template_geometry

# A unit disk, a script of the test's own written to the hand-over (geometry.md § 2): the body
# `body`, its circle `rim`. Its measures are known exactly: π and 2π.
DISK = """
import json, sys
import gmsh
radius = json.load(open(sys.argv[1]))["definitions"]["radius"]
gmsh.initialize()
disk = gmsh.model.occ.addDisk(0, 0, 0, radius, radius)
gmsh.model.occ.synchronize()
rim = [tag for _, tag in gmsh.model.getBoundary([(2, disk)], oriented=False)]
gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [disk]), "body")
gmsh.model.setPhysicalName(1, gmsh.model.addPhysicalGroup(1, rim), "rim")
gmsh.write(sys.argv[2])
gmsh.finalize()
"""
DISK_CONTRACT = documents.make("contract", dimension=2, axis=None, groups={"body": 2, "rim": 1}, mesh=None, brep=False)
# The unit disk again, its script meshing it too at order 2 and writing MESH (geometry.md § 3); with
# `forget`, its circle's group is taken out before the mesh is written.
DISK_MESHED = DISK.replace("gmsh.write(sys.argv[2])\n", """gmsh.write(sys.argv[2])
gmsh.option.setNumber("Mesh.MeshSizeMax", 0.2)
gmsh.model.mesh.generate(2)
gmsh.model.mesh.setOrder(2)
if "forget" in sys.argv[4:]:
    gmsh.model.removePhysicalGroups([(1, t) for _, t in gmsh.model.getPhysicalGroups(1)])
gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
gmsh.option.setNumber("Mesh.Binary", 0)
gmsh.write(sys.argv[3])
""")


def disk(work: Path) -> dict:
    (work / "geometry.py").write_text(DISK)
    write_json(work / "inputs.json", documents.make("inputs", definitions={"radius": 1.0}))
    assert inside("gmsh", ["python", "geometry.py", "inputs.json", "geometry.xao"], work).ok
    return DISK_CONTRACT


def check(work: Path, contract: dict, *files: str):
    """The geometry's check of `<work>/geometry.xao` against ``contract``, its verdict into
    `checked.json` and its outputs' record into `outputs.json`; ``files``, the script's mesh and the
    BREP where the contract declares or asks for them."""
    write_json(work / "contract.json", contract)
    return inside("gmsh", ["python", program(files().programs_folder() / "check_geometry.py", work), "contract.json", "geometry.xao",
                           "groups.json", "checked.json", "outputs.json", *files], work)


def verdict(work: Path) -> dict:
    """A check's verdict, a `checked` document."""
    return documents.check("checked", read_json(work / "checked.json"))


def observed(work: Path) -> dict:
    """The check's `groups.json`, a `groups` document."""
    return documents.check("groups", read_json(work / "groups.json"))


def faces_of(groups: dict, name: str) -> list[dict]:
    """The faces a group holds, as the check observed them."""
    tags = {p["tag"] for p in groups["groups"][name]["pieces"]}
    return [f for f in groups["faces"] if f["tag"] in tags]


def test_the_two_material_slab_holds_its_contract_and_its_middle_lies_between_its_layers(tmp_path):
    """Fails if the geometry's check refuses a template's own geometry, or what it observes
    places the slab's `middle` anywhere but between its two layers — the place a physics' interface
    condition must find (geometry.md § 7, measured) — or an outer side anywhere but on the outside
    of one layer, read by the vocabulary of places."""
    contract = template_geometry("two_material", tmp_path)
    result = check(tmp_path, contract)
    assert result.ok, result.stdout
    groups = observed(tmp_path)
    assert set(groups["groups"]) == set(contract["groups"]) and groups["unpromised"] == []
    (middle,) = faces_of(groups, "middle")
    assert len(middle["bodies"]) == 2 and middle["embedded_in"] == []
    assert places_of(catalogue.places(ctx()), groups) == {
        "low": ["body"], "high": ["body"], "middle": ["interface"],
        "left": ["outer_boundary"], "right": ["outer_boundary"], "sides": ["outer_boundary"]}
    assert sorted(p["tag"] for b in ("low", "high") for p in groups["groups"][b]["pieces"]) == groups["bodies"]


def test_the_laplace_squares_sides_are_outer_faces(tmp_path):
    """Fails if the geometry's check refuses the Laplace template's own geometry, or does not
    observe each of its sides as a face of its one body on the outside, measured as the side it is
    (geometry.md § 7)."""
    contract = template_geometry("laplace_square", tmp_path)
    result = check(tmp_path, contract)
    assert result.ok, result.stdout
    groups = observed(tmp_path)
    for side in ("left", "right", "sides"):
        faces = faces_of(groups, side)
        assert faces and all(f["bodies"] == groups["bodies"] and not f["embedded_in"] for f in faces), side
    assert {n: p for n, p in places_of(catalogue.places(ctx()), groups).items() if n != "domain"} == {
        "left": ["outer_boundary"], "right": ["outer_boundary"], "sides": ["outer_boundary"]}
    assert [p["measure"] for p in groups["groups"]["left"]["pieces"]] == [1.0]


def test_a_promised_group_the_script_does_not_make_fails_the_check_naming_it(tmp_path):
    """Fails if the geometry's check passes a geometry missing a group its contract promises,
    or holding it at another dimension, or fails without naming each such group in its last line
    (geometry.md § 3)."""
    contract = template_geometry("laplace_square", tmp_path)
    contract["groups"] |= {"ghost": 1, "left": 2}
    result = check(tmp_path, contract)
    assert not result.ok
    assert said(result, "`ghost` is promised and not in the geometry",
                "`left` is a group of dimension 1 in the geometry; its contract promises 2"), result.stdout
    assert {"name": "left", "dimension": 1} in [{k: g[k] for k in ("name", "dimension")}
                                                 for g in observed(tmp_path)["unpromised"]]


def test_a_geometry_holding_more_dimensions_than_its_frame_fails_the_check(tmp_path):
    """Fails if the geometry's check passes a geometry holding a volume under a 2-D frame —
    a drawing no physics of the frame means (geometry.md § 3)."""
    (tmp_path / "geometry.py").write_text(
        "import sys, gmsh\ngmsh.initialize()\nbox = gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)\n"
        "gmsh.model.occ.synchronize()\n"
        "gmsh.model.setPhysicalName(3, gmsh.model.addPhysicalGroup(3, [box]), 'domain')\n"
        "gmsh.write(sys.argv[2])\ngmsh.finalize()\n")
    write_json(tmp_path / "inputs.json", documents.make("inputs", definitions={}))
    assert inside("gmsh", ["python", "geometry.py", "inputs.json", "geometry.xao"], tmp_path).ok
    result = check(tmp_path, documents.make("contract", dimension=2, axis=None, groups={"domain": 3}))
    assert not result.ok
    assert said(result, "the geometry holds 3-D pieces; its frame is 2-D"), result.stdout


def test_a_drawing_on_one_side_of_its_axis_of_revolution_passes_and_one_across_it_fails(tmp_path):
    """Fails if the geometry's check refuses a drawing that touches its axis of revolution and
    lies on one side of it — the Laplace square, along x = 0 and y = 0, which Gmsh's box reaches
    1e-7 past (measured) — or passes one lying across it, the unit disk about the origin, or fails
    without saying so (geometry.md § 3)."""
    contract = template_geometry("laplace_square", tmp_path)
    for axis in ("x", "y"):
        result = check(tmp_path, contract | {"axis": axis})
        assert result.ok, (axis, result.stdout)
    across = tmp_path / "across"
    across.mkdir()
    result = check(across, disk(across) | {"axis": "y"})
    assert not result.ok
    assert said(result, "the drawing crosses its axis of revolution `y`", "on both sides of x = 0"), result.stdout


def test_a_disk_meshed_at_order_two_keeps_its_area_and_at_order_one_does_not(tmp_path):
    """Fails if a second-order mesh of the unit disk measures beyond 1e-5 of π and 2π, relative —
    its curved elements measured as straight, by Gmsh's per-element size rather than over each
    element's own shape (geometry.md § 5, measured: within 3.1e-6) — or a first-order one within
    it, the measure then reading no curvature at all."""
    contract = disk(tmp_path)
    for order, tolerance in ((2, 1e-5), (1, 1e-2)):
        work = tmp_path / f"order-{order}"
        work.mkdir()
        (work / "geometry.xao").write_bytes((tmp_path / "geometry.xao").read_bytes())
        result = mesh(work, contract, size=0.2, order=order, tolerance=tolerance)
        assert result.ok, result.stdout
        regions = documents.check("regions", read_json(work / "regions.json"))["groups"]
        error = {"body": abs(regions["body"]["measure"] - math.pi) / math.pi,
                 "rim": abs(regions["rim"]["measure"] - 2 * math.pi) / (2 * math.pi)}
        if order == 2:
            assert max(error.values()) < 1e-5, error
        else:
            assert min(error.values()) > 1e-5, error


def test_a_size_on_a_group_refines_the_mesh_near_it(tmp_path):
    """Fails if a recipe's size on a named group leaves the mesh near it as coarse as elsewhere —
    the size field not built, or not applied — or refines it away from it (geometry.md § 6)."""
    contract = template_geometry("laplace_square", tmp_path)
    result = mesh(tmp_path, contract, size=0.2, order=1, tolerance=1e-9, growth=0.5, sizes={"left": 0.02})
    assert result.ok, result.stdout
    regions = read_json(tmp_path / "regions.json")["groups"]
    assert regions["left"]["elements"] >= 0.8 / 0.02             # about one element per 0.02 along it
    assert regions["right"]["elements"] <= 1 / 0.2 + 1           # the largest size, far from it


def test_a_measure_beyond_the_recipes_tolerance_is_refused_naming_its_group(tmp_path):
    """Fails if the mesh's check passes a mesh whose group measures beyond the recipe's tolerance
    from the geometry, or fails without naming the group (geometry.md § 5)."""
    contract = disk(tmp_path)
    result = mesh(tmp_path, contract, size=0.2, order=2, tolerance=1e-9)
    assert not result.ok
    assert said(result, "`body` measures", "`rim` measures", "beyond the recipe's tolerance"), result.stdout
    assert read_json(tmp_path / "regions.json")["groups"]["body"]["difference"] > 1e-9   # what it measured, kept


def test_an_element_below_the_recipes_quality_is_refused_naming_its_group(tmp_path):
    """Fails if the mesh's check passes a mesh holding an element below the recipe's quality, or fails
    without naming the body that holds it (geometry.md § 5)."""
    contract = disk(tmp_path)
    result = mesh(tmp_path, contract, size=0.2, order=1, tolerance=1e-2, quality=0.99)
    assert not result.ok
    assert said(result, "`body` holds an element of quality", "below the recipe's 0.99"), result.stdout


def test_the_mesh_is_written_as_the_type_gmshs_definition_says_it_writes(tmp_path):
    """Fails if Gmsh's meshing writes its mesh in a format of its own choosing rather than the type
    its definition declares it writes — `mesh/msh-2.2`, MSH 2.2 as text, the one every hand-over
    reads (workflow.md § 2.2; geometry.md §§ 5, 8)."""
    contract = template_geometry("laplace_square", tmp_path)
    assert mesh(tmp_path, contract, size=0.5, order=1, tolerance=1e-9).ok
    assert catalogue.meshers(ctx())["gmsh"].writes["mesh"] == "mesh/msh-2.2"
    assert (tmp_path / "mesh.msh").read_text().split("\n")[:2] == ["$MeshFormat", "2.2 0 8"]


def test_the_geometry_check_records_what_passed_and_writes_the_shapes_as_brep_when_asked(tmp_path):
    """Fails if the geometry's check passes without its verdict, or without the SHA-256 of each
    output — the geometry, its groups, and the BREP it was asked for — which a later stage's launch
    checks what it shares against; or writes no BREP Gmsh opens to the same shapes (jobs.md § 2;
    geometry.md § 8: "the geometry stage also writes its shapes as BREP")."""
    contract = template_geometry("laplace_square", tmp_path)
    result = check(tmp_path, contract | {"brep": True}, "geometry.brep")
    assert result.ok, result.stdout
    assert verdict(tmp_path) == {"schema": 1, "passed": True, "reason": None}
    files = ("geometry.xao", "groups.json", "geometry.brep")
    assert read_json(tmp_path / "outputs.json")["files"] == {
        f: hashlib.sha256((tmp_path / f).read_bytes()).hexdigest() for f in files}
    (tmp_path / "count.py").write_text("import sys, gmsh\ngmsh.initialize()\ngmsh.open(sys.argv[1])\n"
                                       "print(len(gmsh.model.getEntities(2)), len(gmsh.model.getEntities(1)))\n")
    shapes = [inside("gmsh", ["python", "count.py", f], tmp_path).stdout.split()[-2:] for f in files[::2]]
    assert shapes[0] == shapes[1] == ["1", "4"], shapes


def test_a_mesh_the_script_writes_is_checked_for_every_promised_group(tmp_path):
    """Fails if the geometry's check passes a mesh the contract declares that lacks a promised
    group, or fails without naming it; or refuses one holding every promised group, or records it
    without its SHA-256 (geometry.md § 3: "after the script runs, the check finds each promised
    group in it")."""
    contract = DISK_CONTRACT | {"mesh": 2}
    (tmp_path / "geometry.py").write_text(DISK_MESHED)
    write_json(tmp_path / "inputs.json", documents.make("inputs", definitions={"radius": 1.0}))
    for argv, passes in ((["forget"], False), ([], True)):
        built = inside("gmsh", ["python", "geometry.py", "inputs.json", "geometry.xao", "mesh.msh", *argv], tmp_path)
        assert built.ok, built.stdout
        result = check(tmp_path, contract, "mesh.msh")
        assert result.ok == passes, result.stdout
    assert verdict(tmp_path)["passed"] and "mesh.msh" in read_json(tmp_path / "outputs.json")["files"]


def test_the_pass_through_passes_the_scripts_mesh_on_unchanged_and_maps_it_as_every_mesher_does(tmp_path):
    """Fails if the pass-through changes the mesh the script wrote, or maps it otherwise than every
    mesher's region map — each promised group by name, its measure over each element's own shape,
    the unit disk at order 2 within 1e-5 of π and 2π, the mesh's own order — or the one mesh check
    refuses it (workflow.md § 2.3: "passes it on unchanged and writes its region map from it and
    `groups.json`, under the same check as any mesher's"; geometry.md § 5)."""
    contract = DISK_CONTRACT | {"mesh": 2}
    (tmp_path / "geometry.py").write_text(DISK_MESHED)
    write_json(tmp_path / "inputs.json", documents.make("inputs", definitions={"radius": 1.0}))
    assert inside("gmsh", ["python", "geometry.py", "inputs.json", "geometry.xao", "given.msh"], tmp_path).ok
    assert check(tmp_path, contract, "given.msh").ok
    passed = inside("gmsh", ["python", program(files().programs_folder() / "pass_mesh.py", tmp_path), "given.msh", "groups.json",
                             "mesh.msh", "regions.json"], tmp_path)
    assert passed.ok, passed.stdout
    assert (tmp_path / "mesh.msh").read_bytes() == (tmp_path / "given.msh").read_bytes()
    regions = documents.check("regions", read_json(tmp_path / "regions.json"))
    assert regions["order"] == 2 and set(regions["groups"]) == {"body", "rim"}
    assert abs(regions["groups"]["body"]["measure"] - math.pi) / math.pi < 1e-5
    assert abs(regions["groups"]["rim"]["measure"] - 2 * math.pi) / (2 * math.pi) < 1e-5
    write_json(tmp_path / "recipe.json", documents.make(
        "recipe", dimension=2, groups=contract["groups"], size=0.2, order=2, tolerance=1e-5, growth=None,
        quality=None, sizes={}))
    judged = inside("gmsh", ["python", program(files().programs_folder() / "check_mesh.py", tmp_path), "recipe.json", "regions.json",
                             "checked.json", "outputs.json", "mesh.msh"], tmp_path)
    assert judged.ok, judged.stdout


def test_the_gmsh_environments_own_check_passes(tmp_path):
    """Fails if the `gmsh` environment's declared check — the Laplace square built from its
    template's script, checked, meshed, each region's measure against the geometry's — does not
    pass as `env validate` would run it (definitions.md § 4.7)."""
    from femkit.envs import checks
    r = checks.runner(ctx(), "gmsh")
    (declared,) = r.env.checks
    (step, _) = checks.steps(r, [declared])
    outcome = checks.run_check(r, declared, step.argv, tmp_path / declared.id)
    assert outcome.outcome == "passed", (outcome.reason, Path(outcome.log).read_text()[-2000:])
