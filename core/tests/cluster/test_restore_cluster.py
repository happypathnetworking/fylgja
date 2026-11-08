"""The trigger and the restore on the k3s cluster (D-058, D-067, D-069). The twin `rst-cluster`,
from `steps/two-node`, is made in a store of the module's own and reconciled by a `Reconciler`
the module runs in-process on the session's event loop (`loop`), to which the lightkube clients
are bound. The resync is an hour away (`RESYNC_S`), so every pass these tests read after the
create was started by the pod watch, never by the resync; the step wait is the server's default,
`STEP_WAIT_S`.

Once the twin is Ready, its nodes are replaced behind the core's back, in order:

- `n2`'s pod deleted through the tests' own `kube`: a restore run, the core's own, readies and
  pushes `n2` alone at the uid of its new pod, waits for verify and ends `ok`, the twin Ready
  again, its Services `Local`;
- `n1`'s container ended in its pod (`kill 1`): restarted there its address would not answer
  again, so the driver deletes the pod as the watch delivers the container's end, and the
  replacement is restored within the node's boot window;

then the twin is left alone for `QUIET_S`, and its pods' changes counted; a watch is asked for at
a version long compacted; the twin is stepped to `three-node-probed`, a probe host's pod deleted,
stepped to `steps/three-node-n3-eos` and the cEOS node's pod deleted. A node's pod replaced must
run again within its package's boot window (60 s for SR Linux, 30 s for a ping host, 90 s for
cEOS), counted by the loop from the first pass that saw it gone: otherwise the twin reads
`twin.node.missing` though nothing is missing.

The loop's driver is the module's own, made as `drivers.make` makes the session's, over the
session driver's own reach, so the session's driver, which every cluster module shares, is left
as it is: an observing `Kube` keeps each change the pod watch delivered and each pod the driver
deleted, with its time (`Observed`); the driver keeps each name its `events` yielded
(`Watching`); and the reconciler each pass's start and end (`Timed`). The loop's log goes to a
file as one JSON object a line, every address scrubbed from it as from pytest's capture, since
the push's lines name each node's address (`Scrubbing`). The polling is on the session's loop,
so the reconciler runs while a test waits; a test never sleeps outside it.

Each test prints what it took and saw (`-s`). Nothing of the site is printed, a failure's message
included: no address, host, CIDR or credential. A log line or a finding's message is printed with
every IPv4 address in it replaced (`scrubbed`), and an assertion compares first and asserts on a
bool or on names, never on a verdict, a node or an allocation, which pytest would print. The
teardown stops the loop and destroys the twin through the driver, by the deployment its record
names; then, whatever that did, deletes its namespace through `kube`, waits for it to go and
fails if it remains.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest
from lightkube import ALL_NS, ApiError
from lightkube.resources import core_v1
from scrubbing import Scrubbed, Scrubbing, scrubbed

from cluster.conftest import Site, gated, run, say, until
from fylgja_core import logs, packages
from fylgja_core.clabernetes import OWNER, OWNER_LABEL, TWIN_LABEL, namespace_of
from fylgja_core.clabernetes.driver import ClabernetesDriver
from fylgja_core.clabernetes.kube import NODE_LABEL, Kube, LightKube, Namespace, Pod, Service
from fylgja_core.credentials import Provider
from fylgja_core.driver import Exec
from fylgja_core.kubeapi import client
from fylgja_core.local_store import LocalStore
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage
from fylgja_core.reconcile import RESTORE_PRINCIPAL, RULE_NODE_MISSING, Reconciler
from fylgja_core.run import Event, Run
from fylgja_core.store import NotFound
from fylgja_core.twin_record import Condition, Node, Spec, Status, TwinRecord
from fylgja_core.verify import Verifier

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINTS = ROOT / "testdata/blueprint"
TWIN = "rst-cluster"
NS = namespace_of(TWIN)
LABELS = {OWNER_LABEL: OWNER, TWIN_LABEL: TWIN}
RESYNC_S = 3600.0
"""The loop's resync, an hour: a pass within a test's window was started by an event."""
STEP_WAIT_S = 180.0
"""How long a restore or a step waits for verify to hold: the server's default."""
CREATE_S = 600.0
STEP_S = 900.0
RESTORE_S = 600.0
"""The most a restore may take to end after the act that caused it."""
SETTLE_S = 5.0
"""How long the twin is left after a run's end, for the passes the kicks folded while the run held
it; none may write."""
BLINK_S = 30.0
"""How long a step's kept pods are watched after the step ends: a kept pod's `Ready` blinked 1.8
to 21 s after its Topology read ready again (verified-facts.md, "the clabernetes driver's calls")."""
QUIET_S = 180.0
"""How long the settled twin is left alone while its pods' changes are counted."""
POLL_S = 1.0
"""How often a test reads the record."""
GONE_S = 180.0
WATCH_S = 30.0
"""The budget of the watch at a compacted version."""
SRL_LINKS = ("info from state / interface ethernet-1/* oper-state",
             "info from state / system lldp interface ethernet-1/* neighbor * system-name")
"""What an SR Linux node is asked of its links: each port's operational state, and the system
name of each neighbour LLDP lists on it."""
EOS_LINKS = ("show interfaces status", "show lldp neighbors")
HOST_LINKS = ["ip", "-4", "-o", "addr"]

type Change = tuple[float, str, Pod]
"""A change the driver's pod watch delivered: the `time.time()` it was read at, its operation and
the pod."""


class Observed:
    """`Kube` over `kube`, every call passed to it: each change its pod watch delivers kept with the
    `time.time()` it was read at, and each pod it deletes and each Service it patches with the
    time of the call."""

    def __init__(self, kube: Kube) -> None:
        self.kube = kube
        self.changes: list[Change] = []
        self.deleted: list[tuple[float, str, str]] = []
        self.patched: list[tuple[float, str, str]] = []

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
        self.patched.append((time.time(), namespace, name))
        await self.kube.patch_service(namespace, name, patch)

    async def delete_pod(self, namespace: str, name: str) -> None:
        self.deleted.append((time.time(), namespace, name))
        await self.kube.delete_pod(namespace, name)

    async def delete_namespace(self, name: str) -> None:
        await self.kube.delete_namespace(name)

    async def exec(self, namespace: str, pod: str, argv: Sequence[str], timeout_s: float) -> Exec:
        return await self.kube.exec(namespace, pod, argv, timeout_s)

    async def watch_pods(self, labels: Mapping[str, str]) -> AsyncGenerator[tuple[str, Pod]]:
        async with contextlib.aclosing(self.kube.watch_pods(labels)) as changes:
            async for operation, pod in changes:
                self.changes.append((time.time(), operation, pod))
                yield operation, pod

    def changes_since(self, at: float, to: float | None = None) -> list[Change]:
        return [c for c in list(self.changes) if c[0] >= at and (to is None or c[0] <= to)
                and c[2].namespace == NS]


class Watching(ClabernetesDriver):
    """The clabernetes driver, each name its `events` yields kept with the `time.time()` it was
    read at."""

    def __init__(self, *args: Any, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.names: list[tuple[float, str]] = []

    async def events(self) -> AsyncIterator[str]:
        async for name in super().events():
            self.names.append((time.time(), name))
            yield name

    def names_since(self, at: float, to: float | None = None) -> list[float]:
        return [t for t, name in list(self.names) if t >= at and (to is None or t <= to) and name == TWIN]


class Timed(Reconciler):
    """The reconciler, each pass's twin and its `time.time()` at its start and end kept in
    `passes`."""

    def __init__(self, *args: Any, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.passes: list[tuple[str, float, float]] = []

    async def reconcile(self, name: str) -> None:
        began = time.time()
        try:
            await super().reconcile(name)
        finally:
            self.passes.append((name, began, time.time()))

    def since(self, at: float) -> list[tuple[float, float]]:
        return [(start, end) for name, start, end in list(self.passes) if name == TWIN and end >= at]


@dataclass
class Held:
    """The store, the module's driver over the session driver's reach (`observed`) and the
    tests' `kube`, the reconciler over them on the session's loop, and the file the loop's log
    writes."""

    loop: asyncio.Runner
    store: LocalStore
    driver: Watching
    kube: LightKube
    reconciler: Timed
    observed: Observed
    platforms: Mapping[str, PlatformPackage] = field(repr=False)
    probes: Mapping[str, ProbePackage] = field(repr=False)
    log: Path
    fixture: str = ""
    """The blueprint the twin runs, once a create or a step of it ended."""
    windows: dict[str, float] = field(default_factory=dict)
    """Each node's boot window, by its package's readiness window."""

    def record(self) -> TwinRecord:
        return self.store.get_twin(TWIN)

    def runs(self) -> list[Run]:
        return self.store.list_runs(TWIN)

    def logged(self, since: float, loggers: tuple[str, ...] = ("fylgja.reconcile",)) -> list[tuple[float, str, str]]:
        """The loop's log lines of `loggers` since `since`: each one's time, level and message."""
        found = []
        for text in self.log.read_text(errors="replace").splitlines():
            try:
                doc = json.loads(text)
            except ValueError:  # a line still being written
                continue
            at = epoch(doc["time"])
            if at >= since and doc["logger"] in loggers:
                found.append((at, doc["level"], doc["message"]))
        return found

    def renewals(self, since: float) -> list[tuple[float, dict[str, Any]]]:
        """The driver's renewals since `since`, from their audit lines: each one's time and the
        line whole, its principal, twin, node, pod, uid and restart count among its members."""
        found = []
        for text in self.log.read_text(errors="replace").splitlines():
            try:
                doc = json.loads(text)
            except ValueError:  # a line still being written
                continue
            at = epoch(doc["time"])
            if at >= since and doc["logger"] == "fylgja.audit" and doc.get("action") == "renew":
                found.append((at, doc))
        return found


@dataclass(frozen=True)
class Restored:
    """A restore read from the act that caused it: the act's `time.time()`, the record before it
    and once the restore settled, the run and its events, each `Ready` the record showed with the
    time it was read, and when the settle was read."""

    began: float
    before: TwinRecord = field(repr=False)
    record: TwinRecord = field(repr=False)
    run: Run = field(repr=False)
    events: list[Event]
    readies: list[tuple[float, str, str | None]]
    settled_at: float


def epoch(stamp: str) -> float:
    return datetime.fromisoformat(stamp).timestamp()


def relative(at: float, origin: float) -> str:
    return f"{at - origin:+.2f} s"


def ready_of(record: TwinRecord) -> Condition:
    """The record's `Ready` condition; one with no status `Unknown`, as a record before its first
    run has none."""
    found = [c for c in record.status.conditions if c.type == "Ready"]
    return found[0] if found else Condition(type="Ready", status="Unknown")


def nodes_of(record: TwinRecord) -> dict[str, Node]:
    return {n.name: n for n in record.status.nodes}


def run_ids(held: Held) -> set[str]:
    return {r.id for r in held.runs()}


def pairs(phase: str, node: str) -> list[tuple[str, str, str | None]]:
    return [(phase, "started", node), (phase, "done", node)]


VERIFIED: list[tuple[str, str, str | None]] = [("verify", "started", None), ("verify", "done", None)]


def described(pod: Pod) -> str:
    """A pod as the tests print it: its node, its uid's first eight characters and its restart
    count, its phase, and whether it is `Ready`, deleting, and its container running or ended."""
    return (f"{pod.labels.get(NODE_LABEL)} {pod.uid[:8]}/{pod.restarts} {pod.phase}{' Ready' if pod.ready else ''}"
            f"{' deleting' if pod.deleting else ''}{' running' if pod.container_running else ''}"
            f"{' ended' if pod.container_ended else ''}")


async def pod_of(held: Held, node: str) -> Pod:
    """The node's one pod not being deleted, read through `kube`."""
    [pod] = [p for p in await held.kube.pods(NS, LABELS) if p.labels.get(NODE_LABEL) == node and not p.deleting]
    return pod


async def settled_run(held: Held, ran: set[str], budget_s: float, what: str,
                      readies: list[tuple[float, str, str | None]]) -> tuple[Run, TwinRecord]:
    """The one run made since `ran`, once it has ended and the record no longer names it, the
    record read each `POLL_S` and each change of its `Ready` kept in `readies`; a failure naming
    `what` once `budget_s` have passed."""
    start = time.time()
    while True:
        record = held.record()
        ready = ready_of(record)
        if (ready.status, ready.reason) != readies[-1][1:]:
            readies.append((time.time(), ready.status, ready.reason))
        made = [r for r in held.runs() if r.id not in ran]
        if made and made[0].state == "ended" and record.status.run_id is None:
            return made[0], record
        if time.time() - start > budget_s:
            pytest.fail(f"{what}: not within {budget_s:g} s; runs made {[(r.operation, r.state) for r in made]}")
        await asyncio.sleep(POLL_S)


async def restored(held: Held, act: Callable[[], Awaitable[object]], what: str) -> Restored:
    """`act` behind the core's back, then the restore it causes, once it ended and the record
    settled it; then `SETTLE_S` for the passes the kicks folded meanwhile, which must write
    nothing and make no run."""
    before, ran = held.record(), run_ids(held)
    readies: list[tuple[float, str, str | None]] = [(time.time(), ready_of(before).status, ready_of(before).reason)]
    began = time.time()
    await act()
    say(f"{what}: done in {time.time() - began:.2f} s")
    run_, record = await settled_run(held, ran, RESTORE_S, f"the restore after {what}", readies)
    settled_at = time.time()
    await asyncio.sleep(SETTLE_S)
    unwritten = held.record().revision == record.revision
    assert unwritten, "a pass after the restore wrote the record"
    made = len(run_ids(held) - ran)
    assert made == 1, f"{made} runs were made"
    return Restored(began=began, before=before, record=record, run=held.store.get_run(run_.id),
                    events=held.store.events(run_.id), readies=readies, settled_at=settled_at)


@dataclass(frozen=True)
class Renewed:
    """A renewal read from the act that caused it: the act's `time.time()`, the record before it and
    once it settled, every run made since, oldest first, each ended, each `Ready` the record showed
    with the time it was read, and when the settle was read."""

    began: float
    before: TwinRecord = field(repr=False)
    record: TwinRecord = field(repr=False)
    runs: list[Run] = field(repr=False)
    readies: list[tuple[float, str, str | None]]
    settled_at: float


async def renewed(held: Held, act: Callable[[], Awaitable[object]], node: str, old: Pod) -> Renewed:
    """`act` behind the core's back, then whatever runs follow, until every run made has ended, the
    record names none, `node` is recorded at another uid than `old`'s and the twin is Ready; then
    `SETTLE_S`, in which no pass may write. The record is read each `POLL_S`."""
    before, ran = held.record(), run_ids(held)
    readies: list[tuple[float, str, str | None]] = [(time.time(), ready_of(before).status, ready_of(before).reason)]
    began = time.time()
    await act()
    while True:
        record = held.record()
        ready = ready_of(record)
        if (ready.status, ready.reason) != readies[-1][1:]:
            readies.append((time.time(), ready.status, ready.reason))
        made = sorted((r for r in held.runs() if r.id not in ran), key=lambda r: r.created_at)
        incarnation = nodes_of(record)[node].incarnation or ""
        if (made and all(r.state == "ended" for r in made) and record.status.run_id is None
                and not incarnation.startswith(f"{old.uid}/") and ready.status == "True"):
            break
        if time.time() - began > RESTORE_S:
            pytest.fail(f"not restored within {RESTORE_S:g} s: runs {[(r.operation, r.state) for r in made]}, Ready "
                        f"{(ready.status, ready.reason)}")
        await asyncio.sleep(POLL_S)
    settled_at = time.time()
    await asyncio.sleep(SETTLE_S)
    unwritten = held.record().revision == record.revision
    assert unwritten, "a pass after the restore wrote the record"
    unmade = run_ids(held) - ran == {r.id for r in made}
    assert unmade, "a run was made after the restore"
    return Renewed(began=began, before=before, record=record, runs=[held.store.get_run(r.id) for r in made],
                   readies=readies, settled_at=settled_at)


def told(held: Held, origin: float, to: float, readies: list[tuple[float, str, str | None]], made: list[Run],
         what: str) -> None:
    """What happened from `what`, at `origin`, to `to`, timed from `origin`: the `Ready` reasons
    seen, the pod watch's changes, the names `events` yielded, the loop's passes and lines, the
    driver's renewals and warnings, and each run's events and verdict, its findings by rule and
    object alone."""
    say(f"Ready seen after {what}: " + ", ".join(f"{relative(at, origin)} {status} {reason}"
                                                  for at, status, reason in readies))
    changes = held.observed.changes_since(origin, to)
    say(f"the pod watch delivered {len(changes)} change(s) of the twin's pods:")
    for at, operation, pod in changes:
        say(f"    {relative(at, origin)} {operation} {described(pod)}")
    names = held.driver.names_since(origin, to)
    say(f"the driver's events named {TWIN} {len(names)} time(s): {[relative(at, origin) for at in names]}")
    passes = held.reconciler.since(origin)
    say(f"the loop's passes over {TWIN}: {[(relative(s, origin), relative(e, origin)) for s, e in passes]}")
    for at, level, message in held.logged(origin):
        say(f"the loop {relative(at, origin)}: {level} {scrubbed(message)}")
    for at, level, message in held.logged(origin, ("fylgja.clabernetes",)):
        if level != "INFO" or message.startswith("events "):
            say(f"the driver {relative(at, origin)}: {level} {scrubbed(message)}")
    for at, doc in held.renewals(origin):
        say(f"the driver {relative(at, origin)}: renewed the pod {doc['pod']} (uid {doc['uid']}, "
            f"{doc['restarts']} restart(s)) of {doc['node']}, audited as {doc['principal']}")
    for each in made:
        steps = ", ".join(f"{e.phase} {e.outcome}{'' if e.node is None else f' {e.node}'} "
                          f"{relative(epoch(e.at), origin)}" for e in held.store.events(each.id)
                          if e.outcome != "started")
        ended_at = epoch(each.ended_at) if each.ended_at else time.time()
        say(f"the {each.operation} run made {relative(epoch(each.created_at), origin)}: {steps}; ended "
            f"{relative(ended_at, origin)}")
        verdict = each.verdict
        if verdict is not None:
            say(f"its verdict: {verdict.operation} {verdict.status}; the wait {verdict.wait}; the last verify's "
                f"counts {verdict.counts}; findings {[(f.severity, f.rule, f.object) for f in verdict.findings]}")


def window_told(held: Held, origin: float, node: str, taken_at: float) -> None:
    """`node`'s boot window, from the first pass since `origin` that saw it gone, against the
    restore's take at `taken_at`."""
    sighted = [at for at, _, message in held.logged(origin) if "each waited for through its boot window" in message
               and f"{node} (" in message]
    window = held.windows[node]
    if sighted:
        say(f"{node}'s boot window: {window:g} s from the first pass that saw it gone, "
            f"{relative(sighted[0], origin)}; the restore taken {relative(taken_at, origin)}, "
            f"{sighted[0] + window - taken_at:.1f} s inside it")
    else:
        say(f"{node}'s boot window: no pass saw it gone; the restore taken {relative(taken_at, origin)}")


def report(held: Held, r: Restored, node: str, what: str) -> None:
    """What the restore of `node` after `what` read (`told`), and its boot window."""
    told(held, r.began, r.settled_at + SETTLE_S, r.readies, [r.run], what)
    window_told(held, r.began, node, epoch(r.run.created_at))


def assert_restored(held: Held, r: Restored, node: str, events: list[tuple[str, str, str | None]]) -> None:
    """The restore, the core's own, ended `ok` with `events`; no pass wrote `twin.node.missing`
    or saw a node past its boot window; `node` recorded at its new incarnation holding the bundle,
    at the address it had, every other node as it was; the twin Ready since the run; and the
    wait settled, so verify held: each link's two ends up and each other's neighbour."""
    run_ = r.run
    taken = (run_.operation, run_.principal)
    assert taken == ("restore", RESTORE_PRINCIPAL), f"the run is {taken}"
    verdict = run_.verdict
    assert verdict is not None, "the restore ended with no verdict"
    ended = (verdict.operation, verdict.status)
    found = [(f.rule, f.object) for f in verdict.findings]
    assert ended == ("restore", "ok"), f"the restore ended {ended}: {found}"
    assert [(e.phase, e.outcome, e.node) for e in r.events] == events
    missing = [reason for _, _, reason in r.readies if reason == RULE_NODE_MISSING]
    past = [level for _, level, message in held.logged(r.began) if "past their boot windows" in message]
    assert not missing and not past, f"a boot window was missed: Ready {RULE_NODE_MISSING} {len(missing)}, {past}"
    was, now = nodes_of(r.before), nodes_of(r.record)
    moved = now[node].incarnation != was[node].incarnation
    assert moved, f"{node}'s incarnation did not move"
    holds = (now[node].holds == r.record.status.bundle_id == r.before.status.bundle_id
             or now[node].holds is was[node].holds is None)
    assert holds, f"{node} does not hold the twin's bundle, nor nothing as before"
    kept = now[node].address == was[node].address
    assert kept, f"{node}'s address moved"
    others = sorted(n for n in now if n != node and now[n] != was[n])
    assert not others, f"nodes other than {node} changed in the record: {others}"
    ready = ready_of(r.record)
    assert (ready.status, ready.reason) == ("True", "twin.ready") and ready.since is not None
    since, made_at, began = epoch(ready.since), epoch(run_.created_at), r.began
    assert since >= made_at > began, "Ready True is not the restore's"
    untouched = (r.record.status.last_step == r.before.status.last_step
                 and r.record.status.observed_generation == r.before.status.observed_generation)
    assert untouched, "the restore wrote last_step or the observed generation"
    settled = verdict.wait is not None and verdict.wait.outcome == "settled"
    assert settled, f"verify did not hold within the restore's wait: {verdict.counts}, {found}"


async def services_local(held: Held, since: float) -> tuple[list[str], list[str]]:
    """The LoadBalancer Services not `Local`, by name, read through the tests' `kube` with no
    `inspect` before (an `inspect` patches a drifted one back); and the Services the driver
    patched since `since`, by name, which a Service that drifted and was patched back would be."""
    drifted = [s.name for s in await held.kube.services(NS) if s.type == "LoadBalancer" and s.traffic_policy != "Local"]
    return drifted, [name for at, _, name in list(held.observed.patched) if at >= since]


async def links(held: Held, node: str, platform: str) -> None:
    """Print what the node says of its links, through the driver's `exec`: an SR Linux node's
    ports' state and its LLDP neighbours, a cEOS node's, or a probe host's addresses."""
    if platform == "nokia_srlinux":
        asked = [["sr_cli", command] for command in SRL_LINKS]
    elif platform == "arista_eos":
        asked = [["Cli", "-p", "15", "-c", command] for command in EOS_LINKS]
    else:
        asked = [HOST_LINKS]
    for argv in asked:
        answer = await held.driver.exec(TWIN, node, argv, 30.0)
        lines = [line.strip() for line in answer.stdout.splitlines() if line.strip()]
        say(f"{node}: {argv[-1]!r} answered {answer.returncode}: {scrubbed(' | '.join(lines))}")


async def created(held: Held, fixture: str) -> TwinRecord:
    """The twin made in the store from `fixture` and kicked, then Ready; the passes its own
    deploy's changes cause write nothing and make no run."""
    blueprint_id, _ = held.store.put_blueprint(json.loads((BLUEPRINTS / f"{fixture}.json").read_text()))
    spec = Spec(blueprint_id=blueprint_id, driver=held.driver.name, allow_restart=False)
    held.store.create_twin(TwinRecord(name=TWIN, revision=1, generation=1, spec=spec,
                                      status=Status(observed_generation=0, conditions=(), nodes=())))
    began = time.time()
    held.reconciler.kick(TWIN)
    readies: list[tuple[float, str, str | None]] = [(began, "Unknown", None)]
    run_, record = await settled_run(held, set(), CREATE_S, f"{TWIN}'s create", readies)
    verdict = run_.verdict
    assert verdict is not None
    say(f"create: {verdict.status} in {time.time() - began:.1f} s; {len(held.driver.names_since(began))} name(s) "
        f"from the driver's events meanwhile")
    ended, found = (run_.operation, verdict.status), [(f.rule, f.object) for f in verdict.findings]
    assert ended == ("create", "ok"), f"the create ended {ended}: {found}"
    condition = ready_of(record)
    assert (condition.status, condition.reason) == ("True", "twin.ready")
    await asyncio.sleep(SETTLE_S)
    operations = [r.operation for r in held.runs()]
    assert operations == ["create"], "the create's own changes made a run"
    unwritten = held.record().revision == record.revision
    assert unwritten, "the create's own changes wrote the record"
    held.fixture = fixture
    return record


async def stepped(held: Held, fixture: str, allow_restart: bool) -> tuple[Run, TwinRecord, float, float]:
    """The twin stepped to `fixture`, its spec written to the store as the API writes one, with the
    next generation, and kicked: the step run, the core's own, once it ended and the record settled
    it, the step's start, and when the settle was read."""
    blueprint_id, _ = held.store.put_blueprint(json.loads((BLUEPRINTS / f"{fixture}.json").read_text()))
    record, ran = held.record(), run_ids(held)
    spec = replace(record.spec, blueprint_id=blueprint_id, allow_restart=allow_restart)
    held.store.update_twin(replace(record, spec=spec, generation=record.generation + 1), record.revision)
    began = time.time()
    held.reconciler.kick(TWIN)
    readies: list[tuple[float, str, str | None]] = [(began, ready_of(record).status, ready_of(record).reason)]
    run_, settled = await settled_run(held, ran, STEP_S, f"the step to {fixture}", readies)
    settled_at = time.time()
    verdict = run_.verdict
    assert verdict is not None
    say(f"the step to {fixture}: {verdict.status} in {settled_at - began:.1f} s; the wait {verdict.wait}; counts "
        f"{verdict.counts}; findings {[(f.severity, f.rule, f.object) for f in verdict.findings]}")
    for e in held.store.events(run_.id):
        if e.outcome != "started":
            say(f"    {e.phase} {e.outcome}{'' if e.node is None else f' {e.node}'} {relative(epoch(e.at), began)}")
    last = settled.status.last_step
    ended, found = (run_.operation, verdict.status), [(f.rule, f.object) for f in verdict.findings]
    assert ended == ("step", "ok"), f"the step ended {ended}: {found}"
    stepped_ = last is not None and last.outcome == "stepped" and last.run_id == run_.id
    assert stepped_, "last_step is not the run's, stepped"
    condition = ready_of(settled)
    assert (condition.status, condition.reason) == ("True", "twin.ready")
    held.fixture = fixture
    return run_, settled, began, settled_at


async def after_step(held: Held, revision: int, recorded: set[str], began: float, settled_at: float) -> None:
    """`BLINK_S` after a step's settle: the changes of the twin's pods and the names `events` gave,
    during the step and after it, a kept pod's `Ready` blinking among them; the passes after the
    step write nothing and make no run."""
    ran = run_ids(held)
    await asyncio.sleep(BLINK_S)
    during = held.observed.changes_since(began, settled_at)
    after = held.observed.changes_since(settled_at)
    say(f"during the step: {len(during)} change(s) of the twin's pods, "
        f"{len(held.driver.names_since(began, settled_at))} name(s) from the driver's events")
    blinks = [(at, pod) for at, operation, pod in after
              if operation == "MODIFIED" and not pod.ready and f"{pod.uid}/{pod.restarts}" in recorded]
    say(f"in the {BLINK_S:g} s after its settle: {len(after)} change(s), "
        f"{len(held.driver.names_since(settled_at))} name(s), passes "
        f"{[(relative(s, settled_at), relative(e, settled_at)) for s, e in held.reconciler.since(settled_at)]}")
    for at, operation, pod in after:
        say(f"    {relative(at, settled_at)} {operation} {described(pod)}")
    say("a kept pod's Ready blinked: " + (", ".join(f"{relative(at, settled_at)} {described(pod)}"
                                                     for at, pod in blinks) if blinks else "no"))
    unmade = run_ids(held) == ran
    assert unmade, "a run was made after the step"
    unwritten = held.record().revision == revision
    assert unwritten, "a pass after the step wrote the record"


@pytest.fixture(scope="module")
def held(site: Site, loop: asyncio.Runner, kube: LightKube, driver: ClabernetesDriver, provider: Provider,
         tmp_path_factory: pytest.TempPathFactory) -> Iterator[Held]:
    """The loop over a store of the module's own, on the session's loop, the twin absent first:
    its driver made as `drivers.make` makes the session's, over the session driver's own reach,
    observed, so the session's driver is left as it is. At the end the loop stopped, the twin
    destroyed through the driver and its namespace gone."""
    root = tmp_path_factory.mktemp(TWIN)
    loaded = packages.load([ROOT / "psp", ROOT / "probes"])
    observed = Observed(driver.kube)
    mine = Watching(observed, provider, controller_namespace=site.controller_namespace, pod_cidr=site.pod_cidr,
                    core_namespace=driver.core_namespace)
    state = run(loop, mine.inspect(TWIN), f"inspect {TWIN}, before").state
    assert state == "absent", f"inspect {TWIN}, before: {state}"
    store = LocalStore.open(root)
    reconciler = Timed(store, {mine.name: mine}, loaded.platforms, loaded.probes, provider, resync_s=RESYNC_S,
                       step_wait_s=STEP_WAIT_S, verifier=Verifier(loaded.platforms, loaded.probes, provider))
    shared = Held(loop=loop, store=store, driver=mine, kube=kube, reconciler=reconciler, observed=observed,
                  platforms=loaded.platforms, probes=loaded.probes, log=root / "loop.log")
    shared.windows = {
        **{name: float(loaded.platforms[platform].readiness.timeout_s)
           for name, platform in (("n1", "nokia_srlinux"), ("n2", "nokia_srlinux"), ("n3", "arista_eos"))},
        "n1-loop-a": float(loaded.probes["ping"].readiness.timeout_s),
    }
    handler = logging.FileHandler(shared.log)
    handler.setFormatter(logs.JsonFormatter())
    handler.addFilter(Scrubbed())
    fylgja = logging.getLogger("fylgja")
    level = fylgja.level
    fylgja.addHandler(handler)
    fylgja.setLevel(logging.INFO)
    scrubbing = Scrubbing()
    logging.setLogRecordFactory(scrubbing)
    started = False
    try:
        run(loop, reconciler.start(), "the reconciler's start")
        started = True
        run(loop, created(shared, "steps/two-node"), f"{TWIN} created by the loop")
        yield shared
    finally:
        failures: list[BaseException] = []
        try:
            if started:
                run(loop, asyncio.wait_for(reconciler.stop(), 120.0), "the reconciler's stop")
            try:
                record: TwinRecord | None = store.get_twin(TWIN)
            except NotFound:
                record = None
            if record is not None and record.status.deployment_id is not None:
                deployment, files = store.get_deployment(record.status.deployment_id)
                run(loop, mine.destroy(deployment, files, loaded.platforms, loaded.probes),
                    f"teardown: destroy {TWIN}")
        except Exception as e:
            say(f"teardown: the stop or the destroy failed: {type(e).__name__}")
            failures.append(e)
        try:
            run(loop, kube.delete_namespace(NS), f"delete_namespace {NS} (the module's end)")
            until(loop, lambda: kube.namespace(NS), lambda found: found is None, GONE_S,
                  f"{NS} gone (the module's end)")
        except (Exception, pytest.fail.Exception) as e:
            say(f"teardown: {NS} not gone: {type(e).__name__}")
            failures.append(e)
        finally:
            fylgja.removeHandler(handler)
            handler.close()
            fylgja.setLevel(level)
            logging.setLogRecordFactory(scrubbing.made)
            store.close()
            say(f"teardown: the loop's log {shared.log}")
        if failures:
            raise failures[0]


def test_a_deleted_pod_is_replaced_and_its_node_pushed_again_without_the_resync(held: Held) -> None:
    """`n2`'s pod deleted through the tests' `kube`: the pod watch, not the resync an hour away,
    starts the restore, which pushes `n2` alone at its new pod's uid."""
    old = run(held.loop, pod_of(held, "n2"), "n2's pod")
    r = run(held.loop, restored(held, lambda: held.kube.delete_pod(NS, old.name), "n2's pod deleted"),
            "n2's pod deleted, until its restore settled")
    report(held, r, "n2", "the delete")
    changes = held.observed.changes_since(r.began, r.settled_at)
    new = [(at, pod) for at, _, pod in changes if pod.labels.get(NODE_LABEL) == "n2" and pod.uid != old.uid]
    ready_at = next((at for at, pod in new if pod.ready), None)
    running_at = next((at for at, pod in new if pod.container_running), None)
    push = next(e for e in r.events if (e.phase, e.outcome) == ("push", "done"))
    say(f"from the delete: the new pod running {None if running_at is None else relative(running_at, r.began)}, "
        f"Ready {None if ready_at is None else relative(ready_at, r.began)}; the run made "
        f"{relative(epoch(r.run.created_at), r.began)}; push done {relative(epoch(push.at), r.began)}")
    deleted = [pod for _, operation, pod in changes if operation == "DELETED"]
    say(f"DELETED: {[described(pod) for pod in deleted]}, carrying the twin's label: "
        f"{[pod.labels.get(TWIN_LABEL) == TWIN for pod in deleted]}")
    assert deleted and all(pod.labels.get(TWIN_LABEL) == TWIN for pod in deleted)
    assert_restored(held, r, "n2", [*pairs("ready", "n2"), *pairs("push", "n2"), *VERIFIED])
    incarnation = nodes_of(r.record)["n2"].incarnation or ""
    now = run(held.loop, pod_of(held, "n2"), "n2's pod")
    assert incarnation.split("/")[0] == now.uid != old.uid
    not_local, patched = run(held.loop, services_local(held, r.began), "the Services")
    assert not not_local and not patched, f"not Local: {not_local}; patched back by the driver: {patched}"
    for node in ("n1", "n2"):
        run(held.loop, links(held, node, "nokia_srlinux"), f"{node}'s links")


def test_a_container_ended_in_its_pod_is_replaced_by_the_driver_and_its_replacement_restored(held: Held) -> None:
    """`n1`'s container ended in its pod (`kill 1`, SIGTERM to its `tini`): restarted there, its
    address would answer nothing again (verified-facts.md, "a container restarted in its pod"), so
    the driver deletes the pod as the watch delivers the container's end, before the kubelet
    restarts it, the Deployment makes it anew, and one restore pushes the replacement inside the
    node's boot window: no `twin.node.missing` at any time, the twin Ready again."""
    old = run(held.loop, pod_of(held, "n1"), "n1's pod")

    async def kill() -> None:
        killed = await held.driver.exec(TWIN, "n1", ["sh", "-c", "kill 1"], 10.0)
        status = killed.returncode
        assert status == 0, f"kill 1 answered status {status}"

    r = run(held.loop, renewed(held, kill, "n1", old), "n1's container ended, until its replacement's restore settled")
    origin, last = r.began, r.runs[-1]
    told(held, origin, r.settled_at + SETTLE_S, r.readies, r.runs, "the kill")
    window_told(held, origin, "n1", epoch(last.created_at))
    changes = held.observed.changes_since(origin, r.settled_at + SETTLE_S)
    deleted = [(at, name) for at, _, name in list(held.observed.deleted) if at >= origin]
    new = run(held.loop, pod_of(held, "n1"), "n1's pod")
    first = {
        "the container's end": next((at for at, _, p in changes if p.uid == old.uid and p.container_ended), None),
        "the deletion": deleted[0][0] if deleted else None,
        "the replacement added": next((at for at, op, p in changes if p.uid == new.uid and op == "ADDED"), None),
        "the replacement running": next((at for at, _, p in changes if p.uid == new.uid and p.container_running), None),
        "the replacement Ready": next((at for at, _, p in changes if p.uid == new.uid and p.ready), None),
        "the restore made": epoch(last.created_at),
        "the restore ended": epoch(last.ended_at) if last.ended_at else None,
    }
    say("from the kill: " + ", ".join(f"{what} {None if at is None else relative(at, origin)}"
                                       for what, at in first.items()))
    once = [name for _, name in deleted] == [old.name]
    assert once, "the driver did not delete n1's pod once"
    counted = [at for at, _, p in changes if p.uid == old.uid and p.restarts > old.restarts and not p.deleting]
    assert not counted, "n1's pod was delivered restarted before it was deleted: not renewed at its container's end"
    renewal = [(doc["principal"], doc["twin"], doc["node"], doc["pod"]) for _, doc in held.renewals(origin)]
    assert renewal == [(RESTORE_PRINCIPAL, TWIN, "n1", old.name)], f"not one audit line for the deletion: {renewal}"
    missing = [reason for _, _, reason in r.readies if reason == RULE_NODE_MISSING]
    past = [level for _, level, message in held.logged(origin) if "past their boot windows" in message]
    assert not missing and not past, f"Ready read {RULE_NODE_MISSING} {len(missing)} time(s), {past}"
    operations = [each.operation for each in r.runs]
    assert operations == ["restore"], f"the runs made: {operations}"
    principal = last.principal
    assert principal == RESTORE_PRINCIPAL, f"the restore's principal is {principal}"
    verdict = last.verdict
    assert verdict is not None
    ended = (verdict.operation, verdict.status)
    found = [(f.rule, f.object) for f in verdict.findings]
    assert ended == ("restore", "ok"), f"the restore ended {ended}: {found}"
    seen = [(e.phase, e.outcome, e.node) for e in held.store.events(last.id)]
    assert seen == [*pairs("ready", "n1"), *pairs("push", "n1"), *VERIFIED]
    settled = verdict.wait is not None and verdict.wait.outcome == "settled"
    assert settled, f"verify did not hold within the restore's wait: {verdict.counts}, {found}"
    was, now = nodes_of(r.before), nodes_of(r.record)
    replaced = new.uid != old.uid and now["n1"].incarnation == f"{new.uid}/0"
    assert replaced, "n1 is not recorded at its replacement's uid"
    holds = now["n1"].holds == r.record.status.bundle_id == r.before.status.bundle_id
    assert holds, "n1 does not hold the twin's bundle"
    kept = now["n1"].address == was["n1"].address
    assert kept, "n1's address moved"
    unchanged = now["n2"] == was["n2"]
    assert unchanged, "n2 changed in the record"
    ready = ready_of(r.record)
    assert (ready.status, ready.reason) == ("True", "twin.ready") and ready.since is not None
    since, made_at = epoch(ready.since), epoch(last.created_at)
    assert since >= made_at, "Ready True is not the restore's"
    for node in ("n1", "n2"):
        run(held.loop, links(held, node, "nokia_srlinux"), f"{node}'s links")


def test_a_settled_twins_pods_are_counted_and_its_passes_write_nothing(held: Held) -> None:
    """The settled twin left alone for `QUIET_S`: what its pods' changes are, what the driver's
    `events` names for them, and that the passes they cause write nothing and make no run."""

    async def quiet() -> tuple[TwinRecord, set[str], float]:
        record, ran, began = held.record(), run_ids(held), time.time()
        await asyncio.sleep(QUIET_S)
        return record, ran, began

    before, ran, began = run(held.loop, quiet(), f"{TWIN} left alone for {QUIET_S:g} s")
    changes = held.observed.changes_since(began)
    by_operation: dict[str, int] = {}
    for _, operation, _ in changes:
        by_operation[operation] = by_operation.get(operation, 0) + 1
    say(f"over {QUIET_S:g} s: {len(changes)} change(s) of the twin's pods {by_operation}, "
        f"{len(held.driver.names_since(began))} name(s) from the driver's events, "
        f"{len(held.reconciler.since(began))} pass(es)")
    for at, operation, pod in changes:
        say(f"    {relative(at, began)} {operation} {described(pod)}")
    unmade = run_ids(held) == ran
    assert unmade, "a run was made"
    unwritten = held.record().revision == before.revision
    assert unwritten, "a pass wrote the record"


def test_a_watch_at_a_compacted_version_is_answered_inside_the_stream(held: Held) -> None:
    """A pod watch asked for at the version `1`, long compacted, through lightkube's client as
    `LightKube` makes it and its handler that raises: k3s answers it with HTTP 200 and an `ERROR`
    event of code 410 (`ApiError`), which lightkube's own retry answers by dropping the version
    (verified-facts.md, "the pod watch, as lightkube runs it"); not an HTTP 410, which it would
    ask for again at the same version."""

    async def answered() -> tuple[str, int | None]:
        reach = client()
        try:
            watch = reach.watch(core_v1.Pod, namespace=ALL_NS, labels={OWNER_LABEL: OWNER}, resource_version="1")
            try:
                async with asyncio.timeout(WATCH_S):
                    async for operation, _ in watch:
                        return f"an event, {operation}", None
            finally:
                if isinstance(watch, AsyncGenerator):
                    await watch.aclose()
        except TimeoutError:
            return f"no event within {WATCH_S:g} s", None
        except ApiError as e:
            return f"ApiError, an ERROR event: {e.status.reason}", e.status.code
        except httpx2.HTTPStatusError as e:
            return "HTTPStatusError, the response's status", e.response.status_code
        finally:
            await reach.close()
        return "the stream ended", None

    form, code = run(held.loop, answered(), "a pod watch at resourceVersion 1")
    say(f"a pod watch at resourceVersion 1: {form}, code {code}")
    assert (form.startswith("ApiError"), code) == (True, 410)


def test_a_step_that_keeps_pods_makes_no_restore(held: Held) -> None:
    """The twin stepped to `three-node-probed`: `n3` and two probe hosts added, `n1` and `n2`
    re-cabled, their pods kept. The step's own changes kick passes while it holds the twin, and
    the passes after it find nothing moved."""
    _, settled, began, settled_at = run(held.loop, stepped(held, "three-node-probed", False),
                                        "the step to three-node-probed")
    recorded = {n.incarnation or "" for n in settled.status.nodes}
    run(held.loop, after_step(held, settled.revision, recorded, began, settled_at), "after the step")


def test_a_probe_hosts_pod_replaced_runs_again_within_its_boot_window(held: Held) -> None:
    """`n1-loop-a`'s pod deleted: the restore readies both hosts and pushes nothing, its window
    the ping package's 30 s."""
    fixture = held.fixture
    assert fixture == "three-node-probed", "the step to three-node-probed failed"
    old = run(held.loop, pod_of(held, "n1-loop-a"), "n1-loop-a's pod")
    r = run(held.loop, restored(held, lambda: held.kube.delete_pod(NS, old.name), "n1-loop-a's pod deleted"),
            "n1-loop-a's pod deleted, until its restore settled")
    report(held, r, "n1-loop-a", "the delete")
    assert_restored(held, r, "n1-loop-a", [*pairs("ready", "n1-loop-a"), *pairs("ready", "n1-loop-b"), *VERIFIED])
    for node, platform in (("n1-loop-a", "linux"), ("n1", "nokia_srlinux")):
        run(held.loop, links(held, node, platform), f"{node}'s links")


def test_a_kind_change_step_replaces_a_pod_and_makes_no_restore(held: Held, provider: Provider) -> None:
    """The twin stepped to `steps/three-node-n3-eos` under `allow_restart`: `n3` recreated as a
    cEOS node, a new pod the step records itself, and the probe hosts removed."""
    gated(provider)
    fixture = held.fixture
    assert fixture == "three-node-probed", "the step to three-node-probed failed"
    _, settled, began, settled_at = run(held.loop, stepped(held, "steps/three-node-n3-eos", True),
                                        "the step to three-node-n3-eos")
    recorded = {n.incarnation or "" for n in settled.status.nodes}
    run(held.loop, after_step(held, settled.revision, recorded, began, settled_at), "after the step")


def test_a_ceos_pod_replaced_runs_again_within_its_boot_window(held: Held, provider: Provider) -> None:
    """`n3`'s pod deleted, a cEOS node: the restore pushes it alone, its window cEOS's 90 s."""
    gated(provider)
    fixture = held.fixture
    assert fixture == "steps/three-node-n3-eos", "the step to three-node-n3-eos failed"
    old = run(held.loop, pod_of(held, "n3"), "n3's pod")
    r = run(held.loop, restored(held, lambda: held.kube.delete_pod(NS, old.name), "n3's pod deleted"),
            "n3's pod deleted, until its restore settled")
    report(held, r, "n3", "the delete")
    assert_restored(held, r, "n3", [*pairs("ready", "n3"), *pairs("push", "n3"), *VERIFIED])
    for node, platform in (("n3", "arista_eos"), ("n2", "nokia_srlinux")):
        run(held.loop, links(held, node, platform), f"{node}'s links")
