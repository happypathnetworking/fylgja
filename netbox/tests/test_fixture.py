"""The fixture network the seed puts on the development NetBox's `main`, read as files: `netbox/seed/main.yaml`
against `testdata/blueprint/three-node.json` and `three-node-probed.json`, the reader document
`netbox/seed/reader.yaml` against the platform package it names, and the configuration template
`netbox/seed/template.j2` against the configuration lines the blueprint holds.

Nothing here reaches NetBox: what it makes of the files, and what the template renders, is read on the running
instance (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3") and held by the contract tier.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "netbox" / "seed"
FIXTURE = SEED / "main.yaml"
TEMPLATE = SEED / "template.j2"
READER = SEED / "reader.yaml"
NETWORK = ROOT / "testdata" / "blueprint" / "three-node.json"
PROBED = ROOT / "testdata" / "blueprint" / "three-node-probed.json"
PACKAGE = ROOT / "psp" / "nokia_srlinux.yaml"

LINK_N1_N3 = frozenset({"n1:ethernet-1/2", "n3:ethernet-1/2"})
"""The blueprint's link that `main` lacks: the change's first step adds it."""

ADDRESS = re.compile(r"^set / interface (\S+) subinterface 0 ipv4 address (\S+)$", re.MULTILINE)

WORDS = (
    "set / system name host-name",
    "set / network-instance default type default",
    'description "to',
    "admin-state",
    "subinterface 0 admin-state enable",
    "subinterface 0 ipv4 admin-state enable",
    "subinterface 0 ipv4 address",
    "set / network-instance default interface",
    "out-of-band management, left to the platform",
)
"""The runs of words the blueprint's configuration lines for `n1` are made of, besides the names and addresses."""


def fixture() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(FIXTURE.read_text())
    return loaded


def blueprint(path: Path = NETWORK) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text())
    return loaded


def test_the_fixture_is_three_node_less_the_link_n1_n3() -> None:
    held = fixture()
    network = blueprint()["network"]
    wanted = {device["name"]: device for device in network["devices"]}

    devices = {device["name"]: device for device in held["devices"]}
    assert sorted(devices) == sorted(wanted) == ["n1", "n2", "n3"]
    assert len(held["devices"]) == 3
    for name, device in devices.items():
        assert device["description"] == "FYLGJA-MARKER-fixture"
        ports = {port["name"]: port for port in device["interfaces"]}
        assert len(ports) == len(device["interfaces"])
        assert {port: about["mgmt_only"] for port, about in ports.items()} == {
            interface["name"]: interface["mgmt_only"] for interface in wanted[name]["interfaces"]
        }
        for port in ports.values():
            assert port["type"] == ("1000base-t" if port["mgmt_only"] else "25gbase-x-sfp28"), (name, port["name"])

    addresses = {
        (device["name"], port["name"], address)
        for device in held["devices"]
        for port in device["interfaces"]
        for address in port["addresses"]
    }
    assert addresses == {
        (name, port, address) for name, device in wanted.items() for port, address in ADDRESS.findall(device["config"])
    }
    assert len(addresses) == 6

    links = {
        frozenset(f"{end['device']}:{end['interface']}" for end in (link["a"], link["b"])) for link in network["links"]
    }
    cables = [frozenset(cable) for cable in held["cables"]]
    assert all(len(cable) == 2 for cable in held["cables"])
    assert set(cables) == links - {LINK_N1_N3}
    assert len(cables) == len(links) - 1
    for cable in cables:
        for end in cable:
            device, port = end.split(":")
            assert port in {about["name"] for about in devices[device]["interfaces"]}, end

    assert held["manufacturer"] == {"name": "Nokia", "slug": "nokia"}
    assert held["platform"] == {"name": "SR Linux", "slug": "sr-linux"}
    assert held["device_type"] == {"model": "7220 IXR-D2L", "slug": "7220-ixr-d2l"}
    assert held["site"] == {"name": "lab", "slug": "lab"}
    assert held["role"] == {"name": "fylgja", "slug": "fylgja"}
    assert held["tag"] == {"name": "fylgja", "slug": "fylgja"}
    assert held["template"] == "fylgja-srlinux"


def test_the_probes_context_is_three_node_probeds_declaration() -> None:
    held = fixture()
    probes = held["probes"]
    assert sorted(probes) == ["data", "name"]
    assert probes["name"] == "fylgja-probes"
    declared = blueprint(PROBED)["probes"]
    assert [probe["name"] for probe in declared] == ["n1-loop"]
    assert probes["data"] == {"probes_version": "1", "probes": declared}
    ports = {(device["name"], port["name"]) for device in held["devices"] for port in device["interfaces"]}
    for probe in probes["data"]["probes"]:
        for endpoint in probe["endpoints"]:
            assert (endpoint["device"], endpoint["interface"]) in ports


def test_the_reader_document_maps_the_fixtures_pair_to_a_shipped_package() -> None:
    reader = yaml.safe_load(READER.read_text())
    assert reader == {
        "reader_version": "1",
        "platforms": [{"manufacturer": "Nokia", "platform": "SR Linux", "package": "nokia_srlinux"}],
        "probes": "fylgja-probes",
    }
    held = fixture()
    [pair] = reader["platforms"]
    assert (pair["manufacturer"], pair["platform"]) == (held["manufacturer"]["name"], held["platform"]["name"])
    assert pair["package"] == yaml.safe_load(PACKAGE.read_text())["id"]
    assert reader["probes"] == held["probes"]["name"]


def test_the_template_is_netboxs_and_names_no_other_source() -> None:
    text = TEMPLATE.read_text()
    assert "rendered by NetBox (fylgja-srlinux)" in text
    assert "Infrahub" not in text
    assert "data." not in text
    n1 = next(device for device in blueprint()["network"]["devices"] if device["name"] == "n1")
    for words in WORDS:
        assert words in n1["config"], words
        assert words in text, words
