# ADR 0016: every step runs from a run folder, by one machinery

**Role:** ADR

**Status:** accepted (2026-11-25); its stages' declaration, the workflow
graph and the translation — folder writing since ADR 0025 decision 10 —
consolidated by
[ADR 0018](0018-one-graph-from-description-to-execution.md) into
[`workflow.md`](../contracts/workflow.md); it widens
[`definitions.md`](../contracts/definitions.md) § 4.7's tool environment, which
may now be installed by default and carry checks; being built in plan § 4, X.
Decision 11 and the consequences that have a study state its resources and
its mesher per environment, one meshing job each, amended by
[ADR 0025](0025-one-engine-per-study-observables-after.md) (decision 1): a
study names no engine — its `[solve]` and `[meshing]` stated once, the
engine chosen when it is solved — and the mesh recipe names its mesher; a
study's solves in one engine are one job, as decision 4 has its meshing.
Decision 5's "the run keeps the shell it is started in" amended by
[ADR 0026](0026-environments-under-condas-management.md) (decision 4): a run
starts clean, as every call into an environment does, its shell's undeclared
functions no longer exported, never removed

**Authority:** the reasons and the alternatives only;
[`jobs.md`](../contracts/jobs.md) §§ 1–6, [`workflow.md`](../contracts/workflow.md)
and [`geometry.md`](../contracts/geometry.md) §§ 2, 3, 5, 8 and 10 own the rules

## Context

Until X, femkit ran nothing of a project. A project could be written,
checked and expanded into cases, but the person's geometry script had no way
to run, the mesh step did not exist, and `jobs.md` described a job for a
solver only. Install steps and checks ran inside an operation, through the
manager's `run`. The bowtie needs every step — the geometry, the mesh, the
solve — run on a cluster as well as on a workstation, inspectable afterwards
and repeatable.

Measured on this workstation on 2026-11-25, before the design was settled:

- No environment could run a geometry script: `elmer` holds the Gmsh program
  but not its Python module, and `ngsolve` holds no Gmsh.
- ElmerSolver 26.2 exits 0 when a solver module it names fails to load; its
  log ends with the loader's errors.
- Of Gmsh's file formats, `.xao` alone kept both the exact shapes and every
  group name of the Laplace square; `.brep` and `.step` kept no group, and
  `.msh` made the shapes discrete.

The shape of a run — a folder per start, its launch, start and conclusion
each a record of its own, a stop told from a failure, one job per submission,
dependent stages run as a sequence each launched when the one before has
finished, every file a real copy — was already proven on the cluster by the
person's earlier tool, and `jobs.md` already held part of it for a solve. A
first design for X departed from it in several places with no measured failure
of it; a full-text review against that tool found them, and the person
directed that its design be copied (2026-11-25).

## Decision

1. **One run machinery for every step.** The geometry script, the mesh step,
   a solve, and a check that needs a compute node each run from a
   calculation folder — its request, its run script, a new `run-NNN/` per
   start — inside the step's environment, watched by a monitor, its outputs in
   its folder. Only `job launch` starts a run (the earlier tool's launch-door
   gate). The programs a step runs, femkit's own and the monitor, are copied
   into its calculation folder when it is prepared, each one's SHA-256
   recorded, so a run never reads the checkout — femkit's own launcher
   exports no variable a run could inherit — and a checkout changed after
   prepare never reaches a run; a sequence's walk alone runs femkit, entering
   its control environment as the earlier tool's walk enters its own, to
   launch each part. A step's program runs as one process,
   as the earlier tool runs an engine that runs one process.
2. **Every step is a program wrapped by a contract** — the person's geometry
   script, femkit's standard import script and each mesher's standard
   meshing script alike ([`geometry.md`](../contracts/geometry.md) §§ 3, 8):
   its inputs checked before it runs, what it promises checked after. How the
   program ended and what its contract found are two facts, in two files,
   `ended.json` and `checked.json` (the earlier tool's rule); a run finishes
   when both say so.
3. **Each step is made once, within a study, per machine**, its folder named
   by the SHA-256 of what it is made from — the programs that make and check
   it, its target and the target's install fingerprint of its environment
   included, so a changed program or a rebuilt environment makes it anew, and
   a second machine its own.
4. **A case's calculation is a sequence**: geometry, mesh, solve, each
   launched when the one before has finished, each in its own environment —
   the earlier tool's sequence of groups, femkit's batches (ADR 0018). Steps of one environment that take
   nothing from each other go in one job as a group, one after another. As in
   the earlier tool, a batch's or a sequence's job keeps its header, its walk
   and its log in `launch/`, its members' runs where they always are; a
   sequence launches each part inside its job with femkit's own `job launch`,
   waited on, so it waits on each and a stop reaches the part that runs; a
   step found finished is used. A step depends on its own inputs alone (the
   person, 2026-11-25): a mesh whose geometry did not finish is not made, and
   the other cases go on — the earlier tool's groups were stages of one
   calculation, a study's are independent cases. Inside a job, every step
   runs with what the job holds (the person, 2026-11-25). `study mesh` runs
   each case's sequence up to its meshes and stops, so the person looks at
   them before a solve — since [ADR 0022](0022-one-prep-step.md), `study
   prep`, whose stage waiting on a job's mesh is written by a later prep.
5. **The run script is the earlier tool's**: with unset variables allowed, the
   target record's preamble verbatim — each absolute path a bare `source X`
   or `. X` line of it names checked readable first — then its activation of
   the exact prefix; then unset variables refused again. The prefix entered
   and its own `python` are verified; the environment's declared thread and
   fixed variables are exported. The run keeps the shell it is started in: an
   engine's own settings are its environment's, which its activation and its
   definition give.
6. **A run is stopped by `SIGTERM` to its process group**, once, as the
   earlier tool stops it, through the core's one signal for a run launched
   earlier; the run script's handler logs the signal and writes no record of
   how it ended.
7. **A run's state is observed from its records by the earlier tool's order
   of evidence** into its closed list — `pending`, `queued`, `running`,
   `finished`, `failed`, `unreadable`: what the run's own records say how it
   ended first; then the job's word, asked once on the machine that launched
   the job, by whichever reader asks first, and written once into the run
   (`gone.json`); then the monitor's closing record; then a sent job's wall; a
   run's start before its launch record, so a launch cut short after the run
   started never reads `pending`. A stopped run reads `failed`, with its
   evidence — *cancelled*, *never started* — and a run read from another
   machine reads from its files.
8. **Every launch leaves an address on this machine**, as the earlier tool's
   does: `job list` shows each job and its runs, `job cancel ID` stops one,
   with no lock. A launch here goes to the background, or is waited on and
   exits by how its runs ended.
9. **A monitor runs beside every run** (the person, 2026-11-25): the earlier
   tool's, copied — standard library alone, at `nice 19`, watching the run
   script's PID; it samples what the run uses against what the job holds,
   writes a line only when something moved, and leaves a closing record that
   is evidence of how a run ended. It observes and never decides. Telling
   channels outside the run is not in X.
10. **What the person brings is copied; what the workflow made is shared**
    (the person, 2026-11-25). A file a step of the workflow made — a geometry,
    a mesh — is read where it was made, by its path from the reading run, its
    SHA-256 checked at launch and the file read-only once its step finished;
    what the person brings, and what an engine continues from and may write
    into, is copied into the run, as the earlier tool copies every file.
11. **Every meshing task runs in the environment that provides its mesher**,
    and the study names, per environment, which mesher makes its mesh — the
    meshers' declared route where it does not (the person, 2026-11-25;
    [ADR 0017](0017-netgen-curves-ngsolve-geometry.md)).
12. **The geometry scripts' and Gmsh meshing's environment is `gmsh`**:
    conda-forge packages alone — Python, Gmsh 4.15.2 with its Python module,
    NumPy — no engine, installed by default. A geometry script imports what it
    holds; pip installs nothing.
13. **The geometry file is `geometry.xao`**; a mesher that reads another form
    — Netgen's, BREP — is handed that form beside it.
14. **A calculation keeps its own copy of its target's machine record**, taken
    at its first prepare and never changed, whatever was probed since (the
    earlier tool's rule): a later prepare reads the copy, and a newer record
    reaches calculations not yet prepared.
15. **Every step's results are kept, to be looked at** (the person,
    2026-11-25): read-only once checked, never removed or overwritten by
    femkit, shown by `case list` and `job status`, each mesh with a copy
    ParaView opens.

## Alternatives not chosen

- **A sequence only where the person names it at a launch, as the earlier
  tool chains stages**: there, which stage follows which is a scientific
  judgement made in advance; a case's mesh always takes from its geometry, a
  dependency of data, so femkit chains the two — the person, 2026-11-25:
  "`study mesh` runs each case's sequence up to its meshes and stops" — and
  never chains across a judgement: the solve rides no meshing job (ADR 0022
  decision 8).

- **A stage named by its case and kind, as the earlier tool names a
  calculation's stages, with a record of what it was prepared with**: the
  cases of a sweep share a stage whenever they share what it is made from —
  a wavelength sweep's cases one shape and one mesh — and a name from content
  finds that stage for every case, made once; a name per case would make it
  once per case, or need a second record mapping cases to it.

- **Geometry and mesh run in the foreground of a command.** A second way to
  run things beside jobs, with no path to a compute node: a 3-D bowtie mesh
  does not belong on a login node.
- **Dependent steps in one shell walk, linked to files not yet made and
  skipped by the walk's own logic** — X's first design. A link points at a
  file that does not exist yet, and deciding on the node in shell is what the
  earlier tool keeps in Python on the host; a sequence launches each part when
  the one before has finished, with every check its launch has.
- **Every file a real copy, a workflow's mesh included.** A mesh shared by a
  fifty-point wavelength sweep would exist fifty times, though the workflow
  made it in the same project, where the reading run finds it by a path that
  moves with the project.
- **Every file a link.** A link dangles once a folder is synced elsewhere, and
  an engine writes into the files it continues from — the earlier tool's
  reasons, 2026-08-24, which hold for what the person brings.
- **A run script that restarts itself with an empty environment.** It removed
  the `module` command a batch job inherits from the submitting shell, so a
  site's preamble failed on every run; and an engine's settings are its
  environment's to give, not the run script's to filter.
- **The command's exit status as the verdict.** Measured above: Elmer reports
  success when a solver module never loaded.
- **The states `cancelled`, `lost` and `unknown`** — X's first design. The
  earlier tool reads a stopped run as `failed` with the evidence beside it,
  and writes once into the run that its job is gone, so the folder reads the
  same on every machine; a run seen from another machine never waits on an
  answer only one machine can give.
- **Re-pointing a prepared calculation at another machine** — X's first
  design. The earlier tool's calculation keeps the record it was prepared
  with; a second target is a second calculation, and a step made for another
  machine is another step.
- **Batches and sequences as calculation folders with runs of their own** — X's
  first design. The earlier tool keeps a group's and a sequence's header,
  walk and log in `launch/`, and reads them by their members' runs.
- **Separate resources for the geometry and mesh steps.** Meshing takes
  little of a job, and inside one job every step runs with what the job holds
  (the person, 2026-11-25). Since the solve rides no meshing job, the meshing
  job states its own ([ADR 0022](0022-one-prep-step.md) decision 10).
- **A run's log written to its file alone.** The earlier tool tees it, so a
  scheduler's output file holds it too, and ignores a broken pipe so a stop
  that kills the tee does not kill the script.
- **One environment gathering every mesher.** A second build of a mesher an
  engine already holds — Netgen inside `ngsolve` — with its pins kept twice.
- **Gmsh's Python module added to `elmer`.** Every mesh, an NGSolve case's
  too, would need Elmer's environment; a mesh depends on no engine.
- **Extra packages named per project.** An environment per project, built and
  kept for each.

## Consequences

- `jobs.md` §§ 1–6: stages, batches and sequences; `shares`, `outputs` and
  `check`; the run's records `launched.json`, `started.json`, `ended.json`,
  `checked.json`, `outputs.json`, `gone.json`, `cancel.json`; the monitor's
  `monitor.log` and `util.csv`; the run state machine declared as data, by the
  earlier tool's order of evidence; the launch-door gate; a calculation's own
  record copy; `job launch --in-sequence`, typed by a sequence alone.
- The core gains one signal for a run launched earlier, beside its block for
  the children an operation waits on, and a child kept in its starter's
  process group for a run waited on.
- A calculation folder is locked by its own lock, wherever it lies; the run
  door writes a job's word whichever operation reads the run.
- `job list` and `job cancel ID` over this machine's addresses, in femkit's
  state directory.
- A study states, per engine environment, its jobs' resources — every stage
  inside a job running with what the job holds (ADR 0018) — and, where it
  wants another than the default, the mesher.
- `definitions.md` § 4.7: a tool environment may be `default` and declare
  command checks read by the generic readers; `gmsh` is the first.
- `project check` reads a built geometry's groups to observe each group's
  place, replacing the note that said it was not checked yet.
- `study mesh` (since ADR 0022, `study prep`) writes its batches and sequences in `runs/<study>/launch/`, one
  job per environment the study solves in; each stage's folder keeps what it
  is made from, `stage.json`, by which a reader finds a case's stages
  ([`workflow.md`](../contracts/workflow.md) §§ 4, 7).
