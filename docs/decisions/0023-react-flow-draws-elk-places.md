# ADR 0023: the page's diagrams — React Flow draws, ELK places

**Role:** ADR

**Status:** accepted (2026-11-26); decisions 1–2 amended the same day by the person (decision 4), built

**Authority:** the reasons and the alternatives only;
[`web.md`](../contracts/web.md) §§ 2.2, 2.4 and 10.1 own the diagrams, their
layout and the worker that runs it

## Context

The page draws three diagrams of one shape, the `Graph`
([ADR 0018](0018-one-graph-from-description-to-execution.md)): a project's
parts by section, a study's stages by case, and the jobs over them. React
Flow, already the page's dependency, draws nodes, ports and wires and lets
the person pan, zoom and select; it places nothing itself. Placing nodes by
hand-written code — columns by section, rows by rank, offsets for boxes — is
the handcrafted code the person's rules forbid, and breaks on the first graph
it was not tuned for. The person, 2026-11-26, asked how the flowchart would
be drawn — "i thought we already decided on how the flowchart will be drawn?
using react frameworks?" — and approved a layout library for it.

## Decision

1. **React Flow draws; ELK places.** The arrangement is computed by ELK
   (`elkjs`), a layered layout engine with ports, compound nodes and
   partitions, given the graph's declared order as its options: sections and
   ranks as partitions, boxes as compound nodes, each port on its side, wires
   in one direction. The page computes no position of its own.
2. **The top level placed from the top**, in the graph's order (ELK's
   `INTERACTIVE` node placement, no positions given), so a diagram opens on
   its content; measured: the centring placements left the first view on an
   empty quarter of Runs.
3. **ELK runs in a worker** the bundle ships, same-origin under the page's
   `script-src 'self'`; its bundled build does not resolve in the page's
   production build, measured.
4. **A node editor, not a diagram of boxes** (the person, 2026-11-26, on
   the first version: the parts must not be forced inside one box each
   section, the wires must not be compacted into square lines, groups are to
   be shown by colour, and the person moves the nodes where they want them —
   as the node editors they find clear manage complicated relations): cards
   with named slots — inputs left, outputs right — wires as smooth curves from
   slot to slot coloured by what they carry, a group shown by colour, never a
   frame around nodes; ELK proposes the first positions only — no compound
   nodes, no routes — and the person places every card. A category is a
   card's shape, colour and icon (few categories: the sections, the stage
   kinds); a card may be copied to wherever it serves, each wire attaching to
   the nearest copy so links do not cross, every copy lit together when one is
   selected — one node, its one file edited through any; the project is the
   master list, a list on the side and never a card in the network, and each
   definition a small card of its own beside what uses it (the person, the same
   day).

## Alternatives not chosen

- **Sections as bands, cases as boxes, right-angle routes**: built first and
  rejected by the person — containers forced around nodes and wires bundled
  into square lines hide what connects to what.

- **dagre**: a layered layout without ports or compound nodes; a case's box
  and a component's group ports would be drawn by hand around it.
- **Positions computed by the page's code**: handcrafted, and wrong for the
  next graph.

## Consequences

- `elkjs` is a dependency of the page, locked in `frontend/package-lock.json`
  and installed by `web build` through femkit's own web environment.
