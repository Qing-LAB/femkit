"""The `elmer-solver-log` reader: what an Elmer CTest case's own log says (definitions.md § 5.3).

Elmer's test harness writes `test-stdout_<ranks>.log` (an MPI build) or
`test-stdout.log`, and a `TEST.PASSED*` marker, into the test's working directory;
the runner hands over those written since the check started, and the log's `Version:`
must be the pinned one. Where the test's own verdict counts, every marker must hold 1;
where the check sets it aside (`upstream_verdict = false`), only the quantities are judged.

Quantities:

| name | from |
|---|---|
| norms | every `Solver N PASSED|FAILED: Norm = … RefNorm = …` line's Norm, in order |
| norm_N | solver N's Norm, from the same line |
| reference_error | the largest relative error of a Norm against its RefNorm |
| mmg_runs | how many times Mmg re-meshed serially (its `MODULE MMG3D` banner) |
| parmmg_runs | how many times ParMmg re-meshed in parallel (its `MODULE PARMMGLIB_DISTRIBUTED` banner) |
| adaptive_converged | how many adaptive-meshing loops ended by meeting their error limit (`Mesh convergence limit reached`) |
| adaptive_depth_limited | how many ended at `Adaptive Max Depth` instead, unconverged (`Max adaptive depth reached`) — both endings print `Adaptive Meshing Finished`, so that line proves nothing |
| ranks | `Running in parallel using N tasks`, when Elmer prints it |
| threads | `parallel with N threads per task`, when Elmer prints it |
| amgx_solves | how many AmgX solves completed (`Total Iterations` with a `Final Residual`) |
| amgx_final_residual | the largest AmgX final residual, when any ran |
"""

from __future__ import annotations

import math
import re

from femkit.engines import Output

_NORM = re.compile(r"Solver\s+(?P<solver>[0-9]+)\s+(?:PASSED|FAILED):\s+Norm\s*=\s*(?P<norm>[+\-0-9.Ee]+)"
                   r"\s+RefNorm\s*=\s*(?P<reference>[+\-0-9.Ee]+)")
_RANKS = re.compile(r"Running in parallel using\s+([0-9]+)\s+tasks")
VERSION = re.compile(r"Version:\s*([0-9]+\.[0-9]+)-")
_THREADS = re.compile(r"parallel with\s+([0-9]+)\s+threads per task")
_AMGX_ITERATIONS = re.compile(r"Total Iterations:\s*([0-9]+)")
_AMGX_RESIDUAL = re.compile(r"Final Residual:\s*([+\-0-9.Ee]+)")
_MMG = re.compile(r"MODULE MMG3D:")
_PARMMG = re.compile(r"MODULE PARMMGLIB_DISTRIBUTED")
_ADAPTIVE_CONVERGED = re.compile(r"Mesh convergence limit reached")
_ADAPTIVE_DEPTH_LIMITED = re.compile(r"Max adaptive depth reached")


def solver_log(output: Output) -> dict:
    logs = output.written(f"test-stdout_{output.ranks}.log") or output.written("test-stdout.log")
    if not logs:
        raise ValueError("no test-stdout log from this run in the test's working directory")
    (name, held), = logs.items()
    markers = output.written("TEST.PASSED*")
    if output.upstream_verdict and (not markers or any(
            m.decode("utf-8", errors="replace").strip() != "1" for m in markers.values())):
        raise ValueError("Elmer wrote no passing TEST.PASSED marker in this run")
    text = held.decode("utf-8", errors="replace")
    version = VERSION.search(text)
    if version is None or version.group(1) != output.version:
        raise ValueError(f"{name} reports Elmer {version.group(1) if version else 'of no version'}; "
                         f"the environment pins {output.version}")

    norms, errors, by_solver = [], [], {}
    for match in _NORM.finditer(text):
        norm, reference = float(match.group("norm")), float(match.group("reference"))
        error = abs(norm - reference) / abs(reference) if reference else abs(norm - reference)
        if not all(math.isfinite(v) for v in (norm, reference, error)):
            raise ValueError(f"Elmer reported a non-finite norm: {match.group(0)}")
        norms.append(norm)
        errors.append(error)
        by_solver[f"norm_{match.group('solver')}"] = norm
    if not norms:
        raise ValueError(f"{log.name} holds no Norm / RefNorm line")
    quantities: dict = {"norms": norms, "reference_error": max(errors), **by_solver,
                        "mmg_runs": len(_MMG.findall(text)), "parmmg_runs": len(_PARMMG.findall(text)),
                        "adaptive_converged": len(_ADAPTIVE_CONVERGED.findall(text)),
                        "adaptive_depth_limited": len(_ADAPTIVE_DEPTH_LIMITED.findall(text))}
    if found := _RANKS.search(text):
        quantities["ranks"] = int(found.group(1))
    if found := _THREADS.search(text):
        quantities["threads"] = int(found.group(1))

    iterations, residuals = _AMGX_ITERATIONS.findall(text), _AMGX_RESIDUAL.findall(text)
    if len(iterations) != len(residuals):
        raise ValueError("AmgX solve statistics are incomplete")
    values = [float(r) for r in residuals]
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("AmgX reported a non-finite or negative final residual")
    quantities["amgx_solves"] = len(values)
    if values:
        quantities["amgx_final_residual"] = max(values)
    return quantities
