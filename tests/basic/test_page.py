"""The page declaration (web.md § 8.1)."""

from __future__ import annotations

import pytest

from femkit.core.schema import DefinitionError
from femkit.server import page


def test_the_shipped_page_declaration_loads():
    """Fails if the page femkit ships names something that does not exist (web.md § 8.1)."""
    assert page.load().workspaces


@pytest.mark.parametrize("old, new, where", [
    ('document = "model.graph"', 'document = "model.nowhere"', "workspaces.0.document"),   # no such operation
    ('document = "model.graph"', 'document = "model.set"', "workspaces.0.document"),       # one that changes things
    ('rows = "studies"', 'rows = "nothing"', "context.1.rows"),                            # no such field
    ('value_key = "name"', 'value_key = "nowhere"', "context.2"),                          # no such row key
    ('depends = ["project"]', 'depends = ["study"]', "context.1.depends"),                 # depends on itself
    ('parameter = "variable"\n', "", "kinds"),                                               # a kind without its icon
])
def test_a_page_declaration_naming_what_does_not_exist_is_refused(tmp_path, monkeypatch, old, new, where):
    """Fails if a declaration naming an operation that does not exist or changes things, a field
    or key its result lacks, a context it does not declare, or leaving an object type without its
    icon, loads — the page would draw a part it cannot fill (web.md § 8.1)."""
    text = page.path().read_text(encoding="utf-8")
    assert old in text
    broken = tmp_path / "page.toml"
    broken.write_text(text.replace(old, new, 1), encoding="utf-8")
    monkeypatch.setattr(page, "path", lambda: broken)
    with pytest.raises(DefinitionError) as refused:
        page.load()
    assert where in [p for p, _ in refused.value.problems]
