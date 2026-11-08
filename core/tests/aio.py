"""Bounds for the tests of what runs until it is cancelled or closed: a generator or a task that
swallowed its cancel or its close (rule B's failure) fails a test within seconds, where an
unbounded await would hang the suite, which has no per-test timeout.

`bounded` runs a test's body on an event loop of its own, closed whatever ended it, never
`asyncio.run`, whose teardown cancels a task still pending and waits for it for ever, and fails
it once it has run `BODY_S`, by `SIGALRM`, even where the loop never gets control back (a
generator that loops without awaiting anything that suspends, where no asyncio bound can fire).
`cancelled` and `closed` give a cancel and a close `BOUND_S` to end, through `asyncio.wait`;
`asyncio.timeout` and `wait_for` would cancel the waiter and wait again, for ever too.

`Skipping` is an event loop on a fake clock, for a body that `bounded` runs: a backoff or a poll
measured in seconds is crossed at once."""

from __future__ import annotations

import asyncio
import selectors
import signal
import time
from collections.abc import Awaitable, Callable, Coroutine
from types import FrameType
from typing import Any, Protocol

BOUND_S = 2.0
"""How long a cancel or a close may take to end before the test fails."""

BODY_S = 30.0
"""How long `bounded` lets a body run before its test fails: every body ends within about a second."""


class _Overran(BaseException):
    """Raised by `SIGALRM` wherever a body past `BODY_S` is running: a `BaseException`, so code
    under test that catches every `Exception` of its source (rule A), and never a
    `BaseException` (rule B), lets it through."""


class Closable(Protocol):
    def aclose(self) -> Awaitable[None]: ...


class Skipping(asyncio.SelectorEventLoop):
    """An event loop whose clock skips the waits it would make idle: when nothing is ready and its
    next timer is due later, it moves its clock to that timer rather than sleeping, so each timer
    still fires in its order and at its time on `time()`, and a body that waits out a backoff of
    seconds ends at once. Time the loop spends at work passes as it does, so a body that never waits
    is measured in real time. With no timer due it waits for its file descriptors as any loop does.
    Only the loop's clock is moved: `time.monotonic()`, read by the code under test, is not."""

    def __init__(self) -> None:
        self.skipped = 0.0
        super().__init__(_Skipping(self))

    def time(self) -> float:
        return time.monotonic() + self.skipped


class _Skipping(selectors.DefaultSelector):
    """`Skipping`'s selector: a wait for a timer is answered at once, the clock moved past it."""

    def __init__(self, loop: Skipping) -> None:
        super().__init__()
        self._loop = loop

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        ready = super().select(0)
        if ready or (timeout is not None and timeout <= 0):
            return ready
        if timeout is None:  # no timer: a file descriptor alone can wake it
            return super().select(None)
        self._loop.skipped += timeout
        return []


def bounded[T](body: Callable[[], Coroutine[Any, Any, T]], *, loop: asyncio.AbstractEventLoop | None = None) -> T:
    """`body()`'s result, run on `loop` (a new event loop by default), closed whatever ended it. As
    `asyncio.run` does, the asynchronous generators the body left open (a library's own, such as
    httpx's lines) are closed first, within `BOUND_S`, since one that swallows its close would
    hold that too. A body still running after `BODY_S` fails its test: `SIGALRM` raises into
    whatever runs then and stops the loop, which ends at its next turn where the alarm landed in
    another task than the body's; the loop is then closed with nothing more run on it. From the
    main thread alone, as pytest runs a test."""
    loop = asyncio.new_event_loop() if loop is None else loop
    overran = False

    def alarm(signum: int, frame: FrameType | None) -> None:
        nonlocal overran
        overran = True
        loop.stop()
        raise _Overran

    previous = signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, BODY_S)
    try:
        return loop.run_until_complete(body())
    except BaseException as e:
        if overran:  # the alarm's traceback, where it landed, or the stopped loop's, is this one's cause
            raise AssertionError(f"the body ran past {BODY_S:g} s: something it awaits never ends, or a loop in it "
                                 "never awaits anything that suspends") from e
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        try:
            if not overran:
                shutdown = loop.create_task(loop.shutdown_asyncgens())
                loop.run_until_complete(asyncio.wait({shutdown}, timeout=BOUND_S))
        finally:
            loop.close()


async def cancelled(task: asyncio.Task[Any]) -> None:
    """Cancel `task`, and fail unless it has ended within `BOUND_S`, cancelled."""
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=BOUND_S)
    assert task in done, f"the cancel did not end the task within {BOUND_S:g} s: something swallowed it"
    assert task.cancelled()


async def closed(closable: Closable) -> None:
    """Close `closable`, an asynchronous generator or a stream, and fail unless the close has
    returned within `BOUND_S`; what the close raised is raised here."""
    closing = asyncio.ensure_future(closable.aclose())
    done, _ = await asyncio.wait({closing}, timeout=BOUND_S)
    assert closing in done, f"the close did not return within {BOUND_S:g} s: something swallowed it"
    closing.result()
