# Configuration — what is set, what is measured, and where each lives

**Role:** contract
**Status:** current; what is not built yet is marked so
**Authority:** the homes of every non-source file femkit reads or writes,
who writes each, how each is found, and the user configuration

## The short version

| rule | § |
|---|---|
| Information has **five homes**: shipped definitions, user configuration, machine records, install records, run files. Each has one kind of writer | 1 |
| Nothing a person sets and nothing a machine reports is in the repository; it lives in the user's own directories | 1, 2 |
| Each directory is chosen by **the first rule that is set** — its own variable, the XDG variable, the default — and a file is read from that directory only, never from another; files are never merged; `config path` says which rule chose each | 2 |
| `config.toml` holds **choices**: where environments go, CUDA targets, the MPI launcher, the activation preamble and command | 3 |
| How a job's shell gets ready on a machine and enters an environment (`activation.preamble`, `activation.command`) has **no default**: `config init` asks for both on a terminal and proposes nothing; no record is written and no job prepared until both are stated | 3.1, 3.2 |
| A **default is never written**: `paths.environments` unset means the default, which `config init` shows and asks to change | 3.2 |
| A **machine record** holds **facts**, written only by `job probe` on that machine; a choice is never measured into it, only copied. Its contents are [`jobs.md`](jobs.md) § 9 | 1 |
| The repository ships **templates**; `config init` turns them into the person's files and never overwrites what a person set | 3.2 |

## 1. The five homes

| home | holds | lives in | written by |
|---|---|---|---|
| shipped definitions | `channels.txt`, `control.txt`, `units.toml`, environments, manager and scheduler kinds, templates | the repository, `femkit/data/` | a femkit change, reviewed ([`definitions.md`](definitions.md)) |
| user configuration | choices for this machine | `<config>/config.toml` | the person, through `config init` / `config set` |
| machine records | measured facts of a machine | `<config>/machines/<name>.toml` | `job probe`, run on that machine ([`jobs.md`](jobs.md) § 9) |
| install records | what was installed and what its checks showed | inside each prefix, plus package locks under `<data>` | the installer and validator ([`envs.md`](envs.md) § 4) |
| run files | a calculation's request, scripts and runs | the calculation folder | `job prepare`, the run script ([`jobs.md`](jobs.md)); `case prepare` for a prepared case ([`models.md`](models.md) § 2; not built yet, plan § 3, M6) |

A writer never writes another's home: a probe never writes a choice, `config
set` never writes a fact, and preparing a job never edits configuration.

The repository holds none of the last four: no home path, host name, user name,
device model, site name or credential appears in a committed file.

## 2. Directories and lookup

| directory | holds | default | override |
|---|---|---|---|
| `<config>` | what a person set and what a probe measured: `config.toml`, `machines/`; the web server's secrets, `secrets/` ([`web.md`](web.md) § 5; not built yet, plan § 3, M7) | `$XDG_CONFIG_HOME/femkit`, else `~/.config/femkit` | `FEMKIT_CONFIG_DIR` |
| `<data>` | environments, package locks, subject locks; benchmark projects, `<data>/benchmarks/` ([`models.md`](models.md) § 6.3; not built yet, plan § 3, M6) | `$XDG_DATA_HOME/femkit`, else `~/.local/share/femkit` | `FEMKIT_DATA_DIR` |
| `<cache>` | downloads femkit can fetch again; may be emptied at any time | `$XDG_CACHE_HOME/femkit`, else `~/.cache/femkit` | `FEMKIT_CACHE_DIR` |
| `<state>` | operation logs ([`core.md`](core.md) § 6): what each install, check and probe did; kept until the person deletes them; the web server's logs, `<state>/logs/` ([`web.md`](web.md) § 4) | `$XDG_STATE_HOME/femkit`, else `~/.local/state/femkit` | `FEMKIT_STATE_DIR` |
| `<runtime>` | a running web server's pidfile, token and socket ([`web.md`](web.md) § 4); its sign-in session records, not built yet (plan § 3, M7) | `<state>/run/<host>/` | `FEMKIT_RUNTIME_DIR` |

A log is not a cache: emptying a cache must lose nothing but downloads, so the
logs live apart from it, under `$XDG_STATE_HOME`.

Each variable chooses a directory; the file is the one in it. `~` is expanded;
a directory that is still relative is refused, so no file is read from the
working directory. No two files of one kind are combined. `scripts/install-env.sh`
resolves the data directory by the same rule, because it must find the control
environment before Python runs.
`python -m femkit config path` prints the five directories, the rule that chose
each, every file under the configuration directory and the top-level entries of
the others, so which file is in effect is never a guess. `core/dirs.py` holds
the list of the five and their variables ([`core.md`](core.md) § 3).

`FEMKIT_ENV_MANAGER` is set by the install script to the manager it found; it
is not a setting. How Python learns the manager without it is
[`envs.md`](envs.md) § 7.1.

## 3. User configuration — `config.toml`

### 3.1 What it holds

| key | meaning | when unset |
|---|---|---|
| `projects.undo` | how many edits of a project `project undo` reaches back through ([`projects.md`](projects.md) § 7); decided by the person, not built yet (plan § 3, R step C) | 100 |
| `paths.projects` | the projects root: the person's material library and their projects ([`projects.md`](projects.md) § 1); replacing `web.projects`; decided by the person (plan § 6), not built yet (plan § 3, R) | the page cannot list or create projects, and `material add --from` and `material import --into library` are refused, naming this key |
| `paths.environments` | where engine environment prefixes are created (the control environment's place is fixed, [`envs.md`](envs.md) § 1) — on a cluster, typically project storage rather than a small home quota | `<data>/environments` |
| `build.cuda_architectures` | GPU architectures the CUDA environments target, e.g. `["80", "90"]` ([`definitions.md`](definitions.md) § 4.5); the default environments never read it | installing an environment with a build compiled for CUDA (both CUDA environments have one) is refused, naming this key |
| `build.jobs` | parallel compile jobs | the CPUs this process may use (its CPU affinity: on a cluster, the allocation's share, never the whole login node) |
| `launch.mpi` | how a multi-rank process starts, e.g. `["mpirun", "-np", "{ranks}"]` — the environment's own `mpirun` ([`jobs.md`](jobs.md) § 7). It must pass `{ranks}` and may not be empty: a launcher without it would run every job on the wrong number of processes. The same rule holds for a scheduler kind's `mpi_launch` | a multi-rank check or job, and installing an environment with MPI (its toolchain check runs two ranks, [`envs.md`](envs.md) § 4.1), are refused, naming this key |
| `activation.preamble` | the shell lines a run script runs on this machine before it enters an environment — `module load` lines that put the manager on `PATH`, for instance; `[]` states that none are needed | `job probe --write` and `job prepare` are refused, naming this key |
| `activation.command` | how a shell on this machine then enters an environment: `source activate`, the activate script on `PATH` (a cluster's `module load mamba` puts it there); or `conda activate` / `mamba activate`, the manager's shell function, which exists only once the manager's hook file is sourced — femkit sources it first, from the kind's `activate.hook` under the manager's root ([`definitions.md`](definitions.md) § 6) | `job probe --write` and `job prepare` are refused, naming this key |

The web server's keys — `[web.auth]`, `web.tls`, `web.trust_proxy`,
`web.public_name`, `web.projects`, `web.upload_max_mb` — are
[`web.md`](web.md) § 5's and § 8.6's; `web.projects` is built, and becomes
`paths.projects`, decided, once plan § 3, R lands; the others are not built yet
(plan § 3, M7).

Every key is optional in the file, and its absence has the one consequence the
table states. Unknown keys are refused at load. The schema model is the
authority for types and allowed values (`docs/reference/`).

`activation.preamble` and `activation.command` have no default because nothing
on the machine can reveal them: a login shell may have the manager on `PATH`
through a module that a batch job does not load, and a hook file on disk does
not say that a batch job's shell can use it — on a cluster whose module puts
`activate` on `PATH`, `source activate` is the form that works. Unset and `[]`
are different answers for the preamble — unset means nobody has said, `[]` means
someone said nothing is needed.

### 3.2 How it is made

- `config init` writes the file from `femkit/data/templates/config.toml`,
  a commented template. Like every changing command it first shows its plan
  ([`api.md`](api.md) § 3): each key it will add and where the value came
  from — given as an option (`--environments`, `--cuda-architectures`,
  `--jobs`, `--mpi`, `--preamble`, `--no-preamble`, `--activation`) or measured here (the GPU
  architectures the driver reports, the scheduler kind's launcher). The person
  consents to the plan, or runs it again with an option to change a value.
- **A default is never written.** It applies while its key is unset, so an
  unattended run never fixes multi-gigabyte builds in a home directory for
  good. While `paths.environments` is unset the plan shows where environments
  will go — the default, whether it is writable and its filesystem's free
  space (a quota is not measured; on a cluster the home quota is often too
  small) — and on a terminal `config init` asks for another place; an empty
  answer keeps the default, unwritten.
- `activation.preamble` and `activation.command` are never proposed. While
  the preamble is unset, `config init` asks for its lines on a terminal,
  showing beside the question the loaded modules when the shell lists them;
  while the command is unset, it asks which of the three it is, saying what
  each means. An empty answer leaves the key unset. `--preamble LINE`
  (repeatable) or `--no-preamble`, and `--activation COMMAND`, state them
  without the questions. Left unset, the report says what that blocks, naming
  the options.
- Both are asked as [`api.md`](api.md) § 3.1 states: never under `--yes` or
  `--dry-run`, or without a terminal.
- Re-running `config init` adds only keys the file lacks and reports each as
  `added` or `kept`; it never replaces a value.
- `config set KEY VALUE` validates and writes one key, keeping the file's
  comments and layout. `VALUE` is TOML text, as the file writes it —
  `config set web.projects '"/data/projects"'` — and a bare word is refused,
  never guessed to be text ([`web.md`](web.md) § 7.3). `config show` prints every key with its value and where
  it came from: the file, or the "when unset" rule.

## 4. Install records and run files

Their contents are owned by their domain contracts; their homes are:

| file | home |
|---|---|
| manifest and check results of an environment | `<prefix>/.femkit/` — removed with the prefix |
| package lock (the solved package list) | `<data>/locks/<environment>/` — kept, so an environment can be recreated exactly |
| operation event logs and command logs | the operation directory ([`core.md`](core.md) § 6) |
| job request, run script, scheduler header, machine record copy, runs | the calculation folder |
