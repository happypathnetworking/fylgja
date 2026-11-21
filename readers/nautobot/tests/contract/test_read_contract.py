"""The read against the development Nautobot (D-118): the seeded fixture, under `tag:fylgja`, reads to its three
devices and three links, each device's `config` Golden Config's render of it, the envelope carrying the open's newest
row and the template repository's head; and a scope no device carries is `scope.empty`. The renders' text is held to
what the superuser's token renders through `box`, and the network but `config` to `three-node.json`'s
(design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8", "Golden Config's render on the fixture"). The one
write is a tag of the tier's naming, deleted in a `finally`. No assertion message prints the address or a token."""

from __future__ import annotations

import json
from typing import Any

from fylgja_core import blueprint

from fylgja_nautobot import Nautobot, ReaderDocument, read

from .conftest import ROOT, SEEDING, Writes, contract_name

SCOPE = "tag:fylgja"
REPOSITORY = "fylgja-templates"
FIXTURE = json.loads((ROOT / "testdata" / "blueprint" / "three-node.json").read_text())


def but_config(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in device.items() if key != "config"} for device in devices]


def test_the_fixture_reads_to_its_devices_and_links(conn: Nautobot, box: Writes, document: ReaderDocument) -> None:
    result = read(conn, scope=SCOPE, document=document)
    assert [(f.rule, f.object) for f in result.findings if f.severity == "error"] == []
    assert result.blueprint is not None and result.empty is False
    assert blueprint.validate(result.blueprint) == []
    network = result.blueprint["network"]
    assert [(d["name"], d["platform"]) for d in network["devices"]] == [
        ("n1", "nokia_srlinux"),
        ("n2", "nokia_srlinux"),
        ("n3", "nokia_srlinux"),
    ]
    assert but_config(network["devices"]) == but_config(FIXTURE["network"]["devices"])
    assert network["links"] == FIXTURE["network"]["links"]

    rendered = {}
    for row in box.listed("dcim/devices/", tags="fylgja"):
        answer = box.get(SEEDING.RENDER, device_id=row["id"])
        rendered[row["name"]] = answer["intended_config"]
    held = {device["name"]: device["config"] for device in network["devices"]}
    assert held.keys() == rendered.keys()
    assert [name for name in held if held[name] != rendered[name]] == [], "a config is not Golden Config's render"

    source = result.blueprint["source"]
    assert list(source) == ["source", "scope", "mapping", "changelog", "templates", "observed_at", "fidelity"]
    (repository,) = box.listed("extras/git-repositories/", name=REPOSITORY)
    assert source["templates"] == {REPOSITORY: repository["current_head"]}
    assert source["mapping"] == {"reader": "nautobot-dcim", "model": "nautobot", "version": conn.version}
    assert source["changelog"] is not None and set(source["changelog"]) == {"id", "time"}

    again = read(conn, scope=SCOPE, document=document)
    assert again.blueprint is not None
    assert blueprint.blueprint_id(again.blueprint) == blueprint.blueprint_id(result.blueprint)


def test_a_scope_no_device_carries_is_empty(conn: Nautobot, box: Writes, document: ReaderDocument) -> None:
    name = contract_name()
    result = read(conn, scope=f"tag:{name}", document=document)
    assert ([(f.rule, f.object) for f in result.findings], result.empty) == ([("scope.empty", f"tag:{name}")], True)
    assert "lists no tag" in result.findings[0].message

    made: dict[str, Any] | None = None
    try:
        made = box.post("extras/tags/", {"name": name, "content_types": ["dcim.device"]})
        result = read(conn, scope=f"tag:{name}", document=document)
        assert [(f.rule, f.object) for f in result.findings] == [("scope.empty", f"tag:{name}")]
        assert result.empty is True and result.blueprint is None
        assert "no dcim.device carries" in result.findings[0].message
    finally:
        if made is not None:
            box.delete(f"extras/tags/{made['id']}/")
