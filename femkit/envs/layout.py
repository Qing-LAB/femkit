"""Where an environment's files live, within the prefix the manager lists for it and in femkit's
own folders (envs.md § 1, § 4.3; config.md § 4): never where the prefix itself lies, which is the
manager's (`manager.Manager.prefix`)."""

from __future__ import annotations

from pathlib import Path

from femkit.core import dirs, locks
from femkit.core.operations import operations_root

def unmade(managed: str) -> Path:
    """What a plan made before the environment the manager knows as ``managed`` exists writes for its
    prefix, `<prefix of femkit-NAME>`: each step that needs it runs with the one the manager then
    lists (envs.md § 4.1)."""
    return Path(f"<prefix of {managed}>")


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
    """The saved package list, beside the subjects' lock files (envs.md § 4.3)."""
    return locks.root() / name / f"{install_fingerprint}.txt"


def archive_cache(sha256: str) -> Path:
    return dirs.cache_dir() / "sources" / f"{sha256}.tar.gz"


def subject(name: str) -> str:
    """The lock subject and operation-log folder of an environment."""
    return f"env-{name}"


def operations_dir(name: str) -> Path:
    return operations_root(subject(name))
