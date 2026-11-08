"""`changes` held to the pods' uids on the k3s cluster (D-057): clabernetes has no dry run, so the
cluster is the oracle of what a step does to each node. The twin `chg-k8s` is applied from
`three-node` by the session's driver, then stepped through every kind of change the step
fixtures hold (testdata/blueprint/steps/README.md), each fixture and back, a probe added, moved
and removed, and a kind change. For each step `changes` answers before the apply, and each node's
pod's uid is read before the apply and after it returns: a node `kept` or `recabled` keeps its
uid, one `restarted` or `recreated` has another, one `added` has a uid where it had none, and one
`removed` has none. The answers are the ones the pure tier lists for each pair
(`core/tests/test_clabernetes_changes.py`); a disagreement here is a fault of `changes` or of
`apply`'s wait, never of the test.

A node's uid is its pod's, the part of `inspect`'s incarnation before the `/` (D-069): a step
replaces pods, it restarts no container in place.

Then the twin `hot-k8s` runs `mixed`, and steps to `mixed-e2-port`, a port added after boot to
two cEOS nodes, which `apply` recreates itself (D-057): first through a driver whose reach is
`Killing`, which stops the apply at its first pod deletion as a kill would, then through the
session's driver, which finishes what the Topology's annotation names; the replaced nodes list
the port.

The tests run in order and share each twin; each prints what it took and saw (`-s`), the
Topology's status and the pods across each apply among it. Each twin is destroyed at the
module's end whatever happened, and its namespace deleted through `kube`. Nothing of the site is
printed, a failure's message included: no address, host, CIDR or credential. An assertion
compares first and asserts on a bool or on names, since pytest prints the values an assertion
compared.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncGenerator, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from test_clabernetes_changes import REVERSED, ROWS, SWAPPED

from cluster.conftest import Site, gated, run, say, until, watching
from fylgja_core import blueprint, compiler, mapping, packages, probe_package
from fylgja_core.clabernetes import namespace_of
from fylgja_core.clabernetes.driver import RECREATE_ANNOTATION, ClabernetesDriver
from fylgja_core.clabernetes.kube import Kube, LightKube, Namespace, Pod, Service
from fylgja_core.credentials import Provider
from fylgja_core.driver import Allocation, Changes, DriverFailed, Exec, Inspection, Planned, Refusal

ROOT = Path(__file__).resolve().parents[3]
LOADED = packages.load([ROOT / "psp", ROOT / "probes"])
PLATFORMS, PROBES = LOADED.platforms, LOADED.probes
TWIN, HOT = "chg-k8s", "hot-k8s"
EXEC_TIMEOUT_S = 30.0
EOS_WAIT_S = 240.0
"""How long a test waits for EOS's CLI to list the port, from the apply's return."""
SHOW_STATUS = ["Cli", "-p", "15", "-c", "show interfaces status"]
ETHERNET10 = re.compile(r"^Et10\s", re.MULTILINE)
GONE_S = 180.0

Answer = tuple[str, tuple[str, ...]]


@dataclass
class Stepped:
    """A twin the tests step: its allocation, what it runs (`current`, planned from the fixture
    `name`, set once an apply returns), and the last deployment an apply was started with
    (`attempted`, so the teardown can destroy a twin whose apply failed)."""

    twin: str
    allocation: Allocation | None = None
    current: Planned | None = None
    name: str = ""
    attempted: Planned | None = None


class Killed(Exception):
    """An `apply` stopped at its first pod deletion, as a kill of the core would stop it."""


class Killing:
    """`Kube` over `kube`: every call passed to it, but the first `delete_pod`, which raises `Killed`."""

    def __init__(self, kube: Kube) -> None:
        self.kube = kube
        self.killed = False

    async def apply(self, obj: Mapping[str, Any]) -> None:
        await self.kube.apply(obj)

    async def namespace(self, name: str) -> Namespace | None:
        return await self.kube.namespace(name)

    async def topology(self, namespace: str, name: str) -> Mapping[str, Any] | None:
        return await self.kube.topology(namespace, name)

    async def pods(self, namespace: str, labels: Mapping[str, str]) -> list[Pod]:
        return await self.kube.pods(namespace, labels)

    async def services(self, namespace: str) -> list[Service]:
        return await self.kube.services(namespace)

    async def patch_service(self, namespace: str, name: str, patch: Mapping[str, Any]) -> None:
        await self.kube.patch_service(namespace, name, patch)

    async def delete_pod(self, namespace: str, name: str) -> None:
        if not self.killed:
            self.killed = True
            raise Killed(f"killed at the deletion of the pod {name}")
        await self.kube.delete_pod(namespace, name)

    async def delete_namespace(self, name: str) -> None:
        await self.kube.delete_namespace(name)

    async def exec(self, namespace: str, pod: str, argv: Sequence[str], timeout_s: float) -> Exec:
        return await self.kube.exec(namespace, pod, argv, timeout_s)

    def watch_pods(self, labels: Mapping[str, str]) -> AsyncGenerator[tuple[str, Pod]]:
        return self.kube.watch_pods(labels)


def compiled(name: str) -> compiler.Compiled:
    return compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)


def planned(driver: ClabernetesDriver, t: Stepped, name: str) -> Planned:
    assert t.allocation is not None, f"{t.twin} was never admitted: an earlier test failed"
    c = compiled(name)
    return driver.plan(c.manifest, c.id, PLATFORMS, PROBES, t.twin, t.allocation)


def state_of(loop: asyncio.Runner, driver: ClabernetesDriver, twin: str) -> str:
    """`inspect`'s state for the twin, alone: an `Inspection` holds each node's address."""
    state: str = run(loop, driver.inspect(twin), f"inspect {twin}").state
    return state


def admit(loop: asyncio.Runner, driver: ClabernetesDriver, t: Stepped, name: str) -> None:
    """Admit the twin, absent, for the fixture `name`."""
    before = state_of(loop, driver, t.twin)
    assert before == "absent", f"inspect {t.twin}, before: {before}"
    c = compiled(name)
    allocation = run(loop, driver.admit(c.manifest, PLATFORMS, PROBES, t.twin, []), f"admit {t.twin}")
    if isinstance(allocation, Refusal):
        pytest.fail(f"admit {t.twin} refused: {allocation.rule}")
    t.allocation = allocation


def apply(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, t: Stepped, name: str, p: Planned,
          what: str) -> None:
    t.attempted = p
    applying = driver.apply(p.deployment, p.files, PLATFORMS, PROBES)
    run(loop, watching(kube, namespace_of(t.twin), t.twin, applying, what), what)
    t.current, t.name = p, name


def destroy(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, t: Stepped) -> None:
    p = t.current
    assert p is not None, f"{t.twin} runs nothing to destroy: an earlier test failed"
    run(loop, driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"destroy {t.twin}")
    absent = run(loop, driver.inspect(t.twin), f"inspect {t.twin}") == Inspection("absent", ())
    assert absent, f"inspect {t.twin} is not absent"
    assert run(loop, kube.namespace(namespace_of(t.twin)), "namespace") is None
    t.current = None


def uids(loop: asyncio.Runner, driver: ClabernetesDriver, twin: str) -> dict[str, str]:
    """Each node's pod's uid, from `inspect`'s incarnation; every node is running."""
    inspection = run(loop, driver.inspect(twin), f"inspect {twin}")
    state = inspection.state
    assert state == "present", f"inspect {twin}: {state}"
    lacking = [n.name for n in inspection.nodes if not (n.running and n.incarnation)]
    assert not lacking, f"not running, or with no incarnation: {lacking}"
    return {n.name: (n.incarnation or "").split("/")[0] for n in inspection.nodes}


def addresses(loop: asyncio.Runner, driver: ClabernetesDriver, twin: str) -> dict[str, str | None]:
    return {n.name: n.address for n in run(loop, driver.inspect(twin), f"inspect {twin}").nodes}


def short(found: Mapping[str, str]) -> dict[str, str]:
    return {node: value[:8] for node, value in found.items()}


def actions(c: Changes) -> dict[str, Answer]:
    return {n.node: (n.action, n.reasons) for n in c.nodes}


def expected(before: str, after: str) -> dict[str, Answer]:
    """What the pure tier answers for the pair: a row of its table, or a row reversed."""
    for base, target, nodes, *_ in ROWS:
        if (base, target) == (before, after):
            return nodes
        if (target, base) == (before, after):
            return REVERSED.get((base, target), {node: (SWAPPED.get(action, action), reasons)
                                                 for node, (action, reasons) in nodes.items()})
    raise AssertionError(f"the pure tier lists no row for {before} -> {after}")


def held_to_the_pods(answer: Changes, before: Mapping[str, str], now: Mapping[str, str]) -> None:
    """The cluster did what `changes` answered, by each node's pod's uid."""
    for n in answer.nodes:
        if n.action == "added":
            assert n.node in now and n.node not in before, (n, before, now)
        elif n.action == "removed":
            assert n.node in before and n.node not in now, (n, before, now)
        elif n.action in ("kept", "recabled"):
            assert now[n.node] == before[n.node], (n, before, now)
        else:
            assert n.action in ("restarted", "recreated"), n
            assert now[n.node] != before[n.node], (n, before, now)
    assert set(now) == {n.node for n in answer.nodes if n.action != "removed"}
    moved = sorted(node for node in now if node in before and now[node] != before[node])
    say(f"another uid: {moved}")


def step(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, t: Stepped, name: str) -> Changes:
    """Step the twin to the fixture `name`: admit it with the deployment it holds, ask `changes`,
    apply, and hold the answer to the pods' uids and to the pure tier's."""
    current = t.current
    assert current is not None, f"{t.twin} runs nothing to step from: an earlier test failed"
    c = compiled(name)
    after = planned(driver, t, name)
    held = run(loop, driver.admit(c.manifest, PLATFORMS, PROBES, t.twin, [], held=current.deployment),
               f"admit {name} with the held deployment")
    kept = held == t.allocation
    assert kept, f"admit {name} with the held deployment answered another allocation, or refused"
    answer = driver.changes(current, after, PLATFORMS, PROBES)
    before, base = uids(loop, driver, t.twin), t.name
    apply(loop, kube, driver, t, name, after, f"apply {name}")
    now = uids(loop, driver, t.twin)
    say(f"changes {base} -> {name}: {actions(answer)}; links added {answer.links_added}, removed "
        f"{answer.links_removed}")
    say(f"uids before the apply {short(before)}, after its return {short(now)}")
    held_to_the_pods(answer, before, now)
    assert actions(answer) == expected(base, name)
    return answer


def host_ready(loop: asyncio.Runner, driver: ClabernetesDriver, name: str, host: str) -> tuple[str, Exec]:
    """The probe package's readiness command for the probe host `host` of the fixture `name`,
    rendered with `probe_package.host_values` as the loop's ready phase renders it, run inside the
    host until it shows what the package expects, within its readiness budget: the text it is
    ready on, and the last answer."""
    [(package, values)] = [(PROBES[probe.format], probe_package.host_values(PROBES[probe.format], probe, side))
                           for probe in compiled(name).manifest.probes
                           for side, (named, _, _) in zip("ab", blueprint.hosts(probe), strict=True) if named == host]
    argv = [mapping.render(word, values) for word in package.readiness.command]
    expect = mapping.render(package.readiness.expect, values)
    answer, _ = until(loop, lambda: driver.exec(TWIN, host, argv, EXEC_TIMEOUT_S),
                      lambda a: a.returncode == 0 and expect in a.stdout, package.readiness.timeout_s,
                      f"{host}'s readiness, {argv}, shows {expect}")
    say(f"{host}'s readiness answered status {answer.returncode}, stdout {answer.stdout!r}")
    return expect, answer


def eos_lists_ethernet10(loop: asyncio.Runner, driver: ClabernetesDriver, node: str, returned: float) -> Exec:
    """`show interfaces status` in EOS's CLI on `node` until it answers 0 listing `Et10`, within
    `EOS_WAIT_S` of `returned`, the apply's return; the last answer."""

    async def status() -> Exec | None:
        try:
            return await driver.exec(HOT, node, SHOW_STATUS, EXEC_TIMEOUT_S)
        except DriverFailed:
            return None

    answer, _ = until(loop, status, lambda a: a is not None and a.returncode == 0 and bool(ETHERNET10.search(a.stdout)),
                      EOS_WAIT_S - (time.monotonic() - returned), f"{node}'s CLI lists Et10")
    assert answer is not None
    say(f"{node} lists Et10 {time.monotonic() - returned:.1f} s after the apply returned: "
        f"{[line for line in answer.stdout.splitlines() if line.startswith('Et')]}")
    return answer


def teardown(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, t: Stepped) -> None:
    """Leave the cluster as it was, whatever the tests did: destroy what an apply last started,
    then delete the namespace through `kube` and wait for it to go."""
    if t.attempted is not None:
        p = t.attempted
        try:
            run(loop, driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"teardown: destroy {t.twin}")
        except Exception as e:
            say(f"teardown: destroy {t.twin} failed: {e}")
    namespace = namespace_of(t.twin)
    run(loop, kube.delete_namespace(namespace), f"delete_namespace {namespace} (the module's end)")
    until(loop, lambda: kube.namespace(namespace), lambda found: found is None, GONE_S,
          f"{namespace} gone (the module's end)")


@pytest.fixture(scope="module")
def chg(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver) -> Iterator[Stepped]:
    shared = Stepped(TWIN)
    try:
        yield shared
    finally:
        teardown(loop, kube, driver, shared)


@pytest.fixture(scope="module")
def hot(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver) -> Iterator[Stepped]:
    shared = Stepped(HOT)
    try:
        yield shared
    finally:
        teardown(loop, kube, driver, shared)


def test_01_the_base_deploys(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, chg: Stepped) -> None:
    admit(loop, driver, chg, "three-node")
    apply(loop, kube, driver, chg, "three-node", planned(driver, chg, "three-node"), "apply three-node")
    assert set(uids(loop, driver, TWIN)) == {"n1", "n2", "n3"}


def test_02_a_link_removed(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, chg: Stepped) -> None:
    step(loop, kube, driver, chg, "steps/three-node-unlinked")


def test_03_the_link_added(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, chg: Stepped) -> None:
    step(loop, kube, driver, chg, "three-node")


def test_04_a_node_removed(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, chg: Stepped) -> None:
    step(loop, kube, driver, chg, "steps/two-node")


def test_05_the_node_added(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, chg: Stepped) -> None:
    step(loop, kube, driver, chg, "three-node")


def test_06_a_step_the_cluster_has_nothing_to_do_for(
    loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, chg: Stepped
) -> None:
    # `three-node-n1-disabled` changes a port's configuration alone and renders the same Topology:
    # the apply moves no generation.
    for name in ("steps/three-node-n1-disabled", "three-node"):
        step(loop, kube, driver, chg, name)


def test_07_a_probe_added(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, chg: Stepped) -> None:
    step(loop, kube, driver, chg, "three-node-probed")
    expect, _ = host_ready(loop, driver, "three-node-probed", "n1-loop-a")
    assert expect == "10.1.10.2/24"


def test_08_the_probe_moved(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, chg: Stepped) -> None:
    step(loop, kube, driver, chg, "steps/three-node-probed-moved")
    # The moved host's start-up lines ran anew in its new pod: its new address, and not its old one.
    expect, ready = host_ready(loop, driver, "steps/three-node-probed-moved", "n1-loop-a")
    assert expect == "10.2.10.2/24" and "10.2.10.2" in ready.stdout and "10.1.10.2" not in ready.stdout


def test_09_the_probe_removed(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, chg: Stepped) -> None:
    step(loop, kube, driver, chg, "three-node")


def test_10_a_kind_change(
    loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, provider: Provider, chg: Stepped
) -> None:
    gated(provider)
    step(loop, kube, driver, chg, "steps/three-node-n3-eos")


def test_11_destroy_leaves_nothing(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver,
                                   chg: Stepped) -> None:
    destroy(loop, kube, driver, chg)


def test_12_mixed_deploys(
    loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, provider: Provider, hot: Stepped
) -> None:
    gated(provider)
    admit(loop, driver, hot, "mixed")
    apply(loop, kube, driver, hot, "mixed", planned(driver, hot, "mixed"), "apply mixed")
    assert set(uids(loop, driver, HOT)) == {"e1", "e2", "s1"}


def test_13_a_port_added_after_boot_is_killed_before_its_deletions_and_resumed_and_both_nodes_list_it(
    site: Site, loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, provider: Provider, hot: Stepped,
    caplog: pytest.LogCaptureFixture,
) -> None:
    gated(provider)
    current, applied_name = hot.current, hot.name
    assert current is not None and applied_name == "mixed", "mixed was never applied: an earlier test failed"
    name, namespace = "steps/mixed-e2-port", namespace_of(HOT)
    after = planned(driver, hot, name)
    answer = driver.changes(current, after, PLATFORMS, PROBES)
    say(f"changes mixed -> {name}: {actions(answer)}; links added {answer.links_added}")
    assert actions(answer) == expected("mixed", name)
    before, held_at = uids(loop, driver, HOT), addresses(loop, driver, HOT)

    caplog.set_level(logging.INFO, logger="fylgja.clabernetes")
    started = time.time()
    killing = ClabernetesDriver(Killing(kube), provider, controller_namespace=site.controller_namespace,
                                pod_cidr=site.pod_cidr)
    hot.attempted = after
    with pytest.raises(Killed):
        run(loop, watching(kube, namespace, HOT, killing.apply(after.deployment, after.files, PLATFORMS, PROBES),
                           f"apply {name}, killed"), f"apply {name} through Killing, until its first pod deletion")
    topology = run(loop, kube.topology(namespace, HOT), "topology")
    assert topology is not None
    pending = json.loads((topology["metadata"].get("annotations") or {})[RECREATE_ANNOTATION])
    say(f"the Topology's {RECREATE_ANNOTATION} after the kill: {short(pending)}")
    assert pending == {"e1": before["e1"], "e2": before["e2"]}
    assert uids(loop, driver, HOT) == before

    apply(loop, kube, driver, hot, name, after, f"apply {name} again, by the session's driver")
    returned = time.monotonic()
    now = uids(loop, driver, HOT)
    say(f"uids before the killed apply {short(before)}, after the resumed one {short(now)}")
    held_to_the_pods(answer, before, now)
    for record in caplog.records:
        if record.name == "fylgja.clabernetes" and record.created >= started:
            say(f"+{record.created - started:7.2f} s {record.getMessage()}")
    topology = run(loop, kube.topology(namespace, HOT), "topology")
    removed = topology is not None and RECREATE_ANNOTATION not in (topology["metadata"].get("annotations") or {})
    assert removed, f"the Topology is absent, or still carries {RECREATE_ANNOTATION}"
    now_at = addresses(loop, driver, HOT)
    moved = sorted(node for node in {*now_at, *held_at} if now_at.get(node) != held_at.get(node))
    assert not moved, f"the addresses of {moved} moved"
    for node in ("e1", "e2"):
        eos_lists_ethernet10(loop, driver, node, returned)


def test_14_destroy_leaves_nothing(
    loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, provider: Provider, hot: Stepped
) -> None:
    gated(provider)
    destroy(loop, kube, driver, hot)
