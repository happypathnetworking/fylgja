"""The read: a branch of Infrahub at a time, under a scope, into a blueprint 1 with its source envelope, or the
findings that refused it (D-082), over a `FakeSource` of rows built in the tests. The forms are judged before anything
is sent; a schema that differs, a scope that selects nothing and a list of the devices or the ports that is not whole
each end the read; otherwise every rule is judged in one pass, and the blueprint is None exactly when a finding is an
error. The id addresses the network and the probes alone (D-006), so the envelope, unhashed, may differ."""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from fake import DOCUMENT, THREE_NODE, FakeSource, dcim_schema, listing, three_node
from fylgja_core import blueprint
from fylgja_core.findings import Finding

from fylgja_infrahub import check_schema, read
from fylgja_infrahub.mapping import FIDELITY
from fylgja_infrahub.read import RULE_SCOPE_EMPTY, RULE_SCOPE_INVALID, Result
from fylgja_infrahub.rows import RULE_INCOMPLETE, Port
from fylgja_infrahub.schema import RULE_KIND_MISSING
from fylgja_infrahub.times import RULE_INVALID as RULE_AT_INVALID

T = "2026-11-09T10:00:00.000000+00:00"
FIXTURE = json.loads(THREE_NODE.read_text())
LIBRARY = (THREE_NODE.parents[2] / "infrahub" / "schema" / "dcim" / "COMMIT").read_text().strip()
"""The library's commit the development Infrahub loads, which the envelope's `mapping.version` names."""
ENVELOPE = ("source", "branch", "at", "scope", "mapping", "schema_hash", "observed_at", "fidelity")
UNVERIFIED = Finding(
    rule="infrahub.version.unverified",
    severity="warning",
    object="1.12.0",
    message="Infrahub is version 1.12.0, and this reader is verified on 1.11.11 alone.",
)


def ran(source: FakeSource, **given: Any) -> Result:
    asked: dict[str, Any] = {"branch": "main", "at": T, "scope": "tag:fylgja", "document": DOCUMENT, **given}
    return read(source, **asked)


def rules(result: Result) -> list[tuple[str, str, str | None]]:
    return [(f.rule, f.severity, f.object) for f in result.findings]


def test_three_node_reads_to_the_fixtures_id() -> None:
    source = three_node()
    result = ran(source)
    assert (result.findings, result.empty) == ((), False)
    assert result.blueprint is not None
    assert blueprint.validate(result.blueprint) == []
    assert blueprint.blueprint_id(result.blueprint) == blueprint.blueprint_id(FIXTURE)
    assert result.blueprint["network"] == FIXTURE["network"]
    assert result.blueprint["probes"] == []
    assert source.calls == [
        ("schema", "main", None),
        ("devices", "main", T),
        ("ports", "main", T),
        *[("content", "main", T)] * 3,
        ("stamps", "main", T),
        ("cable_stamps", "main", T),
        ("groups", "main", T),
        ("branch", "main", None),
        ("events", "main", None),
    ]


@pytest.mark.parametrize("scope", ["site:x", "tag:", "fylgja", ""])
def test_a_scope_that_is_no_tag_sends_nothing(scope: str) -> None:
    source = three_node()
    result = ran(source, scope=scope)
    assert (result.blueprint, result.empty) == (None, False)
    assert rules(result) == [(RULE_SCOPE_INVALID, "error", scope)]
    assert "main" in result.findings[0].message and T in result.findings[0].message
    assert source.calls == []


@pytest.mark.parametrize(
    ("at", "since"),
    [("yesterday", None), (T, "yesterday"), ("2026-11-09T10:00:00.0000001+00:00", None), ("2026-11-09", None)],
    ids=["at no time", "generated_since no time", "past the microsecond", "no T"],
)
def test_an_at_that_is_no_time_sends_nothing(at: str, since: str | None) -> None:
    source = three_node()
    result = ran(source, at=at, generated_since=since)
    assert result.blueprint is None
    assert rules(result) == [(RULE_AT_INVALID, "error", since or at)]
    assert "branch main" in result.findings[0].message
    assert source.calls == []


def test_every_form_at_fault_is_filed_at_once() -> None:
    source = three_node()
    result = ran(source, scope="site:x", at="yesterday", generated_since="today")
    assert rules(result) == [
        (RULE_AT_INVALID, "error", "today"),
        (RULE_AT_INVALID, "error", "yesterday"),
        (RULE_SCOPE_INVALID, "error", "site:x"),
    ]
    assert source.calls == []


def test_a_schema_that_differs_ends_the_read() -> None:
    source = three_node()
    held = dcim_schema()
    source.held_schema = dataclasses.replace(held, nodes={k: v for k, v in held.nodes.items() if k != "DcimCable"})
    result = ran(source)
    assert result.blueprint is None
    assert rules(result) == [(RULE_KIND_MISSING, "error", "DcimCable")]
    assert source.calls == [("schema", "main", None)]


def test_a_scope_selecting_nothing_is_empty() -> None:
    source = three_node()
    source.held_devices = listing("DcimDevice", [])
    result = ran(source)
    (finding,) = result.findings
    assert result == Result(None, (finding,), True)
    assert (finding.rule, finding.severity, finding.object) == (RULE_SCOPE_EMPTY, "error", "tag:fylgja")
    for held in ("tag:fylgja", "main", T):
        assert held in finding.message
    assert source.calls == [("schema", "main", None), ("devices", "main", T)]


def test_a_short_list_of_ports_ends_the_read_incomplete() -> None:
    source = three_node()
    source.held_ports = listing("InterfacePhysical", source.held_ports.items[1:], count=15)
    result = ran(source)
    assert (result.blueprint, result.empty) == (None, False)
    assert rules(result) == [(RULE_INCOMPLETE, "error", "InterfacePhysical")]
    assert "counted 15" in result.findings[0].message and T in result.findings[0].message
    assert [call[0] for call in source.calls] == ["schema", "devices", "ports"]


def test_a_short_list_of_devices_ends_the_read_incomplete() -> None:
    source = three_node()
    source.held_devices = listing("DcimDevice", source.held_devices.items[:2], count=3)
    result = ran(source)
    assert (result.blueprint, result.empty) == (None, False)
    assert rules(result) == [(RULE_INCOMPLETE, "error", "DcimDevice")]
    assert [call[0] for call in source.calls] == ["schema", "devices"]


def test_the_envelope_holds_its_eight_members_and_none_is_hashed() -> None:
    before = datetime.now(UTC)
    result = ran(three_node())
    after = datetime.now(UTC)
    assert result.blueprint is not None
    source = result.blueprint["source"]
    assert sorted(source) == sorted(ENVELOPE)
    assert {key: value for key, value in source.items() if key != "observed_at"} == {
        "source": "infrahub",
        "branch": "main",
        "at": T,
        "scope": "tag:fylgja",
        "mapping": {"reader": "infrahub-dcim", "model": "opsmill/schema-library", "version": LIBRARY},
        "schema_hash": dcim_schema().hash,
        "fidelity": list(FIDELITY),
    }
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", source["observed_at"])
    observed = datetime.strptime(source["observed_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    assert before <= observed <= after

    other = ran(three_node(), branch="third-link", at="2026-11-10T00:00:00.000000Z")
    assert other.blueprint is not None
    assert (other.blueprint["source"]["branch"], other.blueprint["source"]["at"]) == (
        "third-link",
        "2026-11-10T00:00:00.000000Z",
    )
    assert blueprint.blueprint_id(other.blueprint) == blueprint.blueprint_id(result.blueprint)


def reversed_rows() -> FakeSource:
    """`three_node`'s rows, the devices, the ports and each cable's ends in the reverse order."""
    source = three_node()
    source.held_devices = listing("DcimDevice", source.held_devices.items[::-1])
    flipped: list[Port] = []
    for port in source.held_ports.items[::-1]:
        if port.connector is not None:
            ends = dataclasses.replace(port.connector.ends, items=port.connector.ends.items[::-1])
            port = dataclasses.replace(port, connector=dataclasses.replace(port.connector, ends=ends))
        flipped.append(port)
    source.held_ports = listing("InterfacePhysical", flipped)
    return source


def unobserved(result: Result) -> dict[str, Any]:
    assert result.blueprint is not None
    return {**result.blueprint, "source": {k: v for k, v in result.blueprint["source"].items() if k != "observed_at"}}


def test_the_same_rows_read_twice_give_one_document_but_for_observed_at() -> None:
    first, again, flipped = ran(three_node()), ran(three_node()), ran(reversed_rows())
    assert unobserved(first) == unobserved(again) == unobserved(flipped)
    assert json.dumps(unobserved(first)) == json.dumps(unobserved(flipped)), "every list in one order"


def renamed_n1(source: FakeSource) -> None:
    source.held_devices = listing(
        "DcimDevice", [dataclasses.replace(d, name="N1") if d.name == "n1" else d for d in source.held_devices.items]
    )


def missing_n1(source: FakeSource) -> None:
    source.held_devices = listing(
        "DcimDevice",
        [
            dataclasses.replace(d, artifacts=listing("n1.artifacts", [])) if d.name == "n1" else d
            for d in source.held_devices.items
        ],
    )


def unverified(source: FakeSource) -> None:
    source.unverified = UNVERIFIED


def both(source: FakeSource) -> None:
    renamed_n1(source)
    source.held_content["storage-n2"] = dataclasses.replace(source.held_content["storage-n2"], status=500)


@pytest.mark.parametrize(
    ("alter", "refused"),
    [(lambda source: None, False), (renamed_n1, False), (unverified, False), (missing_n1, True), (both, True)],
    ids=["clean", "an info", "a warning", "an error", "an error and an info"],
)
def test_a_blueprint_is_none_exactly_when_a_finding_is_an_error(alter: Any, refused: bool) -> None:
    source = three_node()
    alter(source)
    result = ran(source)
    assert any(f.severity == "error" for f in result.findings) is refused
    assert (result.blueprint is None) is refused
    if not refused:
        assert result.blueprint is not None and blueprint.validate(result.blueprint) == []


def test_the_version_warning_rides_on_every_result() -> None:
    source = three_node()
    source.unverified = UNVERIFIED
    result = ran(source)
    assert result.findings == (UNVERIFIED,)
    assert result.blueprint is not None, "a warning refuses nothing"
    assert ran(source, scope="site:x").findings[-1] == UNVERIFIED
    assert check_schema(source, branch="main") == (UNVERIFIED,)
    held = dcim_schema()
    source.held_schema = dataclasses.replace(held, nodes={k: v for k, v in held.nodes.items() if k != "DcimCable"})
    assert [(f.rule, f.object) for f in check_schema(source, branch="main")] == [
        (RULE_KIND_MISSING, "DcimCable"),
        (UNVERIFIED.rule, "1.12.0"),
    ]
    assert three_node().unverified is None
    assert check_schema(three_node(), branch="main") == ()


def test_a_problem_of_the_blueprint_built_is_an_error_under_its_own_rule() -> None:
    """`read` holds what it built to blueprint 1 (blueprint.validate), each problem an error under the core's rule, its
    pointer the object: here a device with two ports of one name."""
    source = three_node()
    again = next(p for p in source.held_ports.items if p.id == "port-n2-ethernet-1/2")
    twin = dataclasses.replace(again, id="port-n2-ethernet-1/2-again", connector=None)
    source.held_ports = listing("InterfacePhysical", [*source.held_ports.items, twin])
    result = ran(source)
    assert result.blueprint is None
    assert rules(result) == [(blueprint.RULE_DUPLICATE, "error", "/network/devices/1/interfaces/4")]
    assert "main" in result.findings[0].message and T in result.findings[0].message
