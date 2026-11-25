"""The `geometry` domain (geometry.md): a component's contract and the mesh recipes.

Its modules, each the one home of what it names:

- `component` — `components/<name>/component.toml`, the contract wrapping the person's geometry
                script: its frame, its inputs, the groups it promises; the material assignment in
                it is the `materials` package's (§ 3; projects.md § 2)
- `recipe`    — `mesh/<name>.toml`, a mesh recipe on named groups (§ 6)

The kinds of place a group may be are `femkit/data/geometry/kinds.toml`, read by
`femkit/definitions/places.py`, since the catalogue that loads them sits below this package
(framework.md § 1). Running the script, the mesh step and the hand-over are step X's (plan § 4, X).
"""
