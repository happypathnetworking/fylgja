"""The clabernetes driver's plan: a bundle bound to a named twin as three Kubernetes objects
(D-019, D-044, D-057, D-059).

`plan` is pure, as the local driver's is (Constitution V and XIII): no I/O, clock or
environment, which a test enforces through its imports. It renders three files:

- `namespace.yaml`, the twin's own Namespace, `namespace_of(twin)`, labelled as the core's
  and the twin's, its pod security `privileged`, since the nodes run privileged;
- `networkpolicy.yaml`, which admits ingress to the twin's pods from its own pods,
  clabernetes' namespace, any source outside the pod CIDR (a client off the cluster) and,
  when the allocation names one, the core's namespace, so that no other twin's pod reaches
  them;
- `topology.yaml`, a `Topology` wrapping the containerlab definition both containerlab
  drivers render, with no `mgmt` block, bind or startup-config. Every pod carries both
  labels; each device declares SSH and its package's push and gNMI ports, since auto-expose
  is off, and a probe host declares none, so it gets no LoadBalancer; each node requests its
  package's resources; and a gated image is written under its registry's prefix.

No Secret is one of them, and no credential reaches any: the store keeps every deployment's
files, so `apply` makes each pull secret in the twin's namespace from the credential provider
(D-057). The Topology names the pull secret of every registry the allocation holds, whichever
the bundle uses: the allocation is fixed for the twin's life, so a step that brings a gated
kind changes no pod's pull secrets. A node whose image needs a registry the allocation lacks
is refused (`plan.registry.absent`), with the local plan's refusals, in one pass.

The deployment's id hashes the driver, the twin, the bundle id and the three files (D-044).
It moves with what the allocation puts in a file (the controller's and the core's
namespaces, the pod CIDR, the set of registries, and the prefix of a registry a node's image
is written under) and with what a package does (kind, image, link mode, ports, resources, a
host's commands); not with the prefix of a registry no node's image uses.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any

import yaml

from fylgja_core import blueprint, bundle, credentials, platform_package, probe_package
from fylgja_core.clabernetes import CAPABILITIES, NAME, OWNER, OWNER_LABEL, TWIN_LABEL, namespace_of, pull_secret
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.driver import Allocation, Planned, Unplannable
from fylgja_core.findings import Finding
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage

NAMESPACE = "namespace.yaml"
POLICY = "networkpolicy.yaml"
TOPOLOGY = "topology.yaml"

POLICY_NAME = "fylgja-isolation"

# Rule ids. Clients and tests match on them; the catalogue is docs/rules.md.
RULE_REGISTRY_ABSENT = "plan.registry.absent"


def plan(
    manifest: bundle.Manifest,
    bundle_id: str,
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
    twin: str,
    allocation: Allocation,
) -> Planned:
    """The deployment of the bundle `bundle_id`, whose manifest is `manifest`, as the twin
    `twin` on the allocation `admit` reserved for it, and the three files it lists; or
    `Unplannable` with every fault. An allocation that is not the twin's (another namespace, a
    member missing, a namespace member present and not a non-empty string, a pod CIDR that is
    no IPv4 network written with its prefix length) is the caller's error, a `ValueError`."""
    namespace = namespace_of(twin)
    if allocation.get("namespace") != namespace:
        raise ValueError(f"the allocation is for the namespace {allocation.get('namespace')!r}, "
                         f"not the twin {twin!r}'s {namespace!r}")
    for member in ("controller_namespace", "pod_cidr", "registries"):
        if member not in allocation:
            raise ValueError(f"the allocation holds no {member}")
    for member in ("controller_namespace", "core_namespace"):
        if member in allocation and not (isinstance(allocation[member], str) and allocation[member]):
            raise ValueError(f"the allocation's {member} {allocation[member]!r} is not a namespace's name")
    pod_cidr = _pod_cidr(allocation["pod_cidr"])
    registries: Mapping[str, str] = allocation["registries"]

    images = {device.name: platforms[device.platform].runtime.containerlab.image for device in manifest.nodes}
    images |= {
        host: probe_packages[probe.format].runtime.containerlab.image
        for probe in manifest.probes
        for host, _, _ in blueprint.hosts(probe)
    }
    refused = [
        _registry_absent(node, pulled.ref, pulled.pull_secret)
        for node, pulled in images.items()
        if pulled.pull_secret is not None and credentials.key(pulled.pull_secret) not in registries
    ]
    try:
        counts, shared = clab_plan.lossy(manifest, platforms)
    except Unplannable as caught:
        raise Unplannable([*caught.findings, *refused]) from None
    if refused:
        raise Unplannable(refused)

    labels = {OWNER_LABEL: OWNER, TWIN_LABEL: twin}
    files = {
        NAMESPACE: clab_plan.dump({
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": namespace, "labels": {**labels, "pod-security.kubernetes.io/enforce": "privileged"}},
        }),
        POLICY: clab_plan.dump(_policy(namespace, labels, allocation, pod_cidr)),
        TOPOLOGY: _topology(manifest, platforms, probe_packages, twin, namespace, labels, images, registries),
    }
    return clab_plan.bind(
        driver=NAME, forwarding=CAPABILITIES.forwarding, manifest=manifest, bundle_id=bundle_id, platforms=platforms,
        probe_packages=probe_packages, twin=twin, allocation=allocation, files=files, counts=counts, shared=shared)


def image(image: platform_package.Image, registries: Mapping[str, str]) -> str:
    """The reference a node's image is pulled by: a gated image (one with a pull secret) under
    its registry's prefix, `<prefix>/<ref>`, and any other by its `ref`. `KeyError` when
    `registries` holds no prefix for the pull secret."""
    if image.pull_secret is None:
        return image.ref
    return f"{registries[credentials.key(image.pull_secret)]}/{image.ref}"


def ports(package: PlatformPackage) -> list[str]:
    """The ports a device declares, so that its LoadBalancer serves them: SSH on 22 and the
    package's push and gNMI ports, ascending and each once, as `<port>:<port>`."""
    return [f"{port}:{port}" for port in sorted({22, package.push.port, package.gnmi.port})]


def _pod_cidr(value: Any) -> str:
    """The allocation's pod CIDR, an IPv4 network written with its prefix length and read
    strictly; a `ValueError` for anything else, a bare address among them, which would be read
    as one address and keep almost no pod out."""
    message = f"the allocation's pod_cidr {value!r} is not an IPv4 network written with its prefix length"
    if not isinstance(value, str) or "/" not in value:
        raise ValueError(message)
    try:
        return str(ipaddress.IPv4Network(value))
    except ValueError:
        raise ValueError(message) from None


def _registry_absent(node: str, ref: str, secret: str) -> Finding:
    """The finding for a node whose image is pulled with a secret the allocation has no registry for."""
    message = (f"Node {node} runs {ref}, which is pulled with the secret {secret}, and the twin's allocation "
               f"holds no registry for it: {credentials.variable(secret, 'REGISTRY')} was not set when the twin "
               "was admitted.")
    return Finding(rule=RULE_REGISTRY_ABSENT, severity="error", object=node, message=message)


def _policy(namespace: str, labels: Mapping[str, str], allocation: Allocation, pod_cidr: str) -> dict[str, Any]:
    """The twin's NetworkPolicy: ingress from its own pods, clabernetes' namespace, any source
    outside the pod CIDR, and the core's namespace when the core runs on the cluster (D-059)."""
    sources: list[dict[str, Any]] = [
        {"podSelector": {}},
        _namespace_source(allocation["controller_namespace"]),
        {"ipBlock": {"cidr": "0.0.0.0/0", "except": [pod_cidr]}},
    ]
    if "core_namespace" in allocation:
        sources.append(_namespace_source(allocation["core_namespace"]))
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": POLICY_NAME, "namespace": namespace, "labels": dict(labels)},
        "spec": {"podSelector": {}, "policyTypes": ["Ingress"], "ingress": [{"from": sources}]},
    }


def _namespace_source(name: str) -> dict[str, Any]:
    """A policy source naming one namespace by the label Kubernetes sets on every namespace."""
    return {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": name}}}


class _Dumper(yaml.SafeDumper):
    """Multi-line strings as literal blocks, so the wrapped definition reads as the YAML it is."""


def _text(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|" if "\n" in value else None)


_Dumper.add_representer(str, _text)


def _topology(
    manifest: bundle.Manifest,
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
    twin: str,
    namespace: str,
    labels: Mapping[str, str],
    images: Mapping[str, platform_package.Image],
    registries: Mapping[str, str],
) -> bytes:
    """The `Topology`: the containerlab definition with both labels on every pod, each node's
    image as it is pulled and each device's ports, and every node's requests, in its order."""
    definition = clab_plan.definition(manifest, platforms, probe_packages, twin)
    definition["topology"]["defaults"] = {"labels": dict(labels)}
    nodes = definition["topology"]["nodes"]
    for node, pulled in images.items():
        nodes[node]["image"] = image(pulled, registries)
    for device in manifest.nodes:
        nodes[device.name]["ports"] = ports(platforms[device.platform])
    requests = {device.name: _requests(platforms[device.platform].runtime.containerlab.resources)
                for device in manifest.nodes}
    requests |= {
        host: _requests(probe_packages[probe.format].runtime.containerlab.resources)
        for probe in manifest.probes
        for host, _, _ in blueprint.hosts(probe)
    }
    spec: dict[str, Any] = {"expose": {"disableAutoExpose": True}}
    if registries:
        spec["imagePull"] = {"pullSecrets": [pull_secret(key) for key in sorted(registries)]}
    spec["deployment"] = {"resources": {node: {"requests": requests[node]} for node in nodes}}
    spec["definition"] = {"containerlab": clab_plan.dump(definition).decode("utf-8")}
    doc = {
        "apiVersion": "c9s.run/v1alpha1",
        "kind": "Topology",
        "metadata": {"name": twin, "namespace": namespace, "labels": dict(labels)},
        "spec": spec,
    }
    return yaml.dump(doc, Dumper=_Dumper, sort_keys=False, width=1000).encode("utf-8")


def _requests(resources: platform_package.Resources | probe_package.Resources) -> dict[str, str]:
    """A node's pod requests, from its package's resources: requests alone, never limits."""
    return {"cpu": f"{round(resources.cpu * 1000)}m", "memory": f"{resources.memory_mb}Mi"}
