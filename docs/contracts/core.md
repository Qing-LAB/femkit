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
| A refusal is one of seven **`Refusal`** types (exit 2); any other exception is a defect or an unavailable system (exit 1) | 9 |
| A dimensional value is an **exact rational** in its dimension's canonical unit, read by one grammar from a unit table that is data | 11 |

The core imports the standard library and declared third-party libraries
only — never a domain, a surface, a solver or a scheduler. Importing any core
module reads no file, probes nothing and starts nothing.

## 1. Modules

| module | offers | § |
|---|---|---|
| `dirs` | the user's directories and the variables that name them, the control prefix, and the checkout femkit runs from | 3 |
| `clock` | how femkit writes a moment: UTC, ISO 8601, to the second — in every record, event log and server log line | 6 |
| `paths` | `inside(path, root)`: the one test that a path resolves within a prefix or tree; `nearest_existing(path)`: where a place not made yet would be made | 3 |
| `schema` | `Model`, the loader, `DefinitionError` and each `Problem` in plain words with what would be right, the placeholder grammar; a field's help, and a template held to it | 2 |
| `persist` | every write: atomic files and streams, appends, copies, removal, a folder emptied or replaced whole, an archive unpacked; TOML and JSON reads and writes; a TOML text's keys with the comments above them | 4 |
| `locks` | `subject_lock`, and the grammar of a subject's name | 5 |
| `eventlog` | `EventLog`, its file's name, the record kinds, the step outcomes, and its fold | 6 |
| `states` | `StateTable`, a machine's table as data; `Binding`, what code gives it; `load`; `Machine`, `Rule`, `Action` | 7 |
| `process` | `run`, `ProcessResult`, `tail` (a log's last lines), a process's `Identity`, the one stop grace | 8 |
| `errors` | `Refusal` and its seven kinds | 9 |
| `issues` | `Issue` | 10 |
| `units` | the unit table's schema, `Quantity`, `Units`: one grammar for a quantity, a unit and an expression of named quantities; conversion | 11 |
| `text` | how a value, a path (from `~`), a count (`1 step`, `16 steps`), a table, a finding and a "next" block are shown | [`api.md`](api.md) § 4.4 |
| `markdown` | `headings(text)`: a Markdown document's headings and their link anchors, by GitHub's rule — read by a formulation's section check and the document viewer, so a section named in data and its anchor agree | [`web.md`](web.md) § 2.3 |
| `view` | the one vocabulary of what a person may read and do: `Help`, `Action`, `Field`, `Table` — every next step an `Action`; and `Verb`, an operation's name with its request model, one per name ([`api.md`](api.md) § 2) | [`web.md`](web.md) § 7 |
| `commandline` | the one mapping between a request's fields and a command's arguments, both ways: the command line parses by it, and an `Action` is written as a command by it | [`api.md`](api.md) § 4.1 |
| `operations` | `Context`, `Plan`, `Step`, `Result`, `Outcome`, `Observer`, `operation`, `run_steps`; an operation's address and its folder | [`api.md`](api.md), § 6 |

## 2. Schema — `core/schema.py`

```python
class Model(pydantic.BaseModel):          # extra="forbid", frozen=True
    ...

def load_text(text: str, model: type[M], file: Path | str, context: dict | None = None, *, exact: bool = False) -> M
                                                        # TOML text, as a file named `file` holds it: the one reader
def load_toml(path: Path, model: type[M], context: dict | None = None, *, exact: bool = False) -> M
                                                        # persist.read_text, then load_text; no file is a problem too
def validate(model: type[M], data: Any, file: Path | str, context: dict | None = None) -> M
def problems(model, data, errors) -> list[Problem]       # pydantic's errors as a person reads them, at their keys
def not_toml(text, exc) -> Problem                      # why a text is not TOML, plainly, at its line
class Problem(tuple):                                   # (path, reason), what every reader unpacks; and what would
    path: str; reason: str; right: str | None; choices: tuple[str, ...]   # be right there, as the file writes it
def refuse(model: str, problems: list[tuple[location, reason]]) -> None
                                                        # in a model validator: every cross-reference problem at once
def field_extras(field: FieldInfo) -> dict              # a field's annotations, its Annotated type's included
def alternatives(annotation) -> list                    # what it may hold, through Annotated, Optional, unions
def classes(annotation), keys_of(annotation), values_of(annotation), items_of(annotation), closed(annotation)
                                                        # its models; a table's keys, values; a list's items; a Literal's texts
def optional(annotation) -> bool                        # whether it allows None, through Annotated and unions
def described(field) -> str                             # its help: its description, `: one of` its closed values,
                                                        # and its `doc` reference after it
def help_text(sentence, values=(), doc=None, *, unit=None) -> str
                                                        # the one builder of a help: `described`'s, and a
                                                        # declared key's — its sentence, `, in` and its unit
def help_findings(text, model, declared=lambda path: None) -> list[HelpFinding]
                                                        # where a template of a file `model` reads breaks the rule
                                                        # that the comment above each key is its help
class HelpFinding: line: int | None, key: str, problem: str   # its line from 1 (None: the text), its key path, why
def field_named(cls, key) -> tuple[str, FieldInfo] | None   # the field a file writes as `key`, alias or name
def key_path(loc) -> str                                # a problem's place: `builds[1].options`, in a file or a request,
                                                        # a key TOML quotes quoted: `axes."mesh:fine:size"`
def problem_path(model, loc) -> str                     # a validation error's place as the file writes it: the
                                                        # keys alone, pydantic's own marks left out
def matching(pattern, **field), whole(pattern) -> str   # a text field its pattern holds whole; the pattern tied to both ends
def references(instance) -> Iterator[tuple[location, type, name, held]]   # every name its `ref` fields hold;
                                                        # held: `key`, `value` or `item` — how the location holds it
QUANTITIES: dict[kind, QuantityKind]                    # each `quantity` kind: QuantityKind(reads, dimension, sentence)
DIMENSIONS: dict[kind, dimension]                         # the kinds with a fixed one; LENGTH, a length's
def as_quantity(description, kind="any", *, extra=None, **field) -> Field   # a field written as a quantity of `kind`
def as_reference(description, target, *, extra=None, **field) -> Field   # a field naming `target`'s objects (`ref`)

class DefinitionError(Refusal):           # .file: str, .problems: list[Problem]
```

- **One home per field.** A field's type, default, allowed values and
  description are written once, on its model, with `pydantic.Field(...,
  description=...)`. Help text, `docs/reference/` and the web form read that
  description; nothing restates it. A field's **help** is what `described`
  makes of it, one text: its description; then, when its value — or a table's
  values — is a closed list, `: one of` and each allowed value in backticks,
  joined by `, `; then its `doc` reference in parentheses. An element's
  `family`, described as "the element family", has the help "the element
  family: one of \`lagrange\`, \`nedelec\`". A description therefore never
  lists the allowed values itself. A value is a closed list when every
  alternative it allows is a `Literal`'s: a number or `unlimited` is not.
  `help_text` is the one builder of a help: `described` makes a field's with
  it, and each `declared` (below) a declared key's — its sentence, then `, in`
  and its unit.
- **A template's comment above a key is that text**
  ([`projects.md`](projects.md) § 7). `persist.key_comments` reads a
  template's keys with the comments above them (§ 4), and `help_findings`
  holds them to the schema — given a template's text and the model of the file
  it is (the settings file's `UserConfig`, a part kind's schema), one finding
  for each key the schema names whose comment is not its help, each key the
  schema does not allow, each table the schema names that has no header of its
  own or holds keys it names inline, and each key of a table the text writes
  that it neither sets nor shows commented out. A key whose name the person
  chooses is not compared. `declared(path)` gives the help of a key a
  declaration outside the schema states — a formulation's parameter, the
  property list's property ([`web.md`](web.md) § 8.3) — and None for every
  other key; one test holds every template file to it, each part of every
  project template and the settings file's (`tests/basic/test_templates.py`).
- **Extra facts on a field** go in `json_schema_extra` under these names only:
  `unset` (what an unset optional key means, [`config.md`](config.md) § 3),
  `ask` (the question `config init` asks for a setting while it is unset,
  [`config.md`](config.md) § 3.2),
  `cli` (how the command line spells it, [`api.md`](api.md) § 4.1: `argument`, or an
  option's own spelling where the field's name cannot be it, `--from`),
  `placeholders` (the names a templated field accepts, § 2.1), `ref` (the type of
  object a field refers to by name, read by both the cross-reference check and
  the project graph, [`models.md`](models.md) § 11.2; made with
  `as_reference`), `quantity` (a value written as a quantity, § 11: `any`, a
  quantity or an expression of a project's parameters; `length`, one in a
  length's dimension — a coordinate is one, since only a geometry script
  writes a bare number ([`geometry.md`](geometry.md) § 3); `constant`, a
  quantity naming no parameter — a material's value, since a material cites
  nothing ([`projects.md`](projects.md) § 3); or `unit`, a unit text alone;
  made with `as_quantity`, and `QUANTITIES` the one table of the kinds — what
  each value reads as, its fixed dimension and its sentence — the loaders,
  the cases, the forms' units and the reference pages read),
  `toml` (a
  field that takes a value as its TOML text, `whole` — `config set`'s
  `value`, `whole`; a surface writes the text from the value a
  person gives), `doc` (where the field is defined: a document and its
  section, so a description holds its sentence and nothing else), `context`
  (the page's context a request field takes — `project`, `study` or
  `environment`, [`web.md`](web.md) § 8.1), `for` (the one type of its object
  a field belongs to, when the others never hold it) and `stated` (a field a
  file may leave out while it is being written, which `project check` asks for
  and `study expand` requires — what a material's dataset rests on,
  [`materials.md`](materials.md) § 3).
- **A pattern holds the whole value.** A text field with a pattern — a name,
  a digest, an ID — is made with `matching`, and a form's pattern with
  `whole`: pydantic and JSON Schema search inside a value, so a name's pattern
  left open would take `../outside`, a path out of its folder.
- **One reading of an annotation.** Every walk of a schema — the command
  line's spelling, the object types, the graph, the fragments — reads a
  field's annotation through `alternatives` and the functions beside it, and
  finds a field by the key a file writes with `field_named`.
- **`ref`** on a text or a list of texts names the type its values refer to; on
  a table it is `{"key": type, "value": type}`, either part optional. A type may
  offer alternatives, `group:outer_boundary|group:interface`; a group's place
  is one of the names `femkit/data/geometry/kinds.toml` declares
  ([`geometry.md`](geometry.md) § 7). The type `file` names a file in a folder part's own
  folder, by its path from it, which the door reads ([`projects.md`](projects.md) § 6). `references` walks a
  loaded file's fields and yields every name with its location, its type and
  how the location holds it — a table's key, a text value, a list's item; the
  domain that owns the file says which names exist.
- **One TOML reader.** `load_text` reads every declared file's text — a
  definition, a setting, a record, a project's part — and `load_toml` is
  `persist.read_text` then `load_text`: a text that is not TOML, a file that is
  not UTF-8 and a file that is not there are each a `DefinitionError` at the
  file, like a field's problem. Why a text is not TOML is said in plain words
  at its line (`not_toml`): tomllib's errors each read as a sentence — "line
  23: a quoted text is not closed before the line ends" — a key or table set
  twice at that key, with both its lines — "`side` is set twice (lines 23 and
  27)" — and tomllib's own words kept, after the line, only where no sentence
  fits.
- **`exact=True`** reads every TOML float from its decimal text as a
  `Decimal`, never a binary float: a model's numbers enter a case ID exactly
  (§ 11).
- **Loading fails whole.** Every field problem in a file is reported at once,
  each as `(key path, reason)`; the key path is the one the file writes
  (`problem_path`): dots and `[index]`, e.g. `builds[1].options.NETGEN_DIR`,
  a key TOML quotes quoted, and none of pydantic's own marks — a validator's
  kind, the member of a union it tried, `[key]` — so the problems of a
  union's members at one key are one problem there, their reasons joined. Cross-reference problems (next point) are
  checked once every field is valid, and are then reported together.
- **Each problem in plain words, with what would be right** (`problems`;
  [`models.md`](models.md) § 13). A problem's reason is a sentence for a
  person, never pydantic's words, and a `Problem` carries what would be right
  at its key as a finding does (§ 10): an unknown key is one problem at it —
  "`szie` is no key here; did you mean `size`?" — its choices the keys its
  table may still take, the closest first, and a required key it most nearly
  spells is not said missing besides; a value outside a closed list says so,
  its choices those values, the closest first, or its `right` the one value
  when there is one; a value of the wrong kind says what it should be — a
  whole number, a text in quotes, a table — each member of a union what it
  takes; a missing key is said at its table — "`solver` is missing". Built
  once, here, every declared file gets it: each part kind, each definition,
  the settings file.
- **Cross-references** (a build's source, a registered engine) are checked by
  a model validator, which raises them together with `refuse`; outside facts a
  validator needs, such as the registered engine IDs or the unit table, arrive
  in `context`, never from a global.

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
def runtime_dir() -> Path   # FEMKIT_RUNTIME_DIR, else as config.md § 2 says; made private by persist.private_dir
VARIABLES: dict[str, str]   # each of the five directories -> the variable that names it outright; a test
                            # isolates every one of them from this list (testing.md § 2.1)
def host() -> str           # this machine's name, which keys the runtime directory
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
def write_stream(path, source, accept=None) -> bool     # a stream written whole, or not at all: in place only
                                                        # when accept takes the written file (a download's digest)
def copy_file(source, path) -> Path                    # atomic, as write_stream
def append_text(path, text) -> None                    # a log's lines added at its end, flushed and fsynced:
                                                        # the one appender, an event log's records too
def touch(path) -> Path                                # made empty if absent; its time now
def remove(path) -> None                               # a file, or a folder with all it holds; absent is no error
def make_folder(path) -> Path                          # a folder, with the folders above it; there already is no error
def read_text(path) -> str | None                      # a file's text as its bytes hold it; None when no file is there
def read_bytes(path) -> bytes | None                   # a file's bytes; None when no file is there
def sha256(path) -> str | None                         # the one digest of a file, read in blocks — a download
                                                        # may be large; None when no file is there
def empty_folder(path) -> Path                         # an empty folder, whatever was there
def copy_tree(source, path, only=None) -> Path         # a folder copied to a place not there yet: copied beside
                                                        # it and renamed in, whole — an interrupted copy leaves nothing;
                                                        # `only`: just these files, by their POSIX paths from source
def replace_folder(fresh, path) -> None                # fresh takes path's place whole: old moved aside, fresh
                                                        # renamed in, old removed — never a half of either
def unpack_single(archive, path) -> bool               # a gzipped tar's one top folder becomes path, whole
BARE                                                   # a key TOML writes bare; any other it quotes — what a key path
                                                       # (§ 2), an address and a template's keys read
def plain_value(text) -> Any                           # a TOML inline value as a person types it, as plain Python
def read_toml(path: Path) -> dict
def read_json(path: Path) -> Any
def read_document(path, empty="") -> TOMLDocument     # a TOML file to edit, its comments and order kept
def write_document(path, doc) -> Path                  # atomic
def document_has(doc, key) -> bool; document_set(doc, key, value)
                                                       # a key not there yet: directly under the line showing it
def key_comments(text) -> list[KeyComment]             # every key and table header a TOML text writes or shows
                                                       # commented out, with the comment lines directly above it
class KeyComment: path, line, header, shown, value, comment
def document_text(doc, key) -> str                     # an entry's text as its file holds it: a table as its own document
def inline_text(value) -> str                          # a plain value as TOML text on one line
def private_dir(path: Path, *, make=True) -> Path   # 0700; refused when another account could enter it or
                                                   # replace it; make=False only refuses — what a plan checks
def open_private(path: Path, mode: str) -> IO   # 0600 from its first byte, never through a link;
                                                # "a" appends, "w" truncates, "x" creates exclusively
```

`config.toml` keeps its comments, its order and its layout through every edit
`config set` makes — read as a document, changed key by key, and written whole
and atomically; a key not there yet goes directly under the line that shows it
commented out, so it stands under its help ([`config.md`](config.md) § 3.2); no
command edits a project's files ([`projects.md`](projects.md) § 7). tomlkit
inserts a key at a place only through its own `Container._insert_at`, held to
it by tomlkit's version range in `control.txt` and a test.

`key_comments` is the one reader of a template's help
([`projects.md`](projects.md) § 7): for each key, its path from the text's
root, its line, whether it is a table header, whether it is shown commented
out, its value, and the comment lines directly above it with no blank line
between that are no key, read without their `#` and joined by single spaces. A
comment line that reads as a TOML key or table header is a key shown, on one
line; a shown header heads the shown keys after it until a key is set; a
statement's value may span lines.

`atomic_write_text` and `write_json` take `private=True` for a file only this
account may read (a pidfile). `private_dir` makes each folder it creates
`0700`, and refuses a folder above it through which another account could
replace what is inside: one owned by another account (root aside), or one
writable by others and not sticky (`/tmp` is sticky) — a group's write counts
unless the group is this account's own private group, as a `002` umask makes
every folder.

- Every file femkit writes goes through these. Parent directories are created.
- A file whose appearance means "done" (a manifest, `prepared.json`) is
  written **last**, by one of these calls: that write is the commit point. The
  install script's control stamp follows the same rule in bash
  ([`envs.md`](envs.md) § 7.2).
- Appending — a log's lines, an event log's records (§ 6) — is the one
  non-atomic write; each append is flushed and fsynced before it returns.
- Every read of a file femkit declares or writes goes through these too:
  `read_text`, `read_bytes`, `read_toml`, `read_json`, `sha256`.

## 5. Locks — `core/locks.py`

```python
@contextmanager
def subject_lock(subject: str, *, shared: bool = False) -> Iterator[None]    # raises Busy
def is_held(subject: str) -> bool       # held alone by another process: something else is changing it
def require_free(subject: str) -> None  # raises Busy while anyone holds it, shared or alone; takes nothing
def held_fd(subject: str) -> int        # the descriptor this process holds it on, to hand to a process it starts
def adopt(fd: int, by: str | None = None, next: Iterable[dict] = ()) -> None   # each next step as its Action's JSON
                                        # a handed lock: its file now names the receiver, and what ends its hold
def holders() -> dict[str, int]         # subject -> pid, from the kernel's lock table (/proc/locks): the
                                        # process that took the lock, which after a handover is not the holder
```

- **A lock can be handed over**: a process started with the descriptor
  (`process.start_detached(keep_fds=...)`) holds it too, so it stays held for
  as long as either runs — how `serve start` leaves its lock with the
  supervisor it detaches ([`web.md`](web.md) § 4).

- A non-blocking `flock` on `<data>/locks/<subject>.lock` (a *subject lock*;
  the solved package lists beside it are *package locks*,
  [`envs.md`](envs.md) § 4.3), held for the `with` block. The kernel releases
  it however the process ends, so there is no stale lock to detect.
- **Alone or shared.** What changes a subject holds its lock alone; what only
  uses it holds it shared — any number of users at once, and none while
  something holds it alone. A running web server holds the `web`
  environment's lock shared, so the environment is never removed under it
  ([`web.md`](web.md) § 4). `is_held` answers whether something holds it
  alone — is changing it; `require_free` refuses while anyone holds it.
- `Busy` means **another** process holds it. The process that holds it reads
  its own subject as not busy: `is_held` and `require_free` leave its own hold
  out, so what it observes under its own lock reads as it would under none.
  — only so `Busy` can name the live ones and offer those commands as its next
  steps; nothing is decided from its content. A holder alone rewrites the file;
  a shared holder adds its line.
- A subject is a stable name — `env-ngsolve`, `machine-Sol`, `server-<host>-8000` —
  of letters, digits, `.`, `_` and `-`, starting with a letter or a digit
  (`locks.SUBJECT`): its lock file and its operations' folder are called by it,
  and a name outside the grammar is a defect where it is made. The operation
  declares it ([`api.md`](api.md) § 2); the operation runner, not the
  operation, takes the lock.
- The file holds one line per holder — the holder's process, by its identity
  (§ 8), what it is, and the commands that end its hold

## 6. Event logs — `core/eventlog.py`

```python
FILE = "events.jsonl"                                  # in its operation directory; nothing else names it
StepOutcome = Literal["done", "failed", "killed"]      # how a step ends; OUTCOMES lists them

class EventLog:
    @classmethod
    def of(cls, folder: Path, now=clock.now) -> EventLog  # the log of the operation in folder; its moments from now
    def append(self, kind: str, **fields) -> None     # one JSON line, by persist.append_text: flushed and fsynced
    def events(self) -> list[dict]                     # every complete line, read by persist; a torn last line is ignored

def fold(events: list[dict]) -> LogState
class LogState(Model):
    operation: str | None          # the operation that wrote it, as its start record names it
    basis: dict                    # the facts its plan rested on, as its start record holds them
    started: bool
    ended: bool                    # an operation-end record exists
    outcome: str | None            # its outcome: done | failed
    steps: tuple[StepState, ...]   # each step: its ID, its outcome or `running`, its log — what a surface shows
    finished_steps: tuple[str, ...]   # step IDs with step-end outcome done, in order
    failed_step: str | None
    interrupted: bool              # started, not ended, and the process that started it no longer runs —
                                   # by its identity (§ 8), never its ID alone

class OperationAddress:            # in core/operations.py: `<subject>/<time>`, how a surface names a run
    @classmethod
    def at(cls, subject, moment) -> OperationAddress   # its time: UTC, `%Y%m%dT%H%M%S.%fZ`
    @classmethod
    def parse(cls, subject, time) -> OperationAddress | None   # None where either breaks its grammar
    def folder(self) -> Path
```

An **operation directory** is `<state>/operations/<subject>/<time>/`, or
`<state>/operations/<operation>/<time>/` for an operation with no subject. It
holds the event log and each step's log; nothing else names this path. An
operation over several subjects (`env install ngsolve elmer`) writes one
directory per subject, and its result names each on its row.

Record kinds, each with `time` (`core/clock.py`, from the operation's
context): `operation-start` (operation, request, basis — the facts its plan was
made from — and process, its identity),
`step-start` (step), `step-log` (step, log: the running step's log, as it reports it to the observer — the runner wraps every apply's observer to record it), `step-end` (step, outcome, log), `operation-end`
(outcome). A step outcome outside `StepOutcome` is a defect of the step. Progress, the failed step, interruption and what a resume may skip
are folds over the log; nothing else records them. An operation's result
becomes visible only through its commit write (§ 4), never through the log.

## 7. State machines — `core/states.py`

A state machine says what state a subject is in and what may be done in each
state. Decided by the person: the machine itself is data, one table per machine,
and code gives it only its facts. Every machine observed from facts is built so,
its table in `femkit/data/states/` and its facts and predicates in its domain
(an install's steps are a fold over its event log instead, § 6):

| table | subject | facts and predicates | contract |
|---|---|---|---|
| `part.toml` | a part of a project | `projects/state.py` | [`projects.md`](projects.md) § 8 |
| `environment.toml` | an engine or tool environment | `envs/state.py` | [`envs.md`](envs.md) § 3 |
| `control.toml` | the control environment | `jobs/setup.py`; the install script holds the same rules in bash, held equal by a test | [`envs.md`](envs.md) § 7.2 |
| `server.toml` | a web server | `server/state.py` | [`web.md`](web.md) § 4 |
| `record.toml` | a record of this machine | `jobs/record.py` | [`jobs.md`](jobs.md) § 9.3 |

```text
femkit/data/states/<machine>.toml      one machine, declared:
  [states]          its states, in order, each with the sentence saying when it is observed
  [[rules]]         in order: `state`, and `when`, the condition on the machine's named facts that
                    gives it — names joined by `and`, `or`, `not` and parentheses; the last rule's
                    `when` is `otherwise`, and only its
  [actions.<state>] each action the state allows, by its name; an empty table: none. An action has
                    `describe`, and `operation`, a registered operation by its name, with `request`,
                    its values — a text that is one placeholder alone, `{name}`, is the value the
                    subject gives it, and a key the subject leaves unset is left out; or `shell`, a
                    line that is no operation (the control environment's install script); or
                    neither: allowed, with nothing to do
```

```python
class StateTable(Model)                    # the schema of a machine's file
@dataclass(frozen=True)
class Binding(Generic[F]):                 # what code gives a machine:
    machine: str                           #   its name, its file's stem
    predicates: Mapping[str, Callable[[F], bool]]   # each fact a condition may name, over the facts
    values: Mapping[str, Callable[[str], Any]]      # each value a request takes from the subject's name;
                                                    # by default `name`, the name itself
    reads: frozenset[str]                           # each state code reads by name, `m.states.ready`, anywhere
def bindings() -> list[Binding]            # every binding made so far: what `schema check` loads each table to
def load(path: Path, binding: Binding[F]) -> Machine[F, Enum]   # the one loader: the table bound;
                                           # its states an enumeration of texts, named after the machine
class Machine:                             # observe(facts) -> state; allowed(state); next(state, name)
                                           # -> each next step; require(state, action, name) -> or Refused
```

- **Facts** are gathered by one function per machine, in its domain module,
  which reads durable things — directories, records, event logs, a scheduler's
  answer, file hashes — into named values. Nothing else is code: a condition
  is written over those names in one small grammar, read by `core/states.py`.
- **Closed and total**, checked when the machine loads, each refusal a
  `DefinitionError` at its key path: the last rule is the otherwise and only it;
  every state is produced by some rule; every state has an action row (possibly
  empty); a condition stays inside its grammar and names only the facts the
  binding names; a request names only values the subject gives; every action
  names a registered operation whose request has each field the row fills;
  every state the binding's code reads is declared. The catalogue loads each
  table by its own rules (`definitions.md` § 2); `schema check` checks every
  table's operations against the registry, and loads every table femkit ships
  bound to its binding, so a table lacking a fact or a state the code reads is
  refused there, never first met while the code runs; a domain's `load` checks
  the rest it gives, once per invocation (`catalogue.machine(ctx, binding)`).
- **A state is the loaded enumeration's member.** Code that acts on a state
  compares it with the member of the machine it observed by, `state is
  m.states.ready`, `m` from the same invocation — never with a state's name
  as text — and its binding lists each state it so reads (`reads`); a result
  holds the state's name, a text, as its JSON does.
- **Never stored.** No module writes a state label to disk; every state is
  observed from the facts, each time.
- **One source of "next".** Refusals, findings, `doctor` and every next step
  read the machine's allowed actions; no message writes a remedy by hand.
- **One machine per subject**: the subject is the thing whose state it is — an
  environment, the server, a part of a project, a step's run, a study's
  expansion, a case's preparation for one environment, a run, a run's results.
  A count over subjects — a project's parts, a study's cases — is a summary,
  never a machine.
- `schema docs` renders each machine into `docs/reference/`, so its contract and
  its declaration cannot drift. Not built yet: today it renders the table's
  schema, not each machine (plan § 7).

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
  parses). `run` opens its log itself, with the standard library alone: a
  check program running inside an environment imports `process`, and nothing
  else of femkit's ([`framework.md`](framework.md) § 1), so `process` cannot
  import `persist`, whose TOML library the environment does not hold.
- Each command runs in its own process group. A timeout or an interrupt stops
  the whole group (`SIGTERM`, then `SIGKILL` after `GRACE`, 5 s — the one grace for
  every process femkit stops).
- A non-zero exit is a result, not an exception; the caller decides.
- A detached, supervised process — the web server's supervisor and its child
  ([`web.md`](web.md) § 4), and a job a person launches — is started through
  one building block beside `run`:

  ```python
  @dataclass(frozen=True)
  class Identity:
      pid: int
      start: int                   # the process's start time, in clock ticks since boot
      boot: str                    # the kernel's boot ID
      def alive(self) -> bool      # a process with this pid and start time runs now, on this boot, as this account

  def identify(pid: int) -> Identity | None        # None: no such process of this account
  def start_detached(argv, *, env=None, cwd=None, keep_fds=(), log=None) -> Identity
                                                   # a new session, stdin closed; its output to `log` or discarded
  def end(identity: Identity, *, grace: float = 5.0) -> bool   # SIGTERM, then SIGKILL; only if alive()
  ```

  A process is identified by its ID and start time on this boot, never by its
  ID alone: a signal goes only to an `Identity` that is `alive()`. A child that
  must not outlive its parent sets `PR_SET_PDEATHSIG` and checks `getppid`
  after, which `start_detached` does not do — the child that needs it sets it
  itself (`web.md` § 4). Jobs will use the same block (plan § 4, X).

## 9. Errors — `core/errors.py`

```python
class Refusal(Exception):        # refused before acting: exit 2
    code: str                    # which refusal of its kind; without one of its own, its kind's: `plan-stale`
    subject: str | None          # what it is about: a setting, an environment, a file, an address
    next: tuple[Action, ...]     # what a person may do instead (core/view.py)

class DefinitionError(Refusal)   # a declared file does not load (§ 2); defined in core/schema.py
class Refused(Refusal)           # a state does not allow the action (§ 7)
class Unstated(Refusal)          # something the work needs is not stated, and femkit never guesses it
class Busy(Refusal)              # the subject's lock is held (§ 5)
class ConsentDeclined(Refusal)   # the person said no, or no terminal and no --yes
class PlanStale(Refusal)         # the state changed between plan and apply (api.md § 3)
class UsageError(Refusal)        # a request that does not validate (api.md § 4.1)
```

Every refusal is one of these kinds, never a bare `Refusal` — a narrower class a
domain keeps for itself is answered as the kind it is of; the kind tells a
surface or a script what sort of problem it is, its code and subject which one
and about what — as a finding's do (§ 10) — and its next steps say what to do.
A script, a surface or a test tells two refusals apart by kind, code and
subject, never by their wording. Every refusal names its code and subject. `Unstated` is the missing statement [`framework.md`](framework.md) § 4
refuses: a setting, the package manager, a scheduler's kind or command. A
request naming what does not exist is a `UsageError`; one making what exists
already is `Refused`, as the state of the thing it names does not allow it.

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
    code: str                    # stable, kebab-case, e.g. "preamble-unset"; another is refused when made
    subject: str                 # what it is about: an environment, a key, a file, an address
    label: str | None = None     # what a person calls the subject, where its address is not that
    message: str                 # one whole sentence for a person
    file: str | None = None      # the file it is about, as the person opens it: a project's, from the project's folder
    key: str | None = None       # the key in that file, its dotted path: `conditions.left.kind`
    right: str | None = None     # the one value that would be right, as the file would write it (TOML text)
    choices: tuple[str, ...] = ()  # the values that would be right, when more than one would do
    next: tuple[Action, ...] = ()  # what would resolve it (core/view.py): operations that exist
```

`code` is what tests and programs match on; `message` is free to change.

- **A finding says where and what would be right.** A finding about a
  project's part carries the file and the key the person opens in their
  editor, read through the door from its subject's address
  ([`projects.md`](projects.md) § 6), never formed by the domain that found
  it. Where one value would be right — the digest a declared file has now, a
  group's dimension in its promise — it is `right`; where several would do —
  the condition kinds a formulation allows, the groups a component promises —
  they are `choices`, and the fix chooses none ([`web.md`](web.md) § 7.4).
  Its message is a plain sentence that leaves the file and the key to the
  finding, which shows them once.
- **`next` holds only operations that exist** — `study expand`, `project new`,
  `config set` — never an edit of a file the person wrote, which femkit does
  not make ([`projects.md`](projects.md) § 7).
- **One value, or the choices — never both**: a finding holding both is refused
  where it is made.
- In a project, a finding is made through the door: `door.finding(opened,
  address, …)` reads the file from the address and writes the key from its
  path; a part's check makes one with `Checking.issue`
  ([`models.md`](models.md) § 11.1).

## 11. Units — `core/units.py`

```python
class UnitTable(Model)                         # the schema of femkit/data/units.toml (definitions.md § 1)

@dataclass(frozen=True)
class Quantity:
    value: Fraction                                # exact, in the canonical unit of its dimension
    dimension: tuple[tuple[str, int], ...] = ()    # each base dimension with its power, by name;
                                                   # no power is zero; empty for a plain number

class Units:
    def __init__(self, table: UnitTable)
    def symbols(self) -> list[str]                                 # every symbol read, prefixed ones included
    def parse(self, text: str, names: Mapping[str, Quantity] = {}) -> Quantity
    def convert(self, quantity: Quantity, unit: str) -> Fraction   # its value in that unit
    def canonical(self, dimension) -> str | None                   # a base dimension's canonical unit: `m`
    def of(self, dimension) -> list[str]                           # every symbol of it, prefixed ones included

def name_spans(text: str) -> list[tuple[int, int, str]]   # each name a quantity text uses — a parameter or a
                                                          # unit symbol — with its span; empty when the grammar
                                                          # cannot read the text: what a graph draws a wire from
class UnitError(ValueError)                    # names the text and what in it is wrong
```

- **Exact.** A number is read from its decimal text — `500`, `0.5`, `-3`,
  `1.602176634e-19` — as an exact rational, never through a binary float, and
  every operation keeps it exact. A value is held in its dimension's canonical
  unit: coherent SI, with plane angle a base dimension of its own, held in
  degrees, so that a written angle stays exact; a radian would need π, and the
  table has none.
- **One grammar** reads a quantity (`"500 nm"`, `"8.854187817e-12 F/m"`,
  `"5 W/m^2"`), a unit (`"F/m"`) and an expression of named quantities — a
  model's parameters (`"gap / 2 + 1 nm"`): numbers, unit symbols and the names
  given; `+` and `-` between terms of one dimension; `*`, `/` and
  juxtaposition (`500 nm`, `kg m/s^2`), left to right, binding tighter than
  `+` and `-`; parentheses; a unary `-`; `^` with an integer, on a unit symbol
  only. A name given is read before a unit symbol; a model refuses a parameter
  named like a unit ([`models.md`](models.md) § 3). Nothing else is read.
- **The table is data**: each base dimension with its canonical unit as
  written; each unit in order, either a base dimension times an exact `factor`
  or `equals`, an expression of units above it, and whether SI prefixes apply
  to it; each prefix with its power of ten. Loading refuses a text that reads
  two ways — a unit that is also a prefixed unit, or two prefixed readings of
  one text — a unit that is not positive, and a canonical unit that is not
  exactly one of its dimension.
- **Refused**, as a `UnitError` naming the text: a symbol that is neither a
  unit nor a name given; terms of different dimensions added or subtracted,
  quoting both; a conversion to a unit of another dimension, naming both; a
  power on anything but a unit symbol, or one that is not an integer; a
  division by zero; anything outside the grammar. Raised inside a schema
  validator, it is that field's problem (§ 2).
- A value is shown to a person only by a surface: in a study's display units,
  else in its canonical unit ([`models.md`](models.md) § 5).
