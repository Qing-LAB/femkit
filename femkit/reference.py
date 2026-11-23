"""`schema check` and `schema docs` (definitions.md § 2.2–2.3).

They read every domain's models, so they live beside the registry, above the
domains (framework.md § 1).
"""

from __future__ import annotations

import enum
import html
import types
import typing
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from femkit.config.settings import UserConfig
from femkit.core import dirs, text
from femkit.core.issues import Issue
from femkit.core.errors import PlanStale
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.persist import atomic_write_text
from femkit.core.schema import Model, field_extras
from femkit.core.units import UnitTable, Units
from femkit.definitions import catalogue
from femkit.definitions.formulations import FormulationDefinition
from femkit.definitions.meshers import MesherDefinition
from femkit.definitions.models import ControlDefinition, EnvironmentDefinition, ManagerKind, SchedulerKind
from femkit.jobs.record import Record
from femkit.models.schema import ModelFile, StudyFile
from femkit.engines import registered

# page name -> (title, the files it describes, models)
PAGES: dict[str, tuple[str, str, list[type[Model]]]] = {
    "definitions": ("Shipped definitions", "`femkit/data/` (definitions.md)",
                    [ControlDefinition, EnvironmentDefinition, ManagerKind, SchedulerKind, UnitTable,
                     FormulationDefinition, MesherDefinition]),
    "config": ("User configuration", "`<config>/config.toml` (config.md § 3)", [UserConfig]),
    "machines": ("Machine records", "`<config>/machines/<name>.toml` (jobs.md § 9)", [Record]),
    "models": ("Models and studies", "`<project>/model.toml` and `<project>/studies/<study>/study.toml` "
               "(models.md § 3, § 5)", [ModelFile, StudyFile]),
}


def reference_dir() -> Path:
    return dirs.checkout() / "docs" / "reference"


# ----------------------------------------------------------------- schema check

class CheckRequest(Model):
    """No inputs."""


class CheckResult(Result):
    environments: list[str] = Field(default_factory=list, description="engine environments that loaded")
    managers: list[str] = Field(default_factory=list, description="manager kinds that loaded")
    schedulers: list[str] = Field(default_factory=list, description="scheduler kinds that loaded")
    units: int = Field(0, description="unit symbols the unit table reads, prefixed ones included")
    formulations: list[str] = Field(default_factory=list, description="formulations that loaded")
    meshers: list[str] = Field(default_factory=list, description="meshers that loaded")

    def text(self) -> str:
        if not self.ok():
            return "\n".join(["shipped definitions that do not load"] + text.findings(self.issues))
        return "\n".join(["every shipped definition loads"] + text.table([
            ("control", "channels.txt, control.txt"),
            ("environments", text.show(self.environments)),
            ("managers", text.show(self.managers)),
            ("schedulers", text.show(self.schedulers)),
            ("units", f"units.toml, {text.count(self.units, 'symbol')}"),
            ("formulations", text.show(self.formulations)),
            ("meshers", text.show(self.meshers)),
        ]))


@operation("schema.check", request=CheckRequest, result=CheckResult)
def schema_check(req: CheckRequest, ctx: Context) -> CheckResult:
    """Load every shipped definition and report every problem, each with its file and key path."""
    try:
        cat = catalogue.load(ctx, engines=registered())
    except catalogue.CatalogueError as exc:
        issues = [
            Issue(severity="error", code="definition-invalid", subject=err.file,
                  message=f"{err.file}: {path or '<file>'}: {reason}")
            for err in exc.errors for path, reason in err.problems
        ]
        return CheckResult(issues=issues)
    issues = _benchmark_issues(cat, ctx)
    if issues:
        return CheckResult(issues=issues)
    return CheckResult(environments=list(cat.environments), managers=list(cat.managers),
                       schedulers=list(cat.schedulers), units=len(Units(cat.units).symbols()),
                       formulations=list(cat.formulations), meshers=list(cat.meshers))


def _benchmark_issues(cat, ctx: Context) -> list[Issue]:
    """Each benchmark's project loads, is complete for its formulation (`model check`), and
    its reference names its study's observables, each in its observable's dimension
    (models.md § 4). Here, above both layers, as the definitions may not import `models`."""
    from femkit.core.errors import Refusal
    from femkit.models import check as model_check
    from femkit.models.project import load_model, read_study
    units = Units(cat.units)
    out: list[Issue] = []
    for fid, f in cat.formulations.items():
        for name, b in f.benchmarks.items():
            where = catalogue.data_root() / "formulations" / b.project
            subject = f"formulations/{fid}.toml: benchmarks.{name}"

            def problem(message: str) -> None:
                out.append(Issue(severity="error", code="benchmark-invalid", subject=subject,
                                 message=f"{subject}: {message}"))
            try:
                model = load_model(where, ctx)
                study = read_study(where / "study.toml", ctx, model)
            except Refusal as exc:
                problem(str(exc))
                continue
            if model.formulation != fid:
                problem(f"its model names the formulation {model.formulation!r}")
            for finding in model_check.findings(model, cat.formulations, units):
                problem(f"{finding.subject} {finding.message}")
            for observable, value in b.reference.items():
                spec = study.observables.get(observable)
                if spec is None:
                    problem(f"reference.{observable}: its study has no such observable")
                elif spec.unit is not None and units.parse(value).dimension != units.parse(spec.unit).dimension:
                    problem(f"reference.{observable}: {value!r} is not in the dimension of {spec.unit}")
    return out



# ------------------------------------------------------------------ rendering

def _type_name(annotation: Any) -> str:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        rest = [a for a in args if a is not type(None)]
        name = " or ".join(_type_name(a) for a in rest)
        return f"{name}, optional" if len(rest) < len(args) else name
    if origin is typing.Annotated:
        return _type_name(args[0])
    if origin is typing.Literal:
        return " \\| ".join(f"`{a}`" for a in args)
    if origin in (list, tuple):
        return f"list of {_type_name(args[0])}" if args else "list"
    if origin is dict:
        return f"table of {_type_name(args[0])} → {_type_name(args[1])}"
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return " \\| ".join(f"`{m.value}`" for m in annotation)
    if isinstance(annotation, type) and issubclass(annotation, Model):
        return f"[{annotation.__name__}](#{annotation.__name__.lower()})"
    return {str: "text", int: "integer", float: "number", bool: "boolean", Path: "path"}.get(
        annotation, getattr(annotation, "__name__", str(annotation)))


def _default(field: FieldInfo) -> str:
    if field.is_required():
        return "required"
    if field.default_factory is not None:
        value = field.default_factory()
    else:
        value = field.default
    if value is None or value is PydanticUndefined:
        return "—"
    if isinstance(value, Model):
        return "see table"
    return f"`{value!r}`" if value not in ([], {}) else "empty"


def _nested(annotation: Any) -> list[type[Model]]:
    if isinstance(annotation, type) and issubclass(annotation, Model):
        return [annotation]
    found = []
    for arg in typing.get_args(annotation):
        found += _nested(arg)
    return found


def _cell(text: str) -> str:
    return html.escape(text, quote=False).replace("|", "\\|")


def render_model(model: type[Model], seen: set) -> list[str]:
    if model in seen:
        return []
    seen.add(model)
    doc = " ".join((model.__doc__ or "").split())
    lines = [f"## {model.__name__}", ""] + ([doc, ""] if doc else [])
    lines += ["| key | type | default | meaning |", "|---|---|---|---|"]
    nested: list[type[Model]] = []
    for name, field in model.model_fields.items():
        meaning = _cell(field.description or "")
        extra = field_extras(field)
        if "unset" in extra:
            meaning += f". When unset: {_cell(extra['unset'])}"
        if "ref" in extra:
            target = extra["ref"]
            names = target if isinstance(target, str) else ", ".join(f"its {k}s: {v}" for k, v in target.items())
            meaning += f". Refers by name to {_cell(names.replace('|', ' or '))}"
        if "quantity" in extra:
            meaning += {"any": ". A quantity with its unit, or an expression of parameters",
                        "length": ". A length", "coordinate": ". A bare number in the frame's unit, or a length",
                        "unit": ". A unit"}[extra["quantity"]]
        if "placeholders" in extra:
            meaning += ". Placeholders: " + ", ".join("`{%s}`" % p for p in extra["placeholders"])
        lines.append(f"| `{field.alias or name}` | {_type_name(field.annotation)} | {_default(field)} | {meaning} |")  # the key as written
        nested += _nested(field.annotation)
    lines.append("")
    for sub in nested:
        lines += render_model(sub, seen)
    return lines


def render_page(name: str) -> str:
    title, describes, models = PAGES[name]
    lines = [
        f"# {title}", "",
        "**Role:** reference",
        "**Status:** generated by `python -m femkit schema docs` — do not edit",
        f"**Authority:** none of its own; the schema models are the authority for {describes}",
        "",
    ]
    seen: set = set()
    for model in models:
        lines += render_model(model, seen)
    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------ schema docs

class DocsRequest(Model):
    """No inputs."""


class DocsOutcome(Outcome):
    written: list[str] = Field(default_factory=list, description="pages written")

    def text(self) -> str:
        if not self.written:
            return "docs/reference/ is up to date"
        return "\n".join([f"wrote {text.count(len(self.written), 'page')}"]
                         + [f"  {p}" for p in self.written])


def _stale() -> dict[str, str]:
    """page file name -> its text, for every page that differs from what the models render."""
    out = {}
    for name in PAGES:
        path, text = reference_dir() / f"{name}.md", render_page(name)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            out[path.name] = text
    return out


@operation("schema.docs", request=DocsRequest, result=DocsOutcome, changes=True,
           subject=lambda req: ["reference-docs"])
class SchemaDocs:
    """Render docs/reference/ from the schema models; pages already up to date are left alone."""

    def plan(self, req: DocsRequest, ctx: Context) -> Plan:
        stale = _stale()
        steps = tuple(Step(id=name, describe=f"write {text.path(reference_dir() / name)}") for name in sorted(stale))
        return Plan(operation="schema.docs", request=req.model_dump(mode="json"),
                    basis={"stale": sorted(stale)}, steps=steps)

    def apply(self, plan: Plan, ctx: Context, observer) -> DocsOutcome:
        pages = _stale()
        if sorted(pages) != plan.basis["stale"]:
            raise PlanStale("the reference pages changed since the plan; plan again", (text.typed("schema", "docs"),))
        written: list[str] = []

        def do(step: Step, where):
            path = atomic_write_text(reference_dir() / step.id, pages[step.id])
            written.append(str(path))
            return "done", None

        status, log = run_steps(plan, ctx, observer, do)
        return DocsOutcome(plan=plan, status=status, log=str(log), written=written)
