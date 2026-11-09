"""The driver seam's types (D-017, D-049) and each driver's declared capabilities."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import types
import typing
from pathlib import Path

import fakes
import pytest

from fylgja_core import (
    blueprint,
    clabernetes,
    compiler,
    containerlab,
    documents,
    platform_package,
    probe_package,
    schemas,
)
from fylgja_core.bundle import Manifest
from fylgja_core.capacity import NOTHING, Host, Reading, Resources
from fylgja_core.clabernetes import plan as clabernetes_plan
from fylgja_core.clabernetes.driver import ClabernetesDriver
from fylgja_core.containerlab import changes as clab_changes
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.containerlab.driver import ContainerlabDriver
from fylgja_core.deployment import Deployment
from fylgja_core.driver import (
    Action,
    Capabilities,
    ChangeReason,
    Changes,
    Driver,
    DriverFailed,
    Exec,
    Inspection,
    NodeChange,
    NodeState,
    Planned,
    check_files,
    events_backoff,
    relinks,
    restarts,
    unsupported,
)

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = {p.id: p for p in map(platform_package.load, [ROOT / "psp/nokia_srlinux.yaml"])}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes/ping.yaml")]}
NO_MANIFEST = typing.cast(Manifest, types.SimpleNamespace(nodes=(), probes=()))  # the fake's admit reads its nodes


CALLS = {"capabilities", "admit", "plan", "changes", "apply", "inspect", "destroy", "endpoints", "exec", "events",
         "capacity"}


def test_the_seam_has_eleven_calls() -> None:
    declared = {name for name, value in vars(Driver).items() if callable(value) and not name.startswith("_")}
    assert declared == CALLS
    for driver in (fakes.FakeDriver, ContainerlabDriver, ClabernetesDriver):
        assert all(callable(getattr(driver, call, None)) for call in CALLS), driver.__name__


def test_the_fake_reads_its_room() -> None:
    room = Resources(8.0, 16384)
    assert asyncio.run(fakes.FakeDriver().capacity([])) == Reading((Host("fake", room, room),), NOTHING)
    driver, _, _ = _lab("t", "node r1", "node r2", "node r3")
    reserved = [{"lab": "u", "mgmt_subnet": "10.0.2.0/24", "demand": {"nodes": 2, "cpu": 1.0, "memory_mb": 4096}}]
    assert asyncio.run(driver.capacity(reserved)) == Reading((Host("fake", room, Resources(6.5, 10240)),), NOTHING)
    assert driver.calls[-1] == ("capacity",)
    driver.fail_capacity = True
    with pytest.raises(DriverFailed):
        asyncio.run(driver.capacity([]))


def test_every_drivers_capacity_takes_the_reserved_allocations() -> None:
    # What `admit` would take now for a twin whose other twins' allocations are `reserved`: the caller names them.
    for driver in (Driver, fakes.FakeDriver, ContainerlabDriver, ClabernetesDriver):
        assert list(inspect.signature(driver.capacity).parameters) == ["self", "reserved"], driver.__name__


def test_the_events_backoff_doubles_from_one_second_to_a_minute() -> None:
    assert events_backoff(None) == 1.0
    assert events_backoff(1.0) == 2.0
    assert events_backoff(60.0) == 60.0


def test_the_fake_yields_each_name_it_was_given_until_cancelled() -> None:
    driver = fakes.FakeDriver()

    async def first() -> None:
        driver.emit("a")
        driver.emit("b")
        names = driver.events()
        assert [await anext(names), await anext(names)] == ["a", "b"]
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(anext(names), timeout=0.05)

    async def second() -> None:  # one fake serves a second event loop: a stopped reconciler starts on another
        names = driver.events()
        waiting = asyncio.ensure_future(anext(names))
        await asyncio.sleep(0.01)
        driver.emit("c")
        assert await asyncio.wait_for(waiting, timeout=1.0) == "c"

    asyncio.run(first())
    asyncio.run(second())


def test_the_local_drivers_capabilities_are_what_the_api_lists() -> None:
    doc = {"name": containerlab.NAME, "default": True, "capabilities": documents.encode(containerlab.CAPABILITIES)}
    assert list(schemas.api_validator("Driver").iter_errors(doc)) == []
    for member in ("isolation", "reapply"):
        without = {**doc, "capabilities": {k: v for k, v in doc["capabilities"].items() if k != member}}
        assert not schemas.api_validator("Driver").is_valid(without), member
    expected = Capabilities(nodes="provisions", relink=True, forwarding="software", access="direct", isolation="names",
                            reapply=False)
    assert expected == containerlab.CAPABILITIES


def test_the_clabernetes_drivers_capabilities_are_what_the_api_lists() -> None:
    doc = {"name": clabernetes.NAME, "default": False, "capabilities": documents.encode(clabernetes.CAPABILITIES)}
    assert list(schemas.api_validator("Driver").iter_errors(doc)) == []
    for member in ("isolation", "reapply"):
        without = {**doc, "capabilities": {k: v for k, v in doc["capabilities"].items() if k != member}}
        assert not schemas.api_validator("Driver").is_valid(without), member
    expected = Capabilities(
        nodes="provisions", relink=True, forwarding="software", access="direct", isolation="network", reapply=True)
    assert expected == clabernetes.CAPABILITIES


def test_a_driver_declares_whether_applying_again_finishes_an_apply_cut_short() -> None:
    with pytest.raises(TypeError, match="reapply"):  # no default: every driver declares it (D-068)
        Capabilities(  # type: ignore[call-arg]
            nodes="provisions", relink=True, forwarding="software", access="direct", isolation="names")
    assert containerlab.CAPABILITIES.reapply is False  # a plain redeploy of a partial lab fixes nothing (D-023)
    assert clabernetes.CAPABILITIES.reapply is True


def test_check_files_passes_the_deployments_own_and_refuses_a_missing_an_extra_or_a_changed_file() -> None:
    c = compiler.compile(blueprint.load(ROOT / "testdata/blueprint/three-node.json"), PLATFORMS, PROBES)
    allocation = {"namespace": "fylgja-twin-t", "controller_namespace": "c9s", "pod_cidr": "10.244.0.0/16",
                  "registries": {}}
    planned = clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", allocation)
    deployment, files = planned.deployment, dict(planned.files)
    check_files(deployment, files)
    missing = {path: data for path, data in files.items() if path != "topology.yaml"}
    refused = (r"the files \['namespace\.yaml', 'networkpolicy\.yaml'\] are not the deployment's "
               r"\['namespace\.yaml', 'networkpolicy\.yaml', 'topology\.yaml'\]")
    with pytest.raises(ValueError, match=refused):
        check_files(deployment, missing)
    with pytest.raises(ValueError, match=r"the files \[.*'extra\.yaml'.*\] are not the deployment's"):
        check_files(deployment, {**files, "extra.yaml": b""})
    with pytest.raises(ValueError, match=rf"topology\.yaml is not the deployment's: its SHA-256 differs from the "
                                         rf"one {deployment.id} lists"):
        check_files(deployment, {**files, "topology.yaml": files["topology.yaml"] + b"\n"})


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


def test_the_fake_declares_no_reapply_unless_made_with_it() -> None:
    assert fakes.FakeDriver().capabilities().reapply is False
    assert fakes.FakeDriver(reapply=True).capabilities().reapply is True


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
    assert asyncio.run(driver.admit(NO_MANIFEST, {}, {}, "t", reserved, held=held)) == {
        **held.allocation, "demand": {"nodes": 0, "cpu": 0.0, "memory_mb": 0}}
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
