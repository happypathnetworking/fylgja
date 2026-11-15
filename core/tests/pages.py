"""What the tests of the user documentation share: the pages' paths, and the readers of their Markdown.

A page is held to the code by tables whose header's first cell is fixed (`Command`, `Option`, `Variable`,
`Status`, ...): `rows` finds one by that cell, and the test compares what it lists with the code's, as sets, both
ways. Each reader's `tests/test_docs.py` states `options` again, since a reader's tests import nothing of the core's.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

USER_PAGES: tuple[str, ...] = ("docs/installing.md", "docs/cli.md", "docs/server.md", "docs/api.md", "docs/client.md",
              "docs/demonstrations.md")
"""The pages a user reads, as paths from the repository's root, grown by the task that writes each."""


def text(path: str) -> str:
    """A page's text; `path` is from the repository's root."""
    return (ROOT / path).read_text()


def _level(line: str) -> int:
    """The depth of a Markdown heading line, 0 for any other."""
    match = re.match(r"(#{1,6}) ", line)
    return len(match.group(1)) if match else 0


_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


class _Fences:
    """Which lines of a page are inside a fenced code block: a fence of three or more backticks or tildes, indented
    or not, closed by one of the same character at least as long with nothing after it."""

    def __init__(self) -> None:
        self.open: tuple[str, int] | None = None

    def step(self, line: str) -> str | None:
        """Feed a line; the info string when it opens a block, "" when it closes one, None for any other line."""
        match = _FENCE.match(line)
        if self.open is None:
            if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
                self.open = (match.group(1)[0], len(match.group(1)))
                return match.group(2).strip()
        elif match and match.group(1)[0] == self.open[0] and len(match.group(1)) >= self.open[1] \
                and not match.group(2).strip():
            self.open = None
            return ""
        return None


def section(text: str, heading: str) -> list[str]:
    """The lines under `heading`, a whole heading line, to the next heading of its level or a higher one. A `#` inside
    a code block is no heading."""
    lines = text.splitlines()
    start = lines.index(heading) + 1
    level = _level(heading)
    found: list[str] = []
    fences = _Fences()
    for line in lines[start:]:
        was_open = fences.open is not None
        fences.step(line)
        if not was_open and fences.open is None and 0 < _level(line) <= level:
            break
        found.append(line)
    return found


def _cells(line: str) -> list[str]:
    """A table row's cells: split on a `|` that is neither escaped nor inside backticks, `\\|` unescaped."""
    cells: list[str] = []
    current: list[str] = []
    ticks = False
    k = 0
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    while k < len(body):
        ch = body[k]
        if ch == "\\" and body[k + 1:k + 2] == "|":
            current.append("|")
            k += 1
        elif ch == "`":
            ticks = not ticks
            current.append(ch)
        elif ch == "|" and not ticks:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        k += 1
    cells.append("".join(current).strip())
    return cells


def rows(lines: list[str], first: str) -> list[list[str]]:
    """The cells of each row of the table among `lines` whose header's first cell is `first`, header and rule left
    out. A pipe in backticks or escaped is part of its cell, and a row may have an empty first cell."""
    found: list[list[str]] = []
    inside = False
    for line in lines:
        if not line.startswith("|"):
            if inside:
                break
            continue
        cells = _cells(line)
        if not inside:
            inside = bool(cells) and cells[0] == first
            continue
        if not all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
            found.append(cells)
    return found


def blocks(text: str) -> list[tuple[str, list[str]]]:
    """Each fenced code block of `text`: its info string and its lines."""
    found: list[tuple[str, list[str]]] = []
    info = ""
    body: list[str] = []
    fences = _Fences()
    for line in text.splitlines():
        opened = fences.step(line)
        if opened is not None and fences.open is not None:
            info, body = opened, []
        elif opened is not None:
            found.append((info, body))
        elif fences.open is not None:
            body.append(line)
    return found


def ticked(cell: str) -> list[str]:
    """The backticked spans of a cell."""
    return re.findall(r"`([^`]+)`", cell)


def flags(text: str) -> set[str]:
    """The `--long-option` tokens of `text`."""
    return set(re.findall(r"--[a-z][a-z0-9-]*", text))


def options(parser: argparse.ArgumentParser) -> dict[tuple[str, ...], frozenset[str]]:
    """Each path of subcommands from the root, `()` the root, to its long options, `--help` left out. A path with
    subcommands under it is a node, and its own options are under its key."""
    found: dict[tuple[str, ...], frozenset[str]] = {}

    def walk(path: tuple[str, ...], current: argparse.ArgumentParser) -> None:
        longs: set[str] = set()
        for action in current._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    walk((*path, name), sub)
            else:
                longs |= {o for o in action.option_strings if o.startswith("--") and o != "--help"}
        found[path] = frozenset(longs)

    walk((), parser)
    return found


def statuses(lines: list[str]) -> set[int]:
    """The exit statuses the `Status` table among `lines` lists: its first cells."""
    return {int(row[0].strip("`")) for row in rows(lines, "Status")}


def targets() -> frozenset[str]:
    """The `Makefile`'s `.PHONY` names, a continued line joined."""
    lines = (ROOT / "Makefile").read_text().splitlines()
    names: list[str] = []
    k = 0
    while k < len(lines):
        if lines[k].startswith(".PHONY:"):
            joined = lines[k][len(".PHONY:"):]
            while joined.endswith("\\"):
                k += 1
                joined = joined[:-1] + " " + lines[k]
            names += joined.split()
        k += 1
    return frozenset(names)
