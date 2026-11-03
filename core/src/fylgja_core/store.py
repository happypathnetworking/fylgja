"""The state store: the one interface behind which every record lives (Constitution IX,
D-024, D-041).

The core keeps no state of its own and no database: blueprints, bundles and deployments by
their content-addressed ids, twin records by name, and runs with their events. The local
store (`local_store`) is a directory; a production store is S3-compatible object storage
behind this same interface. The interface is synchronous.
"""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from fylgja_core import ulid
from fylgja_core.deployment import Deployment
from fylgja_core.run import Event, Run, State
from fylgja_core.twin_record import TwinRecord


class StoreError(Exception):
    """A store operation that could not be done."""


class NotFound(StoreError):
    """The key names nothing in the store."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"{key} is not in the store")


class Conflict(StoreError):
    """A write that lost: the key exists, or its revision is not the one expected."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class Locked(StoreError):
    """The store is held by another core."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


_ID = re.compile(r"^[0-9a-f]{64}$")
_TWIN_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")


def check_id(key: str) -> str:
    """`key` if it is a content-addressed id (64 lowercase hex digits), else `ValueError`."""
    if not _ID.fullmatch(key):
        raise ValueError(f"{key!r} is not an id (64 lowercase hex digits)")
    return key


def check_run_id(key: str) -> str:
    """`key` if it is a ULID, else `ValueError`."""
    if not ulid.PATTERN.fullmatch(key):
        raise ValueError(f"{key!r} is not a run id (a ULID)")
    return key


def check_twin_name(key: str) -> str:
    """`key` if it is a twin name (twin-record-1's pattern), else `ValueError`."""
    if not _TWIN_NAME.fullmatch(key):
        raise ValueError(f"{key!r} is not a twin name")
    return key


def check_file_key(key: str) -> str:
    """`key` if it is a relative, `/`-separated path with no empty, `.` or `..` segment, else `ValueError`."""
    if not key or any(part in ("", ".", "..") for part in key.split("/")) or "\\" in key or "\0" in key:
        raise ValueError(f"{key!r} is not a relative file path")
    return key


@dataclass(frozen=True)
class Change:
    """One twin write, as a watcher sees it: the record as written (as last stored, for a delete)."""

    type: Literal["ADDED", "MODIFIED", "DELETED"]
    record: TwinRecord


class Subscription:
    """A watcher's queue of every twin change written while it is open, in write order."""

    def __init__(self, loop: asyncio.AbstractEventLoop, on_close: Callable[[Subscription], None]) -> None:
        self.loop = loop  # the loop the watcher runs on: changes are delivered through it
        self.queue: asyncio.Queue[Change] = asyncio.Queue()
        self._on_close = on_close

    def close(self) -> None:
        """Stop delivering to the queue."""
        self._on_close(self)

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class Store(ABC):
    """Every record the core keeps. Keys are checked at this boundary (`check_*`, `ValueError`);
    compare-and-set is thread-safe; after `close` every operation raises `StoreError`."""

    @abstractmethod
    def put_blueprint(self, doc: Mapping[str, Any]) -> tuple[str, bool]:
        """File a validated blueprint document under its id; returns `(id, created)`, and
        `created` is False, with nothing written, when the id already exists."""

    @abstractmethod
    def get_blueprint(self, blueprint_id: str) -> dict[str, Any]:
        """The blueprint document filed under the id, or `NotFound`."""

    @abstractmethod
    def put_bundle(self, bundle_id: str, files: Mapping[str, bytes]) -> bool:
        """File a bundle's files (`manifest.json`, `configs/<node>.cfg`) under its id;
        returns whether it was created. `ValueError` when the id is not the files' own
        (`bundle.bundle_id`), `manifest.json` is missing or a path is not a relative path."""

    @abstractmethod
    def get_bundle(self, bundle_id: str) -> dict[str, bytes]:
        """The bundle's files by path, or `NotFound`; a reader sees every file or `NotFound`."""

    @abstractmethod
    def put_deployment(self, deployment: Deployment, files: Mapping[str, bytes]) -> bool:
        """File a deployment document and its rendered files under its id; returns whether
        it was created."""

    @abstractmethod
    def get_deployment(self, deployment_id: str) -> tuple[Deployment, dict[str, bytes]]:
        """The deployment and its rendered files by path, or `NotFound`; a reader sees every
        file or `NotFound`."""

    @abstractmethod
    def list_twins(self) -> list[TwinRecord]:
        """Every twin record, sorted by name."""

    @abstractmethod
    def get_twin(self, name: str) -> TwinRecord:
        """The twin record, or `NotFound`."""

    @abstractmethod
    def create_twin(self, record: TwinRecord) -> TwinRecord:
        """Store a new twin record, whose revision must be 1 (`ValueError` otherwise);
        `Conflict` when the name exists."""

    @abstractmethod
    def update_twin(self, record: TwinRecord, expected_revision: int) -> TwinRecord:
        """Store `record` at revision `expected_revision + 1` only if the stored revision is
        `expected_revision` (`Conflict` otherwise, `NotFound` when absent); returns it as stored."""

    @abstractmethod
    def delete_twin(self, name: str, expected_revision: int) -> None:
        """Remove the twin record under the same check as `update_twin`."""

    @abstractmethod
    def subscribe(self) -> Subscription:
        """A queue that every later twin create, update and delete is put on, in write order.
        Called on the watcher's event loop; a write may come from any thread."""

    @abstractmethod
    def create_run(self, run: Run) -> None:
        """Store a new run; `Conflict` when its id exists."""

    @abstractmethod
    def get_run(self, run_id: str) -> Run:
        """The run, or `NotFound`."""

    @abstractmethod
    def update_run(self, run: Run, expected_state: State) -> None:
        """Replace the run's whole document only if the stored run's state is `expected_state`
        (`Conflict` otherwise, `NotFound` when it does not exist)."""

    @abstractmethod
    def list_runs(self, twin: str | None = None) -> list[Run]:
        """Every run, or those of one twin, newest first."""

    @abstractmethod
    def append_event(self, run_id: str, event: Event) -> Event:
        """Append the event with the next sequence number, whatever its `seq` says; returns
        it as stored. `NotFound` when the run has no record."""

    @abstractmethod
    def events(self, run_id: str, after: int = 0) -> list[Event]:
        """The run's events with `seq` greater than `after`, in order; `NotFound` when the run
        has no record."""

    @abstractmethod
    def close(self) -> None:
        """Release whatever the store holds."""
