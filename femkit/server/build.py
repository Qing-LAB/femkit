"""`web build`: the web page's bundle, built with the Node.js of the `web` environment (web.md § 3).

npm, as `programs.toml` declares it — its environment, and the variables it is set beyond the
clean start — runs inside that environment through the one door into it (envs.md § 4.4), where
its state allows its use (§ 3.3), in a work folder under femkit's cache, with its cache and
configuration there too: nothing reaches the person's home or the checkout but the bundle it
ships.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from femkit.core import dirs, text, view
from femkit.core.operations import Context, Outcome, Plan, Step, operation, run_steps
from femkit.core import persist
from femkit.core.persist import atomic_write_text, write_json
from femkit.definitions import catalogue
from femkit.envs import inside, layout
from femkit.envs.install import VERSION_TIMEOUT
from femkit.envs.state import observe, usable
from femkit.definitions.requests import DOCS_SUBJECT
from femkit.server.requests import BuildRequest
from femkit.server.requests import WEB_BUILD

NPM = "npm"     # the program that builds the page, by its name in programs.toml (envs.md § 4.4)


def source_dir() -> Path:
    return dirs.checkout() / "frontend"


def static_dir() -> Path:
    return dirs.checkout() / "femkit" / "web" / "static"


def work_root() -> Path:
    return dirs.cache_dir() / "frontend"


def declared_sources(root: Path) -> list[Path]:
    """Every file `package.json` declares the bundle is built from, relative to ``root``."""
    patterns = persist.read_json(root / "package.json")["femkit"]["sources"]
    found: set[Path] = set()
    for pattern in patterns:
        path = root / pattern
        if path.is_dir():
            found |= {p.relative_to(root) for p in path.rglob("*") if p.is_file()}
        elif path.is_file():
            found.add(path.relative_to(root))
    return sorted(found)


def sources_hash(root: Path) -> dict:
    """Each declared source's SHA-256, and the digest of them all: the one digest of a value
    (`persist.canonical_sha256`)."""
    files = {str(p): persist.sha256(root / p) for p in declared_sources(root)}
    return {"files": files, "sha256": persist.canonical_sha256(files)}


def bundle_hashes(static: Path) -> dict[str, str]:
    return {str(p.relative_to(static)): persist.sha256(p)
            for p in sorted(static.rglob("*")) if p.is_file() and p.name != "build.json"}


def licenses(work: Path) -> str:
    """Each package the lock file installs for the page (not for building it), with its license text."""
    lock = persist.read_json(work / "package-lock.json")
    parts = ["Third-party software in this bundle, from frontend/package-lock.json.", ""]
    for key, meta in sorted(lock.get("packages", {}).items()):
        if not key.startswith("node_modules/") or meta.get("dev"):
            continue
        folder = work / key
        texts = [p for p in sorted(folder.glob("*")) if p.is_file() and p.name.upper().startswith(("LICENSE", "LICENCE"))]
        parts += [f"== {key[len('node_modules/'):]} {meta.get('version', '')} ({meta.get('license', 'license not stated')})",
                  *(persist.read_bytes(t).decode("utf-8", errors="replace").strip() for t in texts), ""]
    return "\n".join(parts) + "\n"


class BuildOutcome(Outcome):
    written: list[str] = Field(default_factory=list, description="what was written into the checkout")
    static: str = Field(default="", description="the folder the bundle is written into")

    @property
    def report(self) -> view.Report:
        if self.status != "done":
            return view.Report(blocks=[view.Text(text=line) for line in self.plan.text(brief=True).splitlines()]
                               + [view.Text(text=f"log: {self.log}")])
        return view.Report(blocks=[view.Text(text=f"built the page: {text.count(len(self.written), 'file')} in "
                                                  f"{text.path(self.static)}")])


@operation(WEB_BUILD, result=BuildOutcome, subject=lambda req: ["web-build"])
class WebBuild:
    """Build the web page's bundle from frontend/ with the web environment's Node.js, into
    femkit/web/static/ with its build.json and third-party licenses."""

    def plan(self, req: BuildRequest, ctx: Context) -> Plan:
        npm = inside.program(ctx, NPM)
        usable(ctx, npm.environment, "web build")
        builds, work = inside.entered(ctx, npm.environment), work_root() / "work"
        steps = [Step(id="copy", describe=f"copy the declared sources of frontend/ to {text.path(work)}")]
        if req.relock:
            steps.append(Step(id="relock", describe="solve package-lock.json again from package.json",
                              argv=tuple(builds.program(npm, "install", "--package-lock-only", "--ignore-scripts"))))
        steps += [Step(id="install", describe="install the locked packages (npm ci --ignore-scripts)",
                       argv=tuple(builds.program(npm, "ci", "--ignore-scripts"))),
                  Step(id="build", describe="build the bundle (npm run build)",
                       argv=tuple(builds.program(npm, "run", "build"))),
                  Step(id="ship", describe=f"write the bundle, build.json and its licenses into "
                                           f"{text.path(static_dir())}")]
        return Plan(shared=(layout.subject(npm.environment), DOCS_SUBJECT),   # the environment it builds with,
                    steps=tuple(steps))                         # and the files `schema docs` generates for it, in use

    def observe(self, req: BuildRequest, ctx: Context) -> dict:
        """The declared sources of frontend/ as they are now — what the bundle is built from —
        and the state of the environment it is built with."""
        environment = inside.program(ctx, NPM).environment
        return {"sources": sources_hash(source_dir())["sha256"], environment: observe(ctx, environment)[1].value}

    def apply(self, plan: Plan, ctx: Context, observer) -> BuildOutcome:
        npm, work = inside.program(ctx, NPM), work_root() / "work"
        builds = inside.entered(ctx, npm.environment)
        written: list[str] = []
        built_from: dict = {}

        def do(step: Step, where: Path):
            log = where / f"{step.id}.log"
            if step.id == "copy":
                persist.remove(work)
                for rel in declared_sources(source_dir()):
                    persist.copy_file(source_dir() / rel, work / rel)
                built_from.update(sources_hash(work))          # what the bundle is built from, before npm touches it
                return "done", None
            if step.id == "ship":
                return _ship(work, builds, ctx, written, built_from), None
            observer.step_log(log)
            result = builds.run(step.argv, declared=npm, work=work_root(), cwd=work, log=log)
            if step.id == "relock" and result.ok:
                persist.copy_file(work / "package-lock.json", source_dir() / "package-lock.json")
                written.append(str(source_dir() / "package-lock.json"))
                built_from.update(sources_hash(work))          # the lock solved again is a source too
            return ("done" if result.ok else "failed"), log

        status, where = run_steps(plan, ctx, observer, do)
        return BuildOutcome(plan=plan, status=status, log=str(where), written=written, static=str(static_dir()))


def _version(result) -> str:
    """The last line a tool's `--version` printed; what was not printed is said, never guessed."""
    lines = result.stdout.strip().splitlines()
    if result.ok and lines:
        return lines[-1]
    return f"not measured: {result.argv[-2]} --version " + ("printed nothing" if result.ok else f"exited {result.returncode}")


def _ship(work: Path, builds: inside.Inside, ctx: Context, written: list[str], built_from: dict) -> str:
    """The bundle replaces femkit/web/static/ whole; build.json is written last: Node.js's version
    as the web environment's own version command states it, and npm's."""
    npm = inside.program(ctx, NPM)
    command = catalogue.environments(ctx)[npm.environment].version_command
    versions = {"node": _version(builds.run(builds.argv(command), timeout=VERSION_TIMEOUT)),
                "npm": _version(builds.run(builds.program(npm, "--version"), declared=npm, work=work_root()))}
    static, fresh = static_dir(), static_dir().with_name("static.new")
    persist.remove(fresh)
    persist.copy_tree(work / "dist", fresh)
    atomic_write_text(fresh / "THIRD-PARTY-LICENSES.txt", licenses(work))
    persist.replace_folder(fresh, static)
    write_json(static / "build.json", {"sources": built_from, "node": versions["node"],   # what was built
                                       "npm": versions["npm"], "bundle": bundle_hashes(static)})
    written += [str(p) for p in sorted(static.rglob("*")) if p.is_file()]
    return "done"
