"""The meshing path a study uses: gmsh meshes a unit square, ElmerGrid converts it for Elmer.

Summary quantities, from ElmerGrid's `mesh.header`: nodes, elements, boundary_elements; its
version entry, Elmer's, as `ElmerSolver -v` states it — the Elmer this check ran
(definitions.md § 5.3).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from femkit.core import process
from femkit.engines import summary
from femkit.engines.elmer import ENGINE, read_version

GEOMETRY = Path(__file__).with_name("square.geo")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m femkit.engines.elmer.checks.mesh WORK", file=sys.stderr)
        return 2
    work = Path(argv[0])
    geo, msh, out = work / GEOMETRY.name, work / "square.msh", work / "square"
    shutil.copyfile(GEOMETRY, geo)
    for argv_ in (["gmsh", "-2", str(geo), "-format", "msh2", "-o", str(msh)],
                  ["ElmerGrid", "14", "2", str(msh), "-out", str(out)]):
        result = process.run(argv_, cwd=work, timeout=300, log=work / f"{argv_[0]}.log")
        if not result.ok:
            print(f"{argv_[0]} failed ({result.returncode}):\n{result.stdout}", file=sys.stderr)
            return 1
    header = out / "mesh.header"
    if not header.is_file():
        print("ElmerGrid wrote no mesh.header", file=sys.stderr)
        return 1
    stated = process.run(["ElmerSolver", "-v"], cwd=work, timeout=120)
    version = read_version(stated.stdout, stated.stderr)
    if version is None:
        print(f"ElmerSolver -v stated no version ({stated.returncode}):\n{stated.stdout}{stated.stderr}",
              file=sys.stderr)
        return 1
    nodes, elements, boundary = (int(v) for v in header.read_text(encoding="utf-8").split()[:3])
    summary.write(work, {"nodes": nodes, "elements": elements, "boundary_elements": boundary}, {ENGINE: version})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
