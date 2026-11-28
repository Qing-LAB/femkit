"""The projects framework (projects.md): a project's parts opened each on its own, the files no
part kind declares, the citations between parts, the layout as data, and a project carried to
another root — proven on a layout and toy schemas of the tests' own, since the framework names no
part kind."""

from __future__ import annotations

import copy
import hashlib
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import Field, ValidationInfo, field_validator

from tests import kit
from tests.kit import laplace  # noqa: F401 -- a fixture
from femkit.core.errors import Refused, UsageError
from femkit.core.persist import write_toml
from femkit.core.schema import LENGTH, DefinitionError, Measured, Model, as_quantity
from femkit import registry
from femkit.definitions import catalogue
from femkit.projects import addresses, door, layout, location, schemas
from femkit.projects.addresses import Address
from femkit.projects.door import Opened
from femkit.projects.layout import Layout
from femkit.projects.project import Project


# ------------------------------------------------------------------ the tests' own layout

class ToyProject(Model):
    """The project file: names its components and studies (projects.md § 3), and holds parameters."""

    description: str = ""
    components: list[str] = Field(default_factory=list, json_schema_extra={"ref": "component"})
    studies: list[str] = Field(default_factory=list, json_schema_extra={"ref": "study"})
    parameters: dict[str, str] = Field(default_factory=dict)


class ToyComponent(Model):
    """A component, a folder holding its own file: the groups it promises, and the files beside it
    it reads — a table keyed by each file's path, and one file named as a value."""

    groups: list[str] = Field(default_factory=list)
    inputs: dict[str, str] = Field(default_factory=dict, json_schema_extra={"ref": {"key": "file"}})
    profile: str | None = Field(default=None, json_schema_extra={"ref": "file"})


class ToyMaterial(Model):
    """A material, a folder holding its own file, of the kind the root holds a library of."""

    display: str = ""


class ToyPhysics(Model):
    """A physics, one file: on named groups, with a number and a length."""

    groups: list[str] = Field(default_factory=list)
    order: int = 1
    scale: int | Decimal = 1
    size: Measured | None = as_quantity("its size", "length", default=None)

    @field_validator("size")
    @classmethod
    def _a_length(cls, value: Measured | None, info: ValidationInfo) -> Measured | None:
        """Read by the unit table its loader hands it (core.md § 2: outside facts in `context`)."""
        if value is not None and info.context["units"].measure(value).dimension != LENGTH:
            raise ValueError(f"{value!r} is no length")
        return value


class ToyStudy(Model):
    """A study, one file: pairs one component with one physics."""

    component: str = Field(json_schema_extra={"ref": "component"})
    physics: str = Field(json_schema_extra={"ref": "physics"})
    weights: dict[str, float] = Field(default_factory=dict, json_schema_extra={"ref": {"key": "physics"}})
    also: str | None = Field(default=None, json_schema_extra={"ref": "component|physics"})


SCHEMAS = {"tests.project": ToyProject, "tests.component": ToyComponent, "tests.physics": ToyPhysics,
           "tests.study": ToyStudy, "tests.material": ToyMaterial}

# Every shape a part kind has (projects.md § 4): the one `single` file, `folder` parts — one holding
# a file by a fixed name, one of a kind with a library — two `file` kinds; folders that hold no
# part — a run's, femkit's, and the person's own; and an object type.
LAYOUT = {
    "sections": ["Definitions", "Component", "Physics", "Study"],
    "kinds": {
        "project": {"shape": "single", "schema": "tests.project", "rank": 0, "section": "Definitions"},
        "material": {"folder": "materials", "shape": "folder", "file": "material.toml", "schema": "tests.material",
                     "rank": 1, "section": "Definitions", "library": True},
        "component": {"folder": "components", "shape": "folder", "file": "component.toml", "files": ["geometry.py"],
                      "schema": "tests.component", "rank": 1, "section": "Component"},
        "physics": {"folder": "physics", "shape": "file", "schema": "tests.physics", "rank": 2, "section": "Physics"},
        "study": {"folder": "studies", "shape": "file", "schema": "tests.study", "rank": 3, "section": "Study"},
    },
    "folders": {
        "runs": {"writer": "run", "moves": "yes",
                 "holds": {"stage": "{study}/{kind}/{id}", "launch": "{study}/launch/{name}"}},
        "cases": {"writer": "femkit", "moves": "yes", "holds": {"case": "{study}/{id}/case.json"}},
        "computed": {"writer": "femkit", "moves": "yes", "holds": {"definitions": "{study}/definitions.nc"}},
        ".femkit": {"writer": "femkit", "moves": "local"},
        "custom": {"writer": "person", "moves": "yes"},
    },
    "objects": {
        "parameter": {"part": "project", "table": "parameters", "named": True},
    },
    "editor_files": ["*~", ".*.swp", "#*#", ".#*"],
}


def write_layout(definitions: Path, data: dict) -> None:
    folder = definitions / "project"
    folder.mkdir(exist_ok=True)
    write_toml(folder / "layout.toml", data)


@pytest.fixture
def toy_layout(definitions) -> Layout:
    """The tests' layout in the test's own definitions, its schemas registered as a package
    registers its own, and taken back after."""
    with kit.own_parts(SCHEMAS):
        write_layout(definitions, LAYOUT)
        yield layout.load()


# ------------------------------------------------------------------ a small project

PROJECT = """\
# The demo project: one component, two studies.
description = "a bowtie, swept"
components = ["bowtie"]  # every component a study may pair
studies = ["baseline", "sweeps/gap_sweep"]  # the studies cases are made from
"""
COMPONENT = '# The sharp-tipped bowtie.\ngroups = ["gap", "arms"]\n'
OPTICS = '# Optics on the gap.\ngroups = ["gap"]\norder = 1\n'
HEAT = 'groups = ["arms"]\norder = 2\n'
BASELINE = '# The baseline study.\ncomponent = "bowtie"  # the sharp one\nphysics = "heat"\n'
GAP_SWEEP = '# Sweep the gap.\ncomponent = "bowtie"  # the sharp one\nphysics = "optics"  # optics alone\n'

FILES = {
    "project.toml": PROJECT,
    "components/bowtie/component.toml": COMPONENT,
    "components/bowtie/geometry.py": "import gmsh\n",
    "physics/optics.toml": OPTICS,
    "physics/heat.toml": HEAT,
    "studies/baseline.toml": BASELINE,
    "studies/sweeps/gap_sweep.toml": GAP_SWEEP,
}
PARTS = {"project", "component:bowtie", "physics:optics", "physics:heat", "study:baseline", "study:sweeps/gap_sweep"}


def make_project(root: Path, name: str = "demo") -> Project:
    """The small project, written by hand under ``root``."""
    project = Project(root, name)
    for relative, text in FILES.items():
        path = project.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return project


@pytest.fixture
def demo(tmp_path, toy_layout) -> Project:
    """The small project under a projects root in the test's own folder, the root set."""
    root = tmp_path / "projects"
    root.mkdir()
    project = make_project(root)
    kit.set_root(root)
    return project


def findings(opened: Opened) -> list[tuple[str, str, str]]:
    return sorted((i.code, i.subject, i.severity) for i in opened.issues)


# ------------------------------------------------------------------ (a) each part on its own

@pytest.mark.parametrize("broken, address, key, written", [
    ("physics/heat.toml", "physics:heat", "order", b'groups = ["arms"]\norder = "high"\n'),
    ("physics/heat.toml", "physics:heat", None, b'groups = ["arms"\n'),
    ("project.toml", "project", "components", b'description = "a bowtie, swept"\ncomponents = "bowtie"\n'),
    ("physics/heat.toml", "physics:heat", None, b"# caf\xe9\norder = 2\n"),
    ("physics/optics.toml", "physics:optics", None, None),
], ids=["a physics its schema refuses", "a physics that is no TOML", "the project file", "bytes that are no text",
        "a file that cannot be opened"])
def test_a_part_broken_by_hand_is_a_finding_and_every_other_part_opens(demo, toy_layout, broken, address, key,
                                                                         written):
    """Fails if a part that does not load — its schema refuses it, it is no TOML, its bytes are no
    text, or it cannot be opened — stops the project opening, hides another part, or is not an
    `unloadable` finding on that part's address naming its file and the key at fault (projects.md
    § 6: "each on its own: a part that does not load is a finding on that part — and every other
    part is still read"; a project file that does not load leaves the components and studies
    listed from their folders; core.md § 10: a finding names its file and key)."""
    path = demo.folder / broken
    if written is None:
        path.chmod(0)
    else:
        path.write_bytes(written)
    try:
        opened = door.open_project(demo, kit.ctx(), toy_layout)
    finally:
        path.chmod(0o644)
    assert findings(opened) == [("unloadable", address, "error")]
    assert [(i.file, i.key) for i in opened.issues] == [(broken, key)]
    assert set(opened.parts) == PARTS
    part = opened.part(toy_layout.address(address))
    assert part.file == broken and part.data is None
    assert all(p.data is not None for a, p in opened.parts.items() if a != address)
    assert written is None or path.read_bytes() == written          # read, never changed


# ------------------------------------------------------------------ (e) a project moves whole

def test_a_project_zipped_and_unpacked_under_another_root_opens_as_before(tmp_path, demo, toy_layout):
    """Fails if a project carried to another projects root as a zip opens otherwise than it did:
    another part, file, value, finding, listing, text or hash — so a path held absolute, or a part
    read from the old place (projects.md § 1: "Every path inside it is relative, so a project can
    be zipped and unpacked under another projects root and still work")."""
    (demo.folder / "physics" / "heat.toml").write_text('order = "high"\n')    # a finding goes along too
    (demo.folder / ".femkit").mkdir()
    (demo.folder / ".femkit" / "view.json").write_text("{}")               # carried along, harmlessly
    before = door.open_project(demo, kit.ctx(), toy_layout)
    listed = door.listing(demo, toy_layout)
    texts = {a: door.text(before, p.address) for a, p in before.parts.items()}

    archive = shutil.make_archive(str(tmp_path / "carried"), "zip", root_dir=demo.root, base_dir=demo.name)
    shutil.rmtree(demo.folder)                                             # nothing left to read in the old place
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    shutil.unpack_archive(archive, elsewhere)
    kit.set_root(elsewhere)

    moved = location.locate(kit.ctx(), demo.name, cwd=tmp_path)
    assert moved == Project(elsewhere, demo.name)
    after = door.open_project(moved, kit.ctx(), toy_layout)
    assert {a: (p.file, p.data) for a, p in after.parts.items()} == {a: (p.file, p.data) for a, p in before.parts.items()}
    assert findings(after) == findings(before) == [("unloadable", "physics:heat", "error")]
    assert after.texts == before.texts
    assert door.listing(moved, toy_layout) == listed
    assert {a: door.text(after, p.address) for a, p in after.parts.items()} == texts


# ------------------------------------------------------------------ (f) files no kind declares

STRAYS = ["components/notes.toml", "physics/notes.txt", "studies/sweeps/draft.txt"]
#: The files an editor keeps beside what it edits — a backup, a swap file, a lock — in a part's
#: folder, a kind's and the project's top.
EDITORS = ["physics/heat.toml~", "physics/.optics.toml.swp", "components/bowtie/#geometry.py#", ".#project.toml",
           "studies/sweeps/.#gap_sweep.toml"]


def test_a_file_no_part_kind_declares_is_a_stray_finding_and_never_read(demo, toy_layout):
    """Fails if a file in the tree that no part kind declares is read, taken for a part, or not a
    `stray` finding naming its path and the folder the person's own files go in — or if a file in
    a folder the layout declares as holding no part, what a run or femkit writes or the person's
    own `custom/`, is, or a file an editor keeps beside what it edits (projects.md § 2: "A file in
    a folder of the tree that no part kind declares is a finding, never read"; § 3: "a file in a
    group folder that is no part is a finding, never read"; § 4: a folder that holds no part, the
    editor's own files)."""
    for relative in STRAYS:
        path = demo.folder / relative
        path.write_text("component = 'bowtie\n")      # read as a part, it would not load
        path.chmod(0)                                  # read at all, it raises
    for relative in ("runs/geometry/run.log", ".femkit/view.json", "custom/solver.sif"):
        path = demo.folder / relative
        path.parent.mkdir(parents=True)
        path.write_text("{}")
    (demo.folder / "components/bowtie/geometry.py").write_text("x = 1\n")   # a folder part's own other file

    for relative in EDITORS:
        (demo.folder / relative).write_text("")
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    assert findings(opened) == [("stray", relative, "warning") for relative in sorted(STRAYS)]
    assert all(i.file == i.subject and "custom/" in i.message for i in opened.issues)
    assert not set(EDITORS) & set(opened.files)
    assert set(opened.parts) == PARTS and all(p.data is not None for p in opened.parts.values())
    assert [f for f in opened.texts if f in STRAYS or f.startswith(("runs/", ".femkit/", "custom/"))] == []


# ------------------------------------------------------------------ (h) the layout's own rules

def spoiled(where: tuple[str, ...], value) -> dict:
    """The tests' layout with one key set — or, given None, removed."""
    data = copy.deepcopy(LAYOUT)
    *path, last = where
    table = data
    for key in path:
        table = table[key]
    if value is None:
        del table[last]
    else:
        table[last] = value
    return data


@pytest.mark.parametrize("spoil", [
    (("kinds", "physics", "schema"), "tests.unregistered"),
    (("kinds", "study", "folder"), "physics"),
    (("kinds", "study", "folder"), "runs"),
    (("kinds", "project"), None),
    (("kinds", "second"), {"shape": "single", "schema": "tests.project", "rank": 0, "section": "Definitions"}),
    (("kinds", "project", "file"), "project.toml"),
    (("kinds", "study", "folder"), "work/studies"),
    (("folders", "runs/old"), {"writer": "run", "moves": "yes"}),
    (("folders", "runs", "writer"), "the run"),
    (("kinds", "physics", "files"), ["notes.txt"]),
    (("kinds", "component", "files"), ["../geometry.py"]),
    (("kinds", "project", "library"), True),
    (("objects", "parameter", "part"), "nothing"),
    (("objects", "study"), {"part": "study", "table": "steps", "named": True}),
    (("objects", "parameter", "table"), "parameters..x"),
    (("kinds", "stage"), {"folder": "stages", "shape": "file", "schema": "tests.study", "rank": 3,
                       "section": "Study"}),
    (("kinds", "launch"), {"folder": "launches", "shape": "file", "schema": "tests.study", "rank": 3,
                       "section": "Study"}),
    (("kinds", "job"), {"folder": "jobs", "shape": "file", "schema": "tests.study", "rank": 3,
                       "section": "Study"}),
    (("folders", "runs", "holds", "stage"), "{study}/{id}"),
    (("folders", "runs", "holds", "stage"), "{study}/{kind}/{id}/{id}"),
    (("folders", "runs", "holds", "stage"), "{study}/../{kind}/{id}"),
    (("folders", "runs", "holds", "stage"), "{study}/{kind}-{id}"),
    (("folders", "runs", "holds", "stage"), "{study}/{kind}/{id?}"),
    (("folders", "runs", "holds", "solve"), "{study}/{id}"),
    (("folders", "cases", "holds", "stage"), "{study}/{kind}/{id}"),
    (("folders", "runs", "holds"), {"stage": "{study}/{kind}/{id}"}),
    (("kinds", "physics", "section"), "Physical"),
    (("sections",), ["Definitions", "Component", "Physics", "Study", "Physics"]),
    (("objects", "parameter", "rank"), 0),
], ids=["a schema no package registered", "two kinds on one folder", "a kind on a folder femkit writes",
        "no project file kind", "two project file kinds", "the project file named again",
        "a kind's folder deeper than the top", "a folder holding no part deeper than the top",
        "a writer that is none of the three", "a fixed file of a part that is one file",
        "a fixed file out of its part's folder", "a library of the project file", "an object in no part kind",
        "an object named like a part kind", "an object's table that is no table", "a part kind named stage",
        "a part kind named launch", "a part kind named job", "a stage's folder without its kind",
        "a stage's folder naming its ID twice", "a stage's folder out of its folder", "a step half a placeholder",
        "an optional step", "a folder the door forms none of", "a stage's folder declared twice",
        "no launch folder declared", "a kind in no section", "a section declared twice",
        "an object type's own rank"])
def test_a_layout_breaking_its_rules_is_refused(definitions, toy_layout, spoil):
    """Fails if the layout loads while it names a schema no package registered — the keys
    registered reach it in its validation context — declares two kinds of thing on one folder, a
    folder that is not one step at the project's top, names the project file, which is fixed, or
    has not exactly one `single` kind, the project file; a writer but the person, femkit or a run;
    a fixed file of a part that is no folder, or out of its folder; a library of the project file;
    or an object type in no part kind, named like one, or in no table; or a part kind named
    `stage`, `launch` or `job`, the forms that name what femkit makes; or what the door forms in a
    folder holding no part — a stage's folder, a launch folder, a case's file — declared with a
    path that does not name each step it is formed from once, each a step of its own, inside its
    folder, declared none or twice, or something the door forms none of; or a kind in a section the
    layout does not declare, a section declared twice, or an object type with a rank of its own
    (projects.md § 4: "Whether a folder is a part or a group is read from that declaration"; "Every
    folder is one step"; "The project file is fixed"; the writer; `files`; `library`; each kind's
    section and the sections' order; the object types, each in its part's place; § 5: "the layout
    refuses a part kind named `stage`, `launch` or `job`"; § 6: "Schemas are registered, never
    imported"; the stage's and launch folders "as the layout declares `runs/`"). The tests' layout
    loads (the fixture), so each refusal is the one change's."""
    write_layout(definitions, spoiled(*spoil))
    with kit.refused(DefinitionError, "definition-invalid", str(layout.file())):
        layout.load()


def test_the_two_orders_are_by_rank_then_the_kinds_place_then_name_and_by_section_first():
    """Fails if the chain's order is not by rank, then the kind's place in the layout, then name —
    two kinds of one rank and one section ordered by their place, whatever their parts' names; a
    lower rank first, wherever its kind is placed — or the reading order is not by section first,
    then the same; or an object does not take its part kind's place (projects.md § 4: "Two
    orders, each declared here alone")."""
    shipped = layout.read().model_dump(mode="json", by_alias=True)
    toy = {**shipped, "sections": ["Near", "Far"], "objects": {"thing": {"part": "second", "table": "things",
                                                                         "named": True}},
           "kinds": {"project": {**shipped["kinds"]["project"], "rank": 0, "section": "Near"},
                     "first": {"folder": "first", "shape": "file", "schema": "s", "rank": 2, "section": "Near"},
                     "second": {"folder": "second", "shape": "file", "schema": "s", "rank": 2, "section": "Near"},
                     "low": {"folder": "low", "shape": "file", "schema": "s", "rank": 1, "section": "Near"},
                     "other": {"folder": "other", "shape": "file", "schema": "s", "rank": 0, "section": "Far"}}}
    toy.pop("listed", None)
    toy_layout = Layout.model_validate(toy)
    parts = [("second", "a"), ("thing", "a"), ("other", "b"), ("first", "z"), ("low", "y"), ("project", None)]
    assert sorted(parts, key=lambda p: toy_layout.chain(*p)) == [
        ("project", None), ("other", "b"), ("low", "y"), ("first", "z"), ("second", "a"), ("thing", "a")]
    assert sorted(parts, key=lambda p: toy_layout.reading(*p)) == [
        ("project", None), ("low", "y"), ("first", "z"), ("second", "a"), ("thing", "a"), ("other", "b")]


# ------------------------------------------------------------------ the shipped layout and the templates

def test_the_shipped_layout_reads_before_any_part_schema_and_binds_once_each_is_registered():
    """Fails if the shipped layout, with no part schema registered, breaks its own rules or binds
    — each schema refused at its kind's key — or, each one registered, does not open every
    template whole: every part loaded, each file its kind fixes — a component's script, an
    observables part's `observe.py` — and its `definitions.py` read with their digests, and nothing else found (projects.md § 4: the shipped layout; § 2: `definitions.py`;
    § 6: "a key no package registered is refused"; § 7: the templates)."""
    registry.part_schemas()
    held = schemas.registered()
    for key in held:
        schemas.unregister(key)
    try:
        shipped = layout.read()
        with kit.refused(DefinitionError, "definition-invalid") as caught:
            layout.load()
        assert {where for where, _ in caught.value.problems} == {f"kinds.{k}.schema" for k in shipped.kinds}
    finally:
        for key, model in held.items():
            schemas.register(key, model)
    assert layout.load() == shipped
    for name, folder in catalogue.templates(kit.ctx()).items():
        opened = door.open_project(Project(folder.parent, name), kit.ctx())
        assert opened.issues == [] and all(p.data is not None for p in opened.parts.values()), name
        scripts = {h.file: h.sha256 for h in opened.held.values()}
        fixed = {p.folder: f for p in opened.parts.values() for f in opened.layout.kinds[p.address.kind].files}
        assert scripts == {f"{where}/{f}": hashlib.sha256((folder / where / f).read_bytes()).hexdigest()
                           for where, f in fixed.items()} | {
            "definitions.py": hashlib.sha256((folder / "definitions.py").read_bytes()).hexdigest()}, name


@pytest.mark.parametrize("verb, request_", [("project.list", {}), ("project.check", {"project": "laplace_square"}),
                                             ("case.list", {"project": "laplace_square"})])
def test_one_invocation_reads_the_layout_once_each_way(laplace, monkeypatch, verb, request_):
    """Fails if one invocation reads the layout's file more than once by its own rules, or more
    than once bound to the registered schemas — finding the projects, opening one and listing it
    each read it through the invocation's context (api.md § 2.4: "a file is read once per
    invocation"; projects.md § 4: "read two ways")."""
    reads: list[bool] = []
    real = layout.load_toml

    def counted(path, model, context=None, **more):
        if path == layout.file():
            reads.append(bool(context))
        return real(path, model, context, **more)

    monkeypatch.setattr(layout, "load_toml", counted)
    kit.run(verb, **request_)
    assert reads.count(False) <= 1 and reads.count(True) <= 1, reads


# ------------------------------------------------------------------ what the review of C found

@pytest.mark.parametrize("written, asked", [
    (b"# caf\xe9\norder = 2\n", "physics:heat"),
    (b"# caf\xe9\norder = 2\n", "physics:heat:order"),
    (b'groups = ["arms"\n', "physics:heat:groups"),
], ids=["a part that could not be read", "a value in it", "a value in a part that is not TOML"])
def test_the_text_of_a_part_that_does_not_load_is_refused_naming_the_address(demo, toy_layout, written, asked):
    """Fails if asking for the text of a part that could not be read, or a value in a part that is
    not TOML, fails as a defect instead of a refusal `unloadable` naming the address asked for
    (projects.md § 6: "A part's text"; core.md § 9)."""
    (demo.folder / "physics/heat.toml").write_bytes(written)
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    with kit.refused(UsageError, "unloadable", asked):
        door.text(opened, toy_layout.address(asked))


def test_the_text_of_a_folder_parts_file_is_that_files_as_the_project_read_it(demo, toy_layout):
    """Fails if the text of an address naming a folder part's file — `component:bowtie@geometry.py`
    — is the part's own file's, or read again from disk, rather than that file's as the project
    read it, with one in its place in memory (projects.md § 5: "a file of a folder part, by its path
    from the part's folder"; § 6: "A part's text is the file as it holds it"; web.md § 7.6: a node's
    files, "read once by the door")."""
    address = Address("component", "bowtie", file="geometry.py")
    assert door.text(door.open_project(demo, kit.ctx(), toy_layout), address) == "import gmsh\n"
    assert door.text(door.open_project(demo, kit.ctx(), toy_layout, texts={address: "import os\n"}),
                     address) == "import os\n"


def test_a_parts_numbers_are_exact_and_its_quantities_read_by_the_unit_table(demo, toy_layout):
    """Fails if a part's number is read through a binary float — its digits past a float's lost —
    or its validators are not handed the unit table, so a quantity of the wrong dimension loads or
    the project does not open (projects.md § 6: "A part loads as every declared file does";
    core.md §§ 2, 11)."""
    digits = "0.12345678901234567890123"
    (demo.folder / "physics/heat.toml").write_text(HEAT + f'scale = {digits}\nsize = {{value = 0.5, unit = "um"}}\n')
    (demo.folder / "physics/optics.toml").write_text(OPTICS + 'size = {value = 5, unit = "s"}\n')
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    heat = opened.parts["physics:heat"].data
    assert heat.scale == Decimal(digits) and (heat.size.value, heat.size.unit) == (Decimal("0.5"), "um")
    assert findings(opened) == [("unloadable", "physics:optics", "error")]


def test_a_folder_parts_other_files_are_read_once_and_any_other_is_a_stray(demo, toy_layout):
    """Fails if a folder part's files — the one its kind fixes, those its own file declares, as a
    table's key or a value — are not each read once with their bytes and SHA-256; if a file in
    its folder that neither fixes nor declares — a mesh it holds, a deeper file of the part's own
    name — is taken for a part or not a `stray` finding; or if a declared file that is missing is
    not a finding on the key that declares it — one that cannot be read too — a fixed one missing
    a finding naming that file, and a declared path out of the folder a finding on its key, never
    read (projects.md § 6: "A
    folder part's other files"; § 3: a folder is a part or a group, never both)."""
    folder = demo.folder / "components/bowtie"
    (folder / "data").mkdir()
    (folder / "data/tip.csv").write_bytes(b"x,y\n0,1\n")
    (folder / "profile.txt").write_text("sharp\n")
    (folder / "component.toml").write_text(COMPONENT + 'profile = "profile.txt"\n'
                                           '[inputs]\n"data/tip.csv" = "its digest"\n')
    (folder / "mesh.bin").write_bytes(b"\x80\x81\x00binary")
    (folder / "sub").mkdir()
    (folder / "sub/component.toml").write_text("groups = []\n")
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    held = opened.held_by(Address("component", "bowtie"))
    expected = [("geometry.py", ()), ("data/tip.csv", ("inputs", "data/tip.csv")), ("profile.txt", ("profile",))]
    assert {n: (h.file, h.key, h.data, h.sha256) for n, h in held.items()} == {
        n: (f"components/bowtie/{n}", key, (folder / n).read_bytes(), hashlib.sha256((folder / n).read_bytes()).hexdigest())
        for n, key in expected}
    assert "component:bowtie/sub" not in opened.parts
    assert findings(opened) == [("stray", "components/bowtie/mesh.bin", "warning"),
                                ("stray", "components/bowtie/sub/component.toml", "warning")]

    (folder / "geometry.py").unlink()
    (folder / "data/tip.csv").unlink()
    (folder / "locked.csv").write_text("x\n")
    (folder / "locked.csv").chmod(0)
    (folder / "component.toml").write_text(COMPONENT + 'profile = "../../project.toml"\n'
                                           '[inputs]\n"data/tip.csv" = "its digest"\n"locked.csv" = "x"\n')
    try:
        opened = door.open_project(demo, kit.ctx(), toy_layout)
    finally:
        (folder / "locked.csv").chmod(0o644)
    assert {(i.code, i.subject, i.file, i.key) for i in opened.issues if i.code != "stray"} == {
        ("missing-file", "component:bowtie", "components/bowtie/geometry.py", None),
        ("missing-file", 'component:bowtie:inputs."data/tip.csv"', "components/bowtie/component.toml",
         'inputs."data/tip.csv"'),
        ("unreadable", 'component:bowtie:inputs."locked.csv"', "components/bowtie/component.toml",
         'inputs."locked.csv"'),
        ("outside-part", "component:bowtie:profile", "components/bowtie/component.toml", "profile")}
    assert opened.held_by(Address("component", "bowtie")) == {}


def test_a_folder_part_that_does_not_load_has_no_strays_and_keeps_its_fixed_file(demo, toy_layout):
    """Fails if, for a folder part whose own file does not load, a file of its folder is called a
    stray — what it declares cannot be known — or the file its kind fixes is not read
    (projects.md § 6)."""
    folder = demo.folder / "components/bowtie"
    (folder / "component.toml").write_text('groups = "gap"\n')
    (folder / "tip.csv").write_text("x,y\n")
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    assert findings(opened) == [("unloadable", "component:bowtie", "error")]
    assert list(opened.held_by(Address("component", "bowtie"))) == ["geometry.py"]


def test_a_citation_naming_either_of_two_kinds_finds_the_one_that_has_the_part(demo, toy_layout):
    """Fails if a citation that may name a component or a physics is taken as naming no part when
    the physics exists (projects.md § 3)."""
    study = demo.folder / "studies/baseline.toml"
    study.write_text(study.read_text() + 'also = "optics"\n')
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    assert Address("physics", "optics") in [cited for _, cited in door.references(opened)]


def test_a_value_is_read_at_its_address_as_its_file_writes_it(demo, toy_layout):
    """Fails if a value's text is not its TOML, or an address naming no value is not refused
    (projects.md § 6: "a value's text is its TOML")."""
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    assert door.text(opened, toy_layout.address("physics:heat:order")) == "2"
    with kit.refused(UsageError, "no-such-value", "physics:heat:nothing"):
        door.text(opened, toy_layout.address("physics:heat:nothing"))


@pytest.mark.parametrize("written, address", [
    ("study:sweeps/gap_sweep", Address("study", "sweeps/gap_sweep")),
    ('study:sweeps/gap_sweep:axes."project:definitions.gap"',
     Address("study", "sweeps/gap_sweep", ("axes", "project:definitions.gap"))),
    ("project:description", Address("project", None, ("description",))),
    ("material:GLOBAL/metals/gold", Address("material", "GLOBAL/metals/gold")),
    ("component:bowtie@geometry.py", Address("component", "bowtie", file="geometry.py")),
    ("material:GLOBAL/metals/gold@data/n-k.csv", Address("material", "GLOBAL/metals/gold", file="data/n-k.csv")),
])
def test_an_address_reads_and_writes_back_the_same(toy_layout, written, address):
    """Fails if an address — a grouped name, a quoted key holding `:` and `.`, the project file's
    unnamed part, a `GLOBAL/` name of a kind with a library, a folder part's file by its path from
    the part's folder — is read otherwise, or written back otherwise (projects.md § 5)."""
    assert toy_layout.address(written) == address and str(address) == written


def test_a_quoted_key_of_an_address_is_read_as_toml_reads_it(toy_layout):
    """Fails if a quoted key of an address is read otherwise than TOML reads that key in the file —
    an escape TOML has and JSON lacks, `\\U` and eight digits, read as its character — or a quoted
    key TOML refuses is anything but the address's refusal (projects.md § 5: "quoted as TOML quotes
    them")."""
    held = toy_layout.address('study:sweeps/gap_sweep:axes."x\\U0001F600y"')
    assert held.path == ("axes", "x\U0001F600y")
    with kit.refused(UsageError, "bad-address"):
        toy_layout.address('study:sweeps/gap_sweep:axes."x\\qy"')


STAGE_ID = "91c0" + "0" * 60   # a stage's ID: a SHA-256, in hexadecimal (workflow.md § 4)


@pytest.mark.parametrize("written, made", [
    (f"stage:sweeps/gap/mesh/{STAGE_ID}", addresses.Stage("sweeps/gap", "mesh", STAGE_ID)),
    (f"stage:check/geometry/{STAGE_ID}", addresses.Stage("check", "geometry", STAGE_ID)),
    ("launch:check/mesh-check-001", addresses.Launch("check", "mesh-check-001")),
    ("launch:sweeps/gap/geometries-ngsolve-cuda-002", addresses.Launch("sweeps/gap", "geometries-ngsolve-cuda-002")),
    ("job:workstation-41822", addresses.Job("workstation-41822")),
])
def test_what_femkit_makes_is_named_by_a_form_no_part_kind_takes(toy_layout, written, made):
    """Fails if a stage — its last two steps its kind and ID, the rest its study's grouped name —
    a launch folder or a job is read otherwise, written back otherwise, or read where an address of
    a part or a value is asked for — an axis keyed by a stage (projects.md § 5)."""
    assert toy_layout.address(written, made=True) == made and str(made) == written
    with kit.refused(UsageError, "bad-address", written):
        toy_layout.address(written)


@pytest.mark.parametrize("written", [
    "nokind:x", "study", "study:Bad", "study:a:x.", 'study:a:"open', "study:a:x..y", "component:GLOBAL/bowtie",
    "physics:heat@notes.txt", "project@notes.txt", "component:bowtie@../geometry.py", "component:bowtie@.hidden",
    "component:bowtie@", "component:bowtie@geometry.py:x", "component:bowtie:groups@geometry.py",
    "component:bowtie@component.toml",
    "stage:check/mesh", f"stage:check/mesh/{STAGE_ID[:12]}", f"stage:Check/mesh/{STAGE_ID}",
    f"stage:check/Mesh/{STAGE_ID}", f"stage:check/mesh/{STAGE_ID}:x",
    "launch:check", "launch:check/.hidden", "launch:Check/mesh-elmer-001", "launch:check/a:b",
    "job:", "job:a/b", "job:.hidden",
])
def test_an_address_breaking_the_grammar_is_refused(toy_layout, written):
    """Fails if an address naming no kind, a named kind without its name, a name breaking the rule,
    a dotted path that does not close, or `GLOBAL/` opening the name of a kind the layout declares
    with no library is read at all; or a file of a part that is no folder, a file's path that
    leaves the part's folder or is hidden or empty, a file holding a value, or the part's own file
    named as a file of it, which its address alone names; or a stage without its kind and ID, its
    ID no SHA-256, its study's name or its kind breaking the name rule; a launch folder without
    its study or with a name that is no folder's; or a job without its ID or with one that is no
    one step (projects.md § 5)."""
    with kit.refused(UsageError, "bad-address", written):
        toy_layout.address(written, made=True)


# ------------------------------------------------------------------ what the door forms, and a text in place

def test_the_door_forms_each_stages_and_launch_folder_and_each_cases_file_as_the_layout_declares(demo, toy_layout,
                                                                                                definitions):
    """Fails if a stage's calculation folder, a launch folder or a case's file is formed otherwise
    than the layout declares the folder that holds it — formed by a literal of the door's own, so a
    layout declaring another place is not followed — or a written case is not found where it is
    formed, or a study, a stage kind, an ID or a launch folder's name that breaks its grammar forms
    a path at all (projects.md §§ 2, 4, 6: "formed by the door alone … as the layout declares
    `runs/`")."""
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    assert door.stage_folder(opened, "sweeps/gap_sweep", "mesh", STAGE_ID) == \
        demo.folder / "runs" / "sweeps" / "gap_sweep" / "mesh" / STAGE_ID
    assert door.launch_folder(opened, "baseline", "mesh-elmer-001") == \
        demo.folder / "runs" / "baseline" / "launch" / "mesh-elmer-001"
    assert door.case_file(opened, "sweeps/gap_sweep", STAGE_ID) == f"cases/sweeps/gap_sweep/{STAGE_ID}/case.json"
    for study, kind, id_ in (("Bad", "mesh", STAGE_ID), ("baseline", "Mesh", STAGE_ID), ("baseline", "mesh", "x")):
        with pytest.raises(UsageError):
            door.stage_folder(opened, study, kind, id_)
    with pytest.raises(UsageError):
        door.launch_folder(opened, "baseline", "../elsewhere")

    elsewhere = copy.deepcopy(LAYOUT)
    elsewhere["folders"]["runs"]["holds"] = {"stage": "{study}/stages/{kind}/{id}", "launch": "{study}/jobs/{name}"}
    elsewhere["folders"]["cases"]["holds"] = {"case": "{study}/written/{id}/the-case.json"}
    write_layout(definitions, elsewhere)
    opened = door.open_project(demo, kit.ctx(), layout.load())
    assert door.stage_folder(opened, "baseline", "geometry", STAGE_ID) == \
        demo.folder / "runs" / "baseline" / "stages" / "geometry" / STAGE_ID
    assert door.launch_folder(opened, "baseline", "mesh-elmer-001") == \
        demo.folder / "runs" / "baseline" / "jobs" / "mesh-elmer-001"
    written = door.case_file(opened, "sweeps/gap_sweep", STAGE_ID)
    assert written == f"cases/sweeps/gap_sweep/written/{STAGE_ID}/the-case.json"
    door.write_output(opened, written, {"schema": 1})
    door.write_output(opened, f"cases/sweeps/gap_sweep/{STAGE_ID}/case.json", {})
    assert door.cases(door.open_project(demo, kit.ctx(), layout.load())) == {"sweeps/gap_sweep": {STAGE_ID: written}}


NEW_HEAT = 'groups = ["arms"]\norder = 3\n'


@pytest.mark.parametrize("address, relative, text", [
    (Address("physics", "heat"), "physics/heat.toml", NEW_HEAT),
    (Address("project", None), "project.toml", PROJECT.replace("a bowtie, swept", "a bowtie, rounded")),
    (Address("component", "bowtie", file="geometry.py"), "components/bowtie/geometry.py", "import gmsh  # new\n"),
])
def test_a_project_opens_with_one_files_text_in_place_of_the_files_in_memory(demo, toy_layout, address, relative,
                                                                             text):
    """Fails if a project opened with one file's text in place — a part's own file, the project
    file, a folder part's file — reads the file on disk instead, keeps its old text or digest, or
    writes anything (projects.md §§ 6, 7: "the door opens the project with that one file's text in
    place of the file's, in memory")."""
    before = kit.tree(demo.folder)
    opened = door.open_project(demo, kit.ctx(), toy_layout, texts={address: text})
    assert kit.tree(demo.folder) == before
    if address.file is None:
        assert opened.texts[relative] == text and door.text(opened, address) == text
    else:
        held = opened.held[relative]
        assert held.data == text.encode() and held.sha256 == hashlib.sha256(text.encode()).hexdigest()
    if address == Address("physics", "heat"):
        assert opened.part(address).data.order == 3
    assert opened.issues == door.open_project(demo, kit.ctx(), toy_layout).issues


def test_a_text_in_place_is_read_as_its_file_would_be_and_one_naming_no_file_is_refused(demo, toy_layout):
    """Fails if a text in place that does not load is not that part's finding, as its file's would
    be, or a text for a file the project does not hold — a part it lacks, a stray, a value — is
    dropped silently instead of refused (projects.md § 6)."""
    opened = door.open_project(demo, kit.ctx(), toy_layout, texts={Address("physics", "heat"): 'order = "high"\n'})
    assert findings(opened) == [("unloadable", "physics:heat", "error")]
    (demo.folder / "physics" / "notes.txt").write_text("")
    for address in (Address("physics", "cold"), Address("component", "bowtie", file="notes.txt"),
                    Address("physics", "heat", ("order",))):
        with kit.refused(UsageError, "no-such-file", str(address)):
            door.open_project(demo, kit.ctx(), toy_layout, texts={address: NEW_HEAT})


def test_a_save_reads_the_layout_once_through_its_invocation(demo, toy_layout, monkeypatch):
    """Fails if a save reads the layout's file again in an invocation that has read it, rather than
    through the invocation's context (api.md § 2.4: "a file is read once per invocation"; projects.md
    § 4: "read two ways")."""
    c = kit.ctx()
    layout.read_once(c)
    reads: list[Path] = []
    real = layout.load_toml

    def counted(path, model, context=None, **more):
        if path == layout.file():
            reads.append(path)
        return real(path, model, context, **more)

    monkeypatch.setattr(layout, "load_toml", counted)
    path = demo.folder / "physics/heat.toml"
    door.save_text(c, demo, Address("physics", "heat"), HEAT, hashlib.sha256(path.read_bytes()).hexdigest())
    assert reads == [] and path.read_text() == HEAT


@pytest.mark.parametrize("address, relative", [
    (Address("physics", "heat"), "physics/heat.toml"),
    (Address("component", "bowtie", file="geometry.py"), "components/bowtie/geometry.py"),
])
def test_a_save_writes_the_text_exactly_and_refuses_a_file_changed_since_it_was_opened(demo, toy_layout, address,
                                                                                       relative):
    """Fails if a save writes other bytes than the text given — its line ends, its last line
    without an end, its comments — or writes over a file whose SHA-256 is not the one given, the
    file changed since the page opened it, or one gone, instead of refusing, `Refused` ·
    `file-changed`, naming it, and writing nothing (projects.md § 7)."""
    path = demo.folder / relative
    opened_at = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_text(path.read_text() + "# changed meanwhile\n")
    meanwhile = path.read_bytes()
    with kit.refused(Refused, "file-changed", str(address)):
        door.save_text(kit.ctx(), demo, address, "anything\n", opened_at)
    assert path.read_bytes() == meanwhile
    text = "# my own\r\norder = 2  # kept\r\n\r\nlast = 1"
    door.save_text(kit.ctx(), demo, address, text, hashlib.sha256(meanwhile).hexdigest())
    assert path.read_bytes() == text.encode("utf-8")
    path.unlink()
    with kit.refused(Refused, "file-changed", str(address)):
        door.save_text(kit.ctx(), demo, address, text, hashlib.sha256(text.encode()).hexdigest())
    assert not path.exists()
    with kit.refused(UsageError, "bad-address", "physics:heat:order"):
        door.save_text(kit.ctx(), demo, Address("physics", "heat", ("order",)), text, opened_at)
