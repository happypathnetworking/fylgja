"""The orchestrator's record and store (`record.py`, T024; data-model §8, R-09): US6's
scenarios 1, 2, 4 and 5 over a temporary root, with `twin.show`'s answers and the
platform's flow runs stubbed."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from fylgja_orchestrator import record
from fylgja_orchestrator.adapters.infrahub import snapshot
from fylgja_orchestrator.core import CoreFailure
from fylgja_orchestrator.documents import findings
from fylgja_orchestrator.documents.findings import Document, Findings
from fylgja_orchestrator.record import ChangeRef, Record, RecordError, StageRef, Store

DATA = Path(__file__).resolve().parents[1] / "data"
FLOW_RUN = "5f0c1d2e-3b4a-4c5d-8e6f-7a8b9c0d1e2f"
CHANGE = ChangeRef("18e2ec03-0000-0000-0000-00000000c0de", "change-a")


def a_snapshot(name: str = "three-node") -> dict:
    return snapshot.read(DATA / "snapshot" / f"{name}.json")


def show(snapshot_id: str | None) -> Document:
    """twin.show's document: a twin whose record names snapshot_id, or none at all."""
    blocks = {"show": {"host": {}, "kind": "none"}}
    if snapshot_id is not None:
        blocks["show"]["record"] = {"branch": "change-a", "snapshot_id": snapshot_id}
    return Document(findings.OP_TWIN_SHOW, "ok", None, Findings(), blocks)


def created(store: Store, flow: str = record.FLOW_CREATE, label: str = "a") -> Record:
    """A twin the orchestrator created from stage change-a/<label>: the snapshot filed, the
    record written."""
    snap = a_snapshot()
    store.put(snap)
    rec = record.new_record(StageRef("change-a", label, "2026-10-29T10:00:00.000000Z"), CHANGE, snap["snapshot_id"],
                            FLOW_RUN, flow, now=datetime(2026, 10, 30, 1, 2, 3, 456789, tzinfo=UTC))
    store.write_record(rec)
    return rec


def test_the_root_from_the_environment(tmp_path):
    assert record.root({}) == Path("local/orchestrator")
    assert record.root({record.ENV_ROOT: str(tmp_path)}) == tmp_path
    assert Store.from_env({record.ENV_ROOT: str(tmp_path)}).snapshots == tmp_path / "snapshots"


# US6 scenario 1: the record of a twin created from a stage, trusted beside twin show.


def test_the_record_written_by_a_create_is_read_and_trusted(tmp_path):
    store = Store(tmp_path)
    rec = created(store)
    on_disk = json.loads(store.record_path.read_text())
    assert on_disk == {
        "record_version": "1",
        "stage": {"branch": "change-a", "label": "a", "at": "2026-10-29T10:00:00.000000Z"},
        "proposed_change": {"id": CHANGE.id, "branch": "change-a"},
        "snapshot_id": rec.snapshot_id,
        "flow_run_id": FLOW_RUN,
        "flow": "twin-create",
        "written_at": "2026-10-30T01:02:03.456789Z",
    }
    assert list(on_disk) == ["record_version", "stage", "proposed_change", "snapshot_id", "flow_run_id", "flow",
                             "written_at"]
    got = store.read_record()
    assert got == rec and got.ref == "change-a/a"
    assert record.trusted(got, show(rec.snapshot_id))
    assert record.trusted(got, show(rec.snapshot_id).blocks["show"])
    assert record.stale(store, got, show(rec.snapshot_id)) is None
    assert record.target_required(got, show(rec.snapshot_id)) is None


def test_a_step_writes_the_record_whole(tmp_path):
    """The step's record replaces the create's, whole; no temporary file is left."""
    store = Store(tmp_path)
    created(store)
    probed = a_snapshot("three-node-probed")
    store.put(probed)
    step = record.new_record(StageRef("change-a", "b", "2026-10-29T11:00:00.000000Z"), CHANGE,
                             probed["snapshot_id"], "6a1b2c3d-0000-4000-8000-000000000001", record.FLOW_STEP)
    store.write_record(step)
    assert store.read_record() == step
    assert sorted(p.name for p in tmp_path.iterdir()) == ["snapshots", "twin.json"]
    assert step.written_at.endswith("Z") and len(step.written_at) == len("2026-10-30T01:02:03.456789Z")


def test_no_record_is_none_and_a_foreign_one_refused(tmp_path):
    store = Store(tmp_path)
    assert store.read_record() is None
    tmp_path.joinpath("twin.json").write_text('{"twin_version": "12"}')
    with pytest.raises(RecordError, match="declares record_version None; this build reads '1'"):
        store.read_record()
    tmp_path.joinpath("twin.json").write_text("{")
    with pytest.raises(RecordError, match="is not a record"):
        store.read_record()


def test_a_record_is_held_to_its_shape():
    with pytest.raises(ValueError, match="writes no record"):
        record.new_record(StageRef("b", "a", "t"), CHANGE, "0" * 64, FLOW_RUN, "stage-plan")
    with pytest.raises(ValueError, match="is not a snapshot id"):
        record.new_record(StageRef("b", "a", "t"), CHANGE, "0940db93", FLOW_RUN, record.FLOW_CREATE)


# US6 scenario 2: the twin stepped elsewhere through the core's own CLI.


def test_a_record_twin_show_does_not_name_is_stale(tmp_path):
    """The core's twin show names another snapshot: the record is not trusted, the list
    files record.twin.stale (info) and marks no row, and a step given no stage is refused
    step.target.required (error, exit 1)."""
    store = Store(tmp_path)
    rec = created(store)
    other = "f" * 64
    assert not record.trusted(rec, show(other))

    f = record.stale(store, rec, show(other))
    assert (f.severity, f.rule, f.object) == ("info", "record.twin.stale", str(store.record_path))
    assert f.message == (f"the orchestrator's record names snapshot {rec.snapshot_id} from stage change-a/a, and "
                         f"twin show's record names snapshot {other}; the record is not trusted, so no stage is "
                         "marked as the twin's")

    f = record.target_required(rec, show(other))
    assert (f.severity, f.rule, f.object, f.step) == ("rejection", "step.target.required", "--stage", "start")
    assert f.message.endswith(", so the record is not trusted, and there is no stage to take the next of; give "
                              "--stage <branch>/<label>")
    doc = findings.new_document(findings.OP_TWIN_STEP, None, [f])
    assert doc.status == "rejected" and doc.exit_code == 1
    findings.validate(doc.to_dict())


def test_no_twin_and_no_record(tmp_path):
    """A twin destroyed: twin show names none, the record is stale; no record at all is no
    finding for the list and still no target for the step."""
    store = Store(tmp_path)
    rec = created(store)
    assert "names no snapshot, since no twin is recorded" in record.stale(store, rec, show(None)).message
    assert record.stale(store, None, show(None)) is None
    f = record.target_required(None, show(rec.snapshot_id))
    assert f.message == ("the orchestrator holds no record of a twin, and there is no stage to take the next of; "
                         "give --stage <branch>/<label>")


# US6 scenario 4: the reclaim.


@pytest.mark.parametrize("state", ["FAILED", "CRASHED", "CANCELLED"])
def test_a_dead_rehearsals_twin_is_reclaimed(tmp_path, state):
    rec = created(Store(tmp_path), record.FLOW_REHEARSE)
    assert record.reclaimable(rec, show(rec.snapshot_id), {"id": FLOW_RUN, "state": {"type": state}})


def test_a_rehearsal_run_past_the_platforms_retention_is_reclaimed(tmp_path):
    rec = created(Store(tmp_path), record.FLOW_REHEARSE)
    assert record.reclaimable(rec, show(rec.snapshot_id), None)


@pytest.mark.parametrize("state", ["RUNNING", "PENDING", "SCHEDULED", "CANCELLING", "COMPLETED", "PAUSED"])
def test_a_rehearsal_not_dead_holds_the_host(tmp_path, state):
    rec = created(Store(tmp_path), record.FLOW_REHEARSE)
    assert not record.reclaimable(rec, show(rec.snapshot_id), {"state": {"type": state}})


def test_a_twin_not_the_records_or_not_a_rehearsals_holds_the_host(tmp_path):
    dead = {"state": {"type": "CRASHED"}}
    rec = created(Store(tmp_path), record.FLOW_REHEARSE)
    assert not record.reclaimable(rec, show("f" * 64), dead)  # the operator stepped it elsewhere
    assert not record.reclaimable(rec, show(None), dead)
    assert not record.reclaimable(None, show(rec.snapshot_id), dead)
    for flow in (record.FLOW_CREATE, record.FLOW_STEP):
        rec = created(Store(tmp_path / flow), flow)
        assert not record.reclaimable(rec, show(rec.snapshot_id), None)


def platform(handler):
    return httpx.MockTransport(handler)


def test_the_platforms_flow_run(tmp_path):
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/gone"):
            return httpx.Response(404, json={"detail": "Flow run not found"})
        return httpx.Response(200, json={"id": FLOW_RUN, "state": {"type": "CRASHED", "name": "Crashed"}})

    env = {record.ENV_PLATFORM: "http://172.17.0.1:4200/api/", record.ENV_PLATFORM_AUTH: "fylgja:sentinel-secret"}
    run = record.read_flow_run(FLOW_RUN, env, platform(answer))
    assert run["state"]["type"] == "CRASHED"
    assert str(seen[0].url) == f"http://172.17.0.1:4200/api/flow_runs/{FLOW_RUN}"
    assert seen[0].headers["authorization"] == httpx.BasicAuth("fylgja", "sentinel-secret")._auth_header
    assert record.read_flow_run("gone", env, platform(answer)) is None


def test_a_platform_that_does_not_answer():
    def refused(request):
        raise httpx.ConnectError("[Errno 111] Connection refused")

    env = {record.ENV_PLATFORM: "http://172.17.0.1:4200/api", record.ENV_PLATFORM_AUTH: "fylgja:sentinel-secret"}
    with pytest.raises(CoreFailure) as e:
        record.read_flow_run(FLOW_RUN, env, platform(refused))
    assert (e.value.rule, e.value.object) == ("platform.unreachable", "http://172.17.0.1:4200/api")
    assert "did not answer: [Errno 111] Connection refused" in e.value.message
    assert "sentinel-secret" not in e.value.message
    with pytest.raises(CoreFailure) as e:
        record.read_flow_run(FLOW_RUN, env, platform(lambda r: httpx.Response(401)))
    assert "answered 401 Unauthorized" in e.value.message
    with pytest.raises(CoreFailure, match="PREFECT_API_URL is not set"):
        record.read_flow_run(FLOW_RUN, {})


# US6 scenario 5: every snapshot under its id, filed once.


def test_every_snapshot_is_filed_once_under_its_id(tmp_path):
    store = Store(tmp_path)
    snap = a_snapshot()
    sid, wrote = store.put(snap)
    assert (sid, wrote) == (snap["snapshot_id"], True)
    path = store.path(sid)
    assert path == tmp_path / "snapshots" / f"{sid}.json"
    assert path.read_bytes() == (DATA / "snapshot" / "three-node.json").read_bytes()
    assert oct(path.stat().st_mode & 0o777) == "0o644"
    before = path.stat()

    # A second take of the same snapshot, a later observed_at among it, writes nothing.
    again = a_snapshot()
    again["observed_at"] = again["ctm"]["envelope"]["observed_at"] = "2026-10-30T09:00:00.000000Z"
    assert snapshot.snapshot_id(again) == sid
    assert store.put(again) == (sid, False)
    after = path.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert store.fetch(sid)["observed_at"] == snap["observed_at"]

    other = a_snapshot("lossy")
    assert store.put(other) == (other["snapshot_id"], True)
    assert sorted(p.name for p in store.snapshots.iterdir()) == sorted([f"{sid}.json", f"{other['snapshot_id']}.json"])
    assert store.has(sid) and store.has(other["snapshot_id"]) and not store.has("0" * 64)


def test_a_corrupt_entry_is_refused_not_replaced(tmp_path):
    store = Store(tmp_path)
    snap = a_snapshot()
    sid = snap["snapshot_id"]
    store.snapshots.mkdir(parents=True)
    lossy = (DATA / "snapshot" / "lossy.json").read_bytes()
    store.path(sid).write_bytes(lossy)
    with pytest.raises(RecordError, match=f"hashes to [0-9a-f]{{64}}, not {sid}"):
        store.put(snap)
    assert store.path(sid).read_bytes() == lossy
    assert not store.has(sid)
    assert [p.name for p in store.snapshots.iterdir()] == [f"{sid}.json"]


def test_a_take_that_lost_the_race_keeps_the_first(tmp_path, monkeypatch):
    """Another take linked the same entry between the check and the link: the same entry,
    not a failure, and nothing replaced."""
    store = Store(tmp_path)
    snap = a_snapshot()
    real_link = os.link

    def raced(src, dst):
        real_link(src, dst)  # the other take's
        real_link(src, dst)

    monkeypatch.setattr(os, "link", raced)
    assert store.put(snap) == (snap["snapshot_id"], False)
    assert [p.name for p in store.snapshots.iterdir()] == [f"{snap['snapshot_id']}.json"]


def test_no_id_is_joined_to_the_directory(tmp_path):
    with pytest.raises(RecordError, match="is not a snapshot id"):
        Store(tmp_path).path("../twin")
    with pytest.raises(FileNotFoundError):
        Store(tmp_path).fetch("0" * 64)
