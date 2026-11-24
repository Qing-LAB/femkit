"""Install records inside each prefix (envs.md § 4.3, § 5)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from femkit.core.persist import read_json
from femkit.core.schema import Model


class Manifest(Model):
    """`<prefix>/.femkit/manifest.json` — written last by an install: its commit point."""

    install_fingerprint: str = Field(description="the install fingerprint it was built for", json_schema_extra={"doc": "envs.md § 2"})
    lock_sha256: str = Field(description="SHA-256 of the exact package list it was created from")
    manager_kind: str = Field(description="the manager kind that made it")
    manager_version: str = Field(description="that manager's version")
    solver_version: str = Field(description="what the engine's version probe reported")
    time: str = Field(description="when it was written, UTC")


class CheckOutcome(Model):
    id: str = Field(description="the check's ID")
    outcome: Literal["passed", "failed"] = Field(description="whether it met everything it expects")
    quantities: dict = Field(default_factory=dict, description="what its reader produced")
    reason: str = Field(default="", description="why it did not pass")
    log: str | None = Field(default=None, description="its log file")


class ChecksRecord(Model):
    """`<prefix>/.femkit/checks.json` — written by each validate."""

    check_fingerprint: str = Field(description="the check fingerprint the outcomes are for", json_schema_extra={"doc": "envs.md § 2"})
    outcomes: list[CheckOutcome] = Field(description="every check's outcome")
    time: str = Field(description="when it was written, UTC")


def read(path: Path, model):
    """The record, or None when it is missing or does not load (it then counts as missing)."""
    try:
        return model.model_validate(read_json(path))
    except (OSError, ValueError):
        return None
