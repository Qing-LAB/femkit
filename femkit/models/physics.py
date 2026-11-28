"""A physics, `physics/<p>.toml` (models.md § 3): a formulation family, what each dimension
means for it, and the conditions and sources on named groups — the `models.physics` part schema
and its check. A condition's and a source's parameters are the keys its kind lists in the
formulation (models.md § 4.3), so their help is the formulation's: `keys` states them.

Its findings, each at the physics' key (what a study's pairing with a component finds at its keys
is the study's check, `study.py`):
- `no-such-formulation` (error), at `formulation`: choices, the declared families;
- `no-such-dimension` (error), at `meaning.<d>`: a dimension the formulation states no meaning for —
  those it does, its choices;
- `no-such-meaning` (error), at `meaning.<d>`: choices, the formulation's meanings for it;
- `no-such-kind` (error), at `<conditions|sources>.<name>.kind`: choices, the formulation's kinds;
- `unknown-parameter` (error), at the parameter: one its kind does not list;
- `missing-parameter` (error), at the parameter: one its kind lists that is not stated;
- `bad-quantity`, `wrong-dimension` (error), at the parameter: its value does not read — a text
  that names no definition, the table to write where it reads as one — or is not in its unit's
  dimension (core.md § 11);
- and each name it cites that names no part (`parts.cited`).
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping

from pydantic import Field

from femkit.core.issues import Issue
from femkit.core.schema import DeclaredKey, as_reference, field_extras, help_text, written_keys
from femkit.definitions.formulations import FormulationDefinition, KindSpec
from femkit.models.parts import Parameterized, cited
from femkit.projects.checking import Checking, Registration
from femkit.projects.door import Part
from femkit.projects.schemas import PartFile


class Condition(Parameterized):
    """The condition on one group: its kind, one its formulation allows, and the parameters that
    kind lists (models.md § 3)."""

    kind: str = Field(description="which condition holds on the group")


class Source(Parameterized):
    """One source: its kind, one its formulation allows, the group it acts in or on, and the
    parameters that kind lists (models.md § 3)."""

    kind: str = Field(description="which source it is")
    on: str = as_reference("the group it acts in or on, by name", "group")


class Physics(PartFile):
    """`physics/<p>.toml`: the physics stated on named groups, never on a component, so it serves
    every component whose contract promises the groups it names (models.md § 3)."""

    formulation: str = Field(description="the formulation family it states", json_schema_extra={"doc": "models.md § 4"})
    meaning: dict[str, str] = Field(default_factory=dict, description="what each dimension of the components it "
                                    "serves means for its formulation, keyed by the dimension",
                                    json_schema_extra={"doc": "models.md § 3"})
    conditions: dict[str, Condition] = as_reference(
        "the condition on each outer-boundary group, and on each interface group that carries one, keyed by the group",
        {"key": "group:outer_boundary|group:interface"}, default_factory=dict)
    sources: dict[str, Source] = Field(default_factory=dict, description="each source by its name: its kind, the "
                                                                         "group it acts in or on, and the parameters "
                                                                         "its kind lists")


#: The tables whose entries are of a formulation's kinds, its table of the same name: each with what
#: one entry is called, and its model.
TABLES: dict[str, tuple[str, type[Parameterized]]] = {"conditions": ("condition", Condition),
                                                      "sources": ("source", Source)}


def kinds(f: FormulationDefinition, table: str) -> dict[str, KindSpec]:
    """The formulation's kinds for one of `TABLES`: its condition kinds, or its source kinds."""
    return getattr(f, table)


def keys(formulations: Mapping[str, FormulationDefinition], text: str, manual: str | None = None) -> list[DeclaredKey]:
    """The keys a physics' text holds that a declaration states, not its schema (core.md § 2; web.md
    § 8.3): `formulation`, one of the declared families, its help ending with ``manual``, the
    chapter of the manual its kind declares; and, for the formulation the text names, each condition's
    and source's `kind`, one of its formulation's kinds, and each parameter its kind lists, as the
    formulation states it. A kind is read from the text as it writes it — set, or shown commented
    out — so an entry shown as an example has its keys too; an entry whose kind the text does not
    write, or writes as none of the formulation's, holds each parameter every kind listing it agrees
    on, if they do."""
    written = written_keys(text)
    field = Physics.model_fields["formulation"]
    out = [DeclaredKey(("formulation",), field.description, values=tuple(formulations), required=field.is_required(),
                       manual=manual if field_extras(field).get("doc") else None)]
    named = written.get(("formulation",))
    f = formulations.get(named) if isinstance(named, str) else None
    if f is None:
        return out
    for table, entry in sorted({p[:2] for p in written if len(p) > 1 and p[0] in TABLES}):
        allowed, model = kinds(f, table), TABLES[table][1]
        kind = model.model_fields["kind"]
        out.append(DeclaredKey((table, entry, "kind"), kind.description, values=tuple(allowed),
                               required=kind.is_required()))
        written_kind = written.get((table, entry, "kind"))
        specs = [allowed[written_kind]] if isinstance(written_kind, str) and written_kind in allowed \
            else list(allowed.values())
        listed: dict[str, set[tuple[str, str]]] = {}
        for spec in specs:
            for name, parameter in spec.parameters.items():
                listed.setdefault(name, set()).add((parameter.description, parameter.unit))
        out += [DeclaredKey((table, entry, name), sentence, units=(unit,), required=True)
                for name, agreed in listed.items() if len(agreed) == 1 for sentence, unit in agreed]
    return out


def _stated(c: Checking, text: str, manual: str | None) -> list[DeclaredKey]:
    """The keys the formulations state beside a physics' schema (`keys`), as the frame hands them."""
    return keys(c.formulations, text, manual)


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """The physics' own rules and its formulation's (models.md §§ 3–4)."""
    data: Physics = part.data
    yield from cited(c, part)
    f = c.formulations.get(data.formulation)
    if f is None:
        yield c.issue(part, "formulation", code="no-such-formulation", choices=sorted(c.formulations),
                      message=f"`{data.formulation}` is no formulation femkit declares")
        return
    for dimension, meaning in data.meaning.items():
        if dimension not in f.meanings:
            yield c.issue(part, "meaning", dimension, code="no-such-dimension", choices=sorted(f.meanings),
                          message=f"{data.formulation} states what {' and '.join(sorted(f.meanings))} dimensions "
                                  f"mean, not {dimension}")
        elif meaning not in f.meanings[dimension]:
            yield c.issue(part, "meaning", dimension, code="no-such-meaning", choices=f.meanings[dimension],
                          message=f"`{meaning}` is not what {dimension}-D can mean for {data.formulation}")
    for table, (noun, _) in TABLES.items():
        allowed = kinds(f, table)
        for name, entry in getattr(data, table).items():
            yield from _entry(c, part, (table, name), noun, entry, allowed, data.formulation)


def _entry(c: Checking, part: Part, at: tuple[str, str], noun: str, entry: Parameterized,
           allowed: dict[str, KindSpec], formulation: str) -> Iterator[Issue]:
    """One condition or source: its kind, one the formulation allows, and the parameters it lists."""
    spec = allowed.get(entry.kind)
    if spec is None:
        yield c.issue(part, *at, "kind", code="no-such-kind", choices=list(allowed),
                      message=f"`{entry.kind}` is no {noun} kind of {formulation}")
        return
    for key in sorted(set(entry.parameters) - set(spec.parameters)):
        yield c.issue(part, *at, key, code="unknown-parameter",
                      message=f"a {entry.kind} {noun} takes {', '.join(sorted(spec.parameters)) or 'no parameter'}, "
                              f"not {key}")
    for key, parameter in spec.parameters.items():
        given: Any = entry.parameters.get(key)
        if given is None:
            yield c.issue(part, *at, key, code="missing-parameter",
                          message=f"the {entry.kind} {noun} {at[1]} states no {key}: "
                                  f"{help_text(parameter.description, unit=parameter.unit)}")
            continue
        yield from c.measure(part, (*at, key), given, c.units.unit(parameter.unit).dimension,
                             f"in the dimension of {parameter.unit}", unit=parameter.unit)[1]


REGISTERS = Registration(schemas={"models.physics": Physics}, checks={"models.physics": check},
                         keys={"models.physics": _stated})
