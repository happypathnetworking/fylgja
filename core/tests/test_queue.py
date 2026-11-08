"""The work queue and its pool of workers (D-023): one name waits once, one worker holds a
twin at a time, and a failing handler does not stop the pool."""

from __future__ import annotations

import asyncio
import time

import pytest

from fylgja_core.queue import Closed, Workers, WorkQueue


def test_a_name_put_twice_is_served_once() -> None:
    async def scenario() -> list[str]:
        q = WorkQueue()
        q.put("a")
        q.put("a")
        assert q.waiting() == ["a"]
        first = await q.get()
        q.done(first)
        assert q.waiting() == []
        return [first]

    assert asyncio.run(scenario()) == ["a"]


def test_a_delayed_name_is_served_after_its_delay_and_after_a_due_one() -> None:
    async def scenario() -> tuple[list[str], float]:
        q = WorkQueue()
        start = time.monotonic()
        q.put("b", delay_s=0.2)
        q.put("a")
        order = []
        for _ in range(2):
            name = await q.get()
            order.append(name)
            q.done(name)
        return order, time.monotonic() - start

    order, elapsed = asyncio.run(scenario())
    assert order == ["a", "b"]
    assert elapsed >= 0.2


def test_the_earlier_deadline_wins() -> None:
    async def scenario() -> float:
        q = WorkQueue()
        q.put("a", delay_s=5.0)
        q.put("a")
        start = time.monotonic()
        await q.get()
        return time.monotonic() - start

    assert asyncio.run(scenario()) < 1.0


def test_a_name_put_while_active_is_served_again_once_after_done() -> None:
    async def scenario() -> None:
        q = WorkQueue()
        q.put("a")
        name = await q.get()
        q.put("a")
        q.put("a")
        assert q.waiting() == []
        q.done(name)
        assert q.waiting() == ["a"]
        again = await q.get()
        q.done(again)
        assert q.waiting() == []

    asyncio.run(scenario())


def test_a_delay_asked_while_active_is_kept_when_the_worker_lets_go() -> None:
    # The loop requeues a twin with a backoff from inside its own pass: the delay must hold.
    async def scenario() -> float:
        q = WorkQueue()
        q.put("a")
        name = await q.get()
        q.put("a", delay_s=0.3)
        q.done(name)
        assert q.waiting() == ["a"]
        start = time.monotonic()
        await q.get()
        return time.monotonic() - start

    assert asyncio.run(scenario()) >= 0.25


def test_the_earlier_deadline_asked_while_active_wins() -> None:
    async def scenario() -> float:
        q = WorkQueue()
        q.put("a")
        name = await q.get()
        q.put("a", delay_s=5.0)
        q.put("a")
        q.done(name)
        start = time.monotonic()
        await q.get()
        return time.monotonic() - start

    assert asyncio.run(scenario()) < 1.0


async def taken(q: WorkQueue) -> str:
    """The name `q` serves next, within 10 s: a name never queued again fails the test, not the suite."""
    return await asyncio.wait_for(q.get(), timeout=10)


def test_a_nudge_waits_out_a_backoff_and_a_put_does_not() -> None:
    # A driver's event nudges its twin; a client's write puts it.
    async def scenario() -> tuple[float, float]:
        q = WorkQueue()
        q.back_off("a", 0.3)
        q.nudge("a")
        start = time.monotonic()
        name = await taken(q)
        nudged = time.monotonic() - start
        q.done(name)
        q.back_off("a", 5.0)
        q.put("a")
        start = time.monotonic()
        await taken(q)
        return nudged, time.monotonic() - start

    nudged, put = asyncio.run(scenario())
    assert nudged >= 0.25 and put < 1.0


def test_a_nudge_while_active_is_served_after_done_at_once_or_once_a_backoff_asked_meanwhile_ends() -> None:
    # The loop's own pass raises events: they cost one pass after it, or wait out the backoff it failed into.
    async def scenario() -> tuple[float, float]:
        q = WorkQueue()
        q.put("a")
        name = await taken(q)
        q.nudge("a")
        q.done(name)
        start = time.monotonic()
        name = await taken(q)
        at_once = time.monotonic() - start
        q.nudge("a")
        q.back_off("a", 0.3)
        q.done(name)
        assert q.waiting() == ["a"]
        start = time.monotonic()
        await taken(q)
        return at_once, time.monotonic() - start

    at_once, held = asyncio.run(scenario())
    assert at_once < 0.2 and held >= 0.25


def test_a_put_while_active_is_served_after_done_at_once_whatever_backoff_was_asked_meanwhile() -> None:
    async def scenario() -> float:
        q = WorkQueue()
        q.put("a")
        name = await taken(q)
        q.put("a")
        q.back_off("a", 5.0)
        q.done(name)
        start = time.monotonic()
        await taken(q)
        return time.monotonic() - start

    assert asyncio.run(scenario()) < 1.0


def test_a_backoff_ends_when_its_name_is_taken() -> None:
    # A pass a put brought forward ends the backoff: an event after it is served at once.
    async def scenario() -> float:
        q = WorkQueue()
        q.back_off("a", 5.0)
        q.put("a")
        name = await taken(q)
        q.done(name)
        q.nudge("a")
        start = time.monotonic()
        await taken(q)
        return time.monotonic() - start

    assert asyncio.run(scenario()) < 1.0


def test_an_active_name_is_not_served_to_a_second_worker() -> None:
    async def scenario() -> bool:
        q = WorkQueue()
        q.put("a")
        await q.get()
        q.put("a")
        try:
            await asyncio.wait_for(q.get(), timeout=0.1)
        except TimeoutError:
            return True
        return False

    assert asyncio.run(scenario())


def test_close_wakes_a_waiting_getter_with_closed() -> None:
    async def scenario() -> None:
        q = WorkQueue()
        getter = asyncio.ensure_future(q.get())
        await asyncio.sleep(0.05)
        q.close()
        with pytest.raises(Closed):
            await getter
        with pytest.raises(Closed):
            await q.get()

    asyncio.run(scenario())


def test_the_pool_never_exceeds_its_size_and_handles_every_name() -> None:
    async def scenario() -> tuple[int, set[str]]:
        q = WorkQueue()
        running = 0
        peak = 0
        handled: set[str] = set()

        async def handle(name: str) -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1
            handled.add(name)

        workers = Workers(q, handle, size=2)
        await workers.start()
        for name in ("a", "b", "c"):
            q.put(name)
        while len(handled) < 3:
            await asyncio.sleep(0.01)
        await workers.stop()
        return peak, handled

    peak, handled = asyncio.run(scenario())
    assert peak == 2
    assert handled == {"a", "b", "c"}


def test_a_handler_that_raises_does_not_stop_the_pool(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[str]:
        q = WorkQueue()
        handled: list[str] = []

        async def handle(name: str) -> None:
            if name == "bad":
                raise RuntimeError("boom")
            handled.append(name)

        workers = Workers(q, handle, size=1)
        await workers.start()
        q.put("bad")
        q.put("good", delay_s=0.05)
        while not handled:
            await asyncio.sleep(0.01)
        await workers.stop()
        return handled

    assert asyncio.run(scenario()) == ["good"]
    (line,) = [r for r in caplog.records if "bad" in r.getMessage()]
    assert line.exc_info and getattr(line, "fields", None) == {"twin": "bad"}


class FailingOnce(WorkQueue):
    """A queue whose first `get` fails, as one bound to another event loop would."""

    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    async def get(self) -> str:
        if not self.failed:
            self.failed = True
            raise RuntimeError("bound to a different event loop")
        return await super().get()


def test_a_get_that_fails_is_logged_and_the_worker_goes_on(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[str]:
        q = FailingOnce()
        handled: list[str] = []

        async def handle(name: str) -> None:
            handled.append(name)

        workers = Workers(q, handle, size=1, retry_s=0.01)
        await workers.start()
        q.put("a")
        while not handled:
            await asyncio.sleep(0.01)
        await workers.stop()
        return handled

    assert asyncio.run(scenario()) == ["a"]
    assert any("could not take a name" in r.getMessage() and r.exc_info for r in caplog.records)


def test_stop_ends_every_task() -> None:
    async def scenario() -> list[bool]:
        q = WorkQueue()

        async def handle(name: str) -> None:
            await asyncio.sleep(10)

        workers = Workers(q, handle, size=3)
        await workers.start()
        q.put("a")
        await asyncio.sleep(0.05)
        tasks = list(workers.tasks)
        await workers.stop()
        return [t.done() for t in tasks]

    assert asyncio.run(scenario()) == [True, True, True]
