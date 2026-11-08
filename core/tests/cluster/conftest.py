"""The cluster tier: the clabernetes driver's calls on the k3s cluster (CONTRIBUTING.md, Test tiers).

Every test under tests/cluster is marked `cluster`: `make test` deselects them and `make
cluster` runs them. Everything of the site comes from the environment, never from the tree:
`KUBECONFIG`, `FYLGJA_CLABERNETES_NAMESPACE`, `FYLGJA_POD_CIDR`, the pull credentials and the
node logins. It is read inside the fixtures, never at import, since the pure tier collects
this file too.

lightkube's connections belong to the event loop that opened them, so the session runs one
loop, `loop`, and every call goes through it by `run`. The session's `driver` is made as the
server makes it, by the registry before the loop runs, over a lightkube client of its own;
`kube` is the tests' own reach, beside it.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from fylgja_core import drivers
from fylgja_core.clabernetes.driver import ClabernetesDriver
from fylgja_core.clabernetes.kube import NODE_LABEL, Kube, LightKube
from fylgja_core.credentials import Provider
from fylgja_core.kubeapi import client

_HERE = Path(__file__).resolve().parent

SITE_VARIABLES = ("KUBECONFIG", "FYLGJA_CLABERNETES_NAMESPACE", "FYLGJA_POD_CIDR")
"""What the tier needs set to reach the cluster and plan for it."""

GATED = "ARISTA_CEOS"
"""The pull credential's key the gated cEOS image is pulled under (`psp/arista_eos.yaml`)."""

POLL_S = 2.0
"""How often `until` reads again."""

SAMPLE_S = 0.25
"""How often `watching` reads the Topology's status and the twin's pods."""


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/cluster `cluster`, before `-m` selects."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.cluster)


@dataclass(frozen=True)
class Site:
    """What the site decides that a plan writes (D-057): clabernetes' namespace and the pod CIDR."""

    controller_namespace: str
    pod_cidr: str


@pytest.fixture(scope="session")
def site() -> Site:
    for variable in SITE_VARIABLES:
        if not os.environ.get(variable):
            pytest.fail(f"the cluster tier needs {variable} set (CONTRIBUTING.md, Test tiers)")
    return Site(os.environ["FYLGJA_CLABERNETES_NAMESPACE"], os.environ["FYLGJA_POD_CIDR"])


@pytest.fixture(scope="session")
def loop() -> Iterator[asyncio.Runner]:
    with asyncio.Runner() as runner:
        yield runner


@pytest.fixture(scope="session")
def provider() -> Provider:
    return Provider(os.environ)


@pytest.fixture(scope="session")
def kube(site: Site, loop: asyncio.Runner) -> Iterator[LightKube]:
    reach = LightKube(client())
    try:
        yield reach
    finally:
        loop.run(reach.close())


@pytest.fixture(scope="session")
def driver(site: Site, loop: asyncio.Runner, provider: Provider) -> Iterator[ClabernetesDriver]:
    """The clabernetes driver as the server makes it: by the registry, before the loop runs."""
    made = drivers.make("clabernetes", root=None, credentials=provider,
                        clabernetes_namespace=site.controller_namespace, pod_cidr=site.pod_cidr)
    assert isinstance(made, ClabernetesDriver) and isinstance(made.kube, LightKube)
    try:
        yield made
    finally:
        loop.run(made.kube.close())


def run[T](loop: asyncio.Runner, awaitable: Awaitable[T], what: str) -> T:
    """`awaitable`'s result, run on the session's loop, printing what it took."""
    start = time.monotonic()
    try:
        return loop.run(awaitable)
    finally:
        print(f"\n[cluster] {what}: {time.monotonic() - start:.2f} s", flush=True)


def say(what: str) -> None:
    print(f"[cluster] {what}", flush=True)


def until[T](loop: asyncio.Runner, read: Callable[[], Awaitable[T]], done: Callable[[T], bool], budget_s: float,
             what: str) -> tuple[T, float]:
    """The first answer of `read` that is `done`, asking every `POLL_S`, and the seconds it took;
    a failure naming `what` once `budget_s` have passed."""
    start = time.monotonic()
    while True:
        value = loop.run(read())
        elapsed = time.monotonic() - start
        if done(value):
            say(f"{what}: {elapsed:.1f} s")
            return value, elapsed
        if elapsed > budget_s:
            pytest.fail(f"{what}: not within {budget_s:g} s; last read {value!r}")
        time.sleep(POLL_S)


async def watching[T](kube: Kube, namespace: str, topology: str, acting: Awaitable[T], what: str) -> T:
    """`acting`'s result, the Topology `topology`'s status and the pods of `namespace` read every
    `SAMPLE_S` while it runs: each reading that differs from the one before is printed with its
    offset from the start, and then when `acting` returned or raised. A pod is its node, its
    uid's first eight characters and its restart count, its phase, and whether it is `Ready` and
    deleting."""
    start = time.monotonic()
    lines: list[str] = []
    ended = "raised"

    async def sample() -> None:
        last = None
        while True:
            held = await kube.topology(namespace, topology)
            status = (held or {}).get("status") or {}
            generation = held["metadata"]["generation"] if held is not None else None
            pods = sorted(await kube.pods(namespace, {}), key=lambda p: (p.labels.get(NODE_LABEL, ""), p.created))
            each = ", ".join(f"{p.labels.get(NODE_LABEL)} {p.uid[:8]}/{p.restarts} {p.phase}"
                             f"{' Ready' if p.ready else ''}{' deleting' if p.deleting else ''}" for p in pods)
            seen = (f"generation {generation} observed {status.get('observedGeneration')} topologyReady "
                    f"{status.get('topologyReady')} nodes ready {status.get('readyNodeCount')}/"
                    f"{status.get('nodeCount')} | {each}")
            if seen != last:
                lines.append(f"+{time.monotonic() - start:6.2f} s {seen}")
                last = seen
            await asyncio.sleep(SAMPLE_S)

    task = asyncio.create_task(sample())
    try:
        result = await acting
        ended = "returned"
        return result
    finally:
        lines.append(f"+{time.monotonic() - start:6.2f} s {what} {ended}")
        task.cancel()
        [stopped] = await asyncio.gather(task, return_exceptions=True)
        if not isinstance(stopped, asyncio.CancelledError):
            lines.append(f"(the sampling stopped early: {type(stopped).__name__})")
        say(f"{what}, the Topology's status and the pods meanwhile:\n" + "\n".join(f"    {line}" for line in lines))


def gated(provider: Provider) -> None:
    """Skip the test, saying why, unless the provider holds the gated cEOS image's registry."""
    if GATED not in provider.registries():
        pytest.skip(f"the cEOS image is account-gated: set FYLGJA_CREDENTIAL_{GATED}_REGISTRY, _USERNAME and "
                    "_PASSWORD to pull it (CONTRIBUTING.md, Running the core)")
