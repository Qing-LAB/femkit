#!/usr/bin/env python
"""The user manual's examples, run as the person types them (docs/README.md § 3.1, M4).

    python tools/manual.py                         # run every chapter, write what femkit printed into it
    python tools/manual.py docs/manual/4-check-it.md  # one chapter

Run from the checkout on the control environment's own `python`. Each chapter runs as one
session, in a home folder of its own that is removed after; nothing of the person's is read or
written. An example whose output changed is written back into its chapter, for the person to read
as `git diff docs/manual/`; the basic tests (tests/basic/test_manual.py) hold every example to
what femkit prints.

How a chapter marks what runs — nothing of it shows on GitHub but the blocks themselves:

- A ```console block is run. Each line opening with `$ ` is what the person types, every other
  line what it prints. A typed line is `femkit …`, run from the folder the session is in through
  the `femkit` command the install script writes — made from the same source,
  `femkit/data/launcher.sh`, in the session's home, running femkit from this checkout on this
  Python; `cd FOLDER`, which moves the session; or one of the shell commands `SHELL` names, run
  by bash. A session starts in its home folder, `~`, as a person's shell does.
- A file the story writes or changes is the block after an HTML comment:
  `<!-- write PATH -->` before a block that is the file's whole text, and `<!-- edit PATH -->`
  before a ```diff block: its `-` lines, with its unmarked context lines, are in the file once,
  and become its `+` lines, with the same context. PATH is from the session's folder, or `~/…`.
- Every other block is shown, never run: ```bash for a command that cannot run here —
  installing environments, `doctor` — its femkit commands still checked by the tests.

What femkit prints is shown as the person sees it, with three changes only, each for something
that differs between two runs of the same example:

- the session's home folder is shown as `/home/you`, where femkit prints it whole — the home is
  `/tmp/` and four letters, as long as `/home/you`, so a table holding such a path keeps its
  columns (femkit itself writes a path under the home from `~`);
- a step's `done in N s` line, which femkit prints only for a step that took a second or more,
  is left out;
- the time in an operation's log folder (`…/operations/config/20261125T163159.050770Z`) is the
  time the command ran: compared as any time, and kept as the chapter shows it when nothing else
  in the example changed.

Lines are compared without trailing spaces, which a Markdown file does not keep.
"""

from __future__ import annotations

import os
import re
import secrets
import shlex
import shutil
import string
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

REPO = Path(__file__).resolve().parent.parent
MANUAL = REPO / "docs" / "manual"

COMMAND = "femkit"                 # what the person types, the command the install script writes
PROG = ("python", "-m", "femkit")  # the form the install script forwards by: checked in a bash block, never run
#: The shell commands a console block may run besides femkit, each a file operation a person does
#: by hand in the story: show a file, copy, move or remove one, make a folder, list one.
SHELL = frozenset({"cat", "cp", "ls", "mkdir", "mv", "rm"})
SHOWN_HOME = "/home/you"
#: The `femkit` command's one source, which the install script fills (envs.md § 7): read here as a
#: file — this tool imports nothing from femkit — and filled as the script fills it.
LAUNCHER = REPO / "femkit" / "data" / "launcher.sh"
#: The folder of the session's home that stands for the activated control environment's `bin/`:
#: it holds the session's `femkit` command.
ON_PATH = ".control-bin"
SEPARATORS = ("&&", "||", ";", "|", "&")         # what ends a command on a shell line
ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")       # `NAME=value` before a command, which it runs with

FENCE = re.compile(r"^(`{3,})\s*([\w+-]*)\s*$")
DIRECTIVE = re.compile(r"^<!--\s*(write|edit)\s+(\S+)\s*-->\s*$")
STAMP = re.compile(r"\d{8}T\d{6}\.\d{6}Z")
TOOK = re.compile(r"^\s*\[\s*\d+/\d+\] done in .+$")
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
INLINE_CODE = re.compile(r"`+[^`]*`+")


class ManualError(Exception):
    """A chapter that cannot run as written: its place, and why."""


# ------------------------------------------------------------------ reading a chapter

@dataclass
class Block:
    """One fenced block: its language, its lines, the index of its opening fence in the file, and
    the directive above it, if any."""

    lang: str
    lines: list[str]
    start: int
    directive: tuple[str, str] | None = None


@dataclass
class Example:
    """One typed line of a console block and what the chapter shows under it; ``first`` and
    ``last`` bound those lines in the file, 0-based, ``last`` excluded."""

    file: Path
    line: int  # 1-based, the typed line's
    typed: str
    shown: list[str]
    first: int
    last: int
    printed: list[str] = field(default_factory=list)


def chapters() -> list[Path]:
    """The chapters, `docs/manual/<n>-<name>.md`, in their order."""
    return sorted(MANUAL.glob("[0-9]*-*.md"), key=lambda p: int(p.name.split("-", 1)[0]))


def documents() -> list[Path]:
    """Every file of the manual: its chapters and its README."""
    return sorted(MANUAL.glob("*.md"))


def blocks(path: Path) -> list[Block]:
    """The fenced blocks of a manual file, each with the directive bound to it; a directive bound
    to no block is refused."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[Block] = []
    pending: tuple[str, str, int] | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        opened = FENCE.match(line)
        if opened:
            ticks, lang = opened.groups()
            j = i + 1
            while j < len(lines) and not (lines[j].startswith(ticks) and lines[j].strip("`").strip() == ""):
                j += 1
            if j == len(lines):
                raise ManualError(f"{path.name}:{i + 1}: a block opened here is never closed")
            out.append(Block(lang, lines[i + 1:j], i, pending[:2] if pending else None))
            pending = None
            i = j + 1
            continue
        directive = DIRECTIVE.match(line)
        if directive:
            if pending:
                raise ManualError(f"{path.name}:{pending[2] + 1}: `{pending[0]}` is followed by no block")
            pending = (directive.group(1), directive.group(2), i)
        elif line.strip() and pending:
            raise ManualError(f"{path.name}:{pending[2] + 1}: `{pending[0]}` is followed by text, not a block")
        i += 1
    if pending:
        raise ManualError(f"{path.name}:{pending[2] + 1}: `{pending[0]}` is followed by no block")
    return out


def examples(path: Path, block: Block) -> list[Example]:
    """A console block's typed lines, each with the lines the chapter shows under it."""
    out: list[Example] = []
    for k, line in enumerate(block.lines):
        at = block.start + 1 + k
        if line.startswith("$ "):
            out.append(Example(path, at + 1, line[2:], [], at + 1, at + 1))
        elif not out:
            raise ManualError(f"{path.name}:{at + 1}: a console block opens with a typed line, `$ …`")
        else:
            out[-1].shown.append(line)
    for example in out:  # a blank line before the next typed line only separates them
        while example.shown and not example.shown[-1].strip():
            example.shown.pop()
        example.last = example.first + len(example.shown)
    return out


# ------------------------------------------------------------------ the words a line holds

def expand(line: str, home: Path) -> str:
    """The line with `~` expanded where bash expands it: at the start of a word outside quotes."""
    out, quote, start = [], None, True
    for i, ch in enumerate(line):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "~" and start and (i + 1 == len(line) or line[i + 1] in "/ \t"):
            out.append(str(home))
            start = False
            continue
        out.append(ch)
        start = quote is None and ch in " \t"
    return "".join(out)


def commands(line: str) -> list[list[str]]:
    """Each femkit command a shell line holds, as its words after `femkit` — `femkit` where a
    command starts, `python -m femkit` anywhere, and the install script's verb as the `env`
    command it forwards to (envs.md § 7) — up to the end of the command: a comment, `&&`, `||`,
    `;`, `|` or `&`."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise ManualError(f"`{line}` does not read as a shell line: {exc}") from None
    out, i, starts = [], 0, True   # starts: tokens[i] is where a command starts
    while i < len(tokens):
        if tuple(tokens[i:i + 3]) == PROG:
            start, prefix = i + 3, []
        elif starts and tokens[i] == COMMAND:
            start, prefix = i + 1, []
        elif tokens[i].endswith("install-env.sh"):
            start, prefix = i + 1, ["env"]
        else:
            starts = tokens[i] in SEPARATORS or (starts and ASSIGNMENT.match(tokens[i]) is not None)
            i += 1
            continue
        end = start
        while end < len(tokens) and tokens[end] not in SEPARATORS:
            end += 1
        out.append(prefix + tokens[start:end])
        i = end
    return out


def shell_lines(path: Path) -> list[tuple[int, str]]:
    """Every line of a code block that a person types: each `$ ` line of a console block, and
    every line of a bash block."""
    out = []
    for block in blocks(path):
        if block.lang == "console":
            out += [(e.line, e.typed) for e in examples(path, block)]
        elif block.lang in ("bash", "sh", "shell"):
            out += [(block.start + 2 + k, line) for k, line in enumerate(block.lines)]
    return out


def links(path: Path) -> list[tuple[int, str]]:
    """Every link of a manual file outside its code: its line and its target."""
    out, inside = [], None
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fence = FENCE.match(line)
        if fence and inside is None:
            inside = fence.group(1)
            continue
        if inside is not None:
            if line.startswith(inside) and not line.strip("`").strip():
                inside = None
            continue
        out += [(n, target) for target in LINK.findall(INLINE_CODE.sub("", line))]
    return out


# ------------------------------------------------------------------ a session

def shell_word(value: str) -> str:
    """``value`` as one single-quoted shell word, each `'` in it written `'\\''`: as the install
    script quotes what it fills the `femkit` command's text with."""
    return "'" + value.replace("'", "'\\''") + "'"


def launcher(path: Path, python: str, checkout: Path) -> Path:
    """The `femkit` command the install script writes, made at ``path`` from its one source as the
    script fills it — `{checkout}`, then `{python}`, each a shell word — running femkit from
    ``checkout`` on ``python``."""
    text = LAUNCHER.read_bytes().decode("utf-8")
    text = text.replace("{checkout}", shell_word(str(checkout))).replace("{python}", shell_word(python))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    path.chmod(0o755)
    return path


@contextmanager
def home() -> Iterator[Path]:
    """A home folder of the session's own: `/tmp/` and four letters, as long as the `/home/you`
    the manual shows, holding the `femkit` command, running femkit from this checkout on this
    Python, in `ON_PATH`; removed after."""
    letters = string.ascii_lowercase + string.digits
    for _ in range(1000):
        path = Path("/tmp") / "".join(secrets.choice(letters) for _ in range(4))
        try:
            path.mkdir(mode=0o700)
            break
        except FileExistsError:
            continue
    else:
        raise ManualError("no free name for a home folder under /tmp")
    try:
        launcher(path / ON_PATH / COMMAND, sys.executable, REPO)
        yield path
    finally:
        shutil.rmtree(path)


#: Variables a session's commands never inherit: femkit's own directories and the XDG ones, so
#: femkit finds each in the session's home by its default rule (config.md § 2); a Python path,
#: which the `femkit` command sets to its checkout.
UNSET = re.compile(r"^(FEMKIT_\w+_DIR|XDG_\w+|PYTHONPATH|PYTHONHOME)$")


def environment(base: dict[str, str], home_folder: Path) -> dict[str, str]:
    """The variables a session's commands run with: ``base`` without `UNSET`'s, the session's
    home, a terminal 80 columns wide — what click wraps a help text to — and Python writing each
    line as it prints it, in UTF-8, with no user site and no cached bytecode in the checkout."""
    env = {k: v for k, v in base.items() if not UNSET.match(k)}
    env.update(HOME=str(home_folder), COLUMNS="80", LC_ALL="C.UTF-8", PYTHONNOUSERSITE="1",
               PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    return env


def shown_as(printed: str, home_folder: Path) -> list[str]:
    """What femkit printed, as the manual shows it (this module's docstring)."""
    lines = [line.rstrip() for line in printed.replace(str(home_folder), SHOWN_HOME).splitlines()
             if not TOOK.match(line)]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def same(shown: list[str], printed: list[str]) -> bool:
    """Whether the manual shows what was printed, any time in a log folder's name aside."""
    return [STAMP.sub("<time>", s) for s in shown] == [STAMP.sub("<time>", p) for p in printed]


def place(path: str, cwd: Path, home_folder: Path) -> Path:
    return Path(os.path.normpath(cwd / expand(path, home_folder)))


def change(path: Path, block: Block, directive: tuple[str, str], cwd: Path, home_folder: Path) -> None:
    """A file the story writes or changes, by the directive above ``block``."""
    verb, target = directive
    where = place(target, cwd, home_folder)
    at = f"{path.name}:{block.start + 1}"
    if verb == "write":
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_text("\n".join(block.lines) + "\n", encoding="utf-8")
        return
    if block.lang != "diff":
        raise ManualError(f"{at}: `edit` is followed by a ```diff block, not ```{block.lang}")
    old, new = [], []
    for line in block.lines:
        mark, text = line[:1], line[1:]
        if mark == "-":
            old.append(text)
        elif mark == "+":
            new.append(text)
        elif mark in (" ", ""):
            old.append(text)
            new.append(text)
        else:
            raise ManualError(f"{at}: a diff line opens with `-`, `+` or a space, not {line!r}")
    if not where.is_file():
        raise ManualError(f"{at}: `edit {target}`: there is no such file")
    text, before, after = where.read_text(encoding="utf-8"), "\n".join(old), "\n".join(new)
    if text.count(before) != 1:
        raise ManualError(f"{at}: `edit {target}`: its `-` lines are in the file {text.count(before)} times, not once")
    where.write_text(text.replace(before, after), encoding="utf-8")


def run_line(typed: str, cwd: Path, env: dict[str, str], home_folder: Path) -> tuple[Path, str]:
    """One typed line run: the folder the session is in after it, and what it printed."""
    try:
        words = shlex.split(typed)
    except ValueError as exc:
        raise ManualError(f"`{typed}` does not read as a shell line: {exc}") from None
    if words and words[0] == "cd":
        if len(words) != 2:
            raise ManualError(f"`{typed}`: cd takes one folder")
        target = place(words[1], cwd, home_folder)
        if not target.is_dir():
            return cwd, f"bash: cd: {words[1]}: No such file or directory\n"
        return target, ""
    if words and words[0] == COMMAND:
        argv = [str(home_folder / ON_PATH / COMMAND), *shlex.split(expand(typed, home_folder))[1:]]
    elif words and words[0] in SHELL:
        argv = ["bash", "-c", typed]
    else:
        raise ManualError(f"`{typed}`: a console block runs `femkit`, `cd` and {', '.join(sorted(SHELL))}, "
                          "as the person types them; show any other command in a ```bash block")
    done = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          encoding="utf-8", errors="replace", timeout=300, check=False)
    return cwd, done.stdout


def run(path: Path, base: dict[str, str]) -> list[Example]:
    """Every example of a chapter, run in order in one session, each with what it printed."""
    out: list[Example] = []
    with home() as home_folder:
        env, cwd = environment(base, home_folder), home_folder
        for block in blocks(path):
            if block.directive:
                change(path, block, block.directive, cwd, home_folder)
            if block.lang != "console":
                continue
            for example in examples(path, block):
                cwd, printed = run_line(example.typed, cwd, env, home_folder)
                example.printed = shown_as(printed, home_folder)
                out.append(example)
    return out


# ------------------------------------------------------------------ writing what femkit printed back

def rewrite(path: Path) -> int:
    """Run ``path`` and write back each example whose printed lines differ from what it shows;
    the number written."""
    base = {k: v for k, v in os.environ.items() if k not in ("FEMKIT_ENV_MANAGER", "CONDA_EXE", "MAMBA_EXE")}
    ran = run(path, base)
    lines = path.read_text(encoding="utf-8").splitlines()
    changed = 0
    for example in reversed(ran):
        if not same(example.shown, example.printed):
            lines[example.first:example.last] = example.printed
            changed += 1
    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def main(argv: list[str]) -> int:
    targets = [Path(a).resolve() for a in argv] or chapters()
    for path in targets:
        try:
            n = rewrite(path)
        except ManualError as exc:
            print(f"{path.relative_to(REPO)}: {exc}", file=sys.stderr)
            return 1
        print(f"{path.relative_to(REPO)}: {n} example{'' if n == 1 else 's'} written" if n else
              f"{path.relative_to(REPO)}: as shown")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
