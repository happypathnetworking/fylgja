"""The mapping, `netbox-dcim`: NetBox's devices, platforms, interfaces and cables, as rows, into blueprint 1's network
(D-095).

There is one mapping, and `readers/netbox/mapping.md` documents it member by member. A blueprint's id addresses its
network and probes alone (D-006), so the mapping sorts every list and orders each link's ends itself, and the same
rows in any order, a cable's sides swapped among them, map to one network. A device is named by its NetBox name made a
DNS-1123 label (D-038), and its platform package is the reader document's row of its platform's manufacturer and name;
a device that cannot be named or has no package is refused, an error, and left out of the network with every link it
ends, while a cable it ends is still judged for omission, so that every finding is filed in one pass (Constitution
III). An interface's `enabled` and `mgmt_only` are NetBox's own, so nothing
of them is approximated. A cable the mapping cannot make a link of is omitted, an info finding and a fidelity row:
blueprint 1 has nowhere to put it, and the rest of the network is whole without it. Every finding names the branch
read, or `main`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fylgja_core.findings import Finding, order

from fylgja_netbox.document import ReaderDocument
from fylgja_netbox.rows import Cable, Device, End, Platform, Port

# Rule ids. Callers and tests match on them (rules.md).
RULE_PLATFORM_MISSING = "platform.missing"
RULE_PLATFORM_UNMATCHED = "platform.unmatched"
RULE_RENAMED = "device.name.renamed"
RULE_UNMAPPABLE = "device.name.unmappable"
RULE_DUPLICATE = "device.name.duplicate"
RULE_OMIT_ENDS = "omit.cable.ends"
RULE_OMIT_ENDPOINT = "omit.cable.endpoint"
RULE_OMIT_OUTSIDE = "omit.cable.outside_scope"
RULE_OMIT_MANAGEMENT = "omit.cable.management"

READER = "netbox-dcim"
"""The mapping's name, the source envelope's `mapping.reader`."""

MODEL = "netbox"
"""What the mapping reads, the source envelope's `mapping.model`: NetBox's own DCIM, whose version is NetBox's."""

NOT_PORTS = ("virtual", "bridge", "lag")
"""The interface types that are no port of a blueprint: a virtual, bridge or LAG interface is the configuration's."""

INTERFACE = "dcim.interface"
"""The one object type a link ends on."""

LONGEST = 63
"""The most characters a DNS-1123 label holds."""

APPROXIMATED, OMITTED = "approximated", "omitted"

FIDELITY: tuple[dict[str, str], ...] = (
    {
        "disposition": OMITTED,
        "object": "platform.version",
        "source": "dcim.platform",
        "reason": "NetBox's platform carries no version",
    },
)
"""The fidelity row of every read: what blueprint 1 states that NetBox does not hold."""

_OUTSIDE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Mapped:
    """What the mapping built: the network's devices, each with no `config` yet, and its links, each list sorted;
    `names`, each device's id to its blueprint name, for every device that has one whatever its platform; the fidelity
    rows, sorted, `FIDELITY`'s among them; and the findings, in a result's order (findings.order)."""

    devices: tuple[dict[str, Any], ...]
    links: tuple[dict[str, Any], ...]
    names: Mapping[int, str]
    fidelity: tuple[dict[str, str], ...]
    findings: tuple[Finding, ...]


def label(name: str) -> str:
    """`name` as a DNS-1123 label, by D-038's rule: lower-cased, each run of characters outside `[a-z0-9]` made one
    `-`, and `-` trimmed from both ends. It may be empty, or longer than `LONGEST`, which no label is."""
    return _OUTSIDE.sub("-", name.lower()).strip("-")


def build(
    devices: Sequence[Device],
    platforms: Sequence[Platform],
    ports: Sequence[Port],
    cables: Sequence[Cable],
    document: ReaderDocument,
    *,
    branch: str | None,
) -> Mapped:
    """The network of `devices`, the scope's, with `platforms`, theirs, `ports`, their interfaces of every type, and
    `cables`, the cables of those interfaces, as `document` maps their platforms, with every finding in one pass.
    A platform id a device names that `platforms` lacks raises `KeyError`: the caller holds the platforms list to the
    ids it asked (`rows.incomplete` with `asked=`) before it calls `build`. `branch` is the name of the branch read,
    None for `main`."""
    where = f"branch {branch}" if branch is not None else "main"
    found: list[Finding] = []
    fidelity = [dict(row) for row in FIDELITY]
    ordered = sorted(devices, key=lambda d: (d.name is None, d.name or "", d.id))
    names = _names(ordered, found, fidelity, where)
    held_platforms = {platform.id: platform for platform in platforms}
    packages = {
        d.id: chosen for d in ordered if (chosen := _package(d, held_platforms, document, found, where)) is not None
    }
    built = {d.id for d in ordered if d.id in names and d.id in packages}
    scope = {d.id: d for d in ordered}
    held = {p.id: p for p in ports if p.device in scope}
    owned: dict[int, list[Port]] = {}
    for p in held.values():
        owned.setdefault(p.device, []).append(p)
    network = [
        {"name": names[d.id], "platform": packages[d.id], "interfaces": _interfaces(owned.get(d.id, []))}
        for d in ordered
        if d.id in built
    ]
    links = _links(cables, scope, held, names, built, found, fidelity, where)
    return Mapped(
        devices=tuple(sorted(network, key=lambda device: str(device["name"]))),
        links=tuple(sorted(links, key=_ends)),
        names=names,
        fidelity=tuple(sorted(fidelity, key=_row)),
        findings=order(found),
    )


def _called(device: Device) -> str:
    """A device as findings name it: its name in NetBox, or `dcim.device <id>` where it has none."""
    return device.name if device.name is not None else f"dcim.device {device.id}"


def _names(
    devices: Sequence[Device], found: list[Finding], fidelity: list[dict[str, str]], where: str
) -> dict[int, str]:
    """Each device's blueprint name by its id, where its label is one and no other scoped device's: no name, or a
    label that is none, is `device.name.unmappable`, one shared `device.name.duplicate` for each device sharing it,
    its own first, and a name changed to its label `device.name.renamed` with a fidelity row. A name two of the
    sharing devices hold exactly, which NetBox takes on two sites, is given with each one's id, `n1 (dcim.device 4)`,
    so that their findings differ."""
    sharing: dict[str, list[tuple[Device, str]]] = {}
    for device in devices:
        if device.name is None:
            said = f"The device {_called(device)} on {where} has no name"
        else:
            made = label(device.name)
            if made and len(made) <= LONGEST:
                sharing.setdefault(made, []).append((device, device.name))
                continue
            if not made:
                said = f"Device {device.name} on {where} holds no letter or digit, so its name makes no label"
            else:
                said = (
                    f"Device {device.name} on {where} makes the label {made}, of {len(made)} characters, longer than "
                    f"the {LONGEST} of a DNS-1123 label"
                )
        message = f"{said}, and blueprint 1 names a device by the DNS-1123 label of its name (D-038)."
        found.append(Finding(rule=RULE_UNMAPPABLE, severity="error", object=_called(device), message=message))
    names: dict[int, str] = {}
    for made, held in sharing.items():
        if len(held) > 1:
            names_held = [name for _, name in held]
            told = [f"{name} (dcim.device {d.id})" if names_held.count(name) > 1 else name for d, name in held]
            for index, (_, name) in enumerate(held):
                others = [said for at, said in enumerate(told) if at != index]
                does = "does" if len(others) == 1 else "do"
                message = (
                    f"Device {told[index]} on {where} makes the blueprint name {made}, as {_and(others)} {does}, "
                    "which names one alone."
                )
                found.append(Finding(rule=RULE_DUPLICATE, severity="error", object=name, message=message))
            continue
        ((device, name),) = held
        names[device.id] = made
        if made != name:
            message = f"Device {name} on {where} is named {made} in the blueprint, the DNS-1123 label of its name."
            found.append(Finding(rule=RULE_RENAMED, severity="info", object=name, message=message))
            reason = f"named {made}, its name made the DNS-1123 label blueprint 1 names a device by (D-038)"
            row = {"disposition": APPROXIMATED, "object": name, "source": "dcim.device.name", "reason": reason}
            fidelity.append(row)
    return names


def _package(
    device: Device, platforms: Mapping[int, Platform], document: ReaderDocument, found: list[Finding], where: str
) -> str | None:
    """The platform package `document` names for the device's platform's manufacturer and name, compared exactly; or,
    where it has no platform, its platform no manufacturer, or the pair is in no row, its finding filed and None."""
    called = _called(device)
    platform = platforms[device.platform] if device.platform is not None else None
    if platform is None:
        rule, said = RULE_PLATFORM_MISSING, f"Device {called} on {where} has no platform"
    elif platform.manufacturer is None:
        rule = RULE_PLATFORM_MISSING
        said = f"Device {called}'s platform {platform.name} on {where} has no manufacturer"
    else:
        chosen = document.package(platform.manufacturer, platform.name)
        if chosen is not None:
            return chosen
        rule = RULE_PLATFORM_UNMATCHED
        said = (
            f"Device {called} on {where} is of the manufacturer {platform.manufacturer} and the platform "
            f"{platform.name}, a pair no row of the reader document holds, compared exactly"
        )
    message = f"{said}, so no platform package is chosen for it."
    found.append(Finding(rule=rule, severity="error", object=called, message=message))
    return None


def _interfaces(ports: Sequence[Port]) -> list[dict[str, Any]]:
    """A device's ports as its interfaces, sorted by name: every interface whose type is not in `NOT_PORTS`, with
    NetBox's own `enabled` and `mgmt_only`."""
    interfaces = [
        {"name": port.name, "mgmt_only": port.mgmt_only, "enabled": port.enabled}
        for port in ports
        if port.type not in NOT_PORTS
    ]
    return sorted(interfaces, key=lambda f: (f["name"], f["mgmt_only"], f["enabled"]))


def _links(
    cables: Sequence[Cable],
    scope: Mapping[int, Device],
    held: Mapping[int, Port],
    names: Mapping[int, str],
    built: set[int],
    found: list[Finding],
    fidelity: list[dict[str, str]],
    where: str,
) -> list[dict[str, Any]]:
    """The link of each cable, judged once: the first omission that applies, whatever the devices it ends on; else a
    link, where both its devices are built. A cable that would be a link and ends on a device the mapping refused is
    neither a link nor an omission, that device's refusal being the read's already."""
    links = []
    for cable in sorted(cables, key=lambda c: (_object(c), c.id)):
        ends = sorted((*cable.a, *cable.b), key=lambda e: (e.kind, e.id))
        omitted = _omission(cable, ends, scope, held)
        if omitted is not None:
            rule, reason = omitted
            what = _object(cable)
            message = f"Cable {what} on {where} is omitted from the blueprint: {reason}."
            found.append(Finding(rule=rule, severity="info", object=what, message=message))
            fidelity.append({"disposition": OMITTED, "object": what, "source": "dcim.cable", "reason": reason})
            continue
        if any(held[e.id].device not in built for e in ends):
            continue
        a, b = sorted((names[held[e.id].device], held[e.id].name) for e in ends)
        links.append({"a": {"device": a[0], "interface": a[1]}, "b": {"device": b[0], "interface": b[1]}})
    return links


def _omission(
    cable: Cable, ends: Sequence[End], scope: Mapping[int, Device], held: Mapping[int, Port]
) -> tuple[str, str] | None:
    """Why `cable` is no link, the first of the four reasons that applies, in their order, as its rule and the reason a
    fidelity row gives; None where it is a link. `ends` are both sides' terminations in an order of their own, so that
    which side is `a` changes no reason."""
    if len(cable.a) != 1 or len(cable.b) != 1:
        fewer, more = sorted((len(cable.a), len(cable.b)))
        return RULE_OMIT_ENDS, f"a cable of {fewer} and {more} terminations a side, where a link has one a side"
    for end in ends:
        if end.kind != INTERFACE:
            return RULE_OMIT_ENDPOINT, f"an end on the {end.kind} {end.id}, where a link ends on a {INTERFACE}"
    for end in ends:
        port = held.get(end.id)
        if port is None:
            shown = f" ({end.display})" if end.display is not None else ""
            reason = f"an end on the {INTERFACE} {end.id}{shown}, no interface of a device in the scope"
            return RULE_OMIT_OUTSIDE, reason
        if port.type in NOT_PORTS:
            return (
                RULE_OMIT_OUTSIDE,
                f"an end on {_called(scope[port.device])}:{port.name}, of the type {port.type}, which is no port",
            )
    for end in ends:
        port = held[end.id]
        if port.mgmt_only:
            at = f"{_called(scope[port.device])}:{port.name}"
            return RULE_OMIT_MANAGEMENT, f"an end on the management port {at}, which blueprint 1 refuses a link on"
    return None


def _object(cable: Cable) -> str:
    """A cable as findings name it: its label, or else `cable <id>`."""
    return cable.label if cable.label is not None else f"cable {cable.id}"


def _ends(link: Mapping[str, Any]) -> tuple[str, str, str, str]:
    a, b = link["a"], link["b"]
    return a["device"], a["interface"], b["device"], b["interface"]


def _row(row: Mapping[str, str]) -> tuple[str, str, str, str]:
    return row["disposition"], row["object"], row["source"], row["reason"]


def _and(items: Sequence[str]) -> str:
    """Items as a sentence lists them: `a and b`, `a, b and c`."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"
