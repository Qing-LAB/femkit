"""The shipped web page (web.md § 3): built from its sources as they are."""

from __future__ import annotations

import json
import shlex

from tests.kit import apply, hold, installed, planned, refused
from femkit.core import dirs
from femkit.core.errors import Busy, PlanStale
from femkit.definitions.requests import DOCS_SUBJECT
from femkit.envs import layout
from femkit.server.build import bundle_hashes, source_dir, sources_hash, static_dir

WEB = "web"   # the environment the page is built in, as its program's declaration names it (programs.toml)


def test_the_shipped_bundle_is_built_from_the_sources_as_they_are():
    """Fails if a source of the page changed without `web build`, or a bundle file was edited,
    added or removed by hand: both hashes are recomputed here, without Node.js (web.md § 3)."""
    recorded = json.loads((static_dir() / "build.json").read_text())
    assert sources_hash(source_dir())["sha256"] == recorded["sources"]["sha256"], "run: femkit web build"
    assert bundle_hashes(static_dir()) == recorded["bundle"]



def test_a_build_waits_for_neither_the_web_environment_nor_the_generated_files_to_change(manager):
    """Fails if `web build` runs while `schema docs` writes the files it builds from, or while
    the web environment it builds with changes — either holding its lock alone: the bundle would
    be built from half-written sources, and build.json name others (web.md § 3, api.md § 3)."""
    installed(WEB, outcomes=[])
    for subject in (layout.subject(WEB), DOCS_SUBJECT):
        op, plan, c = planned("web.build")
        holder = hold(subject, "alone")
        try:
            with refused(Busy, "held", subject):
                op.apply(plan, c)
        finally:
            holder.stdin.close()
            holder.wait()


def test_a_build_refuses_its_plan_when_its_environment_changed_since(manager):
    """Fails if `web build` applies a plan made while the web environment was ready after it
    changed: its npm steps would run in what is no longer that environment (api.md § 3)."""
    f = installed(WEB, outcomes=[])
    op, plan, c = planned("web.build")
    layout.manifest_file(f.prefix).unlink()                       # another shell, meanwhile
    with refused(PlanStale, "basis-changed"):
        op.apply(plan, c)


def test_npm_runs_in_the_web_environment_with_the_variables_its_declaration_gives_and_no_other(
        manager_doing, tmp_path, monkeypatch):
    """Fails if `web build`'s npm is started other than through the one door into the web
    environment — the manager's `run`, the clean start, and those its declaration names: a proxy the
    person set, passed as the start passes it, and npm's cache and configuration in femkit's cache — so
    that a variable of the person's shell reaches it, or a proxy does not (envs.md § 4.4: "the
    program's declared extra variables"; web.md § 3); or if a registry of the person's — a mirror
    their shell or their `~/.npmrc` names — can send it elsewhere than npm's own, which its
    declaration names (envs.md § 4.4: the recipe decides what goes in)."""
    seen = tmp_path / "npm.env"
    manager_doing(f'  "run --no-capture-output") env > {shlex.quote(str(seen))}; exit 1 ;;')   # npm ci fails
    installed(WEB, outcomes=[])
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("CC", "a-compiler-of-the-persons")
    monkeypatch.setenv("npm_config_registry", "https://mirror.example/npm/")
    assert apply("web.build").status == "failed"
    held = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)
    assert held["HTTPS_PROXY"] == "http://proxy.example:3128" and "CC" not in held
    assert held["npm_config_registry"] == "https://registry.npmjs.org/"
    assert held["npm_config_cache"] == str(dirs.cache_dir() / "frontend" / "npm-cache")
