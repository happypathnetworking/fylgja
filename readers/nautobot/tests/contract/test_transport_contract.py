"""The transport against the development Nautobot: its two versions; a token Nautobot never made, refused with its
status and never quoted; the fixture's rows, every list whole; a list of more than a page read whole; a tag Nautobot
lacks answered 400, which is why the tag is listed first; and a list by ids batched to the request bound and answered
(CONTRIBUTING.md, Test tiers; design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8"). No assertion
message prints the address or a token."""

from __future__ import annotations

import os
import secrets
import uuid

import httpx
import pytest
from fylgja_core.client import base_url, trust

from fylgja_nautobot import SUPPORTED, Nautobot, NautobotError, connect
from fylgja_nautobot.rows import Tag, incomplete
from fylgja_nautobot.transport import DEVICES, MAX_REQUEST, PAGE, PLATFORMS, TOKEN

from .conftest import ADDRESS, SENT, Writes, ca, contract_name, reader, recording

PORTS = 120
"""The ports of the device the page test makes: more than `PAGE`, so two pages."""

MISSING = "fylgja-contract-none"
"""A tag Nautobot lacks: no tag of the tier's own, which are named by 8 hex digits."""


def test_the_versions_are_read(conn: Nautobot) -> None:
    headers = {"Authorization": f"Token {os.environ[TOKEN]}"}
    with httpx.Client(base_url=base_url(os.environ[ADDRESS]), verify=trust(ca()), trust_env=False) as plain:
        answered = plain.get("/api/status/", headers=headers).json()
    apps = answered["nautobot-apps"]
    assert (conn.version, conn.golden_config) == (answered["nautobot-version"], apps.get("nautobot_golden_config"))
    assert (conn.unverified is None) == ((conn.version, conn.golden_config) in SUPPORTED)


def refused(raised: pytest.ExceptionInfo[NautobotError], *phrases: str) -> tuple[int | None, list[str]]:
    """The error's status, and those of `phrases` its text lacks: plain values, so that a failing assertion prints
    neither the error, whose text names the address where Nautobot was not reached, nor its repr."""
    text = str(raised.value)
    return raised.value.status, [phrase for phrase in phrases if phrase not in text]


@pytest.mark.usefixtures("conn")
def test_a_wrong_token_is_refused_and_never_quoted() -> None:
    """`/api/status/` refuses a token of Nautobot's shape that Nautobot never made, 403 `Invalid token`
    (design/verified-facts.md), so `connect` refuses it before any list is asked. It needs the reader's own connection
    made first, so that a Nautobot not reached is the fixture's one sentence."""
    wrong = secrets.token_hex(20)
    with pytest.raises(NautobotError) as raised:
        connect(os.environ[ADDRESS], wrong, ca=ca(), transport=recording("a token Nautobot never made"))
    assert refused(raised, "reading Nautobot's version", TOKEN) == (403, [])
    assert [wrong in text for text in (str(raised.value), repr(raised.value))] == [False, False], "the token is quoted"
    assert "Invalid token" not in str(raised.value)


def test_the_fixtures_rows(conn: Nautobot) -> None:
    tags = conn.tags("fylgja")
    assert incomplete(tags) is None
    assert [tag.name for tag in tags.items] == ["fylgja"]

    devices = conn.devices(tags.items[0])
    assert incomplete(devices) is None
    assert devices.count == 3
    assert sorted(device.name or "" for device in devices.items) == ["n1", "n2", "n3"]

    platforms = sorted({device.platform for device in devices.items if device.platform is not None})
    held = conn.platforms(platforms)
    assert incomplete(held, asked=platforms) is None
    assert [platform.name for platform in held.items] == ["SR Linux"]
    makers = sorted({platform.manufacturer for platform in held.items if platform.manufacturer is not None})
    found = conn.manufacturers(makers)
    assert incomplete(found, asked=makers) is None
    assert [maker.name for maker in found.items] == ["Nokia"]

    ids = sorted(device.id for device in devices.items)
    ports = conn.ports(ids)
    assert incomplete(ports) is None
    assert ports.count == 15
    assert {port.device for port in ports.items} == set(ids)
    assert {port.name for port in ports.items if port.mgmt_only} == {"mgmt0"}
    assert len([port for port in ports.items if port.mgmt_only]) == 3

    cabled = sorted({port.cable for port in ports.items if port.cable is not None})
    cables = conn.cables(cabled)
    assert incomplete(cables, asked=cabled) is None
    assert cables.count == 3
    read = {port.id: port for port in ports.items}
    for cable in cables.items:
        for side in (cable.a, cable.b):
            assert [(end.kind, end.id in read, end.display) for end in side] == [("dcim.interface", True, None)]
            assert read[side[0].id].cable == cable.id


def test_a_list_of_more_than_a_page_is_read_whole(box: Writes) -> None:
    """A device of the tier's own with `PORTS` interfaces, deleted after, with any cable of it first: Nautobot leaves a
    deleted device's cables standing (design/verified-facts.md)."""
    kind = box.listed("dcim/device-types/")[0]["id"]
    role, site = box.one("extras/roles/", name="fylgja"), box.one("dcim/locations/", name="lab")
    assert role is not None and site is not None
    body = {"name": contract_name(), "device_type": kind, "role": role["id"], "location": site["id"]}
    body["status"] = "Active"
    device = box.post("dcim/devices/", body)["id"]
    try:
        for start in range(0, PORTS, 60):
            made = [
                {"device": device, "name": f"e-{i:03d}", "type": "1000base-t", "status": "Active"}
                for i in range(start, start + 60)
            ]
            box.post("dcim/interfaces/", made)
        with reader() as paging:
            ports = paging.ports([device])
        assert PORTS > PAGE
        assert (ports.count, len(ports.items), len({port.id for port in ports.items})) == (PORTS, PORTS, PORTS)
        assert incomplete(ports) is None
        assert sorted(port.name for port in ports.items) == [f"e-{i:03d}" for i in range(PORTS)]
        assert [sent.path for sent in SENT[paging]].count("/api/dcim/interfaces/") == 2
    finally:
        for cable in box.listed("dcim/cables/", device_id=device):
            box.delete(f"dcim/cables/{cable['id']}/")
        box.delete(f"dcim/devices/{device}/")


def test_an_unknown_tag_value_is_400(conn: Nautobot) -> None:
    """Nautobot answers 400 to `?tags=` of a tag it does not hold, by its name or its id, never an empty list, so the
    read lists the tag first, and a scope no tag has is `scope.empty`, not a refusal."""
    assert conn.tags(MISSING).count == 0
    with pytest.raises(NautobotError) as by_name:
        conn.listed(DEVICES, "dcim.device", [("tags", MISSING)])
    assert refused(by_name, "reading dcim.device: HTTP 400:", "Select a valid choice", MISSING) == (400, [])
    with pytest.raises(NautobotError) as by_id:
        conn.devices(Tag(str(uuid.uuid4()), MISSING))
    assert refused(by_id, "reading dcim.device: HTTP 400:", "Select a valid choice") == (400, [])


def test_a_list_by_ids_is_batched_to_the_bound_and_answered() -> None:
    """The seeded platform's id beside 199 ids no object has: Nautobot answers no row and no error for an id it lacks
    (design/verified-facts.md), so each request is answered, the longest within one id of `MAX_REQUEST` and none
    over it, and the one platform is read. Nautobot dropped a request of 1825 bytes, unanswered, and one of 3000 and
    4097 alike (design/verified-facts.md): that is the reason for the bound, read and not run here."""
    with reader() as batching:
        devices = batching.devices(batching.tags("fylgja").items[0]).items
        real = sorted({device.platform for device in devices if device.platform is not None})[0]
        wanted = [real, *(str(uuid.uuid4()) for _ in range(199))]
        held = batching.platforms(wanted)
    assert [(platform.id, platform.name) for platform in held.items] == [(real, "SR Linux")]
    assert held.count == 1
    asked = [sent for sent in SENT[batching] if sent.path == PLATFORMS]
    lengths = [sent.length for sent in asked[1:]]
    assert len(lengths) > 1
    assert max(lengths) <= MAX_REQUEST
    assert max(lengths) > MAX_REQUEST - len(f"&id={real}")


def test_a_tags_name_is_exact_letter_case_included(conn: Nautobot) -> None:
    """`?name=` of a tag answers the tag of that name alone, letter case included (design/verified-facts.md): the
    transport's check that each row is named as asked rests on it, and a scope's tag is found by its exact name."""
    assert [tag.name for tag in conn.tags("fylgja").items] == ["fylgja"]
    for other in ("FYLGJA", "Fylgja"):
        held = conn.tags(other)
        assert (held.count, held.items) == (0, ()), other


def test_an_id_no_object_has_answers_no_row(conn: Nautobot) -> None:
    """`?id=` of manufacturers, cables, repositories (the seeded setting's), platforms and groups, given a known id
    beside one no object has, answers the known one alone, and given the unknown one alone answers none, with no error
    (design/verified-facts.md): so a lack is told by `rows.incomplete`, never by Nautobot's refusal."""
    devices = conn.devices(conn.tags("fylgja").items[0]).items
    platforms = conn.platforms(sorted({d.platform for d in devices if d.platform is not None})).items
    maker = sorted({p.manufacturer for p in platforms if p.manufacturer is not None})[0]
    ports = conn.ports(sorted(d.id for d in devices)).items
    cable = sorted({p.cable for p in ports if p.cable is not None})[0]
    setting = conn.settings().items[0]
    assert setting.repository is not None
    for call, known in (
        (conn.manufacturers, maker),
        (conn.cables, cable),
        (conn.repositories, setting.repository),
        (conn.platforms, platforms[0].id),
        (conn.groups, setting.group),
    ):
        nobody = str(uuid.uuid4())
        both = call([known, nobody])
        assert (both.count, [row.id for row in both.items]) == (1, [known])
        assert incomplete(both, asked=[known, nobody]) is not None
        alone = call([nobody])
        assert (alone.count, alone.items) == (0, ())
