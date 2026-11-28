"""What femkit's control process reads of a built geometry and hands each engine (geometry.md §§ 7,
8): the place each group of a built geometry is, from the geometry stage's `groups.json`; and the
groups a hand-over hands its engine. Which hand-over a mesh reaches its engine by is the mesher
definitions' one lookup by the mesh's type (`definitions/meshers.py`, `handover`); where the stage
programs are and what is
copied beside them is the jobs domain's catalogue (jobs.md § 1.1).

The programs themselves run inside an environment — `femkit/engines/stages/` and each engine's
hand-over — and import nothing of femkit's but what is copied beside them; this module reads for
them the definitions they cannot (framework.md § 1). What a finished geometry stage built is read
back here too: its run's `groups.json`, the document its check wrote (`built`), and each group a
contract promises that it holds not (`unheld`) — what a change's impact says of a built geometry
(workflow.md § 10).
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from femkit.core import persist
from femkit.core.operations import Context
from femkit.definitions import catalogue
from femkit.definitions.meshers import HandOver
from femkit.definitions.places import PlaceKind, possible
from femkit.engines.stages import documents
from femkit.jobs import runs

#: The artifact type whose document says what a built geometry holds — each promised group's
#: pieces, and each group it made unpromised — and that document's kind (workflow.md § 2.2;
#: geometry.md § 7).
GROUPS, GROUPS_DOCUMENT = "geometry/groups", "groups"


def built(ctx: Context, run: Path) -> dict | None:
    """What the geometry built in ``run`` holds, as its check wrote it (geometry.md § 7): its
    `groups.json`, read by the stage programs' own reader of the document's shape; None where it is
    not there, or does not read."""
    try:
        held = persist.read_json(runs.output(run, catalogue.artifacts(ctx)[GROUPS].file))
        return documents.check(GROUPS_DOCUMENT, held)
    except (OSError, ValueError):                       # not there, no JSON, or not of the shape
        return None


def unheld(promised: Mapping[str, int], observed: dict) -> list[str]:
    """Each group ``promised`` — by its name, with its dimension — that the built geometry
    ``observed`` holds not: no group of that name and dimension with pieces, among those it was
    promised or those it made unpromised (geometry.md § 7)."""
    held = {(name, group["dimension"]) for name, group in observed["groups"].items() if group["pieces"]}
    held |= {(group["name"], group["dimension"]) for group in observed["unpromised"] if group["pieces"]}
    return [name for name, dimension in promised.items() if (name, dimension) not in held]


def places_of(places: Mapping[str, PlaceKind], observed: dict) -> dict[str, list[str]]:
    """Each promised group of a `groups` document, with the places its pieces are, by the
    vocabulary of places (geometry.md § 7): a piece of the frame's dimension, a body; a face, by
    the bodies it touches — those it bounds, or the one it lies inside — and on which side; a
    piece of a lower dimension, the one place of its dimension there."""
    frame = observed["dimension"]
    faces = {f["tag"]: f for f in observed["faces"]}
    out = {}
    for name, group in observed["groups"].items():
        found = set()
        for piece in group["pieces"]:
            candidates = possible(places, frame, piece["dimension"])
            face = faces.get(piece["tag"]) if piece["dimension"] == frame - 1 else None
            if face is not None:
                inside = bool(face["embedded_in"])
                touches = len(face["embedded_in"]) if inside else len(face["bodies"])
                side = "inside" if inside else "outside"
                candidates = [p for p in candidates
                              if places[p].bodies == touches and places[p].side in (None, side)]
            found.update(candidates)
        out[name] = sorted(found)
    return out


def handed(route: HandOver, places: Mapping[str, PlaceKind], frame: int, groups: Mapping[str, int]) -> dict[str, int]:
    """The promised ``groups`` — each by name with its dimension — that the hand-over ``route``
    hands its engine: those whose every place, as far as their dimension tells in a geometry of
    dimension ``frame``, is one the hand-over keeps by its name."""
    kept = set(route.names)
    return {name: d for name, d in groups.items() if set(possible(places, frame, d)) <= kept}
