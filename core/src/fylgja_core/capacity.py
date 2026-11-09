"""Admission by capacity (D-073). Pure: reading the runtime's room is each driver's half.

A demand fits when `demand.cpu <= sum(free.cpu) - pending.cpu` and
`demand.memory_mb <= sum(free.memory_mb) - pending.memory_mb`, `pending` being what twins already
admitted have yet to take. For a create, every node's package resources must also fit the roomiest
host: `node.cpu <= roomiest.free.cpu and node.memory_mb <= roomiest.free.memory_mb`.

A step checks the sum alone, over what it adds. Its `admit` is given the held deployment and not the
nodes it adds, and a per-node check over every node of the target would refuse a step that adds
nothing on a full cluster, whose running nodes already hold their room.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fylgja_core.deployment import Demand

LOCAL_HOST = "host"
DEMAND = "demand"

NOTHING = Demand(nodes=0, cpu=0.0, memory_mb=0)
"""No demand: what a twin holds of the runtime while none of its nodes is up."""


@dataclass(frozen=True)
class Resources:
    """An amount of CPU and memory."""

    cpu: float
    memory_mb: int


@dataclass(frozen=True)
class Host:
    """One host of the runtime: its total room and what is free of it now."""

    name: str
    total: Resources
    free: Resources


@dataclass(frozen=True)
class Reading:
    """The runtime's room as `admit` would take it: its hosts, and the demand admitted twins have yet to take."""

    hosts: tuple[Host, ...]
    pending: Demand

    @property
    def free(self) -> Resources:
        """The free room summed over the hosts."""
        return Resources(sum(h.free.cpu for h in self.hosts), sum(h.free.memory_mb for h in self.hosts))

    @property
    def roomiest(self) -> Host | None:
        """The host with the most free memory, free CPU breaking a tie; None when there is no host."""
        if not self.hosts:
            return None
        return max(self.hosts, key=lambda h: (h.free.memory_mb, h.free.cpu))


def demand_of(allocation: Mapping[str, Any]) -> Demand | None:
    """The demand an allocation records; None when it has none (every allocation before phase 7).

    Raises ValueError when the member is malformed.
    """
    if DEMAND not in allocation:
        return None
    member = allocation[DEMAND]
    if not isinstance(member, Mapping):
        raise ValueError(f"the allocation's {DEMAND} is not a mapping: {member!r}")
    nodes, cpu, memory_mb = member.get("nodes"), member.get("cpu"), member.get("memory_mb")
    if (
        not isinstance(nodes, int)
        or isinstance(nodes, bool)
        or not isinstance(memory_mb, int)
        or isinstance(memory_mb, bool)
        or not isinstance(cpu, int | float)
        or isinstance(cpu, bool)
    ):
        raise ValueError(f"the allocation's {DEMAND} wants integer nodes and memory_mb and numeric cpu: {member!r}")
    return Demand(nodes=nodes, cpu=float(cpu), memory_mb=memory_mb)


def with_demand(allocation: Mapping[str, Any], demand: Demand) -> dict[str, Any]:
    """A copy of `allocation` recording `demand`."""
    return {**allocation, DEMAND: {"nodes": demand.nodes, "cpu": demand.cpu, "memory_mb": demand.memory_mb}}


def pending(twins: Iterable[tuple[Demand, Demand]]) -> Demand:
    """What admitted twins have yet to take: over `(recorded, held)` pairs, what each adds, floored at zero."""
    todo = [added(recorded, held) for recorded, held in twins]
    return Demand(
        nodes=sum(d.nodes for d in todo),
        cpu=sum(d.cpu for d in todo),
        memory_mb=sum(d.memory_mb for d in todo),
    )


def added(demand: Demand, held: Demand | None) -> Demand:
    """What a step adds to what a twin holds, each component floored at zero; `demand` itself when nothing is held."""
    if held is None:
        return demand
    return Demand(
        nodes=max(0, demand.nodes - held.nodes),
        cpu=max(0.0, demand.cpu - held.cpu),
        memory_mb=max(0, demand.memory_mb - held.memory_mb),
    )


def shortfalls(
    reading: Reading,
    demand: Demand,
    nodes: Sequence[tuple[str, Resources]],
    *,
    verb: str,
    where: str,
) -> list[str]:
    """One sentence per way `demand` does not fit `reading`: CPU, memory, then each node of `nodes` in order.

    `verb` is `The twin needs` or `The step adds`; `where` is `cluster` or `host`. A step passes no nodes.
    A component of zero yields no sentence, so a demand of nothing is admitted whatever the room.
    """
    free, queued = reading.free, reading.pending
    sentences: list[str] = []
    if demand.cpu > 0 and demand.cpu > free.cpu - queued.cpu:
        sentences.append(
            f"{verb} {demand.cpu:g} CPUs, and the {where} has {free.cpu:g} free with {queued.cpu:g} pending."
        )
    if demand.memory_mb > 0 and demand.memory_mb > free.memory_mb - queued.memory_mb:
        sentences.append(
            f"{verb} {demand.memory_mb} MiB of memory, and the {where} has {free.memory_mb} MiB free"
            f" with {queued.memory_mb} MiB pending."
        )
    roomiest = reading.roomiest
    if roomiest is None:  # no host: the sums above already refuse
        return sentences
    for name, need in nodes:
        if need.cpu > roomiest.free.cpu or need.memory_mb > roomiest.free.memory_mb:
            sentences.append(
                f"The node {name} needs {need.cpu:g} CPUs and {need.memory_mb} MiB, and the roomiest host,"
                f" {roomiest.name}, has {roomiest.free.cpu:g} CPUs and {roomiest.free.memory_mb} MiB free."
            )
    return sentences
