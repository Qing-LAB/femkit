# ADR 0025: one engine solves a run, chosen when it is solved, and the observables come after the study

**Role:** ADR

**Status:** accepted (2026-11-27), decisions 5–8 as the person settled them
that day after its design review, and decision 1's environments and the
names of decision 10 as they settled them after the second, with the
environment's name, `postprocess`; decisions 1 and 3 rewritten, and
decision 9 withdrawn, as the person settled them later that day: a study
names no engine, the engine is chosen when the study is solved, and no
study is built on another. Built: a study naming no engine, `study prep
--engine`, the mesh recipe's mesher, the observables part and the order;
the solve, observe and translate stages with M6; studies feeding studies
after M9.
It amends [ADR 0002](0002-paraview-visualization-boundary.md) (decisions
4–5 and 8: a case's reductions are the person's functions, and femkit reads
no field an engine writes); [ADR 0008](0008-one-model-declared-abilities.md)
decisions 4 and 6 (decision 1) and 10 (decisions 4–8);
[ADR 0011](0011-project-structure.md) decisions 2–3 (decision 4);
[ADR 0012](0012-one-mesh-path.md) and
[ADR 0016](0016-every-step-runs-from-a-run-folder.md) decision 11 — the
study naming its mesher per environment — and ADR 0016's consequences on a
study's resources and jobs per environment (decision 1);
[ADR 0019](0019-section-order-block-states-axes-together.md) decision 1's
rank of an observable set and its last consequence (decision 4);
[ADR 0020](0020-each-engine-its-own-stages.md) decision 1 (decision 1);
[ADR 0021](0021-definitions.md) decisions 1 and 6 (decision 6), 2 (decision
5) and 7's list of what `definitions.py` may import (decision 5); and
[ADR 0022](0022-one-prep-step.md) decisions 2, 4 and 10 (decision 1)

**Authority:** the reasons and the alternatives only; once accepted,
[`models.md`](../contracts/models.md) §§ 1, 3, 5, 9, 10 and 11, [`projects.md`](../contracts/projects.md)
§§ 2–4 and 6, [`workflow.md`](../contracts/workflow.md) §§ 2, 4–7,
[`geometry.md`](../contracts/geometry.md) § 6, [`core.md`](../contracts/core.md)
§ 4, [`envs.md`](../contracts/envs.md) §§ 1–2 and
[`web.md`](../contracts/web.md) § 2.2 own what it decides

## Context

The person, 2026-11-27, reading the project as a graph, asked why every part
points into the study, the study standing last: in the order they work, a
study produces the raw solution of its equations, and what is observed comes
after it — "the 'result' or 'observable' is done after the study which will
generate all the raw solution from the equations, and the result/observable
would do its own work by taking the study's data as input and other inputs as
well (such as … definitions/constants, and components from the geometry)".
They asked how a multiphysics calculation fits, Elmer's electrostatics feeding
another engine's flow: "should we set one engine for one study, and allow
study to feed each other such that we can allow such coupling across engine?
i can hardly think of a situation where tight coupled equations can be
separated into two engines". On this proposal: "this frees the complexity of
coupling multiple studies (such as multiple equations that need to feed one
another in a loop) into the study organization, and observation is placed
lastly which would be a user's script that takes the data set and other
parameters as input for post processing".

Today a study binds several environments, `[environments.<e>]`, and the whole
study runs on each — the cross-engine check comparing them; and a study names
its observable sets, which the engine computes during or after the solve
(`models.md` § 5.2, § 10.1), so a changed set prepares the solve again.

Three reviewers then read the contracts written to this decision. The
person, 2026-11-27, settled what they left open: where every observables
script runs — one environment of femkit's for analysis, to which the person
may add packages, the solvers' staying solver-only; how the two studies of a
cross-engine check are written without writing one study twice — a study
built on another; and what the script is handed of a solve — "it is not
femkit's job to manage output/input - that's the engine and user script's
job"; femkit's role, in their words: "femkit provide the hierarchical support
and contractual agreement to bind all parties to work on the problem". And
on what femkit keeps of the person's outputs: "i think we should propose
netcdf, xarray etc for full data storage as a common baseline with meta data
fully saved with it (or with accompany meta data file as standard practice).
this is more like a contract of normalizing output (that's again the reason
we support script and definition of input/output for each components)". And
on an engine's output a script cannot use as it is: "we can have translation
layers/nodes in between input/output such that we can have some standarized
way to provide support in case engine out could need additional steps
before the final user script can use it, such as translating from mesh into
grid etc".

Three more reviewers read the contracts again. The draft had a study's
`[engine]` hold its mesher and its meshing job beside its solves, and a study
built on another inherit `[engine]`. The person, 2026-11-27: "the only thing
that can be physics/equation specific is the study section, all the others
are tied to environment created specific for those steps"; and, on the
draft, "i don't see how engine is used anywhere but the study?? mesh has its
own env and that's it. why are you mixing it with study? and why is engine
'inherited'??". They settled, the same day, that the packages a project's
scripts need travel with the project, and that "translator" names one thing.

The build that followed had each study name its engine, so every template
study became two, one per engine, the second built on the first by a key,
`from`. The person, 2026-11-27, reading them: "why … do we have study
design started with an engine? engine is only assigned when we try to solve
it or start calculation and it can be switched at any time so why … is
this duplicated … representation shown here and for what … purpose?
unless you are trying to showing coupled solution of two studies". They
chose that the engine is chosen at solve time, and that `from` is
withdrawn.

## Decision

1. **A study is the problem's design and names no engine; one engine
   solves a run, chosen when it is solved; each step's environment its
   own.** The person, above: "engine is only assigned when we try to solve
   it or start calculation and it can be switched at any time". The engine
   is chosen when the study is prepared to solve, `study prep <study>
   --engine <engine>` — a choice of which party solves, never a value of
   the calculation — and may be switched at any time: each engine's solves,
   and what is observed of them, are kept apart, keyed by the engine, while
   the study's cases, geometries and meshes are made once and serve every
   engine. "One engine" means only that one engine solves a run, and that
   nothing couples two engines inside a study. The solve is the one step
   bound to an engine, and runs in that engine's own environment, its
   `-cuda` twin where its resources ask GPUs; the study's `[solve]` holds its
   job's `resources`, whatever engine solves, and what only one engine has —
   its options, decisions, customizations and truncations — goes under that
   engine's name, `[solve.<engine>]`, applying only when it solves. Every
   other step runs in the environment that is its own, as the person said
   earlier that day: "the only thing that can be physics/equation specific
   is the study section, all the others are tied to environment created
   specific for those steps" — a project's definitions in `model_prep`; the
   geometry in `gmsh`; the mesh in its mesher's, the mesher — Gmsh, Netgen —
   stated by the mesh recipe, never by the study ("mesh has its own env and
   that's it"); each output translator in the one declared for it; the
   observables in `postprocess`. The study's `[meshing]` holds the meshing
   job's `resources` alone. Whether an engine can take the mesh the study's
   recipe makes, through a hand-over where one is needed, is checked when
   that engine is chosen; `project check` shows the engines that can, as a
   fact. `[environments]` goes.
2. **Coupling lives in how studies are organized.** Physics solved together —
   tightly coupled equations — are steps of one study, solved by one engine,
   on one mesh (ADR 0019 decision 4). Physics in different engines are different
   studies, a study taking a result of another as an input, case by case,
   and a loop of studies feeding each other until they settle stated where the
   studies are organized. Built after M9, with the first such calculation;
   until then, a study takes no other study's result.
3. **Comparing engines is an analysis of one study's solves.** The
   cross-engine check compares two engines' solves of the same study, case
   by case, each case with itself, by its ID: one case, two solve runs, two
   engines (`models.md` § 10.2). The pairing of two studies by physical
   point, written for two engines' studies, goes with them. At a geometry
   order above 1 NGSolve wants Netgen's mesh, which Elmer cannot take
   today; whether a hand-over gives Elmer Netgen's mesh is not measured
   (plan § 4, M6, M9).
4. **Observables come after the study.** An observables part names the
   studies it reads — any whose components promise the groups it takes: a
   convergence study and a sweep alike. A study names no observables. The
   part is evaluated per case and per engine's solve of it, after the case
   is solved, as a stage of its own, which rides that solve's job after the
   solve and can be run again alone — its inputs
   the case's finished solve run, a typed artifact, and exactly what each
   function's `takes` lists of the case's values (the definitions at its
   point) and of the groups as the built geometry holds them; its outputs
   typed values, kept as the case's results
   as a study's definitions are kept. Adding or changing an observable runs
   that stage again, never the solve; a solve no longer depends on what is
   observed, and an error in the part holds back its own stages alone.
5. **An observable is declared as a definition is, and computed by a
   script.** The person, on this ADR: "observable is similar to any definition
   components where we define what it would take and what it would generate,
   and then there is always a script associated with it … the contract would
   regulate/normalize the format/input and output for the script, and the user
   has the flexibility to work this out with a controlled environment. so in a
   sense the result would need a environment associated with it so the script
   can run correctly". So the observables part's file declares, for each
   observable, what it takes — definitions by name, groups of the component —
   and what it gives — its name, its type and its unit, as a definition's
   (ADR 0021) — and names the function of its script, `observe.py`, that
   computes it; there is no observable without its function. The contract
   regulates both sides of the script: what it is handed — one object,
   `case` — and what it returns, in SI, checked against its declared type and
   dimensions, its unit the person's promise as a definition's is. Every
   part's script runs in one **environment** of femkit's, `postprocess` —
   numpy, scipy, matplotlib, netCDF4, xarray and meshio — declared,
   installed by default and validated by femkit; a project declares the
   packages its scripts need beyond them, in its project file, so they
   travel with it, and each machine installs them into its `postprocess`;
   the solvers' environments stay solver-only, and a part names no
   environment. What a script imports is checked against `postprocess`'s
   declared modules and the project's packages before any solve, as `definitions.py`'s is against
   `model_prep`'s declared modules. femkit runs the script there, in a
   process of its own with its time limit, and records its hash. A proof
   never rests on a package a project adds.
6. **One store for every declared output femkit keeps** (the person,
   2026-11-27, above), as the person's earlier tool keeps its netCDF: a
   study's computed definitions, each case's observables and what each
   translator gives, written as netCDF through xarray by one writer, and read
   by one reader in femkit, through netCDF4 — the one door for netCDF in
   femkit; any tool opens them (`xarray.open_dataset`). Every call into the
   netCDF-C library in the control process, whose web server reads in
   threads, holds one process-wide lock: the earlier tool measured two
   threads inside it at once crashing the process; the writer runs in a
   process of its own, with one thread. Each file states its
   `schema` as an attribute, checked when it is read. The metadata is in the
   file, by the CF conventions: each variable its `units`, its description
   (`long_name`), its declared type and its dimensions; each file its
   provenance — the case, the study, the engine, the environment, the run
   and the script's hash. No time is written in it: the run's records hold
   the time, so the same result is the same bytes. In the file, so the
   numbers and their description never drift apart and a file copied alone
   still says what it holds. A typed value — a definition's or an
   observable's — is a number, a complex number, or an array with named
   dimensions and coordinates over the case's own dimensions: a profile
   along a line, a map on a plane; a function may return an xarray
   DataArray, which femkit checks against its declaration — type and
   dimensions — before writing it. A spectrum is an analysis over a sweep's
   cases, never a case's observable.
7. **Output translators between the solve and the script** (the person,
   2026-11-27, above). What each engine's solve writes is declared by the
   engine, as a mesher declares what it writes — its own files, which femkit
   never converts. An output translator is a node with a declared contract,
   as a hand-over is: what it takes, an engine's solve output or another
   translator's; what it gives, a standard form — the solution's fields on
   the mesh, or resampled onto a grid — as netCDF with its metadata in the
   file (decision 6). It is Python under the one way femkit runs a person's
   Python — one runner, one reader of its functions, one check of what they
   return, the one store for it — whether femkit ships it or the person
   writes it, the person's own a part kind of the project, stating no program
   of its own. Each runs in the environment declared for it; which one the
   standard translators need — an NGSolve solution is read only in
   `ngsolve` — is measured and settled with M6. Each runs as a stage per
   case, between the solve and the observe stage, drawn as every stage is.
   An observables part's `takes` may name a standard form; before anything
   runs, femkit checks that each engine's output reaches it through
   the translators, so through translators one script serves every
   engine's solves. Built with M6.
8. **The solution is the engine's and the script's.** A function is handed
   `case`: the location of the case's finished solve run, the definitions
   and groups its `takes` names — each group with its place and the engine's
   own region IDs in that case's mesh — the study and the engine that solved
   it, and the standard forms it takes. The engine writes whatever files it
   writes, and the script reads what it needs of them, loading, extracting
   and interpolating as it likes. What femkit reads of a solve is its log
   and its status — whether it finished and whether it converged — and
   whether the files its engine declares are there; it never reads a field's
   values, and neither samples, converts nor verifies one; it checks what
   each function returns. A standard translator resampling onto a grid is a
   translator, a party with its contract, not femkit. One script serves
   several engines' solves through translators giving one form, or where
   the person writes it to read each engine's files.
9. **Withdrawn: a study built on another.** It was written so the two
   studies of a cross-engine check need not be written twice, each stating
   its own `engine` and `[solve]` and taking the rest from its base, `from`.
   With the engine chosen when a study is solved (decision 1), one study
   serves every engine, and nothing is left for a second study to take: the
   person, above: why is this duplicated? No study builds on
   another, and nothing marks what a part takes from a base.
10. **One name for each thing.** "Translator" names an output translator
    alone — the node between the solve and the person's script — and the
    stage kind `translate`. The engine's code that turns a case into its
    solver's input is the engine's **input writer**; turning a stage into
    its calculation folder is **folder writing**. `takes` names what an
    observable or a translator takes; a step that uses another's result
    takes from it.

## Alternatives not chosen

- **Several engines in one study, all steps on each**: the cross-engine check
  inside one study, at the cost of every study carrying several engines'
  bindings, and no place for physics split across engines.
- **Steps of one study on different engines**: a coupling across engines
  hidden inside a study; the person sees tightly coupled equations as one
  engine's work.
- **The engine binding the meshing** — the study naming its mesher and its
  meshing job under its engine: a mesh tied to an engine that does not make
  it, where the mesh has its own environment and its recipe says how it is
  made.
- **Observables computed during the solve**: the most accurate for some
  quantities, but a changed observable prepares the solve again.
- **A declared form femkit evaluates** (a quantity, where, a reduction, a
  unit, without a script): withdrawn — every observable is declared for its
  inputs and outputs and computed by the person's function, as a computed
  definition is.
- **Each part naming the environment its script runs in**: a fact stated in
  every part, and a solver's environment named there would gain what analysis
  needs; one environment for analysis keeps the solvers' solver-only.
- **The packages a script needs set in femkit's configuration**: a machine's
  setting a project's results rest on, which a copied project does not
  carry.
- **The solution handed in one form of femkit's, whatever engine solved
  it** — sampled at its integration points, or converted to a common format,
  its accuracy measured: one script for every engine without the person
  writing for each, but femkit would do the engines' and the scripts' work,
  managing data that is theirs, and what it sampled away no script could
  recover. A conversion the script needs is an output translator's, a party
  with its own contract (decision 7).
- **A study naming its one engine**, `engine = "<name>"`, built at first: the
  same problem written once per engine — two studies, the second built on
  the first by `from` — where the engine is only a choice of which party
  solves, made when the study is solved and switched at any time (the
  person, above).
- **The second study of a cross-engine check written whole, or built on the
  first**: withdrawn with the engine in the study — two files for one
  problem either way.
- **Results as JSON, `result.json`**: JSON declares no number's type, holds
  no complex number, and holds an array only as nested lists with no
  dimension's name or coordinate — the reasons the definitions' values are
  netCDF already (ADR 0021 decision 6).
- **Metadata in a file beside each data file**: the person's alternative,
  but two files that must be copied, kept and changed together, and drift
  apart when one is not; CF attributes inside the file are what netCDF's
  readers already show.

## Consequences

- **Files**: every study's `[environments.<e>]` becomes `[solve]` and
  `[meshing]`, naming no engine — a file writing `engine` is told that the
  engine is chosen when the study is solved, with the command; a mesh recipe
  states its `mesher`; an observables part becomes a folder,
  `observables/<o>/`, its file naming its studies and declaring each
  observable's inputs, outputs and function, beside `observe.py`; a study's,
  a recipe's and an observables part's `schema` become 2, and a file of the
  old observables shape is told so, never left a stray; each template holds
  one study, which every engine solves; the templates, the manual and the
  reference pages change with them. `study prep --engine` chooses the
  engine; which engines `formulation verify` solves a benchmark in is
  settled with M6.
- **Environments**: `postprocess` joins the tool environments — numpy,
  scipy, matplotlib, netCDF4, xarray and meshio — and it and `model_prep`,
  which gains xarray for the one writer, are installed by default; a project
  file gains `[postprocess] packages`, installed into `postprocess` on each
  machine — every project's under the projects root by one install, each
  project file's table read alone, through its schema, never by opening the
  project, so a file whose table does not read adds nothing and is noted in
  the install's report. A package a project adds is delivered into the
  existing `postprocess` by `env install postprocess` — installed into its
  prefix, its lock saved again, its manifest recording it — never by a
  removal and a rebuild: `outdated` stays for a change of femkit's own
  declared set, and the install fingerprint is that set alone, so an observe
  stage's identity, which holds it, holds femkit's set and its own project's
  packages alone, never another project's.
- **Stored outputs**: `computed/<study>/definitions.nc` is written by the
  one writer, its metadata by the CF conventions; each case's observables
  are a netCDF file of the same writer in its observe stage's run; an
  observable may be an array — a profile or a plane's samples no longer
  wait for M9.
- **Order**: an observables part ranks after the study it reads (ADR 0019's
  rank: what a part is made from comes before it); the graph's wire runs
  study → observables by the data itself, and the page's turned wire
  (`canvas.produces`) is withdrawn.
- **Workflow**: an observe stage after each case's solve (M6), its
  identity `workflow.md` § 4's, its input the solve's run as a typed
  artifact; `run reduce` becomes that stage. A study's solves in one engine
  are one job, as its meshing is (ADR 0016 decision 4). A study's
  observables leave the solve's manifest and staleness (`models.md` § 9.5).
  A stage kind declares where its environment comes from and the part whose
  files it brings; a geometry or a mesh stage holds nothing of an engine and
  serves every engine, and a solve stage, and each stage after it, is keyed
  by the engine that solves.
- **Translate stages** (M6): the `translate` kind, the standard translators
  in `femkit/data/translators/` and the person's own as a part kind, each
  engine's declaration of what its solve writes, `takes.forms`.
- **Names**: the engines' input writers, and folder writing —
  `workflow/translate.py` renamed with the build.
- **Built now**: the study's `[solve]` and `[meshing]`, naming no engine,
  `study prep --engine` and the engines that can solve a study, the recipe's
  `mesher`, the observables part naming its studies, the order and the
  graph. **With M6**: the translate and observe stages, the script
  run, the results. **After M9**: studies feeding studies.
