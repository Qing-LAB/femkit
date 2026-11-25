"""The shipped web page (web.md § 3): built from its sources as they are."""

from __future__ import annotations

import json

from tests.kit import hold, installed, planned, refused
from femkit.core.errors import Busy, PlanStale
from femkit.definitions.requests import DOCS_SUBJECT
from femkit.envs import layout
from femkit.server import build
from femkit.server.build import bundle_hashes, source_dir, sources_hash, static_dir


def test_the_shipped_bundle_is_built_from_the_sources_as_they_are():
    """Fails if a source of the page changed without `web build`, or a bundle file was edited,
    added or removed by hand: both hashes are recomputed here, without Node.js (web.md § 3)."""
    recorded = json.loads((static_dir() / "build.json").read_text())
    assert sources_hash(source_dir())["sha256"] == recorded["sources"]["sha256"], "run: femkit web build"
    assert bundle_hashes(static_dir()) == recorded["bundle"]



def test_a_build_waits_for_neither_the_web_environment_nor_the_generated_files_to_change(manager):
    """Fails if `web build` runs while `schema docs` writes the files it builds from, or while
    the web environment it builds with changes — either holding its lock alone: the bundle would
    be built from half-written sources, and build.json name others (web.md § 3, api.md § 3)."""
    installed(build.TOOL, outcomes=[])
    for subject in (layout.subject(build.TOOL), DOCS_SUBJECT):
        op, plan, c = planned("web.build")
        holder = hold(subject, "alone")
        try:
            with refused(Busy, "held", subject):
                op.apply(plan, c)
        finally:
            holder.stdin.close()
            holder.wait()


def test_a_build_refuses_its_plan_when_its_environment_changed_since(manager):
    """Fails if `web build` applies a plan made while the web environment was ready after it
    changed: its npm steps would run in what is no longer that environment (api.md § 3)."""
    f = installed(build.TOOL, outcomes=[])
    op, plan, c = planned("web.build")
    layout.manifest_file(f.prefix).unlink()                       # another shell, meanwhile
    with refused(PlanStale, "basis-changed"):
        op.apply(plan, c)
