"""Blueprint 1's id, order and cross-field rules (formats/blueprint-1.schema.json)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import rfc8785

from fylgja_core import blueprint, documents
from fylgja_core.documents import Problem, Rejected

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "testdata" / "blueprint"
NAMES = ["lossy", "mixed", "three-node", "three-node-probed"]


def load(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return doc


def rules(problems: list[Problem]) -> set[str]:
    return {p.rule for p in problems}


@pytest.mark.parametrize("name", NAMES)
def test_each_fixture_is_valid(name: str) -> None:
    assert blueprint.validate(load(name)) == []


@pytest.mark.parametrize("name", NAMES)
def test_the_id_is_rfc_8785_over_network_and_probes(name: str) -> None:
    doc = load(name)
    body = {"network": doc["network"], "probes": doc["probes"]}
    assert blueprint.canonical(body) == rfc8785.dumps(body)
    assert blueprint.blueprint_id(doc) == hashlib.sha256(rfc8785.dumps(body)).hexdigest()


def test_the_id_ignores_the_version_and_the_source() -> None:
    doc = load("three-node")
    other = copy.deepcopy(doc)
    other["source"] = {"branch": "elsewhere"}
    del other["blueprint_version"]
    assert blueprint.blueprint_id(other) == blueprint.blueprint_id(doc)


def test_the_fixtures_ids_are_pinned() -> None:
    facts = {n: json.loads((ROOT / "testdata" / "compiler" / f"{n}.facts.json").read_text()) for n in NAMES}
    for name in NAMES:
        assert blueprint.blueprint_id(load(name)) == facts[name]["input"]["blueprint_id"], name


def test_canonical_orders_member_names_by_utf_16_code_units() -> None:
    # U+FB33 sorts after U+1F600 by code point, before it by UTF-16 code unit.
    value = {"\U0001f600": True, "דּ": False, "a": None}
    assert blueprint.canonical(value) == rfc8785.dumps(value)
    assert list(json.loads(blueprint.canonical(value))) == ["a", "\U0001f600", "דּ"]


def test_canonical_escapes_as_ecmascript_does() -> None:
    value = ["quote \" backslash \\ tab \t nul \x00 del \x7f é " + chr(0x2028)]
    assert blueprint.canonical(value) == rfc8785.dumps(value)


@pytest.mark.parametrize("value", [1, 1.5, {"a": [2]}, "\ud800"])
def test_canonical_refuses_numbers_and_lone_surrogates(value: Any) -> None:
    with pytest.raises(blueprint.NotCanonical):
        blueprint.canonical(value)


def test_another_version_is_refused_first() -> None:
    doc = load("three-node")
    doc["blueprint_version"] = "2"
    assert blueprint.validate(doc) == [
        Problem("/blueprint_version", blueprint.RULE_VERSION, "version '2'; this core reads 1")
    ]


def test_a_schema_violation_is_reported_with_its_pointer() -> None:
    doc = load("three-node")
    del doc["network"]["devices"][0]["config"]
    doc["network"]["devices"][1]["interfaces"][0]["enabled"] = "yes"
    found = blueprint.validate(doc)
    assert rules(found) == {blueprint.RULE_INVALID}
    assert {p.pointer for p in found} == {"/network/devices/0", "/network/devices/1/interfaces/0/enabled"}


def test_unsorted_and_duplicated_lists_are_refused_never_sorted() -> None:
    doc = load("three-node")
    devices = doc["network"]["devices"]
    devices[0], devices[1] = devices[1], devices[0]
    doc["network"]["devices"][2]["interfaces"].append(copy.deepcopy(doc["network"]["devices"][2]["interfaces"][-1]))
    link = doc["network"]["links"][0]
    link["a"], link["b"] = link["b"], link["a"]
    found = blueprint.validate(doc)
    assert ("/network/devices/1", blueprint.RULE_UNSORTED) in {(p.pointer, p.rule) for p in found}
    assert blueprint.RULE_DUPLICATE in rules(found)
    assert ("/network/links/0", blueprint.RULE_UNSORTED) in {(p.pointer, p.rule) for p in found}


def test_a_link_must_join_known_free_data_ports() -> None:
    doc = load("three-node")
    n1 = doc["network"]["devices"][0]
    mgmt = next(f["name"] for f in n1["interfaces"] if f["mgmt_only"])
    first = doc["network"]["links"][0]
    doc["network"]["links"] = [
        first,
        {"a": {"device": "n1", "interface": mgmt}, "b": {"device": "n9", "interface": "x"}},
        {"a": first["a"], "b": {"device": "n3", "interface": "ethernet-1/2"}},
    ]
    doc["network"]["links"].sort(key=lambda lk: (lk["a"]["device"], lk["a"]["interface"],
                                                  lk["b"]["device"], lk["b"]["interface"]))
    found = rules(blueprint.validate(doc))
    assert {blueprint.RULE_LINK_MGMT, blueprint.RULE_ENDPOINT_UNKNOWN, blueprint.RULE_INTERFACE_TWICE} <= found


def test_a_probes_gateway_and_hosts_are_checked() -> None:
    doc = load("three-node-probed")
    a, b = doc["probes"][0]["endpoints"]
    a["gateway"] = "10.9.9.1"
    b["address"] = a["address"]
    found = rules(blueprint.validate(doc))
    assert found == {blueprint.RULE_GATEWAY_OUTSIDE, blueprint.RULE_ADDRESS_SHARED}


def test_every_problem_is_reported_in_one_pass() -> None:
    doc = load("three-node-probed")
    doc["network"]["devices"].reverse()
    doc["probes"][0]["endpoints"][0]["gateway"] = "10.9.9.1"
    found = rules(blueprint.validate(doc))
    assert {blueprint.RULE_UNSORTED, blueprint.RULE_GATEWAY_OUTSIDE} <= found


def test_a_fixture_decodes_to_its_model_and_encodes_back_unchanged() -> None:
    doc = load("three-node-probed")
    bp = blueprint.decode(doc)
    assert isinstance(bp, blueprint.Blueprint)
    assert [d.name for d in bp.network.devices] == ["n1", "n2", "n3"]
    assert bp.network.devices[0].interfaces[-1] == blueprint.Interface(name="mgmt0", mgmt_only=True, enabled=True)
    assert bp.network.links[0] == blueprint.Link(
        a=blueprint.Endpoint(device="n1", interface="ethernet-1/1"),
        b=blueprint.Endpoint(device="n2", interface="ethernet-1/1"),
    )
    assert bp.probes[0].name == "n1-loop" and bp.probes[0].endpoints[1].gateway == "10.1.11.1"
    assert bp.source is not None and bp.source["envelope"]["branch"] == "fylgja-fixture"
    assert documents.encode(bp) == doc


def test_a_blueprint_without_a_source_encodes_without_one() -> None:
    doc = load("three-node")
    del doc["source"]
    assert documents.encode(blueprint.decode(doc)) == doc


def test_decode_refuses_an_invalid_document_with_every_problem() -> None:
    doc = load("three-node-probed")
    doc["network"]["devices"].reverse()
    doc["probes"][0]["endpoints"][0]["gateway"] = "10.9.9.1"
    with pytest.raises(Rejected) as caught:
        blueprint.decode(doc)
    assert {p.rule for p in caught.value.problems} >= {blueprint.RULE_UNSORTED, blueprint.RULE_GATEWAY_OUTSIDE}


def test_load_reads_a_file_and_names_it_when_it_refuses(tmp_path: Path) -> None:
    assert blueprint.load(FIXTURES / "three-node.json") == blueprint.decode(load("three-node"))
    path = tmp_path / "two.json"
    path.write_text(json.dumps({**load("three-node"), "blueprint_version": "2"}))
    with pytest.raises(Rejected) as caught:
        blueprint.load(path)
    assert caught.value.subject == str(path)
    assert [p.rule for p in caught.value.problems] == [blueprint.RULE_VERSION]
