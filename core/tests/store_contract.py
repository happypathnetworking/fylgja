"""The store interface's guarantees (Constitution IX, D-024), as one contract every store runs.

A store's tests subclass `StoreContract` and give it the fixture `store`: an open, empty store,
closed after the test (a test may have closed it already). Each case speaks through the
interface alone, so what one store passes the other must.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
from pathlib import Path

import pytest

from fylgja_core import blueprint, bundle, deployment
from fylgja_core.run import Event, Run
from fylgja_core.store import Conflict, NotFound, Store, StoreError, Subscription
from fylgja_core.twin_record import Spec, Status, TwinRecord

ROOT = Path(__file__).resolve().parents[2]

DEPLOYMENT = deployment.Deployment(
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


def record(name: str = "t", revision: int = 1, generation: int = 1) -> TwinRecord:
    return TwinRecord(
        name=name,
        revision=revision,
        generation=generation,
        spec=Spec(blueprint_id="a" * 64, driver="containerlab", allow_restart=False),
        status=Status(observed_generation=0, conditions=(), nodes=()),
    )


def run_(id_: str = "01ARZ3NDEKTSV4RRFFQ69G5FAV", twin: str = "t") -> Run:
    return Run(
        id=id_, twin=twin, operation="create", state="queued", principal="p", created_at="2026-11-03T10:00:00.000000Z"
    )


class StoreContract:
    """Every store's cases; a subclass named `Test...` provides `store` and runs them."""

    def test_a_blueprint_is_filed_once_and_read_back_whole(self, store: Store) -> None:
        doc = json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
        bid, created = store.put_blueprint(doc)
        assert created and bid == blueprint.blueprint_id(doc)
        assert store.put_blueprint(doc) == (bid, False)
        assert store.get_blueprint(bid) == doc  # the source envelope included
        with pytest.raises(NotFound):
            store.get_blueprint("f" * 64)

    def test_a_bundle_is_its_files_under_its_id(self, store: Store) -> None:
        files = {"manifest.json": b"{}", "configs/n1.cfg": b"set / system\n"}
        bid = bundle.bundle_id(files)
        assert store.put_bundle(bid, files) is True
        assert store.put_bundle(bid, files) is False
        assert store.get_bundle(bid) == files
        with pytest.raises(NotFound):
            store.get_bundle("b" * 64)

    def test_a_file_path_that_needs_encoding_is_read_back_the_same(self, store: Store) -> None:
        files = {"manifest.json": b"{}", "configs/a b+c=é~x.cfg": b"x"}
        bid = bundle.bundle_id(files)
        assert store.put_bundle(bid, files) is True
        assert store.get_bundle(bid) == files

    def test_a_deployment_is_its_document_and_its_rendered_files(self, store: Store) -> None:
        assert store.put_deployment(DEPLOYMENT, {"topology.clab.yml": b"name: t\n"}) is True
        assert store.put_deployment(DEPLOYMENT, {"topology.clab.yml": b"name: t\n"}) is False
        got, files = store.get_deployment(DEPLOYMENT.id)
        assert got == DEPLOYMENT and files == {"topology.clab.yml": b"name: t\n"}
        with pytest.raises(NotFound):
            store.get_deployment("e" * 64)

    def test_a_rendered_file_cannot_be_named_for_the_deployment_document(self, store: Store) -> None:
        with pytest.raises(ValueError):
            store.put_deployment(DEPLOYMENT, {"deployment.json": b"{}"})
        with pytest.raises(NotFound):
            store.get_deployment(DEPLOYMENT.id)

    def test_a_bundle_needs_its_own_id_and_a_manifest(self, store: Store) -> None:
        with pytest.raises(ValueError):
            store.put_bundle("a" * 64, {"manifest.json": b"{}"})
        with pytest.raises(ValueError):
            store.put_bundle(bundle.bundle_id({"configs/n.cfg": b"x"}), {"configs/n.cfg": b"x"})

    def test_a_twin_is_created_once_at_revision_1_and_listed_by_name(self, store: Store) -> None:
        assert store.create_twin(record("a0")).revision == 1
        store.create_twin(record("a-b"))
        store.create_twin(record("a"))
        with pytest.raises(Conflict):
            store.create_twin(record("a"))
        with pytest.raises(ValueError):
            store.create_twin(record("c", revision=2))
        assert [t.name for t in store.list_twins()] == ["a", "a-b", "a0"]  # by name: their keys sort a-b, a, a0

    def test_compare_and_set_takes_the_revision_read_and_refuses_a_stale_one(self, store: Store) -> None:
        store.create_twin(record())
        written = store.update_twin(record(generation=2), expected_revision=1)
        assert written.revision == 2 and store.get_twin("t").generation == 2
        with pytest.raises(Conflict):
            store.update_twin(record(generation=3), expected_revision=1)
        with pytest.raises(NotFound):
            store.update_twin(record("missing"), expected_revision=1)
        with pytest.raises(Conflict):
            store.delete_twin("t", expected_revision=1)
        store.delete_twin("t", expected_revision=2)
        with pytest.raises(NotFound):
            store.get_twin("t")
        with pytest.raises(NotFound):
            store.delete_twin("t", expected_revision=2)

    def test_two_writers_racing_on_one_record_get_exactly_one_success(self, store: Store) -> None:
        store.create_twin(record())
        outcomes: list[str] = []
        barrier = threading.Barrier(2)

        def writer(generation: int) -> None:
            barrier.wait()
            try:
                store.update_twin(record(generation=generation), expected_revision=1)
                outcomes.append("ok")
            except Conflict:
                outcomes.append("conflict")

        threads = [threading.Thread(target=writer, args=(g,)) for g in (2, 3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(outcomes) == ["conflict", "ok"] and store.get_twin("t").revision == 2

    def test_subscribers_see_every_change_in_write_order(self, store: Store) -> None:
        async def scenario() -> list[tuple[str, int]]:
            sub = store.subscribe()
            store.create_twin(record())
            store.update_twin(record(generation=2), expected_revision=1)
            store.delete_twin("t", expected_revision=2)
            sub.close()
            store.create_twin(record("u"))  # after close: not delivered
            await asyncio.sleep(0)  # deliveries are scheduled on the loop
            seen: list[tuple[str, int]] = []
            while not sub.queue.empty():
                c = sub.queue.get_nowait()
                seen.append((c.type, c.record.revision))
            return seen

        assert asyncio.run(scenario()) == [("ADDED", 1), ("MODIFIED", 2), ("DELETED", 2)]

    def test_a_write_from_a_worker_thread_reaches_a_waiting_watcher(self, store: Store) -> None:
        async def scenario() -> tuple[str, int]:
            store.create_twin(record())
            sub = store.subscribe()
            waiter = asyncio.create_task(sub.queue.get())
            await asyncio.sleep(0)  # the task is now parked on the empty queue
            await asyncio.to_thread(store.update_twin, record(generation=2), 1)
            change = await asyncio.wait_for(waiter, timeout=5)
            sub.close()
            return change.type, change.record.revision

        assert asyncio.run(scenario()) == ("MODIFIED", 2)

    def test_a_subscription_whose_loop_closed_does_not_fail_a_write(self, store: Store) -> None:
        async def subscribe() -> Subscription:
            return store.subscribe()

        sub = asyncio.run(subscribe())  # its loop is closed on return
        assert store.create_twin(record()).revision == 1
        assert store.update_twin(record(generation=2), expected_revision=1).revision == 2
        assert sub.queue.empty()

    def test_a_subscription_is_a_context_manager(self, store: Store) -> None:
        async def scenario() -> tuple[int, int]:
            with store.subscribe() as sub:
                store.create_twin(record())
                await asyncio.sleep(0)
                inside = sub.queue.qsize()
            store.update_twin(record(generation=2), expected_revision=1)  # after the block: not delivered
            await asyncio.sleep(0)
            return inside, sub.queue.qsize()

        assert asyncio.run(scenario()) == (1, 1)

    def test_runs_are_kept_by_id_and_listed_newest_first(self, store: Store) -> None:
        store.create_run(run_("01ARZ3NDEKTSV4RRFFQ69G5FAV", "a"))
        store.create_run(run_("01BRZ3NDEKTSV4RRFFQ69G5FAV", "b"))
        with pytest.raises(Conflict):
            store.create_run(run_("01ARZ3NDEKTSV4RRFFQ69G5FAV"))
        assert [r.id[:3] for r in store.list_runs()] == ["01B", "01A"]
        assert [r.twin for r in store.list_runs(twin="a")] == ["a"]
        store.create_run(run_("01DRZ3NDEKTSV4RRFFQ69G5FAV", "a"))
        assert [r.id[:3] for r in store.list_runs(twin="a")] == ["01D", "01A"] and store.list_runs(twin="zz") == []
        running = dataclasses.replace(store.get_run("01ARZ3NDEKTSV4RRFFQ69G5FAV"), state="running")
        store.update_run(running, expected_state="queued")
        with pytest.raises(Conflict):  # the stored run is no longer queued
            ended = dataclasses.replace(store.get_run("01ARZ3NDEKTSV4RRFFQ69G5FAV"), state="ended")
            store.update_run(ended, expected_state="queued")
        assert store.get_run("01ARZ3NDEKTSV4RRFFQ69G5FAV").state == "running"
        with pytest.raises(NotFound):
            store.get_run("01CRZ3NDEKTSV4RRFFQ69G5FAV")
        with pytest.raises(NotFound):
            store.update_run(run_("01CRZ3NDEKTSV4RRFFQ69G5FAV"), expected_state="queued")

    def test_events_get_the_stores_sequence_and_are_read_after_a_cursor(self, store: Store) -> None:
        store.create_run(run_())
        e1 = store.append_event(
            run_().id,
            Event(seq=99, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started"),
        )
        e2 = store.append_event(
            run_().id,
            Event(seq=99, at="2026-11-03T10:00:01.000000Z", phase="compile", outcome="done", duration_s=1.0),
        )
        assert (e1.seq, e2.seq) == (1, 2)
        assert [e.seq for e in store.events(run_().id)] == [1, 2] and store.events(run_().id, after=1) == [e2]
        assert store.events(run_().id, after=2) == []
        with pytest.raises(NotFound):
            store.append_event("01CRZ3NDEKTSV4RRFFQ69G5FAV", e1)
        with pytest.raises(NotFound):
            store.events("01CRZ3NDEKTSV4RRFFQ69G5FAV")

    def test_many_events_keep_their_order(self, store: Store) -> None:
        store.create_run(run_())
        event = Event(seq=0, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started", node="n" * 500)
        for _ in range(300):
            store.append_event(run_().id, event)
        assert store.append_event(run_().id, event).seq == 301
        assert [e.seq for e in store.events(run_().id, after=299)] == [300, 301]

    @pytest.mark.parametrize("bad", ["..", "", "A" * 64, "a" * 63, "../" + "a" * 61])
    def test_ids_are_64_lowercase_hex(self, store: Store, bad: str) -> None:
        for call in (store.get_blueprint, store.get_bundle, store.get_deployment):
            with pytest.raises(ValueError):
                call(bad)

    @pytest.mark.parametrize("bad", ["..", "", "T", "A_b", "-a", "a-", "a" * 41, "../x"])
    def test_twin_names_are_checked(self, store: Store, bad: str) -> None:
        with pytest.raises(ValueError):
            store.get_twin(bad)
        with pytest.raises(ValueError):
            store.create_twin(record(bad))

    @pytest.mark.parametrize("bad", ["..", "x", "01ARZ3NDEKTSV4RRFFQ69G5FAI", "01arz3ndektsv4rrffq69g5fav", "../x"])
    def test_run_ids_are_ulids(self, store: Store, bad: str) -> None:
        with pytest.raises(ValueError):
            store.get_run(bad)
        with pytest.raises(ValueError):
            store.events(bad)
        with pytest.raises(ValueError):
            store.append_event(bad, Event(seq=0, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started"))

    @pytest.mark.parametrize(
        "bad",
        ["../../twins/evil.json", "/abs", "a//b", "a/./b", "a/..", "", "a\\b", "a\nb", "a\x7fb",
         "a\ufffeb", "a\uffffb"],
    )
    def test_file_keys_are_relative_paths(self, store: Store, bad: str) -> None:
        files = {"manifest.json": b"{}", bad: b"x"}
        with pytest.raises(ValueError):
            store.put_bundle(bundle.bundle_id(files), files)
        with pytest.raises(NotFound):
            store.get_bundle(bundle.bundle_id(files))
        assert store.list_twins() == []  # nothing escaped the bundle

    def test_operations_after_close_raise(self, store: Store) -> None:
        store.close()
        with pytest.raises(StoreError, match="closed"):
            store.list_twins()
        with pytest.raises(StoreError, match="closed"):
            store.get_run("01ARZ3NDEKTSV4RRFFQ69G5FAV")
