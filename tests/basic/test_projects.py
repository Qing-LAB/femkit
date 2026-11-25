"""The projects framework (projects.md): a project's parts opened each on its own, the files no
part kind declares, the citations between parts, the layout as data, and a project carried to
another root — proven on a layout and toy schemas of the tests' own, since the framework names no
part kind."""

from __future__ import annotations

import copy
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import Field, ValidationInfo, field_validator

from tests import kit
from femkit.core.errors import UsageError
from femkit.core.persist import write_toml
from femkit.core.schema import LENGTH, DefinitionError, Model, as_quantity
from femkit.projects import addresses, door, layout, location, schemas
from femkit.projects.addresses import Address
from femkit.projects.door import Opened
from femkit.projects.layout import Layout
from femkit.projects.project import Project


# ------------------------------------------------------------------ the tests' own layout

class ToyProject(Model):
    """The project file: names its components and studies (projects.md § 3)."""

    description: str = ""
    components: list[str] = Field(default_factory=list, json_schema_extra={"ref": "component"})
    studies: list[str] = Field(default_factory=list, json_schema_extra={"ref": "study"})


class ToyComponent(Model):
    """A component, a folder holding its own file: the groups it promises."""

    groups: list[str] = Field(default_factory=list)


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
           "tests.study": ToyStudy}

# Every shape a part kind has (projects.md § 4): the one `single` file, a `folder` part, two `file` kinds;
# and folders that hold no part — a run's, femkit's, and the person's own.
LAYOUT = {
    "kinds": {
        "project": {"shape": "single", "schema": "tests.project", "rank": 0},
        "component": {"folder": "components", "shape": "folder", "file": "component.toml",
                      "schema": "tests.component", "rank": 1},
        "physics": {"folder": "physics", "shape": "file", "schema": "tests.physics", "rank": 2},
        "study": {"folder": "studies", "shape": "file", "schema": "tests.study", "rank": 3},
    },
    "folders": {
        "runs": {"writer": "the run", "moves": "yes"},
        ".femkit": {"writer": "femkit", "moves": "local"},
        "custom": {"writer": "the person", "moves": "yes"},
    },
}


def write_layout(definitions: Path, data: dict) -> None:
    folder = definitions / "project"
    folder.mkdir(exist_ok=True)
    write_toml(folder / "layout.toml", data)


@pytest.fixture
def toy_layout(definitions) -> Layout:
    """The tests' layout in the test's own definitions, its schemas registered as a package
    registers its own, and taken back after."""
    for key, model in SCHEMAS.items():
        schemas.register(key, model)
    try:
        write_layout(definitions, LAYOUT)
        yield layout.load()
    finally:
        for key in SCHEMAS:
            schemas.unregister(key)


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


def set_root(root: Path) -> None:
    kit.apply("config.set", key="paths.projects", value=f'"{root}"')


@pytest.fixture
def demo(tmp_path, toy_layout) -> Project:
    """The small project under a projects root in the test's own folder, the root set."""
    root = tmp_path / "projects"
    root.mkdir()
    project = make_project(root)
    set_root(root)
    return project


def tree(folder: Path) -> dict[str, bytes | None]:
    """Every file (its bytes) and folder (None) of a project, but its local `.femkit/`."""
    return {p.relative_to(folder).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in sorted(folder.rglob("*")) if p.relative_to(folder).parts[0] != ".femkit"}


def findings(opened: Opened) -> list[tuple[str, str, str]]:
    return sorted((i.code, i.subject, i.severity) for i in opened.issues)


def optics(order: int) -> str:
    return OPTICS.replace("order = 1", f"order = {order}")


# ------------------------------------------------------------------ (a) each part on its own

@pytest.mark.parametrize("broken, address, text", [
    ("physics/heat.toml", "physics:heat", 'groups = ["arms"]\norder = "high"\n'),
    ("physics/heat.toml", "physics:heat", 'groups = ["arms"\n'),
    ("project.toml", "project", 'description = "a bowtie, swept"\ncomponents = "bowtie"\n'),
], ids=["a physics its schema refuses", "a physics that is no TOML", "the project file"])
def test_a_part_broken_by_hand_is_a_finding_and_every_other_part_opens(demo, toy_layout, broken, address, text):
    """Fails if a part that does not load stops the project opening, hides another part, or is not
    an `unloadable` finding on that part's address (projects.md § 6: "each on its own: a part that
    does not load is a finding on that part — and every other part is still read"; a project file
    that does not load leaves the components and studies listed from their folders)."""
    (demo.folder / broken).write_text(text)
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    assert findings(opened) == [("unloadable", address, "error")]
    assert set(opened.parts) == PARTS
    part = opened.part(addresses.parse(address, toy_layout.named()))
    assert part.file == broken and part.data is None
    assert all(p.data is not None for a, p in opened.parts.items() if a != address)
    assert (demo.folder / broken).read_text() == text              # read, never changed


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
    set_root(elsewhere)

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


def test_a_file_no_part_kind_declares_is_a_stray_finding_and_never_read(demo, toy_layout):
    """Fails if a file in the tree that no part kind declares is read, taken for a part, or not a
    `stray` finding naming its path — or if a file in a folder the layout declares as holding no
    part, what a run or femkit writes or the person's own `custom/`, is (projects.md § 2: "A file in
    a folder of the tree that no part kind declares is a finding, never read"; § 3: "a file in a
    group folder that is no part is a finding, never read"; § 4: a folder that holds no part)."""
    for relative in STRAYS:
        path = demo.folder / relative
        path.write_text("component = 'bowtie\n")      # read as a part, it would not load
        path.chmod(0)                                  # read at all, it raises
    for relative in ("runs/geometry/run.log", ".femkit/view.json", "custom/solver.sif"):
        path = demo.folder / relative
        path.parent.mkdir(parents=True)
        path.write_text("{}")
    (demo.folder / "components/bowtie/geometry.py").write_text("x = 1\n")   # a folder part's own other file

    opened = door.open_project(demo, kit.ctx(), toy_layout)
    assert findings(opened) == [("stray", relative, "warning") for relative in sorted(STRAYS)]
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
    (("folders", "runs/old"), {"writer": "the run", "moves": "yes"}),
], ids=["a schema no package registered", "two kinds on one folder", "a kind on a folder femkit writes",
        "no project file kind", "two project file kinds", "the project file named again",
        "a kind's folder deeper than the top", "a folder holding no part deeper than the top"])
def test_a_layout_breaking_its_rules_is_refused(definitions, toy_layout, spoil):
    """Fails if the layout loads while it names a schema no package registered — the keys
    registered reach it in its validation context — declares two kinds of thing on one folder, a
    folder that is not one step at the project's top, names the project file, which is fixed, or
    has not exactly one `single` kind, the project file (projects.md § 4: "Whether a folder is a
    part or a group is read from that declaration"; "Every folder is one step"; "The project file
    is fixed"; § 6: "Schemas are registered, never imported"). The tests' layout loads (the
    fixture), so each refusal is the one change's."""
    write_layout(definitions, spoiled(*spoil))
    with kit.refused(DefinitionError, "definition-invalid", str(layout.file())):
        layout.load()


# ------------------------------------------------------------------ what the review of C found

def test_a_part_that_cannot_be_read_is_a_finding_and_the_rest_opens(demo, toy_layout):
    """Fails if a part whose bytes are no text, or that cannot be opened, stops the project from
    opening instead of being a finding on that part alone (projects.md § 6: "each on its own")."""
    (demo.folder / "physics/heat.toml").write_bytes(b"# caf\xe9\norder = 2\n")
    (demo.folder / "physics/optics.toml").chmod(0)
    try:
        opened = door.open_project(demo, kit.ctx(), toy_layout)
    finally:
        (demo.folder / "physics/optics.toml").chmod(0o644)
    assert {(i.code, i.subject) for i in opened.issues} == {("unloadable", "physics:heat"), ("unloadable", "physics:optics")}
    assert opened.parts["study:baseline"].data is not None


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
        door.text(opened, addresses.parse(asked, toy_layout.named()))


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


def test_a_folder_parts_other_files_are_its_own(demo, toy_layout):
    """Fails if a file inside a part's folder — a component's script, a mesh it holds, a deeper
    file of the part's own name — is taken for a part or for a stray file: a folder is a part or
    a group, never both (projects.md § 3)."""
    (demo.folder / "components/bowtie/mesh.bin").write_bytes(b"\x80\x81\x00binary")
    (demo.folder / "components/bowtie/sub").mkdir()
    (demo.folder / "components/bowtie/sub/component.toml").write_text("groups = []\n")
    opened = door.open_project(demo, kit.ctx(), toy_layout)
    assert "component:bowtie/sub" not in opened.parts and not opened.issues


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
    assert door.text(opened, addresses.parse("physics:heat:order", toy_layout.named())) == "2"
    with kit.refused(UsageError, "no-such-value", "physics:heat:nothing"):
        door.text(opened, addresses.parse("physics:heat:nothing", toy_layout.named()))


@pytest.mark.parametrize("written, address", [
    ("study:sweeps/gap_sweep", Address("study", "sweeps/gap_sweep")),
    ('study:sweeps/gap_sweep:axes."project:parameters.gap"',
     Address("study", "sweeps/gap_sweep", ("axes", "project:parameters.gap"))),
    ("project:description", Address("project", None, ("description",))),
    ("component:GLOBAL/metals/gold", Address("component", "GLOBAL/metals/gold")),
])
def test_an_address_reads_and_writes_back_the_same(toy_layout, written, address):
    """Fails if an address — a grouped name, a quoted key holding `:` and `.`, the project file's
    unnamed part, a `GLOBAL/` name — is read otherwise, or written back otherwise (projects.md § 5)."""
    assert addresses.parse(written, toy_layout.named()) == address and str(address) == written


@pytest.mark.parametrize("written", ["nokind:x", "study", "study:Bad", "study:a:x.", 'study:a:"open', "study:a:x..y"])
def test_an_address_breaking_the_grammar_is_refused(toy_layout, written):
    """Fails if an address naming no kind, a named kind without its name, a name breaking the rule,
    or a dotted path that does not close is read at all (projects.md § 5)."""
    with kit.refused(UsageError, "bad-address", written):
        addresses.parse(written, toy_layout.named())
