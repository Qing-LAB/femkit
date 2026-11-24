"""User configuration operations (config.md § 3)."""

from __future__ import annotations

import pytest

from tests.kit import apply, planned, refused, run
from femkit.config import probe, settings
from femkit.core import dirs
from femkit.core.operations import Context
from femkit.core.errors import UsageError
from femkit.core.schema import DefinitionError
from femkit.definitions.catalogue import load_schedulers

# Every measured key given, so no measurement runs (basic tier).
GIVEN = {"cuda_architectures": ["80"], "mpi": ["mpirun", "-np", "{ranks}"]}


def init(**fields):
    return apply("config.init", **{**GIVEN, **fields})


def test_init_adds_only_missing_keys_and_never_replaces_a_value():
    """Fails if re-running init replaces what a person set (config.md § 3.2)."""
    init(jobs=4)
    ctx = Context.from_process()
    apply("config.set", key="build.jobs", value="12")
    outcome = init(jobs=2, preamble=["module load x"])
    rows = {r.key: r for r in outcome.rows}
    assert rows["build.jobs"].status == "kept" and rows["build.jobs"].value == 12
    assert rows["activation.preamble"].status == "added"
    assert settings.load(Context.from_process()).config.build.jobs == 12


@pytest.mark.parametrize("request_, refusal", [
    ({"key": "launch.mpi", "value": '["mpirun", "-np", "4"]'}, ("invalid-value", "launch.mpi")),  # no {ranks}
    ({"key": "launch.mpirun", "value": '["mpirun"]'}, ("invalid-request", "config.set")),         # no such key
], ids=["a launcher without {ranks}", "a key config.toml has not"])
def test_an_invalid_value_or_key_is_refused_before_anything_is_written(request_, refusal):
    """Fails if config set writes a value the model rejects, or takes a key the file has not —
    the key a closed set in its request's schema, as a form built from it shows (config.md § 3.1)."""
    with refused(UsageError, *refusal):
        planned("config.set", **request_)
    assert not settings.config_file().exists()


def test_a_value_is_toml_text_and_a_bare_word_is_refused():
    """Fails if config set guesses that a bare word is text, reads TOML text otherwise than
    the file would, or fails on a value of the wrong type instead of refusing it — here `true`
    for a number (config.md § 3, web.md § 7.3)."""
    ctx = Context.from_process()
    with refused(UsageError, "not-toml", "/data/projects"):
        planned("config.set", key="web.projects", value="/data/projects")
    with refused(UsageError, "invalid-value", "build.jobs"):
        planned("config.set", key="build.jobs", value="true")
    apply("config.set", key="web.projects", value='"/data/projects"')
    assert str(settings.load(Context.from_process()).config.web.projects) == "/data/projects"


def test_show_says_where_each_value_came_from_or_what_its_absence_means():
    """Fails if show hides whether a key was set, or loses the unset rule (config.md § 3.2)."""
    init()
    rows = {r.key: r for r in run("config.show").rows}
    assert rows["build.cuda_architectures"].source == "config.toml"
    assert rows["activation.preamble"].source == "unset"
    assert rows["activation.preamble"].unset == settings.key("activation.preamble").unset


def test_init_with_nothing_to_add_still_reports_kept_ignored_and_blocking_keys():
    """Fails if a run of init that adds nothing hides what it kept, a value it ignored, or
    that an unset preamble or activation command blocks jobs (config.md § 3.2)."""
    init(jobs=4)
    plan = planned("config.init", **GIVEN, jobs=2)[1]
    assert plan.steps == ()
    codes = {(i.code, i.subject) for i in plan.issues}
    assert ("key-kept", "build.jobs") in codes
    assert ("value-ignored", "build.jobs") in codes
    assert {("stated-unset", "activation.preamble"), ("stated-unset", "activation.command")} <= codes


@pytest.mark.parametrize("text", [
    "[build\n",                              # not TOML
    "[build]\njobs = 0\n",                   # a value the model rejects
    '[build]\njobs = "8"\n',                 # text where a number belongs
    '[paths]\nenvironments = "envs"\n',      # a place taken from the working directory
])
def test_a_broken_config_file_is_refused_naming_the_file(text):
    """Fails if a config.toml that does not load is used, coerced, or blamed on the
    request instead of refused naming the file (config.md § 2, § 3.1; core.md § 2)."""
    settings.config_file().parent.mkdir(parents=True, exist_ok=True)
    settings.config_file().write_text(text)
    ctx = Context.from_process()
    with pytest.raises(DefinitionError) as caught:
        planned("config.set", key="launch.mpi", value='["mpirun", "-np", "{ranks}"]')
    assert caught.value.file == str(settings.config_file())



def test_a_login_node_with_only_the_submit_command_is_detected_as_its_scheduler(tmp_path, monkeypatch,
                                                                                 tripwire_script):
    """Fails if a scheduler kind is detected only when every command it names is found
    (jobs.md § 9.2): a login node without `sacctmgr` would read as `local`. The stub
    logs to the tripwire log, so running it fails the test."""
    bin_dir = tmp_path / "login-node-bin"
    bin_dir.mkdir()
    submit = bin_dir / "sbatch"
    submit.write_text(tripwire_script)  # located, never run
    submit.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    kind, _why = probe.detect_scheduler(load_schedulers())
    assert kind == "slurm"


def test_config_path_names_each_of_femkits_directories_and_what_chose_it():
    """Fails if `config path` leaves out one of femkit's directories — the runtime one among them —
    or names another rule than the variable that chose it (config.md § 2)."""
    rows = run("config.path").directories
    assert [(r.name, r.rule) for r in rows] == list(dirs.VARIABLES.items())
