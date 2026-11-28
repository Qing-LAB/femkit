"""The Laplace square: a square of side `side` in the x-y plane, its lower-left corner at the
frame's origin, with the groups its contract (component.toml) promises — the body `domain`,
and its sides `left` (x = 0), `right` (x = side) and `sides` (the top and the bottom).

femkit runs it as `python geometry.py INPUTS OUTPUT` (manual: 3 · Write each part). INPUTS is
a JSON file, {"schema": 2, "definitions": {"side": 1.0}}: each definition the contract declares, a
length in the frame's unit — metres here. OUTPUT is the file to write the geometry to; its
format is femkit's choice, by its extension. The script builds the shapes and names the
groups; it does not mesh, since meshing is femkit's next step. Run it by hand the same way,
with an INPUTS file of your own.
"""

import json
import sys

import gmsh


def main(inputs: str, output: str) -> None:
    with open(inputs) as f:
        side = json.load(f)["definitions"]["side"]
    if not side > 0:
        sys.exit(f"the square's side must be positive, not {side}")

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1)   # Gmsh's messages into the run's log
        gmsh.model.add("square")
        square = gmsh.model.occ.addRectangle(0, 0, 0, side, side)
        gmsh.model.occ.synchronize()

        # Each side of the square is told apart by where its middle lies.
        near = side / 1000
        left, right, sides = [], [], []
        for _, curve in gmsh.model.getBoundary([(2, square)], combined=False, oriented=False):
            x, _, _ = gmsh.model.occ.getCenterOfMass(1, curve)
            if abs(x) < near:
                left.append(curve)
            elif abs(x - side) < near:
                right.append(curve)
            else:
                sides.append(curve)

        name(2, [square], "domain")
        name(1, left, "left")
        name(1, right, "right")
        name(1, sides, "sides")

        gmsh.write(output)
    finally:
        gmsh.finalize()


def name(dimension: int, tags: list[int], group: str) -> None:
    """One named group — in Gmsh's terms, a physical group with its name."""
    tag = gmsh.model.addPhysicalGroup(dimension, sorted(tags))
    gmsh.model.setPhysicalName(dimension, tag, group)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
