"""The toolchain: declared by each environment, proven before any source is fetched, and every
command in a prefix confined to it (definitions.md § 4.6; envs.md § 4.1, § 4.4).

The program that runs inside an environment is exercised in the field tier
(tests/field/test_toolchain_on_this_machine.py); here, femkit's side: the plan, the confinement, the judgement.
"""

from __future__ import annotations

import shlex

import pytest

from tests.kit import apply, ctx, made, planned, refused
from femkit.core.errors import Unstated
from femkit.definitions.catalogue import load_environments
from femkit.engines.toolchain import LANGUAGES
from femkit.envs import checks, install, toolchain


def test_every_environment_with_builds_solves_its_own_toolchain():
    """Fails if an engine environment's solve lacks its toolchain's compilers, sysroot or build
    tools — they would come from wherever the solver or the host chose (definitions.md § 4.6)."""
    for name, env in load_environments().items():
        if env.builds:
            assert env.toolchain and set(env.toolchain.packages) <= set(env.packages.conda), name


def test_the_toolchain_is_proven_before_any_source_is_fetched(manager):
    """Fails if the toolchain check is missing from an install, or comes after a download
    (envs.md § 4.1)."""
    c = ctx()
    apply("config.set", key="launch.mpi", value='["mpirun", "-np", "{ranks}"]')
    ids = [s.id.split("/", 1)[1] for s in planned("env.install", names=["elmer"])[1].steps]
    assert ids.index("forbid") < ids.index("toolchain") < min(i for i, s in enumerate(ids) if s.startswith("fetch:"))


def test_an_mpi_environment_is_refused_while_launch_mpi_is_unset_and_told_how_to_set_it(manager):
    """Fails if an install of an MPI environment is planned with no launcher for its
    toolchain check's two ranks, or the command the refusal names does not make it plannable
    (envs.md § 4.1)."""
    with refused(Unstated, "setting-unset", "launch.mpi") as caught:
        planned("env.install", names=["elmer"])
    (step,) = caught.value.next
    (fill,) = step.fills
    assert step.call.operation == "config.set" and fill.field == "value" and fill.toml
    apply(step.call.operation, **step.call.request, value=fill.example)  # the step it offers, with the value it offers
    assert planned("env.install", names=["elmer"])[1].steps


LEAKS = {"CC": "/opt/site/gcc", "LD_LIBRARY_PATH": "/opt/site/lib", "HYPRE_ROOT": "/opt/site",
         "CMAKE_PREFIX_PATH": "/opt/site", "CPATH": "/opt/site/include"}  # what a module may set


INSIDE = ("toolchain", "configure", "compile", "install", "audit", "manifest")  # step kinds run in the prefix


def test_every_command_in_the_prefix_sees_none_of_the_shells_build_settings(manager_doing, monkeypatch, tmp_path):
    """Fails if a command femkit runs inside the prefix — the toolchain check, configure,
    compile, install, the audit, the version probe, a check — or the manager's own create sees a
    compiler, search path or package root the person's shell set, or loses the locale: each begins
    from the clean start (envs.md § 4.4)."""
    for name, value in {**LEAKS, "LC_ALL": "C.UTF-8"}.items():
        monkeypatch.setenv(name, value)
    handed = tmp_path / "handed"   # the variables each command was handed, as the manager received them
    handed.mkdir()
    manager_doing('  "env list") @LISTS@ ;;\n  "info --json") @FOLDERS@ ;;\n'   # where its environments are,
                  '  "config --show-sources") @SETTINGS@ ;;\n'                # as it keeps them; the settings it read
                  f'  *) env -0 > "$(mktemp -p {shlex.quote(str(handed))})"; exit 1 ;;')   # each fails at once
    apply("config.set", key="launch.mpi", value='["mpirun", "-np", "{ranks}"]')  # its toolchain check runs MPI
    made("ngsolve")                                                  # as its create left it
    t = install.target(ctx(), "ngsolve")
    env = t.env

    def seen(run) -> list[dict]:
        for earlier in handed.iterdir():
            earlier.unlink()
        run()
        return [dict(v.split("=", 1) for v in f.read_bytes().decode().split("\0") if v) for f in handed.iterdir()]

    steps = install.plan_steps(t, remove_first=False, discard_lock=True)
    confined = {s.id: seen(lambda: install.run_step(t, s, tmp_path / "logs"))
                for s in steps if s.id.split(":")[0] in INSIDE}
    work = tmp_path / "check"
    work.mkdir()
    r = checks.runner(ctx(), "ngsolve")
    confined["check"] = seen(lambda: checks.run_check(r, env.checks[0], checks.steps(r, env.checks[:1])[0].argv,
                                                      work))   # as validate runs one
    assert {i.split(":")[0] for i, envs in confined.items() if envs} == {*INSIDE, "check"}  # every kind ran something
    for step_id, envs in confined.items():
        for variables in envs:
            assert not set(LEAKS) & set(variables) and variables["LC_ALL"] == "C.UTF-8", step_id
    create = next(s for s in steps if s.id == "create")            # the manager's own command, from the same start
    assert all(not set(LEAKS) & set(v) and v["LC_ALL"] == "C.UTF-8"
               for v in seen(lambda: install.run_step(t, create, tmp_path / "logs")))


def _report(prefix) -> dict:
    """A report in the program's own format: everything inside the prefix, and working."""
    works = {"compiled": True, "ran": True, "error": ""}
    return {"tools": {"cmake": str(prefix / "bin" / "cmake")},
            "compilers": {"c": {"variable": "CC", "value": "cc", "command": str(prefix / "bin" / "cc"),
                                "version": "cc 14.4.0", **works}},
            "mpi": {"c": {"wrapper": "mpicc", "command": str(prefix / "bin" / "mpicc"), **works}},
            "launcher": str(prefix / "bin" / "mpirun")}


BROKEN = {  # what the toolchain check exists to catch
    "a build tool from the host": lambda r: r["tools"].update(cmake="/usr/bin/cmake"),
    "the host's compiler": lambda r: r["compilers"]["c"].update(command="/usr/bin/cc"),
    "a compiler that is not found": lambda r: r["compilers"]["c"].update(command=None),
    "no compiler set": lambda r: r["compilers"]["c"].update(value="", command=None),
    "a program that does not run here": lambda r: r["compilers"]["c"].update(
        ran=False, error="CPU ISA level is lower than required"),
    "a program that does not link": lambda r: r["compilers"]["c"].update(
        compiled=False, ran=False, error="cannot find -lgfortran"),
    "the host's MPI wrapper": lambda r: r["mpi"]["c"].update(command="/usr/bin/mpicc"),
    "an MPI program that does not run on two ranks": lambda r: r["mpi"]["c"].update(
        ran=False, error="orted: not found"),
}


@pytest.mark.parametrize("broken", BROKEN.values(), ids=BROKEN.keys())
def test_the_toolchain_is_not_proven_by_anything_outside_the_prefix_or_a_program_that_does_not_run(tmp_path,
                                                                                                    broken):
    """Fails if a build tool, compiler or MPI wrapper outside the prefix, or a trivial program
    that does not build or run, passes the toolchain check (envs.md § 4.1)."""
    report = _report(tmp_path)
    assert not toolchain.judge(report, tmp_path).problems
    broken(report)
    assert toolchain.judge(report, tmp_path).problems


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_program_that_cannot_start_is_a_finding_not_a_crash(tmp_path, monkeypatch, language):
    """Fails if a compiler the kernel cannot run, for any language a toolchain may name, or a
    launcher not on the confined PATH, crashes the toolchain program — losing every finding
    already made — instead of being reported as a program that does not build or run
    (envs.md § 4.1, definitions.md § 4.6)."""
    from femkit.engines import toolchain as program
    broken = tmp_path / "cc"
    broken.write_text("#!/no/such/interpreter\n")
    builds = tmp_path / "mpiwrapper"                     # an MPI wrapper that builds anything
    builds.write_text("#!/bin/sh\nexit 0\n")
    for script in (broken, builds):
        script.chmod(0o755)
    monkeypatch.setenv("CC", str(broken))
    work = tmp_path / "work"
    work.mkdir()
    report = program.check({"compilers": {language: "CC"}, "mpi": {language: str(builds)},
                            "launcher": [str(tmp_path / "no-such-launcher"), "-np", "2"], "tools": []}, work)
    assert not report["compilers"][language]["compiled"] and report["compilers"][language]["error"]
    mpi = report["mpi"][language]
    assert mpi["compiled"] and not mpi["ran"] and mpi["error"] and report["launcher"] is None

