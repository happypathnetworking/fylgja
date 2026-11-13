"""The rows: what NetBox answered, as typed, frozen values, never its JSON (D-034, D-095).

Each row holds what NetBox returned, and None where it returned null; a cable's label is None where it is empty, as
NetBox answers one never given (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"). A list is a
`Listing`, which keeps beside its items the `count` NetBox answered for it, and `incomplete` holds the two to each
other: a list that is not whole is refused, never mapped. `Source` is every call the read makes of NetBox, so the read
runs alike against NetBox and against rows built in a test.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fylgja_core.findings import Finding

# Rule ids. Callers and tests match on them (rules.md).
RULE_INCOMPLETE = "read.incomplete"


@dataclass(frozen=True)
class Listing[T]:
    """A list NetBox answered: what it lists, by NetBox's object type (`dcim.device`), the `count` NetBox gave for it,
    and the items read."""

    what: str
    count: int
    items: tuple[T, ...]


@dataclass(frozen=True)
class Branch:
    """A branch of the branching plugin: its id, its name, the `schema_id` its header selects it by, its status's
    value (`ready`), and its `last_sync` as NetBox answers it, None where it answers null. A sync moves `last_sync`
    and adds no row to either changelog (design/verified-facts.md, "A sync"), so the bracket reads the branch again
    at the close (bracket.py)."""

    id: int
    name: str
    schema_id: str
    status: str
    last_sync: str | None


@dataclass(frozen=True)
class Change:
    """A row of a changelog, `main`'s or a branch's: its id and its `changed_object_type` (`dcim.interface`)."""

    id: int
    kind: str


@dataclass(frozen=True)
class Tag:
    """A tag: its id and its name."""

    id: int
    name: str


@dataclass(frozen=True)
class Device:
    """A device: its id, its name, None where it has none, and its platform's id, None where it has none."""

    id: int
    name: str | None
    platform: int | None


@dataclass(frozen=True)
class Platform:
    """A platform: its id, its name, and its manufacturer's name, None where it has none."""

    id: int
    name: str
    manufacturer: str | None


@dataclass(frozen=True)
class Port:
    """An interface of a device, whatever its type: its id, its device's id, its name, its type's value
    (`1000base-t`), `enabled` and `mgmt_only` as NetBox holds them, and its cable's id, None where it has none."""

    id: int
    device: int
    name: str
    type: str
    enabled: bool
    mgmt_only: bool
    cable: int | None


@dataclass(frozen=True)
class End:
    """A termination of a cable: its object's type (`dcim.interface`), its object's id, and its object's display
    text, which is a port's name, None where NetBox answered none."""

    kind: str
    id: int
    display: str | None


@dataclass(frozen=True)
class Cable:
    """A cable: its id, its label, None where it is empty, and the terminations of its two sides, `a` then `b`."""

    id: int
    label: str | None
    a: tuple[End, ...]
    b: tuple[End, ...]


@dataclass(frozen=True)
class Context:
    """A configuration context: its id, its name, whether it is active (`is_active`), and its `data` as NetBox answered
    it, whatever JSON it is."""

    id: int
    name: str
    active: bool
    data: Any


@dataclass(frozen=True)
class Rendered:
    """What NetBox answered a device's render: the HTTP status, the bytes, and the content type NetBox gave them, its
    parameters among it (`text/plain; charset=utf-8`), None where it gave none."""

    status: int
    body: bytes
    content_type: str | None


class Source(Protocol):
    """Every call the read makes of NetBox. `version` is NetBox's own, `branching` the branching plugin's, None where
    NetBox names none, and `unverified` the warning every result carries where the pair is not one the reader was
    verified on, None where it is. A call given a branch reads under its header, and one given None reads `main`."""

    version: str
    branching: str | None
    unverified: Finding | None

    def branches(self, name: str) -> Listing[Branch]:
        """Every branch named `name`, read under no branch's header."""
        ...

    def tags(self, branch: Branch | None, name: str) -> Listing[Tag]:
        """Every tag named `name`."""
        ...

    def devices(self, branch: Branch | None, tag: int) -> Listing[Device]:
        """Every device that carries the tag whose id is `tag`."""
        ...

    def platforms(self, branch: Branch | None, ids: Sequence[int]) -> Listing[Platform]:
        """The platforms whose ids are `ids`."""
        ...

    def ports(self, branch: Branch | None, devices: Sequence[int]) -> Listing[Port]:
        """Every interface, whatever its type, of the devices whose ids are `devices`."""
        ...

    def cables(self, branch: Branch | None, ids: Sequence[int]) -> Listing[Cable]:
        """The cables whose ids are `ids`."""
        ...

    def contexts(self, branch: Branch | None, name: str) -> Listing[Context]:
        """Every configuration context named `name`."""
        ...

    def render(self, branch: Branch | None, device: int) -> Rendered:
        """What NetBox renders for the device whose id is `device`."""
        ...

    def latest(self, branch: Branch | None) -> int | None:
        """The highest id of the changelog read from, `main`'s with no branch and the branch's under its header; None
        where it holds no row."""
        ...

    def changes(self, branch: Branch | None, after: int | None) -> Listing[Change]:
        """Every row of that changelog whose id is above `after`, every row where it is None."""
        ...

    def counted(self, branch: Branch | None, upto: int) -> int:
        """How many rows that changelog holds whose id is at or below `upto`."""
        ...


def incomplete(listing: Listing[Any], *, branch: str | None, asked: Collection[int] | None = None) -> Finding | None:
    """`read.incomplete` where `listing` holds other than the `count` NetBox answered for it, or one object twice, or
    no object of an id of `asked`, the ids it was read by, so that it is not the whole list; None where it is whole.
    `branch` is the name of the branch read, None for `main`. An item is an object by its `id`."""
    ids = [item.id for item in listing.items]
    repeated = len(ids) - len(set(ids))
    wanted = set(asked) if asked is not None else set()
    missing = sorted(wanted - set(ids))
    if len(ids) == listing.count and not repeated and not missing:
        return None
    again = f", {repeated} of them an object it had answered already" if repeated else ""
    lacking = (
        f", and no object of {len(missing)} of the {len(wanted)} ids it was asked for, id {missing[0]} the first"
        if missing
        else ""
    )
    where = f"branch {branch}" if branch is not None else "main"
    return Finding(
        rule=RULE_INCOMPLETE,
        severity="error",
        object=listing.what,
        message=(
            f"NetBox counted {listing.count} in {listing.what} on {where} "
            f"and answered {len(ids)}{again}{lacking}, so the list is not whole."
        ),
    )
