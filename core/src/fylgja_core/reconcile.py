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
- `ready`: each device node's push transport answers, then each probe host shows its address on its
  port, read through the driver's `exec` (probe package 1, D-049);
- `pushed`: each device node with a configuration pushed it; one without is passed over and marked as
  holding the bundle (D-048). The bundle a node holds is recorded at once.

A step (D-050) takes a twin that runs to the spec's new bundle through the same phases and two
more, `verified` and `flows` (`STEP`). A pass runs one when the spec's generation is ahead of the
observed one, the record names a deployment and the nodes its apply left, and no create run is in
flight; otherwise a create, so a twin whose create never applied is created again. Until
`applied` the target is `last_step.to` alone, each phase is recorded in `last_step.phase` alone,
and the record's bundle, blueprint, deployment, nodes and `phase` stay the running twin's:

- `compiled`: a diverged twin is refused at once (`step.twin.diverged`): it accepts only
  deletion (D-029). Then the spec's bundle, as a create's. One equal to the twin's ends the run
  `ok` at once, `last_step` `unchanged`, Ready True and Stepping False for `twin.ready`: the twin
  runs what the spec asks. Otherwise `last_step` names the step `running` from the twin's bundle
  to it, Stepping is True and Ready False for `twin.stepping`;
- `admitted`: the driver's `admit` with the deployment the twin runs, whose allocation it keeps;
- `planned`: the target's pure `plan` with that allocation, the deployment filed, and the
  driver's `changes` from the running deployment to it. Then, before anything is touched, the
  refusals: a diverged twin (`step.twin.diverged`), a change the driver cannot make
  (`step.relink.unsupported`), a node restarted or recreated without the spec's `allow_restart`
  (`step.restart.required`), which counts only while the spec is the one the run was taken
  under: a newer spec a client wrote meanwhile is the next run's, its permission too. A resume
  after `planned` plans again, purely, and refuses again, but for the restart check once its
  apply had begun: the pass that began it passed that check under the run's own spec;
- `applied`: the target applied over the running lab, plainly (a resume into an apply already
  begun probes the lab first, below), then `inspect`; the record's bundle, blueprint, deployment
  and nodes move to the target, and from here each phase is recorded in `phase` too. A node keeps
  what it holds while its incarnation is the one the record knew and `changes` neither restarted
  nor recreated it (a runtime may restart a node in place), and holds nothing otherwise;
- `ready`: each device node holding nothing (added, or its incarnation moved), and every probe
  host of the target;
- `pushed`: each of those device nodes, and each whose configuration's checksum differs from the
  one it ran; any other is marked holding the target without a push, as is a node without a
  configuration;
- `verified`: the wait, verify tried every `verify_poll_s` until it holds or `step_wait_s` has
  passed (D-032); an expiry is the warning `step.wait.expired`, and the step goes on;
- `flows`: each probe of the target recorded `not_started` from each host (D-051).

The step then ends `ok`, `last_step` `stepped`, Ready True and Stepping False for `twin.ready`,
the observed generation the one the run was taken under (a spec written meanwhile is the next
pass's); its verdict carries the last verify's findings and counts and the wait, from the pass
that waited, and the flows, whichever pass ends it (a resume after `flows`, or a cancel or a
core without the driver finding every phase run, lists them from the target).

A refused step, like one whose blueprint does not compile, or one whose running deployment
names a package this core lacks, ends `rejected`, recorded as a refused create is: Ready and
Stepping False for its rule, `last_step` `rejected`, the observed generation the run's; its
verdict names what the run compiled and planned, the target's blueprint from its manifest (the
stored target's when the pass read none), never a newer spec's. A twin diverged already keeps the
`last_step` of the step that left it so: a run refused
or cancelled after that one writes only the conditions, the observed generation and no run
named. **No rollback** (D-029): from its
apply on, an `apply started` of any pass of the run, every failure ends a step `diverged` (a node
that never answers, a refused push, a login refused or a credential missing in a resume's probe,
a refusal of the re-plan on a resume into the apply), with the finding `step.diverged` beside the
failure's own, and so does every cancel; its message names the phase, the last one recorded and
what each node holds as the record knows. A silent node on a resume without `allow_restart` is
`step.node.silent` instead. A diverged step is recorded so too, with `last_step` `diverged` and
Diverged True for its rule: no bundle describes the twin, so it accepts only deletion. A step
cancelled before its apply began ends `failed` with `run.cancelled`, `last_step` `cancelled`,
the twin running what it ran. A step tears nothing down, refused, cancelled, failed or
diverged: the lab is the running twin's, or what the step made of it.

A twin whose deletion was asked is torn down by a destroy run instead (D-025): a create or a
step still in flight is cancelled first (a step's cancel touches nothing), then the driver's
`destroy` removes the deployment the record names, `destroyed` is recorded, and the record is
deleted.

Every phase emits run events: `started`, then `done`, `skipped`, `failed`, `timed_out` or
`cancelled`, with the seconds since `started`, and on a failure the rule; `ready` and `push`
emit a pair per node.

A resume runs the phase after the one recorded, under the run the record names. Two rules make
it reach the desired state in that one pass (D-023): a lab present while the record lacks
`applied` is probed, and applied again with `reconfigure` when a device node stays silent (it is
missing, stopped, without an address, or does not answer), or not at all when every one answers;
and a node already holding the bundle is never pushed again. A step's lab is always present, so
its probe runs only when the run's events show its apply begun and not ended (D-050): any `apply
started` of an earlier pass, a core stopped during the apply or a transient failure that ended
it, since either may have left it partly landed (a transient `apply failed` is no end; a step's
`apply done` follows `applied`, after which no pass applies). Then the target is applied again
plainly when every device node answers, with `reconfigure` when one stays silent and the run's
spec allows a restart, and otherwise not at all: the step ends `diverged` with `step.node.silent`,
since its apply had begun. In a step's probe a node missing from the lab is not silent: the
plain apply makes it anew, as it makes a node the step adds.

Failures are of two classes. **A failure only a new spec can clear** (a refused admission, an
uncompilable blueprint, a refused plan, a node that does not become ready, a refused or
unauthorized push, a missing credential, a driver this core does not serve) ends the run
`rejected` (nothing was built) or `failed`, cleans up (a create), and sets `observed_generation`, so the
loop waits for the spec to be written again; unless the twin's deletion was asked meanwhile,
whose generation the destroy run settles, by deleting the record. A step's, from its apply on,
ends it `diverged` instead, and cleans nothing up. **A transient failure** (the driver's
`DriverFailed`, an unreachable node, a store's `OSError` or lost compare-and-set) leaves the
record as it is, logs, and queues the twin again after a backoff that doubles from 1 s to 60 s
and resets on a pass that completes.

**Cancelling** a create or a step marks its run `cancelling` in the store. The loop reads the
mark between phases and before each node's readiness wait and push, and watches it during every
call on the runtime, which it stops; then a create cleans up and ends the run `failed` with the
finding `run.cancelled`. A step ends so before its apply began, touching nothing, and `diverged`
from it on, also touching nothing; one whose phases have all run has completed, and ends as it
would have. A destroy run is never stopped halfway: it completes.

The run's verdict is written before the record's last write, so a core stopped between the two
loses neither: a pass that finds the record naming an ended run completes that write from the
verdict, a step's even on a core without the twin's driver, since it tears nothing down.
Cleanup is then the driver's `destroy`, when a deployment was filed, and the record's nodes,
deployment and allocation cleared; a destroy that fails keeps the allocation, so a lingering
network's subnet stays reserved, and is retried on the next pass.

A twin has one run at a time. When a pass takes a create or step run afresh (one it makes, or
the newest queued of the operation), every other create or step run of the twin still queued, or
queued and marked cancelling by a client, ends `failed` with `run.cancelled`, superseded before
it started by the run taken, which its message names: two specs written before the loop took the
first queue two runs, and the API queues by the dispatch rule as it reads the record, which a
later pass may read otherwise (a create in flight, or one whose cleanup cleared what it
applied). A run the pass resumes supersedes nothing; a destroy run is never superseded.

The loop is scheduled by its work queue (D-023): `start` queues every twin in the store and
starts the workers and a periodic resync, a client's write `kick`s its twin, and a transient
failure queues its twin again after the backoff. `dry_run` writes nothing: for a new twin, or one
whose create never applied, a create's admission and plan; for a twin that runs, a step's
admission with the deployment it holds, the target's plan, the driver's `changes` and the step's
refusals, as the API's dry run answers them (D-050).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, NoReturn, Protocol

from fylgja_core import blueprint, bundle, clock, compiler, findings, logs, mapping, probe_package, push, store
from fylgja_core import run as runs
from fylgja_core.bundle import Manifest
from fylgja_core.credentials import Credential, Missing, Provider
from fylgja_core.deployment import Deployment
from fylgja_core.driver import (
    Changes,
    Driver,
    DriverFailed,
    Inspection,
    NodeChange,
    Planned,
    Refusal,
    Unplannable,
    relinks,
    restarts,
    unsupported,
)
from fylgja_core.findings import Counts, Finding, Loss, Subject, Verdict, Wait
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage
from fylgja_core.queue import Workers, WorkQueue
from fylgja_core.readiness import RULE_TIMEOUT, RULE_UNAUTHORIZED, NotReady, await_transport
from fylgja_core.run import Event, Outcome, Run
from fylgja_core.twin_record import Condition, LastStep, Node, Spec, StepPhase, TwinRecord
from fylgja_core.verify import Verifier

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
# The step's rules and reason (D-050).
RULE_STEP_TWIN_DIVERGED = "step.twin.diverged"
RULE_RESTART_REQUIRED = "step.restart.required"
RULE_RELINK_UNSUPPORTED = "step.relink.unsupported"
RULE_WAIT_EXPIRED = "step.wait.expired"
RULE_NODE_SILENT = "step.node.silent"
RULE_STEP_DIVERGED = "step.diverged"
REASON_STEPPING = "twin.stepping"

# The messages of a create or step run ended before it started.
UNSTARTED_DELETED = "The run was cancelled before it started: the twin's deletion was asked."
UNSTARTED_SUPERSEDED = "The run was superseded before it started by run {run}."
"""Formatted with the run the loop took afresh: a client's newer run, or the loop's own (principal `core`), made when
none of the operation was queued, so the message names the run rather than saying who wrote a later spec."""

HOST_POLL_S = 2.0  # between tries of a probe host's readiness command
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

# The phases of a step (D-050): the create's, then the wait for verify and the flows' record.
STEP: tuple[tuple[str, runs.Phase], ...] = (
    *CREATE,
    ("verified", "verify"),
    ("flows", "flows"),
)

# A step's phases recorded in `last_step` alone: until `applied` the record describes the running twin.
BEFORE_APPLIED: tuple[StepPhase, ...] = ("compiled", "admitted", "planned")

# A probe's hosts, as a step's verdict lists each one's flow.
SIDES: tuple[Literal["a", "b"], ...] = ("a", "b")

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


CONDITIONS: tuple[Literal["Ready", "Stepping", "Diverged"], ...] = ("Ready", "Stepping", "Diverged")


def set_condition(
    conditions: Iterable[Condition],
    kind: Literal["Ready", "Stepping", "Diverged"],
    status: Literal["True", "False"],
    reason: str,
) -> tuple[Condition, ...]:
    """`conditions` with the condition `kind` set to `status` for `reason`, in the order of
    `CONDITIONS`; its `since` changes only when its status does."""
    conditions = tuple(conditions)
    old = next((c for c in conditions if c.type == kind), None)
    since = old.since if old is not None and old.status == status and old.since else clock.now()
    kept = (c for c in conditions if c.type != kind)
    return tuple(sorted((Condition(type=kind, status=status, reason=reason, since=since), *kept),
                        key=lambda c: CONDITIONS.index(c.type)))


def ready_condition(
    conditions: Iterable[Condition], status: Literal["True", "False"], reason: str
) -> tuple[Condition, ...]:
    """`conditions` with Ready set to `status` for `reason`; its `since` changes only when its status does."""
    return set_condition(conditions, "Ready", status, reason)


def _taken(record: TwinRecord) -> int:
    """The generation the record's run works toward: `generation_in_flight`, or the record's own
    generation for one written before that member (or with no run yet taken)."""
    in_flight = record.status.generation_in_flight
    return record.generation if in_flight is None else in_flight


def _restart_allowed(record: TwinRecord) -> bool:
    """Whether the run the record names may restart or recreate a node: the spec's `allow_restart`,
    trusted only while the spec is the one the run was taken under (`_taken`). A spec a client
    writes while the run runs replaces the record's (`_write_as` writes the status over it, a
    resume reads it), so a newer spec's permission is read as false: the run is refused before
    its apply began, or ends `step.node.silent` on a resume whose probe finds a node silent, and
    the next run steps to the newer spec under its own setting. An older run never restarts a node
    under a later spec's permission (D-029). The restart check a resume into a begun apply skips
    is not read here (`_refusals`)."""
    return record.spec.allow_restart and record.generation == _taken(record)


class _Failed(Exception):
    """A failure only a new spec can clear: the run ends `status` with `found`, and the Ready
    condition and the failing event carry `reason`. A step's `diverged` tears nothing down and
    records the twin Diverged: its apply had begun, so no bundle describes it (D-029, D-050)."""

    def __init__(
        self,
        status: Literal["rejected", "failed", "diverged"],
        reason: str,
        found: Iterable[Finding],
        outcome: Outcome = "failed",
        *,
        recorded: bool = False,
    ) -> None:
        self.status: Literal["rejected", "failed", "diverged"] = status
        self.reason = reason
        self.findings = findings.order(found)
        self.outcome = outcome
        self.recorded = recorded  # whether a step wrote its ending event, or the failure needs none
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
    # A step's: the bundle it steps to (`last_step.to`), the deployment the twin runs and its files,
    # what the runtime does to go from that to the target, and the running bundle's manifest.
    target: str | None = None
    held: tuple[Deployment, Mapping[str, bytes]] | None = None
    changes: Changes | None = None
    from_manifest: Manifest | None = None
    unchanged: bool = False  # a step's bundle is the twin's: the run ends after `compiled`
    # A step's verdict members: the last verify's findings (and the wait's expiry), its counts, the wait, the flows.
    found: tuple[Finding, ...] = ()
    counts: Counts | None = None
    wait: Wait | None = None
    loss: tuple[Loss, ...] | None = None

    @property
    def name(self) -> str:
        return self.record.name

    def fields(self, **kw: Any) -> dict[str, Any]:
        return logs.fields(twin=self.name, run=self.run.id, **kw)


class Reconciler:
    """The loop over a store: the passes, the queue and workers they are scheduled by, the
    resync, and each twin's backoff. `cancel_poll_s` is how often a call on the runtime looks
    for its run's cancellation; `verifier` is the one the API shares, `step_wait_s` bounds a step's
    wait for verify and `verify_poll_s` spaces its tries.

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
        verifier: Verifier,
        step_wait_s: float = 180.0,
        verify_poll_s: float = 5.0,
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
        self.verifier = verifier
        self.step_wait_s = step_wait_s
        self.verify_poll_s = verify_poll_s
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
        named = self._read_run(record.status.run_id) if record.status.run_id is not None else None
        if named is not None and named.state == "ended" and (driver is not None or named.operation == "step"):
            # The run's end was recorded and the record's last write was not, or its cleanup is owed. A step's settle
            # tears nothing down, so it needs no driver: a core without the twin's driver records it too, before it
            # refuses anything, or a diverged step would never be marked Diverged.
            try:
                if driver is None:
                    self._settle_step(record, named, None)
                else:
                    await self._settle(record, named, driver)
            except TRANSIENT as e:
                raise _Retry(e, named.id) from e
            try:
                record = self.store.get_twin(name)
            except store.NotFound:  # a destroy run's settling deletes the record
                return
        if driver is None:
            await self._unserved(record)
            return
        if record.deletion_requested_at is not None:
            await self._delete(record, driver)
        elif record.generation != record.status.observed_generation:
            lacking = self._lacking(record) if record.status.run_id is None else []
            if lacking:
                # A deployment this core lacks the packages for is kept: a create over it would compile over
                # its bundle, admit over its allocation, and leave a cleanup no one here can do, and a step could
                # not tell what it changes. Refused, untouched. A step's refusal is recorded under its run, as
                # every other's is: `last_step` rejected, and Stepping False for the rule.
                if self._steps(record):
                    record, _ = self._take_run(record, "step", None)
                await self._refuse(record, RULE_BUNDLE_REJECTED, lacking)
            elif self._steps(record):
                await self._step_run(record, driver)
            else:
                await self._create(record, driver)

    def _steps(self, record: TwinRecord) -> bool:
        """Whether the spec is a step's (D-050): a lab was applied (`applied`), and no create run
        is still in flight. A twin whose create never applied, its cleanup having cleared the
        deployment or its nodes never recorded, is created again; a create in flight resumes."""
        if not applied(record):
            return False
        named = self._read_run(record.status.run_id) if record.status.run_id is not None else None
        return named is None or named.operation != "create" or named.state == "ended"

    async def _create(self, record: TwinRecord, driver: Driver) -> None:
        record, run = self._take_run(record, "create", REASON_CREATING)
        p = _Pass(record=record, run=run, driver=driver)
        work: Mapping[runs.Phase, Callable[[_Pass], Awaitable[None]]] = {
            "compile": self._compile, "admit": self._admit, "plan": self._plan,
            "apply": self._apply, "ready": self._ready, "push": self._push,
        }
        await self._run(p, self._phases_after(p.record.status.phase), work)

    async def _step_run(self, record: TwinRecord, driver: Driver) -> None:
        """A step (D-050): the twin taken from the bundle it runs to the spec's, through `STEP`,
        under a run of operation `step`. The take leaves the conditions alone: `compiled` sets them
        once it knows the bundle changes. The phases the run recorded are `last_step`'s, so a
        resume runs those after its `phase`, and a new run starts at the first."""
        record, run = self._take_run(record, "step", None)
        mine = _own_step(record, run.id)
        p = _Pass(record=record, run=run, driver=driver, target=None if mine is None else mine.to)
        work: Mapping[runs.Phase, Callable[[_Pass], Awaitable[None]]] = {
            "compile": self._compile, "admit": self._admit, "plan": self._plan,
            "apply": self._apply, "ready": self._ready, "push": self._push,
            "verify": self._verify_phase, "flows": self._flows_phase,
        }
        await self._run(p, self._phases_after(None if mine is None else mine.phase, STEP), work)

    async def _run(
        self,
        p: _Pass,
        phases: Iterable[tuple[str, runs.Phase]],
        work: Mapping[runs.Phase, Callable[[_Pass], Awaitable[None]]],
    ) -> None:
        """The run's `phases`, each by its `work` after a look for the run's cancellation, then the
        run's end `ok` (a step whose bundle is the twin's ends after `compiled`), with what a step's
        wait found. A create looks once more before its end; a step whose phases have all run has
        completed, and a cancel then has nothing left to stop (as one read during its end, `_end`).
        A failure only a new spec can clear ends it with its status, after the failing phase's ending
        event when the phase wrote none; a step's from its apply on ends `diverged` (`_diverges`). A
        cancel runs the cancel path, told the phase it was read in; a transient failure is raised as
        `_Retry`."""
        current: runs.Phase | None = None
        try:
            try:
                try:
                    for recorded, phase in phases:
                        current = phase
                        await self._checkpoint(p)
                        await work[phase](p)
                        _log.info("%s: %s", p.name, recorded, **p.fields(phase=phase))
                        if p.unchanged:
                            break
                    if p.run.operation != "step":
                        await self._checkpoint(p)
                    await self._end(p, "ok", p.found, None)
                except _Failed as failure:
                    if not failure.recorded and current is not None:  # failed outside a step: its ending event
                        self._event(p, current, failure.outcome, rule=failure.reason)
                    if p.run.operation == "step":
                        failure = self._diverges(p, failure, current)
                        await self._end(p, failure.status, failure.findings, failure.reason, self._step_subject(p))
                    else:
                        await self._end(p, failure.status, failure.findings, failure.reason)
            except _Cancelled:
                await self._cancel(p, current)
        except TRANSIENT as e:
            raise _Retry(e, p.run.id) from e

    def _diverges(self, p: _Pass, failure: _Failed, phase: runs.Phase | None) -> _Failed:
        """A step's failure as its run ends with it (D-029, D-050). One from its apply on, an apply
        begun by this pass or an earlier one (`_apply_begun`), whatever it was (a node that never
        answered, a refused push, a login refused in the resume's probe, a refusal of the re-plan on
        a resume into it), ends the step `diverged` for `step.diverged`, its finding beside the
        failure's own, naming `phase` and what each node holds: nothing is torn down and no bundle
        describes the twin. One before the apply began, or a divergence already
        (`step.node.silent`), is as it was."""
        if failure.status == "diverged" or not self._apply_begun(p.run.id):
            return failure
        _log.warning("%s: the step failed during %s for %s after its apply began: the twin is diverged", p.name,
                     phase, failure.reason, **p.fields(phase=phase, reason=RULE_STEP_DIVERGED))
        found = [*failure.findings, _left_diverged(p.record, p.run.id, phase, failure.reason)]
        return _Failed("diverged", RULE_STEP_DIVERGED, found, recorded=True)

    async def _delete(self, record: TwinRecord, driver: Driver) -> None:
        """Tear the twin down and delete its record (D-025): a create or a step in flight is
        cancelled first, through the cancel path (a step's tears nothing down: it ends cancelled
        before its apply began and diverged after, D-029), and any create or step run that never
        started is ended cancelled; then the destroy run, of the deployment the record names (a
        diverged step's target once it was applied, else the one the twin ran)."""
        named = self._read_run(record.status.run_id) if record.status.run_id is not None else None
        if named is not None and named.operation in ("create", "step") and named.state != "ended":
            try:
                if named.state != "cancelling":
                    cancelling = replace(named, state="cancelling")
                    self.store.update_run(cancelling, named.state)
                    named = cancelling
                mine = _own_step(record, named.id)
                await self._cancel(_Pass(record=record, run=named, driver=driver,
                                         target=None if mine is None else mine.to))
            except TRANSIENT as e:
                raise _Retry(e, named.id) from e
            record = self.store.get_twin(record.name)
        for stray in self.store.list_runs(record.name):
            if stray.operation in ("create", "step") and stray.state != "ended":
                self._cancel_unstarted(record, stray, UNSTARTED_DELETED)
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
        with `found`, and Ready is False for `reason`, once; nothing is torn down. A step's verdict
        names its target; one whose apply had begun ends `diverged` instead, with `step.diverged`
        beside `found` (D-029); one whose phases have all run has completed, and ends `ok`, as it
        would have. The step the record names is recorded as its run ended (`_step_ending`, or
        `_step_done` for `ok`): Stepping False for `reason` too, `last_step` `rejected`, or
        `diverged` with the twin Diverged for `step.diverged`; a twin diverged already keeps the
        `last_step` of the step that left it so. An `ok` step's verdict lists its target's flows,
        `not_started` (D-051), as the `flows` phase it had run recorded them."""
        status = record.status
        in_flight = [r for r in self.store.list_runs(record.name) if r.state != "ended"]
        settled = (ready_reason(status.conditions) == reason and status.run_id is None
                   and status.observed_generation == record.generation)
        if not in_flight and settled:
            return
        ordered = findings.order(found)
        stepping: dict[str, Any] = {"conditions": ready_condition(status.conditions, "False", reason)}
        for run in in_flight:
            verdict = Verdict(operation=run.operation, status="rejected", subject=self._subject(record, run),
                              findings=ordered)
            if run.operation == "step" and _completed(record, run.id):
                done = _own_step(record, run.id)
                assert done is not None
                verdict = replace(verdict, status="ok", findings=(), loss=self._flows_of(done.to))
                if run.id == status.run_id:
                    stepping = _step_done(record, run.id)
            elif run.operation == "step":
                mine = _own_step(record, run.id)
                target = None if mine is None else mine.to
                verdict = replace(verdict, subject=_stepping_subject(
                    record, run.id, target, None if target is None else self._described(target)))
                if self._apply_begun(run.id):
                    verdict = replace(verdict, status="diverged", findings=findings.order(
                        [*ordered, _left_diverged(record, run.id, None, reason)]))
                if run.id == status.run_id:
                    stepping = _step_ending(record, run.id, "diverged" if verdict.status == "diverged" else "rejected",
                                            reason, RULE_STEP_DIVERGED)
            self.store.update_run(runs.ended(run, verdict), run.state)
            _log.warning("%s: run %s ended %s: %s", record.name, run.id, verdict.status, reason,
                         **logs.fields(twin=record.name, run=run.id, reason=reason))
        if not settled:
            principal = in_flight[0].principal if in_flight else "core"
            self._write_as(record, principal, None, observed_generation=_taken(record), run_id=None,
                           generation_in_flight=None, **stepping)

    # The run.

    def _read_run(self, run_id: str) -> Run | None:
        try:
            return self.store.get_run(run_id)
        except store.NotFound:
            return None

    def _take_run(
        self, record: TwinRecord, operation: runs.Operation, reason: str | None
    ) -> tuple[TwinRecord, Run]:
        """The run this pass acts under, and the record naming it with Ready False for `reason`
        (or its conditions as they are, for None: a step's are set at `compiled`): the run the
        record names, if it is of `operation` and has not ended; else the newest run of the twin
        and `operation` queued (or cancelled before it started); else a new one, the core's. The
        record names it before it is marked running, so a core stopped between the two finds it
        again; one the API marked cancelling meanwhile stays so, to be cancelled. A create or step
        run taken afresh, made or from the queue (or named and still queued, a take cut short),
        supersedes every other create or step run of the twin still queued, or cancelled before it
        started (`_supersede`); one resumed supersedes nothing."""
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
        conditions = (record.status.conditions if reason is None
                      else ready_condition(record.status.conditions, "False", reason))
        fresh = run is not named or run.state == "queued"
        if record.status.run_id != run.id or conditions != record.status.conditions:
            in_flight = (record.status.generation_in_flight if record.status.run_id == run.id
                         and record.status.generation_in_flight is not None else record.generation)
            record = self._write(record, run, run_id=run.id, conditions=conditions, generation_in_flight=in_flight)
        if fresh and operation in ("create", "step"):  # after the record names the run: a swept one is named by none
            self._supersede(record, run)
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
            own = _own_step(record, run.id)
            after = (None if own is None else own.phase) if operation == "step" else record.status.phase
            _log.info("%s: %s run %s resumed after %s", record.name, operation, run.id, after or "nothing",
                      **logs.fields(twin=record.name, run=run.id))
        return record, run

    def _supersede(self, record: TwinRecord, taken: Run) -> None:
        """Every create or step run of the twin but `taken` still queued, or queued and marked
        cancelling by a client, ended before it started, its message naming `taken`: the loop takes
        the newest queued run of an operation, so an older one would wait for good, one the API
        queued by a reading of the dispatch rule this pass did not make would never be taken, and
        one a client cancelled beside a newer one would stay cancelling until the twin's deletion.
        None of them started: the record names `taken`, and a run it named is never left behind
        unended. `taken` may be the loop's own (principal `core`), so the message names the run
        rather than a later spec. A destroy run is never superseded."""
        why = UNSTARTED_SUPERSEDED.format(run=taken.id)
        for stray in self.store.list_runs(record.name):
            if (stray.id != taken.id and stray.operation in ("create", "step")
                    and stray.state in ("queued", "cancelling")):
                self._cancel_unstarted(record, stray, why)
                _log.info("%s: %s run %s superseded before it started by run %s", record.name, stray.operation,
                          stray.id, taken.id, **logs.fields(twin=record.name, run=stray.id))

    @staticmethod
    def _phases_after(
        phase: str | None, sequence: tuple[tuple[str, runs.Phase], ...] = CREATE
    ) -> tuple[tuple[str, runs.Phase], ...]:
        names = [recorded for recorded, _ in sequence]
        if phase is None:
            return sequence
        return sequence[names.index(phase) + 1:] if phase in names else ()

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

    async def _cancel(self, p: _Pass, phase: runs.Phase | None = None) -> None:
        """The cancel path (D-023): events `cancel started`, the cleanup (`destroy` when a
        deployment was filed, and the record's nodes, deployment and allocation cleared), and
        `cancel done` carrying `run.cancelled`; then the run ends `failed` with that finding,
        and Ready is False for it. A step's is `_cancel_step`, told the `phase` the cancel was read
        in: it cleans nothing up. A core stopped meanwhile finds the run still cancelling and runs
        the path again."""
        p.run = self.store.get_run(p.run.id)
        if p.run.operation == "step":
            await self._cancel_step(p, phase)
            return
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

    async def _cancel_step(self, p: _Pass, phase: runs.Phase | None) -> None:
        """A step's cancel path, which tears nothing down (D-029, D-050): `cancel started`, then
        `cancel done` carrying the ending's rule, and the run's end, its subject the step's. Before
        its apply began (`_apply_begun`) the run ends `failed` with `run.cancelled`, the twin running
        what it ran. From the apply on it ends `diverged` with `step.diverged`, naming `phase` (where
        the cancel was read; None when no pass was running the step, as for a deletion's) and what
        each node holds: the twin is left as it stands, and no bundle describes it. A step whose
        phases have all run (`last_step` at `flows`, a core stopped before its end) has completed: it
        ends `ok`, as it would have, with no cancel events, as `_run` ends one cancelled then."""
        if _completed(p.record, p.run.id):
            _log.info("%s: run %s was cancelled after its last phase: it ends as it would have", p.name, p.run.id,
                      **p.fields())
            await self._end(p, "ok", p.found, None)
            return
        begun = self._apply_begun(p.run.id)
        rule = RULE_STEP_DIVERGED if begun else RULE_CANCELLED
        async with self._step(p, "cancel") as step:
            step.rule = rule
        status: Literal["failed", "diverged"] = "diverged" if begun else "failed"
        finding = (_left_diverged(p.record, p.run.id, phase, None) if begun else
                   Finding(rule=RULE_CANCELLED, severity="error", object=p.name,
                           message="The step was cancelled before its apply began; the twin runs what it ran."))
        verdict = Verdict(operation="step", status=status, subject=self._step_subject(p), findings=(finding,))
        ended = runs.ended(p.run, verdict)
        self.store.update_run(ended, p.run.state)
        if begun:
            _log.warning("%s: run %s cancelled after its apply began: the twin is diverged", p.name, ended.id,
                         **p.fields(phase=phase, status=status, reason=rule))
        else:
            _log.info("%s: run %s cancelled", p.name, ended.id, **p.fields(status=status, reason=rule))
        await self._settle(p.record, ended, p.driver, rule)

    def _cancel_unstarted(self, record: TwinRecord, run: Run, why: str) -> None:
        """A create or step run that never started, of a twin being deleted or superseded by a
        newer run: its end, `failed` with `run.cancelled` and the message `why`, then its cancel
        events; it touched nothing, so it cleans nothing up."""
        finding = Finding(rule=RULE_CANCELLED, severity="error", object=record.name, message=why)
        verdict = Verdict(operation=run.operation, status="failed", subject=Subject(twin=record.name, run_id=run.id),
                          findings=(finding,))
        self.store.update_run(runs.ended(run, verdict), run.state)  # first: a lost update repeats no events
        self.store.append_event(run.id, Event(seq=0, at=clock.now(), phase="cancel", outcome="started"))
        self.store.append_event(run.id, Event(seq=0, at=clock.now(), phase="cancel", outcome="done", duration_s=0.0,
                                              rule=RULE_CANCELLED))

    async def _end(
        self,
        p: _Pass,
        status: Literal["ok", "rejected", "failed", "diverged"],
        found: tuple[Finding, ...],
        reason: str | None,
        subject: Subject | None = None,
    ) -> None:
        """End the run with its verdict, then settle the record. A create whose run is marked
        cancelling (when it was taken, or by the API meanwhile) is decided again: cancelled, never
        `ok`. A destroy completes all the same, and so does a step: its end follows its last phase
        or a failure, so a cancel has nothing left to stop. `subject` is the verdict's, when the
        record no longer names what the run acted on. A step's verdict carries verify's counts, the
        wait and the flows, once its phases found them; one that ends `ok` having run every phase
        lists its target's flows, `not_started` (D-051), whether or not this pass ran `flows` (a
        resume after it, or a cancel read after it, runs none)."""
        if p.run.operation == "create" and p.run.state == "cancelling":
            raise _Cancelled
        loss = p.loss
        if loss is None and status == "ok" and p.run.operation == "step" and _completed(p.record, p.run.id):
            assert p.target is not None  # a step's pass is told its target once `compiled` recorded it
            loss = self._flows_of(p.target)
        verdict = Verdict(operation=p.run.operation, status=status, subject=subject or self._subject(p.record, p.run),
                          findings=found, counts=p.counts, wait=p.wait, loss=loss)
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
        """The record's last write for an ended run. A destroy's: the record deleted. A step's:
        `_settle_step`, which tears nothing down. A create's:
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
        if run.operation == "step":
            self._settle_step(record, run, reason)
            return
        observed = record.status.observed_generation if record.deletion_requested_at is not None else _taken(record)
        if run.verdict.status == "ok":
            self._write(record, run, conditions=ready_condition(record.status.conditions, "True", REASON_READY),
                        observed_generation=observed, run_id=None, generation_in_flight=None)
            return
        reason = reason if reason is not None else self._failing_rule(run)
        conditions = ready_condition(record.status.conditions, "False", reason)
        lacking = self._lacking(record)
        if lacking:
            _log.error("%s: its deployment %s cannot be torn down without the packages its bundle names (%s): it is "
                       "kept, and so is its allocation", record.name, record.status.deployment_id,
                       ", ".join(str(f.object) for f in lacking), **logs.fields(twin=record.name, run=run.id))
            self._write(record, run, conditions=conditions, observed_generation=observed, run_id=None,
                        generation_in_flight=None, phase=None)
            return
        if record.status.deployment_id is not None:
            deployment, files = self.store.get_deployment(record.status.deployment_id)
            try:
                await driver.destroy(deployment, files, self.platforms, self.probe_packages)
            except DriverFailed:
                if (conditions, observed) != (record.status.conditions, record.status.observed_generation):
                    self._write(record, run, conditions=conditions, observed_generation=observed)
                raise
        self._write(record, run, conditions=conditions, observed_generation=observed, run_id=None,
                    generation_in_flight=None, phase=None,
                    nodes=(), deployment_id=None, allocation=None)

    def _settle_step(self, record: TwinRecord, run: Run, reason: str | None) -> None:
        """The record's last write for an ended step, which tears nothing down: the twin runs what
        it ran, or what the step made of it (D-029). One that ended `ok` leaves Ready True and
        Stepping False for `twin.ready`, since the twin runs what the spec asks: `last_step`
        `stepped`, the run's own, when it reached `flows`; `unchanged`, from and to the twin's
        bundle, when it ended at `compiled`, the spec's bundle being the twin's. Otherwise it was
        refused, or cancelled before its apply began, and is recorded as a refused create is
        (`_step_ending`): Ready and Stepping False for `reason`, and `last_step` `cancelled` for
        `run.cancelled` and `rejected` for any other, unless the twin is diverged already, whose
        `last_step` is the diverging step's and stays. One that ended `diverged`, its apply begun,
        is recorded so too, `last_step` `diverged`, and Diverged True for `reason`: no bundle
        describes the twin, so it accepts only deletion (D-029). Not given, `reason` is read back as
        the run ended: `step.diverged` when the verdict holds it (the failing phase's event carries
        the failure's own rule), else the run's ending rule, as `_settle` reads it. Each is one
        write, with the observed generation the run's (unless the twin's deletion was asked
        meanwhile) and no run named."""
        assert run.verdict is not None
        status = record.status
        assert status.bundle_id is not None  # a stepping twin applied a bundle
        observed = status.observed_generation if record.deletion_requested_at is not None else _taken(record)
        ended: dict[str, Any] = {"observed_generation": observed, "run_id": None, "generation_in_flight": None}
        if run.verdict.status == "ok":
            self._write(record, run, **_step_done(record, run.id), **ended)
            return
        # The verdict says `diverged` where the apply had begun: a failure or a cancel from it on (`step.diverged`), or
        # a silent node on a resume into it without `allow_restart` (`step.node.silent`). Nothing is torn down.
        if reason is None:
            left = any(f.rule == RULE_STEP_DIVERGED for f in run.verdict.findings)
            reason = RULE_STEP_DIVERGED if left else self._failing_rule(run)
        outcome: Literal["rejected", "cancelled", "diverged"] = (
            "diverged" if run.verdict.status == "diverged" else "cancelled" if reason == RULE_CANCELLED else "rejected")
        self._write(record, run, **_step_ending(record, run.id, outcome, reason), **ended)

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

    def _step_subject(self, p: _Pass) -> Subject:
        """A step's verdict subject: what the run compiled and planned, else what runs
        (`_stepping_subject`), the target's blueprint read from its manifest, this pass's or, when
        this pass read none (a deletion's cancel, say), the stored one (`_described`)."""
        manifest = p.manifest if p.manifest is not None or p.target is None else self._described(p.target)
        return _stepping_subject(p.record, p.run.id, p.target, manifest, p.deployment)

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
        """The files of the bundle the run builds: a step's target, else the record's bundle."""
        if p.files is None:
            bundle_id = p.target if p.target is not None else p.record.status.bundle_id
            assert bundle_id is not None
            p.files = self.store.get_bundle(bundle_id)
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

    def _held(self, p: _Pass) -> tuple[Deployment, Mapping[str, bytes]]:
        """The deployment a stepping twin runs, and its files: the record's, until `applied`."""
        if p.held is None:
            assert p.record.status.deployment_id is not None
            p.held = self.store.get_deployment(p.record.status.deployment_id)
        return p.held

    def _from_manifest(self, p: _Pass) -> Manifest:
        """The manifest of the bundle a step's twin ran, `last_step.from`, which a resume after
        `applied` still names (the record's deployment is the target's by then): each node's
        configuration is compared with it."""
        if p.from_manifest is None:
            mine = _own_step(p.record, p.run.id)
            assert mine is not None
            p.from_manifest = bundle.decode(json.loads(self.store.get_bundle(mine.from_)["manifest.json"]))
        return p.from_manifest

    def _described(self, bundle_id: str) -> Manifest:
        """The stored bundle `bundle_id`'s manifest, read without `_manifest`'s package check: for
        what describes a step's target (its blueprint, its probes) where the pass read no manifest,
        on a core that may lack a package the bundle names."""
        return bundle.decode(json.loads(self.store.get_bundle(bundle_id)["manifest.json"]))

    def _flows_of(self, bundle_id: str) -> tuple[Loss, ...]:
        """The flows a step to the bundle `bundle_id` lists, each `not_started` (`_not_started`), for
        a step that ends `ok` with no `flows` phase in the pass that ends it."""
        return _not_started(self._described(bundle_id))

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
            if p.run.operation == "step" and diverged(p.record):  # it accepts only deletion (D-029)
                raise _Failed("rejected", RULE_STEP_TWIN_DIVERGED, [_diverged_finding(p.name)])
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
            if p.run.operation == "step":
                self._compiled_step(p, bundle_id)
            else:
                p.record = self._write(p.record, p.run, phase="compiled", blueprint_id=manifest.blueprint_id,
                                       bundle_id=bundle_id)

    def _compiled_step(self, p: _Pass, bundle_id: str) -> None:
        """`compiled` for a step to `bundle_id`. One equal to the twin's ends the run, nothing
        written here: its settle writes the rest. Otherwise `last_step` names the step running from
        the twin's bundle to it, Stepping is True and Ready False for `twin.stepping`; the record's
        bundle, blueprint, deployment, nodes and `phase` stay the running twin's until `applied`, so
        a kill before it leaves a record that still describes what runs."""
        status = p.record.status
        assert status.bundle_id is not None
        p.target = bundle_id
        if bundle_id == status.bundle_id:
            p.unchanged = True
            return
        conditions = set_condition(ready_condition(status.conditions, "False", REASON_STEPPING), "Stepping", "True",
                                   REASON_STEPPING)
        running = LastStep(outcome="running", from_=status.bundle_id, to=bundle_id, phase="compiled", run_id=p.run.id)
        p.record = self._write(p.record, p.run, conditions=conditions, last_step=running)

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

    def _recorded(self, p: _Pass, phase: StepPhase, **changes: Any) -> None:
        """`phase` recorded as done, with `changes` to the status. A step's is `last_step`'s, and
        before `applied` its alone: the record's `phase` describes the running twin until then."""
        if p.run.operation == "step":
            last = _own_step(p.record, p.run.id)
            assert last is not None
            changes["last_step"] = replace(last, phase=phase)
            if phase in BEFORE_APPLIED:
                p.record = self._write(p.record, p.run, **changes)
                return
        p.record = self._write(p.record, p.run, phase=phase, **changes)

    async def _admit(self, p: _Pass) -> None:
        """`admitted`: the driver's `admit`; a step's with the deployment the twin runs, whose
        allocation the driver keeps, checking only the demand the target adds (D-049)."""
        async with self._step(p, "admit"), self._admission:
            manifest, reserved = self._manifest(p), self._reserved(p.name)
            held = self._held(p)[0] if p.run.operation == "step" else None
            answer = await self._runtime(p, p.driver.admit, manifest, self.platforms, self.probe_packages, p.name,
                                         reserved, held=held)
            if isinstance(answer, Refusal):
                raise _Failed("rejected", answer.rule, [Finding(rule=answer.rule, severity="error", object=p.name,
                                                                message=answer.message)])
            if held is not None:  # the allocation is the one the twin holds
                self._recorded(p, "admitted")
            else:
                self._recorded(p, "admitted", allocation=dict(answer))

    async def _plan(self, p: _Pass) -> None:
        if p.run.operation == "step":
            await self._plan_step(p)
            return
        async with self._step(p, "plan"):
            assert p.record.status.bundle_id is not None
            planned = self._planned(p, p.record.status.bundle_id)
            self.store.put_deployment(planned.deployment, planned.files)
            self._recorded(p, "planned", deployment_id=planned.deployment.id)

    def _planned(self, p: _Pass, bundle_id: str) -> Planned:
        """The driver's pure plan of the bundle `bundle_id` with the record's allocation, kept in
        the pass as the deployment the run applies; a refused plan is `plan.rejected`."""
        allocation = p.record.status.allocation
        assert allocation is not None
        try:
            planned = p.driver.plan(self._manifest(p), bundle_id, self.platforms, self.probe_packages, p.name,
                                    allocation)
        except Unplannable as e:
            raise _Failed("rejected", RULE_PLAN_REJECTED, e.findings) from e
        p.deployment, p.deployment_files = planned.deployment, planned.files
        return planned

    async def _plan_step(self, p: _Pass) -> None:
        """`planned` for a step: the target planned with the allocation the twin holds, and filed,
        then the driver's `changes` from the deployment the twin runs to it. The record keeps the
        running deployment's id: a resume plans again, purely, to the same id. Then, after `plan
        done` and before anything is touched, the refusals."""
        async with self._step(p, "plan"):
            assert p.target is not None
            planned = self._planned(p, p.target)
            self.store.put_deployment(planned.deployment, planned.files)
            p.changes = self._changes(p, planned)
            self._recorded(p, "planned")
        self._refusals(p)

    def _changes(self, p: _Pass, planned: Planned) -> Changes:
        """The driver's `changes` from the deployment the twin runs to `planned`. A running
        deployment that names a node no loaded package runs (one whose package's image moved since,
        say) cannot be stepped from: `bundle.rejected`, as a teardown without its packages is."""
        held, files = self._held(p)
        try:
            return p.driver.changes(Planned(deployment=held, files=files), planned, self.platforms,
                                    self.probe_packages)
        except ValueError as e:
            raise _Failed("rejected", RULE_BUNDLE_REJECTED, [_unsteppable(p.name, e)]) from e

    def _refusals(self, p: _Pass, *, restart_passed: bool = False) -> None:
        """A step refused before it touches anything, the twin running what it ran (D-050,
        D-029), for the first refusal that holds (`_refused`); a diverged twin, refused at
        `compiled` already, is checked again here for a resume past it. The spec's `allow_restart`
        counts only while it is the run's own (`_restart_allowed`). With `restart_passed`, the
        restart check is not made: a resume into an apply already begun plans again, purely, to
        the plan an earlier pass of the run checked under the run's own spec before it applied,
        and a newer spec written since must not refuse what that one allowed."""
        assert p.changes is not None
        refusal = _refused(p.record, restart_passed or _restart_allowed(p.record), p.changes, p.driver)
        if refusal is not None:
            self._refuse_step(p, *refusal)

    @staticmethod
    def _refuse_step(p: _Pass, rule: str, found: Iterable[Finding]) -> NoReturn:
        """The step refused for `rule` with `found`: the run ends `rejected` through `_end`, and its
        settle records it as a refused create is. It follows `plan done`, so it writes no event."""
        _log.info("%s: the step is refused before it touches anything: %s", p.name, rule, **p.fields(reason=rule))
        raise _Failed("rejected", rule, found, recorded=True)

    async def _apply(self, p: _Pass) -> None:
        """`applied`: the deployment applied, then every node `inspect` reports recorded. A create's
        is probed first when its lab is present while the record lacks `applied` (D-023), and its
        nodes hold nothing yet. A step's target is applied over the running lab, plainly, and the
        record moves to it: its bundle, blueprint, deployment and nodes, a removed node leaving the
        record and an added one joining it, each node keeping what it holds while its incarnation is
        the one the record knew, and holding nothing once it moved (D-050) or once the driver's
        `changes` restarted or recreated it, whose incarnation a runtime may keep. A step resumed after
        `planned` plans its target again, purely (the same deployment), and makes the refusals
        again before it touches anything: a kill between `planned` and the run's end skipped them.
        Into an apply already begun, the restart check is not made again: the pass that began the
        apply passed it under the run's own spec, which a newer one may have replaced since.
        A step's lab is always present, so it is probed only when an earlier pass of the run began
        its apply (`_apply_begun`, `_reconfigures`)."""
        stepping = p.run.operation == "step"
        # Read before this pass writes its own `apply started`: any earlier one began the apply, a transient
        # `apply failed` being no end, since the apply may have partly landed (D-050).
        begun = stepping and self._apply_begun(p.run.id)
        if stepping and p.changes is None:
            async with self._step(p, "plan"):
                assert p.target is not None
                planned = self._planned(p, p.target)
                self.store.put_deployment(planned.deployment, planned.files)  # filed already: the same files again
                p.changes = self._changes(p, planned)
            # Once the apply began, the pass that began it passed the restart check under the run's own spec, and
            # the pure re-plan is that plan: only the checks no spec setting decides are made again.
            self._refusals(p, restart_passed=begun)
            await self._checkpoint(p)  # a cancel during the pure re-plan is read before the apply begins
        async with self._step(p, "apply") as step:
            deployment, files = self._deployment(p)
            if stepping:
                reconfigure = begun and await self._reconfigures(p)
                await self._runtime(p, p.driver.apply, deployment, files, self.platforms, self.probe_packages,
                                    reconfigure=reconfigure)
            else:
                inspection = await self._runtime(p, p.driver.inspect, p.name)
                if inspection.state == "present":  # a lab while the record lacks applied: probe it (D-023)
                    silent = await self._silent(p, inspection)
                    if silent is None:
                        step.outcome = "skipped"
                        _log.info("%s: the lab is present and every node answers: no deploy", p.name, **p.fields())
                    else:
                        _log.info("%s: the lab is present and %s is silent: reconfigure", p.name, silent,
                                  **p.fields(node=silent))
                        await self._runtime(p, p.driver.apply, deployment, files, self.platforms,
                                            self.probe_packages, reconfigure=True)
                else:
                    await self._runtime(p, p.driver.apply, deployment, files, self.platforms, self.probe_packages)
            inspection = await self._runtime(p, p.driver.inspect, p.name)
            nodes = tuple(Node(name=n.name, handle=n.handle, address=n.address, incarnation=n.incarnation)
                          for n in sorted(inspection.nodes, key=lambda n: n.name))
            if stepping:
                assert p.changes is not None
                self._recorded(p, "applied", bundle_id=p.target, blueprint_id=self._manifest(p).blueprint_id,
                               deployment_id=deployment.id,
                               nodes=_carried(p.record.status.nodes, nodes, restarts(p.changes)))
            else:
                self._recorded(p, "applied", nodes=nodes)

    def _apply_begun(self, run_id: str) -> bool:
        """Whether the step `run_id`'s apply had begun (D-050): the run's events hold an `apply
        started`, of this pass or of one a core was stopped during or a transient failure ended.
        Either may have left the apply partly landed, so a transient `apply failed` is no end; a
        step's `apply done` is written only once `applied` is recorded, and `_apply` runs only while
        it is not. A step's lab is always present, so this, not the lab, says whether a resume
        probes it; and from it on a failure or a cancel leaves the twin diverged (D-029)."""
        return any(e.phase == "apply" and e.outcome == "started" for e in self.store.events(run_id))

    async def _reconfigures(self, p: _Pass) -> bool:
        """Whether a step resumed into an apply already begun applies its target with `reconfigure`
        (D-050): the lab probed against the target, as a create's partial lab is (D-023). False when
        every device node answers: the target is applied again plainly, which makes a node it lacks
        (`_silent`). True when one stays silent and the run's spec allows a restart
        (`_restart_allowed`), which a reconfigure makes of every node. A silent node without it ends
        the step `diverged` with `step.node.silent`, the node its object, the message naming the
        phase recorded last and what each node holds: the apply had begun, so no bundle describes
        the twin."""
        silent = await self._silent(p, await self._runtime(p, p.driver.inspect, p.name))
        if silent is None:
            _log.info("%s: the step's apply was cut short and every node answers: it is applied again", p.name,
                      **p.fields())
            return False
        if _restart_allowed(p.record):
            _log.info("%s: the step's apply was cut short and %s is silent: reconfigure", p.name, silent,
                      **p.fields(node=silent))
            return True
        mine = _own_step(p.record, p.run.id)
        assert mine is not None
        _log.warning("%s: the step's apply was cut short and %s is silent, and the spec does not allow a restart: "
                     "the twin is diverged", p.name, silent, **p.fields(node=silent, reason=RULE_NODE_SILENT))
        raise _Failed("diverged", RULE_NODE_SILENT, [Finding(
            rule=RULE_NODE_SILENT, severity="error", object=silent,
            message=f"{silent} is silent after the step's apply was cut short, and the reconfigure that would "
                    f"remedy it makes every node anew, which the spec does not allow (allow_restart): {p.name} is "
                    f"diverged, its apply begun after {mine.phase}. {_holding(p.record.status.nodes)}.")])

    async def _silent(self, p: _Pass, inspection: Inspection) -> str | None:
        """The first device node of a present lab that is silent: missing from the inspection,
        not running, without an address, or not answering within its boot window; None when
        every one answers. A node that refuses the login is not silent, and a reconfigure would
        not help it: the run fails at once with `readiness.unauthorized`.

        In a step's probe a node missing from the inspection is not silent: the plain apply that
        follows makes a node whose container is gone anew (verified-facts.md, containerlab 0.81.0),
        and a node the step adds needs no `allow_restart` (D-029), so a step cut short before its
        deploy made an added node goes on. A create's probe counts it silent (D-023)."""
        manifest = self._manifest(p)
        found = {n.name: n for n in inspection.nodes}
        probed = [node for node in manifest.nodes if node.name in found or p.run.operation != "step"]
        for node in probed:
            state = found.get(node.name)
            if state is None or not state.running or not state.address:
                return node.name
        for node in probed:
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
        """`ready`: each device node holding no bundle (all of a create's; a step's that it added,
        or whose incarnation moved) until its push transport answers, then every probe host until
        it shows its address. A step passes over, with no event, each node still holding the bundle
        it ran: its incarnation did not move, so it has answered since."""
        manifest = self._manifest(p)
        held = {n.name: n.holds for n in p.record.status.nodes}
        for node in manifest.nodes:
            if held.get(node.name) is not None:
                continue
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
        for probe in manifest.probes:
            probe_pkg = self.probe_packages[probe.format]
            for side, (host, _, _) in zip(SIDES, blueprint.hosts(probe), strict=True):
                await self._checkpoint(p)
                async with self._step(p, "ready", host):
                    await self._host_ready(p, probe_pkg, host, probe_package.host_values(probe_pkg, probe, side))
        self._recorded(p, "ready")

    async def _host_ready(self, p: _Pass, package: ProbePackage, host: str, values: Mapping[str, str]) -> None:
        """Wait for a probe host to show its expected text, polling its readiness command
        inside it, until the package's bound has passed since the first try."""
        argv = [mapping.render(word, values) for word in package.readiness.command]
        expect, budget = mapping.render(package.readiness.expect, values), package.readiness.timeout_s
        start = time.monotonic()
        while True:
            result = await self._runtime(p, p.driver.exec, p.name, host, argv, timeout_s=budget)
            if expect in result.stdout:
                return
            if time.monotonic() - start >= budget:
                raise _Failed("failed", RULE_TIMEOUT,
                              [Finding(rule=RULE_TIMEOUT, severity="error", object=host,
                                       message=f"{host} did not show {expect!r} within {budget:g}s")],
                              outcome="timed_out")
            await asyncio.sleep(HOST_POLL_S)

    async def _push(self, p: _Pass) -> None:
        """`pushed`: each device node's configuration pushed and the bundle it holds recorded at once,
        a node already holding the bundle passed over (a resume). One without a configuration is
        marked holding the bundle without a push (D-048); so is a step's node that still holds the
        bundle it ran when its configuration is unchanged (D-050)."""
        manifest, files = self._manifest(p), self._files(p)
        bundle_id = p.record.status.bundle_id
        assert bundle_id is not None
        ran = {n.name: n.config for n in self._from_manifest(p).nodes} if p.run.operation == "step" else {}
        for node in manifest.nodes:
            holds = next((n.holds for n in p.record.status.nodes if n.name == node.name), None)
            if holds == bundle_id:
                continue
            await self._checkpoint(p)
            async with self._step(p, "push", node.name) as step:
                if node.config is None:  # unmanaged (D-048): it owes nothing, yet holds the bundle like the rest
                    step.outcome = "skipped"
                    _log.info("%s: %s carries no configuration: nothing pushed", p.name, node.name,
                              **p.fields(node=node.name))
                    self._hold(p, node.name, bundle_id)
                    continue
                was = ran.get(node.name)
                if holds is not None and was is not None and was.sha256 == node.config.sha256:
                    step.outcome = "skipped"
                    _log.info("%s: %s's configuration is the one it runs: nothing pushed", p.name, node.name,
                              **p.fields(node=node.name))
                    self._hold(p, node.name, bundle_id)
                    continue
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
                self._hold(p, node.name, bundle_id)
        self._recorded(p, "pushed")

    def _hold(self, p: _Pass, name: str, bundle_id: str) -> None:
        """The node `name` recorded as holding the bundle `bundle_id`, at once."""
        nodes = tuple(replace(n, holds=bundle_id) if n.name == name else n for n in p.record.status.nodes)
        p.record = self._write(p.record, p.run, nodes=nodes)

    async def _verify_phase(self, p: _Pass) -> None:
        """`verified`, a step's wait (D-050, D-032): verify of the twin as it stands against the
        target, through the runtime, tried again every `verify_poll_s` until it holds (`ok`; a
        `failed` verdict, a node unread, is no more held than a `nonconforming` one) or `step_wait_s`
        has passed since the phase began. The last try begins within the budget and may end past it,
        so the wait's `after_s` may exceed its `budget_s`. The phase ends `done` either way, carrying
        `step.wait.expired` when the wait ran out: verify is advisory, and the step goes on. The
        run's verdict takes the last verify's findings and counts, the wait, and on expiry a warning
        naming the budget and the last status."""
        async with self._step(p, "verify") as step:
            manifest, bundle_id = self._manifest(p), p.record.status.bundle_id
            assert bundle_id is not None
            start = time.monotonic()
            while True:
                verdict = await self._runtime(p, self.verifier.verify, p.record, manifest, bundle_id, p.driver.exec)
                after = time.monotonic() - start
                if verdict.status == "ok" or after >= self.step_wait_s:
                    break
                await asyncio.sleep(min(self.verify_poll_s, self.step_wait_s - after))
            found = list(verdict.findings)
            if verdict.status == "ok":
                _log.info("%s: verify held after %.1fs", p.name, after, **p.fields())
            else:
                step.rule = RULE_WAIT_EXPIRED
                found.append(Finding(rule=RULE_WAIT_EXPIRED, severity="warning", object=p.name,
                                     message=f"Verify did not hold within the step's wait of {self.step_wait_s:g}s: "
                                             f"its last verdict was {verdict.status}."))
                _log.warning("%s: the step's wait of %gs expired: verify was %s", p.name, self.step_wait_s,
                             verdict.status, **p.fields(reason=RULE_WAIT_EXPIRED))
            p.found, p.counts = findings.order(found), verdict.counts
            p.wait = Wait(outcome="settled" if verdict.status == "ok" else "expired", budget_s=int(self.step_wait_s),
                          after_s=after)
            self._recorded(p, "verified")

    async def _flows_phase(self, p: _Pass) -> None:
        """`flows`: each probe of the target recorded from each host as `not_started`, since the flow
        across a step is not built in this phase (D-051); the phase is otherwise skipped."""
        async with self._step(p, "flows") as step:
            step.outcome = "skipped"
            p.loss = _not_started(self._manifest(p))
            self._recorded(p, "flows")

    # The dry run.

    async def dry_run(
        self, twin: str, spec: Spec, held: TwinRecord | None = None
    ) -> tuple[Deployment | None, Verdict, Changes | None]:
        """What the loop would do with `spec` for `twin`, writing nothing: the compile (or the
        spec's bundle), the driver's `admit` against the live reservations, and its pure `plan`.
        `held` is the twin's record when it exists: once it applied a lab (`applied`), the spec is
        a step's, and the admission is with the deployment it holds, checking only the demand the
        target adds (D-049); the driver's `changes` from that deployment to the target follow, and
        the step's refusals (`_refused`, the spec's `allow_restart` deciding). It answers the
        deployment, a verdict of operation `plan` and, for a step, the changes. The verdict is
        `ok`, or `rejected` with the findings: for a refused admission or a driver this core does
        not serve, with no deployment, since a refusal reserves nothing to plan with; for a step
        the loop would refuse, with the deployment and the changes (none when the deployment the
        twin runs cannot be stepped from, `bundle.rejected`). A blueprint that does not compile
        raises `compiler.Uncompilable` (so does a bundle naming a package this core has not
        loaded), a refused plan `driver.Unplannable`, and an id the store does not hold
        `store.NotFound`, for the API to answer."""
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
            return None, Verdict(operation="plan", status="rejected", subject=subject, findings=(finding,)), None
        # The loop's `_lacking` guard is not repeated: with a real driver, `changes` raises for a running node no
        # loaded package runs, and the dry run answers `bundle.rejected` below.
        running: Planned | None = None  # the deployment a step goes from
        if held is not None and applied(held):
            assert held.status.deployment_id is not None
            deployed, files = self.store.get_deployment(held.status.deployment_id)
            running = Planned(deployment=deployed, files=files)
        async with self._admission:
            answer = await driver.admit(manifest, self.platforms, self.probe_packages, twin, self._reserved(twin),
                                        held=None if running is None else running.deployment)
        if isinstance(answer, Refusal):
            refusal = Finding(rule=answer.rule, severity="error", object=twin, message=answer.message)
            return None, Verdict(operation="plan", status="rejected", subject=subject, findings=(refusal,)), None
        planned = driver.plan(manifest, bundle_id, self.platforms, self.probe_packages, twin, answer)
        ok = Verdict(operation="plan", status="ok", subject=replace(subject, deployment_id=planned.deployment.id),
                     findings=())
        if running is None:
            return planned.deployment, ok, None
        assert held is not None
        try:
            changes = driver.changes(running, planned, self.platforms, self.probe_packages)
        except ValueError as e:
            return planned.deployment, replace(ok, status="rejected", findings=(_unsteppable(twin, e),)), None
        refused = _refused(held, spec.allow_restart, changes, driver)
        if refused is None:
            return planned.deployment, ok, changes
        return planned.deployment, replace(ok, status="rejected", findings=findings.order(refused[1])), changes


def applied(record: TwinRecord) -> bool:
    """Whether the twin applied a lab: its record names a deployment and the nodes the apply left.
    A new spec of such a twin is a step's (D-050), and of any other a create's: a twin whose create
    never applied is created again. The loop dispatches by it, and the API queues its run by it."""
    return record.status.deployment_id is not None and bool(record.status.nodes)


def _refused(
    record: TwinRecord, allow_restart: bool, changes: Changes, driver: Driver
) -> tuple[str, tuple[Finding, ...]] | None:
    """The refusal of a step of the twin `record` describes that makes `changes` on `driver`, as
    its rule and findings, or None (D-050, D-029). The first that holds, what no spec can clear
    first: a diverged twin, which accepts only deletion (`step.twin.diverged`); a change the
    driver cannot make (`step.relink.unsupported`), one finding per node it cannot satisfy and one
    for the twin when links change on a driver that cannot relink; a node restarted or recreated
    without `allow_restart` (`step.restart.required`), one finding per node, naming its action and
    reasons. The loop refuses by it after `planned`, and the dry run answers it."""
    name = record.name
    if diverged(record):
        return RULE_STEP_TWIN_DIVERGED, (_diverged_finding(name),)
    by_node = {n.node: n for n in changes.nodes}
    found = [Finding(rule=RULE_RELINK_UNSUPPORTED, severity="error", object=node,
                     message=f"The {driver.name} driver cannot make the change the step asks of {node} "
                             f"({_reasons(by_node[node])}).")
             for node in unsupported(changes)]
    if relinks(changes) and not driver.capabilities().relink:
        found.append(Finding(
            rule=RULE_RELINK_UNSUPPORTED, severity="error", object=name,
            message=f"The step changes {name}'s links ({len(changes.links_added)} added, "
                    f"{len(changes.links_removed)} removed), and the {driver.name} driver cannot change a link "
                    f"of a running twin."))
    if found:
        return RULE_RELINK_UNSUPPORTED, tuple(found)
    restarted = restarts(changes)
    if restarted and not allow_restart:
        return RULE_RESTART_REQUIRED, tuple(Finding(
            rule=RULE_RESTART_REQUIRED, severity="error", object=node,
            message=f"{node} would be {by_node[node].action} ({_reasons(by_node[node])}), and the spec does "
                    f"not allow a restart: set allow_restart to step it.") for node in restarted)
    return None


def _diverged_finding(twin: str) -> Finding:
    return Finding(rule=RULE_STEP_TWIN_DIVERGED, severity="error", object=twin,
                   message=f"{twin} is diverged: no bundle describes it, so it accepts only deletion.")


def _unsteppable(twin: str, error: ValueError) -> Finding:
    """`bundle.rejected` for a step whose running deployment the driver's `changes` cannot read (it
    names a node no loaded package runs, as after a package's image moved), as a teardown without
    its packages is refused."""
    return Finding(rule=RULE_BUNDLE_REJECTED, severity="error", object=twin,
                   message=f"The deployment {twin} runs cannot be stepped from: {error}.")


def _reasons(change: NodeChange) -> str:
    """A node change's reasons for a finding's message, comma-separated."""
    return ", ".join(change.reasons) or "no reason given"


def _holding(nodes: Iterable[Node]) -> str:
    """What each node holds as the record knows it, a sentence for a diverged step's finding: before
    `applied` the record names the running twin's nodes, which the lab may no longer match. The
    nodes are grouped by the bundle each holds, in the record's order (`As the record knows, n1, n2
    hold <bundle>; n3 holds nothing`)."""
    held: dict[str | None, list[str]] = {}
    for node in nodes:
        held.setdefault(node.holds, []).append(node.name)
    listed = "; ".join(f"{', '.join(names)} {'holds' if len(names) == 1 else 'hold'} {bundle_id or 'nothing'}"
                       for bundle_id, names in held.items())
    return f"As the record knows, {listed}" if listed else "The record knows no node"


def _left_diverged(record: TwinRecord, run_id: str, phase: runs.Phase | None, cause: str | None) -> Finding:
    """`step.diverged`, an error about the twin: its step, the run `run_id`, failed for the rule
    `cause` (or was cancelled, for None) during `phase` (None when no pass was running it), after
    its apply began. The message names the phase, the last the step recorded, and what each node
    holds as the record knows it (D-029, D-050)."""
    mine = _own_step(record, run_id)
    assert mine is not None  # an apply follows `compiled`, which wrote it
    during = "" if phase is None else f" during {phase}"
    lead = f"The step was cancelled{during}" if cause is None else f"The step failed{during} ({cause})"
    return Finding(rule=RULE_STEP_DIVERGED, severity="error", object=record.name,
                   message=f"{lead}, after its apply began; the twin is left as it stands, diverged, and accepts only "
                           f"deletion. The last phase it recorded is {mine.phase}. {_holding(record.status.nodes)}.")


def _not_started(manifest: Manifest) -> tuple[Loss, ...]:
    """Each probe of `manifest` from each host, `not_started`, sorted by probe and host: a step's
    flows, since the flow across a step is not built in this phase (D-051)."""
    return tuple(Loss(probe=name, from_=side, outcome="not_started")
                 for name in sorted(probe.name for probe in manifest.probes) for side in SIDES)


def _completed(record: TwinRecord, run_id: str) -> bool:
    """Whether the step `run_id` has run all its phases (`last_step` at `flows`): its end was all
    it had left, so a cancel or a refusal ends it as it would have ended, `ok`."""
    mine = _own_step(record, run_id)
    return mine is not None and mine.phase == STEP[-1][0]


def _step_done(record: TwinRecord, run_id: str) -> dict[str, Any]:
    """The status members a step's run `run_id` writes when it ends `ok`: Ready True and Stepping
    False for `twin.ready`, since the twin runs what the spec asks; `last_step` `stepped`, the
    run's own, once it reached `flows`, or `unchanged`, from and to the twin's bundle, when it
    ended at `compiled`."""
    status = record.status
    assert status.bundle_id is not None  # a stepping twin applied a bundle
    mine = _own_step(record, run_id)
    last_step = (replace(mine, outcome="stepped") if mine is not None else
                 LastStep(outcome="unchanged", from_=status.bundle_id, to=status.bundle_id, phase="compiled",
                          run_id=run_id))
    ready = set_condition(ready_condition(status.conditions, "True", REASON_READY), "Stepping", "False", REASON_READY)
    return {"conditions": ready, "last_step": last_step}


def _step_ending(
    record: TwinRecord,
    run_id: str,
    outcome: Literal["rejected", "cancelled", "diverged"],
    reason: str,
    diverged_for: str | None = None,
) -> dict[str, Any]:
    """The status members a step's run `run_id` writes when it ends `outcome` short of its target:
    Ready and Stepping False for `reason`, and for `diverged` the Diverged condition True for
    `diverged_for` (`reason` unless given); `last_step` the run's own with that outcome, or, for a
    run that ended before `compiled` wrote one, the twin's bundle as both ends at `compiled`. A
    twin diverged already keeps a `last_step` the run did not write: it records the step that left
    the twin diverged, its bundles, run and phase, which D-029 keeps, and a run refused for
    `step.twin.diverged` (or ended before it compiled, by a cancel or a core that cannot serve the
    twin) never began. The Diverged condition is never set back."""
    status = record.status
    assert status.bundle_id is not None  # a stepping twin applied a bundle
    mine = _own_step(record, run_id)
    conditions = set_condition(ready_condition(status.conditions, "False", reason), "Stepping", "False", reason)
    if outcome == "diverged":
        conditions = set_condition(conditions, "Diverged", "True", diverged_for or reason)
    if mine is None and diverged(record):
        return {"conditions": conditions}
    last_step = (replace(mine, outcome=outcome) if mine is not None else
                 LastStep(outcome=outcome, from_=status.bundle_id, to=status.bundle_id, phase="compiled",
                          run_id=run_id))
    return {"conditions": conditions, "last_step": last_step}


def _stepping_subject(
    record: TwinRecord,
    run_id: str,
    target: str | None,
    manifest: Manifest | None,
    deployment: Deployment | None = None,
) -> Subject:
    """A step's verdict subject: what the run compiled and planned, else what runs. Once the run
    knows its `target` bundle, the blueprint is the target's, from its `manifest`, which the
    caller reads when the pass did not: the record's spec may be a newer one a client wrote while
    the run ran, and the record's blueprint the running twin's, and neither is ever paired with
    the run's target. Before it, the bundle is the running twin's, and the blueprint the spec's,
    or, when the spec names a bundle, the record's. The target `deployment` once planned in this
    pass, else the record's."""
    status, spec = record.status, record.spec
    if target is not None:
        assert manifest is not None  # the target's, filed before `compiled` named it
        blueprint_id: str | None = manifest.blueprint_id
    else:
        blueprint_id = spec.blueprint_id or status.blueprint_id
    return Subject(twin=record.name, run_id=run_id, blueprint_id=blueprint_id, bundle_id=target or status.bundle_id,
                   deployment_id=status.deployment_id if deployment is None else deployment.id)


def _carried(known: Iterable[Node], nodes: Iterable[Node], restarted: Iterable[str]) -> tuple[Node, ...]:
    """`nodes`, as a step's apply left them, each holding what the record's node of its name held
    while its incarnation is the one the record knew; one whose incarnation moved, or is unknown (a
    node never started), or that the record lacks, holds nothing, and so does one the driver's
    `changes` restarted or recreated (`restarted`): a runtime that restarts a container in place
    keeps its incarnation, and the node lost what it was pushed all the same."""
    was, anew = {n.name: n for n in known}, set(restarted)
    return tuple(replace(n, holds=was[n.name].holds)
                 if n.name in was and n.name not in anew and n.incarnation is not None
                 and n.incarnation == was[n.name].incarnation else n
                 for n in nodes)


def _own_step(record: TwinRecord, run_id: str) -> LastStep | None:
    """The record's `last_step` when the run `run_id` wrote it, else None (a step's run before
    `compiled`, or another run's step)."""
    last = record.status.last_step
    return last if last is not None and last.run_id == run_id else None


def diverged(record: TwinRecord) -> bool:
    """Whether the twin is diverged, its Diverged condition True: it accepts only deletion (D-029).
    The loop refuses a step of it, and the API a new spec."""
    return any(c.type == "Diverged" and c.status == "True" for c in record.status.conditions)


def ready_reason(conditions: Iterable[Condition]) -> str | None:
    """The Ready condition's reason, or None without one."""
    return next((c.reason for c in conditions if c.type == "Ready"), None)
