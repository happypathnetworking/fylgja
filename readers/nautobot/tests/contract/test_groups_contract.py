"""A Golden Config setting's dynamic group against the development Nautobot (D-118; design/verified-facts.md, "Nautobot
3.2.8 with Golden Config 3.0.8", "A group's stored members"): the seeded group's stored members are what its filter
lists; and a device tagged since the group's last save is listed by the filter and not stored, so the read is refused
by `group.stale`, naming the group, beside the device's `render.setting.absent`. The one write is a device of the
tier's naming, deleted in a `finally`, after which the group is saved again with its filter, as the seed leaves it. No
assertion message prints the address or a token."""

from __future__ import annotations

from typing import Any

from fylgja_nautobot import Nautobot, ReaderDocument, read
from fylgja_nautobot.groups import judge, params
from fylgja_nautobot.renders import called

from .conftest import Writes, contract_name

SCOPE = "tag:fylgja"
GROUP = "GoldenConfigSetting Default Settings scope"
"""The installed setting's dynamic group, whose filter the seed sets to the devices tagged `fylgja`."""

GROUPS = "extras/dynamic-groups/"


def test_the_seeded_groups_stored_members_are_what_its_filter_lists(conn: Nautobot) -> None:
    (setting,) = conn.settings().items
    (group,) = conn.groups([setting.group]).items
    assert (group.name, group.kind, group.filter) == (GROUP, "dynamic-filter", {"tags": ["fylgja"]})
    devices = conn.devices(conn.tags("fylgja").items[0]).items
    scoped = {device.id: called(device) for device in devices}
    ids = sorted(scoped)
    sent = params(group)
    assert sent == [("tags", "fylgja")]
    stored = conn.stored(group.id, ids)
    matching = conn.matching(sent, ids)
    assert (stored.count, sorted(stored.items)) == (3, ids)
    assert (matching.count, sorted(device.id for device in matching.items)) == (3, ids)
    assert judge(group, stored.items, [device.id for device in matching.items], scoped) is None


def test_a_device_tagged_since_the_last_save_is_stale(conn: Nautobot, box: Writes, document: ReaderDocument) -> None:
    group = box.one(GROUPS, name=GROUP)
    assert group is not None
    kind = box.listed("dcim/device-types/")[0]["id"]
    role, site = box.one("extras/roles/", name="fylgja"), box.one("dcim/locations/", name="lab")
    tag = box.one("extras/tags/", name="fylgja")
    assert role is not None and site is not None and tag is not None
    name = contract_name()
    body = {"name": name, "device_type": kind, "role": role["id"], "location": site["id"], "status": "Active"}
    made: dict[str, Any] | None = None
    try:
        made = box.post("dcim/devices/", {**body, "tags": [tag["id"]]})
        result = read(conn, scope=SCOPE, document=document)
        errors = [(f.rule, f.object) for f in result.findings if f.severity == "error"]
        assert ("group.stale", GROUP) in errors
        assert ("render.setting.absent", name) in errors
        assert result.blueprint is None
        (stale,) = [f for f in result.findings if f.rule == "group.stale"]
        assert name in stale.message and "does not store" in stale.message
        assert "n1" not in stale.message
    finally:
        if made is not None:
            for cable in box.listed("dcim/cables/", device_id=made["id"]):
                box.delete(f"dcim/cables/{cable['id']}/")
            box.delete(f"dcim/devices/{made['id']}/")
        box.patch(f"{GROUPS}{group['id']}/", {"filter": group["filter"]})
    again = read(conn, scope=SCOPE, document=document)
    assert [(f.rule, f.object) for f in again.findings if f.severity == "error"] == []
