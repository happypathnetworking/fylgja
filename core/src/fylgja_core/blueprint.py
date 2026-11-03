"""Blueprint 1: the core's one input (formats/blueprint-1.schema.json, D-006).

A blueprint is the network (devices, interfaces, links, each device's rendered config) and
its probes. Its id is the SHA-256 of the RFC 8785 (JCS) canonical form of
{"network": ..., "probes": ...}; `blueprint_version` and the opaque `source` are not hashed.
Every list in the hashed body arrives sorted and unique, and the core never sorts on a
client's behalf.

`validate` reports every problem in one pass (Constitution III), each with a stable rule id
and a JSON pointer; `decode` builds the `Blueprint` model from a valid document.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fylgja_core import documents
from fylgja_core.documents import Problem, Rejected

VERSION = "1"

# Rule ids. Clients and tests match on them.
RULE_INVALID = "blueprint.invalid"
RULE_VERSION = "blueprint.version.unsupported"
RULE_UNSORTED = "blueprint.unsorted"
RULE_DUPLICATE = "blueprint.duplicate"
RULE_ENDPOINT_UNKNOWN = "blueprint.link.endpoint.unknown"
RULE_INTERFACE_TWICE = "blueprint.link.interface.shared"
RULE_LINK_MGMT = "blueprint.link.mgmt_only"
RULE_GATEWAY_OUTSIDE = "blueprint.probe.gateway.outside"
RULE_ADDRESS_SHARED = "blueprint.probe.address.shared"


@dataclass(frozen=True, kw_only=True)
class Interface:
    """A device's physical port, by its production name."""

    name: str
    mgmt_only: bool
    enabled: bool


@dataclass(frozen=True, kw_only=True)
class Device:
    """One device in scope, with the configuration its source rendered."""

    name: str
    platform: str
    interfaces: tuple[Interface, ...]
    config: str


@dataclass(frozen=True, kw_only=True)
class Endpoint:
    """One end of a link: a device and one of its interfaces."""

    device: str
    interface: str


@dataclass(frozen=True, kw_only=True)
class Link:
    """A cable with two ends in scope; `a` sorts before `b`."""

    a: Endpoint
    b: Endpoint


@dataclass(frozen=True, kw_only=True)
class Network:
    """The intent the compiler compiles: devices and the links between them."""

    devices: tuple[Device, ...]
    links: tuple[Link, ...]


@dataclass(frozen=True, kw_only=True)
class ProbeEndpoint:
    """Where one probe host is cabled, and its IPv4 address and gateway."""

    device: str
    interface: str
    address: str
    gateway: str


@dataclass(frozen=True, kw_only=True)
class Probe:
    """A probe: two hosts of one format on two uncabled ports. The same definition serves the
    probe declaration (formats/probes-1.schema.json)."""

    name: str
    format: str
    endpoints: tuple[ProbeEndpoint, ProbeEndpoint]


@dataclass(frozen=True, kw_only=True)
class Blueprint:
    """A blueprint 1 document as a model. `source` is the opaque envelope, carried unread."""

    blueprint_version: str = VERSION
    network: Network
    probes: tuple[Probe, ...]
    source: Mapping[str, Any] | None = None


class NotCanonical(ValueError):
    """A value RFC 8785 serialization is not defined for here: a number or a lone surrogate."""


def canonical(value: Any) -> bytes:
    """The RFC 8785 (JCS) canonical UTF-8 bytes of a JSON value of strings, booleans, null,
    arrays and objects. Numbers are refused: a blueprint's hashed body holds none, so JCS's
    number rules never apply."""
    return _jcs(value).encode("utf-8")


def _jcs(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, str):
        if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise NotCanonical("a string holds a lone surrogate")
        # ECMAScript's JSON.stringify escapes as Python's json does with ensure_ascii off:
        # the quote, the backslash, \b \f \n \r \t, and other controls as lowercase \u00xx.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_jcs(v) for v in value) + "]"
    if isinstance(value, dict):
        # Members sort by their names' UTF-16 code units, not by code points.
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(_jcs(k) + ":" + _jcs(value[k]) for k in keys) + "}"
    raise NotCanonical(f"{type(value).__name__} is not part of a blueprint's hashed body")


def blueprint_id(doc: dict[str, Any]) -> str:
    """The blueprint's id: lowercase hex SHA-256 over the canonical network and probes."""
    return hashlib.sha256(canonical({"network": doc["network"], "probes": doc["probes"]})).hexdigest()


def validate(doc: Any) -> list[Problem]:
    """Every problem with `doc` as a blueprint, sorted; an empty list means it is valid."""
    problems = documents.unsupported_version(doc, "blueprint_version", VERSION, RULE_VERSION)
    if problems:
        return problems
    problems = documents.schema_problems("blueprint-1", doc, RULE_INVALID)
    if problems:
        return problems
    network, probes = doc["network"], doc["probes"]
    problems += _order(network["devices"], lambda d: d["name"], "/network/devices")
    for i, device in enumerate(network["devices"]):
        problems += _order(device["interfaces"], lambda f: f["name"], f"/network/devices/{i}/interfaces")
    for i, link in enumerate(network["links"]):
        if _end(link["a"]) >= _end(link["b"]):
            problems.append(Problem(f"/network/links/{i}", RULE_UNSORTED, "a link's a must sort before its b"))
    problems += _order(network["links"], lambda lk: (*_end(lk["a"]), *_end(lk["b"])), "/network/links")
    problems += _order(probes, lambda p: p["name"], "/probes")
    problems += _links(network)
    problems += probe_problems(probes, "/probes", RULE_GATEWAY_OUTSIDE, RULE_ADDRESS_SHARED)
    return sorted(set(problems))


def decode(doc: Any) -> Blueprint:
    """The `Blueprint` a document holds, or `Rejected` with every problem."""
    problems = validate(doc)
    if problems:
        raise Rejected(problems)
    return documents.decode(Blueprint, doc)


def load(path: Path) -> Blueprint:
    """The `Blueprint` in a file, or `Rejected` naming the file."""
    return documents.load(path, RULE_INVALID, decode)


def _end(endpoint: dict[str, str]) -> tuple[str, str]:
    return endpoint["device"], endpoint["interface"]


def _order(items: Sequence[Any], key: Any, pointer: str) -> list[Problem]:
    found = []
    for i in range(1, len(items)):
        before, here = key(items[i - 1]), key(items[i])
        if here == before:
            found.append(Problem(f"{pointer}/{i}", RULE_DUPLICATE, f"{here!r} appears twice"))
        elif here < before:
            found.append(Problem(f"{pointer}/{i}", RULE_UNSORTED, f"{here!r} sorts before {before!r}"))
    return found


def _links(network: dict[str, Any]) -> list[Problem]:
    interfaces = {
        (d["name"], f["name"]): f for d in network["devices"] for f in d["interfaces"]
    }
    found, taken = [], set()
    for i, link in enumerate(network["links"]):
        for side in ("a", "b"):
            end, pointer = _end(link[side]), f"/network/links/{i}/{side}"
            if end not in interfaces:
                found.append(Problem(pointer, RULE_ENDPOINT_UNKNOWN, f"{end[0]}:{end[1]} is no device's interface"))
                continue
            if interfaces[end]["mgmt_only"]:
                found.append(Problem(pointer, RULE_LINK_MGMT, f"{end[0]}:{end[1]} is management-only"))
            if end in taken:
                found.append(Problem(pointer, RULE_INTERFACE_TWICE, f"{end[0]}:{end[1]} ends another link"))
            taken.add(end)
    return found


def probe_problems(probes: list[dict[str, Any]], pointer: str, gateway_rule: str, address_rule: str) -> list[Problem]:
    """The cross-field rules every list of probes keeps, in a blueprint and in a declaration
    alike: a gateway inside its address's prefix, and no two hosts on one address. The rule
    ids are the caller's, since each format names them."""
    found, hosts = [], set()
    for i, probe in enumerate(probes):
        for j, endpoint in enumerate(probe["endpoints"]):
            where = f"{pointer}/{i}/endpoints/{j}"
            address = ipaddress.ip_interface(endpoint["address"])
            if ipaddress.ip_address(endpoint["gateway"]) not in address.network:
                detail = f"{endpoint['gateway']} is outside {address.network}"
                found.append(Problem(f"{where}/gateway", gateway_rule, detail))
            if address.ip in hosts:
                found.append(Problem(f"{where}/address", address_rule, f"{address.ip} is another host's"))
            hosts.add(address.ip)
    return found
