"""The driver seam's types (D-017, D-049) and the local driver's declared capabilities."""

from __future__ import annotations

import asyncio
import dataclasses
import types
import typing
from pathlib import Path

import fakes
import pytest

from fylgja_core import blueprint, compiler, containerlab, documents, platform_package, probe_package, schemas
from fylgja_core.bundle import Manifest
from fylgja_core.containerlab import changes as clab_changes
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.deployment import Deployment
from fylgja_core.driver import (
    Action,
    Capabilities,
    ChangeReason,
    Changes,
    DriverFailed,
    Exec,
    Inspection,
    NodeChange,
    NodeState,
    Planned,
    relinks,
    restarts,
    unsupported,
)

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = {p.id: p for p in map(platform_package.load, [ROOT / "psp/nokia_srlinux.yaml"])}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes/ping.yaml")]}
NO_MANIFEST = typing.cast(Manifest, None)  # the fake's admit never reads it


def test_the_local_drivers_capabilities_are_what_the_api_lists() -> None:
    doc = {"name": containerlab.NAME, "default": True, "capabilities": documents.encode(containerlab.CAPABILITIES)}
    assert list(schemas.api_validator("Driver").iter_errors(doc)) == []
    without = {**doc, "capabilities": {k: v for k, v in doc["capabilities"].items() if k != "isolation"}}
    assert not schemas.api_validator("Driver").is_valid(without)
    expected = Capabilities(nodes="provisions", relink=True, forwarding="software", access="direct", isolation="names")
    assert expected == containerlab.CAPABILITIES


def test_an_inspection_is_one_of_three_states_beside_the_nodes() -> None:
    assert typing.get_args(typing.get_type_hints(Inspection)["state"]) == ("absent", "present", "residue")
    assert [f.name for f in dataclasses.fields(Inspection)] == ["state", "nodes"]
    node = NodeState(name="n1", handle="clab-t-n1", incarnation="2026-11-03T12:00:00Z", address="172.20.1.2",
                     running=True)
    assert Inspection(state="present", nodes=(node,)).nodes == (node,)
    assert Inspection(state="residue", nodes=()).state == "residue"


def _changes(*nodes: tuple[str, Action], added: int = 0, removed: int = 0) -> Changes:
    return Changes(
        nodes=tuple(NodeChange(node=n, action=a, reasons=()) for n, a in nodes),
        links_added=tuple((f"a{i}:p", f"b{i}:p") for i in range(added)),
        links_removed=tuple((f"c{i}:p", f"d{i}:p") for i in range(removed)))


def test_restarts_names_the_nodes_restarted_or_recreated() -> None:
    c = _changes(("a", "kept"), ("b", "restarted"), ("c", "recreated"), ("d", "recabled"), ("e", "added"),
                 ("f", "removed"), ("g", "unsupported"))
    assert restarts(c) == ("b", "c")


def test_relinks_is_any_link_added_or_removed_or_any_node_recabled() -> None:
    assert not relinks(_changes(("a", "kept"), ("b", "restarted")))
    assert relinks(_changes(("a", "kept"), added=1))
    assert relinks(_changes(("a", "kept"), removed=1))
    assert relinks(_changes(("a", "recabled")))


def test_unsupported_names_the_nodes_the_runtime_cannot_satisfy() -> None:
    assert unsupported(_changes(("a", "unsupported"), ("b", "kept"), ("c", "unsupported"))) == ("a", "c")
    assert unsupported(_changes(("a", "kept"))) == ()


def test_a_node_change_has_its_action_and_reasons() -> None:
    assert typing.get_args(typing.get_type_hints(NodeChange)["action"]) == (
        "kept", "added", "removed", "recabled", "restarted", "recreated", "unsupported")
    assert typing.get_args(ChangeReason) == ("kind", "image", "link_mode", "exec", "links", "hot_add")
    assert NodeChange(node="n", action="kept", reasons=()) == NodeChange(node="n", action="kept", reasons=())


def _planned(*lines: str) -> Planned:
    files = {fakes.PLAN: ("\n".join(["lab t", "subnet 10.0.1.0/24", *lines]) + "\n").encode()}
    return Planned(deployment=typing.cast(Deployment, types.SimpleNamespace(twin="t")), files=files)


def test_the_fakes_changes_compare_two_renders() -> None:
    before = _planned("node a", "node b", "node c", "link a:1 b:1", "link b:2 c:1")
    after = _planned("node a", "node b", "node d", "link a:1 b:1", "link b:3 d:1")
    driver = fakes.FakeDriver()
    c = driver.changes(before, after, {}, {})
    assert [(n.node, n.action, n.reasons) for n in c.nodes] == [
        ("a", "kept", ()), ("b", "recabled", ("links",)), ("c", "removed", ()), ("d", "added", ())]
    assert c.links_added == (("b:3", "d:1"),) and c.links_removed == (("b:2", "c:1"),)
    driver.restarts, driver.recreates = {"b"}, {"b"}
    assert driver.changes(before, after, {}, {}).nodes[1].action == "restarted"
    driver.restarts = set()
    recreated = driver.changes(before, after, {}, {}).nodes[1]
    assert recreated == NodeChange(node="b", action="recreated", reasons=("links",))


def test_the_fake_declares_relink_unless_made_without_it() -> None:
    assert fakes.FakeDriver().capabilities().relink is True
    assert fakes.FakeDriver(relink=False).capabilities().relink is False


def test_the_fakes_changes_recreate_a_host_whose_address_moves_and_refuse_two_twins() -> None:
    before = _planned("node p-a", "node r1", "node r2", "link p-a:eth1 r1:e10", "host p-a 10.1.1.2/24")
    moved = _planned("node p-a", "node r1", "node r2", "link p-a:eth1 r2:e10", "host p-a 10.2.1.2/24")
    readdressed = _planned("node p-a", "node r1", "node r2", "link p-a:eth1 r1:e10", "host p-a 10.1.1.3/24")
    driver = fakes.FakeDriver()
    assert driver.changes(before, moved, {}, {}).nodes == (
        NodeChange(node="p-a", action="recreated", reasons=("exec", "links")),
        NodeChange(node="r1", action="recabled", reasons=("links",)),
        NodeChange(node="r2", action="recabled", reasons=("links",)))
    assert driver.changes(before, readdressed, {}, {}).nodes == (
        NodeChange(node="p-a", action="recreated", reasons=("exec",)),
        NodeChange(node="r1", action="kept", reasons=()), NodeChange(node="r2", action="kept", reasons=()))
    assert driver.calls == [("changes", "t")] * 2
    other = Planned(deployment=typing.cast(Deployment, types.SimpleNamespace(twin="u")), files=moved.files)
    with pytest.raises(ValueError, match="two twins"):
        driver.changes(before, other, {}, {})


@pytest.mark.parametrize(("before", "after"), [
    ("three-node", "three-node-probed"), ("three-node-probed", "three-node"),
    ("three-node-probed", "steps/three-node-probed-moved"), ("steps/three-node-probed-moved", "three-node-probed")])
def test_the_fakes_changes_answer_a_probe_step_as_the_local_driver_does(before: str, after: str) -> None:
    allocation = {"lab": "t", "mgmt_subnet": "10.0.1.0/24"}
    fake = fakes.FakeDriver()

    def plans(name: str) -> tuple[Planned, Planned]:
        c = compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)
        return (fake.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", allocation),
                clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", allocation))

    (fake_before, clab_before), (fake_after, clab_after) = plans(before), plans(after)
    local = clab_changes.changes(clab_before, clab_after, PLATFORMS, PROBES)
    assert fake.changes(fake_before, fake_after, PLATFORMS, PROBES).nodes == local.nodes


def test_the_fakes_admit_with_the_held_deployment_answers_its_allocation_and_can_be_killed_after_it() -> None:
    held = typing.cast(Deployment, types.SimpleNamespace(allocation={"lab": "t", "mgmt_subnet": "10.0.7.0/24"}))
    driver = fakes.FakeDriver()
    reserved = [{"lab": "u", "mgmt_subnet": "10.0.1.0/24"}]
    assert asyncio.run(driver.admit(NO_MANIFEST, {}, {}, "t", reserved, held=held)) == held.allocation
    driver.fail_after = "admit"
    with pytest.raises(RuntimeError, match="killed"):
        asyncio.run(driver.admit(NO_MANIFEST, {}, {}, "t", reserved, held=held))
    assert driver.fail_after is None
    assert driver.calls == [("admit", "t", "held")] * 2


def _lab(twin: str, *lines: str) -> tuple[fakes.FakeDriver, Deployment, dict[str, bytes]]:
    driver = fakes.FakeDriver()
    files = {fakes.PLAN: ("\n".join(["lab t", "subnet 10.0.1.0/24", *lines]) + "\n").encode()}
    dep = typing.cast(Deployment, types.SimpleNamespace(twin=twin, allocation={"mgmt_subnet": "10.0.1.0/24"}))
    asyncio.run(driver.apply(dep, files, {}, {}))
    return driver, dep, files


def test_the_fakes_exec_answers_a_host_with_its_address_and_records_the_call() -> None:
    driver, _, _ = _lab("t", "node r1", "node p-a", "host p-a 10.1.1.2/24")
    host = asyncio.run(driver.exec("t", "p-a", ["ip", "addr"], 5.0))
    assert host == Exec(0, "2: eth1    inet 10.1.1.2/24 scope global eth1\n", "")
    assert asyncio.run(driver.exec("t", "r1", ["true"], 5.0)) == Exec(0, "", "")
    assert driver.calls[-2:] == [("exec", "t", "p-a", "ip", "addr"), ("exec", "t", "r1", "true")]


def test_the_fakes_exec_answers_what_a_test_sets_and_fails_when_unreachable_or_absent() -> None:
    driver, _, _ = _lab("t", "node r1", "node p-a", "node p-b", "host p-a 10.1.1.2/24")
    driver.exec_answers[("t", "p-a")] = Exec(1, "", "no route")
    assert asyncio.run(driver.exec("t", "p-a", ["ping"], 5.0)) == Exec(1, "", "no route")
    driver.unreachable_exec.add(("t", "r1"))
    with pytest.raises(DriverFailed):
        asyncio.run(driver.exec("t", "r1", ["true"], 5.0))
    with pytest.raises(DriverFailed):
        asyncio.run(driver.exec("t", "nope", ["true"], 5.0))
    driver.labs["t"]["p-b"] = dataclasses.replace(driver.labs["t"]["p-b"], running=False)
    with pytest.raises(DriverFailed):
        asyncio.run(driver.exec("t", "p-b", ["true"], 5.0))


def test_the_fakes_exec_can_be_blocked_until_cancelled() -> None:
    driver, _, _ = _lab("t", "node p-a", "host p-a 10.1.1.2/24")
    driver.block = "exec"

    async def bounded() -> None:
        await asyncio.wait_for(driver.exec("t", "p-a", ["true"], 5.0), timeout=0.05)

    with pytest.raises(TimeoutError):
        asyncio.run(bounded())
    assert driver.calls[-1] == ("exec", "t", "p-a", "true")
