"""What every NGSolve check program shares: MPI and thread start-up, the free-equation residual."""

from __future__ import annotations

import math
import os


def start():
    """MPI first, then NGSolve with the declared threads. Returns (communicator, threads).

    mpi4py initialises MPI on import; that must happen before any Netgen/NGSolve
    call, a serial mesh included, in an MPI-enabled build.
    """
    from mpi4py.MPI import COMM_WORLD
    import ngsolve

    threads = int(os.environ.get("NGS_NUM_THREADS", "1"))
    ngsolve.SetNumThreads(threads)
    return COMM_WORLD, threads


def versions() -> dict[str, str]:
    import netgen
    import ngsolve
    return {"ngsolve": ngsolve.__version__, "netgen": getattr(netgen, "__version__", "")}


def projected(vector, freedofs):
    from ngsolve import Projector

    result = vector.CreateVector()
    result.data = vector
    Projector(freedofs, True).Project(result)
    return result


def relative_residual(matrix, solution, load, freedofs) -> float:
    """||P(A x - b)|| / ||P b|| over the free degrees of freedom; MPI-aware through NGSolve's vectors."""
    from ngsolve import Norm

    residual = load.CreateVector()
    residual.data = matrix * solution - load
    numerator, denominator = Norm(projected(residual, freedofs)), Norm(projected(load, freedofs))
    if not (math.isfinite(denominator) and denominator > 0):
        raise ValueError("the free-equation load norm is not finite and positive")
    ratio = numerator / denominator
    if not math.isfinite(ratio):
        raise ValueError("the relative residual is not finite")
    return ratio
