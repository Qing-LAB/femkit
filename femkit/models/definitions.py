"""A project's definitions (models.md § 3; ADR 0021, amended by ADR 0022): each shared value of a
project, by its name in `project.toml`'s `[definitions]` — its address `project:definitions.<name>`
(projects.md § 5) — a typed number with its unit, written as its value or computed by a function
of the project's `definitions.py`.

- **The table** (`Definition`, which the project file's schema holds): a typed value (`Typed`,
  `femkit/models/typed.py`) — its `type` and its `unit`, the one rule of which is `unit_said`'s —
  and exactly one of `value`, a number of its type — a complex one `[real, imaginary]` — and
  `function`, the function that computes it.
- **`definitions.py`, read without running it** (`read`, by the one static reader of a file of the
  person's functions, `femkit/engines/person/functions.py`): its top level
  holds only imports and functions; it imports only `project.definitions`, as `defs`, the modules
  `model_prep` declares it provides, and `math` and `cmath`; each function's line, whether it
  takes arguments, each `defs.<name>` it reads and each of the file's functions it calls — so each
  computed definition's reads, through every function it calls, give their order and their
  circles (`declared`).
- **Resolved** (`declared`, `defined`): every constant in SI, exactly — an angle in degrees
  (core.md § 11) — and the computed ones in their order; for the check frame, every real value at
  hand by name, the computed ones computed where the operation computes them (`defined`).
- **Computed** (`Computing`): femkit's program in `model_prep`,
  `femkit/engines/person/definitions.py`, as `programs.toml` declares it — its environment and
  its time limit — run through the one door into it (envs.md § 4.4), where its state allows its
  use (§ 3.3), handed the document the program defines and its JSON lines read through `persist`,
  once per distinct request: its values kept in femkit's cache by the SHA-256 of what they rest
  on — `definitions.py`, the `[definitions]` table, `model_prep`'s install fingerprint and the
  sets of constants, and the study they are kept for — so a plan's preview and its apply run it
  once (api.md § 3). Each result is recorded as returned, by the one check of a typed value; a
  case reads it exactly. The program writes them through the one store's writer, with their
  metadata and their provenance — the study, the SHA-256 of `definitions.py` and of the
  `[definitions]` table, the environment and its install fingerprint — and no time (`KeptValues`,
  read by the one reader, `persist.read_record`, core.md § 4).
- **Kept** (`Keeping`): a study's values as `study prep` keeps them, `computed/<study>/definitions.nc`,
  read where its provenance is that of now — the study, the SHA-256s and the fingerprint — never
  otherwise: a computed value not kept in sync at a point is not at hand there, and the point's
  case waits for `study prep`.

Its findings, each an `Issue` (core.md § 10):
- at the definition's key, `definitions.<name>`: `bad-name`, a name a function cannot read as
  `defs.<name>`; `value-or-function`, both or neither; `definition-circle`, definitions whose
  functions read each other in a circle; `function-failed`, a function that raised, returned no
  finite number of its type — an `int` a whole number, however written — or ran past the time
  limit — its file and line said;
- at `definitions.<name>.value`: `wrong-type`, a value not of its type, said in plain words — a
  number of its type, its unit written apart, in `unit`;
- at `definitions.<name>.unit`: `bad-unit`, a unit femkit does not read as one, or an `int`'s other
  than `1`;
- at `definitions.<name>.function`: `no-such-function`, a function `definitions.py` lacks — its
  functions the choices;
- at `definitions.py` and its line: `not-python`, a text Python does not read; `top-level`, a
  statement at its top level that is neither an import nor a function; `bad-import`, an import of
  anything else; `takes-arguments`, a definition's function that takes any; `no-such-definition`,
  a `defs.<name>` naming no definition; `function-failed`, the file failing as it is imported;
- the refusal of the one door into `model_prep`, its code and subject (error): a project with a
  computed definition, checked where `model_prep`'s state does not allow its use — `not-allowed`,
  with that state's own next steps, or the lock's `held` while another command holds it (envs.md
  § 3.3).
"""

from __future__ import annotations

import keyword
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Protocol

from pydantic import Field

from femkit.core import dirs, persist, text, view
from femkit.core.errors import Refusal, Refused
from femkit.core.issues import Issue
from femkit.core.operations import Context
from femkit.core.schema import Model, meant
from femkit.core.units import Dimension, Quantity, Units
from femkit.definitions import catalogue
from femkit.engines.person import definitions as program
from femkit.engines.person import functions as reader
from femkit.engines.person.functions import Fault, Written
from femkit.envs import inside
from femkit.envs import state as env_state
from femkit.projects.requests import PROJECT_CHECK
from femkit.projects import door
from femkit.projects.addresses import Address
from femkit.projects.checking import DEFINITION, Defined, at_line
from femkit.projects.door import Held, Opened
from femkit.models.typed import Typed, unit_said

#: femkit's program that runs a project's `definitions.py`, by its name in `programs.toml`, which
#: declares the environment it runs in — `model_prep` — and its time limit (models.md § 3; envs.md
#: § 4.4).
DEFINITIONS = "definitions"
#: How `definitions.py` imports `project.definitions`, and the modules it may import beside it and
#: those `model_prep` declares (models.md § 3).
FILE, MODULE, ALIAS = "definitions.py", "project.definitions", "defs"
ALWAYS = ("math", "cmath")
#: Where a run's values are kept in femkit's cache, by the SHA-256 of what they rest on.
CACHE = "definitions"

Plain = int | float | complex          # a value as a function reads it, and returns it: in SI


class Definition(Typed):
    """One definition (models.md § 3): a typed value — its number's type and its unit — written as
    its value or computed by its function."""

    value: Any = Field(default=None, description="its value, a number of its type — a `float` may be written `10`, "
                                                 "a `complex` as `[real, imaginary]` — its unit written apart, in "
                                                 "`unit`; else `function`")
    function: str | None = Field(default=None, description="else the name of the function in the project's "
                                                           "`definitions.py` that computes it: it takes no "
                                                           "arguments, reads every other definition as "
                                                           "`defs.<name>`, a plain number in SI units — an angle in "
                                                           "degrees — and returns its own the same way")


# ------------------------------------------------------------------ definitions.py, read without running it

def read(text: str, modules: Iterable[str]) -> Written:
    """``text``, a project's `definitions.py`, read without running it (models.md § 3) by the one
    static reader of a file of the person's functions (`functions.read`): it may import
    `project.definitions` as `defs`, ``modules`` — those `model_prep` provides — `math` and
    `cmath`."""
    return reader.read(text, name=FILE, modules=modules, gives=(MODULE, ALIAS), always=ALWAYS)


# ------------------------------------------------------------------ the definitions, resolved

@dataclass(frozen=True)
class Declared:
    """A project's definitions as read and checked before anything runs (models.md § 3): the
    table; each definition's unit's dimension, where it reads; each real constant in SI exactly,
    each complex one as its real and imaginary parts, both exact; the computed ones that can be
    computed, in their order, each with every computed one it reads; `definitions.py` as held and
    as read; each name with a finding of its own, or resting on one; and every finding."""

    table: dict[str, Definition] = field(default_factory=dict)
    dimensions: dict[str, Dimension] = field(default_factory=dict)
    exact: dict[str, Quantity] = field(default_factory=dict)
    complexes: dict[str, tuple[Fraction, Fraction]] = field(default_factory=dict)
    order: tuple[str, ...] = ()
    needs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    held: Held | None = None
    written: Written | None = None
    broken: frozenset[str] = frozenset()
    issues: tuple[Issue, ...] = ()

    def constants(self, at: Mapping[str, Quantity] | None = None) -> dict[str, Plain]:
        """A set of the constants as a function reads them, each a plain number of its type in
        SI: as written, but each ``at`` gives — a point's — in its place."""
        given = {**self.exact, **(at or {})}
        out: dict[str, Plain] = {n: (int(q.value) if self.table[n].type == "int" else float(q.value))
                                 for n, q in given.items() if n in self.table and n not in self.broken}
        out |= {n: complex(float(r), float(i)) for n, (r, i) in self.complexes.items()}
        return dict(sorted(out.items()))


def project_file(opened: Opened) -> Any:
    """The project file as loaded; None where it does not load."""
    part = opened.parts.get(opened.layout.project_kind)
    return part.data if part is not None else None


def held(opened: Opened) -> Held | None:
    """`definitions.py` as the project opened holds it — the one file the layout declares the
    project file may hold at the project's top (projects.md §§ 2, 4); None where it is not there."""
    (name,) = opened.layout.kinds[opened.layout.project_kind].optional
    return opened.held_by(Address(opened.layout.project_kind, None)).get(name)


def environment(ctx: Context) -> str:
    """The environment a project's `definitions.py` runs in, as its program's declaration names it:
    `model_prep` (models.md § 3)."""
    return inside.program(ctx, DEFINITIONS).environment


def provided(ctx: Context) -> list[str]:
    """The modules `model_prep` provides, as its declaration lists them: what `definitions.py`
    may import beside `project.definitions`, `math` and `cmath`."""
    return list(catalogue.environments(ctx)[environment(ctx)].provides.modules)


def declared(opened: Opened, ctx: Context) -> Declared:
    """The project's definitions read and checked before anything runs (models.md § 3), once per
    invocation for ``opened``."""
    return ctx.cached(f"definitions {id(opened)}", lambda: _declared(opened, ctx))


def _declared(opened: Opened, ctx: Context) -> Declared:
    units = catalogue.units(ctx)
    data = project_file(opened)
    table: dict[str, Definition] = dict(data.definitions) if data is not None else {}
    kind = opened.layout.project_kind
    found: list[Issue] = []
    broken: set[str] = set()

    def at(name: str, *keys: str) -> Address:
        return Address(kind, None, (*opened.layout.objects[DEFINITION].keys, name, *keys))

    def finding(name: str, *keys: str, code: str, message: str, right: Any = None, choices: Iterable[Any] = ()
                ) -> None:
        found.append(door.finding(opened, at(name, *keys), code=code, message=message,
                                  right=None if right is None else persist.inline_text(right),
                                  choices=[persist.inline_text(c) for c in choices]))
        broken.add(name)

    dimensions: dict[str, Dimension] = {}
    exact: dict[str, Quantity] = {}
    complexes: dict[str, tuple[Fraction, Fraction]] = {}
    for name, d in table.items():
        if not name.isidentifier() or keyword.iskeyword(name):
            finding(name, code="bad-name", message=f"`{name}` is no name a function reads as `{ALIAS}.{name}`: "
                                                   "letters, digits and `_`, not starting with a digit, and no word "
                                                   "Python keeps")
        if (d.value is None) == (d.function is None):
            finding(name, code="value-or-function",
                    message=f"`{name}` states {'both' if d.value is not None else 'neither'} of `value` and "
                            "`function`: a definition is written as its value, or computed by its function")
        said = unit_said(units, d, name)
        if said.problem is not None:
            finding(name, "unit", code="bad-unit", right=said.right, message=said.problem)
        if said.dimension is None:
            continue
        dimensions[name] = said.dimension
        one = units.unit(d.unit)
        if d.value is None:
            continue
        held_value = _typed(d)
        if held_value is None:
            finding(name, "value", code="wrong-type",
                    message=f"`{name}`'s value is {_shown(d.value)}, and a value here is {_TYPES[d.type]}; its "
                            "unit is written apart, in `unit`")
        elif name not in broken:
            if d.type == "complex":
                complexes[name] = (held_value[0] * one.value, held_value[1] * one.value)
            else:
                exact[name] = Quantity(held_value * one.value, one.dimension)
    held_file = held(opened)
    written = None
    if held_file is not None:
        try:
            written = read(held_file.data.decode("utf-8"), provided(ctx))
        except UnicodeDecodeError as exc:
            written = Written({}, (Fault(None, "not-python", f"definitions.py is not text written in UTF-8: byte "
                                                             f"{exc.start + 1} is not"),))
        found += [at_line(opened, held_file, f) for f in written.faults]
    functions = written.functions if written is not None else {}
    runs = written is not None and not written.faults        # a file with a fault runs nothing
    for name, d in table.items():
        if d.function is None or d.value is not None:
            continue
        if not runs:
            broken.add(name)
        if d.function not in functions:
            finding(name, "function", code="no-such-function", choices=sorted(functions),
                    message=f"definitions.py holds no function `{d.function}`" + meant(d.function, functions))
        elif functions[d.function].takes:
            found.append(at_line(opened, held_file, Fault(functions[d.function].line, "takes-arguments",
                                                          f"`{d.function}` computes `{name}`, and takes no arguments: "
                                                          f"it reads every definition as `{ALIAS}.<name>`")))
            broken.add(name)
    for fname, function in functions.items():
        for read_, line in function.reads.items():
            if read_ not in table:
                found.append(at_line(opened, held_file, Fault(line, "no-such-definition",
                                                              f"`{ALIAS}.{read_}` names no definition"
                                                              + meant(read_, table, shown=lambda n: f"{ALIAS}.{n}"))))
    reads = {n: list(written.reads(d.function)) for n, d in table.items()
             if d.function is not None and d.value is None and written is not None and d.function in functions}
    broken |= {n for n, r in reads.items() if set(r) - set(table)}     # it reads what no definition is
    order, circles = _ordered(reads)
    for circle in circles:
        finding(circle[0], code="definition-circle",
                message=f"the definitions {' → '.join(circle)} are computed from each other in a circle")
    resting = {n for n in order if set(_all(reads, n)) & broken} | broken
    return Declared(table=table, dimensions=dimensions, exact=exact, complexes=complexes,
                    order=tuple(n for n in order if n not in resting),
                    needs={n: tuple(r for r in _all(reads, n) if r in reads) for n in order},
                    held=held_file, written=written, broken=frozenset(resting), issues=tuple(found))


def _typed(d: Definition) -> Any:
    """A written value as its type holds it, exactly — an `int` a whole number, `4` or `4.0`; a
    `float` a finite number, a whole one among them; a `complex` a pair of them — or None where it
    is not one: a text, a truth value, TOML's `inf` or `nan`, a list where one number belongs."""
    def real(v: Any) -> Fraction | None:
        return Fraction(v) if isinstance(v, (int, Decimal)) and not isinstance(v, bool) else None
    if d.type == "int":
        whole = real(d.value)
        return whole if whole is not None and whole.denominator == 1 else None
    if d.type == "float":
        return real(d.value)
    if isinstance(d.value, list) and len(d.value) == 2 and None not in (pair := [real(v) for v in d.value]):
        return tuple(pair)
    return None


#: What a value of each type is, as a finding says it (models.md § 3).
_TYPES = {"int": "a whole number of its type (`int`)", "float": "a number of its type (`float`)",
          "complex": "a pair of numbers of its type (`complex`), `[real, imaginary]`"}


def _shown(value: Any) -> str:
    """A value as the project file writes it, for a sentence."""
    try:
        return persist.inline_text(value)
    except (TypeError, ValueError):
        return repr(value)


def _all(reads: Mapping[str, list[str]], name: str) -> list[str]:
    """Every definition ``name``'s function reads, through every computed one it reads."""
    out, walking = [], list(reads.get(name, []))
    while walking:
        now = walking.pop(0)
        if now not in out:
            out.append(now)
            walking += reads.get(now, [])
    return out


def _ordered(reads: Mapping[str, list[str]]) -> tuple[list[str], list[list[str]]]:
    """The computed definitions in the order their reads give — each after every computed one it
    reads, else as the table writes them — and each circle, from where it was met back to it."""
    order: list[str] = []
    circles: list[list[str]] = []
    walking: list[str] = []
    stuck: set[str] = set()

    def visit(name: str) -> None:
        if name in order or name in stuck:
            return
        if name in walking:
            circle = [*walking[walking.index(name):], name]
            circles.append(circle)
            stuck.update(circle)
            return
        walking.append(name)
        for used in reads[name]:
            if used in reads:
                visit(used)
        walking.pop()
        if name not in stuck and not any(u in stuck for u in reads[name]):
            order.append(name)
        else:
            stuck.add(name)

    for name in reads:
        visit(name)
    return order, circles


def defined(opened: Opened, ctx: Context, *, compute: bool) -> Defined:
    """The project's definitions as the check frame holds them (projects.md § 6; models.md § 3):
    every real constant, and — with ``compute``, as `project check` and `study prep` compute them —
    every computed one as its function returns it for the constants as written, each failure a
    finding at its definition's key, its file and line said; `model_prep` not installed, a finding
    naming its install. Without, a computed one is not at hand: no other reader runs a function
    (models.md § 3)."""
    d = declared(opened, ctx)
    values = dict(d.exact)
    issues = list(d.issues)
    if compute and d.order:
        try:
            ran = Computing(ctx, opened, d).run([d.constants()])
        except Refusal as exc:   # model_prep may not be used here, or no manager enters it: a finding
            issues.append(Issue.of(exc, "error"))
        else:
            issues += ran.findings(opened, d)
            if ran.values:
                values |= quantities(d, ran.values[0])
    real = {n for n, t in d.table.items() if t.type != "complex"}
    return Defined(values=values, dimensions=dict(d.dimensions), unresolved=frozenset(real - set(values)),
                   complex=frozenset(set(d.table) - real), issues=tuple(issues))


def quantities(d: Declared, values: Mapping[str, Plain]) -> dict[str, Quantity]:
    """Each computed real definition's value, as its function returned it, exactly, in SI."""
    return {n: Quantity(Fraction(v), d.dimensions[n]) for n, v in values.items()
            if n in d.order and d.table[n].type != "complex" and n in d.dimensions}


def shown(units: Units, d: Declared, name: str, value: Plain) -> str:
    """A value as a person reads it, by the core's one formatter (`Units.shown`): converted from SI
    into its definition's declared unit (models.md § 3), its decimal where it has one — `5 nm`; a
    complex one its two parts in brackets."""
    unit = d.table[name].unit
    dimension = units.unit(unit).dimension
    if isinstance(value, complex):
        parts = [units.shown(Quantity(Fraction(v), dimension), (unit,)).removesuffix(f" {unit}")
                 for v in (value.real, value.imag)]
        return f"[{', '.join(parts)}]" + ("" if unit == "1" else f" {unit}")
    return units.shown(Quantity(Fraction(value), dimension), (unit,))


# ------------------------------------------------------------------ computed in model_prep

class Values(Protocol):
    """Where a study's computed values come from, for each point's set of constants: computed
    (`Computing`), or kept (`Keeping`) — each set's values, every constant and computed definition
    by name, or None where they are not at hand; the project's definitions as declared, ``d``."""

    d: Declared

    def at(self, sets: list[dict[str, Plain]]) -> list[dict[str, Plain] | None]: ...


def digest(d: Declared) -> str:
    """The SHA-256 of the `[definitions]` table, as the project file writes it (models.md § 3)."""
    return persist.canonical_sha256({n: t.model_dump(mode="json") for n, t in d.table.items()})


def fingerprint(ctx: Context) -> str | None:
    """`model_prep`'s install fingerprint, as its manifest records the install — None where it has
    none (envs.md §§ 2, 4.3): never read from its state, so one another command holds — a validate
    — is the install it is."""
    f = env_state.facts(ctx, environment(ctx))
    return f.manifest.install_fingerprint if f.manifest is not None else None


def attributes(ctx: Context, d: Declared, study: str | None) -> dict[str, str]:
    """A study's values' provenance and what they rest on, as their file's attributes (models.md
    § 3): the study they are kept for — none for `project check`'s, which keeps nothing — the
    SHA-256 of `definitions.py`, the script that computes them, and of the `[definitions]` table, and
    the environment it ran in with its install fingerprint."""
    return {"study": study or "", "script_sha256": d.held.sha256 if d.held is not None else "",
            "definitions_sha256": digest(d), "environment": environment(ctx), "fingerprint": fingerprint(ctx) or ""}


def described(opened: Opened, name: str) -> str:
    """What a definition is, as its file says it (models.md § 3): the comment above its table, else
    its name — the `long_name` its kept values carry."""
    part = opened.parts.get(opened.layout.project_kind)
    written = opened.texts.get(part.file) if part is not None else None
    keys = (*opened.layout.objects[DEFINITION].keys, name)
    found = next((k.comment for k in persist.key_comments(written or "") if k.path == keys and k.comment), None)
    return found or name


class KeptVariable(Model):
    """One definition's values along `point`, as the one store holds it (models.md § 3)."""

    dimensions: list[Literal["point"]] = Field(description="the dimension its values lie along")
    attributes: dict[str, str] = Field(description="its metadata: `units`, its values' SI unit; `declared_unit`; "
                                                   "`long_name`; `declared_type`")
    values: list[int | float | complex] = Field(description="its value at each set of the constants, in SI")


class KeptAttributes(Model):
    """What a file of kept values says of itself (models.md § 3): its shape, and its provenance."""

    schema_: Literal[program.SHAPE] = Field(alias="schema", description="the shape of the file, raised when it "
                                                                         "changes", json_schema_extra={"doc": "models.md § 2"})
    study: str = Field(description="the study it is kept for; none for a run that keeps nothing")
    script_sha256: str = Field(description="the SHA-256 of `definitions.py`, the script that computed it")
    definitions_sha256: str = Field(description="the SHA-256 of the project file's `[definitions]` table")
    environment: str = Field(description="the environment its script ran in")
    fingerprint: str = Field(description="that environment's install fingerprint")


class KeptValues(Model):
    """A file of a project's computed definitions' values — `computed/<study>/definitions.nc`, or a
    run's in femkit's cache — read by the one reader (`persist.read_record`, core.md § 4)."""

    attributes: KeptAttributes = Field(description="its shape and provenance")
    variables: dict[str, KeptVariable] = Field(description="each definition, constant or computed, by its name")

    def entries(self) -> list[dict[str, Plain]]:
        """Each set's values, every definition by its name as a plain number of its type."""
        n = len(next(iter(self.variables.values())).values) if self.variables else 0
        return [{name: v.values[i] for name, v in self.variables.items()} for i in range(n)]

    def rests_on(self) -> dict[str, str]:
        """Its attributes beside its shape: what it is kept for and rests on."""
        return self.attributes.model_dump(exclude={"schema_"})


@dataclass(frozen=True)
class Ran:
    """What a run gave, or the cache held: each set's values — every constant and every computed
    definition, a plain number of its type in SI — and the file in femkit's cache holding them; or
    each failure, as the program says it."""

    values: list[dict[str, Plain]] = field(default_factory=list)
    file: Path | None = None
    failures: list[dict[str, Any]] = field(default_factory=list)

    def findings(self, opened: Opened, d: Declared, points: list[str] | None = None) -> list[Issue]:
        """Each failure as a finding (models.md § 3): at its definition's key, its file and line
        said, and, given ``points`` — each set as a person names it — the point it failed at; one
        failing as the file is imported, at the file and its line."""
        out = []
        for f in self.failures:
            if f["definition"] is None:
                out.append(at_line(opened, d.held, Fault(f["line"], "function-failed", f"definitions.py {f['reason']}")))
                continue
            name = f["definition"]
            where = f" at {points[f['point']]}" if points and f.get("point") is not None else ""
            line = f", line {f['line']}" if f.get("line") else ""
            out.append(door.finding(opened, Address(opened.layout.project_kind, None,
                                                    (*opened.layout.objects[DEFINITION].keys, name)),
                                    code="function-failed",
                                    message=f"`{d.table[name].function}`, which computes `{name}`, {f['reason']}"
                                            f"{where} ({d.held.file if d.held else 'definitions.py'}{line})"))
        return out


@dataclass
class Computing:
    """A project's computed definitions computed in `model_prep` by femkit's program there
    (models.md § 3), each distinct request once, kept in femkit's cache."""

    ctx: Context
    opened: Opened
    d: Declared
    ran: Ran | None = None      # the last run `at` asked for: what a study keeps (models.md § 3)
    study: str | None = field(default=None, kw_only=True)   # the study its values are kept for, if any

    def document(self, sets: list[dict[str, Plain]]) -> dict:
        """What the program is handed, in the shape it defines (`program.document`): each
        definition, the order, the sets, and what its values rest on."""
        units = catalogue.units(self.ctx)
        written = self.d.written
        definitions = {}
        for name, t in self.d.table.items():
            if name in self.d.broken or name not in self.d.dimensions:
                continue
            spec: dict[str, Any] = {"type": t.type, "units": units.si(self.d.dimensions[name]), "declared_unit": t.unit,
                                    "long_name": described(self.opened, name)}
            if name in self.d.order:
                spec |= {"function": t.function, "line": written.functions[t.function].line,
                         "needs": list(self.d.needs[name])}
            definitions[name] = spec
        return program.document(self.d.held.name, definitions, list(self.d.order),
                                [{n: [v.real, v.imag] if isinstance(v, complex) else v for n, v in s.items()}
                                 for s in sets], attributes(self.ctx, self.d, self.study))

    def run(self, sets: list[dict[str, Plain]]) -> Ran:
        """The values at each of ``sets`` (models.md § 3): from femkit's cache where a run of the
        same request kept them, else from a run of the program in `model_prep`, through the one
        door into it, within its declared time limit (envs.md § 4.4). Refused where `model_prep`'s
        state does not allow its use, with that state's own next steps (envs.md § 3.3)."""
        env_state.usable(self.ctx, environment(self.ctx), "the project's computed definitions")
        document = self.document(sets)
        key = persist.canonical_sha256(document)
        kept = dirs.cache_dir() / CACHE / f"{key}.nc"
        return self.ctx.cached(f"definitions run {key}", lambda: self._ran(document, kept))

    def _ran(self, document: dict, kept: Path) -> Ran:
        held = persist.read_record(kept, KeptValues)
        if held.reads:
            return Ran(values=held.value.entries(), file=kept)
        work = kept.with_suffix(".work")
        persist.remove(work)
        persist.write_folder(work, {self.d.held.name: self.d.held.data,
                                    "document.json": persist.json_text(document).encode("utf-8")})
        declared = inside.program(self.ctx, DEFINITIONS)
        where = inside.entered(self.ctx, declared.environment)
        result = where.run(where.program(declared, "document.json", "values.nc"), declared=declared, cwd=work,
                           log=work / "definitions.log")
        said = [line for line in (_json(t) for t in result.stdout.splitlines()) if line is not None]
        if result.timed_out:
            last = next((s for s in reversed(said) if program.COMPUTING in s), None)
            persist.remove(work)
            return Ran(failures=[{"definition": last[program.COMPUTING] if last else None,
                                  "point": last[program.POINT] if last else None, "line": None,
                                  "reason": f"did not return within {declared.timeout} s, the time limit of "
                                            f"femkit's program in {declared.environment}"}])
        failures = next((s[program.FAILURES] for s in reversed(said) if program.FAILURES in s), None)
        if failures is None or (result.ok and failures):
            raise RuntimeError(f"femkit's program in {declared.environment} ended with {result.returncode} and said "
                               f"nothing of its definitions: its log is {work / 'definitions.log'}")
        if failures:
            persist.remove(work)
            return Ran(failures=list(failures))
        persist.move(work / "values.nc", kept)
        persist.remove(work)
        held = persist.read_record(kept, KeptValues)
        if not held.reads:
            raise RuntimeError(f"femkit's program in {declared.environment} wrote values that do not read: "
                               f"{held.problem}")
        return Ran(values=held.value.entries(), file=kept)

    def at(self, sets: list[dict[str, Plain]]) -> list[dict[str, Plain] | None]:
        """Each set's values, every set computed in one run; refused, `has-findings`, at the first
        definition that failed, its file and line said (workflow.md § 7). With no computed
        definition, each set as it is: nothing runs."""
        if not self.d.order:
            return [dict(s) for s in sets]
        ran = self.ran = self.run(_distinct(sets))
        if ran.failures:   # every finding it rests on carried, shown before its sentence (core.md § 9)
            found = ran.findings(self.opened, self.d, [_point(self.d, s) for s in _distinct(sets)])
            raise Refused(f"{text.count(len(found), 'computed definition')} did not compute",
                          (view.command(PROJECT_CHECK, project=self.opened.project.name),),
                          code="has-findings", subject=found[0].subject, issues=found)
        by_set = {_key(self.d, v): v for v in ran.values}
        return [by_set.get(_key(self.d, s)) for s in sets]


def _json(text: str) -> dict | None:
    """One line the program says, a JSON object, read through `persist`; None for any other line of
    its log."""
    try:
        found = persist.json_value(text)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def _distinct(sets: list[dict[str, Plain]]) -> list[dict[str, Plain]]:
    """Each distinct set, in the order they first come."""
    out: dict[str, dict[str, Plain]] = {}
    for s in sets:
        out.setdefault(persist.canonical_sha256(_plain(s)), s)
    return list(out.values())


def _plain(s: Mapping[str, Plain]) -> dict:
    return {n: [v.real, v.imag] if isinstance(v, complex) else v for n, v in s.items()}


def _key(d: Declared, values: Mapping[str, Plain]) -> str:
    """A set of the constants as a key: each constant's value, the computed ones left out."""
    return persist.canonical_sha256(_plain({n: v for n, v in values.items() if n not in d.order and n in d.table}))


def _point(d: Declared, values: Mapping[str, Plain]) -> str:
    """A set of the constants as a person names it, each differing from its written value."""
    written = d.constants()
    differs = {n: v for n, v in values.items() if n in written and written[n] != v}
    return ", ".join(f"{n} = {v!r} in SI" for n, v in differs.items()) or "the constants as written"


# ------------------------------------------------------------------ kept by `study prep`

@dataclass
class Keeping:
    """A study's computed values as `study prep` keeps them (models.md § 3): each set's, where its
    file's SHA-256s and fingerprint are those of now; none otherwise — never a value used
    silently."""

    ctx: Context
    opened: Opened
    d: Declared
    study: str

    def entries(self) -> list[dict[str, Plain]] | None:
        """The kept values, each set's; None where there are none, they do not read, or they are not
        in sync — kept for another study, or resting on another script, table or install."""
        held = door.read_record(self.opened, door.definitions_file(self.opened, self.study), KeptValues)
        if not held.reads:
            return None
        return held.value.entries() if held.value.rests_on() == attributes(self.ctx, self.d, self.study) else None

    def at(self, sets: list[dict[str, Plain]]) -> list[dict[str, Plain] | None]:
        """Each set's values as kept in sync; None for a set they do not hold. With no computed
        definition, each set as it is: nothing is kept."""
        if not self.d.order:
            return [dict(s) for s in sets]
        entries = self.entries() or []
        by_set = {_key(self.d, v): v for v in entries}
        return [by_set.get(_key(self.d, s)) for s in sets]

