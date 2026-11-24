# ADR 0012: one mesh path — Gmsh, in an environment of its own

**Role:** ADR

**Status:** accepted (2026-11-23); it would
supersede decision 9 of [ADR 0008](0008-one-model-declared-abilities.md)

**Authority:** the reasons and the alternatives only;
[`geometry.md`](../contracts/geometry.md) owns the rules

## Context

ADR 0008 let each engine mesh with its own mesher — Elmer with Gmsh, NGSolve
with Netgen — and a study share one mesher when it chose. Geometry is now a
script written with Gmsh's interface ([ADR 0013](0013-geometry-scripts.md)).
Measured on this workstation on 2026-11-23: Netgen in femkit's NGSolve build
cannot read CAD geometry ("Netgen was not built with Opencascade support");
NGSolve's own reader of a Gmsh mesh read both bodies' elements of a two-body
test but only the first body's name. Gmsh's command line is installed in the
`elmer` environment; its Python interface is in no environment.

## Decision

1. **Every mesh is made by Gmsh**, in femkit's mesh step — the second step of
   the pipeline, after the person's geometry script — from the geometry and a
   mesh recipe, in an environment of its own holding Gmsh with its Python
   interface — proposed as `gmsh`, decided with execution (plan § 3, X).
   Neither engine owns the mesh.
2. **femkit hands each engine its mesh.** How — the format written, the
   formats each engine reads, the conversion step and what each keeps (region
   names, geometry order) — is declared as data. NGSolve receives the mesh
   through femkit's own layer, with its region names proven by a test; it never
   deals with file formats itself.
3. **A mesh depends on the geometry and the recipe alone**, so cases that
   differ only in a wavelength share one mesh; where it is kept is designed
   with execution.

## Alternatives not chosen

- **Each engine's own mesher** (ADR 0008 decision 9). Netgen cannot read the
  script's geometry in this build; two meshers would also mesh one geometry
  differently, and a comparison between the engines would no longer compare
  one discrete geometry.
- **Rebuilding NGSolve with Netgen's CAD support.** An environment change for
  one engine, which still leaves two mesh paths to prove.

## Consequences

- Netgen curves its meshes to geometry order up to 4 in its own geometry
  (measured, `femkit/data/meshers/netgen.toml`). Which orders the Gmsh route
  keeps is not measured (`gmsh.toml` states 1 and 2 as expected), nor whether
  femkit's layer can hand NGSolve curved second-order elements — a cost to weigh
  for the bowtie's curved metal surfaces. A case that asks for more than the
  route keeps is a match line.
- A proof is keyed to the mesh path's environment, not to a mesher per engine;
  no proof exists yet, so none is redone.
- `femkit/data/meshers/netgen.toml`, a study's per-environment mesher binding
  and `formulation verify --mesher` go; `gmsh.toml` describes the one path.
- The mesh step's environment is an environment change, made only on the person's
  approval.
