"""The reconcile loop (Constitution VIII, D-023, D-025): one pass drives a twin's create from
compiled to pushed as a run with events, over a local store in a temporary directory, a fake
driver, a fake readiness wait and a fake push."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import io
import json
import logging
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import pytest
from fakes import FakeDriver, FakePush, FakeReady, fake_push, fake_ready

from fylgja_core import (
    blueprint,
    bundle,
    clock,
    compiler,
    deployment,
    documents,
    logs,
    platform_package,
    probe_package,
    push,
    reconcile,
)
from fylgja_core.credentials import Credential, Provider
from fylgja_core.driver import Planned, Refusal, Unplannable
from fylgja_core.findings import Finding, Subject
from fylgja_core.local_store import LocalStore
from fylgja_core.reconcile import Reconciler
from fylgja_core.run import Run, queued
from fylgja_core.run import State as RunState
from fylgja_core.store import Change, Conflict, NotFound
from fylgja_core.twin_record import Condition, Spec, Status, TwinRecord

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = {
    p.id: p
    for p in map(platform_package.load, [ROOT / "psp/nokia_srlinux.yaml", ROOT / "psp/arista_eos.yaml",
                                         ROOT / "testdata/packages/chassisos.yaml"])
}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes/ping.yaml")]}
ENVIRON = {
    "FYLGJA_CREDENTIAL_SRLINUX_USERNAME": "admin",
    "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "NokiaSrl1!",
    "FYLGJA_CREDENTIAL_EOS_USERNAME": "admin",
    "FYLGJA_CREDENTIAL_EOS_PASSWORD": "admin",
}
DEVICES = ["n1", "n2", "n3"]

Seen = tuple[str, str, str | None]


@pytest.fixture
def store(tmp_path: Path) -> Iterator[LocalStore]:
    s = LocalStore.open(tmp_path / "store")
    yield s
    s.close()


def file_blueprint(store: LocalStore, path: str = "testdata/blueprint/three-node.json") -> str:
    blueprint_id, _ = store.put_blueprint(json.loads((ROOT / path).read_text()))
    return blueprint_id


def new_twin(
    store: LocalStore, blueprint_id: str | None, name: str = "t", *, bundle_id: str | None = None, driver: str = "fake"
) -> None:
    spec = Spec(blueprint_id=blueprint_id, bundle_id=bundle_id, driver=driver, allow_restart=False)
    store.create_twin(TwinRecord(name=name, revision=1, generation=1, spec=spec,
                                 status=Status(observed_generation=0, conditions=(), nodes=())))


def make(
    store: LocalStore,
    driver: FakeDriver,
    ready: FakeReady | None = None,
    pusher: FakePush | None = None,
    environ: Mapping[str, str] = ENVIRON,
    *,
    workers: int = 4,
    resync_s: float = 300.0,
) -> Reconciler:
    return Reconciler(store, {driver.name: driver}, PLATFORMS, PROBES, Provider(environ), workers=workers,
                      resync_s=resync_s, pusher=pusher if pusher is not None else fake_push(driver=driver),
                      readiness=ready if ready is not None else fake_ready(driver=driver), cancel_poll_s=0.01)


def ready_of(record: TwinRecord) -> Condition:
    (condition,) = [c for c in record.status.conditions if c.type == "Ready"]
    return condition


def only_run(store: LocalStore, twin: str = "t") -> Run:
    (run,) = store.list_runs(twin)
    return run


def seen(store: LocalStore, run_id: str) -> list[Seen]:
    return [(e.phase, e.outcome, e.node) for e in store.events(run_id)]


def pairs(phase: str, nodes: list[str]) -> list[Seen]:
    return [(phase, outcome, node) for node in nodes for outcome in ("started", "done")]


UP_TO_APPLY: list[Seen] = [
    ("compile", "started", None), ("compile", "done", None),
    ("admit", "started", None), ("admit", "done", None),
    ("plan", "started", None), ("plan", "done", None),
    ("apply", "started", None), ("apply", "done", None),
]
CREATE: list[Seen] = UP_TO_APPLY + pairs("ready", DEVICES) + pairs("push", DEVICES)


def assert_cleaned_up(record: TwinRecord, reason: str) -> None:
    assert ready_of(record).status == "False" and ready_of(record).reason == reason
    assert record.status.observed_generation == record.generation == 1
    assert record.status.nodes == () and record.status.deployment_id is None and record.status.allocation is None
    assert record.status.run_id is None and record.status.phase is None


def test_a_create_runs_every_phase_and_ends_ready(store: LocalStore) -> None:
    blueprint_id = file_blueprint(store)
    new_twin(store, blueprint_id)
    driver = FakeDriver()
    pusher = fake_push(driver=driver)
    asyncio.run(make(store, driver, pusher=pusher).reconcile("t"))

    record = store.get_twin("t")
    status = record.status
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert ready_of(record).since is not None
    assert status.observed_generation == record.generation == 1
    assert status.phase == "pushed" and status.run_id is None
    assert status.blueprint_id == blueprint_id and status.bundle_id is not None
    assert status.allocation == {"lab": "t", "mgmt_subnet": "10.0.1.0/24"}
    assert [n.name for n in status.nodes] == DEVICES
    assert all(n.address and n.incarnation == "boot-1" and n.holds == status.bundle_id for n in status.nodes)
    bundle_files = store.get_bundle(status.bundle_id)
    assert status.deployment_id is not None
    deployment, _ = store.get_deployment(status.deployment_id)
    assert deployment.bundle_id == status.bundle_id and deployment.allocation == status.allocation

    run = only_run(store)
    assert run.state == "ended" and run.operation == "create" and run.principal == "core" and run.ended_at
    assert run.verdict is not None and run.verdict.status == "ok" and run.verdict.findings == ()
    assert run.verdict.subject == Subject(twin="t", run_id=run.id, blueprint_id=blueprint_id,
                                          bundle_id=status.bundle_id, deployment_id=status.deployment_id)
    events = store.events(run.id)
    assert seen(store, run.id) == CREATE
    assert all(e.duration_s is not None and e.duration_s >= 0 for e in events if e.outcome == "done")
    assert all(e.rule is None for e in events)
    assert pusher.calls == [(n, bundle_files[f"configs/{n}.cfg"].decode()) for n in DEVICES]
    assert driver.calls == [("admit", "t"), ("plan", "t"), ("inspect", "t"), ("apply", "t"), ("inspect", "t")]


def test_a_queued_create_run_is_the_run_the_pass_takes(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    asked = queued("t", "create", "alice")
    store.create_run(asked)
    driver = FakeDriver()
    asyncio.run(make(store, driver).reconcile("t"))

    run = only_run(store)
    assert run.id == asked.id and run.principal == "alice" and run.state == "ended"
    assert run.verdict is not None and run.verdict.status == "ok"
    assert seen(store, run.id) == CREATE


def test_a_settled_twin_is_left_alone(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    r = make(store, driver)
    asyncio.run(r.reconcile("t"))
    revision, calls = store.get_twin("t").revision, list(driver.calls)
    asyncio.run(r.reconcile("t"))
    assert store.get_twin("t").revision == revision and driver.calls == calls and len(store.list_runs("t")) == 1


def test_an_absent_twin_is_nothing_to_do(store: LocalStore) -> None:
    driver = FakeDriver()
    asyncio.run(make(store, driver).reconcile("t"))
    assert driver.calls == [] and store.list_runs() == []


def test_a_refused_admission_is_a_rejected_run_that_waits_for_a_new_spec(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver(refuse=Refusal("admission.capacity", "no room"))
    r = make(store, driver)
    asyncio.run(r.reconcile("t"))

    run = only_run(store)
    assert run.state == "ended" and run.verdict is not None and run.verdict.status == "rejected"
    refusal = Finding(rule="admission.capacity", severity="error", object="t", message="no room")
    assert run.verdict.findings == (refusal,)
    assert seen(store, run.id) == [("compile", "started", None), ("compile", "done", None),
                                   ("admit", "started", None), ("admit", "failed", None)]
    assert store.events(run.id)[-1].rule == "admission.capacity"
    record = store.get_twin("t")
    assert_cleaned_up(record, "admission.capacity")
    assert ("apply", "t") not in driver.calls and ("destroy", "t") not in driver.calls

    revision, calls = record.revision, list(driver.calls)
    asyncio.run(r.reconcile("t"))
    assert len(store.list_runs("t")) == 1 and store.get_twin("t").revision == revision and driver.calls == calls


def test_an_uncompilable_blueprint_is_rejected_with_its_findings(store: LocalStore) -> None:
    blueprint_id = file_blueprint(store, "testdata/compiler/rejected/network-empty.json")
    new_twin(store, blueprint_id)
    driver = FakeDriver()
    asyncio.run(make(store, driver).reconcile("t"))

    run = only_run(store)
    assert run.verdict is not None and run.verdict.status == "rejected"
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("network.empty", "network")]
    assert run.verdict.subject == Subject(twin="t", run_id=run.id, blueprint_id=blueprint_id)
    assert seen(store, run.id) == [("compile", "started", None), ("compile", "failed", None)]
    assert store.events(run.id)[-1].rule == "bundle.rejected"
    assert_cleaned_up(store.get_twin("t"), "bundle.rejected")
    assert driver.calls == []


def test_a_blueprint_not_in_the_store_is_rejected(store: LocalStore) -> None:
    new_twin(store, "f" * 64)
    asyncio.run(make(store, FakeDriver()).reconcile("t"))
    run = only_run(store)
    assert run.verdict is not None and run.verdict.status == "rejected"
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("blueprint.missing", "f" * 64)]
    assert_cleaned_up(store.get_twin("t"), "blueprint.missing")


def test_a_spec_naming_a_bundle_is_planned_with_no_compile(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store), "first")
    driver = FakeDriver()
    r = make(store, driver)
    asyncio.run(r.reconcile("first"))
    first = store.get_twin("first").status
    assert first.bundle_id is not None
    new_twin(store, None, "second", bundle_id=first.bundle_id)
    asyncio.run(r.reconcile("second"))

    second = store.get_twin("second")
    assert ready_of(second).status == "True"
    assert second.status.bundle_id == first.bundle_id and second.status.blueprint_id == first.blueprint_id
    assert second.status.allocation == {"lab": "second", "mgmt_subnet": "10.0.2.0/24"}  # first's is reserved
    assert seen(store, only_run(store, "second").id) == CREATE


def test_a_bundle_not_in_the_store_is_rejected(store: LocalStore) -> None:
    new_twin(store, None, bundle_id="b" * 64)
    asyncio.run(make(store, FakeDriver()).reconcile("t"))
    run = only_run(store)
    assert run.verdict is not None
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("bundle.missing", "b" * 64)]
    assert_cleaned_up(store.get_twin("t"), "bundle.missing")


class UnplannableDriver(FakeDriver):
    def plan(self, *args: object, **kwargs: object) -> Planned:
        self.calls.append(("plan", "t"))
        raise Unplannable([Finding(rule="interface.port.shared", severity="error", object="n1:ethernet-1/1",
                                   message="shared")])


def test_a_refused_plan_is_rejected_with_its_findings(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = UnplannableDriver()
    asyncio.run(make(store, driver).reconcile("t"))
    run = only_run(store)
    assert run.verdict is not None and run.verdict.status == "rejected"
    assert [f.rule for f in run.verdict.findings] == ["interface.port.shared"]
    assert seen(store, run.id)[-2:] == [("plan", "started", None), ("plan", "failed", None)]
    assert store.events(run.id)[-1].rule == "plan.rejected"
    assert_cleaned_up(store.get_twin("t"), "plan.rejected")
    assert ("destroy", "t") not in driver.calls


def test_a_silent_node_fails_the_create_and_cleans_up(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    pusher = fake_push(driver=driver)
    ready = fake_ready(answers={"n1", "n2"}, driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher).reconcile("t"))

    run = only_run(store)
    assert run.verdict is not None and run.verdict.status == "failed"
    (finding,) = run.verdict.findings
    assert (finding.rule, finding.object) == ("readiness.timeout", "n3") and "60s" in finding.message
    assert run.verdict.subject.deployment_id is not None
    assert seen(store, run.id) == UP_TO_APPLY + pairs("ready", ["n1", "n2"]) + [("ready", "started", "n3"),
                                                                                ("ready", "timed_out", "n3")]
    assert store.events(run.id)[-1].rule == "readiness.timeout"
    assert driver.calls[-1] == ("destroy", "t") and "t" not in driver.labs
    assert_cleaned_up(store.get_twin("t"), "readiness.timeout")
    assert pusher.calls == []


def test_a_refused_push_fails_the_create_and_cleans_up(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    asyncio.run(make(store, driver, pusher=fake_push(refuse={"n2"}, driver=driver)).reconcile("t"))

    run = only_run(store)
    assert run.verdict is not None and run.verdict.status == "failed"
    assert run.verdict.findings == (Finding(rule="push.refused", severity="error", object="n2",
                                            message="At line 1: n2 refused the configuration"),)
    assert seen(store, run.id) == [*CREATE[:-4], ("push", "started", "n2"), ("push", "failed", "n2")]
    assert store.events(run.id)[-1].rule == "push.refused"
    assert ("destroy", "t") in driver.calls and "t" not in driver.labs
    record = store.get_twin("t")
    assert_cleaned_up(record, "push.refused")
    assert not any(n.name == "n1" and n.holds for n in record.status.nodes)


def test_an_unauthorized_push_fails_the_create_and_cleans_up(store: LocalStore) -> None:
    class Refusing(FakePush):
        async def __call__(self, *args: object) -> push.Pushed | push.Refused:
            raise push.Unauthorized("https://10.0.1.1/jsonrpc answered HTTP 401: the node refused the login")

    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    asyncio.run(make(store, driver, pusher=Refusing(None, None, None, None)).reconcile("t"))
    run = only_run(store)
    assert run.verdict is not None
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("push.unauthorized", "n1")]
    assert ("destroy", "t") in driver.calls
    assert_cleaned_up(store.get_twin("t"), "push.unauthorized")


def test_a_missing_credential_fails_before_any_push(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher, environ={}).reconcile("t"))

    run = only_run(store)
    assert run.verdict is not None and run.verdict.status == "failed"
    (finding,) = run.verdict.findings
    assert (finding.rule, finding.object) == ("credential.missing", "n1")
    assert "FYLGJA_CREDENTIAL_SRLINUX_USERNAME" in finding.message
    assert seen(store, run.id) == [*UP_TO_APPLY, ("ready", "started", "n1"), ("ready", "failed", "n1")]
    assert store.events(run.id)[-1].rule == "credential.missing"
    assert ready.calls == [] and pusher.calls == []
    assert ("destroy", "t") in driver.calls
    assert_cleaned_up(store.get_twin("t"), "credential.missing")


def test_an_unreachable_push_is_transient(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    pusher = fake_push(unreachable={"n1"}, driver=driver)

    async def scenario() -> None:
        r = make(store, driver, pusher=pusher)
        await r.reconcile("t")
        record = store.get_twin("t")
        run = only_run(store)
        assert record.status.run_id == run.id and record.status.phase == "ready" and run.state == "running"
        assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.creating")
        assert record.status.observed_generation == 0 and record.status.deployment_id is not None
        assert seen(store, run.id) == [*CREATE[:-6], ("push", "started", "n1"), ("push", "failed", "n1")]
        assert store.events(run.id)[-1].rule == "push.unreachable"
        assert r.queue.waiting() == ["t"] and r.backoff == {"t": 1.0}
        assert ("destroy", "t") not in driver.calls

        await r.reconcile("t")
        record = store.get_twin("t")
        assert ready_of(record).status == "True" and record.status.run_id is None
        assert all(n.holds == record.status.bundle_id for n in record.status.nodes)
        assert [node for node, _ in pusher.calls] == ["n1", "n1", "n2", "n3"]
        assert seen(store, run.id)[-6:] == pairs("push", DEVICES)
        assert r.backoff == {}

    asyncio.run(scenario())


def test_a_failed_deploy_is_transient_and_the_next_pass_deploys(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver(fail_apply=True)

    async def scenario() -> None:
        r = make(store, driver)
        await r.reconcile("t")
        record, run = store.get_twin("t"), only_run(store)
        assert record.status.phase == "planned" and record.status.run_id == run.id and run.state == "running"
        assert seen(store, run.id) == [*UP_TO_APPLY[:-1], ("apply", "failed", None)]
        assert store.events(run.id)[-1].rule is None
        assert r.backoff == {"t": 1.0}
        await r.reconcile("t")
        assert r.backoff == {"t": 2.0}
        driver.fail_apply = False
        await r.reconcile("t")
        assert ready_of(store.get_twin("t")).status == "True" and r.backoff == {}

    asyncio.run(scenario())


def test_the_backoff_doubles_from_one_second_to_a_minute() -> None:
    delays = [reconcile.next_backoff(None)]
    for _ in range(8):
        delays.append(reconcile.next_backoff(delays[-1]))
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0]


def test_probe_hosts_are_skipped_in_the_ready_phase_and_never_pushed(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store, "testdata/blueprint/three-node-probed.json"))
    driver = FakeDriver()
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher).reconcile("t"))

    record = store.get_twin("t")
    assert ready_of(record).status == "True"
    hosts = ["n1-loop-a", "n1-loop-b"]
    assert [n.name for n in record.status.nodes] == sorted(DEVICES + hosts)
    assert all(n.holds is None for n in record.status.nodes if n.name in hosts)
    assert seen(store, only_run(store).id) == (UP_TO_APPLY + pairs("ready", DEVICES)
                                               + [("ready", "skipped", h) for h in hosts] + pairs("push", DEVICES))
    assert [node for node, _ in ready.calls] == DEVICES and [node for node, _ in pusher.calls] == DEVICES
    assert all(timeout == PLATFORMS["nokia_srlinux"].readiness.timeout_s for _, timeout in ready.calls)


def test_admission_reserves_every_other_twins_allocation_one_twin_at_a_time(store: LocalStore) -> None:
    blueprint_id = file_blueprint(store)
    for name in ("a", "b", "c"):
        new_twin(store, blueprint_id, name)
    driver = FakeDriver(refuse=Refusal("admission.capacity", "no room"))

    async def scenario() -> None:
        r = make(store, driver)
        await r.reconcile("c")  # refused: it records no allocation, and nothing reserves for it
        driver.refuse = None
        await asyncio.gather(r.reconcile("a"), r.reconcile("b"))

    asyncio.run(scenario())
    subnets = {name: store.get_twin(name).status.allocation for name in ("a", "b", "c")}
    assert subnets["c"] is None
    assert sorted(str(a["mgmt_subnet"]) for a in (subnets["a"], subnets["b"]) if a) == ["10.0.1.0/24", "10.0.2.0/24"]


def test_a_failed_cleanup_destroy_keeps_the_allocation_and_is_retried(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    driver.fail_destroy = True

    async def scenario() -> None:
        r = make(store, driver, pusher=fake_push(refuse={"n2"}, driver=driver))
        await r.reconcile("t")
        record, run = store.get_twin("t"), only_run(store)
        assert run.state == "ended" and run.verdict is not None and run.verdict.status == "failed"
        assert (ready_of(record).status, ready_of(record).reason) == ("False", "push.refused")
        assert record.status.observed_generation == 1
        assert record.status.allocation is not None and record.status.deployment_id is not None
        assert record.status.run_id == run.id  # the run whose cleanup is still owed
        assert "t" in driver.labs and r.queue.waiting() == ["t"] and r.backoff == {"t": 1.0}

        driver.fail_destroy = False
        await r.reconcile("t")
        assert_cleaned_up(store.get_twin("t"), "push.refused")
        assert "t" not in driver.labs and len(store.list_runs("t")) == 1 and r.backoff == {}
        assert driver.calls.count(("destroy", "t")) == 2

    asyncio.run(scenario())


def test_the_ready_condition_keeps_its_since_while_its_status_holds(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()

    async def scenario() -> tuple[Condition, Condition]:
        r = make(store, driver, pusher=fake_push(unreachable={"n1"}, driver=driver))
        await r.reconcile("t")
        creating = ready_of(store.get_twin("t"))
        await r.reconcile("t")
        return creating, ready_of(store.get_twin("t"))

    creating, done = asyncio.run(scenario())
    assert creating.status == "False" and done.status == "True"
    assert creating.since is not None and done.since is not None and done.since > creating.since
    (refused,) = reconcile.ready_condition((creating,), "False", "push.refused")
    assert (refused.reason, refused.since) == ("push.refused", creating.since)  # the status held: so does since


# Resumption (Task 5): a kill is an exception raised at a phase boundary, after the record was
# written; a fresh Reconciler over the same store, driver and lab is the restarted core.


class KillingStore(LocalStore):
    """A local store that kills the core once, right after writing a twin record whose phase is
    `kill_at`, or, for `kill_at == "ended"`, right after ending a run."""

    kill_at: str | None = None

    def update_twin(self, record: TwinRecord, expected_revision: int) -> TwinRecord:
        written = super().update_twin(record, expected_revision)
        if self.kill_at is not None and written.status.phase == self.kill_at:
            self.kill_at = None
            raise RuntimeError("killed")
        return written

    def update_run(self, run: Run, expected_state: RunState) -> None:
        super().update_run(run, expected_state)
        if self.kill_at == "ended" and run.state == "ended":
            self.kill_at = None
            raise RuntimeError("killed")


@pytest.fixture
def killing(tmp_path: Path) -> Iterator[KillingStore]:
    s = KillingStore.open(tmp_path / "store")
    assert isinstance(s, KillingStore)  # `open` makes the class it is called on
    yield s
    s.close()


def killed(r: Reconciler) -> None:
    with pytest.raises(RuntimeError, match="killed"):
        asyncio.run(r.reconcile("t"))


def resumed(store: LocalStore, run_id: str) -> list[Seen]:
    """The run's events, after checking it is still the twin's one run and its events have no gap."""
    assert [r.id for r in store.list_runs("t")] == [run_id]
    events = store.events(run_id)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    return seen(store, run_id)


def assert_ready_once_each(store: LocalStore, pusher: FakePush) -> TwinRecord:
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert record.status.observed_generation == 1 and record.status.run_id is None
    assert all(n.holds == record.status.bundle_id for n in record.status.nodes)
    run = only_run(store)
    assert run.state == "ended" and run.verdict is not None and run.verdict.status == "ok"
    assert sorted(node for node, _ in pusher.calls) == DEVICES
    return record


def test_killed_after_applied_a_resume_never_deploys_again_and_pushes_each_node_once(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "applied"
    killed(make(killing, driver))
    record, run = killing.get_twin("t"), only_run(killing)
    assert record.status.phase == "applied" and record.status.run_id == run.id and run.state == "running"

    before = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher).reconcile("t"))
    assert driver.calls[before:] == []  # no inspect, no apply: the record says applied
    assert_ready_once_each(killing, pusher)
    assert [node for node, _ in ready.calls] == DEVICES
    # The killed phase's end was never written; the resume continues the run with the next phase.
    assert resumed(killing, run.id) == [*UP_TO_APPLY[:-1], *pairs("ready", DEVICES), *pairs("push", DEVICES)]


def test_killed_after_the_deploy_and_before_applied_the_answering_lab_is_not_deployed_again(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    driver.fail_after = "apply"
    killed(make(store, driver))
    assert store.get_twin("t").status.phase == "planned" and "t" in driver.labs

    before = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher).reconcile("t"))
    assert driver.calls[before:] == [("inspect", "t"), ("inspect", "t")]  # probed, and every node answered
    record = assert_ready_once_each(store, pusher)
    assert {n.incarnation for n in record.status.nodes} == {"boot-1"}
    assert [node for node, _ in ready.calls] == DEVICES + DEVICES  # the probe, then the ready phase
    run = only_run(store)
    assert resumed(store, run.id) == [*UP_TO_APPLY[:-1], ("apply", "started", None), ("apply", "skipped", None),
                                      *pairs("ready", DEVICES), *pairs("push", DEVICES)]
    (skipped,) = [e for e in store.events(run.id) if e.outcome == "skipped"]
    assert skipped.duration_s is not None and skipped.duration_s >= 0


async def deploy_as_killed(store: LocalStore, driver: FakeDriver) -> None:
    """Deploy the twin's recorded deployment, as a deploy the kill interrupted would have."""
    deployment_id = store.get_twin("t").status.deployment_id
    assert deployment_id is not None
    deployment, files = store.get_deployment(deployment_id)
    await driver.apply(deployment, files, PLATFORMS, PROBES)


def silence(driver: FakeDriver, how: str) -> None:
    lab = driver.labs["t"]
    if how == "not answering":
        driver.silent.add(("t", "n3"))
    elif how == "stopped":
        lab["n3"] = dataclasses.replace(lab["n3"], running=False, address=None)
    elif how == "every node stopped":
        for name in list(lab):
            lab[name] = dataclasses.replace(lab[name], running=False, address=None)
    elif how == "without an address":
        lab["n3"] = dataclasses.replace(lab["n3"], address=None)
    else:
        assert how == "missing"
        del lab["n3"]


@pytest.mark.parametrize("how", ["not answering", "stopped", "every node stopped", "without an address", "missing"])
def test_killed_after_planned_with_a_silent_node_in_the_lab_a_resume_reconfigures(
    killing: KillingStore, how: str
) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "planned"
    killed(make(killing, driver))
    asyncio.run(deploy_as_killed(killing, driver))
    silence(driver, how)

    before = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher).reconcile("t"))
    assert driver.calls[before:] == [("inspect", "t"), ("apply", "t", "reconfigure"), ("inspect", "t")]
    record = assert_ready_once_each(killing, pusher)
    assert {n.incarnation for n in record.status.nodes} == {"boot-2"}  # every node made anew
    probed = {"not answering": DEVICES}.get(how, [])  # a node with no running address is silent without a call
    assert [node for node, _ in ready.calls] == probed + DEVICES
    # Killed after planned was written and before its end: the resume goes on with apply.
    assert resumed(killing, only_run(killing).id) == [*UP_TO_APPLY[:5], *UP_TO_APPLY[6:], *pairs("ready", DEVICES),
                                                      *pairs("push", DEVICES)]


@pytest.mark.parametrize("left", ["absent", "residue"])
def test_killed_after_planned_with_no_lab_a_resume_deploys_plainly(killing: KillingStore, left: str) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "planned"
    killed(make(killing, driver))
    if left == "residue":
        driver.residue.add("t")  # the lab removed by hand, its leftovers not

    before = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher).reconcile("t"))
    assert driver.calls[before:] == [("inspect", "t"), ("apply", "t"), ("inspect", "t")]
    assert "t" not in driver.residue
    assert_ready_once_each(killing, pusher)
    assert [node for node, _ in ready.calls] == DEVICES


def test_killed_after_two_pushes_a_resume_pushes_only_the_third(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    killed(make(store, driver, pusher=fake_push(kill_after=2, driver=driver)))
    record, run = store.get_twin("t"), only_run(store)
    assert record.status.phase == "ready"
    assert [(n.name, n.holds == record.status.bundle_id) for n in record.status.nodes] == [
        ("n1", True), ("n2", True), ("n3", False)]

    before = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher).reconcile("t"))
    assert [node for node, _ in pusher.calls] == ["n3"] and ready.calls == [] and driver.calls[before:] == []
    record = store.get_twin("t")
    assert ready_of(record).status == "True" and all(n.holds == record.status.bundle_id for n in record.status.nodes)
    assert resumed(store, run.id) == [*CREATE[:-2], ("push", "started", "n3"), *pairs("push", ["n3"])]


def test_killed_after_admitted_a_resume_plans_with_the_recorded_allocation(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "admitted"
    killed(make(killing, driver))
    status = killing.get_twin("t").status
    assert status.phase == "admitted" and status.allocation == {"lab": "t", "mgmt_subnet": "10.0.1.0/24"}
    assert status.bundle_id is not None

    driver.refuse = Refusal("admission.capacity", "a second admission would be refused")
    before = len(driver.calls)
    asyncio.run(make(killing, driver).reconcile("t"))
    assert driver.calls[before:] == [("plan", "t"), ("inspect", "t"), ("apply", "t"), ("inspect", "t")]
    record = killing.get_twin("t")
    assert ready_of(record).status == "True" and record.status.allocation == status.allocation
    manifest = bundle.decode(json.loads(killing.get_bundle(status.bundle_id)["manifest.json"]))
    expected = driver.plan(manifest, status.bundle_id, PLATFORMS, PROBES, "t", status.allocation)
    assert record.status.deployment_id == expected.deployment.id
    assert resumed(killing, only_run(killing).id) == [*UP_TO_APPLY[:3], *UP_TO_APPLY[4:], *pairs("ready", DEVICES),
                                                      *pairs("push", DEVICES)]


def test_killed_after_the_run_ended_ok_the_next_pass_completes_the_record(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "ended"
    killed(make(killing, driver))
    record, run = killing.get_twin("t"), only_run(killing)
    assert run.state == "ended" and record.status.run_id == run.id and record.status.observed_generation == 0

    before, events = len(driver.calls), len(killing.events(run.id))
    asyncio.run(make(killing, driver).reconcile("t"))
    record = killing.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert record.status.observed_generation == 1 and record.status.run_id is None and record.status.phase == "pushed"
    assert driver.calls[before:] == [] and len(killing.events(run.id)) == events and only_run(killing).id == run.id


def test_killed_after_a_failed_run_ended_the_next_pass_cleans_up(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "ended"
    killed(make(killing, driver, pusher=fake_push(refuse={"n2"}, driver=driver)))
    assert "t" in driver.labs and killing.get_twin("t").status.deployment_id is not None

    asyncio.run(make(killing, driver).reconcile("t"))
    assert_cleaned_up(killing.get_twin("t"), "push.refused")  # the reason read back from the failing event
    assert "t" not in driver.labs and driver.calls[-1] == ("destroy", "t") and len(killing.list_runs("t")) == 1


def test_a_record_naming_a_queued_run_marks_it_running_and_runs_it(store: LocalStore) -> None:
    # A core killed after the record named its new run and before marking it running.
    new_twin(store, file_blueprint(store))
    run = queued("t", "create", "core")
    store.create_run(run)
    record = store.get_twin("t")
    store.update_twin(dataclasses.replace(record, status=dataclasses.replace(record.status, run_id=run.id)),
                      record.revision)
    asyncio.run(make(store, FakeDriver()).reconcile("t"))
    assert only_run(store).id == run.id and ready_of(store.get_twin("t")).status == "True"
    assert seen(store, run.id) == CREATE


# Deletion, cancellation, the dry run, start and resync (Task 6).


def request_deletion(store: LocalStore, name: str = "t", *, mark: bool = True, principal: str = "bob") -> Run:
    """What the API's DELETE does (plan 6): `deletion_requested_at` set and `generation` bumped,
    a run in flight marked cancelling (unless `mark` is False), and a destroy run queued."""
    record = store.get_twin(name)
    store.update_twin(dataclasses.replace(record, deletion_requested_at=clock.now(), generation=record.generation + 1),
                      record.revision)
    for run in store.list_runs(name):
        if mark and run.state in ("queued", "running"):
            store.update_run(dataclasses.replace(run, state="cancelling"), run.state)
    destroy = queued(name, "destroy", principal)
    store.create_run(destroy)
    return destroy


def mark_cancelling(store: LocalStore, run_id: str) -> None:
    """What the API's cancel does (plan 6)."""
    run = store.get_run(run_id)
    store.update_run(dataclasses.replace(run, state="cancelling"), run.state)


def the_run(store: LocalStore, operation: str, twin: str = "t") -> Run:
    (run,) = [r for r in store.list_runs(twin) if r.operation == operation]
    return run


def assert_cancelled(run: Run) -> None:
    assert run.state == "ended" and run.verdict is not None and run.verdict.status == "failed"
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("run.cancelled", run.twin)]


async def until(condition: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "the condition never held"
        await asyncio.sleep(0.01)


def is_ready(store: LocalStore, name: str) -> bool:
    try:
        record = store.get_twin(name)
    except NotFound:
        return False
    return record.status.observed_generation == record.generation and ready_of(record).status == "True"


def test_deleting_a_ready_twin_destroys_it_and_deletes_its_record(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()

    async def scenario() -> tuple[list[Change], str | None]:
        r = make(store, driver)
        await r.reconcile("t")
        deployment_id = store.get_twin("t").status.deployment_id
        with store.subscribe() as watch:
            request_deletion(store)
            await r.reconcile("t")
            await asyncio.sleep(0)  # a change is delivered through the loop
            changes = []
            while not watch.queue.empty():
                changes.append(watch.queue.get_nowait())
        return changes, deployment_id

    changes, deployment_id = asyncio.run(scenario())
    with pytest.raises(NotFound):
        store.get_twin("t")
    assert driver.calls.count(("destroy", "t")) == 1 and "t" not in driver.labs
    destroy = the_run(store, "destroy")
    assert destroy.state == "ended" and destroy.principal == "bob"
    assert destroy.verdict is not None and destroy.verdict.status == "ok" and destroy.verdict.operation == "destroy"
    assert destroy.verdict.subject.twin == "t" and destroy.verdict.subject.run_id == destroy.id
    assert deployment_id is not None and destroy.verdict.subject.deployment_id == deployment_id  # what it tore down
    assert seen(store, destroy.id) == [("destroy", "started", None), ("destroy", "done", None)]
    create = the_run(store, "create")
    assert create.verdict is not None and create.verdict.status == "ok"  # the create had ended: nothing cancelled
    assert [c.type for c in changes][-1] == "DELETED"
    deleting = [c.record for c in changes if c.type == "MODIFIED" and ready_of(c.record).reason == "twin.deleting"]
    assert deleting and deleting[0].status.run_id == destroy.id
    assert changes[-1].record.status.phase == "destroyed" and changes[-1].record.status.deployment_id is None


def test_deleting_a_twin_whose_admission_was_refused_destroys_nothing(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver(refuse=Refusal("admission.capacity", "no room"))
    r = make(store, driver)
    asyncio.run(r.reconcile("t"))
    request_deletion(store)
    asyncio.run(r.reconcile("t"))
    with pytest.raises(NotFound):
        store.get_twin("t")
    assert ("destroy", "t") not in driver.calls
    destroy = the_run(store, "destroy")
    assert destroy.verdict is not None and destroy.verdict.status == "ok"
    assert seen(store, destroy.id) == [("destroy", "started", None), ("destroy", "done", None)]


def test_a_deletion_with_no_destroy_run_queued_runs_one_of_the_cores(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    r = make(store, driver)
    asyncio.run(r.reconcile("t"))
    record = store.get_twin("t")
    store.update_twin(dataclasses.replace(record, deletion_requested_at=clock.now(), generation=2), record.revision)
    asyncio.run(r.reconcile("t"))
    with pytest.raises(NotFound):
        store.get_twin("t")
    destroy = the_run(store, "destroy")
    assert destroy.principal == "core" and destroy.verdict is not None and destroy.verdict.status == "ok"


def test_a_failed_teardown_is_transient_and_the_next_pass_completes_it(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()

    async def scenario() -> None:
        r = make(store, driver)
        await r.reconcile("t")
        destroy = request_deletion(store)
        driver.fail_destroy = True
        await r.reconcile("t")
        record = store.get_twin("t")
        assert record.status.run_id == destroy.id and store.get_run(destroy.id).state == "running"
        assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.deleting")
        assert record.status.deployment_id is not None and r.backoff == {"t": 1.0}
        assert seen(store, destroy.id) == [("destroy", "started", None), ("destroy", "failed", None)]
        driver.fail_destroy = False
        await r.reconcile("t")
        with pytest.raises(NotFound):
            store.get_twin("t")
        assert seen(store, destroy.id)[-2:] == [("destroy", "started", None), ("destroy", "done", None)]
        assert len(store.list_runs("t")) == 2 and r.backoff == {}

    asyncio.run(scenario())


def test_killed_after_destroyed_a_resume_deletes_the_record_without_a_second_destroy(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    asyncio.run(make(killing, driver).reconcile("t"))
    destroy = request_deletion(killing)
    killing.kill_at = "destroyed"
    killed(make(killing, driver))
    assert killing.get_twin("t").status.phase == "destroyed"
    asyncio.run(make(killing, driver).reconcile("t"))
    with pytest.raises(NotFound):
        killing.get_twin("t")
    assert driver.calls.count(("destroy", "t")) == 1
    assert killing.get_run(destroy.id).verdict is not None
    assert seen(killing, destroy.id) == [("destroy", "started", None)]  # the kill came before its end


def test_killed_after_the_destroy_run_ended_the_next_pass_deletes_the_record(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    asyncio.run(make(killing, driver).reconcile("t"))
    destroy = request_deletion(killing)
    killing.kill_at = "ended"
    killed(make(killing, driver))
    assert killing.get_run(destroy.id).state == "ended" and killing.get_twin("t").status.run_id == destroy.id
    asyncio.run(make(killing, driver).reconcile("t"))
    with pytest.raises(NotFound):
        killing.get_twin("t")
    assert driver.calls.count(("destroy", "t")) == 1 and len(killing.list_runs("t")) == 2


class CancellingPush(FakePush):
    """A push that marks the twin's create run cancelling once it has pushed `after` nodes, or
    asks for the twin's deletion then, as a client would meanwhile."""

    def __init__(self, store: LocalStore, driver: FakeDriver, *, after: int = 1, delete: bool = False) -> None:
        super().__init__(None, None, None, driver)
        self.store, self.after, self.delete = store, after, delete

    async def __call__(
        self, address: str, package: platform_package.PlatformPackage, config: str, credential: Credential
    ) -> push.Pushed | push.Refused:
        answer = await super().__call__(address, package, config, credential)
        if len(self.calls) == self.after:
            if self.delete:
                request_deletion(self.store)
            else:
                mark_cancelling(self.store, the_run(self.store, "create").id)
        return answer


def test_a_cancelled_create_stops_cleans_up_and_ends_cancelled(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    pusher = CancellingPush(store, driver)
    asyncio.run(make(store, driver, pusher=pusher).reconcile("t"))

    run = only_run(store)
    assert_cancelled(run)
    assert run.verdict is not None and run.verdict.findings[0].message.endswith("was torn down.")
    assert [node for node, _ in pusher.calls] == ["n1"]
    assert seen(store, run.id) == [*CREATE[:-4], ("cancel", "started", None), ("cancel", "done", None)]
    assert store.events(run.id)[-1].rule == "run.cancelled"
    assert driver.calls[-1] == ("destroy", "t") and "t" not in driver.labs
    assert_cleaned_up(store.get_twin("t"), "run.cancelled")


def test_a_cancel_stops_a_call_the_runtime_never_answers(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    driver.block = "apply"

    async def scenario() -> None:
        r = make(store, driver)
        pass_ = asyncio.create_task(r.reconcile("t"))
        await until(lambda: ("apply", "t") in driver.calls)
        mark_cancelling(store, only_run(store).id)
        await asyncio.wait_for(pass_, timeout=5)

    asyncio.run(scenario())
    run = only_run(store)
    assert_cancelled(run)
    assert seen(store, run.id) == [*UP_TO_APPLY[:-1], ("apply", "cancelled", None), ("cancel", "started", None),
                                   ("cancel", "done", None)]
    assert driver.calls[-1] == ("destroy", "t")
    assert_cleaned_up(store.get_twin("t"), "run.cancelled")


def test_a_run_cancelled_before_it_started_ends_cancelled_having_done_nothing(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    asked = queued("t", "create", "alice")
    store.create_run(asked)
    mark_cancelling(store, asked.id)
    driver = FakeDriver()
    asyncio.run(make(store, driver).reconcile("t"))
    run = only_run(store)
    assert run.id == asked.id
    assert_cancelled(run)
    assert run.verdict is not None and "before it had built anything" in run.verdict.findings[0].message
    assert seen(store, run.id) == [("cancel", "started", None), ("cancel", "done", None)]
    assert driver.calls == []
    assert_cleaned_up(store.get_twin("t"), "run.cancelled")


def test_a_create_whose_run_is_cancelled_while_it_ends_is_cancelled(store: LocalStore) -> None:
    # The API marks the run cancelling between the last push and the run's end: the loop decides again.
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    pusher = CancellingPush(store, driver, after=3)
    asyncio.run(make(store, driver, pusher=pusher).reconcile("t"))
    run = only_run(store)
    assert_cancelled(run)
    assert seen(store, run.id) == [*CREATE, ("cancel", "started", None), ("cancel", "done", None)]
    assert_cleaned_up(store.get_twin("t"), "run.cancelled")
    assert "t" not in driver.labs


def test_a_deletion_during_a_create_cancels_it_then_tears_the_twin_down(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    pusher = CancellingPush(store, driver, delete=True)

    async def scenario() -> None:
        r = make(store, driver, pusher=pusher)
        await r.reconcile("t")  # the create, cancelled by the deletion's mark
        create = the_run(store, "create")
        assert_cancelled(create)
        # The deletion's write mid-pass did not fail the push: the loop's status was written over it.
        assert seen(store, create.id) == [*CREATE[:-4], ("cancel", "started", None), ("cancel", "done", None)]
        record = store.get_twin("t")
        assert record.status.deployment_id is None
        # The generation is the deletion's, which the destroy run has yet to act on.
        assert record.deletion_requested_at is not None
        assert record.status.observed_generation < record.generation
        await r.reconcile("t")  # the kick the deletion queued

    asyncio.run(scenario())
    with pytest.raises(NotFound):
        store.get_twin("t")
    destroy = the_run(store, "destroy")
    assert destroy.verdict is not None and destroy.verdict.status == "ok"
    assert driver.calls.count(("destroy", "t")) == 1 and "t" not in driver.labs  # the create's cleanup tore it down


def test_a_deletion_finding_a_create_left_running_cancels_it_first(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "applied"
    killed(make(killing, driver))  # a core that stopped mid-create
    create = the_run(killing, "create")
    stray = queued("t", "create", "alice")  # and a create run that never started
    killing.create_run(stray)
    destroy = request_deletion(killing, mark=False)
    asyncio.run(make(killing, driver).reconcile("t"))
    with pytest.raises(NotFound):
        killing.get_twin("t")
    assert_cancelled(killing.get_run(create.id))
    assert seen(killing, create.id)[-2:] == [("cancel", "started", None), ("cancel", "done", None)]
    assert_cancelled(killing.get_run(stray.id))
    assert seen(killing, stray.id) == [("cancel", "started", None), ("cancel", "done", None)]
    verdict = killing.get_run(destroy.id).verdict
    assert verdict is not None and verdict.status == "ok"
    assert driver.calls.count(("destroy", "t")) == 1 and "t" not in driver.labs


def test_a_cancel_after_a_transient_failure_is_read_back_as_cancelled(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    asyncio.run(make(killing, driver, pusher=fake_push(unreachable={"n1"}, driver=driver)).reconcile("t"))
    run = only_run(killing)
    assert killing.events(run.id)[-1].rule == "push.unreachable"
    mark_cancelling(killing, run.id)
    killing.kill_at = "ended"
    killed(make(killing, driver))  # stopped between the run's end and the record's last write
    asyncio.run(make(killing, driver).reconcile("t"))
    assert_cleaned_up(killing.get_twin("t"), "run.cancelled")  # not push.unreachable
    assert killing.events(run.id)[-1].rule == "run.cancelled"


def test_a_node_refusing_the_login_in_the_partial_lab_probe_fails_at_once(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "planned"
    killed(make(killing, driver))
    asyncio.run(deploy_as_killed(killing, driver))

    before = len(driver.calls)
    ready = fake_ready(refuse_login={"n2"}, driver=driver)
    asyncio.run(make(killing, driver, ready=ready).reconcile("t"))
    assert driver.calls[before:] == [("inspect", "t"), ("destroy", "t")]  # no reconfigure: it would not help
    run = only_run(killing)
    assert run.verdict is not None and [(f.rule, f.object) for f in run.verdict.findings] == [
        ("readiness.unauthorized", "n2")]
    assert seen(killing, run.id)[-2:] == [("apply", "started", None), ("apply", "failed", None)]
    assert killing.events(run.id)[-1].rule == "readiness.unauthorized"
    assert_cleaned_up(killing.get_twin("t"), "readiness.unauthorized")


def test_a_driver_this_core_does_not_serve_rejects_the_run_and_raises_nothing(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store), driver="elsewhere")
    asked = queued("t", "create", "alice")
    store.create_run(asked)
    driver = FakeDriver()
    r = make(store, driver)
    asyncio.run(r.reconcile("t"))
    run = only_run(store)
    assert run.id == asked.id and run.state == "ended" and run.verdict is not None
    assert run.verdict.status == "rejected"
    (finding,) = run.verdict.findings
    assert (finding.rule, finding.object) == ("twin.driver.unknown", "t") and "'elsewhere'" in finding.message
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.driver.unknown")
    assert record.status.observed_generation == 1 and record.status.run_id is None
    assert driver.calls == []
    asyncio.run(r.reconcile("t"))
    assert store.get_twin("t").revision == record.revision and len(store.list_runs("t")) == 1


def test_a_driver_this_core_does_not_serve_with_no_run_queued_makes_none(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store), driver="elsewhere")
    asyncio.run(make(store, FakeDriver()).reconcile("t"))
    assert store.list_runs("t") == []
    assert ready_of(store.get_twin("t")).reason == "twin.driver.unknown"


def spec_of(blueprint_id: str, driver: str = "fake") -> Spec:
    return Spec(blueprint_id=blueprint_id, driver=driver, allow_restart=False)


def test_a_dry_run_plans_against_the_live_reservations_and_writes_nothing(store: LocalStore) -> None:
    blueprint_id = file_blueprint(store)
    new_twin(store, blueprint_id, "held")
    driver = FakeDriver()
    r = make(store, driver)
    asyncio.run(r.reconcile("held"))  # holds 10.0.1.0/24
    root = store.root

    def contents() -> dict[Path, str]:
        return {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}

    before = contents()
    revision = store.get_twin("held").revision

    planned, verdict = asyncio.run(r.dry_run("t", spec_of(blueprint_id)))
    assert planned is not None and planned.twin == "t"
    assert planned.allocation == {"lab": "t", "mgmt_subnet": "10.0.2.0/24"}
    assert deployment.validate(documents.encode(planned)) == []
    assert verdict.operation == "plan" and verdict.status == "ok" and verdict.findings == ()
    assert verdict.subject == Subject(twin="t", blueprint_id=blueprint_id, bundle_id=planned.bundle_id,
                                      deployment_id=planned.id)
    assert contents() == before  # no record, run, bundle or deployment written, and none changed
    assert store.get_twin("held").revision == revision


def test_a_dry_run_a_driver_refuses_is_rejected(store: LocalStore) -> None:
    blueprint_id = file_blueprint(store)
    r = make(store, FakeDriver(refuse=Refusal("admission.capacity", "no room")))
    planned, verdict = asyncio.run(r.dry_run("t", spec_of(blueprint_id)))
    assert planned is None and verdict.operation == "plan" and verdict.status == "rejected"
    assert verdict.findings == (Finding(rule="admission.capacity", severity="error", object="t", message="no room"),)
    unserved, verdict = asyncio.run(r.dry_run("t", spec_of(blueprint_id, driver="elsewhere")))
    assert unserved is None and [f.rule for f in verdict.findings] == ["twin.driver.unknown"]


def test_a_dry_run_raises_what_the_api_answers_422(store: LocalStore) -> None:
    rejected = file_blueprint(store, "testdata/compiler/rejected/network-empty.json")
    with pytest.raises(compiler.Uncompilable):
        asyncio.run(make(store, FakeDriver()).dry_run("t", spec_of(rejected)))
    with pytest.raises(Unplannable):
        asyncio.run(make(store, UnplannableDriver()).dry_run("t", spec_of(file_blueprint(store))))
    with pytest.raises(NotFound):
        asyncio.run(make(store, FakeDriver()).dry_run("t", spec_of("f" * 64)))


def test_start_serves_every_twin_kick_serves_one_and_stop_ends_cleanly(store: LocalStore) -> None:
    blueprint_id = file_blueprint(store)
    for name in ("a", "b"):
        new_twin(store, blueprint_id, name)
    driver = FakeDriver()

    async def scenario() -> None:
        r = make(store, driver, workers=2)
        await r.start()
        await until(lambda: is_ready(store, "a") and is_ready(store, "b"))
        new_twin(store, blueprint_id, "c")
        r.kick("c")
        await until(lambda: is_ready(store, "c"))
        request_deletion(store, "a")
        r.kick("a")
        await until(lambda: "a" not in [t.name for t in store.list_twins()])
        await r.stop()
        await r.stop()  # stopping twice is harmless
        assert {t for t in asyncio.all_tasks() if not t.done()} == {asyncio.current_task()}

    asyncio.run(scenario())
    assert [t.name for t in store.list_twins()] == ["b", "c"]


def test_the_resync_serves_a_twin_nothing_kicked(store: LocalStore) -> None:
    blueprint_id = file_blueprint(store)
    driver = FakeDriver()

    async def scenario() -> None:
        r = make(store, driver, resync_s=0.05)
        await r.start()
        new_twin(store, blueprint_id)
        await until(lambda: is_ready(store, "t"))
        await r.stop()

    asyncio.run(scenario())


# No credential in any line (Task 7, Constitution X).

PASSWORD = "s3cret-never-logged"


@contextlib.contextmanager
def json_logs(level: int = logging.DEBUG) -> Iterator[io.StringIO]:
    """The core's JSON logging into a buffer for the test's body, and the root logger and the HTTP
    clients' levels as they were afterwards."""
    root = logging.getLogger()
    saved, was = root.handlers[:], root.level
    quieted = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    out = io.StringIO()
    logs.configure(level=level, stream=out)
    try:
        yield out
    finally:
        root.handlers[:] = saved
        root.setLevel(was)
        for name, level_was in quieted.items():
            logging.getLogger(name).setLevel(level_was)


def test_no_credential_reaches_a_log_line_or_the_store(store: LocalStore) -> None:
    blueprint_id = file_blueprint(store)
    for name in ("refused", "silent"):
        new_twin(store, blueprint_id, name)
    environ = {**ENVIRON, "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": PASSWORD}
    driver = FakeDriver()
    with json_logs() as out:
        refusing = make(store, driver, pusher=fake_push(refuse={"n2"}, driver=driver), environ=environ)
        asyncio.run(refusing.reconcile("refused"))
        timing_out = make(store, driver, ready=fake_ready(answers={"n1", "n2"}, driver=driver), environ=environ)
        asyncio.run(timing_out.reconcile("silent"))

    verdicts = {r.twin: r.verdict for r in store.list_runs()}
    assert [(t, v.findings[0].rule) for t, v in sorted(verdicts.items()) if v is not None] == [
        ("refused", "push.refused"), ("silent", "readiness.timeout")]
    text = out.getvalue()
    assert PASSWORD not in text
    lines = [json.loads(line) for line in text.splitlines()]
    assert lines and all({"time", "level", "logger", "message"} <= set(line) for line in lines)
    assert any(line["logger"] == "fylgja.credentials" for line in lines)  # the provider logged, by variable name
    run_of = {r.twin: r.id for r in store.list_runs()}
    loop = [line for line in lines if line["logger"] in ("fylgja.reconcile", "fylgja.audit")]
    assert loop and all(line.get("twin") in run_of and line.get("run") == run_of[line["twin"]] for line in loop)
    assert all(PASSWORD.encode() not in path.read_bytes() for path in store.root.rglob("*") if path.is_file())


# The final review's fixes.


def test_a_create_cancelled_as_it_ends_never_ends_ok_when_its_cleanup_must_wait(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    driver.fail_destroy = True
    pusher = CancellingPush(store, driver, after=3)  # cancelled between `pushed` and the run's end

    async def scenario() -> None:
        r = make(store, driver, pusher=pusher)
        await r.reconcile("t")  # the cancel path's teardown fails: transient
        run, record = only_run(store), store.get_twin("t")
        assert run.state == "cancelling" and record.status.phase == "pushed" and record.status.run_id == run.id
        driver.fail_destroy = False
        await r.reconcile("t")  # nothing is left to run, and the run is still cancelling

    asyncio.run(scenario())
    run = only_run(store)
    assert_cancelled(run)
    assert seen(store, run.id) == [*CREATE, ("cancel", "started", None), ("cancel", "failed", None),
                                   ("cancel", "started", None), ("cancel", "done", None)]
    assert_cleaned_up(store.get_twin("t"), "run.cancelled")
    assert "t" not in driver.labs


def test_start_twice_is_refused_and_a_stopped_reconciler_starts_on_another_loop(
    store: LocalStore, caplog: pytest.LogCaptureFixture
) -> None:
    blueprint_id = file_blueprint(store)
    new_twin(store, blueprint_id, "a")
    driver = FakeDriver()
    r = make(store, driver)
    with pytest.raises(RuntimeError, match="before start"):
        r.kick("a")  # before start, and with no loop running

    async def first() -> None:
        await r.start()
        with pytest.raises(RuntimeError):
            await r.start()
        await until(lambda: is_ready(store, "a"))
        await r.stop()

    async def second() -> None:
        await r.start()  # its workers wait on a queue of this loop, not the first's
        await until(lambda: is_ready(store, "b"))
        new_twin(store, blueprint_id, "c")
        await asyncio.to_thread(r.kick, "c")  # a client's write, from another thread
        await until(lambda: is_ready(store, "c"))
        await r.stop()

    asyncio.run(first())
    with pytest.raises(RuntimeError, match="after stop"):
        r.kick("a")
    new_twin(store, blueprint_id, "b")
    asyncio.run(second())
    # No worker failed to take a name: the queue it waits on is its own loop's.
    assert [r.getMessage() for r in caplog.records if r.name == "fylgja.queue"] == []


class FlakyStore(LocalStore):
    """A local store whose next `get_twin` fails, as a disk would."""

    fail_get = False

    def get_twin(self, name: str) -> TwinRecord:
        if self.fail_get:
            self.fail_get = False
            raise OSError("the disk is gone")
        return super().get_twin(name)


def test_a_transient_failure_outside_a_run_logs_no_run(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    s = FlakyStore.open(tmp_path / "store")
    assert isinstance(s, FlakyStore)
    try:
        new_twin(s, file_blueprint(s))
        s.fail_get = True
        r = make(s, FakeDriver())
        asyncio.run(r.reconcile("t"))
    finally:
        s.close()
    (line,) = [record for record in caplog.records if record.name == "fylgja.reconcile"]
    assert getattr(line, "fields", None) == {"twin": "t", "error": "OSError", "retry_s": 1.0}
    assert r.backoff == {"t": 1.0}


def test_a_resume_on_a_core_without_a_package_the_bundle_names_is_rejected(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing, "testdata/blueprint/lossy.json"))
    driver = FakeDriver()
    killing.kill_at = "admitted"
    killed(make(killing, driver))
    run = only_run(killing)

    lacking = {k: v for k, v in PLATFORMS.items() if k != "chassisos"}
    without = Reconciler(killing, {driver.name: driver}, lacking, PROBES, Provider(ENVIRON),
                         pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver))
    before = len(driver.calls)
    asyncio.run(without.reconcile("t"))  # raises nothing: no KeyError
    run = killing.get_run(run.id)
    assert run.state == "ended" and run.verdict is not None and run.verdict.status == "rejected"
    (finding,) = run.verdict.findings
    assert (finding.rule, finding.object) == ("platform.unsupported", "chassisos") and "c1, c2" in finding.message
    assert seen(killing, run.id)[-2:] == [("plan", "started", None), ("plan", "failed", None)]
    assert killing.events(run.id)[-1].rule == "bundle.rejected"
    assert driver.calls[before:] == []
    assert_cleaned_up(killing.get_twin("t"), "bundle.rejected")


def test_a_deployment_a_core_lacks_the_packages_for_is_kept_not_torn_down(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing, "testdata/blueprint/lossy.json"))
    driver = FakeDriver()
    killing.kill_at = "applied"
    killed(make(killing, driver))
    deployment_id = killing.get_twin("t").status.deployment_id
    without = {k: v for k, v in PLATFORMS.items() if k != "chassisos"}

    def lacking() -> Reconciler:
        return Reconciler(killing, {driver.name: driver}, without, PROBES, Provider(ENVIRON),
                          pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver))

    asyncio.run(lacking().reconcile("t"))  # the ready phase needs the package: rejected, and no teardown
    run = only_run(killing)
    assert run.verdict is not None and run.verdict.status == "rejected"
    assert seen(killing, run.id)[-1] == ("ready", "failed", None)
    record = killing.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "bundle.rejected")
    assert record.status.deployment_id == deployment_id and record.status.allocation is not None  # kept, reserved
    assert record.status.run_id is None and record.status.observed_generation == 1
    assert ("destroy", "t") not in driver.calls and "t" in driver.labs

    destroy = request_deletion(killing)
    asyncio.run(lacking().reconcile("t"))  # nor can it be deleted here: refused, and the record stays
    verdict = killing.get_run(destroy.id).verdict
    assert verdict is not None and verdict.status == "rejected"
    assert [f.object for f in verdict.findings] == ["chassisos"]
    revision = killing.get_twin("t").revision
    asyncio.run(lacking().reconcile("t"))  # said once: no new run, no write
    assert killing.get_twin("t").revision == revision and len(killing.list_runs("t")) == 2

    asyncio.run(make(killing, driver).reconcile("t"))  # a core with the package tears it down
    with pytest.raises(NotFound):
        killing.get_twin("t")
    assert "t" not in driver.labs and driver.calls.count(("destroy", "t")) == 1


class LosingStore(LocalStore):
    """A local store whose next update of the run `lose` loses its compare-and-set, as one the API
    wrote meanwhile would."""

    lose: str | None = None

    def update_run(self, run: Run, expected_state: RunState) -> None:
        if run.id == self.lose:
            self.lose = None
            raise Conflict(f"run {run.id} moved")
        super().update_run(run, expected_state)


def test_an_unstarted_run_whose_end_is_lost_is_ended_once_with_one_pair_of_events(tmp_path: Path) -> None:
    s = LosingStore.open(tmp_path / "store")
    assert isinstance(s, LosingStore)
    try:
        new_twin(s, file_blueprint(s))
        driver = FakeDriver()
        r = make(s, driver)
        asyncio.run(r.reconcile("t"))
        stray = queued("t", "create", "alice")
        s.create_run(stray)
        request_deletion(s, mark=False)
        s.lose = stray.id
        asyncio.run(r.reconcile("t"))  # the stray's end is lost: transient
        assert s.events(stray.id) == [] and s.get_run(stray.id).state == "queued" and r.backoff == {"t": 1.0}
        asyncio.run(r.reconcile("t"))
        assert_cancelled(s.get_run(stray.id))
        assert seen(s, stray.id) == [("cancel", "started", None), ("cancel", "done", None)]
        with pytest.raises(NotFound):
            s.get_twin("t")
    finally:
        s.close()


def kept_without_chassisos(killing: KillingStore, driver: FakeDriver) -> Callable[[], Reconciler]:
    """`lossy` killed after `applied`, then resumed by a core without `chassisos`: the run rejected,
    and the deployment kept. Answers the maker of such a core."""
    new_twin(killing, file_blueprint(killing, "testdata/blueprint/lossy.json"))
    killing.kill_at = "applied"
    killed(make(killing, driver))
    lacking = {k: v for k, v in PLATFORMS.items() if k != "chassisos"}

    def without() -> Reconciler:
        return Reconciler(killing, {driver.name: driver}, lacking, PROBES, Provider(ENVIRON),
                          pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver))

    asyncio.run(without().reconcile("t"))
    assert killing.get_twin("t").status.deployment_id is not None
    return without


def test_a_new_spec_over_a_kept_deployment_starts_no_create(killing: KillingStore) -> None:
    driver = FakeDriver()
    without = kept_without_chassisos(killing, driver)
    kept = killing.get_twin("t").status
    three_node = file_blueprint(killing)
    record = killing.get_twin("t")  # a client's PUT: a new spec, and its queued create run
    killing.update_twin(dataclasses.replace(record, generation=2, spec=dataclasses.replace(
        record.spec, blueprint_id=three_node)), record.revision)
    asked = queued("t", "create", "alice")
    killing.create_run(asked)
    driver.refuse = Refusal("admission.capacity", "no room")  # had admission run, its cleanup would destroy

    before = len(driver.calls)
    asyncio.run(without().reconcile("t"))
    assert driver.calls[before:] == []  # no admit, no destroy
    run = killing.get_run(asked.id)
    assert run.state == "ended" and run.verdict is not None and run.verdict.status == "rejected"
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("platform.unsupported", "chassisos")]
    assert killing.events(asked.id) == []  # it never started
    status = killing.get_twin("t").status
    assert (status.deployment_id, status.allocation, status.nodes, status.bundle_id) == (
        kept.deployment_id, kept.allocation, kept.nodes, kept.bundle_id)  # no compile overwrote it
    assert (ready_of(killing.get_twin("t")).reason, status.observed_generation) == ("bundle.rejected", 2)
    revision = killing.get_twin("t").revision
    asyncio.run(without().reconcile("t"))  # said once
    assert killing.get_twin("t").revision == revision and driver.calls[before:] == []


def test_what_a_core_lacks_to_tear_down_is_read_from_the_deployment_itself(killing: KillingStore) -> None:
    driver = FakeDriver()
    without = kept_without_chassisos(killing, driver)
    # A record whose bundle is no longer the kept deployment's: the deployment's own decides.
    other = compiler.compile(blueprint.load(ROOT / "testdata/blueprint/three-node.json"), PLATFORMS, PROBES)
    killing.put_bundle(other.id, other.files)
    record = killing.get_twin("t")
    killing.update_twin(dataclasses.replace(record, status=dataclasses.replace(record.status, bundle_id=other.id)),
                        record.revision)
    destroy = request_deletion(killing)
    asyncio.run(without().reconcile("t"))
    assert ("destroy", "t") not in driver.calls and "t" in driver.labs
    verdict = killing.get_run(destroy.id).verdict
    assert verdict is not None and verdict.status == "rejected"
    assert [f.object for f in verdict.findings] == ["chassisos"]


def test_a_cancel_whose_teardown_this_core_cannot_do_says_it_kept_the_lab(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing, "testdata/blueprint/lossy.json"))
    driver = FakeDriver()
    killing.kill_at = "applied"
    killed(make(killing, driver))
    run = only_run(killing)
    mark_cancelling(killing, run.id)
    lacking = {k: v for k, v in PLATFORMS.items() if k != "chassisos"}
    without = Reconciler(killing, {driver.name: driver}, lacking, PROBES, Provider(ENVIRON),
                         pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver))
    asyncio.run(without.reconcile("t"))
    run = killing.get_run(run.id)
    assert_cancelled(run)
    assert run.verdict is not None and "kept" in run.verdict.findings[0].message
    assert "torn down" not in run.verdict.findings[0].message.replace("to tear it down", "")
    assert ("destroy", "t") not in driver.calls and killing.get_twin("t").status.deployment_id is not None
