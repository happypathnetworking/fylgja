"""The read (D-118): Nautobot as it stands, under a scope, into a blueprint 1 with its source envelope, or the findings
that refused it, every rule judged in one pass (Constitution III), every list held whole, every scoped device rendered
by Golden Config, and the bracket opened before the first list and closed after the last render, on every path past
the open (D-098). Over rows built in the tests and `FakeSource`, never Nautobot's answers (D-034)."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

import pytest
from fake import (
    CHANGE,
    DOCUMENT,
    GROUP,
    MANUFACTURER,
    PLATFORM,
    REPOSITORY,
    SETTING,
    TAG,
    THREE_NODE,
    FakeSource,
    listing,
    three_node,
)
from fylgja_core import blueprint
from fylgja_core.findings import Finding

from fylgja_nautobot import NautobotError, Result, check, read
from fylgja_nautobot.rows import Cable, Change, Device, End, Rendered, Repository

SCOPE = "tag:fylgja"
FIXTURE = json.loads(THREE_NODE.read_text())
FIXTURE_ID = blueprint.blueprint_id(FIXTURE)
CONFIGS = {device["name"]: device["config"] for device in FIXTURE["network"]["devices"]}
NO_SETTING = "No Golden Config settings found for this device"
FAILED = "Error rendering Jinja template: Subtask: GENERATE CONFIG (failed)\n"
UNVERIFIED = Finding(
    rule="nautobot.version.unverified",
    severity="warning",
    object="3.2.9/3.0.8",
    message="Nautobot is version 3.2.9 with Golden Config 3.0.8, and this reader is verified on 3.2.8 alone.",
)
OBSERVED = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")
LATER = Change("change-2", "2026-11-19T21:00:07.000001Z")
"""A row newer than `fake.CHANGE`, written during a read."""


def done(conn: FakeSource, *, scope: str = SCOPE) -> Result:
    return read(conn, scope=scope, document=DOCUMENT)


def rules(result: Result) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in result.findings]


def errors(result: Result) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in result.findings if finding.severity == "error"]


def but_observed(doc: dict[str, Any]) -> dict[str, Any]:
    held: dict[str, Any] = json.loads(json.dumps(doc))
    del held["source"]["observed_at"]
    return held


def moving(conn: FakeSource) -> FakeSource:
    """`conn` whose changelog moves after the open: its first `newest` answers the open's row, every later one a row
    written during the read."""
    opened = conn.held_newest
    answers = [opened]

    def newest() -> tuple[int, Change | None]:
        conn.calls.append("newest")
        held = answers.pop(0) if answers else (opened[0] + 1, LATER)
        return held

    conn.newest = newest  # type: ignore[method-assign]
    return conn


def short(what: str) -> FakeSource:
    """`three_node`'s rows with the list `what` answered one short of its count."""
    conn = three_node()
    held = {
        "extras.tag": "held_tags",
        "dcim.device": "held_devices",
        "dcim.platform": "held_platforms",
        "dcim.manufacturer": "held_manufacturers",
        "dcim.interface": "held_ports",
        "dcim.cable": "held_cables",
        "extras.dynamicgroup": "held_groups",
        "extras.staticgroupassociation": "held_stored",
    }[what]
    listed = getattr(conn, held)
    setattr(conn, held, replace(listed, count=listed.count + 1))
    return conn


def refused(what: str) -> NautobotError:
    """What the transport raises where Nautobot answers a list 400: interfaces asked by a device id no device has
    (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8")."""
    return NautobotError(f'reading {what}: HTTP 400: {{"device_id": ["Select a valid choice."]}}', 400)


def test_three_node_reads_to_the_fixtures_id() -> None:
    result = done(three_node())
    assert result.findings == ()
    assert result.empty is False
    assert result.blueprint is not None
    assert blueprint.validate(result.blueprint) == []
    assert blueprint.blueprint_id(result.blueprint) == FIXTURE_ID
    assert {device["name"]: device["config"] for device in result.blueprint["network"]["devices"]} == CONFIGS
    assert result.blueprint["probes"] == []


@pytest.mark.parametrize("scope", ["site:x", "tag:", "fylgja", ""])
def test_a_scope_that_is_no_tag_sends_nothing(scope: str) -> None:
    conn = three_node()
    result = done(conn, scope=scope)
    assert rules(result) == [("scope.invalid", scope)]
    assert result.blueprint is None and result.empty is False
    assert conn.calls == []


def test_a_nautobot_without_golden_config_sends_nothing_more() -> None:
    conn = three_node()
    conn.golden_config = None
    result = done(conn)
    assert rules(result) == [("golden_config.absent", "nautobot_golden_config")]
    assert "nautobot_golden_config" in result.findings[0].message
    assert result.blueprint is None and result.empty is False
    assert conn.calls == []


def test_a_scope_selecting_nothing_is_empty() -> None:
    conn = three_node()
    conn.held_tags = listing("extras.tag", [])
    result = done(conn)
    assert (result.blueprint, rules(result), result.empty) == (None, [("scope.empty", SCOPE)], True)
    assert "no tag fylgja" in result.findings[0].message
    assert "devices" not in conn.calls

    conn = three_node()
    conn.held_devices = listing("dcim.device", [])
    result = done(conn)
    assert (result.blueprint, rules(result), result.empty) == (None, [("scope.empty", SCOPE)], True)
    assert "no dcim.device carries the tag fylgja" in result.findings[0].message
    assert "render" not in conn.calls and "platforms" not in conn.calls


@pytest.mark.parametrize(
    "what",
    [
        "extras.tag",
        "dcim.device",
        "dcim.platform",
        "dcim.manufacturer",
        "dcim.interface",
        "dcim.cable",
        "extras.dynamicgroup",
        "extras.staticgroupassociation",
    ],
)
def test_a_list_that_is_not_whole_ends_the_read(what: str) -> None:
    conn = short(what)
    result = done(conn)
    assert rules(result) == [("read.incomplete", what)]
    assert result.blueprint is None and result.empty is False
    assert "render" not in conn.calls
    assert conn.calls[-2:] == ["newest", "repositories"], "the close was not taken"


def test_an_id_asked_for_and_not_answered_ends_the_read() -> None:
    """The platforms, the manufacturers and the cables are held to the ids asked: `mapping.build` is never given a
    device whose platform, or a platform whose manufacturer, is not among those read."""
    conn = three_node()
    devices = list(conn.held_devices.items)
    devices[1] = replace(devices[1], platform="platform-2")
    conn.held_devices = listing("dcim.device", devices)
    result = done(conn)
    assert rules(result) == [("read.incomplete", "dcim.platform")]
    assert "platform-2" in result.findings[0].message
    assert "manufacturers" not in conn.calls and "render" not in conn.calls

    conn = three_node()
    conn.held_platforms = listing("dcim.platform", [replace(PLATFORM, manufacturer="manufacturer-2")])
    result = done(conn)
    assert rules(result) == [("read.incomplete", "dcim.manufacturer")]
    assert "manufacturer-2" in result.findings[0].message

    conn = three_node()
    ports = list(conn.held_ports.items)
    ports[0] = replace(ports[0], cable="cable-9")
    conn.held_ports = listing("dcim.interface", ports)
    result = done(conn)
    assert rules(result) == [("read.incomplete", "dcim.cable")]
    assert "render" not in conn.calls


def test_the_bracket_opens_before_the_first_list_and_closes_after_the_last_render() -> None:
    conn = three_node()
    assert done(conn).blueprint is not None
    assert conn.calls[:3] == ["newest", "settings", "repositories"]
    assert conn.calls[3:9] == ["tags", "devices", "platforms", "manufacturers", "ports", "cables"]
    assert conn.calls[9:12] == ["groups", "stored", "matching"]
    assert conn.calls[12:15] == ["render"] * 3
    assert conn.calls[15:] == ["newest", "repositories"]


def test_groups_are_read_inside_the_bracket() -> None:
    """After the cables and before the renders, the groups of the settings the open listed are listed by their ids,
    and each group's stored members and what its filter lists, each restricted to the scoped devices."""
    conn = three_node()
    assert done(conn).blueprint is not None
    scoped = ("device-1", "device-2", "device-3")
    assert conn.groups_asked == [(SETTING.group,)]
    assert conn.stored_asked == [(GROUP.id, scoped)]
    assert conn.matching_asked == [((("tags", "fylgja"),), scoped)]

    conn = three_node()
    conn.held_settings = listing("nautobot_golden_config.goldenconfigsetting", [SETTING, replace(SETTING, id="s-2")])
    assert done(conn).blueprint is not None
    assert conn.groups_asked == [(SETTING.group,)]

    conn = three_node()
    conn.held_groups = listing("extras.dynamicgroup", [])
    result = done(conn)
    assert rules(result) == [("read.incomplete", "extras.dynamicgroup")]
    assert SETTING.group in result.findings[0].message
    assert "render" not in conn.calls and "stored" not in conn.calls
    assert conn.calls[-2:] == ["newest", "repositories"]


def test_a_stale_group_refuses_the_read_with_the_render_beside_it() -> None:
    """A device tagged since the group's last save is listed by the filter and not stored, and Golden Config refuses
    its render: both are filed, each naming its own object."""
    conn = three_node()
    conn.held_stored = listing("extras.staticgroupassociation", ["device-1", "device-2"])
    conn.renders["device-3"] = Rendered(400, None, NO_SETTING)
    result = done(conn)
    assert errors(result) == [("group.stale", GROUP.name), ("render.setting.absent", "n3")]
    assert result.blueprint is None
    stale = result.findings[0]
    assert "n3" in stale.message and "RefreshDynamicGroupCaches" in stale.message
    assert conn.rendered == ["device-1", "device-2", "device-3"]


def test_a_group_the_reader_cannot_check_warns_and_sends_nothing_for_it() -> None:
    conn = three_node()
    conn.held_groups = listing("extras.dynamicgroup", [replace(GROUP, kind="dynamic-set", filter={})])
    result = done(conn)
    assert rules(result) == [("group.unchecked", GROUP.name)]
    assert result.blueprint is not None
    assert "stored" not in conn.calls and "matching" not in conn.calls


def test_a_refused_open_has_no_close() -> None:
    """The open's own lists not whole end the read with what they say, and nothing is listed or closed (D-098)."""
    conn = three_node()
    conn.held_settings = replace(conn.held_settings, count=2)
    result = done(conn)
    assert rules(result) == [("read.incomplete", "nautobot_golden_config.goldenconfigsetting")]
    assert conn.calls == ["newest", "settings"]

    conn = three_node()
    error = NautobotError("reading extras.objectchange: HTTP 400: x", 400)
    conn.raising = {"newest": error}
    with pytest.raises(NautobotError) as raised:
        done(conn)
    assert raised.value is error
    assert conn.calls == ["newest"]


def test_an_edit_during_a_read_is_moved() -> None:
    conn = moving(three_node())
    result = done(conn)
    assert rules(result) == [("read.moved", "extras.objectchange")]
    assert result.blueprint is None
    for said in (CHANGE.id, CHANGE.time, LATER.id, LATER.time, "read again"):
        assert said in result.findings[0].message, said

    conn = three_node()
    opened = conn.repositories
    asked = 0

    def pushed(ids: Any) -> Any:
        nonlocal asked
        asked += 1
        held = opened(ids)
        if asked == 1:
            return held
        return listing("extras.gitrepository", [Repository(REPOSITORY.id, REPOSITORY.name, "f" * 40)])

    conn.repositories = pushed  # type: ignore[method-assign]
    result = done(conn)
    assert rules(result) == [("read.moved", REPOSITORY.name)]
    assert REPOSITORY.head in result.findings[0].message and "f" * 40 in result.findings[0].message


def test_the_close_is_taken_on_every_path() -> None:
    for conn, refusal in ((three_node(), "scope.empty"), (short("dcim.interface"), "read.incomplete")):
        if refusal == "scope.empty":
            conn.held_devices = listing("dcim.device", [])
        moving(conn)
        result = done(conn)
        assert sorted(rule for rule, _ in rules(result)) == sorted([refusal, "read.moved"])
        assert result.blueprint is None
        assert result.empty is (refusal == "scope.empty")
        assert conn.calls[-2:] == ["newest", "repositories"]

    conn = three_node()
    conn.raising = {"ports": refused("dcim.interface")}
    with pytest.raises(NautobotError):
        done(conn)
    assert conn.calls[-2:] == ["newest", "repositories"], "the close was not taken after a list's 400"

    conn = three_node()
    conn.renders["device-1"] = Rendered(400, None, "Device with id 'device-1' not found")
    done(conn)
    assert conn.calls[-2:] == ["newest", "repositories"], "the close was not taken after a render's 400"


@pytest.mark.parametrize(("call", "what"), [("devices", "dcim.device"), ("ports", "dcim.interface")])
def test_a_400_after_the_open_is_weighed_at_the_close(call: str, what: str) -> None:
    """Nautobot answers 400 to a list by an id it does not hold, so an object deleted between the read's own list and
    a request by its id shows so: the read takes the close, and where it moved the read is `read.moved` alone; where it
    did not, the transport's error is raised as it came."""
    conn = moving(three_node())
    conn.raising = {call: refused(what)}
    result = done(conn)
    assert rules(result) == [("read.moved", "extras.objectchange")]
    assert result.blueprint is None
    assert "render" not in conn.calls

    conn = three_node()
    error = refused(what)
    conn.raising = {call: error}
    with pytest.raises(NautobotError) as raised:
        done(conn)
    assert raised.value is error
    assert conn.calls[-2:] == ["newest", "repositories"]


def test_a_400_whose_close_cannot_tell_is_incomplete_with_its_words() -> None:
    """A close whose repositories are not listed whole cannot tell whether a head moved: the read is refused by that
    `read.incomplete`, carrying the 400's own words, so that both are seen."""
    conn = three_node()
    conn.raising = {"ports": refused("dcim.interface")}
    opened = conn.repositories
    asked = 0

    def repositories(ids: Any) -> Any:
        nonlocal asked
        asked += 1
        held = opened(ids)
        return held if asked == 1 else replace(held, count=2)

    conn.repositories = repositories  # type: ignore[method-assign]
    result = done(conn)
    assert rules(result) == [("read.incomplete", "extras.gitrepository")]
    assert "HTTP 400" in result.findings[0].message and "Select a valid choice." in result.findings[0].message


def test_another_refusal_passes_through_with_no_close() -> None:
    conn = three_node()
    error = NautobotError("reading dcim.interface: HTTP 500: Server Error", 500)
    conn.raising = {"ports": error}
    with pytest.raises(NautobotError) as raised:
        done(conn)
    assert raised.value is error
    assert conn.calls.count("newest") == 1


def test_a_device_not_found_is_weighed_at_the_close() -> None:
    """Golden Config answers 400 `Device with id '<id>' not found` to a device deleted under the read: where the
    bracket moved, the read is `read.moved` and the render files nothing of its own; where it did not, the device's
    error stands. A 400 in other words is weighed the same; a missing setting, the device's own, stands either way."""
    gone = Rendered(400, None, "Device with id 'device-1' not found")
    conn = moving(three_node())
    conn.renders["device-1"] = gone
    result = done(conn)
    assert rules(result) == [("read.moved", "extras.objectchange")]
    assert conn.rendered == ["device-1", "device-2", "device-3"]

    conn = three_node()
    conn.renders["device-1"] = gone
    result = done(conn)
    assert rules(result) == [("render.device.unknown", "n1")]
    assert result.blueprint is None

    conn = moving(three_node())
    conn.renders["device-1"] = Rendered(400, None, "Select a valid choice.")
    assert rules(done(conn)) == [("read.moved", "extras.objectchange")]

    conn = moving(three_node())
    conn.renders["device-1"] = Rendered(400, None, NO_SETTING)
    conn.renders["device-2"] = Rendered(502, None, None)
    assert sorted(rules(done(conn))) == [
        ("read.moved", "extras.objectchange"),
        ("render.setting.absent", "n1"),
        ("render.unavailable", "n2"),
    ]


def test_every_device_at_fault_is_filed_in_one_pass() -> None:
    conn = three_node()
    conn.renders["device-1"] = Rendered(400, None, NO_SETTING)
    conn.renders["device-2"] = Rendered(400, None, FAILED)
    conn.renders["device-3"] = Rendered(200, "   \n", None)
    result = done(conn)
    assert errors(result) == [
        ("render.empty", "n3"),
        ("render.failed", "n2"),
        ("render.setting.absent", "n1"),
    ]
    assert result.blueprint is None
    assert conn.rendered == ["device-1", "device-2", "device-3"]


def test_no_message_holds_another_devices_configuration() -> None:
    conn = three_node()
    conn.held_devices = listing("dcim.device", list(reversed(conn.held_devices.items)))
    conn.renders["device-2"] = Rendered(400, None, FAILED)
    result = done(conn)
    assert errors(result) == [("render.failed", "n2")]
    assert result.blueprint is None
    lines = {line for name in ("n1", "n3") for line in CONFIGS[name].splitlines() if line.strip()}
    assert lines
    for finding in result.findings:
        assert [line for line in lines if line in finding.message] == []


def test_the_renders_are_in_name_order_then_id_a_device_the_mapping_refused_among_them() -> None:
    conn = three_node()
    devices = [
        Device("device-5", "n2", None),
        Device("device-4", "n2", PLATFORM.id),
        Device("device-3", "a", PLATFORM.id),
        Device("device-9", None, PLATFORM.id),
        Device("device-8", None, PLATFORM.id),
    ]
    conn.held_devices = listing("dcim.device", devices)
    conn.held_ports = listing("dcim.interface", [])
    conn.held_cables = listing("dcim.cable", [])
    conn.renders = {device.id: Rendered(200, "x\n", None) for device in devices}
    done(conn)
    assert conn.rendered == ["device-3", "device-4", "device-5", "device-8", "device-9"]


def test_the_envelope_holds_its_seven_members_and_none_is_hashed() -> None:
    conn = three_node()
    result = done(conn)
    assert result.blueprint is not None
    source = result.blueprint["source"]
    assert list(source) == ["source", "scope", "mapping", "changelog", "templates", "observed_at", "fidelity"]
    assert source["source"] == "nautobot"
    assert source["scope"] == SCOPE
    assert source["mapping"] == {"reader": "nautobot-dcim", "model": "nautobot", "version": "3.2.8"}
    assert source["changelog"] == {"id": CHANGE.id, "time": CHANGE.time}
    assert source["templates"] == {"fylgja-templates": REPOSITORY.head}
    assert OBSERVED.match(source["observed_at"])
    assert source["fidelity"] == [
        {
            "disposition": "omitted",
            "object": "platform.version",
            "source": "dcim.platform",
            "reason": "Nautobot's platform carries no version",
        }
    ]
    assert list(result.blueprint) == ["blueprint_version", "network", "probes", "source"]
    assert result.blueprint["blueprint_version"] == "1"

    other = three_node()
    other.held_newest = (0, None)
    other.held_settings = listing("nautobot_golden_config.goldenconfigsetting", [])
    other.held_repositories = listing("extras.gitrepository", [])
    other.held_groups = listing("extras.dynamicgroup", [])
    empty = done(other)
    assert empty.blueprint is not None
    assert (empty.blueprint["source"]["changelog"], empty.blueprint["source"]["templates"]) == (None, {})
    assert blueprint.blueprint_id(empty.blueprint) == blueprint.blueprint_id(result.blueprint) == FIXTURE_ID


def test_rows_in_any_order_read_to_one_id() -> None:
    conn = three_node()
    conn.held_devices = listing("dcim.device", list(reversed(conn.held_devices.items)))
    conn.held_ports = listing("dcim.interface", list(reversed(conn.held_ports.items)))
    swapped = [Cable(cable.id, cable.label, cable.b, cable.a) for cable in reversed(conn.held_cables.items)]
    conn.held_cables = listing("dcim.cable", swapped)
    result = done(conn)
    assert result.blueprint is not None
    expected = done(three_node()).blueprint
    assert expected is not None
    assert but_observed(result.blueprint) == but_observed(expected)
    assert blueprint.blueprint_id(result.blueprint) == FIXTURE_ID


def test_the_findings_are_in_one_order_whatever_the_rows_order() -> None:
    def faulted(reverse: bool) -> FakeSource:
        conn = three_node()
        devices = [replace(d, name=d.name.upper()) if d.name else d for d in conn.held_devices.items]
        devices[1] = replace(devices[1], platform=None)
        ports = list(conn.held_ports.items)
        far = Cable("cable-9", "far", (End("dcim.interface", "x", "x"),), (End("dcim.interface", ports[0].id, None),))
        cables = [*conn.held_cables.items, far]
        ports[0] = replace(ports[0], cable="cable-9")
        if reverse:
            devices.reverse()
            ports.reverse()
            cables = [Cable(c.id, c.label, c.b, c.a) for c in reversed(cables)]
        conn.held_devices = listing("dcim.device", devices)
        conn.held_ports = listing("dcim.interface", ports)
        conn.held_cables = listing("dcim.cable", cables)
        conn.renders["device-1"] = Rendered(400, None, FAILED)
        conn.renders["device-3"] = Rendered(200, "", None)
        return conn

    first, second = done(faulted(False)), done(faulted(True))
    assert [(f.severity, f.rule, f.object) for f in first.findings] == [
        ("error", "platform.missing", "N2"),
        ("error", "render.empty", "N3"),
        ("error", "render.failed", "N1"),
        ("info", "device.name.renamed", "N1"),
        ("info", "device.name.renamed", "N2"),
        ("info", "device.name.renamed", "N3"),
        ("info", "omit.cable.outside_scope", "far"),
    ]
    assert first.findings == second.findings


def test_a_blueprint_is_none_exactly_when_a_finding_is_an_error() -> None:
    conn = three_node()
    devices = list(conn.held_devices.items)
    devices[0] = replace(devices[0], name="N1")
    conn.held_devices = listing("dcim.device", devices)
    result = done(conn)
    assert rules(result) == [("device.name.renamed", "N1")]
    assert result.blueprint is not None
    assert {row["object"] for row in result.blueprint["source"]["fidelity"]} == {"N1", "platform.version"}

    conn = three_node()
    conn.renders["device-3"] = Rendered(200, "\t\n", None)
    found = done(conn)
    assert errors(found) == [("render.empty", "n3")]
    assert found.blueprint is None


def test_a_problem_of_the_blueprint_built_is_an_error() -> None:
    """`read` holds what it built to blueprint 1 and files each problem under the problem's own rule, its pointer the
    object: a name of Nautobot's that UTF-8 cannot encode has no id."""
    conn = three_node()
    ports = list(conn.held_ports.items)
    ports[4] = replace(ports[4], name="ethernet-\ud800")
    conn.held_ports = listing("dcim.interface", ports)
    result = done(conn)
    assert result.blueprint is None
    held = [finding for finding in result.findings if finding.rule == "blueprint.unencodable"]
    assert [finding.severity for finding in held] == ["error"]
    assert (held[0].object or "").startswith("/network/devices/0/interfaces/")


def test_two_tags_of_the_scopes_name_are_refused() -> None:
    """Which of two tags of the name the read would take cannot be told: Nautobot's error of status 200
    (transport.named), raised before the devices of either are asked, and passed through as any refusal but a 400."""
    conn = three_node()
    conn.held_tags = listing("extras.tag", [TAG, replace(TAG, id="tag-2")])
    with pytest.raises(NautobotError) as raised:
        done(conn)
    assert raised.value.status == 200
    assert "devices" not in conn.calls
    assert conn.calls.count("newest") == 1


def test_the_version_warning_rides_on_every_result() -> None:
    conn = three_node()
    conn.unverified = UNVERIFIED
    result = done(conn)
    assert result.blueprint is not None
    assert result.findings == (UNVERIFIED,)

    assert UNVERIFIED in done(conn, scope="site:x").findings
    conn.golden_config = None
    assert rules(done(conn)) == [
        ("golden_config.absent", "nautobot_golden_config"),
        (UNVERIFIED.rule, UNVERIFIED.object),
    ]
    assert check(conn) == tuple(done(conn).findings)


def test_check_sends_nothing() -> None:
    conn = three_node()
    assert check(conn) == ()
    conn.unverified = UNVERIFIED
    assert check(conn) == (UNVERIFIED,)
    conn.golden_config = None
    assert [(f.rule, f.object) for f in check(conn)] == [
        ("golden_config.absent", "nautobot_golden_config"),
        (UNVERIFIED.rule, UNVERIFIED.object),
    ]
    assert conn.calls == []


def test_the_manufacturers_asked_are_the_platforms() -> None:
    conn = three_node()
    asked: list[tuple[str, ...]] = []
    held = conn.manufacturers

    def manufacturers(ids: Any) -> Any:
        asked.append(tuple(ids))
        return held(ids)

    conn.manufacturers = manufacturers  # type: ignore[method-assign]
    done(conn)
    assert asked == [(MANUFACTURER.id,)]
