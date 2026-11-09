"""A fake of the clabernetes driver's reach into Kubernetes: `FakeKube` answers `kube.Kube` in
memory, with a clock of its own, so the pure tier runs the driver's acting calls whole and no
test waits (D-060).

It is written from what the cluster answered (verified-facts.md: "fylgja-core, phase 6: the
driver's reach, over lightkube", and, under the k3s section, "fylgja-core, phase 6: the
Topology's status, and the pods replaced, read by hand" and "fylgja-core, phase 6: the
clabernetes driver's calls"):

- A `Topology` applied with a changed `spec` gains a generation; the same one again, or one
  differing in its annotations alone, moves none, and what was applied last is what it holds,
  so an annotation applied and then left out is gone. It has no `status` until the
  controller's first pass.
- The status is the controller's to write, and only its pass (`settle`) writes it. A pass runs
  `settle_s` after a generation moves and after any change to a pod. The one that observes a
  new generation writes `observedGeneration` and nothing else: `topologyReady` stays what the
  generation before left (false for a first), no pod or Service changes, and another pass
  follows `settle_s` later. That next pass reconciles the generation: it sets `topologyReady`
  false, whether or not a pod changes, makes and replaces pods as below, and another pass
  follows `settle_s` later. Any other pass sets `topologyReady` to whether every node has a pod
  that is `Ready` and not being deleted. Until a pass runs, the status read is the one written
  before: after a generation's apply, the generation before, observed and ready; after a
  pod's deletion, still ready. A driver must trust neither the status nor a pod alone.
- A pass gives each node of the wrapped containerlab definition without a pod one, phase
  `Running`, its container running, `Ready` `ready_s` later. A pod is named as a Deployment's
  are, `<node>-<hash>-<suffix>` (the hash of the node's name, a suffix from the pods made so
  far), its uid is `uid-<k>`, `k` counting every pod made from 1, and it carries the
  definition's default labels, `NODE_LABEL` and `TOPOLOGY_OWNER_LABEL`. A node in `replaces`
  has its pod replaced by the pass that reconciles a new generation, the one after the pass
  that observes it; the pod of a node no longer named goes. Each node that declares `ports` has
  a `LoadBalancer` Service of its name at `192.0.2.<k>` (its pod's `k` when the Service is
  made) with `externalTrafficPolicy: Cluster`, kept as it is once made, and given its address
  at once, or `address_s[node]` later when the test withholds it; every node has its headless
  `<node>-wire` Service; both go with the node.
- A Topology whose `spec.imagePull.pullSecrets` names a Secret its namespace lacks gets no pod
  and no Service from a pass, and reads not ready: clabernetes resolves the Secret itself
  before it makes a pod. Whether a Secret made later starts the nodes was not read; here the
  next pass would.
- A container ended in its pod (`restart`) leaves the pod at its uid and phase `Running`, not
  `Ready`, the container down and ended (`container_ended`, a `terminated` state on the
  cluster), until the test lets the kubelet start it (`start`), when the restart count grows
  by one and the container runs, as read; the pod is `Ready` `ready_s` later. That the node's
  address answers nothing then (verified-facts.md, "a container restarted in its pod") the fake
  does not model: it models no address's answer.
- A pod deleted (`delete_pod`, or a pass replacing it) goes as on the cluster: it reads
  deleting and still `Ready`, its replacement comes at once, another uid, `Pending` (`Running`
  and `Ready` together `ready_s` later), and the old pod goes `terminate_s` later, at once when
  that is 0. With `controller` off nothing replaces it. A namespace deleted reads `deleting`,
  and `namespace_delete_s` later it is gone with everything in it. An object applied into a
  namespace that is not there is refused with 404, and into one being deleted with 403.
- Kubernetes labels every namespace `kubernetes.io/metadata.name` with its name.
- A watch of pods, in every namespace, begins with each pod there that carries its labels,
  `ADDED`, as the cluster's did, and then delivers each change as it is made.
  `break_watch` and `restart_watch` stand for its connection lost and its restart by
  `LightKube.watch_pods` itself, which delivers every pod present again as `ADDED` and never a
  `DELETED` it missed. A watch never ends of itself; `fail_watch` makes each open one raise,
  as `LightKube`'s does only for what is neither the API's nor the transport's failure:
  `undecodable` makes that failure, a line lightkube cannot decode, as lightkube raises it.

- A pod a pass makes carries the request its node's entry in the Topology's
  `spec.deployment.resources` gives, else the `default` entry, else none (verified-facts.md,
  "The Topology's requests are by node name"), and, as its `host`, the nodes `add_node` added in
  turn, the k-th pod made taking the k-th node round the list; with no node added its host is None.
  `nodes` answers the nodes added and `all_pods` every pod of every namespace.

What a test reads: `namespaces`; `objects`, every mapping applied, by `(kind, namespace, name)`,
as it was given; `calls`, every call of `Kube` in order with its arguments; and `watches` and
`queued`, the watches open and the changes they hold unread. `fail` names a call and the
failures its next calls raise in turn, a None letting one through; the call is recorded either
way. Time moves only through `sleep`, which runs whatever falls due on the way, each at its own
time, and `at` schedules an action of the test's own. `feed` gives a watch a change to a pod
made by no Topology, as the test writes it.
"""

from __future__ import annotations

import asyncio
import copy
import functools
import hashlib
import heapq
import itertools
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import yaml
from lightkube.core import decoders

from fylgja_core.capacity import Resources
from fylgja_core.clabernetes.kube import NO_REQUEST, NODE_LABEL, KubeFailed, Namespace, Node, Pod, Service, cpu, mib
from fylgja_core.driver import Exec

TOPOLOGY_OWNER_LABEL = "c9s.run/topologyOwner"
"""The label clabernetes puts on a node's pod, its value the Topology's name (not the driver's
`clabernetes.OWNER_LABEL`)."""

NAME_LABEL = "kubernetes.io/metadata.name"
"""The label Kubernetes sets on every namespace, its value the namespace's name."""

SUFFIX = "bcdfghjklmnpqrstvwxz2456789"
"""What Kubernetes draws the suffix of a generated name from."""

EPOCH = datetime(2026, 11, 5, tzinfo=UTC)
"""The wall-clock time the fake's `now` of 0 stands for, in a pod's `created`."""

Key = tuple[str, str | None, str]


class FakeKube:
    """`kube.Kube` in memory, with the Topology's controller and time (see the module)."""

    def __init__(self) -> None:
        self.namespaces: dict[str, Namespace] = {}
        self.objects: dict[Key, dict[str, Any]] = {}
        self.calls: list[tuple[Any, ...]] = []
        self.now = 0.0
        self.controller = True
        self.settle_s = 0.0
        self.ready_s = 0.0
        self.terminate_s = 0.0
        self.namespace_delete_s = 0.0
        self.replaces: set[str] = set()
        self.address_s: dict[str, float] = {}
        self.exec_answers: dict[tuple[str, str], Exec | KubeFailed] = {}
        self.fail: dict[str, list[Exception | None]] = {}
        self._nodes: list[Node] = []
        self._pods: dict[tuple[str, str], Pod] = {}
        self._services: dict[tuple[str, str], Service] = {}
        self._generations: dict[tuple[str, str], int] = {}
        self._observed: dict[tuple[str, str], int] = {}
        self._ready: dict[tuple[str, str], bool] = {}
        self._reconciling: set[tuple[str, str]] = set()
        self._timers: list[tuple[float, int, Callable[[], None]]] = []
        self._order = itertools.count()
        self._made = 0
        self._watchers: list[tuple[dict[str, str], asyncio.Queue[tuple[str, Pod] | Exception]]] = []
        self._watch_broken = False

    # Time.

    def clock(self) -> float:
        """The fake's time, in seconds: what the driver is given for `time.monotonic`."""
        return self.now

    async def sleep(self, seconds: float) -> None:
        """Move the time on by `seconds`, running each action that falls due on the way at its own
        time, in order; then let the event loop run once."""
        until = self.now + seconds
        while self._timers and self._timers[0][0] <= until:
            due, _, action = heapq.heappop(self._timers)
            self.now = max(self.now, due)
            action()
        self.now = until
        await asyncio.sleep(0)

    def at(self, delay: float, action: Callable[[], None]) -> None:
        """Run `action` once the time has moved `delay` seconds on from now."""
        heapq.heappush(self._timers, (self.now + delay, next(self._order), action))

    # Kube.

    async def apply(self, obj: Mapping[str, Any]) -> None:
        kind, metadata = obj["kind"], obj["metadata"]
        namespace, name = metadata.get("namespace"), metadata["name"]
        self._call("apply", kind, namespace, name)
        if namespace is not None:
            held = self.namespaces.get(namespace)
            if held is None:
                raise _refused("apply", kind, f"{namespace}/{name}", 404, "Not Found",
                               f'namespaces "{namespace}" not found')
            if held.deleting:
                raise _refused("apply", kind, f"{namespace}/{name}", 403, "Forbidden",
                               f"unable to create new content in namespace {namespace} because it is being terminated")
        doc = copy.deepcopy(dict(obj))
        if kind == "Namespace":
            held = self.namespaces.get(name)
            labels = {**(held.labels if held else {}), **metadata.get("labels", {}), NAME_LABEL: name}
            self.namespaces[name] = Namespace(name, labels, held is not None and held.deleting)
        elif kind == "Topology":
            before = self.objects.get((kind, namespace, name))
            if before is None or before["spec"] != doc["spec"]:
                self._generations[(namespace, name)] = self._generations.get((namespace, name), 0) + 1
                self.at(self.settle_s, lambda: self._pass(namespace))
        self.objects[(kind, namespace, name)] = doc

    async def namespace(self, name: str) -> Namespace | None:
        self._call("namespace", name)
        return self.namespaces.get(name)

    async def topology(self, namespace: str, name: str) -> Mapping[str, Any] | None:
        self._call("topology", namespace, name)
        doc = self.objects.get(("Topology", namespace, name))
        if doc is None:
            return None
        held = copy.deepcopy(doc)
        held["metadata"]["generation"] = self._generations[(namespace, name)]
        observed = self._observed.get((namespace, name), 0)
        if observed:
            held["status"] = {"observedGeneration": observed, "topologyReady": self._ready[(namespace, name)]}
        return held

    async def pods(self, namespace: str, labels: Mapping[str, str]) -> list[Pod]:
        self._call("pods", namespace, dict(labels))
        return sorted((p for (ns, _), p in self._pods.items() if ns == namespace and _carries(p.labels, labels)),
                      key=lambda p: p.name)

    async def services(self, namespace: str) -> list[Service]:
        self._call("services", namespace)
        return sorted((s for (ns, _), s in self._services.items() if ns == namespace), key=lambda s: s.name)

    async def nodes(self) -> list[Node]:
        self._call("nodes")
        return sorted(self._nodes, key=lambda n: n.name)

    async def all_pods(self) -> list[Pod]:
        self._call("all_pods")
        return sorted(self._pods.values(), key=lambda p: (p.namespace, p.name))

    async def patch_service(self, namespace: str, name: str, patch: Mapping[str, Any]) -> None:
        """Merge `patch` into the Service; of its members, the fake reads
        `spec.externalTrafficPolicy` alone."""
        self._call("patch_service", namespace, name, copy.deepcopy(dict(patch)))
        held = self._services.get((namespace, name))
        if held is None:
            raise _refused("patch_service", "Service", f"{namespace}/{name}", 404, "Not Found",
                           f'services "{name}" not found')
        policy = patch.get("spec", {}).get("externalTrafficPolicy")
        if policy is not None:
            self._services[(namespace, name)] = replace(held, traffic_policy=policy)

    async def delete_pod(self, namespace: str, name: str) -> None:
        """The pod deleted as the cluster deletes a node's pod (see the module); one already gone,
        or already being deleted, is left as it is."""
        self._call("delete_pod", namespace, name)
        pod = self._pods.get((namespace, name))
        if pod is not None and not pod.deleting:
            self._retire(pod, replaced=self.controller)

    async def delete_namespace(self, name: str) -> None:
        self._call("delete_namespace", name)
        held = self.namespaces.get(name)
        if held is None or held.deleting:
            return
        self.namespaces[name] = replace(held, deleting=True)
        self.at(self.namespace_delete_s, lambda: self._gone(name))

    async def exec(self, namespace: str, pod: str, argv: Sequence[str], timeout_s: float) -> Exec:
        self._call("exec", namespace, pod, tuple(argv), timeout_s)
        if (namespace, pod) not in self._pods:
            raise KubeFailed(f"exec Pod {namespace}/{pod}: 404 Not Found", 404)
        answer = self.exec_answers.get((namespace, pod), Exec(0, "", ""))
        if isinstance(answer, KubeFailed):
            raise answer
        return answer

    async def watch_pods(self, labels: Mapping[str, str]) -> AsyncGenerator[tuple[str, Pod]]:
        """Each pod present carrying `labels`, `ADDED`, in namespace and name order, then each change
        as it comes; a failure `fail_watch` gives is raised in its turn, and the watch is over."""
        self._call("watch_pods", dict(labels))
        queue = asyncio.Queue[tuple[str, Pod] | Exception]()
        for pod in sorted(self._pods.values(), key=lambda p: (p.namespace, p.name)):
            if _carries(pod.labels, labels):
                queue.put_nowait(("ADDED", pod))
        watcher = (dict(labels), queue)
        self._watchers.append(watcher)
        try:
            while True:
                change = await queue.get()
                if isinstance(change, Exception):
                    raise change
                yield change
        finally:
            self._watchers.remove(watcher)

    # The Topology's controller.

    def settle(self, namespace: str) -> None:
        """The controller's pass over each Topology of `namespace` (see the module)."""
        named: set[str] = set()
        observing = False
        for (kind, ns, name), doc in list(self.objects.items()):
            if kind != "Topology" or ns != namespace:
                continue
            key = (namespace, name)
            if self._observed.get(key, 0) < self._generations[key]:
                # The generation observed, the readiness of the one before kept: about 0.14 s on the cluster.
                self._observed[key] = self._generations[key]
                self._ready.setdefault(key, False)
                self._reconciling.add(key)
                self.at(self.settle_s, lambda: self._pass(namespace))
                observing = True
                continue
            reconciles = key in self._reconciling
            self._reconciling.discard(key)
            definition = yaml.safe_load(doc["spec"]["definition"]["containerlab"])["topology"]
            nodes: dict[str, Any] = definition["nodes"]
            defaults = (definition.get("defaults") or {}).get("labels") or {}
            pulled = (doc["spec"].get("imagePull") or {}).get("pullSecrets") or []
            if any(("Secret", namespace, secret) not in self.objects for secret in pulled):
                # A pull secret missing: no pod, and not ready (verified-facts.md, lightkube 1.0.1).
                named |= {*(n for n, spec in nodes.items() if spec.get("ports")), *(f"{n}-wire" for n in nodes)}
                self._ready[key] = False
                continue
            for pod in self._pods_of(namespace, name):
                if pod.labels.get(NODE_LABEL) not in nodes and not pod.deleting:
                    self._retire(pod, replaced=False)
            for node, spec in nodes.items():
                current: Pod | None = self._current(namespace, name, node)
                if current is not None and reconciles and node in self.replaces:
                    current = self._retire(current, replaced=True)
                if current is None:
                    labels = {**defaults, NODE_LABEL: node, TOPOLOGY_OWNER_LABEL: name}
                    current = self._make(namespace, labels, phase="Running", ready_s=self.ready_s,
                                         requests=_requested(doc, node))
                if spec.get("ports") and (namespace, node) not in self._services:
                    address = f"192.0.2.{_k(current)}"
                    withheld = node in self.address_s
                    self._services[(namespace, node)] = Service(node, "LoadBalancer", "Cluster",
                                                                None if withheld else address)
                    if withheld:
                        self.at(self.address_s[node], functools.partial(self._addressed, namespace, node, address))
                wire = f"{node}-wire"
                self._services.setdefault((namespace, wire), Service(wire, "ClusterIP", None, None))
            named |= {*(n for n, spec in nodes.items() if spec.get("ports")), *(f"{n}-wire" for n in nodes)}
            if reconciles:
                self._ready[key] = False
                self.at(self.settle_s, lambda: self._pass(namespace))
            else:
                self._ready[key] = all((ready := self._current(namespace, name, node)) is not None and ready.ready
                                       for node in nodes)
        if not observing:
            for gone in [k for k in self._services if k[0] == namespace and k[1] not in named]:
                del self._services[gone]

    # Helpers.

    def add_namespace(self, name: str, labels: Mapping[str, str]) -> None:
        """A namespace made by someone else, labelled `labels`; no call is recorded."""
        self.namespaces[name] = Namespace(name, {**labels, NAME_LABEL: name}, False)

    def add_node(self, name: str, cpus: float, memory_mb: int) -> None:
        """A node of the cluster with `cpus` and `memory_mb` allocatable; no call is recorded."""
        self._nodes.append(Node(name, Resources(cpus, memory_mb)))

    def add_pod(
        self, namespace: str, name: str, host: str | None, requests: Resources, labels: Mapping[str, str] | None = None
    ) -> None:
        """A pod of someone else's on `host` (None: bound to no host yet), `Running` with its container running,
        carrying `labels` (none: it is no twin's unless they say so) and asking `requests`; no call is recorded."""
        self._put("ADDED", Pod(name=name, namespace=namespace, uid=f"uid-added-{name}", labels=dict(labels or {}),
                               phase="Running", ready=True, deleting=False,
                               created=(EPOCH + timedelta(seconds=self.now)).isoformat(), restarts=0,
                               container_running=True, host=host, requests=requests))

    def fail_next(self, call: str) -> None:
        """Make the next call of `call` (`nodes`, `all_pods`, ...) raise `KubeFailed`, no status."""
        self.fail.setdefault(call, []).append(KubeFailed(f"{call}: the cluster did not answer", None))

    def pod_of(self, namespace: str, node: str) -> Pod:
        """The node's pod: the one not being deleted, else the last made."""
        found = sorted((p for p in self._pods.values() if p.namespace == namespace
                        and p.labels.get(NODE_LABEL) == node), key=lambda p: (not p.deleting, _k(p)))
        assert found, f"the node {node} has no pod in {namespace}"
        return found[-1]

    def set_ready(self, namespace: str, node: str, ready: bool) -> None:
        """The node's pod `Ready` or not; one made `Ready` runs, its container with it."""
        pod = self.pod_of(namespace, node)
        self._put("MODIFIED", replace(pod, ready=ready, phase="Running" if ready else pod.phase,
                                      container_running=ready or pod.container_running))

    def set_phase(self, namespace: str, node: str, phase: str) -> None:
        """The node's pod at `phase`; its container runs only while the pod is `Running`."""
        pod = self.pod_of(namespace, node)
        self._put("MODIFIED", replace(pod, phase=phase, container_running=pod.container_running and phase == "Running",
                                      ended=phase in ("Succeeded", "Failed")))

    def terminate(self, namespace: str, node: str) -> None:
        """The node's pod being deleted and staying, `Ready`, beside a second pod of the node,
        `Pending` and not `Ready` until a test says so: a deletion's window, held open."""
        pod = self.pod_of(namespace, node)
        self._put("MODIFIED", replace(pod, deleting=True))
        self._make(namespace, dict(pod.labels), phase="Pending", ready_s=None, requests=pod.requests)

    def restart(self, namespace: str, node: str) -> None:
        """The node's container ended in its pod, as the cluster was read to keep it: the same pod,
        its phase `Running`, not `Ready`, the container down, until `start`."""
        pod = self.pod_of(namespace, node)
        self._put("MODIFIED", replace(pod, ready=False, container_running=False, container_ended=True))

    def start(self, namespace: str, node: str) -> None:
        """The node's container ended by `restart` started again by the kubelet: one restart more,
        the container running, and the pod `Ready` `ready_s` later."""
        pod = replace(self.pod_of(namespace, node), restarts=self.pod_of(namespace, node).restarts + 1,
                      container_running=True, container_ended=False)
        self._put("MODIFIED", pod)
        self.at(self.ready_s, lambda: self._made_ready(pod))

    def set_policy(self, namespace: str, service: str, value: str) -> None:
        """The Service's `externalTrafficPolicy` set by someone else; no call is recorded."""
        self._services[(namespace, service)] = replace(self._services[(namespace, service)], traffic_policy=value)

    def break_watch(self) -> None:
        """Every watch's connection lost: no change reaches a watcher until `restart_watch`."""
        self._watch_broken = True

    def restart_watch(self) -> None:
        """Every watch restarted, as after `LightKube.watch_pods`' fresh watch or lightkube's reset on
        a 410: each pod present that it watches is delivered again as `ADDED`, and a pod gone since
        `break_watch` is never delivered as `DELETED`. lightkube's own reconnect at its version,
        which delivers what changed meanwhile, is a watch never broken here."""
        self._watch_broken = False
        present = sorted(self._pods.values(), key=lambda p: (p.namespace, p.name))
        for labels, queue in self._watchers:
            for pod in present:
                if _carries(pod.labels, labels):
                    queue.put_nowait(("ADDED", pod))

    def fail_watch(self, error: Exception) -> None:
        """Every open watch raises `error` once it has delivered what came before, and is over: what
        `LightKube.watch_pods`, which watches again for itself after any failure of the API or the
        transport, still raises, such as a line it cannot decode."""
        for _, queue in self._watchers:
            queue.put_nowait(error)

    def feed(self, operation: str, pod: Pod) -> None:
        """A change to `pod` as the test gives it, made by no Topology and delivered to each watch as
        the API delivers one: `ADDED` or `MODIFIED` holds `pod` as given, and `DELETED` removes the
        pod of its namespace and name. No call is recorded."""
        if operation == "DELETED":
            self._pods.pop((pod.namespace, pod.name), None)
        else:
            self._pods[(pod.namespace, pod.name)] = pod
        self._changed(operation, pod)

    @property
    def watches(self) -> int:
        """How many watches are open: iterated, and not yet ended by a cancel, a close or a failure."""
        return len(self._watchers)

    @property
    def queued(self) -> int:
        """How many changes the open watches hold that their readers have not yet read."""
        return sum(queue.qsize() for _, queue in self._watchers)

    # Within.

    def _call(self, name: str, *args: Any) -> None:
        self.calls.append((name, *args))
        failures = self.fail.get(name)
        if failures:
            failure = failures.pop(0)
            if failure is not None:
                raise failure

    def _pass(self, namespace: str) -> None:
        if self.controller:
            self.settle(namespace)

    def _pods_of(self, namespace: str, topology: str) -> list[Pod]:
        return [p for p in self._pods.values()
                if p.namespace == namespace and p.labels.get(TOPOLOGY_OWNER_LABEL) == topology]

    def _addressed(self, namespace: str, node: str, address: str) -> None:
        """The node's LoadBalancer, withheld by `address_s`, given its address, if it still stands."""
        held = self._services.get((namespace, node))
        if held is not None and held.address is None:
            self._services[(namespace, node)] = replace(held, address=address)

    def _current(self, namespace: str, topology: str, node: str) -> Pod | None:
        """The node's pod not being deleted, the last made."""
        found = [p for p in self._pods_of(namespace, topology) if p.labels.get(NODE_LABEL) == node and not p.deleting]
        return max(found, key=_k) if found else None

    def _make(self, namespace: str, labels: dict[str, str], *, phase: str, ready_s: float | None,
              requests: Resources = NO_REQUEST) -> Pod:
        self._made += 1
        k = self._made
        host = self._nodes[(k - 1) % len(self._nodes)].name if self._nodes else None
        pod = Pod(name=_pod_name(labels[NODE_LABEL], k), namespace=namespace, uid=f"uid-{k}", labels=labels,
                  phase=phase, ready=False, deleting=False, created=(EPOCH + timedelta(seconds=self.now)).isoformat(),
                  restarts=0, container_running=phase == "Running", host=host, requests=requests)
        self._put("ADDED", pod)
        if ready_s is not None:
            self.at(ready_s, lambda: self._made_ready(pod))
        return pod

    def _made_ready(self, made: Pod) -> None:
        pod = self._pods.get((made.namespace, made.name))
        if pod is not None and pod.uid == made.uid and not pod.ready:
            self._put("MODIFIED", replace(pod, ready=True, phase="Running", container_running=True))

    def _retire(self, pod: Pod, *, replaced: bool) -> Pod | None:
        """`pod` deleted as the cluster deletes a node's pod: it reads deleting and still `Ready`,
        its replacement, when `replaced`, comes at once, `Pending`, and it goes `terminate_s`
        later, at once when that is 0. The replacement, or None."""
        old = replace(pod, deleting=True)
        self._put("MODIFIED", old)
        new = self._make(pod.namespace, dict(pod.labels), phase="Pending", ready_s=self.ready_s,
                         requests=pod.requests) if replaced else None
        if self.terminate_s > 0:
            self.at(self.terminate_s, lambda: self._ended(old))
        else:
            self._remove(old)
        return new

    def _ended(self, old: Pod) -> None:
        pod = self._pods.get((old.namespace, old.name))
        if pod is not None and pod.uid == old.uid:
            self._remove(pod)

    def _put(self, operation: str, pod: Pod) -> None:
        self._pods[(pod.namespace, pod.name)] = pod
        self._changed(operation, pod)

    def _remove(self, pod: Pod) -> None:
        del self._pods[(pod.namespace, pod.name)]
        self._changed("DELETED", replace(pod, deleting=True))

    def _changed(self, operation: str, pod: Pod) -> None:
        """A change to `pod`: to each watcher whose labels it carries, unless the watch is broken;
        and the controller's pass over its namespace, `settle_s` later."""
        if not self._watch_broken:
            for labels, queue in self._watchers:
                if _carries(pod.labels, labels):
                    queue.put_nowait((operation, pod))
        self.at(self.settle_s, lambda: self._pass(pod.namespace))

    def _gone(self, name: str) -> None:
        held = self.namespaces.get(name)
        if held is None or not held.deleting:
            return
        del self.namespaces[name]
        for obj in [k for k in self.objects if k[1] == name or k == ("Namespace", None, name)]:
            del self.objects[obj]
        for pod in [p for p in self._pods.values() if p.namespace == name]:
            self._remove(pod)
        for service in [k for k in self._services if k[0] == name]:
            del self._services[service]
        for table in (self._generations, self._observed):
            for topology in [k for k in table if k[0] == name]:
                del table[topology]
        for ready in [k for k in self._ready if k[0] == name]:
            del self._ready[ready]
        self._reconciling = {key for key in self._reconciling if key[0] != name}


def undecodable(line: bytes = b"not json") -> ValueError:
    """The failure a real pod watch raises to its reader, the one `LightKube.watch_pods` lets
    through: lightkube's decode of a line it cannot read (`decoders.decode_watch_event`), msgspec's
    `DecodeError` for one that is no JSON and its `ValidationError` for JSON not shaped as an
    event, each a `ValueError` outside `kube.FAILURES` (verified-facts.md, lightkube 1.0.1). The
    API's refusals and the transport's failures, a 403 or a 410 among them, lightkube and
    `LightKube` retry, so no watch raises them."""
    try:
        decoders.decode_watch_event(line)
    except ValueError as e:
        return e
    raise AssertionError(f"lightkube decodes {line!r} as a watch event")


def _requested(topology: Mapping[str, Any], node: str) -> Resources:
    """What the Topology asks of `node`'s pod: its entry of `spec.deployment.resources`, else `default`'s."""
    resources = (topology["spec"].get("deployment") or {}).get("resources") or {}
    asked = (resources.get(node) or resources.get("default") or {}).get("requests") or {}
    return Resources(cpu(asked["cpu"]) if "cpu" in asked else 0.0, mib(asked["memory"]) if "memory" in asked else 0)


def _carries(labels: Mapping[str, str], wanted: Mapping[str, str]) -> bool:
    return all(labels.get(k) == v for k, v in wanted.items())


def _k(pod: Pod) -> int:
    """The count of pods made when `pod` was, from its uid."""
    return int(pod.uid.removeprefix("uid-"))


def _pod_name(node: str, k: int) -> str:
    """The `k`-th pod's name, shaped as a Deployment's pods are named: `<node>-<hash>-<suffix>`,
    the hash the node's name's and the suffix `k` written in `SUFFIX`'s letters."""
    suffix = ""
    for _ in range(5):
        k, digit = divmod(k, len(SUFFIX))
        suffix = SUFFIX[digit] + suffix
    return f"{node}-{hashlib.sha256(node.encode()).hexdigest()[:9]}-{suffix}"


def _refused(call: str, kind: str, named: str, code: int, reason: str, message: str) -> KubeFailed:
    """The `KubeFailed` `LightKube` raises for the API's refusal, the API's message left out over a Secret."""
    shown = f": {message}" if kind != "Secret" else ""
    return KubeFailed(f"{call} {kind} {named}: {code} {reason}{shown}", code)
