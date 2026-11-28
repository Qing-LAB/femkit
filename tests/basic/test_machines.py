"""Machine records: their file, the probe's refusals, and `job machines` (jobs.md § 9).

The probe's measurement starts outside programs, so it is tested where they answer: the
field tier (tests/field/test_job_probe.py); here only on a machine whose programs are
stand-ins that print nothing of a real one's — a manager that answers nothing, an
`nvidia-smi` that finds no GPU, no scheduler command on PATH. Records here are built from
femkit's own model, never from typed-in scheduler output (testing.md § 2.1).
"""

from __future__ import annotations

from dataclasses import replace

import tomllib
from pathlib import Path

import pytest

from tests.kit import (NO_GPU, a_record, ahead, apply, made, planned, refused, run, tripwire_names,
                       workstation)  # noqa: F401 -- workstation: a fixture
from femkit.config import settings
from femkit.config.probe import GPU_QUERY
from femkit.core import dirs, eventlog
from femkit.core.errors import Unstated, UsageError
from femkit.core.operations import Context
from femkit.core.persist import write_toml
from femkit.core.schema import DefinitionError, load_text, validate
from femkit.definitions.catalogue import CatalogueError, load_schedulers
from femkit.definitions.models import SchedulerKind
from femkit.jobs import record
from femkit.jobs.record import Unknown


def test_a_record_survives_the_disk_with_its_three_answers():
    """Fails if writing and reading a record loses a value: TOML has no null, so `unlimited`,
    an unknown with its reason, an absent QOS and a wall in the scheduler's spelling must
    each come back as written (jobs.md § 9.1)."""
    r = a_record(queues=[{"partition": "p1", "max_time": "unlimited", "max_cpus": {"unknown": "no QOS"},
                          "max_memory_mib": {"unknown": "no QOS"}, "max_gpus": {"unknown": "no QOS"},
                          "max_submit_jobs_per_user": {"unknown": "no QOS"}}])
    back = record.read(record.write(record.path("cluster-a"), r))
    assert back == r
    assert back.queues[0].qos is None and back.queues[0].max_time == "unlimited"
    assert isinstance(back.host.gpus, Unknown) and back.partitions["p1"].max_cpus_per_node == "unlimited"


def test_a_record_of_another_schema_version_does_not_load_and_names_its_version():
    """Fails if a record written by another femkit loads, or its refusal does not say which
    version it is and what rewrites it (jobs.md § 9.1)."""
    file = record.path("old")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("schema = 0\n")
    with pytest.raises(DefinitionError) as caught:
        record.read(file)
    assert caught.value.problems[0][0] == "schema" and "0" in caught.value.problems[0][1]


def test_job_machines_lists_every_record_marking_one_that_does_not_load():
    """Fails if a record that does not load is skipped instead of listed and marked: a
    skipped record looks exactly like one never copied (jobs.md § 9.3)."""
    record.write(record.path("cluster-a"), a_record())
    broken = record.path("cluster-b")
    broken.write_text("schema = 1\nidentity = \n")
    rows = {r.name: r.status for r in run("job.machines").rows}
    assert rows == {"cluster-a": "ok", "cluster-b": "does not load"}


@pytest.mark.parametrize("identity", ["this-host", {"unknown": "the host name printed nothing"}],
                         ids=["known", "unknown"])
def test_only_a_record_of_this_machine_is_compared_with_its_config(identity):
    """Fails if `local` is not marked stale when this machine's settings changed, or if
    another machine's record is compared with this machine's config.toml — two identities
    neither probe could read name no machine (jobs.md § 9.3)."""
    apply("config.init", no_preamble=True, cuda_architectures=["80"], mpi=["mpirun", "-np", "{ranks}"])
    ctx = Context.from_process()
    here = record.settings_now(settings.load(ctx, fresh=True).config)
    record.write(record.path("local"), a_record(identity=identity, settings=here.model_dump(exclude_none=True)))
    other = identity if isinstance(identity, dict) else "cluster-a"
    record.write(record.path("cluster-a"), a_record(identity=other))  # not this machine's settings: never compared
    ctx = Context.from_process()
    assert {r.name: r.status for r in run("job.machines").rows} == {"cluster-a": "ok", "local": "ok"}
    apply("config.set", key="activation.preamble", value='["module load y"]')
    ctx = Context.from_process()
    assert {r.name: r.status for r in run("job.machines").rows} == {"cluster-a": "ok", "local": "stale"}


def test_a_stale_record_of_this_machine_offers_the_probe_that_writes_it_again_under_its_own_name():
    """Fails if `job machines` offers, for a stale record of this machine, a probe that would write
    another record than it: `local` is the probe's own default, any other name is given with
    `--name` (jobs.md § 9.3)."""
    apply("config.init", no_preamble=True, cuda_architectures=["80"], mpi=["mpirun", "-np", "{ranks}"])
    here = record.settings_now(settings.load(Context.from_process(), fresh=True).config)
    for name in ("local", "workstation"):                          # both this machine's, by its identity
        record.write(record.path(name), a_record(identity="this-host", settings=here.model_dump(exclude_none=True)))
    apply("config.set", key="activation.preamble", value='["module load y"]')
    offered = {i.subject: [n.command for n in i.next] for i in run("job.machines").issues if i.code == "stale"}
    assert offered == {"local": ["femkit job probe --write"],
                       "workstation": ["femkit job probe --write --name workstation"]}


@pytest.mark.parametrize("fields, refusal", [
    ({"write": True, "name": "local"}, (UsageError, "invalid-request", "job.probe")),  # local: this machine's own record
    ({"write": True}, (Unstated, "setting-unset", "activation.preamble, activation.command")),  # the activation unset
    ({"set": ["partitions.p1.max_time=1:00:00"]}, (UsageError, "invalid-request", "job.probe")),  # only command paths
    ({"set": ["scheduler.commands.submit"]}, (UsageError, "invalid-request", "job.probe")),        # not KEY=VALUE
    ({"set": ["scheduler.commands.sumbit=/opt/x"], "scheduler": "slurm"}, (UsageError, "no-such-role", "scheduler.commands.sumbit")),
    ({"name": "../elsewhere"}, (UsageError, "invalid-request", "job.probe")),     # a name is a file name, nothing more
])
def test_the_probe_refuses_before_it_measures(fields, refusal):
    """Fails if `job probe` measures (and so starts outside programs — the tripwires catch
    it) before refusing what it can tell from the request, the kind and config.toml — or if a
    request its schema does not admit gets past the schema (jobs.md § 9.2, framework.md § 4)."""
    with refused(*refusal):
        planned("job.probe", **fields)


@pytest.mark.parametrize("name, text, where", [
    ("pbs", 'mpi_launch = ["mpirun", "-np", "{ranks}"]\n[commands]\nsubmit = "qsub"\n'
            '[job_variables]\nid = "PBS_JOBID"\n', ""),                                      # commands no reader reads
    ("slurm", None, "probe"),                                                               # a role its reader does not read
])
def test_a_scheduler_kind_its_reader_cannot_read_does_not_load(definitions, name, text, where):
    """Fails if a kind file loads with commands no module in femkit/schedulers/ reads, or with
    probe roles other than its reader's — its probe would record every queue as unknown
    (jobs.md § 7)."""
    path = definitions / "schedulers" / f"{name}.toml"
    if text is not None:
        path.write_text(text)
    else:
        data = tomllib.loads(path.read_text())
        write_toml(path, {**data, "probe": {**data["probe"], "nodes": "sinfo"}})
    with pytest.raises(CatalogueError) as refused:
        load_schedulers()
    assert [(e.file, [w for w, _ in e.problems]) for e in refused.value.errors] == [(str(path), [where])]


@pytest.mark.parametrize("data", [
    {"mpi_launch": ["mpirun", "-np", "{ranks}"], "commands": {"submit": "s", "launch": "x"}, "job_variables": {"id": "J"}},
    {"mpi_launch": ["mpirun", "-np", "{ranks}"], "commands": {"query": "q"}, "job_variables": {"id": "J"}},
    {"mpi_launch": ["mpirun", "-np", "{ranks}"], "commands": {"submit": "s"}},
    {"mpi_launch": ["mpirun", "-np", "{ranks}"], "commands": {"submit": "s"}, "job_variables": {"id": "J", "cpus": "C"}},
])
def test_a_scheduler_kind_names_only_femkits_roles_and_its_submit_and_job_id(data):
    """Fails if a kind file loads with a role femkit does not know, or with commands but no
    submit command or no job-ID variable (jobs.md § 7)."""
    with refused(DefinitionError, "definition-invalid", "kind.toml"):
        validate(SchedulerKind, data, "kind.toml")


def answering(executable, answer: dict, monkeypatch):
    """The manager femkit resolves when FEMKIT_ENV_MANAGER names ``executable``: a stand-in of that
    kind that prints ``answer`` to whatever it is asked (envs.md § 7.1)."""
    import json
    import shlex
    from femkit.envs import manager
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(f"#!/bin/sh\nprintf '%s' {shlex.quote(json.dumps(answer))}\n")
    executable.chmod(0o755)
    monkeypatch.setenv(manager.VARIABLE, str(executable))
    return manager.resolve(Context.from_process())


@pytest.mark.parametrize("answer", [{"root_prefix": "/r", "platform": "linux-64"},  # mamba 1.5.9
                                    {"base environment": "/r", "platform": "linux-64"}],  # mamba 2.9.0
                         ids=["mamba 1", "mamba 2"])
def test_the_mamba_kind_reads_its_root_from_either_versions_answer(answer, tmp_path, monkeypatch):
    """Fails if the mamba kind finds its root under one version's key only: 1.x answers
    `root_prefix`, 2.x `base environment` (definitions.md § 6; both measured)."""
    m = answering(tmp_path / "bin" / "mamba", answer, monkeypatch)
    assert m.query(m.kind.root) == ("/r", None)


@pytest.mark.parametrize("command, manager_there, expected", [
    ("source activate", True, ["source activate {p}"]),                      # the script: never the hook
    ("conda activate", True, ['eval "$({exe} shell.bash hook)"', "conda activate {p}"]),
    ("conda activate", False, ["conda activate {p}   # no manager at {exe}: `conda activate` needs its hook "
                               "evaluated first"]),
    ("mamba activate", True, ["mamba activate {p}   # not one of the conda kind's forms"]),
], ids=["source activate", "conda activate", "no manager there", "another kind's"])
def test_the_entry_is_the_activation_the_person_stated(command, manager_there, expected, tmp_path, monkeypatch):
    """Fails if the entry line follows what is on disk instead of the activation stated for this
    machine: a cluster's module may ship a hook file while its batch shells enter with
    `source activate` (config.md § 3.1; envs.md § 6.2); if the shell function's form loads its hook
    otherwise than from the manager it knows, by the manager's own way — never a file guessed from
    where the manager lies (definitions.md § 6); or if it enters the environment other than by its
    name with the manager (envs.md § 1)."""
    prefix = "femkit-gmsh"
    m = answering(tmp_path / "root" / "bin" / "conda", {"root_prefix": str(tmp_path / "root")}, monkeypatch)
    if not manager_there:
        m = replace(m, path=tmp_path / "gone" / "conda")
    assert m.activation(prefix, [], command) == [e.format(p=prefix, exe=m.path) for e in expected]


def test_a_changed_record_names_each_value_that_changed_as_a_person_reads_it():
    """Fails if a re-probe's changes print a queue, or any list of parts, as program text
    instead of naming the one value that changed (jobs.md § 9.2)."""
    old = a_record()
    queue = {**old.data()["queues"][0], "max_time": "2-00:00:00"}
    new = a_record(queues=[queue], host={**old.data()["host"], "gpus": {"unknown": "nvidia-smi printed nothing"}})
    assert record.differences(old, new) == [
        "host.gpus: unknown (nvidia-smi not found on PATH) -> unknown (nvidia-smi printed nothing)",
        "queues[0].max_time: 1-00:00:00 -> 2-00:00:00"]


def test_a_record_that_is_not_toml_is_said_as_every_declared_file_is():
    """Fails if a machine record that is not TOML is read by another reader than the one every
    declared file is read by, so tomllib's own words reach the person instead of why, in plain
    words, at its line (core.md § 2: "One TOML reader")."""
    text = 'identity = "cluster-a\n'
    file = record.path("cluster-a")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    with pytest.raises(DefinitionError) as caught:
        record.read(file)
    with pytest.raises(DefinitionError) as expected:
        load_text(text, record.Record, file)
    assert caught.value.problems == expected.value.problems


def test_job_machines_names_the_probe_that_rewrites_a_record_that_does_not_load():
    """Fails if `job machines` lists a record that does not load without the one next step the
    record's state allows — `job probe --write`, with `--name` for a record named other than
    `local` — observed by `femkit/data/states/record.toml`, not decided apart (jobs.md § 9.3)."""
    for name in ("local", "cluster-b"):
        record.path(name).parent.mkdir(parents=True, exist_ok=True)
        record.path(name).write_text("schema = 1\nidentity = \n")
    result = run("job.machines")
    assert {r.name: r.status for r in result.rows} == {"local": "does not load", "cluster-b": "does not load"}
    offered = {i.subject: [n.command for n in i.next] for i in result.issues if i.code == "unloadable"}
    assert offered == {"local": ["femkit job probe --write"], "cluster-b": ["femkit job probe --write --name cluster-b"]}


def test_job_machines_says_beside_an_environment_that_it_is_otherwise_here_now():
    """Fails if `job machines NAME`, for a record of this machine, does not say beside an
    environment that `env list` reports it otherwise now, naming `job probe --write`, or calls the
    record stale for it (jobs.md § 9.3: "When only its environments differ … it is not stale;
    preparation and `job machines NAME` say so beside the environment")."""
    apply("config.init", no_preamble=True, command="source activate", cuda_architectures=["80"],
          mpi=["mpirun", "-np", "{ranks}"])
    here = record.settings_now(settings.load(Context.from_process(), fresh=True).config)
    record.write(record.path("local"), a_record(settings=here.model_dump(exclude_none=True)))   # ngsolve ready there
    result = run("job.machines", name="local")
    assert result.rows[0].status == "ok" and result.now == {"ngsolve": ("ready", "absent")}
    (said,) = [i for i in result.issues if i.code == "environments-changed"]
    assert [n.command for n in said.next] == ["femkit job probe --write"]
    m = record.machine(Context.from_process())     # the step is the record table's own row for its state
    assert [n.label for n in said.next] == [a.describe for a in m.allowed(m.states.current).values()]


def test_job_machines_shows_every_part_of_a_record():
    """Fails if `job machines NAME` leaves out a part of the record it shows — a setting it
    copied, a queue's memory cap or `MaxSubmitJobsPerUser`, a partition's policy (jobs.md § 9.1:
    each part; § 9.3: "`job machines NAME` prints one record with the source of each fact")."""
    copied = {"activation": {"preamble": [], "command": "source activate"}}
    record.write(record.path("cluster-a"), a_record(settings=copied))
    report = run("job.machines", name="cluster-a").report.model_dump(mode="json")
    rows = [row for b in report["blocks"] if b["kind"] == "table" for row in b["rows"]]
    shown = {row["key"]: row["value"] for row in rows if "key" in row}
    assert shown["activation.command"] == "source activate" and set(record.COPIED) <= set(shown)
    (queue,) = [row for row in rows if "qos" in row]
    assert queue["max_memory_mib"] == "unlimited" and queue["max_submit_jobs_per_user"] == "unlimited"
    (partition,) = [row for row in rows if "policy" in row]
    assert "MaxCPUsPerNode unlimited" in partition["policy"] and "DefMemPerCPU 2048 MiB" in partition["policy"]


def test_whether_the_manager_runs_inside_a_prefix_is_unknown_when_running_it_failed(manager_doing, workstation):
    """Fails if `run_enters` reads `false` when `<manager> run` failed — a failure says nothing of
    where it would run — instead of unknown with the reason (jobs.md § 9.1: "Every other fact is
    a value or `unknown` with its reason")."""
    manager_doing('  "run --no-capture-output") echo "the prefix is locked" >&2; exit 3 ;;')
    made(dirs.CONTROL)
    enters = apply("job.probe").record.manager.run_enters
    assert isinstance(enters, Unknown) and "exit 3" in enters.unknown and "the prefix is locked" in enters.unknown


def test_a_probe_that_writes_nothing_names_the_log_it_wrote(manager, workstation):
    """Fails if `job probe` without `--write` — a plan of no steps, still applied — answers with no
    log, though it wrote its operation's event log (api.md § 3: "it changes nothing, writes an
    event log of no steps, and returns the operation's outcome")."""
    outcome = apply("job.probe")
    assert outcome.log and (Path(outcome.log) / eventlog.FILE).is_file()


def test_a_declared_submit_command_detects_its_scheduler_kind(manager, tmp_path, monkeypatch, tripwire_dir):
    """Fails if `job probe --set scheduler.commands.submit=PATH` without `--scheduler` is refused,
    on a login node whose submit command is a site's own wrapper, not on PATH: a kind with
    commands is detected when its submit command is found or declared (jobs.md § 9.2)."""
    scheduler = {name for kind in load_schedulers().values() for name in (*kind.commands.values(), *kind.probe.values())}
    own = tmp_path / "login-node"
    own.mkdir()
    for name in tripwire_names() - scheduler - {GPU_QUERY[0]}:   # every other program still a tripwire
        (own / name).symlink_to(tripwire_dir / name)
    ahead(own, monkeypatch, {GPU_QUERY[0]: NO_GPU}, path="/usr/bin:/bin")
    wrapper = "/opt/site/bin/submit"
    r = apply("job.probe", set=[f"scheduler.commands.submit={wrapper}"]).record
    assert (r.scheduler.kind, r.scheduler.commands["submit"]) == ("slurm", wrapper)
