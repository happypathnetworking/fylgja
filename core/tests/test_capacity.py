"""Admission by capacity (D-073): the fit rule, the pending demand and the shortfall sentences, pure."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from fylgja_core.capacity import (
    NOTHING,
    Host,
    Reading,
    Resources,
    added,
    demand_of,
    pending,
    shortfalls,
    with_demand,
)
from fylgja_core.deployment import Demand

SRC = Path(__file__).resolve().parents[1] / "src" / "fylgja_core"


def H(name: str, cpu: float, memory_mb: int, free_cpu: float, free_memory_mb: int) -> Host:
    return Host(name, Resources(cpu, memory_mb), Resources(free_cpu, free_memory_mb))


def D(nodes: int, cpu: float, memory_mb: int) -> Demand:
    return Demand(nodes=nodes, cpu=cpu, memory_mb=memory_mb)


R3 = Reading(
    (H("h1", 8.0, 24000, 7.7, 23540), H("h2", 8.0, 24000, 7.7, 23680), H("h3", 8.0, 24000, 7.9, 23808)),
    NOTHING,
)
TWIN = {"verb": "The twin needs", "where": "cluster"}


def test_the_readings_free_is_the_sum_and_the_roomiest_has_the_most_memory() -> None:
    assert R3.free.cpu == pytest.approx(23.3)
    assert R3.free.memory_mb == 71028
    assert R3.roomiest is not None and R3.roomiest.name == "h3"
    empty = Reading((), NOTHING)
    assert empty.free == Resources(0.0, 0)
    assert empty.roomiest is None


def test_nothing_is_the_one_zero_demand() -> None:
    assert Demand(nodes=0, cpu=0.0, memory_mb=0) == NOTHING


def test_pending_floors_each_twin_at_zero_and_sums() -> None:
    recorded = D(3, 1.5, 6144)
    assert pending([(recorded, NOTHING), (recorded, D(2, 1.0, 4096)), (recorded, D(5, 2.5, 10240))]) == D(4, 2.0, 8192)
    assert pending([]) == NOTHING


def test_added_is_what_a_step_adds_floored_at_zero() -> None:
    assert added(D(4, 2.0, 8192), D(3, 1.5, 6144)) == D(1, 0.5, 2048)
    assert added(D(2, 1.0, 4096), D(3, 1.5, 6144)) == NOTHING
    demand = D(4, 2.0, 8192)
    assert added(demand, None) == demand


def test_a_twin_that_fits_has_no_shortfall() -> None:
    nodes = [(f"n{i}", Resources(0.5, 2048)) for i in range(15)]
    assert shortfalls(R3, D(15, 7.5, 30720), nodes, **TWIN) == []


def test_the_sum_shortfalls_name_the_need_the_free_and_the_pending() -> None:
    busy = dataclasses.replace(R3, pending=D(6, 3.0, 12288))
    assert shortfalls(busy, D(42, 21.0, 73728), [], **TWIN) == [
        "The twin needs 21 CPUs, and the cluster has 23.3 free with 3 pending.",
        "The twin needs 73728 MiB of memory, and the cluster has 71028 MiB free with 12288 MiB pending.",
    ]
    assert shortfalls(busy, D(36, 18.0, 73728), [], **TWIN) == [
        "The twin needs 73728 MiB of memory, and the cluster has 71028 MiB free with 12288 MiB pending.",
    ]


def test_a_node_no_host_can_take_is_named_with_the_roomiest() -> None:
    sentence = "The node {} needs {} CPUs and {} MiB, and the roomiest host, h3, has 7.9 CPUs and 23808 MiB free."
    assert shortfalls(R3, D(1, 0.5, 30000), [("big", Resources(0.5, 30000))], **TWIN) == [
        sentence.format("big", "0.5", "30000")
    ]
    assert shortfalls(R3, D(1, 0.5, 30000), [("wide", Resources(8.5, 1024))], **TWIN) == [
        sentence.format("wide", "8.5", "1024")
    ]


def test_two_hosts_each_short_of_one_resource_refuse_the_node() -> None:
    reading = Reading((H("h1", 8.0, 24000, 8.0, 1024), H("h2", 8.0, 24000, 0.4, 24000)), NOTHING)
    assert shortfalls(reading, D(1, 0.5, 2048), [("n", Resources(0.5, 2048))], **TWIN) == [
        "The node n needs 0.5 CPUs and 2048 MiB, and the roomiest host, h2, has 0.4 CPUs and 24000 MiB free."
    ]


def test_the_step_verb_and_the_host_word() -> None:
    reading = Reading((H("host", 10.0, 31066, 1.5, 4000),), NOTHING)
    assert shortfalls(reading, D(1, 2.0, 1024), [], verb="The step adds", where="host") == [
        "The step adds 2 CPUs, and the host has 1.5 free with 0 pending."
    ]


def test_demand_round_trips_through_the_allocation() -> None:
    allocation = {"lab": "t", "mgmt_subnet": "172.20.1.0/24"}
    held = with_demand(allocation, D(3, 1.5, 6144))
    assert held == {**allocation, "demand": {"nodes": 3, "cpu": 1.5, "memory_mb": 6144}}
    assert allocation == {"lab": "t", "mgmt_subnet": "172.20.1.0/24"}
    assert demand_of(held) == D(3, 1.5, 6144)
    assert demand_of({"lab": "t"}) is None
    with pytest.raises(ValueError):
        demand_of({"demand": {"nodes": "3"}})


def test_capacity_is_pure() -> None:
    """Constitution V: no I/O, clock or environment, held by the imports."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse((SRC / "capacity.py").read_text())):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            imported.add(node.module)
    allowed = {"__future__", "collections.abc", "dataclasses", "typing", "fylgja_core.deployment"}
    assert imported <= allowed, imported - allowed


def test_a_demand_of_nothing_has_no_shortfall_whatever_the_room() -> None:
    # a tight local host reads a negative free once the up twins' demand is counted
    reading = Reading((Host("h1", Resources(1.0, 1000), Resources(-0.5, -100)),), NOTHING)
    step = {"verb": "The step adds", "where": "host"}
    assert shortfalls(reading, NOTHING, [], **step) == []
    assert shortfalls(reading, D(1, 0.5, 0), [], **step) == [
        "The step adds 0.5 CPUs, and the host has -0.5 free with 0 pending."
    ]
