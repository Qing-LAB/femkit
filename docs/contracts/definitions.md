# Definitions — what femkit ships

**Role:** contract
**Status:** current; what is not built yet is marked so
**Authority:** the definition files shipped with femkit, their schemas,
and the boundary between declared data and engine code

## The short version

| rule | § |
|---|---|
| A **shipped definition** says what femkit supports: environments, the tools it drives, the checks that prove an install. It is reviewed source, never per-user or per-machine | 1 |
| Generic code reads declared fields and registered IDs; it never tests an engine, manager or scheduler **name** ([`conventions.md`](../process/conventions.md) § 2) | 1 |
| Every field's type, default and description is defined **once**, on a schema model; the reference page is generated from it | 2 |
| Unknown keys, wrong types and dangling references fail **at load**, before any plan or process | 2.2 |
| The control environment is two plain lists, **`channels.txt`** and **`control.txt`**, read by the install script, the package manager and Python alike | 3 |
| An engine environment declares packages, sources, builds and checks; nothing about a machine | 4, 5 |
| Everything in an environment comes from **conda-forge in one solve**, unless femkit builds it from a pinned source; nothing comes from the host, and pip installs nothing yet | 4.1 |
| How to drive a package manager or a scheduler is a **kind** file; adding a scheduler, or a manager of the conda family, is data plus, at most, a reader | 6 |

What is configured per user or per machine is not here: it is
[`config.md`](config.md). What a run writes is
[`jobs.md`](jobs.md).

## 1. What a shipped definition is

femkit ships these definitions under `femkit/data/`, beside its templates
([`projects.md`](projects.md) § 7):

```text
femkit/data/
├── channels.txt               the channel order every environment is solved with
├── control.txt                the control environment's packages, as `conda create --file` reads them
├── launcher.sh                the `femkit` command's text, which the install script fills and writes (envs.md § 7)
├── process.toml               how every process femkit starts for an environment begins — femkit's own Python too: the variables it passes and removes, how a shell function a scheduler kind declares is passed, the system PATH, what it sets (envs.md § 4.4)
├── naming.toml                every environment's name with the package manager: `femkit`, `femkit-<name>` (envs.md § 1)
├── environments/<name>.toml   one per environment, an engine's or a tool's (§ 4.7): today ngsolve,
│                              elmer, and the tools gmsh — geometry scripts and Gmsh's meshing —
│                              model_prep — a project's definitions.py, and nothing else — postprocess
│                              — every observables part's observe.py — and web
├── formulations/<family>.toml a formulation family, stated for every engine (models.md § 4)
├── meshers/<id>.toml          a mesher, a program of the mesh stage, which a mesh recipe names (workflow.md
│                              § 2.3): gmsh and given; netgen with its measurement (plan § 4, X)
├── stages.toml                the meshing sequence's name, a stage folder's made-from file, and the stage kinds —
│                              each with where its environment comes from and the part whose files it brings (workflow.md § 2.1)
├── programs.toml              every femkit program that runs inside an environment: its entry, time limit and variables, and its environment but a stage's, which its stage kind declares (envs.md § 4.4; `femkit/definitions/programs.py`)
├── artifacts.toml             the artifact types between stages (workflow.md § 2.2)
├── handovers/<name>.toml      a mesh's hand-over to an engine, keyed by the type it reads (geometry.md § 8)
├── jobs/files.toml            every file of a calculation folder, a launch folder and a run (jobs.md § 1.1)
├── managers/<kind>.toml       how to drive a package manager (conda, mamba)
├── schedulers/<kind>.toml     how to talk to a scheduler (local, slurm)
├── units.toml                 the units a value may be written in, with exact factors (core.md § 11)
├── geometry/kinds.toml        the kinds of place a group may be (geometry.md § 7)
├── properties.toml            the property list: names in femkit, each engine and each source (materials.md § 1)
├── dispersion.toml            the variables a material's data may vary with, and the dispersion models (materials.md § 2)
├── step_kinds.toml            the kinds of calculation and the variables each supplies (models.md § 4.2)
├── materials/<name>/          the shipped materials, seeding the global library (materials.md § 4)
├── importers/<source>.toml    how another library's files map onto femkit's (materials.md § 7)
├── states/<machine>.toml      each state machine declared as data (core.md § 7)
├── project/layout.toml        a project's parts, folders and object types (projects.md § 4)
├── web/page.toml              the web page's own structure (web.md § 8.1)
├── web/theme.toml             every design value of the page, both themes (web.md § 10.1)
└── templates/                 the settings file's template, and the project templates (projects.md § 7)
```

`step_kinds.toml` holds `stationary` alone; its `frequency` kind joins with
Maxwell (plan § 4, M9). Not built yet, decided by the person: couplings
(after M9; ADRs [0011](../decisions/0011-project-structure.md)–[0014](../decisions/0014-materials.md)),
and output translators (M6; [ADR 0025](../decisions/0025-one-engine-per-study-observables-after.md)):

```text
femkit/data/
├── couplings/<coupling>.toml  a coupling joining formulation families (models.md § 4.5)
└── translators/<name>         a standard output translator: its declaration and its script (workflow.md § 2.4)
```

A definition changes only when femkit changes: it is reviewed, versioned
with the code, and covered by the same tests. A person tunes their own machine
through configuration, never by editing these files.

Generic code — planner, builder, check runner, doctor, job preparation, CLI —
acts on declared fields and on IDs registered by engine adapters. Adding an
engine adds one environment file and one engine package; it changes no framework
module.

Engine code lives in `femkit/engines/<engine>/` and provides only:

- **readers** — turn the engine's own output (a solver log, a result file) into
  named quantities, each registered under an ID;
- **a version reader**, `read_version` — only for an engine whose version
  command prints its version too irregularly for its last line to be it,
  Elmer's; the command itself is data (§ 4);
- **check programs** — small numerical problems that run inside the engine's
  environment and write the common summary (§ 5.3);
- **a hand-over** — turns the mesh stage's mesh into the engine's own, run
  inside its environment ([`geometry.md`](geometry.md) § 8);
- **input writers, a solve's log reader and finalizers** — not built yet
  (plan § 4, M6): per formulation the engine declares, turn a case into its
  solver's input files, say from a solve's log and status whether it
  finished and whether it converged — never reading a field's values — and
  apply each kind of customization ([`models.md`](models.md) § 9.1). An environment definition also declares
  its abilities, extension points and engine-only options —
  not built yet (plan § 4, M5) ([`models.md`](models.md) § 6.1).

## 2. Schemas

### 2.1 One definition per field, one list of types

The catalogue's record (`definitions/catalogue.py`) holds one field per type of
shipped definition, each declaring where its files are, its model and its
loader: the catalogue, `schema check`, `schema docs` and the reference all read
that list, and no other keeps one.

Each definition type has one schema model. The model owns every field's type,
default, allowed values and description; no other module, document or command
keeps a list of those fields. A model lives in `femkit/definitions/` beside the
catalogue — the place kinds' (`places.py`) and the property list's
(`properties.py`) among them, though `geometry` and `materials` own their
rules — since the catalogue sits below those packages ([`framework.md`](framework.md)
§ 1); a state table's is the core's (`StateTable`). A template has no model of
its own: it is a project, read through the part schemas
([`projects.md`](projects.md) § 7). The layout's model, the page's, the theme's
and the jobs catalogue's live in the packages that read them (`projects`,
`page.py`, `jobs/layout.py`), so `schema check` loads those four files beside
the table rather than from it; each loads once per invocation (`ctx.cached`). A definition's identity is its file stem —
`environments/ngsolve.toml` defines the environment `ngsolve` — and the stem is
not repeated inside the file.

### 2.2 Loading

One loader reads every definition type. A definition loads completely or fails, naming the
file, the key path and the reason. It fails when:

- a key is unknown, a value has the wrong type, or a required key is missing;
- a reference names nothing: a build's source, a check's build or source, a
  reader or engine ID no adapter registered, a hand-over's program its
  engine's package does not hold, a stage or mesher program femkit's stage
  programs do not hold, a stage kind's `environment` that is neither an
  environment's name nor `engine`, an artifact type `artifacts.toml` does not
  declare, a place no `kinds.toml` declares, an agreement group with one
  member;
- an ID repeats within its file, or a placeholder is not one its field
  accepts (§ 4.3);
- two hand-overs give one engine the same mesh type at the same geometry
  order, so the order a case asks for would not choose one
  ([`geometry.md`](geometry.md) § 8);
- two engine environments' definitions declare one engine, so the engine
  `study prep --engine` names would not name one environment — the catalogue resolves an engine
  to its definition's environment alone ([`framework.md`](framework.md) § 5);
- two tool environments' definitions both take the packages projects
  declare (`projects`), since a project's scripts run in one environment
  (§ 4.7);
- the clean start removes a variable no pattern of its own pass list takes —
  such an entry removes nothing (`process.toml`, [`envs.md`](envs.md) § 4.4).

Loading reads only definition files, and the science documents a formulation
names (`models.md` § 4.3). It probes nothing, starts no process and
writes nothing; importing a schema module loads nothing.

### 2.3 Generated reference

`femkit schema docs` (in `femkit/reference.py`, beside the registry, because it
reads every domain's models) renders `docs/reference/` from the schema models
(the state tables are not rendered yet, [`core.md`](core.md) § 7). The
committed pages are that output; a test renders them again and fails on any difference. Contracts,
guides and help text link to the reference instead of restating fields.
`femkit schema check` loads every shipped definition; a test runs it.
Beside the table, it checks what only the registry can: each state table's
operations, by their names and their requests' fields; the layout by its own
rules ([`projects.md`](projects.md) § 4); each stage kind against the layout,
as its one reader reads it — the part kind it `brings` one the layout
declares, the file its program runs a stage program of femkit's or one every
such part holds — since the layout's model and reader are the projects
domain's, above the catalogue; each template a project named by one
step of the name rule; the page's declaration ([`web.md`](web.md) § 8.1).

## 3. `channels.txt` and `control.txt`

The control environment holds Python and the libraries the femkit command
itself needs. It is declared in two plain lists, because the install script
creates it before any Python exists (the files themselves are the authority for
what they list):

```text
channels.txt          control.txt
conda-forge           # comments and blank lines allowed
                      python=3.12
                      pydantic>=2,<3
                      ...
```

- **`channels.txt`** is the one home of the **channel order** every environment
  is solved with: one bare channel name a line, nothing else, because the
  install script passes each line to the manager as a channel exactly as it
  stands; loading refuses a blank line, a comment or a space.
- **`control.txt`** is the control environment's packages, one constraint a
  line, the format every conda, mamba and micromamba version reads with
  `create --file`; it is the one home of the **Python minor** (its `python=`
  line), which every engine environment shares.

The control environment is made by the manager kind's `create` like any engine
environment, by its name, `femkit` ([`envs.md`](envs.md) § 1) — the declared
channels named on its command line, each by its full address as the kind's
`channel` writes one, none of the person's own ([`envs.md`](envs.md) § 4.4) —
with `--file control.txt` for its packages.

## 4. Engine environment

```toml
engine = "ngsolve"                     # registered engine adapter ID
version = "6.2.2606"                   # what its version command must state
version_command = ["python", "-c", "import ngsolve; print(ngsolve.__version__)"]
description = "Netgen/NGSolve with MPI and threads"
default = true                         # part of `env install --all`
thread_variables = ["NGS_NUM_THREADS"]   # set to a run's threads per rank
fixed_variables = { OMP_NUM_THREADS = "1" }   # set to these values in every check and run

[packages]                             # besides its toolchain's
conda = ["openmpi", "mumps-mpi", "hypre", "..."]
forbid = ["elmer", "amgx", "rocm"]     # families that must be absent from the solved lock

[toolchain]                            # its own compilers and build tools (§ 4.6)
packages = ["gcc_linux-64=14", "gxx_linux-64=14", "gfortran_linux-64=14", "sysroot_linux-64=2.28", "cmake=4.5", "..."]
tools = ["cmake", "make", "..."]
compilers = { c = "CC", cxx = "CXX", fortran = "FC" }
mpi = { c = "mpicc", cxx = "mpicxx", fortran = "mpifort" }

[provides]                             # what the audit finds inside the prefix, beyond the toolchain's tools
executables = ["python", "mpirun"]
modules = ["ngsolve", "netgen"]

[cuda]                                 # the CUDA environment, ngsolve-cuda (§ 4.5)
description = "CUDA: device matrices and preconditioners for iterative solves"
packages = ["cuda-version=12.9", "cuda-compiler=12.9.1", "..."]
executables = ["nvcc"]

[[sources]]
id = "netgen"
archive = "https://codeload.github.com/NGSolve/netgen/tar.gz/<commit>"
sha256 = "<archive hash>"
commit = "<40-hex commit>"
release = "v6.2.2606"
into = "netgen"                        # path under the prefix's source tree
version_text = "v6.2.2606-0-a3e08f0"   # written as version.txt: stands in for `git describe` in an archive

[[builds]]
id = "ngsolve"
source = "ngsolve"
after = ["netgen"]
cuda_architectures = true              # in the CUDA environment, compiled for build.cuda_architectures (§ 4.5)
rpath = ["lib"]

[builds.options]                       # CMake cache entries, TOML-typed
USE_MPI = true
NETGEN_DIR = "{prefix}/lib/cmake/netgen"

[builds.cuda_options]                  # set only in the CUDA environment (§ 4.5)
USE_CUDA = true
```

Every environment, an engine's or a tool's (§ 4.7), states its
`version_command`: the command, run in its prefix, that states its version.
The install's `manifest` step runs it and requires `version`
([`envs.md`](envs.md) § 4.1): what it states is the last non-empty line it
prints — unless its engine registers a version reader for output too irregular
for that, Elmer's `ElmerSolver -v`, whose `Version: 26.2-…` line is no last
line. `provides` lists what the audit finds beyond the toolchain's tools,
which the `toolchain` step proves (§ 4.6).

### 4.1 Where each part comes from

An environment holds what its file lists, and nothing from the host. Each part
has one source:

| what | listed in | installed by | from |
|---|---|---|---|
| compilers, the sysroot and every tool a build calls | `[toolchain] packages` (§ 4.6) | the package manager, conda or mamba | conda-forge |
| libraries, MPI, Python and its packages | `[packages] conda` | the package manager, in the same solve | conda-forge |
| the GPU compilers and libraries of the CUDA environment | `[cuda] packages` (§ 4.5) | the package manager, in the same solve | conda-forge |
| each engine, and anything femkit needs at a version, option or patch conda-forge does not offer | `[[sources]]`, `[[builds]]` (§ 4.2) | femkit's build steps, inside the prefix, with its toolchain | an archive pinned by its commit and SHA-256 |
| a package a project's observables scripts need, in `postprocess` (§ 4.7) | the project file's `[postprocess] packages` ([`models.md`](models.md) § 2) | the package manager, on each machine: in the create's solve, or into the prefix as it stands when a project adds it ([`envs.md`](envs.md) § 4.1) | conda-forge |
| a Python package conda-forge does not have | `[packages] pip` | nothing: an environment that lists one is refused. What a geometry script imports is what the `gmsh` environment's definition lists ([`geometry.md`](geometry.md) § 2) | — |

The rule: everything comes from conda-forge, solved once and together, unless
femkit must build it. pip itself is in every environment with Python, but
femkit installs nothing with it, because a package pip installs sits outside the
solve: the manager cannot pin it with the rest, rebuild it exactly, or keep it
from replacing a library the solve chose. The first install records the exact
solution (the lock, [`envs.md`](envs.md) § 4); `forbid` names what must be
absent from it, and is checked against that lock, never against the host.

### 4.2 Builds

- Compilers come from the environment's toolchain (§ 4.6): entering the prefix
  sets each variable its `compilers` names. The `toolchain` step refuses, before
  any source is fetched, a compiler that resolves outside the prefix.
- **Option types come from TOML**: a boolean becomes `BOOL`, anything else
  `STRING`. After configuring, every declared option must be one the project
  read — absent from CMake's own list of variables it was given and never read —
  and present in the build's `CMakeCache.txt`. A misspelt option, or one dead
  where it is declared (inside a switch that is off), fails the build instead of
  being ignored.
- **Framework-owned options** — install prefix, generator, build type, RPATH
  policy, test enablement, package-registry refusal, CUDA architectures — are
  not declarable. The generator is left to CMake's own default (make, on
  Linux): every pinned project builds and tests itself that way, and femkit
  builds each as its authors do ([ADR 0007](../decisions/0007-cmake-default-generator.md)).
- `cuda_architectures = true` marks a build compiled for CUDA architectures in
  the CUDA environment (§ 4.5); they come from the user's configuration
  ([`config.md`](config.md) § 3), never from a device query.

### 4.3 Placeholders

The core's one grammar ([`core.md`](core.md) § 2.1). Each templated field
declares the names it accepts on its schema model
(`placeholders`), and `docs/reference/` lists them per field — build options
take `{prefix}`, `{source:<id>}` and `{build:<id>}`, for example. Any other
name fails at load, and an `<id>` must name a declared source or build. A
manager command must also pass each name it is rendered with — `{name}` on
an environment, `{file}` for a create from a lock — or it fails at load.

### 4.4 Threads

`thread_variables` are set to the run's threads per rank; `fixed_variables`
are set to their declared values. Together they keep a library from starting
threads nobody asked for — NGSolve's task manager uses `NGS_NUM_THREADS`, and
its BLAS would otherwise take every core through `OMP_NUM_THREADS`. A variable
may appear in only one of the two.

### 4.5 CUDA: a second environment

GPU acceleration helps a narrow class of finite-element work, and a CUDA build
costs a toolkit, extra sources and architecture pins
([ADR 0005](../decisions/0005-cuda-environments.md)). So a definition with a
`[cuda]` part is two environments, both made by the catalogue from the one file:

| environment | holds | default |
|---|---|---|
| `<name>` | the definition without its `[cuda]` part: CPU solvers, MPI, threads | as the file says |
| `<name>-cuda` | the definition with it | never: installed on request |

What the CUDA environment adds, all of it declared:

- `[cuda]`: `description`, appended to the environment's in `env list`;
  `packages`, conda constraints solved only for `<name>-cuda`; `executables`
  the audit finds only there; `[[cuda.sources]]` and `[[cuda.builds]]`, the
  sources and builds only it has — Elmer's AmgX. A build of the definition may
  name one of these in `after`; in `<name>` that entry is dropped.
- On a build of the definition: `cuda_architectures = true`, compiled for
  `build.cuda_architectures` in `<name>-cuda`; `[builds.cuda_options]`, cache
  entries added there — in `<name>` each boolean among them is set false and
  the rest are left out.
- A check with `device = true` exists only in `<name>-cuda`. An agreement
  group left with one check in `<name>` is dropped there.

What loading refuses:

- a build with `cuda_architectures` or `cuda_options`, or a device check, in a
  definition without the `[cuda]` part;
- a `[cuda]` part that adds nothing — no package, executable, source or build,
  and nothing marked for CUDA: its environment would be `<name>` under another
  name;
- `cuda_options` on a `[cuda]` build: it exists only in `<name>-cuda`, so all
  its cache entries go in `options`;
- one cache entry in both a build's `options` and its `cuda_options`: which
  value `<name>-cuda` gets would be a guess;
- in what `<name>` runs, anything only `[cuda]` declares: a check without
  `device` may not name a `[cuda]` build or source, and a build's plain
  `options` may not name one (its `cuda_options` may);
- a definition named `control`, the control environment's name
  ([`envs.md`](envs.md) § 1), or `engine`, the word a stage kind's
  `environment` takes for the engine chosen to solve's ([`workflow.md`](workflow.md)
  § 2.1), or ending in `-cuda`.

The two are separate prefixes with their own fingerprints and states;
`build.cuda_architectures` enters only the CUDA one's. A job that asks for a GPU
runs in the CUDA environment ([`jobs.md`](jobs.md) § 3).

### 4.6 Toolchain

An environment with builds declares its own toolchain in `[toolchain]`:
environments may need different compilers, versions or patches, so none shares
another's ([ADR 0006](../decisions/0006-toolchain-first.md)):

| key | holds |
|---|---|
| `packages` | the compilers, the sysroot (the C library the builds link against, so the oldest glibc their binaries run on), and every tool a build calls — CMake, make, pkg-config, git, the shell utilities — solved into the environment |
| `tools` | the executables a build calls; the toolchain check requires each to resolve inside the prefix |
| `compilers` | language (`c`, `cxx`, `fortran`) → the variable the activation sets to its compiler; at least one |
| `mpi` | language → the MPI compiler wrapper the environment provides, for a language `compilers` names (a wrapper drives that compiler); declared, the toolchain check builds with them and runs two ranks |

Its packages are solved with the environment's, so they enter its lock and its
install fingerprint. The `toolchain` install step proves it on the machine
before any source is fetched ([`envs.md`](envs.md) § 4.1, § 4.5). Both shipped
engines pin gcc 14 (ADRs 0003, 0004), `sysroot_linux-64=2.28` — unpinned, the
compilers take the newest sysroot, whose startup objects need an x86-64-v3
processor — and CMake to its 4.5 series (ADR 0006).

### 4.7 A tool environment

An environment that runs no engine — what femkit's own surfaces need, such as
the web server and the tool its page is built with ([`web.md`](web.md)), or
Gmsh, for the geometry stage and Gmsh's meshing ([`workflow.md`](workflow.md) § 2) — states no `engine`;
its `version_command`, as every environment's (§ 4), states its version, read
by its last line:

```toml
description = "the web surface: femkit's server, and Node.js to build its page"
version = "v22.23.5"                   # the last line `version_command` prints
version_command = ["node", "--version"]
control_packages = true                # femkit's own libraries, as control.txt lists them

[packages]
conda = ["flask>=3,<4", "nodejs=22.23.5"]

[provides]
executables = ["python", "node", "npm"]
modules = ["flask"]
```

- A check program of its own states its version under the environment's own
  name — `gmsh`'s, `{"gmsh": …}` — since there is no engine to name it by (§ 5.3).
- `control_packages = true` takes the control environment's packages
  (`control.txt`), solved with its own: a tool environment that runs femkit's
  own code — `web` runs femkit's server — needs femkit's own libraries, and
  taking them by reference keeps the two lists one. A change of `control.txt`
  changes its install fingerprint.
- A femkit program that runs in a tool environment — the definitions' in
  `model_prep`, the observe stage's in `postprocess` (with M6), the page's build in
  `web` — is declared in `programs.toml`, with its time limit there, never
  in the environment's file ([`envs.md`](envs.md) § 4.4); a stage's program
  — the observe stage's — takes its environment from its stage kind alone
  ([`workflow.md`](workflow.md) § 2.1).
- A tool environment whose definition states `projects = true` —
  `postprocess` — takes, beside its own, every package the projects under
  the projects root declare for their scripts, in their project files'
  `[postprocess] packages` ([`models.md`](models.md) § 2): each a conda
  constraint as the project writes it, every one once, from the declared
  channels on each machine — solved with its own when it is built, and a
  package a project adds later delivered into it as it stands by `env
  install` ([`envs.md`](envs.md) § 4.1) — so they enter its lock and its
  manifest records them, but never its install fingerprint, which is
  femkit's own set ([`envs.md`](envs.md) §§ 2, 4.3): a project's package
  never makes it `outdated`. Only new packages are taken: what goes into it
  is femkit's recipe alone ([`envs.md`](envs.md) § 4.4), so an entry naming a
  package its recipe declares or pins — its own constraints, the control
  environment's where it takes them, and Python (`EnvironmentDefinition.held`)
  — is never delivered, and the project file's check says so at that entry,
  `package-held`: a warning for the name alone, which the environment holds
  already; an error for a version it is held to, which the recipe decides. Each project file's `[postprocess]` is read
  alone, through the project file's schema, never by opening the project,
  by the models domain's one function (`models/project.py`, `declared`): a
  project whose other parts or keys do not load still declares its packages,
  and a project file whose table does not read adds none, noted in the
  install's report. With none declared, it is its definition alone. A project names, beside a package its scripts import by another
  name, that name (`{ conda = "scikit-image", module = "skimage" }`): what
  `observe.py` may import is the modules `postprocess` provides and those its
  own project's packages name — never another project's. The projects lie
  above the envs domain, so femkit's start hands it what reads them
  ([`api.md`](api.md) § 6). No other environment takes any — an engine's
  definition that states `projects` is refused, and a solver's, a geometry
  script's and `definitions.py`'s stay as femkit ships them.
- A tool environment has no `toolchain`, `sources`, `builds`, `agreements`,
  `cuda`, thread or fixed variables. It is `default` when every project needs
  it — `gmsh`, which every geometry and every Gmsh mesh runs in, and
  `model_prep` and `postprocess`, where the person's Python runs — and
  otherwise installed when a person asks (`env install web`).
- It installs as any environment does — the declared channels, the Python
  minor `control.txt` names (§ 3) when it provides `python`, a solved and saved lock, the audit of
  `provides`, its version command — by the manager, as every environment is
  ([`envs.md`](envs.md) § 4.4): femkit's own programs run in it as in an
  engine's — Gmsh's meshing in `gmsh` — so it shares their Python. Measured
  2026-11-25: `gmsh` declared with Python unpinned was solved to Python 3.15.2,
  beside 3.12.16 everywhere else. With no checks it is `ready` once
  its manifest is written; its checks, when it declares them, are `command`
  checks read by the generic readers (§ 5), since there is no engine adapter to
  read them: `gmsh`'s builds the Laplace square from its template's script,
  meshes it with Gmsh's meshing program, and compares each region's area with the
  geometry's.

## 5. Checks

A check runs one bounded calculation inside the environment and states the
numbers it must produce. The runner is generic; only readers know an engine.

```toml
[[checks]]
id = "hcurl-mpi"
kind = "command"
run = ["python", "-m", "femkit.engines.ngsolve.checks.hcurl", "{work}", "{threads}"]   # distributes when ranks > 1
ranks = 2
threads = 1
read = "summary"                       # reader ID
expect = { relative_residual = { max = 1e-9 } }   # the ranks and threads reported: the runner's to compare
agree = "hcurl-field"                  # agreement group, § 5.2
timeout = 300

[[checks]]
id = "amgx-gpu"
kind = "ctest"
build = "elmer"
test = "WinkelBmPoissonAMGX"
read = "elmer-solver-log"
expect = { reference_error = { max = 1e-5 }, amgx_solves = { min = 1 } }   # the device did the solves
agree = "winkel-poisson"
device = true

[agreements.hcurl-field]
quantity = "field_l2_norm"
rtol = 1e-9
```

### 5.1 Check kinds

| kind | runs |
|---|---|
| `command` | `run`, through `launch.mpi` ([`config.md`](config.md) § 3.1) when `ranks > 1` |
| `ctest` | one named test from a build's test tree, located through CTest's own JSON listing; its working directory must lie inside the build tree. The test launches its own ranks; `ranks` states what its log must report (§ 5.2). With `upstream_verdict = false` the test's own pass or fail is set aside and only `expect` and its agreement judge it — for a test whose stored reference does not hold for the pinned libraries, which the definition says |
| `pytest` | named upstream test nodes, given relative to the source tree, from the deepest folder holding them all, with plugin autoloading and the invocation's pytest options off and the declared `plugins` loaded first (`-p`; e.g. `mpi4py.MPI`, so MPI starts before the tests import an MPI build); judged from their JUnit report |

Every check runs inside its environment through the manager, in a fresh
`{work}` folder of its own under the validate's operation directory, with the
environment's `thread_variables` set to `threads`, its `fixed_variables` set,
the femkit checkout as `PYTHONPATH` (nothing inherited), and the user's own
site-packages off (`PYTHONNOUSERSITE=1`), so nothing outside the prefix can
stand in for what it built. That is how a check program in
`femkit/engines/<engine>/checks/` runs there, under the import rule for
`engines` ([`framework.md`](framework.md) § 1). `run` may use
`{prefix}`, `{work}`, `{ranks}` and `{threads}`.

A check fails when it exits non-zero (except a `ctest` that sets its upstream
verdict aside), outlives its `timeout`, or its reader refuses the output;
otherwise its quantities are judged (§ 5.2).

### 5.2 What a check proves

- The run is the one asked for: the runner compares the `ranks` and `threads`
  the reader reports with the check's own. A check on more than one rank or
  thread fails unless they are reported, and any reported must equal the
  check's — so its outcome proves what was asked ran
  ([`framework.md`](framework.md) § 4). `expect` never names them; loading
  refuses it.
- Every `expect` entry is compared with the reader's quantities; a quantity the
  reader did not produce fails the check.
- Checks sharing an `agree` group must give the declared quantity within `rtol`
  of one another, every pair of members (element-wise for a list; the
  difference is relative to the larger of the two values). A group is judged
  when every member passed.
- A disagreement fails the group's `device = true` members when it has any —
  the CPU path is the reference — and every member otherwise. When a member
  without `device = true` did not pass, the device members fail too: their
  reference is gone.
- `device = true` marks a check that uses a GPU: it runs only when the person
  asks for the GPU (`validate --gpu`). Its expectations must prove the device
  did the work — data in device memory, solves the GPU library counted — so a
  silent fallback to the CPU fails it, with the reason
  ([`framework.md`](framework.md) § 4). How device and non-device outcomes decide an environment's state is
  [`envs.md`](envs.md) § 5.

### 5.3 Readers

A reader turns one finished check's output into quantities, or refuses it
with the reason. It opens no file: the runner reads for it, through the core
([`framework.md`](framework.md) § 1 rule 1), the files the check wrote in this
run that it asks for by name or pattern — in the folder the check writes into,
its `{work}` folder or a `ctest`'s working directory — and gives it the check's
ranks, threads and named tests, and the pinned `version` with what it is a
version of: the engine, or a tool environment's own name. Output older than
the start is not this run's: the start is the time of a marker the runner
writes into that folder, so both times come from the file system holding the
outputs. A reader refuses output that reports another version than the pinned
one.

| reader | owned by | reads |
|---|---|---|
| `summary` | the runner | `{work}/summary.json`, written by a check program for femkit: `quantities` as finite numbers or lists of them, plus the runtime `versions` it observed, whose entry for the engine — for a tool environment, its own name — must be there and be the pinned version (`femkit/engines/summary.py`) |
| `junit` | the runner | the `pytest` kind's JUnit report: exactly the named tests, once each, none failed, errored or skipped |
| an engine's | its package, as `READERS` | output femkit does not write, such as a solver's own test log; an environment may name only its engine's readers and the runner's |

## 6. Manager and scheduler kinds — how femkit talks to outside tools

A **kind** file declares everything femkit says to one family of external
tool: its command lines as argument templates, and how to read its answers.
Code keeps only the readers of answers too irregular for a pattern, registered
by ID and named in the kind.

| directory | one file per | declares |
|---|---|---|
| `managers/` | conda; mamba, 1.x and 2.x (every form measured on 1.5.9 and 2.9.0 by prefix; by name, the `environments` and `envs_dirs` queries, its shell hook and channels by their full addresses, not measured yet, plan § 4, X); micromamba once measured (plan § 4, M1) | each command on one environment by its name, `{name}` — the manager decides where it lies ([`envs.md`](envs.md) § 1): create from constraints (the control environment's: `--file control.txt`) / from a lock; run in an environment (and, not built yet, the text its `run` prints when it cannot start a command, [`envs.md`](envs.md) § 4.4); export the lock; create from a lock and remove, each naming the declared channels as a create does where the kind needs them (`channels_named`: conda does, mamba refuses them on a removal) ([`envs.md`](envs.md) § 4.4); `channel`, how one declared channel is named — by its full address, `https://conda.anaconda.org/{channel}`, which no channel alias or custom channel of the person's re-routes; report version, root and platform; `environments`: every environment the manager lists, by prefix, as JSON; `names`, where the manager says its own name for each (conda's `envs_details`), and `envs_dirs`, the folders where it keeps environments by their names — together where femkit takes an environment's prefix, the one the manager names so, and where it finds a folder in the way it does not list ([`envs.md`](envs.md) §§ 1, 3); `install`: the constraints that follow installed into an environment as it stands, naming the declared channels — what delivers a package a project adds into `postprocess` ([`envs.md`](envs.md) § 4.1; not measured yet on either kind); `settings`: the manager's own answer of which of the person's settings it read where (conda's `config --show-sources --json`), each of those that would change what goes into an environment set aside by the flags its solving commands carry (`neutralised`, saying how) or refused before any create (`refused`, with the value refused and what to change) ([`envs.md`](envs.md) § 4.4; none declared for mamba, not measured); `activate`: the kind's two ways a shell enters an environment by its name, between which this machine's `activation.command` chooses ([`config.md`](config.md) § 3.1) — the shell function, with the manager's own command that prints its hook for bash (`{exe} shell.bash hook` for conda), evaluated first, never a file derived from the binary's path, which on a cluster may be a module's wrapper; and the activate script (`source activate {name}`) and the `script` it finds on `PATH` ([`envs.md`](envs.md) § 6.2); and `active`, the variable either form sets to the prefix it entered, which a run script reads to verify it entered the environment it was prepared for ([`jobs.md`](jobs.md) § 4) — `CONDA_PREFIX` for both kinds, the variable conda's activation sets; that mamba's forms set it is not measured. A kind sets none of the manager's own variables: the manager runs as the person set it up ([`envs.md`](envs.md) § 4.4) |
| `schedulers/` | local, slurm | the parts of the `SchedulerKind` model (`docs/reference/`) — its `passes` among them, the variables a job of the kind sees that a clean start passes, and its `functions`, the shell functions it needs passed ([`envs.md`](envs.md) § 4.4); [`jobs.md`](jobs.md) § 7 says what each is for |

The manager in use and the scheduler a machine has are facts of that machine
([`jobs.md`](jobs.md) § 9); the language each one speaks is
here, once, for every machine of that kind. A manager kind assumes the conda
family's shape — an environment named by `-n`, constraints on one command line,
a lock printed to standard output; a manager of another shape (pixi, say, which
the plan excludes) would change this model, not just add a file.
