"""The fixture network the seed puts on `main` and its branch, read as files: `infrahub/seed/main/`'s and
`infrahub/seed/stages/`'s object files against `testdata/blueprint/three-node.json`, and the reader document
`infrahub/seed/reader.yaml` against the platform package it names.

Nothing here reaches Infrahub: what it makes of the files is read on the running instance (design/verified-facts.md,
"Infrahub 1.11.11") and held by the contract tier.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import register
import yaml

ROOT = Path(__file__).resolve().parents[2]
FILES = ROOT / "infrahub" / "seed" / "main"
STAGES = ROOT / "infrahub" / "seed" / "stages"
READER = ROOT / "infrahub" / "seed" / "reader.yaml"
PACKAGE = ROOT / "psp" / "nokia_srlinux.yaml"
LIBRARY = ROOT / "infrahub" / "schema" / "dcim"
PROBE_KIND = ROOT / "readers" / "infrahub" / "schema"
"""The reader's own schema, its kind `FylgjaProbe`, which the seed loads on `main` before the object files."""
FIXTURE = ROOT / "testdata" / "blueprint" / "three-node.json"

LINK_N1_N3 = frozenset({("n1", "ethernet-1/2"), ("n3", "ethernet-1/2")})
"""The fixture's link that `main` lacks: the branch's first staged edit adds it."""

ADDRESS = re.compile(r"^set / interface (\S+) subinterface 0 ipv4 address (\S+)$", re.MULTILINE)


def documents(paths: Iterable[Path] | None = None) -> list[dict[str, Any]]:
    """Every document of the object files `paths`, `main/`'s where they are not given, in the order of their names."""
    found = []
    for path in sorted(FILES.glob("*.yml") if paths is None else paths):
        for document in yaml.safe_load_all(path.read_text()):
            assert document["apiVersion"] == "infrahub.app/v1", path.name
            assert document["kind"] == "Object", path.name
            found.append(document)
    return found


Found = tuple[str, dict[str, Any], tuple[tuple[str, dict[str, Any]], ...]]
"""An object a file says: its kind, its fields, and the kind and fields of each object it is nested under."""


def walk(kind: str, items: list[dict[str, Any]], above: tuple[tuple[str, dict[str, Any]], ...] = ()) -> Iterator[Found]:
    for item in items:
        yield kind, item, above
        for value in item.values():
            if isinstance(value, dict) and "data" in value:
                yield from walk(value["kind"], value["data"], (*above, (kind, item)))


def objects(paths: Iterable[Path] | None = None) -> list[Found]:
    """Each object the files `paths` say, `main/`'s where they are not given, nested ones included."""
    return [
        found for document in documents(paths) for found in walk(document["spec"]["kind"], document["spec"]["data"])
    ]


def of(kind: str, *under: str) -> list[tuple[dict[str, Any], tuple[dict[str, Any], ...]]]:
    """The objects of `kind` nested under objects of the kinds `under`, outermost first, with those objects."""
    return [
        (item, tuple(fields for _, fields in above))
        for found, item, above in objects()
        if found == kind and tuple(outer for outer, _ in above) == under
    ]


def test_the_baseline_is_three_node_less_the_link_n1_n3() -> None:
    network = json.loads(FIXTURE.read_text())["network"]
    fixture = {device["name"]: device for device in network["devices"]}

    devices = {item["name"]: item for item, _ in of("DcimDevice")}
    assert sorted(devices) == sorted(fixture) == ["n1", "n2", "n3"]
    for device in devices.values():
        assert device["platform"] == "SR Linux"
        assert device["tags"] == ["fylgja"]
        assert device["member_of_groups"] == [register.GROUP]
        assert device["status"] == "active"
        assert device["description"] == "FYLGJA-MARKER-fixture"

    ports: dict[str, dict[str, str | None]] = {name: {} for name in devices}
    for port, (device,) in of("InterfacePhysical", "DcimDevice"):
        ports[device["name"]][port["name"]] = port.get("role")
    for name, device in fixture.items():
        assert ports[name] == {
            interface["name"]: "management" if interface["mgmt_only"] else None for interface in device["interfaces"]
        }

    found = of("IpamIPAddress", "DcimDevice", "InterfacePhysical")
    addresses = {(device["name"], port["name"], item["address"]) for item, (device, port) in found}
    assert addresses == {
        (name, port, address) for name, device in fixture.items() for port, address in ADDRESS.findall(device["config"])
    }
    assert len(addresses) == 6

    pairs = ((link["a"], link["b"]) for link in network["links"])
    links = {frozenset((end["device"], end["interface"]) for end in pair) for pair in pairs}
    cables: dict[str, set[tuple[str, str]]] = {cable["label"]: set() for cable, _ in of("DcimCable")}
    for port, (cable,) in of("InterfacePhysical", "DcimCable"):
        assert set(port) == {"name", "device"}, "an end names a port the devices' file made, and sets nothing of it"
        cables[cable["label"]].add((port["device"], port["name"]))
    assert {frozenset(ends) for ends in cables.values()} == links - {LINK_N1_N3}
    assert len(cables) == len(links - {LINK_N1_N3})
    for label, ends in cables.items():
        assert label == "|".join(sorted(f"{device}:{port}" for device, port in ends))

    assert [item["name"] for item, _ in of("OrganizationManufacturer")] == ["Nokia"]
    assert [(item["name"], item["manufacturer"]) for item, _ in of("DcimPlatform")] == [("SR Linux", "Nokia")]


def test_every_object_file_names_a_kind_main_holds() -> None:
    held = {*register.library_kinds(LIBRARY), *register.library_kinds(PROBE_KIND), "BuiltinTag", "CoreStandardGroup"}
    assert "FylgjaProbe" in held
    kinds = [kind for kind, _, _ in (*objects(), *objects(STAGES.glob("*.yml")))]
    assert kinds
    assert [kind for kind in kinds if kind not in held] == []


def test_the_third_link_makes_three_node_and_the_address_moves_no_port() -> None:
    network = json.loads(FIXTURE.read_text())["network"]
    pairs = ((link["a"], link["b"]) for link in network["links"])
    links = {frozenset((end["device"], end["interface"]) for end in pair) for pair in pairs}
    baseline = {cable["label"]: set[tuple[str, str]]() for cable, _ in of("DcimCable")}
    for port, (cable,) in of("InterfacePhysical", "DcimCable"):
        baseline[cable["label"]].add((port["device"], port["name"]))

    third = objects([STAGES / "1-third-link.yml"])
    assert [(kind, tuple(outer for outer, _ in above)) for kind, _, above in third] == [
        ("DcimCable", ()),
        ("InterfacePhysical", ("DcimCable",)),
        ("InterfacePhysical", ("DcimCable",)),
    ]
    cable = third[0][1]
    ends = [port for _, port, _ in third[1:]]
    assert all(set(port) == {"name", "device"} for port in ends), "an end names a port main holds, and sets nothing"
    added = frozenset((port["device"], port["name"]) for port in ends)
    assert added == LINK_N1_N3
    assert cable["label"] == "|".join(sorted(f"{device}:{port}" for device, port in added))
    assert {frozenset(ends) for ends in baseline.values()} | {added} == links
    assert len(baseline) + 1 == len(links)

    address = objects([STAGES / "2-n1-address.yml"])
    assert [(kind, tuple(outer for outer, _ in above)) for kind, _, above in address] == [
        ("InterfacePhysical", ()),
        ("IpamIPAddress", ("InterfacePhysical",)),
    ]
    port, made = address[0][1], address[1][1]
    assert {key: value for key, value in port.items() if key != "ip_addresses"} == {
        "name": "ethernet-1/2",
        "device": "n1",
    }, "the port is named and set nothing, so the load finds main's and changes no port"
    assert made == {"address": "192.0.2.1/24"}


def test_the_probe_is_the_probed_fixtures() -> None:
    """`main/`'s one `FylgjaProbe` is `testdata/blueprint/three-node-probed.json`'s probe, its ends flat, a then b, its
    devices named as Infrahub names them, which are the fixture's names."""
    (held,) = json.loads(FIXTURE.with_name("three-node-probed.json").read_text())["probes"]
    probes = [item for item, _ in of("FylgjaProbe")]
    fields = ("device", "interface", "address", "gateway")
    sides = zip("ab", held["endpoints"], strict=True)
    ends = [{f"{side}_{field}": end[field] for field in fields} for side, end in sides]
    assert probes == [{"name": held["name"], "format": held["format"], **ends[0], **ends[1]}]


def test_the_reader_document_maps_the_fixtures_pair_to_a_shipped_package() -> None:
    reader = yaml.safe_load(READER.read_text())
    assert reader == {
        "reader_version": "1",
        "platforms": [{"manufacturer": "Nokia", "platform": "SR Linux", "package": "nokia_srlinux"}],
        "artifact": "device-config",
        "probes": True,
    }
    [match] = reader["platforms"]
    assert match["package"] == yaml.safe_load(PACKAGE.read_text())["id"]
    pair = (match["platform"], match["manufacturer"])
    assert [(item["name"], item["manufacturer"]) for item, _ in of("DcimPlatform")] == [pair]
    assert [item["name"] for item, _ in of("OrganizationManufacturer")] == [match["manufacturer"]]
