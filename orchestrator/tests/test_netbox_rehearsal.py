"""A NetBox branch marked in steps and rehearsed through the library (D-097): the core's own server on its fake runtime
(`served`), the source over `fake_netbox.FakeNetBox` with the reader's `connect` and `read` replaced, on a clock that
never waits. The marks are NetBox's journal entries and their blueprints the core's: the example keeps no store."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fake_netbox import ADDRESS, TOKEN, FakeNetBox
from fylgja_netbox import Result, document
from harness import Clock, Served

from fylgja_orchestrator.netbox import source as module
from fylgja_orchestrator.netbox.source import NetBoxSource, marks_of
from fylgja_orchestrator.rehearsal import ChangeSource, Limits, documents, rehearse, rules

ROOT = Path(__file__).resolve().parents[2]
BLUEPRINTS = ROOT / "testdata" / "blueprint"
DOCUMENT = document.load(ROOT / "netbox" / "seed" / "reader.yaml")
SCOPE = "tag:fylgja"
REF = "third-link"


def blueprint(name: str, observed: str) -> dict[str, Any]:
    """A blueprint of `testdata/`, its source envelope the NetBox reader's, read at `observed`."""
    loaded: dict[str, Any] = json.loads((BLUEPRINTS / name).read_text())
    loaded["source"] = {"source": "netbox", "branch": REF, "scope": SCOPE, "observed_at": observed}
    return loaded


class Reader:
    """The reader, replaced: `main` read as the fixture less its third link, and the branch as each of `branch` in
    turn, the last for every read after; `calls` holds each read's branch."""

    def __init__(self) -> None:
        self.main = blueprint("steps/three-node-unlinked.json", "2026-11-13T09:30:00.000000Z")
        self.branch = [
            blueprint("three-node.json", "2026-11-13T09:00:00.000000Z"),
            blueprint("steps/three-node-n1-disabled.json", "2026-11-13T09:10:00.000000Z"),
        ]
        self.calls: list[str | None] = []

    def connect(self, address: str, token: str, **_: object) -> object:
        return self

    def close(self) -> None:
        pass

    def read(self, conn: object, *, branch: str | None, scope: str, document: object) -> Result:
        assert scope == SCOPE and document is DOCUMENT
        self.calls.append(branch)
        if branch is None:
            return Result(self.main, (), False)
        return Result(self.branch.pop(0) if len(self.branch) > 1 else self.branch[0], (), False)


@pytest.fixture
def marked(
    served: Served, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[NetBoxSource, FakeNetBox, Reader, list[str | None]]]:
    """A source of a branch marked twice, `third-link` and then `n1-address`, through `served`'s core, in an empty
    directory of the test's own; and the marks' blueprint ids."""
    here = tmp_path / "cwd"
    here.mkdir()
    monkeypatch.chdir(here)
    netbox, reader = FakeNetBox(), Reader()
    monkeypatch.setattr(module, "connect", reader.connect)
    monkeypatch.setattr(module, "read", reader.read)
    netbox.branch(REF, tags=("fylgja-rehearse",))
    source = NetBoxSource(ADDRESS, TOKEN, DOCUMENT, served.client, transport=httpx.MockTransport(netbox))
    change = source.change(REF)
    ids = [source.mark(change, label, SCOPE).blueprint_id for label in ("third-link", "n1-address")]
    reader.calls.clear()
    yield source, netbox, reader, ids
    source.close()
    assert netbox.keyed, "a request was sent without the token in Authorization alone, or under a branch"
    assert list(here.iterdir()) == [], "the example kept something of the marks on its disk"


def rehearsed(served: Served, source: NetBoxSource) -> dict[str, Any]:
    c = Clock()
    seam: ChangeSource = source
    doc = rehearse(seam, served.client, REF, SCOPE, run_id="r1", limits=Limits(), clock=c.now, sleep=c.sleep)
    assert documents.validate("rehearsal-1", doc) == []
    return doc


def test_a_marked_change_is_rehearsed_from_main_through_its_marks_to_its_head_and_reported_on_the_branch(
    served: Served, marked: tuple[NetBoxSource, FakeNetBox, Reader, list[str | None]]
) -> None:
    source, netbox, reader, ids = marked
    assert all(ids) and len(set(ids)) == 2
    doc = rehearsed(served, source)
    assert doc["status"] == "passed", doc["headline"]
    stages = doc["plan"]["stages"]
    assert [stage["label"] for stage in stages] == ["main", "third-link", "n1-address", "head"]
    assert [stage["blueprint_id"] for stage in stages[1:3]] == ids
    assert reader.calls == [None, REF], "the reader was asked for more than main and the head"
    assert len(netbox.entries) == 3
    report = netbox.entries[-1]
    assert report["kind"]["value"] == "success"
    assert report["comments"].startswith("## Rehearsal passed")
    assert [mark.label for mark in marks_of(netbox.entries)] == ["third-link", "n1-address"]
    assert served.client.list_twins() == []


def test_a_report_netbox_refuses_keeps_the_status(
    served: Served, marked: tuple[NetBoxSource, FakeNetBox, Reader, list[str | None]]
) -> None:
    source, netbox, _, _ = marked
    denied = {"detail": "You do not have permission to perform this action."}
    netbox.scripted[("POST", "extras/journal-entries/")] = [httpx.Response(403, json=denied)]
    doc = rehearsed(served, source)
    assert doc["status"] == "passed"
    assert [f["rule"] for f in doc["findings"]].count(rules.REPORT_UNPOSTED) == 1
    assert len(netbox.entries) == 2
