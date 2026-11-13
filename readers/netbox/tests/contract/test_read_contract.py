"""The read against the development NetBox (D-095; design/verified-facts.md, "NetBox 4.7.5 with netbox-branching
1.2.3"): the seeded fixture network read from `main` into its devices and links, each configuration the bytes NetBox
renders for the device, and the same state read twice into one id; a branch with no change read to `main`'s id; a
cable made on a branch a link there alone; a template that reads the device's configuration context taken verbatim;
and a scope no device carries, empty. The seed's reader document is read here with no context named: the probes are
test_probes_contract.py's. Every write is the superuser's, through `box`, under the header of the test's own
branch. No assertion message prints the address or a token."""

from __future__ import annotations

import json
import secrets
from typing import Any

import pytest
from fylgja_core import blueprint

from fylgja_netbox import NetBox, ReaderDocument, Result, read
from fylgja_netbox.rows import Branch

from .conftest import PREFIX, Writes

SCOPE = "tag:fylgja"
DEVICES = ["n1", "n2", "n3"]
LINKS = [
    {"a": {"device": "n1", "interface": "ethernet-1/1"}, "b": {"device": "n2", "interface": "ethernet-1/1"}},
    {"a": {"device": "n2", "interface": "ethernet-1/2"}, "b": {"device": "n3", "interface": "ethernet-1/1"}},
]
"""The seeded fixture's two links on `main`, which lacks `testdata/blueprint/three-node.json`'s third."""

THIRD = {"a": {"device": "n1", "interface": "ethernet-1/2"}, "b": {"device": "n3", "interface": "ethernet-1/2"}}


@pytest.fixture(scope="module")
def unprobed(document: ReaderDocument) -> ReaderDocument:
    """The seeded fixture network's reader document, naming no configuration context of probes."""
    return ReaderDocument(document.platforms, None)


def errors(result: Result) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in result.findings if finding.severity == "error"]


def taken(result: Result) -> dict[str, Any]:
    """The blueprint a read answered, which must have no error."""
    assert errors(result) == []
    assert result.blueprint is not None
    return result.blueprint


def configs(doc: dict[str, Any]) -> dict[str, str]:
    return {device["name"]: device["config"] for device in doc["network"]["devices"]}


def but_observed(doc: dict[str, Any]) -> dict[str, Any]:
    held: dict[str, Any] = json.loads(json.dumps(doc))
    del held["source"]["observed_at"]
    return held


def ids(box: Writes, schema_id: str | None = None) -> dict[str, int]:
    """The fixture's devices by their names, as the tests' writer lists them."""
    return {row["name"]: row["id"] for row in box.listed("dcim/devices/", branch=schema_id, tag="fylgja")}


def rendered(box: Writes, device: int, schema_id: str | None = None) -> str:
    """The configuration NetBox renders for the device, through the tests' writer: `{configtemplate, content}`."""
    return str(box.post(f"dcim/devices/{device}/render-config/", None, branch=schema_id)["content"])


def test_the_fixture_reads_to_its_devices_and_links(conn: NetBox, box: Writes, unprobed: ReaderDocument) -> None:
    doc = taken(read(conn, branch=None, scope=SCOPE, document=unprobed))
    assert blueprint.validate(doc) == []
    devices = doc["network"]["devices"]
    assert [device["name"] for device in devices] == DEVICES
    assert {device["platform"] for device in devices} == {"nokia_srlinux"}
    for device in devices:
        names = [interface["name"] for interface in device["interfaces"]]
        assert len(names) == 5 and names == sorted(names), device["name"]
    assert doc["network"]["links"] == LINKS
    assert doc["probes"] == []
    held = ids(box)
    assert configs(doc) == {name: rendered(box, held[name]) for name in DEVICES}
    assert doc["source"]["changelog"] == conn.latest(None)
    assert (doc["source"]["branch"], doc["source"]["scope"]) == (None, SCOPE)

    again = taken(read(conn, branch=None, scope=SCOPE, document=unprobed))
    assert but_observed(again) == but_observed(doc)
    assert blueprint.blueprint_id(again) == blueprint.blueprint_id(doc)


def test_a_branch_with_no_change_reads_to_mains_id(conn: NetBox, branch: Branch, unprobed: ReaderDocument) -> None:
    on_main = taken(read(conn, branch=None, scope=SCOPE, document=unprobed))
    on_branch = taken(read(conn, branch=branch.name, scope=SCOPE, document=unprobed))
    assert blueprint.blueprint_id(on_branch) == blueprint.blueprint_id(on_main)
    assert on_branch["source"]["branch"] == branch.name
    assert on_branch["source"]["changelog"] == conn.latest(branch)


def test_a_cable_made_on_a_branch_is_a_link_there_alone(
    conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    before = taken(read(conn, branch=branch.name, scope=SCOPE, document=unprobed))
    held = ids(box, branch.schema_id)
    ends = []
    for name in ("n1", "n3"):
        port = box.one("dcim/interfaces/", branch=branch.schema_id, device_id=held[name], name="ethernet-1/2")
        assert port is not None, name
        ends.append([{"object_type": "dcim.interface", "object_id": port["id"]}])
    box.post("dcim/cables/", {"a_terminations": ends[0], "b_terminations": ends[1]}, branch=branch.schema_id)

    on_branch = taken(read(conn, branch=branch.name, scope=SCOPE, document=unprobed))
    on_main = taken(read(conn, branch=None, scope=SCOPE, document=unprobed))
    assert on_branch["network"]["links"] == [LINKS[0], THIRD, LINKS[1]]
    assert on_main["network"]["links"] == LINKS
    moved = [name for name in DEVICES if configs(on_branch)[name] != configs(before)[name]]
    assert moved == ["n1", "n3"]
    assert configs(on_main) == configs(before)
    assert configs(on_branch) == {name: rendered(box, held[name], branch.schema_id) for name in DEVICES}


def test_a_render_that_reads_the_context_is_taken_verbatim(
    conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    """A template printing a key of the device's configuration context, which an active context made on the branch
    holds, and whether a key of the inactive `fylgja-probes` is defined: the key's value, and not defined
    (design/verified-facts.md, "A render of a template that reads the configuration context")."""
    value = PREFIX + secrets.token_hex(4)
    context = {"name": value, "is_active": True, "data": {"fylgja_contract_key": value}}
    box.post("extras/config-contexts/", context, branch=branch.schema_id)
    template = box.one("extras/config-templates/", branch=branch.schema_id, name="fylgja-srlinux")
    assert template is not None
    code = '{{ device.name }} {{ fylgja_contract_key }} {{ probes is defined }}{{ "\\n" }}'
    box.patch(f"extras/config-templates/{template['id']}/", {"template_code": code}, branch=branch.schema_id)

    doc = taken(read(conn, branch=branch.name, scope=SCOPE, document=unprobed))
    assert configs(doc) == {name: f"{name} {value} False\n" for name in DEVICES}


def test_a_scope_no_device_carries_is_empty(conn: NetBox, unprobed: ReaderDocument) -> None:
    result = read(conn, branch=None, scope="tag:fylgja-contract-none", document=unprobed)
    assert result.blueprint is None and result.empty is True
    assert errors(result) == [("scope.empty", "tag:fylgja-contract-none")]
