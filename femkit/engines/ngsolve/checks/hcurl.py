"""A small complex H(curl) solve: proves NGSolve really runs, serial, threaded or over MPI.

An installation check, not a physical benchmark: a coercive curl-curl plus mass
problem on the unit cube (maxh 0.35, order 1, Dirichlet on every boundary). On
one rank it solves directly and exports the field to VTK, then reads it back;
on several ranks it distributes the mesh and solves with CG and a local
preconditioner.

Summary quantities: ranks, threads, degrees_of_freedom, relative_residual, field_l2_norm.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from femkit.engines import summary
from femkit.engines.ngsolve.checks.common import projected, relative_residual, start, versions

FIELDS = ("E_real", "E_imag")


def _check_export(work: Path, stem: str) -> None:
    """The exported field reads back with finite points and both field components."""
    import meshio
    import numpy as np

    files = sorted(work.glob(stem + "*.vtu"))
    if not files:
        raise RuntimeError("the field export wrote no .vtu file")
    for path in files:
        mesh = meshio.read(path)
        points = len(mesh.points)
        if points <= 0 or not sum(len(b.data) for b in mesh.cells) or not np.isfinite(mesh.points).all():
            raise RuntimeError(f"{path.name}: empty or non-finite mesh")
        for name in FIELDS:
            values = mesh.point_data.get(name)
            if values is None or values.shape != (points, 3) or not np.isfinite(values).all():
                raise RuntimeError(f"{path.name}: field {name} is missing or not finite")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m femkit.engines.ngsolve.checks.hcurl WORK", file=sys.stderr)
        return 2
    work = Path(argv[0])
    comm, threads = start()
    distributed = comm.size > 1

    import netgen.meshing
    import ngsolve
    from netgen.csg import unit_cube
    from ngsolve import (BilinearForm, CoefficientFunction, GridFunction, HCurl, InnerProduct, LinearForm,
                         Mesh, Norm, TaskManager, VTKOutput, curl)

    if distributed:
        if comm.rank == 0:
            mesh = Mesh(unit_cube.GenerateMesh(maxh=0.35).Distribute(comm))
        else:
            mesh = Mesh(netgen.meshing.Mesh.Receive(comm))
        comm.Barrier()
    else:
        mesh = Mesh(unit_cube.GenerateMesh(maxh=0.35))

    space = HCurl(mesh, order=1, complex=True, dirichlet=".*")
    trial, test = space.TnT()
    form = BilinearForm(space)
    form += InnerProduct(curl(trial), curl(test)) * ngsolve.dx
    form += InnerProduct(trial, test) * ngsolve.dx
    load = LinearForm(space)
    load += InnerProduct(CoefficientFunction((1.0 + 0.25j, 0.0, 0.0)), test) * ngsolve.dx
    solution = GridFunction(space, name="E")
    if distributed:
        from ngsolve import Preconditioner
        from ngsolve.krylovspace import CGSolver
        preconditioner = Preconditioner(form, "local")
    with TaskManager():
        form.Assemble()
        load.Assemble()
        rhs = projected(load.vec, space.FreeDofs())
        if distributed:
            solution.vec.data = CGSolver(form.mat, preconditioner.mat, maxiter=400, tol=1.0e-11,
                                         printrates=False) * rhs
        else:
            solution.vec.data = form.mat.Inverse(space.FreeDofs()) * rhs

    residual = relative_residual(form.mat, solution.vec, load.vec, space.FreeDofs())
    norm = Norm(solution.vec)
    if not (math.isfinite(norm) and norm > 0.0):
        raise RuntimeError(f"the computed field norm is {norm}")
    if not distributed:
        VTKOutput(mesh, coefs=[solution.real, solution.imag], names=list(FIELDS),
                  filename=str(work / "hcurl"), subdivision=0).Do()
        _check_export(work, "hcurl")
    if comm.rank == 0:
        summary.write(work, {
            "ranks": comm.size, "threads": threads,
            "degrees_of_freedom": getattr(space, "ndofglobal", space.ndof),
            "relative_residual": residual, "field_l2_norm": norm,
        }, versions())
    if distributed:
        comm.Barrier()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
