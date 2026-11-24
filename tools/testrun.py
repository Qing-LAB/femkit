#!/usr/bin/env python
"""Run a test tier with a live progress log, and say what the log supports.

    python tools/testrun.py run basic                  # the default tier, over the cores
    <data>/environments/web/bin/python tools/testrun.py run web   # the web environment's own Python
    python tools/testrun.py run field                  # this machine's manager and scheduler
    python tools/testrun.py run engine                 # installed engines, on the person's word
    python tools/testrun.py run tests/basic/test_x.py  # a targeted set: batch `custom`
    python tools/testrun.py run lf                     # only the last run's failures
    python tools/testrun.py status [BATCH] [--fails]   # what each batch's log supports saying
    python tools/testrun.py failed BATCH               # failed test IDs, to pass back to pytest

The contract is docs/contracts/testing.md § 4. This file and its plugin use
the standard library and pytest only, and import nothing from femkit: the
instrument that reports femkit's failures must keep working when femkit is
broken.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRESS_DIR = os.path.join(REPO, ".test-progress")

TIERS = {"basic": "tests/basic", "web": "tests/web", "field": "tests/field", "engine": "tests/engine"}
ONE_PROCESS = {"field", "engine"}  # no two installs or calculations compete (§ 4.6)

#: A log silent this long belongs to a run that is not writing any more (§ 4.4).
SILENCE_LIMIT = 30 * 60

#: Batch states that are not a suite result (§ 4.4).
UNTRUSTED = {"unusable", "interleaved", "partial", "unexplained", "abandoned"}


# ------------------------------------------------------------------ the code

def code_now(repo: str | None = None) -> str | None:
    """Digest of every file git would keep — tracked, and untracked but not
    ignored — by name and bytes, a link by its target; None where git cannot
    list them. The person's git settings are left out (§ 4.5)."""
    repo = repo or REPO
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=repo, env=env, capture_output=True, timeout=60, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    digest = hashlib.sha256()
    for name in sorted(set(listed.split(b"\0")) - {b""}):
        path = os.path.join(repo, os.fsdecode(name))
        if os.path.islink(path):
            digest.update(name + b"\0" + os.fsencode(os.readlink(path)))
        elif os.path.isfile(path):
            digest.update(name + b"\0")
            with open(path, "rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------------ paths and the lock

def default_workers() -> int:
    """A quarter of the cores, at most 8 (§ 4.6)."""
    return min(8, max(1, (os.cpu_count() or 1) // 4))


def progress_path(batch: str, root: str = PROGRESS_DIR) -> str:
    return os.path.join(root, f"{batch}.jsonl")


def _lock_path(batch: str, root: str = PROGRESS_DIR) -> str:
    return os.path.join(root, f"{batch}.lock")


def acquire_batch_lock(batch: str, root: str = PROGRESS_DIR):
    """An exclusive flock for the batch, or None when another run holds it (§ 4.3).

    The kernel releases it however the process ends, so there is nothing stale
    to detect. The pid written inside only lets a refusal name the holder.
    """
    os.makedirs(root, exist_ok=True)
    fh = open(_lock_path(batch, root), "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def _lock_holder(batch: str, root: str = PROGRESS_DIR) -> int | None:
    try:
        text = open(_lock_path(batch, root)).read().strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ reading a log

def read_records(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # a half-written last line during a live read
    return out


def _writer_is_alive(start: dict, path: str, now: float) -> bool:
    """A missing process settles it; a live pid does not (pids are reused), so
    the log's own clock decides (§ 4.4)."""
    pid = start.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            pass
    try:
        return now - os.path.getmtime(path) < SILENCE_LIMIT
    except OSError:
        return False


def summarise(batch: str, path: str, now: float | None = None) -> dict:
    """What the log's last generation supports saying: one closed table (§ 4.4)."""
    now = time.time() if now is None else now
    records = read_records(path)
    if not records:
        return {"batch": batch, "state": "no-data", "path": path}
    starts = [i for i, r in enumerate(records) if r.get("event") == "start"]
    if not starts:
        return {"batch": batch, "state": "unusable", "path": path,
                "why": "no `start` record: the log was cut under a writer; what is left is a fragment"}
    gen = records[starts[-1]:]
    run_id = gen[0].get("run")
    strays = {r.get("run") for r in gen} - {run_id}
    collected = next((r["n"] for r in gen if r.get("event") == "collected"), None)
    done = next((r for r in gen if r.get("event") == "done"), None)
    tests = [r for r in gen if r.get("event") == "test"]
    results = [r for r in gen if r.get("event") in ("test", "collect")]
    counts = Counter(r["outcome"] for r in results)
    # `ran` counts distinct tests, not records: a teardown failure or a crash
    # reported against a test that already has a record is not a second test.
    ran = len({r["nodeid"] for r in tests if not r["nodeid"].endswith(" [teardown]")})
    start_t = gen[0].get("time", 0)
    last_t = max((r.get("time", start_t) for r in gen), default=start_t)

    alive = not done and _writer_is_alive(gen[0], path, now)
    if collected is None and alive:
        state, why = "running", "collecting the tests"
    elif collected is None:
        state, why = "unusable", "no `collected` record: collection never finished, so there is no total"
    elif strays:
        state, why = "interleaved", f"records from {len(strays) + 1} runs share this generation"
    elif done and ran < collected:
        state, why = "partial", f"the run stopped after {ran} of {collected} tests (exit {done['exitstatus']})"
    elif done and done["exitstatus"] != 0 and counts["failed"] == 0:
        state, why = "unexplained", (
            f"pytest exited {done['exitstatus']} with no failure recorded: a canary, an internal or a "
            f"plugin error; read {os.path.splitext(path)[0]}.out")
    elif done:
        state, why = "done", None
    elif alive:
        state, why = "running", None
    else:
        state, why = "abandoned", f"no `done` record and the writer is gone after {ran} tests: a fragment"

    return {
        "batch": batch, "state": state, "why": why, "run": run_id, "path": path,
        "exitstatus": done["exitstatus"] if done else None,
        "collected": collected, "ran": ran,
        "passed": counts["passed"], "failed": counts["failed"],
        "skipped": counts["skipped"], "xfailed": counts["xfailed"],
        "not_run": Counter(r.get("reason") or "no reason given" for r in results
                           if r["outcome"] in ("skipped", "xfailed")),
        "elapsed": round(last_t - start_t, 1), "ran_at": start_t,
        "code": gen[0].get("code"), "asked": gen[0].get("asked") or [],
        "failed_ids": [(r["nodeid"], r.get("reason", "")) for r in results if r["outcome"] == "failed"],
    }


def code_verdict(summary: dict, code: str | None) -> str | None:
    """For a `done`: None when it is about this code; `other` or `unknown` otherwise (§ 4.5)."""
    if summary["state"] != "done":
        return None
    if summary["code"] is None or code is None:
        return "unknown"
    return "other" if summary["code"] != code else None


# ------------------------------------------------------------------ commands

def _inside(target: str, tier_dir: str) -> bool:
    path = os.path.normpath(os.path.join(REPO, target.split("::", 1)[0]))
    tier = os.path.normpath(os.path.join(REPO, tier_dir))
    return path == tier or path.startswith(tier + os.sep)


def _last_failed_names_a_file() -> bool:
    path = os.path.join(REPO, ".pytest_cache", "v", "cache", "lastfailed")
    try:
        with open(path) as fh:
            ids = json.load(fh)
    except (OSError, ValueError):
        return False
    return any(os.path.isfile(os.path.join(REPO, nid.split("::", 1)[0])) for nid in ids)


def select(batch: str, targets: list[str], workers: int) -> tuple[list[str], str, int]:
    """(pytest selection, batch name, workers) for what was asked (§ 4.3, § 4.6)."""
    if batch == "lf":
        return ["tests", "--last-failed", "--last-failed-no-failures", "none"], "lf", 1
    if batch in TIERS and not targets:
        return [TIERS[batch]], batch, 1 if batch in ONE_PROCESS else workers
    # A part of a tier, or any targeted set, is the batch `custom`, ordered by
    # directory so a subdirectory's conftest binds every file in it.
    sel = sorted(list(targets) if batch in TIERS else [batch, *targets], key=lambda s: (os.path.dirname(s), s))
    if any(_inside(s, TIERS[t]) for s in sel for t in ONE_PROCESS):
        workers = 1  # a part of field or engine is still one process
    return sel, "custom", workers


def cmd_run(args) -> int:
    if args.batch == "lf" and not _last_failed_names_a_file():
        print("[testrun] lf: the last-failed list names no test file here; nothing to rerun.")
        return 0
    sel, batch, workers = select(args.batch, args.targets, args.workers)
    if workers > 1 and importlib.util.find_spec("xdist") is None:
        print("[testrun] refused: spreading the run needs pytest-xdist; use --workers 1", file=sys.stderr)
        return 2

    lock = acquire_batch_lock(batch)
    if lock is None:
        holder = _lock_holder(batch)
        who = f" (pid {holder})" if holder else ""
        if not args.force:
            print(f"[testrun] refused: batch {batch!r} is already running{who}.", file=sys.stderr)
            print(f"[testrun]   watch it: python tools/testrun.py status {batch}", file=sys.stderr)
            return 2
        print(f"[testrun] --force: a second {batch} run alongside the one going{who}; "
              f"`status {batch}` will read interleaved.", file=sys.stderr)

    prog = progress_path(batch)
    cmd = [sys.executable, "-m", "pytest", *sel, "-p", "tools.progress_plugin",
           f"--progress-file={prog}", "-q", "-rfE", "--tb=short"]
    if workers > 1:
        cmd += ["-n", str(workers), "--dist", "loadgroup", "--max-worker-restart", "0"]
    print(f"[testrun] batch={batch} workers={workers} progress={prog}", flush=True)
    print("[testrun] " + " ".join(cmd), flush=True)
    out_path = os.path.splitext(prog)[0] + ".out"
    # The full console text of the run holding the lock (§ 4.2), and the terminal too.
    with open(out_path, "w") if lock is not None else open(os.devnull, "w") as out:
        proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            sys.stdout.write(line)
            out.write(line)
            out.flush()
        return proc.wait()


def _known_batches() -> list[str]:
    if not os.path.isdir(PROGRESS_DIR):
        return []
    return sorted(f[:-6] for f in os.listdir(PROGRESS_DIR) if f.endswith(".jsonl"))


def cmd_status(args) -> int:
    batches = [args.batch] if args.batch else _known_batches()
    if not batches:
        print("no progress logs under .test-progress/ yet")
        return 0
    code = code_now()
    untrusted = False
    for b in batches:
        s = summarise(b, progress_path(b))
        if s["state"] == "no-data":
            print(f"[{b}] no data")
            continue
        verdict = code_verdict(s, code)
        if s["state"] in UNTRUSTED or verdict:
            untrusted = True
        if s["state"] in UNTRUSTED:
            # no count is printed as a result for these states (§ 4.4)
            print(f"[{b}] {s['state'].upper()}: not a suite result")
            print(f"      {s['why']}")
        elif s["state"] == "running":
            print(f"[{b}] running | {s['ran']}/{s['collected']} so far, {s['failed']} failed | "
                  f"started {datetime.fromtimestamp(s['ran_at']):%Y-%m-%d %H:%M}")
        else:
            label = {"other": "done, ON OTHER CODE", "unknown": "done, ON UNKNOWN CODE"}.get(verdict, s["state"])
            exit_note = f" (exit {s['exitstatus']})" if s["exitstatus"] is not None else ""
            print(f"[{b}] {label}{exit_note} | {s['ran']}/{s['collected']} ran | pass {s['passed']}  "
                  f"FAIL {s['failed']}  skip {s['skipped']}  xfail {s['xfailed']} | {s['elapsed']}s | "
                  f"started {datetime.fromtimestamp(s['ran_at']):%Y-%m-%d %H:%M}")
            if s["why"]:
                print(f"      {s['why']}")
            if verdict == "other":
                print("      the checkout changed since this run: its numbers are not about this code")
            elif verdict == "unknown":
                print("      which code this run was of cannot be said")
            if b == "custom" and s["asked"]:
                print(f"      a part, not a tier: {' '.join(s['asked'][:6])}")
            for reason, n in s["not_run"].most_common():
                print(f"      skipped or expected to fail, {n}: {reason}")
        if args.fails:
            for nid, reason in s.get("failed_ids", []):
                print(f"    FAIL {nid}")
                if reason:
                    print(f"         -> {reason}")
    return 1 if untrusted else 0


def cmd_failed(args) -> int:
    for nid, _ in summarise(args.batch, progress_path(args.batch)).get("failed_ids", []):
        if not nid.endswith(" [teardown]"):
            print(nid)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="action", required=True)
    pr = sub.add_parser("run", help="run a tier or a targeted set with a live progress log")
    pr.add_argument("batch", help="basic | web | field | engine | lf | a test path")
    pr.add_argument("targets", nargs="*", help="more test paths (makes the batch `custom`)")
    pr.add_argument("--force", action="store_true", help="run even while this batch is running")
    pr.add_argument("--workers", type=int, default=default_workers(),
                    help="processes for `basic` (default: a quarter of the cores, at most 8)")
    pr.set_defaults(func=cmd_run)
    ps = sub.add_parser("status", help="what each batch's log supports saying")
    ps.add_argument("batch", nargs="?")
    ps.add_argument("--fails", action="store_true", help="list every failure, one line each")
    ps.set_defaults(func=cmd_status)
    pf = sub.add_parser("failed", help="failed test IDs, to pass back to pytest")
    pf.add_argument("batch")
    pf.set_defaults(func=cmd_failed)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
