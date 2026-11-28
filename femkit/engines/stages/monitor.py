"""The monitor beside every run (jobs.md § 4.3), the earlier tool's, copied: started by the run
script on the environment's own python, at nice 19, watching the run script's own process; it
observes, and never decides.

    python monitor.py --watch-pid PID --cores N [--gpus N] [--in-job] [--interval S]
                      --log RUN_LOG --writes MONITOR_LOG --util UTIL_CSV --ended ENDED --checked CHECKED

A program run in a job (framework.md § 1): the standard library, and `process` beside it, only —
it is the instrument that reports a failure, so it must load where the environment's own packages
do not. Every name it reads or writes is given by the run script, which the catalogue of a run's
files names them for (jobs.md § 1.1). femkit's control process imports it as
`femkit.engines.stages.monitor` for the words of its closing record and the job's clock's
variables, defined here once; it imports `process` only where it starts one, beside it in a run.

It wakes every 10 seconds, reads what the run's log gained, and samples what the run uses against
what the job holds, never the node: inside a scheduler's job (`--in-job`), the job's own control
group and the cores its affinity mask holds; a run here, the run script's process tree and the
cores the run uses (`--cores`). It writes `monitor.log`, one line per record — `[MACHINE]`,
`[MONITOR] start`, `[STATUS]` when the log grew, `[WALL]` once when the wall cannot be counted,
then the closing `[MONITOR] job ended`, `[STATUS]` with the run's records as they stand,
`[UTIL-SUMMARY]` and `[UTIL-BASIS]` — and `util.csv`, a row when a reading moved by a tenth of its
last or 300 seconds passed. It stops on SIGTERM, or when the watched process is gone. Its start,
and any error loading it, go to its standard error, which the run script appends to the run's log.
"""

import argparse
import json
import os
import signal
import socket
import sys
import time
from datetime import datetime, timezone

INTERVAL = 10.0    # seconds between two wakes
KEEPALIVE = 300.0  # a util.csv row at least this often
MOVED = 0.1        # a reading moved: by this fraction of its last written value
STOPS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
CLOSED = "[MONITOR] job ended"   # its closing record, which the run's state reads (jobs.md § 5.2)
#: The job's start in epoch seconds, and its wall in seconds counted from it, as the run script and
#: its walk export them (jobs.md § 4, blocks 4 and 10).
JOB_STARTED = "FEMKIT_JOB_STARTED"
WALL = "FEMKIT_WALL_S"
LAST_LINE = 200                  # characters of the log's last line a [STATUS] quotes
GPU_QUERY = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]


class Stopped(Exception):
    """A signal that stops the monitor, by its name."""


def now() -> str:
    """A moment as femkit writes one: UTC, ISO 8601, to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def human(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m {s % 60:02d}s"


class Log:
    """`monitor.log`: one line per record, `[<time>] [<TAG>] …`, each flushed as it is written."""

    def __init__(self, path: str) -> None:
        self.file = open(path, "a", encoding="utf-8")

    def say(self, tag: str, text: str) -> None:
        self.file.write(f"[{now()}] [{tag}] {text}\n")
        self.file.flush()


# ------------------------------------------------------------------ what the job holds, and uses

def _stat(pid: int) -> list[str] | None:
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rpartition(")")[2].split()
    except OSError:
        return None


def tree(root: int, leave_out: int) -> list[int]:
    """The process ``root`` and every descendant of it now, but ``leave_out`` — the monitor."""
    children: dict[int, list[int]] = {}
    for entry in os.scandir("/proc"):
        if entry.name.isdigit() and (fields := _stat(int(entry.name))) is not None:
            children.setdefault(int(fields[1]), []).append(int(entry.name))
    found, todo = [], [root]
    while todo:
        pid = todo.pop()
        if pid == leave_out:
            continue
        found.append(pid)
        todo += children.get(pid, [])
    return found


def cpu_of(pids: list[int]) -> float:
    """The CPU time the processes have used, with their reaped children's, in seconds."""
    total = 0
    for pid in pids:
        fields = _stat(pid)
        if fields is not None:
            total += sum(int(fields[i]) for i in (11, 12, 13, 14))   # utime, stime, cutime, cstime
    return total / os.sysconf("SC_CLK_TCK")


def pss_of(pids: list[int]) -> float:
    """The memory the processes use, each page shared among them counted once (PSS), in bytes."""
    total = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/smaps_rollup") as fh:
                for line in fh:
                    if line.startswith("Pss:"):
                        total += int(line.split()[1]) * 1024
                        break
        except OSError:
            pass
    return float(total)


def cgroup() -> str | None:
    """This process's control group's folder, on the unified hierarchy; None where there is none."""
    try:
        with open("/proc/self/cgroup") as fh:
            for line in fh:
                if line.startswith("0::"):
                    folder = "/sys/fs/cgroup" + line.strip()[3:]
                    return folder if os.path.isfile(os.path.join(folder, "cpu.stat")) else None
    except OSError:
        pass
    return None


def read_number(path: str) -> float | None:
    try:
        with open(path) as fh:
            text = fh.read().strip()
    except OSError:
        return None
    return float(text) if text.isdigit() else None


class Basis:
    """What every percentage is a fraction of, fixed once, when the monitor starts (jobs.md § 4.3)."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.watch, self.me = args.watch_pid, os.getpid()
        self.group = cgroup() if args.in_job else None
        affinity = len(os.sched_getaffinity(0)) if args.in_job else None
        self.cores = affinity or args.cores
        self.cores_from = "the job's affinity mask" if affinity else "the cores the run uses, as the run script says"
        self.limit = read_number(os.path.join(self.group, "memory.max")) if self.group else None

    def cpu(self) -> float:
        if self.group:
            with open(os.path.join(self.group, "cpu.stat")) as fh:
                usage = next((line.split()[1] for line in fh if line.startswith("usage_usec")), "0")
            return int(usage) / 1e6
        return cpu_of(tree(self.watch, self.me))

    def memory(self) -> float:
        if self.group:
            return read_number(os.path.join(self.group, "memory.current")) or 0.0
        return pss_of(tree(self.watch, self.me))

    def said(self) -> str:
        where = f"the job's control group, {self.group}" if self.group else "the run script's process tree"
        limit = f"limit {self.limit / 2 ** 30:.1f} GB" if self.limit else "limit not stated"
        memory = "the control group's" if self.group else "proportional set size"
        return f"cpu% of {self.cores} core(s) [{self.cores_from}]; cpu time [{where}]; mem [{memory}]; {limit}"


# ------------------------------------------------------------------ the records

def machine(args: argparse.Namespace) -> str:
    """The node, its cores, memory and GPUs — the GPUs asked of the driver only for a run that asks
    for some: a CPU run on a GPU node holds none of them."""
    memory = "unknown"
    try:
        with open("/proc/meminfo") as fh:
            kb = next(int(line.split()[1]) for line in fh if line.startswith("MemTotal:"))
        memory = f"{kb / 2 ** 20:.1f}"
    except (OSError, StopIteration, ValueError):
        pass
    gpus = "not asked for"
    if args.gpus:
        import process     # beside it in the run: every process it starts goes through it
        found = process.run(GPU_QUERY, timeout=30)
        gpus = "; ".join(line.strip() for line in found.stdout.splitlines() if line.strip()) if found.ok \
            else f"unknown ({GPU_QUERY[0]} exit {found.returncode})"
    return f"node={socket.gethostname()} cores={os.cpu_count()} mem_gb={memory} gpus={gpus}"


def wall() -> tuple[float | None, str | None]:
    """When the job's wall falls, from `FEMKIT_JOB_STARTED` and `FEMKIT_WALL_S`; or why it cannot be
    counted. No wall stated: nothing to count, and nothing said."""
    stated, start = os.environ.get(WALL), os.environ.get(JOB_STARTED)
    if not stated:
        return None, None
    if not stated.isdigit():
        return None, f"{WALL} is {stated!r}, not a number of seconds"
    if not (start or "").isdigit():
        return None, f"{JOB_STARTED} is {start!r}, not the job's start in epoch seconds"
    return int(start) + int(stated), None


def left(falls: float | None) -> str:
    """What is left of the job's wall, as a [STATUS] line says it; nothing when none is counted."""
    return "" if falls is None else f" | time limit: {human(max(0.0, falls - time.time()))} left"


def records(args: argparse.Namespace) -> str:
    """The run's records as they stand: how the command ended, and the check's verdict — never a
    state of the monitor's own: the run's state is the run door's (jobs.md § 5.2)."""
    said = []
    for name, describe in ((args.ended, _ended), (args.checked, _checked)):
        try:
            with open(name, encoding="utf-8") as fh:
                said.append(describe(name, json.load(fh)))
        except FileNotFoundError:
            said.append(f"no {name}")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            said.append(f"{name} does not read: {exc}")
    return "; ".join(said)


def _ended(name: str, held: dict) -> str:
    return f"{name}: exit {held['status']}" + (f", {held['reason']}" if held.get("reason") else "")


def _checked(name: str, held: dict) -> str:
    return f"{name}: " + ("passed" if held["passed"] else f"did not hold, {held.get('reason')}")


def alive(pid: int, start: str | None) -> bool:
    """Whether the watched process runs still: the same ID and start time, never a zombie."""
    fields = _stat(pid)
    return fields is not None and fields[0] not in ("Z", "X") and fields[19] == start


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="monitor.py")
    parser.add_argument("--watch-pid", type=int, required=True)
    parser.add_argument("--cores", type=int, required=True)
    parser.add_argument("--gpus", type=int, default=0)
    parser.add_argument("--in-job", action="store_true")
    parser.add_argument("--interval", type=float, default=INTERVAL)
    for name in ("--log", "--writes", "--util", "--ended", "--checked"):
        parser.add_argument(name, required=True)
    args = parser.parse_args(argv)

    def stop(number, frame):
        raise Stopped(signal.Signals(number).name)

    for sig in STOPS:               # first: from here on a stop is answered with its closing lines
        signal.signal(sig, stop)
    closing, readings, log, basis, falls = None, [], None, None, None
    try:
        print(f"femkit: monitor: started, process {os.getpid()}", file=sys.stderr, flush=True)
        first = _stat(args.watch_pid)
        watched = first[19] if first else None     # its start time: a later process given its ID is not it
        basis = Basis(args)
        log = Log(args.writes)
        new = not os.path.exists(args.util)
        util = open(args.util, "a", encoding="utf-8")
        if new:
            util.write("epoch,iso,cpu_pct,mem_gb\n")
            util.flush()
        last_row: list = []                  # its time, cpu %, memory
        position = os.path.getsize(args.log) if os.path.exists(args.log) else 0
        falls, why = wall()
        log.say("MACHINE", machine(args))
        log.say("MONITOR", f"start (interval={args.interval:g}s watch_pid={args.watch_pid}) "
                           f"mem {basis.memory() / 2 ** 30:.3f} GB")
        if why:
            log.say("WALL", f"the wall cannot be counted: {why}")
        previous = (time.monotonic(), basis.cpu())
        while True:
            time.sleep(args.interval)
            if not alive(args.watch_pid, watched):
                closing = f"watched pid {args.watch_pid} gone"
                break
            t, cpu = time.monotonic(), basis.cpu()
            pct = 100 * (cpu - previous[1]) / max(1e-9, (t - previous[0]) * basis.cores)
            previous, mem = (t, cpu), basis.memory() / 2 ** 30
            readings.append(pct)
            moment = time.time()
            if not last_row or moment - last_row[0] >= KEEPALIVE or any(
                    abs(v - w) > MOVED * max(abs(w), 1e-9) for v, w in ((pct, last_row[1]), (mem, last_row[2]))):
                util.write(f"{int(moment)},{now()},{pct:.1f},{mem:.3f}\n")
                util.flush()
                last_row = [moment, pct, mem]
            size = os.path.getsize(args.log) if os.path.exists(args.log) else 0
            if size > position:
                with open(args.log, "rb") as fh:
                    fh.seek(position)
                    gained = fh.read().decode("utf-8", "replace").splitlines()
                position = size
                last = next((line for line in reversed(gained) if line.strip()), "")
                log.say("STATUS", f"the log gained {len(gained)} line(s), the last: {last[:LAST_LINE]}"
                                  f" | cpu {pct:.0f}% mem {mem:.3f} GB{left(falls)}")
    except Stopped as exc:
        closing = f"stopped by {exc}"
    for sig in STOPS:
        signal.signal(sig, signal.SIG_IGN)   # its closing lines are written whole
    if log is None:
        log = Log(args.writes)
    log.say("MONITOR", f"job ended ({closing})")
    log.say("STATUS", records(args) + left(falls))
    if readings:
        log.say("UTIL-SUMMARY", f"cpu mean={sum(readings) / len(readings):.0f}% "
                                f"({min(readings):.0f}-{max(readings):.0f})")
    else:
        log.say("UTIL-SUMMARY", "no reading: the run ended before the first wake")
    log.say("UTIL-BASIS", basis.said() if basis is not None else "no basis: stopped before it was read")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
