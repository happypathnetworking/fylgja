"""A fake of Nautobot for the pure tier: a `Source` over rows built in the tests, never over Nautobot's answers (D-034).
`three_node` builds the rows of `testdata/blueprint/three-node.json` from that file, the seeded context of
`three-node-probed.json`'s probe among them; `DOCUMENT` is the reader document that maps its devices, and `PROBING`
the one that also names that context."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fylgja_core.findings import Finding

from fylgja_nautobot.document import Match, ReaderDocument
from fylgja_nautobot.rows import (
    Cable,
    Change,
    Context,
    Device,
    End,
    Group,
    Listing,
    Manufacturer,
    Platform,
    Port,
    Rendered,
    Repository,
    Setting,
    Tag,
)

ROOT = Path(__file__).resolve().parents[3]
THREE_NODE = ROOT / "testdata" / "blueprint" / "three-node.json"
PROBED = ROOT / "testdata" / "blueprint" / "three-node-probed.json"

DOCUMENT = ReaderDocument((Match("Nokia", "SR Linux", "nokia_srlinux"),), None)
"""The reader document of `three_node`'s rows, mapping its platform as `nautobot/seed/reader.yaml` maps the seeded
fixture's, and naming no configuration context of probes."""

PROBING = ReaderDocument(DOCUMENT.platforms, "fylgja-probes")
"""`DOCUMENT` naming the configuration context `fylgja-probes`, as `nautobot/seed/reader.yaml` names it."""

TAG = Tag("tag-1", "fylgja")
"""The tag every device of `three_node` carries."""

MANUFACTURER = Manufacturer("manufacturer-1", "Nokia")
"""The manufacturer of `three_node`'s one platform."""

PLATFORM = Platform("platform-1", "SR Linux", MANUFACTURER.id)
"""The one platform of `three_node`."""

CHANGE = Change("change-1", "2026-11-19T21:00:06.129892Z")
"""The newest row of `three_node`'s changelog, of 66 rows, as `nautobot/seed/seed.py` leaves one."""

REPOSITORY = Repository("repository-1", "fylgja-templates", "31b3c5a6ad58a98ec861ebab4acef56dd2afeae5")
"""The template repository of `three_node`'s one setting."""

SETTING = Setting("setting-1", "Default Settings", 1000, REPOSITORY.id, "group-1")
"""Golden Config's one setting of `three_node`, as the seed leaves the installed one: its repository and its group."""

GROUP = Group("group-1", "GoldenConfigSetting Default Settings scope", "dynamic-filter", {"tags": ["fylgja"]})
"""`SETTING`'s dynamic group, as the seed leaves the installed one: its filter the devices tagged `fylgja`."""


def seeded_context() -> Context:
    """The configuration context `fylgja-probes` as plan 1 seeds it: inactive, its data the probe declaration of
    `three-node-probed.json`'s one probe, `n1-loop`, whose ends name `n1` by its Nautobot name."""
    probes: list[dict[str, Any]] = json.loads(PROBED.read_text())["probes"]
    return Context("context-1", "fylgja-probes", False, {"probes_version": "1", "probes": probes})


def listing[T](what: str, items: Sequence[T], count: int | None = None) -> Listing[T]:
    """A list as Nautobot answers it: `count` the total it gave, the number of `items` where it is None."""
    return Listing(what, len(items) if count is None else count, tuple(items))


class FakeSource:
    """A `Source` over rows held in its attributes: each call answers what they hold, whatever it is asked, and is
    recorded by its name in `calls`. A render is held by the device's id in `renders`, and an id it does not hold is a
    test's mistake, a `KeyError`; `rendered` holds the id of each device a render was asked for, in the order asked. A
    call whose name is a key of `raising` raises that error, recorded first, as Nautobot's refusal would be. `close`
    records that it was called. `newest` answers `held_newest`, which a test sets anew to move the changelog, and the
    ids each `repositories` was asked are kept, in the order asked, in `repositories_asked`; so are the ids `groups` was
    asked in `groups_asked`, the group and the devices `stored` was asked in `stored_asked`, and the filter and the
    devices `matching` was asked in `matching_asked`. `contexts` answers `held_contexts`, whatever name it is asked, and
    keeps the names it was asked in `contexts_asked`."""

    def __init__(
        self,
        *,
        held_tags: Listing[Tag],
        held_devices: Listing[Device],
        held_platforms: Listing[Platform],
        held_manufacturers: Listing[Manufacturer],
        held_ports: Listing[Port],
        held_cables: Listing[Cable],
        renders: Mapping[str, Rendered],
        held_newest: tuple[int, Change | None] = (0, None),
        held_settings: Listing[Setting] | None = None,
        held_repositories: Listing[Repository] | None = None,
        held_groups: Listing[Group] | None = None,
        held_stored: Listing[str] | None = None,
        held_matching: Listing[Device] | None = None,
        held_contexts: Listing[Context] | None = None,
        version: str = "3.2.8",
        golden_config: str | None = "3.0.8",
        unverified: Finding | None = None,
        raising: Mapping[str, Exception] | None = None,
    ) -> None:
        self.held_tags = held_tags
        self.held_devices = held_devices
        self.held_platforms = held_platforms
        self.held_manufacturers = held_manufacturers
        self.held_ports = held_ports
        self.held_cables = held_cables
        self.renders = dict(renders)
        self.held_newest = held_newest
        self.held_settings = held_settings or listing("nautobot_golden_config.goldenconfigsetting", [])
        self.held_repositories = held_repositories or listing("extras.gitrepository", [])
        self.repositories_asked: list[tuple[str, ...]] = []
        self.held_groups = held_groups or listing("extras.dynamicgroup", [])
        self.held_stored = held_stored or listing("extras.staticgroupassociation", [])
        self.held_matching = held_matching or listing("dcim.device", [])
        self.held_contexts = held_contexts or listing("extras.configcontext", [])
        self.contexts_asked: list[str] = []
        self.groups_asked: list[tuple[str, ...]] = []
        self.stored_asked: list[tuple[str, tuple[str, ...]]] = []
        self.matching_asked: list[tuple[tuple[tuple[str, str], ...], tuple[str, ...]]] = []
        self.version = version
        self.golden_config = golden_config
        self.unverified = unverified
        self.calls: list[str] = []
        self.rendered: list[str] = []
        self.raising: dict[str, Exception] = dict(raising or {})
        self.closed = False

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if name in self.raising:
            raise self.raising[name]

    def close(self) -> None:
        self.closed = True

    def tags(self, name: str) -> Listing[Tag]:
        self._call("tags")
        return self.held_tags

    def devices(self, tag: Tag) -> Listing[Device]:
        self._call("devices")
        return self.held_devices

    def platforms(self, ids: Sequence[str]) -> Listing[Platform]:
        self._call("platforms")
        return self.held_platforms

    def manufacturers(self, ids: Sequence[str]) -> Listing[Manufacturer]:
        self._call("manufacturers")
        return self.held_manufacturers

    def ports(self, devices: Sequence[str]) -> Listing[Port]:
        self._call("ports")
        return self.held_ports

    def cables(self, ids: Sequence[str]) -> Listing[Cable]:
        self._call("cables")
        return self.held_cables

    def contexts(self, name: str) -> Listing[Context]:
        self._call("contexts")
        self.contexts_asked.append(name)
        return self.held_contexts

    def render(self, device: str) -> Rendered:
        self._call("render")
        self.rendered.append(device)
        return self.renders[device]

    def newest(self) -> tuple[int, Change | None]:
        self._call("newest")
        return self.held_newest

    def settings(self) -> Listing[Setting]:
        self._call("settings")
        return self.held_settings

    def repositories(self, ids: Sequence[str]) -> Listing[Repository]:
        self._call("repositories")
        self.repositories_asked.append(tuple(ids))
        return self.held_repositories

    def groups(self, ids: Sequence[str]) -> Listing[Group]:
        self._call("groups")
        self.groups_asked.append(tuple(ids))
        return self.held_groups

    def stored(self, group: str, devices: Sequence[str]) -> Listing[str]:
        self._call("stored")
        self.stored_asked.append((group, tuple(devices)))
        return self.held_stored

    def matching(
        self, filter: Sequence[tuple[str, str]], devices: Sequence[str], group: str | None = None
    ) -> Listing[Device]:
        self._call("matching")
        self.matching_asked.append((tuple(filter), tuple(devices)))
        return self.held_matching


def three_node() -> FakeSource:
    """The rows of `three-node.json`, on Nautobot 3.2.8 with Golden Config 3.0.8: each device, its id `device-N` for its
    place N in the file from 1, carrying the tag `fylgja` and on the platform `SR Linux` of `Nokia`; each interface a
    port of type `1000base-t`, numbered from 1 in the file's order, with the fixture's `enabled` and `mgmt_only`; each
    link a `Cable` with no label, numbered from 1, of one `dcim.interface` end a side, each with no display text, as
    Nautobot answers a cable's `terminations` at the default depth; each device rendered 200 to the fixture's
    `config`; a changelog of 66 rows, the newest `CHANGE`, and Golden Config's one setting, `SETTING`, naming
    `REPOSITORY` and `GROUP`, whose stored members are the three devices, and whose filter lists the three; and the
    one context of the fixture's probe, `seeded_context`."""
    network = json.loads(THREE_NODE.read_text())["network"]
    ids: dict[tuple[str, str], str] = {}
    devices, ports, renders = [], [], {}
    for number, device in enumerate(network["devices"], start=1):
        devices.append(Device(f"device-{number}", device["name"], PLATFORM.id))
        renders[f"device-{number}"] = Rendered(200, device["config"], None)
        for interface in device["interfaces"]:
            ids[(device["name"], interface["name"])] = f"interface-{len(ids) + 1}"
    cabled: dict[str, str] = {}
    cables = []
    for number, link in enumerate(network["links"], start=1):
        a, b = (ids[(link[side]["device"], link[side]["interface"])] for side in ("a", "b"))
        cabled |= {a: f"cable-{number}", b: f"cable-{number}"}
        a_end = End("dcim.interface", a, None)
        b_end = End("dcim.interface", b, None)
        cables.append(Cable(f"cable-{number}", None, (a_end,), (b_end,)))
    for number, device in enumerate(network["devices"], start=1):
        for interface in device["interfaces"]:
            port = ids[(device["name"], interface["name"])]
            ports.append(
                Port(
                    port,
                    f"device-{number}",
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
        held_manufacturers=listing("dcim.manufacturer", [MANUFACTURER]),
        held_ports=listing("dcim.interface", ports),
        held_cables=listing("dcim.cable", cables),
        renders=renders,
        held_newest=(66, CHANGE),
        held_settings=listing("nautobot_golden_config.goldenconfigsetting", [SETTING]),
        held_repositories=listing("extras.gitrepository", [REPOSITORY]),
        held_groups=listing("extras.dynamicgroup", [GROUP]),
        held_stored=listing("extras.staticgroupassociation", [device.id for device in devices]),
        held_matching=listing("dcim.device", devices),
        held_contexts=listing("extras.configcontext", [seeded_context()]),
    )
