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

from fylgja_core import blueprint, deployment, documents, twin_record
from fylgja_core.deployment import Deployment
from fylgja_core.store import Change, Conflict, Locked, NotFound, Store, Subscription
from fylgja_core.twin_record import TwinRecord

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
    with temp.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
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


def _json(doc: Any) -> bytes:
    return (json.dumps(doc, sort_keys=True, indent=1) + "\n").encode()


class LocalStore(Store):
    """The state store as a directory."""

    def __init__(self, root: Path, lock_fd: int | None = None) -> None:
        self.root = Path(root)
        self._lock_fd = lock_fd
        self._mutex = threading.Lock()  # compare-and-set, and the order of notifications
        self._subscriptions: list[Subscription] = []

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
        os.ftruncate(fd, 0)
        os.pwrite(fd, str(os.getpid()).encode(), 0)
        return cls(root, fd)

    def put_blueprint(self, doc: Mapping[str, Any]) -> tuple[str, bool]:
        bid = blueprint.blueprint_id(dict(doc))
        return bid, _write_new(self.root / "blueprints" / f"{bid}.json", _json(doc))

    def get_blueprint(self, blueprint_id: str) -> dict[str, Any]:
        try:
            doc: dict[str, Any] = json.loads((self.root / "blueprints" / f"{blueprint_id}.json").read_bytes())
        except FileNotFoundError:
            raise NotFound(blueprint_id) from None
        return doc

    def put_bundle(self, bundle_id: str, files: Mapping[str, bytes]) -> bool:
        return _write_tree(self.root / "bundles" / bundle_id, files)

    def get_bundle(self, bundle_id: str) -> dict[str, bytes]:
        return _read_tree(self.root / "bundles" / bundle_id, bundle_id)

    def put_deployment(self, deployment: Deployment, files: Mapping[str, bytes]) -> bool:
        return _write_tree(
            self.root / "deployments" / deployment.id,
            {"deployment.json": _json(documents.encode(deployment)), **files},
        )

    def get_deployment(self, deployment_id: str) -> tuple[Deployment, dict[str, bytes]]:
        files = _read_tree(self.root / "deployments" / deployment_id, deployment_id)
        doc = json.loads(files.pop("deployment.json"))
        return deployment.decode(doc), files

    def _twin_path(self, name: str) -> Path:
        return self.root / "twins" / f"{name}.json"

    def _read_twin(self, name: str) -> TwinRecord:
        try:
            return twin_record.decode(json.loads(self._twin_path(name).read_bytes()))
        except FileNotFoundError:
            raise NotFound(name) from None

    def _notify(self, change: Change) -> None:
        for subscription in self._subscriptions:
            subscription.queue.put_nowait(change)

    def list_twins(self) -> list[TwinRecord]:
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
        if record.revision != 1:
            raise ValueError(f"a new twin record is at revision 1, not {record.revision}")
        with self._mutex:
            if not _write_new(self._twin_path(record.name), _json(documents.encode(record))):
                raise Conflict(f"twin {record.name} exists")
            self._notify(Change("ADDED", record))
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
            _write_atomic(self._twin_path(record.name), _json(documents.encode(written)))
            self._notify(Change("MODIFIED", written))
        return written

    def delete_twin(self, name: str, expected_revision: int) -> None:
        with self._mutex:
            current = self._check(name, expected_revision)
            self._twin_path(name).unlink()
            _fsync_directory(self.root / "twins")
            self._notify(Change("DELETED", current))

    def subscribe(self) -> Subscription:
        subscription = Subscription(self._unsubscribe)
        with self._mutex:
            self._subscriptions.append(subscription)
        return subscription

    def _unsubscribe(self, subscription: Subscription) -> None:
        with self._mutex:
            if subscription in self._subscriptions:
                self._subscriptions.remove(subscription)

    def close(self) -> None:
        """Release the store's lock; closing twice is harmless."""
        if self._lock_fd is not None:
            os.close(self._lock_fd)  # closing the descriptor drops the flock
            self._lock_fd = None
