"""What every store shares beside its interface: the subscriptions a twin write feeds."""

from __future__ import annotations

import asyncio

from store_contract import record

from fylgja_core.store import Change, Subscribers, Subscription


def test_a_subscription_whose_loop_closed_is_dropped_at_the_next_notify() -> None:
    subscribers = Subscribers()

    async def subscribe() -> Subscription:
        return subscribers.subscribe()

    sub = asyncio.run(subscribe())  # its loop is closed on return
    assert len(subscribers) == 1
    subscribers.notify(Change("ADDED", record()))
    assert len(subscribers) == 0 and sub.queue.empty()


def test_a_closed_subscription_is_removed() -> None:
    subscribers = Subscribers()

    async def scenario() -> int:
        with subscribers.subscribe():
            return len(subscribers)

    assert asyncio.run(scenario()) == 1 and len(subscribers) == 0
