"""The requests of the operations over the shipped definitions, `schema check` and `schema docs`
(definitions.md § 2.3): declared beside the definitions they check, so a refusal about them
names its next step without reaching above this domain (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.core.schema import Model


class CheckRequest(Model):
    """No inputs."""


class DocsRequest(Model):
    """No inputs."""


# ------------------------------------------------------------------ the operations these requests are for

SCHEMA_CHECK = Verb("schema.check", CheckRequest, on_machine=False, effect="reads")
SCHEMA_DOCS = Verb("schema.docs", DocsRequest, on_machine=False, effect="changes")
DOCS_SUBJECT = "reference-docs"   # held by `schema docs` while it writes; shared by `web build`, which builds from its files
