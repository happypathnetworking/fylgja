"""The live fixture's snapshot, as the core filed it, read to its id and written back byte for
byte (data-model §4, R-07). The fixture's live read is T017's; until then this test reads
the core's file under the state root's snapshots/ and skips when the host has none."""

import os
from pathlib import Path

import pytest

from fylgja_orchestrator.adapters.infrahub import snapshot

pytestmark = pytest.mark.contract

FIXTURE_ID = "0940db93e2ad1244a097824ececdaa6979500b1ddeeef15ca3cd612da68656ef"
REPO = Path(__file__).resolve().parents[3]


def test_the_fixtures_snapshot_as_the_core_filed_it():
    root = Path(os.environ.get("FYLGJA_STATE_ROOT") or REPO / "local")
    filed = root / "snapshots" / f"{FIXTURE_ID}.json"
    if not filed.is_file():
        pytest.skip(f"{filed} is absent: the core files it at the fixture's first read (fylgja intent read --out)")
    s = snapshot.read(filed)
    assert s["snapshot_id"] == FIXTURE_ID
    assert snapshot.marshal(s) == filed.read_bytes()
