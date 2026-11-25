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
   with its benchmark set.
2. **Each engine environment declares its abilities as data**, per
   formulation: exact, approximated (with the approximation and its basis), or
   absent — per environment, since a CUDA environment can do what its CPU twin
   cannot.
3. **Matching gives a match report** with one line per element of a case, and
   nothing is prepared while a line is open.
4. **Decisions are data in the study**, bound to an environment: accepting an
   approximation names the line, the environment, the reason and what it
   accepted, so it goes stale when that changes.
5. **An ability counts once proven**, in that environment, by the
   formulation's benchmark set — cases an error would show in — and goes
   unproven when the environment, the translator or the mesher changes. Results
   resting on an accepted unproven line are `unverified`, and comparisons
   refuse them.
6. **A case is the model, the numerics and one axis point**; everything bound
   to an environment lives in the study and is recorded in each preparation's
   manifest.
7. **Customizations attach only at extension points each engine declares** —
   `overlay`, `hook`, `replace`, `step`, `custom-input` — as files the person owns,
   referenced by path and hash, each saying what it covers and whether it
   changes the physics.
8. **`custom-input` is a customization like the others**: the person's whole
   input, prepared, reviewed, run and recorded, its results marked
   `custom-input` and never compared.
9. **Meshers are declared, and each engine meshes with its own by default** —
   NGSolve with Netgen, Elmer with Gmsh. A study may share one mesh between
   engines, so that a difference between them is their discretization alone.
   *Superseded 2026-11-23:* one mesh path, Gmsh, for every engine
   ([ADR 0012](0012-one-mesh-path.md)).
10. **Observables are computed on the engine's own discretization**, inside its
   environment, and written to one result form.
11. **TOML files and web forms** built from the same schemas, as for the rest
   of femkit.
   *Amended 2026-11-23:* the page edits a part's text beside its help, not
   forms ([ADR 0010](0010-describe-the-system.md)).
   *Superseded 2026-11-24:* the person writes each part in their own editor;
   the page shows its text beside its help and changes no file of theirs
   ([ADR 0015](0015-the-persons-files.md)).

## Alternatives not chosen

- **One benchmark per formulation.** Laplace with φ = x is reproduced exactly
  by linear elements and does not depend on ε, so a translation that drops the
  permittivity would pass it and prove every ability it declares. A benchmark
  set proves each ability by a case its error would show in.
- **Decisions and customizations inside the case.** Every decision would give
  new case IDs and orphan the other environment's runs; a case is what is
  solved, and what an environment needs to solve it is bound beside it.

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
  carries executable text ([`web.md`](../contracts/web.md)); code is a
  file in the project, and its review is the consent.
  *Amended 2026-11-23:* a geometry script is written in the page as the text
  of its file, and run only under review
  ([ADR 0013](0013-geometry-scripts.md)).
  *Superseded 2026-11-24:* the person writes a geometry script in their own
  editor and the page only shows it; it still runs only under review
  ([ADR 0015](0015-the-persons-files.md)).

## Consequences

- Every limitation is visible before a run: a person sees each line the engine
  cannot do exactly and resolves it by name.
- Every observable says how faithful it is to the model — exact, approximated,
  customized, unverified or custom input — and comparisons read that.
- **Truncation is numerics, chosen per environment**: the model states the
  radiation condition, and a perfectly matched layer or an absorbing condition
  is each environment's approximation of it, shown in every comparison.
- **Scope:** one formulation per model. Coupled problems, eigenproblems and
  time-domain problems are formulations of their own when they come; symmetry
  and periodicity are conditions a formulation lists when it allows them.
- Adding a formulation adds its data file, its science document, its
  benchmark set, and one translator, parser and finalizers per engine that
  declares it.
- Adding an engine adds its abilities and extension points as data and its
  translators and parsers; nothing in the model, the study, the matching or
  the surfaces changes.
- The first formulation built end to end is `electrostatics`, proven by its
  benchmark set, before `maxwell` at a frequency (plan § 4, M6, M9).
