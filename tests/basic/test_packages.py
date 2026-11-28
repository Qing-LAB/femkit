"""The packages a project's scripts need travel with it (models.md § 2; definitions.md § 4.7; envs.md
§§ 1–4): its project file's `[postprocess] packages`, each a conda package and, where a script
imports it by another name, that name; read from each project file alone, through its schema, never
by opening the project; `postprocess` installed on each machine with femkit's own set and every
package the projects under the projects root declare — which enter its create, its lock and its
manifest, never its install fingerprint, and no other environment's — a package added later
delivered into it as it stands by `env install postprocess`, never by a rebuild; `model_prep` and
`postprocess` installed by default."""

from __future__ import annotations

from pathlib import Path

from femkit import registry
from tests import kit
from tests.kit import laplace  # noqa: F401 -- a fixture
from femkit.envs import install
from femkit.envs.state import facts, observe
from femkit.models import project

DECLARED = '\n[postprocess]\npackages = ["meshio", { conda = "scikit-image>=0.24", module = "skimage" }]\n'


def declare(folder: Path, text: str = DECLARED) -> None:
    """Packages declared in the project file of the project at ``folder``, as the person writes them."""
    with open(folder / "project.toml", "a", encoding="utf-8") as f:
        f.write(text)


def test_a_project_declares_its_scripts_packages_each_with_the_name_it_is_imported_by(laplace):
    """Fails if a project file's `[postprocess] packages` does not load — a conda package by its
    name, or a table naming the module a script imports it by — or if the names its scripts may
    import are not each package's own name or the module it states; or if an entry that is no
    conda package is not a finding at its key (models.md § 2: "The packages its scripts need travel
    with it"; § 5.2: "How a declared package's modules are known")."""
    declare(laplace)
    opened = kit.opened(laplace)
    data = opened.parts[opened.layout.project_kind].data
    assert project.modules(data) == ["meshio", "skimage"]
    said = [(i.code, i.label) for i in kit.run("project.check", project=laplace.name).issues if i.file == "project.toml"]
    assert said == [("package-held", "meshio")]                         # femkit's recipe holds it already
    kit.rewrite(laplace / "project.toml", 'packages = ["meshio",', 'packages = ["mesh io",')
    found = [(i.code, i.key) for i in kit.run("project.check", project=laplace.name).issues if i.file == "project.toml"]
    assert ("unloadable", "postprocess.packages[0]") in found


def test_the_door_reads_one_parts_file_on_its_own(laplace):
    """Fails if the door gives no read of one part's file on its own — the project file's text, as the
    layout puts it, without opening the project; None where it is not there — the read each project
    file's `[postprocess]` is taken through, so a project whose other parts do not load still declares
    its packages (projects.md § 6: "One part's file read on its own, never the project opened";
    framework.md § 5; framework.md § 1, rule 2: only the door reads a project's file)."""
    from femkit.projects import door, layout
    from femkit.projects.addresses import Address
    from femkit.projects.project import Project
    shape = layout.read_once(kit.ctx())
    alone, file = Project(laplace.parent, laplace.name), Address(shape.project_kind, None)
    declare(laplace)
    (laplace / "studies" / "check.toml").write_text("schema = [\n")
    assert door.read_alone(alone, shape, file) == (laplace / "project.toml").read_text()
    assert "meshio" in project.declared(kit.ctx()).packages
    (laplace / "project.toml").unlink()
    assert door.read_alone(alone, shape, file) is None


def _steps(name: str = "postprocess") -> dict[str, tuple[str, ...] | None]:
    """What `env install NAME` would run, each step by its ID with its command."""
    return {s.id.split("/", 1)[1]: s.argv for s in kit.planned("env.install", names=[name])[1].steps}


def test_a_package_a_project_adds_is_delivered_into_postprocess_as_it_stands(laplace, manager):
    """Fails if a package a project under the projects root declares moves `postprocess`'s install
    fingerprint — the installed environment then `outdated`, and another project's package would make
    its stages anew — or any other environment's; or if `env install postprocess` does not deliver
    each package the projects declare that it lacks, once each, into its prefix as it stands — the
    manager's install from the declared channels, the lock saved again, the manifest written with
    them, then the validate — or removes or creates it to do so (envs.md §§ 2, 3.3, 4.1, 4.3;
    definitions.md § 4.7: "delivered into the existing environment")."""
    registry.operations()
    alone = {name: facts(kit.ctx(), name).install_fingerprint for name in ("postprocess", "model_prep", "gmsh")}
    kit.installed("postprocess", outcomes=[])
    assert _steps() == {}                                                  # ready, and nothing lacking
    declare(laplace)
    other = kit.copy_template(laplace.parent, "two_material", "slab")
    declare(other, '\n[postprocess]\npackages = ["pint", "meshio"]\n')
    assert {name: facts(kit.ctx(), name).install_fingerprint for name in alone} == alone
    assert observe(kit.ctx(), "postprocess")[1].value == "ready"
    steps = _steps()
    assert list(steps) == ["deliver", "lock", "manifest", "validate"]
    deliver = steps["deliver"]
    assert deliver[1:2] == ("install",) and "--override-channels" in deliver
    assert "https://conda.anaconda.org/conda-forge" in deliver             # the declared channel, by its address
    assert [w for w in deliver if w in ("pint", "scikit-image>=0.24", "meshio")] == ["pint", "scikit-image>=0.24"]
    assert install.target(kit.ctx(), "postprocess").projects == ["pint", "scikit-image>=0.24"]   # meshio: femkit's


def test_a_build_of_postprocess_takes_every_package_the_projects_declare(laplace, manager):
    """Fails if `postprocess` built from its constraints does not take each package the projects
    declare in its one create, or, built from its saved lock, does not deliver them after it; or if
    another environment takes them (envs.md § 4.1; definitions.md § 4.7)."""
    registry.operations()
    declare(laplace)
    steps = _steps()
    assert "deliver" not in steps and steps["create"].count("scikit-image>=0.24") == 1
    assert not [w for s in _steps("model_prep").values() if s for w in s if w == "scikit-image>=0.24"]
    lock = install.target(kit.ctx(), "postprocess").lock
    lock.parent.mkdir(parents=True)
    lock.write_text("@EXPLICIT\n")
    steps = _steps()
    assert list(steps)[:3] == ["create", "deliver", "lock"] and "scikit-image>=0.24" in steps["deliver"]


def test_a_project_file_whose_packages_do_not_load_adds_none_and_says_so(laplace, manager):
    """Fails if a project file whose `[postprocess]` does not load, or which is no TOML, adds a
    package, makes `postprocess` anything but what it was, or goes unsaid in `env install`'s plan —
    a note naming the file; or if a project file whose other keys do not load loses the packages its
    `[postprocess]` declares: each is read alone, through the project file's schema, never by
    opening the project (envs.md § 3.1; definitions.md § 4.7)."""
    registry.operations()
    kit.installed("postprocess", outcomes=[])
    declare(laplace, '\n[postprocess]\npackages = ["mesh io"]\n')
    other = kit.copy_template(laplace.parent, "two_material", "slab")
    (other / "project.toml").write_text("description = \"unclosed\n")
    third = kit.copy_template(laplace.parent, "two_material", "third")
    declare(third, '\nnot_a_key_of_the_project_file = 1\n[postprocess]\npackages = ["pint"]\n')
    assert observe(kit.ctx(), "postprocess")[1].value == "ready"
    plan = kit.planned("env.install", names=["postprocess"])[1]
    assert [s.id for s in plan.steps] == ["postprocess/deliver", "postprocess/lock", "postprocess/manifest",
                                          "postprocess/validate"]
    assert [w for w in plan.steps[0].argv if w in ("pint", "mesh io")] == ["pint"]
    notes = {Path(i.file).parent.name for i in plan.issues if i.severity == "info" and i.file}
    assert notes == {laplace.name, "slab"}


def test_model_prep_and_postprocess_are_installed_by_default(manager):
    """Fails if `env install --all` does not install `model_prep` and `postprocess`, where every
    project's definitions and observables scripts run (envs.md § 1: "a default"; definitions.md
    § 4.7: "It is `default` when every project needs it")."""
    kit.apply("config.set", key="launch.mpi", value='["mpirun", "-np", "{ranks}"]')   # the engines' toolchain runs MPI
    steps = kit.planned("env.install", all=True)[1].steps
    assert {s.id.split("/", 1)[0] for s in steps} >= {"model_prep", "postprocess"}
