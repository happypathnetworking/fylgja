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
    assert any("bad" in r.getMessage() and r.exc_info for r in caplog.records)


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
