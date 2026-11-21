"""The one mapping of Nautobot's DCIM into blueprint 1's network (D-118, readers/nautobot/mapping.md), over rows built
in the tests: every list sorted and each link's ends ordered by the mapping itself, so the same rows in any order map
alike (D-006); a device's name made a DNS-1123 label (D-038); `enabled` and `mgmt_only` Nautobot's own; a cable the
blueprint cannot hold omitted, an info finding and a fidelity row; and a device with no package or no label refused."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from fake import DOCUMENT, MANUFACTURER, PLATFORM, THREE_NODE, FakeSource, listing, three_node

from fylgja_nautobot.mapping import (
    FIDELITY,
    LONGEST,
    MODEL,
    NOT_PORTS,
    READER,
    RULE_DUPLICATE,
    RULE_OMIT_ENDPOINT,
    RULE_OMIT_ENDS,
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
from fylgja_nautobot.rows import Cable, End, Manufacturer, Platform, Port

NETWORK = json.loads(THREE_NODE.read_text())["network"]
NAMES = {"device-1": "n1", "device-2": "n2", "device-3": "n3"}
L12 = "n1:ethernet-1/1|n2:ethernet-1/1"
"""The label a test gives the cable it puts in place of the fixture's first, `n1:ethernet-1/1` to `n2:ethernet-1/1`."""


def built(source: FakeSource) -> Mapped:
    return build(
        source.held_devices.items,
        source.held_platforms.items,
        source.held_manufacturers.items,
        source.held_ports.items,
        source.held_cables.items,
        DOCUMENT,
    )


def unconfigured() -> dict[str, Any]:
    """The fixture's network with each device's `config` removed: what the mapping builds before the renders."""
    devices = [{key: value for key, value in device.items() if key != "config"} for device in NETWORK["devices"]]
    return {"devices": devices, "links": NETWORK["links"]}


def network(mapped: Mapped) -> dict[str, Any]:
    return {"devices": list(mapped.devices), "links": list(mapped.links)}


def port(source: FakeSource, device: str, name: str) -> Port:
    """The port `name` of the device named `device` in `source`."""
    (held,) = [d.id for d in source.held_devices.items if d.name == device]
    (found,) = [p for p in source.held_ports.items if (p.device, p.name) == (held, name)]
    return found


def interface(source: FakeSource, device: str, name: str) -> End:
    """An end on the port `name` of the device `device`, as Nautobot answers one: no display text."""
    return End("dcim.interface", port(source, device, name).id, None)


def changed(source: FakeSource, called: str, /, **changes: Any) -> FakeSource:
    """`source` with the device named `called` changed by `changes`, its ports following it where its id changes."""
    (device,) = [d for d in source.held_devices.items if d.name == called]
    after = replace(device, **changes)
    source.held_devices = listing("dcim.device", [after if d == device else d for d in source.held_devices.items])
    ports = [replace(p, device=after.id) if p.device == device.id else p for p in source.held_ports.items]
    source.held_ports = listing("dcim.interface", ports)
    return source


def recabled(source: FakeSource, cable: Cable, *extra: Port) -> FakeSource:
    """`source` with `cable` in place of the fixture's first, each port it ends on carrying it, and `extra` ports
    added."""
    ends = {end.id for end in (*cable.a, *cable.b) if end.kind == "dcim.interface"}
    ports = []
    for held in [*source.held_ports.items, *extra]:
        on = cable.id if held.id in ends else None if held.cable == "cable-1" else held.cable
        ports.append(replace(held, cable=on))
    source.held_ports = listing("dcim.interface", ports)
    source.held_cables = listing("dcim.cable", [cable, *source.held_cables.items[1:]])
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
        ("omitted", "platform.version", "dcim.platform")
    ]
    assert FIDELITY[0]["reason"]
    assert (READER, MODEL, NOT_PORTS, LONGEST) == ("nautobot-dcim", "nautobot", ("virtual", "bridge", "lag"), 63)


def test_rows_in_any_order_map_alike() -> None:
    source = three_node()
    swapped = [replace(cable, a=cable.b, b=cable.a) for cable in source.held_cables.items[::-1]]
    assert swapped[-1].a[0].id == port(source, "n2", "ethernet-1/1").id, "the sides are swapped"
    again = build(
        source.held_devices.items[::-1],
        source.held_platforms.items[::-1],
        source.held_manufacturers.items[::-1],
        source.held_ports.items[::-1],
        swapped,
        DOCUMENT,
    )
    assert again == built(three_node())


def test_rows_in_any_order_map_alike_where_findings_are_filed() -> None:
    """Two devices renamed onto one label and a cable omitted: one `Mapped`, its findings and rows alike, whatever
    the order of the rows and whichever side of the cable is `a`."""
    source = three_node()
    lag = Port("interface-30", "device-2", "lag1", "lag", True, False, None)
    loose = End("dcim.interface", "interface-99", None)
    cable = Cable("cable-9", None, (End("dcim.interface", lag.id, None),), (loose,))
    source = recabled(changed(changed(source, "n1", name="N1"), "n3", name="n1"), cable, lag)
    swapped = [replace(c, a=c.b, b=c.a) for c in source.held_cables.items[::-1]]
    again = build(
        source.held_devices.items[::-1],
        source.held_platforms.items[::-1],
        source.held_manufacturers.items[::-1],
        source.held_ports.items[::-1],
        swapped,
        DOCUMENT,
    )
    mapped = built(source)
    assert again == mapped
    assert {f.rule for f in mapped.findings} == {RULE_DUPLICATE, RULE_OMIT_OUTSIDE}


def test_enabled_and_mgmt_only_are_nautobots_own() -> None:
    source = three_node()
    off, managed = port(source, "n2", "ethernet-1/10"), port(source, "n2", "ethernet-1/11")
    ports = [
        replace(p, enabled=False) if p == off else replace(p, mgmt_only=True) if p == managed else p
        for p in source.held_ports.items
    ]
    source.held_ports = listing("dcim.interface", ports)
    mapped = built(source)
    n2 = next(device for device in mapped.devices if device["name"] == "n2")
    assert n2["platform"] == "nokia_srlinux"
    assert [(f["name"], f["mgmt_only"], f["enabled"]) for f in n2["interfaces"]] == [
        ("ethernet-1/1", False, True),
        ("ethernet-1/10", False, False),
        ("ethernet-1/11", True, True),
        ("ethernet-1/2", False, True),
        ("mgmt0", True, True),
    ]
    assert [row for row in mapped.fidelity if row["object"] in ("interface.enabled", "interface.mgmt_only")] == []
    assert mapped.fidelity == FIDELITY
    assert mapped.findings == ()


def test_only_ports_are_interfaces() -> None:
    source = three_node()
    extra = [
        Port("interface-31", "device-1", "irb0", "virtual", True, False, None),
        Port("interface-32", "device-1", "br0", "bridge", True, False, None),
        Port("interface-33", "device-1", "lag1", "lag", True, False, None),
        Port("interface-34", "device-1", "ethernet-1/3", "25gbase-x-sfp28", True, False, None),
    ]
    source.held_ports = listing("dcim.interface", [*source.held_ports.items, *extra])
    mapped = built(source)
    assert mapped.findings == ()
    n1 = next(device for device in mapped.devices if device["name"] == "n1")
    assert [f["name"] for f in n1["interfaces"]] == [
        "ethernet-1/1",
        "ethernet-1/10",
        "ethernet-1/11",
        "ethernet-1/2",
        "ethernet-1/3",
        "mgmt0",
    ]
    assert network(mapped)["links"] == NETWORK["links"]


FRONT = End("dcim.frontport", "front-40", None)
LAG = Port("interface-30", "device-2", "lag1", "lag", True, False, None)
"""A LAG of `n2`'s, whose id no other port of the fixture holds."""
LOOSE = End("dcim.interface", "interface-99", None)
"""An interface of no port read."""


def omissions() -> dict[str, tuple[str, Cable, tuple[Port, ...]]]:
    """Each case: the rule, the cable in place of the fixture's first, and the ports added for it."""
    source = three_node()
    n1, n2 = interface(source, "n1", "ethernet-1/1"), interface(source, "n2", "ethernet-1/1")
    mgmt = interface(source, "n2", "mgmt0")
    lag = End("dcim.interface", LAG.id, None)
    return {
        "two on side a and no side b": (RULE_OMIT_ENDS, Cable("cable-9", L12, (n1, n2), ()), ()),
        "an end on a front port": (RULE_OMIT_ENDPOINT, Cable("cable-9", None, (n1,), (FRONT,)), ()),
        "an end on no port read": (RULE_OMIT_OUTSIDE, Cable("cable-9", L12, (n1,), (LOOSE,)), ()),
        "an end on a lag": (RULE_OMIT_OUTSIDE, Cable("cable-9", L12, (n1,), (lag,)), (LAG,)),
        "an end on a management port": (RULE_OMIT_MANAGEMENT, Cable("cable-9", L12, (n1,), (mgmt,)), ()),
        "two a side, one a front port": (RULE_OMIT_ENDS, Cable("cable-9", L12, (n1, FRONT), (n2, mgmt)), ()),
    }


@pytest.mark.parametrize("case", list(omissions()))
def test_a_cable_is_omitted_by_the_first_reason_that_applies(case: str) -> None:
    rule, cable, extra = omissions()[case]
    mapped = built(recabled(three_node(), cable, *extra))
    what = cable.label or "cable cable-9"
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [(rule, "info", what)]
    added = [row for row in mapped.fidelity if row not in FIDELITY]
    assert [(row["disposition"], row["object"], row["source"]) for row in added] == [("omitted", what, "dcim.cable")]
    assert added[0]["reason"]
    assert network(mapped) == {**unconfigured(), "links": NETWORK["links"][1:]}


def test_a_cable_is_judged_by_the_ends_it_has() -> None:
    """Task 3 leaves a breakout connector cabled to nothing out of a cable's ends (the ledger's R9), so a cable whose
    one interface a side is a link, however many connectors Nautobot held for it."""
    source = three_node()
    n1, n2 = interface(source, "n1", "ethernet-1/11"), interface(source, "n2", "ethernet-1/11")
    cable = Cable("cable-9", None, (n1,), (n2,))
    mapped = built(recabled(source, cable))
    assert mapped.findings == ()
    link = {"a": {"device": "n1", "interface": "ethernet-1/11"}, "b": {"device": "n2", "interface": "ethernet-1/11"}}
    assert link in mapped.links and len(mapped.links) == len(NETWORK["links"])


def test_a_cable_with_both_ends_on_one_device_is_a_link() -> None:
    source = three_node()
    n11, n10 = interface(source, "n1", "ethernet-1/11"), interface(source, "n1", "ethernet-1/10")
    loop = Cable("cable-9", None, (n11,), (n10,))
    mapped = built(recabled(source, loop))
    assert mapped.findings == ()
    looped = {"a": {"device": "n1", "interface": "ethernet-1/10"}, "b": {"device": "n1", "interface": "ethernet-1/11"}}
    assert list(mapped.links) == [looped, *NETWORK["links"][1:]]


def test_a_device_without_a_package_is_refused() -> None:
    source = three_node()
    nokia = Manufacturer("manufacturer-2", "Nokia")
    source.held_platforms = listing(
        "dcim.platform",
        [PLATFORM, Platform("platform-2", "SR Linux", None), Platform("platform-3", "SR OS", "manufacturer-3")],
    )
    source.held_manufacturers = listing("dcim.manufacturer", [MANUFACTURER, replace(nokia, id="manufacturer-3")])
    source = changed(source, "n1", platform=None)
    source = changed(changed(source, "n2", platform="platform-2"), "n3", platform="platform-3")
    mapped = built(source)
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [
        (RULE_PLATFORM_MISSING, "error", "n1"),
        (RULE_PLATFORM_MISSING, "error", "n2"),
        (RULE_PLATFORM_UNMATCHED, "error", "n3"),
    ]
    assert "SR Linux" in mapped.findings[1].message
    assert "Nokia" in mapped.findings[2].message and "SR OS" in mapped.findings[2].message
    assert (mapped.devices, mapped.links) == ((), ())
    assert mapped.fidelity == FIDELITY, "its cables are no omissions"
    assert mapped.names == NAMES, "a device's name is mapped whatever its platform"


def test_a_refused_devices_links_are_held_back() -> None:
    source = three_node()
    source.held_platforms = listing("dcim.platform", [PLATFORM, Platform("platform-3", "SR OS", MANUFACTURER.id)])
    mapped = built(changed(source, "n3", platform="platform-3"))
    assert [(f.rule, f.object) for f in mapped.findings] == [(RULE_PLATFORM_UNMATCHED, "n3")]
    assert [device["name"] for device in mapped.devices] == ["n1", "n2"]
    assert list(mapped.links) == NETWORK["links"][:1]
    assert mapped.fidelity == FIDELITY


def test_a_refused_devices_cables_are_still_judged_for_omission() -> None:
    """`n3`, refused by its platform, cabled to a front port and to `n1`'s management port: each files the omission
    it would file were `n3` sound (Constitution III), and `n3`'s cable to `n2`, which would be a link, files nothing
    and is no link."""
    source = three_node()
    source.held_platforms = listing("dcim.platform", [PLATFORM, Platform("platform-3", "SR OS", MANUFACTURER.id)])
    source = changed(source, "n3", platform="platform-3")
    first, _, third = source.held_cables.items
    front = Cable("cable-2", "n3-front", (interface(source, "n3", "ethernet-1/2"),), (FRONT,))
    managed = Cable(
        "cable-10", "n3-mgmt", (interface(source, "n3", "ethernet-1/10"),), (interface(source, "n1", "mgmt0"),)
    )
    source.held_cables = listing("dcim.cable", [first, front, third, managed])
    mapped = built(source)
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [
        (RULE_PLATFORM_UNMATCHED, "error", "n3"),
        (RULE_OMIT_ENDPOINT, "info", "n3-front"),
        (RULE_OMIT_MANAGEMENT, "info", "n3-mgmt"),
    ]
    reasons = {row["object"]: row["reason"] for row in mapped.fidelity if row not in FIDELITY}
    assert sorted(reasons) == ["n3-front", "n3-mgmt"]
    assert "dcim.frontport front-40" in reasons["n3-front"]
    assert "n1:mgmt0" in reasons["n3-mgmt"]
    assert [device["name"] for device in mapped.devices] == ["n1", "n2"]
    assert list(mapped.links) == NETWORK["links"][:1]


def test_an_end_outside_the_scope_is_judged_before_a_management_end() -> None:
    source = three_node()
    cable = Cable("cable-9", L12, (interface(source, "n2", "mgmt0"),), (LOOSE,))
    mapped = built(recabled(source, cable))
    assert [(f.rule, f.object) for f in mapped.findings] == [(RULE_OMIT_OUTSIDE, L12)]
    (row,) = [row for row in mapped.fidelity if row not in FIDELITY]
    assert "dcim.interface interface-99" in row["reason"]
    assert "management" not in row["reason"]


def test_a_renamed_device_is_recorded_and_its_links_follow() -> None:
    mapped = built(changed(three_node(), "n1", name="N1"))
    assert network(mapped) == unconfigured()
    assert mapped.names == NAMES
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [(RULE_RENAMED, "info", "N1")]
    assert "n1" in mapped.findings[0].message
    (row,) = [row for row in mapped.fidelity if row not in FIDELITY]
    assert (row["disposition"], row["object"], row["source"]) == ("approximated", "N1", "dcim.device.name")
    assert "n1" in row["reason"]
    assert mapped.links[0]["a"] == {"device": "n1", "interface": "ethernet-1/1"}


def test_two_devices_of_one_label_are_refused() -> None:
    mapped = built(changed(three_node(), "n2", name="N1"))
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [
        (RULE_DUPLICATE, "error", "N1"),
        (RULE_DUPLICATE, "error", "n1"),
    ]
    for finding in mapped.findings:
        assert "N1" in finding.message and "n1" in finding.message
    assert mapped.names == {"device-3": "n3"}
    assert [device["name"] for device in mapped.devices] == ["n3"]
    assert mapped.links == ()
    assert mapped.fidelity == FIDELITY


def test_two_devices_of_one_exact_name_are_refused() -> None:
    """Each finding names its own device first, and a name two devices share with its id, so that the two differ."""
    mapped = built(changed(three_node(), "n2", name="n1"))
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [
        (RULE_DUPLICATE, "error", "n1"),
        (RULE_DUPLICATE, "error", "n1"),
    ]
    first, second = mapped.findings
    assert first.message.startswith("Device n1 (dcim.device device-1) ")
    assert "n1 (dcim.device device-2)" in first.message
    assert second.message.startswith("Device n1 (dcim.device device-2) ")
    assert "n1 (dcim.device device-1)" in second.message
    assert mapped.names == {"device-3": "n3"}


@pytest.mark.parametrize(
    "name", ["a" * 64, "***", None, ""], ids=["64 characters", "no letter or digit", "no name", "an empty name"]
)
def test_a_device_that_makes_no_label_is_unmappable(name: str | None) -> None:
    mapped = built(changed(three_node(), "n3", name=name, id="device-7"))
    what = name if name else "dcim.device device-7"
    assert [(f.rule, f.severity, f.object) for f in mapped.findings] == [(RULE_UNMAPPABLE, "error", what)]
    assert mapped.names == {"device-1": "n1", "device-2": "n2"}
    assert [device["name"] for device in mapped.devices] == ["n1", "n2"]
    assert list(mapped.links) == NETWORK["links"][:1]
    assert mapped.fidelity == FIDELITY


def test_a_name_of_63_characters_is_a_label() -> None:
    mapped = built(changed(three_node(), "n3", name="a" * 63))
    assert mapped.findings == ()
    assert mapped.names["device-3"] == "a" * 63


@pytest.mark.parametrize("name", [None, ""])
def test_a_device_with_no_name_is_named_by_its_id_in_its_platforms_finding(name: str | None) -> None:
    mapped = built(changed(three_node(), "n3", name=name, id="device-7", platform=None))
    assert [(f.rule, f.object) for f in mapped.findings] == [
        (RULE_UNMAPPABLE, "dcim.device device-7"),
        (RULE_PLATFORM_MISSING, "dcim.device device-7"),
    ]


def test_a_device_with_no_name_is_named_by_its_id_where_its_platform_is_unmatched() -> None:
    source = three_node()
    source.held_platforms = listing("dcim.platform", [PLATFORM, Platform("platform-3", "SR OS", MANUFACTURER.id)])
    mapped = built(changed(source, "n3", name=None, id="device-7", platform="platform-3"))
    assert [(f.rule, f.object) for f in mapped.findings] == [
        (RULE_UNMAPPABLE, "dcim.device device-7"),
        (RULE_PLATFORM_UNMATCHED, "dcim.device device-7"),
    ]
    assert "SR OS" in mapped.findings[1].message


def test_devices_sort_by_their_blueprint_names() -> None:
    """`Z1` sorts before `a1` by code point and after it by label: the network is in the labels' order, and so is
    each link's pair of ends."""
    mapped = built(changed(changed(three_node(), "n1", name="Z1"), "n2", name="a1"))
    assert [device["name"] for device in mapped.devices] == ["a1", "n3", "z1"]
    assert [(link["a"]["device"], link["b"]["device"]) for link in mapped.links] == [
        ("a1", "z1"),
        ("a1", "n3"),
        ("n3", "z1"),
    ]
