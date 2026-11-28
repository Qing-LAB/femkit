# ADR 0013: geometry is the person's Gmsh script, wrapped by a contract

**Role:** ADR

**Status:** accepted (2026-11-23); it
amends [`web.md`](../contracts/web.md) §§ 1–2 and
[`models.md`](../contracts/models.md) § 8.4. Decision 1's "it does not mesh"
is amended by [ADR 0018](0018-one-graph-from-description-to-execution.md)
decision 3: a script may write a mesh its contract declares, which the mesh
stage passes through (the person, 2026-11-25)

**Authority:** the reasons and the alternatives only;
[`geometry.md`](../contracts/geometry.md) owns the rules

## Context

The model held its own shape kinds — rectangle, disk, box, union and the rest —
each one every mesher had to translate. The bowtie needs a construction with
its gap and lengths as swept parameters, and named edges and points for mesh
sizes at the tips. A script does both, and a rectangle is a few lines of it.
Until now no request could carry code, and a person's code ran only inside a
job they reviewed.

## Decision

1. **The geometry is a Python script with Gmsh, the person's**: a full, working
   script, written as they like, importing what they like; femkit never
   generates, parses or rewrites it. It builds the exact shapes and names the
   groups the project needs. It does not mesh: meshing is femkit's next step.
2. **A contract wraps it**: the parameters and files it needs, checked before
   it runs; the geometry file and the named groups it promises, checked after.
   Everything downstream names only promised groups, so a study's pairing is
   checked from the contracts before anything runs.
3. **The pipeline is three steps, each wrapped by a contract**: geometry (the
   script), mesh (femkit's step, with a mesh recipe), solve (the engine's run).
   Each runs in a run folder, as a run of its own, designed with execution;
   saving a script never runs it.
4. **The model's own shape kinds are removed.** femkit ships a few example
   scripts with their contracts and one guide; geometry is the person's work.
5. **Importing a CAD file is a script whose input is the file**, under the same
   contract; a standard import script comes with it, later.

## Alternatives not chosen

- **Shape kinds in the model.** Every mesher translates each; a script is more
  flexible and is the person's own.
- **CadQuery or build123d.** CAD-first libraries that hand their geometry to
  Gmsh to mesh and name it: a second tool where one does both. A person may
  still use them inside their script; the contract is what femkit reads.
- **Scripts with unlimited freedom and no contract.** Nothing downstream could
  rely on what a script produces, and nothing could be checked before it ran.
- **Netgen's Python geometry.** Not available in femkit's NGSolve build, and it
  would tie geometry to one engine.
- **Importing CAD files now.** No first benchmark needs it.

## Consequences

- A request may now carry a script's text as the content of a file; it is never
  run outside a pipeline's first step, in a run folder.
  *Superseded 2026-11-24:* no request carries a script's text; the person
  writes the script in their own editor, and it still runs only as a
  pipeline's first step ([ADR 0015](0015-the-persons-files.md)).
- With sign-in, everyone on the allow-list can run code as the server's owner
  through a reviewed run — as they already can through a reviewed job; the
  allow-list names only people trusted that far ([`web.md`](../contracts/web.md) § 5).
- The benchmarks are rewritten as example scripts with their contracts.
