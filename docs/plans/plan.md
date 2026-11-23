# femkit plan

**Role:** plan
**Status:** current
**Authority:** open work only, in its order; `docs/contracts/` governs the code,
and this plan never overrides a contract

## 1. Where femkit stands

The framework, the installer and the machine probe are built, and the basic test
tier covers them. On a workstation, `env bootstrap` from a clean slate builds and
validates `elmer` (seven checks, adaptive re-meshing with Mmg and ParMmg among
them) and `ngsolve` (six checks), writes the machine record, and `doctor` reports
the machine ready. Running a job is not built yet (M3, M4).

Each milestone ends with its tier green and a review before the next starts.

## 2. Milestones

- **M1 — framework, installer, tests.** Open:
  - **An installed-solver check with an exact answer.** Laplace on the unit
    square, 0 V on the left, 1 V on the right, insulated top and bottom: the
    exact potential is φ = x. Elmer runs gmsh, ElmerGrid and the installed
    ElmerSolver to a VTU field; NGSolve solves the same case. Acceptance: every
    nodal |φ − x| ≤ 1e-7, at least 200 cells and 50 interior points, area
    1 ± 1e-8. It is the serial base for Elmer's same case run threaded and on two
    ranks, the three agreeing, on the installed solver, and the first case of
    the engine tier (`testing.md` § 1).
  - **Rebuilding from a saved lock** is shown once: an environment created from
    its lock (`envs.md` § 4.3) gives the same manifest.
  - **Entering through the activate hook** where the manager kind's `run`
    cannot start a command, with the text of that failure in the kind
    (`envs.md` § 4.4).
  - **On the cluster:**
    - build `ngsolve-cuda` and `elmer-cuda` (ADR 0005), settling whether nvcc's
      host compiler and CMake's CUDA toolkit are found inside the prefix without
      `CMAKE_CUDA_HOST_COMPILER` and `CUDAToolkit_ROOT` — Elmer finds AmgX
      through CMake's old FindCUDA module (`CUDA_TOOLKIT_ROOT_DIR`, policy
      CMP0146), which the pinned CMake 4.5 still offers — and whether a CUDA build
      starts on a node without the NVIDIA driver;
    - the GPU failure cases, each a failed check with its reason, never a false
      pass: a GPU whose architecture the build was not compiled for, running out
      of device memory, and ranks mapped to GPUs in a multi-rank GPU run (every
      shipped device check uses one rank and one device, while `jobs.md` § 2
      allows `gpus > 1`);
    - the `mamba` and `micromamba` kind files, written against that cluster's
      module; until then the install script refuses a manager without a kind
      file. A kind is chosen by more than the executable's file name: a `mamba`
      link to micromamba would otherwise get the wrong kind file.
- **M2 — machines.** `job probe` and `job machines` are built. Open: the SLURM
  readers (`femkit/schedulers/slurm.py`) have read only made-up text; the field
  test on the cluster's login node (`tests/field/test_job_probe.py`) is their
  first real reading, and settles the `sacctmgr` column names and the shape of
  `scontrol show node -o` there.
- **M3 — local jobs.** Job request, prepare, run script, run state machine;
  `job prepare|launch|status|cancel` on the workstation; the engine tier. Open:
  - how `env validate --gpu` is requested as a job (`envs.md` § 5): its command
    runs femkit, in the control environment, from the target's checkout;
  - a run script starts its engine from none of the variables a shell or a
    cluster module set that redirect it — Elmer reads `ELMER_HOME`, `ELMER_LIB`
    and `ELMER_MODULES_PATH` to find its solver modules (`jobs.md` § 4);
  - a run's state does not rest on the engine's exit status alone: Elmer is
    reported to exit 0 when a solver module fails to load (not yet measured).
- **M4 — SLURM.** The `slurm` kind's remaining parts and its readers in
  `femkit/schedulers/` (`jobs.md` § 7); cluster probing and carrying a record;
  header, submission, query, cancel, `launch --check`. The fit and its wording
  follow `framework.md` § 4. Field tier on the cluster: the
  readers' first real reading is M2's field test there.

## 3. Framework debts, not yet scheduled

Each makes a likely future change touch generic code; each is fixed when the
milestone that first needs it starts, or sooner if cheap.

- **The GPU stack is CUDA by name**: the `[cuda]` part and `<name>-cuda`
  environments (ADR 0005), the `nvidia-smi` query, the CUDA architecture
  setting. A second stack (ROCm) would need a small declared GPU-stack kind —
  its CMake variable, architecture query, visibility and model queries — in
  their place.
- **Check kinds are dispatched in seven places** (`checks.py`, the `Check`
  model's optional fields); `ranks` means "launch this many" for `command` and
  "what the log must report" for `ctest`. One model per kind, as a discriminated
  union, and one table of what each kind does.
- **The check fingerprint lists its shared files by hand** (`checks.JUDGING`:
  `checks.py`, `engines/__init__.py`, `summary.py`, `cuda.py`): a change to
  `cuda.py` marks the CPU environments `unchecked` too. Count only what each
  environment's checks import.
- **Manager facts in generic code**: the activation variables
  (`envs/manager.py`), `conda-meta` spelled three times (`envs/state.py`,
  `jobs/probe.py`, `jobs/setup.py`), the explicit-lock parser in
  `envs/install.py`. Each becomes a manager-kind field or a registered reader.
- **The engine adapter is a set of module attributes** (`engines/__init__.py`);
  a missing one raises `AttributeError` (exit 1), not `DefinitionError`.
- **The engine-version rule is looser in code than in `definitions.md` § 5.3**:
  `engines/summary.py` accepts a summary without the engine's version entry, and
  Elmer's mesh check writes none.
- **State tables are not rendered** into `docs/reference/`, so each contract's
  table is a second copy of its code (`core.md` § 7).
- **The web's plan digest covers human text** (a step's `describe` carries the
  free space), so it can call a plan stale when no fact changed; and the web has
  no route for a long apply's progress (`api.md` § 5).
- **`maturity` has no reader**; **`env plan` repeats `install --dry-run`**;
  **`doctor` prints the preamble's two commands under both the configuration
  and the record row**. Each is deleted, given its one use, or said once.

## 4. After the framework

1. **Model preparation and headless analysis** (§ 6), reworked into a contract
   first: strict geometry, material, mesh, study and observable schemas,
   deterministic cases, engine preparation, parsers, reductions, pattern-aware
   convergence, ParaView-readable output ([`../design.md`](../design.md),
   scientific data). No solver-model work starts before the CPU environments
   validate.
2. One analytic Maxwell benchmark end to end in both engines, through those
   contracts.
3. A focused web interface for preparation, job status and numerical tables;
   interactive field visualization stays in ParaView (ADR 0002).
4. The bowtie model and its numerical convergence ladder.
5. Water and effective-tunneling studies, only after the classical model is
   converged and cross-checked.

## 5. Not scheduled: jobs across several nodes

A job runs on one node (`jobs.md` § 2). It stays that way unless one node turns
out to be too small for a real study, and the cluster's own documentation shows
that multi-node MPI is supported. The framework is ready for it: the request,
the record, the fit and the header can all be extended without changing how they
are built. What each piece would need:

- a `nodes` field in the request (`memory` and `gpus` are already per node);
- the partition's node limit, which the probe already reads, kept in the record;
- a fit worked out per node;
- one more line in the scheduler kind's header;
- the run's node list recorded in its outcome.

The real cost is not in femkit. The environment's MPI must start ranks through
the scheduler and use the cluster's fast network, not quietly fall back to TCP.
Showing that it does needs a validation job that runs across several nodes. That
may mean building against the cluster's own MPI, which is a deployment decision.

## 6. Model preparation and analysis

The work order and acceptance for solver-neutral input preparation and headless
result analysis, reworked into a contract before its code starts. Governing
documents: [`../design.md`](../design.md) (scientific data) and ADR 0002.

### 6.1 Outcome

Given one versioned physical model and study, femkit will produce:

1. validated, explicit geometry/material/excitation/boundary records;
2. deterministic resolved cases for each study point;
3. named-region and mesh manifests suitable for either backend;
4. complete solver-specific input directories;
5. structured numerical summaries from completed runs;
6. convergence and cross-case comparison tables;
7. unmodified or exported ParaView-readable field artifacts for optional visual
   inspection.

No analysis result will depend on manually clicking a plot, reading a screenshot,
or selecting an unnamed solver dataset.

### 6.2 Preparation authorities

These solver-neutral packages come after the framework:

```text
femkit/
├── geometry/       dimensions, coordinate frames, named regions and topology
├── materials/      complex dispersive properties and source provenance
├── physics/        excitation, boundaries, open-domain treatment and equations
├── mesh/           mesh policy, region-size rules, quality and fingerprints
├── studies/        sweep axes, deterministic case expansion and identifiers
├── observables/    definitions of points, lines, regions and reductions
└── analysis/       parsers, reductions, convergence and comparisons
```

Each package owns typed schemas plus validation. Backend adapters consume the
resolved forms; they do not invent missing values.

### 6.3 Explicit data required before preparation

#### Geometry

- length unit and right-handed coordinate frame;
- bowtie main axis and polarization axis;
- complete dimensions and construction method;
- named volumes, surfaces, edges, points and probe planes;
- topology checks for unwanted buried or overlapping interfaces;
- expected material assignment for every volume.

#### Materials

- complex relative permittivity or constitutive model;
- wavelength/frequency convention and interpolation rule;
- source citation and valid range;
- water/air selection;
- effective tunneling region and conductivity-law parameters, clearly marked
  as a phenomenological model.

#### Numerical policy

- outer-domain extent and open-boundary/PML policy;
- element-order policy;
- gap, metal-surface, bulk and PML mesh constraints;
- mesh growth and quality thresholds;
- solver tolerance and iteration limits;
- resource request kept separate from numerical physics.

#### Observables

Every observable states a name, expression, support, reduction, normalization,
unit, and complex-value convention. Initial bowtie observables are:

- complex electric field and amplitude enhancement at the gap center;
- gap-volume mean of amplitude and intensity enhancement;
- gap-volume mean of the $|E/E_0|^4$ proxy;
- field profile along the bowtie main axis;
- field profile through the gap normal direction;
- explicitly defined vertical center-plane samples;
- absorbed power in each metal body and leakage region;
- resonance wavelength and linewidth when a spectral study exists.

Point maxima may be reported diagnostically but cannot be the sole convergence
criterion.

### 6.4 Study separation

The study schema distinguishes:

- **numerical convergence:** mesh resolution/order, outer padding, PML thickness
  and solver tolerance;
- **geometry convergence:** electrode length and other truncation dimensions;
- **physical sweep:** wavelength, water/air, gap, material model and tunneling
  conductivity;
- **execution benchmark:** ranks, threads, memory and solver implementation.

Axes from different classes are not silently combined. A mixed study must name
the classes and explain why the Cartesian product is required.

### 6.5 Canonical analysis products

Every successful parser produces `result.json` plus ordinary tabular files:

```text
results/
├── result.json             status, provenance, metrics and artifact catalogue
├── scalar-metrics.csv      one row per case/frequency
├── probes/
│   ├── gap-axis.csv
│   ├── gap-normal.csv
│   └── center-plane.csv
├── convergence.csv         parameter, observable, relative change, pattern score
├── mesh-summary.json       counts, quality, named-region coverage, fingerprint
└── fields/                 retained ParaView-readable VTU/PVD artifacts
```

The exact filenames become contractual only when their schemas are implemented.
Large arrays stay in standard field/tabular artifacts rather than being embedded
in JSON.

### 6.6 Pattern-aware convergence

Convergence analysis must test whether the spatial solution pattern changes,
not only whether its maximum changes. For matched physical probes it reports:

- relative change in integrated/averaged observables;
- normalized correlation of complex field or intensity profiles;
- location shift of dominant peaks;
- sign/phase consistency where meaningful;
- energy-balance or power residual;
- changes in resonance wavelength and linewidth for spectral studies.

Comparison across nonidentical meshes occurs on declared physical probe lines,
planes, or integration regions. It does not compare raw node indices.

### 6.7 Backend preparation boundary

Both adapters receive the same resolved case and return a preparation manifest:

- backend name/version requirement;
- complete generated-file inventory and hashes;
- geometry/mesh fingerprints;
- named-region mapping from common names to backend identifiers;
- exact command vector and controlled environment additions;
- declared expected products.

Elmer emits Gmsh/ElmerGrid artifacts and a readable SIF. NGSolve emits a
standalone Python solve script and resolved input record. Generated inputs carry
provenance and are inspectable, but edits to them do not alter the authoritative
model.

### 6.8 Parser and analysis discipline

- Detection, parsing, and scientific interpretation are separate steps.
- A parser never silently substitutes zero or an empty array for missing output.
- Complex fields retain real and imaginary components until a named reduction
  requests magnitude, phase, real part, or imaginary part.
- Every reduction records the mesh/field source and expression used.
- Failed and unconverged attempts remain analyzable but are labeled as such.
- Cross-backend comparison is refused when coordinate frames, excitation
  normalization, material convention, or observable support do not agree.

### 6.9 Tests and validation

- strict schema round trips and unknown-key refusal;
- unit conversion and coordinate-frame tests;
- deterministic case identifiers independent of dictionary ordering;
- geometry-region coverage and topology checks;
- material interpolation against fixed reference points;
- mesh-manifest and region-map completeness;
- parser fixtures for successful, failed and truncated solver output;
- analytic probe/reduction tests using synthetic complex fields;
- convergence tests that distinguish amplitude agreement from pattern change;
- cross-backend normalization refusal tests;
- ParaView artifact catalogue test without importing VTK in the host process.

### 6.10 Completion gate

This milestone is complete when a small analytic Maxwell model can be described
once, prepared reproducibly for both backends, run through the common attempt
contract, and reduced to comparable numerical tables—with its raw field files
ready for ParaView—without any manual GUI action.

