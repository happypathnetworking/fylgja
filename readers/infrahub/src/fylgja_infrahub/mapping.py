"""The mapping: the DCIM library's devices, ports and cables, as rows, into blueprint 1's network (D-082).

There is one mapping, and `readers/infrahub/mapping.md` documents it member by member. A blueprint's id addresses its
network and probes alone (D-006), so the mapping sorts every list and orders each link's ends itself, and the same
rows in any order map to one network. A device is named by its Infrahub name made a DNS-1123 label (D-038), and its
platform package is the reader document's row of its manufacturer and platform; a device that cannot be named or has no
package is refused, an error, and left out of the network with every link it ends. A connector the mapping cannot make
a link of is omitted, an info finding and a fidelity row: blueprint 1 has nowhere to put it, and the rest of the
network is whole without it. Every finding names the branch and the time read.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fylgja_core.findings import Finding, order

from fylgja_infrahub.document import ReaderDocument
from fylgja_infrahub.rows import Connector, Device, End, Port, incomplete

# Rule ids. Callers and tests match on them (rules.md).
RULE_PLATFORM_MISSING = "platform.missing"
RULE_PLATFORM_UNMATCHED = "platform.unmatched"
RULE_RENAMED = "device.name.renamed"
RULE_UNMAPPABLE = "device.name.unmappable"
RULE_DUPLICATE = "device.name.duplicate"
RULE_OMIT_KIND = "omit.cable.kind"
RULE_OMIT_ENDS = "omit.cable.ends"
RULE_OMIT_ENDPOINT = "omit.cable.endpoint"
RULE_OMIT_OUTSIDE = "omit.cable.outside_scope"
RULE_OMIT_MANAGEMENT = "omit.cable.management"

CABLE = "DcimCable"
"""The one connector kind a link is made of."""

PORT = "InterfacePhysical"
"""The one kind a link ends on, and the one kind of a blueprint's interfaces: an `InterfaceVirtual` is the
configuration's."""

MANAGEMENT = "management"
"""The role of a port that is `mgmt_only`."""

DISABLED = "disabled"
"""The status of a port that is not `enabled`."""

LONGEST = 63
"""The most characters a DNS-1123 label holds."""

APPROXIMATED, OMITTED = "approximated", "omitted"

FIDELITY: tuple[dict[str, str], ...] = (
    {
        "disposition": APPROXIMATED,
        "object": "interface.enabled",
        "source": "InterfacePhysical.status",
        "reason": "a port is enabled unless its status is disabled; the library's status is not an admin state",
    },
    {
        "disposition": APPROXIMATED,
        "object": "interface.mgmt_only",
        "source": "InterfacePhysical.role",
        "reason": "the management port is the port whose role is management; the library has no management-only flag",
    },
    {
        "disposition": OMITTED,
        "object": "platform.version",
        "source": "DcimPlatform",
        "reason": "the library's platform carries no version",
    },
)
"""The fidelity rows of every read, in their order: what blueprint 1 states that the library holds only nearly, or
not at all."""

_OUTSIDE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Mapped:
    """What the mapping built: the network's devices, each with no `config` yet, and its links, each list sorted;
    `names`, each device's id to its blueprint name, for every device that has one whatever its platform; the fidelity
    rows, sorted, `FIDELITY`'s among them; and the findings, in a result's order (findings.order)."""

    devices: tuple[dict[str, Any], ...]
    links: tuple[dict[str, Any], ...]
    names: Mapping[str, str]
    fidelity: tuple[dict[str, str], ...]
    findings: tuple[Finding, ...]


def label(name: str) -> str:
    """`name` as a DNS-1123 label, by D-038's rule: lower-cased, each run of characters outside `[a-z0-9]` made one
    `-`, and `-` trimmed from both ends. It may be empty, or longer than `LONGEST`, which no label is."""
    return _OUTSIDE.sub("-", name.lower()).strip("-")


def build(
    devices: Sequence[Device], ports: Sequence[Port], document: ReaderDocument, *, branch: str, at: str
) -> Mapped:
    """The network of `devices`, the scope's, and `ports`, their physical ports, as `document` maps their platforms,
    with every finding in one pass. `devices` and `ports` are whole lists (rows.incomplete), and a connector's ends
    are held to their count here, each connector judged once however many of its ports were read."""
    when = f"on branch {branch} at {at}"
    found: list[Finding] = []
    fidelity = [dict(row) for row in FIDELITY]
    ordered = sorted(devices, key=lambda d: (d.name, d.id))
    names = _names(ordered, found, fidelity, when)
    packages = {d.id: chosen for d in ordered if (chosen := _package(d, document, found, when)) is not None}
    built = {d.id for d in ordered if d.id in names and d.id in packages}
    held: dict[str, list[Port]] = {}
    for port in ports:
        held.setdefault(port.device, []).append(port)
    network = [
        {"name": names[d.id], "platform": packages[d.id], "interfaces": _interfaces(held.get(d.id, []))}
        for d in ordered
        if d.id in built
    ]
    scope = {d.id: d.name for d in ordered}
    links = _links(ports, scope, names, built, found, fidelity, branch=branch, at=at)
    return Mapped(
        devices=tuple(sorted(network, key=lambda device: str(device["name"]))),
        links=tuple(sorted(links, key=_ends)),
        names=names,
        fidelity=tuple(sorted(fidelity, key=_row)),
        findings=order(found),
    )


def _names(
    devices: Sequence[Device], found: list[Finding], fidelity: list[dict[str, str]], when: str
) -> dict[str, str]:
    """Each device's blueprint name by its id, where its label is one and no other scoped device's: a label that is
    none is `device.name.unmappable`, one shared `device.name.duplicate` for each device sharing it, and a name
    changed to its label `device.name.renamed` with a fidelity row."""
    sharing: dict[str, list[Device]] = {}
    for device in devices:
        made = label(device.name)
        if not made:
            said = "holds no letter or digit, so its name makes no DNS-1123 label"
        elif len(made) > LONGEST:
            said = f"makes the label {made}, of {len(made)} characters, longer than the {LONGEST} of a DNS-1123 label"
        else:
            sharing.setdefault(made, []).append(device)
            continue
        message = f"Device {device.name} {when} {said}, and blueprint 1 names a device by such a label (D-038)."
        found.append(Finding(rule=RULE_UNMAPPABLE, severity="error", object=device.name, message=message))
    names: dict[str, str] = {}
    for made, held in sharing.items():
        if len(held) > 1:
            both = _and([device.name for device in held])
            for device in held:
                message = f"Devices {both} {when} each make the blueprint name {made}, which names one device alone."
                found.append(Finding(rule=RULE_DUPLICATE, severity="error", object=device.name, message=message))
            continue
        (device,) = held
        names[device.id] = made
        if made != device.name:
            message = f"Device {device.name} {when} is named {made} in the blueprint, the DNS-1123 label of its name."
            found.append(Finding(rule=RULE_RENAMED, severity="info", object=device.name, message=message))
            reason = f"named {made}, its name made the DNS-1123 label blueprint 1 names a device by (D-038)"
            row = {"disposition": APPROXIMATED, "object": device.name, "source": "DcimDevice.name", "reason": reason}
            fidelity.append(row)
    return names


def _package(device: Device, document: ReaderDocument, found: list[Finding], when: str) -> str | None:
    """The platform package `document` names for the device's manufacturer and platform, compared exactly; or, where
    it has no platform, its platform no manufacturer, or the pair is in no row, its finding filed and None."""
    if device.platform is not None and device.manufacturer is not None:
        chosen = document.package(device.manufacturer, device.platform)
        if chosen is not None:
            return chosen
    if device.platform is None:
        rule, said = RULE_PLATFORM_MISSING, f"Device {device.name} {when} has no platform"
    elif device.manufacturer is None:
        rule = RULE_PLATFORM_MISSING
        said = f"Device {device.name}'s platform {device.platform} {when} has no manufacturer"
    else:
        rule = RULE_PLATFORM_UNMATCHED
        said = (
            f"Device {device.name} {when} is of the manufacturer {device.manufacturer} and the platform "
            f"{device.platform}, a pair no row of the reader document holds, compared exactly"
        )
    message = f"{said}, so no platform package is chosen for it."
    found.append(Finding(rule=rule, severity="error", object=device.name, message=message))
    return None


def _interfaces(ports: Sequence[Port]) -> list[dict[str, Any]]:
    """A device's physical ports as its interfaces, sorted by name."""
    interfaces = [
        {"name": port.name, "mgmt_only": port.role == MANAGEMENT, "enabled": port.status != DISABLED} for port in ports
    ]
    return sorted(interfaces, key=lambda f: (f["name"], f["mgmt_only"], f["enabled"]))


def _links(
    ports: Sequence[Port],
    scope: Mapping[str, str],
    names: Mapping[str, str],
    built: set[str],
    found: list[Finding],
    fidelity: list[dict[str, str]],
    *,
    branch: str,
    at: str,
) -> list[dict[str, Any]]:
    """The links of every connector a scoped port is connected by, each judged once: ends not whole are
    `read.incomplete`; else the first omission that applies; else a link, where both its devices are built (one
    refused is the read's refusal already, and its links are not built)."""
    reached: dict[str, list[Connector]] = {}
    for port in ports:
        if port.connector is not None and port.device in scope:
            reached.setdefault(port.connector.id, []).append(port.connector)
    held = {port.id: port for port in ports if port.device in scope}
    links = []
    for copies in sorted(reached.values(), key=lambda copies: (_object(copies[0]), copies[0].id)):
        cut = {finding for copy in copies if (finding := incomplete(copy.ends, branch=branch, at=at)) is not None}
        if cut:
            found.extend(sorted(cut, key=lambda finding: finding.message))
            continue
        connector = copies[0]
        ends = sorted(connector.ends.items, key=lambda e: (scope.get(e.device or "", ""), e.port or "", e.id))
        omitted = _omission(connector, ends, scope, held)
        if omitted is not None:
            rule, reason = omitted
            what, noun = _object(connector), "Cable" if connector.kind == CABLE else "Connector"
            message = f"{noun} {what} on branch {branch} at {at} is omitted from the blueprint: {reason}."
            found.append(Finding(rule=rule, severity="info", object=what, message=message))
            fidelity.append({"disposition": OMITTED, "object": what, "source": connector.kind, "reason": reason})
            continue
        if all(end.device in built for end in ends):
            a, b = sorted((names[str(end.device)], held[end.id].name) for end in ends)
            links.append({"a": {"device": a[0], "interface": a[1]}, "b": {"device": b[0], "interface": b[1]}})
    return links


def _omission(
    connector: Connector, ends: Sequence[End], scope: Mapping[str, str], held: Mapping[str, Port]
) -> tuple[str, str] | None:
    """Why `connector` is no link, the first of the five reasons that applies, in their order, as its rule and the
    reason a fidelity row gives; None where it is a link."""
    if connector.kind != CABLE:
        return RULE_OMIT_KIND, f"a connector of the kind {connector.kind}, where a link is a {CABLE}"
    if len(ends) != 2:
        return RULE_OMIT_ENDS, f"a cable of {len(ends)} ends, where a link has two"
    for end in ends:
        if end.kind != PORT:
            return RULE_OMIT_ENDPOINT, f"an end on the {end.kind} {end.id}, where a link ends on an {PORT}"
    for end in ends:
        if end.device not in scope or end.id not in held:
            # A device outside the scope is never read, so it is named by its id.
            where = f"{end.port} of the device {end.device}" if end.device is not None else end.id
            return RULE_OMIT_OUTSIDE, f"an end on {where}, which is no port of a device in the scope"
    for end in ends:
        if held[end.id].role == MANAGEMENT:
            where = f"{scope[str(end.device)]}:{end.port}"
            return RULE_OMIT_MANAGEMENT, f"an end on the management port {where}, which blueprint 1 refuses a link on"
    return None


def _object(connector: Connector) -> str:
    """A connector as findings name it: its label, or else its id."""
    return connector.label or connector.id


def _ends(link: Mapping[str, Any]) -> tuple[str, str, str, str]:
    a, b = link["a"], link["b"]
    return a["device"], a["interface"], b["device"], b["interface"]


def _row(row: Mapping[str, str]) -> tuple[str, str, str, str]:
    return row["disposition"], row["object"], row["source"], row["reason"]


def _and(items: Sequence[str]) -> str:
    """Items as a sentence lists them: `a and b`, `a, b and c`."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"
