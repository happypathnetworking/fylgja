"""The conformance suite's one tolerance, `reads.readdressed`, and the two calls that clear its mark
(`reads.created`, `reads.remove`), read over a stub harness: the real functions, imported from
`conformance.reads` as `test_conformance_scenarios.py` does, which pulls in no fixture and reaches no
network (the suite's conftest loads only for a collection of `tests/conformance`). The live run of the
scenarios is its own window; this holds the rule they lean on."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from conformance import reads
from conformance.harness import Fylgja, Harness

from fylgja_core import documents
from fylgja_core.twin_record import Condition, Node, Spec, Status, TwinRecord

TWIN = "cf-step"
FIXTURE = Path("steps/third-link.json")
AWAY = "https://192.0.2.10"
HERE = "127.0.0.1:8080"
BEFORE = {"n1": "t1", "n2": "t1", "n3": "t1"}
NOW = {"n1": "t1", "n2": "t2", "n3": "t1"}
"""`n2` made anew by the step; the others kept."""
ID = "a" * 64


def expected(*, added: tuple[str, ...] = (), removed: tuple[str, ...] = ()) -> reads.Expected:
    """The dry run's answer: `n2` recabled, and the nodes added or removed."""
    return reads.Expected(kept=frozenset({"n1", "n2", "n3"}), recabled=frozenset({"n2"}), restarted=frozenset(),
                          recreated=frozenset(), added=frozenset(added), removed=frozenset(removed), refused=None)


class Stub:
    """A harness holding a record of `TWIN` until it is deleted: the reads' functions read these alone."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.held = True
        self.deleted: list[str] = []

    def record(self, twin: str) -> dict[str, Any] | None:
        if not self.held:
            return None
        nodes = tuple(Node(name=n, handle=f"h-{n}", address="192.0.2.1", incarnation=BEFORE[n]) for n in BEFORE)
        record = TwinRecord(
            name=twin, revision=1, generation=1, spec=Spec(blueprint_id=ID, driver="containerlab", allow_restart=False),
            status=Status(observed_generation=1,
                          conditions=(Condition(type="Ready", status="True", since="2026-11-03T10:00:00Z"),),
                          phase="flows", blueprint_id=ID, bundle_id=ID, deployment_id=ID, nodes=nodes))
        encoded: dict[str, Any] = documents.encode(record)
        return encoded

    def leftovers(self, twin: str) -> list[str]:
        return []

    def nodes(self, twin: str) -> dict[str, str]:
        return dict(BEFORE)

    def client(self) -> Stub:
        return self

    def delete(self, path: str) -> Stub:
        self.held = False
        self.deleted.append(path)
        return self

    status_code = 202
    text = ""


@pytest.fixture(autouse=True)
def clean_mark() -> Iterator[None]:
    reads.RESHAPED.clear()
    yield
    reads.RESHAPED.clear()


def readdressed(address: str, e: reads.Expected) -> frozenset[str]:
    return reads.readdressed(cast(Harness, Stub(address)), TWIN, FIXTURE, e, BEFORE, NOW)


def test_away_a_step_that_reshapes_tolerates_a_recabled_node_made_anew() -> None:
    assert readdressed(AWAY, expected(added=("p-a",))) == {"n2"}
    assert TWIN in reads.RESHAPED


def test_a_recabled_node_kept_at_its_incarnation_is_never_named() -> None:
    e = expected(removed=("p-a",))
    assert reads.readdressed(cast(Harness, Stub(AWAY)), TWIN, FIXTURE, e, BEFORE, BEFORE) == frozenset()


def test_here_a_step_that_reshapes_tolerates_none_but_still_marks_the_twin() -> None:
    assert readdressed(HERE, expected(added=("p-a",))) == frozenset()
    assert TWIN in reads.RESHAPED


def test_away_a_step_that_neither_reshapes_nor_follows_one_tolerates_none() -> None:
    assert readdressed(AWAY, expected()) == frozenset()
    assert TWIN not in reads.RESHAPED


def test_the_step_after_a_reshaping_one_tolerates_and_the_second_after_does_not() -> None:
    assert readdressed(AWAY, expected(removed=("p-a",))) == {"n2"}
    assert readdressed(AWAY, expected()) == {"n2"}
    assert TWIN not in reads.RESHAPED
    assert readdressed(AWAY, expected()) == frozenset()


def test_here_the_step_after_a_reshaping_one_tolerates_none() -> None:
    readdressed(HERE, expected(added=("p-a",)))
    assert readdressed(HERE, expected()) == frozenset()


def test_the_mark_is_a_twins_own() -> None:
    reads.RESHAPED.add("cf-other")
    assert readdressed(AWAY, expected()) == frozenset()
    assert "cf-other" in reads.RESHAPED


def fylgja(*args: str) -> tuple[int, str]:
    return 0, ""


def test_a_create_clears_the_twins_mark() -> None:
    reads.RESHAPED.update({TWIN, "cf-other"})
    harness = Stub(AWAY)
    reads.created(cast(Harness, harness), cast(Fylgja, fylgja), TWIN, FIXTURE, BEFORE)
    assert {"cf-other"} == reads.RESHAPED


def test_a_remove_clears_the_twins_mark_and_waits_for_the_twin_to_go() -> None:
    reads.RESHAPED.update({TWIN, "cf-other"})
    harness = Stub(AWAY)
    reads.remove(cast(Harness, harness), TWIN)
    assert {"cf-other"} == reads.RESHAPED
    assert harness.deleted == [f"/v1/twins/{TWIN}"]
    reads.RESHAPED.add(TWIN)
    reads.remove(cast(Harness, harness), TWIN)  # gone already: nothing asked, the mark still cleared
    assert {"cf-other"} == reads.RESHAPED
    assert len(harness.deleted) == 1
