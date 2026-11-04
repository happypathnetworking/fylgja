"""The reconcile loop: each twin record driven toward its desired state, a bundle, through its
driver, as runs with events (Constitution VIII, D-023, D-025).

One pass (`Reconciler.reconcile`) reads the record and acts on it. A create runs these phases,
in order, each recorded in the record by compare-and-set before the next begins, so a restarted
core resumes after the last one recorded:

- `compiled`: the spec's blueprint compiled and its bundle filed (or the spec's bundle read);
- `admitted`: the driver's `admit`, against every other twin's recorded allocation, one twin
  at a time, and the allocation it answers;
- `planned`: the driver's pure `plan` with that allocation, and the deployment filed;
- `applied`: the driver's `apply`, then every node `inspect` reports, holding nothing yet;
- `ready`: each device node's push transport answers (a probe host's readiness is phase 5's);
- `pushed`: each device node pushed its configuration; the bundle it holds is recorded at once.

A twin whose deletion was asked is torn down by a destroy run instead (D-025): a create still
in flight is cancelled first, then the driver's `destroy` removes the deployment, `destroyed`
is recorded, and the record is deleted.

Every phase emits run events: `started`, then `done`, `skipped`, `failed`, `timed_out` or
`cancelled`, with the seconds since `started`, and on a failure the rule; `ready` and `push`
emit a pair per node.

A resume runs the phase after the one recorded, under the run the record names. Two rules make
it reach the desired state in that one pass (D-023): a lab present while the record lacks
`applied` is probed, and applied again with `reconfigure` when a device node stays silent (it is
missing, stopped, without an address, or does not answer), or not at all when every one answers;
and a node already holding the bundle is never pushed again.

Failures are of two classes. **A failure only a new spec can clear** (a refused admission, an
uncompilable blueprint, a refused plan, a node that does not become ready, a refused or
unauthorized push, a missing credential, a driver this core does not serve) ends the run
`rejected` (nothing was built) or `failed`, cleans up, and sets `observed_generation`, so the
loop waits for the spec to be written again; unless the twin's deletion was asked meanwhile,
whose generation the destroy run settles, by deleting the record. **A transient failure** (the driver's
`DriverFailed`, an unreachable node, a store's `OSError` or lost compare-and-set) leaves the
record as it is, logs, and queues the twin again after a backoff that doubles from 1 s to 60 s
and resets on a pass that completes.

**Cancelling** a create marks its run `cancelling` in the store. The loop reads the mark
between phases and before each node's readiness wait and push, and watches it during every
call on the runtime, which it stops; then it cleans up and ends the run `failed` with the
finding `run.cancelled`. A destroy run is never stopped halfway: it completes.

The run's verdict is written before the record's last write, so a core stopped between the two
loses neither: a pass that finds the record naming an ended run completes that write from the
verdict. Cleanup is then the driver's `destroy`, when a deployment was filed, and the record's
nodes, deployment and allocation cleared; a destroy that fails keeps the allocation, so a
lingering network's subnet stays reserved, and is retried on the next pass.

The loop is scheduled by its work queue (D-023): `start` queues every twin in the store and
starts the workers and a periodic resync, a client's write `kick`s its twin, and a transient
failure queues its twin again after the backoff. `dry_run` runs a create's admission and plan
and writes nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from fylgja_core import blueprint, bundle, clock, compiler, findings, logs, push, store
from fylgja_core import run as runs
from fylgja_core.bundle import Manifest
from fylgja_core.credentials import Credential, Missing, Provider
from fylgja_core.deployment import Deployment
from fylgja_core.driver import Driver, DriverFailed, Inspection, Refusal, Unplannable
from fylgja_core.findings import Finding, Subject, Verdict
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage
from fylgja_core.queue import Workers, WorkQueue
from fylgja_core.readiness import RULE_TIMEOUT, RULE_UNAUTHORIZED, NotReady, await_transport
from fylgja_core.run import Event, Outcome, Run
from fylgja_core.twin_record import Condition, Node, Spec, TwinRecord

# Rule ids: findings the loop files and the reasons it sets on the Ready condition; the
# catalogue is docs/rules.md.
RULE_BLUEPRINT_MISSING = "blueprint.missing"
RULE_BUNDLE_MISSING = "bundle.missing"
RULE_BUNDLE_REJECTED = "bundle.rejected"
RULE_PLAN_REJECTED = "plan.rejected"
RULE_CANCELLED = "run.cancelled"
RULE_DRIVER_UNKNOWN = "twin.driver.unknown"
REASON_READY = "twin.ready"
REASON_CREATING = "twin.creating"
REASON_DELETING = "twin.deleting"

BACKOFF_FIRST_S = 1.0
BACKOFF_CEILING_S = 60.0

# The phases of a create, as the record names each once done, and the run events' names for them.
CREATE: tuple[tuple[str, runs.Phase], ...] = (
    ("compiled", "compile"),
    ("admitted", "admit"),
    ("planned", "plan"),
    ("applied", "apply"),
    ("ready", "ready"),
    ("pushed", "push"),
)

# What the loop retries with a backoff, leaving the record as it is.
TRANSIENT: tuple[type[Exception], ...] = (DriverFailed, push.Unreachable, OSError, store.Conflict)

PushFn = Callable[[str, PlatformPackage, str, Credential], Awaitable[push.Pushed | push.Refused]]
"""The push's shape, `push.push`'s: a node's address, its package, its configuration and its login."""


class ReadyFn(Protocol):
    """The readiness wait's shape, `readiness.await_transport`'s: the seconds until the node's
    push transport answered, or `NotReady`; the loop passes the package's budget as `timeout_s`."""

    def __call__(
        self, address: str, package: PlatformPackage, credential: Credential, /, *, timeout_s: float | None = None
    ) -> Awaitable[float]: ...


_log = logging.getLogger("fylgja.reconcile")


def next_backoff(previous: float | None) -> float:
    """The delay before a twin's next try after a transient failure: 1 s, then twice the last, at most 60 s."""
    return BACKOFF_FIRST_S if previous is None else min(previous * 2, BACKOFF_CEILING_S)


def ready_condition(
    conditions: Iterable[Condition], status: Literal["True", "False"], reason: str
) -> tuple[Condition, ...]:
    """`conditions` with Ready set to `status` for `reason`; its `since` changes only when its status does."""
    conditions = tuple(conditions)
    old = next((c for c in conditions if c.type == "Ready"), None)
    since = old.since if old is not None and old.status == status and old.since else clock.now()
    return (Condition(type="Ready", status=status, reason=reason, since=since),
            *(c for c in conditions if c.type != "Ready"))


class _Failed(Exception):
    """A failure only a new spec can clear: the run ends `status` with `found`, and the Ready
    condition and the failing event carry `reason`."""

    def __init__(
        self,
        status: Literal["rejected", "failed"],
        reason: str,
        found: Iterable[Finding],
        outcome: Outcome = "failed",
    ) -> None:
        self.status: Literal["rejected", "failed"] = status
        self.reason = reason
        self.findings = findings.order(found)
        self.outcome = outcome
        self.recorded = False  # whether a step wrote its ending event
        super().__init__(reason)


class _Cancelled(Exception):
    """The run was marked cancelling: the pass stops where it is and runs the cancel path."""


class _Retry(Exception):
    """A transient failure inside a run, carrying the run's id for the log line."""

    def __init__(self, error: Exception, run_id: str) -> None:
        self.error = error
        self.run_id = run_id
        super().__init__(str(error))


@dataclass
class _Step:
    outcome: Outcome = "done"
    rule: str | None = None


@dataclass
class _Pass:
    """One pass's working state: the record as last written, the run, and what the phases read."""

    record: TwinRecord
    run: Run
    driver: Driver
    manifest: Manifest | None = None
    files: Mapping[str, bytes] | None = None
    deployment: Deployment | None = None
    deployment_files: Mapping[str, bytes] | None = None

    @property
    def name(self) -> str:
        return self.record.name

    def fields(self, **kw: Any) -> dict[str, Any]:
        return logs.fields(twin=self.name, run=self.run.id, **kw)


class Reconciler:
    """The loop over a store: the passes, the queue and workers they are scheduled by, the
    resync, and each twin's backoff. `cancel_poll_s` is how often a call on the runtime looks
    for its run's cancellation.

    `start` runs it on the event loop that calls it: the queue, the admission lock and the
    workers are made there, since asyncio's primitives bind to the first loop that waits on
    them, so a reconciler stopped on one loop starts cleanly on another. `start` twice without
    a `stop` is `RuntimeError`. `kick` may be called from any thread once started; before
    `start`, only from a running loop. `reconcile` may be called directly, without `start`, on
    one loop at a time."""

    def __init__(
        self,
        store: store.Store,
        drivers: Mapping[str, Driver],
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        credentials: Provider,
        *,
        workers: int = 4,
        resync_s: float = 300.0,
        pusher: PushFn = push.push,
        readiness: ReadyFn = await_transport,
        cancel_poll_s: float = 0.5,
    ) -> None:
        self.store = store
        self.drivers = drivers
        self.platforms = platforms
        self.probe_packages = probe_packages
        self.credentials = credentials
        self.workers = workers
        self.resync_s = resync_s
        self.pusher = pusher
        self.readiness = readiness
        self.cancel_poll_s = cancel_poll_s
        self.queue = WorkQueue()
        # Each twin's delay after its last transient failure; a pass that completes drops it.
        self.backoff: dict[str, float] = {}
        # Admission and its record, one twin at a time: `reserved` is all that keeps two creates off one subnet.
        self._admission = asyncio.Lock()
        self._workers: Workers | None = None
        self._resync: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopped = False  # whether `stop` ran since the last `start`

    # The schedule.

    async def start(self) -> None:
        """Queue every twin in the store, then start the workers and the resync, which queues
        every twin again each `resync_s`, so a missed trigger is only late (D-023). A new queue
        and admission lock are made on this loop; `RuntimeError` when already started."""
        if self._workers is not None:
            raise RuntimeError("the reconciler is started: stop it first")
        self._loop = asyncio.get_running_loop()
        self._stopped = False
        self.queue = WorkQueue()
        self._admission = asyncio.Lock()
        for record in self.store.list_twins():
            self.queue.put(record.name)
        self._workers = Workers(self.queue, self.reconcile, self.workers)
        await self._workers.start()
        self._resync = asyncio.create_task(self._resync_every())

    async def stop(self) -> None:
        """Stop the resync and the workers. A pass cut short resumes from its record at the next start."""
        if self._resync is not None:
            self._resync.cancel()
            await asyncio.gather(self._resync, return_exceptions=True)
            self._resync = None
        if self._workers is not None:
            await self._workers.stop()
            self._workers = None
        self._loop = None
        self._stopped = True

    def kick(self, name: str) -> None:
        """Queue the twin `name` at once: a client wrote its record. From another thread (or
        loop) than the one the reconciler runs on, the queue is handed the name on its own loop."""
        try:
            running: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is not None and running is not self._loop:
            self._loop.call_soon_threadsafe(self.queue.put, name)
        elif running is None:
            when = "after stop" if self._stopped else "before start"
            raise RuntimeError(f"kick {when} needs a running event loop: the reconciler runs on none")
        else:
            self.queue.put(name)

    async def _resync_every(self) -> None:
        while True:
            await asyncio.sleep(self.resync_s)
            try:
                names = [record.name for record in self.store.list_twins()]
            except (OSError, store.StoreError) as e:
                _log.warning("resync: the store's twins could not be listed: %s", e,
                             **logs.fields(error=type(e).__name__))
                continue
            for name in names:
                self.queue.put(name)

    # A pass.

    async def reconcile(self, name: str) -> None:
        """One pass over the twin `name`. A transient failure raises nothing: it is logged and the
        twin queued again after its backoff, the record left as it is."""
        try:
            await self._pass(name)
        except _Retry as e:
            self._retry(name, e.error, e.run_id)
        except TRANSIENT as e:
            self._retry(name, e, None)
        else:
            self.backoff.pop(name, None)

    def _retry(self, name: str, error: Exception, run_id: str | None) -> None:
        delay = next_backoff(self.backoff.get(name))
        self.backoff[name] = delay
        known: dict[str, Any] = {"twin": name} if run_id is None else {"twin": name, "run": run_id}
        _log.warning("%s: %s: %s; trying again in %gs", name, type(error).__name__, error, delay,
                     **logs.fields(**known, error=type(error).__name__, retry_s=delay))
        self.queue.put(name, delay_s=delay)

    async def _pass(self, name: str) -> None:
        try:
            record = self.store.get_twin(name)
        except store.NotFound:
            return
        driver = self.drivers.get(record.spec.driver)
        if driver is None:
            await self._unserved(record)
            return
        if record.status.run_id is not None:
            named = self._read_run(record.status.run_id)
            if named is not None and named.state == "ended":
                # The run's end was recorded and the record's last write was not, or its cleanup is owed.
                try:
                    await self._settle(record, named, driver)
                except TRANSIENT as e:
                    raise _Retry(e, named.id) from e
                try:
                    record = self.store.get_twin(name)
                except store.NotFound:  # a destroy run's settling deletes the record
                    return
        if record.deletion_requested_at is not None:
            await self._delete(record, driver)
        elif record.generation != record.status.observed_generation:
            await self._create(record, driver)

    async def _create(self, record: TwinRecord, driver: Driver) -> None:
        if record.status.run_id is None:
            lacking = self._lacking(record)
            if lacking:
                # A deployment this core cannot tear down is kept: a new spec over it would compile over its
                # bundle, admit over its allocation, and leave a cleanup no one here can do. Refused, untouched.
                await self._refuse(record, RULE_BUNDLE_REJECTED, lacking)
                return
        record, run = self._take_run(record, "create", REASON_CREATING)
        p = _Pass(record=record, run=run, driver=driver)
        current: runs.Phase | None = None
        work: Mapping[runs.Phase, Callable[[_Pass], Awaitable[None]]] = {
            "compile": self._compile, "admit": self._admit, "plan": self._plan,
            "apply": self._apply, "ready": self._ready, "push": self._push,
        }
        try:
            try:
                try:
                    for recorded, phase in self._phases_after(p.record.status.phase):
                        current = phase
                        await self._checkpoint(p)
                        await work[phase](p)
                        _log.info("%s: %s", p.name, recorded, **p.fields(phase=phase))
                    await self._checkpoint(p)
                    await self._end(p, "ok", (), None)
                except _Failed as failure:
                    if not failure.recorded and current is not None:  # failed outside a step: its ending event
                        self._event(p, current, failure.outcome, rule=failure.reason)
                    await self._end(p, failure.status, failure.findings, failure.reason)
            except _Cancelled:
                await self._cancel(p)
        except TRANSIENT as e:
            raise _Retry(e, p.run.id) from e

    async def _delete(self, record: TwinRecord, driver: Driver) -> None:
        """Tear the twin down and delete its record (D-025): a create in flight is cancelled
        first, through the cancel path, and any create run that never started is ended
        cancelled; then the destroy run."""
        named = self._read_run(record.status.run_id) if record.status.run_id is not None else None
        if named is not None and named.operation == "create" and named.state != "ended":
            try:
                if named.state != "cancelling":
                    cancelling = replace(named, state="cancelling")
                    self.store.update_run(cancelling, named.state)
                    named = cancelling
                await self._cancel(_Pass(record=record, run=named, driver=driver))
            except TRANSIENT as e:
                raise _Retry(e, named.id) from e
            record = self.store.get_twin(record.name)
        for stray in self.store.list_runs(record.name):
            if stray.operation == "create" and stray.state != "ended":
                self._cancel_unstarted(record, stray, driver)
        lacking = self._lacking(record)
        if lacking:  # the deployment cannot be torn down without its packages: wait for a core that has them
            await self._refuse(record, RULE_BUNDLE_REJECTED, lacking)
            return
        record, run = self._take_run(record, "destroy", REASON_DELETING)
        p = _Pass(record=record, run=run, driver=driver)
        subject = self._subject(p.record, p.run)  # before `destroyed` clears the deployment it names
        try:
            if p.record.status.phase != "destroyed":
                async with self._step(p, "destroy"):
                    if p.record.status.deployment_id is not None:
                        deployment, files = self._deployment(p)
                        await driver.destroy(deployment, files, self.platforms, self.probe_packages)
                    p.record = self._write(p.record, p.run, phase="destroyed", nodes=(), deployment_id=None,
                                           allocation=None)
            await self._end(p, "ok", (), None, subject)
        except TRANSIENT as e:
            raise _Retry(e, p.run.id) from e

    async def _unserved(self, record: TwinRecord) -> None:
        """A spec naming a driver this core does not serve: a failure only a new spec (or a core
        serving that driver) can clear, refused with `twin.driver.unknown`; a twin with nothing
        asked of it is left alone."""
        status = record.status
        asked = record.deletion_requested_at is not None or record.generation != status.observed_generation
        if not asked and not any(r.state != "ended" for r in self.store.list_runs(record.name)):
            return
        served = ", ".join(sorted(self.drivers)) or "none"
        finding = Finding(rule=RULE_DRIVER_UNKNOWN, severity="error", object=record.name,
                          message=f"The spec's driver {record.spec.driver!r} is not one this core serves ({served}).")
        await self._refuse(record, RULE_DRIVER_UNKNOWN, [finding])

    async def _refuse(self, record: TwinRecord, reason: str, found: Iterable[Finding]) -> None:
        """What this core cannot do for the twin at all, whatever is asked (a driver it does not
        serve, a teardown without the packages): every run of the twin in flight ends `rejected`
        with `found`, and Ready is False for `reason`, once; nothing is torn down."""
        status = record.status
        in_flight = [r for r in self.store.list_runs(record.name) if r.state != "ended"]
        settled = (ready_reason(status.conditions) == reason and status.run_id is None
                   and status.observed_generation == record.generation)
        if not in_flight and settled:
            return
        ordered = findings.order(found)
        for run in in_flight:
            verdict = Verdict(operation=run.operation, status="rejected", subject=self._subject(record, run),
                              findings=ordered)
            self.store.update_run(runs.ended(run, verdict), run.state)
            _log.warning("%s: run %s ended rejected: %s", record.name, run.id, reason,
                         **logs.fields(twin=record.name, run=run.id, reason=reason))
        if not settled:
            principal = in_flight[0].principal if in_flight else "core"
            self._write_as(record, principal, None, conditions=ready_condition(status.conditions, "False", reason),
                           observed_generation=record.generation, run_id=None)

    # The run.

    def _read_run(self, run_id: str) -> Run | None:
        try:
            return self.store.get_run(run_id)
        except store.NotFound:
            return None

    def _take_run(self, record: TwinRecord, operation: runs.Operation, reason: str) -> tuple[TwinRecord, Run]:
        """The run this pass acts under, and the record naming it with Ready False for `reason`:
        the run the record names, if it is of `operation` and has not ended; else the newest run
        of the twin and `operation` queued (or cancelled before it started); else a new one, the
        core's. The record names it before it is marked running, so a core stopped between the
        two finds it again; one the API marked cancelling meanwhile stays so, to be cancelled."""
        named = self._read_run(record.status.run_id) if record.status.run_id is not None else None
        run = named if named is not None and named.operation == operation and named.state != "ended" else None
        if run is None:
            waiting = [r for r in self.store.list_runs(record.name)
                       if r.operation == operation and r.state in ("queued", "cancelling")]
            if waiting:
                run = waiting[0]
            else:
                run = runs.queued(record.name, operation, "core")
                self.store.create_run(run)
        conditions = ready_condition(record.status.conditions, "False", reason)
        if record.status.run_id != run.id or conditions != record.status.conditions:
            record = self._write(record, run, run_id=run.id, conditions=conditions)
        if run.state == "queued":
            try:
                running = replace(run, state="running")
                self.store.update_run(running, "queued")
                run = running
            except store.Conflict:
                run = self.store.get_run(run.id)
                if run.state != "cancelling":
                    raise
            _log.info("%s: %s run %s started", record.name, operation, run.id,
                      **logs.fields(twin=record.name, run=run.id))
        else:
            _log.info("%s: %s run %s resumed after %s", record.name, operation, run.id,
                      record.status.phase or "nothing", **logs.fields(twin=record.name, run=run.id))
        return record, run

    @staticmethod
    def _phases_after(phase: str | None) -> tuple[tuple[str, runs.Phase], ...]:
        names = [recorded for recorded, _ in CREATE]
        if phase is None:
            return CREATE
        return CREATE[names.index(phase) + 1:] if phase in names else ()

    async def _check_cancel(self, run_id: str) -> bool:
        """Whether the run is marked cancelling in the store."""
        return self.store.get_run(run_id).state == "cancelling"

    async def _checkpoint(self, p: _Pass) -> None:
        if await self._check_cancel(p.run.id):
            raise _Cancelled

    async def _runtime[**A, T](self, p: _Pass, call: Callable[A, Awaitable[T]], *args: A.args, **kw: A.kwargs) -> T:
        """`call(*args, **kw)` awaited, a call on the runtime (the driver, a readiness wait, a
        push), unless the run is cancelling: then, or once it is marked so meanwhile, the call is
        stopped (D-023) and `_Cancelled` raised. A call that ends first, answering or failing,
        ends it."""
        await self._checkpoint(p)
        task: asyncio.Future[T] = asyncio.ensure_future(call(*args, **kw))
        watch = asyncio.ensure_future(self._until_cancelling(p.run.id))
        try:
            done, _ = await asyncio.wait((task, watch), return_when=asyncio.FIRST_COMPLETED)
        finally:
            task.cancel()
            watch.cancel()
            await asyncio.gather(task, watch, return_exceptions=True)
        if task in done:
            return task.result()
        watch.result()  # the store's failure, if that is what ended the watch
        _log.info("%s: run %s marked cancelling: its call on the runtime is stopped", p.name, p.run.id, **p.fields())
        raise _Cancelled

    async def _until_cancelling(self, run_id: str) -> None:
        while not await self._check_cancel(run_id):
            await asyncio.sleep(self.cancel_poll_s)

    async def _cancel(self, p: _Pass) -> None:
        """The cancel path (D-023): events `cancel started`, the cleanup (`destroy` when a
        deployment was filed, and the record's nodes, deployment and allocation cleared), and
        `cancel done` carrying `run.cancelled`; then the run ends `failed` with that finding,
        and Ready is False for it. A core stopped meanwhile finds the run still cancelling and
        runs the path again."""
        p.run = self.store.get_run(p.run.id)
        subject = self._subject(p.record, p.run)
        message = "The run was cancelled before it had built anything."
        async with self._step(p, "cancel") as step:
            step.rule = RULE_CANCELLED
            if p.record.status.deployment_id is not None:
                if self._lacking(p.record):
                    message = ("The run was cancelled; what it had built is kept, since this core lacks the "
                               "packages to tear it down.")
                else:
                    deployment, files = self._deployment(p)
                    await p.driver.destroy(deployment, files, self.platforms, self.probe_packages)
                    p.record = self._write(p.record, p.run, nodes=(), deployment_id=None, allocation=None,
                                           phase=None)
                    message = "The run was cancelled, and what it had built was torn down."
        verdict = Verdict(operation=p.run.operation, status="failed", subject=subject,
                          findings=(Finding(rule=RULE_CANCELLED, severity="error", object=p.name, message=message),))
        ended = runs.ended(p.run, verdict)
        self.store.update_run(ended, p.run.state)
        _log.info("%s: run %s cancelled", p.name, ended.id, **p.fields(status="failed", reason=RULE_CANCELLED))
        await self._settle(p.record, ended, p.driver, RULE_CANCELLED)

    def _cancel_unstarted(self, record: TwinRecord, run: Run, driver: Driver) -> None:
        """A create run of a twin being deleted that never started: its cancel events and end;
        it built nothing, so it cleans nothing up."""
        finding = Finding(rule=RULE_CANCELLED, severity="error", object=record.name,
                          message="The run was cancelled before it started: the twin's deletion was asked.")
        verdict = Verdict(operation=run.operation, status="failed", subject=Subject(twin=record.name, run_id=run.id),
                          findings=(finding,))
        self.store.update_run(runs.ended(run, verdict), run.state)  # first: a lost update repeats no events
        p = _Pass(record=record, run=run, driver=driver)
        self._event(p, "cancel", "started")
        self._event(p, "cancel", "done", duration_s=0.0, rule=RULE_CANCELLED)

    async def _end(
        self,
        p: _Pass,
        status: Literal["ok", "rejected", "failed"],
        found: tuple[Finding, ...],
        reason: str | None,
        subject: Subject | None = None,
    ) -> None:
        """End the run with its verdict, then settle the record. A create whose run is marked
        cancelling (when it was taken, or by the API meanwhile) is decided again: cancelled, never
        `ok`. A destroy completes all the same. `subject` is the verdict's, when the record no
        longer names what the run acted on."""
        if p.run.operation == "create" and p.run.state == "cancelling":
            raise _Cancelled
        verdict = Verdict(operation=p.run.operation, status=status, subject=subject or self._subject(p.record, p.run),
                          findings=found)
        try:
            ended = runs.ended(p.run, verdict)
            self.store.update_run(ended, p.run.state)
        except store.Conflict:
            current = self.store.get_run(p.run.id)
            if current.state != "cancelling":
                raise
            if current.operation == "create":
                raise _Cancelled from None
            ended = runs.ended(current, verdict)
            self.store.update_run(ended, current.state)
        _log.info("%s: %s run %s ended %s", p.name, ended.operation, ended.id, status,
                  **p.fields(status=status, reason=reason))
        await self._settle(p.record, ended, p.driver, reason)

    async def _settle(self, record: TwinRecord, run: Run, driver: Driver, reason: str | None = None) -> None:
        """The record's last write for an ended run. A destroy's: the record deleted. A create's:
        Ready True for an `ok` verdict; otherwise the cleanup, `destroy` when a deployment was
        filed, and then the nodes, deployment and allocation cleared, with Ready False for
        `reason` (read from the run's ending event when not given). A failed destroy records the
        failure, keeps the rest, and is raised.

        A create's end sets `observed_generation` to the generation it acted on, unless the twin's
        deletion was asked meanwhile: that generation is the deletion's, which the destroy run
        acts on and settles by deleting the record, so a client that waits for the twin to be
        observed at it is never told so by a create's end while the twin is still there (a
        teardown this core refuses is observed, by `_refuse`, and the record kept)."""
        assert run.verdict is not None
        if run.operation == "destroy" and run.verdict.status == "ok":
            self.store.delete_twin(record.name, record.revision)
            logs.audit(run.principal, "delete", record.name, run=run.id, revision=record.revision)
            _log.info("%s: torn down, and its record deleted", record.name, **logs.fields(twin=record.name, run=run.id))
            return
        observed = record.status.observed_generation if record.deletion_requested_at is not None else record.generation
        if run.verdict.status == "ok":
            self._write(record, run, conditions=ready_condition(record.status.conditions, "True", REASON_READY),
                        observed_generation=observed, run_id=None)
            return
        reason = reason if reason is not None else self._failing_rule(run)
        conditions = ready_condition(record.status.conditions, "False", reason)
        lacking = self._lacking(record)
        if lacking:
            _log.error("%s: its deployment %s cannot be torn down without the packages its bundle names (%s): it is "
                       "kept, and so is its allocation", record.name, record.status.deployment_id,
                       ", ".join(str(f.object) for f in lacking), **logs.fields(twin=record.name, run=run.id))
            self._write(record, run, conditions=conditions, observed_generation=observed, run_id=None, phase=None)
            return
        if record.status.deployment_id is not None:
            deployment, files = self.store.get_deployment(record.status.deployment_id)
            try:
                await driver.destroy(deployment, files, self.platforms, self.probe_packages)
            except DriverFailed:
                if (conditions, observed) != (record.status.conditions, record.status.observed_generation):
                    self._write(record, run, conditions=conditions, observed_generation=observed)
                raise
        self._write(record, run, conditions=conditions, observed_generation=observed, run_id=None, phase=None,
                    nodes=(), deployment_id=None, allocation=None)

    def _failing_rule(self, run: Run) -> str:
        """The rule of the run's ending event, its last: every path that ends a run badly writes
        that event with the condition's reason (a phase's failure, or `cancel done` with
        `run.cancelled`) before it ends the run, so an earlier transient failure's rule is never
        taken for it. The first finding's rule when the ending event carries none, as for a run
        ended before it began."""
        events = self.store.events(run.id)
        assert run.verdict is not None
        if events and events[-1].rule is not None:
            return events[-1].rule
        return run.verdict.findings[0].rule

    @staticmethod
    def _subject(record: TwinRecord, run: Run) -> Subject:
        status, spec = record.status, record.spec
        return Subject(twin=record.name, run_id=run.id, blueprint_id=status.blueprint_id or spec.blueprint_id,
                       bundle_id=status.bundle_id or spec.bundle_id, deployment_id=status.deployment_id)

    # The record and the events.

    def _write(self, record: TwinRecord, run: Run, **changes: Any) -> TwinRecord:
        """The record with `changes` to its status, written by compare-and-set; one audit line."""
        return self._write_as(record, run.principal, run.id, **changes)

    def _write_as(self, record: TwinRecord, principal: str, acting: str | None, **changes: Any) -> TwinRecord:
        """`_write` on behalf of `principal`, under the run `acting` (None for no run). The status
        is the loop's alone (D-025): a write lost to a client's (a spec, a deletion request) whose
        stored status is still the one the loop last wrote is made again over the client's, once;
        any other loss is `store.Conflict`."""
        status = replace(record.status, **changes)
        try:
            written = self.store.update_twin(replace(record, status=status), record.revision)
        except store.Conflict:
            current = self.store.get_twin(record.name)
            if current.status != record.status:
                raise
            _log.debug("%s: a client wrote the record at revision %d: the status is written over it", record.name,
                       current.revision, **logs.fields(twin=record.name, run=acting))
            written = self.store.update_twin(replace(current, status=status), current.revision)
        logs.audit(principal, "status", record.name, run=acting, phase=written.status.phase, revision=written.revision)
        return written

    def _event(
        self,
        p: _Pass,
        phase: runs.Phase,
        outcome: Outcome,
        node: str | None = None,
        duration_s: float | None = None,
        rule: str | None = None,
    ) -> None:
        event = Event(seq=0, at=clock.now(), phase=phase, outcome=outcome, node=node, duration_s=duration_s, rule=rule)
        self.store.append_event(p.run.id, event)

    @contextlib.asynccontextmanager
    async def _step(self, p: _Pass, phase: runs.Phase, node: str | None = None) -> AsyncIterator[_Step]:
        """A phase's (or a node's) `started` event, then its end: the step's outcome, `done`
        unless it says otherwise, with its rule; a failure's outcome and reason; `cancelled`
        when the run was cancelled during it; `failed` for a transient failure, with its rule
        when it has one. Anything else, a kill, ends nothing."""
        self._event(p, phase, "started", node)
        start = time.monotonic()
        step = _Step()
        try:
            yield step
        except _Failed as failure:
            self._event(p, phase, failure.outcome, node, time.monotonic() - start, failure.reason)
            failure.recorded = True
            raise
        except _Cancelled:
            self._event(p, phase, "cancelled", node, time.monotonic() - start)
            raise
        except TRANSIENT as e:
            rule: str | None = getattr(e, "rule", None)
            with contextlib.suppress(*TRANSIENT, store.StoreError):  # the store may be what failed
                self._event(p, phase, "failed", node, time.monotonic() - start, rule)
            raise
        self._event(p, phase, step.outcome, node, time.monotonic() - start, step.rule)

    # What the phases read: from this pass, or the store on a resume.

    def _files(self, p: _Pass) -> Mapping[str, bytes]:
        if p.files is None:
            assert p.record.status.bundle_id is not None
            p.files = self.store.get_bundle(p.record.status.bundle_id)
        return p.files

    def _manifest(self, p: _Pass) -> Manifest:
        """The bundle's manifest, refused (`bundle.rejected`) when it names a package this core
        has not loaded: a bundle compiled elsewhere, or a resume on a core started without a
        package the run began with."""
        if p.manifest is None:
            manifest = bundle.decode(json.loads(self._files(p)["manifest.json"]))
            unloaded = self._unloaded(manifest)
            if unloaded:
                raise _Failed("rejected", RULE_BUNDLE_REJECTED, unloaded)
            p.manifest = manifest
        return p.manifest

    def _lacking(self, record: TwinRecord) -> list[Finding]:
        """What this core lacks to tear the record's deployment down: the packages the
        deployment's own bundle names that are not loaded, since a driver's `destroy` takes them.
        The deployment's, not the record's `bundle_id`, which a newer compile may have written.
        Empty without a deployment."""
        if record.status.deployment_id is None:
            return []
        deployed, _ = self.store.get_deployment(record.status.deployment_id)
        files = self.store.get_bundle(deployed.bundle_id)
        return self._unloaded(bundle.decode(json.loads(files["manifest.json"])))

    def _deployment(self, p: _Pass) -> tuple[Deployment, Mapping[str, bytes]]:
        if p.deployment is None or p.deployment_files is None:
            assert p.record.status.deployment_id is not None
            p.deployment, p.deployment_files = self.store.get_deployment(p.record.status.deployment_id)
        return p.deployment, p.deployment_files

    def _login(self, package: PlatformPackage, node: str) -> Credential:
        try:
            return self.credentials.login(package.credentials)
        except Missing as e:
            finding = Finding(rule=e.rule, severity="error", object=node, message=str(e))
            raise _Failed("failed", e.rule, [finding]) from e

    @staticmethod
    def _address(p: _Pass, node: str) -> str:
        address = next((n.address for n in p.record.status.nodes if n.name == node), None)
        if address is None:
            message = f"{node} has no management address on the runtime, so its transport cannot answer"
            raise _Failed("failed", RULE_TIMEOUT, [Finding(rule=RULE_TIMEOUT, severity="error", object=node,
                                                           message=message)], outcome="timed_out")
        return address

    @staticmethod
    def _not_ready(e: NotReady, node: str) -> _Failed:
        outcome: Outcome = "timed_out" if e.rule == RULE_TIMEOUT else "failed"
        return _Failed("failed", e.rule, [Finding(rule=e.rule, severity="error", object=node, message=e.message)],
                       outcome)

    # The phases.

    async def _compile(self, p: _Pass) -> None:
        async with self._step(p, "compile"):
            spec = p.record.spec
            if spec.blueprint_id is not None:
                try:
                    doc = self.store.get_blueprint(spec.blueprint_id)
                except store.NotFound:
                    raise _Failed("rejected", RULE_BLUEPRINT_MISSING, [Finding(
                        rule=RULE_BLUEPRINT_MISSING, severity="error", object=spec.blueprint_id,
                        message=f"The spec's blueprint {spec.blueprint_id} is not in the store.")]) from None
                try:
                    compiled = compiler.compile(blueprint.decode(doc), self.platforms, self.probe_packages)
                except compiler.Uncompilable as e:
                    raise _Failed("rejected", RULE_BUNDLE_REJECTED, e.findings) from e
                self.store.put_bundle(compiled.id, compiled.files)
                bundle_id, p.manifest, p.files = compiled.id, compiled.manifest, compiled.files
            else:
                assert spec.bundle_id is not None
                bundle_id = spec.bundle_id
                try:
                    p.files = self.store.get_bundle(bundle_id)
                except store.NotFound:
                    raise _Failed("rejected", RULE_BUNDLE_MISSING, [Finding(
                        rule=RULE_BUNDLE_MISSING, severity="error", object=bundle_id,
                        message=f"The spec's bundle {bundle_id} is not in the store.")]) from None
                p.manifest = None
            manifest = self._manifest(p)
            p.record = self._write(p.record, p.run, phase="compiled", blueprint_id=manifest.blueprint_id,
                                   bundle_id=bundle_id)

    def _unloaded(self, manifest: Manifest) -> list[Finding]:
        """One finding, in the compile's rules, for each package the manifest names that this
        core has not loaded; the object is the package, and the message names who uses it."""
        platforms: dict[str, list[str]] = {}
        for node in manifest.nodes:
            if node.platform not in self.platforms:
                platforms.setdefault(node.platform, []).append(node.name)
        formats: dict[str, list[str]] = {}
        for probe in manifest.probes:
            if probe.format not in self.probe_packages:
                formats.setdefault(probe.format, []).append(probe.name)
        return [Finding(rule=compiler.RULE_PLATFORM, severity="error", object=platform,
                        message=f"No loaded platform package is {platform!r}, which {', '.join(nodes)} run.")
                for platform, nodes in platforms.items()] + [
                Finding(rule=compiler.RULE_PROBE_FORMAT, severity="error", object=probe_format,
                        message=f"No loaded probe package runs {probe_format!r}, which {', '.join(probes)} use.")
                for probe_format, probes in formats.items()]

    def _reserved(self, twin: str) -> list[Mapping[str, Any]]:
        """Every other twin's recorded allocation, for admission."""
        return [t.status.allocation for t in self.store.list_twins()
                if t.name != twin and t.status.allocation is not None]

    async def _admit(self, p: _Pass) -> None:
        async with self._step(p, "admit"), self._admission:
            manifest, reserved = self._manifest(p), self._reserved(p.name)
            answer = await self._runtime(p, p.driver.admit, manifest, self.platforms, self.probe_packages, p.name,
                                         reserved)
            if isinstance(answer, Refusal):
                raise _Failed("rejected", answer.rule, [Finding(rule=answer.rule, severity="error", object=p.name,
                                                                message=answer.message)])
            p.record = self._write(p.record, p.run, phase="admitted", allocation=dict(answer))

    async def _plan(self, p: _Pass) -> None:
        async with self._step(p, "plan"):
            status = p.record.status
            assert status.bundle_id is not None and status.allocation is not None
            try:
                planned = p.driver.plan(self._manifest(p), status.bundle_id, self.platforms, self.probe_packages,
                                        p.name, status.allocation)
            except Unplannable as e:
                raise _Failed("rejected", RULE_PLAN_REJECTED, e.findings) from e
            self.store.put_deployment(planned.deployment, planned.files)
            p.deployment, p.deployment_files = planned.deployment, planned.files
            p.record = self._write(p.record, p.run, phase="planned", deployment_id=planned.deployment.id)

    async def _apply(self, p: _Pass) -> None:
        async with self._step(p, "apply") as step:
            deployment, files = self._deployment(p)
            inspection = await self._runtime(p, p.driver.inspect, p.name)
            if inspection.state == "present":  # a lab while the record lacks applied: probe it (D-023)
                silent = await self._silent(p, inspection)
                if silent is None:
                    step.outcome = "skipped"
                    _log.info("%s: the lab is present and every node answers: no deploy", p.name, **p.fields())
                else:
                    _log.info("%s: the lab is present and %s is silent: reconfigure", p.name, silent,
                              **p.fields(node=silent))
                    await self._runtime(p, p.driver.apply, deployment, files, self.platforms, self.probe_packages,
                                        reconfigure=True)
            else:
                await self._runtime(p, p.driver.apply, deployment, files, self.platforms, self.probe_packages)
            inspection = await self._runtime(p, p.driver.inspect, p.name)
            nodes = tuple(Node(name=n.name, handle=n.handle, address=n.address, incarnation=n.incarnation)
                          for n in sorted(inspection.nodes, key=lambda n: n.name))
            p.record = self._write(p.record, p.run, phase="applied", nodes=nodes)

    async def _silent(self, p: _Pass, inspection: Inspection) -> str | None:
        """The first device node of a present lab that is silent: missing from the inspection,
        not running, without an address, or not answering within its boot window; None when
        every one answers. A node that refuses the login is not silent, and a reconfigure would
        not help it: the run fails at once with `readiness.unauthorized`."""
        manifest = self._manifest(p)
        found = {n.name: n for n in inspection.nodes}
        for node in manifest.nodes:
            state = found.get(node.name)
            if state is None or not state.running or not state.address:
                return node.name
        for node in manifest.nodes:
            package = self.platforms[node.platform]
            address = found[node.name].address
            assert address is not None
            credential = self._login(package, node.name)
            try:
                await self._runtime(p, self.readiness, address, package, credential,
                                    timeout_s=package.readiness.timeout_s)
            except NotReady as e:
                if e.rule == RULE_UNAUTHORIZED:
                    raise self._not_ready(e, node.name) from e
                return node.name
        return None

    async def _ready(self, p: _Pass) -> None:
        manifest = self._manifest(p)
        for node in manifest.nodes:
            await self._checkpoint(p)
            async with self._step(p, "ready", node.name):
                package = self.platforms[node.platform]
                credential = self._login(package, node.name)
                address = self._address(p, node.name)
                try:
                    await self._runtime(p, self.readiness, address, package, credential,
                                        timeout_s=package.readiness.timeout_s)
                except NotReady as e:
                    raise self._not_ready(e, node.name) from e
        for probe in manifest.probes:  # a probe host's readiness is phase 5's
            for side in "ab":
                self._event(p, "ready", "skipped", f"{probe.name}-{side}")
        p.record = self._write(p.record, p.run, phase="ready")

    async def _push(self, p: _Pass) -> None:
        manifest, files = self._manifest(p), self._files(p)
        bundle_id = p.record.status.bundle_id
        for node in manifest.nodes:
            if any(n.name == node.name and n.holds == bundle_id for n in p.record.status.nodes):
                continue
            await self._checkpoint(p)
            async with self._step(p, "push", node.name):
                package = self.platforms[node.platform]
                credential = self._login(package, node.name)
                address, config = self._address(p, node.name), files[node.config.file].decode()
                try:
                    answer = await self._runtime(p, self.pusher, address, package, config, credential)
                except push.Unauthorized as e:
                    raise _Failed("failed", e.rule, [Finding(rule=e.rule, severity="error", object=node.name,
                                                             message=e.message)]) from e
                if isinstance(answer, push.Refused):
                    raise _Failed("failed", answer.rule, [Finding(rule=answer.rule, severity="error", object=node.name,
                                                                  message=answer.message)])
                # The diff is not kept in phase 4: its event member arrives with steps.
                _log.info("%s: pushed %s", p.name, node.name,
                          **p.fields(node=node.name, diff_length=len(answer.diff), push_s=answer.duration_s))
                nodes = tuple(replace(n, holds=bundle_id) if n.name == node.name else n for n in p.record.status.nodes)
                p.record = self._write(p.record, p.run, nodes=nodes)
        p.record = self._write(p.record, p.run, phase="pushed")

    # The dry run.

    async def dry_run(self, twin: str, spec: Spec) -> tuple[Deployment | None, Verdict]:
        """What a create of `twin` with `spec` would be, writing nothing: the compile (or the
        spec's bundle), the driver's `admit` against the live reservations, and its pure `plan`.
        It answers the deployment and a verdict of operation `plan`: `ok`, or `rejected` with the
        refusal's finding and no deployment, since a refused admission reserves nothing to plan
        with. A blueprint that does not compile raises `compiler.Uncompilable` (so does a bundle
        naming a package this core has not loaded), a refused plan `driver.Unplannable`, and an
        id the store does not hold `store.NotFound`, for the API to answer."""
        if spec.blueprint_id is not None:
            doc = self.store.get_blueprint(spec.blueprint_id)
            compiled = compiler.compile(blueprint.decode(doc), self.platforms, self.probe_packages)
            manifest, bundle_id = compiled.manifest, compiled.id
        else:
            assert spec.bundle_id is not None
            bundle_id = spec.bundle_id
            manifest = bundle.decode(json.loads(self.store.get_bundle(bundle_id)["manifest.json"]))
            unloaded = self._unloaded(manifest)
            if unloaded:
                raise compiler.Uncompilable(unloaded)
        subject = Subject(twin=twin, blueprint_id=manifest.blueprint_id, bundle_id=bundle_id)
        driver = self.drivers.get(spec.driver)
        if driver is None:
            served = ", ".join(sorted(self.drivers)) or "none"
            finding = Finding(rule=RULE_DRIVER_UNKNOWN, severity="error", object=twin,
                              message=f"The spec's driver {spec.driver!r} is not one this core serves ({served}).")
            return None, Verdict(operation="plan", status="rejected", subject=subject, findings=(finding,))
        async with self._admission:
            answer = await driver.admit(manifest, self.platforms, self.probe_packages, twin, self._reserved(twin))
        if isinstance(answer, Refusal):
            refusal = Finding(rule=answer.rule, severity="error", object=twin, message=answer.message)
            return None, Verdict(operation="plan", status="rejected", subject=subject, findings=(refusal,))
        planned = driver.plan(manifest, bundle_id, self.platforms, self.probe_packages, twin, answer)
        verdict = Verdict(operation="plan", status="ok", subject=replace(subject, deployment_id=planned.deployment.id),
                          findings=())
        return planned.deployment, verdict


def ready_reason(conditions: Iterable[Condition]) -> str | None:
    """The Ready condition's reason, or None without one."""
    return next((c.reason for c in conditions if c.type == "Ready"), None)
