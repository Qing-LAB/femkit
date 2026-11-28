"""The `gmsh` environment's check (definitions.md § 4.7), a command check run inside it:

    python -m femkit.engines.stages.environment_check WORK

The Laplace square built from its template's script, as the geometry stage runs it; checked by the
geometry's check against the template's contract; meshed by Gmsh's meshing; judged by the mesh's
check; and each region's measure in the mesh compared with its measure in the geometry
(geometry.md §§ 2, 5, 7). It runs femkit's own stage programs as a run does — each copied into WORK
with the modules it imports beside it (framework.md § 1) — and writes the common summary, read by
the generic `summary` reader (definitions.md § 5.3):

- `regions`: the groups the mesh holds;
- `largest_difference`: the largest relative difference between a region's measure in the mesh
  and in the geometry.

A program that fails ends the check with its reason, its log in WORK.

It runs inside the environment, which holds none of femkit's libraries, so it cannot read the
template through the definitions' loader nor its parameter through the unit table: it finds the
template beside femkit's own data and hands the script the square's side as the template's project
file states it, 1 m, in its frame's unit, metres.
"""

from __future__ import annotations

import shutil
import sys
import tomllib
from pathlib import Path

from femkit.core import process
from femkit.engines import summary
from femkit.engines.stages import documents

HERE = Path(__file__).resolve().parent
SQUARE = HERE.parent.parent / "data" / "templates" / "laplace_square" / "components" / "square"
INPUTS = {"side": 1.0}   # the template's `side`, 1 m, in its frame's unit, metres
# A recipe of the check's own: straight sides, so each measure in the mesh is the geometry's to
# rounding.
RECIPE = {"size": 0.25, "order": 1, "tolerance": 1e-9, "growth": None, "quality": None, "sizes": {}}
TIMEOUT = 300


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m femkit.engines.stages.environment_check WORK", file=sys.stderr)
        return 2
    import gmsh  # the environment's own, the version this check ran

    work = Path(argv[0])
    with open(SQUARE / "component.toml", "rb") as f:
        contract = tomllib.load(f)
    dimension, groups = contract["frame"]["dimension"], contract["groups"]
    for name, kind, fields in (
            ("inputs.json", "inputs", {"definitions": INPUTS}),
            ("contract.json", "contract", {"dimension": dimension, "axis": None, "groups": groups, "mesh": None,
                                           "brep": False}),
            ("recipe.json", "recipe", {"dimension": dimension, "groups": groups, **RECIPE})):
        documents.write(str(work / name), kind, documents.make(kind, **fields))
    for source in (SQUARE / "geometry.py", HERE / "check_geometry.py", HERE / "mesh.py", HERE / "check_mesh.py",
                   Path(documents.__file__), Path(process.__file__)):
        shutil.copyfile(source, work / source.name)
    for program, argv_ in (
            ("geometry", ["geometry.py", "inputs.json", "geometry.xao"]),
            ("check_geometry", ["check_geometry.py", "contract.json", "geometry.xao", "groups.json",
                                "geometry-checked.json", "geometry-outputs.json"]),
            ("mesh", ["mesh.py", "recipe.json", "geometry.xao", "mesh.msh", "regions.json"]),
            ("check_mesh", ["check_mesh.py", "recipe.json", "regions.json", "mesh-checked.json", "mesh-outputs.json",
                            "mesh.msh"])):
        result = process.run([sys.executable, *argv_], cwd=work, timeout=TIMEOUT, log=work / f"{program}.log")
        if not result.ok:
            reason = result.stdout.strip().splitlines()[-1:] or ["no output"]
            print(f"{program} failed ({result.returncode}): {reason[0]}", file=sys.stderr)
            return 1
    regions = documents.read(str(work / "regions.json"), "regions")["groups"]
    summary.write(work, {"regions": len(regions),
                         "largest_difference": max(r["difference"] for r in regions.values())},
                  {"gmsh": gmsh.__version__})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
