"""`material import` (materials.md § 7; models.md § 11.1; projects.md § 7): a new material from
another source's file — refractiveindex.info's, declared in `femkit/data/importers/` — in a
template copy's project or a test root's global library: Johnson and Christy's gold, a table, and
Malitson's silica, a Sellmeier model, each passing `project check` and giving the science
document's values; the file written as a person's own; every key a file holds mapped or the file
refused; never over or into a material there; the plan resting on the file's digest, holding the
lock of what it writes into and saying when the project's material will be found before the
library's; each refusal told apart by its code and subject, and offering what to do instead. The
files are tests/basic/data/refractiveindex_info/: two from refractiveindex.info's database (CC0
1.0), cut short, and two made from them — an older file's `COMMENTS`, and a `SPECS` block."""

from __future__ import annotations

import hashlib
import shutil
import tomllib
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from tests import kit
from tests.kit import laplace, slab  # noqa: F401 -- fixtures
from femkit.core.errors import Busy, PlanStale, Refused, UsageError
from femkit.core.persist import exact_number, key_comments
from femkit.core.schema import Measure, Number, declared_by, help_findings, key_path
from femkit.core.units import Quantity
from femkit.definitions import catalogue
from femkit.definitions.catalogue import CatalogueError
from femkit.materials import data, material
from femkit.materials.data import Complex
from femkit.projects import layout
from femkit.projects.project import Library, Project
from tests.basic.test_templates import CITED

DATA = Path(__file__).resolve().parent / "data" / "refractiveindex_info"
SOURCE = "refractiveindex_info"
LIBRARY = "materials"                       # the global library's folder at the root (materials.md § 4)
#: The two materials, each by the name it is imported as, its file, the property its dataset is
#: held under and the dataset's name.
GOLD = ("metals/gold", "Johnson.yml", "refractive_index", "johnson")
SILICA = ("silica", "Malitson.yml", "relative_permittivity", "malitson")


def importing(project: Path, name: str, file: str | Path, into: str = "project"):
    """`material import` of ``file`` — one of the two, or a test's own — as ``name``, into the
    project ``project`` or the global library of its root."""
    return kit.apply("material.import", source=SOURCE, file=str(DATA / file), name=name, into=into,
                     project=project.name)


def written(folder: Path) -> dict:
    """A written material's file, as femkit reads it: each number exactly, as written."""
    return tomllib.loads((folder / "material.toml").read_text(encoding="utf-8"), parse_float=exact_number)


def q(value: str, unit: str) -> Quantity:
    """``value`` in ``unit``, exactly, as the one quantity form reads it (core.md § 11)."""
    return catalogue.units(kit.ctx()).measure(Measure[Number](value=Decimal(value), unit=unit))


def taken(opened, address: str, prop: str, dataset: str, at: Quantity, convention: str) -> Complex:
    """A material's dataset, as the door opened it, taken by `femkit.materials.data` for a
    formulation reading the relative permittivity in ``convention`` at ``at``."""
    ctx = kit.ctx()
    part = opened.parts[address]
    held = part.data.properties[prop][dataset]
    files = opened.held_by(part.address)
    units = catalogue.units(ctx)
    return data.taken(held, prop, "relative_permittivity", at, convention,
                      file=files[held.table].data if isinstance(held, material.Table) else None,
                      properties=catalogue.properties(ctx), dispersion=catalogue.dispersion(ctx), units=units,
                      subject=address)


# ------------------------------------------------------------------ the acceptance

@pytest.mark.parametrize("into", ["project", "library"])
def test_gold_and_silica_imported_pass_project_check_and_give_the_science_documents_values(slab, into):
    """Fails if Johnson and Christy's gold or Malitson's silica, imported from refractiveindex.info's
    files into a project or into the global library — named there by `GLOBAL/<name>` — is other
    than a material `project check` finds nothing on, or, taken by `femkit.materials.data`, does
    not give material-data.md § 8's values: gold at 0.5821 µm eps = -8.112669 + 1.66054i under
    exp(-iwt), exactly; silica n = 1.4585 at 0.5876 µm, to four decimals (materials.md § 7; plan
    § 4, E: "imported from their refractiveindex.info files into new materials that pass `project
    check`, and evaluated to the science document's check values"). Science: protected."""
    prefix = "GLOBAL/" if into == "library" else ""
    for name, file, _, _ in (GOLD, SILICA):
        assert importing(slab, name, file, into).ok()
    component = slab / "components" / "slab" / "component.toml"
    kit.rewrite(component, 'material = "dielectric_1"', f'material = "{prefix}{GOLD[0]}"')
    kit.rewrite(component, 'material = "dielectric_2"', f'material = "{prefix}{SILICA[0]}"')
    checked = kit.run("project.check", project="slab")
    ours = {f"material:{prefix}{name}" for name, *_ in (GOLD, SILICA)}
    assert {p.part: p.state for p in checked.parts if p.part in ours} == dict.fromkeys(ours, "complete")
    assert [i for i in checked.issues if any(i.subject.startswith(a) for a in ours)] == []
    opened = kit.opened(slab)
    gold = taken(opened, f"material:{prefix}{GOLD[0]}", GOLD[2], GOLD[3], q("0.5821", "um"), "exp(-iwt)")
    assert gold == Complex(Fraction("-8.112669"), Fraction("1.66054"))
    eps = taken(opened, f"material:{prefix}{SILICA[0]}", SILICA[2], SILICA[3], q("0.5876", "um"), "real")
    assert eps.im == 0 and Fraction("1.45845") ** 2 <= eps.re < Fraction("1.45855") ** 2


def test_an_import_into_a_project_adds_no_finding_to_its_check(laplace):
    """Fails if a material imported into a project, named by no assignment, adds any finding to
    that project's `project check` — an error, a warning or a note (materials.md § 7: the written
    file is one `project check` checks as the person's own; projects.md § 6)."""
    before = kit.run("project.check", project=laplace.name).issues
    for name, file, _, _ in (GOLD, SILICA):
        importing(laplace, name, file)
    assert kit.run("project.check", project=laplace.name).issues == before


def test_a_material_imported_into_a_project_offers_its_check_and_one_into_the_library_none(laplace):
    """Fails if `material import` into a project does not end with `project check` of that project
    as its next step, or an import into the global library, which no project names yet, offers one
    (plan.md § 2, rows 3–5: a project's files written, the project is checked)."""
    name, file, _, _ = GOLD
    into_project = importing(laplace, name, file)
    assert [(a.call.operation, a.call.request) for a in into_project.next] == [
        ("project.check", {"project": laplace.name})]
    assert importing(laplace, "kept", file, into="library").next == []


def keys_of(value: dict, at: tuple = ()) -> set[tuple]:
    """Every key a TOML text sets, by its path as `key_comments` gives it — a list's tables' keys
    under the list's own path; a quantity's `{value, unit}` one value, written on its key's line
    (core.md § 11)."""
    out = set()
    for key, held in value.items():
        quantity = isinstance(held, dict) and set(held) == {"value", "unit"}
        tables = isinstance(held, list) and held and all(isinstance(v, dict) for v in held)
        for each in (held if tables else [held] if isinstance(held, dict) and not quantity else []):
            out |= keys_of(each, (*at, key))
        if not tables and (quantity or not isinstance(held, dict)):
            out.add((*at, key))
    return out


def test_the_written_material_carries_each_keys_help_as_a_template_does(laplace, tmp_path):
    """Fails if a material `material import` writes — a table's, a model's, and a model's whose
    source states no range — holds a key whose comment is not its help as its schema, the property
    list or the dispersion list states it — ending, where its schema states a `doc`, with the
    material kind's chapter of the manual — or a comment citing a contract or the plan (docs/README.md
    § 3.1, M5), a model's parameter or a term's the dispersion list
    gives no help, a key its schema does not allow, a key written inside an inline table, where no
    help stands above it, or a key of a table it writes neither set nor shown commented out; or if
    the range the source does not state is not shown commented out under its help (materials.md
    § 7: "each key under its help, as a template's — a model's parameters under the help the
    dispersion list gives them, and a key it cannot fill, such as a range the source does not
    state, shown commented out under its help"; projects.md § 7; core.md § 2, `help_findings`)."""
    ctx = kit.ctx()
    shipped = layout.read()
    manual = shipped.kinds[shipped.kind_of(material.KEY)].manual
    rangeless = tmp_path / "Rangeless.yml"
    rangeless.write_text((DATA / SILICA[1]).read_text(encoding="utf-8").replace("    wavelength_range: 0.21 6.7\n", ""),
                         encoding="utf-8")
    found, ranges = {}, {}
    for name, file in ((GOLD[0], GOLD[1]), (SILICA[0], SILICA[1]), ("rangeless", rangeless)):
        importing(laplace, name, file)
        text = (laplace / "materials" / name / "material.toml").read_text(encoding="utf-8")
        helps = declared_by(material.keys(catalogue.properties(ctx), catalogue.dispersion(ctx), text))
        entries = key_comments(text)
        found[name] = [str(f) for f in help_findings(text, material.Material, helps, manual)]
        found[name] += [f"cites {cited[0]}" for cited in [CITED.search(text)] if cited is not None]
        found[name] += [f"{key_path(p)}: inline" for p in keys_of(tomllib.loads(text)) - {e.path for e in entries}]
        found[name] += [f"{key_path(e.path)}: no help declared" for e in entries
                        if e.path[3:4] == ("parameters",) and len(e.path) > 4 and helps(e.path) is None]
        ranges[name] = [e.shown for e in entries if e.path[3:] == ("range",)]
    assert found == {GOLD[0]: [], SILICA[0]: [], "rangeless": []}
    assert ranges == {GOLD[0]: [False], SILICA[0]: [False], "rangeless": [True]}
    held = written(laplace / "materials" / "rangeless")["properties"]["relative_permittivity"]["rangeless"]
    assert "range" not in held and held["parameters"]["terms"][2] == {
        "B": Decimal("0.8974794"), "C": {"value": Decimal("9.896161"), "unit": "um"}}


# ------------------------------------------------------------------ what it writes

def test_a_table_record_becomes_a_table_dataset_and_its_file_the_numbers_as_the_source_wrote_them(laplace):
    """Fails if `tabulated nk` does not become a `refractive_index` table named by the file's name
    — its display the name's last step, its source the citation with its link reduced to its text,
    its emphasis gone and its DOI kept, `exp(-iwt)`, its range the table's first and last rows
    with their unit, its notes the material's — whose file is a first row naming the wavelength,
    n and k, then each row of the source, each number as the source wrote it, under the SHA-256
    the dataset states (materials.md §§ 3, 7)."""
    importing(laplace, GOLD[0], GOLD[1])
    folder = laplace / "materials" / GOLD[0]
    held = written(folder)
    dataset = held["properties"]["refractive_index"]["johnson"]
    source = (DATA / GOLD[1]).read_text(encoding="utf-8")
    rows = [line.split() for line in source.split("data: |\n")[1].splitlines() if line.strip()]
    table = (folder / "johnson.csv").read_bytes()
    assert table.decode() == "".join(",".join(r) + "\n" for r in [["wavelength", "n", "k"], *rows])
    assert ["1.30", "1.350"] in [r[1:] for r in rows]                        # trailing zeros, as written
    assert (held["display"], list(held["properties"]), held["notes"]) == ("gold", ["refractive_index"],
                                                                         {"johnson": "Room temperature"})
    assert 'range = {value = [0.1879, 1.9370], unit = "um"}' in (folder / "material.toml").read_text()  # as written
    assert dataset == {
        "table": "johnson.csv", "sha256": hashlib.sha256(table).hexdigest(), "interpolation": "linear",
        "convention": "exp(-iwt)", "range": {"value": [Decimal("0.1879"), Decimal("1.9370")], "unit": "um"},
        "variable": {"name": "wavelength", "unit": "um"},
        "source": "P. B. Johnson and R. W. Christy. Optical constants of the noble metals. Phys. Rev. B 6, "
                  "4370-4379 (1972), doi:10.1103/PhysRevB.6.4370"}
    assert sorted(p.name for p in folder.iterdir()) == ["johnson.csv", "material.toml"]


def test_a_formula_record_becomes_a_sellmeier_model_its_coefficients_as_material_data_maps_them(laplace, tmp_path):
    """Fails if `formula 1` does not become a `relative_permittivity` `sellmeier` dataset with A =
    C1 and each term's B and C the next two coefficients, C a resonance wavelength in µm, its
    range the record's, its temperature the file's condition in K, every DOI of its citation kept;
    or if `formula 2`, the same coefficients with each pole stated as its square in µm², does not
    give the same permittivity exactly (materials.md § 7; material-data.md §§ 6.1, 8)."""
    importing(laplace, SILICA[0], SILICA[1])
    dataset = written(laplace / "materials" / SILICA[0])["properties"]["relative_permittivity"]["malitson"]
    assert {k: v for k, v in dataset.items() if k != "source"} == {
        "model": "sellmeier", "convention": "real", "range": {"value": [Decimal("0.21"), Decimal("6.7")], "unit": "um"},
        "temperature": {"value": 293, "unit": "K"},
        "parameters": {"A": 0, "terms": [{"B": Decimal(b), "C": {"value": Decimal(c), "unit": "um"}}
                                         for b, c in (("0.6961663", "0.0684043"), ("0.4079426", "0.1162414"),
                                                      ("0.8974794", "9.896161"))]}}
    assert "doi:10.1364/JOSA.55.001205" in dataset["source"]
    assert "doi:10.1016/S0022-3093(97)00438-9" in dataset["source"]
    assert not any(mark in dataset["source"] for mark in ("*", "[", "](", "<br>", "\n"))
    poles = ["0.0684043", "0.1162414", "9.896161"]
    squares = (DATA / SILICA[1]).read_text(encoding="utf-8").replace("formula 1", "formula 2")
    for pole in poles:
        squares = squares.replace(f" {pole}", f" {Decimal(pole) ** 2}")
    (tmp_path / "Squares.yml").write_text(squares, encoding="utf-8")
    importing(laplace, "squares", tmp_path / "Squares.yml")
    terms = written(laplace / "materials" / "squares")["properties"]["relative_permittivity"]["squares"]["parameters"]
    assert [t["C"] for t in terms["terms"]] == [{"value": Decimal(p) ** 2, "unit": "um^2"} for p in poles]
    opened = kit.opened(laplace)
    assert taken(opened, "material:squares", "relative_permittivity", "squares", q("0.5876", "um"), "real") == \
        taken(opened, f"material:{SILICA[0]}", "relative_permittivity", "malitson", q("0.5876", "um"), "real")


def test_a_record_of_real_values_becomes_a_real_table(laplace, tmp_path):
    """Fails if `tabulated n` does not become a `refractive_index` table of `real` data whose file's
    first row names the wavelength and n alone, passing `project check` (materials.md § 7)."""
    (tmp_path / "Own-2026.yml").write_text("REFERENCES: |\n    A test's own table.\nDATA:\n  - type: tabulated n\n"
                                           "    data: |\n        0.5 1.50\n        0.6 1.49\n", encoding="utf-8")
    before = kit.run("project.check", project=laplace.name).issues
    importing(laplace, "own", tmp_path / "Own-2026.yml")
    folder = laplace / "materials" / "own"
    dataset = written(folder)["properties"]["refractive_index"]["own_2026"]
    assert (dataset["convention"], dataset["range"]) == ("real", {"value": [Decimal("0.5"), Decimal("0.6")],
                                                                   "unit": "um"})
    assert (folder / "own_2026.csv").read_text() == "wavelength,n\n0.5,1.50\n0.6,1.49\n"
    assert kit.run("project.check", project=laplace.name).issues == before


def test_an_older_files_comments_become_the_materials_notes(laplace):
    """Fails if `COMMENTS`, the name older files of refractiveindex.info give their notes, is
    refused or dropped instead of becoming the material's `[notes]` under the dataset's name, as
    `NOTES` does (materials.md § 7: "`NOTES`, or `COMMENTS` as older files call it, the
    material's `[notes]`, under the dataset's name")."""
    assert importing(laplace, "gold", "Johnson-comments.yml").ok()
    assert written(laplace / "materials" / "gold")["notes"] == {"johnson_comments": "Room temperature"}


# ------------------------------------------------------------------ never over or into one

def test_an_import_is_never_made_over_or_into_a_material_or_over_anything_there(laplace):
    """Fails if `material import` writes where a material already is — a second import of one name,
    or the library's seeded `vacuum` — into a material's folder, over a group of materials, or
    along a file, instead of refusing `Refused` with code `exists` or `inside-part`, naming the
    name, and writing nothing (materials.md § 7: "never over one there, and never into one";
    projects.md § 7)."""
    root = laplace.parent
    importing(laplace, GOLD[0], GOLD[1])
    (laplace / "materials" / "notes").write_text("mine\n")
    before = kit.tree(root)
    for name, into, code in [(GOLD[0], "project", "exists"), ("metals", "project", "exists"),
                             ("metals/gold/inner", "project", "inside-part"), ("notes/x", "project", "exists"),
                             ("vacuum", "library", "exists")]:
        with kit.refused(Refused, code, name):
            importing(laplace, name, SILICA[1], into)
        assert kit.tree(root) == before, name


@pytest.mark.parametrize("name, into", [(GOLD[0], "project"), ("vacuum", "library")])
def test_an_import_refused_over_a_material_offers_itself_under_a_free_name(laplace, name, into):
    """Fails if an import refused because a material is there — the project's, or the library's
    seeded `vacuum` — offers no way forward: the same import, its source, file and destination
    kept, its name to give again, with a name free there as its example — or if that name is not
    free, so the import under it is refused too (materials.md § 7: "Every refusal says what to do
    instead: over a material there, to import it under another name and copy its lines"; core.md
    § 9)."""
    importing(laplace, GOLD[0], GOLD[1])
    with kit.refused(Refused, "exists", name) as caught:
        importing(laplace, name, SILICA[1], into)
    (again,) = caught.value.next
    (fill,) = again.fills
    assert (again.call.operation, fill.field) == ("material.import", "name")
    assert again.call.request == {"source": SOURCE, "file": str(DATA / SILICA[1]), "into": into,
                                  "project": laplace.name}
    outcome = kit.apply("material.import", **again.call.request, name=fill.example)
    assert outcome.ok() and outcome.dataset == SILICA[3] and fill.example.startswith(name)


def test_a_material_made_between_plan_and_apply_is_never_written_over(laplace):
    """Fails if an import planned while its name was free writes over a material made there before
    it is applied, instead of refusing, naming it (materials.md § 7; api.md § 3)."""
    op, plan, c = kit.planned("material.import", source=SOURCE, file=str(DATA / GOLD[1]), name="gold",
                              into="project", project=laplace.name)
    importing(laplace, "gold", SILICA[1])
    theirs = kit.tree(laplace / "materials" / "gold")
    with kit.refused(Refused, "exists", "gold"):
        op.apply(plan, c)
    assert kit.tree(laplace / "materials" / "gold") == theirs


# ------------------------------------------------------------------ the plan

def test_a_file_changed_between_plan_and_apply_is_refused_as_stale_and_nothing_is_written(laplace, tmp_path):
    """Fails if the import goes ahead when the source's file changed after its plan was shown, so
    the person would get other than what they agreed to (materials.md § 7; api.md § 3)."""
    file = tmp_path / "Johnson.yml"
    file.write_bytes((DATA / GOLD[1]).read_bytes())
    op, plan, c = kit.planned("material.import", source=SOURCE, file=str(file), name="gold", into="project",
                              project=laplace.name)
    assert [s.id for s in plan.steps] == ["write"]
    kit.rewrite(file, "0.5821 0.29 2.863", "0.5821 0.30 2.863")
    with kit.refused(PlanStale, "basis-changed"):
        op.apply(plan, c)
    assert not (laplace / "materials" / "gold").exists()


@pytest.mark.parametrize("into", ["library", "project"])
def test_the_import_holds_the_lock_of_what_it_writes_into(laplace, into):
    """Fails if an import's plan does not hold the lock of what it writes into — the global
    library's, or the project's — or it is applied while another process holds that lock,
    writing anything (materials.md § 4: "A write to the global library — … an import (§ 7) — holds
    the library's lock and is shown as its plan before it is applied"; projects.md § 7; core.md
    § 5)."""
    root = laplace.parent
    subject = Library(root, LIBRARY).subject if into == "library" else Project(root, laplace.name).subject
    op, plan, c = kit.planned("material.import", source=SOURCE, file=str(DATA / GOLD[1]), name="gold", into=into,
                              project=laplace.name)
    assert plan.subjects == (subject,)
    before = kit.tree(root)
    holder = kit.hold(subject, "alone")
    try:
        with kit.refused(Busy, "held", subject):
            op.apply(plan, c)
    finally:
        holder.stdin.close()
        holder.wait()
    assert kit.tree(root) == before
    assert op.apply(plan, c).ok() and (root / ("" if into == "library" else laplace.name) / LIBRARY / "gold").is_dir()


def test_an_import_into_a_project_of_a_name_the_library_has_says_the_projects_is_found_first(slab):
    """Fails if the plan of an import into a project, under the name of a material the global
    library holds — the seeded `vacuum` — does not say, as a warning `found-first` about the new
    material, that the project's will be found first for every assignment naming it; or says so
    for a name the library does not hold (materials.md § 7: "An import whose name a library
    material also has says, in its plan, that the project's will be found first"; § 4)."""
    found = {}
    for name in ("vacuum", "silica"):
        _, plan, _ = kit.planned("material.import", source=SOURCE, file=str(DATA / SILICA[1]), name=name,
                                 into="project", project=slab.name)
        found[name] = [(i.severity, i.code, i.subject) for i in plan.issues]
    assert found == {"vacuum": [("warning", "found-first", "material:vacuum")], "silica": []}


# ------------------------------------------------------------------ what is refused

JOHNSON = (DATA / GOLD[1]).read_text(encoding="utf-8")
RECORD = "DATA:\n  - type: tabulated nk\n"


@pytest.mark.parametrize("name, text, code", [
    ("Johnson.yml", JOHNSON.replace("REFERENCES: |", "REFERENCES: [|"), "unreadable"),
    ("Johnson.yml", JOHNSON.replace("type: tabulated nk", "type: tabulated k"), "unmapped-record"),
    ("Johnson.yml", JOHNSON.split(RECORD)[0], "no-record"),
    ("Johnson.yml", JOHNSON.replace(RECORD, "DATA:\n  - type: tabulated n\n    data: |\n        0.5 1.5\n"
                                            "        0.6 1.4\n  - type: tabulated nk\n"), "several-records"),
    ("Johnson.yml", JOHNSON.replace("NOTES: |\n    Room temperature\n", "").replace("REFERENCES: |", "NOTES: |"),
     "no-source"),
    ("Johnson.yml", "REFERENCES: a test's own\nCONDITIONS:\n    pressure: 1\n" + RECORD + "    data: |\n"
                    "        0.5 1 0\n", "unmapped-condition"),
    ("Johnson.yml", JOHNSON.replace("0.5821 0.29", "0.4821 0.29"), "bad-value"),
    ("Malitson.yml", (DATA / "Malitson-specs.yml").read_text(encoding="utf-8"), "unmapped-key"),
    ("Johnson.yml", JOHNSON.replace("NOTES: |", "PROPERTIES: |"), "unmapped-key"),
    ("Johnson.yml", JOHNSON.replace("    data: |", "    temperature: 293\n    data: |"), "unmapped-key"),
    ("Johnson.yml", JOHNSON.replace("NOTES: |", "COMMENTS: |\n    Room temperature\nNOTES: |"), "unreadable"),
    ("1972Johnson.yml", JOHNSON, "bad-name"),
], ids=["not YAML", "a record type the importer maps onto no dataset", "no record", "n and k as two records",
        "no source",
        "a condition the importer does not map", "a table whose wavelength does not increase", "a SPECS block",
        "a key at its top the importer does not know", "a key in its record the importer does not map",
        "its notes under both their names", "a name that gives no dataset's name"])
def test_a_file_that_cannot_become_one_dataset_with_its_source_is_refused_and_nothing_is_written(laplace, tmp_path,
                                                                                                 name, text, code):
    """Fails if a file that does not read as YAML, a record of a type the declaration does not map,
    a file holding no record, or several — n and k as two tables — one without `REFERENCES`, a
    condition the declaration does not map, a record whose data does not read, a key at the
    file's top or in its record the declaration does not map — `SPECS` among them, which can say
    the wavelengths are in air — the notes under both their names, or a file whose name gives no
    dataset's name, is imported, instead of refused as a `UsageError` with its code, about the
    file, nothing written (materials.md § 7: "A key the declaration does not map, at the file's
    top or in a record, is refused, naming it: nothing a file says is dropped. A record that maps
    onto no form … is refused, naming it; a record without a source is refused. A file holding
    several records is refused, naming them: one import is one dataset"; core.md § 9)."""
    file = tmp_path / name
    file.write_text(text, encoding="utf-8")
    before = kit.tree(laplace.parent)
    with kit.refused(UsageError, code, str(file)):
        importing(laplace, "gold", file)
    assert kit.tree(laplace.parent) == before


def test_a_source_with_no_importer_is_refused_offering_each_declared_one(laplace):
    """Fails if `material import` reads a file for a source femkit declares no importer for, instead
    of refusing, naming it, and offering the import of the same file as each declared source's —
    and no other (materials.md § 7: "Each source is declared as data"; "Every refusal says what to
    do instead")."""
    request = {"file": str(DATA / GOLD[1]), "name": "gold", "into": "project", "project": laplace.name}
    with kit.refused(UsageError, "no-such-source", "elsewhere") as caught:
        kit.apply("material.import", source="elsewhere", **request)
    offered = [(a.call.operation, a.call.request) for a in caught.value.next]
    assert offered == [("material.import", {**request, "source": s}) for s in catalogue.importers(kit.ctx())]


def test_an_import_into_a_root_with_no_library_yet_is_refused_offering_project_new(laplace):
    """Fails if an import into the global library of a projects root that holds none yet writes
    anything, or is refused other than as `Refused` `no-library` about the library's folder,
    offering `project new`, which makes it (materials.md § 7: "An import into the library of a
    root that has none is refused, saying that the next `project new` makes it"; § 4)."""
    root = laplace.parent
    shutil.rmtree(root / LIBRARY)
    before = kit.tree(root)
    with kit.refused(Refused, "no-library", str(Library(root, LIBRARY).place)) as caught:
        importing(laplace, "gold", GOLD[1], "library")
    assert [a.call.operation for a in caught.value.next] == ["project.new"]
    assert kit.tree(root) == before


# ------------------------------------------------------------------ the declaration

def test_a_source_is_read_by_its_declaration_and_a_new_source_is_a_new_file(definitions, laplace, tmp_path):
    """Fails if the importer reads a source's file by anything but its declaration — its keys, its
    record types, its names in the property list — so that a new source's file, declared as
    data with other keys and its name for the refractive index, is not read as its declaration
    says, or a file of the one source is read by the other's instead of refused for the key its
    declaration does not know (materials.md § 7: "Each source is declared as data"; "A key the
    declaration does not map … is refused"; framework.md § 1, rule 5; conventions.md § 2)."""
    shipped = (definitions / "importers" / f"{SOURCE}.toml").read_text(encoding="utf-8")
    table = '[records."tabulated nk"]\nproperty = "nk"\ndata = "data"\ncolumns = ["n", "k"]'
    assert shipped.count(table) == 1
    other = shipped.replace('records = "DATA"', 'records = "POINTS"').replace(
        table, '[records."eps table"]\nproperty = "eps"\ndata = "data"\ncolumns = ["e1", "e2"]')
    (definitions / "importers" / "another_source.toml").write_text(other, encoding="utf-8")
    kit.rewrite(definitions / "properties.toml", 'names = { elmer = "Relative Permittivity" }',
                'names = { elmer = "Relative Permittivity", another_source = "eps" }')
    kit.rewrite(definitions / "properties.toml", 'names = { refractiveindex_info = "nk" }',
                'names = { refractiveindex_info = "nk", another_source = "nk" }')
    file = tmp_path / "Theirs.yml"
    file.write_text(JOHNSON.replace(RECORD, "POINTS:\n  - type: eps table\n"), encoding="utf-8")
    outcome = kit.apply("material.import", source="another_source", file=str(file), name="gold", into="project",
                        project=laplace.name)
    assert (outcome.property, outcome.dataset) == ("relative_permittivity", "theirs")
    assert (laplace / "materials" / "gold" / "theirs.csv").read_text().splitlines()[0] == "wavelength,e1,e2"
    with kit.refused(UsageError, "unmapped-key", str(file)):
        importing(laplace, "again", file)


@pytest.mark.parametrize("old, new, at", [
    ('[records."formula 1"]\nmodel = "sellmeier"', '[records."formula 1"]\nmodel = "cauchy"',
     'records."formula 1".model'),
    ('term = { B = "1", C = "um" }', 'term = { B = "1", C = "K" }', 'records."formula 1".term.C'),
    ('parameters = { A = "1" }\nsum = "terms"\nterm = { B = "1", C = "um" }',
     'parameters = {}\nsum = "terms"\nterm = { B = "1", C = "um" }', 'records."formula 1".parameters'),
    ('property = "nk"\ndata = "data"\ncolumns = ["n", "k"]', 'property = "eps"\ndata = "data"\ncolumns = ["n", "k"]',
     'records."tabulated nk".property'),
    ('columns = ["n", "k"]', 'columns = ["n"]', 'records."tabulated nk".columns'),
    ('[conditions.temperature]\nname = "temperature"', '[conditions.temperature]\nname = "wavelength"',
     "conditions.temperature.name"),
], ids=["a model not on the list", "a pole in no dimension it may have", "a parameter of the model not given",
        "a property no name of the source gives", "columns that do not fit the convention",
        "a condition no dataset states"])
def test_an_importer_that_misstates_itself_does_not_load(definitions, old, new, at):
    """Fails if an importer loads that maps a record onto a model femkit's list lacks, gives a
    parameter in a unit of a dimension the model does not allow or leaves one out, names a
    property the property list's `names` do not give the source, gives complex data one column,
    or maps a condition onto a variable no dataset states the value of — the wavelength, which a
    dataset states by its variable and range — so the import would write a key no material holds
    (materials.md §§ 1, 2, 3, 7; definitions.md § 2.2: "a reference names nothing" fails at
    load)."""
    path = definitions / "importers" / f"{SOURCE}.toml"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(CatalogueError) as caught:
        catalogue.load_importers()
    assert any(where.endswith(f":{at}") for where, _ in caught.value.problems), caught.value.problems


def test_an_import_says_the_projects_is_found_first_when_applied_without_asking(slab):
    """Fails if an import into a project under the name a library material has says the project's
    is found first in its plan alone — so `--yes`, which prints the plan's steps and not its findings,
    never says it — rather than in its outcome too, where the runner carries a plan's findings (api.md
    § 4.4: "its findings come with the outcome — carried there by the runner, once"; materials.md
    § 7)."""
    outcome = kit.apply("material.import", source=SOURCE, file=str(DATA / SILICA[1]), name="vacuum", into="project",
                        project=slab.name)
    assert outcome.ok() and [(i.code, i.subject) for i in outcome.issues] == [("found-first", "material:vacuum")]
