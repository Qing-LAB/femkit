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


def test_the_machine_a_studys_stages_are_for_is_a_context_its_choices_job_machines():
    """Fails if the page's context does not declare `target` — the machine a study's stages are
    for — its choices the records `job machines` lists, by their names, chosen apart from the
    project; or `study prep` and `study flow` do not take their `--target` from it (web.md § 8.1:
    "the machine a study's stages are for, `target`, its choices `job machines`'"; ADR 0022
    decision 5: "the page's context names the machine")."""
    ops = registry.operations()
    (target,) = [c for c in page.load(ops).context if c.key == "target"]
    assert (target.choices, target.rows, target.value_key, target.depends) == ("job.machines", "rows", "name", [])
    for name in ("study.prep", "study.flow"):
        assert ops[name].request.model_fields["target"].json_schema_extra["context"] == "target"


@pytest.mark.parametrize("old, new, where", [
    ('document = "project.graph"', 'document = "project.nowhere"', "workspaces[0].document"),  # no such operation
    ('document = "project.graph"', 'document = "study.prep"', "workspaces[0].document"),       # one that changes things
    ('rows = "studies"', 'rows = "nothing"', "context[1].rows"),                            # no such field
    ('depends = ["project"]', 'depends = ["study"]', "context[1].depends"),                 # depends on itself
    ('definition = "variable"\n', "", "kinds.object"),                                        # an object type without its icon
    ('study = "flask-conical"\n', "", "kinds.part"),                                         # a part kind without its icon
    ('crossing = "merge"\n', 'crossing = "merge"\nshape = "square"\n', "kinds.object"),   # an icon of no kind
    ('geometry = "box"\n', "", "kinds.stage"),                                               # a stage kind without its icon
    ('geometry = "box"\n', 'geometry = "box"\nsolve = "play"\n', "kinds.stage"),          # an icon of no stage kind
    ('[groups.case]\n', '[groups.nothing]\ntitle = "Nothing"\nicon = "x"\naccent = "group-x"\n\n[groups.case]\n',
     "groups.nothing"),                                                                    # a group the registry lacks
    ('[groups.case]\n', '[groups.box]\n', "groups"),                                          # a registry group with none
    ('document = "project.check"', 'document = "study.prep"', "workspaces[0].panels[1].document"),  # a panel that changes
    ('context = ["project"]\n\n[[workspaces.panels]]', 'context = ["galaxy"]\n\n[[workspaces.panels]]',
     "workspaces[0].panels[1].context[0]"),                                                 # a context undeclared
    ('value_key = "name"\ndepends = ["project"]', 'value_key = "nowhere"\ndepends = ["project"]', "context[1]"),  # no such
    # row key
    ('rows = "projects"\nvalue_key = "name"\n', 'rows = "root"\nvalue_key = "name"\n', "context[0]"),  # rows that are no records
    ('"needs attention" = "block-attention"\n', "", "shows"),                                 # a word without its color
    ('"needs attention" = "block-attention"\n', '"needs attention" = "block-attention"\nbroken = "block-broken"\n',
     "shows.broken"),                                                                    # a word of no list
])
def test_a_page_declaration_naming_what_does_not_exist_is_refused(definitions, old, new, where):
    """Fails if a declaration naming an operation that does not exist or changes things — a
    workspace's document or a panel's — a field or key its result lacks, a context it does not
    declare, or leaving a part kind, an object type or a stage kind without its icon, or giving one
    to a kind there is none of, a group of operations the registry lacks or a registry's group
    without its title, icon and accent, or a word of the vocabulary's closed list without its color,
    or a color to a word not in it, loads — the page would draw a part it cannot fill (web.md
    §§ 7.6, 8.1–8.2)."""
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
    @property
    def report(self) -> view.Report:
        return view.Report()


@operation(Verb("toy.where", Where, on_machine=False, effect="reads"), result=Nothing)
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


def test_every_model_the_page_reads_has_a_name_no_other_has():
    """Fails if two models the page reads — the vocabulary, every registered operation's result, the
    page declaration — share a name: the page names each generated type by its model's name, so
    `schema docs` could not write the page's schemas and the reference pages could not be
    regenerated (web.md § 8.7; api.md § 2.3)."""
    import json
    from femkit import reference
    defined = json.loads(reference.page_schemas())["$defs"]
    assert not [name for name in defined if "__" in name]      # a name two models share is written prefixed


def test_every_block_word_a_result_holds_is_typed_by_the_vocabularys_closed_list():
    """Fails if a field of an operation's result holding a block's word — a part's in `project
    check`, a stage's in `case list`, a node's in a graph — is typed a bare text, so the schema the
    page's types are generated from loses the closed list of words (web.md § 7.6; core.md § 7)."""
    from typing import get_args
    words = sorted(get_args(view.Shows))

    def word_fields(schema: dict) -> list[dict]:
        found = []
        for name, definition in {"": schema, **schema.get("$defs", {})}.items():
            for key, prop in definition.get("properties", {}).items():
                if key == "shows":
                    found.append(prop)
        return found

    held = {name: word_fields(op.result.model_json_schema()) for name, op in registry.operations().items()}
    assert held["project.check"] and held["case.list"] and held["study.flow"]
    for name, props in held.items():
        for prop in props:
            options = prop.get("anyOf", [prop])
            assert any(sorted(o.get("enum", [])) == words for o in options), (name, prop)


def test_the_groups_of_operations_are_the_registrys_in_the_order_of_work_each_with_its_title_icon_and_accent():
    """Fails if the declaration's groups of operations are not the registry's groups and no other,
    served in the order the declaration lists them — the person's order of work, the project's first —
    each with its title, its icon and its accent token, so the page would keep a list of operations,
    or a group, of its own (web.md § 8.1: "each of the registry's groups and no other … in the order
    the declaration lists them — the person's order of work"; § 10.2)."""
    groups = page.load(registry.operations()).groups
    assert set(groups) == set(registry.GROUPS)
    assert all(g.title and g.icon and g.accent for g in groups.values())
    assert len({g.accent for g in groups.values()}) == len(groups)


def test_every_part_kind_object_type_and_stage_kind_has_its_icon_keyed_by_its_family():
    """Fails if the kinds' icons are not keyed by a node's family and kind — each part kind and
    object type of the layout, each stage kind of `stages.toml` — so the mesh recipe and the mesh
    stage, each of the kind `mesh`, could not each have its own icon (web.md § 8.1: "one for each
    part kind, object type and stage kind, keyed by the node's `family` and `kind`")."""
    from femkit.definitions import catalogue
    from femkit.projects import layout
    kinds, read = page.load(registry.operations()).kinds, layout.read()
    assert (set(kinds["part"]), set(kinds["object"]), set(kinds["stage"])) == (
        set(read.kinds), set(read.objects), set(catalogue.load_stages().kinds))
    assert kinds["part"]["mesh"] != kinds["stage"]["mesh"]


# ------------------------------------------------------------------ the theme (web.md § 10)

def test_the_shipped_theme_loads_and_names_every_colour_the_declaration_names():
    """Fails if the theme femkit ships does not load — a colour that resolves to nothing, a space off
    the 4px grid — or a group's accent, a block word's colour or a severity's colour the declaration
    names is no colour of it: the page would draw a part with a token no stylesheet defines (web.md
    §§ 8.1, 10.1)."""
    theme, declared = page.load_theme(), page.load(registry.operations())
    named = {g.accent for g in declared.groups.values()} | set(declared.shows.values()) \
        | {s.color for s in declared.severities.values()}
    assert named <= set(theme.color.theme)


def _luminance(hex_: str) -> float:
    """WCAG 2.2's relative luminance of an opaque colour (its definition of "relative luminance")."""
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(int(hex_[i:i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_every_text_on_its_surface_and_every_block_word_and_accent_meets_wcag_aa_in_each_theme():
    """Fails if a text colour on a surface the theme says it is read on, or a block word's colour on
    its block, or a group's accent where it bands its operations, is under WCAG 2.2 AA in any theme
    theme.toml declares — 4.5:1 for text (1.4.3), 3:1 for a graphic (1.4.11) — computed here from
    theme.toml with WCAG's own formula (web.md § 10.2: "every pair of a text and its surface, and every
    block word's color on its block, meets WCAG AA contrast in both")."""
    import tomllib
    whole = tomllib.loads(page.theme_path().read_text(encoding="utf-8"))
    data, themes = whole["color"], list(whole["themes"])
    scale, shades = data["scale"], data["theme"]

    def colour(name: str, side: str) -> str:
        written = shades[name][side]
        return scale.get(written, written)

    for kind, least in (("text", 4.5), ("graphic", 3.0)):
        for fore, backs in data["contrast"][kind].items():
            for back in backs:
                for side in themes:
                    high, low = sorted((_luminance(colour(fore, side)), _luminance(colour(back, side))), reverse=True)
                    assert (high + 0.05) / (low + 0.05) >= least, (kind, fore, back, side)


@pytest.mark.parametrize("file, old, new, where", [
    ("theme.toml", 'text-faint = { light = "slate-500"', 'text-faint = { light = "slate-300"',
     "color.contrast.text.text-faint[0]"),                                        # a text too faint on its surface
    ("theme.toml", 'canvas = { light = "slate-50"', 'canvas = { light = "slate-55"', "color.theme.canvas.light"),
    ("theme.toml", "\n3 = 12\n", "\n3 = 14\n", "space.3"),                               # a space off the 4px grid
    ("theme.toml", 'color = "shadow-strong" }]\n\n[layer.sticky]', 'color = "smoke" }]\n\n[layer.sticky]',
     "layer.lifted.shadow[1].color"),                                             # a shadow of no colour
    ("page.toml", 'accent = "group-study"', 'accent = "group-studies"', "groups.study.accent"),  # no such token
    ("page.toml", '"needs update" = "block-update"', '"needs update" = "block-updated"', 'shows."needs update"'),
    ("page.toml", '[[themes]]\ntitle = "System"', '[[themes]]\ntheme = "light"\ntitle = "System"', "themes"),  # no system's
    ("page.toml", '[[themes]]\ntheme = "dark"', '[[themes]]\ntheme = "dusk"', "themes"),      # a theme theme.toml lacks
    ("theme.toml", 'canvas = { light = "slate-50", dark = "slate-950" }', 'canvas = { light = "slate-50" }',
     "color.theme.canvas"),                                                      # a colour not given for each theme
    ("page.toml", 'failed = "error"\nkilled', 'failed = "errors"\nkilled', "outcomes.failed"),  # no such token
    ("page.toml", 'running = "accent"\n', "", "outcomes"),                       # a step word without its colour
    ("page.toml", '[sections.Physics]\ncolour = "section-physics"\nshape = "round"\nicon = "atom"\n', "",
     "sections"),                                                                 # a section without its look
    ("page.toml", '[sections.Results]\n', '[sections.Library]\ncolour = "section-results"\nshape = "round"\n'
     'icon = "gauge"\n\n[sections.Results]\n', "sections.Library"),              # a look for no section
    ("page.toml", 'colour = "section-physics"', 'colour = "accent-soft"', "sections.Physics.colour"),  # no contrast
    ("page.toml", 'colour = "section-physics"\nshape = "round"', 'colour = "section-physics"\nshape = "blob"',
     "sections.Physics.shape"),                                                   # a shape of no closed list
    ("page.toml", '[stages.mesh]\ncolour = "stage-mesh"\nshape = "notch"\nicon = "grid-2x2"\n', "",
     "stages"),                                                                   # a stage kind without its look
    ("page.toml", 'observables = "wire-observables"\n', "", "wires"),             # a part kind a wire carries, none
    ("page.toml", '"geometry/brep" = "wire-geometry"\n', "", "wires"),            # an artifact type without one
    ("page.toml", 'definition = "wire-definition"\n', 'definition = "wire-definition"\nnothing = "wire-definition"\n',
     "wires.nothing"),                                                            # a colour for what nothing carries
    ("page.toml", 'tags = [', 'tags = []\nwas = [', "tags"),                     # no colour for a box's tag
    ("page.toml", 'running = "accent"', 'running = "accent-soft"', "outcomes.running"),   # held to no contrast
    ("page.toml", 'families = ["stage"]', 'families = ["stage", "part"]', "workspaces"),  # a family drawn twice
    ("page.toml", 'line = "{file}, line {line}"', 'line = "{file}"', "says.line"),        # a template missing a value
    ("page.toml", 'first = "docs/README.md"', 'first = "docs/NOWHERE.md"', "documents.first"),  # no such document
    ("page.toml", 'from = "planned"\non = "apply"\nto = "applying"', 'from = "planned"\non = "apply"\nto = "flying"',
     "action.transitions[17].to"),                                                # a move to no state
    ("page.toml", 'document = "project.graph"\ncontext = ["project"]',
     'document = "project.graph"\ncontext = ["project", "target"]',
     "workspaces[0].context"),                                                    # a context its document takes not
    ("page.toml", '[controls.copy]\nlabel = "Copy"\nicon = "copy"\nhelp = "Copy the line, to paste it into a shell."\n',
     "", "controls"),                                                                      # a control without words
    ("page.toml", 'none = "—"\n', "", "says"),                                             # a sentence not written
    ("page.toml", 'first = "project.new"', 'first = "project.newest"', "workspaces[0].first"),
    ("page.toml", 'cards = "project"', 'cards = "galaxy"', "workspaces[0].landing.cards"),        # no such context
    ("page.toml", 'last lines."\ncontext = []\n', 'last lines."\ncontext = []\nshows = "issues"\n',
     "workspaces[0].panels[3].shows"),                                                      # findings of no document
    ("page.toml", '# its findings alone: each part\'s state is the graph\'s\nshows = "issues"',
     'shows = "parts"', "workspaces[0].panels[1].shows"),                                   # a document's parts listed
    ("page.toml", 'listed = "project"', 'listed = "galaxy"', "canvas.listed"),          # a master list of no part kind
    ("page.toml", 'cards = ["definition"]', 'cards = ["definition", "galaxy"]', "canvas.cards[1]"),  # no object type
    ("page.toml", 'detail = "studies"', 'detail = "planets"', "workspaces[0].landing.detail"),     # no such row key
    ("page.toml", 'starts = "source"', 'starts = "name"', "workspaces[0].landing.starts"),         # a field of no choices
    ("page.toml", 'language = "python"', 'language = "toml"', "editor.languages"),     # one language declared twice
    ("page.toml", 'files = ["*.py"]', 'files = []', "editor.languages[1].files"),     # a language reading no file
])
def test_a_theme_or_declaration_whose_values_do_not_hold_is_refused(definitions, file, old, new, where):
    """Fails if a theme loads with a pair of a text and its surface under WCAG AA, a colour naming no
    colour of its scale or not given for each of its themes, a space off the 4px grid or a shadow of no
    colour; or a declaration loads naming a colour token the theme lacks or one held to no contrast, a
    step word, a part kind or an artifact type a wire carries without its colour, a section of the
    layout or a stage kind without its colour, shape and icon, a look for no section, a shape off its
    closed list, a colour for what no wire carries, no colour for a box's tag,
    its switch not the system's then each theme of
    theme.toml, a family two workspaces draw, a template sentence missing a placeholder, a first
    document that is no file, an action machine moving to no state, a workspace needing a context its
    document does not take, a control of the page's without its words, a sentence of the page's unwritten, a
    first step that is no operation, a panel showing the findings of no document, a panel of a document listing
    the parts its workspace's graph holds, a part kind the canvas lists, or an object type it draws as
    cards of their own, that the layout lacks, or a landing whose cards are no context's choices, whose detail no
    key of their rows, or whose starts no field of the first step's naming declared choices, or an
    editor language declared twice or reading no file — the page would draw what no token, word or
    choice defines, or a file in two languages (web.md §§ 8.1, 9.2, 10.1–10.2, 11)."""
    from tests.kit import rewrite
    rewrite(definitions / "web" / file, old, new)
    with pytest.raises(DefinitionError) as refused:
        page.load(registry.operations())
    assert where in [p for p, _ in refused.value.problems]


@pytest.mark.parametrize("old, new, where", [
    ('wire = [\n    "{target} names {source_port} of {source} at {key}",\n'
     '    "{target} names {type} {source} at {key}",\n    "{target} takes {type} from {source}",\n]\n',
     "", "sentences"),                                     # a wire's sentences not given: said at their table
    ('"{target} takes {type} from {source}"', '"{target} takes {type} from {source} by {route}"',
     "sentences.wire[2]"),                                                     # a placeholder no wire holds
    ('"{target} takes {type} from {source}"', '"{target} takes {type} from {source}, checked {checked}"',
     "sentences.wire[2]"),                                                     # a field that holds no text
    ('    "{target} takes {type} from {source}",\n', "", "sentences.wire"),  # a wire of no address said by none
    ('port = ["{name} → {names}", "{name}"]', 'port = ["{name} → {names}"]', "sentences.port"),  # a port naming none
])
def test_a_declaration_whose_canvas_sentences_leave_a_wire_or_a_port_unsaid_is_refused(definitions, old, new, where):
    """Fails if the declaration loads without the sentences the canvas says each wire and each port
    of an opened block in, with a placeholder that names no field of the vocabulary's `Wire` or
    `GraphPort` holding a text, or with a list whose last template names a field not every wire or
    port holds — a wire of no address, an artifact flowing, or a port naming nothing would be said in
    no sentence, or the page would write its own (web.md § 8.1: "every word the page says of its own
    … so no sentence is written in its code"; § 7.6: a wire's `address` for a reference alone)."""
    from tests.kit import rewrite
    rewrite(definitions / "web" / "page.toml", old, new)
    with pytest.raises(DefinitionError) as refused:
        page.load(registry.operations())
    assert where in [p for p, _ in refused.value.problems]


def test_the_tokens_are_what_the_theme_and_the_declaration_give():
    """Fails if the page's `tokens.css` differs from what theme.toml and page.toml give — a token
    written or changed by hand, or a theme changed without `schema docs` — so the page would draw
    with values no definition holds (web.md § 10.1: "generated from `theme.toml` ... never written by
    hand"; § 8.7)."""
    from femkit import reference
    assert reference.tokens_file().read_text(encoding="utf-8") == reference.page_tokens(), \
        "frontend/src/generated/tokens.css is stale: run `femkit schema docs`"


def test_the_tokens_give_each_colour_for_each_theme_and_bind_every_declared_word_to_its_token():
    """Fails if the page's sheet of tokens gives a colour of the theme in one theme and not another,
    leaves a duration under reduced motion, or leaves a block word, a group of operations, a severity, a
    step word, a section, a stage kind, what a wire carries or a box's tag unbound to the token the
    declaration names — an element showing it
    would be drawn without its colour or its look (web.md §§ 2.2, 7.6, 8.1, 10.1–10.2)."""
    theme, declared = page.load_theme(), page.load(registry.operations())
    sheet = page.sheet(theme, declared)
    assert set(sheet.colours) == set(theme.themes) and sheet.default == next(iter(theme.themes))
    for colours in sheet.colours.values():
        assert set(colours) == {f"--color-{n}" for n in theme.color.theme}
    assert set(sheet.reduced) == {f"--motion-{n}" for n in theme.motion.duration}
    bound = {(b.attribute, b.value): b.token for b in sheet.bindings}
    wanted = {("shows", w): v for w, v in declared.shows.items()} \
        | {("group", g): v.accent for g, v in declared.groups.items()} \
        | {("severity", s): v.color for s, v in declared.severities.items()} \
        | {("outcome", w): v for w, v in declared.outcomes.items()} \
        | {("section", k): v.colour for k, v in declared.sections.items()} \
        | {("stage", k): v.colour for k, v in declared.stages.items()} \
        | {("wire", k): v for k, v in declared.wires.items()} \
        | {("tag", str(i)): v for i, v in enumerate(declared.tags)}
    assert bound == wanted


def test_the_action_machine_reaches_each_state_from_its_start_and_every_run_can_end():
    """Fails if the declared action machine holds a state no move reaches from its start, or one from
    which no move leads to a state that shows an outcome, a refusal, a defect or a lost server — an
    action could never be shown, or never end (web.md § 9.1; framework.md § 3: one closed table)."""
    machine = page.load(registry.operations()).action
    moves: dict[str, set[str]] = {}
    for m in machine.transitions:
        moves.setdefault(m.source, set()).add(m.to)

    def reach(start: str) -> set[str]:
        seen, todo = {start}, [start]
        while todo:
            for n in moves.get(todo.pop(), ()):
                if n not in seen:
                    seen.add(n)
                    todo.append(n)
        return seen

    keys = {s.key for s in machine.states}
    assert reach(machine.start) == keys
    ends = {s.key for s in machine.states if s.shows in ("outcome", "refusal", "defect", "lost")}
    assert all(reach(s) & ends for s in keys - ends - {machine.start})
