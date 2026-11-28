# Jobs — requests, run scripts, runs and schedulers

**Role:** contract
**Status:** current; built: §§ 1–6 and § 8's `job prepare`, `launch`, `status`, `list` and `cancel` for a machine without a scheduler, machine records and the probe (§ 9), and the scheduler kinds' probe commands and readers, each kind checked against its reader when it loads (§ 7) — but the review's fixes written into §§ 1–5.5, parked until the project and workflow layers are done (plan § 4, X, "Jobs, parked"). Not built: § 7's header, submit, check, query and cancel (plan § 4, M4)
**Authority:** machine records and the probe, the job request, preparation,
the run script, the run state machine, and how femkit uses a scheduler

## The short version

| rule | § |
|---|---|
| A **job** runs one command in one environment with stated resources, on one node; a **calculation folder** holds its request, its scripts and its runs. This contract runs any calculation folder and knows nothing of geometry, meshes or projects: a stage of a case's pipeline is one ([`workflow.md`](workflow.md)) | 1, 2 |
| One writer makes a calculation folder; every file of a calculation folder, a launch folder and a run is declared once, with its writer and its readers | 1 |
| A **batch** is one job running calculation folders that take nothing from each other, one after another; a **sequence** is one job launching batches or single folders in turn. Each keeps its request, header, walk, launch record and log in a launch folder, its members' runs where they always are | 1.2, 4.1, 4.2 |
| `job prepare` reads the request, **the calculation's own copy of its target's machine record** — taken at the first prepare and never changed — and the scheduler kind, writes a self-contained run script for the request as stated, and shows how it fits the record | 3 |
| The run script is a **closed list of blocks**, the person's earlier, cluster-proven run script's: it opens its log and its exit trap before anything can stop it, starts clean from the declared pass list ([`envs.md`](envs.md) § 4.4), enters the environment as the target's record says — its preamble and its activation, verbatim, of the environment by its name — verifies the environment it entered, runs the command on the environment's own `python`, and arranges no file. A **monitor** runs beside it | 4 |
| **Two facts, two files**: `ended.json` says how the command ended; `checked.json`, the contract's verdict on what it left. A run finishes when both say so | 4, 5 |
| A run is **one start**, and only `job launch` starts one. What the person brings is copied into a run; what a stage of the workflow made is **shared** — read where it was made, by its SHA-256 | 1, 2, 5 |
| A run's state is **observed** from its records by the earlier tool's order of evidence — its start before its launch record, the job's word **asked once, written once** by whichever reader asks first — into `pending`, `queued`, `running`, `finished`, `failed`, `unreadable`; a calculation folder's state, over its preparation, the job that holds it and its newest run, is declared too | 5 |
| **Every launch leaves an address** on this machine, as a server leaves its pidfile: `job list` shows each job and its runs' states, `job cancel ID` stops one. A launch here goes to the background, or is **waited on** and exits by how its runs ended | 5, 5.4 |
| **One job per launch**, by the person; femkit never submits in a loop, retries, or changes an ask | 6 |
| What a scheduler is told is its **kind file**, from closed lists of parts; only irregular answers have readers, in `femkit/schedulers/` | 7 |
| A **machine record** holds what one machine offers, measured by `job probe` on it: scheduler, queues, node groups, installed environments, where femkit is, and the settings a run script needs. It is shown, never a veto | 9 |

Turning a scientific model into solver input is not this contract; it produces
the inputs a job request names. The shape of every part below is the person's
earlier tool's, proven on the cluster; femkit departs from it only where a
line here says so and why.

## 1. The calculation folder

```text
<calculation>/
├── job.toml          the request — written by a person, or by femkit's one writer (below)
├── <inputs>          files the command reads, as the request lists them
├── <maker's files>   what the folder's maker keeps beside the request — a stage's stage.json
├── machine.toml      the calculation's own copy of its target's record, taken at its first prepare (§ 3)
├── <programs>        femkit's programs the request names, and the monitor — copied in by prepare
├── run.sh            the run script (§ 4)
├── submit.sh         the scheduler header that starts run.sh (targets with a scheduler)
├── prepared.json     what prepare resolved — written last
└── run-0/            one start: copies of job.toml, the inputs, run.sh — the paths of
                      what it shares written in — submit.sh and the programs; its
                      outputs, its log, the monitor's log and its records (§ 5.1)
```

Runs are numbered as the earlier tool numbers them: `run-0`, `run-1`, … — the
next unused number, not padded. `job launch` opens each run it fills, the
first among them: femkit's calculation folder holds what the earlier tool's
prep put into its first run — the request, the inputs, the programs — so
`job prepare` opens no run.

A calculation folder is written by a person anywhere — a solver run on inputs
they wrote — or by femkit: a stage of a case's pipeline
([`workflow.md`](workflow.md) § 5), at the path its project's door forms
([`projects.md`](projects.md) § 2). A job reads nothing outside its run but
the files its request shares (§ 2). A job command names a calculation folder
by its path, from the folder it runs in; every next step femkit prints names
it by its full path, so the line runs wherever it is typed, and the page sends
full paths. A step for another machine — `job prepare --target`'s own, a
maker's — carries the machine it runs on (`Action.on`, [`web.md`](web.md)
§ 7.2), a line for that machine, never run here.

### 1.1 How femkit writes one

- **One writer.** femkit writes a calculation folder through one function,
  `jobs.folders.write(folder, request, files)`: the request, its inputs and
  the maker's files — a launch folder's `maker.json`, `{"action": <the
  Action that writes it again>}`, declared in the catalogue;
  a stage's `stage.json`, declared by the workflow in `stages.toml`
  (`made_from`), the catalogue holding only its slot — before its first prepare; nothing else
  writes into a calculation folder but `job prepare`, `job launch`, a run's
  script and the records of § 5.1. The maker writes its request again, its
  resources alone, where the folder's state allows `prepare` — no job holds
  it and no run of it goes (`jobs.folders.restate`), refused `not-allowed`
  with its state's next steps otherwise: how a folder runs may change, never what it runs
  — as the earlier tool prepares a stage again when only how it runs
  changes; the folder is then `stale` and prepared again (§ 3).
- **One catalogue.** Every file of a calculation folder, a launch folder
  (§ 1.2) and a run — its name, its writer, its readers, and whether a run's
  copy of it is made — is declared once, `femkit/data/jobs/files.toml`, which
  `jobs/layout.py` reads through the per-invocation cache, as the earlier tool
  keeps one catalogue of a run's files; every name the code reads is declared
  there, or it does not load. `schema docs` renders each file's row — its
  writer and its readers — into `docs/reference/` (parked with the jobs fixes);
  this section's tree and § 5.1's records are a summary of that page.
- **Programs.** A request may name femkit's own programs, `programs`, by their
  path in `femkit/engines/stages/`: `job prepare` copies each, with the
  standard-library modules it runs with and the monitor, into the calculation
  folder and records its SHA-256, and `job launch` copies them from there into
  each run, as the earlier tool copies its bundles beside the deck at prep. A
  run never reads femkit's checkout, and a checkout changed between prepare
  and launch never reaches it.
- **One process.** A request may state `one_process = true`, as the earlier
  tool marks an engine that runs one process: it then states `ranks = 1`, and
  `job prepare` refuses another count; inside a job that holds more, it runs
  with its own (§ 1.2).

### 1.2 Batches and sequences

- **A batch** is calculation folders that take nothing from each other, run
  in one job. On disk a batch is nothing new: each member is prepared as it
  would be alone — its own request, scripts and runs — and the batch's one job
  keeps its request, its header, its walk, its launch record and its log in a
  **launch folder** of its own. The walk runs each member's run script in that
  member's own new run, one after another; a member that fails does not stop
  the others (§ 4.1).
- **A sequence** is batches or single calculation folders, in the order each
  takes from those before it, sent as one job whose walk launches each inside
  the job with femkit's own `job launch`, waited on (§ 4.2): each part is
  planned when its turn comes, so it takes what it shares from runs the parts
  before it have just finished, under every check a launch has.
- **A launch folder states its job's resources**, explicitly, in its request:
  one job is one batch with one set of resources, and every member and part
  inside it runs with what the job holds (the person, 2026-11-25). Each
  member's and part's request states the job's queue, wall and memory, and
  counts that fit inside the job's — `ranks × threads` no more than the job's
  cores, `gpus` no more than its — and `job prepare` refuses one that differs,
  naming each value. Nothing is derived from the members: the earlier tool
  sums its members' walls and takes the largest of their counts, which
  femkit's launch folders, written by the workflow from the study's statement
  of the job, need not.
- **A member whose shared input did not finish is left out**, and the part's
  launch names it and the input; so is a member a job still going has — held,
  queued or running — and one whose newest run finished, whose outputs the
  parts after it take — a sequence written again for the parts an earlier
  job left; the walk goes on to the next part. A stage depends on its own inputs alone (the
  person, 2026-11-25), so a batch of independent members never fails as a
  whole: only a part's refused launch, or a stop signal, ends a sequence's
  job. A calculation folder launched outside a sequence after its run
  finished makes a new run (§ 5.3).
- **Launched again to continue**, as the earlier tool launches a group again
  whole: a job that ended — stopped at its wall, failed, cancelled — is
  continued by `job launch` of its launch folder again; its walk uses each
  member or part that finished and runs the rest anew, each a new run, and
  the folder keeps each launch's record and log. Nothing is ever added to a
  job once launched: a new case is a new prep's job. What wrote a launch
  folder is named by its maker's file `maker.json`, so `job status` offers it
  without knowing what wrote it (§ 1.1) — for a folder whose members changed
  (§ 5.5). An action naming an operation
  femkit does not have is never offered: `job status` says so, a warning,
  `maker-unknown`, naming the operation — no old name is kept to map it
  (conventions § 2). A member or part a job still going
  holds is not prepared or launched by anything but that job's own sequence
  (§§ 3, 5), as in the earlier tool.

## 2. The job request — `job.toml`

```toml
environment = "elmer"                  # an environment, by name
command = ["ElmerSolver", "case.sif"]
inputs = ["case.sif"]                  # copied into each run
name = "bowtie-gap"

[resources]
ranks = 4
threads = 2                            # per rank
gpus = 0                               # per node, a count; 0 states "no GPU"
wall = "02:00:00"
memory = "16G"                         # per node
partition = "<partition>"              # the queue, on a machine with a scheduler
qos = "<qos>"                          # where the record lists QOS for the partition
```

A request femkit writes for a stage may add:

```toml
programs = ["check_mesh.py"]                     # femkit's own, copied in by prepare (§ 1)
one_process = true                               # § 1
outputs = ["mesh.msh", "regions.json"]           # what its contract promises; made read-only once checked
check = ["{python}", "check_mesh.py", "recipe.json", "regions.json"]   # the contract's check of them
shares = [{ folder = "../../geometry/3f2a…", file = "geometry.xao" }] # made by another calculation folder
```

a batch's or a sequence's request, in its launch folder, holds `members` or
`sequence` — paths from its folder — and its job's resources (§ 1.2):

```toml
name = "mesh-check-001"
sequence = ["../geometries-check-001", "../meshes-check-001"]
[resources]
…
```

The schema model is the authority for every field (`docs/reference/`), and
each `[resources]` field declares its roles on itself (`roles`) — shared by a
job and every member inside it (`partition`, `qos`, `wall`, `memory`); read
only where a scheduler is (`partition`, `qos`, `memory`); the queue
(`partition`, `qos`) — which the fit, a member's statement and a stage's
folder writing read (`Resources.holding`, `Resources.shared`), never a list of
names written again. The
request holds only what this calculation asks for; nothing about a machine.

- **Every resource is stated**, none defaulted ([`framework.md`](framework.md)
  § 4): `ranks`, `threads` and `gpus` always; `wall`, `memory` and the queue on
  a machine with a scheduler. On a machine without one, the queue and memory
  are not read, and preparation says so, so one request serves a cluster and
  the workstation; a stated wall is the run's own, which it is told (§ 4,
  block 10).
- **One node.** A job runs on one node. `memory` and `gpus` are stated per
  node, as the record measures nodes and the scheduler grants them, so a job
  across several nodes would add a node count without changing what either
  means.
- **A GPU ask is a count**; no field names a card.
- **One spelling each.** `wall` is `[D-]HH:MM:SS`, at least three parts:
  `04:30` is refused, because a scheduler reads it as four minutes thirty.
  `memory` is a positive whole number with its unit (`K`, `M`, `G`, `T`, `P`): a
  bare number is megabytes to SLURM, and `--mem=0` means the whole node.
- `partition` and `qos` together name one of the target's queues
  (§ 9.1); which queue to spend the wall time in is
  the person's judgement.
- **`{share:FILE}` names a shared file** in a `command` or `check`: the
  placeholder of the core's one grammar ([`core.md`](core.md) § 2.1), written
  at launch as the file's path from the run's folder (§ 5).
- **`{python}` is the environment's own**, the one block 9 verifies (§ 4):
  the placeholder of the core's one grammar ([`core.md`](core.md) § 2.1), its
  name declared once in `femkit/definitions/stages.py`, the lowest layer that
  reads it, and read by the request (being built, plan § 4, X), so a
  command never finds a `python` on `PATH` — the earlier tool runs everything
  on its environment's `python` by its path, since a site's `python` can stay
  first on `PATH` after an activation.
- **What the person brings is copied; what the workflow made is shared**
  (the person, 2026-11-25). An input is a file of the calculation folder,
  copied into each run — the person's earlier rule, every file a real copy,
  since a link dangles once a folder is synced elsewhere and an engine may
  write into a file it continues from; so is a file an engine continues from.
  A file another calculation folder made — a geometry, a mesh — is shared: the
  request names that folder and the file, and the run reads it where it was
  made, in that folder's newest run, which must be finished, by its path from
  the run's own folder, which `job launch` writes into the run's copy of
  `run.sh`. Never placed in the run, a shared file takes no name there: a
  run's inputs, programs and outputs each have their own name, and the shares
  theirs, so a stage can share a file and write one of the same name — the
  pass-through mesher shares the script's `mesh.msh` and writes its own
  ([`workflow.md`](workflow.md) § 2.3). It lies beside it in the same project's run folders, so the path
  holds wherever the project moves; `job launch` checks its SHA-256 against
  that run's `outputs.json` first, and it was made read-only when its run
  finished, so a run can never read one that changed.
- **A check is the contract's verdict.** `check` is a command run after
  `command`, in the same environment and run, given the inputs and what the
  command left; it writes its verdict, `checked.json` — passed, or failed with
  its reason — and, when passed, each output's SHA-256 into `outputs.json`,
  exactly the outputs the request lists, and makes them read-only, in the
  shapes `femkit/engines/stages/documents.py` declares: a check that only
  exits 0 leaves its run `failed` (§ 5.2). femkit's own checks write them
  through that module.
  How the command ended and what its contract found are two facts, in two
  files: a geometry script that exits 0 having made no geometry reads
  `failed`, and says that the script ran and its result did not hold.
- **A prepared case's request** (not built yet, plan § 4, M6) lists each input
  with its SHA-256 and whether it was generated or customized
  (`{ path = "case.sif", sha256 = "…", origin = "customized" }`), the steps
  to run before and after the command (`steps.before`, `steps.after`), and the
  environment's install fingerprint and lock hash it was prepared for
  (`prepared_for`). `job prepare` refuses an input whose hash differs, naming
  `study prep`; a target whose record lists the environment with another
  fingerprint is a warning (§ 3, step 4), and the run script stops before the
  command when the prefix is not the one prepared for (§ 4).

## 3. Prepare

`job prepare DIR [--target NAME]` runs these steps. A refusal — a missing
statement, one that contradicts the record ([`framework.md`](framework.md) § 4),
or an input whose hash differs from its request — writes nothing; everything
the record says about the request is shown as a warning, and the job is
prepared as asked. Nothing here probes a machine. A batch or a sequence is
prepared whole, every part for its target, so no part runs a script made for
another machine.

**A prepare planned in memory.** The same steps run on a request a maker
holds and a folder it has not written yet — the request, its files and the
target's record given, not read from disk — so a maker that writes many
folders, `study prep` ([`workflow.md`](workflow.md) § 7), plans every
prepare before it writes any: every refusal below comes first, and the
folder and its prepared files are then written together
(`jobs.prepare.planned`).

1. **Request** — load `job.toml`; for a prepared case (§ 2), refuse an input whose
   SHA-256 differs from the request's, naming `study prep`.
2. **Target** — **the calculation's own copy of its target's record**,
   `machine.toml`, is the record every later prepare and launch reads, so what
   a calculation was prepared for never changes under it (the person's
   earlier rule: taken at the first prepare and never changed, whatever was
   probed since). The first prepare takes it: from the record `--target`
   names, or `local` when no record of another machine is present in
   `<config>/machines/` — when one is, the first prepare is refused and lists
   every record with the `--target` line for each: being asked costs one flag,
   preparing for the wrong machine costs a queue wait. A later prepare reads
   the copy, and needs no `--target`; one naming another record is refused,
   since a second target is a second calculation (the earlier tool's rule,
   whatever machine that record is of). A target with no record,
   `local` included, is refused, naming `job probe --write`; a record, or a
   copy, that does not load is refused with its reason, never replaced by the
   next source. A record of this machine that is `stale` (§ 9.3) is refused at
   the first prepare, the one that takes it; a later prepare reads the copy
   and asks nothing more of the record.
3. **Statements** — refused, naming what to state: a resource § 2 requires
   that is stated nowhere or is mis-spelled; with a scheduler, a record that
   lists no queues (naming the probe that renews it), no queue named, or a
   (partition, QOS) pair that is not one of the record's `queues` — the refusal
   lists them with the request's fit on each; a record whose
   `activation.preamble` or `activation.command` is unset; `ranks > 1` with
   no `launch.mpi` in the record's `settings`; `one_process` with `ranks`
   other than 1; a member or part whose queue, wall or memory is not its launch
   folder's, or whose counts do not fit inside them (§ 1.2).
4. **Environment** — the request's environment, and with `gpus > 0` its CUDA
   environment, `<name>-cuda` ([`definitions.md`](definitions.md) § 4.5).
   Shown, from the record's `environments`, which is `env
   list` on the target as of the record's `measured` time
   (§ 9.1): the environment not installed there, in a
   state other than `ready`, or — with `gpus > 0` — not GPU-qualified
   (`passed`, [`envs.md`](envs.md) § 5), or, for a prepared case, listed with
   an install fingerprint other than the request's `prepared_for`, is a
   warning naming what settles it on the target — the listed state's own next
   steps from the environment table ([`envs.md`](envs.md) § 3.3), `env
   validate NAME --gpu` on a GPU node, `study prep` again. When
   the record could not list environments, nothing is said. The run script
   stops, saying so, if the environment is not there (§ 4). Whether an environment
   was built for another platform than a partition's nodes is shown with the
   scheduler's targets (plan § 4, M4).
5. **Fit** — shown: how the request sits on the record, as one node must hold
   all of it. With a scheduler, node group by node group of the named
   partition: how many nodes hold the whole request — `ranks × threads` cores,
   the memory, and the GPUs counted whatever their type — of how many, as a
   share never rounded to none or all; every limit of the queue it is over,
   with its numbers; and, when no node holds it, which node groups lack what,
   each lack once. Without a scheduler: the `host`. A limit the record does
   not state, or states as `unlimited` or `unknown`, is not counted. A misfit
   is a warning; the request is never changed, and the scheduler's answer at
   submission is shown.
6. **Render** — `run.sh` (§ 4) and, for a scheduler, `submit.sh` from its
   kind's header (§ 7), using the request, the record's facts and its
   `settings` (§ 9); a batch's and a sequence's header too, from the
   resources its request states (§ 1.2). A batch's and a sequence's walk is written by
   the launch that sends it (§ 5).
7. **Commit** — take the record copy on a first prepare; copy into the folder
   the programs the request names and the monitor; write the scripts; then
   write `prepared.json`, last: the target's name; `request`, the SHA-256 of
   `job.toml` as prepared, so a launch refuses a request changed since
   (`prepared-stale`, § 5); the environment and its install fingerprint, none
   for a batch or a sequence; the resolved resources; the SHA-256 of each script, each program
   and `machine.toml`, so a launch refuses any of them changed since; and, for
   a member of a batch or a part of a sequence, the launch folder it is
   prepared with.

Preparing again regenerates the scripts. Earlier runs keep the copies they ran.

| refusal | kind · code | subject |
|---|---|---|
| no record chosen while another machine's is present | `Unstated` · `target-unchosen` | `--target`; next: one `job prepare … --target NAME` per record |
| `--target` names no record there is | `UsageError` · `no-record` | `--target`; next: `job machines`, `job probe --write` |
| the target `local` has no record | `Unstated` · `no-record` | `local`; next: `job probe --write` |
| a record or the copy does not load | `DefinitionError` · its own | the file |
| a record that is `stale` (§ 9.3), at the first prepare | `Refused` · `stale` | the record; next: what its state allows |
| `--target` names another record than the copy's | `Refused` · `target-other` | `--target`; next: `job prepare` without it |
| a statement missing or mis-spelled | `Unstated` · `resource-unstated`, or `UsageError` | the key |
| no queue, or a queue the record does not list | `Unstated` · `queue-unstated`, `Refused` · `queue-unknown` | `partition`, `qos` |
| the record's activation, or `launch.mpi` with `ranks > 1`, unset | `Unstated` · `setting-unstated` | the setting; next: `config init`, which asks for the activation; `config set launch.mpi`, which no workstation's `config init` proposes |
| the record names a manager femkit has no kind file for, or an activation command that cannot enter an environment | `Unstated` · `manager-unknown`, `UsageError` · `activation-unusable` | the record |
| `one_process` with `ranks` other than 1 | `Refused` · `one-process` | `resources.ranks` |
| a member or part whose queue, wall or memory is not its launch folder's, or whose counts do not fit inside them | `Refused` · `member-differs` | the member, each value |
| an input whose hash differs | `Refused` · `input-changed` | the input; next: `study prep` — with a prepared case (plan § 4, M6) |
| a state that allows no prepare — held by a job still going, its newest run queued or running, a launch folder launched (§ 5.5) | `Refused` · `not-allowed` | the folder; next: what its state allows |
| no request, an environment, a program or a scheduler kind that does not exist, a member that is itself a launch folder, a part that is itself a sequence | `UsageError` · `no-request`, `no-such-environment`, `no-such-program`, `no-such-kind`, `member-is-launch`, `part-is-sequence` | the folder or the key |
| a lock held | `Busy` | the folder's lock (§ 5) |

## 4. The run script

Self-contained: it takes no count as an argument — the request is the one
source of the counts, written into it at prepare — and reads only what the
scheduler granted, its own run
directory, which `job launch` has already filled (§ 5), and the files its
request shares, by the paths written into it. It creates no directory, copies
no file and changes directory nowhere: anything that computes, decides or
arranges files is femkit's Python, on the host, before the script starts.
Before it enters its environment it starts clean, as every process femkit
starts for an environment does ([`envs.md`](envs.md) § 4.4): of the variables
of the shell it is started in — the scheduler's, or the one `job launch`
starts it from — it keeps only those the declared start passes, with the job
variables its scheduler kind declares, and none it removes; `PATH` is the
system's; the shell's functions — a batch job's `module` among them — stay.
Then the target's preamble runs as the record states it, and the activation
enters the environment, as the target's record says; after the activation
nothing is filtered. Its blocks, in order, form a closed list; adding one is a change
to this contract:

| # | block |
|---|---|
| 1 | strict mode (`set -euo pipefail`); its one argument is its run directory, and it stops unless it runs there — checked, never changed to. `-h` prints its usage; `--dry-run` prints what it would run — the command, each count and its source, the environment — and exits 0, writing nothing; any other argument is refused, exit 1 |
| 2 | **one start per run**: refused when the directory already holds `started.json` |
| 3 | **the launch-door gate**: refused, exit 2, writing nothing, unless `FEMKIT_LAUNCHED_BY` holds `job launch`'s claim, `femkit job launch` — set in the started process's environment here, on the submission line with a scheduler. Only `job launch` starts a run: a run's records are its launch's, and a start made without them is one no reader can place (the person's earlier rule) |
| 4 | write `started.json` (§ 5.1), its first write: the time, the host, and from the kind's job variables the scheduler job ID, ranks, cores per rank, cores on the node, GPUs and nodes granted. Set `FEMKIT_JOB_STARTED`, the job's start in epoch seconds, to now unless the job's header or walk has set it |
| 5 | **the run's log**: its standard output and error teed into `run.log`, so a scheduler's output file holds them too; a `PIPE` from the tee is handled — its line appended to `run.log` directly, and `PIPE` ignored from then on — and the lines a stop writes are appended to `run.log` directly, since a stop that kills the tee would otherwise kill the script by a broken pipe (measured with the earlier tool). Handled, not ignored from the start: an ignored signal is inherited by every child, the command included, where a handled one is reset to its default (the earlier tool's rule) |
| 6 | traps. One EXIT trap, run however the script ends: when the script stopped on its own before writing `ended.json` — a block that failed under `set -e`, or stopped with a reason — it writes it, with that status and its reason, *stopped before its end*; then it stops the monitor — waiting, within the same 10 seconds, for the monitor to have opened its log, so a run that ends at once still leaves a closing record — and waits up to 10 seconds for its closing lines. One handler for every signal that stops a run — HUP, INT, QUIT, ALRM, TERM, XCPU, XFSZ, VTALRM, PROF: it logs the signal and exits 128 + its number **without** `ended.json`; a forced stop is told by the scheduler, by the job found gone, or by the monitor's closing record (§ 5.2), never by a record the script writes. USR1 and USR2 are logged and the run goes on |
| 7 | with `gpus > 0`: the GPU model the driver reports, added to `started.json` (no count); and with no device visible — the scheduler's GPU grant, else `CUDA_VISIBLE_DEVICES`, else the driver's own list — stop with that reason |
| 8 | start clean: every exported variable the declared start does not pass, or removes, is unset, every exported shell function the target's scheduler kind does not declare is no longer exported — the shell keeps it, a preamble's `module` may call it — and `PATH` is the system's own ([`envs.md`](envs.md) § 4.4) — the lines `envs/start.py` writes from `process.toml` and the target's scheduler kind's `passes` and `functions`. Then enter the environment, with unset variables allowed (`set +u`; `-e` stays on), since a site's or a package's activation scripts read variables that may be unset: the target's `activation.preamble`, from the record's `settings`, verbatim — every absolute path a bare `source X` or `. X` line of it names checked readable first, and a missing one stops the run naming it, so a preamble written for another machine fails here, not halfway; a relative path, or one built from a variable, is left as written — then the target's activation of the environment by its name with the manager, `femkit-<name>` ([`config.md`](config.md) § 3.1; [`envs.md`](envs.md) § 1): for the shell function, `conda activate`, the manager's own hook evaluated first, as the manager the record names prints it (`eval "$(<manager> shell.bash hook)"`), that manager checked there first, a missing one stopping the run naming it; for the activate script, `source activate`, its script found on `PATH` once the preamble ran, or the run stops saying that nothing put it there after the clean start; a failed activation stopping the run, naming the environment; then `set -u` again |
| 9 | verify the environment entered: the variable the manager kind's activation sets (`activate.active`, [`definitions.md`](definitions.md) § 6) — `CONDA_PREFIX` — names an environment of the name entered, its last step that name; the environment's own `python`, `$CONDA_PREFIX/bin/python`, is there, and is `{python}` from here on (§ 2); the command's program — and with `ranks > 1` the launcher, `launch.mpi`'s first word — resolves inside the prefix. For a prepared case, also that the prefix's install fingerprint and lock hash are the request's `prepared_for`. Stop with the reason otherwise |
| 10 | export each of the environment's `thread_variables` set to `threads`, and its `fixed_variables` set to their values ([`definitions.md`](definitions.md) § 4.4): an engine's own settings are its environment's, which its activation and its definition give. Export the wall the job states in seconds, `FEMKIT_WALL_S` — a sent job's, or a run here's own `wall` when its request states one — counted from `FEMKIT_JOB_STARTED`, as the earlier tool tells a run its wall; a member or a part is told its job's. Whether an engine can stop on it is not measured |
| 11 | **start the monitor** (§ 4.3) on `{python}`, at `nice 19`, in the background, watching the run script's own PID, given the cores the run uses — `ranks × threads` — its start and any error loading it written to `run.log` |
| 12 | run the command as a child — through `launch.mpi` when `ranks > 1` — its output to the run's log, its exit status kept. Under a scheduler no binding or mapping options are added: the scheduler has placed the job. For a prepared case, the steps its request lists run before and after the command, each with its own log ([`models.md`](models.md) § 8.3; not built yet, plan § 4, M8) |
| 13 | when the command exited 0 and the request states a `check`: the check, on `{python}`, its output to `check.log`. The check writes `checked.json` and, when passed, `outputs.json`, and makes the outputs read-only (§ 2), in the shapes the stage programs' documents declare (`femkit/engines/stages/documents.py`); the script records nothing of it, and keeps its exit status — 0 when it held — for block 14 |
| 14 | write `ended.json`, the command's exit status, as its last act; exit with that status, or with 1 when it was 0 and the check did not pass, so whoever started the script reads from its exit whether the run finished |

The exit status alone never says a run did what was asked: measured
2026-11-25, ElmerSolver 26.2 exits 0 when a solver module it names fails to
load, its log ending with the loader's errors. A run's `check`, and for a
solve the reader of its log and status ([`models.md`](models.md) § 9.1;
plan § 4, M6), is what makes `finished` mean finished.

### 4.1 A batch's walk

Written by the launch that sends the batch, into its launch folder,
`run.sh`: blocks 1, 3, 5 and 6 as above, its log the launch folder's `log`,
and `FEMKIT_JOB_STARTED` set once for every member; then each member's own
run script, started in the member's run the launch opened, one after another,
each member's output to that run's log; a member that fails leaves the rest
to run. A stop signal stops the member that runs — its whole process group —
and no later member starts. The walk exits 0 once every member has ended,
however each ended — each member's run says how — and 128 + the signal's
number when stopped. It enters no environment and starts no monitor: each
member enters its own and starts its own.

### 4.2 A sequence's walk

Written by the launch that sends the sequence, into its launch folder,
`run.sh`: blocks 1, 3, 5 and 6 as above, and `FEMKIT_JOB_STARTED` set once;
then it enters femkit's control environment as block 8 enters any — a clean
start, the target's preamble, then its activation of the control
environment by its name, `femkit` — and verifies it as block 9 does, its `python` the control
environment's own, as the earlier tool's walk enters its own environment
before its first batch; then, for each part in order, femkit's own `job
launch` of that part, run by the `femkit` command of the prefix it entered
([`envs.md`](envs.md) § 7) from the checkout it names, which the job's node
must see — a cluster's shared home — with `--foreground --yes --in-sequence
<the launch folder> --in-job <the job>`: the job's ID as the walk's shell
knows it — the scheduler's, or `<host>-<pid>` run here, `$HOSTNAME-$$` — as
the earlier tool's walk names it, so each part's runs join the job's entry.
The sequence's launch record is written before the job goes, since its parts
read it (§ 5).

- **A part's launch inside it** runs here, on the job's node, whatever the
  target's scheduler — `--in-job` says it is inside its job already — and is
  planned, shown, sent and recorded as any launch, and asks nothing;
  `--in-sequence` and `--in-job`, which the walk alone types, are refused with
  any launch but a waited-on one. It runs its runs in the foreground, in its
  own process group — the walk's — so a stop signal to the walk's process group
  reaches the part that runs. It exits 0 once its runs have ended and all
  finished, 1 when one did not — or femkit itself failed, its traceback in
  the walk's log — and 2 when refused; a member left out (§ 1.2) is no
  refusal.
- **The walk stops on a refused part or a stop signal**, never on a part
  whose runs failed: the person's rule for a study's independent cases (§
  1.2), where the earlier tool's walk stops on any step that does not exit 0.
  Its log holds every part's launch as it printed it.
- **Each run a part sends records the job it rides**, from `--in-job`: run
  here, the walk's process, the ID's host this machine's and its process
  there — else the part is refused, naming the flag; with a scheduler, that
  job's ID, the line that sent it and where its scheduler writes the job's
  error file. So every reader reads a part's run as a run of that job, and a
  job cancelled or killed reads its runs `failed`, as any job's do. The part
  adds the runs it started to its entry of the sequence's launch record, under
  the sequence folder's own hold, taken for that write alone.

### 4.3 The monitor

The earlier tool's monitor, copied: one standard-library program,
`femkit/engines/stages/monitor.py`, copied into the calculation folder with the
others and started beside every run (block 11); it observes, and never
decides. It wakes every 10 seconds; it reads what the run's log gained, and
samples what the run uses against what the job **holds**, never the node — its
CPU time against the cores the job holds, its memory against the limit where
the scheduler's grant has one: inside a scheduler's job, the job's own control
group; a run here, the run script's process tree and the cores the run uses.
It writes `monitor.log`, one line per record, and `util.csv`, a row when a
reading moved by a tenth of its last or 300 seconds passed:

| tag | when | says |
|---|---|---|
| `[MACHINE]` | first | the node, its cores, memory and GPUs |
| `[MONITOR] start` | at start | the interval, the watched PID, the first reading |
| `[STATUS]` | when the run's log grew, and once at the end | what it read; with `FEMKIT_WALL_S`, the time left before the wall |
| `[WALL]` | once, when the wall cannot be counted | why |
| `[MONITOR] job ended` | the first closing line | why it stopped: `stopped by SIGTERM`, `watched pid N gone` — the closing record the state rules read (§ 5.2) |
| `[STATUS]` | after it | the run's records as they stand — `ended.json`'s status and reason, `checked.json`'s verdict, or neither — never a state of its own: the run's state is the run door's (§ 5.2), which the earlier tool's monitor asks; femkit's runs on the environment's own `python`, with the standard library and femkit's stage programs' modules alone, which hold no run door |
| `[UTIL-SUMMARY]`, `[UTIL-BASIS]` | at the end | the CPU use's mean and range; what every percentage is a fraction of |

It stops on `SIGTERM` from the run script's exit trap, or when the watched PID
is gone. Reading a run's progress in an engine's own words, and warning when
the wall is near by the steps it has taken, join with that engine's readers
(plan § 4, M6); telling channels outside the run — the earlier tool's
notifications — is not scheduled.

## 5. Runs

`job launch DIR` opens the next run (§ 1) — or fills again, emptied whole
first, a run a refused or interrupted launch opened and never started
(`pending`, § 5.2) — and copies into it, from the calculation folder,
`job.toml`, the inputs, `run.sh`, the programs `job prepare` copied there and,
with a scheduler, `submit.sh`; it finds each file the request shares in the
newest run of its folder, which must be finished, checks its SHA-256 against
that run's `outputs.json`, and writes its path, from the run's folder, into
the run's copy of `run.sh`. For a batch it opens a run for each member and
writes the walk; for a sequence it writes the walk alone, each part's runs
opened by the part's own launch when its turn comes. A batch's or a
sequence's launch record (§ 5.1) is written before the job goes, since the
job reads it, as the earlier tool writes it; a sequence's launch then ends
its hold on every folder, since each part's launch takes its own. Then it
starts the job,
with `FEMKIT_LAUNCHED_BY` set, in the environment it runs in, which holds
none of femkit's own variables ([`envs.md`](envs.md) § 7):

- **here, in the background** — the default: in a new process session, so
  closing the terminal does not end it; the launch returns once the process
  exists, saying *started in the background*, its folder and its log, and the
  line that stops it, `job cancel <id>`;
- **here, waited on** — `--foreground`: in the launch's own process group, so
  Ctrl-C reaches it; the launch reads each run's state when the process ends,
  says it, removes its address, and exits 0 when every run finished, 1 when
  any did not or its state could not be read (the earlier tool's rule, so a
  script that trusts the exit status is told what happened). Stopped at its
  terminal, it waits up to twice the run script's 10 seconds for the run to
  close, reads each run once and says how it ended; a run not ended by then
  keeps the address for `job list`;
- **with a scheduler**, by one submission made from inside the run folder, so
  the header's relative output names land in it (not built yet, plan § 4,
  M4); `--foreground` is refused there, but inside a job (§ 4.2).

Then it writes `launched.json` — the job, known once its start succeeded —
into each run it started and, for a batch or a sequence, into its launch
folder; and the job's address (§ 5.4). The launch's next step is `job status`
of the folder and, for a job in the background, the line that stops it.

| refusal | kind · code | subject |
|---|---|---|
| a state that does not allow `launch` (§ 5.5) — not prepared; a file `prepared.json` records changed since (`stale`); held by a job still going, but the sequence launching it; a launch folder launched before; its newest run `queued`, `running` or `unreadable` | `Refused` · `not-allowed` | the folder; next: what its state allows (§ 5.5) — for a launch folder launched, the action its `maker.json` names too |
| a member or part prepared for another target, or apart from it | `Refused` · `prepared-apart` | the member |
| the target has a scheduler, outside a job (plan § 4, M4) | `Refused` · `not-built` | the target |
| this machine's identity is not the target's | `Refused` · `not-this-machine` | the target |
| no request, or a scheduler kind that does not exist | `UsageError` · `no-request`, `no-such-kind` | the folder or the kind |
| an input the request lists is not in the folder | `UsageError` · `no-such-input` | the input |
| a folder it shares from has no finished newest run | `Refused` · `shares-unfinished` | the folder |
| a file it shares has no SHA-256 in that run's `outputs.json`, or another | `Refused` · `shares-changed` | the file |
| `--in-sequence` or `--in-job` without `--foreground`, or one without the other; `--foreground` with a scheduler, outside a job | `UsageError` · `in-sequence-alone`, `foreground-scheduler` | the flag |
| `--in-job` naming no process of this host that is still there | `UsageError` | `--in-job` |
| a lock held | `Busy` | the folder's lock |

Inside a sequence, a member a job still going has, one whose newest run
finished, and one whose shared input did not finish are left out rather than
refusing the part (§ 1.2).

- **Locks.** `job prepare` and `job launch` take the calculation folder's own
  lock, `job-<the first 16 hexadecimal digits of the SHA-256 of its resolved
  path>` ([`core.md`](core.md) § 5) — a batch's or a sequence's, every
  member's or part's too — whether or not the folder lies in a project: only
  the jobs domain writes inside a calculation folder. A launch holds them
  while it opens and starts runs and writes their records, and ends its hold
  before it waits on one ([`api.md`](api.md) § 3) — a sequence's before its
  job goes (above); a part inside it takes the sequence folder's hold for
  the one write it makes there (§ 4.2). `job cancel` takes none,
  as the earlier tool's stop takes none: `cancel.json` has one writer and is
  written whole. The run door takes the calculation folder's lock for the one write it
  makes (§ 5.1).
- A submission the scheduler refuses leaves the run it opened `pending`, and
  shows the scheduler's answer.
- A submission that succeeds without a job ID femkit can read writes
  `launched.json` with no ID and the scheduler's answer, and no address; that
  run reads by its files alone, and `job status` shows the answer so the
  person can find the job.

### 5.1 Facts

Each record is one JSON file, written whole, each by one writer, as the
catalogue declares it (§ 1): in a run, the run script writes `started.json`
and `ended.json`; the check, `checked.json` and `outputs.json`; the monitor,
`monitor.log`; `job launch`, `launched.json`; `job cancel`, `cancel.json`;
and the first reader that finds the job over, `gone.json` — the earlier tool
writes that answer into its launch record, femkit beside it, so no record is
ever written twice. In a launch folder, `job launch` writes the launch
record, `launch.json`, before the job goes, and `launched.json` once it went;
each part of a sequence adds its runs to the launch record.

| fact | from |
|---|---|
| started | `started.json`: `time`, `host`, each job role of § 7's `job_variables` the kind declares and the job's variables hold, and `gpu_model` with `gpus > 0` where the driver names one |
| launched | `launched.json` in a run, and in a launch folder, written once the start succeeded: `time`; `identity`, the host it was launched from — its name, which the run door compares, never a record's identity; the job — a run here: its host, process ID, start time and the kernel's boot ID, the walk's for a member or a part, a part's from its `--in-job` (§ 4.2); with a scheduler (M4): the job ID, the line that sent it, where the job's error file is, and the queue, wall and memory it was sent with |
| launch record | `launch.json` in a batch's or a sequence's launch folder, written before the job goes: when, the host it was launched from, its members or parts in order; for each part launched, its runs, which that part's launch adds |
| ended | `ended.json`: `status`, the command's exit status, or the script's own when it stopped before its end; `time`; `reason`, null when there is none |
| checked | `checked.json`, written by the check: `passed`, and `reason` — null when passed — at the stage programs' documents' schema (`documents.py`, `checked`) |
| outputs | `outputs.json`, written by the check once it passed: `files`, each output the request lists with its SHA-256 (`documents.py`, `outputs`); none without a check, so a request with outputs and no check is shared from by none |
| the monitor's closing record | `[MONITOR] job ended` in `monitor.log` (§ 4.3): the run's process went, and the monitor saw it |
| the job's word | **asked once, written once** (the person's earlier rule): every reader of a run that reads it live — `job status`, `job list`, a launch, and every reader above the jobs domain that reads a run's state ([`workflow.md`](workflow.md) § 6) — reads it through the one run door, `jobs/runs.py`, which asks, on the machine the job was launched from, whether it is still going: a run here by its process (host, process ID, start time, boot ID); a queue job by the scheduler's query, at most once per ten seconds per job. A job found over with no `ended.json` is written into each of its runs, `gone.json` — when, where it asked, what it found — under its calculation folder's lock, taken for that write alone, by that very look, so the run reads `failed` from then on, wherever the folder is copied; a lock held, or a disk that refuses the write, is said on the run's line, never a crash. A run launched from another machine is not asked, and reads as its files say. With a scheduler, its own final line in the job's error file (`*** JOB … CANCELLED … DUE TO TIME LIMIT ***`), read by the kind's reader, is the job's word too |
| cancel requested | `cancel.json`, `time`: written by `job cancel` once its signal was sent or the scheduler accepted the cancel; the words a stopped run's state carries |

### 5.2 Observation — the first rule that matches

The earlier tool's order of evidence, declared as data,
`femkit/data/states/run.toml` ([`core.md`](core.md) § 7):

| # | when | state |
|---|---|---|
| 1 | `launched.json` is there and does not read | `unreadable`, naming the file |
| 2 | `ended.json` with status 0, and `checked.json` passed with `outputs.json` recording exactly the outputs the run's own `job.toml` lists, or no check in it | `finished` |
| 3 | `ended.json` with another status, or not reading; `checked.json` failed, or not reading; `outputs.json` missing, not reading, or recording other outputs than the request lists; or `ended.json` with status 0, a check stated and no `checked.json` — the check stopped before its verdict | `failed`, in words |
| 4 | the job's word says it is over — `gone.json`, read or not, or the scheduler's line | `failed`: *stopped before its end*, with that word — *never started* when the run holds no `started.json`, *cancelled* where `cancel.json` is there |
| 5 | the monitor's closing record | `failed`: *stopped before its end: no exit recorded* — *cancelled* where `cancel.json` is there |
| 6 | started, sent with a wall, and its newest own write — its log, the monitor's log, its outputs, never a record femkit writes of it — older than that wall | `failed`: *nothing was written for longer than its time limit* |
| 7 | `started.json`, read or not | `running` — with how long since the run last wrote; read from another machine, with *ask on* that machine |
| 8 | launched, not started | `queued` |
| 9 | otherwise — opened, never launched | `pending` |

A run's start comes before its launch record: a launch cut short after the run
started leaves no `launched.json`, and that run reads `running`, never
`pending`, so no launch empties it. Silence is not death: a run whose log has
not grown is `running` until a rule above says otherwise. A member its walk
never reached reads `queued` while the job goes, and *failed — never started*
once the job's word says it is over.

### 5.3 A run's actions

Declared in the same file, `run.toml`, the one home of a run's states and
what each allows; a calculation folder past its own states is its newest
run's (§ 5.5). Each names the run's calculation folder.

| state | allows |
|---|---|
| `pending` | `launch`, filling it again; `prepare` |
| `queued`, `running` | `status` |
| `finished` | `launch`, a new run as asked; `prepare`; `status` |
| `failed` | `launch`, a new run as asked; `prepare`; `status` |
| `unreadable` | `status`, naming the file |

What a sequence's walk does with a folder in each state — a finished
folder's outputs taken, a folder another job has left to it (§ 1.2) — is
the jobs domain's own `[tasks]`, by state, never an action (core.md § 7;
plan § 4, X, "Jobs, parked").

The person's `job launch` runs a folder again as asked, however its last run
ended, as the earlier tool's launch does. Cancelling is a job's, not a run's
(§ 5.4).

### 5.4 The jobs launched from this machine — `job list`, `job cancel`

Every launch leaves an **address**, the way a server leaves its pidfile
([`web.md`](web.md) § 4): one file per job in femkit's state directory,
`<state>/jobs/` ([`config.md`](config.md) § 2), written the moment the job
goes — a run here once its process exists, a queue job once the scheduler
gives its ID. It holds an address, never a state: its `id` — `<host>-<pid>`
for a job here, the scheduler's ID with its cluster for a queue job; how it
went, here in the background or waited on, or to a queue; the host; the
process ID and its start time, or the job ID and cluster; the calculation or
launch folder; each run it started, by its path; for a sequence, each part in
order; and when it went. A part's launch inside a sequence writes no address
of its own, and adds nothing to the sequence's: its runs are in the
sequence's launch record (§ 5.1), where `job list` reads them.

- **`job list`** shows every address: its ID, how and when it went, its
  folder, and each run with its state, read through the run door (§ 5.1) —
  which writes the job's word for a job found over — each with its `job
  status` line; for a sequence, each part not reached yet, *not launched
  yet*; and, while a job left in the background goes, its `job cancel` line —
  a job waited on is stopped at its terminal, and says so. A job that has ended is
  shown once, with how each run ended, and its address is removed — the one
  other write a read makes ([`api.md`](api.md) § 2). A job launched on another
  host is said so, *on HOST: ask there*, and never removed or signalled here;
  an address that does not read is said, with its path, and kept.
- **`job cancel ID`** — the line a launch prints beside a job it left in the
  background — shows what it will stop and asks; `--yes` answers in advance.
  A job here is checked to be the process launched (host, process ID, start
  time), and `SIGTERM` goes once to its process group, through the core's one
  signal for a run launched earlier ([`core.md`](core.md) § 8): the run
  script's handler logs it and `mpirun` stops its ranks; a walk's process group holds
  its members' and its part's runs. A queue job: its kind's cancel (plan § 4,
  M4). It writes `cancel.json` into each run the job holds that has not ended,
  and the run reads `failed`, *cancelled*, once the job's word or the
  monitor's closing record says it is over. A job waited on is stopped at its
  terminal, with Ctrl-C, and `job cancel` says so.

| refusal | kind · code | subject |
|---|---|---|
| no address with that ID | `UsageError` · `no-such-job` | the ID; next: `job list` |
| a job launched on another host | `Refused` · `other-host` | the host |
| a job waited on | `Refused` · `waited-on` | the ID: stop it at its terminal |
| the process is not the one launched | `Refused` · `not-the-job` | the ID; next: `job list` |
| its address does not read | `Refused` · `unreadable` | the file |

### 5.5 A calculation folder's state — `femkit/data/states/calculation.toml`

Declared as data ([`core.md`](core.md) § 7), over the folder's facts —
`prepared.json` and the SHA-256s it records, the addresses of the jobs still
going (§ 5.4), and its newest run's state (§ 5.2) — the first rule that
matches; `job prepare`, `job launch`, `job status` and every reader above the
jobs domain read it:

| # | when | state | allows — each its next step |
|---|---|---|---|
| 1 | a job still going holds it and has not started its run — a run it opened, a sequence part it has not reached, or a member of one | `held` — *goes in job <id>* | `job list`, `job cancel <id>` |
| 2 | no `prepared.json`, or one that does not read | `unprepared` | `job prepare` |
| 3 | a file `prepared.json` records differs from it | `stale` | `job prepare` |
| 4 | a launch folder whose `launch.json` is there | `launched` | `job status`; `job launch`, again, which continues it (§ 1.2) |
| 5 | a launch folder not launched yet, a member or part it names — at any level, a batch's member inside a sequence included — prepared apart since: its members changed, as the earlier tool's `ready.regrouped` | `regrouped` | the action its `maker.json` names (§ 1.2), which forms the job again — `calculation.toml`'s `again`, as `launched`'s; `job launch` refuses it `prepared-apart` |
| 6 | a member or part prepared with a launch folder that is there, whole — every member and part it names still prepared with it — and not launched yet, whatever runs it made before; one whose launch folder is not there or not whole — a prep cut short, a member taken out — is in no job, and placed again | `in_launch` — *goes in job <launch folder>* | `job launch` of the launch folder that holds it — for a batch inside a sequence, the sequence — never of the member alone: a group goes whole the first time, as in the earlier tool; and `job prepare`, which takes it out of that job, whose launch then refuses it `prepared-apart` |
| 7 | no run | `prepared` | `job launch`, `job prepare` |
| 8 | otherwise | `ran`: shown as its newest run's state | the run's (§ 5.3) |



A folder held comes first: while a job holds it, nothing but that job touches
it, whatever else is true of it. Past the folder's own states it is its
newest run's: `run.toml` is the one home of a run's states and actions, read
here, never declared twice. `job status DIR` shows the folder's state in its
words, each run's beside it — for a launch folder, each member's or part's —
the files each run left, and what its state allows.

A stage past its own states is drawn in its folder's state
([`workflow.md`](workflow.md) § 6), so each of these states, and each of a
run's, has its block word ([`web.md`](web.md) § 7.6), declared in
`calculation.toml`'s and `run.toml`'s `[shows]`: `held` and `queued`,
*waiting*; `unprepared`, `stale`, `regrouped`, `in_launch`, `prepared` and `pending`, *needs update*;
`launched` and `running`, *running*; `finished`, *up to date*; `failed`,
*failed*; `unreadable`, *needs attention*.

## 6. Rules

- **One job per launch.** A launch submits at most one job, on the person's
  command — a batch and a sequence included, each one job however many parts
  it runs. There is no batch submission, no automatic retry and no
  resubmission.
- A request is never adjusted to fit, and a misfit is never refused: it is
  shown at preparation, and the scheduler decides ([`framework.md`](framework.md) § 4).
- No test submits, queries or cancels a real scheduler job
  ([`testing.md`](testing.md) § 2).

## 7. Scheduler kinds — `femkit/data/schedulers/`

A kind file declares, for every machine with that scheduler, from closed lists
its schema model holds:

| part | declares |
|---|---|
| `commands` | the job commands by role — `submit`, `query`, `cancel`, `cluster` — by their usual names. A kind with commands is detected when its `submit` is found or declared; the others are located, and the probe records where each is (§ 9.2) |
| `probe` | the commands that measure a machine of this kind, by role: for `slurm`, `control` (`scontrol`: the cluster name, each partition's policy, and every node, from which the node groups are counted exactly) and `accounts` (`sacctmgr`: QOS limits and the account's associations). Its readers know what to ask of each |
| `header` | the directive prefix and one directive per value, from a closed list: `name`; `nodes`, fixed (`-N 1`, § 2); `ranks` (`-n`); `threads` (`-c`, cores per rank); `gpus` (`--gres=gpu:{gpus}`, per node); `memory` (`--mem`, per node); `wall`; `partition`; `qos`, left out when the queue has none; `stdout` and `stderr`, relative names with the job ID, so they land in the run folder |
| `submit` | the submit line, and the pattern of the job ID it answers |
| `check` | optional: the word that asks without submitting (`--test-only`), added to the same submit line; used by `job launch --check`. Its answer is read for a start time, and shown verbatim when none can be read |
| `query` | the line that asks one job's state and the scheduler's reason (`squeue --noheader --jobs={id} --format=%T\|%r`), and the closed list of **ended** state words; any other listed state is alive |
| `cancel` | its line |
| `interactive` | the command that opens an interactive allocation (`salloc`): `env bootstrap` names it in its plan when it runs outside any job on a machine of this kind, and an install names it after a step was killed ([`envs.md`](envs.md) § 6.2); never with a partition |
| `job_variables` | the scheduler's variable for each of femkit's job roles: job ID, ranks, cores per rank, cores on the node, GPUs, nodes |
| `passes` | the variables a job of this kind sees, as name patterns (`SLURM_*`), that a clean start passes ([`envs.md`](envs.md) § 4.4): a run script's block 8 keeps them, and a command femkit starts for an environment inside such a job does too |
| `functions` | the shell functions a job of this kind needs passed, by name — the module system's `module`, which a preamble's `module load` calls: a clean start passes these and no other, a run script's block 8 keeping them exported ([`envs.md`](envs.md) § 4.4) |
| `mpi_launch` | the launcher `config init` proposes for `launch.mpi`: the environment's own `mpirun -np {ranks}`. `srun` is not proposed: the environment's MPI and the cluster's process manager need not agree |

`local` declares no commands, header, submission or probe. Adding a scheduler is
one kind file and its readers: the readers of its answers live in
`femkit/schedulers/<kind>.py`, registered by ID and checked when the kind loads,
as engine readers are. The `slurm` readers are tested on the cluster's own
output in the field tier ([`testing.md`](testing.md) § 2.1); none is committed,
because it names the site's nodes and partitions.

## 8. Commands

| command | does |
|---|---|
| `job prepare DIR [--target NAME]` | § 3 |
| `job launch DIR [--foreground] [--check] [--in-sequence SEQ --in-job ID]` | § 5: in the background, or waited on; `--check` asks the scheduler without submitting; `--in-sequence` and `--in-job`, typed by a sequence's walk alone, launch a part inside its job (§ 4.2) |
| `job status DIR` | the folder's state and each run's, in their words, and the files each run left (§ 5.5); for a queued job the scheduler's state and reason |
| `job list` | every job launched from this machine, and its runs' states (§ 5.4) |
| `job cancel ID [--yes]` | stop one job `job list` shows (§ 5.4) |
| `job probe [--write] [--name NAME] [--set KEY=VALUE] [--scheduler KIND]` | measure this machine (§ 9.2) |
| `job machines [NAME]` | every record, or one with the source of each fact (§ 9.3) |

`doctor` and `env bootstrap` ([`envs.md`](envs.md) § 6.1, § 6.2) are declared
here too, in `femkit/jobs/setup.py`: `doctor` reads this machine's record, and
`env bootstrap` writes it with `job probe --write` after its installs.

## 9. Machine records — `<config>/machines/<name>.toml`

### 9.1 What a record holds

The record of one machine, as measured on it:

| part | holds |
|---|---|
| `schema` | the record's schema version, read before anything else |
| `measured` | when, and where the probe ran: a workstation, a cluster's login node, or inside a scheduler job |
| `identity` | the scheduler's cluster name (`ClusterName`), or the host name of a machine without one — how a command knows it is running on that machine |
| `host` | the machine the probe ran on: operating system, architecture, cores, memory, and GPUs (model, compute capability, memory) as the driver reports them |
| `manager` | kind, path, version, root, its platform (`linux-64`, `linux-aarch64`: what an environment built here is for), and `run_enters`: whether `<manager> run -n femkit` actually runs inside the prefix the manager lists for the control environment here, measured by running it once — `unknown`, with why, when that run fails or names no prefix |
| `scheduler` | kind (from `schedulers/`) and the path of each command its kind names |
| `partitions` | each partition's limits — `MaxTime`, `MaxCPUsPerNode`, `DefMemPerCPU` or `DefMemPerNode` (each kept as stated, never converted into the other), and the QOS it allows or denies — and its **node groups**: count, cores, memory, GPUs per node as `{type: count}`, architecture |
| `queues` | each (partition, QOS) pair **this account may submit to**, from the scheduler's association records, with its effective limits: the shorter of the partition's `MaxTime` and the QOS's `MaxWall`; the QOS's per-job cpu, memory and GPU caps (`MaxTRESPerJob`); and `MaxSubmitJobsPerUser`, shown and never counted, since femkit submits one job per launch. When the account's QOS list cannot be read, each partition is one queue with no QOS, and the record says so |
| `environments` | `env list` on this machine when the probe ran: each environment with its state, install fingerprint, solver version and GPU qualification; its platform is the record's `manager.platform`, since this machine's manager built it. An empty table means none is installed; one that could not be listed is `unknown` with the reason |
| `settings` | a copy of this machine's `config.toml` values a job run here needs — `launch.mpi`, `activation.preamble`, `activation.command` — each under its own key and with its own type, as `config.toml` writes it ([`config.md`](config.md) § 3.1) |

Rules the record follows:

- **The record is shown, never a veto** ([`framework.md`](framework.md) § 4).
  Preparation reads it to say how a request sits on the machine; a GPU card's
  type, like any model name, is shown and never compared — a GPU ask is a count.
- **A partition is a queue, not a machine type.** One partition can hold nodes
  with whole GPUs, nodes with GPU slices and nodes with no GPU. Its node groups are
  the measurement; femkit derives no single "node size" from them.
- **Compute nodes are measured through the scheduler**, never from the login
  node the probe runs on. `host` describes where the probe ran; on a cluster,
  preparation checks a job against `partitions` and `queues`, never `host`.
- **Nothing about a site is in femkit.** No partition, QOS, queue name or limit
  is named in code or shipped data; every one comes from the scheduler's
  answers, read by the commands and readers its kind declares
  (§ 7).
- **A limit has three answers**: a number; `unlimited`, when the scheduler was
  asked and states none (`UNLIMITED`, `infinite`, an empty `MaxWall`); or
  `unknown`, with the reason it could not be read. Neither of the last two is
  counted against a request or read as zero. Every other fact is a value or
  `unknown` with its reason. Each fact carries its **source**: the command that
  measured it, `declared`, or `config.toml` for `settings`.
- **How the scheduler is read.** Memory is kept in whole MiB as the scheduler
  reports it and converted only for display. Every node is read
  (`scontrol show node`), so node groups are exact — no `48+` range stands for
  a group — and nothing is cut to a column width. In a GPU entry the affinity tail is dropped and other
  generic resources are ignored; a count without a type is type `gpu`; a node
  that states none (`(null)`) has measured `{}`, never `unknown`. A GPU entry
  whose count does not read makes that node's GPUs `unknown`, and a node's
  cores or memory that is no number is `unknown`, each naming what the
  scheduler wrote — never a count guessed.
- **Which queues.** Associations are those of the user running the probe; one
  that names no partition holds on every partition; `no_submit` is not a QOS;
  a pair the partition denies (`AllowQos`, `DenyQos`) is not a queue. Each
  optional column is its own query, so one column a site's scheduler does not
  know cannot cost the others, and columns are read by name, never by position.
- **`environments` is a dated snapshot**: what `env list` answered at
  `measured`. It is shown, never taken for an environment's live state, which
  is observed on the machine itself ([`framework.md`](framework.md) § 3); one
  reader, `record.listed`, says whether the record lists an environment and
  as what, for a stage's identity and a prepare's warning alike. From a
  workstation it is the only view of a cluster's environments.
- **One schema version.** A record states its version; a record of another
  version does not load, and `job machines` names its version and the probe
  that rewrites it, run on that machine. Unknown keys do not load: only the
  probe writes records, never a person.
- The probe copies `settings` as they are; it does not choose them. They let a
  job be prepared on one machine for another. After a change to the machine's
  `config.toml` or its environments, the record is probed again.

### 9.2 Probing, declaring and writing

`job probe` measures the machine it runs on and prints the record — every
part of § 9.1, a queue's memory cap and `MaxSubmitJobsPerUser` and a
partition's policy among them — any facts it could not measure and why, and
the exact command that would write what was shown. It writes nothing without
`--write`, and names the log of its run either way.

| option | does |
|---|---|
| `--write` | write `machines/local.toml`, this machine's own record |
| `--write --name NAME` | write `machines/NAME.toml`, the record another machine prepares this one by; `local` is refused as a name by the request itself |
| `--set KEY=VALUE` (repeatable) | **declare** where a scheduler command is, when the probe cannot find it — a site's own submit wrapper, `--set scheduler.commands.submit=PATH`. Only command paths are declarable; nothing in `identity`, `partitions`, `queues`, `environments` or `settings` is, because a queue list typed on another machine is a guess. An unknown key or a mistyped value is refused by name; the declared value's source is `declared` |
| `--scheduler KIND` | name the scheduler kind instead of detecting it; its commands are still located |
| `--yes` | accept every difference from an existing record without asking |

- **Detection.** A kind with commands is detected when its `submit` command is
  found or declared — a declared one, `--set scheduler.commands.submit=PATH`,
  stands for every kind with commands, so `--scheduler` is needed only where
  two have them; when none is, the kind is `local`; when two are, the probe
  refuses and asks for `--scheduler`. Each other command the kind names is
  located; one that is not found makes the facts it measures `unknown`, naming
  the command. A kind with commands whose `submit` is not found refuses
  `--write`, naming `--set scheduler.commands.submit=PATH`.
- **Replacing a record.** Every difference from the existing record is shown —
  partitions and queues field by field, as one block — and then one question
  is asked. No, or no answer, writes nothing; `--yes` accepts. `settings` are
  copied, never asked about, and their change is shown: declining them would
  write a record that is stale at once. A file there that does not load is
  said, with its reason, and replaced only on consent.
- **Refusals.** `--write` is refused while this machine's
  `activation.preamble` or `activation.command` is unset ([`config.md`](config.md) § 3.1), naming
  `config init`, because every job prepared for the record needs both.
- **Run it where it will be used.** On a cluster, run it on a login node: the
  scheduler's commands describe the compute nodes from there.
- **Reading a record never probes.** Every command but `job probe` reads
  records only.

### 9.3 Carrying a record, and which one is read

To prepare jobs on a workstation for a cluster:

1. on the cluster: `femkit job probe --write --name cluster-a`;
2. copy `machines/cluster-a.toml` into the workstation's `<config>/machines/`;
3. on the workstation: `femkit job machines` shows it arrived and loads.

- `job machines` shows every record in `<config>/machines/`: name, path, when
  and where it was measured, and a one-line summary (scheduler, node groups,
  queue count). A record that does not load is listed and marked with the
  reason, never skipped — a skipped record looks exactly like one never copied.
  `job machines NAME` prints one record with the source of each fact.
- `local` is always the machine the command runs on.
- **Stale.** A record whose identity is this machine's is marked `stale` when
  its `settings` differ from this machine's `config.toml`: a run script built
  from it would contradict this machine. When only its `environments` differ
  from what `env list` reports now, it is not stale; preparation and `job machines NAME` say so beside the environment, naming `job probe --write`. The comparison
  asks no scheduler, so it runs on every `job machines`, `job machines NAME`,
  `doctor` and `job prepare`; a change in the cluster's partitions or queues is
  not detected this way, which is why every record shows when it was measured.
  A record of another machine cannot be compared from here and is never marked.
- **A record of this machine has a state**, declared as data in
  `femkit/data/states/record.toml` ([`core.md`](core.md) § 7) over the facts
  `jobs/record.py` gathers, the first rule that holds: `absent`, no file;
  `unloadable`, its file does not load; `stale`, as above; otherwise `current`.
  Every state allows `job probe --write` — with `--name` for a record named
  other than `local` — declared in each state's row; `doctor` and `job
  machines` name it for a record not `current`, and a current record that
  lacks an environment's fingerprint is measured again by its own row's. `job machines` observes every record by these rules —
  a record that does not load is `unloadable` whichever machine it was, and its
  probe is run on that machine — but one that loads and names another machine,
  which is never compared; it lists each with its own words for the state:
  `does not load`, `stale`, or `ok` for a record that loads and is current or
  cannot be compared.
- A calculation keeps a copy of the record it was prepared for, taken at its
  first prepare, and its runs read that copy (§ 3); a newer record reaches
  calculations not yet prepared.
