"""A mesh recipe, `mesh/<name>.toml` (geometry.md § 6), and its check.

A recipe states the mesh's size over the whole geometry and on named groups, how fast elements
grow away from a group, the worst element it accepts, how closely the mesh keeps each group's
measure, and the geometry order. It names groups only, so it serves every component that
promises them; whether the component a study pairs it with does is the study's check. Each value
is its own number, or an expression of the project's parameters (`"gap / 4"`).

The check of a recipe alone (models.md § 11.1) finds, each at its key (core.md § 10), every
value read by the check frame (`Checking.measure`, projects.md § 6):
- `bad-quantity`: a value that does not read (core.md § 11) — none for one using a parameter
  that does not resolve, whose own finding says why (models.md § 3);
- `wrong-dimension`: a size that is no length, or a tolerance, growth or quality that is no
  plain number;
- `growth-required`: sizes on groups with no `growth`;
- `out-of-range`: a growth not above 0, a quality above 1.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterator, Literal, Union

from pydantic import Field

from femkit.core.issues import Issue
from femkit.core.schema import LENGTH, as_quantity, as_reference
from femkit.projects.checking import Checking
from femkit.projects.door import Part
from femkit.projects.schemas import PartFile

KEY = "geometry.recipe"   # the key the layout names this schema by (projects.md § 4)

Number = Union[int, Decimal, str]   # a plain number, or an expression of the project's parameters
PLAIN = ()                          # a plain number's dimension


class Recipe(PartFile):
    """`mesh/<name>.toml`: one mesh recipe, on named groups (geometry.md § 6)."""

    size: str = as_quantity("the largest element size anywhere: a length", "length")
    order: Literal[1, 2] = Field(description="the geometry order — how closely elements follow a curved surface, 2 "
                                             "bending them to it")
    tolerance: Number = as_quantity("how far each group's measure in the mesh may differ from its measure in the "
                                    "geometry, relative: a plain number")
    growth: Number | None = as_quantity("how fast the size grows away from a group of `sizes`: the size added per "
                                        "unit of distance, a plain number above 0; required with `sizes`", default=None)
    quality: Number | None = as_quantity("the smallest quality an element may have, by Gmsh's signed inverse "
                                         "condition number, at most 1; unset, only an inverted element, below 0, is "
                                         "refused", default=None)
    sizes: dict[str, str] = as_reference("a finer size on and near named groups, keyed by the group: each a length",
                                         {"key": "group"}, extra={"quantity": "length"}, default_factory=dict)


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """The findings on a recipe alone (module docstring), from the check frame's unit table and
    the project's parameters resolved (projects.md § 6)."""
    recipe: Recipe = part.data
    length, plain = "a length, with its unit", "a plain number"
    yield from c.measure(part, ("size",), recipe.size, LENGTH, length)[1]
    for group, size in recipe.sizes.items():
        yield from c.measure(part, ("sizes", group), size, LENGTH, length)[1]
    yield from c.measure(part, ("tolerance",), recipe.tolerance, PLAIN, plain)[1]
    if recipe.growth is None and recipe.sizes:
        yield c.issue(part, "growth", code="growth-required",
                      message="sizes on groups need a `growth`: how fast the size grows away from them")
    if recipe.growth is not None:
        growth, found = c.measure(part, ("growth",), recipe.growth, PLAIN, plain)
        yield from found
        if growth is not None and growth.value <= 0:
            yield c.issue(part, "growth", code="out-of-range", message=f"the growth is above 0, not {recipe.growth}")
    if recipe.quality is not None:
        quality, found = c.measure(part, ("quality",), recipe.quality, PLAIN, plain)
        yield from found
        if quality is not None and quality.value > 1:
            yield c.issue(part, "quality", code="out-of-range",
                          message=f"the quality is at most 1, not {recipe.quality}")


PART_SCHEMAS = {KEY: Recipe}
PART_CHECKS = {KEY: check}
