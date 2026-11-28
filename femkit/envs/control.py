"""The control environment's machine (envs.md § 7.2): its facts, read from its prefix — the one the
manager lists under its name, `femkit` (§ 1) — as the install script reads them, and their names for
`femkit/data/states/control.toml`, which `doctor` observes it by; and its `femkit` command (§ 7),
whose one source the install script fills, and the link that puts it on a shell's path.

The script runs before femkit can, so it holds the same rules in bash (`control_state`); a basic
test holds the two together.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from femkit.core import dirs, persist, states
from femkit.core.operations import Context
from femkit.core.schema import render
from femkit.definitions import catalogue
from femkit.envs import layout, start
from femkit.envs.manager import made, resolve

STAMP = "control.sha256"           # in the control prefix's records; written last by the install script
LAUNCHER = Path("bin") / dirs.COMMAND  # in the control prefix: the `femkit` command the install script writes (§ 7)
LAUNCHER_SOURCE = "launcher.sh"    # in femkit/data/: that command's one source, which the install script fills


def shell_word(value: str) -> str:
    """``value`` as one single-quoted shell word, each `'` in it written `'\\''`: as the install
    script quotes what it fills the launcher's text with."""
    return "'" + value.replace("'", "'\\''") + "'"


def launcher_text(ctx: Context, checkout: Path, python: Path) -> str:
    """The `femkit` command that runs femkit from ``checkout`` on ``python`` (envs.md § 7):
    femkit/data/launcher.sh with `{checkout}` and then `{python}` each replaced by a shell word, and
    `{start}` by what femkit's own process sheds of the shell, from process.toml's `femkit_sheds`
    (envs.md § 7) — as the install script fills it."""
    source = catalogue.shipped(catalogue.data_root() / LAUNCHER_SOURCE)
    own = "\n".join(start.own_lines(catalogue.process(ctx)))
    return render(source, {"checkout": shell_word(str(checkout)), "python": shell_word(str(python)), "start": own})


@dataclass(frozen=True)
class ControlFacts:
    """What is observed of the control environment (envs.md § 7.2), and its `femkit` command (§ 7)."""

    prefix: bool           # the manager lists the control environment, and its prefix is there
    environment: bool      # it holds conda-meta/
    python: bool           # its bin/python can be run
    stamp: str | None      # the stamp's text; None: no stamp
    digest: str | None     # the SHA-256 of channels.txt then control.txt, read beside a stamp
    launcher: bytes | None   # its `femkit` command's bytes (envs.md § 7); None: there is none
    ours: bytes            # the command the install script writes from this checkout for this prefix
    linked: bool           # `<bin>/femkit` is a link to its `femkit` command (§ 7)


BINDING = states.Binding("control", {
    "prefix": lambda f: f.prefix,
    "environment": lambda f: f.environment,
    "python": lambda f: f.python,
    "stamp": lambda f: f.stamp is not None,
    "stamp_matches": lambda f: f.stamp is not None and f.stamp.strip() == f.digest,
    "command": lambda f: f.launcher == f.ours,
    "linked": lambda f: f.linked,
}, values={"script": lambda f: shlex.quote(str(dirs.install_script()))}, reads=frozenset({"current"}))


def machine(ctx: Context) -> states.Machine:
    """The machine `femkit/data/states/control.toml` declares, bound to these facts (envs.md § 7.2)."""
    return catalogue.machine(ctx, BINDING)


def link() -> Path:
    """Where the link that puts `femkit` on a shell's path lies: `<bin>/femkit` (envs.md § 7)."""
    return dirs.bin_dir() / dirs.COMMAND


def prefix(ctx: Context) -> Path | None:
    """The control environment's prefix, as the manager lists it under its name (envs.md § 1); None
    where it lists none. Refused while no manager is named."""
    return resolve(ctx).prefix(catalogue.managed(ctx, dirs.CONTROL))


def facts(ctx: Context) -> ControlFacts:
    """The control environment's facts, read from the prefix the manager lists as the install script
    reads them."""
    where = prefix(ctx)
    if where is None:
        return ControlFacts(prefix=False, environment=False, python=False, stamp=None, digest=None, launcher=None,
                            ours=b"", linked=False)
    stamp = persist.read_text(layout.records(where) / STAMP)   # None: there is none
    held = link()
    return ControlFacts(prefix=where.exists(), environment=made(where, catalogue.managers(ctx)),
                        python=os.access(where / "bin" / "python", os.X_OK), stamp=stamp,
                        digest=catalogue.control_digest() if stamp is not None else None,
                        launcher=persist.read_bytes(where / LAUNCHER),
                        ours=launcher_text(ctx, dirs.checkout(), where / "bin" / "python").encode("utf-8", "surrogateescape"),
                        linked=held.is_symlink() and os.readlink(held) == str(where / LAUNCHER))


def observe(ctx: Context) -> tuple[ControlFacts, Enum]:
    """The control environment's facts, and its state by the machine's rules."""
    f = facts(ctx)
    return f, machine(ctx).observe(f)


def names_this_checkout(launcher: bytes) -> bool:
    """Whether a `femkit` command names this checkout, as the launcher's one `checkout=` line does
    (femkit/data/launcher.sh) — in whatever form the script wrote it then."""
    line = f"checkout={shell_word(str(dirs.checkout()))}\n".encode("utf-8", "surrogateescape")
    return line in launcher
