"""A typed value (models.md § 3; framework.md § 5): the one check of what a function of the person's
returned, and the one writer of the one store.

**The check** (`checked`) holds a returned value to its declaration — a definition's or an
observable's alike: a plain number of its declared type — an `int` a whole number, however returned
(`4` or `4.0`, kept as the integer it is), a `float` a finite real number, a whole one among them,
kept as the double it is, a `complex` a finite complex number, Python's or numpy's — or, for a value
declared over named dimensions, an xarray DataArray of its type over exactly those dimensions, a
coordinate for each, every value finite. Never its physical dimension: that is the person's promise,
written as its unit. What does not hold is `Failed`, with the line of the person's file and why.

**The writer** (`write`) keeps every declared output femkit keeps as netCDF, through xarray, inside
the environment that computed it (models.md § 3, "One store"): each variable its values in SI, its
`units` — their SI unit — its `declared_unit`, its `long_name` and its `declared_type`, over its
named dimensions, each coordinate its `units`; the file its `schema` and its provenance as global
attributes, as the caller hands them — and no time, so the same result is the same bytes. It writes
to a name beside the file and renames it in, whole. It runs in a process of its own with one thread,
so it holds no lock: the one lock around the netCDF-C library is the control process's, where the
web server's threads read (`persist.NETCDF_LOCK`, core.md § 4).

Standard library only at import (framework.md § 1): numpy and xarray, which the environments it runs
in provide, are imported where they are used.
"""

from __future__ import annotations

import cmath
import math
import os
from typing import Any, Mapping

#: How each declared type is held in a file of the store: netCDF's 64-bit integer, its double, and
#: netCDF4's complex convention.
DTYPES = {"int": "i8", "float": "f8", "complex": "c16"}
#: The attribute a file of the store states its shape in, which its reader checks (core.md § 4).
SCHEMA = "schema"


class Failed(Exception):
    """A returned value that does not hold to its declaration: the line of the person's file, and
    why."""

    def __init__(self, line: int | None, reason: str):
        super().__init__(reason)
        self.line, self.reason = line, reason


def checked(kind: str, value: Any, line: int | None, dims: Mapping[str, str] | None = None) -> Any:
    """``value``, a function's result, as its declaration holds it: a plain number of the type
    ``kind`` — or, given ``dims``, the dimensions it is declared over by name, an xarray DataArray of
    that type over exactly them, a coordinate for each, every value finite; else `Failed`, saying
    what it is instead, at ``line``."""
    if dims:
        return _array(kind, value, line, dims)
    import numpy
    real = (float, numpy.floating, int, numpy.integer)       # a whole number is a float's value too
    if kind in ("int", "float") and isinstance(value, real) and not isinstance(value, (bool, numpy.bool_)):
        whole = isinstance(value, (int, numpy.integer))
        if not whole and not math.isfinite(value):
            raise Failed(line, f"returned {value!r}, which is no finite number")
        if kind == "float":
            return float(value)
        if whole or float(value).is_integer():          # an `int` holds a whole number, 4 and 4.0 alike
            return int(value)
        raise Failed(line, f"returned {value!r}, which is no whole number, and an `int` is one")
    if kind == "complex" and isinstance(value, (complex, numpy.complexfloating)):
        if not cmath.isfinite(value):
            raise Failed(line, f"returned {value!r}, which is no finite number")
        return complex(value)
    raise Failed(line, f"returned {_said(value)}, of type {type(value).__name__}, which is no {kind}")


def _array(kind: str, value: Any, line: int | None, dims: Mapping[str, str]) -> Any:
    """An array declared over ``dims``, as `checked` holds it."""
    import numpy
    import xarray
    over = ", ".join(f"`{d}`" for d in dims)
    if not isinstance(value, xarray.DataArray):
        raise Failed(line, f"returned {_said(value)}, of type {type(value).__name__}, and it is declared a {kind} "
                           f"array over {over}: an xarray DataArray")
    if set(value.dims) != set(dims) or len(value.dims) != len(dims):
        raise Failed(line, f"returned an array over {', '.join(f'`{d}`' for d in value.dims) or 'no dimension'}, "
                           f"and it is declared over {over}")
    lacking = [d for d in dims if d not in value.coords]
    if lacking:
        raise Failed(line, f"returned an array with no coordinate for {', '.join(f'`{d}`' for d in lacking)}: each "
                           "dimension has one")
    held = value.dtype.kind
    takes = {"int": "iu", "float": "iuf", "complex": "c"}[kind]
    if held not in takes and not (kind == "int" and held == "f"):
        raise Failed(line, f"returned an array of {value.dtype}, which holds no {kind}")
    data = numpy.asarray(value.values)
    if not numpy.all(numpy.isfinite(data)):
        raise Failed(line, "returned an array holding a value that is no finite number")
    if kind == "int" and held == "f" and not numpy.all(numpy.equal(numpy.mod(data, 1), 0)):
        raise Failed(line, "returned an array holding a number that is no whole number, and an `int` is one")
    return value.astype(DTYPES[kind])


def _said(value: Any) -> str:
    """A returned value for a sentence: its text on one line, cut short."""
    text = " ".join(repr(value).split())
    return text if len(text) <= 60 else text[:57] + "..."


def write(path: str, variables: Mapping[str, Mapping[str, Any]], attributes: Mapping[str, Any]) -> None:
    """The file ``path`` of the one store, written whole, through xarray: each of ``variables`` by its
    name — its `type`, its `values` (a list along its `dims`, or a DataArray), its `units`, its
    `declared_unit`, its `long_name`, and, for a DataArray, `coordinates`, each dimension's unit — and
    ``attributes``, its `schema` and its provenance, as the file's own; no time."""
    import numpy
    import xarray
    data = {}
    for name, spec in variables.items():
        values = spec["values"]
        if isinstance(values, xarray.DataArray):
            held = values.astype(DTYPES[spec["type"]])
            for dim, unit in spec.get("coordinates", {}).items():
                held.coords[dim].attrs["units"] = unit
        else:
            held = xarray.DataArray(numpy.array(values, dtype=DTYPES[spec["type"]]), dims=tuple(spec["dims"]))
        held.attrs = {"units": spec["units"], "declared_unit": spec["declared_unit"], "long_name": spec["long_name"],
                      "declared_type": spec["type"]}
        data[name] = held
    dataset = xarray.Dataset(data, attrs=dict(attributes))
    part = path + ".part"
    dataset.to_netcdf(part, engine="netcdf4", auto_complex=True,           # one thread: the writer's own process
                      encoding={name: {"_FillValue": None} for name in [*data, *dataset.coords]})
    os.replace(part, path)
