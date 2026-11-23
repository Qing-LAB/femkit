# ADR 0009: the web front end is a React application, built and shipped in the package

**Role:** ADR

**Status:** accepted (2026-11-22)

**Authority:** the reasons and the alternatives only;
[`api.md`](../contracts/api.md) § 5 owns the rules

## Context

A model is a graph: regions refer to shapes, conditions to regions, materials to
domains, observables to quantities the formulation derives
([`models.md`](../contracts/models.md) § 11.2). People read such structure
fastest as nodes and wires, the way node editors for image pipelines present
theirs, and they want to build and change it the same way, with the engine's
limitations marked on it. flask serves femkit's operations as JSON; a fluent
node editor is a program that runs in the browser, and femkit has none.

## Decision

1. **A React application, its graph view built on React Flow** (the xyflow
   project, MIT-licensed), in a top-level `frontend/` folder.
2. **Built with Node.js by whoever changes it**, in their own environment, from
   conda-forge; the control environment never holds Node.js.
3. **The bundle is shipped** in `femkit/web/static/`, generated and checked
   against its sources' hash like the reference pages, so installing femkit and
   opening the page need neither Node.js nor the network.
4. **Generic, as the command line is**: forms from the JSON schemas, the graph
   from `model graph`, every change through plan and apply.

## Alternatives not chosen

- **Rete.js.** Framework-neutral and extensible, but its current version also
  wants a bundler, so it saves no toolchain, and React Flow is the more
  widely used and better documented of the two.
- **litegraph.js**, the canvas library early node-editor tools for image
  pipelines used. Fast for very large graphs, but a canvas draws its own
  widgets: forms, text selection and keyboard access would be rebuilt by hand,
  where React Flow's nodes are ordinary page elements.
- **No build step** (a small library loaded as plain files, pages written by
  hand). Simpler to set up, but a graph editor of this size is then hand-made
  in every part React Flow already provides — panning, zoom, connection rules,
  selection, minimap — and would look and behave the less polished for it.
- **Server-rendered pages** (flask templates with small scripts). Good for
  forms and tables, not for a live graph editor.
- **A desktop program** (Qt, for example). It would not reach a cluster's
  login node through a browser and an SSH tunnel, and it would duplicate the
  surfaces femkit already generates from the registry.

## Consequences

- femkit gains a JavaScript toolchain, used only to change the front end; a
  stale bundle fails a basic test, as a stale reference page does.
- The page works offline and on a cluster through an SSH tunnel, served from
  the loopback address of the machine that holds the calculation folders.
- Nothing about a model's meaning lives in the front end: a new field,
  operation or node kind reaches the page through the schemas and the graph
  document.
