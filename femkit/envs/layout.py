"""Where an environment's files live (envs.md § 1, § 4.3; config.md § 4)."""

from __future__ import annotations

from pathlib import Path

from femkit.config import settings
from femkit.core import dirs
from femkit.core.operations import Context, operations_root


def prefix(ctx: Context, name: str) -> Path:
    return settings.environments_root(settings.load(ctx).config) / name


def records(prefix_dir: Path) -> Path:
    return prefix_dir / ".femkit"


def manifest_file(prefix_dir: Path) -> Path:
    return records(prefix_dir) / "manifest.json"


def checks_file(prefix_dir: Path) -> Path:
    return records(prefix_dir) / "checks.json"


def source_tree(prefix_dir: Path) -> Path:
    return records(prefix_dir) / "src"


def build_tree(prefix_dir: Path) -> Path:
    return records(prefix_dir) / "build"


def source_dir(prefix_dir: Path, env, source_id: str) -> Path:
    """Where a declared source is unpacked: its `into`, under the source tree."""
    return source_tree(prefix_dir) / next(s.into for s in env.sources if s.id == source_id)


def build_dir(prefix_dir: Path, build_id: str) -> Path:
    return build_tree(prefix_dir) / build_id


def toolchain_dir(prefix_dir: Path) -> Path:
    """Where the toolchain step writes its trivial programs: outside the build tree, so no
    build's folder is its."""
    return records(prefix_dir) / "toolchain"


def lock_file(name: str, install_fingerprint: str) -> Path:
    return dirs.data_dir() / "locks" / name / f"{install_fingerprint}.txt"


def archive_cache(sha256: str) -> Path:
    return dirs.cache_dir() / "sources" / f"{sha256}.tar.gz"


def subject(name: str) -> str:
    """The lock subject and operation-log folder of an environment."""
    return f"env-{name}"


def operations_dir(name: str) -> Path:
    return operations_root(subject(name))
