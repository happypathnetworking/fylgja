"""The local store (Constitution IX, D-024, D-041): the store contract run over a directory, and
what is the directory's alone: its layout, its whole-or-nothing writes, its lock and its events file."""

from __future__ import annotations

import dataclasses
import errno
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from store_contract import DEPLOYMENT, ROOT, StoreContract, record, run_

from fylgja_core import bundle, documents
from fylgja_core.local_store import LocalStore
from fylgja_core.run import Event
from fylgja_core.store import Conflict, Store


@pytest.fixture(autouse=True)
def _close_stores(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Close every store a test opens, so no file or lock outlives it."""
    opened: list[LocalStore] = []
    real = LocalStore.open.__func__  # type: ignore[attr-defined]

    def tracking(cls: type[LocalStore], root: Path) -> LocalStore:
        s: LocalStore = real(cls, root)
        opened.append(s)
        return s

    monkeypatch.setattr(LocalStore, "open", classmethod(tracking))
    yield
    for s in opened:
        s.close()


class TestLocalStore(StoreContract):
    @pytest.fixture
    def store(self, tmp_path: Path) -> Iterator[Store]:
        s = LocalStore.open(tmp_path)
        yield s
        s.close()


def test_open_creates_the_d041_layout(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path / "store")
    assert {p.name for p in (tmp_path / "store").iterdir()} >= {"blueprints", "bundles", "deployments", "twins", "runs"}
    s.close()


def test_the_files_are_d041s(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    doc = json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
    bid, _ = s.put_blueprint(doc)
    files = {"manifest.json": b"{}", "configs/n1.cfg": b"set / system\n"}
    s.put_bundle(bundle.bundle_id(files), files)
    s.put_deployment(DEPLOYMENT, {"topology.clab.yml": b"name: t\n"})
    s.create_twin(record("a"))
    s.create_run(run_())
    s.append_event(run_().id, Event(seq=99, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started"))
    s.append_event(
        run_().id,
        Event(seq=99, at="2026-11-03T10:00:01.000000Z", phase="compile", outcome="done", duration_s=1.0),
    )
    assert s.put_blueprint(doc) == (bid, False)  # each refused duplicate drops the temporary file it wrote
    with pytest.raises(Conflict):
        s.create_twin(record("a"))
    with pytest.raises(Conflict):
        s.create_run(run_())
    escaping = {"manifest.json": b"{}", "../../twins/evil.json": b"x"}
    with pytest.raises(ValueError):
        s.put_bundle(bundle.bundle_id(escaping), escaping)
    with pytest.raises(ValueError):
        s.put_deployment(dataclasses.replace(DEPLOYMENT, id="e" * 64), {"deployment.json": b"{}"})
    assert (tmp_path / "blueprints" / f"{bid}.json").exists()
    assert (tmp_path / "bundles" / bundle.bundle_id(files) / "configs" / "n1.cfg").read_bytes() == b"set / system\n"
    deployed = tmp_path / "deployments" / DEPLOYMENT.id / "deployment.json"
    assert json.loads(deployed.read_text()) == documents.encode(DEPLOYMENT)
    assert (tmp_path / "twins" / "a.json").exists()
    lines = (tmp_path / "runs" / f"{run_().id}.events.ndjson").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["seq"] == 1
    # The refused writes left nothing, and no write left a temporary file behind.
    assert [p.name for p in (tmp_path / "bundles").iterdir()] == [bundle.bundle_id(files)]
    assert not list(tmp_path.rglob("evil*")) and not (tmp_path / "deployments" / ("e" * 64)).exists()
    assert not list(tmp_path.rglob(".tmp*"))


def test_a_filed_document_is_never_overwritten(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    doc = json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
    bid, _ = s.put_blueprint(doc)
    path = tmp_path / "blueprints" / f"{bid}.json"
    path.write_text("sentinel")
    assert s.put_blueprint(doc) == (bid, False) and path.read_text() == "sentinel"


def test_a_write_is_the_whole_file_or_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The rename is the commit: a failure before it leaves the old record and no temp file.
    s = LocalStore.open(tmp_path)
    s.create_twin(record())

    def gone(*args: object, **kwargs: object) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", gone)
    with pytest.raises(OSError):
        s.update_twin(record(generation=2), expected_revision=1)
    monkeypatch.undo()
    assert s.get_twin("t").generation == 1 and not list((tmp_path / "twins").glob(".tmp*"))


def test_a_second_core_is_refused_naming_the_holder(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    code = (
        "import sys; from fylgja_core.local_store import LocalStore; from fylgja_core import store\n"
        "try:\n    LocalStore.open(sys.argv[1])\nexcept store.Locked as e:\n    print(e); sys.exit(3)\nsys.exit(0)"
    )
    done = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True)
    assert done.returncode == 3 and str(os.getpid()) in done.stdout
    s.close()
    assert subprocess.run([sys.executable, "-c", code, str(tmp_path)]).returncode == 0


def test_a_trailing_partial_line_is_skipped_and_the_sequence_continues(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    s.create_run(run_())
    s.append_event(run_().id, Event(seq=0, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started"))
    path = tmp_path / "runs" / f"{run_().id}.events.ndjson"
    with path.open("a") as f:
        f.write('{"seq": 2, "at": "2026-11-03T10:00:01.0')  # a core killed mid-append
    assert [e.seq for e in s.events(run_().id)] == [1]
    e = s.append_event(run_().id, Event(seq=0, at="2026-11-03T10:00:02.000000Z", phase="compile", outcome="done"))
    assert e.seq == 2 and [x.seq for x in s.events(run_().id)] == [1, 2]


def test_a_bundle_whose_paths_collide_raises_and_leaves_nothing(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    with pytest.raises(OSError):
        collide = {"manifest.json": b"{}", "configs": b"x", "configs/n1.cfg": b"y"}
        s.put_bundle(bundle.bundle_id(collide), collide)
    assert list((tmp_path / "bundles").iterdir()) == []


def test_a_bundle_that_appears_during_the_build_is_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LocalStore.open(tmp_path)
    mine = {"manifest.json": b"mine"}
    final = tmp_path / "bundles" / bundle.bundle_id(mine)
    real = os.rename

    def racing(src: object, dst: object) -> None:
        final.mkdir()
        (final / "manifest.json").write_bytes(b"theirs")
        real(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "rename", racing)
    assert s.put_bundle(bundle.bundle_id(mine), mine) is False
    monkeypatch.undo()
    assert (final / "manifest.json").read_bytes() == b"theirs" and not list((tmp_path / "bundles").glob(".tmp*"))


def test_a_rename_failure_other_than_present_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LocalStore.open(tmp_path)

    def broken(src: object, dst: object) -> None:
        raise OSError(errno.EIO, "io")

    monkeypatch.setattr(os, "rename", broken)
    with pytest.raises(OSError):
        s.put_bundle(bundle.bundle_id({"manifest.json": b"{}"}), {"manifest.json": b"{}"})
    monkeypatch.undo()
    assert not list((tmp_path / "bundles").glob(".tmp*"))


def test_a_failed_temp_write_leaves_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LocalStore.open(tmp_path)

    def full(fd: int) -> None:
        raise OSError(errno.ENOSPC, "full")

    monkeypatch.setattr(os, "fsync", full)
    with pytest.raises(OSError):
        s.create_twin(record())
    monkeypatch.undo()
    assert not list((tmp_path / "twins").glob(".tmp*"))


def test_open_sweeps_what_a_killed_core_left(tmp_path: Path) -> None:
    LocalStore.open(tmp_path).close()
    (tmp_path / "twins" / ".tmp-dead").write_bytes(b"half")
    (tmp_path / "bundles" / ".tmp-dir" / "configs").mkdir(parents=True)
    (tmp_path / "bundles" / ".tmp-dir" / "configs" / "n.cfg").write_bytes(b"x")
    LocalStore.open(tmp_path)
    assert not list(tmp_path.rglob(".tmp-*"))


def test_a_long_events_file_continues_its_sequence_from_the_tail(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    s.create_run(run_())
    event = Event(seq=0, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started", node="n" * 500)
    for _ in range(300):  # well over 64 KiB
        s.append_event(run_().id, event)
    assert (tmp_path / "runs" / f"{run_().id}.events.ndjson").stat().st_size > 64 * 1024
    assert s.append_event(run_().id, event).seq == 301


def test_a_last_line_longer_than_the_tail_window_still_gives_the_next_seq(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    s.create_run(run_())
    long = Event(seq=0, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="failed", rule="r" * 100_000)
    assert s.append_event(run_().id, long).seq == 1
    assert s.append_event(run_().id, long).seq == 2  # the only whole line in the window is the last one
    assert s.append_event(run_().id, long).seq == 3
    assert [e.seq for e in s.events(run_().id)] == [1, 2, 3]


def test_a_fragment_longer_than_the_tail_window_is_cut_cleanly(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    s.create_run(run_())
    first = Event(seq=0, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started")
    s.append_event(run_().id, first)
    path = tmp_path / "runs" / f"{run_().id}.events.ndjson"
    with path.open("a") as f:
        f.write('{"seq": 2, "rule": "' + "x" * 150_000)  # killed mid-append, longer than the window
    assert s.append_event(run_().id, first).seq == 2
    lines = path.read_text().splitlines()
    assert len(lines) == 2 and [json.loads(line)["seq"] for line in lines] == [1, 2]


def test_a_committed_file_named_like_a_temp_survives_open(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    files = {"manifest.json": b"{}", ".tmp-keep": b"x"}
    bid = bundle.bundle_id(files)
    s.put_bundle(bid, files)
    s.close()
    LocalStore.open(tmp_path)
    assert (tmp_path / "bundles" / bid / ".tmp-keep").exists()
