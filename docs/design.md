# Design principles

**Role:** principle

**Status:** current

**Authority:** mission, durable design values, and the rules every stored scientific quantity follows

femkit exists to make a finite-element result inspectable and reproducible,
from physical intent through visualization, on a workstation or an HPC cluster.

- Explicit beats inferred: units, regions, coordinate systems, solver
  capabilities, resource requests, and dataset choices are named.
- Portable descriptions contain science; machine records contain machine facts.
- An engine translates but does not redefine the physical model.
- Raw solver output is retained. Parsed summaries add a view; they do not
  replace evidence.
- Numerical convergence and physical parameter studies are different objects.
- Independent engines are used as cross-checks only after each has passed its
  own analytic benchmarks and convergence study.
- Observable averages, profiles, powers, and pattern comparisons carry more
  scientific weight than a single mesh-node maximum.


## Scientific data

These rules hold for every model, study and result femkit stores; the contract
that defines those files, [`contracts/models.md`](contracts/models.md) (not
built yet, plan § 3, M5–M9), follows them.

- Physical intent, a study's questions, one resolved case, the solver input
  prepared from it, one run and its interpretation are separate files, each
  with one writer. Prepared input is evidence, never the source of intent.
- A stored dimensional quantity has an explicit value and unit. Internally one
  documented convention holds — SI, with angles in degrees so that a written
  angle stays exact; conversion for display happens only at a surface.
- Geometry declares its origin, axes, handedness and named regions. A plane is
  an origin and a normal, never a label such as "YZ-like".
- Material data records its source, independent variable, interpolation rule,
  complex-value convention and valid range.
- Numerical controls and physical parameters are separate study axes.
- An option one engine needs lives in that engine's own block and never changes
  the meaning of a common field. What an engine cannot do is refused, never
  approximated silently.
- Every reported observable defines its support and reduction: point, line,
  surface, volume; average, integral, maximum or norm.
- Process success, algebraic convergence, mesh convergence and physical
  validity are four different statements.
- Raw solver output stays beside parsed summaries.
- Interactive field rendering is ParaView's
  ([ADR 0002](decisions/0002-paraview-visualization-boundary.md)); femkit owns
  field export, metadata, numerical reduction and analysis.

## Settled choices

| topic | choice |
|---|---|
| name | `femkit`, everywhere ([ADR 0001](decisions/0001-project-name-femkit.md)) |
| engines | Elmer and Netgen/NGSolve, each built from pinned sources in its own environment |
| package manager | the conda family (conda; mamba and micromamba once their kind files are written), driven only through declared manager kinds |
| design basis | state machines: state observed from durable facts, one closed table per machine, operations as event logs |
| definitions | engines, environments, managers and schedulers are data under a schema; adding an engine adds data and one small adapter |
| calculations | one solver-neutral model in a closed list of formulations, matched against each environment's declared and proven abilities; every limitation is shown, decided or customized at a declared extension point ([ADR 0008](decisions/0008-one-model-declared-abilities.md)) |
| schedulers | SLURM first, its language declared in a scheduler kind file |
| surfaces | the command line (click) and, to come, a web interface (flask, with a React front end built and shipped in the package, [ADR 0009](decisions/0009-web-front-end.md)), both generic adapters over the same operations |
| a shipped definition | is never overridden by a person's copy; a machine that needs another value gets it as a declared option, chosen in `config.toml` |
