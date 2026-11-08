"""The clabernetes driver's reach into Kubernetes (D-057, D-064), with no cluster: a failure
becomes a `KubeFailed` naming the call and the object, never the API's message over a Secret,
and never a transport error's text, which is logged at DEBUG alone; lightkube's models read as
the three dataclasses; `apply` names its field manager whatever client it is given; the pod
watch watches again after the seam's backoff, which an event resets, logs a failure by its type
and status code alone, and closes its response when it is closed; and `exec` keeps the tail of
each stream. mypy holds `LightKube` to `Kube`. The calls are read on the cluster in
tests/cluster/test_kube_cluster.py; the client is made by `fylgja_core.kubeapi`
(test_kubeapi.py)."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping
from typing import Any

import httpx2
import pytest
from aio import bounded, cancelled, closed
from lightkube import ApiError, AsyncClient, KubeConfig, codecs
from lightkube.models.meta_v1 import Status
from lightkube.resources.core_v1 import Pod as PodModel
from lightkube.resources.core_v1 import Service as ServiceModel
from lightkube.types import OnErrorAction

from fylgja_core import kubeapi, logs
from fylgja_core.clabernetes import kube
from fylgja_core.clabernetes.driver import ClabernetesDriver
from fylgja_core.containerlab import driver as containerlab_driver
from fylgja_core.credentials import Provider
from fylgja_core.driver import DriverFailed

KUBECONFIG = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [{"name": "example", "cluster": {"server": "https://kube.example:6443"}}],
    "users": [{"name": "example", "user": {"token": "not-a-token"}}],
    "contexts": [{"name": "example", "context": {"cluster": "example", "user": "example"}}],
    "current-context": "example",
}
POLICY = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {"name": "isolate", "namespace": "fylgja-twin-t"},
    "spec": {"podSelector": {}},
}
SECRET = {
    "apiVersion": "v1",
    "kind": "Secret",
    "metadata": {"name": "fylgja-pull-arista-ceos", "namespace": "fylgja-twin-t"},
    "type": "kubernetes.io/dockerconfigjson",
    "data": {".dockerconfigjson": "e30="},
}
FORBIDDEN = 'namespaces "x" is forbidden'

Handler = Callable[[httpx2.Request], httpx2.Response]


def refusing(code: int, reason: str, message: str) -> Handler:
    """An API server that answers every request with the Status `code`, `reason`, `message`."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(code, json={"kind": "Status", "apiVersion": "v1", "metadata": {}, "status": "Failure",
                                           "message": message, "reason": reason, "code": code})

    return handler


def raising(error: Exception) -> Handler:
    """A transport that raises `error` for every request."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    return handler


def reaching(handler: Handler) -> kube.LightKube:
    """`LightKube` over a transport answering by `handler`."""
    return kube.LightKube(AsyncClient(config=KubeConfig.from_dict(KUBECONFIG), field_manager=kubeapi.FIELD_MANAGER,
                                      transport=httpx2.MockTransport(handler)))


def _conforms(client: AsyncClient) -> kube.Kube:
    # Never called: mypy holds `LightKube` to the protocol the driver acts through.
    return kube.LightKube(client)


def applied(handler: Handler, obj: Mapping[str, Any]) -> kube.KubeFailed:
    """The failure `LightKube.apply` of `obj` raises over a transport answering by `handler`."""

    async def apply() -> None:
        reach = reaching(handler)
        try:
            await reach.apply(obj)
        finally:
            await reach.close()

    with pytest.raises(kube.KubeFailed) as raised:
        asyncio.run(apply())
    return raised.value


def test_an_api_refusal_is_a_driver_failure_naming_the_call_the_object_and_the_apis_message() -> None:
    failed = applied(refusing(403, "Forbidden", FORBIDDEN), POLICY)
    assert isinstance(failed, DriverFailed)
    assert failed.status == 403
    assert str(failed) == f"apply NetworkPolicy fylgja-twin-t/isolate: 403 Forbidden: {FORBIDDEN}"


def test_the_apis_message_is_cut_to_its_first_200_characters() -> None:
    failed = applied(refusing(422, "Invalid", "x" * 300), POLICY)
    assert str(failed) == "apply NetworkPolicy fylgja-twin-t/isolate: 422 Invalid: " + "x" * 200


def test_a_refusal_over_a_secret_never_carries_the_apis_message() -> None:
    failed = applied(refusing(403, "Forbidden", FORBIDDEN), SECRET)
    assert failed.status == 403
    assert str(failed) == "apply Secret fylgja-twin-t/fylgja-pull-arista-ceos: 403 Forbidden"
    # Nor does its traceback: lightkube's error, whose text is the API's message, is not chained.
    assert FORBIDDEN not in "".join(traceback.format_exception(failed))


@pytest.mark.parametrize("error", [httpx2.ConnectError("connection refused"), httpx2.ReadTimeout("timed out")],
                         ids=lambda e: type(e).__name__)
def test_a_transport_failure_is_a_driver_failure_with_no_status_naming_the_errors_type_alone(error: Exception) -> None:
    for obj, named in ((POLICY, "NetworkPolicy fylgja-twin-t/isolate"),
                       (SECRET, "Secret fylgja-twin-t/fylgja-pull-arista-ceos")):
        failed = applied(raising(error), obj)
        assert isinstance(failed, DriverFailed)
        assert failed.status is None
        assert str(failed) == f"apply {named}: {type(error).__name__}"
        # Nor does its traceback carry the error's text: lightkube's error is not chained.
        assert str(error) not in "".join(traceback.format_exception(failed))


@pytest.mark.parametrize("obj", [POLICY, SECRET], ids=lambda obj: obj["kind"])
def test_a_transport_failures_text_is_logged_once_at_debug_and_never_reaches_its_failure(
    obj: Mapping[str, Any], caplog: pytest.LogCaptureFixture,
) -> None:
    """A TLS or connect error's text names the API server's address, and a `DriverFailed`'s message reaches the run's
    events, which a client of the API reads: the failure names the error's type alone, and the text is logged once,
    at DEBUG on the driver's logger, where an operator can turn it on."""
    caplog.set_level(logging.DEBUG, logger="fylgja.clabernetes")
    marker = "192.0.2.1"
    error = httpx2.ConnectError(f"certificate verify failed: IP address mismatch, certificate is not valid for "
                                f"'{marker}'")
    failed = applied(raising(error), obj)
    assert marker not in str(failed)
    assert marker not in "".join(traceback.format_exception(failed))
    formatted = [(r, logs.JsonFormatter().format(r)) for r in caplog.records]
    assert [(r.name, r.levelno) for r, line in formatted if marker in line] == [("fylgja.clabernetes", logging.DEBUG)]
    assert not [line for r, line in formatted if r.levelno >= logging.INFO and marker in line]


def test_apply_names_its_field_manager_on_a_client_built_without_one() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=POLICY)

    async def apply() -> None:
        reach = kube.LightKube(AsyncClient(config=KubeConfig.from_dict(KUBECONFIG),
                                           transport=httpx2.MockTransport(handler)))
        try:
            await reach.apply(POLICY)
        finally:
            await reach.close()

    asyncio.run(apply())
    assert [(r.method, r.url.params.get("fieldManager"), r.url.params.get("force")) for r in seen] == [
        ("PATCH", kubeapi.FIELD_MANAGER, "true")]


def test_an_exec_whose_websocket_upgrade_is_refused_fails_with_the_refusals_status() -> None:
    async def run() -> None:
        reach = reaching(refusing(404, "NotFound", 'pods "n1-x" not found'))
        try:
            await reach.exec("fylgja-twin-t", "n1-x", ["true"], 3.0)
        finally:
            await reach.close()

    with pytest.raises(kube.KubeFailed) as raised:
        asyncio.run(run())
    # The refused upgrade's body is never read, so the API's message is not in it.
    assert raised.value.status == 404
    assert str(raised.value) == "exec Pod fylgja-twin-t/n1-x: 404 Not Found"


def watch_line(name: str, labels: Mapping[str, str] | None = None) -> bytes:
    """One line of a pod watch's stream: the pod `name` `ADDED`, carrying `labels`."""
    pod = {"apiVersion": "v1", "kind": "Pod",
           "metadata": {"name": name, "namespace": "fylgja-twin-t", "uid": f"uid-{name}", "resourceVersion": "7",
                        "labels": dict(labels or {})}}
    return json.dumps({"type": "ADDED", "object": pod}).encode() + b"\n"


def test_a_watch_that_cannot_reach_the_api_watches_again_after_a_pause_doubling_from_1_s_that_an_event_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A request lightkube could not send leaves its watch; LightKube's own loop watches again.
    answers: list[bytes | None] = [None, None, watch_line("n1"), None, watch_line("n2")]

    def handler(request: httpx2.Request) -> httpx2.Response:
        answer = answers.pop(0) if answers else None
        if answer is None:
            raise httpx2.ConnectError("connection refused")
        return httpx2.Response(200, content=answer)

    pauses: list[float] = []
    resting = asyncio.sleep

    async def pause(seconds: float) -> None:
        pauses.append(seconds)
        await resting(0)

    monkeypatch.setattr(asyncio, "sleep", pause)  # what `watch_pods` pauses with

    async def watch() -> list[tuple[str, str, list[float]]]:
        reach = reaching(handler)
        events = reach.watch_pods({"fylgja.owner": "core"})
        assert isinstance(events, AsyncGenerator)
        seen = []
        try:
            async with asyncio.timeout(5):
                async for operation, pod in events:
                    seen.append((operation, pod.name, list(pauses)))
                    if len(seen) == 2:
                        break
        finally:
            try:
                await closed(events)
            finally:
                await reach.close()
        return seen

    assert bounded(watch) == [("ADDED", "n1", [1.0, 2.0]), ("ADDED", "n2", [1.0, 2.0, 1.0])]


def test_a_ready_pod_being_deleted_reads_as_ready_and_deleting() -> None:
    model = codecs.from_dict({
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "n1-5d8f-x",
            "namespace": "fylgja-twin-t",
            "uid": "0b9d1c2e-uid",
            "labels": {"fylgja.owner": "core", "fylgja.twin": "t", kube.NODE_LABEL: "n1"},
            "creationTimestamp": "2026-11-05T15:00:00Z",
            "deletionTimestamp": "2026-11-05T15:05:00Z",
        },
        "status": {
            "phase": "Running",
            "conditions": [{"type": "PodScheduled", "status": "True"}, {"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": "node", "image": "i", "imageID": "", "ready": True, "restartCount": 1,
                                   "state": {"running": {"startedAt": "2026-11-05T15:00:05Z"}}}],
        },
    })
    assert isinstance(model, PodModel)
    assert kube.pod_from(model) == kube.Pod(
        name="n1-5d8f-x", namespace="fylgja-twin-t", uid="0b9d1c2e-uid",
        labels={"fylgja.owner": "core", "fylgja.twin": "t", kube.NODE_LABEL: "n1"},
        phase="Running", ready=True, deleting=True, created="2026-11-05T15:00:00+00:00", restarts=1,
        container_running=True)


@pytest.mark.parametrize("state", [
    {"terminated": {"exitCode": 143, "reason": "Error"}},
    {"waiting": {"reason": "CrashLoopBackOff"}},
    None,
], ids=["terminated", "waiting", "no-state"])
def test_a_pods_container_terminated_or_waiting_is_not_running_though_the_pod_is(state: dict[str, Any] | None) -> None:
    # Read on the cluster: a container ended in its pod leaves the pod's phase `Running` while it is
    # terminated and while it restarts.
    container: dict[str, Any] = {"name": "node", "image": "i", "imageID": "", "ready": False, "restartCount": 1}
    if state is not None:
        container["state"] = state
    model = codecs.from_dict({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "n1", "namespace": "ns",
                                                                              "uid": "u1"},
                              "status": {"phase": "Running", "containerStatuses": [container]}})
    assert isinstance(model, PodModel)
    pod = kube.pod_from(model)
    assert (pod.phase, pod.ready, pod.restarts, pod.container_running) == ("Running", False, 1, False)


@pytest.mark.parametrize(("restarts", "state", "last", "ended"), [
    (0, {"terminated": {"exitCode": 143, "reason": "Error"}}, None, True),
    (1, {"waiting": {"reason": "CrashLoopBackOff"}}, {"terminated": {"exitCode": 143, "reason": "Error"}}, True),
    (0, {"waiting": {"reason": "PodInitializing"}}, None, False),
    (0, {"waiting": {"reason": "PodInitializing"}}, {}, False),
    (1, {"running": {"startedAt": "2026-11-06T10:00:00Z"}}, {"terminated": {"exitCode": 143, "reason": "Error"}},
     False),
    (0, None, None, False),
], ids=["terminated", "waiting-after-terminated", "starting", "starting-empty-last", "running-again", "no-state"])
def test_a_container_ended_in_its_pod_reads_as_ended_and_a_starting_one_never_does(
    restarts: int, state: dict[str, Any] | None, last: dict[str, Any] | None, ended: bool,
) -> None:
    # Read on the cluster (verified-facts.md, "a container restarted in its pod"): a container ended in its pod is
    # `terminated` at its restart count, then `running` at one more with a last state `terminated`; a pod starting
    # shows no status, then `waiting` (`PodInitializing`) with no last state, then `running`.
    container: dict[str, Any] = {"name": "node", "image": "i", "imageID": "", "ready": False, "restartCount": restarts}
    if state is not None:
        container["state"] = state
    if last is not None:
        container["lastState"] = last
    model = codecs.from_dict({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "n1", "namespace": "ns",
                                                                              "uid": "u1"},
                              "status": {"phase": "Running", "containerStatuses": [container]}})
    assert isinstance(model, PodModel)
    assert kube.pod_from(model).container_ended is ended


def test_a_pod_with_no_status_is_not_ready_with_no_phase() -> None:
    model = codecs.from_dict({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "n2", "namespace": "ns",
                                                                              "uid": "u2"}})
    assert isinstance(model, PodModel)
    pod = kube.pod_from(model)
    assert (pod.ready, pod.phase, pod.deleting, pod.restarts, pod.labels, pod.container_running) == (
        False, "", False, 0, {}, False)


def test_a_load_balancer_reads_as_its_ingress_address_and_none_before_it_has_one() -> None:
    spec = {"type": "LoadBalancer", "externalTrafficPolicy": "Cluster", "ports": [{"port": 22}]}
    held = codecs.from_dict({"apiVersion": "v1", "kind": "Service", "metadata": {"name": "n1"}, "spec": spec,
                             "status": {"loadBalancer": {"ingress": [{"ip": "192.0.2.10", "ipMode": "VIP"}]}}})
    pending = codecs.from_dict({"apiVersion": "v1", "kind": "Service", "metadata": {"name": "n2"}, "spec": spec,
                                "status": {}})
    assert isinstance(held, ServiceModel) and isinstance(pending, ServiceModel)
    assert kube.service_from(held) == kube.Service(name="n1", type="LoadBalancer", traffic_policy="Cluster",
                                                   address="192.0.2.10")
    assert kube.service_from(pending).address is None


def test_exec_keeps_the_tail_the_local_driver_keeps() -> None:
    assert kube.EXEC_OUTPUT_KEPT == containerlab_driver.EXEC_OUTPUT_KEPT
    written = bytes(i % 251 for i in range(200_000))
    tail = kube.Tail()
    for start in range(0, len(written), 7_000):
        tail.write(written[start:start + 7_000])
    assert tail.getvalue() == written[-65_536:]


def test_a_watch_the_api_keeps_refusing_is_retried_after_a_pause_doubling_from_1_s_to_60_s() -> None:
    refused = httpx2.HTTPStatusError("forbidden", request=httpx2.Request("GET", "https://kube.example:6443/"),
                                     response=httpx2.Response(403))
    answers = [kube.watch_retry(refused, count) for count in [*range(1, 10), 10_000]]
    assert {answer.action for answer in answers} == {OnErrorAction.RETRY}
    assert [answer.sleep for answer in answers] == [1, 2, 4, 8, 16, 32, 60, 60, 60, 60]


def test_the_watch_pauses_by_the_seams_one_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not a copy of it (pre-flight ruling 9): the third failure in a row waits the backoff after two before it."""
    asked: list[float | None] = []

    def backoff(previous: float | None) -> float:
        asked.append(previous)
        return 3.0 if previous is None else previous + 1

    monkeypatch.setattr(kube, "events_backoff", backoff)
    assert kube.watch_retry(httpx2.ReadError("reset"), 3).sleep == 5.0
    assert asked == [None, 3.0, 4.0]


MARKERS = ("192.0.2.1", "secret-marker")


def test_a_failed_watch_is_logged_by_its_type_and_the_apis_status_code_and_never_its_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Rule A: an error's text can name the API server's address (a certificate's, a URL), and the API's message is
    the API's to write, so neither reaches the warning: the watch is the clabernetes driver's `events` source."""
    marked = " ".join(MARKERS)
    expired = ApiError(status=Status(code=410, reason="Expired", message=f"too old resource version: {marked}"))
    kube.watch_retry(expired, 1)
    answers: list[bytes | None] = [None, watch_line("n1")]

    def handler(request: httpx2.Request) -> httpx2.Response:
        answer = answers.pop(0) if answers else None
        if answer is None:
            raise httpx2.ConnectError(f"certificate verify failed: IP address mismatch, certificate is not valid for "
                                      f"'{marked}'")
        return httpx2.Response(200, content=answer)

    resting = asyncio.sleep

    async def pause(seconds: float) -> None:
        await resting(0)

    monkeypatch.setattr(asyncio, "sleep", pause)

    async def watch() -> str:
        reach = reaching(handler)
        events = reach.watch_pods({"fylgja.owner": "core"})
        try:
            async with asyncio.timeout(5):
                return (await anext(events))[1].name
        finally:
            try:
                await closed(events)
            finally:
                await reach.close()

    assert bounded(watch) == "n1"  # it went on
    formatted = [logs.JsonFormatter().format(record) for record in caplog.records]
    assert not [line for line in formatted if any(marker in line for marker in MARKERS)]
    assert [r.getMessage() for r in caplog.records if r.levelname == "WARNING"] == [
        "watch_pods Pod */*: ApiError, status 410; watching again in 1s",
        "watch_pods Pod */*: ConnectError; watching again in 1s"]


class Held(httpx2.AsyncByteStream):
    """A watch's response body: its `lines`, then nothing more until it is closed."""

    def __init__(self, *lines: bytes) -> None:
        self.lines = lines
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for line in self.lines:
            yield line
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


def test_closing_the_watch_closes_lightkubes_watch_and_its_response_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rule B: the driver's `events` closes its watch when it is closed, and the watch closes its response then, not
    when lightkube's watch is collected. The test keeps a reference to lightkube's watch, so the collector cannot
    reach it (the awaits of a close give asyncio's finalizer its turn): only the watch's own close can have closed
    the response."""
    held = Held(watch_line("n1"))
    kept: list[Any] = []  # lightkube's watches

    async def watch() -> None:
        reach = reaching(lambda request: httpx2.Response(200, stream=held))
        client = reach._client
        made = client.watch

        def keeping(*args: Any, **kw: Any) -> Any:
            kept.append(made(*args, **kw))
            return kept[-1]

        monkeypatch.setattr(client, "watch", keeping)
        events = reach.watch_pods({"fylgja.owner": "core"})
        try:
            async with asyncio.timeout(5):
                assert (await anext(events))[1].name == "n1"
            await closed(events)
            assert len(kept) == 1 and held.closed
        finally:
            await reach.close()

    bounded(watch)


def test_a_line_the_watch_cannot_decode_is_raised_past_lightkubes_retries_and_watched_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The failure a real watch raises past `LightKube.watch_pods`: a line lightkube cannot decode is msgspec's
    `DecodeError`, a `ValueError` outside `kube.FAILURES`, which neither lightkube nor `LightKube` retries
    (verified-facts.md, lightkube 1.0.1). The clabernetes driver's `events` logs it by its type alone, watches
    again, and the new watch names the twin."""
    answers = [httpx2.Response(200, content=b"not json\n"),
               httpx2.Response(200, stream=Held(watch_line("n1", {"fylgja.owner": "core", "fylgja.twin": "t"})))]

    async def body() -> list[str]:
        reach = reaching(lambda request: answers.pop(0))
        driver = ClabernetesDriver(reach, Provider({}), controller_namespace="c9s", pod_cidr="10.244.0.0/16",
                                   backoff=lambda _: 0.0)
        names: list[str] = []

        async def consume() -> None:
            async for name in driver.events():
                names.append(name)

        task = asyncio.create_task(consume())
        try:
            async with asyncio.timeout(5):
                while not names:
                    if task.done():
                        await task
                    await asyncio.sleep(0.001)
            await cancelled(task)
        finally:
            await reach.close()
        return names

    assert bounded(body) == ["t"]
    assert [(r.name, r.getMessage()) for r in caplog.records if r.levelname == "WARNING"] == [
        ("fylgja.clabernetes", "the pod watch ended (DecodeError): it is watched again in 0s, and names the twin of "
                               "each pod there again")]
    assert "not json" not in caplog.text
