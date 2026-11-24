"""Cases: a model, its numerics and one axis point, resolved; named by their content
(models.md § 2, § 5)."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from femkit.core.errors import Refused, UsageError
from femkit.core.paths import inside
from femkit.core.units import Quantity, UnitError, Units
from femkit.definitions.formulations import FormulationDefinition
from femkit.core import view
from femkit.models import check
from femkit.models.requests import ProjectRequest
from femkit.models.schema import Axis, ModelFile, Numerics, StudyFile, quantities
from femkit.models.requests import CASE_LIST, MODEL_CHECK

SCHEMA = 1


# ------------------------------------------------------------------ the canonical form

def exact(q: Quantity) -> dict:
    """A quantity as a case holds it: its exact value in canonical units, and its dimension."""
    return {"value": str(q.value), "dimension": {name: power for name, power in q.dimension}}


def number(value: int | Decimal) -> str:
    """A plain number in one form, whatever its spelling: `1`, `1.0` and `1e0` are `"1"`."""
    return str(Fraction(value))


def canonical(case: dict) -> bytes:
    return json.dumps(case, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def case_id(case: dict) -> str:
    """The SHA-256 of the case's canonical JSON (models.md § 5)."""
    return hashlib.sha256(canonical(case)).hexdigest()


def _set(tree: Any, at: tuple, value: Any) -> None:
    for key in at[:-1]:
        tree = tree[key]
    tree[at[-1]] = value


def _plain(tree: Any) -> Any:
    """Every number in one form, as text: `-1`, `-1.0` and a degree of `2` alike (models.md § 5)."""
    if isinstance(tree, dict):
        return {k: _plain(v) for k, v in tree.items()}
    if isinstance(tree, list):
        return [_plain(v) for v in tree]
    if isinstance(tree, (int, Decimal)) and not isinstance(tree, bool):
        return number(tree)
    return tree


# ------------------------------------------------------------------ resolving one case

def _quantity(value: Any, kind: str, units: Units, names: dict[str, Quantity], frame: Quantity | None,
              at: tuple) -> Quantity:
    try:
        if isinstance(value, (int, Decimal)):
            if kind == "coordinate":
                if frame is None:
                    raise Refused(f"{'.'.join(map(str, at))}: a bare-number coordinate, and no frame unit")
                return Quantity(Fraction(value) * frame.value, frame.dimension)
            return Quantity(Fraction(value))
        return units.parse(str(value), {} if kind == "unit" else names)
    except UnitError as exc:
        raise Refused(f"{'.'.join(map(str, at))}: {exc}") from None


def _resolved(instance, units: Units, names: dict[str, Quantity], frame: Quantity | None, skip: tuple = ()) -> dict:
    """The instance as data, each quantity in it resolved to its exact canonical form."""
    tree = _plain(instance.model_dump(mode="python", by_alias=True))
    for at, kind, value in quantities(instance):
        if at[:len(skip)] == skip and skip:
            continue
        _set(tree, at, exact(_quantity(value, kind, units, names, frame, at)))
    return tree


def apply_point(m: ModelFile, numerics: Numerics | None, point: dict[str, Any]) -> tuple[ModelFile, Numerics | None]:
    """The model and numerics with each axis's value in place: a parameter replaced (the ones
    after it are computed again from it), a numerics value set at its path."""
    params = dict(m.parameters)
    tree = numerics.model_dump(mode="python", by_alias=True) if numerics is not None else {}
    for path, value in point.items():
        head, _, rest = path.partition(".")
        if head == "parameters":
            params[rest] = value if isinstance(value, str) else number(value)
        else:
            node = tree
            keys = rest.split(".")
            for key in keys[:-1]:
                node = node.setdefault(key, {}) if isinstance(node, dict) else node
            node[keys[-1]] = value
    model = m.model_copy(update={"parameters": params})
    return model, (Numerics.model_validate(tree) if tree else numerics)


def resolve(m: ModelFile, numerics: Numerics | None, point: dict[str, Any], units: Units, project: Path) -> dict:
    """One complete case (models.md § 5)."""
    m, numerics = apply_point(m, numerics, point)
    names: dict[str, Quantity] = {}
    for name, text in m.parameters.items():
        try:
            names[name] = units.parse(text, names)
        except UnitError as exc:
            raise Refused(f"parameters.{name}, with the point applied: {exc}") from None
    frame = units.parse(m.frame.unit) if m.frame is not None else None
    model = _resolved(m, units, names, frame, skip=("parameters",))
    model["parameters"] = {name: exact(q) for name, q in names.items()}
    model.pop("frame", None)  # resolved away: every coordinate is in canonical units now
    for material, props in m.materials.items():
        for prop, p in props.items():
            if p.table is not None:
                model["materials"][material][prop].update(_table(m, material, prop, units, project))
            if isinstance(p.range, list):
                _in_range(f"materials.{material}.{prop}", p, names, units)
    return {
        "schema": SCHEMA,
        "model": model,
        "numerics": _resolved(numerics, units, names, frame) if numerics is not None else None,
        "point": {path: exact(_quantity(value, "any", units, names, frame, ("point", path)))
                  for path, value in point.items()},
    }


def _in_range(where: str, p, names: dict[str, Quantity], units: Units) -> None:
    """A case outside a property's range is refused (models.md § 3): the case's value of the
    property's variable is the model's parameter of that name."""
    if p.variable is None:
        raise Refused(f"{where}: its range is [from, to], and it names no variable that range is in")
    value = names.get(p.variable.name)
    if value is None:
        raise Refused(f"{where}: valid only from {p.range[0]} to {p.range[1]} in {p.variable.name}, and the model "
                      f"states no parameter {p.variable.name!r} giving this case's value")
    low, high = (units.parse(t, names) for t in p.range)
    if value.dimension != low.dimension or not low.value <= value.value <= high.value:
        raise Refused(f"{where}: this case's {p.variable.name} lies outside its range, {p.range[0]} to {p.range[1]}")


# ------------------------------------------------------------------ tabulated properties

def _table(m: ModelFile, material: str, prop: str, units: Units, project: Path) -> dict:
    """A tabulated property's rows, exactly, converted to the model's phasor convention (§ 3)."""
    p = m.materials[material][prop]
    where = f"materials.{material}.{prop}"
    path = (project / "custom" / p.table).resolve() if not p.table.startswith("custom/") else (project / p.table).resolve()
    if not inside(path, project / "custom") or not path.is_file():
        raise Refused(f"{where}.table: {p.table} is not a file under the project's custom/")
    data = path.read_bytes()
    if p.sha256 != hashlib.sha256(data).hexdigest():
        raise Refused(f"{where}.table: {p.table} does not match its sha256: the file changed since it was named")
    if p.variable is None:
        raise Refused(f"{where}: a table states its `variable`")
    unit = units.parse(p.variable.unit)
    target = m.conventions.phasor if m.conventions else None
    flip = p.convention not in (None, "real") and target is not None and p.convention != target
    rows = []
    for n, row in enumerate(csv.reader(data.decode("utf-8").splitlines())):
        if not row or row[0].strip().startswith("#"):
            continue
        try:
            x, real, imag = (Fraction(c.strip()) for c in row[:3])
        except (ValueError, IndexError):
            raise Refused(f"{where}.table: line {n + 1} is not three numbers: the variable, real, imaginary") from None
        imag = -imag if flip else imag
        rows.append([str(x * unit.value), str(real), str(imag)])
    passive_sign = {"exp(-iwt)": 1, "exp(+iwt)": -1}.get(target or "", 0)
    if passive_sign and any(Fraction(r[2]) * passive_sign < 0 for r in rows):
        raise Refused(f"{where}: with its convention {p.convention} converted to the model's {target}, its loss has "
                      "the wrong sign — a passive material would gain energy. Check the source's convention")
    return {"rows": rows, "variable": {"name": p.variable.name, "dimension": dict(unit.dimension)},
            "converted": f"conjugated from {p.convention} to {target}" if flip else "none"}


# ------------------------------------------------------------------ expanding a study

@dataclass(frozen=True)
class Case:
    id: str
    point: dict[str, Any]   # each axis's value as the study writes it
    data: dict


def points(study: StudyFile) -> list[dict[str, Any]]:
    """Every axis point: the axes crossed, in the order the study writes them."""
    axes = {k: a for k, a in study.axes.items() if isinstance(a, Axis)}
    classes = {a.class_ for a in axes.values()}
    if len(classes) > 1 and not isinstance(study.axes.get("reason"), str):
        raise Refused(f"the study crosses axes of different classes ({', '.join(sorted(classes))}) and does not "
                      "say why the full product is needed: state it as axes.reason (models.md § 5)")
    return [dict(zip(axes, values)) for values in itertools.product(*(a.values for a in axes.values()))]


def expand(m: ModelFile, study: StudyFile, formulations: dict[str, FormulationDefinition], units: Units,
           project: Path) -> list[Case]:
    """Every case the study produces; refused while `model check` has a finding."""
    found = check.findings(m, formulations, units, project)
    if found:
        raise Refused(f"the model has {len(found)} finding(s); a case is expanded only from a complete model: "
                      + " ".join(i.message for i in found[:3]),
                      (view.command(MODEL_CHECK, project=str(project)),))
    out: dict[str, Case] = {}
    for point in points(study):  # two spellings of one point are one case
        data = resolve(m, study.numerics, point, units, project)
        out.setdefault(case_id(data), Case(case_id(data), point, data))
    return list(out.values())


def case_dir(project: Path, cid: str) -> Path:
    return project / "cases" / cid


def written_cases(project: Path) -> dict[str, dict]:
    """Every case.json under cases/, by its ID."""
    root = project / "cases"
    out = {}
    for path in sorted(root.glob("*/case.json")) if root.is_dir() else []:
        out[path.parent.name] = json.loads(path.read_text(encoding="utf-8"))
    return out


def named(project: Path, prefix: str) -> str:
    """The case a unique prefix of its ID names (models.md § 5)."""
    matches = [cid for cid in written_cases(project) if cid.startswith(prefix)]
    if len(matches) != 1:
        raise UsageError(f"{prefix!r} names {'no case' if not matches else f'{len(matches)} cases'}: give more of "
                         "its ID", (view.command(CASE_LIST, project=str(project)),))
    return matches[0]
