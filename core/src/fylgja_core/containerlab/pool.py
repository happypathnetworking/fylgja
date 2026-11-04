"""The local driver's management subnet pool (D-043). Pure: reading Docker's networks is the live half's."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from ipaddress import IPv4Network

DEFAULT_POOL = ipaddress.IPv4Network("172.20.0.0/16")


def choose(pool: IPv4Network, taken: Iterable[IPv4Network]) -> IPv4Network | None:
    """The first /24 of `pool`, in address order, that overlaps no network in `taken`; None when none is free."""
    held = list(taken)
    for subnet in pool.subnets(new_prefix=24):
        if not any(subnet.overlaps(other) for other in held):
            return subnet
    return None


def allocation(twin: str, subnet: IPv4Network) -> dict[str, str]:
    """The local driver's allocation for `twin`: its lab name and management subnet."""
    return {"lab": twin, "mgmt_subnet": str(subnet)}
