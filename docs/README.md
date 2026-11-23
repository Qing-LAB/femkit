# femkit documentation

**Role:** index
**Status:** current
**Authority:** the one list of documents, and the rules every document
follows; [`../PROJECT_CONTRACT.md`](../PROJECT_CONTRACT.md) says which
document wins

This is the one index. Every document in the repository has exactly one line
here (§ 5), added in the same change that adds, moves or removes it. A
document not listed here does not exist; review looks for files without a line
and lines without a file.

## 1. Structure

Documents are grouped by what a reader is working on; the header says what
kind of document each is.

| folder | holds |
|---|---|
| *(root)* | this index; [`design.md`](design.md) — mission, design values, scientific-data rules, settled choices |
| `contracts/` | one contract per package, named after it ([`contracts/framework.md`](contracts/framework.md) § 1) |
| `reference/` | pages generated from the schema models by `python -m femkit schema docs`; never edited by hand |
| `science/` | equations, assumptions, validity limits, citations, observable definitions |
| `decisions/` | ADRs, `NNNN-short-name.md`, one settled choice each |
| `process/` | how work is done: the order of work, design discipline, rules for code |
| `plans/` | one file, [`plans/plan.md`](plans/plan.md): everything not built yet |
| `assets/` | images the documents and the README show |

## 2. Rules for documents

- **D1 — Header.** Every document begins with `Role`, `Status` and
  `Authority`. `Role` is one of the table below; `Status` says what is true
  now (`current`, or `current; what is not built yet is marked so`);
  `Authority` names what the document decides, and nothing else.
- **D2 — Present tense.** A document says what is true now. What is not built
  is marked so in one sentence that names its section of the plan; planned
  behavior is never described as if it existed.
- **D3 — One plan.** Every open item lives in [`plans/plan.md`](plans/plan.md)
  and nowhere else. A contract states its rule and points to the plan for
  status. The plan shrinks as work lands and keeps no record of it.
- **D4 — No history in the repository.** A review finding is fixed in the
  contract and the code; what the next step needs goes into the plan. No dated
  review, handover, evidence or changelog document is added. Superseded text
  is deleted, not archived; version control keeps it.
- **D5 — One home per fact.** A document links the authority and may summarize
  it in one sentence; it never carries a second field list, state table,
  formula, default or validation rule that could drift
  ([`../PROJECT_CONTRACT.md`](../PROJECT_CONTRACT.md) § 1).
- **D6 — Links.** A link is a relative path to the file. In a document written
  by hand, a section is named in plain text (`§ 4.2`), never as a `#` anchor,
  so a heading can change without breaking links; a generated reference page
  links its own headings, since one generator writes both.
- **D7 — Upstream is cited, not copied.** A document links upstream
  documentation, at a release where it matters, instead of restating it.

| role | contains | never contains |
|---|---|---|
| root contract | which document wins, the organizing rule, the zones | domain rules |
| index | this file: the document list and the document rules | rules for code |
| principle | durable reasons and design values | implementation status |
| contract | current interfaces, invariants, schemas, refusals; what is not built yet, marked so | work lists and dates |
| scientific background | equations, assumptions, validity limits, citations, observable definitions | software status |
| reference | generated from the schema models | promises, or text written by hand |
| process | how work is done, and the rules a review checks | rules of a single package |
| guide | ordered instructions over current behavior | rules a contract does not state |
| example | what an example shows, and which contract it follows | rules of its own |
| ADR | one decision: context, alternatives, reason, consequences | living interface documentation |
| plan | unfinished work, its order and its acceptance | claims that planned behavior exists; history |

## 3. How documents are written

- **E1 — Structure first, never append.** Before a document is changed, map
  its sections and its siblings', and put the new content where it belongs. A
  merge rewrites the combined content into one structure; it is never a
  concatenation.
- **E2 — Diagrams where they explain.** Ownership, data flow, state machines
  and sequences get a Mermaid diagram (GitHub renders it). A diagram never
  carries a field list a schema or table owns.
- **E3 — Plain language, full rigor.** Jargon is translated into plain words
  and concrete scenarios ("when you run X, Y happens"), and nothing is lost:
  every constraint, number, edge case and reason survives. A coined term is
  used only after the sentence that defines it.
- **E4 — Scientific claims carry their basis.** An equation defines every
  symbol and unit convention near its first use. A default, threshold or
  tolerance states where it comes from: a derivation, a citation or a
  measurement. A merge keeps that basis and fills it in where it is thin.

## 4. Moving or merging a document

Moving or merging a document is a review, not a file move:

1. Read it against the current code, and fix what has drifted or delete it.
2. Map its structure and its new siblings' (E1); decide the shape before
   writing.
3. Merge overlaps into one home instead of carrying duplicates (D5).
4. Move open work into the plan (D3).
5. Give it its header (D1) and its line in § 5, in the same change.
6. Repoint every inbound reference — documents, code comments, tests,
   generators — in the same change, each found with `grep`.

## 5. Index

### At the repository root

- [`../README.md`](../README.md) — what femkit is, and the first commands.
- [`../PROJECT_CONTRACT.md`](../PROJECT_CONTRACT.md) — which document wins, the
  organizing rule, and where each top-level entry belongs.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — where a contributor starts.
- [`../SECURITY.md`](../SECURITY.md) — the trust boundary, and how to report a
  problem.
- [`../examples/bowtie_nanogap/README.md`](../examples/bowtie_nanogap/README.md)
  — the first application model, not yet written.

### Principles and process

- [`design.md`](design.md) — why femkit exists, its design values, the rules
  every stored scientific quantity follows, and the settled choices.
- [`process/conventions.md`](process/conventions.md) — the order of work,
  design discipline, rules for code and configuration, working practice.

### Contracts

- [`contracts/framework.md`](contracts/framework.md) — packages and layers,
  which contract governs each concern, state machines, requests and outcomes.
- [`contracts/core.md`](contracts/core.md) — the building blocks every package
  uses: schema, directories, persistence, locks, event logs, processes, errors.
- [`contracts/api.md`](contracts/api.md) — how an operation is declared, and
  how the command line and the web serve it.
- [`contracts/definitions.md`](contracts/definitions.md) — what femkit ships:
  the control environment, engine environments, manager and scheduler kinds.
- [`contracts/config.md`](contracts/config.md) — where configuration lives,
  and what a machine record is.
- [`contracts/envs.md`](contracts/envs.md) — how an environment is installed,
  validated and entered, and the install script.
- [`contracts/models.md`](contracts/models.md) — how a calculation is described
  once, matched against an environment's declared and proven abilities,
  decided on, customized, prepared and reduced; not built yet (plan § 3).
- [`contracts/jobs.md`](contracts/jobs.md) — machine records and the probe;
  how a job will be prepared and run.
- [`contracts/testing.md`](contracts/testing.md) — test tiers, isolation, what
  earns a test, and the runner.

### Reference (generated)

- [`reference/definitions.md`](reference/definitions.md) — every field of the
  shipped definition files.
- [`reference/config.md`](reference/config.md) — every field of `config.toml`.
- [`reference/machines.md`](reference/machines.md) — every field of a machine
  record.
- [`reference/models.md`](reference/models.md) — every field of `model.toml` and
  `study.toml`.

### Science

- [`science/electrostatics.md`](science/electrostatics.md) — the electrostatic
  potential: its terms and symbols, equation, conditions and their signs, what
  each dimension means, derived quantities.
- [`science/electromagnetics.md`](science/electromagnetics.md) — the
  frequency-domain Maxwell problem, its validation ladder, and what a
  converged adaptive result requires.

### Decisions

- [`decisions/0001-project-name-femkit.md`](decisions/0001-project-name-femkit.md)
  — the name femkit, everywhere.
- [`decisions/0002-paraview-visualization-boundary.md`](decisions/0002-paraview-visualization-boundary.md)
  — interactive field rendering is ParaView's; femkit exports and reduces.
- [`decisions/0003-ngsolve-stability-first-baseline.md`](decisions/0003-ngsolve-stability-first-baseline.md)
  — the NGSolve release and toolchain pinned, and why.
- [`decisions/0004-elmer-stability-first-baseline.md`](decisions/0004-elmer-stability-first-baseline.md)
  — the Elmer release and toolchain pinned, and why.
- [`decisions/0005-cuda-environments.md`](decisions/0005-cuda-environments.md)
  — GPU builds are separate `-cuda` environments, built on request.
- [`decisions/0006-toolchain-first.md`](decisions/0006-toolchain-first.md)
  — each environment declares its toolchain, proven before any source is
  fetched.
- [`decisions/0007-cmake-default-generator.md`](decisions/0007-cmake-default-generator.md)
  — femkit names no CMake generator; each project's default applies.
- [`decisions/0008-one-model-declared-abilities.md`](decisions/0008-one-model-declared-abilities.md)
  — one model, translated per engine through declared abilities, with every
  limitation shown, decided or customized.
- [`decisions/0009-web-front-end.md`](decisions/0009-web-front-end.md)
  — the web front end is a React application with React Flow, built and
  shipped in the package.

### Plan

- [`plans/plan.md`](plans/plan.md) — everything not built yet: the milestones,
  framework debts, and model preparation and analysis.
