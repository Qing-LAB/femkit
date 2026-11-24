"""Shipped definitions and their loader (definitions.md § 2)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from femkit.core.dirs import CONTROL
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, load_toml, validate
from femkit.definitions import catalogue
from femkit.definitions.catalogue import CUDA_SUFFIX, CatalogueError, data_root, load_environments
from femkit.definitions.models import EnvironmentDefinition
from femkit.reference import SchemaDocs, schema_check


def test_every_shipped_definition_loads():
    """Fails if any shipped file stops loading (definitions.md § 2.3: a test runs schema check)."""
    result = schema_check.run(schema_check.request(), Context.from_process())
    assert result.ok(), result.text()


def test_the_reference_pages_match_the_models():
    """Fails if docs/reference/ differs from what the models render (definitions.md § 2.3)."""
    plan = SchemaDocs.plan(SchemaDocs.request(), Context.from_process())
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


@pytest.mark.parametrize("name", [CONTROL, "ngsolve" + CUDA_SUFFIX])
def test_a_definition_may_not_take_another_environments_name(definitions, name):
    """Fails if a definition named `control` or `<name>-cuda` loads: installing it would remove
    femkit's own control environment, or take a definition's CUDA environment's place
    (definitions.md § 4.5)."""
    (definitions / "environments" / f"{name}.toml").write_text(_shipped("ngsolve"))
    with pytest.raises(CatalogueError) as refused:
        load_environments()
    assert [Path(e.file).stem for e in refused.value.errors] == [name]


@pytest.mark.parametrize("line", ["", "# the channel femkit uses", "conda-forge  "])
def test_channels_hold_one_bare_name_a_line(definitions, line):
    """Fails if channels.txt loads holding a blank line, a comment or stray spaces: the install
    script passes each line to the manager as a channel exactly as it stands, so femkit and the
    script would solve with different channels (definitions.md § 3)."""
    from femkit.definitions.catalogue import load_control
    assert load_control().channels and load_control().python_minor
    channels = definitions / "channels.txt"            # the test's own copy, by the path it was given
    channels.write_text(channels.read_text() + line + "\n")
    with pytest.raises(DefinitionError):
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
    from femkit.envs.operations import EnvInstall
    plan = EnvInstall.plan(EnvInstall.request(names=["web"]), Context.from_process())
    create = list(next(s for s in plan.steps if s.id.endswith("/create")).argv)
    control = load_control().dependencies
    assert all(d in create for d in control) and "flask>=3,<4" in create and "nodejs=22.23.5" in create
    assert not any(d.startswith(("flask", "nodejs")) for d in control)


def test_a_tool_environment_without_control_packages_holds_only_its_own(manager, definitions):
    """Fails if the create planned for a tool environment that does not ask for femkit's
    libraries installs them, or the Python femkit's own programs need (definitions.md § 4.7)."""
    from femkit.envs.operations import EnvInstall
    data = definitions
    (data / "environments" / "tool.toml").write_text(
        'description = "a tool"\nversion = "v1"\nversion_command = ["tool", "--version"]\n'
        '[packages]\nconda = ["tool=1"]\n[provides]\nexecutables = ["tool"]\n')
    plan = EnvInstall.plan(EnvInstall.request(names=["tool"]), Context.from_process())
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


DERIVED = {"description": "d", "section": "7-derived-quantities"}
KIND = {"description": "d", "section": "3-conditions-on-an-outer-boundary", "on": ["boundary"],
        "parameters": {"value": {"unit": "V", "description": "d"}}}


@pytest.mark.parametrize("change, at", [
    ({"science": "docs/science/none.md"}, "science"),                                   # no such document
    ({"derived": {"potential": DERIVED | {"unit": "V"}, "field": DERIVED | {"unit": "V/mm2"}}},
     "derived.field.unit"),                                                               # a unit the grammar does not read
    ({"derived": {"electric_field": DERIVED | {"unit": "V/m"}}}, "derived"),            # the unknown not observable
    ({"conditions": {"potential": KIND | {"on": ["edge"]}}}, "conditions.potential.on[0]"),
    ({"conditions": {"potential": KIND | {"section": "9-nowhere"}}}, "conditions.potential.section"),
])
def test_a_formulation_that_misstates_itself_does_not_load(change, at):
    """Fails if a formulation loads with a science document that does not exist, a unit the
    grammar does not read, its unknown not among what an observable may name, a condition on
    a region kind that does not exist, or a description pointing to a section its science
    document lacks (models.md § 4)."""
    from femkit.core.schema import validate
    from femkit.core.units import Units
    from femkit.definitions.catalogue import load_units
    from femkit.definitions.formulations import FormulationDefinition
    data = tomllib.loads((data_root() / "formulations" / "electrostatics.toml").read_text()) | change
    with pytest.raises(DefinitionError) as caught:
        validate(FormulationDefinition, data, "f.toml", {"units": Units(load_units())})
    assert at in [path for path, _ in caught.value.problems]


def test_schema_check_refuses_a_page_declaration_that_names_what_is_not_served(definitions):
    """Fails if a page declaration whose workspace shows an operation that does not exist
    passes `schema check` (definitions.md § 2.3, web.md § 8.1)."""
    page = definitions / "web" / "page.toml"
    page.write_text(page.read_text().replace('document = "model.graph"', 'document = "model.nothing"', 1))
    result = schema_check.run(schema_check.request(), Context.from_process())
    assert [i.subject for i in result.issues] == [str(page)]
    assert "workspaces.0.document" in result.issues[0].message

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
    ({"project": "electrostatics/benchmarks/none"}, "benchmarks.two_material.project"),     # no such project
    ({"reference": {"potential_low": "2/5 VV"}}, "benchmarks.two_material.reference.potential_low"),
])
def test_a_benchmark_that_misstates_itself_does_not_load(change, at):
    """Fails if a benchmark exercises a kind its formulation lacks, names a project that does not
    exist, or a reference value the unit grammar does not read (models.md § 4)."""
    from femkit.core.schema import validate
    from femkit.core.units import Units
    from femkit.definitions.catalogue import load_units
    from femkit.definitions.formulations import FormulationDefinition
    data = tomllib.loads((data_root() / "formulations" / "electrostatics.toml").read_text())
    data["benchmarks"]["two_material"] |= change
    with pytest.raises(DefinitionError) as caught:
        validate(FormulationDefinition, data, "f.toml", {"units": Units(load_units()), "root": data_root() / "formulations"})
    assert at in [path for path, _ in caught.value.problems]


def test_an_environment_listing_a_pip_package_does_not_load():
    """Fails if an environment listing a pip package loads, though femkit installs nothing with
    pip: the package would be missing from the environment it builds (definitions.md § 4.1)."""
    data = tomllib.loads(_shipped("ngsolve"))
    data["packages"]["pip"] = ["requests"]
    with pytest.raises(DefinitionError) as caught:
        validate(EnvironmentDefinition, data, "ngsolve.toml")
    assert "packages.pip" in [path for path, _ in caught.value.problems]
