"""A project's files (models.md § 2): where each lives, and the one way each is read."""

from __future__ import annotations

from pathlib import Path

from femkit.core.operations import Context
from femkit.core.schema import load_toml
from femkit.definitions import catalogue
from femkit.models.schema import ModelFile, StudyFile


def model_file(project: Path) -> Path:
    return project / "model.toml"


def study_file(project: Path, study: str) -> Path:
    return project / "studies" / study / "study.toml"


def studies(project: Path) -> list[str]:
    root = project / "studies"
    return sorted(p.parent.name for p in root.glob("*/study.toml")) if root.is_dir() else []


def load_model(project: Path, ctx: Context) -> ModelFile:
    """`model.toml`, its numbers read exactly; refused whole when it does not load (models.md § 11.2)."""
    return load_toml(model_file(project), ModelFile, {"units": catalogue.units(ctx)}, exact=True)


def load_study(project: Path, study: str, ctx: Context, model: ModelFile) -> StudyFile:
    """A study, read against its project's model: its references name the model's objects."""
    return read_study(study_file(project, study), ctx, model)


def read_study(path: Path, ctx: Context, model: ModelFile) -> StudyFile:
    """A study file wherever it lies — a project's, or a benchmark's beside its formulation."""
    return load_toml(path, StudyFile, {"units": catalogue.units(ctx), "model": model}, exact=True)
