# Jobs — requests, run scripts, runs and schedulers

**Role:** contract
**Status:** current; built: machine records and the probe (§ 9), and the scheduler kinds' probe commands and readers, each kind checked against its reader when it loads (§ 7). Not built: §§ 1–6, § 8 but `job probe` and `job machines`, and § 7's header, submit, check, query and cancel (plan § 4, X and M4); whether X rewrites §§ 1–5 is the person's (plan § 4, X)
**Authority:** machine records and the probe, the job request, preparation,
the run script, the run state machine, and how femkit uses a scheduler

## The short version

| rule | § |
|---|---|
| A **job** runs one command in one engine environment with stated resources, on one node; a **calculation folder** holds its request, its scripts and its runs | 1, 2 |
| `job prepare` reads the request, the **target's machine record** and the scheduler kind, writes a self-contained run script for the request as stated, and shows how it fits the record — refusing only a missing statement, one that contradicts the record, or a prepared case's input whose hash differs from its request | 3 |
| The run script is a **closed list of blocks**; every fact about the machine is fixed in it at preparation, and it arranges no file | 4 |
| A run is **one start**: each launch fills a new `run-NNN/` and starts it there; nothing is overwritten | 5 |
| A run's state is **observed** from its markers, its facts and, when asked, the scheduler; six ordered rules decide it | 5 |
| **One job per launch**, by the person; femkit never submits in a loop, retries, or changes an ask | 6 |
| What a scheduler is told is its **kind file**, from closed lists of parts; only irregular answers have readers, in `femkit/schedulers/` | 7 |
| A **machine record** holds what one machine offers, measured by `job probe` on it: scheduler, queues, node groups, installed environments, and the settings a run script needs. It is shown, never a veto | 9 |

Turning a scientific model into solver input is not this contract; it produces
the inputs a job request names.

## 1. The calculation folder

```text
<calculation>/
├── job.toml          the request — written by a person or a preparer
├── <inputs>          files the command reads, as the request lists them
├── machine.toml      copy of the target's record used by the last prepare
├── run.sh            the run script
├── submit.sh         the scheduler header that starts run.sh (targets with a scheduler)
├── prepared.json     what prepare resolved — written last
└── run-001/          one start: copies of the inputs, run.sh and submit.sh;
                      its outputs, logs and markers
```

A calculation folder is written by a person, or by `case prepare` for a
prepared case, in its project's run folders (`runs/`,
[`projects.md`](projects.md) § 2; their design is plan § 4, X), holding its
`job.toml` (§ 2) beside the prepared `final/` inputs; a job reads nothing else of the
preparation ([`models.md`](models.md) § 9.3; not built yet, plan § 4, X and M6).

## 2. The job request — `job.toml`

```toml
environment = "elmer"                  # an engine environment
command = ["ElmerSolver", "case.sif"]
inputs = ["case.sif", "mesh"]          # copied into each run
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

The schema model is the authority for every field (`docs/reference/`). The
request holds only what this calculation asks for; nothing about a machine.

- **Every resource is stated**, none defaulted ([`framework.md`](framework.md)
  § 4): `ranks`, `threads` and `gpus` always; `wall`, `memory` and the queue on
  a machine with a scheduler. On a machine without one, the queue, wall and
  memory are not read, and preparation says so, so one request serves a
  cluster and the workstation.
- **One node.** A job runs on one node. `memory` and `gpus` are stated per
  node, as the record measures nodes and the scheduler grants them, so a job
  across several nodes would add a node count without changing what either
  means.
- **A GPU ask is a count**; no field names a card.
- **One spelling each.** `wall` is `[D-]HH:MM:SS`, at least three parts:
  `04:30` is refused, because a scheduler reads it as four minutes thirty.
  `memory` is a positive whole number with its unit (`K`, `M`, `G`, `T`): a
  bare number is megabytes to SLURM, and `--mem=0` means the whole node.
- `partition` and `qos` together name one of the target's queues
  (§ 9.1); which queue to spend the wall time in is
  the person's judgement.
- **A prepared case's request** (not built yet, plan § 4, M6) lists each input
  with its SHA-256 and whether it was generated or customized
  (`{ path = "case.sif", sha256 = "…", origin = "customized" }`), the steps
  to run before and after the command (`steps.before`, `steps.after`), and the
  environment's install fingerprint and lock hash it was prepared for
  (`prepared_for`). `job prepare` refuses an input whose hash differs, naming
  `case prepare`; a target whose record lists the environment with another
  fingerprint is a warning (§ 3, step 4), and the run script stops before the
  command when the prefix is not the one prepared for (§ 4).

## 3. Prepare

`job prepare DIR [--target NAME]` runs these steps. A refusal — a missing
statement, one that contradicts the record ([`framework.md`](framework.md) § 4),
or a prepared case's input whose hash differs from its request —
writes nothing; everything the record says about the request is shown as a
warning, and the job is prepared as asked. Nothing here probes a machine.

1. **Request** — load `job.toml`; for a prepared case (§ 2), refuse an input whose
   SHA-256 differs from the request's, naming `case prepare`.
2. **Target** — the record named by `--target`; otherwise the target named in
   the folder's `prepared.json`; otherwise `local`, but only when no record of
   another machine is present in `<config>/machines/`. When one is, the first
   prepare is refused and lists every record with the `--target` line for
   each: being asked costs one flag, preparing for the wrong machine costs a
   queue wait. A folder already prepared for one target changes target only by
   an explicit `--target`. The record is always read again from
   `<config>/machines/`, so a newer probe is used; `machine.toml` is the copy
   the runs read.
   - A target with no record, `local` included, is refused, naming `job
     probe --write`. A record that does not load is refused with its reason,
     never replaced by the next source.
   - A record whose identity is this machine and whose `settings` no longer
     match this machine's `config.toml` (`stale`, § 9.3) is refused, naming `job probe --write`.
3. **Statements** — refused, naming what to state: a resource § 2 requires
   that is stated nowhere or is mis-spelled; with a scheduler, a record that
   lists no queues (naming the probe that renews it), no queue named, or a
   (partition, QOS) pair that is not one of the record's `queues` — the refusal
   lists them with the request's fit on each; a record whose
   `activation.preamble` or `activation.command` is unset.
4. **Environment** — the engine's environment, and with `gpus > 0` its CUDA
   environment, `<name>-cuda` ([`definitions.md`](definitions.md) § 4.5).
   Shown, from the record's `environments`, which is `env
   list` on the target as of the record's `measured` time
   (§ 9.1): the environment not installed there, in a
   state other than `ready`, built for another platform than the partition's
   nodes, or — with `gpus > 0` — not GPU-qualified (`passed`,
   [`envs.md`](envs.md) § 5), or, for a prepared case, listed with an install
   fingerprint other than the request's `prepared_for`, is a warning naming the
   command that settles it on the target (`env install NAME`,
   `env validate NAME --gpu` on a GPU node, `case prepare` again).
   When the record could not list environments, nothing is said. The run
   script stops, saying so, if the prefix is not there (§ 4).
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
   `settings` (§ 9).
7. **Commit** — copy the record to `machine.toml`, then write `prepared.json`
   with the target's name, the environment's install fingerprint, the resolved
   resources and the hash of each script.

Preparing again regenerates the scripts. Earlier runs keep the copies they ran.

## 4. The run script

Self-contained: it reads only what the scheduler granted and its own run
directory, which `job launch` has already filled (§ 5). It creates no
directory, copies no file and changes directory nowhere. Its blocks, in order:

| # | block |
|---|---|
| 1 | strict mode (`set -euo pipefail`); it runs in the run directory, its one argument |
| 2 | refuse if that directory already has `started.json` |
| 3 | traps. On the script's own exit, write `ended.json`: exit code, time, and the reason when the script stopped itself. On a stop signal (HUP, INT, QUIT, TERM, XCPU and the like), log the signal and exit 128 + its number **without** `ended.json`: a forced stop — a cancel, the wall time, a node failure — is told by the scheduler or by `cancel.json`, never by a marker |
| 4 | write `started.json`: time, host, and from the kind's job variables the scheduler job ID, ranks, cores per rank, cores on the node, GPUs and nodes granted; with `gpus > 0`, the GPU model the driver reports (no count). With `gpus > 0` and no device visible — the scheduler's GPU grant, else `CUDA_VISIBLE_DEVICES`, else the driver's own list — stop with that reason |
| 5 | the target's `activation.preamble`, from the record's `settings`, with unset variables allowed (`set +u`, restored after; `-e` stays on): a site's or a package's activation scripts read variables that may be unset |
| 6 | enter the exact prefix with the target's `activation.command`, from the record's `settings` — `source activate <prefix>`, or the manager kind's hook sourced then `conda activate` / `mamba activate <prefix>` (`set +u` as in 5) — then verify the active prefix is that one, that the command's executable resolves inside it, and, for a prepared case, that the prefix's install fingerprint and lock hash are the request's `prepared_for`; stop with the reason otherwise |
| 7 | set each of the environment's `thread_variables` to `threads` and its `fixed_variables` to their values ([`definitions.md`](definitions.md) § 4.4) |
| 8 | verify every input the request lists is present in the run directory; stop naming any that is missing |
| 9 | run the command — through `launch.mpi` when `ranks > 1` — with output to the run's log. Under a scheduler no binding or mapping options are added: the scheduler has placed the job. For a prepared case, the steps its request lists run before and after the command, each with its own log ([`models.md`](models.md) § 8.3; not built yet, plan § 4, M8) |
| 10 | exit with the command's status |

## 5. Runs

`job launch DIR` opens the next `run-NNN/`, copies into it the request's
inputs, `run.sh` and, with a scheduler, `submit.sh`, and starts it there:
directly, in a new process session, on a machine without a scheduler; or by one
submission made from inside the run folder, so the header's relative output
names land in it. The launch is refused when the folder has a run that is
`queued`, `running` or `unknown`, or when this machine's identity is not the
target's.

- A submission the scheduler refuses removes the run folder it opened and
  shows the scheduler's answer.
- A submission that succeeds without a job ID femkit can read writes
  `launched.json` with no ID and the scheduler's answer; that run reads
  `unknown`, and `job status` shows the answer so the person can find the job.

### 5.1 Facts

| fact | from |
|---|---|
| launched | `launched.json`, written once the start succeeded: the machine's identity, and the process (host, pid, the process's start time) or the scheduler job ID |
| started / ended | `started.json`, `ended.json`, written by the run script |
| cancel requested | `cancel.json`, written by `job cancel` once its command succeeded |
| gone | `gone.json`, written the first time the scheduler, asked, no longer lists a job that has no `ended.json`: when, where it was asked, and the scheduler's words. It is read on any machine afterwards, so the answer survives copying the folder |
| alive | asked when needed: the same process (pid and start time) exists, or the scheduler lists the job in a state that is not one of its kind's ended words. An ID the scheduler no longer knows is not listed: SLURM keeps an ended job only briefly |

### 5.2 Observation — the first rule that matches

| # | when | state |
|---|---|---|
| 1 | `ended.json` with status 0 | `finished` |
| 2 | `ended.json` with any other status | `failed` |
| 3 | cancel requested, and known not alive (asked now, or `gone.json`) | `cancelled` |
| 4 | alive: started → `running`; not started → `queued` | `running` / `queued` |
| 5 | known not alive; or started, and its start plus its wall has passed | `lost` |
| 6 | otherwise — whether it is alive cannot be asked from this machine | `unknown` |

For `lost`, `job status` adds the scheduler's own final words: its line in the
run's error file (`*** JOB … CANCELLED … DUE TO TIME LIMIT ***`), read by the
kind's reader, and `gone.json`.

### 5.3 Actions

| state | `launch` (a new run) | `cancel` |
|---|---|---|
| `queued`, `running` | refused | allowed |
| `finished`, `failed`, `cancelled`, `lost` | allowed | nothing to do |
| `unknown` | refused | refused |

`cancel` stops a local run's whole process group (`SIGTERM`), or asks the
scheduler to cancel the job; the run script's trap logs the signal (§ 4).

## 6. Rules

- **One job per launch.** A launch submits at most one job, on the person's
  command. There is no batch submission, no automatic retry and no resubmission.
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
| `job launch DIR [--check]` | § 5; `--check` asks the scheduler without submitting |
| `job status DIR` | each run's state; for a queued job the scheduler's state and reason, for a lost one its final words |
| `job cancel DIR` | cancel the queued or running run |
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
| `schema` | the record's schema version |
| `measured` | when, and where the probe ran: a workstation, a cluster's login node, or inside a scheduler job |
| `identity` | the scheduler's cluster name (`ClusterName`), or the host name of a machine without one — how a command knows it is running on that machine |
| `host` | the machine the probe ran on: operating system, architecture, cores, memory, and GPUs (model, compute capability, memory) as the driver reports them |
| `manager` | kind, path, version, root, its platform (`linux-64`, `linux-aarch64`: what an environment built here is for), and `run_enters`: whether `<manager> run -p <control prefix>` actually runs inside that prefix here, measured by running it once |
| `scheduler` | kind (from `schedulers/`) and the path of each command its kind names |
| `partitions` | each partition's limits — `MaxTime`, `MaxCPUsPerNode`, `DefMemPerCPU` or `DefMemPerNode` (each kept as stated, never converted into the other), and the QOS it allows or denies — and its **node groups**: count, cores, memory, GPUs per node as `{type: count}`, architecture |
| `queues` | each (partition, QOS) pair **this account may submit to**, from the scheduler's association records, with its effective limits: the shorter of the partition's `MaxTime` and the QOS's `MaxWall`; the QOS's per-job cpu, memory and GPU caps (`MaxTRESPerJob`); and `MaxSubmitJobsPerUser`, shown and never counted, since femkit submits one job per launch. When the account's QOS list cannot be read, each partition is one queue with no QOS, and the record says so |
| `environments` | `env list` on this machine when the probe ran: each environment with its state, install fingerprint, solver version and GPU qualification; its platform is the record's `manager.platform`, since this machine's manager built it. An empty table means none is installed; one that could not be listed is `unknown` with the reason |
| `settings` | a copy of this machine's `config.toml` values a job run here needs: `paths.environments`, `launch.mpi`, `activation.preamble`, `activation.command` |

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
  that states none (`(null)`) has measured `{}`, never `unknown`.
- **Which queues.** Associations are those of the user running the probe; one
  that names no partition holds on every partition; `no_submit` is not a QOS;
  a pair the partition denies (`AllowQos`, `DenyQos`) is not a queue. Each
  optional column is its own query, so one column a site's scheduler does not
  know cannot cost the others, and columns are read by name, never by position.
- **`environments` is a dated snapshot**: what `env list` answered at
  `measured`. It is shown, never read back as an environment's state, which is
  observed on the machine itself ([`framework.md`](framework.md) § 3). From a
  workstation it is the only view of a cluster's environments.
- **One schema version.** A record states its version; a record of another
  version does not load, and `job machines` names its version and the probe
  that rewrites it, run on that machine. Unknown keys do not load: only the
  probe writes records, never a person.
- The probe copies `settings` as they are; it does not choose them. They let a
  job be prepared on one machine for another. After a change to the machine's
  `config.toml` or its environments, the record is probed again.

### 9.2 Probing, declaring and writing

`job probe` measures the machine it runs on and prints the record, any
facts it could not measure and why, and the exact command that would write what
was shown. It writes nothing without `--write`.

| option | does |
|---|---|
| `--write` | write `machines/local.toml`, this machine's own record |
| `--write --name NAME` | write `machines/NAME.toml`, the record another machine prepares this one by; `local` is refused as a name |
| `--set KEY=VALUE` (repeatable) | **declare** where a scheduler command is, when the probe cannot find it — a site's own submit wrapper, `--set scheduler.commands.submit=PATH`. Only command paths are declarable; nothing in `identity`, `partitions`, `queues`, `environments` or `settings` is, because a queue list typed on another machine is a guess. An unknown key or a mistyped value is refused by name; the declared value's source is `declared` |
| `--scheduler KIND` | name the scheduler kind instead of detecting it; its commands are still located |
| `--yes` | accept every difference from an existing record without asking |

- **Detection.** A kind with commands is detected when its `submit` command is
  found or declared; when none is, the kind is `local`; when two are, the probe
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

1. on the cluster: `python -m femkit job probe --write --name cluster-a`;
2. copy `machines/cluster-a.toml` into the workstation's `<config>/machines/`;
3. on the workstation: `python -m femkit job machines` shows it arrived and loads.

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
- A calculation keeps a copy of the record it was prepared for, and its runs
  read that copy (§ 3).
