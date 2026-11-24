"""The JUnit report pytest writes for an upstream suite's named tests (definitions.md § 5.3), read
by the check runner as a generic reader. Standard library only, as everything under `engines/`."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath

FILE = "junit.xml"   # in the check's own folder


def relative_nodes(tests: list[str]) -> tuple[PurePosixPath, list[str]]:
    """The deepest folder holding every named test, and the node IDs relative to it — the
    root pytest runs from, as the upstream suite's own runner does."""
    files = [PurePosixPath(node.split("::", 1)[0]) for node in tests]
    common: list[str] = []
    for column in zip(*(f.parent.parts for f in files)):
        if len(set(column)) != 1:
            break
        common.append(column[0])
    root = PurePosixPath(*common)
    return root, [str(f.relative_to(root)) + "::" + node.split("::", 1)[1] for f, node in zip(files, tests)]


def _case(node: str) -> str:
    """How pytest's report names a node `dir/file.py::Class::test`: its module and classes
    dotted, then `::` and the test — `dir.file.Class::test`."""
    file, *parts = node.split("::")
    return ".".join([file.removesuffix(".py").replace("/", "."), *parts[:-1]]) + "::" + parts[-1]


def read(work: Path, nodes: list[str]) -> dict:
    """Exactly the named tests ran, once each, and passed — none skipped, missing or extra;
    ValueError, with the reason, otherwise."""
    path = Path(work) / FILE
    try:
        root = ET.parse(path).getroot()
    except FileNotFoundError:
        raise ValueError(f"pytest wrote no {path.name}") from None
    except ET.ParseError as exc:
        raise ValueError(f"{path.name} does not parse: {exc}") from None
    observed: Counter = Counter()
    for suite in (list(root) if root.tag == "testsuites" else [root]):
        for case in suite.iter("testcase"):
            bad = next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None), None)
            if bad:
                raise ValueError(f"{case.get('classname')}::{case.get('name')}: {bad}")
            observed[f"{case.get('classname')}::{case.get('name')}"] += 1
    expected = Counter(_case(n) for n in relative_nodes(nodes)[1])
    if observed != expected:
        raise ValueError(f"the report holds {dict(observed)}, not the named tests {dict(expected)}")
    return {"tests": len(nodes), "passed": sum(observed.values())}
