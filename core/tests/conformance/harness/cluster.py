"""`ClusterHarness` is the clabernetes driver's: the core deployed on the cluster, one pod under its
Lease (D-062), reached over TLS at the address the environment names, with the token of the
suite's principal; the cluster read and acted on through lightkube, each call a client of its
own. Its core is killed as a pod's host would lose it: cut off, its Lease left unreleased, and
deleted with no grace, so the Deployment's next pod takes the Lease once its duration has passed.
A node is replaced by its pod's deletion; a node stopped behind the core is not expressible there,
since clabernetes scales the node's Deployment back to one replica at once. A pod's log goes with
the pod, so the harness keeps it before each kill. Its `reach` is a TCP probe run by exec, from a
node's own pod or from a pod it makes in a third namespace, to each address the cluster gives a
node.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import ssl
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from lightkube import ApiError, AsyncClient
from lightkube.resources import coordination_v1, core_v1, networking_v1
from lightkube.types import PatchType

from conformance.harness import RESYNC_S, Mark, Resume, _Api
from conformance.reads import ROOT, TWINS, remove, wait_for
from fylgja_core import kubeapi, probe_package
from fylgja_core.clabernetes import OWNER, OWNER_LABEL, TWIN_LABEL, namespace_of
from fylgja_core.clabernetes.driver import RECREATE_ANNOTATION
from fylgja_core.clabernetes.kube import NODE_LABEL, LightKube, Pod, pod_from, service_from
from fylgja_core.client import InvalidAddress, InvalidToken, base_url, bearer
from fylgja_core.lease import DURATION_S, RENEW_S

CORE_NAMESPACE = "fylgja"
"""The deployed core's namespace where `FYLGJA_CONFORMANCE_NAMESPACE` is unset (D-062)."""
CLUSTER_VARIABLES = ("KUBECONFIG", "FYLGJA_API_ADDRESS", "FYLGJA_API_TOKEN", "FYLGJA_API_CA",
                     "FYLGJA_CONFORMANCE_SELECTOR")
"""What the cluster harness reads from the environment and cannot be made without."""
CUT_LABEL = "fylgja.reading"
"""The label a kill puts on the core's pod it cuts off, never the owner's: `CUT_POLICY` selects it."""
CUT_POLICY = "fylgja-conformance-cut"
"""The NetworkPolicy a kill makes in the core's namespace: every egress of a pod labelled
`CUT_LABEL` denied, no rule given; the kubelet's readiness probe is no egress, and still answers."""
KILL_ANNOTATION = "fylgja.reading/kill"
"""The annotation a kill writes on the core's Lease just before the holder's deletion: the
Lease's version moves, so the holder's release, written at the version it holds, is refused
`Conflict` and the Lease stays held by the pod that went (verified-facts.md)."""
RENEWED_S = (0.3, 3.0)
"""How far behind the Lease's last renewal a kill writes the Lease, by the workstation's clock
against the holder's (read within 0.05 s of each other): the holder renews every `RENEW_S` from
the send, so no renewal lands between the write and the release it refuses. The window is read on
the client that then writes and deletes, at once."""
OVERDUE_S = RENEW_S + 1.0
"""How far behind its last renewal the Lease is overdue, which a kill writes at too: the holder's
renewals have stopped under the cut, so none can land and no window will come (read: four of the
nine kills of the passing lifecycle run wrote at this mark, verified-facts.md; the explanation, not
read, is a renewal's connection opened anew, which the cut refuses)."""
TAKEN_S = 180.0
"""How long a kill waits for another pod of the core to be Ready: the Lease's 15 s from that
pod's first read of it, its start and its store's proof."""
SETTLED_S = 60.0
"""How long the cluster's audits give a twin's Services, Topology and pods to settle."""
ANSWER_S = 5.0
"""How long one ask of the core's version waits: the LoadBalancer's address drops what is sent
to it while no pod of the core is Ready (verified-facts.md), so an ask waits out its timeout."""
REACH = ("nc", "-z", "-w", "3")
"""The probe `reach` runs by exec in its source, the address and the port after it: BusyBox
1.37.0's `nc` in the ping package's image, which answers 0 where the connection was accepted and
1 where it was refused (0.09 to 1.17 s by exec) or not answered in 3 s (3.12 s), printing
nothing (verified-facts.md)."""
REACH_BUDGET_S = 15.0
"""The exec's budget for one probe: its 3 s, and the exec's own round trip many times over."""
PROBE_AGE_S = 15
"""How long a source's container has run before `reach` probes from it: k3s's network policy
controller learns a new pod late (D-037, verified-facts.md)."""
PROBE_NAMESPACE = "fylgja-conformance-probe"
"""The namespace of the pod `reach` probes from for a place of no twin: a third namespace, whose
pods a twin's policy admits no more than another twin's."""
PROBE_POD = "probe"
PROBE_LABEL = {"fylgja.conformance": "probe"}
"""The label of `PROBE_NAMESPACE` and its pod, never `OWNER_LABEL`: the core's watch and the
session's leftover checks pass them by."""
PROBE_S = 120.0
"""How long the probe's pod may take to run, and its namespace to go once deleted (read: 1.2 to
2.6 s, and 9.2 to 11.8 s)."""


def _selector(text: str) -> dict[str, str]:
    """`FYLGJA_CONFORMANCE_SELECTOR`'s labels: `key=value` pairs joined by commas, an equality
    selector; any other form is `pytest.UsageError` naming the variable."""
    pairs = [part.strip().partition("=") for part in text.split(",")]
    if not all(key and sep and value and not key.endswith("!") and "=" not in value for key, sep, value in pairs):
        raise pytest.UsageError("FYLGJA_CONFORMANCE_SELECTOR is not a label selector of key=value pairs")
    return {key: value for key, _, value in pairs}


def _tag(image: str | None) -> str:
    """The tag of the image `image`: what follows the last `:` past its registry and path, never
    those; `latest` where it names none, as a pull reads it."""
    last = (image or "").rsplit("/", 1)[-1]
    return last.rpartition(":")[2] if ":" in last else "latest"


async def _delete_namespace(name: str, client: AsyncClient) -> None:
    await LightKube(client).delete_namespace(name)


async def _apply(objects: Sequence[Mapping[str, Any]], client: AsyncClient) -> None:
    for obj in objects:
        await LightKube(client).apply(obj)


def _running_since(model: core_v1.Pod) -> datetime | None:
    """When the pod's one container last began to run; None while it does not."""
    statuses = (model.status.containerStatuses or []) if model.status is not None else []
    state = statuses[0].state if statuses else None
    return state.running.startedAt if state is not None and state.running is not None else None


def _probe_manifests() -> list[dict[str, Any]]:
    """`PROBE_NAMESPACE` and its pod `PROBE_POD`, each labelled `PROBE_LABEL`: the ping package's
    image (`probes/ping.yaml`), a public one, so pulled with no secret, running `sleep 3600` and
    never restarted, so one a session killed hard leaves stops within the hour, with no token of the
    API mounted and a second's grace."""
    image = probe_package.load(ROOT / "probes" / "ping.yaml").runtime.containerlab.image
    assert image.pull_secret is None, "the ping package's image is gated: the probe's pod would need its pull secret"
    namespace = {"apiVersion": "v1", "kind": "Namespace",
                 "metadata": {"name": PROBE_NAMESPACE, "labels": dict(PROBE_LABEL)}}
    pod = {"apiVersion": "v1", "kind": "Pod",
           "metadata": {"name": PROBE_POD, "namespace": PROBE_NAMESPACE, "labels": dict(PROBE_LABEL)},
           "spec": {"containers": [{"name": PROBE_POD, "image": image.ref, "command": ["sleep", "3600"]}],
                    "restartPolicy": "Never", "automountServiceAccountToken": False,
                    "terminationGracePeriodSeconds": 1}}
    return [namespace, pod]


def _between(first: str, then: str) -> float:
    """The seconds from the core's log line `first` to its line `then`, by their times."""
    times = [datetime.fromisoformat(json.loads(line)["time"]) for line in (first, then)]
    return (times[1] - times[0]).total_seconds()


def _since(at: datetime, line: str | None) -> str:
    """The seconds from `at` to the time of the core's log line `line`, its own clock's: a reading."""
    if line is None:
        return "never"
    return f"{(datetime.fromisoformat(json.loads(line)['time']) - at).total_seconds():+.2f}s"


@dataclass(eq=False)
class ClusterHarness(_Api):
    """The clabernetes driver's harness: the core deployed on the cluster, one pod under its Lease
    in `namespace`, found by the labels `selector`, and served over TLS at `api` with the token of
    the suite's principal; the cluster read and acted on through lightkube, each call one
    `asyncio.run` with a client of its own, made from `kubeconfig` (`kubeapi.client`), so that any
    thread may call. Everything of the site comes from the environment (`over`): the address, the
    token, the paths of the CA and the kubeconfig, and the values no log line may hold (`hidden`)
    are no part of its repr. `kept` holds this session's log lines of each pod of the core that
    went, a kill's or another's, since a pod's log goes with it; `reading` is the last read of the
    present pod's incarnation, `begun` the incarnation and the line the session began at;
    `readings` each kill's, printed again at the end, since a kill on a thread beside a waiting
    CLI prints into that CLI's captured output. `container` is the core's container, whose log is
    read; `served` that `start` found the core as the suite needs it; `probing` that `reach` has
    made its pod of no twin this session, and `probe_ran` the monotonic time it first read that
    pod's container running."""

    namespace: str
    selector: dict[str, str]
    api: str = field(repr=False)
    token: str = field(repr=False)
    ca: Path = field(repr=False)
    kubeconfig: str = field(repr=False)
    hidden: dict[str, str] = field(repr=False)
    pod: str | None = None
    container: str | None = None
    lease: str | None = None
    tag: str | None = None
    served: bool = False
    probing: bool = False
    probe_ran: float | None = field(default=None, repr=False)
    kills: list[float] = field(default_factory=list)
    readings: list[str] = field(default_factory=list, repr=False)
    kept: list[str] = field(default_factory=list, repr=False)
    http: httpx.Client | None = field(default=None, repr=False)
    context: ssl.SSLContext | None = field(default=None, repr=False)
    reading: tuple[tuple[str, int], list[str]] | None = field(default=None, repr=False)
    begun: tuple[tuple[str, int], int] | None = field(default=None, repr=False)

    @classmethod
    def over(cls) -> ClusterHarness:
        """The harness over the process's environment, read here and never passed in, so no frame
        shown holds it: a variable of `CLUSTER_VARIABLES` unset or empty is `pytest.UsageError`
        naming it, and so is an address that is no https:// URL, a token that is no bearer token
        (`bearer`: its header would otherwise reach an HTTP library that quotes it in its error),
        or a selector of another form, never with a value. Nothing is read from the cluster or the
        core, and nothing written."""
        for variable in CLUSTER_VARIABLES:
            if not os.environ.get(variable):
                raise pytest.UsageError(f"{variable} is not set: the cluster harness reads it from the environment")
        try:
            api = base_url(os.environ["FYLGJA_API_ADDRESS"])
        except InvalidAddress as e:  # its message is a predicate, never the address
            raise pytest.UsageError(f"FYLGJA_API_ADDRESS {e}") from None
        if not api.startswith("https://"):
            raise pytest.UsageError("FYLGJA_API_ADDRESS is not an https:// URL: the deployed core serves TLS (D-063)")
        try:
            bearer(os.environ["FYLGJA_API_TOKEN"])
        except InvalidToken as e:  # its message is a predicate, never the token
            raise pytest.UsageError(f"FYLGJA_API_TOKEN {e}") from None
        hidden = {"FYLGJA_API_TOKEN": os.environ["FYLGJA_API_TOKEN"]}
        hidden.update({name: value for name, value in os.environ.items()
                       if name.startswith("FYLGJA_CREDENTIAL_") and name.endswith("_PASSWORD")})
        if os.environ.get("FYLGJA_S3_SECRET_KEY"):
            hidden["FYLGJA_S3_SECRET_KEY"] = os.environ["FYLGJA_S3_SECRET_KEY"]
        return cls(namespace=os.environ.get("FYLGJA_CONFORMANCE_NAMESPACE") or CORE_NAMESPACE,
                   selector=_selector(os.environ["FYLGJA_CONFORMANCE_SELECTOR"]), api=api,
                   token=os.environ["FYLGJA_API_TOKEN"], ca=Path(os.environ["FYLGJA_API_CA"]),
                   kubeconfig=os.environ["KUBECONFIG"], hidden=hidden)

    @property
    def address(self) -> str:
        return self.api

    def _token(self) -> str:
        return self.token

    def _ca(self) -> Path | None:
        return self.ca

    def client(self) -> httpx.Client:
        assert self.http is not None, "the core was never started"
        return self.http

    def _kube[T](self, call: Callable[[AsyncClient], Awaitable[T]]) -> T:
        """`call`'s answer over a lightkube client of its own, closed after it, under one
        `asyncio.run`: lightkube's connections belong to the loop that opened them."""

        async def run() -> T:
            client = kubeapi.client({"KUBECONFIG": self.kubeconfig})
            try:
                return await call(client)
            finally:
                await client.close()

        return asyncio.run(run())

    def _verified(self) -> ssl.SSLContext:
        """The context the core's certificate is verified against, `FYLGJA_API_CA`'s, loaded once;
        `pytest.UsageError` naming the variable where it cannot be loaded."""
        context = self.context
        if context is None:
            try:
                context = ssl.create_default_context(cafile=str(self.ca))
            except (OSError, ssl.SSLError) as e:
                raise pytest.UsageError(f"FYLGJA_API_CA names no CA certificate that can be loaded "
                                        f"({type(e).__name__})") from None
            self.context = context
        return context

    def _connect(self) -> None:
        """The API's client, made anew: one a kill outlived holds connections to the pod that went.
        The token rides in its own headers, never in a call's arguments."""
        if self.http is not None:
            self.http.close()
        self.http = httpx.Client(base_url=self.api, verify=self._verified(), trust_env=False, timeout=30.0,
                                 headers={"Authorization": bearer(self.token)})

    def _answers(self) -> bool | None:
        """True once `GET /v1/version` answers 200 within `ANSWER_S`."""
        try:
            answer = httpx.get(f"{self.api}/v1/version", verify=self._verified(), timeout=ANSWER_S, trust_env=False)
        except httpx.TransportError:
            return None
        return True if answer.status_code == 200 else None

    # The core.

    def _core_pods(self) -> list[tuple[Pod, core_v1.Pod]]:
        """Each pod of the core the selector finds, not being deleted, as the driver reads a pod and
        as the API holds it."""

        async def read(client: AsyncClient) -> list[core_v1.Pod]:
            return [m async for m in client.list(core_v1.Pod, namespace=self.namespace, labels=dict(self.selector))]

        return [(pod, m) for m in self._kube(read) if not (pod := pod_from(m)).deleting]

    def _the_core(self) -> tuple[Pod, core_v1.Pod] | str:
        """The one pod of the core not being deleted, Ready; or why there is not one."""
        found = self._core_pods()
        if len(found) == 1 and found[0][0].ready:
            return found[0]
        shown = [(p.name, "Ready" if p.ready else "not Ready") for p, _ in found]
        return f"FYLGJA_CONFORMANCE_SELECTOR finds {shown} in {self.namespace}, not one pod of the core Ready"

    def start(self) -> None:
        """The core answers `GET /v1/version` within 60 s; the one pod the selector finds is
        Ready, its container's `env` holds `FYLGJA_RESYNC_S` as a literal of 3600 or more, and its
        image's tag (never the registry's name) is printed, the only record of the commit a run
        read; what a kill of an earlier session left is undone; then each of `TWINS` with a record
        is deleted through the API, printed, and waited for, and the session fails if anything of
        one is left by its label. The core's log, `log()`, is this session's from here. A CA that
        cannot be loaded, not one pod of the core Ready, or a resync below 3600 is
        `pytest.UsageError`, which ends the session in one line (conftest.py)."""
        began = time.monotonic()
        self._connect()
        wait_for(self._answers, "the core's answer at FYLGJA_API_ADDRESS", timeout_s=60, every_s=0.5)
        core = self._the_core()
        if isinstance(core, str):
            raise pytest.UsageError(core)
        pod, model = core
        assert model.spec is not None and model.spec.containers, "the API answered a pod with no container"
        container = model.spec.containers[0]
        env = {var.name: var for var in container.env or []}

        def literal(name: str) -> str | None:
            var = env.get(name)
            return var.value if var is not None and var.valueFrom is None else None

        resync = literal("FYLGJA_RESYNC_S")
        if resync is None or not resync.isdigit() or int(resync) < RESYNC_S:
            raise pytest.UsageError(f"the core's pod {pod.name} holds FYLGJA_RESYNC_S {resync or 'as no literal'} in "
                                    f"its env: the suite needs {RESYNC_S} or more, so that no pass a scenario reads "
                                    "was started by the resync (deploy/README.md, the overlay's patch)")
        self.pod, self.container, self.lease = pod.name, container.name, literal("FYLGJA_LEASE")
        self.tag, self.served = _tag(container.image), True
        undone = self._uncut()
        self._present()
        print(f"\n[conformance] the core: its pod {pod.name} Ready, its image's tag {self.tag}, FYLGJA_RESYNC_S "
              f"{resync}, answering {time.monotonic() - began:.2f}s after the start"
              f"{''.join(f'; {done}, left by an earlier kill' for done in undone)}", flush=True)
        for twin in TWINS:
            remove(self, twin)
        left = {twin: found for twin in TWINS if (found := self.leftovers(twin))}
        if left:
            pytest.fail(f"the cluster holds the suite's twins after their records went: {left}", pytrace=False)

    def kill(self) -> float:
        """The core's pod lost as its host would lose it, and the Deployment's next pod serving in
        its place: the holder is labelled `CUT_LABEL` and cut off by `CUT_POLICY`, and its log is
        kept; then, once the Lease's last renewal lies `RENEWED_S` behind, the Lease is written
        (`KILL_ANNOTATION`) so the release its SIGTERM handler writes is refused, and the pod is
        deleted with a grace period of 0, at once, on the client that read the window; once one pod
        of another uid is Ready the cut is undone, that pod's log read and the kill printed, and it
        returns as the version answers, with nothing after, so that a waiting CLI cannot end
        between the answer and the return. The next pod waits for the Lease, which the pod that
        went holds, and takes it once its duration has passed (D-071): the test fails where it did
        not wait, or held it sooner than the duration (`DURATION_S`, less 1 s) after it began
        waiting. The seconds from the deletion to that pod's first answer.

        A forced delete alone is no kill: the kubelet still sends SIGTERM and the holder releases
        the Lease; nor is the cut alone, since its renewals and its release ride the connection it
        holds to the API, which the policy leaves open (verified-facts.md)."""
        core = self._the_core()
        if isinstance(core, str):
            pytest.fail(core, pytrace=False)
        pod, _ = core
        lease = self.lease
        if lease is None:
            pytest.fail(f"the core's pod {pod.name} names no Lease as a literal FYLGJA_LEASE: nothing to kill it by",
                        pytrace=False)
        number = len(self.kills) + 1
        try:
            self._kube(lambda c: c.patch(core_v1.Pod, pod.name, {"metadata": {"labels": {CUT_LABEL: "cut"}}},
                                         namespace=self.namespace, patch_type=PatchType.MERGE))
            self._kube(lambda c: LightKube(c).apply(self._cut_policy()))
            kept = self._present()
            self.kept.extend(kept)
            self.reading = None
            renewed, written = self._kube(functools.partial(self._written, lease, pod.name, number))
            deleted, deleted_at = time.monotonic(), datetime.now(UTC)
            other = self._kube(functools.partial(self._next, pod.uid))
            ready = time.monotonic() - deleted
        finally:
            self._uncut()
        self.pod = other.name
        said = self._present()
        waited = next((line for line in said if f"waiting for the Lease {lease}, held by {pod.name}" in line), None)
        holding = next((line for line in said if f"holding the Lease {lease} as {other.name}" in line), None)
        reading = (f"the core killed ({number}): its pod {pod.name} cut and {len(kept)} lines of its log kept, the "
                   f"Lease written {(written - renewed).total_seconds():.2f}s after its last renewal and the pod "
                   f"deleted with no grace; from the deletion, the pod {other.name} waited for the Lease "
                   f"{_since(deleted_at, waited)} and held it {_since(deleted_at, holding)} "
                   f"({_since(renewed, holding)} after the last renewal), Ready {ready:.2f}s")
        self.readings.append(reading)
        print(f"\n[conformance] {reading}", flush=True)
        if waited is None:
            pytest.fail(f"the core's pod {other.name} did not wait for the Lease held by {pod.name}: it was released, "
                        "and the kill was a graceful restart", pytrace=False)
        took = None if holding is None else _between(waited, holding)
        if took is None or took < DURATION_S - 1:
            pytest.fail(f"the core's pod {other.name} held the Lease {'never' if took is None else f'{took:.2f}s'} "
                        f"after it began waiting for it, not its duration of {DURATION_S}s: it was released, and the "
                        "kill was a graceful restart", pytrace=False)
        self._connect()
        wait_for(self._answers, "the core's answer after the kill", timeout_s=60, every_s=0.25)
        back = time.monotonic() - deleted
        self.kills.append(back)
        self.readings[-1] += f", answering {back:.2f}s"
        return back

    async def _written(self, lease: str, pod: str, number: int, client: AsyncClient) -> tuple[datetime, datetime]:
        """Once the Lease's last renewal lies within `RENEWED_S` behind, or `OVERDUE_S` or more
        (within three renewals, the test failed otherwise), the Lease written with `KILL_ANNOTATION`
        and the pod `pod` deleted with a grace period of 0, at once, on this one client: the last
        renewal, and when the write was sent."""
        deadline = time.monotonic() + 3 * RENEW_S
        while True:
            held = await client.get(coordination_v1.Lease, lease, namespace=self.namespace)
            renewed = held.spec.renewTime if held.spec is not None else None
            if renewed is not None:
                behind = (datetime.now(UTC) - renewed).total_seconds()
                if RENEWED_S[0] <= behind <= RENEWED_S[1] or behind >= OVERDUE_S:
                    break
            assert time.monotonic() < deadline, f"the Lease {lease} was not renewed within {3 * RENEW_S}s"
            await asyncio.sleep(0.05)
        written = datetime.now(UTC)
        await client.patch(coordination_v1.Lease, lease, {"metadata": {"annotations": {KILL_ANNOTATION: str(number)}}},
                           namespace=self.namespace, patch_type=PatchType.MERGE)
        await client.delete(core_v1.Pod, pod, namespace=self.namespace, grace_period=0)
        return renewed, written

    async def _next(self, gone: str, client: AsyncClient) -> Pod:
        """The pod of the core of another uid than `gone`, once it is Ready; within `TAKEN_S`."""
        deadline = time.monotonic() + TAKEN_S
        while True:
            found = [p for p in await LightKube(client).pods(self.namespace, self.selector)
                     if p.uid != gone and p.ready and not p.deleting]
            if found:
                return found[0]
            assert time.monotonic() < deadline, f"no other pod of the core was Ready within {TAKEN_S:g}s of the kill"
            await asyncio.sleep(0.25)

    def _cut_policy(self) -> dict[str, Any]:
        return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
                "metadata": {"name": CUT_POLICY, "namespace": self.namespace},
                "spec": {"podSelector": {"matchLabels": {CUT_LABEL: "cut"}}, "policyTypes": ["Egress"]}}

    def _uncut(self) -> list[str]:
        """What a kill makes, undone wherever it is left: `CUT_POLICY` deleted, `CUT_LABEL` taken off
        each pod of the core's namespace carrying it, `KILL_ANNOTATION` taken off the Lease, where
        there is one. What was done, each a short description."""
        lease = self.lease

        async def undo(client: AsyncClient) -> list[str]:
            done: list[str] = []
            try:
                await client.delete(networking_v1.NetworkPolicy, CUT_POLICY, namespace=self.namespace)
                done.append(f"the NetworkPolicy {CUT_POLICY} deleted")
            except ApiError as e:
                if e.status.code != 404:
                    raise
            async for model in client.list(core_v1.Pod, namespace=self.namespace, labels={CUT_LABEL: "cut"}):
                assert model.metadata is not None and model.metadata.name is not None
                await client.patch(core_v1.Pod, model.metadata.name, {"metadata": {"labels": {CUT_LABEL: None}}},
                                   namespace=self.namespace, patch_type=PatchType.MERGE)
                done.append(f"the label {CUT_LABEL} taken off the pod {model.metadata.name}")
            if lease is not None:
                try:
                    held = await client.get(coordination_v1.Lease, lease, namespace=self.namespace)
                except ApiError as e:
                    if e.status.code != 404:
                        raise
                    return done  # no Lease, so no annotation to take off
                if held.metadata is not None and KILL_ANNOTATION in (held.metadata.annotations or {}):
                    await client.patch(coordination_v1.Lease, lease,
                                       {"metadata": {"annotations": {KILL_ANNOTATION: None}}},
                                       namespace=self.namespace, patch_type=PatchType.MERGE)
                    done.append(f"the annotation {KILL_ANNOTATION} taken off the Lease {lease}")
            return done

        return self._kube(undo)

    def close(self, twins: Iterable[str]) -> None:
        """Each of `twins` destroyed through the API if it is still there, once the core answers;
        then the cleanup, each step run whatever the one before did: what a kill made undone,
        `PROBE_NAMESPACE` deleted and waited for (`_unprobe`; said to be an earlier session's where
        this one never probed), any namespace still labelled for one of the twins deleted, the
        session's end printed, and the API's client closed. The session fails for a twin's namespace
        or the probe's still there, and for a step that raised, named by its exception's type alone,
        since its text could quote an address. A session whose `start` refused the core made
        nothing, and asks nothing of the core or the cluster."""
        twins = tuple(twins)
        if not self.served:
            if self.http is not None:
                self.http.close()
            return
        try:
            wait_for(self._answers, "the core's answer at the session's end", timeout_s=TAKEN_S, every_s=0.5)
            for twin in twins:
                remove(self, twin)
        finally:
            failed: list[str] = []

            def step[T](what: str, call: Callable[[], T]) -> T | None:
                try:
                    return call()
                except (Exception, pytest.fail.Exception) as e:  # its type alone: its text could quote an address
                    failed.append(f"{what} raised {type(e).__name__}")
                    return None

            undone = step("undoing a kill", self._uncut) or []
            unprobed = step(f"deleting {PROBE_NAMESPACE}", self._unprobe)
            if unprobed is not None:
                undone.append(unprobed if self.probing else f"{unprobed}, left by an earlier session")
            stayed = step(f"reading {PROBE_NAMESPACE}", lambda: self._namespaces(PROBE_LABEL)) or []
            left = step("deleting the twins' namespaces", functools.partial(self._swept, twins)) or {}

            def ended() -> None:
                print(f"\n[conformance] the core's image's tag {self.tag}; kills, each to the next pod's answer: "
                      f"{', '.join(f'{s:.2f}s' for s in self.kills) or 'none'}; lines kept of the pods that went: "
                      f"{len(self.kept)}{''.join(f'; {done}' for done in undone)}"
                      f"{''.join(f'\n[conformance]   {reading}' for reading in self.readings)}", flush=True)

            step("printing the session's end", ended)
            if self.http is not None:
                step("closing the API's client", self.http.close)
            dirty = (([f"{left}, each namespace now deleted"] if left else [])
                     + ([f"the probe's namespaces {stayed}, labelled {PROBE_LABEL}"] if stayed else []) + failed)
            if dirty:
                pytest.fail(f"the teardown did not leave the cluster clean: {'; '.join(dirty)}", pytrace=False)

    def _swept(self, twins: Sequence[str]) -> dict[str, list[str]]:
        """Each namespace still labelled for one of `twins`, by its twin, deleted."""
        left = {twin: names for twin in twins if (names := self._namespaces({TWIN_LABEL: twin}))}
        for name in [name for names in left.values() for name in names]:
            self._kube(functools.partial(_delete_namespace, name))
        return left

    # The runtime.

    def _namespaces(self, labels: Mapping[str, str]) -> list[str]:
        """The name of each namespace carrying every label of `labels`, one being deleted included."""

        async def read(client: AsyncClient) -> list[str]:
            return [m.metadata.name async for m in client.list(core_v1.Namespace, labels=dict(labels))
                    if m.metadata is not None and m.metadata.name is not None]

        return sorted(self._kube(read))

    def nodes(self, twin: str) -> dict[str, str]:
        """Each node of the twin in `namespace_of(twin)`, by its pods' `NODE_LABEL`, with the
        incarnation the driver writes, `<uid>/<restarts>` (D-069), of the pod that stands for it as
        the driver reads it: its newest not being deleted, or the newest where every one is."""
        pods = self._kube(lambda c: LightKube(c).pods(namespace_of(twin), {OWNER_LABEL: OWNER, TWIN_LABEL: twin}))
        found: dict[str, str] = {}
        for node in sorted({p.labels[NODE_LABEL] for p in pods if p.labels.get(NODE_LABEL)}):
            mine = [p for p in pods if p.labels.get(NODE_LABEL) == node]
            standing = max([p for p in mine if not p.deleting] or mine, key=lambda p: (p.created, p.name))
            found[node] = f"{standing.uid}/{standing.restarts}"
        return found

    def twins(self) -> set[str]:
        """The `TWIN_LABEL` of every namespace labelled `OWNER_LABEL=OWNER`, as the driver makes each."""

        async def read(client: AsyncClient) -> set[str]:
            found = set()
            async for m in client.list(core_v1.Namespace, labels={OWNER_LABEL: OWNER}):
                twin = ((m.metadata.labels if m.metadata is not None else None) or {}).get(TWIN_LABEL)
                if twin:
                    found.add(twin)
            return found

        return self._kube(read)

    def leftovers(self, twin: str) -> list[str]:
        """`namespace <name>` for each namespace labelled `TWIN_LABEL=<twin>`, one being deleted
        included: the driver's whole twin is its namespace."""
        return [f"namespace {name}" for name in self._namespaces({TWIN_LABEL: twin})]

    def _standing(self, twin: str, node: str) -> Pod:
        """The pod that stands for `node` of `twin` and is not being deleted (`_stands`)."""
        pod, _ = self._kube(functools.partial(self._stands, twin, node))
        return pod

    async def _stands(self, twin: str, node: str, client: AsyncClient) -> tuple[Pod, core_v1.Pod]:
        """The pod that stands for `node` of `twin`, as the driver's `exec` and `inspect` find it
        (`_current`): its newest not being deleted, by creation time and then by name; as the
        driver reads a pod, and as the API holds it."""
        labels: dict[str, Any] = {OWNER_LABEL: OWNER, TWIN_LABEL: twin, NODE_LABEL: node}
        mine = [(p, m) async for m in client.list(core_v1.Pod, namespace=namespace_of(twin), labels=labels)
                if not (p := pod_from(m)).deleting]
        assert mine, f"the cluster holds no pod of {node} of {twin} not being deleted"
        return max(mine, key=lambda found: (found[0].created, found[0].name))

    def replace_node(self, twin: str, node: str) -> None:
        """The pod that stands for the node deleted, with its grace, as a host's loss of it would
        go, until `nodes(twin)[node]` names another: its Deployment makes the next at once
        (verified-facts.md, "a node's pod deleted behind the core")."""
        pod = self._standing(twin, node)
        was = f"{pod.uid}/{pod.restarts}"
        began = time.monotonic()
        self._kube(lambda c: LightKube(c).delete_pod(namespace_of(twin), pod.name))
        wait_for(lambda: True if self.nodes(twin).get(node) not in (None, was) else None,
                 f"{node}'s next pod", timeout_s=60, every_s=0.2)
        print(f"\n[conformance] {node} of {twin}: its pod {pod.name} deleted, the next there "
              f"{time.monotonic() - began:.2f}s after", flush=True)

    def stop_node(self, twin: str, node: str) -> None:
        """Not expressible on this cluster: the node's Deployment is owned by clabernetes' `Node`,
        which scales it back to one replica at once (verified-facts.md, "the conformance suite's
        cluster harness"), so no node stays stopped."""
        raise NotImplementedError(
            "a stopped node is not expressible on clabernetes 0.10.1: its Node scales the node's Deployment back to "
            "one replica within 1.3 s of a scale to none, and the next pod is restored (verified-facts.md)")

    def reach(self, frm: tuple[str, str] | None, to: tuple[str, str], port: int) -> dict[str, bool]:
        """Whether `REACH` to `port` answers 0, by each path the cluster gives the node `to`: `pod`,
        the address of the pod that stands for it; `service`, the cluster address of the Service
        of its name, its LoadBalancer; and `loadbalancer`, that Service's LoadBalancer address, the
        one the twin record holds (a node that declares no port has no such Service, and `pod`
        alone). The source is the pod that stands for the node `frm`, the probe run in its one
        container as the driver's `exec` runs a command, naming none (verified-facts.md), or for
        None the pod `PROBE_POD` of `PROBE_NAMESPACE`, made at first use (`_probe`); it has run
        `PROBE_AGE_S` or more before the first probe, waited for (`_probed` says from when). A probe
        is accepted on status 0 and refused on 1 with nothing on either stream, as read
        (verified-facts.md); any other answer, or a probe that cannot be run, fails the test as a
        probe not run, by the harness's reason or the exception's type alone, since the command
        holds the address. Each path's answer and seconds are printed, never an address."""
        twin, node = to
        if frm is None:
            namespace, pod, source = PROBE_NAMESPACE, self._probe(), f"the pod {PROBE_POD} of {PROBE_NAMESPACE}"
            ran_from = self.probe_ran
        else:
            namespace, pod, source = namespace_of(frm[0]), self._standing(*frm).name, f"{frm[1]} of {frm[0]}"
            ran_from = None
        try:
            aged, probed = self._kube(functools.partial(self._probed, namespace, pod, ran_from, twin, node, port))
        except AssertionError as e:  # the harness's own reason, which names no address
            pytest.fail(f"a probe from {source} to {node} of {twin} on {port} was not run: {e}", pytrace=False)
        except Exception as e:  # its frames hold the probe's command, the address in it: never shown
            pytest.fail(f"a probe from {source} to {node} of {twin} on {port} was not run: {type(e).__name__}",
                        pytrace=False)
        said = ", ".join(f"{path} {'accepted' if accepted else 'refused'} in {took:.2f}s"
                         for path, accepted, took in probed)
        print(f"\n[conformance] from {source}, {aged:.1f}s old, to {node} of {twin} on {port}: {said}", flush=True)
        return {path: accepted for path, accepted, _ in probed}

    async def _probed(self, namespace: str, pod: str, ran_from: float | None, twin: str, node: str, port: int,
                      client: AsyncClient) -> tuple[float, list[tuple[str, bool, float]]]:
        """From the pod `pod` of `namespace`, its container running, once it has run `PROBE_AGE_S`:
        `REACH` to each path of `node` of `twin` on `port` (`_paths`), by exec naming no container,
        each path with whether it was accepted (status 0) or refused (1, nothing on either stream),
        and the probe's seconds; and the source's age at the first. Any other answer fails, naming
        its status and its streams' lengths, never what they hold.

        The age of the probe's own pod is measured on this host's monotonic clock alone, from
        `ran_from`, `_probe`'s first read of its container running; a node's pod has no such read,
        and its age is its container's `startedAt`, the kubelet's clock, against this host's (the
        two agreed within 0.05 s, verified-facts.md)."""
        started = _running_since(await client.get(core_v1.Pod, pod, namespace=namespace))
        assert started is not None, f"the source's pod {pod} has no container running"

        def age() -> float:
            if ran_from is not None:
                return time.monotonic() - ran_from
            return (datetime.now(UTC) - started).total_seconds()

        if (aged := age()) < PROBE_AGE_S:
            await asyncio.sleep(PROBE_AGE_S - aged)
            aged = age()
        kube, probed = LightKube(client), []
        for path, address in (await self._paths(twin, node, client)).items():
            began = time.monotonic()
            answer = await kube.exec(namespace, pod, [*REACH, address, str(port)], REACH_BUDGET_S)
            took = time.monotonic() - began
            refused = answer.returncode == 1 and not answer.stdout and not answer.stderr
            assert answer.returncode == 0 or refused, \
                (f"the probe to its {path} answered status {answer.returncode}, with {len(answer.stdout)} characters "
                 f"on stdout and {len(answer.stderr)} on stderr: neither accepted nor refused")
            probed.append((path, answer.returncode == 0, took))
        return aged, probed

    async def _paths(self, twin: str, node: str, client: AsyncClient) -> dict[str, str]:
        """Each path the cluster gives `node` of `twin`, by its name, with its address: `pod`, the
        pod that stands for it (`_stands`); `service` and `loadbalancer`, the cluster address and
        the LoadBalancer address of the Service of its name (`service_from`, as the driver reads
        one), where it has one."""
        namespace = namespace_of(twin)
        _, model = await self._stands(twin, node, client)
        address = model.status.podIP if model.status is not None else None
        assert address, f"the pod of {node} of {twin} has no address yet"
        try:
            service = await client.get(core_v1.Service, node, namespace=namespace)
        except ApiError as e:
            if e.status.code != 404:
                raise
            return {"pod": address}
        cluster = service.spec.clusterIP if service.spec is not None else None
        balanced = service_from(service).address
        assert cluster and cluster != "None" and balanced, \
            f"the Service {node} of {twin} has no cluster address or no LoadBalancer address"
        return {"pod": address, "service": cluster, "loadbalancer": balanced}

    def _probe(self) -> str:
        """The pod `PROBE_POD`, made at first use with its namespace (`_probe_manifests`), once what
        an earlier session left of them is gone (`_unprobe`), and waited for until its container
        runs, within `PROBE_S`, the monotonic time of that first read kept in `probe_ran`; printed.
        `close` deletes its namespace."""
        if not self.probing:
            self.probing = True
            began = time.monotonic()
            left = self._unprobe()
            self._kube(functools.partial(_apply, _probe_manifests()))

            def runs() -> float | None:
                model = self._kube(lambda c: c.get(core_v1.Pod, PROBE_POD, namespace=PROBE_NAMESPACE))
                return time.monotonic() if _running_since(model) is not None else None

            self.probe_ran = wait_for(runs, f"the pod {PROBE_POD} of {PROBE_NAMESPACE} running", timeout_s=PROBE_S,
                                      every_s=0.5)
            print(f"\n[conformance] the pod {PROBE_POD} of {PROBE_NAMESPACE}, of no twin, running "
                  f"{time.monotonic() - began:.2f}s after it was asked"
                  f"{f'; {left}, left by an earlier session' if left else ''}", flush=True)
        return PROBE_POD

    def _unprobe(self) -> str | None:
        """`PROBE_NAMESPACE` deleted where it is, and waited for until it is gone, within `PROBE_S`:
        what was done, or None where there was none. A namespace of that name without
        `PROBE_LABEL` is not the suite's: it is left, and the test fails."""

        async def unprobe(client: AsyncClient) -> str | None:
            kube = LightKube(client)
            found = await kube.namespace(PROBE_NAMESPACE)
            if found is None:
                return None
            assert all(found.labels.get(key) == value for key, value in PROBE_LABEL.items()), \
                f"the namespace {PROBE_NAMESPACE} is not the suite's: it lacks the label {PROBE_LABEL}"
            began = time.monotonic()
            await kube.delete_namespace(PROBE_NAMESPACE)
            while await kube.namespace(PROBE_NAMESPACE) is not None:
                if time.monotonic() - began > PROBE_S:
                    return f"the namespace {PROBE_NAMESPACE} deleted, and not gone {PROBE_S:g}s after"
                await asyncio.sleep(0.5)
            return f"the namespace {PROBE_NAMESPACE} deleted, gone {time.monotonic() - began:.1f}s after"

        return self._kube(unprobe)

    # The core's log.

    def _present(self) -> list[str]:
        """This session's log lines of the core's present pod (its Ready one, else its newest),
        of its container's present incarnation, `<uid>/<restarts>`: what was last read of an
        incarnation that has gone since (a container restarted in its pod, a pod gone otherwise
        than by `kill`) is kept first, the lines it logged after that read lost with it."""
        pods = [p for p in self._kube(lambda c: LightKube(c).pods(self.namespace, self.selector)) if not p.deleting]
        if not pods:
            return []
        pod = max(pods, key=lambda p: (p.ready, p.created, p.name))
        incarnation = (pod.uid, pod.restarts)

        async def read(client: AsyncClient) -> list[str]:
            try:
                return [line async for line in client.log(pod.name, namespace=self.namespace, container=self.container,
                                                          newlines=False)]
            except ApiError as e:
                if e.status.code == 400:  # the core's container, named, not started yet: no log
                    return []
                raise

        lines = self._kube(read)
        if self.begun is None:
            self.begun = (incarnation, len(lines))
        if self.begun[0] == incarnation:
            lines = lines[self.begun[1]:]
        if self.reading is not None and self.reading[0] != incarnation:
            self.kept.extend(self.reading[1])
        self.reading = (incarnation, lines)
        return lines

    def log(self) -> list[str]:
        """The lines kept of each pod of the core that went, then this session's of the present one."""
        present = self._present()
        return [*self.kept, *present]

    def mark(self) -> Mark:
        return len(self.log())

    def secrets(self) -> Mapping[str, str]:
        """The token, each node's password the environment holds, and the store's secret key where
        it holds one (the workstation's does not: the store's keys are the pod's)."""
        return dict(self.hidden)

    # The audits: what only the cluster's account shows.

    def _settled(self, twin: str, what: str) -> None:
        """Within `SETTLED_S`: every LoadBalancer Service of the twin's namespace at
        `externalTrafficPolicy: Local` (D-037), its Topology carrying no `RECREATE_ANNOTATION`, and
        each node one pod, none being deleted; printed."""
        namespace, began = namespace_of(twin), time.monotonic()

        async def read(client: AsyncClient) -> str | None:
            kube = LightKube(client)
            services, topology = await kube.services(namespace), await kube.topology(namespace, twin)
            pods = await kube.pods(namespace, {OWNER_LABEL: OWNER, TWIN_LABEL: twin})
            astray = [s.name for s in services if s.type == "LoadBalancer" and s.traffic_policy != "Local"]
            annotations = ((topology or {}).get("metadata") or {}).get("annotations") or {}
            each: dict[str, list[Pod]] = {}
            for pod in pods:
                each.setdefault(pod.labels.get(NODE_LABEL, ""), []).append(pod)
            unsettled = {node: [p.name for p in held] for node, held in each.items()
                         if len(held) != 1 or held[0].deleting}
            if topology is None or astray or RECREATE_ANNOTATION in annotations or unsettled or not each:
                return (f"the Topology {'absent' if topology is None else 'present'}, "
                        f"{RECREATE_ANNOTATION} {'present' if RECREATE_ANNOTATION in annotations else 'absent'}, "
                        f"Services not at Local {astray}, nodes not at one pod {unsettled}, nodes {sorted(each)}")
            lb = sum(1 for s in services if s.type == "LoadBalancer")
            print(f"[conformance] {twin}{what}: {lb} LoadBalancer Services at Local, the Topology with no "
                  f"{RECREATE_ANNOTATION}, {len(each)} nodes each at one pod, {time.monotonic() - began:.1f}s after "
                  "the audit began", flush=True)
            return None

        last: list[str | None] = [None]

        def settled() -> bool | None:
            last[0] = self._kube(read)
            return True if last[0] is None else None

        try:
            wait_for(settled, f"{twin} settled in the cluster", timeout_s=SETTLED_S, every_s=1.0)
        except AssertionError:
            pytest.fail(f"{twin} did not settle in the cluster within {SETTLED_S:g}s: {last[0]}", pytrace=False)

    def audit_apply(self, twin: str, since: Mark, applies: int) -> None:
        self._settled(twin, f", {applies} apply started")

    def audit_resume(self, twin: str, since: Mark, resume: Resume) -> None:
        """`_settled`, after printing what the core's log says it resumed since `since`."""
        resumed = []
        for line in self.log()[since:]:
            try:
                said = json.loads(line).get("message")
            except (ValueError, AttributeError):
                continue
            if isinstance(said, str) and " resumed after " in said:
                resumed.append(said)
        print(f"[conformance] {twin}: the core's log says {resumed or 'nothing resumed'}", flush=True)
        self._settled(twin, f"'s {resume.operation} resumed after the kill, {resume.applies} apply started")

    def audit_destroy(self, twin: str, since: Mark, unnamed: Sequence[str] = (), stray: bool = False) -> None:
        """Prints alone: the driver's destroy is its namespace's deletion, which `leftovers` reads."""
        print(f"[conformance] {twin}'s destroy: the cluster holds {self.leftovers(twin) or 'nothing'} of it"
              f"{f'; {sorted(unnamed)} among it' if unnamed else ''}", flush=True)
