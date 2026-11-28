# ADR 0018: one graph from description to execution, a workflow layer, and a text editor on the page

**Role:** ADR

**Status:** accepted (2026-11-25); it amends decision 1 of
[ADR 0015](0015-the-persons-files.md) for the page's text editor alone, and
decision 1 of [ADR 0013](0013-geometry-scripts.md) for a script that declares
its own mesh (decision 3); amended by
[ADR 0020](0020-each-engine-its-own-stages.md): each engine its own stages;
being built in plan § 4, X and G. Decision 4's translation is folder
writing since [ADR 0025](0025-one-engine-per-study-observables-after.md)
(decision 10), "translator" naming an output translator alone

**Authority:** the reasons and the alternatives only;
[`workflow.md`](../contracts/workflow.md) owns the stages, the workflow graph
and the translation, [`projects.md`](../contracts/projects.md) § 2 every path
in a project, [`jobs.md`](../contracts/jobs.md) the execution,
[`web.md`](../contracts/web.md) the page

## Context

By the end of X's design, the pipeline lived in three documents: the
project's run folders in `projects.md`, the stages and their mesher in
`geometry.md` §§ 4, 5 and 8, the groups and sequences in `jobs.md` § 1.2. Three
reviews of the run design found the same fact stated in two or three places
and stated differently. The page drew the description alone, and nothing said
how a study's stages and runs would be shown. ADR 0015 kept the page from
writing any file the person wrote.

The person, 2026-11-25:

- asked for a consolidated design of the project's structure, the workflow
  and the job execution, each a contract that can be checked against the code,
  built as clean layers;
- asked that the page show all of it as a flowchart, and that the same
  description carry enough context to become each engine's execution scripts;
- asked that each node of the flowchart open for editing as text — "many of
  these may run remotely, so access to the files and contents may not be
  accessible to local tools" — with no structured editing of a geometry or
  anything else unless a specific need is discussed first;
- set femkit's scope: "our main job is to provide the support in designing of
  the structure, the configuration file, data structure, and APIs to support
  the overall workflow and logical relation between all the calculation
  components. We're not trying to replace tools that eventually does the
  actual job";
- set that a command-line flag is femkit's own option, never a calculation's
  value;
- asked that a mesh be able to pass straight through when the person's
  script makes it.

## Decision

1. **Three layers, one contract each**: the project's structure
   (`projects.md`, `femkit/projects/`), the workflow (`workflow.md`, a new
   `femkit/workflow/` between `models` and `results`), the execution
   (`jobs.md`, `femkit/jobs/`, which knows nothing of geometry, meshes or
   projects). Each contract names the module and function of each rule.
2. **One graph shape, three views**: the description the person writes, the
   workflow derived from it per study, and its execution — one document
   shape, drawn by one element; the one relation between the views is
   declared in it — a stage's `made_from`, the parts and stages it is made
   from — and the page selects across views by it alone.
3. **Stages and artifacts are declared as data**: each stage kind's typed
   inputs and outputs, environment, program template, check and
   one-process rule; each artifact type's file, format and how it is opened. A
   mesher fills the mesh stage's slots; the pass-through is one more mesher.
   "Stage" is the earlier tool's word, since "step" already names a study's
   step of physics.
4. **Translation by listed context**: a stage becomes a calculation folder
   from its kind's template and the context its kind lists; nothing else
   reaches it.
5. **femkit works at the higher level**: each stage's work is a tool's,
   wrapped by a contract; a part of femkit that would do a tool's work is
   raised with the person first.
6. **A text editor on the page, and the impact of a save**: a node opens its
   file as plain text; saving writes exactly the text typed, refused when the
   file changed since it was opened. It is the one write femkit makes to a
   file the person wrote. No structured editing. Before it writes, the save
   shows its impact — what the new text breaks, which promise it breaks, what
   it makes impossible, which stages it makes anew — by a closed table of
   named comparisons, each its owner's and each reading only declared inputs
   (the person, 2026-11-25: "there better be some agreed contract that
   defines them, and the parameter better be explicit rather than
   implicit").
7. **A flag is femkit's own option** ([`api.md`](../contracts/api.md) § 4).
8. **One name each**: a job running several calculation folders is a
   **batch** (the person, 2026-11-25), since "group" names a geometry's
   named group; the earlier tool's "group" is femkit's batch; a diagram's box
   is a `Box`.

## Alternatives not chosen

- **Keeping the pipeline in `geometry.md` and the run folders split.** The
  reviews' drift came from it.
- **A second editor of the person's files with history and undo** (ADR 0015's
  reason): the save is plain text, refused on a file changed since it was
  opened; the person's own tools keep the history.
- **A form per key, or a geometry editor on the page.** Femkit's scope
  (decision 5); a specific need is discussed first.
- **Flags that set a study's resources or a mesher.** They would write past
  the person's own files (decision 7).

## Consequences

- `geometry.md` keeps the geometry script and its contract, the recipes, the
  six places, the hand-over to each engine, importing and the file format;
  the stages move to `workflow.md`.
- `framework.md` gains the `workflow` package and layer; `models` keeps the
  description and its graph; `study mesh` moves to `workflow` (since ADR
  0022, `study prep`, the workflow domain's).
- `jobs.md` gains one writer of a calculation folder, a declared state of a
  calculation folder and a declared catalogue of its files.
- `web.md`: the three diagrams and how they relate (§ 2.4), one `Graph`
  document (§ 7.6); the Runs workspace draws the workflow graph; a node opens
  the text editor. The save, `project save`, writes through the door and is
  declared in `workflow`, whose impact (`workflow.md` § 10) is its plan.
- The plan: X builds the workflow layer and the execution; G, the page's
  views of them and the editor.
