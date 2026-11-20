"""A Golden Config setting's devices are a dynamic group whose members are stored, recomputed when the group is saved
or by the job `RefreshDynamicGroupCaches`, and a device rendered under the setting its stored membership gives (D-118):
the group's filter, listed as devices, is held to its stored members for the scoped devices, and a difference is
`group.stale`; a group whose filter the reader cannot list is `group.unchecked`. Over `Group` values built in the
tests, never Nautobot's answers (D-034); the filters are of the forms design/verified-facts.md holds a save to store as
the device list answers them, "Nautobot 3.2.8 with Golden Config 3.0.8", "A group's stored members"."""

from __future__ import annotations

from typing import Any

import pytest
from fylgja_core.findings import Finding

from fylgja_nautobot import groups
from fylgja_nautobot.rows import Group

NAME = "GoldenConfigSetting Default Settings scope"
SCOPED = {"device-1": "n1", "device-2": "n2", "device-3": "n3"}
ALL = set(SCOPED)


def group(filter: Any = None, *, kind: str = "dynamic-filter") -> Group:
    return Group("group-1", NAME, kind, {"tags": ["fylgja"]} if filter is None else filter)


def stale(found: Finding | None) -> Finding:
    assert found is not None
    assert (found.rule, found.severity, found.object) == ("group.stale", "error", NAME)
    assert found.message.endswith(".")
    for said in ("save the group", "RefreshDynamicGroupCaches", "no changelog row", "read again"):
        assert said in found.message, said
    return found


def test_a_stored_membership_equal_to_the_filter_is_no_finding() -> None:
    assert groups.judge(group(), ALL, ALL, SCOPED) is None
    assert groups.judge(group(), set(), set(), SCOPED) is None
    assert groups.judge(group(), {"device-2"}, {"device-2"}, SCOPED) is None


def test_a_device_the_filter_lists_and_the_group_does_not_store_is_stale() -> None:
    found = stale(groups.judge(group(), {"device-1", "device-2"}, ALL, SCOPED))
    assert "n3" in found.message
    assert "n1" not in found.message and "n2" not in found.message
    assert "lists and the group does not store" in found.message
    assert groups.RULE_STALE == "group.stale"


def test_a_device_stored_that_the_filter_no_longer_lists_is_stale() -> None:
    found = stale(groups.judge(group(), ALL, {"device-1"}, SCOPED))
    assert "n2" in found.message and "n3" in found.message
    assert "stored and the filter no longer lists" in found.message

    both = stale(groups.judge(group(), {"device-1", "device-2"}, {"device-2", "device-3"}, SCOPED))
    assert "n1" in both.message and "n3" in both.message


def test_a_device_outside_the_scope_is_not_judged() -> None:
    assert groups.judge(group(), {*ALL, "device-9"}, ALL, SCOPED) is None
    assert groups.judge(group(), ALL, {*ALL, "device-9"}, SCOPED) is None
    found = stale(groups.judge(group(), {"device-9"}, {"device-1", "device-8"}, SCOPED))
    assert "device-9" not in found.message and "device-8" not in found.message


def test_many_stale_devices_are_named_up_to_a_bound() -> None:
    scoped = {f"device-{i}": f"n{i:02d}" for i in range(1, 21)}
    found = stale(groups.judge(group(), set(), set(scoped), scoped))
    assert "20 scoped devices" in found.message
    assert [f"n{i:02d}" in found.message for i in range(1, 21)] == [i <= groups.NAMED for i in range(1, 21)]
    assert f"and {20 - groups.NAMED} more" in found.message


@pytest.mark.parametrize(
    ("unsendable", "said"),
    [
        (group({"name": [["n1"]]}), "filter"),
        (group({"name": {"x": "n1"}}), "filter"),
        (group({"name": [None]}), "filter"),
        (group({"name": None}), "filter"),
        (group({"id": ["device-1"]}), "filter"),
        (group(["tags", "fylgja"]), "filter"),
        (group({}, kind="dynamic-set"), "dynamic-set"),
        (group({}, kind="static"), "static"),
    ],
    ids=["a list in a list", "an object", "a null in a list", "a null", "the key id", "no object", "a set", "static"],
)
def test_a_filter_the_reader_cannot_send_is_unchecked(unsendable: Group, said: str) -> None:
    found = groups.judge(unsendable, set(), ALL, SCOPED)
    assert found is not None
    assert (found.rule, found.severity, found.object) == ("group.unchecked", "warning", NAME)
    assert said in found.message and found.message.endswith(".")
    assert groups.RULE_UNCHECKED == "group.unchecked"


def test_params_of_each_kind() -> None:
    """Each key's value as the device list reads it: a list sent once a member, text as it stands, a number as
    Python writes it, a boolean as `true` or `false`, an empty list as nothing; None for a group of another
    `group_type`, for any other value, and for the key `id`, which the reader restricts the list by."""
    assert groups.params(group()) == [("tags", "fylgja")]
    assert groups.params(group({"name": ["n1", "n2"], "location": ["lab"]})) == [
        ("name", "n1"),
        ("name", "n2"),
        ("location", "lab"),
    ]
    assert groups.params(group({"name": "n2"})) == [("name", "n2")]
    assert groups.params(group({"has_interfaces": True, "has_primary_ip": False})) == [
        ("has_interfaces", "true"),
        ("has_primary_ip", "false"),
    ]
    numbers = group({"vc_position": [1], "vc_priority": 2.5})
    assert groups.params(numbers) == [("vc_position", "1"), ("vc_priority", "2.5")]
    assert groups.params(group({"name": []})) == []
    assert groups.params(group({})) == []
    lookups = group({"name__ic": ["N1"], "id__n": ["device-1"]})
    assert groups.params(lookups) == [("name__ic", "N1"), ("id__n", "device-1")]
    for value in ([["n1"]], {"x": "n1"}, [None], None, [True, {"x": 1}]):
        assert groups.params(group({"name": value})) is None, value
    assert groups.params(group({"id": ["device-1"]})) is None
    assert groups.params(group(["tags"])) is None
    assert groups.params(group({"tags": ["fylgja"]}, kind="dynamic-set")) is None
