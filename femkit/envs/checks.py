"""The generic check runner (definitions.md § 5; envs.md § 5).

It runs a check inside its environment, hands the output to the check's
reader, compares the quantities with what the check expects, and judges the
agreement groups. It knows no engine: a reader that understands one engine's
output is that engine's, registered in its package.
"""

from __future__ import annotations

import json
import math
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import femkit.engines
from femkit.config import settings
from femkit.core import paths, process, text
from femkit.core.operations import Context, Plan, Step, run_steps
from femkit.core.persist import write_json
from femkit.core.schema import render
from femkit.definitions.models import GENERIC_READERS, Check, EnvironmentDefinition, Expectation
from femkit.engines import Output, cuda, reader, summary
from femkit.envs import layout, manager
from femkit.envs.manager import Manager, resolve
from femkit.envs.records import CheckOutcome, ChecksRecord

# The shared code that runs and judges checks: a change to it re-validates (envs.md § 2). The toolchain's
# program checks nothing, so it is not here: changing it must not mark every environment unchecked.
JUDGING = tuple(Path(f).resolve() for f in (__file__, femkit.engines.__file__, summary.__file__, cuda.__file__))
JUNIT = "junit.xml"
START_MARKER = ".femkit-check-start"


@dataclass(frozen=True)
class Runner:
    """Everything a check needs that is not in the check itself."""

    env: EnvironmentDefinition
    prefix: Path
    manager: Manager
    launcher: list[str] | None


def runner(ctx: Context, name: str) -> Runner:
    from femkit.envs.state import definition
    return Runner(env=definition(ctx, name), prefix=layout.prefix(ctx, name), manager=resolve(ctx),
                  launcher=settings.load(ctx).config.launch.mpi)


# ------------------------------------------------------------------ which checks

def selected(env: EnvironmentDefinition, gpu: bool) -> list[Check]:
    """What the user asked for (envs.md § 5): without ``gpu``, the checks without device = true;
    with it, the device checks and every check sharing an agreement group with one, so each
    group can be judged. Nothing here asks what the machine has."""
    if not gpu:
        return [c for c in env.checks if not c.device]
    groups = {c.agree for c in env.checks if c.device and c.agree}
    return [c for c in env.checks if c.device or c.agree in groups]


def refusals(ctx: Context, env: EnvironmentDefinition, checks: list[Check]) -> None:
    """What makes the checks impossible to run, said before anything starts."""
    if any(c.kind == "command" and c.ranks > 1 for c in checks):
        settings.launcher(ctx, "a check runs on several MPI ranks")


def steps(checks: list[Check]) -> list[Step]:
    out = [Step(id=f"check:{c.id}", describe=_describe(c)) for c in checks]
    out.append(Step(id="record", describe="judge the agreement groups and write the check results"))
    return out


def _describe(c: Check) -> str:
    what = {"command": lambda: " ".join(c.run or []), "ctest": lambda: f"ctest {c.test} ({c.build})",
            "pytest": lambda: f"pytest {text.count(len(c.tests), 'upstream test')} ({c.source})"}[c.kind]()
    where = f"{text.count(c.ranks, 'rank')} x {text.count(c.threads, 'thread')}"
    return f"check {c.id}: {what}; {where}" + ("; needs a GPU" if c.device else "")


# ------------------------------------------------------------------ running one check

def _variables(r: Runner, check: Check) -> dict[str, str]:
    """The confined variables with the checkout (envs.md § 4.4), and the declared thread and
    fixed variables."""
    variables = manager.confined(r.manager.environment, checkout=True)
    variables.update({v: str(check.threads) for v in r.env.thread_variables})
    variables.update(r.env.fixed_variables)
    return variables


def _ctest_dir(r: Runner, check: Check) -> Path:
    """The test's working directory, from CTest's own listing; it must lie inside the build tree."""
    build = layout.build_dir(r.prefix, check.build)
    listing = process.run(r.manager.in_prefix(r.prefix, [
        "ctest", "--test-dir", str(build), "--show-only=json-v1", "--tests-regex", f"^{re.escape(check.test)}$"]),
        env=manager.confined(r.manager.environment), timeout=120)
    if not listing.ok:
        raise ValueError(f"ctest could not list {check.test}: {listing.stderr.strip() or listing.stdout.strip()}")
    try:
        tests = [t for t in json.loads(listing.stdout)["tests"] if t.get("name") == check.test]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"ctest's listing does not load: {exc}") from None
    if len(tests) != 1:
        raise ValueError(f"ctest lists {check.test} {text.count(len(tests), 'time')} in {build}")
    props = {p.get("name"): p.get("value") for p in tests[0].get("properties", []) if isinstance(p, dict)}
    where = Path(props.get("WORKING_DIRECTORY") or build)
    where = (where if where.is_absolute() else build / where).resolve()
    if not paths.inside(where, build) or not where.is_dir():
        raise ValueError(f"{check.test}'s working directory {where} is not inside {build}")
    return where


def relative_nodes(tests: list[str]) -> tuple[PurePosixPath, list[str]]:
    """The deepest folder holding every named test, and the node IDs relative to it — the
    root pytest runs from, as the upstream suite's own runner does."""
    files = [PurePosixPath(node.split("::", 1)[0]) for node in tests]
    root = PurePosixPath(*_common_parts([f.parent.parts for f in files]))
    return root, [str(f.relative_to(root)) + "::" + node.split("::", 1)[1] for f, node in zip(files, tests)]


def _pytest_root(r: Runner, check: Check) -> tuple[Path, list[str]]:
    root, nodes = relative_nodes(check.tests)
    return layout.source_dir(r.prefix, r.env, check.source) / root, nodes


def _common_parts(parts: list[tuple[str, ...]]) -> tuple[str, ...]:
    common: list[str] = []
    for column in zip(*parts):
        if len(set(column)) != 1:
            break
        common.append(column[0])
    return tuple(common)


def _argv(r: Runner, check: Check, work: Path, test_dir: Path | None) -> list[str]:
    if check.kind == "command":
        values = {"prefix": str(r.prefix), "work": str(work), "ranks": str(check.ranks), "threads": str(check.threads)}
        argv = [render(a, values) for a in check.run]
        if check.ranks > 1:
            argv = [render(a, {"ranks": str(check.ranks)}) for a in r.launcher] + argv
        return argv
    if check.kind == "ctest":
        build = layout.build_dir(r.prefix, check.build)
        return ["ctest", "--test-dir", str(build), "--output-on-failure", "--no-tests=error",
                "--tests-regex", f"^{re.escape(check.test)}$"]
    root, nodes = _pytest_root(r, check)
    return ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", *[a for p in check.plugins for a in ("-p", p)],
            "--import-mode=importlib",
            "-o", "addopts=", "-o", "junit_family=xunit2", "--rootdir", str(root), "--confcutdir", str(root),
            "--junitxml", str(work / JUNIT), *[str(root / n) for n in nodes]]


def run_check(r: Runner, check: Check, work: Path) -> CheckOutcome:
    """Run one check as asked and judge it: passed, or failed with the reason. A device check
    where no GPU is allocated runs too, and its own failure says so (envs.md § 5)."""
    work.mkdir(parents=True, exist_ok=True)
    log = work / "check.log"

    def failed(reason: str) -> CheckOutcome:
        return CheckOutcome(id=check.id, outcome="failed", reason=reason, log=str(log))

    started = time.time()
    try:
        test_dir = _ctest_dir(r, check) if check.kind == "ctest" else None
    except ValueError as exc:
        return failed(str(exc))
    if test_dir is not None:  # its outputs are dated by the file system holding them: start by that clock
        marker = test_dir / START_MARKER
        marker.touch()
        started = marker.stat().st_mtime
    variables = _variables(r, check)
    if check.kind == "pytest":  # the upstream tests alone: no plugin installed in the prefix loads by itself
        variables.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
    result = process.run(r.manager.in_prefix(r.prefix, _argv(r, check, work, test_dir)),
                         env=variables, cwd=work, timeout=check.timeout, log=log)
    if result.timed_out:
        return failed(f"stopped after {check.timeout} s")
    if not result.ok and check.upstream_verdict:  # set aside, only the check's expectations judge it
        return failed(f"exited with {result.returncode}")
    output = Output(work=work, log=log, test_dir=test_dir, started=started, ranks=check.ranks, threads=check.threads,
                    version=r.env.version, upstream_verdict=check.upstream_verdict)
    try:
        quantities = read(r.env.engine, check, output)
    except ValueError as exc:
        return failed(str(exc))
    problems = judge(check.expect, quantities)
    return CheckOutcome(id=check.id, outcome="failed" if problems else "passed", quantities=quantities,
                        reason="; ".join(problems), log=str(log))


# ------------------------------------------------------------------ readers

def read(engine: str, check: Check, output: Output) -> dict:
    if check.read in GENERIC:
        return GENERIC[check.read](check, output, engine)
    return reader(engine, check.read)(output)


GENERIC = {
    "summary": lambda check, output, engine: summary.read(output.work, engine, output.version),
    "junit": lambda check, output, engine: read_junit(output.work / JUNIT, check.tests),
}
if set(GENERIC) != GENERIC_READERS:  # the declared IDs and the runner's readers are one list
    raise ImportError(f"the runner reads {sorted(GENERIC)}; the definitions declare {sorted(GENERIC_READERS)}")


def read_junit(path: Path, nodes: list[str]) -> dict:
    """Exactly the named tests ran, once each, and passed — none skipped, missing or extra."""
    try:
        root = ET.parse(path).getroot()
    except FileNotFoundError:
        raise ValueError(f"pytest wrote no {path.name}") from None
    except ET.ParseError as exc:
        raise ValueError(f"{path.name} does not parse: {exc}") from None
    suites = list(root) if root.tag == "testsuites" else [root]
    observed: Counter = Counter()
    for suite in suites:
        for case in suite.iter("testcase"):
            bad = next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None), None)
            if bad:
                raise ValueError(f"{case.get('classname')}::{case.get('name')}: {bad}")
            observed[f"{case.get('classname')}::{case.get('name')}"] += 1
    _, relative = relative_nodes(nodes)
    expected = Counter(f"{n.split('::', 1)[0].removesuffix('.py').replace('/', '.')}::{n.split('::', 1)[1]}"
                       for n in relative)
    if observed != expected:
        raise ValueError(f"the report holds {dict(observed)}, not the named tests {dict(expected)}")
    return {"tests": len(nodes), "passed": sum(observed.values())}


# ------------------------------------------------------------------ judging

def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def judge(expect: dict[str, Expectation], quantities: dict) -> list[str]:
    """Every expectation the quantities break, in words; a missing quantity breaks it (definitions.md § 5.2)."""
    problems = []
    for name, e in expect.items():
        if name not in quantities:
            problems.append(f"{name}: the reader did not produce it")
            continue
        value = quantities[name]
        if e.equals is not None and value != e.equals:
            problems.append(f"{name} = {value}, expected {e.equals}")
        if e.min is not None and not (_is_number(value) and value >= e.min):
            problems.append(f"{name} = {value}, expected at least {e.min}")
        if e.max is not None and not (_is_number(value) and value <= e.max):
            problems.append(f"{name} = {value}, expected at most {e.max}")
    return problems


def _difference(a, b) -> float | None:
    """The largest relative difference, element-wise for lists; None when they cannot be compared."""
    a, b = (a if isinstance(a, list) else [a]), (b if isinstance(b, list) else [b])
    if len(a) != len(b) or not all(_is_number(v) for v in a + b):
        return None
    return max(abs(x - y) / max(abs(x), abs(y), 1e-300) for x, y in zip(a, b))


def agree(env: EnvironmentDefinition, outcomes: dict[str, CheckOutcome]) -> dict[str, CheckOutcome]:
    """Judge each agreement group among the checks in ``outcomes`` (definitions.md § 5.2).

    A group is judged when every member passed. A disagreement fails the group's device
    members when it has any — the CPU path is the reference — and every member otherwise.
    When a member without device = true did not pass, the device members fail too: their
    reference is gone.
    """
    out = dict(outcomes)
    for group, rule in env.agreements.items():
        members = [c for c in env.checks if c.agree == group and c.id in out]
        if len(members) < 2:
            continue
        devices = [c for c in members if c.device]
        references = [c for c in members if not c.device]
        lost = [c.id for c in references if out[c.id].outcome != "passed"]
        if lost:
            for c in devices:
                if out[c.id].outcome == "passed":
                    out[c.id] = out[c.id].model_copy(update={
                        "outcome": "failed", "reason": f"its reference {', '.join(lost)} in {group} did not pass"})
            continue
        if any(out[c.id].outcome != "passed" for c in members):
            continue
        values = [out[c.id].quantities.get(rule.quantity) for c in members]
        worst = 0.0
        for i, a in enumerate(values):  # every pair: each member agrees with every other
            for b in values[i + 1:]:
                d = _difference(a, b)
                worst = math.inf if d is None else max(worst, d)
        if worst > rule.rtol:
            reason = (f"{rule.quantity} disagrees across {group}: largest relative difference "
                      f"{worst:.3e} > {rule.rtol:g}" if math.isfinite(worst)
                      else f"{rule.quantity} cannot be compared across {group}")
            for c in devices or members:
                out[c.id] = out[c.id].model_copy(update={"outcome": "failed", "reason": reason})
    return out


# ------------------------------------------------------------------ one validation

def run_validation(ctx: Context, name: str, gpu: bool, plan_steps: tuple[Step, ...], observer
                   ) -> tuple[str, Path, list[CheckOutcome]]:
    """Run the planned checks as their own operation (its own event log), then judge the
    agreement groups and write the check results (envs.md § 4.3, § 5).

    Every check runs, whatever the one before it gave, so the record covers them all: a
    check that fails is a finished step, its verdict in the results. The outcomes of the
    checks not run — the device checks for a plain validate, the others for ``gpu`` — are
    kept when they are for the current check fingerprint.
    The caller holds the environment's lock.
    """
    from femkit.envs.state import facts
    f = facts(ctx, name, holding_lock=True)
    r = runner(ctx, name)
    by_id = {c.id: c for c in r.env.checks}
    plan = Plan(operation="env.validate", request={"name": name, "gpu": gpu}, subjects=(layout.subject(name),),
                basis={"check_fingerprint": f.check_fingerprint}, steps=plan_steps)
    ran: dict[str, CheckOutcome] = {}
    recorded: list[CheckOutcome] = []

    def do(step: Step, where: Path):
        if step.id == "record":
            kept = {o.id: o for o in f.checks.outcomes} if (
                f.checks and f.checks.check_fingerprint == f.check_fingerprint) else {}
            kept.update(ran)  # judged together: a kept GPU outcome against a reference that ran again
            kept = agree(r.env, kept)
            recorded.extend(kept[c.id] for c in r.env.checks if c.id in kept)
            write_json(layout.checks_file(f.prefix), ChecksRecord(
                check_fingerprint=f.check_fingerprint, outcomes=recorded,
                time=ctx.now().isoformat(timespec="seconds")).model_dump())
            return "done", None
        check = by_id[step.id.split(":", 1)[1]]
        outcome = run_check(r, check, where / check.id)
        ran[check.id] = outcome
        observer.note(f"verdict: {outcome.outcome}" + (f" -- {outcome.reason}" if outcome.reason else ""))
        return "done", Path(outcome.log) if outcome.log else None

    status, where = run_steps(plan, ctx, observer, do)
    return status, where, recorded
