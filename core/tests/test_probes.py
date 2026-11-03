"""Probe declaration 1's loader (formats/probes-1.schema.json): each fixture under
testdata/probes/ loads, and each one under testdata/probes/invalid/ is refused for its fault
alone, with the probe formats checked against the loaded probe packages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fylgja_core import blueprint, documents, probes
from fylgja_core.documents import Rejected
from fylgja_core.probes import (
    RULE_ADDRESS_DUPLICATE,
    RULE_FORMAT_UNKNOWN,
    RULE_GATEWAY_OUTSIDE,
    RULE_INVALID,
    RULE_NAME_DUPLICATE,
    RULE_VERSION,
)

ROOT = Path(__file__).resolve().parents[2]
DECLARATIONS = ROOT / "testdata" / "probes"
VALID = sorted(DECLARATIONS.glob("*.json"))
INVALID = DECLARATIONS / "invalid"
FORMATS = frozenset({"ping"})

# Every rejection fixture, named by its fault, and the (pointer, rule) pairs the loader must
# report for it. A fault the schema states is probes.invalid at the member's pointer.
REJECTED: dict[str, set[tuple[str, str]]] = {
    "probe.address.duplicate.json": {("/probes/1/endpoints/0/address", RULE_ADDRESS_DUPLICATE)},
    "probe.address.invalid.json": {("/probes/0/endpoints/1/address", RULE_INVALID)},
    "probe.address.ipv6.json": {
        ("/probes/0/endpoints/1/address", RULE_INVALID),
        ("/probes/0/endpoints/1/gateway", RULE_INVALID),
    },
    "probe.format.unknown.json": {("/probes/0/format", RULE_FORMAT_UNKNOWN)},
    "probe.gateway.invalid.json": {("/probes/0/endpoints/1/gateway", RULE_INVALID)},
    "probe.gateway.outside.json": {("/probes/0/endpoints/1/gateway", RULE_GATEWAY_OUTSIDE)},
    "probe.name.duplicate.json": {("/probes/1/name", RULE_NAME_DUPLICATE)},
    "probe.name.invalid.json": {("/probes/0/name", RULE_INVALID)},
    "probes.invalid.json": {("/probes/0/endpoints", RULE_INVALID)},
    "probes.version.unsupported.json": {("/probes_version", RULE_VERSION)},
}


def read(path: Path) -> Any:
    return json.loads(path.read_text())


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_each_declaration_loads_to_its_model_and_encodes_back_unchanged(path: Path) -> None:
    declaration = probes.load(path, FORMATS)
    assert all(isinstance(p, blueprint.Probe) for p in declaration.probes)
    assert documents.encode(declaration) == read(path)


def test_a_declaration_holds_blueprint_probes() -> None:
    declaration = probes.load(DECLARATIONS / "n1-loop.json", FORMATS)
    (probe,) = declaration.probes
    assert probe.name == "n1-loop" and probe.format == "ping"
    assert probe.endpoints[1] == blueprint.ProbeEndpoint(
        device="n1", interface="ethernet-1/11", address="10.1.11.2/24", gateway="10.1.11.1"
    )
    assert probes.load(DECLARATIONS / "none.json", FORMATS).probes == ()


def test_the_order_of_a_declaration_is_free() -> None:
    later = read(DECLARATIONS / "n2-loop.json")["probes"][0]
    earlier = read(DECLARATIONS / "n1-loop.json")["probes"][0]
    assert probes.validate({"probes_version": "1", "probes": [later, earlier]}, FORMATS) == []


def test_a_format_is_checked_against_the_loaded_packages_not_a_list() -> None:
    doc = read(INVALID / "probe.format.unknown.json")
    assert [p.rule for p in probes.validate(doc, FORMATS)] == [RULE_FORMAT_UNKNOWN]
    assert probes.validate(doc, {"ping", "traceroute"}) == []


@pytest.mark.parametrize("name", sorted(REJECTED))
def test_each_rejection_fixture_is_refused_for_its_fault_alone(name: str) -> None:
    found = probes.validate(read(INVALID / name), FORMATS)
    assert {(p.pointer, p.rule) for p in found} == REJECTED[name], found
    with pytest.raises(Rejected) as caught:
        probes.load(INVALID / name, FORMATS)
    assert caught.value.subject == str(INVALID / name)


def test_every_rejection_fixture_has_a_row() -> None:
    assert {p.name for p in INVALID.glob("*.json")} == set(REJECTED)
