"""Machine records: their file, the probe's refusals, and `job machines` (jobs.md § 9).

The probe's measurement starts outside programs, so it is tested where they answer: the
field tier (tests/field/test_job_probe.py). Records here are built from femkit's own model,
never from typed-in scheduler output (testing.md § 2.1).
"""

from __future__ import annotations

import tomllib

import pytest

from tests.kit import a_record, apply, planned, refused, run
from femkit.config import settings
from femkit.core.errors import Unstated, UsageError
from femkit.core.operations import Context
from femkit.core.persist import write_toml
from femkit.core.schema import DefinitionError, validate
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


@pytest.mark.parametrize("fields, refusal", [
    ({"write": True, "name": "local"}, (UsageError, "reserved-name", "local")),     # local is this machine's own record
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


@pytest.mark.parametrize("command, hook_on_disk, expected", [
    ("source activate", True, ["source activate {p}"]),                      # the script: never the hook
    ("conda activate", True, ["source {root}/etc/profile.d/conda.sh", "conda activate {p}"]),
    ("conda activate", False, ["conda activate {p}   # no hook file at {root}/etc/profile.d/conda.sh: "
                               "`conda activate` needs the manager's hook sourced first"]),
    ("mamba activate", True, ["mamba activate {p}   # not one of the conda kind's forms"]),
], ids=["source activate", "conda activate", "no hook file", "another kind's"])
def test_the_entry_is_the_activation_the_person_stated(command, hook_on_disk, expected, tmp_path, monkeypatch):
    """Fails if the entry line follows what is on disk instead of the activation stated for this
    machine: a cluster's module may ship a hook file while its batch shells enter with
    `source activate` (config.md § 3.1; envs.md § 6.2)."""
    root, prefix = tmp_path / "root", tmp_path / "env"
    if hook_on_disk:
        (root / "etc" / "profile.d").mkdir(parents=True)
        (root / "etc" / "profile.d" / "conda.sh").write_text("")
    # conda 26.7.1's `info --json` answer, measured, cut to the one key the kind file reads
    m = answering(root / "bin" / "conda", {"root_prefix": str(root)}, monkeypatch)
    assert m.activation(prefix, command) == [e.format(p=prefix, root=root) for e in expected]


def test_a_changed_record_names_each_value_that_changed_as_a_person_reads_it():
    """Fails if a re-probe's changes print a queue, or any list of parts, as program text
    instead of naming the one value that changed (jobs.md § 9.2)."""
    old = a_record()
    queue = {**old.data()["queues"][0], "max_time": "2-00:00:00"}
    new = a_record(queues=[queue], host={**old.data()["host"], "gpus": {"unknown": "nvidia-smi printed nothing"}})
    assert record.differences(old, new) == [
        "host.gpus: unknown (nvidia-smi not found on PATH) -> unknown (nvidia-smi printed nothing)",
        "queues[0].max_time: 1-00:00:00 -> 2-00:00:00"]
