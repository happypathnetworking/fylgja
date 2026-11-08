"""Two twins up at once, and TCP refused between them, on a driver that keeps twins apart by the
network (design/core.md, phase 6: the anti-goal "a node of one twin reachable from another twin's
pod"; D-019, D-037, D-059). The twins `cf-iso-a`, created from `three-node-probed`, and
`cf-iso-b`, from `two-node`, are Ready together and each verified, the core reaching both. On
SSH's and gNMI's ports, `cf-iso-a`'s probe host `n1-loop-a` reaches its own twin's `n1` at its
pod's address, the control; it is refused by every path to each node of `cf-iso-b`; a place of
no twin is refused by every path to each device node of both; and the test's own host reaches
each device node at its record's address. Both twins are then destroyed, leaving nothing.

What a path is, and where a place of no twin is, is the harness's (`Harness.reach`): each source
has run 15 s or more before it probes, since a network policy may learn a new source late and
answers ping whatever it says (verified-facts.md), so the probe is a TCP connection. A driver
that keeps twins apart by names alone closes no path between them, and the scenario skips there
with that reason. No address is printed or held in an assertion's message.
"""

from __future__ import annotations

import socket
import time
from typing import Any

import pytest

from conformance.harness import Fylgja, Harness
from conformance.reads import (
    ROOT,
    created,
    destroyed,
    devices,
    ready,
    record_nodes,
    settled,
    twin_nodes,
    verified,
)

ISO_A = "cf-iso-a"
ISO_B = "cf-iso-b"
PROBED = ROOT / "testdata" / "blueprint" / "three-node-probed.json"
TWO_NODE = ROOT / "testdata" / "blueprint" / "steps" / "two-node.json"
SOURCE = (ISO_A, "n1-loop-a")
"""The probe host of `cf-iso-a`: a node of one twin, probing from inside it."""
PORTS = (22, 57400)
"""SSH's and gNMI's: the management ports every device node serves."""
GNMI = 57400
"""gNMI's port, which the test's own host connects to at each device node's record address."""
CONNECT_S = 5.0
"""How long the test's host waits for each connection to a node's record address."""


def accepted_from_here(record: dict[str, Any], node: str) -> str | None:
    """Whether the test's own host connects to `node` at its address in `record`, on gNMI's port:
    None where it does, else why not, by the error's type alone (the address is never shown)."""
    address = record_nodes(record)[node].get("address")
    if not address:
        return "no address in the record"
    began = time.monotonic()
    try:
        with socket.create_connection((str(address), GNMI), timeout=CONNECT_S):
            pass
    except OSError as e:
        return type(e).__name__
    print(f"[conformance] the test's host to {node} of {record['name']} on {GNMI}: accepted in "
          f"{time.monotonic() - began:.2f}s", flush=True)
    return None


def test_two_twins_up_at_once_refuse_each_other_and_a_third_namespace(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    if caps["isolation"] != "network":
        pytest.skip(f"the driver keeps twins apart by {caps['isolation']}, not by the network: no path of one twin is "
                    "closed to another, so there is nothing to refuse")
    created(harness, fylgja, ISO_A, PROBED, twin_nodes(PROBED))
    created(harness, fylgja, ISO_B, TWO_NODE, twin_nodes(TWO_NODE))
    records = {}
    for twin in (ISO_A, ISO_B):
        record = harness.record(twin)
        assert record is not None, f"{twin} is gone"
        # Held as a bool: pytest would explain a False with the record, which holds each node's address.
        ok = ready(record) and settled(record)
        assert ok, f"{twin} is not settled and Ready"
        records[twin] = record
    verified(fylgja, ISO_A, "three-node-probed")
    verified(fylgja, ISO_B, "two-node")

    for port in PORTS:
        control = harness.reach(SOURCE, (ISO_A, "n1"), port)
        assert control.get("pod") is True, \
            f"{SOURCE[1]} of {ISO_A} did not reach its own twin's n1 on {port}: {control}"
        for node in sorted(twin_nodes(TWO_NODE)):
            paths = harness.reach(SOURCE, (ISO_B, node), port)
            assert paths and not any(paths.values()), \
                f"{SOURCE[1]} of {ISO_A} reached {node} of {ISO_B} on {port}: {paths}"
        for twin, fixture in ((ISO_A, PROBED), (ISO_B, TWO_NODE)):
            for node in sorted(devices(fixture)):
                paths = harness.reach(None, (twin, node), port)
                assert paths and not any(paths.values()), \
                    f"a place of no twin reached {node} of {twin} on {port}: {paths}"

    refused = {f"{node} of {twin}": why for twin, fixture in ((ISO_A, PROBED), (ISO_B, TWO_NODE))
               for node in sorted(devices(fixture)) if (why := accepted_from_here(records[twin], node)) is not None}
    assert not refused, f"the test's host did not reach these on {GNMI}: {refused}"

    destroyed(harness, fylgja, ISO_A)
    destroyed(harness, fylgja, ISO_B)
