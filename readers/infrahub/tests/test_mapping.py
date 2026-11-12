"""The one mapping of the DCIM library into blueprint 1's network (D-082, readers/infrahub/mapping.md), over rows
built in the tests: every list sorted and each link's ends ordered by the mapping itself, so the same rows in any order
map alike (D-006); a device's name made a DNS-1123 label (D-038); and what it cannot place omitted, an info finding
and a fidelity row, while a device no package is chosen for is refused."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import pytest
from fake import DOCUMENT, THREE_NODE, FakeSource, listing, three_node

from fylgja_infrahub.mapping import (
    FIDELITY,
    RULE_DUPLICATE,
    RULE_OMIT_ENDPOINT,
    RULE_OMIT_ENDS,
    RULE_OMIT_KIND,
    RULE_OMIT_MANAGEMENT,
    RULE_OMIT_OUTSIDE,
    RULE_PLATFORM_MISSING,
    RULE_PLATFORM_UNMATCHED,
    RULE_RENAMED,
    RULE_UNMAPPABLE,
    Mapped,
    build,
    label,
)
from fylgja_infrahub.rows import Connector, End, Listing

BRANCH = "main"
AT = "2026-11-09T10:00:00.000000+00:00"
NETWORK = json.loads(THREE_NODE.read_text())["network"]
NAMES = {"device-n1": "n1", "device-n2": "n2", "device-n3": "n3"}
L12 = "n1:ethernet-1/1|n2:ethernet-1/1"
"""The fixture's first cable, by the label `three_node` gives it."""


def built(source: FakeSource) -> Mapped:
    return build(source.held_devices.items, source.held_ports.items, DOCUMENT, branch=BRANCH, at=AT)


def unconfigured() -> dict[str, Any]:
    """The fixture's network with each device's `config` removed: what the mapping builds before the artifacts."""
    devices = [{key: value for key, value in device.items() if key != "config"} for device in NETWORK["devices"]]
    return {"devices": devices, "links": NETWORK["links"]}


def network(mapped: Mapped) -> dict[str, Any]:
    return {"devices": list(mapped.devices), "links": list(mapped.links)}


def end(device: str, port: str) -> End:
    """An end on the port `port` of the device `device`, as `three_node` ids them."""
    return End(f"port-{device}-{port}", "InterfacePhysical", f"device-{device}", port)


def renamed(source: FakeSource, name: str, to: str, **changes: Any) -> FakeSource:
    """`source` with the device `name` called `to` in Infrahub, and its other fields changed by `changes`."""
    items = [replace(d, name=to, **changes) if d.name == name else d for d in source.held_devices.items]
    source.held_devices = listing("DcimDevice", items)
    return source


def recabled(source: FakeSource, cable: str, connector: Connector | None, at: Sequence[str]) -> FakeSource:
    """`source` with the cable labelled `cable` taken off every port, and `connector` on the ports `at`, each
    `device:port`."""
    items = []
    for port in source.held_ports.items:
        held = port.connector if port.connector is None or port.connector.label != cable else None
        if f"{port.device.removeprefix('device-')}:{port.name}" in at:
            held = connector
        items.append(replace(port, connector=held))
    source.held_ports = listing("InterfacePhysical", items)
    return source


def test_label() -> None:
    assert label("N1") == "n1"
    assert label("core1.lon.example") == "core1-lon-example"
    assert label("sw_01 (lab)") == "sw-01-lab"
    assert label("n1") == "n1"


def test_three_node_maps_to_the_fixtures_network() -> None:
    mapped = built(three_node())
    assert network(mapped) == unconfigured()
    assert mapped.names == NAMES
    assert mapped.fidelity == FIDELITY
    assert mapped.findings == ()
    assert [(row["disposition"], row["object"], row["source"]) for row in FIDELITY] == [
        ("approximated", "interface.enabled", "InterfacePhysical.status"),
        ("approximated", "interface.mgmt_only", "InterfacePhysical.role"),
        ("omitted", "platform.version", "DcimPlatform"),
    ]


def test_rows_in_any_order_map_alike() -> None:
    source = three_node()
    flipped = [
        replace(p, connector=replace(p.connector, ends=replace(p.connector.ends, items=p.connector.ends.items[::-1])))
        if p.connector is not None
        else p
        for p in source.held_ports.items[::-1]
    ]
    n1 = next(p for p in flipped if p.id == "port-n1-ethernet-1/1")
    assert n1.connector is not None and n1.connector.ends.items[0].device == "device-n2", "the ends are reversed"
    assert build(source.held_devices.items[::-1], flipped, DOCUMENT, branch=BRANCH, at=AT) == built(three_node())


def ends_of(*ends: End) -> Listing[End]:
    return listing(f"{L12}.connected_endpoints", ends)


VIRTUAL = End("virtual-n2-lo0", "InterfaceVirtual", None, None)
FOREIGN = End("port-x9-e1", "InterfacePhysical", "device-x9", "e1")
OMISSIONS = {
    # The connector is no cable, reached from both its ports.
    RULE_OMIT_KIND: (
        Connector("circuit-1", "DcimCircuit", L12, ends_of(end("n1", "ethernet-1/1"), end("n2", "ethernet-1/1"))),
        ("n1:ethernet-1/1", "n2:ethernet-1/1"),
    ),
    # Three ends listed of three, reached from each: not two. Two listed of three is read.incomplete (test_artifacts).
    RULE_OMIT_ENDS: (
        Connector(
            "cable-3",
            "DcimCable",
            L12,
            ends_of(end("n1", "ethernet-1/1"), end("n2", "ethernet-1/1"), end("n3", "ethernet-1/10")),
        ),
        ("n1:ethernet-1/1", "n2:ethernet-1/1", "n3:ethernet-1/10"),
    ),
    # An end on a virtual interface, the cable reached from its one physical port.
    RULE_OMIT_ENDPOINT: (
        Connector("cable-v", "DcimCable", L12, ends_of(end("n1", "ethernet-1/1"), VIRTUAL)),
        ("n1:ethernet-1/1",),
    ),
    # An end on a device the scope does not hold, the cable reached from the port that it does.
    RULE_OMIT_OUTSIDE: (
        Connector("cable-x", "DcimCable", L12, ends_of(end("n1", "ethernet-1/1"), FOREIGN)),
        ("n1:ethernet-1/1",),
    ),
    # Two management ports, reached from both: blueprint 1 refuses a link on either.
    RULE_OMIT_MANAGEMENT: (
        Connector("cable-m", "DcimCable", L12, ends_of(end("n1", "mgmt0"), end("n2", "mgmt0"))),
        ("n1:mgmt0", "n2:mgmt0"),
    ),
}


@pytest.mark.parametrize("rule", list(OMISSIONS))
def test_a_cable_is_omitted_by_the_first_reason_that_applies(rule: str) -> None:
    connector, at = OMISSIONS[rule]
    mapped = built(recabled(three_node(), L12, connector, at))
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [(rule, "info", L12)], "judged once"
    for held in (BRANCH, AT):
        assert held in mapped.findings[0].message
    added = [row for row in mapped.fidelity if row not in FIDELITY]
    assert [(row["disposition"], row["object"], row["source"]) for row in added] == [
        ("omitted", L12, connector.kind)
    ]
    assert added[0]["reason"]
    assert network(mapped) == {**unconfigured(), "links": NETWORK["links"][1:]}


MANAGED = end("n2", "mgmt0")
BOTH = {
    RULE_OMIT_KIND: Connector("circuit-3", "DcimCircuit", L12, ends_of(end("n1", "ethernet-1/1"), VIRTUAL, FOREIGN)),
    RULE_OMIT_ENDS: Connector("cable-3v", "DcimCable", L12, ends_of(end("n1", "ethernet-1/1"), VIRTUAL, FOREIGN)),
    RULE_OMIT_ENDPOINT: Connector("cable-vx", "DcimCable", L12, ends_of(VIRTUAL, FOREIGN)),
    RULE_OMIT_OUTSIDE: Connector("cable-xm", "DcimCable", L12, ends_of(MANAGED, FOREIGN)),
}


@pytest.mark.parametrize("rule", list(BOTH))
def test_the_first_reason_is_filed_where_several_apply(rule: str) -> None:
    """Each connector here has the reason of its own row and of the next, and is filed under its own alone."""
    mapped = built(recabled(three_node(), L12, BOTH[rule], ("n1:ethernet-1/1", "n2:mgmt0")))
    assert [(f.rule, f.object) for f in mapped.findings] == [(rule, L12)]


def test_the_omissions_fidelity_rows_sort_among_the_rows_of_every_read() -> None:
    connector, at = OMISSIONS[RULE_OMIT_MANAGEMENT]
    mapped = built(recabled(three_node(), L12, connector, at))
    keys = [(row["disposition"], row["object"], row["source"], row["reason"]) for row in mapped.fidelity]
    assert keys == sorted(keys)
    assert len(keys) == 4


def test_a_cable_with_both_ends_on_one_device_is_a_link() -> None:
    loop = "n1:ethernet-1/11|n1:ethernet-1/10"
    ends = listing(f"{loop}.connected_endpoints", [end("n1", "ethernet-1/11"), end("n1", "ethernet-1/10")])
    connector = Connector("cable-loop", "DcimCable", loop, ends)
    mapped = built(recabled(three_node(), loop, connector, ("n1:ethernet-1/10", "n1:ethernet-1/11")))
    assert mapped.findings == ()
    looped = {"a": {"device": "n1", "interface": "ethernet-1/10"}, "b": {"device": "n1", "interface": "ethernet-1/11"}}
    assert list(mapped.links) == [NETWORK["links"][0], looped, *NETWORK["links"][1:]]


def test_a_device_without_a_package_is_refused() -> None:
    source = three_node()
    source = renamed(source, "n1", "n1", platform=None, manufacturer=None)
    source = renamed(source, "n2", "n2", manufacturer=None)
    source = renamed(source, "n3", "n3", platform="SR OS")
    mapped = built(source)
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [
        (RULE_PLATFORM_MISSING, "error", "n1"),
        (RULE_PLATFORM_MISSING, "error", "n2"),
        (RULE_PLATFORM_UNMATCHED, "error", "n3"),
    ]
    for finding in mapped.findings:
        assert BRANCH in finding.message and AT in finding.message
    assert "SR Linux" in mapped.findings[1].message
    assert "Nokia" in mapped.findings[2].message and "SR OS" in mapped.findings[2].message
    assert (mapped.devices, mapped.links) == ((), ())
    assert mapped.names == NAMES, "a device's name is mapped whatever its platform"


def test_devices_sort_by_their_blueprint_names() -> None:
    """`Z1` sorts before `a1` by code point and after it by label: the network is in the labels' order, and so is
    each link's pair of ends."""
    mapped = built(renamed(renamed(three_node(), "n1", "Z1"), "n2", "a1"))
    assert [device["name"] for device in mapped.devices] == ["a1", "n3", "z1"]
    assert [(link["a"]["device"], link["b"]["device"]) for link in mapped.links] == [
        ("a1", "z1"),
        ("a1", "n3"),
        ("n3", "z1"),
    ]
    assert mapped.links[0] == {
        "a": {"device": "a1", "interface": "ethernet-1/1"},
        "b": {"device": "z1", "interface": "ethernet-1/1"},
    }


def test_a_renamed_device_is_recorded_and_its_links_follow() -> None:
    mapped = built(renamed(three_node(), "n1", "N1"))
    assert network(mapped) == unconfigured()
    assert mapped.names == NAMES
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [(RULE_RENAMED, "info", "N1")]
    assert "n1" in mapped.findings[0].message and BRANCH in mapped.findings[0].message
    (row,) = [row for row in mapped.fidelity if row not in FIDELITY]
    assert (row["disposition"], row["object"], row["source"]) == ("approximated", "N1", "DcimDevice.name")
    assert "n1" in row["reason"]
    assert mapped.links[0]["a"] == {"device": "n1", "interface": "ethernet-1/1"}


def test_two_devices_of_one_label_are_refused() -> None:
    mapped = built(renamed(three_node(), "n2", "N1"))
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [
        (RULE_DUPLICATE, "error", "N1"),
        (RULE_DUPLICATE, "error", "n1"),
    ]
    for finding in mapped.findings:
        assert "N1" in finding.message and "n1" in finding.message and AT in finding.message
    assert mapped.names == {"device-n3": "n3"}
    assert [device["name"] for device in mapped.devices] == ["n3"]
    assert mapped.links == ()


@pytest.mark.parametrize("name", ["a" * 64, "***"], ids=["64 characters", "no letter or digit"])
def test_a_name_that_is_no_label_is_refused(name: str) -> None:
    mapped = built(renamed(three_node(), "n3", name))
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [(RULE_UNMAPPABLE, "error", name)]
    assert BRANCH in mapped.findings[0].message
    assert "device-n3" not in mapped.names
    assert [device["name"] for device in mapped.devices] == ["n1", "n2"]
    assert list(mapped.links) == NETWORK["links"][:1]


def test_a_name_of_63_characters_is_a_label() -> None:
    mapped = built(renamed(three_node(), "n3", "a" * 63))
    assert mapped.findings == ()
    assert mapped.names["device-n3"] == "a" * 63


def test_a_device_is_built_from_its_own_rows_alone() -> None:
    """Each device's interfaces are its own ports, physical ones alone, `mgmt_only` from the role and `enabled` from
    the status (mapping.md)."""
    source = three_node()
    ports = [
        replace(p, status="disabled") if (p.device, p.name) == ("device-n2", "ethernet-1/10") else p
        for p in source.held_ports.items
    ]
    source.held_ports = listing("InterfacePhysical", ports)
    mapped = built(source)
    n2 = next(device for device in mapped.devices if device["name"] == "n2")
    assert n2["platform"] == "nokia_srlinux"
    assert [(f["name"], f["mgmt_only"], f["enabled"]) for f in n2["interfaces"]] == [
        ("ethernet-1/1", False, True),
        ("ethernet-1/10", False, False),
        ("ethernet-1/11", False, True),
        ("ethernet-1/2", False, True),
        ("mgmt0", True, True),
    ]
