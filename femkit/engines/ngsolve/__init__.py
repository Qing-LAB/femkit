"""The NGSolve adapter: check programs and the hand-over of a mesh (`handover.py`, geometry.md § 8;
definitions.md § 1).

Its check programs write the common summary, and its version command prints the version as its
last line, so it registers no reader of its own.
"""

from __future__ import annotations

ENGINE = "ngsolve"

READERS: dict = {}
