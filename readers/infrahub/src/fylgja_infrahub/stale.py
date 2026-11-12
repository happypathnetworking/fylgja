"""A configuration older than its intent is refused, by device, and the head's arithmetic (D-082).

Infrahub regenerates an artifact only when asked, so a read after an edit meets the configuration rendered before it
until someone asks; `artifact.stale` refuses that read. The rule is the prototype's, restated on what plan 2 read of
Infrahub 1.11.11 (design/verified-facts.md, "Infrahub 1.11.11", "What a stale rule can be built on").

The intent a device's configuration renders from is spread over the device, its platform, its manufacturer, each of
its interfaces of either kind, each address on an interface, and each cable one of its ports ends, and a stamp is read
on every one of them: an address's edit moves its own stamp alone, and an address made moves its interface's. Of the
platform and the manufacturer, the configuration renders their names, so their `name` stamps are intent and their node
stamps are not, which a device made on the platform moves (P3-44); their own other writes count through their events.
Of a cable's far end, likewise, the configuration renders the far port's name and the far device's, so their `name`
stamps, and their events naming `name`, are intent, and nothing else of the far end is (P3-27): an address made on the
far port, or an event of another of the far device's ports, renders nothing here. A node's stamp is its edge's
`updated_at`, or its `created_at` where the task workers' account wrote it last: that account, the maker of the
internal query groups the scope's artifacts render through, restamps every node that joins a group at the generation
that reads it, after the checksum, which is no intent. `__system__` is never discounted, whatever made the groups: it
is the account Infrahub answers, by that id, on an operator's address create and edit. The branch's events are read
beside the stamps, because the discount loses an operator's write under the workers' restamp, and because a removal
can move a stamp back. An event names a device where its primary node is one of the device's nodes, or where its
related nodes name one of the device's own: the device, its interfaces, its addresses and its cables. A port's event
names its device there, an address's itself alone, and a cable's whose ends were taken off it the ports it had. The
platform and the manufacturer are every device's on them, and a device made on the platform names it among its related
nodes, so the two count through an event whose primary node they are alone (P3-25, P3-42).

A device's intent was written at the latest of its stamps and of the intent events naming it no later than the time
read; its configuration was generated at its artifact's checksum stamp, or at the `generated_since` given where that
is later. It is stale where the first is strictly later than the second. A stale configuration stays stale until
someone regenerates it, which is the message's remedy, or until the caller gives a `generated_since` a regeneration
is known for: a regeneration that stores the same bytes moves no checksum stamp.

A branch is made from `main` and holds what `main` held at its `branched_from`, a configuration gone stale there among
it, so the events a branch is judged by are its own log's and `main`'s up to its `branched_from`, read in one list
from the events' floor; a write on `main` after the branch was made is not the branch's, and a rebase is not read
(P3-45). `main` is judged by its own log alone.

`head`'s arithmetic counts every stamp and every event, nothing discounted: it is a time to read at, not a judgement,
and the workers' own restamp is a write a read must be pinned after.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from fylgja_core.findings import Finding

from fylgja_infrahub import times
from fylgja_infrahub.artifacts import RULE_UNREADY
from fylgja_infrahub.rows import RULE_INCOMPLETE, CableStamp, Event, Generated, Group, Schema, Stamp, Stamped

# Rule ids. Callers and tests match on them (rules.md).
RULE_STALE = "artifact.stale"

SYSTEM = "__system__"
"""The account Infrahub names on an operator's address create and edit, told by the id it answers for it, which is
`__system__` itself: `updated_by { id }` and `created_by { id }` read `__system__` there (design/verified-facts.md,
"Infrahub 1.11.11": "Which stamps each write moved", "An address on a virtual interface, read under
`InterfaceLayer3`"). A write by it is never discounted, whatever made the query groups (P3-29)."""

INTENT_NODES = ("DcimPlatform", "OrganizationManufacturer", "IpamIPAddress")
"""The kinds whose writes are intent's beside the implementers of `INTENT_GENERICS`."""

INTENT_GENERICS = ("DcimGenericDevice", "DcimInterface", "DcimConnector")
"""The generics each implementer of which, by the branch's `used_by`, is a kind whose writes are intent's: an
implementer of the operator's own counts."""

CHURN = frozenset({"member_of_groups", "subscriber_of_groups", "artifacts", "profiles", "object_template"})
"""Infrahub's own relationships on every node, a write to which alone is no intent: a query group's membership,
rewritten after each generation, and an artifact's."""

REVERSE = {"DcimPlatform": frozenset({"devices"}), "OrganizationManufacturer": frozenset({"platforms"})}
"""The relationships of a kind that list what points at it, which the mapping never renders, a write to which alone is
no intent: a device made or re-platformed elsewhere may name the platform, and a platform the manufacturer, and would
otherwise make every device on them stale (P3-31; not read)."""

CREATED = "infrahub.node.created"
DELETED = "infrahub.node.deleted"

NAME = "name"
"""The attribute of a cable's far port and far device that a configuration renders, and all of the far end the rule
counts (P3-27)."""

MAIN = "main"
"""The branch every other is made from, whose log up to a branch's `branched_from` is the branch's history (P3-45)."""


def logs(branch: str) -> tuple[str, ...]:
    """The logs `branch`'s events are read from: its own, and `main`'s beside for any other branch (P3-45)."""
    return (branch,) if branch == MAIN else (branch, MAIN)


def since(branch: str, branched_from: str, floor: str | None) -> str:
    """When `branch`'s events are read from: `main`'s at its `branched_from`; another branch's at `floor`, the earliest
    time an event can matter, where one is given, since `main`'s events before the branch was made are the branch's
    too, and at its `branched_from` where none is."""
    return floor if branch != MAIN and floor is not None else branched_from


def inherited(events: Sequence[Event], branch: str, branched_from: str) -> tuple[Event, ...]:
    """`events`, read from `logs(branch)`, as `branch`'s history: every one of its own log, and one of `main`'s where it
    occurred no later than `branched_from`, when the branch was made holding what `main` held then (P3-45); for `main`,
    every one."""
    if branch == MAIN:
        return tuple(events)
    point = times.parse(branched_from)
    return tuple(event for event in events if event.branch != MAIN or times.parse(event.occurred_at) <= point)


def intent(event: Event, schema: Schema) -> bool:
    """Whether `event` is a write to intent: a node's own write, on a node of `INTENT_NODES` or of an implementer of
    `INTENT_GENERICS` in `schema`, that created or deleted it, or names an attribute, or a relationship but `CHURN`
    and its kind's `REVERSE`. Whose account wrote it is `written`'s to judge."""
    return _intent(event, _kinds(schema))


def _intent(event: Event, kinds: Collection[str]) -> bool:
    """`intent`, over `kinds`, the branch's kinds whose writes are intent's (`_kinds`)."""
    if not event.mutated or event.primary is None or event.kind is None or event.kind not in kinds:
        return False
    if event.name in (CREATED, DELETED) or event.attributes:
        return True
    ignored = CHURN | REVERSE.get(event.kind, frozenset())
    return any(name not in ignored for name, _ in event.relationships)


def written(
    device: Stamped, cables: Sequence[CableStamp], events: Sequence[Event], own: frozenset[str], at: str
) -> tuple[str | None, Event | None]:
    """When `device`'s intent was last written, and the event that says so where an event is the latest: the latest of
    its own stamp, its interfaces', its addresses' and its cables' among `cables`, each as `counted` counts it under the
    workers' accounts `own`, of its platform's and manufacturer's `name` stamps, in place of their node stamps
    (P3-44), and of the `name` stamps of each of those cables' ends and their devices; and of `events` that none of
    `own` but `SYSTEM` wrote, that occurred no later than `at`, and whose primary node is one of the device's nodes or
    its cables, or whose related nodes name one of its own, its platform and manufacturer aside (P3-42), or whose
    primary node is a cable's end or its device and which names the attribute `name`. The far end counts for its names
    and nothing else of it (P3-27). `events` are intent's (`intent`). None where nothing is stamped and no event names
    it."""
    ours = [cable for cable in cables if cable.device == device.id]
    ids = {*device.ids, *(cable.id for cable in ours)}
    owned = {
        device.id,
        *(interface for interface, _ in device.interfaces.items),
        *(address for _, address, _ in device.addresses.items),
        *(cable.id for cable in ours),
    }
    ends = [end for cable in ours for end in cable.ends.items]
    far = {*(end.id for end in ends), *(end.device for end in ends if end.device is not None)}
    # The platform's and the manufacturer's node stamps (`shared`) are not counted: their names are (P3-44).
    stamps = [
        device.own,
        *(stamp for _, stamp in device.interfaces.items),
        *(stamp for _, _, stamp in device.addresses.items),
        *(cable.stamp for cable in ours),
    ]
    rendered = (device.platform_name_at, device.manufacturer_name_at)
    names = [time for time in (*rendered, *(t for end in ends for t in (end.name_at, end.device_name_at))) if time]
    counts = [time for time in (counted(stamp, own) for stamp in stamps) if time is not None]
    stamped_at = times.latest([*counts, *names])
    limit = times.parse(at)
    named = [
        event
        for event in events
        if not _discounted(event.account, own)
        and times.parse(event.occurred_at) <= limit
        and (
            event.primary in ids
            or any(node in owned for node in event.related)
            or (event.primary in far and NAME in event.attributes)
        )
    ]
    last = max(named, key=lambda event: times.parse(event.occurred_at), default=None)
    if last is not None and (stamped_at is None or times.later(last.occurred_at, stamped_at)):
        return last.occurred_at, last
    return stamped_at, None


def counted(stamp: Stamp, own: frozenset[str]) -> str | None:
    """A node's stamp as the rule counts it: its `updated_at`, or its `created_at` where one of the workers' accounts
    `own` wrote it last, `SYSTEM` never among them; None where that time is null."""
    return stamp.created_at if _discounted(stamp.updated_by, own) else stamp.updated_at


def judge(
    devices: Sequence[Stamped],
    cables: Sequence[CableStamp],
    groups: Sequence[Group],
    events: Sequence[Event],
    schema: Schema,
    selected: Mapping[str, str],
    *,
    branch: str,
    at: str,
    generated_since: str | None,
) -> tuple[Finding, ...]:
    """`artifact.stale` for each device of `devices` whose intent was written later than its configuration was
    generated, `selected` naming by a device's id the id of the artifact the read chose for it; `artifact.unready` for
    one whose artifact has no checksum stamp, whatever `generated_since` says; and `read.incomplete` for one whose
    artifact the stamps read did not list. A device not selected is not judged. The workers' accounts are the makers
    of `groups`; one finding a device, in name order."""
    own = frozenset(group.created_by for group in groups if group.created_by is not None)
    kinds = _kinds(schema)
    ours = [event for event in events if _intent(event, kinds)]
    found = []
    for device in sorted((d for d in devices if d.id in selected), key=lambda d: (d.name, d.id)):
        artifact = chosen(device, selected[device.id])
        if artifact is None:
            message = (
                f"Infrahub listed the artifact {selected[device.id]} of device {device.name} on branch {branch} at "
                f"{at}, and the stale rule's read of its artifacts did not, so that list is not whole."
            )
            cut = Finding(rule=RULE_INCOMPLETE, severity="error", object=f"{device.name}.artifacts", message=message)
            found.append(cut)
            continue
        checksum_at = artifact.checksum_at
        if checksum_at is None:
            message = (
                f"Device {device.name}'s artifact {artifact.definition} on branch {branch} at {at} has no checksum "
                "stamp, so when its configuration was generated is not known, whatever generated_since says; "
                "regenerate it in Infrahub, and read again once it is Ready."
            )
            found.append(Finding(rule=RULE_UNREADY, severity="error", object=device.name, message=message))
            continue
        since = generated_since if generated_since is not None and times.later(generated_since, checksum_at) else None
        when, event = written(device, cables, ours, own, at)
        if when is None or not times.later(when, since or checksum_at):
            continue
        by = f" (Infrahub's event log: {event.name} of the {event.kind} {event.primary})" if event is not None else ""
        generated = (
            f"at {since}, the generated_since given, its checksum stamped {checksum_at}"
            if since is not None
            else f"when its checksum was stamped, {checksum_at}"
        )
        message = (
            f"Device {device.name}'s intent on branch {branch} at {at} was written at {when}{by}, later than its "
            f"artifact {artifact.definition} was generated, {generated}, and Infrahub regenerates an artifact only "
            "when asked: regenerate it in Infrahub and read again, or read with a generated_since at which a "
            "regeneration is known to have completed, since one that stores the same bytes moves no checksum stamp."
        )
        found.append(Finding(rule=RULE_STALE, severity="error", object=device.name, message=message))
    return tuple(found)


def chosen(device: Stamped, artifact: str) -> Generated | None:
    """The device's artifact whose id is `artifact`, as the stamps read listed it; None where it listed none."""
    return next((generated for generated in device.artifacts.items if generated.id == artifact), None)


def floor(devices: Sequence[Stamped], selected: Mapping[str, str], generated_since: str | None) -> str | None:
    """The earliest time an event can make one of the devices `judge` judges stale: the later of the earliest checksum
    stamp among them and `generated_since`, where it is given, since each is judged from the later of its own checksum
    stamp and `generated_since` and is stale only where its intent was written strictly later (P3-50), so the branch's
    events are read down to it. None where none has a checksum stamp."""
    stamps = [
        artifact.checksum_at
        for device in devices
        if device.id in selected
        and (artifact := chosen(device, selected[device.id])) is not None
        and artifact.checksum_at is not None
    ]
    lowest = min(stamps, key=times.parse, default=None)
    if lowest is not None and generated_since is not None and times.later(generated_since, lowest):
        return generated_since
    return lowest


def latest(
    devices: Sequence[Stamped],
    cables: Sequence[CableStamp],
    events: Sequence[Event] = (),
    probes: Sequence[tuple[str, Stamp]] = (),
) -> str | None:
    """The latest time of every stamp of `devices` and `cables`, the platform's and manufacturer's node stamps, their
    names', each checksum's and each cable end's names' among them, of every event of `events` and of every probe's
    stamp of `probes`, nothing discounted, as Infrahub answered it; None where there is none."""
    stamps = [cable.stamp for cable in cables] + [stamp for _, stamp in probes]
    found = [event.occurred_at for event in events]
    found += [
        time
        for cable in cables
        for end in cable.ends.items
        for time in (end.name_at, end.device_name_at)
        if time is not None
    ]
    for device in devices:
        stamps += [device.own, *device.shared]
        stamps += [*(s for _, s in device.interfaces.items), *(s for _, _, s in device.addresses.items)]
        found += [generated.checksum_at for generated in device.artifacts.items if generated.checksum_at is not None]
        found += [time for time in (device.platform_name_at, device.manufacturer_name_at) if time is not None]
    found += [time for stamp in stamps for time in (stamp.updated_at, stamp.created_at) if time is not None]
    return times.latest(found)


def _discounted(account: str | None, own: frozenset[str]) -> bool:
    """Whether a write by `account` is the task workers' own: one of `own`, and never `SYSTEM`."""
    return account is not None and account != SYSTEM and account in own


def _kinds(schema: Schema) -> set[str]:
    """Every kind on the branch whose writes are intent's: `INTENT_NODES`, and each implementer of `INTENT_GENERICS`."""
    generics = [schema.generics[generic] for generic in INTENT_GENERICS if generic in schema.generics]
    return {*INTENT_NODES, *(user for generic in generics for user in generic.used_by)}
