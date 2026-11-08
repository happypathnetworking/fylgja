"""The clabernetes driver's calls on the k3s cluster (D-057, D-069): the twin `drv-k8s`,
`three-node` compiled with the shipped packages, admitted, planned and applied by the driver the
server makes (`drivers.make`), with every pull credential the environment holds, so that its
`apply` makes their pull secrets. `admit` against a namespace that is not the twin's; `apply`,
its repeat and a Service drifted back to `Cluster`; `exec`; a node's container ended in place; a
pod deleted and `reconfigure`; `destroy`, and a namespace alone as residue.

A node's uid, where a test says one moves or stays, is its pod's uid, the part of `inspect`'s
incarnation before the `/`; the restart count is the part after it (D-069).

The tests run in order and share the twin; each asserts what it read and prints it with its time
(`-s`), and design/verified-facts.md records the readings. The module destroys the twin at its
end, whatever happened, then deletes its namespace and the refused twin's through `kube` and
waits for them to go, each delete and wait tried whatever another did. Nothing of the site is
printed, a failure's message included: no address, host, CIDR or credential. An assertion
compares first and asserts on a bool or on names, since pytest prints the values an assertion
compared; and the DEBUG apply's check holds the credential's values in a helper of its own,
never in the test's frame. Without a pull credential set, that check has nothing to look for,
and the test that makes it is skipped once the rest of it has run.

(The module is not named `test_clabernetes_driver.py`: the pure tier's module has that name, and
pytest and mypy each take a test module by its basename.)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import time
import traceback
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from cluster.conftest import GATED, Site, run, say, until, watching
from fylgja_core import blueprint, compiler, packages, push
from fylgja_core.clabernetes import OWNER, OWNER_LABEL, TWIN_LABEL, namespace_of
from fylgja_core.clabernetes.driver import RULE_NAMESPACE, ClabernetesDriver
from fylgja_core.clabernetes.kube import NODE_LABEL, LightKube, Pod
from fylgja_core.clabernetes.plan import NAMESPACE
from fylgja_core.credentials import Provider
from fylgja_core.driver import Allocation, DriverFailed, Exec, Inspection, NodeState, Planned, Refusal
from fylgja_core.kubeapi import REQUEST_TIMEOUT_S

ROOT = Path(__file__).resolve().parents[3]
LOADED = packages.load([ROOT / "psp", ROOT / "probes"])
PLATFORMS, PROBES = LOADED.platforms, LOADED.probes
TWIN = "drv-k8s"
NS = namespace_of(TWIN)
TAKEN = "drv-k8s-taken"
"""A twin whose namespace the test makes first, with no label: it is not the twin's."""
NODES = ("n1", "n2", "n3")
LABELS = {OWNER_LABEL: OWNER, TWIN_LABEL: TWIN}
CONFIG = {d["name"]: d["config"] for d in json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
          ["network"]["devices"]}
DESCRIPTION = 'description "to n2 ethernet-1/1"'
"""A line of n1's pushed configuration that its baseline lacks."""
DESCRIBED = ["sr_cli", "info from running / interface ethernet-1/1 description"]
UPTIME = ["sh", "-c", "echo $(( $(cut -d' ' -f1 /proc/uptime | cut -d. -f1) - $(cut -d' ' -f22 /proc/1/stat) "
                      "/ $(getconf CLK_TCK) ))"]
"""The seconds the node's container's first process, `tini`, has run."""
REPEAT_S = 15.0
SSH_S = 5.0
RESTART_S = 180.0
CLI_S = 120.0
GONE_S = 180.0


@dataclass
class Twin:
    """What the tests share: the deployment planned for the twin, once `admit` answered, and its
    nodes as `inspect` last answered them running."""

    planned: Planned | None = None
    nodes: dict[str, NodeState] = field(default_factory=dict)

    def deployed(self) -> Planned:
        assert self.planned is not None, "the twin was never planned: the first test failed"
        return self.planned


class Collected(logging.Handler):
    """Every log record emitted while it is the root logger's one handler, kept and never shown."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def compiled(name: str) -> compiler.Compiled:
    return compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)


def uid(node: NodeState) -> str:
    """The node's pod's uid, from its incarnation `<uid>/<restarts>` (D-069)."""
    incarnation = node.incarnation
    assert incarnation is not None, f"{node.name} has no incarnation"
    return incarnation.split("/")[0]


def state_of(loop: asyncio.Runner, driver: ClabernetesDriver, twin: str) -> str:
    """`inspect`'s state for the twin, alone: an `Inspection` holds each node's address."""
    state: str = run(loop, driver.inspect(twin), f"inspect {twin}").state
    return state


def present(loop: asyncio.Runner, driver: ClabernetesDriver) -> dict[str, NodeState]:
    """The twin's nodes, by name: every node of `three-node`, running, at an incarnation and an address."""
    inspection = run(loop, driver.inspect(TWIN), f"inspect {TWIN}")
    state = inspection.state
    assert state == "present", f"inspect {TWIN}: {state}"
    nodes = {n.name: n for n in inspection.nodes}
    names = tuple(nodes)
    assert names == NODES, f"inspect {TWIN}: the nodes {names}"
    lacking = [n.name for n in inspection.nodes
               if not (n.running and n.address and n.incarnation and "/" in n.incarnation)]
    assert not lacking, f"not running, or without an address or an incarnation: {lacking}"
    return nodes


def moved(before: dict[str, NodeState], after: dict[str, NodeState]) -> list[str]:
    """The nodes whose address is not the one they had, by name alone."""
    was = {name: n.address for name, n in before.items()}
    now = {name: n.address for name, n in after.items()}
    return sorted(name for name in {*was, *now} if was.get(name) != now.get(name))


def pod_of(loop: asyncio.Runner, kube: LightKube, node: str) -> Pod:
    """The node's one pod, read through `kube`."""
    [pod] = [p for p in run(loop, kube.pods(NS, LABELS), "pods") if p.labels.get(NODE_LABEL) == node]
    return pod


def secret_values(driver: ClabernetesDriver, provider: Provider, allocation: Allocation) -> list[str]:
    """For each pull credential of the allocation: its password, the base64 of `username:password`,
    and the Secret's `.dockerconfigjson` as the driver makes it. Never printed."""
    values = []
    for key, prefix in allocation["registries"].items():
        credential = provider.pull(key)
        login = f"{credential.username}:{credential.password}".encode()
        secret = driver._pull_secret(TWIN, NS, key, prefix)
        values += [credential.password, base64.b64encode(login).decode(), secret["data"][".dockerconfigjson"]]
    return values


def carries(text: str, values: Sequence[str]) -> bool:
    return any(value in text for value in values)


def auths_hosts(driver: ClabernetesDriver, key: str, prefix: str) -> list[str]:
    """The keys of the `auths` of the pull secret the driver makes for `key`, alone: the Secret holds the login."""
    config = json.loads(base64.b64decode(driver._pull_secret(TWIN, NS, key, prefix)["data"][".dockerconfigjson"]))
    return list(config["auths"])


@dataclass(frozen=True)
class Checked:
    """What the DEBUG apply's check found, and nothing of the credential: the records by logger,
    the loggers of those that carried a value, how many values were looked for, the type of the
    apply's exception when it raised, and whether that exception carried a value."""

    by_logger: dict[str, int]
    leaked: list[str]
    values: int
    raised: str | None
    raised_leaks: bool


def applied_at_debug(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, provider: Provider,
                     p: Planned) -> Checked:
    """Apply `p` with the root logger at DEBUG and its one handler a collector, so pytest's own keep
    no record and no report could show one; then check every record, and the apply's exception if
    it raised, against each value `secret_values` gives. Done here and answered as counts and
    names: a value in the test's frame would be printed by `pytest -l` at any later failure."""
    values = secret_values(driver, provider, p.deployment.allocation)
    collected, root = Collected(), logging.getLogger()
    handlers, level = root.handlers[:], root.level
    failure: Exception | None = None
    root.handlers = [collected]
    root.setLevel(logging.DEBUG)
    try:
        run(loop, watching(kube, NS, TWIN, driver.apply(p.deployment, p.files, PLATFORMS, PROBES), f"apply {TWIN}"),
            f"apply {TWIN}, the root logger at DEBUG")
    except Exception as e:
        failure = e
    finally:
        root.handlers = handlers
        root.setLevel(level)
    return Checked(
        by_logger=dict(Counter(r.name for r in collected.records)),
        leaked=[r.name for r in collected.records if carries(record_text(r), values)],
        values=len(values),
        raised=None if failure is None else type(failure).__name__,
        raised_leaks=failure is not None and carries("".join(traceback.format_exception(failure)), values))


def record_text(record: logging.LogRecord) -> str:
    """All a record could show: its message, formatted and not, its arguments, and any exception or stack."""
    parts = [str(record.msg), repr(record.args), record.exc_text or "", record.stack_info or ""]
    try:
        parts.append(record.getMessage())
    except Exception as e:  # a record whose arguments do not fit its message
        parts.append(type(e).__name__)
    if record.exc_info and record.exc_info[1] is not None:
        parts.append("".join(traceback.format_exception(record.exc_info[1])))
    return "\n".join(parts)


@pytest.fixture(scope="module")
def twin(loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver) -> Iterator[Twin]:
    shared = Twin()
    try:
        yield shared
    finally:
        if shared.planned is not None:
            p = shared.planned
            try:
                run(loop, driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"teardown: destroy {TWIN}")
            except Exception as e:
                say(f"teardown: destroy {TWIN} failed: {e}")
        failures: list[BaseException] = []
        deleted = []
        for namespace in (NS, namespace_of(TAKEN)):
            try:
                run(loop, kube.delete_namespace(namespace), f"delete_namespace {namespace} (the module's end)")
                deleted.append(namespace)
            except Exception as e:
                say(f"teardown: delete_namespace {namespace} failed: {type(e).__name__}")
                failures.append(e)
        for namespace in deleted:
            try:
                gone(loop, kube, namespace, f"{namespace} gone (the module's end)")
            except (Exception, pytest.fail.Exception) as e:
                say(f"teardown: {namespace} not gone: {type(e).__name__}")
                failures.append(e)
        if failures:
            raise failures[0]


def gone(loop: asyncio.Runner, kube: LightKube, namespace: str, what: str) -> None:
    """Wait until the namespace `namespace` is gone."""
    until(loop, lambda: kube.namespace(namespace), lambda found: found is None, GONE_S, what)


def test_1_admit_answers_the_sites_values_and_refuses_a_namespace_that_is_not_the_twins(
    site: Site, loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, provider: Provider, twin: Twin
) -> None:
    before = state_of(loop, driver, TWIN)
    assert before == "absent", f"inspect {TWIN}, before: {before}"
    c = compiled("three-node")
    allocation = run(loop, driver.admit(c.manifest, PLATFORMS, PROBES, TWIN, []), f"admit {TWIN}")
    if isinstance(allocation, Refusal):
        pytest.fail(f"admit {TWIN} refused: {allocation.rule}")
    site_values = {"namespace": NS, "controller_namespace": site.controller_namespace, "pod_cidr": site.pod_cidr,
                   "registries": provider.registries()}
    differing = sorted(k for k in {*allocation, *site_values} if allocation.get(k) != site_values.get(k))
    assert not differing, f"the allocation differs from the site's in {differing}"
    say(f"allocation: {sorted(allocation)}, registries {sorted(allocation['registries'])}")
    twin.planned = driver.plan(c.manifest, c.id, PLATFORMS, PROBES, TWIN, allocation)

    taken = namespace_of(TAKEN)
    run(loop, kube.apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": taken}}),
        f"apply the namespace {taken}, with no label")
    refused = run(loop, driver.admit(c.manifest, PLATFORMS, PROBES, TAKEN, []), f"admit {TAKEN}")
    if not isinstance(refused, Refusal):
        pytest.fail(f"admit {TAKEN} answered an allocation")
    rule = refused.rule
    assert rule == RULE_NAMESPACE, f"admit {TAKEN} refused by {rule}"
    say(f"refused: {refused.rule}: {refused.message}")
    absent = run(loop, driver.inspect(TAKEN), f"inspect {TAKEN}") == Inspection("absent", ())
    assert absent, f"inspect {TAKEN} is not absent"
    p = driver.plan(c.manifest, c.id, PLATFORMS, PROBES, TAKEN, {**allocation, "namespace": taken})
    run(loop, driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"destroy {TAKEN}")
    left = run(loop, kube.namespace(taken), f"namespace {taken}")
    assert left is not None and not left.deleting, left
    run(loop, kube.delete_namespace(taken), f"delete_namespace {taken}")
    gone(loop, kube, taken, f"{taken} gone")


def test_2_apply_runs_every_node_at_an_address_reached_from_off_the_cluster_and_logs_no_credential(
    loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, provider: Provider, twin: Twin
) -> None:
    p = twin.deployed()
    registries = p.deployment.allocation["registries"]
    for key, prefix in registries.items():
        held = auths_hosts(driver, key, prefix) == [prefix.split("/", 1)[0]]
        assert held, f"the pull secret of {key}: its auths is not the host of the allocation's prefix alone"
        say(f"the pull secret of {key}: its auths holds one key, the host of the allocation's prefix, no path")

    checked = applied_at_debug(loop, kube, driver, provider, p)
    say(f"{sum(checked.by_logger.values())} log records ({checked.by_logger}), checked against {checked.values} "
        f"values of {len(registries)} pull credential(s): "
        f"{'none carries one' if not (checked.leaked or checked.raised_leaks) else 'one carries one'}")
    assert not checked.raised_leaks, "the apply's exception carries a credential"
    assert not checked.leaked, f"a log record carries a credential, of the loggers {sorted(set(checked.leaked))}"
    assert checked.raised is None, f"the apply raised {checked.raised}"

    nodes = present(loop, driver)
    twin.nodes = nodes
    for n in nodes.values():
        say(f"{n.name}: pod {n.handle}, incarnation {n.incarnation}, an address")
    endpoints = run(loop, driver.endpoints(TWIN), "endpoints")
    unlike = sorted(name for name in {*endpoints, *nodes}
                    if endpoints.get(name) != (nodes[name].address if name in nodes else None))
    assert not unlike, f"endpoints and inspect disagree on {unlike}"
    pods = run(loop, kube.pods(NS, LABELS), "pods")
    assert sorted(pod.labels[NODE_LABEL] for pod in pods) == list(NODES)
    assert all(LABELS.items() <= pod.labels.items() for pod in pods)
    balancers = [s for s in run(loop, kube.services(NS), "services") if s.type == "LoadBalancer"]
    assert [s.name for s in balancers] == list(NODES)
    not_local = [s.name for s in balancers if s.traffic_policy != "Local"]
    assert not not_local, f"not Local: {not_local}"
    for name, n in nodes.items():
        address = n.address
        assert address is not None, f"{name} has no address"
        start = time.monotonic()
        with socket.create_connection((address, 22), timeout=SSH_S):
            pass
        say(f"TCP to {name}'s address on port 22 from the development host: open in {time.monotonic() - start:.2f} s")
    if not checked.values:
        pytest.skip(f"the DEBUG check had no value to look for: set a pull credential, FYLGJA_CREDENTIAL_{GATED}_"
                    "REGISTRY, _USERNAME and _PASSWORD (CONTRIBUTING.md, make cluster)")


def test_3_apply_again_is_quick_moves_no_uid_and_inspect_patches_a_drifted_service_back_to_local(
    loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, twin: Twin
) -> None:
    p = twin.deployed()
    start = time.monotonic()
    run(loop, driver.apply(p.deployment, p.files, PLATFORMS, PROBES), f"apply {TWIN} again")
    assert time.monotonic() - start < REPEAT_S
    nodes = present(loop, driver)
    assert {name: uid(n) for name, n in nodes.items()} == {name: uid(n) for name, n in twin.nodes.items()}
    run(loop, kube.patch_service(NS, "n1", {"spec": {"externalTrafficPolicy": "Cluster"}}), "patch n1 to Cluster")
    assert {s.name: s.traffic_policy for s in run(loop, kube.services(NS), "services")}["n1"] == "Cluster"
    run(loop, driver.inspect(TWIN), f"inspect {TWIN}")
    assert {s.name: s.traffic_policy for s in run(loop, kube.services(NS), "services")}["n1"] == "Local"


def test_4_exec_answers_a_status_and_both_streams_and_fails_where_the_local_driver_fails(
    loop: asyncio.Runner, driver: ClabernetesDriver, twin: Twin
) -> None:
    answered = run(loop, driver.exec(TWIN, "n1", ["sh", "-c", "echo out; echo err >&2; exit 7"], 10.0),
                   "exec of an exit 7")
    assert answered == Exec(7, "out\n", "err\n")
    for node, argv, budget, what in (("n1", ["no-such-binary"], 10.0, "a binary the node lacks"),
                                     ("nx", ["true"], 10.0, "a node the twin lacks"),
                                     ("n1", ["sleep", "30"], 3.0, "sleep 30 within 3 s")):
        start = time.monotonic()
        with pytest.raises(DriverFailed) as failed:
            run(loop, driver.exec(TWIN, node, argv, budget), f"exec of {what}")
        took = time.monotonic() - start
        say(f"{what}: {type(failed.value).__name__} in {took:.2f} s: {failed.value}")
        assert took < 2 * budget


def test_5_a_container_ended_in_place_keeps_its_pods_uid_counts_a_restart_boots_again_and_loses_the_push(
    loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, provider: Provider, twin: Twin
) -> None:
    # D-069's premise, read through the driver's Kube: the kubelet restarts a node's container in
    # its pod. SR Linux's first process is `tini`, which ends with its child on SIGTERM.
    srlinux = PLATFORMS["nokia_srlinux"]
    nodes = present(loop, driver)
    address = nodes["n1"].address
    assert address is not None
    pushed = run(loop, push.push(address, srlinux, CONFIG["n1"], provider.login(srlinux.credentials)),
                 "push n1's configuration over JSON-RPC at its address")
    assert isinstance(pushed, push.Pushed), f"the push answered {type(pushed).__name__}"
    described = run(loop, driver.exec(TWIN, "n1", DESCRIBED, 30.0), "exec sr_cli, n1's ethernet-1/1 description")
    assert described.returncode == 0 and DESCRIPTION in described.stdout, described
    up = run(loop, driver.exec(TWIN, "n1", UPTIME, 10.0), "exec: the seconds n1's first process has run")
    before = pod_of(loop, kube, "n1")
    say(f"before: n1's pod uid {before.uid}, restarts {before.restarts}, phase {before.phase}, ready {before.ready}; "
        f"its first process up {up.stdout.strip()} s; incarnation {nodes['n1'].incarnation}")

    async def restarted() -> tuple[Pod, dict[str, set[bool]], float]:
        # `inspect`'s `running` for n1 while its pod is not Ready: before the restart count moves,
        # the container down, and after, the container running and the node booting.
        killed = await driver.exec(TWIN, "n1", ["sh", "-c", "kill 1"], 10.0)
        start = time.monotonic()
        assert killed.returncode == 0, killed
        running: dict[str, set[bool]] = {"before the count moved": set(), "after it moved": set()}
        while True:
            [pod] = [p for p in await kube.pods(NS, LABELS) if p.labels.get(NODE_LABEL) == "n1"]
            if pod.restarts > before.restarts and pod.ready:
                return pod, running, time.monotonic() - start
            if not pod.ready:
                inspection = await driver.inspect(TWIN)
                moved = "after it moved" if pod.restarts > before.restarts else "before the count moved"
                running[moved] |= {n.running for n in inspection.nodes if n.name == "n1"}
            assert time.monotonic() - start < RESTART_S, f"n1's container was not running again within {RESTART_S:g} s"
            await asyncio.sleep(0.5)

    after, running, took = run(loop, watching(kube, NS, TWIN, restarted(), "exec kill 1 in n1"),
                               "n1's container ended by `kill 1`, until its pod is Ready again")
    say(f"after {took:.1f} s: n1's pod uid {after.uid}, restarts {after.restarts}, phase {after.phase}, ready "
        f"{after.ready}; inspect's running while the pod was not Ready: "
        f"{ {when: sorted(seen) for when, seen in running.items()} }")
    assert False in running["before the count moved"], "inspect never read n1 down before its restart"
    assert after.uid == before.uid and after.restarts == before.restarts + 1
    now = present(loop, driver)
    incarnation, was = now["n1"].incarnation, nodes["n1"].incarnation
    assert incarnation == f"{before.uid}/{before.restarts + 1}" != was
    assert {name: now[name].incarnation for name in ("n2", "n3")} == {name: nodes[name].incarnation
                                                                      for name in ("n2", "n3")}
    up = run(loop, driver.exec(TWIN, "n1", UPTIME, 10.0), "exec: the seconds n1's first process has run")
    say(f"n1's first process up {up.stdout.strip()} s, {took:.1f} s after the kill")
    assert int(up.stdout) < took + 5, "n1 did not boot again"

    async def answered() -> Exec | None:
        try:
            return await driver.exec(TWIN, "n1", DESCRIBED, 30.0)
        except DriverFailed:
            return None

    described_after, _ = until(loop, answered, lambda a: a is not None and a.returncode == 0, CLI_S,
                               "sr_cli answers in n1 again")
    assert described_after is not None
    say(f"n1's ethernet-1/1 description after the restart: {described_after.stdout!r}")
    assert DESCRIPTION not in described_after.stdout, "the push outlived the container's restart"
    twin.nodes = now


def test_6_a_deleted_pod_is_another_uid_at_the_same_address_and_reconfigure_replaces_every_pod(
    loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, twin: Twin
) -> None:
    nodes = present(loop, driver)
    old = pod_of(loop, kube, "n1")

    async def replaced() -> NodeState:
        await kube.delete_pod(NS, old.name)
        start, moved = time.monotonic(), False
        while True:
            node = {n.name: n for n in (await driver.inspect(TWIN)).nodes}["n1"]
            if uid(node) != old.uid and not moved:
                moved = True
                say(f"inspect: n1 at another uid {time.monotonic() - start:.2f} s after the delete, running "
                    f"{node.running}, its address {'kept' if node.address == nodes['n1'].address else 'changed'}")
            if moved and node.running:
                return node
            assert time.monotonic() - start < RESTART_S, f"n1 did not run again within {RESTART_S:g} s"
            await asyncio.sleep(0.5)

    node = run(loop, watching(kube, NS, TWIN, replaced(), "delete_pod n1"),
               "n1's pod deleted through kube, until inspect has it running at another uid")
    replaced_at, kept = uid(node) != old.uid, node.address == nodes["n1"].address
    assert replaced_at and kept, "n1 is not at another uid, or its address moved"

    p = twin.deployed()
    before = present(loop, driver)
    run(loop, watching(kube, NS, TWIN, driver.apply(p.deployment, p.files, PLATFORMS, PROBES, reconfigure=True),
                       f"apply {TWIN} --reconfigure"), f"apply {TWIN} --reconfigure")
    after = present(loop, driver)
    say(f"uids before {[uid(before[n])[:8] for n in NODES]}, after {[uid(after[n])[:8] for n in NODES]}")
    assert all(uid(after[n]) != uid(before[n]) for n in NODES)
    elsewhere = moved(before, after)
    assert not elsewhere, f"the addresses of {elsewhere} moved"


def test_7_destroy_leaves_nothing_and_the_namespace_alone_is_residue_destroy_clears(
    loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, twin: Twin
) -> None:
    p = twin.deployed()
    run(loop, driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"destroy {TWIN}")
    state = state_of(loop, driver, TWIN)
    assert state == "absent", f"inspect {TWIN}: {state}"
    assert run(loop, kube.namespace(NS), "namespace") is None
    start = time.monotonic()
    run(loop, driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"destroy {TWIN} again")
    assert time.monotonic() - start < REQUEST_TIMEOUT_S

    run(loop, kube.apply(yaml.safe_load(p.files[NAMESPACE])), f"apply {NAMESPACE} alone")
    residue = run(loop, driver.inspect(TWIN), f"inspect {TWIN}") == Inspection("residue", ())
    assert residue, f"inspect {TWIN} is not residue"
    run(loop, driver.destroy(p.deployment, p.files, PLATFORMS, PROBES), f"destroy {TWIN}, the residue")
    state = state_of(loop, driver, TWIN)
    assert state == "absent", f"inspect {TWIN}: {state}"
    assert run(loop, kube.namespace(NS), "namespace") is None
