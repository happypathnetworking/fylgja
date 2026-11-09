"""The clabernetes driver's reach into Kubernetes on the k3s cluster (D-057, D-064): every call of
`LightKube` on the twin `kube-k8s`, `steps/two-node.json` compiled with the shipped packages and
planned by `clabernetes.plan.plan` on an allocation of the site, its three files applied through
`LightKube` alone. The allocation holds no registry, whatever pull credential the environment
holds: the module makes no Secret, and a Topology naming a pull secret no Secret backs gets no
pod (verified-facts.md). The driver's own tests make the Secrets through its `apply`.

The tests run in order and share the twin; each asserts what it read and prints it with its time
(`-s`), and design/verified-facts.md records the readings. The module deletes the twin's
namespace at its end, whatever happened, and waits for it to go. Nothing of the site is printed:
no address, host or CIDR.
"""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from cluster.conftest import POLL_S, Site, run, say, until
from fylgja_core import blueprint, compiler, packages
from fylgja_core.clabernetes import OWNER, OWNER_LABEL, TWIN_LABEL, namespace_of
from fylgja_core.clabernetes import plan as clabernetes_plan
from fylgja_core.clabernetes.kube import NODE_LABEL, KubeFailed, LightKube, Pod
from fylgja_core.driver import Exec
from fylgja_core.kubeapi import REQUEST_TIMEOUT_S

ROOT = Path(__file__).resolve().parents[3]
TWIN = "kube-k8s"
NAMESPACE = namespace_of(TWIN)
LABELS = {OWNER_LABEL: OWNER, TWIN_LABEL: TWIN}
NODES = ["n1", "n2"]
RECREATE = "fylgja.recreate"  # the annotation the driver's hot-add recreate writes (D-057)
SETTLE_S = 300.0
GONE_S = 120.0


@dataclass
class Twin:
    """What the tests share: the three objects the plan rendered, and the pods read once they ran."""

    objects: dict[str, dict[str, Any]]
    pods: dict[str, Pod] = field(default_factory=dict)

    @property
    def topology(self) -> dict[str, Any]:
        return self.objects[clabernetes_plan.TOPOLOGY]

    @property
    def name(self) -> str:
        """The Topology's name."""
        name: str = self.topology["metadata"]["name"]
        return name


@pytest.fixture(scope="module")
def twin(site: Site, loop: asyncio.Runner, kube: LightKube) -> Iterator[Twin]:
    loaded = packages.load([ROOT / "psp", ROOT / "probes"])
    c = compiler.compile(blueprint.load(ROOT / "testdata/blueprint/steps/two-node.json"), loaded.platforms,
                         loaded.probes)
    allocation = {"namespace": NAMESPACE, "controller_namespace": site.controller_namespace,
                  "pod_cidr": site.pod_cidr, "registries": {}}
    planned = clabernetes_plan.plan(c.manifest, c.id, loaded.platforms, loaded.probes, TWIN, allocation)
    paths = (clabernetes_plan.NAMESPACE, clabernetes_plan.POLICY, clabernetes_plan.TOPOLOGY)
    try:
        yield Twin({path: yaml.safe_load(planned.files[path]) for path in paths})
    finally:
        run(loop, kube.delete_namespace(NAMESPACE), f"delete_namespace {NAMESPACE} (the module's end)")
        until(loop, lambda: kube.namespace(NAMESPACE), lambda found: found is None, GONE_S + 60,
              f"{NAMESPACE} gone (the module's end)")


def test_the_namespace_the_policy_and_the_topology_apply_and_apply_again(
    twin: Twin, loop: asyncio.Runner, kube: LightKube
) -> None:
    assert run(loop, kube.namespace(NAMESPACE), "namespace, absent") is None
    for attempt in ("apply", "apply again"):
        run(loop, kube.apply(twin.objects[clabernetes_plan.NAMESPACE]), f"{attempt} {clabernetes_plan.NAMESPACE}")
    namespace = run(loop, kube.namespace(NAMESPACE), "namespace")
    assert namespace is not None and namespace.name == NAMESPACE and not namespace.deleting
    assert LABELS.items() <= namespace.labels.items()
    say(f"namespace labels: {sorted(namespace.labels)}")
    run(loop, kube.apply(twin.objects[clabernetes_plan.POLICY]), f"apply {clabernetes_plan.POLICY}")
    for attempt in ("apply", "apply again"):
        run(loop, kube.apply(twin.topology), f"{attempt} {clabernetes_plan.TOPOLOGY}")
    topology = run(loop, kube.topology(NAMESPACE, twin.name), "topology")
    assert topology is not None and topology["metadata"]["generation"] == 1
    say(f"topology status keys: {sorted(topology.get('status') or {})}")


def test_the_topology_observes_its_generation_and_its_pods_and_itself_turn_ready(
    twin: Twin, loop: asyncio.Runner, kube: LightKube
) -> None:
    start = time.monotonic()
    seen: dict[str, float] = {}
    while True:
        topology = loop.run(kube.topology(NAMESPACE, twin.name))
        pods = loop.run(kube.pods(NAMESPACE, LABELS))
        assert topology is not None
        status = topology.get("status") or {}
        moments = {
            "observedGeneration == generation": status.get("observedGeneration") == topology["metadata"]["generation"],
            "both pods ready": sorted(p.labels.get(NODE_LABEL, "") for p in pods if p.ready) == NODES,
            "topologyReady": status.get("topologyReady") is True,
        }
        for what, holds in moments.items():
            if holds and what not in seen:
                seen[what] = time.monotonic() - start
                say(f"{what}: {seen[what]:.1f} s after the apply's last read")
        if len(seen) == len(moments):
            break
        if "observedGeneration" not in status and {"both pods ready", "topologyReady"} <= seen.keys():
            pytest.fail(f"the Topology's status holds no observedGeneration, and D-057's wait rests on it: {status}")
        if time.monotonic() - start > SETTLE_S:
            pytest.fail(f"the twin did not settle within {SETTLE_S:g} s: {sorted(seen)}; status {status}")
        time.sleep(POLL_S)
    say(f"topology status keys: {sorted(status)}")


def test_nodes_and_every_pod_are_read_with_allocatable_and_requests(
    twin: Twin, loop: asyncio.Runner, kube: LightKube, site: Site
) -> None:
    nodes = run(loop, kube.nodes(), "nodes")
    assert len(nodes) == 3
    for node in nodes:
        assert node.allocatable.cpu == 8.0 and 20000 < node.allocatable.memory_mb < 25000
    pods = run(loop, kube.all_pods(), "all_pods")
    say(f"{len(nodes)} nodes, {len(pods)} pods, requests of {sum(p.requests.cpu for p in pods):g} CPU in all")
    assert any(p.namespace == site.controller_namespace and p.requests.cpu > 0 for p in pods)
    listed = {n.name for n in nodes}
    unlisted = sum(1 for p in pods if p.host and p.host not in listed)  # a count: a failure names no host
    assert unlisted == 0, f"{unlisted} pods are bound to a host the nodes do not list"
    assert not [p.name for p in pods if p.namespace == NAMESPACE and p.ended]


def test_the_twins_pods_run_and_each_node_has_a_load_balancer_whose_policy_patches_to_local(
    twin: Twin, loop: asyncio.Runner, kube: LightKube
) -> None:
    pods = run(loop, kube.pods(NAMESPACE, LABELS), "pods")
    assert sorted(p.labels.get(NODE_LABEL, "") for p in pods) == NODES
    assert all(p.phase == "Running" and p.namespace == NAMESPACE and not p.deleting for p in pods)
    twin.pods = {p.labels[NODE_LABEL]: p for p in pods}
    for p in pods:
        say(f"pod {p.name}: node {p.labels[NODE_LABEL]}, uid {p.uid}, restarts {p.restarts}, created {p.created}")
    async def unaddressed() -> list[str]:
        """The LoadBalancers with no address yet, by name: a failure prints names, never an address."""
        return [s.name for s in await kube.services(NAMESPACE) if s.type == "LoadBalancer" and not s.address]

    until(loop, unaddressed, lambda names: not names, 60.0, "every LoadBalancer has an address")
    services = run(loop, kube.services(NAMESPACE), "services")
    for s in services:
        say(f"service {s.name}: {s.type}, policy {s.traffic_policy}, address {'held' if s.address else 'none'}")
    balancers = [s for s in services if s.type == "LoadBalancer"]
    assert [s.name for s in balancers] == NODES
    assert all(s.address and s.traffic_policy == "Cluster" for s in balancers)
    run(loop, kube.patch_service(NAMESPACE, "n1", {"spec": {"externalTrafficPolicy": "Local"}}), "patch_service n1")
    after = {s.name: s for s in run(loop, kube.services(NAMESPACE), "services")}
    assert (after["n1"].traffic_policy, after["n2"].traffic_policy) == ("Local", "Cluster")


def test_an_annotation_applied_and_then_left_out_comes_and_goes_at_the_same_generation(
    twin: Twin, loop: asyncio.Runner, kube: LightKube
) -> None:
    annotated = copy.deepcopy(twin.topology)
    annotated["metadata"].setdefault("annotations", {})[RECREATE] = "{}"
    run(loop, kube.apply(annotated), f"apply {clabernetes_plan.TOPOLOGY} with {RECREATE}")
    held = run(loop, kube.topology(NAMESPACE, twin.name), "topology")
    assert held is not None
    assert (held["metadata"].get("annotations") or {}).get(RECREATE) == "{}"
    assert held["metadata"]["generation"] == 1
    run(loop, kube.apply(twin.topology), f"apply {clabernetes_plan.TOPOLOGY} as rendered")
    held = run(loop, kube.topology(NAMESPACE, twin.name), "topology")
    assert held is not None
    assert RECREATE not in (held["metadata"].get("annotations") or {})
    assert held["metadata"]["generation"] == 1
    say(f"annotations left: {sorted(held['metadata'].get('annotations') or {})}")


def test_exec_answers_a_status_and_both_streams_and_fails_where_it_has_none(
    twin: Twin, loop: asyncio.Runner, kube: LightKube
) -> None:
    pod = twin.pods["n1"].name
    answered = run(loop, kube.exec(NAMESPACE, pod, ["sh", "-c", "echo out; echo err >&2; exit 7"], 10.0),
                   "exec of an exit 7")
    assert answered == Exec(7, "out\n", "err\n")

    start = time.monotonic()
    with pytest.raises(KubeFailed) as slept:
        run(loop, kube.exec(NAMESPACE, pod, ["sleep", "30"], 3.0), "exec of sleep 30 within 3 s")
    assert slept.value.status is None and time.monotonic() - start < 6.0
    say(f"budget run out: {slept.value}")

    with pytest.raises(KubeFailed) as lacking:
        run(loop, kube.exec(NAMESPACE, pod, ["no-such-binary"], 10.0), "exec of a binary the node lacks")
    assert lacking.value.status == 500
    say(f"a binary the node lacks: {lacking.value}")

    with pytest.raises(KubeFailed) as absent:
        run(loop, kube.exec(NAMESPACE, "no-such-pod", ["true"], 10.0), "exec in a pod that does not exist")
    say(f"a pod that does not exist: status {absent.value.status}, lightkube raised "
        f"{type(absent.value.__context__).__module__}.{type(absent.value.__context__).__name__}: {absent.value}")

    answered = run(loop, kube.exec(NAMESPACE, pod, ["sh", "-c", "yes | head -c 200000"], 30.0),
                   "exec of 200000 bytes of output")
    assert answered.returncode == 0 and answered.stderr == ""
    assert len(answered.stdout.encode()) == 65536 and set(answered.stdout) == {"y", "\n"}


def test_a_deleted_pod_is_watched_going_and_coming_back_and_the_namespace_goes(
    twin: Twin, loop: asyncio.Runner, kube: LightKube
) -> None:
    old = twin.pods["n1"]

    def went(events: list[tuple[str, Pod]]) -> bool:
        return any(operation == "DELETED" and pod.uid == old.uid for operation, pod in events)

    def came(events: list[tuple[str, Pod]]) -> bool:
        return any(operation == "ADDED" and pod.labels.get(NODE_LABEL) == "n1" and pod.uid != old.uid
                   for operation, pod in events)

    async def replaced() -> list[tuple[str, Pod]]:
        events: list[tuple[str, Pod]] = []
        watching = asyncio.Event()
        start = time.monotonic()

        async def watch() -> None:
            async for operation, pod in kube.watch_pods({OWNER_LABEL: OWNER}):
                if pod.namespace != NAMESPACE:
                    continue
                events.append((operation, pod))
                watching.set()
                say(f"{time.monotonic() - start:5.1f} s watch {operation} {pod.labels.get(NODE_LABEL)} uid {pod.uid} "
                    f"phase {pod.phase or '-'} ready {pod.ready} deleting {pod.deleting}")
                if went(events) and came(events):
                    return

        task = asyncio.create_task(watch())
        try:
            await asyncio.wait_for(watching.wait(), REQUEST_TIMEOUT_S)
            await kube.delete_pod(NAMESPACE, old.name)
            say(f"{time.monotonic() - start:5.1f} s delete_pod {old.name}")
            await asyncio.wait_for(task, 180.0)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return events

    events = run(loop, replaced(), "watch_pods while delete_pod removes n1's pod")
    assert went(events) and came(events)
    run(loop, kube.delete_pod(NAMESPACE, old.name), "delete_pod of a pod already gone")

    start = time.monotonic()
    run(loop, kube.delete_namespace(NAMESPACE), "delete_namespace")
    assert time.monotonic() - start < REQUEST_TIMEOUT_S
    deleting = run(loop, kube.namespace(NAMESPACE), "namespace, being deleted")
    assert deleting is not None and deleting.deleting
    run(loop, kube.delete_namespace(NAMESPACE), "delete_namespace while it is being deleted")
    until(loop, lambda: kube.namespace(NAMESPACE), lambda found: found is None, GONE_S, f"{NAMESPACE} gone")
    run(loop, kube.delete_namespace(NAMESPACE), "delete_namespace of a namespace already gone")
