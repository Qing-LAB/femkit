"""An observables part, `observables/<o>/` (models.md § 5.2): its file, `observables.toml`, and its
script, `observe.py` — the `models.observables` part schema and its check. It reads studies after
they solve, naming each; a study names none. Each observable is a typed value, declared as a
definition is (`typed.Typed`, models.md § 3) — what it takes, the project's definitions and groups
of its studies' components, and what it gives, its type, its unit and, for an array over the
case's own dimensions, `dims` — and computed by its function in `observe.py`, which takes one
argument, `case`. The function runs with its observe stage (plan § 4, M6); before anything runs,
`observe.py` is read without running it, by the one static reader of a file of the person's
functions (`engines/person/functions.py`), told this signature, the tables of `case` it tracks and
what it may import: what the environment the observe stage kind declares provides — `postprocess`
(workflow.md § 2.1) — and the packages the project declares (models.md § 2).

Its findings, each at its key, once per key and code however many values or studies show it
(core.md § 10), the observables' table the layout's declaration (`observable`):
- `no-such-part` (error), at `studies`: a study the project lacks (`parts.cited`);
- at `observables.<n>.function`: `no-such-function` (error), a function `observe.py` lacks — its
  functions the choices; `takes-arguments` (error), one that does not take one argument;
- at `observables.<n>.takes.definitions`: `no-such-definition` (error), each definition the
  project lacks — its definitions the choices;
- at `observables.<n>.takes.definitions` or `.takes.groups`: `not-taken` (error), each
  `case.defs.<name>` or `case.groups.<name>` its function reads — or a function of `observe.py` it
  calls, handed `case` first — that its `takes` does not list, with its line (`HANDED`);
- at `observables.<n>.takes.groups`: `not-promised` (error), each group a component of the studies
  it reads does not promise, naming those studies — the groups every such component promises the
  choices;
- at `observables.<n>.unit`, or `observables.<n>.dims.<d>`: `bad-unit` (error), a unit that does
  not read, or an `int`'s that is not `1`;
- at `observables.<n>`: `observable-twice` (error), a name each part reading one of its studies
  before it, in the reading order (projects.md § 4), gives an observable too;
- at `observe.py` and its line: `not-python`, `top-level`, `bad-import` (error), as the static
  reader says them — an import of anything the environment the observe stage runs in and the
  project's packages do not give among them, said with what would be right: its package added to
  the project file's `[postprocess] packages`, the line said whole (`project.adding`) — its subject
  the file's address, so the part's state counts it (`checking.at_line`).
An error on it holds back its own observe stages alone: it is no part a study uses (§ 5.3).
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Generator, Iterator, Literal

from pydantic import Field

from femkit.core import text
from femkit.core.issues import Issue
from femkit.core.schema import Model, as_quantity, as_reference, meant, whole
from femkit.core.units import UnitError
from femkit.engines.person import functions
from femkit.models import project as projects
from femkit.models.parts import Contract, cited, contract, listed, objects
from femkit.models.study import cites
from femkit.models.typed import Typed, unit_said
from femkit.projects.checking import DEFINITION, Checking, Registration, at_line
from femkit.projects.door import Part
from femkit.projects.names import STEP
from femkit.projects.schemas import PartFile

KEY = "models.observables"   # the key the layout names this schema by (projects.md § 4)
OBSERVABLE = "observable"    # its object type, whose table the layout's declaration names (projects.md § 4)
SCRIPT = "observe.py"        # the file of its functions, the one its kind fixes (projects.md § 4)
ARGUMENTS = 1                # an observable's function takes one argument, `case` (models.md § 5.2)
#: What `case` hands a function of what its `takes` lists: each field of `takes`, with the table of
#: `case` it is read from, `case.defs.<name>` and `case.groups.<name>` (models.md § 5.2) — the one
#: statement of both sides, which the static reader tracks (`not-taken`) and the observe stage's
#: runner hands (M6).
HANDED = {"definitions": "defs", "groups": "groups"}

Name = Annotated[str, Field(pattern=whole(STEP))]   # an observable's name: one step of the name rule


class Takes(Model):
    """What an observable's function takes of a case beside its solve's run (models.md § 5.2) —
    the one statement of what it uses; the standard forms an output translator gives join with
    M6."""

    definitions: list[str] = as_reference("the project's definitions it reads, by name, each at the case's point, in "
                                          "SI units, as `case.defs.<name>`", "definition", default_factory=list)
    groups: list[str] = as_reference("groups of the components of the studies it reads, by name, each as the built "
                                     "geometry holds it, with its regions in the case's mesh, as `case.groups.<name>`",
                                     "group", default_factory=list)


class Observable(Typed):
    """One observable (models.md § 5.2): its function, what it takes, and what it gives, a typed
    value — a number, or an array over the case's own dimensions."""

    function: str = Field(description="the name of its function in the part's `observe.py`: it takes one argument, "
                                      "`case`, and returns a number of its type, or an xarray DataArray of it over "
                                      "its `dims`, in SI units")
    takes: Takes = Field(default_factory=Takes, description="what its function reads of the case beside its solve's "
                                                            "run: definitions, groups")
    dims: dict[Name, str] = as_quantity("for an array, each of its dimensions by name, with the unit of its "
                                        "coordinate — `{ x = \"nm\" }`, a profile along a line; none: one number",
                                        "unit", default_factory=dict)


class ObservablesPart(PartFile):
    """`observables/<o>/observables.toml`: the studies it reads, and each observable, computed by its
    function in `observe.py` beside it (models.md § 5.2)."""

    CHANGES: ClassVar[dict[int, str]] = {
        2: "an observables part is a folder, `observables/<name>/`, holding `observables.toml` — the studies it "
           "reads, and each observable's function, what it takes and its type and unit — and `observe.py`, the "
           "function that computes each; a study names no observables, and the declared form of `quantity`, "
           "`point`, `line`, `group`, `side` and `reduction` is gone"}

    schema_: Literal[2] = Field(alias="schema", description="the version of this file's format, which femkit raises "
                                "when it changes how files of this kind are written",
                                json_schema_extra={"doc": "models.md § 2"})
    studies: list[str] = as_reference("the studies it reads, by name: any whose components promise the groups it "
                                      "takes", "study", min_length=1, extra={"doc": "models.md § 5.2"})
    observables: dict[Name, Observable] = Field(default_factory=dict, description="its observables, by name, unique "
                                                "across the parts reading one study: each computed by its function",
                                                json_schema_extra={"doc": "models.md § 5.2"})


def check(c: Checking, part: Part) -> Iterator[Issue]:
    """The part's own rules, then what it reads of its studies (module docstring) — each said once
    at its key and code, however many values or studies show it (core.md § 10)."""
    data: ObservablesPart = part.data
    table = c.opened.layout.objects[OBSERVABLE].keys
    yield from cited(c, part)
    written = yield from _script(c, part, data, table)
    project = c.opened.parts.get(c.opened.layout.project_kind)
    known = sorted(objects(c.opened, project, DEFINITION)) if c.known else None
    for name, o in data.observables.items():
        at = (*table, name)
        missing = [d for d in o.takes.definitions if d not in known] if known is not None else []
        if missing:
            yield c.issue(part, *at, "takes", "definitions", code="no-such-definition", label=missing[0],
                          choices=known, message=f"`{name}` takes {_the('definition', missing)}, which the project "
                                                 "does not define" + (meant(missing[0], known) if len(missing) == 1
                                                                      else ""))
        said = unit_said(c.units, o, name)
        if said.problem is not None:
            yield c.issue(part, *at, "unit", code="bad-unit", right=said.right, message=said.problem)
        for dim, unit in o.dims.items():
            try:
                c.units.unit(unit)
            except UnitError as exc:
                yield c.issue(part, *at, "dims", dim, code="bad-unit",
                              message=f"the unit of `{name}`'s coordinate `{dim}` does not read: {exc}")
        if written is not None and o.function in written.functions:
            yield from _taken(c, part, at, name, o, written)
    yield from _groups(c, part, data, table)
    yield from _twice(c, part, data, table)


def _the(noun: str, names: list[str]) -> str:
    """`the definition `a``, `the definitions `a` and `b``, `the studies …` — the plural every count
    a person reads takes (`text.count`)."""
    return f"the {text.count(len(names), noun).partition(' ')[2]} {listed(names)}"


def _script(c: Checking, part: Part, data: ObservablesPart, table: tuple[str, ...]
            ) -> Generator[Issue, None, functions.Written | None]:
    """`observe.py`, read without running it by the one static reader (models.md § 5.2): each fault
    at its line; each observable's function there, taking one argument. What it may import is what
    the environment the stage that brings this part runs in provides (`Checking.running`; the
    observe stage kind, workflow.md § 2.1) and the packages its project declares (models.md § 2).
    It gives the file as read, none where it is not there or is not text."""
    held = c.opened.held_by(part.address).get(SCRIPT)
    if held is None:
        return None                                           # the door says it is missing
    project = c.opened.parts.get(c.opened.layout.project_kind)
    own = projects.modules(project.data) if project is not None and project.data is not None else []
    try:
        written = functions.read(held.data.decode("utf-8"), name=SCRIPT, handed=HANDED.values(),
                                 modules=[*c.running.get(part.address.kind, ()), *own], beyond=projects.adding)
    except UnicodeDecodeError as exc:
        yield at_line(c.opened, held, functions.Fault(None, "not-python",
                                                      f"{SCRIPT} is not text written in UTF-8: byte {exc.start + 1} "
                                                      "is not"))
        return None
    for f in written.faults:
        yield at_line(c.opened, held, f)
    there = sorted(written.functions)
    for name, o in data.observables.items():
        found = written.functions.get(o.function)
        if found is None and not any(f.code == "not-python" for f in written.faults):
            yield c.issue(part, *table, name, "function", code="no-such-function", label=o.function, choices=there,
                          message=f"{SCRIPT} has no function `{o.function}`" + meant(o.function, there))
        elif found is not None and found.arguments != ARGUMENTS:
            took = "other arguments" if found.arguments is None else \
                f"{found.arguments} argument{'' if found.arguments == 1 else 's'}"
            yield c.issue(part, *table, name, "function", code="takes-arguments", label=o.function,
                          message=f"`{o.function}` takes {took}, and an observable's function takes one, `case`")
    return written


def _taken(c: Checking, part: Part, at: tuple[str, ...], name: str, o: Observable,
           written: functions.Written) -> Iterator[Issue]:
    """What ``o``'s function reads of `case` — itself, or a function of `observe.py` it calls handed
    `case` first — that its `takes` does not list (models.md § 5.2: `takes` is the one statement of
    what it uses): one finding at each `takes` key, naming each read and its line, before anything
    runs (conventions.md § 7)."""
    read = written.handed(o.function)
    for field, handed in HANDED.items():
        listed_ = set(getattr(o.takes, field))
        outside = sorted(((n, line) for (t, n), line in read.items() if t == handed and n not in listed_),
                         key=lambda item: item[1])
        if outside:
            yield c.issue(part, *at, "takes", field, code="not-taken", label=outside[0][0],
                          message=f"`{o.function}`" + (f", which computes `{name}`," if o.function != name else "")
                                  + " reads "
                                  + listed([f"`case.{handed}.{n}` ({SCRIPT}, line {line})" for n, line in outside],
                                           "{}")
                                  + f", and its `takes.{field}` names {_none(outside)}: what a function reads of the "
                                    "case is what its `takes` lists")


def _none(outside: list[tuple[str, int]]) -> str:
    """`no `a``, `neither `a` nor `b``, `none of `a`, `b` and `c``."""
    names = [f"`{n}`" for n, _ in outside]
    if len(names) == 1:
        return f"no {names[0]}"
    if len(names) == 2:
        return f"neither {names[0]} nor {names[1]}"
    return f"none of {', '.join(names[:-1])} and {names[-1]}"


def reads(c: Checking, part: Part) -> list[Part]:
    """The studies ``part`` reads that the project holds and that load (models.md § 5.2)."""
    return [found for name in part.data.studies if (found := cites(c, "studies", name, ObservablesPart)) is not None]


def _groups(c: Checking, part: Part, data: ObservablesPart, table: tuple[str, ...]) -> Iterator[Issue]:
    """Each group an observable takes, one the component of each study the part reads promises
    (models.md §§ 5.1, 5.2): what is not said once at its `takes.groups`, naming each group and, for
    each component lacking one, the studies that solve it — its choices the groups every such
    component promises."""
    held: list[tuple[Contract, Part]] = []
    for study in reads(c, part):
        holder = cites(c, "component", study.data.component)
        k = contract(c.opened, holder) if holder is not None else None
        if k is not None:                                     # else the study's own findings say why
            held.append((k, study))
    for name, o in data.observables.items():
        lacking: dict[str, tuple[Contract, list[str], list[str]]] = {}
        for k, study in held:
            missing = [g for g in o.takes.groups if g not in k.groups]
            if missing:
                entry = lacking.setdefault(str(k.part.address), (k, [], []))
                entry[1].append(study.address.name)
                entry[2].extend(g for g in missing if g not in entry[2])
        if not lacking:
            continue
        groups = list(dict.fromkeys(g for _, _, missing in lacking.values() for g in missing))
        promised = [g for g in held[0][0].groups if all(g in k.groups for k, _ in held)]
        said = "; ".join(f"the component `{k.part.address.name}` {_the('study', studies)} "
                         f"{'solves' if len(studies) == 1 else 'solve'} promises {_none([(g, 0) for g in missing])}"
                         for k, studies, missing in lacking.values())
        yield c.issue(part, *table, name, "takes", "groups", code="not-promised", label=groups[0], choices=promised,
                      message=f"`{name}` takes {_the('group', groups)}, and {said}"
                              + (meant(groups[0], promised) if len(groups) == 1 else ""))


def _twice(c: Checking, part: Part, data: ObservablesPart, table: tuple[str, ...]) -> Iterator[Issue]:
    """Each observable whose name a part reading one of its studies before it, in the reading order,
    gives an observable too (models.md § 5.2), said once at the later part's observable, naming each
    such part and the studies they share."""
    layout = c.opened.layout
    mine = layout.reading(part.address.kind, part.address.name)
    earlier = [o for o in c.opened.parts.values() if o.address.kind == part.address.kind and o.data is not None
               and layout.reading(o.address.kind, o.address.name) < mine]
    for name in data.observables:
        others = [(o, [s for s in data.studies if s in o.data.studies]) for o in earlier if name in o.data.observables]
        others = [(o, shared) for o, shared in others if shared]
        if others:
            yield c.issue(part, *table, name, code="observable-twice", label=name,
                          message=f"`{name}` is an observable of " + "; and of ".join(
                              f"`{o.address}` too, which reads {listed(shared)} as this part does" for o, shared in others)
                                  + ": a name is one observable of a study")


REGISTERS = Registration(schemas={KEY: ObservablesPart}, checks={KEY: check})
