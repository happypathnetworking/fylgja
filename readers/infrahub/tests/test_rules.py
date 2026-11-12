"""The reader's rules are its own, never the core's (formats/README.md, note 11): each rule its code files is a row of
its catalogue, `readers/infrahub/rules.md`, and the catalogue names no other; and each is a rule id as findings 1 has
it, so a finding the reader files is one a findings 1 document could hold."""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
from pathlib import Path

import fylgja_infrahub

READER = Path(__file__).resolve().parents[1]
ROOT = READER.parents[1]
CATALOGUE = READER / "rules.md"


def _rows() -> list[list[str]]:
    """The cells of every row of the catalogue's table that names a rule, its backticks taken off each cell."""
    rows = []
    for line in CATALOGUE.read_text().splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0].startswith("`"):
            rows.append([cell.strip("`") for cell in cells])
    return rows


def _filed() -> set[str]:
    """Every module-level `RULE*` string of every module of the reader, walked with `pkgutil`."""
    names = [m.name for m in pkgutil.walk_packages(fylgja_infrahub.__path__, f"{fylgja_infrahub.__name__}.")]
    found: set[str] = set()
    for name in [fylgja_infrahub.__name__, *names]:
        module = importlib.import_module(name)
        found |= {value for key, value in vars(module).items() if key.startswith("RULE") and isinstance(value, str)}
    return found


def test_the_catalogue_holds_exactly_the_rules_the_code_files() -> None:
    listed = [row[0] for row in _rows()]
    assert "read.incomplete" in listed, "the parse is blind"
    assert len(listed) == len(set(listed)), "a rule has two rows"
    assert set(listed) == _filed()


def test_every_rule_is_a_findings_1_rule_id() -> None:
    schema = json.loads((ROOT / "formats" / "findings-1.schema.json").read_text())
    pattern = re.compile(schema["$defs"]["rule"]["pattern"])
    rules = _filed() | {row[0] for row in _rows()}
    assert rules
    assert sorted(rule for rule in rules if not pattern.search(rule)) == []
