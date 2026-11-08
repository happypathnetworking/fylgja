"""A Lease's API and a clock, for the pure tier: `FakeLeases` holds one record in memory and
answers as `lease.KubeLeases` does, and `FakeClock` is a monotonic clock whose sleeps pass at
once. A test reads the arithmetic of the Lease's seconds on it, its calls taking the time it
sets, with no wait."""

from __future__ import annotations

import asyncio
import heapq
import itertools
from collections.abc import Callable
from typing import NamedTuple

from fylgja_core.lease import Api, Conflict, Record, Refused


class Stopped(Exception):
    """Raised by a test's action on the clock, to end a body that would run for ever (`hold`, or
    `acquire` waiting on a holder that renews)."""


class FakeClock:
    """A monotonic clock from 0 that moves only when slept on or advanced: `sleep` passes its
    seconds at once and keeps each in `sleeps`. An action set `at` a time runs when the clock
    reaches it, in order, before the sleep or the call that crosses it returns; what it raises is
    raised there. `jump` moves the clock with nothing run, as a process stalled does."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self._due: list[tuple[float, int, Callable[[], object]]] = []
        self._order = itertools.count()

    def monotonic(self) -> float:
        return self.now

    def at(self, when: float, action: Callable[[], object]) -> None:
        heapq.heappush(self._due, (when, next(self._order), action))

    def jump(self, seconds: float) -> None:
        self.now += seconds

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        await self.advance(seconds)

    async def advance(self, seconds: float) -> None:
        """`seconds` passed, as a call taking them: not a sleep, so not kept in `sleeps`."""
        target = self.now + seconds
        while self._due and self._due[0][0] <= target:
            when, _, action = heapq.heappop(self._due)
            self.now = max(self.now, when)
            action()
        self.now = max(self.now, target)
        await asyncio.sleep(0)


class Write(NamedTuple):
    """One call of `FakeLeases.write`: the clock's time when it was made (0 with no clock), and
    what it asked."""

    at: float
    holder: str
    transitions: int
    version: str | None


class FakeLeases:
    """`lease.Api` over one record, `record`, None for no Lease; a test sets it between calls as
    another process's write (`set`). A write is a compare-and-set as the API's: a create where a
    record is is `Conflict`, a replace at a version not the record's is `Conflict`, and one where
    there is none is `Refused` (a 404). Each answered write makes a new `renewed` and `version`.

    `read_errors` and `write_errors` are queues: each call takes the head, raising it (any
    `BaseException`) or, for None, answering. A read takes `read_s` and a write `write_s` on the
    clock, the error raised at its end. While `stalled`, a write never answers. `reads`, `writes`
    and `written` count and keep every call."""

    def __init__(self, clock: FakeClock | None = None, name: str = "fylgja-core") -> None:
        self.name = name
        self.clock = clock
        self.record: Record | None = None
        self.read_errors: list[BaseException | None] = []
        self.write_errors: list[BaseException | None] = []
        self.read_s = 0.0
        self.write_s = 0.0
        self.stalled = False
        self.reads = 0
        self.writes = 0
        self.written: list[Write] = []
        self.closed = False
        self._versions = itertools.count(1)

    def set(self, holder: str, transitions: int = 0) -> Record:
        """The record as another process writes it, at a new `renewed` and `version`."""
        self.record = self._made(holder, transitions)
        return self.record

    async def read(self) -> Record | None:
        self.reads += 1
        await self._take(self.read_s)
        _raise(self.read_errors)
        return self.record

    async def write(self, holder: str, transitions: int, version: str | None) -> Record:
        self.writes += 1
        self.written.append(Write(self.clock.now if self.clock else 0.0, holder, transitions, version))
        if self.stalled:
            await asyncio.Event().wait()
        await self._take(self.write_s)
        _raise(self.write_errors)
        if version is None and self.record is not None:
            raise Conflict(f"create Lease {self.name}: 409 AlreadyExists")
        if version is not None and self.record is None:
            raise Refused(f"replace Lease {self.name}: 404 NotFound", status=404)
        if version is not None and self.record is not None and self.record.version != version:
            raise Conflict(f"replace Lease {self.name}: 409 Conflict")
        self.record = self._made(holder, transitions)
        return self.record

    async def close(self) -> None:
        self.closed = True

    def _made(self, holder: str, transitions: int) -> Record:
        n = next(self._versions)
        return Record(holder=holder, renewed=f"renewed-{n}", transitions=transitions, version=str(n))

    async def _take(self, seconds: float) -> None:
        if self.clock is not None:
            await self.clock.advance(seconds)
        else:
            await asyncio.sleep(seconds)


def _raise(queue: list[BaseException | None]) -> None:
    if queue and (error := queue.pop(0)) is not None:
        raise error


def _conforms(fake: FakeLeases) -> Api:
    # Never called: mypy holds `FakeLeases` to the API the Lease acts through.
    return fake
