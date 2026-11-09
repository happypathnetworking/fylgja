"""The clabernetes driver's reach into Kubernetes: twelve calls, and nothing else of the API (D-057,
D-064, D-073).

`Kube` is what the driver acts through: it applies an object, reads a namespace, a `Topology`,
the twin's pods and Services, the cluster's nodes and every pod, patches a Service, deletes a pod or
a namespace, runs an exec and watches pods. A protocol that small is one a fake can stand in for, so
the driver's acting calls run in the pure tier (D-060). `LightKube` answers it over lightkube, and
this is the one module of the driver that imports lightkube or httpx2; the client it is given is
made by `fylgja_core.kubeapi`, above the seam. A test holds which modules import them.

Every call raises `KubeFailed` alone, a `DriverFailed` the loop retries: an API's refusal with
its code, a refused WebSocket upgrade's included, or a transport failure or a budget run out
with none. Its message names the call, the kind and the object, never an object's body; over a
Secret it never carries the API's message either, which may quote the object (Constitution X).
A failure with no status names its type alone, since a transport's error can name the API
server's address; its text is logged at DEBUG alone. Every behaviour a call relies on was read
on the cluster (verified-facts.md, lightkube 1.0.1).

`nodes` lists `core_v1.Node`, a cluster-scoped kind, with no namespace. `all_pods` lists
`core_v1.Pod` with `namespace=ALL_NS`: lightkube's `list` takes a namespace, and `ALL_NS` (`"*"`) is
the value its request builder reads as every namespace (`lightkube.core.generic_client`, 1.0.1),
the one the pod watch passes likewise. A pod's request is read from its spec as the scheduler sums
it (`requests_of`), its own pod-level requests over its containers' where it sets them, and a
quantity as Kubernetes writes it (`cpu`, `mib`). A pod or a node that will not read so is a
`KubeFailed` of the call that listed it, `pods`, `all_pods` or `nodes`, naming the object.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import floor
from typing import Any, Protocol

import httpx2
from httpx2.websockets import HTTPXWSException, WebSocketUpgradeError
from lightkube import ALL_NS, ApiError, AsyncClient, codecs
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources import core_v1
from lightkube.types import OnErrorAction, OnErrorResult, PatchType

from fylgja_core.capacity import Resources
from fylgja_core.driver import DriverFailed, Exec, events_backoff
from fylgja_core.kubeapi import FIELD_MANAGER

EXEC_OUTPUT_KEPT = 65536
"""How many bytes of each of an `exec`'s outputs are kept: the last, as the local driver keeps."""

NODE_LABEL = "c9s.run/topologyNode"
"""The label clabernetes puts on a node's pod, its value the node's name."""

NO_REQUEST = Resources(0.0, 0)
"""What a pod that asks for nothing requests."""

MESSAGE_KEPT = 200
"""How many characters of the API's message a `KubeFailed` carries."""

Topology = create_namespaced_resource("c9s.run", "v1alpha1", "Topology", "topologies")
"""clabernetes' `Topology`, a generic resource; made at import, so that `codecs.from_dict` knows the kind."""

FAILURES = (ApiError, httpx2.HTTPError, HTTPXWSException, OSError, TimeoutError)
"""What a call through lightkube raises when the API refuses, the transport fails or a budget runs
out; `ApiError` is an `httpx2.HTTPError`, named for the reader."""

_log = logging.getLogger("fylgja.clabernetes")

_QUANTITY = re.compile(r"([+-]?(?:\d+\.?\d*|\.\d+))(?:([eE][+-]?\d+)|([A-Za-z]{0,2}))")
_SUFFIXES = {
    "n": Decimal("1e-9"), "u": Decimal("1e-6"), "m": Decimal("1e-3"), "": Decimal(1), "k": Decimal("1e3"),
    "M": Decimal("1e6"), "G": Decimal("1e9"), "T": Decimal("1e12"), "P": Decimal("1e15"), "E": Decimal("1e18"),
    "Ki": Decimal(2**10), "Mi": Decimal(2**20), "Gi": Decimal(2**30), "Ti": Decimal(2**40), "Pi": Decimal(2**50),
    "Ei": Decimal(2**60),
}


class KubeFailed(DriverFailed):
    """A call refused by the API (`status` its code), or one the transport failed or that ran
    out of its budget (`status` None)."""

    def __init__(self, message: str, status: int | None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Namespace:
    """A namespace as the driver reads it: its labels, and whether it is being deleted."""

    name: str
    labels: Mapping[str, str]
    deleting: bool


@dataclass(frozen=True)
class Pod:
    """A pod as the driver reads it. `ready` is its `Ready` condition `True`, `deleting` a
    deletion timestamp set, `created` its creation timestamp in ISO form, `restarts` the restart
    count of its one container, 0 before it has a status, and `container_running` whether that
    container's state is `running`, False before it has one. A container ended in its pod leaves
    the pod's phase `Running` while it is terminated and while it restarts (verified-facts.md,
    "the clabernetes driver's calls"): only the container's state says it is down.
    `host` is the node its spec names, None before it is scheduled; `requests` its effective request
    as the scheduler sums it (`requests_of`); `ended` whether its phase is `Succeeded` or `Failed`.
    `container_ended` is whether that container has ended in the pod and not run since: its state
    `terminated`, or `waiting` after a last state `terminated`; a pod starting never shows either,
    its container `waiting` with no last state (verified-facts.md, "a container restarted in its
    pod")."""

    name: str
    namespace: str
    uid: str
    labels: Mapping[str, str]
    phase: str
    ready: bool
    deleting: bool
    created: str
    restarts: int
    container_running: bool
    container_ended: bool = False
    host: str | None = None
    requests: Resources = NO_REQUEST
    ended: bool = False


@dataclass(frozen=True)
class Node:
    """A node as the driver reads it: its name and the CPU and memory it has to give pods."""

    name: str
    allocatable: Resources


@dataclass(frozen=True)
class Service:
    """A Service as the driver reads it: `address` is its first LoadBalancer ingress address,
    None before it has one."""

    name: str
    type: str
    traffic_policy: str | None
    address: str | None


class Kube(Protocol):
    """The driver's whole reach into Kubernetes. Every call raises `KubeFailed` alone."""

    async def apply(self, obj: Mapping[str, Any]) -> None:
        """Apply `obj`, a mapping with `apiVersion`, `kind` and `metadata`, server-side, forced,
        under `FIELD_MANAGER`."""
        ...

    async def namespace(self, name: str) -> Namespace | None:
        """The namespace `name`, or None when there is none."""
        ...

    async def topology(self, namespace: str, name: str) -> Mapping[str, Any] | None:
        """The `Topology` `name` as the API holds it (`metadata.generation`,
        `metadata.annotations`, `spec`, `status`), or None when there is none."""
        ...

    async def pods(self, namespace: str, labels: Mapping[str, str]) -> list[Pod]:
        """The pods of `namespace` carrying every label of `labels`, sorted by name."""
        ...

    async def services(self, namespace: str) -> list[Service]:
        """The Services of `namespace`, sorted by name."""
        ...

    async def nodes(self) -> list[Node]:
        """Every node of the cluster with its allocatable, sorted by name."""
        ...

    async def all_pods(self) -> list[Pod]:
        """Every pod of every namespace, whoever owns it, sorted by namespace and name."""
        ...

    async def patch_service(self, namespace: str, name: str, patch: Mapping[str, Any]) -> None:
        """Merge `patch` into the Service `name`."""
        ...

    async def delete_pod(self, namespace: str, name: str) -> None:
        """Delete the pod `name`, without waiting for it to go; one already gone is fine."""
        ...

    async def delete_namespace(self, name: str) -> None:
        """Delete the namespace `name`, without waiting for it to go; one already gone is fine."""
        ...

    async def exec(self, namespace: str, pod: str, argv: Sequence[str], timeout_s: float) -> Exec:
        """Run `argv` in the pod's one container, naming none and with no shell, within
        `timeout_s`. A non-zero exit is the answer; each output is cut to its last
        `EXEC_OUTPUT_KEPT` bytes."""
        ...

    def watch_pods(self, labels: Mapping[str, str]) -> AsyncGenerator[tuple[str, Pod]]:
        """Each change to a pod of any namespace carrying every label of `labels`, as its
        operation (`ADDED`, `MODIFIED` or `DELETED`) and the pod, beginning with each pod there,
        `ADDED` (verified-facts.md, lightkube 1.0.1); reconnecting for itself, it ends only when
        cancelled or closed, and a close ends its request at once. lightkube asks again at the
        version of the last pod it delivered, after a stream that ends and after a failure it
        retries, so a change during that gap is delivered then, not lost (verified-facts.md, "the
        pod watch, as lightkube runs it"). After a version too old (a 410, which k3s answers
        inside the stream), and when this watch starts afresh after a failure lightkube raises,
        every pod present is delivered again as `ADDED`, and a pod deleted during that gap is
        never delivered as `DELETED`. Its failures
        are logged by their type and status code alone, never their text."""
        ...


class Tail(io.BytesIO):
    """The stream `exec` hands lightkube for each of a command's outputs: it keeps the last
    `EXEC_OUTPUT_KEPT` bytes written to it."""

    def write(self, data: Any) -> int:
        written = super().write(data)
        if self.tell() > EXEC_OUTPUT_KEPT:
            kept = self.getvalue()[-EXEC_OUTPUT_KEPT:]
            self.seek(0)
            self.truncate()
            super().write(kept)
        return written

    def text(self) -> str:
        """What was kept, decoded, a character cut at its start replaced."""
        return self.getvalue().decode(errors="replace")


class LightKube:
    """`Kube` over lightkube's client."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def apply(self, obj: Mapping[str, Any]) -> None:
        metadata = obj["metadata"]
        resource = codecs.from_dict(dict(obj))
        try:
            await self._client.apply(resource, field_manager=FIELD_MANAGER, force=True)
        except FAILURES as e:
            raise _failed("apply", obj["kind"], _named(metadata.get("namespace"), metadata["name"]), e) from None

    async def namespace(self, name: str) -> Namespace | None:
        try:
            model = await self._client.get(core_v1.Namespace, name)
        except FAILURES as e:
            if _absent(e):
                return None
            raise _failed("namespace", "Namespace", name, e) from None
        return namespace_from(model)

    async def topology(self, namespace: str, name: str) -> Mapping[str, Any] | None:
        try:
            model = await self._client.get(Topology, name, namespace=namespace)
        except FAILURES as e:
            if _absent(e):
                return None
            raise _failed("topology", "Topology", f"{namespace}/{name}", e) from None
        return dict(model)

    async def pods(self, namespace: str, labels: Mapping[str, str]) -> list[Pod]:
        found: list[Pod] = []
        try:
            async for model in self._client.list(core_v1.Pod, namespace=namespace, labels=dict(labels)):
                try:
                    found.append(pod_from(model))
                except ValueError as e:
                    named = (model.metadata.name if model.metadata else None) or "*"
                    raise _failed("pods", "Pod", f"{namespace}/{named}", e) from None
        except FAILURES as e:
            raise _failed("pods", "Pod", f"{namespace}/*", e) from None
        return sorted(found, key=lambda p: p.name)

    async def services(self, namespace: str) -> list[Service]:
        try:
            found = [service_from(m) async for m in self._client.list(core_v1.Service, namespace=namespace)]
        except FAILURES as e:
            raise _failed("services", "Service", f"{namespace}/*", e) from None
        return sorted(found, key=lambda s: s.name)

    async def nodes(self) -> list[Node]:
        found: list[Node] = []
        try:
            async for model in self._client.list(core_v1.Node):
                try:
                    found.append(node_from(model))
                except ValueError as e:
                    named = (model.metadata.name if model.metadata else None) or "*"
                    raise _failed("nodes", "Node", named, e) from None
        except FAILURES as e:
            raise _failed("nodes", "Node", "*", e) from None
        return sorted(found, key=lambda n: n.name)

    async def all_pods(self) -> list[Pod]:
        found: list[Pod] = []
        try:
            async for model in self._client.list(core_v1.Pod, namespace=ALL_NS):
                try:
                    found.append(pod_from(model))
                except ValueError as e:
                    meta = model.metadata
                    raise _failed("all_pods", "Pod", f"{meta.namespace}/{meta.name}" if meta else "*/*", e) from None
        except FAILURES as e:
            raise _failed("all_pods", "Pod", "*/*", e) from None
        return sorted(found, key=lambda p: (p.namespace, p.name))

    async def patch_service(self, namespace: str, name: str, patch: Mapping[str, Any]) -> None:
        try:
            await self._client.patch(core_v1.Service, name, dict(patch), namespace=namespace,
                                     patch_type=PatchType.MERGE)
        except FAILURES as e:
            raise _failed("patch_service", "Service", f"{namespace}/{name}", e) from None

    async def delete_pod(self, namespace: str, name: str) -> None:
        try:
            await self._client.delete(core_v1.Pod, name, namespace=namespace)
        except FAILURES as e:
            if not _absent(e):
                raise _failed("delete_pod", "Pod", f"{namespace}/{name}", e) from None

    async def delete_namespace(self, name: str) -> None:
        try:
            await self._client.delete(core_v1.Namespace, name)
        except FAILURES as e:
            if not _absent(e):
                raise _failed("delete_namespace", "Namespace", name, e) from None

    async def exec(self, namespace: str, pod: str, argv: Sequence[str], timeout_s: float) -> Exec:
        stdout, stderr = Tail(), Tail()
        try:
            answer = await self._client.exec(pod, namespace=namespace, command=list(argv), stdout=stdout,
                                             stderr=stderr, timeout=timeout_s)
        except FAILURES as e:
            raise _failed("exec", "Pod", f"{namespace}/{pod}", e) from None
        return Exec(answer.exit_code, stdout.text(), stderr.text())

    async def watch_pods(self, labels: Mapping[str, str]) -> AsyncGenerator[tuple[str, Pod]]:
        # lightkube restarts a stream that ended and, through `watch_retry`, one the API refused or
        # broke; what it raises instead, a request it could not send, is retried here, after the
        # seam's backoff. Closed or cancelled, it closes lightkube's watch, and so its response, at
        # once: lightkube's is an asynchronous generator, typed as an iterable.
        pause: float | None = None
        while True:
            watch = self._client.watch(core_v1.Pod, namespace=ALL_NS, labels=dict(labels), on_error=watch_retry)
            try:
                async for operation, model in watch:
                    pause = None
                    yield operation, pod_from(model)
            except FAILURES as e:
                pause = events_backoff(pause)
                _log.warning("watch_pods Pod */*: %s; watching again in %gs", _watch_failure(e), pause)
                await asyncio.sleep(pause)
            finally:
                if isinstance(watch, AsyncGenerator):
                    await watch.aclose()

    async def close(self) -> None:
        """Close lightkube's client and its connections."""
        await self._client.close()


def watch_retry(error: Exception, count: int) -> OnErrorResult:
    """lightkube's error handler for the pod watch: retry the `count`-th failure in a row (lightkube
    counts from 1, and from 0 again once a stream opens) after `_watch_pause(count)`, logged at
    WARNING by the error's type and status code alone (`_watch_failure`)."""
    pause = _watch_pause(count)
    _log.warning("watch_pods Pod */*: %s; watching again in %gs", _watch_failure(error), pause)
    return OnErrorResult(OnErrorAction.RETRY, sleep=pause)


def _watch_pause(count: int) -> float:
    """The pause after the `count`-th failure in a row: the seam's `events_backoff` after the
    `count - 1` before it (pre-flight ruling 9: the one backoff of the core, no copy), asked again
    only while it grows."""
    pause = events_backoff(None)
    for _ in range(count - 1):
        longer = events_backoff(pause)
        if longer == pause:
            break
        pause = longer
    return pause


def _refusal(error: Exception) -> tuple[int | None, str | None, str | None] | None:
    """The API's refusal `error` carries: its status code, its reason and, from a Status
    document, the API's message. None for a failure with no API status: the transport's, or a
    budget run out."""
    if isinstance(error, ApiError):
        return error.status.code, error.status.reason, error.status.message
    if isinstance(error, (httpx2.HTTPStatusError, WebSocketUpgradeError)):
        # A refusal with no Status document, and a refused WebSocket upgrade, whose body is never read.
        return error.response.status_code, error.response.reason_phrase, None
    return None


def _watch_failure(error: Exception) -> str:
    """How a failure of the pod watch is logged: its type and, for the API's refusal, its status
    code. Never its text, nor the API's message: a transport's error can name the API server's
    address, a certificate's own among them (Constitution X), and the watch is the clabernetes
    driver's `events` source."""
    refusal = _refusal(error)
    code = None if refusal is None else refusal[0]
    return type(error).__name__ if code is None else f"{type(error).__name__}, status {code}"


def _failed(call: str, kind: str, named: str, error: Exception) -> KubeFailed:
    """The `KubeFailed` for `error`, raised by the call `call` over the object `named` (a name,
    `<namespace>/<name>`, or `<namespace>/*` for a list) of the kind `kind`. An API's refusal
    carries its code, its reason and, unless the object is a Secret, the API's message. A failure
    with no API status names its type alone: a TLS or connect error's text names the API server's
    address, and a `DriverFailed`'s message reaches the run's events, which a client of the API
    reads. Its text is logged once, at DEBUG, where an operator can turn it on."""
    refusal = _refusal(error)
    if refusal is None:
        _log.debug("%s %s %s: %s: %s", call, kind, named, type(error).__name__, error)
        return KubeFailed(f"{call} {kind} {named}: {type(error).__name__}", None)
    code, reason, detail = refusal
    answer = " ".join(str(part) for part in (code, reason) if part is not None)
    shown = f": {detail[:MESSAGE_KEPT]}" if detail and kind != "Secret" else ""
    return KubeFailed(f"{call} {kind} {named}: {answer}{shown}", code)


def namespace_from(model: core_v1.Namespace) -> Namespace:
    """A namespace from lightkube's model."""
    metadata = model.metadata
    assert metadata is not None and metadata.name is not None, "the API answered a namespace with no name"
    return Namespace(name=metadata.name, labels=dict(metadata.labels or {}),
                     deleting=metadata.deletionTimestamp is not None)


def pod_from(model: core_v1.Pod) -> Pod:
    """A pod from lightkube's model."""
    metadata, status = model.metadata, model.status
    assert metadata is not None and metadata.name is not None, "the API answered a pod with no name"
    conditions = (status.conditions or []) if status else []
    containers = (status.containerStatuses or []) if status else []
    state = containers[0].state if containers else None
    last = containers[0].lastState if containers else None
    ended = bool(state and (state.terminated or (state.waiting and last and last.terminated)))
    return Pod(
        name=metadata.name,
        namespace=metadata.namespace or "",
        uid=metadata.uid or "",
        labels=dict(metadata.labels or {}),
        phase=(status.phase if status else None) or "",
        ready=any(c.type == "Ready" and c.status == "True" for c in conditions),
        deleting=metadata.deletionTimestamp is not None,
        created=metadata.creationTimestamp.isoformat() if metadata.creationTimestamp else "",
        restarts=containers[0].restartCount if containers else 0,
        container_running=bool(state and state.running),
        container_ended=ended,
        host=model.spec.nodeName if model.spec else None,
        requests=requests_of(model),
        ended=(status.phase if status else None) in ("Succeeded", "Failed"),
    )


def node_from(model: core_v1.Node) -> Node:
    """A node from lightkube's model; `ValueError` naming it when it reports no allocatable."""
    metadata, status = model.metadata, model.status
    assert metadata is not None and metadata.name is not None, "the API answered a node with no name"
    allocatable = (status.allocatable if status else None) or {}
    if "cpu" not in allocatable or "memory" not in allocatable:
        raise ValueError(f"the node {metadata.name} reports no allocatable cpu and memory")
    return Node(metadata.name, Resources(cpu(allocatable["cpu"]), mib(allocatable["memory"])))


def requests_of(model: core_v1.Pod) -> Resources:
    """The pod's effective request: Kubernetes' PodRequests, in init-container order, per resource.
    The containers' total is the sum over `spec.containers`. The init containers are walked in
    order, keeping the running sum of the restartable ones (`restartPolicy: Always`) seen so far:
    a restartable one adds its request to the containers' total and to the running sum, and its
    figure is the running sum; a non-restartable one's figure is its own request plus the running
    sum before it. The effective request is the larger of the containers' total and the largest
    init figure; where the pod sets its own `spec.resources.requests` (pod-level resources,
    Kubernetes 1.34 and later), its `cpu` and its `memory` each replace that figure for their
    resource; then `overhead` is added when set. A container with no request counts zero. Memory
    is summed in exact bytes and rounded down to MiB once, at the end, as `mib` rounds one quantity."""
    spec = model.spec
    if spec is None:
        return NO_REQUEST

    def asked(container: Any) -> tuple[Decimal, Decimal]:
        requests = (container.resources.requests if container.resources else None) or {}
        return (_quantity(requests["cpu"]) if "cpu" in requests else Decimal(0),
                _quantity(requests["memory"]) if "memory" in requests else Decimal(0))

    pairs = [asked(c) for c in spec.containers]
    total_cpu, total_memory = sum((p[0] for p in pairs), Decimal(0)), sum((p[1] for p in pairs), Decimal(0))
    side_cpu, side_memory = Decimal(0), Decimal(0)
    peak_cpu, peak_memory = Decimal(0), Decimal(0)
    for init in spec.initContainers or []:
        init_cpu, init_memory = asked(init)
        if init.restartPolicy == "Always":
            total_cpu, total_memory = total_cpu + init_cpu, total_memory + init_memory
            side_cpu, side_memory = side_cpu + init_cpu, side_memory + init_memory
            figure = (side_cpu, side_memory)
        else:
            figure = (init_cpu + side_cpu, init_memory + side_memory)
        peak_cpu, peak_memory = max(peak_cpu, figure[0]), max(peak_memory, figure[1])
    cores, memory = max(total_cpu, peak_cpu), max(total_memory, peak_memory)
    own = (spec.resources.requests if spec.resources else None) or {}
    if "cpu" in own:
        cores = _quantity(own["cpu"])
    if "memory" in own:
        memory = _quantity(own["memory"])
    overhead = spec.overhead or {}
    # Each is summed as the exact decimals it is written in, so that 250m and 50m make 0.3 and not 0.30000000000000004,
    # and two 1536M make 2929 MiB and not twice 1464.
    cores += _quantity(overhead["cpu"]) if "cpu" in overhead else 0
    memory += _quantity(overhead["memory"]) if "memory" in overhead else 0
    return Resources(float(cores), _mib(memory))


def _quantity(quantity: str) -> Decimal:
    """A Kubernetes quantity's value, `ValueError` for text that is none, a negative one or one out of range."""
    found = _QUANTITY.fullmatch(quantity)
    if found is None:
        raise ValueError(f"not a Kubernetes quantity: {quantity!r}")
    number, exponent, suffix = found.groups()
    if exponent is None and suffix not in _SUFFIXES:
        raise ValueError(f"not a Kubernetes quantity: {quantity!r}")
    try:
        value = Decimal(number + (exponent or "")) * (1 if exponent else _SUFFIXES[suffix])
    except ArithmeticError:  # InvalidOperation, Overflow
        raise ValueError(f"not a Kubernetes quantity: {quantity!r}") from None
    if value < 0:
        raise ValueError(f"a negative quantity: {quantity!r}")
    return value


def cpu(quantity: str) -> float:
    """A CPU quantity in cores: `500m` is 0.5, `2` is 2.0."""
    return float(_quantity(quantity))


def mib(quantity: str) -> int:
    """A memory quantity in mebibytes, rounded down: `1Gi` is 1024, `1536M` is 1464."""
    return _mib(_quantity(quantity))


def _mib(value: Decimal) -> int:
    """A number of bytes in mebibytes, rounded down."""
    return floor(value / 2**20)


def service_from(model: core_v1.Service) -> Service:
    """A Service from lightkube's model."""
    metadata, spec, status = model.metadata, model.spec, model.status
    assert metadata is not None and metadata.name is not None, "the API answered a Service with no name"
    ingress = (status.loadBalancer.ingress or []) if status and status.loadBalancer else []
    return Service(
        name=metadata.name,
        type=(spec.type if spec else None) or "",
        traffic_policy=spec.externalTrafficPolicy if spec else None,
        address=next((i.ip for i in ingress if i.ip), None),
    )


def _named(namespace: str | None, name: str) -> str:
    return f"{namespace}/{name}" if namespace else name


def _absent(error: Exception) -> bool:
    return isinstance(error, ApiError) and error.status.code == 404
