"""The one static reader of a file of the person's functions (framework.md § 5; models.md §§ 3,
5.2): `definitions.py`, `observe.py` — read without running it, by Python's own `ast`.

What it finds: each function at the file's top level, by its name — its line, how many positional
arguments it takes (`arguments`, none for one taking others: `*args`, a keyword-only argument,
`**kwargs`), each `<alias>.<name>` it reads of the module femkit gives it, each
`<first argument>.<table>.<name>` it reads of the one object femkit hands it, for each table its
caller names — an observable's `case.defs.<name>` and `case.groups.<name>` — and each name it calls —
and each fault, at its line: `not-python`, a text Python does not read; `top-level`, a statement at
its top level that is neither an import nor a function, which would run something as the file is
read; `bad-import`, an import of anything but what it may import — the module femkit gives it, as
the alias it must take, the modules its environment provides, and the ones always allowed beside
them — each said with what would let the file import it, where its caller says what would. Each
caller tells it the file's name, what it may import and the module it is given; the signature each
function must have is the caller's to hold it to, by `arguments`, and what it reads
of what it is handed to what it declares it takes, by `handed` — through each function of the file it
calls, handed the same object first.

Standard library only: it runs in the control process, and beside femkit's programs inside an
environment (framework.md § 1).
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from typing import Callable, Iterable


@dataclass(frozen=True)
class Function:
    """One function of a file, as read without running it."""

    line: int
    arguments: int | None          # how many positional arguments it takes; None for one taking others
    reads: dict[str, int]          # each `<alias>.<name>` it reads of the module it is given, with its first line
    calls: frozenset[str]          # each name it calls as a function: the file's own among them
    handed: dict[tuple[str, str], int] = field(default_factory=dict)   # each (table, name) it reads of its first
                                                                         # argument, with its first line

    @property
    def takes(self) -> bool:
        """Whether it takes any argument."""
        return self.arguments != 0


@dataclass(frozen=True)
class Fault:
    """What is wrong in a file of the person's functions, at its line."""

    line: int | None
    code: str
    message: str


@dataclass(frozen=True)
class Written:
    """A file of the person's functions read without running it: each function by its name, and
    every fault."""

    functions: dict[str, Function]
    faults: tuple[Fault, ...]

    def reads(self, name: str) -> dict[str, int]:
        """Every `<alias>.<name>` the function ``name`` reads, through each of the file's functions it
        calls, with the first line reading it."""
        return self._through(name, lambda f: f.reads)

    def handed(self, name: str) -> dict[tuple[str, str], int]:
        """Every `<table>.<name>` the function ``name`` reads of the object it is handed first,
        through each of the file's functions it calls, with the first line reading it."""
        return self._through(name, lambda f: f.handed)

    def _through(self, name: str, of) -> dict:
        """What ``of`` gives of the function ``name`` and of each of the file's functions it calls,
        each with its first line."""
        out: dict = {}
        walking, seen = [name], set()
        while walking:
            now = walking.pop()
            if now in seen or now not in self.functions:
                continue
            seen.add(now)
            for read_, line in of(self.functions[now]).items():
                out.setdefault(read_, line)
            walking += sorted(self.functions[now].calls)
        return out


def read(text: str, *, name: str, modules: Iterable[str], gives: tuple[str, str] | None = None,
         always: Iterable[str] = (), handed: Iterable[str] = (),
         beyond: Callable[[str], str] | None = None) -> Written:
    """``text``, the file ``name`` of the person's functions, read without running it: each function
    at its top level, with what it reads of each table ``handed`` names of the object it is handed
    first; and each fault — a text Python does not read, a statement at its top level that is neither
    an import nor a function, an import of anything but ``gives`` — femkit's module and the alias it
    is imported as — ``modules``, those its environment provides, and ``always``: said with what
    would be right, ``beyond`` of the top-level module it names, where its caller can say what would
    let the file import it — `observe.py`'s, its project's packages (models.md § 5.2)."""
    modules, always = sorted(modules), list(always)
    allowed = {*modules, *always}
    module, alias = gives if gives is not None else (None, None)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return Written({}, (Fault(exc.lineno, "not-python", f"{name} does not read as Python: {exc.msg}"),))
    functions: dict[str, Function] = {}
    faults: list[Fault] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.decorator_list:
            functions[node.name] = _function(node, alias, frozenset(handed))
        elif not isinstance(node, (ast.Import, ast.ImportFrom)):
            line = node.decorator_list[0].lineno if getattr(node, "decorator_list", None) else node.lineno
            faults.append(Fault(line, "top-level", f"{name} holds imports and functions alone, and this runs "
                                                   "something as the file is read"))
    said = _said(module, alias, modules, always)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if module is not None and a.name == module and a.asname != alias:
                    faults.append(Fault(node.lineno, "bad-import", f"{name} imports {module} as "
                                                                   f"`import {module} as {alias}`, and reads each "
                                                                   f"of its values as `{alias}.<name>`"))
                elif a.name != module and a.name.split(".")[0] not in allowed:
                    faults.append(Fault(node.lineno, "bad-import", f"{name} imports `{a.name}`, and may import "
                                                                   f"only {said}" + _right(a.name, beyond)))
        elif isinstance(node, ast.ImportFrom):
            source = node.module or ""
            if node.level or source.split(".")[0] not in allowed:
                right = _right(source, beyond) if not node.level else ""
                faults.append(Fault(node.lineno, "bad-import", f"{name} imports from `{'.' * node.level}{source}`, "
                                                               f"and may import only {said}" + right))
    return Written(functions, tuple(faults))


def _right(imported: str, beyond: Callable[[str], str] | None) -> str:
    """What would let a file import ``imported``, as the end of its fault's sentence: ``beyond`` of
    its top-level module; nothing where its caller says nothing, or for a module of Python's own
    standard library, which no package brings."""
    top = imported.split(".")[0]
    return f"; {beyond(top)}" if beyond is not None and top not in sys.stdlib_module_names else ""


def _said(module: str | None, alias: str | None, modules: list[str], always: list[str]) -> str:
    """What a file may import, as a sentence names it."""
    parts = [f"`import {module} as {alias}`"] if module is not None else []
    if modules:
        parts.append(f"the modules {', '.join(modules)}")
    if always:
        parts.append(" and ".join(f"`{m}`" for m in always))
    return ", ".join(parts[:-1]) + (" — and " if len(parts) > 1 else "") + parts[-1] if parts else "nothing"


def _function(node: ast.FunctionDef, alias: str | None, tables: frozenset[str]) -> Function:
    """A function as read without running it: its line, how many positional arguments it takes,
    each `<alias>.<name>` it reads, each `<first argument>.<table>.<name>` it reads of one of
    ``tables``, and each name it calls."""
    a = node.args
    first = (a.posonlyargs + a.args)[0].arg if a.posonlyargs + a.args else None
    reads: dict[str, int] = {}
    handed: dict[tuple[str, str], int] = {}
    calls: set[str] = set()
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Attribute):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                calls.add(inner.func.id)
            continue
        if alias is not None and isinstance(inner.value, ast.Name) and inner.value.id == alias:
            reads.setdefault(inner.attr, inner.lineno)
        held = inner.value
        if first is not None and isinstance(held, ast.Attribute) and held.attr in tables \
                and isinstance(held.value, ast.Name) and held.value.id == first:
            handed.setdefault((held.attr, inner.attr), inner.lineno)
    others = bool(a.vararg or a.kwonlyargs or a.kwarg)
    return Function(line=node.lineno, arguments=None if others else len(a.posonlyargs) + len(a.args),
                    reads=reads, calls=frozenset(calls), handed=handed)
