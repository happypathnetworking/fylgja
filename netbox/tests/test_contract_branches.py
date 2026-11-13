"""The NetBox contract tier's branches, its fixtures' own functions over `httpx.MockTransport`: no contract branch
outlives its test, whatever the test did, and the tier deletes no branch but its own.

Nothing here opens a socket: NetBox is a fake that keeps the branches it is given and every request it is sent.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from box import BRANCH_WAIT_S, Box, BoxError
from contract import conftest
from contract.conftest import delete, scratch, sweep, writer

HOST = "netbox.example"
ADDRESS = f"http://{HOST}"
BRANCHES = "/api/plugins/branching/branches/"


PROVISIONING = "A branch in the provisioning status may not be deleted."
"""NetBox's words in its 500 to a `DELETE` of a branch still provisioning (design/verified-facts.md, "A branch deleted
before it is `ready`")."""


class Branches:
    """A fake of NetBox's branches: each made answers `status`, and `?name=` selects by the whole name. A branch named
    in `provisioning` is made `provisioning` and reads `ready` once it has been read, by its id or by its name, that
    many times; its `DELETE` until then answers 500 in NetBox's words, as NetBox does for one still provisioning."""

    def __init__(self, *names: str, status: str = "ready", provisioning: dict[str, int] | None = None) -> None:
        self.status = status
        self.rows: dict[int, dict[str, Any]] = {}
        self.made = 0
        self.sent: list[tuple[str, str]] = []
        self.turns: dict[int, int] = {}
        for name in names:
            self.make(name)
        for name, reads in (provisioning or {}).items():
            row = self.make(name)
            row["status"] = {"value": "provisioning"}
            self.turns[row["id"]] = reads

    def _read(self, number: int) -> None:
        """One read of the branch `number`, which brings it nearer `ready` where it has turns left."""
        if number not in self.turns:
            return
        self.turns[number] -= 1
        if self.turns[number] == 0:
            del self.turns[number]
            self.rows[number]["status"] = {"value": "ready"}

    def make(self, name: str) -> dict[str, Any]:
        self.made += 1
        row = {"id": self.made, "name": name, "schema_id": "p9d46y7z", "status": {"value": self.status}}
        self.rows[self.made] = row
        return row

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == BRANCHES:
            asked = request.url.params.get("name")
            if asked is not None:
                for number in [n for n, row in self.rows.items() if row["name"] == asked]:
                    self._read(number)
            rows = [row for row in self.rows.values() if asked is None or row["name"] == asked]
            return httpx.Response(200, json={"count": len(rows), "next": None, "previous": None, "results": rows})
        if request.method == "POST":
            return httpx.Response(201, json=self.make(json.loads(request.content)["name"]))
        number = int(request.url.path.removeprefix(BRANCHES).strip("/"))
        if request.method == "DELETE":
            if self.rows[number]["status"]["value"] == "provisioning":
                return httpx.Response(500, json={"error": PROVISIONING, "exception": "AbortRequest"})
            del self.rows[number]
            return httpx.Response(204)
        self._read(number)
        return httpx.Response(200, json=self.rows[number])

    def deleted(self) -> list[str]:
        return [path for method, path in self.sent if method == "DELETE"]


def over(fake: Branches) -> Box:
    return writer(ADDRESS, "nbt_k.t", transport=httpx.MockTransport(fake))


NAME = "fylgja-contract-0a1b2c3d"


def test_a_test_that_raises_still_deletes_its_branch() -> None:
    fake = Branches()
    with pytest.raises(RuntimeError), scratch(over(fake), NAME) as made:
        assert made["name"] == NAME
        raise RuntimeError("the test failed")
    assert fake.deleted() == [f"{BRANCHES}{made['id']}/"]
    assert fake.rows == {}


def test_a_branch_that_is_never_ready_is_still_deleted() -> None:
    fake = Branches(status="failed")
    with pytest.raises(BoxError, match="failed"), scratch(over(fake), NAME):
        pass
    assert [method for method, _ in fake.sent] == ["GET", "POST", "GET", "DELETE"]
    assert fake.rows == {}


def test_the_sweep_deletes_the_tiers_leftovers_and_nothing_else() -> None:
    fake = Branches(NAME, "p9-read-a", "third-link-fylgja-contract-0a1b2c3d", "fylgja-contract-ffff0000")
    sweep(over(fake))
    assert sorted(row["name"] for row in fake.rows.values()) == ["p9-read-a", "third-link-fylgja-contract-0a1b2c3d"]
    assert len(fake.deleted()) == 2


class Clock:
    """A clock the waits read, which each of their sleeps moves on, so that no wait takes a second."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """The conftest's waits on a `Clock`."""
    held = Clock()
    monkeypatch.setattr(conftest, "CLOCK", held)
    monkeypatch.setattr(conftest, "SLEEP", held.sleep)
    return held


def test_the_sweep_waits_for_a_branch_still_provisioning_then_deletes_it(clock: Clock) -> None:
    """A leftover a stopped run made just before it stopped is still provisioning: deleted at once, NetBox would answer
    500 and the session's start would fail."""
    fake = Branches(provisioning={NAME: 3})
    sweep(over(fake))
    assert fake.rows == {}
    assert [method for method, _ in fake.sent].count("DELETE") == 1
    assert [method for method, _ in fake.sent].count("POST") == 0
    assert 0 < clock.now < BRANCH_WAIT_S


def test_delete_waits_for_a_branch_still_provisioning_then_deletes_it(clock: Clock) -> None:
    fake = Branches(provisioning={NAME: 3})
    delete(over(fake), NAME)
    assert fake.rows == {}
    assert [method for method, _ in fake.sent].count("DELETE") == 1
    assert [method for method, _ in fake.sent].count("POST") == 0
    assert 0 < clock.now < BRANCH_WAIT_S


def test_a_branch_that_stays_provisioning_is_reported_by_its_wait_not_by_the_delete(clock: Clock) -> None:
    """The wait is bounded by `BRANCH_WAIT_S`, and a branch still provisioning then is named with its status, and sent
    no `DELETE` NetBox would refuse 500."""
    fake = Branches(provisioning={NAME: 10**6})
    with pytest.raises(BoxError) as raised:
        sweep(over(fake))
    assert NAME in str(raised.value) and "still provisioning" in str(raised.value)
    assert PROVISIONING not in str(raised.value)
    assert fake.deleted() == []
    assert BRANCH_WAIT_S <= clock.now <= BRANCH_WAIT_S + conftest.POLL_S


def test_a_branch_gone_while_it_is_waited_for_is_sent_no_delete(clock: Clock) -> None:
    """A branch the sweep waits on that disappears between two reads, deleted by another hand: the wait ends at the
    read that finds it gone, and no `DELETE` is sent."""
    fake = Branches(provisioning={NAME: 10**6})
    reads = 0

    def vanishing(request: httpx.Request) -> httpx.Response:
        nonlocal reads
        if request.method == "GET":
            reads += 1
            if reads == 3:
                fake.rows.clear()
        return fake(request)

    sweep(writer(ADDRESS, "nbt_k.t", transport=httpx.MockTransport(vanishing)))
    assert fake.deleted() == []
    assert reads == 3
    assert 0 < clock.now < BRANCH_WAIT_S


def test_the_writers_repr_holds_no_address() -> None:
    """pytest prints a failing test's arguments by their repr, and `Box`'s own holds the address."""
    assert HOST in repr(Box(ADDRESS, "nbt_k.t", transport=httpx.MockTransport(Branches())))
    assert HOST not in repr(over(Branches()))


def test_a_branch_answered_for_another_name_is_neither_waited_for_nor_deleted() -> None:
    """Where NetBox's filter answered another branch than the one asked, the tier would delete that one."""

    def wrong(request: httpx.Request) -> httpx.Response:
        rows = [{"id": 4, "name": "third-link", "schema_id": "p9d46y7z", "status": {"value": "ready"}}]
        return httpx.Response(200, json={"count": 1, "next": None, "previous": None, "results": rows})

    sent: list[str] = []

    def keep(request: httpx.Request) -> httpx.Response:
        sent.append(request.method)
        return wrong(request)

    box = Box(ADDRESS, "nbt_k.t", transport=httpx.MockTransport(keep))
    with pytest.raises(BoxError) as raised, scratch(box, NAME):
        pass
    assert NAME in str(raised.value) and "third-link" in str(raised.value)
    assert "DELETE" not in sent
