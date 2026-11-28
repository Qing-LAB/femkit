# Design principles

**Role:** principle

**Status:** current

**Authority:** mission, durable design values, the rules every stored scientific quantity follows, and the one register of settled choices, each line naming the ADR or contract that states it

femkit's purpose, in the person's words (2026-11-27): "femkit provide the
hierarchical support and contractual agreement to bind all parties to work
on the problem". The hierarchy is the project, its parts, its studies, their
cases, each case's stages and runs, and its observables. The parties are the
person, who writes the problem — the definitions, the geometry script, the
physics, the mesh recipe, the study and `observe.py`; the engines, which
solve and write their output; the person's scripts, which read that output
and compute the results; and the environments and machines that run them.
The contracts say what each party gives and receives: femkit checks each
agreement before anything runs and each declared result after, and never
does a party's work.

femkit exists to make a finite-element result inspectable and reproducible,
from physical intent through visualization, on a workstation or an HPC cluster.

- Explicit beats inferred: units, regions, coordinate systems, solver
  capabilities, resource requests, and dataset choices are named.
- Portable descriptions contain science; machine records contain machine facts.
- An engine's input writer expresses the physical model; it never redefines it.
- Raw solver output is retained. Parsed summaries add a view; they do not
  replace evidence.
- Numerical convergence and physical parameter studies are different objects.
- Independent engines are used as cross-checks only after each has passed its
  own analytic benchmarks and convergence study.
- Observable averages, profiles, powers, and pattern comparisons carry more
  scientific weight than a single mesh-node maximum.


## Scientific data

These rules hold for every model, study and result femkit stores; the contract
that defines those files, [`contracts/models.md`](contracts/models.md), follows
them.

- Physical intent, a study's questions, one resolved case, the solver input
  prepared from it, one run and its interpretation are separate files, each
  with one writer. Prepared input is evidence, never the source of intent.
- A stored dimensional quantity has an explicit value and unit. Internally one
  documented convention holds — SI, with angles in degrees so that a written
  angle stays exact; conversion for display happens only at a surface.
- Geometry is written in one Cartesian, right-handed frame and declares its
  named regions. A plane is a point and a normal, never a label such as
  "YZ-like".
- Material data records its source, independent variable, interpolation rule,
  complex-value convention and valid range.
- Numerical controls and physical parameters are separate study axes.
- An option one engine needs lives under that engine's own name and never changes
  the meaning of a common field. What an engine cannot do is refused, never
  approximated silently.
- Every reported observable declares what it reads and what it gives, with
  its unit; how it reduces the solver's output is the person's own function,
  which reads the engine's files as the engine wrote them; femkit runs it,
  records it and checks what it returns.
- Process success, algebraic convergence, mesh convergence and physical
  validity are four different statements.
- Raw solver output stays beside parsed summaries.

## Settled choices

Every decision in force, once, with the ADR or contract section that states
it; a superseded decision is not listed. A new decision gets its line in the
same change that writes it into its ADR or contract.

| topic | choice |
|---|---|
| name | `femkit`, everywhere: the package, the command, the variables, the directories, the schema IDs ([ADR 0001](decisions/0001-project-name-femkit.md)) |
| engines | Elmer and Netgen/NGSolve, each built from pinned sources in its own environment: an established, deployed release before a feature-new one, and upstream sources never patched ([ADR 0003](decisions/0003-ngsolve-stability-first-baseline.md), [ADR 0004](decisions/0004-elmer-stability-first-baseline.md); [`contracts/definitions.md`](contracts/definitions.md) § 4) |
| GPU builds | an engine definition with a CUDA part is two environments: `<name>`, for CPUs and the default, and `<name>-cuda`, installed only on request ([ADR 0005](decisions/0005-cuda-environments.md); [`contracts/definitions.md`](contracts/definitions.md) § 4.5) |
| toolchains | each environment declares its own, proven inside the prefix before any source is fetched; every process femkit starts for an environment — femkit's own Python and a job's run script among them — begins from one clean start, a declared pass list, then enters by the manager's own `run` or the target's preamble and activation ([ADR 0006](decisions/0006-toolchain-first.md), [ADR 0026](decisions/0026-environments-under-condas-management.md); [`contracts/definitions.md`](contracts/definitions.md) § 4.6, [`contracts/envs.md`](contracts/envs.md) § 4.4) |
| build generator | femkit names no CMake generator; each project's own default applies ([ADR 0007](decisions/0007-cmake-default-generator.md); [`contracts/definitions.md`](contracts/definitions.md) § 4.2) |
| package manager | the conda family (conda and mamba; micromamba once its kind file is written), driven only through declared manager kinds: conda manages — every environment an ordinary named one, `femkit` and `femkit-<name>`, where it keeps environments, with its cache, its list and its activation — and the recipe decides, the person's settings that would change what goes in set aside by the manager's own flags or refused ([ADR 0026](decisions/0026-environments-under-condas-management.md); [`contracts/definitions.md`](contracts/definitions.md) § 6, [`contracts/envs.md`](contracts/envs.md) §§ 1, 4.4) |
| an installed environment | is read with the manager its manifest says built it; another manager named leaves it as built ([`contracts/envs.md`](contracts/envs.md) § 2) |
| definitions | engines, environments, managers and schedulers are data under a schema; adding an engine adds data and one small adapter ([`contracts/definitions.md`](contracts/definitions.md) § 1) |
| a shipped definition | is never overridden by a person's copy; a machine that needs another value gets it as a declared option, chosen in `config.toml` ([`contracts/definitions.md`](contracts/definitions.md) § 1) |
| schedulers | SLURM first, its language declared in a scheduler kind file ([`contracts/jobs.md`](contracts/jobs.md) § 7) |
| design basis | state machines: state observed from durable facts, one closed table per machine, operations as event logs ([`contracts/framework.md`](contracts/framework.md) § 3) |
| layers | surfaces → registry → domains → core, the programs and readers that run inside an environment the lowest of the domains; each one-way rule has one home, held by design and by review, and no test reads code ([`contracts/framework.md`](contracts/framework.md) § 1, [`contracts/testing.md`](contracts/testing.md) § 3) |
| requests, records, outcomes | execution runs the request; what a machine record measured is shown, never a veto; a missing statement, or one that contradicts the record, is refused ([`contracts/framework.md`](contracts/framework.md) § 4) |
| refusals | each of a kind, with a code and the subject it is about; something the work needs and nobody stated is `Unstated`, naming what does not exist a `UsageError`, making what exists already `Refused` ([`contracts/core.md`](contracts/core.md) § 9) |
| results | each a report — its rows, findings and next steps as data — that the terminal writes and the page draws ([`contracts/web.md`](contracts/web.md) § 7.7) |
| surfaces | the command line (click) and the web page (flask, with a React application built in the `web` environment and shipped in the package), both generic adapters over the same operations ([ADR 0009](decisions/0009-web-front-end.md); [`contracts/api.md`](contracts/api.md), [`contracts/web.md`](contracts/web.md)) |
| serving | on a cluster login node the web server listens on a Unix socket; its token travels in the address's fragment, never in a cookie; a supervisor whose application exits by itself ends too ([`contracts/web.md`](contracts/web.md) §§ 4–5) |
| field visualization | interactive field rendering is ParaView's; an engine writes its own fields, ParaView-readable where its input writer asks for it, and femkit checks they are there and reads none of them; femkit runs the person's observables functions, which reduce each case's solution, and the analyses ([ADR 0002](decisions/0002-paraview-visualization-boundary.md), amended by [ADR 0025](decisions/0025-one-engine-per-study-observables-after.md)) |
| the person's files | femkit changes no file the person wrote, but through the page's plain text editor, saving exactly what they typed, for a project their own tools may not reach ([ADR 0018](decisions/0018-one-graph-from-description-to-execution.md)); it writes only the new files they ask for — a template, an imported material, the library's first copy of femkit's materials — and its own outputs — cases, runs, results; `config set` sets femkit's own settings ([ADR 0015](decisions/0015-the-persons-files.md); [`contracts/projects.md`](contracts/projects.md) § 7) |
| templates | one set, in `femkit/data/templates/`: the settings file's, and whole, working projects written by hand, which are also femkit's examples, its formulations' benchmarks and its tests' projects; a new project is a copy of one, or of one of the person's projects ([ADR 0015](decisions/0015-the-persons-files.md); [`contracts/projects.md`](contracts/projects.md) § 7) |
| the page | shows a project's structure, each part's text with the help of every key, its findings and the templates to copy; the graph and the help are derived from the files and the schemas, never stored ([ADR 0010](decisions/0010-describe-the-system.md) decision 4, [ADR 0015](decisions/0015-the-persons-files.md); [`contracts/web.md`](contracts/web.md) § 2) |
| where nodes stand | the page's alone, never project data and never stored: a position says nothing of what connects to what; the diagram arranges itself and the person moves blocks freely ([`contracts/projects.md`](contracts/projects.md) § 2, [`contracts/web.md`](contracts/web.md) § 2.2) |
| projects | one projects root, set in `config.toml`, holds the global material library and the projects; a command names a project as a whole; a project is one folder, which moves whole ([ADR 0011](decisions/0011-project-structure.md); [`contracts/projects.md`](contracts/projects.md) § 1) |
| a project's parts | a fixed tree, each part in its own file; a component is one geometry, its contract and its material assignment; physics and mesh recipes name groups, and a study pairs them with a component, the pairing checked before anything runs; an observables part reads studies; a name is a path, and a folder only groups ([ADR 0011](decisions/0011-project-structure.md), [ADR 0025](decisions/0025-one-engine-per-study-observables-after.md); [`contracts/projects.md`](contracts/projects.md) §§ 2–3) |
| the layout | each part kind's folder, file, schema, writer and scope, declared as data and read by the door, the graph, the checks and the page ([ADR 0011](decisions/0011-project-structure.md); [`contracts/projects.md`](contracts/projects.md) § 4) |
| one door | only `femkit/projects/` forms a path in a project or reads its files; each part loads on its own, and a broken one is a finding on it ([ADR 0011](decisions/0011-project-structure.md); [`contracts/projects.md`](contracts/projects.md) § 6) |
| project commands | `project new`, `project list`, `project check`, `project graph`; `project save` of the page alone ([`contracts/models.md`](contracts/models.md) § 11.1; [`contracts/workflow.md`](contracts/workflow.md) § 7) |
| geometry | the person's Gmsh script, wrapped by a contract checked before and after it runs; a case's pipeline is stages — geometry, mesh, solve — each wrapped so ([`contracts/workflow.md`](contracts/workflow.md)); a CAD file is imported by a script under the same contract ([ADR 0013](decisions/0013-geometry-scripts.md); [`contracts/geometry.md`](contracts/geometry.md) §§ 2–4, 9) |
| meshes | a mesher is a program of the mesh stage, declared as a contract and run in the environment that provides it; the mesh recipe names it, never the study — Gmsh, which both engines take, Netgen, which NGSolve takes above geometry order 1 — the engine chosen to solve checked to take it, and a pass-through takes a mesh the person's script makes ([ADR 0012](decisions/0012-one-mesh-path.md), [ADR 0017](decisions/0017-netgen-curves-ngsolve-geometry.md), [ADR 0018](decisions/0018-one-graph-from-description-to-execution.md), [ADR 0025](decisions/0025-one-engine-per-study-observables-after.md); [`contracts/workflow.md`](contracts/workflow.md) § 2.3, [`contracts/geometry.md`](contracts/geometry.md) § 6) |
| curved geometry in NGSolve | above geometry order 1, Netgen meshes the geometry in a stage of its own in the `ngsolve` environment, and the solve curves it from the true shapes ([ADR 0017](decisions/0017-netgen-curves-ngsolve-geometry.md); [`contracts/geometry.md`](contracts/geometry.md) § 8) |
| execution | the person's earlier tool's run design, copied: calculation folders, a run script that enters its environment as the target's record says, runs observed from their records, every launch an address on its machine, a monitor beside every run ([ADR 0016](decisions/0016-every-step-runs-from-a-run-folder.md); [`contracts/jobs.md`](contracts/jobs.md)) |
| workflow | one graph from description to execution: a case's stages declared as data, typed artifacts between them, each stage's calculation folder written from its listed context; each study its own stages, its geometries and meshes serving every engine that solves it and each engine's solves kept apart; the page draws it, and femkit does no stage's work itself ([ADR 0018](decisions/0018-one-graph-from-description-to-execution.md), [ADR 0020](decisions/0020-each-engine-its-own-stages.md), [ADR 0025](decisions/0025-one-engine-per-study-observables-after.md); [`contracts/workflow.md`](contracts/workflow.md)) |
| reading a project | a project's parts are read in sections, from what they share to what they compute — Definitions, Component, Physics, Mesh, Study, Results — and every block of a diagram shows one plain word of a closed list; loading and checking keep the chain's order ([ADR 0019](decisions/0019-section-order-block-states-axes-together.md); [`contracts/projects.md`](contracts/projects.md) § 4, [`contracts/web.md`](contracts/web.md) § 7.6) |
| getting ready to run | one prep step, `study prep`: the definitions computed and every value validated, the cases, the machine, the study's stages and their jobs, planned whole before anything is written — the command line's and the page's one entry; a launch sends what prep wrote ([ADR 0022](decisions/0022-one-prep-step.md); [`contracts/workflow.md`](contracts/workflow.md) § 7) |
| shared values | definitions: each a typed number with its unit, or computed by a Python function in the project's `definitions.py` reading `defs.<name>`; femkit converts every unit, and no physical quantity in the person's files is written as text ([ADR 0021](decisions/0021-definitions.md); [`contracts/models.md`](contracts/models.md) § 3) |
| sweeps | axes are crossed, a crossing of classes saying why; values one formula relates are that formula; values no formula relates step together in a named group of one class ([ADR 0019](decisions/0019-section-order-block-states-axes-together.md); [`contracts/models.md`](contracts/models.md) § 5.1) |
| the geometry file | `geometry.xao`, the OpenCASCADE shapes with their groups, written by the person's script where femkit names it ([ADR 0016](decisions/0016-every-step-runs-from-a-run-folder.md) decision 13; [`contracts/geometry.md`](contracts/geometry.md) §§ 2, 10) |
| calculations | one solver-neutral model in a closed list of formulations, each with its science document and benchmark set, matched against each environment's declared abilities; every limitation is shown, decided or customized at a declared extension point ([ADR 0008](decisions/0008-one-model-declared-abilities.md); [`contracts/models.md`](contracts/models.md) §§ 4, 6–8) |
| formulations | a family — the equations — and a step kind — the kind of calculation — each declared as data; several physics in one engine are solved in turn, as a study's steps, or together, joined by declared couplings ([`contracts/models.md`](contracts/models.md) § 4) |
| each step's environment | its own: definitions in `model_prep`, the geometry in `gmsh`, the mesh in its recipe's mesher's, each output translator in its own, the observables in `postprocess`; only the solve is engine-specific ([ADR 0025](decisions/0025-one-engine-per-study-observables-after.md) decision 1; [`contracts/workflow.md`](contracts/workflow.md) § 2) |
| the engine that solves | named by no file: chosen when a study is solved, `study prep --engine`, and switched at any time; one engine solves a run, every engine the same cases, each engine's solves kept apart; what only one engine has stated under its name, `[solve.<engine>]`; physics in different engines are different studies, one taking another's result — after M9; comparing engines is an analysis of two engines' solves of one study ([ADR 0025](decisions/0025-one-engine-per-study-observables-after.md); [`contracts/models.md`](contracts/models.md) §§ 4.5, 5.1, 10.2) |
| a case | the component, the physics, the materials' data, the mesh recipe, the numerics and one axis point; nothing of an engine enters it — what is bound to one lives in the study's `[solve]`, under the engine's name — and nothing observed enters it ([ADR 0008](decisions/0008-one-model-declared-abilities.md); [`contracts/models.md`](contracts/models.md) § 5.3) |
| proof | an ability counts once proven in that environment by its formulation's benchmark set; a result resting on an accepted unproven line is `unverified`, and comparisons refuse it ([ADR 0008](decisions/0008-one-model-declared-abilities.md); [`contracts/models.md`](contracts/models.md) §§ 6.3, 10.1) |
| observables | after the study: an observables part reads any studies whose components promise the groups it takes; each observable is a typed value, as a definition is — the definitions and groups it takes, its type and unit — computed by the person's function in `observe.py`, in femkit's `postprocess` environment, with the packages its project declares; the function is handed `case` — the finished solve run, its values, its groups with their regions, its study and engine — and reads the engine's files itself, or a standard form of them an output translator gives — a party with its own contract — femkit reading a solve's log and status alone, converting nothing and checking what it returns; a stage of its own after each solve, so a solve never depends on what is observed ([ADR 0025](decisions/0025-one-engine-per-study-observables-after.md); [`contracts/models.md`](contracts/models.md) §§ 5.2, 9.1, 10.1) |
| stored outputs | every declared output femkit keeps — a study's computed definitions, each case's observables, what a translator gives — is one store, the one door for netCDF: one writer through xarray, one reader through netCDF4, one process-wide lock around netCDF-C; each value a number, a complex number or an array over the case's own dimensions, its `schema`, metadata and provenance in the file by the CF conventions, never in a file beside it, and no time, so the same result is the same bytes ([ADR 0025](decisions/0025-one-engine-per-study-observables-after.md) decision 6; [`contracts/models.md`](contracts/models.md) § 3) |
| names | "translator" is an output translator alone; an engine's code that writes its solver's input is its input writer; a stage turned into its calculation folder is folder writing ([ADR 0025](decisions/0025-one-engine-per-study-observables-after.md) decision 10) |
| coordinates | a physics and a mesh recipe carry each coordinate's unit; only the geometry script's own numbers are bare ([`contracts/models.md`](contracts/models.md) § 3) |
| materials | femkit's own format, one property list naming each property once and in each engine and source; a project's own material first, then the global library's, `GLOBAL/` naming the global one; every case holds the data it used; an importer keeps the source and writes a new material, never into one ([ADR 0014](decisions/0014-materials.md); [`contracts/materials.md`](contracts/materials.md)) |
| material data | a dataset without its source, convention or range is a finding while it is written, and refused by `study prep` ([`contracts/materials.md`](contracts/materials.md) § 3) |
| material forms | a dataset is a value, a table with its digest, or a dispersion model from a closed list — first `sellmeier` and `drude_lorentz`; its meaning, conventions and conversions are one science document ([`contracts/materials.md`](contracts/materials.md) §§ 2–3; [`science/material-data.md`](science/material-data.md)) |
| a prepared case's folder | a job's calculation folder, in the project's run folders ([`contracts/jobs.md`](contracts/jobs.md) § 1, [`contracts/projects.md`](contracts/projects.md) § 2) |
| a test's definitions | a test points femkit at definitions of its own with `FEMKIT_DEFINITIONS_DIR`; nothing else sets it ([`contracts/testing.md`](contracts/testing.md) § 2.1) |
