"""The one process runner (core.md § 8).

Every external command — manager, CMake, compiler, check, scheduler, engine —
starts here: an argument vector, never a shell string; an explicit environment
and working directory; an optional timeout that stops the whole process group.
"""

from __future__ import annotations

import os
import signal
import subprocess
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
