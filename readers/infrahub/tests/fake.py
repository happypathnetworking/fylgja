"""A fake of Infrahub for the pure tier: a `Source` over rows built in the tests, never over Infrahub's answers
(D-034). `three_node` builds the rows of `testdata/blueprint/three-node.json` from that file, `dcim_schema` the
schema of a branch that holds the DCIM library as the mapping reads it, and `DOCUMENT` is the reader document that
maps its devices; `probed_schema` adds the kind `FylgjaProbe`, `PROBING` is `DOCUMENT` asking for probes, and
`seeded_probe` is `testdata/blueprint/three-node-probed.json`'s probe as a row. Its stamps are the stale rule's: every
node written at `T0` by `ADMIN`, every artifact generated at `G`, every query group made by `OWN`, and no event."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from fylgja_core.findings import Finding

from fylgja_infrahub.document import Match, ReaderDocument
from fylgja_infrahub.probes import FIELDS, KIND
from fylgja_infrahub.rows import (
    Artifact,
    Attribute,
    Branch,
    CableEnd,
    CableStamp,
    Connector,
    Content,
    Device,
    End,
    End4,
    Event,
    Generated,
    Group,
    Kind,
    Listing,
    Port,
    Probe,
    Schema,
    Stamp,
    Stamped,
)
from fylgja_infrahub.schema import TABLE

ROOT = Path(__file__).resolve().parents[3]
THREE_NODE = ROOT / "testdata" / "blueprint" / "three-node.json"
THREE_NODE_PROBED = ROOT / "testdata" / "blueprint" / "three-node-probed.json"

DOCUMENT = ReaderDocument((Match("Nokia", "SR Linux", "nokia_srlinux"),), "device-config", probes=False)
"""The reader document of `three_node`'s rows, mapping its platform as `infrahub/seed/reader.yaml` maps the seeded
fixture's, and reading no probe."""

PROBING = ReaderDocument(DOCUMENT.platforms, DOCUMENT.artifact, probes=True)
"""`DOCUMENT` asking for probes, as `infrahub/seed/reader.yaml` does."""

T0 = "2026-11-09T10:00:00.000000+00:00"
"""When every node of `three_node` was made and last written."""

G = "2026-11-09T10:00:01.000000+00:00"
"""When every artifact of `three_node` was generated: its checksum's stamp."""

BRANCHED = "2026-11-09T09:00:00.000000Z"
"""When `three_node`'s branch was made, in the layout Infrahub answers a branch's times in."""

ADMIN = "acct-admin"
"""The operator's account, which wrote every node of `three_node`."""

OWN = "acct-own"
"""The task workers' account, which made every query group of `three_node`."""

QUERY = "query-device-config"
"""The query every artifact of `three_node` renders through."""

PLATFORM = "platform-sr-linux"
MANUFACTURER = "manufacturer-nokia"


def listing[T](what: str, items: Sequence[T], count: int | None = None) -> Listing[T]:
    """A list as Infrahub answers it: `count` the total it gave, the number of `items` where it is None."""
    return Listing(what, len(items) if count is None else count, tuple(items))


def stamp(updated_at: str = T0, updated_by: str | None = ADMIN, created_at: str | None = T0) -> Stamp:
    """A node's stamp: by default `three_node`'s, made and last written at `T0` by `ADMIN`."""
    return Stamp(updated_at, updated_by, created_at)


def dcim_schema() -> Schema:
    """A branch's schema holding the table's own kinds as rows (`schema.TABLE`): each node and generic with exactly
    the attributes, relationships, choices and users the table names, under a hash of hex digits of its own. Its
    dicts of kinds are its own, but each `Kind`, and the dicts of fields inside it, is `TABLE`'s own object, so a test
    changes one with `dataclasses.replace`, never in place, which would change `TABLE` too."""
    return Schema(hashlib.md5(b"dcim").hexdigest(), dict(TABLE.nodes), dict(TABLE.generics))


def probed_schema() -> Schema:
    """`dcim_schema()` and the kind `FylgjaProbe` with exactly the attributes the reader reads, each Text and
    required."""
    held = dcim_schema()
    kind = Kind({field: Attribute("Text", optional=False) for field in FIELDS}, {})
    return Schema(held.hash, {**held.nodes, KIND: kind}, dict(held.generics))


def probe(
    name: str,
    a: End4,
    b: End4,
    *,
    format: str = "ping",
    id: str | None = None,
) -> Probe:
    """A `FylgjaProbe` as a row, each end its device's name in Infrahub, its port, its address and its gateway; its id
    `probe-<name>` unless one is given."""
    return Probe(id or f"probe-{name}", name, format, a, b)


def seeded_probe() -> Probe:
    """`three-node-probed.json`'s one probe, `n1-loop`, as the seed's `FylgjaProbe` holds it: each end on `n1`, as
    Infrahub names the device."""
    (held,) = json.loads(THREE_NODE_PROBED.read_text())["probes"]
    a, b = ((end["device"], end["interface"], end["address"], end["gateway"]) for end in held["endpoints"])
    return probe(held["name"], a, b, format=held["format"])


class FakeSource:
    """A `Source` over rows held in its attributes: each call answers what they hold and is recorded in `calls` as
    `(name, branch, at)`, `at` None for a call that takes none; the events' `since` and `floor` are recorded in
    `events_asked` too, and the logs asked in `logs_asked`, every held event answered whichever logs are asked. It
    holds no probe, and no probe's stamp, unless `held_probes` and `held_probe_stamps` give
    them. Content is held by storage id, and an id it does not hold is a test's mistake, a `KeyError`. `close` records
    that it was called, as the command closes the connection `connect` answered."""

    def __init__(
        self,
        *,
        held_schema: Schema,
        held_devices: Listing[Device],
        held_ports: Listing[Port],
        held_content: Mapping[str, Content],
        held_stamps: Listing[Stamped],
        held_cables: Listing[CableStamp],
        held_groups: Listing[Group],
        held_events: Listing[Event],
        held_probes: Listing[Probe] | None = None,
        held_probe_stamps: Listing[tuple[str, Stamp]] | None = None,
        branched_from: str = BRANCHED,
        version: str = "1.11.11",
        unverified: Finding | None = None,
    ) -> None:
        self.held_schema = held_schema
        self.held_devices = held_devices
        self.held_ports = held_ports
        self.held_content = dict(held_content)
        self.held_stamps = held_stamps
        self.held_cables = held_cables
        self.held_groups = held_groups
        self.held_events = held_events
        self.held_probes = held_probes if held_probes is not None else listing(KIND, [])
        self.held_probe_stamps = held_probe_stamps if held_probe_stamps is not None else listing(KIND, [])
        self.branched_from = branched_from
        self.version = version
        self.unverified = unverified
        self.calls: list[tuple[str, str, str | None]] = []
        self.events_asked: list[tuple[str, str | None]] = []
        self.logs_asked: list[tuple[str, ...]] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def schema(self, branch: str) -> Schema:
        self.calls.append(("schema", branch, None))
        return self.held_schema

    def devices(self, branch: str, at: str | None, tag: str) -> Listing[Device]:
        self.calls.append(("devices", branch, at))
        return self.held_devices

    def ports(self, branch: str, at: str | None, devices: Sequence[str]) -> Listing[Port]:
        self.calls.append(("ports", branch, at))
        return self.held_ports

    def content(self, branch: str, at: str | None, storage_id: str) -> Content:
        self.calls.append(("content", branch, at))
        return self.held_content[storage_id]

    def stamps(self, branch: str, at: str | None, tag: str) -> Listing[Stamped]:
        self.calls.append(("stamps", branch, at))
        return self.held_stamps

    def cable_stamps(self, branch: str, at: str | None, devices: Sequence[str]) -> Listing[CableStamp]:
        self.calls.append(("cable_stamps", branch, at))
        return self.held_cables

    def groups(self, branch: str, at: str | None, queries: Sequence[str]) -> Listing[Group]:
        self.calls.append(("groups", branch, at))
        return self.held_groups

    def events(self, branch: str, logs: Sequence[str], since: str, floor: str | None) -> Listing[Event]:
        self.calls.append(("events", branch, None))
        self.events_asked.append((since, floor))
        self.logs_asked.append(tuple(logs))
        return self.held_events

    def branch(self, name: str) -> Branch:
        self.calls.append(("branch", name, None))
        return Branch(name, self.branched_from)

    def probes(self, branch: str, at: str | None) -> Listing[Probe]:
        self.calls.append(("probes", branch, at))
        return self.held_probes

    def probe_stamps(self, branch: str, at: str | None) -> Listing[tuple[str, Stamp]]:
        self.calls.append(("probe_stamps", branch, at))
        return self.held_probe_stamps


def three_node() -> FakeSource:
    """The rows of `three-node.json`, on a branch whose schema is `dcim_schema()`: each device on the platform
    `SR Linux` of `Nokia`, with one `Ready` artifact `device-config` whose content is the fixture's `config` and whose
    checksum is its MD5; each interface a port, its role `management` where it is management-only and its status
    `disabled` where it is not enabled; and each link a `DcimCable`, labelled by its two ends as the seed labels it,
    reached from both its ports, each reaching both its ends. Every node, the cables among them, is stamped `stamp()`,
    every end's name and its device's written at `T0`, no port holds an address, each artifact's checksum is stamped
    `G` and renders through `QUERY`, whose one query group `OWN` made, and the branch, made at `BRANCHED`, has no
    event."""
    network = json.loads(THREE_NODE.read_text())["network"]
    devices, ports, content, stamped = [], [], {}, []
    cables: dict[tuple[str, str], Connector] = {}
    cable_stamps: list[CableStamp] = []
    for link in network["links"]:
        a, b = link["a"], link["b"]
        label = f"{a['device']}:{a['interface']}|{b['device']}:{b['interface']}"
        ends = [
            End(f"port-{e['device']}-{e['interface']}", "InterfacePhysical", f"device-{e['device']}", e["interface"])
            for e in (a, b)
        ]
        cable = Connector(f"cable-{label}", "DcimCable", label, listing(f"{label}.connected_endpoints", ends))
        cables |= {(e["device"], e["interface"]): cable for e in (a, b)}
        named = listing(f"{label}.connected_endpoints", [CableEnd(end.id, T0, end.device, T0) for end in ends])
        cable_stamps += [CableStamp(cable.id, end.id, str(end.device), stamp(), named) for end in ends]
    for device in network["devices"]:
        name, config = device["name"], device["config"].encode()
        checksum = hashlib.md5(config).hexdigest()
        artifact = Artifact(f"artifact-{name}", "device-config", "Ready", checksum, f"storage-{name}")
        devices.append(Device(f"device-{name}", name, "SR Linux", "Nokia", listing(f"{name}.artifacts", [artifact])))
        content[f"storage-{name}"] = Content(200, config)
        own = [f"port-{name}-{interface['name']}" for interface in device["interfaces"]]
        stamped.append(
            Stamped(
                f"device-{name}",
                name,
                (f"device-{name}", PLATFORM, MANUFACTURER, *own),
                stamp(),
                (stamp(), stamp()),
                T0,
                T0,
                listing(f"{name}.interfaces", [(port, stamp()) for port in own]),
                listing(f"{name}.ip_addresses", []),
                listing(f"{name}.artifacts", [Generated(f"artifact-{name}", "device-config", G, QUERY)]),
            )
        )
        for interface in device["interfaces"]:
            ports.append(
                Port(
                    f"port-{name}-{interface['name']}",
                    f"device-{name}",
                    interface["name"],
                    "management" if interface["mgmt_only"] else None,
                    "active" if interface["enabled"] else "disabled",
                    cables.get((name, interface["name"])),
                )
            )
    return FakeSource(
        held_schema=dcim_schema(),
        held_devices=listing("DcimDevice", devices),
        held_ports=listing("InterfacePhysical", ports),
        held_content=content,
        held_stamps=listing("DcimDevice", stamped),
        held_cables=listing("InterfacePhysical.connector", cable_stamps),
        held_groups=listing("CoreGraphQLQueryGroup", [Group("group-device-config", OWN)]),
        held_events=listing("InfrahubEvent", []),
    )
