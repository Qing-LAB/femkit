# The framework — layers and where each rule lives

**Role:** contract
**Status:** current; what is not built yet is marked so
**Authority:** package layout, dependency direction, and the map from a
concern to the contract that governs it

## The short version

| rule | § |
|---|---|
| Packages depend downward only: **surfaces → registry → domains → core** | 1 |
| The **core** is the one implementation of files, processes, locks, logs, schemas and state machines ([`core.md`](core.md)) | 2 |
| Every operation is declared once and served by **generic surfaces** ([`api.md`](api.md)) | 2 |
| **State is observed, never stored**; each machine is one closed table | 3 |
| Importing a module probes nothing, reads no user file, starts no process and writes nothing | 1 |
| **One way per concern**: each concern's one mechanism, and what adding a piece takes, listed — found before any helper is written, its row added with any new mechanism | 5, 6 |
| A **request** is the person's, a **record** is the machine's, an **outcome** is what happened: execution runs the request; what the record measured is shown and never vetoes it; a statement missing, contradicting, or naming what the record does not list is refused; the outcome says what the machine did | 4 |

## 1. Packages and layers

```text
femkit/
├── core/          building blocks (core.md); operation types (api.md)
├── data/          shipped definitions (definitions.md)
├── engines/       the readers every engine has, the toolchain program; `stages/`, the
│                  stage programs femkit ships — the geometry's check, Gmsh's meshing,
│                  the mesh's check, the pass-through, the `gmsh` environment's check —
│                  the monitor beside every run (jobs.md § 4.3), and the documents
│                  every stage program reads and writes (`documents.py`); `person/`,
│                  the programs that run the person's Python — `definitions.py`, the
│                  definitions' in `model_prep`; with M6 `observe.py`, the observe
│                  stage's in `postprocess`, and the output translators' runner — and
│                  the modules they share: `functions.py`, the one static reader of a
│                  file of the person's functions, told the signature each must
│                  have; `values.py`, the one check of a returned typed value, and
│                  the one store's writer, through xarray (models.md § 3) — a
│                  namespace package, as `stages/` is; and one package per engine: its
│                  readers, version probe, check programs, its mesh's hand-over,
│                  and (M6) its input writers and the reader of a solve's log
├── schedulers/    readers of each scheduler kind's answers (jobs.md § 7)
├── definitions/   models and loader of the shipped definitions
├── config/        user configuration (config.md)
├── envs/          environment lifecycle; the one door into an environment, from the clean
│                  start `data/process.toml` declares (envs.md)
├── jobs/          machine records and the probe; this machine's setup (`doctor`,
│                  `env bootstrap`); job requests, preparation, run scripts, runs
│                  (jobs.md) — built for a machine without a scheduler
├── projects/      the projects root, a project's tree and the one door to it:
│                  every path, every read; the check frame every part kind's check
│                  is handed; what femkit writes into a project (projects.md) —
│                  built
├── materials/     the property list, the material format, libraries, importers,
│                  a property's data for a case (materials.md) — built but a case
│                  taking a dataset at a variable's value (plan § 4, M9) and a
│                  property's name in an engine's input (M6)
├── geometry/      the geometry script's contract, mesh recipes, kinds and coverage,
│                  the place each built group is, each engine's hand-over
│                  (geometry.md); the programs themselves are in `engines/` — built
├── models/        calculations described once: model, studies, observables parts,
│                  cases, the engines that can solve a study, the match against an
│                  engine's abilities, decisions, customizations, preparation
│                  (models.md) — the parts, their checks, the cases, `project
│                  check` and `project graph` built; the rest not yet (plan § 4,
│                  M5, M6, M8, M9)
├── workflow/      a case's stages, declared as data; a study's workflow graph; a
│                  stage's identity, state and folder writing;
│                  a change's impact; the commands that read or make stages — `study
│                  prep`, `study flow`, `case list`, `project save` (workflow.md)
│                  — built but the check of a built geometry's groups (plan § 4, X)
├── results/       proofs, a case's observables read back, comparisons, analyses
│                  (models.md § 6.3, § 10) — not built yet (plan § 4, M6, M9)
├── server/        `serve`: the web server's verbs, state machine, supervisor,
│                  pidfile and log (web.md § 4); `web build`, the page's
│                  bundle (web.md § 3)
├── registry.py    the one list of operation modules and of part-schema modules; what the
│                  server loads before it starts, handed to it (api.md § 6)
├── reference.py   `schema check|docs`: they span every domain (definitions.md § 2.3)
├── page.py        the page declaration, checked against the operations, and the
│                  theme and its tokens (web.md §§ 8.1, 10.1)
├── cli/           the generic command-line adapter (api.md § 4)
└── web/           the generic flask adapter (web.md), run in the `web`
                   environment; its built front end
scripts/install-env.sh  the install script (envs.md § 7) — the only shell code
tools/             developer tools that import nothing from femkit (testing.md § 4)
```

| layer | packages | may import |
|---|---|---|
| core | `core` | the standard library and declared third-party libraries |
| programs and readers | `engines`, `schedulers` | the standard library, `femkit.core.process` and their own package only — a scheduler's readers, which run in the control process, `femkit.core.units` too — because their programs run inside an environment that holds no femkit dependency — a check program also imports what its environment provides (ngsolve, mpi4py, …); an engine never imports another engine. Lowest of the domains, so the loader of the definitions reads their registries directly. A program run in a stage's job is stricter (below) |
| domains | `definitions`, `config`, `envs`, `jobs`, `projects`, `materials`, `geometry`, `models`, `workflow`, `results`, `server` | core, the programs and readers, and any domain earlier in this list |
| registry | `registry.py`, `reference.py`, `page.py` | every domain |
| surfaces | `cli`, `web` | everything below; never each other |

**One way to do each thing.** Decided by the person; rule 6 waits for the
engines' input writers (plan § 4, M6); under rule 7, every machine observed from facts is a
table in `femkit/data/states/` ([`core.md`](core.md) § 7). Each rule below
has one home, held by design where it can be — a module never given a
project's folder cannot form a path in it — and
by each milestone's independent review, which reads the source against it; no
test reads code ([`testing.md`](testing.md) § 3):

1. in the control process, only `core/persist.py` opens or writes a file —
   code that runs inside an environment (`engines/`) holds to its own
   package's one writer, since it imports nothing of femkit's but `process`;
2. only `projects` forms a path inside a project ([`projects.md`](projects.md) § 6) —
   inside a calculation folder the door hands over, under `runs/`, the jobs
   domain writes, as it does in any calculation folder, and its run script
   writes its runs ([`jobs.md`](jobs.md) §§ 1–5);
3. only `core/units.py` reads a quantity or converts a unit ([`core.md`](core.md) § 11);
4. only the property list names a material property, in femkit, an engine or a
   source ([`materials.md`](materials.md) § 1);
5. only a declared importer reads another library's format
   ([`materials.md`](materials.md) § 7);
6. only an engine's input writer writes that engine's input ([`models.md`](models.md) § 9.1);
7. every rule, table and state machine that can be data is data
   (`femkit/data/`, [`definitions.md`](definitions.md) § 1); code gathers facts
   and does the work.

- The control process never imports a solver library; engine code that needs
  one runs inside the engine's environment as a subprocess.
- **A program run in a stage's job** — a stage program in `engines/stages/`,
  an engine's hand-over — runs where femkit's packages
  are not importable: beside it lie the two modules every such program has,
  `documents.py` (`engines/stages/`) and `process.py` (`core/process.py`,
  standard library only by design) — and, beside a program that runs the
  person's code, the modules of `engines/person/` it imports — and it imports
  the standard library, what its environment provides, and those, by those
  names — nothing else of femkit's. It starts a process only through `process.run`; it writes a
  document only through `documents.write`, and a file in another program's
  format — a mesh — only through the library whose format it is, to a name
  beside it renamed in whole. `job prepare` copies the program and its two
  modules into the calculation folder, and `job launch` from there into each
  run ([`jobs.md`](jobs.md) § 1.1); the monitor, `engines/stages/monitor.py`,
  travels the same way, a standard-library program.
- Importing a module probes nothing, reads no user file, starts no process and
  writes nothing; work starts when a function is called.
- One name per domain: the contract of package `p` is `docs/contracts/p.md`.
  `api.md` covers `registry`, `cli` and `core/operations.py`; `web.md`
  covers `web`, `server` and the page in `frontend/`; `testing.md` covers
  `tests/` and `tools/`. One exception: `doctor` and
  `env bootstrap` are declared in `jobs/setup.py`, because they read and write
  the machine record, and their rules are `envs.md` § 6.1–6.2, because they set
  up environments; the control environment's own machine is the envs domain's,
  `envs/control.py`.
  One more exception, until its own contract is written: `results` is
  governed by `models.md` § 6.3 and § 10.

## 2. Where each concern is governed

| concern | contract |
|---|---|
| schemas and loading, directories, persistence, locks, event logs, state-machine primitive, process runner, refusals, issues, units | [`core.md`](core.md) |
| operation declaration, requests and results, plan/apply, context, CLI conventions, exit codes | [`api.md`](api.md) |
| routes, access, serving, the page: its vocabulary, declaration, layers, elements and styles | [`web.md`](web.md) |
| shipped definitions and kinds | [`definitions.md`](definitions.md) |
| configuration | [`config.md`](config.md) |
| environments, installs, the install script | [`envs.md`](envs.md) |
| a project's tree, its parts, addresses, the one door, the check frame, what femkit writes into a project | [`projects.md`](projects.md) |
| the property list, materials, libraries, importers | [`materials.md`](materials.md) — built but a case taking a dataset at a variable's value (plan § 4, M9) and a property's name in an engine's input (M6) |
| the geometry script's contract, mesh recipes, the six places, the mesh's check, the hand-over to each engine | [`geometry.md`](geometry.md) — the contract, the recipes and the places built; the rest not yet (plan § 4, X) |
| a case's stages and their kinds, each step's own environment, artifacts and meshers' place in them, a study's workflow graph, a stage's identity, state, folder writing and jobs | [`workflow.md`](workflow.md) — built in part (plan § 4, X) |
| a project's definitions: their tables, `definitions.py` read without running it, its functions run in `model_prep` by femkit's program there, declared in `programs.toml`, through the envs domain's one door ([`envs.md`](envs.md) § 4.4) — by the models domain in `project check` and in `study prep` — and each study's values kept; a typed value, a definition's and an observable's; the one store | [`models.md`](models.md) § 3 |
| calculations: physics, studies, observables parts, cases, formulations, environment abilities and proofs, the match report, decisions, customizations, preparation, results and analyses | [`models.md`](models.md) — the parts, their checks, the cases and the graph built; the rest not yet (models.md, status; plan § 4, M5–M9) |
| machine records and the probe, calculation folders, run scripts, runs, the jobs launched from a machine, the monitor, schedulers | [`jobs.md`](jobs.md) |
| tests and the test runner | [`testing.md`](testing.md) |

The rules every change follows, whatever package it touches, are
[`../process/conventions.md`](../process/conventions.md).

## 3. State machines

Built: the control environment ([`envs.md`](envs.md) § 7), an environment
([`envs.md`](envs.md) § 3), an install's steps ([`envs.md`](envs.md) § 4), the
web server ([`web.md`](web.md) § 4), a record of this machine
([`jobs.md`](jobs.md) § 9.3) and a part of a project
([`projects.md`](projects.md) § 8), each but an install's steps declared as
data ([`core.md`](core.md) § 7), a run ([`jobs.md`](jobs.md) § 5.2) and a
calculation folder ([`jobs.md`](jobs.md) § 5.5) and a stage
([`workflow.md`](workflow.md) § 6) among them. Not
built yet: a case's results (M6) — a case's solve and each observe after it
are stages, each its state the stage table's ([`models.md`](models.md) §§ 9.5,
10.1); a study's prep is the state of each of its stages (`to_prep`, [`workflow.md`](workflow.md) § 6). The test runner's tier-run states ([`testing.md`](testing.md)
§ 4.4) are a machine outside femkit.

Every one follows these rules. In Python the primitive that enforces them is
[`core.md`](core.md) § 7, and an install's steps are a fold over its event log
([`core.md`](core.md) § 6); the install script and the test runner follow the
same rules without importing femkit:

- **Observed.** State is computed from durable facts by one pure function each
  time it is asked; it is never written beside those facts.
- **One closed table.** A closed set of states; ordered observation rules that
  end in `otherwise`, so no observation falls through; the actions each state
  allows.
- **Refused before acting.** An action the state does not allow is refused
  with exit code 2 and the allowed actions as the next commands.
- **One source of "next".** Doctor, refusals and hints read the same table.
- **Event logs for steps.** Progress, failure, interruption and resume are
  folds over an operation's append-only log; one atomic write commits the
  result.

The page's own machines — an action's run and the page's state
([`web.md`](web.md) § 9.1) — hold nothing durable; they keep the one closed
table, and live in the page.

## 4. Requests, records and outcomes

Every resource question — ranks, threads, memory, wall time, GPUs, which
environment — has three owners, and each answers only its own part:

| | owner | written by | says |
|---|---|---|---|
| **request** | the person | `job.toml`, a command's options (`env validate --gpu`) | what this work asks for |
| **record** | the machine | `job probe` on that machine ([`jobs.md`](jobs.md) § 9) | what the machine offers, as measured |
| **outcome** | what happened | the work itself: its exit, its log, its markers, what the scheduler granted | what the machine actually did |

- **Execution runs the request, and its outcome proves it.** A check, a
  validate or a run does what was asked and nothing else; no probe decides
  whether it runs. Nothing falls back silently: work that asks for a GPU shows
  it used one — a GPU check's expectations require the device to have done the
  work ([`definitions.md`](definitions.md) § 5.2), and a run asking for GPUs
  stops at its start, saying so, when it sees none ([`jobs.md`](jobs.md) § 4).
  When the machine cannot do what was asked, the outcome says so with the
  reason and its log, so "no GPU was granted" and "the GPU build is broken"
  read differently.
- **Preparation compares the request with the record and shows the
  comparison; it never vetoes it.** What the record says the machine cannot
  do is a warning `Issue` ([`core.md`](core.md) § 10) with the numbers — every
  limit the request is over and the node groups that would hold it — and the
  work is prepared as asked. The machine, or its scheduler, decides; its
  answer is the outcome.
- **What is refused is a missing statement, or one that contradicts the record**: a
  value the work needs that was stated nowhere, a name the record does not
  list (a queue, a target), two statements that contradict each other, a
  record whose `settings` no longer match this machine, a record that lists
  nothing a request could name (no queues on a machine with a scheduler,
  naming the probe that renews it), or an environment to install whose CUDA
  toolkit needs a newer driver than the record measured, since what it builds
  could not run here (the driver is the machine's; femkit never changes it) —
  not built: the record holds no driver version yet (plan § 4, M1).
  These are `Refusal`s
  ([`core.md`](core.md) § 9) — a contradicting statement a `UsageError`, a
  record that no longer matches `Refused` — because nothing could be prepared
  correctly from them.
- **A request is a count, never a model.** A GPU ask is how many; which card,
  which node and whether it works are the machine's. The record keeps the card
  it measured and shows it; nothing compares it. What a run landed on — host,
  and the GPU model with no count — is recorded in the run's `started.json`
  ([`jobs.md`](jobs.md) § 4).
- **A silence is not a limit.** A limit the record does not state, or states
  as `unknown`, is not counted against a request.
- **Every resource is stated.** A request has no default resource: what it
  does not state is refused when the work needs it, never filled in.


## 5. The one way — for each concern

Each concern has one mechanism, and every caller uses it. Before a helper is
written, its concern is found here; a concern that is not here gains its
mechanism in the owner the table names — the core where every domain needs
it — and a row here, in the same change; never a local copy
([`conventions.md`](../process/conventions.md) § 2). The review holds it.

| concern | the one way | contract |
|---|---|---|
| a file written | `persist.atomic_write_text`, `persist.write_json`, `persist.write_toml` — temp, fsync, rename | [`core.md`](core.md) § 4 |
| a file femkit wrote, read back | `persist.read_record(file, model)` — absent, read, or why not; its `schema` stated — a netCDF file of the one store among them (below) | [`core.md`](core.md) § 4 |
| a declared file loaded | `schema.load_toml`, `schema.load_text` — every number exact, every problem at its key | [`core.md`](core.md) § 2 |
| the names a field may take from declared data — the importers, environments, templates, meshers, engines | `schema.provide` at start, `schema.choices` to read them | [`core.md`](core.md) § 2; [`api.md`](api.md) § 6 |
| what a lower layer is handed from above it at femkit's start — a part schema, its check and its keys; what gives the packages the projects declare | the registry, `registry.operations`: what each module of `PARTS` registers, one shape, `REGISTERS` (`checking.Registration`), filled with what it has — registered with the door and the check frame, and its `packages`, the project file's — each project file read alone, by the door's read of one part's file on its own (`door.read_alone`, [`projects.md`](projects.md) § 6), and its `[postprocess]` through its schema, never the project opened (`models/project.py`, `declared`) — handed to the envs domain by `envs.state.provide`, which only `env install` reads | [`api.md`](api.md) § 6; [`definitions.md`](definitions.md) § 4.7 |
| a key a part's file may hold, and its help — on hover, as a suggestion | `checking.keys` → `view.Field.keys`, from the part schema and the `keys` each module of the registry's `PARTS` registers; a JSON schema fragment, `schema.fragment` | [`web.md`](web.md) § 8.3 |
| a field declared | its schema model, once — `as_quantity`, `as_reference`, `as_path`, the extras of [`core.md`](core.md) § 2 — never a second list of fields | [`core.md`](core.md) § 2 |
| a quantity read | `Units.measure` — `{value, unit}`, a plain number or a definition's name, exact | [`core.md`](core.md) § 11 |
| a value shown | `Units.shown`, in a study's display units | [`core.md`](core.md) § 11 |
| the line a key of a TOML text stands at | `persist.key_line`; for a part's file, the door's `line_of` | [`core.md`](core.md) § 10 |
| a unit converted | `core/units.py` alone; memory's letters `units.MEMORY_LETTERS` | [`core.md`](core.md) § 11 |
| a process started, signalled, awaited | `core/process.py` | [`core.md`](core.md) § 8 |
| an operation's steps recorded, and its progress, failed step or interruption read back | `core/eventlog.py` — the log and its one fold | [`core.md`](core.md) § 6 |
| a folder of femkit's — config, data, cache, state, runtime, bin, the checkout | `core/dirs.py` | [`config.md`](config.md) § 2 |
| the time now, as femkit writes it | `core/clock.py` | [`core.md`](core.md) § 4 |
| a subject held | `locks.subject_lock` | [`core.md`](core.md) § 5 |
| a request refused — a field missing, a word no number, a key it does not take | `Operation.request_from`, one refusal for both surfaces (`operations.refused`), each field as written by `commandline.written` | [`api.md`](api.md) § 4 |
| an operation | a `Verb` (name, request, `on_machine`, `effect` — the one statement of whether it reads, changes or removes) in `<domain>/requests.py`; `@operation` with `observe`/`plan`/`apply`, and `outcome` where its plan foresees what it would show; the runner holds the locks, checks the basis, carries the plan's issues | [`api.md`](api.md) §§ 2–3 |
| a request read from the command line, an `Action` written as one | `core/commandline.py` | [`api.md`](api.md) § 4 |
| what a result shows | its `report`, built from its own fields — `Text`, `Code`, `Table` from its row model, `Graph`, `Next`; one renderer per surface | [`web.md`](web.md) § 7.7 |
| a refusal | a kind of `core/errors.py` with its `code`, `subject`, `next` and the `issues` it rests on | [`core.md`](core.md) § 9 |
| a finding | an `Issue`, at its file, line and key; a refusal as one by `Issue.of`, placed at its part's file, key and line by `door.finding_of`, built on it — never `Issue(code=exc.code …)` by hand | [`core.md`](core.md) § 10 |
| a finding at a line of the person's Python — what the static reader finds, a `Fault` | `checking.at_line`, the check frame's one maker: an error at the file's line, its subject the file's address, `<kind>:<name>@<file>`, so its part counts it (`Opened.owner`) | [`projects.md`](projects.md) § 6; [`models.md`](models.md) §§ 3, 5.2 |
| a next step | a subject's next step is its state table's row (`Machine.next`, `[next_from]`) — the one source; `view.command` writes the `Action` naming an operation, which a table's row and a refusal naming what clears it both use; for another machine `view.at`; never a remedy written by hand | [`core.md`](core.md) § 7, [`web.md`](web.md) § 7.2 |
| a step needing a setting | `config/settings.py` — `asking`, `setting`, `options`, read from the field's declaration | [`config.md`](config.md) § 3.2 |
| a subject's state, and what code does in it | a state table in `femkit/data/states/`, its `[tasks]` and `[does]`; the bound machine from `catalogue.machine`, `Machine.does` | [`core.md`](core.md) § 7 |
| whether a record is this machine's | `record.of_this_machine` | [`jobs.md`](jobs.md) § 3 |
| a call into an environment — a manager command, femkit's programs, the person's `definitions.py`, `observe.py` and translators, a check, a build step, `web build`'s npm, the web server's supervisor and child, a run script the jobs domain writes | the clean start declared in `femkit/data/process.toml` — what passes, what is removed, how a scheduler kind's declared shell function passes, the system `PATH` — and each scheduler kind's `passes` and `functions`, read by its one owner, `envs/start.py`: `begin` for a process femkit starts (the manager's own commands, `Manager.environment`; a command inside an environment, `envs/inside.py`), `clean` for the invocation's, `lines` for a run script's shell (block 8) — the install script writing the same lines from the same data; femkit's own process, through the `femkit` command and the install script's forward, isolated (`-I`) and keeping the shell but what `femkit_sheds` names, so it sees the machine it probes (`own_lines`); then the manager's own `run -n <name>` or activation by the name; never `PATH` or a library path set by hand, never a list of variables in code | [`envs.md`](envs.md) § 4.4; [`jobs.md`](jobs.md) § 4 |
| femkit's own Python program on an environment's Python — the web server's supervisor and child, a check program — started | `dirs.femkit_argv`, the module run with `-P`, and `dirs.femkit_env` over the clean start (`start.clean`, above): the door's one addition, the checkout alone as `PYTHONPATH`, never a filter of its own | [`envs.md`](envs.md) §§ 4.4, 7; [`core.md`](core.md) §§ 3, 8 |
| an environment's name with the manager, and where it lies | the one naming rule, `femkit/data/naming.toml` — `femkit`, `femkit-<name>` — read by `catalogue.managed` and the install script; its prefix the listed one the manager names so — its own name for it, or in one of its `envs_dirs` under the name — `Manager.prefix`, never formed nor taken from a listed path's last step; a folder in its way it does not list, `Manager.orphan` | [`envs.md`](envs.md) §§ 1, 3 |
| the person's own manager settings that would change what goes into an environment | the manager kind's `settings`: each set aside by the flags its solving commands carry, or refused before any create — `Manager.settings`, `install.refuse_settings`; what was set aside recorded in the manifest | [`envs.md`](envs.md) § 4.4 |
| a program run inside an environment | `envs/inside.py`, the program declared in `programs.toml`; whether the environment may be used, `envs.state.usable` | [`envs.md`](envs.md) §§ 3.3, 4.4 |
| the lines that enter an environment — in a run script, bootstrap's lines, the line that opens an output | `envs/manager.entering`: the machine's preamble, then the activation of the environment by its name | [`envs.md`](envs.md) § 6.2, [`jobs.md`](jobs.md) § 4 |
| a document crossing into an environment | its program's documents module — `engines/stages/documents.py` for the stages, the observe stage's among them, `engines/person/definitions.py` for the definitions — each kind its schema and one writer | [`models.md`](models.md) § 9.1 |
| the person's Python run — `definitions.py`, `observe.py`, an output translator's script | femkit's program for it in `engines/person/`, declared in `programs.toml` with its entry and its time limit, the one home of that limit; its environment the one home its step gives it — the definitions' entry in `programs.toml` (`model_prep`), a stage's kind in `stages.toml` (`postprocess` for observe; a translator's as declared for it, M6), never both; an operation starts it through `envs/inside.py`, a stage's job by its run script; it runs each script in one process of its own and holds what each function returns to its type — built for `definitions.py`; `observe.py` and the translators with M6 | [`models.md`](models.md) §§ 3, 5.2, 8.4; [`workflow.md`](workflow.md) § 2.1 |
| a file of the person's functions read without running it — their names, their imports, what each reads | `engines/person/functions.py`, the one static reader, told the signature each function must have — none for a definition's, one argument for an observable's — what its file may import: its environment's declared modules, and for `observe.py` its project's packages — and the tables of the object a function is handed first whose reads it tracks, through each function it calls: `observe.py`'s `case.defs` and `case.groups`, held to its `takes` | [`models.md`](models.md) §§ 3, 5.2 |
| a value a function of the person's returned — a number or an xarray DataArray — held to its declaration: its type, its dimensions, a coordinate for each, every value finite; never its physical dimension, the person's promise | `engines/person/values.py`, the one check of a typed value | [`models.md`](models.md) § 3 |
| every declared output femkit keeps — a study's computed definitions, a case's observables, what an output translator gives | the one store, the one door for netCDF in femkit: one writer, through xarray, inside the environment that computed them (`engines/person/values.py`), in a process of its own with one thread, holding no lock; and one reader in the control process, `persist.read_record`, through netCDF4 without xarray, which holds one process-wide lock around every call into the netCDF-C library, since the web server's threads read there; each file its `schema` attribute, checked on read, its metadata by the CF conventions and its provenance as its attributes — case, study, engine, environment, run, script hash — and no time, so the same result is the same bytes; the lock `persist.NETCDF_LOCK`, and a file of the store named `.nc` | [`models.md`](models.md) §§ 3, 10.1; [`core.md`](core.md) § 4 |
| a part's file of an earlier shape | three mechanisms, for three kinds of change: a file of the kind's own form whose shape was raised — its part schema's shape, `schema_: Literal[n]`, and what changed in each shape after the first, `CHANGES` (`projects/schemas.py`, `PartFile`): one finding naming both shapes and what changed; a key a schema no longer takes, its shape unchanged — the model's `WITHDRAWN`, each such key with what a file writing it is told (`core/schema.py`, `Model`): its finding at that key, in those words (a study's `engine`); and a part kind whose parts were once each one file and are now a folder — the layout's `was = "file"` on the kind, a file of the old form the door's finding `now-a-folder`, never a stray (`projects/door.py`) | [`models.md`](models.md) § 2; [`projects.md`](projects.md) § 4; [`core.md`](core.md) § 2 |
| the closest of the names there are — "did you mean `x`?" | `core/schema.py`, `nearest` — compared by each of a name's `forms` — and `meant`, the end of a finding's sentence, as `shown` writes the name; a schema's unknown key, a unit, a name a part cites alike | [`core.md`](core.md) § 2 |
| the environment an engine solves in, and an environment's `-cuda` twin by GPUs | the catalogue (`definitions/catalogue.py`): `engines`, each engine `study prep --engine` may name with the engine environment whose definition declares it — one alone, two declaring one refused when they load; the twin, `with_gpus`, where GPUs are asked, which a job's environment takes too | [`definitions.md`](definitions.md) §§ 2.2, 4, 4.5; [`jobs.md`](jobs.md) § 3, step 4 |
| the engines that can solve a study — those a hand-over gives the mesh its recipe's mesher writes, at each geometry order of its cases — and whether one engine can | `models/study.py`, `solvers` and `takes`, over the hand-overs' one lookup (`definitions/meshers.py`, `handover`): read by `project check`, `study list`, the graph's facts, `study prep --engine` and the engine each `study prep` action asks for alike | [`models.md`](models.md) § 5.1; [`workflow.md`](workflow.md) § 2.2 |
| the values an action asks of the person before it runs | its `fills`, each a request field's whole fill (`view.Fill.of`); for a state table's action, its row's `fills`, each a field of its operation's request, checked when the table loads; where its subject narrows what a field may take — the engines that can solve a study, `study.solvers` — the fill's fragment a closed list of those names, `Fill.of(…, choices=…)` (`schema.narrowed`), a state table's from its binding's `choices`, read from the subject's facts | [`web.md`](web.md) § 7.2; [`core.md`](core.md) § 7 |
| a calculation folder's runs, their files and their state | `jobs/runs.py`, the run door | [`jobs.md`](jobs.md) § 5 |
| the job still going that runs or holds a folder | `jobs.addresses.running` | [`jobs.md`](jobs.md) § 5.4 |
| what a built geometry holds, against what its contract promises | `geometry.steps.built`, `unheld` | [`geometry.md`](geometry.md) § 7 |
| a file of a project saved as typed, and the change's impact | `project save`; `workflow/impact.py`; the file unchanged since opened, `door.unchanged` | [`workflow.md`](workflow.md) § 10 |
| a path inside a project | the door, `projects/door.py`; inside a calculation folder, the jobs domain | [`projects.md`](projects.md) § 6 |
| the order parts are read or checked | the layout, `layout.read_once` — section, rank, place, name | [`projects.md`](projects.md) § 4 |
| the project layout read — by the door, the checks, the page, and `schema check`, which holds each stage kind's `brings` to it | its one reader, `projects/layout.py` (`read`, `load`, once per invocation each), never the file read raw: the catalogue below it reads no layout | [`projects.md`](projects.md) § 4; [`definitions.md`](definitions.md) § 2.3 |
| a stage kind, a mesher, a hand-over | their declarations in `femkit/data/`, read by `definitions/` | [`workflow.md`](workflow.md) § 2 |
| an engine's output turned into a standard form for a script | an output translator: its declaration — what it takes, what standard form it gives — and its Python script, run by the one runner of the person's Python and held by its one check, what it gives kept by the one store, whether femkit ships it in `femkit/data/translators/` or the person writes it, a part kind of the project; run as a stage of the `translate` kind; never femkit converting the data itself — with M6 | [`workflow.md`](workflow.md) § 2.4 |
| the page talking to the server | `frontend/src/kernel/client.ts` alone | [`web.md`](web.md) § 9.1 |
| the page never a blank window — a piece of an old build gone from the server, a view that cannot be drawn | `main.tsx`'s one answer to `vite:preloadError`, reading the page again once per build; the shell's one holder around each workspace, `shell/Recover.tsx`, saying what could not be drawn with the control to read the page again | [`web.md`](web.md) § 9.1 |
| a file's text shown, edited, its findings at their keys, its keys' help and suggestions | `elements/TextEditor.tsx` on CodeMirror 6; a file's language, `kernel/editor.ts`'s `languageOf` over the declaration's patterns; the key at a place of the text, `kernel/toml.ts`'s `keyAt` | [`web.md`](web.md) §§ 8.3, 9.2 |
| a sentence's backticks drawn as code; a style text applied under the page's policy | `kernel/sentence.ts`; `kernel/styles.ts`, `adopt` | [`web.md`](web.md) §§ 9.2, 5 |
| what a shown plan's findings are about, marked on the diagrams | `kernel/marks.ts` | [`web.md`](web.md) § 2.4 |
| an action on the page | the action machine, declared in the page declaration (`action`) and run by `kernel/action.ts`; its dialogs kept apart from the press that opened them, `kernel/flows.ts` | [`web.md`](web.md) § 9.1 |
| the page's context, workspace and selection, and the address that mirrors them | `kernel/state.ts` | [`web.md`](web.md) § 9.1 |
| a context's choices; a document's address in the viewer | `kernel/choices.ts`; `kernel/documents.ts` | [`web.md`](web.md) §§ 8.1, 2.3 |
| the theme chosen; the notices kept | `kernel/theme.ts`, over the declared themes; `kernel/notify.ts` | [`web.md`](web.md) §§ 10.2, 9.2 |
| a value written as TOML for a field that takes TOML (`config set`'s value) | `kernel/toml.ts`, `write` | [`web.md`](web.md) § 7.3 |
| what the bundle carries before any token — the gate's words, the mark, the addresses | `frontend/src/generated/bundle.json`, written by `schema docs` from the declaration | [`web.md`](web.md) § 8.1 |
| something the page shows | the element of its vocabulary model (§ 9.2 of [`web.md`](web.md)) | [`web.md`](web.md) § 9.2 |
| a sentence the page says of what it draws — a wire, a port of an opened block | the declaration's `sentences`, the first of a list whose placeholders the values fill: `kernel/declared.ts`, `sentence` | [`web.md`](web.md) § 8.1 |
| a design value — colour, space, type, motion | `femkit/data/web/theme.toml`, loaded by `page.load_theme`, generated into `tokens.css` by `schema docs` | [`web.md`](web.md) § 10.1 |
| the page's workspaces, groups, icons, themes | `femkit/data/web/page.toml` | [`web.md`](web.md) § 8.1 |
| which surface offers an operation — the command line, the page | its `surfaces`, read by `registry.offered` | [`api.md`](api.md) § 2 |
| a file the server must load before it serves — the configuration, the declaration | `server/startup.register` | [`web.md`](web.md) § 4 |
| a file generated from femkit's models — the reference pages, the page's schemas, icons and tokens | `reference.py`, written by `schema docs`, checked by the reference test | [`definitions.md`](definitions.md) § 2.3 |
| a design value read by the page's code — a breakpoint, a duration | `kernel/tokens.ts`, `measure` | [`web.md`](web.md) § 10.1 |
| a colour by a block word, a group or a severity | the element's `data-shows`, `data-group`, `data-severity`, bound in `tokens.css` | [`web.md`](web.md) § 10.1 |
| a workspace's or a panel's document, built from the context | `kernel/document.ts` | [`web.md`](web.md) § 9.1 |
| the operations running, and their progress | `kernel/runs.ts` | [`web.md`](web.md) § 9.1 |

## 6. Adding a piece — what it takes, and nothing more

Each is declarations and the one ways above; what is never written by hand is
said.

- **An operation**: its `Verb` and request model in `<domain>/requests.py`;
  the operation in its domain with `@operation`; its result model with its
  `report`; its next steps from its subjects' tables. No command-line or page
  code — both are generic ([`api.md`](api.md) § 2).
- **A state machine**: its table in `femkit/data/states/` — states, rules,
  actions, `[tasks]` and `[does]`, `[shows]` where it is drawn — and its
  `Binding` naming the facts code gathers ([`core.md`](core.md) § 7). No state
  compared as text, no remedy written beside it.
- **A part kind or an object type**: its schema model and its row in the
  layout — folder, file, section, rank ([`projects.md`](projects.md) § 4); its
  icon in `page.toml`. No order or kind named in code.
- **A stage kind, a mesher, a hand-over**: its declaration in `femkit/data/`
  ([`workflow.md`](workflow.md) § 2); its program under `femkit/engines/` with
  its documents' kind; a stage kind's icon in `page.toml`, which refuses to
  load without it. No branch per kind.
- **An output translator**: its declaration — what it takes, what it gives —
  and its script, a file of the person's Python (below), in
  `femkit/data/translators/` or the project; no program of its own (with M6;
  [`workflow.md`](workflow.md) § 2.4).
- **A group of operations** (a new first word of a command): its name in
  `registry.GROUPS`, and its entry in `page.toml` — title, icon and accent
  token, placed in the order of work ([`web.md`](web.md) § 8.1); the page
  refuses a group of the registry it lacks.
- **A program in an environment**: its entry in `programs.toml`, started
  through `envs/inside.py` ([`envs.md`](envs.md) § 4.4).
- **A file of the person's Python**: its part kind's row in the layout,
  naming the file by its fixed name ([`projects.md`](projects.md) § 4); its
  program in `engines/person/`, declared in `programs.toml` with its time
  limit, its environment where its step declares it (§ 5); the signature its
  functions must have and the modules it may import, handed to the one
  static reader; what each returns, a typed value, held by the one check and
  kept by the one writer of typed values (§ 5). No second runner, reader,
  check or store.
- **A setting**: its field on `UserConfig` with its declaration — `ask`,
  `propose`, `empty` — ([`config.md`](config.md) § 3.1); its steps come from
  `config/settings.py`.
- **A page workspace, panel or group**: its entry in `page.toml`; a view only
  arranges elements ([`web.md`](web.md) §§ 8.1, 9.3).
- **A page element**: one component rendering one vocabulary model, its sheet
  using tokens alone ([`web.md`](web.md) § 9.2).
- **A design value**: a token in `theme.toml`, then `schema docs` — never a
  number or colour in a stylesheet or the page's code ([`web.md`](web.md)
  § 10.1).
