"""The local driver on real labs (D-017, D-018, D-019, D-023, D-043): the `three-node` fixture,
compiled with the shipped packages and planned for the twin `drv-live` on an allocation from
a real `admit`, then `drv-live-2` beside it. The tests run in order and share the labs; each
prints what it took and what it saw (`-s`). The module destroys both twins at its end,
whatever happened.

(The module is not named `test_containerlab_driver.py`: the pure tier's module has that name,
and pytest and mypy each take a test module by its basename.)
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import subprocess
import time
from collections.abc import Awaitable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from fylgja_core import blueprint, compiler, platform_package, probe_package
from fylgja_core.containerlab import pool
from fylgja_core.containerlab.driver import ContainerlabDriver
from fylgja_core.driver import Allocation, Inspection, Planned, Refusal

ROOT = Path(__file__).resolve().parents[3]
PLATFORMS = {p.id: p for p in map(platform_package.load, sorted((ROOT / "psp").glob("*.yaml")))}
PROBES = {p.format: p for p in map(probe_package.load, sorted((ROOT / "probes").glob("*.yaml")))}
TWIN, TWIN_2 = "drv-live", "drv-live-2"
NODES = ("n1", "n2", "n3")


@dataclass
class Lab:
    """What the tests share: the driver, the two twins' allocations and plans, and what they saw."""

    driver: ContainerlabDriver
    allocations: dict[str, Allocation]
    planned: dict[str, Planned]
    admit_s: float
    incarnations: dict[str, str | None] = field(default_factory=dict)


def run[T](awaitable: Awaitable[T], what: str) -> T:
    """`awaitable`'s result, printing what it took."""

    async def timed() -> tuple[T, float]:
        start = time.monotonic()
        result = await awaitable
        return result, time.monotonic() - start

    result, seconds = asyncio.run(timed())
    print(f"\n[live] {what}: {seconds:.2f} s")
    return result


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60, check=check)


def leftovers(twin: str) -> dict[str, Any]:
    """What the host holds of `twin`: its containers by label, its lines of /etc/hosts (the
    block's markers and its nodes' names, exactly), its ssh config and its network."""
    names = docker("ps", "-a", "--filter", f"label=containerlab={twin}", "--format", "{{.Names}}").stdout.split()
    hosts = Path("/etc/hosts").read_text(errors="replace").splitlines()
    exact = {f"clab-{twin}-{node}" for node in NODES}
    marked = {f"###### CLAB-{twin}-START ######", f"###### CLAB-{twin}-END ######"}
    lines = [line for line in hosts if line.strip() in marked or exact & set(line.split()[1:])]
    return {
        "containers": names,
        "hosts": lines,
        "ssh_config": Path(f"/etc/ssh/ssh_config.d/clab-{twin}.conf").exists(),
        "network": docker("network", "inspect", f"clab-{twin}", check=False).returncode == 0,
    }


CLEAN = {"containers": [], "hosts": [], "ssh_config": False, "network": False}


def inspect(lab: Lab, twin: str = TWIN) -> Inspection:
    return run(lab.driver.inspect(twin), f"inspect {twin}")


def apply(lab: Lab, twin: str = TWIN, reconfigure: bool = False) -> None:
    p = lab.planned[twin]
    what = f"apply {twin}" + (" --reconfigure" if reconfigure else "")
    run(lab.driver.apply(p.deployment, p.files, PLATFORMS, PROBES, reconfigure), what)


def destroy(lab: Lab, twin: str = TWIN) -> None:
    p = lab.planned[twin]
    run(lab.driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"destroy {twin}")


def assert_running(lab: Lab, inspection: Inspection, twin: str = TWIN) -> None:
    subnet = ipaddress.ip_network(lab.allocations[twin]["mgmt_subnet"])
    assert inspection.state == "present"
    assert [n.name for n in inspection.nodes] == list(NODES)
    for node in inspection.nodes:
        assert node.running and node.handle == f"clab-{twin}-{node.name}"
        assert node.address is not None and ipaddress.ip_address(node.address) in subnet, node
        assert node.incarnation, node


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Lab]:
    driver = ContainerlabDriver(tmp_path_factory.mktemp("driver-live"))
    c = compiler.compile(blueprint.load(ROOT / "testdata/blueprint/three-node.json"), PLATFORMS, PROBES)
    start = time.monotonic()
    first = asyncio.run(driver.admit(c.manifest, PLATFORMS, PROBES, TWIN, []))
    assert not isinstance(first, Refusal), first
    second = asyncio.run(driver.admit(c.manifest, PLATFORMS, PROBES, TWIN_2, [first]))
    assert not isinstance(second, Refusal), second
    admit_s = time.monotonic() - start
    allocations = {TWIN: first, TWIN_2: second}
    planned = {twin: driver.plan(c.manifest, c.id, PLATFORMS, PROBES, twin, a) for twin, a in allocations.items()}
    shared = Lab(driver=driver, allocations=allocations, planned=planned, admit_s=admit_s)
    yield shared
    for twin in (TWIN, TWIN_2):  # leave the host clean, whatever the tests did
        try:
            destroy(shared, twin)
        except Exception as e:
            print(f"\n[live] teardown: destroy {twin} failed: {e}")


def test_1_admit_reserves_a_subnet_no_docker_network_holds_and_another_for_a_second_twin(lab: Lab) -> None:
    print(f"\n[live] two admits: {lab.admit_s:.2f} s; {lab.allocations}")
    held: list[ipaddress.IPv4Network] = []
    for line in docker("network", "inspect", "--format", "{{json .IPAM.Config}}",
                       *docker("network", "ls", "--format", "{{.ID}}").stdout.split()).stdout.splitlines():
        subnets = [ipaddress.ip_network(c["Subnet"]) for c in json.loads(line) or [] if c.get("Subnet")]
        held += [s for s in subnets if isinstance(s, ipaddress.IPv4Network)]
    first, second = (ipaddress.IPv4Network(lab.allocations[t]["mgmt_subnet"]) for t in (TWIN, TWIN_2))
    assert lab.allocations[TWIN]["lab"] == TWIN and lab.allocations[TWIN_2]["lab"] == TWIN_2
    assert first.subnet_of(pool.DEFAULT_POOL) and second.subnet_of(pool.DEFAULT_POOL)
    assert first.prefixlen == second.prefixlen == 24 and first != second
    assert not any(first.overlaps(h) or second.overlaps(h) for h in held), held


def test_2_apply_deploys_the_twin(lab: Lab) -> None:
    assert leftovers(TWIN) == CLEAN, "the host holds drv-live already"
    apply(lab)
    inspection = inspect(lab)
    assert_running(lab, inspection)
    lab.incarnations = {n.name: n.incarnation for n in inspection.nodes}
    print(f"[live] nodes: {inspection.nodes}")
    endpoints = run(lab.driver.endpoints(TWIN), "endpoints")
    assert endpoints == {n.name: n.address for n in inspection.nodes}
    for node in inspection.nodes:
        labels = json.loads(docker("inspect", "--format", "{{json .Config.Labels}}", node.handle).stdout)
        assert labels["fylgja.twin"] == TWIN and labels["containerlab"] == TWIN
        assert labels["clab-node-name"] == node.name
    print(f"[live] labels of {node.handle}: {sorted(labels.items())}")
    left = leftovers(TWIN)
    print(f"[live] the running lab on the host: {left}")
    assert f"###### CLAB-{TWIN}-START ######" in left["hosts"] and left["ssh_config"] and left["network"]
    directory = lab.driver.root / "containerlab" / TWIN
    assert sorted(p.name for p in directory.iterdir()) == [f"clab-{TWIN}", "topology.clab.yml"]


def test_3_a_repeat_apply_is_a_quick_reconcile_that_restarts_nothing(lab: Lab) -> None:
    start = time.monotonic()
    apply(lab)
    assert time.monotonic() - start < 5
    inspection = inspect(lab)
    assert_running(lab, inspection)
    assert {n.name: n.incarnation for n in inspection.nodes} == lab.incarnations


def test_4_apply_with_reconfigure_redeploys(lab: Lab) -> None:
    apply(lab, reconfigure=True)
    inspection = inspect(lab)
    assert_running(lab, inspection)
    now = {n.name: n.incarnation for n in inspection.nodes}
    changed = sorted(name for name in now if now[name] != lab.incarnations[name])
    print(f"[live] incarnations before {lab.incarnations}, after {now}: changed {changed}")
    lab.incarnations = now


def test_5_destroy_leaves_nothing(lab: Lab) -> None:
    destroy(lab)
    assert leftovers(TWIN) == CLEAN
    assert inspect(lab) == Inspection(state="absent", nodes=())
    assert not (lab.driver.root / "containerlab" / TWIN).exists()


def test_6_the_residue_containers_removed_by_hand_leave_is_deployed_then_destroyed(lab: Lab) -> None:
    apply(lab)
    start = time.monotonic()
    docker("rm", "-f", *(f"clab-{TWIN}-{node}" for node in NODES))
    print(f"\n[live] docker rm -f of three nodes: {time.monotonic() - start:.2f} s")
    left = leftovers(TWIN)
    print(f"[live] what docker rm -f left: {left}")
    assert inspect(lab) == Inspection(state="residue", nodes=())
    destroy(lab)
    assert leftovers(TWIN) == CLEAN
    assert inspect(lab) == Inspection(state="absent", nodes=())


def test_7_two_labs_at_once(lab: Lab) -> None:
    async def both() -> None:
        plans = [lab.planned[t] for t in (TWIN, TWIN_2)]
        await asyncio.gather(*(lab.driver.apply(p.deployment, p.files, PLATFORMS, PROBES) for p in plans))

    run(both(), "apply drv-live and drv-live-2 at once")
    assert_running(lab, inspect(lab, TWIN), TWIN)
    assert_running(lab, inspect(lab, TWIN_2), TWIN_2)
    destroy(lab, TWIN)
    # drv-live-2's host entries name clab-drv-live-2-n1, which begins with clab-drv-live-:
    # drv-live is gone all the same, and its neighbour untouched.
    assert leftovers(TWIN) == CLEAN
    assert inspect(lab, TWIN) == Inspection(state="absent", nodes=())
    assert_running(lab, inspect(lab, TWIN_2), TWIN_2)
    destroy(lab, TWIN_2)
    assert leftovers(TWIN_2) == CLEAN
