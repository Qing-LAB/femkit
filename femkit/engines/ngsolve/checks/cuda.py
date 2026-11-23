"""A sparse CG solve on the GPU against the same solve on the CPU; a host fallback is a failure.

H1 order 2 on the unit square (maxh 0.12), Jacobi-smoothed CG to 1e-12 on both
sides; the device vectors must really live in CUDA memory.

Summary quantities: degrees_of_freedom, relative_difference, cpu_relative_residual,
gpu_relative_residual.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from femkit.engines import summary
from femkit.engines.cuda import current_device, require_device_pointer
from femkit.engines.ngsolve.checks.common import projected, relative_residual, start, versions


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m femkit.engines.ngsolve.checks.cuda WORK", file=sys.stderr)
        return 2
    work = Path(argv[0])
    start()
    os.environ["NGS_CUDA_DEVICE_INDEX"] = "0"
    from netgen.geom2d import unit_square
    from ngsolve import BilinearForm, GridFunction, H1, LinearForm, Mesh, Norm, TaskManager, dx, grad, x
    from ngsolve.krylovspace import CGSolver
    from ngsolve.ngscuda import DevCGSolver, DevSparseMatrix, UnifiedVector

    print(f"device: {current_device()}")
    mesh = Mesh(unit_square.GenerateMesh(maxh=0.12))
    space = H1(mesh, order=2, dirichlet=".*")
    trial, test = space.TnT()
    form = BilinearForm(grad(trial) * grad(test) * dx + trial * test * dx)
    load = LinearForm(x * test * dx)
    with TaskManager():
        form.Assemble()
        load.Assemble()
        rhs = projected(load.vec, space.FreeDofs())
        smoother = form.mat.CreateSmoother(space.FreeDofs())
        host = GridFunction(space)
        host.vec.data = CGSolver(form.mat, smoother, maxiter=500, tol=1.0e-12, printrates=False) * rhs
        device_load = UnifiedVector(rhs)
        device_load.UpdateDevice()
        require_device_pointer(device_load.dev_ptr)
        device_result = UnifiedVector(space.ndof)
        device_result.data = DevCGSolver(
            form.mat, smoother, adev_raw=DevSparseMatrix(form.mat), cdev_raw=smoother.CreateDeviceMatrix(),
            maxsteps=500, precision=1.0e-12, printrates=False,
        ) * device_load
        require_device_pointer(device_result.dev_ptr)
        device_result.UpdateHost()
        copied = host.vec.CreateVector()
        copied.data = device_result
    difference = Norm(host.vec - copied) / max(Norm(host.vec), 1.0e-30)
    if not math.isfinite(difference):
        raise RuntimeError(f"the CPU/GPU difference is {difference}")
    summary.write(work, {
        "degrees_of_freedom": space.ndof,
        "relative_difference": difference,
        "cpu_relative_residual": relative_residual(form.mat, host.vec, load.vec, space.FreeDofs()),
        "gpu_relative_residual": relative_residual(form.mat, copied, load.vec, space.FreeDofs()),
    }, versions())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
