"""The record a twin (D-086): which change and stage a twin `twin create` or `twin step` made stands at, a file of its
own under the caller's root, replaced whole, trusted only while its blueprint id is the one the twin runs. No database
(Constitution IX): one writer and one reader, both the example's."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest
from sources import CHANGE, SCOPE

from fylgja_orchestrator.rehearsal import record
from fylgja_orchestrator.rehearsal.record import Record

DEMO = Record(twin="demo", change_id=CHANGE.id, ref=CHANGE.ref, scope=SCOPE, label="seeded", blueprint_id="a" * 64,
              written_at="2026-11-09T10:15:11Z")


def test_a_record_written_is_read_back_equal(tmp_path: Path) -> None:
    root = tmp_path / "records"
    record.write(root, DEMO)
    assert record.read(root, "demo") == DEMO
    written = json.loads((root / "twins" / "demo.json").read_text())
    assert written == {"record_version": "1", **dataclasses.asdict(DEMO)}
    assert list(written) == ["record_version", *(f.name for f in dataclasses.fields(Record))]


def test_a_second_write_replaces_the_first_whole(tmp_path: Path) -> None:
    root = tmp_path / "records"
    record.write(root, DEMO)
    moved = dataclasses.replace(DEMO, label="third-node", blueprint_id="b" * 64, written_at="2026-11-09T10:16:00Z")
    record.write(root, moved)
    assert record.read(root, "demo") == moved
    assert [p.name for p in (root / "twins").iterdir()] == ["demo.json"], "a temporary file is left beside it"


@pytest.mark.parametrize(
    "content",
    [
        "{}",
        json.dumps({"record_version": "2", **dataclasses.asdict(DEMO)}),
        json.dumps(dataclasses.asdict(DEMO)),
        json.dumps({"record_version": "1", **dataclasses.asdict(DEMO), "label": 3}),
        json.dumps({"record_version": "1", **dataclasses.asdict(DEMO), "twin": "other"}),
        "[]",
        "not json",
    ],
)
def test_a_file_that_is_no_version_1_record_reads_as_none(tmp_path: Path, content: str) -> None:
    (tmp_path / "twins").mkdir()
    (tmp_path / "twins" / "demo.json").write_text(content)
    assert record.read(tmp_path, "demo") is None
    assert record.listed(tmp_path) == ()


def test_a_missing_record_reads_as_none(tmp_path: Path) -> None:
    assert record.read(tmp_path, "demo") is None
    assert record.listed(tmp_path) == ()


def test_a_twin_name_that_is_no_twin_name_is_refused_before_any_path_is_made(tmp_path: Path) -> None:
    root = tmp_path / "records"
    for name in ("../x", "Demo", "a" * 41, "-x", ""):
        with pytest.raises(ValueError, match=re.escape(repr(name))):
            record.write(root, dataclasses.replace(DEMO, twin=name))
    assert list(tmp_path.iterdir()) == []
    # Nor is one read: the file outside the records' directory that the name would lead to is never opened.
    (root / "twins").mkdir(parents=True)
    (root / "x.json").write_text(json.dumps({"record_version": "1", **dataclasses.asdict(DEMO), "twin": "../x"}))
    assert record.read(root, "../x") is None


def test_every_record_is_listed_by_its_twin_and_nothing_else(tmp_path: Path) -> None:
    root, other = tmp_path / "records", dataclasses.replace(DEMO, twin="a-twin", change_id="pc-2")
    record.write(root, DEMO)
    record.write(root, other)
    (root / "twins" / "broken.json").write_text("{}")
    (root / "twins" / "Not-A-Twin.json").write_text(json.dumps({"record_version": "1", **dataclasses.asdict(DEMO)}))
    (root / "twins" / "notes.txt").write_text("")
    assert record.listed(root) == (other, DEMO)


def test_a_record_is_trusted_only_for_the_twins_own_blueprint_id() -> None:
    assert record.trusted(DEMO, {"name": "demo", "status": {"blueprint_id": DEMO.blueprint_id}})
    assert not record.trusted(DEMO, {"name": "demo", "status": {"blueprint_id": "b" * 64}})
    assert not record.trusted(DEMO, {"name": "demo", "status": {}})
