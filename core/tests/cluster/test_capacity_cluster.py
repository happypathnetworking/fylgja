"""The clabernetes driver's reading of the cluster's room on the k3s cluster (D-073): `capacity(reserved)`
through the driver the server makes, with no twin up and then with the twin `cap-k8s`, `steps/two-node.json`
compiled with the shipped packages, admitted, planned and applied by the driver.

The test prints each host's figures, by its place in the list and never by name, and what it read of
the room before and after the twin; design/verified-facts.md records the readings. The module destroys
the twin at its end, whatever happened, then deletes its namespace through `kube` and waits for it to go.
Nothing of the site is printed: no address, host or CIDR.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

from cluster.conftest import run, say, until
from fylgja_core import blueprint, compiler, packages
from fylgja_core.capacity import NOTHING, Reading
from fylgja_core.clabernetes import namespace_of
from fylgja_core.clabernetes.driver import ClabernetesDriver
from fylgja_core.clabernetes.kube import LightKube
from fylgja_core.deployment import Demand
from fylgja_core.driver import Allocation, Planned, Refusal

ROOT = Path(__file__).resolve().parents[3]
LOADED = packages.load([ROOT / "psp", ROOT / "probes"])
PLATFORMS, PROBES = LOADED.platforms, LOADED.probes
TWIN = "cap-k8s"
NS = namespace_of(TWIN)
GONE_S = 180.0


def compiled() -> compiler.Compiled:
    return compiler.compile(blueprint.load(ROOT / "testdata/blueprint/steps/two-node.json"), PLATFORMS, PROBES)


def show(what: str, reading: Reading) -> None:
    """Each host's figures, by its place in the list, then the sums and what is pending."""
    for place, host in enumerate(reading.hosts, start=1):
        say(f"{what}: host {place}: total {host.total.cpu:g} CPU and {host.total.memory_mb} MiB, "
            f"free {host.free.cpu:g} CPU and {host.free.memory_mb} MiB")
    say(f"{what}: {len(reading.hosts)} hosts, free {reading.free.cpu:g} CPU and {reading.free.memory_mb} MiB, "
        f"pending {reading.pending.nodes} nodes, {reading.pending.cpu:g} CPU and {reading.pending.memory_mb} MiB")


@pytest.fixture(scope="module")
def twin(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver) -> Iterator[list[Planned]]:
    """The planned deployment of the twin, once the test has admitted it; the module's end destroys it."""
    made: list[Planned] = []
    try:
        yield made
    finally:
        try:
            if made:
                p = made[0]
                run(loop, driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"teardown: destroy {TWIN}")
        except Exception as e:  # the namespace is deleted below whatever happened
            say(f"teardown: destroy {TWIN} failed: {type(e).__name__}")
        finally:
            run(loop, kube.delete_namespace(NS), f"delete_namespace {NS} (the module's end)")
            until(loop, lambda: kube.namespace(NS), lambda found: found is None, GONE_S,
                  f"{NS} gone (the module's end)")


def test_the_reading_is_the_clusters_allocatable_less_requests(
    loop: asyncio.Runner, driver: ClabernetesDriver, twin: list[Planned]
) -> None:
    before = run(loop, driver.capacity([]), "capacity, no twin up")
    show("no twin up", before)
    assert len(before.hosts) == 3, f"the cluster has {len(before.hosts)} hosts, not 3"
    assert all(h.total.cpu == 8.0 for h in before.hosts), "a host's total CPU is not 8"
    assert all(7.0 < h.free.cpu < 8.0 for h in before.hosts), "a host's free CPU is not within (7, 8)"
    assert all(21000 < h.free.memory_mb < 24100 for h in before.hosts), "a host's free memory is not within range"
    assert before.pending == NOTHING, "something is pending with nothing reserved"

    c = compiled()
    admitted = run(loop, driver.admit(c.manifest, PLATFORMS, PROBES, TWIN, []), f"admit {TWIN}")
    assert not isinstance(admitted, Refusal), f"admit refused the twin: {admitted}"
    allocation: Allocation = admitted
    assert allocation["demand"] == {"nodes": 2, "cpu": 1.0, "memory_mb": 4096}, "the demand is not the twin's"
    p = driver.plan(c.manifest, c.id, PLATFORMS, PROBES, TWIN, allocation)
    twin.append(p)

    # Reserved and not yet applied, its whole demand is pending.
    queued = run(loop, driver.capacity([allocation]), "capacity, the twin admitted and not applied")
    show("admitted, not applied", queued)
    assert queued.pending == Demand(nodes=2, cpu=1.0, memory_mb=4096), "the twin's demand is not all pending"

    run(loop, driver.apply(p.deployment, p.files, PLATFORMS, PROBES), f"apply {TWIN}")
    after = run(loop, driver.capacity([allocation]), "capacity, the twin up")
    show("twin up", after)
    fallen = before.free.memory_mb - after.free.memory_mb
    say(f"free memory fell by {fallen} MiB")
    assert abs(fallen - 4096) <= 64, "the free memory did not fall by the twin's 4096 MiB, within 64"
    assert after.pending == NOTHING, "something is still pending once every pod runs"
