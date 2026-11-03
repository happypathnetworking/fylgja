"""The compiler (design/core.md, architecture §4.2): pure, and held to the facts the frozen Go
compiler produced for the four fixtures (testdata/compiler/*.facts.json): nodes, links, mapping
rows, configurations, probes and omissions. Lossy rows and ports shared by a rename are the
driver plan's facts, computed per deployment, and are not checked here."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from fylgja_core import blueprint, bundle, compiler, deployment, documents, platform_package, probe_package

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "core" / "src" / "fylgja_core"
FIXTURES = ROOT / "testdata" / "blueprint"
FACTS = ROOT / "testdata" / "compiler"
NAMES = ["lossy", "mixed", "three-node", "three-node-probed"]
PLATFORMS = {
    p.id: p
    for p in map(platform_package.load, [ROOT / "psp" / "nokia_srlinux.yaml", ROOT / "psp" / "arista_eos.yaml",
                                         ROOT / "testdata" / "packages" / "chassisos.yaml"])
}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes" / "ping.yaml")]}

# How the Go compiler's dispositions read in bundle 1. A Go "omitted" row is omitted here only
# when the Go omission was unmappable; one omitted for a shared port is uncabled here, since
# sharing is the plan's to compute from the rename.
DISPOSITIONS = {"cabled": "cabled", "configured-not-cabled": "uncabled", "management": "management"}


def compiled(name: str) -> compiler.Compiled:
    return compiler.compile(blueprint.load(FIXTURES / f"{name}.json"), PLATFORMS, PROBES)


def facts(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((FACTS / f"{name}.facts.json").read_text())
    return doc


def hosts_of(c: compiler.Compiled) -> set[str]:
    return {f"{p.name}-{side}" for p in c.manifest.probes for side in "ab"}


def unmappable_of(f: dict[str, Any]) -> set[str]:
    return {o["object"] for o in f["omissions"] if o["rule"] == "omit.interface.unmappable"}


@pytest.mark.parametrize("name", NAMES)
def test_the_nodes_and_configurations_are_the_go_compilers(name: str) -> None:
    c, f = compiled(name), facts(name)
    assert [(n.name, n.platform) for n in c.manifest.nodes] == [(n["name"], n["platform_package"]) for n in f["nodes"]]
    for node, fact in zip(c.manifest.nodes, f["nodes"], strict=True):
        data = c.files[node.config.file]
        assert node.config.file == f"configs/{node.name}.cfg"
        assert node.config.sha256 == fact["config"]["sha256"] == hashlib.sha256(data).hexdigest()
        assert len(data) == fact["config"]["bytes"]
    assert c.manifest.blueprint_id == f["input"]["blueprint_id"]
    assert len(c.manifest.nodes) == f["counts"]["nodes"]


@pytest.mark.parametrize("name", NAMES)
def test_the_links_between_devices_and_to_hosts_are_the_go_compilers(name: str) -> None:
    c, f = compiled(name), facts(name)
    hosts = hosts_of(c)

    def is_host_link(pair: list[str]) -> bool:
        return any(end.split(":")[0] in hosts for end in pair)

    device_links = sorted(sorted(pair) for pair in f["links"] if not is_host_link(pair))
    assert device_links == sorted(
        sorted([f"{lk.a.device}:{lk.a.interface}", f"{lk.b.device}:{lk.b.interface}"]) for lk in c.manifest.links
    )
    host_links = sorted(sorted(pair) for pair in f["links"] if is_host_link(pair))
    derived = sorted(
        sorted([f"{p.name}-{side}:{PROBES[p.format].host.interface}", f"{e.device}:{e.interface}"])
        for p in c.manifest.probes
        for side, e in zip("ab", p.endpoints, strict=True)
    )
    assert host_links == derived
    assert len(f["links"]) == f["counts"]["links"]


@pytest.mark.parametrize("name", NAMES)
def test_the_mapping_rows_are_the_go_compilers_except_the_plans_shared_ports(name: str) -> None:
    c, f = compiled(name), facts(name)
    hosts, unmappable = hosts_of(c), unmappable_of(f)
    rows = {(r.device, r.interface): r for r in c.manifest.mapping}
    expected = [m for m in f["mapping"] if m["device"] not in hosts]
    assert set(rows) == {(m["device"], m["interface"]) for m in expected}
    for m in expected:
        row = rows[(m["device"], m["interface"])]
        assert row.enabled == m["enabled"]
        assert (row.disposition == "management") == m["mgmt_only"]
        if m["disposition"] == "omitted":
            want = "omitted" if f"{m['device']}:{m['interface']}" in unmappable else "uncabled"
        else:
            want = DISPOSITIONS[m["disposition"]]
        assert row.disposition == want, (m, row)
        assert (row.node_name is None) == (row.disposition == "omitted")
        assert (row.omission is not None) == (row.disposition == "omitted")
    assert [(r.device, r.interface) for r in c.manifest.mapping] == sorted(rows)


@pytest.mark.parametrize("name", NAMES)
def test_the_probes_and_the_fidelity_are_the_go_compilers(name: str) -> None:
    c, f = compiled(name), facts(name)
    assert [(p.name, p.format) for p in c.manifest.probes] == [(p["name"], p["format"]) for p in f["probes"]]
    for probe, fact in zip(c.manifest.probes, f["probes"], strict=True):
        for endpoint, host in zip(probe.endpoints, fact["hosts"], strict=True):
            assert (endpoint.device, endpoint.interface, endpoint.address, endpoint.gateway) == (
                host["device"], host["interface"], host["address"], host["gateway"]
            )
    assert {f"{o.device}:{o.interface}" for o in c.fidelity.omitted} == unmappable_of(f)
    assert all(o.omission in ("out_of_range", "no_rule") for o in c.fidelity.omitted)
    omitted = [(o.device, o.interface) for o in c.fidelity.omitted]
    assert omitted == sorted(omitted)
    assert list(c.fidelity.synthesized) == sorted(hosts_of(c))
    assert len(c.fidelity.synthesized) == f["counts"]["probe_hosts"]


@pytest.mark.parametrize("name", NAMES)
def test_the_manifest_is_a_valid_bundle_whose_id_is_the_files(name: str) -> None:
    c = compiled(name)
    assert bundle.validate(documents.encode(c.manifest)) == []
    assert c.files["manifest.json"] == bundle.manifest_bytes(c.manifest)
    assert set(c.files) == {"manifest.json", *(f"configs/{n.name}.cfg" for n in c.manifest.nodes)}
    assert c.id == bundle.bundle_id(c.files)
    assert c.findings == ()


def test_approximations_come_from_every_package_the_bundle_uses() -> None:
    fidelity = compiled("three-node-probed").fidelity
    assert [a.package for a in fidelity.approximations] == ["nokia_srlinux"] * 3 + ["ping"] * 4
    assert [a.text for a in fidelity.approximations[:3]] == list(PLATFORMS["nokia_srlinux"].fidelity.approximations)
    mixed = compiled("mixed").fidelity
    assert [a.package for a in mixed.approximations] == ["arista_eos"] * 4 + ["nokia_srlinux"] * 3


def test_compiling_is_deterministic() -> None:
    first, second = compiled("lossy"), compiled("lossy")
    assert first == second and first.id == second.id


PURE_IMPORTS = {"__future__", "re", "hashlib", "dataclasses", "functools", "collections.abc", "typing"}
MODEL_IMPORTS = {f"fylgja_core.{m}" for m in ("blueprint", "bundle", "deployment", "findings", "mapping",
                                              "platform_package", "probe_package")}


@pytest.mark.parametrize("module", ["compiler.py", "mapping.py"])
def test_the_compiler_is_pure(module: str) -> None:
    """Constitution V: no I/O, clock or environment. The imports say so."""
    imported = set()
    for node in ast.walk(ast.parse((SRC / module).read_text())):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            if node.module == "fylgja_core":
                imported |= {f"fylgja_core.{alias.name}" for alias in node.names}
            else:
                imported.add(node.module)
    assert imported <= PURE_IMPORTS | MODEL_IMPORTS, imported - (PURE_IMPORTS | MODEL_IMPORTS)


REJECTED_DIR = FACTS / "rejected"
# Every rejection fixture, and the (rule, object) pairs the compiler must report for it:
# exactly these, so a fixture with one fault yields one fault. several.json carries three.
REJECTED: dict[str, set[tuple[str, str]]] = {
    "platform-unsupported.json": {(compiler.RULE_PLATFORM, "e1")},
    "config-missing.json": {(compiler.RULE_CONFIG, "s1")},
    "interface-unmappable-linked-range.json": {(compiler.RULE_UNMAPPABLE_LINKED, "s1:ethernet-1/59")},
    "interface-unmappable-linked-no-rule.json": {(compiler.RULE_UNMAPPABLE_LINKED, "e1:Port-Channel1")},
    "probe-interface-unmappable.json": {(compiler.RULE_UNMAPPABLE_LINKED, "s1:ethernet-1/59")},
    "probe-format-unknown.json": {(compiler.RULE_PROBE_FORMAT, "s1-loop")},
    "probe-device-unknown.json": {(compiler.RULE_PROBE_DEVICE, "s1-loop/b")},
    "probe-interface-unknown.json": {(compiler.RULE_PROBE_INTERFACE, "s1-loop/b")},
    "probe-interface-cabled.json": {(compiler.RULE_PROBE_CABLED, "s1-loop/a")},
    "probe-interface-mgmt-only.json": {(compiler.RULE_PROBE_MGMT, "s1-loop/b")},
    "probe-port-taken.json": {(compiler.RULE_PROBE_TAKEN, "s1-loop2/a")},
    "probe-host-collision.json": {(compiler.RULE_PROBE_HOST, "s1-loop/a")},
    "network-empty.json": {(compiler.RULE_NETWORK_EMPTY, "network")},
    "probe-port-twice.json": {(compiler.RULE_PROBE_TAKEN, "s1-loop/b")},
    "several.json": {
        (compiler.RULE_PLATFORM, "e1"),
        (compiler.RULE_CONFIG, "s1"),
        (compiler.RULE_PROBE_DEVICE, "s1-loop/b"),
    },
}


@pytest.mark.parametrize("name", sorted(REJECTED))
def test_each_rejection_fixture_is_refused_for_its_fault_alone(name: str) -> None:
    bp = blueprint.load(REJECTED_DIR / name)
    with pytest.raises(compiler.Uncompilable) as caught:
        compiler.compile(bp, PLATFORMS, PROBES)
    found = caught.value.findings
    # The findings come ordered, so a list comparison also catches a fault filed twice.
    assert [(f.rule, f.object) for f in found] == sorted(REJECTED[name]), found
    for finding in found:
        assert finding.severity == "error"
        assert finding.message[0].isupper() and finding.message.endswith("."), finding.message


def test_every_rejection_fixture_has_a_row() -> None:
    assert {p.name for p in REJECTED_DIR.glob("*.json")} == set(REJECTED)


def test_a_refusal_names_what_is_loaded_and_what_links() -> None:
    bp = blueprint.load(REJECTED_DIR / "several.json")
    with pytest.raises(compiler.Uncompilable) as caught:
        compiler.compile(bp, PLATFORMS, PROBES)
    by_rule = {f.rule: f.message for f in caught.value.findings}
    assert "junos" in by_rule[compiler.RULE_PLATFORM] and "nokia_srlinux" in by_rule[compiler.RULE_PLATFORM]
    assert "s9" in by_rule[compiler.RULE_PROBE_DEVICE]
    bp = blueprint.load(REJECTED_DIR / "probe-interface-unmappable.json")
    with pytest.raises(compiler.Uncompilable) as caught:
        compiler.compile(bp, PLATFORMS, PROBES)
    (finding,) = caught.value.findings
    assert "59" in finding.message and "probe s1-loop endpoint b" in finding.message
    bp = blueprint.load(REJECTED_DIR / "probe-port-twice.json")
    with pytest.raises(compiler.Uncompilable) as caught:
        compiler.compile(bp, PLATFORMS, PROBES)
    (finding,) = caught.value.findings
    assert "two ports" in finding.message and "endpoint a" not in finding.message


def with_interface(name: str, device: int, interface: dict[str, Any]) -> blueprint.Blueprint:
    doc = json.loads((FIXTURES / f"{name}.json").read_text())
    interfaces = doc["network"]["devices"][device]["interfaces"]
    interfaces.append(interface)
    interfaces.sort(key=lambda i: str(i["name"]))
    return blueprint.decode(doc)


def test_an_unlinked_interface_no_rule_matches_is_omitted_not_refused() -> None:
    bp = with_interface("mixed", 0, {"name": "Port-Channel1", "mgmt_only": False, "enabled": True})
    c = compiler.compile(bp, PLATFORMS, PROBES)
    row = next(r for r in c.manifest.mapping if (r.device, r.interface) == ("e1", "Port-Channel1"))
    assert row == bundle.Row(device="e1", interface="Port-Channel1", enabled=True, disposition="omitted",
                             omission="no_rule")
    assert deployment.Omitted(device="e1", interface="Port-Channel1", omission="no_rule") in c.fidelity.omitted
    assert bundle.validate(documents.encode(c.manifest)) == []


def test_a_second_management_interface_is_omitted_and_said() -> None:
    bp = with_interface("mixed", 0, {"name": "Management2", "mgmt_only": True, "enabled": True})
    c = compiler.compile(bp, PLATFORMS, PROBES)
    rows = {r.interface: r for r in c.manifest.mapping if r.device == "e1"}
    assert rows["Management1"].disposition == "management" and rows["Management1"].node_name == "Management0"
    assert rows["Management2"] == bundle.Row(device="e1", interface="Management2", rule="management", enabled=True,
                                             disposition="omitted", omission="extra_management")
    assert deployment.Omitted(device="e1", interface="Management2", omission="extra_management") in c.fidelity.omitted
    assert bundle.validate(documents.encode(c.manifest)) == []
    assert deployment.validate(documents.encode(deployment_with(c.fidelity))) == []


def deployment_with(fidelity: deployment.CompileFidelity) -> deployment.Deployment:
    return deployment.Deployment(
        id="a" * 64, driver="containerlab", twin="t", allocation={"lab": "t"}, bundle_id="b" * 64,
        files=(deployment.File(path="topology.clab.yml", sha256="c" * 64),),
        demand=deployment.Demand(nodes=1, cpu=1.0, memory_mb=1),
        fidelity=deployment.Fidelity(forwarding="software", approximations=fidelity.approximations,
                                     omitted=fidelity.omitted, synthesized=fidelity.synthesized,
                                     lossy=deployment.Lossy(mappings=0, shared_ports=0)),
    )
