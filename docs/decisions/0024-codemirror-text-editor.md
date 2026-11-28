# ADR 0024: the page's text editor — CodeMirror 6, with help on hover and suggestions

**Role:** ADR

**Status:** accepted (2026-11-26); built

**Authority:** the reasons and the alternatives only;
[`web.md`](../contracts/web.md) § 9.2 owns the `TextEditor` element, § 8.3 a
node's keys, [`projects.md`](../contracts/projects.md) § 7 `project save`,
[`workflow.md`](../contracts/workflow.md) § 10 a change's impact

## Context

The page's text editor is for a project the person's own tools may not
reach: it writes exactly the text typed, femkit changing nothing the person
wrote ([ADR 0015](0015-the-persons-files.md)). What femkit already holds — each
finding's line and key, each key's sentence, unit, choices and section — is
worth most where the person types. A plain text box cannot mark a line or
show help; the page's read-only listing cannot be edited.

## Decision

1. **CodeMirror 6**, through a thin wrapper of the page's own, one element
   for viewing and editing: TOML for a part's file and Python for
   `definitions.py` and a geometry script, by the file's declared kind; each
   finding at its line and key; search, line numbers, folding, keyboard
   access; the editor's own undo while typing — femkit never undoes a saved
   file; its colours the page's tokens.
2. **Help on hover and suggestions as the person types** (the person,
   2026-11-26, "hover and suggestions"): a key's help on hover, and its allowed
   values and the keys the part may hold offered as completions — all from the
   node's keys, built by the one builder of the loader's fragments; the person
   chooses whether to take one, and the file is exactly what was typed.

## Alternatives not chosen

- **Monaco**, the editor of a large IDE: several megabytes with workers of its
  own, its strengths — a language server — needed nowhere in femkit.
- **A plain text box**: no line marked, no help.
- **Help on hover alone**: the person chose suggestions too.

## Consequences

- The CodeMirror packages are dependencies of the page, pinned in
  `frontend/package-lock.json` and installed by `web build` through femkit's
  own web environment.
- The server serves each node's keys (`web.md` § 8.3) and `project save` with
  its impact (`workflow.md` § 10).
