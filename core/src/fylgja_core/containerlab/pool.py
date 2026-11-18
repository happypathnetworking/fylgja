"""The local driver's management subnet pool (D-043), which the server's settings may move
(D-103). Pure: reading Docker's networks is the live half's."""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterable, Sequence
from ipaddress import IPv4Network

DEFAULT_POOL = ipaddress.IPv4Network("172.20.0.0/16")
"""The pool where the settings give none. This module alone names it."""

VARIABLE = "FYLGJA_LAB_POOL"
"""The server's setting that gives the pool (`config.lab_pool`), which a refusal names."""

FORMAT = "{{json .Name}} {{json .IPAM.Config}}"
"""What the driver asks `docker network inspect --format` for, which `networks` reads: a line a
network, its name as a JSON string, one space, and its IPAM config, a list of objects or `null`
(Docker 29.8.1, verified-facts.md)."""

_PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
"""A network's name that a refusal writes as it is; any other it writes as a JSON string."""


def networks(answered: str) -> list[tuple[str, IPv4Network]]:
    """Each Docker network of `answered`, `docker network inspect`'s answer to `FORMAT`, with each
    IPv4 subnet it holds: a `(name, subnet)` pair a subnet, in the answer's order. A network with
    no IPv4 subnet, as `host` and `none`, gives nothing, and an IPv6 subnet is passed over.

    The answer is split on the newline alone, which ends a network's line: `str.splitlines`
    splits on more, U+0085 among them, and a name that held one would be cut in two. Whether
    Docker lets a name hold one was not read."""
    found = []
    for line in answered.split("\n"):
        if not line.strip():
            continue
        name, end = json.JSONDecoder().raw_decode(line)
        for config in json.loads(line[end:]) or []:
            network = ipaddress.ip_network(config["Subnet"], strict=False) if config.get("Subnet") else None
            if isinstance(network, IPv4Network):
                found.append((str(name), network))
    return found


def choose(pool: IPv4Network, taken: Iterable[IPv4Network]) -> IPv4Network | None:
    """The first /24 of `pool`, in address order, that overlaps no network in `taken`; None when none is free."""
    held = list(taken)
    for subnet in pool.subnets(new_prefix=24):
        if not any(subnet.overlaps(other) for other in held):
            return subnet
    return None


def holders(pool: IPv4Network, networks: Iterable[tuple[str, IPv4Network]]) -> list[tuple[str, IPv4Network]]:
    """The Docker networks that hold part of `pool`: each `(name, subnet)` of `networks` whose
    subnet overlaps it, one wider than the pool among them, sorted by name, then subnet."""
    return sorted((name, subnet) for name, subnet in networks if subnet.overlaps(pool))


def refusal(pool: IPv4Network, holding: Sequence[tuple[str, IPv4Network]]) -> str:
    """What `admit` says of a pool with no free /24 (D-103): that it has none, each Docker network
    of `holding` (`holders`) by its name and subnet, and the setting that moves the pool. With
    no network holding any of it, other twins hold it whole, and the setting is named alone.

    A name of letters, digits, `_`, `.` and `-` after a letter or digit is written as it is; any
    other is written as a JSON string, so that a space, a comma, a parenthesis or a control
    character in a name reaches the finding quoted and escaped, never read as the list's own."""
    held = ""
    if holding:
        named = ", ".join(f"{name if _PLAIN.fullmatch(name) else json.dumps(name)} ({subnet})"
                          for name, subnet in holding)
        held = f" Docker networks holding part of it: {named}."
    return (f"The pool {pool} has no /24 that neither a Docker network nor another twin holds.{held} "
            f"Set {VARIABLE} to an IPv4 network with a free /24, and start the core again.")


def allocation(twin: str, subnet: IPv4Network) -> dict[str, str]:
    """The local driver's allocation for `twin`: its lab name and management subnet."""
    return {"lab": twin, "mgmt_subnet": str(subnet)}
