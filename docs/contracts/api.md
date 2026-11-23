# API — operations, the registry, and the surfaces over them

**Role:** contract
**Status:** current; what is not built yet is marked so
**Authority:** what an operation is and how it is declared
(`femkit/core/operations.py`), the operation registry (`femkit/registry.py`,
with `femkit/reference.py` beside it),
and the two generic surfaces over it: the command line (`femkit/cli/`) and the
web application (`femkit/web/`)

## The short version

| rule | § |
|---|---|
| Everything femkit does for a person is an **operation**, declared once: name, request model, result model, whether it changes anything, its lock subject | 2 |
| A changing operation is **plan, then apply**; the plan is printable, is what `--dry-run` shows, and is what the person consents to | 3 |
| The command line and the web are **generic adapters**: every command and route is derived from the declarations; neither holds a decision or a per-operation branch | 4, 5 |
| Request fields become options and arguments; the field's description is the help | 4.1 |
| One result model gives the text a person reads, the JSON a program reads, and the exit code | 2.3, 4.3 |
| An operation reaches files, processes and configuration only through its **`Context`** | 2.4 |
| Adding a verb is one declared operation; no surface file changes | 6 |

## 1. Why one layer

Every way to drive femkit — a terminal, a script with `--json`, the web page,
a test — calls the same operation with the same request model and gets the same
result model. Behaviour cannot drift between surfaces because there is only one
copy of it. A test drives an operation directly; a surface test checks only
the generic adapter, once.

## 2. Declaring an operation

An operation lives in its domain package, in its operations module
(`femkit/envs/operations.py`, `femkit/config/operations.py`, …; § 6 says when a
domain has a second); `schema check|docs` live in `femkit/reference.py`,
because they read every domain ([`framework.md`](framework.md) § 1).

### 2.1 A read-only operation

```python
class ListRequest(Model):
    """No inputs."""

class EnvRow(Model):
    name: str = Field(description="environment name")
    state: str = Field(description="observed state (envs.md § 3.2)")

class ListResult(Result):
    rows: list[EnvRow]
    def text(self) -> str: ...

@operation("env.list", request=ListRequest, result=ListResult)
def env_list(req: ListRequest, ctx: Context) -> ListResult:
    """Every environment with its definition, state and GPU qualification."""
```

### 2.2 A changing operation

```python
@operation("env.install", request=InstallRequest, result=InstallOutcome,
           changes=True, subject=lambda req: [f"env-{n}" for n in req.names])
class EnvInstall:
    """Install environments from their definitions (envs.md § 4)."""

    def plan(self, req: InstallRequest, ctx: Context) -> Plan: ...
    def apply(self, plan: Plan, ctx: Context, observer: Observer) -> InstallOutcome: ...
```

| declaration part | meaning |
|---|---|
| name | `group.verb` (`env.install`), or one word for a top-level verb (`doctor`). It is the command `python -m femkit env install` and the route `/api/env/install` |
| `request` | a `Model`; its fields are every input the operation takes |
| `result` | a `Result` subclass (§ 2.3) |
| `changes` | `False` (default): one function `(req, ctx) -> result`. `True`: a class with `plan` and `apply` (§ 3) |
| `subject` | for a changing operation: the lock subjects it holds while applying (core.md § 5) |
| docstring | the command's help and the route's description |

The name is unique; the registry refuses a duplicate at start.

### 2.3 Results

```python
class Result(Model):
    issues: list[Issue] = []
    def ok(self) -> bool                  # default: no issue of severity "error"
    def text(self) -> str                 # what a person reads; required

class Outcome(Result):                    # the result of apply
    plan: Plan
    status: Literal["done", "failed"]
    log: str | None                       # the operation directory (core.md § 6); empty when each row names its own
    def ok(self) -> bool                  # status == "done" and no error issue
```

- `text()` renders only fields of the model; it decides nothing.
- A result field carries a description like a request field; the JSON a
  program reads is `model_dump(mode="json")`, nothing else.
- An operation whose answer is a verdict (`doctor`: ready or not) overrides
  `ok()`; the exit code follows it (§ 4.3).

### 2.4 Context

```python
@dataclass
class Context:
    env: Mapping[str, str]                          # the process environment, read once
    now: Callable[[], datetime]
    def cached(self, key: str, factory: Callable[[], T]) -> T    # loaded once per context
    @classmethod
    def from_process(cls) -> "Context"
```

- The surface makes one `Context` per invocation and passes it to the
  operation. Directories come from `core.dirs`, which reads the process
  environment on every call (core.md § 3), so a test sets the `FEMKIT_*`
  variables there. `ctx.env` is that environment read once, for what an
  operation reads or passes on itself: the manager variable, a check's
  environment.
- Domain data is loaded through `ctx.cached` by the domain's own loader —
  `definitions.catalogue.load(ctx)`, `config.settings.load(ctx)` — so a file
  is read once per invocation and a `DefinitionError` surfaces before any step.
- The context carries no domain types; the core stays free of domains.

## 3. Plan, then apply

```python
class Step(Model):
    id: str                                # stable within the plan, e.g. "build:netgen"
    describe: str                          # one line for a person
    argv: tuple[str, ...] | None = None    # the command it will run, when it runs one

class Plan(Model):
    operation: str
    request: dict                          # the request, as JSON
    subjects: tuple[str, ...]
    basis: dict                            # the observed facts the plan was made from
    steps: tuple[Step, ...]                # empty: nothing to do
    issues: list[Issue] = []
    asks: tuple[Ask, ...] = ()             # request fields to ask for on a terminal (§ 3.1)
    def text(self) -> str
    def digest(self) -> str                # SHA-256 of the canonical JSON
```

1. `plan(req, ctx)` observes state and reads definitions. It writes nothing,
   starts nothing but read-only probes, and lists every step with its command
   line. A state that does not allow the action raises `Refused` here
   (core.md § 7, `require`).
2. The surface shows the plan and obtains consent (§ 4.2, § 5).
3. The runner takes the subjects' locks, then calls `apply(plan, ctx,
   observer)`. `apply` first observes again and raises `PlanStale` if the
   facts differ from `plan.basis`; then it runs the steps, writing the event
   log (core.md § 6) and reporting each step to the observer. The first step
   that does not finish stops the run — unless the steps do not depend on one
   another (`env bootstrap`'s installs, envs.md § 6.2): then every step runs,
   and the run fails if any did.

```python
class Observer(Protocol):
    def operation_start(self, plan: Plan, where: Path) -> None   # where: the operation directory
    def step_start(self, step: Step, index: int, total: int) -> None
    def step_log(self, log: Path) -> None   # the running step writes its log here, as it runs
    def step_end(self, step: Step, outcome: str, log: Path | None) -> None
    def note(self, text: str) -> None
    def operation_end(self, plan: Plan, status: str) -> None
```

An empty plan asks no consent and is still applied: it changes nothing, writes
an event log of no steps, and returns the operation's outcome. A changing
command therefore always answers with its outcome type — `config init` with
nothing to add still reports every key it kept.

### 3.1 Questions

Some values only the person can give, and install time is when they are there:
the activation preamble, where environments go.
A plan names each such request field it lacks in `asks`:

```python
class Ask(Model):
    key: str                     # the request field the answer fills
    question: str                # one line
    context: tuple[str, ...]     # what the person should see beside it
```

The CLI asks them on a terminal, before consent, and plans again with the
answers; a list field takes a line per item, ended by an empty line. An empty
answer is no answer, and the plan stands as it was. An answer is checked as it is
given: one holding characters that are not text — an arrow or erase key the
terminal passed through — or one the request model refuses is said, with the
characters shown, and the question is asked again, so one keystroke never ends
the command. Nothing is asked under
`--yes` or `--dry-run`, or without a terminal. A program reads `asks` in the
`--dry-run --json` plan and sends the fields itself. No domain module reads a
terminal.

## 4. The command line — `femkit/cli/`

One click group per name prefix, one command per operation, built at start
from the registry. The CLI package holds the adapter and nothing
operation-specific.

### 4.1 From request fields to options

| request field | command line |
|---|---|
| `json_schema_extra={"cli": "argument"}` | a positional argument; a `list[...]` field takes one or more |
| `bool`, default `False` | a flag `--name` |
| any other field | an option `--name VALUE`; a `list[...]` field repeats |
| a field with no default | required |

- Underscores become dashes (`cuda_architectures` → `--cuda-architectures`).
- A value is validated by the request model; its errors are reported by key,
  exit 2.
- Help is the operation's docstring and each field's description.

### 4.2 Options every command has

| option | on | meaning |
|---|---|---|
| `--json` | all | print exactly one JSON document on stdout: the result (for a changing operation, its outcome, even when there was nothing to do), or for `--dry-run` the plan, or for a refusal `{"refused": …, "message": …, "next": […]}` |
| `--dry-run` | changing | print the plan and stop; never asks or writes, and starts nothing but the plan's read-only probes |
| `--yes`, `-y` | changing | consent given in advance |

Consent: with a non-empty plan and no `--yes`, the CLI first asks the plan's
questions (§ 3.1), then prints the plan and asks on a terminal; without a
terminal it refuses (`ConsentDeclined`). Progress goes
to stderr through a terminal observer, so stdout holds only the result.

### 4.3 Exit codes

| code | when |
|---|---|
| 0 | the result's `ok()` is true (including "nothing to do") |
| 1 | the operation ran and `ok()` is false, or an exception that is not a `Refusal` (a defect) — reported with its log path |
| 2 | a `Refusal`: bad usage, a declared file that does not load, a state that does not allow the action, a held lock, consent declined, a stale plan — reported with its `next` commands |

### 4.4 The text a person reads

Built from `core/text.py`, so every command reads alike:

- **The first line is tagged** `[group verb]` — `[config init] …` — and says
  the outcome in a few words; the details follow, indented.
- **Values are shown as typed**, never as Python or JSON: a path as a path, a
  command line as a command line (`mpirun -np {ranks}`), a list space-joined,
  `unset` and `none` in words.
- **Rows are aligned columns**; a note about a row follows it after `#`.
- **A finding** is one line marked `x` (error), `!` (warning) or `-` (info),
  with the commands that resolve it indented under it.
- **What to do next** is `next -- <sentence>:` and the commands, one a line,
  indented, prose after `#`. A printed command is one a person can paste:
  `python -m femkit …`, run in the control environment from the checkout,
  because femkit is never installed ([`envs.md`](envs.md) § 7). Contracts
  write commands the same way, or leave out the leading `python -m femkit`
  (`env install NAME`) where the context makes it plain.
- **A refusal** is `[group verb] refused: <reason>` and `next -- instead:`
  with the commands its state allows.
- **Progress** goes to stderr. An operation
  with steps first says, as `[group verb]`, how many and where its logs are
  (the log folder names what it acts on); each step is numbered
  (`[ 3/16] configure netgen`) and ends with its outcome and the time it took
  (one line only, for a step done at once); a step that did not finish shows
  its log's path and last lines. An operation run inside another's step
  (`env bootstrap`'s installs, `env install`'s validate) is indented under
  that step. On a terminal, a running step whose log the observer was told
  of shows one line under it, rewritten in place about once a second: the
  time it has run and its log's last line, cut to the terminal's width. The
  line is erased before anything else is printed and when the step ends, so
  it takes no room; output that is not a terminal never gets it. Paths under the
  home directory are written from `~`. With `--yes` the plan is printed first,
  its steps only; its findings come with the outcome.

`--json` is for programs: the model as JSON, indented.

## 5. The web application — `femkit/web/`

Two parts: a flask application built from the same registry, and a front end
that runs in the browser. No milestone builds them yet (plan § 7); these rules
hold when one does, and a basic test checks that every registered operation can
be expressed this way (its request and result models produce a JSON schema).
The reasons for the front end's form are
[ADR 0009](../decisions/0009-web-front-end.md).

### 5.1 Routes

| route | does |
|---|---|
| `GET /api/operations` | every operation: name, description, request and result JSON schemas |
| `POST /api/<name>` | a read-only operation: request JSON in, result JSON out |
| `POST /api/<name>/plan` | a changing operation: request JSON in, plan JSON out |
| `POST /api/<name>/apply` | `{"request": …, "digest": …}`: re-plans, refuses with `PlanStale` unless the new plan's digest equals the one the person saw, then applies |
| `GET /api/events/<operation directory>` | the operation's event log as a stream of server-sent events, from its first line, as it grows: how a long apply's progress reaches the page |
| `GET /api/health` | answers when the server is serving; `serve status` asks it (§ 5.4) |
| `GET /` and `/static/…` | the built front end |

HTTP status follows § 4.3: 200 for a result, exit 0 or 1 (the body says `ok`);
409 for a refusal; 500 for a defect, with the log path. A request body is the
request model and nothing else: no field takes executable text, a shell
fragment, an environment variable or a path outside the folders the operation
names.

### 5.2 The front end

- **Built from the registry and the schemas, never from a list of its own.**
  Forms are rendered from the JSON schemas; the model graph from the graph
  document `model graph` returns ([`models.md`](models.md) § 11.2); the
  palette, the port types and the statuses come from that document. Adding a
  field, an operation or a node kind changes no front-end code.
- **Writes only through plan and apply.** Every change the page makes — an
  edit of the model, a decision, preparing a case — is an operation, shown as
  its plan and applied with its digest; the page holds no state the files do
  not.
- **Its views:**

  | view | shows | acts through |
  |---|---|---|
  | operation | any operation as a form, its plan, its outcome | the routes of § 5.1 |
  | model graph | the model and study as nodes and typed wires; findings on each node; with an engine chosen, each node's fit status | `model graph`, `model check`, `model set`, `model unset`; positions saved by their own operation |
  | node | the selected node's form, from its kind's schema; for an open fit line, the decisions and customizations that resolve it | `model set`, `model unset` |
  | review | `case prepare`'s plan: the fit report, each decision, each customization with its hash, the files `final/` changes, the command | apply with the digest |
  | progress | an operation's steps as they run, and each step's log's last line | `GET /api/events/…` |
  | jobs and results | runs, their states, the result tables; where each field file is, for ParaView | the job and result operations |

- **Code is a file.** A customization is uploaded as a file into the
  calculation folder by an operation that records its hash; the page shows it
  and never runs or edits code typed into a form.
- **Fields are viewed in ParaView**
  ([ADR 0002](../decisions/0002-paraview-visualization-boundary.md)); the page
  shows numbers, tables and where the field files are.

### 5.3 Source and build

- **Source** is a React application whose graph view uses React Flow, in a
  top-level `frontend/` folder (created with it; `PROJECT_CONTRACT.md` § 2
  then lists it). It is built with Node.js from conda-forge in a developer's
  own environment — never in the control environment.
- **The built bundle is shipped** in `femkit/web/static/`: generated, never
  edited by hand, and checked by a basic test against the hash of its sources,
  as the reference pages are ([`definitions.md`](definitions.md) § 2.3).
  Installing femkit never needs Node.js, and the page loads nothing from the
  network: scripts, styles and fonts are all in the bundle.

### 5.4 Serving — `serve`

`serve` is a group of verbs, declared as operations of the `server` domain
([`framework.md`](framework.md) § 1); a verb is always named, never implied:

| verb | does |
|---|---|
| `serve start` | detaches a supervisor, which runs the web application as its child; writes the pidfile; logs to the server's log |
| `serve status` | every server this account runs, each with two answers kept apart: is the process up (the pidfile's checks), and is it answering (`GET /api/health`, asked at the address it was started on); `--port` for one |
| `serve restart` | reads the configuration first, as a fresh child would, and refuses with its reason if it does not load — leaving the running server alone; otherwise signals the supervisor, which replaces its child |
| `serve stop` | asks the supervisor to stop; it takes its child down and removes the pidfile |
| `serve foreground` | the supervisor and its child in this terminal, stopped with Ctrl-C: for development |

The supervisor runs `python -m femkit.web` as a child process; the `server`
domain never imports the web package, as no domain imports a surface.

**Files**, each in a directory of the person's own account:

| file | holds |
|---|---|
| `$XDG_RUNTIME_DIR/femkit/serve-<port>.pid` (`<state>/run/` when that variable is unset) | the supervisor's process ID and the address its server was started on |
| `<state>/logs/serve-<port>.log` | every line the supervisor and the server print, each event timestamped: child start, respawn, give-up, stop, and a `status` that found the server up but not answering |
| `<state>/logs/serve-<port>.stacks.log` | every thread's stack, appended each time the child receives `SIGUSR1` |

- **The log is capped and rotated**: over its size limit it is closed and
  compressed to `serve-<port>.log.1.gz`, older archives shift up, and only the
  newest few are kept (`--log-max-mb`, `--log-keep`), so a long-lived server
  cannot fill a disk.
- **Every verb checks before it acts**: the process the pidfile names is alive,
  belongs to this account, and is a femkit server; a pidfile naming anything
  else is reported stale and never signalled.
- **The supervisor respawns a child that dies by a signal**, and gives up,
  saying so in the log, after two such deaths within 30 s. A child that exits
  with an error — a configuration it cannot load — is not respawned, since
  restarting it would only fail again.
- **It never kills a child that is running.** A server that is up but not
  answering is a question, not a verdict: its stacks are dumped and read
  (`kill -USR1`), and a person decides on `serve restart`.

The server is a state machine ([`framework.md`](framework.md) § 3), observed
from the pidfile, the process and the health route:

| state | observed when | `start` | `stop` | `restart` |
|---|---|---|---|---|
| `stopped` | no pidfile | starts | nothing to do | refused: offers `start` |
| `stale` | a pidfile whose process is gone, not this account's, or not a femkit server | removes the pidfile, starts | removes the pidfile | refused: offers `start` |
| `answering` | the process is up and `/api/health` answers | refused: already running | stops | restarts |
| `not answering` | the process is up and `/api/health` does not answer | refused: already running | stops | restarts |

### 5.5 Access

The state reached by configuring nothing is the safe one: a mistake leaves a
capability missing, never open to everyone.

- **Loopback by default.** `--host` defaults to `127.0.0.1`. Any other address
  is refused unless the server serves TLS and sign-in is configured; with
  neither, the refusal names both.
- **Sign-in is optional and outsourced.** With no `[web.auth]` section in
  `config.toml` nobody signs in, which is right for one person on their own
  machine. A `[web.auth]` section names identity providers (OpenID Connect);
  femkit learns an account's address and never holds a password. The provider's
  client secret and the session-signing key are files in
  `<config>/secrets/` (the folder `0700`, each file `0600`), under fixed names;
  the session key is created on the first run.
- **TLS** directly from PEM files (`--cert`, `--key`, or `web.tls` in
  `config.toml`; the command line wins), or from a reverse proxy in front of a
  loopback server, with `web.trust_proxy` trusting exactly one hop of its
  forwarded headers.
- **Every response** carries a content security policy that allows scripts
  only from the server itself — no inline script, which a basic test checks
  across the bundle — and no other origin, together with
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`, HSTS once served over HTTPS, and a cap on
  request size. Session cookies are `HttpOnly`, `Secure` over HTTPS and
  `SameSite=Lax`, which is the defense against cross-site requests; no CORS
  headers are sent.
- `--no-auth` is accepted only with a loopback address.

How access works on a machine whose loopback address is shared by its users —
a cluster's login node — is open (plan § 7).

## 6. The registry — `femkit/registry.py`

```python
DOMAINS = ("femkit.config.operations", "femkit.envs.operations", ...)
def operations() -> dict[str, Operation]     # imports DOMAINS when called, never at import
```

The one list of where operations live. Adding a verb to an existing domain
changes only that domain's operations module; adding a domain, or a second
module to a domain whose operations serve another subject (`jobs.setup`: this
machine's setup, beside the machine records), adds one line here.
