"""The clabernetes driver's `changes` (D-049, D-057): pure, comparing the definitions two
Topologies wrap into what the cluster does to each pod. It answers every step fixture as the
local driver does, and so a changed link mode too: the pods of the nodes whose mode changed are
replaced, and no other, as the cluster was read to do."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
import yaml
from test_clabernetes_plan import ALLOCATION, LOCAL_ALLOCATION, PLATFORMS, PROBES, ROOT, SRC, imports
from test_diff import PAIRS as STEP_PAIRS

from fylgja_core import blueprint, clabernetes, compiler
from fylgja_core.clabernetes import changes as clabernetes_changes
from fylgja_core.clabernetes import plan as clabernetes_plan
from fylgja_core.containerlab import changes as clab_changes
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.driver import Changes, Planned
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage

Answer = tuple[str, tuple[str, ...]]
Links = tuple[tuple[str, str], ...]

KEPT: Answer = ("kept", ())
RECABLED: Answer = ("recabled", ("links",))
REPLACED: Answer = ("recreated", ("link_mode",))


def compiled(name: str) -> compiler.Compiled:
    return compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)


def planned(
    name: str, platforms: dict[str, PlatformPackage] = PLATFORMS, probes: dict[str, ProbePackage] = PROBES,
    twin: str = "t",
) -> Planned:
    """The fixture `name` planned on clabernetes for `twin`, on the documentation allocation."""
    c = compiled(name)
    allocation: dict[str, Any] = {**ALLOCATION, "namespace": clabernetes.namespace_of(twin)}
    return clabernetes_plan.plan(c.manifest, c.id, platforms, probes, twin, allocation)


def local(name: str, platforms: dict[str, PlatformPackage] = PLATFORMS) -> Planned:
    """The fixture `name` planned on the local driver."""
    c = compiled(name)
    return clab_plan.plan(c.manifest, c.id, platforms, PROBES, "t", LOCAL_ALLOCATION)


def step(before: str, after: str) -> Changes:
    return clabernetes_changes.changes(planned(before), planned(after), PLATFORMS, PROBES)


def actions(c: Changes) -> dict[str, Answer]:
    return {n.node: (n.action, n.reasons) for n in c.nodes}


def restart(package_id: str) -> dict[str, PlatformPackage]:
    """The packages, with `package_id`'s link mode `restart`."""
    package = PLATFORMS[package_id]
    containerlab = dataclasses.replace(package.runtime.containerlab, link_apply_mode="restart")
    runtime = dataclasses.replace(package.runtime, containerlab=containerlab)
    return {**PLATFORMS, package_id: dataclasses.replace(package, runtime=runtime)}


# The step fixtures (testdata/blueprint/steps/README.md), each pair's answer as the pods' uids are
# to hold it: before, after, each node's action and reasons, the links added and the links removed.
# The link tuples are test_containerlab_changes.py's: the two drivers name links alike.
N3_LINKS: Links = (("n1:ethernet-1/2", "n3:ethernet-1/2"), ("n2:ethernet-1/2", "n3:ethernet-1/1"))
PROBE_ON_N1: Links = (("n1-loop-a:eth1", "n1:ethernet-1/10"), ("n1-loop-b:eth1", "n1:ethernet-1/11"))
ROWS: list[tuple[str, str, dict[str, Answer], Links, Links]] = [
    ("three-node", "steps/three-node-unlinked", {"n1": KEPT, "n2": RECABLED, "n3": RECABLED},
     (), (("n2:ethernet-1/2", "n3:ethernet-1/1"),)),
    ("three-node", "steps/two-node", {"n1": RECABLED, "n2": RECABLED, "n3": ("removed", ())}, (), N3_LINKS),
    ("three-node", "steps/three-node-n3-eos",
     {"n1": RECABLED, "n2": RECABLED, "n3": ("recreated", ("image", "kind", "links"))},
     (("n1:ethernet-1/2", "n3:eth2"), ("n2:ethernet-1/2", "n3:eth1")), N3_LINKS),
    ("three-node", "steps/three-node-n1-disabled", {"n1": KEPT, "n2": KEPT, "n3": KEPT}, (), ()),
    ("three-node", "three-node-unmanaged", {"n1": KEPT, "n2": KEPT, "n3": KEPT}, (), ()),
    ("three-node", "three-node-probed",
     {"n1": RECABLED, "n2": KEPT, "n3": KEPT, "n1-loop-a": ("added", ()), "n1-loop-b": ("added", ())},
     PROBE_ON_N1, ()),
    ("mixed", "steps/mixed-e2-port",
     {"e1": ("recreated", ("hot_add", "links")), "e2": ("recreated", ("hot_add", "links")), "s1": KEPT},
     (("e1:eth10", "e2:eth10"),), ()),
    ("three-node-probed", "steps/three-node-probed-moved",
     {"n1": RECABLED, "n2": RECABLED, "n3": KEPT,
      "n1-loop-a": ("recreated", ("exec", "links")), "n1-loop-b": ("recreated", ("exec", "links"))},
     (("n1-loop-a:eth1", "n2:ethernet-1/10"), ("n1-loop-b:eth1", "n2:ethernet-1/11")), PROBE_ON_N1),
    # The moved probe removed: its hosts go, and `n2`, which they were cabled to, is recabled.
    ("steps/three-node-probed-moved", "three-node",
     {"n1": KEPT, "n2": RECABLED, "n3": KEPT, "n1-loop-a": ("removed", ()), "n1-loop-b": ("removed", ())},
     (), (("n1-loop-a:eth1", "n2:ethernet-1/10"), ("n1-loop-b:eth1", "n2:ethernet-1/11"))),
]
# Reversed, a pair swaps added and removed, and the rest stands but here: back to `mixed`, `e1` and
# `e2` lose a port, the ones they keep were there at boot, and they are recabled.
REVERSED: dict[tuple[str, str], dict[str, Answer]] = {
    ("mixed", "steps/mixed-e2-port"): {"e1": RECABLED, "e2": RECABLED, "s1": KEPT}}
SWAPPED = {"added": "removed", "removed": "added"}


@pytest.mark.parametrize(("before", "after", "nodes", "added", "removed"), ROWS,
                         ids=[f"{before}->{after}" for before, after, *_ in ROWS])
def test_each_step_fixture_pair_answers_as_the_table_says(
    before: str, after: str, nodes: dict[str, Answer], added: Links, removed: Links
) -> None:
    forward = step(before, after)
    assert actions(forward) == nodes
    assert (forward.links_added, forward.links_removed) == (added, removed)
    back = step(after, before)
    mirrored = {node: (SWAPPED.get(action, action), reasons) for node, (action, reasons) in nodes.items()}
    assert actions(back) == REVERSED.get((before, after), mirrored)
    assert (back.links_added, back.links_removed) == (removed, added)


# Every pair the README lists, as the bundle diff's tests hold them, and each reversed.
PAIRS = [(base, target) for base, target, *_ in STEP_PAIRS]


@pytest.mark.parametrize(("before", "after"), [*PAIRS, *((target, base) for base, target in PAIRS)])
def test_the_two_drivers_agree_on_every_pair_in_both_directions(before: str, after: str) -> None:
    # Both shipped kinds are `live`, so no pair changes a link mode; where one does, they answer alike too.
    theirs = clab_changes.changes(local(before), local(after), PLATFORMS, PROBES)
    assert step(before, after) == theirs


def test_a_deployment_against_itself_keeps_every_node() -> None:
    # `mixed`'s cEOS image is written under its registry's prefix, and its package found by it.
    c = step("mixed", "mixed")
    assert actions(c) == {"e1": KEPT, "e2": KEPT, "s1": KEPT}
    assert c.links_added == () and c.links_removed == ()


def test_a_link_change_under_restart_mode_restarts_the_pod() -> None:
    platforms = restart("chassisos")
    c = compiled("lossy")
    link = c.manifest.links[0]
    gone = {(link.a.device, link.a.interface), (link.b.device, link.b.interface)}
    manifest = dataclasses.replace(
        c.manifest,
        links=c.manifest.links[1:],
        mapping=tuple(dataclasses.replace(r, disposition="uncabled") if (r.device, r.interface) in gone else r
                      for r in c.manifest.mapping))
    before = clabernetes_plan.plan(c.manifest, c.id, platforms, PROBES, "t", ALLOCATION)
    after = clabernetes_plan.plan(manifest, c.id, platforms, PROBES, "t", ALLOCATION)
    result = clabernetes_changes.changes(before, after, platforms, PROBES)
    assert actions(result) == {"c1": ("restarted", ("links",)), "c2": KEPT, "s1": RECABLED}  # s1 is srlinux, live
    assert result.links_added == () and result.links_removed == (("c1:eth1", "s1:ethernet-1/1"),)


def test_a_link_mode_change_recreates_the_nodes_whose_mode_changed_and_no_other() -> None:
    srlinux = restart("nokia_srlinux")
    result = clabernetes_changes.changes(
        planned("three-node-probed"), planned("three-node-probed", srlinux), srlinux, PROBES)
    # The hosts, cabled to n1, keep their pods: their mode is not the SR Linux kind's.
    assert actions(result) == {"n1": REPLACED, "n2": REPLACED, "n3": REPLACED, "n1-loop-a": KEPT, "n1-loop-b": KEPT}
    assert result.links_added == () and result.links_removed == ()
    unlinked = clabernetes_changes.changes(
        planned("three-node"), planned("steps/three-node-unlinked", srlinux), srlinux, PROBES)
    assert actions(unlinked) == {"n1": REPLACED, "n2": ("recreated", ("link_mode", "links")),
                                 "n3": ("recreated", ("link_mode", "links"))}
    assert unlinked.links_added == () and unlinked.links_removed == (("n2:ethernet-1/2", "n3:ethernet-1/1"),)
    # `s1`'s own mode is unchanged, and it keeps its pod though it is cabled to `c1`, as locally.
    chassisos = restart("chassisos")
    ours = clabernetes_changes.changes(planned("lossy"), planned("lossy", chassisos), chassisos, PROBES)
    assert actions(ours) == {"c1": REPLACED, "c2": REPLACED, "s1": KEPT}
    theirs = clab_changes.changes(local("lossy"), local("lossy", chassisos), chassisos, PROBES)
    assert actions(ours) == actions(theirs)


def test_a_hosts_start_up_lines_alone_replace_its_pod() -> None:
    ping = PROBES["ping"]
    route = ("ip", "route", "replace", "{far_address}/32", "via", "{gateway}", "dev", "{interface}")
    probes = {"ping": dataclasses.replace(ping, host=dataclasses.replace(ping.host, route=route))}
    result = clabernetes_changes.changes(
        planned("three-node-probed"), planned("three-node-probed", probes=probes), PLATFORMS, probes)
    assert actions(result) == {"n1": KEPT, "n2": KEPT, "n3": KEPT,
                               "n1-loop-a": ("recreated", ("exec",)), "n1-loop-b": ("recreated", ("exec",))}
    assert result.links_added == () and result.links_removed == ()


def test_two_deployments_of_different_twins_are_refused() -> None:
    with pytest.raises(ValueError, match="twin"):
        clabernetes_changes.changes(planned("three-node", twin="a"), planned("three-node", twin="b"), PLATFORMS, PROBES)


def test_a_node_no_package_runs_is_refused() -> None:
    with pytest.raises(ValueError, match="no package given runs the node"):
        clabernetes_changes.changes(planned("three-node"), planned("three-node"), {}, PROBES)
    # A gated image is matched as the Topology writes it: the cEOS package with no pull secret
    # renders `ceos:4.32.0.2F`, and with one neither allocation holds renders none.
    mixed = planned("mixed")
    eos = PLATFORMS["arista_eos"]
    for secret in (None, "other"):
        containerlab = eos.runtime.containerlab
        image = dataclasses.replace(containerlab.image, pull_secret=secret)
        runtime = dataclasses.replace(eos.runtime, containerlab=dataclasses.replace(containerlab, image=image))
        platforms = {**PLATFORMS, "arista_eos": dataclasses.replace(eos, runtime=runtime)}
        with pytest.raises(ValueError, match="no package given runs the node e1"):
            clabernetes_changes.changes(mixed, mixed, platforms, PROBES)


def test_sections_of_finds_a_gated_node_by_the_registries_it_is_written_under() -> None:
    # The local driver's lookup, told how the Topology writes an image (D-057): `e1` runs cEOS
    # under the allocation's prefix, which no registries but the allocation's write.
    e1 = clabernetes_changes.wrapped(yaml.safe_load(planned("mixed").files["topology.yaml"]))["nodes"]["e1"]
    eos = PLATFORMS["arista_eos"].runtime.containerlab
    assert clabernetes_changes.sections_of("e1", e1, PLATFORMS, PROBES, [{}, ALLOCATION["registries"]]) == [eos]
    refused = r"no package given runs the node e1 \(ceos, registry\.example:5443/arista/ceos:4\.32\.0\.2F\)"
    unwritten: list[list[dict[str, str]]] = [[], [{}], [{"ARISTA_CEOS": "registry.example:5443/other"}]]
    for registries in unwritten:
        with pytest.raises(ValueError, match=refused):
            clabernetes_changes.sections_of("e1", e1, PLATFORMS, PROBES, registries)
    with pytest.raises(ValueError, match=refused):
        clab_changes.sections_of("e1", e1, PLATFORMS, PROBES)


def test_wrapped_is_the_definitions_topology() -> None:
    p = planned("mixed")
    topology = clabernetes_changes.wrapped(yaml.safe_load(p.files["topology.yaml"]))
    assert set(topology["nodes"]) == {"e1", "e2", "s1"}


PURE_IMPORTS = {"__future__", "collections.abc", "dataclasses", "typing", "yaml"}
MODEL_IMPORTS = {f"fylgja_core.{m}" for m in ("driver", "platform_package", "probe_package", "containerlab.changes",
                                              "clabernetes.plan")}


def test_changes_is_pure() -> None:
    """Constitution V: no I/O, clock or environment, held by the imports."""
    imported = imports((SRC / "clabernetes" / "changes.py").read_text())
    assert imported <= PURE_IMPORTS | MODEL_IMPORTS, imported - (PURE_IMPORTS | MODEL_IMPORTS)
