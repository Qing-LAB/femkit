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
| Each of femkit's six directories is chosen by **the first rule that is set** — its own variable, the XDG variable, the default — and a file is read from that directory only, never from another; files are never merged; `config path` says which rule chose each | 2 |
| `config.toml` holds **choices**: the projects root, CUDA targets, build jobs, the MPI launcher, the activation preamble and command — never what a project needs, which travels with the project, and never where an environment lies, which is the package manager's ([`envs.md`](envs.md) § 1) | 3 |
| Each key's **help**, what its **absence** means and the **question** `config init` asks for it are declared once, on its field of `UserConfig`; the template's comments, the questions, `config show` and the reference page read them there | 3.1, 3.2 |
| How a job's shell gets ready on a machine and enters an environment (`activation.preamble`, `activation.command`) has **no default**: `config init` asks for both on a terminal and proposes nothing; no record is written and no job prepared until both are stated | 3.1, 3.2 |
| A **default is never written**: `build.jobs` unset means the CPUs this process may use, never a number fixed into the file | 3.2 |
| A **machine record** holds **facts**, written only by `job probe` on that machine; a choice is never measured into it, only copied. Its contents are [`jobs.md`](jobs.md) § 9 | 1 |
| The repository ships **templates**; `config init` turns them into the person's files and never overwrites what a person set | 3.2 |

## 1. The five homes

| home | holds | lives in | written by |
|---|---|---|---|
| shipped definitions | `channels.txt`, `control.txt`, `units.toml`, environments, manager and scheduler kinds, templates | the repository, `femkit/data/` | a femkit change, reviewed ([`definitions.md`](definitions.md)) |
| user configuration | choices for this machine | `<config>/config.toml` | the person, through `config init` / `config set` |
| machine records | measured facts of a machine | `<config>/machines/<name>.toml` | `job probe`, run on that machine ([`jobs.md`](jobs.md) § 9) |
| install records | what was installed and what its checks showed | inside each prefix, plus package locks under `<data>` | the installer and validator ([`envs.md`](envs.md) § 4) |
| run files | a calculation's request, scripts and runs | the calculation folder | its writers as the jobs domain's catalogue declares them ([`jobs.md`](jobs.md) § 1.1) |

A writer never writes another's home: a probe never writes a choice, `config
set` never writes a fact, and preparing a job never edits configuration.

The repository holds none of the last four: no home path, host name, user name,
device model, site name or credential appears in a committed file.

## 2. Directories and lookup

| directory | holds | default | override |
|---|---|---|---|
| `<config>` | what a person set and what a probe measured: `config.toml`, `machines/`; the web server's secrets, `secrets/` ([`web.md`](web.md) § 5; not built yet, plan § 4, M7's remainder) | `$XDG_CONFIG_HOME/femkit`, else `~/.config/femkit` | `FEMKIT_CONFIG_DIR` |
| `<data>` | package locks, subject locks; benchmark projects, `<data>/benchmarks/<formulation>/` ([`models.md`](models.md) § 6.3; not built yet, plan § 4, M6) | `$XDG_DATA_HOME/femkit`, else `~/.local/share/femkit` | `FEMKIT_DATA_DIR` |
| `<cache>` | what femkit can make or fetch again, and may be emptied at any time: source archives, `sources/`; the page's build folder and npm's cache, `frontend/` ([`web.md`](web.md) § 3); the definitions' computed values, `definitions/` ([`models.md`](models.md) § 3) | `$XDG_CACHE_HOME/femkit`, else `~/.cache/femkit` | `FEMKIT_CACHE_DIR` |
| `<state>` | operation logs ([`core.md`](core.md) § 6): what each install, check and probe did; kept until the person deletes them; the web server's logs, `<state>/logs/` ([`web.md`](web.md) § 4); the address of each job launched from this machine, `<state>/jobs/` ([`jobs.md`](jobs.md) § 5.4) | `$XDG_STATE_HOME/femkit`, else `~/.local/state/femkit` | `FEMKIT_STATE_DIR` |
| `<runtime>` | a running web server's pidfile, token and socket ([`web.md`](web.md) § 4); its sign-in session records, not built yet (plan § 4, M7's remainder) | `<state>/run/<host>/` | `FEMKIT_RUNTIME_DIR` |
| `<bin>` | the link that puts `femkit` on a shell's path, `<bin>/femkit`, written by the install script alone ([`envs.md`](envs.md) § 7) | `~/.local/bin` | `FEMKIT_BIN_DIR` |

A log is not a cache: emptying a cache must lose nothing but downloads, so the
logs live apart from it, under `$XDG_STATE_HOME`.

Each variable chooses a directory; the file is the one in it. `~` is expanded;
a directory that is still relative is refused, so no file is read from the
working directory. No two files of one kind are combined. `scripts/install-env.sh`
resolves the data, cache and bin directories by the same rule, because it acts
before Python runs.
`femkit config path` prints the six directories, the rule that chose
each, every file under the configuration directory and the top-level entries of
the others, so which file is in effect is never a guess. `core/dirs.py` holds
the list of the six and their variables ([`core.md`](core.md) § 3).

`FEMKIT_ENV_MANAGER` is set by the install script to the manager it found; it
is not a setting. How Python learns the manager without it is
[`envs.md`](envs.md) § 7.1.

## 3. User configuration — `config.toml`

### 3.1 What it holds

**Where each fact lives.** A key's help, what its absence means — its default,
or what it blocks — and, for a key `config init` asks for, its question are
declared once, on the key's field of `UserConfig` (`femkit/config/settings.py`):
its description, its `unset` annotation and its `ask` annotation
([`core.md`](core.md) § 2). So are what is measured here and shown beside its
question (`beside`), what `config init` proposes it from (`propose`, § 3.2), a
value that would do (its `examples`), which every step that states the key
shows with its help, and its option's spelling where its name is not that
(`cli`: `activation.command` is `--activation`); the measurements a `beside`
or a `propose` names are code, each once. The template's comments (§ 3.2),
`config init`'s questions, `config show`, the command line's help, every step
that states a key and [`../reference/config.md`](../reference/config.md) read
them there; nothing restates them. The schema model is the authority for types
and allowed values too. The table names what reads each key, not its help.

| key | what reads it |
|---|---|
| `paths.projects` | every project operation, which finds the projects root by it ([`projects.md`](projects.md) § 1); the person's decision ([ADR 0011](../decisions/0011-project-structure.md)) |
| `build.cuda_architectures` | a build compiled for CUDA ([`definitions.md`](definitions.md) § 4.5) — both CUDA environments have one; the default environments never read it |
| `build.jobs` | every build's compile |
| `launch.mpi` | a multi-rank check or job — the environment's own `mpirun` ([`jobs.md`](jobs.md) § 7) — and an MPI environment's toolchain check, which runs two ranks ([`envs.md`](envs.md) § 4.1). It must pass `{ranks}` and may not be empty: a launcher without it would run every job on the wrong number of processes. The same rule holds for a scheduler kind's `mpi_launch` |
| `activation.preamble` | `job probe --write`, which copies it into the machine record ([`jobs.md`](jobs.md) § 9.1), from which a run script runs it before it enters an environment ([`jobs.md`](jobs.md) § 4) |
| `activation.command` | the same, and a run script enters an environment by it. For `conda activate` and `mamba activate`, the manager's shell function exists only once its hook is evaluated: femkit evaluates it first, as the manager prints it — `<manager> shell.bash hook`, the kind's `activate.hook` — from the manager the record names ([`definitions.md`](definitions.md) § 6). For `source activate`, the activate script is found on `PATH`, which only the preamble puts it on after the clean start ([`envs.md`](envs.md) § 4.4). A form the named manager's kind does not have is refused by `env bootstrap` before anything runs, naming the kind's forms ([`envs.md`](envs.md) § 6.2) |

The web server's keys — `[web.auth]`, `web.tls`, `web.trust_proxy`,
`web.public_name`, `web.upload_max_mb` — are [`web.md`](web.md) § 5's and
§ 8.6's, not built yet (plan § 4, M7's remainder).

Every key is optional in the file, and its absence has the one consequence its
field states. Unknown keys are refused at load.

`activation.preamble` and `activation.command` have no default because nothing
on the machine can reveal them: a login shell may have the manager on `PATH`
through a module that a batch job does not load, and a manager answering here
does not say that a batch job's shell can use it — on a cluster whose module
puts `activate` on `PATH`, `source activate` is the form that works. Unset and `[]`
are different answers for the preamble — unset means nobody has said, `[]` means
someone said nothing is needed.

### 3.2 How it is made

- `config init` writes the file from `femkit/data/templates/config.toml`,
  the settings file's template, under [`projects.md`](projects.md) § 7's
  rule: the comment directly above each key is its help as its field states
  it (§ 3.1) — its manual chapter, where it names one, the settings file's,
  `1-install.md` — and every key the template leaves unset is shown commented
  out under its help — held so by a test. Like every changing command it first
  shows its plan ([`api.md`](api.md) § 3): each key it will add and where the value came
  from — given as an option (`--projects`, `--cuda-architectures`,
  `--jobs`, `--mpi`, `--preamble`, `--no-preamble`, `--activation`) or proposed
  from what is found here, as the key's field says (§ 3.1): the GPU
  architectures the driver reports, measured; the launcher the detected
  scheduler kind declares for `launch.mpi` ([`jobs.md`](jobs.md) § 7), the
  kind's, not the machine's. The person consents to the plan — `--yes` is
  that consent — or runs it again with an option to change a value.
- **A default is never written.** It applies while its key is unset, so an
  unattended run never fixes a value measured on one machine into the file for
  good — `build.jobs`, the CPUs this process may use, is a login node's on a
  cluster and an allocation's inside one. A proposal is no default: nothing
  applies while its key is unset, and it is written only on the consent to
  the plan that shows it. Where an environment lies is not a setting: the
  package manager keeps femkit's environments where it keeps every other
  ([`envs.md`](envs.md) § 1), so a cluster's small home quota is met by the
  manager's own configuration (`envs_dirs`, `pkgs_dirs`), never by femkit's.
- `paths.projects` has no default: it is the person's decision
  ([ADR 0011](../decisions/0011-project-structure.md)). While it is unset,
  `config init` asks for it on a terminal, saying what its absence blocks —
  no project is listed, made or named; an empty answer leaves it unset, and
  `--projects` states it without the question. The folder need not exist:
  the first `project new` makes it ([`projects.md`](projects.md) § 1).
- `activation.preamble` and `activation.command` are never proposed. While
  the preamble is unset, `config init` asks for its lines on a terminal,
  showing beside the question the loaded modules when the shell lists them;
  while the command is unset, it asks which of the three it is, saying what
  each means. An empty answer leaves the key unset. `--preamble LINE`
  (repeatable) or `--no-preamble` — a request naming both is refused — and
  `--activation COMMAND` state them without the questions. Left unset, the
  report says what that blocks, naming the options, one step for each form of
  the command.
- **A setting's next step is built in one place**, `config/settings.py`:
  wherever another command needs a key the person states that is unset —
  `doctor`, `job probe`, `study prep`, `job prepare` — its step is `config
  init`, which asks for it in words (`settings.asking`); a key `config init`
  proposes but cannot here — `launch.mpi` on a workstation,
  `build.cuda_architectures` — is `config set` (`settings.setting`); `config
  init`'s own report names each form of its options (`settings.options`),
  each read from the field's declaration — the flag that states a list empty
  declared on its field (`empty`), never spelled from its name.
- Every question is asked as [`api.md`](api.md) § 3.1 states: never under
  `--yes` or `--dry-run`, or without a terminal. A key is asked for when its
  field declares its question (§ 3.1), and beside the question stand the
  key's help, what is measured here for it — the loaded modules — and what
  its absence means.
- Re-running `config init` adds only keys the file lacks and reports each as
  `added` or `kept`; it never replaces a value.
- A key `config init` or `config set` adds goes directly under the line that
  shows it commented out, so it stands under its help; where no line shows
  it, at its table's end.
- `config set KEY VALUE` validates and writes one key, keeping the file's
  comments and layout. `VALUE` is TOML text, as the file writes it —
  `config set paths.projects '"/data/projects"'` — and a bare word is refused,
  never guessed to be text ([`web.md`](web.md) § 7.3): the refusal, about the
  key, says a text is written in quotes and, where the key takes text, gives
  the command again with the word quoted. `config show` prints every key with its value and where
  it came from: the file, or the "when unset" rule.

## 4. Install records and run files

Their contents are owned by their domain contracts; their homes are:

| file | home |
|---|---|
| manifest and check results of an environment | `<prefix>/.femkit/` — removed with the prefix |
| package lock (the solved package list) | `<data>/locks/<environment>/` — kept, so an environment can be recreated exactly |
| operation event logs and command logs | the operation directory ([`core.md`](core.md) § 6) |
| job request, run script, scheduler header, machine record copy, runs | the calculation folder |
