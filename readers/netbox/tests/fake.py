"""A fake of NetBox for the pure tier: a `Source` over rows built in the tests, never over NetBox's answers (D-034).
`three_node` builds the rows of `testdata/blueprint/three-node.json` from that file, the seeded context of
`three-node-probed.json`'s probe among them; `DOCUMENT` is the reader document that maps its devices, and `PROBING`
the one that also names that context."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fylgja_core.findings import Finding

from fylgja_netbox.document import Match, ReaderDocument
from fylgja_netbox.rows import Branch, Cable, Change, Context, Device, End, Listing, Platform, Port, Rendered, Tag

ROOT = Path(__file__).resolve().parents[3]
THREE_NODE = ROOT / "testdata" / "blueprint" / "three-node.json"
PROBED = ROOT / "testdata" / "blueprint" / "three-node-probed.json"

DOCUMENT = ReaderDocument((Match("Nokia", "SR Linux", "nokia_srlinux"),), None)
"""The reader document of `three_node`'s rows, mapping its platform as `netbox/seed/reader.yaml` maps the seeded
fixture's, and naming no configuration context of probes."""

PROBING = ReaderDocument(DOCUMENT.platforms, "fylgja-probes")
"""`DOCUMENT` naming the configuration context `fylgja-probes`, as `netbox/seed/reader.yaml` names it."""

TAG = Tag(1, "fylgja")
"""The tag every device of `three_node` carries."""

PLATFORM = Platform(1, "SR Linux", "Nokia")
"""The one platform of `three_node`, of the manufacturer `Nokia`."""

TEXT = "text/plain; charset=utf-8"
"""The content type NetBox gives a render's text (design/verified-facts.md, "A device's configuration, rendered")."""


def seeded_context() -> Context:
    """The configuration context `fylgja-probes` as plan 1 seeds it (`netbox/seed/main.yaml`): inactive, its data the
    probe declaration of `three-node-probed.json`'s one probe, `n1-loop`, whose ends name `n1` by its NetBox name."""
    probes: list[dict[str, Any]] = json.loads(PROBED.read_text())["probes"]
    return Context(1, "fylgja-probes", False, {"probes_version": "1", "probes": probes})


def listing[T](what: str, items: Sequence[T], count: int | None = None) -> Listing[T]:
    """A list as NetBox answers it: `count` the total it gave, the number of `items` where it is None."""
    return Listing(what, len(items) if count is None else count, tuple(items))


class FakeSource:
    """A `Source` over rows held in its attributes: each call answers what they hold, whatever it is asked, and is
    recorded in `calls` as `(name, the name of the branch it reads under)`, None for `main` and for `branches`, which
    is sent under no branch. A render is held by the device's id in `renders`, and an id it does not hold is a test's
    mistake, a `KeyError`. `latest` answers `latests` in order, and the last again once they are spent, and `counted`
    `counts` the same way; `changes` answers `changed`, whatever it is asked, under the count `changed_count`, theirs
    where it is None. `contexts` answers `held_contexts`, whatever name it is asked, none where it is not given.
    `rendered` holds the id of each device a render was asked for, in the order asked. A call whose
    name is a key of `raising` raises that error, recorded first, as NetBox's refusal would be. `close` records that
    it was called."""

    def __init__(
        self,
        *,
        held_tags: Listing[Tag],
        held_devices: Listing[Device],
        held_platforms: Listing[Platform],
        held_ports: Listing[Port],
        held_cables: Listing[Cable],
        renders: Mapping[int, Rendered],
        held_branches: Listing[Branch] | None = None,
        held_contexts: Listing[Context] | None = None,
        latests: Sequence[int | None] = (None,),
        changed: Sequence[Change] = (),
        changed_count: int | None = None,
        counts: Sequence[int] = (0,),
        version: str = "4.7.5",
        branching: str | None = "1.2.3",
        unverified: Finding | None = None,
        raising: Mapping[str, Exception] | None = None,
    ) -> None:
        self.held_tags = held_tags
        self.held_devices = held_devices
        self.held_platforms = held_platforms
        self.held_ports = held_ports
        self.held_cables = held_cables
        self.renders = dict(renders)
        self.held_branches = held_branches if held_branches is not None else listing("netbox_branching.branch", [])
        self.held_contexts = held_contexts if held_contexts is not None else listing("extras.configcontext", [])
        self.latests: list[int | None] = list(latests)
        self.changed: tuple[Change, ...] = tuple(changed)
        self.changed_count = changed_count
        self.counts: list[int] = list(counts)
        self._latest = 0
        self._counted = 0
        self.version = version
        self.branching = branching
        self.unverified = unverified
        self.calls: list[tuple[str, str | None]] = []
        self.rendered: list[int] = []
        self.raising: dict[str, Exception] = dict(raising or {})
        self.closed = False

    def _call(self, name: str, branch: Branch | None) -> None:
        self.calls.append((name, _name(branch)))
        if name in self.raising:
            raise self.raising[name]

    def close(self) -> None:
        self.closed = True

    def branches(self, name: str) -> Listing[Branch]:
        self._call("branches", None)
        return self.held_branches

    def tags(self, branch: Branch | None, name: str) -> Listing[Tag]:
        self._call("tags", branch)
        return self.held_tags

    def devices(self, branch: Branch | None, tag: int) -> Listing[Device]:
        self._call("devices", branch)
        return self.held_devices

    def platforms(self, branch: Branch | None, ids: Sequence[int]) -> Listing[Platform]:
        self._call("platforms", branch)
        return self.held_platforms

    def ports(self, branch: Branch | None, devices: Sequence[int]) -> Listing[Port]:
        self._call("ports", branch)
        return self.held_ports

    def cables(self, branch: Branch | None, ids: Sequence[int]) -> Listing[Cable]:
        self._call("cables", branch)
        return self.held_cables

    def contexts(self, branch: Branch | None, name: str) -> Listing[Context]:
        self._call("contexts", branch)
        return self.held_contexts

    def render(self, branch: Branch | None, device: int) -> Rendered:
        self._call("render", branch)
        self.rendered.append(device)
        return self.renders[device]

    def latest(self, branch: Branch | None) -> int | None:
        self._call("latest", branch)
        held = self.latests[min(self._latest, len(self.latests) - 1)]
        self._latest += 1
        return held

    def changes(self, branch: Branch | None, after: int | None) -> Listing[Change]:
        self._call("changes", branch)
        return listing("core.objectchange", self.changed, self.changed_count)

    def counted(self, branch: Branch | None, upto: int) -> int:
        self._call("counted", branch)
        held = self.counts[min(self._counted, len(self.counts) - 1)]
        self._counted += 1
        return held


def _name(branch: Branch | None) -> str | None:
    return None if branch is None else branch.name


def three_node() -> FakeSource:
    """The rows of `three-node.json`, on NetBox 4.7.5 with netbox-branching 1.2.3: each device, its id its place in the
    file from 1, carrying the tag `fylgja` (id 1) and on the platform `SR Linux` of `Nokia` (id 1); each interface a
    port of type `1000base-t`, numbered from 1 in the file's order, with the fixture's `enabled` and `mgmt_only`; each
    link a `Cable` with no label, numbered from 1, of one `dcim.interface` end a side, each displayed by its port's
    name, as NetBox displays an interface; each device rendered 200 to the fixture's `config`; and the context
    `seeded_context`."""
    network = json.loads(THREE_NODE.read_text())["network"]
    ids: dict[tuple[str, str], int] = {}
    devices, ports, renders = [], [], {}
    for number, device in enumerate(network["devices"], start=1):
        devices.append(Device(number, device["name"], PLATFORM.id))
        renders[number] = Rendered(200, device["config"].encode(), TEXT)
        for interface in device["interfaces"]:
            ids[(device["name"], interface["name"])] = len(ids) + 1
    cabled: dict[int, int] = {}
    cables = []
    for number, link in enumerate(network["links"], start=1):
        a, b = (ids[(link[side]["device"], link[side]["interface"])] for side in ("a", "b"))
        cabled |= {a: number, b: number}
        a_end = End("dcim.interface", a, link["a"]["interface"])
        b_end = End("dcim.interface", b, link["b"]["interface"])
        cables.append(Cable(number, None, (a_end,), (b_end,)))
    for number, device in enumerate(network["devices"], start=1):
        for interface in device["interfaces"]:
            port = ids[(device["name"], interface["name"])]
            ports.append(
                Port(
                    port,
                    number,
                    interface["name"],
                    "1000base-t",
                    interface["enabled"],
                    interface["mgmt_only"],
                    cabled.get(port),
                )
            )
    return FakeSource(
        held_tags=listing("extras.tag", [TAG]),
        held_devices=listing("dcim.device", devices),
        held_platforms=listing("dcim.platform", [PLATFORM]),
        held_ports=listing("dcim.interface", ports),
        held_cables=listing("dcim.cable", cables),
        renders=renders,
        held_contexts=listing("extras.configcontext", [seeded_context()]),
    )
