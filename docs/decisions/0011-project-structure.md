# ADR 0011: a project is parts in a fixed tree, reached through one door

**Role:** ADR

**Status:** accepted (2026-11-23); decision 5's transactions and undo
superseded by [ADR 0015](0015-the-persons-files.md); decisions 2–3's
observable sets amended by
[ADR 0025](0025-one-engine-per-study-observables-after.md) (decision 4): an
observables part, a folder with its script, reads studies, and no study
pairs it

**Authority:** the reasons and the alternatives only;
[`projects.md`](../contracts/projects.md) owns the rules

## Context

A project was one file, `model.toml`, holding the physics, the geometry's
shapes, the regions and the materials inline, with studies beside it. Several
modules built paths into a project and opened its files themselves, so the
graph and the edits could read one project differently. The bowtie study needs
more than one file can hold well: a parameterized geometry, materials with
tabulated data from cited sources, more than one physics over one geometry
later, and observables that several studies share.

## Decision

1. **A projects root.** One folder, set once in `config.toml`, holds the
   person's material library and their projects. The page lists it; a command
   names a project from it, or by the folder it runs in.
2. **A project is parts, each in its own file in a fixed tree**, side by side
   as a model is read: the project file (shared parameters; it names
   its components and studies); components; physics; mesh recipes; observable
   sets; studies; analyses; the project's materials; and what runs write. Any
   kind's parts may be grouped in folders; a name is a path, and a folder only
   groups.
3. **A component is one geometry**: its script and the contract that wraps it,
   which promises named groups, and its material assignment. A physics, a mesh
   recipe and an observable set name groups, never a component, so each serves
   every component that promises what it names; a study pairs them, and the
   pairing is checked from the contracts before anything runs. Analyses read
   studies' results. A command names a project as a whole.
4. **One layout, declared as data**: each part kind's folder, file, schema,
   writer, and whether it moves with the project, is regenerated, or stays
   local. The graph, the checks and the page read it.
5. **One door.** The `projects` package is the only code that forms a path in a
   project or reads or writes its files. Each part loads on its own, so a broken
   file is a finding on that part. Every change of the project's data is one
   transaction: it may
   create, change, move or delete files, holds the project's lock, checks
   nothing was edited by hand since it was planned, writes all or nothing, and
   is one undo step.
   *Superseded 2026-11-24:* femkit changes no file the person wrote, so no
   transaction or undo of theirs exists; the one door remains ([ADR
   0015](0015-the-persons-files.md)).

## Alternatives not chosen

- **One file per project.** It cannot hold scripts and tables well, and two
  physics over one geometry would state its material assignment twice.
- **Every object in a file of its own** (each condition, each region). A
  condition is a few lines and is structure; parts are cut where a concern
  changes, not per object.
- **Physics, mesh recipes and observable sets inside their component's
  folder.** It would make a mismatch impossible, but a physics shared by a
  sharp-tipped bowtie, a rounded one and a 2-D cross-section would be copied
  three times; the contract's promised groups make the mismatch a finding the
  moment a study pairs them.
- **A projects tree by topic** (one folder per kind of calculation). femkit's
  calculations are cut by part, and a study is already the unit of a
  calculation.

## Consequences

- The model's schema and its addresses change; benchmarks become projects in
  this tree.
- Jobs leave the study's folder for the project's run folders, designed with
  execution.
- `web.projects` becomes `paths.projects`, read by every surface.
- Every existing reader and writer of project files moves onto the door, held
  by design and by each milestone's review of the source.
