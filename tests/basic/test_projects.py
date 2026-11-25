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
from femkit.core.errors import UsageError
from femkit.core.persist import write_toml
from femkit.core.schema import LENGTH, DefinitionError, Model, as_quantity
from femkit import registry
from femkit.definitions import catalogue
from femkit.projects import door, layout, location, schemas
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
    size: str | None = as_quantity("its size", "length", default=None)

    @field_validator("size")
    @classmethod
    def _a_length(cls, value: str | None, info: ValidationInfo) -> str | None:
        """Read by the unit table its loader hands it (core.md § 2: outside facts in `context`)."""
        if value is not None and info.context["units"].parse(value).dimension != LENGTH:
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
    "kinds": {
        "project": {"shape": "single", "schema": "tests.project", "rank": 0},
        "material": {"folder": "materials", "shape": "folder", "file": "material.toml", "schema": "tests.material",
                     "rank": 1, "library": True},
        "component": {"folder": "components", "shape": "folder", "file": "component.toml", "files": ["geometry.py"],
                      "schema": "tests.component", "rank": 1},
        "physics": {"folder": "physics", "shape": "file", "schema": "tests.physics", "rank": 2},
        "study": {"folder": "studies", "shape": "file", "schema": "tests.study", "rank": 3},
    },
    "folders": {
        "runs": {"writer": "run", "moves": "yes"},
        ".femkit": {"writer": "femkit", "moves": "local"},
        "custom": {"writer": "person", "moves": "yes"},
    },
    "objects": {
        "parameter": {"part": "project", "table": "parameters", "named": True, "rank": 0},
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
    (("kinds", "second"), {"shape": "single", "schema": "tests.project", "rank": 0}),
    (("kinds", "project", "file"), "project.toml"),
    (("kinds", "study", "folder"), "work/studies"),
    (("folders", "runs/old"), {"writer": "run", "moves": "yes"}),
    (("folders", "runs", "writer"), "the run"),
    (("kinds", "physics", "files"), ["notes.txt"]),
    (("kinds", "component", "files"), ["../geometry.py"]),
    (("kinds", "project", "library"), True),
    (("objects", "parameter", "part"), "nothing"),
    (("objects", "study"), {"part": "study", "table": "steps", "named": True, "rank": 3}),
    (("objects", "parameter", "table"), "parameters..x"),
], ids=["a schema no package registered", "two kinds on one folder", "a kind on a folder femkit writes",
        "no project file kind", "two project file kinds", "the project file named again",
        "a kind's folder deeper than the top", "a folder holding no part deeper than the top",
        "a writer that is none of the three", "a fixed file of a part that is one file",
        "a fixed file out of its part's folder", "a library of the project file", "an object in no part kind",
        "an object named like a part kind", "an object's table that is no table"])
def test_a_layout_breaking_its_rules_is_refused(definitions, toy_layout, spoil):
    """Fails if the layout loads while it names a schema no package registered — the keys
    registered reach it in its validation context — declares two kinds of thing on one folder, a
    folder that is not one step at the project's top, names the project file, which is fixed, or
    has not exactly one `single` kind, the project file; a writer but the person, femkit or a run;
    a fixed file of a part that is no folder, or out of its folder; a library of the project file;
    or an object type in no part kind, named like one, or in no table (projects.md § 4: "Whether a
    folder is a part or a group is read from that declaration"; "Every folder is one step"; "The
    project file is fixed"; the writer; `files`; `library`; the object types; § 6: "Schemas are
    registered, never imported"). The tests' layout loads (the fixture), so each refusal is the
    one change's."""
    write_layout(definitions, spoiled(*spoil))
    with kit.refused(DefinitionError, "definition-invalid", str(layout.file())):
        layout.load()


# ------------------------------------------------------------------ the shipped layout and the templates

def test_the_shipped_layout_reads_before_any_part_schema_and_binds_once_each_is_registered():
    """Fails if the shipped layout, with no part schema registered, breaks its own rules or binds
    — each schema refused at its kind's key — or, each one registered, does not open every
    template whole: every part loaded, its component's script read with its digest, and nothing
    else found (projects.md § 4: the shipped layout; § 6: "a key no package registered is refused";
    § 7: the templates)."""
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
        assert scripts == {f"{p.folder}/geometry.py": hashlib.sha256((folder / p.folder / "geometry.py").read_bytes())
                           .hexdigest() for p in opened.parts.values() if p.address.kind == "component"}, name


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


def test_a_parts_numbers_are_exact_and_its_quantities_read_by_the_unit_table(demo, toy_layout):
    """Fails if a part's number is read through a binary float — its digits past a float's lost —
    or its validators are not handed the unit table, so a quantity of the wrong dimension loads or
    the project does not open (projects.md § 6: "A part loads as every declared file does";
    core.md §§ 2, 11)."""
    digits = "0.12345678901234567890123"
    (demo.folder / "physics/heat.toml").write_text(HEAT + f'scale = {digits}\nsize = "0.5 um"\n')
    (demo.folder / "physics/optics.toml").write_text(OPTICS + 'size = "5 s"\n')
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    heat = opened.parts["physics:heat"].data
    assert heat.scale == Decimal(digits) and heat.size == "0.5 um"
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
    ('study:sweeps/gap_sweep:axes."project:parameters.gap"',
     Address("study", "sweeps/gap_sweep", ("axes", "project:parameters.gap"))),
    ("project:description", Address("project", None, ("description",))),
    ("material:GLOBAL/metals/gold", Address("material", "GLOBAL/metals/gold")),
])
def test_an_address_reads_and_writes_back_the_same(toy_layout, written, address):
    """Fails if an address — a grouped name, a quoted key holding `:` and `.`, the project file's
    unnamed part, a `GLOBAL/` name of a kind with a library — is read otherwise, or written back
    otherwise (projects.md § 5)."""
    assert toy_layout.address(written) == address and str(address) == written


@pytest.mark.parametrize("written", ["nokind:x", "study", "study:Bad", "study:a:x.", 'study:a:"open', "study:a:x..y",
                                     "component:GLOBAL/bowtie"])
def test_an_address_breaking_the_grammar_is_refused(toy_layout, written):
    """Fails if an address naming no kind, a named kind without its name, a name breaking the rule,
    a dotted path that does not close, or `GLOBAL/` opening the name of a kind the layout declares
    with no library is read at all (projects.md § 5)."""
    with kit.refused(UsageError, "bad-address", written):
        toy_layout.address(written)
