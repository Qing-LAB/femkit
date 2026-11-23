"""The one process runner (core.md § 8).

Every external command — manager, CMake, compiler, check, scheduler, engine —
starts here: an argument vector, never a shell string; an explicit environment
and working directory; an optional timeout that stops the whole process group.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

TAIL_LINES = 40


@dataclass(frozen=True)
class ProcessResult:
    argv: tuple[str, ...]
    returncode: int | None  # None: it did not finish (timeout or interrupt)
    stdout: str  # the whole stdout when captured; the tail of the log otherwise
    stderr: str
    log: Path | None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _stop_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


TAIL_BLOCK = 65536  # bytes read at a time from a file's end


def tail(path: Path, lines: int) -> list[str]:
    """The last ``lines`` lines of ``path``, read from its end: a build log may be large."""
    with open(path, "rb") as fh:
        end = fh.seek(0, os.SEEK_END)
        start, data = end, b""
        while start > 0 and data.count(b"\n") <= lines:
            start = max(0, start - TAIL_BLOCK)
            fh.seek(start)
            data = fh.read(end - start)
    return data.decode("utf-8", errors="replace").splitlines()[-lines:]


def run(
    argv: list[str] | tuple[str, ...],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: float | None = None,
    log: Path | None = None,
) -> ProcessResult:
    """Run ``argv`` to completion.

    With ``log``, stdout and stderr go together to that file and the result
    keeps a bounded tail; without it, both are captured whole (for the short
    answers a probe reads).
    """
    argv = tuple(str(a) for a in argv)
    environment = dict(os.environ if env is None else env)
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "w", encoding="utf-8") as out:
            proc = subprocess.Popen(
                argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                env=environment, cwd=cwd, start_new_session=True,
            )
            timed_out = _wait(proc, timeout)
        return ProcessResult(argv, None if timed_out else proc.returncode, "\n".join(tail(log, TAIL_LINES)), "", log,
                             timed_out)

    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        env=environment, cwd=cwd, start_new_session=True, text=True, errors="replace",
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop_group(proc)
        out, err = proc.communicate()
        return ProcessResult(argv, None, out, err, None, True)
    except BaseException:
        _stop_group(proc)
        raise
    return ProcessResult(argv, proc.returncode, out, err, None)


def _wait(proc: subprocess.Popen, timeout: float | None) -> bool:
    try:
        proc.wait(timeout=timeout)
        return False
    except subprocess.TimeoutExpired:
        _stop_group(proc)
        return True
    except BaseException:
        _stop_group(proc)
        raise


# ------------------------------------------------------------ detached processes

def boot_id() -> str:
    """The kernel's ID for this boot: a process ID and start time name one process only within it."""
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def _start_ticks(pid: int) -> int | None:
    """Its start time, or None when there is no such process or it has ended and only
    awaits its parent (a zombie runs nothing)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    fields = stat.rpartition(")")[2].split()  # the fields after the command name, from field 3
    return None if fields[0] in ("Z", "X") else int(fields[19])


@dataclass(frozen=True)
class Identity:
    """One process: its ID and start time on one boot (core.md § 8)."""

    pid: int
    start: int
    boot: str

    def alive(self) -> bool:
        """A process with this ID and start time runs now, on this boot, as this account."""
        return self.boot == boot_id() and identify(self.pid) == self

    def as_json(self) -> dict:
        return {"pid": self.pid, "start": self.start, "boot": self.boot}

    @classmethod
    def from_json(cls, data: dict) -> "Identity":
        return cls(int(data["pid"]), int(data["start"]), str(data["boot"]))


def identify(pid: int) -> Identity | None:
    """The process with this ID, when one of this account's runs; None otherwise."""
    try:
        if Path(f"/proc/{pid}").stat().st_uid != os.getuid():
            return None
    except OSError:
        return None
    start = _start_ticks(pid)
    return None if start is None else Identity(pid, start, boot_id())


def start_detached(
    argv: list[str] | tuple[str, ...],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    keep_fds: tuple[int, ...] = (),
    log: Path | None = None,
) -> Identity:
    """Start ``argv`` in a session of its own, stdin closed, its output to ``log`` or
    discarded, keeping only ``keep_fds`` open beside the standard three. Not waited for."""
    from femkit.core.persist import open_private
    out = open_private(log, "ab") if log is not None else subprocess.DEVNULL  # a log may hold what only its owner reads
    try:
        proc = subprocess.Popen(
            [str(a) for a in argv], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
            env=dict(os.environ if env is None else env), cwd=cwd, start_new_session=True,
            pass_fds=keep_fds,
        )
    finally:
        if log is not None:
            out.close()
    identity = identify(proc.pid)
    if identity is None:  # it ended before it could be read
        proc.wait()
        raise RuntimeError(f"{argv[0]} ended at once with exit code {proc.returncode}")
    _detached[:] = [p for p in _detached if p.poll() is None]  # reap those that ended
    _detached.append(proc)
    return identity


_detached: list[subprocess.Popen] = []  # started here and not yet reaped: an ended one is collected later


def end(identity: Identity, *, grace: float = 5.0) -> bool:
    """``SIGTERM``, then ``SIGKILL`` after ``grace`` seconds; only to a process that is
    ``identity``. False when it was not running."""
    if not identity.alive():
        return False
    os.kill(identity.pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not identity.alive():
            return True
        time.sleep(0.05)
    if identity.alive():
        os.kill(identity.pid, signal.SIGKILL)
    return True
