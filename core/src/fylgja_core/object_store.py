"""The object store: the store interface over an S3 endpoint that honours conditional writes
(Constitution IX, D-024, D-061).

    blueprints/<id>.json
    bundles/<id>/<path>, then bundles/<id>/manifest.json
    deployments/<id>/<path>, then deployments/<id>/deployment.json
    twins/<name>.json
    twin-runs/<twin>/<ulid>                     a marker, its body the run's id
    runs/<ulid>.json
    events/<ulid>/<seq as 10 digits>.json
    proof/<ulid>                                the proof at start, left absent

each under `<prefix>/` when the store has a prefix. Compare-and-set is the endpoint's
condition: `If-None-Match: *` creates, and `If-Match` at the ETag read replaces and deletes.
Some endpoints accept a condition and write anyway, so `open` proves the endpoint refuses
what it must before the store trusts it.
A bundle's or a deployment's document is written after its files and read before them, so
a reader sees every file or `NotFound`. An event is one object under its number, created only
if absent, so the endpoint gives each number to one writer. A twin's runs are found by their
markers, since a listing answers keys alone; events live outside `runs/` because a listing
has no delimiter.

A refused condition (`PreconditionFailed`) loses a compare-and-set, settled or not, but is
taken as proof that an object exists only when it is settled (a 412). One that is not (a 409:
another write to the key was in flight, its outcome unknown) is raised where an answer would
claim the object exists, or moving on could leave a reader a gap. Any other endpoint failure
leaves the store as the `S3Error` it is, an `OSError`, so the loop backs off on it as on a
disk failure. No request is repeated here.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import threading
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from fylgja_core import blueprint, bundle, deployment, documents, twin_record, ulid
from fylgja_core.deployment import Deployment
from fylgja_core.run import Event, Run, State
from fylgja_core.s3 import S3, NoSuchKey, PreconditionFailed, S3Error
from fylgja_core.store import (
    Change,
    Conflict,
    NotFound,
    Store,
    StoreError,
    Subscribers,
    Subscription,
    check_file_key,
    check_id,
    check_run_id,
    check_twin_name,
    dumps,
)
from fylgja_core.twin_record import TwinRecord

RULE_UNCONDITIONAL = "store.unconditional"
CONDITIONS = ("If-None-Match: * on a put", "If-Match on a put", "If-Match on a delete")


class Unconditional(StoreError):
    """The endpoint accepted a write its condition should have refused, so compare-and-set
    cannot rest on it (D-061). `condition` is the one it ignores, one of `CONDITIONS`."""

    rule = RULE_UNCONDITIONAL

    def __init__(self, condition: str) -> None:
        self.condition = condition
        super().__init__(f"the endpoint accepted a write it must refuse: it ignores {condition}")


def _refused(write: Callable[[], object], condition: str) -> None:
    """`Unconditional(condition)` unless `write` is refused."""
    try:
        write()
    except PreconditionFailed:
        return
    raise Unconditional(condition)


def _prove(s3: S3, key: str) -> None:
    """Six requests on `key`, which is left absent: a create over an object, a replace at an
    earlier ETag and a delete at an earlier ETag must each be refused. When any request fails,
    `Unconditional` or not, the key is deleted without a condition, best effort, so a core
    restarting in a loop leaves no object at a start, and the failure is raised as it was. The
    first put is among them: the endpoint may have stored it and its answer been lost, and a
    delete of a key that holds nothing is no error."""
    try:
        first = s3.put(key, b"1", if_none_match=True)
        _refused(lambda: s3.put(key, b"2", if_none_match=True), CONDITIONS[0])
        second = s3.put(key, b"3", if_match=first)
        _refused(lambda: s3.put(key, b"4", if_match=first), CONDITIONS[1])
        _refused(lambda: s3.delete(key, if_match=first), CONDITIONS[2])
        s3.delete(key, if_match=second)
    except Exception:
        with contextlib.suppress(S3Error):
            s3.delete(key)
        raise


def _check_tree(paths: Iterable[str]) -> None:
    """`ValueError` when one path is a directory of another (`configs` beside
    `configs/n1.cfg`): a directory could not hold both, and what one store holds the other must."""
    names = set(paths)
    for path in names:
        parts = path.split("/")
        for depth in range(1, len(parts)):
            parent = "/".join(parts[:depth])
            if parent in names:
                raise ValueError(f"{parent!r} is a file and the directory of {path!r}")


def _is_twin_name(name: str) -> bool:
    try:
        check_twin_name(name)
    except ValueError:
        return False
    return True


def _event_key(run_id: str, seq: int) -> str:
    return f"events/{run_id}/{seq:010d}.json"


class ObjectStore(Store):
    """The state store as objects in one bucket of an S3 endpoint."""

    def __init__(self, s3: S3, prefix: str = "") -> None:
        """No request is made. `prefix` has no leading or trailing `/`; every key is
        `<prefix>/<key>`, or `<key>` when it is empty."""
        self._s3 = s3
        self._root = f"{prefix}/" if prefix else ""
        self._lock = threading.Lock()  # a twin write and its notification, so watchers see the endpoint's order
        self._subscribers = Subscribers()
        self._closed = False

    @classmethod
    def open(cls, s3: S3, prefix: str = "") -> ObjectStore:
        """The store, once its endpoint has proved that it refuses what compare-and-set rests
        on (D-061), on a key of its own, new each start, so two cores starting together never
        read each other's. `Unconditional` names the condition it ignores; any other failure
        is the `S3Error` it is. Either way `s3` is left open for the caller to close."""
        store = cls(s3, prefix)  # no request is made
        _prove(s3, f"{store._root}proof/{ulid.new()}")
        return store

    def _live(self) -> None:
        if self._closed:
            raise StoreError("closed")

    def _get(self, key: str, missing: str) -> tuple[bytes, str]:
        """The object at `key` and its ETag; `NotFound(missing)` when the key holds none."""
        try:
            return self._s3.get(self._root + key)
        except NoSuchKey:
            raise NotFound(missing) from None

    def _list(self, prefix: str, start_after: str = "") -> list[str]:
        """Every key under `prefix` after `start_after`, in the endpoint's order, without the
        store's prefix."""
        keys = self._s3.list(self._root + prefix, self._root + start_after if start_after else "")
        return [key[len(self._root) :] for key in keys]

    def _put_new(self, key: str, body: bytes) -> bool:
        """Create `key` only if it is absent; False when the endpoint refused, settled or not:
        for a compare-and-set, which loses either way."""
        try:
            self._s3.put(self._root + key, body, if_none_match=True)
        except PreconditionFailed:
            return False
        return True

    def _put_unless_present(self, key: str, body: bytes) -> bool:
        """Create `key` only if it is absent; False on a settled refusal, which means it is
        there already. An unsettled one, whose outcome is unknown, is raised."""
        try:
            self._s3.put(self._root + key, body, if_none_match=True)
        except PreconditionFailed as refused:
            if not refused.settled:
                raise
            return False
        return True

    # documents kept by id

    def put_blueprint(self, doc: Mapping[str, Any]) -> tuple[str, bool]:
        self._live()
        bid = blueprint.blueprint_id(dict(doc))
        return bid, self._put_unless_present(f"blueprints/{bid}.json", dumps(doc))

    def get_blueprint(self, blueprint_id: str) -> dict[str, Any]:
        self._live()
        check_id(blueprint_id)
        body, _ = self._get(f"blueprints/{blueprint_id}.json", blueprint_id)
        doc: dict[str, Any] = json.loads(body)
        return doc

    def _put_tree(self, base: str, document: str, files: Mapping[str, bytes]) -> bool:
        """File `files` under `base`, `document` last; False when the document is there,
        before any file is written, or when its own put is refused settled. A file already
        there is an earlier writer's cut short, or a racing one's: the id is the files' own,
        so its bytes are these."""
        try:
            self._s3.get(self._root + base + document)
        except NoSuchKey:
            pass
        else:
            return False
        for path in sorted(files):
            if path != document:
                self._put_unless_present(base + path, files[path])
        return self._put_unless_present(base + document, files[document])

    def _get_tree(self, base: str, document: str, missing: str) -> dict[str, bytes]:
        """The files under `base` by path, `document` read first: `NotFound(missing)` without it."""
        first, _ = self._get(base + document, missing)
        files: dict[str, bytes] = {}
        for key in self._list(base):
            path = key[len(base) :]
            files[path] = first if path == document else self._get(key, missing)[0]
        files.setdefault(document, first)
        return files

    def put_bundle(self, bundle_id: str, files: Mapping[str, bytes]) -> bool:
        self._live()
        check_id(bundle_id)
        for key in files:
            check_file_key(key)
        if "manifest.json" not in files:
            raise ValueError("a bundle holds manifest.json")
        if bundle.bundle_id(files) != bundle_id:
            raise ValueError(f"bundle {bundle_id} is not the id of its files")
        _check_tree(files)
        return self._put_tree(f"bundles/{bundle_id}/", "manifest.json", files)

    def get_bundle(self, bundle_id: str) -> dict[str, bytes]:
        self._live()
        check_id(bundle_id)
        return self._get_tree(f"bundles/{bundle_id}/", "manifest.json", bundle_id)

    def put_deployment(self, deployment: Deployment, files: Mapping[str, bytes]) -> bool:
        self._live()
        check_id(deployment.id)
        for key in files:
            check_file_key(key)
        if "deployment.json" in files:
            raise ValueError("deployment.json is the deployment's own document, not a rendered file")
        tree = {"deployment.json": dumps(documents.encode(deployment)), **files}
        _check_tree(tree)
        return self._put_tree(f"deployments/{deployment.id}/", "deployment.json", tree)

    def get_deployment(self, deployment_id: str) -> tuple[Deployment, dict[str, bytes]]:
        self._live()
        check_id(deployment_id)
        files = self._get_tree(f"deployments/{deployment_id}/", "deployment.json", deployment_id)
        doc = json.loads(files.pop("deployment.json"))
        return deployment.decode(doc), files

    # twin records

    def _read_twin(self, name: str) -> tuple[TwinRecord, str]:
        body, etag = self._get(f"twins/{name}.json", name)
        return twin_record.decode(json.loads(body)), etag

    def list_twins(self) -> list[TwinRecord]:
        self._live()
        twins = []
        for key in self._list("twins/"):
            name = key.removeprefix("twins/").removesuffix(".json")
            if key != f"twins/{name}.json" or not _is_twin_name(name):  # no twin's key
                continue
            try:
                twins.append(self._read_twin(name)[0])
            except NotFound:  # deleted since the listing
                continue
        return sorted(twins, key=lambda twin: twin.name)

    def get_twin(self, name: str) -> TwinRecord:
        self._live()
        check_twin_name(name)
        return self._read_twin(name)[0]

    def create_twin(self, record: TwinRecord) -> TwinRecord:
        self._live()
        check_twin_name(record.name)
        if record.revision != 1:
            raise ValueError(f"a new twin record is at revision 1, not {record.revision}")
        with self._lock:
            if not self._put_new(f"twins/{record.name}.json", dumps(documents.encode(record))):
                raise Conflict(f"twin {record.name} exists")
            self._subscribers.notify(Change("ADDED", record))
        return record

    def _check(self, name: str, expected_revision: int) -> tuple[TwinRecord, str]:
        current, etag = self._read_twin(name)
        if current.revision != expected_revision:
            raise Conflict(f"twin {name} is at revision {current.revision}, not {expected_revision}")
        return current, etag

    def update_twin(self, record: TwinRecord, expected_revision: int) -> TwinRecord:
        self._live()
        check_twin_name(record.name)
        with self._lock:
            _, etag = self._check(record.name, expected_revision)
            written = dataclasses.replace(record, revision=expected_revision + 1)
            try:
                self._s3.put(self._root + f"twins/{record.name}.json", dumps(documents.encode(written)), if_match=etag)
            except PreconditionFailed:
                raise Conflict(f"twin {record.name} changed while it was written") from None
            except NoSuchKey:  # deleted since the read
                raise NotFound(record.name) from None
            self._subscribers.notify(Change("MODIFIED", written))
        return written

    def delete_twin(self, name: str, expected_revision: int) -> None:
        self._live()
        check_twin_name(name)
        with self._lock:
            current, etag = self._check(name, expected_revision)
            try:
                self._s3.delete(self._root + f"twins/{name}.json", if_match=etag)
            except PreconditionFailed:
                raise Conflict(f"twin {name} changed while it was deleted") from None
            except NoSuchKey:  # deleted since the read
                raise NotFound(name) from None
            self._subscribers.notify(Change("DELETED", current))

    def subscribe(self) -> Subscription:
        self._live()
        return self._subscribers.subscribe()

    # runs and their events

    def _read_run(self, run_id: str) -> tuple[Run, str]:
        body, etag = self._get(f"runs/{run_id}.json", run_id)
        return documents.decode(Run, json.loads(body)), etag

    def create_run(self, run: Run) -> None:
        self._live()
        check_run_id(run.id)
        check_twin_name(run.twin)
        self._put_unless_present(f"twin-runs/{run.twin}/{run.id}", run.id.encode())
        if not self._put_new(f"runs/{run.id}.json", dumps(documents.encode(run))):
            raise Conflict(f"run {run.id} exists")

    def get_run(self, run_id: str) -> Run:
        self._live()
        check_run_id(run_id)
        return self._read_run(run_id)[0]

    def update_run(self, run: Run, expected_state: State) -> None:
        # No lock: the ETag makes the check and the write one.
        self._live()
        check_run_id(run.id)
        current, etag = self._read_run(run.id)
        if current.state != expected_state:
            raise Conflict(f"run {run.id} is {current.state}, not {expected_state}")
        try:
            self._s3.put(self._root + f"runs/{run.id}.json", dumps(documents.encode(run)), if_match=etag)
        except PreconditionFailed:
            raise Conflict(f"run {run.id} changed while it was written") from None
        except NoSuchKey:  # gone since the read
            raise NotFound(run.id) from None

    def list_runs(self, twin: str | None = None) -> list[Run]:
        self._live()
        if twin is None:
            ids = [key.removeprefix("runs/").removesuffix(".json") for key in self._list("runs/")]
        else:
            check_twin_name(twin)
            ids = [key.removeprefix(f"twin-runs/{twin}/") for key in self._list(f"twin-runs/{twin}/")]
        runs = []
        for run_id in reversed(ids):  # a ULID sorts by time: the listing is oldest first
            try:
                run = self._read_run(run_id)[0]
            except NotFound:  # a marker whose run's create was cut short
                continue
            if twin is None or run.twin == twin:  # a refused duplicate leaves a marker under another twin
                runs.append(run)
        return runs

    def append_event(self, run_id: str, event: Event) -> Event:
        self._live()
        check_run_id(run_id)
        self._get(f"runs/{run_id}.json", run_id)
        listed = self._list(f"events/{run_id}/")
        seq = int(listed[-1].rpartition("/")[2].removesuffix(".json")) + 1 if listed else 1
        while True:
            stored = dataclasses.replace(event, seq=seq)
            try:
                self._s3.put(self._root + _event_key(run_id, seq), dumps(documents.encode(stored)), if_none_match=True)
            except PreconditionFailed as refused:
                # Settled, the number is taken: the next one, without listing again. Unsettled,
                # moving on could leave a gap if the other write failed; `seq` has none (run.py).
                if not refused.settled:
                    raise
                seq += 1
                continue
            return stored

    def events(self, run_id: str, after: int = 0) -> list[Event]:
        self._live()
        check_run_id(run_id)
        listed = self._list(f"events/{run_id}/", _event_key(run_id, after) if after > 0 else "")
        if not listed:  # an unknown run is NotFound, a known one has no events yet
            self._get(f"runs/{run_id}.json", run_id)
            return []
        return [documents.decode(Event, json.loads(self._get(key, run_id)[0])) for key in listed]

    def close(self) -> None:
        """Close the endpoint's client; closing twice is harmless."""
        if not self._closed:
            self._closed = True
            self._s3.close()
