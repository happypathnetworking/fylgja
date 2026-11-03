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

Every phase emits run events: `started`, then `done`, `skipped`, `failed` or `timed_out`, with
the seconds since `started`, and on a failure the rule; `ready` and `push` emit a pair per node.

A resume runs the phase after the one recorded, under the run the record names. Two rules make
it reach the desired state in that one pass (D-023): a lab present while the record lacks
`applied` is probed, and applied again with `reconfigure` when a device node stays silent (it is
missing, stopped, without an address, or does not answer), or not at all when every one answers;
and a node already holding the bundle is never pushed again.

Failures are of two classes. **A failure only a new spec can clear** (a refused admission, an
uncompilable blueprint, a refused plan, a node that does not become ready, a refused or
unauthorized push, a missing credential) ends the run `rejected` (a compile, admission or plan
refusal) or `failed`, cleans up, and sets `observed_generation`, so the loop waits for the spec
to be written again. **A transient failure** (the driver's `DriverFailed`, an unreachable node,
a store's `OSError` or lost compare-and-set) leaves the record as it is, logs, and queues the
twin again after a backoff that doubles from 1 s to 60 s and resets on a pass that completes.

The run's verdict is written before the record's last write, so a core stopped between the two
loses neither: a pass that finds the record naming an ended run completes that write from the
verdict. Cleanup is then the driver's `destroy`, when a deployment was filed, and the record's
nodes, deployment and allocation cleared; a destroy that fails keeps the allocation, so a
lingering network's subnet stays reserved, and is retried on the next pass.
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
from fylgja_core.queue import WorkQueue
from fylgja_core.readiness import RULE_TIMEOUT, NotReady, await_transport
from fylgja_core.run import Event, Outcome, Run
from fylgja_core.twin_record import Condition, Node, TwinRecord

# Rule ids: findings the loop files and the reasons it sets on the Ready condition; the
# catalogue is docs/rules.md.
RULE_BLUEPRINT_MISSING = "blueprint.missing"
RULE_BUNDLE_MISSING = "bundle.missing"
RULE_BUNDLE_REJECTED = "bundle.rejected"
RULE_PLAN_REJECTED = "plan.rejected"
RULE_CANCELLED = "run.cancelled"
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
        super().__init__(reason)


class _Retry(Exception):
    """A transient failure inside a run, carrying the run's id for the log line."""

    def __init__(self, error: Exception, run_id: str) -> None:
        self.error = error
        self.run_id = run_id
        super().__init__(str(error))


@dataclass
class _Step:
    outcome: Outcome = "done"


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
    """The loop over a store: the passes, the queue they are scheduled by, and each twin's backoff."""

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
        self.queue = WorkQueue()
        # Each twin's delay after its last transient failure; a pass that completes drops it.
        self.backoff: dict[str, float] = {}
        # Admission and its record, one twin at a time: `reserved` is all that keeps two creates off one subnet.
        self._admission = asyncio.Lock()

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
        _log.warning("%s: %s: %s; trying again in %gs", name, type(error).__name__, error, delay,
                     **logs.fields(twin=name, run=run_id, error=type(error).__name__, retry_s=delay))
        self.queue.put(name, delay_s=delay)

    async def _pass(self, name: str) -> None:
        try:
            record = self.store.get_twin(name)
        except store.NotFound:
            return
        if record.deletion_requested_at is not None:
            await self._delete(record)
            return
        driver = self.drivers[record.spec.driver]
        if record.status.run_id is not None:
            named = self._read_run(record.status.run_id)
            if named is not None and named.state == "ended":
                # The run's end was recorded and the record's last write was not, or its cleanup is owed.
                try:
                    await self._settle(record, named, driver)
                except TRANSIENT as e:
                    raise _Retry(e, named.id) from e
                return
        if record.generation == record.status.observed_generation:
            return
        record, run = self._take_run(record)
        p = _Pass(record=record, run=run, driver=driver)
        work: Mapping[runs.Phase, Callable[[_Pass], Awaitable[None]]] = {
            "compile": self._compile, "admit": self._admit, "plan": self._plan,
            "apply": self._apply, "ready": self._ready, "push": self._push,
        }
        try:
            try:
                for recorded, phase in self._phases_after(p.record.status.phase):
                    if await self._check_cancel(p.run.id):
                        raise NotImplementedError("cancellation is built with the destroy path")
                    await work[phase](p)
                    _log.info("%s: %s", name, recorded, **p.fields(phase=phase))
            except _Failed as failure:
                await self._end(p, failure.status, failure.findings, failure.reason)
                return
            await self._end(p, "ok", (), None)
        except TRANSIENT as e:
            raise _Retry(e, p.run.id) from e

    # The run.

    def _read_run(self, run_id: str) -> Run | None:
        try:
            return self.store.get_run(run_id)
        except store.NotFound:
            return None

    def _take_run(self, record: TwinRecord) -> tuple[TwinRecord, Run]:
        """The run this pass acts under, running, and the record naming it with Ready False
        `twin.creating`: the run the record names, if it has not ended; else the newest queued
        create run of the twin; else a new one, the core's. The record names it before it is
        marked running, so a core stopped between the two finds it again."""
        run = self._read_run(record.status.run_id) if record.status.run_id is not None else None
        if run is None or run.state == "ended":
            waiting = [r for r in self.store.list_runs(record.name) if r.state == "queued" and r.operation == "create"]
            if waiting:
                run = waiting[0]
            else:
                run = runs.queued(record.name, "create", "core")
                self.store.create_run(run)
        conditions = ready_condition(record.status.conditions, "False", REASON_CREATING)
        if record.status.run_id != run.id or conditions != record.status.conditions:
            record = self._write(record, run, run_id=run.id, conditions=conditions)
        if run.state == "queued":
            running = replace(run, state="running")
            self.store.update_run(running, "queued")
            run = running
            _log.info("%s: run %s started", record.name, run.id, **logs.fields(twin=record.name, run=run.id))
        else:
            _log.info("%s: run %s resumed after %s", record.name, run.id, record.status.phase or "nothing",
                      **logs.fields(twin=record.name, run=run.id))
        return record, run

    @staticmethod
    def _phases_after(phase: str | None) -> tuple[tuple[str, runs.Phase], ...]:
        names = [recorded for recorded, _ in CREATE]
        if phase is None:
            return CREATE
        return CREATE[names.index(phase) + 1:] if phase in names else ()

    async def _check_cancel(self, run_id: str) -> bool:
        """Whether the run was marked cancelling. A hook: cancellation (D-023) is built with the
        destroy path, and until then no run is cancelled."""
        return False

    async def _delete(self, record: TwinRecord) -> None:
        """The destroy path (D-025), a hook: it is built with cancellation."""
        raise NotImplementedError(f"the deletion of {record.name} is built with the destroy path")

    async def _end(
        self, p: _Pass, status: Literal["ok", "rejected", "failed"], found: tuple[Finding, ...], reason: str | None
    ) -> None:
        """End the run with its verdict, then settle the record."""
        verdict = Verdict(operation="create", status=status, subject=self._subject(p.record, p.run), findings=found)
        ended = runs.ended(p.run, verdict)
        self.store.update_run(ended, p.run.state)
        _log.info("%s: run %s ended %s", p.name, ended.id, status, **p.fields(status=status, reason=reason))
        await self._settle(p.record, ended, p.driver, reason)

    async def _settle(self, record: TwinRecord, run: Run, driver: Driver, reason: str | None = None) -> None:
        """The record's last write for an ended run: Ready True for an `ok` verdict; otherwise the
        cleanup, `destroy` when a deployment was filed, and then the nodes, deployment and
        allocation cleared, with Ready False for `reason` (the run's failing event's rule when
        not given). A failed destroy records the failure, keeps the rest, and is raised."""
        assert run.verdict is not None
        if run.verdict.status == "ok":
            self._write(record, run, conditions=ready_condition(record.status.conditions, "True", REASON_READY),
                        observed_generation=record.generation, run_id=None)
            return
        reason = reason if reason is not None else self._failing_rule(run)
        conditions = ready_condition(record.status.conditions, "False", reason)
        if record.status.deployment_id is not None:
            deployment, files = self.store.get_deployment(record.status.deployment_id)
            try:
                await driver.destroy(deployment, files, self.platforms, self.probe_packages)
            except DriverFailed:
                if (conditions, record.generation) != (record.status.conditions, record.status.observed_generation):
                    self._write(record, run, conditions=conditions, observed_generation=record.generation)
                raise
        self._write(record, run, conditions=conditions, observed_generation=record.generation, run_id=None, phase=None,
                    nodes=(), deployment_id=None, allocation=None)

    def _failing_rule(self, run: Run) -> str:
        """The rule of the run's last event that carries one: the failure's, which is the
        condition's reason. The first finding's rule if no event carries one."""
        rules = [e.rule for e in self.store.events(run.id) if e.rule is not None]
        assert run.verdict is not None
        return rules[-1] if rules else run.verdict.findings[0].rule

    @staticmethod
    def _subject(record: TwinRecord, run: Run) -> Subject:
        status, spec = record.status, record.spec
        return Subject(twin=record.name, run_id=run.id, blueprint_id=status.blueprint_id or spec.blueprint_id,
                       bundle_id=status.bundle_id or spec.bundle_id, deployment_id=status.deployment_id)

    # The record and the events.

    def _write(self, record: TwinRecord, run: Run, **changes: Any) -> TwinRecord:
        """The record with `changes` to its status, written by compare-and-set; one audit line."""
        written = self.store.update_twin(replace(record, status=replace(record.status, **changes)), record.revision)
        logs.audit(run.principal, "status", record.name, run=run.id, phase=written.status.phase,
                   revision=written.revision)
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
        unless it says otherwise; a failure's outcome and reason; `failed` for a transient
        failure, with its rule when it has one. Anything else, a kill, ends nothing."""
        self._event(p, phase, "started", node)
        start = time.monotonic()
        step = _Step()
        try:
            yield step
        except _Failed as failure:
            self._event(p, phase, failure.outcome, node, time.monotonic() - start, failure.reason)
            raise
        except TRANSIENT as e:
            rule: str | None = getattr(e, "rule", None)
            with contextlib.suppress(*TRANSIENT, store.StoreError):  # the store may be what failed
                self._event(p, phase, "failed", node, time.monotonic() - start, rule)
            raise
        self._event(p, phase, step.outcome, node, time.monotonic() - start)

    # What the phases read: from this pass, or the store on a resume.

    def _files(self, p: _Pass) -> Mapping[str, bytes]:
        if p.files is None:
            assert p.record.status.bundle_id is not None
            p.files = self.store.get_bundle(p.record.status.bundle_id)
        return p.files

    def _manifest(self, p: _Pass) -> Manifest:
        if p.manifest is None:
            p.manifest = bundle.decode(json.loads(self._files(p)["manifest.json"]))
        return p.manifest

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
                p.manifest = bundle.decode(json.loads(p.files["manifest.json"]))
                unloaded = self._unloaded(p.manifest)
                if unloaded:
                    raise _Failed("rejected", RULE_BUNDLE_REJECTED, unloaded)
            p.record = self._write(p.record, p.run, phase="compiled", blueprint_id=p.manifest.blueprint_id,
                                   bundle_id=bundle_id)

    def _unloaded(self, manifest: Manifest) -> list[Finding]:
        """A bundle compiled elsewhere may name a package this core has not loaded; the compile's rules say so."""
        return [Finding(rule=compiler.RULE_PLATFORM, severity="error", object=node.name,
                        message=f"No loaded platform package is {node.platform!r}.")
                for node in manifest.nodes if node.platform not in self.platforms] + [
                Finding(rule=compiler.RULE_PROBE_FORMAT, severity="error", object=probe.name,
                        message=f"No loaded probe package runs {probe.format!r}.")
                for probe in manifest.probes if probe.format not in self.probe_packages]

    async def _admit(self, p: _Pass) -> None:
        async with self._step(p, "admit"), self._admission:
            reserved = [t.status.allocation for t in self.store.list_twins()
                        if t.name != p.name and t.status.allocation is not None]
            answer = await p.driver.admit(self._manifest(p), self.platforms, self.probe_packages, p.name, reserved)
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
            inspection = await p.driver.inspect(p.name)
            if inspection.state == "present":  # a lab while the record lacks applied: probe it (D-023)
                silent = await self._silent(p, inspection)
                if silent is None:
                    step.outcome = "skipped"
                    _log.info("%s: the lab is present and every node answers: no deploy", p.name, **p.fields())
                else:
                    _log.info("%s: the lab is present and %s is silent: reconfigure", p.name, silent,
                              **p.fields(node=silent))
                    await p.driver.apply(deployment, files, self.platforms, self.probe_packages, reconfigure=True)
            else:
                await p.driver.apply(deployment, files, self.platforms, self.probe_packages)
            inspection = await p.driver.inspect(p.name)
            nodes = tuple(Node(name=n.name, handle=n.handle, address=n.address, incarnation=n.incarnation)
                          for n in sorted(inspection.nodes, key=lambda n: n.name))
            p.record = self._write(p.record, p.run, phase="applied", nodes=nodes)

    async def _silent(self, p: _Pass, inspection: Inspection) -> str | None:
        """The first device node of a present lab that is silent: missing from the inspection,
        not running, without an address, or not answering within its boot window; None when
        every one answers."""
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
            try:
                await self.readiness(address, package, self._login(package, node.name),
                                     timeout_s=package.readiness.timeout_s)
            except NotReady:
                return node.name
        return None

    async def _ready(self, p: _Pass) -> None:
        manifest = self._manifest(p)
        for node in manifest.nodes:
            async with self._step(p, "ready", node.name):
                package = self.platforms[node.platform]
                credential = self._login(package, node.name)
                try:
                    await self.readiness(self._address(p, node.name), package, credential,
                                         timeout_s=package.readiness.timeout_s)
                except NotReady as e:
                    outcome: Outcome = "timed_out" if e.rule == RULE_TIMEOUT else "failed"
                    raise _Failed("failed", e.rule, [Finding(rule=e.rule, severity="error", object=node.name,
                                                             message=e.message)], outcome) from e
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
            async with self._step(p, "push", node.name):
                package = self.platforms[node.platform]
                credential = self._login(package, node.name)
                config = files[node.config.file].decode()
                try:
                    answer = await self.pusher(self._address(p, node.name), package, config, credential)
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
