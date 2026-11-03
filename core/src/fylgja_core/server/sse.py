"""Server-sent events, as the HTML standard reads an event stream: the watch of one twin or of
every twin, and the stream of a run's events (formats/api-1.openapi.yaml, D-025).

A twin watch subscribes to the store before it reads, so no write between the two is missed,
and sends each record whole, each revision once. A watch of one twin sends its current record
first (`ADDED` at revision 1, else `MODIFIED`) unless `since_revision` is at or beyond it, then
every write to it in the order the store made them, and ends after `DELETED`. The store keeps no
history, so a client that reconnects with the last revision it saw is sent the record as it
stands, then every later write: it misses no change of state, and is sent none it saw. A watch
of every twin sends each current record (those beyond `since_revision`, when given), then every
change to any twin.

A run's stream polls the store and sends each event with its `seq` as the message's id, so
`Last-Event-ID` resumes it, and ends once the run has ended and every event is sent. An idle
stream sends a comment each `KEEPALIVE_S`, so a client gone without a word is found when the
write fails.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from typing import Any

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from fylgja_core import documents
from fylgja_core.store import Store, Subscription
from fylgja_core.twin_record import TwinRecord

MEDIA_TYPE = "text/event-stream"
KEEPALIVE_S = 15.0
POLL_S = 0.5
_KEEPALIVE = b": keepalive\n\n"


def message(event: str | None, data: Any, id: str | None = None) -> bytes:
    """One message: its `event:` and `id:` lines when given, `data:` the JSON of `data` on one
    line, and the blank line that ends it."""
    lines = [f"event: {event}"] if event is not None else []
    if id is not None:
        lines.append(f"id: {id}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'))}")
    return ("\n".join(lines) + "\n\n").encode()


def _watch_event(kind: str, record: TwinRecord) -> bytes:
    return message(kind, {"type": kind, "object": documents.encode(record)})


class Watch(AsyncIterator[bytes]):
    """A twin watch's messages; `aclose` ends its subscription, whether or not they were read."""

    def __init__(self, subscription: Subscription, messages: AsyncGenerator[bytes]) -> None:
        self._subscription = subscription
        self._messages = messages

    def __aiter__(self) -> Watch:
        return self

    async def __anext__(self) -> bytes:
        return await anext(self._messages)

    async def aclose(self) -> None:
        self._subscription.close()
        await self._messages.aclose()


def twin_stream(
    store: Store, name: str | None, since_revision: int | None, *, keepalive_s: float = KEEPALIVE_S
) -> Watch:
    """The watch of the twin `name`, or of every twin when None, subscribed and read at once on
    the running event loop: `store.NotFound` is raised here, before any stream begins, for a twin
    that does not exist. Close it with `aclose` (`EventStream` does)."""
    subscription = store.subscribe()
    try:
        current = [store.get_twin(name)] if name is not None else store.list_twins()
    except BaseException:
        subscription.close()
        raise
    return Watch(subscription, _twin_messages(subscription, name, since_revision, current, keepalive_s))


async def _twin_messages(
    subscription: Subscription,
    name: str | None,
    since_revision: int | None,
    current: Sequence[TwinRecord],
    keepalive_s: float,
) -> AsyncGenerator[bytes]:
    seen: dict[str, int] = {}  # each twin's revision the client has, sent now or before
    try:
        for record in current:
            seen[record.name] = record.revision
            if since_revision is None or record.revision > since_revision:
                yield _watch_event("ADDED" if record.revision == 1 else "MODIFIED", record)
        while True:
            try:
                change = await asyncio.wait_for(subscription.queue.get(), keepalive_s)
            except TimeoutError:
                yield _KEEPALIVE
                continue
            record = change.record
            if name is not None and record.name != name:
                continue
            if change.type == "DELETED":
                seen.pop(record.name, None)
                yield _watch_event("DELETED", record)
                if name is not None:
                    return
            elif record.revision > seen.get(record.name, 0):  # a write the current record already held is not sent
                seen[record.name] = record.revision
                yield _watch_event(change.type, record)
    finally:
        subscription.close()


async def run_events_stream(
    store: Store, run_id: str, after: int, poll_s: float = POLL_S, *, keepalive_s: float = KEEPALIVE_S
) -> AsyncIterator[bytes]:
    """Each event of the run with `seq` beyond `after`, polled each `poll_s`, until the run has
    ended. Its state is read before its events, so once it reads ended every event is in."""
    quiet = 0.0
    while True:
        ended = store.get_run(run_id).state == "ended"
        events = store.events(run_id, after)
        for event in events:
            yield message(None, documents.encode(event), id=str(event.seq))
            after = event.seq
        if ended:
            return
        quiet = 0.0 if events else quiet + poll_s
        if quiet >= keepalive_s:
            quiet = 0.0
            yield _KEEPALIVE
        await asyncio.sleep(poll_s)


class EventStream(StreamingResponse):
    """A text/event-stream answer that closes its messages however it ends: finished, cut short
    by a client gone, or never begun."""

    def __init__(self, messages: AsyncIterator[bytes]) -> None:
        super().__init__(messages, media_type=MEDIA_TYPE, headers={"Cache-Control": "no-cache"})
        self._messages = messages

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            close = getattr(self._messages, "aclose", None)
            if close is not None:
                await close()
