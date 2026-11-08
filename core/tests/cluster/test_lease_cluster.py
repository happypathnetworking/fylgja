"""The Lease on the k3s cluster (D-062, D-064): `KubeLeases` over the kubeconfig's client, on a
Lease `fylgja-lease-test` in the kubeconfig's default namespace, held by `a` and `b`, two
`Lease`s of one process standing for two cores, each over a `KubeLeases` and a client of its own.

The tests run in order and share the two:

- `a` acquires it, and the Lease read back with lightkube names `a`, for 15 s;
- `b` is still waiting 10 s later, while `a` holds it and renews;
- `a`'s `hold` is cancelled just after a renewal, without a release, and `b` holds it no sooner
  than 15 s after `a`'s last renewal was sent (the promise: `b` counts from a read that answered
  after it), and within 25 s of the cancel; `a` renews and is `Lost` naming `b`. `a`'s clock
  stands still from its cancel, as a suspended host's does: run on, its renewal would be `Lost`
  with nothing written, which the pure tier holds, and the 409 and the read back it reaches here
  would go unread;
- `b` releases it, and `a` acquires it within 2 s;
- a Lease written through lightkube at a whole second, which lightkube encodes with no fraction,
  is refused, 400: a Lease's times are `MicroTime`, read with six digits, so `KubeLeases` writes
  such a time a microsecond later.

The module needs `KUBECONFIG` alone. The Lease is deleted at its end, whatever failed, with
lightkube directly, and read back absent, before the clients are closed; each step of the end
runs whatever the one before raised, and the first failure is raised after them all. Each test
prints what it took and read (`-s`); nothing of the site is printed, a failure's message included:
a test compares holders, counts and seconds, never an `ApiError`'s text or a client's
representation. The Lease logs through `fylgja.lease`,
each record scrubbed of every IPv4 address as it is made (`Scrubbing`), as every cluster module's.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from lightkube import ApiError, AsyncClient, codecs
from lightkube.resources.coordination_v1 import Lease as LeaseModel
from scrubbing import Scrubbing

from cluster.conftest import run, say
from fylgja_core import kubeapi
from fylgja_core.lease import DURATION_S, KubeLeases, Lease, Lost, Record

NAME = "fylgja-lease-test"
WAITING_S = 10.0
"""How long `b` is watched waiting while `a` holds the Lease."""
TAKEN_WITHIN_S = 25.0
"""How soon `b` must hold the Lease after `a`'s cancel, just after a renewal."""
FREED_S = 2.0
"""How soon `a` must hold the Lease once `b` has released it."""
STEP_S = 60.0
"""The most any one call or wait of a test may take."""


class Stilled:
    """A monotonic clock that stands still from `still()`, as a suspended host's does, and runs
    again from `resume()`, where it stood."""

    def __init__(self) -> None:
        self._stood: float | None = None
        self._lag = 0.0

    def __call__(self) -> float:
        return self._stood if self._stood is not None else time.monotonic() - self._lag

    def still(self) -> None:
        self._stood = self()

    def resume(self) -> None:
        if self._stood is not None:
            self._lag = time.monotonic() - self._stood
            self._stood = None


class Timed:
    """`lease.Api` over `api`, keeping when each write was sent, and when each write that was
    answered was sent and answered, on `time.monotonic`."""

    def __init__(self, api: KubeLeases) -> None:
        self.api = api
        self.sent: list[float] = []
        self.answered: list[tuple[float, float]] = []

    @property
    def name(self) -> str:
        return self.api.name

    async def read(self) -> Record | None:
        return await self.api.read()

    async def write(self, holder: str, transitions: int, version: str | None) -> Record:
        sent = time.monotonic()
        self.sent.append(sent)
        written = await self.api.write(holder, transitions, version)
        self.answered.append((sent, time.monotonic()))
        return written

    async def close(self) -> None:
        await self.api.close()


@dataclass
class Two:
    """What the tests share: the tests' own client, which reads and deletes the Lease; `a` over its
    writes, timed, and its clock; `b`, and the holders it said it waited for; and the tasks running
    on the session's loop between the tests."""

    loop: asyncio.Runner
    client: AsyncClient
    a: Lease
    a_writes: Timed
    a_clock: Stilled
    b: Lease
    waited: list[str]
    tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)


async def _absent(client: AsyncClient) -> bool:
    """Delete the Lease if it is there; whether it was absent."""
    try:
        await client.delete(LeaseModel, NAME)
    except ApiError as e:
        if e.status.code == 404:
            return True
        raise AssertionError(f"delete {NAME}: {e.status.code} {e.status.reason}") from None
    return False


async def _gone(client: AsyncClient) -> None:
    """Delete the Lease, and fail unless a second delete finds it absent."""
    await _absent(client)
    assert await _absent(client), f"{NAME} is still there"


@pytest.fixture(scope="module")
def two(loop: asyncio.Runner) -> Iterator[Two]:
    if not os.environ.get("KUBECONFIG"):
        pytest.fail("the Lease's cluster test needs KUBECONFIG set (CONTRIBUTING.md, Test tiers)")
    client = kubeapi.client()
    a_clock = Stilled()
    waited: list[str] = []
    a_writes = Timed(KubeLeases(NAME))
    shared = Two(loop=loop, client=client, a=Lease(a_writes, "a", monotonic=a_clock), a_writes=a_writes,
                 a_clock=a_clock, b=Lease(KubeLeases(NAME), "b", on_wait=waited.append), waited=waited)
    scrubbing = Scrubbing()
    logging.setLogRecordFactory(scrubbing)
    try:
        was_absent = run(loop, _absent(client), f"{NAME} absent first")
        say(f"{NAME} {'was absent' if was_absent else 'was there, and is deleted'}")
        yield shared
    finally:
        try:
            for task in shared.tasks.values():
                task.cancel()
            steps: list[tuple[Coroutine[Any, Any, object], str]] = []
            if shared.tasks:
                steps.append((asyncio.wait(shared.tasks.values(), timeout=STEP_S), "the tasks left, cancelled"))
            steps += [(_gone(client), f"{NAME} deleted and read back absent (the module's end)"),
                      (shared.a.close(), "a's client closed"), (shared.b.close(), "b's client closed"),
                      (client.close(), "the tests' client closed")]
            failures: list[Exception] = []
            for step, what in steps:
                try:
                    run(loop, step, what)
                except Exception as e:  # the next step runs whatever this one raised
                    say(f"the module's end: {what}: {type(e).__name__}")
                    failures.append(e)
            if failures:
                raise failures[0]
        finally:
            logging.setLogRecordFactory(scrubbing.made)


def read(two: Two) -> tuple[str, int, str]:
    """The Lease as lightkube reads it: its holder, transitions and renewTime."""
    model = run(two.loop, two.client.get(LeaseModel, NAME), f"{NAME} read")
    spec = model.spec
    assert spec is not None and spec.renewTime is not None
    return spec.holderIdentity or "", spec.leaseTransitions or 0, spec.renewTime.isoformat()


def started(two: Two, what: str, coroutine: Coroutine[Any, Any, None]) -> None:
    """`coroutine` run as a task on the session's loop, which runs it during every later `run`."""

    async def start() -> asyncio.Task[None]:
        return asyncio.ensure_future(coroutine)

    two.tasks[what] = two.loop.run(start())


def test_a_takes_the_lease_and_it_reads_back_held_by_a_for_15_s(two: Two) -> None:
    run(two.loop, asyncio.wait_for(two.a.acquire(), STEP_S), "a acquires")
    model = run(two.loop, two.client.get(LeaseModel, NAME), f"{NAME} read")
    spec = model.spec
    assert spec is not None
    held = (spec.holderIdentity, spec.leaseDurationSeconds, spec.leaseTransitions)
    say(f"read back: holder {held[0]}, {held[1]} s, transitions {held[2]}, acquireTime "
        f"{'equal to' if spec.acquireTime == spec.renewTime else 'not'} renewTime")
    assert held == ("a", DURATION_S, 0)
    assert spec.acquireTime is not None and spec.acquireTime == spec.renewTime
    started(two, "a holds", two.a.hold())


def test_b_is_still_waiting_10_s_later_while_a_holds_it(two: Two) -> None:
    before = read(two)
    renewals = len(two.a_writes.answered)
    started(two, "b acquires", two.b.acquire())
    run(two.loop, asyncio.sleep(WAITING_S), f"{WAITING_S:g} s with b waiting")
    after = read(two)
    renewed = len(two.a_writes.answered) - renewals
    say(f"b still waiting: {not two.tasks['b acquires'].done()}; it said it waited for {two.waited}; a renewed "
        f"{renewed} times meanwhile")
    assert not two.tasks["b acquires"].done() and not two.tasks["a holds"].done()
    assert two.waited == ["a"]
    assert after[:2] == ("a", 0) and after[2] != before[2] and renewed >= 1


def test_a_gone_silent_is_taken_by_b_15_s_after_its_last_renewal_and_its_renewal_is_lost_naming_b(
    two: Two,
) -> None:
    renewals = len(two.a_writes.answered)

    async def next_renewal() -> None:
        while len(two.a_writes.answered) == renewals:
            await asyncio.sleep(0.02)

    run(two.loop, asyncio.wait_for(next_renewal(), STEP_S), "a's next renewal answered")
    hold = two.tasks.pop("a holds")
    hold.cancel()
    silent = time.monotonic()
    two.a_clock.still()
    run(two.loop, asyncio.wait({hold}, timeout=STEP_S), "a's hold cancelled, nothing released")
    assert hold.cancelled()
    assert two.a_writes.answered[-1][0] == two.a_writes.sent[-1]  # a's last write answered, whatever one before met
    last_sent = two.a_writes.sent[-1]
    run(two.loop, asyncio.wait_for(two.tasks.pop("b acquires"), STEP_S), "b takes it over")
    taken = time.monotonic()
    say(f"b holds it {taken - last_sent:.2f} s after a's last renewal was sent, {taken - silent:.2f} s after a "
        "went silent")
    assert taken - last_sent >= DURATION_S
    assert taken - silent <= TAKEN_WITHIN_S
    assert read(two)[:2] == ("b", 1)
    started(two, "b holds", two.b.hold())
    writes = len(two.a_writes.answered)
    with pytest.raises(Lost) as raised:
        run(two.loop, asyncio.wait_for(two.a.renew(), STEP_S), "a renews, its clock still")
    say(f"a's renewal: Lost, {raised.value}")
    assert str(raised.value) == f"the Lease {NAME} is held by b"
    assert len(two.a_writes.answered) == writes  # its write was answered 409, not as a renewal


def test_b_releases_it_and_a_acquires_it_within_2_s(two: Two) -> None:
    hold = two.tasks.pop("b holds")
    hold.cancel()
    run(two.loop, asyncio.wait({hold}, timeout=STEP_S), "b's hold stopped")
    run(two.loop, two.b.release(), "b releases")
    freed = read(two)
    say(f"released: holder {freed[0]!r}, transitions {freed[1]}")
    assert freed[:2] == ("", 1)
    two.a_clock.resume()
    start = time.monotonic()
    run(two.loop, asyncio.wait_for(two.a.acquire(), STEP_S), "a acquires")
    elapsed = time.monotonic() - start
    say(f"a holds it {elapsed:.2f} s after b's release")
    assert elapsed < FREED_S
    assert read(two)[:2] == ("a", 2)


def test_a_time_at_a_whole_second_as_lightkube_writes_it_is_refused(two: Two) -> None:
    model = run(two.loop, two.client.get(LeaseModel, NAME), f"{NAME} read")
    assert model.metadata is not None and model.spec is not None
    whole = "2026-11-06T10:00:00.000000Z"
    obj = codecs.from_dict({"apiVersion": "coordination.k8s.io/v1", "kind": "Lease",
                            "metadata": {"name": NAME, "resourceVersion": model.metadata.resourceVersion},
                            "spec": {"holderIdentity": "a", "leaseDurationSeconds": DURATION_S, "renewTime": whole,
                                     "acquireTime": whole, "leaseTransitions": model.spec.leaseTransitions}})
    assert isinstance(obj, LeaseModel)
    try:
        run(two.loop, two.client.replace(obj), f"{NAME} replaced at a whole second")
        answered: int | None = None
    except ApiError as e:
        answered = e.status.code
        say(f"a whole second: refused, {e.status.code} {e.status.reason}")
    if answered is None:
        say(f"a whole second: accepted, renewTime read back {read(two)[2]}")
    assert answered == 400, answered
