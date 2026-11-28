"""A distributed scalar solve through one linear-algebra backend: MUMPS or Hypre.

H1 order 1 on the unit cube (maxh 0.35), (grad u, grad v) + (u, v) = (x, v), Dirichlet on
every boundary; MUMPS as the direct inverse, Hypre as CG's preconditioner.

Summary quantities: ranks, degrees_of_freedom, relative_residual, solution_l2_norm.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from femkit.engines import summary
from femkit.engines.ngsolve.checks.common import projected, relative_residual, start, versions

BACKENDS = ("mumps", "hypre")


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in BACKENDS or not argv[2].isdigit():
        print("usage: python -m femkit.engines.ngsolve.checks.linear_backend WORK {mumps|hypre} THREADS",
              file=sys.stderr)
        return 2
    work, backend = Path(argv[0]), argv[1]
    comm = start(int(argv[2]))

    import netgen.meshing
    from netgen.csg import unit_cube
    from ngsolve import BilinearForm, GridFunction, H1, LinearForm, Mesh, Norm, Preconditioner, TaskManager, dx, grad, x
    from ngsolve.krylovspace import CGSolver

    if comm.rank == 0:
        mesh = Mesh(unit_cube.GenerateMesh(maxh=0.35).Distribute(comm))
    else:
        mesh = Mesh(netgen.meshing.Mesh.Receive(comm))
    comm.Barrier()

    space = H1(mesh, order=1, dirichlet=".*")
    trial, test = space.TnT()
    form = BilinearForm(space)
    form += (grad(trial) * grad(test) + trial * test) * dx
    load = LinearForm(x * test * dx)
    solution = GridFunction(space)
    preconditioner = Preconditioner(form, "hypre") if backend == "hypre" else None
    with TaskManager():
        form.Assemble()
        load.Assemble()
        rhs = projected(load.vec, space.FreeDofs())
        if backend == "mumps":
            solution.vec.data = form.mat.Inverse(space.FreeDofs(), inverse="mumps") * rhs
        else:
            solution.vec.data = CGSolver(form.mat, preconditioner.mat, maxiter=400, tol=1.0e-11,
                                         printrates=False) * rhs

    residual = relative_residual(form.mat, solution.vec, load.vec, space.FreeDofs())
    norm = Norm(solution.vec)
    if not (math.isfinite(norm) and norm > 0.0):
        raise RuntimeError(f"{backend} produced the solution norm {norm}")
    if comm.rank == 0:
        summary.write(work, {
            "ranks": comm.size, "degrees_of_freedom": getattr(space, "ndofglobal", space.ndof),
            "relative_residual": residual, "solution_l2_norm": norm,
        }, versions())
    comm.Barrier()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
