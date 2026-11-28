"""Jobs on a machine without a scheduler (jobs.md §§ 1–6, 8): the catalogue of a folder's files,
a calculation folder written by the one writer, prepared for its own copy of a record, its run
script run end to end beside its monitor, its runs observed through the run door, launched in the
background or waited on, listed and cancelled; batches and sequences.

The run script runs for real, behind the tripwires: the environment it enters is a stand-in one
where the stand-in manager keeps its environments, in the test's own folder, entered by its name by
a stand-in activation hook under the record's manager root — a `conda` shell function — never the
person's manager; its command is a stand-in solver that does what its input file says, in /bin/sh.
femkit's control environment, `femkit`, which a sequence's walk enters, is a stand-in one too, whose
`femkit` command runs this checkout on the test's own python. A run's records that a test writes
itself, to see one observation rule, are written through femkit's own models: femkit's own format.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests import kit
from tests.kit import NO_GPU, a_record, ahead, apply, ctx, files, hold, refused, run, wait_until
from femkit.config import settings
from femkit.config.probe import GPU_QUERY
from femkit.core import dirs, persist, process
from femkit.core.errors import Busy, Refused, Unstated, UsageError
from femkit.core.schema import DefinitionError
from femkit.envs import state as env_state
from femkit.jobs import addresses, folders, layout, record, runs
from femkit.jobs.request import JobRequest, Resources

CHECKOUT = Path(__file__).resolve().parents[2]
SOLVER = '#!/bin/sh\n. "./$1"\n'   # the stand-in solver: runs its input file, in the run directory


@pytest.fixture
def here(tmp_path, tripwire_dir) -> Path:
    """This machine as config.toml and its record state it (`kit.stand_in_machine`): a stand-in
    `elmer` environment, and its CUDA twin, whose `ElmerSolver` runs its input file, and a
    stand-in control environment. Returns the manager's root."""
    root = kit.stand_in_machine(tmp_path, tripwire_dir, {env: {"ElmerSolver": SOLVER} for env in ("elmer", "elmer-cuda")})
    machine("local", root)
    return root


def machine(name: str, root: Path, identity: str | None = None, **changes) -> Path:
    """A record of a machine without a scheduler, named ``name``, holding this machine's settings."""
    config = settings.load(ctx(), fresh=True).config
    changes.setdefault("settings", record.settings_now(config).model_dump(exclude_none=True))
    changes.setdefault("manager", {"kind": "conda", "path": os.environ["FEMKIT_ENV_MANAGER"], "version": "26.7",
                                   "root": str(root), "platform": "linux-64", "run_enters": True})
    r = a_record(identity=identity or record.host_identity(), scheduler={"kind": "local"}, partitions={}, queues=[],
                 environments={"elmer": {"state": "ready", "install_fingerprint": "abc"}}, **changes)
    return record.write(record.path(name), r)


RESOURCES = {"ranks": 1, "threads": 3, "gpus": 0}


def calculation(folder: Path, does: str, **request) -> Path:
    """A calculation folder of the test's own, written by femkit's one writer: its request, and
    `case.sif`, what the stand-in solver does."""
    files = {"case.sif": does.encode(), **{k: v.encode() for k, v in request.pop("files", {}).items()}}
    req = {"name": "stand-in", "environment": "elmer", "command": ["ElmerSolver", "case.sif"],
           "inputs": sorted(files), "resources": RESOURCES, **request}
    return folders.write(ctx(), folder, JobRequest.model_validate(req), files)


def launch_folder(folder: Path, walk: str, listed: list[str], resources=None, maker=None) -> Path:
    """A launch folder of the test's own, written by femkit's one writer: its request and, given
    one, the action its maker names as what writes it again (jobs.md § 1.1)."""
    return folders.write(ctx(), folder, JobRequest.model_validate(
        {"name": "walk", walk: listed, "resources": resources or RESOURCES}), {}, maker=maker)


def prepared(folder: Path, **more):
    """`job prepare`, every script it wrote read by `bash -n`: each rendered run script is shell."""
    out = apply("job.prepare", dir=str(folder), **more)
    for w in out.plan.holds["folders"]:
        if w["script"] is not None:
            checked = subprocess.run(["bash", "-n", str(Path(w["path"]) / files().name("script"))], capture_output=True,
                                     text=True)
            assert checked.returncode == 0, checked.stderr
    return out


def launched(folder: Path, **more):
    return apply("job.launch", dir=str(folder), **more)


def settled(folder: Path, timeout: float = 60) -> dict[str, str]:
    """`job status`, once no run of the folder is queued or running: each run's state."""
    deadline = time.monotonic() + timeout
    while True:
        rows = run("job.status", dir=str(folder)).runs
        if not any(r.state in ("queued", "running") for r in rows) or time.monotonic() > deadline:
            return {r.run: r.state for r in rows}
        time.sleep(0.05)


def started(run_: Path, timeout: float = 30) -> runs.Launched:
    """The run, once its script wrote started.json and its launch, launched.json."""
    assert wait_until(lambda: (run_ / files().name("started")).exists() and (run_ / files().name("launched")).exists(),
                      timeout), (run_ / files().name("log")).read_text() if (run_ / files().name("log")).exists() else ""
    return persist.read_record(run_ / files().name("launched"), runs.Launched).value


def record_of(run_: Path, role: str):
    return persist.read_record(run_ / files().name(role), {**runs.RECORDS, **runs.CHECKS}[role]).value


def seen(run_: Path) -> runs.Seen:
    return runs.observe(ctx(), run_)


@pytest.fixture(autouse=True)
def nothing_left_running(tmp_path):
    """Every job a test started, stopped when it ends: none outlives its test."""
    yield
    for hold_ in tmp_path.rglob("hold"):
        hold_.unlink()
    for marker in tmp_path.rglob(files().name("launched")):
        found = persist.read_record(marker, runs.Launched).value
        if found is not None and found.job.identity().alive():
            process.end(found.job.identity(), grace=1, group=True)


# ------------------------------------------------------------------ the catalogue (jobs.md § 1.1)

def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = re.search(r"\n#{2,3} ", text[start + len(heading):])
    return text[start:start + len(heading) + following.start()] if following else text[start:]


def test_the_catalogue_is_read_once_per_invocation_and_anew_by_the_next(definitions):
    """Fails if the catalogue of a folder's files is not read through the invocation's context:
    within one invocation, a change to it after it was read is not seen; the next invocation reads
    it anew, never answered from an earlier one's read (jobs.md § 1.1: "which `jobs/layout.py`
    reads through the per-invocation cache"; api.md § 2.4)."""
    first = ctx()
    assert layout.read_once(first).name("request") == "job.toml"
    kit.rewrite(definitions / "jobs" / "files.toml", 'name = "job.toml"', 'name = "request.toml"')
    assert layout.read_once(first).name("request") == "job.toml"
    assert layout.read_once(ctx()).name("request") == "request.toml"


def test_the_contracts_tree_and_records_are_a_summary_of_the_catalogue():
    """Fails if a file jobs.md § 1's tree names, or a record § 5.1 names, is not declared in
    `femkit/data/jobs/files.toml` where the contract puts it, or is declared with another writer
    than § 5.1's sentence names: the tree and the records are a summary of the catalogue, held to
    it (jobs.md § 1.1)."""
    contract = (CHECKOUT / "docs" / "contracts" / "jobs.md").read_text(encoding="utf-8")
    tree = re.search(r"```text\n(<calculation>/.*?)```", contract, re.S).group(1)
    named = [m.group(1) for m in re.finditer(r"[├└]── (<[^>]+>|\S+)", tree)]
    catalogue = layout.read().files.values()
    calculation = {r.name for r in catalogue if "calculation" in r.lies}
    for name in named:
        if name.startswith("run-"):
            assert files().run_number(name.rstrip("/")) == 1, name
        else:
            assert name in calculation, name
    facts = _section(contract, "### 5.1 Facts")
    by_name = {r.name: r for r in catalogue}
    sentence = facts[:facts.index("| fact |")]
    in_run, in_launch = sentence.split("In a launch folder,")
    for clause in in_run.split(";"):
        first = re.search(r"`[\w.]+\.(?:json|log)`", clause)
        said = clause[:first.start()].split("in a run,")[-1].replace("`", "").replace(",", " ").split()
        writer = " ".join(w for w in said[1 if said[0] == "and" else 0:] if w != "writes")
        for f in re.findall(r"`([\w.]+\.(?:json|log))`", clause[first.start():].split("—")[0]):
            assert f in by_name and "run" in by_name[f].lies, f
            assert writer in by_name[f].writer, (f, writer, by_name[f].writer)
    for f in re.findall(r"`([\w.]+\.json)`", in_launch):
        assert f in by_name and "launch" in by_name[f].lies and by_name[f].writer == "job launch", f
    table = facts[facts.index("| fact |"):]
    for f in re.findall(r"`([\w.]+\.(?:json|log))`", table):
        assert f in by_name, f


def test_the_one_writer_writes_a_folder_whole_and_never_one_of_femkits_own_names(here, tmp_path):
    """Fails if `jobs.folders.write` leaves a folder whose request does not load as written, or
    writes a maker's file under a name a calculation folder or a run holds of femkit's own — a
    run's record a maker wrote would be read as the run's (jobs.md § 1.1)."""
    folder = calculation(tmp_path / "calc", "echo ran\n", files={"made.json": "{}"})
    assert runs.request_of(ctx(), folder).inputs == ["case.sif", "made.json"]
    with pytest.raises(ValueError, match="started.json"):
        folders.write(ctx(), tmp_path / "other", runs.request_of(ctx(), folder), {"case.sif": b"", "made.json": b"",
                                                                    "started.json": b"{}"})
    assert not (tmp_path / "other").exists()


# ------------------------------------------------------------------ the request (jobs.md § 2)

@pytest.mark.parametrize("change, key", [
    ({"command": ["ElmerSolver", "{share:geometry.xao}"]}, "command[1]"),   # a share the request does not list
    ({"command": ["ElmerSolver", "{mesh?}"]}, "command[1]"),                # an optional placeholder: none is given
    ({"check": ["{python:3}", "check.py"]}, "check[0]"),                    # {python} takes no argument
    ({"inputs": ["case.sif", "ended.json"]}, "inputs[1]"),                  # a record's name
    ({"members": ["../a"]}, "command"),                                     # a command and members both
])
def test_a_request_is_refused_at_its_key_where_it_breaks_its_rule(tmp_path, change, key):
    """Fails if a request loads that names a shared file it does not share, holds a placeholder no
    launch gives, takes a name of femkit's own, or is both a calculation folder's and a launch
    folder's (jobs.md § 2; core.md § 2.1)."""
    folder = tmp_path / "calc"
    folder.mkdir()
    persist.write_toml(folder / files().name("request"), {
        "name": "x", "environment": "elmer", "command": ["ElmerSolver", "case.sif"], "inputs": ["case.sif"],
        "resources": RESOURCES, **change})
    with pytest.raises(DefinitionError) as caught:
        runs.request_of(ctx(), folder)
    assert any(p.path.startswith(key.split("[")[0]) for p in caught.value.problems), caught.value.problems


# ------------------------------------------------------------------ prepare (jobs.md § 3)

def test_the_first_prepare_takes_the_record_copy_and_a_later_one_keeps_it(here, tmp_path):
    """Fails if a later prepare reads the record in `<config>/machines/` rather than the copy the
    first one took, or writes the copy again: what a calculation was prepared for never changes
    under it (jobs.md § 3, step 2)."""
    calc = calculation(tmp_path / "calc", "echo ran\n")
    prepared(calc)
    copy = (calc / files().name("machine")).read_bytes()
    record.write(record.path("local"), a_record(identity=record.host_identity(), scheduler={"kind": "local"},
                                                partitions={}, queues=[], notes=["measured again"],
                                                settings=record.read(record.path("local")).settings.model_dump()))
    out = prepared(calc)
    assert out.plan.holds["folders"][0]["copy"] is None
    assert (calc / files().name("machine")).read_bytes() == copy


def test_prepare_refuses_choosing_a_target_for_the_person(here, tmp_path):
    """Fails if a first prepare guesses among several records, takes a `--target` naming no record,
    or a later prepare is pointed at another machine — or writes anything when it refuses
    (jobs.md § 3, step 2 and its table)."""
    calc = calculation(tmp_path / "calc", "")
    with refused(UsageError, "no-record", "--target"):
        apply("job.prepare", dir=str(calc), target="cluster-b")
    machine("workstation-b", here, identity="workstation-b")
    with refused(Unstated, "target-unchosen", "--target") as caught:
        apply("job.prepare", dir=str(calc))
    assert [n.command for n in caught.value.next] == [f"femkit job prepare {calc} --target {t}"
                                                       for t in ("local", "workstation-b")]
    assert sorted(p.name for p in calc.iterdir()) == ["case.sif", files().name("request")]
    prepared(calc, target="local")
    with refused(Refused, "target-other", "--target"):
        apply("job.prepare", dir=str(calc), target="workstation-b")


def test_prepare_refuses_a_missing_record_of_this_machine(tmp_path):
    """Fails if a folder is prepared for `local` while this machine has no record (jobs.md § 3)."""
    calc = calculation(tmp_path / "calc", "")
    with refused(Unstated, "no-record", "local"):
        apply("job.prepare", dir=str(calc))


def test_the_probe_a_refusal_names_is_the_record_tables_action_never_one_written_by_hand(definitions, here,
                                                                                        tmp_path):
    """Fails if the probe a refusal names as what writes a record — `--target` naming no record there
    is — is written by hand rather than read from the record table's declared action: its words
    the table's, its request the one the table fills, `--name` for any record but `local`, this
    machine's own (jobs.md § 9.3: "Each state but `current` allows `job probe --write` — with
    `--name` for a record named other than `local`"; core.md § 7: "no message writes a remedy by
    hand")."""
    kit.rewrite(definitions / "states" / "record.toml", '"measure this machine, and write its record"',
                '"probe it, and write its record"')
    calc = calculation(tmp_path / "calc", "")
    with refused(UsageError, "no-record", "--target") as caught:
        apply("job.prepare", dir=str(calc), target="nowhere")
    (probe,) = [a for a in caught.value.next if a.call.operation == "job.probe"]
    assert (probe.label, probe.call.request) == ("probe it, and write its record", {"write": True, "name": "nowhere"})


@pytest.mark.parametrize("resources, refusal", [
    ({"ranks": 1, "threads": 1, "gpus": 0, "memory": "1G", "partition": "p1", "qos": "q1"},
     (Unstated, "resource-unstated", "resources.wall")),
    ({"ranks": 1, "threads": 1, "gpus": 0, "wall": "01:00:00", "memory": "1G"},
     (Unstated, "queue-unstated", "resources.partition")),
    ({"ranks": 1, "threads": 1, "gpus": 0, "wall": "01:00:00", "memory": "1G", "partition": "p1", "qos": "q9"},
     (Refused, "queue-unknown", "resources.qos")),
])
def test_prepare_for_a_scheduler_refuses_what_the_request_does_not_state(here, tmp_path, resources, refusal):
    """Fails if a request prepared for a machine with a scheduler gets a wall time or a queue it did
    not state, or one the record does not list (jobs.md § 2, § 3 step 3)."""
    config = settings.load(ctx(), fresh=True).config
    record.write(record.path("cluster-a"), a_record(settings=record.settings_now(config).model_dump(exclude_none=True)))
    calc = calculation(tmp_path / "calc", "", resources=resources)
    with refused(*refusal):
        apply("job.prepare", dir=str(calc), target="cluster-a")


@pytest.mark.parametrize("memory, cap, over", [("2G", 2047, True), ("2G", 2048, False),
                                               ("1P", 1024 ** 3 - 1, True), ("1P", 1024 ** 3, False)],
                         ids=["a cap a MiB short of it", "a cap of it", "a pebibyte over a cap a MiB short of it",
                              "a pebibyte within a cap of it"])
def test_a_requests_memory_is_counted_in_whole_mib_as_a_record_keeps_it(here, tmp_path, memory, cap, over):
    """Fails if a request's memory — `2G`, `1P` — is set against a queue's memory cap, which a record
    keeps in whole MiB, as anything but the binary multiple the unit table reads its letter as —
    2048 MiB over a cap of 2047 and within one of 2048, a pebibyte 1024³ MiB — or a letter a
    scheduler's memory is written with is refused in a request, read by a table of its own (jobs.md
    § 2: "`memory` is a positive whole number with its unit"; § 3, step 5; § 9.1: "Memory is kept in
    whole MiB"; core.md § 11: memory's binary multiples, `information`; framework.md § 1, rule 3)."""
    config = settings.load(ctx(), fresh=True).config
    queue = {"partition": "p1", "qos": "q1", "max_time": "1-00:00:00", "max_cpus": 128, "max_memory_mib": cap,
             "max_gpus": "unlimited", "max_submit_jobs_per_user": "unlimited"}
    record.write(record.path("cluster-a"), a_record(settings=record.settings_now(config).model_dump(exclude_none=True),
                                                    queues=[queue]))
    calc = calculation(tmp_path / "calc", "", resources={"ranks": 1, "threads": 1, "gpus": 0, "wall": "01:00:00",
                                                         "memory": memory, "partition": "p1", "qos": "q1"})
    _, plan, _ = kit.planned("job.prepare", dir=str(calc), target="cluster-a")
    assert ("over-queue" in {i.code for i in plan.issues}) == over


@pytest.mark.parametrize("listed, gpus, code", [
    ({}, 0, "not-installed"),
    ({"elmer": {"state": "failing"}}, 0, "not-ready"),
    ({"elmer": {"state": "ready", "install_fingerprint": "abc"}}, 0, None),
    ({"elmer-cuda": {"state": "ready", "gpu": "not-run", "install_fingerprint": "abc"}}, 1, "not-gpu-qualified"),
    ({"elmer-cuda": {"state": "ready", "gpu": "passed", "install_fingerprint": "abc"}}, 1, None),
], ids=["not listed", "listed in another state", "listed ready", "listed, not GPU-qualified", "listed, qualified"])
def test_what_the_record_lists_of_the_environment_is_shown_with_the_step_on_that_machine(here, tmp_path, listed, gpus,
                                                                                         code):
    """Fails if what another machine's record lists of the request's environment — not listed,
    listed in a state other than `ready`, or, with GPUs asked, listed not GPU-qualified — is not a
    warning whose steps settle it on that machine, `on` it, each a step the environment's own table
    gives the state the record lists, in its words — none written by hand, the GPU checks' validate
    among them; or one is said where the record lists it ready, and qualified (jobs.md § 3, step 4:
    "the environment not installed there, in a state other than `ready`, or — with `gpus > 0` — not
    GPU-qualified … is a warning naming what settles it on the target — the listed state's own next
    steps from the environment table … `env validate NAME --gpu` on a GPU node"; § 9.1: "one reader,
    `record.listed`"; core.md § 7: "no message writes a remedy by hand"; web.md § 7.2)."""
    config = settings.load(ctx(), fresh=True).config
    record.write(record.path("other"), a_record(
        identity="elsewhere", scheduler={"kind": "local"}, partitions={}, queues=[], environments=listed,
        manager={"kind": "conda", "path": "/x/bin/conda", "version": "26.7", "root": str(here),
                 "platform": "linux-64", "run_enters": True},
        settings=record.settings_now(config).model_dump(exclude_none=True)))
    calc = calculation(tmp_path / "calc", "", resources={"ranks": 1, "threads": 1, "gpus": gpus})
    _, plan, _ = kit.planned("job.prepare", dir=str(calc), target="other")
    found = [i for i in plan.issues if i.code in ("not-installed", "not-ready", "not-gpu-qualified")]
    assert [i.code for i in found] == ([code] if code else [])
    assert all(a.on == "other" for i in found for a in i.next) and all(i.next for i in found)
    c = ctx()
    m, env = env_state.machine(c), next(iter(listed), "elmer")   # each step the environment's own table allows
    state = m.states(listed[env]["state"]) if listed else m.states.absent   # not listed: not installed there
    allowed = {(s.command, s.label) for s in env_state.steps(c, env, state)}
    assert all((a.command, a.label) in allowed for i in found for a in i.next)


def test_prepare_refuses_an_unstated_setting_and_one_process_with_ranks(here, tmp_path):
    """Fails if a job is prepared for a record whose activation is unset, more than one rank asked
    of a record with no `launch.mpi`, or one process asked with more than one rank; or a setting's
    refusal names another next step than its one builder's — `config init`, which asks, for the
    activation; `config set launch.mpi`, which no workstation's `config init` proposes — then the
    probe, each on the machine the record describes (jobs.md § 3's table: "next: `config init`,
    which asks for the activation; `config set launch.mpi`"; config.md § 3.2)."""
    machine("bare", here, identity="bare", settings={})
    calc = calculation(tmp_path / "calc", "")
    with refused(Unstated, "setting-unstated", "activation.preamble") as caught:
        apply("job.prepare", dir=str(calc), target="bare")
    assert [(a.call.operation, a.on) for a in caught.value.next] == [("config.init", "bare"), ("job.probe", "bare")]
    machine("no-mpi", here, identity="no-mpi", settings={"activation": {"preamble": [], "command": "conda activate"}})
    many = calculation(tmp_path / "many", "", resources={"ranks": 2, "threads": 1, "gpus": 0})
    with refused(Unstated, "setting-unstated", "launch.mpi") as caught:
        apply("job.prepare", dir=str(many), target="no-mpi")
    assert [(a.call.operation, a.on) for a in caught.value.next] == [("config.set", "no-mpi"),
                                                                     ("job.probe", "no-mpi")]
    one = calculation(tmp_path / "one", "", one_process=True, resources={"ranks": 2, "threads": 1, "gpus": 0})
    with refused(Refused, "one-process", "resources.ranks"):
        apply("job.prepare", dir=str(one), target="local")


def test_prepare_copies_the_programs_and_the_monitor_and_a_launch_refuses_one_changed(here, tmp_path):
    """Fails if a prepared folder lacks a program its request names, the monitor or the modules a
    program runs with, or prepared.json does not record each one's SHA-256 so a launch refuses one
    changed since: a run never reads femkit's checkout (jobs.md § 1.1, § 3 step 7, § 5)."""
    calc = calculation(tmp_path / "calc", "echo ran\n", programs=["check_geometry.py"])
    prepared(calc)
    p = folders.prepared(ctx(), calc).value
    for name in ("check_geometry.py", files().name("monitor"), "documents.py", "process.py", files().name("script"),
                 files().name("machine")):
        assert p.files[name] == persist.sha256(calc / name), name
    with refused(UsageError, "no-such-program", "absent.py"):
        apply("job.prepare", dir=str(calculation(tmp_path / "other", "", programs=["absent.py"])))
    (calc / "check_geometry.py").write_text("# changed\n")
    with refused(Refused, "prepared-stale", str(calc / "check_geometry.py")):
        launched(calc)


def test_a_batch_is_prepared_whole_within_its_jobs_resources(here, tmp_path):
    """Fails if a batch's member is prepared apart from its launch folder, or one whose queue, wall
    or memory is not the job's — or whose counts do not fit inside it — is prepared at all
    (jobs.md §§ 1.2, 3)."""
    a = calculation(tmp_path / "runs" / "a", "echo a\n")
    calculation(tmp_path / "runs" / "b", "echo b\n", resources={"ranks": 1, "threads": 4, "gpus": 0})
    batch = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a", "../../b"])
    with refused(Refused, "member-differs", str(tmp_path / "runs" / "b")):
        apply("job.prepare", dir=str(batch))
    assert not (a / files().name("prepared")).exists()
    fits = launch_folder(tmp_path / "runs" / "launch" / "batch-002", "members", ["../../a", "../../b"],
                         resources={"ranks": 2, "threads": 4, "gpus": 0})
    out = prepared(fits)
    assert [Path(w["path"]) for w in out.plan.holds["folders"]] == [a, tmp_path / "runs" / "b", fits]
    assert folders.prepared(ctx(), a).value.launch == "../launch/batch-002"
    assert not (fits / files().name("script")).exists()


#: The job's resources a member runs within: every field a job and its members share stated (jobs.md § 2).
JOB = {"ranks": 2, "threads": 2, "gpus": 0, "wall": "01:00:00", "memory": "2G", "partition": "p1", "qos": "q1"}


@pytest.mark.parametrize("field, value", [("partition", "p2"), ("qos", "q2"), ("wall", "02:00:00"), ("memory", "4G")])
def test_a_member_states_each_field_its_job_and_its_members_share_as_the_job_does(here, tmp_path, field, value):
    """Fails if a member of a batch whose queue, wall or memory is not its job's — each field a job
    and every member inside it share, as the field declares its role — is prepared, or refused
    without naming that field (jobs.md § 1.2; § 2: "each `[resources]` field declares its role on
    itself — shared by a job and every member inside it (`partition`, `qos`, `wall`, `memory`)")."""
    calculation(tmp_path / "runs" / "a", "echo a\n", resources={**JOB, "ranks": 1, field: value})
    batch = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a"], resources=JOB)
    with refused(Refused, "member-differs", str(tmp_path / "runs" / "a")) as caught:
        apply("job.prepare", dir=str(batch))
    assert f"{field} {value}, the job's {JOB[field]}" in str(caught.value), str(caught.value)


def test_a_field_read_only_with_a_scheduler_is_said_not_read_on_a_machine_without_one(here, tmp_path):
    """Fails if, on a machine without a scheduler, a request stating the queue and its memory is not
    told that each of them is not read — or is told so of its wall, which a run here is told
    (jobs.md § 2: "read only where a scheduler is"; "On a machine without one, the queue and
    memory are not read, and preparation says so")."""
    calc = calculation(tmp_path / "calc", "", resources={**JOB, "ranks": 1})
    (said,) = [i.message for i in prepared(calc).issues if i.code == "not-read"]
    assert said.endswith("memory, partition, qos are not read"), said


def test_a_prepare_planned_in_memory_is_job_prepares_of_the_folders_once_written_and_writes_nothing(here, tmp_path):
    """Fails if a prepare planned from requests a maker holds, for folders not written yet — a
    batch and its member — writes anything, or differs from `job prepare` of the same folders once
    the one writer has written them: each folder's record copy, programs, run script and
    `prepared.json`, the request's SHA-256 among it, and every finding; or refuses otherwise than
    `job prepare` refuses the same request (jobs.md § 3: "A prepare planned in memory. The same
    steps run on a request a maker holds and a folder it has not written yet — the request, its
    files and the target's record given, not read from disk")."""
    from femkit.jobs import prepare
    member, batch = tmp_path / "runs" / "a", tmp_path / "runs" / "launch" / "batch-001"
    req = JobRequest.model_validate({"name": "stand-in", "environment": "elmer", "command": ["ElmerSolver", "case.sif"],
                                     "inputs": ["case.sif"], "resources": RESOURCES, "programs": ["check_mesh.py"]})
    walk = JobRequest.model_validate({"name": "walk", "members": ["../../a"], "resources": RESOURCES})
    planned = prepare.planned(ctx(), str(batch), None, {member: req, batch: walk})
    assert not (tmp_path / "runs").exists()
    folders.write(ctx(), member, req, {"case.sif": b"echo a\n"})
    launch_folder(batch, "members", ["../../a"])
    on_disk = prepare.prepare(ctx(), str(batch), None)

    def written(p) -> list[tuple]:
        return [(w.folder, w.named, w.copy, w.sources, w.script, w.prepared) for w in p.folders]

    assert written(planned) == written(on_disk) and planned.issues == on_disk.issues
    assert planned.folders[0].prepared.request == persist.sha256(member / files().name("request"))
    one = tmp_path / "one"
    many = JobRequest.model_validate({**req.model_dump(exclude_defaults=True), "one_process": True,
                                      "resources": {"ranks": 2, "threads": 1, "gpus": 0}})
    with refused(Refused, "one-process", "resources.ranks"):
        prepare.planned(ctx(), str(one), None, {one: many})
    assert not one.exists()


def test_a_launch_folder_whose_maker_names_an_operation_femkit_does_not_have_is_never_offered_it(here, tmp_path):
    """Fails if a launch folder whose `maker.json` names an operation femkit does not have — `study
    mesh`, withdrawn — is offered it, or another in its place, by `job status` or by its refused
    second launch, rather than `job status` saying so, a warning `maker-unknown` naming the
    operation, and the refusal offering only what the folder's state allows (jobs.md § 1.2: "An
    action naming an operation femkit does not have is never offered: `job status` says so, a
    warning, `maker-unknown`, naming the operation — no old name is kept to map it"; conventions
    § 2: no compatibility shims)."""
    calc = calculation(tmp_path / "calc", "echo ran\n")
    batch = launch_folder(tmp_path / "launch" / "batch-001", "members", ["../../calc"])
    gone = {"label": "study mesh check", "call": {"operation": "study.mesh", "request": {     # as an earlier
        "project": "square", "study": "check", "target": "local"}}}                          # femkit wrote it
    persist.write_json(batch / files().name("maker_action"), {"action": gone})
    prepared(batch)
    launched(batch, foreground=True)
    status = run("job.status", dir=str(batch))
    assert [a.call.operation for a in status.next] == ["job.status"]
    assert [(i.severity, i.code) for i in status.issues] == [("warning", "maker-unknown")]
    assert "study.mesh" in status.issues[0].message and status.issues[0].next == ()
    with refused(Refused, "launched-once", str(batch)) as caught:
        launched(batch)
    assert [(a.call.operation, a.call.request) for a in caught.value.next] == [("job.status", {"dir": str(batch)})]


def test_an_outcomes_next_steps_are_what_its_operation_filled_from_its_subject(here, tmp_path):
    """Fails if `job prepare`'s outcome does not hold the launch its folder's state allows, by the
    folder's full path, or holds one for another machine's target, which only that machine runs;
    or a launch's does not hold `job status` of its folder and, for a job left in the background,
    the line that stops it; or a cancel's does not hold `job list` — each a field its operation
    fills, never a step its report makes (jobs.md §§ 1, 5, 5.4; plan § 4, X: "every outcome's next
    steps a field filled from its subject's machine … `job prepare`'s launch by the folder's full
    path, and none for another machine's target")."""
    calc = calculation(tmp_path / "calc", "sleep 30\n")
    out = prepared(calc)
    assert [(a.call.operation, a.call.request) for a in out.next] == [("job.launch", {"dir": str(calc.resolve())})]
    went = launched(calc)
    assert [(a.call.operation, a.call.request) for a in went.next] == [
        ("job.status", {"dir": str(calc.resolve())}), ("job.cancel", {"id": went.job})]
    stopped = apply("job.cancel", id=went.job)
    assert [a.call.operation for a in stopped.next] == ["job.list"]
    machine("cluster-b", here, identity="another-host")
    other = calculation(tmp_path / "other", "")
    assert prepared(other, target="cluster-b").next == []


def test_prepare_and_launch_hold_the_folders_own_lock(here, tmp_path):
    """Fails if `job prepare` or `job launch` writes in a calculation folder while another process
    holds its own lock, `job-<hash>` of its resolved path, wherever it lies (jobs.md § 5; core.md § 5)."""
    calc = calculation(tmp_path / "calc", "echo ran\n")
    subject = runs.subject(calc)
    holder = hold(subject, "alone")
    try:
        with refused(Busy, "held", subject):
            apply("job.prepare", dir=str(calc))
    finally:
        holder.stdin.close()
        holder.wait()
    prepared(calc)
    holder = hold(subject, "alone")
    try:
        with refused(Busy, "held", subject):
            launched(calc)
    finally:
        holder.stdin.close()
        holder.wait()
    assert runs.runs(ctx(), calc) == []


# ------------------------------------------------------------------ the run script (jobs.md § 4)

def test_a_run_starts_clean_enters_its_environment_by_name_and_runs_on_its_python(here, tmp_path, monkeypatch):
    """Fails if anything of the shell a job is launched from reaches the run's command or its check —
    a stage's program — but what the clean start passes: another active environment, outside Python,
    injected libraries, an outside toolchain, a setting of the shell's own (jobs.md § 4, block 8;
    envs.md § 4.4); if the run enters its environment other than by its name with the manager; if
    `{python}` is any python but the entered environment's own, though the preamble put a site's
    first; if the environment's thread variable is not the request's threads; or if the run is not
    told its wall and its job's start (jobs.md § 4, blocks 4, 9, 10)."""
    ahead(tmp_path / "site", monkeypatch, {"python": "#!/bin/sh\necho 'a site python' > python.txt\n"})
    apply("config.set", key="activation.preamble", value=f'["export SITE_FIRST={tmp_path / "site"}"]')
    machine("local", here)                                        # the preamble, as the record copies it
    kit.polluted(monkeypatch)
    calc = calculation(tmp_path / "calc", "env > seen.env\n", resources={**RESOURCES, "wall": "00:02:00"},
                       check=["{python}", "check.py"],
                       files={"check.py": "import os, sys\nopen('python.txt', 'w').write(sys.executable)\n"
                                          "open('check.env', 'w').write(''.join(f'{k}={v}\\n' for k, v in os.environ.items()))\n"
                              + a_check(None)})
    prepared(calc)
    run_ = Path(launched(calc).runs[0].run)
    assert settled(calc) == {"run-001": "finished"}, (run_ / files().name("log")).read_text()
    for seen in ("seen.env", "check.env"):                         # the command; the check, a stage's program
        env = dict(line.split("=", 1) for line in (run_ / seen).read_text().splitlines() if "=" in line)
        assert kit.kept(env, shell=False) and not kit.leaked(env), (seen, kit.leaked(env))
        assert "SITE_SETTING" not in env and "/outside" not in env["PATH"]
        assert env["CONDA_PREFIX"] == str(kit.made("elmer"))      # entered by its name, femkit-elmer
        assert env["OMP_NUM_THREADS"] == "3" and env["FEMKIT_WALL_S"] == "120" and env["FEMKIT_JOB_STARTED"].isdigit()
    assert "conda activate femkit-elmer" in (calc / files().name("script")).read_text()
    assert (run_ / "python.txt").read_text() == str(kit.made("elmer") / "bin" / "python")


def test_a_run_enters_by_the_shell_hook_its_manager_prints_never_a_file_guessed_from_where_it_lies(here, tmp_path):
    """Fails if a run whose activation is the manager's shell function loads that function otherwise
    than from the manager its target's record names, by the manager's own command — a hook file formed
    from the manager's root, which on a cluster may be a module's wrapper's — so it enters no
    environment; or goes on where that manager is not there (jobs.md § 4, block 8; definitions.md
    § 6)."""
    calc = calculation(tmp_path / "calc", "true\n")
    prepared(calc)
    launched(calc)
    assert settled(calc) == {"run-001": "finished"}
    machine("local", tmp_path / "no-root-holds-a-hook", manager={"kind": "conda", "path": str(tmp_path / "gone"),
            "version": "26.7", "root": str(here), "platform": "linux-64", "run_enters": True})
    other = calculation(tmp_path / "other", "true\n")
    prepared(other)
    run_ = Path(launched(other).runs[0].run)
    assert settled(other) == {"run-001": "failed"}
    assert "which is not here" in record_of(run_, "ended").reason


def test_source_activate_after_the_clean_start_stops_saying_nothing_put_activate_on_path(here, tmp_path):
    """Fails if a run whose activation is the manager's activate script, `source activate`, fails
    after its clean start — `PATH` the system's — without saying that nothing put `activate` on PATH,
    which a site's preamble does by loading the manager, so the person reads a bare shell error
    (jobs.md § 4, block 8; envs.md § 4.4)."""
    apply("config.set", key="activation.command", value='"source activate"')
    machine("local", here)
    calc = calculation(tmp_path / "calc", "true\n")
    prepared(calc)
    run_ = Path(launched(calc).runs[0].run)
    assert settled(calc) == {"run-001": "failed"}
    assert "nothing put it there" in record_of(run_, "ended").reason


def test_only_its_launch_starts_a_run_and_only_once(here, tmp_path):
    """Fails if a run script started without `job launch`'s claim starts, or writes anything, or a
    run that holds started.json starts again: a run is one start, and its launch's (jobs.md § 4,
    blocks 2 and 3)."""
    calc = calculation(tmp_path / "calc", "echo ran >> ran.txt\n")
    prepared(calc)
    went = launched(calc)
    made = Path(went.runs[0].run)
    assert settled(calc) == {"run-001": "finished"}
    job = addresses.find(went.job).value.job                # its exit trap closes the monitor after ended.json
    assert wait_until(lambda: not job.identity().alive())
    before = {p.name: p.stat().st_mtime_ns for p in made.iterdir()}
    again = subprocess.run(["bash", files().name("script"), str(made)], cwd=made, capture_output=True, text=True,
                           env={**os.environ, "FEMKIT_LAUNCHED_BY": "femkit job launch"})
    assert again.returncode == 2 and {p.name: p.stat().st_mtime_ns for p in made.iterdir()} == before
    fresh = tmp_path / "by-hand"
    fresh.mkdir()
    for name in (files().name("script"), "case.sif", files().name("request")):
        shutil.copy(made / name, fresh / name)
    gate = subprocess.run(["bash", files().name("script"), str(fresh)], cwd=fresh, capture_output=True, text=True,
                          env={k: v for k, v in os.environ.items() if k != "FEMKIT_LAUNCHED_BY"})
    assert gate.returncode == 2 and "launch-door gate" in gate.stderr
    assert sorted(p.name for p in fresh.iterdir()) == sorted([files().name("script"), "case.sif",
                                                              files().name("request")])


def test_help_and_a_dry_run_write_nothing_and_any_other_argument_is_refused(here, tmp_path):
    """Fails if `-h` or `--dry-run` writes anything or exits other than 0, a dry run does not say
    the command, each count and its source and the environment, or an argument the script does not
    take is not refused with exit 1 (jobs.md § 4, block 1)."""
    calc = calculation(tmp_path / "calc", "", resources={"ranks": 1, "threads": 2, "gpus": 0})
    prepared(calc)
    listing = sorted(p.name for p in calc.iterdir())
    script = str(calc / files().name("script"))
    dry = subprocess.run(["bash", script, "--dry-run"], cwd=calc, capture_output=True, text=True)
    assert dry.returncode == 0, dry.stderr
    assert "the command: ElmerSolver case.sif" in dry.stdout and "threads per rank: 2, from job.toml" in dry.stdout
    assert "the environment: elmer, femkit-elmer with the manager" in dry.stdout
    assert subprocess.run(["bash", script, "-h"], cwd=calc, capture_output=True).returncode == 0
    for wrong in (["--np", "4"], ["--bogus"], [str(tmp_path)]):
        assert subprocess.run(["bash", script, *wrong], cwd=calc, capture_output=True).returncode == 1, wrong
    assert sorted(p.name for p in calc.iterdir()) == listing


def a_check(reason: str | None, outputs: list[str] = ()) -> str:
    """A check program that writes its two records as the stage programs' documents shape them
    (jobs.md § 2: the check writes them) and exits 0 when it held."""
    from femkit.engines.stages import documents
    return (f"import json, hashlib, os\nreason = {reason!r}\n"
            f"if reason is None:\n"
            f"    files = {{f: hashlib.sha256(open(f, 'rb').read()).hexdigest() for f in {list(outputs)!r}}}\n"
            f"    json.dump({{'schema': {documents.schema(documents.OUTPUTS)}, 'files': files}}, "
            f"open('outputs.json', 'w'))\n"
            f"    [os.chmod(f, 0o444) for f in files]\n"
            f"json.dump({{'schema': {documents.schema(documents.CHECKED)}, 'passed': reason is None, "
            f"'reason': reason}}, open('checked.json', 'w'))\nraise SystemExit(0 if reason is None else 4)\n")


def test_the_checks_records_are_read_in_the_shape_the_stage_programs_write_them():
    """Fails if the jobs layer reads `checked.json` or `outputs.json` in a shape other than the one
    the stage programs write — two homes for one record, one of them wrong (jobs.md § 2;
    models.md § 9.1: the documents crossing into an environment are defined once)."""
    from femkit.engines.stages import documents
    for kind, model in (("checked", runs.Checked), ("outputs", runs.Outputs)):
        assert {f.alias or n for n, f in model.model_fields.items()} == {"schema", *documents.SHAPES[kind]}, kind


def test_a_check_that_does_not_hold_makes_a_clean_exit_failed(here, tmp_path):
    """Fails if a run whose command exited 0 reads `finished` although its check did not hold, the
    verdict the check wrote is not read beside ended.json, outputs are recorded, or the script
    exits 0 (jobs.md § 2; § 4, blocks 13 and 14)."""
    calc = calculation(tmp_path / "calc", "echo made > out.txt\n", outputs=["out.txt"],
                       check=["{python}", "check.py"], files={"check.py": a_check("the group is empty")})
    prepared(calc)
    out = launched(calc, foreground=True)
    made = Path(out.runs[0].run)
    assert not out.ok() and out.runs[0].state == "failed"
    assert record_of(made, "ended").status == 0
    assert (record_of(made, "checked").passed, record_of(made, "checked").reason) == (False, "the group is empty")
    assert not (made / files().name("outputs")).exists()
    again = tmp_path / "again"                       # the script's own exit, as whoever started it reads it
    shutil.copytree(made, again, ignore=lambda d, names: [n for n in names if n not in folders.prepared(ctx(), calc).value.files
                                                         and n not in ("case.sif", "check.py", files().name("request"))])
    started_ = subprocess.run(["bash", files().name("script"), str(again)], cwd=again, capture_output=True,
                              env={**os.environ, "FEMKIT_LAUNCHED_BY": "femkit job launch"})
    assert started_.returncode == 1 and record_of(again, "ended").status == 0


def test_a_check_that_holds_records_each_output_and_makes_it_read_only(here, tmp_path):
    """Fails if a run whose check held leaves an output writable or unrecorded by its SHA-256, or
    reads anything but `finished` (jobs.md § 2; § 4, block 13)."""
    calc = calculation(tmp_path / "calc", "echo made > out.txt\n", outputs=["out.txt"],
                       check=["{python}", "check.py"], files={"check.py": a_check(None, ["out.txt"])})
    prepared(calc)
    out = launched(calc, foreground=True)
    made = Path(out.runs[0].run)
    assert out.ok() and out.runs[0].state == "finished"
    assert record_of(made, "outputs").files == {"out.txt": persist.sha256(made / "out.txt")}
    assert (made / "out.txt").stat().st_mode & 0o222 == 0


def test_the_checks_records_are_found_by_the_document_each_holds_never_by_a_name_of_their_own(here, tmp_path,
                                                                                               definitions):
    """Fails if the jobs domain finds a record a stage's check writes — its verdict, its outputs —
    by a name of its own beside the stage programs' document the catalogue says the file holds, so
    the records are named in two places that can drift: a catalogue whose rows for them are named
    otherwise still runs, launches from and reads such a run as before; or a catalogue holding no
    file for one of those records loads (jobs.md § 5.1: "`checked.json`, written by the check …
    at the stage programs' documents' schema (`documents.py`, `checked`)"; plan § 4, X: "the
    check's records `checked` and `outputs` named once")."""
    table = definitions / "jobs" / "files.toml"
    kit.rewrite(table, "[files.checked]", "[files.verdict]")
    kit.rewrite(table, "[files.outputs]\n", "[files.hashes]\n")
    made = calculation(tmp_path / "made", "echo made > out.txt\n", outputs=["out.txt"],
                       check=["{python}", "check.py"], files={"check.py": a_check(None, ["out.txt"])})
    prepared(made)
    out = launched(made, foreground=True)
    assert out.ok() and out.runs[0].state == "finished"
    reader = calculation(tmp_path / "reader", "cat \"$1\" > /dev/null\n",
                         shares=[{"folder": "../made", "file": "out.txt"}])
    prepared(reader)
    assert launched(reader, foreground=True).ok()
    held = table.read_text()
    table.write_text(held.replace('document = "outputs"\n', ""))
    with refused(DefinitionError, "definition-invalid"):
        layout.read()
    table.write_text(held)


def test_a_preamble_that_sources_a_missing_file_stops_the_run_before_its_end(here, tmp_path):
    """Fails if a preamble written for another machine runs halfway: every absolute file a bare
    `source` line of it names is checked readable first, and a missing one stops the run with
    ended.json saying so (jobs.md § 4, blocks 6 and 8)."""
    apply("config.set", key="activation.preamble", value=f'["source {tmp_path}/site/env.sh"]')
    machine("local", here)
    calc = calculation(tmp_path / "calc", "echo ran > ran.txt\n")
    prepared(calc)
    made = Path(launched(calc, foreground=True).runs[0].run)
    assert seen(made).state.value == "failed"
    assert record_of(made, "ended").reason == f"stopped before its end: the preamble sources {tmp_path}/site/env.sh, " \
                                              "which is not readable here"
    assert not (made / "ran.txt").exists()


def test_a_gpu_asked_for_and_none_visible_stops_the_run_after_its_traps(here, tmp_path, monkeypatch):
    """Fails if a run asking for a GPU goes on when none is visible — no scheduler grant, no
    CUDA_VISIBLE_DEVICES, a driver that lists none — or stops before its log and its traps, so that
    nothing records why (jobs.md § 4, block 7; framework.md § 4)."""
    ahead(tmp_path / "workstation", monkeypatch, {GPU_QUERY[0]: NO_GPU})
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    calc = calculation(tmp_path / "calc", "echo ran > ran.txt\n", resources={"ranks": 1, "threads": 1, "gpus": 1})
    prepared(calc)
    made = Path(launched(calc, foreground=True).runs[0].run)
    assert "none is visible" in record_of(made, "ended").reason
    assert (made / files().name("log")).is_file() and not (made / "ran.txt").exists()


def test_the_monitor_leaves_its_tags_and_its_closing_record_states_the_runs_records(here, tmp_path):
    """Fails if the monitor beside a run does not leave its machine line, its start, its closing
    record and after it the run's records as they stand — never a state of its own — and what
    its percentages are fractions of (jobs.md § 4.3)."""
    calc = calculation(tmp_path / "calc", "echo ran\n")
    prepared(calc)
    made = Path(launched(calc, foreground=True).runs[0].run)
    held = (made / files().name("monitor_log")).read_text()
    tags = re.findall(r"\] \[([A-Z-]+)\] (\S+)?", held)
    assert [t for t, _ in tags] == ["MACHINE", "MONITOR", "MONITOR", "STATUS", "UTIL-SUMMARY", "UTIL-BASIS"], held
    closing = held.splitlines()[3]
    assert "ended.json: exit 0" in closing and "finished" not in closing
    assert "stopped by SIGTERM" in held.splitlines()[2]
    assert (made / files().name("util")).read_text().startswith("epoch,iso,cpu_pct,mem_gb")


def test_the_monitor_says_what_the_log_gained_and_closes_when_the_watched_process_is_gone(tmp_path):
    """Fails if the monitor, run as a run script runs it, writes no `[STATUS]` when the run's log
    grew, or does not close with its closing record once the process it watches is gone
    (jobs.md § 4.3)."""
    watched = subprocess.Popen(["sleep", "1.5"])
    (tmp_path / "run.log").write_text("")
    monitor = files().beside()[files().name("monitor")]
    shutil.copy(monitor, tmp_path / "monitor.py")
    child = subprocess.Popen([sys.executable, "monitor.py", "--watch-pid", str(watched.pid), "--cores", "1",
                              "--interval", "0.2", "--log", "run.log", "--writes", "monitor.log", "--util", "util.csv",
                              "--ended", "ended.json", "--checked", "checked.json"], cwd=tmp_path,
                             stderr=subprocess.PIPE, text=True)
    time.sleep(0.5)
    with open(tmp_path / "run.log", "a") as fh:
        fh.write("SCF iteration 3\n")
    watched.wait()
    assert child.wait(timeout=10) == 0, child.stderr.read()
    held = (tmp_path / "monitor.log").read_text()
    assert "the last: SCF iteration 3" in held
    assert f"[MONITOR] job ended (watched pid {watched.pid} gone)" in held
    assert "no ended.json; no checked.json" in held


# ------------------------------------------------------------------ launch (jobs.md § 5)

def test_shares_are_read_where_they_were_made_checked_and_their_path_written_in(here, tmp_path):
    """Fails if a run copies a file another calculation folder made instead of reading it where it
    was made, by its path written into the run's script; or a launch takes it from a run that did
    not finish, or one changed since its run recorded it (jobs.md §§ 2, 5)."""
    maker = calculation(tmp_path / "geometry", "exit 1\n", outputs=["out.txt"], check=["{python}", "check.py"],
                        files={"check.py": a_check(None, ["out.txt"])})
    user = calculation(tmp_path / "mesh", 'cat "$2" > copy.txt\n',
                       command=["ElmerSolver", "case.sif", "{share:out.txt}"],
                       shares=[{"folder": "../geometry", "file": "out.txt"}])
    prepared(maker)
    prepared(user)
    with refused(Refused, "shares-unfinished", str(maker)):
        launched(user)                                    # no run at all
    launched(maker, foreground=True)
    with refused(Refused, "shares-unfinished", str(maker)):
        launched(user)                                    # its newest run failed
    (maker / "case.sif").write_text("echo made > out.txt\n")
    made = Path(launched(maker, foreground=True).runs[0].run)
    run_ = Path(launched(user, foreground=True).runs[0].run)
    assert (run_ / "copy.txt").read_text() == "made\n" and not (run_ / "out.txt").exists()
    assert "share_1=../../geometry/run-002/out.txt" in (run_ / files().name("script")).read_text()
    (made / "out.txt").chmod(0o644)
    (made / "out.txt").write_text("changed\n")
    with refused(Refused, "shares-changed", str(made / "out.txt")):
        launched(user)


@pytest.mark.parametrize("case, refusal", [
    ("unprepared", (Refused, "not-prepared")),
    ("another machine", (Refused, "not-this-machine", "workstation-b")),
    ("input gone", (UsageError, "no-such-input")),
    ("in-sequence alone", (UsageError, "in-sequence-alone", "--in-sequence")),
])
def test_launch_refuses_what_its_table_names_and_opens_no_run(here, tmp_path, case, refusal):
    """Fails if a launch opens a run for a folder not prepared, prepared for another machine, whose
    input is gone, or started with a sequence's flags by anything but a waited-on launch
    (jobs.md § 5's table)."""
    calc = calculation(tmp_path / "calc", "echo ran\n")
    more = {}
    if case != "unprepared":
        if case == "another machine":
            machine("workstation-b", here, identity="workstation-b")
        prepared(calc, **({"target": "workstation-b"} if case == "another machine" else {}))
    if case == "input gone":
        (calc / "case.sif").unlink()
    if case == "in-sequence alone":
        more = {"in_sequence": str(tmp_path), "in_job": "h-1"}
    with refused(*refusal):
        launched(calc, **more)
    assert runs.runs(ctx(), calc) == []


def test_a_launch_fills_again_a_run_never_launched_and_never_empties_one_that_started(here, tmp_path):
    """Fails if a launch opens a new run beside one a cut-short launch opened and never launched
    rather than emptying it whole and filling it again — or empties a run whose start began but
    whose launch record was never written, which reads `running` (jobs.md §§ 5, 5.2)."""
    calc = calculation(tmp_path / "calc", "echo ran\n")
    prepared(calc)
    pending = calc / files().run_name(1)
    pending.mkdir()
    (pending / "stray.XV").write_text("left from an earlier fill\n")
    assert seen(pending).state.value == "pending"
    launched(calc, foreground=True)
    assert [r.name for r in runs.runs(ctx(), calc)] == ["run-001"] and not (pending / "stray.XV").exists()
    cut = calc / files().run_name(2)
    cut.mkdir()
    runs.write(cut / files().name("started"), runs.Started(time="2026-01-01T00:00:00+00:00", host="h"))
    with refused(Refused, "not-allowed", str(cut)):
        launched(calc)
    assert (cut / files().name("started")).exists()


def test_a_launch_waited_on_exits_by_how_its_runs_ended_and_removes_its_address(here, tmp_path):
    """Fails if a launch waited on reports success for a run that failed, or leaves its address once
    it has said how its runs ended (jobs.md §§ 5, 5.4)."""
    calc = calculation(tmp_path / "calc", "exit 3\n")
    prepared(calc)
    out = launched(calc, foreground=True)
    assert not out.ok() and out.runs[0].state == "failed" and "exit 3" in out.runs[0].words
    assert addresses.listing() == []


def test_a_background_launch_leaves_an_address_job_list_shows_once_it_ended(here, tmp_path):
    """Fails if a launch in the background leaves no address naming its job and run, `job list`
    does not show it with its run's state, or shows an ended job twice (jobs.md § 5.4)."""
    calc = calculation(tmp_path / "calc", "echo ran\n")
    prepared(calc)
    out = launched(calc)
    assert out.ok() and out.how == "background"
    assert [a.value.id for _, a in addresses.listing()] == [out.job]
    job = addresses.find(out.job).value.job
    assert settled(calc) == {"run-001": "finished"}
    assert wait_until(lambda: not job.identity().alive())
    first = run("job.list").jobs
    assert [(j.id, [r.state for r in j.runs]) for j in first] == [(out.job, ["finished"])]
    assert run("job.list").jobs == []


def test_job_cancel_stops_a_job_once_and_its_run_reads_failed_cancelled(here, tmp_path):
    """Fails if `job cancel` stops anything but the job named, writes ended.json for it, leaves no
    cancel.json, or the run reads otherwise than `failed`, *cancelled*; or if it cancels a job
    waited on at its terminal, or one there is no address of (jobs.md §§ 4 block 6, 5.4)."""
    calc = calculation(tmp_path / "calc", "echo never\n")
    prepared(calc)
    (calc / "hold").touch()
    out = launched(calc)
    made = Path(out.runs[0].run)
    started(made)
    assert seen(made).state.value == "running"
    cancelled = apply("job.cancel", id=out.job)
    assert cancelled.stopped
    assert wait_until(lambda: seen(made).state.value == "failed")
    assert record_of(made, "ended") is None and (made / files().name("cancel")).is_file()
    assert "cancelled" in seen(made).words
    assert "stopped by SIGTERM" in (made / files().name("log")).read_text()
    with refused(UsageError, "no-such-job", "nowhere-1"):
        apply("job.cancel", id="nowhere-1")


def test_a_job_waited_on_is_not_cancelled_from_elsewhere(here, tmp_path):
    """Fails if `job cancel` signals a job a launch waits on: it is stopped at its terminal
    (jobs.md § 5.4)."""
    calc = calculation(tmp_path / "calc", "echo ran\n")
    prepared(calc)
    own = process.identify(os.getpid())
    a = addresses.Address(id=f"{dirs.host()}-{own.pid}", how="waited on", host=dirs.host(),
                          job=runs.Job.of(dirs.host(), own), folder=str(calc), time="2026-01-01T00:00:00+00:00")
    addresses.write(a)
    with refused(Refused, "waited-on", a.id):
        apply("job.cancel", id=a.id)


def test_a_killed_run_reads_failed_its_word_written_once_and_read_the_same_from_a_copy(here, tmp_path):
    """Fails if a run killed with no handler to answer reads anything but `failed`, the job's word
    is not written into it once — by whichever reader asks first — or a copy of its folder read
    elsewhere reads otherwise or writes it again (jobs.md §§ 5.1, 5.2)."""
    calc = calculation(tmp_path / "calc", "echo never\n")
    prepared(calc)
    (calc / "hold").touch()
    out = launched(calc)
    made = Path(out.runs[0].run)
    job = started(made).job
    os.killpg(job.pid, signal.SIGKILL)
    assert wait_until(lambda: not job.identity().alive())
    first = seen(made)
    assert first.state.value == "failed" and "stopped before its end" in first.words
    gone = made / files().name("gone")
    when = gone.stat().st_mtime_ns
    assert run("job.status", dir=str(calc)).runs[0].state == "failed" and gone.stat().st_mtime_ns == when
    copy = tmp_path / "copied" / "calc"
    shutil.copytree(calc, copy)
    assert seen(copy / made.name).state.value == "failed"
    assert (copy / made.name / files().name("gone")).read_bytes() == gone.read_bytes()


def test_a_folder_a_job_still_going_holds_is_prepared_or_launched_by_nothing_else(here, tmp_path):
    """Fails if a member a batch's job still going has not reached yet is prepared or launched by
    anything but that job: it reads `held`, and both refuse it naming the job (jobs.md §§ 1.2, 3,
    5, 5.5)."""
    a = calculation(tmp_path / "runs" / "a", "echo a\n")
    b = calculation(tmp_path / "runs" / "b", "echo b\n")
    batch = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a", "../../b"])
    prepared(batch)
    (a / "hold").touch()
    out = launched(batch)
    started(a / files().run_name(1))
    assert run("job.status", dir=str(b)).state == "held"
    with refused(Refused, "held", str(b)) as caught:
        apply("job.prepare", dir=str(b))
    assert f"femkit job cancel {out.job}" in [s.command for s in caught.value.next]
    with refused(Refused, "held", str(b)):
        launched(b)


def test_a_maker_states_a_requests_resources_again_alone_and_never_while_a_job_holds_it(here, tmp_path):
    """Fails if `folders.restate` changes anything of a request but its resources, or leaves the
    folder reading otherwise than `stale`, to be prepared again; or states them again in a folder a
    job still going holds, or one whose run goes, rather than refusing, `not-allowed`, with what its
    state allows (jobs.md § 1.1: "its resources alone, while no job holds the folder and no run of it
    goes"; §§ 3, 5.5)."""
    c = calculation(tmp_path / "runs" / "c", "echo c\n")
    prepared(c)
    before = runs.request_of(ctx(), c)
    wider = Resources(ranks=1, threads=2, gpus=0, wall="00:20:00")
    folders.restate(ctx(), c, wider)
    after = runs.request_of(ctx(), c)
    assert after.resources == wider and after.model_copy(update={"resources": before.resources}) == before
    assert run("job.status", dir=str(c)).state == "stale"
    prepared(c)
    assert run("job.status", dir=str(c)).state == "prepared"
    a = calculation(tmp_path / "runs" / "a", "echo a\n")
    b = calculation(tmp_path / "runs" / "b", "echo b\n")
    batch = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a", "../../b"])
    prepared(batch)
    (a / "hold").touch()
    out = launched(batch)
    started(a / files().run_name(1))
    for folder, state, offered in ((b, "held", f"femkit job cancel {out.job}"), (a, "running", "femkit job status")):
        written = (folder / files().name("request")).read_bytes()
        assert run("job.status", dir=str(folder)).state == state
        with refused(Refused, "not-allowed", str(folder)) as caught:
            folders.restate(ctx(), folder, wider)
        assert any(s.command.startswith(offered) for s in caught.value.next), caught.value.next
        assert (folder / files().name("request")).read_bytes() == written


def test_launch_refuses_a_member_prepared_apart_a_target_with_a_scheduler_and_an_unreadable_run(here, tmp_path):
    """Fails if a batch launches a member prepared apart from it, a folder prepared for a machine with
    a scheduler is started here — or waited on — or a launch goes on past a run whose launch record
    does not read (jobs.md § 5's table)."""
    a = calculation(tmp_path / "runs" / "a", "echo a\n")
    batch = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a"])
    prepared(batch)
    prepared(a)
    with refused(Refused, "prepared-apart", str(a)):
        launched(batch)
    config = settings.load(ctx(), fresh=True).config
    record.write(record.path("cluster-a"), a_record(settings=record.settings_now(config).model_dump(exclude_none=True)))
    queued = calculation(tmp_path / "queued", "", resources={"ranks": 1, "threads": 1, "gpus": 0, "wall": "01:00:00",
                                                              "memory": "1G", "partition": "p1", "qos": "q1"})
    prepared(queued, target="cluster-a")
    with refused(Refused, "not-built", "cluster-a"):
        launched(queued)
    with refused(UsageError, "foreground-scheduler", "--foreground"):
        launched(queued, foreground=True)
    (a / files().run_name(1)).mkdir()
    (a / files().run_name(1) / files().name("launched")).write_text("{")
    with refused(Refused, "unreadable", str(a / files().run_name(1) / files().name("launched"))):
        launched(a)


QUEUED = {"ranks": 1, "threads": 1, "gpus": 0, "wall": "01:00:00", "memory": "1G", "partition": "p1", "qos": "q1"}


def test_on_a_cluster_its_own_record_by_another_name_is_this_machines_for_its_probe_and_its_launch(here, tmp_path,
                                                                                                  sleeper):
    """Fails if, on a cluster whose own records — `local`, and `cluster-a`, written there to carry
    elsewhere — name it by its scheduler's cluster name, never this host's: the probe a prepare for
    `cluster-a` names carries the machine `cluster-a` as another's (`Action.on`), told by the
    record's name; or a part of a sequence prepared for `cluster-a`, launched inside that sequence's
    job there, is refused `not-this-machine`, its copy's identity set against this host's name
    (jobs.md § 9.3; workflow.md § 7: "The machine a record describes is told by its identity of the
    host, never its name, in one function: on the cluster, its own record `cluster-a` is this
    machine's, as `local` is"; jobs.md § 5's table)."""
    config = settings.load(ctx(), fresh=True).config
    cluster = a_record(manager={"kind": "conda", "path": os.environ["FEMKIT_ENV_MANAGER"], "version": "26.7",
                                "root": str(here), "platform": "linux-64", "run_enters": True},
                       environments={"elmer": {"state": "ready", "install_fingerprint": "abc"}},
                       settings=record.settings_now(config).model_dump(exclude_none=True))
    assert cluster.identity != record.host_identity()
    for name in ("local", "cluster-a"):
        record.write(record.path(name), cluster)
    part = calculation(tmp_path / "part", "echo ran\n", resources=QUEUED)
    sequence = launch_folder(tmp_path / "launch" / "seq-001", "sequence", ["../../part"], resources=QUEUED)
    out = prepared(sequence, target="cluster-a")
    probes = [a for i in out.issues for a in i.next if a.call is not None and a.call.operation == "job.probe"]
    assert probes and all(a.on is None for a in probes)
    runs.write(sequence / files().name("launch_record"), folders.LaunchRecord(   # as its launch writes it, before
        time="2026-01-01T00:00:00+00:00", identity=record.host_identity(), job=sleeper,     # the job goes
        listed=[folders.Listed(folder="../../part")]))
    inside = launched(part, foreground=True, in_sequence=str(sequence), in_job=sleeper.id)
    assert inside.ok() and [r.state for r in inside.runs] == ["finished"]


def _write(path: Path, model) -> None:
    runs.write(path, model)


@pytest.fixture
def sleeper():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
    yield runs.Job.of(record.host_identity(), process.identify(p.pid))
    p.kill()
    p.wait()


@pytest.mark.parametrize("case, expected", [
    ("unreadable launched", "unreadable"),               # rule 1
    ("ended 0", "finished"),                             # rule 2
    ("ended 0, check, passed", "finished"),              # rule 2
    ("ended 2", "failed"),                               # rule 3
    ("ended 0, check", "failed"),                        # rule 3: the check stopped before its verdict
    ("ended 0, check, not passed", "failed"),            # rule 3
    ("gone, started", "failed"),                         # rule 4
    ("closed, started, alive", "failed"),                # rule 5
    ("wall passed, started, alive", "failed"),           # rule 6
    ("started, alive", "running"),                       # rule 7
    ("started, elsewhere", "running"),                   # rule 7: another machine's is not asked
    ("alive", "queued"),                                 # rule 8
    ("", "pending"),                                     # rule 9
    ("ended 0, gone, closed", "finished"),               # rule 2 before rules 4 and 5
])
def test_each_observation_rule_gives_its_state_in_order(case, expected, tmp_path, sleeper):
    """Fails if a run's state is not the first of § 5.2's rules that holds — each rule seen, from
    its records alone and the job's word, asked only of a job launched from this machine."""
    made = tmp_path / "calc" / files().run_name(1)
    made.mkdir(parents=True)
    words = case.split(", ") if case else []
    now = "2026-01-01T00:00:00+00:00"
    persist.write_toml(made / files().name("request"), {
        "name": "x", "environment": "elmer", "command": ["ElmerSolver"], "resources": RESOURCES,
        **({"check": ["{python}", "check.py"]} if "check" in words else {})})
    job = sleeper if "alive" in words or "elsewhere" in words else runs.Job.of(record.host_identity(),
                                                                              process.Identity(1, 1, "gone"))
    if "unreadable launched" in words:
        (made / files().name("launched")).write_text("{")
    elif words:
        _write(made / files().name("launched"), runs.Launched(
            time=now, identity="another-machine" if "elsewhere" in words else record.host_identity(), job=job,
            wall="00:00:01" if "wall passed" in words else None))
    if "started" in words:
        _write(made / files().name("started"), runs.Started(time=now, host="h"))
        os.utime(made / files().name("started"), (0, 0))
    for word in words:
        if word.startswith("ended"):
            _write(made / files().name("ended"), runs.Ended(status=int(word.split()[1]), time=now))
    if "passed" in words or "not passed" in words:
        _write(made / files().name("checked"), runs.Checked.model_validate({"schema": 1, "passed": "not passed" not in words}))
    if "gone" in words:
        _write(made / files().name("gone"), runs.Gone(time=now, where="h", found="its process ended"))
    if "closed" in words:
        (made / files().name("monitor_log")).write_text("[t] [MONITOR] job ended (stopped by SIGTERM)\n")
        os.utime(made / files().name("monitor_log"), (0, 0))
    assert seen(made).state.value == expected


# ------------------------------------------------------------------ a folder's state (jobs.md § 5.5)

def test_a_folders_state_follows_its_preparation_and_its_newest_run(here, tmp_path):
    """Fails if a calculation folder reads otherwise than its table says: unprepared, prepared,
    stale once its request changed, its newest run's state once it ran — and a launch folder,
    `launched` once its launch record is there, refusing a second launch with the action its
    maker named beside what its state allows, and `job status` of it offering that action beside its
    table's (jobs.md §§ 1.2, 5.5: "`job status`, and the action its `maker.json` names"; § 5: "next:
    what its state allows")."""
    calc = calculation(tmp_path / "calc", "echo ran\n")
    state = lambda folder: run("job.status", dir=str(folder)).state
    assert state(calc) == "unprepared"
    prepared(calc)
    assert state(calc) == "prepared"
    (calc / files().name("request")).write_text((calc / files().name("request")).read_text().replace("3", "2"))
    assert state(calc) == "stale"
    with refused(Refused, "prepared-stale", str(calc / files().name("request"))):
        launched(calc)
    prepared(calc)
    launched(calc, foreground=True)
    assert state(calc) == "finished"
    again = folders.Maker(action=run("job.status", dir=str(calc)).next[0]).action
    batch = launch_folder(tmp_path / "launch" / "batch-001", "members", ["../../calc"], maker=again)
    prepared(batch)
    launched(batch, foreground=True)
    assert state(batch) == "launched"
    with refused(Refused, "launched-once", str(batch)) as caught:
        launched(batch)
    assert [(a.call.operation, a.call.request) for a in caught.value.next] == [
        ("job.status", {"dir": str(batch)}), (again.call.operation, again.call.request)]
    assert [(a.call.operation, a.call.request["dir"]) for a in run("job.status", dir=str(batch)).next] == [
        ("job.status", str(batch)), (again.call.operation, again.call.request["dir"])]


def test_a_member_goes_whole_with_its_launch_folder_the_first_time_and_alone_only_again(here, tmp_path):
    """Fails if a member prepared with a launch folder not launched yet — a batch's member, a
    sequence's part, a member of a batch inside a sequence — does not read `in_launch`, *needs
    update*, its next steps `job launch` of the launch folder that holds it by its full path — the
    sequence, for a batch inside one — then `job prepare` of it, which takes it out of that job; or
    `job launch` of it alone is not refused `not-allowed` with those next steps; or the launch
    folder is not prepared again and launched whole; or the member, once its run ended, is not
    launched alone again (jobs.md §§ 1.2, 5.5: the earlier tool's "a group goes whole the first
    time; a member is launched alone only again")."""
    def seen(folder: Path) -> tuple[str, str, list[tuple[str, str]]]:
        c = ctx()
        m = folders.machine(c)
        f, state = folders.observe(c, folder)
        return state.value, m.word(state), [(x.call.operation, x.call.request["dir"]) for x in m.next(state, f)]

    a = calculation(tmp_path / "runs" / "a", "echo a\n")
    batch = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a"])
    prepared(batch)
    assert seen(a) == ("in_launch", "needs update", [("job.launch", str(batch)), ("job.prepare", str(a))])
    with refused(Refused, "not-allowed", str(a)) as caught:
        launched(a)
    assert [(x.call.operation, x.call.request["dir"]) for x in caught.value.next] == [("job.launch", str(batch)),
                                                                                       ("job.prepare", str(a))]
    b = calculation(tmp_path / "runs" / "b", "echo b\n")
    inner = launch_folder(tmp_path / "runs" / "launch" / "batch-002", "members", ["../../b"])
    seq = launch_folder(tmp_path / "runs" / "launch" / "seq-001", "sequence", ["../batch-002"])
    prepared(seq)
    assert seen(b)[:2] == seen(inner)[:2] == ("in_launch", "needs update")
    assert seen(b)[2] == [("job.launch", str(seq)), ("job.prepare", str(b))]
    assert seen(inner)[2] == [("job.launch", str(seq)), ("job.prepare", str(inner))]
    with refused(Refused, "not-allowed", str(inner)):
        launched(inner)
    prepared(batch)
    assert launched(batch, foreground=True).ok()
    assert seen(a)[0] == "finished"
    assert launched(a, foreground=True).ok()


def test_a_member_with_runs_of_its_own_goes_whole_with_a_new_launch_folder_not_launched_yet(here, tmp_path):
    """Fails if a member whose earlier run failed, prepared again with a new launch folder not
    launched yet, does not read `in_launch` with that launch folder's launch as its first next step
    — so a second writer would put it in yet another job (jobs.md § 5.5: "a member or part prepared
    with a launch folder not launched yet, whatever runs it made before")."""
    c = ctx()
    a = calculation(tmp_path / "runs" / "a", "exit 3\n")
    first = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a"])
    prepared(first)
    assert not launched(first, foreground=True).ok()
    second = launch_folder(tmp_path / "runs" / "launch" / "batch-002", "members", ["../../a"])
    prepared(second)
    m = folders.machine(c)
    f, state = folders.observe(c, a)
    assert state.value == "in_launch"
    assert [(x.call.operation, x.call.request["dir"]) for x in m.next(state, f)][0] == ("job.launch", str(second))



def test_a_launch_folder_whose_member_was_prepared_apart_reads_regrouped_offering_its_makers_action_alone(
        here, tmp_path):
    """Fails if a launch folder not launched yet — a batch, and the sequence holding it — whose
    member was prepared apart since does not read `regrouped`, *needs update*, offering only the
    action its `maker.json` names, which forms the job again; or its launch is not refused
    `prepared-apart`, naming that member, before anything is opened or the job goes; or the
    member left in it still reads `in_launch` of a job that is not whole (jobs.md § 5.5, rows 5–6:
    "a launch folder not launched yet, a member or part it names prepared apart since … `job
    launch` refuses it `prepared-apart`"; "one whose launch folder is not there or not whole … is
    in no job"; the earlier tool's `ready.regrouped`)."""
    a = calculation(tmp_path / "runs" / "a", "echo a\n")
    b = calculation(tmp_path / "runs" / "b", "echo b\n")
    again = folders.Maker(action=run("job.status", dir=str(a)).next[0]).action   # what writes it again
    batch = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a", "../../b"], maker=again)
    seq = launch_folder(tmp_path / "runs" / "launch" / "seq-001", "sequence", ["../batch-001"], maker=again)
    assert folders.maker(ctx(), seq).action == again
    prepared(seq)
    assert folders.observe(ctx(), b)[1].value == "in_launch"
    prepared(a)                                                     # taken out of its job
    c = ctx()
    m = folders.machine(c)
    for folder in (batch, seq):
        f, state = folders.observe(c, folder)
        assert (state.value, m.word(state)) == ("regrouped", "needs update")
        assert [x.command for x in folders.next_steps(c, state, f)] == [again.command]
    assert folders.observe(c, b)[1].value == "prepared"
    for folder in (seq, batch):
        with refused(Refused, "prepared-apart", str(a)):
            launched(folder)
    assert not runs.runs(ctx(), b) and not (seq / files().name("launch_record")).exists()


def test_a_launch_folder_offers_its_makers_action_where_its_row_says_so_whatever_the_rows_name(here, tmp_path,
                                                                                                definitions):
    """Fails if the action a launch folder's `maker.json` names is offered by the name of the row that
    allows it, `again`, rather than by the row's own mark that its operation is its subject's — so a
    row renamed stops offering it — or a row of neither operation nor shell offers it without that
    mark (core.md § 7: "or neither: the request is allowed and asks nothing of a person, never
    offered as a next step … save where the row says its operation is its subject's (`subject =
    true`: a launch folder's maker's, read from `maker.json`)"; jobs.md § 5.5, row 5)."""
    table = definitions / "states" / "calculation.toml"
    kit.rewrite(table, 'again = { describe = "form the job again, by what wrote it"',
                'anew = { describe = "form the job again, by what wrote it"')
    a = calculation(tmp_path / "runs" / "a", "echo a\n")
    calculation(tmp_path / "runs" / "b", "echo b\n")
    again = folders.Maker(action=run("job.status", dir=str(a)).next[0]).action   # what writes it again
    batch = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a", "../../b"], maker=again)
    prepared(batch)
    prepared(a)                                                     # taken out of its job: regrouped

    def offered() -> list[str]:
        c = ctx()
        f, state = folders.observe(c, batch)
        assert state.value == "regrouped"
        return [x.command for x in folders.next_steps(c, state, f)]

    assert offered() == [again.command]
    kit.rewrite(table, 'anew = { describe = "form the job again, by what wrote it", subject = true }',
                'anew = { describe = "form the job again, by what wrote it" }')
    assert offered() == []


def test_a_member_whose_launch_folder_is_not_there_is_in_no_job(here, tmp_path):
    """Fails if a member prepared with a launch folder that is not there — a prep cut short after it
    wrote its stages and before their job — still reads `in_launch`, so no later prep would place it
    in a job again (jobs.md § 5.5: "prepared with a launch folder that is there and not launched
    yet"; ADR 0022: "a prep cut short leaves a project a second prep completes")."""
    import shutil
    c = ctx()
    a = calculation(tmp_path / "runs" / "a", "echo a\n")
    batch = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a"])
    prepared(batch)
    assert folders.observe(c, a)[1].value == "in_launch"
    shutil.rmtree(batch)
    assert folders.observe(ctx(), a)[1].value != "in_launch"


# ------------------------------------------------------------------ batches and sequences (jobs.md §§ 4.1, 4.2)

def test_a_batch_runs_every_member_in_one_job_and_one_that_fails_leaves_the_rest_to_run(here, tmp_path):
    """Fails if a batch's walk stops at a member that failed, runs a member outside its own new run,
    or its members' runs ride any job but the walk's (jobs.md §§ 1.2, 4.1, 5.1)."""
    a = calculation(tmp_path / "runs" / "a", "exit 3\n")
    b = calculation(tmp_path / "runs" / "b", "echo b > b.txt\n")
    batch = launch_folder(tmp_path / "runs" / "launch" / "batch-001", "members", ["../../a", "../../b"])
    prepared(batch)
    out = launched(batch, foreground=True)
    assert not out.ok()
    assert {Path(r.run).parent.name: r.state for r in out.runs} == {"a": "failed", "b": "finished"}
    assert (b / files().run_name(1) / "b.txt").exists()
    rides = {record_of(r, "launched").job for r in (a / files().run_name(1), b / files().run_name(1))}
    assert rides == {folders.launch_record(ctx(), batch).value.job}
    assert "../../b starts" in (batch / files().name("launch_log")).read_text()


def test_a_sequence_whose_geometry_failed_for_one_case_makes_the_other_cases_meshes(here, tmp_path):
    """Fails if a sequence's walk does not launch each part in turn inside its job, in femkit's
    control environment entered by the record's activation, or a part's member whose shared input
    did not finish is not left out while the others run; or a part's runs ride another job than
    the sequence's (jobs.md §§ 1.2, 4.2; plan § 4, X's acceptance)."""
    runs_ = tmp_path / "runs"
    for n, command in ((1, "exit 1\n"), (2, "echo g2 > g.txt\n")):
        calculation(runs_ / f"g{n}", command, outputs=["g.txt"], check=["{python}", "check.py"],
                    files={"check.py": a_check(None, ["g.txt"])})
    for n in (1, 2):
        calculation(runs_ / f"m{n}", 'cat "$2" > m.txt\n', command=["ElmerSolver", "case.sif", "{share:g.txt}"],
                    shares=[{"folder": f"../g{n}", "file": "g.txt"}])
    launch_folder(runs_ / "launch" / "geometries-001", "members", ["../../g1", "../../g2"])
    launch_folder(runs_ / "launch" / "meshes-001", "members", ["../../m1", "../../m2"])
    seq = launch_folder(runs_ / "launch" / "mesh-001", "sequence", ["../geometries-001", "../meshes-001"])
    prepared(seq)
    out = launched(seq, foreground=True)
    log = (seq / files().name("launch_log")).read_text()
    assert out.closed, log
    states = {Path(r.run).parent.name: r.state for r in out.runs}
    assert states == {"g1": "failed", "g2": "finished", "m2": "finished"}, log
    assert runs.runs(ctx(), runs_ / "m1") == [] and (runs_ / "m2" / files().run_name(1) / "m.txt").read_text() == "g2\n"
    job = folders.launch_record(ctx(), seq).value.job
    assert {record_of(Path(r.run), "launched").job for r in out.runs} == {job}
