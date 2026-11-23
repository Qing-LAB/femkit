"""`model set`, `unset`, `rename`: one edit of the model or a study, its comments kept, refused
when it would leave a file unloadable or remove what others refer to (models.md § 11.1, § 11.2).

An edit is made on the project's files as documents (core.md § 4), and the whole project is
then loaded again through the first tier — the model, and every study against it — so the
edit is refused before anything is written."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import tomlkit

from femkit.core.errors import Refused, UsageError
from femkit.core.persist import (document_has, document_rename, document_set, document_unset, parse_value,
                                 read_document)
from femkit.core.schema import DefinitionError, references, validate
from femkit.core.units import Units, name_spans
from femkit.models.address import Address
from femkit.models.project import model_file, studies, study_file
from femkit.models.schema import NAME, ModelFile, StudyFile, quantities

NEW_FILE = "schema = 1\n"

# The tables whose entries are named objects, and the reference type that names each (§ 3, § 5).
MODEL_OBJECTS = {("parameters",): "parameter", ("geometry", "shapes"): "shape", ("regions",): "region",
                 ("materials",): "material", ("sources",): "source"}
STUDY_OBJECTS = {("observables",): "observable", ("environments",): "binding"}


@dataclass
class Project:
    """The model and every study, as editable documents."""
    root: Path
    units: Units
    docs: dict[str | None, tomlkit.TOMLDocument] = field(default_factory=dict)   # None: the model
    digests: dict[str | None, str | None] = field(default_factory=dict)          # each file as read; None: absent

    @classmethod
    def read(cls, root: Path, units: Units, extra_study: str | None = None) -> "Project":
        p = cls(root, units)
        for study in [None, *studies(root), *([extra_study] if extra_study else [])]:
            path = model_file(root) if study is None else study_file(root, study)
            p.docs[study] = read_document(path, empty=NEW_FILE)
            p.digests[study] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        return p

    def path(self, study: str | None) -> Path:
        return model_file(self.root) if study is None else study_file(self.root, study)

    def text(self, study: str | None) -> str:
        return tomlkit.dumps(self.docs[study])

    def load(self) -> tuple[ModelFile, dict[str, StudyFile]]:
        """Every file through the first tier, as it would be written; refused naming each problem."""
        model = _validate(ModelFile, self.text(None), self.path(None), {"units": self.units})
        out = {}
        for study in (s for s in self.docs if s is not None):
            out[study] = _validate(StudyFile, self.text(study), self.path(study), {"units": self.units, "model": model})
        return model, out


def _validate(kind, text: str, path: Path, context: dict):
    try:
        return validate(kind, tomllib.loads(text, parse_float=Decimal), path, context)
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"{path.name} would not be TOML: {exc}") from None
    except DefinitionError as exc:
        raise UsageError(f"the edit would leave {path.name} unloadable — {exc.summary()}") from None


def named(address: Address) -> str | None:
    """The reference type of the named object ``address`` is, if it is one."""
    table = MODEL_OBJECTS if address.study is None else STUDY_OBJECTS
    for prefix, kind in table.items():
        if address.path[:-1] == prefix and len(address.path) == len(prefix) + 1:
            return kind
    return None


def referrers(project: Project, model: ModelFile, studies_: dict[str, StudyFile], kind: str,
              name: str) -> list[tuple[str | None, tuple, str]]:
    """Every place in the project that names the object ``kind`` ``name``: as a reference
    `(study, location, held)` — `key`, `value`, `item` — or, for a parameter, an expression
    using it (`text`), or a study axis varying it (`axis`)."""
    out = []
    for study, instance in [(None, model), *studies_.items()]:
        for at, target, held_name, held in references(instance):
            if held_name == name and kind in {t.split(":")[0] for t in target.split("|")}:
                out.append((study, at, held))
        if kind == "parameter":
            for at, _, value in quantities(instance):
                if isinstance(value, str) and at != ("parameters", name) and \
                        any(n == name for _, _, n in name_spans(value)):
                    out.append((study, at, "text"))
            if study is not None and f"parameters.{name}" in instance.axes:
                out.append((study, ("axes", f"parameters.{name}"), "axis"))
    return out


def _address(study: str | None, at: tuple) -> str:
    return str(Address(study, tuple(str(p) for p in at)))


# ------------------------------------------------------------------ the three edits

def set_value(project: Project, address: Address, text: str) -> None:
    if not address.path:
        raise UsageError(f"{address}: name what to set")
    try:
        value = parse_value(text)
    except ValueError as exc:
        raise UsageError(str(exc)) from None
    if address.study is not None and address.study not in project.docs:
        project.docs[address.study] = read_document(project.path(address.study), empty=NEW_FILE)
        project.digests[address.study] = None
    try:
        document_set(project.docs[address.study], address.path, value)
    except KeyError as exc:
        raise UsageError(f"{address}: {exc.args[0]}") from None
    project.load()


def unset(project: Project, address: Address) -> None:
    doc = project.docs.get(address.study)
    if doc is None or not address.path or not document_has(doc, address.path):
        raise UsageError(f"{address} is not set")
    kind = named(address)
    if kind is not None:
        model, studies_ = project.load()
        using = [(s, at) for s, at, held in referrers(project, model, studies_, kind, address.path[-1])
                 if (s, tuple(at[:len(address.path)])) != (address.study, address.path)]
        if using:
            raise Refused(f"{address} is referred to by " + ", ".join(_address(s, at) for s, at in using),
                          ("python -m femkit model rename " + str(address) + " NEW   # or unset those first",))
    document_unset(doc, address.path)
    project.load()


def rename(project: Project, address: Address, new: str) -> None:
    """The object renamed, and every reference to it, every expression using it, every axis
    varying it, changed with it."""
    kind = named(address)
    if kind is None:
        raise UsageError(f"{address} is not a named object: one of "
                         + ", ".join(".".join(p) + ".<name>" for p in (MODEL_OBJECTS if address.study is None
                                                                       else STUDY_OBJECTS)))
    if not NAME.fullmatch(new):
        raise UsageError(f"{new!r}: a name matches [a-z][a-z0-9_]*")
    doc = project.docs.get(address.study)
    old = address.path[-1]
    if doc is None or not document_has(doc, address.path):
        raise UsageError(f"{address} does not exist")
    model, studies_ = project.load()
    sites = referrers(project, model, studies_, kind, old)
    for study, at, held in sorted(sites, key=lambda s: -len(s[1])):  # deepest first: a key renamed keeps its children
        target = project.docs[study]
        if held == "key":
            document_rename(target, at, new)
        elif held in ("value", "item"):
            document_set(target, at[:-1] + (at[-1],), new) if held == "value" else _set_item(target, at, new)
        elif held == "text":
            document_set(target, at, _renamed_text(_get(target, at), old, new))
        elif held == "axis":
            document_rename(target, at, f"parameters.{new}")
    try:
        document_rename(doc, address.path, new)
    except KeyError:
        raise UsageError(f"{address.path[:-1]} already has an entry named {new!r}") from None
    project.load()


def _get(doc: Any, at: tuple) -> Any:
    for step in at:
        doc = doc[step]
    return doc


def _set_item(doc: Any, at: tuple, value: str) -> None:
    _get(doc, at[:-1])[at[-1]] = value


def _renamed_text(text: str, old: str, new: str) -> str:
    """The quantity text with each use of the name ``old`` written ``new``, token by token."""
    out, last = [], 0
    for start, end, name in name_spans(str(text)):
        if name == old:
            out += [str(text)[last:start], new]
            last = end
    return "".join(out) + str(text)[last:]


def written(project: Project) -> list[Path]:
    """The files whose text the edits changed."""
    changed = []
    for study, doc in project.docs.items():
        path = project.path(study)
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if tomlkit.dumps(doc) != before:
            changed.append(path)
    return changed
