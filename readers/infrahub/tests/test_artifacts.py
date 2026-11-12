"""Each device's configuration is its artifact's content, exactly what Infrahub rendered (D-007, D-082): the one
artifact of the reader document's name, `Ready`, with a storage id and a checksum, whose bytes Infrahub serves and are
the checksum's, as UTF-8 text. Every device at fault is filed in one pass, no content is fetched for one refused from
its listing, and no finding holds a byte of a configuration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import replace

import pytest
from fake import DOCUMENT, THREE_NODE, FakeSource, listing, three_node

from fylgja_infrahub.artifacts import (
    RULE_AMBIGUOUS,
    RULE_INVALID,
    RULE_MISMATCH,
    RULE_MISSING,
    RULE_UNAVAILABLE,
    RULE_UNREADY,
)
from fylgja_infrahub.read import Result, read
from fylgja_infrahub.rows import RULE_INCOMPLETE, Artifact, Connector, Content

BRANCH = "main"
AT = "2026-11-09T10:00:00.000000+00:00"
CONFIGS = {device["name"]: device["config"] for device in json.loads(THREE_NODE.read_text())["network"]["devices"]}
L12 = "n1:ethernet-1/1|n2:ethernet-1/1"


def md5(body: bytes) -> str:
    return hashlib.md5(body).hexdigest()


def ran(source: FakeSource) -> Result:
    return read(source, branch=BRANCH, at=AT, scope="tag:fylgja", document=DOCUMENT)


def listed(source: FakeSource, name: str, artifacts: Sequence[Artifact], count: int | None = None) -> FakeSource:
    """`source` with the device `name` listing `artifacts`, its count `count` where it is given."""
    items = [
        replace(d, artifacts=listing(f"{name}.artifacts", artifacts, count)) if d.name == name else d
        for d in source.held_devices.items
    ]
    source.held_devices = listing("DcimDevice", items)
    return source


def artifact(source: FakeSource, name: str) -> Artifact:
    (found,) = next(d for d in source.held_devices.items if d.name == name).artifacts.items
    return found


def served(source: FakeSource, name: str, body: bytes, *, status: int = 200, listed_as: str | None = None) -> None:
    """`source` serving `body` for the device `name`'s artifact, the artifact listing the checksum `listed_as`, or
    the body's own MD5 where it is None."""
    source.held_content[f"storage-{name}"] = Content(status, body)
    listed(source, name, [replace(artifact(source, name), checksum=listed_as or md5(body))])


def other_name(source: FakeSource) -> None:
    listed(source, "n2", [replace(artifact(source, "n2"), id="artifact-n2-startup", definition="startup-config")])


def two(source: FakeSource) -> None:
    held = artifact(source, "n2")
    listed(source, "n2", [held, replace(held, id="artifact-n2-b", checksum="0" * 32, storage_id="storage-n2-b")])


def pending(source: FakeSource) -> None:
    listed(source, "n2", [replace(artifact(source, "n2"), status="Pending")])


def no_storage(source: FakeSource) -> None:
    listed(source, "n2", [replace(artifact(source, "n2"), storage_id=None)])


def no_checksum(source: FakeSource) -> None:
    listed(source, "n2", [replace(artifact(source, "n2"), checksum=None)])


def not_served(source: FakeSource) -> None:
    source.held_content["storage-n2"] = Content(404, b'{"detail": "not found"}')


def other_bytes(source: FakeSource) -> None:
    source.held_content["storage-n2"] = Content(200, b"set / system name host-name elsewhere\n")


FAULTS: dict[str, tuple[Callable[[FakeSource], None], str, tuple[str, ...]]] = {
    "another name beside": (other_name, RULE_MISSING, ("device-config",)),
    "two": (two, RULE_AMBIGUOUS, (md5(CONFIGS["n2"].encode()), "0" * 32)),
    "pending": (pending, RULE_UNREADY, ("Pending",)),
    "no storage id": (no_storage, RULE_UNREADY, ("storage id",)),
    "no checksum": (no_checksum, RULE_UNREADY, ("checksum",)),
    "not served": (not_served, RULE_UNAVAILABLE, ("404",)),
    "other bytes": (
        other_bytes,
        RULE_MISMATCH,
        (md5(b"set / system name host-name elsewhere\n"), md5(CONFIGS["n2"].encode())),
    ),
    "empty": (lambda source: served(source, "n2", b""), RULE_INVALID, ("empty",)),
    "no UTF-8": (lambda source: served(source, "n2", b"\xff\xfe"), RULE_INVALID, ("UTF-8",)),
}


@pytest.mark.parametrize("fault", list(FAULTS))
def test_each_fault_is_its_rule(fault: str) -> None:
    alter, rule, held = FAULTS[fault]
    source = three_node()
    alter(source)
    result = ran(source)
    assert result.blueprint is None
    assert [(f.rule, f.severity, f.object) for f in result.findings] == [(rule, "error", "n2")]
    for phrase in (*held, BRANCH, AT):
        assert phrase in result.findings[0].message


def lines(*texts: str) -> set[str]:
    return {line for text in texts for line in text.splitlines() if line.strip()}


def test_every_device_at_fault_is_filed_in_one_pass() -> None:
    source = three_node()
    listed(source, "n1", [])
    pending(source)
    source.held_content["storage-n3"] = Content(200, b"set / system name host-name n9\n")
    result = ran(source)
    assert result.blueprint is None
    assert [(f.rule, f.severity, f.object) for f in result.findings] == [
        (RULE_MISMATCH, "error", "n3"),
        (RULE_MISSING, "error", "n1"),
        (RULE_UNREADY, "error", "n2"),
    ]
    content = lines(*CONFIGS.values(), "set / system name host-name n9")
    assert [line for f in result.findings for line in content if line in f.message] == []


@pytest.mark.parametrize("fault", ["another name beside", "two", "pending", "no storage id", "no checksum"])
def test_no_content_is_fetched_for_a_device_refused_from_the_listing(fault: str) -> None:
    """The fake holds no content of `n2`'s, so a fetch of it would be a `KeyError`."""
    alter, rule, _ = FAULTS[fault]
    source = three_node()
    alter(source)
    del source.held_content["storage-n2"]
    result = ran(source)
    assert [(f.rule, f.object) for f in result.findings] == [(rule, "n2")]
    assert [call for call in source.calls if call[0] == "content"] == [("content", BRANCH, AT)] * 2


def no_platform(source: FakeSource, name: str) -> None:
    items = [replace(d, platform=None, manufacturer=None) if d.name == name else d for d in source.held_devices.items]
    source.held_devices = listing("DcimDevice", items)


def other_bytes_of(source: FakeSource, name: str) -> None:
    source.held_content[f"storage-{name}"] = Content(200, b"set / system name host-name elsewhere\n")


@pytest.mark.parametrize(
    ("alter", "rule", "fetched"),
    [
        (lambda source: listed(source, "n1", []), RULE_MISSING, 2),
        (lambda source: other_bytes_of(source, "n1"), RULE_MISMATCH, 3),
    ],
    ids=["no artifact", "bytes not the checksum's"],
)
def test_a_device_without_a_package_has_its_artifact_judged_too(
    alter: Callable[[FakeSource], None], rule: str, fetched: int
) -> None:
    """Choosing the artifact needs the reader document's `artifact` and the listing alone, never the package, so a
    device refused by its platform has its artifact selected, fetched and judged in the same pass (P3-24)."""
    source = three_node()
    no_platform(source, "n1")
    alter(source)
    result = ran(source)
    assert result.blueprint is None
    assert [(f.rule, f.object) for f in result.findings] == sorted([(rule, "n1"), ("platform.missing", "n1")])
    assert [call for call in source.calls if call[0] == "content"] == [("content", BRANCH, AT)] * fetched


def short_artifacts(source: FakeSource) -> str:
    listed(source, "n1", [artifact(source, "n1")], count=2)
    del source.held_content["storage-n1"]
    return "n1.artifacts"


def short_ends(source: FakeSource) -> str:
    items = []
    for port in source.held_ports.items:
        if port.connector is not None and port.connector.label == L12:
            ends = replace(port.connector.ends, count=3)
            port = replace(port, connector=Connector(port.connector.id, "DcimCable", L12, ends))
        items.append(port)
    source.held_ports = listing("InterfacePhysical", items)
    return f"{L12}.connected_endpoints"


@pytest.mark.parametrize("cut", [short_artifacts, short_ends], ids=["a device's artifacts", "a cable's ends"])
def test_a_nested_list_short_of_its_count_is_incomplete(cut: Callable[[FakeSource], str]) -> None:
    """A cable reached from both its ports, each listing two ends of three, is one finding and no omission (P3-1)."""
    source = three_node()
    what = cut(source)
    result = ran(source)
    assert result.blueprint is None
    assert [(f.rule, f.severity, f.object) for f in result.findings] == [(RULE_INCOMPLETE, "error", what)]
    for phrase in ("counted 3" if what.endswith("endpoints") else "counted 2", BRANCH, AT):
        assert phrase in result.findings[0].message
