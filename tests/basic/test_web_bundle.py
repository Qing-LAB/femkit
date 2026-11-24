"""The shipped web page (web.md § 3): built from its sources as they are."""

from __future__ import annotations

import json

from femkit.server.build import bundle_hashes, source_dir, sources_hash, static_dir


def test_the_shipped_bundle_is_built_from_the_sources_as_they_are():
    """Fails if a source of the page changed without `web build`, or a bundle file was edited,
    added or removed by hand: both hashes are recomputed here, without Node.js (web.md § 3)."""
    recorded = json.loads((static_dir() / "build.json").read_text())
    assert sources_hash(source_dir())["sha256"] == recorded["sources"]["sha256"], "run: python -m femkit web build"
    assert bundle_hashes(static_dir()) == recorded["bundle"]

