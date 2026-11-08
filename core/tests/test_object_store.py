"""The object store (D-061): the store contract run over a fake S3 endpoint, and what is the
object store's alone: its keys, its conditional writes, and the requests each method costs."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import hashlib
import json
import threading
from collections.abc import Callable, Iterator
from urllib.parse import parse_qsl, unquote

import httpx
import pytest
from fake_s3 import FakeS3
from store_contract import DEPLOYMENT, ROOT, StoreContract, record, run_

from fylgja_core import bundle, documents, ulid
from fylgja_core.object_store import CONDITIONS, RULE_UNCONDITIONAL, ObjectStore, Unconditional
from fylgja_core.run import Event
from fylgja_core.s3 import NoSuchKey, PreconditionFailed, S3Error
from fylgja_core.store import Conflict, NotFound, Store, StoreError, dumps

FILES = {"manifest.json": b"{}", "configs/n1.cfg": b"set / system\n"}
BUNDLE = bundle.bundle_id(FILES)
RUN = run_().id
EVENT = Event(seq=0, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started")
IDS = [f"01ARZ3NDEKTSV4RRFFQ69G{i:04d}" for i in range(43)]  # ULIDs in time order


class TestObjectStore(StoreContract):
    @pytest.fixture
    def store(self) -> Iterator[Store]:
        s = ObjectStore.open(FakeS3().client(), "p")
        yield s
        s.close()


@pytest.fixture
def fake() -> FakeS3:
    return FakeS3()


@pytest.fixture
def store(fake: FakeS3) -> Iterator[ObjectStore]:
    s = ObjectStore(fake.client(), "p")
    yield s
    s.close()


def key_of(request: httpx.Request) -> str:
    return unquote(request.url.raw_path.decode()).lstrip("/").partition("/")[2]


def calls(fake: FakeS3, since: int) -> list[str]:
    """The requests from the `since`th on: `LIST <prefix>`, or the method and the key."""
    out = []
    for request in fake.requests[since:]:
        query = dict(parse_qsl(request.url.query.decode()))
        out.append(f"LIST {query['prefix']}" if "list-type" in query else f"{request.method} {key_of(request)}")
    return out


def on_put(fake: FakeS3, key: str, act: Callable[[], object]) -> None:
    """Run `act` once, as the first PUT of `key` reaches the endpoint and before it is answered."""

    def hook(request: httpx.Request) -> None:
        if request.method == "PUT" and key_of(request) == key:
            fake.before = None
            act()

    fake.before = hook


def refuse_next_put_unsettled(fake: FakeS3) -> None:
    """Answer the next PUT `409 ConditionalRequestConflict`: another write to its key was in flight."""

    def hook(request: httpx.Request) -> None:
        if request.method == "PUT":
            fake.before = None
            fake.forced.append((409, "ConditionalRequestConflict"))

    fake.before = hook


def answer_request(fake: FakeS3, index: int, status: int, code: str) -> None:
    """Answer the endpoint's `index`th request, counted from 0 over every request, `status code`."""

    def hook(request: httpx.Request) -> None:
        if len(fake.requests) == index:  # the request is recorded after this hook
            fake.before = None
            fake.forced.append((status, code))

    fake.before = hook


def delivered(store: ObjectStore, write: Callable[[], object]) -> int:
    """How many twin changes a subscriber is given while `write` runs and raises `Conflict`."""

    async def scenario() -> int:
        with store.subscribe() as sub:
            with pytest.raises(Conflict):
                write()
            await asyncio.sleep(0)  # deliveries are scheduled on the loop
            return sub.queue.qsize()

    return asyncio.run(scenario())


# --- the keys ------------------------------------------------------------------------------


@pytest.mark.parametrize(("prefix", "root"), [("p", "p/"), ("", "")])
def test_the_keys(fake: FakeS3, prefix: str, root: str) -> None:
    s = ObjectStore(fake.client(), prefix)
    doc = json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
    bid, _ = s.put_blueprint(doc)
    s.put_bundle(BUNDLE, FILES)
    s.put_deployment(DEPLOYMENT, {"topology.clab.yml": b"name: t\n"})
    s.create_twin(record("t"))
    s.create_run(run_())
    s.append_event(RUN, EVENT)
    s.append_event(RUN, EVENT)
    s.close()
    assert sorted(fake.objects) == sorted(
        root + key
        for key in (
            f"blueprints/{bid}.json",
            f"bundles/{BUNDLE}/configs/n1.cfg",
            f"bundles/{BUNDLE}/manifest.json",
            f"deployments/{DEPLOYMENT.id}/deployment.json",
            f"deployments/{DEPLOYMENT.id}/topology.clab.yml",
            "twins/t.json",
            f"twin-runs/t/{RUN}",
            f"runs/{RUN}.json",
            f"events/{RUN}/0000000001.json",
            f"events/{RUN}/0000000002.json",
        )
    )
    assert not any(key.startswith("/") for key in fake.objects)
    # A JSON object's bytes are the local store's; the marker's are the run's id.
    assert fake.objects[f"{root}twins/t.json"] == dumps(documents.encode(record("t")))
    assert fake.objects[f"{root}events/{RUN}/0000000002.json"] == dumps(
        documents.encode(dataclasses.replace(EVENT, seq=2))
    )
    assert fake.objects[f"{root}twin-runs/t/{RUN}"] == RUN.encode()


# --- compare-and-set at the ETag read ------------------------------------------------------


def test_an_update_is_a_get_then_a_put_at_the_etag_read(fake: FakeS3, store: ObjectStore) -> None:
    store.create_twin(record())
    etag = fake.etag("p/twins/t.json")
    since = len(fake.requests)
    store.update_twin(record(generation=2), expected_revision=1)
    assert calls(fake, since) == ["GET p/twins/t.json", "PUT p/twins/t.json"]
    assert fake.requests[-1].headers["if-match"] == etag and etag.startswith('"')


def test_a_record_replaced_between_the_read_and_the_write_is_a_conflict(fake: FakeS3, store: ObjectStore) -> None:
    store.create_twin(record())
    other = dumps(documents.encode(record(revision=2, generation=9)))
    on_put(fake, "p/twins/t.json", lambda: fake.objects.__setitem__("p/twins/t.json", other))
    assert delivered(store, lambda: store.update_twin(record(generation=2), expected_revision=1)) == 0
    assert fake.objects["p/twins/t.json"] == other


def test_a_record_replaced_before_its_delete_is_a_conflict(fake: FakeS3, store: ObjectStore) -> None:
    store.create_twin(record())
    other = dumps(documents.encode(record(revision=2, generation=9)))

    def replace(request: httpx.Request) -> None:
        if request.method == "DELETE":
            fake.before = None
            fake.objects["p/twins/t.json"] = other

    fake.before = replace
    assert delivered(store, lambda: store.delete_twin("t", expected_revision=1)) == 0
    assert fake.objects["p/twins/t.json"] == other


def test_a_record_deleted_between_the_read_and_the_delete_is_not_found(fake: FakeS3, store: ObjectStore) -> None:
    store.create_twin(record())

    def remove(request: httpx.Request) -> None:
        if request.method == "DELETE":
            fake.before = None
            fake.objects.pop("p/twins/t.json")

    fake.before = remove
    since = len(fake.requests)
    with pytest.raises(NotFound):
        store.delete_twin("t", expected_revision=1)
    assert calls(fake, since) == ["GET p/twins/t.json", "DELETE p/twins/t.json"]  # the delete's answer, not the read's
    assert "p/twins/t.json" not in fake.objects


def test_a_run_replaced_between_the_read_and_the_write_is_a_conflict(fake: FakeS3, store: ObjectStore) -> None:
    store.create_run(run_())
    other = dumps(documents.encode(dataclasses.replace(run_(), state="cancelling")))
    on_put(fake, f"p/runs/{RUN}.json", lambda: fake.objects.__setitem__(f"p/runs/{RUN}.json", other))
    with pytest.raises(Conflict):
        store.update_run(dataclasses.replace(run_(), state="running"), expected_state="queued")
    assert fake.objects[f"p/runs/{RUN}.json"] == other


def test_a_record_deleted_between_the_read_and_the_write_is_not_found(fake: FakeS3, store: ObjectStore) -> None:
    store.create_twin(record())
    on_put(fake, "p/twins/t.json", lambda: fake.objects.pop("p/twins/t.json"))
    with pytest.raises(NotFound):
        store.update_twin(record(generation=2), expected_revision=1)
    assert "p/twins/t.json" not in fake.objects


def test_a_run_deleted_between_the_read_and_the_write_is_not_found(fake: FakeS3, store: ObjectStore) -> None:
    store.create_run(run_())
    on_put(fake, f"p/runs/{RUN}.json", lambda: fake.objects.pop(f"p/runs/{RUN}.json"))
    with pytest.raises(NotFound):
        store.update_run(dataclasses.replace(run_(), state="running"), expected_state="queued")
    assert f"p/runs/{RUN}.json" not in fake.objects


# --- documents kept by id ------------------------------------------------------------------


def test_a_filed_document_is_never_overwritten(fake: FakeS3, store: ObjectStore) -> None:
    doc = json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
    bid, _ = store.put_blueprint(doc)
    fake.objects[f"p/blueprints/{bid}.json"] = b"sentinel"
    assert store.put_blueprint(doc) == (bid, False)
    assert fake.objects[f"p/blueprints/{bid}.json"] == b"sentinel"


def test_an_unsettled_refusal_of_a_blueprint_is_raised_not_false(fake: FakeS3, store: ObjectStore) -> None:
    doc = json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
    refuse_next_put_unsettled(fake)
    with pytest.raises(PreconditionFailed) as refused:  # no proof the id exists: False would say it does
        store.put_blueprint(doc)
    assert refused.value.settled is False and isinstance(refused.value, OSError)


def test_a_bundle_cut_short_is_not_found_then_completed(fake: FakeS3, store: ObjectStore) -> None:
    fake.objects[f"p/bundles/{BUNDLE}/configs/n1.cfg"] = FILES["configs/n1.cfg"]  # its writer died before the manifest
    with pytest.raises(NotFound):
        store.get_bundle(BUNDLE)
    assert store.put_bundle(BUNDLE, FILES) is True
    assert store.get_bundle(BUNDLE) == FILES


def test_a_bundle_present_costs_one_get(fake: FakeS3, store: ObjectStore) -> None:
    store.put_bundle(BUNDLE, FILES)
    since = len(fake.requests)
    assert store.put_bundle(BUNDLE, FILES) is False
    assert calls(fake, since) == [f"GET p/bundles/{BUNDLE}/manifest.json"]


def test_a_racing_writer_of_one_bundle_loses_cleanly(fake: FakeS3, store: ObjectStore) -> None:
    manifest = f"p/bundles/{BUNDLE}/manifest.json"
    on_put(fake, manifest, lambda: fake.objects.__setitem__(manifest, FILES["manifest.json"]))
    assert store.put_bundle(BUNDLE, FILES) is False
    assert store.get_bundle(BUNDLE) == FILES


def test_an_unsettled_refusal_of_a_file_fails_the_put(fake: FakeS3, store: ObjectStore) -> None:
    refuse_next_put_unsettled(fake)
    with pytest.raises(PreconditionFailed) as refused:
        store.put_bundle(BUNDLE, FILES)
    assert refused.value.settled is False
    assert calls(fake, 0) == [f"GET p/bundles/{BUNDLE}/manifest.json", f"PUT p/bundles/{BUNDLE}/configs/n1.cfg"]
    assert f"p/bundles/{BUNDLE}/manifest.json" not in fake.objects


def test_an_unsettled_refusal_of_a_manifest_is_raised_and_the_bundle_not_found(
    fake: FakeS3, store: ObjectStore
) -> None:
    manifest = f"p/bundles/{BUNDLE}/manifest.json"
    on_put(fake, manifest, lambda: fake.forced.append((409, "ConditionalRequestConflict")))
    with pytest.raises(PreconditionFailed) as refused:
        store.put_bundle(BUNDLE, FILES)
    assert refused.value.settled is False and isinstance(refused.value, OSError)
    assert calls(fake, 0) == [f"GET {manifest}", f"PUT p/bundles/{BUNDLE}/configs/n1.cfg", f"PUT {manifest}"]
    with pytest.raises(NotFound):
        store.get_bundle(BUNDLE)


def test_paths_that_collide_are_refused_before_any_request(fake: FakeS3, store: ObjectStore) -> None:
    collide = {"manifest.json": b"{}", "configs": b"x", "configs/n1.cfg": b"y"}
    with pytest.raises(ValueError):
        store.put_bundle(bundle.bundle_id(collide), collide)
    with pytest.raises(ValueError):
        store.put_deployment(DEPLOYMENT, {"topology": b"x", "topology/clab.yml": b"y"})
    with pytest.raises(ValueError):
        store.put_deployment(DEPLOYMENT, {"deployment.json/x": b"y"})  # beneath the deployment's document
    assert fake.requests == []


# --- events --------------------------------------------------------------------------------


def test_a_number_taken_meanwhile_moves_the_event_on(fake: FakeS3, store: ObjectStore) -> None:
    store.create_run(run_())
    store.append_event(RUN, EVENT)
    store.append_event(RUN, EVENT)
    third = f"p/events/{RUN}/0000000003.json"
    taken = dumps(documents.encode(dataclasses.replace(EVENT, seq=3, outcome="done")))
    on_put(fake, third, lambda: fake.objects.__setitem__(third, taken))  # after the listing, before our put
    since = len(fake.requests)
    assert store.append_event(RUN, EVENT).seq == 4
    assert calls(fake, since) == [
        f"GET p/runs/{RUN}.json",
        f"LIST p/events/{RUN}/",
        f"PUT {third}",
        f"PUT p/events/{RUN}/0000000004.json",
    ]
    assert [e.seq for e in store.events(RUN)] == [1, 2, 3, 4]
    assert store.events(RUN, after=2)[0].outcome == "done"  # the other's event, kept as it filed it


def test_an_unsettled_refusal_of_an_event_is_raised_and_leaves_no_gap(fake: FakeS3, store: ObjectStore) -> None:
    store.create_run(run_())
    store.append_event(RUN, EVENT)
    refuse_next_put_unsettled(fake)
    with pytest.raises(PreconditionFailed) as refused:
        store.append_event(RUN, EVENT)
    assert refused.value.settled is False
    assert sorted(k for k in fake.objects if k.startswith("p/events/")) == [f"p/events/{RUN}/0000000001.json"]
    assert store.append_event(RUN, EVENT).seq == 2
    assert [e.seq for e in store.events(RUN)] == [1, 2]


def test_eight_threads_appending_to_one_run_get_1_to_8(fake: FakeS3, store: ObjectStore) -> None:
    store.create_run(run_())
    listed = threading.Barrier(8, timeout=10)

    def all_listed(request: httpx.Request) -> None:
        if b"list-type" in request.url.query:
            listed.wait()  # every thread has read the same last number before any puts

    fake.after = all_listed
    since = len(fake.requests)
    seqs: list[int] = []
    threads = [threading.Thread(target=lambda: seqs.append(store.append_event(RUN, EVENT).seq)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fake.after = None
    assert sorted(seqs) == list(range(1, 9))
    # Each thread tries 1, 2, ... until one is its own, listing once: the kth to win puts k times.
    made = calls(fake, since)
    assert made.count(f"LIST p/events/{RUN}/") == 8
    assert sum(c.startswith(f"PUT p/events/{RUN}/") for c in made) == sum(range(1, 9))
    assert [e.seq for e in store.events(RUN)] == list(range(1, 9))


def test_events_after_a_cursor_start_the_listing_there(fake: FakeS3, store: ObjectStore) -> None:
    store.create_run(run_())
    for _ in range(4):
        store.append_event(RUN, EVENT)
    since = len(fake.requests)
    assert [e.seq for e in store.events(RUN, after=2)] == [3, 4]
    listing = dict(parse_qsl(fake.requests[since].url.query.decode()))
    assert listing["start-after"] == f"p/events/{RUN}/0000000002.json"
    assert calls(fake, since) == [
        f"LIST p/events/{RUN}/",
        f"GET p/events/{RUN}/0000000003.json",
        f"GET p/events/{RUN}/0000000004.json",
    ]


def test_events_of_a_run_with_none_cost_a_listing_and_a_get(fake: FakeS3, store: ObjectStore) -> None:
    store.create_run(run_())
    since = len(fake.requests)
    assert store.events(RUN) == []
    assert calls(fake, since) == [f"LIST p/events/{RUN}/", f"GET p/runs/{RUN}.json"]


# --- runs by twin --------------------------------------------------------------------------


def test_an_unsettled_refusal_of_a_runs_marker_is_raised(fake: FakeS3, store: ObjectStore) -> None:
    refuse_next_put_unsettled(fake)
    with pytest.raises(PreconditionFailed) as refused:
        store.create_run(run_())
    assert refused.value.settled is False
    assert calls(fake, 0) == [f"PUT p/twin-runs/t/{RUN}"]  # the run is not put


def test_a_twins_runs_cost_one_listing_and_a_get_each(fake: FakeS3, store: ObjectStore) -> None:
    mine = (5, 20, 40)
    for i, id_ in enumerate(IDS):
        store.create_run(run_(id_, "a" if i in mine else "b"))
    since = len(fake.requests)
    assert [r.id for r in store.list_runs("a")] == [IDS[40], IDS[20], IDS[5]]
    assert calls(fake, since) == ["LIST p/twin-runs/a/"] + [f"GET p/runs/{IDS[i]}.json" for i in (40, 20, 5)]


def test_a_marker_without_its_run_is_skipped(fake: FakeS3, store: ObjectStore) -> None:
    store.create_run(run_(IDS[0], "a"))
    fake.objects[f"p/twin-runs/a/{IDS[1]}"] = IDS[1].encode()  # a create cut short between the marker and the run
    assert [r.id for r in store.list_runs("a")] == [IDS[0]]


def test_a_marker_left_by_a_refused_duplicate_is_skipped(fake: FakeS3, store: ObjectStore) -> None:
    store.create_run(run_(IDS[0], "b"))
    with pytest.raises(Conflict):
        store.create_run(run_(IDS[0], "a"))  # its marker under `a` is written before the run is refused
    assert f"p/twin-runs/a/{IDS[0]}" in fake.objects
    assert store.list_runs("a") == [] and [r.id for r in store.list_runs("b")] == [IDS[0]]


def test_twin_a_does_not_list_twin_a_b(fake: FakeS3, store: ObjectStore) -> None:
    store.create_run(run_(IDS[0], "a"))
    store.create_run(run_(IDS[1], "a-b"))
    since = len(fake.requests)
    assert [r.id for r in store.list_runs("a")] == [IDS[0]]
    assert calls(fake, since) == ["LIST p/twin-runs/a/", f"GET p/runs/{IDS[0]}.json"]


def test_twins_listed_skip_one_deleted_since_the_listing_and_a_key_that_is_no_name(
    fake: FakeS3, store: ObjectStore
) -> None:
    for name in ("a", "b", "c"):
        store.create_twin(record(name))
    fake.objects["p/twins/Not_A_Name.json"] = b"{}"

    def delete_b(request: httpx.Request) -> None:
        if request.method == "GET" and key_of(request) == "p/twins/b.json":
            fake.objects.pop("p/twins/b.json")

    fake.before = delete_b
    since = len(fake.requests)
    assert [t.name for t in store.list_twins()] == ["a", "c"]
    assert "GET p/twins/Not_A_Name.json" not in calls(fake, since)


# --- the proof at start --------------------------------------------------------------------


def test_an_honest_endpoint_passes_and_nothing_is_left(fake: FakeS3) -> None:
    store = ObjectStore.open(fake.client(), "p")
    key = key_of(fake.requests[0])
    assert ulid.PATTERN.fullmatch(key.removeprefix("p/proof/"))
    e1, e2 = (f'"{hashlib.md5(body).hexdigest()}"' for body in (b"1", b"3"))  # the fake's ETags
    assert [
        (r.method, key_of(r), r.content, r.headers.get("if-none-match"), r.headers.get("if-match"))
        for r in fake.requests
    ] == [
        ("PUT", key, b"1", "*", None),
        ("PUT", key, b"2", "*", None),
        ("PUT", key, b"3", None, e1),
        ("PUT", key, b"4", None, e1),
        ("DELETE", key, b"", None, e1),
        ("DELETE", key, b"", None, e2),
    ]
    assert fake.objects == {}
    store.close()


IGNORED = [  # the condition ignored, its name, and the requests the proof makes, the cleanup last
    ("if-none-match", CONDITIONS[0], ["PUT", "PUT", "DELETE"]),
    ("if-match-put", CONDITIONS[1], ["PUT"] * 4 + ["DELETE"]),
    ("if-match-delete", CONDITIONS[2], ["PUT"] * 4 + ["DELETE", "DELETE"]),
]


@pytest.mark.parametrize(("ignored", "condition", "made"), IGNORED)
def test_each_ignored_condition_is_refused_by_name(
    fake: FakeS3, ignored: str, condition: str, made: list[str]
) -> None:
    fake.ignore = {ignored}
    client = fake.client()
    with pytest.raises(Unconditional) as refused:
        ObjectStore.open(client, "p")
    assert refused.value.condition == condition
    assert refused.value.rule == RULE_UNCONDITIONAL == "store.unconditional"
    assert condition in str(refused.value)
    assert [r.method for r in fake.requests] == made  # the proof stops at the condition ignored
    cleanup = fake.requests[-1]
    assert cleanup.method == "DELETE" and "if-match" not in cleanup.headers  # deleted without a condition
    assert not any(key.startswith("p/proof/") for key in fake.objects)
    assert client.list("p/") == []  # the client is left open, for the caller to close
    client.close()


@pytest.mark.parametrize(("ignored", "condition", "made"), IGNORED)
def test_a_failed_cleanup_leaves_the_refusal_as_it_was(
    fake: FakeS3, ignored: str, condition: str, made: list[str]
) -> None:
    fake.ignore = {ignored}
    answer_request(fake, len(made) - 1, 500, "InternalError")  # the cleanup's delete
    with pytest.raises(Unconditional) as refused:
        ObjectStore.open(fake.client(), "p")
    assert refused.value.condition == condition
    assert refused.value.__context__ is None and refused.value.__cause__ is None
    assert [r.method for r in fake.requests] == made and fake.forced == []  # the 500 was the cleanup's


@pytest.mark.parametrize("step", [1, 2, 3, 4, 5, 6])
def test_a_failure_of_any_request_is_raised_and_nothing_is_left(fake: FakeS3, step: int) -> None:
    answer_request(fake, step - 1, 500, "InternalError")
    with pytest.raises(S3Error) as failed:
        ObjectStore.open(fake.client(), "p")
    assert not isinstance(failed.value, Unconditional) and failed.value.status == 500
    assert str(failed.value).startswith(f"{'PUT' if step <= 4 else 'DELETE'} p/proof/")  # the step's own error
    assert failed.value.__context__ is None and failed.value.__cause__ is None
    assert len(fake.requests) == step + 1
    cleanup = fake.requests[-1]
    assert cleanup.method == "DELETE" and "if-match" not in cleanup.headers
    assert not any(key.startswith("p/proof/") for key in fake.objects)


def test_a_first_put_stored_with_its_answer_lost_leaves_nothing(fake: FakeS3) -> None:
    def lose_the_answer(request: httpx.Request) -> None:
        fake.after = None
        raise httpx.ReadTimeout("lost")  # after the fake stored the put

    fake.after = lose_the_answer
    with pytest.raises(S3Error) as failed:
        ObjectStore.open(fake.client(), "p")
    assert failed.value.status is None and str(failed.value).startswith("PUT p/proof/")
    assert [key for key in fake.objects if key.startswith("p/proof/")] == []
    assert [r.method for r in fake.requests] == ["PUT", "DELETE"]
    assert "if-match" not in fake.requests[-1].headers  # deleted without a condition


def test_two_proofs_use_two_keys(fake: FakeS3) -> None:
    client = fake.client()
    ObjectStore.open(client, "p")
    ObjectStore.open(client, "p")
    keys = [key_of(r) for r in fake.requests]
    assert len(keys) == 12 and len(set(keys[:6])) == 1 and len(set(keys[6:])) == 1
    assert keys[0] != keys[6] and all(key.startswith("p/proof/") for key in keys)
    client.close()


def test_a_missing_bucket_at_start_is_an_s3_error_not_unconditional(fake: FakeS3) -> None:
    with pytest.raises(S3Error) as failed:
        ObjectStore.open(fake.client(bucket="other"), "p")
    assert not isinstance(failed.value, (Unconditional, NoSuchKey))
    assert "404 NoSuchBucket" in str(failed.value)
    assert [r.method for r in fake.requests] == ["PUT", "DELETE"]  # the cleanup's delete, refused alike


def test_a_wrong_secret_at_start_names_no_key(fake: FakeS3) -> None:
    wrong = "wrong-fixture-secret-not-a-credential"
    with pytest.raises(S3Error) as failed:
        ObjectStore.open(fake.client(secret_key=wrong), "p")
    assert failed.value.status == 403 and "403 SignatureDoesNotMatch" in str(failed.value)
    for text in (str(failed.value), repr(failed.value)):
        assert wrong not in text and fake.secret_key not in text and fake.access_key not in text
    assert [r.method for r in fake.requests] == ["PUT", "DELETE"]  # the cleanup's delete, refused alike


def test_a_skewed_clock_at_start_is_named(fake: FakeS3) -> None:
    behind = fake.client(now=lambda: datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=16))
    with pytest.raises(S3Error) as failed:
        ObjectStore.open(behind, "p")
    assert failed.value.code == "RequestTimeTooSkewed" and "clock" in str(failed.value)
    assert [r.method for r in fake.requests] == ["PUT", "DELETE"]  # the cleanup's delete, refused alike


# --- the endpoint and close ----------------------------------------------------------------


def test_an_endpoint_failure_is_an_oserror_and_the_store_goes_on(fake: FakeS3, store: ObjectStore) -> None:
    store.create_twin(record())
    fake.forced = [(500, "InternalError")]
    with pytest.raises(OSError) as failed:
        store.get_twin("t")
    assert not isinstance(failed.value, StoreError)
    assert store.get_twin("t") == record()


def test_a_404_that_is_not_no_such_key_is_an_endpoint_failure_not_not_found(fake: FakeS3, store: ObjectStore) -> None:
    store.create_twin(record())
    fake.forced = [(404, "NotFound")]  # not the gateway's answer for a missing key: the twin is there
    with pytest.raises(S3Error) as failed:
        store.get_twin("t")
    assert failed.value.status == 404 and "404 NotFound" in str(failed.value)
    assert store.get_twin("t") == record()


def test_close_closes_the_endpoint(fake: FakeS3) -> None:
    client = fake.client()
    s = ObjectStore(client, "p")
    s.close()
    s.close()  # twice is harmless
    with pytest.raises(RuntimeError):  # the client is closed
        client.get("p/twins/t.json")
    every: list[Callable[[], object]] = [
        lambda: s.put_blueprint({}),
        lambda: s.get_blueprint("a" * 64),
        lambda: s.put_bundle(BUNDLE, FILES),
        lambda: s.get_bundle(BUNDLE),
        lambda: s.put_deployment(DEPLOYMENT, {}),
        lambda: s.get_deployment(DEPLOYMENT.id),
        s.list_twins,
        lambda: s.get_twin("t"),
        lambda: s.create_twin(record()),
        lambda: s.update_twin(record(), 1),
        lambda: s.delete_twin("t", 1),
        s.subscribe,
        lambda: s.create_run(run_()),
        lambda: s.get_run(RUN),
        lambda: s.update_run(run_(), "queued"),
        s.list_runs,
        lambda: s.append_event(RUN, EVENT),
        lambda: s.events(RUN),
    ]
    for call in every:
        with pytest.raises(StoreError, match="closed"):
            call()
    assert fake.requests == []
