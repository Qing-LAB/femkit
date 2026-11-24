"""The one vocabulary of what a person may read and do (web.md § 7).

Every document the page renders, and every next step any surface shows, is built from these: a
`Help`, an `Action` — an operation with its request, or a shell line — a `Field`, a `Table`. The
command line writes an action as the command a person types (core/commandline.py); the page
draws it as a button.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field as Describe

from femkit.core import commandline, dirs
from femkit.core.markdown import headings
from femkit.core.errors import Refusal
from femkit.core.schema import Model, field_extras


@dataclass(frozen=True)
class Verb:
    """An operation by its name, with its request model: declared once, beside the request,
    and read both by the operation's declaration and by every next step that names it."""

    name: str
    request: type[BaseModel]


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
    path = dirs.checkout() / document
    return tuple((h.text, h.anchor) for h in headings(path.read_text(encoding="utf-8"))) if path.is_file() else ()


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
    whole value, or a hole in its text — the `<name>` of `model:regions.<name>`."""

    field: str = Describe(description="the request field it fills")
    hole: str | None = Describe(default=None, description="the text in the field's value it replaces; "
                                                          "none: the whole value")
    toml: Literal["whole"] | None = Describe(
        default=None, description="the request takes the value as its TOML text, which the surface writes from "
                                  "what the person gives")
    label: str = Describe(description="what the value is")
    help: Help | None = Describe(default=None, description="its sentence")
    json_schema: dict[str, Any] = Describe(default_factory=dict, description="the JSON schema fragment of what it may hold")
    accepts: list[str] = Describe(default_factory=list,
                                  description="the node kinds whose names may fill it, as `kind` or `kind:type`")
    example: str | None = Describe(default=None, description="a value that would do, as a command line writes it")
    template: str | None = Describe(default=None, description="for an object's text, the text it starts from: its "
                                                              "template, every key it may hold written or commented")


class Call(Model):
    """An operation and its request — the values a fill leaves out are asked for."""

    operation: str = Describe(description="the operation's name, `model.set`")
    request: dict[str, Any] = Describe(default_factory=dict, description="the request's values, as JSON")


class Action(Model):
    """Something a person may do: an operation with its request, or a shell line that is no
    operation — a shell's activation, a scheduler's interactive command."""

    label: str = Describe(description="what a person reads on it")
    command: str = Describe(description="the command a person types, written once from the call or the shell line")
    note: str | None = Describe(default=None, description="a remark a command line writes after it")
    call: Call | None = Describe(default=None, description="the operation it runs; none for a shell line")
    fills: list[Fill] = Describe(default_factory=list, description="each value still to fill, in the order asked")
    help: Help | None = Describe(default=None, description="what it does")

    def __str__(self) -> str:
        return self.command + (f"   # {self.note}" if self.note else "")


def command(verb: Verb, *, label: str | None = None, note: str | None = None,
            fills: Iterable[Fill] = (), **values: Any) -> Action:
    """The action that runs ``operation`` with ``values``: its command written once, by the
    command line's own mapping, a whole value still to fill shown as its example or its name,
    a hole as the text it stands in. A fill of a field the request takes as TOML text says so."""
    operation, request = verb.name, verb.request
    fields = request.model_fields
    unknown = (set(values) | {f.field for f in fills}) - set(fields)
    if unknown:
        raise ValueError(f"{operation}: {request.__name__} has no field {sorted(unknown)}")
    properties = request.model_json_schema()["properties"]
    fills = [f.model_copy(update={
        "toml": None if f.hole else field_extras(fields[f.field]).get("toml"),   # a hole is text in a text
        "json_schema": f.json_schema or ({"type": "string"} if f.hole else properties[fields[f.field].alias or f.field]),
    }) for f in fills]
    words = commandline.words(operation, request, values,
                              {f.field: f.example or f.field.upper() for f in fills if f.hole is None})
    return Action(label=label or " ".join(words), command=commandline.typed(words), note=note,
                  call=Call(operation=operation, request=json.loads(json.dumps(values, default=str))),
                  fills=fills)


def shell(line: str, *, note: str | None = None) -> Action:
    """A line a person types that is no operation of femkit's."""
    return Action(label=line, command=line, note=note)


class Field(Model):
    """One value as a person sees it, and the action that writes it."""

    label: str = Describe(description="what it is called")
    required: bool = Describe(default=False, description="whether what holds it must state it")
    value: str | None = Describe(default=None, description="its value as its file writes it, in TOML; none when unset")
    json_schema: dict[str, Any] = Describe(default_factory=dict, description="the JSON schema fragment of what it may hold")
    help: Help | None = Describe(default=None, description="its sentence")
    set: Action | None = Describe(default=None, description="the action that writes it; its value is the fill")


class Column(Model):
    key: str = Describe(description="the rows' key it shows")
    label: str = Describe(description="its heading")
    help: Help | None = Describe(default=None, description="what it holds")


class Table(Model):
    columns: list[Column] = Describe(default_factory=list)
    rows: list[dict[str, Any]] = Describe(default_factory=list)


# ------------------------------------------------------------------ the routes' answers (web.md § 1)

class RefusalAnswer(Model):
    """A refusal, as `--json` prints it and a route answers it: its kind, why, and what a person
    may do instead."""

    refused: str = Describe(description="the kind of refusal, `Refused`, `PlanStale`, …")
    code: str = Describe(description="which refusal of its kind: what a script tells it apart by")
    subject: str | None = Describe(default=None, description="what it is about")
    message: str = Describe(description="why")
    next: list[Action] = Describe(default_factory=list, description="what a person may do instead")

    @classmethod
    def of(cls, exc: Refusal) -> "RefusalAnswer":
        return cls(refused=type(exc).__name__, code=exc.code, subject=exc.subject, message=str(exc),
                   next=list(exc.next))


class DefectAnswer(Model):
    """An error femkit did not expect: its kind and the operation's log, never a stack trace."""

    defect: str = Describe(description="the kind of error")
    message: str = Describe(default="an error femkit did not expect; the server's log has the detail",
                            description="what a person reads")
    log: str | None = Describe(default=None, description="the operation's log, where one was written")

    @classmethod
    def of(cls, exc: BaseException) -> "DefectAnswer":
        return cls(defect=type(exc).__name__, log=getattr(exc, "femkit_log", None))


class OperationInfo(Model):
    """One operation as `GET /api/operations` lists it."""

    name: str = Describe(description="`group.verb`")
    description: str = Describe(description="its help")
    changes: bool = Describe(description="whether it is planned and applied")
    confirm: bool = Describe(description="whether a surface shows its plan and asks first")
    undoable: bool = Describe(description="whether `model undo` takes it back")
    request: dict[str, Any] = Describe(description="its request's JSON schema")
    result: dict[str, Any] = Describe(description="its result's JSON schema")


class RunAnswer(Model):
    """A read-only operation's answer."""

    ok: bool
    result: dict[str, Any]


class Started(Model):
    """A line of an apply's answer: a run started, at this operation directory."""

    operation: str = Describe(description="`<subject>/<time>`: what the events and tail routes take")


class Ended(Model):
    """The last line of an apply's answer, or the answer of an apply that ended before starting."""

    ok: bool
    outcome: dict[str, Any]


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
