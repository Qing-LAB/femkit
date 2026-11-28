# ADR 0020: each engine its own stages

**Role:** ADR

**Status:** accepted (2026-11-25), built; it amends
[ADR 0018](0018-one-graph-from-description-to-execution.md)'s workflow, where
a geometry two environments' jobs need was a stage of each, and
[ADR 0012](0012-one-mesh-path.md) and
[ADR 0017](0017-netgen-curves-ngsolve-geometry.md) where they say the two
engines solve one mesh. Decision 1 amended by
[ADR 0025](0025-one-engine-per-study-observables-after.md) (decision 1): a
geometry and a mesh stage are their study's and hold nothing of an engine —
a study names no engine, so every engine that solves it solves from the
same ones — and a study turned to GPUs, or to another engine, reuses them;
a solve stage is keyed by the engine chosen and serves the environment it
resolves to

**Authority:** the reasons and the alternatives only;
[`workflow.md`](../contracts/workflow.md) §§ 3–5 own the rule

## Context

A study solving in Elmer and NGSolve has, for each case, a geometry and a
mesh both engines could use: Gmsh meshes the geometry for both at geometry
order 1, and each engine's solve takes the mesh through its own hand-over.
`workflow.md` § 5 put such a stage in both engines' meshing jobs, "the job
that reaches it first makes it". As built in milestone 4, the shipped
templates' `study mesh` then wrote jobs whose first part `job launch` refused:
a calculation folder is prepared with one launch folder, stating that one
job's wall and resources ([`jobs.md`](../contracts/jobs.md) §§ 1.2, 3, 5).

Asked whether each stage should be made once, in the first engine's job, the
other engine's meshes waiting for it, or once per engine, the person,
2026-11-25: "why not keep engine copy by themselves? first, some stages may
need engine specific settings, so it makes no sense not to isolate those
special instancetation of such stage, second, the cost isn't really much,
and it's much cleaner to maintain".

## Decision

1. **A stage serves one environment.** The environment it serves is part of
   what it is made from, so its identity holds it: each engine has its own
   geometry and its own mesh for each case, and no stage is shared between
   two engines.
2. **Each engine's meshing job holds its own stages alone**, with that
   engine's resources, so the two jobs share nothing and run at once.
3. **Within one engine**, cases whose geometry or mesh content is the same
   share one stage, as before — a wavelength sweep's cases one geometry and
   one mesh.

## Alternatives not chosen

- **One stage for both engines, in the first engine's job**, the other
  engine's meshes waiting for it: one file for both engines to mesh and
  compare on, but a setting one engine needs in a geometry or a mesh would
  reach the other, and the two jobs would depend on each other.

## Consequences

- Each engine's geometry and mesh are built and checked once each: the cost
  is one more geometry and one more mesh per case and engine.
- Whether two engines' copies built from the same script and inputs are the
  same files is not measured; each copy's check records every group's
  measure, so an analysis compares the engines on what each meshed.
