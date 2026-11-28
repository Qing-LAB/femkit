"""The one vocabulary of what a person may read and do (web.md § 7).

Every document the page renders, and every next step any surface shows, is built from these: a
`Help`, an `Action` — an operation with its request, or a shell line — a `Field`, a `Table`. The
command line writes an action as the command a person types (core/commandline.py); the page
draws it as a button.
"""

from __future__ import annotations

import functools
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Iterable, Literal, get_args

from pydantic import BaseModel, ConfigDict, Discriminator, Field as Describe, computed_field, model_validator

from femkit.core import commandline, dirs, persist
from femkit.core.markdown import headings
from femkit.core.errors import Refusal
from femkit.core.schema import (MANUAL_DIR, QUANTITIES, DeclaredKey, Model, described, field_extras, field_named,
                                fragment, key_path, may_hold, narrowed, path_fields, render, written_keys)
from femkit.core.units import Dimension, UnitError, Units


#: What an operation does when it runs (api.md § 2; web.md § 7.2): it only reads; or, planned and
#: applied, it changes things, or removes them — what the page tones its button by.
Effect = Literal["reads", "changes", "removes"]
EFFECTS: tuple[str, ...] = Effect.__args__


@dataclass(frozen=True)
class Verb:
    """An operation by its name, with its request model: declared once, beside the request,
    and read both by the operation's declaration and by every next step that names it. Each
    is known here as it is declared, so a surface writes an action from its call alone; a
    second of one name with another request is a defect, refused where it is made (api.md § 2).
    ``on_machine``: whether the operation acts on the machine it runs on — its environments, its
    settings, its records, the jobs and servers started there: `job launch`, `env install`, `doctor`
    — so a step of it for another machine carries that machine (`Action.on`; api.md § 2.2, web.md
    § 7.2); any other — `job prepare`, `study prep` — runs here for any target, and stays an
    operation. ``effect``: whether it reads, changes or removes (`EFFECTS`) — the one home of whether
    it changes anything: one that does more than read is planned, shown and applied once the person
    agrees (`Operation.changes`), and every action of it carries it, so the page tones its button by
    it and asks before applying one whose effect is not `reads`, deciding neither (web.md § 7.2).
    Every verb declares both: neither has a default (api.md § 2)."""

    name: str
    request: type[BaseModel]
    on_machine: bool = field(kw_only=True)
    effect: Effect = field(kw_only=True)

    def __post_init__(self) -> None:
        if self.effect not in EFFECTS:
            raise ValueError(f"the verb {self.name!r} declares the effect {self.effect!r}; an effect is one of "
                             f"{', '.join(EFFECTS)}")
        held = _VERBS.get(self.name)
        if held is not None and held.request is not self.request:
            raise TypeError(f"the verb {self.name!r} is declared twice: with {held.request.__name__} "
                            f"and with {self.request.__name__}")
        _VERBS[self.name] = self


_VERBS: dict[str, Verb] = {}


def verbs() -> list[Verb]:
    """Every verb declared so far: what the registry checks against the operations at start
    (api.md § 6)."""
    return list(_VERBS.values())


class DocRef(Model):
    """Where something is defined: a document of the repository, a section of it, and that
    section's link anchor."""

    document: str = Describe(description="the document's path from the repository's root, `docs/contracts/models.md`")
    section: str | None = Describe(default=None, description="its section as the reference writes it, `11.1`; none "
                                                              "for the whole document")
    anchor: str | None = Describe(default=None, description="the section's heading's link anchor, read from the "
                                                            "document; none when it has no such heading")

    @classmethod
    def at(cls, document: str, section: str | None) -> "DocRef":
        return cls(document=document, section=section, anchor=_anchor(document, section) if section else None)


@functools.lru_cache(maxsize=None)
def _anchors(document: str) -> tuple[tuple[str, str], ...]:
    """Each heading of a document of the checkout — its text, its anchor — read once."""
    held = persist.read_text(dirs.checkout() / document)
    return tuple((h.text, h.anchor) for h in headings(held)) if held is not None else ()


def _anchor(document: str, section: str) -> str | None:
    """A section's anchor: the heading numbered so — `11.1` heads `### 11.1 Addresses` — or the
    anchor itself, as a science document's sections are written."""
    for text, anchor in _anchors(document):
        if anchor == section or text.split(" ", 1)[0].rstrip(".") == section:
            return anchor
    return None


class Help(Model):
    """What a person reads beside something they may not understand."""

    sentence: str = Describe(description="one plain sentence")
    doc: DocRef | None = Describe(default=None, description="where it is defined")

    @classmethod
    def of(cls, sentence: str | None, doc: str | None = None) -> "Help | None":
        """A sentence, and a `doc` annotation (core.md § 2): `models.md § 4`, a contract and its
        section, as the contracts write a reference; or a path from the repository's root and its
        section, `docs/science/electrostatics.md § 3-conditions-on-an-outer-boundary`."""
        if not sentence:
            return None
        if not doc:
            return cls(sentence=sentence)
        document, _, section = doc.partition(" § ")
        return cls(sentence=sentence, doc=DocRef.at(document if "/" in document else f"docs/contracts/{document}",
                                                    section or None))


class Fill(Model):
    """A value an action still needs, asked of the person before it runs: a request field's
    whole value."""

    field: str = Describe(description="the request field it fills")
    toml: Literal["whole"] | None = Describe(
        default=None, description="the request takes the value as its TOML text, which the surface writes from "
                                  "what the person gives")
    label: str = Describe(description="what the value is")
    help: Help | None = Describe(default=None, description="its sentence")
    json_schema: dict[str, Any] = Describe(default_factory=dict, description="the JSON schema fragment of what it may "
                                           "hold, whole: each definition it names carried with it")
    example: str | None = Describe(default=None, description="a value that would do, as a command line writes it")
    required: bool = Describe(default=True, description="whether it must be given: a value an action still needs "
                                                        "always; a form's field where its request has no default")

    @classmethod
    def of(cls, request: type[BaseModel], name: str, *, choices: Iterable[str] | None = None,
           **given: Any) -> "Fill":
        """The fill of ``request``'s field ``name`` — the one builder of a fill (web.md § 7.2): ``given``
        what its maker says of it, the rest read from the field — its label its key in words, its help
        its description and `doc`, its schema fragment whole, whether the request takes its TOML text,
        whether it is required; with ``choices``, the names the field may take for the action's subject,
        narrower than its declaration — the engines that can solve a study — its fragment a closed list
        of them (`schema.narrowed`), so a surface offers those alone."""
        field = request.model_fields[name]
        extras = field_extras(field)
        held = given.get("json_schema") or fragment(request, (field.alias or name,))
        return cls(**{"field": name, "label": name.replace("_", " "),
                      "help": Help.of(field.description, extras.get("doc")), "required": field.is_required(),
                      **given, "toml": extras.get("toml"),
                      "json_schema": held if choices is None else narrowed(held, choices)})


class Call(Model):
    """An operation and its request — the values a fill leaves out are asked for."""

    operation: str = Describe(description="the operation's name, `study.prep`")
    request: dict[str, Any] = Describe(default_factory=dict, description="the request's values, as JSON")


class Action(Model):
    """Something a person may do: an operation with its request, or a shell line that is no
    operation — a shell's activation, a scheduler's interactive command — on this machine, or on
    another, `on`, where a surface writes it as a line for that machine and never runs it. Its
    line and its effect are its operation's, computed from its call and serialized with it (web.md
    § 7.2), never stored beside it: an action read back from a file femkit keeps computes them
    again, from the verbs femkit has then."""

    label: str = Describe(description="what a person reads on it")
    note: str | None = Describe(default=None, description="a remark a command line writes after it")
    call: Call | None = Describe(default=None, description="the operation it runs; none for a shell line")
    shell: str | None = Describe(default=None, description="the line a person types, for what is no operation")
    fills: list[Fill] = Describe(default_factory=list, description="each value still to fill, in the order asked")
    help: Help | None = Describe(default=None, description="what it does")
    on: str | None = Describe(default=None, description="the machine it runs on, by its record's name, where that is "
                              "not the one the page or the command line runs on: a line for that machine, its "
                              "request's path fields from the project's folder, never run here; none: this machine",
                              json_schema_extra={"doc": "web.md § 7.2"})

    @model_validator(mode="before")
    @classmethod
    def _computed_unread(cls, data: Any) -> Any:
        """What is computed from its call — its line, its effect — is never read back, the one place
        it is dropped: an action written as JSON, as a lock's file, a launch folder's maker and a plan
        held in another's hold it, reads as itself."""
        return {k: v for k, v in data.items() if k not in cls.model_computed_fields} if isinstance(data, dict) else data

    @computed_field(description="the line the command line writes for it: a value still to fill as what it asks "
                                "for, never its example", json_schema_extra={"doc": "web.md § 7.2"})
    @property
    def command(self) -> str:
        """The command a person types, written from the call by the command line's own mapping
        (core/commandline.py): a value still to fill as what it asks for, never its example
        (`filled`); a shell line with each of its placeholders so (`shell`)."""
        if self.call is None:
            return _line(self.shell or "", self.fills)
        verb = _VERBS[self.call.operation]
        return commandline.typed(commandline.words(verb.name, verb.request, self.call.request, filled(self.fills)))

    @computed_field(description="what its operation does, as its verb declares it: it reads, changes or removes; "
                                "none for a shell line", json_schema_extra={"doc": "api.md § 2"})
    @property
    def effect(self) -> Effect | None:
        return _VERBS[self.call.operation].effect if self.call is not None else None

    def named(self) -> str | None:
        """Its label, where it says more than its command — the words a state's table or the step's
        maker gives it (web.md § 7.2: "what a person reads on it"); None where it is the command's
        own words, as `command` and `shell` label a step that is given none."""
        if self.call is None:
            bare = _line(self.shell or "", self.fills)
        else:
            verb = _VERBS[self.call.operation]
            bare = " ".join(commandline.words(verb.name, verb.request, self.call.request, filled(self.fills)))
        return None if self.label == bare else self.label

    def remarks(self) -> list[str]:
        """What a command line writes after it, as help (web.md § 7.2): its note; for another machine,
        where it is typed — on that machine, in the project's folder there where a path field of its
        request is given; and each value still to fill's example, said as one."""
        where = []
        if self.on is not None:
            given = self.call is not None and any(self.call.request.get(k) is not None
                                                  for k in path_fields(_VERBS[self.call.operation].request))
            where = [f"on the machine {self.on} describes" + (", in the project's folder there" if given else "")]
        examples = [f"{f.field.upper()} e.g. {f.example}" for f in self.fills if f.example is not None]
        return [*filter(None, [self.note]), *where, *examples]

    def __str__(self) -> str:
        """The one line the command line writes for it, wherever it stands — under a next block's
        heading, under a finding, in a table's cell (api.md § 4.4): its command, then after `#` its
        label where it says more than the command (`named`), then its remarks."""
        said = [*filter(None, [self.named()]), *self.remarks()]
        return self.command + (f"   # {'; '.join(said)}" if said else "")


def filled(fills: Iterable[Fill]) -> dict[str, str]:
    """Each value still to fill, as a command line writes it: what it asks for — the field, in
    capitals, as the command line's help names it — never its example, which is said apart as help
    (workflow.md § 7: "never an example written as if it were theirs")."""
    return {f.field: f.field.upper() for f in fills}


def _line(line: str, fills: Iterable[Fill]) -> str:
    """A shell line as a person types it: each value still to fill, a placeholder of the core's
    grammar (`{name}`, core.md § 2.1), written as what it asks for (`filled`)."""
    fills = list(fills)
    return render(line, filled(fills)) if fills else line


@dataclass(frozen=True)
class Machine:
    """The machine a step is for, where it is not the one the page or the command line runs on
    (web.md § 7.2): its record's name, and the folder a line typed there starts in — the project's —
    from which each path field of a step's request is given; none where a step names no path."""

    name: str
    folder: Path | None = None


def at(action: Action, machine: Machine | None) -> Action:
    """``action`` as the machine ``machine`` takes it (web.md § 7.2; workflow.md § 7): for this
    machine — no ``machine`` — as it is; for another, a step of an operation that acts on the machine it
    runs on, as its verb declares it (`Verb.on_machine`), or a shell line, carrying that machine,
    `on` — a line for that machine, never run here — each field its request's model declares names
    a folder or a file (`path`), and no other, given by its path from ``machine.folder`` where it
    lies there; any other operation runs here for any target, and stays the operation it is. The one
    way a step is made for another machine."""
    if machine is None:
        return action
    if action.call is None:
        return action.model_copy(update={"on": machine.name})
    verb = _VERBS[action.call.operation]
    if not verb.on_machine:
        return action
    request = action.call.request
    inside = {k: _from(machine.folder, request[k]) for k in path_fields(verb.request) if isinstance(request.get(k), str)}
    return action.model_copy(update={"on": machine.name, "call": action.call.model_copy(
        update={"request": {**request, **inside}})})


def _from(folder: Path | None, path: str) -> str:
    """A folder's or a file's path as a line typed in ``folder`` names it: from there where it lies
    there, else as it is."""
    return path if folder is None or not Path(path).is_relative_to(folder) else \
        Path(path).relative_to(folder).as_posix()


def command(verb: Verb, *, label: str | None = None, note: str | None = None,
            fills: Iterable[Fill] = (), machine: Machine | None = None, **values: Any) -> Action:
    """The action that runs ``verb``'s operation with ``values`` — for the machine ``machine``, where
    it is another's, as `at` takes it there: its command written once, by the command line's own
    mapping, a value still to fill shown as what it asks for (`filled`). A fill of a field the
    request takes as TOML text says so. Never `target`: a request may hold a field of that name."""
    operation, request = verb.name, verb.request
    fields = request.model_fields
    unknown = (set(values) | {f.field for f in fills}) - set(fields)
    if unknown:
        raise ValueError(f"{operation}: {request.__name__} has no field {sorted(unknown)}")
    fills = [Fill.of(request, f.field, **f.model_dump(exclude={"toml", "required"}, exclude_defaults=True))
             for f in fills]
    words = commandline.words(operation, request, values, filled(fills))
    return at(Action(label=label or " ".join(words), note=note,
                     call=Call(operation=operation, request=json.loads(json.dumps(values, default=str))),
                     fills=fills), machine)


def shell(line: str, *, note: str | None = None, fills: Iterable[Fill] = (),
          machine: Machine | None = None) -> Action:
    """A line a person types that is no operation of femkit's — for the machine ``machine``, where it
    is another's — each value it still needs, one only the person knows, a placeholder of the core's
    grammar, `{name}`, with its fill: written as what it asks for, its example said apart as help,
    never an example written into the line as if it were theirs (web.md § 7.2)."""
    fills = list(fills)
    return at(Action(label=_line(line, fills), shell=line, note=note, fills=fills), machine)


class Field(Model):
    """One value as a person sees it, and the action that writes it: a setting, or a key a part's
    file may hold (web.md § 7.3)."""

    label: str = Describe(description="what it is called")
    key: str | None = Describe(default=None, description="for a key a file may hold, its path from the file's top, as "
                                                         "a finding names it (`Issue.key`)",
                               json_schema_extra={"doc": "web.md § 8.3"})
    required: bool = Describe(default=False, description="whether what holds it must state it")
    value: str | None = Describe(default=None, description="its value as its file writes it, in TOML; none when unset")
    json_schema: dict[str, Any] = Describe(default_factory=dict, description="the JSON schema fragment of what it may "
                                           "hold: a closed list's values as `enum`; a quantity's dimension, the unit "
                                           "table's symbols for it as `units`, and a declared unit as `unit`")
    help: Help | None = Describe(default=None, description="its sentence, and the manual's chapter that explains it")
    set: Action | None = Describe(default=None, description="the action that writes it; its value is the fill")

    @classmethod
    def keys(cls, model: type[BaseModel], text: str | None, declared: Iterable[DeclaredKey], units: Units,
             manual: str | None) -> list["Field"]:
        """Every key a file of ``model`` holding ``text`` may hold (web.md §§ 7.3, 8.3) — the one
        builder of a part's keys: each key its schema names there (`schema.may_hold`), and each key
        ``declared`` states beside it — a formulation's, the property list's — whose statement wins
        where it names a key the schema names too, as a key's help is read (`help_findings`). Each
        its key path as the file writes it; whether it must be stated; its value as the file sets
        it; the loader's own fragment at its path (`schema.fragment`), with what its declaration adds
        — its values as `enum`, its unit — and, for a quantity of a known dimension, that dimension
        and the unit table's symbols for it (core.md § 11); and its help: its sentence as the
        template's comment above it reads (`described`, `help_text`), and, where that comment ends
        with the manual's chapter ``manual``, that chapter — never a contract (core.md § 2)."""
        try:
            data = tomllib.loads(text, parse_float=persist.exact_number) if text is not None else {}
        except tomllib.TOMLDecodeError:
            data = {}
        stated = {d.path: d for d in declared}
        out: list[Field] = []
        for k in may_hold(model, written_keys(text)):
            d = stated.pop(k.path, None)
            if d is not None:
                out.append(cls._declared(model, d, units, data))
                continue
            kind = field_extras(k.field).get("quantity")
            fixed = QUANTITIES[kind].dimension if kind in QUANTITIES else None
            out.append(cls._key(model, k.path, described(k.field), manual if field_extras(k.field).get("doc") else None,
                                k.field.is_required(), {}, [fixed] if fixed is not None else [], units,
                                _set(data, k.path, k.leaf)))
        return out + [cls._declared(model, d, units, data) for d in stated.values()]

    @classmethod
    def _declared(cls, model: type[BaseModel], d: DeclaredKey, units: Units, data: dict) -> "Field":
        """A key a declaration states, as `keys` builds it: one value, unless the loader's fragment at
        its path is a table of keys — a property's datasets."""
        dimensions = []
        for unit in d.units:
            try:
                dimensions.append(units.unit(unit).dimension)
            except UnitError:
                continue                                    # the declaration's own check says why
        added = {**({"enum": list(d.values)} if d.values else {}), **({"unit": d.unit} if d.unit else {})}
        leaf = fragment(model, d.path).get("type") != "object"
        return cls._key(model, d.path, d.help(manual=False), d.manual, d.required, added, dimensions, units,
                        _set(data, d.path, leaf))

    @classmethod
    def _key(cls, model: type[BaseModel], path: tuple[str, ...], sentence: str, manual: str | None, required: bool,
             added: dict[str, Any], dimensions: list[Dimension], units: Units, value: str | None) -> "Field":
        """One key: the loader's fragment at its path with what is ``added``, and its dimensions'."""
        shape = {**fragment(model, path), **added}
        held = list(dict.fromkeys(dimensions))
        if len(held) == 1:
            shape["dimension"] = dict(held[0])
        if held:
            shape["units"] = sorted({s for d in held for s in (units.of(d) if d else ["1"])})
        help = Help.of(sentence, str(MANUAL_DIR / manual) if manual else None)
        return cls(label=str(path[-1]), key=key_path(path), required=required, value=value, json_schema=shape,
                   help=help)


def _set(data: Any, path: tuple[str, ...], leaf: bool) -> str | None:
    """The value ``data`` sets at ``path``, as its file writes it on one line — a table of keys none:
    its keys are their own; none where it sets none."""
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return persist.inline_text(data) if leaf or not isinstance(data, dict) else None


class Column(Model):
    """One column of a table: one field of its row model (web.md § 7.5)."""

    key: str = Describe(description="the rows' key it shows: its field's name")
    label: str = Describe(description="its heading: its field's title, else its key, spaces for underscores")
    help: Help | None = Describe(default=None, description="what it holds: its field's description, and where it is "
                                                           "defined")


def column(model: type[BaseModel], key: str) -> Column:
    """The column of ``model``'s field ``key`` (web.md § 7.5): its label the field's short name — the
    `title` its declaration gives, else its key with spaces for underscores — its help the field's
    description and `doc`; never a heading written by hand. A field the model lacks, or one with no
    description, makes none."""
    found = field_named(model, key)
    if found is None:
        raise ValueError(f"{model.__name__} has no field {key!r}: a table's column is a field of its row model")
    described = found[1].description
    if not described:
        raise ValueError(f"{model.__name__}.{key} has no description: a column's label and help are its field's")
    label = found[1].title or key.replace("_", " ")
    return Column(key=key, label=label, help=Help.of(described, field_extras(found[1]).get("doc")))


class Table(Model):
    """Rows under their columns (web.md § 7.5): each column a field of a row model, `column`; a cell
    holds a value, or an `Action` — a row's own next step."""

    kind: Literal["table"] = "table"
    columns: list[Column] = Describe(default_factory=list)
    rows: list[dict[str, Any]] = Describe(default_factory=list)

    @classmethod
    def of(cls, model: type[BaseModel], rows: Iterable[dict[str, Any]], *keys: str) -> "Table":
        """A table of rows of ``model``: a column for each of its fields ``keys`` names, in order, as
        `column` makes it; each row its cells by those keys — one naming no column is refused."""
        return cls.over([column(model, k) for k in keys], rows)

    @classmethod
    def over(cls, columns: list[Column], rows: Iterable[dict[str, Any]]) -> "Table":
        """A table under ``columns`` — each made by `column`, of one row model or of several, as a
        table of a case's stages takes the case's ID from the case — each row its cells by their keys;
        one naming no column is refused."""
        rows, keys = list(rows), {c.key for c in columns}
        stray = sorted({k for row in rows for k in row} - keys)
        if stray:
            raise ValueError(f"a row names {', '.join(stray)}, which no column of its table shows")
        return cls(columns=columns, rows=rows)


class Text(Model):
    """One line a person reads (web.md § 7.7)."""

    kind: Literal["text"] = "text"
    text: str


class Code(Model):
    """Text a person copies as it is — a diagram's source, a file's lines (web.md § 7.7): the
    command line prints it untouched, the page shows it as a block of code."""

    kind: Literal["code"] = "code"
    text: str


class Next(Model):
    """A heading and the actions under it: what a person may do next (web.md § 7.7)."""

    kind: Literal["next"] = "next"
    label: str
    actions: list[Action] = Describe(default_factory=list)


class Report(Model):
    """What a result shows a person, as data; its findings follow its blocks (web.md § 7.7). A graph
    is a block like any other: the page draws it, the command line writes it as its tables."""

    blocks: list[Annotated[Text | Code | Table | Graph | Next, Discriminator("kind")]] = Describe(default_factory=list)


# ------------------------------------------------------------------ the graph (web.md § 7.6)
#
# One document shape for every diagram the page draws — the description a person writes, the
# workflow derived from it, its execution — built by the operation that derives it and drawn by
# the one graph element. A node's issues are the vocabulary's findings, `Issue` (core.md § 10),
# which names its next steps by `Action` above: its module is bound at the end of this one.

#: One plain word per block a diagram draws (web.md § 7.6): the closed list a state table of a thing
#: drawn as a block declares its states' words in (core.md § 7), and the page colors a block by.
Shows = Literal["up to date", "needs update", "needs attention", "waiting", "running", "failed"]
#: What a node of a diagram is (web.md § 7.6): a part of a project, an object inside one, or a stage
#: of a study's workflow — its `kind` within that, as its declaration names it, so the mesh recipe
#: (`part`, `mesh`) and the mesh stage (`stage`, `mesh`) are told apart.
Family = Literal["part", "object", "stage"]
PART, OBJECT, STAGE = get_args(Family)
#: Which way a port faces (web.md § 7.6): what its node reads or takes, or what it gives.
Side = Literal["in", "out"]
IN, OUT = get_args(Side)
#: What a box groups (web.md § 7.6): a grouping folder, a case, the stages several cases share, a job.
BoxKind = Literal["folder", "case", "shared", "job"]
FOLDER, CASE, SHARED, JOB = get_args(BoxKind)


class File(Model):
    """A file a node opens as (web.md § 7.6): its text as the file holds it and its SHA-256, read
    once by the door (projects.md § 6), which a save sends back (projects.md § 7)."""

    address: str = Describe(description="the file, by its address: a part's own, `mesh:fine`, or a folder part's "
                                        "file, `component:bowtie@geometry.py`",
                            json_schema_extra={"doc": "projects.md § 5"})
    path: str = Describe(description="the file as a finding names it (`Issue.file`): a project's by its path from the "
                                     "project's folder, a global library's by its full path — so a finding is marked "
                                     "at its line of the file it names", json_schema_extra={"doc": "core.md § 10"})
    text: str | None = Describe(default=None, description="its text as the file holds it, comments kept; none where "
                                                          "it could not be read")
    sha256: str | None = Describe(default=None, description="the SHA-256 of its bytes as they were read; none where "
                                                            "it could not be read")
    save: Action | None = Describe(default=None, description="the action that writes it exactly as the person typed it "
                                                             "— `project save` — its one value to fill the text; none "
                                                             "where it is not saved from here",
                                   json_schema_extra={"doc": "projects.md § 7"})


class Fact(Model):
    """What a person reads of a node, built by the operation that draws it and drawn generically
    (web.md § 7.6): a study's cases written and made."""

    label: str = Describe(description="what it is")
    value: str = Describe(description="what it is now, as a person reads it")
    shows: Shows | None = Describe(default=None, description="the block word it shows, where it is a state's")


class GraphPort(Model):
    """A field or an artifact a node takes or gives, typed by its declaration: a `ref` annotation
    (core.md § 2), or an artifact type (workflow.md § 2.2)."""

    name: str = Describe(description="the field, by its dotted path from the node; a group a component promises, by "
                                     "its name; or the artifact, by the name its stage's program calls it")
    side: Side = Describe(description="`in`, what the node reads or takes — a field naming another node; `out`, what "
                                      "it gives — a component's groups, a stage's outputs")
    accepts: list[str] = Describe(description="the types it names, as its `ref` annotation states them — `physics`, "
                                              "`group:outer_boundary` — a group's, the places it may be; or its "
                                              "artifact's type, `geometry/xao`")
    many: bool = Describe(description="whether it names several: a list, or a table's keys")
    names: list[str] = Describe(default_factory=list, description="what it holds: the names a field holds; the "
                                                                  "nodes a group or an artifact flows to, or from")
    file: str | None = Describe(default=None, description="for a stage's output, its file in the stage's newest "
                                                          "finished run; none before one finished",
                                json_schema_extra={"doc": "workflow.md § 8"})
    actions: list[Action] = Describe(default_factory=list, description="for a stage's output, the lines that open "
                                     "it; none for a file femkit opens no way",
                                     json_schema_extra={"doc": "workflow.md § 8"})


class GraphNode(Model):
    """A part, an object inside one, or a stage, as a diagram shows it: one field list for every
    node (web.md § 7.6)."""

    address: str = Describe(description="its address", title="node", json_schema_extra={"doc": "projects.md § 5"})
    family: Family = Describe(description="what it is: a part, an object inside one, or a stage")
    kind: str = Describe(description="its kind within its family — its part kind, object type or stage kind — as its "
                                     "declaration names it")
    type: str | None = Describe(default=None, description="its type within its kind, where its declaration has one: "
                                                          "a condition's kind, a mesh stage's mesher")
    part: str | None = Describe(default=None, description="for an object, the address of the part holding it")
    label: str = Describe(description="what a person calls it")
    rank: int | None = Describe(default=None, description="its place in the chain's order, its kind's — an object's "
                                                          "its part's: what it is made from comes first; none for a "
                                                          "stage", json_schema_extra={"doc": "projects.md § 4"})
    section: str | None = Describe(default=None, description="where a person finds it, its kind's — an object's its "
                                                             "part's; none for a stage",
                                   json_schema_extra={"doc": "projects.md § 4"})
    state: str | None = Describe(default=None, description="for a part or a stage, its state, in its machine's words")
    shows: Shows | None = Describe(default=None, description="for a part or a stage, its block's one plain word")
    ports: list[GraphPort] = Describe(default_factory=list, description="the fields or the artifacts it takes or "
                                                                        "gives, each typed")
    issues: list[_issues.Issue] = Describe(default_factory=list, description="the findings that name it",
                                           title="findings")
    files: list[File] = Describe(default_factory=list, description="each file it opens as — a part's, a component's "
                                 "contract and its script — with its text; none for an object, whose part's the page "
                                 "shows, nor for a stage", json_schema_extra={"doc": "web.md § 8.3"})
    keys: list[Field] = Describe(default_factory=list, description="for a part, every key its file may hold, each "
                                 "with its help and the fragment of what it may hold: what the page's text editor "
                                 "explains on hover and offers as the person types; none for an object, whose part's "
                                 "the page shows, nor for a stage", json_schema_extra={"doc": "web.md § 8.3"})
    facts: list[Fact] = Describe(default_factory=list, description="what a person reads of it, as its operation "
                                                                   "builds it")
    made_from: list[str] = Describe(default_factory=list, description="for a stage, the addresses of the parts and "
                                    "stages it is made from: the one relation between the diagrams",
                                    json_schema_extra={"doc": "workflow.md § 3"})
    engine: str | None = Describe(default=None, description="for a solve stage alone, the engine whose solve it is; "
                                  "none for a geometry or a mesh stage, its study's, made for no engine, nor for a "
                                  "study, which names none", json_schema_extra={"doc": "web.md § 7.6"})
    environment: str | None = Describe(default=None, description="for a stage, the environment it runs in")
    folder: str | None = Describe(default=None, description="for a stage, its calculation folder's path",
                                  json_schema_extra={"doc": "projects.md § 2"})
    actions: list[Action] = Describe(default_factory=list, description="its state's next steps")


class Wire(Model):
    """One reference, or one artifact flowing, of the type both ends declare, in one direction
    everywhere: from what gives or is named to what takes or names it (web.md § 7.6)."""

    source: str = Describe(description="the node that gives, or is named", title="from")
    source_port: str | None = Describe(default=None, description="the port it leaves by: an output, a group a "
                                                                 "component promises; none for a node named whole",
                                       title="from port")
    target: str = Describe(description="the node that takes, or names", title="to")
    target_port: str | None = Describe(default=None, description="the port it reaches: the input it feeds, the field "
                                       "that names; none for a definition a value's text uses, or what an axis varies",
                                       title="to port")
    type: str = Describe(description="what it carries: the `ref` annotation's type, `definition`, a node's kind, or an "
                                     "artifact type")
    address: str | None = Describe(default=None, description="for a reference, the address of the value that names; "
                                                             "none for an artifact flowing", title="written at")
    key: str | None = Describe(default=None, description="for a reference, the key that names it, within the naming "
                                                         "part's file, as a finding names its key (`Issue.key`)",
                               json_schema_extra={"doc": "web.md § 7.6"})
    checked: bool = Describe(default=True, description="false for a wire through a group whose kind waits on the "
                                                       "built geometry, not checked yet",
                             json_schema_extra={"doc": "models.md § 11.2"})


class Box(Model):
    """A box drawn around nodes: a grouping folder, a case, the stages several cases share, or a
    job — a box, since "group" names a geometry's named group. Boxes of one kind never overlap."""

    address: str = Describe(description="what it is: a grouping folder by its path in the project, a case by its "
                                        "file's, the stages several cases share by the addresses of those cases' "
                                        "boxes, joined by `+`")
    label: str = Describe(description="what a person calls it", title="box")
    kind: BoxKind = Describe(description="what it groups")
    members: list[str] = Describe(default_factory=list, description="the nodes and boxes inside it, by their "
                                                                    "addresses")
    serves: list[str] = Describe(default_factory=list, description="for a box of shared stages, the boxes of the cases "
                                                                   "they serve")


class Graph(Model):
    """Every diagram the page draws, one shape (web.md § 7.6): a block of a report (§ 7.7)."""

    kind: Literal["graph"] = "graph"
    nodes: list[GraphNode] = Describe(default_factory=list, description="its nodes, in the reading order: a "
                                                                        "description's by section, then rank, then "
                                                                        "its kind's place; a workflow's in its "
                                                                        "cases' order")
    wires: list[Wire] = Describe(default_factory=list, description="its wires")
    boxes: list[Box] = Describe(default_factory=list, description="its boxes")


# ------------------------------------------------------------------ the routes' answers (web.md § 1)

class RefusalAnswer(Model):
    """A refusal, as `--json` prints it and a route answers it: its kind, why, and what a person
    may do instead."""

    refused: str = Describe(description="the kind of refusal, `Refused`, `PlanStale`, …")
    code: str = Describe(description="which refusal of its kind: what a script tells it apart by")
    subject: str | None = Describe(default=None, description="what it is about")
    message: str = Describe(description="why")
    issues: list[_issues.Issue] = Describe(default_factory=list, description="the findings it rests on, every one, "
                                           "shown before its sentence", json_schema_extra={"doc": "core.md § 9"})
    next: list[Action] = Describe(default_factory=list, description="what a person may do instead")

    @classmethod
    def of(cls, exc: Refusal) -> "RefusalAnswer":
        return cls(refused=exc.kind, code=exc.code, subject=exc.subject, message=str(exc),
                   issues=list(exc.issues), next=list(exc.next))


class DefectAnswer(Model):
    """An error femkit did not expect: its kind and the operation's log, never a stack trace."""

    defect: str = Describe(description="the kind of error")
    message: str = Describe(default="an error femkit did not expect: a defect, or a system it needs that is "
                                    "unavailable", description="what a person reads")
    log: str | None = Describe(default=None, description="the operation's log, where one was written")

    @classmethod
    def of(cls, exc: BaseException) -> "DefectAnswer":
        return cls(defect=type(exc).__name__, log=getattr(exc, "femkit_log", None))


class OperationInfo(Model):
    """One operation as `GET /api/operations` lists it."""

    name: str = Describe(description="`group.verb`")
    description: str = Describe(description="its help")
    effect: Effect = Describe(description="what it does, as its verb declares it: it only reads, run at once; or it "
                                          "changes or removes, planned, shown and applied once the person agrees",
                              json_schema_extra={"doc": "api.md § 2"})
    group: str = Describe(description="its command group, by the registry's name — `\"\"` femkit's own — the "
                                      "group the page bands it with", json_schema_extra={"doc": "api.md § 6"})
    words: list[str] = Describe(description="its command, the words after `femkit`, as the command line spells it",
                                json_schema_extra={"doc": "api.md § 4.1"})
    fills: list[Fill] = Describe(default_factory=list, description="each field of its request as a value to fill, "
                                 "built by the one builder of a fill: what its form asks")
    request: dict[str, Any] = Describe(description="its request's JSON schema")
    result: dict[str, Any] = Describe(description="its result's JSON schema")
    choices: dict[str, list[str]] = Describe(default_factory=dict, description="each request field whose values are "
                                             "declared data — the templates, the importers, the environments — with "
                                             "the names declared now", json_schema_extra={"doc": "api.md § 4.1"})


class Shown(Model):
    """What the page reads of every result (api.md § 2.3): its report and its findings, and, for an
    outcome, how it ended and its log — every other field the result's own, carried as it is."""

    model_config = ConfigDict(extra="allow", frozen=True)

    report: Report = Describe(description="what a person reads, as data", json_schema_extra={"doc": "web.md § 7.7"})
    issues: list[_issues.Issue] = Describe(default_factory=list, description="its findings")
    status: Literal["done", "failed", "planned"] | None = Describe(
        default=None, description="for an outcome, how it ended; `planned` the outcome a plan foresees")
    log: str | None = Describe(default=None, description="for an outcome, its operation directory")


class RunAnswer(Model):
    """A read-only operation's answer."""

    ok: bool
    result: Shown


class Started(Model):
    """A line of an apply's answer: a run started, at this operation directory."""

    operation: str = Describe(description="`<subject>/<time>`: what the events and tail routes take")


class Ended(Model):
    """The last line of an apply's answer, or the answer of an apply that ended before starting."""

    ok: bool
    outcome: Shown


class Lines(Model):
    lines: list[str] = Describe(default_factory=list, description="a step's log's last lines")


class Proof(Model):
    proof: str = Describe(description="the server's token's HMAC of the nonce given")


class Documents(Model):
    files: list[str] = Describe(description="every document the viewer shows")


class Heading(Model):
    level: int
    text: str
    anchor: str = Describe(description="its link anchor, by GitHub's rule")


class Document(Model):
    path: str
    text: str
    headings: list[Heading]


class Image(Model):
    path: str
    type: str = Describe(description="its media type")
    data: str = Describe(description="its bytes, in base64")


# The findings a graph's node holds are `Issue`s, whose next steps are this module's `Action`s: the
# module is bound here, at the end, so either module may be imported first. Each model above that
# names it is completed when it is first used.
import femkit.core.issues as _issues  # noqa: E402
