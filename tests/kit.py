"""What tests share, written once (testing.md § 3): a context for one command, an operation called
through the registry as a surface calls it, a refusal told apart by its code, a lock held by
another process, an environment left as an install leaves it, a machine record, part schemas and
checks of a test's own, a project opened as femkit's start leaves the door, a projects root
stated, a copy of a project template — the Laplace and the two-material one as fixtures — every
command of the command line with its options, a folder's files, a file of a test's own changed,
a condition waited for, the tripwires the basic and web tiers stand behind, and for the engine
tier a program run inside an environment as a check runs there, copied in as a run holds it, its
reason read, a template's geometry built by its own script, and Gmsh's meshing and the mesh's check
run on it. Each test
file takes these from here, never from another test file; a tier's conftest.py takes the tripwire
fixtures it applies."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from pydantic import ConfigDict

from femkit import registry
from femkit.config.probe import GPU_QUERY, place
from femkit.core.errors import Refusal
from femkit.core.operations import Context
from femkit.core.persist import read_json, write_json
from femkit.core.schema import Model
from femkit.definitions.catalogue import load_environments, load_managers, load_schedulers
from femkit.envs import layout
from femkit.envs.records import CheckOutcome, ChecksRecord, Manifest
from femkit.envs.state import EnvFacts, facts
from femkit.jobs.record import SCHEMA as RECORD_SCHEMA, Record
from femkit.projects import checking, door
from femkit.projects import schemas as part_schemas
from femkit.projects.project import Project


def ctx() -> Context:
    """One command's context, read from the process as the command line reads it — inside a test
    only, where the tier's isolation has set femkit's directories (testing.md § 2.1). Outside one,
    in a script of one's own, they would be the person's: the kit refuses before anything runs."""
    if "PYTEST_CURRENT_TEST" not in os.environ:
        raise RuntimeError("the test kit acts only inside a test: outside one, femkit's directories are the "
                           "person's own configuration, environments and logs (testing.md § 2.1)")
    return Context.from_process()


def files():
    """The jobs catalogue of a folder's files, as one command reads it (jobs.md § 1.1)."""
    from femkit.jobs import layout
    return layout.read_once(ctx())


def run(name: str, /, **request):
    """A read-only operation, its request given as JSON values, run as a surface runs it."""
    op = registry.operations()[name]
    return op.run(op.request_from(request), ctx())


def apply(name: str, /, **request):
    """A changing operation planned and applied in one context, as `--yes` applies it."""
    op = registry.operations()[name]
    c = ctx()
    return op.apply(op.plan(op.request_from(request), c), c)


def planned(name: str, /, **request):
    """A changing operation, its plan, and the one context the plan was made in — held, as the
    command line holds them while the person reads the plan; ``op.apply(plan, c)`` applies it."""
    op = registry.operations()[name]
    c = ctx()
    return op, op.plan(op.request_from(request), c), c


HOLDER = """
import sys
from femkit.core import locks, view
with locks.subject_lock(sys.argv[1], shared=sys.argv[2] == "shared"):
    locks.adopt(locks.held_fd(sys.argv[1]), "a user of " + sys.argv[1], [view.shell("end it").model_dump(mode="json")])
    print("held", flush=True)
    sys.stdin.read()
"""


@contextmanager
def refused(kind: type[Refusal], code: str, subject: str | None = None):
    """The block refused with ``kind`` and ``code`` — and, given one, about ``subject``: a refusal
    told apart by its code, never its wording (core.md § 9)."""
    with pytest.raises(kind) as caught:
        yield caught
    assert caught.value.code == code, (caught.value.code, str(caught.value))
    assert subject is None or caught.value.subject == subject, (caught.value.subject, str(caught.value))


def hold(subject: str, mode: str) -> subprocess.Popen:
    """Another process holding ``subject``'s lock, ``mode`` shared or alone, until its stdin closes."""
    p = subprocess.Popen([sys.executable, "-c", HOLDER, subject, mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True)
    assert p.stdout.readline().strip() == "held"
    return p


def wait_until(check, timeout: float = 15.0) -> bool:
    """Whether ``check()`` came true within ``timeout`` seconds: what another process does — a
    server answering, a process ending — is seen when it happens, not at a fixed moment."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.1)
    return False


def manager_root() -> Path:
    """The stand-in manager's root, in the test's own folder: where it keeps its environments, each
    `<root>/envs/<its name>` with `conda-meta/`, and lists them (envs.md § 1)."""
    return Path(os.environ["FEMKIT_DATA_DIR"]).parent / "manager"


def made(name: str) -> Path:
    """The environment ``name`` made where the stand-in manager keeps its environments, by its name
    with the manager — `femkit`, `femkit-<name>` — as its create makes one: what it lists from then on."""
    from femkit.definitions.catalogue import managed
    prefix = manager_root() / "envs" / managed(ctx(), name)
    (prefix / "conda-meta").mkdir(parents=True, exist_ok=True)
    return prefix


def listed(prefix: Path) -> Path:
    """``prefix`` listed by the stand-in manager whatever is there, as a manager's own list of its
    environments may name a folder that is gone, or one that is no environment."""
    manager_root().mkdir(parents=True, exist_ok=True)
    with open(manager_root() / "listed", "a") as f:
        f.write(f"{prefix}\n")
    prefix.mkdir(parents=True, exist_ok=True)
    return prefix


def installed(name: str, *, fingerprint: str | None = None, outcomes: list[CheckOutcome] | None = None,
              stale_checks: bool = False) -> EnvFacts:
    """The environment ``name`` left as an install leaves it — and, given ``outcomes``, as a
    validate then leaves it — where the stand-in manager keeps its environments (envs.md § 4.3)."""
    made(name)
    f = facts(ctx(), name)
    write_json(layout.manifest_file(f.prefix), Manifest(
        install_fingerprint=fingerprint or f.install_fingerprint, lock_sha256="0" * 64, manager_kind="conda",
        manager_version="0", solver_version="0", time="t").model_dump())
    if outcomes is not None:
        write_json(layout.checks_file(f.prefix), ChecksRecord(
            check_fingerprint="stale" if stale_checks else f.check_fingerprint, outcomes=outcomes, time="t").model_dump())
    return f


def a_record(**changes) -> Record:
    """A cluster's record with every kind of value: numbers, `unlimited`, unknowns, walls."""
    data = {
        "schema": RECORD_SCHEMA,
        "measured": {"time": "2026-01-01T00:00:00Z", "where": "login node"},
        "identity": "cluster-a",
        "host": {"os": "Linux 5", "architecture": "x86_64", "cores": 8, "memory_mib": 16000,
                 "gpus": {"unknown": "nvidia-smi not found on PATH"}},
        "manager": {"kind": "conda", "path": "/opt/conda/bin/conda", "version": "25.1", "root": "/opt/conda",
                    "platform": "linux-64", "run_enters": False},
        "scheduler": {"kind": "slurm", "commands": {"submit": "/usr/bin/sbatch", "query": {"unknown": "squeue not found"}},
                      "probe": {"control": "/usr/bin/scontrol"}},
        "partitions": {"p1": {"max_time": "7-00:00:00", "max_cpus_per_node": "unlimited", "def_mem_per_cpu_mib": 2048,
                              "allow_qos": "all", "deny_qos": [],
                              "node_groups": [{"count": 3, "cores": 48, "memory_mib": 515000, "gpus": {"t1": 4},
                                               "architecture": "x86_64"}]}},
        "queues": [{"partition": "p1", "qos": "q1", "max_time": "1-00:00:00", "max_cpus": 128,
                    "max_memory_mib": "unlimited", "max_gpus": {"unknown": "capped per GPU type: gres/gpu:t1=2"},
                    "max_submit_jobs_per_user": "unlimited"}],
        "environments": {"ngsolve": {"state": "ready", "gpu": "not-run", "install_fingerprint": "abc"}},
        "settings": {"activation": {"preamble": ["module load x"]}},
        "sources": {"partitions": "scontrol show partition, scontrol show node"},
        "notes": [],
    }
    data.update(changes)
    return Record.model_validate(data)


class StandIn(Model):
    """A part schema of a test's own, for a kind no package of femkit's declares: it takes any key,
    as written."""

    model_config = ConfigDict(extra="allow", frozen=True)


@contextmanager
def own_parts(schemas: dict[str, type[Model]] | None = None, checks: dict[str, checking.Check] | None = None):
    """Part schemas and checks of a test's own, each by its key, registered with the door and the
    check frame as the registry registers a package's at femkit's start (api.md § 6) — a check
    beside those registered for its key — and taken back after, those held before kept."""
    held = part_schemas.registered(), checking.registered()
    for key, model in (schemas or {}).items():
        part_schemas.register(key, model)
    for key, check in (checks or {}).items():
        checking.register(key, check)
    try:
        yield
    finally:
        for key in schemas or {}:
            part_schemas.unregister(key)
            if key in held[0]:
                part_schemas.register(key, held[0][key])
        for key in checks or {}:
            checking.unregister(key)
            for check in held[1].get(key, ()):
                checking.register(key, check)


def opened(folder: Path) -> door.Opened:
    """The project at ``folder`` — a template in place, or a test's own — opened through the one
    door as an operation opens it after femkit's start: every part schema and check registered
    (api.md § 6)."""
    registry.operations()
    return door.open_project(Project(folder.parent, folder.name), ctx())


def set_root(folder: Path) -> None:
    """``folder`` stated as the projects root, `paths.projects`, as `config set` states it (projects.md § 1)."""
    apply("config.set", key="paths.projects", value=f'"{folder}"')


def copy_template(root: Path, template: str, name: str | None = None) -> Path:
    """A copy of one of femkit's project templates, made by `project new` under ``root``, the
    projects root this states: what a test that needs a project starts from (projects.md § 7)."""
    set_root(root)
    apply("project.new", name=name or template, source=template)
    return root / (name or template)


@pytest.fixture
def laplace(tmp_path) -> Path:
    """A copy of the Laplace template, `laplace_square`, under a projects root of the test's own."""
    return copy_template(tmp_path / "projects", "laplace_square")


@pytest.fixture
def slab(tmp_path) -> Path:
    """A copy of the two-material template, as the project `slab`, under a projects root of the test's own."""
    return copy_template(tmp_path / "projects", "two_material", "slab")


# ------------------------------------------------------------------ a machine of stand-ins (testing.md § 2.1)
#
# A run script runs for real behind the tripwires: the environment it enters is a stand-in one where
# the stand-in manager keeps its environments, in the test's own folder, entered by its name by a
# stand-in activation hook the record's manager prints as its own — a `conda` shell function — never
# the person's manager; femkit's control environment, `femkit`, which a sequence's walk enters, is a
# stand-in one too, whose `femkit` command runs this checkout on the test's own python.

CHECKOUT = Path(__file__).resolve().parents[1]

# The stand-in activation hook: `conda activate NAME` enters the environment of that name where the
# stand-in manager keeps its environments — none there, it fails, as conda's does — and puts its bin
# first, then the tripwires, so a command that reaches an outside program still fails the test. While
# the calculation folder holds `hold`, it waits, its run script's process ID beside it in `held.pid`:
# a run held there has started and does not end. With SITE_FIRST set — by the preamble, the one thing
# that runs between the clean start and the activation — the folder it names stays first on PATH, as a
# site's `python` can stay first after an activation (jobs.md § 2).
STAND_IN_HOOK = """conda() {
  [ "$1" = activate ] && [ -d "@ENVS@/$2" ] || return 1
  [ ! -e ../hold ] || echo "$$" > ../held.pid
  n=0
  while [ -e ../hold ] && [ "$n" -lt 1200 ]; do sleep 0.05; n=$((n + 1)); done
  export CONDA_PREFIX="@ENVS@/$2"
  PATH="${SITE_FIRST:+$SITE_FIRST:}$CONDA_PREFIX/bin:@TRIPWIRES@:$PATH"
  export PATH
}
"""
# The stand-in `femkit` command of the control environment: this checkout on the test's python, as
# the launcher the install script writes runs it (envs.md § 7).
STAND_IN_FEMKIT = f'#!/bin/sh\nexec {sys.executable} -I {CHECKOUT}/femkit/__main__.py "$@"\n'


def stand_in_machine(tmp_path: Path, tripwire_dir: Path, environments: dict[str, dict[str, str]]) -> Path:
    """This machine as config.toml states it — activation by `conda activate` — the stand-in manager
    printing the stand-in hook as its own (`HOOK`), each environment of ``environments`` a stand-in
    one where the stand-in manager keeps its environments (`made`), its `bin` holding the test's
    python and the programs given, name: text, and a stand-in control environment, `femkit`, beside
    them. Returns the manager's root."""
    root = manager_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "hook.sh").write_text(STAND_IN_HOOK.replace("@TRIPWIRES@", str(tripwire_dir))
                                  .replace("@ENVS@", str(manager_root() / "envs")))
    from femkit.core.dirs import CONTROL
    for env, programs in {**environments, CONTROL: {"femkit": STAND_IN_FEMKIT}}.items():
        bin_ = made(env) / "bin"
        bin_.mkdir(parents=True)
        (bin_ / "python").symlink_to(sys.executable)
        for name, text in programs.items():
            (bin_ / name).write_text(text)
            (bin_ / name).chmod(0o755)
    apply("config.init", no_preamble=True, command="conda activate", mpi=["mpirun", "-np", "{ranks}"],
          cuda_architectures=["80"])
    return root


def commands() -> dict[tuple[str, ...], frozenset[str]]:
    """Every command femkit's command line has, as the words a person types after `femkit` —
    `("project", "new")`, `("doctor",)` — each with the options it takes, `--help` among them
    (api.md § 4.1)."""
    import click
    from femkit.cli import build
    out: dict[tuple[str, ...], frozenset[str]] = {}

    def walk(command: click.Command, path: tuple[str, ...]) -> None:
        if isinstance(command, click.Group):
            for name, sub in command.commands.items():
                walk(sub, (*path, name))
        else:
            out[path] = frozenset(o for p in command.params for o in (*p.opts, *p.secondary_opts)
                                  if o.startswith("-")) | {"--help"}

    walk(build(), ())
    return out


def tree(folder: Path) -> dict[str, bytes]:
    """Every file of a folder, by its path from it, with its bytes."""
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def rewrite(path: Path, old: str, new: str) -> None:
    """A file of a test's own — of its project, or its copy of the definitions — changed as its
    person would change it: ``old`` there, once, made ``new``."""
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} is in {path} {text.count(old)} times"
    path.write_text(text.replace(old, new), encoding="utf-8")


# ------------------------------------------------------------------ the tripwires (testing.md § 2.1)
#
# PATH starts with a directory holding a tripwire for every outside program femkit can start; a
# test that reaches one fails, naming the call.

# Programs the tests' own process needs; never tripwired.
NEEDED_BY_THE_TEST_PROCESS = frozenset({"python", "bash", "git"})
# Named by testing.md § 2.1 or started by code, but listed in no definition file:
# the GPU query, and CTest (the `ctest` check kind, definitions.md § 5.1).
NAMED_IN_CODE = frozenset({GPU_QUERY[0], "ctest"})


def tripwire_names() -> frozenset[str]:
    names = set(load_managers()) | NAMED_IN_CODE
    for kind in load_schedulers().values():
        names |= set(kind.commands.values()) | set(kind.probe.values()) | {kind.mpi_launch[0]}
    for env in load_environments().values():
        names |= set(env.provides.executables) | set(env.toolchain.mpi.values() if env.toolchain else ())
    return frozenset(names - NEEDED_BY_THE_TEST_PROCESS)


#: The machine the basic and web tiers stand on (testing.md § 2.1): the tripwires put every scheduler
#: kind's commands on PATH and clear its job variables, so femkit finds SLURM's submit command and no
#: job. A test that needs another place says so in its own environment, for its own run.
MACHINE = "login node"

REACHED = "reached.log"  # in the tripwire directory: every call a tripwire took during the current test


def tripwire_text(log: Path) -> str:
    """A tripwire's text. The log's path is written into it, not passed in a variable: a command
    run in an environment starts clean (envs.md § 4.4)."""
    return f'#!/bin/sh\necho "$0 $*" >> {shlex.quote(str(log))}\nexit 97\n'


@pytest.fixture(scope="session")
def tripwire_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("tripwires")
    for name in tripwire_names():
        script = d / name
        script.write_text(tripwire_text(d / REACHED))
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return d


#: An `nvidia-smi` that finds no GPU, as on a machine without one: it says so and exits 6, as the
#: driver's own does there.
NO_GPU = "#!/bin/sh\necho 'No devices were found' >&2\nexit 6\n"


def ahead(folder: Path, monkeypatch, programs: dict[str, str], path: str | None = None) -> Path:
    """``programs`` — name: text — written into ``folder`` and put first on PATH, before ``path``
    (by default the PATH the test has, its tripwires first): the machine a test stands on, stated
    in its own environment."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in programs.items():
        (folder / name).write_text(text)
        (folder / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH'] if path is None else path}")
    return folder


@pytest.fixture
def workstation(definitions, tmp_path, monkeypatch):
    """This test's machine, stated in its own environment (testing.md § 2.1): no scheduler — its
    own definitions hold no SLURM kind — and no GPU, an `nvidia-smi` ahead of the tripwires
    finding none, as on a workstation without one."""
    (definitions / "schedulers" / "slurm.toml").unlink()
    ahead(tmp_path / "workstation", monkeypatch, {GPU_QUERY[0]: NO_GPU})


def calls_env(log: Path) -> list[dict[str, str]]:
    """Every variable each call of the stand-in was handed, in order: what a manager command, or a
    command it runs in an environment, starts with."""
    held = Path(f"{log}.env").read_text() if Path(f"{log}.env").exists() else ""
    return [dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            for block in held.split("----\n")[1:]]


#: What the shell femkit is typed in holds besides the person's own: another environment active,
#: outside Python, library injection and an outside toolchain; a platform forced on the manager and
#: its virtual packages overridden; a shell function no scheduler kind declares (envs.md § 4.4).
POLLUTED = {"PYTHONPATH": "/outside/python", "PYTHONHOME": "/outside", "LD_LIBRARY_PATH": "/outside/lib",
            "LD_PRELOAD": "/outside/lib/inject.so", "CONDA_PREFIX": "/outside/env", "CONDA_SHLVL": "2",
            "CONDA_DEFAULT_ENV": "outside", "VIRTUAL_ENV": "/outside/venv", "CC": "/outside/bin/gcc",
            "CFLAGS": "-O0 -outside", "CMAKE_PREFIX_PATH": "/outside", "BOOST_ROOT": "/outside/boost",
            "CONDA_SUBDIR": "osx-arm64", "CONDA_OVERRIDE_CUDA": "11.8", "BASH_FUNC_outside%%": "() {  :\n}",
            "SITE_SETTING": "from the shell"}
#: The person's own, which every process femkit starts for an environment keeps (envs.md § 4.4) — the
#: module system's `module` among them, which a scheduler kind declares.
PERSONS = {"HOME": "/home/someone", "LANG": "C.UTF-8", "TZ": "Europe/Vienna", "CONDARC": "/home/someone/.condarc",
           "CONDA_PKGS_DIRS": "/home/someone/pkgs", "HTTPS_PROXY": "http://proxy:3128",
           "BASH_FUNC_module%%": "() {  :\n}"}


def polluted(monkeypatch) -> None:
    """The shell femkit is typed in: the person's own settings, and what must never leak (envs.md § 4.4)."""
    for k, v in {**POLLUTED, **PERSONS}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PATH", f"/outside/env/bin{os.pathsep}{os.environ['PATH']}")


def leaked(env: dict[str, str]) -> list[str]:
    """Each variable of the outside that reached ``env`` as the shell held it — a function, by its
    name alone, as a shell writes its body again — and the outside's folder on its `PATH`."""
    found = sorted(k for k, v in POLLUTED.items() if k in env and (env[k] == v or k.startswith("BASH_FUNC_")))
    return found + (["PATH"] if "/outside/env/bin" in env.get("PATH", "") else [])


def kept(env: dict[str, str], shell: bool = True) -> bool:
    """Whether ``env`` holds every one of the person's own as the shell held it — a function by its
    name alone, as a shell writes its body again; without ``shell``, every one but the functions,
    for what a job of a scheduler kind that declares none starts with (envs.md § 4.4)."""
    return all(k in env and (env[k] == v or k.startswith("BASH_FUNC_")) for k, v in PERSONS.items()
               if shell or not k.startswith("BASH_FUNC_"))


#: How a stand-in manager answers what it is asked of its environments (envs.md § 1), as conda 26
#: does: `env list --json`, each folder under its root's `envs/` that holds `conda-meta/` — and under
#: its root's `elsewhere/`, an environment made by its path in no folder where it keeps environments —
#: and each prefix its root's file `listed` names, whatever is there (`listed`), by its prefix, under
#: `envs`, with its own name for each under `envs_details`, the folder's name in `envs/` and none
#: elsewhere; with a file `no-names` in its root, without `envs_details`, as a manager that says no
#: name. `info --json`, the folders where it keeps environments, `envs_dirs`:
#: its root's `envs/`. `config --show-sources --json`, each setting of the person's it read: those of
#: its root's `condarc.json`, under that file's name, as the file holds them (envs.md § 4.4).
LISTS = r"""all=''
    for d in @ROOT@/envs/*/ @ROOT@/elsewhere/*/; do [ -d "$d/conda-meta" ] && all="$all ${d%/}"; done
    [ -f @ROOT@/listed ] && all="$all $(cat @ROOT@/listed)"
    printf '{"envs": ['; sep=''
    for d in $all; do printf '%s"%s"' "$sep" "$d"; sep=', '; done
    if [ ! -e @ROOT@/no-names ]; then
      printf '], "envs_details": {'; sep=''
      for d in $all; do
        name=''; case "$d" in @ROOT@/envs/*) name=${d##*/} ;; esac
        printf '%s"%s": {"base": false, "name": "%s"}' "$sep" "$d" "$name"; sep=', '; done
      printf '}}
'
    else
      printf ']}
'
    fi"""
FOLDERS = r"""printf '{"envs_dirs": ["%s"]}
' @ROOT@/envs"""
#: How a stand-in manager prints its shell hook for bash, `shell.bash hook` (definitions.md § 6): the
#: stand-in hook a machine of stand-ins holds in its root (`stand_in_machine`), none elsewhere.
HOOK = r"""cat @ROOT@/hook.sh"""
SETTINGS = r"""if [ -f @ROOT@/condarc.json ]; then printf '{"%s": ' @ROOT@/condarc.json; cat @ROOT@/condarc.json; printf '}
'; else printf '{}
'; fi"""


def answering(script: str) -> str:
    """A stand-in manager's text with its answers in place: what it lists, where it keeps
    environments, which settings it read — each of its root (`manager_root`)."""
    root = shlex.quote(str(manager_root()))
    return script.replace("@LISTS@", LISTS).replace("@FOLDERS@", FOLDERS).replace("@SETTINGS@", SETTINGS) \
        .replace("@HOOK@", HOOK).replace("@ROOT@", root)


# The manager every test of the tier stands on: it answers what it is asked of its environments —
# looking at an environment asks it where one is (envs.md § 3.1) — and is a tripwire for anything
# else; a test that installs or removes one takes the stand-in that does (tests/basic/conftest.py).
LISTER = """#!/bin/bash
case "$*" in
  "env list --json") @LISTS@ ;;
  "info --json") @FOLDERS@ ;;
  "config --show-sources --json") @SETTINGS@ ;;
  "shell.bash hook") @HOOK@ ;;
  *) echo "$0 $*" >> @REACHED@; exit 97 ;;
esac
"""


@pytest.fixture(autouse=True)
def tripwires(tripwire_dir, tmp_path, monkeypatch, isolated_dirs):
    log = tripwire_dir / REACHED
    log.unlink(missing_ok=True)
    for kind in load_schedulers().values():  # run inside an allocation, a test still sees none of its job
        for variable in kind.job_variables.values():
            monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("PATH", f"{tripwire_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    lister = tmp_path / "lister" / sorted(load_managers())[0]
    lister.parent.mkdir()
    lister.write_text(answering(LISTER).replace("@REACHED@", shlex.quote(str(log))))
    lister.chmod(0o755)
    monkeypatch.setenv("FEMKIT_ENV_MANAGER", str(lister))
    stood_on = place(load_schedulers(), os.environ).where
    assert stood_on == MACHINE, f"the tests stand on a {stood_on}, not the stated {MACHINE} (testing.md § 2.1)"
    yield log
    if log.exists() and log.read_text().strip():
        pytest.fail("a test reached an outside program: " + log.read_text().strip())


# ------------------------------------------------------------------ the engine tier (testing.md § 1)
#
# femkit's programs run inside the person's own environments — `femkit-<name>`, where the person's
# manager keeps them — as femkit runs a check there: through the manager's own `run`, by the name,
# from the clean start, `HOME` a folder of the test's own (envs.md § 4.4). Nothing is written into a
# prefix.

def inside(environment: str, argv: list, work: Path, *, checkout: bool = False):
    """``argv`` run in the folder ``work`` inside ``environment``, through the one door into it, as a
    one-thread check runs there (definitions.md § 4.4; envs.md § 4.4); with ``checkout``, femkit's
    checkout on `PYTHONPATH`, as a check program has it. Its output goes to `<work>/<the program's
    name>.log`, and the result's `stdout` holds its last lines."""
    from femkit.envs import checks
    r = checks.runner(ctx(), environment)
    declared = {**{v: "1" for v in r.env.thread_variables}, **r.env.fixed_variables,
                "PYTHONDONTWRITEBYTECODE": "1"}   # the prefix is only read: Python caches nothing in it
    return r.inside.run(r.inside.argv([str(a) for a in argv]), checkout=checkout, more=declared, cwd=work,
                        timeout=600, log=work / f"{Path(str(argv[1])).stem}.log")


def program(source: Path, work: Path) -> str:
    """``source`` copied into ``work`` with the modules every femkit program has beside it, as a
    stage's run holds the program it runs (jobs.md § 1.1; framework.md § 1): its name there."""
    import shutil
    for file in (source, *files().beside().values()):
        shutil.copyfile(file, work / file.name)
    return source.name


def said(result, *fragments: str) -> bool:
    """Whether one line of a program's last lines holds every fragment: a reason is one line
    (jobs.md § 2). Through the manager's `run`, the manager prints a line of its own after a
    command that failed, so the reason need not be the very last."""
    return any(all(f in line for f in fragments) for line in result.stdout.splitlines())


def template_geometry(template: str, work: Path) -> dict:
    """The one component of the project template ``template`` built in ``work`` by its own script
    inside the `gmsh` environment, as the geometry stage runs it (geometry.md § 2) — each length it
    reads in its frame's unit, the nearest double — into `geometry.xao`. Returns its contract as
    the stage's check is given it, a `contract` document (`femkit/engines/stages/documents.py`),
    asking for no BREP."""
    from femkit.definitions import catalogue
    from femkit.engines.stages import documents
    c = ctx()
    project = opened(catalogue.templates(c)[template])
    (part,) = [p for p in project.parts.values() if p.address.kind == "component"]
    from femkit.models import definitions
    frame = part.data.frame
    checked = checking.Checking.of(project, c, definitions.defined(project, c, compute=False))
    assert set(part.data.inputs.definitions.values()) <= {"length"}, "the templates' scripts read lengths only"
    write_json(work / "inputs.json", documents.make("inputs", definitions={
        name: float(checked.units.convert(checked.definitions[name], frame.unit))
        for name in part.data.inputs.definitions}))
    (work / "geometry.py").write_bytes(project.held_by(part.address)["geometry.py"].data)
    built = inside("gmsh", ["python", "geometry.py", "inputs.json", "geometry.xao"], work)
    assert built.ok, built.stdout
    return documents.make("contract", dimension=frame.dimension, groups=dict(part.data.groups),
                          axis=frame.symmetry.axis if frame.symmetry else None,
                          mesh=part.data.outputs.mesh.order if part.data.outputs.mesh else None, brep=False)


def mesh(work: Path, contract: dict, **recipe):
    """Gmsh's meshing of `<work>/geometry.xao`, then the mesh's check (geometry.md § 5): ``recipe``
    — its values as `recipe.json` holds them, `growth` and `quality` unset and no `sizes` unless it
    gives them — for ``contract``'s frame and groups, each program run inside the `gmsh`
    environment. The meshing's result where it failed, else the check's; `mesh.msh` and
    `regions.json` in ``work`` when it meshed, and the check's `checked.json` and, when it passed,
    `outputs.json`."""
    from femkit.engines.stages import documents
    programs = files().programs_folder
    write_json(work / "recipe.json", documents.make(
        "recipe", dimension=contract["dimension"], groups=contract["groups"],
        **{"growth": None, "quality": None, "sizes": {}, **recipe}))
    meshed = inside("gmsh", ["python", program(programs() / "mesh.py", work), "recipe.json", "geometry.xao",
                             "mesh.msh", "regions.json"], work)
    if not meshed.ok:
        return meshed
    return inside("gmsh", ["python", program(programs() / "check_mesh.py", work), "recipe.json", "regions.json",
                           "checked.json", "outputs.json", "mesh.msh"], work)


def hand_over(engine: str, work: Path, order: int):
    """``engine``'s hand-over of `<work>/mesh.msh`, Gmsh's mesh (geometry.md § 8), for geometry
    ``order``: the groups of `<work>/regions.json` the hand-over hands written to `handover.json`,
    and its program run with its declared arguments inside the engine's environment, copied in as
    a run holds it. Its result, and the hand-over."""
    from femkit.core.schema import render
    from femkit.definitions import catalogue
    from femkit.engines import package_dir
    from femkit.engines.stages import documents
    from femkit.definitions.meshers import handover
    from femkit.geometry.steps import handed
    c = ctx()
    chosen = catalogue.handovers(c)[handover(catalogue.handovers(c), engine, order,
                                             catalogue.meshers(c)["gmsh"].writes.values())]
    regions = documents.check("regions", read_json(work / "regions.json"))
    groups = {name: g["dimension"] for name, g in regions["groups"].items()}
    write_json(work / "handover.json", documents.make(
        "handover", groups=handed(chosen, catalogue.places(c), regions["dimension"], groups)))
    argv = [render(a, {"mesh": "mesh.msh", "handover": "handover.json"}) for a in chosen.arguments]
    return inside(engine, ["python", program(package_dir(engine) / chosen.program, work), *argv], work), chosen
