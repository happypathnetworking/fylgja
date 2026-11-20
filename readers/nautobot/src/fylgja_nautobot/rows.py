"""The rows: what Nautobot answered, as typed, frozen values, never its JSON (D-034, D-118).

Each row holds what Nautobot returned, and None where it returned null; ids are Nautobot's UUIDs, held as text. A list
is a `Listing`, which keeps beside its items the `count` Nautobot answered for it, and `incomplete` holds the two to
each other: a list that is not whole is refused, never mapped. `Source` is every call the read makes of Nautobot, so
the read runs alike against Nautobot and against rows built in a test. The rows are premises taken from
design/verified-facts.md; the transport's reading of each list corrects them where it must.
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
    """A list Nautobot answered: what it lists, by Nautobot's object type (`dcim.device`), the `count` Nautobot gave
    for it, and the items read."""

    what: str
    count: int
    items: tuple[T, ...]


@dataclass(frozen=True)
class Tag:
    """A tag: its id and its name."""

    id: str
    name: str


@dataclass(frozen=True)
class Device:
    """A device: its id, its name, None where it has none, and its platform's id, None where it has none."""

    id: str
    name: str | None
    platform: str | None


@dataclass(frozen=True)
class Platform:
    """A platform: its id, its name, and its manufacturer's id, None where it has none."""

    id: str
    name: str
    manufacturer: str | None


@dataclass(frozen=True)
class Manufacturer:
    """A manufacturer: its id and its name."""

    id: str
    name: str


@dataclass(frozen=True)
class Port:
    """An interface of a device, whatever its type: its id, its device's id, its name, its type's value
    (`1000base-t`), `enabled` and `mgmt_only` as Nautobot holds them, and its cable's id, None where it has none."""

    id: str
    device: str
    name: str
    type: str
    enabled: bool
    mgmt_only: bool
    cable: str | None


@dataclass(frozen=True)
class End:
    """A termination of a cable: its object's type (`dcim.interface`), its object's id, and its object's display
    text, None where Nautobot answered none."""

    kind: str
    id: str
    display: str | None


@dataclass(frozen=True)
class Cable:
    """A cable: its id, its label, None where it is empty, and the terminations of its two sides, `a` then `b`."""

    id: str
    label: str | None
    a: tuple[End, ...]
    b: tuple[End, ...]


@dataclass(frozen=True)
class Context:
    """A configuration context: its id, its name, whether it is active, and its `data` as Nautobot answered it,
    whatever JSON it is."""

    id: str
    name: str
    active: bool
    data: Any


@dataclass(frozen=True)
class Rendered:
    """What Golden Config answered a device's render: the HTTP status; for 200, the `intended_config` where it is
    text; for any other status, the `detail` where it is text, the token replaced and the words uncut."""

    status: int
    text: str | None
    detail: str | None


@dataclass(frozen=True)
class Change:
    """A row of Nautobot's changelog: its id, a UUID, which orders nothing, and its `time` as Nautobot answered it, to
    the microsecond."""

    id: str
    time: str


@dataclass(frozen=True)
class Setting:
    """A Golden Config setting: its id, its name, its weight, the id of its template repository, its
    `jinja_repository`, None where it names none, and the id of the dynamic group of devices it applies to."""

    id: str
    name: str
    weight: int
    repository: str | None
    group: str


@dataclass(frozen=True)
class Repository:
    """A Git repository: its id, its name, and its `current_head`, the commit Nautobot last saved for it, empty where
    it was never synced."""

    id: str
    name: str
    head: str


@dataclass(frozen=True)
class Group:
    """A dynamic group: its id, its name, its `group_type` as `kind` (`dynamic-filter`), and its `filter` as Nautobot
    answered it, whatever JSON it is."""

    id: str
    name: str
    kind: str
    filter: Any


class Source(Protocol):
    """Every call the read makes of Nautobot. `version` is Nautobot's own, `golden_config` the Golden Config app's,
    None where Nautobot's status names none, and `unverified` the warning every result carries where the pair is not one
    the reader was verified on, None where it is."""

    version: str
    golden_config: str | None
    unverified: Finding | None

    def tags(self, name: str) -> Listing[Tag]:
        """Every tag named `name`."""
        ...

    def devices(self, tag: Tag) -> Listing[Device]:
        """Every device that carries `tag`."""
        ...

    def platforms(self, ids: Sequence[str]) -> Listing[Platform]:
        """The platforms whose ids are `ids`."""
        ...

    def manufacturers(self, ids: Sequence[str]) -> Listing[Manufacturer]:
        """The manufacturers whose ids are `ids`."""
        ...

    def ports(self, devices: Sequence[str]) -> Listing[Port]:
        """Every interface, whatever its type, of the devices whose ids are `devices`."""
        ...

    def cables(self, ids: Sequence[str]) -> Listing[Cable]:
        """The cables whose ids are `ids`."""
        ...

    def contexts(self, name: str) -> Listing[Context]:
        """Every configuration context named `name`."""
        ...

    def render(self, device: str) -> Rendered:
        """What Golden Config renders for the device whose id is `device`."""
        ...

    def newest(self) -> tuple[int, Change | None]:
        """The changelog's total count and its newest row, None where it holds none."""
        ...

    def settings(self) -> Listing[Setting]:
        """Every Golden Config setting."""
        ...

    def repositories(self, ids: Sequence[str]) -> Listing[Repository]:
        """The Git repositories whose ids are `ids`."""
        ...

    def groups(self, ids: Sequence[str]) -> Listing[Group]:
        """The dynamic groups whose ids are `ids`."""
        ...

    def stored(self, group: str, devices: Sequence[str]) -> Listing[str]:
        """The ids of the devices, among `devices`, stored as the members of the dynamic group whose id is `group`."""
        ...

    def matching(
        self, filter: Sequence[tuple[str, str]], devices: Sequence[str], group: str | None = None
    ) -> Listing[Device]:
        """The devices, among `devices`, that the device list answers asked with `filter`, a filter's parameters, of
        the dynamic group named `group` where it is given."""
        ...


def incomplete(listing: Listing[Any], *, asked: Collection[str] | None = None) -> Finding | None:
    """`read.incomplete` where `listing` holds other than the `count` Nautobot answered for it, or one object twice, or
    no object of an id of `asked`, the ids it was read by, so that it is not the whole list; None where it is whole.
    An item is an object by its `id`, or the object's id itself where it is text (a group's stored member)."""
    ids = [item if isinstance(item, str) else item.id for item in listing.items]
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
    return Finding(
        rule=RULE_INCOMPLETE,
        severity="error",
        object=listing.what,
        message=(
            f"Nautobot counted {listing.count} in {listing.what} and answered {len(ids)}{again}{lacking}, "
            "so the list is not whole."
        ),
    )
