# ADR 0002: outsource field visualization to ParaView

**Role:** ADR

**Status:** accepted; what femkit owns amended by
[ADR 0025](0025-one-engine-per-study-observables-after.md) (decisions 4–5):
a case's probes, reductions, profiles and integrals are the person's
observables functions, which femkit runs after the solve and whose results
it keeps; and (decision 8): femkit checks that the files an engine declares
are there, and reads no field's values

**Authority:** boundary between femkit's result preparation and interactive
field visualization

## Decision

FEM field visualization is outside femkit's product boundary.
Elmer and NGSolve backends will retain or export standard ParaView-readable
artifacts such as VTU/PVD, together with region names, units, coordinate-frame
metadata, and provenance. Users open those artifacts in ParaView when spatial
inspection is needed.

femkit does not embed VTK/PyVista, run a visualization service,
or develop a browser-based volume/surface renderer.

## What femkit owns

- checking that expected field artifacts were produced and are readable;
  *Amended 2026-11-27:* that the files its engine declares are there — femkit
  reads no field's values, which are the engine's and the person's script's
  ([ADR 0025](0025-one-engine-per-study-observables-after.md) decision 8);
- preserving their relationship to the case and attempt;
- recording field names, components, complex-value convention, units, mesh,
  coordinate system, and named domains;
- extracting reproducible numerical probes, reductions, profiles, integrals,
  convergence tables, and comparison metrics;
  *Amended 2026-11-27:* a case's probes, reductions, profiles and integrals
  are the person's observables functions, femkit running them and keeping
  their results; convergence tables and comparisons are analyses
  ([ADR 0025](0025-one-engine-per-study-observables-after.md) decisions 4–5);
- emitting small CSV/JSON tables and analysis reports;
- generating a ParaView state or helper script later only if it can remain a
  simple export rather than becoming an internal visualization subsystem.

## Consequences

The host environment does not need VTK or PyVista. Backend environments may
write VTK-family files, but the web/CLI process does not load them for rendering.
Screenshots are supporting evidence, not canonical numerical results. The
canonical result remains a structured analysis record derived from retained raw
solver output.

