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
| How to drive a package manager or a scheduler is a **kind** file; adding a scheduler, or a manager of the conda family, is data plus, at most, a reader | 6 |

What is configured per user or per machine is not here: it is
[`config.md`](config.md). What a run writes is
[`jobs.md`](jobs.md).

## 1. What a shipped definition is

femkit ships seven types of definition under `femkit/data/`, beside the
templates for user configuration:

```text
femkit/data/
├── channels.txt               the channel order every environment is solved with
├── control.txt                the control environment's packages, as `conda create --file` reads them
├── environments/<name>.toml   one per engine environment
├── formulations/<id>.toml     a physical problem stated for every engine (models.md § 4)
├── meshers/<id>.toml          a mesher and what it builds (models.md § 6.5)
├── managers/<kind>.toml       how to drive a package manager (conda, mamba)
├── schedulers/<kind>.toml     how to talk to a scheduler (local, slurm)
├── units.toml                 the units a value may be written in, with exact factors (core.md § 11)
└── templates/                 starting text for user configuration files
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
- **version probe** — report the installed solver version;
- **check programs** — small numerical problems that run inside the engine's
  environment and write the common summary (§ 5.3).
- **translators, parsers and finalizers** — not built yet (plan § 3, M6): per formulation
  the engine declares, turn a case into input files, a run's output into
  observations, and apply each kind of customization
  ([`models.md`](models.md) § 9.1). An environment definition also declares
  its abilities, default mesher, extension points and engine-only options —
  not built yet (plan § 3, M5) ([`models.md`](models.md) § 6.1).

## 2. Schemas

### 2.1 One definition per field

Each definition type has one schema model. The model owns every field's type,
default, allowed values and description; no other module, document or command
keeps a list of those fields. A definition's identity is its file stem —
`environments/ngsolve.toml` defines the environment `ngsolve` — and the stem is
not repeated inside the file.

### 2.2 Loading

One loader reads every definition type. A definition loads completely or fails, naming the
file, the key path and the reason. It fails when:

- a key is unknown, a value has the wrong type, or a required key is missing;
- a reference names nothing: a build's source, a check's build or source, a
  reader or engine ID no adapter registered, an agreement group with one member;
- an ID repeats within its file, or a placeholder is not one its field
  accepts (§ 4.3).

Loading reads only definition files. It probes nothing, starts no process and
writes nothing; importing a schema module loads nothing.

### 2.3 Generated reference

`python -m femkit schema docs` (in `femkit/reference.py`, beside the registry, because it
reads every domain's models) renders `docs/reference/` from the schema models
(the state tables are not rendered yet, [`core.md`](core.md) § 7). The
committed pages are that output; a test renders them again and fails on any difference. Contracts,
guides and help text link to the reference instead of restating fields.
`python -m femkit schema check` loads every shipped definition; a test runs it.

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
environment — the declared channels only, none of the person's own conda
settings ([`envs.md`](envs.md) § 4.4) — with `--file control.txt` for its
packages.

## 4. Engine environment

```toml
engine = "ngsolve"                     # registered engine adapter ID
version = "6.2.2606"                   # what the version probe must report
description = "Netgen/NGSolve with MPI and threads"
maturity = "candidate"                 # production | candidate | experimental
default = true                         # part of `env install --all`
thread_variables = ["NGS_NUM_THREADS"]   # set to a run's threads per rank
fixed_variables = { OMP_NUM_THREADS = "1" }   # set to these values in every check and run

[packages]                             # besides its toolchain's
conda = ["openmpi", "mumps-mpi", "hypre", "..."]
pip = []
forbid = ["elmer", "amgx", "rocm"]     # families that must be absent from the solved lock

[toolchain]                            # its own compilers and build tools (§ 4.6)
packages = ["gcc_linux-64=14", "gxx_linux-64=14", "gfortran_linux-64=14", "sysroot_linux-64=2.28", "cmake=4.5", "..."]
tools = ["cmake", "make", "..."]
compilers = { c = "CC", cxx = "CXX", fortran = "FC" }
mpi = { c = "mpicc", cxx = "mpicxx", fortran = "mpifort" }

[provides]                             # what the install's audit step finds inside the prefix
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

### 4.1 Packages

`conda` and `pip` are constraints the manager solves, together with the
toolchain's packages (§ 4.6) in one solve. The first install records
the exact solution (the lock, [`envs.md`](envs.md) § 4); `forbid`
is checked against that lock, never against the host.

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

One grammar everywhere, `{name}` or `{name:argument}` ([`core.md`](core.md)
§ 2.1). Each templated field declares the names it accepts on its schema model
(`placeholders`), and `docs/reference/` lists them per field — build options
take `{prefix}`, `{source:<id>}` and `{build:<id>}`, for example. Any other
name fails at load, and an `<id>` must name a declared source or build.

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
  ([`envs.md`](envs.md) § 1), or ending in `-cuda`.

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
the web server and the tool its page is built with ([`api.md`](api.md) § 5) —
states no `engine`; it states the command that reports its version instead:

```toml
description = "the web surface: femkit's server, and Node.js to build its page"
version = "v22.23.5"                   # the last line `version_command` prints
version_command = ["node", "--version"]
maturity = "production"
control_packages = true                # femkit's own libraries, as control.txt lists them

[packages]
conda = ["flask>=3,<4", "nodejs=22.23.5"]

[provides]
executables = ["python", "node", "npm"]
modules = ["flask"]
```

- Exactly one of `engine` and `version_command` is given.
- `control_packages = true` takes the control environment's packages
  (`control.txt`), solved with its own: a tool environment that runs femkit's
  own code — `web` runs femkit's server — needs femkit's own libraries, and
  taking them by reference keeps the two lists one. A change of `control.txt`
  changes its install fingerprint.
- A tool environment has no `toolchain`, `sources`, `builds`, `checks`,
  `agreements`, `cuda`, thread or fixed variables, and is never `default`: it is
  installed when a person asks (`env install web`).
- It installs as any environment does — the declared channels, a solved and
  saved lock, the audit of `provides`, the version probe — in the manager's
  femkit places ([`envs.md`](envs.md) § 4.4), and is `ready` once its manifest is
  written: it has no checks to run.

## 5. Checks

A check runs one bounded calculation inside the environment and states the
numbers it must produce. The runner is generic; only readers know an engine.

```toml
[[checks]]
id = "hcurl-mpi"
kind = "command"
run = ["python", "-m", "femkit.engines.ngsolve.checks.hcurl", "{work}"]   # distributes when ranks > 1
ranks = 2
threads = 1
read = "summary"                       # reader ID
expect = { relative_residual = { max = 1e-9 }, ranks = { equals = 2 } }
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
| `ctest` | one named test from a build's test tree, located through CTest's own JSON listing; its working directory must lie inside the build tree. The test launches its own ranks; `ranks` states what its log must report. With `upstream_verdict = false` the test's own pass or fail is set aside and only `expect` and its agreement judge it — for a test whose stored reference does not hold for the pinned libraries, which the definition says |
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
with the reason. It is given the check's `{work}` folder and log, the test's
working directory for a `ctest`, the time the check started, and its ranks,
threads and the pinned `version`. Output older than the start is not this
run's; for a `ctest` the start is the time of a marker the runner writes into
the test's working directory, so both times come from the file system holding
the outputs. A reader refuses output that reports another version of the
engine than the pinned one.

| reader | owned by | reads |
|---|---|---|
| `summary` | the runner | `{work}/summary.json`, written by a check program for femkit: `quantities` as finite numbers or lists of them, plus the runtime `versions` it observed, whose entry for the engine must be the pinned version (`femkit/engines/summary.py`) |
| `junit` | the runner | the `pytest` kind's JUnit report: exactly the named tests, once each, none failed, errored or skipped |
| an engine's | its package, as `READERS` | output femkit does not write, such as a solver's own test log; an environment may name only its engine's readers and the runner's |

## 6. Manager and scheduler kinds — how femkit talks to outside tools

A **kind** file declares everything femkit says to one family of external
tool: its command lines as argument templates, and how to read its answers.
Code keeps only the readers of answers too irregular for a pattern, registered
by ID and named in the kind.

| directory | one file per | declares |
|---|---|---|
| `managers/` | conda; mamba, 1.x and 2.x (every form measured on 1.5.9 and 2.9.0); micromamba once measured (plan) | create from constraints (the control environment's: `--file control.txt`), overriding the person's own conda channels and, where the manager can, default packages / from a lock; run in a prefix (and, not built yet, the text its `run` prints when it cannot start a command, [`envs.md`](envs.md) § 4.4); export the lock; remove, naming the declared channels as a create does where the kind needs them (`remove_channels`: conda does, mamba refuses them) ([`envs.md`](envs.md) § 4.4); report version, root and platform; `activate`: the kind's two ways a shell enters a prefix, between which this machine's `activation.command` chooses ([`config.md`](config.md) § 3.1) — the shell function, with the hook file under `{root}` that defines it (for conda `{root}/etc/profile.d/conda.sh`, checked on disk, never derived from the binary's path, which on a cluster may be a module's wrapper), and the activate script (`source activate {prefix}`) ([`envs.md`](envs.md) § 6.2) |
| `schedulers/` | local, slurm | the parts of the `SchedulerKind` model (`docs/reference/`); [`jobs.md`](jobs.md) § 7 says what each is for |

The manager in use and the scheduler a machine has are facts of that machine
([`jobs.md`](jobs.md) § 9); the language each one speaks is
here, once, for every machine of that kind. A manager kind assumes the conda
family's shape — a prefix given by `-p`, constraints on one command line, a lock
printed to standard output; a manager of another shape (pixi, say, which the
plan excludes) would change this model, not just add a file.
