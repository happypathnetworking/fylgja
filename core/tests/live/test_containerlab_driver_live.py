"""The local driver on real labs (D-017, D-018, D-019, D-023, D-043): the `three-node` fixture,
compiled with the shipped packages and planned for the twin `drv-live` on an allocation from
a real `admit`, then `drv-live-2` beside it. The tests run in order and share the labs; each
prints what it took and what it saw (`-s`). The module destroys both twins at its end,
whatever happened. Among them a `destroy` under packages that do not list a node's image, which
is refused and removes nothing (D-102). The eighth test deploys nothing: over a pool of its own,
one /24, it makes a Docker network, and `admit` is refused naming the network and the setting
(D-103); the network is the test's to remove. The last cancels an apply whose deploy is a stream
of `docker create` clients and destroys the twin `drv-cut` at once: the containers the daemon
makes after the kill are removed by the teardown's settle (verified-facts.md, 2026-11-14).

(The module is not named `test_containerlab_driver.py`: the pure tier's module has that name,
and pytest and mypy each take a test module by its basename.)
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import subprocess
import time
from collections.abc import Awaitable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fakes import with_image

from fylgja_core import blueprint, compiler, platform_package, probe_package
from fylgja_core.containerlab import cli, pool
from fylgja_core.containerlab.driver import ContainerlabDriver
from fylgja_core.driver import Allocation, Inspection, Planned, Refusal, Unpackaged

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
    assert sorted(p.name for p in directory.iterdir()) == [f"clab-{TWIN}", "deploy.log", "topology.clab.yml"]
    log = (directory / "deploy.log").read_text(errors="replace")  # D-056: the deploy's output, its table last
    assert "Running postdeploy actions" in log and log.rstrip().endswith("╯"), log[-400:]


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


def test_4b_destroy_under_packages_that_do_not_list_the_image_is_refused_and_removes_nothing(lab: Lab) -> None:
    # D-102's premise, on the running lab: a core whose SR Linux package was edited to another image
    # is asked to destroy the twin that runs the one it had. The driver meets `n1` in its lookup of a
    # node's package, before any command, so the host holds what it held, each container at the
    # incarnation it had; the true packages' destroy, the next test, then removes everything.
    p = lab.planned[TWIN]
    directory = lab.driver.root / "containerlab" / TWIN
    before, nodes, files = leftovers(TWIN), inspect(lab).nodes, sorted(f.name for f in directory.iterdir())
    assert {n.name: n.incarnation for n in nodes} == lab.incarnations
    srl = PLATFORMS["nokia_srlinux"]
    listed = platform_package.image(srl).ref
    moved = {**PLATFORMS, "nokia_srlinux": with_image(srl, ref=listed + "-moved")}
    start = time.monotonic()
    with pytest.raises(Unpackaged) as refused:
        asyncio.run(lab.driver.destroy(p.deployment, p.files, moved, PROBES))
    print(f"\n[live] destroy {TWIN} under a package whose image moved: refused in {time.monotonic() - start:.2f} s: "
          f"{refused.value}")
    assert (refused.value.node, refused.value.kind, refused.value.image) == ("n1", "nokia_srlinux", listed)
    after = inspect(lab).nodes
    print(f"[live] the host after the refusal: {leftovers(TWIN)}; incarnations "
          f"{ {n.name: n.incarnation for n in after} }")
    assert leftovers(TWIN) == before and after == nodes  # each node's incarnation among them
    assert sorted(f.name for f in directory.iterdir()) == files


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
    # No container, and the root-owned residue whole: the hosts block (its two markers and a
    # line per node), the ssh config, and the network.
    assert left["containers"] == []
    assert f"###### CLAB-{TWIN}-START ######" in left["hosts"] and len(left["hosts"]) == 2 + len(NODES)
    assert left["ssh_config"] and left["network"]
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


def test_8_a_pool_a_docker_network_holds_is_refused_naming_it_and_the_setting(tmp_path: Path) -> None:
    # D-103, on Docker itself: a network made over the one /24 of a pool of the test's own, and a driver of its own
    # on that pool, which reads every network of the host as the driver's format prints them (verified-facts.md):
    # a line a network, its name as a JSON string, one space, and its IPAM config, a list, or `null` as for `host`.
    # Nothing is deployed, and no time is held to.
    #
    # It needs 192.0.2.0/24 held by no Docker network of the host, and the name `fylgja-live-pool` free. It leaves
    # nothing: the network is removed whatever the `admit` did. A run killed between the create and the `finally`
    # leaves `fylgja-live-pool`, which is removed by hand (`docker network rm fylgja-live-pool`) before the next run.
    network, held = "fylgja-live-pool", ipaddress.IPv4Network("192.0.2.0/24")
    form = "{{json .Name}} {{json .IPAM.Config}}"
    c = compiler.compile(blueprint.load(ROOT / "testdata/blueprint/three-node.json"), PLATFORMS, PROBES)
    driver = ContainerlabDriver(tmp_path, pool=held)
    docker("network", "create", "--subnet", str(held), network)
    try:
        made = docker("network", "inspect", "--format", form, network).stdout
        host = docker("network", "inspect", "--format", form, "host").stdout
        print(f"\n[live] docker's lines: {made.strip()} | {host.strip()}")
        refused = run(driver.admit(c.manifest, PLATFORMS, PROBES, "pool-live", []), "admit pool-live on a held pool")
    finally:
        removed = docker("network", "rm", network, check=False)
    print(f"[live] the refusal: {refused}")
    assert removed.returncode == 0, removed.stderr
    assert docker("network", "inspect", network, check=False).returncode != 0, "the test's network still stands"
    name, space, config = made.rstrip("\n").partition(" ")
    assert (json.loads(name), space) == (network, " ")
    assert [entry["Subnet"] for entry in json.loads(config)] == [str(held)]
    assert host == '"host" null\n'
    assert isinstance(refused, Refusal) and refused.rule == "admission.capacity"
    assert f"{network} ({held})" in refused.message and "FYLGJA_LAB_POOL" in refused.message
    assert not (tmp_path / "containerlab").exists()  # nothing written, nothing deployed


CUT = "drv-cut"
CUT_CREATES = 30
CUT_EVERY_S = 0.03
CUT_AFTER_S = 0.4
CUT_LEFT_AFTER_S = 10.0


def test_9_a_deploy_killed_mid_create_leaves_nothing_once_its_teardown_has_settled(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A deletion during a create's deploy (verified-facts.md, 2026-11-14): the driver kills the deploy, and the
    creates it had sent run on in the daemon, which lists a container only once it has made it. The teardown after the
    kill settles: it lists the lab until the listing has been empty for `SETTLE_WINDOW_S` (5 s), removing what
    appears.

    The deploy is the driver's own `apply` through `cli.run`, its `containerlab deploy` replaced by a script in the
    same process group: it makes the lab's network, then starts a `docker create` of the SR Linux image every 0.03 s,
    30 of them, each labelled for the lab and named as containerlab names a node, and the apply is cancelled 0.4 s
    after the network stands; the cancel kills the script's group, its `docker create` clients with it, as it kills a
    deploy's. `destroy` follows at once. On this idle host the creates in flight at such a kill were made within about
    0.1 s of it, mostly before the teardown's first listing answered (verified-facts.md, 2026-11-14, the stream of
    `docker create` clients), so the race alone would test the settle only now and then. So that it is tested every
    run, the late container is made certain: once the teardown's first listing has answered, the test starts one
    more `docker create` labelled for the lab (`clab-drv-cut-late`, no network), which the daemon makes after that
    listing, as it made the containers of the cut. Ten seconds after the destroy returns nothing labelled for the
    lab is listed, its network is gone, and the settle is what removed the late container.

    The window rests on these readings, on Docker 29.8.1: a container whose `docker create` client was killed was
    listed 0.1 to 0.6 s after the kill, and in a cut of a create through the core one was not yet listed 0.35 s after
    its `Created`. The window is 8.3 times the slowest, 0.6 s; the 10 s wait after the destroy is twice the window.
    Leaves nothing: every container labelled for the lab and its network are removed whatever happened."""
    image = platform_package.image(PLATFORMS["nokia_srlinux"]).ref
    marker = tmp_path / "network-made"
    script = (f"docker network create clab-{CUT} >/dev/null && : > {marker} && i=0 && "
              f"while [ $i -lt {CUT_CREATES} ]; do "
              f"docker create --label containerlab={CUT} --label clab-node-name=c$i --name clab-{CUT}-c$i "
              f"--network clab-{CUT} {image} >/dev/null 2>&1 & i=$((i+1)); sleep {CUT_EVERY_S}; done; wait")
    listing = ["docker", "ps", "-a", "--filter", f"label=containerlab={CUT}", "--format", "{{.Names}}"]
    late: list[subprocess.Popen[bytes]] = []
    armed = False

    async def runner(argv: list[str], **kw: Any) -> str:
        nonlocal armed
        if argv[:2] == ["containerlab", "deploy"]:
            argv = ["sh", "-c", script]
        answer = await cli.run(argv, **kw)
        if armed and argv == listing:  # the teardown's first listing has answered: the daemon makes one more
            armed = False
            late.append(subprocess.Popen(
                ["docker", "create", "--label", f"containerlab={CUT}", "--label", "clab-node-name=late", "--name",
                 f"clab-{CUT}-late", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        return answer

    driver = ContainerlabDriver(tmp_path / "root", runner=runner)
    c = compiler.compile(blueprint.load(ROOT / "testdata/blueprint/three-node.json"), PLATFORMS, PROBES)
    try:
        assert leftovers(CUT) == CLEAN, f"the host holds {CUT} already"
        allocation = asyncio.run(driver.admit(c.manifest, PLATFORMS, PROBES, CUT, []))
        assert not isinstance(allocation, Refusal), allocation
        p = driver.plan(c.manifest, c.id, PLATFORMS, PROBES, CUT, allocation)

        async def cut() -> float:
            nonlocal armed
            applying = asyncio.ensure_future(driver.apply(p.deployment, p.files, PLATFORMS, PROBES))
            while not marker.exists():
                assert not applying.done(), applying
                await asyncio.sleep(0.005)
            await asyncio.sleep(CUT_AFTER_S)
            applying.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await applying
            armed = True
            start = time.monotonic()
            await driver.destroy(p.deployment, p.files, PLATFORMS, PROBES)
            return time.monotonic() - start

        with caplog.at_level("INFO", logger="fylgja.containerlab"):
            destroy_s = asyncio.run(cut())
        removed = [r.getMessage() for r in caplog.records if "since the daemon made it after" in r.getMessage()]
        print(f"\n[live] killed the deploy {CUT_AFTER_S:g} s after its network; destroy {CUT}: {destroy_s:.2f} s; "
              f"the settle removed {removed}")
        assert late and late[0].wait(timeout=60) == 0, "the late docker create failed"
        time.sleep(CUT_LEFT_AFTER_S)
        left = leftovers(CUT)
        print(f"[live] {CUT_LEFT_AFTER_S:g} s after the destroy: {left}")
        assert left["containers"] == [] and not left["network"], left
        assert any(f"removed clab-{CUT}-late," in message for message in removed), removed
    finally:
        for process in late:  # ended before the lab is listed: a client killed mid-create is the race itself
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                time.sleep(CUT_LEFT_AFTER_S)  # what the daemon was already asked is made after the kill
        names = docker("ps", "-a", "--filter", f"label=containerlab={CUT}", "--format", "{{.Names}}").stdout.split()
        if names:
            docker("rm", "-f", *names, check=False)
        docker("network", "rm", f"clab-{CUT}", check=False)
