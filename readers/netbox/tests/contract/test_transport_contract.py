"""The transport against the development NetBox: its two versions; a token NetBox never made, refused with its status
and never quoted; the fixture's rows, every list whole; a branch found by its name and read under its header; and a
list of more than a page read whole (CONTRIBUTING.md, Test tiers; design/verified-facts.md, "NetBox 4.7.5 with
netbox-branching 1.2.3"). No assertion message prints the address or a token."""

from __future__ import annotations

import os
import secrets

import httpx
import pytest
from fylgja_core.client import base_url, bearer, trust

from fylgja_netbox import SUPPORTED, NetBox, NetBoxError, connect
from fylgja_netbox.rows import Branch, incomplete
from fylgja_netbox.transport import PAGE, TOKEN

from .conftest import ADDRESS, SENT, Writes, ca, reader, recording

MISSING = "fylgja-contract-none"
"""A branch NetBox lacks: no branch of the tier's own, which are named by 8 hex digits."""

PORTS = 120
"""The ports of the device the page test makes: more than `PAGE`, so two pages."""


def test_the_versions_are_read(conn: NetBox) -> None:
    headers = {"Authorization": bearer(os.environ[TOKEN])}
    with httpx.Client(base_url=base_url(os.environ[ADDRESS]), verify=trust(ca()), trust_env=False) as plain:
        answered = plain.get("/api/status/", headers=headers).json()
    assert (conn.version, conn.branching) == (answered["netbox-version"], answered["plugins"].get("netbox_branching"))
    assert (conn.unverified is None) == ((conn.version, conn.branching) in SUPPORTED)


def refused(raised: pytest.ExceptionInfo[NetBoxError], *phrases: str) -> tuple[int | None, list[str]]:
    """The error's status, and those of `phrases` its text lacks: plain values, so that a failing assertion prints
    neither the error, whose text names the address where NetBox was not reached, nor its repr."""
    text = str(raised.value)
    return raised.value.status, [phrase for phrase in phrases if phrase not in text]


@pytest.mark.usefixtures("conn")
def test_a_wrong_token_is_refused_and_never_quoted() -> None:
    """`/api/status/` refuses a token of NetBox's v2 shape that NetBox never made, 403 `Invalid v2 token`
    (design/verified-facts.md), so `connect` refuses it before any list is asked. It needs the reader's own connection
    made first, so that a NetBox not reached is the fixture's one sentence."""
    key, secret = secrets.token_hex(6), secrets.token_hex(20)
    wrong = f"nbt_{key}.{secret}"
    with pytest.raises(NetBoxError) as raised:
        connect(os.environ[ADDRESS], wrong, ca=ca(), transport=recording("a token NetBox never made"))
    assert refused(raised, "reading NetBox's version", TOKEN) == (403, [])
    quoted = [part in text for text in (str(raised.value), repr(raised.value)) for part in (wrong, key, secret)]
    assert quoted == [False] * 6, "the error quotes the token"
    assert "Invalid v2 token" not in str(raised.value)


def test_the_fixtures_rows(conn: NetBox) -> None:
    tags = conn.tags(None, "fylgja")
    assert incomplete(tags, branch=None) is None
    assert [tag.name for tag in tags.items] == ["fylgja"]

    devices = conn.devices(None, tags.items[0].id)
    assert incomplete(devices, branch=None) is None
    assert devices.count == 3
    assert sorted(device.name or "" for device in devices.items) == ["n1", "n2", "n3"]

    platforms = sorted({device.platform for device in devices.items if device.platform is not None})
    held = conn.platforms(None, platforms)
    assert incomplete(held, branch=None, asked=platforms) is None
    assert [(platform.name, platform.manufacturer) for platform in held.items] == [("SR Linux", "Nokia")]

    ids = sorted(device.id for device in devices.items)
    ports = conn.ports(None, ids)
    assert incomplete(ports, branch=None) is None
    assert ports.count == 15
    assert {port.device for port in ports.items} == set(ids)
    assert {port.name for port in ports.items if port.mgmt_only} == {"mgmt0"}
    assert len([port for port in ports.items if port.mgmt_only]) == 3

    cabled = sorted({port.cable for port in ports.items if port.cable is not None})
    cables = conn.cables(None, cabled)
    assert incomplete(cables, branch=None, asked=cabled) is None
    assert cables.count == 2
    read = {port.id: port.name for port in ports.items}
    for cable in cables.items:
        for side in (cable.a, cable.b):
            assert [(end.kind, end.id in read, end.display == read.get(end.id)) for end in side] == [
                ("dcim.interface", True, True)
            ]


def test_a_branch_is_found_by_its_name_and_read_under_its_header(conn: NetBox, box: Writes, branch: Branch) -> None:
    found = conn.branches(branch.name)
    assert incomplete(found, branch=None) is None
    assert found.items == (branch,)
    assert branch.status == "ready"

    devices = conn.devices(branch, conn.tags(branch, "fylgja").items[0].id)
    n2 = [device.id for device in devices.items if device.name == "n2"]
    port = next(port for port in conn.ports(None, n2).items if port.name == "ethernet-1/1")
    box.patch(f"dcim/interfaces/{port.id}/", {"enabled": False}, branch=branch.schema_id)
    assert [p.enabled for p in conn.ports(branch, n2).items if p.id == port.id] == [False]
    assert [p.enabled for p in conn.ports(None, n2).items if p.id == port.id] == [True]

    assert conn.branches(MISSING).count == 0


def test_a_list_of_more_than_a_page_is_read_whole(box: Writes, branch: Branch) -> None:
    under = branch.schema_id
    kinds = [box.listed(path)[0]["id"] for path in ("dcim/device-types/", "dcim/device-roles/", "dcim/sites/")]
    body = {"name": "fc-dense", "device_type": kinds[0], "role": kinds[1], "site": kinds[2], "status": "active"}
    device = box.post("dcim/devices/", body, branch=under)["id"]
    made = [{"device": device, "name": f"e-{i:03d}", "type": "1000base-t"} for i in range(PORTS)]
    box.post("dcim/interfaces/", made, branch=under)

    with reader() as paging:
        ports = paging.ports(branch, [device])
    assert PORTS > PAGE
    assert (ports.count, len(ports.items), len({port.id for port in ports.items})) == (PORTS, PORTS, PORTS)
    assert incomplete(ports, branch=branch.name) is None
    assert sorted(port.name for port in ports.items) == [f"e-{i:03d}" for i in range(PORTS)]
    assert [path for _, path in SENT[paging]].count("/api/dcim/interfaces/") == 2
