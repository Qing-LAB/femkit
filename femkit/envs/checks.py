"""The generic check runner (definitions.md § 5; envs.md § 5).

It runs a check inside its environment, hands the output to the check's
reader, compares the quantities with what the check expects, and judges the
agreement groups. It knows no engine: a reader that understands one engine's
output is that engine's, registered in its package.
"""

from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from femkit.config import settings
from femkit.core import clock, dirs, paths, text
from femkit.core.operations import Context, Plan, Step, run_steps
from femkit.core import persist
from femkit.core.persist import write_json
from femkit.core.schema import render
from femkit.definitions.models import RUN_QUANTITIES, Check, EnvironmentDefinition, Expectation
from femkit.engines import Output, junit, reader
from femkit.envs import layout
from femkit.envs.inside import Inside, entered
from femkit.envs.records import CheckOutcome, ChecksRecord
from femkit.envs.requests import ENV_VALIDATE, ValidateRequest

START_MARKER = ".femkit-check-start"


@dataclass(frozen=True)
class Runner:
    """Everything a check needs that is not in the check itself: the environment it runs in,
    entered through the one door (envs.md § 4.4)."""

    name: str
    env: EnvironmentDefinition
    inside: Inside
    launcher: list[str] | None

    @property
    def prefix(self) -> Path:
        """Its prefix as the manager lists it, or — in a plan made before the environment exists —
        `<prefix of femkit-NAME>`, which each check runs with the listed one in place of (envs.md § 4.1)."""
        return self.inside.prefix or layout.unmade(self.inside.managed)


def runner(ctx: Context, name: str) -> Runner:
    from femkit.envs.state import definition
    return Runner(name=name, env=definition(ctx, name), inside=entered(ctx, name),
                  launcher=settings.load(ctx).config.launch.mpi)


# ------------------------------------------------------------------ what decides a verdict

def code(env: EnvironmentDefinition) -> dict[str, str]:
    """Every file of the code that decides the checks' verdicts, by its path from the checkout,
    with its SHA-256 (envs.md § 2): this runner, which runs and judges them; what each check
    runs — for `python -m <module>`, every file of that module's package, as the checkout holds
    it; and the module of each reader they name. Nothing else: no other file changes a verdict."""
    root = dirs.checkout()
    files = {Path(__file__).resolve()}
    for c in env.checks:
        if c.run and len(c.run) > 2 and c.run[1] == "-m":   # the interpreter's own `-m <module>`
            files |= _package(root, c.run[2])
        files.add(Path(sys.modules[reader(env.engine, c.read).__module__].__file__).resolve())
    return {str(path.relative_to(root)): persist.sha256(path) for path in sorted(files)}


def _package(root: Path, module: str) -> set[Path]:
    """Every file of the package that holds ``module``, as the checkout holds it — the one place a
    check program is imported from inside an environment (definitions.md § 5.1); none for a
    module the checkout does not hold."""
    where = root.joinpath(*module.split("."))
    folder = where if (where / "__init__.py").is_file() else where.parent if where.with_suffix(".py").is_file() else None
    if folder is None:
        return set()
    return {p.resolve() for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


# ------------------------------------------------------------------ which checks

def selected(env: EnvironmentDefinition, gpu: bool) -> list[Check]:
    """What the user asked for (envs.md § 5): without ``gpu``, the checks without device = true;
    with it, the device checks and every check sharing an agreement group with one, so each
    group can be judged. Nothing here asks what the machine has."""
    if not gpu:
        return [c for c in env.checks if not c.device]
    groups = {c.agree for c in env.checks if c.device and c.agree}
    return [c for c in env.checks if c.device or c.agree in groups]


def refusals(ctx: Context, checks: list[Check]) -> None:
    """What makes the checks impossible to run, said before anything starts."""
    if any(c.kind == "command" and c.ranks > 1 for c in checks):
        settings.launcher(ctx, "a check runs on several MPI ranks")


WORK = "{work}"  # a check's own folder in its operation's: known when it runs, filled in then


def command(r: Runner, check: Check) -> tuple[str, ...]:
    """What a check runs — inside the environment, with the launcher when on several ranks — its
    own folder `{work}`, filled in when it runs."""
    return tuple(r.inside.argv(_argv(r, check, Path(WORK))))


def steps(r: Runner, checks: list[Check]) -> list[Step]:
    """Each check with the command it runs and the step that records the verdicts (envs.md § 5)."""
    out = [Step(id=f"check:{c.id}", describe=_describe(c), argv=command(r, c)) for c in checks]
    out.append(Step(id="record", describe="judge the agreement groups and write the check results"))
    return out


def _describe(c: Check) -> str:
    what = {"command": lambda: " ".join(c.run or []), "ctest": lambda: f"ctest {c.test} ({c.build})",
            "pytest": lambda: f"pytest {text.count(len(c.tests), 'upstream test')} ({c.source})"}[c.kind]()
    where = f"{text.count(c.ranks, 'rank')} x {text.count(c.threads, 'thread')}"
    return f"check {c.id}: {what}; {where}" + ("; needs a GPU" if c.device else "")


# ------------------------------------------------------------------ running one check

def _declared(r: Runner, check: Check) -> dict[str, str]:
    """What a check runs with beside the clean start and the checkout (envs.md § 4.4): its
    environment's declared thread and fixed variables."""
    return {**{v: str(check.threads) for v in r.env.thread_variables}, **r.env.fixed_variables}


def _ctest_dir(r: Runner, check: Check) -> Path:
    """The test's working directory, from CTest's own listing; it must lie inside the build tree."""
    build = layout.build_dir(r.prefix, check.build)
    listing = r.inside.run(r.inside.argv([
        "ctest", "--test-dir", str(build), "--show-only=json-v1", "--tests-regex", f"^{re.escape(check.test)}$"]),
        timeout=120)
    if not listing.ok:
        raise ValueError(f"ctest could not list {check.test}: {listing.stderr.strip() or listing.stdout.strip()}")
    try:
        tests = [t for t in persist.json_value(listing.stdout)["tests"] if t.get("name") == check.test]
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


def _pytest_root(r: Runner, check: Check) -> tuple[Path, list[str]]:
    root, nodes = junit.relative_nodes(check.tests)
    return layout.source_dir(r.prefix, r.env, check.source) / root, nodes


def _argv(r: Runner, check: Check, work: Path) -> list[str]:
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
            "--junitxml", str(work / junit.FILE), *[str(root / n) for n in nodes]]


def run_check(r: Runner, check: Check, argv: tuple[str, ...], work: Path) -> CheckOutcome:
    """Run one check — the command its step carries, in its folder ``work`` — and judge it:
    passed, or failed with the reason. A device check where no GPU is allocated runs too, and
    its own failure says so (envs.md § 5)."""
    persist.make_folder(work)
    log = work / "check.log"

    def failed(reason: str) -> CheckOutcome:
        return CheckOutcome(id=check.id, outcome="failed", reason=reason, log=str(log))

    try:
        outputs = _ctest_dir(r, check) if check.kind == "ctest" else work
    except ValueError as exc:
        return failed(str(exc))
    # What the check writes is dated by the file system holding it: its start is a marker's time there.
    marker = persist.touch(outputs / START_MARKER)
    started = marker.stat().st_mtime
    declared = _declared(r, check)
    if check.kind == "pytest":  # the upstream tests alone: no plugin installed in the prefix loads by itself
        declared.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
    result = r.inside.run([a.replace(WORK, str(work)) for a in argv], checkout=True, more=declared,
                          cwd=work, timeout=check.timeout, log=log)
    if result.timed_out:
        return failed(f"stopped after {check.timeout} s")
    if not result.ok and check.upstream_verdict:  # set aside, only the check's expectations judge it
        return failed(f"exited with {result.returncode}")

    def written(pattern: str) -> dict[str, bytes]:
        """What the check wrote in this run, read here for its reader: each file matching
        ``pattern`` where it writes, no older than its start (definitions.md § 5.3)."""
        found = sorted(p for p in outputs.glob(pattern) if p.is_file() and p.name != START_MARKER
                       and p.stat().st_mtime >= started)
        return {p.name: held for p in found if (held := persist.read_bytes(p)) is not None}

    output = Output(written=written, ranks=check.ranks, threads=check.threads, product=r.env.engine or r.name,
                    version=r.env.version, tests=tuple(check.tests), upstream_verdict=check.upstream_verdict)
    try:
        quantities = reader(r.env.engine, check.read)(output)
    except ValueError as exc:
        return failed(str(exc))
    problems = ran_as_asked(check, quantities) + judge(check.expect, quantities)
    return CheckOutcome(id=check.id, outcome="failed" if problems else "passed", quantities=quantities,
                        reason="; ".join(problems), log=str(log))


# ------------------------------------------------------------------ judging

def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def ran_as_asked(check: Check, quantities: dict) -> list[str]:
    """Every way the run the reader reports differs from the one the check asks for, in words
    (definitions.md § 5.2): the ranks and threads it reports must be the check's own, and a check
    on more than one must have them reported — its outcome proves what was asked ran
    (framework.md § 4)."""
    problems = []
    for name in RUN_QUANTITIES:
        asked, reported = getattr(check, name), quantities.get(name)
        if reported is None and asked > 1:
            problems.append(f"{name}: the reader did not report it; the check runs on {asked}")
        elif reported is not None and reported != asked:
            problems.append(f"{name} = {reported}, the check's own {asked}")
    return problems


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
    f = facts(ctx, name)
    r = runner(ctx, name)
    by_id = {c.id: c for c in r.env.checks}
    plan = Plan(operation=ENV_VALIDATE.name, request=ValidateRequest(name=name, gpu=gpu).model_dump(mode="json"),
                subjects=(layout.subject(name),),
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
                time=clock.stamp(ctx.now())).model_dump())
            return "done", None
        check = by_id[step.id.split(":", 1)[1]]   # with the prefix the manager lists now (envs.md § 4.1)
        outcome = run_check(r, check, command(r, check), where / check.id)
        ran[check.id] = outcome
        observer.note(f"verdict: {outcome.outcome}" + (f" -- {outcome.reason}" if outcome.reason else ""))
        return "done", Path(outcome.log) if outcome.log else None

    status, where = run_steps(plan, ctx, observer, do)
    return status, where, recorded
