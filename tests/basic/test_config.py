"""User configuration operations (config.md § 3)."""

from __future__ import annotations

import re

import pytest

from tests import kit
from tests.kit import apply, planned, refused, run
from femkit.config import probe, settings
from femkit.core import dirs
from femkit.core.operations import Context
from femkit.core.errors import UsageError
from femkit.core.persist import key_comments
from femkit.core.schema import DefinitionError
from femkit.definitions.catalogue import load_schedulers

# Every measured key given, so no measurement runs (basic tier).
GIVEN = {"cuda_architectures": ["80"], "mpi": ["mpirun", "-np", "{ranks}"]}


def init(**fields):
    return apply("config.init", **{**GIVEN, **fields})


def test_init_writes_each_key_directly_under_the_line_showing_it():
    """Fails if config init writes a key away from its help: appended at its table's end, where
    the next table's help stands (config.md § 3.2)."""
    init(projects="/data/projects", jobs=4, preamble=["module load x"], command="source activate")
    entries = key_comments(settings.config_file().read_text())
    shown = {e.path: e.line for e in entries if e.shown}
    written = {e.path: e.line for e in entries if not e.shown and not e.header}
    assert len(written) == 6 and all(line == shown[path] + 1 for path, line in written.items())


def test_init_adds_only_missing_keys_and_never_replaces_a_value():
    """Fails if re-running init replaces what a person set (config.md § 3.2)."""
    init(jobs=4)
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
    for a number; or if the refusal of a bare word is about the word rather than the key, or does
    not give, as its next step, the command again with the word in quotes where the key takes that
    text, and only there (config.md § 3.2: "a bare word is refused, never guessed to be text";
    core.md § 9: a refusal's subject is "what it is about: a setting", and "its next steps say
    what to do"; web.md § 7.3)."""
    with refused(UsageError, "not-toml", "paths.projects") as caught:
        planned("config.set", key="paths.projects", value="/data/projects")
    (again,) = caught.value.next
    assert again.call.operation == "config.set"
    assert again.call.request == {"key": "paths.projects", "value": '"/data/projects"'}
    with refused(UsageError, "not-toml", "build.jobs") as caught:
        planned("config.set", key="build.jobs", value="eight")       # no text fits: no quoted command
    assert caught.value.next == ()
    with refused(UsageError, "invalid-value", "build.jobs"):
        planned("config.set", key="build.jobs", value="true")
    apply("config.set", **again.call.request)
    assert str(settings.load(Context.from_process()).config.paths.projects) == "/data/projects"


def test_config_writes_its_file_and_a_path_it_holds_from_home(tmp_path, monkeypatch):
    """Fails if `config set`, `config show` or `config path` writes, in the text a person reads, a
    path under the home folder otherwise than from `~` — the file it wrote or read, a path a key
    holds, a directory — or gives a program anything but the full path in its JSON (api.md § 4.4:
    "Paths under the home directory are written from `~`"; config.md §§ 2, 3.2)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    file = settings.config_file()
    assert file.is_relative_to(tmp_path)
    said = apply("config.set", key="paths.projects", value=f'"{tmp_path / "projects"}"').text()
    assert said.endswith(f"in ~/{file.relative_to(tmp_path)}") and str(tmp_path) not in said
    shown = run("config.show")
    held = shown.model_dump(mode="json")
    assert held["file"] == str(file)
    assert {r["key"]: r["value"] for r in held["rows"]}["paths.projects"] == str(tmp_path / "projects")
    text = shown.text()
    assert f"read ~/{file.relative_to(tmp_path)}" in text and "~/projects" in text and str(tmp_path) not in text
    listed = run("config.path")
    assert {d.name: d.path for d in listed.directories}["config"] == str(dirs.config_dir())
    assert f"~/{dirs.config_dir().relative_to(tmp_path)}" in listed.text() and str(tmp_path) not in listed.text()


def test_what_a_keys_absence_blocks_names_only_commands_femkit_has():
    """Fails if what a key's absence means, as `config show` prints it, names a command femkit
    does not have — `job prepare`, not built yet — or an option that command does not take
    (config.md § 3.1: "its absence has the one consequence its field states"; api.md § 4.4)."""
    have = kit.commands()
    named = [span.split() for k in settings.keys() for span in re.findall(r"`([^`]+)`", k.unset)]
    assert named
    for words in named:
        command = next((tuple(words[:n]) for n in range(len(words), 0, -1) if tuple(words[:n]) in have), None)
        assert command is not None, words
        assert {w for w in words[len(command):] if w.startswith("-")} <= have[command], words


def test_show_says_where_each_value_came_from_or_what_its_absence_means():
    """Fails if show hides whether a key was set, or loses the unset rule (config.md § 3.2)."""
    init()
    rows = {r.key: r for r in run("config.show").rows}
    assert rows["build.cuda_architectures"].source == "config.toml"
    assert rows["activation.preamble"].source == "unset"
    assert rows["activation.preamble"].unset == settings.key("activation.preamble").unset


def test_show_carries_its_report_a_table_naming_each_key():
    """Fails if `config show`'s JSON lacks the report the page draws, or its table leaves out a
    key or the value the file holds (web.md § 7.6, api.md § 2.3)."""
    init()
    report = run("config.show").model_dump(mode="json")["report"]
    (table,) = [b for b in report["blocks"] if b["kind"] == "table"]
    rows = {row["key"]: row for row in table["rows"]}
    assert list(rows) == [k.dotted for k in settings.keys()]
    assert rows["build.cuda_architectures"]["value"] == "80"


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


def test_a_step_stating_what_the_person_alone_knows_asks_for_it_one_step_a_form():
    """Fails if a step that states a key only the person knows — how this machine enters an
    environment — writes the key's example as if it were their value (`--preamble 'module load
    mamba'`), or lists the alternatives of one key each as a step of its own (`--activation
    'source activate'`, `--activation 'conda activate'`, …), rather than one step for each form of
    the command, each asking for its value (workflow.md § 7: "never an example written as if it
    were theirs"; config.md § 3.2: "naming the options, one step for each form of the command")."""
    plan = planned("config.init", **GIVEN)[1]
    steps = {i.subject: i.next for i in plan.issues if i.code == "stated-unset"}
    preamble, command = steps["activation.preamble"], steps["activation.command"]
    assert [(s.call.request, [f.field for f in s.fills]) for s in preamble] == [({}, ["preamble"]),
                                                                                 ({"no_preamble": True}, [])]
    (asking,) = command
    assert (asking.call.request, [f.field for f in asking.fills]) == ({}, ["command"])
    for key, step in (("activation.preamble", preamble[0]), ("activation.command", asking)):
        example = settings.key(key).example
        assert all(str(v) not in step.command for v in (example if isinstance(example, list) else [example]))


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


def test_a_settings_step_is_chosen_from_its_fields_declaration():
    """Fails if the step that states a key another command needs is chosen otherwise than by the
    key's field: `config init`, once, for the keys it asks for (`ask`) — `paths.projects` and the
    activation among them — and `config set`, its value to fill, for one it proposes but cannot here
    (`propose`), `launch.mpi` (config.md § 3.2: "a setting's next step is built in one place … its
    step is `config init` … a key `config init` proposes but cannot here … is `config set`")."""
    def said(keys):
        return [(a.call.operation, a.call.request, [f.field for f in a.fills]) for a in settings.steps(keys)]
    assert said(["paths.projects"]) == [("config.init", {}, [])]
    assert said(["activation.preamble", "activation.command"]) == [("config.init", {}, [])]
    assert said(["launch.mpi"]) == [("config.set", {"key": "launch.mpi"}, ["value"])]
    assert said(["activation.command", "build.cuda_architectures"]) == [
        ("config.init", {}, []), ("config.set", {"key": "build.cuda_architectures"}, ["value"])]


def test_a_settings_value_to_fill_takes_the_keys_own_schema_so_a_list_is_given_as_a_list():
    """Fails if `config set`'s value to fill, for a key holding a list, does not carry the key's own
    schema fragment — a list — so the page would ask for one text and write a list key as a string
    (web.md § 7.3: "`json_schema` is a self-contained JSON schema fragment of what it may hold";
    config.md § 3.1; the fill's `toml` says the request takes it as TOML text)."""
    from femkit.config import settings
    (step,) = settings.setting(["launch.mpi"])
    (fill,) = step.fills
    assert any(s.get("type") == "array" for s in fill.json_schema.get("anyOf", [fill.json_schema]))
    assert fill.toml == "whole"
