# Testing — tiers, isolation, the runner, and what earns a test

**Role:** contract
**Status:** current; what is not built yet is marked so
**Authority:** test tiers and their boundaries, isolation of the person's
machine and its canaries, the admission rule for a test, and the test runner —
its progress log, its one-run-per-batch lock and the states it reports

## The short version

| rule | § |
|---|---|
| **Four tiers**, one directory each: `basic` (no outside tool), `web` (the `web` environment), `field` (this machine's real manager and scheduler), `engine` (installed solvers) | 1 |
| A basic or web test cannot reach the person's directories, a package manager, a scheduler or a solver: each is a **tripwire** that fails the test | 2.1 |
| **Canaries** measure the outcome: a run that changed the person's config, environments or checkout fails | 2.2 |
| No test input is **typed-in output** of a solver, manager or scheduler; output is read where it is printed — in the field and engine tiers | 2.1 |
| A test exists only by naming the **failure it catches** that nothing else would; it says so, and which contract owns the rule, in its first lines | 3 |
| Tests assert **results through the API**, never text grepped from source or a rendered file | 3 |
| Scientific validation tests are **protected**: their design may change, their existence may not | 3 |
| `tools/testrun.py` streams every result to a **progress log** that outlives the run; a log holding an unfinished run is never wiped | 4.2 |
| **One run per batch**: a second copy of a batch that is running is refused | 4.3 |
| `status` prints a count as a result **only** when the log proves one complete run, and says when that run was of other code | 4.4, 4.5 |

## 1. Tiers

| tier | answers | needs | directory |
|---|---|---|---|
| **basic** | does femkit decide and write what its contracts say? | the control environment only | `tests/basic/` |
| **web** | does the web surface serve, check and refuse what its contract says? | the `web` environment's Python, which holds flask (`env install web`; [`web.md`](web.md)) | `tests/web/` |
| **field** | does it work with **this** machine — its manager, its scheduler, its records? | this machine's manager (and network for a small package solve); on a cluster, its scheduler | `tests/field/` |
| **engine** | do the installed solvers give the right numbers, and does a real job run end to end? | installed engine environments; their CPUs and GPUs | `tests/engine/` |

- **Basic** drives operations the way a person does — load definitions, plan,
  observe states from records written by the real writers, prepare a job — and
  checks what comes back and what is written.
- **Field** first proves the toolchain on this machine: each default engine
  environment's packages, solved by the install's own `create` step and put
  through its own `toolchain` step (`tests/field/test_toolchain.py`; [`envs.md`](envs.md)
  § 4.5), and probes the machine (`tests/field/test_job_probe.py`). Not built
  yet: a tiny environment from a test definition in `tests/field/data/`,
  walked through its states (`absent → ready`, a changed definition →
  `outdated`, an interrupted install → `incomplete` → resumed); a small job
  run through `run.sh` (M3); on a cluster, asking the scheduler without
  submitting (`job launch --check`, M4).
- **Engine** runs `env validate` on installed engines and one real calculation
  per engine through `job launch`, checked against analytic or published
  values. It spends the machine's cores and runs on the person's word.

A tier passes before the next is worth running.

## 2. Isolation

### 2.1 By construction

Every test, in every tier, runs with `FEMKIT_CONFIG_DIR`,
`FEMKIT_DATA_DIR`, `FEMKIT_CACHE_DIR` and `FEMKIT_STATE_DIR` set to its own
temporary directories. No test reads or writes the person's configuration, records or
projects, and only the engine tier reaches the person's environments: its
temporary `config.toml` points `paths.environments` at them, on the person's
word, and `env validate` writes each prefix's check results there exactly as it
does for the person. In that tier the environments canary (§ 2.2) watches
`conda-meta/` and the manifest, not the check results.

In the **basic** and **web** tiers, `PATH` starts with a directory of
tripwires for every outside program femkit can start: the managers, MPI and
scheduler commands, CMake and CTest, `nvidia-smi`, and every executable an
environment definition names — the solvers, and the `web` environment's
Node.js. A tripwire logs its call and exits 97; a test that reached one
fails, naming the call. `FEMKIT_ENV_MANAGER` points at a tripwire too. No
scheduler kind's job variables are set, so the basic tier gives the same answers
run inside an allocation as anywhere else.

No tier feeds a reader text typed by hand as if a solver, manager or scheduler
had printed it. A reader is tested on real output, in the tier that produces it.

### 2.2 Canaries — the outcome, measured

Isolation by construction is a claim; three session-wide canaries measure it.
Each fingerprints something of the person's when the run starts and again when
it ends, and a difference fails the run, naming what changed:

| canary | fingerprint | catches |
|---|---|---|
| config | every file under the person's real config directory: names, sizes, modification times | a test writing past `FEMKIT_CONFIG_DIR` |
| environments | for each environment femkit manages here (the control prefix under the real `<data>`, and each engine prefix under the person's real `paths.environments`): entry count and modification time of its `conda-meta/` and `.femkit/` | a test that reached the real manager and installed into, or removed, an environment |
| checkout | the code digest of § 4.5 | a test writing into the repository — or a person editing it while a run is going |

- The real directories are resolved once, before the run's own isolation is
  set; no test can move them.
- A canary that cannot read its side (no git, an unreadable directory) does
  not pass: it warns that it is **disarmed**, so "no alarm" and "no canary"
  never read alike.
- A canary fires in the session's teardown. The runner records that as a
  failure (§ 4.4), never as a clean run. The fix is always in the test that
  reached out, never a relaxed canary.

## 3. What earns a test

- **Admission.** A test names a failure it would catch that no other test,
  type or validator already makes impossible. Unifying an API should remove
  tests, not add them.
- **First lines.** Its docstring states that failure and the contract section
  owning the rule. A rule no contract states is not tested; it is first written
  into its contract or dropped.
- **Tests check the API.** A test asserts on what an operation returns, the
  records and files it writes, and the outcome of running what it generated —
  through the interfaces femkit offers, never by reading source code or
  grepping a rendered file for a line.
- **The code's discipline is the review's.** Rules about the code itself — the
  one-way rules and the layers ([`framework.md`](framework.md) § 1), no
  duplicated or hand-made code, the page naming no field
  ([`web.md`](web.md) § 12) — are held by design where it can hold them, and
  by each milestone's independent review, which reads the source against them
  ([`../process/conventions.md`](../process/conventions.md) § 1). No test reads
  code. The person's decision (plan § 6); today's tests that read source are
  removed in plan § 3, R step B.
- **Proven to fail.** Before a test is trusted, the rule it guards is broken in
  the code and the test is seen to fail.
- **Retired with its design.** When a design is replaced, its tests are deleted
  and new ones are written from the new contract.
- **Science is protected.** A test asserting a physical result — an analytic
  benchmark, a convergence order, a tolerance with a stated source — stays; its
  design may change, its existence may not.
- **Every failure is real.** A red test is diagnosed against its contract and
  fixed in the code or the test; none is skipped, filtered out or called flaky.

## 4. Running the suite — `tools/testrun.py`

### 4.1 Commands

```bash
python tools/testrun.py run basic                  # the default tier, over the cores
<data>/environments/web/bin/python tools/testrun.py run web   # the web environment's own Python
python tools/testrun.py run field                  # this machine's manager/scheduler
python tools/testrun.py run engine                 # installed engines, on the person's word
python tools/testrun.py run tests/basic/test_x.py  # a targeted set: batch `custom`
python tools/testrun.py run lf                     # only the last run's failures
python tools/testrun.py status [BATCH] [--fails]   # what each batch's log supports saying
python tools/testrun.py failed BATCH               # failed test IDs, to pass back to pytest
```

It runs from the repository root in the control environment and is started in
the background. A pytest plugin, `tools/progress_plugin.py`, writes the log.

The runner and its plugin use the standard library and pytest only, and import
nothing from `femkit`: the instrument that reports femkit's failures must keep
working when femkit is broken. They follow the framework's state-machine rules
all the same ([`framework.md`](framework.md) § 3, [`core.md`](core.md) § 7): state read from a log, one
closed table, one lock per subject.

### 4.2 The progress log

Each batch has one log, `.test-progress/<batch>.jsonl`, in the checkout and
ignored by git — a stable path any shell or session can read, never a temporary
file. The plugin appends one record per result and flushes it at once, so the
log is current while the run is going. pytest's own output is no substitute:
a pipe buffers it until the process exits, and a `tail` cuts the failure list
short.

| record | written | fields |
|---|---|---|
| `start` | when the run begins | `pid`, `time`, `code` (§ 4.5), `asked` (pytest's arguments) |
| `collected` | once, when the run's tests are known | `n` |
| `test` | a test's call; a setup that failed or skipped; a teardown that failed (ID suffixed ` [teardown]`); a worker crash | `nodeid`, `outcome` (`passed`, `failed`, `skipped`, `xfailed`), `reason`, `duration` |
| `collect` | a file that failed to import, or skipped itself whole | `nodeid`, `outcome`, `reason` |
| `done` | when pytest exits | `exitstatus` |

Every record carries `run`, the ID of the run that wrote it, and `time`. A
`reason` is the last line of a failure's text, or the skip or expected-failure
reason.

- **A log outlives its run.** A new run empties the log only when its last
  record is `done`. Otherwise — a run still writing, or one that was killed —
  the new run appends its own `start` after it: the older records are evidence
  and are never wiped. `status` reads the last generation, from the last
  `start`.
- **One writer.** A run spread over workers (§ 4.6) is written by the one
  process the runner started; the workers stay silent and their results are
  relayed to it, so the log reads exactly as a one-process run's.
- **The full text.** The run holding the batch's lock (§ 4.3) also keeps
  pytest's own console output of its last run at `.test-progress/<batch>.out`: the full
  tracebacks, and whatever never becomes a record (§ 4.4, `unexplained`).

### 4.3 One run per batch

Two runs of one batch writing one log make its counts meaningless: more tests
"ran" than were collected, two runs' failures mixed, the first run's `done`
reported while the second still runs. So `run` takes an exclusive `flock` on
`.test-progress/<batch>.lock` and holds it for the run's life. The kernel
releases it however the process ends — normally, on Ctrl-C, when killed — so
there is no stale lock to detect or clean up. The lock file holds the holder's
pid only so a refusal can name it; nothing is decided from it.

- A second `run` of a batch that is running is **refused** (exit 2), naming
  the holder and `status <batch>` to watch it.
- `--force` runs anyway and says so: both runs append to one generation, which
  `status` reports as `interleaved`; once both have ended, the batch's next run
  starts a clean log.
- Different batches run side by side, each with its own log and lock.
- A part of a batch — files named after a tier, or any targeted set — is the
  batch `custom`, never logged under the tier's name: twelve tests are not the
  basic tier. `status` shows what was asked.

### 4.4 What `status` may say

A batch's state is observed from its log's last generation each time `status`
runs, by one closed table. The rows are checked in order; the first that
matches is the state.

| state | observed when | counts printed as a result? |
|---|---|---|
| `no-data` | no log | — |
| `unusable` | no `start` (the file was cut under a writer), or no `collected` (collection never finished) | no |
| `interleaved` | records from more than one `run` | no |
| `partial` | `done`, but fewer tests ran than were collected | no |
| `unexplained` | `done` with a non-zero exit and no failure recorded — a canary, an internal or a plugin error; read `<batch>.out` | no |
| `done` | `done`, every collected test accounted for | yes |
| `running` | no `done`; the writer's pid exists and the log changed within the silence limit | progress only |
| `abandoned` | no `done`; the writer's pid is gone, or the log has been silent past the limit | no — a fragment |

- **`ran` counts distinct test IDs, not records.** A teardown failure or a
  crash reported against a test that already has a record is a failure, never
  a second test.
- **A file that fails to collect is a failure**: counted in FAIL, named by
  `--fails`, never counted in `ran`.
- **A skip is not a pass, and an expected failure is neither.** Each is counted
  apart and listed by reason. An expected failure that passes fails the run
  (`xfail_strict`).
- **The exit code outranks the counts.** A non-zero exit with nothing recorded
  as failed is `unexplained`, never `FAIL 0`.
- **A pid only rules a writer out.** A missing process settles it; a live pid
  does not, because pids are reused. The log's own clock decides: a log silent
  past the limit (30 minutes, far above the slowest single test) belongs to a
  run that is not writing any more. Calling a live run dead is the worse error,
  so the limit is generous.
- `status` exits non-zero when any batch it shows cannot be trusted:
  `unusable`, `interleaved`, `partial`, `unexplained`, `abandoned`, or a
  `done` of other or unknown code (§ 4.5).

### 4.5 Which code a result is about

`start` records a digest of every file git would keep — tracked, and untracked
but not ignored — by name and bytes, a link by its target, computed with the
person's git settings left out. `status` recomputes it for each `done`:

- the same digest: the result is about the code in the checkout;
- a different one: `done, on other code` — it is not today's result;
- none could be computed: `done, on unknown code`.

A commit changes no bytes, so a result stays valid across it. `status` also
prints when each run started, so a repeated run of unchanged code can be seen
to tell nothing new; the runner never skips one on its own.

The checkout is not edited while a run of it is going: the result would be of
neither version. The checkout canary (§ 2.2) compares this digest at the run's
start and end and fails a run whose files changed under it.

### 4.6 Spreading a run over the cores

`basic` runs over pytest-xdist workers — by default a quarter of the cores, at
most 8; `--workers 1` is one process. `field` and `engine` always run in one
process, one test at a time, so no two installs or calculations compete for the
machine.

- A file whose tests share a fixture wider than one test runs whole, in order,
  in one worker (`--dist loadgroup`, the group named by the file's
  `xdist_group` mark).
  Every other test runs on whichever worker is free.
- A worker that dies ends the run (`--max-worker-restart 0`). The test it was
  running is recorded as failed with the crash as its reason; the tests no
  worker reached leave `ran` short, and the run reads `partial`.
- A test's ID and its place in the collection never depend on the process —
  no clock, pid, random draw, unsorted set or temporary path in its
  parameters — because xdist refuses a run whose workers disagree.
- A targeted set is handed to pytest ordered by directory, so a subdirectory's
  `conftest.py` binds every file in it.
- IDs are reported without xdist's `@group` suffix, so `failed` and
  `status --fails` print IDs pytest accepts back.

### 4.7 Rerunning failures, and the working loop

- `run lf` reruns the last run's failures, in one process, and only when
  pytest's last-failed list names a test file in the checkout. When it names
  none it runs nothing and says so; pytest's own `--last-failed` would run
  every test.
- The loop: run the tests of what changed and of what it touches, read
  `status --fails`, fix, `run lf`. A whole tier runs at a milestone that
  reaches it.
- No conclusion is drawn from a truncated view: `status --fails` lists every
  failure, one line each.
- A failure in a test the change seems not to touch is checked against `HEAD`
  in a throwaway `git worktree` before it is called pre-existing.

### 4.8 The runner's own tests

`tests/basic/test_testrun.py` holds one test per row of the § 4.4 table and
per counting rule, built from logs in the record format of § 4.2 — femkit's own
format, so typed records are fair input. The rules only a live run shows run a
real pytest session through the plugin: a log is emptied only after `done`, a
teardown failure is recorded, a spread run reads as one run, a dead worker
leaves the run `partial`, and `run lf` with nothing to rerun runs nothing.
