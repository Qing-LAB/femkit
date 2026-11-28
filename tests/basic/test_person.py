"""The one way femkit runs the person's Python (framework.md §§ 5, 6; models.md §§ 3, 5.2): the one
static reader of a file of their functions, told what it may import and the module it is given,
each function's signature read for its caller to hold; the one check of a typed value a function
returned; and the one reader of the one store, `persist.read_record`, through netCDF4 under one
process-wide lock (core.md § 4). The store's writer and an array's check run through xarray, which
the control environment does not hold: their tests are the engine tier's (tests/engine/test_person.py)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal

import pytest
from pydantic import Field

from femkit.core import persist
from femkit.core.schema import Model
from femkit.engines.person import functions, values

OBSERVE = """import numpy as np
import os
from xarray import DataArray
open({mark!r}, "w")


def potential_middle(case):
    return float(np.mean([case.defs.height]))


def energy_low(case, more):
    return 0.0


def everything(*cases):
    return 1.0


def helper():
    return 2
"""


def test_a_file_of_functions_is_read_without_running_it_each_signature_and_each_fault_at_its_line(tmp_path):
    """Fails if a file of the person's functions is run to be read — a statement at its top level
    would leave its mark — or if the one static reader does not give each function's positional
    arguments, so its caller holds it to its signature — one, `case`, for an observable's — or does
    not say, at its line and naming the file, a statement at its top level that is no import or
    function and an import of what it may not import (framework.md § 5: "the one static reader,
    told the signature each function must have — … one argument for an observable's — and what its
    file may import"; models.md § 5.2)."""
    mark = tmp_path / "ran"
    text = OBSERVE.format(mark=str(mark))
    written = functions.read(text, name="observe.py", modules=["numpy", "xarray"])
    assert {n: f.arguments for n, f in written.functions.items()} == {
        "potential_middle": 1, "energy_low": 2, "everything": None, "helper": 0}
    lines = text.splitlines()
    faults = {(f.code, f.line) for f in written.faults}
    assert faults == {("bad-import", lines.index("import os") + 1),
                      ("top-level", lines.index(f"open({str(mark)!r}, \"w\")") + 1)}
    assert all("observe.py" in f.message for f in written.faults) and not mark.exists()


def test_the_module_femkit_gives_is_read_as_its_alias_and_nothing_else_of_it():
    """Fails if a file given a module of femkit's — `definitions.py`, `project.definitions` as `defs`
    — may import it under another name, or if what each function reads of it, through each function
    it calls, is not read; or if a file given none may import it (models.md § 3: "`project.definitions`
    … reads each definition as `defs.<name>`")."""
    text = ("import project.definitions as defs\nimport project.definitions as d\n\n\n"
            "def inner():\n    return defs.side\n\n\ndef outer():\n    return inner() * defs.bias\n")
    given = functions.read(text, name="definitions.py", modules=[], gives=("project.definitions", "defs"))
    assert [(f.code, f.line) for f in given.faults] == [("bad-import", 2)]
    assert given.reads("outer") == {"bias": 10, "side": 6}
    alone = functions.read(text, name="observe.py", modules=["numpy"])
    assert [f.code for f in alone.faults] == ["bad-import", "bad-import"]


@pytest.mark.parametrize("kind, returned, kept", [
    ("int", 4, 4), ("int", 4.0, 4), ("float", 2, 2.0), ("float", 0.5, 0.5), ("complex", 1 + 2j, 1 + 2j),
], ids=["an int", "a whole float for an int", "a whole number for a float", "a float", "a complex"])
def test_a_number_returned_is_kept_as_its_declared_type(kind, returned, kept):
    """Fails if a number a function returns is not kept as its declared type — an `int` the count a
    whole number holds, however returned, a `float` the double it is, a whole one among them, a
    `complex` as it is (models.md § 3: "One check holds what a function returns to its declaration —
    its type …"; "an `int` holds a whole number, a `float` may be written `10` and is a double")."""
    got = values.checked(kind, returned, 3)
    assert got == kept and type(got) is type(kept)


@pytest.mark.parametrize("kind, returned, said", [
    ("int", 2.5, "no whole number"), ("float", float("nan"), "no finite number"),
    ("complex", complex("inf"), "no finite number"), ("float", True, "which is no float"),
    ("float", "1.0", "which is no float"), ("float", [1.0], "which is no float"), ("complex", 1.0, "no complex"),
], ids=["an int not whole", "not finite", "a complex not finite", "a truth value", "a text", "a list",
        "a real for a complex"])
def test_what_is_no_finite_number_of_its_type_is_refused_at_its_line(kind, returned, said):
    """Fails if a returned value that is no finite number of its declared type is kept, or refused
    without its line and why (models.md § 3: "One check holds what a function returns to its
    declaration — its type …, every value finite"; "a result not a finite number of its declared
    type … each at the file and the line")."""
    with pytest.raises(values.Failed) as caught:
        values.checked(kind, returned, 7)
    assert caught.value.line == 7 and said in caught.value.reason


# ------------------------------------------------------------------ the one store's reader

class Point(Model):
    dimensions: list[Literal["point"]]
    attributes: dict[str, str]
    values: list[int | float | complex]


class Shape(Model):
    schema_: Literal[2] = Field(alias="schema")
    study: str


class Stored(Model):
    attributes: Shape
    variables: dict[str, Point]


def stored(path: Path, schema: int = 2, **variables) -> Path:
    """A netCDF file holding ``variables`` along `point`, its attributes `schema` and `study`."""
    import netCDF4
    import numpy
    with netCDF4.Dataset(str(path), "w", auto_complex=True) as ds:
        ds.createDimension("point", len(next(iter(variables.values()))))
        for name, held in variables.items():
            array = numpy.array(held)
            v = ds.createVariable(name, array.dtype, ("point",))
            v[:] = array
            v.units = "m"
        ds.setncattr("schema", schema)
        ds.setncattr("study", "check")
    return path


def test_a_netcdf_file_of_the_store_is_read_by_its_model_its_schema_checked(tmp_path):
    """Fails if a netCDF file of the one store is not read back by `read_record` as its model
    describes it — its attributes, each variable's dimensions, attributes and values of their stored
    types, a complex one as complex — or if one stating another `schema`, or one that is no netCDF,
    reads, or an absent one is there (core.md § 4: "A netCDF file of the one store … is read back by
    the same `read_record` … its `schema` attribute checked as a record's `schema` is")."""
    file = stored(tmp_path / "values.nc", gap=[1e-8, 2e-8], layers=[2, 5], amplitude=[1 + 0.5j, -1j])
    held = persist.read_record(file, Stored)
    assert held.reads, held.problem
    assert held.value.attributes.study == "check"
    assert {n: v.values for n, v in held.value.variables.items()} == {
        "gap": [1e-8, 2e-8], "layers": [2, 5], "amplitude": [1 + 0.5j, -1j]}
    assert type(held.value.variables["layers"].values[0]) is int
    assert held.value.variables["gap"].attributes == {"units": "m"}
    other = persist.read_record(stored(tmp_path / "other.nc", schema=1, gap=[1.0]), Stored)
    assert other.there and not other.reads and "schema" in other.problem
    (tmp_path / "text.nc").write_text("no netCDF")
    broken = persist.read_record(tmp_path / "text.nc", Stored)
    assert broken.there and not broken.reads
    assert not persist.read_record(tmp_path / "absent.nc", Stored).there


def test_every_read_of_the_store_holds_the_one_process_wide_lock(tmp_path):
    """Fails if a read of a netCDF file of the store enters the netCDF-C library while another
    thread of the process holds the store's lock: two threads inside the library at once crash the
    process, as the person's earlier tool measured (core.md § 4: "Every call into the netCDF-C library
    in the control process holds one process-wide lock, `persist.NETCDF_LOCK`")."""
    file = stored(tmp_path / "values.nc", gap=[1.0])
    done = threading.Event()
    with persist.NETCDF_LOCK:
        reader = threading.Thread(target=lambda: (persist.read_record(file, Stored), done.set()))
        reader.start()
        assert not done.wait(0.5)
    assert done.wait(10)
    reader.join()
