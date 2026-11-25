"""The user manual held to femkit (docs/README.md § 3.1, M4; testing.md § 3): every example a
chapter marks as run prints what the chapter shows, run as the person types it — through the
`femkit` command, in the folder the session is in, in the chapter's order, in one session with a
home folder and a projects root of its own; every command and option a code block of the manual names is one femkit
has; every command femkit has is in a code block of the manual; every link of the manual resolves.
How a chapter marks what runs, and the three things of femkit's output it shows otherwise than
printed, each because it differs between two runs, are tools/manual.py's docstring."""

from __future__ import annotations

import difflib
import os
import re

import pytest

from tests import kit
from tools import manual

CHAPTERS = manual.chapters()


def named(words: list[str]) -> tuple[tuple[str, ...] | None, str | None]:
    """The command ``words`` name — none for a group's or femkit's own `--help` — and what is
    wrong with them: a command femkit lacks, or an option its command does not take."""
    every = kit.commands()
    path: tuple[str, ...] = ()
    for word in words:
        if not any(c[:len(path) + 1] == (*path, word) for c in every):
            break
        path = (*path, word)
        if path in every:
            break
    rest = words[len(path):]
    if path not in every:
        if rest in ([], ["--help"]) and any(c[:len(path)] == path for c in every):
            return None, None
        return None, f"`{' '.join(words)}` names no command of femkit's"
    unknown = [w for w in rest if w.startswith("-") and w.split("=")[0] not in every[path]]
    return path, (f"`{' '.join(path)}` takes no {', '.join(unknown)}" if unknown else None)


def typed() -> list[tuple[str, int, str, list[str]]]:
    """Every femkit command a code block of the manual names: its file, its line, the line, and
    its words after `femkit`."""
    return [(path.name, n, line, words) for path in manual.documents()
            for n, line in manual.shell_lines(path) for words in manual.commands(line)]


@pytest.mark.parametrize("chapter", CHAPTERS, ids=[c.stem for c in CHAPTERS])
def test_every_example_prints_what_the_manual_shows(chapter):
    """Fails if an example a chapter marks as run — each typed line of a console block, run in the
    chapter's order in one session, the files the story writes or changes changed between them —
    prints other than the chapter shows under it, or cannot run as the chapter writes it (docs/
    README.md § 3.1, M4: "Every example marked as run is run by the basic tests in a temporary
    projects root, in its chapter's order, and must print what the manual shows")."""
    ran = manual.run(chapter, dict(os.environ))
    assert ran, f"{chapter.name} runs no example"
    wrong = [e for e in ran if not manual.same(e.shown, e.printed)]
    assert not wrong, "\n\n".join(
        f"{e.file.name}:{e.line}: $ {e.typed}\n" + "\n".join(
            difflib.unified_diff(e.shown, e.printed, "the manual shows", "femkit prints", lineterm=""))
        for e in wrong)


def test_every_command_and_option_the_manual_names_is_one_femkit_has():
    """Fails if a code block of the manual — a typed line of a console block, or a line of a bash
    block, the install script's verb read as the `env` command it forwards to — names a command
    femkit does not have, or an option its command does not take (docs/README.md § 3.1, M4:
    "every command and option the manual names exists")."""
    wrong = [f"{name}:{n}: {problem}" for name, n, line, words in typed() if (problem := named(words)[1])]
    assert not wrong, "\n".join(wrong)


def test_every_command_femkit_has_appears_in_the_manual():
    """Fails if a command femkit's command line has is named in no code block of the manual, so a
    new command without its place in the manual is seen (docs/README.md § 3.1, M4: "every command
    femkit has appears in it")."""
    shown = {path for _, _, _, words in typed() if (path := named(words)[0])}
    missing = sorted(" ".join(c) for c in set(kit.commands()) - shown)
    assert not missing, "in no code block of docs/manual/: " + ", ".join(missing)


def test_every_link_in_the_manual_resolves():
    """Fails if a link of the manual, outside its code, names a file of the repository that is not
    there, or a section by a `#` anchor, which a heading's change breaks unseen (docs/README.md
    § 3.1, M4: "every link resolves"; § 2, D6)."""
    wrong = []
    for path in manual.documents():
        for n, target in manual.links(path):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):  # another site: not this repository's
                continue
            if "#" in target:
                wrong.append(f"{path.name}:{n}: {target} names a section by its anchor; name it in plain text (D6)")
            elif not (path.parent / target).exists():
                wrong.append(f"{path.name}:{n}: {target} is not there")
    assert not wrong, "\n".join(wrong)


def test_a_typed_femkit_line_runs_through_the_femkit_command_in_any_folder(tmp_path):
    """Fails if the manual's runner cannot run a typed `femkit …` line, or runs it other than
    through a `femkit` command — the one the install script writes, from the same source — that
    runs femkit from the checkout in whatever folder the session is in, even one holding a
    `femkit` folder of the person's own, as the person's does (docs/README.md § 3.1, M4; envs.md
    § 7)."""
    chapter = tmp_path / "1-story.md"
    chapter.write_text("```console\n$ femkit --help\n```\n\n"
                       "<!-- write ~/elsewhere/femkit/__main__.py -->\n```python\nprint('not femkit')\n```\n\n"
                       "```console\n$ cd ~/elsewhere\n$ femkit --help\n```\n", encoding="utf-8")
    ran = manual.run(chapter, dict(os.environ))
    assert ran[0].printed[:1] == ["Usage: femkit [OPTIONS] COMMAND [ARGS]..."], "\n".join(ran[0].printed)
    assert ran[-1].printed == ran[0].printed, "\n".join(ran[-1].printed)
