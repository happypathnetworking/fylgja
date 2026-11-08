"""The fake of the clabernetes driver's reach into Kubernetes, held to what the cluster answered
(verified-facts.md, "fylgja-core, phase 6: the driver's reach, over lightkube"): a Topology
settles to a pod and a Service per node, its generation moves with its spec alone, its pods
are Ready before it says so, a deleted pod comes back as another, a namespace deleted takes
everything in it, and a watch of pods begins with each pod there. Time is the fake's own, so
nothing here waits."""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import re
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest
import yaml
from aio import bounded, cancelled
from fake_kube import FakeKube, undecodable

from fylgja_core import blueprint, compiler, platform_package, probe_package
from fylgja_core.clabernetes import plan as clabernetes_plan
from fylgja_core.clabernetes.kube import NODE_LABEL, KubeFailed, Namespace, Pod, Service
from fylgja_core.driver import Exec

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = {
    p.id: p for p in map(platform_package.load, [ROOT / "psp/nokia_srlinux.yaml", ROOT / "psp/arista_eos.yaml"])}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes/ping.yaml")]}
NS = "fylgja-twin-t"
ALLOCATION = {"namespace": NS, "controller_namespace": "c9s", "pod_cidr": "10.244.0.0/16", "registries": {}}
TWINS = {"fylgja.owner": "core", "fylgja.twin": "t"}
OWNED = {"fylgja.owner": "core"}
SUFFIX = "bcdfghjklmnpqrstvwxz2456789"  # what Kubernetes draws a generated name's suffix from
POD = Pod(name="n1-x", namespace=NS, uid="uid-90", labels=TWINS, phase="Running", ready=True, deleting=False,
          created="2026-11-05T00:00:00+00:00", restarts=0, container_running=True)
"""A pod the test feeds the fake, made by no Topology."""


def documents(name: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The fixture `name` planned on clabernetes for the twin `t`: its Namespace, NetworkPolicy
    and Topology."""
    c = compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)
    files = clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", ALLOCATION).files
    namespace, policy, topology = (yaml.safe_load(files[path]) for path in (
        clabernetes_plan.NAMESPACE, clabernetes_plan.POLICY, clabernetes_plan.TOPOLOGY))
    return namespace, policy, topology


def created(fake: FakeKube, name: str = "three-node", settle: float | None = 0.0) -> dict[str, Any]:
    """The fixture `name` applied, then, unless `settle` is None, `settle` seconds of the fake's
    time; its Topology."""
    namespace, policy, topology = documents(name)

    async def run() -> None:
        for doc in (namespace, policy, topology):
            await fake.apply(doc)
        if settle is not None:
            await fake.sleep(settle)

    asyncio.run(run())
    return topology


def read(fake: FakeKube) -> tuple[list[Pod], list[Service], dict[str, Any] | None]:
    """The twin's pods, the namespace's Services and the Topology, as the driver reads them."""

    async def run() -> tuple[list[Pod], list[Service], dict[str, Any] | None]:
        topology = await fake.topology(NS, "t")
        return await fake.pods(NS, TWINS), await fake.services(NS), None if topology is None else dict(topology)

    return asyncio.run(run())


def status(fake: FakeKube) -> dict[str, Any]:
    topology = read(fake)[2]
    assert topology is not None
    found: dict[str, Any] = topology.get("status", {})
    return found


def sleep(fake: FakeKube, seconds: float) -> None:
    asyncio.run(fake.sleep(seconds))


def test_a_topology_applied_settles_to_a_ready_pod_per_node_and_a_cluster_service_per_device_node() -> None:
    fake = FakeKube()
    created(fake, "three-node-probed")
    pods, services, topology = read(fake)
    assert topology is not None
    assert topology["metadata"]["generation"] == 1
    assert topology["status"] == {"observedGeneration": 1, "topologyReady": True}
    nodes = ["n1", "n2", "n3", "n1-loop-a", "n1-loop-b"]
    assert {p.labels[NODE_LABEL]: p.uid for p in pods} == {node: f"uid-{k}" for k, node in enumerate(nodes, start=1)}
    for pod in pods:
        # Named as a Deployment's pods are: the node, its template's hash, a suffix of its own.
        assert re.fullmatch(rf"{re.escape(pod.labels[NODE_LABEL])}-[0-9a-f]{{9}}-[{SUFFIX}]{{5}}", pod.name)
        assert dict(pod.labels) == {**TWINS, NODE_LABEL: pod.labels[NODE_LABEL], "c9s.run/topologyOwner": "t"}
        assert (pod.namespace, pod.phase, pod.ready, pod.deleting, pod.restarts, pod.container_running) == (
            NS, "Running", True, False, 0, True)
    # A device's LoadBalancer, at the address of its first pod; a probe host has none, and every node
    # has its headless `-wire` Service, as on the cluster.
    assert services == sorted([
        *(Service(node, "LoadBalancer", "Cluster", f"192.0.2.{k}") for k, node in enumerate(nodes[:3], start=1)),
        *(Service(f"{node}-wire", "ClusterIP", None, None) for node in nodes),
    ], key=lambda s: s.name)


PULL_SECRET = "fylgja-pull-arista-ceos"


def test_a_topology_naming_a_pull_secret_its_namespace_lacks_gets_no_pod_and_never_reads_ready() -> None:
    # Read on the cluster: clabernetes resolves a Topology's pull secrets itself and makes no pod
    # while one is missing; its generation is observed, and it reads not ready.
    fake = FakeKube()
    namespace, policy, topology = documents("three-node")
    topology["spec"]["imagePull"] = {"pullSecrets": [PULL_SECRET]}

    async def run(*docs: dict[str, Any]) -> None:
        for doc in docs:
            await fake.apply(doc)
        await fake.sleep(100)

    asyncio.run(run(namespace, policy, topology))
    pods, services, held = read(fake)
    assert pods == [] and services == []
    assert held is not None and held["status"] == {"observedGeneration": 1, "topologyReady": False}
    # The Secret there, the same Topology gets its pods.
    fake = FakeKube()
    secret = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": PULL_SECRET, "namespace": NS},
              "type": "kubernetes.io/dockerconfigjson", "data": {".dockerconfigjson": "e30="}}
    asyncio.run(run(namespace, policy, secret, topology))
    pods, _, held = read(fake)
    assert len(pods) == 3 and all(pod.ready for pod in pods)
    assert held is not None and held["status"] == {"observedGeneration": 1, "topologyReady": True}


def test_a_load_balancer_withheld_has_no_address_until_its_time() -> None:
    fake = FakeKube()
    fake.address_s = {"n2": 50}
    created(fake)
    assert {s.name: s.address for s in read(fake)[1] if s.type == "LoadBalancer"} == {
        "n1": "192.0.2.1", "n2": None, "n3": "192.0.2.3"}
    sleep(fake, 50)
    assert {s.name: s.address for s in read(fake)[1] if s.type == "LoadBalancer"} == {
        "n1": "192.0.2.1", "n2": "192.0.2.2", "n3": "192.0.2.3"}


def test_the_applied_mappings_and_the_calls_are_recorded_as_given() -> None:
    fake = FakeKube()
    namespace, policy, topology = documents("three-node")
    created(fake)
    assert fake.objects == {("Namespace", None, NS): namespace, ("NetworkPolicy", NS, "fylgja-isolation"): policy,
                            ("Topology", NS, "t"): topology}
    assert fake.calls == [("apply", "Namespace", None, NS), ("apply", "NetworkPolicy", NS, "fylgja-isolation"),
                          ("apply", "Topology", NS, "t")]
    # The namespace carries the label Kubernetes sets on every namespace beside the applied ones.
    assert fake.namespaces[NS] == Namespace(NS, {**namespace["metadata"]["labels"],
                                                 "kubernetes.io/metadata.name": NS}, False)


def test_the_same_topology_again_and_an_annotation_alone_move_no_generation() -> None:
    fake = FakeKube()
    topology = created(fake)
    annotated = copy.deepcopy(topology)
    annotated["metadata"]["annotations"] = {"fylgja.recreate": "{}"}
    changed = copy.deepcopy(topology)
    changed["spec"]["expose"]["disableAutoExpose"] = False
    seen = []
    for doc in (topology, annotated, topology, changed):
        asyncio.run(fake.apply(doc))
        held = read(fake)[2]
        assert held is not None
        seen.append((held["metadata"]["generation"], held["metadata"].get("annotations")))
    assert seen == [(1, None), (1, {"fylgja.recreate": "{}"}), (1, None), (2, None)]


def test_a_changed_topology_is_observed_still_ready_from_before_and_the_next_pass_says_it_is_not() -> None:
    fake = FakeKube()
    topology = created(fake)
    fake.settle_s = 10.0
    changed = copy.deepcopy(topology)
    changed["spec"]["expose"]["disableAutoExpose"] = False
    asyncio.run(fake.apply(changed))
    # Until the controller's pass, the status is the one written for the generation before.
    assert status(fake) == {"observedGeneration": 1, "topologyReady": True}
    sleep(fake, 9.0)
    assert status(fake) == {"observedGeneration": 1, "topologyReady": True}
    # The pass that observes a generation writes it and keeps the readiness of the generation before;
    # the next says it is not ready, though no pod changed; the one after says it is.
    sleep(fake, 1.0)
    assert status(fake) == {"observedGeneration": 2, "topologyReady": True}
    sleep(fake, 10.0)
    assert status(fake) == {"observedGeneration": 2, "topologyReady": False}
    sleep(fake, 10.0)
    assert status(fake) == {"observedGeneration": 2, "topologyReady": True}


def test_the_pass_that_observes_a_generation_replaces_no_pod_and_the_next_does() -> None:
    fake = FakeKube()
    created(fake)
    before = fake.pod_of(NS, "n1").uid
    fake.replaces, fake.settle_s = {"n1"}, 10.0
    created(fake, "steps/three-node-unlinked", settle=10.0)
    assert status(fake) == {"observedGeneration": 2, "topologyReady": True}
    assert fake.pod_of(NS, "n1").uid == before
    sleep(fake, 10.0)
    assert status(fake) == {"observedGeneration": 2, "topologyReady": False}
    assert fake.pod_of(NS, "n1").uid != before


def test_pods_ready_after_50_s_keep_the_topology_not_ready_until_then() -> None:
    fake = FakeKube()
    fake.ready_s = 50.0
    created(fake, settle=None)
    topology = read(fake)[2]
    assert topology is not None and "status" not in topology  # none before the controller's first pass
    sleep(fake, 2.0)
    pods = read(fake)[0]
    assert pods and not any(p.ready for p in pods)
    assert status(fake) == {"observedGeneration": 1, "topologyReady": False}
    sleep(fake, 47.0)
    assert status(fake)["topologyReady"] is False
    sleep(fake, 1.0)
    assert fake.now == 50.0
    assert status(fake)["topologyReady"] is True
    assert all(p.ready for p in read(fake)[0])


def test_a_deleted_pod_is_replaced_at_once_and_the_topology_reads_ready_until_the_next_pass() -> None:
    fake = FakeKube()
    created(fake)
    fake.settle_s, fake.ready_s = 10.0, 30.0
    old = fake.pod_of(NS, "n1")
    asyncio.run(fake.delete_pod(NS, old.name))
    # The old pod is gone (terminate_s is 0); its replacement is there at once, another uid, Pending.
    n1 = [p for p in read(fake)[0] if p.labels[NODE_LABEL] == "n1"]
    assert [(p.uid != old.uid, p.phase, p.ready, p.deleting) for p in n1] == [(True, "Pending", False, False)]
    # The status is the controller's to write: straight after the deletion it still says ready.
    assert status(fake)["topologyReady"] is True
    sleep(fake, 10.0)
    assert status(fake)["topologyReady"] is False
    sleep(fake, 20.0)
    assert (fake.pod_of(NS, "n1").phase, fake.pod_of(NS, "n1").ready) == ("Running", True)
    assert status(fake)["topologyReady"] is False  # until the pass that follows its turning ready
    sleep(fake, 10.0)
    assert status(fake)["topologyReady"] is True
    # The node's Service is kept as it was made, its address with it.
    assert next(s for s in read(fake)[1] if s.name == "n1").address == "192.0.2.1"
    asyncio.run(fake.delete_pod(NS, old.name))  # one already gone is fine


def test_a_deleted_pod_stays_deleting_and_ready_beside_its_replacement_for_terminate_s() -> None:
    fake = FakeKube()
    created(fake)
    fake.terminate_s = 2.0
    old = fake.pod_of(NS, "n1")
    asyncio.run(fake.delete_pod(NS, old.name))
    n1 = [p for p in read(fake)[0] if p.labels[NODE_LABEL] == "n1"]
    assert sorted((p.uid == old.uid, p.deleting, p.ready, p.phase) for p in n1) == [
        (False, False, False, "Pending"), (True, True, True, "Running")]
    assert fake.pod_of(NS, "n1").uid != old.uid
    asyncio.run(fake.delete_pod(NS, old.name))  # one being deleted is deleted again, and nothing more comes
    sleep(fake, 1.0)
    assert len([p for p in read(fake)[0] if p.labels[NODE_LABEL] == "n1"]) == 2
    sleep(fake, 1.0)
    assert [p.uid for p in read(fake)[0] if p.labels[NODE_LABEL] == "n1"] == [fake.pod_of(NS, "n1").uid]


def test_a_namespace_deleted_is_deleting_until_30_s_and_then_gone_with_its_pods() -> None:
    fake = FakeKube()
    created(fake)
    fake.namespace_delete_s = 30.0
    asyncio.run(fake.delete_namespace(NS))
    assert fake.namespaces[NS].deleting
    sleep(fake, 29.0)
    assert fake.namespaces[NS].deleting and read(fake)[0]
    sleep(fake, 1.0)
    assert asyncio.run(fake.namespace(NS)) is None
    assert read(fake) == ([], [], None)
    assert not any(key[1] == NS or key[2] == NS for key in fake.objects)
    asyncio.run(fake.delete_namespace(NS))  # one already gone is fine


def test_an_object_applied_into_an_absent_or_a_deleting_namespace_is_refused() -> None:
    fake = FakeKube()
    namespace, policy, _ = documents("three-node")
    with pytest.raises(KubeFailed) as absent:
        asyncio.run(fake.apply(policy))
    assert absent.value.status == 404
    asyncio.run(fake.apply(namespace))
    fake.namespace_delete_s = 30.0
    asyncio.run(fake.delete_namespace(NS))
    with pytest.raises(KubeFailed) as deleting:
        asyncio.run(fake.apply(policy))
    assert deleting.value.status == 403
    assert ("NetworkPolicy", NS, "fylgja-isolation") not in fake.objects


def test_no_controller_settles_nothing() -> None:
    fake = FakeKube()
    fake.controller = False
    created(fake, settle=240.0)
    pods, services, topology = read(fake)
    assert (pods, services) == ([], [])
    assert topology is not None and "status" not in topology


def test_a_node_in_replaces_gets_a_new_pod_when_a_generation_is_observed_and_a_node_removed_goes() -> None:
    fake = FakeKube()
    created(fake)
    before = {node: fake.pod_of(NS, node).uid for node in ("n1", "n2", "n3")}
    fake.replaces = {"n1"}
    fake.terminate_s = 5.0
    created(fake, "steps/two-node")
    # The replaced pod and the removed node's go as a deleted pod does: deleting, then gone terminate_s later.
    pods = read(fake)[0]
    assert sorted((p.labels[NODE_LABEL], p.uid == before.get(p.labels[NODE_LABEL]), p.deleting) for p in pods) == [
        ("n1", False, False), ("n1", True, True), ("n2", True, False), ("n3", True, True)]
    sleep(fake, 5.0)
    pods, services, _ = read(fake)
    after = {p.labels[NODE_LABEL]: p.uid for p in pods}
    assert len(pods) == 2 and after.keys() == {"n1", "n2"}
    assert after["n1"] != before["n1"] and after["n2"] == before["n2"]
    assert {s.name for s in services} == {"n1", "n1-wire", "n2", "n2-wire"}
    # A pass that observes no new generation, as a deleted pod's replacement, replaces nothing.
    asyncio.run(fake.delete_pod(NS, fake.pod_of(NS, "n2").name))
    sleep(fake, 0.0)
    assert fake.pod_of(NS, "n1").uid == after["n1"]


def test_a_terminating_pod_stays_ready_beside_its_replacement_until_it_is_made_ready() -> None:
    fake = FakeKube()
    created(fake)
    old = fake.pod_of(NS, "n1")
    fake.terminate(NS, "n1")
    pods = [p for p in read(fake)[0] if p.labels[NODE_LABEL] == "n1"]
    assert sorted((p.uid == old.uid, p.deleting, p.ready, p.phase) for p in pods) == [
        (False, False, False, "Pending"), (True, True, True, "Running")]
    assert fake.pod_of(NS, "n1").uid != old.uid
    # Ready from before until the controller's next pass, a window a driver must not trust.
    assert status(fake)["topologyReady"] is True
    sleep(fake, 0.0)
    assert status(fake)["topologyReady"] is False
    fake.at(40.0, lambda: fake.set_ready(NS, "n1", True))
    sleep(fake, 40.0)
    assert (fake.pod_of(NS, "n1").ready, fake.pod_of(NS, "n1").phase) == (True, "Running")
    assert status(fake)["topologyReady"] is True


def test_a_container_restarted_in_place_is_down_in_its_running_pod_until_it_starts_and_counts_the_restart() -> None:
    # As read on the cluster: terminated at once, the phase still `Running`; the count moves when it starts.
    fake = FakeKube()
    created(fake)
    old = fake.pod_of(NS, "n1")
    assert old.container_running
    fake.restart(NS, "n1")
    down = fake.pod_of(NS, "n1")
    assert (down.uid, down.phase, down.ready, down.container_running, down.restarts) == (
        old.uid, "Running", False, False, 0)
    sleep(fake, 0.0)
    assert status(fake)["topologyReady"] is False
    fake.start(NS, "n1")
    up = fake.pod_of(NS, "n1")
    assert (up.uid, up.phase, up.container_running, up.restarts) == (old.uid, "Running", True, 1)
    sleep(fake, 0.0)
    assert fake.pod_of(NS, "n1").ready and status(fake)["topologyReady"] is True


def test_the_helpers_set_a_pods_phase_and_a_services_policy_and_a_patch_sets_it_back() -> None:
    fake = FakeKube()
    created(fake)
    fake.set_phase(NS, "n2", "Pending")
    fake.set_policy(NS, "n1", "Local")
    assert fake.pod_of(NS, "n2").phase == "Pending"
    asyncio.run(fake.patch_service(NS, "n2", {"spec": {"externalTrafficPolicy": "Local"}}))
    assert {s.name: s.traffic_policy for s in read(fake)[1] if s.type == "LoadBalancer"} == {
        "n1": "Local", "n2": "Local", "n3": "Cluster"}
    assert ("patch_service", NS, "n2", {"spec": {"externalTrafficPolicy": "Local"}}) in fake.calls
    with pytest.raises(KubeFailed) as absent:
        asyncio.run(fake.patch_service(NS, "nx", {"spec": {"externalTrafficPolicy": "Local"}}))
    assert absent.value.status == 404


def test_exec_answers_by_pod_and_an_absent_pod_is_a_404() -> None:
    fake = FakeKube()
    created(fake)
    n1, n2, n3 = (fake.pod_of(NS, node).name for node in ("n1", "n2", "n3"))
    fake.exec_answers[(NS, n2)] = Exec(7, "out\n", "err\n")
    fake.exec_answers[(NS, n3)] = KubeFailed(f"exec Pod {NS}/{n3}: 500 Internal Server Error", 500)
    assert asyncio.run(fake.exec(NS, n1, ["true"], 5.0)) == Exec(0, "", "")
    assert asyncio.run(fake.exec(NS, n2, ["sh", "-c", "exit 7"], 5.0)) == Exec(7, "out\n", "err\n")
    with pytest.raises(KubeFailed) as refused:
        asyncio.run(fake.exec(NS, n3, ["no-such-binary"], 5.0))
    assert refused.value.status == 500
    with pytest.raises(KubeFailed) as absent:
        asyncio.run(fake.exec(NS, "nx-9", ["true"], 5.0))
    assert absent.value.status == 404
    assert fake.calls[-4:] == [("exec", NS, n1, ("true",), 5.0), ("exec", NS, n2, ("sh", "-c", "exit 7"), 5.0),
                               ("exec", NS, n3, ("no-such-binary",), 5.0), ("exec", NS, "nx-9", ("true",), 5.0)]


def test_a_failure_set_for_a_call_is_raised_once_in_its_turn_and_the_call_is_recorded() -> None:
    fake = FakeKube()
    fake.fail["namespace"] = [None, RuntimeError("killed")]
    assert asyncio.run(fake.namespace(NS)) is None
    with pytest.raises(RuntimeError, match="killed"):
        asyncio.run(fake.namespace(NS))
    assert asyncio.run(fake.namespace(NS)) is None
    assert fake.calls == [("namespace", NS)] * 3


def test_a_watch_begins_with_each_pod_present_added_and_then_yields_each_change_as_it_comes() -> None:
    fake = FakeKube()
    created(fake)
    present = [fake.pod_of(NS, node) for node in ("n1", "n2", "n3")]
    old = present[0]

    async def run() -> list[tuple[str, str, str, bool, bool]]:
        seen = await watched(fake, fake.delete_pod(NS, old.name))
        return [(operation, pod.uid, pod.phase, pod.ready, pod.deleting) for operation, pod in seen]

    # As on the cluster: a watch begins with each pod there, ADDED; then the old pod reads deleting and
    # still Ready, its replacement comes Pending, the old one goes, and the replacement turns Ready.
    assert bounded(run) == [
        *[("ADDED", pod.uid, "Running", True, False) for pod in sorted(present, key=lambda p: p.name)],
        ("MODIFIED", old.uid, "Running", True, True),
        ("ADDED", "uid-4", "Pending", False, False),
        ("DELETED", old.uid, "Running", True, True),
        ("MODIFIED", "uid-4", "Running", True, False),
    ]


def test_a_watch_begins_with_the_pods_of_every_namespace_that_carry_its_labels_in_namespace_and_name_order() -> None:
    fake = FakeKube()
    for namespace, name, labels in [("fylgja-twin-u", "a", OWNED), (NS, "b", TWINS), (NS, "a", {}), (NS, "c", OWNED)]:
        fake.feed("ADDED", dataclasses.replace(POD, namespace=namespace, name=name, labels=labels))

    async def run() -> list[tuple[str, str, str]]:
        seen = await watched(fake, asyncio.sleep(0), labels=OWNED)
        return [(operation, pod.namespace, pod.name) for operation, pod in seen]

    assert bounded(run) == [("ADDED", NS, "b"), ("ADDED", NS, "c"), ("ADDED", "fylgja-twin-u", "a")]


def test_a_restarted_watch_delivers_every_pod_present_as_added_and_never_a_deletion_it_missed() -> None:
    fake = FakeKube()
    created(fake)
    old = fake.pod_of(NS, "n1")
    before = [("ADDED", fake.pod_of(NS, node).uid) for node in ("n1", "n2", "n3")]

    async def gap() -> None:
        fake.break_watch()
        await fake.delete_pod(NS, old.name)
        await fake.sleep(0)
        fake.restart_watch()

    async def run() -> list[tuple[str, str]]:
        return [(operation, pod.uid) for operation, pod in await watched(fake, gap())]

    seen = bounded(run)
    assert seen == before + [("ADDED", fake.pod_of(NS, node).uid) for node in ("n1", "n2", "n3")]
    assert fake.pod_of(NS, "n1").uid != old.uid


def test_a_change_fed_by_the_test_reaches_each_watch_as_given_and_is_what_the_fake_then_holds() -> None:
    fake = FakeKube()
    blinked = dataclasses.replace(POD, ready=False)

    async def run() -> list[tuple[str, Pod]]:
        async def feed() -> None:
            fake.feed("ADDED", POD)
            assert await fake.pods(NS, {}) == [POD]
            fake.feed("MODIFIED", blinked)
            assert await fake.pods(NS, {}) == [blinked]
            fake.feed("DELETED", blinked)
            assert await fake.pods(NS, {}) == []

        return await watched(fake, feed())

    assert bounded(run) == [("ADDED", POD), ("MODIFIED", blinked), ("DELETED", blinked)]


def test_a_failed_watch_raises_once_it_has_delivered_what_came_before_and_is_over() -> None:
    fake = FakeKube()
    created(fake)
    failure = RuntimeError("a line the watch cannot decode")

    async def run() -> list[str]:
        events = fake.watch_pods(TWINS)
        async with asyncio.timeout(5):
            seen = [(await anext(events))[0]]
            assert fake.watches == 1
            await fake.delete_pod(NS, fake.pod_of(NS, "n2").name)
            fake.fail_watch(failure)
            with pytest.raises(RuntimeError) as raised:
                while True:
                    seen.append((await anext(events))[0])
            assert raised.value is failure
            assert fake.watches == 0
            with pytest.raises(StopAsyncIteration):
                await anext(events)
        return seen

    # Two pods more of the first watch's start, then the deletion's three changes: delivered before the failure.
    assert bounded(run) == ["ADDED", "ADDED", "ADDED", "MODIFIED", "ADDED", "DELETED"]


def test_a_watch_failure_set_for_the_call_is_raised_at_its_start_and_opens_no_watch() -> None:
    # The failure a real watch raises at a first line lightkube cannot decode: the API's refusals it retries.
    fake = FakeKube()
    failure = undecodable()
    fake.fail["watch_pods"] = [failure]

    async def run() -> None:
        with pytest.raises(ValueError) as raised:
            await anext(fake.watch_pods(TWINS))
        assert raised.value is failure and type(failure).__name__ == "DecodeError"
        assert fake.watches == 0

    bounded(run)
    assert fake.calls == [("watch_pods", TWINS)]


async def watched(
    fake: FakeKube, step: Coroutine[Any, Any, None], labels: dict[str, str] = TWINS
) -> list[tuple[str, Pod]]:
    """What a watch of the pods carrying `labels`, iterated before `step`, delivers until `step` is
    done and the fake's time has moved on by nothing; it is then cancelled, and is over."""
    events = fake.watch_pods(labels)
    seen: list[tuple[str, Pod]] = []

    async def collect() -> None:
        async for event in events:
            seen.append(event)

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    assert fake.watches == 1
    await step
    await fake.sleep(0)
    await cancelled(task)
    assert fake.watches == 0
    return seen
