"""The reader's documents hold to its code: the README states the Infrahub versions the contract tier passed on, each
of `SUPPORTED` with its date and no other (D-083), and names each fact its upgrade procedure reads again by a bullet
`design/verified-facts.md` holds; and `mapping.md` has a row for each member of blueprint 1 the reader writes, each
property of a device, an interface, a link and a probe, and each of the envelope's eight."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fake import DOCUMENT, three_node

from fylgja_infrahub import SUPPORTED, read

READER = Path(__file__).resolve().parents[1]
ROOT = READER.parents[1]
SUPPORTED_HEADING = "## Supported Infrahub versions"
UPGRADE_HEADING = "## Upgrading Infrahub"
FACTS_HEADING = "## Infrahub 1.11.11"
"""The section of `design/verified-facts.md` the upgrade table's facts are read from: the version `SUPPORTED` names."""
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


def test_the_readme_states_the_supported_versions() -> None:
    section = _section((READER / "README.md").read_text(), SUPPORTED_HEADING)
    rows = _rows(section, "Infrahub")
    listed = [row[0].strip("`") for row in rows]
    assert listed, "the parse is blind"
    assert sorted(listed) == sorted(SUPPORTED)
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\d", row[1]) for row in rows), "each version with its date"
    named = set(re.findall(r"\b\d+\.\d+\.\d+\b", "\n".join(section)))
    assert named == set(SUPPORTED), "no other version in the section"


def test_the_upgrade_table_names_bullets_the_facts_hold() -> None:
    """Each bold title in the third column of the README's upgrade table is the title of a bullet, `- **…**`, under
    "Infrahub 1.11.11" in the facts, a title wrapped over two lines read as one (ruling P3-40)."""
    section = _section((READER / "README.md").read_text(), UPGRADE_HEADING)
    titles = [title for row in _rows(section, "The code") for title in re.findall(r"\*\*(.+?)\*\*", row[2])]
    assert "What a stale rule can be built on" in titles, "the README's parse is blind"
    facts = "\n".join(_section((ROOT / "design" / "verified-facts.md").read_text(), FACTS_HEADING))
    joined = re.sub(r"\n  (?!- )", " ", facts)
    held = set(re.findall(r"^- \*\*(.+?)\*\*", joined, re.M))
    assert "Its version." in held, "the facts' parse is blind"
    assert sorted(set(titles) - held) == []


def test_mapping_md_names_every_blueprint_member() -> None:
    rows = _rows((READER / "mapping.md").read_text().splitlines(), "Member")
    named = {name for row in rows for name in re.findall(r"`([^`]+)`", row[0])}
    assert "config" in named, "the parse is blind"
    schema = json.loads((ROOT / "formats" / "blueprint-1.schema.json").read_text())
    wanted = {prop for member in MEMBERS for prop in schema["$defs"][member]["properties"]}
    assert sorted(wanted - named) == []
    built = read(three_node(), branch="main", at="2026-11-09T10:01:00.000000+00:00", scope="tag:fylgja",
                 document=DOCUMENT).blueprint  # fmt: skip
    assert built is not None
    envelope = {f"source.{key}" for key in built["source"]}
    assert len(envelope) == 8
    assert sorted(envelope - named) == []
