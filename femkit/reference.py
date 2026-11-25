"""`schema check` and `schema docs` (definitions.md § 2.2–2.3).

They read every domain's models, so they live beside the registry, above the
domains (framework.md § 1).
"""

from __future__ import annotations

import json
from dataclasses import fields

import enum
import html
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from femkit.config.settings import UserConfig
from femkit.core import dirs, states, text, view
from femkit.definitions.requests import CheckRequest, DocsRequest
from femkit.core.issues import Issue
from femkit.core.operations import Context, Outcome, Plan, Result, Step, operation, run_steps
from femkit.core.persist import atomic_write_text, inline_text, read_text
from femkit.core.schema import (QUANTITIES, DefinitionError, Model, allowed, alternatives, classes, described,
                                field_extras, items_of, keys_of, optional, values_of)
from femkit.definitions import catalogue
from femkit.jobs.record import Record
from femkit.models.cases import Case
from femkit.projects import layout as layouts
from femkit.projects import location
from femkit.projects.project import PROJECT_FILE
from femkit import page
from femkit.definitions.requests import DOCS_SUBJECT, SCHEMA_CHECK, SCHEMA_DOCS


def pages() -> dict[str, tuple[str, str, list[type[Model]]]]:
    """page name -> (title, the files it describes, models). A project's parts are the part
    schemas the registry registers (api.md § 6), a page once there is one."""
    from femkit import registry               # here: the registry imports this module
    parts = list(registry.part_schemas().values())
    return {
        "definitions": ("Shipped definitions", "`femkit/data/` (definitions.md)",
                        [kind.metadata["model"] for kind in fields(catalogue.Catalogue) if kind.metadata["model"]]
                        + [layouts.Layout, page.Page]),
        "config": ("User configuration", "`<config>/config.toml` (config.md § 3)", [UserConfig]),
        "machines": ("Machine records", "`<config>/machines/<name>.toml` (jobs.md § 9)", [Record]),
        "cases": ("Cases", "`<project>/cases/<study>/<id>/case.json` (models.md § 5.3)", [Case]),
        "parts": ("A project's parts", "each part of a project (projects.md §§ 2–4)", parts),
    }


def reference_dir() -> Path:
    return dirs.checkout() / "docs" / "reference"


# ----------------------------------------------------------------- schema check

class Loaded(Model):
    type: str = Field(description="a type of shipped definition")
    files: str = Field(description="where its files are, under femkit/data/")
    names: list[str] = Field(default_factory=list, description="each of its definitions, by name; none for one file")


class SchemaCheckResult(Result):
    loaded: list[Loaded] = Field(default_factory=list, description="each type of shipped definition that loaded")

    def report(self) -> view.Report:
        if not self.ok():
            return view.Report(blocks=[view.Text(text="shipped definitions that do not load")])
        return view.Report(blocks=[
            view.Text(text="every shipped definition loads"),
            view.Table(columns=view.columns("type", "loaded"),
                       rows=[{"type": row.type, "loaded": text.show(row.names) if row.names else row.files}
                             for row in self.loaded])])


@operation(SCHEMA_CHECK, result=SchemaCheckResult)
def schema_check(req: CheckRequest, ctx: Context) -> SchemaCheckResult:
    """Load every shipped definition and report every problem, each with its file and key path."""
    try:
        cat = catalogue.load(ctx)
    except catalogue.CatalogueError as exc:
        return SchemaCheckResult(issues=[i for err in exc.errors for i in _issues(err)])
    from femkit import registry               # here: the registry imports this module
    ops = registry.operations()
    issues = _benchmark_issues(cat, ctx) + _template_issues(cat)
    beside = [(lambda: catalogue.load_states({"operations": {n: op.request for n, op in ops.items()}})),
              layouts.read, lambda: page.load(ops)]
    for load in beside:   # what the catalogue's own rules cannot see: the operations, the layout, the page
        try:
            load()
        except catalogue.CatalogueError as exc:
            issues += [i for err in exc.errors for i in _issues(err)]
        except DefinitionError as exc:
            issues += _issues(exc)
    issues += _machine_issues()
    if issues:   # a file met twice — a table by its rules and bound, the layout by itself and by the page — said once
        return SchemaCheckResult(issues=list({(i.subject, i.message): i for i in issues}.values()))
    loaded = [Loaded(type=kind.name, files=kind.metadata["files"],
                     names=list(part) if isinstance(part := getattr(cat, kind.name), dict) else [])
              for kind in fields(catalogue.Catalogue)]
    return SchemaCheckResult(loaded=loaded + [Loaded(type=name, files=str(file().relative_to(catalogue.data_root())))
                                              for name, file in (("layout", layouts.file), ("page", page.path))])


def _issues(err: DefinitionError) -> list[Issue]:
    """A file that does not load, as findings: one per problem, with its file and key path."""
    return [Issue(severity="error", code="definition-invalid", subject=err.file, message=line) for line in err.lines()]


def _machine_issues() -> list[Issue]:
    """Each machine's table bound to what its domain's code gives it — the facts its conditions
    name, the values its requests take, the states the code reads (core.md § 7) — so a table
    lacking a state the code reads is refused here, before the code meets it. A binding whose
    machine femkit ships no table of is not femkit's."""
    out: list[Issue] = []
    for binding in states.bindings():
        path = catalogue.state_file(binding.machine)
        if path.is_file():
            try:
                states.load(path, binding)
            except DefinitionError as exc:
                out += _issues(exc)
    return out


def _template_issues(cat) -> list[Issue]:
    """Each template is a project named bare — one step of the name rule — holding its project
    file (projects.md § 7). Here, above both layers, as the definitions may not import `projects`;
    each template's own check is `project check`'s."""
    return [Issue(severity="error", code="definition-invalid", subject=str(folder),
                  message=f"{folder}: a template is a project named by one step of the name rule, holding "
                          f"{PROJECT_FILE}")
            for name, folder in cat.templates.items()
            if "/" in name or location.project_at(folder.parent, name) is None]


def _benchmark_issues(cat, ctx: Context) -> list[Issue]:
    """Each benchmark's project template passes `project check` where it can check without
    building its geometry, its one study's steps state the benchmark's formulation, and its
    reference names an observable of that study, in that observable's dimension (models.md § 4.3).
    Here, above both layers, as the definitions may not import `models`."""
    from femkit.models.physics import Physics
    from femkit.models.study import KEY as STUDY_SCHEMA, cites
    from femkit.projects import checking, door
    from femkit.projects.project import Project
    out: list[Issue] = []
    try:
        layouts.read()
    except DefinitionError:
        return out                    # no project opens until the layout loads; its own loading says why
    for fid, f in cat.formulations.items():
        for name, b in f.benchmarks.items():
            subject = f"formulations/{fid}.toml: benchmarks.{name}"

            def problem(message: str) -> None:
                out.append(Issue(severity="error", code="benchmark-invalid", subject=subject,
                                 message=f"{subject}: {message}"))
            try:
                opened = door.open_project(Project(cat.templates[b.project].parent, b.project), ctx)
            except DefinitionError as exc:
                problem(exc.summary())
                continue
            c = checking.Checking.of(opened, ctx)
            for finding in checking.findings(c):
                if finding.severity == "error":
                    problem(f"{finding.file}: {finding.key or '<file>'}: {finding.message}")
            study_kind = opened.layout.kind_of(STUDY_SCHEMA)
            studies = [p for p in opened.parts.values() if p.address.kind == study_kind and p.data is not None]
            if len(studies) != 1:
                problem(f"its project {b.project} holds {len(studies)} studies that load, not one")
                continue
            study = studies[0].data
            for step in study.steps.values():
                physics = cites(c, "physics", step.physics, type(step))
                if physics is not None and isinstance(physics.data, Physics) and physics.data.formulation != fid:
                    problem(f"its study's step solves {physics.data.formulation}, not {fid}")
            units = {o: spec.unit for s in study.observables if (held := cites(c, "observables", s)) is not None
                     for o, spec in held.data.observables.items()}
            for observable, value in b.reference.items():
                if observable not in units:
                    problem(f"reference.{observable}: its study reports no such observable")
                elif c.units.parse(value).dimension != c.units.parse(units[observable]).dimension:
                    problem(f"reference.{observable}: {value!r} is not in the dimension of {units[observable]}")
    return out


# ------------------------------------------------------------------ rendering

def _type_name(annotation: Any) -> str:
    name = " or ".join(_one_type(a) for a in alternatives(annotation))
    return f"{name}, optional" if optional(annotation) else name


def _one_type(annotation: Any) -> str:
    if values := allowed(annotation):                            # a Literal's values, text or not
        return " \\| ".join(f"`{a}`" for a in values)
    if (item := items_of(annotation)) is not None:
        return f"list of {_type_name(item)}"
    if (value := values_of(annotation)) is not None:
        return f"table of {_type_name(keys_of(annotation))} → {_type_name(value)}"
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
    return f"`{inline_text(value)}`" if value not in ([], {}) else "empty"   # as the file writes it


def _nested(annotation: Any) -> list[type[Model]]:
    """The models a field holds: as itself, as a list's items or a table's values."""
    if annotation is None:
        return []
    return [*classes(annotation), *_nested(items_of(annotation)), *_nested(values_of(annotation))]


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
        meaning = _cell(described(field))
        extra = field_extras(field)
        if "unset" in extra:
            meaning += f". When unset: {_cell(extra['unset'])}"
        if "ref" in extra:
            target = extra["ref"]
            names = target if isinstance(target, str) else ", ".join(f"its {k}s: {v}" for k, v in target.items())
            meaning += f". Refers by name to {_cell(names.replace('|', ' or '))}"
        if "quantity" in extra:
            meaning += f". {QUANTITIES[extra['quantity']].sentence.capitalize()}"
        if "placeholders" in extra:
            meaning += ". Placeholders: " + ", ".join("`{%s}`" % p for p in extra["placeholders"])
        lines.append(f"| `{field.alias or name}` | {_type_name(field.annotation)} | {_default(field)} | {meaning} |")  # the key as written
        nested += _nested(field.annotation)
    lines.append("")
    for sub in nested:
        lines += render_model(sub, seen)
    return lines


def render_page(name: str) -> str:
    title, describes, models = pages()[name]
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

class DocsOutcome(Outcome):
    written: list[str] = Field(default_factory=list, description="pages written")

    def report(self) -> view.Report:
        if not self.written:
            return view.Report(blocks=[view.Text(text="docs/reference/ and the page's schemas are up to date")])
        return view.Report(blocks=[view.Text(text=f"wrote {text.count(len(self.written), 'page')}"),
                                   view.Table(columns=view.columns("page"),
                                              rows=[{"page": p} for p in self.written])])


def schemas_file() -> Path:
    """The page's schemas, from which `web build` writes its types (web.md § 8.7)."""
    return dirs.checkout() / "frontend" / "src" / "generated" / "schemas.json"


def page_schemas() -> str:
    """Every model the page reads — the vocabulary of core/view.py and core/operations.py, every
    registered operation's result, the page declaration — as one JSON schema, in the form the
    server writes them."""
    from pydantic.json_schema import models_json_schema
    from femkit import registry               # here: the registry imports this module
    from femkit.core import operations as surface
    vocabulary = [m for module in (view, surface) for m in vars(module).values()
                  if isinstance(m, type) and issubclass(m, Model) and m.__module__ == module.__name__]
    results = {op.result for op in registry.operations().values()}
    models = sorted({*vocabulary, *results, page.Page}, key=lambda m: (m.__module__, m.__qualname__))
    names = [m.__name__ for m in models]
    if len(set(names)) != len(names):     # the page names a type by its model's name: one each
        raise ValueError(f"two models the page reads share a name: {sorted({n for n in names if names.count(n) > 1})}")
    _, schema = models_json_schema([(m, "serialization") for m in models], title="femkit")

    def untitled(node):
        """Only a definition keeps its title: a titled property would become a type of its own.
        The keys of `properties` and `$defs` are names, never the keyword: a field named `title`
        stays."""
        if isinstance(node, list):
            return [untitled(v) for v in node]
        if not isinstance(node, dict):
            return node
        return {k: {name: untitled(s) for name, s in v.items()} if k in ("properties", "$defs") else untitled(v)
                for k, v in node.items() if k != "title"}

    defs = {name: {**untitled(d), "title": d.get("title", name)} for name, d in schema["$defs"].items()}
    return json.dumps({"title": "femkit", "$defs": defs}, indent=2, sort_keys=True) + "\n"


def icons_file() -> Path:
    """The icons the page declaration names, as one module the page imports (web.md § 8.7)."""
    return dirs.checkout() / "frontend" / "src" / "generated" / "icons.ts"


def page_icons() -> str:
    """Every icon the page declaration names — a workspace's, a kind's — imported from the icon
    set by its component's name, and keyed by the name the declaration uses."""
    from femkit import registry               # here: the registry imports this module
    p = page.load(registry.operations())
    names = sorted({w.icon for w in p.workspaces} | set(p.kinds.values()))
    component = {n: "".join(part.capitalize() for part in n.split("-")) + "Icon" for n in names}  # never a global's name
    lines = ["// generated by `python -m femkit schema docs` from femkit/data/web/page.toml -- do not edit",
             "import { " + ", ".join(sorted(set(component.values()))) + " } from \"lucide-react\";", "",
             "export const icons = {"] + [f"  {json.dumps(n)}: {component[n]}," for n in names] + ["} as const;", ""]
    return "\n".join(lines)


def _stale() -> dict[str, str]:
    """file, from the checkout -> its text, for every reference page and the page's schemas
    that differ from what the models render."""
    out = {}
    wanted = {reference_dir() / f"{name}.md": render_page(name) for name in pages()}
    wanted[schemas_file()] = page_schemas()
    wanted[icons_file()] = page_icons()
    for path, text in wanted.items():
        if read_text(path) != text:
            out[str(path.relative_to(dirs.checkout()))] = text
    return out


@operation(SCHEMA_DOCS, result=DocsOutcome, changes=True,
           subject=lambda req: [DOCS_SUBJECT])
class SchemaDocs:
    """Render docs/reference/, and the page's schemas, from the schema models; files already up to date are left alone."""

    def plan(self, req: DocsRequest, ctx: Context) -> Plan:
        stale = _stale()
        steps = tuple(Step(id=name, describe=f"write {text.path(dirs.checkout() / name)}") for name in sorted(stale))
        return Plan(steps=steps)

    def observe(self, req: DocsRequest, ctx: Context) -> dict:
        """The pages that differ from what the models render now: what the plan writes."""
        return {"stale": sorted(_stale())}

    def apply(self, plan: Plan, ctx: Context, observer) -> DocsOutcome:
        pages = _stale()
        written: list[str] = []

        def do(step: Step, where):
            path = atomic_write_text(dirs.checkout() / step.id, pages[step.id])
            written.append(str(path))
            return "done", None

        status, log = run_steps(plan, ctx, observer, do)
        return DocsOutcome(plan=plan, status=status, log=str(log), written=written)
