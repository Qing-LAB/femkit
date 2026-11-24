"""A project's files (models.md § 2): where each lives, and the one way each is read."""

from __future__ import annotations

import tomllib

from pathlib import Path

from femkit.core.operations import Context
from femkit.core.schema import load_toml, validate
from femkit.definitions import catalogue
from femkit.models.schema import ModelFile, StudyFile


def model_file(project: Path) -> Path:
    return project / "model.toml"


def study_file(project: Path, study: str) -> Path:
    return project / "studies" / study / "study.toml"


def file_of(project: Path, study: str | None) -> Path:
    """The file a study's name names in ``project``; none: the model's."""
    return model_file(project) if study is None else study_file(project, study)


def studies(project: Path) -> list[str]:
    root = project / "studies"
    return sorted(p.parent.name for p in root.glob("*/study.toml")) if root.is_dir() else []


#: A model or a study before anything is set: what the first edit writes into (models.md § 11.1).
NEW_FILE = "schema = 1\n"


def load_model(project: Path, ctx: Context) -> ModelFile:
    """`model.toml`, its numbers read exactly; refused whole when it does not load (models.md § 11.2).
    A folder with none holds the empty model, which `model check` and the graph read like any
    other (web.md § 8.4)."""
    path = model_file(project)
    if not path.exists():
        return validate(ModelFile, tomllib.loads(NEW_FILE), path, {"units": catalogue.units(ctx)})
    return load_toml(path, ModelFile, {"units": catalogue.units(ctx)}, exact=True)


def load_study(project: Path, study: str, ctx: Context, model: ModelFile) -> StudyFile:
    """A study, read against its project's model: its references name the model's objects."""
    return read_study(study_file(project, study), ctx, model)


def read_study(path: Path, ctx: Context, model: ModelFile) -> StudyFile:
    """A study file wherever it lies — a project's, or a benchmark's beside its formulation."""
    return load_toml(path, StudyFile, {"units": catalogue.units(ctx), "model": model}, exact=True)
