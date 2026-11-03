"""The local driver's plan (D-011, D-015, D-043, D-044): pure, and rendering the four fixtures'
bundles as containerlab topologies bound to a named twin, with the deployment that lists them."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

import yaml

from fylgja_core import blueprint, compiler, deployment, documents, platform_package, probe_package
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.driver import Planned

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "core" / "src" / "fylgja_core"
PLATFORMS = {
    p.id: p
    for p in map(platform_package.load, [ROOT / "psp/nokia_srlinux.yaml", ROOT / "psp/arista_eos.yaml",
                                         ROOT / "testdata/packages/chassisos.yaml"])
}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes/ping.yaml")]}
ALLOCATION = {"lab": "t", "mgmt_subnet": "172.20.3.0/24"}


def planned(name: str, twin: str = "t") -> tuple[compiler.Compiled, Planned]:
    c = compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)
    return c, clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, twin, {**ALLOCATION, "lab": twin})


def topology(p: Planned) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(p.files["topology.clab.yml"])
    return doc


def test_the_topology_is_named_for_the_twin_with_its_own_management_network() -> None:
    _, p = planned("three-node", "three-node")
    t = topology(p)
    assert t["name"] == "three-node"
    assert t["mgmt"] == {"network": "clab-three-node", "ipv4-subnet": "172.20.3.0/24"}
    assert t["topology"]["defaults"]["labels"] == {"fylgja.twin": "three-node"}
    assert list(t) == ["name", "mgmt", "topology"]


def test_srlinux_nodes_take_production_names_and_the_kinds_fields() -> None:
    _, p = planned("three-node")
    t = topology(p)
    assert t["topology"]["nodes"]["n1"] == {
        "kind": "nokia_srlinux", "image": "ghcr.io/nokia/srlinux:24.7.1", "link-apply-mode": "live"}
    assert t["topology"]["links"][0] == {"endpoints": ["n1:ethernet-1/1", "n2:ethernet-1/1"]}
    assert "startup-config" not in yaml.safe_dump(t)
    assert "startup-config" not in p.files["topology.clab.yml"].decode()


def test_eos_nodes_take_renamed_ports_and_only_those() -> None:
    _, p = planned("mixed")
    links = topology(p)["topology"]["links"]
    assert links == [{"endpoints": ["e1:eth1", "s1:ethernet-1/1"]},
                     {"endpoints": ["e1:eth2_1", "e2:eth1"]},
                     {"endpoints": ["e2:eth3_1_1", "s1:ethernet-1/2"]}]
    assert "Ethernet" not in p.files["topology.clab.yml"].decode()


def test_probe_hosts_are_linux_nodes_with_their_two_exec_lines_and_links() -> None:
    _, p = planned("three-node-probed")
    t = topology(p)
    assert t["topology"]["nodes"]["n1-loop-a"] == {
        "kind": "linux", "image": "alpine:3.24.2",
        "exec": ["ip addr add 10.1.10.2/24 dev eth1", "ip route add 10.1.11.2/32 via 10.1.10.1 dev eth1"]}
    assert t["topology"]["nodes"]["n1-loop-b"]["exec"] == ["ip addr add 10.1.11.2/24 dev eth1",
                                                            "ip route add 10.1.10.2/32 via 10.1.11.1 dev eth1"]
    assert t["topology"]["links"][-2:] == [{"endpoints": ["n1-loop-a:eth1", "n1:ethernet-1/10"]},
                                           {"endpoints": ["n1-loop-b:eth1", "n1:ethernet-1/11"]}]
    assert list(t["topology"]["nodes"]) == ["n1", "n2", "n3", "n1-loop-a", "n1-loop-b"]


def test_the_demand_sums_the_packages_per_node_resources() -> None:
    c, p = planned("three-node-probed")
    assert p.deployment.demand == deployment.Demand(nodes=5, cpu=1.7, memory_mb=3 * 2048 + 2 * 32)
    assert clab_plan.demand(c.manifest, PLATFORMS, PROBES) == p.deployment.demand


def test_the_deployment_is_valid_names_its_one_file_and_hashes_as_d044_says() -> None:
    c, p = planned("three-node", "three-node")
    d = p.deployment
    assert deployment.validate(documents.encode(d)) == []
    assert d.driver == "containerlab" and d.twin == "three-node" and d.bundle_id == c.id
    assert d.allocation == {"lab": "three-node", "mgmt_subnet": "172.20.3.0/24"}
    sha256 = hashlib.sha256(p.files["topology.clab.yml"]).hexdigest()
    assert d.files == (deployment.File(path="topology.clab.yml", sha256=sha256),)
    assert set(p.files) == {f.path for f in d.files}
    body = {"driver": "containerlab", "twin": "three-node", "bundle_id": c.id,
            "files": [documents.encode(f) for f in d.files]}
    assert d.id == hashlib.sha256(blueprint.canonical(body)).hexdigest()
    assert d.id == clab_plan.deployment_id("containerlab", "three-node", c.id, d.files)
    assert d.fidelity.forwarding == "software" and d.fidelity.approximations == c.fidelity.approximations
    assert d.fidelity.synthesized == () and d.fidelity.lossy == deployment.Lossy(mappings=0, shared_ports=0)


def test_the_same_plan_has_the_same_id_and_another_allocation_another() -> None:
    _, a = planned("three-node")
    _, b = planned("three-node")
    assert a.deployment.id == b.deployment.id
    c = planned("three-node")[0]
    other = clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", {"lab": "t", "mgmt_subnet": "172.20.4.0/24"})
    assert other.deployment.id != a.deployment.id


def test_the_probed_deployments_fidelity_is_the_compiles_with_the_runtimes_forwarding() -> None:
    c, p = planned("three-node-probed")
    f = p.deployment.fidelity
    assert deployment.validate(documents.encode(p.deployment)) == []
    assert f.approximations == c.fidelity.approximations
    assert f.omitted == c.fidelity.omitted
    assert f.synthesized == c.fidelity.synthesized == ("n1-loop-a", "n1-loop-b")


PURE_IMPORTS = {"__future__", "hashlib", "math", "shlex", "collections.abc", "typing", "yaml"}
MODEL_IMPORTS = {f"fylgja_core.{m}" for m in ("blueprint", "bundle", "containerlab", "deployment", "driver",
                                              "mapping", "platform_package", "probe_package")}


def test_plan_is_pure() -> None:
    """Constitution V: no I/O, clock or environment. The imports say so, as the compiler's do."""
    imported = set()
    for node in ast.walk(ast.parse((SRC / "containerlab" / "plan.py").read_text())):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            if node.module == "fylgja_core":
                imported |= {f"fylgja_core.{alias.name}" for alias in node.names}
            else:
                imported.add(node.module)
    assert imported <= PURE_IMPORTS | MODEL_IMPORTS, imported - (PURE_IMPORTS | MODEL_IMPORTS)
