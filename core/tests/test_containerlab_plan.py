"""The local driver's plan (D-011, D-015, D-043, D-044): pure, and rendering the four fixtures'
bundles as containerlab topologies bound to a named twin, with the deployment that lists them."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from fylgja_core import blueprint, compiler, deployment, documents, platform_package, probe_package
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.driver import Planned, Unplannable
from fylgja_core.findings import Finding

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


def test_an_allocation_for_another_lab_is_refused() -> None:
    # The lab is named exactly the twin's name (D-043), so an allocation admit made for
    # another twin is a caller's error, never a plan.
    c = planned("three-node")[0]
    with pytest.raises(ValueError, match="the lab 'u', not the twin 't'"):
        clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", {"lab": "u", "mgmt_subnet": "172.20.3.0/24"})
    with pytest.raises(ValueError, match="the lab None, not the twin 't'"):
        clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", {"mgmt_subnet": "172.20.3.0/24"})


def test_the_probed_deployments_fidelity_is_the_compiles_with_the_runtimes_forwarding() -> None:
    c, p = planned("three-node-probed")
    f = p.deployment.fidelity
    assert deployment.validate(documents.encode(p.deployment)) == []
    assert f.approximations == c.fidelity.approximations
    assert f.omitted == c.fidelity.omitted
    assert f.synthesized == c.fidelity.synthesized == ("n1-loop-a", "n1-loop-b")


def test_the_lossy_fixtures_counts_and_shared_ports_are_the_go_compilers() -> None:
    _, p = planned("lossy")
    facts = json.loads((ROOT / "testdata/compiler/lossy.facts.json").read_text())
    lossy_rows = [r for r in facts["lossy"] if r["lossy"]]
    assert p.deployment.fidelity.lossy == deployment.Lossy(mappings=len(lossy_rows), shared_ports=3)
    assert len(lossy_rows) == facts["counts"]["lossy"] == 7
    shared = {f"{o.device}:{o.interface}" for o in p.deployment.fidelity.omitted if o.omission == "shared"}
    assert shared == {o["object"] for o in facts["omissions"] if o["rule"] == "omit.interface.shared"}
    assert [f"{o.device}:{o.interface}" for o in p.deployment.fidelity.omitted] == sorted(
        f"{o.device}:{o.interface}" for o in p.deployment.fidelity.omitted)
    assert {f"{o.device}:{o.interface}" for o in p.deployment.fidelity.omitted} == {
        o["object"] for o in facts["omissions"]}
    assert deployment.validate(documents.encode(p.deployment)) == []


def test_lossy_answers_the_plans_counts_and_the_ports_the_go_compiler_saw_shared() -> None:
    c, p = planned("lossy")
    facts = json.loads((ROOT / "testdata/compiler/lossy.facts.json").read_text())
    rows = {(r.device, r.interface): r for r in c.manifest.mapping}
    counts, shared = clab_plan.lossy(c.manifest, PLATFORMS)
    assert counts == p.deployment.fidelity.lossy
    assert shared == tuple(o for o in p.deployment.fidelity.omitted if o.omission == "shared")
    assert all(rows[(o.device, o.interface)].disposition == "uncabled" for o in shared)
    chassisos = PLATFORMS["chassisos"]
    ports = {(r["device"], clab_plan.endpoint_port(chassisos, rows[(r["device"], r["interface"])]))
             for r in facts["lossy"] if r["shares"]}
    assert ports == {("c1", "eth1"), ("c1", "eth49"), ("c2", "eth50")}


def test_shared_and_omitted_interfaces_render_nowhere_and_cabled_ones_render_once() -> None:
    _, p = planned("lossy")
    links = topology(p)["topology"]["links"]
    assert links == [{"endpoints": ["c1:eth1", "s1:ethernet-1/1"]},
                     {"endpoints": ["c1:eth49", "c2:eth49"]},
                     {"endpoints": ["c2:eth1", "s1:ethernet-1/2/1"]}]


def test_kinds_with_aliases_are_never_lossy() -> None:
    _, p = planned("three-node-probed")
    assert p.deployment.fidelity.lossy == deployment.Lossy(mappings=0, shared_ports=0)


REJECTED_DIR = ROOT / "testdata" / "deployment" / "rejected"
# Every plan rejection fixture, and the (rule, object) pairs the plan must report for it:
# exactly these. Ethernet2/1 renames to eth1 as Ethernet1/1 does, which already ends a link,
# so cabling it too, by a link or by a probe's host, would cable c1's eth1 twice.
SHARED_ETH1 = {(clab_plan.RULE_PORT_SHARED, "c1:Ethernet1/1"), (clab_plan.RULE_PORT_SHARED, "c1:Ethernet2/1")}
REJECTED: dict[str, set[tuple[str, str]]] = {
    "port-shared-link.json": SHARED_ETH1,
    "port-shared-probe.json": SHARED_ETH1,
}


def refused(name: str) -> tuple[Finding, ...]:
    c = compiler.compile(blueprint.load(REJECTED_DIR / name), PLATFORMS, PROBES)
    with pytest.raises(Unplannable) as caught:
        clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", ALLOCATION)
    return caught.value.findings


@pytest.mark.parametrize("name", sorted(REJECTED))
def test_each_rejection_fixture_is_refused_for_its_fault_alone(name: str) -> None:
    found = refused(name)
    # The findings come ordered, so a list comparison also catches a fault filed twice.
    assert [(f.rule, f.object) for f in found] == sorted(REJECTED[name]), found
    for finding in found:
        assert finding.severity == "error"
        assert finding.message[0].isupper() and finding.message.endswith("."), finding.message


def test_every_rejection_fixture_has_a_row() -> None:
    assert {p.name for p in REJECTED_DIR.glob("*.json")} == set(REJECTED)


def test_a_refusal_names_the_port_and_the_other_interfaces_on_it() -> None:
    assert refused("port-shared-link.json") == (
        Finding(rule="interface.port.shared", severity="error", object="c1:Ethernet1/1",
                message="Port c1:Ethernet1/1 is cabled, and the rename puts it on eth1 with Ethernet2/1 (cabled); "
                        "the twin can cable a port once."),
        Finding(rule="interface.port.shared", severity="error", object="c1:Ethernet2/1",
                message="Port c1:Ethernet2/1 is cabled, and the rename puts it on eth1 with Ethernet1/1 (cabled); "
                        "the twin can cable a port once."),
    )
    assert "interface.port.shared on c1:Ethernet1/1" in str(Unplannable(refused("port-shared-probe.json")))


PURE_IMPORTS = {"__future__", "collections.abc", "dataclasses", "hashlib", "ipaddress", "math", "shlex", "typing",
                "yaml"}
MODEL_IMPORTS = {f"fylgja_core.{m}" for m in ("blueprint", "bundle", "containerlab", "deployment", "driver",
                                              "findings", "mapping", "platform_package", "probe_package")}


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


def test_a_from_import_of_a_submodule_names_the_submodule() -> None:
    assert imports("from fylgja_core.containerlab import pool, NAME\nfrom fylgja_core import bundle") == {
        "fylgja_core.containerlab.pool", "fylgja_core.containerlab", "fylgja_core.bundle"}


@pytest.mark.parametrize("module", ["containerlab/plan.py", "containerlab/__init__.py", "containerlab/pool.py",
                                    "driver.py"])
def test_plan_is_pure(module: str) -> None:
    """Constitution V: no I/O, clock or environment. The imports say so, as the compiler's do:
    the plan's own and those of the modules it reaches through, so that none re-exports one."""
    imported = imports((SRC / module).read_text())
    assert imported <= PURE_IMPORTS | MODEL_IMPORTS, imported - (PURE_IMPORTS | MODEL_IMPORTS)


GOLDEN = ROOT / "testdata" / "deployment" / "containerlab"


@pytest.mark.parametrize("name", ["three-node", "mixed", "lossy", "three-node-probed"])
def test_the_plan_is_the_golden_deployment(name: str) -> None:
    c = compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)
    p = clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, name, {"lab": name, "mgmt_subnet": "172.20.1.0/24"})
    assert p.files["topology.clab.yml"] == (GOLDEN / name / "topology.clab.yml").read_bytes()
    encoded = documents.encode(p.deployment)
    assert encoded == json.loads((GOLDEN / name / "deployment.json").read_text())
    assert deployment.validate(encoded) == []
