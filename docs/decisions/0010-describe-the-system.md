# ADR 0010: the page describes the system; each part's detail is text

**Role:** ADR

**Status:** accepted (2026-11-23); decisions 1–3 superseded by
[ADR 0015](0015-the-persons-files.md)

**Authority:** the reasons and the alternatives only;
[`web.md`](../contracts/web.md) and [`projects.md`](../contracts/projects.md)
own the rules

## Context

The first web design gave the page a form for every field of every object, and
a palette that built shapes, sizes, materials and conditions value by value. It
grew to edit everything and was hard to use. A calculation has two kinds of
content that want different tools:

- **Structure**: which parts there are and how they connect — which material
  fills which body, which condition holds on which boundary, what a study
  varies, which observables it reports. A person reads and changes this best
  as a graph.
- **Detail**: what each part holds — a material's tables and sources, a
  condition's values, a mesh recipe's sizes, the geometry itself. A person
  writes this best as text they can annotate and copy, or as a script.

## Decision

1. **The page shows the structure and edits the relations.** Its graph shows
   the parts and their references; a wire drawn or cut is an edit of the
   reference.
   *Superseded 2026-11-24:* the page shows the relations and changes no file
   the person wrote ([ADR 0015](0015-the-persons-files.md)).
2. **Detail is the part's own text**, as its file holds it, comments and all —
   a TOML file, or the geometry's Python script. Beside it is the help: every
   key the part may hold, with its sentence, its unit or choices, whether it is
   required, and where it is defined; its findings are shown with it. Saving is
   one checked transaction, taken back by one undo.
   *Superseded 2026-11-24:* the detail is shown with its help and findings,
   never saved by femkit ([ADR 0015](0015-the-persons-files.md)).
3. **A new part starts from a template generated from its schema** and, where
   it has one, its formulation: required keys to fill, optional keys written as
   comments. No template text is written by hand, and no value is asked for
   field by field. Geometry is the exception: it is the person's work, and a
   component starts from one of femkit's example scripts with its contract
   ([ADR 0013](0013-geometry-scripts.md)).
   *Superseded 2026-11-24:* one set of hand-written project templates, their
   comments held equal to the schemas' help ([ADR
   0015](0015-the-persons-files.md)).
4. **Text is the one source.** The graph, the help, the templates, the findings
   and the page are derived from the files and the schemas; nothing is stored
   twice.

## Alternatives not chosen

- **A form for every field.** It grows with every part type, hides the file a
  person reads and copies, and is code written per kind, where text and its
  help is one mechanism for every kind.
- **A geometry editor in the page.** CAD is its own discipline; the geometry is
  a script ([ADR 0013](0013-geometry-scripts.md)).

## Consequences

- The page shrinks to a graph, each part's text with its help, and the views
  of runs, operations and documents; the web discipline
  ([`../process/conventions.md`](../process/conventions.md) § 2.1) is
  unchanged.
- The first page's per-field forms and value-by-value palette are removed.
