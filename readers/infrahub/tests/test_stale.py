"""A configuration older than its intent is refused by device (D-082), over a `FakeSource` of rows built in the tests:
the intent a configuration renders from is spread over the device, its platform, its manufacturer, its interfaces of
either kind, their addresses and its cables, each read by its stamp, a write by the task workers' account counted at
the node's creation and one by `__system__` never so, and the branch's events beside them; it is
judged against the selected artifact's checksum stamp, or the `generated_since` given where that is later. `head` is
the first instant after the branch's latest write, counting every stamp and every event (design/verified-facts.md,
"Infrahub 1.11.11", "What a stale rule can be built on")."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from fake import (
    ADMIN,
    BRANCHED,
    DOCUMENT,
    MANUFACTURER,
    OWN,
    PLATFORM,
    T0,
    FakeSource,
    G,
    dcim_schema,
    listing,
    probed_schema,
    stamp,
    three_node,
)

from fylgja_infrahub import Refused, head, read, stale
from fylgja_infrahub.artifacts import RULE_UNREADY
from fylgja_infrahub.read import RULE_SCOPE_EMPTY, RULE_SCOPE_INVALID, Result
from fylgja_infrahub.rows import (
    RULE_INCOMPLETE,
    CableEnd,
    CableStamp,
    Event,
    Generated,
    Group,
    Listing,
    Stamp,
    Stamped,
)
from fylgja_infrahub.stale import RULE_STALE
from fylgja_infrahub.times import RULE_INVALID as RULE_AT_INVALID

AT = "2026-11-09T10:01:00.000000+00:00"
"""The time every read here is pinned at: after every stamp and event of `three_node`, and of each test's own."""
LATER = "2026-11-09T10:00:05.000000+00:00"
"""A write after every artifact was generated at `G`."""
SYSTEM = "__system__"
"""The account Infrahub names for an operator's address create and edit."""
L12 = "n1:ethernet-1/1|n2:ethernet-1/1"


def ran(source: FakeSource, **given: Any) -> Result:
    asked: dict[str, Any] = {"branch": "main", "at": AT, "scope": "tag:fylgja", "document": DOCUMENT, **given}
    return read(source, **asked)


def errors(result: Result) -> list[tuple[str, str | None]]:
    return [(f.rule, f.object) for f in result.findings if f.severity == "error"]


def stale_of(result: Result) -> list[str | None]:
    """The devices `result` refuses as stale, by name."""
    return [f.object for f in result.findings if f.rule == RULE_STALE]


def row(source: FakeSource, name: str) -> Stamped:
    return next(d for d in source.held_stamps.items if d.name == name)


def put(source: FakeSource, changed: Stamped) -> None:
    source.held_stamps = listing(
        "DcimDevice", [changed if d.id == changed.id else d for d in source.held_stamps.items]
    )


def own(source: FakeSource, name: str, changed: Stamp) -> None:
    """The device `name`'s own stamp, on its edge, `changed`."""
    held = row(source, name)
    put(source, dataclasses.replace(held, own=changed))


def platform(source: FakeSource, changed: Stamp) -> None:
    """The platform's node stamp `changed`, on every device's `platform` edge, since they share it."""
    for held in source.held_stamps.items:
        put(source, dataclasses.replace(held, shared=(changed, held.shared[1])))


def manufacturer(source: FakeSource, changed: Stamp) -> None:
    for held in source.held_stamps.items:
        put(source, dataclasses.replace(held, shared=(held.shared[0], changed)))


def names_at(source: FakeSource, *, platform: str | None = None, manufacturer: str | None = None) -> None:
    """When the platform's `name` and the manufacturer's were last written, `platform` and `manufacturer` where each
    is given, on every device, since they share them."""
    for held in source.held_stamps.items:
        at = (platform or held.platform_name_at, manufacturer or held.manufacturer_name_at)
        put(source, dataclasses.replace(held, platform_name_at=at[0], manufacturer_name_at=at[1]))


def interface(source: FakeSource, name: str, port: str, changed: Stamp) -> None:
    held = row(source, name)
    items = [(i, changed if i == f"port-{name}-{port}" else s) for i, s in held.interfaces.items]
    put(source, dataclasses.replace(held, interfaces=listing(f"{name}.interfaces", items)))


def virtual(source: FakeSource, name: str, changed: Stamp) -> None:
    """A virtual interface added to the device `name`, stamped `changed`: the stamps read takes interfaces of either
    kind, and the mapping none but physical ports."""
    held = row(source, name)
    added = f"virtual-{name}-lo0"
    items = [*held.interfaces.items, (added, changed)]
    put(source, dataclasses.replace(held, ids=(*held.ids, added), interfaces=listing(f"{name}.interfaces", items)))


def address(source: FakeSource, name: str, port: str, changed: Stamp, *, on: str | None = None) -> None:
    """An address under the device `name`'s port `port`, or under the interface whose id is `on`, stamped `changed`."""
    held = row(source, name)
    added = f"address-{name}-{port}"
    items = [*held.addresses.items, (on or f"port-{name}-{port}", added, changed)]
    put(source, dataclasses.replace(held, ids=(*held.ids, added), addresses=listing(f"{name}.ip_addresses", items)))


def cable(source: FakeSource, label: str, changed: Stamp) -> None:
    """The cable `label`'s stamp `changed`, on the `connector` edge of each port it ends."""
    items = [dataclasses.replace(c, stamp=changed) if c.id == f"cable-{label}" else c for c in source.held_cables.items]
    source.held_cables = listing("InterfacePhysical.connector", items)


def named(source: FakeSource, end: str, *, name_at: str | None = None, device_name_at: str | None = None) -> None:
    """The cable end whose id is `end`: its `name` written at `name_at`, and its device's at `device_name_at`, where
    each is given, as each port of its cable reads them, since one node answers alike from either side."""
    items = []
    for held in source.held_cables.items:
        ends = [
            dataclasses.replace(
                e, name_at=name_at or e.name_at, device_name_at=device_name_at or e.device_name_at
            )
            if e.id == end
            else e
            for e in held.ends.items
        ]
        items.append(dataclasses.replace(held, ends=dataclasses.replace(held.ends, items=tuple(ends))))
    source.held_cables = listing("InterfacePhysical.connector", items)


def outside(source: FakeSource, name: str, port: str) -> None:
    """A cable from the device `name`'s port `port` to `port-x9-1`, on `device-x9`, a device the scope does not hold."""
    near = CableEnd(f"port-{name}-{port}", T0, f"device-{name}", T0)
    ends = listing("cable-out.connected_endpoints", [near, CableEnd("port-x9-1", T0, "device-x9", T0)])
    added = CableStamp("cable-out", near.id, f"device-{name}", stamp(), ends)
    source.held_cables = listing("InterfacePhysical.connector", [*source.held_cables.items, added])


def generated(source: FakeSource, name: str, checksum_at: str | None) -> None:
    held = row(source, name)
    artifacts = [dataclasses.replace(g, checksum_at=checksum_at) for g in held.artifacts.items]
    put(source, dataclasses.replace(held, artifacts=listing(f"{name}.artifacts", artifacts)))


def event(
    occurred_at: str = "2026-11-09T10:00:07.000000+00:00",
    *,
    name: str = "infrahub.node.updated",
    mutated: bool = True,
    kind: str | None = "DcimDevice",
    primary: str | None = "device-n1",
    account: str | None = ADMIN,
    attributes: tuple[str, ...] = (),
    relationships: tuple[tuple[str, str | None], ...] = (),
    related: tuple[str, ...] = (),
    branch: str = "main",
) -> Event:
    """An event of the branch's log: by default the operator's update of `n1` on `main`, naming nothing it changed."""
    return Event(
        f"event-{occurred_at}-{primary}-{branch}",
        name,
        occurred_at,
        mutated,
        kind,
        primary,
        account,
        attributes,
        relationships,
        related,
        branch,
    )


def logged(source: FakeSource, *events: Event) -> None:
    source.held_events = listing("InfrahubEvent", events)


def test_a_scope_generated_after_its_last_write_is_fresh() -> None:
    source = three_node()
    result = ran(source)
    assert (result.findings, result.empty) == ((), False)
    assert result.blueprint is not None
    assert source.events_asked == [(BRANCHED, G)]
    assert [call for call in source.calls if call[0] in ("stamps", "cable_stamps", "groups")] == [
        ("stamps", "main", AT),
        ("cable_stamps", "main", AT),
        ("groups", "main", AT),
    ]


def test_a_device_edited_after_its_generation_is_stale() -> None:
    source = three_node()
    own(source, "n1", stamp(LATER))
    result = ran(source)
    assert result.blueprint is None
    assert [(f.rule, f.severity, f.object) for f in result.findings] == [(RULE_STALE, "error", "n1")]
    message = result.findings[0].message
    for held in (LATER, G, "main", AT, "regenerate", "generated_since"):
        assert held in message
    assert RULE_STALE == "artifact.stale"


def test_generated_since_stands_for_the_checksum_stamp_where_it_is_later() -> None:
    source = three_node()
    own(source, "n1", stamp(LATER))
    without = ran(source)
    assert ran(source, generated_since=LATER).findings == ()
    assert ran(source, generated_since="2026-11-09T10:00:06.000000Z").findings == ()
    just_before = ran(source, generated_since="2026-11-09T10:00:04.999999+00:00")
    assert stale_of(just_before) == ["n1"]
    assert "2026-11-09T10:00:04.999999+00:00" in just_before.findings[0].message
    assert G in just_before.findings[0].message
    earlier = ran(source, generated_since="2026-11-09T10:00:00.500000+00:00")
    assert earlier.findings == without.findings


@pytest.mark.parametrize(
    ("alter", "refused"),
    [
        (lambda source: names_at(source, platform=LATER), ["n1", "n2", "n3"]),
        (lambda source: names_at(source, manufacturer=LATER), ["n1", "n2", "n3"]),
        (lambda source: interface(source, "n2", "ethernet-1/1", stamp(LATER)), ["n2"]),
        (lambda source: virtual(source, "n3", stamp(LATER)), ["n3"]),
        (lambda source: cable(source, L12, stamp(LATER)), ["n1", "n2"]),
    ],
    ids=["the platform's name", "the manufacturer's name", "an interface's", "a virtual interface's", "a cable's"],
)
def test_each_source_of_intent_moves_its_devices_alone(alter: Any, refused: list[str]) -> None:
    source = three_node()
    alter(source)
    result = ran(source)
    assert errors(result) == [(RULE_STALE, name) for name in refused]
    assert all(LATER in f.message for f in result.findings)


def test_the_platforms_and_manufacturers_node_stamps_are_no_intent() -> None:
    """A device made on the platform moves the platform's node stamp, which every device reads on its `platform` edge,
    and not the platform's `name` stamp (design/verified-facts.md, "The platform's node stamp moves with a device made
    on it"); the configuration renders the platform and the manufacturer by their names alone, so their node stamps
    make no device stale, and `head` counts them, nothing discounted (P3-44)."""
    source = three_node()
    platform(source, stamp(LATER))
    manufacturer(source, stamp(LATER))
    assert ran(source).findings == ()
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:05.000001+00:00"


def test_the_workers_own_write_is_not_intent() -> None:
    """The task workers' account restamps every node that joins a query group at the generation that reads it, after
    the checksum: its write is counted at the node's creation (design/verified-facts.md, "Infrahub's own account")."""
    source = three_node()
    own(source, "n1", stamp("2026-11-09T10:00:06.000000+00:00", OWN, T0))
    assert ran(source).findings == ()
    own(source, "n1", stamp("2026-11-09T10:00:06.000000+00:00", ADMIN, T0))
    assert stale_of(ran(source)) == ["n1"]


def test_a_removal_no_stamp_records_is_seen_by_its_event() -> None:
    """A port deleted names its device in its related nodes, as a port's event does; no stamp moved."""
    source = three_node()
    deleted = event(
        name="infrahub.node.deleted",
        kind="InterfacePhysical",
        primary="port-n1-gone",
        relationships=(("device", "device-n1"),),
        related=("device-n1",),
    )
    logged(source, deleted)
    result = ran(source)
    assert errors(result) == [(RULE_STALE, "n1")]
    for held in ("infrahub.node.deleted", "InterfacePhysical", "2026-11-09T10:00:07.000000+00:00", G):
        assert held in result.findings[0].message


def test_a_relationship_peer_alone_names_no_device() -> None:
    """The rule names a device by an event's primary node or its related nodes (P2-25, P2-30). A relationship's peer
    alone does not: a device made elsewhere on the scope's platform names the platform as its peer, and would make
    every device on it stale."""
    source = three_node()
    assert PLATFORM in row(source, "n1").ids
    logged(source, event(name="infrahub.node.created", primary="device-n9", relationships=(("platform", PLATFORM),)))
    assert ran(source).findings == ()


def test_a_device_made_on_the_scopes_platform_makes_no_other_device_stale() -> None:
    """A device made on the branch names each peer it was made with in its event's related nodes, the platform among
    them (design/verified-facts.md, "A device made on the scope's platform"). The platform and its manufacturer are
    every scoped device's, and count through an event whose primary node they are alone (P3-25): an event's related
    nodes are matched to a device's own nodes, the device, its interfaces, its addresses and its cables (P3-42)."""
    source = three_node()
    assert {PLATFORM, MANUFACTURER} <= set(row(source, "n1").ids)
    peers = (("tags", "tag-fylgja"), ("platform", PLATFORM), ("location", "site-lab"))
    related = tuple(peer for _, peer in peers)
    made = event(name="infrahub.node.created", primary="device-n9", relationships=peers, related=related)
    logged(source, made)
    assert ran(source).findings == ()
    logged(source, dataclasses.replace(made, related=(MANUFACTURER,)))
    assert ran(source).findings == ()
    logged(source, event(kind="DcimPlatform", primary=PLATFORM, attributes=("name",)))
    assert stale_of(ran(source)) == ["n1", "n2", "n3"], "the platform's own write"


def test_an_event_naming_a_port_in_its_related_nodes_is_its_devices() -> None:
    """A cable's ends taken off it on the branch: no stamp moves, and the cable's event names both ports in its related
    nodes (design/verified-facts.md, "The same cable's ends removed instead"), each one of its device's own nodes."""
    source = three_node()
    ends = ("port-n1-ethernet-1/2", "port-n2-ethernet-1/10")
    removed = tuple(("connected_endpoints", end) for end in ends)
    logged(source, event(kind="DcimCable", primary="cable-gone", relationships=removed, related=ends))
    assert stale_of(ran(source)) == ["n1", "n2"]


def test_a_relationship_removed_moves_a_stamp_back_and_its_event_counts() -> None:
    """A relationship removed on the branch that added it moves the device's stamp back, and only its event shows the
    removal (design/verified-facts.md, "Which stamps each write moved")."""
    source = three_node()
    own(source, "n1", stamp("2026-11-09T09:59:00.000000+00:00"))
    logged(source, event(relationships=(("tags", "tag-branch"),)))
    assert stale_of(ran(source)) == ["n1"]


def test_an_address_edited_on_a_port_is_intent() -> None:
    """An address's edit moves its own stamp alone, under its port's `ip_addresses`, written as `__system__`, and its
    event names no port and no device (design/verified-facts.md, "What a stale rule can be built on")."""
    source = three_node()
    address(source, "n1", "ethernet-1/2", stamp(LATER, SYSTEM, T0))
    result = ran(source)
    assert errors(result) == [(RULE_STALE, "n1")]
    assert LATER in result.findings[0].message


def test_an_address_edit_is_seen_by_its_event_naming_the_address_alone() -> None:
    source = three_node()
    address(source, "n1", "ethernet-1/2", stamp())
    logged(source, event(kind="IpamIPAddress", primary="address-n1-ethernet-1/2", attributes=("address",)))
    assert stale_of(ran(source)) == ["n1"]


def test_system_is_never_discounted() -> None:
    """`__system__` is the account Infrahub names on an operator's address create and edit, and nothing but its name
    tells an account (design/verified-facts.md, "Nothing but its name tells the account")."""
    source = three_node()
    own(source, "n1", stamp(LATER, SYSTEM, T0))
    assert stale_of(ran(source)) == ["n1"]
    own(source, "n1", stamp(LATER, OWN, T0))
    assert ran(source).findings == ()


def test_an_operators_write_under_the_workers_restamp_is_seen_by_its_event() -> None:
    """The workers' restamp leaves the device's edge naming them over the operator's earlier write, which only the
    operator's event shows (`n1` after the admin's port create, design/verified-facts.md, "Infrahub's own account")."""
    source = three_node()
    own(source, "n1", stamp("2026-11-09T10:00:06.000000+00:00", OWN, T0))
    logged(source, event(LATER, relationships=(("interfaces", "port-n1-new"),)))
    result = ran(source)
    assert errors(result) == [(RULE_STALE, "n1")]
    assert LATER in result.findings[0].message and "infrahub.node.updated" in result.findings[0].message


def test_an_address_create_shows_by_its_ports_stamp() -> None:
    """An address made on a port makes no event and moves the port's stamp, as `__system__`."""
    source = three_node()
    interface(source, "n1", "ethernet-1/2", stamp(LATER, SYSTEM, T0))
    assert stale_of(ran(source)) == ["n1"]


INTENT = event(attributes=("description",))
"""An operator's edit of `n1`'s description after its generation: intent's, and `n1` stale."""


@pytest.mark.parametrize(
    "fresh",
    [
        dataclasses.replace(INTENT, occurred_at="2026-11-09T10:02:00.000000+00:00"),
        dataclasses.replace(INTENT, mutated=False),
        dataclasses.replace(INTENT, kind="CoreArtifact", primary="artifact-n1", related=("device-n1",)),
        dataclasses.replace(INTENT, attributes=(), relationships=(("member_of_groups", "group-device-config"),)),
        dataclasses.replace(INTENT, account=OWN),
        dataclasses.replace(INTENT, primary=None, kind=None),
    ],
    ids=[
        "after the time read",
        "no node's write",
        "a CoreArtifact's",
        "member_of_groups alone",
        "the workers'",
        "no node",
    ],
)
def test_an_event_is_not_intent_when(fresh: Event) -> None:
    source = three_node()
    logged(source, INTENT)
    assert stale_of(ran(source)) == ["n1"], "the base event is intent's"
    logged(source, fresh)
    assert ran(source).findings == ()


@pytest.mark.parametrize(
    ("changed", "intent"),
    [
        ({"name": "infrahub.node.created"}, True),
        ({"name": "infrahub.node.deleted"}, True),
        ({"attributes": ("description",)}, True),
        ({"relationships": (("tags", "tag-x"),)}, True),
        ({"relationships": (("member_of_groups", "g"), ("subscriber_of_groups", "g"), ("artifacts", "a"))}, False),
        ({"relationships": (("profiles", "p"), ("object_template", "t"))}, False),
        ({}, False),
        ({"kind": "DcimPlatform", "attributes": ("name",)}, True),
        ({"kind": "OrganizationManufacturer", "attributes": ("name",)}, True),
        ({"kind": "IpamIPAddress", "attributes": ("address",)}, True),
        ({"kind": "DcimCable", "attributes": ("label",)}, True),
        ({"kind": "BuiltinTag", "attributes": ("name",)}, False),
        ({"kind": "CoreGraphQLQueryGroup", "attributes": ("description",)}, False),
        ({"kind": "DcimPlatform", "relationships": (("devices", "device-n9"),)}, False),
        ({"kind": "DcimPlatform", "relationships": (("manufacturer", "manufacturer-x"),)}, True),
        ({"kind": "OrganizationManufacturer", "relationships": (("platforms", "platform-x"),)}, False),
        ({"kind": "DcimDevice", "relationships": (("devices", "device-n9"),)}, True),
    ],
)
def test_what_is_intent(changed: dict[str, Any], intent: bool) -> None:
    """A platform's `devices` and a manufacturer's `platforms` list what points at them, which the mapping never
    renders: a device made or re-platformed elsewhere names them there (P3-31)."""
    assert stale.intent(dataclasses.replace(event(), **changed), dcim_schema()) is intent


def test_an_implementer_of_the_operators_own_counts() -> None:
    """A kind the branch lets inherit `DcimInterface` is an interface, whoever declared it."""
    source = three_node()
    logged(
        source, event(kind="InterfaceOperatorsOwn", primary="own-n1-1", attributes=("name",), related=("device-n1",))
    )
    assert ran(source).findings == ()
    held = dcim_schema()
    interface = held.generics["DcimInterface"]
    users = dataclasses.replace(interface, used_by=(*interface.used_by, "InterfaceOperatorsOwn"))
    source.held_schema = dataclasses.replace(held, generics={**held.generics, "DcimInterface": users})
    assert stale_of(ran(source)) == ["n1"]


def test_an_artifact_with_no_checksum_stamp_is_unready() -> None:
    source = three_node()
    generated(source, "n2", None)
    later = "2026-11-09T10:00:30.000000+00:00"
    for since in (None, later):
        result = ran(source, generated_since=since)
        assert result.blueprint is None
        assert errors(result) == [(RULE_UNREADY, "n2")]
        for held in ("checksum stamp", "main", AT):
            assert held in result.findings[0].message
    floors = [floor for _, floor in source.events_asked]
    assert floors == [G, later], "the earliest checksum stamp of those judged, or generated_since where later"


def test_the_events_are_read_down_to_the_earliest_checksum_stamp() -> None:
    source = three_node()
    generated(source, "n3", "2026-11-09T10:00:00.500000+00:00")
    assert ran(source).findings == ()
    assert source.events_asked == [(BRANCHED, "2026-11-09T10:00:00.500000+00:00")]
    assert source.logs_asked == [("main",)], "main's own log alone"


BRANCH = "fc-branch"
POINT = "2026-11-09T10:00:30.000000Z"
"""A branch made from `main` after every artifact was generated at `G`, and when it was made."""

AFTER = "2026-11-09T10:00:40.000000+00:00"
"""A write after `POINT`, before the time read."""


def branched() -> FakeSource:
    """`three_node` read as the branch `BRANCH`, made from `main` at `POINT`."""
    source = three_node()
    source.branched_from = POINT
    return source


def test_mains_events_up_to_the_branch_point_are_the_branchs() -> None:
    """A branch is made from `main` and holds what `main` held at its `branched_from`, a stale artifact among it, so a
    write on `main` before the branch point that only an event shows, a platform re-pointed to another manufacturer, is
    the branch's too; the branch's and `main`'s logs are read in one list from the events' floor, the earliest checksum
    stamp among the devices judged, since a write before it was regenerated after (P3-45)."""
    source = branched()
    repointed = event(kind="DcimPlatform", primary=PLATFORM, relationships=(("manufacturer", "manufacturer-x"),))
    logged(source, repointed)
    assert stale_of(ran(source, branch=BRANCH)) == ["n1", "n2", "n3"]
    assert (source.logs_asked, source.events_asked) == ([(BRANCH, "main")], [(G, G)])


def test_mains_events_after_the_branch_point_are_not_the_branchs() -> None:
    """A write on `main` after the branch was made is not the branch's (a rebase is not read); the branch's own write
    at that time is, and `main` read alone counts its own."""
    source = branched()
    repointed = event(AFTER, kind="DcimPlatform", primary=PLATFORM, relationships=(("manufacturer", "manufacturer-x"),))
    logged(source, repointed)
    assert ran(source, branch=BRANCH).findings == ()
    assert stale_of(ran(source)) == ["n1", "n2", "n3"], "main's own"
    logged(source, dataclasses.replace(repointed, branch=BRANCH))
    assert stale_of(ran(source, branch=BRANCH)) == ["n1", "n2", "n3"], "the branch's own"


def test_a_generated_since_later_than_every_checksum_stamp_is_the_events_floor() -> None:
    """Each device is judged from the later of its checksum stamp and `generated_since`, and is stale only where its
    intent was written strictly later, so no event at or before the later of the scope's earliest checksum stamp and
    `generated_since` can make one stale: the events are read from there (P3-50), and one after it still counts."""
    since = "2026-11-09T10:00:35.000000+00:00"
    source = branched()
    assert ran(source, branch=BRANCH, generated_since=since).findings == ()
    assert source.events_asked == [(since, since)]
    assert ran(source, generated_since=since).findings == ()
    assert source.events_asked[-1] == (POINT, since), "main's from its branched_from, down to the floor"
    assert ran(source, branch=BRANCH, generated_since="2026-11-09T10:00:00.500000+00:00").findings == ()
    assert source.events_asked[-1] == (G, G), "an earlier generated_since raises nothing"
    logged(source, event(AFTER, attributes=("description",), branch=BRANCH))
    assert stale_of(ran(source, branch=BRANCH, generated_since=since)) == ["n1"], "an event after it counts"


def test_a_removal_on_main_before_the_branch_point_is_the_branchs() -> None:
    """A relationship removed on `main` that moved `n1`'s stamp back, shown by its event alone, before the branch was
    made from `main`: `n1` stale on the branch."""
    source = branched()
    own(source, "n1", stamp("2026-11-09T09:59:00.000000+00:00"))
    logged(source, event(relationships=(("tags", "tag-main"),)))
    assert stale_of(ran(source, branch=BRANCH)) == ["n1"]


def test_a_device_with_no_artifact_selected_is_not_judged() -> None:
    source = three_node()
    own(source, "n1", stamp(LATER))
    devices = [
        dataclasses.replace(d, artifacts=listing("n1.artifacts", [])) if d.name == "n1" else d
        for d in source.held_devices.items
    ]
    source.held_devices = listing("DcimDevice", devices)
    assert errors(ran(source)) == [("artifact.missing", "n1")]


def test_with_no_artifact_selected_nothing_of_the_rule_is_read() -> None:
    source = three_node()
    none = [dataclasses.replace(d, artifacts=listing(f"{d.name}.artifacts", [])) for d in source.held_devices.items]
    source.held_devices = listing("DcimDevice", none)
    assert errors(ran(source)) == [("artifact.missing", name) for name in ("n1", "n2", "n3")]
    assert [call[0] for call in source.calls] == ["schema", "devices", "ports"]


def short_stamps(source: FakeSource) -> str:
    source.held_stamps = listing("DcimDevice", source.held_stamps.items[1:], count=3)
    return "DcimDevice"


def short_interfaces(source: FakeSource) -> str:
    held = row(source, "n1")
    put(source, dataclasses.replace(held, interfaces=listing("n1.interfaces", held.interfaces.items[1:], count=5)))
    return "n1.interfaces"


def twice_an_address(source: FakeSource) -> str:
    address(source, "n1", "ethernet-1/2", stamp())
    held = row(source, "n1")
    items = held.addresses.items * 2
    put(source, dataclasses.replace(held, addresses=listing("n1.ip_addresses", items)))
    return "n1.ip_addresses"


def short_artifacts(source: FakeSource) -> str:
    held = row(source, "n2")
    put(source, dataclasses.replace(held, artifacts=listing("n2.artifacts", held.artifacts.items, count=2)))
    return "n2.artifacts"


def short_cables(source: FakeSource) -> str:
    source.held_cables = listing("InterfacePhysical.connector", source.held_cables.items[1:], count=6)
    return "InterfacePhysical.connector"


def twice_a_port(source: FakeSource) -> str:
    """A port answered twice and another not, as a list that shifted between its pages would answer them: the count
    holds, and the port's id shows the fault."""
    items = source.held_cables.items
    source.held_cables = listing("InterfacePhysical.connector", [*items[:-1], items[0]])
    return "InterfacePhysical.connector"


def short_ends(source: FakeSource) -> str:
    """A cable's ends listed short of their count, as both its ports read them: one finding, the cable's."""
    items = [
        dataclasses.replace(c, ends=dataclasses.replace(c.ends, count=3)) if c.id == f"cable-{L12}" else c
        for c in source.held_cables.items
    ]
    source.held_cables = listing("InterfacePhysical.connector", items)
    return f"{L12}.connected_endpoints"


def short_ends_on_one_row(source: FakeSource) -> str:
    """A cable's ends listed short of their count on the first of its two rows alone, the other whole: the first row's
    device would be judged over part of its ends, so it is the cable's finding still."""
    rows = [c for c in source.held_cables.items if c.id == f"cable-{L12}"]
    cut = dataclasses.replace(rows[0], ends=dataclasses.replace(rows[0].ends, count=3))
    items = [cut if c is rows[0] else c for c in source.held_cables.items]
    source.held_cables = listing("InterfacePhysical.connector", items)
    return f"{L12}.connected_endpoints"


def short_groups(source: FakeSource) -> str:
    source.held_groups = listing("CoreGraphQLQueryGroup", source.held_groups.items, count=2)
    return "CoreGraphQLQueryGroup"


def short_events(source: FakeSource) -> str:
    source.held_events = listing("InfrahubEvent", [INTENT], count=2)
    return "InfrahubEvent"


@pytest.mark.parametrize(
    "cut",
    [
        short_stamps,
        short_interfaces,
        twice_an_address,
        short_artifacts,
        short_cables,
        twice_a_port,
        short_ends,
        short_ends_on_one_row,
        short_groups,
        short_events,
    ],
    ids=[
        "devices",
        "interfaces",
        "an address twice",
        "artifacts",
        "cables",
        "a port twice",
        "a cable's ends",
        "a cable's ends on one row",
        "query groups",
        "events",
    ],
)
def test_a_list_the_rule_reads_that_is_not_whole_refuses_the_read(cut: Any) -> None:
    """The rule judged over part of a list could pass a stale device, so a list it reads that is not whole is
    `read.incomplete`, and the rule is not judged."""
    source = three_node()
    what = cut(source)
    result = ran(source)
    assert result.blueprint is None
    assert errors(result) == [(RULE_INCOMPLETE, what)]
    assert AT in result.findings[0].message


def test_a_cable_reached_from_both_its_ports_on_one_device_is_whole() -> None:
    """A connector is one row for each of its ports read, so two rows of one cable on one device are its two ends and
    no object answered twice."""
    source = three_node()
    ends: Listing[CableEnd] = listing("cable-loop.connected_endpoints", [])
    loop = [
        CableStamp("cable-loop", "port-n1-ethernet-1/10", "device-n1", stamp(), ends),
        CableStamp("cable-loop", "port-n1-ethernet-1/11", "device-n1", stamp(LATER), ends),
    ]
    source.held_cables = listing("InterfacePhysical.connector", [*source.held_cables.items, *loop])
    assert errors(ran(source)) == [(RULE_STALE, "n1")]


def test_a_short_page_of_events_is_incomplete() -> None:
    source = three_node()
    source.held_events = listing("InfrahubEvent", [], count=1)
    result = ran(source)
    assert errors(result) == [(RULE_INCOMPLETE, "InfrahubEvent")]
    assert "counted 1" in result.findings[0].message


def test_the_findings_are_one_a_device_sorted_by_name() -> None:
    source = three_node()
    own(source, "n3", stamp(LATER))
    own(source, "n1", stamp("2026-11-09T10:00:09.000000+00:00"))
    logged(source, event(primary="device-n1", attributes=("description",)))
    found = stale.judge(
        source.held_stamps.items,
        source.held_cables.items,
        source.held_groups.items,
        source.held_events.items,
        dcim_schema(),
        {"device-n1": "artifact-n1", "device-n3": "artifact-n3", "device-n2": "artifact-n2"},
        branch="main",
        at=AT,
        generated_since=None,
    )
    assert [(f.rule, f.object) for f in found] == [(RULE_STALE, "n1"), (RULE_STALE, "n3")]
    assert "2026-11-09T10:00:09.000000+00:00" in found[0].message, "the latest write, its stamp over the event"


def test_written_answers_the_latest_write_and_the_event_that_says_so() -> None:
    source = three_node()
    n1 = row(source, "n1")
    assert stale.written(n1, source.held_cables.items, (), frozenset({OWN}), AT) == (T0, None)
    later = event(attributes=("description",))
    assert stale.written(n1, source.held_cables.items, (later,), frozenset({OWN}), AT) == (later.occurred_at, later)
    restamped = dataclasses.replace(n1, own=stamp(LATER, OWN, None))
    assert stale.written(restamped, (), (), frozenset({OWN}), AT) == (T0, None), "no creation: no stamp of its own"
    far = CableEnd("port-x9-1", T0, "device-x9", T0)
    cabled = [CableStamp("cable-x", "port-n1-ethernet-1/10", n1.id, stamp(LATER), listing("x.ends", [far]))]
    assert stale.written(n1, cabled, (), frozenset(), AT) == (LATER, None)
    by_cable = event(kind="DcimCable", primary="cable-x", attributes=("label",))
    assert stale.written(n1, cabled, (by_cable,), frozenset(), AT) == (by_cable.occurred_at, by_cable)
    renamed = [dataclasses.replace(cabled[0], ends=listing("x.ends", [dataclasses.replace(far, name_at=AT)]))]
    assert stale.written(n1, renamed, (), frozenset(), AT) == (AT, None), "the far port's name"
    by_far = event(kind="InterfacePhysical", primary="port-x9-1", attributes=("name",))
    assert stale.written(n1, cabled, (by_far,), frozenset(), AT) == (by_far.occurred_at, by_far)
    unnamed = dataclasses.replace(by_far, attributes=("description",))
    assert stale.written(n1, cabled, (unnamed,), frozenset(), AT) == (LATER, None), "the far port's other attributes"


def test_a_far_port_renamed_makes_both_ends_stale_and_no_third() -> None:
    """A configuration renders its cable's far end by the far port's name and the far device's, so their `name`
    stamps are intent, and all of the far end that is (P3-27): renamed, both ends of the cable are stale, `n1` by its
    far port's name and `n2` by its own port's name, as its cable's ends list it, and the device not on the cable is
    not."""
    source = three_node()
    named(source, "port-n2-ethernet-1/1", name_at=LATER)
    result = ran(source)
    assert errors(result) == [(RULE_STALE, "n1"), (RULE_STALE, "n2")]
    assert all(LATER in f.message for f in result.findings)


def test_a_far_device_renamed_outside_the_scope_makes_the_scoped_end_stale() -> None:
    """A far device the scope does not hold is never read but for its name, which the scoped end renders: renamed, by
    its `name` stamp or by its event, its primary node the far device and naming the attribute `name`."""
    source = three_node()
    outside(source, "n3", "ethernet-1/10")
    assert ran(source).findings == ()
    named(source, "port-x9-1", device_name_at=LATER)
    assert stale_of(ran(source)) == ["n3"]

    source = three_node()
    outside(source, "n3", "ethernet-1/10")
    logged(source, event(kind="DcimDevice", primary="device-x9", attributes=("name",)))
    assert stale_of(ran(source)) == ["n3"]
    logged(source, event(kind="DcimDevice", primary="device-x9", attributes=("description",)))
    assert ran(source).findings == (), "a far device's other attributes are not rendered"


def test_a_ports_event_naming_its_device_is_not_intent_of_the_devices_neighbours() -> None:
    """A port's event names its device in its related nodes (design/verified-facts.md, "What each write's events
    named"), and the far device is no node of a neighbour's but for its name: a cable made at a port of `n1` makes
    `n1` stale, and neither `n2` nor `n3`, whose cables end on `n1` (the seed's first stage)."""
    source = three_node()
    took = event(
        kind="InterfacePhysical",
        primary="port-n1-ethernet-1/2",
        relationships=(("connector", "cable-new"),),
        related=("device-n1",),
    )
    logged(source, took)
    assert errors(ran(source)) == [(RULE_STALE, "n1")]


def test_head_is_the_first_instant_after_the_latest_write() -> None:
    source = three_node()
    own(source, "n1", stamp(LATER))
    logged(source, event("2026-11-09T10:00:07.000001+00:00", kind="BuiltinTag", primary="tag-x"))
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:07.000002+00:00"
    assert [call for call in source.calls if call[0] in ("stamps", "cable_stamps")] == [
        ("stamps", "main", None),
        ("cable_stamps", "main", None),
    ]
    assert source.events_asked == [(BRANCHED, LATER)], "read down to the latest stamp"

    logged(source)
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:05.000001+00:00"

    logged(source, event("2026-11-09T10:00:07.000001+00:00"))
    own(source, "n2", stamp("2026-11-09T10:00:09.000000+00:00", OWN, T0))
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:09.000001+00:00", "nothing discounted"

    logged(source, event("2026-11-09T10:00:11.000000+00:00", relationships=(("member_of_groups", "g"),), account=OWN))
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:11.000001+00:00", "every event"


def test_head_of_a_branch_counts_mains_events_up_to_its_point() -> None:
    """`head` of a branch reads its log and `main`'s from the latest stamp, and counts `main`'s up to the branch's
    `branched_from`, what the branch was made holding, and none after (P3-45)."""
    source = branched()
    logged(source, event("2026-11-09T10:00:20.000000+00:00"), event(AFTER))
    assert head(source, branch=BRANCH, scope="tag:fylgja") == "2026-11-09T10:00:20.000001+00:00"
    assert (source.logs_asked, source.events_asked) == ([(BRANCH, "main")], [(G, G)])
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:40.000001+00:00", "main's own"
    assert (source.logs_asked[-1], source.events_asked[-1]) == (("main",), (POINT, G))


@pytest.mark.parametrize(
    "alter",
    [
        lambda source: interface(source, "n3", "ethernet-1/1", stamp("2026-11-09T10:00:13.000000+00:00")),
        lambda source: address(source, "n3", "ethernet-1/10", stamp("2026-11-09T10:00:13.000000+00:00")),
        lambda source: cable(source, L12, stamp("2026-11-09T10:00:13.000000+00:00")),
        lambda source: generated(source, "n2", "2026-11-09T10:00:13.000000+00:00"),
        lambda source: platform(source, stamp("2026-11-09T10:00:13.000000+00:00")),
        lambda source: names_at(source, platform="2026-11-09T10:00:13.000000+00:00"),
        lambda source: names_at(source, manufacturer="2026-11-09T10:00:13.000000+00:00"),
        lambda source: named(source, "port-n2-ethernet-1/1", name_at="2026-11-09T10:00:13.000000+00:00"),
        lambda source: named(source, "port-n2-ethernet-1/1", device_name_at="2026-11-09T10:00:13.000000+00:00"),
    ],
    ids=[
        "an interface's",
        "an address's",
        "a cable's",
        "a checksum's",
        "the platform's",
        "the platform's name's",
        "the manufacturer's name's",
        "a far port's name's",
        "a far device's name's",
    ],
)
def test_head_counts_every_stamp(alter: Any) -> None:
    source = three_node()
    alter(source)
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:13.000001+00:00"


def test_head_answers_the_layout_it_read() -> None:
    source = three_node()
    own(source, "n1", stamp("2026-11-09T10:00:05.000000Z"))
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:05.000001Z"
    own(source, "n1", stamp(LATER))
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:05.000001+00:00"


def test_head_of_a_scope_selecting_nothing_is_refused() -> None:
    source = three_node()
    source.held_stamps = listing("DcimDevice", [])
    with pytest.raises(Refused) as raised:
        head(source, branch="main", scope="tag:fylgja")
    (empty,) = raised.value.findings
    assert (empty.rule, empty.severity, empty.object) == (RULE_SCOPE_EMPTY, "error", "tag:fylgja")
    assert "main" in empty.message
    assert [call[0] for call in source.calls] == ["schema", "stamps"]


def test_head_over_a_schema_that_differs_is_refused_and_reads_nothing_else() -> None:
    """`head`'s reads select fields of the table's kinds, so a branch whose schema differs is refused by the schema
    check's findings, as `read` is, before any of them is sent (P3-51)."""
    source = three_node()
    held = dcim_schema()
    source.held_schema = dataclasses.replace(held, nodes={k: v for k, v in held.nodes.items() if k != "DcimCable"})
    with pytest.raises(Refused) as raised:
        head(source, branch="main", scope="tag:fylgja")
    assert [(f.rule, f.severity, f.object) for f in raised.value.findings] == [
        ("schema.kind.missing", "error", "DcimCable")
    ]
    assert source.calls == [("schema", "main", None)]


def test_head_reads_the_schema_once_and_first() -> None:
    """The schema `head` checks is the one the probes' step asks whether the branch holds `FylgjaProbe`."""
    source = three_node()
    source.held_schema = probed_schema()
    head(source, branch="main", scope="tag:fylgja")
    assert [call[0] for call in source.calls if call[0] == "schema"] == ["schema"]
    assert source.calls[0] == ("schema", "main", None)
    assert "probe_stamps" in [call[0] for call in source.calls]


@pytest.mark.parametrize("scope", ["site:x", "tag:", "fylgja"])
def test_head_of_a_scope_that_is_no_tag_sends_nothing(scope: str) -> None:
    source = three_node()
    with pytest.raises(Refused) as raised:
        head(source, branch="main", scope=scope)
    assert [(f.rule, f.object) for f in raised.value.findings] == [(RULE_SCOPE_INVALID, scope)]
    assert source.calls == []


@pytest.mark.parametrize(
    "cut", [short_stamps, short_cables, short_ends, short_events], ids=["devices", "cables", "a cable's ends", "events"]
)
def test_head_over_a_list_that_is_not_whole_is_refused(cut: Any) -> None:
    source = three_node()
    what = cut(source)
    with pytest.raises(Refused) as raised:
        head(source, branch="main", scope="tag:fylgja")
    assert [(f.rule, f.object) for f in raised.value.findings] == [(RULE_INCOMPLETE, what)]


def test_latest_counts_every_stamp_and_event_undiscounted() -> None:
    source = three_node()
    assert stale.latest(source.held_stamps.items, source.held_cables.items) == G
    generated(source, "n1", None)
    assert stale.latest([row(source, "n1")], ()) == T0
    assert stale.latest((), (), (event(LATER),)) == LATER
    assert stale.latest((), ()) is None
    unstamped = Stamped(
        "d",
        "d",
        ("d",),
        Stamp(None, None, None),
        (),
        None,
        None,
        listing("d.interfaces", []),
        listing("d.ip_addresses", []),
        listing("d.artifacts", [Generated("artifact-d", "x", None, None)]),
    )
    assert stale.latest([unstamped], ()) is None

    source.held_stamps = listing("DcimDevice", [unstamped])
    source.held_cables = listing("InterfacePhysical.connector", [])
    with pytest.raises(ValueError, match="no stamp"):
        head(source, branch="main", scope="tag:fylgja")


def test_an_address_on_a_virtual_interface_is_intent() -> None:
    """`ip_addresses` is `InterfaceLayer3`'s, which a virtual interface inherits too, so an address on a loopback is
    read under it, its edit moving its own stamp alone (P3-28; design/verified-facts.md, "Infrahub 1.11.11")."""
    source = three_node()
    virtual(source, "n2", stamp())
    address(source, "n2", "lo0", stamp(LATER, SYSTEM, T0), on="virtual-n2-lo0")
    result = ran(source)
    assert errors(result) == [(RULE_STALE, "n2")]
    assert LATER in result.findings[0].message


def test_the_artifact_judged_is_the_one_selected_by_its_id() -> None:
    """Two artifacts of one name are `artifact.ambiguous` from the listing; were the stamps read to list a second, the
    rule still judges the one the read selected, by its id (P3-26)."""
    source = three_node()
    held = row(source, "n2")
    other = Generated("artifact-n2-other", "device-config", None, "query-other")
    put(source, dataclasses.replace(held, artifacts=listing("n2.artifacts", [*held.artifacts.items, other])))
    assert ran(source).findings == ()

    put(source, dataclasses.replace(held, artifacts=listing("n2.artifacts", [other])))
    result = ran(source)
    assert errors(result) == [(RULE_INCOMPLETE, "n2.artifacts")]
    for said in ("artifact-n2", "n2", "main", AT):
        assert said in result.findings[0].message


def test_a_selected_device_the_stamps_read_does_not_list_is_incomplete() -> None:
    """Both lists are read under one filter at one time; a device the first lists and the second does not is filed by
    its name, never passed, and the rest are judged (Minor 6)."""
    source = three_node()
    own(source, "n3", stamp(LATER))
    source.held_stamps = listing("DcimDevice", [d for d in source.held_stamps.items if d.name != "n1"])
    result = ran(source)
    assert result.blueprint is None
    assert errors(result) == [(RULE_STALE, "n3"), (RULE_INCOMPLETE, "n1")]
    (unlisted,) = [f for f in result.findings if f.rule == RULE_INCOMPLETE]
    for said in ("n1", "main", AT):
        assert said in unlisted.message


def test_a_group_made_by_system_discounts_nothing() -> None:
    """`__system__` writes an operator's address create and edit, so a write of its own is intent whatever made the
    query groups: by its id, as Infrahub answers it (P3-29)."""
    source = three_node()
    source.held_groups = listing("CoreGraphQLQueryGroup", [Group("group-device-config", SYSTEM)])
    own(source, "n1", stamp(LATER, SYSTEM, T0))
    assert stale_of(ran(source)) == ["n1"]
    logged(source, event(account=SYSTEM, attributes=("description",)))
    own(source, "n1", stamp())
    assert stale_of(ran(source)) == ["n1"]
    assert stale.counted(stamp(LATER, SYSTEM, T0), frozenset({SYSTEM})) == LATER


@pytest.mark.parametrize("since", ["2026-11-09T10:01:00.000001+00:00", "2026-11-09T10:02:00.000000Z"])
def test_a_generated_since_later_than_at_is_refused(since: str) -> None:
    """A `generated_since` later than `at` would stand for a regeneration the bytes read at `at` cannot carry
    (P3-30): `at.invalid`, its object the value, and nothing is sent."""
    source = three_node()
    result = ran(source, generated_since=since)
    assert result.blueprint is None
    assert errors(result) == [(RULE_AT_INVALID, since)]
    for said in ("later than the time read", AT, "main"):
        assert said in result.findings[0].message
    assert source.calls == []
    assert ran(three_node(), generated_since=AT).findings == (), "at itself is no later than at"
