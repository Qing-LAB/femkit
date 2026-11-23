# ADR 0008: one model, translated per engine through declared abilities

**Role:** ADR

**Status:** accepted (2026-11-22)

**Authority:** the reasons and the alternatives only;
[`models.md`](../contracts/models.md) owns the rules

## Context

femkit solves with two engines whose abilities differ: Elmer and NGSolve do not
offer the same boundary treatments, element families or solvers, and some
problems cannot be carried from one to the other unchanged. The scientific use
needs both: one model solved by two independent engines is a cross-check only
when both solve the same stated problem, and a person must be able to finish a
job the translation cannot fully express — with their own options, code or
input — without losing track of what was solved.

## Decision

1. **A person describes physics, in a closed list of formulations.** Each
   formulation is solver-neutral, has its science document and enters femkit
   with its analytic benchmark.
2. **Each engine declares its abilities as data**, per formulation: exact,
   approximated (with the approximation and its basis), or absent.
3. **Matching gives a fit report** with one line per element of a case, and
   nothing is prepared while a line is open.
4. **Decisions are data in the study**: accepting an approximation names the
   line, the engine and the reason.
5. **Customizations attach only at extension points each engine declares** —
   overlay, hook, replace, step, custom input — as files the person owns,
   referenced by path and hash, each saying what it covers and whether it
   changes the physics.
6. **Custom input is a case**, prepared, reviewed, run and recorded like any
   other, and marked as not translated from the model.
7. **Meshers are declared, and each engine meshes with its own by default** —
   NGSolve with Netgen, Elmer with Gmsh. A study may share one mesh between
   engines, so that a difference between them is their discretization alone.
8. **Observables are computed on the engine's own discretization**, inside its
   environment, and written to one result form.
9. **TOML files and web forms** built from the same schemas, as for the rest
   of femkit.

## Alternatives not chosen

- **Free-form weak forms** as the problem language. NGSolve can take any
  variational form; Elmer largely cannot, so a model written that way would
  have one engine and no cross-check. Formulations keep the problem
  solver-neutral; a weak form NGSolve alone can solve remains possible as a
  customization, marked as single-engine.
- **Translate and hope**: substitute the nearest thing an engine has and
  carry on. It contradicts [`../design.md`](../design.md) — what an engine
  cannot do is refused, never approximated silently — and a result would not
  say what was solved.
- **Editing generated input by hand.** Edits are lost on the next
  preparation, are invisible in the record, and make generated input the
  source of intent. Customizations at declared points keep the translation as
  evidence and the person's change as a reviewed file.
- **One shared mesher by default.** NGSolve's environment holds Netgen and
  Elmer's holds Gmsh; Netgen's curved, high-order meshes are part of what
  NGSolve does well; and every comparison is made on declared probes, lines,
  planes and regions whatever the meshes. A shared mesh stays available for
  the case where a difference between engines must be traced to their
  discretizations rather than their meshers.
- **Computing every observable in femkit from exported fields.** Exporting an
  H(curl) field to mesh nodes loses accuracy before the reduction starts;
  values come from the engine's own basis functions, and femkit compares on
  declared probes across meshes.
- **A decision file per engine.** Decisions in the study keep one model
  preparable for several engines, each with its own decisions, in one place
  that names the study they belong to.
- **Customization code typed into the web interface.** A request field never
  carries executable text ([`api.md`](../contracts/api.md) § 5); code is a
  file in the calculation folder, and its review is the consent.

## Consequences

- Every limitation is visible before a run: a person sees each line the engine
  cannot do exactly and resolves it by name.
- Every result says how faithful it is to the model — exact, approximated,
  customized or custom input — and comparisons read that.
- Adding a formulation adds its data file, its science document, its
  benchmark, and one translator and parser per engine that declares it.
- Adding an engine adds its abilities and extension points as data and its
  translators and parsers; nothing in the model, the study, the matching or
  the surfaces changes.
- The first formulation built end to end is `electrostatics`, on the Laplace
  benchmark, before `maxwell-frequency` (plan § 6).
