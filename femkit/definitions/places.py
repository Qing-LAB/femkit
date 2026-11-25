"""`femkit/data/geometry/kinds.toml`: the kinds of place a group may be (geometry.md § 7) — the
one vocabulary of places a formulation's `on` and a schema field's `ref` read.

Its model lives here, with the shipped definitions' others, since the catalogue that loads it
sits below the `geometry` package that owns the rule (framework.md § 1)."""

from __future__ import annotations

import re
from typing import Literal, Mapping

from pydantic import ConfigDict, Field, RootModel, model_validator

from femkit.core.schema import Model, refuse

NAME = re.compile(r"[a-z][a-z_]*")
FRAMES = (2, 3)   # a geometry's dimensions: 2, drawn in the x-y plane, or 3 (geometry.md § 3)


class PlaceKind(Model):
    """One kind of place a group may be: what it is, its dimension in each geometry it exists in,
    and, for a face, the bodies it touches (geometry.md § 7)."""

    sentence: str = Field(description="what the place is, in one plain sentence")
    dimension: dict[int, int] = Field(min_length=1, description="its dimension in a geometry of each dimension it "
                                                                "exists in, keyed by the geometry's: 2 or 3")
    bodies: Literal[1, 2] | None = Field(default=None, description="for a face — one dimension less than its "
                                                                   "geometry — how many bodies it touches, observed "
                                                                   "once the geometry exists; none for another place")
    side: Literal["outside", "inside"] | None = Field(default=None, description="for a face touching one body: on "
                                                                                "the geometry's outside, or inside "
                                                                                "the body")

    @model_validator(mode="after")
    def _whole(self) -> "PlaceKind":
        problems: list[tuple[tuple, str]] = []
        for frame, dimension in self.dimension.items():
            if frame not in FRAMES:
                problems.append((("dimension", str(frame)), f"a geometry's dimension is 2 or 3, not {frame}"))
            elif not 0 <= dimension <= frame:
                problems.append((("dimension", str(frame)), f"a place in a geometry of dimension {frame} has a "
                                                            f"dimension from 0 to {frame}, not {dimension}"))
        faces = {frame - dimension == 1 for frame, dimension in self.dimension.items()}
        if len(faces) > 1:
            problems.append((("dimension",), "a place is a face in every geometry it exists in, or in none"))
        elif faces == {True} and self.bodies is None:
            problems.append((("bodies",), "a face says how many bodies it touches"))
        elif faces == {False} and self.bodies is not None:
            problems.append((("bodies",), "only a face, one dimension less than its geometry, touches bodies"))
        if (self.side is not None) != (self.bodies == 1):
            problems.append((("side",), "a face touching one body says on which side of it it lies, and no other"))
        refuse("PlaceKind", problems)
        return self


class PlaceList(RootModel[dict[str, PlaceKind]]):
    """`geometry/kinds.toml`: each place by its name — the one name it has, in a formulation's `on`
    and a `ref`'s `group:<place>`."""

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def _names(self) -> "PlaceList":
        refuse("PlaceList", [((name,), f"{name!r} is no place's name: lowercase letters and `_`")
                             for name in self.root if not NAME.fullmatch(name)])
        return self


def possible(places: Mapping[str, PlaceKind], frame: int, dimension: int) -> list[str]:
    """The places a group of ``dimension`` may be in a geometry of dimension ``frame``, as far as
    its promised dimension tells before the geometry exists (geometry.md § 7): one, or several
    faces until the geometry tells them apart; none when no place has that dimension there."""
    return [name for name, place in places.items() if place.dimension.get(frame) == dimension]
