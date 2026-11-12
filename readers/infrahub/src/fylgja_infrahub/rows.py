"""The rows: what Infrahub answered, as typed, frozen values, never its JSON (D-034, D-082).

Each row holds strings as Infrahub returned them, and None where it returned null. A list is a `Listing`, which keeps
beside its items the total Infrahub answered for it, and `incomplete` holds the two to each other: a list that is not
whole is refused, never mapped. `Source` is every call the read makes of Infrahub, so the read runs alike against
Infrahub and against rows built in a test.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fylgja_core.findings import Finding

# Rule ids. Callers and tests match on them (rules.md).
RULE_INCOMPLETE = "read.incomplete"


@dataclass(frozen=True)
class Listing[T]:
    """A list Infrahub answered: what it lists (a kind, or a nested list by its owner's name and its field), the
    `count` Infrahub gave for it, and the items read."""

    what: str
    count: int
    items: tuple[T, ...]


@dataclass(frozen=True)
class Attribute:
    """An attribute of a kind in the branch's schema: its kind, whether it is optional, and a dropdown's choices."""

    kind: str
    optional: bool
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Relationship:
    """A relationship of a kind in the branch's schema: its peer's kind, its own kind, its cardinality and whether it
    is optional."""

    peer: str
    kind: str
    cardinality: str
    optional: bool


@dataclass(frozen=True)
class Kind:
    """A node or a generic of the branch's schema: its attributes and relationships by name, and, for a generic, the
    kinds that use it."""

    attributes: Mapping[str, Attribute]
    relationships: Mapping[str, Relationship]
    used_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class Schema:
    """The branch's schema: its hash, and its nodes and generics by kind."""

    hash: str
    nodes: Mapping[str, Kind]
    generics: Mapping[str, Kind]


@dataclass(frozen=True)
class Artifact:
    """A device's artifact: `definition` is its definition's `artifact_name`; the status, the checksum and the storage
    id are None where Infrahub holds none."""

    id: str
    definition: str
    status: str | None
    checksum: str | None
    storage_id: str | None


@dataclass(frozen=True)
class Device:
    """A scoped device: its name in Infrahub, its platform's name and that platform's manufacturer's, each None where
    there is none, and its artifacts."""

    id: str
    name: str
    platform: str | None
    manufacturer: str | None
    artifacts: Listing[Artifact]


@dataclass(frozen=True)
class End:
    """One end of a connector: the endpoint's id and kind, and, where it is an `InterfacePhysical`, its device's id
    and its own name."""

    id: str
    kind: str
    device: str | None
    port: str | None


@dataclass(frozen=True)
class Connector:
    """What a port is connected by: its id, its kind, its label where it has one, and its ends."""

    id: str
    kind: str
    label: str | None
    ends: Listing[End]


@dataclass(frozen=True)
class Port:
    """A physical port of a scoped device: its device's id, its name, its role and status, and its connector where it
    has one."""

    id: str
    device: str
    name: str
    role: str | None
    status: str | None
    connector: Connector | None


@dataclass(frozen=True)
class Content:
    """What Infrahub served for an artifact's storage id: the HTTP status and the bytes."""

    status: int
    body: bytes


@dataclass(frozen=True)
class Stamp:
    """When a node was last written, by which account (its id), and when it was made: the `node_metadata` of the edge
    the node was read through, each None where Infrahub answered null."""

    updated_at: str | None
    updated_by: str | None
    created_at: str | None


@dataclass(frozen=True)
class Generated:
    """A device's artifact as the stale rule reads it: its id; its definition's `artifact_name`; when its checksum was
    last written, the checksum's own `updated_at`, which moves only when the bytes stored differ; and the id of the
    query its definition's transformation renders through. Each None where Infrahub holds none."""

    id: str
    definition: str
    checksum_at: str | None
    query: str | None


@dataclass(frozen=True)
class Stamped:
    """A scoped device's stamps, of every node its configuration renders from but its cables: `own` the device's;
    `shared` its platform's and that platform's manufacturer's node stamps, where it has them, which `head` counts and
    the stale rule does not; `platform_name_at` and `manufacturer_name_at` when the platform's `name` and the
    manufacturer's were last written, None where Infrahub answered none, which is all of the two the configuration
    renders and the stale rule counts (P3-44, P3-46); `interfaces` each of its interfaces of either kind, by id;
    `addresses` each `IpamIPAddress` under an interface's `ip_addresses`, as (the interface's id, the address's id, its
    stamp); and `ids` the id of each of those nodes, the device's first. `artifacts` are its artifacts."""

    id: str
    name: str
    ids: tuple[str, ...]
    own: Stamp
    shared: tuple[Stamp, ...]
    platform_name_at: str | None
    manufacturer_name_at: str | None
    interfaces: Listing[tuple[str, Stamp]]
    addresses: Listing[tuple[str, str, Stamp]]
    artifacts: Listing[Generated]


@dataclass(frozen=True)
class CableEnd:
    """An end of a connector, as the stale rule reads it: the endpoint's id and when its `name` was last written, and,
    where it is an interface, its device's id and when that device's `name` was; each None where Infrahub answered
    none. The far end's two names are what a configuration renders of it, and all the rule reads of it."""

    id: str
    name_at: str | None
    device: str | None
    device_name_at: str | None


@dataclass(frozen=True)
class CableStamp:
    """A connector a scoped device's physical port ends on: its id, the port's, that device's, its stamp on the port's
    `connector` edge, and its ends. A connector is one row for each of its ports read, so two rows may be one cable's,
    and a row is that port's."""

    id: str
    port: str
    device: str
    stamp: Stamp
    ends: Listing[CableEnd]


@dataclass(frozen=True)
class Group:
    """An internal query group: its id, and the id of the account that made it, None where Infrahub answered none."""

    id: str
    created_by: str | None


@dataclass(frozen=True)
class Event:
    """One event of a branch's log: `name` its `event` (`infrahub.node.updated`); `mutated` whether it is a node's own
    write, a `NodeMutatedEvent`; `kind` and `primary` its primary node's kind and id, and `account` its `account_id`,
    each None where Infrahub answered none; `attributes` the names of the attributes it changed and `relationships`
    each relationship it changed, by name, with its peer's id; `related` the ids of its related nodes; and `branch` the
    branch whose log holds it, which every event has."""

    id: str
    name: str
    occurred_at: str
    mutated: bool
    kind: str | None
    primary: str | None
    account: str | None
    attributes: tuple[str, ...]
    relationships: tuple[tuple[str, str | None], ...]
    related: tuple[str, ...]
    branch: str


@dataclass(frozen=True)
class Branch:
    """A branch: its name, and when it was made, `branched_from`."""

    name: str
    branched_from: str


End4 = tuple[str | None, str | None, str | None, str | None]
"""A probe's end: its device's name in Infrahub, its port, its address with its prefix length and its gateway."""


@dataclass(frozen=True)
class Probe:
    """A `FylgjaProbe`: its id, its name, its format, and each end, a then b (`End4`), each None where Infrahub answered
    null, which the read judges (probes.py)."""

    id: str
    name: str | None
    format: str | None
    a: End4
    b: End4


class Source(Protocol):
    """Every call the read makes of Infrahub. `version` is Infrahub's own, and `unverified` the warning every result
    carries where that version is not one the reader was verified on, None where it is. A call given `at` reads the
    branch at that time, sent as given; `at` None sends no time and reads the branch as it stands. A time a row holds
    is one Infrahub answered, and reads as a time (times.parse)."""

    version: str
    unverified: Finding | None

    def schema(self, branch: str) -> Schema:
        """The branch's schema."""
        ...

    def devices(self, branch: str, at: str | None, tag: str) -> Listing[Device]:
        """Every `DcimDevice` that carries the tag `tag`."""
        ...

    def ports(self, branch: str, at: str | None, devices: Sequence[str]) -> Listing[Port]:
        """Every `InterfacePhysical` of the devices whose ids are `devices`."""
        ...

    def content(self, branch: str, at: str | None, storage_id: str) -> Content:
        """The bytes Infrahub stores under `storage_id`."""
        ...

    def stamps(self, branch: str, at: str | None, tag: str) -> Listing[Stamped]:
        """The stamps of every `DcimDevice` that carries the tag `tag`."""
        ...

    def cable_stamps(self, branch: str, at: str | None, devices: Sequence[str]) -> Listing[CableStamp]:
        """The connector of every `InterfacePhysical` that has one, of the devices whose ids are `devices`."""
        ...

    def groups(self, branch: str, at: str | None, queries: Sequence[str]) -> Listing[Group]:
        """Every internal `CoreGraphQLQueryGroup` of the queries whose ids are `queries`."""
        ...

    def events(self, branch: str, logs: Sequence[str], since: str, floor: str | None) -> Listing[Event]:
        """The events of the branches `logs`, read on `branch`'s endpoint, since `since`, newest first: every page
        down to the first that holds an event no later than `floor`, or every page where it is None. The log is read
        as it stands, with no time. Its `count` is how many events those pages should hold by their own `count` and
        `limit`; an event answered twice is kept once, since the log grows while it is paged."""
        ...

    def branch(self, name: str) -> Branch:
        """The branch `name`."""
        ...

    def probes(self, branch: str, at: str | None) -> Listing[Probe]:
        """Every `FylgjaProbe`, which is branch-agnostic, read through the branch's endpoint."""
        ...

    def probe_stamps(self, branch: str, at: str | None) -> Listing[tuple[str, Stamp]]:
        """Every `FylgjaProbe`'s stamp, by its id, read through the branch's endpoint."""
        ...


def _own_id(item: Any) -> Hashable:
    """Which object an item of a list is: its `id`."""
    found: Hashable = item.id
    return found


def incomplete(
    listing: Listing[Any], *, branch: str, at: str | None, key: Callable[[Any], Hashable] = _own_id
) -> Finding | None:
    """`read.incomplete` where `listing` holds other than the `count` Infrahub answered for it, or one object twice,
    so that it is not the whole list; None where it is whole. `key` answers which object an item is, its `id` unless
    another is given: an interface's or an address's in a tuple, or a connector's port, since a connector is listed
    once for each port it ends."""
    ids = [key(item) for item in listing.items]
    repeated = len(ids) - len(set(ids))
    if len(listing.items) == listing.count and not repeated:
        return None
    again = f", {repeated} of them an object it had answered already" if repeated else ""
    when = f"at {at}" if at is not None else "as it stands"
    return Finding(
        rule=RULE_INCOMPLETE,
        severity="error",
        object=listing.what,
        message=(
            f"Infrahub counted {listing.count} in {listing.what} on branch {branch} {when} "
            f"and answered {len(listing.items)}{again}, so the list is not whole."
        ),
    )
