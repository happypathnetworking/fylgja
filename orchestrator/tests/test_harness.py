"""The harness the rehearsal library is tested over is the core's own server on its fake runtime (D-034): a twin is
made, followed, verified and destroyed through the core's real client, so the library is held to the core's answers.
Its clock never waits, and a wrapped client's calls are the test's where a test names them."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from fylgja_core.client import Client, ProblemError
from harness import Clock, Served, Wrapped, wait_for
from sources import BLUEPRINTS


def test_the_served_core_makes_and_destroys_a_twin_through_the_client(served: Served) -> None:
    client = served.client
    blueprint_id = client.put_blueprint(json.loads((BLUEPRINTS / "three-node.json").read_text()))
    record, _ = client.apply_twin("t", {"blueprint_id": blueprint_id}, if_none_match="*")
    assert client.follow(record, ("create",)).run["verdict"]["status"] == "ok"
    assert client.verify_twin("t")["status"] == "ok"
    client.delete_twin("t")

    def gone() -> bool | None:
        try:
            client.get_twin("t")
        except ProblemError as e:
            return True if e.status == 404 else None
        return None

    wait_for(gone)
    assert served.driver.labs == {}


def test_the_clock_moves_by_what_it_is_asked_and_waits_none_of_it() -> None:
    woken: list[float] = []
    clock = Clock()
    clock.on_sleep = lambda: woken.append(clock.now())
    started = time.monotonic()
    clock.sleep(120.0)
    clock.sleep(2.0)
    assert time.monotonic() - started < 5.0
    assert (clock.now(), clock.slept, woken) == (122.0, [120.0, 2.0], [120.0, 122.0])


def test_a_wrapped_client_answers_the_tests_calls_and_the_clients_others(served: Served) -> None:
    asked: list[str] = []

    def get_twin(name: str) -> tuple[dict[str, Any], str]:
        asked.append(name)
        return {"name": name}, '"1"'

    wrapped = Wrapped(served.client, get_twin=get_twin)
    assert isinstance(wrapped, Client)
    assert wrapped.get_twin("t") == ({"name": "t"}, '"1"') and asked == ["t"]
    assert wrapped.list_twins() == []
    with pytest.raises(TypeError, match="Client has no call get_twins"):
        Wrapped(served.client, get_twins=get_twin)
