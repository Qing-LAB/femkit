"""`model check`: the second tier of validity (models.md § 3, § 11.2, § 13).

A model that loads may still be incomplete, or ask what its formulation does not allow;
each such finding names the object by its address (§ 11.1). Region coverage needs the
geometry built and is checked where a mesher runs (§ 9.2), never here.
"""

from __future__ import annotations

from decimal import Decimal

from femkit.core import text
from femkit.core.issues import Issue
from femkit.core.units import Quantity, UnitError, Units
from femkit.definitions.formulations import FormulationDefinition, KindSpec
from femkit.models.schema import Kinded, ModelFile, quantities

TWO_D = {"rectangle", "disk", "polygon"}
THREE_D = {"box", "sphere", "cylinder", "extrusion"}


def address(*path: str) -> str:
    """`model:<dotted path>` (models.md § 11.1)."""
    return "model:" + ".".join(path)


def _set(path: str, value: str) -> str:
    return text.typed("model", "set", path, value)


def findings(m: ModelFile, formulations: dict[str, FormulationDefinition], units: Units) -> list[Issue]:
    out: list[Issue] = []

    def finding(subject: str, message: str, *next: str, code: str = "model-incomplete") -> None:
        out.append(Issue(severity="error", code=code, subject=subject, message=message, next=tuple(next)))

    if m.formulation is None:
        finding(address("formulation"), "names no formulation", _set("model:formulation", '"<id>"'))
        return out
    f = formulations.get(m.formulation)
    if f is None:
        finding(address("formulation"), f"{m.formulation!r} is not a formulation (declared: "
                f"{', '.join(sorted(formulations))})", code="model-invalid")
        return out
    params = m.parameter_values(units)

    # geometry, frame, dimension
    g = m.geometry
    dimension = g.dimension if g else None
    if g is None or dimension is None:
        finding(address("geometry", "dimension"), "states no dimension (2 or 3)", _set("model:geometry.dimension", "2"))
    else:
        meanings = f.meanings.get(str(dimension), [])
        if not meanings:
            finding(address("geometry", "dimension"), f"{m.formulation} is not stated in {dimension}-D", code="model-invalid")
        elif g.meaning not in meanings:
            finding(address("geometry", "meaning"), f"says what {dimension}-D means for {m.formulation}: one of "
                    f"{', '.join(map(repr, meanings))}", _set("model:geometry.meaning", f'"{meanings[0]}"'))
        for name, shape in g.shapes.items():
            wrong = (shape.kind in THREE_D) if dimension == 2 else (shape.kind in TWO_D)
            if wrong:
                finding(address("geometry", "shapes", name), f"a {shape.kind} is not a {dimension}-D shape",
                        code="model-invalid")
    bare = any(isinstance(v, (int, Decimal)) for at, kind, v in quantities(m) if kind == "coordinate")
    if bare and m.frame is None:
        finding(address("frame", "unit"), "has bare-number coordinates, and no frame unit to read them in",
                _set("model:frame.unit", '"m"'))
    if dimension is not None:
        for at, kind, _ in quantities(m):
            if kind == "coordinate" and isinstance(at[-1], int) and at[-1] >= dimension:
                finding(address(*map(str, at[:-1])), f"has more coordinates than the model's {dimension} dimensions",
                        code="model-invalid")

    # regions, materials, conditions
    domains = [n for n, r in m.regions.items() if r.kind == "domain"]
    if not domains:
        finding(address("regions"), "has no domain region", _set("model:regions.<name>",
                '{ kind = "domain", shapes = ["<shape>"] }'))
    for name in domains:
        if name not in m.assign:
            finding(address("regions", name), "is a domain with no material", _set(f"model:assign.{name}", '"<material>"'))
    for name, region in m.regions.items():
        if region.kind != "domain" and name not in m.conditions:
            what = "an outer boundary" if region.kind == "boundary" else "a named interface"
            kinds = [k for k, s in f.conditions.items() if region.kind in s.on]
            finding(address("regions", name), f"is {what} with no condition (allowed: {', '.join(kinds)})",
                    _set(f"model:conditions.{name}", f'{{ kind = "{kinds[0]}" }}' if kinds else '"<kind>"'))
    for name, condition in m.conditions.items():
        _kinded(finding, ("conditions", name), condition, f.conditions, m.regions[name].kind, params, units)
    for name, source in m.sources.items():
        region = m.regions.get(source.on)
        _kinded(finding, ("sources", name), source, f.sources, region.kind if region else None, params, units)

    # materials: every property the formulation reads, each with what it rests on
    for name, props in m.materials.items():
        for prop in props:
            if prop not in f.properties:
                finding(address("materials", name, prop), f"{m.formulation} reads no {prop!r} (it reads: "
                        f"{', '.join(f.properties)})", code="model-invalid")
    for domain, material in m.assign.items():
        props = m.materials.get(material, {})
        for prop, spec in f.properties.items():
            p = props.get(prop)
            at = ("materials", material, prop)
            if p is None:
                finding(address(*at), f"is missing, and {m.formulation} reads it in {domain}",
                        _set(f"model:materials.{material}.{prop}.value", '"<value>"'))
                continue
            if p.value is None and p.table is None:
                finding(address(*at), "has neither a value nor a table")
            for key in ("source", "convention", "range"):
                if getattr(p, key) is None:
                    finding(address(*at, key), "is missing: a property says what it rests on, how its complex "
                            "values are written, and where it is valid", _set(f"model:materials.{material}.{prop}.{key}",
                                                                          '"<…>"'))
            if not spec.complex and p.convention not in (None, "real"):
                finding(address(*at, "convention"), f"{prop} is real in {m.formulation}", code="model-invalid")
            if p.value is not None:
                _dimension(finding, (*at, "value"), p.value, spec.unit, params, units)

    for convention in f.conventions:
        if m.conventions is None or getattr(m.conventions, convention) is None:
            finding(address("conventions", convention), f"{m.formulation} requires it chosen; it is never defaulted",
                    _set(f"model:conventions.{convention}", '"<…>"'))
    return out


def _kinded(finding, at: tuple, item: Kinded, allowed: dict[str, KindSpec], region_kind: str | None,
            params: dict[str, Quantity], units: Units) -> None:
    spec = allowed.get(item.kind)
    if spec is None:
        finding(address(*at, "kind"), f"{item.kind!r} is not a kind the formulation allows (allowed: "
                f"{', '.join(allowed) or 'none'})", code="model-invalid")
        return
    if region_kind is not None and region_kind not in spec.on:
        finding(address(*at), f"a {item.kind} stands on a {' or '.join(spec.on)}, not a {region_kind}",
                code="model-invalid")
    given = dict(item.model_extra or {})
    if isinstance(item, Kinded) and "on" in type(item).model_fields:
        given.pop("on", None)
    for name in spec.parameters:
        if name not in given:
            finding(address(*at, name), f"is missing: a {item.kind} states its {name} — "
                    f"{spec.parameters[name].description} (in {spec.parameters[name].unit})")
    for name, value in given.items():
        if name not in spec.parameters:
            finding(address(*at, name), f"a {item.kind} takes no {name!r} (it takes: "
                    f"{', '.join(spec.parameters) or 'nothing'})", code="model-invalid")
        else:
            _dimension(finding, (*at, name), value, spec.parameters[name].unit, params, units)


def _dimension(finding, at: tuple, value, unit: str, params: dict[str, Quantity], units: Units) -> None:
    """A value is a quantity of its unit's dimension."""
    if not isinstance(value, str):
        value = str(value)
    try:
        q, want = units.parse(value, params), units.parse(unit)
    except UnitError as exc:
        finding(address(*at), str(exc), code="model-invalid")
        return
    if q.dimension != want.dimension:
        what = "a plain number" if not want.dimension else f"in the dimension of {unit}"
        finding(address(*at), f"{value!r} is not {what}", code="model-invalid")
