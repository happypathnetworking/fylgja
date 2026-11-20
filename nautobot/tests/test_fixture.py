"""The fixture network the seed puts on the development Nautobot, read as files: `nautobot/seed/main.yaml` against
`testdata/blueprint/three-node.json` and `three-node-probed.json`, the reader document `nautobot/seed/reader.yaml`
against the platform package it names, the GraphQL query `nautobot/seed/sotagg.graphql` and the template
`nautobot/seed/templates/nokia_srl.j2` against the configuration lines the blueprint holds.

Nothing here reaches Nautobot: what it makes of the files, and what Golden Config renders, is read on the running
instance (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8") and held by the contract tier.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import seed
import yaml

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "nautobot" / "seed"
FIXTURE = SEED / "main.yaml"
TEMPLATE = SEED / "templates" / "nokia_srl.j2"
QUERY = SEED / "sotagg.graphql"
READER = SEED / "reader.yaml"
NETWORK = ROOT / "testdata" / "blueprint" / "three-node.json"
PROBED = ROOT / "testdata" / "blueprint" / "three-node-probed.json"
PACKAGE = ROOT / "psp" / "nokia_srlinux.yaml"
COMPOSE = ROOT / "nautobot" / "dev" / "compose.yml"

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

DEVICE = re.compile(r"(?<![.\w])device\.")
"""A member read from a `device` the template is not given: Golden Config spreads the query's device as names. A
far port's `….device.name` is the query's own."""

SELECTED = (
    "query ($device_id: ID!) { device(id: $device_id) { hostname: name description: comments config_context"
    " platform { name manufacturer { name } } interfaces { name mgmt_only enabled ip_addresses { address }"
    " cable_peer_interface { name device { name } } } } }"
)
"""The query, its whitespace runs made one space: the device's name as `hostname`, since a top-level `name` is lost
to the render, and its comments as `description`, since a Nautobot device has none."""


def fixture() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(FIXTURE.read_text())
    return loaded


def blueprint(path: Path = NETWORK) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text())
    return loaded


def test_the_fixture_is_three_node_whole() -> None:
    held = fixture()
    network = blueprint()["network"]
    wanted = {device["name"]: device for device in network["devices"]}

    devices = {device["name"]: device for device in held["devices"]}
    assert sorted(devices) == sorted(wanted) == ["n1", "n2", "n3"]
    assert len(held["devices"]) == 3
    for name, device in devices.items():
        assert sorted(device) == ["comments", "interfaces", "name"]
        assert device["comments"] == "FYLGJA-MARKER-fixture"
        ports = {port["name"]: port for port in device["interfaces"]}
        assert len(ports) == len(device["interfaces"]) == 5
        assert {port: about["mgmt_only"] for port, about in ports.items()} == {
            interface["name"]: interface["mgmt_only"] for interface in wanted[name]["interfaces"]
        }
        assert all(interface["enabled"] for interface in wanted[name]["interfaces"])
        for port in ports.values():
            assert sorted(port) == ["addresses", "mgmt_only", "name", "type"]
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

    links = [
        frozenset(f"{end['device']}:{end['interface']}" for end in (link["a"], link["b"])) for link in network["links"]
    ]
    assert all(len(cable) == 2 for cable in held["cables"])
    assert [frozenset(cable) for cable in held["cables"]] == links
    assert len(links) == 3
    for cable in held["cables"]:
        for end in cable:
            device, port = end.split(":")
            assert port in {about["name"] for about in devices[device]["interfaces"]}, end

    assert held["manufacturer"] == {"name": "Nokia"}
    assert held["platform"] == {"name": "SR Linux", "network_driver": "nokia_srl"}
    assert held["device_type"] == {"model": "7220 IXR-D2L"}
    assert held["location_type"] == {"name": "Site"}
    assert held["location"] == {"name": "lab"}
    assert held["role"] == {"name": "fylgja"}
    assert held["tag"] == {"name": "fylgja"}
    assert sorted(held) == [
        "cables",
        "device_type",
        "devices",
        "location",
        "location_type",
        "manufacturer",
        "platform",
        "probes",
        "query",
        "repository",
        "role",
        "setting",
        "tag",
    ]


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


def test_the_setting_is_plan_0s() -> None:
    """The repository the `git` service serves, by its alias and its port in the project's network; the path template
    that names the template by the platform's network driver; the query; and the installed Default Settings' slug and
    its group's filter, the devices tagged `fylgja`."""
    held = fixture()
    git = yaml.safe_load(COMPOSE.read_text())["services"]["git"]
    [alias] = git["networks"]["default"]["aliases"]
    port = git["command"][git["command"].index("http.server") + 1]
    assert held["repository"] == {
        "name": "fylgja-templates",
        "remote_url": f"http://{alias}:{port}/{seed.REPOSITORY}",
        "branch": "main",
    }
    assert held["query"] == "fylgja-sotagg"
    assert held["setting"] == {
        "slug": "default",
        "path": "{{ obj.platform.network_driver }}.j2",
        "filter": {"tags": [held["tag"]["name"]]},
    }
    assert held["setting"]["path"].replace("{{ obj.platform.network_driver }}", held["platform"]["network_driver"]) == (
        TEMPLATE.name
    )
    assert [path.name for path in TEMPLATE.parent.iterdir()] == [TEMPLATE.name]


def fields(text: str, depth: int) -> list[str]:
    """The lines of the query `text` that open no selection and sit `depth` braces in."""
    found = []
    level = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "}":
            level -= 1
            continue
        if level == depth and not stripped.endswith("{"):
            found.append(stripped)
        if stripped.endswith("{"):
            level += 1
    assert level == 0
    return found


def test_the_query_selects_hostname_and_no_top_level_name() -> None:
    """Golden Config spreads the query's device as names into a call whose own argument is `name`, so a top-level
    `name` fails the render and `hostname: name` renders (design/verified-facts.md, "Nautobot 3.2.8 with Golden
    Config 3.0.8")."""
    text = QUERY.read_text()
    assert " ".join(text.split()) == SELECTED
    top = fields(text, 2)
    assert top == ["hostname: name", "description: comments", "config_context"]
    assert "name" not in top


def test_the_template_reads_the_query_alone() -> None:
    text = TEMPLATE.read_text()
    assert "rendered by Golden Config (fylgja-templates)" in text
    for word in ("obj", "NetBox", "Infrahub"):
        assert word not in text, word
    assert DEVICE.search(text) is None
    assert "port.cable_peer_interface.device.name" in text
    for name in ("hostname", "description", "platform", "interfaces", "ip_addresses", "cable_peer_interface"):
        assert name in text, name
    n1 = next(device for device in blueprint()["network"]["devices"] if device["name"] == "n1")
    for words in WORDS:
        assert words in n1["config"], words
        assert words in text, words
