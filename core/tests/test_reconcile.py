"""The reconcile loop (Constitution VIII, D-023, D-025): one pass drives a twin's create from
compiled to pushed as a run with events, over a local store in a temporary directory, a fake
driver, a fake readiness wait and a fake push."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import io
import itertools
import json
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from aio import Skipping, bounded
from fakes import FakeDriver, FakePush, FakeReader, FakeReady, fake_push, fake_ready

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
from fylgja_core.driver import Changes, Exec, Inspection, NodeChange, Planned, Refusal, Unplannable
from fylgja_core.findings import Finding, Loss, Subject, Verdict
from fylgja_core.local_store import LocalStore
from fylgja_core.reconcile import Reconciler
from fylgja_core.run import Event, Run, queued
from fylgja_core.run import State as RunState
from fylgja_core.store import Change, Conflict, NotFound
from fylgja_core.twin_record import Condition, LastStep, Spec, Status, TwinRecord
from fylgja_core.verify import ExecFn, Verifier

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


def verifier_of(driver: FakeDriver, platforms: Mapping[str, Any] = PLATFORMS) -> Verifier:
    return Verifier(platforms, PROBES, Provider(ENVIRON), reader=FakeReader(driver))


def make(
    store: LocalStore,
    driver: FakeDriver,
    ready: FakeReady | None = None,
    pusher: FakePush | None = None,
    environ: Mapping[str, str] = ENVIRON,
    *,
    workers: int = 4,
    resync_s: float = 300.0,
    verifier: Verifier | None = None,
    step_wait_s: float = 1.0,
    platforms: Mapping[str, platform_package.PlatformPackage] = PLATFORMS,
    events_retry_s: float = 5.0,
) -> Reconciler:
    return Reconciler(store, {driver.name: driver}, platforms, PROBES, Provider(environ), workers=workers,
                      resync_s=resync_s, verifier=verifier if verifier is not None else verifier_of(driver, platforms),
                      step_wait_s=step_wait_s, verify_poll_s=0.01, events_retry_s=events_retry_s,
                      pusher=pusher if pusher is not None else fake_push(driver=driver),
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


def skipped_pairs(phase: str, nodes: list[str]) -> list[Seen]:
    return [(phase, outcome, node) for node in nodes for outcome in ("started", "skipped")]


def test_the_push_passes_over_a_node_with_no_configuration(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store, "testdata/blueprint/three-node-unmanaged.json"))
    driver = FakeDriver()
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher).reconcile("t"))

    record = store.get_twin("t")
    assert ready_of(record).status == "True"
    assert [n for n, _ in pusher.calls] == ["n1", "n3"]
    assert [n for n, _ in ready.calls] == DEVICES
    assert all(n.holds == record.status.bundle_id for n in record.status.nodes)
    events = store.events(only_run(store).id)
    assert seen(store, only_run(store).id) == (UP_TO_APPLY + pairs("ready", DEVICES) + pairs("push", ["n1"])
                                               + skipped_pairs("push", ["n2"]) + pairs("push", ["n3"]))
    skipped = [e for e in events if e.outcome == "skipped"]
    assert len(skipped) == 1 and skipped[0].duration_s is not None and skipped[0].rule is None


def test_a_create_with_no_configuration_anywhere_pushes_nothing(store: LocalStore) -> None:
    doc = json.loads((ROOT / "testdata/blueprint/three-node-unmanaged.json").read_text())
    for device in doc["network"]["devices"]:
        device.pop("config", None)
    blueprint_id, _ = store.put_blueprint(doc)
    new_twin(store, blueprint_id)
    driver = FakeDriver()
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher).reconcile("t"))

    record = store.get_twin("t")
    assert ready_of(record).status == "True" and pusher.calls == []
    assert [n for n, _ in ready.calls] == DEVICES
    assert all(n.holds == record.status.bundle_id for n in record.status.nodes)
    assert seen(store, only_run(store).id) == UP_TO_APPLY + pairs("ready", DEVICES) + skipped_pairs("push", DEVICES)


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


def test_a_kick_on_a_ready_twin_with_nothing_moved_inspects_once_and_writes_nothing(store: LocalStore) -> None:
    driver = FakeDriver()
    revision = ready_twin(store, driver).revision
    before = len(driver.calls)
    r = restorer(store, driver)
    asyncio.run(r.reconcile("t"))
    assert store.get_twin("t").revision == revision and len(store.list_runs("t")) == 1
    assert driver.calls[before:] == [("inspect", "t")] and r.queue.waiting() == []


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


def test_a_probe_hosts_readiness_is_read_inside_it_and_it_is_never_pushed(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store, "testdata/blueprint/three-node-probed.json"))
    driver = FakeDriver()
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher).reconcile("t"))

    record = store.get_twin("t")
    assert ready_of(record).status == "True"
    hosts = ["n1-loop-a", "n1-loop-b"]
    assert [n.name for n in record.status.nodes] == sorted(DEVICES + hosts)
    assert all(n.holds is None for n in record.status.nodes if n.name in hosts)
    assert seen(store, only_run(store).id) == (UP_TO_APPLY + pairs("ready", DEVICES + hosts)
                                               + pairs("push", DEVICES))
    assert [node for node, _ in ready.calls] == DEVICES and [node for node, _ in pusher.calls] == DEVICES
    assert all(timeout == PLATFORMS["nokia_srlinux"].readiness.timeout_s for _, timeout in ready.calls)
    execs = [c for c in driver.calls if c[0] == "exec"]
    assert execs == [("exec", "t", h, "ip", "-4", "-o", "addr", "show", "dev", "eth1") for h in hosts]


def test_a_probe_host_that_never_shows_its_address_times_out_the_create(
    store: LocalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reconcile, "HOST_POLL_S", 0.05)
    new_twin(store, file_blueprint(store, "testdata/blueprint/three-node-probed.json"))
    driver = FakeDriver()
    driver.exec_answers[("t", "n1-loop-b")] = Exec(0, "", "")
    ping = PROBES["ping"]
    short = {"ping": dataclasses.replace(ping, readiness=dataclasses.replace(ping.readiness, timeout_s=1))}
    r = Reconciler(store, {driver.name: driver}, PLATFORMS, short, Provider(ENVIRON),
                   pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver), cancel_poll_s=0.01,
                   verifier=verifier_of(driver))
    asyncio.run(r.reconcile("t"))

    run = only_run(store)
    assert run.verdict is not None and run.verdict.status == "failed"
    (finding,) = run.verdict.findings
    assert (finding.rule, finding.object) == ("readiness.timeout", "n1-loop-b") and "within 1s" in finding.message
    assert seen(store, run.id)[-2:] == [("ready", "started", "n1-loop-b"), ("ready", "timed_out", "n1-loop-b")]
    assert len([c for c in driver.calls if c[:3] == ("exec", "t", "n1-loop-b")]) > 1
    assert driver.calls[-1] == ("destroy", "t") and "t" not in driver.labs
    assert_cleaned_up(store.get_twin("t"), "readiness.timeout")


def test_an_unreachable_probe_host_is_transient(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store, "testdata/blueprint/three-node-probed.json"))
    driver = FakeDriver()
    driver.unreachable_exec.add(("t", "n1-loop-a"))

    async def scenario() -> None:
        r = make(store, driver)
        await r.reconcile("t")
        record, run = store.get_twin("t"), only_run(store)
        assert record.status.phase == "applied" and run.state == "running"
        assert seen(store, run.id)[-2:] == [("ready", "started", "n1-loop-a"), ("ready", "failed", "n1-loop-a")]
        assert r.queue.waiting() == ["t"] and r.backoff == {"t": 1.0}
        assert ("destroy", "t") not in driver.calls

    asyncio.run(scenario())


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


def phase_of(record: TwinRecord) -> str | None:
    """The phase a record says its run last completed: a running step's `last_step.phase`, where a
    step records its phases (alone before `applied`, beside `phase` after), else `phase`."""
    step = record.status.last_step
    return step.phase if step is not None and step.outcome == "running" else record.status.phase


class KillingStore(LocalStore):
    """A local store that kills the core once, right after the write of a twin record that moves
    its phase (`phase_of`) to `kill_at`, or, for `kill_at == "ended"`, right after ending a run;
    or right after appending a run event whose `(phase, outcome)` is `kill_event`; or right after
    making a run of the operation `kill_created`. The move is what counts: a step's run is taken
    over a twin whose `phase` is already `pushed`."""

    kill_at: str | None = None
    kill_event: tuple[str, str] | None = None
    kill_created: str | None = None

    def create_run(self, run: Run) -> None:
        super().create_run(run)
        if self.kill_created == run.operation:
            self.kill_created = None
            raise RuntimeError("killed")

    def append_event(self, run_id: str, event: Event) -> Event:
        appended = super().append_event(run_id, event)
        if self.kill_event == (event.phase, event.outcome):
            self.kill_event = None
            raise RuntimeError("killed")
        return appended

    def update_twin(self, record: TwinRecord, expected_revision: int) -> TwinRecord:
        was = phase_of(self.get_twin(record.name)) if self.kill_at is not None else None
        written = super().update_twin(record, expected_revision)
        if self.kill_at is not None and phase_of(written) == self.kill_at != was:
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


def resumed(store: LocalStore, run_id: str, operation: str | None = None) -> list[Seen]:
    """The run's events, after checking it is still the twin's one run (of `operation`, when named:
    a stepped twin has its create's run too) and its events have no gap."""
    assert [r.id for r in store.list_runs("t") if operation in (None, r.operation)] == [run_id]
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


def test_with_reapply_a_create_applies_with_no_inspect_before_it(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver(reapply=True)
    asyncio.run(make(store, driver).reconcile("t"))
    assert driver.calls == [("admit", "t"), ("plan", "t"), ("apply", "t"), ("inspect", "t")]
    assert seen(store, only_run(store).id) == CREATE
    assert ready_of(store.get_twin("t")).status == "True"


def test_with_reapply_a_create_killed_during_its_deploy_applies_again_with_no_probe(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver(reapply=True)
    driver.fail_after = "apply"
    killed(make(store, driver))
    assert store.get_twin("t").status.phase == "planned" and "t" in driver.labs
    del driver.labs["t"]["n3"]  # a node the killed apply had not made yet

    before = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher).reconcile("t"))
    # Applying again finishes the apply cut short (D-068): no inspect before it, and no reconfigure.
    assert driver.calls[before:] == [("apply", "t"), ("inspect", "t")]
    assert [node for node, _ in ready.calls] == DEVICES  # the ready phase alone: no probe
    record = assert_ready_once_each(store, pusher)
    assert [(n.name, n.incarnation) for n in record.status.nodes] == [("n1", "boot-1"), ("n2", "boot-1"),
                                                                      ("n3", "boot-2")]
    events = resumed(store, only_run(store).id)
    assert events == [*UP_TO_APPLY[:-1], ("apply", "started", None), ("apply", "done", None),
                      *pairs("ready", DEVICES), *pairs("push", DEVICES)]
    assert all(outcome != "skipped" for _, outcome, _ in events)


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


def test_killed_after_ready_with_an_unmanaged_node_a_resume_pushes_the_others_and_holds_the_bundle_everywhere(
    killing: KillingStore,
) -> None:
    new_twin(killing, file_blueprint(killing, "testdata/blueprint/three-node-unmanaged.json"))
    driver = FakeDriver()
    killing.kill_at = "ready"
    killed(make(killing, driver))
    run = only_run(killing)

    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher).reconcile("t"))
    assert sorted(node for node, _ in pusher.calls) == ["n1", "n3"]
    events = resumed(killing, run.id)
    assert ("push", "started", "n2") in events and ("push", "skipped", "n2") in events
    assert ("push", "started", "n1") in events and ("push", "started", "n3") in events
    record = killing.get_twin("t")
    assert ready_of(record).status == "True" and record.status.bundle_id is not None
    assert all(n.holds == record.status.bundle_id for n in record.status.nodes if n.name in DEVICES)


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
    """A push that marks the twin's run of `operation` (its create, unless named) cancelling once
    it has pushed `after` nodes, or asks for the twin's deletion then, as a client would meanwhile."""

    def __init__(
        self, store: LocalStore, driver: FakeDriver, *, after: int = 1, delete: bool = False, operation: str = "create"
    ) -> None:
        super().__init__(None, None, None, driver)
        self.store, self.after, self.delete, self.operation = store, after, delete, operation

    async def __call__(
        self, address: str, package: platform_package.PlatformPackage, config: str, credential: Credential
    ) -> push.Pushed | push.Refused:
        answer = await super().__call__(address, package, config, credential)
        if len(self.calls) == self.after:
            if self.delete:
                request_deletion(self.store)
            else:
                mark_cancelling(self.store, the_run(self.store, self.operation).id)
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

    planned, verdict, changes = asyncio.run(r.dry_run("t", spec_of(blueprint_id)))
    assert planned is not None and planned.twin == "t" and changes is None  # a create's changes nothing that runs
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
    planned, verdict, changes = asyncio.run(r.dry_run("t", spec_of(blueprint_id)))
    assert planned is None and changes is None and verdict.operation == "plan" and verdict.status == "rejected"
    assert verdict.findings == (Finding(rule="admission.capacity", severity="error", object="t", message="no room"),)
    unserved, verdict, changes = asyncio.run(r.dry_run("t", spec_of(blueprint_id, driver="elsewhere")))
    assert unserved is None and changes is None and [f.rule for f in verdict.findings] == ["twin.driver.unknown"]


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


class SlowToStop(FakeDriver):
    """A runtime whose `events`, once cancelled, takes until `released` is set to close, as a watch's
    stream may; and whose `apply` answers once `answer` is set, setting `cancelled` when it is
    cancelled waiting."""

    def __init__(self) -> None:
        super().__init__()
        self.closing = asyncio.Event()
        self.released = asyncio.Event()
        self.applying = asyncio.Event()
        self.answer = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def events(self) -> AsyncIterator[str]:
        try:
            await asyncio.Event().wait()  # nothing happens on this runtime: only a cancel ends the wait
            yield ""
        finally:
            self.closing.set()
            await self.released.wait()  # its source's close, held by the test

    async def apply(self, *args: Any, **kw: Any) -> None:
        self.applying.set()
        try:
            await self.answer.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        await super().apply(*args, **kw)


def test_stop_cancels_a_pass_in_flight_before_it_awaits_a_watcher_slow_to_close(store: LocalStore) -> None:
    # A watcher's cancellation can take as long as its source's close: a pass must not go on meanwhile, calling the
    # runtime and writing the store, a stop for a lost Lease's included.
    new_twin(store, file_blueprint(store))
    driver = SlowToStop()

    async def scenario() -> None:
        r = make(store, driver, workers=1)
        await r.start()
        await asyncio.wait_for(driver.applying.wait(), 5)  # a create's pass, in its deploy
        (run,) = store.list_runs("t")
        at_stop = (list(driver.calls), store.get_twin("t"), store.list_runs("t"), store.events(run.id))
        stopping = asyncio.create_task(r.stop())
        await asyncio.wait_for(driver.closing.wait(), 5)  # the watcher cancelled, its close held
        driver.answer.set()  # the runtime answers now: a pass still running goes on
        for _ in range(50):
            await asyncio.sleep(0)
        assert driver.cancelled.is_set()  # the pass was cancelled before the watcher's close ended
        driver.released.set()
        await asyncio.wait_for(stopping, 5)
        assert (driver.calls, store.get_twin("t"), store.list_runs("t"), store.events(run.id)) == at_stop

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
    # No worker failed to take a name: the queue it waits on is its own loop's; nor did the task that listens to the
    # driver's events, whose wake-up is made on the loop that listens.
    assert [r.getMessage() for r in caplog.records if r.name == "fylgja.queue"] == []
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


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
                         pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver),
                         verifier=verifier_of(driver))
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
                          pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver),
                          verifier=verifier_of(driver))

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
                          pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver),
                          verifier=verifier_of(driver))

    asyncio.run(without().reconcile("t"))
    assert killing.get_twin("t").status.deployment_id is not None
    return without


@pytest.mark.parametrize("queued_as", ["step", "create"])
def test_a_new_spec_over_a_kept_deployment_starts_no_create(killing: KillingStore, queued_as: str) -> None:
    driver = FakeDriver()
    without = kept_without_chassisos(killing, driver)
    kept = killing.get_twin("t").status
    assert kept.bundle_id is not None and kept.nodes  # a lab was applied: a new spec is a step's
    three_node = file_blueprint(killing)
    record = killing.get_twin("t")  # a client's PUT: a new spec, and its queued run
    killing.update_twin(dataclasses.replace(record, generation=2, spec=dataclasses.replace(
        record.spec, blueprint_id=three_node)), record.revision)
    # A step, as the API queues one over an applied lab; or a create, a reading the loop's dispatch does not make.
    asked = queued("t", "step" if queued_as == "step" else "create", "alice")
    killing.create_run(asked)
    driver.refuse = Refusal("admission.capacity", "no room")  # had admission run, its cleanup would destroy

    before = len(driver.calls)
    asyncio.run(without().reconcile("t"))
    assert driver.calls[before:] == []  # no admit, no destroy
    (run,) = steps(killing)  # the step refused: the client's, or the loop's own superseding the create
    assert run.state == "ended" and run.verdict is not None and run.verdict.status == "rejected"
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("platform.unsupported", "chassisos")]
    assert killing.events(run.id) == []  # it never started
    if queued_as == "step":
        assert run.id == asked.id
    else:
        superseded = killing.get_run(asked.id)
        assert run.principal == "core" and superseded.verdict is not None
        assert [(f.rule, f.message) for f in superseded.verdict.findings] == [
            ("run.cancelled", SUPERSEDED.format(run=run.id))]
    record = killing.get_twin("t")
    status = record.status
    assert (status.deployment_id, status.allocation, status.nodes, status.bundle_id) == (
        kept.deployment_id, kept.allocation, kept.nodes, kept.bundle_id)  # no compile overwrote it
    assert (ready_of(record).reason, status.observed_generation) == ("bundle.rejected", 2)
    # Recorded as every refused step is: Stepping False for the rule, `last_step` rejected, naming the run.
    assert (condition_of(record, "Stepping").status, condition_of(record, "Stepping").reason) == (
        "False", "bundle.rejected")
    assert status.last_step == LastStep(outcome="rejected", from_=kept.bundle_id, to=kept.bundle_id,
                                        phase="compiled", run_id=run.id)
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
                         pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver),
                         verifier=verifier_of(driver))
    asyncio.run(without.reconcile("t"))
    run = killing.get_run(run.id)
    assert_cancelled(run)
    assert run.verdict is not None and "kept" in run.verdict.findings[0].message
    assert "torn down" not in run.verdict.findings[0].message.replace("to tear it down", "")
    assert ("destroy", "t") not in driver.calls and killing.get_twin("t").status.deployment_id is not None


def test_a_reconciler_without_a_verifier_is_a_type_error(store: LocalStore) -> None:
    with pytest.raises(TypeError, match="verifier"):
        Reconciler(store, {}, PLATFORMS, PROBES, Provider(ENVIRON))  # type: ignore[call-arg]


def test_a_spec_written_while_a_run_is_in_flight_is_not_swallowed_by_its_settle(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    inner = fake_push(driver=driver)
    written: list[int] = []

    async def writes_a_spec(address: str, package: Any, config: str, credential: Any) -> Any:
        if not written:  # a client's PUT meanwhile: the generation moves, the run's target does not
            current = store.get_twin("t")
            assert current.status.generation_in_flight == 1
            bumped = dataclasses.replace(current, generation=2)
            written.append(store.update_twin(bumped, current.revision).generation)
        return await inner(address, package, config, credential)

    asyncio.run(make(store, driver, pusher=writes_a_spec).reconcile("t"))  # type: ignore[arg-type]

    record = store.get_twin("t")
    assert written == [2]
    assert record.generation == 2 and record.status.observed_generation == 1
    assert record.status.generation_in_flight is None and record.status.run_id is None
    assert ready_of(record).status == "True"


def test_a_create_clears_the_generation_in_flight_with_its_run(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    asyncio.run(make(store, driver).reconcile("t"))
    status = store.get_twin("t").status
    assert status.generation_in_flight is None and status.run_id is None


def test_a_record_written_before_the_generation_in_flight_settles_at_its_generation(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "pushed"
    killed(make(killing, driver))
    record = killing.get_twin("t")
    assert record.status.generation_in_flight == 1
    killing.update_twin(dataclasses.replace(record, status=dataclasses.replace(
        record.status, generation_in_flight=None)), record.revision)  # as a record of phase 4 is
    asyncio.run(make(killing, driver).reconcile("t"))
    settled = killing.get_twin("t")
    assert settled.status.observed_generation == settled.generation == 1 and settled.status.run_id is None


# The step (D-050): a Ready `three-node` twin, then a client's new spec.

UP_TO_PLAN: list[Seen] = UP_TO_APPLY[:6]


def ready_twin(store: LocalStore, driver: FakeDriver, path: str = "testdata/blueprint/three-node.json") -> TwinRecord:
    """A Ready twin of the blueprint at `path`, `three-node` unless named, made as
    `test_a_create_runs_every_phase_and_ends_ready` makes it."""
    new_twin(store, file_blueprint(store, path))
    asyncio.run(make(store, driver).reconcile("t"))
    record = store.get_twin("t")
    assert ready_of(record).status == "True" and record.status.observed_generation == record.generation == 1
    return record


def respec(
    store: LocalStore,
    path: str | None = None,
    *,
    bundle_id: str | None = None,
    blueprint_id: str | None = None,
    allow_restart: bool = False,
) -> TwinRecord:
    """A client's new spec for `t`, written as the API writes one: the blueprint at `path` filed
    (or the filed blueprint `blueprint_id`, or the bundle `bundle_id`, named), the generation moved on."""
    record = store.get_twin("t")
    blueprint_id = blueprint_id if path is None else file_blueprint(store, path)
    spec = dataclasses.replace(record.spec, blueprint_id=blueprint_id, bundle_id=bundle_id, allow_restart=allow_restart)
    return store.update_twin(dataclasses.replace(record, spec=spec, generation=record.generation + 1), record.revision)


def condition_of(record: TwinRecord, kind: str) -> Condition:
    (condition,) = [c for c in record.status.conditions if c.type == kind]
    return condition


def steps(store: LocalStore) -> list[Run]:
    """The twin's step runs, oldest first."""
    return [r for r in reversed(store.list_runs("t")) if r.operation == "step"]


def assert_refused(
    store: LocalStore, before: TwinRecord, run: Run, rule: str, *, kept: LastStep | None = None, written: int = 0
) -> TwinRecord:
    """The step ended `rejected` for `rule`, `before` being the record as the new spec left it,
    and is recorded as a refused create is: Ready and Stepping False for it, `last_step` rejected
    and naming the run (or `kept`, the `last_step` a twin diverged already keeps), the observed
    generation the run's (and `written` specs a client wrote meanwhile ahead of it), no run in
    flight; and the twin runs what it ran, its record still describing it."""
    assert run.state == "ended" and run.verdict is not None
    assert (run.verdict.operation, run.verdict.status) == ("step", "rejected")
    record = store.get_twin("t")
    status = record.status
    assert (ready_of(record).status, ready_of(record).reason) == ("False", rule)
    assert (condition_of(record, "Stepping").status, condition_of(record, "Stepping").reason) == ("False", rule)
    if kept is not None:
        assert status.last_step == kept
    else:
        assert status.last_step is not None
        assert (status.last_step.outcome, status.last_step.run_id) == ("rejected", run.id)
        assert status.last_step.from_ == before.status.bundle_id
    assert status.observed_generation == record.generation - written == before.generation
    assert status.run_id is None and status.generation_in_flight is None
    assert (status.phase, status.blueprint_id, status.bundle_id, status.deployment_id, status.allocation,
            status.nodes) == (before.status.phase, before.status.blueprint_id, before.status.bundle_id,
                              before.status.deployment_id, before.status.allocation, before.status.nodes)
    return record


@pytest.mark.parametrize("how", ["blueprint", "bundle"])
def test_a_step_to_the_bundle_the_twin_runs_ends_unchanged_at_compiled(store: LocalStore, how: str) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    calls = len(driver.calls)
    if how == "blueprint":  # the same blueprint, another spec: it compiles to the bundle the twin runs
        respec(store, "testdata/blueprint/three-node.json", allow_restart=True)
    else:
        respec(store, bundle_id=before.status.bundle_id)
    asyncio.run(make(store, driver).reconcile("t"))

    (run,) = steps(store)
    assert run.state == "ended" and run.verdict is not None
    assert (run.verdict.operation, run.verdict.status, run.verdict.findings) == ("step", "ok", ())
    assert seen(store, run.id) == [("compile", "started", None), ("compile", "done", None)]
    record = store.get_twin("t")
    status = before.status
    assert status.bundle_id is not None
    assert record.status.last_step == LastStep(outcome="unchanged", from_=status.bundle_id, to=status.bundle_id,
                                               phase="compiled", run_id=run.id)
    assert record.status.observed_generation == record.generation == 2
    assert record.status.run_id is None and record.status.generation_in_flight is None
    assert ready_of(record) == ready_of(before)  # True for twin.ready already: its since kept
    assert (condition_of(record, "Stepping").status, condition_of(record, "Stepping").reason) == (
        "False", "twin.ready")
    assert (record.status.phase, record.status.bundle_id, record.status.deployment_id, record.status.nodes) == (
        status.phase, status.bundle_id, status.deployment_id, status.nodes)
    assert driver.calls[calls:] == []


def test_a_step_that_recreates_a_node_without_allow_restart_is_refused_after_planned(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    calls = len(driver.calls)
    driver.recreates = {"n3"}  # its kind changes: the runtime makes it anew
    before = respec(store, "testdata/blueprint/steps/three-node-n3-eos.json")
    asked = queued("t", "step", "alice")
    store.create_run(asked)
    pusher = fake_push(driver=driver)
    asyncio.run(make(store, driver, pusher=pusher).reconcile("t"))

    (run,) = steps(store)
    assert run.id == asked.id and run.principal == "alice"
    record = assert_refused(store, before, run, "step.restart.required")
    assert run.verdict is not None
    (finding,) = run.verdict.findings
    assert (finding.rule, finding.severity, finding.object) == ("step.restart.required", "error", "n3")
    assert "recreated" in finding.message
    assert seen(store, run.id) == UP_TO_PLAN  # it ends at plan done: nothing from apply
    assert record.status.last_step is not None and record.status.last_step.phase == "planned"
    target = record.status.last_step.to
    assert target != before.status.bundle_id
    subject = run.verdict.subject  # what the run compiled and planned
    assert (subject.blueprint_id, subject.bundle_id) == (before.spec.blueprint_id, target)
    assert subject.deployment_id is not None and subject.deployment_id != before.status.deployment_id
    assert store.get_deployment(subject.deployment_id)[0].bundle_id == target
    assert all(n.holds == before.status.bundle_id for n in record.status.nodes)
    assert driver.calls[calls:] == [("admit", "t", "held"), ("plan", "t"), ("changes", "t")]
    assert pusher.calls == [] and "t" in driver.labs


def test_killed_after_a_refused_step_ended_the_next_pass_records_the_refusal(killing: KillingStore) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    driver.recreates = {"n3"}
    before = respec(killing, "testdata/blueprint/steps/three-node-n3-eos.json")
    killing.kill_at = "ended"
    killed(make(killing, driver))
    (run,) = steps(killing)
    assert run.state == "ended" and killing.get_twin("t").status.run_id == run.id

    calls, events = len(driver.calls), len(killing.events(run.id))
    asyncio.run(make(killing, driver).reconcile("t"))
    assert_refused(killing, before, run, "step.restart.required")  # read back from the verdict: no event names it
    assert driver.calls[calls:] == [] and len(killing.events(run.id)) == events and "t" in driver.labs


def test_killed_after_admitted_a_step_resumes_planning_its_target_and_is_still_refused(killing: KillingStore) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    driver.recreates = {"n3"}
    before = respec(killing, "testdata/blueprint/steps/three-node-n3-eos.json")
    killing.kill_at = "admitted"
    killed(make(killing, driver))
    (run,) = steps(killing)
    record = killing.get_twin("t")
    assert record.status.last_step is not None and record.status.last_step.phase == "admitted"
    assert record.status.phase == "pushed" and record.status.run_id == run.id  # the running twin's, until applied
    target = record.status.last_step.to

    calls = len(driver.calls)
    asyncio.run(make(killing, driver).reconcile("t"))
    run = killing.get_run(run.id)
    assert_refused(killing, before, run, "step.restart.required")
    assert driver.calls[calls:] == [("plan", "t"), ("changes", "t")]  # admitted once: not again
    assert seen(killing, run.id) == [("compile", "started", None), ("compile", "done", None),
                                     ("admit", "started", None), ("plan", "started", None), ("plan", "done", None)]
    assert run.verdict is not None and run.verdict.subject.deployment_id is not None
    assert killing.get_deployment(run.verdict.subject.deployment_id)[0].bundle_id == target


def test_a_refused_twin_whose_spec_is_restored_to_what_it_runs_is_ready_again(store: LocalStore) -> None:
    driver = FakeDriver()
    r = make(store, driver)
    ready = ready_twin(store, driver)
    driver.recreates = {"n3"}
    respec(store, "testdata/blueprint/steps/three-node-n3-eos.json")
    asyncio.run(r.reconcile("t"))
    assert ready_of(store.get_twin("t")).reason == "step.restart.required"
    respec(store, "testdata/blueprint/three-node.json")
    asyncio.run(r.reconcile("t"))

    _, restored = steps(store)
    assert restored.verdict is not None and restored.verdict.status == "ok"
    assert seen(store, restored.id) == [("compile", "started", None), ("compile", "done", None)]
    record = store.get_twin("t")
    old = ready.status.bundle_id
    assert old is not None
    assert record.status.last_step == LastStep(outcome="unchanged", from_=old, to=old, phase="compiled",
                                               run_id=restored.id)
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")  # it runs what is asked
    assert (condition_of(record, "Stepping").status, condition_of(record, "Stepping").reason) == (
        "False", "twin.ready")
    assert record.status.observed_generation == record.generation == 3 and record.status.run_id is None
    assert (record.status.phase, record.status.bundle_id, record.status.nodes) == (
        ready.status.phase, old, ready.status.nodes)


def test_a_new_spec_on_a_record_with_a_deployment_and_no_nodes_runs_a_create(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    record = store.get_twin("t")  # a deployment filed and no lab applied
    store.update_twin(dataclasses.replace(record, status=dataclasses.replace(record.status, nodes=(), phase=None)),
                      record.revision)
    driver.labs.pop("t")
    respec(store, "testdata/blueprint/three-node.json", allow_restart=True)
    asyncio.run(make(store, driver).reconcile("t"))

    assert [run.operation for run in store.list_runs("t")] == ["create", "create"] and steps(store) == []
    created = store.list_runs("t")[0]
    assert created.verdict is not None and created.verdict.status == "ok"
    assert seen(store, created.id) == CREATE


def test_a_link_change_on_a_driver_that_cannot_relink_is_refused(store: LocalStore) -> None:
    driver = FakeDriver(relink=False)
    ready_twin(store, driver)
    calls = len(driver.calls)
    before = respec(store, "testdata/blueprint/steps/three-node-unlinked.json")
    asyncio.run(make(store, driver).reconcile("t"))

    (run,) = steps(store)
    assert_refused(store, before, run, "step.relink.unsupported")
    assert run.verdict is not None
    assert [(f.rule, f.severity, f.object) for f in run.verdict.findings] == [("step.relink.unsupported", "error", "t")]
    assert seen(store, run.id) == UP_TO_PLAN
    assert driver.calls[calls:] == [("admit", "t", "held"), ("plan", "t"), ("changes", "t")]


@pytest.mark.parametrize("to", ["another", "its own"])
def test_a_diverged_twin_is_refused_at_compiled_whatever_the_spec(store: LocalStore, to: str) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    record = store.get_twin("t")
    old = record.status.bundle_id
    assert old is not None
    # The step that left the twin diverged, and its record (D-029): the refusal never writes over it.
    diverged = Condition(type="Diverged", status="True", reason="step.diverged", since=clock.now())
    left = LastStep(outcome="diverged", from_=old, to="e" * 64, phase="ready", run_id=queued("t", "step", "bob").id)
    store.update_twin(dataclasses.replace(record, status=dataclasses.replace(
        record.status, conditions=(*record.status.conditions, diverged), last_step=left)), record.revision)
    calls = len(driver.calls)
    if to == "another":
        before = respec(store, "testdata/blueprint/steps/two-node.json")
    else:  # never `unchanged`: no bundle describes a diverged twin (D-029)
        before = respec(store, bundle_id=old)
    asyncio.run(make(store, driver).reconcile("t"))

    (run,) = steps(store)
    record = assert_refused(store, before, run, "step.twin.diverged", kept=left)
    assert run.verdict is not None
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("step.twin.diverged", "t")]
    assert condition_of(record, "Diverged") == diverged
    assert seen(store, run.id) == [("compile", "started", None), ("compile", "failed", None)]
    assert store.events(run.id)[-1].rule == "step.twin.diverged"
    assert driver.calls[calls:] == []


def test_an_uncompilable_step_target_is_rejected_and_the_twin_runs_what_it_ran(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    calls = len(driver.calls)
    before = respec(store, "testdata/compiler/rejected/network-empty.json")
    asyncio.run(make(store, driver).reconcile("t"))

    (run,) = steps(store)
    record = assert_refused(store, before, run, "bundle.rejected")
    assert run.verdict is not None
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("network.empty", "network")]
    assert seen(store, run.id) == [("compile", "started", None), ("compile", "failed", None)]
    assert store.events(run.id)[-1].rule == "bundle.rejected"
    old = before.status.bundle_id
    assert old is not None
    assert record.status.last_step == LastStep(outcome="rejected", from_=old, to=old, phase="compiled",
                                               run_id=run.id)  # it reached no bundle of its own
    assert run.verdict.subject == Subject(twin="t", run_id=run.id, blueprint_id=before.spec.blueprint_id,
                                          bundle_id=old, deployment_id=before.status.deployment_id)
    assert driver.calls[calls:] == []


class UnreadableChanges(FakeDriver):
    """A driver whose `changes` finds a node of the running deployment no loaded package runs, as
    after a package's image was upgraded."""

    def changes(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("changes", "t"))
        raise ValueError("no package given runs the node n3 (nokia_srlinux, ghcr.io/nokia/srlinux:old)")


def test_a_running_deployment_no_loaded_package_runs_rejects_the_step(store: LocalStore) -> None:
    driver = UnreadableChanges()
    ready_twin(store, driver)
    calls = len(driver.calls)
    before = respec(store, "testdata/blueprint/steps/two-node.json")
    asyncio.run(make(store, driver).reconcile("t"))

    (run,) = steps(store)
    assert_refused(store, before, run, "bundle.rejected")
    assert run.verdict is not None
    (finding,) = run.verdict.findings
    assert (finding.rule, finding.object) == ("bundle.rejected", "t") and "n3" in finding.message
    assert seen(store, run.id) == [*UP_TO_APPLY[:5], ("plan", "failed", None)]
    assert store.events(run.id)[-1].rule == "bundle.rejected"
    assert driver.calls[calls:] == [("admit", "t", "held"), ("plan", "t"), ("changes", "t")]


def test_after_a_refused_step_a_spec_allowing_the_restart_passes_the_refusals(store: LocalStore) -> None:
    driver = FakeDriver()
    r = make(store, driver, verifier=seeded(driver, "testdata/blueprint/steps/three-node-n3-eos.json")[0])
    before = ready_twin(store, driver)
    driver.recreates = {"n3"}
    respec(store, "testdata/blueprint/steps/three-node-n3-eos.json")
    asyncio.run(r.reconcile("t"))
    calls = len(driver.calls)
    allowing = respec(store, "testdata/blueprint/steps/three-node-n3-eos.json", allow_restart=True)
    asyncio.run(r.reconcile("t"))

    refused, stepping = steps(store)
    assert refused.verdict is not None and refused.verdict.status == "rejected"
    assert seen(store, stepping.id) == UP_TO_APPLY + pairs("ready", ["n3"]) + push_events(["n3"], DEVICES) + WAITED
    assert driver.calls[calls:] == [("admit", "t", "held"), ("plan", "t"), ("changes", "t"), ("apply", "t"),
                                    ("inspect", "t")]
    assert allowing.status.bundle_id == before.status.bundle_id  # the refusal left the twin as it ran
    assert_stepped(store, allowing, stepping)
    assert ("destroy", "t") not in driver.calls


def test_a_new_spec_on_a_twin_whose_create_never_applied_creates_it_again(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver(refuse=Refusal("admission.capacity", "no room"))
    r = make(store, driver)
    asyncio.run(r.reconcile("t"))
    assert store.get_twin("t").status.deployment_id is None  # its cleanup cleared it
    driver.refuse = None
    respec(store, "testdata/blueprint/three-node.json", allow_restart=True)
    asyncio.run(r.reconcile("t"))

    assert [run.operation for run in store.list_runs("t")] == ["create", "create"]
    assert ready_of(store.get_twin("t")).status == "True" and steps(store) == []


def test_a_step_cancelled_before_it_started_ends_cancelled_and_tears_nothing_down(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    calls = len(driver.calls)
    before = respec(store, "testdata/blueprint/steps/two-node.json")
    asked = queued("t", "step", "alice")
    store.create_run(asked)
    mark_cancelling(store, asked.id)
    asyncio.run(make(store, driver).reconcile("t"))

    run = store.get_run(asked.id)
    assert_cancelled(run)
    assert seen(store, run.id) == [("cancel", "started", None), ("cancel", "done", None)]
    assert driver.calls[calls:] == [] and "t" in driver.labs
    record = store.get_twin("t")
    assert record.status.last_step is not None
    assert (record.status.last_step.outcome, record.status.last_step.run_id) == ("cancelled", run.id)
    assert (ready_of(record).reason, condition_of(record, "Stepping").status) == ("run.cancelled", "False")
    assert record.status.observed_generation == record.generation == 2 and record.status.run_id is None
    assert (record.status.bundle_id, record.status.deployment_id, record.status.nodes) == (
        before.status.bundle_id, before.status.deployment_id, before.status.nodes)


# The step completes (D-050): applied through flows, the wait for verify, and the end.

WAITED: list[Seen] = [("verify", "started", None), ("verify", "done", None),
                      ("flows", "started", None), ("flows", "skipped", None)]


def push_events(pushed: list[str], nodes: list[str]) -> list[Seen]:
    """A push over `nodes` in order: those in `pushed` pushed, the rest marked holding without a push."""
    return [("push", outcome, node) for node in nodes
            for outcome in ("started", "done" if node in pushed else "skipped")]


def doc_of(path: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((ROOT / path).read_text())
    return doc


def seeded(driver: FakeDriver, target: str | dict[str, Any]) -> tuple[Verifier, FakeReader]:
    """A verifier whose reader holds the facts of `t` built to `target` (a blueprint, or its
    path), so verify holds on the twin a step to it leaves."""
    doc = doc_of(target) if isinstance(target, str) else target
    reader = FakeReader(driver)
    reader.seed("t", compiler.compile(blueprint.decode(doc), PLATFORMS, PROBES).manifest, PLATFORMS)
    return Verifier(PLATFORMS, PROBES, Provider(ENVIRON), reader=reader), reader


def edited_n1() -> dict[str, Any]:
    """`three-node` with one more line in `n1`'s configuration: a step to it changes `n1`'s checksum alone."""
    doc = doc_of("testdata/blueprint/three-node.json")
    (n1,) = [device for device in doc["network"]["devices"] if device["name"] == "n1"]
    n1["config"] += "set / system information location lab-2\n"
    return doc


def assert_stepped(store: LocalStore, before: TwinRecord, run: Run, *, waited: bool = True) -> TwinRecord:
    """The step ended `ok`, `before` being the record as the new spec left it, and the record
    moved to its target: the bundle, blueprint and deployment the run planned over the allocation
    the twin held, `last_step` stepped at `flows` naming the run, Ready True and Stepping False for
    `twin.ready`, the observed generation the run's, no run in flight. The verdict names the
    target and carries the flows, and verify's counts and the wait unless `waited` is False: a step
    resumed after `verified` runs `flows` alone."""
    assert run.state == "ended" and run.verdict is not None
    assert (run.verdict.operation, run.verdict.status) == ("step", "ok")
    record = store.get_twin("t")
    status, old = record.status, before.status.bundle_id
    assert old is not None and status.bundle_id is not None and status.bundle_id != old
    assert status.last_step == LastStep(outcome="stepped", from_=old, to=status.bundle_id, phase="flows",
                                        run_id=run.id)
    assert status.deployment_id is not None and status.deployment_id != before.status.deployment_id
    target, _ = store.get_deployment(status.deployment_id)
    assert target.bundle_id == status.bundle_id and target.allocation == status.allocation == before.status.allocation
    assert status.blueprint_id == before.spec.blueprint_id
    assert (status.phase, status.run_id, status.generation_in_flight) == ("flows", None, None)
    assert status.observed_generation == before.generation
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert (condition_of(record, "Stepping").status, condition_of(record, "Stepping").reason) == (
        "False", "twin.ready")
    assert run.verdict.subject == Subject(twin="t", run_id=run.id, blueprint_id=status.blueprint_id,
                                          bundle_id=status.bundle_id, deployment_id=status.deployment_id)
    assert run.verdict.loss is not None
    if not waited:
        assert (run.verdict.counts, run.verdict.wait) == (None, None)
        return record
    assert run.verdict.counts is not None and run.verdict.wait is not None
    assert run.verdict.wait.budget_s == 1 and run.verdict.wait.after_s >= 0
    return record


def holds(record: TwinRecord) -> dict[str, str | None]:
    return {n.name: n.holds for n in record.status.nodes}


def test_a_step_removing_a_node_drops_it_pushes_nothing_unchanged_and_ends_stepped(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    calls = len(driver.calls)
    before = respec(store, "testdata/blueprint/steps/two-node.json")
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    verifier, _ = seeded(driver, "testdata/blueprint/steps/two-node.json")
    asyncio.run(make(store, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))

    (run,) = steps(store)
    record = assert_stepped(store, before, run)
    # No node's incarnation moved: none is readied, and n1 and n2 hold the new bundle with no push.
    assert seen(store, run.id) == UP_TO_APPLY + push_events([], ["n1", "n2"]) + WAITED
    assert holds(record) == {"n1": record.status.bundle_id, "n2": record.status.bundle_id}
    assert [n.incarnation for n in record.status.nodes] == ["boot-1", "boot-1"]
    assert ready.calls == [] and pusher.calls == []
    assert driver.calls[calls:] == [("admit", "t", "held"), ("plan", "t"), ("changes", "t"), ("apply", "t"),
                                    ("inspect", "t")]
    assert sorted(driver.labs["t"]) == ["n1", "n2"]
    assert run.verdict is not None and run.verdict.wait is not None
    assert (run.verdict.wait.outcome, run.verdict.loss) == ("settled", ())
    assert all(e.rule is None for e in store.events(run.id))


def test_a_step_adding_a_probe_readies_its_hosts_and_lists_its_flows_not_started(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    calls = len(driver.calls)
    before = respec(store, "testdata/blueprint/three-node-probed.json")
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    verifier, _ = seeded(driver, "testdata/blueprint/three-node-probed.json")
    asyncio.run(make(store, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))

    (run,) = steps(store)
    record = assert_stepped(store, before, run)
    hosts = ["n1-loop-a", "n1-loop-b"]
    assert seen(store, run.id) == UP_TO_APPLY + pairs("ready", hosts) + push_events([], DEVICES) + WAITED
    target = record.status.bundle_id
    assert holds(record) == {"n1": target, "n1-loop-a": None, "n1-loop-b": None, "n2": target, "n3": target}
    assert ready.calls == [] and pusher.calls == []
    assert [c for c in driver.calls[calls:] if c[0] != "exec"] == [
        ("admit", "t", "held"), ("plan", "t"), ("changes", "t"), ("apply", "t"), ("inspect", "t")]
    assert run.verdict is not None and run.verdict.wait is not None and run.verdict.wait.outcome == "settled"
    assert run.verdict.loss == (Loss(probe="n1-loop", from_="a", outcome="not_started"),
                                Loss(probe="n1-loop", from_="b", outcome="not_started"))


def test_a_step_removing_a_probe_lists_no_flow_for_it(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver, "testdata/blueprint/three-node-probed.json")
    before = respec(store, "testdata/blueprint/three-node.json")
    verifier, _ = seeded(driver, "testdata/blueprint/three-node.json")
    asyncio.run(make(store, driver, verifier=verifier).reconcile("t"))

    (run,) = steps(store)
    record = assert_stepped(store, before, run)
    assert seen(store, run.id) == UP_TO_APPLY + push_events([], DEVICES) + WAITED
    assert sorted(holds(record)) == DEVICES and sorted(driver.labs["t"]) == DEVICES
    assert run.verdict is not None and run.verdict.loss == ()


def test_a_step_adding_a_node_readies_and_pushes_it_alone(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver, "testdata/blueprint/steps/two-node.json")
    before = respec(store, "testdata/blueprint/three-node.json")
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    verifier, _ = seeded(driver, "testdata/blueprint/three-node.json")
    asyncio.run(make(store, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))

    (run,) = steps(store)
    record = assert_stepped(store, before, run)
    assert seen(store, run.id) == UP_TO_APPLY + pairs("ready", ["n3"]) + push_events(["n3"], DEVICES) + WAITED
    assert [n for n, _ in ready.calls] == ["n3"] and [n for n, _ in pusher.calls] == ["n3"]
    assert holds(record) == dict.fromkeys(DEVICES, record.status.bundle_id)
    assert [n.incarnation for n in record.status.nodes] == ["boot-1", "boot-1", "boot-2"]
    assert len({n.address for n in record.status.nodes}) == 3


def renamed_n3() -> dict[str, Any]:
    """`three-node` with `n3` replaced by `n4`, cabled where `n3` was: a step to it removes a node and adds one."""
    doc = doc_of("testdata/blueprint/three-node.json")
    for device in doc["network"]["devices"]:
        if device["name"] == "n3":
            device["name"] = "n4"
    for link in doc["network"]["links"]:
        for end in (link["a"], link["b"]):
            if end["device"] == "n3":
                end["device"] = "n4"
    return doc


def test_a_step_removing_a_node_and_adding_another_readies_and_pushes_the_added_alone(store: LocalStore) -> None:
    driver = FakeDriver()
    ran = {n.name: n for n in ready_twin(store, driver).status.nodes}
    doc = renamed_n3()
    blueprint_id, _ = store.put_blueprint(doc)
    before = respec(store, blueprint_id=blueprint_id)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    verifier, _ = seeded(driver, doc)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))

    (run,) = steps(store)
    record = assert_stepped(store, before, run)
    kept = ["n1", "n2", "n4"]
    assert seen(store, run.id) == UP_TO_APPLY + pairs("ready", ["n4"]) + push_events(["n4"], kept) + WAITED
    assert [n for n, _ in ready.calls] == ["n4"] and [n for n, _ in pusher.calls] == ["n4"]
    assert [(n.name, n.incarnation) for n in record.status.nodes] == [("n1", "boot-1"), ("n2", "boot-1"),
                                                                       ("n4", "boot-2")]
    # n4 took the address n3 left, yet holds nothing of n3's: what a node held is carried by its name.
    (n4,) = [n for n in record.status.nodes if n.name == "n4"]
    assert n4.address == ran["n3"].address
    assert holds(record) == dict.fromkeys(kept, record.status.bundle_id) and sorted(driver.labs["t"]) == kept


def test_a_step_recreating_a_node_under_allow_restart_readies_and_pushes_that_node_alone(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    driver.recreates = {"n3"}
    before = respec(store, "testdata/blueprint/steps/three-node-n3-eos.json", allow_restart=True)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    verifier, _ = seeded(driver, "testdata/blueprint/steps/three-node-n3-eos.json")
    asyncio.run(make(store, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))

    (run,) = steps(store)
    record = assert_stepped(store, before, run)
    # n3's incarnation moved, so its hold was voided at applied: it alone is readied and pushed.
    assert seen(store, run.id) == UP_TO_APPLY + pairs("ready", ["n3"]) + push_events(["n3"], DEVICES) + WAITED
    assert [n for n, _ in ready.calls] == ["n3"] and [n for n, _ in pusher.calls] == ["n3"]
    assert [(n.name, n.incarnation) for n in record.status.nodes] == [("n1", "boot-1"), ("n2", "boot-1"),
                                                                       ("n3", "boot-2")]
    assert holds(record) == dict.fromkeys(DEVICES, record.status.bundle_id)


def test_a_step_changing_one_configuration_pushes_that_node_alone(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    edited = edited_n1()
    blueprint_id, _ = store.put_blueprint(edited)
    before = respec(store, blueprint_id=blueprint_id)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    verifier, _ = seeded(driver, edited)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))

    (run,) = steps(store)
    record = assert_stepped(store, before, run)
    assert seen(store, run.id) == UP_TO_APPLY + push_events(["n1"], DEVICES) + WAITED
    assert ready.calls == []
    assert record.status.bundle_id is not None
    assert pusher.calls == [("n1", store.get_bundle(record.status.bundle_id)["configs/n1.cfg"].decode())]
    assert holds(record) == dict.fromkeys(DEVICES, record.status.bundle_id)


def test_a_step_from_a_configuration_to_none_pushes_nothing_and_the_node_holds_the_target(
    store: LocalStore,
) -> None:
    """D-048: `n2` loses its configuration, so it is unmanaged; no node is pushed, and every one
    holds the target bundle."""
    driver = FakeDriver()
    ready_twin(store, driver)
    before = respec(store, "testdata/blueprint/three-node-unmanaged.json")
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    verifier, _ = seeded(driver, "testdata/blueprint/three-node-unmanaged.json")
    asyncio.run(make(store, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))

    (run,) = steps(store)
    record = assert_stepped(store, before, run)
    assert seen(store, run.id) == UP_TO_APPLY + push_events([], DEVICES) + WAITED
    assert ready.calls == [] and pusher.calls == []
    assert holds(record) == dict.fromkeys(DEVICES, record.status.bundle_id)


def test_a_wait_that_never_settles_expires_with_a_warning_and_the_step_ends_stepped(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    before = respec(store, "testdata/blueprint/steps/two-node.json")
    verifier, reader = seeded(driver, "testdata/blueprint/steps/two-node.json")
    reader.facts[("t", "n1")] = {}  # n1 reports nothing: every node read, and its assertions fail
    asyncio.run(make(store, driver, verifier=verifier, step_wait_s=0.05).reconcile("t"))

    (run,) = steps(store)
    assert run.verdict is not None and run.verdict.wait is not None
    assert (run.verdict.operation, run.verdict.status) == ("step", "ok")
    assert run.verdict.wait.outcome == "expired" and run.verdict.wait.after_s >= 0.05
    assert run.verdict.counts is not None and run.verdict.counts.failed > 0
    (expired,) = [f for f in run.verdict.findings if f.rule == "step.wait.expired"]
    assert (expired.severity, expired.object) == ("warning", "t")
    assert "0.05s" in expired.message and "nonconforming" in expired.message
    assert any(f.rule.startswith("verify.") and f.severity == "error" for f in run.verdict.findings)
    verify_done = [e for e in store.events(run.id) if (e.phase, e.outcome) == ("verify", "done")]
    assert [e.rule for e in verify_done] == ["step.wait.expired"]
    assert seen(store, run.id) == UP_TO_APPLY + push_events([], ["n1", "n2"]) + WAITED
    record = store.get_twin("t")
    assert record.status.last_step is not None and record.status.last_step.outcome == "stepped"
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert record.status.observed_generation == before.generation == 2


class HeldAfterFirst(Verifier):
    """A verifier over the target's facts with `n1` faulty at the first verify only: reporting
    nothing (`nonconforming`) or unread (`failed`). From the second on the twin has settled."""

    def __init__(self, driver: FakeDriver, target: str, fault: str) -> None:
        _, self.fake = seeded(driver, target)
        super().__init__(PLATFORMS, PROBES, Provider(ENVIRON), reader=self.fake)
        self.fixed = dict(self.fake.facts)
        if fault == "nonconforming":
            self.fake.facts[("t", "n1")] = {}
        else:
            self.fake.unreadable.add(("t", "n1"))
        self.statuses: list[str] = []

    async def verify(self, record: TwinRecord, manifest: bundle.Manifest, bundle_id: str, exec_fn: ExecFn) -> Verdict:
        verdict = await super().verify(record, manifest, bundle_id, exec_fn)
        self.statuses.append(verdict.status)
        self.fake.facts, self.fake.unreadable = dict(self.fixed), set()
        return verdict


@pytest.mark.parametrize("fault", ["nonconforming", "failed"])
def test_a_wait_tries_verify_again_until_it_holds_and_settles(store: LocalStore, fault: str) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    before = respec(store, "testdata/blueprint/steps/two-node.json")
    verifier = HeldAfterFirst(driver, "testdata/blueprint/steps/two-node.json", fault)
    asyncio.run(make(store, driver, verifier=verifier).reconcile("t"))

    (run,) = steps(store)
    assert_stepped(store, before, run)
    assert verifier.statuses == [fault, "ok"]  # a node unread is not held either: it is read again
    assert run.verdict is not None and run.verdict.wait is not None
    assert run.verdict.wait.outcome == "settled"
    assert run.verdict.wait.after_s >= 0.01  # it paused `verify_poll_s` between its two tries
    assert run.verdict.counts is not None and run.verdict.counts.failed == 0
    assert not any(f.rule == "step.wait.expired" or f.severity == "error" for f in run.verdict.findings)
    assert all(e.rule is None for e in store.events(run.id))


def test_a_spec_written_during_a_step_is_observed_by_the_next_pass_which_steps_to_it(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    edited = edited_n1()
    blueprint_id, _ = store.put_blueprint(edited)
    before = respec(store, blueprint_id=blueprint_id)
    inner = fake_push(driver=driver)
    written: list[TwinRecord] = []

    async def writes_a_spec(address: str, package: Any, config: str, credential: Any) -> Any:
        if not written:  # a client's PUT while the step pushes n1: the generation moves, the run's target does not
            assert store.get_twin("t").status.generation_in_flight == 2
            written.append(respec(store, "testdata/blueprint/steps/two-node.json"))
        return await inner(address, package, config, credential)

    verifier, reader = seeded(driver, edited)
    r = make(store, driver, pusher=writes_a_spec, verifier=verifier)  # type: ignore[arg-type]
    asyncio.run(r.reconcile("t"))

    first = steps(store)[0]
    stepped = assert_stepped(store, before, first)
    assert [w.generation for w in written] == [3] and stepped.generation == 3
    assert stepped.status.observed_generation == 2  # the generation the run was taken under
    reader.seed("t", compiler.compile(blueprint.decode(doc_of("testdata/blueprint/steps/two-node.json")), PLATFORMS,
                                      PROBES).manifest, PLATFORMS)
    asyncio.run(r.reconcile("t"))

    again, second = steps(store)
    assert again.id == first.id
    record = assert_stepped(store, written[0], second)
    assert record.status.observed_generation == record.generation == 3
    assert record.status.last_step is not None and record.status.last_step.from_ == stepped.status.bundle_id


@pytest.mark.parametrize("allowed", [False, True], ids=["refused", "allowed"])
def test_killed_after_planned_a_step_plans_again_and_refuses_again_before_it_applies(
    killing: KillingStore, allowed: bool
) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    driver.recreates = {"n3"}
    before = respec(killing, "testdata/blueprint/steps/three-node-n3-eos.json", allow_restart=allowed)
    verifier, _ = seeded(driver, "testdata/blueprint/steps/three-node-n3-eos.json")
    killing.kill_at = "planned"
    killed(make(killing, driver, verifier=verifier))
    (run,) = steps(killing)
    planned = killing.get_twin("t").status.last_step
    assert planned is not None and planned.phase == "planned"

    calls = len(driver.calls)
    asyncio.run(make(killing, driver, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    # The refusals follow `plan done`: a resume after `planned` plans again, purely, and refuses again. The killed
    # plan's end was never written.
    replanned = [*UP_TO_PLAN[:-1], ("plan", "started", None), ("plan", "done", None)]
    if not allowed:
        assert_refused(killing, before, run, "step.restart.required")
        assert seen(killing, run.id) == replanned
        assert driver.calls[calls:] == [("plan", "t"), ("changes", "t")]
        return
    record = assert_stepped(killing, before, run)  # its deployment is the one filed before the kill: the same id
    assert seen(killing, run.id) == [*replanned, *UP_TO_APPLY[6:], *pairs("ready", ["n3"]),
                                     *push_events(["n3"], DEVICES), *WAITED]
    assert driver.calls[calls:calls + 4] == [("plan", "t"), ("changes", "t"), ("apply", "t"), ("inspect", "t")]
    assert run.verdict is not None and run.verdict.subject.deployment_id == record.status.deployment_id


# A step's resumption (D-050): a Ready `three-node` twin stepped to `three-node-probed`, which adds a probe and its two
# hosts and changes no device's configuration, killed after one recorded phase; a fresh Reconciler over the same
# store, driver and lab is the restarted core.

PROBED = "testdata/blueprint/three-node-probed.json"
HOSTS = ["n1-loop-a", "n1-loop-b"]
NOT_STARTED = (Loss(probe="n1-loop", from_="a", outcome="not_started"),
               Loss(probe="n1-loop", from_="b", outcome="not_started"))
"""The flows a step to `three-node-probed` lists (D-051)."""
AFTER_APPLY: list[Seen] = pairs("ready", HOSTS) + push_events([], DEVICES) + WAITED
"""The step's events after its apply, unkilled: the two hosts readied, each device marked holding without a push."""
APPLY_BEGUN: list[Seen] = [*UP_TO_PLAN, ("apply", "started", None), ("plan", "started", None), ("plan", "done", None),
                           ("apply", "started", None)]
"""A step killed during its apply and resumed into it: the kill left `apply started` with no end, and the resume,
after `planned`, plans again before it applies."""


def killed_stepping(
    killing: KillingStore,
    driver: FakeDriver,
    *,
    kill_at: str | None = None,
    fail_after: str | None = None,
    allow_restart: bool = False,
) -> tuple[TwinRecord, Run, Verifier]:
    """A Ready `three-node` twin stepped toward `three-node-probed` and killed once `kill_at` was
    recorded, or once the driver's `fail_after` call took effect: the record as the new spec left
    it, the step's run, and a verifier holding the target's facts."""
    ready_twin(killing, driver)
    before = respec(killing, PROBED, allow_restart=allow_restart)
    verifier, _ = seeded(driver, PROBED)
    killing.kill_at, driver.fail_after = kill_at, fail_after
    killed(make(killing, driver, verifier=verifier))
    (run,) = steps(killing)
    return before, run, verifier


def runtime_calls(driver: FakeDriver, since: int) -> list[tuple[str, ...]]:
    """The driver's calls from `since` on, `exec` left out: a host's readiness and verify's bursts run through it."""
    return [c for c in driver.calls[since:] if c[0] != "exec"]


@pytest.mark.parametrize("phase", ["compiled", "admitted", "planned"])
def test_a_step_killed_before_its_apply_began_resumes_and_applies_plainly_with_no_probe(
    killing: KillingStore, phase: str
) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, kill_at=phase)
    record = killing.get_twin("t")
    assert record.status.last_step is not None and record.status.last_step.phase == phase
    assert record.status.phase == "pushed" and sorted(driver.labs["t"]) == DEVICES  # nothing touched yet

    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    record = assert_stepped(killing, before, run)
    # No inspect before the apply and no readiness call: the run's events show no apply begun, so the lab is not probed.
    admitted = [("admit", "t", "held")] if phase == "compiled" else []
    assert runtime_calls(driver, calls) == [*admitted, ("plan", "t"), ("changes", "t"), ("apply", "t"),
                                            ("inspect", "t")]
    assert ready.calls == [] and pusher.calls == []
    # The killed phase's end was never written; after `planned` the target is planned again, so its plan pair repeats.
    cut, again = {"compiled": (1, 2), "admitted": (3, 4), "planned": (5, 4)}[phase]
    events = resumed(killing, run.id, "step")
    assert events == [*UP_TO_APPLY[:cut], *UP_TO_APPLY[again:], *AFTER_APPLY]
    assert events.count(("apply", "started", None)) == 1
    assert record.status.bundle_id is not None and before.status.allocation is not None
    manifest = bundle.decode(json.loads(killing.get_bundle(record.status.bundle_id)["manifest.json"]))
    planned = driver.plan(manifest, record.status.bundle_id, PLATFORMS, PROBES, "t", before.status.allocation)
    assert record.status.deployment_id == planned.deployment.id  # the plan is pure: the same deployment


def test_a_step_killed_during_its_apply_probes_the_lab_and_applies_plainly_again_when_every_node_answers(
    killing: KillingStore,
) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, fail_after="apply")
    record = killing.get_twin("t")
    assert record.status.last_step is not None and record.status.last_step.phase == "planned"
    assert seen(killing, run.id)[-1] == ("apply", "started", None)
    assert sorted(driver.labs["t"]) == sorted(DEVICES + HOSTS)  # the apply took effect: the hosts run

    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    record = assert_stepped(killing, before, run)
    assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("inspect", "t"), ("apply", "t"),
                                            ("inspect", "t")]
    # The probe asks every device node; none's incarnation moved, so none is readied after the apply.
    assert [node for node, _ in ready.calls] == DEVICES and pusher.calls == []
    events = resumed(killing, run.id, "step")
    assert events == [*APPLY_BEGUN, ("apply", "done", None), *AFTER_APPLY]
    assert (events.count(("apply", "started", None)), events.count(("apply", "done", None))) == (2, 1)
    assert [(n.name, n.incarnation) for n in record.status.nodes] == [
        ("n1", "boot-1"), ("n1-loop-a", "boot-2"), ("n1-loop-b", "boot-2"), ("n2", "boot-1"), ("n3", "boot-1")]
    assert holds(record) == {**dict.fromkeys(DEVICES, record.status.bundle_id), **dict.fromkeys(HOSTS)}


def test_a_step_killed_during_its_apply_with_a_node_silent_reconfigures_under_allow_restart(
    killing: KillingStore,
) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, fail_after="apply", allow_restart=True)
    driver.silent.add(("t", "n3"))  # its transport stopped answering while the core was down

    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    record = assert_stepped(killing, before, run)
    assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("inspect", "t"),
                                            ("apply", "t", "reconfigure"), ("inspect", "t")]
    # The probe stops at n3; the reconfigure made every node anew, so every one is readied and pushed again.
    assert [node for node, _ in ready.calls] == DEVICES + DEVICES
    assert [node for node, _ in pusher.calls] == DEVICES
    assert {n.incarnation for n in record.status.nodes} == {"boot-3"}
    assert resumed(killing, run.id, "step") == [*APPLY_BEGUN, ("apply", "done", None),
                                                *pairs("ready", DEVICES + HOSTS), *pairs("push", DEVICES), *WAITED]
    assert holds(record) == {**dict.fromkeys(DEVICES, record.status.bundle_id), **dict.fromkeys(HOSTS)}


@pytest.mark.parametrize("lost", [False, True], ids=["recorded", "record lost"])
def test_a_step_killed_during_its_apply_with_a_node_silent_and_no_restart_allowed_ends_diverged(
    killing: KillingStore, lost: bool
) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, fail_after="apply")
    driver.silent.add(("t", "n3"))
    running = killing.get_twin("t").status.last_step

    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    if lost:  # the run's end written and the record's last write lost: the next pass records it from the run
        killing.kill_at = "ended"
        killed(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier))
        assert killing.get_twin("t").status.run_id == run.id and killing.get_run(run.id).state == "ended"
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    assert run.state == "ended" and run.verdict is not None
    assert (run.verdict.operation, run.verdict.status) == ("step", "diverged")
    (finding,) = run.verdict.findings
    assert (finding.rule, finding.severity, finding.object) == ("step.node.silent", "error", "n3")
    assert before.status.bundle_id is not None
    assert f"n1, n2, n3 hold {before.status.bundle_id}" in finding.message
    assert "after planned" in finding.message and "allow_restart" in finding.message
    assert "As the record knows" in finding.message  # before applied, its nodes are the running twin's
    assert resumed(killing, run.id, "step") == [*APPLY_BEGUN, ("apply", "failed", None)]
    assert killing.events(run.id)[-1].rule == "step.node.silent"
    # Neither applied again nor torn down: the lab is what the killed apply made of it.
    assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("inspect", "t")]
    assert [node for node, _ in ready.calls] == DEVICES and pusher.calls == []
    assert sorted(driver.labs["t"]) == sorted(DEVICES + HOSTS)
    record = killing.get_twin("t")
    status = record.status
    for kind, value in (("Ready", "False"), ("Stepping", "False"), ("Diverged", "True")):
        assert (condition_of(record, kind).status, condition_of(record, kind).reason) == (value, "step.node.silent")
    assert running is not None and status.last_step == dataclasses.replace(running, outcome="diverged")
    assert status.observed_generation == record.generation == before.generation == 2
    assert status.run_id is None and status.generation_in_flight is None
    # `applied` was never recorded: the record still names what the twin ran, and what each node held.
    assert (status.phase, status.blueprint_id, status.bundle_id, status.deployment_id, status.nodes) == (
        before.status.phase, before.status.blueprint_id, before.status.bundle_id, before.status.deployment_id,
        before.status.nodes)


@pytest.mark.parametrize("allowed", [True, False], ids=["allow_restart", "no restart"])
def test_a_transient_failure_in_the_resumes_probe_leaves_the_apply_begun_so_the_next_pass_probes_again(
    killing: KillingStore, allowed: bool
) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, fail_after="apply", allow_restart=allowed)
    driver.silent.add(("t", "n3"))
    driver.fail_inspect_once = True  # the probe's inspect blips: `apply failed`, and the twin is queued again
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)

    async def scenario() -> None:
        r = make(killing, driver, ready=ready, pusher=pusher, verifier=verifier)
        await r.reconcile("t")
        assert r.backoff == {"t": 1.0} and killing.get_run(run.id).state == "running"
        assert seen(killing, run.id) == [*APPLY_BEGUN, ("apply", "failed", None)]
        calls = len(driver.calls)
        await r.reconcile("t")
        # A transient `apply failed` is no end: the apply may have partly landed, so the lab is probed again.
        applied = [("apply", "t", "reconfigure"), ("inspect", "t")] if allowed else []
        assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("inspect", "t"), *applied]

    asyncio.run(scenario())
    run = killing.get_run(run.id)
    again = [*APPLY_BEGUN, ("apply", "failed", None), ("plan", "started", None), ("plan", "done", None),
             ("apply", "started", None)]
    assert "t" in driver.labs and ("destroy", "t") not in driver.calls
    if allowed:
        record = assert_stepped(killing, before, run)
        assert {n.incarnation for n in record.status.nodes} == {"boot-3"}
        assert [node for node, _ in ready.calls] == DEVICES + DEVICES and [node for node, _ in pusher.calls] == DEVICES
        assert resumed(killing, run.id, "step") == [*again, ("apply", "done", None), *pairs("ready", DEVICES + HOSTS),
                                                    *pairs("push", DEVICES), *WAITED]
        return
    assert run.verdict is not None and run.verdict.status == "diverged"
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("step.node.silent", "n3")]
    assert resumed(killing, run.id, "step") == [*again, ("apply", "failed", None)]
    assert killing.events(run.id)[-1].rule == "step.node.silent"
    assert [node for node, _ in ready.calls] == DEVICES and pusher.calls == []
    record = killing.get_twin("t")
    for kind, value in (("Ready", "False"), ("Stepping", "False"), ("Diverged", "True")):
        assert (condition_of(record, kind).status, condition_of(record, kind).reason) == (value, "step.node.silent")
    assert record.status.last_step is not None and record.status.last_step.outcome == "diverged"


@pytest.mark.parametrize("allowed", [False, True], ids=["no restart", "allow_restart"])
def test_with_reapply_a_step_resumed_into_its_apply_applies_again_and_never_reconfigures(
    killing: KillingStore, allowed: bool
) -> None:
    driver = FakeDriver(reapply=True)
    before, run, verifier = killed_stepping(killing, driver, fail_after="apply", allow_restart=allowed)
    driver.silent.add(("t", "n3"))  # without reapply the probe finds it silent: a reconfigure, or diverged

    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    record = assert_stepped(killing, before, run)
    # Applied again plainly, with no inspect before it (D-068). On clabernetes a reconfigure writes no hot-add
    # annotation, so one cut short before its pod deletions and resumed plainly would leave a port added after boot
    # unarrived: a resume there never reconfigures.
    assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("apply", "t"), ("inspect", "t")]
    assert ready.calls == [] and pusher.calls == []  # no probe, and no device node's incarnation moved
    assert [(n.name, n.incarnation) for n in record.status.nodes] == [
        ("n1", "boot-1"), ("n1-loop-a", "boot-2"), ("n1-loop-b", "boot-2"), ("n2", "boot-1"), ("n3", "boot-1")]
    assert run.verdict is not None and all(f.rule != "step.node.silent" for f in run.verdict.findings)
    events = resumed(killing, run.id, "step")
    assert events == [*APPLY_BEGUN, ("apply", "done", None), *AFTER_APPLY]
    assert (events.count(("apply", "started", None)), events.count(("apply", "done", None))) == (2, 1)


def test_a_step_killed_after_applied_resumes_with_no_second_apply_readies_the_hosts_and_skips_the_pushes(
    killing: KillingStore,
) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, kill_at="applied")
    record = killing.get_twin("t")
    assert record.status.last_step is not None and record.status.phase == record.status.last_step.phase == "applied"
    assert record.status.bundle_id == record.status.last_step.to  # the record moved to the target at applied

    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    record = assert_stepped(killing, before, run)
    assert runtime_calls(driver, calls) == []  # no inspect, no apply: the record says applied
    assert [c[2] for c in driver.calls[calls:]][:2] == HOSTS  # each host's readiness, read inside it
    assert ready.calls == [] and pusher.calls == []
    assert resumed(killing, run.id, "step") == [*UP_TO_APPLY[:-1], *AFTER_APPLY]
    assert holds(record) == {**dict.fromkeys(DEVICES, record.status.bundle_id), **dict.fromkeys(HOSTS)}


def test_a_step_killed_after_pushed_resumes_with_the_wait_and_the_flows(killing: KillingStore) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, kill_at="pushed")
    record = killing.get_twin("t")
    assert record.status.last_step is not None and record.status.phase == record.status.last_step.phase == "pushed"
    assert all(record.status.bundle_id == h for n, h in holds(record).items() if n in DEVICES)

    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    assert_stepped(killing, before, run)  # its verdict carries the wait, run by the resume
    assert runtime_calls(driver, calls) == [] and ready.calls == [] and pusher.calls == []
    assert resumed(killing, run.id, "step") == UP_TO_APPLY + AFTER_APPLY  # the push has no phase pair: none was cut
    assert run.verdict is not None and run.verdict.wait is not None and run.verdict.wait.outcome == "settled"


def test_a_step_killed_after_verified_resumes_with_the_flows_alone(killing: KillingStore) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, kill_at="verified")

    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    # The pass that waited was killed: this one runs `flows` alone, and its verdict has no wait and no counts.
    assert_stepped(killing, before, run, waited=False)
    assert driver.calls[calls:] == [] and ready.calls == [] and pusher.calls == []
    assert resumed(killing, run.id, "step") == [*UP_TO_APPLY, *AFTER_APPLY[:-3], *AFTER_APPLY[-2:]]
    assert run.verdict is not None and run.verdict.findings == ()
    assert run.verdict.loss == NOT_STARTED


def test_a_step_killed_after_its_last_phase_resumes_to_its_end_and_lists_its_flows(killing: KillingStore) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, kill_at="flows")

    calls = len(driver.calls)
    asyncio.run(make(killing, driver, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    # Every phase had run: the resume runs none, and ends the step. The pass that waited was killed, so the verdict
    # has no wait and no counts; its flows are listed all the same, read from the target (D-051).
    assert_stepped(killing, before, run, waited=False)
    assert run.verdict is not None and run.verdict.loss == NOT_STARTED
    assert driver.calls[calls:] == []
    assert resumed(killing, run.id, "step") == [*UP_TO_APPLY, *AFTER_APPLY[:-1]]  # the killed flows' end never written


def test_a_step_killed_after_its_run_ended_ok_the_next_pass_completes_the_record(killing: KillingStore) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, kill_at="ended")
    record = killing.get_twin("t")
    assert killing.get_run(run.id).state == "ended" and record.status.run_id == run.id
    assert condition_of(record, "Stepping").status == "True" and record.status.observed_generation == 1

    calls, events = len(driver.calls), len(killing.events(run.id))
    asyncio.run(make(killing, driver, verifier=verifier).reconcile("t"))
    assert_stepped(killing, before, killing.get_run(run.id))
    assert driver.calls[calls:] == [] and len(killing.events(run.id)) == events and steps(killing) == [run]


# A step cancelled or failed (D-050, D-029): before its apply began it ends cancelled with the twin as it ran; from
# the apply on it ends diverged with `step.diverged`, and nothing is torn down. A deletion then destroys as any twin's.

CANCELLED: list[Seen] = [("cancel", "started", None), ("cancel", "done", None)]


class HookedDriver(FakeDriver):
    """A fake driver that runs `after[call]` once that call (`admit` or `changes`) has answered, once: a client
    acting meanwhile, as one that cancels the run."""

    def __init__(self) -> None:
        super().__init__()
        self.after: dict[str, Callable[[], None]] = {}

    async def admit(self, *args: Any, **kwargs: Any) -> Any:
        answer = await super().admit(*args, **kwargs)
        self._hook("admit")
        return answer

    def changes(self, *args: Any, **kwargs: Any) -> Any:
        answer = super().changes(*args, **kwargs)
        self._hook("changes")
        return answer

    def _hook(self, call: str) -> None:
        hook = self.after.pop(call, None)
        if hook is not None:
            hook()


def cancels(store: LocalStore) -> Callable[[], None]:
    """A hook that marks the twin's step run cancelling, as the API's cancel does."""
    return lambda: mark_cancelling(store, the_run(store, "step").id)


class CancellingReady(FakeReady):
    """A readiness wait that marks the twin's step run cancelling at its first call, then answers as `FakeReady`."""

    def __init__(self, store: LocalStore, driver: FakeDriver) -> None:
        super().__init__(None, None, driver)
        self.cancelling = store

    async def __call__(
        self, address: str, package: platform_package.PlatformPackage, credential: Credential, *,
        timeout_s: float | None = None,
    ) -> float:
        if not self.calls:
            mark_cancelling(self.cancelling, the_run(self.cancelling, "step").id)
        return await super().__call__(address, package, credential, timeout_s=timeout_s)


class CancellingVerifier(Verifier):
    """A verifier over the facts of `t` built to `target` with `n1` reporting nothing, so verify never holds, that
    marks the twin's step run cancelling at its first verify: a cancel landing during the step's wait."""

    def __init__(self, store: LocalStore, driver: FakeDriver, target: str) -> None:
        _, fake = seeded(driver, target)
        fake.facts[("t", "n1")] = {}
        super().__init__(PLATFORMS, PROBES, Provider(ENVIRON), reader=fake)
        self.cancelling = store
        self.tries = 0

    async def verify(self, record: TwinRecord, manifest: bundle.Manifest, bundle_id: str, exec_fn: ExecFn) -> Verdict:
        self.tries += 1
        if self.tries == 1:
            mark_cancelling(self.cancelling, the_run(self.cancelling, "step").id)
        return await super().verify(record, manifest, bundle_id, exec_fn)


async def cancelled_during_apply(store: LocalStore, driver: FakeDriver, r: Reconciler) -> None:
    """A pass of the step, cancelled while the driver's apply has not answered."""
    calls = len(driver.calls)
    driver.block = "apply"
    pass_ = asyncio.create_task(r.reconcile("t"))
    await until(lambda: ("apply", "t") in driver.calls[calls:])
    mark_cancelling(store, the_run(store, "step").id)
    await asyncio.wait_for(pass_, timeout=5)
    driver.block = None


def assert_step_cancelled(store: LocalStore, before: TwinRecord, run: Run, phase: str) -> TwinRecord:
    """The step was cancelled before its apply began, `before` being the record as the new spec left it and `phase`
    the last the step recorded: the run ended `failed` with `run.cancelled` saying so, its subject the step's target;
    `last_step` cancelled at `phase`, Ready and Stepping False for `run.cancelled`, no Diverged condition, the
    observed generation caught up, no run in flight, and the record still describing what the twin runs."""
    assert_cancelled(run)
    assert run.verdict is not None and run.verdict.operation == "step"
    assert run.verdict.findings[0].message == ("The step was cancelled before its apply began; the twin runs what it "
                                               "ran.")
    assert seen(store, run.id)[-2:] == CANCELLED and store.events(run.id)[-1].rule == "run.cancelled"
    record = store.get_twin("t")
    status = record.status
    assert status.last_step is not None
    assert (status.last_step.outcome, status.last_step.phase, status.last_step.run_id) == ("cancelled", phase, run.id)
    assert run.verdict.subject.bundle_id == status.last_step.to != before.status.bundle_id  # the step's target
    assert run.verdict.subject.blueprint_id == before.spec.blueprint_id
    for kind in ("Ready", "Stepping"):
        assert (condition_of(record, kind).status, condition_of(record, kind).reason) == ("False", "run.cancelled")
    assert [c.type for c in status.conditions if c.type == "Diverged"] == []
    assert status.observed_generation == record.generation == before.generation
    assert status.run_id is None and status.generation_in_flight is None
    assert (status.phase, status.blueprint_id, status.bundle_id, status.deployment_id, status.allocation,
            status.nodes) == (before.status.phase, before.status.blueprint_id, before.status.bundle_id,
                              before.status.deployment_id, before.status.allocation, before.status.nodes)
    return record


def assert_diverged(store: LocalStore, before: TwinRecord, run: Run, phase: str) -> TwinRecord:
    """The step ended `diverged` with `step.diverged`, `before` being the record as the new spec left it and `phase`
    the last the step recorded: Diverged True, Ready and Stepping False, each for `step.diverged`; `last_step`
    diverged at `phase`, naming the run; the observed generation caught up and no run in flight."""
    assert run.state == "ended" and run.verdict is not None
    assert (run.verdict.operation, run.verdict.status) == ("step", "diverged")
    record = store.get_twin("t")
    status = record.status
    for kind, value in (("Ready", "False"), ("Stepping", "False"), ("Diverged", "True")):
        assert (condition_of(record, kind).status, condition_of(record, kind).reason) == (value, "step.diverged")
    assert status.last_step is not None and before.status.bundle_id is not None
    assert (status.last_step.outcome, status.last_step.phase, status.last_step.run_id, status.last_step.from_) == (
        "diverged", phase, run.id, before.status.bundle_id)
    assert status.observed_generation == record.generation == before.generation
    assert status.run_id is None and status.generation_in_flight is None
    return record


def diverged_finding(run: Run) -> Finding:
    """The verdict's one `step.diverged` finding, an error about the twin."""
    assert run.verdict is not None
    (finding,) = [f for f in run.verdict.findings if f.rule == "step.diverged"]
    assert (finding.severity, finding.object) == ("error", "t")
    assert "the twin is left as it stands, diverged, and accepts only deletion" in finding.message
    return finding


def assert_unmoved(record: TwinRecord, before: TwinRecord) -> None:
    """`applied` was never recorded: the record still names what the twin ran, and what each node held."""
    assert (record.status.phase, record.status.blueprint_id, record.status.bundle_id, record.status.deployment_id,
            record.status.nodes) == (before.status.phase, before.status.blueprint_id, before.status.bundle_id,
                                     before.status.deployment_id, before.status.nodes)


def test_a_step_cancelled_during_admit_ends_cancelled_and_leaves_the_twin_as_it_ran(store: LocalStore) -> None:
    driver = HookedDriver()
    ready_twin(store, driver)
    calls = len(driver.calls)
    before = respec(store, "testdata/blueprint/steps/two-node.json")
    driver.after["admit"] = cancels(store)
    asyncio.run(make(store, driver).reconcile("t"))

    (run,) = steps(store)
    assert_step_cancelled(store, before, run, "admitted")
    assert seen(store, run.id) == [*UP_TO_PLAN[:4], *CANCELLED]
    assert driver.calls[calls:] == [("admit", "t", "held")]  # nothing planned, applied or destroyed
    assert sorted(driver.labs["t"]) == DEVICES


def test_a_step_cancelled_while_its_resume_plans_again_ends_cancelled_before_its_apply(killing: KillingStore) -> None:
    driver = HookedDriver()
    before, run, verifier = killed_stepping(killing, driver, kill_at="planned")
    driver.after["changes"] = cancels(killing)  # the re-plan is pure: the cancel is read before the apply begins
    calls = len(driver.calls)
    asyncio.run(make(killing, driver, verifier=verifier).reconcile("t"))

    run = killing.get_run(run.id)
    assert_step_cancelled(killing, before, run, "planned")
    assert resumed(killing, run.id, "step") == [*UP_TO_PLAN[:-1], ("plan", "started", None), ("plan", "done", None),
                                                *CANCELLED]
    assert driver.calls[calls:] == [("plan", "t"), ("changes", "t")]
    assert sorted(driver.labs["t"]) == DEVICES


def test_a_step_cancelled_during_its_apply_ends_diverged_and_tears_nothing_down(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    before = respec(store, "testdata/blueprint/steps/two-node.json")
    calls = len(driver.calls)
    asyncio.run(cancelled_during_apply(store, driver, make(store, driver)))

    (run,) = steps(store)
    record = assert_diverged(store, before, run, "planned")
    finding = diverged_finding(run)
    assert run.verdict is not None and run.verdict.findings == (finding,)  # a cancel carries no other finding
    assert "The step was cancelled during apply, after its apply began" in finding.message
    assert "The last phase it recorded is planned" in finding.message
    assert f"As the record knows, n1, n2, n3 hold {before.status.bundle_id}." in finding.message
    assert seen(store, run.id) == [*UP_TO_PLAN, ("apply", "started", None), ("apply", "cancelled", None), *CANCELLED]
    assert store.events(run.id)[-1].rule == "step.diverged"
    assert_unmoved(record, before)
    assert driver.calls[calls:] == [("admit", "t", "held"), ("plan", "t"), ("changes", "t"), ("apply", "t")]
    assert sorted(driver.labs["t"]) == DEVICES


def test_a_step_cancelled_during_its_push_ends_diverged_naming_what_each_node_holds(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    blueprint_id, _ = store.put_blueprint(edited_n1())
    before = respec(store, blueprint_id=blueprint_id)
    calls = len(driver.calls)
    pusher = CancellingPush(store, driver, operation="step")
    asyncio.run(make(store, driver, pusher=pusher).reconcile("t"))

    (run,) = steps(store)
    record = assert_diverged(store, before, run, "ready")
    finding = diverged_finding(run)
    assert run.verdict is not None and run.verdict.findings == (finding,)
    new, old = record.status.bundle_id, before.status.bundle_id
    assert record.status.last_step is not None and new == record.status.last_step.to != old  # moved at applied
    assert "The step was cancelled during push, after its apply began" in finding.message
    assert "The last phase it recorded is ready" in finding.message
    assert f"As the record knows, n1 holds {new}; n2, n3 hold {old}." in finding.message
    assert seen(store, run.id) == [*UP_TO_APPLY, ("push", "started", "n1"), ("push", "done", "n1"), *CANCELLED]
    assert store.events(run.id)[-1].rule == "step.diverged"
    assert holds(record) == {"n1": new, "n2": old, "n3": old}
    assert [node for node, _ in pusher.calls] == ["n1"]
    assert driver.calls[calls:] == [("admit", "t", "held"), ("plan", "t"), ("changes", "t"), ("apply", "t"),
                                    ("inspect", "t")]
    assert sorted(driver.labs["t"]) == DEVICES
    assert run.verdict.subject == Subject(twin="t", run_id=run.id, blueprint_id=blueprint_id, bundle_id=new,
                                          deployment_id=record.status.deployment_id)


@pytest.mark.parametrize("lost", [False, True], ids=["recorded", "record lost"])
def test_a_refused_push_on_a_step_ends_diverged_and_tears_nothing_down(killing: KillingStore, lost: bool) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    blueprint_id, _ = killing.put_blueprint(edited_n1())
    before = respec(killing, blueprint_id=blueprint_id)
    pusher = fake_push(refuse={"n1"}, driver=driver)
    if lost:  # the run's end written and the record's last write lost: the next pass records it from the run
        killing.kill_at = "ended"
        killed(make(killing, driver, pusher=pusher))
        assert killing.get_twin("t").status.run_id == steps(killing)[0].id
    asyncio.run(make(killing, driver, pusher=pusher).reconcile("t"))

    (run,) = steps(killing)
    record = assert_diverged(killing, before, run, "ready")  # not failed, and not cleaned up
    assert run.verdict is not None
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("push.refused", "n1"), ("step.diverged", "t")]
    finding = diverged_finding(run)
    assert "The step failed during push (push.refused), after its apply began" in finding.message
    assert f"As the record knows, n1, n2, n3 hold {before.status.bundle_id}." in finding.message
    assert seen(killing, run.id) == [*UP_TO_APPLY, ("push", "started", "n1"), ("push", "failed", "n1")]
    assert killing.events(run.id)[-1].rule == "push.refused"  # the phase's own failure; the twin's reason is diverged
    assert [node for node, _ in pusher.calls] == ["n1"]
    assert ("destroy", "t") not in driver.calls and sorted(driver.labs["t"]) == DEVICES
    assert record.status.deployment_id is not None and record.status.deployment_id != before.status.deployment_id


def test_a_node_a_step_adds_that_never_answers_ends_the_step_diverged(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver, "testdata/blueprint/steps/two-node.json")
    before = respec(store, "testdata/blueprint/three-node.json")
    ready, pusher = fake_ready({"n1", "n2"}, driver=driver), fake_push(driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher).reconcile("t"))

    (run,) = steps(store)
    record = assert_diverged(store, before, run, "applied")
    assert run.verdict is not None
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("readiness.timeout", "n3"), ("step.diverged", "t")]
    finding = diverged_finding(run)
    assert "The step failed during ready (readiness.timeout), after its apply began" in finding.message
    assert f"As the record knows, n1, n2 hold {before.status.bundle_id}; n3 holds nothing." in finding.message
    assert seen(store, run.id) == [*UP_TO_APPLY, ("ready", "started", "n3"), ("ready", "timed_out", "n3")]
    assert [node for node, _ in ready.calls] == ["n3"] and pusher.calls == []
    assert ("destroy", "t") not in driver.calls and sorted(driver.labs["t"]) == DEVICES
    assert holds(record) == {"n1": before.status.bundle_id, "n2": before.status.bundle_id, "n3": None}


def test_a_step_cancelled_during_its_wait_for_verify_ends_diverged(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    before = respec(store, "testdata/blueprint/steps/two-node.json")
    verifier = CancellingVerifier(store, driver, "testdata/blueprint/steps/two-node.json")
    asyncio.run(make(store, driver, verifier=verifier, step_wait_s=5.0).reconcile("t"))

    (run,) = steps(store)
    record = assert_diverged(store, before, run, "pushed")
    finding = diverged_finding(run)
    assert run.verdict is not None and run.verdict.findings == (finding,)
    assert run.verdict.wait is None  # the wait never ended
    assert "The step was cancelled during verify, after its apply began" in finding.message
    assert f"As the record knows, n1, n2 hold {record.status.bundle_id}." in finding.message
    assert seen(store, run.id) == [*UP_TO_APPLY, *push_events([], ["n1", "n2"]), ("verify", "started", None),
                                   ("verify", "cancelled", None), *CANCELLED]
    assert ("destroy", "t") not in driver.calls and sorted(driver.labs["t"]) == ["n1", "n2"]


def test_a_step_cancelled_during_its_resumes_probe_ends_diverged(killing: KillingStore) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, fail_after="apply")
    calls = len(driver.calls)
    asyncio.run(make(killing, driver, ready=CancellingReady(killing, driver), verifier=verifier).reconcile("t"))

    run = killing.get_run(run.id)
    record = assert_diverged(killing, before, run, "planned")
    finding = diverged_finding(run)
    assert run.verdict is not None and run.verdict.findings == (finding,)
    assert "The step was cancelled during apply, after its apply began" in finding.message
    assert resumed(killing, run.id, "step") == [*APPLY_BEGUN, ("apply", "cancelled", None), *CANCELLED]
    assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("inspect", "t")]
    assert sorted(driver.labs["t"]) == sorted(DEVICES + HOSTS)
    assert_unmoved(record, before)


@pytest.mark.parametrize("fault", ["unauthorized", "no credential"])
def test_a_login_refused_or_missing_in_the_resumes_probe_ends_the_step_diverged(
    killing: KillingStore, fault: str
) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, fail_after="apply")
    calls = len(driver.calls)
    if fault == "unauthorized":
        r = make(killing, driver, ready=fake_ready(refuse_login={"n2"}, driver=driver), verifier=verifier)
        failing = ("readiness.unauthorized", "n2")
    else:
        r = make(killing, driver, environ={}, verifier=verifier)
        failing = ("credential.missing", "n1")
    asyncio.run(r.reconcile("t"))

    run = killing.get_run(run.id)
    record = assert_diverged(killing, before, run, "planned")  # not rejected: the apply had begun
    assert run.verdict is not None
    assert [(f.rule, f.object) for f in run.verdict.findings] == [failing, ("step.diverged", "t")]
    assert f"The step failed during apply ({failing[0]}), after its apply began" in diverged_finding(run).message
    assert resumed(killing, run.id, "step") == [*APPLY_BEGUN, ("apply", "failed", None)]
    assert killing.events(run.id)[-1].rule == failing[0]
    assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("inspect", "t")]
    assert sorted(driver.labs["t"]) == sorted(DEVICES + HOSTS)
    assert_unmoved(record, before)


def test_a_step_its_resume_refuses_after_its_apply_began_ends_diverged(killing: KillingStore) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, fail_after="apply")
    # The runtime now answers that it cannot change a running twin's links, which the probe's hosts are cabled by:
    # a refusal no spec setting decides, so a resume into the begun apply makes it again (the restart check it
    # does not, `test_a_restart_bearing_step_resumed_into_its_apply_after_a_spec_was_written_ends_stepped`).
    driver.relink = False
    calls = len(driver.calls)
    asyncio.run(make(killing, driver, verifier=verifier).reconcile("t"))

    run = killing.get_run(run.id)
    record = assert_diverged(killing, before, run, "planned")  # refused, yet after an apply that had begun
    assert run.verdict is not None
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("step.diverged", "t"),
                                                                  ("step.relink.unsupported", "t")]
    assert ("The step failed during apply (step.relink.unsupported), after its apply began"
            in diverged_finding(run).message)
    assert resumed(killing, run.id, "step") == APPLY_BEGUN[:-1]  # the refusals follow the re-plan's `plan done`
    assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t")]
    assert sorted(driver.labs["t"]) == sorted(DEVICES + HOSTS)
    assert_unmoved(record, before)


@pytest.mark.parametrize("when", ["before applied", "after applied"])
def test_deleting_a_diverged_twin_destroys_its_lab_and_deletes_its_record(store: LocalStore, when: str) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    if when == "after applied":
        blueprint_id, _ = store.put_blueprint(edited_n1())
        before = respec(store, blueprint_id=blueprint_id)
        asyncio.run(make(store, driver, pusher=fake_push(refuse={"n1"}, driver=driver)).reconcile("t"))
    else:
        before = respec(store, "testdata/blueprint/steps/two-node.json")
        asyncio.run(cancelled_during_apply(store, driver, make(store, driver)))
    diverged = store.get_twin("t")
    assert condition_of(diverged, "Diverged").status == "True"
    held = diverged.status.deployment_id  # the target's once applied, else the one the twin ran
    assert held is not None and (held == before.status.deployment_id) == (when == "before applied")

    destroy = request_deletion(store)
    asyncio.run(make(store, driver).reconcile("t"))
    with pytest.raises(NotFound):
        store.get_twin("t")
    assert driver.calls.count(("destroy", "t")) == 1 and "t" not in driver.labs
    destroy = store.get_run(destroy.id)
    assert destroy.verdict is not None and destroy.verdict.status == "ok"
    assert destroy.verdict.subject.deployment_id == held
    assert seen(store, destroy.id) == [("destroy", "started", None), ("destroy", "done", None)]


@pytest.mark.parametrize("kill_at", ["admitted", "applied"])
def test_a_deletion_finding_a_step_left_running_cancels_it_then_tears_the_twin_down(
    killing: KillingStore, kill_at: str
) -> None:
    driver = FakeDriver()
    before, run, verifier = killed_stepping(killing, driver, kill_at=kill_at)
    record = killing.get_twin("t")
    held, last = record.status.deployment_id, record.status.last_step
    assert last is not None
    stray = queued("t", "step", "alice")  # and a step run that never started
    killing.create_run(stray)
    destroy = request_deletion(killing, mark=False)  # the API's deletion marks a create alone
    asyncio.run(make(killing, driver, verifier=verifier).reconcile("t"))

    with pytest.raises(NotFound):
        killing.get_twin("t")
    run = killing.get_run(run.id)
    assert run.state == "ended" and run.verdict is not None
    assert seen(killing, run.id)[-2:] == CANCELLED
    assert run.verdict.subject.bundle_id == last.to  # the step's target
    if kill_at == "admitted":  # nothing touched: the twin it tears down is the one it ran
        assert_cancelled(run)
        assert "before its apply began" in run.verdict.findings[0].message
        assert held == before.status.deployment_id
    else:
        assert run.verdict.status == "diverged" and run.verdict.findings == (diverged_finding(run),)
        assert "The step was cancelled, after its apply began" in run.verdict.findings[0].message
        assert "The last phase it recorded is applied" in run.verdict.findings[0].message
        assert killing.events(run.id)[-1].rule == "step.diverged"
        assert held != before.status.deployment_id  # the target's, from applied
    assert_cancelled(killing.get_run(stray.id))
    assert seen(killing, stray.id) == CANCELLED
    destroy = killing.get_run(destroy.id)
    assert destroy.verdict is not None and destroy.verdict.status == "ok"
    assert destroy.verdict.subject.deployment_id == held
    assert driver.calls.count(("destroy", "t")) == 1 and "t" not in driver.labs


@pytest.mark.parametrize("kill_at", ["admitted", "applied"])
def test_a_driver_this_core_does_not_serve_ends_a_step_in_flight_and_its_stepping(
    killing: KillingStore, kill_at: str
) -> None:
    driver = FakeDriver()
    before, run, _ = killed_stepping(killing, driver, kill_at=kill_at)
    last = killing.get_twin("t").status.last_step
    assert last is not None
    calls = len(driver.calls)
    r = make(killing, FakeDriver("elsewhere"))  # a core restarted without the twin's driver
    asyncio.run(r.reconcile("t"))

    run = killing.get_run(run.id)
    assert run.state == "ended" and run.verdict is not None
    assert run.verdict.subject.bundle_id == last.to  # the step's target
    record = killing.get_twin("t")
    status = record.status
    for kind in ("Ready", "Stepping"):  # not a stale Stepping True
        assert (condition_of(record, kind).status, condition_of(record, kind).reason) == (
            "False", "twin.driver.unknown")
    assert status.last_step is not None and status.last_step.run_id == run.id
    assert status.observed_generation == record.generation == before.generation
    assert status.run_id is None and status.generation_in_flight is None
    if kill_at == "admitted":
        assert run.verdict.status == "rejected"
        assert [(f.rule, f.object) for f in run.verdict.findings] == [("twin.driver.unknown", "t")]
        assert status.last_step == dataclasses.replace(last, outcome="rejected")
        assert [c.type for c in status.conditions if c.type == "Diverged"] == []
    else:  # its apply had begun: no bundle describes the twin
        assert run.verdict.status == "diverged"
        assert [(f.rule, f.object) for f in run.verdict.findings] == [("step.diverged", "t"),
                                                                      ("twin.driver.unknown", "t")]
        assert status.last_step == dataclasses.replace(last, outcome="diverged")
        assert (condition_of(record, "Diverged").status, condition_of(record, "Diverged").reason) == (
            "True", "step.diverged")
    assert driver.calls[calls:] == [] and "t" in driver.labs
    asyncio.run(r.reconcile("t"))  # refused once
    assert killing.get_twin("t").revision == record.revision


class MarkingStore(LocalStore):
    """A local store that marks the twin's step run cancelling right after the write of a twin record that moves its
    phase (`phase_of`) to `mark_at`, once: a cancel landing then."""

    mark_at: str | None = None

    def update_twin(self, record: TwinRecord, expected_revision: int) -> TwinRecord:
        was = phase_of(self.get_twin(record.name)) if self.mark_at is not None else None
        written = super().update_twin(record, expected_revision)
        if self.mark_at is not None and phase_of(written) == self.mark_at != was:
            self.mark_at = None
            mark_cancelling(self, the_run(self, "step").id)
        return written


def test_a_step_cancelled_once_its_last_phase_is_recorded_has_completed_and_ends_stepped(tmp_path: Path) -> None:
    s = MarkingStore.open(tmp_path / "store")
    assert isinstance(s, MarkingStore)
    try:
        driver = FakeDriver()
        ready_twin(s, driver)
        before = respec(s, "testdata/blueprint/steps/two-node.json")
        verifier, _ = seeded(driver, "testdata/blueprint/steps/two-node.json")
        s.mark_at = "flows"
        asyncio.run(make(s, driver, verifier=verifier).reconcile("t"))

        (run,) = steps(s)
        assert_stepped(s, before, run)  # nothing was left to stop: the cancel came too late
        assert seen(s, run.id) == UP_TO_APPLY + push_events([], ["n1", "n2"]) + WAITED
        assert ("destroy", "t") not in driver.calls
    finally:
        s.close()


def test_a_diverged_step_whose_record_write_was_lost_is_recorded_by_a_core_without_its_driver(
    killing: KillingStore,
) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    blueprint_id, _ = killing.put_blueprint(edited_n1())
    before = respec(killing, blueprint_id=blueprint_id)
    killing.kill_at = "ended"  # the run ended diverged, and the record's last write was lost
    killed(make(killing, driver, pusher=fake_push(refuse={"n1"}, driver=driver)))
    (run,) = steps(killing)
    ended = killing.get_run(run.id)
    assert ended.verdict is not None and ended.verdict.status == "diverged"
    assert killing.get_twin("t").status.run_id == run.id
    events = len(killing.events(run.id))

    r = make(killing, FakeDriver("elsewhere"))  # restarted without the twin's driver: a step's settle needs none
    asyncio.run(r.reconcile("t"))
    record = assert_diverged(killing, before, killing.get_run(run.id), "ready")  # never refused into a ready twin
    assert killing.get_run(run.id) == ended and len(killing.events(run.id)) == events
    asyncio.run(r.reconcile("t"))  # nothing is asked of it now
    assert killing.get_twin("t").revision == record.revision


def test_a_deletion_finding_a_step_killed_after_its_last_phase_ends_it_stepped_then_tears_down(
    killing: KillingStore,
) -> None:
    driver = FakeDriver()
    _, run, verifier = killed_stepping(killing, driver, kill_at="flows")
    held = killing.get_twin("t").status.deployment_id
    destroy = request_deletion(killing, mark=False)
    asyncio.run(make(killing, driver, verifier=verifier).reconcile("t"))

    with pytest.raises(NotFound):
        killing.get_twin("t")
    run = killing.get_run(run.id)
    # Its phases had all run: it had completed, so the cancel ends it as it would have ended, never diverged, its
    # flows listed though no pass ran `flows` to its end.
    assert run.verdict is not None and (run.verdict.status, run.verdict.findings) == ("ok", ())
    assert run.verdict.loss == NOT_STARTED
    assert ("cancel", "started", None) not in seen(killing, run.id)
    destroy = killing.get_run(destroy.id)
    assert destroy.verdict is not None and destroy.verdict.status == "ok"
    assert destroy.verdict.subject.deployment_id == held
    assert driver.calls.count(("destroy", "t")) == 1 and "t" not in driver.labs


def test_a_core_without_the_driver_ends_a_step_killed_after_its_last_phase_stepped(killing: KillingStore) -> None:
    driver = FakeDriver()
    before, run, _ = killed_stepping(killing, driver, kill_at="flows")
    calls = len(driver.calls)
    r = make(killing, FakeDriver("elsewhere"))
    asyncio.run(r.reconcile("t"))

    run = killing.get_run(run.id)
    assert run.verdict is not None and (run.verdict.status, run.verdict.findings) == ("ok", ())
    assert run.verdict.loss == NOT_STARTED  # as the `flows` it had run recorded them
    record = killing.get_twin("t")
    status = record.status
    assert status.last_step is not None and (status.last_step.outcome, status.last_step.phase) == ("stepped", "flows")
    for kind, value in (("Ready", "True"), ("Stepping", "False")):
        assert (condition_of(record, kind).status, condition_of(record, kind).reason) == (value, "twin.ready")
    assert [c.type for c in status.conditions if c.type == "Diverged"] == []
    assert status.observed_generation == record.generation == before.generation and status.run_id is None
    assert driver.calls[calls:] == []
    asyncio.run(r.reconcile("t"))
    assert killing.get_twin("t").revision == record.revision


@pytest.mark.parametrize("kill_at", ["admitted", "applied"])
def test_a_step_to_a_bundle_ended_with_no_manifest_read_names_the_targets_blueprint(
    killing: KillingStore, kill_at: str
) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    target = compiler.compile(blueprint.decode(doc_of(PROBED)), PLATFORMS, PROBES)
    killing.put_bundle(target.id, target.files)
    before = respec(killing, bundle_id=target.id)
    killing.kill_at = kill_at
    killed(make(killing, driver, verifier=seeded(driver, PROBED)[0]))
    (run,) = steps(killing)
    asyncio.run(make(killing, FakeDriver("elsewhere")).reconcile("t"))  # a pass that reads no manifest of its own

    run = killing.get_run(run.id)
    # The target's blueprint, read from the stored target: never the running twin's, which the record names until
    # applied, beside the target.
    assert run.verdict is not None
    assert (run.verdict.subject.bundle_id, run.verdict.subject.blueprint_id) == (target.id,
                                                                                 target.manifest.blueprint_id)
    assert target.manifest.blueprint_id != before.status.blueprint_id
    if kill_at == "admitted":  # nothing planned in this pass, nor applied: the deployment the twin runs
        assert run.verdict.subject.deployment_id == before.status.deployment_id


@pytest.mark.parametrize("cut", ["cancel started", "ended"])
@pytest.mark.parametrize("when", ["before its apply", "after its apply began"])
def test_a_steps_cancel_path_cut_short_is_completed_once(killing: KillingStore, cut: str, when: str) -> None:
    driver = HookedDriver()
    ready_twin(killing, driver)
    if when == "before its apply":
        before = respec(killing, "testdata/blueprint/steps/two-node.json")
        driver.after["admit"] = cancels(killing)
        pusher = fake_push(driver=driver)
    else:
        blueprint_id, _ = killing.put_blueprint(edited_n1())
        before = respec(killing, blueprint_id=blueprint_id)
        pusher = CancellingPush(killing, driver, operation="step")
    if cut == "ended":  # the run's end written, the record's last write lost
        killing.kill_at = "ended"
    else:  # stopped inside the cancel path, the run still cancelling
        killing.kill_event = ("cancel", "started")
    killed(make(killing, driver, pusher=pusher))
    (run,) = steps(killing)
    assert killing.get_twin("t").status.run_id == run.id
    asyncio.run(make(killing, driver).reconcile("t"))

    run = killing.get_run(run.id)
    events = seen(killing, run.id)
    started = 2 if cut == "cancel started" else 1  # cut inside it, the path is run again, from its start
    assert (events.count(("cancel", "started", None)), events.count(("cancel", "done", None))) == (started, 1)
    if when == "before its apply":
        assert_step_cancelled(killing, before, run, "admitted")
    else:
        assert_diverged(killing, before, run, "ready")
        assert run.verdict is not None and run.verdict.findings == (diverged_finding(run),)
    assert ("destroy", "t") not in driver.calls and "t" in driver.labs


# The dry run of a step (D-050): on a twin that runs, admission with the deployment it holds, the
# target's plan, the driver's changes and the step's refusals, writing nothing.


def stored_files(store: LocalStore) -> dict[Path, str]:
    """Every file the store holds, by path, with its content's hash."""
    return {p.relative_to(store.root): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in store.root.rglob("*") if p.is_file()}


def step_spec(store: LocalStore, path: str, *, allow_restart: bool = False) -> Spec:
    """A spec of `t` naming the blueprint at `path`, filed."""
    return Spec(blueprint_id=file_blueprint(store, path), driver="fake", allow_restart=allow_restart)


UNLINKED = "testdata/blueprint/steps/three-node-unlinked.json"
N3_EOS = "testdata/blueprint/steps/three-node-n3-eos.json"


def test_a_dry_run_of_a_step_admits_with_the_held_deployment_and_answers_its_changes(store: LocalStore) -> None:
    driver = FakeDriver()
    record = ready_twin(store, driver)
    spec = step_spec(store, UNLINKED)
    before, calls = stored_files(store), len(driver.calls)
    planned, verdict, changes = asyncio.run(make(store, driver).dry_run("t", spec, held=record))

    assert driver.calls[calls:] == [("admit", "t", "held"), ("plan", "t"), ("changes", "t")]
    assert planned is not None and planned.allocation == record.status.allocation
    assert planned.id != record.status.deployment_id and deployment.validate(documents.encode(planned)) == []
    assert (verdict.operation, verdict.status, verdict.findings) == ("plan", "ok", ())
    assert verdict.subject == Subject(twin="t", blueprint_id=spec.blueprint_id, bundle_id=planned.bundle_id,
                                      deployment_id=planned.id)
    assert changes == Changes(
        nodes=(NodeChange(node="n1", action="kept", reasons=()),
               NodeChange(node="n2", action="recabled", reasons=("links",)),
               NodeChange(node="n3", action="recabled", reasons=("links",))),
        links_added=(), links_removed=(("n2:ethernet-1/2", "n3:ethernet-1/1"),))
    assert stored_files(store) == before  # no run, bundle or deployment written, and the record as it was


@pytest.mark.parametrize("allow_restart", [False, True])
def test_a_dry_run_of_a_step_recreating_a_node_is_rejected_unless_the_spec_allows_a_restart(
    store: LocalStore, allow_restart: bool
) -> None:
    driver = FakeDriver()
    record = ready_twin(store, driver)
    driver.recreates = {"n3"}
    planned, verdict, changes = asyncio.run(make(store, driver).dry_run(
        "t", step_spec(store, N3_EOS, allow_restart=allow_restart), held=record))

    assert planned is not None and changes is not None
    assert [(c.node, c.action) for c in changes.nodes] == [("n1", "recabled"), ("n2", "recabled"), ("n3", "recreated")]
    assert len(changes.links_added) == len(changes.links_removed) == 2
    assert verdict.subject.deployment_id == planned.id
    if allow_restart:
        assert (verdict.status, verdict.findings) == ("ok", ())
        return
    assert verdict.status == "rejected"
    (finding,) = verdict.findings  # the loop's own refusal, as the step's verdict would carry it
    assert (finding.rule, finding.severity, finding.object) == ("step.restart.required", "error", "n3")
    assert "recreated (links)" in finding.message and "allow_restart" in finding.message


def test_a_dry_run_of_a_link_change_on_a_driver_that_cannot_relink_is_rejected(store: LocalStore) -> None:
    driver = FakeDriver(relink=False)
    record = ready_twin(store, driver)
    planned, verdict, changes = asyncio.run(make(store, driver).dry_run("t", step_spec(store, UNLINKED), held=record))
    assert planned is not None and changes is not None and verdict.status == "rejected"
    assert [(f.rule, f.object) for f in verdict.findings] == [("step.relink.unsupported", "t")]


def test_a_dry_run_on_a_diverged_twin_is_rejected_as_its_step_would_be(store: LocalStore) -> None:
    driver = FakeDriver()
    record = ready_twin(store, driver)
    diverged = Condition(type="Diverged", status="True", reason="step.diverged", since=clock.now())
    record = store.update_twin(dataclasses.replace(record, status=dataclasses.replace(
        record.status, conditions=(*record.status.conditions, diverged))), record.revision)
    _, verdict, changes = asyncio.run(make(store, driver).dry_run("t", record.spec, held=record))
    assert changes is not None and verdict.status == "rejected"
    assert [(f.rule, f.object) for f in verdict.findings] == [("step.twin.diverged", "t")]


def test_a_dry_run_of_a_step_from_a_deployment_no_loaded_package_runs_is_rejected(store: LocalStore) -> None:
    driver = UnreadableChanges()
    record = ready_twin(store, driver)
    planned, verdict, changes = asyncio.run(make(store, driver).dry_run(
        "t", step_spec(store, "testdata/blueprint/steps/two-node.json"), held=record))
    assert planned is not None and changes is None  # the target plans; what changes cannot be told
    assert verdict.status == "rejected"
    (finding,) = verdict.findings
    assert (finding.rule, finding.object) == ("bundle.rejected", "t") and "n3" in finding.message


def test_a_dry_run_on_a_twin_whose_create_never_applied_is_a_creates(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver(refuse=Refusal("admission.capacity", "no room"))
    r = make(store, driver)
    asyncio.run(r.reconcile("t"))
    record = store.get_twin("t")
    assert record.status.deployment_id is None  # its cleanup cleared it
    driver.refuse = None
    calls = len(driver.calls)
    planned, verdict, changes = asyncio.run(r.dry_run("t", step_spec(store, UNLINKED), held=record))
    assert driver.calls[calls:] == [("admit", "t"), ("plan", "t")]
    assert planned is not None and changes is None and verdict.status == "ok"


# A run taken afresh supersedes every other create or step run of the twin still queued, or cancelled before it
# started.

SUPERSEDED = "The run was superseded before it started by run {run}."
"""The superseded run's message, naming the run taken: a client's, or the loop's own."""


def test_a_step_queued_where_the_loop_creates_again_is_superseded_by_the_create(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    asyncio.run(make(store, driver, pusher=fake_push({"n1"}, driver=driver)).reconcile("t"))
    assert store.get_twin("t").status.deployment_id is None  # the refused push's cleanup cleared what it applied
    # The API queued a step while the record named the applied lab; the cleanup made the spec a create's again.
    respec(store, "testdata/blueprint/steps/two-node.json")
    asked = queued("t", "step", "alice")
    store.create_run(asked)
    asyncio.run(make(store, driver).reconcile("t"))

    again, refused = [r for r in store.list_runs("t") if r.operation == "create"]
    superseded = store.get_run(asked.id)
    assert superseded.state == "ended" and superseded.verdict is not None
    assert superseded.verdict.status == "failed"
    assert [(f.rule, f.object, f.message) for f in superseded.verdict.findings] == [
        ("run.cancelled", "t", SUPERSEDED.format(run=again.id))]  # the loop's own run, which no later spec queued
    assert [(e.phase, e.outcome, e.rule) for e in store.events(asked.id)] == [
        ("cancel", "started", None), ("cancel", "done", "run.cancelled")]
    assert (again.principal, again.verdict is not None and again.verdict.status) == ("core", "ok")
    assert refused.verdict is not None and refused.verdict.status == "failed"
    assert ready_of(store.get_twin("t")).status == "True" and steps(store) == [superseded]


def test_a_resumed_create_supersedes_nothing_and_the_step_queued_meanwhile_runs_next(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "applied"
    killed(make(killing, driver))
    respec(killing, UNLINKED)  # a client's spec, written once the create applied: the API queued a step
    asked = queued("t", "step", "alice")
    killing.create_run(asked)
    r = make(killing, driver, verifier=seeded(driver, UNLINKED)[0])
    asyncio.run(r.reconcile("t"))  # the create resumes, under the run the record names

    record = killing.get_twin("t")
    assert ready_of(record).status == "True" and record.status.observed_generation == 1
    assert killing.get_run(asked.id).state == "queued"
    asyncio.run(r.reconcile("t"))

    (step,) = steps(killing)
    assert step.id == asked.id and step.verdict is not None and step.verdict.status == "ok"
    assert killing.get_twin("t").status.observed_generation == 2


def test_a_queued_run_a_client_cancelled_beside_a_newer_one_is_superseded_with_the_rest(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    respec(store, UNLINKED)
    older = queued("t", "step", "alice")
    store.create_run(older)
    mark_cancelling(store, older.id)  # the client cancelled it before the loop took it
    written = respec(store, TWO_NODE)
    newer = queued("t", "step", "bob")
    store.create_run(newer)
    verifier, _ = seeded(driver, TWO_NODE)
    asyncio.run(make(store, driver, verifier=verifier).reconcile("t"))

    swept = store.get_run(older.id)
    assert swept.state == "ended" and swept.verdict is not None and swept.verdict.status == "failed"
    assert [(f.rule, f.message) for f in swept.verdict.findings] == [
        ("run.cancelled", SUPERSEDED.format(run=newer.id))]
    assert [(e.phase, e.outcome, e.rule) for e in store.events(older.id)] == [
        ("cancel", "started", None), ("cancel", "done", "run.cancelled")]
    assert_stepped(store, written, store.get_run(newer.id))


# A spec written while a run is in flight (D-050): the run works toward the generation it was taken under, its own
# spec deciding what it may restart, and the next run takes the newer spec.

TWO_NODE = "testdata/blueprint/steps/two-node.json"
N3_EOS = "testdata/blueprint/steps/three-node-n3-eos.json"


def test_a_spec_allowing_restarts_written_while_a_step_admits_is_not_the_runs_and_the_next_run_steps_to_it(
    store: LocalStore,
) -> None:
    driver = HookedDriver()
    ready_twin(store, driver)
    driver.recreates = {"n3"}
    before = respec(store, N3_EOS)  # it recreates n3, and the spec does not allow a restart
    written: list[TwinRecord] = []
    # A client's PUT while the step admits: another target, allowing restarts. The run's next write carries its spec.
    driver.after["admit"] = lambda: written.append(respec(store, TWO_NODE, allow_restart=True))
    calls = len(driver.calls)
    r = make(store, driver, verifier=seeded(driver, TWO_NODE)[0])
    asyncio.run(r.reconcile("t"))

    (first,) = steps(store)
    record = assert_refused(store, before, first, "step.restart.required", written=1)
    assert record.spec == written[0].spec and record.spec.allow_restart  # the newer spec, which no run took yet
    assert first.verdict is not None and record.status.last_step is not None
    assert [(f.rule, f.object) for f in first.verdict.findings] == [("step.restart.required", "n3")]
    # What the run compiled and planned, never the newer spec's blueprint beside the run's target.
    assert (first.verdict.subject.blueprint_id, first.verdict.subject.bundle_id) == (
        before.spec.blueprint_id, record.status.last_step.to)
    assert driver.calls[calls:] == [("admit", "t", "held"), ("plan", "t"), ("changes", "t")]  # n3 never recreated
    assert driver.labs["t"]["n3"].incarnation == "boot-1"
    asyncio.run(r.reconcile("t"))

    _, second = steps(store)
    assert_stepped(store, written[0], second)  # the newer spec, stepped to under its own setting


def test_a_create_that_fails_while_a_spec_is_written_observes_the_generation_it_was_taken_under(
    store: LocalStore,
) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    refusing = fake_push(refuse={"n1"}, driver=driver)
    written: list[TwinRecord] = []

    async def writes_a_spec(address: str, package: Any, config: str, credential: Any) -> Any:
        if not written:  # a client's PUT while the create pushes n1, which refuses
            written.append(respec(store, TWO_NODE))
        return await refusing(address, package, config, credential)

    asyncio.run(make(store, driver, pusher=writes_a_spec).reconcile("t"))  # type: ignore[arg-type]
    record = store.get_twin("t")
    assert_cleaned_up(dataclasses.replace(record, generation=1), "push.refused")
    assert (record.generation, record.status.observed_generation) == (2, 1)  # the newer spec is the next run's
    assert record.status.generation_in_flight is None
    asyncio.run(make(store, driver).reconcile("t"))

    again, failed = store.list_runs("t")
    assert failed.verdict is not None and failed.verdict.status == "failed"
    assert again.operation == "create" and again.verdict is not None and again.verdict.status == "ok"
    created = store.get_twin("t")
    assert ready_of(created).status == "True" and created.status.observed_generation == created.generation == 2
    assert created.status.blueprint_id == written[0].spec.blueprint_id


def test_a_step_a_core_without_its_driver_ends_after_a_spec_was_written_observes_the_generation_it_took(
    killing: KillingStore,
) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    before = respec(killing, UNLINKED)
    killing.kill_at = "admitted"
    killed(make(killing, driver))
    (first,) = steps(killing)
    written = respec(killing, TWO_NODE)  # a client's PUT while the step is in flight
    asyncio.run(make(killing, FakeDriver("elsewhere")).reconcile("t"))

    first = killing.get_run(first.id)
    assert first.verdict is not None and [f.rule for f in first.verdict.findings] == ["twin.driver.unknown"]
    record = assert_refused(killing, before, first, "twin.driver.unknown", written=1)
    # What the run compiled, read from its stored target though this pass read no manifest: never the newer spec's
    # blueprint, which the record's spec names now, beside the run's target.
    assert record.status.last_step is not None and record.spec.blueprint_id == written.spec.blueprint_id
    assert (first.verdict.subject.blueprint_id, first.verdict.subject.bundle_id) == (
        before.spec.blueprint_id, record.status.last_step.to)
    asyncio.run(make(killing, driver, verifier=seeded(driver, TWO_NODE)[0]).reconcile("t"))  # a core with it

    _, second = steps(killing)
    assert_stepped(killing, written, second)


@pytest.mark.parametrize("silent", [False, True], ids=["every node answers", "a node silent"])
def test_a_step_resumed_after_a_spec_was_written_keeps_the_generation_and_the_spec_it_was_taken_under(
    killing: KillingStore, silent: bool
) -> None:
    driver = FakeDriver()
    _, run, verifier = killed_stepping(killing, driver, fail_after="apply")  # its spec allows no restart
    if silent:
        driver.silent.add(("t", "n3"))  # a reconfigure would remedy it, which only the newer spec allows
    written = respec(killing, TWO_NODE, allow_restart=True)  # a client's PUT while the core was down
    assert (written.generation, written.status.generation_in_flight) == (3, 2)

    calls = len(driver.calls)
    asyncio.run(make(killing, driver, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    record = killing.get_twin("t")
    assert (record.generation, record.status.observed_generation) == (3, 2)  # the generation the run was taken under
    assert record.status.run_id is None and record.status.generation_in_flight is None
    assert run.verdict is not None and record.status.last_step is not None
    if not silent:
        assert (run.verdict.status, record.status.last_step.outcome) == ("ok", "stepped")
        assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("inspect", "t"), ("apply", "t"),
                                                ("inspect", "t")]
        asyncio.run(make(killing, driver, verifier=seeded(driver, TWO_NODE)[0]).reconcile("t"))
        _, second = steps(killing)
        assert_stepped(killing, record, second)  # the next run steps to the newer spec
        return
    # Diverged, never reconfigured under the newer spec's permission: every node keeps its incarnation.
    assert run.verdict.status == "diverged"
    assert [(f.rule, f.object) for f in run.verdict.findings] == [("step.node.silent", "n3")]
    assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("inspect", "t")]
    assert {driver.labs["t"][n].incarnation for n in DEVICES} == {"boot-1"}
    left = record.status.last_step
    asyncio.run(make(killing, driver).reconcile("t"))  # the newer spec's step: the twin accepts only deletion now
    _, second = steps(killing)
    assert_refused(killing, record, second, "step.twin.diverged", kept=left)


def test_a_restart_bearing_step_resumed_into_its_apply_after_a_spec_was_written_ends_stepped(
    killing: KillingStore,
) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    driver.recreates = {"n3"}
    before = respec(killing, N3_EOS, allow_restart=True)  # it recreates n3, which its spec allows
    verifier, _ = seeded(driver, N3_EOS)
    driver.fail_after = "apply"  # the core stops once the deploy took effect: n3 is made anew
    killed(make(killing, driver, verifier=verifier))
    (run,) = steps(killing)
    written = respec(killing, TWO_NODE)  # a client's PUT while the core was down, allowing no restart

    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    # The pass that began the apply passed the restart check under the run's own spec, and the re-plan is that plan:
    # the newer spec, which does not allow it, refuses nothing. Every node answers, so it is applied again plainly.
    record = assert_stepped(killing, before, run)
    assert (record.generation, record.status.observed_generation) == (3, 2)
    assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("inspect", "t"), ("apply", "t"),
                                            ("inspect", "t")]
    assert [node for node, _ in ready.calls] == [*DEVICES, "n3"] and [node for node, _ in pusher.calls] == ["n3"]
    assert [c.type for c in record.status.conditions if c.type == "Diverged"] == []
    asyncio.run(make(killing, driver, verifier=seeded(driver, TWO_NODE)[0]).reconcile("t"))

    _, second = steps(killing)
    assert_stepped(killing, dataclasses.replace(record, spec=written.spec), second)  # the newer spec, stepped to


# A step that left the twin diverged keeps its record (D-029): a later run of the twin, refused or cancelled, never
# writes over it.


@pytest.mark.parametrize("then", ["refused", "cancelled"])
def test_a_run_after_a_step_left_the_twin_diverged_keeps_that_steps_record(store: LocalStore, then: str) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    blueprint_id, _ = store.put_blueprint(edited_n1())
    respec(store, blueprint_id=blueprint_id)  # the first step pushes n1, which refuses: it ends diverged
    refusing = fake_push(refuse={"n1"}, driver=driver)
    asked: list[Run] = []

    async def writes_a_spec(address: str, package: Any, config: str, credential: Any) -> Any:
        if not asked:  # a client's PUT while the first step pushes, accepted: the twin was not yet diverged
            respec(store, TWO_NODE)
            asked.append(queued("t", "step", "alice"))
            store.create_run(asked[0])
            if then == "cancelled":
                mark_cancelling(store, asked[0].id)
        return await refusing(address, package, config, credential)

    asyncio.run(make(store, driver, pusher=writes_a_spec).reconcile("t"))  # type: ignore[arg-type]
    first = steps(store)[0]
    diverged = store.get_twin("t")
    left = diverged.status.last_step
    assert first.verdict is not None and first.verdict.status == "diverged"
    assert left is not None and (left.outcome, left.run_id, left.phase) == ("diverged", first.id, "ready")
    assert (diverged.status.observed_generation, diverged.generation) == (2, 3)  # the newer spec is the next run's
    calls = len(driver.calls)
    asyncio.run(make(store, driver).reconcile("t"))

    second = store.get_run(asked[0].id)
    record = store.get_twin("t")
    rule = "step.twin.diverged" if then == "refused" else "run.cancelled"
    assert second.verdict is not None
    assert (second.verdict.status, [f.rule for f in second.verdict.findings]) == (
        "rejected" if then == "refused" else "failed", [rule])
    assert record.status.last_step == left  # the diverged step's bundles, run and phase
    for kind in ("Ready", "Stepping"):
        assert (condition_of(record, kind).status, condition_of(record, kind).reason) == ("False", rule)
    assert condition_of(record, "Diverged") == condition_of(diverged, "Diverged")  # never set back
    assert record.status.observed_generation == record.generation == 3 and record.status.run_id is None
    assert driver.calls[calls:] == []


# A step cut short before its deploy made a node it adds (D-029: an added node needs no allow_restart).


@pytest.mark.parametrize("allowed", [False, True], ids=["no restart", "allow_restart"])
def test_a_step_cut_short_before_its_deploy_made_an_added_node_applies_plainly_and_makes_it(
    killing: KillingStore, allowed: bool
) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver, TWO_NODE)
    before = respec(killing, "testdata/blueprint/three-node.json", allow_restart=allowed)  # adds n3
    verifier, _ = seeded(driver, "testdata/blueprint/three-node.json")
    killing.kill_event = ("apply", "started")  # the core stops before the deploy made n3
    killed(make(killing, driver, verifier=verifier))
    (run,) = steps(killing)
    assert sorted(driver.labs["t"]) == ["n1", "n2"]

    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(killing, driver, ready=ready, pusher=pusher, verifier=verifier).reconcile("t"))
    run = killing.get_run(run.id)
    record = assert_stepped(killing, before, run)
    # The probe reads the nodes the lab has; n3, which it lacks, is not silent: the plain apply makes it, whatever
    # allow_restart says, and every other node keeps its incarnation and what it holds.
    assert runtime_calls(driver, calls) == [("plan", "t"), ("changes", "t"), ("inspect", "t"), ("apply", "t"),
                                            ("inspect", "t")]
    assert [node for node, _ in ready.calls] == ["n1", "n2", "n3"] and [node for node, _ in pusher.calls] == ["n3"]
    assert [(n.name, n.incarnation) for n in record.status.nodes] == [("n1", "boot-1"), ("n2", "boot-1"),
                                                                       ("n3", "boot-2")]
    assert holds(record) == dict.fromkeys(DEVICES, record.status.bundle_id)
    assert resumed(killing, run.id, "step") == [*APPLY_BEGUN, ("apply", "done", None), *pairs("ready", ["n3"]),
                                                *push_events(["n3"], DEVICES), *WAITED]


# A node restarted in place keeps its incarnation and loses its push all the same.


class RestartsInPlace(FakeDriver):
    """A runtime that restarts a node in place, as under a restart link mode: a node `changes` calls `restarted`
    keeps its incarnation through the apply."""

    async def apply(self, *args: Any, **kwargs: Any) -> None:
        twin = args[0].twin  # the deployment's
        was = dict(self.labs.get(twin, {}))
        await super().apply(*args, **kwargs)
        lab = self.labs[twin]
        for name in self.restarts & was.keys() & lab.keys():
            lab[name] = dataclasses.replace(lab[name], incarnation=was[name].incarnation)


def test_a_node_a_step_restarts_in_place_is_readied_and_pushed_though_its_incarnation_stayed(
    store: LocalStore,
) -> None:
    driver = RestartsInPlace()
    ready_twin(store, driver)
    driver.restarts = {"n2"}  # its links change, and the runtime restarts it to change them
    before = respec(store, UNLINKED, allow_restart=True)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(make(store, driver, ready=ready, pusher=pusher, verifier=seeded(driver, UNLINKED)[0]).reconcile("t"))

    (run,) = steps(store)
    record = assert_stepped(store, before, run)
    assert {n.name: n.incarnation for n in record.status.nodes} == dict.fromkeys(DEVICES, "boot-1")
    # n2's hold was voided at applied, its incarnation unmoved: it alone is readied and pushed again.
    assert seen(store, run.id) == UP_TO_APPLY + pairs("ready", ["n2"]) + push_events(["n2"], DEVICES) + WAITED
    assert [node for node, _ in ready.calls] == ["n2"] and [node for node, _ in pusher.calls] == ["n2"]
    assert holds(record) == dict.fromkeys(DEVICES, record.status.bundle_id)


# The pass on a settled twin, and the restore (D-067): a kick inspects a settled twin, and a node the runtime replaced
# behind the loop's back is readied, pushed and verified again under a run of operation `restore`.

VERIFIED: list[Seen] = [("verify", "started", None), ("verify", "done", None)]


def restorer(store: LocalStore, driver: FakeDriver, path: str = "testdata/blueprint/three-node.json",
             **kw: Any) -> Reconciler:
    """A reconciler whose verify holds on the twin built to the blueprint at `path` (`seeded`), so a restore's wait
    settles at once: the default reader holds no facts, and the wait would expire after `step_wait_s`."""
    return make(store, driver, verifier=seeded(driver, path)[0], **kw)


def newest(store: LocalStore) -> Run:
    """The twin's newest run."""
    return store.list_runs("t")[0]


class RecordingPush(FakePush):
    """A push that keeps the twin's record as it stands at each call."""

    def __init__(self, store: LocalStore, driver: FakeDriver) -> None:
        super().__init__(None, None, None, driver)
        self.store = store
        self.records: list[TwinRecord] = []

    async def __call__(
        self, address: str, package: platform_package.PlatformPackage, config: str, credential: Credential
    ) -> push.Pushed | push.Refused:
        self.records.append(self.store.get_twin("t"))
        return await super().__call__(address, package, config, credential)


def test_a_node_at_another_incarnation_is_readied_pushed_and_verified_under_a_restore_run(store: LocalStore) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    replaced = driver.replace("t", "n2")
    assert replaced.incarnation != "boot-1" and replaced.running
    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), RecordingPush(store, driver)
    r = restorer(store, driver, ready=ready, pusher=pusher)
    asyncio.run(r.reconcile("t"))

    run = newest(store)
    (at_push,) = pusher.records
    assert (ready_of(at_push).status, ready_of(at_push).reason) == ("False", "twin.restoring")
    assert at_push.status.run_id == run.id
    (n2,) = [n for n in at_push.status.nodes if n.name == "n2"]
    assert n2.incarnation == replaced.incarnation and n2.holds is None
    assert (run.operation, run.principal, run.state) == ("restore", "core", "ended")
    assert run.verdict is not None and (run.verdict.operation, run.verdict.status) == ("restore", "ok")
    was = before.status
    assert run.verdict.subject == Subject(twin="t", run_id=run.id, blueprint_id=was.blueprint_id,
                                          bundle_id=was.bundle_id, deployment_id=was.deployment_id)
    assert run.verdict.counts is not None and run.verdict.wait is not None and run.verdict.wait.outcome == "settled"
    assert run.verdict.loss is None
    assert seen(store, run.id) == [*pairs("ready", ["n2"]), *pairs("push", ["n2"]), *VERIFIED]
    assert [n for n, _ in ready.calls] == [n for n, _ in pusher.calls] == ["n2"]
    assert driver.calls[calls:] == [("inspect", "t")]  # no compile, admit, plan or apply: nothing is applied

    record = store.get_twin("t")
    status = record.status
    nodes = {n.name: n for n in status.nodes}
    assert (nodes["n2"].incarnation, nodes["n2"].holds) == (driver.labs["t"]["n2"].incarnation, was.bundle_id)
    assert [nodes["n1"], nodes["n3"]] == [n for n in was.nodes if n.name in ("n1", "n3")]
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert status.run_id is None and status.generation_in_flight is None
    assert (record.generation, status.observed_generation, status.phase, status.last_step, status.bundle_id,
            status.deployment_id, status.allocation) == (before.generation, was.observed_generation, was.phase,
                                                         was.last_step, was.bundle_id, was.deployment_id,
                                                         was.allocation)

    calls = len(driver.calls)
    asyncio.run(r.reconcile("t"))  # nothing moved since: one inspect, and no run
    assert driver.calls[calls:] == [("inspect", "t")]
    assert [each.operation for each in store.list_runs("t")] == ["restore", "create"]


def test_a_replaced_probe_host_is_readied_again_and_nothing_is_pushed(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver, PROBED)
    driver.replace("t", "n1-loop-a")
    pusher = fake_push(driver=driver)
    asyncio.run(restorer(store, driver, PROBED, pusher=pusher).reconcile("t"))

    run = newest(store)
    assert run.operation == "restore" and run.verdict is not None and run.verdict.status == "ok"
    assert seen(store, run.id) == [*pairs("ready", HOSTS), *VERIFIED]  # every host readied, as a step readies them
    assert pusher.calls == []
    record = store.get_twin("t")
    (host,) = [n for n in record.status.nodes if n.name == "n1-loop-a"]
    assert host.incarnation == driver.labs["t"]["n1-loop-a"].incarnation
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")


def test_a_restore_on_a_twin_whose_step_was_refused_pushes_and_leaves_its_conditions(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    driver.recreates = {"n3"}
    respec(store, "testdata/blueprint/steps/three-node-n3-eos.json")
    asyncio.run(make(store, driver).reconcile("t"))
    refused = store.get_twin("t")
    assert (ready_of(refused).status, ready_of(refused).reason) == ("False", "step.restart.required")
    driver.replace("t", "n1")
    pusher = fake_push(driver=driver)
    asyncio.run(restorer(store, driver, pusher=pusher).reconcile("t"))

    run = newest(store)
    assert run.operation == "restore" and run.verdict is not None and run.verdict.status == "ok"
    assert [n for n, _ in pusher.calls] == ["n1"]
    record = store.get_twin("t")
    # The twin does not run what the spec asks, so the restore leaves the refusal's conditions and step as they were.
    assert ready_of(record) == ready_of(refused)
    assert condition_of(record, "Stepping") == condition_of(refused, "Stepping")
    assert record.status.last_step == refused.status.last_step
    assert record.status.observed_generation == refused.status.observed_generation and record.status.run_id is None


def test_a_diverged_twin_is_passed_over(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    blueprint_id, _ = store.put_blueprint(edited_n1())
    respec(store, blueprint_id=blueprint_id)
    asyncio.run(make(store, driver, pusher=fake_push(refuse={"n1"}, driver=driver)).reconcile("t"))
    assert reconcile.diverged(store.get_twin("t"))
    driver.replace("t", "n1")

    revision, calls = store.get_twin("t").revision, len(driver.calls)
    asyncio.run(restorer(store, driver).reconcile("t"))
    assert driver.calls[calls:] == []
    assert [r.operation for r in store.list_runs("t") if r.operation == "restore"] == []
    assert store.get_twin("t").revision == revision


def test_a_restore_never_starts_beside_a_run_in_flight(killing: KillingStore) -> None:
    new_twin(killing, file_blueprint(killing))
    driver = FakeDriver()
    killing.kill_at = "applied"
    killed(make(killing, driver))
    replaced = driver.replace("t", "n2")  # behind the back of a create left in flight
    pusher = fake_push(driver=driver)
    r = restorer(killing, driver, pusher=pusher)

    asyncio.run(r.reconcile("t"))  # the create resumes and ends: no restore beside it
    record = killing.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert [run.operation for run in killing.list_runs("t")] == ["create"]

    asyncio.run(r.reconcile("t"))  # the next pass finds n2 at an incarnation the record does not hold
    run = newest(killing)
    assert run.operation == "restore" and run.verdict is not None and run.verdict.status == "ok"
    assert [n for n, _ in pusher.calls] == ["n1", "n2", "n3", "n2"]
    (n2,) = [n for n in killing.get_twin("t").status.nodes if n.name == "n2"]
    assert n2.incarnation == driver.labs["t"]["n2"].incarnation == replaced.incarnation


def test_a_step_that_recreates_a_node_then_a_kick_starts_no_restore(killing: KillingStore) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    driver.recreates = {"n3"}
    target = "testdata/blueprint/steps/three-node-n3-eos.json"
    respec(killing, target, allow_restart=True)
    killing.kill_at = "applied"  # the step's own apply made n3 anew, and the event it raised finds the step in flight
    killed(make(killing, driver))
    recorded = {n.name: n.incarnation for n in killing.get_twin("t").status.nodes}
    assert recorded == {name: state.incarnation for name, state in driver.labs["t"].items()}
    assert recorded["n3"] != "boot-1"
    pusher = fake_push(driver=driver)
    r = restorer(killing, driver, target, pusher=pusher)

    calls = len(driver.calls)
    asyncio.run(r.reconcile("t"))  # the kick resumes the step to its end, and asks nothing more of the runtime
    assert driver.calls[calls:] == []
    assert [run.operation for run in killing.list_runs("t")] == ["step", "create"]
    record = killing.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert [n for n, _ in pusher.calls] == ["n3"]

    revision, calls = record.revision, len(driver.calls)
    asyncio.run(r.reconcile("t"))  # the pass after the step's end: n3 is at the incarnation the step recorded
    assert driver.calls[calls:] == [("inspect", "t")]
    assert killing.get_twin("t").revision == revision
    assert [run.operation for run in killing.list_runs("t")] == ["step", "create"]


@pytest.mark.parametrize("served", [True, False])
def test_killed_after_a_restore_ended_the_next_pass_records_its_ending(killing: KillingStore, served: bool) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    driver.replace("t", "n2")
    killing.kill_at = "ended"
    killed(restorer(killing, driver))
    run = newest(killing)
    record = killing.get_twin("t")
    assert run.operation == "restore" and run.state == "ended" and record.status.run_id == run.id
    assert ready_of(record).reason == "twin.restoring"

    calls = len(driver.calls)
    asyncio.run((restorer(killing, driver) if served else make(killing, FakeDriver("elsewhere"))).reconcile("t"))
    record = killing.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert record.status.run_id is None and record.status.generation_in_flight is None
    assert [r.operation for r in killing.list_runs("t")] == ["restore", "create"]  # no second restore
    assert driver.calls[calls:] == []  # a pass that ends a run inspects nothing after it


def test_killed_after_a_missing_end_the_next_pass_settles_for_twin_node_missing(killing: KillingStore) -> None:
    driver = FakeDriver()
    ready_twin(killing, driver)
    driver.replace("t", "n2")
    asyncio.run(restorer(killing, driver, pusher=fake_push(unreachable={"n2"}, driver=driver)).reconcile("t"))
    run = newest(killing)
    assert run.state == "running" and killing.events(run.id)[-1].rule == "push.unreachable"
    del driver.labs["t"]["n3"]
    r = restorer(killing, driver, platforms=SHORT)

    async def scenario() -> None:
        await r.reconcile("t")
        await asyncio.sleep(1.1)
        killing.kill_at = "ended"  # killed once the run ended, before the record's write
        with pytest.raises(RuntimeError, match="killed"):
            await r.reconcile("t")

    asyncio.run(scenario())
    asyncio.run(restorer(killing, driver).reconcile("t"))
    record = killing.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.node.missing")


def test_a_settled_pass_reads_a_deployment_and_its_bundle_once_per_deployment(
    store: LocalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    reads: list[str] = []
    for name in ("get_deployment", "get_bundle"):
        monkeypatch.setattr(store, name, counted(reads, getattr(store, name)))
    r = restorer(store, driver)

    asyncio.run(r.reconcile("t"))  # what this core lacks to serve the deployment is read once
    assert reads == ["get_deployment", "get_bundle"]
    reads.clear()
    asyncio.run(r.reconcile("t"))  # the same deployment: content-addressed, and the packages are fixed
    assert reads == []
    assert driver.calls[-2:] == [("inspect", "t"), ("inspect", "t")]


def counted(reads: list[str], call: Callable[..., Any]) -> Callable[..., Any]:
    """`call`, its name appended to `reads` at each call."""

    def counting(*args: Any) -> Any:
        reads.append(call.__name__)
        return call(*args)

    return counting


# A node missing or not running (D-067): waited for through its boot window, then reported, never made.

SRLINUX = PLATFORMS["nokia_srlinux"]
SHORT = {**PLATFORMS, SRLINUX.id: dataclasses.replace(SRLINUX, readiness=dataclasses.replace(SRLINUX.readiness,
                                                                                               timeout_s=1))}
"""The packages with SR Linux's readiness window shrunk to 1 s: a `three-node` node's boot window."""


def stopped(driver: FakeDriver, node: str, *, stop: bool = True) -> None:
    """`node` of `t` stopped, or running again (`stop=False`), at the incarnation it had."""
    driver.labs["t"][node] = dataclasses.replace(driver.labs["t"][node], running=not stop)


def warnings_of(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The loop's WARNING lines so far."""
    return [r.getMessage() for r in caplog.records if r.name == "fylgja.reconcile" and r.levelno == logging.WARNING]


async def served(r: Reconciler) -> str:
    """A worker's turn: the twin the queue has due, passed over, and released; within 0.5 s."""
    name = await asyncio.wait_for(r.queue.get(), timeout=0.5)
    try:
        await r.reconcile(name)
    finally:
        r.queue.done(name)
    return name


async def reported_missing(store: LocalStore, driver: FakeDriver, r: Reconciler) -> None:
    """`n3` of a Ready `t` stopped, and two passes of `r` its boot window apart: `twin.node.missing` recorded."""
    stopped(driver, "n3")
    await r.reconcile("t")
    await asyncio.sleep(1.1)
    await r.reconcile("t")
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.node.missing")


@pytest.mark.parametrize("how", ["deleted", "stopped"])
def test_a_missing_node_is_waited_for_then_recorded_and_never_made(
    store: LocalStore, caplog: pytest.LogCaptureFixture, how: str
) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    if how == "deleted":
        del driver.labs["t"]["n3"]
    else:
        stopped(driver, "n3")
    calls = len(driver.calls)
    r = restorer(store, driver, platforms=SHORT)

    async def scenario() -> None:
        await r.reconcile("t")  # within n3's boot window: nothing written, the twin queued again
        assert store.get_twin("t").revision == before.revision and len(store.list_runs("t")) == 1
        assert driver.calls[calls:] == [("inspect", "t")]
        assert r.queue.waiting() == ["t"]
        assert warnings_of(caplog) == []

        await asyncio.sleep(1.1)
        assert await served(r) == "t"  # the window has passed: the twin says so, and is not queued again
        record = store.get_twin("t")
        assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.node.missing")
        was, now = before.status, record.status
        assert (now.nodes, now.phase, now.last_step, now.observed_generation) == (
            was.nodes, was.phase, was.last_step, was.observed_generation)
        (n3,) = [n for n in now.nodes if n.name == "n3"]
        assert (n3.incarnation, n3.holds) == ("boot-1", was.bundle_id)  # still recorded, never made
        assert len(store.list_runs("t")) == 1
        assert driver.calls[calls:] == [("inspect", "t")] * 2  # nothing applied
        assert r.queue.waiting() == []
        (warning,) = warnings_of(caplog)
        assert "n3" in warning

        await r.reconcile("t")  # the next kick looks again, and the same holds: nothing written
        assert store.get_twin("t").revision == record.revision
        assert r.queue.waiting() == []

    asyncio.run(scenario())
    lab = driver.labs["t"]
    assert "n3" not in lab if how == "deleted" else not lab["n3"].running  # never made, never started


def test_a_node_back_within_its_window_at_its_incarnation_writes_nothing(store: LocalStore) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    r = restorer(store, driver, platforms=SHORT)

    async def scenario() -> None:
        stopped(driver, "n3")
        await r.reconcile("t")
        assert "t" in r._absent
        stopped(driver, "n3", stop=False)
        await r.reconcile("t")

    asyncio.run(scenario())
    record = store.get_twin("t")
    assert record.revision == before.revision and len(store.list_runs("t")) == 1
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert "t" not in r._absent


def test_a_missing_node_that_returns_at_another_incarnation_is_restored(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    r = restorer(store, driver, ready=ready, pusher=pusher, platforms=SHORT)
    asyncio.run(reported_missing(store, driver, r))
    returned = driver.replace("t", "n3")
    asyncio.run(r.reconcile("t"))

    run = newest(store)
    assert (run.operation, run.state) == ("restore", "ended")
    assert run.verdict is not None and run.verdict.status == "ok"
    assert seen(store, run.id) == [*pairs("ready", ["n3"]), *pairs("push", ["n3"]), *VERIFIED]
    assert [n for n, _ in ready.calls] == [n for n, _ in pusher.calls] == ["n3"]
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    (n3,) = [n for n in record.status.nodes if n.name == "n3"]
    assert (n3.incarnation, n3.holds) == (returned.incarnation, record.status.bundle_id)
    assert "t" not in r._absent


def test_a_twin_reported_missing_whose_nodes_all_run_again_is_verified_before_it_is_ready(store: LocalStore) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    r = restorer(store, driver, ready=ready, pusher=pusher, platforms=SHORT)
    asyncio.run(reported_missing(store, driver, r))
    stopped(driver, "n3", stop=False)  # at the incarnation the record holds
    calls = len(driver.calls)
    asyncio.run(r.reconcile("t"))

    run = newest(store)
    assert (run.operation, run.principal, run.state) == ("restore", "core", "ended")
    assert run.verdict is not None and run.verdict.status == "ok" and run.verdict.wait is not None
    assert seen(store, run.id) == VERIFIED  # nothing holds nothing: no node is readied or pushed
    assert pusher.calls == [] and ready.calls == []
    assert driver.calls[calls:] == [("inspect", "t")]
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert record.status.nodes == before.status.nodes and record.status.run_id is None


def test_a_node_missing_on_a_twin_whose_spec_is_not_met_writes_nothing(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    driver.recreates = {"n3"}
    respec(store, "testdata/blueprint/steps/three-node-n3-eos.json")
    asyncio.run(make(store, driver).reconcile("t"))
    refused = store.get_twin("t")
    assert (ready_of(refused).status, ready_of(refused).reason) == ("False", "step.restart.required")
    stopped(driver, "n3")
    r = restorer(store, driver, platforms=SHORT)

    async def scenario() -> None:
        await r.reconcile("t")
        await asyncio.sleep(1.1)
        await r.reconcile("t")

    asyncio.run(scenario())
    record = store.get_twin("t")
    assert record.revision == refused.revision  # the refusal's conditions stand: the twin does not run its spec
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "step.restart.required")
    assert [run.operation for run in store.list_runs("t")] == ["step", "create"]


def test_a_node_gone_during_a_restore_ends_it_failed_naming_the_node(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    driver.replace("t", "n2")
    killed(restorer(store, driver, pusher=fake_push(kill_after=0, driver=driver)))  # left in flight at n2's push
    run = newest(store)
    assert (run.operation, run.state) == ("restore", "running")
    del driver.labs["t"]["n3"]
    calls = len(driver.calls)
    r = restorer(store, driver, platforms=SHORT)

    async def scenario() -> None:
        await r.reconcile("t")  # the resume waits for n3 through its boot window
        assert store.get_run(run.id).state == "running" and store.get_twin("t").status.run_id == run.id
        await asyncio.sleep(1.1)
        await r.reconcile("t")

    asyncio.run(scenario())
    ended = store.get_run(run.id)
    assert ended.state == "ended" and ended.verdict is not None
    assert (ended.verdict.operation, ended.verdict.status) == ("restore", "failed")
    assert [(f.rule, f.severity, f.object) for f in ended.verdict.findings] == [("twin.node.missing", "error", "n3")]
    last = store.events(run.id)[-1]  # the ending event, naming the node
    assert (last.phase, last.outcome, last.node, last.rule) == ("ready", "failed", "n3", "twin.node.missing")
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.node.missing")
    assert record.status.run_id is None and record.status.generation_in_flight is None
    assert driver.calls[calls:] == [("inspect", "t")] * 2  # no apply, and no destroy: a restore tears nothing down
    assert record.status.deployment_id is not None and record.status.allocation is not None


def test_each_absent_nodes_boot_window_is_its_own_packages_readiness_window(store: LocalStore) -> None:
    driver = FakeDriver()
    probed = ready_twin(store, driver, PROBED)
    new_twin(store, file_blueprint(store, N3_EOS), "e")
    asyncio.run(make(store, driver).reconcile("e"))
    mixed = store.get_twin("e")
    r = make(store, driver)
    assert r._boot_windows(probed, ["n1-loop-a", "n2"]) == {"n1-loop-a": 30, "n2": 60}  # a ping host's, SR Linux's
    assert r._boot_windows(mixed, ["n2", "n3"]) == {"n2": 60, "n3": 90}  # SR Linux's, cEOS's
    assert make(store, driver, platforms={})._boot_windows(mixed, ["n3"]) == {"n3": 0}  # no package loaded


N3_EOS = "testdata/blueprint/steps/three-node-n3-eos.json"
EOS = PLATFORMS["arista_eos"]
SHORT_EOS = {**SHORT, EOS.id: dataclasses.replace(EOS, readiness=dataclasses.replace(EOS.readiness, timeout_s=2))}
"""`SHORT` with cEOS's readiness window shrunk to 2 s."""


def test_a_node_gone_after_another_is_not_reported_on_the_first_ones_clock(
    store: LocalStore, caplog: pytest.LogCaptureFixture
) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    r = restorer(store, driver, platforms=SHORT)

    async def scenario() -> None:
        stopped(driver, "n3")
        await r.reconcile("t")
        await asyncio.sleep(0.6)
        stopped(driver, "n2")  # as a drain evicts a twin's pods one after another
        await r.reconcile("t")
        await asyncio.sleep(0.6)
        await r.reconcile("t")  # n3's window has passed, and n2's has not: nothing is written
        record = store.get_twin("t")
        assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
        assert warnings_of(caplog) == [] and r.queue.waiting() == ["t"]
        await asyncio.sleep(0.6)
        await r.reconcile("t")  # both have passed: every absent node is reported, at once

    asyncio.run(scenario())
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.node.missing")
    (warning,) = warnings_of(caplog)
    assert "n2" in warning and "n3" in warning


def test_each_absent_node_is_waited_for_through_its_own_packages_window(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver, N3_EOS)  # n3 runs cEOS, 2 s here; n2 SR Linux, 1 s
    r = restorer(store, driver, N3_EOS, platforms=SHORT_EOS)

    def ready() -> tuple[str, str | None]:
        record = store.get_twin("t")
        return ready_of(record).status, ready_of(record).reason

    async def scenario() -> None:
        stopped(driver, "n3")
        await r.reconcile("t")  # n3's window ends at 2 s
        await asyncio.sleep(1.5)
        stopped(driver, "n2")
        await r.reconcile("t")  # n2's ends at 2.5 s, its own 1 s from its own sighting
        await asyncio.sleep(0.7)
        await r.reconcile("t")  # 2.2 s: n3's has passed, and n2's has not
        assert ready() == ("True", "twin.ready")
        await asyncio.sleep(0.5)
        await r.reconcile("t")  # 2.7 s: n2's has passed too, though cEOS's 2 s from its sighting would not have
        assert ready() == ("False", "twin.node.missing")

    asyncio.run(scenario())


def test_a_node_that_runs_again_drops_its_own_sighting_alone(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    r = restorer(store, driver, platforms=SHORT)

    async def scenario() -> None:
        stopped(driver, "n3")
        await r.reconcile("t")
        stopped(driver, "n2")
        await r.reconcile("t")
        first = dict(r._absent["t"])
        assert set(first) == {"n2", "n3"}
        stopped(driver, "n3", stop=False)
        await r.reconcile("t")
        assert r._absent["t"] == {"n2": first["n2"]}  # n2 keeps its own first sighting

    asyncio.run(scenario())


def test_a_node_first_seen_absent_after_a_step_is_waited_for(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    edited = edited_n1()
    blueprint_id, _ = store.put_blueprint(edited)
    r = make(store, driver, verifier=seeded(driver, edited)[0], platforms=SHORT)

    async def scenario() -> None:
        stopped(driver, "n3")
        await r.reconcile("t")  # n3 seen absent
        respec(store, blueprint_id=blueprint_id)
        await r.reconcile("t")  # the step's run is taken: the twin's sightings are dropped
        (run,) = steps(store)
        assert run.verdict is not None and run.verdict.status == "ok"
        await asyncio.sleep(1.1)
        await r.reconcile("t")  # n3 seen absent after the step: its window begins now

    asyncio.run(scenario())
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert "t" in r._absent


def test_a_node_replaced_and_not_yet_running_is_waited_for_then_restored_and_never_reported(
    store: LocalStore,
) -> None:
    """The clabernetes shape: a pod replaced, or a container restarted in place, reads not running at its new
    incarnation until it starts."""
    driver = FakeDriver()
    ready_twin(store, driver)
    new = driver.replace("t", "n3")
    driver.labs["t"]["n3"] = dataclasses.replace(new, running=False)
    pusher = fake_push(driver=driver)
    r = restorer(store, driver, pusher=pusher, platforms=SHORT)

    async def scenario() -> None:
        await r.reconcile("t")
        record = store.get_twin("t")
        assert "t" in r._absent and len(store.list_runs("t")) == 1
        assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
        driver.labs["t"]["n3"] = new  # it starts, inside its window
        await r.reconcile("t")

    asyncio.run(scenario())
    run = newest(store)
    assert run.operation == "restore" and run.verdict is not None and run.verdict.status == "ok"
    assert [n for n, _ in pusher.calls] == ["n3"]
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert "t" not in r._absent


def test_a_twin_deleted_while_a_node_was_missing_leaves_no_window_behind(store: LocalStore) -> None:
    """A twin made again under the name begins its own window: the old one's sighting is not carried to it."""
    driver = FakeDriver()
    ready_twin(store, driver)
    stopped(driver, "n3")
    r = restorer(store, driver, platforms=SHORT)

    async def scenario() -> None:
        await r.reconcile("t")
        assert "t" in r._absent
        request_deletion(store)
        await r.reconcile("t")

    asyncio.run(scenario())
    assert store.list_twins() == [] and "t" not in r._absent


# A restore's failures, its cancel, a deletion, its resume, and a spec written meanwhile (D-067): a restore that fails
# or is cancelled leaves the twin up and not diverged, and is not repeated; one that fails transiently is.

NO_SRLINUX_LOGIN = {k: v for k, v in ENVIRON.items() if not k.startswith("FYLGJA_CREDENTIAL_SRLINUX_")}


def assert_kept(record: TwinRecord, before: TwinRecord, driver: FakeDriver) -> None:
    """Nothing torn down and the twin not diverged: no `destroy`, and the record keeps the deployment, the allocation
    and the nodes `before` named."""
    was, now = before.status, record.status
    assert ("destroy", "t") not in driver.calls and "t" in driver.labs
    assert (now.deployment_id, now.allocation, [n.name for n in now.nodes]) == (
        was.deployment_id, was.allocation, [n.name for n in was.nodes])
    assert not any(c.type == "Diverged" and c.status == "True" for c in now.conditions)
    assert now.run_id is None and now.generation_in_flight is None


@pytest.mark.parametrize(("fault", "rule"), [("a refused push", "push.refused"),
                                             ("a node that never answers", "readiness.timeout"),
                                             ("a missing credential", "credential.missing")])
def test_a_refused_restore_ends_failed_and_the_next_kick_repeats_nothing(
    store: LocalStore, fault: str, rule: str
) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    replaced = driver.replace("t", "n2")
    kw: dict[str, Any] = {}
    if fault == "a refused push":
        kw["pusher"] = fake_push(refuse={"n2"}, driver=driver)
    elif fault == "a node that never answers":
        kw["ready"] = fake_ready(answers={"n1", "n3"}, driver=driver)
    else:
        kw["environ"] = NO_SRLINUX_LOGIN
    asyncio.run(restorer(store, driver, **kw).reconcile("t"))

    run = newest(store)
    assert (run.operation, run.state) == ("restore", "ended")
    assert run.verdict is not None and (run.verdict.operation, run.verdict.status) == ("restore", "failed")
    assert [(f.rule, f.object) for f in run.verdict.findings] == [(rule, "n2")]
    assert store.events(run.id)[-1].rule == rule
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", rule)
    nodes = {n.name: n for n in record.status.nodes}
    assert (nodes["n2"].incarnation, nodes["n2"].holds) == (replaced.incarnation, None)
    assert nodes["n1"].holds == nodes["n3"].holds == before.status.bundle_id
    assert_kept(record, before, driver)

    revision, runs, calls = record.revision, len(store.list_runs("t")), len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(restorer(store, driver, ready=ready, pusher=pusher).reconcile("t"))  # one that would succeed
    assert pusher.calls == [] and ready.calls == []  # nothing moved since: the refused push is not pushed again
    assert driver.calls[calls:] == [("inspect", "t")]
    assert store.get_twin("t").revision == revision and len(store.list_runs("t")) == runs


def test_a_transient_failure_in_a_restore_backs_off_and_the_next_pass_pushes(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    driver.replace("t", "n2")
    pusher = fake_push(unreachable={"n2"}, driver=driver)
    r = restorer(store, driver, pusher=pusher)

    async def scenario() -> Run:
        await r.reconcile("t")
        run = newest(store)
        assert (run.operation, run.state) == ("restore", "running")
        record = store.get_twin("t")
        assert record.status.run_id == run.id
        assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.restoring")
        assert r.backoff["t"] == 1.0
        await r.reconcile("t")  # the next pass resumes the same run
        return run

    run = asyncio.run(scenario())
    ended = store.get_run(run.id)
    assert ended.state == "ended" and ended.verdict is not None and ended.verdict.status == "ok"
    assert [each.operation for each in store.list_runs("t")] == ["restore", "create"]
    assert [n for n, _ in pusher.calls] == ["n2", "n2"]
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert r.backoff == {}


def test_a_restore_killed_at_its_push_resumes_inspects_again_and_pushes_the_node_once_at_its_newest_incarnation(
    store: LocalStore,
) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    driver.replace("t", "n2")
    killed(restorer(store, driver, pusher=fake_push(kill_after=0, driver=driver)))
    run = newest(store)
    assert (run.operation, run.state) == ("restore", "running")
    third = driver.replace("t", "n2")  # replaced once more while its restore waits to be resumed
    calls = len(driver.calls)
    pusher = fake_push(driver=driver)
    asyncio.run(restorer(store, driver, pusher=pusher).reconcile("t"))

    assert [each.id for each in store.list_runs("t") if each.operation == "restore"] == [run.id]
    ended = store.get_run(run.id)
    assert ended.state == "ended" and ended.verdict is not None and ended.verdict.status == "ok"
    assert [n for n, _ in pusher.calls] == ["n2"]
    assert driver.calls[calls:] == [("inspect", "t")]  # inspected again; nothing applied
    record = store.get_twin("t")
    (n2,) = [n for n in record.status.nodes if n.name == "n2"]
    assert (n2.incarnation, n2.holds) == (third.incarnation, record.status.bundle_id)
    assert third.incarnation == "boot-3"


def test_a_cancelled_restore_ends_failed_tears_nothing_down_and_is_not_repeated(store: LocalStore) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    driver.replace("t", "n2")
    pusher = CancellingPush(store, driver, operation="restore")  # n2 pushed, then a client's cancel
    asyncio.run(restorer(store, driver, pusher=pusher).reconcile("t"))

    run = newest(store)
    assert run.operation == "restore"
    assert_cancelled(run)
    assert run.verdict is not None and run.verdict.operation == "restore"
    assert seen(store, run.id) == [*pairs("ready", ["n2"]), *pairs("push", ["n2"]), *CANCELLED]
    assert store.events(run.id)[-1].rule == "run.cancelled"
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "run.cancelled")
    assert_kept(record, before, driver)

    revision, calls = record.revision, len(driver.calls)
    asyncio.run(restorer(store, driver).reconcile("t"))  # the next kick: nothing moved since, nothing written
    assert store.get_twin("t").revision == revision
    assert [each.operation for each in store.list_runs("t")] == ["restore", "create"]
    assert driver.calls[calls:] == [("inspect", "t")]


def test_a_deletion_finding_a_restore_in_flight_cancels_it_then_tears_the_twin_down(store: LocalStore) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    driver.replace("t", "n2")
    killed(restorer(store, driver, pusher=fake_push(kill_after=0, driver=driver)))  # left in flight at n2's push
    restore = newest(store)
    assert (restore.operation, restore.state) == ("restore", "running")
    destroy = request_deletion(store)
    calls = len(driver.calls)
    asyncio.run(restorer(store, driver).reconcile("t"))

    with pytest.raises(NotFound):
        store.get_twin("t")
    ended = store.get_run(restore.id)
    assert_cancelled(ended)
    assert seen(store, restore.id)[-2:] == CANCELLED
    assert ended.verdict is not None and "where it stood" in ended.verdict.findings[0].message  # its cancel path's
    verdict = store.get_run(destroy.id).verdict
    assert verdict is not None and verdict.status == "ok"
    assert verdict.subject.deployment_id == before.status.deployment_id  # the destroy run found the deployment kept
    assert driver.calls[calls:] == [("destroy", "t")]  # the restore's cancel tore nothing down: the destroy run did
    assert "t" not in driver.labs


def test_a_restore_in_flight_is_not_resumed_once_the_twins_deletion_is_asked_though_its_run_is_not_marked(
    store: LocalStore,
) -> None:
    """A deletion asked between a pass's `inspect` and its take of the restore leaves the run unmarked: the next pass
    cancels it where it stands, readying and pushing nothing, and then tears the twin down."""
    driver = FakeDriver()
    ready_twin(store, driver)
    driver.replace("t", "n2")
    killed(restorer(store, driver, pusher=fake_push(kill_after=0, driver=driver)))  # left in flight at n2's push
    restore = newest(store)
    request_deletion(store, mark=False)
    assert store.get_run(restore.id).state == "running"
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    calls = len(driver.calls)
    asyncio.run(restorer(store, driver, ready=ready, pusher=pusher).reconcile("t"))

    assert ready.calls == [] and pusher.calls == []  # never resumed
    assert driver.calls[calls:] == [("destroy", "t")]
    ended = store.get_run(restore.id)
    assert_cancelled(ended)
    assert seen(store, restore.id)[-2:] == CANCELLED
    with pytest.raises(NotFound):
        store.get_twin("t")


def test_a_spec_written_during_a_restore_is_stepped_to_in_the_same_pass(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    replaced = driver.replace("t", "n2")
    inner = fake_push(driver=driver)
    written: list[TwinRecord] = []

    async def writes_a_spec(address: str, package: Any, config: str, credential: Any) -> Any:
        if not written:  # a client's PUT while the restore pushes n2
            written.append(respec(store, TWO_NODE))
        return await inner(address, package, config, credential)

    asyncio.run(restorer(store, driver, pusher=writes_a_spec).reconcile("t"))

    assert [each.operation for each in store.list_runs("t")] == ["step", "restore", "create"]
    restore = the_run(store, "restore")
    assert restore.verdict is not None and restore.verdict.status == "ok"
    assert [e for e in seen(store, restore.id) if e[0] == "push"] == pairs("push", ["n2"])
    (step,) = steps(store)
    assert step.verdict is not None and step.verdict.status == "ok"
    record = store.get_twin("t")
    assert record.status.observed_generation == record.generation == 2
    assert record.status.last_step is not None and record.status.last_step.outcome == "stepped"
    # The step read the nodes the restore recorded: n2, at its new incarnation and holding what it was pushed, is not
    # waited for again.
    assert [e for e in seen(store, step.id) if e[0] == "ready"] == []
    (n2,) = [n for n in record.status.nodes if n.name == "n2"]
    assert n2.incarnation == replaced.incarnation


@pytest.mark.parametrize("left", ["backing off", "by a stopped core"])
def test_a_spec_written_while_a_restore_waits_to_be_resumed_is_stepped_to_by_the_pass_that_ends_it(
    store: LocalStore, left: str
) -> None:
    """A kick while a restore backs off merges into its waiting entry, and a restarted core queues each twin once: the
    pass that resumes and ends the restore is the only one the spec gets, so it goes on to the step."""
    driver = FakeDriver()
    ready_twin(store, driver)
    driver.replace("t", "n2")
    if left == "by a stopped core":
        killed(restorer(store, driver, pusher=fake_push(kill_after=0, driver=driver)))
        r = restorer(store, driver)
    else:
        r = restorer(store, driver, pusher=fake_push(unreachable={"n2"}, driver=driver))

    async def go() -> list[str]:
        if left == "backing off":
            await r.reconcile("t")  # n2's push is unreachable: the restore is in flight, backing off
            assert r.queue.waiting() == ["t"]
        assert newest(store).state == "running"
        respec(store, TWO_NODE)  # a client's spec, then its kick
        r.queue.put("t")
        name = await r.queue.get()  # at once: the kick moved the backoff's deadline up
        await r.reconcile(name)
        r.queue.done(name)
        return r.queue.waiting()

    waiting = asyncio.run(go())
    record = store.get_twin("t")
    assert [run.operation for run in store.list_runs("t")] == ["step", "restore", "create"]
    assert record.generation == record.status.observed_generation == 2 and record.status.run_id is None
    assert waiting == []  # nothing left for the resync


def test_a_cancelled_restore_whose_node_is_absent_is_cancelled_without_waiting_out_its_window(
    store: LocalStore,
) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    driver.replace("t", "n2")
    killed(restorer(store, driver, pusher=fake_push(kill_after=0, driver=driver)))  # left in flight at n2's push
    run = newest(store)
    stopped(driver, "n3")
    r = restorer(store, driver, platforms=SHORT)

    async def scenario() -> None:
        await r.reconcile("t")  # the resume waits for n3 through its boot window
        assert store.get_run(run.id).state == "running" and r.queue.waiting() == ["t"]
        mark_cancelling(store, run.id)
        await asyncio.sleep(1.1)  # past n3's window: an inspect now would end the restore for n3
        calls = len(driver.calls)
        await r.reconcile("t")  # the cancel is read first
        assert driver.calls[calls:] == []

    asyncio.run(scenario())
    ended = store.get_run(run.id)
    assert_cancelled(ended)
    assert seen(store, run.id)[-2:] == CANCELLED
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "run.cancelled")
    assert_kept(record, before, driver)


@pytest.mark.parametrize("how", ["keeps failing", "never answers"])
def test_a_cancelled_restore_waits_on_no_inspect(store: LocalStore, how: str) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    driver.replace("t", "n2")
    r = restorer(store, driver, pusher=fake_push(unreachable={"n2"}, driver=driver))

    async def scenario() -> Run:
        await r.reconcile("t")  # the restore backs off
        run = newest(store)
        if how == "keeps failing":
            driver.fail_inspect_once = True
            await r.reconcile("t")  # its resume's inspect fails: it backs off again
            assert r.backoff["t"] == 2.0 and store.get_run(run.id).state == "running"
            mark_cancelling(store, run.id)
            driver.fail_inspect_once = True  # and would fail again
            calls = len(driver.calls)
            await r.reconcile("t")  # the cancel is read before the inspect
            assert driver.calls[calls:] == [] and driver.fail_inspect_once
        else:
            driver.block = "inspect"
            calls = len(driver.calls)
            resume = asyncio.create_task(r.reconcile("t"))
            await until(lambda: ("inspect", "t") in driver.calls[calls:])
            mark_cancelling(store, run.id)  # the cancel stops the inspect it waits on
            await asyncio.wait_for(resume, timeout=5)
            driver.block = None
        return run

    run = asyncio.run(scenario())
    assert_cancelled(store.get_run(run.id))
    assert seen(store, run.id)[-2:] == CANCELLED
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "run.cancelled")
    assert_kept(record, before, driver)
    assert r.backoff == {}


@pytest.mark.parametrize("taken", ["destroy", "step"])
def test_a_restore_run_left_queued_is_ended_by_the_next_run_taken(store: LocalStore, taken: str) -> None:
    """A restore whose take was cut short before the record named it: the deletion's sweep ends it, and so does a step
    taken afresh, as either ends a create or step run that never started."""
    driver = FakeDriver()
    ready_twin(store, driver)
    stray = queued("t", "restore", "core")
    store.create_run(stray)
    if taken == "destroy":
        request_deletion(store)
    else:
        respec(store, TWO_NODE)
    asyncio.run(restorer(store, driver).reconcile("t"))

    ended = store.get_run(stray.id)
    assert_cancelled(ended)
    assert ended.verdict is not None and ended.verdict.operation == "restore"
    message = ended.verdict.findings[0].message
    assert ("deletion" in message) if taken == "destroy" else (the_run(store, "step").id in message)
    assert seen(store, stray.id) == CANCELLED


def test_a_restore_run_left_queued_by_a_take_cut_short_is_ended_by_the_pass_that_reports_its_node_missing(
    killing: KillingStore,
) -> None:
    """A core killed after it made a restore's run and before the record named it, and then the node gone for good:
    no pass takes a restore while a node is missing, so the pass that reports it ends the run left queued, as the
    sweep ends a create's or a step's that never started, its message saying why."""
    driver = FakeDriver()
    ready_twin(killing, driver)
    driver.replace("t", "n2")
    killing.kill_created = "restore"
    killed(restorer(killing, driver))
    (stray,) = [run for run in killing.list_runs("t") if run.operation == "restore"]
    assert stray.state == "queued" and killing.get_twin("t").status.run_id is None
    stopped(driver, "n2")  # and it stays down
    r = restorer(killing, driver, platforms=SHORT)

    async def scenario() -> None:
        await r.reconcile("t")  # inside n2's boot window: nothing written
        assert killing.get_run(stray.id).state == "queued"
        await asyncio.sleep(1.1)
        await r.reconcile("t")  # past it: n2 reported missing

    asyncio.run(scenario())
    record = killing.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.node.missing")
    ended = killing.get_run(stray.id)
    assert_cancelled(ended)
    assert ended.verdict is not None and "missing past its boot window" in ended.verdict.findings[0].message
    assert seen(killing, stray.id) == CANCELLED
    assert [run.operation for run in killing.list_runs("t")] == ["restore", "create"]


# A step to the bundle the twin runs (D-050's unchanged step) where a restore that failed or was cancelled left a node
# holding nothing: it readies, pushes and verifies what holds nothing, so a new spec is a client's remedy, and it never
# reports Ready over a node that holds nothing.

SAME_BUNDLE = "testdata/blueprint/three-node.json"
"""A `three-node` twin's own blueprint: a spec of it (with `allow_restart` toggled) compiles to the bundle it runs."""
COMPILED: list[Seen] = [("compile", "started", None), ("compile", "done", None)]


def left_holding_nothing(store: LocalStore, driver: FakeDriver, how: str) -> None:
    """`n2` of a Ready `t` replaced, and its restore refused at the push, or cancelled before it: `n2` recorded at its
    new incarnation holding nothing, and Ready False for the restore's rule."""
    driver.replace("t", "n2")
    if how == "refused":
        asyncio.run(restorer(store, driver, pusher=fake_push(refuse={"n2"}, driver=driver)).reconcile("t"))
    else:
        r = restorer(store, driver, pusher=fake_push(unreachable={"n2"}, driver=driver))

        async def cancelled() -> None:
            await r.reconcile("t")  # the restore backs off before n2 holds anything
            mark_cancelling(store, newest(store).id)
            await r.reconcile("t")

        asyncio.run(cancelled())
    (n2,) = [n for n in store.get_twin("t").status.nodes if n.name == "n2"]
    assert n2.holds is None


@pytest.mark.parametrize(("how", "rule"), [("refused", "push.refused"), ("cancelled", "run.cancelled")])
def test_a_step_to_the_running_bundle_pushes_the_node_a_restore_left_holding_nothing_and_only_then_is_ready(
    store: LocalStore, how: str, rule: str
) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    left_holding_nothing(store, driver, how)
    assert ready_of(store.get_twin("t")).reason == rule
    respec(store, SAME_BUNDLE, allow_restart=True)
    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), RecordingPush(store, driver)
    asyncio.run(restorer(store, driver, ready=ready, pusher=pusher).reconcile("t"))

    (step,) = steps(store)
    assert step.verdict is not None and (step.verdict.operation, step.verdict.status) == ("step", "ok")
    assert seen(store, step.id) == [*COMPILED, *pairs("ready", ["n2"]), *pairs("push", ["n2"]), *VERIFIED]
    assert [n for n, _ in ready.calls] == [n for n, _ in pusher.calls] == ["n2"]
    (at_push,) = pusher.records
    assert (ready_of(at_push).status, ready_of(at_push).reason) == ("False", rule)  # not Ready before it is pushed
    assert step.verdict.wait is not None and step.verdict.wait.outcome == "settled"
    assert driver.calls[calls:] == []  # no plan, changes, apply or destroy: nothing of the lab changes
    record = store.get_twin("t")
    bundle_id = before.status.bundle_id
    assert bundle_id is not None
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert all(n.holds == bundle_id for n in record.status.nodes)
    assert record.status.observed_generation == record.generation == 2 and record.status.run_id is None
    assert record.status.last_step == LastStep(outcome="unchanged", from_=bundle_id, to=bundle_id, phase="compiled",
                                               run_id=step.id)
    assert (record.status.deployment_id, record.status.allocation) == (before.status.deployment_id,
                                                                       before.status.allocation)


def test_a_spec_to_the_running_bundle_written_during_a_refused_restore_pushes_the_node_in_the_same_pass(
    store: LocalStore,
) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    driver.replace("t", "n2")
    inner = fake_push(driver=driver)
    written: list[TwinRecord] = []

    async def refuses_once_and_writes_a_spec(address: str, package: Any, config: str, credential: Any) -> Any:
        if not written:  # the restore's push of n2: refused, while a client writes a spec of the bundle the twin runs
            written.append(respec(store, SAME_BUNDLE, allow_restart=True))
            return push.Refused("At line 1: n2 refused the configuration")
        return await inner(address, package, config, credential)

    asyncio.run(restorer(store, driver, pusher=refuses_once_and_writes_a_spec).reconcile("t"))

    restore = the_run(store, "restore")
    assert restore.verdict is not None and restore.verdict.status == "failed"
    (step,) = steps(store)
    assert step.verdict is not None and step.verdict.status == "ok"
    assert [n for n, _ in inner.calls] == ["n2"]  # pushed under the step
    assert [e for e in seen(store, step.id) if e[0] == "push"] == pairs("push", ["n2"])
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert all(n.holds == before.status.bundle_id for n in record.status.nodes)
    assert record.status.observed_generation == record.generation == 2


def test_a_step_to_the_running_bundle_whose_push_is_refused_leaves_the_twin_up_and_not_diverged(
    store: LocalStore,
) -> None:
    driver = FakeDriver()
    before = ready_twin(store, driver)
    replaced = driver.replace("t", "n2")
    refusing = fake_push(refuse={"n2"}, driver=driver)
    written: list[TwinRecord] = []

    async def writes_a_spec(address: str, package: Any, config: str, credential: Any) -> Any:
        if not written:  # during the restore's push of n2, which is refused, and so is the step's
            written.append(respec(store, SAME_BUNDLE, allow_restart=True))
        return await refusing(address, package, config, credential)

    asyncio.run(restorer(store, driver, pusher=writes_a_spec).reconcile("t"))

    (step,) = steps(store)
    assert step.state == "ended" and step.verdict is not None
    assert (step.verdict.operation, step.verdict.status) == ("step", "failed")
    assert [(f.rule, f.object) for f in step.verdict.findings] == [("push.refused", "n2")]
    assert [n for n, _ in refusing.calls] == ["n2", "n2"]  # the restore's push, then the step's
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "push.refused")
    assert (condition_of(record, "Stepping").status, condition_of(record, "Stepping").reason) == (
        "False", "push.refused")
    assert_kept(record, before, driver)  # up, nothing destroyed, the record kept, not diverged
    (n2,) = [n for n in record.status.nodes if n.name == "n2"]
    assert (n2.incarnation, n2.holds) == (replaced.incarnation, None)
    assert record.status.observed_generation == record.generation == 2
    bundle_id = before.status.bundle_id
    assert bundle_id is not None
    assert record.status.last_step == LastStep(outcome="rejected", from_=bundle_id, to=bundle_id, phase="compiled",
                                               run_id=step.id)


def test_a_step_to_the_running_bundle_leaves_a_twin_reported_missing_so(store: LocalStore) -> None:
    driver = FakeDriver()
    ready_twin(store, driver)
    r = restorer(store, driver, platforms=SHORT)
    asyncio.run(reported_missing(store, driver, r))  # n3 stopped past its window, at the incarnation it held
    respec(store, SAME_BUNDLE, allow_restart=True)
    calls = len(driver.calls)
    asyncio.run(r.reconcile("t"))

    (step,) = steps(store)
    assert step.verdict is not None and step.verdict.status == "ok"
    assert seen(store, step.id) == COMPILED  # every device node holds the bundle: nothing to push
    assert driver.calls[calls:] == []
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("False", "twin.node.missing")  # the settled pass's
    assert record.status.observed_generation == record.generation == 2 and record.status.run_id is None
    assert record.status.last_step is not None and record.status.last_step.outcome == "unchanged"


def test_a_step_to_the_running_bundle_of_a_twin_whose_every_device_node_holds_it_ends_at_compiled(
    store: LocalStore,
) -> None:
    """A probe host holds no bundle: the shortcut counts the device nodes alone."""
    driver = FakeDriver()
    ready_twin(store, driver, PROBED)
    respec(store, PROBED, allow_restart=True)
    calls = len(driver.calls)
    asyncio.run(make(store, driver).reconcile("t"))

    (step,) = steps(store)
    assert step.verdict is not None and step.verdict.status == "ok"
    assert seen(store, step.id) == COMPILED
    assert driver.calls[calls:] == []  # no host readied through exec
    record = store.get_twin("t")
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")


@pytest.mark.parametrize("kill_event", [("ready", "done"), ("push", "done"), ("verify", "started")],
                         ids=["ready done", "push done", "verify started"])
def test_a_step_to_the_running_bundle_killed_once_it_began_to_ready_finishes_and_ends_with_counts(
    killing: KillingStore, kill_event: tuple[str, str]
) -> None:
    """A step to the bundle the twin runs records no phase, so its resume reads its events: once it began to ready, it
    finishes what it began, readying and pushing what still holds nothing and verifying, and neither compiles again nor
    takes the shortcut a step that pushed nothing takes. Killed after n2's ready, n2 still holds nothing: a resume that
    compiled again would read the spec a client wrote meanwhile under this run."""
    driver = FakeDriver()
    ready_twin(killing, driver)
    left_holding_nothing(killing, driver, "refused")
    respec(killing, SAME_BUNDLE, allow_restart=True)
    killing.kill_event = kill_event
    killed(restorer(killing, driver))
    (step,) = steps(killing)
    assert step.state == "running"
    calls = len(driver.calls)
    ready, pusher = fake_ready(driver=driver), fake_push(driver=driver)
    asyncio.run(restorer(killing, driver, ready=ready, pusher=pusher).reconcile("t"))

    ended = killing.get_run(step.id)
    assert ended.verdict is not None and (ended.verdict.operation, ended.verdict.status) == ("step", "ok")
    assert ended.verdict.counts is not None
    assert ended.verdict.wait is not None and ended.verdict.wait.outcome == "settled"
    if kill_event == ("ready", "done"):  # n2 readied and not pushed: readied again, then pushed
        killed_run, readied = pairs("ready", ["n2"]), ["n2"]
    else:  # n2 holds the bundle already
        cut = [("verify", "started", None)] if kill_event == ("verify", "started") else []
        killed_run, readied = [*pairs("ready", ["n2"]), *pairs("push", ["n2"]), *cut], []
    resume = [*pairs("ready", readied), *pairs("push", readied)]
    assert resumed(killing, step.id, "step") == [*COMPILED, *killed_run, *resume, *VERIFIED]  # no second compile
    assert [node for node, _ in ready.calls] == readied and [node for node, _ in pusher.calls] == readied
    assert driver.calls[calls:] == []
    record = killing.get_twin("t")
    bundle_id = record.status.bundle_id
    assert bundle_id is not None
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
    assert record.status.last_step == LastStep(outcome="unchanged", from_=bundle_id, to=bundle_id, phase="compiled",
                                               run_id=step.id)
    assert record.status.observed_generation == record.generation == 2 and record.status.run_id is None


def test_a_spec_written_while_a_step_to_the_running_bundle_backs_off_is_stepped_to_by_the_next_run(
    store: LocalStore,
) -> None:
    """The resume of a step to the bundle the twin runs, past `compiled`, compiles no spec again: one a client wrote
    during its backoff is not admitted, planned or applied under the older generation's run, and is the next run's."""
    driver = FakeDriver()
    before = ready_twin(store, driver)
    left_holding_nothing(store, driver, "refused")
    respec(store, SAME_BUNDLE, allow_restart=True)
    r = restorer(store, driver, pusher=fake_push(unreachable={"n2"}, driver=driver))

    async def backed_off() -> TwinRecord:
        await r.reconcile("t")  # n2's push is unreachable: the step backs off, n2 still holding nothing
        assert steps(store)[0].state == "running"
        newer = respec(store, TWO_NODE)  # a client's spec, during the backoff
        calls = len(driver.calls)
        await r.reconcile("t")  # the resume pushes n2 and verifies, to the bundle the twin runs
        assert driver.calls[calls:] == []  # no admit, plan, changes or apply of the newer spec
        return newer

    newer = asyncio.run(backed_off())
    (step,) = steps(store)
    assert step.verdict is not None and (step.verdict.status, step.verdict.subject.bundle_id) == (
        "ok", before.status.bundle_id)
    assert step.verdict.counts is not None
    assert [e for e in seen(store, step.id) if e[0] == "compile"] == COMPILED
    record = store.get_twin("t")
    bundle_id = before.status.bundle_id
    assert bundle_id is not None
    assert (record.status.bundle_id, record.status.deployment_id) == (bundle_id, before.status.deployment_id)
    assert record.status.last_step == LastStep(outcome="unchanged", from_=bundle_id, to=bundle_id, phase="compiled",
                                               run_id=step.id)
    assert (record.generation, record.status.observed_generation, record.status.run_id) == (3, 2, None)

    asyncio.run(restorer(store, driver, TWO_NODE).reconcile("t"))  # the next pass steps to the newer spec
    first, second = steps(store)
    assert first.id == step.id
    assert_stepped(store, newer, second)


# The trigger (D-058): the driver names a twin whose runtime changed, and the loop's task queues it, so a node the
# runtime replaced is restored without waiting for the resync.


def errors_of(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The ERROR records so far, of any logger."""
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_drivers_event_restores_a_replaced_node_without_the_resync(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver()
    r = restorer(store, driver, resync_s=3600)

    def restored() -> bool:
        return any(run.operation == "restore" and run.verdict is not None and run.verdict.status == "ok"
                   for run in store.list_runs("t"))

    async def scenario() -> None:
        await r.start()
        await until(lambda: is_ready(store, "t"))
        driver.replace("t", "n2")
        driver.emit("t")
        await until(restored)
        await r.stop()

    asyncio.run(scenario())
    record = store.get_twin("t")
    (n2,) = [n for n in record.status.nodes if n.name == "n2"]
    assert (n2.incarnation, n2.holds) == (driver.labs["t"]["n2"].incarnation, record.status.bundle_id)
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")


def test_an_event_naming_no_twin_is_dropped(store: LocalStore, caplog: pytest.LogCaptureFixture) -> None:
    blueprint_id = file_blueprint(store)
    driver = FakeDriver()
    r = restorer(store, driver, resync_s=3600)

    async def scenario() -> None:
        await r.start()
        driver.emit("nobody")
        new_twin(store, blueprint_id, "c")
        driver.emit("c")
        await until(lambda: is_ready(store, "c"))
        await r.stop()

    asyncio.run(scenario())
    assert store.list_runs("nobody") == []
    assert [run.twin for run in store.list_runs()] == ["c"]
    assert errors_of(caplog) == []


class EndsOnce(FakeDriver):
    """A fake whose first `events` ends at once, naming nothing, as a driver that breaks the seam's contract."""

    def __init__(self) -> None:
        super().__init__()
        self.ended = False

    async def events(self) -> AsyncIterator[str]:
        if not self.ended:
            self.ended = True
            return
        async for name in super().events():
            yield name


@pytest.mark.parametrize("fault", ["raises", "ends"])
def test_a_driver_whose_events_fail_is_asked_again(
    store: LocalStore, caplog: pytest.LogCaptureFixture, fault: str
) -> None:
    blueprint_id = file_blueprint(store)
    driver = FakeDriver() if fault == "raises" else EndsOnce()
    driver.fail_events_once = fault == "raises"  # its first `events` raises, or ends
    r = restorer(store, driver, resync_s=3600, events_retry_s=0.01)

    async def scenario() -> None:
        await r.start()
        await until(lambda: errors_of(caplog) != [])
        new_twin(store, blueprint_id, "c")
        driver.emit("c")  # served by the `events` the loop asks for again
        await until(lambda: is_ready(store, "c"))
        await r.stop()

    asyncio.run(scenario())
    (error,) = errors_of(caplog)
    assert error.name == "fylgja.reconcile" and "fake" in error.getMessage()
    assert (error.exc_info is not None) == (fault == "raises")  # a traceback for what was raised
    assert not driver.fail_events_once


# An event never brings a twin's pass forward of its backoff (D-070 item 18): a runtime's own events follow every apply
# and destroy, so a pass that failed after changing the runtime is kicked by its own events. A client's write still
# brings it forward, as it did before. These run on a fake clock (`Skipping`), so a backoff's seconds pass at once.


class Clocked(FakeDriver):
    """A fake that keeps the loop's time at each `apply` and each `inspect` it is asked for."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.applied: list[float] = []
        self.inspected: list[float] = []

    async def apply(
        self,
        deployment: deployment.Deployment,
        files: Mapping[str, bytes],
        platforms: Mapping[str, platform_package.PlatformPackage],
        probe_packages: Mapping[str, probe_package.ProbePackage],
        reconfigure: bool = False,
    ) -> None:
        self.applied.append(asyncio.get_running_loop().time())
        await super().apply(deployment, files, platforms, probe_packages, reconfigure)

    async def inspect(self, twin: str) -> Inspection:
        self.inspected.append(asyncio.get_running_loop().time())
        return await super().inspect(twin)


def gaps(times: list[float]) -> list[float]:
    return [b - a for a, b in itertools.pairwise(times)]


def test_a_failing_apply_whose_driver_names_the_twin_is_retried_at_the_backoffs_pace(store: LocalStore) -> None:
    """A deploy that fails after its containers changed: the fake's `apply` names the twin each time, as a real
    runtime's events do, and fails. Each pass's own event is folded into its retry, which comes as the backoff ends:
    five applies in 20 s, 1, 2, 4 and 8 s apart, never hundreds back to back."""
    new_twin(store, file_blueprint(store))
    driver = Clocked(fail_apply=True, own_events=True)
    r = make(store, driver, resync_s=3600)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        await r.start()
        began = loop.time()
        try:
            while len(driver.applied) < 10 and loop.time() < began + 20:
                await asyncio.sleep(0.01)
        finally:
            await r.stop()

    bounded(scenario, loop=Skipping())
    assert gaps(driver.applied) == pytest.approx([1.0, 2.0, 4.0, 8.0], abs=0.1)
    assert r.backoff == {"t": 16.0}


class Faulty(Clocked):
    """A fake whose `apply` names its twin, as a runtime's events do, then fails outside the seam's contract."""

    async def apply(self, *args: Any, **kw: Any) -> None:
        self.applied.append(asyncio.get_running_loop().time())
        self.emit(args[0].twin)
        raise RuntimeError("a fault the seam does not declare")


def test_a_pass_that_fails_outside_the_seams_contract_is_retried_at_the_backoffs_pace_too(
    store: LocalStore, caplog: pytest.LogCaptureFixture
) -> None:
    """A fault the loop does not class is the worker's to log, with its traceback. The twin still waits out a backoff
    before its next pass, which its own events do not shorten: such a pass was served again at once, for ever."""
    new_twin(store, file_blueprint(store))
    driver = Faulty()
    r = make(store, driver, resync_s=3600)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        await r.start()
        began = loop.time()
        try:
            while len(driver.applied) < 10 and loop.time() < began + 20:
                await asyncio.sleep(0.01)
        finally:
            await r.stop()

    with caplog.at_level(logging.ERROR, logger="fylgja"):
        bounded(scenario, loop=Skipping())
    assert gaps(driver.applied) == pytest.approx([1.0, 2.0, 4.0, 8.0], abs=0.1)
    assert r.backoff == {"t": 16.0}
    logged = [record for record in caplog.records if record.name == "fylgja.queue" and record.exc_info is not None]
    assert len(logged) == len(driver.applied)  # each failure logged once, by the worker, as before


def test_an_event_received_while_a_twin_backs_off_does_not_bring_its_retry_forward(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = Clocked(fail_apply=True)  # it names nothing of its own
    r = make(store, driver, resync_s=3600)

    async def scenario() -> None:
        await r.start()
        try:
            await until(lambda: r.backoff.get("t") == 1.0)
            await asyncio.sleep(0.5)
            driver.emit("t")  # half way through the backoff
            await until(lambda: len(driver.applied) == 2)
        finally:
            await r.stop()

    bounded(scenario, loop=Skipping())
    assert gaps(driver.applied) == pytest.approx([1.0], abs=0.1)


def test_a_clients_write_while_a_twin_backs_off_brings_its_pass_forward_as_it_always_did(store: LocalStore) -> None:
    """A client's write kicks its twin (`kick`), which the queue serves at once, the backoff's later deadline lost."""
    new_twin(store, file_blueprint(store))
    driver = Clocked(fail_apply=True)
    r = make(store, driver, resync_s=3600)

    async def scenario() -> None:
        await r.start()
        try:
            await until(lambda: r.backoff.get("t") == 1.0)
            await asyncio.sleep(0.5)
            r.kick("t")  # half way through the backoff
            # The pass it brought forward has failed and grown the backoff: a stop as its apply begins would cut it.
            await until(lambda: len(driver.applied) == 2 and r.backoff.get("t") == 2.0)
        finally:
            await r.stop()

    bounded(scenario, loop=Skipping())
    assert gaps(driver.applied) == pytest.approx([0.5], abs=0.1)
    assert r.backoff == {"t": 2.0}  # the pass it brought forward failed too: the backoff grows as before


def test_a_create_that_completes_is_followed_by_one_settled_pass_for_its_own_events(store: LocalStore) -> None:
    new_twin(store, file_blueprint(store))
    driver = FakeDriver(own_events=True)
    r = make(store, driver, resync_s=3600)

    async def scenario() -> None:
        await r.start()
        try:
            await until(lambda: is_ready(store, "t"))
            await asyncio.sleep(30)  # every pass the create's events cause has run by now
        finally:
            await r.stop()

    bounded(scenario, loop=Skipping())
    create = [("admit", "t"), ("plan", "t"), ("inspect", "t"), ("apply", "t"), ("inspect", "t")]
    assert driver.calls == [*create, ("inspect", "t")]  # then one settled pass, which writes nothing
    assert [run.operation for run in store.list_runs("t")] == ["create"]


def test_a_node_replaced_while_its_twin_backs_off_is_restored_by_the_pass_the_backoffs_end_brings(
    store: LocalStore,
) -> None:
    """`n2`'s restore backs off at its push; `n3` is replaced half way through the backoff, and its event folded into
    the retry, which comes as the backoff ends: one pass inspects again and pushes both."""
    driver = Clocked()
    ready_twin(store, driver)
    driver.replace("t", "n2")
    pusher = fake_push(unreachable={"n2"}, driver=driver)
    r = restorer(store, driver, pusher=pusher, resync_s=3600)
    since = len(driver.inspected)

    async def scenario() -> None:
        await r.start()  # the twin queued: the restore, which backs off
        try:
            await until(lambda: r.backoff.get("t") == 1.0)
            await asyncio.sleep(0.5)
            driver.replace("t", "n3")
            driver.emit("t")
            await until(lambda: newest(store).state == "ended")
        finally:
            await r.stop()

    bounded(scenario, loop=Skipping())
    restore = newest(store)
    assert restore.operation == "restore" and restore.verdict is not None and restore.verdict.status == "ok"
    assert [n for n, _ in pusher.calls] == ["n2", "n2", "n3"]
    assert gaps(driver.inspected[since:]) == pytest.approx([1.0], abs=0.1)
    record = store.get_twin("t")
    nodes = {n.name: n for n in record.status.nodes}
    for node in ("n2", "n3"):
        assert (nodes[node].incarnation, nodes[node].holds) == (driver.labs["t"][node].incarnation,
                                                                record.status.bundle_id)
    assert (ready_of(record).status, ready_of(record).reason) == ("True", "twin.ready")
