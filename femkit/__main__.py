"""femkit's entry: `python -m femkit`, or this file run by its path, as the `femkit` command runs
it, isolated (envs.md § 7) — then the checkout that holds it is put on femkit's own import path
here, and never exported to a process femkit starts."""

import sys
from pathlib import Path

if not __package__:   # run by its path, not as `-m femkit`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from femkit.cli import main  # noqa: E402 — after the path above

main()
