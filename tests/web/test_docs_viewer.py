"""The document viewer's server side (web.md § 1, § 2): only the repository's documents,
by a list made without following a link; each heading's anchor by GitHub's rule."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from femkit.core import dirs
from femkit.core.markdown import headings
from femkit.server.protocol import Listen
from femkit.web import docs

AUTH = {"Authorization": "Bearer t", "Host": "127.0.0.1:8000"}


@pytest.fixture
def client():
    from femkit.web.app import create_app
    return create_app("t", Listen(port=8000)).test_client()


@pytest.fixture
def checkout(tmp_path, monkeypatch) -> Path:
    """A checkout of its own: documents, an image, code, a local file, and links leading out."""
    (tmp_path / "docs" / "sub").mkdir(parents=True)
    (tmp_path / "docs" / "README.md").write_text("# Index\n")
    (tmp_path / "docs" / "sub" / "a.md").write_text("# A\n")
    (tmp_path / "docs" / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (tmp_path / "femkit").mkdir()
    (tmp_path / "femkit" / "secret.py").write_text("token = 1\n")
    (tmp_path / "README.md").write_text("# femkit\n")
    (tmp_path / "LOCAL.md").write_text("# a local note\n")            # beside the root documents, never shown
    (tmp_path / "outside.md").write_text("# outside\n")
    os.symlink(tmp_path / "outside.md", tmp_path / "docs" / "leak.md")  # a link to a file outside docs/
    os.symlink(tmp_path / "femkit", tmp_path / "docs" / "code")         # a link to a folder outside docs/
    monkeypatch.setattr(dirs, "checkout", lambda: tmp_path)
    return tmp_path


def test_the_viewer_lists_only_the_repositorys_documents(checkout):
    """Fails if a local file at the root, a file reached through a symbolic link, or anything
    but Markdown and images is listed (web.md § 2)."""
    assert docs.listing() == ["README.md", "docs/README.md", "docs/logo.svg", "docs/sub/a.md"]


@pytest.mark.parametrize("path", ["femkit/secret.py", "docs/leak.md", "docs/code/secret.py", "LOCAL.md",
                                  "docs/../femkit/secret.py", "docs/%2e%2e/femkit/secret.py", "/etc/passwd",
                                  "docs/sub/../../femkit/secret.py"])
def test_no_spelling_of_a_path_reaches_beyond_the_documents(checkout, client, path):
    """Fails if any path not on the viewer's list — another file, a link out, a climb up, an
    absolute path — is served (web.md § 2)."""
    response = client.get(f"/api/docs/{path}", headers=AUTH)
    assert response.status_code in (404, 405) and b"token = 1" not in response.get_data()  # refused, its content never sent


def test_a_document_comes_as_text_with_its_anchors_and_an_image_as_data(checkout, client):
    """Fails if a document is served as anything but its text with its headings, an image as
    anything but data, or either without the token (web.md § 1, § 5)."""
    assert client.get("/api/docs/docs/sub/a.md", headers={"Host": "127.0.0.1:8000"}).status_code == 401
    doc = client.get("/api/docs/docs/sub/a.md", headers=AUTH).get_json()
    assert doc["text"] == "# A\n" and doc["headings"] == [{"level": 1, "text": "A", "anchor": "a"}]
    image = client.get("/api/docs/docs/logo.svg", headers=AUTH).get_json()
    assert image["type"] == "image/svg+xml" and "data" in image


def test_a_headings_anchor_is_githubs():
    """Fails if an anchor differs from GitHub's — a link written in a document, a section a
    formulation names, and the viewer's address would then disagree (web.md § 2)."""
    text = ("# 5.4 Serving — `serve`\n## Terms and symbols\n```toml\n# not a heading\n```\n"
            "## Terms and symbols\n### What's `n`, really?\n")
    assert [h.anchor for h in headings(text)] == ["54-serving--serve", "terms-and-symbols", "terms-and-symbols-1",
                                                  "whats-n-really"]
