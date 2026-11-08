"""The trigger and the restore on the local driver (D-058, D-067). The twin `rst-live`, from
`three-node`, is made in a store of the module's own and reconciled by a `Reconciler` the module
runs in-process, on an event loop in a thread of its own, over the real `ContainerlabDriver`,
whose `events` follows `docker events`. The resync is an hour away (`RESYNC_S`), so every pass
these tests read after the create was started by the driver's event, never by the resync; the
step wait is `STEP_WAIT_S`, so a restore whose verify never holds ends within its test.

Once the twin is Ready, its nodes are replaced behind the core's back, in order:

- `n3` restarted by `docker restart`: a restore run is made within `EVENT_S` of the command's
  return, readies and pushes `n3` alone, waits for verify and ends `ok`, the twin Ready again;
- `n1` stopped from inside, its init sent SIGTERM, and started again by Docker itself under the
  restart policy containerlab gives a `linux` node, a probe host, `always`, where it gives an SR
  Linux node `no`: the same, timed from Docker's own `start`; then `no` again;
- `n2` removed by `docker rm -f`: waited for through SR Linux's boot window, then reported (`Ready`
  False for `twin.node.missing`), with no run made and nothing deployed.

The driver's follower is `cli.follow` itself, wrapped (`Recording`) to keep each line's time and
what it names (its action, its container and a `die`'s exit code), and the reconciler keeps each
pass's start and end (`Timed`); beside them, every action Docker raised for the lab is written to
a file by a second `docker events` the module runs without the driver's filters, and the loop's
log goes to a file as one JSON object a line. Each test prints what it took and saw (`-s`);
nothing printed holds a credential or a configuration. The teardown stops the loop and destroys
the lab through the driver; then, whatever that did or raised, it clears what the host still holds
of the twin, and a `docker events` of this process, and fails for it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from fylgja_core import logs, packages
from fylgja_core.containerlab import cli
from fylgja_core.containerlab.driver import ContainerlabDriver
from fylgja_core.credentials import Provider
from fylgja_core.local_store import LocalStore
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage
from fylgja_core.reconcile import RESTORE_PRINCIPAL, RULE_NODE_MISSING, Reconciler
from fylgja_core.run import Event, Run
from fylgja_core.store import NotFound
from fylgja_core.twin_record import Condition, Spec, Status, TwinRecord
from fylgja_core.verify import Verifier
from live.host import (
    BLUEPRINT,
    CLEAN,
    NEEDS_LOGINS,
    NODES,
    ROOT,
    clean_up_by_hand,
    containerlab_processes,
    docker,
    followers,
    leftovers,
)

TWIN = "rst-live"
RESYNC_S = 3600.0
"""The loop's resync, an hour: a pass within a test's window was started by an event."""
STEP_WAIT_S = 20.0
"""How long a restore waits for verify to hold before it ends with `step.wait.expired`."""
EVENT_S = 10.0
"""The most a restore run may take to be made after the act that caused it."""
RESTORE_S = 150.0
"""The most a restore may take to end after that act: SR Linux's boot, a push and the wait."""
UNTOUCHED_S = 5.0
"""How long after a removal the record must still be as it was, inside the node's boot window."""
REPORTED_S = (59.9, 90.0)
"""When, after the driver's follower read a removal's `die`, `Ready` is False for
`twin.node.missing`: SR Linux's 60 s window from the first pass that saw the node gone, which the
`die`'s name kicked, so after that read, however long before the command's return Docker raised
it. The read is timed by `time.time()` and the window by the loop's `time.monotonic()`: the lower
bound allows 0.1 s between the two clocks."""
CREATE_S = 600.0
SETTLE_S = 3.0
"""How long the twin is left after a run, for the pass a kick folded while the run held it: the
create's own deploy's events, a restart's second event."""
POLL_S = 0.25
RESTART_POLICY = "always"
"""What containerlab 0.81.0 gives a `linux` node, given here to an SR Linux node, which it gives `no`
(verified-facts.md)."""

pytestmark = NEEDS_LOGINS

type Seen = tuple[str, str, str | None]
"""An event as the tests compare it: its phase, its outcome and its node."""


@dataclass(frozen=True)
class Line:
    """A line of `docker events` as it came: the `time.time()` it was read at, the time Docker
    gives it, its action, its container's name and, for a `die`, the exit code."""

    read_at: float
    raised_at: float
    action: str
    container: str
    exit_code: str | None


def line_of(text: str, read_at: float) -> Line | None:
    try:
        event = json.loads(text)
        attributes = event["Actor"]["Attributes"]
        return Line(read_at, int(event["timeNano"]) / 1e9, event["Action"], attributes.get("name", ""),
                    attributes.get("exitCode"))
    except (ValueError, KeyError, TypeError):
        return None


class Recording:
    """The driver's follower: `cli.follow` itself, each line it yields kept as a `Line` as it is
    read, and the times the driver followed the stream counted."""

    def __init__(self) -> None:
        self.lines: list[Line] = []
        self.follows = 0

    async def follow(self, argv: Sequence[str], **kw: Any) -> AsyncGenerator[str]:
        self.follows += 1
        async with contextlib.aclosing(cli.follow(argv, **kw)) as lines:
            async for text in lines:
                if (kept := line_of(text, time.time())) is not None:
                    self.lines.append(kept)
                yield text

    def since(self, at: float) -> list[Line]:
        return [line for line in list(self.lines) if line.read_at >= at]


class Timed(Reconciler):
    """The reconciler, each pass's `time.time()` at its start and its end kept in `passes`, so a
    test reads which pass an event caused and what it did."""

    def __init__(self, *args: Any, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.passes: list[tuple[float, float]] = []

    async def reconcile(self, name: str) -> None:
        began = time.time()
        try:
            await super().reconcile(name)
        finally:
            self.passes.append((began, time.time()))


@dataclass
class Loop:
    """The store, the driver and the reconciler over them, run on `loop` in `thread`; and the
    files the loop's log and the unfiltered `docker events` write."""

    root: Path
    store: LocalStore
    driver: ContainerlabDriver
    reconciler: Timed
    recording: Recording
    platforms: Mapping[str, PlatformPackage]
    probes: Mapping[str, ProbePackage]
    log: Path
    every_event: Path
    loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.new_event_loop)
    thread: threading.Thread | None = None

    def on_loop[T](self, awaitable: Awaitable[T], timeout_s: float) -> T:
        """`awaitable` run on the reconciler's event loop, its result within `timeout_s`."""

        async def wrapped() -> T:
            return await awaitable

        return asyncio.run_coroutine_threadsafe(wrapped(), self.loop).result(timeout_s)

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

    def actions(self, since: float, to: float) -> list[tuple[float, str, str]]:
        """Every action Docker raised for the lab from `since` to `to`, by the unfiltered `docker
        events`: each one's time, action and container."""
        found = []
        for text in self.every_event.read_text(errors="replace").splitlines():
            try:
                event = json.loads(text)
            except ValueError:  # a line still being written
                continue
            at = int(event["timeNano"]) / 1e9
            if since <= at <= to:
                found.append((at, event["Action"], event["Actor"]["Attributes"].get("name", "")))
        return found


def epoch(stamp: str) -> float:
    return datetime.fromisoformat(stamp).timestamp()


def say(text: str) -> None:
    print(f"[rst] {text}", flush=True)


def handle(node: str) -> str:
    return f"clab-{TWIN}-{node}"


def container(node: str, template: str) -> str:
    """`docker inspect --format template` of the node's container."""
    done = docker("inspect", "--format", template, handle(node))
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def act(*argv: str, check: bool = True) -> tuple[float, float]:
    """Run `argv` behind the core's back: the `time.time()` it began and returned at, printed; with
    `check`, its status 0 asserted."""
    began = time.time()
    done = subprocess.run(list(argv), capture_output=True, text=True, timeout=120, check=False)
    returned = time.time()
    say(f"{' '.join(argv)}: status {done.returncode} in {returned - began:.2f}s")
    assert not check or done.returncode == 0, done.stderr[-2000:]
    return began, returned


def until[T](deadline: float, read: Callable[[], T | None], what: str) -> T:
    """`read()` once it answers something, polled each `POLL_S`, failing once `time.time()`
    passes `deadline`."""
    while (value := read()) is None:
        assert time.time() < deadline, f"{what}: not by its deadline"
        time.sleep(POLL_S)
    return value


def ready_of(record: TwinRecord) -> Condition:
    (condition,) = [c for c in record.status.conditions if c.type == "Ready"]
    return condition


def run_ids(loop: Loop) -> set[str]:
    return {r.id for r in loop.runs()}


def new_run(loop: Loop, before: set[str]) -> Run | None:
    return next((r for r in loop.runs() if r.id not in before), None)


def ended(loop: Loop, run_id: str) -> Run | None:
    run = loop.store.get_run(run_id)
    return run if run.state == "ended" else None


def pairs(phase: str, node: str) -> list[Seen]:
    return [(phase, "started", node), (phase, "done", node)]


VERIFIED: list[Seen] = [("verify", "started", None), ("verify", "done", None)]


def relative(at: float, origin: float) -> str:
    return f"{at - origin:+.2f}s"


def report_lines(loop: Loop, began: float, to: float, origin: float) -> None:
    """What `docker events` printed from `began` to `to`, the driver's and the unfiltered one, the
    loop's passes and its lines meanwhile, each timed from `origin`."""
    for line in loop.recording.since(began):
        code = "" if line.exit_code is None else f" exitCode {line.exit_code}"
        say(f"the driver's docker events: {line.action} {line.container}{code}, raised "
            f"{relative(line.raised_at, origin)}, read {relative(line.read_at, origin)}")
    raised = [(relative(at, origin), action, name) for at, action, name in loop.actions(began, to)]
    say(f"every action Docker raised for the lab: {raised}")
    passes = [(relative(start, origin), relative(end, origin)) for start, end in list(loop.reconciler.passes)
              if end >= began]
    say(f"the loop's passes, each from its start to its end: {passes}")
    for at, level, message in loop.logged(began):
        say(f"the loop {relative(at, origin)}: {level} {message}")


def report_run(loop: Loop, run: Run, events: list[Event], began: float, origin: float, what: str) -> None:
    """The run's making, each event's end and the run's, timed from `origin` (`what`), its wait and
    the last verify's counts and findings, after what `docker events` printed and the loop logged."""
    ended_at = epoch(run.ended_at) if run.ended_at else time.time()
    report_lines(loop, began, ended_at, origin)
    steps = ", ".join(f"{e.phase} {e.outcome}{'' if e.node is None else f' {e.node}'} {relative(epoch(e.at), origin)}"
                      for e in events if e.outcome != "started")
    say(f"from {what}: the run made {relative(epoch(run.created_at), origin)}, {steps}, the run ended "
        f"{relative(ended_at, origin)}")
    verdict = run.verdict
    assert verdict is not None
    say(f"the verdict: {verdict.operation} {verdict.status}; the wait {verdict.wait}; the last verify's counts "
        f"{verdict.counts}")
    for f in verdict.findings:
        say(f"  {f.severity} {f.rule} {f.object}: {f.message}")


def interfaces(loop: Loop, node: str) -> list[str]:
    """The node's `/sys/class/net`, through the driver's `exec`."""
    answer = loop.on_loop(loop.driver.exec(TWIN, node, ["ls", "/sys/class/net"], 10.0), 30.0)
    assert answer.returncode == 0, answer
    return answer.stdout.split()


def assert_restored(loop: Loop, node: str, before: TwinRecord, ran: set[str], began: float, origin: float,
                    what: str) -> None:
    """A restore run made within `EVENT_S` of `origin` (`what`), the core's own, ended `ok` within
    `RESTORE_S` of it, after the driver's follower read the node's `die` or `start`, its events
    readying and pushing `node` alone, then waiting for verify; the record holding `node` at its
    container's new incarnation with the bundle, every other node as `before` held it, and the twin
    Ready again since the run. Its timings printed from `origin`."""
    run = until(origin + EVENT_S, lambda: new_run(loop, ran), f"a restore run made after {what}")
    assert (run.operation, run.principal) == ("restore", RESTORE_PRINCIPAL)
    read = [line.read_at for line in loop.recording.since(began)
            if line.container == handle(node) and line.action in ("die", "start")]
    assert read and min(read) <= epoch(run.created_at), "the restore was made before the driver read an event"
    done = until(origin + RESTORE_S, lambda: ended(loop, run.id), "the restore's end")

    def settled() -> TwinRecord | None:  # the run's end is written first, then the record's
        record = loop.record()
        return record if record.status.run_id is None else None

    until(origin + RESTORE_S, settled, "the record's settling of the restore")
    time.sleep(SETTLE_S)  # for the pass a kick folded while the restore held the twin
    record = loop.record()
    events = loop.store.events(run.id)
    report_run(loop, done, events, began, origin, what)
    assert done.verdict is not None and (done.verdict.operation, done.verdict.status) == ("restore", "ok")
    assert [(e.phase, e.outcome, e.node) for e in events] == [*pairs("ready", node), *pairs("push", node), *VERIFIED]
    assert len(run_ids(loop) - ran) == 1, "more than one run was made"
    was = {n.name: n for n in before.status.nodes}
    now = {n.name: n for n in record.status.nodes}
    started = container(node, "{{.State.StartedAt}}")
    assert now[node].incarnation == started != was[node].incarnation
    assert now[node].holds == record.status.bundle_id == before.status.bundle_id
    others = [n for n in NODES if n != node]
    assert [now[n].incarnation for n in others] == [was[n].incarnation for n in others]
    ready = ready_of(record)
    assert (ready.status, ready.reason) == ("True", "twin.ready") and ready.since is not None
    assert epoch(ready.since) >= epoch(run.created_at) > began, "Ready True is not the restore's"
    assert record.status.run_id is None and record.status.last_step is None
    say(f"Ready True {relative(epoch(ready.since), origin)}; {node}'s incarnation {was[node].incarnation} -> "
        f"{started}; its /sys/class/net {interfaces(loop, node)}")


@pytest.fixture(scope="module")
def loop(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Loop]:
    """The loop over a store of the module's own, the twin made and kicked, and Ready; at the end
    the loop stopped, the lab destroyed through the driver and the host held to `CLEAN`."""
    root = tmp_path_factory.mktemp(TWIN)
    loaded = packages.load([ROOT / "psp", ROOT / "probes"])
    provider = Provider(os.environ)
    recording = Recording()
    driver = ContainerlabDriver(root, follower=recording.follow)
    store = LocalStore.open(root)
    reconciler = Timed(store, {driver.name: driver}, loaded.platforms, loaded.probes, provider,
                       resync_s=RESYNC_S, step_wait_s=STEP_WAIT_S,
                       verifier=Verifier(loaded.platforms, loaded.probes, provider))
    held = Loop(root=root, store=store, driver=driver, reconciler=reconciler, recording=recording,
                platforms=loaded.platforms, probes=loaded.probes, log=root / "loop.log",
                every_event=root / "docker-events.ndjson")
    handler = logging.FileHandler(held.log)
    handler.setFormatter(logs.JsonFormatter())
    fylgja = logging.getLogger("fylgja")
    level = fylgja.level
    fylgja.addHandler(handler)
    fylgja.setLevel(logging.INFO)
    with held.every_event.open("wb") as out:
        watcher = subprocess.Popen(
            ["docker", "events", "--filter", "type=container", "--filter", f"label=containerlab={TWIN}",
             "--format", "{{json .}}"],
            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.DEVNULL, env=cli.environment(os.environ),
            start_new_session=True)
    held.thread = threading.Thread(target=held.loop.run_forever, name=f"{TWIN}-loop", daemon=True)
    held.thread.start()
    try:
        held.on_loop(reconciler.start(), 30.0)
        create(held)
        yield held
    finally:
        try:
            close(held)  # what it raises is raised once the host is clean
        finally:
            try:
                with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                    watcher.kill()
                    watcher.wait(timeout=30)
                fylgja.removeHandler(handler)
                handler.close()
                fylgja.setLevel(level)
            finally:
                clean(root, recording, held.log)


def clean(root: Path, recording: Recording, log: Path) -> None:
    """The host held to `CLEAN` and to no `docker events` of this process, whatever the teardown
    did before: what is left is cleared first (the lab by containerlab and `docker`, a follower
    ended), then the module fails for it. A follower found here is this process's own child, not
    yet reaped, so its pid names no other process. A read of the host that raises (`docker` past
    its timeout, say) is a host not known clean: the lab is cleared by hand all the same, and the
    failure says which read raised. The failure replaces the exception the teardown was raising,
    which it shows only as its context, so it names that exception too."""
    in_flight = sys.exception()
    unread: list[str] = []
    left: dict[str, Any] | None = None
    stray: list[int] = []
    try:
        left = leftovers(TWIN)
    except Exception as e:
        unread.append(f"the host's leftovers ({type(e).__name__})")
    try:
        stray = followers(os.getpid())
    except Exception as e:
        unread.append(f"this process's docker events ({type(e).__name__})")
    say(f"teardown: the host holds {left}; docker events of this process {stray}; unread {unread}; the driver "
        f"followed docker events {recording.follows} time(s); the loop's log {log}")
    for pid in stray:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        with contextlib.suppress(ChildProcessError):  # reaped meanwhile by the event loop's child watcher
            os.waitpid(pid, 0)
    if left != CLEAN:
        clean_up_by_hand(root, TWIN)
    if left != CLEAN or stray or unread:
        raising = "" if in_flight is None else f"; the teardown was raising {in_flight!r}"
        pytest.fail(f"the teardown left the host dirty: {left}, docker events {stray}, unread {unread}{raising}",
                    pytrace=False)


def create(loop: Loop) -> None:
    """The twin made in the store and kicked, then Ready; its own deploy's events cost a pass that
    writes nothing and makes no run."""
    blueprint_id, _ = loop.store.put_blueprint(json.loads(BLUEPRINT.read_text()))
    spec = Spec(blueprint_id=blueprint_id, driver=loop.driver.name, allow_restart=False)
    loop.store.create_twin(TwinRecord(name=TWIN, revision=1, generation=1, spec=spec,
                                      status=Status(observed_generation=0, conditions=(), nodes=())))
    began = time.time()
    loop.reconciler.kick(TWIN)

    def settled() -> TwinRecord | None:
        record = loop.record()
        done = record.status.observed_generation == record.generation and record.status.run_id is None
        return record if done else None

    record = until(began + CREATE_S, settled, f"{TWIN}'s create")
    (run,) = loop.runs()
    verdict = run.verdict
    assert verdict is not None
    say(f"create: {verdict.status} in {time.time() - began:.1f}s")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready"), [
        (f.rule, f.object) for f in verdict.findings]
    assert [n.name for n in record.status.nodes] == list(NODES)
    time.sleep(SETTLE_S)
    starts = [line for line in loop.recording.since(began) if line.action == "start"]
    say(f"the deploy's docker events, read by the driver: {[(line.action, line.container) for line in starts]}")
    assert sorted(line.container for line in starts) == [handle(n) for n in NODES]
    assert [r.operation for r in loop.runs()] == ["create"], "the create's own events made a run"
    assert loop.record().revision == record.revision, "the create's own events wrote the record"


def close(loop: Loop) -> None:
    """Stop the loop, then destroy the lab through the driver, by the deployment the record names;
    the event loop and the store closed whatever happened."""
    try:
        loop.on_loop(loop.reconciler.stop(), 60.0)
        try:
            record: TwinRecord | None = loop.record()
        except NotFound:
            record = None
        if record is not None and record.status.deployment_id is not None:
            deployment, files = loop.store.get_deployment(record.status.deployment_id)
            began = time.time()
            loop.on_loop(loop.driver.destroy(deployment, files, loop.platforms, loop.probes), 300.0)
            say(f"teardown: the driver's destroy in {time.time() - began:.2f}s")
    finally:
        try:
            loop.loop.call_soon_threadsafe(loop.loop.stop)
            assert loop.thread is not None
            loop.thread.join(30)
            loop.loop.close()
        finally:
            loop.store.close()


def test_a_restarted_node_is_pushed_again_within_seconds_of_answering(loop: Loop) -> None:
    """`docker restart`: Docker raises `die` then `start`, and the driver's event, not the resync an
    hour away, starts the restore."""
    before, ran = loop.record(), run_ids(loop)
    assert container("n3", "{{.State.StartedAt}}") == {n.name: n for n in before.status.nodes}["n3"].incarnation
    began, returned = act("docker", "restart", handle("n3"))
    assert_restored(loop, "n3", before, ran, began, returned, "the restart's return")


def test_a_node_docker_starts_again_by_itself_is_pushed_again(loop: Loop) -> None:
    """A container that dies and is started again by Docker itself, under a restart policy: the
    restore is timed from the `start` Docker raised, which no command of the test's returns at."""
    policy = container("n1", "{{json .HostConfig.RestartPolicy}}")
    say(f"the restart policy containerlab gave n1, an SR Linux node: {policy}")
    assert json.loads(policy)["Name"] == "no"
    act("docker", "update", "--restart", RESTART_POLICY, handle("n1"))
    try:
        restarts = int(container("n1", "{{.RestartCount}}"))
        before, ran = loop.record(), run_ids(loop)
        # Its status may be the container's death, which ends the command with it.
        began, returned = act("docker", "exec", "--user", "0", handle("n1"), "sh", "-c", "kill -TERM 1", check=False)

        def started() -> Line | None:
            return next((line for line in loop.recording.since(began)
                         if line.action == "start" and line.container == handle("n1")), None)

        start = until(returned + 60.0, started, "Docker's own start of n1")
        say(f"Docker started n1 again {relative(start.raised_at, returned)} after the kill's return; its restart "
            f"count {restarts} -> {container('n1', '{{.RestartCount}}')}")
        assert int(container("n1", "{{.RestartCount}}")) == restarts + 1
        assert_restored(loop, "n1", before, ran, began, start.read_at, "Docker's start")
    finally:  # containerlab's own policy again, for the tests after and for a node a teardown would miss
        act("docker", "update", "--restart", "no", handle("n1"))


def test_a_removed_node_is_reported_missing_and_never_made(loop: Loop) -> None:
    """`docker rm -f`: the node is waited for through SR Linux's boot window, from the first pass
    that saw it gone, then reported; no run is made and nothing is deployed to make it."""
    before, ran = loop.record(), run_ids(loop)
    assert (ready_of(before).status, ready_of(before).reason) == ("True", "twin.ready")
    began, returned = act("docker", "rm", "-f", handle("n2"))
    deploying: set[int] = set()
    while time.time() < returned + UNTOUCHED_S:
        record = loop.record()
        assert record.revision == before.revision and ready_of(record).status == "True", "written within its window"
        deploying |= set(containerlab_processes())
        time.sleep(POLL_S)

    def reported() -> TwinRecord | None:
        deploying.update(containerlab_processes())
        record = loop.record()
        return record if ready_of(record).reason == RULE_NODE_MISSING else None

    record = until(returned + REPORTED_S[1], reported, f"Ready False for {RULE_NODE_MISSING}")
    ready = ready_of(record)
    assert ready.status == "False" and ready.since is not None
    report_lines(loop, began, time.time(), returned)
    dies = [line for line in loop.recording.since(began) if line.action == "die" and line.container == handle("n2")]
    assert dies, "the driver's follower read no die of n2"
    after = epoch(ready.since) - dies[0].read_at
    say(f"Ready False for {RULE_NODE_MISSING} {after:.2f}s after the driver read n2's die (read "
        f"{relative(dies[0].read_at, returned)} from the removal's return), the record's revision {before.revision} "
        f"-> {record.revision}")
    assert REPORTED_S[0] <= after <= REPORTED_S[1]
    assert record.revision == before.revision + 1, "the record was written more than once over the window"
    assert run_ids(loop) == ran, "a run was made"
    names = docker("ps", "-a", "--filter", f"label=containerlab={TWIN}", "--format", "{{.Names}}").stdout.split()
    assert sorted(names) == [handle("n1"), handle("n3")]
    assert not deploying, f"a containerlab process ran: {sorted(deploying)}"
    commands = [message for _, _, message in loop.logged(began, ("fylgja.containerlab",))]
    assert not [c for c in commands if c.startswith("containerlab ")], commands
    assert [n.name for n in record.status.nodes] == list(NODES) and record.status.run_id is None
