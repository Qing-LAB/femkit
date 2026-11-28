"""The run script, `run.sh` (jobs.md § 4), and the walks of a batch (§ 4.1) and a sequence (§ 4.2):
the one place each is rendered.

A calculation folder's script is the closed list `JOB` of fourteen blocks, in order — the person's
earlier, cluster-proven run script's. Each block is a function of what preparation resolved and
returns its lines; nothing else writes a line of the script. It takes no count as an argument:
every count is the request's, written in here. It reads only what the scheduler granted, its own
run directory, which `job launch` has filled, and the files its request shares, by the paths
`job launch` writes into the run's copy of it (`with_shares`). It creates no directory, copies no
file and changes directory nowhere. Before it enters its environment it starts clean, by the lines
the one owner of the clean start writes (`envs/start.py`, envs.md § 4.4), then runs the target's
preamble and its activation of the environment by its name, as the target's record says.

The records it writes — `started.json`, `ended.json`, `checked.json`, `outputs.json` — are written
as the run door reads them (`femkit/jobs/runs.py`), each whole: beside its place, then renamed in.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from femkit.config.probe import GPU_QUERY
from femkit.core import schema
from femkit.core.schema import parsed
from femkit.definitions.models import JOB_ROLES, EnvironmentDefinition, SchedulerKind
from femkit.engines.stages import documents
from femkit.engines.stages.monitor import JOB_STARTED, WALL
from femkit.envs.manager import Entry
from femkit.jobs.layout import Catalogue
from femkit.jobs.request import PYTHON, Resources, Share, wall_seconds

#: The launch-door gate (jobs.md § 4, block 3): `job launch` sets this variable to its claim in the
#: environment of what it starts; a script started without it is refused.
LAUNCHED_BY = "FEMKIT_LAUNCHED_BY"
CLAIM = "femkit job launch"
#: The signals that stop a run, each logged and answered by an exit of 128 + its number with no
#: ended.json; the two that are logged while the run goes on (jobs.md § 4, block 6).
STOP_SIGNALS = ("HUP", "INT", "QUIT", "ALRM", "TERM", "XCPU", "XFSZ", "VTALRM", "PROF")
GOING_ON = ("USR1", "USR2")
#: How long the exit trap waits for the monitor's closing lines, in seconds (jobs.md § 4, block 6).
MONITOR_CLOSE = 10
#: A line of a run script that holds the path of a file the run shares, written in by `job launch`.
SHARED = re.compile(r"^share_(\d+)=('[^']*'|\S*)(  # .*)$", re.M)


def q(word: str | Path) -> str:
    """One word as the shell reads it back unchanged."""
    return shlex.quote(str(word))


@dataclass(frozen=True)
class Target:
    """What a script needs of its target's record (jobs.md § 9.1), resolved by preparation; how it
    enters an environment there is each environment's entry (`Environment.entry`)."""

    name: str                    # the record's name
    kind: SchedulerKind          # its scheduler kind's declaration
    mpi: tuple[str, ...] | None  # launch.mpi, as the record copied it


@dataclass(frozen=True)
class Environment:
    """An environment a script enters, and how: by its name with the manager on the target, which
    keeps it where it keeps its environments (envs.md § 1)."""

    name: str
    managed: str                 # its name with the manager (`catalogue.managed`)
    entry: Entry                 # the lines that enter it: the target's preamble, its activation (`manager.entering`)
    active: str                  # the variable the manager's activation sets to the prefix it entered
    start: tuple[str, ...]       # the clean start, as shell (`envs/start.py`, envs.md § 4.4)


@dataclass(frozen=True)
class Job:
    """A calculation folder's script: one command in one environment (jobs.md § 2)."""

    name: str
    target: Target
    files: Catalogue                     # what each file of the folder and its runs is named (jobs.md § 1.1)
    resources: Resources
    environment: Environment
    definition: EnvironmentDefinition    # its thread and fixed variables (definitions.md § 4.4)
    command: tuple[str, ...]
    check: tuple[str, ...] | None
    outputs: tuple[str, ...]
    shares: tuple[Share, ...]


@dataclass(frozen=True)
class Batch:
    """A batch's walk: each member's own script, in the member's new run, one after another
    (jobs.md § 4.1)."""

    name: str
    target: Target
    files: Catalogue
    resources: Resources
    members: tuple[tuple[str, Path], ...]     # each member as its launch folder names it, and its run


@dataclass(frozen=True)
class Sequence:
    """A sequence's walk: femkit's own `job launch` of each part in turn, inside the job, in
    femkit's control environment (jobs.md § 4.2)."""

    name: str
    target: Target
    files: Catalogue
    resources: Resources
    control: Environment
    folder: Path                              # the launch folder
    parts: tuple[tuple[str, Path], ...]       # each part as the launch folder names it, and its path


Script = Job | Batch | Sequence


# ------------------------------------------------------------------ words

def words(argv: tuple[str, ...] | list[str], shares: tuple[Share, ...]) -> str:
    """A command as the script runs it: each word quoted, `{python}` the environment's own python
    and `{share:FILE}` the shared file's path, both as the script holds them (jobs.md §§ 2, 4)."""
    numbered = {s.file: n for n, s in enumerate(shares, 1)}
    out = []
    for word in argv:
        held, at, parts = parsed(word), 0, []
        for p in held:
            if word[at:p.span[0]]:
                parts.append(q(word[at:p.span[0]]))
            parts.append('"$python"' if p.name == PYTHON else f'"$share_{numbered[p.argument]}"')
            at = p.span[1]
        if word[at:] or not held:
            parts.append(q(word[at:]))
        out.append("".join(parts))
    return " ".join(out)


def launched(argv: tuple[str, ...], s: Job) -> tuple[str, ...]:
    """The command through the target's MPI launcher when it runs more than one rank."""
    if s.resources.ranks == 1:
        return argv
    assert s.target.mpi, "preparation refuses a multi-rank job for a target with no launch.mpi"
    return (*(schema.render(w, {"ranks": str(s.resources.ranks)}) for w in s.target.mpi), *argv)


# ------------------------------------------------------------------ blocks every script has

def log_of(s: Script) -> str:
    return s.files.name("log") if isinstance(s, Job) else s.files.name("launch_log")


def arguments(s: Script) -> list[str]:
    """1 — strict mode; its one argument its run directory — a walk's, its launch folder — which it
    stops unless it runs in, checked and never changed to; `-h` its usage, `--dry-run` what it would
    run, writing nothing; any other argument refused, exit 1."""
    where = "RUN, the run's folder" if isinstance(s, Job) else "its launch folder"
    return ["set -euo pipefail",
            *helpers(),
            "usage() {",
            *(f"  printf '%s\\n' {q(line)}" for line in (
                f"usage: bash {s.files.name('script')} DIR  -- started by `femkit job launch` alone, in DIR, {where}",
                f"       bash {s.files.name('script')} --dry-run  -- what it would run; it starts and writes nothing")),
            "}",
            "dry_run() {",
            *(f"  printf '%s\\n' {line}" for line in dry_run(s)),
            "}",
            'case "$#:${1-}" in',
            "  1:-h | 1:--help) usage; exit 0 ;;",
            "  1:--dry-run) dry_run; exit 0 ;;",
            "  1:-*) usage >&2; exit 1 ;;",
            "  1:*) ;;",
            "  *) usage >&2; exit 1 ;;",
            "esac",
            '[ "$(pwd -P)" = "$(cd -- "$1" 2>/dev/null && pwd -P)" ] || '
            '{ echo "femkit: it runs in $1, and was started in $PWD" >&2; exit 1; }']


def dry_run(s: Script) -> list[str]:
    """What `--dry-run` prints, each line one shell word: the command, each count and its source,
    the environment — or a walk's members or parts."""
    res, source = s.resources, f"from {s.files.name('request')}"
    counts = [f"ranks: {res.ranks}, {source}", f"threads per rank: {res.threads}, {source}",
              f"GPUs: {res.gpus}, {source}",
              f"wall: {res.wall}, {source}" if res.wall else "wall: none stated"]
    if isinstance(s, Job):
        env = s.environment
        lines = [f"the command: {shlex.join(launched(s.command, s))}",
                 f"the check: {shlex.join(s.check)}" if s.check else "the check: none",
                 *counts,
                 f"the environment: {env.name}, {env.managed} with the manager, its python {{python}}",
                 *(f"its preamble: {line}" for line in env.entry.preamble),
                 *(f"entered by: {line}" for line in env.entry.activation)]
        return [*(q(line) for line in lines),       # a shared file's name needs no quoting (jobs/request.py)
                *(f'"it shares {sh.file}: ${{share_{n}:-written in by job launch}}"' for n, sh in enumerate(s.shares, 1))]
    listed = s.members if isinstance(s, Batch) else s.parts
    what = "member" if isinstance(s, Batch) else "part"
    return [q(line) for line in [*counts, *(f"{what} {n}: {name}" for n, (name, _) in enumerate(listed, 1))]]


def once(s: Script) -> list[str]:
    """2 — one start per run: refused when the directory already holds started.json."""
    started = s.files.name("started")
    return [f"if [ -e {q(started)} ]; then",
            f'  echo "femkit: this run has started already ($PWD/{started}): a run is one start, and '
            '\\`femkit job launch\\` opens the next" >&2',
            "  exit 2",
            "fi"]


def gate(s: Script) -> list[str]:
    """3 — the launch-door gate: refused, exit 2, writing nothing, unless `job launch` started it."""
    return [f'if [ "${{{LAUNCHED_BY}-}}" != {q(CLAIM)} ]; then',
            '  echo "femkit: this script was not started by its launch: a run is started by \\`femkit job launch\\`, '
            'which writes its records; no other start is taken" >&2',
            f'  echo "launched-by: ${{{LAUNCHED_BY}:-NONE}} -- refused at the launch-door gate" >&2',
            "  exit 2",
            "fi"]


def helpers() -> list[str]:
    """How the script writes a moment and a record, as femkit's readers read them."""
    return ["json_text() {",
            "  if [ -z \"$1\" ]; then printf 'null'; return; fi",
            "  local s=$1",
            "  s=${s//\\\\/\\\\\\\\}; s=${s//\\\"/\\\\\\\"}; s=${s//$'\\n'/\\\\n}; s=${s//$'\\t'/\\\\t}; "
            "s=${s//[[:cntrl:]]/}",
            "  printf '\"%s\"' \"$s\"",
            "}",
            "now() { date -u +%Y-%m-%dT%H:%M:%S+00:00; }",
            "record() { printf '%s\\n' \"$2\" > \"$1.part\"; mv -f -- \"$1.part\" \"$1\"; }"]


def started(s: Job) -> list[str]:
    """4 — started.json, its first write: the time, the host, and what the scheduler granted, from
    the kind's job variables. The job's start, `FEMKIT_JOB_STARTED`, now unless its header or
    walk has set it."""
    roles = s.target.kind.job_variables
    lines = ['started="\\"time\\": \\"$(now)\\", \\"host\\": $(json_text "$HOSTNAME")"']
    lines += [f'[ -z "${{{roles[r]}:-}}" ] || started+=", \\"{r}\\": $(json_text "${{{roles[r]}}}")"'
              for r in JOB_ROLES if r in roles]   # each job role the kind names, as started.json records it
    lines += [f'record {q(s.files.name("started"))} "{{$started}}"', clock()]
    return lines


def clock() -> str:
    return f'export {JOB_STARTED}="${{{JOB_STARTED}:-$(date +%s)}}"'


def tee(s: Script) -> list[str]:
    """5 — its standard output and error teed into its log, so a scheduler's output file holds
    them too; SIGPIPE ignored: a stop that kills the tee must not kill the script."""
    return ["trap '' PIPE",
            f"exec > >(tee -a {q(log_of(s))}) 2>&1",
            "tee_pid=$!"]


def traps(s: Script) -> list[str]:
    """6 — one EXIT trap, run however the script ends: a script that stopped on its own before
    ended.json writes it, `stopped before its end`, with its reason; then the monitor is stopped
    and given its 10 seconds. One handler for every stop signal: it logs the signal into the log
    directly and exits 128 + its number, writing no ended.json. USR1 and USR2 are logged."""
    log = q(log_of(s))
    lines = ['doing=""', 'reason=""', 'stopped_by=""', 'ended_written=""', 'monitor=""',
             'stop() { reason=$1; echo "femkit: $1"; exit 1; }',
             "on_exit() {",
             "  local status=$?",
             "  set +e",
             "  trap - EXIT"]
    if isinstance(s, Job):
        lines += ['  if [ -z "$stopped_by" ] && [ -z "$ended_written" ]; then',
                  '    local why="stopped before its end"',
                  '    if [ -n "$reason" ]; then why+=": $reason"; elif [ -n "$doing" ]; then '
                  'why+=": $doing ended with exit $status"; fi',
                  f'    record {q(s.files.name("ended"))} "{{\\"status\\": $status, \\"time\\": \\"$(now)\\", '
                  '\\"reason\\": $(json_text "$why")}"',
                  f'    printf \'%s femkit: %s\\n\' "$(now)" "$why" >> {log}',
                  "  fi",
                  '  if [ -n "$monitor" ]; then       # once it opened its log it answers SIGTERM with its closing lines',
                  "    local n=0",
                  f'    while [ ! -e {q(s.files.name("monitor_log"))} ] && kill -0 "$monitor" 2>/dev/null && '
                  f'[ "$n" -lt {MONITOR_CLOSE * 10} ]; do sleep 0.1; n=$((n + 1)); done',
                  '    kill -TERM "$monitor" 2>/dev/null',
                  f'    while kill -0 "$monitor" 2>/dev/null && [ "$n" -lt {MONITOR_CLOSE * 10} ]; do '
                  'sleep 0.1; n=$((n + 1)); done',
                  "  fi"]
    lines += ["  exec >&- 2>&-",
              '  wait "$tee_pid" 2>/dev/null',
              '  exit "$status"',
              "}",
              "on_signal() {",
              "  set +e",
              "  stopped_by=$1",
              f"  printf '%s femkit: stopped by SIG%s\\n' \"$(now)\" \"$1\" >> {log}",
              '  exit $((128 + $(kill -l "$1")))',
              "}",
              f"going_on() {{ printf '%s femkit: SIG%s received; the run goes on\\n' \"$(now)\" \"$1\" >> {log}; }}",
              "trap on_exit EXIT",
              f"for signal in {' '.join(STOP_SIGNALS)}; do trap \"on_signal $signal\" \"$signal\"; done",
              f"for signal in {' '.join(GOING_ON)}; do trap \"going_on $signal\" \"$signal\"; done"]
    return lines


# ------------------------------------------------------------------ a calculation folder's blocks

def gpus(s: Job) -> list[str]:
    """7 — with GPUs asked: the model the driver reports, added to started.json, no count; and,
    with no device visible — the scheduler's grant, else CUDA_VISIBLE_DEVICES, else the driver's
    own list — a stop with that reason."""
    n = s.resources.gpus
    if not n:
        return ["# no GPU asked for"]
    grant = s.target.kind.job_variables.get("gpus")
    visible = f"${{{grant}:-${{CUDA_VISIBLE_DEVICES:-}}}}" if grant else "${CUDA_VISIBLE_DEVICES:-}"
    smi = q(GPU_QUERY[0])
    return ['doing="looking for the GPUs asked for"',
            f'visible="{visible}"',
            f'if [ -z "$visible" ] && command -v {smi} >/dev/null; then visible=$({smi} -L 2>/dev/null || true); fi',
            'model=""',
            f"if command -v {smi} >/dev/null; then "
            f"model=$({smi} --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || true); fi",
            f'if [ -n "$model" ]; then started+=", \\"gpu_model\\": $(json_text "$model")"; '
            f'record {q(s.files.name("started"))} "{{$started}}"; fi',
            f'[ -n "$visible" ] || stop "{n} GPU{"s" if n > 1 else ""} asked for, and none is visible: the scheduler '
            'granted none, CUDA_VISIBLE_DEVICES is unset, and the driver lists none"']


def entry_block(env: Environment, what: str) -> list[str]:
    """Enter ``env`` as block 8 enters any: a clean start, then its entry's lines — the target's
    preamble verbatim, then the activation of the environment by its name, a failed one stopping the
    run — each absolute file the preamble sources checked readable first, and the manager whose own
    hook the shell function's form evaluates checked there; after the preamble, the activate
    script's form stops, saying so, where nothing put its script on PATH; unset variables allowed
    while they run, `-e` kept."""
    *before, last = env.entry.activation
    manager, script = env.entry.manager, env.entry.script
    return [f'doing="entering {what}"',
            *env.start,
            *(f"[ -r {q(f)} ] || stop {q(f'{by} sources {f}, which is not readable here')}"
              for f, by in env.entry.sources()),
            *([f"[ -x {q(manager)} ] || stop {q(f'the activation evaluates the hook of the manager {manager}, which is not here')}"]
              if manager else []),
            "set +u", *env.entry.preamble,
            *([f"command -v {q(script)} >/dev/null || stop "
               + q(f"`{last}` sources {script} from PATH, and nothing put it there: after the clean start PATH is "
                   "the system's own, so the preamble puts the manager's bin on it (a cluster's module does), or the "
                   "activation is the manager's shell function")] if script else []),
            *before,
            f"{last} || stop {q(f'{what} is no environment the manager knows here as {env.managed}')}", "set -u"]


def verifying(env: Environment, what: str) -> list[str]:
    """Verify the environment entered, as block 9 does: the variable the manager's activation sets
    names an environment of its name, and its own python is there; that prefix is `$prefix` from
    here on."""
    return [f'doing="verifying {what}"',
            f'active="${{{env.active}:-}}"',
            f'[ -n "$active" ] && [ "${{active##*/}}" = {q(env.managed)} ] || '
            f'stop "the environment entered is ${{active:-none}}, not {env.managed}"',
            'prefix="$active"',
            'python="$prefix/bin/python"',
            '[ -x "$python" ] || stop "the environment\'s own python, $python, is not there"']


def enter(s: Job) -> list[str]:
    """8 — a clean start, then enter the environment: the target's preamble, then its activation of
    the environment by its name."""
    return entry_block(s.environment, f"the environment {s.environment.name}")


def verify(s: Job) -> list[str]:
    """9 — verify the environment entered, its own python — `{python}` from here on — and that the
    command's program, and with ranks > 1 the MPI launcher, resolves inside its prefix."""
    programs = [w for w in (s.command[0], *(s.target.mpi[:1] if s.resources.ranks > 1 and s.target.mpi else ()))
                if not parsed(w)]
    return [*verifying(s.environment, f"the environment {s.environment.name}"),
            "inside() {",
            "  local found",
            '  found=$(command -v -- "$1") || stop "$1 is not found in $prefix"',
            '  case "$(cd -- "$(dirname -- "$found")" && pwd -P)/" in "$(cd -- "$prefix" && pwd -P)"/*) ;; '
            '*) stop "$1 resolves to $found, outside $prefix" ;; esac',
            "}",
            *(f"inside {q(p)}" for p in programs)]


def variables(s: Job) -> list[str]:
    """10 — the environment's thread variables set to the threads per rank, its fixed variables to
    their values; the wall the job states in seconds, `FEMKIT_WALL_S` — a member's or a part's,
    its job's, which its walk set."""
    d = s.definition
    set_to = {**{v: str(s.resources.threads) for v in d.thread_variables}, **d.fixed_variables}
    lines = [f"export {k}={q(v)}" for k, v in set_to.items()]
    seconds = wall_seconds(s.resources.wall) if s.resources.wall else None
    if seconds is not None:
        lines.append(f'export {WALL}="${{{WALL}:-{seconds}}}"')
    return lines or ["# the environment sets no variable, and the request states no wall"]


def monitor(s: Job) -> list[str]:
    """11 — the monitor, on `{python}` at nice 19 in the background, watching this script's own
    process, given the cores the run uses; its start and any error loading it into the log."""
    job_id = s.target.kind.job_variables.get("id")
    flags = [f"--watch-pid \"$$\"", f"--cores {s.resources.cores}",
             *([f"--gpus {s.resources.gpus}"] if s.resources.gpus else []),
             f"--log {q(s.files.name('log'))}", f"--writes {q(s.files.name('monitor_log'))}",
             f"--util {q(s.files.name('util'))}", f"--ended {q(s.files.name('ended'))}",
             f"--checked {q(s.files.record(documents.CHECKED))}"]
    in_job = f" ${{{job_id}:+--in-job}}" if job_id else ""
    return ['doing="starting the monitor"',
            f'echo "femkit: monitor: starting {s.files.name("monitor")} on $python"',
            f'nice -n 19 "$python" {q(s.files.name("monitor"))} {" ".join(flags)}{in_job} '
            f'>/dev/null 2>>{q(s.files.name("log"))} &',
            "monitor=$!"]


def command(s: Job) -> list[str]:
    """12 — the command, as a child — through `launch.mpi` when it runs more than one rank — its
    output to the run's log, its exit status kept."""
    argv = launched(s.command, s)
    return ['doing=""',
            f'echo "femkit: the command: "{q(shlex.join(argv))}',
            "set +e",
            words(argv, s.shares),
            "status=$?",
            "set -e",
            'echo "femkit: the command exited $status"']


def check(s: Job) -> list[str]:
    """13 — when the command exited 0 and the request states a check: the check, on `{python}`,
    its output to check.log. The check writes its verdict, checked.json, and when passed
    outputs.json, its outputs made read-only (jobs.md § 2): the script computes nothing and records
    nothing of it; its exit status says whether it held, for the script's own exit (block 14)."""
    if not s.check:
        return ['verdict=""', "# the request states no check"]
    log = q(s.files.name("check_log"))
    return ['verdict=""',
            'if [ "$status" -eq 0 ]; then',
            '  doing="the check"',
            "  set +e",
            f"  {words(s.check, s.shares)} > {log} 2>&1",
            "  held=$?",
            "  set -e",
            '  if [ "$held" -eq 0 ]; then verdict=passed; fi',
            '  echo "femkit: the check ${verdict:-did not hold}"',
            '  doing=""',
            "fi"]


def ended(s: Job) -> list[str]:
    """14 — ended.json, the command's exit status, as its last act; the script exits with that
    status, or with 1 when it was 0 and the check did not pass."""
    lines = [f'record {q(s.files.name("ended"))} "{{\\"status\\": $status, \\"time\\": \\"$(now)\\", \\"reason\\": null}}"',
             "ended_written=1",
             'echo "femkit: ended, exit $status"']
    if s.check:
        lines.append('[ "$status" -ne 0 ] || [ "$verdict" = passed ] || exit 1')
    return [*lines, 'exit "$status"']


# ------------------------------------------------------------------ the walks

def walk_clock(s: Batch | Sequence) -> list[str]:
    """The job's clock, set once for every member or part, and the wall its launch folder states."""
    seconds = wall_seconds(s.resources.wall) if s.resources.wall else None
    return [clock(), *([f'export {WALL}="${{{WALL}:-{seconds}}}"'] if seconds is not None else [])]


def members(s: Batch) -> list[str]:
    """Each member's own run script, in the member's new run, one after another, its output to
    that run's log; one that fails leaves the rest to run. The walk enters no environment."""
    return ["member() {",
            '  echo "femkit: $2 starts, in $1"',
            "  local status=0",
            f'  ( cd -- "$1" && exec bash {q(s.files.name("script"))} "$1" ) >/dev/null || status=$?',
            '  echo "femkit: $2 ended, exit $status"',
            "}",
            *(f"member {q(run)} {q(name)}" for name, run in s.members),
            "exit 0"]


def control(s: Sequence) -> list[str]:
    """femkit's control environment, entered as block 8 enters any and verified as block 9
    verifies one; its `femkit` command."""
    what = "femkit's control environment"
    return [*entry_block(s.control, what), *verifying(s.control, what),
            'femkit="$prefix/bin/femkit"',
            '[ -x "$femkit" ] || stop "the femkit command is not at $femkit"']


def parts(s: Sequence) -> list[str]:
    """Each part launched in turn by femkit's own `job launch`, waited on, inside this job: the job
    is the scheduler's job ID, or `<host>-<pid>` run here. The walk stops on a refused part, exit 2,
    never on a part whose runs failed."""
    job_id = s.target.kind.job_variables.get("id")
    here = '"$HOSTNAME-$$"'
    job = f'"${{{job_id}:-$HOSTNAME-$$}}"' if job_id else here
    return [f"job={job}",
            "part() {",
            '  echo "femkit: the part $2: femkit job launch $1"',
            "  local status=0",
            f'  "$femkit" job launch "$1" --foreground --yes --in-sequence {q(s.folder)} --in-job "$job" || status=$?',
            '  if [ "$status" -eq 2 ]; then echo "femkit: the launch of $2 was refused: the sequence stops"; exit 2; fi',
            '  echo "femkit: the part $2 ended its launch, exit $status"',
            "}",
            *(f"part {q(path)} {q(name)}" for name, path in s.parts),
            "exit 0"]


Block = tuple[int | None, str, Callable]   # its number in jobs.md § 4's table, or none; what it does; its lines

#: A calculation folder's script: its fourteen blocks, in order (jobs.md § 4).
JOB: tuple[Block, ...] = tuple((n, title, block) for n, (title, block) in enumerate((
    ("arguments, strict mode, in its run directory", arguments),
    ("one start per run", once),
    ("the launch-door gate", gate),
    ("started.json", started),
    ("the run's log", tee),
    ("traps", traps),
    ("the GPUs asked for", gpus),
    ("a clean start, and enter the environment", enter),
    ("verify the environment entered", verify),
    ("threads, fixed variables and the wall", variables),
    ("start the monitor", monitor),
    ("the command", command),
    ("the check", check),
    ("ended.json", ended),
), 1))
#: A batch's walk: blocks 1, 3, 5 and 6, the job's clock, then each member (jobs.md § 4.1).
BATCH: tuple[Block, ...] = (JOB[0], JOB[2], JOB[4], JOB[5], (None, "the job's clock", walk_clock),
                            (None, "each member, in its run", members))
#: A sequence's walk: blocks 1, 3, 5 and 6, the job's clock, femkit's control environment, then
#: each part (jobs.md § 4.2).
SEQUENCE: tuple[Block, ...] = (JOB[0], JOB[2], JOB[4], JOB[5], (None, "the job's clock", walk_clock),
                               (None, "femkit's control environment", control),
                               (None, "each part, launched", parts))


def render(s: Script) -> str:
    """The script of ``s``: its blocks in order, each under the line naming it. A calculation
    folder's opens with a line for each file it shares, its path written in by `job launch`."""
    blocks, what = {Job: (JOB, "run script"), Batch: (BATCH, "batch's walk"),
                    Sequence: (SEQUENCE, "sequence's walk")}[type(s)]
    lines = ["#!/bin/bash",
             f"# The {what} of {s.name}, made by femkit for {s.target.name} (jobs.md § 4). Started by",
             "# `femkit job launch` alone, in its folder; `--dry-run` says what it would run."]
    if isinstance(s, Job) and s.shares:
        lines += ["# The files this run shares, each by its path from the run: written in by `job launch`."]
        lines += [f"share_{n}=''  # {sh.file}, made by {sh.folder}" for n, sh in enumerate(s.shares, 1)]
    for n, title, block in blocks:
        lines += ["", f"# {n} · {title}" if n else f"# {title}", *block(s)]
    return "\n".join(lines) + "\n"


def with_shares(text: str, paths: list[str]) -> str:
    """A calculation folder's run script as a run's copy holds it: the path of each file it shares,
    in the request's order, written in (jobs.md § 5)."""
    def fill(found: re.Match) -> str:
        return f"share_{found.group(1)}={q(paths[int(found.group(1)) - 1])}{found.group(3)}"
    filled, n = SHARED.subn(fill, text)
    assert n == len(paths), f"the script holds {n} shared files' lines, and {len(paths)} paths are given"
    return filled
