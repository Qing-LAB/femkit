"""A mesh recipe, `mesh/<name>.toml` (geometry.md § 6), and its check.

A recipe states the mesher that makes the mesh — never the study (geometry.md § 6) — the mesh's
size over the whole geometry and on named groups, how fast elements grow away from a group, the
worst element it accepts, how closely the mesh keeps each group's measure, and the geometry order. It names groups only, so it serves every component that
promises them; whether the component a study pairs it with does is the study's check. Each value
is written in the one quantity form (core.md § 11): a size a length, `{value, unit}`, or a
definition's name; a tolerance, a growth and a quality plain numbers.

The check of a recipe alone (models.md § 11.1) finds, each at its key (core.md § 10), every
value read by the check frame (`Checking.measure`, projects.md § 6):
- `no-such-mesher`: a mesher femkit does not declare — the meshers, its choices;
- `bad-quantity`: a value that does not read (core.md § 11) — a text saying the table to write, a
  name the project does not define; none for a definition whose value is not at hand, whose own
  finding says why (models.md § 3);
- `wrong-dimension`: a size that is no length, or a tolerance, growth or quality that is no
  plain number;
- `growth-required`: sizes on groups with no `growth`;
- `out-of-range`: a size, or a size on a group, not above 0; a tolerance below 0; a growth not
  above 0; a quality above 1.

These are every rule a recipe's values follow: the mesh stage that reads them checks only the
shape of the document femkit hands it (geometry.md §§ 5, 6).
"""

from __future__ import annotations

from typing import Iterator, Literal

from pydantic import Field

from femkit.core.issues import Issue
from femkit.core.schema import LENGTH, Measured, as_quantity, as_reference, meant
from femkit.core.units import Quantity
from femkit.definitions.meshers import Order
from femkit.projects.checking import Checking, Registration
from femkit.projects.door import Part
from femkit.projects.schemas import PartFile

KEY = "geometry.recipe"   # the key the layout names this schema by (projects.md § 4)

PLAIN = ()                          # a plain number's dimension


class Recipe(PartFile):
    """`mesh/<name>.toml`: one mesh recipe, on named groups, and the mesher that makes its mesh
    (geometry.md § 6)."""

    CHANGES = {2: "a recipe states the mesher that makes its mesh, `mesher` — `gmsh`, Gmsh's, or `given`, the "
                  "mesh the component's script writes — and a study names none"}

    schema_: Literal[2] = Field(alias="schema", description="the version of this file's format, which femkit raises "
                                "when it changes how files of this kind are written",
                                json_schema_extra={"doc": "models.md § 2"})
    mesher: str = as_reference("the mesher that makes the mesh, by name — `given`, the mesh the component's script "
                               "writes, passed on unchanged", "mesher", extra={"doc": "geometry.md § 6",
                                                                               "choices": "meshers"})
    size: Measured = as_quantity("the largest element size anywhere: a length above 0", "length")
    order: Order = Field(description="the geometry order — how closely elements follow a curved surface, 2 bending "
                                     "them to it")
    tolerance: Measured = as_quantity("how far each group's measure in the mesh may differ from its measure in the "
                                      "geometry, relative: a plain number, 0 or above", "constant")
    growth: Measured | None = as_quantity("how fast the size grows away from a group of `sizes`: the size added per "
                                          "unit of distance, a plain number above 0; required with `sizes`",
                                          "constant", default=None)
    quality: Measured | None = as_quantity("the smallest quality an element may have, by Gmsh's signed inverse "
                                           "condition number, at most 1; unset, only an inverted element, below 0, "
                                           "is refused", "constant", default=None)
    sizes: dict[str, Measured] = as_reference("a finer size on and near named groups, keyed by the group: each a "
                                              "length above 0",
                                              {"key": "group"}, extra={"quantity": "length"}, default_factory=dict)


#: The recipe's key that states its geometry order — its field of the type a geometry order is
#: (`Order`), read from the model: the key a mesher's `order = "recipe"` reads, and an axis of the
#: recipe may vary (geometry.md § 6; workflow.md § 2.3).
(ORDER,) = [name for name, f in Recipe.model_fields.items() if f.annotation is Order]


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """The findings on a recipe alone (module docstring), from the check frame's unit table and
    the project's definitions resolved (projects.md § 6)."""
    recipe: Recipe = part.data
    if recipe.mesher not in c.meshers:
        yield c.issue(part, "mesher", code="no-such-mesher", choices=sorted(c.meshers),
                      message=f"`{recipe.mesher}` is no mesher femkit has" + meant(recipe.mesher, sorted(c.meshers)))
    length, plain = "a length", "a plain number"
    for keys, value in ((("size",), recipe.size), *((("sizes", g), v) for g, v in recipe.sizes.items())):
        size, found = c.measure(part, keys, value, LENGTH, length)
        yield from found
        if size is not None and size.value <= 0:
            yield c.issue(part, *keys, code="out-of-range", message=f"a size is above 0, not {shown(size, c)}")
    tolerance, found = c.measure(part, ("tolerance",), recipe.tolerance, PLAIN, plain, definitions=False)
    yield from found
    if tolerance is not None and tolerance.value < 0:
        yield c.issue(part, "tolerance", code="out-of-range",
                      message=f"the tolerance is 0 or above, not {shown(tolerance, c)}")
    if recipe.growth is None and recipe.sizes:
        yield c.issue(part, "growth", code="growth-required",
                      message="sizes on groups need a `growth`: how fast the size grows away from them")
    if recipe.growth is not None:
        growth, found = c.measure(part, ("growth",), recipe.growth, PLAIN, plain, definitions=False)
        yield from found
        if growth is not None and growth.value <= 0:
            yield c.issue(part, "growth", code="out-of-range", message=f"the growth is above 0, not {shown(growth, c)}")
    if recipe.quality is not None:
        quality, found = c.measure(part, ("quality",), recipe.quality, PLAIN, plain, definitions=False)
        yield from found
        if quality is not None and quality.value > 1:
            yield c.issue(part, "quality", code="out-of-range",
                          message=f"the quality is at most 1, not {shown(quality, c)}")


def shown(value: Quantity, c: Checking) -> str:
    """A value read, as a person reads it, by the core's one formatter (`Units.shown`): a recipe
    serves every study, so in its canonical unit, exactly — `0 m`, `-0.02 m`, `1.5`."""
    return c.units.shown(value)


REGISTERS = Registration(schemas={KEY: Recipe}, checks={KEY: check})
