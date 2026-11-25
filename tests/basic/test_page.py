"""The page declaration (web.md § 8.1)."""

from __future__ import annotations

import pytest

from pydantic import Field

from tests.kit import refused, rewrite
from femkit import page, registry
from femkit.core.operations import Result, operation
from femkit.core.schema import DefinitionError, Model
from femkit.core import view
from femkit.core.view import Verb


def test_the_shipped_page_declaration_loads():
    """Fails if the page femkit ships names something that does not exist (web.md § 8.1)."""
    assert page.load(registry.operations()).workspaces


@pytest.mark.parametrize("old, new, where", [
    ('document = "project.graph"', 'document = "project.nowhere"', "workspaces[0].document"),  # no such operation
    ('document = "project.graph"', 'document = "study.expand"', "workspaces[0].document"),     # one that changes things
    ('rows = "studies"', 'rows = "nothing"', "context[1].rows"),                            # no such field
    ('depends = ["project"]', 'depends = ["study"]', "context[1].depends"),                 # depends on itself
    ('parameter = "variable"\n', "", "kinds"),                                               # an object type without its icon
    ('study = "flask-conical"\n', "", "kinds"),                                              # a part kind without its icon
    ('crossing = "merge"\n', 'crossing = "merge"\nshape = "square"\n', "kinds"),          # an icon of no kind
    ('value_key = "name"\ndepends = ["project"]', 'value_key = "nowhere"\ndepends = ["project"]', "context[1]"),  # no such
    # row key
    ('rows = "projects"\nvalue_key = "name"\n', 'rows = "root"\nvalue_key = "name"\n', "context[0]"),  # rows that are no records
])
def test_a_page_declaration_naming_what_does_not_exist_is_refused(definitions, old, new, where):
    """Fails if a declaration naming an operation that does not exist or changes things, a field
    or key its result lacks, a context it does not declare, or leaving a part kind or an object
    type of the layout without its icon, or giving one to a kind the layout lacks, loads — the page
    would draw a part it cannot fill (web.md §§ 8.1–8.2)."""
    copy = definitions / "web" / "page.toml"           # the test's own copy, by the path it was given
    text = copy.read_text(encoding="utf-8")
    assert old in text
    copy.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(DefinitionError) as refused:
        page.load(registry.operations())
    assert where in [p for p, _ in refused.value.problems]


class Where(Model):
    where: str = Field(description="a context the page does not declare", json_schema_extra={"context": "galaxy"})


class Nothing(Result):
    def report(self) -> view.Report:
        return view.Report()


@operation(Verb("toy.where", Where), result=Nothing)
def toy_where(req: Where, ctx) -> Nothing:
    """An operation whose field takes a context the page does not declare."""
    return Nothing()


def test_a_request_field_taking_a_context_the_page_does_not_declare_is_refused():
    """Fails if the declaration loads beside an operation whose field takes a context it does not
    declare: that field's form could never start from the page's context (web.md § 8.1)."""
    with pytest.raises(DefinitionError) as refused:
        page.load({**registry.operations(), toy_where.name: toy_where})
    assert "context" in [p for p, _ in refused.value.problems]


def test_the_page_declaration_is_refused_while_the_layout_whose_kinds_it_draws_does_not_load(definitions):
    """Fails if the declaration loads while the project layout does not, each kind's icon then
    checked against nothing (web.md § 8.2: each part kind and object type of the layout has its
    icon)."""
    layout = definitions / "project" / "layout.toml"
    rewrite(layout, 'folder = "physics"', 'folder = "studies"')       # two kinds on one folder
    with refused(DefinitionError, "definition-invalid", str(layout)):
        page.load(registry.operations())
