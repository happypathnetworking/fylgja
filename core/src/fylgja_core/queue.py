"""The work queue and its pool of workers (D-023).

The queue holds twin names, not tasks. A name already waiting is not added twice (the earlier
deadline wins), and one that arrives while a worker holds its twin is marked dirty and queued
again when the worker is done, so each twin has at most one worker and one run at a time. A
bounded pool of workers keeps one slow twin from holding up the others.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

_log = logging.getLogger("fylgja.queue")


class Closed(Exception):
    """The queue was closed: a waiting `get` ends with it, and so does every later one."""


class WorkQueue:
    """Names due at a deadline, each waiting once, each held by one worker at a time.

    Single-threaded: `put`, `done` and `close` are called from the event loop's thread.
    """

    def __init__(self) -> None:
        self._due: dict[str, float] = {}
        self._active: set[str] = set()
        self._dirty: set[str] = set()
        self._closed = False
        self._changed = asyncio.Condition()
        self._wakes: set[asyncio.Task[None]] = set()

    def put(self, name: str, delay_s: float = 0.0) -> None:
        """Queue `name` after `delay_s`; a name already waiting keeps the earlier deadline, and
        one whose worker is active is marked dirty and queued again at once by `done`."""
        if name in self._active:
            self._dirty.add(name)
            return
        deadline = asyncio.get_running_loop().time() + delay_s
        self._due[name] = min(deadline, self._due.get(name, deadline))
        self._notify()

    async def get(self) -> str:
        """The earliest due name, once its deadline has come; it is active until `done`."""
        loop = asyncio.get_running_loop()
        async with self._changed:
            while True:
                if self._closed:
                    raise Closed
                timeout: float | None = None
                if self._due:
                    name = min(self._due, key=lambda n: self._due[n])
                    timeout = self._due[name] - loop.time()
                    if timeout <= 0:
                        del self._due[name]
                        self._active.add(name)
                        return name
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._changed.wait(), timeout)

    def done(self, name: str) -> None:
        """Release `name`; a name marked dirty meanwhile is queued again at once."""
        self._active.discard(name)
        if name in self._dirty:
            self._dirty.discard(name)
            self.put(name)

    def waiting(self) -> list[str]:
        """The names queued and not yet served, earliest deadline first."""
        return sorted(self._due, key=lambda n: self._due[n])

    def close(self) -> None:
        """End every waiting `get` with `Closed`."""
        self._closed = True
        self._notify()

    def _notify(self) -> None:
        async def wake() -> None:
            async with self._changed:
                self._changed.notify_all()

        task = asyncio.get_running_loop().create_task(wake())
        self._wakes.add(task)
        task.add_done_callback(self._wakes.discard)


class Workers:
    """`size` tasks, each looping `get`, `handle`, `done`; a handler's exception is logged."""

    def __init__(self, queue: WorkQueue, handle: Callable[[str], Awaitable[None]], size: int) -> None:
        self._queue = queue
        self._handle = handle
        self._size = size
        self.tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Spawn the tasks."""
        self.tasks = [asyncio.create_task(self._work()) for _ in range(self._size)]

    async def stop(self) -> None:
        """Cancel every task and wait for it to end."""
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def _work(self) -> None:
        while True:
            try:
                name = await self._queue.get()
            except Closed:
                return
            try:
                await self._handle(name)
            except Exception:
                _log.exception("handling %s failed", name)
            finally:
                self._queue.done(name)
