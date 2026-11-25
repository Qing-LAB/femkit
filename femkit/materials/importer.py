"""A source's file read by its importer's declaration, and the new material it becomes
(materials.md § 7; the declarations are `femkit/data/importers/<source>.toml`, read by
`femkit/definitions/importers.py`): its one record as a dataset — a table and its file, or a
dispersion model with its parameters — held under the property its record gives, named by the
file's name under the name rule; its citation, plain, as the dataset's `source`, each DOI kept;
its conditions, each with its unit; its range, or a table's first and last rows; its notes —
under today's name or an older one — in the material's `[notes]`. Every key the file holds is
one its declaration maps: nothing a file says is dropped. Every number is read exactly by the
unit grammar (core.md § 11) and written as the source wrote it. The material's file is written
by the core's one writer of a person's TOML file (`persist.commented_text`) as a person's own:
each key under its help as the schema, the property list or the dispersion list states it
(`material.declared`), and each key the source leaves unset shown commented out under its help
(projects.md § 7).

Each refusal is a `UsageError` with its code, its subject the file as the request names it
(core.md § 9), its message saying what to do instead:
- `no-such-file`: no file is there;
- `bad-name`: the file's name gives no dataset's name under the name rule — rename the file so
  its name starts with a letter;
- `unreadable`: the file is not text in UTF-8, does not read in its source's format, or is not of
  the shape its declaration states — a table at its top, a list of records, each record a table,
  its notes text under one of their names;
- `unmapped-key`: it holds a key, at its top or in its record, that the declaration does not
  map, naming it — one the declaration says it does not map, with what that key can state;
- `no-source`: it states no citation — a value without a source is refused;
- `no-record`, `several-records`: it holds no record, or several, naming their types: one import
  is one dataset, and records given apart are never resampled into one;
- `unmapped-record`: its record is of a type the declaration does not map, naming it and those it
  maps;
- `unmapped-condition`: it states a condition the declaration does not map, naming it;
- `bad-value`: a value the declaration maps does not read — a key missing, a number the grammar
  does not read, a row of another length, a table whose variable does not increase, coefficients
  that do not fill whole terms, a range that is not two numbers.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import PurePath
from typing import Any, Callable, Iterable, Mapping

import yaml

from femkit.core.errors import UsageError
from femkit.core.markdown import plain
from femkit.core.persist import Shown, commented_text
from femkit.core.schema import Declared, Model, allowed, described, field_named, pointer
from femkit.core.units import Quantity, UnitError, Units, number
from femkit.definitions.dispersion import Dispersion
from femkit.definitions.importers import Importer, ModelRecord, TableRecord, property_of
from femkit.definitions.properties import Property
from femkit.materials.material import (PROPERTIES, Column, Material, Modelled, Stated, Table, TableError, declared,
                                       rows)
from femkit.projects import names


def _yaml(text: str) -> Any:
    """A YAML text, read with PyYAML's `BaseLoader`: every scalar stays text, so each number is
    read exactly by femkit's own grammar (materials.md § 7). A ValueError where it is not YAML."""
    try:
        return yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise ValueError(str(exc)) from None


#: Each format an importer may declare its files are written in, and its reader.
READERS: dict[str, Callable[[str], Any]] = {"yaml": _yaml}

#: A table's file, beside the material's own, by its dataset's name (materials.md § 3).
TABLE_FILE = "{dataset}.csv"

#: What a key the source leaves unset is shown with, where its value goes (projects.md § 7).
UNSET = "…"


@dataclass(frozen=True)
class Imported:
    """A source's file as the new material it becomes: the property its dataset is held under,
    the dataset's name, and the material's files by their paths from its folder, its own first."""

    property: str
    dataset: str
    files: dict[str, bytes]


def dataset_name(file: str) -> str:
    """The dataset's name, from the file's (materials.md § 7: `Johnson.yml`, `johnson`): its stem in
    lower case, each run of characters the name rule does not allow one `_`, none at either end.
    Refused, `bad-name`, where that is no step of the name rule."""
    name = re.sub(r"[^a-z0-9_]+", "_", PurePath(file).stem.lower()).strip("_")
    if not re.fullmatch(names.STEP, name):
        raise UsageError(f"the name of {file} gives no dataset's name, which is the file's name in lowercase letters, "
                         "digits and `_`, starting with a letter: rename the file so its name starts with a letter, "
                         "and import it again", code="bad-name", subject=file)
    return name


def imported(importer: Importer, source: str, file: str, data: bytes | None, *, name: str, own: str,
             properties: Mapping[str, Property], dispersion: Dispersion, units: Units,
             manual: str | None = None) -> Imported:
    """The material ``name`` — its own file called ``own``, its keys' help ending, where its schema
    states a `doc`, with ``manual``, the chapter of the manual its kind declares — that ``data``,
    the bytes of ``file`` from ``source``, becomes by ``importer``, its declaration (module
    docstring); refused as the module docstring lists, each a `UsageError` about ``file``."""

    def refused(code: str, message: str) -> UsageError:
        return UsageError(f"{file}: {message}", code=code, subject=file)

    if data is None:
        raise refused("no-such-file", "no file is there")
    dataset = dataset_name(file)
    keys = importer.keys
    doc = _document(importer, data, refused)
    _known(doc, "it", importer.mapped, importer.unmapped, refused)
    references = doc.get(keys.references)
    if not isinstance(references, str) or not references.strip():
        raise refused("no-source", f"it states no `{keys.references}`, and data without a source is never imported")
    records = doc.get(keys.records)
    if records is not None and (not isinstance(records, list) or not all(isinstance(r, dict) for r in records)):
        raise refused("unreadable", f"its `{keys.records}` is not a list of records, each a table")
    if not records:
        raise refused("no-record", f"it holds no record in `{keys.records}`")
    if len(records) > 1:
        raise refused("several-records", f"it holds {len(records)} records — "
                                         f"{', '.join(str(r.get(keys.type)) for r in records)} — and one import is "
                                         "one dataset: records given apart, each on its own points, would have to "
                                         "be resampled onto one another to make one, which femkit never does to a "
                                         "source's data. A file holding one record of a type femkit maps — "
                                         f"{', '.join(importer.records)} — imports")
    record = records[0]
    kind = record.get(keys.type)
    mapping = importer.records.get(kind) if isinstance(kind, str) else None
    if mapping is None:
        raise refused("unmapped-record", f"its record is of the type {kind!r}, which femkit's importer maps onto no "
                                         f"dataset; it maps {', '.join(importer.records)}")
    _known(record, "its record", (keys.type, keys.range, *mapping.holds()), {}, refused)

    def read(value: Any, what: str) -> str:
        """``value``, a number as the source wrote it; `bad-value` where the grammar does not read it."""
        try:
            number(value if isinstance(value, str) else "")
        except UnitError:
            raise refused("bad-value", f"{what} is {value!r}, no decimal number") from None
        return value

    def quantity(value: str, unit: str) -> str:
        """A number the source wrote, with its unit, as a material writes a quantity: alone, for a
        plain number (core.md § 11)."""
        return value if units.parse(unit) == Quantity(Fraction(1)) else f"{value} {unit}"

    variable = importer.variable
    stated: dict[str, Any] = {}
    for key, value in _conditions(doc, keys.conditions, refused).items():
        if key not in importer.conditions:
            raise refused("unmapped-condition", f"it states the condition {key!r}, which femkit's importer does not "
                                                f"map; it maps {', '.join(importer.conditions) or 'none'}")
        condition = importer.conditions[key]
        stated[condition.name] = quantity(read(value, f"its condition {key}"), condition.unit)
    span = record.get(keys.range)
    if span is not None:
        bounds = span.split() if isinstance(span, str) else []
        if len(bounds) != 2:
            raise refused("bad-value", f"its record's `{keys.range}` is {span!r}, not two numbers")
        span = [quantity(read(b, f"its record's {keys.range}"), variable.unit) for b in bounds]
    stated["source"] = plain(references, lambda shown, to: next((f"{shown}, doi:{to.removeprefix(p)}"
                                                                 for p in importer.doi if to.startswith(p)), shown))
    files: dict[str, bytes] = {}
    if isinstance(mapping, TableRecord):
        form, prop = Table, property_of(properties, source, mapping.property)[0]
        table = TABLE_FILE.format(dataset=dataset)
        files[table], ends = _table(record, mapping, variable.name, read, refused)
        head = {"table": table, "sha256": hashlib.sha256(files[table]).hexdigest(),
                "interpolation": mapping.interpolation}
        stated |= {"convention": mapping.convention, "range": span or [quantity(e, variable.unit) for e in ends]}
        within = {"variable": {"name": variable.name, "unit": variable.unit}}
    else:
        model = dispersion.models[mapping.model]
        form, prop = Modelled, model.gives
        head = {"model": mapping.model}
        stated |= {"convention": model.convention, **({"range": span} if span else {})}
        within = {"parameters": _parameters(record, mapping, read, quantity, refused)}
    held = {**head, **_stated(stated, variable.unit, dispersion), **within}
    notes = _notes(doc, keys.notes, refused)
    material = {"schema": max(allowed(field_named(Material, "schema")[1].annotation)), "display": names.last(name),
                "formula": Shown(""), "aliases": Shown([]), PROPERTIES: {prop: {dataset: held}},
                "notes": {dataset: notes} if notes else Shown({})}
    # the help the property list and the dispersion list give its keys, read from the file as it
    # writes them — its dataset's model among them — as a template's is
    helps = declared(properties, dispersion, commented_text(material, lambda path: None))
    text = commented_text(material, _comments(form, helps, manual),
                          prose=f"Written by `material import` from {source}'s file {PurePath(file).name}; yours "
                                "from now on, as a file you wrote is" + (f" {pointer(manual)}" if manual else "")
                                + ".")
    return Imported(property=prop, dataset=dataset, files={own: text.encode("utf-8"), **files})


def _document(importer: Importer, data: bytes, refused: Callable[[str, str], UsageError]) -> dict[str, Any]:
    """The file read in its format: a table at its top; `unreadable` otherwise."""
    try:
        doc = READERS[importer.format](data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise refused("unreadable", f"this is not text written in UTF-8: byte {exc.start + 1} is not") from None
    except ValueError as exc:
        raise refused("unreadable", f"it does not read as {importer.format.upper()}: {exc}") from None
    if not isinstance(doc, dict):
        raise refused("unreadable", "it holds no table at its top, as a file of its source does")
    return doc


def _known(held: Mapping[str, Any], where: str, mapped: Iterable[str], unmapped: Mapping[str, str],
           refused: Callable[[str, str], UsageError]) -> None:
    """Each key ``held`` — the file's top, or its record — holds is one ``mapped`` names: nothing a
    file says is dropped (materials.md § 7). `unmapped-key` otherwise, naming it, and saying what
    it can state for one of ``unmapped``, which the declaration knows and does not map."""
    mapped = tuple(mapped)
    for key in held:
        if key in unmapped:
            raise refused("unmapped-key", f"{where} holds `{key}`, which femkit's importer does not map, and nothing "
                                          f"a file says is dropped: {unmapped[key]}")
        if key not in mapped:
            raise refused("unmapped-key", f"{where} holds `{key}`, which femkit's importer does not know — it reads "
                                          f"{', '.join(f'`{k}`' for k in mapped)} — and nothing a file says is "
                                          "dropped; where what it states changes nothing of the data, a copy of the "
                                          "file without it imports")


def _conditions(doc: dict[str, Any], key: str, refused: Callable[[str, str], UsageError]) -> dict[str, Any]:
    """The conditions the file states, by name; none where it states none."""
    held = doc.get(key)
    if held is not None and not isinstance(held, dict):
        raise refused("unreadable", f"its `{key}` is not a table of conditions")
    return held or {}


def _notes(doc: dict[str, Any], keys: list[str], refused: Callable[[str, str], UsageError]) -> str | None:
    """The source's notes, under today's name or an older one, as written, without the white
    space at either end; None where it states none. `unreadable` where they are not text, or
    stated under two of their names."""
    given = [k for k in keys if k in doc]
    if len(given) > 1:
        raise refused("unreadable", f"it states its notes twice, under {' and '.join(f'`{k}`' for k in given)}, "
                                    f"names of one key: a copy of the file holding them under `{keys[0]}` alone "
                                    "imports")
    notes = doc[given[0]] if given else None
    if notes is not None and not isinstance(notes, str):
        raise refused("unreadable", f"its `{given[0]}` is not text")
    return (notes.strip() or None) if notes is not None else None


def _table(record: dict[str, Any], mapping: TableRecord, variable: str, read: Callable[[Any, str], str],
           refused: Callable[[str, str], UsageError]) -> tuple[bytes, list[str]]:
    """A table record's rows as the table's file (materials.md § 3): a first row naming the
    variable and each column, then one row per point, each number as the source wrote it — read
    by `rows`, the one reader of a table's shape, so a table whose variable does not increase is
    refused here; and its first and last rows' variable, as the source wrote them."""
    data = record.get(mapping.data)
    if not isinstance(data, str):
        raise refused("bad-value", f"its record states no `{mapping.data}`")
    width = 1 + len(mapping.columns)
    lines = [line.split() for line in data.splitlines() if line.strip()]
    for i, cells in enumerate(lines, 1):
        if len(cells) != width:
            raise refused("bad-value", f"row {i} of its `{mapping.data}` holds {len(cells)} numbers, not {width}: the "
                                       f"{variable}, then {', '.join(mapping.columns)}")
        for cell in cells:
            read(cell, f"a value of row {i} of its `{mapping.data}`")
    out = "".join(",".join(row) + "\n" for row in [[variable, *mapping.columns], *lines]).encode("utf-8")
    try:
        rows(out, mapping.convention)
    except TableError as exc:
        raise refused("bad-value", f"row {exc.line - 1} of its `{mapping.data}`: {exc.why}") from None
    return out, [lines[0][0], lines[-1][0]]


def _parameters(record: dict[str, Any], mapping: ModelRecord, read: Callable[[Any, str], str],
                quantity: Callable[[str, str], str], refused: Callable[[str, str], UsageError]) -> dict[str, Any]:
    """A model record's coefficients as its model's parameters, in the order its declaration gives
    them: the leading parameters, then the list of terms, term after term — each with its unit."""
    given = record.get(mapping.coefficients)
    if not isinstance(given, str):
        raise refused("bad-value", f"its record states no `{mapping.coefficients}`")
    coefficients = [read(c, f"a coefficient in its `{mapping.coefficients}`") for c in given.split()]
    lead, term = list(mapping.parameters.items()), list(mapping.term.items())
    rest = coefficients[len(lead):]
    if len(coefficients) < len(lead) or len(rest) % len(term):
        raise refused("bad-value", f"its `{mapping.coefficients}` hold {len(coefficients)} numbers: "
                                   f"{', '.join(k for k, _ in lead) or 'none'} first, then "
                                   f"{', '.join(k for k, _ in term)} for each term, so whole terms")
    out: dict[str, Any] = {k: quantity(c, unit) for (k, unit), c in zip(lead, coefficients)}
    out[mapping.sum] = [{k: quantity(c, unit) for (k, unit), c in zip(term, rest[i:i + len(term)])}
                        for i in range(0, len(rest), len(term))]
    return out


# ------------------------------------------------------------------ the material's file

def _stated(stated: Mapping[str, Any], unit: str, dispersion: Dispersion) -> dict[str, Any]:
    """What the dataset states (materials.md § 3), in its schema's order: each value the source
    gives, and each it leaves unset shown — `…` where its value goes, with the unit it is written
    in: a range's in ``unit``, the source's, a condition's in its variable's (projects.md § 7)."""
    out: dict[str, Any] = {}
    for name, field in Stated.model_fields.items():
        key = field.alias or name
        if key in stated:
            out[key] = stated[key]
        elif key == "range":
            out[key] = Shown([f"{UNSET} {unit}"] * 2)
        else:
            out[key] = Shown(f"{UNSET} {dispersion.variables[key].unit}" if key in dispersion.variables else UNSET)
    return out


def _comments(form: type[Model], helps: Declared, manual: str | None) -> Callable[[tuple[str, ...]], str | None]:
    """The comment above each key of the new material's file, by its path: its help as the
    property list or the dispersion list states it (``helps``), else as its schema — the
    material's, its dataset's ``form``, a table's variable's — states it, ending, where the schema
    states a `doc`, with ``manual``, the chapter of the manual (core.md § 2); a dataset's name,
    which the source gives, its note; none for a key of `[notes]`, which the person names."""

    def schema_help(model: type[Model], key: str) -> str:
        return described(field_named(model, key)[1], manual)

    def comment(path: tuple[str, ...]) -> str | None:
        if (said := helps(path)) is not None:
            return said
        if len(path) == 1:
            return schema_help(Material, path[0])
        if path[0] != PROPERTIES or len(path) < 3:
            return None
        if len(path) == 3:
            return f"the dataset named `{path[2]}`"
        if len(path) == 4:
            return schema_help(form, path[3])
        return schema_help(Column, path[4]) if len(path) == 5 and path[3] == "variable" else None

    return comment
