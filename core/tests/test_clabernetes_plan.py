"""The clabernetes driver's plan (D-057, D-059), and the package's names it writes: a twin bound
as its own Namespace, a NetworkPolicy and a `Topology` wrapping the containerlab definition the
local plan renders, on the documentation allocation below and no other site value."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from fylgja_core import (
    blueprint,
    clabernetes,
    compiler,
    credentials,
    deployment,
    documents,
    findings,
    platform_package,
    probe_package,
)
from fylgja_core.clabernetes import plan as clabernetes_plan
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.driver import Capabilities, Planned, Unplannable
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage


def test_a_twins_namespace_is_named_for_the_twin() -> None:
    assert clabernetes.namespace_of("three-node") == "fylgja-twin-three-node"


def test_a_pull_secret_is_named_for_its_credentials_key() -> None:
    assert clabernetes.pull_secret("ARISTA_CEOS") == clabernetes.pull_secret(credentials.key("arista-ceos")) == (
        "fylgja-pull-arista-ceos")


def test_the_packages_names() -> None:
    assert clabernetes.NAME == "clabernetes"
    expected = Capabilities(
        nodes="provisions", relink=True, forwarding="software", access="direct", isolation="network", reapply=True)
    assert expected == clabernetes.CAPABILITIES
    assert clabernetes.OWNER_LABEL == "fylgja.owner"
    assert clabernetes.OWNER == "core"
    assert clabernetes.TWIN_LABEL == "fylgja.twin"


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "core" / "src" / "fylgja_core"
PLATFORMS = {
    p.id: p
    for p in map(platform_package.load, [ROOT / "psp/nokia_srlinux.yaml", ROOT / "psp/arista_eos.yaml",
                                         ROOT / "testdata/packages/chassisos.yaml"])
}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes/ping.yaml")]}
REGISTRIES = {"ARISTA_CEOS": "registry.example:5443/arista"}
ALLOCATION: dict[str, Any] = {"namespace": "fylgja-twin-t", "core_namespace": "fylgja", "controller_namespace": "c9s",
                              "pod_cidr": "198.51.100.0/24", "registries": REGISTRIES}
OFF_THE_CLUSTER = {key: value for key, value in ALLOCATION.items() if key != "core_namespace"}
LOCAL_ALLOCATION = {"lab": "t", "mgmt_subnet": "192.0.2.0/24"}
FIXTURES = ["three-node", "mixed", "lossy", "three-node-probed"]
LABELS = {"fylgja.owner": "core", "fylgja.twin": "t"}


def compiled(
    name: str, platforms: dict[str, PlatformPackage] = PLATFORMS, probes: dict[str, ProbePackage] = PROBES
) -> compiler.Compiled:
    return compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), platforms, probes)


def planned(name: str, allocation: dict[str, Any] = ALLOCATION) -> tuple[compiler.Compiled, Planned]:
    c = compiled(name)
    return c, clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", allocation)


def local(c: compiler.Compiled) -> dict[str, Any]:
    """The local plan's topology for the same manifest."""
    p = clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", LOCAL_ALLOCATION)
    doc: dict[str, Any] = yaml.safe_load(p.files["topology.clab.yml"])
    return doc


def document(p: Planned, path: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(p.files[path])
    return doc


def spec(p: Planned) -> dict[str, Any]:
    found: dict[str, Any] = document(p, "topology.yaml")["spec"]
    return found


def wrapped(p: Planned) -> dict[str, Any]:
    """The containerlab definition the Topology wraps."""
    doc: dict[str, Any] = yaml.safe_load(spec(p)["definition"]["containerlab"])
    return doc


def gated_platform(package: PlatformPackage, secret: str) -> PlatformPackage:
    containerlab = package.runtime.containerlab
    image = dataclasses.replace(containerlab.image, pull_secret=secret)
    runtime = dataclasses.replace(package.runtime, containerlab=dataclasses.replace(containerlab, image=image))
    return dataclasses.replace(package, runtime=runtime)


def gated_probe(package: ProbePackage, secret: str) -> ProbePackage:
    containerlab = package.runtime.containerlab
    image = dataclasses.replace(containerlab.image, pull_secret=secret)
    runtime = dataclasses.replace(package.runtime, containerlab=dataclasses.replace(containerlab, image=image))
    return dataclasses.replace(package, runtime=runtime)


def pairs(caught: pytest.ExceptionInfo[Unplannable]) -> list[tuple[str, str | None]]:
    return [(f.rule, f.object) for f in caught.value.findings]


def test_the_namespace_is_the_twins_own_labelled_and_privileged() -> None:
    _, p = planned("three-node")
    assert document(p, "namespace.yaml") == {
        "apiVersion": "v1", "kind": "Namespace",
        "metadata": {"name": "fylgja-twin-t", "labels": {
            "fylgja.owner": "core", "fylgja.twin": "t", "pod-security.kubernetes.io/enforce": "privileged"}}}


def test_the_policy_admits_four_sources_and_three_off_the_cluster() -> None:
    c, p = planned("three-node")
    policy = document(p, "networkpolicy.yaml")
    assert list(policy) == ["apiVersion", "kind", "metadata", "spec"]
    assert (policy["apiVersion"], policy["kind"]) == ("networking.k8s.io/v1", "NetworkPolicy")
    assert policy["metadata"] == {"name": "fylgja-isolation", "namespace": "fylgja-twin-t", "labels": LABELS}
    sources = [
        {"podSelector": {}},
        {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "c9s"}}},
        {"ipBlock": {"cidr": "0.0.0.0/0", "except": ["198.51.100.0/24"]}},
        {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "fylgja"}}},
    ]
    assert policy["spec"] == {"podSelector": {}, "policyTypes": ["Ingress"], "ingress": [{"from": sources}]}
    # A core off the cluster is a non-pod source already (D-059).
    off = clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", OFF_THE_CLUSTER)
    assert document(off, "networkpolicy.yaml")["spec"]["ingress"] == [{"from": sources[:3]}]
    assert off.files["namespace.yaml"] == p.files["namespace.yaml"]
    assert off.files["topology.yaml"] == p.files["topology.yaml"]
    assert off.deployment.id != p.deployment.id


@pytest.mark.parametrize("name", FIXTURES)
def test_the_topology_wraps_the_local_definition_less_its_mgmt_block(name: str) -> None:
    c, p = planned(name)
    theirs = local(c)["topology"]
    ours = wrapped(p)
    assert list(ours) == ["name", "topology"]
    assert ours["name"] == "t"
    assert ours["topology"]["links"] == theirs["links"]
    bare = {
        node: {key: value.removeprefix("registry.example:5443/arista/") if key == "image" else value
               for key, value in fields.items() if key != "ports"}
        for node, fields in ours["topology"]["nodes"].items()
    }
    assert bare == theirs["nodes"]
    assert list(bare) == list(theirs["nodes"])
    assert ours["topology"]["defaults"] == {"labels": LABELS}
    text = p.files["topology.yaml"].decode()
    for absent in ("mgmt", "binds", "startup-config"):
        assert absent not in text
    assert "containerlab: |" in text


def test_a_mixed_twins_topology() -> None:
    _, p = planned("mixed")
    topology = document(p, "topology.yaml")
    assert list(topology) == ["apiVersion", "kind", "metadata", "spec"]
    assert (topology["apiVersion"], topology["kind"]) == ("c9s.run/v1alpha1", "Topology")
    assert list(topology["spec"]) == ["expose", "imagePull", "deployment", "definition"]
    assert topology["metadata"] == {"name": "t", "namespace": "fylgja-twin-t", "labels": LABELS}
    assert spec(p)["expose"] == {"disableAutoExpose": True}
    assert spec(p)["imagePull"] == {"pullSecrets": ["fylgja-pull-arista-ceos"]}
    eos = {"requests": {"cpu": "500m", "memory": "1536Mi"}}
    assert spec(p)["deployment"] == {
        "resources": {"e1": eos, "e2": eos, "s1": {"requests": {"cpu": "500m", "memory": "2048Mi"}}}}
    nodes = wrapped(p)["topology"]["nodes"]
    assert nodes["e1"] == {"kind": "ceos", "image": "registry.example:5443/arista/ceos:4.32.0.2F",
                           "link-apply-mode": "live", "ports": ["22:22", "443:443", "6030:6030"]}
    assert nodes["s1"] == {"kind": "nokia_srlinux", "image": "ghcr.io/nokia/srlinux:24.7.1",
                           "link-apply-mode": "live", "ports": ["22:22", "443:443", "57400:57400"]}


def test_a_probe_host_declares_no_port_and_requests_its_packages_resources() -> None:
    _, p = planned("three-node-probed")
    assert wrapped(p)["topology"]["nodes"]["n1-loop-a"] == {
        "kind": "linux", "image": "alpine:3.24.2",
        "exec": ["ip addr add 10.1.10.2/24 dev eth1", "ip route add 10.1.11.2/32 via 10.1.10.1 dev eth1"]}
    resources = spec(p)["deployment"]["resources"]
    assert list(resources) == ["n1", "n2", "n3", "n1-loop-a", "n1-loop-b"]
    assert resources["n1-loop-a"] == {"requests": {"cpu": "100m", "memory": "32Mi"}}


def test_every_registry_of_the_allocation_is_named_whichever_the_bundle_uses() -> None:
    # The allocation is fixed for the twin's life, so a step that brings a gated kind changes
    # no pod's pull secrets.
    _, before = planned("three-node")
    _, after = planned("steps/three-node-n3-eos")
    assert spec(before)["imagePull"] == {"pullSecrets": ["fylgja-pull-arista-ceos"]}
    assert spec(after)["imagePull"] == spec(before)["imagePull"]
    assert wrapped(after)["topology"]["nodes"]["n3"]["image"] == "registry.example:5443/arista/ceos:4.32.0.2F"
    two_registries = {"B_X": "registry.example/b", "A": "registry.example/a"}
    _, two = planned("three-node", {**ALLOCATION, "registries": two_registries})
    assert spec(two)["imagePull"] == {"pullSecrets": ["fylgja-pull-a", "fylgja-pull-b-x"]}
    _, none = planned("three-node", {**ALLOCATION, "registries": {}})
    assert "imagePull" not in spec(none)


def test_a_port_two_transports_share_is_declared_once() -> None:
    srlinux = PLATFORMS["nokia_srlinux"]
    assert clabernetes_plan.ports(srlinux) == ["22:22", "443:443", "57400:57400"]
    gnmi_on_443 = dataclasses.replace(srlinux, gnmi=dataclasses.replace(srlinux.gnmi, port=443))
    assert clabernetes_plan.ports(gnmi_on_443) == ["22:22", "443:443"]
    push_on_22 = dataclasses.replace(srlinux, push=dataclasses.replace(srlinux.push, port=22))
    assert clabernetes_plan.ports(push_on_22) == ["22:22", "57400:57400"]


def test_the_deployment_lists_three_files_and_hashes_as_d044_says() -> None:
    assert (clabernetes_plan.NAMESPACE, clabernetes_plan.POLICY, clabernetes_plan.TOPOLOGY) == (
        "namespace.yaml", "networkpolicy.yaml", "topology.yaml")
    assert clabernetes_plan.POLICY_NAME == "fylgja-isolation"
    c, p = planned("three-node")
    d = p.deployment
    assert deployment.validate(documents.encode(d)) == []
    assert d.driver == "clabernetes" and d.twin == "t" and d.bundle_id == c.id
    assert d.allocation == ALLOCATION
    assert [f.path for f in d.files] == ["namespace.yaml", "networkpolicy.yaml", "topology.yaml"]
    assert all(f.sha256 == hashlib.sha256(p.files[f.path]).hexdigest() for f in d.files)
    assert set(p.files) == {f.path for f in d.files}
    assert d.id == clab_plan.deployment_id("clabernetes", "t", c.id, d.files)
    # What the twin needs and models is the bundle's on either containerlab driver.
    for name in FIXTURES:
        c, p = planned(name)
        theirs = clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", LOCAL_ALLOCATION).deployment
        assert p.deployment.demand == theirs.demand
        assert p.deployment.fidelity == theirs.fidelity
        assert deployment.validate(documents.encode(p.deployment)) == []
    _, lossy = planned("lossy")
    assert lossy.deployment.fidelity.lossy == deployment.Lossy(mappings=7, shared_ports=3)
    assert any(o.omission == "shared" for o in lossy.deployment.fidelity.omitted)


def test_what_moves_the_id() -> None:
    _, a = planned("three-node")
    _, b = planned("three-node")
    assert a.deployment.id == b.deployment.id and a.files == b.files
    for changed in ({"pod_cidr": "203.0.113.0/24"}, {"controller_namespace": "clabernetes"},
                    {"core_namespace": "fylgja-core"}, {"registries": {**REGISTRIES, "B": "registry.example/b"}}):
        assert planned("three-node", {**ALLOCATION, **changed})[1].deployment.id != a.deployment.id, changed
    # A registry's prefix moves the id only where a node's image is written under it.
    moved = {**ALLOCATION, "registries": {"ARISTA_CEOS": "registry.example:5443/other"}}
    assert planned("mixed", moved)[1].deployment.id != planned("mixed")[1].deployment.id
    assert planned("three-node", moved)[1].deployment.id == a.deployment.id


def test_a_gated_image_the_allocation_has_no_registry_for_is_refused() -> None:
    c = compiled("mixed")
    with pytest.raises(Unplannable) as caught:
        clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", {**ALLOCATION, "registries": {}})
    assert pairs(caught) == [("plan.registry.absent", "e1"), ("plan.registry.absent", "e2")]
    assert clabernetes_plan.RULE_REGISTRY_ABSENT == "plan.registry.absent"
    assert all(f.severity == "error" for f in caught.value.findings)
    assert caught.value.findings[0].message == (
        "Node e1 runs ceos:4.32.0.2F, which is pulled with the secret arista-ceos, and the twin's allocation "
        "holds no registry for it: FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY was not set when the twin was admitted.")
    with pytest.raises(KeyError):
        clabernetes_plan.image(PLATFORMS["arista_eos"].runtime.containerlab.image, {})
    # A probe host's image is held to the same rule.
    probes = {"ping": gated_probe(PROBES["ping"], "probe")}
    c = compiled("three-node-probed", PLATFORMS, probes)
    with pytest.raises(Unplannable) as caught:
        clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, probes, "t", ALLOCATION)
    assert pairs(caught) == [("plan.registry.absent", "n1-loop-a"), ("plan.registry.absent", "n1-loop-b")]


REJECTED_DIR = ROOT / "testdata" / "deployment" / "rejected"
REJECTED = ["port-shared-link.json", "port-shared-probe.json"]


@pytest.mark.parametrize("name", REJECTED)
def test_each_rejection_fixture_is_refused_as_the_local_plan_refuses_it(name: str) -> None:
    c = compiler.compile(blueprint.load(REJECTED_DIR / name), PLATFORMS, PROBES)
    with pytest.raises(Unplannable) as ours:
        clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", ALLOCATION)
    with pytest.raises(Unplannable) as theirs:
        clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", LOCAL_ALLOCATION)
    assert pairs(ours) == pairs(theirs)
    assert {p.name for p in REJECTED_DIR.glob("*.json")} == set(REJECTED)


def test_every_fault_is_reported_in_one_pass() -> None:
    platforms = {**PLATFORMS, "chassisos": gated_platform(PLATFORMS["chassisos"], "chassis")}
    c = compiler.compile(blueprint.load(REJECTED_DIR / "port-shared-link.json"), platforms, PROBES)
    with pytest.raises(Unplannable) as caught:
        clabernetes_plan.plan(c.manifest, c.id, platforms, PROBES, "t", ALLOCATION)
    assert set(pairs(caught)) == {("interface.port.shared", "c1:Ethernet1/1"),
                                  ("interface.port.shared", "c1:Ethernet2/1"),
                                  ("plan.registry.absent", "c1"), ("plan.registry.absent", "c2")}
    assert len(caught.value.findings) == 4
    assert caught.value.findings == findings.order(caught.value.findings)


def test_an_allocation_that_is_not_the_twins_is_the_callers_error() -> None:
    c = compiled("three-node")
    wrong = [({**ALLOCATION, "namespace": "fylgja-twin-u"}, "'fylgja-twin-u'")]
    wrong += [({key: value for key, value in ALLOCATION.items() if key != member}, member)
              for member in ("controller_namespace", "pod_cidr", "registries")]
    wrong += [({**ALLOCATION, "pod_cidr": cidr}, f"'{cidr}'") for cidr in ("fd00::/48", "198.51.100.1/24")]
    for allocation, named in wrong:
        with pytest.raises(ValueError, match=named):
            clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", allocation)


@pytest.mark.parametrize(("member", "value"), [("core_namespace", None), ("core_namespace", ""),
                                               ("controller_namespace", None), ("controller_namespace", ""),
                                               ("pod_cidr", "198.51.100.0")])
def test_an_allocation_member_present_and_unusable_is_the_callers_error(member: str, value: Any) -> None:
    """A namespace member that is no non-empty string would name no namespace in the policy, and
    a pod CIDR with no prefix length would be read as one address, a policy that keeps almost no
    pod out. Absent, `core_namespace` is the core off the cluster, which the policy's test plans."""
    c = compiled("three-node")
    with pytest.raises(ValueError, match=re.escape(f"{member} {value!r}")):
        clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", {**ALLOCATION, member: value})


PURE_IMPORTS = {"__future__", "collections.abc", "hashlib", "ipaddress", "typing", "yaml"}
MODEL_IMPORTS = {f"fylgja_core.{m}" for m in ("blueprint", "bundle", "clabernetes", "containerlab.plan",
                                              "credentials", "deployment", "driver", "findings", "platform_package",
                                              "probe_package")}


def imports(source: str) -> set[str]:
    """Every module `source` imports. A from-import that names a module of a package records
    that module, not the package, so an impure sibling cannot hide behind its package."""
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None and node.level == 0
            for alias in node.names:
                name = f"{node.module}.{alias.name}"
                path = SRC.parent.joinpath(*name.split("."))
                is_module = path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()
                imported.add(name if is_module else node.module)
    return imported


# The package imports the seam alone; the plan, the model modules too.
ALLOWED = {"clabernetes/__init__.py": {"fylgja_core.driver"}, "clabernetes/plan.py": PURE_IMPORTS | MODEL_IMPORTS}


@pytest.mark.parametrize("module", list(ALLOWED))
def test_plan_is_pure(module: str) -> None:
    """Constitution V: no I/O, clock or environment, held by the imports: the plan's own and
    its package's, so that neither re-exports one."""
    imported = imports((SRC / module).read_text())
    assert imported <= ALLOWED[module], imported - ALLOWED[module]


GOLDEN = ROOT / "testdata" / "deployment" / "clabernetes"


@pytest.mark.parametrize("name", FIXTURES)
def test_the_plan_is_the_golden_deployment(name: str) -> None:
    c = compiled(name)
    allocation = {**ALLOCATION, "namespace": clabernetes.namespace_of(name)}
    p = clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, name, allocation)
    for path in (clabernetes_plan.NAMESPACE, clabernetes_plan.POLICY, clabernetes_plan.TOPOLOGY):
        assert p.files[path] == (GOLDEN / name / path).read_bytes(), path
    golden = json.loads((GOLDEN / name / "deployment.json").read_text())
    encoded = documents.encode(p.deployment)
    assert encoded == golden
    assert deployment.validate(encoded) == []
    # The allocation the goldens are planned on holds a documentation range and a reserved name.
    assert golden["allocation"] == {
        "namespace": f"fylgja-twin-{name}", "core_namespace": "fylgja", "controller_namespace": "c9s",
        "pod_cidr": "198.51.100.0/24", "registries": {"ARISTA_CEOS": "registry.example:5443/arista"}}
