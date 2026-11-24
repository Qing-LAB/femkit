"""Atomic writes and reads (core.md § 4). Every file femkit writes goes through here."""

from __future__ import annotations

import copy
import json
import os
import shutil
import stat
import tarfile
import tempfile
import tomllib
from pathlib import Path
from typing import IO, Any, Callable

import tomlkit

from femkit.core.errors import UsageError

PRIVATE_FILE = 0o600
PRIVATE_DIR = 0o700


def _umask() -> int:
    """This process's umask, read without changing it: setting it to read it would, for that
    moment, give another thread's new file or folder every permission."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("Umask:"):
            return int(line.split()[1], 8)
    raise RuntimeError("/proc/self/status names no umask")


def _atomic(path: Path, fill: Callable[[IO], object], *, binary: bool = False, private: bool = False,
            accept: Callable[[Path], bool] | None = None) -> bool:
    """``fill`` writes a file beside ``path``, which takes its place only when ``accept`` takes it:
    a reader sees the old file or the new one, never a part. False, nothing changed, when refused."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)  # 0600 as made
    try:
        if not private:
            os.chmod(tmp, 0o666 & ~_umask())
        with os.fdopen(fd, "wb") if binary else os.fdopen(fd, "w", encoding="utf-8") as fh:
            fill(fh)
            fh.flush()
            os.fsync(fh.fileno())
        if accept is not None and not accept(Path(tmp)):
            Path(tmp).unlink(missing_ok=True)
            return False
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def atomic_write_text(path: Path, text: str, *, private: bool = False) -> Path:
    """Write ``text`` so a reader sees the old file or the new one, never a part;
    ``private``: readable by this account alone, from its first byte."""
    _atomic(path, lambda fh: fh.write(text), private=private)
    return Path(path)


def write_stream(path: Path, source: IO[bytes], accept: Callable[[Path], bool] | None = None) -> bool:
    """``source`` read to its end into ``path``, whole or not at all: it takes ``path``'s place only
    when ``accept`` takes the written file — a download whose digest matches; False otherwise."""
    return _atomic(path, lambda fh: shutil.copyfileobj(source, fh, length=1 << 20), binary=True, accept=accept)


def copy_file(source: Path, path: Path) -> Path:
    """A copy of ``source`` at ``path``, written as `write_stream` writes."""
    with open(source, "rb") as fh:
        write_stream(path, fh)
    return Path(path)


def append_text(path: Path, text: str) -> None:
    """``text`` added at the end of ``path`` — a log's lines — its folders made; what was there stays."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def touch(path: Path) -> Path:
    """``path`` made empty if it is not there, its modification time now either way."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def remove(path: Path) -> None:
    """``path`` gone — a file, or a folder with everything in it; nothing there is no error."""
    path = Path(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def empty_folder(path: Path) -> Path:
    """``path`` as an empty folder, whatever was there before."""
    remove(path)
    Path(path).mkdir(parents=True)
    return Path(path)


def copy_tree(source: Path, path: Path) -> Path:
    """A copy of the folder ``source`` at ``path``, which is not there yet."""
    shutil.copytree(source, path)
    return Path(path)


def replace_folder(fresh: Path, path: Path) -> None:
    """``fresh`` takes ``path``'s place whole: the old folder moved aside, the fresh one renamed in,
    the old one removed — a reader finds the old folder or the new, never a part of either, and the
    place is empty only between two renames."""
    path = Path(path)
    aside = path.with_name(f".{path.name}.old")
    remove(aside)
    if path.exists():
        os.rename(path, aside)
    os.rename(fresh, path)
    remove(aside)


def unpack_single(archive: Path, path: Path) -> bool:
    """A gzipped tar's one top folder becomes ``path``, which is not there yet: unpacked beside it
    and renamed in, whole. False, nothing made, when the archive holds anything but one folder."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as scratch, tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(scratch, filter="data")
        roots = list(Path(scratch).iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            return False
        roots[0].rename(path)
    return True


def write_json(path: Path, data: Any, *, private: bool = False) -> Path:
    return atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n", private=private)


def write_toml(path: Path, data: dict) -> Path:
    return atomic_write_text(path, tomlkit.dumps(data))


def read_toml(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _own_group(gid: int) -> bool:
    """The account's private group: its primary group, named after it, with no other member."""
    import grp
    import pwd
    try:
        group, me = grp.getgrgid(gid), pwd.getpwuid(os.getuid())
    except KeyError:
        return False
    return gid == os.getgid() and group.gr_name == me.pw_name and set(group.gr_mem) <= {me.pw_name}


def _replaceable_by_others(info: os.stat_result) -> bool:
    """Another account could rename or replace what this folder holds."""
    if info.st_uid not in (os.getuid(), 0):
        return True  # its owner is another account
    if info.st_mode & stat.S_ISVTX:
        return False  # sticky (/tmp): only an entry's owner may rename or remove it
    return bool(info.st_mode & stat.S_IWOTH) or bool(info.st_mode & stat.S_IWGRP and not _own_group(info.st_gid))


def private_dir(path: Path) -> Path:
    """``path``, made if absent — each folder made here 0700 — and entered by this account
    alone. Refused, naming the folder, when it is another account's, or a folder above it
    lets another account replace what is inside: owned by another account, or writable by
    others and not sticky (a group's write counts unless the group is this account's own)."""
    path = Path(path)
    missing = [p for p in [path, *path.parents] if not p.exists()]
    for folder in reversed(missing):
        folder.mkdir(mode=PRIVATE_DIR)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
        raise UsageError(f"{path} is not a folder of this account's own")
    if info.st_mode & 0o077:
        os.chmod(path, PRIVATE_DIR)
    for above in path.resolve().parents:
        if _replaceable_by_others(above.stat()):
            raise UsageError(f"{above} lets other accounts replace what is inside it, so {path} below it "
                             "cannot be kept private")
    return path


def open_private(path: Path, mode: str) -> IO:
    """``path`` opened readable by this account alone from its first byte, never through a
    link. ``mode``: ``"a"``/``"ab"`` appends, ``"w"``/``"wb"`` truncates, ``"x"``/``"xb"``
    creates and refuses a file already there."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    flags |= os.O_APPEND if "a" in mode else os.O_EXCL if "x" in mode else os.O_TRUNC
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, flags, PRIVATE_FILE)
    if os.fstat(fd).st_mode & 0o077:
        os.fchmod(fd, PRIVATE_FILE)
    binary = "b" in mode
    return os.fdopen(fd, "ab" if binary and "a" in mode else "wb" if binary else "a" if "a" in mode else "w",
                     **({} if binary else {"encoding": "utf-8"}))


# ------------------------------------------------------------ editing TOML in place
#
# A person's file keeps its comments, its order and its layout through every edit a
# command makes (config set, model set): read as a document, changed key by key, written
# whole and atomically.

Key = tuple[str, ...]


def read_document(path: Path, empty: str = "") -> tomlkit.TOMLDocument:
    """``path`` as an editable document, its comments kept; ``empty`` when it does not exist."""
    path = Path(path)
    return tomlkit.parse(path.read_text(encoding="utf-8") if path.exists() else empty)


def write_document(path: Path, doc: tomlkit.TOMLDocument) -> Path:
    return atomic_write_text(path, tomlkit.dumps(doc))


def parse_value(text: str) -> Any:
    """A TOML inline value as a person types it — `"1 nm"`, `2`, `[0, 0]`, `{ kind = "x" }` —
    as the item a document holds, its formatting kept; or ValueError."""
    return _one_value(text)["value"]


def plain_value(text: str) -> Any:
    """`parse_value`'s value as plain Python: a number, text, a list, a dict; or ValueError."""
    return _one_value(text).unwrap()["value"]


def _one_value(text: str) -> tomlkit.TOMLDocument:
    try:
        doc = tomlkit.parse(f"value = {text}")
    except tomlkit.exceptions.TOMLKitError as exc:
        raise ValueError(f"{text!r} is not a TOML value: {exc}") from None
    if list(doc) != ["value"]:
        raise ValueError(f"{text!r} is not one TOML value")
    return doc


def _parent(doc: Any, key: Key, create: bool) -> Any:
    node = doc
    for part in key[:-1]:
        if part not in node:
            if not create:
                raise KeyError(".".join(key))
            node[part] = tomlkit.table() if isinstance(node, (tomlkit.TOMLDocument, tomlkit.items.Table)) \
                else tomlkit.inline_table()
        node = node[part]
        if not isinstance(node, (dict, tomlkit.items.Table, tomlkit.items.InlineTable)):
            raise KeyError(f"{'.'.join(key)}: {part} is a value, not a table")
    return node


def document_has(doc: Any, key: Key) -> bool:
    try:
        return key[-1] in _parent(doc, key, create=False)
    except KeyError:
        return False


def document_set(doc: Any, key: Key, value: Any) -> None:
    """``key`` set to ``value``, every table on the way made when absent. A table set over a
    table already there is changed in place, key by key — a key the value leaves out removed —
    so its form, its order and its comments stay (models.md § 11.1)."""
    parent = _parent(doc, key, create=True)
    held = parent.get(key[-1]) if hasattr(parent, "get") else None
    if isinstance(value, dict) and isinstance(held, (tomlkit.items.Table, tomlkit.items.InlineTable)):
        _merge(held, value)
    else:
        parent[key[-1]] = value


def _merge(table: Any, value: dict) -> None:
    for gone in [k for k in table if k not in value]:
        del table[gone]
    for k, v in value.items():
        if isinstance(v, dict) and isinstance(table.get(k), (tomlkit.items.Table, tomlkit.items.InlineTable)):
            _merge(table[k], v)
        elif k not in table or table[k] != v:
            table[k] = v


def document_text(doc: Any, key: Key) -> str:
    """The entry at ``key`` as a person edits it: a table as a TOML document of its own — its
    keys, its comments, its tables headed relative to it — a value as its TOML inline text."""
    item = _parent(doc, key, create=False)[key[-1]]
    if isinstance(item, tomlkit.items.InlineTable):          # one line, no comments: each key on its own
        return "".join(f"{tomlkit.key(k).as_string()} = {inline_text(v)}\n" for k, v in item.unwrap().items())
    if not isinstance(item, tomlkit.items.Table):
        return item.as_string().strip()
    own = tomlkit.document()
    for k, v in item.value.body:
        v = copy.deepcopy(v)
        if k is None:
            own.add(v)
        else:
            _headers_from_keys(v)
            own.add(k, v)
    return tomlkit.dumps(own).strip() + "\n"


def inline_text(value: Any) -> str:
    """A plain value as TOML text on one line: a table inline, a list's tables inline in it."""
    return _inline(value).as_string()


def _inline(value: Any) -> Any:
    """A plain value as an inline TOML item: a table inline, a list's tables inline in it."""
    if isinstance(value, dict):
        table = tomlkit.inline_table()
        table.update({k: _inline(v) for k, v in value.items()})
        return table
    if isinstance(value, list):
        array = tomlkit.array()
        array.extend(_inline(v) for v in value)
        return array
    return tomlkit.item(value)


def document_write(doc: Any, key: Key, text: str) -> None:
    """The entry at ``key`` made what ``text`` writes — a table's text as `document_text` gives
    it, or a value's inline text — every comment of the text kept, and the comment on the
    entry's own line kept when the text brings none; or ValueError."""
    try:
        written = tomlkit.parse(text)
    except tomlkit.exceptions.TOMLKitError:
        written = None
    parent = _parent(doc, key, create=True)
    held = parent.get(key[-1]) if hasattr(parent, "get") else None
    if written is None:
        value = parse_value(text.strip())
    else:
        value = tomlkit.table()
        for k, v in written.body:
            if k is None:
                value.add(v)
            else:
                _headers_from_keys(v)
                value.add(k, v)
        last = written.body[-1][1] if written.body else None
        if not isinstance(last, tomlkit.items.Whitespace) or last.as_string().count("\n") < 2:
            value.add(tomlkit.nl())                     # a blank line before the next table's header
    if held is not None and not value.trivia.comment and held.trivia.comment:
        value.trivia.comment, value.trivia.comment_ws = held.trivia.comment, held.trivia.comment_ws
    parent[key[-1]] = value


def document_unset(doc: Any, key: Key) -> None:
    del _parent(doc, key, create=False)[key[-1]]


def document_rename(doc: Any, key: Key, new: str) -> None:
    """The entry at ``key`` renamed ``new``, in its place, its comment kept. tomlkit offers
    this only as `Container._replace` (tomlkit < 1, control.txt); a test holds it to it."""
    parent = _parent(doc, key, create=False)
    container = parent if isinstance(parent, tomlkit.container.Container) else parent.value
    if new in container:
        raise KeyError(f"{new!r} is taken")
    item = container[key[-1]]
    container._replace(key[-1], new, item)
    _headers_from_keys(item)


def _headers_from_keys(item: Any) -> None:
    """A parsed table keeps its header's text (`[axes."parameters.bias"]`); forgetting it, in
    the renamed table and every table under it, has each header written from its keys again."""
    if isinstance(item, tomlkit.items.Table):
        item.display_name = None
        for _, child in item.value.body:
            _headers_from_keys(child)
    elif isinstance(item, tomlkit.items.AoT):
        for table in item.body:
            _headers_from_keys(table)
