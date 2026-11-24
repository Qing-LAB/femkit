"""`web build`: the web page's bundle, built with the Node.js of the `web` environment (web.md § 3).

npm runs inside that environment through the manager, in a work folder under femkit's
cache, with its cache and configuration there too: nothing reaches the person's home or
the checkout but the bundle it ships.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field

from femkit.core import dirs, text, view
from femkit.core.errors import Refused
from femkit.core.operations import Context, Outcome, Plan, Step, operation, run_steps
from femkit.core import persist
from femkit.core.persist import atomic_write_text, write_json
from femkit.core.process import run
from femkit.envs import layout
from femkit.envs.manager import confined, resolve
from femkit.envs.state import EnvState, observe
from femkit.server.requests import BuildRequest
from femkit.envs.requests import ENV_INSTALL
from femkit.server.requests import WEB_BUILD

TOOL = "web"                       # the environment that builds and serves the page (definitions.md § 4.7)
PROXIES = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")


def source_dir() -> Path:
    return dirs.checkout() / "frontend"


def static_dir() -> Path:
    return dirs.checkout() / "femkit" / "web" / "static"


def work_root() -> Path:
    return dirs.cache_dir() / "frontend"


def declared_sources(root: Path) -> list[Path]:
    """Every file `package.json` declares the bundle is built from, relative to ``root``."""
    patterns = json.loads((root / "package.json").read_text(encoding="utf-8"))["femkit"]["sources"]
    found: set[Path] = set()
    for pattern in patterns:
        path = root / pattern
        if path.is_dir():
            found |= {p.relative_to(root) for p in path.rglob("*") if p.is_file()}
        elif path.is_file():
            found.add(path.relative_to(root))
    return sorted(found)


def sources_hash(root: Path) -> dict:
    files = {str(p): hashlib.sha256((root / p).read_bytes()).hexdigest() for p in declared_sources(root)}
    whole = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"files": files, "sha256": whole}


def bundle_hashes(static: Path) -> dict[str, str]:
    return {str(p.relative_to(static)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(static.rglob("*")) if p.is_file() and p.name != "build.json"}


def npm_environment(base: dict[str, str]) -> dict[str, str]:
    """npm's cache and configuration in femkit's cache; a proxy the person set still passes."""
    root = work_root()
    for name in ("npmrc", "npmrc-global"):
        persist.touch(root / name)
    return {**confined(base), **{k: base[k] for k in PROXIES if k in base},
            "npm_config_cache": str(root / "npm-cache"), "npm_config_userconfig": str(root / "npmrc"),
            "npm_config_globalconfig": str(root / "npmrc-global"), "npm_config_update_notifier": "false",
            "npm_config_fund": "false", "npm_config_audit": "false"}


def licenses(work: Path) -> str:
    """Each package the lock file installs for the page (not for building it), with its license text."""
    lock = json.loads((work / "package-lock.json").read_text(encoding="utf-8"))
    parts = ["Third-party software in this bundle, from frontend/package-lock.json.", ""]
    for key, meta in sorted(lock.get("packages", {}).items()):
        if not key.startswith("node_modules/") or meta.get("dev"):
            continue
        folder = work / key
        texts = [p for p in sorted(folder.glob("*")) if p.is_file() and p.name.upper().startswith(("LICENSE", "LICENCE"))]
        parts += [f"== {key[len('node_modules/'):]} {meta.get('version', '')} ({meta.get('license', 'license not stated')})",
                  *(t.read_text(encoding="utf-8", errors="replace").strip() for t in texts), ""]
    return "\n".join(parts) + "\n"


class BuildOutcome(Outcome):
    written: list[str] = Field(default_factory=list, description="what was written into the checkout")

    def text(self) -> str:
        if self.status != "done":
            return "\n".join([self.plan.text(brief=True), f"log: {self.log}"] + text.findings(self.issues))
        return "\n".join([f"built the page: {text.count(len(self.written), 'file')} in "
                          f"{text.path(static_dir())}"] + text.findings(self.issues))


@operation(WEB_BUILD, result=BuildOutcome, changes=True, subject=lambda req: ["web-build"])
class WebBuild:
    """Build the web page's bundle from frontend/ with the web environment's Node.js, into
    femkit/web/static/ with its build.json and third-party licenses."""

    def plan(self, req: BuildRequest, ctx: Context) -> Plan:
        state = observe(ctx, TOOL)[1]
        if state is not EnvState.ready:
            raise Refused(f"the {TOOL} tool environment, which builds the page, is {state.value}",
                          (view.command(ENV_INSTALL, names=[TOOL]),), code="environment-not-ready", subject=TOOL)
        m, prefix, work = resolve(ctx), layout.prefix(ctx, TOOL), work_root() / "work"
        steps = [Step(id="copy", describe=f"copy the declared sources of frontend/ to {text.path(work)}")]
        if req.relock:
            steps.append(Step(id="relock", describe="solve package-lock.json again from package.json",
                              argv=tuple(m.in_prefix(prefix, ["npm", "install", "--package-lock-only",
                                                              "--ignore-scripts"]))))
        steps += [Step(id="install", describe="install the locked packages (npm ci --ignore-scripts)",
                       argv=tuple(m.in_prefix(prefix, ["npm", "ci", "--ignore-scripts"]))),
                  Step(id="build", describe="build the bundle (npm run build)",
                       argv=tuple(m.in_prefix(prefix, ["npm", "run", "build"]))),
                  Step(id="ship", describe=f"write the bundle, build.json and its licenses into "
                                           f"{text.path(static_dir())}")]
        return Plan(shared=(layout.subject(TOOL),), steps=tuple(steps))   # the environment it builds with, in use

    def observe(self, req: BuildRequest, ctx: Context, held: bool) -> dict:
        """The declared sources of frontend/ as they are now: what the bundle is built from."""
        return {"sources": sources_hash(source_dir())["sha256"]}

    def apply(self, plan: Plan, ctx: Context, observer) -> BuildOutcome:
        m, work = resolve(ctx), work_root() / "work"
        env = npm_environment(m.environment)
        written: list[str] = []

        def do(step: Step, where: Path):
            log = where / f"{step.id}.log"
            if step.id == "copy":
                persist.remove(work)
                for rel in declared_sources(source_dir()):
                    persist.copy_file(source_dir() / rel, work / rel)
                return "done", None
            if step.id == "ship":
                return _ship(work, m, ctx, written), None
            observer.step_log(log)
            result = run(list(step.argv), env=env, cwd=work, log=log)
            if step.id == "relock" and result.ok:
                persist.copy_file(work / "package-lock.json", source_dir() / "package-lock.json")
                written.append(str(source_dir() / "package-lock.json"))
            return ("done" if result.ok else "failed"), log

        status, where = run_steps(plan, ctx, observer, do)
        return BuildOutcome(plan=plan, status=status, log=str(where), written=written)


def _version(result) -> str:
    """The last line a tool's `--version` printed; what was not printed is said, never guessed."""
    lines = result.stdout.strip().splitlines()
    if result.ok and lines:
        return lines[-1]
    return f"not measured: {result.argv[-2]} --version " + ("printed nothing" if result.ok else f"exited {result.returncode}")


def _ship(work: Path, m, ctx: Context, written: list[str]) -> str:
    """The bundle replaces femkit/web/static/ whole; build.json is written last."""
    prefix = layout.prefix(ctx, TOOL)
    versions = {tool: _version(run(m.in_prefix(prefix, [tool, "--version"]), env=confined(m.environment), timeout=60))
                for tool in ("node", "npm")}
    static, fresh = static_dir(), static_dir().with_name("static.new")
    persist.remove(fresh)
    persist.copy_tree(work / "dist", fresh)
    atomic_write_text(fresh / "THIRD-PARTY-LICENSES.txt", licenses(work))
    persist.replace_folder(fresh, static)
    write_json(static / "build.json", {"sources": sources_hash(source_dir()), "node": versions["node"],
                                       "npm": versions["npm"], "bundle": bundle_hashes(static)})
    written += [str(p) for p in sorted(static.rglob("*")) if p.is_file()]
    return "done"
