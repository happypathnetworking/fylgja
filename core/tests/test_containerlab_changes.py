"""The local driver's `changes` (D-049): pure, and comparing two rendered topologies into what the
runtime does to each node, with the reasons, and the links added and removed."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
import yaml

from fylgja_core import blueprint, compiler, platform_package, probe_package
from fylgja_core.containerlab import changes as clab_changes
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.driver import Changes, Planned

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "core" / "src" / "fylgja_core"
PLATFORMS = {
    p.id: p
    for p in map(platform_package.load, [ROOT / "psp/nokia_srlinux.yaml", ROOT / "psp/arista_eos.yaml",
                                         ROOT / "testdata/packages/chassisos.yaml"])
}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes/ping.yaml")]}
ALLOCATION = {"lab": "t", "mgmt_subnet": "172.20.3.0/24"}


def compiled(name: str) -> compiler.Compiled:
    return compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)


def planned(name: str, twin: str = "t") -> Planned:
    c = compiled(name)
    return clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, twin, {**ALLOCATION, "lab": twin})


def step(before: str, after: str) -> Changes:
    return clab_changes.changes(planned(before), planned(after), PLATFORMS, PROBES)


def actions(c: Changes) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {n.node: (n.action, n.reasons) for n in c.nodes}


def test_a_deployment_against_itself_keeps_every_node() -> None:
    c = step("three-node", "three-node")
    assert actions(c) == {"n1": ("kept", ()), "n2": ("kept", ()), "n3": ("kept", ())}
    assert c.links_added == () and c.links_removed == ()


@pytest.mark.parametrize("after", ["steps/three-node-n1-disabled", "three-node-unmanaged"])
def test_a_change_of_configuration_alone_keeps_every_node(after: str) -> None:
    c = step("three-node", after)
    assert actions(c) == {"n1": ("kept", ()), "n2": ("kept", ()), "n3": ("kept", ())}
    assert c.links_added == () and c.links_removed == ()


def test_a_link_removed_recables_its_two_nodes() -> None:
    c = step("three-node", "steps/three-node-unlinked")
    assert actions(c) == {"n1": ("kept", ()), "n2": ("recabled", ("links",)), "n3": ("recabled", ("links",))}
    assert c.links_added == ()
    assert c.links_removed == (("n2:ethernet-1/2", "n3:ethernet-1/1"),)


def test_the_link_added_back_recables_its_two_nodes() -> None:
    c = step("steps/three-node-unlinked", "three-node")
    assert actions(c) == {"n1": ("kept", ()), "n2": ("recabled", ("links",)), "n3": ("recabled", ("links",))}
    assert c.links_added == (("n2:ethernet-1/2", "n3:ethernet-1/1"),)
    assert c.links_removed == ()


def test_a_node_removed_with_its_links() -> None:
    c = step("three-node", "steps/two-node")
    assert actions(c) == {"n1": ("recabled", ("links",)), "n2": ("recabled", ("links",)), "n3": ("removed", ())}
    assert c.links_added == ()
    assert c.links_removed == (("n1:ethernet-1/2", "n3:ethernet-1/2"), ("n2:ethernet-1/2", "n3:ethernet-1/1"))


def test_a_kind_and_image_change_recreates_the_node() -> None:
    c = step("three-node", "steps/three-node-n3-eos")
    assert actions(c) == {"n1": ("recabled", ("links",)), "n2": ("recabled", ("links",)),
                          "n3": ("recreated", ("image", "kind", "links"))}
    assert c.links_added == (("n1:ethernet-1/2", "n3:eth2"), ("n2:ethernet-1/2", "n3:eth1"))
    assert c.links_removed == (("n1:ethernet-1/2", "n3:ethernet-1/2"), ("n2:ethernet-1/2", "n3:ethernet-1/1"))


def test_a_probe_added_adds_its_hosts_and_recables_its_node() -> None:
    c = step("three-node", "three-node-probed")
    assert actions(c) == {"n1": ("recabled", ("links",)), "n2": ("kept", ()), "n3": ("kept", ()),
                          "n1-loop-a": ("added", ()), "n1-loop-b": ("added", ())}
    assert c.links_added == (("n1-loop-a:eth1", "n1:ethernet-1/10"), ("n1-loop-b:eth1", "n1:ethernet-1/11"))
    assert c.links_removed == ()
    assert [n.node for n in c.nodes] == sorted(n.node for n in c.nodes)


def test_a_probe_moved_recreates_its_hosts() -> None:
    c = step("three-node-probed", "steps/three-node-probed-moved")
    assert actions(c) == {"n1": ("recabled", ("links",)), "n2": ("recabled", ("links",)), "n3": ("kept", ()),
                          "n1-loop-a": ("recreated", ("exec", "links")),
                          "n1-loop-b": ("recreated", ("exec", "links"))}
    assert c.links_added == (("n1-loop-a:eth1", "n2:ethernet-1/10"), ("n1-loop-b:eth1", "n2:ethernet-1/11"))
    assert c.links_removed == (("n1-loop-a:eth1", "n1:ethernet-1/10"), ("n1-loop-b:eth1", "n1:ethernet-1/11"))


def test_a_port_added_after_boot_to_a_kind_that_cannot_hot_add_recreates_the_node() -> None:
    c = step("mixed", "steps/mixed-e2-port")
    assert actions(c) == {"e1": ("recreated", ("hot_add", "links")), "e2": ("recreated", ("hot_add", "links")),
                          "s1": ("kept", ())}
    assert c.links_added == (("e1:eth10", "e2:eth10"),) and c.links_removed == ()


def mixed_without_e1_ethernet1() -> Planned:
    """`mixed` with its link on `e1:Ethernet1` (to `s1:ethernet-1/1`) removed, both ports uncabled."""
    c = compiled("mixed")
    link = next(k for k in c.manifest.links if (k.a.device, k.a.interface) == ("e1", "Ethernet1"))
    gone = {(link.a.device, link.a.interface), (link.b.device, link.b.interface)}
    manifest = dataclasses.replace(
        c.manifest,
        links=tuple(k for k in c.manifest.links if k != link),
        mapping=tuple(dataclasses.replace(r, disposition="uncabled") if (r.device, r.interface) in gone else r
                      for r in c.manifest.mapping))
    return clab_plan.plan(manifest, c.id, PLATFORMS, PROBES, "t", ALLOCATION)


def test_a_link_removed_on_ports_present_at_boot_recables() -> None:
    result = clab_changes.changes(planned("mixed"), mixed_without_e1_ethernet1(), PLATFORMS, PROBES)
    assert actions(result) == {"e1": ("recabled", ("links",)), "e2": ("kept", ()), "s1": ("recabled", ("links",))}
    assert result.links_added == () and result.links_removed == (("e1:eth1", "s1:ethernet-1/1"),)


def test_a_port_removed_and_re_added_counts_as_new_on_a_kind_that_cannot_hot_add() -> None:
    """The approximation: a port not in the deployment applied before stands for one not present
    at boot, so cEOS's `eth1`, at boot and removed in the step before, is recreated where the
    runtime would re-cable it live. The safe direction: a recreate covers a re-cable."""
    result = clab_changes.changes(mixed_without_e1_ethernet1(), planned("mixed"), PLATFORMS, PROBES)
    assert actions(result) == {"e1": ("recreated", ("hot_add", "links")), "e2": ("kept", ()),
                               "s1": ("recabled", ("links",))}
    assert result.links_added == (("e1:eth1", "s1:ethernet-1/1"),) and result.links_removed == ()


def test_a_link_change_under_restart_mode_restarts_the_node() -> None:
    restart = dataclasses.replace(
        PLATFORMS["chassisos"],
        runtime=platform_package.Runtime(containerlab=dataclasses.replace(
            PLATFORMS["chassisos"].runtime.containerlab, link_apply_mode="restart")))
    platforms = {**PLATFORMS, "chassisos": restart}
    c = compiled("lossy")
    link = c.manifest.links[0]
    gone = {(link.a.device, link.a.interface), (link.b.device, link.b.interface)}
    manifest = dataclasses.replace(
        c.manifest,
        links=c.manifest.links[1:],
        mapping=tuple(dataclasses.replace(r, disposition="uncabled") if (r.device, r.interface) in gone else r
                      for r in c.manifest.mapping))
    before = clab_plan.plan(c.manifest, c.id, platforms, PROBES, "t", ALLOCATION)
    after = clab_plan.plan(manifest, c.id, platforms, PROBES, "t", ALLOCATION)
    result = clab_changes.changes(before, after, platforms, PROBES)
    assert actions(result) == {"c1": ("restarted", ("links",)), "c2": ("kept", ()),
                               "s1": ("recabled", ("links",))}  # s1 is srlinux, live
    assert result.links_added == () and result.links_removed == (("c1:eth1", "s1:ethernet-1/1"),)


def test_two_deployments_of_different_twins_are_refused() -> None:
    with pytest.raises(ValueError, match="twin"):
        clab_changes.changes(planned("three-node", "a"), planned("three-node", "b"), PLATFORMS, PROBES)


def test_a_node_no_package_runs_is_refused() -> None:
    with pytest.raises(ValueError, match="no package given runs the node"):
        clab_changes.changes(planned("three-node"), planned("three-node"), {}, PROBES)


def test_endpoints_are_each_nodes_ports() -> None:
    topology = yaml.safe_load(planned("mixed").files[clab_plan.TOPOLOGY])
    assert clab_changes.endpoints(topology["topology"]) == {
        "e1": {"eth1", "eth2_1"}, "s1": {"ethernet-1/1", "ethernet-1/2"}, "e2": {"eth1", "eth3_1_1"}}


PURE_IMPORTS = {"__future__", "collections.abc", "typing", "yaml"}
MODEL_IMPORTS = {"fylgja_core.driver", "fylgja_core.platform_package", "fylgja_core.probe_package",
                 "fylgja_core.containerlab.plan"}


def test_changes_is_pure() -> None:
    """Constitution V: no I/O, clock or environment. The imports say so."""
    imported = set()
    for node in ast.walk(ast.parse((SRC / "containerlab" / "changes.py").read_text())):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            if node.module == "fylgja_core":
                imported |= {f"fylgja_core.{alias.name}" for alias in node.names}
            else:
                imported.add(node.module)
    assert imported <= PURE_IMPORTS | MODEL_IMPORTS, imported - (PURE_IMPORTS | MODEL_IMPORTS)

