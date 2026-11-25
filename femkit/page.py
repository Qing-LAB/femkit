"""The page declaration (web.md § 8.1): the web page's own structure as data under a schema —
the app, its workspaces, the context, each kind's icon, the keys it answers. Served at
`GET /api/page`; the page keeps no list of its own."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Mapping

from pydantic import Field

from femkit.core.operations import Operation
from femkit.core.schema import DefinitionError, Model, classes, field_extras, items_of, key_path, load_toml
from femkit.definitions import catalogue
from femkit.projects import layout as layouts

Context = Literal["project", "study", "environment"]
#: The page's own commands, which a key may be bound to (web.md § 8.1). The page changes no file
#: the person wrote (projects.md § 7), so none edits, removes or undoes.
Command = Literal["cancel"]


class App(Model):
    name: str = Field(description="what the page is called")
    tagline: str = Field(description="what femkit is, in one sentence")
    mark: str = Field(description="its mark, a file the page ships")


class Workspace(Model):
    key: str = Field(description="how the address names it")
    title: str = Field(description="what a person reads on it")
    icon: str = Field(description="its icon, by the icon set's name")
    tagline: str = Field(description="what it is, in one sentence")
    help: str = Field(description="how it is used")
    document: str | None = Field(default=None, description="the read-only operation whose answer it shows; none: "
                                                           "the registry itself")
    context: list[Context] = Field(default_factory=list, description="the context it needs")
    empty: str = Field(description="what it says before there is anything to show")


class ContextPart(Model):
    key: Context
    label: str = Field(description="what a person reads beside it")
    help: str = Field(description="what it is")
    choices: str = Field(description="the read-only operation that lists its choices")
    rows: str = Field(description="the field of that operation's result holding the choices")
    value_key: str | None = Field(default=None, description="each row's key holding the choice; none: the row is it")
    label_key: str | None = Field(default=None, description="each row's key a person reads; none: the value")
    depends: list[Context] = Field(default_factory=list, description="what must be chosen first")


class Shortcut(Model):
    key: str = Field(description="the key, `Mod` the platform's command key")
    command: Command = Field(description="the page's command it runs")
    help: str = Field(description="what it does")


class Page(Model):
    """`femkit/data/web/page.toml`."""

    schema_: Literal[1] = Field(alias="schema", description="this file's shape; raised when it changes")
    app: App
    workspaces: list[Workspace] = Field(min_length=1)
    context: list[ContextPart]
    kinds: dict[str, str] = Field(description="each part kind's and object type's icon, as the project layout names "
                                              "them (web.md § 8.2)")
    shortcuts: list[Shortcut] = Field(default_factory=list)


def path() -> Path:
    """`web/page.toml`, among the shipped definitions."""
    return catalogue.data_root() / "web" / "page.toml"


def load(ops: Mapping[str, Operation]) -> Page:
    """The declaration, refused unless all it names exists among ``ops``, the operations the
    page is served with: each workspace's document and each context's choices a read-only
    operation, each context's rows and keys in that operation's result, each dependence a
    declared context, each part kind and object type of the project layout with its icon — the
    layout's own refusal when it does not load, as no icon could be checked — each workspace key
    once, and each request field's `context` a declared one — a page that loads it never draws a
    part it cannot fill."""
    p = load_toml(path(), Page)
    contexts, problems = {c.key for c in p.context}, []

    def reads(name: str) -> bool:
        return name in ops and not ops[name].changes

    for i, w in enumerate(p.workspaces):
        if w.document is not None and not reads(w.document):
            problems.append((key_path(("workspaces", i, "document")), f"{w.document!r} is not a read-only operation"))
        problems += [(key_path(("workspaces", i, "context")), f"{c!r} is not a declared context") for c in set(w.context) - contexts]
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
    layout = layouts.read()                                  # refused, the layout's own refusal, when it does not load
    kinds = {*layout.kinds, *layout.objects}
    problems += [("kinds", f"the part kind or object type {k!r} has no icon") for k in sorted(kinds - set(p.kinds))]
    problems += [("kinds", f"{k!r} is no part kind or object type of the layout") for k in sorted(set(p.kinds) - kinds)]
    if problems:
        raise DefinitionError(path(), problems)
    return p
