# Core — the building blocks every package uses

**Role:** contract
**Status:** current; what is not built yet is marked so
**Authority:** the public API of `femkit/core/`: what each building block
offers, its exact signature, and the rules a caller follows. The operation
types in `core/operations.py` are governed by [`api.md`](api.md).

## The short version

| rule | § |
|---|---|
| Every concern below has **one** implementation, here; no other package writes files, starts processes, takes locks or loads declared files its own way | all |
| Every declared file is a **`Model`**; one loader turns any failure into a `DefinitionError` with file, key path and reason | 2 |
| Every write is **atomic**: a reader sees the old file or the new one | 4 |
| A mutating operation holds a **non-blocking lock** on its subject; a second is refused, never queued | 5 |
| A multi-step operation is an **append-only event log** folded for progress and resume; one atomic write, made last, commits it | 6 |
| A **state machine** is one closed table: ordered observation rules ending in `otherwise`, and the actions each state allows | 7 |
| Every external command runs through **`process.run`** | 8 |
| A refusal is one of six **`Refusal`** types (exit 2); any other exception is a defect or an unavailable system (exit 1) | 9 |

The core imports the standard library and declared third-party libraries
only — never a domain, a surface, a solver or a scheduler. Importing any core
module reads no file, probes nothing and starts nothing.

## 1. Modules

| module | offers | § |
|---|---|---|
| `dirs` | the user's directories, the control prefix, and the checkout femkit runs from | 3 |
| `paths` | `inside(path, root)`: the one test that a path resolves within a prefix or tree; `nearest_existing(path)`: where a place not made yet would be made | 3 |
| `schema` | `Model`, the loader, `DefinitionError`, the placeholder grammar | 2 |
| `persist` | atomic writes, TOML and JSON reads and writes | 4 |
| `locks` | `subject_lock` | 5 |
| `eventlog` | `EventLog` and its fold | 6 |
| `states` | `Machine`, `Rule`, `Action` | 7 |
| `process` | `run`, `ProcessResult`, `tail` (a log's last lines) | 8 |
| `errors` | `Refusal` and its six kinds | 9 |
| `issues` | `Issue` | 10 |
| `text` | how a value, a path (from `~`), a count (`1 step`, `16 steps`), a table, a finding and a "next" block are shown | [`api.md`](api.md) § 4.4 |
| `operations` | `Context`, `Plan`, `Step`, `Result`, `Outcome`, `Observer`, `operation` | [`api.md`](api.md) |

## 2. Schema — `core/schema.py`

```python
class Model(pydantic.BaseModel):          # extra="forbid", frozen=True
    ...

def load_toml(path: Path, model: type[M], context: dict | None = None) -> M
def validate(model: type[M], data: Any, file: Path | str, context: dict | None = None) -> M

class DefinitionError(Refusal):           # .file: str, .problems: list[tuple[key_path, reason]]
```

- **One home per field.** A field's type, default, allowed values and
  description are written once, on its model, with `pydantic.Field(...,
  description=...)`. Help text, `docs/reference/` and the web form read that
  description; nothing restates it.
- **Extra facts on a field** go in `json_schema_extra` under these names only:
  `unset` (what an unset optional key means, [`config.md`](config.md) § 3),
  `declarable` (a machine fact `--set` may declare, [`jobs.md`](jobs.md)
  § 9.2), `cli` (how the command line spells it, [`api.md`](api.md) § 4),
  `placeholders` (the names a templated field accepts, § 2.1), and — not
  built yet (plan § 3, M5) — `ref` (the type of object a field refers to by name, read by both
  the cross-reference check and the model graph,
  [`models.md`](models.md) § 11.2).
- **Loading fails whole.** Every field problem in a file is reported at once,
  each as `(key path, reason)`; the key path uses dots and `[index]`, e.g.
  `builds[1].options.NETGEN_DIR`. Cross-reference problems (next point) are
  checked once every field is valid, and are then reported together.
- **Cross-references** (a build's source, a registered engine) are checked by
  a model validator; outside facts a validator needs, such as the registered
  engine IDs, arrive in `context`, never from a global.

### 2.1 Placeholders

```python
PLACEHOLDER                                          # `{name}` or `{name:argument}`
def check_placeholders(text: str, allowed: frozenset[str]) -> str
def placeholders(text: str) -> list[tuple[str, str | None]]
def render(text: str, values: dict[str, str]) -> str  # keys: "name" or "name:argument"
```

One grammar everywhere. Each templated field declares which names it accepts
and validates with `check_placeholders`; `docs/reference/` lists them per
field. A name the field does not accept fails at load.

## 3. Directories — `core/dirs.py`

```python
def config_dir() -> Path    # FEMKIT_CONFIG_DIR, else $XDG_CONFIG_HOME/femkit, else ~/.config/femkit
def data_dir() -> Path      # FEMKIT_DATA_DIR,   else $XDG_DATA_HOME/femkit,   else ~/.local/share/femkit
def cache_dir() -> Path     # FEMKIT_CACHE_DIR,  else $XDG_CACHE_HOME/femkit,  else ~/.cache/femkit
def state_dir() -> Path     # FEMKIT_STATE_DIR,  else $XDG_STATE_HOME/femkit,  else ~/.local/state/femkit
def runtime_dir() -> Path   # FEMKIT_RUNTIME_DIR, else as config.md § 2 says; made 0700 — not built yet (plan § 3, M7)
def control_prefix() -> Path            # <data>/environments/control (envs.md § 1)
def checkout() -> Path                  # the checkout femkit runs from; it is never installed (envs.md § 7)
def directory_sources() -> dict[str, tuple[Path, str]]   # each directory and the rule that chose it
```

`core/paths.py` holds the one test that a path lies within another — a compiler
within a prefix, a test's directory within a build tree — and the one walk to the
nearest existing parent of a place not made yet:

```python
def inside(path, root) -> bool          # resolves to root or below it; nothing, or an empty path, is not inside
def nearest_existing(path) -> Path | None   # path or its nearest existing parent: whose disk, whose permissions
```

Read from the environment on every call. No other module reads these
variables or builds these paths.

## 4. Persistence — `core/persist.py`

```python
def atomic_write_text(path: Path, text: str) -> Path   # temp file in the same directory, fsync, rename
def write_json(path: Path, data: Any) -> Path          # atomic; sorted keys, two-space indent, final newline
def write_toml(path: Path, data: dict) -> Path         # atomic
def read_toml(path: Path) -> dict
def read_json(path: Path) -> Any
```

- Every file femkit writes goes through these. Parent directories are created.
- A file whose appearance means "done" (a manifest, `prepared.json`) is
  written **last**, by one of these calls: that write is the commit point. The
  install script's control stamp follows the same rule in bash
  ([`envs.md`](envs.md) § 7.2).
- Appending to an event log is the one non-atomic write (§ 6).

## 5. Locks — `core/locks.py`

```python
@contextmanager
def subject_lock(subject: str) -> Iterator[None]    # raises Busy
```

- An exclusive, non-blocking `flock` on `<data>/locks/<subject>.lock` (a
  *subject lock*; the solved package lists beside it are *package locks*,
  [`envs.md`](envs.md) § 4.3), held for the `with` block. The kernel releases
  it however the process ends, so there is no stale lock to detect.
- `Busy` means **another** process holds it. The process that holds it reads
  its own subject as not busy: its facts function is told so.
- The file holds the holder's pid and command only so `Busy` can name them;
  nothing is decided from its content.
- A subject is a stable name: `env-ngsolve`, `run-<calculation path hash>`.
  The operation declares it ([`api.md`](api.md) § 2); the operation runner,
  not the operation, takes the lock.

## 6. Event logs — `core/eventlog.py`

```python
class EventLog:
    def __init__(self, path: Path)                   # <operation directory>/events.jsonl
    def append(self, kind: str, **fields) -> None     # one JSON line, flushed and fsynced
    def events(self) -> list[dict]                     # every complete line; a torn last line is ignored

def fold(events: list[dict]) -> LogState
class LogState(Model):
    started: bool
    ended: bool                    # an operation-end record exists
    outcome: str | None            # its outcome: done | failed
    finished_steps: tuple[str, ...]   # step IDs with step-end outcome done, in order
    failed_step: str | None
    interrupted: bool              # started, not ended, and the pid in operation-start is not alive
```

An **operation directory** is `<state>/operations/<subject>/<time>/`, or
`<state>/operations/<operation>/<time>/` for an operation with no subject. It
holds the event log and each step's log; nothing else names this path. An
operation over several subjects (`env install ngsolve elmer`) writes one
directory per subject, and its result names each on its row.

Record kinds, each with `time`: `operation-start` (operation, request, pid),
`step-start` (step), `step-end` (step, outcome, log), `operation-end`
(outcome). Progress, the failed step, interruption and what a resume may skip
are folds over the log; nothing else records them. An operation's result
becomes visible only through its commit write (§ 4), never through the log.

## 7. State machines — `core/states.py`

```python
@dataclass(frozen=True)
class Rule(Generic[F, S]):
    describe: str
    state: S
    when: Callable[[F], bool] | None = None    # None only on the last rule: otherwise

@dataclass(frozen=True)
class Action:
    describe: str
    command: str        # what a person types, a "next" line; `{name}` is what the machine describes (`ngsolve`);
                        # empty for an allowed action with nothing to do
    def typed(self, name: str) -> str

@dataclass(frozen=True)
class Machine(Generic[F, S]):
    name: str
    states: type[S]                            # an Enum
    rules: tuple[Rule[F, S], ...]
    actions: Mapping[S, Mapping[str, Action]]
    def observe(self, facts: F) -> S
    def allowed(self, state: S) -> Mapping[str, Action]
    def require(self, state: S, action: str, name: str) -> Action    # raises Refused
    def next_commands(self, state: S, name: str) -> tuple[str, ...]  # each allowed command once
```

- **Facts** are a frozen dataclass or `Model` gathered by one function that
  reads durable things — directories, records, event logs, a scheduler's
  answer. `observe` is pure: same facts, same state.
- **Closed and total**, checked when the `Machine` is constructed: the last
  rule is `otherwise` and only it; every state is produced by some rule; every
  state has an action row (possibly empty).
- **Never stored.** No module writes a state label to disk.
- **One source of "next".** Refusals, `doctor` and every "next" line read
  `allowed()`; no message writes a remedy by hand.
- Each machine lives in its domain module, beside its facts function. Its
  contract shows the same table; rendering it into `docs/reference/` with
  `schema docs`, so the two cannot drift, is not built yet.

## 8. Processes — `core/process.py`

```python
def run(argv: Sequence[str], *, env: Mapping[str, str] | None = None,
        cwd: Path | None = None, timeout: float | None = None,
        log: Path | None = None) -> ProcessResult

@dataclass(frozen=True)
class ProcessResult:
    argv: tuple[str, ...]
    returncode: int | None       # None: did not finish (timeout)
    stdout: str                  # whole stdout when captured; the log's last 40 lines otherwise
    stderr: str                  # empty when logged (stderr goes into the log)
    log: Path | None
    timed_out: bool
    ok: bool                     # returncode == 0

def tail(path: Path, lines: int) -> list[str]   # a log's last lines, read from its end: a build log may be large
```

- An argument vector, never a shell string; `stdin` is closed.
- `env=None` passes the current environment; otherwise exactly the mapping
  given. Callers build environments from declared data; nobody edits
  `PATH` or library paths by hand — the one fixed `PATH` is the confinement's
  system part, under the manager's activation ([`envs.md`](envs.md) § 4.4).
- With `log`, stdout and stderr go together to that file (for builds and
  checks); without it, both are captured whole (for short answers a reader
  parses).
- Each command runs in its own process group. A timeout or an interrupt stops
  the whole group (`SIGTERM`, then `SIGKILL` after 5 s).
- A non-zero exit is a result, not an exception; the caller decides.
- A detached, supervised process — the web server's supervisor and its child
  ([`api.md`](api.md) § 5.4), and a job a person launches — is started through
  one building block beside `run`, which returns its process ID and start
  time, the one way a process is identified; not built yet (plan § 3, M3).

## 9. Errors — `core/errors.py`

```python
class Refusal(Exception):        # refused before acting: exit 2
    next: tuple[str, ...]        # commands a person may run instead

class DefinitionError(Refusal)   # a declared file does not load (§ 2); defined in core/schema.py
class Refused(Refusal)           # a state does not allow the action (§ 7)
class Busy(Refusal)              # the subject's lock is held (§ 5)
class ConsentDeclined(Refusal)   # the person said no, or no terminal and no --yes
class PlanStale(Refusal)         # the state changed between plan and apply (api.md § 3)
class UsageError(Refusal)        # a request that does not validate (api.md § 4.1)
```

A finding a person should act on but that does not stop the operation is an
`Issue` in the result (§ 10), not an exception. Which findings refuse and which
are issues is [`framework.md`](framework.md) § 4: a missing statement, or one
that contradicts the record, refuses; what a machine record says of a request is a warning. Any exception that is not a
`Refusal` is a defect or an unavailable system: the surface reports it with
the operation's log path and exits 1.

## 10. Issues — `core/issues.py`

```python
class Issue(Model):
    severity: Literal["error", "warning", "info"]
    code: str                    # stable, kebab-case, e.g. "preamble-unset"
    subject: str                 # what it is about: an environment, a key, a file
    message: str                 # one sentence for a person
    next: tuple[str, ...] = ()   # commands that would resolve it
```

`code` is what tests and programs match on; `message` is free to change.
