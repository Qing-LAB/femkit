"""The `geometry` domain (geometry.md): a component's contract, the mesh recipes, and what femkit's
control process reads of the stages.

Its modules, each the one home of what it names:

- `component` — `components/<name>/component.toml`, the contract wrapping the person's geometry
                script: its frame, its inputs, the groups it promises, the mesh it writes too; the
                material assignment in it is the `materials` package's (§ 3; projects.md § 2)
- `recipe`    — `mesh/<name>.toml`, a mesh recipe on named groups (§ 6)
- `steps`     — the place each group of a built geometry is (§ 7), and the groups a hand-over
                hands its engine (§ 8)

The programs a stage runs inside an environment — the geometry's check, Gmsh's meshing, the
pass-through, the mesh's check, the `gmsh` environment's check — are `femkit/engines/stages/`, and
each engine's hand-over its engine package's (framework.md § 1). The kinds of place a group may be
are `femkit/data/geometry/kinds.toml`, read by `femkit/definitions/places.py`, since the catalogue
that loads them sits below this package. Writing and running the stages from a study is the
workflow's (workflow.md; plan § 4, X).
"""
