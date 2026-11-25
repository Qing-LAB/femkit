# ADR 0015: the person's files are theirs; one set of templates starts them

**Role:** ADR

**Status:** accepted (2026-11-24); it supersedes decisions 1–3 of
[ADR 0010](0010-describe-the-system.md), the transaction and undo of
decision 5 of [ADR 0011](0011-project-structure.md), the two amendments of
[ADR 0008](0008-one-model-declared-abilities.md) that have the page edit a
part's text or write a geometry script, and the request carrying a script's
text in [ADR 0013](0013-geometry-scripts.md)'s consequences

**Authority:** the reasons and the alternatives only;
[`projects.md`](../contracts/projects.md) § 7 owns the rules

## Context

The page was to edit a project's parts: wires drawn as references, text saved
as one checked transaction, taken back by one undo. Each new part was to start
from a template generated from its schema, a component from one of a few
example scripts; whole example projects, formulation benchmarks and the tests'
projects were each kept apart, and the person's own starting points were to
live in a `shared/` folder. That is several sets of starting text, each able
to drift from the others, and a writer of the person's files that has to be
safe against their editor.

## Decision

1. **femkit changes no file the person wrote.** The person writes every part
   in their own editor. femkit reads it, checks it and says what is wrong and
   what would be right; no command sets, writes, renames or undoes a part.
   `config set` stays: it sets femkit's own settings through the one API.
2. **femkit writes only a template the person asks for, and its own
   outputs** — cases, runs, results.
3. **One set of templates.** femkit ships its starting points in
   `femkit/data/templates/`: the settings file's, and its project templates,
   each a whole, working project written by hand. They are femkit's examples,
   its formulations' benchmarks and its tests' projects; nothing else holds a
   project. Each passes `project check` in a test, and the comment above each
   key is that key's help as its schema states it, held so by a test.
4. **A new project is a copy.** `project new NAME` copies a template, or one
   of the person's own projects, whole; the person's starting points are their
   projects, with no folder of their own.

## Alternatives not chosen

- **Editing in the page or by command, with undo.** It makes femkit a second
  editor of files the person's editor owns, and needs transactions, conflict
  checks and history to be safe. Checking what they wrote needs none of it.
- **A template generated per part kind.** It shows every key, but it is a
  second set beside the projects that work, and the help it would carry is
  already on the reference pages, the page and each finding.
- **A `shared/` folder for the person's own pieces.** A copy from any project
  does the same with no second place, and a project never points outside its
  own folder.

## Consequences

- The page shows the structure, each part's text, its help and its findings,
  and the templates to copy; it writes nothing of the person's.
- The benchmarks' and the tests' projects move into the templates when step D
  rewrites them in the parts' formats (plan § 4, D).
