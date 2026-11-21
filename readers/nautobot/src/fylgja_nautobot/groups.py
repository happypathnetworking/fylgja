"""A Golden Config setting's dynamic group: its stored members held to its filter, for the scoped devices (D-118).

A setting applies to the devices of its dynamic group, and the group's members are stored: they are recomputed when the
group is saved, or by the job `RefreshDynamicGroupCaches`, and at no other time. Golden Config renders a device under
the setting its stored membership gives, with no error, so a device tagged or edited since the group's last refresh
renders under another setting than its filter now gives, or under none (`render.setting.absent`). The reading behind
this module (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8", "A group's stored members") showed
that a group's stored members are listed whole, with a count, and restricted to the devices asked; and that the device
list, asked with a `dynamic-filter` group's filter as its query, answered what a save of the filter stored, for each
filter read: a tag, a name of two values, a related object's name, two keys together, booleans, a number, text where a
list was, an empty list, no key, and a lookup and its negation.

So the read lists, for each group of the settings the open listed, its stored members and what its filter lists, each
restricted to the scoped devices, and `judge` holds the two to each other: a scoped device in one and not the other is
`group.stale`, an error naming the group. The remedy is to refresh the group, which writes no changelog row, so the
bracket does not see it, and the read is refused until it is made. A group of another `group_type` than
`dynamic-filter`, whose members are not its filter's, or whose filter `params` cannot send as a query, is
`group.unchecked`, a warning naming it: the read goes on, and a stale membership of it is not seen.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from fylgja_core.findings import Finding

from fylgja_nautobot.rows import Group

# Rule ids. Callers and tests match on them (rules.md).
RULE_STALE = "group.stale"
RULE_UNCHECKED = "group.unchecked"

FILTERED = "dynamic-filter"
"""The one `group_type` whose members are its filter's: a `dynamic-set` combines other groups, and a `static` group's
members are its own."""

RESTRICTED = "id"
"""The key the reader restricts the device list by, to the scoped devices: a filter holding it cannot be sent beside
the restriction, since Nautobot answers the devices of any of the values a key is given."""

NAMED = 5
"""How many devices a `group.stale` names of each kind, by name; the rest are counted."""

REFRESH = (
    "save the group, or run the job RefreshDynamicGroupCaches, a refresh that writes no changelog row, so the "
    "reader's bracket does not see it, then read again"
)
"""The remedy every `group.stale` ends in."""


def params(group: Group) -> list[tuple[str, str]] | None:
    """`group`'s filter as the device list's query: each key's value, a list sent once a member, in the filter's
    order; text as it stands, a number as Python writes it, a boolean `true` or `false`, as the device list read each
    (design/verified-facts.md), and an empty list nothing. None where the group's `group_type` is not `dynamic-filter`,
    its filter is no JSON object, a key is `id` (`RESTRICTED`), or a value is any other: null, an object, or a list
    holding one or a list."""
    if group.kind != FILTERED or not isinstance(group.filter, dict):
        return None
    sent: list[tuple[str, str]] = []
    for key, value in group.filter.items():
        if key == RESTRICTED:
            return None
        for member in value if isinstance(value, list) else [value]:
            text = _sent(member)
            if text is None:
                return None
            sent.append((key, text))
    return sent


def _sent(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    return None


def judge(
    group: Group, stored: Collection[str], matching: Collection[str], scoped: Mapping[str, str]
) -> Finding | None:
    """`group.unchecked` where `group`'s `group_type` is not `dynamic-filter`, or `params` cannot send its filter;
    else `group.stale` where a device of `scoped`, by its id, is in one of `stored`, the ids of the group's stored
    members, and `matching`, the ids of the devices its filter lists, and not in the other; None where the two agree
    on every scoped device. `scoped` gives each scoped device's name as findings name it; a device outside it is not
    judged."""
    if group.kind != FILTERED:
        said = (
            f"Dynamic group {group.name} is of group_type {group.kind}, not {FILTERED}, so its members are not its "
            "filter's, and the reader does not hold its stored members to anything: a membership stale since its "
            "last refresh is not seen."
        )
        return Finding(rule=RULE_UNCHECKED, severity="warning", object=group.name, message=said)
    if params(group) is None:
        said = (
            f"The filter of dynamic group {group.name} is no JSON object, or holds what the reader cannot send as the "
            f"device list's query, a null, an object, a list within a list or the key {RESTRICTED}, so the reader does "
            "not hold the group's stored members to it: a membership stale since its last refresh is not seen."
        )
        return Finding(rule=RULE_UNCHECKED, severity="warning", object=group.name, message=said)
    held, listed = set(stored) & set(scoped), set(matching) & set(scoped)
    unstored, unlisted = listed - held, held - listed
    if not unstored and not unlisted:
        return None
    parts = []
    if unstored:
        parts.append(f"{_devices(unstored, scoped)} its filter lists and the group does not store")
    if unlisted:
        parts.append(f"{_devices(unlisted, scoped)} stored and the filter no longer lists")
    said = (
        f"The stored members of dynamic group {group.name} are not what its filter lists now, {' and '.join(parts)}, "
        "so Golden Config renders each under the setting its stored membership gives, or under none: refresh the "
        f"group's stored members, {REFRESH}."
    )
    return Finding(rule=RULE_STALE, severity="error", object=group.name, message=said)


def _devices(ids: set[str], scoped: Mapping[str, str]) -> str:
    """`ids` as a message names them: their number and the first `NAMED` by name, in name order then id."""
    names = [scoped[id] for id in sorted(ids, key=lambda id: (scoped[id], id))]
    shown = ", ".join(names[:NAMED])
    more = f", and {len(names) - NAMED} more" if len(names) > NAMED else ""
    kind = "scoped device" if len(names) == 1 else "scoped devices"
    return f"{len(names)} {kind} ({shown}{more})"
