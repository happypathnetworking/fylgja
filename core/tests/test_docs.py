"""The checks every user page shares: each command line a page gives is parsed by the CLI's own parser, each make
target a page names exists, and no page cites a decision or a phase. What one page lists is held by the page's own
test (`test_docs_cli.py`)."""

from __future__ import annotations

import re
import shlex

import pytest
from pages import USER_PAGES, blocks, flags, options, targets, text

from fylgja_core import cli

PROG = "fylgja-core"


def _command_lines(page: str) -> list[str]:
    """The lines of a page's `sh` and `console` blocks that give a `fylgja-core` command, a console prompt left off."""
    found: list[str] = []
    for info, lines in blocks(text(page)):
        if info in ("sh", "console"):
            for line in lines:
                line = line.removeprefix("$ ")
                if line.startswith(PROG + " "):
                    found.append(line)
    return found


def _path(argv: list[str], known: set[tuple[str, ...]]) -> tuple[str, ...]:
    """The command an argument vector names: the longest run of subcommand words, options before them passed over."""
    path: tuple[str, ...] = ()
    for word in argv:
        if word.startswith("-"):
            continue
        if (*path, word) not in known:
            break
        path = (*path, word)
    return path


def test_every_command_line_a_page_gives_parses() -> None:
    """Each line, its brackets taken out and its placeholders kept, is parsed by the real parser; each `--` token is
    an option of its command whole, since argparse accepts an abbreviation. `--version` and `--help` lines answer and
    exit, and are left out."""
    held = options(cli._parser())
    known = set(held)
    seen = 0
    for page in USER_PAGES:
        for line in _command_lines(page):
            argv = shlex.split(line.replace("[", "").replace("]", ""))[1:]
            if "--version" in argv or "--help" in argv or "-h" in argv:
                continue
            seen += 1
            try:
                cli._parser().parse_args(argv)
            except SystemExit:
                pytest.fail(f"{page}: the parser refuses `{line}`")
            path = _path(argv, known)
            assert flags(" ".join(argv)) <= held[path] | held[()], f"{page}: `{line}` names an option by part"
    assert seen, "the parse is blind"


def test_every_make_target_a_page_names_exists() -> None:
    assert {"venv", "test"} <= targets(), "the parse is blind"
    for page in USER_PAGES:
        body = text(page)
        named = {m.group(1) for span in re.findall(r"`([^`]+)`", body) if (m := re.match(r"make ([\w-]+)", span))}
        for info, lines in blocks(body):
            if info in ("sh", "console"):
                named |= {m.group(1) for line in lines if (m := re.match(r"(?:\$ )?make ([\w-]+)", line))}
        assert named <= targets(), f"{page}: no such make target: {sorted(named - targets())}"


def test_no_user_page_cites_a_decision_number_or_a_phase() -> None:
    """Outside a line that begins "Why it is so", which links `design/`."""
    assert USER_PAGES, "the parse is blind"
    for page in USER_PAGES:
        for number, line in enumerate(text(page).splitlines(), 1):
            if line.startswith("Why it is so"):
                continue
            assert not re.search(r"D-\d{3}|[Pp]hase \d", line), f"{page}:{number}: {line}"
