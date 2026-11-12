"""`make infrahub-seed`'s work as the development Infrahub holds it: the fixture network on `main`, the seeded branch
with its two staged edits, each read at its time and marked, no open proposed change of it, and a second seed's.

A module fixture runs the seed whole, as `make infrahub-seed` does, the reader's kind and the stage kind passed as
`--schema`, with no `--proposed-change`, and each stage timed by the reader's `head`, read with the reader's token,
writing `seed.json` where `FYLGJA_INFRAHUB_SEED` names it, so that the tiers `make contract` runs after this one read
the branch as it leaves it. On an instance seeded already it loads nothing on `main`, removes the earlier seed's marks
and open proposed change, and makes the branch anew.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
import seed
from fylgja_infrahub import times
from hub import Hub

from .conftest import need

SEED = Path(__file__).resolve().parents[2] / "seed"
FIXTURE = Path(__file__).resolve().parents[3] / "testdata" / "blueprint" / "three-node.json"
PROBE_KIND = Path(__file__).resolve().parents[3] / "readers" / "infrahub" / "schema" / "fylgja-probe.yml"
"""The reader's kind, which `make infrahub-seed` passes as `--schema`: absolute, since this tier runs from
`infrahub/`."""
STAGE_KIND = Path(__file__).resolve().parents[2] / "schema" / "fylgja-stage.yml"
"""The example's stage kind, which `make infrahub-seed` passes as a second `--schema`."""

BRANCH = "third-link"
"""The seeded branch, `make infrahub-seed`'s `SEED_BRANCH` as the Makefile gives it."""

DROPPED = {
    "n1": 'set / interface ethernet-1/2 description "to n3 ethernet-1/2"\n',
    "n3": 'set / interface ethernet-1/2 description "to n1 ethernet-1/2"\n',
}
"""The one line of `n1`'s and of `n3`'s configuration that the link `main` lacks would give them."""

ANCHOR = "set / interface ethernet-1/2 subinterface 0 admin-state enable\n"
ADDRESSED = (
    "set / interface ethernet-1/2 subinterface 0 ipv4 admin-state enable\n"
    "set / interface ethernet-1/2 subinterface 0 ipv4 address 192.0.2.1/24\n"
)
"""The two lines the second stage's address gives `n1`'s configuration, after `ANCHOR`."""

NETWORK = """
query ($tag: String!, $name: String!) {
  DcimDevice(tags__name__value: $tag) {
    count
    edges {
      node {
        name { value }
        interfaces {
          count
          edges {
            node {
              name { value }
              ... on InterfacePhysical {
                ip_addresses { count edges { node { address { value } } } }
                connector { node { id } }
              }
            }
          }
        }
        artifacts(name__value: $name) {
          count
          edges { node { status { value } checksum { value } storage_id { value } } }
        }
      }
    }
  }
}
"""


def fixture() -> dict[str, str]:
    """`testdata/blueprint/three-node.json`'s configuration of each device."""
    return {device["name"]: device["config"] for device in json.loads(FIXTURE.read_text())["network"]["devices"]}


def seed_whole() -> dict[str, Any]:
    """`seed.main` run as `make infrahub-seed` runs it, and the file it wrote."""
    out = Path(os.environ["FYLGJA_INFRAHUB_SEED"])
    ctl = os.environ["FYLGJA_INFRAHUB_CTL"]
    argv = ["--branch", BRANCH, "--files", str(SEED), "--out", str(out), "--ctl", ctl]
    assert seed.main([*argv, "--schema", str(PROBE_KIND), "--schema", str(STAGE_KIND)]) == 0
    record: dict[str, Any] = json.loads(out.read_text())
    return record


@pytest.fixture(scope="module")
def seeded(hub: Hub) -> dict[str, Any]:
    need("FYLGJA_INFRAHUB_SEED", seed.READER_TOKEN)
    return seed_whole()


MARKS = """
query ($branch: String!) {
  FylgjaStage(branch__value: $branch) { count edges { node { label { value } as_of { value } description { value } } } }
  CoreProposedChange(source_branch__value: $branch, state__value: "open") { count }
}
"""


def marks(hub: Hub) -> tuple[list[dict[str, str]], int]:
    """The seeded branch's marks on `main`, each its label and `as_of`, in the order of their labels in `seed.EDITS`,
    and how many open proposed changes the branch has."""
    data = hub.gql("main", MARKS, {"branch": BRANCH})
    held = [edge["node"] for edge in data["FylgjaStage"]["edges"]]
    assert data["FylgjaStage"]["count"] == len(held)
    order = [edit.label for edit in seed.EDITS]
    found = [{"label": node["label"]["value"], "at": node["as_of"]["value"]} for node in held]
    return sorted(found, key=lambda mark: order.index(mark["label"])), data["CoreProposedChange"]["count"]


def network(hub: Hub, branch: str, at: str | None = None) -> dict[str, Any]:
    """The scope's devices on `branch`, at the time `at` where it is given."""
    data: dict[str, Any] = hub.gql(branch, NETWORK, {"tag": seed.TAG, "name": seed.DEFINITION}, at=at)["DcimDevice"]
    return data


def counted(devices: dict[str, Any]) -> tuple[int, int, int, int]:
    """The devices, ports, addresses and cables of the scope."""
    ports = [port["node"] for edge in devices["edges"] for port in edge["node"]["interfaces"]["edges"]]
    addresses = sum(port["ip_addresses"]["count"] for port in ports)
    cables = {port["connector"]["node"]["id"] for port in ports if port["connector"]["node"]}
    return devices["count"], len(ports), addresses, len(cables)


def addresses_on(devices: dict[str, Any], device: str, port: str) -> list[str]:
    [edge] = [edge for edge in devices["edges"] if edge["node"]["name"]["value"] == device]
    [held] = [found["node"] for found in edge["node"]["interfaces"]["edges"] if found["node"]["name"]["value"] == port]
    return [found["node"]["address"]["value"] for found in held["ip_addresses"]["edges"]]


def configurations(hub: Hub, devices: dict[str, Any]) -> dict[str, str]:
    """Each device's configuration: its one artifact `Ready`, and the MD5 of the bytes stored for it its checksum."""
    found = {}
    for edge in devices["edges"]:
        name = edge["node"]["name"]["value"]
        [artifact] = [held["node"] for held in edge["node"]["artifacts"]["edges"]]
        assert artifact["status"]["value"] == "Ready", name
        body = hub.rest("GET", f"/api/storage/object/{artifact['storage_id']['value']}").content
        assert hashlib.md5(body).hexdigest() == artifact["checksum"]["value"], name
        found[name] = body.decode()
    return found


def stage(hub: Hub, at: str) -> tuple[tuple[int, int, int, int], dict[str, str]]:
    """The branch's counts and configurations at the time `at`."""
    devices = network(hub, BRANCH, at)
    return counted(devices), configurations(hub, devices)


def test_main_is_left_the_baseline(seeded: dict[str, Any], hub: Hub) -> None:
    devices = network(hub, "main")
    assert counted(devices) == (3, 15, 6, 2)
    configs = configurations(hub, devices)
    assert configs == {name: config.replace(DROPPED.get(name, ""), "") for name, config in fixture().items()}
    assert DROPPED["n1"] not in configs["n1"]


def test_the_file_names_the_branch_the_scope_and_two_stages_in_order(seeded: dict[str, Any]) -> None:
    held = {"branch": BRANCH, "scope": seed.SCOPE, "stages": seeded["stages"], "marks": ["third-link", "n1-address"]}
    assert seeded == held | {"proposed_change": None}
    assert [sorted(found) for found in seeded["stages"]] == [["at", "label"], ["at", "label"]]
    assert [found["label"] for found in seeded["stages"]] == ["third-link", "n1-address"]
    first, second = (found["at"] for found in seeded["stages"])
    assert times.later(second, first)


def test_each_stage_is_marked_at_its_time_and_no_proposed_change_is_open(seeded: dict[str, Any], hub: Hub) -> None:
    """One mark a stage, its `as_of` answered as the seed wrote it, the stage's time verbatim (P5-12); without
    `--proposed-change` the seed leaves the branch no open proposed change (D-088)."""
    assert marks(hub) == (seeded["stages"], 0)


def test_each_stage_reads_its_own_configuration_at_its_time(seeded: dict[str, Any], hub: Hub) -> None:
    first, second = (found["at"] for found in seeded["stages"])
    configs = fixture()

    at_first = network(hub, BRANCH, first)
    assert counted(at_first) == (3, 15, 6, 3)
    assert configurations(hub, at_first) == configs
    assert addresses_on(at_first, "n1", "ethernet-1/2") == []

    at_second = network(hub, BRANCH, second)
    assert counted(at_second) == (3, 15, 7, 3)
    assert configs["n1"].count(ANCHOR) == 1
    assert configurations(hub, at_second) == configs | {"n1": configs["n1"].replace(ANCHOR, ANCHOR + ADDRESSED)}
    assert addresses_on(at_second, "n1", "ethernet-1/2") == ["192.0.2.1/24"]

    assert network(hub, BRANCH) == at_second


def test_a_second_seed_gives_the_same_network_and_later_times(seeded: dict[str, Any], hub: Hub) -> None:
    """Last in the module: it makes the branch anew, and the file then names the second run's times."""
    on_main = network(hub, "main")
    earlier = [stage(hub, found["at"]) for found in seeded["stages"]]
    again = seed_whole()
    assert marks(hub) == (again["stages"], 0), "the earlier seed's marks removed, this one's written"
    assert [stage(hub, found["at"]) for found in again["stages"]] == earlier
    for old, new in zip(seeded["stages"], again["stages"], strict=True):
        assert new["label"] == old["label"]
        assert times.later(new["at"], old["at"])
    assert network(hub, "main") == on_main
