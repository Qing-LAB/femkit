"""Shipped definitions and their loader (definitions.md § 2)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tests import kit
from tests.kit import ctx as kit_ctx, planned, refused, run
from femkit.core.dirs import CONTROL
from femkit.core.errors import UsageError
from femkit.core.persist import exact_number, write_toml
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
    assert plan.steps == (), "docs/reference/ is stale: run `femkit schema docs`"


def _load_problems(tmp_path, text: str) -> dict[str, str]:
    """An environment definition's problems, as the catalogue loads it."""
    path = tmp_path / "environment.toml"
    path.write_text(text)
    try:
        load_toml(path, EnvironmentDefinition, catalogue.environment_context())
    except DefinitionError as exc:
        return dict(exc.problems)
    return {}


def test_an_environments_engine_is_checked_against_the_engines_its_context_gives():
    """Fails if an environment definition's validator reads the registered engines from a global
    instead of the context its loader gives it — an engine that context does not register then
    loads (core.md § 2)."""
    data = tomllib.loads(_shipped("ngsolve"))
    with pytest.raises(DefinitionError) as caught:
        validate(EnvironmentDefinition, data, "ngsolve.toml", {"engines": {"elmer": frozenset()}})
    assert "engine" in [path for path, _ in caught.value.problems]


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
    ({"version_command": None}, "version_command"),          # no command to state its version
    ({"fixed_variables": {"OMP_NUM_THREADS": "1"}}, "fixed_variables"),
    ({"thread_variables": ["X"]}, "thread_variables"),
])
def test_a_tool_environment_runs_no_engine(change, at):
    """Fails if a definition states no command that states its version — every environment's,
    an engine's too (definitions.md § 4) — or a tool environment carries variables for an
    engine's runs (definitions.md § 4.7)."""
    from femkit.core.schema import validate
    data = {**TOOL, **change}
    if data.get("version_command") is None:
        data.pop("version_command")
    with pytest.raises(DefinitionError) as caught:
        validate(EnvironmentDefinition, data, "tool.toml")
    assert any(path == at or f"`{at}`" in reason for path, reason in caught.value.problems), caught.value.problems


TOOL_CHECK = {"id": "c", "kind": "command", "run": ["python", "-m", "a.check", "{work}"], "read": "summary"}


@pytest.mark.parametrize("change, at", [
    ({}, None),                                                       # a default with a command check: loads
    ({"read": "elmer-solver-log"}, "checks[0].read"),                 # an engine's reader: it has no engine
    ({"kind": "ctest", "build": "b", "test": "t", "run": None}, "checks[0].kind"),   # nothing built to test
])
def test_a_tool_environment_may_be_a_default_checked_by_commands_the_generic_readers_read(change, at):
    """Fails if a tool environment every project needs cannot be installed by default with a
    check of its own — the mesh step's `gmsh` — or loads with a check no generic reader reads, or
    of a kind that tests a build it does not have (definitions.md § 4.7)."""
    from femkit.core.schema import validate
    data = {**TOOL, "default": True, "checks": [{**TOOL_CHECK, **change}]}
    if at is None:
        env = validate(EnvironmentDefinition, data, "tool.toml")
        assert env.default and env.tool and [c.id for c in env.checks] == ["c"]
        return
    with pytest.raises(DefinitionError) as caught:
        validate(EnvironmentDefinition, data, "tool.toml")
    assert at in [path for path, _ in caught.value.problems], caught.value.problems


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
    """Fails if the create planned for a tool environment that neither asks for femkit's libraries
    nor provides Python installs them, or a Python (definitions.md § 4.7)."""
    data = definitions
    (data / "environments" / "tool.toml").write_text(
        'description = "a tool"\nversion = "v1"\nversion_command = ["tool", "--version"]\n'
        '[packages]\nconda = ["tool=1"]\n[provides]\nexecutables = ["tool"]\n')
    plan = planned("env.install", names=["tool"])[1]
    create = list(next(s for s in plan.steps if s.id.endswith("/create")).argv)
    assert create[-1] == "tool=1" and not any(a.startswith("python") for a in create)
    assert not set(catalogue.load_control().dependencies) & set(create)


def test_a_tool_environment_that_provides_python_holds_the_python_every_environment_shares(manager, definitions):
    """Fails if a tool environment that provides Python — the mesh step's, which runs femkit's own
    programs — is solved to whatever Python the solver picks: measured 2026-11-25, `gmsh` unpinned
    took Python 3.15.2 beside 3.12.16 everywhere else (definitions.md § 4.7)."""
    (definitions / "environments" / "pytool.toml").write_text(
        'description = "a tool with Python"\nversion = "v1"\nversion_command = ["tool", "--version"]\n'
        '[packages]\nconda = ["tool=1"]\n[provides]\nexecutables = ["python", "tool"]\n')
    plan = planned("env.install", names=["pytool"])[1]
    create = list(next(s for s in plan.steps if s.id.endswith("/create")).argv)
    assert f"python={catalogue.load_control().python_minor}" in create


def test_conda_names_the_declared_channels_on_a_create_from_a_lock_and_a_removal_and_mamba_on_neither():
    """Fails if conda's create from a saved lock or its removal leaves out the declared channels —
    it would stop on the terms of the base configuration's `defaults`, channels femkit never uses —
    or mamba's names them, which mamba 2.9.0 refuses on a removal (envs.md § 4.4; measured forms)."""
    from femkit.definitions.catalogue import load_control, load_managers
    from femkit.envs.manager import Manager
    kinds, channels = load_managers(), load_control().channels
    for kind, named in (("conda", True), ("mamba", False)):
        m = Manager(Path(f"/m/{kind}"), kind, kinds[kind], {})
        each = [m.argv(kinds[kind].channel, channel=c) for c in channels]   # as the kind names one
        for argv in (m.create_from_lock("femkit-x", Path("/lock.txt"), channels), m.remove("femkit-x", channels)):
            assert (argv[-len(channels) * 2:] == [a for c in each for a in c]) is named, (kind, argv)
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
    data = tomllib.loads((data_root() / "formulations" / "electrostatics.toml").read_text(),
                         parse_float=exact_number) | change
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

def test_a_formulation_names_its_properties_from_the_list_and_repeats_none_of_it(definitions):
    """Fails if a formulation loads naming a property the property list lacks, or stating a
    property's unit or sentence, which are the list's (models.md § 4.3: "the material properties
    it reads, by their names in the property list, each needed real or allowed complex";
    materials.md § 1: "it never defines a property of its own")."""
    path = definitions / "formulations" / "electrostatics.toml"
    shipped = tomllib.loads(path.read_text())
    spec = shipped["properties"]["relative_permittivity"]
    for change, at in (({"conductivity": spec}, "properties.conductivity"),
                       ({"relative_permittivity": spec | {"unit": "1"}}, "properties.relative_permittivity.unit"),
                       ({"relative_permittivity": spec | {"description": "d"}},
                        "properties.relative_permittivity.description")):
        write_toml(path, shipped | {"properties": shipped["properties"] | change})
        with pytest.raises(CatalogueError) as caught:
            catalogue.load_formulations()
        assert [where for e in caught.value.errors for where, _ in e.problems] == [at]


def _shipped_toml(relative: str) -> dict:
    return tomllib.loads((data_root() / relative).read_text())


def _context() -> dict:
    """What the catalogue gives a stage kind, an artifact type, a mesher or a hand-over beside its
    file (core.md § 2): the environments femkit declares, the artifact types, femkit's stage programs, the
    documents a stage is handed, the places, the engines' packages and the project layout's part
    kinds with the files each holds by a fixed name."""
    from femkit.definitions.catalogue import load_artifacts, load_places, stage_programs
    from femkit.engines import package_dir, registered
    from femkit.engines.stages import documents
    from femkit.definitions.catalogue import load_environments
    from femkit.projects import layout
    return {"environments": set(load_environments()), "artifacts": frozenset(load_artifacts()),
            "programs": stage_programs(), "documents": frozenset(documents.SHAPES), "places": frozenset(load_places()),
            "engine_packages": {engine: package_dir(engine) for engine in registered()}, "parts": layout.read().fixed()}


@pytest.mark.parametrize("change, at", [
    ({"provided_by": "nosuch"}, "provided_by"),                            # no such environment
    ({"program": "nowhere.py"}, "program"),                                # no stage program of femkit's
    ({"reads": {"geometry": "geometry/step"}}, "reads.geometry"),          # no such artifact type
    ({"reads": {"mesh": "geometry/xao"}, "arguments": ["{recipe}", "{mesh}", "{regions}"]}, "reads.mesh"),
    ({"arguments": ["{recipe}", "{geometry}", "{mesh}", "{out}"]}, "arguments"),   # a file it is not handed
    ({"arguments": ["{recipe}", "{geometry}", "{mesh}"]}, "arguments"),    # its region map, written nowhere
    ({"arguments": ["{recipe}", "{geometry}", "{mesh?}", "{regions}"]}, "arguments"),   # a file it may lack
    ({"arguments": ["{recipe}", "{geometry}", "{writes:mesh}", "{regions}"]}, "arguments"),
    ({"writes": {"mesh": "mesh/msh-2.2", "regions": "mesh/regions", "recipe": "mesh/regions"}}, "writes.recipe"),
    ({"order": "script"}, "order"),                                        # neither the recipe's nor the contract's
    ({"routes": {}}, "routes"),                                            # hand-overs are files of their own
    ({"builds": ["rectangle"]}, "builds"),                                 # a shape kind: no key of a mesher
])
def test_a_mesher_that_misstates_itself_does_not_load(change, at):
    """Fails if a mesher names an environment that does not exist, a program femkit's stage
    programs do not hold, or an artifact type no `artifacts.toml` declares; calls a file it reads
    and one it writes by one name, or one like a document or a check's record; hands its program a
    file it neither reads nor writes, leaves one
    it writes unnamed, or names one as optional or by an argument; takes its mesh's geometry order
    from neither the recipe nor the contract; or keeps the hand-overs, or a list of shape kinds,
    which no model of it has (definitions.md § 2.2; workflow.md § 2.3; ADR 0013)."""
    from femkit.definitions.meshers import MesherDefinition
    data = _shipped_toml("meshers/gmsh.toml") | change
    with pytest.raises(DefinitionError) as caught:
        validate(MesherDefinition, data, "m.toml", _context())
    assert at in [path for path, _ in caught.value.problems], caught.value.problems


@pytest.mark.parametrize("change, at", [
    ({"engine": "nosuch"}, "engine"),                                      # no such engine
    ({"program": "nowhere.py"}, "program"),                                # no such file in its package
    ({"names": ["body", "volume"]}, "names"),                              # no such place
    ({"reads": "mesh/vtk"}, "reads"),                                      # no such artifact type
    ({"arguments": ["{mesh}", "mesh"]}, "arguments"),                      # the groups it hands, read nowhere
    ({"arguments": ["{mesh}", "{handover}", "{out}"]}, "arguments"),       # no such placeholder
])
def test_a_hand_over_that_misstates_itself_does_not_load(change, at):
    """Fails if a hand-over names an engine no adapter registers, a program its engine's package
    does not hold, a place that is none, or an artifact type no `artifacts.toml` declares; or
    arguments that do not name the mesh and the groups it hands, or name another file
    (definitions.md § 2.2; geometry.md § 8)."""
    from femkit.definitions.meshers import HandOver
    data = _shipped_toml("handovers/elmergrid.toml") | change
    with pytest.raises(DefinitionError) as caught:
        validate(HandOver, data, "h.toml", _context())
    assert at in [path for path, _ in caught.value.problems], caught.value.problems


@pytest.mark.parametrize("kind, change, at", [
    ("geometry", {"environment": "nosuch"}, "geometry.environment"),             # no such environment
    ("geometry", {"outputs": {"output": "geometry/step"}}, "geometry.outputs.output"),   # no such artifact type
    ("geometry", {"documents": ["inputs", "drawing"]}, "geometry.documents"),    # no such document
    ("geometry", {"check": ["{python}", "nowhere.py", "{contract}"]}, "geometry.check"),   # no stage program
    ("geometry", {"check": ["check_geometry.py", "{contract}"]}, "geometry.check"),      # not on its own python
    ("geometry", {"program": ["{python}", "geometry.py", "{inputs}", "{output}", "{shape}"]}, "geometry.program"),
    ("geometry", {"program": ["{python}", "geometry.py", "{inputs}", "{output}", "{mesh}"]}, "geometry.program"),
    ("geometry", {"program": ["{python}", "geometry.py", "{inputs}", "{output?}", "{mesh?}"]}, "geometry.program"),
    ("geometry", {"program": None}, "geometry"),                                 # no filler, and no program
    ("geometry", {"asked": {"brep": "geometry/brep", "outputs": "mesh/msh-2.2"}}, "geometry.asked.outputs"),
    ("mesh", {"environment": "gmsh"}, "mesh"),                                   # a slot its mesher fills
    ("mesh", {"filled_by": "engine"}, "mesh.filled_by"),                         # no such filler
    ("geometry", {"environment": "the engine"}, "geometry.environment"),         # neither one nor `engine`
    ("geometry", {"brings": "script"}, "geometry.brings"),                       # no part kind of the layout
    ("geometry", {"brings": "physics"}, "geometry.program"),                     # a file no physics holds
])
def test_a_stage_kind_that_misstates_itself_does_not_load(kind, change, at):
    """Fails if a stage kind names an environment, an artifact type or a document that does not
    exist; a check that is not one of femkit's stage programs on the environment's own python; a
    file named like a document or a check's record, so one placeholder would name two; a
    placeholder naming none of its files, documents or records, a file it writes only when asked
    as one it is always handed, or one always written as one it may lack; or if a kind no filler
    fills leaves a slot unset, or one its mesher fills states it — two homes for one fact
    (definitions.md § 2.2; workflow.md § 2.1)."""
    from femkit.definitions.stages import Stages
    data = _shipped_toml("stages.toml")
    data["kinds"][kind] = {k: v for k, v in (data["kinds"][kind] | change).items() if v is not None}
    with pytest.raises(DefinitionError) as caught:
        validate(Stages, data, "stages.toml", _context())
    assert f"kinds.{at}" in [path for path, _ in caught.value.problems], caught.value.problems


@pytest.mark.parametrize("brings, at", [("physics", "kinds.geometry.program"), ("script", "kinds.geometry.brings")])
def test_schema_check_holds_each_stage_kind_to_the_layout_as_its_one_reader_reads_it(definitions, brings, at):
    """Fails if `schema check` passes a stage kind that brings a part kind the project layout does
    not declare, or runs a file no part of the kind it brings holds — the layout read by its one
    reader, the projects domain's, above the catalogue (definitions.md §§ 2.2, 2.3)."""
    stages = definitions / "stages.toml"
    stages.write_text(stages.read_text().replace('brings = "component"', f'brings = "{brings}"', 1))
    found = kit.run("schema.check").issues
    assert any("stages.toml" in str(i.subject) and at in i.message for i in found), [i.message for i in found]


def test_the_meshing_sequence_takes_no_name_a_kinds_batch_takes():
    """Fails if `stages.toml` names a study's meshing sequence as a kind names its batch: the two
    launch folders of one job would be one folder (workflow.md § 7)."""
    from femkit.definitions.stages import Stages
    data = _shipped_toml("stages.toml")
    data["sequence"] = data["kinds"]["mesh"]["batch"]
    with pytest.raises(DefinitionError) as caught:
        validate(Stages, data, "stages.toml", _context())
    assert "sequence" in [path for path, _ in caught.value.problems], caught.value.problems


def test_a_stage_kind_declared_before_a_kind_it_takes_from_does_not_load():
    """Fails if `stages.toml` may declare a kind before a kind whose output it reads: a study's
    meshing sequence runs its batches in the kinds' order, so one would run before the batch it
    takes from (workflow.md § 7: "each kind taking only from kinds before it, which the catalogue
    checks when it loads")."""
    from femkit.definitions.stages import Stages
    data = _shipped_toml("stages.toml")
    view = {**data["kinds"]["geometry"], "batch": "views", "inputs": {"shapes": "geometry/xao"}}
    data["kinds"] = {"view": view, **data["kinds"]}
    with pytest.raises(DefinitionError) as caught:
        validate(Stages, data, "stages.toml", _context())
    assert [path for path, _ in caught.value.problems] == ["kinds.view.inputs.shapes"], caught.value.problems


def test_the_mesh_kind_declared_before_the_geometry_its_meshers_read_does_not_load(definitions):
    """Fails if `stages.toml` may declare the kind a mesher fills before the kind whose outputs its
    meshers read — the meshes' batch would run before the geometries' — or the catalogue says so
    elsewhere than at that kind in `stages.toml` (workflow.md § 7: "each kind taking only from kinds
    before it, which the catalogue checks when it loads")."""
    stages = definitions / "stages.toml"
    text = stages.read_text()
    geometry, mesh = text.index("# The component's script builds"), text.index("# A mesher meshes")
    stages.write_text(text[:geometry] + text[mesh:].rstrip("\n") + "\n\n" + text[geometry:mesh])
    assert _refused_in(definitions, catalogue.load_meshers) == {"stages.toml": ["kinds.mesh"]}


@pytest.mark.parametrize("change, at", [
    ({"mesh": {"file": "mesh.msh", "format": "f"}}, "mesh"),                          # a type with no form
    ({"mesh/msh-2.2": {"file": "meshes/mesh.msh", "format": "f"}}, '"mesh/msh-2.2".file'),   # a file in a folder
    ({"mesh/msh-2.2": {"file": "mesh.msh", "format": "f", "opened": {"environment": "nosuch",
                                                                     "command": ["c", "{file}"]}}},
     '"mesh/msh-2.2".opened.environment'),
    ({"mesh/msh-2.2": {"file": "mesh.msh", "format": "f", "opened": {"environment": "gmsh",
                                                                     "command": ["gmsh", "{path}"]}}},
     '"mesh/msh-2.2".opened.command'),
])
def test_an_artifact_type_that_misstates_itself_does_not_load(change, at):
    """Fails if an artifact type is named otherwise than `<what>/<form>`, its file is not one name
    in its stage's run, or it is opened in an environment that does not exist or by a command
    naming another placeholder than its file (workflow.md § 2.2)."""
    from femkit.definitions.stages import ArtifactList
    data = _shipped_toml("artifacts.toml") | change
    with pytest.raises(DefinitionError) as caught:
        validate(ArtifactList, data, "artifacts.toml", _context())
    assert at in [path for path, _ in caught.value.problems], caught.value.problems


def _refused_in(definitions: Path, load) -> dict[str, list[str]]:
    """The catalogue's refusal of what ``load`` loads: each file, by its path from the definitions,
    with the key paths at fault."""
    with pytest.raises(CatalogueError) as caught:
        load()
    return {Path(e.file).relative_to(definitions).as_posix(): [where for where, _ in e.problems]
            for e in caught.value.errors}


def test_two_engine_definitions_declaring_one_engine_are_refused_each_in_its_file(definitions):
    """Fails if two environments' definitions, each in its own file, may both declare one engine — a
    study's `engine` would not name one environment, the catalogue resolving an engine to its
    definition's alone — or the refusal names but one of them, or not at its `engine`
    (definitions.md § 2.2; framework.md § 5)."""
    (definitions / "environments" / "again.toml").write_text(_shipped("ngsolve"))
    assert _refused_in(definitions, load_environments) == {"environments/again.toml": ["engine"],
                                                          "environments/ngsolve.toml": ["engine"]}


def test_two_environments_taking_the_projects_packages_are_refused_each_in_its_file(definitions):
    """Fails if two tool environments' definitions may both take the packages projects declare —
    a project's scripts run in one environment, where its packages are installed and against whose
    modules `observe.py` is checked — or the refusal names but one, or not at its `projects`
    (definitions.md §§ 2.2, 4.7; models.md § 5.2)."""
    (definitions / "environments" / "again.toml").write_text(_shipped("postprocess"))
    assert _refused_in(definitions, load_environments) == {"environments/again.toml": ["projects"],
                                                          "environments/postprocess.toml": ["projects"]}


def test_a_studys_engine_resolves_to_its_definitions_environment_or_its_cuda_twin_where_gpus_are_asked():
    """Fails if an engine is not resolved to the environment whose definition declares it, its
    `-cuda` twin where the study's solve asks GPUs, or a name no definition declares — a tool's — to
    one (framework.md § 5; models.md § 5.1)."""
    c = kit_ctx()
    engines = catalogue.engines(c)
    assert [catalogue.with_gpus(c, engines[e], g) for e, g in (("elmer", 0), ("ngsolve", 0), ("ngsolve", 1))] == [
        "elmer", "ngsolve", "ngsolve-cuda"]
    assert "gmsh" not in engines and set(engines) == {"elmer", "ngsolve"}


def test_two_hand_overs_for_one_engine_type_and_order_are_refused_across_files(definitions):
    """Fails if two hand-overs, each in its own file, may both give one engine the same mesh type
    at one geometry order — the order a case asks for would not choose one — or the refusal names
    but one of them (definitions.md § 2.2; geometry.md § 8)."""
    elmergrid = (definitions / "handovers" / "elmergrid.toml").read_text()
    (definitions / "handovers" / "again.toml").write_text(elmergrid.replace("orders = [1, 2]", "orders = [2]"))
    assert _refused_in(definitions, catalogue.load_handovers) == {
        "handovers/again.toml": ["orders"], "handovers/elmergrid.toml": ["orders"]}


GIVEN_ARGUMENTS = 'arguments = ["{given}", "{groups}", "{mesh}", "{regions}"]'
GIVEN_WRITES = 'writes = { mesh = "mesh/msh-2.2", regions = "mesh/regions" }'


@pytest.mark.parametrize("changes, at", [
    ([(GIVEN_ARGUMENTS, GIVEN_ARGUMENTS.replace("regions", "map")),
      (GIVEN_WRITES, GIVEN_WRITES.replace("regions =", "map ="))], "writes"),
    ([(GIVEN_ARGUMENTS, GIVEN_ARGUMENTS.replace('"]', '", "{contract}"]'))], "arguments"),
], ids=["a file the mesh check reads, written by no name it knows", "a document its stage is not handed"])
def test_a_mesher_is_held_to_the_stage_kind_it_fills(definitions, changes, at):
    """Fails if a mesher may write no file the mesh stage's check names — the region map it reads,
    the mesh it records — or hand its program a document its stage is not handed (workflow.md
    §§ 2.1, 2.3)."""
    for old, new in changes:
        kit.rewrite(definitions / "meshers" / "given.toml", old, new)
    assert _refused_in(definitions, catalogue.load_meshers) == {"meshers/given.toml": [at]}


def test_an_engine_may_have_a_hand_over_per_geometry_order():
    """Fails if a second hand-over for an engine, at an order no other of its hand-overs reads its
    type at — Netgen's for NGSolve beside femkit's layer (ADR 0017) — is refused, or the order
    asked does not choose it (geometry.md § 8)."""
    from femkit.definitions.meshers import HandOver, handover
    handovers = dict(catalogue.handovers(kit_ctx()))
    handovers["netgen"] = validate(HandOver, _shipped_toml("handovers/layer.toml") | {"orders": [2]}, "n.toml")
    msh = ["mesh/msh-2.2"]
    assert [handover(handovers, "ngsolve", order, msh) for order in (1, 2)] == ["layer", "netgen"]
    assert handover(handovers, "elmer", 2, msh) == "elmergrid" and handover(handovers, "nosuch", 1, msh) is None
    assert handover(handovers, "elmer", 1, ["mesh/netgen-vol"]) is None     # keyed by the type it reads too


@pytest.mark.parametrize("change, at", [
    ({"exercises": ["potential", "tunneling"]}, "benchmarks.two_material.exercises[1]"),   # no such kind
    ({"project": "nowhere"}, "benchmarks.two_material.project"),                          # no such template
    ({"reference": {"potential_low": {"value": 2, "unit": "VV"}}},
     "benchmarks.two_material.reference.potential_low.unit"),
    ({"reference": {"potential_low": "2/5 V"}}, "benchmarks.two_material.reference.potential_low"),
])
def test_a_benchmark_that_misstates_itself_does_not_load(change, at):
    """Fails if a benchmark exercises a kind its formulation lacks, names a project that does not
    exist, or a reference value whose unit the unit grammar does not read, or written as a text
    (models.md § 4; core.md § 11)."""
    from femkit.core.schema import validate
    from femkit.core.units import Units
    from femkit.definitions.catalogue import load_places, load_templates, load_units
    from femkit.definitions.formulations import FormulationDefinition
    data = tomllib.loads((data_root() / "formulations" / "electrostatics.toml").read_text(), parse_float=exact_number)
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
    mesher.write_text(shipped.replace('provided_by = "gmsh"', 'provided_by = "elmer-cuda"', 1))
    assert load_meshers()["gmsh"].provided_by == "elmer-cuda"
    (definitions / "environments" / "web.toml").write_text("this is [ no TOML\n")
    mesher.write_text(shipped.replace('provided_by = "gmsh"', 'provided_by = "nowhere"', 1))
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
    ({"equivalents": ["conductivity"]}, "relative_permittivity.equivalents[0]"),
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
    ("states/stage.toml", 'pending = ["restate", "place"]', 'pending = ["restate", "place"]\nmended = ["place"]',
     "does.mended"),
    ("states/stage.toml", 'pending = ["restate", "place"]\n', "", "does"),
    ("states/stage.toml", 'prepared = ["restate", "place"]', 'prepared = ["launch"]', "does.prepared"),
    ("states/stage.toml", 'when = "not held_back"', 'when = "not behind"', "tasks.place.when"),
], ids=["an action naming no registered operation", "a machine that could fall through",
        "a layout putting two kinds in one folder", "what prep does in a state no table of the chain has",
        "what prep does in one of its folder's states unnamed",
        "prep doing its folder's action in a state, not its own task", "a task's guard naming no fact of a stage's"])
def test_schema_check_refuses_a_state_table_or_a_layout_breaking_its_rules(definitions, file, old, new, at):
    """Fails if `schema check` passes a machine's table naming an operation that is not registered
    or breaking its own rules — what `study prep` does in a stage's states keyed by a state no
    table of its chain has, leaving one of its folder's table's states unnamed, or doing an action of the
    folder's table rather than one of the stage table's own tasks, or a task's guard naming no fact
    a stage's code gives, among them — or a layout breaking its own, each reported in its file at its
    key path (core.md § 7: "`[does]` … each state of the tables down the `past` chain — every one
    named … each key and task checked at load"; workflow.md § 6; projects.md § 4; definitions.md
    § 2.3)."""
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


def test_femkits_own_data_writes_each_quantity_in_the_one_form_read_exactly():
    """Fails if a quantity in femkit's own definitions — a dispersion list's constant, a
    formulation's constant or a benchmark's reference value — is written as a text, or reaches its
    model through a binary float, or a benchmark's tolerance, a plain number, is not one (core.md
    § 11: "One quantity form, everywhere a quantity is written — … and femkit's own data"; "Exact":
    "a TOML number by the text the person wrote")."""
    from fractions import Fraction

    def held(measure) -> tuple:
        return measure.value, measure.unit

    c = kit_ctx()
    constants = catalogue.dispersion(c).constants
    assert held(constants["planck"].value) == (Fraction(662607015, 10 ** 42), "J s")
    assert held(constants["speed_of_light"].value) == (299792458, "m/s")
    f = catalogue.formulations(c)["electrostatics"]
    assert held(f.constants["vacuum_permittivity"].value) == (Fraction(88541878188, 10 ** 22), "F/m")
    bench = f.benchmarks["two_material"]
    assert bench.tolerance == Fraction(1, 10 ** 9) and not isinstance(bench.tolerance, float)
    assert held(bench.reference["potential_low"]) == (Fraction(2, 5), "V")


def test_a_clean_start_that_removes_what_no_pattern_passes_is_refused_when_it_loads(definitions):
    """Fails if process.toml loads with a `removes` entry no pattern of its `passes` takes — a variable
    no pattern passes is never kept, so the entry removes nothing and reads as a protection it is not
    (envs.md § 4.4; definitions.md § 2.2)."""
    from femkit.definitions.models import ProcessStart
    kit.rewrite(definitions / "process.toml", 'removes = [', 'removes = ["LD_PRELOAD", ')
    with pytest.raises(DefinitionError) as caught:
        load_toml(definitions / "process.toml", ProcessStart)
    assert any("LD_PRELOAD" in reason for _, reason in caught.value.problems), caught.value.problems
