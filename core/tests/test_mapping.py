"""Interface mapping: how a platform package's rules decide a production name, held to the
rows each shipped package must decide (testdata/packages/mappings.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from fylgja_core import mapping, platform_package

ROOT = Path(__file__).resolve().parents[2]
PSP = ROOT / "psp"
PACKAGES = {
    p.id: p
    for p in map(platform_package.load, [PSP / "nokia_srlinux.yaml", PSP / "arista_eos.yaml",
                                         ROOT / "testdata" / "packages" / "chassisos.yaml"])
}
MAPPINGS: dict[str, list[dict[str, Any]]] = yaml.safe_load(
    (ROOT / "testdata" / "packages" / "mappings.yaml").read_text()
)
ROWS = [(package_id, row) for package_id, rows in MAPPINGS.items() for row in rows]


def row_id(value: Any) -> str:
    return value if isinstance(value, str) else str(value["production"])


@pytest.mark.parametrize(("package_id", "row"), ROWS, ids=row_id)
def test_each_mapping_row_is_decided_as_the_packages_say(package_id: str, row: dict[str, Any]) -> None:
    decision = mapping.decide(PACKAGES[package_id], row["production"], row.get("rule") == "management")
    if "unmappable" in row:
        assert isinstance(decision, mapping.Unmappable), decision
        assert (decision.omission, decision.rule) == (row["unmappable"], row.get("rule"))
    else:
        assert isinstance(decision, mapping.Mapped), decision
        assert (decision.rule, decision.node_name) == (row["rule"], row["node_name"])


def test_match_captures_one_segment_per_placeholder_and_nothing_else() -> None:
    assert mapping.match("ethernet-{slot}/{port}", "ethernet-1/58") == {"slot": "1", "port": "58"}
    assert mapping.match("ethernet-{slot}/{port}", "ethernet-1/58/1") is None
    assert mapping.match("Ethernet{port}", "xEthernet1") is None
    assert mapping.match("Ethernet{port}", "Ethernet1x") == {"port": "1x"}
    assert mapping.match("mgmt0", "mgmt0") == {}
    assert mapping.match("a.b{x}", "axb1") is None


def test_render_fills_the_captures_into_a_template() -> None:
    assert mapping.render("eth{slot}_{port}", {"slot": "2", "port": "1"}) == "eth2_1"
    assert mapping.render("Management0", {}) == "Management0"


def test_a_non_numeric_capture_is_out_of_range() -> None:
    decision = mapping.decide(PACKAGES["arista_eos"], "Ethernet1a", False)
    assert isinstance(decision, mapping.Unmappable)
    assert (decision.omission, decision.rule) == ("out_of_range", "ethernet")
    assert "1a" in decision.detail


def test_the_first_fitting_rule_decides_even_out_of_range() -> None:
    # chassisos: Ethernet1/53 fits front first (port 53 is above 52) and never falls to linecard.
    decision = mapping.decide(PACKAGES["chassisos"], "Ethernet1/53", False)
    assert isinstance(decision, mapping.Unmappable)
    assert decision.rule == "front" and "53" in decision.detail and "52" in decision.detail


def test_a_name_no_rule_matches_names_the_rules_tried() -> None:
    decision = mapping.decide(PACKAGES["nokia_srlinux"], "Ethernet99", False)
    assert isinstance(decision, mapping.Unmappable)
    assert (decision.omission, decision.rule) == ("no_rule", None)
    assert "ethernet" in decision.detail and "breakout" in decision.detail


def test_a_mapped_name_carries_its_captures_for_the_plans_rename() -> None:
    decision = mapping.decide(PACKAGES["arista_eos"], "Ethernet3/1/1", False)
    assert decision == mapping.Mapped(rule="breakout", node_name="Ethernet3/1/1",
                                      captures={"slot": "3", "port": "1", "sub": "1"})


def test_the_management_rule_names_the_port_by_its_literal_or_the_production_name() -> None:
    assert mapping.decide(PACKAGES["arista_eos"], "Management1", True) == mapping.Mapped(
        rule="management", node_name="Management0", captures={}
    )
    assert mapping.decide(PACKAGES["nokia_srlinux"], "mgmt0", True) == mapping.Mapped(
        rule="management", node_name="mgmt0", captures={}
    )
