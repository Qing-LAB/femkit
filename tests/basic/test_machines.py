"""Machine records: their file, the probe's refusals, and `job machines` (jobs.md § 9).

The probe's measurement starts outside programs, so it is tested where they answer: the
field tier (tests/field/test_job_probe.py). Records here are built from femkit's own model,
never from typed-in scheduler output (testing.md § 2.1).
"""

from __future__ import annotations

import pytest

from femkit import schedulers
from femkit.config import settings
from femkit.config.operations import ConfigInit, ConfigSet
from femkit.core.errors import Refusal, UsageError
from femkit.core.operations import Context
from femkit.core.schema import DefinitionError, validate
from femkit.definitions.catalogue import load_schedulers
from femkit.definitions.models import SchedulerKind
from femkit.jobs import record
from femkit.jobs.operations import JobProbe, job_machines
from femkit.jobs.record import Record, Unknown


def a_record(**changes) -> Record:
    """A cluster's record with every kind of value: numbers, `unlimited`, unknowns, walls."""
    data = {
        "schema": 1,
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
        "settings": {"environments": "/scratch/envs", "preamble": ["module load x"]},
        "sources": {"partitions": "scontrol show partition, scontrol show node"},
        "notes": [],
    }
    data.update(changes)
    return Record.model_validate(data)


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
    rows = {r.name: r.status for r in job_machines.run(job_machines.request(), Context.from_process()).rows}
    assert rows == {"cluster-a": "ok", "cluster-b": "does not load"}


def test_only_a_record_of_this_machine_is_compared_with_its_config():
    """Fails if `local` is not marked stale when this machine's settings changed, or if
    another machine's record is compared with this machine's config.toml (jobs.md § 9.3)."""
    ctx = Context.from_process()
    ConfigInit.apply(ConfigInit.plan(ConfigInit.request.model_validate(
        {"no_preamble": True, "cuda_architectures": ["80"], "mpi": ["mpirun", "-np", "{ranks}"]}), ctx), ctx)
    here = record.settings_now(settings.load(ctx, fresh=True).config)
    record.write(record.path("local"), a_record(identity="this-host", settings=here.model_dump(exclude_none=True)))
    record.write(record.path("cluster-a"), a_record())  # its settings are not this machine's, and never compared
    ctx = Context.from_process()
    assert {r.name: r.status for r in job_machines.run(job_machines.request(), ctx).rows} == {"cluster-a": "ok", "local": "ok"}
    ConfigSet.apply(ConfigSet.plan(ConfigSet.request(key="activation.preamble", value='["module load y"]'), ctx), ctx)
    ctx = Context.from_process()
    assert {r.name: r.status for r in job_machines.run(job_machines.request(), ctx).rows} == {"cluster-a": "ok", "local": "stale"}


@pytest.mark.parametrize("fields, refusal", [
    ({"write": True, "name": "local"}, UsageError),          # local is this machine's own record
    ({"write": True}, Refusal),                               # activation.preamble unset
    ({"set": ["partitions.p1.max_time=1:00:00"]}, UsageError),  # only command paths are declarable
    ({"name": "../elsewhere"}, UsageError),                   # a name is a file name, nothing more
])
def test_the_probe_refuses_before_it_measures(fields, refusal):
    """Fails if `job probe` measures (and so starts outside programs — the tripwires catch
    it) before refusing what it can tell from the request and config.toml (jobs.md § 9.2)."""
    with pytest.raises(refusal):
        JobProbe.plan(JobProbe.request.model_validate(fields), Context.from_process())


def test_every_scheduler_kind_with_commands_has_readers():
    """Fails if a kind file names commands that no module in femkit/schedulers/ can read
    (jobs.md § 7): its probe would record every queue as unknown."""
    kinds = {name for name, kind in load_schedulers().items() if kind.commands}
    assert kinds <= schedulers.registered()


@pytest.mark.parametrize("data", [
    {"mpi_launch": ["mpirun", "-np", "{ranks}"], "commands": {"submit": "s", "launch": "x"}, "job_variables": {"id": "J"}},
    {"mpi_launch": ["mpirun", "-np", "{ranks}"], "commands": {"query": "q"}, "job_variables": {"id": "J"}},
    {"mpi_launch": ["mpirun", "-np", "{ranks}"], "commands": {"submit": "s"}},
    {"mpi_launch": ["mpirun", "-np", "{ranks}"], "commands": {"submit": "s"}, "job_variables": {"id": "J", "cpus": "C"}},
])
def test_a_scheduler_kind_names_only_femkits_roles_and_its_submit_and_job_id(data):
    """Fails if a kind file loads with a role femkit does not know, or with commands but no
    submit command or no job-ID variable (jobs.md § 7)."""
    with pytest.raises(DefinitionError):
        validate(SchedulerKind, data, "kind.toml")


@pytest.mark.parametrize("answer", [{"root_prefix": "/r", "platform": "linux-64"},  # mamba 1.5.9
                                    {"base environment": "/r", "platform": "linux-64"}],  # mamba 2.9.0
                         ids=["mamba 1", "mamba 2"])
def test_the_mamba_kind_reads_its_root_from_either_versions_answer(answer, tmp_path):
    """Fails if the mamba kind finds its root under one version's key only: 1.x answers
    `root_prefix`, 2.x `base environment` (definitions.md § 6; both measured)."""
    import json
    from femkit.core.process import ProcessResult
    from femkit.definitions.catalogue import load_managers
    from femkit.envs.manager import Manager
    m = Manager(tmp_path / "mamba", "mamba", load_managers()["mamba"], {})
    argv = tuple(m.argv(m.kind.root.argv))
    m.printed[argv] = ProcessResult(argv=argv, returncode=0, stdout=json.dumps(answer), stderr="", log=None)
    assert m.query(m.kind.root) == ("/r", None)
