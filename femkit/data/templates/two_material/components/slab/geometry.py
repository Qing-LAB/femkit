"""The two-material slab: a rectangle `length` by `height` in the x-y plane, its lower-left
corner at the frame's origin, cut at x = `interface` into two layers that share the face
between them. It names the groups its contract (component.toml) promises — the bodies `low`
and `high`, the face `middle` between them, and the outer sides `left` (x = 0), `right`
(x = length) and `sides` (the top and the bottom of both layers).

femkit runs it as `python geometry.py INPUTS OUTPUT` (geometry.md § 2). INPUTS is a JSON
file, {"schema": 1, "parameters": {"length": 1.0, "height": 1.0, "interface": 0.5}}: each
parameter the contract declares, a length in the frame's unit — metres here. OUTPUT is the
file to write the geometry to; its format is femkit's choice, by its extension. The script
builds the shapes and names the groups; it does not mesh, since meshing is femkit's next
step. Run it by hand the same way, with an INPUTS file of your own.
"""

import json
import sys

import gmsh


def main(inputs: str, output: str) -> None:
    with open(inputs) as f:
        parameters = json.load(f)["parameters"]
    length, height, interface = parameters["length"], parameters["height"], parameters["interface"]
    if not 0 < interface < length or not height > 0:
        sys.exit(f"the interface must lie inside the slab, 0 < {interface} < {length}, "
                 f"and its height must be positive, not {height}")

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1)   # Gmsh's messages into the run's log
        gmsh.model.add("two_material")
        low = gmsh.model.occ.addRectangle(0, 0, 0, interface, height)
        high = gmsh.model.occ.addRectangle(interface, 0, 0, length - interface, height)

        # Fragmenting makes the two layers share one face between them, so the mesh is
        # conforming across it; its map says which surface each rectangle became.
        _, pieces = gmsh.model.occ.fragment([(2, low)], [(2, high)])
        gmsh.model.occ.synchronize()
        low_surfaces = [tag for _, tag in pieces[0]]
        high_surfaces = [tag for _, tag in pieces[1]]

        low_edges = edges(low_surfaces)
        high_edges = edges(high_surfaces)
        middle = low_edges & high_edges              # the face both layers touch
        outer = (low_edges | high_edges) - middle

        # Each outer side is told apart by where its middle lies.
        near = length / 1000
        left, right, sides = [], [], []
        for curve in sorted(outer):
            x, _, _ = gmsh.model.occ.getCenterOfMass(1, curve)
            if abs(x) < near:
                left.append(curve)
            elif abs(x - length) < near:
                right.append(curve)
            else:
                sides.append(curve)

        name(2, low_surfaces, "low")
        name(2, high_surfaces, "high")
        name(1, list(middle), "middle")
        name(1, left, "left")
        name(1, right, "right")
        name(1, sides, "sides")

        gmsh.write(output)
    finally:
        gmsh.finalize()


def edges(surfaces: list[int]) -> set[int]:
    """The curves that bound the given surfaces."""
    return {tag for _, tag in gmsh.model.getBoundary([(2, s) for s in surfaces], combined=False, oriented=False)}


def name(dimension: int, tags: list[int], group: str) -> None:
    """One named group — in Gmsh's terms, a physical group with its name."""
    tag = gmsh.model.addPhysicalGroup(dimension, sorted(tags))
    gmsh.model.setPhysicalName(dimension, tag, group)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
