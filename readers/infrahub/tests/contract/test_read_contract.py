"""The read against the development Infrahub: the seeded fixture read into blueprints, `main` and the seeded branch at
each stage's time, each device's configuration its artifact's bytes, a past time read as it stood after a later one,
and a scope no device carries (CONTRIBUTING.md, Test tiers; design/verified-facts.md, "Infrahub 1.11.11"). The seed's
document reads probes, and the seed declares one, so the first stage's blueprint is `three-node-probed.json`'s. Each
assertion compares plain values, so that a failing one prints no blueprint, no address and no token."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fylgja_core import blueprint

from fylgja_infrahub import Infrahub, ReaderDocument, Result, read

from .conftest import ROOT

THREE_NODE_PROBED = ROOT / "testdata" / "blueprint" / "three-node-probed.json"
NONE = "tag:fylgja-contract-none"
"""A scope no device carries: no tag of the seed's."""


def refused(result: Result) -> list[tuple[str, str | None]]:
    """The errors of a result, by rule and object."""
    return [(f.rule, f.object) for f in result.findings if f.severity == "error"]


def built(conn: Infrahub, branch: str, at: str, seed: dict[str, Any], document: ReaderDocument) -> dict[str, Any]:
    """The blueprint of `branch` read at `at` under the seed's scope, which the test asserts was answered."""
    result = read(conn, branch=branch, at=at, scope=seed["scope"], document=document)
    assert refused(result) == []
    assert result.blueprint is not None
    return result.blueprint


def links(doc: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    ends = [(link["a"], link["b"]) for link in doc["network"]["links"]]
    return [(a["device"], a["interface"], b["device"], b["interface"]) for a, b in ends]


def configs(doc: dict[str, Any]) -> dict[str, str]:
    return {device["name"]: device["config"] for device in doc["network"]["devices"]}


def test_the_fixture_reads_to_its_devices_and_links(
    conn: Infrahub, seed: dict[str, Any], document: ReaderDocument
) -> None:
    at = seed["stages"][0]["at"]
    on_main = built(conn, "main", at, seed, document)
    on_branch = built(conn, seed["branch"], at, seed, document)
    for doc in (on_main, on_branch):
        assert blueprint.validate(doc) == []
        assert [(d["name"], d["platform"]) for d in doc["network"]["devices"]] == [
            ("n1", "nokia_srlinux"),
            ("n2", "nokia_srlinux"),
            ("n3", "nokia_srlinux"),
        ]
        for device in doc["network"]["devices"]:
            names = [interface["name"] for interface in device["interfaces"]]
            assert names == sorted(names)
        assert links(doc) == sorted(links(doc))
        assert doc["source"]["at"] == at
    assert links(on_main) == [
        ("n1", "ethernet-1/1", "n2", "ethernet-1/1"),
        ("n2", "ethernet-1/2", "n3", "ethernet-1/1"),
    ]
    assert links(on_branch) == [
        ("n1", "ethernet-1/1", "n2", "ethernet-1/1"),
        ("n1", "ethernet-1/2", "n3", "ethernet-1/2"),
        ("n2", "ethernet-1/2", "n3", "ethernet-1/1"),
    ]
    # The branch at its first stage holds the fixture's network, its configurations byte for byte (the facts), and the
    # seed's probe, so its blueprint is the probed fixture's by id.
    fixture = json.loads(THREE_NODE_PROBED.read_text())
    assert blueprint.blueprint_id(on_branch) == blueprint.blueprint_id(fixture)


def test_every_stage_reads_with_its_configurations(
    conn: Infrahub, seed: dict[str, Any], document: ReaderDocument
) -> None:
    read_at: list[dict[str, str]] = []
    for stage in seed["stages"]:
        doc = built(conn, seed["branch"], stage["at"], seed, document)
        listed = conn.devices(seed["branch"], stage["at"], seed["scope"].removeprefix("tag:"))
        sums = {
            device.name: [a.checksum for a in device.artifacts.items if a.definition == document.artifact]
            for device in listed.items
        }
        held = configs(doc)
        assert sorted(held) == ["n1", "n2", "n3"]
        assert [name for name, text in held.items() if not text] == []
        assert {name: [hashlib.md5(text.encode()).hexdigest()] for name, text in held.items()} == sums
        read_at.append(held)
    assert len(read_at) >= 2
    first, last = (hashlib.md5(held["n1"].encode()).hexdigest() for held in (read_at[0], read_at[-1]))
    assert first != last, "the last stage changes n1's configuration"


def test_a_past_time_reads_the_configuration_as_it_stood(
    conn: Infrahub, seed: dict[str, Any], document: ReaderDocument
) -> None:
    first, last = seed["stages"][0]["at"], seed["stages"][-1]["at"]
    before = configs(built(conn, seed["branch"], first, seed, document))["n1"]
    later = configs(built(conn, seed["branch"], last, seed, document))["n1"]
    again = configs(built(conn, seed["branch"], first, seed, document))["n1"]
    assert (again == before, again == later) == (True, False)


def test_a_scope_no_device_carries_is_empty(conn: Infrahub, seed: dict[str, Any], document: ReaderDocument) -> None:
    at = seed["stages"][0]["at"]
    result = read(conn, branch="main", at=at, scope=NONE, document=document)
    assert (result.blueprint is None, result.empty) == (True, True)
    assert refused(result) == [("scope.empty", NONE)]
