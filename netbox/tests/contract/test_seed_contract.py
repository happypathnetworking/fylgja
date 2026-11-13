"""`netbox/seed/seed.py` against the running development NetBox: the fixture on `main`, each device's configuration
as NetBox renders it, the change's two steps on a branch of the test's own, the probes' context, and a second seed.

The module's fixture seeds `main` first, as `make netbox-seed` does; on a `main` the seed has already filled it
writes nothing.

The tests rest on two budgets (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"). Every request
is given `box.py`'s `TIMEOUT_S`, 30 s, a first value: a render of one device read under 0.5 s, and of three 1.4 s to
2.1 s; the seed's slowest lookup, an interface's, 1.18 s; and the slowest request read, a branch's `DELETE`, read in
scripts beside the tier and not as the `branch` fixture ends, 3.41 s and 3.31 s in one script and 2.83 s in another;
30 s is 8.8 times the slowest, a derivation. The `branch` fixture waits up to `BRANCH_WAIT_S`, 120 s, for `ready`:
branches read `ready` 11.1 s at most after their request, and two whose `DELETE` NetBox refused while they
provisioned read `ready` at reads 26.7 s to 28.2 s after it; 120 s is about 4.3 times the slowest, 28.2 s, a
derivation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import seed
from box import Box

ROOT = Path(__file__).resolve().parents[3]
FILES = ROOT / "netbox" / "seed"
NETWORK = ROOT / "testdata" / "blueprint" / "three-node.json"

FIRST = "# {name}: production configuration rendered by NetBox (fylgja-srlinux)"
"""The first line of each configuration: the template's own, where the blueprint's is Infrahub's."""

LACKED = {
    "n1": 'set / interface ethernet-1/2 description "to n3 ethernet-1/2"',
    "n3": 'set / interface ethernet-1/2 description "to n1 ethernet-1/2"',
}
"""The line of each device's configuration in the blueprint that `main` lacks with no link between `n1` and `n3`."""

ADDRESS = "192.0.2.1/24"
"""The change's second step: an address on `n1 ethernet-1/2`, the documentation range's."""


@pytest.fixture(scope="module")
def fixture(box: Box) -> dict[str, Any]:
    """`main` seeded, and the fixture it was seeded from."""
    seed.seed(box, FILES)
    return seed.load(FILES)


def configurations() -> dict[str, list[str]]:
    """The blueprint's configuration of each device, by its name, as lines."""
    network = json.loads(NETWORK.read_text())["network"]
    return {device["name"]: device["config"].split("\n") for device in network["devices"]}


def devices(box: Box, branch: str | None = None) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in box.listed("dcim/devices/", branch=branch, tag=seed.TAG)}


def rendered(box: Box, branch: str | None = None) -> dict[str, str]:
    """Each device of the scope's configuration as NetBox renders it, under `branch` where it is given."""
    found = {}
    for name, row in devices(box, branch).items():
        answer = box.post(f"dcim/devices/{row['id']}/render-config/", None, branch=branch)
        assert answer["configtemplate"]["name"] == "fylgja-srlinux"
        found[name] = answer["content"]
    return found


def port(box: Box, device: str, name: str, branch: str | None = None) -> dict[str, Any]:
    number = devices(box, branch)[device]["id"]
    found = box.one("dcim/interfaces/", branch=branch, device_id=number, name=name)
    assert found is not None, f"{device} {name}"
    return found


def test_main_holds_the_fixture(box: Box, fixture: dict[str, Any]) -> None:
    held = devices(box)
    assert sorted(held) == ["n1", "n2", "n3"]
    ports = [row for device in held.values() for row in box.listed("dcim/interfaces/", device_id=device["id"])]
    assert len(ports) == 15
    assert sorted((row["device"]["name"], row["name"]) for row in ports if row["mgmt_only"]) == [
        ("n1", "mgmt0"),
        ("n2", "mgmt0"),
        ("n3", "mgmt0"),
    ]
    addresses = [row for device in held.values() for row in box.listed("ipam/ip-addresses/", device_id=device["id"])]
    assert len(addresses) == 6
    cables = {
        row["id"]: seed.cabled(row)
        for device in held.values()
        for row in box.listed("dcim/cables/", device_id=device["id"])
    }
    assert sorted(cables.values(), key=seed.joined) == sorted(
        (frozenset(cable) for cable in fixture["cables"]), key=seed.joined
    )
    assert seed.differences(box, fixture) == []


def test_each_device_renders_three_nodes_configuration(box: Box, fixture: dict[str, Any]) -> None:
    """The blueprint's line for line after the first, but the far end of the link `main` lacks; each ends in the
    newline the template writes after its last line, as a newline written inside a loop was read kept."""
    wanted = configurations()
    for name, text in rendered(box).items():
        lines = text.split("\n")
        assert lines[0] == FIRST.format(name=name)
        assert lines[1:] == [line for line in wanted[name][1:] if line != LACKED.get(name)], name
        assert text[-1:] == "\n"


def test_the_changes_two_steps_each_move_a_configuration(
    box: Box, fixture: dict[str, Any], branch: dict[str, Any]
) -> None:
    """On the test's own branch, made and waited for until `ready` by the fixture, up to `BRANCH_WAIT_S`, 120 s:
    branches read `ready` 11.1 s at most after their request, and two whose `DELETE` NetBox refused while they
    provisioned read `ready` at reads 26.7 s to 28.2 s after it (design/verified-facts.md, "NetBox 4.7.5 with
    netbox-branching 1.2.3"); 120 s is about 4.3 times the slowest, 28.2 s, a derivation."""
    under = branch["schema_id"]
    main = rendered(box)
    before = rendered(box, under)
    assert before == main

    a, b = port(box, "n1", "ethernet-1/2", under), port(box, "n3", "ethernet-1/2", under)
    box.post(
        "dcim/cables/",
        {
            "a_terminations": [{"object_type": seed.INTERFACE, "object_id": a["id"]}],
            "b_terminations": [{"object_type": seed.INTERFACE, "object_id": b["id"]}],
            "status": "connected",
        },
        branch=under,
    )
    wanted = configurations()
    linked = rendered(box, under)
    for name in ("n1", "n3"):
        assert linked[name].split("\n")[1:] == wanted[name][1:], name
    assert linked["n2"] == before["n2"]
    assert rendered(box) == main

    box.post(
        "ipam/ip-addresses/",
        {"address": ADDRESS, "status": "active", "assigned_object_type": seed.INTERFACE, "assigned_object_id": a["id"]},
        branch=under,
    )
    addressed = rendered(box, under)
    after = "set / interface ethernet-1/2 subinterface 0 admin-state enable"
    lines = linked["n1"].split("\n")
    at = lines.index(after) + 1
    gained = [
        "set / interface ethernet-1/2 subinterface 0 ipv4 admin-state enable",
        f"set / interface ethernet-1/2 subinterface 0 ipv4 address {ADDRESS}",
    ]
    assert addressed["n1"].split("\n") == [*lines[:at], *gained, *lines[at:]]
    assert addressed["n2"] == linked["n2"] and addressed["n3"] == linked["n3"]
    assert rendered(box) == main


def test_the_probes_context_is_read_by_its_name_and_reaches_no_device(box: Box, fixture: dict[str, Any]) -> None:
    context = box.one("extras/config-contexts/", name="fylgja-probes")
    assert context is not None
    assert context["is_active"] is False
    assert context["data"] == fixture["probes"]["data"]
    for name, row in devices(box).items():
        assert "probes" not in box.get(f"dcim/devices/{row['id']}/")["config_context"], name


def counts(box: Box) -> dict[str, int]:
    held = devices(box)
    cables = {row["id"] for device in held.values() for row in box.listed("dcim/cables/", device_id=device["id"])}
    return {
        "devices": len(held),
        "interfaces": sum(len(box.listed("dcim/interfaces/", device_id=device["id"])) for device in held.values()),
        "addresses": sum(len(box.listed("ipam/ip-addresses/", device_id=device["id"])) for device in held.values()),
        "cables": len(cables),
    }


def test_the_seed_run_twice_is_one_network(box: Box, fixture: dict[str, Any]) -> None:
    before = counts(box)
    changes = box.get("core/object-changes/", limit=1)["count"]
    already = len(box.ensured)
    seed.seed(box, FILES)
    assert [what for what, _, _ in box.ensured[already:]] == ["found"] * (len(box.ensured) - already)
    assert counts(box) == before == {"devices": 3, "interfaces": 15, "addresses": 6, "cables": 2}
    assert box.get("core/object-changes/", limit=1)["count"] == changes
