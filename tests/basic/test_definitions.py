"""Shipped definitions and their loader (definitions.md § 2)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tests.kit import planned, refused, run
from femkit.core.dirs import CONTROL
from femkit.core.errors import UsageError
from femkit.core.persist import write_toml
from femkit.core.schema import DefinitionError, load_toml, validate
from femkit.definitions import catalogue
from femkit.core.view import RefusalAnswer
from femkit.definitions.catalogue import CUDA_SUFFIX, CatalogueError, data_root, load_environments
from femkit.definitions.models import EnvironmentDefinition


def test_every_shipped_definition_loads():
    """Fails if any shipped file stops loading (definitions.md § 2.3: a test runs schema check)."""
    result = run("schema.check")
    assert result.ok(), result.text()


def test_the_reference_pages_match_the_models():
    """Fails if docs/reference/ differs from what the models render (definitions.md § 2.3)."""
    plan = planned("schema.docs")[1]
    assert plan.steps == (), "docs/reference/ is stale: run `python -m femkit schema docs`"


def _load_problems(tmp_path, text: str) -> dict[str, str]:
    path = tmp_path / "environment.toml"
    path.write_text(text)
    try:
        load_toml(path, EnvironmentDefinition)
    except DefinitionError as exc:
        return dict(exc.problems)
    return {}


def _shipped(name: str) -> str:
    return (data_root() / "environments" / f"{name}.toml").read_text()


def test_field_problems_are_reported_together_by_key_path(tmp_path):
    """Fails if a typo or a framework-owned option loads, is reported without its key
    path, or one hides the other (definitions.md § 2.2, § 4.2; core.md § 2)."""
    src = _shipped("ngsolve")
    n = len(tomllib.loads(src)["builds"])
    text = (src.replace('default = true\n', 'default = true\ndefualt = "x"\n', 1)
            + '\n[[builds]]\nid = "x"\nsource = "netgen"\n[builds.options]\nCMAKE_BUILD_TYPE = "Debug"\n'
            + '\n[[builds]]\nid = "y"\nsource = "netgen"\n[builds.options]\nX = [1]\n')
    problems = _load_problems(tmp_path, text)
    assert {"defualt", f"builds[{n}].options", f"builds[{n + 1}].options.X"} <= set(problems)
    assert not [p for p in problems if p.startswith(f"builds[{n + 1}].options.X.")]  # one problem, at its key


def test_a_dangling_reference_is_refused_at_its_key_path(tmp_path):
    """Fails if a build may name a source or build nobody declared, or the problem loses
    its key path (definitions.md § 2.2)."""
    src = _shipped("ngsolve")
    n = len(tomllib.loads(src)["builds"])
    problems = _load_problems(tmp_path, src + '\n[[builds]]\nid = "x"\nsource = "nope"\nafter = ["nothing"]\n')
    assert {f"builds[{n}].source", f"builds[{n}].after[0]"} <= set(problems)


def test_a_repeated_id_is_refused_at_the_entry_that_repeats(tmp_path):
    """Fails if an ID declared again — here, a [cuda] source with the name of one every Elmer
    environment has — loads, or is reported without the entry that repeats it (definitions.md § 2.2)."""
    src = _shipped("elmer").replace('[[cuda.sources]]\nid = "amgx"', '[[cuda.sources]]\nid = "zoltan"')
    assert "cuda.sources[0].id" in _load_problems(tmp_path, src)


def test_a_check_may_name_only_its_own_engines_readers_and_the_runners(tmp_path):
    """Fails if an environment loads naming a reader its engine does not register — another
    engine's, or none at all — instead of being refused at the check's key path
    (definitions.md § 5.3)."""
    src = _shipped("ngsolve")
    n = len(tomllib.loads(src)["checks"])
    problems = _load_problems(tmp_path, src + '\n[[checks]]\nid = "x"\nkind = "ctest"\nbuild = "ngsolve"\n'
                                              'test = "t"\nread = "elmer-solver-log"\n')
    assert f"checks[{n}].read" in problems


def test_a_definition_with_a_cuda_part_is_two_environments_and_only_one_has_cuda():
    """Fails if the CPU environment still solves a CUDA package, builds AmgX, sets a CUDA
    option or runs a GPU check, or loses a CPU part such as the bundled Zoltan source no build
    names; or if the CUDA environment lacks its CUDA part — packages, nvcc, AmgX, its CUDA
    options switched on — or is a default (definitions.md § 4.5)."""
    declared = load_toml(data_root() / "environments" / "elmer.toml", EnvironmentDefinition)
    envs = load_environments()
    cpu, gpu = envs["elmer"], envs["elmer-cuda"]
    assert not set(declared.cuda.packages) & set(cpu.packages.conda)
    assert set(declared.cuda.packages) <= set(gpu.packages.conda) and not gpu.default
    cpu_elmer = next(b for b in cpu.builds if b.id == "elmer")
    assert "amgx" not in {b.id for b in cpu.builds} and "amgx" not in cpu_elmer.after
    assert cpu_elmer.options["WITH_AMGX"] is False and "AMGX_ROOT" not in cpu_elmer.options
    assert {b.id for b in gpu.builds} == {b.id for b in cpu.builds} | {"amgx"}
    elmer = next(b for b in gpu.builds if b.id == "elmer")
    assert elmer.options["WITH_AMGX"] is True and elmer.options["AMGX_ROOT"] == "{prefix}"
    assert "amgx" in elmer.after and "nvcc" in gpu.provides.executables
    assert [s.id for s in cpu.sources] == [s.id for s in declared.sources]  # zoltan kept; amgx is [cuda]'s
    assert {s.id for s in gpu.sources} == {s.id for s in declared.sources} | {"amgx"}
    assert not [c for c in cpu.checks if c.device] and "nvcc" not in cpu.provides.executables
    ngsolve = {name: next(b for b in envs[name].builds if b.id == "ngsolve") for name in ("ngsolve", "ngsolve-cuda")}
    assert ngsolve["ngsolve"].options["USE_CUDA"] is False and not ngsolve["ngsolve"].cuda_architectures
    assert ngsolve["ngsolve-cuda"].options["USE_CUDA"] is True and ngsolve["ngsolve-cuda"].cuda_architectures


def _without_cuda(src: str) -> str:
    """The shipped ngsolve file without its [cuda] part and everything that needs one."""
    src = src[:src.index("[cuda]")] + src[src.index("[[sources]]"):]
    src = src.replace("[builds.cuda_options]\nUSE_CUDA = true\n", "").replace("cuda_architectures = true\n", "")
    return "\n".join(line for line in src.splitlines() if "device = true" not in line) + "\n"


@pytest.mark.parametrize("addition", [
    '\n[[checks]]\nid = "g"\nkind = "command"\nrun = ["true"]\nread = "summary"\ndevice = true\n',
    '\n[[builds]]\nid = "x"\nsource = "netgen"\ncuda_architectures = true\n',
])
def test_a_cuda_part_needs_the_cuda_table(tmp_path, addition):
    """Fails if an environment with a GPU check or a build compiled for CUDA loads without the
    [cuda] part that says what the CUDA environment adds (definitions.md § 4.5)."""
    src = _without_cuda(_shipped("ngsolve"))
    assert _load_problems(tmp_path, src) == {}  # what is left loads: only the addition can be the problem
    assert "cuda" in _load_problems(tmp_path, src + addition)


@pytest.mark.parametrize("name, text, at", [
    ("elmer", lambda s: s + "\n[cuda.builds.cuda_options]\nX = true\n", "cuda.builds[0].cuda_options"),
    ("ngsolve", lambda s: _without_cuda(s) + '\n[cuda]\ndescription = "x"\n', "cuda"),
    ("ngsolve", lambda s: s.replace('compilers = { c = "CC", cxx = "CXX", fortran = "FC" }', "compilers = {}"),
     "toolchain.compilers"),
    ("ngsolve", lambda s: s + '\n[[checks]]\nid = "x"\nkind = "command"\nrun = ["true"]\nread = "summary"\n'
                          'expect = { error = { max = inf } }\n',
     f"checks[{len(tomllib.loads(_shipped('ngsolve'))['checks'])}].expect.error.max"),
    ("ngsolve", lambda s: s + '\n[[checks]]\nid = "x"\nkind = "command"\nrun = ["true"]\nread = "summary"\n'
                          'upstream_verdict = false\n', f"checks[{len(tomllib.loads(_shipped('ngsolve'))['checks'])}].upstream_verdict"),
    ("ngsolve", lambda s: s.replace("[builds.cuda_options]\nUSE_CUDA = true\n",
                                    "[builds.cuda_options]\nUSE_CUDA = true\nUSE_MPI = false\n"), "builds[1]"),
])
def test_a_declaration_that_would_be_ignored_guessed_or_prove_nothing_is_refused(tmp_path, name, text, at):
    """Fails if a definition loads with options on a [cuda] build, which would never reach CMake;
    a [cuda] part that adds nothing, whose environment would be the CPU one under another name;
    a toolchain naming no compiler, whose check would prove nothing; one cache entry in both a
    build's options and its cuda_options, whose CUDA value would be a guess; an upstream verdict
    set aside on a check that has none; or an infinite bound, which bounds nothing (definitions.md
    § 4.5, § 4.6, § 5.1, § 5.2)."""
    assert _load_problems(tmp_path, _shipped(name)) == {}
    assert at in _load_problems(tmp_path, text(_shipped(name)))


_ELMER_CHECKS = len(tomllib.loads(_shipped("elmer"))["checks"])


@pytest.mark.parametrize("text, at", [
    (lambda s: s + '\n[[checks]]\nid = "x"\nkind = "ctest"\nbuild = "amgx"\ntest = "t"\nread = "summary"\n',
     f"checks[{_ELMER_CHECKS}].build"),
    (lambda s: s + '\n[[checks]]\nid = "x"\nkind = "pytest"\nsource = "amgx"\ntests = ["t"]\nread = "summary"\n',
     f"checks[{_ELMER_CHECKS}].source"),
    (lambda s: s.replace("\n[builds.options]\n", '\n[builds.options]\nX = "{build:amgx}"\n'), "builds[0].options.X"),
], ids=["a check names a [cuda] build", "a check names a [cuda] source", "a plain option names a [cuda] build"])
def test_what_the_cpu_environment_runs_may_not_name_what_only_cuda_declares(tmp_path, text, at):
    """Fails if a check without `device`, or a build's plain option, loads naming AmgX, which only
    elmer-cuda has: elmer would then fail deep in an install or a validate instead of the file
    being refused (definitions.md § 4.5)."""
    assert _load_problems(tmp_path, _shipped("elmer")) == {}
    assert at in _load_problems(tmp_path, text(_shipped("elmer")))


@pytest.mark.parametrize("name", [CONTROL, "ngsolve" + CUDA_SUFFIX, "a b"])
def test_a_definition_may_not_take_another_environments_name(definitions, name):
    """Fails if a definition named `control` or `<name>-cuda` loads — installing it would remove
    femkit's own control environment, or take a definition's CUDA environment's place — or one
    whose name no lock subject can hold, which would fail as a defect at its install
    (definitions.md § 4.5, core.md § 5)."""
    (definitions / "environments" / f"{name}.toml").write_text(_shipped("ngsolve"))
    with pytest.raises(CatalogueError) as refused:
        load_environments()
    assert [Path(e.file).stem for e in refused.value.errors] == [name]
    answer = RefusalAnswer.of(refused.value)                  # several files, one kind: what a script reads
    assert (answer.refused, answer.code) == ("DefinitionError", "definition-invalid")


@pytest.mark.parametrize("line", ["", "# the channel femkit uses", "conda-forge  "])
def test_channels_hold_one_bare_name_a_line(definitions, line):
    """Fails if channels.txt loads holding a blank line, a comment or stray spaces: the install
    script passes each line to the manager as a channel exactly as it stands, so femkit and the
    script would solve with different channels (definitions.md § 3)."""
    from femkit.definitions.catalogue import load_control
    assert load_control().channels and load_control().python_minor
    channels = definitions / "channels.txt"            # the test's own copy, by the path it was given
    channels.write_text(channels.read_text() + line + "\n")
    with refused(DefinitionError, "definition-invalid", str(channels)):
        load_control()


def test_an_environment_with_builds_declares_its_toolchain(tmp_path):
    """Fails if an environment with builds loads without its own [toolchain]: its compilers and
    build tools would come from wherever the solver or the host chose (definitions.md § 4.6)."""
    src = _shipped("ngsolve")
    start = src.index("[toolchain]")
    without = src[:start] + src[src.index("\n[", start + 1) + 1:]
    assert "toolchain" in _load_problems(tmp_path, without)



TOOL = {"description": "a tool", "version": "v1", "version_command": ["tool", "--version"],
        "packages": {"conda": ["tool=1"]}, "provides": {"executables": ["tool"]}}


@pytest.mark.parametrize("change, at", [
    ({"engine": "ngsolve"}, "engine"),                       # an engine and a tool's version command
    ({"version_command": None}, "engine"),                   # neither
    ({"fixed_variables": {"OMP_NUM_THREADS": "1"}}, "fixed_variables"),
    ({"default": True}, "default"),
    ({"thread_variables": ["X"]}, "thread_variables"),
])
def test_a_tool_environment_runs_no_engine_and_is_never_a_default(change, at):
    """Fails if a definition states both an engine and a tool's version command, or neither, or
    a tool environment carries variables for an engine's runs or a default install
    (definitions.md § 4.7)."""
    from femkit.core.schema import validate
    data = {**TOOL, **change}
    if data.get("version_command") is None:
        data.pop("version_command")
    with pytest.raises(DefinitionError) as caught:
        validate(EnvironmentDefinition, data, "tool.toml")
    assert at in [path for path, _ in caught.value.problems]


def test_the_web_environment_takes_the_control_environments_packages_by_reference(manager):
    """Fails if the web environment does not hold femkit's own libraries exactly as control.txt
    lists them — its server would run femkit on other versions — or the control environment
    holds the web's flask or Node.js (definitions.md § 4.7, ADR 0009)."""
    from femkit.definitions.catalogue import load_control
    plan = planned("env.install", names=["web"])[1]
    create = list(next(s for s in plan.steps if s.id.endswith("/create")).argv)
    control = load_control().dependencies
    assert all(d in create for d in control) and "flask>=3,<4" in create and "nodejs=22.23.5" in create
    assert not any(d.startswith(("flask", "nodejs")) for d in control)


def test_a_tool_environment_without_control_packages_holds_only_its_own(manager, definitions):
    """Fails if the create planned for a tool environment that does not ask for femkit's
    libraries installs them, or the Python femkit's own programs need (definitions.md § 4.7)."""
    data = definitions
    (data / "environments" / "tool.toml").write_text(
        'description = "a tool"\nversion = "v1"\nversion_command = ["tool", "--version"]\n'
        '[packages]\nconda = ["tool=1"]\n[provides]\nexecutables = ["tool"]\n')
    plan = planned("env.install", names=["tool"])[1]
    create = list(next(s for s in plan.steps if s.id.endswith("/create")).argv)
    assert create[-1] == "tool=1" and not any(a.startswith("python") for a in create)
    assert not set(catalogue.load_control().dependencies) & set(create)


def test_conda_names_the_declared_channels_on_a_create_from_a_lock_and_a_removal_and_mamba_on_neither():
    """Fails if conda's create from a saved lock or its removal leaves out the declared channels —
    under femkit's HOME it would stop on the terms of the base configuration's `defaults`, channels
    femkit never uses — or mamba's names them, which mamba 2.9.0 refuses on a removal (envs.md
    § 4.4; measured forms)."""
    from femkit.definitions.catalogue import load_control, load_managers
    from femkit.envs.manager import Manager
    kinds, channels = load_managers(), load_control().channels
    for kind, named in (("conda", True), ("mamba", False)):
        m = Manager(Path(f"/m/{kind}"), kind, kinds[kind], {})
        for argv in (m.create_from_lock(Path("/p"), Path("/lock.txt"), channels), m.remove(Path("/p"), channels)):
            assert (argv[-len(channels) * 2:] == [a for c in channels for a in ("-c", c)]) is named, (kind, argv)
            assert ("--override-channels" in argv) is named, (kind, argv)


@pytest.mark.parametrize("key, value, at", [
    ("version", ["{exe}", "--version", "{file}"], "version"),                        # a value it is never given
    ("root", {"argv": ["{exe}", "info", "-p", "{prefix}"], "key": "root_prefix"}, "root.argv"),
    ("remove", ["{exe}", "remove", "--all", "-y"], "remove"),                         # no prefix to remove
    ("create_from_lock", ["{exe}", "create", "-y", "-p", "{prefix}"], "create_from_lock"),   # the lock left out
], ids=["the version names a file", "a query names a prefix", "a removal names no prefix",
        "a create from a lock names no lock"])
def test_a_manager_command_names_exactly_the_values_femkit_renders_it_with(tmp_path, key, value, at):
    """Fails if a manager kind loads with a command naming a placeholder femkit never renders it
    with — it would stop an install, not the load — or leaving out the prefix or the lock it acts
    on (definitions.md § 6)."""
    from femkit.core.persist import write_toml
    from femkit.definitions.models import ManagerKind
    path = tmp_path / "conda.toml"
    write_toml(path, {**tomllib.loads((data_root() / "managers" / "conda.toml").read_text()), key: value})
    with pytest.raises(DefinitionError) as caught:
        load_toml(path, ManagerKind)
    assert at in dict(caught.value.problems), caught.value.problems


DERIVED = {"description": "d", "section": "7-derived-quantities"}
KIND = {"description": "d", "section": "3-conditions-on-an-outer-boundary", "on": ["outer_boundary"],
        "parameters": {"value": {"unit": "V", "description": "d"}}}


@pytest.mark.parametrize("change, at", [
    ({"science": "docs/science/none.md"}, "science"),                                   # no such document
    ({"derived": {"potential": DERIVED | {"unit": "V"}, "field": DERIVED | {"unit": "V/mm2"}}},
     "derived.field.unit"),                                                               # a unit the grammar does not read
    ({"derived": {"electric_field": DERIVED | {"unit": "V/m"}}}, "derived"),            # the unknown not observable
    ({"conditions": {"potential": KIND | {"on": ["boundary"]}}}, "conditions.potential.on[0]"),   # no such place
    ({"conditions": {"potential": KIND | {"section": "9-nowhere"}}}, "conditions.potential.section"),
])
def test_a_formulation_that_misstates_itself_does_not_load(change, at):
    """Fails if a formulation loads with a science document that does not exist, a unit the
    grammar does not read, its unknown not among what an observable may name, a condition on
    a place the vocabulary of places does not name, or a description pointing to a section its science
    document lacks (models.md § 4)."""
    from femkit.core.schema import validate
    from femkit.core.units import Units
    from femkit.definitions.catalogue import load_places, load_units
    from femkit.definitions.formulations import FormulationDefinition
    data = tomllib.loads((data_root() / "formulations" / "electrostatics.toml").read_text()) | change
    with pytest.raises(DefinitionError) as caught:
        validate(FormulationDefinition, data, "f.toml", {"units": Units(load_units()), "places": frozenset(load_places())})
    assert at in [path for path, _ in caught.value.problems]


def test_schema_check_refuses_a_page_declaration_that_names_what_is_not_served(definitions):
    """Fails if a page declaration whose workspace shows an operation that does not exist
    passes `schema check` (definitions.md § 2.3, web.md § 8.1)."""
    page = definitions / "web" / "page.toml"
    page.write_text(page.read_text().replace('document = "project.graph"', 'document = "project.nothing"', 1))
    result = run("schema.check")
    assert [(i.code, i.subject) for i in result.issues] == [("definition-invalid", str(page))]
    assert result.issues[0].message.startswith(f"{page}: workspaces[0].document:")    # where in the file, at its key path

@pytest.mark.parametrize("change, at", [
    ({"provided_by": "comsol"}, "provided_by"),                 # no such environment
    ({"imports": []}, "imports"),                              # builds `import`, imports nothing
])
def test_a_mesher_that_misstates_itself_does_not_load(change, at):
    """Fails if a mesher names an environment that does not exist, or builds `import` with no
    format (definitions.md § 2.2)."""
    from femkit.core.schema import validate
    from femkit.definitions.meshers import MesherDefinition
    data = tomllib.loads((data_root() / "meshers" / "gmsh.toml").read_text()) | change
    with pytest.raises(DefinitionError) as caught:
        validate(MesherDefinition, data, "m.toml", {"environments": {"elmer", "ngsolve"}})
    assert at in [path for path, _ in caught.value.problems]


@pytest.mark.parametrize("change, at", [
    ({"exercises": ["potential", "tunneling"]}, "benchmarks.two_material.exercises[1]"),   # no such kind
    ({"project": "nowhere"}, "benchmarks.two_material.project"),                          # no such template
    ({"reference": {"potential_low": "2/5 VV"}}, "benchmarks.two_material.reference.potential_low"),
])
def test_a_benchmark_that_misstates_itself_does_not_load(change, at):
    """Fails if a benchmark exercises a kind its formulation lacks, names a project that does not
    exist, or a reference value the unit grammar does not read (models.md § 4)."""
    from femkit.core.schema import validate
    from femkit.core.units import Units
    from femkit.definitions.catalogue import load_places, load_templates, load_units
    from femkit.definitions.formulations import FormulationDefinition
    data = tomllib.loads((data_root() / "formulations" / "electrostatics.toml").read_text())
    data["benchmarks"]["two_material"] |= change
    with pytest.raises(DefinitionError) as caught:
        validate(FormulationDefinition, data, "f.toml", {"units": Units(load_units()), "places": frozenset(load_places()),
                                                         "templates": load_templates()})
    assert at in [path for path, _ in caught.value.problems]


def test_an_environment_listing_a_pip_package_does_not_load():
    """Fails if an environment listing a pip package loads, though femkit installs nothing with
    pip: the package would be missing from the environment it builds (definitions.md § 4.1)."""
    data = tomllib.loads(_shipped("ngsolve"))
    data["packages"]["pip"] = ["requests"]
    with pytest.raises(DefinitionError) as caught:
        validate(EnvironmentDefinition, data, "ngsolve.toml")
    assert "packages.pip" in [path for path, _ in caught.value.problems]


@pytest.mark.parametrize("part", ["compilers", "mpi"])
def test_a_toolchain_naming_a_language_femkit_cannot_check_is_refused_when_it_loads(definitions, part):
    """Fails if a definition whose toolchain names a language the toolchain check has no program
    for loads — its install would pass a check that never compiled that language (definitions.md § 4.6)."""
    file = definitions / "environments" / "ngsolve.toml"
    old = {"compilers": 'compilers = { c = "CC",', "mpi": 'mpi = { c = "mpicc",'}[part]
    file.write_text(file.read_text().replace(old, old.replace("{ c", "{ cobol = \"COB\", c", 1) if part == "compilers"
                                             else old.replace("{ c", "{ cobol = \"mpicob\", c", 1), 1))
    with pytest.raises(CatalogueError) as caught:
        load_environments()
    assert [(Path(e.file).name, e.problems[0][0]) for e in caught.value.errors] == [("ngsolve.toml", "toolchain")]


def test_a_mesher_is_checked_against_the_environments_as_loaded_and_a_broken_one_said_once(definitions):
    """Fails if a mesher may not name a CUDA environment — one no file is named after — or if a
    broken environment file leaves every mesher unchecked, or is reported again under the
    meshers (definitions.md § 4.5, models.md § 6.5)."""
    from femkit.definitions.catalogue import load_meshers
    mesher = definitions / "meshers" / "gmsh.toml"
    shipped = mesher.read_text()
    mesher.write_text(shipped.replace('provided_by = "elmer"', 'provided_by = "elmer-cuda"', 1))
    assert load_meshers()["gmsh"].provided_by == "elmer-cuda"
    (definitions / "environments" / "web.toml").write_text("this is [ no TOML\n")
    mesher.write_text(shipped.replace('provided_by = "elmer"', 'provided_by = "nowhere"', 1))
    with pytest.raises(CatalogueError) as caught:
        load_meshers()
    assert [Path(e.file).name for e in caught.value.errors] == ["gmsh.toml"]


def test_the_definitions_folder_is_read_as_the_directories_are(monkeypatch, tmp_path):
    """Fails if FEMKIT_DEFINITIONS_DIR is taken relative to where the command runs, or its `~`
    is not the home folder (config.md § 2)."""
    monkeypatch.setenv(catalogue.VARIABLE, "relative/definitions")
    with refused(UsageError, "not-absolute", catalogue.VARIABLE):
        data_root()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(catalogue.VARIABLE, "~/definitions")
    assert data_root() == tmp_path / "definitions"


# ------------------------------------------------------------------ what a part reads (definitions.md § 1)

@pytest.mark.parametrize("change, at", [
    ({"edge": {"sentence": "s", "dimension": {"4": 1}}}, "edge.dimension.4"),
    ({"edge": {"sentence": "s", "dimension": {"3": 4}}}, "edge.dimension.3"),
    ({"body": {"sentence": "s", "dimension": {"2": 2, "3": 2}}}, "body.dimension"),
    ({"interface": {"sentence": "s", "dimension": {"2": 1, "3": 2}}}, "interface.bodies"),
    ({"point": {"sentence": "s", "dimension": {"2": 0}, "bodies": 1, "side": "inside"}}, "point.bodies"),
    ({"interface": {"sentence": "s", "dimension": {"2": 1}, "bodies": 2, "side": "outside"}}, "interface.side"),
    ({"Outer": {"sentence": "s", "dimension": {"2": 2}}}, "Outer"),
], ids=["a geometry of no dimension femkit draws", "a place larger than its geometry",
        "a face in one geometry and not in another", "a face touching no stated body",
        "a point touching a body", "a side for a face touching two", "a name that is no place's"])
def test_a_place_kind_that_misstates_itself_does_not_load(definitions, change, at):
    """Fails if a kind of place loads with a dimension for a geometry femkit does not draw or
    larger than its geometry's, a face that is one only in some geometries, a face that does not
    say how many bodies it touches or a place that is no face saying so, a side for a face that
    does not touch one body, or a name that is no place's (geometry.md § 7)."""
    path = definitions / "geometry" / "kinds.toml"
    write_toml(path, tomllib.loads(path.read_text()) | change)
    with refused(DefinitionError, "definition-invalid", str(path)) as caught:
        catalogue.load_places()
    assert at in [where for where, _ in caught.value.problems], caught.value.problems


def test_a_place_is_known_from_a_groups_promised_dimension_as_far_as_it_tells():
    """Fails if, before the geometry exists, a group of a frame's dimension is not a body, one of
    one less is not any of the three faces, an edge is a place of a 2-D geometry, or a point is
    not a point in both (geometry.md § 7: "Before the geometry exists")."""
    from femkit.definitions.places import possible
    places = catalogue.load_places()
    faces = ["outer_boundary", "interface", "embedded"]
    assert [possible(places, 2, d) for d in (2, 1, 0)] == [["body"], faces, ["point"]]
    assert [possible(places, 3, d) for d in (3, 2, 1, 0)] == [["body"], faces, ["edge"], ["point"]]


@pytest.mark.parametrize("change, at", [
    ({"unit": "furlong"}, "relative_permittivity.unit"),
    ({"equivalents": ["refractive_index"]}, "relative_permittivity.equivalents[0]"),
    ({"equivalents": ["relative_permittivity"]}, "relative_permittivity.equivalents[0]"),
    ({"values": "imaginary"}, "relative_permittivity.values"),
], ids=["a unit the table does not read", "an equivalent not on the list", "itself as its equivalent",
        "values neither real nor complex"])
def test_a_property_that_misstates_itself_does_not_load(definitions, change, at):
    """Fails if the property list loads with a unit the unit table does not read, an equivalent
    form that is not on the list or is the property itself, or values neither real nor complex
    (materials.md § 1)."""
    path = definitions / "properties.toml"
    data = tomllib.loads(path.read_text())
    data["relative_permittivity"] |= change
    write_toml(path, data)
    with refused(DefinitionError, "definition-invalid", str(path)) as caught:
        catalogue.load_properties()
    assert at in [where for where, _ in caught.value.problems], caught.value.problems


@pytest.mark.parametrize("file, old, new, at", [
    ("states/part.toml", "unloadable = {}", 'unloadable = { fix = { describe = "d", operation = "part.fix" } }',
     "actions.unloadable.fix.operation"),
    ("states/part.toml", 'state = "complete"\nwhen = "otherwise"', 'state = "complete"\nwhen = "loads"',
     "rules[3].when"),
    ("project/layout.toml", 'folder = "physics"', 'folder = "studies"', "folders"),
], ids=["an action naming no registered operation", "a machine that could fall through",
        "a layout putting two kinds in one folder"])
def test_schema_check_refuses_a_state_table_or_a_layout_breaking_its_rules(definitions, file, old, new, at):
    """Fails if `schema check` passes a machine's table naming an operation that is not registered
    or breaking its own rules, or a layout breaking its own — each reported in its file at its key
    path (core.md § 7; projects.md § 4; definitions.md § 2.3)."""
    path = definitions / file
    assert old in path.read_text()
    path.write_text(path.read_text().replace(old, new, 1))
    result = run("schema.check")
    assert [(i.code, i.subject) for i in result.issues] == [("definition-invalid", str(path))]
    assert result.issues[0].message.startswith(f"{path}: {at}:"), result.issues[0].message


@pytest.mark.parametrize("name, holds", [("half_made", {"notes.txt": ""}), ("Big", {"project.toml": "schema = 1\n"})],
                         ids=["a folder holding no project file", "a name the rule cannot name"])
def test_schema_check_refuses_a_template_that_is_no_project_named_bare(definitions, name, holds):
    """Fails if `schema check` passes a template folder that holds no project file, or whose name
    the name rule cannot name, so `project new --from` could not copy it (projects.md § 7)."""
    folder = definitions / "templates" / name
    folder.mkdir()
    for rel, text in holds.items():
        (folder / rel).write_text(text)
    result = run("schema.check")
    assert [(i.code, i.subject) for i in result.issues] == [("definition-invalid", str(folder))]
