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
| A **request** is the person's, a **record** is the machine's, an **outcome** is what happened: execution runs the request; what the record measured is shown and never vetoes it; a statement missing, contradicting, or naming what the record does not list is refused; the outcome says what the machine did | 4 |

## 1. Packages and layers

```text
femkit/
├── core/          building blocks (core.md); operation types (api.md)
├── data/          shipped definitions (definitions.md)
├── definitions/   models and loader of the shipped definitions
├── engines/<e>/   one package per engine: readers, version probe, check programs
├── schedulers/    readers of each scheduler kind's answers (jobs.md § 7)
├── config/        user configuration (config.md)
├── envs/          environment lifecycle (envs.md)
├── jobs/          machine records and the probe; this machine's setup (`doctor`,
│                  `env bootstrap`); job requests, preparation, run scripts, runs
│                  (jobs.md) — records, the probe and setup built, the rest not yet
├── projects/      the projects root, a project's tree and the one door to it:
│                  every path, every read and write, transactions and undo
│                  (projects.md) — proposed, not built yet (plan § 3, R)
├── materials/     the property list, the material format, libraries, importers,
│                  a property's data for a case (materials.md) — proposed, not built yet
├── geometry/      the geometry script's contract, mesh recipes, the mesh step,
│                  kinds and coverage, the hand-over to each engine (geometry.md) —
│                  proposed, not built yet; the mesh step's code runs inside its
│                  environment (plan § 3, X)
├── models/        calculations described once: model, studies, cases, the match
│                  against an environment's abilities, decisions, customizations,
│                  preparation (models.md) — the schemas and `model check` built;
│                  the rest not yet (plan § 3, M5, M6, M8, M9)
├── results/       a run's observables, proofs, comparisons, analysis (models.md
│                  § 6.3, § 10) — not built yet (plan § 3, M6)
├── server/        `serve`: the web server's verbs, state machine, supervisor,
│                  pidfile and log (web.md § 4); `web build`, the page's
│                  bundle (web.md § 3)
├── registry.py    the one list of operation modules (api.md § 6)
├── reference.py   `schema check|docs`: they span every domain (definitions.md § 2.3)
├── cli/           the generic command-line adapter (api.md § 4)
└── web/           the generic flask adapter (web.md), run in the `web`
                   environment; its built front end
scripts/install-env.sh  the install script (envs.md § 7) — the only shell code
tools/             developer tools that import nothing from femkit (testing.md § 4)
```

| layer | packages | may import |
|---|---|---|
| core | `core` | the standard library and declared third-party libraries |
| domains | `definitions`, `engines`, `schedulers`, `config`, `envs`, `jobs`, `projects`, `materials`, `geometry`, `models`, `results`, `server` | core, and any domain earlier in this list — except `engines`, which imports only the standard library, `femkit.core.process` and its own package, because its check programs run inside an engine environment that holds no femkit dependency; an engine never imports another engine |
| registry | `registry.py`, `reference.py` | every domain |
| surfaces | `cli`, `web` | everything below; never each other |

**One way to do each thing.** Decided by the person; not built yet (plan § 3, R step C). Each rule below
has one home, held by design where it can be — a module never given a
project's folder cannot form a path in it — and by each milestone's
independent review, which reads the source against it; no test reads code
([`testing.md`](testing.md) § 3):

1. in the control process, only `core/persist.py` opens or writes a file —
   code that runs inside an environment (`engines/`) holds to its own
   package's one writer, since it imports nothing of femkit's;
2. only `projects` forms a path inside a project ([`projects.md`](projects.md) § 6);
3. only `core/units.py` reads a quantity or converts a unit ([`core.md`](core.md) § 11);
4. only the property list names a material property, in femkit, an engine or a
   source ([`materials.md`](materials.md) § 1);
5. only a declared importer reads another library's format
   ([`materials.md`](materials.md) § 7);
6. only an engine's translator writes that engine's input ([`models.md`](models.md) § 9.1);
7. every rule, table and state machine that can be data is data
   (`femkit/data/`, [`definitions.md`](definitions.md) § 1); code gathers facts
   and does the work.

- The control process never imports a solver library; engine code that needs
  one runs inside the engine's environment as a subprocess.
- Importing a module probes nothing, reads no user file, starts no process and
  writes nothing; work starts when a function is called.
- One name per domain: the contract of package `p` is `docs/contracts/p.md`.
  `api.md` covers `registry`, `cli` and `core/operations.py`; `web.md`
  covers `web`, `server` and the page in `frontend/`; `testing.md` covers
  `tests/` and `tools/`. One exception: `doctor` and
  `env bootstrap` are declared in `jobs/setup.py`, because they read and write
  the machine record, and their rules are `envs.md` § 6.1–6.2, because they set
  up environments.
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
| a project's tree, its parts, addresses, the one door, transactions and undo | [`projects.md`](projects.md) — proposed (plan § 3, R) |
| the property list, materials, libraries, importers | [`materials.md`](materials.md) — proposed (plan § 3, R) |
| the geometry script's contract, the pipeline's steps, mesh recipes, the mesh step and the hand-over | [`geometry.md`](geometry.md) — proposed (plan § 3, R) |
| calculations: parameters, physics, studies, observables, cases, formulations, environment abilities and proofs, the match report, decisions, customizations, preparation, results and analyses | [`models.md`](models.md) — not built yet (plan § 3, M5–M9, R) |
| machine records and the probe, jobs, schedulers | [`jobs.md`](jobs.md) |
| tests and the test runner | [`testing.md`](testing.md) |

The rules every change follows, whatever package it touches, are
[`../process/conventions.md`](../process/conventions.md).

## 3. State machines

Built: the install script's control environment ([`envs.md`](envs.md) § 7),
an environment ([`envs.md`](envs.md) § 3), an install's steps
([`envs.md`](envs.md) § 4) and the web server ([`web.md`](web.md) § 4). Not
built yet: a run ([`jobs.md`](jobs.md) § 5; plan § 3, M3) and a case's
preparation ([`models.md`](models.md) § 9.5; M6); a part of a project
([`projects.md`](projects.md) § 8), a step's run
([`geometry.md`](geometry.md) § 4; plan § 3, X), a study's expansion (plan
§ 3, R) and a run's results (M6). The test runner's batch states ([`testing.md`](testing.md)
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
  could not run here (the driver is the machine's; femkit never changes it).
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

