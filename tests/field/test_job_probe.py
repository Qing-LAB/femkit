"""`job probe` on this machine, with its real manager and scheduler (jobs.md § 9; testing.md § 1).

On a workstation it reads the host; on a cluster's login node it reads SLURM's own answers,
which is where the scheduler readers are tested — their output names the site, so none is
committed (jobs.md § 7). It writes only into the test's own configuration directory.
"""

from __future__ import annotations

import platform

from femkit.config.operations import ConfigSet
from femkit.core.operations import Context
from femkit.jobs import record
from femkit.jobs.operations import JobProbe
from femkit.jobs.record import Record


def test_the_probe_reads_this_machine_and_its_record_survives_the_disk():
    """Fails if the probe cannot read this machine into a record that loads, cannot write it
    as `job probe --write` does, or — on a machine with a scheduler — reads no partition, no
    node group, or a queue on a partition it did not read."""
    for key, value in (("activation.preamble", "[]"), ("activation.command", '"source activate"')):  # a record needs them
        setting = Context.from_process()                    # each command its own context, as on the command line
        ConfigSet.apply(ConfigSet.plan(ConfigSet.request(key=key, value=value), setting), setting)
    ctx = Context.from_process()
    plan = JobProbe.plan(JobProbe.request(name="probe-test", write=True), ctx)
    outcome = JobProbe.apply(plan, ctx)
    assert outcome.ok() and outcome.file == str(record.path("probe-test")), outcome.text()
    r = record.read(record.path("probe-test"))
    assert Record.model_validate(outcome.record) == r
    assert r.host.architecture == platform.machine()
    said = "; ".join(r.notes + [f"{w}: {why}" for w, why in record.unknowns(r)])
    if r.scheduler.commands:
        assert isinstance(r.identity, str), said
        assert isinstance(r.partitions, dict) and r.partitions, said
        assert any(p.node_groups for p in r.partitions.values()), said
        assert all(g.count > 0 for p in r.partitions.values() for g in p.node_groups)
        assert isinstance(r.queues, list) and r.queues, said
        assert {q.partition for q in r.queues} <= set(r.partitions)
    else:
        assert r.partitions == {} and r.queues == []
