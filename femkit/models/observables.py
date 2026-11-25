"""An observable set, `observables/<o>.toml` (models.md § 5.2): what a study reports, each
observable read at a point, along a line or over a group — the `models.observables` part schema
and its check. What its quantity, its group and its point mean depends on the physics and the
component a study pairs it with: the study's check finds that, at this file's keys (`study.py`).

Its findings, each at the observable's key:
- `wrong-reduction` (error), at `reduction`: `value` at a point (right), another over a line or a
  group (choices);
- `bad-unit` (error), at `unit`: not a unit the unit table reads;
- `bad-quantity`, `wrong-dimension` (error), at `point` or `line`: a coordinate that does not read,
  or is not a length.
"""

from __future__ import annotations

from typing import Annotated, Any, Iterator, Literal, Union

from pydantic import Discriminator, Field, Tag

from femkit.core.issues import Issue
from femkit.core.schema import LENGTH, Model, as_quantity, as_reference, closed
from femkit.core.units import UnitError
from femkit.models.parts import cited
from femkit.projects.checking import Checking
from femkit.projects.door import Part
from femkit.projects.layout import held
from femkit.projects.schemas import PartFile

Reduction = Literal["value", "average", "integral", "maximum", "norm"]
AT_A_POINT = "value"   # the one reduction at a point; the others reduce over a line or a group


class Observable(Model):
    """What every observable states, wherever it is read (models.md § 5.2)."""

    quantity: str = Field(description="the quantity it reads: a derived quantity of the formulation of the physics a "
                                      "study pairs it with")
    reduction: Reduction = Field(description="how it is reduced where it is read — a value at a point, the others "
                                             "over a line or a group")
    unit: str = as_quantity("the unit it is reported in: a unit of its quantity, or, for an integral, of its quantity "
                            "times the length, area or volume it is integrated over", "unit")


class AtPoint(Observable):
    """An observable read at a point."""

    point: list[str] = as_quantity("where it is read, as a point: one length per axis of the component's frame, "
                                   "from its origin; or give `line` or `group` instead", "length", min_length=1)


class AlongLine(Observable):
    """An observable read along a line."""

    line: list[list[str]] = as_quantity("where it is read, as a line: its two end points, each one length per axis "
                                        "of the component's frame, from its origin; or give `point` or `group` "
                                        "instead", "length", min_length=2, max_length=2)


class OverGroup(Observable):
    """An observable read over a group."""

    group: str = as_reference("where it is read, as a group: one the paired component promises; or give `point` or "
                              "`line` instead", "group")
    side: str | None = as_reference("on an interface group, the body group it is read from", "group:body",
                                    default=None)


#: Where an observable may be read, each by the key that states it: exactly one is given.
SUPPORTS: dict[str, type[Observable]] = {"point": AtPoint, "line": AlongLine, "group": OverGroup}


def _support(value: Any) -> str | None:
    """Which support an observable states: the one key of `SUPPORTS` it gives; None for none or several."""
    given = [key for key in SUPPORTS if held(value, key) is not None]
    return given[0] if len(given) == 1 else None


Located = Annotated[Union[tuple(Annotated[model, Tag(key)] for key, model in SUPPORTS.items())],
                    Discriminator(_support, custom_error_type="support",
                                  custom_error_message="give exactly one of `point`, `line` and `group`: where it is "
                                                       "read")]


def support(observable: Observable) -> str:
    """The key that states where ``observable`` is read."""
    return next(key for key, model in SUPPORTS.items() if isinstance(observable, model))


class ObservableSet(PartFile):
    """`observables/<o>.toml`: what a study reports, on named groups and on points and lines given
    with their units (models.md § 5.2)."""

    observables: dict[str, Located] = Field(default_factory=dict, description="the set's observables, by name, "
                                            "unique across the sets a study reports",
                                            json_schema_extra={"doc": "models.md § 5.2"})


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """Each observable's own rules (models.md § 5.2)."""
    data: ObservableSet = part.data
    yield from cited(c, part)
    others = [r for r in closed(Reduction) if r != AT_A_POINT]
    for name, observable in data.observables.items():
        at = ("observables", name)
        where = support(observable)
        if where == "point" and observable.reduction != AT_A_POINT:
            yield c.issue(part, *at, "reduction", code="wrong-reduction", right=AT_A_POINT,
                          message=f"`{name}` is read at a point, where it has one value")
        elif where != "point" and observable.reduction == AT_A_POINT:
            yield c.issue(part, *at, "reduction", code="wrong-reduction", choices=others,
                          message=f"`{name}` is read over a {where}, which has no one value")
        try:
            c.units.parse(observable.unit)
        except UnitError as exc:
            yield c.issue(part, *at, "unit", code="bad-unit", message=f"the unit of `{name}` does not read: {exc}")
        for point in points(observable):
            for length in point:
                yield from c.measure(part, (*at, where), length, LENGTH, "a length")[1]


def points(observable: Observable) -> list[list[str]]:
    """The points an observable is read at: its point, or its line's two ends; none over a group."""
    if isinstance(observable, AtPoint):
        return [observable.point]
    return list(observable.line) if isinstance(observable, AlongLine) else []


PART_SCHEMAS = {"models.observables": ObservableSet}
PART_CHECKS = {"models.observables": check}
