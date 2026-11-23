"""The `model` verbs (models.md § 11.1)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from femkit.core import text
from femkit.core.issues import Issue
from femkit.core.operations import Context, Result, operation
from femkit.core.schema import Model
from femkit.definitions import catalogue
from femkit.models import check
from femkit.models.project import load_model


class ProjectRequest(Model):
    """Which project."""

    project: Path = Field(Path("."), description="the project's folder, holding model.toml")


class CheckResult(Result):
    project: str = Field(description="the project checked")

    def text(self) -> str:
        if not self.issues:
            return f"{self.project}: the model is complete; nothing its formulation refuses"
        lines = [f"{self.project}: {text.count(len(self.issues), 'finding')}"]
        for issue in self.issues:
            lines += text.findings([issue.model_copy(update={"message": f"{issue.subject} {issue.message}"})])
        return "\n".join(lines)


@operation("model.check", request=ProjectRequest, result=CheckResult)
def model_check(req: ProjectRequest, ctx: Context) -> CheckResult:
    """Every rule of the model and its formulation but region coverage, which needs the
    geometry built; changes nothing (models.md § 3, § 11.2)."""
    project = req.project.expanduser().resolve()
    model = load_model(project, ctx)
    issues: list[Issue] = check.findings(model, catalogue.formulations(ctx), catalogue.units(ctx))
    return CheckResult(project=str(project), issues=issues)
