"""The example's rules are its own, never the core's (formats/README.md, note 11): one constant a rule in `rules.py`,
the severity each is filed at and, for an error, the status it gives a rehearsal whose cause it is (D-086); and the
catalogue, `orchestrator/rules.md`, says the same rules with the same severities and statuses. A sentence quotes a
finding as `<object>: <message> (<rule>)`, short enough to read in a report's first sentence (D-087). The catalogue's
last section is the Infrahub change source's, held to that source's own constants: the library names no source's
rules (D-085)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fylgja_orchestrator import infrahub
from fylgja_orchestrator.rehearsal import rules
from fylgja_orchestrator.rehearsal.rules import quote

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / "orchestrator" / "rules.md"
SOURCE = "## Findings: the Infrahub change source"
"""The heading of the catalogue's last section, the change source's rules; every section before it is the
rehearsal's."""

# The rehearsal's errors and the status each gives the rehearsal it is the cause of (D-086).
GIVEN = {
    "stage.refused": "failed",
    "rehearsal.baseline.failed": "failed",
    "rehearsal.stage.failed": "failed",
    "rehearsal.stages.none": "not_rehearsed",
    "rehearsal.capacity": "not_rehearsed",
    "rehearsal.image.absent": "not_rehearsed",
    "rehearsal.admission.refused": "not_rehearsed",
    "rehearsal.core.unreachable": "not_rehearsed",
    "rehearsal.core.refused": "not_rehearsed",
    "rehearsal.source.failed": "not_rehearsed",
    "rehearsal.twin.held": "not_rehearsed",
    "rehearsal.limit.passed": "stopped",
    "rehearsal.run.cancelled": "stopped",
    "rehearsal.twin.deleted": "stopped",
}


def _rows(*, source: bool = False) -> list[list[str]]:
    """The cells of every row of the catalogue's tables that names a rule, its backticks taken off each cell: of the
    rehearsal's sections, or of the change source's where `source` is true."""
    rehearsal, heading, rest = CATALOGUE.read_text().partition(SOURCE)
    assert heading, f"the catalogue has no section {SOURCE!r}"
    rows = []
    for line in (rest if source else rehearsal).splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0].startswith("`"):
            rows.append([cell.strip("`") for cell in cells])
    return rows


def _constants() -> dict[str, str]:
    """Every rule constant of `rules.py`, by name: its upper-case names bound to a string."""
    return {name: value for name, value in vars(rules).items() if name.isupper() and isinstance(value, str)}


def test_the_catalogue_holds_exactly_the_rules_with_their_severity_and_status() -> None:
    rows = _rows()
    listed = [row[0] for row in rows]
    assert "rehearsal.stages.none" in listed, "the parse is blind"
    assert len(listed) == len(set(listed)), "a rule has two rows"

    constants = _constants()
    assert len(set(constants.values())) == len(constants), "two constants name one rule"
    assert set(listed) == set(constants.values()) == set(rules.SEVERITY)
    assert {rule for rule, severity in rules.SEVERITY.items() if severity == "error"} == set(rules.STATUS)
    assert set(rules.SEVERITY.values()) <= {"error", "warning", "info"}
    assert set(rules.STATUS.values()) <= {"failed", "not_rehearsed", "stopped"}
    assert {rule: rules.STATUS[rule] for rule in GIVEN} == GIVEN

    for rule, severity, status, sentence in rows:
        assert severity == rules.SEVERITY[rule], rule
        assert status == rules.STATUS.get(rule, "none"), rule
        assert sentence, rule


def test_the_change_sources_section_holds_exactly_its_rules_with_their_severity() -> None:
    rows = _rows(source=True)
    listed = [row[0] for row in rows]
    assert "stage.main.moved" in listed, "the parse is blind"
    assert len(listed) == len(set(listed)), "a rule has two rows"
    constants = {name: value for name, value in vars(infrahub.source).items() if name.startswith("RULE")}
    exported = {name: value for name, value in vars(infrahub).items() if name.startswith("RULE")}
    assert exported == constants, "the package does not re-export each of the source's rules"
    assert len(set(constants.values())) == len(constants) == 5, "two constants name one rule"
    assert set(listed) == set(constants.values()) == set(infrahub.SEVERITY)
    assert set(listed).isdisjoint(rules.SEVERITY), "a rule is the library's and the source's"
    # A stage refused by an error of the source's is the library's `stage.refused`, which fails the change.
    for rule, severity, status, sentence in rows:
        assert severity == infrahub.SEVERITY[rule], rule
        assert status == (rules.STATUS[rules.STAGE_REFUSED] if severity == "error" else "none"), rule
        assert sentence, rule


def test_every_rule_is_a_rule_id_as_findings_1_has_it() -> None:
    schema = json.loads((ROOT / "formats" / "findings-1.schema.json").read_text())
    pattern = re.compile(schema["$defs"]["rule"]["pattern"])
    assert [rule for rule in [*rules.SEVERITY, *infrahub.SEVERITY] if not pattern.search(rule)] == []


PUSH = {
    "rule": "push.refused",
    "severity": "error",
    "object": "n3",
    "message": "At line 1: n3 refused the configuration",
}


def test_a_finding_is_quoted_with_its_object_its_message_and_its_rule() -> None:
    assert quote(PUSH) == "n3: At line 1: n3 refused the configuration (push.refused)"


def test_a_quoted_message_loses_its_final_full_stop() -> None:
    stale = {"rule": "artifact.stale", "severity": "error", "object": "n1"}
    assert quote(stale | {"message": "n1's configuration is older than its intent."}) == (
        "n1: n1's configuration is older than its intent (artifact.stale)"
    )
    assert quote(stale | {"message": "Wait..."}) == "n1: Wait.. (artifact.stale)"


def test_a_long_message_is_cut_to_300_characters_ending_in_an_ellipsis() -> None:
    assert quote(PUSH | {"message": "x" * 300 + "."}) == "n3: " + "x" * 300 + " (push.refused)"
    assert quote(PUSH | {"message": "x" * 5000}) == "n3: " + "x" * 299 + "… (push.refused)"
    assert quote(PUSH | {"message": "é" * 5000}) == "n3: " + "é" * 299 + "… (push.refused)"


def test_a_finding_with_no_object_begins_with_its_message() -> None:
    empty = {"rule": "scope.empty", "severity": "error", "message": "The scope selects no device."}
    assert quote(empty) == "The scope selects no device (scope.empty)"
    assert quote(empty | {"object": None}) == "The scope selects no device (scope.empty)"
