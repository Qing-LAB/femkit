# Design principles

**Role:** principle

**Status:** current

**Authority:** mission, durable design values, the rules every stored scientific quantity follows, and the one register of settled choices, each line naming the ADR or contract that states it

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
- An option one engine needs lives in that engine's own block and never changes
  the meaning of a common field. What an engine cannot do is refused, never
  approximated silently.
- Every reported observable defines its support and reduction: point, line,
  surface, volume; average, integral, maximum or norm.
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
| toolchains | each environment declares its own, proven inside the prefix before any source is fetched; every command in a prefix starts from an allow-list of variables ([ADR 0006](decisions/0006-toolchain-first.md); [`contracts/definitions.md`](contracts/definitions.md) § 4.6, [`contracts/envs.md`](contracts/envs.md) § 4.4) |
| build generator | femkit names no CMake generator; each project's own default applies ([ADR 0007](decisions/0007-cmake-default-generator.md); [`contracts/definitions.md`](contracts/definitions.md) § 4.2) |
| package manager | the conda family (conda and mamba; micromamba once its kind file is written), driven only through declared manager kinds and run in femkit's own places, so a person's conda settings never change an environment ([`contracts/definitions.md`](contracts/definitions.md) § 6, [`contracts/envs.md`](contracts/envs.md) § 4.4) |
| an installed environment | is read with the manager its manifest says built it; another manager named leaves it as built ([`contracts/envs.md`](contracts/envs.md) § 2) |
| definitions | engines, environments, managers and schedulers are data under a schema; adding an engine adds data and one small adapter ([`contracts/definitions.md`](contracts/definitions.md) § 1) |
| a shipped definition | is never overridden by a person's copy; a machine that needs another value gets it as a declared option, chosen in `config.toml` ([`contracts/definitions.md`](contracts/definitions.md) § 1) |
| schedulers | SLURM first, its language declared in a scheduler kind file ([`contracts/jobs.md`](contracts/jobs.md) § 7) |
| design basis | state machines: state observed from durable facts, one closed table per machine, operations as event logs ([`contracts/framework.md`](contracts/framework.md) § 3) |
| layers | surfaces → registry → domains → core, the programs and readers that run inside an environment the lowest of the domains; each one-way rule has one home, held by design and by review, and no test reads code ([`contracts/framework.md`](contracts/framework.md) § 1, [`contracts/testing.md`](contracts/testing.md) § 3) |
| requests, records, outcomes | execution runs the request; what a machine record measured is shown, never a veto; a missing statement, or one that contradicts the record, is refused ([`contracts/framework.md`](contracts/framework.md) § 4) |
| refusals | each of a kind, with a code and the subject it is about; something the work needs and nobody stated is `Unstated`, naming what does not exist a `UsageError`, making what exists already `Refused` ([`contracts/core.md`](contracts/core.md) § 9) |
| results | each a report — its rows, findings and next steps as data — that the terminal writes and the page draws ([`contracts/web.md`](contracts/web.md) § 7.6) |
| surfaces | the command line (click) and the web page (flask, with a React application built in the `web` environment and shipped in the package), both generic adapters over the same operations ([ADR 0009](decisions/0009-web-front-end.md); [`contracts/api.md`](contracts/api.md), [`contracts/web.md`](contracts/web.md)) |
| serving | on a cluster login node the web server listens on a Unix socket; its token travels in the address's fragment, never in a cookie; a supervisor whose application exits by itself ends too ([`contracts/web.md`](contracts/web.md) §§ 4–5) |
| field visualization | interactive field rendering is ParaView's; femkit owns field export, metadata, numerical reduction and analysis ([ADR 0002](decisions/0002-paraview-visualization-boundary.md)) |
| the person's files | femkit changes no file the person wrote; it writes only the new files they ask for — a template, an imported material, the library's first copy of femkit's materials — and its own outputs — cases, runs, results; `config set` sets femkit's own settings ([ADR 0015](decisions/0015-the-persons-files.md); [`contracts/projects.md`](contracts/projects.md) § 7) |
| templates | one set, in `femkit/data/templates/`: the settings file's, and whole, working projects written by hand, which are also femkit's examples, its formulations' benchmarks and its tests' projects; a new project is a copy of one, or of one of the person's projects ([ADR 0015](decisions/0015-the-persons-files.md); [`contracts/projects.md`](contracts/projects.md) § 7) |
| the page | shows a project's structure, each part's text with the help of every key, its findings and the templates to copy; the graph and the help are derived from the files and the schemas, never stored ([ADR 0010](decisions/0010-describe-the-system.md) decision 4, [ADR 0015](decisions/0015-the-persons-files.md); [`contracts/web.md`](contracts/web.md) § 2) |
| where nodes stand | the page's alone, never project data; positions the person chooses to remember live in `.femkit/view.json`, read by no case, run or check ([`contracts/projects.md`](contracts/projects.md) § 2, [`contracts/web.md`](contracts/web.md) § 2.2) |
| projects | one projects root, set in `config.toml`, holds the global material library and the projects; a command names a project as a whole; a project is one folder, which moves whole ([ADR 0011](decisions/0011-project-structure.md); [`contracts/projects.md`](contracts/projects.md) § 1) |
| a project's parts | a fixed tree, each part in its own file; a component is one geometry, its contract and its material assignment; physics, mesh recipes and observable sets name groups, and a study pairs them with a component, the pairing checked before anything runs; a name is a path, and a folder only groups ([ADR 0011](decisions/0011-project-structure.md); [`contracts/projects.md`](contracts/projects.md) §§ 2–3) |
| the layout | each part kind's folder, file, schema, writer and scope, declared as data and read by the door, the graph, the checks and the page ([ADR 0011](decisions/0011-project-structure.md); [`contracts/projects.md`](contracts/projects.md) § 4) |
| one door | only `femkit/projects/` forms a path in a project or reads its files; each part loads on its own, and a broken one is a finding on it ([ADR 0011](decisions/0011-project-structure.md); [`contracts/projects.md`](contracts/projects.md) § 6) |
| project commands | `project new`, `project list`, `project check`, `project graph`, in place of `model …` ([`contracts/models.md`](contracts/models.md) § 11.1) |
| geometry | the person's Gmsh script, wrapped by a contract checked before and after it runs; the pipeline is three steps — geometry, mesh, solve — each wrapped so; a CAD file is imported by a script under the same contract ([ADR 0013](decisions/0013-geometry-scripts.md); [`contracts/geometry.md`](contracts/geometry.md) §§ 2–4, 9) |
| meshes | one path: Gmsh makes every mesh, in an environment of its own; femkit hands each engine its mesh as declared data; a mesh depends on the geometry and the recipe alone ([ADR 0012](decisions/0012-one-mesh-path.md); [`contracts/geometry.md`](contracts/geometry.md) §§ 5, 8) |
| calculations | one solver-neutral model in a closed list of formulations, each with its science document and benchmark set, matched against each environment's declared abilities; every limitation is shown, decided or customized at a declared extension point ([ADR 0008](decisions/0008-one-model-declared-abilities.md); [`contracts/models.md`](contracts/models.md) §§ 4, 6–8) |
| formulations | a family — the equations — and a step kind — the kind of calculation — each declared as data; several physics are solved in turn, as a study's steps, or together, joined by declared couplings ([`contracts/models.md`](contracts/models.md) § 4) |
| a case | the component, the physics, the materials' data, the mesh recipe, the numerics and one axis point; everything bound to an environment lives in the study ([ADR 0008](decisions/0008-one-model-declared-abilities.md); [`contracts/models.md`](contracts/models.md) § 5.3) |
| proof | an ability counts once proven in that environment by its formulation's benchmark set; a result resting on an accepted unproven line is `unverified`, and comparisons refuse it ([ADR 0008](decisions/0008-one-model-declared-abilities.md); [`contracts/models.md`](contracts/models.md) §§ 6.3, 10.1) |
| observables | computed on the engine's own discretization, inside its environment, and written to one result form ([ADR 0008](decisions/0008-one-model-declared-abilities.md); [`contracts/models.md`](contracts/models.md) § 10.1) |
| coordinates | a physics, a mesh recipe and an observable set carry each coordinate's unit; only the geometry script's own numbers are bare ([`contracts/models.md`](contracts/models.md) § 3) |
| materials | femkit's own format, one property list naming each property once and in each engine and source; a project's own material first, then the global library's, `GLOBAL/` naming the global one; every case holds the data it used; an importer keeps the source and writes a new material, never into one ([ADR 0014](decisions/0014-materials.md); [`contracts/materials.md`](contracts/materials.md)) |
| material data | a dataset without its source, convention or range is a finding while it is written, and refused by `study expand` ([`contracts/materials.md`](contracts/materials.md) § 3) |
| material forms | a dataset is a value, a table with its digest, or a dispersion model from a closed list — first `sellmeier` and `drude_lorentz`; its meaning, conventions and conversions are one science document ([`contracts/materials.md`](contracts/materials.md) §§ 2–3; [`science/material-data.md`](science/material-data.md)) |
| a prepared case's folder | a job's calculation folder, in the project's run folders ([`contracts/jobs.md`](contracts/jobs.md) § 1, [`contracts/projects.md`](contracts/projects.md) § 2) |
| a test's definitions | a test points femkit at definitions of its own with `FEMKIT_DEFINITIONS_DIR`; nothing else sets it ([`contracts/testing.md`](contracts/testing.md) § 2.1) |
