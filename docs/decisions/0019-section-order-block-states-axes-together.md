# ADR 0019: a project read in sections, one plain state per block, and axes that step together

**Role:** ADR

**Status:** accepted (2026-11-25); built, but the page's drawing of the
block words (plan § 4, G) and decisions 4–5 (after M9). Decision 3's formula
of a definition is a function in `definitions.py`
([ADR 0021](0021-definitions.md)). Decision 1's rank of an observable set,
and the last consequence, amended by
[ADR 0025](0025-one-engine-per-study-observables-after.md) (decision 4): an
observables part ranks after the studies it reads, and adding an observable
never prepares a solve again

**Authority:** the reasons and the alternatives only;
[`projects.md`](../contracts/projects.md) § 4 owns each part kind's section and
both orders, [`core.md`](../contracts/core.md) § 7 a state table's words,
[`web.md`](../contracts/web.md) § 7.6 the block words,
[`workflow.md`](../contracts/workflow.md) § 6 a stage's states,
[`models.md`](../contracts/models.md) § 5.1 the axes

## Context

The person, 2026-11-25, reading the workflow's design, asked what a study
does — "isn't study some specific measurement/calculation after the FEM
calculation solves the PDE in physics?" — and asked for the design to be
"logically clean, and user friendly such that it is easy to provide the
flexibility and completeness for multiphysics study/modeling".

A person reads a model from what it shares to what it computes: the values
and materials every part uses; the geometry and what fills each body; the
physics on its groups; the mesh; the study, an ordered list of steps, each
choosing what it solves, with its solver settings and its sweep; and what is
read from each solve. femkit's parts already follow that order, with two
choices of its own: a physics and a mesh recipe are written on group names
beside the component, not inside it ([ADR 0011](0011-project-structure.md)),
so one serves every component that promises those groups; and an observable
set is what is read from each solve — some of it computed by the engine
during the solve, so a changed set prepares the solve again
([`models.md`](../contracts/models.md) § 5.2).

A diagram of the parts and stages is read at a glance only if each block says
in one word where it stands — whether data it needs upstream is missing, has
changed, is being made, or is made — so a change upstream is seen downstream.
A sweep sometimes steps listed values together rather than crossing them —
each fabricated sample's gap with its measured tip radius. An engine may run
its solvers on different meshes, a field mapped between them (Elmer does
[E1]); femkit's studies today share one mesh.

## Decision

1. **A project read in sections.** Each part kind belongs to one section, in
   this order: Definitions (the project's definitions, materials), Component
   (components), Physics, Mesh (mesh recipes), Study (studies), Results
   (observable sets, analyses) — physics and mesh beside the component, as
   femkit keeps them. Everything a person reads lists parts by section: the
   description diagram, `project check`'s and `project graph`'s tables, the
   manual. A kind's rank — what a part is made from comes before it — stays
   the order of loading, checking and findings: an observable set is made
   before the study that reports it, and is shown under Results. Nothing a
   person writes changes.
2. **One plain state per block.** Every part and every stage the diagrams draw
   shows one word of a closed list, declared once in the page's vocabulary:
   *up to date*, *needs update*, *needs attention*, *waiting*, *running*,
   *failed* — its own state beside it. Each state table of a thing drawn as a
   block declares its states' words, and the page colors a block by its word
   alone. A stage waiting on a stage it takes from reads *waiting*, as the
   earlier tool's stage "waits for a run it builds on". A change upstream
   reads downstream at once: the flowchart is drawn from the cases the study
   makes now, and a stage not yet made reads `to_prep`, *needs update*, its
   next step `study prep` (ADR 0022).
3. **Axes that step together.** A study may name a group of axes that step
   together — the n-th case takes each one's n-th value — for values no
   formula relates: each fabricated sample's gap with its measured tip
   radius, three cases, not nine. A group's axes are of one class, since
   numerical convergence and a physical sweep are different studies
   ([`design.md`](../design.md)); values one formula relates are that
   formula, a function in `definitions.py`, and need no group.
4. **A step's own mesh, later.** Every step of a study shares its one mesh,
   sized where each physics needs it, each physics on its own groups. Whether
   a step may have a mesh of its own is decided when steps solved in turn are
   built (after M9). What a step takes from another would then be carried
   between meshes — a field transfer — stated on that hand-off, done by the
   engine, reported with what it lost, and proven by benchmark before it
   counts. Physics joined in one system by a coupling stay on one mesh.
5. **The coupling loop stated, later.** When repeated steps are built, the
   study states their method and relaxation beside the tolerance and the
   number of rounds it already states.

## Alternatives not chosen

- **Physics inside a component**: it would lose one physics serving every
  component that promises its groups.
- **Axes that step together for a formula's values**: the gap with the mesh
  in the gap at a tenth of it is one formula of the gap; two lists paired by
  position would state it twice, and pair them wrongly when one is
  reordered.
- **A continuation sweep**, each point starting from the last solution: it
  makes cases depend on each other, where a stage depends on its own inputs
  alone (the person, 2026-11-25). Revisited only if a nonlinear study needs
  it.
- **Ordering loading and checking by section**: a study would be loaded and
  checked before the observable sets it names.

## Consequences

- `layout.toml` gains each kind's `section` and the sections' order, the one
  home of both orders; an object takes its part's rank and section.
- The page's `GraphNode` gains `section` and `shows`; the page declaration
  gives each word its color; a state table of a thing drawn as a block
  declares `[shows]`, required by its binding.
- A stage observes whether the stages it takes from finished; a study gains
  `together`.
- The manual's chapters on writing each part and on studies follow the
  sections, say what a study is, and teach the formula before the group.
- Whether adding an observable should prepare a solve again is settled with
  the translators (plan § 4, M6).

## Sources

- [E1] Elmer, multiphysics — https://www.nic.funet.fi/index/elmer/webinar/02-ElmerWebinar-Multiphysics.pdf
