"""Server-sent events: the message format, a watch's keepalive, and a watch that releases its
store subscription however it ends, read or not."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from fylgja_core import run
from fylgja_core.client import messages
from fylgja_core.findings import Subject, Verdict
from fylgja_core.local_store import LocalStore
from fylgja_core.run import Event
from fylgja_core.server import sse
from fylgja_core.store import NotFound
from fylgja_core.twin_record import Spec, Status, TwinRecord


@pytest.fixture
def store(tmp_path: Path) -> Iterator[LocalStore]:
    s = LocalStore.open(tmp_path / "store")
    yield s
    s.close()


def a_twin(store: LocalStore, name: str = "t") -> TwinRecord:
    spec = Spec(blueprint_id="a" * 64, driver="fake", allow_restart=False)
    return store.create_twin(TwinRecord(name=name, revision=1, generation=1, spec=spec,
                                        status=Status(observed_generation=0, conditions=(), nodes=())))


def test_a_message_is_its_lines_and_a_blank_line() -> None:
    assert sse.message("ADDED", {"a": [1, "x\ny"]}) == b'event: ADDED\ndata: {"a":[1,"x\\ny"]}\n\n'
    assert sse.message(None, {}, id="7") == b"id: 7\ndata: {}\n\n"
    (parsed,) = messages(sse.message("MODIFIED", {"b": 2}, id="3").decode().split("\n"))
    assert (parsed.event, parsed.id, json.loads(parsed.data)) == ("MODIFIED", "3", {"b": 2})


def test_an_idle_watch_sends_a_comment_then_the_next_change(store: LocalStore) -> None:
    record = a_twin(store)

    async def watch() -> list[bytes]:
        stream = sse.twin_stream(store, "t", None, keepalive_s=0.01)
        first, keepalive = await anext(stream), await anext(stream)
        store.update_twin(record, 1)
        change = await anext(stream)
        await stream.aclose()
        return [first, keepalive, change]

    first, keepalive, change = asyncio.run(watch())
    assert first.startswith(b"event: ADDED\n") and keepalive == b": keepalive\n\n"
    assert change.startswith(b"event: MODIFIED\n") and b'"revision":2' in change
    assert store._subscriptions == []


def test_a_watch_never_read_releases_its_subscription(store: LocalStore) -> None:
    a_twin(store)

    async def unread() -> int:
        stream = sse.twin_stream(store, None, None)
        held = len(store._subscriptions)
        await stream.aclose()
        return held

    assert asyncio.run(unread()) == 1 and store._subscriptions == []


def test_a_watch_of_a_twin_that_does_not_exist_holds_nothing(store: LocalStore) -> None:
    async def absent() -> None:
        sse.twin_stream(store, "nope", None)

    with pytest.raises(NotFound):
        asyncio.run(absent())
    assert store._subscriptions == []


def test_a_runs_stream_ends_once_the_run_has_ended_and_sent_every_event(store: LocalStore) -> None:
    queued = run.queued("t", "create", "alice")
    store.create_run(queued)
    for outcome in ("started", "done"):
        store.append_event(queued.id, Event(seq=0, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome=outcome))

    async def follow() -> list[bytes]:
        sent = []
        async for chunk in sse.run_events_stream(store, queued.id, 0, poll_s=0.01, keepalive_s=0.02):
            sent.append(chunk)
            if len(sent) == 4:  # two events and the idle stream's comments: now it ends
                store.update_run(run.ended(queued, verdict_of(queued)), "queued")
        return sent

    sent = asyncio.run(follow())
    assert [m.id for m in messages(b"".join(sent).decode().split("\n"))] == ["1", "2"]
    assert b": keepalive\n\n" in sent


def verdict_of(r: run.Run) -> Verdict:
    return Verdict(operation="create", status="ok", subject=Subject(twin=r.twin, run_id=r.id), findings=())
