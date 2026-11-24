"""`model check`: the second tier of validity (models.md § 3, § 11.2, § 13).

A model that loads may still be incomplete, or ask what its formulation does not allow. Each
finding is a whole sentence naming its subject, in the chain's order, the first being the
model's next step; its next steps are the very actions a person would take — the palette's adds
and a port's connect, or a value to set with its choices. A fix never chooses among
alternatives. Region coverage needs the geometry built and is checked where a mesher runs
(§ 9.2), never here.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from femkit.core import view
from femkit.core.issues import Issue
from femkit.core.schema import field_extras
from femkit.core.units import Quantity, UnitError, Units
from femkit.definitions.formulations import FormulationDefinition, KindSpec
from femkit.models import adds, fields, graph
from femkit.models.address import Address
from femkit.models.requests import MODEL_SET, MODEL_UNSET
from femkit.models.schema import (LENGTH, Conventions, Geometry, Kinded, ModelFile, Property, locate, object_type,
                                  quantities)

#: The fields of a material property a file may leave out but the check asks for: its `stated`.
STATED = tuple((f.alias or n) for n, f in Property.model_fields.items() if field_extras(f).get("stated"))


def address(*path: str) -> str:
    """`model:<dotted path>` (models.md § 11.1)."""
    return str(Address(None, tuple(path)))


def owner(m: ModelFile, path: tuple[str, ...]) -> tuple[int, str]:
    """The place in the chain's order of what ``path`` lies in, and what a person calls it: an
    entry by its label, as its node is labeled; a table or a single object by its type."""
    found = locate("model", path)
    if found is None:
        return -1, "the model"
    o, key = found
    if key is None:
        return o.rank, f"the {o.kind}"
    return o.rank, o.label_of(key, o.entries(m).get(key))


def formulation_choice(formulations: dict) -> dict:
    """What the model's formulation may be, as a JSON schema fragment: the one place it is built."""
    return {"type": "string", "enum": sorted(formulations),
            "description": ModelFile.model_fields["formulation"].description}


def findings(m: ModelFile, formulations: dict[str, FormulationDefinition], units: Units,
             project: Path) -> list[Issue]:
    """Every finding, in the chain's order."""
    out: list[tuple[int, Issue]] = []

    def finding(path: tuple[str, ...], message: str, *next: view.Action | None, code: str = "model-incomplete") -> None:
        rank, label = owner(m, path)
        out.append((rank, Issue(severity="error", code=code, subject=address(*path), label=label, message=message,
                                next=tuple(n for n in next if n is not None))))

    def choose(path: tuple[str, ...], label: str, schema: dict) -> view.Action | None:
        """A value to choose from a closed list, left to the person; none for a value to write,
        which the person writes in its object's text (web.md § 8.3)."""
        if not (schema.get("enum") or any(o.get("enum") for o in schema.get("anyOf", []))):
            return None
        return view.command(MODEL_SET, label=f"set {label}", project=str(project), address=address(*path),
                            fills=[view.Fill(field="value", label=label, json_schema=schema)])

    def add(kind: str, type_: str | None, name: str | None = None) -> view.Action | None:
        """The palette's add of an object of ``kind`` and ``type_``, its name given or to fill."""
        return adds.entry(project, None, f, units, object_type(kind), type_, name).add

    def remove(path: tuple[str, ...]) -> view.Action:
        """What an invalid entry's fix is: taking it out."""
        return view.command(MODEL_UNSET, label=f"remove {address(*path)}", project=str(project),
                            address=address(*path))

    if m.formulation is None:
        finding(("formulation",), "The model names no formulation.",
                choose(("formulation",), "the formulation", formulation_choice(formulations)))
        return _ordered(out)
    f = formulations.get(m.formulation)
    if f is None:
        finding(("formulation",), f"The model names {m.formulation!r}, which is no formulation; the formulations "
                f"are {', '.join(sorted(formulations))}.", code="model-invalid")
        return _ordered(out)
    params = m.parameter_values(units)
    geometry = fields.fragment(Geometry, units)

    # geometry, frame, dimension
    g = m.geometry
    dimension = g.dimension if g else None
    if g is None or dimension is None:
        finding(("geometry", "dimension"), "The geometry states no dimension.",
                choose(("geometry", "dimension"), "the dimension", fields.leaf(geometry, ("dimension",))))
    else:
        meanings = f.meanings.get(str(dimension), [])
        if not meanings:
            finding(("geometry", "dimension"), f"{m.formulation} is not stated in {dimension}-D.", code="model-invalid")
        elif g.meaning not in meanings:
            finding(("geometry", "meaning"), f"The geometry does not say what {dimension}-D means for {m.formulation}.",
                    choose(("geometry", "meaning"), "what it means", {"type": "string", "enum": meanings}))
        for name, shape in g.shapes.items():
            if type(shape).dimension not in (None, dimension):
                finding(("geometry", "shapes", name), f"The shape {name} is a {shape.kind}, which is no "
                        f"{dimension}-D shape.", remove(("geometry", "shapes", name)), code="model-invalid")
    bare = any(isinstance(v, (int, Decimal)) for at, kind, v in quantities(m) if kind == "coordinate")
    if bare and m.frame is None:
        finding(("frame", "unit"), "The model writes coordinates as bare numbers, and has no frame unit to read "
                "them in.", choose(("frame", "unit"), "the length unit", {"type": "string", "enum": units.of(LENGTH)}))
    if dimension is not None:
        for at, kind, _ in quantities(m):
            if kind == "coordinate" and isinstance(at[-1], int) and at[-1] >= dimension:
                finding(tuple(map(str, at[:-1])), f"{address(*map(str, at[:-1]))} has more coordinates than the "
                        f"model's {dimension} dimensions.", code="model-invalid")

    # regions, materials, conditions
    shapes = g.shapes if g else {}
    if not shapes:
        finding(("geometry", "shapes"), "The geometry has no shape.")
    domains = [n for n, r in m.regions.items() if r.kind == "domain"]
    if shapes and not domains:
        finding(("regions",), "The model has no domain region.", add("region", "domain"))
    for name in domains:
        if name not in m.assign:
            here = Address(None, ("regions", name))
            fix = [p.connect for p in graph.ports(project, m, here, f, units) if p.address == address("assign", name)] \
                if m.materials else [add("material", prop) for prop in f.properties]   # none yet: make one
            finding(("regions", name), f"The domain {name} has no material.", *fix)
    for name, region in m.regions.items():
        if region.kind != "domain" and name not in m.conditions:
            what = "outer boundary" if region.kind == "boundary" else "interface"
            kinds = [k for k, s in f.conditions.items() if region.kind in s.on]
            finding(("regions", name), f"The {what} {name} has no condition.",
                    *(add("condition", k, name) for k in kinds))
    for name, condition in m.conditions.items():
        _kinded(finding, remove, ("conditions", name), f"the condition on {name}", condition, f.conditions,
                m.regions[name].kind, params, units)
    for name, source in m.sources.items():
        region = m.regions.get(source.on)
        _kinded(finding, remove, ("sources", name), f"the source {name}", source, f.sources,
                region.kind if region else None, params, units)

    # materials: every property the formulation reads, each with what it rests on
    prop_schema = fields.fragment(Property, units)
    for name, props in m.materials.items():
        for prop in props:
            if prop not in f.properties:
                finding(("materials", name, prop), f"{m.formulation} reads no {prop!r}; it reads "
                        f"{', '.join(f.properties)}.", remove(("materials", name, prop)), code="model-invalid")
    for domain, material in m.assign.items():
        props = m.materials.get(material, {})
        for prop, spec in f.properties.items():
            p = props.get(prop)
            at = ("materials", material, prop)
            if p is None:
                finding(at, f"The material {material} has no {prop.replace('_', ' ')}, which {m.formulation} reads in "
                        f"{domain}.", add("material", prop, material))
                continue
            if p.value is None and p.table is None:
                finding(at, f"The {prop.replace('_', ' ')} of {material} has neither a value nor a table.")
            for key in STATED:
                if getattr(p, key) is None:
                    finding((*at, key), f"The {prop.replace('_', ' ')} of {material} states no {key}: a property says "
                            "what it rests on, how its complex values are written, and where it is valid.",
                            choose((*at, key), key, fields.leaf(prop_schema, (key,))))
            if not spec.complex and p.convention not in (None, "real"):
                finding((*at, "convention"), f"The {prop.replace('_', ' ')} of {material} is real in {m.formulation}.",
                        choose((*at, "convention"), "convention", {"type": "string", "enum": ["real"]}),
                        code="model-invalid")
            if p.value is not None:
                _dimension(finding, (*at, "value"), p.value, spec.unit, params, units)

    conventions = fields.fragment(Conventions, units)
    for convention in f.conventions:
        if m.conventions is None or getattr(m.conventions, convention) is None:
            finding(("conventions", convention), f"{m.formulation} requires the {convention} convention chosen; it "
                    "is never defaulted.", choose(("conventions", convention), convention,
                                                  fields.leaf(conventions, (convention,))))
    return _ordered(out)


def _ordered(out: list[tuple[int, Issue]]) -> list[Issue]:
    """The findings in the chain's order: what an object is made from before the object."""
    return [issue for _, issue in sorted(out, key=lambda pair: pair[0])]


def _kinded(finding, remove, at: tuple, label: str, item: Kinded, allowed: dict[str, KindSpec],
            region_kind: str | None, params: dict[str, Quantity], units: Units) -> None:
    spec = allowed.get(item.kind)
    if spec is None:
        finding((*at, "kind"), f"{label.capitalize()} is of kind {item.kind!r}, which the formulation does not allow; "
                f"it allows {', '.join(allowed) or 'none'}.", remove(at), code="model-invalid")
        return
    if region_kind is not None and region_kind not in spec.on:
        finding(at, f"{label.capitalize()} is a {item.kind}, which stands on a {' or '.join(spec.on)}, not a "
                f"{region_kind}.", remove(at), code="model-invalid")
    given = dict(item.model_extra or {})
    if "on" in type(item).model_fields:
        given.pop("on", None)
    for name, p in spec.parameters.items():
        if name not in given:
            finding((*at, name), f"{label.capitalize()} states no {name}: {p.description} (in {p.unit}).")
    for name, value in given.items():
        if name not in spec.parameters:
            finding((*at, name), f"{label.capitalize()} takes no {name!r}; a {item.kind} takes "
                    f"{', '.join(spec.parameters) or 'nothing'}.", remove((*at, name)), code="model-invalid")
        else:
            _dimension(finding, (*at, name), value, spec.parameters[name].unit, params, units)


def _dimension(finding, at: tuple, value, unit: str, params: dict[str, Quantity], units: Units) -> None:
    """A value is a quantity of its unit's dimension."""
    if not isinstance(value, str):
        value = str(value)
    try:
        q, want = units.parse(value, params), units.parse(unit)
    except UnitError as exc:
        finding(at, f"{address(*map(str, at))}: {exc}.", code="model-invalid")
        return
    if q.dimension != want.dimension:
        what = "a plain number" if not want.dimension else f"in the dimension of {unit}"
        finding(at, f"{address(*map(str, at))} is {value!r}, which is not {what}.", code="model-invalid")
