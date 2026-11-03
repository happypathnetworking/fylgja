"""The state store: the one interface behind which every record lives (Constitution IX,
D-024, D-041).

The core keeps no state of its own and no database: blueprints, bundles and deployments by
their content-addressed ids, twin records by name, and runs with their events. The local
store (`local_store`) is a directory; a production store is S3-compatible object storage
behind this same interface. The interface is synchronous.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from fylgja_core.deployment import Deployment
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


@dataclass(frozen=True)
class Change:
    """One twin write, as a watcher sees it: the record as written (as last stored, for a delete)."""

    type: Literal["ADDED", "MODIFIED", "DELETED"]
    record: TwinRecord


class Subscription:
    """A watcher's queue of every twin change written while it is open, in write order."""

    def __init__(self, on_close: Callable[[Subscription], None]) -> None:
        self.queue: asyncio.Queue[Change] = asyncio.Queue()
        self._on_close = on_close

    def close(self) -> None:
        """Stop delivering to the queue."""
        self._on_close(self)


class Store(ABC):
    """Every record the core keeps."""

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
        returns whether it was created."""

    @abstractmethod
    def get_bundle(self, bundle_id: str) -> dict[str, bytes]:
        """The bundle's files by path, or `NotFound`."""

    @abstractmethod
    def put_deployment(self, deployment: Deployment, files: Mapping[str, bytes]) -> bool:
        """File a deployment document and its rendered files under its id; returns whether
        it was created."""

    @abstractmethod
    def get_deployment(self, deployment_id: str) -> tuple[Deployment, dict[str, bytes]]:
        """The deployment and its rendered files by path, or `NotFound`."""

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
        """A queue that every later twin create, update and delete is put on, in write order."""

    # Run methods follow (Task 5).

    @abstractmethod
    def close(self) -> None:
        """Release whatever the store holds."""
