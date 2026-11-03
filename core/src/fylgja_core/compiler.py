"""The compiler: a blueprint and the loaded packages to a bundle (design/core.md,
architecture §4.2; D-010, D-011, D-014).

`compile` is a pure function with no I/O, clock or environment (Constitution V), which a
test enforces through its imports. It maps every interface through its platform package's
rules, places each probe's two hosts, and answers the bundle's files, manifest and id with
the runtime-independent part of fidelity. A blueprint that does not compile raises
`Uncompilable` with every fault found in one pass, as findings
(formats/findings-1.schema.json).

Two things differ from the frozen Go core by bundle 1's design. An interface no rule
matches, when no link touches it, is an omission that fidelity reports (`no_rule`), not a
refusal; a linked one is still refused, since the twin would silently lose a connection.
Ports two interfaces are renamed onto are the driver plan's to find, since only it renders
the rename.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from fylgja_core import blueprint, bundle, deployment, findings, mapping
from fylgja_core.blueprint import Blueprint
from fylgja_core.findings import Finding
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage

# Rule ids. Clients and tests match on them; the catalogue is docs/rules.md.
RULE_NETWORK_EMPTY = "network.empty"
RULE_NAME_UNSAFE = "device.name.unsafe"
RULE_PLATFORM = "platform.unsupported"
RULE_CONFIG = "config.missing"
RULE_UNMAPPABLE_LINKED = "interface.unmappable.linked"
RULE_PROBE_FORMAT = "probe.format.unknown"
RULE_PROBE_DEVICE = "probe.device.unknown"
RULE_PROBE_INTERFACE = "probe.interface.unknown"
RULE_PROBE_CABLED = "probe.interface.cabled"
RULE_PROBE_MGMT = "probe.interface.mgmt_only"
RULE_PROBE_TAKEN = "probe.port.taken"
RULE_PROBE_HOST = "probe.host.collision"


@dataclass(frozen=True, kw_only=True)
class Compiled:
    """What a compile answers: the bundle's id, manifest and files, the runtime-independent
    fidelity, and any findings that did not refuse it."""

    id: str
    manifest: bundle.Manifest
    files: Mapping[str, bytes]
    fidelity: deployment.CompileFidelity
    findings: tuple[Finding, ...]


class Uncompilable(Exception):
    """The blueprint does not compile; `findings` holds every fault, in a verdict's order."""

    def __init__(self, found: Iterable[Finding]) -> None:
        self.findings = findings.order(found)
        super().__init__(self.findings)

    def __str__(self) -> str:
        return "; ".join(f"{f.rule} on {f.object}: {f.message}" for f in self.findings)


def compile(
    bp: Blueprint, platforms: Mapping[str, PlatformPackage], probe_packages: Mapping[str, ProbePackage]
) -> Compiled:
    """The bundle of `bp` with the loaded packages, by id and by format, or `Uncompilable`."""
    found: list[Finding] = []
    devices = {device.name: device for device in bp.network.devices}
    if not devices:
        found.append(_error(RULE_NETWORK_EMPTY, "network", "The network has no devices, and a twin of nothing cannot "
                                                           "be built."))
    for device in bp.network.devices:
        if _unsafe(device.name):
            found.append(_error(RULE_NAME_UNSAFE, device.name, "A device name becomes a file name, so it may not hold "
                                                               "a slash, NUL or another control character, or begin "
                                                               "with a dot."))
        if device.platform not in platforms:
            found.append(_error(RULE_PLATFORM, device.name, f"No loaded platform package is {device.platform!r}; "
                                                            f"loaded: {_listed(platforms)}."))
        if not device.config.strip():
            found.append(_error(RULE_CONFIG, device.name, "The configuration is empty."))

    cabled: dict[tuple[str, str], str] = {}
    for link in bp.network.links:
        description = f"the link {_port(link.a.device, link.a.interface)} to {_port(link.b.device, link.b.interface)}"
        cabled[(link.a.device, link.a.interface)] = description
        cabled[(link.b.device, link.b.interface)] = description

    taken: dict[tuple[str, str], str] = {}
    hosts: list[str] = []
    for probe in bp.probes:
        if probe.format not in probe_packages:
            found.append(_error(RULE_PROBE_FORMAT, probe.name, f"No loaded probe package runs {probe.format!r}; "
                                                               f"loaded: {_listed(probe_packages)}."))
        for side, endpoint in zip("ab", probe.endpoints, strict=True):
            host, where = f"{probe.name}-{side}", f"{probe.name}/{side}"
            hosts.append(host)
            if host in devices:
                found.append(_error(RULE_PROBE_HOST, where, f"The host's name {host!r} is a device's."))
            target = devices.get(endpoint.device)
            if target is None:
                found.append(_error(RULE_PROBE_DEVICE, where, f"No device is named {endpoint.device!r}."))
                continue
            interface = next((i for i in target.interfaces if i.name == endpoint.interface), None)
            port, key = _port(endpoint.device, endpoint.interface), (endpoint.device, endpoint.interface)
            if interface is None:
                message = f"{endpoint.device} has no interface {endpoint.interface!r}."
                found.append(_error(RULE_PROBE_INTERFACE, where, message))
            elif interface.mgmt_only:
                found.append(_error(RULE_PROBE_MGMT, where, f"{port} is the management port."))
            elif key in cabled:
                message = f"{port} ends {cabled[key]}; a probe takes an uncabled port."
                found.append(_error(RULE_PROBE_CABLED, where, message))
            elif key in taken:
                message = f"{port} is taken by {taken[key]}; a port is one probe's."
                found.append(_error(RULE_PROBE_TAKEN, where, message))
            else:
                taken[key] = f"probe {probe.name} endpoint {side}"

    rows: list[bundle.Row] = []
    omitted: list[deployment.Omitted] = []
    for device in bp.network.devices:
        package = platforms.get(device.platform)
        if package is None:
            continue
        has_management = False
        for interface in device.interfaces:
            key = (device.name, interface.name)
            linked = cabled.get(key) or taken.get(key)
            decision = mapping.decide(package, interface.name, interface.mgmt_only)
            if isinstance(decision, mapping.Unmappable):
                if linked is not None:
                    message = f"{decision.detail}, and it ends {linked}."
                    found.append(_error(RULE_UNMAPPABLE_LINKED, _port(*key), message))
                rows.append(_omitted(device.name, interface, decision.rule, decision.omission))
                omitted.append(deployment.Omitted(device=device.name, interface=interface.name,
                                                  omission=decision.omission))
                continue
            if interface.mgmt_only and has_management:
                # The twin has one management port: the device's first, by name.
                rows.append(_omitted(device.name, interface, decision.rule, "extra_management"))
                omitted.append(deployment.Omitted(device=device.name, interface=interface.name,
                                                  omission="extra_management"))
                continue
            disposition: bundle.Disposition = "uncabled" if linked is None else "cabled"
            if interface.mgmt_only:
                disposition, has_management = "management", True
            rows.append(bundle.Row(device=device.name, interface=interface.name, rule=decision.rule,
                                   enabled=interface.enabled, disposition=disposition, node_name=decision.node_name))
    if found:
        raise Uncompilable(found)

    files: dict[str, bytes] = {}
    nodes = []
    for device in bp.network.devices:
        path, data = f"configs/{device.name}.cfg", device.config.encode("utf-8")
        files[path] = data
        config = bundle.File(file=path, sha256=hashlib.sha256(data).hexdigest())
        nodes.append(bundle.Node(name=device.name, platform=device.platform, config=config))
    manifest = bundle.Manifest(blueprint_id=blueprint.blueprint_id(bp), nodes=tuple(nodes), mapping=tuple(rows),
                               links=bp.network.links, probes=bp.probes)
    files["manifest.json"] = bundle.manifest_bytes(manifest)
    approximations = [
        deployment.Approximation(package=platform, text=text)
        for platform in sorted({device.platform for device in bp.network.devices})
        for text in platforms[platform].fidelity.approximations
    ] + [
        deployment.Approximation(package=probe_format, text=text)
        for probe_format in sorted({probe.format for probe in bp.probes})
        for text in probe_packages[probe_format].fidelity.approximations
    ]
    fidelity = deployment.CompileFidelity(approximations=tuple(approximations), omitted=tuple(omitted),
                                          synthesized=tuple(sorted(hosts)))
    return Compiled(id=bundle.bundle_id(files), manifest=manifest, files=files, fidelity=fidelity, findings=())


def _omitted(device: str, interface: blueprint.Interface, rule: str | None, omission: bundle.Omission) -> bundle.Row:
    return bundle.Row(device=device, interface=interface.name, rule=rule, enabled=interface.enabled,
                      disposition="omitted", omission=omission)


def _unsafe(name: str) -> bool:
    """Whether a device name would not be a safe bundle file name: a slash, a control character
    (NUL included; sha256sum escapes a newline, so the by-hand id check would not reproduce the
    id) or a leading dot."""
    return "/" in name or name.startswith(".") or any(ord(c) < 0x20 or ord(c) == 0x7F for c in name)


def _error(rule: str, obj: str, message: str) -> Finding:
    return Finding(rule=rule, severity="error", object=obj, message=message)


def _port(device: str, interface: str) -> str:
    return f"{device}:{interface}"


def _listed(loaded: Mapping[str, object]) -> str:
    return ", ".join(sorted(loaded)) or "none"
