"""The read (D-095): a branch of NetBox, or `main`, under a scope, into a blueprint 1 with its source envelope, or the
findings that refused it, every rule judged in one pass (Constitution III), every list held whole, every scoped device
rendered, and the bracket opened before the first list and closed after the last render. Over rows built in the tests
and `FakeSource`, never NetBox's answers (D-034)."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

import pytest
from fake import DOCUMENT, PLATFORM, TAG, TEXT, THREE_NODE, FakeSource, listing, three_node
from fylgja_core import blueprint
from fylgja_core.findings import Finding

from fylgja_netbox import NetBoxError, Result, check, read
from fylgja_netbox.rows import Branch, Cable, Change, Device, End, Listing, Rendered

SCOPE = "tag:fylgja"
BRANCH = Branch(7, "b", "p9d46y7z", "ready", "2026-11-12T16:30:00.115200Z")
FIXTURE = json.loads(THREE_NODE.read_text())
FIXTURE_ID = blueprint.blueprint_id(FIXTURE)
CONFIGS = {device["name"]: device["config"] for device in FIXTURE["network"]["devices"]}
FAILED = b"UndefinedError: 'dcim.models.devices.Device object' has no attribute 'nosuch'"
NO_TEMPLATE = b"{'error': 'No config template found for this device.'}"
UNVERIFIED = Finding(
    rule="netbox.version.unverified",
    severity="warning",
    object="4.8.0/1.2.3",
    message="NetBox is version 4.8.0 with netbox-branching 1.2.3, and this reader is verified on 4.7.5 alone.",
)
OBSERVED = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")


def branched(conn: FakeSource, branch: Branch = BRANCH) -> FakeSource:
    conn.held_branches = listing("netbox_branching.branch", [branch])
    return conn


def in_turn(conn: FakeSource, *answers: Listing[Branch]) -> None:
    """`conn.branches` answering `answers` in turn, the last again once they are spent."""
    held = list(answers)

    def branches(name: str) -> Listing[Branch]:
        conn.calls.append(("branches", None))
        return held.pop(0) if len(held) > 1 else held[0]

    conn.branches = branches  # type: ignore[method-assign]


def done(conn: FakeSource, *, branch: str | None = None) -> Result:
    return read(conn, branch=branch, scope=SCOPE, document=DOCUMENT)


def rules(result: Result) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in result.findings]


def errors(result: Result) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in result.findings if finding.severity == "error"]


def called(conn: FakeSource) -> list[str]:
    return [name for name, _ in conn.calls]


def but_observed(doc: dict[str, Any]) -> dict[str, Any]:
    held: dict[str, Any] = json.loads(json.dumps(doc))
    del held["source"]["observed_at"]
    return held


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
    for branch in (None, "b"):
        conn = branched(three_node())
        result = read(conn, branch=branch, scope=scope, document=DOCUMENT)
        assert rules(result) == [("scope.invalid", scope)]
        assert result.blueprint is None and result.empty is False
        assert conn.calls == []
        assert ("branch b" if branch else "main") in result.findings[0].message


def test_a_branch_of_a_netbox_with_no_plugin_sends_nothing() -> None:
    conn = branched(three_node())
    conn.branching = None
    result = done(conn, branch="b")
    assert rules(result) == [("branch.unsupported", "b")]
    assert "branch b" in result.findings[0].message and "netbox_branching" in result.findings[0].message
    assert result.blueprint is None
    assert conn.calls == []

    conn = three_node()
    conn.branching = None
    assert done(conn).blueprint is not None


def test_a_branch_netbox_lacks_ends_the_read() -> None:
    conn = three_node()
    result = done(conn, branch="b")
    assert rules(result) == [("branch.unknown", "b")]
    assert "branch b" in result.findings[0].message
    assert result.blueprint is None
    assert conn.calls == [("branches", None)]


def test_a_branch_not_ready_ends_the_read() -> None:
    conn = branched(three_node(), replace(BRANCH, status="provisioning"))
    result = done(conn, branch="b")
    assert rules(result) == [("branch.unready", "b")]
    assert "provisioning" in result.findings[0].message and "branch b" in result.findings[0].message
    assert result.blueprint is None
    assert conn.calls == [("branches", None)]
    assert "latest" not in called(conn)


def test_a_branch_list_that_is_not_whole_ends_the_read() -> None:
    conn = three_node()
    conn.held_branches = listing("netbox_branching.branch", [BRANCH], count=2)
    result = done(conn, branch="b")
    assert rules(result) == [("read.incomplete", "netbox_branching.branch")]
    assert "branch b" in result.findings[0].message and "main" not in result.findings[0].message
    assert conn.calls == [("branches", None)]
    found = check(conn, branch="b")
    assert [(f.rule, f.object) for f in found] == [("read.incomplete", "netbox_branching.branch")]


def test_main_is_read_with_no_branch() -> None:
    conn = three_node()
    result = done(conn)
    assert result.blueprint is not None
    assert "branches" not in called(conn)
    assert {branch for _, branch in conn.calls} == {None}
    assert result.blueprint["source"]["branch"] is None


def test_a_branch_is_read_under_its_row() -> None:
    conn = branched(three_node())
    conn.latests = [7]
    conn.counts = [5]
    result = done(conn, branch="b")
    assert result.blueprint is not None
    assert result.blueprint["source"]["branch"] == "b"
    assert conn.calls[0] == ("branches", None)
    assert [call for call in conn.calls[1:] if call[0] != "branches"] == [
        (name, "b") for name in called(conn)[1:] if name != "branches"
    ]
    assert [call for call in conn.calls if call[0] == "branches"] == [("branches", None)] * 2


def test_a_scope_selecting_nothing_is_empty() -> None:
    conn = three_node()
    conn.held_tags = listing("extras.tag", [])
    result = done(conn)
    assert (result.blueprint, rules(result), result.empty) == (None, [("scope.empty", SCOPE)], True)
    assert "main" in result.findings[0].message
    assert "devices" not in called(conn)

    conn = three_node()
    conn.held_devices = listing("dcim.device", [])
    result = done(conn)
    assert (result.blueprint, rules(result), result.empty) == (None, [("scope.empty", SCOPE)], True)
    assert "render" not in called(conn) and "platforms" not in called(conn)


def short(what: str) -> FakeSource:
    """`three_node`'s rows with the list `what` answered one short of its count."""
    conn = three_node()
    held = {
        "dcim.device": "held_devices",
        "dcim.platform": "held_platforms",
        "dcim.interface": "held_ports",
        "dcim.cable": "held_cables",
        "extras.tag": "held_tags",
    }[what]
    listed = getattr(conn, held)
    setattr(conn, held, replace(listed, count=listed.count + 1))
    return conn


@pytest.mark.parametrize("what", ["extras.tag", "dcim.device", "dcim.platform", "dcim.interface", "dcim.cable"])
def test_a_list_that_is_not_whole_ends_the_read(what: str) -> None:
    conn = short(what)
    result = done(conn)
    assert rules(result) == [("read.incomplete", what)]
    assert result.blueprint is None and result.empty is False
    assert "render" not in called(conn)
    assert called(conn)[-1] == "latest", "the close was not taken"


def test_an_id_asked_for_and_not_answered_ends_the_read() -> None:
    """The platforms and the cables are held to the ids asked: `mapping.build` is never given a device whose platform
    is not among the platforms read."""
    conn = three_node()
    devices = list(conn.held_devices.items)
    devices[1] = replace(devices[1], platform=2)
    conn.held_devices = listing("dcim.device", devices)
    result = done(conn)
    assert rules(result) == [("read.incomplete", "dcim.platform")]
    assert "id 2" in result.findings[0].message
    assert "ports" not in called(conn) and "render" not in called(conn)

    conn = three_node()
    ports = list(conn.held_ports.items)
    ports[0] = replace(ports[0], cable=9)
    conn.held_ports = listing("dcim.interface", ports)
    result = done(conn)
    assert rules(result) == [("read.incomplete", "dcim.cable")]
    assert "render" not in called(conn)


def test_a_scoped_device_with_no_interface_is_no_fault() -> None:
    conn = three_node()
    conn.held_devices = listing("dcim.device", [*conn.held_devices.items, Device(4, "n4", PLATFORM.id)])
    conn.renders[4] = Rendered(200, b"set / system name host-name n4\n", TEXT)
    result = done(conn)
    assert result.findings == ()
    assert result.blueprint is not None
    n4 = [device for device in result.blueprint["network"]["devices"] if device["name"] == "n4"]
    config = "set / system name host-name n4\n"
    assert n4 == [{"name": "n4", "platform": "nokia_srlinux", "interfaces": [], "config": config}]


def test_the_bracket_opens_before_the_first_list_and_closes_after_the_last_render() -> None:
    conn = branched(three_node())
    conn.latests = [7]
    conn.counts = [5]
    assert done(conn, branch="b").blueprint is not None
    names = called(conn)
    assert names[:3] == ["branches", "latest", "counted"]
    assert names[3:8] == ["tags", "devices", "platforms", "ports", "cables"]
    assert names[8:11] == ["render"] * 3
    assert names[11:] == ["branches", "latest", "counted"]


def test_an_edit_during_a_read_is_moved() -> None:
    conn = three_node()
    conn.latests = [7, 9]
    conn.counts = [5]
    conn.changed = (Change(8, "dcim.interface"),)
    result = done(conn)
    assert rules(result) == [("read.moved", "main")]
    assert result.blueprint is None
    for said in ("7", "9", "read again"):
        assert said in result.findings[0].message


def test_rows_no_read_reads_do_not_refuse_it() -> None:
    conn = three_node()
    conn.latests = [7, 9]
    conn.counts = [5]
    conn.changed = (Change(8, "extras.journalentry"), Change(9, "netbox_branching.branch"))
    result = done(conn)
    assert result.findings == ()
    assert result.blueprint is not None
    assert result.blueprint["source"]["changelog"] == 9


def test_the_close_is_taken_on_every_path() -> None:
    for conn, refused in ((three_node(), "scope.empty"), (short("dcim.interface"), "read.incomplete")):
        if refused == "scope.empty":
            conn.held_devices = listing("dcim.device", [])
        conn.latests = [7, 9]
        conn.counts = [5]
        conn.changed = (Change(8, "dcim.device"), Change(9, "dcim.device"))
        result = done(conn)
        assert sorted(rule for rule, _ in rules(result)) == sorted([refused, "read.moved"])
        assert result.blueprint is None
        assert result.empty is (refused == "scope.empty")


def invalid(what: str) -> NetBoxError:
    """What the transport raises where NetBox answers 400 to a request by an id it does not hold."""
    return NetBoxError(f"reading {what} (main): HTTP 400: Select a valid choice. 2 is not one of the choices.", 400)


@pytest.mark.parametrize(("call", "what"), [("devices", "dcim.device"), ("ports", "dcim.interface")])
def test_a_400_for_an_id_the_read_listed_is_moved_where_the_changelog_moved(call: str, what: str) -> None:
    """NetBox answers 400 to an id it does not hold, so an object deleted between the read's own list and a request by
    its id shows so: the read closes the bracket, and where the changelog moved the finding is `read.moved`."""
    conn = three_node()
    conn.raising = {call: invalid(what)}
    conn.latests = [7, 9]
    conn.counts = [5]
    conn.changed = (Change(8, "dcim.device"), Change(9, "dcim.device"))
    result = done(conn)
    assert rules(result) == [("read.moved", "main")]
    assert result.blueprint is None
    assert "render" not in called(conn)


def test_a_400_where_the_changelog_did_not_move_is_the_transports_error() -> None:
    conn = three_node()
    refused = invalid("dcim.interface")
    conn.raising = {"ports": refused}
    conn.latests = [7]
    conn.counts = [5]
    with pytest.raises(NetBoxError) as raised:
        done(conn)
    assert raised.value is refused
    assert called(conn)[-2:] == ["latest", "counted"], "the close was not taken"


def test_a_400_whose_close_finds_the_changelog_not_whole_is_incomplete() -> None:
    """A changelog listed short of its count may lack the very row that moved: the read is refused by
    `read.incomplete`, which says to read again, and not by the transport's error."""
    conn = three_node()
    conn.raising = {"ports": invalid("dcim.interface")}
    conn.latests = [7, 9]
    conn.counts = [5]
    conn.changed = (Change(9, "extras.journalentry"),)
    conn.changed_count = 2
    result = done(conn)
    assert rules(result) == [("read.incomplete", "core.objectchange")]
    assert "Select a valid choice. 2 is not one of the choices." in result.findings[0].message
    assert "HTTP 400" in result.findings[0].message


def test_a_branch_gone_at_the_open_is_moved() -> None:
    """A branch deleted between its read and the open answers the open 400: the branch is read again, and gone it is
    `read.moved`; still as it was, the transport's error stands. `main` has no branch to read again."""
    invalid_branch = NetBoxError("reading core.objectchange (branch b): HTTP 400: Invalid branch identifier", 400)
    conn = branched(three_node())
    conn.raising = {"latest": invalid_branch}
    in_turn(conn, conn.held_branches, listing("netbox_branching.branch", []))
    result = done(conn, branch="b")
    assert rules(result) == [("read.moved", "b")]
    assert result.blueprint is None
    assert called(conn) == ["branches", "latest", "branches"]

    conn = branched(three_node())
    conn.raising = {"latest": invalid_branch}
    with pytest.raises(NetBoxError) as raised:
        done(conn, branch="b")
    assert raised.value is invalid_branch
    assert called(conn) == ["branches", "latest", "branches"]

    conn = three_node()
    refused = NetBoxError("reading core.objectchange (main): HTTP 400: x", 400)
    conn.raising = {"latest": refused}
    with pytest.raises(NetBoxError) as raised:
        done(conn)
    assert raised.value is refused
    assert called(conn) == ["latest"]


GONE = Rendered(400, b"Invalid branch identifier", "text/html; charset=utf-8")
"""What NetBox answers a render under the header of a branch that was deleted (design/verified-facts.md, "A render
under the header of a branch that is gone")."""


def test_a_render_refused_400_where_the_changelog_moved_is_moved() -> None:
    """A 400 that is not NetBox's no-template answer is the read's 400, weighed against its bracket: moved, it is
    `read.moved`, and the render files nothing of its own."""
    conn = three_node()
    conn.renders[1] = GONE
    conn.latests = [7, 9]
    conn.counts = [5]
    conn.changed = (Change(8, "dcim.device"), Change(9, "dcim.device"))
    result = done(conn)
    assert rules(result) == [("read.moved", "main")]
    assert conn.rendered == [1, 2, 3]


def test_a_render_refused_400_where_the_changelog_did_not_move_is_unavailable() -> None:
    conn = three_node()
    conn.renders[1] = GONE
    conn.latests = [7]
    conn.counts = [5]
    result = done(conn)
    assert rules(result) == [("render.unavailable", "n1")]
    assert "Invalid branch identifier" in result.findings[0].message
    assert result.blueprint is None


def test_a_missing_template_stands_beside_a_moved_changelog() -> None:
    conn = three_node()
    conn.renders[1] = Rendered(400, NO_TEMPLATE, TEXT)
    conn.latests = [7, 9]
    conn.counts = [5]
    conn.changed = (Change(8, "dcim.device"), Change(9, "dcim.device"))
    result = done(conn)
    assert sorted(rules(result)) == [("read.moved", "main"), ("render.template.missing", "n1")]


def test_the_findings_are_in_one_order_whatever_the_rows_order() -> None:
    def faulted(reverse: bool) -> FakeSource:
        conn = three_node()
        devices = [replace(d, name=d.name.upper()) if d.name else d for d in conn.held_devices.items]
        devices[1] = replace(devices[1], platform=None)
        ports = list(conn.held_ports.items)
        far = Cable(9, "far", (End("dcim.interface", 99, "x"),), (End("dcim.interface", 1, "mgmt0"),))
        cables = [*conn.held_cables.items, far]
        ports[0] = replace(ports[0], cable=9)
        if reverse:
            devices.reverse()
            ports.reverse()
            cables = [Cable(c.id, c.label, c.b, c.a) for c in reversed(cables)]
        conn.held_devices = listing("dcim.device", devices)
        conn.held_ports = listing("dcim.interface", ports)
        conn.held_cables = listing("dcim.cable", cables)
        conn.renders[1] = Rendered(500, FAILED, TEXT)
        conn.renders[3] = Rendered(200, b"", TEXT)
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


def test_a_branch_gone_under_the_read_is_moved() -> None:
    """Under the header of a branch NetBox no longer holds, every request is 400 `Invalid branch identifier`: the close
    finds the branch gone."""
    conn = branched(three_node())
    conn.raising = {"tags": NetBoxError("reading extras.tag (branch b): HTTP 400: Invalid branch identifier", 400)}
    conn.latests = [7]
    conn.counts = [5]
    in_turn(conn, conn.held_branches, listing("netbox_branching.branch", []))
    result = done(conn, branch="b")
    assert rules(result) == [("read.moved", "b")]
    assert "no branch b" in result.findings[0].message


def test_a_branch_list_not_whole_after_a_400_at_the_open_is_incomplete() -> None:
    """The branch read again after a 400 at the open is held to its `count`: a list short of it is `read.incomplete`,
    carrying the 400's words, since whether the branch moved cannot be told."""
    invalid_branch = NetBoxError("reading core.objectchange (branch b): HTTP 400: Invalid branch identifier", 400)
    conn = branched(three_node())
    conn.raising = {"latest": invalid_branch}
    in_turn(conn, conn.held_branches, listing("netbox_branching.branch", [BRANCH], count=2))
    result = done(conn, branch="b")
    assert rules(result) == [("read.incomplete", "netbox_branching.branch")]
    assert "Invalid branch identifier" in result.findings[0].message
    assert result.blueprint is None


def test_a_400_to_the_closes_own_requests_under_a_branch_is_moved() -> None:
    """A sync, a merge or a delete that begins once the close has read the branch again answers its later requests
    under the branch's header 400: the read is refused by `read.moved`, quoting NetBox's words, and raises nothing. On
    `main` the 400 is raised as it came."""
    refused = NetBoxError("reading core.objectchange (branch b): HTTP 400: Selected branch is not ready.", 400)
    conn = branched(three_node())
    conn.latests = [7, 9]
    conn.counts = [5]
    conn.raising = {"changes": refused}
    result = done(conn, branch="b")
    assert rules(result) == [("read.moved", "b")]
    assert "Selected branch is not ready" in result.findings[0].message
    assert result.blueprint is None

    on_main = NetBoxError("reading core.objectchange (main): HTTP 400: x", 400)
    conn = three_node()
    conn.latests = [7, 9]
    conn.counts = [5]
    conn.raising = {"changes": on_main}
    with pytest.raises(NetBoxError) as raised:
        done(conn)
    assert raised.value is on_main


def test_an_empty_branch_name_is_refused_before_any_request() -> None:
    """An empty name names no branch, and `main` is None: `read` and `check` refuse it, a `ValueError`, with nothing
    sent."""
    conn = branched(three_node())
    with pytest.raises(ValueError, match="branch"):
        done(conn, branch="")
    with pytest.raises(ValueError, match="branch"):
        check(conn, branch="")
    assert conn.calls == []


@pytest.mark.parametrize("name", [" ", "\t", " \n "])
def test_a_branch_name_of_whitespace_alone_is_refused_before_any_request(name: str) -> None:
    """A name of whitespace alone names no branch, as an empty one does: `read` and `check` refuse it, a `ValueError`,
    with nothing sent."""
    conn = branched(three_node())
    with pytest.raises(ValueError, match="branch"):
        done(conn, branch=name)
    with pytest.raises(ValueError, match="branch"):
        check(conn, branch=name)
    assert conn.calls == []


def test_another_refusal_passes_through_with_no_close() -> None:
    conn = three_node()
    refused = NetBoxError("reading dcim.interface (main): HTTP 500: Server Error", 500)
    conn.raising = {"ports": refused}
    with pytest.raises(NetBoxError) as raised:
        done(conn)
    assert raised.value is refused
    assert called(conn).count("latest") == 1


def test_one_device_of_three_failing_is_named_alone() -> None:
    conn = three_node()
    conn.held_devices = listing("dcim.device", list(reversed(conn.held_devices.items)))
    conn.renders[2] = Rendered(500, FAILED, TEXT)
    result = done(conn)
    assert errors(result) == [("render.failed", "n2")]
    assert result.blueprint is None
    assert conn.rendered == [1, 2, 3]
    lines = {line for name in ("n1", "n3") for line in CONFIGS[name].splitlines() if line.strip()}
    assert lines
    for finding in result.findings:
        assert [line for line in lines if line in finding.message] == []


def test_the_renders_are_in_name_order_then_id() -> None:
    conn = three_node()
    devices = [Device(5, "n2", 1), Device(4, "n2", 1), Device(3, "a", 1), Device(9, None, 1), Device(8, None, 1)]
    conn.held_devices = listing("dcim.device", devices)
    conn.held_ports = listing("dcim.interface", [])
    conn.held_cables = listing("dcim.cable", [])
    conn.renders = {device.id: Rendered(200, b"x\n", TEXT) for device in devices}
    done(conn)
    assert conn.rendered == [3, 4, 5, 8, 9]


def test_every_device_at_fault_is_filed_in_one_pass() -> None:
    conn = three_node()
    conn.renders[1] = Rendered(400, NO_TEMPLATE, TEXT)
    conn.renders[2] = Rendered(500, FAILED, TEXT)
    conn.renders[3] = Rendered(200, b"", TEXT)
    result = done(conn)
    assert sorted(errors(result)) == [
        ("render.empty", "n3"),
        ("render.failed", "n2"),
        ("render.template.missing", "n1"),
    ]
    assert result.blueprint is None


def test_a_device_the_mapping_refused_is_rendered_too() -> None:
    conn = three_node()
    devices = list(conn.held_devices.items)
    devices[1] = replace(devices[1], platform=None)
    conn.held_devices = listing("dcim.device", devices)
    conn.renders[2] = Rendered(500, FAILED, TEXT)
    result = done(conn)
    assert sorted(errors(result)) == [("platform.missing", "n2"), ("render.failed", "n2")]
    assert conn.rendered == [1, 2, 3]
    assert result.blueprint is None


def test_the_envelope_holds_its_seven_members_and_none_is_hashed() -> None:
    conn = three_node()
    conn.latests = [3]
    result = done(conn)
    assert result.blueprint is not None
    source = result.blueprint["source"]
    assert list(source) == ["source", "branch", "scope", "mapping", "changelog", "observed_at", "fidelity"]
    assert source["source"] == "netbox"
    assert (source["branch"], source["scope"], source["changelog"]) == (None, SCOPE, 3)
    assert OBSERVED.match(source["observed_at"])
    assert source["mapping"] == {"reader": "netbox-dcim", "model": "netbox", "version": "4.7.5"}
    assert source["fidelity"] == [
        {
            "disposition": "omitted",
            "object": "platform.version",
            "source": "dcim.platform",
            "reason": "NetBox's platform carries no version",
        }
    ]
    assert list(result.blueprint) == ["blueprint_version", "network", "probes", "source"]
    assert result.blueprint["blueprint_version"] == "1"

    other = branched(three_node())
    other.latests = [11]
    on_branch = done(other, branch="b")
    assert on_branch.blueprint is not None
    assert (on_branch.blueprint["source"]["branch"], on_branch.blueprint["source"]["changelog"]) == ("b", 11)
    assert blueprint.blueprint_id(on_branch.blueprint) == blueprint.blueprint_id(result.blueprint)


def test_the_same_rows_read_twice_give_one_document_but_for_observed_at() -> None:
    first, second = done(three_node()), done(three_node())
    assert first.blueprint is not None and second.blueprint is not None
    assert but_observed(first.blueprint) == but_observed(second.blueprint)
    assert blueprint.blueprint_id(first.blueprint) == blueprint.blueprint_id(second.blueprint) == FIXTURE_ID


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
    conn.renders[3] = Rendered(200, b"\t\n", TEXT)
    refused = done(conn)
    assert errors(refused) == [("render.empty", "n3")]
    assert refused.blueprint is None


def test_a_problem_of_the_blueprint_built_is_an_error() -> None:
    """`read` holds what it built to blueprint 1 and files each problem under the problem's own rule, its pointer the
    object: a name of NetBox's that UTF-8 cannot encode has no id."""
    conn = three_node()
    ports = list(conn.held_ports.items)
    ports[4] = replace(ports[4], name="ethernet-\ud800")
    conn.held_ports = listing("dcim.interface", ports)
    result = done(conn)
    assert result.blueprint is None
    held = [finding for finding in result.findings if finding.rule == "blueprint.unencodable"]
    assert [finding.severity for finding in held] == ["error"]
    assert (held[0].object or "").startswith("/network/devices/0/interfaces/")
    assert "main" in held[0].message


def test_the_version_warning_rides_on_every_result() -> None:
    conn = three_node()
    conn.unverified = UNVERIFIED
    result = done(conn)
    assert result.blueprint is not None
    assert result.findings == (UNVERIFIED,)

    refused = read(conn, branch=None, scope="site:x", document=DOCUMENT)
    assert UNVERIFIED in refused.findings and refused.blueprint is None

    assert check(conn, branch=None) == (UNVERIFIED,)


def test_check_judges_the_branch_alone() -> None:
    conn = three_node()
    assert check(conn, branch=None) == ()
    assert conn.calls == []

    conn = branched(three_node())
    conn.branching = None
    assert [f.rule for f in check(conn, branch="b")] == ["branch.unsupported"]
    assert conn.calls == []

    conn = three_node()
    assert [(f.rule, f.object) for f in check(conn, branch="b")] == [("branch.unknown", "b")]

    conn = branched(three_node(), replace(BRANCH, status="syncing"))
    found = check(conn, branch="b")
    assert [f.rule for f in found] == ["branch.unready"] and "syncing" in found[0].message

    conn = branched(three_node())
    assert check(conn, branch="b") == ()
    assert conn.calls == [("branches", None)]

    conn = branched(three_node())
    conn.unverified = UNVERIFIED
    conn.branching = None
    assert [f.rule for f in check(conn, branch="b")] == ["branch.unsupported", "netbox.version.unverified"]



def test_two_tags_of_the_scopes_name_are_refused() -> None:
    """NetBox's source holds a tag's name unique, read and not run, and the read does not rely on it: a name that
    answers two rows is NetBox's error, raised before the devices of either are asked."""
    conn = three_node()
    conn.held_tags = listing("extras.tag", [TAG, replace(TAG, id=2)])
    with pytest.raises(NetBoxError) as raised:
        done(conn)
    assert raised.value.status == 200
    for said in ("extras.tag", "main", "2 rows", "fylgja"):
        assert said in str(raised.value)
    assert "devices" not in called(conn)


def test_two_branches_of_the_name_are_refused() -> None:
    """The branch's name, the same: two rows of it are NetBox's error, raised before the bracket opens, by `read` and
    by `check` alike."""
    conn = branched(three_node())
    conn.held_branches = listing("netbox_branching.branch", [BRANCH, replace(BRANCH, id=8, schema_id="q8e57z8a")])
    with pytest.raises(NetBoxError) as raised:
        done(conn, branch="b")
    assert raised.value.status == 200
    for said in ("netbox_branching.branch", "branch b", "2 rows"):
        assert said in str(raised.value)
    assert called(conn) == ["branches"]
    with pytest.raises(NetBoxError):
        check(conn, branch="b")
