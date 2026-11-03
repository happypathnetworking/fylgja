"""The reconcile loop (Constitution VIII, D-023, D-025): one pass drives a twin's create from
compiled to pushed as a run with events, over a local store in a temporary directory, a fake
driver, a fake readiness wait and a fake push."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from fakes import FakeDriver, FakePush, FakeReady, fake_push, fake_ready

from fylgja_core import bundle, platform_package, probe_package, push, reconcile
from fylgja_core.credentials import Provider
from fylgja_core.driver import Planned, Refusal, Unplannable
from fylgja_core.findings import Finding, Subject
from fylgja_core.local_store import LocalStore
from fylgja_core.reconcile import Reconciler
from fylgja_core.run import Run, queued
from fylgja_core.run import State as RunState
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


def new_twin(store: LocalStore, blueprint_id: str | None, name: str = "t", *, bundle_id: str | None = None) -> None:
    spec = Spec(blueprint_id=blueprint_id, bundle_id=bundle_id, driver="fake", allow_restart=False)
    store.create_twin(TwinRecord(name=name, revision=1, generation=1, spec=spec,
                                 status=Status(observed_generation=0, conditions=(), nodes=())))


def make(
    store: LocalStore,
    driver: FakeDriver,
    ready: FakeReady | None = None,
    pusher: FakePush | None = None,
    environ: Mapping[str, str] = ENVIRON,
) -> Reconciler:
    return Reconciler(store, {driver.name: driver}, PLATFORMS, PROBES, Provider(environ),
                      pusher=pusher if pusher is not None else fake_push(driver=driver),
                      readiness=ready if ready is not None else fake_ready(driver=driver))


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
