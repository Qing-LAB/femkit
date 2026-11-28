"""The mesh stage's check (geometry.md § 5; workflow.md § 2.1), one program for every mesher, run
after it in the environment that provides it:

    python check_mesh.py RECIPE REGIONS CHECKED OUTPUTS MESH

A program run in the stage's job with `documents.py` beside it (framework.md § 1): it imports the
standard library and `documents` only, so it runs in every mesher's environment and opens no
mesh — the mesher measured its mesh, in its own library, into the region map.

RECIPE is the `recipe` document the stage was handed; REGIONS the mesher's region map, a
`regions` document; MESH the mesh it maps. The check judges the region map against the recipe and
writes its two records (`documents.judged`): its verdict, CHECKED, a `checked` document, and,
when it passed, OUTPUTS, an `outputs` document holding the SHA-256 of REGIONS and of MESH (jobs.md
§ 2). It refuses the mesh, naming each group that does not hold, for a promised group missing from
the region map, held there at another dimension than its promised one, or holding no element;
measured unlike the geometry beyond the recipe's `tolerance`; or holding an element below the
recipe's `quality` — or, with `quality` unset, an inverted one, below 0; and it refuses a MESH that
is not there. It exits 0 when it passed, otherwise 1, its last line the reason; a RECIPE or
REGIONS not of its shape fails it with that reason, exit 2, and a call naming no CHECKED exits 2,
writing nothing. What a recipe's value may be is `project check`'s (geometry.md § 6); this program
checks only the documents' shapes.
"""

import os
import sys

import documents

USAGE = "usage: python check_mesh.py RECIPE REGIONS CHECKED OUTPUTS MESH"


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        return stop(USAGE, 2)
    recipe_file, regions_file, checked, outputs, mesh = argv
    try:
        recipe = documents.read(recipe_file, "recipe")
        regions = documents.read(regions_file, "regions")
    except documents.Malformed as exc:
        documents.judged(checked, outputs, str(exc), [])
        return stop(str(exc), 2)
    problems = judge(recipe, regions)
    if not os.path.isfile(mesh):
        problems.append(f"the mesher wrote no {os.path.basename(mesh)}")
    reason = "; ".join(problems) or None
    documents.judged(checked, outputs, reason, [regions_file, mesh])
    return 0 if reason is None else stop(reason)


def judge(recipe: dict, regions: dict) -> list[str]:
    """What does not hold of the region map against the recipe (geometry.md § 5), each naming its
    group: every promised group in it at its dimension and holding elements, its measure within
    the recipe's tolerance of the geometry's, and no element of a group of the mesh's dimension
    below the recipe's quality, or inverted where it states none."""
    problems = []
    mapped, tolerance, least = regions["groups"], recipe["tolerance"], recipe["quality"]
    for name, dimension in recipe["groups"].items():
        row = mapped.get(name)
        if row is None:
            problems.append(f"`{name}` is promised and not in the mesh")
        elif row["dimension"] != dimension:
            problems.append(f"`{name}` is a group of dimension {row['dimension']} in the mesh; its contract promises "
                            f"{dimension}")
        elif row["elements"] == 0:
            problems.append(f"`{name}` holds no element of the mesh")
        else:
            if row["difference"] is not None and not row["difference"] <= tolerance:
                problems.append(f"`{name}` measures {row['measure']:.10g} in the mesh against {row['geometry']:.10g} "
                                f"in the geometry, {row['difference']:.2e} apart, beyond the recipe's tolerance "
                                f"{tolerance:g}")
            quality = row["quality"]
            if quality is not None and least is not None and quality < least:
                problems.append(f"`{name}` holds an element of quality {quality:.3g}, below the recipe's {least:g}")
            elif quality is not None and least is None and quality < 0:
                problems.append(f"`{name}` holds an inverted element, of quality {quality:.3g}")
    return problems


def stop(reason: str, status: int = 1) -> int:
    """The reason, as the last line of the check's output (jobs.md § 2)."""
    sys.stdout.flush()
    print(reason, file=sys.stderr, flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
