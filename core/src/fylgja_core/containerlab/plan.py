"""The local driver's plan: a bundle bound to a named twin as a containerlab lab (D-011,
D-015, D-043, D-044).

`plan` is the seam's one pure call (Constitution V and XIII): no I/O, clock or environment,
which a test enforces through its imports. It renders `topology.clab.yml`: the lab named
exactly the twin's name on its own management network, `clab-<twin>`, with the allocation's
subnet; every container labelled as the twin's; a node per device with its package's kind,
image and link mode, and no startup-config, bootstrap or pull option, since the kind's
baseline is enough; a linux node per probe host, which sets its address and its route to the
far host when it starts; and the links, the intent's and then the probes'. An endpoint is the
production name where the kind has aliases and the package's rename of it where the kind has
none (D-015). The deployment lists the file, and its id hashes the driver, the twin, the
bundle id and the file list (D-044).

Both containerlab drivers share the render and the assembly (D-057): `definition` is the lab
less its management network, which the local plan sets and clabernetes wraps in a `Topology`;
`dump` writes a document; and `bind` assembles the deployment of a driver's files.

Only the plan renders the rename, so the facts of a rename that maps many production names
onto one port are its own (`lossy`): the renames that drop a placeholder, the ports two
interfaces of one node land on, and the uncabled interfaces such a port omits because a
cabled one holds it. A port two cabled interfaces land on would be cabled twice, so the plan
refuses it (`Unplannable`, rule `interface.port.shared`), as a compile refuses what it cannot
build; the compiler cannot, since the rename is the runtime's (D-038).
"""

from __future__ import annotations

import hashlib
import math
import shlex
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import yaml

from fylgja_core import blueprint, bundle, deployment, mapping, probe_package
from fylgja_core.containerlab import CAPABILITIES, NAME
from fylgja_core.driver import Allocation, Planned, Unplannable
from fylgja_core.findings import Finding
from fylgja_core.platform_package import PlatformPackage, placeholders
from fylgja_core.probe_package import ProbePackage

TOPOLOGY = "topology.clab.yml"

# Rule ids. Clients and tests match on them; the catalogue is docs/rules.md.
RULE_PORT_SHARED = "interface.port.shared"


def plan(
    manifest: bundle.Manifest,
    bundle_id: str,
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
    twin: str,
    allocation: Allocation,
) -> Planned:
    """The deployment of the bundle `bundle_id`, whose manifest is `manifest`, as the twin
    `twin` on the allocation `admit` reserved for it, and the files the deployment lists; or
    `Unplannable` with every fault. An allocation for another lab than the twin's is the
    caller's error, a `ValueError`: the lab is named exactly the twin's name (D-043)."""
    if allocation.get("lab") != twin:
        raise ValueError(f"the allocation is for the lab {allocation.get('lab')!r}, not the twin {twin!r}")
    counts, shared = lossy(manifest, platforms)
    doc = definition(manifest, platforms, probe_packages, twin)
    mgmt = {"network": f"clab-{twin}", "ipv4-subnet": allocation["mgmt_subnet"]}
    files = {TOPOLOGY: dump({"name": doc["name"], "mgmt": mgmt, "topology": doc["topology"]})}
    return bind(NAME, CAPABILITIES.forwarding, manifest, bundle_id, platforms, probe_packages, twin, allocation, files,
                counts, shared)


def bind(
    driver: str,
    forwarding: Literal["software", "hardware"],
    manifest: bundle.Manifest,
    bundle_id: str,
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
    twin: str,
    allocation: Allocation,
    files: Mapping[str, bytes],
    counts: deployment.Lossy,
    shared: Sequence[deployment.Omitted],
) -> Planned:
    """The deployment the driver `driver` plans of the bundle `bundle_id` for the twin `twin`,
    and its rendered `files`: the files listed by path with their SHA-256, the fidelity (the
    runtime's `forwarding`, the compile's approximations and omissions with the rename's
    `shared` ones, the probe hosts synthesized and the rename's `counts`), the demand and the id
    (D-044). Both containerlab drivers assemble their plans so."""
    listed = tuple(deployment.File(path=path, sha256=hashlib.sha256(files[path]).hexdigest()) for path in sorted(files))
    omitted = [
        deployment.Omitted(device=row.device, interface=row.interface, omission=row.omission)
        for row in manifest.mapping
        if row.omission is not None
    ] + list(shared)
    fidelity = deployment.Fidelity(
        forwarding=forwarding,
        approximations=_approximations(manifest, platforms, probe_packages),
        omitted=tuple(sorted(omitted, key=lambda o: (o.device, o.interface))),
        synthesized=tuple(sorted(host for probe in manifest.probes for host, _, _ in blueprint.hosts(probe))),
        lossy=counts,
    )
    planned = deployment.Deployment(
        id=deployment_id(driver, twin, bundle_id, listed),
        driver=driver,
        twin=twin,
        allocation=dict(allocation),
        bundle_id=bundle_id,
        files=listed,
        demand=demand(manifest, platforms, probe_packages),
        fidelity=fidelity,
    )
    return Planned(deployment=planned, files=dict(files))


def endpoint_port(package: PlatformPackage, row: bundle.Row) -> str:
    """The topology's name for the port of a data row the twin represents: the production
    name where the kind has aliases, else the rename of the row's rule rendered with what the
    rule's match captures of the production name (D-015)."""
    if package.runtime.containerlab.alias:
        return row.interface
    port, _ = _rename(package, row)
    return port


def lossy(
    manifest: bundle.Manifest, platforms: Mapping[str, PlatformPackage]
) -> tuple[deployment.Lossy, tuple[deployment.Omitted, ...]]:
    """The counts of the rename's many-to-one mappings, and the interfaces it omits as
    `shared`, sorted by (device, interface).

    On a kind with no aliases every data row the twin represents, cabled or uncabled, is
    renamed. A rename is lossy when its template names fewer placeholders than its rule's
    match captures; a port is shared when two or more rows of one node are renamed onto it.
    An uncabled row whose port a cabled row of its node holds is omitted as `shared`: the
    twin has that port once, and it is the cabled interface's. Two or more cabled rows on one
    port (a link's end or a probe's endpoint each) raise `Unplannable`, one finding for each,
    since the topology would cable the port twice. A kind with aliases contributes nothing."""
    package_of = {node.name: platforms[node.platform] for node in manifest.nodes}
    mappings = 0
    onto: dict[tuple[str, str], list[bundle.Row]] = {}
    for row in manifest.mapping:
        package = package_of[row.device]
        if package.runtime.containerlab.alias or row.disposition not in ("cabled", "uncabled"):
            continue
        port, dropped = _rename(package, row)
        if dropped:
            mappings += 1
        onto.setdefault((row.device, port), []).append(row)
    shared_ports = {key: rows for key, rows in onto.items() if len(rows) > 1}
    refused = [
        _port_shared(port, row, rows)
        for (_, port), rows in shared_ports.items()
        if sum(r.disposition == "cabled" for r in rows) > 1
        for row in rows
        if row.disposition == "cabled"
    ]
    if refused:
        raise Unplannable(refused)
    omitted = [
        deployment.Omitted(device=row.device, interface=row.interface, omission="shared")
        for rows in shared_ports.values()
        if any(r.disposition == "cabled" for r in rows)
        for row in rows
        if row.disposition == "uncabled"
    ]
    counts = deployment.Lossy(mappings=mappings, shared_ports=len(shared_ports))
    return counts, tuple(sorted(omitted, key=lambda o: (o.device, o.interface)))


def demand(
    manifest: bundle.Manifest, platforms: Mapping[str, PlatformPackage], probe_packages: Mapping[str, ProbePackage]
) -> deployment.Demand:
    """What the deployment needs: a node per device and per probe host, and the sum of their
    packages' per-node resources."""
    devices = [platforms[node.platform].runtime.containerlab.resources for node in manifest.nodes]
    hosts = [probe_packages[probe.format].runtime.containerlab.resources for probe in manifest.probes for _ in "ab"]
    resources = [(r.cpu, r.memory_mb) for r in devices] + [(r.cpu, r.memory_mb) for r in hosts]
    return deployment.Demand(
        nodes=len(resources), cpu=math.fsum(cpu for cpu, _ in resources), memory_mb=sum(mb for _, mb in resources)
    )


def deployment_id(driver_name: str, twin: str, bundle_id: str, files: Sequence[deployment.File]) -> str:
    """The deployment's id: the SHA-256 of the RFC 8785 bytes of its driver, twin, bundle id
    and files, the files sorted by path (D-044)."""
    listed = [{"path": f.path, "sha256": f.sha256} for f in sorted(files, key=lambda f: f.path)]
    body = {"driver": driver_name, "twin": twin, "bundle_id": bundle_id, "files": listed}
    return hashlib.sha256(blueprint.canonical(body)).hexdigest()


def definition(
    manifest: bundle.Manifest,
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
    twin: str,
) -> dict[str, Any]:
    """The containerlab definition both containerlab drivers render, with no `mgmt` block,
    which is the local driver's alone: the lab named `twin`, every container labelled as the
    twin's, a node per device and per probe host, and the links, the intent's and then the
    probes'."""
    package_of = {node.name: platforms[node.platform] for node in manifest.nodes}
    rows = {(row.device, row.interface): row for row in manifest.mapping}

    def endpoint(device: str, interface: str) -> str:
        return f"{device}:{endpoint_port(package_of[device], rows[(device, interface)])}"

    nodes: dict[str, Any] = {}
    for node in manifest.nodes:
        containerlab = package_of[node.name].runtime.containerlab
        nodes[node.name] = {
            "kind": containerlab.kind,
            "image": containerlab.image.ref,
            "link-apply-mode": containerlab.link_apply_mode,
        }
    links = [
        {"endpoints": [endpoint(link.a.device, link.a.interface), endpoint(link.b.device, link.b.interface)]}
        for link in manifest.links
    ]
    for probe in manifest.probes:
        package = probe_packages[probe.format]
        for side, (host, near, _far) in zip("ab", blueprint.hosts(probe), strict=True):
            values = probe_package.host_values(package, probe, side)
            nodes[host] = {
                "kind": "linux",
                "image": package.runtime.containerlab.image.ref,
                "exec": [_command(package.host.address, values), _command(package.host.route, values)],
            }
            links.append({"endpoints": [f"{host}:{package.host.interface}", endpoint(near.device, near.interface)]})
    return {"name": twin, "topology": {"defaults": {"labels": {"fylgja.twin": twin}}, "nodes": nodes, "links": links}}


def dump(doc: Mapping[str, Any]) -> bytes:
    """A document as the drivers write it: block YAML, the keys in their order."""
    # A wide line, so that no long scalar (an exec line) is folded onto the next.
    return yaml.safe_dump(doc, sort_keys=False, width=1000).encode("utf-8")


def _rename(package: PlatformPackage, row: bundle.Row) -> tuple[str, bool]:
    """A data row's port on a kind with no aliases, and whether the rename is lossy."""
    rule = next((r for r in package.interfaces.rules if r.name == row.rule), None)
    rename = next((r for r in package.runtime.containerlab.rename or () if r.rule == row.rule), None)
    captures = None if rule is None or rule.match is None else mapping.match(rule.match, row.interface)
    if rename is None or captures is None:
        raise ValueError(f"{row.device}:{row.interface} is no data row of a rule the package renames: {row.rule!r}")
    return mapping.render(rename.port, captures), len(set(placeholders(rename.port))) < len(captures)


def _port_shared(port: str, row: bundle.Row, rows: Sequence[bundle.Row]) -> Finding:
    """The finding for a cabled row the rename puts on `port` with other cabled rows."""
    others = ", ".join(f"{r.interface} ({r.disposition})" for r in rows if r is not row)
    message = (f"Port {row.device}:{row.interface} is cabled, and the rename puts it on {port} with {others}; "
               "the twin can cable a port once.")
    return Finding(rule=RULE_PORT_SHARED, severity="error", object=f"{row.device}:{row.interface}", message=message)


def _command(words: Sequence[str], values: Mapping[str, str]) -> str:
    """A probe package's command with its placeholders rendered, as one shell line for `exec`."""
    return shlex.join(mapping.render(word, values) for word in words)


def _approximations(
    manifest: bundle.Manifest, platforms: Mapping[str, PlatformPackage], probe_packages: Mapping[str, ProbePackage]
) -> tuple[deployment.Approximation, ...]:
    """As the compiler builds them, so plan and compile agree: every used platform's, in
    platform order, then every used probe format's."""
    return tuple(
        [
            deployment.Approximation(package=platform, text=text)
            for platform in sorted({node.platform for node in manifest.nodes})
            for text in platforms[platform].fidelity.approximations
        ]
        + [
            deployment.Approximation(package=probe_format, text=text)
            for probe_format in sorted({probe.format for probe in manifest.probes})
            for text in probe_packages[probe_format].fidelity.approximations
        ]
    )
