# ADR 0022: one prep step, from a project to what a job runs

**Role:** ADR

**Status:** accepted (2026-11-26); built, its definitions step with ADR 0021,
but the page's Preview and Prep (plan § 4, G). It withdraws
`study expand` and `study mesh` as commands of their own, their work prep's
steps, and `case prepare` as a command to come, the solve's input a stage
prep writes (M6); it amends [ADR 0016](0016-every-step-runs-from-a-run-folder.md)
decision 4 — the per-engine sequence is prep's — and
[ADR 0021](0021-definitions.md) decisions 5–6 — prep keeps the definitions'
values, per study. Decisions 2's stages and jobs per engine, 4's study
binding no environment and 10's `[environments.<e>.meshing]` amended by
[ADR 0025](0025-one-engine-per-study-observables-after.md) (decision 1): a
study names no engine — its geometries and meshes, and its one meshing job
stated in its `[meshing]`, serve every engine that solves it — and prep
without an engine makes its cases, geometries and meshes too, the engine
chosen when the study is solved, `study prep --engine`

**Authority:** the reasons and the alternatives only;
[`workflow.md`](../contracts/workflow.md) § 7 owns prep's steps and its
command, [`models.md`](../contracts/models.md) § 3 the definitions and their
kept values, [`api.md`](../contracts/api.md) § 3 what a plan may run,
[`jobs.md`](../contracts/jobs.md) § 3 a prepare planned in memory

## Context

femkit got a study ready to run in three commands: `study expand` wrote its
cases, every value resolved; `study mesh` wrote each engine's geometry and
mesh stages, prepared for a machine, and the jobs that make them; and
`case prepare` (M6) would write each solve's input. Definitions
([ADR 0021](0021-definitions.md)) added Python the person writes, whose
values the cases need, run — the person, 2026-11-25 — "during check and
expand".

The person, 2026-11-26: "there is a prep step which should be probably be
either before or in the same study expand step, which is right before the run
job would be deployable to HPC or workstation for execution. this prep step is
to get every parameter finalized/validated for all downstream"; "you can check
molbuilder's jobset, which has a prep step"; and, given the two designs below,
"you do the investigation and do the correct logical decision. we want UI and
command cli to work together to present the higher level flowchart, while
provide correct and easy steps to prep for actual execution".

The person's earlier tool has one prep, the hub between describing a
calculation and launching it: one entry run by both doors, the command line's
`jobset prep` and the page's **Preview** and **Prep**; one table of steps
stated once, each deciding within what the steps before it fixed, a kind
adding its own steps as data, never a second sequence; the plan made whole —
every file's text, every job's header — before anything is written; every
launch value stated or refused at prep, so launch sends what prep wrote; one
answer, data, which both doors show. Three holistic reviews of a first draft
of this decision, read against that design, found what this one corrects.

## Decision

1. **One command, `study prep STUDY [--target NAME]`**, takes a study from its
   written parts to what its jobs run, for one machine. `study expand` and
   `study mesh` are withdrawn as commands: their work is its steps.
2. **Its steps, in order, stated once** ([`workflow.md`](../contracts/workflow.md)
   § 7), each deciding within what the ones before it fixed — first those
   that need no machine:
   1. **definitions** — the project's definitions computed and every value
      resolved and validated at every point of the study's sweep;
   2. **cases** — each case, every value final;
   3. **machine** — the target's record read and checked: it loads, is not
      stale, states its activation, names a manager kind femkit has;
   4. **stages** — each engine's stages of every kind the stage kinds
      declare, written and prepared for the machine; the solve kind's input
      is one of them once its translators are built (M6), never a step or a
      command of its own;
   5. **jobs** — one job per engine, its header and walk, ready to launch.
3. **Planned whole, then written.** Every step runs in prep's plan, each
   job folder's prepare planned from its request in memory
   ([`jobs.md`](../contracts/jobs.md) § 3), so every refusal comes before
   anything is written, and `--dry-run`, the preview, shows every value,
   every folder, every job's fit. A plan may run one declared computation, the
   project's definitions, in its own process in `model_prep`, with a time
   limit, writing nothing but femkit's cache ([`api.md`](../contracts/api.md)
   § 3) — once per plan: its result is cached by what it rests on.
4. **What needs no machine never waits for one.** Where the machine step
   cannot go on — no record of the target, an environment the record lacks —
   prep writes the definitions and the cases, and its outcome names what the
   stages wait for, with the steps that settle it; a study binding no
   environment is prepped to its cases. Any other refusal writes nothing.
5. **One entry, two doors.** The page's **Preview** and **Prep** run the same
   operation as the command line, and show the same answer; the page's
   context names the machine.
6. **Where the person's Python runs**: in `project check`, which computes and
   validates the definitions and writes nothing, and in prep, which keeps
   their values for the study — the person's "during check and expand", prep
   now being the expansion. Never when a file is saved. Every other reader —
   `study flow`, `case list`, `study list`, a save's impact — uses the kept
   values where they are in sync, and otherwise shows the stages that rest
   on a computed value not kept as waiting for `study prep` — not drawn,
   their identity not formed yet; one finding says so.
7. **The flowchart is one graph for both doors.** `study flow` and the page's
   workflow view draw the study's stages for the machine: before prep, what
   prep will make; after it, each stage's state. A stage with no folder reads
   `to_prep`, *needs update*, its next step `study prep` — or *waiting*, while
   a stage it takes from is not made.
8. **Prep is run again across a stage's inputs**: a stage is placed in a job
   only behind the stage it takes from, in the job this prep writes for both
   — a mesh behind its geometry; one whose input another job holds waits, and
   a later prep places it. The solve kind rides no meshing job, so the person
   looks at the meshes before a solve, as ADR 0016 decision 4 has it.
9. **Launch sends what prep wrote**: `job launch` of each job prep names.
10. **The meshing job states its own resources** (the person, 2026-11-26,
    asked whether it should ask the solve's): a study states, per engine,
    `[environments.<e>.meshing]` beside the solve's `resources` — the solve
    riding no meshing job, the solve's 8 cores and 2 hours would be reserved
    by a job whose every step runs one process. Its wall is long enough, no
    more (the person, 2026-11-26: "long enough is long enough"); a job that
    stops at it is launched again, as the earlier tool continues one — what
    finished is used, the rest runs; nothing is ever added to a job once
    launched, a new case being a new prep's job.

## Alternatives not chosen

- **Prep as the definitions step alone, before `study expand`**: two
  commands where one does, and the stages and jobs still a third.
- **The machine first, as the earlier tool orders it**: a machine with no
  record could write no case, though a case names no machine; the earlier
  tool's first step reads the record its every later step renders with,
  where femkit's definitions and cases render nothing for a machine.
- **Saving the folder's state before prep writes, as the earlier tool
  does**: prep removes nothing and changes no case, no stage's runs and no
  output; it adds cases and stages named by their content, restates a
  stage's request, and writes each folder and each file whole — beside, then
  renamed in — in the order of its steps, so a prep cut short leaves a
  project a second prep completes: a stage whose launch folder was never
  written is placed again, a folder whose files were cut between them reads
  `stale` and is prepared again. A test cuts prep after each of its steps
  and checks that a second prep completes it; the person delegated the
  decision.
- **A ledger of each prep's decisions in the project, as the earlier tool
  keeps one**: what prep decided is in the files it writes — each case's
  `case.json` its values, each stage's `stage.json` what it is made from,
  each folder's `prepared.json` its prepare — and each prep's plan and log
  in femkit's state folder.
- **Refusing a prep while a job holds one of its stages, as the earlier tool
  does**: the study's cases are independent; prep leaves that stage to the
  job that holds it and preps the rest, and says so in its outcome.
- **Picking which engines' jobs to prepare, as the earlier tool picks
  groups**: a study's cases and engines are independent (ADR 0016 decision
  4), and the whole plan is shown and asked before anything is written.

## Consequences

- The stage's own states `to_expand` and `to_make` become one, `to_prep`.
- A study's kept values are its own file, `computed/<study>/definitions.nc`.
- `job prepare` gains a prepare planned from a request in memory.
- The manual's chapters 5 and 7 teach prep; the templates' and the outcomes'
  next steps name it; a launch folder whose `maker.json` names `study mesh`
  is offered nothing for it — `job status` says femkit has no such
  operation (conventions § 2: no old name kept).
- `study expand`'s verb leaves the models domain; prep is the workflow
  domain's, calling the models domain's cases and the jobs domain's prepare.
