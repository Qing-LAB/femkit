"""The one process runner (core.md § 8).

Every external command — manager, CMake, compiler, check, scheduler, engine, the web
server's child — starts here, as a `Child`: an argument vector, never a shell string; an
explicit environment and working directory; a session of its own, so the whole group it
makes is stopped together, by one escalation with one grace.

This module imports the standard library alone: a check program running inside an
environment imports it, and nothing else of femkit's (framework.md § 1). So it opens a
child's output file itself rather than through `persist`, whose TOML library the
environment does not hold.
"""

from __future__ import annotations

import os
import signal as signals
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Literal, Sequence

TAIL_LINES = 40   # a log's last lines, as every surface shows a step's or a server's (core.md § 8)
GRACE = 5.0       # seconds between SIGTERM and SIGKILL, for every process femkit stops
LOOK = 0.05       # seconds between two looks at a process being stopped
CHUNK = 65536     # bytes read at a time from a child's output
PIPE = "pipe"     # a child's output handed to the caller as it comes (`Child.chunks`)

# Fields of /proc/<pid>/stat, counted after the command's name, which may itself hold spaces.
STATE, GROUP, START = 0, 2, 19
ENDED = ("Z", "X")   # a zombie runs nothing: it only awaits its parent


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


# ------------------------------------------------------------ who a process is

def boot_id() -> str:
    """The kernel's ID for this boot: a process ID and start time name one process only within it."""
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def _stat(pid: int) -> list[str] | None:
    """The fields of the process's /proc/<pid>/stat after its command's name; None when there
    is no such process."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return stat.rpartition(")")[2].split()


def _owned(pid: int) -> bool:
    """The process runs as this account."""
    try:
        return Path(f"/proc/{pid}").stat().st_uid == os.getuid()
    except OSError:
        return False


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
    fields = _stat(pid) if _owned(pid) else None
    if fields is None or fields[STATE] in ENDED:
        return None
    return Identity(pid, int(fields[START]), boot_id())


# ------------------------------------------------------------ stopping

def _escalate(send: Callable[[int], None], running: Callable[[], bool], grace: float) -> None:
    """The one way femkit stops a process or a group: ``SIGTERM``, then ``SIGKILL`` once
    ``grace`` seconds have passed with any of it still running."""
    send(signals.SIGTERM)
    deadline = time.monotonic() + grace
    while running():
        if time.monotonic() >= deadline:
            send(signals.SIGKILL)
            return
        time.sleep(LOOK)


def _signal_group(group: int, sig: int) -> None:
    try:
        os.killpg(group, sig)
    except (ProcessLookupError, PermissionError):  # none of it left, or none of it this account's
        pass


def _member_runs(pid: int, group: int) -> bool:
    fields = _stat(pid)
    return fields is not None and fields[STATE] not in ENDED and int(fields[GROUP]) == group and _owned(pid)


def _group_runs(group: int) -> bool:
    """A process of this account's in the process group ``group`` has not ended: its leader,
    looked at first, or any other — a command's children outlive it unless stopped too."""
    if _member_runs(group, group):
        return True
    return any(_member_runs(int(entry.name), group) for entry in os.scandir("/proc") if entry.name.isdigit())


def _fresh_output(path: Path) -> int:
    """``path`` opened for a child's output: emptied, so it holds this child's output alone —
    a reader parses it; readable by this account alone from its first byte, as what a
    command prints may name paths and settings; never through a link."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    if os.fstat(fd).st_mode & 0o077:
        os.fchmod(fd, 0o600)
    return fd


# ------------------------------------------------------------ the one block that owns a child

class Child:
    """A process femkit started, and owns until it is reaped (core.md § 8): in a session of
    its own, so stopping it reaches every process it made in its group — but a run waited on,
    kept in its starter's group, so Ctrl-C at its launch and a stop sent to a sequence's walk
    reach it; stdin closed; its output to a file, to the caller as it comes, or discarded."""

    def __init__(self, proc: subprocess.Popen, own_group: bool = True) -> None:
        self._proc = proc
        self._own_group = own_group
        fields = _stat(proc.pid)  # not reaped yet, so its entry is there even if it has ended already
        if fields is None:
            raise RuntimeError(f"process {proc.pid}, just started, has no entry in /proc")
        self.identity = Identity(proc.pid, int(fields[START]), boot_id())

    @classmethod
    def start(cls, argv: Sequence[str], *, env: dict[str, str] | None = None, cwd: Path | None = None,
              keep_fds: Sequence[int] = (), output: Path | Literal["pipe"] | None = None,
              own_group: bool = True) -> "Child":
        """Start ``argv``, keeping only ``keep_fds`` open beside the standard three. Its stdout
        and stderr together go to ``output``: a file, ``"pipe"`` for `chunks`, or nowhere. With
        ``own_group`` false it stays in this process's group and session: a run waited on."""
        if output is None or output == PIPE:
            return cls._spawn(argv, env, cwd, keep_fds, subprocess.PIPE if output == PIPE else subprocess.DEVNULL,
                              subprocess.STDOUT, own_group=own_group)
        fd = _fresh_output(Path(output))
        try:
            return cls._spawn(argv, env, cwd, keep_fds, fd, subprocess.STDOUT, own_group=own_group)
        finally:
            os.close(fd)  # the child holds its own copy

    @classmethod
    def _spawn(cls, argv: Sequence[str], env, cwd, keep_fds: Sequence[int], stdout, stderr,
               text: bool = False, own_group: bool = True) -> "Child":
        """The one place a process starts."""
        return cls(subprocess.Popen(
            [str(a) for a in argv], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            env=dict(os.environ if env is None else env), cwd=cwd, start_new_session=own_group,
            pass_fds=tuple(keep_fds), **({"text": True, "errors": "replace"} if text else {})), own_group)

    def chunks(self) -> Iterator[bytes]:
        """Its output as it comes, until it closes it; started with ``output="pipe"``."""
        out = self._proc.stdout
        if out is None:
            raise ValueError("its output is not piped to the caller: start it with output='pipe'")
        with out:
            while chunk := out.read1(CHUNK):
                yield chunk

    def _captured(self, timeout: float | None) -> tuple:
        """Its stdout and stderr, each whole, once it has ended — what `run` keeps when it has no
        log; `subprocess.TimeoutExpired` when ``timeout`` seconds pass first."""
        return self._proc.communicate(timeout=timeout)

    def poll(self) -> int | None:
        """Its exit status — a signal's number negated — or None while it runs."""
        return self._proc.poll()

    def wait(self, timeout: float | None = None) -> int | None:
        """Its exit status once it ends; None when ``timeout`` seconds pass first."""
        try:
            return self._proc.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def stop(self, grace: float = GRACE) -> int:
        """``SIGTERM`` to its whole process group, ``SIGKILL`` to what of it still runs after
        ``grace`` seconds; its exit status. Its group is signalled only while it is not reaped:
        till then its ID cannot name another process's group. A child kept in its starter's
        group leads none: it is stopped alone, by the same escalation (core.md § 8)."""
        if self._proc.returncode is None:
            if self._own_group:
                group = self.identity.pid
                _escalate(lambda sig: _signal_group(group, sig), lambda: _group_runs(group), grace)
            else:
                _escalate(self._proc.send_signal, lambda: self._proc.poll() is None, grace)
        return self._proc.wait()


def run(
    argv: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: float | None = None,
    log: Path | None = None,
) -> ProcessResult:
    """Run ``argv`` to completion: a `Child` waited for. A timeout or an interrupt stops it.

    With ``log``, stdout and stderr go together to that file and the result keeps a bounded
    tail; without it, both are captured whole and apart (for the short answers a probe reads).
    """
    argv = tuple(str(a) for a in argv)
    child = Child.start(argv, env=env, cwd=cwd, output=log) if log is not None else \
        Child._spawn(argv, env, cwd, (), subprocess.PIPE, subprocess.PIPE, text=True)
    timed_out = False
    try:
        out, err = child._captured(timeout)
    except subprocess.TimeoutExpired:
        child.stop()
        out, err = child._captured(None)  # what it wrote before it stopped
        timed_out = True
    except BaseException:  # an interrupt: the command does not outlive femkit
        child.stop()
        raise
    code = None if timed_out else child.poll()
    if log is not None:
        return ProcessResult(argv, code, "\n".join(tail(log, TAIL_LINES)), "", log, timed_out)
    return ProcessResult(argv, code, out, err, None, timed_out)


# ------------------------------------------------------------ processes not waited for

_unreaped: list[Child] = []  # started detached and not yet reaped: an ended one is collected at the next start


def start_detached(
    argv: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    keep_fds: Sequence[int] = (),
    log: Path | None = None,
) -> Identity:
    """A `Child` not waited for: started in a session of its own, its output to ``log`` or
    discarded, keeping only ``keep_fds`` open beside the standard three; reaped later."""
    child = Child.start(argv, env=env, cwd=cwd, keep_fds=keep_fds, output=log)
    _unreaped[:] = [c for c in _unreaped if c.poll() is None] + [child]
    return child.identity


def _leads_its_group(identity: Identity) -> None:
    """Refuse a group named through a process that does not lead it (core.md § 8)."""
    fields = _stat(identity.pid)
    if fields is None or int(fields[GROUP]) != identity.pid:
        raise ValueError(f"process {identity.pid} leads no process group: only a group's leader names it")


def end(identity: Identity, *, grace: float = GRACE, group: bool = False) -> bool:
    """Stop a process this command did not start that femkit stops itself — a web server started
    earlier — by the one escalation: to it alone, or with ``group`` to the process group it
    leads. Only while it is ``identity``; False when it was not running."""
    if not identity.alive():
        return False
    if group:
        _leads_its_group(identity)
        _escalate(lambda sig: _signal_group(identity.pid, sig), lambda: _group_runs(identity.pid), grace)
        return True

    def send(sig: int) -> None:
        if identity.alive():
            try:
                os.kill(identity.pid, sig)
            except ProcessLookupError:
                pass

    _escalate(send, identity.alive, grace)
    return True


def signal(identity: Identity, sig: int, *, group: bool = False) -> bool:
    """One signal, never escalated, to a process this command did not start — a run launched
    earlier, which its own handler ends (core.md § 8; jobs.md § 5.4): to it alone, or with
    ``group`` to the process group it leads. Only while it is ``identity``; False when it was not
    running."""
    if not identity.alive():
        return False
    if group:
        _leads_its_group(identity)
        _signal_group(identity.pid, sig)
        return True
    try:
        os.kill(identity.pid, sig)
    except ProcessLookupError:
        return False
    return True
