"""Verify on a probed twin over real gNMI (D-051, D-052, D-030, D-032). The twin `vfy-live` is
deployed through the local driver from `three-node-probed`, brought up as the loop brings it up
(each device node's push transport, each probe host's readiness command through `exec`, every
node's configuration pushed), and recorded as holding its bundle. Each node's raw gNMI answer
is printed for the paths verify asks, and for paths the node has no value at; a Get with a
login the node refuses is unreadable and quotes no login; each burst runs alone; then
`Verifier.verify` runs with the real reader and the driver's `exec`: `ok`.

Then n3 is stopped, twice. Stopped by `containerlab stop` (its "seamless dataplane"), the
verdict is `failed`, never nonconforming; started by `containerlab start`, n3 keeps its links
and verifies `ok` again. Stopped by `docker stop`, the verdict is `failed` again; started by
`docker start`, n3 no longer lists its data ports, and the verdict is `nonconforming`, each end
of its two links listing no neighbour.

Then, with the cEOS image on the host, `vfy-live-mixed` from `mixed`, its `e1` configuration
edited to name the host `leaf-01`, compiled and pushed as the loop would: the configured node's
host name is reported as `leaf-01`, and the neighbours facing it are judged against that name.

The tests run in order and share the labs; each prints what it took and what it saw (`-s`).
Nothing printed holds a credential or a configuration. The module destroys both twins at its
end, whatever happened.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import subprocess
import time
from collections.abc import Awaitable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from fylgja_core import blueprint, burst, compiler, gnmi, mapping, platform_package, probe_package, push
from fylgja_core.containerlab.driver import ContainerlabDriver
from fylgja_core.containerlab.plan import TOPOLOGY
from fylgja_core.credentials import Credential, Provider
from fylgja_core.driver import Allocation, Inspection, Planned, Refusal
from fylgja_core.findings import Counts, Verdict
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.readiness import await_transport
from fylgja_core.twin_record import Node, Spec, Status, TwinRecord
from fylgja_core.verify import RULE_NODE_UNREAD, RULE_PORT_NEIGHBOR, RULE_SKIPPED, Verifier, paths

ROOT = Path(__file__).resolve().parents[3]
PLATFORMS = {p.id: p for p in map(platform_package.load, sorted((ROOT / "psp").glob("*.yaml")))}
PROBES = {p.format: p for p in map(probe_package.load, sorted((ROOT / "probes").glob("*.yaml")))}
TWIN, MIXED = "vfy-live", "vfy-live-mixed"
CEOS = "ceos:4.32.0.2F"
HOST_NAME = "leaf-01"
OK = Counts(held=8 + 6 + 3 + 2, failed=0, skipped=3 + 2)
"""three-node-probed's verdict: 8 ports enabled, 6 neighbours, 3 claims and 2 bursts held; 3
configured host names reported and the 2 synthesized links' neighbours skipped."""
STOPPED = Counts(held=6 + 2 + 2 + 2, failed=0, skipped=3 + 2 + 2 + 4 + 1)
"""With n3 unread: its 2 ports, its 2 neighbours and the 2 facing it, and its claim are skips."""
WAIT_S = 120.0
"""How long verify is polled for `ok` once a node answers again, LLDP re-forming meanwhile."""
POLL_S = 5.0
HOST_POLL_S = 2.0

pytestmark = pytest.mark.skipif(
    not os.environ.get("FYLGJA_CREDENTIAL_SRLINUX_USERNAME"),
    reason="the live tier reads the node logins from the environment: load local/.env first "
    "(set -a; . local/.env; set +a)",
)


@dataclass
class Lab:
    """One twin the tests share: its driver and compiled bundle, the deployment an apply was last
    started with (`attempted`, set before it runs, so the teardown can destroy a lab whose apply
    failed), what `inspect` last saw, and the record verify reads. Verify and the reads run on
    one event loop for the twin's life, as they do in the server: a read cut at its budget
    leaves pygnmi's thread running to its end, which closing a loop waits for."""

    twin: str
    driver: ContainerlabDriver
    compiled: compiler.Compiled
    allocation: Allocation | None = None
    attempted: Planned | None = None
    inspection: Inspection | None = None
    record: TwinRecord | None = None
    loop: asyncio.Runner = field(default_factory=asyncio.Runner)


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
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120, check=check)


def clab(lab: Lab, *args: str) -> None:
    """containerlab on the twin's topology, as the driver deploys it; its environment carries no
    variable of the core's."""
    directory = lab.driver._directory(lab.twin)
    env = {k: v for k, v in os.environ.items() if not k.startswith("FYLGJA_")}
    start = time.monotonic()
    done = subprocess.run(["containerlab", *args, "-t", str(directory / TOPOLOGY)], capture_output=True, text=True,
                          timeout=300, env=env, cwd=directory, check=False)
    print(f"\n[live] containerlab {' '.join(args)}: rc {done.returncode} in {time.monotonic() - start:.2f} s")
    assert done.returncode == 0, done.stderr[-2000:]


def ceos_present() -> bool:
    return docker("image", "inspect", CEOS, check=False).returncode == 0


def needs_ceos() -> None:
    if not ceos_present():
        pytest.skip(f"the cEOS image {CEOS} is not on the host (docker image inspect fails): import it to show a "
                    "configured node's host name")


def login(package: PlatformPackage) -> Credential:
    return Provider(os.environ).login(package.credentials)


def node_names(c: compiler.Compiled) -> set[str]:
    """Every runtime node of the bundle: its device nodes and its probe hosts."""
    hosts = {host for probe in c.manifest.probes for host, _, _ in blueprint.hosts(probe)}
    return {node.name for node in c.manifest.nodes} | hosts


def leftovers(lab: Lab) -> dict[str, Any]:
    """What the host holds of the twin: its containers by label, its lines of /etc/hosts (the
    block's markers and its nodes' names, exactly), its ssh config and its network."""
    twin = lab.twin
    names = docker("ps", "-a", "--filter", f"label=containerlab={twin}", "--format", "{{.Names}}").stdout.split()
    exact = {f"clab-{twin}-{node}" for node in node_names(lab.compiled)}
    marked = {f"###### CLAB-{twin}-START ######", f"###### CLAB-{twin}-END ######"}
    hosts = Path("/etc/hosts").read_text(errors="replace").splitlines()
    lines = [line for line in hosts if line.strip() in marked or exact & set(line.split()[1:])]
    return {
        "containers": names,
        "hosts": lines,
        "ssh_config": Path(f"/etc/ssh/ssh_config.d/clab-{twin}.conf").exists(),
        "network": docker("network", "inspect", f"clab-{twin}", check=False).returncode == 0,
    }


CLEAN = {"containers": [], "hosts": [], "ssh_config": False, "network": False}


def sweep(twin: str) -> None:
    """The last resort: containerlab's destroy by the lab's name and the network's removal, each
    failure ignored."""
    for argv in (["containerlab", "destroy", "--name", twin, "--cleanup"], ["docker", "network", "rm", f"clab-{twin}"]):
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
    if p is None:
        lab.loop.close()
        return
    for attempt in (1, 2):
        try:
            run(lab.driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"teardown: destroy {lab.twin}")
        except Exception as e:
            print(f"\n[live] teardown: destroy {lab.twin} failed: {e}")
        left = leftovers(lab)
        print(f"\n[live] teardown, attempt {attempt}: the host holds {left}")
        if left == CLEAN:
            lab.loop.close()
            return
    lab.loop.close()
    sweep(lab.twin)
    left = leftovers(lab)
    if left != CLEAN:
        pytest.fail(f"the teardown left {lab.twin} on the host: {left}", pytrace=False)


def inspect(lab: Lab) -> Inspection:
    inspection = run(lab.driver.inspect(lab.twin), f"inspect {lab.twin}")
    lab.inspection = inspection
    return inspection


def address(lab: Lab, node: str) -> str:
    assert lab.inspection is not None
    (state,) = [n for n in lab.inspection.nodes if n.name == node]
    assert state.address, state
    return state.address


def deploy(lab: Lab) -> None:
    """Admit, plan and apply the twin; every node running."""
    c = lab.compiled
    allocation = run(lab.driver.admit(c.manifest, PLATFORMS, PROBES, lab.twin, []), f"admit {lab.twin}")
    assert not isinstance(allocation, Refusal), allocation
    lab.allocation = allocation
    planned = lab.driver.plan(c.manifest, c.id, PLATFORMS, PROBES, lab.twin, allocation)
    lab.attempted = planned
    run(lab.driver.apply(planned.deployment, planned.files, PLATFORMS, PROBES), f"apply {lab.twin}")
    inspection = inspect(lab)
    assert inspection.state == "present" and all(n.running for n in inspection.nodes), inspection
    assert {n.name for n in inspection.nodes} == node_names(c)


async def transport(lab: Lab, node: str) -> float:
    package = PLATFORMS[next(n.platform for n in lab.compiled.manifest.nodes if n.name == node)]
    return await await_transport(address(lab, node), package, login(package), timeout_s=package.readiness.timeout_s)


def ready(lab: Lab) -> None:
    """Each device node's push transport, at once, then each probe host's readiness command,
    polled through `exec` as the loop's ready phase polls it."""

    async def devices() -> list[float]:
        return await asyncio.gather(*(transport(lab, node.name) for node in lab.compiled.manifest.nodes))

    seconds = run(devices(), f"{lab.twin}'s device nodes' push transports")
    names = [n.name for n in lab.compiled.manifest.nodes]
    print(f"[live] each answered after: {dict(zip(names, seconds, strict=True))}")
    for probe in lab.compiled.manifest.probes:
        package = PROBES[probe.format]
        for side, (host, _, _) in zip("ab", blueprint.hosts(probe), strict=True):
            values = probe_package.host_values(package, probe, side)
            argv = [mapping.render(word, values) for word in package.readiness.command]
            expect = mapping.render(package.readiness.expect, values)
            start = time.monotonic()
            while True:
                answer = asyncio.run(lab.driver.exec(lab.twin, host, argv, package.readiness.timeout_s))
                if expect in answer.stdout:
                    break
                assert time.monotonic() - start < package.readiness.timeout_s, (host, answer)
                time.sleep(HOST_POLL_S)
            print(f"[live] {host} showed {expect!r} after {time.monotonic() - start:.2f} s")


def push_all(lab: Lab) -> None:
    """Every configured node's configuration pushed, as the loop's push phase pushes it. The
    diff is configuration text, so only its length is printed."""
    c = lab.compiled
    for node in c.manifest.nodes:
        assert node.config is not None
        package = PLATFORMS[node.platform]
        config = c.files[node.config.file].decode()
        answer = run(push.push(address(lab, node.name), package, config, login(package)), f"push {node.name}")
        assert isinstance(answer, push.Pushed), f"{node.name}'s push was refused"
        print(f"[live] {node.name}: pushed in {answer.duration_s:.2f} s, a diff of {len(answer.diff)} characters")


def record(lab: Lab) -> TwinRecord:
    """The record verify reads: the nodes `inspect` last saw, each holding the bundle."""
    assert lab.inspection is not None and lab.attempted is not None
    c = lab.compiled
    nodes = tuple(Node(name=n.name, handle=n.handle, address=n.address, holds=c.id, incarnation=n.incarnation)
                  for n in sorted(lab.inspection.nodes, key=lambda n: n.name))
    lab.record = TwinRecord(
        name=lab.twin, revision=1, generation=1,
        spec=Spec(bundle_id=c.id, driver="containerlab", allow_restart=False),
        status=Status(observed_generation=1, conditions=(), phase="pushed", bundle_id=c.id,
                      deployment_id=lab.attempted.deployment.id, allocation=lab.allocation, nodes=nodes),
    )
    return lab.record


def verify(lab: Lab, quiet: bool = False) -> tuple[Verdict, float]:
    """The verdict on the twin, with the real gNMI reader and the driver's `exec`, and its
    seconds; its status and counts printed, and its findings unless `quiet`."""
    held = lab.record
    assert held is not None
    verifier = Verifier(PLATFORMS, PROBES, Provider(os.environ))

    async def timed() -> tuple[Verdict, float]:
        start = time.monotonic()
        verdict = await verifier.verify(held, lab.compiled.manifest, lab.compiled.id, lab.driver.exec)
        return verdict, time.monotonic() - start

    verdict, seconds = lab.loop.run(timed())
    print(f"\n[live] verify {lab.twin}: {verdict.status} in {seconds:.2f} s, {verdict.counts}")
    if not quiet:
        print_findings(verdict)
    elif verdict.status != "ok":
        print(f"[live]   errors: {[(f.rule, f.object) for f in verdict.findings if f.severity == 'error']}")
    return verdict, seconds


def print_findings(verdict: Verdict) -> None:
    for f in verdict.findings:
        print(f"[live]   {f.severity} {f.rule} {f.object}: {f.message}")


def until_ok(lab: Lab) -> tuple[Verdict, float, int]:
    """Verify polled until `ok`, for at most `WAIT_S`: the last verdict, its findings printed,
    the seconds from the first try and the tries."""
    start, tries = time.monotonic(), 0
    while True:
        verdict, _ = verify(lab, quiet=True)
        tries += 1
        if verdict.status == "ok" or time.monotonic() - start >= WAIT_S:
            print_findings(verdict)
            return verdict, time.monotonic() - start, tries
        time.sleep(POLL_S)


def raw_get(lab: Lab, node: str, asked: list[str]) -> tuple[Any, float]:
    """The node's raw pygnmi answer to one Get of `asked`, through the reader's own dial, and its
    seconds. It holds the node's values and no credential."""
    package = PLATFORMS[next(n.platform for n in lab.compiled.manifest.nodes if n.name == node)]
    start = time.monotonic()
    reply = gnmi._read(address(lab, node), package, login(package), asked, gnmi.GNMI_TIMEOUT_S)
    return reply, time.monotonic() - start


def answered(lab: Lab, node: str, asked: list[str]) -> Mapping[str, Any]:
    package = PLATFORMS[next(n.platform for n in lab.compiled.manifest.nodes if n.name == node)]
    return asyncio.run(gnmi.get(address(lab, node), package, login(package), asked))


def show(lab: Lab, node: str, asked: list[str]) -> Mapping[str, Any]:
    """Print the node's raw answer to `asked` and what the reader maps it to; the mapping."""
    reply, seconds = raw_get(lab, node, asked)
    print(f"\n[live] {node}'s raw Get of {len(asked)} paths, {seconds:.2f} s: {json.dumps(reply, sort_keys=True)}")
    answer = answered(lab, node, asked)
    print(f"[live] {node}: the reader answers {json.dumps(answer, sort_keys=True)}")
    return answer


def rendered(template: str, node_name: str) -> str:
    return mapping.render(template, {"node_name": node_name})


def held_by_reader(lab: Lab, node: str, answer: Mapping[str, Any], names: bool = True) -> None:
    """The reader's answer holds every path verify asks of `node`: its host name, each enabled
    port's admin state as the package's value, and each intent link end's one neighbour, the far
    node on the far port by its node name (unless `names` is false: a far node whose host name
    has just changed is named anew only at its next LLDP update)."""
    c, rows = lab.compiled, {(r.device, r.interface): r for r in lab.compiled.manifest.mapping}
    package = PLATFORMS[next(n.platform for n in c.manifest.nodes if n.name == node)]
    conformance = package.conformance
    expected_name = HOST_NAME if (lab.twin, node) == (MIXED, "e1") else node
    assert answer.get(conformance.host_name) == expected_name, answer
    for row in c.manifest.mapping:
        if row.device == node and row.disposition == "cabled":
            assert row.node_name is not None
            assert answer.get(rendered(conformance.port.enabled.path, row.node_name)) == conformance.port.enabled.value
    for link in c.manifest.links:
        for near, far in ((link.a, link.b), (link.b, link.a)):
            if near.device != node:
                continue
            here, there = rows[(near.device, near.interface)], rows[(far.device, far.interface)]
            assert here.node_name is not None
            entries = answer.get(rendered(conformance.port.neighbor.path, here.node_name))
            assert isinstance(entries, list) and len(entries) == 1, (here.interface, entries)
            if not names:
                continue
            far_name = HOST_NAME if (lab.twin, far.device) == (MIXED, "e1") else far.device
            assert gnmi.leaf(entries[0], conformance.port.neighbor.system_name) == far_name, entries
            assert gnmi.leaf(entries[0], conformance.port.neighbor.port_id) == there.node_name, entries


class Records(logging.Handler):
    """Every record a logger emits, kept."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def refused(lab: Lab, node: str) -> None:
    """A Get sent with a login the node does not hold, made of random text: what pygnmi would log
    of it (its logger is silenced in the core; a handler is added here for the test alone) and the
    reader's `Unreadable`, neither holding the login. The login is printed as placeholders."""
    package = PLATFORMS[next(n.platform for n in lab.compiled.manifest.nodes if n.name == node)]
    wrong = Credential(username=f"u{secrets.token_hex(8)}", password=secrets.token_hex(16))
    log, kept = logging.getLogger("pygnmi.client"), Records()
    log.addHandler(kept)
    start = time.monotonic()
    try:
        with pytest.raises(gnmi.Unreadable) as raised:
            asyncio.run(gnmi.get(address(lab, node), package, wrong, [package.conformance.host_name]))
    finally:
        log.removeHandler(kept)
    seconds = time.monotonic() - start
    said = [f"{r.levelname}: {r.getMessage()}" for r in kept.records] + [str(raised.value)]
    hidden = [line.replace(wrong.password, "<password>").replace(wrong.username, "<username>") for line in said]
    print(f"\n[live] {node}, a refused login, {seconds:.2f} s: {hidden}")
    assert not any(wrong.password in line or wrong.username in line for line in said)
    assert "UNAUTHENTICATED" in str(raised.value) or "PERMISSION_DENIED" in str(raised.value), hidden


def mixed_blueprint() -> blueprint.Blueprint:
    """`mixed`, its `e1` configuration naming the host `leaf-01`."""
    doc = json.loads((ROOT / "testdata/blueprint/mixed.json").read_text())
    (e1,) = [d for d in doc["network"]["devices"] if d["name"] == "e1"]
    assert "\nhostname e1\n" in e1["config"]
    e1["config"] = e1["config"].replace("\nhostname e1\n", f"\nhostname {HOST_NAME}\n")
    return blueprint.decode(doc)


@pytest.fixture(scope="module")
def probed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Lab]:
    c = compiler.compile(blueprint.load(ROOT / "testdata/blueprint/three-node-probed.json"), PLATFORMS, PROBES)
    shared = Lab(twin=TWIN, driver=ContainerlabDriver(tmp_path_factory.mktemp("verify-live")), compiled=c)
    yield shared
    clean_up(shared)


@pytest.fixture(scope="module")
def mixed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Lab]:
    c = compiler.compile(mixed_blueprint(), PLATFORMS, PROBES)
    shared = Lab(twin=MIXED, driver=ContainerlabDriver(tmp_path_factory.mktemp("verify-live-mixed")), compiled=c)
    yield shared
    clean_up(shared)


def test_01_the_probed_twin_comes_up_as_the_loop_brings_it_up(probed: Lab) -> None:
    assert leftovers(probed) == CLEAN, f"the host holds {TWIN} already"
    deploy(probed)
    ready(probed)
    push_all(probed)
    record(probed)


def test_02_each_srlinux_node_answers_the_paths_verify_asks(probed: Lab) -> None:
    package = PLATFORMS["nokia_srlinux"]
    for node in ("n1", "n2", "n3"):
        answer = show(probed, node, paths(probed.compiled.manifest, node, package))
        held_by_reader(probed, node, answer)
    # A value the node does not hold: an uncabled port's neighbour, and a port the chassis lacks.
    absent = [rendered(package.conformance.port.neighbor.path, "ethernet-1/3"),
              rendered(package.conformance.port.enabled.path, "ethernet-1/99")]
    assert show(probed, "n1", absent) == {}


def test_03_a_refused_login_on_srlinux_is_unreadable_and_quotes_no_login(probed: Lab) -> None:
    refused(probed, "n1")


def test_04_each_burst_runs_alone(probed: Lab) -> None:
    for probe in probed.compiled.manifest.probes:
        package = PROBES[probe.format]
        for side, (host, _, _) in zip("ab", blueprint.hosts(probe), strict=True):
            far = probe_package.host_values(package, probe, side)["far_address"]
            argv = burst.command(package, far)
            result = run(probed.driver.exec(TWIN, host, argv, burst.timeout_s(package)), f"burst {host} -> {far}")
            print(f"[live] {host}'s burst: status {result.returncode}, stdout {result.stdout!r}")
            assert burst.held(package, result) == (True, f"{package.burst.count} of {package.burst.count} "
                                                         "echoes answered")


def test_05_verify_is_ok_with_every_assertion_counted(probed: Lab) -> None:
    verdict, _ = verify(probed)
    assert verdict.status == "ok" and verdict.counts == OK, verdict
    assert all(f.rule == RULE_SKIPPED for f in verdict.findings)


def stopped(lab: Lab, how: str) -> None:
    """n3, just stopped `how`: its read alone, and verify, each within the read's budget; the
    verdict `failed`, n3 its one error, and every assertion of n3 or facing it a skip."""
    package = PLATFORMS["nokia_srlinux"]

    async def alone() -> tuple[str, float]:
        start = time.monotonic()
        with pytest.raises(gnmi.Unreadable) as raised:
            await gnmi.get(address(lab, "n3"), package, login(package), [package.conformance.host_name])
        return str(raised.value), time.monotonic() - start

    what, seconds = lab.loop.run(alone())
    print(f"\n[live] n3, stopped by {how}, read alone: {what} after {seconds:.2f} s")
    assert seconds < gnmi.GNMI_TIMEOUT_S + 1, seconds
    verdict, seconds = verify(lab)
    assert seconds < gnmi.GNMI_TIMEOUT_S + 5, seconds  # the read's budget bounds it, and the bursts run after
    assert verdict.status == "failed" and verdict.counts == STOPPED, verdict
    errors = [(f.rule, f.object) for f in verdict.findings if f.severity == "error"]
    assert errors == [(RULE_NODE_UNREAD, "n3")]
    facing = [f for f in verdict.findings
              if f.rule == RULE_SKIPPED and f.object in ("n1:ethernet-1/2", "n2:ethernet-1/2")]
    assert len(facing) == 2 and all("n3, its far end, could not be read" in f.message for f in facing), facing


def started(lab: Lab) -> list[str]:
    """n3 started again: its push transport awaited, the record's address read anew, and the
    interfaces it holds, printed."""
    inspect(lab)
    seconds = run(transport(lab, "n3"), "n3's push transport")
    print(f"[live] n3 answered its push transport after {seconds:.2f} s")
    ports = asyncio.run(lab.driver.exec(TWIN, "n3", ["ls", "/sys/class/net"], 30.0)).stdout.split()
    print(f"[live] n3's interfaces after the start: {ports}")
    record(lab)
    return ports


def test_06_a_node_stopped_by_containerlab_is_a_failed_verdict(probed: Lab) -> None:
    clab(probed, "stop", "--node", "n3")
    stopped(probed, "containerlab stop")


def test_07_started_by_containerlab_it_keeps_its_links_and_verifies_ok_again(probed: Lab) -> None:
    clab(probed, "start", "--node", "n3")
    ports = started(probed)
    assert {"e1-1", "e1-2"} <= set(ports), ports
    verdict, waited, tries = until_ok(probed)
    print(f"[live] verify after containerlab's start: {verdict.status} after {waited:.1f} s, {tries} tries")
    assert verdict.status == "ok" and verdict.counts == OK, verdict


def test_08_a_node_stopped_by_docker_is_a_failed_verdict(probed: Lab) -> None:
    run(asyncio.to_thread(docker, "stop", f"clab-{TWIN}-n3"), f"docker stop clab-{TWIN}-n3")
    stopped(probed, "docker stop")


def test_09_started_by_docker_it_has_lost_its_links_and_is_nonconforming(probed: Lab) -> None:
    # Started again by Docker, n3 no longer lists e1-1 and e1-2, and a veth's peer goes with
    # it: no neighbour forms at either end of its links.
    run(asyncio.to_thread(docker, "start", f"clab-{TWIN}-n3"), f"docker start clab-{TWIN}-n3")
    ports = started(probed)
    assert not {"e1-1", "e1-2"} & set(ports), ports
    verdict, _ = verify(probed)
    assert verdict.status == "nonconforming", verdict
    assert verdict.counts == Counts(held=OK.held - 4, failed=4, skipped=OK.skipped), verdict
    lost = [f for f in verdict.findings if f.severity == "error"]
    assert [(f.rule, f.object) for f in lost] == [(RULE_PORT_NEIGHBOR, port) for port in (
        "n1:ethernet-1/2", "n2:ethernet-1/2", "n3:ethernet-1/1", "n3:ethernet-1/2")]
    assert all("lists no neighbour" in f.message for f in lost), lost


def test_10_the_probed_twin_is_destroyed(probed: Lab) -> None:
    p = probed.attempted
    assert p is not None
    run(probed.driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"destroy {TWIN}")
    assert leftovers(probed) == CLEAN


def test_11_the_mixed_twin_comes_up_with_e1_named_leaf_01(mixed: Lab) -> None:
    needs_ceos()
    assert leftovers(mixed) == CLEAN, f"the host holds {MIXED} already"
    deploy(mixed)
    ready(mixed)
    push_all(mixed)
    record(mixed)


def test_12_each_ceos_node_answers_the_paths_verify_asks(mixed: Lab) -> None:
    needs_ceos()
    package = PLATFORMS["arista_eos"]
    for node in ("e2", "e1"):
        held_by_reader(mixed, node, show(mixed, node, paths(mixed.compiled.manifest, node, package)), names=False)
    # A value the node does not hold: an uncabled port's neighbour, and a port the node lacks.
    absent = [rendered(package.conformance.port.neighbor.path, "Ethernet10"),
              rendered(package.conformance.port.enabled.path, "Ethernet99")]
    assert show(mixed, "e2", absent) == {}


def test_13_a_refused_login_on_ceos_is_unreadable_and_quotes_no_login(mixed: Lab) -> None:
    needs_ceos()
    refused(mixed, "e1")


def test_14_the_configured_host_name_is_reported_and_judged_against(mixed: Lab) -> None:
    needs_ceos()
    verdict, waited, tries = until_ok(mixed)
    print(f"[live] verify {MIXED}: {verdict.status} after {waited:.1f} s, {tries} tries")
    for node in ("e1", "e2", "s1"):
        package = PLATFORMS[next(n.platform for n in mixed.compiled.manifest.nodes if n.name == node)]
        held_by_reader(mixed, node, answered(mixed, node, paths(mixed.compiled.manifest, node, package)))
    (reported,) = [f for f in verdict.findings if f.rule == RULE_SKIPPED and f.object == "e1"]
    assert f"reports its host name as {HOST_NAME}" in reported.message, reported
    assert verdict.status == "ok" and verdict.counts == Counts(held=6 + 6 + 3, failed=0, skipped=3), verdict


def test_15_the_mixed_twin_is_destroyed(mixed: Lab) -> None:
    needs_ceos()
    p = mixed.attempted
    assert p is not None
    run(mixed.driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"destroy {MIXED}")
    assert leftovers(mixed) == CLEAN
