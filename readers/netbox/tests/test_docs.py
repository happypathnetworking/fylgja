"""The reader's documents hold to its code: the README states the pairs of NetBox's version and the branching plugin's
the reader passed on, each of `SUPPORTED` with its date and no other version (D-096), and names each fact its upgrade
procedure reads again by a bullet `design/verified-facts.md` holds; and `mapping.md` has a row for each member of
blueprint 1 the reader writes, each property of a device, an interface, a link and a probe, and each of the envelope's
seven."""

from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path

import pytest
from fake import PROBING, three_node

from fylgja_netbox import SUPPORTED, cli, read

READER = Path(__file__).resolve().parents[1]
ROOT = READER.parents[1]
SUPPORTED_HEADING = "## Supported NetBox versions"
UPGRADE_HEADING = "## Upgrading NetBox"
FACTS_HEADING = "## NetBox 4.7.5 with netbox-branching 1.2.3"
"""The section of `design/verified-facts.md` the upgrade table's facts are read from: the pair `SUPPORTED` names."""
COMMAND_HEADING = "## The command"
PROG = "fylgja-netbox"
MEMBERS = ("device", "interface", "link", "probe")
"""The definitions of blueprint 1 whose every property `mapping.md` names."""


def _section(text: str, heading: str) -> list[str]:
    """The lines under `heading`, a `## ` heading, up to the next."""
    lines = text.splitlines()
    start = lines.index(heading) + 1
    end = next((k for k in range(start, len(lines)) if lines[k].startswith("## ")), len(lines))
    return lines[start:end]


def _rows(lines: list[str], first: str) -> list[list[str]]:
    """The cells of each row of the table among `lines` whose header's first cell is `first`, header and rule left
    out."""
    rows: list[list[str]] = []
    inside = False
    for line in lines:
        if not line.startswith("|"):
            if inside:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not inside:
            inside = cells[0] == first
            continue
        if not set(cells[0]) <= set("-: "):
            rows.append(cells)
    return rows


def _options(parser: argparse.ArgumentParser) -> dict[tuple[str, ...], frozenset[str]]:
    """Each path of subcommands from the root, `()` the root, to its long options, `--help` left out: the rule of the
    core's `pages.options`, written again here since a reader's tests import nothing of the core's tests."""
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


def _usage() -> list[str]:
    """The command's lines of the README's `sh` block under "The command", each beginning with the command."""
    section = _section((READER / "README.md").read_text(), COMMAND_HEADING)
    lines: list[str] = []
    inside = False
    for line in section:
        if line.startswith("```"):
            inside = line == "```sh" and not inside
            continue
        if inside and line.startswith(PROG + " "):
            lines.append(line)
    return lines


def _words(line: str) -> list[str]:
    return shlex.split(line.replace("[", "").replace("]", ""))


def test_the_readme_states_the_supported_versions() -> None:
    section = _section((READER / "README.md").read_text(), SUPPORTED_HEADING)
    rows = _rows(section, "NetBox")
    listed = [(row[0].strip("`"), row[1].strip("`")) for row in rows]
    assert listed, "the parse is blind"
    assert sorted(listed) == sorted(SUPPORTED)
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\d", row[2]) for row in rows), "each pair with its date"
    named = set(re.findall(r"\b\d+\.\d+\.\d+\b", "\n".join(section)))
    assert named == {version for pair in SUPPORTED for version in pair}, "no other version in the section"


def test_the_upgrade_table_names_bullets_the_facts_hold() -> None:
    """Each bold title in the third column of the README's upgrade table is the title of a bullet, `- **…**`, under
    "NetBox 4.7.5 with netbox-branching 1.2.3" in the facts, a title wrapped over two lines read as one."""
    section = _section((READER / "README.md").read_text(), UPGRADE_HEADING)
    titles = [title for row in _rows(section, "The code") for title in re.findall(r"\*\*(.+?)\*\*", row[2])]
    assert "A sync adds no row to either changelog, and changes what the branch reads." in titles, "the parse is blind"
    facts = "\n".join(_section((ROOT / "design" / "verified-facts.md").read_text(), FACTS_HEADING))
    joined = re.sub(r"\n  (?!- )", " ", facts)
    held = set(re.findall(r"^- \*\*(.+?)\*\*", joined, re.M))
    assert "`/api/status/`" in held, "the facts' parse is blind"
    assert sorted(set(titles) - held) == []


def test_mapping_md_names_every_blueprint_member() -> None:
    rows = _rows((READER / "mapping.md").read_text().splitlines(), "Member")
    named = {name for row in rows for name in re.findall(r"`([^`]+)`", row[0])}
    assert "config" in named, "the parse is blind"
    schema = json.loads((ROOT / "formats" / "blueprint-1.schema.json").read_text())
    wanted = {prop for member in MEMBERS for prop in schema["$defs"][member]["properties"]}
    assert sorted(wanted - named) == []
    built = read(three_node(), branch=None, scope="tag:fylgja", document=PROBING).blueprint
    assert built is not None and built["probes"], "the read is of a probe"
    envelope = {f"source.{key}" for key in built["source"]}
    assert len(envelope) == 7
    assert sorted(envelope - named) == []


def test_the_readme_names_every_command_and_option_the_parser_has() -> None:
    named: dict[tuple[str, ...], set[str]] = {}
    for line in _usage():
        second = line.split()[1]
        path = () if second.startswith("-") else (second,)
        named.setdefault(path, set()).update(re.findall(r"--[a-z][a-z0-9-]*", line))
    assert ("read",) in named, "the parse is blind"
    assert {path: frozenset(flags) for path, flags in named.items()} == _options(cli._parser())
    assert "--version" in named[()]


def test_each_command_line_in_the_readme_parses(capsys: pytest.CaptureFixture[str]) -> None:
    """Each line, its brackets taken out, is parsed by the command's own parser; the `--version` line answers and
    exits 0, which is its parse."""
    lines = _usage()
    assert lines, "the parse is blind"
    for line in lines:
        argv = _words(line)[1:]
        if argv == ["--version"]:
            with pytest.raises(SystemExit) as stopped:
                cli._parser().parse_args(argv)
            assert stopped.value.code == 0
            assert capsys.readouterr().out.startswith(PROG + " ")
        else:
            cli._parser().parse_args(argv)


def test_the_readme_names_the_exit_statuses_and_variables_the_command_has() -> None:
    section = _section((READER / "README.md").read_text(), COMMAND_HEADING)
    statuses = {int(row[0]) for row in _rows(section, "Status")}
    assert statuses, "the parse is blind"
    held = {value for name, value in vars(cli).items() if name.startswith("EXIT_") and type(value) is int}
    assert len(held) >= 3, "the parse is blind"
    assert statuses == held
    text = "\n".join(section)
    for variable in (cli.ADDRESS, cli.TOKEN, cli.CA):
        assert f"`{variable}`" in text
