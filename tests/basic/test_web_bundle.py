"""The shipped web page (api.md § 5.3, § 5.5): built from its sources as they are, and holding
nothing the page's content-security policy would have to allow."""

from __future__ import annotations

import json
from html.parser import HTMLParser

from femkit.server.build import bundle_hashes, source_dir, sources_hash, static_dir


def test_the_shipped_bundle_is_built_from_the_sources_as_they_are():
    """Fails if a source of the page changed without `web build`, or a bundle file was edited,
    added or removed by hand: both hashes are recomputed here, without Node.js (api.md § 5.3)."""
    recorded = json.loads((static_dir() / "build.json").read_text())
    assert sources_hash(source_dir())["sha256"] == recorded["sources"]["sha256"], "run: python -m femkit web build"
    assert bundle_hashes(static_dir()) == recorded["bundle"]


class _Inline(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []
        self._script = False

    def handle_starttag(self, tag, attrs):
        names = dict(attrs)
        if tag == "style":
            self.found.append("a <style> element")
        if tag == "script":
            self._script = "src" not in names
        for name in names:
            if name == "style" or name.startswith("on"):
                self.found.append(f"a {name}= attribute on <{tag}>")

    def handle_data(self, data):
        if self._script and data.strip():
            self.found.append("an inline <script>")

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = False


def test_the_page_holds_no_inline_script_or_style():
    """Fails if the built page carries an inline script, a style element or attribute, or an
    event-handler attribute, which the policy `script-src 'self'; style-src 'self'` would
    block (api.md § 5.5)."""
    parser = _Inline()
    parser.feed((static_dir() / "index.html").read_text())
    assert parser.found == []
