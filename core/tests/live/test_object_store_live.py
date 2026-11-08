"""The object store against Versity S3 Gateway v1.10.0 under Docker, the endpoint development
uses (D-061): the store contract whole; each compare-and-set raced by 32 stores, five rounds,
with no Lease between them; and what the gateway answers at the edges the store meets, each
held to the fake endpoint's answer to the same call. Each test prints what it read (`-s`).

The module runs one gateway on a free port of 127.0.0.1, with keys made for the run, and each
test works under a prefix of its own in one bucket. The container and its data directory are
removed at the module's end, whatever happened. The keys are in no command line, repr, assert
or printed line, and in no file the module writes: Docker holds them in the container's config
until the module removes the container.

Needs Docker alone: no containerlab, no `local/.env`.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import os
import secrets
import shutil
import socket
import statistics
import subprocess
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator

import httpx
import pytest
from fake_s3 import FakeS3
from store_contract import StoreContract, record, run_

from fylgja_core import bundle, s3, ulid
from fylgja_core.object_store import ObjectStore, Unconditional
from fylgja_core.run import Event, Run
from fylgja_core.s3 import S3, NoSuchKey, S3Error
from fylgja_core.store import NotFound
from fylgja_core.twin_record import TwinRecord

IMAGE = "ghcr.io/versity/versitygw:v1.10.0"
BUCKET = "fylgja-live"
READY_S = 30.0
RACERS = 32
ROUNDS = 5
TIMED = 5
EVENT = Event(seq=0, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started")


@dataclasses.dataclass(frozen=True)
class Gateway:
    """The module's gateway: its endpoint, its keys (in no repr) and its container's name."""

    endpoint: str
    access_key: str = dataclasses.field(repr=False)
    secret_key: str = dataclasses.field(repr=False)
    container: str


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60, check=False)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def connect(gateway: Gateway, bucket: str = BUCKET) -> S3:
    return S3.connect(gateway.endpoint, bucket, gateway.access_key, gateway.secret_key)


def prefix() -> str:
    return f"t-{ulid.new().lower()}"


def wait_until_answering(gateway: Gateway) -> None:
    """Poll a listing until the gateway answers it, whatever the answer, within `READY_S`."""
    client = connect(gateway)
    deadline = time.monotonic() + READY_S
    try:
        while True:
            try:
                client.list("")
                return
            except S3Error as error:
                if error.status is not None:
                    return
                if time.monotonic() > deadline:
                    raise
            time.sleep(0.2)
    finally:
        client.close()


def create_bucket(gateway: Gateway) -> None:
    """One signed `PUT /<bucket>`: test code alone, the store has no such call."""
    url = s3.request_url(gateway.endpoint, BUCKET)
    headers = s3.sign(
        "PUT",
        url,
        {},
        b"",
        access_key=gateway.access_key,
        secret_key=gateway.secret_key,
        region="us-east-1",
        at=datetime.datetime.now(datetime.UTC),
    )
    created = httpx.put(url, headers=headers, timeout=s3.TIMEOUT_S)
    assert created.status_code == 200, f"PUT /{BUCKET}: {created.status_code}"


@pytest.fixture(scope="module")
def gateway(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Gateway]:
    """The gateway, with the bucket made; removed at the module's end with its data directory."""
    data = tmp_path_factory.mktemp("versity")
    port = free_port()
    gateway = Gateway(
        endpoint=f"http://127.0.0.1:{port}",
        access_key=secrets.token_hex(10),
        secret_key=secrets.token_hex(20),
        container=f"fylgja-versity-{secrets.token_hex(4)}",
    )
    command = [
        "run", "-d", "--name", gateway.container, "--user", f"{os.getuid()}:{os.getgid()}",
        "-p", f"127.0.0.1:{port}:7070", "-e", "ROOT_ACCESS_KEY", "-e", "ROOT_SECRET_KEY",
        "-v", f"{data}:/data", IMAGE, "posix", "/data",
    ]
    try:
        # Docker reads each `-e NAME`'s value from its own environment, which is this process's
        # for the one call: the keys are no argument a printed traceback could show.
        with pytest.MonkeyPatch.context() as environment:
            environment.setenv("ROOT_ACCESS_KEY", gateway.access_key)
            environment.setenv("ROOT_SECRET_KEY", gateway.secret_key)
            start = time.monotonic()
            started = docker(*command)
        print(f"\n[live] docker {' '.join(command)}: rc {started.returncode}", flush=True)
        assert started.returncode == 0, started.stderr[-2000:]
        wait_until_answering(gateway)
        print(f"[live] the gateway answered a listing {time.monotonic() - start:.2f} s after docker run", flush=True)
        create_bucket(gateway)
        client = connect(gateway)
        try:
            assert client.list("") == []
        finally:
            client.close()
        yield gateway
    finally:
        removed = docker("rm", "-f", gateway.container)
        print(f"\n[live] docker rm -f: rc {removed.returncode}", flush=True)
        shutil.rmtree(data, ignore_errors=True)
        left = docker("ps", "-a", "--filter", f"name=^{gateway.container}$", "--format", "{{.Names}}")
        assert left.stdout.strip() == "" and not data.exists()


@pytest.fixture
def store(gateway: Gateway) -> Iterator[ObjectStore]:
    s = ObjectStore.open(connect(gateway), prefix())
    yield s
    s.close()


class TestObjectStoreLive(StoreContract):
    """The whole contract against the gateway: a case it fails is a bug in the store."""


# --- the races ------------------------------------------------------------------------------


def race(gateway: Gateway, under: str, act: Callable[[ObjectStore, int], object]) -> list[object]:
    """What each of `RACERS` stores over the prefix `under` met doing `act(store, i)` at once,
    behind one barrier: its result, or what it raised. Each store has its own client and its
    own lock, as `RACERS` cores would."""
    stores = [ObjectStore(connect(gateway), under) for _ in range(RACERS)]
    barrier = threading.Barrier(RACERS, timeout=READY_S)
    outcomes: list[object] = [None] * RACERS

    def racer(i: int) -> None:
        try:
            barrier.wait()
            outcomes[i] = act(stores[i], i)
        except Exception as error:
            outcomes[i] = error

    threads = [threading.Thread(target=racer, args=(i,)) for i in range(RACERS)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        for s in stores:
            s.close()
    return outcomes


def tally(outcomes: list[object]) -> dict[str, int]:
    """How many racers met each outcome: the name of what was raised, `True` or `False` for a
    bool, else `accepted`."""

    def label(outcome: object) -> str:
        if isinstance(outcome, BaseException):
            return type(outcome).__name__
        if isinstance(outcome, bool):
            return str(outcome)
        return "accepted"

    return dict(sorted(Counter(map(label, outcomes)).items()))


def rounds(gateway: Gateway) -> Iterator[tuple[int, str, ObjectStore]]:
    """`ROUNDS` times: the round's number, a prefix of its own, and a store over it that
    prepares the race and reads what it left."""
    for n in range(1, ROUNDS + 1):
        under = prefix()
        s = ObjectStore(connect(gateway), under)
        try:
            yield n, under, s
        finally:
            s.close()


def the_winner(outcomes: list[object], accepted: Callable[[object], bool]) -> int:
    (winner,) = [i for i, outcome in enumerate(outcomes) if accepted(outcome)]
    return winner


def test_32_creates_of_one_twin_admit_one(gateway: Gateway) -> None:
    for n, under, s in rounds(gateway):
        outcomes = race(gateway, under, lambda store, i: store.create_twin(record(generation=1 + i)))
        print(f"\n[live] create_twin of one name, round {n}: {tally(outcomes)}")
        assert tally(outcomes) == {"Conflict": 31, "accepted": 1}
        winner = the_winner(outcomes, lambda o: isinstance(o, TwinRecord))
        assert s.get_twin("t").generation == 1 + winner


def test_32_updates_at_one_revision_admit_one(gateway: Gateway) -> None:
    for n, under, s in rounds(gateway):
        s.create_twin(record())
        outcomes = race(
            gateway, under, lambda store, i: store.update_twin(record(generation=2 + i), expected_revision=1)
        )
        print(f"\n[live] update_twin at revision 1, round {n}: {tally(outcomes)}")
        assert tally(outcomes) == {"Conflict": 31, "accepted": 1}
        winner = the_winner(outcomes, lambda o: isinstance(o, TwinRecord))
        stored = s.get_twin("t")
        assert (stored.revision, stored.generation) == (2, 2 + winner)


def test_32_creates_of_one_run_admit_one(gateway: Gateway) -> None:
    run = run_()
    for n, under, s in rounds(gateway):
        outcomes = race(
            gateway, under, lambda store, i: store.create_run(dataclasses.replace(run, principal=f"racer-{i}"))
        )
        print(f"\n[live] create_run of one id, round {n}: {tally(outcomes)}")
        assert tally(outcomes) == {"Conflict": 31, "accepted": 1}
        winner = the_winner(outcomes, lambda o: o is None)
        assert [r.principal for r in s.list_runs()] == [f"racer-{winner}"]
        assert [r.principal for r in s.list_runs(twin="t")] == [f"racer-{winner}"]


def test_32_updates_from_queued_admit_one(gateway: Gateway) -> None:
    run = run_()

    def start(store: ObjectStore, i: int) -> None:
        store.update_run(dataclasses.replace(run, state="running", principal=f"racer-{i}"), expected_state="queued")

    for n, under, s in rounds(gateway):
        s.create_run(run)
        outcomes = race(gateway, under, start)
        print(f"\n[live] update_run from queued, round {n}: {tally(outcomes)}")
        assert tally(outcomes) == {"Conflict": 31, "accepted": 1}
        winner = the_winner(outcomes, lambda o: o is None)
        stored = s.get_run(run.id)
        assert (stored.state, stored.principal) == ("running", f"racer-{winner}")


def test_32_appends_to_one_run_are_numbered_1_to_32(gateway: Gateway) -> None:
    run = run_()
    for n, under, s in rounds(gateway):
        s.create_run(run)
        outcomes = race(
            gateway, under, lambda store, i: store.append_event(run.id, dataclasses.replace(EVENT, node=f"n{i}"))
        )
        print(f"\n[live] append_event to one run, round {n}: {tally(outcomes)}")
        assert tally(outcomes) == {"accepted": 32}
        answered = {e.node: e.seq for e in outcomes if isinstance(e, Event)}
        assert sorted(answered.values()) == list(range(1, 33))
        events = s.events(run.id)
        assert [e.seq for e in events] == list(range(1, 33))
        assert {e.node: e.seq for e in events} == answered  # each event is the one its writer was answered


def test_32_puts_of_one_bundle_answer_true_once_and_every_store_reads_it_whole(gateway: Gateway) -> None:
    files = {"manifest.json": b"{}", "configs/n1.cfg": b"set / system\n", "configs/a b+c=é~x.cfg": b"x"}
    bid = bundle.bundle_id(files)
    read: list[dict[str, bytes] | None] = []

    def put_then_get(store: ObjectStore, i: int) -> bool:
        created = store.put_bundle(bid, files)
        read[i] = store.get_bundle(bid)  # an answer of False means the bundle is whole already
        return created

    for n, under, _ in rounds(gateway):
        read[:] = [None] * RACERS
        outcomes = race(gateway, under, put_then_get)
        print(f"\n[live] put_bundle of one id, round {n}: {tally(outcomes)}")
        assert tally(outcomes) == {"False": 31, "True": 1}
        assert [got == files for got in read] == [True] * RACERS


def test_32_deletes_at_one_revision(gateway: Gateway) -> None:
    for n, under, s in rounds(gateway):
        s.create_twin(record())
        outcomes = race(gateway, under, lambda store, i: store.delete_twin("t", expected_revision=1))
        counts = tally(outcomes)
        print(f"\n[live] delete_twin at revision 1, round {n}: {counts}")
        assert counts.get("accepted", 0) >= 1 and set(counts) <= {"accepted", "Conflict", "NotFound"}
        with pytest.raises(NotFound):
            s.get_twin("t")


# --- the edges, each held to the fake's answer to the same call ------------------------------


def said(error: S3Error) -> str:
    return f"{type(error).__name__} {error.status} {error.code}"


def answer(call: Callable[[], object]) -> str:
    """`accepted`, or what `call` raised: its class, the status and the endpoint's code."""
    try:
        call()
    except S3Error as error:
        return said(error)
    return "accepted"


def test_a_conditional_delete_of_a_missing_key_is_answered_as_the_fake_answers(gateway: Gateway) -> None:
    key, etag = f"{prefix()}/twins/missing.json", f'"{hashlib.md5(b"{}").hexdigest()}"'
    live = connect(gateway)
    try:
        got = answer(lambda: live.delete(key, if_match=etag))
    finally:
        live.close()
    fake = FakeS3().client()
    assumed = answer(lambda: fake.delete(key, if_match=etag))
    print(f"\n[live] DELETE with If-Match of a key that does not exist: {got}; the fake: {assumed}")
    assert got == assumed


def test_a_request_signed_20_minutes_behind_is_named_a_clock_difference(gateway: Gateway) -> None:
    def behind() -> datetime.datetime:
        return datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=20)

    key = f"{prefix()}/skewed"
    live = S3(httpx.Client(timeout=s3.TIMEOUT_S), gateway.endpoint, BUCKET, gateway.access_key,
              gateway.secret_key, now=behind)
    try:
        with pytest.raises(S3Error) as refused:
            live.put(key, b"x", if_none_match=True)
    finally:
        live.close()
    fake = FakeS3().client(now=behind)
    assumed = answer(lambda: fake.put(key, b"x", if_none_match=True))
    print(f"\n[live] a put signed 20 minutes behind: {said(refused.value)}; the fake: {assumed}")
    assert said(refused.value) == assumed
    assert refused.value.code in s3.SKEW_CODES and "clock" in str(refused.value)
    on_time = connect(gateway)
    try:
        with pytest.raises(NoSuchKey):  # nothing was written
            on_time.get(key)
    finally:
        on_time.close()


def test_a_wrong_secret_at_start_is_refused_naming_no_key(gateway: Gateway) -> None:
    wrong = secrets.token_hex(20)
    live = S3.connect(gateway.endpoint, BUCKET, gateway.access_key, wrong)
    try:
        with pytest.raises(S3Error) as refused:
            ObjectStore.open(live, prefix())
    finally:
        live.close()
    texts = (str(refused.value), repr(refused.value))
    named = any(key in text for key in (gateway.access_key, gateway.secret_key, wrong) for text in texts)
    fake = FakeS3()
    assumed = answer(lambda: ObjectStore.open(fake.client(secret_key=wrong), "p"))
    print(f"\n[live] a start with a wrong secret key: {said(refused.value)}; the fake: {assumed}")
    assert not isinstance(refused.value, Unconditional) and refused.value.status == 403
    assert not named  # a bool: computed outside the assert, so a failure prints no key
    assert said(refused.value) == assumed


def test_a_start_against_a_bucket_that_does_not_exist_is_404_no_such_bucket(gateway: Gateway) -> None:
    live = connect(gateway, bucket="fylgja-none")
    try:
        with pytest.raises(S3Error) as refused:
            ObjectStore.open(live, prefix())
    finally:
        live.close()
    assumed = answer(lambda: ObjectStore.open(FakeS3().client(bucket="fylgja-none"), "p"))
    print(f"\n[live] a start against a bucket that does not exist: {refused.value}; the fake: {assumed}")
    assert not isinstance(refused.value, (Unconditional, NoSuchKey)) and "404 NoSuchBucket" in str(refused.value)
    assert said(refused.value) == assumed


def paged(gateway: Gateway) -> tuple[ObjectStore, list[httpx.URL]]:
    """A store whose listings come in pages of five, and the URL of each page it asks for."""
    urls: list[httpx.URL] = []

    def listing(request: httpx.Request) -> None:
        if "list-type" in request.url.params:
            urls.append(request.url)

    http = httpx.Client(timeout=s3.TIMEOUT_S, event_hooks={"request": [listing]})
    client = S3(http, gateway.endpoint, BUCKET, gateway.access_key, gateway.secret_key, page=5)
    return ObjectStore(client, prefix()), urls


def cursor(url: httpx.URL) -> str:
    """The cursor a listing page sent: `start-after`, `continuation-token` or `none`."""
    return next((name for name in ("start-after", "continuation-token") if name in url.params), "none")


def test_events_from_a_cursor_are_read_across_pages_of_five(gateway: Gateway) -> None:
    s, urls = paged(gateway)
    run: Run = run_()
    read: dict[int, tuple[list[int], list[str]]] = {}  # by `after`: the events' numbers, each page's cursor
    try:
        s.create_run(run)
        for _ in range(12):
            s.append_event(run.id, EVENT)
        for after in (7, 2, 0):
            urls.clear()
            read[after] = [e.seq for e in s.events(run.id, after=after)], [cursor(url) for url in urls]
    finally:
        s.close()
    for after, (seqs, cursors) in read.items():
        print(f"\n[live] twelve events read after {after} in pages of five: {seqs}, the pages' cursors {cursors}")
    assert read[7] == ([8, 9, 10, 11, 12], ["start-after"])  # five left fill one page, not marked truncated
    assert read[2] == (list(range(3, 13)), ["start-after", "continuation-token"])
    assert read[0] == (list(range(1, 13)), ["none", "continuation-token", "continuation-token"])


def test_a_continuation_token_holding_a_space_a_plus_and_an_equals_sign_is_signed_as_sent(gateway: Gateway) -> None:
    # Sorted, the fifth key is the one that needs encoding, so a page of five ends there.
    files = {"manifest.json": b"{}", **{f"configs/{n}.cfg": b"x" for n in range(1, 5)}, "configs/a b+c=é~x.cfg": b"y"}
    bid = bundle.bundle_id(files)
    s, urls = paged(gateway)
    try:
        assert s.put_bundle(bid, files) is True
        urls.clear()
        got = s.get_bundle(bid)
    finally:
        s.close()
    (page,) = [url for url in urls if "continuation-token" in url.params]
    token = page.params["continuation-token"]
    sent = next(pair for pair in page.query.decode().split("&") if pair.startswith("continuation-token="))
    print(f"\n[live] the token after configs/a b+c=é~x.cfg: {token!r}, sent as {sent}")
    assert got == files and [cursor(url) for url in urls] == ["none", "continuation-token"]
    assert {" ", "+", "=", "/"} <= set(token)  # the gateway's token is the last key of the page


def ms(seconds: list[float]) -> str:
    """The median and every value, in milliseconds."""
    every = ", ".join(f"{s * 1000:.1f}" for s in sorted(seconds))
    return f"median {statistics.median(seconds) * 1000:.1f} ms of {every}"


def test_the_wall_time_of_a_start_an_append_and_a_listing_of_20_twins(gateway: Gateway) -> None:
    under = prefix()
    opens: list[float] = []
    for _ in range(TIMED):
        client = connect(gateway)  # a start's own client, so its first request connects
        start = time.perf_counter()
        ObjectStore.open(client, under).close()
        opens.append(time.perf_counter() - start)
    s = ObjectStore(connect(gateway), under)
    appends: list[float] = []
    listings: list[float] = []
    twins: list[TwinRecord] = []
    try:
        s.create_run(run_())
        for _ in range(TIMED):
            start = time.perf_counter()
            s.append_event(run_().id, EVENT)
            appends.append(time.perf_counter() - start)
        for i in range(20):
            s.create_twin(record(f"t{i}"))
        for _ in range(TIMED):
            start = time.perf_counter()
            twins = s.list_twins()
            listings.append(time.perf_counter() - start)
    finally:
        s.close()
    print(f"\n[live] open (the proof, 6 requests), {TIMED} starts: {ms(opens)}")
    print(f"[live] one append_event (a get, a listing, a put), {TIMED} appends: {ms(appends)}")
    print(f"[live] list_twins over 20 twins (a listing, 20 gets), {TIMED} listings: {ms(listings)}")
    assert len(twins) == 20


def test_a_twin_written_before_a_restart_is_read_and_replaced_after_it(gateway: Gateway) -> None:
    under = prefix()
    before = ObjectStore(connect(gateway), under)
    try:
        before.create_twin(record())
    finally:
        before.close()
    start = time.monotonic()
    restarted = docker("restart", gateway.container)
    assert restarted.returncode == 0, restarted.stderr[-2000:]
    wait_until_answering(gateway)
    print(f"\n[live] docker restart: the gateway answered a listing again after {time.monotonic() - start:.2f} s")
    after = ObjectStore.open(connect(gateway), under)
    try:
        assert after.get_twin("t") == record()
        assert after.update_twin(record(generation=2), expected_revision=1).revision == 2  # at the ETag it read
        assert after.get_twin("t").generation == 2
    finally:
        after.close()
