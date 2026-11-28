# femkit documentation

**Role:** index
**Status:** current
**Authority:** the one list of documents, and the rules every document
follows; [`../PROJECT_CONTRACT.md`](../PROJECT_CONTRACT.md) says which
document wins

This is the one index. Every document in the repository has exactly one line
here (§ 5), added in the same change that adds, moves or removes it. A
document not listed here does not exist; review looks for files without a line
and lines without a file.

## 1. Structure

Documents are grouped by what a reader is working on; the header says what
kind of document each is.

| folder | holds |
|---|---|
| *(root)* | this index; [`design.md`](design.md) — mission, design values, scientific-data rules, settled choices |
| `contracts/` | one contract per package, named after it, with the exceptions [`contracts/framework.md`](contracts/framework.md) § 1 names |
| `reference/` | pages generated from the schema models by `femkit schema docs`; never edited by hand |
| `science/` | equations, assumptions, validity limits, citations, observable definitions |
| `decisions/` | ADRs, `NNNN-short-name.md`, one settled choice each |
| `process/` | how work is done: the order of work, design discipline, rules for code |
| `plans/` | one file, [`plans/plan.md`](plans/plan.md): everything not built yet |
| `manual/` | the user manual: for the person using femkit — what to type, what to write, what femkit shows — rich in examples and diagrams |
| `assets/` | images the documents and the README show |

## 2. Rules for documents

- **D1 — Header.** Every document begins with `Role`, `Status` and
  `Authority`. `Role` is one of the table below; `Status` says what is true
  now (`current`, or `current; what is not built yet is marked so`);
  `Authority` names what the document decides, and nothing else.
- **D2 — Present tense.** A document says what is true now. What is not built
  is marked so in one sentence that names its section of the plan; planned
  behavior is never described as if it existed.
- **D3 — One plan.** Every open item lives in [`plans/plan.md`](plans/plan.md)
  and nowhere else. A contract states its rule and points to the plan for
  status. The plan shrinks as work lands and keeps no record of it.
- **D4 — No history in the repository.** A review finding is fixed in the
  contract and the code; what the next step needs goes into the plan. No dated
  review, handover, evidence or changelog document is added. Superseded text
  is deleted, not archived; version control keeps it.
- **D5 — One home per fact.** A document links the authority and may summarize
  it in one sentence; it never carries a second field list, state table,
  formula, default or validation rule that could drift
  ([`../PROJECT_CONTRACT.md`](../PROJECT_CONTRACT.md) § 1).
- **D6 — Links.** A link is a relative path to the file. In a document written
  by hand, a section is named in plain text (`§ 4.2`), never as a `#` anchor,
  so a heading can change without breaking links; a generated reference page
  links its own headings, since one generator writes both.
- **D7 — Upstream is cited, not copied.** A document links upstream
  documentation, at a release where it matters, instead of restating it.

| role | contains | never contains |
|---|---|---|
| root contract | which document wins, the organizing rule, the zones | domain rules |
| index | this file: the document list and the document rules | rules for code |
| principle | durable reasons and design values | implementation status |
| contract | current interfaces, invariants, schemas, refusals; what is not built yet, marked so | work lists and dates |
| scientific background | equations, assumptions, validity limits, citations, observable definitions | software status |
| reference | generated from the schema models | promises, or text written by hand |
| process | how work is done, and the rules a review checks | rules of a single package |
| manual | for the person using femkit, in their words: what to type, write and see, step by step, each step an example the tests run, with diagrams | developer terms, femkit's internal names, a contract as the explanation, a rule no contract states |
| ADR | one decision: context, alternatives, reason, consequences | living interface documentation |
| plan | unfinished work, its order and its acceptance | claims that planned behavior exists; history |

## 3. How documents are written

- **E1 — Structure first, never append.** Before a document is changed, map
  its sections and its siblings', and put the new content where it belongs. A
  merge rewrites the combined content into one structure; it is never a
  concatenation.
- **E2 — Diagrams where they explain.** Ownership, data flow, state machines
  and sequences get a Mermaid diagram (GitHub renders it). A diagram never
  carries a field list a schema or table owns.
- **E3 — Plain language, full rigor.** Jargon is translated into plain words
  and concrete scenarios ("when you run X, Y happens"), and nothing is lost:
  every constraint, number, edge case and reason survives. A coined term is
  used only after the sentence that defines it.
- **E4 — Scientific claims carry their basis.** An equation defines every
  symbol and unit convention near its first use. A default, threshold or
  tolerance states where it comes from: a derivation, a citation or a
  measurement. A merge keeps that basis and fills it in where it is thin.

### 3.1 The manual

The manual is the one document written for the person using femkit, not for
someone changing it. Beyond the rules above:

- **M1 — The reader is a scientist using femkit.** It speaks their words: no
  internal name of femkit's — an operation, the door, a schema, a part kind,
  an address, a plan and its apply, canonical units — and every word femkit
  prints is explained in plain words the first time the manual shows it
  (`a case is one calculation: your study's settings at one point of its
  sweep`). Physics is said in physics' own terms.
- **M2 — Examples everywhere.** Every instruction is a command and what femkit
  prints back; every file the person writes has a whole example, taken from a
  template, and an example of a mistake with what femkit says about it.
- **M3 — Diagrams everywhere.** Each chapter opens with a diagram of what it
  covers, and a diagram goes wherever a flow, a folder tree or how the files
  name each other is shown (E2).
- **M4 — Accurate, by test.** Every example marked as run is run by the basic
  tests in a temporary projects root, in its chapter's order, and must print
  what the manual shows; every command and option the manual names exists;
  every command femkit has appears in it; every link resolves
  ([`contracts/testing.md`](contracts/testing.md) § 3). An example is not a
  second home of a fact (D5): the tests hold it to femkit's real output. For
  the full list of a file's keys it links the generated reference pages.
- **M5 — The person's help points here.** A key's help — a template's
  comment — and a command's help name the manual's chapter that explains
  them, never a contract or the plan; a message says what is not built yet
  in plain words, never by the plan's section
  ([`contracts/core.md`](contracts/core.md) § 2).
- **M6 — Current.** A change to what the person types, writes or sees changes
  the manual in the same change
  ([`process/conventions.md`](process/conventions.md) § 1); what is not built
  yet is said plainly, in one sentence.

## 4. Moving or merging a document

Moving or merging a document is a review, not a file move:

1. Read it against the current code, and fix what has drifted or delete it.
2. Map its structure and its new siblings' (E1); decide the shape before
   writing.
3. Merge overlaps into one home instead of carrying duplicates (D5).
4. Move open work into the plan (D3).
5. Give it its header (D1) and its line in § 5, in the same change.
6. Repoint every inbound reference — documents, code comments, tests,
   generators — in the same change, each found with `grep`.

## 5. Index

### At the repository root

- [`../README.md`](../README.md) — what femkit is, and the first commands.
- [`../PROJECT_CONTRACT.md`](../PROJECT_CONTRACT.md) — which document wins, the
  organizing rule, and where each top-level entry belongs.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — where a contributor starts.
- [`../SECURITY.md`](../SECURITY.md) — the trust boundary, and how to report a
  problem.

### Principles and process

- [`design.md`](design.md) — why femkit exists, its design values, the rules
  every stored scientific quantity follows, and the settled choices.
- [`process/conventions.md`](process/conventions.md) — the order of work,
  design discipline, rules for code and configuration, working practice.

### Manual

- [`manual/README.md`](manual/README.md) — what the manual is, the way from an
  idea to a result, how to read its examples, and the words femkit uses.
- [`manual/1-install.md`](manual/1-install.md) — installing femkit and its
  engines, the commands typed every day, settings, where femkit keeps its
  files, and every command for environments, the machine record and the web
  page.
- [`manual/2-start-a-project.md`](manual/2-start-a-project.md) — the projects
  root, the templates, project names, and a copy of one of your projects.
- [`manual/3-write-each-part.md`](manual/3-write-each-part.md) — each part of
  a project, a whole example and a mistake for each: the project file, a
  material, a component, the physics, a mesh recipe, observables, a study.
- [`manual/4-check-it.md`](manual/4-check-it.md) — reading `project check`:
  states, errors, warnings and notes, `right:` and the choices; the project
  as a graph; a file edited on the page, what the change does shown before
  it is saved.
- [`manual/5-studies-and-cases.md`](manual/5-studies-and-cases.md) — studies,
  cases, `study prep` and `case list`, new cases from a changed file, axes
  and their crossing, and the engine chosen to solve them, `--engine`.
- [`manual/6-materials.md`](manual/6-materials.md) — a material's datasets — a
  value, a table, a formula — refractive index or permittivity, data that
  varies under a static study, the library and `GLOBAL/`, and importing from
  refractiveindex.info.
- [`manual/7-geometries-and-meshes.md`](manual/7-geometries-and-meshes.md) —
  the stages each case needs before it is solved, `study prep` and `study
  flow`, each study's own copies, shared by every engine, and the job that
  makes them.

### Contracts

- [`contracts/framework.md`](contracts/framework.md) — packages and layers,
  which contract governs each concern, state machines, requests and outcomes.
- [`contracts/core.md`](contracts/core.md) — the building blocks every package
  uses: schema, directories, persistence, locks, event logs, processes, errors.
- [`contracts/api.md`](contracts/api.md) — how an operation is declared, and
  how the command line serves it.
- [`contracts/web.md`](contracts/web.md) — the web surface: its routes,
  access and serving, and the page — its vocabulary, declaration, layers,
  elements and styles.
- [`contracts/definitions.md`](contracts/definitions.md) — what femkit ships:
  the control environment, engine environments, manager and scheduler kinds.
- [`contracts/config.md`](contracts/config.md) — where configuration lives,
  and what a machine record is.
- [`contracts/envs.md`](contracts/envs.md) — how an environment is installed,
  validated and entered, and the install script.
- [`contracts/projects.md`](contracts/projects.md) — the projects root, a
  project's tree and parts, addresses, the one door every read and write
  passes through, and the check frame.
- [`contracts/materials.md`](contracts/materials.md) — the property list, the
  material format, the global and local libraries, importers; built but a
  case taking a dataset at a variable's value (plan § 4, M9) and a
  property's name in an engine's input (M6).
- [`contracts/geometry.md`](contracts/geometry.md) — the geometry script, its
  contract, mesh recipes and the mesher each names, the six places, the
  mesh's check and the hand-over to each engine; built but a built geometry
  read by `project check`, Netgen's mesher and importing (plan § 4, X).
- [`contracts/models.md`](contracts/models.md) — how a calculation is described
  once, a study naming no engine, solved by the engine chosen when it is
  solved, matched against that engine's declared and proven abilities,
  decided on, customized and prepared, and its observables computed after
  each case's solve by the person's script, kept in the one store; the
  parts, their checks — a study's `[solve]`, the engines that can solve it,
  the observables part among them — the cases, the graph and the one store
  built, the rest not yet (M5–M9).
- [`contracts/workflow.md`](contracts/workflow.md) — a case's stages,
  declared as data, each step in an environment of its own; a study's
  workflow graph; a stage's identity, state, folder writing and jobs; one
  prep step from a project to what its jobs run;
  built for the geometry and mesh stages — `study prep`, `study flow`, `case
  list`, the definitions, a change's impact and `project save`; `project
  check` reading a built geometry being built (plan § 4, X), the solve and
  observe stages with M6.
- [`contracts/jobs.md`](contracts/jobs.md) — machine records and the probe;
  calculation folders, run scripts, runs, the jobs launched from a machine
  and the monitor; built for a machine without a scheduler, a scheduler's
  submission not yet (plan § 4, M4).
- [`contracts/testing.md`](contracts/testing.md) — test tiers, isolation, what
  earns a test, and the runner.

### Reference (generated)

- [`reference/definitions.md`](reference/definitions.md) — every field of the
  shipped definition files.
- [`reference/config.md`](reference/config.md) — every field of `config.toml`.
- [`reference/machines.md`](reference/machines.md) — every field of a machine
  record.
- [`reference/parts.md`](reference/parts.md) — every field of a project's parts:
  the project file, physics, studies, observables parts, and each part
  another package registers.
- [`reference/cases.md`](reference/cases.md) — every field of a case's
  `case.json`.
- [`reference/jobs.md`](reference/jobs.md) — every field of a job request
  and a run's records, and every file of a calculation folder, a launch
  folder and a run, with its writer and readers.

### Science

- [`science/electrostatics.md`](science/electrostatics.md) — the electrostatic
  potential: its terms and symbols, equation, conditions and their signs, what
  each dimension means, derived quantities.
- [`science/electromagnetics.md`](science/electromagnetics.md) — the
  frequency-domain Maxwell problem, its validation ladder, and what a
  converged adaptive result requires.
- [`science/material-data.md`](science/material-data.md) — what a material's
  data means: the phasor conventions and the passive sign, the refractive
  index as permittivity, the spectral variables and their exact relations,
  tables, and the dispersion models.

### Decisions

- [`decisions/0001-project-name-femkit.md`](decisions/0001-project-name-femkit.md)
  — the name femkit, everywhere.
- [`decisions/0002-paraview-visualization-boundary.md`](decisions/0002-paraview-visualization-boundary.md)
  — interactive field rendering is ParaView's; femkit exports and analyses;
  amended by 0025: each case's solution is reduced by the person's
  observables functions, which femkit runs, and femkit reads no field.
- [`decisions/0003-ngsolve-stability-first-baseline.md`](decisions/0003-ngsolve-stability-first-baseline.md)
  — the NGSolve release and toolchain pinned, and why.
- [`decisions/0004-elmer-stability-first-baseline.md`](decisions/0004-elmer-stability-first-baseline.md)
  — the Elmer release and toolchain pinned, and why.
- [`decisions/0005-cuda-environments.md`](decisions/0005-cuda-environments.md)
  — GPU builds are separate `-cuda` environments, built on request.
- [`decisions/0006-toolchain-first.md`](decisions/0006-toolchain-first.md)
  — each environment declares its toolchain, proven before any source is
  fetched.
- [`decisions/0007-cmake-default-generator.md`](decisions/0007-cmake-default-generator.md)
  — femkit names no CMake generator; each project's default applies.
- [`decisions/0008-one-model-declared-abilities.md`](decisions/0008-one-model-declared-abilities.md)
  — one model, translated per engine through declared abilities, with every
  limitation shown, decided or customized.
- [`decisions/0009-web-front-end.md`](decisions/0009-web-front-end.md)
  — the web front end is a React application with React Flow, built and
  shipped in the package.
- [`decisions/0010-describe-the-system.md`](decisions/0010-describe-the-system.md)
  — the page describes the system's structure; each part's detail is
  text.
- [`decisions/0011-project-structure.md`](decisions/0011-project-structure.md)
  — a project is parts in a fixed tree, reached through one door.
- [`decisions/0012-one-mesh-path.md`](decisions/0012-one-mesh-path.md)
  — Gmsh makes every mesh, in an environment of its own; amended by 0016
  and 0017.
- [`decisions/0013-geometry-scripts.md`](decisions/0013-geometry-scripts.md)
  — geometry is the person's Gmsh script, wrapped by a contract.
- [`decisions/0014-materials.md`](decisions/0014-materials.md)
  — materials in femkit's own format, named once and per engine,
  global and local libraries.
- [`decisions/0015-the-persons-files.md`](decisions/0015-the-persons-files.md)
  — femkit changes no file the person wrote; one set of templates starts
  them.
- [`decisions/0016-every-step-runs-from-a-run-folder.md`](decisions/0016-every-step-runs-from-a-run-folder.md)
  — every step runs from a run folder by one machinery, the earlier tool's:
  judged by its check, made once per content, a case's geometry and mesh a sequence,
  every run watched by a monitor; amended by 0026: a run starts clean.
- [`decisions/0017-netgen-curves-ngsolve-geometry.md`](decisions/0017-netgen-curves-ngsolve-geometry.md)
  — curved geometry in NGSolve: Netgen meshes it, in a step of its own in
  `ngsolve`.
- [`decisions/0018-one-graph-from-description-to-execution.md`](decisions/0018-one-graph-from-description-to-execution.md)
  — one graph from description to execution: a workflow layer of declared
  stages between the project and its jobs; a plain text editor on the page.
- [`decisions/0019-section-order-block-states-axes-together.md`](decisions/0019-section-order-block-states-axes-together.md)
  — a project's parts read in sections, one plain state per
  block of the diagrams, axes that step together; a step's own mesh and the
  coupling loop's settings decided with the first coupling.
- [`decisions/0020-each-engine-its-own-stages.md`](decisions/0020-each-engine-its-own-stages.md)
  — each engine its own geometry and mesh stages, never shared between
  engines; each engine's meshing job holds its own; amended by 0025: a
  study's geometries and meshes serve every engine that solves it.
- [`decisions/0021-definitions.md`](decisions/0021-definitions.md) —
  definitions in place of parameters: each a typed number with its unit, or
  computed by a function in `definitions.py` reading `defs.<name>`, femkit
  converting units; no value written as text.
- [`decisions/0022-one-prep-step.md`](decisions/0022-one-prep-step.md) —
  one prep step, `study prep`, from a written study to what its jobs run, as
  the earlier tool's `jobset prep`; one entry for the command line and the
  page.
- [`decisions/0023-react-flow-draws-elk-places.md`](decisions/0023-react-flow-draws-elk-places.md)
  — the page's diagrams: React Flow draws, ELK places them from the graph's
  declared order, in a worker.
- [`decisions/0024-codemirror-text-editor.md`](decisions/0024-codemirror-text-editor.md)
  — the page's text editor on CodeMirror 6: findings at their keys, each
  key's help on hover, its allowed values suggested as the person types.
- [`decisions/0025-one-engine-per-study-observables-after.md`](decisions/0025-one-engine-per-study-observables-after.md)
  — a study names no engine: the engine is chosen when it is solved,
  `study prep --engine`, one engine solves a run and each engine's solves
  are kept apart — the solve the one step bound to an engine, every other
  step in an environment of its own, the mesh recipe naming its mesher; no
  study is built on another; coupling across engines is to be studies
  feeding each other, after M9; observables come after the study — the person's script on each case's
  solve run, in femkit's `postprocess` environment with its project's packages,
  output translators between them where the script needs a standard form;
  every declared output kept as netCDF with its metadata; input writers,
  folder writing and translators each named once.
- [`decisions/0026-environments-under-condas-management.md`](decisions/0026-environments-under-condas-management.md)
  — environments under conda's management, named `femkit` and
  `femkit-<name>`, their prefix the one conda names so; the recipe decides
  what goes in, the person's settings set aside or refused; one clean-start
  door for every call, run scripts and femkit itself included; amends 0016.

### Plan

- [`plans/plan.md`](plans/plan.md) — everything not built yet: where femkit
  stands, the person's workflow and the step that builds each part of it, how
  the work is done, the road of steps with their acceptance, questions and
  decisions not yet in a contract, framework debts, the bowtie model's data,
  and jobs across several nodes.
