"""Atomic writes and reads (core.md § 4). Every file femkit writes goes through here."""

from __future__ import annotations

import copy
import json
import hashlib
import os
import re
import shutil
import stat
import tarfile
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any, Callable, Iterable, Mapping

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
    """``text`` added at the end of ``path`` — a log's lines, an event log's record — its folders
    made; what was there stays. The one appender: flushed and fsynced before it returns, so what
    it added outlives the process (core.md §§ 4, 6)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


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


def make_folder(path: Path) -> Path:
    """``path`` as a folder, made with its parents when it is not there; what it holds stays."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return Path(path)


def empty_folder(path: Path) -> Path:
    """``path`` as an empty folder, whatever was there before."""
    remove(path)
    Path(path).mkdir(parents=True)
    return Path(path)


def _new_folder(path: Path, fill: Callable[[Path], object]) -> Path:
    """A folder at ``path``, which is not there yet, filled by ``fill`` beside it and renamed in,
    whole: an interrupted fill leaves nothing at ``path``. A `FileExistsError` when something is
    there already."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"{path} is there already")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{path.name}.", dir=path.parent) as scratch:
        fresh = Path(scratch) / path.name
        fill(fresh)
        os.rename(fresh, path)
    return path


def _inside(folder: Path, rel: str) -> Path:
    """``rel``, a POSIX path from ``folder``, as a path inside it; a ValueError for one leaving it."""
    steps = PurePosixPath(rel).parts
    if PurePosixPath(rel).is_absolute() or ".." in steps or not steps:
        raise ValueError(f"{rel!r} is no path inside {folder}")
    return Path(folder).joinpath(*steps)


def copy_tree(source: Path, path: Path, only: Iterable[str] | None = None) -> Path:
    """A copy of the folder ``source`` at ``path``, which is not there yet: copied beside it and
    renamed in, whole — an interrupted copy leaves nothing at ``path`` (core.md § 4). ``only``:
    just these files, each by its POSIX path from ``source``, in the folders that hold them."""

    def fill(fresh: Path) -> None:
        if only is None:
            shutil.copytree(source, fresh)
            return
        fresh.mkdir()
        for rel in only:
            _inside(source, rel)
            _inside(fresh, rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_inside(source, rel), _inside(fresh, rel))

    return _new_folder(path, fill)


def write_folder(path: Path, files: Mapping[str, bytes]) -> Path:
    """A new folder at ``path``, which is not there yet, holding ``files`` — each by its POSIX path
    from it, with its bytes: written beside it and renamed in, whole, as `copy_tree` copies — an
    interrupted write leaves nothing at ``path`` (core.md § 4)."""

    def fill(fresh: Path) -> None:
        fresh.mkdir()
        for rel, data in files.items():
            _inside(fresh, rel).parent.mkdir(parents=True, exist_ok=True)
            _inside(fresh, rel).write_bytes(data)

    return _new_folder(path, fill)


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


def json_text(data: Any) -> str:
    """The text `write_json` writes: sorted keys, two-space indent, a final newline — for a file
    written among others, as one folder written whole (`write_folder`)."""
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def write_json(path: Path, data: Any, *, private: bool = False) -> Path:
    return atomic_write_text(path, json_text(data), private=private)


def canonical_sha256(data: Any) -> str:
    """The SHA-256 of ``data``'s canonical JSON — keys sorted, no whitespace, UTF-8 — so two
    spellings of one value give one digest: the one digest of a value, as `sha256` is of a file
    (a case's ID, a fingerprint, a plan's digest, a part's files; models.md § 5.3)."""
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_toml(path: Path, data: dict) -> Path:
    return atomic_write_text(path, tomlkit.dumps(data))


def read_toml(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def json_value(text: str) -> Any:
    """A JSON text read already — one of femkit's outputs a project's door reads (projects.md § 6)
    — as plain Python, as `read_json` reads a file; a ValueError saying why for one that is not
    JSON."""
    return json.loads(text)


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


def private_dir(path: Path, *, make: bool = True) -> Path:
    """``path``, made if absent — each folder made here 0700 — and entered by this account
    alone. Refused, naming the folder, when it is another account's, or a folder above it
    lets another account replace what is inside: owned by another account, or writable by
    others and not sticky (a group's write counts unless the group is this account's own).
    ``make=False``: only the refusals, nothing made or changed — what a plan checks."""
    path = Path(path)
    missing = [p for p in [path, *path.parents] if not p.exists()]
    if not make:
        if missing and missing[-1].parent.exists():
            for above in [missing[-1].parent.resolve(), *missing[-1].parent.resolve().parents]:
                if _replaceable_by_others(above.stat()):
                    raise UsageError(f"{above} lets other accounts replace what is inside it, so {path} below it "
                                     "cannot be kept private", code="not-private", subject=str(path))
            return path
    for folder in reversed(missing):
        folder.mkdir(mode=PRIVATE_DIR)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
        raise UsageError(f"{path} is not a folder of this account's own", code="not-private", subject=str(path))
    if info.st_mode & 0o077 and make:
        os.chmod(path, PRIVATE_DIR)
    for above in path.resolve().parents:
        if _replaceable_by_others(above.stat()):
            raise UsageError(f"{above} lets other accounts replace what is inside it, so {path} below it "
                             "cannot be kept private", code="not-private", subject=str(path))
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


# ------------------------------------------------------------ TOML as a document
#
# `config.toml` keeps its comments, its order and its layout through every edit `config set`
# makes: read as a document, changed key by key, written whole and atomically. A project's
# files are only read so: a part's text as its file holds it (projects.md § 6). A template's
# keys are read with the comments above them, their help (projects.md § 7).

Key = tuple[str, ...]


def read_document(path: Path, empty: str = "") -> tomlkit.TOMLDocument:
    """``path`` as an editable document, its comments kept; ``empty`` when it does not exist."""
    path = Path(path)
    return tomlkit.parse(path.read_text(encoding="utf-8") if path.exists() else empty)


def write_document(path: Path, doc: tomlkit.TOMLDocument) -> Path:
    return atomic_write_text(path, tomlkit.dumps(doc))


def plain_value(text: str) -> Any:
    """A TOML inline value as a person types it — `"1 nm"`, `2`, `[0, 0]`, `{ kind = "x" }` —
    as plain Python: a number, text, a list, a dict; or ValueError."""
    try:
        doc = tomlkit.parse(f"value = {text}")
    except tomlkit.exceptions.TOMLKitError as exc:
        raise ValueError(f"{text!r} is not a TOML value: {exc}") from None
    if list(doc) != ["value"]:
        raise ValueError(f"{text!r} is not one TOML value")
    return doc.unwrap()["value"]


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
    so its form, its order and its comments stay; a key not there yet goes directly under the
    line that shows it commented out, so it stands under its help (config.md § 3.2)."""
    parent = _parent(doc, key, create=True)
    held = parent.get(key[-1]) if hasattr(parent, "get") else None
    if isinstance(value, dict) and isinstance(held, (tomlkit.items.Table, tomlkit.items.InlineTable)):
        _merge(held, value)
    elif held is None and (at := _shown_at(parent, key[-1])) is not None:
        _body(parent)._insert_at(at + 1, key[-1], value)   # tomlkit's own insertion: its index kept whole
    else:
        parent[key[-1]] = value


def _body(table: Any) -> Any:
    return table if isinstance(table, tomlkit.TOMLDocument) else table.value


def _shown_at(table: Any, name: str) -> int | None:
    """Where in ``table`` the last comment line showing the key ``name`` stands, when a line
    follows it; None otherwise, where an appended key lands as well."""
    if not isinstance(table, (tomlkit.TOMLDocument, tomlkit.items.Table)):
        return None
    body = _body(table).body
    shows = [i for i, (k, item) in enumerate(body) if k is None and isinstance(item, tomlkit.items.Comment)
             and [(c.path, c.header) for c in key_comments(item.as_string())] == [((name,), False)]]
    return shows[-1] if shows and shows[-1] < len(body) - 1 else None


def _merge(table: Any, value: dict) -> None:
    for gone in [k for k in table if k not in value]:
        del table[gone]
    for k, v in value.items():
        if isinstance(v, dict) and isinstance(table.get(k), (tomlkit.items.Table, tomlkit.items.InlineTable)):
            _merge(table[k], v)
        elif k not in table or table[k] != v:
            table[k] = v


@dataclass(frozen=True)
class KeyComment:
    """A key or table header a TOML text writes, or shows commented out, and the comment lines
    directly above it (projects.md § 7)."""

    path: Key        # its keys from the text's root, as TOML reads them: `("numerics", "solver", "kind")`
    line: int        # its line, from 1
    header: bool     # a table header, `[numerics.solver]`, rather than a key
    shown: bool      # commented out: a key the text leaves unset, shown under its help
    value: Any       # what it sets or shows, as TOML reads it; None for a header
    comment: str     # the comment lines directly above it that are no key, read without their `#`
                     # and joined by single spaces; "" when there are none


BARE = re.compile(r"[A-Za-z0-9_-]+")   # a key TOML writes bare; any other it quotes (core.md § 2)
_PART = rf'{BARE.pattern}|"(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\''
_WRITES = re.compile(rf'\s*(\[\[?)?\s*((?:{_PART})(?:\s*\.\s*(?:{_PART}))*)\s*(?:\]\]?|=)')


def key_comments(text: str) -> list[KeyComment]:
    """Every key and table header ``text`` writes or shows commented out, in order, each with
    the comment above it — the one reader of a template's help (projects.md § 7). The comment
    lines directly above a key, with no blank line between, are its help; a comment line that
    reads as a TOML key or table header is itself a key, shown — on one line — under its help;
    a comment followed by a blank line is the text's prose. A shown header heads the shown keys
    after it, until a key is set; a key's path is the table it stands in and its own keys."""
    lines = text.splitlines()
    found: list[KeyComment] = []
    table: Key = ()
    shown_table: Key = ()
    above: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        start, i = i, i + 1
        if not line:
            above = []
            continue
        shown = line.startswith("#")
        if shown:
            written = _written(line[1:].strip())
        else:                                   # a statement: the fewest lines that read as TOML
            end = next((j for j in range(i, len(lines) + 1) if _written("\n".join(lines[start:j]))), i)
            written, i = _written("\n".join(lines[start:end])), end
        if written is None:
            above = above + [line[1:].strip()] if shown else []
            continue
        keys, header, value = written
        path = keys if header else (shown_table if shown else table) + keys
        if header:
            shown_table = path
            table = table if shown else path
        elif not shown:
            shown_table = table
        found.append(KeyComment(path=path, line=start + 1, header=header, shown=shown, value=value,
                                comment=" ".join(a for a in above if a)))
        above = []
    return found


def _written(statement: str) -> tuple[Key, bool, Any] | None:
    """The keys ``statement`` writes, whether it is a table header, and its value; None when
    it is no TOML key or header."""
    try:
        data = tomllib.loads(statement)
    except tomllib.TOMLDecodeError:
        return None
    match = _WRITES.match(statement)
    if not data or not match:
        return None
    keys: Any = tomllib.loads(f"{match.group(2)} = 0")     # its keys as TOML reads them, quotes undone
    path: list[str] = []
    while isinstance(keys, dict):
        (key, keys), = keys.items()
        path.append(key)
    value: Any = None if match.group(1) else data
    for key in path if not match.group(1) else ():
        value = value[key]
    return tuple(path), bool(match.group(1)), value


def document_text(doc: Any, key: Key) -> str:
    """The entry at ``key`` as its file writes it: a table as a TOML document of its own — its
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


def _headers_from_keys(item: Any) -> None:
    """A parsed table keeps its header's text (`[axes."parameters.bias"]`); forgetting it, in
    the table and every table under it, has each header written from its keys again — relative
    to the table, when it stands as a document of its own."""
    if isinstance(item, tomlkit.items.Table):
        item.display_name = None
        for _, child in item.value.body:
            _headers_from_keys(child)
    elif isinstance(item, tomlkit.items.AoT):
        for table in item.body:
            _headers_from_keys(table)


@dataclass(frozen=True)
class Shown:
    """A key a person's file leaves unset, shown commented out under its help with ``value`` as
    what it would take — an empty table: its header alone (projects.md § 7)."""

    value: Any


def commented_text(data: Mapping[str, Any], comment: Callable[[Key], str | None], prose: str = "") -> str:
    """``data``, plain values, as the TOML text of a file a person reads and edits as their own
    (projects.md § 7) — what `key_comments` reads back: ``prose``'s lines first, each a comment,
    and a blank line; then each key under ``comment(path)``, its path from the root as
    `key_comments` gives it — a list's index left out — as one comment line, none where it
    gives None; a table under its own header, a list of tables each table under its own; a
    `Shown` value commented out. A blank line stands before each key at the top and each
    header; the keys of one table follow each other."""
    doc = tomlkit.document()
    for line in prose.splitlines():
        doc.add(tomlkit.comment(line))
    _commented(doc, (), data, comment)
    _unindented(doc)
    return tomlkit.dumps(doc)


def _commented(table: Any, at: Key, data: Mapping[str, Any], comment: Callable[[Key], str | None]) -> None:
    """``data``'s keys added to ``table``, the document or a table at ``at``, as `commented_text`
    writes them."""
    for key, value in data.items():
        path, held = (*at, key), value.value if isinstance(value, Shown) else value
        tables = isinstance(held, list) and bool(held) and all(isinstance(v, dict) for v in held)
        header, said = isinstance(held, dict) or tables, comment(path)
        if header and at or not at and len(table.body):
            table.add(tomlkit.nl())
        if said is not None:
            table.add(tomlkit.comment(said))
        if isinstance(value, Shown):
            shown = f"[{'.'.join(tomlkit.key(k).as_string() for k in path)}]" if held == {} else \
                f"{tomlkit.key(key).as_string()} = {inline_text(held)}"
            table.add(tomlkit.comment(shown))
        elif isinstance(held, dict):
            own = tomlkit.table(is_super_table=False)
            _commented(own, path, held, comment)
            table.add(key, own)
        elif tables:
            each = tomlkit.aot()
            for i, entry in enumerate(held):
                own = tomlkit.table(is_super_table=False)
                _commented(own, path, entry, comment)
                if i < len(held) - 1:                # the next table's help stands at this one's end
                    own.add(tomlkit.nl())
                    if said is not None:
                        own.add(tomlkit.comment(said))
                each.append(own)
            table.add(key, each)
        else:
            table.add(key, _inline(value))


def _unindented(item: Any) -> None:
    """Every header in ``item`` written where its line stands, with no blank line tomlkit puts
    before it: `commented_text` writes its own, so a header stays directly under its help."""
    if isinstance(item, tomlkit.items.AoT):
        for table in item.body:
            _unindented(table)
        return
    if isinstance(item, tomlkit.items.Table):
        item.trivia.indent = ""
    for _, child in _body(item).body if isinstance(item, (tomlkit.TOMLDocument, tomlkit.items.Table)) else ():
        _unindented(child)


def read_text(path: Path) -> str | None:
    """A file's text as its bytes hold it — line endings kept, UTF-8 — or None when no file is there."""
    path = Path(path)
    return path.read_bytes().decode("utf-8") if path.is_file() else None


def read_bytes(path: Path) -> bytes | None:
    """A file's bytes, or None when no file is there."""
    path = Path(path)
    return path.read_bytes() if path.is_file() else None


BLOCK = 1 << 20   # bytes read at a time for a digest: a download may be larger than memory


def sha256(path: Path) -> str | None:
    """A file's sha256 over its bytes, read a block at a time, or None when no file is there: the
    one digest of a file (core.md § 4)."""
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(BLOCK):
            digest.update(block)
    return digest.hexdigest()
