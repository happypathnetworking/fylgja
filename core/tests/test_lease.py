"""The Lease (D-062, D-064), with no cluster: one core holds it, a holder is judged by the
watcher's own clock, and a holder that cannot renew stops at the duration's end.

`Lease` is read over `FakeLeases` on a `FakeClock`, whose calls take the seconds a test sets, so
each test reads the real arithmetic with no wait. A write that never answers is cut by
`asyncio.timeout`, on the event loop's clock: one test reads the cut on the real clock, and one on
`Skipping`, a loop whose clock skips its idle waits, where the Lease judges by that clock too.
`KubeLeases` is read over httpx2's `MockTransport`: the whole Lease each write builds, its acquire
time, and what each of the API's answers becomes. The Lease is read on the cluster in
tests/cluster/test_lease_cluster.py."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import socket
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from aio import Skipping, bounded
from fake_leases import FakeClock, FakeLeases, Stopped, Write
from lightkube import AsyncClient, KubeConfig

from fylgja_core import clock as wall_clock
from fylgja_core import kubeapi, lease
from fylgja_core.lease import Conflict, KubeLeases, Lease, Lost, Record, Refused, Unreachable

ADDRESS = "192.0.2.1"
"""An address a failure's text may hold, which no message or log line may carry."""


def leased(fake: FakeLeases, clock: FakeClock, **kw: Any) -> Lease:
    """The Lease `a` over `fake`, on `clock`."""
    return Lease(fake, "a", monotonic=clock.monotonic, sleep=clock.sleep, **kw)


def stop() -> None:
    raise Stopped


def logged(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "fylgja.lease"]


# acquire


def test_no_lease_is_created_held_by_a_with_no_transitions() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    bounded(leased(fake, clock).acquire)
    assert fake.written == [Write(0, "a", 0, None)]
    assert fake.record is not None and (fake.record.holder, fake.record.transitions) == ("a", 0)
    assert clock.sleeps == []


def test_a_lease_no_one_holds_is_taken_at_once_and_counts_a_transition() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    free = fake.set("", 3)
    bounded(leased(fake, clock).acquire)
    assert fake.written == [Write(0, "a", 4, free.version)] and clock.sleeps == []


def test_a_lease_held_under_its_own_name_is_taken_at_once_and_counts_no_transition() -> None:
    # The kubelet restarted the container: the pod's name is the holder's.
    clock = FakeClock()
    fake = FakeLeases(clock)
    own = fake.set("a", 3)
    bounded(leased(fake, clock).acquire)
    assert fake.written == [Write(0, "a", 3, own.version)] and clock.sleeps == []


def test_a_holder_that_renews_keeps_it_however_long_and_is_waited_for_once() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    fake.set("b", 2)
    for t in range(5, 60, 5):
        clock.at(t, lambda: fake.set("b", 2))
    clock.at(60, stop)
    waited: list[str] = []
    with pytest.raises(Stopped):
        bounded(leased(fake, clock, on_wait=waited.append).acquire)
    assert clock.now == 60
    assert fake.writes == 0 and waited == ["b"]


def test_a_holder_gone_silent_is_taken_15_to_20_s_after_the_first_read() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    silent = fake.set("b", 2)
    waited: list[str] = []
    bounded(leased(fake, clock, on_wait=waited.append).acquire)
    [taken] = fake.written
    assert 15 <= taken.at < 20 and taken[1:] == ("a", 3, silent.version)
    assert fake.record is not None and (fake.record.holder, fake.record.transitions) == ("a", 3)
    assert waited == ["b"]


def test_the_15_s_count_from_when_the_read_that_saw_the_holder_answered() -> None:
    # The holder's renewal can have been sent as late as the read's answer: counted from the read's
    # send, a slow read would take the Lease that much too soon.
    clock = FakeClock()
    fake = FakeLeases(clock)
    held_by_b = fake.set("b", 2)
    fake.read_s = 3.0
    clock.at(3, lambda: setattr(fake, "read_s", 0.0))  # the first read alone is slow
    bounded(leased(fake, clock).acquire)
    assert fake.written == [Write(18, "a", 3, held_by_b.version)]
    assert fake.reads == 4  # at 0 (answered at 3), 8, 13 and 18


def test_a_renewal_seen_starts_the_15_s_again_from_the_read_that_saw_it() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    fake.set("b", 2)
    renewed: list[Record] = []
    clock.at(10, lambda: renewed.append(fake.set("b", 2)))
    bounded(leased(fake, clock).acquire)
    assert fake.written == [Write(25, "a", 3, renewed[0].version)]


def test_a_take_over_another_took_first_waits_on_for_it_from_that_read() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    fake.write_s = 1.0
    b = fake.set("b", 2)
    took: list[Record] = []
    clock.at(15.5, lambda: took.append(fake.set("c", 3)))  # while a's take-over is on its way
    waited: list[str] = []
    bounded(leased(fake, clock, on_wait=waited.append).acquire)
    # a's take-over at 15 answered Conflict at 16; c, read then, is waited for 15 s from that read.
    assert fake.written == [Write(15, "a", 3, b.version), Write(31, "a", 4, took[0].version)]
    assert waited == ["b", "c"]
    assert fake.record is not None and fake.record.holder == "a"


def test_a_cluster_that_does_not_answer_is_read_again_every_5_s_and_said_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="fylgja.lease")
    clock = FakeClock()
    fake = FakeLeases(clock)
    fake.read_errors = [Unreachable(f"connect to {ADDRESS}: refused", failure="ConnectError"),
                        Unreachable(f"{ADDRESS} answered 503", status=503),
                        Unreachable(f"connect to {ADDRESS}: refused", failure="ConnectError")]
    bounded(leased(fake, clock).acquire)
    assert clock.sleeps == [5, 5, 5] and fake.reads == 4
    assert fake.written == [Write(15, "a", 0, None)]
    lines = logged(caplog)
    assert [level for level, _ in lines] == [logging.WARNING, logging.INFO]
    assert all(fake.name in message for _, message in lines) and "ConnectError" in lines[0][1]
    assert not [message for _, message in lines if ADDRESS in message]


def test_a_lease_deleted_between_the_read_and_the_take_is_read_again_and_created() -> None:
    # `kubectl delete lease` while a waiter takes it: waiting changes it, so it is no refusal.
    clock = FakeClock()
    fake = FakeLeases(clock)
    fake.write_s = 1.0
    free = fake.set("", 3)
    clock.at(0.5, lambda: setattr(fake, "record", None))  # while the take is on its way
    bounded(leased(fake, clock).acquire)
    assert fake.written == [Write(0, "a", 4, free.version), Write(1, "a", 0, None)]
    assert fake.record is not None and (fake.record.holder, fake.record.transitions) == ("a", 0)
    assert clock.sleeps == [] and fake.reads == 2


@pytest.mark.parametrize("refusal", [Conflict(f"replace Lease fylgja-core: 409 Conflict at {ADDRESS}"),
                                     Refused(f"replace Lease fylgja-core: 404 NotFound at {ADDRESS}", status=404)],
                         ids=["conflict", "no-lease"])
def test_takes_refused_in_a_row_are_read_again_at_once_then_every_5_s_said_once(
    refusal: Exception, caplog: pytest.LogCaptureFixture,
) -> None:
    # An API that answers each read with the record and each take of it with a 409 or a 404 (a proxy,
    # a webhook) is not asked at its own speed: the first take refused is read again at once.
    caplog.set_level(logging.INFO, logger="fylgja.lease")
    clock = FakeClock()
    fake = FakeLeases(clock)
    fake.set("", 3)
    fake.write_errors = [refusal, refusal, refusal]
    bounded(leased(fake, clock).acquire)
    assert [w.at for w in fake.written] == [0, 0, 5, 10]
    assert clock.sleeps == [5, 5] and fake.reads == 4
    [(level, message)] = logged(caplog)
    assert level == logging.WARNING and fake.name in message
    assert ADDRESS not in message


def test_a_holder_waited_for_between_two_refused_takes_ends_their_run(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="fylgja.lease")
    clock = FakeClock()
    fake = FakeLeases(clock)
    fake.write_s = 1.0
    fake.set("b", 2)
    clock.at(15.5, lambda: fake.set("c", 3))  # c takes it while a's take-over at 15 is on its way
    clock.at(31.5, lambda: fake.set("d", 4))  # and d while a's at 31 is
    bounded(leased(fake, clock).acquire)
    # Each refused take is the first of its run, read again at once: d is waited for from 32.
    assert [w.at for w in fake.written] == [15, 31, 47]
    assert logged(caplog) == []


@pytest.mark.parametrize("call", ["read", "create", "take"])
def test_a_lease_that_cannot_be_read_or_written_is_refused_at_once(call: str) -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    refused = Refused("write Lease fylgja-core: 403 Forbidden", status=403)
    if call == "read":
        fake.read_errors = [refused]
    else:
        fake.write_errors = [refused]
    if call == "take":
        fake.set("", 3)
    with pytest.raises(Refused) as raised:
        bounded(leased(fake, clock).acquire)
    assert raised.value is refused and clock.sleeps == []


def test_a_create_refused_404_is_refused_at_once() -> None:
    # No such namespace: waiting will not change it, so it is no Lease deleted under a take.
    clock = FakeClock()
    fake = FakeLeases(clock)
    refused = Refused("create Lease fylgja-core: 404 NotFound", status=404)
    fake.write_errors = [refused]
    with pytest.raises(Refused) as raised:
        bounded(leased(fake, clock).acquire)
    assert raised.value is refused
    assert fake.written == [Write(0, "a", 0, None)] and clock.sleeps == []


# hold


def held(fake: FakeLeases, clock: FakeClock, **kw: Any) -> Lease:
    """The Lease `a`, acquired at 0 by a create that took no time."""
    taken = leased(fake, clock, **kw)
    bounded(taken.acquire)
    assert clock.now == 0 and fake.written == [Write(0, "a", 0, None)]
    return taken


def test_each_renewal_writes_at_the_version_the_last_answered() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    clock.at(17, stop)
    with pytest.raises(Stopped):
        bounded(taken.hold)
    assert fake.written == [Write(0, "a", 0, None), Write(5, "a", 0, "1"), Write(10, "a", 0, "2"),
                            Write(15, "a", 0, "3")]
    assert clock.sleeps == [5, 5, 5, 5]  # the fourth stopped at 17


def test_one_failed_renewal_costs_nothing_and_the_next_deadline_counts_from_the_answering_send() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    fake.write_s = 1.0
    fake.write_errors = [Unreachable("503", status=503), None, Unreachable("503", status=503),
                         Unreachable("503", status=503)]
    with pytest.raises(Lost, match="no renewal succeeded within 15 s"):
        bounded(taken.hold)
    # Each renewal is sent 5 s after the one before was sent, however long that one took. The
    # renewal sent at 10 answered at 11: the 15 s count from 10.
    assert [w.at for w in fake.written] == [0, 5, 10, 15, 20]
    assert clock.now == 25


def test_a_renewal_cut_at_its_bound_is_followed_by_one_sent_at_once_and_costs_nothing() -> None:
    # The renewal sent at 5 goes unanswered and is cut at its 5 s bound, at 10 (`TimeoutError`, as
    # asyncio.timeout raises it): the next is sent at 10, not 5 s after the cut, at the deadline.
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    fake.write_s = 5.0
    fake.write_errors = [TimeoutError()]
    clock.at(10, lambda: setattr(fake, "write_s", 0.0))  # the API answers at once from 10 on
    clock.at(16, stop)
    with pytest.raises(Stopped):
        bounded(taken.hold)
    assert fake.written == [Write(0, "a", 0, None), Write(5, "a", 0, "1"), Write(10, "a", 0, "1"),
                            Write(15, "a", 0, "2")]
    assert clock.sleeps == [5, 5, 5]  # none between the cut and the next send
    assert fake.record is not None and (fake.record.holder, fake.record.version) == ("a", "3")


def test_two_failed_renewals_lose_it_15_s_after_the_last_success_was_sent() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    fake.write_s = 1.0
    fake.write_errors = [None, Unreachable("503", status=503), Unreachable("503", status=503)]
    with pytest.raises(Lost, match="no renewal succeeded within 15 s") as raised:
        bounded(taken.hold)
    assert [w.at for w in fake.written] == [0, 5, 10, 15]  # two written after the success sent at 5
    assert clock.now == 20  # cut at the deadline: the sleep before a renewal is
    assert str(raised.value) == "no renewal succeeded within 15 s"


def test_after_a_take_the_deadline_counts_from_when_the_taking_write_was_sent() -> None:
    # The write can land as soon as it is sent: the next holder's 15 s may count from then.
    clock = FakeClock()
    fake = FakeLeases(clock)
    fake.write_s = 1.0
    taken = leased(fake, clock)
    bounded(taken.acquire)  # the create, sent at 0 and answered at 1
    fake.write_errors = [Unreachable("503", status=503) for _ in range(5)]
    with pytest.raises(Lost, match="no renewal succeeded within 15 s"):
        bounded(taken.hold)
    assert clock.now == 15 and [w.at for w in fake.written] == [0, 5, 10]


def test_a_renewal_that_conflicts_with_another_holder_read_back_loses_it_at_once() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    clock.at(7, lambda: fake.set("b", 1))
    with pytest.raises(Lost, match="held by b"):
        bounded(taken.hold)
    assert clock.now == 10 and [w.at for w in fake.written] == [0, 5, 10]
    # Lost, nothing is released: the Lease is b's.
    assert bounded(taken.release) is False
    assert fake.writes == 3 and fake.record is not None and fake.record.holder == "b"


def deleted(fake: FakeLeases) -> None:
    fake.record = None


def conflicted_then_deleted(fake: FakeLeases) -> None:
    fake.write_errors = [Conflict(f"replace Lease {fake.name}: 409")]  # another wrote it, and then
    fake.record = None  # it was deleted before the renewal's read back


@pytest.mark.parametrize(("hand", "why"), [
    (deleted, "deleted"),  # the replace finds no Lease
    (conflicted_then_deleted, "deleted"),  # the renewal conflicts, and no Lease is read back
    (lambda fake: fake.set("", 1), "released"),  # the renewal conflicts, and no holder is read back
], ids=["replace-404", "conflict-then-none", "conflict-then-no-holder"])
def test_a_lease_deleted_or_emptied_under_its_holder_is_lost_at_the_renewal_that_meets_it(
    hand: Callable[[FakeLeases], object], why: str,
) -> None:
    # A waiter creates a Lease that is not there, and takes one no one holds, at once.
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    clock.at(7, lambda: hand(fake))
    with pytest.raises(Lost) as raised:
        bounded(taken.hold)
    assert str(raised.value) == f"the Lease {fake.name} was {why} by another hand"
    assert clock.now == 10 and [w.at for w in fake.written] == [0, 5, 10]
    assert bounded(taken.release) is False  # lost: nothing is written
    assert fake.writes == 3


def test_a_renewal_refused_403_is_one_failed_renewal() -> None:
    # The service account's role taken away and given back: waiting may change it.
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    fake.write_errors = [None, Refused("replace Lease fylgja-core: 403 Forbidden", status=403)]
    clock.at(16, stop)
    with pytest.raises(Stopped):
        bounded(taken.hold)
    assert [w.at for w in fake.written] == [0, 5, 10, 15]
    assert fake.record is not None and fake.record.holder == "a"


def test_a_renewal_that_conflicts_with_itself_read_back_goes_on_at_the_new_version_crediting_nothing() -> None:
    # The Lease written under its name at 7, by no renewal of its own: each was answered, so none of
    # them can be what landed, and the deadline still counts from the success sent at 5. A renewal
    # answered 409 never landed: crediting its send would count past a waiter that saw the write at 7.
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    landed: list[Record] = []
    clock.at(7, lambda: landed.append(fake.set("a", 0)))
    clock.at(12, lambda: fake.write_errors.extend([Unreachable("503", status=503)] * 2))  # the next two fail
    with pytest.raises(Lost, match="no renewal succeeded within 15 s"):
        bounded(taken.hold)
    assert fake.written == [Write(0, "a", 0, None), Write(5, "a", 0, "1"), Write(10, "a", 0, "2"),
                            Write(15, "a", 0, landed[0].version)]
    assert clock.now == 20
    assert fake.reads == 2  # acquire's, and the one read back


def test_a_conflict_read_back_as_its_own_credits_the_first_renewal_since_its_last_success_that_went_unanswered(
) -> None:
    # The renewal sent at 5 lands at 5.1 and is cut at its bound, at 10, unanswered; the one sent then
    # meets the Conflict and reads the Lease back as its own. The write that landed was sent no
    # earlier than 5, so a waiter counts from 5.1 at the soonest: the deadline counts from 5, not
    # from 0 (lost at 15, where a cut renewal would cost the Lease) nor from 10 (past the waiter).
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    fake.write_s = 5.0
    fake.write_errors = [TimeoutError()]
    landed: list[Record] = []
    clock.at(5.1, lambda: landed.append(fake.set("a", 0)))  # its write applied, its answer never sent
    clock.at(10, lambda: setattr(fake, "write_s", 0.0))
    clock.at(12, lambda: fake.write_errors.extend([Unreachable("503", status=503)] * 2))  # the next two fail
    with pytest.raises(Lost, match="no renewal succeeded within 15 s"):
        bounded(taken.hold)
    assert fake.written == [Write(0, "a", 0, None), Write(5, "a", 0, "1"), Write(10, "a", 0, "1"),
                            Write(15, "a", 0, landed[0].version)]
    assert clock.now == 20


def test_after_the_starts_renewal_a_conflict_credits_the_first_of_its_unanswered_renewals_not_the_latest() -> None:
    # The server renews once at its start (`_Server.startup`), then `hold`s: three renewals after the
    # take in one deadline. The start's, at 0.5, lands at 0.6 and is cut at 5.5; the one sent then is
    # cut at 10.5, never applied; the one sent then meets the Conflict and reads the Lease back as its
    # own. The write that landed was the first's, so a waiter counts from 0.6: credited 0.5, the Lease
    # is lost at 15.5; credited the latest unanswered, 5.5, it would be held until 20.5, past the waiter.
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    fake.write_s = 5.0
    fake.write_errors = [TimeoutError(), TimeoutError()]
    clock.at(0.6, lambda: fake.set("a", 0))  # the start's renewal applied, its answer never sent
    clock.at(10.5, lambda: setattr(fake, "write_s", 0.0))
    clock.at(11, lambda: fake.write_errors.extend([Unreachable("503", status=503)] * 2))  # the next two fail

    async def started() -> None:
        await clock.sleep(0.5)  # the application built after the take
        await taken.renew()  # as `_Server.startup` does, before `hold`
        await taken.hold()

    with pytest.raises(Lost, match="no renewal succeeded within 15 s"):
        bounded(started)
    assert fake.written == [Write(0, "a", 0, None), Write(0.5, "a", 0, "1"), Write(5.5, "a", 0, "1"),
                            Write(10.5, "a", 0, "1")]
    assert clock.now == 15.5


def test_a_conflict_read_back_as_its_own_credits_no_renewal_the_api_refused() -> None:
    # A renewal refused 403 was never applied, so it is no write that could have landed: the
    # Lease written under its name at 7 is credited nothing, and the deadline counts from 0.
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    fake.write_errors = [Refused("replace Lease fylgja-core: 403 Forbidden", status=403)]
    clock.at(7, lambda: fake.set("a", 0))
    clock.at(21, stop)  # credited a send, it would hold on
    with pytest.raises(Lost, match="no renewal succeeded within 15 s"):
        bounded(taken.hold)
    assert [w.at for w in fake.written] == [0, 5, 10] and clock.now == 15


def test_a_renewal_that_never_answers_is_cut_and_the_lease_lost_at_the_deadline() -> None:
    fake = FakeLeases()

    async def body() -> float:
        taken = Lease(fake, "a", renew_s=0.02, duration_s=0.06)
        start = time.monotonic()
        await taken.acquire()
        fake.stalled = True
        with pytest.raises(Lost, match=r"no renewal succeeded within 0\.06 s"):
            await taken.hold()
        return time.monotonic() - start

    elapsed = bounded(body)
    assert 0.06 <= elapsed < 0.2, elapsed
    assert fake.writes >= 2  # the create, and at least one renewal cut


def test_a_renewal_with_less_than_renew_s_left_is_cut_at_the_deadline() -> None:
    # The renewal sent at 5 has 1 s left: it is cut at 6, not after `renew_s`, at 10.
    fake = FakeLeases()

    async def body() -> float:
        loop = asyncio.get_running_loop()
        taken = Lease(fake, "a", monotonic=loop.time, renew_s=5, duration_s=6)
        start = loop.time()
        await taken.acquire()
        fake.stalled = True
        with pytest.raises(Lost, match="no renewal succeeded within 6 s"):
            await taken.hold()
        return loop.time() - start

    elapsed = bounded(body, loop=Skipping())
    assert 6 <= elapsed < 6.5, elapsed
    assert fake.writes == 2  # the create, and the renewal cut


class Timed(FakeLeases):
    """`FakeLeases` keeping when each write was sent, by the running event loop's clock."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[float] = []

    async def write(self, holder: str, transitions: int, version: str | None) -> Record:
        self.sent.append(asyncio.get_running_loop().time())
        return await super().write(holder, transitions, version)


def test_renewals_that_never_answer_are_each_cut_the_next_sent_at_the_cut_until_the_deadline() -> None:
    # On `Skipping`, the cut asyncio.timeout's own: the renewal sent at 5 is cut at 10, the one sent
    # then is cut at the deadline, 15, and the Lease is lost there, with nothing written at 15.
    fake = Timed()

    async def body() -> tuple[list[float], float]:
        loop = asyncio.get_running_loop()
        taken = Lease(fake, "a", monotonic=loop.time)
        start = loop.time()
        await taken.acquire()
        fake.stalled = True
        with pytest.raises(Lost, match="no renewal succeeded within 15 s"):
            await taken.hold()
        return [round(at - start, 1) for at in fake.sent], loop.time() - start

    sent, elapsed = bounded(body, loop=Skipping())
    assert sent == [0, 5, 10]
    assert 15 <= elapsed < 15.5, elapsed


class CutOff:
    """`lease.Api` over `fake` for the holder `a`, on the running loop's clock from `start`: its renewal
    at 5 lands at 5.1 and is never answered, and from 12 on its every call fails, its egress cut."""

    def __init__(self, fake: FakeLeases, start: float) -> None:
        self.fake, self.start, self.writes = fake, start, 0
        self.name = fake.name

    def _cut(self) -> bool:
        return asyncio.get_running_loop().time() - self.start >= 12

    async def read(self) -> Record | None:
        if self._cut():
            raise Unreachable("connect: refused", failure="ConnectError")
        return await self.fake.read()

    async def write(self, holder: str, transitions: int, version: str | None) -> Record:
        self.writes += 1
        if self._cut():
            raise Unreachable("connect: refused", failure="ConnectError")
        if self.writes == 2:  # the renewal at 5
            await asyncio.sleep(0.1)
            await self.fake.write(holder, transitions, version)
            await asyncio.Event().wait()
        return await self.fake.write(holder, transitions, version)

    async def close(self) -> None:
        pass


def test_a_holder_whose_landed_renewal_went_unanswered_stops_before_a_waiter_takes_it() -> None:
    # Two Leases on one record and one clock. `w` reads from 0.2; its read at 5.2 is the first to see
    # the write `a` sent at 5, so it takes at 20.2. `a`'s renewal at 10 meets the Conflict and reads
    # the Lease back as its own; credited the send of that write, 5, `a` stops at 20. Credited the
    # Conflicted renewal's send, 10, it would act until 25, beside `w` for 4.8 s.
    fake = FakeLeases()
    times: dict[str, float] = {}

    async def body() -> None:
        loop = asyncio.get_running_loop()
        start = loop.time()
        a = Lease(CutOff(fake, start), "a", monotonic=loop.time)
        w = Lease(fake, "w", monotonic=loop.time)
        await a.acquire()

        async def holding() -> None:
            with pytest.raises(Lost):
                await a.hold()
            times["a lost"] = loop.time() - start

        async def waiting() -> None:
            await asyncio.sleep(0.2)
            await w.acquire()
            times["w took"] = loop.time() - start

        await asyncio.gather(holding(), waiting())

    bounded(body, loop=Skipping())
    assert times["a lost"] == pytest.approx(20, abs=0.05) and times["w took"] == pytest.approx(20.2, abs=0.05)
    assert times["a lost"] <= times["w took"]  # never two holders at once


def test_a_process_stalled_past_the_duration_loses_it_with_no_write() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    clock.at(7, lambda: clock.jump(16))  # between the renewal at 5 and the next
    with pytest.raises(Lost, match="no renewal succeeded within 15 s"):
        bounded(taken.hold)
    assert clock.now == 23 and [w.at for w in fake.written] == [0, 5]


# release, and what the Lease answers of itself


def test_release_writes_no_holder_at_the_version_held() -> None:
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    assert bounded(taken.release) is True
    assert fake.written[-1] == Write(0, "", 0, "1")
    assert fake.record is not None and (fake.record.holder, fake.record.transitions) == ("", 0)


@pytest.mark.parametrize("failure", ["Conflict", "Unreachable"])
def test_release_swallows_a_failure_as_one_warning(failure: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="fylgja.lease")
    clock = FakeClock()
    fake = FakeLeases(clock)
    taken = held(fake, clock)
    if failure == "Conflict":
        fake.set("b", 1)
    else:
        fake.write_errors = [Unreachable(f"connect to {ADDRESS}: refused", failure="ConnectError")]
    assert bounded(taken.release) is False
    [(level, message)] = logged(caplog)
    assert level == logging.WARNING and fake.name in message and ADDRESS not in message
    assert (failure if failure == "Conflict" else "ConnectError") in message


def test_the_lease_answers_its_apis_name_and_closes_it() -> None:
    fake = FakeLeases(name="fylgja-lease-test")
    taken = Lease(fake, "a")
    assert (taken.name, taken.identity) == ("fylgja-lease-test", "a")
    bounded(taken.close)
    assert fake.closed


def test_the_identity_is_the_host_name() -> None:
    assert lease.identity() == socket.gethostname()


def test_the_constants_are_the_decisions() -> None:
    assert (lease.DURATION_S, lease.RENEW_S, lease.RULE_LOST) == (15, 5, "lease.lost")


# KubeLeases, over a transport that answers as the API does


KUBECONFIG = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [{"name": "example", "cluster": {"server": "https://kube.example:6443"}}],
    "users": [{"name": "example", "user": {"token": "not-a-token"}}],
    "contexts": [{"name": "example", "context": {"cluster": "example", "user": "example"}}],
    "current-context": "example",
}
PATH = "/apis/coordination.k8s.io/v1/namespaces/default/leases"
MESSAGE = f'leases.coordination.k8s.io "x" is forbidden: User "system:serviceaccount" at {ADDRESS}'
"""An API's message, which no failure carries."""


def status(code: int, reason: str, message: str = MESSAGE) -> httpx2.Response:
    return httpx2.Response(code, json={"kind": "Status", "apiVersion": "v1", "metadata": {}, "status": "Failure",
                                       "message": message, "reason": reason, "code": code})


class Server:
    """The Lease API, as a transport's handler: one Lease, created by POST where none is, replaced by
    PUT at the resourceVersion it holds, each write at a new one; every request's method, path and
    body kept. `answer`, when set, answers every request instead, or raises."""

    def __init__(self) -> None:
        self.held: dict[str, Any] | None = None
        self.versions = 0
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.answer: Callable[[], httpx2.Response] | None = None

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if self.answer is not None:
            return self.answer()
        if request.method == "GET":
            return httpx2.Response(200, json=self.held) if self.held else status(404, "NotFound")
        assert body is not None
        if request.method == "POST":
            return status(409, "AlreadyExists") if self.held else self.store(body)
        if self.held is None:
            return status(404, "NotFound")
        if body["metadata"].get("resourceVersion") != self.held["metadata"]["resourceVersion"]:
            return status(409, "Conflict")
        return self.store(body)

    def store(self, body: dict[str, Any]) -> httpx2.Response:
        self.versions += 1
        self.held = copy.deepcopy(body)
        self.held["metadata"] |= {"namespace": "default", "resourceVersion": str(self.versions)}
        return httpx2.Response(201, json=self.held)

    def writes(self) -> list[dict[str, Any]]:
        return [body for method, _, body in self.requests if method in ("POST", "PUT") and body is not None]


def reaching(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx2.Request], httpx2.Response]) -> list[int]:
    """`kubeapi.client` answering clients over a transport answering by `handler`; the list counts
    the clients made."""
    made: list[int] = []

    def client() -> AsyncClient:
        made.append(1)
        return AsyncClient(config=KubeConfig.from_dict(KUBECONFIG), field_manager=kubeapi.FIELD_MANAGER,
                           transport=httpx2.MockTransport(handler))

    monkeypatch.setattr(kubeapi, "client", client)
    return made


def test_kube_leases_writes_a_whole_lease_and_keeps_its_acquire_time_while_its_holder_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = Server()
    reaching(monkeypatch, server)
    times = iter([f"2026-11-06T10:00:0{n}.00000{n}Z" for n in range(1, 6)])
    monkeypatch.setattr(wall_clock, "now", lambda: next(times))
    read: list[Record | None] = []

    async def body() -> None:
        leases = KubeLeases("fylgja-lease-test")
        try:
            read.append(await leases.read())
            made = await leases.write("a", 0, None)
            renewed = await leases.write("a", 0, made.version)
            assert server.held is not None
            server.held["spec"]["holderIdentity"] = "b"  # b took it
            read.append(await leases.read())
            server.held["spec"]["holderIdentity"] = ""  # and released it
            free = await leases.read()
            read.append(free)
            assert renewed.version == "2" and free is not None
            taken = await leases.write("a", 1, free.version)
            await leases.write("", 1, taken.version)
        finally:
            await leases.close()

    bounded(body)
    assert [(method, path) for method, path, _ in server.requests] == [
        ("GET", f"{PATH}/fylgja-lease-test"), ("POST", PATH), ("PUT", f"{PATH}/fylgja-lease-test"),
        ("GET", f"{PATH}/fylgja-lease-test"), ("GET", f"{PATH}/fylgja-lease-test"),
        ("PUT", f"{PATH}/fylgja-lease-test"), ("PUT", f"{PATH}/fylgja-lease-test")]

    def lease_of(spec: dict[str, Any], version: str | None = None) -> dict[str, Any]:
        metadata = {"name": "fylgja-lease-test"} | ({"resourceVersion": version} if version else {})
        return {"apiVersion": "coordination.k8s.io/v1", "kind": "Lease", "metadata": metadata,
                "spec": {"leaseDurationSeconds": 15} | spec}

    t1, t2, t3, t4 = (f"2026-11-06T10:00:0{n}.00000{n}Z" for n in range(1, 5))
    assert server.writes() == [
        lease_of({"holderIdentity": "a", "renewTime": t1, "acquireTime": t1, "leaseTransitions": 0}),
        lease_of({"holderIdentity": "a", "renewTime": t2, "acquireTime": t1, "leaseTransitions": 0}, "1"),
        lease_of({"holderIdentity": "a", "renewTime": t3, "acquireTime": t3, "leaseTransitions": 1}, "2"),
        lease_of({"holderIdentity": "", "renewTime": t4, "leaseTransitions": 1}, "3"),
    ]
    first, other, free = read
    assert first is None
    assert other is not None and (other.holder, other.transitions, other.version) == ("b", 0, "2")
    assert free is not None and free.holder == "" and free.renewed == other.renewed != ""


def test_kube_leases_writes_a_time_at_a_whole_second_a_microsecond_later(monkeypatch: pytest.MonkeyPatch) -> None:
    # lightkube writes a whole second with no fraction, which the API refuses for a MicroTime
    # (verified-facts.md, "A time at a whole second is refused").
    server = Server()
    reaching(monkeypatch, server)
    monkeypatch.setattr(wall_clock, "now", lambda: "2026-11-06T10:00:00.000000Z")

    async def body() -> None:
        leases = KubeLeases("fylgja-lease-test")
        try:
            await leases.write("a", 0, None)
        finally:
            await leases.close()

    bounded(body)
    [written] = server.writes()
    assert (written["spec"]["renewTime"], written["spec"]["acquireTime"]) == ("2026-11-06T10:00:00.000001Z",) * 2


@pytest.mark.parametrize(("call", "answer", "raised", "code"), [
    ("read", lambda: status(403, "Forbidden"), Refused, 403),
    ("read", lambda: status(401, "Unauthorized"), Refused, 401),
    ("write", lambda: status(403, "Forbidden"), Refused, 403),
    ("write", lambda: status(404, "NotFound"), Refused, 404),
    ("write", lambda: status(409, "Conflict"), Conflict, None),
    ("read", lambda: status(500, "InternalError"), Unreachable, 500),
    ("write", lambda: status(429, "TooManyRequests"), Unreachable, 429),
    ("read", lambda: httpx2.Response(503, text=f"upstream {ADDRESS} unavailable"), Unreachable, 503),
], ids=["read-403", "read-401", "write-403", "write-404", "write-409", "read-500", "write-429", "read-503-text"])
def test_kube_leases_answers_the_apis_refusals_by_their_status_and_never_their_text(
    monkeypatch: pytest.MonkeyPatch, call: str, answer: Callable[[], httpx2.Response], raised: type[Exception],
    code: int | None,
) -> None:
    server = Server()
    server.answer = answer
    reaching(monkeypatch, server)
    error = failed(call)
    assert type(error) is raised
    assert getattr(error, "status", None) == code
    assert ADDRESS not in str(error) and ADDRESS not in "".join(traceback.format_exception(error))


@pytest.mark.parametrize("transport", [httpx2.ConnectError(f"connect to {ADDRESS}: refused"),
                                       httpx2.ReadTimeout(f"read from {ADDRESS} timed out")],
                         ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("call", ["read", "write"])
def test_kube_leases_answers_a_transport_failure_as_unreachable_naming_its_type_alone(
    monkeypatch: pytest.MonkeyPatch, call: str, transport: Exception,
) -> None:
    def raising() -> httpx2.Response:
        raise transport

    server = Server()
    server.answer = raising
    reaching(monkeypatch, server)
    error = failed(call)
    assert isinstance(error, Unreachable) and error.status is None
    assert error.failure == type(transport).__name__ and type(transport).__name__ in str(error)
    assert ADDRESS not in str(error) and ADDRESS not in "".join(traceback.format_exception(error))


def failed(call: str) -> Exception:
    """What `KubeLeases`' `call` raised, a write a replace."""

    async def body() -> None:
        leases = KubeLeases("fylgja-lease-test")
        try:
            if call == "read":
                await leases.read()
            else:
                await leases.write("a", 0, "7")
        finally:
            await leases.close()

    with pytest.raises(Exception) as raised:
        bounded(body)
    return raised.value


def test_kube_leases_with_no_cluster_to_reach_is_refused_naming_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kubeapi, "SERVICE_ACCOUNT", tmp_path / "no-service-account")
    monkeypatch.delenv("KUBECONFIG", raising=False)
    with pytest.raises(Refused) as raised:
        bounded(KubeLeases("fylgja-core").read)
    assert raised.value.variable == "KUBECONFIG" and str(raised.value).startswith("KUBECONFIG is not set")


def test_kube_leases_makes_its_client_on_first_use_and_forgets_it_on_close(monkeypatch: pytest.MonkeyPatch) -> None:
    server = Server()
    made = reaching(monkeypatch, server)
    leases = KubeLeases("fylgja-core")
    assert made == []

    async def twice() -> None:
        await leases.read()
        await leases.read()
        await leases.close()

    bounded(twice)  # on one event loop, one client
    bounded(twice)  # and on another, its own
    assert len(made) == 2 and len(server.requests) == 4
    assert leases.name == "fylgja-core"
