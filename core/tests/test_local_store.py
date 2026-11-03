"""The local store (Constitution IX, D-024, D-041): documents by id, twin records by
compare-and-set, runs and their events, in a directory."""

from __future__ import annotations

import asyncio
import dataclasses
import errno
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from fylgja_core import blueprint, deployment, documents, store
from fylgja_core.local_store import LocalStore
from fylgja_core.run import Event, Run
from fylgja_core.twin_record import Spec, Status, TwinRecord

ROOT = Path(__file__).resolve().parents[2]


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


def test_open_creates_the_d041_layout(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path / "store")
    assert {p.name for p in (tmp_path / "store").iterdir()} >= {"blueprints", "bundles", "deployments", "twins", "runs"}
    s.close()


def test_a_blueprint_is_filed_by_its_id_once_and_read_back_whole(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    doc = json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
    bid, created = s.put_blueprint(doc)
    assert created and bid == blueprint.blueprint_id(doc)
    assert (tmp_path / "blueprints" / f"{bid}.json").exists()
    assert s.put_blueprint(doc) == (bid, False)
    assert s.get_blueprint(bid) == doc  # the source envelope included
    with pytest.raises(store.NotFound):
        s.get_blueprint("f" * 64)
    assert not list(tmp_path.glob("blueprints/.tmp*"))  # no temp file left behind


def test_a_filed_document_is_never_overwritten(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    doc = json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
    bid, _ = s.put_blueprint(doc)
    path = tmp_path / "blueprints" / f"{bid}.json"
    path.write_text("sentinel")
    assert s.put_blueprint(doc) == (bid, False) and path.read_text() == "sentinel"


def test_a_bundle_is_its_files_under_its_id(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    files = {"manifest.json": b"{}", "configs/n1.cfg": b"set / system\n"}
    assert s.put_bundle("a" * 64, files) is True
    assert s.put_bundle("a" * 64, {"manifest.json": b"other"}) is False
    assert s.get_bundle("a" * 64) == files
    assert (tmp_path / "bundles" / ("a" * 64) / "configs" / "n1.cfg").read_bytes() == b"set / system\n"
    assert not list((tmp_path / "bundles").glob(".tmp*"))
    with pytest.raises(store.NotFound):
        s.get_bundle("b" * 64)


def test_a_deployment_is_its_document_and_its_rendered_files(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    d = deployment.Deployment(
        id="c" * 64,
        driver="containerlab",
        twin="t",
        allocation={"lab": "t"},
        bundle_id="a" * 64,
        files=(deployment.File(path="topology.clab.yml", sha256="d" * 64),),
        demand=deployment.Demand(nodes=1, cpu=0.5, memory_mb=2048),
        fidelity=deployment.Fidelity(
            forwarding="software",
            approximations=(),
            omitted=(),
            synthesized=(),
            lossy=deployment.Lossy(mappings=0, shared_ports=0),
        ),
    )
    assert s.put_deployment(d, {"topology.clab.yml": b"name: t\n"}) is True
    got, files = s.get_deployment("c" * 64)
    assert got == d and files == {"topology.clab.yml": b"name: t\n"}
    assert json.loads((tmp_path / "deployments" / ("c" * 64) / "deployment.json").read_text()) == documents.encode(d)
    with pytest.raises(store.NotFound):
        s.get_deployment("e" * 64)


def record(name: str = "t", revision: int = 1, generation: int = 1) -> TwinRecord:
    return TwinRecord(
        name=name,
        revision=revision,
        generation=generation,
        spec=Spec(blueprint_id="a" * 64, driver="containerlab", allow_restart=False),
        status=Status(observed_generation=0, conditions=(), nodes=()),
    )


def test_a_twin_is_created_once_at_revision_1_and_listed_by_name(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    assert s.create_twin(record("b")).revision == 1
    s.create_twin(record("a"))
    with pytest.raises(store.Conflict):
        s.create_twin(record("a"))
    with pytest.raises(ValueError):
        s.create_twin(record("c", revision=2))
    assert [t.name for t in s.list_twins()] == ["a", "b"]
    assert (tmp_path / "twins" / "a.json").exists()


def test_compare_and_set_takes_the_revision_read_and_refuses_a_stale_one(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    s.create_twin(record())
    written = s.update_twin(record(generation=2), expected_revision=1)
    assert written.revision == 2 and s.get_twin("t").generation == 2
    with pytest.raises(store.Conflict):
        s.update_twin(record(generation=3), expected_revision=1)
    with pytest.raises(store.NotFound):
        s.update_twin(record("missing"), expected_revision=1)
    with pytest.raises(store.Conflict):
        s.delete_twin("t", expected_revision=1)
    s.delete_twin("t", expected_revision=2)
    with pytest.raises(store.NotFound):
        s.get_twin("t")
    with pytest.raises(store.NotFound):
        s.delete_twin("t", expected_revision=2)


def test_two_writers_racing_on_one_record_get_exactly_one_success(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    s.create_twin(record())
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def writer(generation: int) -> None:
        barrier.wait()
        try:
            s.update_twin(record(generation=generation), expected_revision=1)
            outcomes.append("ok")
        except store.Conflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=writer, args=(g,)) for g in (2, 3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["conflict", "ok"] and s.get_twin("t").revision == 2


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


def test_subscribers_see_every_change_in_write_order(tmp_path: Path) -> None:
    async def scenario() -> list[tuple[str, int]]:
        s = LocalStore.open(tmp_path)
        sub = s.subscribe()
        s.create_twin(record())
        s.update_twin(record(generation=2), expected_revision=1)
        s.delete_twin("t", expected_revision=2)
        sub.close()
        s.create_twin(record("u"))  # after close: not delivered
        await asyncio.sleep(0)  # deliveries are scheduled on the loop
        seen: list[tuple[str, int]] = []
        while not sub.queue.empty():
            c = sub.queue.get_nowait()
            seen.append((c.type, c.record.revision))
        return seen

    assert asyncio.run(scenario()) == [("ADDED", 1), ("MODIFIED", 2), ("DELETED", 2)]


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


def run_(id_: str = "01ARZ3NDEKTSV4RRFFQ69G5FAV", twin: str = "t") -> Run:
    return Run(
        id=id_, twin=twin, operation="create", state="queued", principal="p", created_at="2026-11-03T10:00:00.000000Z"
    )


def test_runs_are_kept_by_id_and_listed_newest_first(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    s.create_run(run_("01ARZ3NDEKTSV4RRFFQ69G5FAV", "a"))
    s.create_run(run_("01BRZ3NDEKTSV4RRFFQ69G5FAV", "b"))
    with pytest.raises(store.Conflict):
        s.create_run(run_("01ARZ3NDEKTSV4RRFFQ69G5FAV"))
    assert [r.id[:3] for r in s.list_runs()] == ["01B", "01A"]
    assert [r.twin for r in s.list_runs(twin="a")] == ["a"]
    s.update_run(dataclasses.replace(s.get_run("01ARZ3NDEKTSV4RRFFQ69G5FAV"), state="running"))
    assert s.get_run("01ARZ3NDEKTSV4RRFFQ69G5FAV").state == "running"
    with pytest.raises(store.NotFound):
        s.get_run("01CRZ3NDEKTSV4RRFFQ69G5FAV")
    with pytest.raises(store.NotFound):
        s.update_run(run_("01CRZ3NDEKTSV4RRFFQ69G5FAV"))


def test_events_are_appended_one_line_each_with_the_stores_sequence(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    s.create_run(run_())
    e1 = s.append_event(run_().id, Event(seq=99, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started"))
    e2 = s.append_event(
        run_().id,
        Event(seq=99, at="2026-11-03T10:00:01.000000Z", phase="compile", outcome="done", duration_s=1.0),
    )
    assert (e1.seq, e2.seq) == (1, 2)
    lines = (tmp_path / "runs" / f"{run_().id}.events.ndjson").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["seq"] == 1
    assert [e.seq for e in s.events(run_().id)] == [1, 2] and s.events(run_().id, after=1) == [e2]
    with pytest.raises(store.NotFound):
        s.append_event("01CRZ3NDEKTSV4RRFFQ69G5FAV", e1)


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


def test_a_write_from_a_worker_thread_reaches_a_waiting_watcher(tmp_path: Path) -> None:
    async def scenario() -> tuple[str, int]:
        s = LocalStore.open(tmp_path)
        s.create_twin(record())
        sub = s.subscribe()
        waiter = asyncio.create_task(sub.queue.get())
        await asyncio.sleep(0)  # the task is now parked on the empty queue
        await asyncio.to_thread(s.update_twin, record(generation=2), 1)
        change = await asyncio.wait_for(waiter, timeout=5)
        sub.close()
        return change.type, change.record.revision

    assert asyncio.run(scenario()) == ("MODIFIED", 2)


def test_a_bundle_whose_paths_collide_raises_and_leaves_nothing(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    with pytest.raises(OSError):
        s.put_bundle("a" * 64, {"configs": b"x", "configs/n1.cfg": b"y"})
    assert list((tmp_path / "bundles").iterdir()) == []


def test_a_bundle_that_appears_during_the_build_is_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LocalStore.open(tmp_path)
    final = tmp_path / "bundles" / ("a" * 64)
    real = os.rename

    def racing(src: object, dst: object) -> None:
        final.mkdir()
        (final / "manifest.json").write_bytes(b"theirs")
        real(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "rename", racing)
    assert s.put_bundle("a" * 64, {"manifest.json": b"mine"}) is False
    monkeypatch.undo()
    assert (final / "manifest.json").read_bytes() == b"theirs" and not list((tmp_path / "bundles").glob(".tmp*"))


def test_a_rename_failure_other_than_present_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LocalStore.open(tmp_path)

    def broken(src: object, dst: object) -> None:
        raise OSError(errno.EIO, "io")

    monkeypatch.setattr(os, "rename", broken)
    with pytest.raises(OSError):
        s.put_bundle("a" * 64, {"manifest.json": b"{}"})
    monkeypatch.undo()
    assert not list((tmp_path / "bundles").glob(".tmp*"))


def test_a_rendered_file_cannot_be_named_for_the_deployment_document(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    d = deployment.Deployment(
        id="c" * 64,
        driver="containerlab",
        twin="t",
        allocation={},
        bundle_id="a" * 64,
        files=(),
        demand=deployment.Demand(nodes=1, cpu=0.5, memory_mb=2048),
        fidelity=deployment.Fidelity(
            forwarding="software",
            approximations=(),
            omitted=(),
            synthesized=(),
            lossy=deployment.Lossy(mappings=0, shared_ports=0),
        ),
    )
    with pytest.raises(ValueError):
        s.put_deployment(d, {"deployment.json": b"{}"})
    assert not (tmp_path / "deployments" / ("c" * 64)).exists()


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
