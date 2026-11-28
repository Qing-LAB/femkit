"""The page declaration (web.md § 8.1) and the page's theme (§ 10.1): the web page's own structure
and its design values, each as data under a schema.

The declaration is the app, its workspaces with the panels beside each one's document and the
families each draws, the context, the registry's groups of operations with their titles, icons and
accents, each kind's icon by a node's family, each block word's and step outcome's color, each
section's and stage kind's colour a block wears, what each wire carries and its colour, the colours
of a box's tag, the part kind the canvas lists, the object types it draws as cards of their own and
the part kinds it draws as the output of the part naming them,
the themes a person switches between, the page's own controls and sentences — those the
canvas says of a wire and of a port among them — its token gate, its addresses, the action machine every action runs by, the keys it answers. Served at `GET
/api/page`; what the bundle needs before any token is generated beside it (`bundle`); the page keeps
no list of its own.

The theme is every design value — each colour for both themes, space, size, type, motion, layer
and layout — under its namespace; `schema docs` writes it into the page's `tokens.css`, and nothing
else holds a value of these kinds."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from types import UnionType
from typing import Literal, Mapping, Union, get_args, get_origin

from pydantic import Field, model_validator

from femkit.core import dirs
from femkit.core.eventlog import StepState
from femkit.core.issues import Issue
from femkit.core.operations import Operation
from femkit.core.schema import (DefinitionError, Model, classes, field_extras, items_of, key_path, load_toml,
                                placeholders, refuse)
from femkit.core.view import OBJECT, PART, STAGE, Family, GraphPort, Shows, Wire
from femkit.definitions import catalogue
from femkit.projects import layout as layouts

Context = Literal["project", "study", "target"]
#: The page's own commands, which a key may be bound to (web.md § 8.1). The page changes no file
#: the person wrote (projects.md § 7), so none edits, removes or undoes.
Command = Literal["cancel"]
#: The page's own controls (web.md § 11: "the page names only its own controls, from the
#: declaration"): what a person presses that is no operation's action — each its words, icon and help.
Control = Literal["documents", "theme", "close", "cancel", "continue", "run", "plan", "apply", "discard", "find",
                  "fit", "zoom-in", "zoom-out", "reset-layout", "open", "fold", "details", "panels", "copy", "select",
                  "add", "remove", "edit", "reload", "duplicate", "remove-copy", "legend", "redraw"]
#: The page's own sentences (web.md § 9.1: each answer of the client "said one way"; § 11): what it
#: says of what is no document's — a connection lost, an answer not read, nothing to do, what a
#: diagram's wire drawn solid or dashed means.
Saying = Literal["loading", "nothing-to-do", "refused", "defect", "applied", "no-request", "running", "none-yet",
                 "files", "facts", "issues", "ports", "made-from", "actions", "optional", "preview", "steps", "outcome",
                 "each", "line", "section", "none", "edited", "wire-checked", "wire-unchecked", "copies",
                 "cannot-draw"]
#: The page's own sentences written as templates, each placeholder in the core's grammar (core.md
#: § 2.1): the words the page puts around a value of the server's.
TEMPLATES: dict[str, frozenset[str]] = {"line": frozenset({"file", "line"}), "section": frozenset({"document", "section"}),
                                        "copies": frozenset({"count"})}
#: The shapes a diagram's card may take (web.md § 7.6): with its colour and its icon, what tells a
#: group of cards apart at a glance — each drawn whole, its slots on its edges never cut.
Shape = Literal["rounded", "square", "round", "double", "tab", "notch"]
#: What the gate says before any token (web.md § 5): the token asked for, the server not answering,
#: an answer the page cannot read.
GateSaying = Literal["token", "unreachable", "unreadable"]
#: How much a finding matters (core.md § 10): the vocabulary's own list, as `Issue` declares it.
Severity = Issue.model_fields["severity"].annotation
#: A step's word as an operation's event log tells it (core.md § 6): how it ended, or running.
StepWord = StepState.model_fields["outcome"].annotation
#: What the action machine is told (web.md § 9.1): an action started, or its values given — a value to
#: fill, a read, a change — its plan answered — with steps, with questions, with none — applied, a run
#: started and ended, refused, a defect, the server lost, the values or the plan discarded.
ActionEvent = Literal["fills", "reads", "changes", "planned", "asks", "empty", "apply", "started", "done", "failed",
                      "refused", "defect", "lost", "discard"]
#: What an action's state shows (web.md § 9.1): nothing, its values to fill, that it is busy, its plan,
#: its progress, its outcome, its refusal, a defect, the server lost.
ActionView = Literal["nothing", "fills", "busy", "plan", "progress", "outcome", "refusal", "defect", "lost"]
#: The languages the page's text editor reads a file in (web.md § 9.2; ADR 0024): each one the page
#: carries, a file named by none of them read as plain text.
Language = Literal["toml", "python"]


class App(Model):
    name: str = Field(description="what the page is called")
    tagline: str = Field(description="what femkit is, in one sentence")
    mark: str = Field(description="its mark, a file the page ships")


class Panel(Model):
    """What a workspace shows beside its document (web.md § 8.1)."""

    key: str = Field(description="how the page names it")
    title: str = Field(description="what a person reads on it")
    help: str = Field(description="what it shows, in one sentence")
    document: str | None = Field(default=None, description="the read-only operation whose answer it shows; none: the "
                                                           "progress of the running operation, the page's own")
    context: list[Context] = Field(default_factory=list, description="the context its operation needs")
    shows: Literal["report", "issues", "parts"] = Field(default="report", description="what of its document it shows: "
                                                        "its report, or its findings alone — where what else it holds "
                                                        "the workspace's document already shows, as the graph each "
                                                        "part's state; or, with no document, the parts its "
                                                        "workspace's own graph holds, listed: the master list "
                                                        "(web.md § 2.2)")


class Workspace(Model):
    key: str = Field(description="how the address names it")
    title: str = Field(description="what a person reads on it")
    icon: str = Field(description="its icon, by the icon set's name")
    tagline: str = Field(description="what it is, in one sentence")
    help: str = Field(description="how it is used")
    document: str | None = Field(default=None, description="the read-only operation whose answer it shows; none: "
                                                           "the registry itself")
    context: list[Context] = Field(default_factory=list, description="the context it needs")
    panels: list[Panel] = Field(default_factory=list, description="what it shows beside its document, in order")
    empty: str = Field(description="what it says before there is anything to show")
    first: str | None = Field(default=None, description="the operation it offers as the first step to take before "
                                                        "there is anything to show, beside its context's choices; "
                                                        "none: its choices alone",
                              json_schema_extra={"doc": "web.md § 10.2"})
    landing: Landing | None = Field(default=None, description="what it shows under the hero before its context is "
                                                              "chosen; none: what it says first alone")
    families: list[Family] = Field(default_factory=list, description="the families of node its document's graph draws "
                                   "— where an address of each is opened; none for a workspace of no graph",
                                   json_schema_extra={"doc": "web.md § 2.4"})


class Landing(Model):
    """What a workspace shows before its context is chosen, under the hero (web.md § 10.2): a context's
    choices as cards, each opening it; and its first step started from each choice one of its request's
    fields names."""

    cards: Context = Field(description="the context whose choices are drawn as cards, each choosing it")
    detail: str | None = Field(default=None, description="each choice's row key a card lists beneath its name — a "
                                                         "project's studies; none: its name alone")
    starts: str | None = Field(default=None, description="the field of the first step's request whose declared "
                                                         "choices each start it — a template to copy; none: it starts "
                                                         "bare")


class OperationGroup(Model):
    """One of the registry's groups of operations, as the page bands it apart (web.md §§ 8.1, 10.2)."""

    title: str = Field(description="what a person reads on it")
    icon: str = Field(description="its icon, by the icon set's name")
    accent: str = Field(description="the design token of its accent, which sets it apart wherever it is listed: a "
                                    "colour of the theme", json_schema_extra={"doc": "web.md § 10.1"})


class ContextPart(Model):
    key: Context
    label: str = Field(description="what a person reads beside it")
    help: str = Field(description="what it is")
    unset: str | None = Field(default=None, description="what it is while none is chosen, where the request that takes "
                                                        "it has its own default — the machine a study's stages are for, "
                                                        "this one; none: it is chosen before what needs it is shown")
    choices: str = Field(description="the read-only operation that lists its choices")
    rows: str = Field(description="the field of that operation's result holding the choices")
    value_key: str | None = Field(default=None, description="each row's key holding the choice; none: the row is it")
    label_key: str | None = Field(default=None, description="each row's key a person reads; none: the value")
    depends: list[Context] = Field(default_factory=list, description="what must be chosen first")


class Shortcut(Model):
    key: str = Field(description="the key, `Mod` the platform's command key")
    command: Command = Field(description="the page's command it runs")
    help: str = Field(description="what it does")


class ThemeChoice(Model):
    """One choice of the theme switch (web.md § 10.2): a theme of `theme.toml`, or the system's."""

    theme: str | None = Field(default=None, description="the theme it chooses, by its name in theme.toml; none: the "
                                                        "system's, the default")
    title: str = Field(description="what a person reads on it")
    icon: str = Field(description="its icon, by the icon set's name")


class Category(Model):
    """How the cards of one group are told apart at a glance (web.md § 7.6): a part's section, a stage's
    kind — its colour, its shape and its icon, the legend showing each."""

    colour: str = Field(description="the colour its cards wear on their titles and edges: a colour of the theme",
                        json_schema_extra={"doc": "web.md § 10.1"})
    shape: Shape = Field(description="the shape its cards take")
    icon: str = Field(description="the icon its cards show, by the icon set's name")


class Canvas(Model):
    """What the canvas reads of the project layout (web.md §§ 2.2, 8.1): the part kind that is the
    project's master list — listed beside the canvas, never drawn, nor any wire to or from it — and
    the object types drawn each as a card of its own, beside what uses it."""

    listed: str = Field(description="the part kind listed and not drawn: the project's, whose file lists the parts")
    cards: list[str] = Field(default_factory=list, description="the object types each drawn as a small card of its "
                                                               "own, its wires leaving its one output slot")


class Words(Model):
    """What a person reads on one of the page's own controls, and its icon."""

    label: str = Field(description="what a person reads on it")
    icon: str | None = Field(default=None, description="its icon, by the icon set's name; none: its words alone")
    help: str = Field(description="what it does, in one sentence")


class SeverityLook(Model):
    """How a finding of one severity is marked (core.md § 10; web.md § 7.4)."""

    label: str = Field(description="what a person reads for it")
    icon: str = Field(description="its icon, by the icon set's name: a severity is told by its icon and its word, "
                                  "never by a colour alone")
    color: str = Field(description="the design token it is marked with: a colour of the theme",
                       json_schema_extra={"doc": "web.md § 10.1"})


class Gate(Model):
    """What the page shows before any token (web.md § 5): what it asks for and how, and what it says
    when the server does not answer or answers what it cannot read — carried by the bundle itself,
    generated beside the declaration (`bundle`), since no route answers before the token."""

    label: str = Field(description="what a person reads beside the token's field")
    icon: str = Field(description="the icon of its press, by the icon set's name")
    help: str = Field(description="what the press does, in one sentence")
    says: dict[GateSaying, str] = Field(description="what it says of the token, a server not answering, an answer it "
                                                    "cannot read")


class Addresses(Model):
    """Where the server serves the page (web.md § 1): its bundle's files, and the document viewer."""

    bundle: str = Field(description="the path the bundle's files are served under, ending in `/`: the mark among them")
    documents: str = Field(description="the path the document viewer opens at")


class Viewer(Model):
    """The document viewer (web.md § 2.3)."""

    first: str = Field(description="the document it opens on, by its path from the repository's root")


#: What the canvas says a sentence of (web.md §§ 7.6, 9.2): a wire, and a port of an opened block —
#: each by the vocabulary's model whose fields its templates' placeholders name.
SPOKEN: dict[str, type[Model]] = {"wire": Wire, "port": GraphPort}


def _texts(model: type[Model]) -> tuple[set[str], set[str]]:
    """The fields of ``model`` a sentence may say — each holding a text, or a list of texts said as
    its items — and those of them every instance holds: required, and no list, which may be empty."""
    sayable, always = set(), set()
    for name, field in model.model_fields.items():
        union = get_origin(field.annotation) in (Union, UnionType)
        kinds = [a for a in (get_args(field.annotation) if union else (field.annotation,)) if a is not type(None)]
        listed = all(get_origin(a) is list and get_args(a) == (str,) for a in kinds)
        if listed or all(a is str or get_origin(a) is Literal for a in kinds):
            sayable.add(name)
            if field.is_required() and not listed:
                always.add(name)
    return sayable, always


class Sentences(Model):
    """What the canvas says of what it draws (web.md § 9.2): for each wire and each port of an opened
    block, the first template of its list whose every placeholder the wire or the port holds a value
    for, filled — so a sentence is always the declaration's, and the last template of each list names
    only what every one holds."""

    wire: list[str] = Field(min_length=1, description="the sentences a wire is said in, the first it fills used: "
                            "each placeholder a field of the wire (`Wire`), its ends said by what a person calls them "
                            "— `{source}` the node named or giving, `{target}` the part that names, or the node that "
                            "takes", json_schema_extra={"doc": "web.md § 7.6"})
    port: list[str] = Field(min_length=1, description="the words a port of an opened block is said in, the first it "
                            "fills used: each placeholder a field of the port (`GraphPort`), the nodes it names said "
                            "by what a person calls them", json_schema_extra={"doc": "web.md § 7.6"})

    @model_validator(mode="after")
    def _fillable(self) -> "Sentences":
        """Each placeholder a field of its model that holds a text, and each list's last template
        filled by every wire or port."""
        problems = []
        for spoken, model in SPOKEN.items():
            sayable, always = _texts(model)
            templates = getattr(self, spoken)
            for i, template in enumerate(templates):
                problems += [((spoken, i), f"{{{name}}} is no field of a {model.__name__} that holds a text")
                             for name in placeholders_of(template) if name not in sayable]
            if not set(placeholders_of(templates[-1])) <= always:
                problems.append(((spoken,), f"the last template names only what every {model.__name__} holds — "
                                            f"{', '.join('{%s}' % n for n in sorted(always))} — so each is said"))
        refuse("Sentences", problems)
        return self


class ActionState(Model):
    """One state of the action machine (web.md § 9.1): what it shows, and the controls it offers."""

    key: str = Field(description="how the machine names it")
    shows: ActionView = Field(description="what the place of the action shows in it")
    offers: list[Control] = Field(default_factory=list, description="the page's own controls it offers, in order")


class Transition(Model):
    """One move of the action machine: from a state, told an event, to a state."""

    source: str = Field(alias="from", description="the state it leaves")
    on: ActionEvent = Field(description="what it is told")
    to: str = Field(description="the state it reaches")


class ActionMachine(Model):
    """The action machine (web.md § 9.1; framework.md § 3): one closed table every action runs by, in
    every view — its states, the one it starts in, and each move — run generically by the page."""

    start: str = Field(description="the state an action starts in, before it is pressed")
    states: list[ActionState] = Field(min_length=1)
    transitions: list[Transition] = Field(min_length=1)

    @model_validator(mode="after")
    def _closed(self) -> "ActionMachine":
        """Each state once, the start and each move's ends among them, each move from a state on an event
        once."""
        keys = [s.key for s in self.states]
        problems = [(("states",), f"the state {k!r} is declared twice") for k in sorted({k for k in keys if keys.count(k) > 1})]
        problems += [(("start",), f"{self.start!r} is no state of the machine")] if self.start not in keys else []
        seen: set[tuple[str, str]] = set()
        for i, m in enumerate(self.transitions):
            problems += [(("transitions", i, end), f"{getattr(m, attr)!r} is no state of the machine")
                         for end, attr in (("from", "source"), ("to", "to")) if getattr(m, attr) not in keys]
            if (m.source, m.on) in seen:
                problems.append((("transitions", i), f"{m.source!r} on {m.on!r} moves twice"))
            seen.add((m.source, m.on))
        refuse("ActionMachine", problems)
        return self


class EditorLanguage(Model):
    """One language of the text editor's, with the files it reads in it (web.md § 9.2)."""

    language: Language = Field(description="the language: its highlighting, its comments, its folding")
    files: list[str] = Field(description="the names of the files read in it, each a pattern — `*` any run of "
                                         "characters, `?` one — matched against a file's name: a file is read by its "
                                         "declared language, never by code naming its extension")


class Editor(Model):
    """The page's text editor (web.md § 9.2; ADR 0024): the languages it reads a file in."""

    languages: list[EditorLanguage] = Field(description="each language, once; a file named by none is plain text")


class Page(Model):
    """`femkit/data/web/page.toml`."""

    schema_: Literal[5] = Field(alias="schema", description="this file's shape; raised when it changes")
    app: App
    workspaces: list[Workspace] = Field(min_length=1)
    context: list[ContextPart]
    groups: dict[str, OperationGroup] = Field(description="each of the registry's groups of operations by its name — "
                                              "`\"\"` femkit's own — with its title, icon and accent, in the order "
                                              "listed, the person's order of work (web.md § 8.1)")
    kinds: dict[Family, dict[str, str]] = Field(description="each kind's icon, keyed by a node's family and its kind: "
                                                "each part kind and object type as the project layout names them, "
                                                "each stage kind as `stages.toml` names it (web.md §§ 7.6, 8.2)")
    shows: dict[Shows, str] = Field(description="each block word of the vocabulary's closed list, with the design "
                                                "token a block showing it is colored by: a colour of the theme "
                                                "(web.md §§ 7.6, 10.2)")
    severities: dict[Severity, SeverityLook] = Field(description="each severity a finding may have, with its word, its "
                                                                 "icon and its colour (web.md § 7.4)")
    outcomes: dict[StepWord, str] = Field(description="each word a step of a run may show — how it ended, or running — "
                                          "with the design token it is marked with: a colour of the theme "
                                          "(web.md § 9.2, `Progress`)")
    sections: dict[str, Category] = Field(description="each section of the project layout, by its name, with the "
                                          "colour, shape and icon a card of a part in it takes (web.md §§ 7.6, 10.2)")
    stages: dict[str, Category] = Field(description="each stage kind, as `stages.toml` names it, with the colour, shape "
                                        "and icon a card of a stage of it takes (web.md §§ 7.6, 10.2)")
    canvas: Canvas = Field(description="the part kind the canvas lists and does not draw, and the object types it "
                                       "draws as cards of their own (web.md §§ 2.2, 8.1)")
    wires: dict[str, str] = Field(description="what a wire carries — a part kind or an object type as the project "
                                  "layout names it, or an artifact type — with the colour the wire and the slots it "
                                  "plugs into are drawn in: a wire takes the longest of these its type begins with, so "
                                  "every place of a group takes `group`'s (web.md § 7.6)")
    tags: list[str] = Field(min_length=1, description="the colours a box's tag takes on the blocks it holds — a case, "
                            "the stages several cases share, a grouping folder — one for each box in the graph's "
                            "order, in turn: colours of the theme (web.md § 7.6)")
    themes: list[ThemeChoice] = Field(description="the theme switch's choices, in the order offered: the system's first, "
                                                  "the default, then each theme of theme.toml (web.md § 10.2)")
    gate: Gate
    addresses: Addresses
    documents: Viewer
    action: ActionMachine
    editor: Editor
    notices: int = Field(gt=0, description="how many notices the stack shows at once: the newest (web.md § 9.2)")
    controls: dict[Control, Words] = Field(description="each of the page's own controls, with its words, icon and help "
                                                       "(web.md § 11)")
    says: dict[Saying, str] = Field(description="each of the page's own sentences: what it says of what is no "
                                                "document's, a template's placeholders in the core's grammar "
                                                "(web.md §§ 9.1, 11)")
    sentences: Sentences = Field(description="what the canvas says of a wire and of a port: each a list of templates, "
                                             "the first a wire or port fills used (web.md §§ 7.6, 9.2)")
    shortcuts: list[Shortcut] = Field(default_factory=list)


def path() -> Path:
    """`web/page.toml`, among the shipped definitions."""
    return catalogue.data_root() / "web" / "page.toml"


def load(ops: Mapping[str, Operation]) -> Page:
    """The declaration, refused unless all it names exists among ``ops``, the operations the
    page is served with: each workspace's document, each panel's and each context's choices a
    read-only operation, each workspace's first step an operation it is served with, each context's
    rows and keys in that operation's result, each dependence a declared context, each of the
    registry's groups of operations with its title, icon and accent and no other group, each part
    kind and object type of the project layout and each stage kind with its icon, under its family,
    and no icon of a kind there is none of — the layout's own refusal when it does not load, as no
    icon could be checked — each word of the vocabulary's closed list with its color, and no other
    word, each severity with its look, each accent and color a colour the theme declares — the
    theme's own refusal when it does not load — the themes the system's, light and dark, the
    system's first, each control and sentence of the page's with its words, each workspace key once,
    and each request field's `context` a declared one — a page that loads it never draws a part it
    cannot fill. Besides: each context a workspace needs or a panel reads taken by its document's
    request, a panel listing the parts of no document but its workspace's, the part kind the canvas
    lists, each it draws as the output of the part naming it and each object type it draws as a card
    of its own the layout's, each family drawn by one
    workspace at most, each step word, section of the layout, stage
    kind, part kind and artifact type with its colour and no colour for a section or a carried kind
    there is none of, each block word, accent, severity, step word, section, stage kind, carried kind
    and tag colour held to a contrast in the theme, the
    switch's choices the system's first and then each theme of theme.toml once, each template sentence
    with its placeholders, the documents' first one a file of the checkout, each editor language once,
    reading some file. Its groups are served in the order it lists them."""
    from femkit.registry import GROUPS        # here: the registry imports this module
    p = load_toml(path(), Page)
    contexts, problems = {c.key for c in p.context}, []

    def reads(name: str) -> bool:
        return name in ops and not ops[name].changes

    for i, w in enumerate(p.workspaces):
        if w.document is not None and not reads(w.document):
            problems.append((key_path(("workspaces", i, "document")), f"{w.document!r} is not a read-only operation"))
        if w.first is not None and w.first not in ops:
            problems.append((key_path(("workspaces", i, "first")), f"{w.first!r} is no operation the page is served"))
        if w.landing is not None:
            problems += _landing(w.landing, w.first, ("workspaces", i, "landing"), p.context, ops)
        problems += [(key_path(("workspaces", i, "context")), f"{c!r} is not a declared context") for c in set(w.context) - contexts]
        problems += [(key_path(("workspaces", i, "context")), f"{w.document} takes no context {c!r}")
                     for c in sorted(set(w.context) - _taken(ops, w.document)) if w.document is None or w.document in ops]
        for j, panel in enumerate(w.panels):
            at = ("workspaces", i, "panels", j)
            if panel.document is not None and not reads(panel.document):
                problems.append((key_path((*at, "document")), f"{panel.document!r} is not a read-only operation"))
            if panel.document is None and panel.shows == "issues":
                problems.append((key_path((*at, "shows")), "a panel of no document has no findings to show"))
            if panel.document is not None and panel.shows == "parts":
                problems.append((key_path((*at, "shows")), "the parts listed are its workspace's graph's, no "
                                                           "panel document's"))
            problems += [(key_path((*at, "context")), f"{c!r} is not a declared context")
                         for c in set(panel.context) - contexts]
            problems += [(key_path((*at, "context")), f"{panel.document} takes no context {c!r}")
                         for c in sorted(set(panel.context) - _taken(ops, panel.document))
                         if panel.document is None or panel.document in ops]
    drawn = [f for w in p.workspaces for f in w.families]
    problems += [("workspaces", f"the family {f!r} is drawn by two workspaces: an address of it opens one")
                 for f in sorted({f for f in drawn if drawn.count(f) > 1})]
    if len({w.key for w in p.workspaces}) != len(p.workspaces):
        problems.append(("workspaces", "two workspaces share a key"))
    for i, c in enumerate(p.context):
        problems += [(key_path(("context", i, "depends")), f"{d!r} is not another declared context")
                     for d in set(c.depends) - (contexts - {c.key})]
        if not reads(c.choices):
            problems.append((key_path(("context", i, "choices")), f"{c.choices!r} is not a read-only operation"))
            continue
        rows = ops[c.choices].result.model_fields.get(c.rows)
        if rows is None:
            problems.append((key_path(("context", i, "rows")), f"{c.choices}'s result has no field {c.rows!r}"))
            continue
        records = classes(items_of(rows.annotation))                  # the row the page reads, when a record
        problems += [(key_path(("context", i)), f"{c.choices}'s rows have no key {key!r}")
                     for key in filter(None, (c.value_key, c.label_key))
                     if not records or key not in records[0].model_fields]
    problems += [("context", f"{op.name}'s field {name!r} takes the context {taken!r}, which is not declared")
                 for op in ops.values() for name, field in op.request.model_fields.items()
                 if (taken := field_extras(field).get("context")) is not None and taken not in contexts]
    problems += [("groups", f"the registry's group {g!r} has no title, icon and accent") for g in GROUPS
                 if g not in p.groups]
    problems += [(key_path(("groups", g)), "no group of the registry's") for g in p.groups if g not in GROUPS]
    layout = layouts.read()                                  # refused, the layout's own refusal, when it does not load
    named = {PART: set(layout.kinds), OBJECT: set(layout.objects), STAGE: set(catalogue.load_stages().kinds)}
    for family in get_args(Family):
        held = set(p.kinds.get(family, {}))
        problems += [(key_path(("kinds", family)), f"the {family} kind {k!r} has no icon")
                     for k in sorted(named[family] - held)]
        problems += [(key_path(("kinds", family)), f"{k!r} is no {family} kind femkit declares")
                     for k in sorted(held - named[family])]
    problems += [("shows", f"the word {w!r} has no color: a block showing it could not be drawn")
                 for w in get_args(Shows) if w not in p.shows]
    problems += [("severities", f"the severity {s!r} has no look: a finding of it could not be marked")
                 for s in get_args(Severity) if s not in p.severities]
    problems += [("outcomes", f"the step word {w!r} has no color: a step showing it could not be marked")
                 for w in _words(StepWord) if w not in p.outcomes]
    problems += [("sections", f"the section {s!r} has no colour: a block in it could not be drawn")
                 for s in layout.sections if s not in p.sections]
    problems += [(key_path(("sections", s)), "no section of the project layout's") for s in p.sections
                 if s not in layout.sections]
    problems += [("stages", f"the stage kind {k!r} has no colour: a block of it could not be drawn")
                 for k in sorted(named[STAGE] - set(p.stages))]
    problems += [(key_path(("stages", k)), "no stage kind femkit declares") for k in sorted(set(p.stages) - named[STAGE])]
    if p.canvas.listed not in named[PART]:
        problems.append((key_path(("canvas", "listed")), f"{p.canvas.listed!r} is no part kind of the project layout"))
    problems += [(key_path(("canvas", "cards", i)), f"{k!r} is no object type of the project layout")
                 for i, k in enumerate(p.canvas.cards) if k not in named[OBJECT]]
    artifacts = set(catalogue.load_artifacts())
    problems += [("wires", f"{k!r} has no colour: a wire carrying it could not be drawn")
                 for k in sorted((named[PART] | artifacts) - set(p.wires))]
    problems += [(key_path(("wires", k)), "no part kind, object type or artifact type femkit declares")
                 for k in sorted(set(p.wires) - named[PART] - named[OBJECT] - artifacts)]
    theme = load_theme()                                     # refused, the theme's own refusal, when it does not load
    seen = [(("groups", g, "accent"), group.accent) for g, group in p.groups.items()] \
        + [(("shows", w), token) for w, token in p.shows.items()] \
        + [(("severities", s, "color"), look.color) for s, look in p.severities.items()] \
        + [(("outcomes", w), token) for w, token in p.outcomes.items()] \
        + [(("sections", s, "colour"), c.colour) for s, c in p.sections.items()] \
        + [(("stages", k, "colour"), c.colour) for k, c in p.stages.items()] \
        + [(("wires", k), token) for k, token in p.wires.items()] \
        + [(("tags", i), token) for i, token in enumerate(p.tags)]
    problems += [(key_path(at), f"{token!r} is no colour the theme declares ({theme_path().name})")
                 for at, token in seen if token not in theme.color.theme]
    held = set(theme.color.contrast.text) | set(theme.color.contrast.graphic)
    problems += [(key_path(at), f"{token!r} is held to no contrast in {theme_path().name}: what a person must see "
                                "meets WCAG AA on its surfaces (web.md § 10.2)")
                 for at, token in seen if token in theme.color.theme and token not in held]
    choices = [t.theme for t in p.themes]
    if choices != [None, *theme.themes]:
        problems.append(("themes", f"the switch offers the system's first, then each theme of {theme_path().name} "
                                   f"once, in its order: {', '.join(theme.themes)}"))
    problems += [("controls", f"the control {c!r} has no words") for c in get_args(Control) if c not in p.controls]
    problems += [("says", f"the sentence {s!r} is not written") for s in get_args(Saying) if s not in p.says]
    problems += [(key_path(("says", s)), f"the template names {', '.join(sorted(needs))}, each once")
                 for s, needs in TEMPLATES.items() if s in p.says and set(placeholders_of(p.says[s])) != needs]
    if not p.addresses.bundle.endswith("/"):
        problems.append(("addresses.bundle", "a path files are served under ends in `/`"))
    if not (dirs.checkout() / p.documents.first).is_file():
        problems.append(("documents.first", f"{p.documents.first!r} is no file of the repository"))
    languages = [e.language for e in p.editor.languages]
    problems += [("editor.languages", f"the language {name!r} is declared twice: a file would be read in two")
                 for name in sorted({n for n in languages if languages.count(n) > 1})]
    problems += [(key_path(("editor", "languages", i, "files")), "a language reads the files named here: none named")
                 for i, e in enumerate(p.editor.languages) if not e.files]
    if problems:
        raise DefinitionError(path(), problems)
    return p


def _taken(ops: Mapping[str, Operation], name: str | None) -> set[str]:
    """The contexts the request of the operation ``name`` takes, by its fields' `context` annotations;
    none for no operation (an operation not served is refused as such, once)."""
    if name not in ops:
        return set()
    return {c for f in ops[name].request.model_fields.values() if (c := field_extras(f).get("context")) is not None}


def _words(annotation: object) -> list[str]:
    """Every word of a closed list, through its unions: a step's outcomes and `running`."""
    out: list[str] = []
    for a in get_args(annotation) or [annotation]:
        out += [str(w) for w in get_args(a)] if get_args(a) else [str(a)]
    return out


def placeholders_of(text: str) -> list[str]:
    """The placeholders a template of the page's names, in the core's grammar (core.md § 2.1)."""
    return [name for name, _ in placeholders(text)]


def _landing(landing: Landing, first: str | None, at: tuple, context: list[ContextPart],
             ops: Mapping[str, Operation]) -> list[tuple[str, str]]:
    """A landing's problems: its cards no declared context's choices, its detail no key of their rows,
    its starts no field of its first step's request that names declared choices (api.md § 4.1)."""
    part = next((c for c in context if c.key == landing.cards), None)
    if part is None:
        return [(key_path((*at, "cards")), f"{landing.cards!r} is not a declared context")]
    out = []
    rows = ops[part.choices].result.model_fields.get(part.rows) if part.choices in ops else None
    records = classes(items_of(rows.annotation)) if rows is not None else []
    if landing.detail is not None and (not records or landing.detail not in records[0].model_fields):
        out.append((key_path((*at, "detail")), f"{part.choices}'s rows have no key {landing.detail!r}"))
    if landing.starts is not None:
        field = ops[first].request.model_fields.get(landing.starts) if first in ops else None
        if field is None or field_extras(field).get("choices") is None:
            out.append((key_path((*at, "starts")), f"{landing.starts!r} is no field of {first}'s request that names "
                                                   "declared choices"))
    return out


def icons(p: Page) -> list[str]:
    """Every icon the declaration names — a workspace's, a group's of operations, a kind's, a
    section's or stage kind's, a severity's, a theme's, a control's — each once, sorted: the page's one
    icon set (web.md § 8.7)."""
    return sorted({w.icon for w in p.workspaces} | {g.icon for g in p.groups.values()}
                  | {i for icons in p.kinds.values() for i in icons.values()}
                  | {c.icon for c in [*p.sections.values(), *p.stages.values()]}
                  | {s.icon for s in p.severities.values()} | {t.icon for t in p.themes} | {p.gate.icon}
                  | {c.icon for c in p.controls.values() if c.icon is not None})


# ------------------------------------------------------------------ the theme (web.md § 10.1)

#: A design token's name within its namespace: lower case, words joined by `-`.
TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
#: A colour as the theme writes it: `#rrggbb`, or `#rrggbbaa` with its opacity.
HEX = re.compile(r"#[0-9a-f]{6}(?:[0-9a-f]{2})?")
#: The grid every space sits on, in px (web.md § 10.1: "Spacing is a 4px grid").
GRID = 4
#: WCAG 2.2's level AA contrast (https://www.w3.org/TR/WCAG22/): 4.5:1 for text against its
#: surface (success criterion 1.4.3), 3:1 for a graphic or a part of a control that must be seen
#: (1.4.11) — a block's word colour, a group's accent.
AA = {"text": Decimal("4.5"), "graphic": Decimal("3")}


class Contrast(Model):
    """Each colour a person must read or see, with the surfaces it is drawn on: every pair meets
    WCAG 2.2 AA in both themes (web.md § 10.2), refused where it does not."""

    text: dict[str, list[str]] = Field(default_factory=dict, description="each text colour with the surfaces it is "
                                                                          "read on: 4.5:1 (WCAG 2.2, 1.4.3)")
    graphic: dict[str, list[str]] = Field(default_factory=dict, description="each colour of a graphic — a block's "
                                          "word, a group's accent — with the surfaces it is seen on: 3:1 (WCAG 2.2, "
                                          "1.4.11)")


class Colors(Model):
    scale: dict[str, str] = Field(description="the palette's colours, by name — a neutral scale and the hues — each "
                                              "`#rrggbb`: what the theme's colours are chosen from")
    theme: dict[str, dict[str, str]] = Field(description="each colour the page names, by its token's name, as each "
                                             "theme gives it: a colour of the scale by its name, or `#rrggbb[aa]`")
    opacity: dict[str, Decimal] = Field(default_factory=dict, description="each opacity, from 0 to 1: how much of what "
                                                                           "lies under a drawing shows through it")
    contrast: Contrast = Field(description="each colour a person reads or sees, with its surfaces, held to WCAG AA")

    def value(self, name: str, theme: str) -> str:
        """The colour ``name`` gives in the theme ``theme``, as `#rrggbb[aa]`."""
        written = self.theme[name][theme]
        return self.scale.get(written, written)


class ThemeKind(Model):
    """One theme of the page (web.md § 10.2)."""

    scheme: Literal["light", "dark"] = Field(description="what the browser's own controls and the system's preference "
                                                         "call it (CSS `color-scheme`): the system asking for it "
                                                         "draws it, while no theme is chosen")


def contrast(a: str, b: str) -> Decimal:
    """The contrast ratio of two opaque colours, by WCAG 2.2's relative luminance (its definition of
    "relative luminance" and "contrast ratio"): (L1 + 0.05) / (L2 + 0.05), L1 the lighter."""
    def luminance(hex_: str) -> float:
        def channel(c: int) -> float:
            s = c / 255
            return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
        r, g, b = (channel(int(hex_[i:i + 2], 16)) for i in (1, 3, 5))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return Decimal(str(round((high + 0.05) / (low + 0.05), 4)))


Px = int        # a length, in CSS pixels
Ms = int        # a time, in milliseconds


class Type(Model):
    family: str = Field(description="the page's one font family, as a CSS font stack the system holds: the page "
                                    "loads no font from the network")
    mono: str = Field(description="the font stack of text a person copies as it is: code, a file's lines")
    size: dict[str, Px] = Field(description="each type size, in px")
    weight: dict[str, int] = Field(description="each weight, as CSS writes it")
    leading: dict[str, Decimal] = Field(description="each line height, a multiple of the size")
    tracking: dict[str, Decimal] = Field(description="each letter spacing, in em")


class Motion(Model):
    duration: dict[str, Ms] = Field(description="each transition's length, in ms: none under reduced motion")
    easing: dict[str, str] = Field(description="each easing, as CSS writes it")
    timing: dict[str, Ms] = Field(description="each time the page waits that is no motion, in ms — how long a "
                                              "notice stays, how often a running step's lines are read — kept "
                                              "under reduced motion")

    @model_validator(mode="after")
    def _apart(self) -> "Motion":
        refuse("Motion", [(("timing", n), "a duration has this name: each is a token of its own")
                          for n in self.timing if n in self.duration])
        return self


class ShadowPart(Model):
    """One layer of a shadow: its offset, blur and spread in px, and its colour."""

    x: Px = 0
    y: Px
    blur: Px
    spread: Px = 0
    color: str = Field(description="a colour of the theme, by its token's name")


class Layer(Model):
    """One plane of the page — the ground, a raised surface, an overlay, a dialog — its order and
    its elevation."""

    z: int = Field(description="its z-order: a plane above another is drawn over it")
    shadow: list[ShadowPart] = Field(default_factory=list, description="its soft elevation, layer by layer; none: flat")


class Theme(Model):
    """`femkit/data/web/theme.toml`: every design value of the page, under its namespace (web.md § 10.1)."""

    schema_: Literal[2] = Field(alias="schema", description="this file's shape; raised when it changes")
    themes: dict[str, ThemeKind] = Field(min_length=1, description="the themes, by name, the first the default: each "
                                                                   "colour is given for each")
    color: Colors
    space: dict[str, Px] = Field(description="each space, in px, on the 4px grid")
    size: dict[str, Px] = Field(description="each size — a line's width, a radius, an icon, a control — in px")
    type: Type
    motion: Motion
    layer: dict[str, Layer] = Field(description="each plane of the page, by name")
    layout: dict[str, Px] = Field(description="each measure of the page's arrangement — a panel's width, the least "
                                              "room a part of it needs, the diagram's spacing — in px")

    @model_validator(mode="after")
    def _named(self) -> "Theme":
        """Each token named as a token is, each scale colour whole and opaque, each colour given for each
        theme and resolving, each contrast pair two opaque colours of the theme meeting AA in each theme,
        each space on the grid, each shadow's colour the theme's."""
        c = self.color
        names = [(("space", n), n) for n in self.space] + [(("size", n), n) for n in self.size] \
            + [(("layout", n), n) for n in self.layout] + [(("layer", n), n) for n in self.layer] \
            + [(("themes", n), n) for n in self.themes] + [(("color", "theme", n), n) for n in c.theme] \
            + [(("color", "scale", n), n) for n in c.scale] + [(("color", "opacity", n), n) for n in c.opacity] \
            + [(("type", part, n), n) for part in ("size", "weight", "leading", "tracking")
               for n in getattr(self.type, part)] \
            + [(("motion", part, n), n) for part in ("duration", "easing", "timing") for n in getattr(self.motion, part)]
        problems = [(at, "a token's name is lower case, its words joined by `-`") for at, n in names
                    if not TOKEN.fullmatch(n)]
        problems += [(("color", "scale", n), f"{v!r} is no colour: a scale's colour is `#rrggbb`")
                     for n, v in c.scale.items() if not (HEX.fullmatch(v) and len(v) == 7)]
        problems += [(("color", "opacity", n), f"{v} is no opacity: one is from 0 to 1") for n, v in c.opacity.items()
                     if not 0 <= v <= 1]
        for n, shades in c.theme.items():
            if set(shades) != set(self.themes):
                problems.append((("color", "theme", n), f"a colour is given for each theme: {', '.join(self.themes)}"))
            problems += [(("color", "theme", n, side), f"{v!r} is neither a colour of the scale nor `#rrggbb[aa]`")
                         for side, v in shades.items() if not HEX.fullmatch(v) and v not in c.scale]
        if not problems:
            for kind, pairs in (("text", c.contrast.text), ("graphic", c.contrast.graphic)):
                for fore, backs in pairs.items():
                    for i, back in enumerate(backs):
                        problems += self._pair(kind, fore, back, ("color", "contrast", kind, fore, i))
        problems += [(("space", n), f"{v} px is off the {GRID} px grid") for n, v in self.space.items() if v % GRID]
        problems += [(("layer", n, "shadow", i, "color"), f"{s.color!r} is no colour of the theme")
                     for n, layer in self.layer.items() for i, s in enumerate(layer.shadow) if s.color not in c.theme]
        refuse("Theme", problems)
        return self

    def _pair(self, kind: str, fore: str, back: str, at: tuple) -> list[tuple[tuple, str]]:
        missing = [n for n in (fore, back) if n not in self.color.theme]
        if missing:
            return [(at, f"{', '.join(map(repr, missing))} is no colour of the theme")]
        out = []
        for side in self.themes:
            a, b = self.color.value(fore, side), self.color.value(back, side)
            if len(a) > 7 or len(b) > 7:
                out.append((at, f"{fore} on {back} is held to a contrast, so both are opaque: `#rrggbb`"))
                continue
            ratio = contrast(a, b)
            if ratio < AA[kind]:
                out.append((at, f"{fore} ({a}) on {back} ({b}) in the {side} theme is {ratio:.2f}:1, under WCAG AA's "
                                f"{AA[kind]}:1 for {'text' if kind == 'text' else 'a graphic'}"))
        return out


def theme_path() -> Path:
    """`web/theme.toml`, among the shipped definitions."""
    return catalogue.data_root() / "web" / "theme.toml"


def load_theme() -> Theme:
    """The theme, refused at the key of each problem — a colour that does not resolve, a pair of a
    text and its surface under WCAG AA, a space off the grid (web.md §§ 10.1–10.2)."""
    return load_toml(theme_path(), Theme)


#: The attribute of the document's root that names the theme a person chose (web.md § 10.2): none
#: while the system's is followed. The page reads its name from the generated bundle (`bundle`).
CHOSEN = "data-theme"


class Binding(Model):
    """One word of the declaration bound to its colour token (web.md § 10.1): an element carrying the
    word in its `data-<attribute>` reads the token as `--<attribute>`."""

    attribute: str = Field(description="the data attribute, after `data-`, and the custom property it sets")
    value: str = Field(description="the word the attribute holds")
    token: str = Field(description="the colour token it is bound to — an opacity of the theme among them, `opacity-<name>`")


class Sheet(Model):
    """The page's tokens as data (web.md § 10.1), before they are written as CSS: each custom property
    the same in every theme, each theme's colours, the durations reduced motion empties, and the
    declaration's words bound to their tokens."""

    attribute: str = Field(description="the attribute naming the theme chosen")
    default: str = Field(description="the theme drawn while none is chosen and the system asks for no other")
    schemes: dict[str, str] = Field(description="each theme's CSS `color-scheme`")
    common: dict[str, str] = Field(description="each custom property every theme holds alike, by its name")
    colours: dict[str, dict[str, str]] = Field(description="each theme's colour properties, by theme")
    reduced: dict[str, str] = Field(description="each property reduced motion sets: every duration, none")
    bindings: list[Binding] = Field(description="each declared word bound to its colour token")

    def css(self) -> str:
        """The sheet as CSS: the default theme's colours and every common property under the root; each
        other theme under the system's preference while none is chosen, and when chosen; reduced
        motion; then each binding."""
        def block(selector: str, props: Mapping[str, str], indent: str = "") -> list[str]:
            return [f"{indent}{selector} {{", *(f"{indent}  {k}: {v};" for k, v in props.items()), f"{indent}}}"]

        def scheme(theme: str) -> dict[str, str]:
            return {"color-scheme": self.schemes[theme], **self.colours[theme]}

        lines = ["/* generated by `femkit schema docs` from femkit/data/web/theme.toml and page.toml -- do not edit */", "",
                 *block(":root", {**scheme(self.default), **self.common}), ""]
        for theme in self.colours:
            if theme == self.default:
                lines += [*block(f':root[{self.attribute}="{theme}"]', scheme(theme)), ""]
                continue
            lines += [f"@media (prefers-color-scheme: {self.schemes[theme]}) {{",
                      *block(f":root:not([{self.attribute}])", scheme(theme), "  "), "}", "",
                      *block(f':root[{self.attribute}="{theme}"]', scheme(theme)), ""]
        lines += ["@media (prefers-reduced-motion: reduce) {", *block(":root", self.reduced, "  "), "}", ""]
        lines += [f'[data-{b.attribute}="{b.value}"] {{ --{b.attribute}: var(--color-{b.token}); }}' for b in self.bindings]
        return "\n".join(lines) + "\n"


#: The namespace of the theme's opacities among its colour tokens: `--color-opacity-<name>`.
OPACITY = "opacity"


def sheet(theme: Theme, p: Page) -> Sheet:
    """The page's tokens (web.md § 10.1): each value of ``theme`` a custom property named by its
    namespace — `--color-*`, `--space-*`, `--size-*`, `--type-*`, `--motion-*`, `--layer-*`,
    `--layout-*` — each colour for each theme, every duration none under reduced motion; and the
    declaration's words bound to their tokens: a block by the word it shows (`shows`), a group of
    operations by its name (`group`), a finding by its severity (`severity`), a step by its word
    (`outcome`), a block by its section (`section`) or its stage kind (`stage`), a wire and its slots
    by what it carries (`wire`), and a box's tag by its place in the graph (`tag`)."""
    def px(prefix: str, values: Mapping[str, int]) -> dict[str, str]:
        return {f"--{prefix}-{n}": f"{v}px" for n, v in values.items()}

    def shadow(layer: Layer) -> str:
        return ", ".join(f"{s.x}px {s.y}px {s.blur}px {s.spread}px var(--color-{s.color})" for s in layer.shadow)

    t, m = theme.type, theme.motion
    common = {**{f"--color-{OPACITY}-{n}": str(v) for n, v in theme.color.opacity.items()},
              **px("space", theme.space), **px("size", theme.size),
              "--type-family": t.family, "--type-mono": t.mono, **px("type-size", t.size),
              **{f"--type-weight-{n}": str(v) for n, v in t.weight.items()},
              **{f"--type-leading-{n}": str(v) for n, v in t.leading.items()},
              **{f"--type-tracking-{n}": f"{v}em" for n, v in t.tracking.items()},
              **{f"--motion-{n}": f"{v}ms" for n, v in m.duration.items()},
              **{f"--motion-ease-{n}": v for n, v in m.easing.items()},
              **{f"--motion-{n}": f"{v}ms" for n, v in m.timing.items()},
              **{f"--layer-{n}": str(layer.z) for n, layer in theme.layer.items()},
              **{f"--layer-{n}-shadow": shadow(layer) for n, layer in theme.layer.items() if layer.shadow},
              **px("layout", theme.layout)}
    bound = [("shows", p.shows), ("group", {g: group.accent for g, group in p.groups.items()}),
             ("severity", {s: look.color for s, look in p.severities.items()}), ("outcome", p.outcomes),
             ("section", {s: c.colour for s, c in p.sections.items()}),
             ("stage", {k: c.colour for k, c in p.stages.items()}), ("wire", p.wires),
             ("tag", {str(i): token for i, token in enumerate(p.tags)})]
    return Sheet(attribute=CHOSEN, default=next(iter(theme.themes)),
                 schemes={n: k.scheme for n, k in theme.themes.items()}, common=common,
                 colours={side: {f"--color-{n}": theme.color.value(n, side) for n in theme.color.theme}
                          for side in theme.themes},
                 reduced={f"--motion-{n}": "0ms" for n in m.duration},
                 bindings=[Binding(attribute=a, value=str(k), token=v) for a, words in bound for k, v in words.items()])


def tokens(theme: Theme, p: Page) -> str:
    """The page's `tokens.css`: its sheet (`sheet`) written as CSS."""
    return sheet(theme, p).css()


def bundle(p: Page) -> dict:
    """What the bundle carries before any token (web.md § 5), generated beside the declaration: the
    token gate's words, icon and sentences, the mark's address, the addresses the page is served at,
    and the attribute naming the theme chosen — no route answers before the token."""
    return {"gate": p.gate.model_dump(mode="json"), "mark": p.addresses.bundle + p.app.mark,
            "addresses": p.addresses.model_dump(mode="json"), "attribute": CHOSEN}
