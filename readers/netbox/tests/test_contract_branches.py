"""The NetBox reader's contract tier's branches, its fixtures' own functions over `httpx.MockTransport`: no contract
branch outlives its test, whatever the test did, and the tier deletes no branch but its own. The functions are written
again from `netbox/tests/contract/conftest.py`, which cannot be imported, so they are held here as
`netbox/tests/test_contract_branches.py` holds that conftest's.

Nothing here opens a socket: NetBox is a fake that keeps the branches it is given and every request it is sent.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from contract import conftest
from contract.conftest import BoxError, Writes, as_row, scratch, sweep, writer

from fylgja_netbox.rows import Branch

HOST = "netbox.example"
ADDRESS = f"http://{HOST}"
BRANCHES = "/api/plugins/branching/branches/"
SYNCED = "2026-11-12T16:30:00.115200Z"


PROVISIONING = "A branch in the provisioning status may not be deleted."
"""NetBox's words in its 500 to a `DELETE` of a branch still provisioning (design/verified-facts.md, "A branch deleted
before it is `ready`")."""


class Branches:
    """A fake of NetBox's branches: each made answers `status`, and `?name=` selects by the whole name. A branch named
    in `provisioning` is made `provisioning` and reads `ready` once it has been read, by its id or by its name, that
    many times; one named in `failing` the same, and then reads `failed`; one named in `vanishing` the same, and then
    is gone. A `DELETE` of a branch whose status is in `refused` answers 500 in NetBox's words, as NetBox does for one
    still provisioning."""

    def __init__(
        self,
        *names: str,
        status: str = "ready",
        provisioning: dict[str, int] | None = None,
        failing: dict[str, int] | None = None,
        vanishing: dict[str, int] | None = None,
        refused: tuple[str, ...] = ("provisioning",),
    ) -> None:
        self.status = status
        self.refused = refused
        self.rows: dict[int, dict[str, Any]] = {}
        self.made = 0
        self.sent: list[tuple[str, str]] = []
        self.turns: dict[int, tuple[int, str | None]] = {}
        for name in names:
            self.make(name)
        for then, held in (("ready", provisioning), ("failed", failing), (None, vanishing)):
            for name, reads in (held or {}).items():
                row = self.make(name)
                row["status"] = {"value": "provisioning"}
                self.turns[row["id"]] = (reads, then)

    def make(self, name: str) -> dict[str, Any]:
        self.made += 1
        row = {
            "id": self.made,
            "name": name,
            "schema_id": "p9d46y7z",
            "status": {"value": self.status},
            "last_sync": SYNCED,
        }
        self.rows[self.made] = row
        return row

    def _read(self, number: int) -> None:
        """One read of the branch `number`, which moves it on where it has turns left."""
        if number not in self.turns:
            return
        reads, then = self.turns[number]
        if reads > 1:
            self.turns[number] = (reads - 1, then)
            return
        del self.turns[number]
        if then is None:
            del self.rows[number]
        else:
            self.rows[number]["status"] = {"value": then}

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
        if request.method == "GET":
            self._read(number)
        if number not in self.rows:
            return httpx.Response(404, json={"detail": "No Branch matches the given query."})
        row = self.rows[number]
        if request.method == "DELETE":
            if row["status"]["value"] in self.refused:
                return httpx.Response(500, json={"error": PROVISIONING, "exception": "AbortRequest"})
            del self.rows[number]
            return httpx.Response(204)
        return httpx.Response(200, json=row)

    def deleted(self) -> list[str]:
        return [path for method, path in self.sent if method == "DELETE"]


def over(fake: Branches) -> Writes:
    return writer(ADDRESS, "nbt_k.t", transport=httpx.MockTransport(fake))


NAME = "fylgja-contract-0a1b2c3d"


def test_a_test_that_raises_still_deletes_its_branch() -> None:
    fake = Branches()
    with pytest.raises(RuntimeError), scratch(over(fake), NAME) as made:
        assert as_row(made) == Branch(1, NAME, "p9d46y7z", "ready", SYNCED)
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
    assert sweep(over(fake)) == [NAME, "fylgja-contract-ffff0000"]
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
    assert sweep(over(fake)) == [NAME]
    assert fake.rows == {}
    assert [method for method, _ in fake.sent].count("DELETE") == 1
    assert 0 < clock.now < conftest.BRANCH_WAIT_S


def test_a_branch_that_stays_provisioning_is_reported_by_its_wait_not_by_the_delete(clock: Clock) -> None:
    """`scratch`'s `branched` times out on a branch that never leaves provisioning, and its `finally` waits again and
    raises that wait's error, naming the branch, and sends no `DELETE` NetBox would refuse 500."""
    fake = Branches()
    box = over(fake)
    fake.make(NAME)["status"] = {"value": "provisioning"}
    with pytest.raises(BoxError) as raised, scratch(box, NAME):
        pass
    assert NAME in str(raised.value) and "still provisioning" in str(raised.value)
    assert PROVISIONING not in str(raised.value)
    assert fake.deleted() == []
    assert clock.now >= 2 * conftest.BRANCH_WAIT_S


def test_the_sweep_reports_a_branch_that_stays_provisioning(clock: Clock) -> None:
    fake = Branches(provisioning={NAME: 10**6})
    with pytest.raises(BoxError) as raised:
        sweep(over(fake))
    assert NAME in str(raised.value) and "still provisioning" in str(raised.value)
    assert fake.deleted() == []
    assert [method for method, _ in fake.sent].count("POST") == 0


def test_a_branch_gone_when_the_wait_ends_is_neither_deleted_nor_reported_as_swept(clock: Clock) -> None:
    """The wait reads the branch by its name and makes none: one that is gone before it settles is no branch the
    sweep deleted."""
    fake = Branches(vanishing={NAME: 2})
    assert sweep(over(fake)) == []
    assert fake.rows == {}
    assert [method for method, _ in fake.sent if method != "GET"] == []
    assert clock.now < conftest.BRANCH_WAIT_S


def test_a_branch_that_turns_failed_is_deleted(clock: Clock) -> None:
    fake = Branches(failing={NAME: 2})
    assert sweep(over(fake)) == [NAME]
    assert fake.rows == {}
    assert [method for method, _ in fake.sent if method != "GET"] == ["DELETE"]


def test_a_failed_branch_netbox_will_not_delete_is_reported_by_its_name(clock: Clock) -> None:
    """A `DELETE` of a `failed` branch was not read: where NetBox refuses it, the refusal names the branch."""
    fake = Branches(failing={NAME: 2}, refused=("provisioning", "failed"))
    with pytest.raises(BoxError) as raised:
        sweep(over(fake))
    assert NAME in str(raised.value) and "failed" in str(raised.value)
    assert len(fake.deleted()) == 1


def test_the_writers_repr_holds_no_address() -> None:
    """pytest prints a failing test's arguments by their repr."""
    assert HOST not in repr(over(Branches()))


def test_a_branch_answered_for_another_name_is_neither_waited_for_nor_deleted() -> None:
    """Where NetBox's filter answered another branch than the one asked, the tier would delete that one."""
    sent: list[str] = []

    def wrong(request: httpx.Request) -> httpx.Response:
        sent.append(request.method)
        rows = [{"id": 4, "name": "third-link", "schema_id": "p9d46y7z", "status": {"value": "ready"}}]
        return httpx.Response(200, json={"count": 1, "next": None, "previous": None, "results": rows})

    box = writer(ADDRESS, "nbt_k.t", transport=httpx.MockTransport(wrong))
    with pytest.raises(BoxError) as raised, scratch(box, NAME):
        pass
    assert NAME in str(raised.value) and "third-link" in str(raised.value)
    assert "DELETE" not in sent
