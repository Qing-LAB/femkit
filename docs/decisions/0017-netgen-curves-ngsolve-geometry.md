# ADR 0017: NGSolve's curved geometry — Netgen meshes it, in a step of its own in `ngsolve`

**Role:** ADR

**Status:** accepted (2026-11-25); it amends decision 1 of
[ADR 0012](0012-one-mesh-path.md) for a geometry order above 1 in NGSolve. The
`ngsolve` environment was rebuilt with OpenCASCADE that day (decision 5); the
route is built in plan § 4, X. Its "route" is a hand-over since
[ADR 0018](0018-one-graph-from-description-to-execution.md), declared as data
of its own and keyed by the mesh type it reads
([`geometry.md`](../contracts/geometry.md) § 8). Decision 4's one discrete
geometry holds again since
[ADR 0025](0025-one-engine-per-study-observables-after.md) (decision 1): a
study names no engine, and every engine that solves it takes the one mesh
its recipe makes. Netgen meshes where a mesh recipe names it, never by an
engine's default; whether Elmer can take Netgen's mesh is not measured

**Authority:** the reasons and the alternatives only;
[`geometry.md`](../contracts/geometry.md) § 8 owns the rules

## Context

The bowtie's field enhancement is set at its rounded metal tips: a mesh
whose faces cut straight across a curved surface changes the very geometry
the study measures. A mesh recipe's `order = 2` asks for elements bent onto
the true surface ([`geometry.md`](../contracts/geometry.md) § 6), and ADR 0012
left open whether each engine's route keeps it.

Measured on this workstation on 2026-11-25 (Gmsh 4.15.2, Elmer 26.2, NGSolve
and Netgen 6.2.2606):

- **Gmsh curves.** A unit disk meshed at order 2 has its area within 3.1e-6
  of π, relative (|a − π|/π); at order 1, 6.4e-3.
- **Elmer keeps it.** ElmerGrid converts Gmsh's MSH 2.2 with every name, and
  keeps the six-node triangles and three-node edges Elmer reads as curved.
- **NGSolve does not, from Gmsh.** Its own reader (`netgen.read_gmsh`) read
  the order-2 disk with no name and an area of 0. femkit's own layer, building
  NGSolve's mesh from Gmsh's nodes, kept every name, but the mesh is not
  curved — the disk's area off by 2.0e-3, relative — and asking NGSolve to curve it
  (`Mesh.Curve`) ends the process with a segmentation fault: NGSolve curves an
  element from the geometry behind it, and an outside mesh has none. A report
  on NGSolve's forum (NGSolve 6.2.2404) finds `Curve` wrong on imported meshes
  too.
- **NGSolve curves its own meshes well.** Measured for ADR 0012 on
  2026-11-23: `Mesh.Curve` at orders 1–4 on Netgen's own disk gave area errors
  of 1.4e-1, 9.0e-4, 1.1e-4 and 1.2e-6.
- **Netgen is its own library and Python module**, built inside the
  `ngsolve` environment from its own pinned source — but without CAD support
  (`USE_OCC = false`), so `netgen.occ` refuses to load and Netgen cannot read
  the geometry step's file.

## Decision

1. **When a case asks NGSolve for a geometry order above 1, Netgen meshes
   the geometry again, in a meshing step of its own run in the `ngsolve`
   environment**, from the geometry step's shapes and the same recipe; the
   solve loads that mesh, reads the same shapes again, and curves the mesh to
   the recipe's order from the true geometry (person, 2026-11-25: an
   engine-specific meshing task runs in that engine's environment, the
   framework's description supporting it). Measured that day, NGSolve and
   Netgen 6.2.2606 with OpenCASCADE 7.9.3: a unit disk meshed by Netgen in one
   process and saved, then loaded in another with its shapes read again and
   curved, has the same area as one meshed and curved in a single process —
   relative errors 6.8e-3, 1.1e-5 and 3.0e-6 at orders 1, 2 and 3 — from a
   BREP or a STEP file Gmsh wrote.
2. **Every meshing task runs in the environment that provides its mesher**
   (person, 2026-11-25), as each mesher's definition names it — Gmsh's in
   `gmsh`, Netgen's in `ngsolve` — never in one environment gathering every
   mesher.
3. **It is femkit's own route, declared as data** — NGSolve's route in the
   meshers' data, beside the route that hands it Gmsh's mesh — not a
   customization of the person's: it is the same for every person and every
   project.
4. **At geometry order 1, NGSolve keeps receiving Gmsh's mesh** through
   femkit's layer, so the two engines still solve one discrete geometry
   wherever no curvature is asked for.
5. **The `ngsolve` environment is rebuilt with OpenCASCADE**, by the person's
   choice of 2026-11-25, and was that day: Netgen's `USE_OCC`, and conda-forge's
   OpenCASCADE held to the 7.9 series, since Netgen 6.2.2606 tests the
   version's minor alone in places (`OCC_VERSION_MAJOR>=7 &&
   OCC_VERSION_MINOR>=6`) and would take its oldest paths on 8.0.

## Alternatives not chosen

- **Straight-sided elements in NGSolve.** Each curved surface would be a
  polygon in one engine and curved in the other, and the cross-check would
  compare different geometries without saying so.
- **femkit building curved elements for NGSolve from Gmsh's nodes.**
  Measured above: NGSolve takes the nodes but not the curvature, and curving
  needs a geometry behind the mesh that an outside mesh lacks.
- **Netgen as the mesher for both engines.** It would undo ADR 0012 for
  Elmer, whose route already keeps Gmsh's curved mesh, and the mesh recipe —
  size fields that grow from named groups, extruded layers — is written in
  Gmsh's terms.
- **Netgen in an environment of its own, or added to `gmsh`.** A second
  Netgen, either built again from the same pinned source or taken from another
  build whose mesh files need not match the solver's; the `ngsolve`
  environment already holds the Netgen NGSolve solves with.
- **The person's own `step` customization**
  ([`models.md`](../contracts/models.md) § 8). That kind is for a person's
  additions; a route every curved case in NGSolve needs belongs to femkit.

## Consequences

- **With curvature, the two engines solve different meshes of one
  geometry**, so their cross-check compares answers each converged on its own
  mesh ladder, not two solutions on one mesh; ADR 0012's reason for one mesh
  path holds for order 1. A study that compares the engines on a curved
  geometry carries a mesh-convergence axis for each.
- A recipe value with no counterpart in Netgen's options — how fast sizes grow
  from a group, say — is a match line, `approximated`
  ([`models.md`](../contracts/models.md) § 6.2), shown before anything runs.
- Measured 2026-11-25: Netgen 6.2.2606 builds against OpenCASCADE 7.9.3 and
  `netgen.occ` loads; it reads STEP, BREP and IGES, not `.xao` ("Valid formats
  are: step, stp, brep, iges"), and Gmsh's BREP and STEP keep no group names.
  So the geometry step also writes its shapes as BREP, and the route carries
  every group's name onto Netgen's shapes from the geometry step's
  `groups.json` — by each piece's centre and measure, measured that day to
  match one for one where Netgen's own order does not
  ([`geometry.md`](../contracts/geometry.md) § 8).
- Until the route is built, geometry order 2 in NGSolve is a match line,
  `unsupported`.
- The rebuild changed `ngsolve`'s install fingerprint: it was validated again
  that day, every check passing.
