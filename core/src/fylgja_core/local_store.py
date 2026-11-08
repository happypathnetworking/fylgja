"""The local store: a directory in D-041's layout (Constitution IX, D-024, D-041).

    lock                                  held while a core has the store
    blueprints/<id>.json
    bundles/<id>/manifest.json, configs/<node>.cfg
    deployments/<id>/deployment.json, and the rendered files beside it
    twins/<name>.json
    runs/<ulid>.json, runs/<ulid>.events.ndjson

Every write goes to a temporary file in the same directory, is fsynced, and is renamed or
linked into place, so a core killed mid-write leaves the old file or none, never half of
one. A content-addressed document is linked, so an existing id is never overwritten; a
multi-file document is built in a temporary directory and renamed into place.
"""

from __future__ import annotations

import dataclasses
import errno
import fcntl
import json
import os
import secrets
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fylgja_core import blueprint, bundle, deployment, documents, twin_record
from fylgja_core.deployment import Deployment
from fylgja_core.run import Event, Run, State
from fylgja_core.store import (
    Change,
    Conflict,
    Locked,
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

_TAIL = 64 * 1024  # how much of an events file is read to find its last sequence number
_DIRECTORIES = ("blueprints", "bundles", "deployments", "twins", "runs")


def _temp_name(directory: Path) -> Path:
    return directory / f".tmp-{secrets.token_hex(8)}"


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_temp(directory: Path, data: bytes) -> Path:
    """`data` in a new fsynced temporary file in `directory`."""
    temp = _temp_name(directory)
    try:
        with temp.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return temp


def _write_atomic(path: Path, data: bytes) -> None:
    """Replace `path` with `data`, whole or not at all."""
    temp = _write_temp(path.parent, data)
    try:
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _link_into_place(temp: Path, final: Path) -> bool:
    """Link `temp` as `final` and drop `temp`; False, with `final` untouched, when it exists."""
    try:
        os.link(temp, final)
    except FileExistsError:
        return False
    finally:
        temp.unlink(missing_ok=True)
    _fsync_directory(final.parent)
    return True


def _write_new(path: Path, data: bytes) -> bool:
    """Write `path` only if it does not exist; returns whether it was written."""
    return _link_into_place(_write_temp(path.parent, data), path)


def _write_tree(final: Path, files: Mapping[str, bytes]) -> bool:
    """Build the directory `final` from `files` in a temporary directory beside it and rename
    it into place; False when `final` is already there."""
    if final.exists():
        return False
    temp = _temp_name(final.parent)
    temp.mkdir()
    try:
        for name, data in files.items():
            path = temp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            if path.parent != temp:
                _fsync_directory(path.parent)
        _fsync_directory(temp)
    except BaseException:
        _remove_tree(temp)
        raise
    try:
        os.rename(temp, final)
    except OSError as e:
        _remove_tree(temp)
        if e.errno in (errno.EEXIST, errno.ENOTEMPTY):
            return False
        raise
    except BaseException:
        _remove_tree(temp)
        raise
    _fsync_directory(final.parent)
    return True


def _remove_tree(directory: Path) -> None:
    if not directory.is_dir():
        directory.unlink(missing_ok=True)
        return
    for path in sorted(directory.rglob("*"), reverse=True):
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
    directory.rmdir()


def _read_tree(directory: Path, key: str) -> dict[str, bytes]:
    if not directory.is_dir():
        raise NotFound(key)
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file()}


class LocalStore(Store):
    """The state store as a directory."""

    def __init__(self, root: Path, lock_fd: int | None = None) -> None:
        self.root = Path(root)
        self._lock_fd = lock_fd
        self._mutex = threading.Lock()  # compare-and-set, and the order of notifications
        self._subscribers = Subscribers()
        self._closed = False

    @classmethod
    def open(cls, root: Path) -> LocalStore:
        """The store in `root`, its layout created and held by this process until `close`;
        `Locked`, naming the holder's pid, when another core holds it."""
        root = Path(root)
        for name in _DIRECTORIES:
            (root / name).mkdir(parents=True, exist_ok=True)
        fd = os.open(root / "lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = os.pread(fd, 32, 0).decode().strip() or "unknown"
            os.close(fd)
            raise Locked(f"the store {root} is held by pid {holder}") from None
        except BaseException:
            os.close(fd)
            raise
        try:
            os.ftruncate(fd, 0)
            os.pwrite(fd, str(os.getpid()).encode(), 0)
            # No other core holds the store, so no temporary file is in use: sweep what a killed one left.
            for name in _DIRECTORIES:
                for leftover in (root / name).glob(".tmp-*"):
                    _remove_tree(leftover)
        except BaseException:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            raise
        return cls(root, fd)

    def put_blueprint(self, doc: Mapping[str, Any]) -> tuple[str, bool]:
        self._live()
        bid = blueprint.blueprint_id(dict(doc))
        return bid, _write_new(self.root / "blueprints" / f"{bid}.json", dumps(doc))

    def get_blueprint(self, blueprint_id: str) -> dict[str, Any]:
        self._live()
        check_id(blueprint_id)
        try:
            doc: dict[str, Any] = json.loads((self.root / "blueprints" / f"{blueprint_id}.json").read_bytes())
        except FileNotFoundError:
            raise NotFound(blueprint_id) from None
        return doc

    def _live(self) -> None:
        if self._closed:
            raise StoreError("closed")

    def put_bundle(self, bundle_id: str, files: Mapping[str, bytes]) -> bool:
        self._live()
        check_id(bundle_id)
        for key in files:
            check_file_key(key)
        if "manifest.json" not in files:
            raise ValueError("a bundle holds manifest.json")
        if bundle.bundle_id(files) != bundle_id:
            raise ValueError(f"bundle {bundle_id} is not the id of its files")
        return _write_tree(self.root / "bundles" / bundle_id, files)

    def get_bundle(self, bundle_id: str) -> dict[str, bytes]:
        self._live()
        check_id(bundle_id)
        return _read_tree(self.root / "bundles" / bundle_id, bundle_id)

    def put_deployment(self, deployment: Deployment, files: Mapping[str, bytes]) -> bool:
        self._live()
        check_id(deployment.id)
        for key in files:
            check_file_key(key)
        if "deployment.json" in files:
            raise ValueError("deployment.json is the deployment's own document, not a rendered file")
        return _write_tree(
            self.root / "deployments" / deployment.id,
            {"deployment.json": dumps(documents.encode(deployment)), **files},
        )

    def get_deployment(self, deployment_id: str) -> tuple[Deployment, dict[str, bytes]]:
        self._live()
        check_id(deployment_id)
        files = _read_tree(self.root / "deployments" / deployment_id, deployment_id)
        doc = json.loads(files.pop("deployment.json"))
        return deployment.decode(doc), files

    def _twin_path(self, name: str) -> Path:
        self._live()
        check_twin_name(name)
        return self.root / "twins" / f"{name}.json"

    def _read_twin(self, name: str) -> TwinRecord:
        try:
            return twin_record.decode(json.loads(self._twin_path(name).read_bytes()))
        except FileNotFoundError:
            raise NotFound(name) from None

    def list_twins(self) -> list[TwinRecord]:
        self._live()
        names = sorted(p.stem for p in (self.root / "twins").glob("*.json"))
        twins = []
        for name in names:
            try:
                twins.append(self._read_twin(name))
            except NotFound:  # deleted since the listing began
                continue
        return twins

    def get_twin(self, name: str) -> TwinRecord:
        return self._read_twin(name)

    def create_twin(self, record: TwinRecord) -> TwinRecord:
        self._live()
        check_twin_name(record.name)
        if record.revision != 1:
            raise ValueError(f"a new twin record is at revision 1, not {record.revision}")
        with self._mutex:
            if not _write_new(self._twin_path(record.name), dumps(documents.encode(record))):
                raise Conflict(f"twin {record.name} exists")
            self._subscribers.notify(Change("ADDED", record))
        return record

    def _check(self, name: str, expected_revision: int) -> TwinRecord:
        current = self._read_twin(name)
        if current.revision != expected_revision:
            raise Conflict(f"twin {name} is at revision {current.revision}, not {expected_revision}")
        return current

    def update_twin(self, record: TwinRecord, expected_revision: int) -> TwinRecord:
        with self._mutex:
            self._check(record.name, expected_revision)
            written = dataclasses.replace(record, revision=expected_revision + 1)
            _write_atomic(self._twin_path(record.name), dumps(documents.encode(written)))
            self._subscribers.notify(Change("MODIFIED", written))
        return written

    def delete_twin(self, name: str, expected_revision: int) -> None:
        with self._mutex:
            current = self._check(name, expected_revision)
            self._twin_path(name).unlink()
            _fsync_directory(self.root / "twins")
            self._subscribers.notify(Change("DELETED", current))

    def subscribe(self) -> Subscription:
        self._live()
        return self._subscribers.subscribe()

    def _run_path(self, run_id: str) -> Path:
        self._live()
        check_run_id(run_id)
        return self.root / "runs" / f"{run_id}.json"

    def _events_path(self, run_id: str) -> Path:
        self._live()
        check_run_id(run_id)
        return self.root / "runs" / f"{run_id}.events.ndjson"

    def create_run(self, run: Run) -> None:
        if not _write_new(self._run_path(run.id), dumps(documents.encode(run))):
            raise Conflict(f"run {run.id} exists")

    def get_run(self, run_id: str) -> Run:
        try:
            return documents.decode(Run, json.loads(self._run_path(run_id).read_bytes()))
        except FileNotFoundError:
            raise NotFound(run_id) from None

    def update_run(self, run: Run, expected_state: State) -> None:
        with self._mutex:
            current = self.get_run(run.id)
            if current.state != expected_state:
                raise Conflict(f"run {run.id} is {current.state}, not {expected_state}")
            _write_atomic(self._run_path(run.id), dumps(documents.encode(run)))

    def list_runs(self, twin: str | None = None) -> list[Run]:
        self._live()
        ids = sorted((p.stem for p in (self.root / "runs").glob("*.json")), reverse=True)
        runs = [self.get_run(i) for i in ids]
        return [r for r in runs if twin is None or r.twin == twin]

    def append_event(self, run_id: str, event: Event) -> Event:
        with self._mutex:
            if not self._run_path(run_id).exists():
                raise NotFound(run_id)
            path = self._events_path(run_id)
            created = not path.exists()
            with path.open("a+b") as f:
                size = f.seek(0, os.SEEK_END)
                window = _TAIL
                while True:  # widen until the last whole line is known whole, or the file's start is reached
                    start = max(0, size - window)
                    f.seek(start)
                    data = f.read()
                    cut = data.rfind(b"\n") + 1
                    before = data[: max(cut - 1, 0)].rfind(b"\n") + 1  # where the last whole line starts
                    if start == 0 or (cut and data.find(b"\n") < cut - 1):
                        break
                    window *= 2
                if cut != len(data):  # a core killed mid-append left a fragment: cut it
                    f.truncate(start + cut)
                last = json.loads(data[before:cut])["seq"] if cut else 0
                stored = dataclasses.replace(event, seq=last + 1)
                f.seek(0, os.SEEK_END)
                f.write((json.dumps(documents.encode(stored), sort_keys=True) + "\n").encode())
                f.flush()
                os.fsync(f.fileno())
            if created:
                _fsync_directory(path.parent)
            return stored

    def events(self, run_id: str, after: int = 0) -> list[Event]:
        if not self._run_path(run_id).exists():
            raise NotFound(run_id)
        try:
            data = self._events_path(run_id).read_bytes()
        except FileNotFoundError:
            return []
        lines = data.split(b"\n")[:-1]  # the last fragment has no newline: not yet whole
        events = [documents.decode(Event, json.loads(line)) for line in lines]
        return [e for e in events if e.seq > after]

    def close(self) -> None:
        """Release the store's lock; closing twice is harmless."""
        self._closed = True
        if self._lock_fd is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None
