"""The checks every user page shares: each command line a page gives is parsed by the CLI's own parser, each make
target a page names exists, and no page cites a decision or a phase. What one page lists is held by the page's own
test (`test_docs_cli.py`)."""

from __future__ import annotations

import re
import shlex

import pytest
from pages import DOCS, ROOT, USER_PAGES, blocks, flags, options, prose, rows, section, targets, text

from fylgja_core import cli

PROG = "fylgja-core"


def _command_lines(page: str) -> list[str]:
    """The lines of a page's `sh` and `console` blocks that give a `fylgja-core` command, a console prompt left off."""
    found: list[str] = []
    for info, lines in blocks(text(page)):
        if info in ("sh", "console"):
            for line in lines:
                if info == "console" and not line.startswith("$ "):
                    continue  # a console block's other lines are the command's output
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
    union: set[str] = set()
    for page in USER_PAGES:
        body = text(page)
        named = {m.group(1) for span in re.findall(r"`([^`]+)`", body) if (m := re.match(r"make ([\w-]+)", span))}
        for info, lines in blocks(body):
            if info in ("sh", "console"):
                named |= {m.group(1) for line in lines if (m := re.match(r"(?:\$ )?make ([\w-]+)", line))}
        assert named <= targets(), f"{page}: no such make target: {sorted(named - targets())}"
        union |= named
    assert union, "the parse is blind"


def test_no_user_page_cites_a_decision_number_or_a_phase() -> None:
    """Outside a line that begins "Why it is so", which links `design/`."""
    assert USER_PAGES, "the parse is blind"
    for page in USER_PAGES:
        for number, line in enumerate(text(page).splitlines(), 1):
            if line.startswith("Why it is so"):
                continue
            assert not re.search(r"D-\d{3}|[Pp]hase \d", line), f"{page}:{number}: {line}"


def test_a_table_row_keeps_a_pipe_in_backticks_or_escaped_and_an_empty_first_cell() -> None:
    lines = ["| Status | Means |", "|:--|---|", "| `a|b` | x \\| y |", "|  | empty first |", "| 2 | ` | ` and `c` |"]
    assert rows(lines, "Status") == [["`a|b`", "x | y"], ["", "empty first"], ["2", "` | ` and `c`"]]
    assert rows(lines, "Other") == []


def test_a_fence_is_found_indented_and_longer_and_closed_only_by_one_as_long() -> None:
    page = "\n".join(["# T", "", "  ````sh", "```", "# not a heading", "````", "", "~~~console", "$ x", "~~~", "",
                      "## Next", "text"])
    assert blocks(page) == [("sh", ["```", "# not a heading"]), ("console", ["$ x"])]
    assert section(page, "# T") == page.splitlines()[1:]
    assert section(page, "## Next") == ["text"]
    assert prose(page) == ["# T", "", "", "", "## Next", "text"]


def _relative_links(page: str) -> set[str]:
    """The relative link targets of a page, an anchor and a query cut off, a link inside code left out."""
    body = "\n".join(prose(text(page)))
    body = re.sub(r"`[^`\n]*`", "", body)
    targets_ = re.findall(r"\]\(([^)\s]+)", body)
    return {t.split("#")[0] for t in targets_ if not re.match(r"[a-z][a-z0-9+.-]*:", t) and t.split("#")[0]}


def test_the_index_links_every_page_under_docs() -> None:
    pages = {path.name for path in DOCS.glob("*.md")} - {"README.md"}
    assert pages, "the parse is blind"
    assert pages <= _relative_links("docs/README.md")


def test_the_index_links_what_it_lists_that_exists() -> None:
    links = _relative_links("docs/README.md")
    assert links, "the parse is blind"
    for link in links:
        assert (DOCS / link).resolve().exists(), link
        assert (DOCS / link).resolve().is_relative_to(ROOT)


def test_the_readme_links_the_index_and_each_page_a_user_starts_from() -> None:
    links = _relative_links("README.md")
    assert links, "the parse is blind"
    assert {"docs/README.md", "docs/installing.md", "docs/demonstrations.md"} <= links
    assert {"readers/infrahub/README.md", "readers/netbox/README.md", "docs/integrating.md"} <= links


def test_the_index_gives_the_six_pages_in_reading_order_and_then_the_rest() -> None:
    lines = text("docs/README.md").splitlines()
    numbered = [m.group(1) for line in lines if (m := re.match(r"\d+\. \[[^\]]+\]\(([^)#\s]+)", line))]
    assert numbered == ["installing.md", "server.md", "cli.md", "api.md", "client.md", "demonstrations.md"]
    beside = lines[lines.index("Beside them:"):]
    rest = [t for t in re.findall(r"\]\(([^)#\s]+)", "\n".join(beside))]
    assert {"rules.md", "glossary.md", "integrating.md", "../readers/infrahub/README.md",
            "../readers/netbox/README.md", "../formats/README.md", "../psp/README.md"} <= set(rest)
    assert not set(numbered) & set(rest)
