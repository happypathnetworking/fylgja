"""`changes` held to containerlab's own dry run (D-049), on real labs. The twin `chg-live` is
deployed through the local driver from `three-node`, then stepped through every kind of change
the step fixtures hold (testdata/blueprint/steps/README.md): each step's `changes` is compared
with the dry run of its topology over the running lab, then the step is applied for real, so
that the next starts from it, and each node's incarnation says whether the lab did what
`changes` answered. Then `mixed` steps to `mixed-e2-port`, the hot-add recreate the dry run
does not name; and `exec` runs inside a probe host, the probe package's own readiness command
among it, rendered as the loop's ready phase renders it, and into a node the lab lacks.

The dry run is `deploy --dry-run --format json` of the new topology, written to a directory of
its own so that the driver's copy is untouched until the apply, with `CLAB_LABDIR_BASE` at the
twin's directory, where containerlab keeps the lab's state (verified-facts.md, "The dry run").
It is the oracle of what a step does to each node: a disagreement is a driver bug.

The tests run in order and share the lab; each prints what it took and what it saw (`-s`). The
module destroys the twin at its end, whatever happened.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Awaitable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from fylgja_core import blueprint, compiler, mapping, platform_package, probe_package
from fylgja_core.containerlab import cli
from fylgja_core.containerlab.driver import DOCKER_DAEMON_ERRORS, ContainerlabDriver
from fylgja_core.containerlab.plan import TOPOLOGY
from fylgja_core.driver import Allocation, Changes, DriverFailed, Exec, Inspection, Planned, Refusal

ROOT = Path(__file__).resolve().parents[3]
PLATFORMS = {p.id: p for p in map(platform_package.load, sorted((ROOT / "psp").glob("*.yaml")))}
PROBES = {p.format: p for p in map(probe_package.load, sorted((ROOT / "probes").glob("*.yaml")))}
TWIN = "chg-live"
CEOS = "ceos:4.32.0.2F"
NODE_LISTS = ("added-nodes", "deleted-nodes", "recreated-nodes", "restarted-nodes", "started-nodes")
DRY_RUN_TIMEOUT_S = 60
EXEC_TIMEOUT_S = 30.0
EOS_WAIT_S = 240.0
"""How long a test waits for EOS's CLI to answer, from the apply's return."""

ETHERNET10 = "show interfaces Ethernet10 status"


@dataclass
class Lab:
    """What the tests share: the driver, the twin's allocation, what it runs now (`current`, set
    once an apply returns), the last deployment an apply was started with (`attempted`, set
    before it runs and never cleared, so the teardown can destroy a lab whose apply failed), and
    the directory the dry runs read their topology from."""

    driver: ContainerlabDriver
    allocation: Allocation
    dry: Path
    current: Planned | None = None
    attempted: Planned | None = None


@dataclass(frozen=True)
class Stepped:
    """One step: what `changes` answered, the dry run's plan, and when the apply started (wall
    clock, as a log record's `created`) and what it took."""

    changes: Changes
    plan: dict[str, Any]
    apply_started: float
    apply_s: float


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


def ceos_present() -> bool:
    return docker("image", "inspect", CEOS, check=False).returncode == 0


def needs_ceos() -> None:
    if not ceos_present():
        pytest.skip(f"the cEOS image {CEOS} is not on the host (docker image inspect fails): import it to run "
                    "the kind change and the hot-add")


def leftovers() -> dict[str, Any]:
    """What the host holds of the twin: its containers by label, its lines of /etc/hosts (the
    block's markers and any line naming a `clab-chg-live-` container), its ssh config and its
    network."""
    names = docker("ps", "-a", "--filter", f"label=containerlab={TWIN}", "--format", "{{.Names}}").stdout.split()
    hosts = Path("/etc/hosts").read_text(errors="replace").splitlines()
    marked = {f"###### CLAB-{TWIN}-START ######", f"###### CLAB-{TWIN}-END ######"}
    lines = [line for line in hosts
             if line.strip() in marked or any(n.startswith(f"clab-{TWIN}-") for n in line.split()[1:])]
    return {
        "containers": names,
        "hosts": lines,
        "ssh_config": Path(f"/etc/ssh/ssh_config.d/clab-{TWIN}.conf").exists(),
        "network": docker("network", "inspect", f"clab-{TWIN}", check=False).returncode == 0,
    }


CLEAN = {"containers": [], "hosts": [], "ssh_config": False, "network": False}


def compiled(name: str) -> compiler.Compiled:
    return compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)


def planned(lab: Lab, c: compiler.Compiled) -> Planned:
    return lab.driver.plan(c.manifest, c.id, PLATFORMS, PROBES, TWIN, lab.allocation)


def apply(lab: Lab, p: Planned, what: str) -> None:
    lab.attempted = p
    run(lab.driver.apply(p.deployment, p.files, PLATFORMS, PROBES), what)
    lab.current = p


def destroy(lab: Lab) -> None:
    p = lab.current
    assert p is not None, "the twin runs nothing to destroy: an earlier test failed"
    run(lab.driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"destroy {TWIN}")
    lab.current = None


def sweep() -> None:
    """The last resort: containerlab's destroy by the lab's name and the network's removal, each
    failure ignored. It leaves the ssh config (verified-facts.md), which the check after it
    reports."""
    for argv in (["containerlab", "destroy", "--name", TWIN, "--cleanup"],
                 ["docker", "network", "rm", f"clab-{TWIN}"]):
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
            print(f"\n[live] teardown: {' '.join(argv)}: rc {done.returncode}")
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"\n[live] teardown: {' '.join(argv)} failed: {e}")


def clean_up(lab: Lab) -> None:
    """Leave the host clean, whatever the tests did: destroy through the driver what an apply
    last started, twice if the host still holds the twin, then sweep it; fail when the host
    still holds any of it. A destroy of a twin already gone does nothing."""
    p = lab.attempted
    for attempt in (1, 2):
        if p is not None:
            try:
                run(lab.driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"teardown: destroy {TWIN}")
            except Exception as e:
                print(f"\n[live] teardown: destroy {TWIN} failed: {e}")
        left = leftovers()
        print(f"\n[live] teardown, attempt {attempt}: the host holds {left}")
        if left == CLEAN:
            return
    sweep()
    left = leftovers()
    if left != CLEAN:
        pytest.fail(f"the teardown left {TWIN} on the host: {left}", pytrace=False)


def incarnations(lab: Lab) -> dict[str, str | None]:
    """Each node's incarnation; every node is running."""
    inspection = run(lab.driver.inspect(TWIN), f"inspect {TWIN}")
    assert inspection.state == "present", inspection
    assert all(n.running for n in inspection.nodes), inspection.nodes
    return {n.name: n.incarnation for n in inspection.nodes}


def actions(c: Changes) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {n.node: (n.action, n.reasons) for n in c.nodes}


def exec_in(lab: Lab, node: str, argv: Sequence[str], timeout_s: float = EXEC_TIMEOUT_S) -> Exec:
    return run(lab.driver.exec(TWIN, node, argv, timeout_s), f"exec {node} {' '.join(argv)}")


def dry_run(lab: Lab, after: Planned) -> dict[str, Any]:
    """containerlab's plan for deploying `after`'s topology over the running lab. Its own
    stdout; the child's environment is the
    allow-list's, as the driver's is."""
    topology = lab.dry / TOPOLOGY
    topology.write_bytes(after.files[TOPOLOGY])
    env = cli.environment(os.environ)
    env["CLAB_LABDIR_BASE"] = str(lab.driver._directory(TWIN))  # where the driver deploys the lab from
    start = time.monotonic()
    done = subprocess.run(["containerlab", "deploy", "--dry-run", "--format", "json", "-t", str(topology)],
                          capture_output=True, text=True, timeout=DRY_RUN_TIMEOUT_S, env=env, cwd=lab.dry, check=False)
    print(f"\n[live] dry run: rc {done.returncode} in {time.monotonic() - start:.2f} s")
    assert done.returncode == 0, done.stderr[-2000:]
    plan: dict[str, Any] = json.loads(done.stdout)
    print(f"[live] dry run's plan: {json.dumps(plan, sort_keys=True)}")
    # deployed-lab false: the dry run found the running lab, so its lists are a reconcile's, not
    # a fresh deploy's (whose lists are all null).
    assert plan["dry-run"] is True and plan["deployed-lab"] is False, plan
    return plan


def listed(plan: dict[str, Any], key: str) -> set[str]:
    """A node list of the plan; containerlab writes an empty one as null."""
    return set(plan.get(key) or [])


def held_to_dry_run(c: Changes, plan: dict[str, Any]) -> None:
    """`changes` agrees with the dry run: the nodes added, removed and restarted are its lists;
    a node it recreates for a kind or image change is one the dry run recreates, and the dry run
    recreates no node `changes` answers otherwise; a node recabled or kept is in none of its
    lists; and a hot-add recreate, the deviation D-049 expects, is one it does not name."""
    by = {action: {n.node for n in c.nodes if n.action == action}
          for action in ("kept", "added", "removed", "recabled", "restarted", "recreated", "unsupported")}
    assert by["added"] == listed(plan, "added-nodes")
    assert by["removed"] == listed(plan, "deleted-nodes")
    assert by["restarted"] == listed(plan, "restarted-nodes")
    strong = {n.node for n in c.nodes if n.action == "recreated" and {"kind", "image"} & set(n.reasons)}
    assert strong <= listed(plan, "recreated-nodes")
    assert listed(plan, "recreated-nodes") <= by["recreated"]
    named = {node for key in NODE_LISTS for node in listed(plan, key)}
    assert not (by["recabled"] | by["kept"]) & named, (by, plan)
    hot = {n.node for n in c.nodes if "hot_add" in n.reasons}
    assert not hot & named, (hot, plan)
    unnamed = by["recreated"] - listed(plan, "recreated-nodes")
    print(f"[live] recreated by changes and not named by the dry run (the hot-add deviation): {sorted(unnamed)}")
    assert unnamed <= hot, (unnamed, plan)
    assert not by["unsupported"], by


def held_to_the_lab(c: Changes, before: dict[str, str | None], now: dict[str, str | None]) -> None:
    """The lab did what `changes` answered: an added node is new, a removed one gone, a kept or
    recabled one the same incarnation, and a restarted or recreated one a new incarnation."""
    for n in c.nodes:
        if n.action == "added":
            assert n.node in now and n.node not in before, n
        elif n.action == "removed":
            assert n.node in before and n.node not in now, n
        elif n.action in ("kept", "recabled"):
            assert now[n.node] == before[n.node], (n, before, now)
        else:
            assert now[n.node] != before[n.node], (n, before, now)
    assert set(now) == {n.node for n in c.nodes if n.action != "removed"}
    moved = sorted(name for name in now if name in before and now[name] != before[name])
    print(f"[live] new incarnations: {moved}")


def step(lab: Lab, name: str) -> Stepped:
    """Step the twin to the fixture `name`: admit it with the deployment it holds, compare
    `changes` with the dry run, apply it, and check the lab against `changes`."""
    assert lab.current is not None
    c = compiled(name)
    after = planned(lab, c)
    held = run(lab.driver.admit(c.manifest, PLATFORMS, PROBES, TWIN, [], held=lab.current.deployment),
               f"admit {name} with the held deployment")
    assert held == lab.allocation, held
    answer = lab.driver.changes(lab.current, after, PLATFORMS, PROBES)
    print(f"[live] changes to {name}: {actions(answer)}; links added {answer.links_added}, "
          f"removed {answer.links_removed}")
    plan = dry_run(lab, after)
    held_to_dry_run(answer, plan)
    before = incarnations(lab)
    started, start = time.time(), time.monotonic()
    apply(lab, after, f"apply {name}")
    apply_s = time.monotonic() - start
    held_to_the_lab(answer, before, incarnations(lab))
    return Stepped(changes=answer, plan=plan, apply_started=started, apply_s=apply_s)


def host_ready(lab: Lab, c: compiler.Compiled, host: str) -> tuple[str, Exec]:
    """The probe package's readiness command for the probe host `host` of `c`, rendered with
    `probe_package.host_values` as the loop's ready phase renders it, run inside the host: the
    text it is ready on, and the answer. It prints both."""
    for probe in c.manifest.probes:
        package = PROBES[probe.format]
        for side, (name, _, _) in zip("ab", blueprint.hosts(probe), strict=True):
            if name == host:
                values = probe_package.host_values(package, probe, side)
                argv = [mapping.render(word, values) for word in package.readiness.command]
                expect = mapping.render(package.readiness.expect, values)
                answer = exec_in(lab, host, argv)
                print(f"[live] {host}'s readiness, {argv}, expects {expect!r}: status {answer.returncode}, "
                      f"stdout {answer.stdout!r}, stderr {answer.stderr!r}")
                return expect, answer
    raise AssertionError(f"{host} is no probe host of {c.id}")


def veths(lab: Lab) -> dict[str, str]:
    """`s1`'s ports to `e1` and `e2`, each with its ifindex, from `/sys/class/net`."""
    ports = ("e1-1", "e1-2")
    read = exec_in(lab, "s1", ["cat", *(f"/sys/class/net/{port}/ifindex" for port in ports)])
    assert read.returncode == 0, read
    return dict(zip(ports, read.stdout.split(), strict=True))


def eos(lab: Lab, node: str, command: str) -> Exec:
    return exec_in(lab, node, ["Cli", "-c", command])


def until_eos(lab: Lab, node: str, command: str, answered: re.Pattern[str]) -> tuple[Exec, Exec]:
    """Run `command` in EOS's CLI on `node` until its status is 0 and its stdout matches
    `answered`, for at most `EOS_WAIT_S`; the first answer and the last."""
    start = time.monotonic()
    first = answer = eos(lab, node, command)
    while not (answer.returncode == 0 and answered.search(answer.stdout)) and time.monotonic() - start < EOS_WAIT_S:
        time.sleep(2)
        answer = eos(lab, node, command)
    return first, answer


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Lab]:
    driver = ContainerlabDriver(tmp_path_factory.mktemp("changes-live"))
    c = compiled("three-node")
    allocation = run(driver.admit(c.manifest, PLATFORMS, PROBES, TWIN, []), "admit three-node")
    assert not isinstance(allocation, Refusal), allocation
    shared = Lab(driver=driver, allocation=allocation, dry=tmp_path_factory.mktemp("changes-dry"))
    yield shared
    clean_up(shared)


def test_01_the_base_deploys(lab: Lab) -> None:
    assert leftovers() == CLEAN, "the host holds chg-live already"
    apply(lab, planned(lab, compiled("three-node")), "apply three-node")
    assert set(incarnations(lab)) == {"n1", "n2", "n3"}


def test_02_a_step_the_runtime_has_nothing_to_do_for(lab: Lab) -> None:
    # `three-node-n1-disabled` changes a port's configuration alone, and renders the same
    # topology, as `three-node-unmanaged` does: every node kept, and the dry run names nothing.
    for name in ("steps/three-node-n1-disabled", "three-node"):
        s = step(lab, name)
        assert actions(s.changes) == {"n1": ("kept", ()), "n2": ("kept", ()), "n3": ("kept", ())}
        assert s.changes.links_added == () and s.changes.links_removed == ()
        assert not any(s.plan.get(key) for key in (*NODE_LISTS, "added-links", "deleted-endpoints")), s.plan


def test_03_a_link_removed(lab: Lab) -> None:
    s = step(lab, "steps/three-node-unlinked")
    assert actions(s.changes) == {"n1": ("kept", ()), "n2": ("recabled", ("links",)),
                                  "n3": ("recabled", ("links",))}


def test_04_the_link_added(lab: Lab) -> None:
    s = step(lab, "three-node")
    assert actions(s.changes) == {"n1": ("kept", ()), "n2": ("recabled", ("links",)),
                                  "n3": ("recabled", ("links",))}
    assert s.changes.links_added == (("n2:ethernet-1/2", "n3:ethernet-1/1"),)


def test_05_a_node_removed(lab: Lab) -> None:
    s = step(lab, "steps/two-node")
    assert actions(s.changes) == {"n1": ("recabled", ("links",)), "n2": ("recabled", ("links",)),
                                  "n3": ("removed", ())}


def test_06_the_node_added(lab: Lab) -> None:
    s = step(lab, "three-node")
    assert actions(s.changes) == {"n1": ("recabled", ("links",)), "n2": ("recabled", ("links",)),
                                  "n3": ("added", ())}


def test_07_a_probe_added(lab: Lab) -> None:
    s = step(lab, "three-node-probed")
    assert actions(s.changes) == {"n1": ("recabled", ("links",)), "n2": ("kept", ()), "n3": ("kept", ()),
                                  "n1-loop-a": ("added", ()), "n1-loop-b": ("added", ())}
    for host, address in (("n1-loop-a", "10.1.10.2/24"), ("n1-loop-b", "10.1.11.2/24")):
        expect, ready = host_ready(lab, compiled("three-node-probed"), host)
        assert expect == address
        assert ready.returncode == 0 and expect in ready.stdout, ready


def test_08_exec_in_a_probe_host_and_into_a_node_the_lab_lacks(lab: Lab) -> None:
    ping = exec_in(lab, "n1-loop-a", ["ping", "-c", "1", "-W", "1", "127.0.0.1"])
    print(f"[live] ping: {ping}")
    assert ping.returncode == 0
    assert "1 packets transmitted, 1 packets received, 0% packet loss" in ping.stdout
    false = exec_in(lab, "n1-loop-a", ["false"])
    print(f"[live] false: {false}")
    assert false == Exec(1, "", "")
    start = time.monotonic()
    with pytest.raises(DriverFailed) as raised:
        asyncio.run(lab.driver.exec(TWIN, "n9", ["true"], EXEC_TIMEOUT_S))
    print(f"\n[live] exec into n9, which the lab lacks: {raised.value!r} in {time.monotonic() - start:.2f} s")
    # What docker itself answers, which the driver's rules read (DOCKER_DAEMON_ERRORS, _remove).
    missing = docker("exec", f"clab-{TWIN}-n9", "true", check=False)
    print(f"[live] docker exec into a missing container: status {missing.returncode}, "
          f"stdout {missing.stdout!r}, stderr {missing.stderr!r}")
    assert missing.returncode == 1 and missing.stderr.startswith(DOCKER_DAEMON_ERRORS)
    start = time.monotonic()
    removed = docker("rm", "-f", f"clab-{TWIN}-n9", check=False)
    print(f"[live] docker rm -f of a missing container: status {removed.returncode}, "
          f"stdout {removed.stdout!r}, stderr {removed.stderr!r}, in {time.monotonic() - start:.2f} s")
    assert removed.returncode == 0 or "No such container" in removed.stderr  # the driver's _remove accepts both


def test_09_a_probe_moved(lab: Lab) -> None:
    s = step(lab, "steps/three-node-probed-moved")
    assert actions(s.changes) == {"n1": ("recabled", ("links",)), "n2": ("recabled", ("links",)),
                                  "n3": ("kept", ()), "n1-loop-a": ("recreated", ("exec", "links")),
                                  "n1-loop-b": ("recreated", ("exec", "links"))}
    # The moved hosts' start-up lines ran anew: each shows its new address and not its old one.
    for host, address, old in (("n1-loop-a", "10.2.10.2/24", "10.1.10.2"), ("n1-loop-b", "10.2.11.2/24", "10.1.11.2")):
        expect, ready = host_ready(lab, compiled("steps/three-node-probed-moved"), host)
        assert expect == address
        assert ready.returncode == 0 and expect in ready.stdout and old not in ready.stdout, ready


def test_10_the_probe_removed(lab: Lab) -> None:
    s = step(lab, "three-node")
    assert actions(s.changes) == {"n1": ("kept", ()), "n2": ("recabled", ("links",)), "n3": ("kept", ()),
                                  "n1-loop-a": ("removed", ()), "n1-loop-b": ("removed", ())}


def test_11_a_kind_change(lab: Lab) -> None:
    needs_ceos()
    s = step(lab, "steps/three-node-n3-eos")
    assert actions(s.changes) == {"n1": ("recabled", ("links",)), "n2": ("recabled", ("links",)),
                                  "n3": ("recreated", ("image", "kind", "links"))}
    print(f"[live] the dry run's reasons: {s.plan.get('node-change-reasons')}")


def test_12_destroy_leaves_nothing(lab: Lab) -> None:
    destroy(lab)
    assert leftovers() == CLEAN
    assert run(lab.driver.inspect(TWIN), f"inspect {TWIN}") == Inspection(state="absent", nodes=())


def test_13_mixed_deploys_and_e2_has_no_ethernet10(lab: Lab) -> None:
    needs_ceos()
    c = compiled("mixed")
    allocation = run(lab.driver.admit(c.manifest, PLATFORMS, PROBES, TWIN, []), "admit mixed")
    assert not isinstance(allocation, Refusal), allocation
    lab.allocation = allocation
    apply(lab, planned(lab, c), "apply mixed")
    returned = time.monotonic()
    assert set(incarnations(lab)) == {"e1", "e2", "s1"}
    _, status = until_eos(lab, "e2", "show interfaces status", re.compile(r"^Et1\s", re.MULTILINE))
    print(f"[live] e2's CLI answered {time.monotonic() - returned:.1f} s after the apply: {status}")
    assert status.returncode == 0
    absent = eos(lab, "e2", ETHERNET10)
    print(f"[live] e2, before the step, {ETHERNET10!r}: {absent}")
    assert not re.search(r"^Et10\s", absent.stdout, re.MULTILINE)


def test_14_a_port_added_to_ceos_recreates_both_nodes_with_it(lab: Lab, caplog: pytest.LogCaptureFixture) -> None:
    needs_ceos()
    caplog.set_level(logging.INFO, logger="fylgja.containerlab")
    before = veths(lab)
    s = step(lab, "steps/mixed-e2-port")
    assert actions(s.changes) == {"e1": ("recreated", ("hot_add", "links")),
                                  "e2": ("recreated", ("hot_add", "links")), "s1": ("kept", ())}
    assert s.changes.links_added == (("e1:eth10", "e2:eth10"),)
    for record in caplog.records:
        if record.created >= s.apply_started and record.name == "fylgja.containerlab":
            print(f"[live] apply +{record.created - s.apply_started:6.2f} s: {record.getMessage()}")
    returned = time.monotonic()
    # EOS lists the port at once, its status `unknown`, then `connected` once its agents bring it
    # up: connected at both ends is the port in use, not a veth EOS never lists.
    connected = re.compile(r"^Et10\s+connected\s", re.MULTILINE)
    for node in ("e1", "e2"):
        first, last = until_eos(lab, node, ETHERNET10, connected)
        print(f"[live] {node}'s {ETHERNET10!r}, first: {first}")
        print(f"[live] {node}'s Et10 connected {time.monotonic() - returned:.1f} s after the apply: {last}")
        assert last.returncode == 0 and connected.search(last.stdout), last
    table = eos(lab, "e1", "show interfaces status")
    print(f"[live] e1's ports: {table.stdout}")
    # A veth goes with its peer's namespace, so s1's ports to e1 and e2 are new ones: a new ifindex.
    after = veths(lab)
    print(f"[live] s1's ports to e1 and e2 by ifindex: before the step {before}, after {after}")
    assert set(after) == set(before) == {"e1-1", "e1-2"}
    assert all(after[port] != before[port] for port in after), (before, after)


def test_15_destroy_leaves_nothing(lab: Lab) -> None:
    needs_ceos()
    destroy(lab)
    assert leftovers() == CLEAN
    assert run(lab.driver.inspect(TWIN), f"inspect {TWIN}") == Inspection(state="absent", nodes=())
