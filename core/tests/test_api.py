"""API 1 served over a local store in a temporary directory, the shipped packages and the reconcile
loop on a fake driver (formats/api-1.openapi.yaml, D-025, D-039). Every answer is held to the
operation its request names in the OpenAPI document (its status, media type and body), or, for a
path API 1 does not have, to problem-1."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from dataclasses import replace as dataclasses_replace
from importlib.metadata import version
from pathlib import Path
from typing import Any

import fake_api
import httpx2
import pytest
import uvicorn
import yaml
from fakes import FakeDriver, FakeReader, fake_push, fake_ready
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fylgja_core import blueprint, bundle, deployment, packages, run, schemas
from fylgja_core.capacity import Reading
from fylgja_core.client import Message, messages
from fylgja_core.credentials import Provider
from fylgja_core.deployment import Demand
from fylgja_core.driver import Planned, Refusal, Unplannable
from fylgja_core.findings import Finding, Subject, Verdict
from fylgja_core.local_store import LocalStore
from fylgja_core.packages import Loaded
from fylgja_core.reconcile import Reconciler, set_condition
from fylgja_core.run import Run
from fylgja_core.run import State as RunState
from fylgja_core.server import auth
from fylgja_core.server.app import capacity_document, create_app
from fylgja_core.store import Conflict
from fylgja_core.twin_record import Spec, Status, TwinRecord
from fylgja_core.verify import Verifier

ROOT = Path(__file__).resolve().parents[2]
ALICE = "alice-test-token"
BOB = "bob-test-token"
ENVIRON = {
    "FYLGJA_CREDENTIAL_SRLINUX_USERNAME": "admin",
    "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "NokiaSrl1!",
    "FYLGJA_CREDENTIAL_EOS_USERNAME": "admin",
    "FYLGJA_CREDENTIAL_EOS_PASSWORD": "admin",
}
THREE_NODE = ROOT / "testdata" / "blueprint" / "three-node.json"
STEPS = ROOT / "testdata" / "blueprint" / "steps"
SSE = "text/event-stream"


@dataclass
class Core:
    """What the application is built over, for a test to arrange and to look into."""

    app: Starlette
    store: LocalStore
    driver: FakeDriver
    reader: FakeReader
    loaded: Loaded
    reconciler: Reconciler
    closing: threading.Event


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Core]:
    store = LocalStore.open(tmp_path / "store")
    tokens = tmp_path / "tokens"
    tokens.write_text(f"# the test's clients\n{auth.hash_token(ALICE)} alice\n{auth.hash_token(BOB)} bob\n")
    loaded = packages.load([ROOT / "psp", ROOT / "probes"])
    driver = FakeDriver()
    reader = FakeReader(driver)
    verifier = Verifier(loaded.platforms, loaded.probes, Provider(ENVIRON), reader=reader)
    reconciler = Reconciler(store, {driver.name: driver}, loaded.platforms, loaded.probes, Provider(ENVIRON),
                            workers=1, pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver),
                            cancel_poll_s=0.01, verifier=verifier, step_wait_s=1.0, verify_poll_s=0.01)
    closing = threading.Event()
    app = create_app(store=store, loaded=loaded, drivers={driver.name: driver}, default_driver=driver.name,
                     reconciler=reconciler, tokens=auth.Tokens.load(tokens), build=version("fylgja-core"),
                     closing=closing, verifier=verifier)
    yield Core(app=app, store=store, driver=driver, reader=reader, loaded=loaded, reconciler=reconciler,
               closing=closing)
    store.close()


@pytest.fixture
def api(core: Core) -> Iterator[TestClient]:
    """A client as alice, with the application's lifespan (and so the loop) running."""
    with TestClient(core.app, headers={"Authorization": f"Bearer {ALICE}"}) as client:
        yield client


@pytest.fixture
def served(core: Core) -> Iterator[httpx2.Client]:
    """The application served by uvicorn on a port of its own, lifespan and all, and a client of it
    as alice. The TestClient answers a request once the application has ended it, so a watch that
    has not ended is read here, as it streams, and closed from the client's side."""
    config = uvicorn.Config(core.app, host="127.0.0.1", port=0, log_config=None, access_log=False,
                            timeout_graceful_shutdown=1)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn")
    thread.start()
    try:
        wait_for(lambda: True if server.started else None)
        host, port = server.servers[0].sockets[0].getsockname()[:2]
        with httpx2.Client(base_url=f"http://{host}:{port}", headers={"Authorization": f"Bearer {ALICE}"},
                          timeout=10.0, trust_env=False) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert not thread.is_alive()


def answered(response: httpx2.Response, status: int) -> Any:
    """The answer's document, once its status is `status` and the operation its request names
    declares that status, its media type and its body's shape."""
    assert response.status_code == status, response.text
    template, method = fake_api.operation(response.request)
    fake_api.check_response(template, method, response)
    return response.json()


def refused(response: httpx2.Response, status: int, rule: str) -> dict[str, Any]:
    """The problem document an operation answered, once its status and rule are these."""
    doc: dict[str, Any] = answered(response, status)
    assert response.headers["content-type"] == "application/problem+json"
    assert doc["rule"] == rule, doc
    assert doc["instance"] == response.request.url.path
    return doc


def stray(response: httpx2.Response, status: int, rule: str) -> dict[str, Any]:
    """The problem document answered for no operation of API 1: held to problem-1 alone."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    doc: dict[str, Any] = response.json()
    assert list(schemas.validator("problem-1").iter_errors(doc)) == []
    assert doc["rule"] == rule, doc
    return doc


def a_blueprint(path: Path = THREE_NODE) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(path.read_text())
    return doc


def file_blueprint(api: httpx2.Client, doc: dict[str, Any] | None = None) -> str:
    created = answered(api.post("/v1/blueprints", json=doc or a_blueprint()), 201)
    blueprint_id: str = created["id"]
    return blueprint_id


# The version and the drivers.


def test_the_version_needs_no_token_and_names_every_format(core: Core) -> None:
    with TestClient(core.app) as anonymous:
        doc = answered(anonymous.get("/v1/version"), 200)
    assert doc["api"] == "1" and doc["build"] == version("fylgja-core")
    assert set(doc["formats"].values()) == {"1"}


def test_every_other_call_needs_a_token(core: Core) -> None:
    with TestClient(core.app) as anonymous:
        refused(anonymous.get("/v1/drivers"), 401, "auth.token.missing")


def test_the_drivers_are_listed_with_the_default_and_capabilities(api: TestClient) -> None:
    doc = answered(api.get("/v1/drivers"), 200)
    assert doc == {"drivers": [{"name": "fake", "default": True, "capabilities": {
        "nodes": "provisions", "relink": True, "forwarding": "software", "access": "direct", "isolation": "names",
        "reapply": False}}]}


# The capacity read (D-076).


def test_the_capacity_read_answers_the_default_drivers_reading(api: TestClient) -> None:
    doc = answered(api.get("/v1/capacity"), 200)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", doc["read_at"])
    assert doc == {"driver": "fake", "read_at": doc["read_at"],
                   "hosts": [{"name": "fake", "cpu": {"total": 8.0, "free": 8.0},
                              "memory_mb": {"total": 16384, "free": 16384}}],
                   "pending": {"nodes": 0, "cpu": 0.0, "memory_mb": 0}, "twins": 0}
    assert list(schemas.api_validator("Capacity").iter_errors(doc)) == []
    create(api)
    doc = answered(api.get("/v1/capacity"), 200)
    assert doc["twins"] == 1 and doc["hosts"][0]["cpu"]["free"] == 6.5


def test_the_capacity_read_fails_as_503_when_the_runtime_cannot_be_read(
    api: TestClient, core: Core, caplog: pytest.LogCaptureFixture
) -> None:
    core.driver.fail_capacity = True
    with caplog.at_level(logging.ERROR, logger="fylgja.server"):
        r = api.get("/v1/capacity")
    problem = refused(r, 503, "capacity.unread")
    assert problem["detail"] == "The runtime could not be read; the log has the fault."
    assert "DriverFailed" not in r.text and "fake" not in problem["detail"]
    (record,) = [x for x in caplog.records if x.name == "fylgja.server"]
    assert record.exc_info is not None and "the fake's runtime cannot be read" in str(record.exc_info[1])


def test_the_capacity_read_needs_a_token(core: Core) -> None:
    with TestClient(core.app) as bare:
        refused(bare.get("/v1/capacity"), 401, "auth.token.missing")
        head = bare.head("/v1/capacity", headers={"Authorization": f"Bearer {ALICE}"})
    assert head.status_code == 200 and head.content == b""


def test_the_capacity_read_holds_no_lock_an_admission_needs(served: httpx2.Client, core: Core) -> None:
    core.driver.block = "capacity"
    reader = httpx2.Client(base_url=served.base_url, headers=dict(served.headers), timeout=30.0, trust_env=False)
    outcome: list[object] = []

    def read() -> None:
        try:
            outcome.append(reader.get("/v1/capacity"))
        except httpx2.HTTPError as e:
            outcome.append(e)
        finally:
            reader.close()

    thread = threading.Thread(target=read, name="capacity-read", daemon=True)
    thread.start()
    try:
        wait_for(lambda: True if ("capacity",) in core.driver.calls else None)
        answered(put(served, "t", {"blueprint_id": file_blueprint(served)}), 201)
        wait_for(lambda: True if any(call[0] == "admit" for call in core.driver.calls) else None, timeout_s=5.0)
        assert thread.is_alive() and outcome == []  # the read still blocks
    finally:
        core.driver.release("capacity")
        thread.join(timeout=10)
    assert not thread.is_alive() and len(outcome) == 1
    doc = answered(outcome[0], 200)  # type: ignore[arg-type]
    assert doc["driver"] == "fake" and doc["twins"] == 0  # counted as the read began, before the create


def test_a_fault_other_than_the_drivers_in_the_capacity_read_is_the_servers_500(api: TestClient, core: Core) -> None:
    core.driver.fail_capacity_with = ValueError("a malformed allocation")
    problem = stray(api.get("/v1/capacity"), 500, "server.error")
    assert "malformed" not in json.dumps(problem)


def test_a_dry_run_refused_by_capacity_carries_the_shortfall_sentence(api: TestClient, core: Core) -> None:
    sentence = "The twin needs 6144 MiB of memory, and the host has 1024 MiB free with 0 MiB pending."
    core.driver.refuse = Refusal("admission.capacity", sentence)
    problem = refused(dry_run(api, {"blueprint_id": file_blueprint(api)}), 422, "admission.capacity")
    assert problem["findings"] == [{"rule": "admission.capacity", "severity": "error", "object": "t",
                                    "message": sentence}]


def test_capacity_document_is_what_the_schema_says() -> None:
    nothing = Demand(nodes=0, cpu=0.0, memory_mb=0)
    doc = capacity_document("fake", Reading((), nothing), 0, "2026-11-08T12:00:00.000000Z")
    assert doc["hosts"] == [] and doc["read_at"] == "2026-11-08T12:00:00.000000Z"
    assert list(schemas.api_validator("Capacity").iter_errors(doc)) == []


# Blueprints.


def test_a_blueprint_is_filed_once_and_read_back_whole(api: TestClient) -> None:
    doc = a_blueprint()
    assert "source" in doc
    r = api.post("/v1/blueprints", json=doc)
    created = answered(r, 201)
    assert created == {"id": blueprint.blueprint_id(doc)}
    assert r.headers["location"] == f"/v1/blueprints/{created['id']}"
    again = api.post("/v1/blueprints", json=doc)
    assert answered(again, 200) == created and "location" not in again.headers
    assert answered(api.get(f"/v1/blueprints/{created['id']}"), 200) == doc


def test_an_unsorted_blueprint_is_refused_with_every_problem(api: TestClient) -> None:
    doc = a_blueprint()
    doc["network"]["devices"].reverse()
    problem = refused(api.post("/v1/blueprints", json=doc), 400, "blueprint.unsorted")
    assert problem["findings"] and all(f["severity"] == "error" for f in problem["findings"])
    assert {f["rule"] for f in problem["findings"]} == {"blueprint.unsorted"}
    assert all(f["object"].startswith("/network/devices/") for f in problem["findings"])


@pytest.mark.parametrize("body", [b"{not json", b"", b'{"x": NaN}', b"\xff\xfe"])
def test_a_body_that_is_no_json_document_is_refused(api: TestClient, body: bytes) -> None:
    r = api.post("/v1/blueprints", content=body, headers={"content-type": "application/json"})
    refused(r, 400, "request.invalid")


def test_a_blueprint_never_filed_is_not_found(api: TestClient) -> None:
    refused(api.get(f"/v1/blueprints/{'f' * 64}"), 404, "blueprint.not_found")
    problem = refused(api.get("/v1/blueprints/not-an-id"), 404, "blueprint.not_found")
    assert "not-an-id" not in problem["detail"]


# Bundles.


def test_a_blueprint_with_an_unmanaged_device_builds_a_bundle_whose_node_has_no_config(api: TestClient) -> None:
    unmanaged = ROOT / "testdata/blueprint/three-node-unmanaged.json"
    blueprint_id = file_blueprint(api, a_blueprint(unmanaged))
    result = answered(api.post("/v1/bundles", json={"blueprint_id": blueprint_id}), 201)
    nodes = {n["name"]: n for n in result["manifest"]["nodes"]}
    assert "config" not in nodes["n2"] and "config" in nodes["n1"] and "config" in nodes["n3"]
    assert bundle.validate(result["manifest"]) == []


def test_a_bundle_is_built_once_and_read_back(api: TestClient) -> None:
    blueprint_id = file_blueprint(api)
    r = api.post("/v1/bundles", json={"blueprint_id": blueprint_id})
    result = answered(r, 201)
    assert r.headers["location"] == f"/v1/bundles/{result['id']}"
    assert bundle.validate(result["manifest"]) == []
    assert result["manifest"]["blueprint_id"] == blueprint_id and result["findings"] == []
    assert result["fidelity"]["synthesized"] == [] and "approximations" in result["fidelity"]
    assert answered(api.post("/v1/bundles", json={"blueprint_id": blueprint_id}), 200) == result
    assert answered(api.get(f"/v1/bundles/{result['id']}"), 200) == {"id": result["id"],
                                                                      "manifest": result["manifest"]}


def test_an_uncompilable_blueprint_is_refused_with_the_compilers_findings(api: TestClient) -> None:
    blueprint_id = file_blueprint(api, a_blueprint(ROOT / "testdata/compiler/rejected/network-empty.json"))
    problem = refused(api.post("/v1/bundles", json={"blueprint_id": blueprint_id}), 422, "bundle.rejected")
    assert [(f["rule"], f["object"]) for f in problem["findings"]] == [("network.empty", "network")]


def test_a_bundle_of_an_unknown_blueprint_is_not_found(api: TestClient) -> None:
    refused(api.post("/v1/bundles", json={"blueprint_id": "e" * 64}), 404, "blueprint.not_found")
    refused(api.get(f"/v1/bundles/{'e' * 64}"), 404, "bundle.not_found")


def test_a_bundle_request_is_held_to_its_schema(api: TestClient) -> None:
    problem = refused(api.post("/v1/bundles", json={"blueprint_id": "e" * 64, "more": 1}), 400, "request.invalid")
    assert problem["findings"][0]["object"] == "/"
    refused(api.post("/v1/bundles", json={"blueprint_id": "short"}), 400, "request.invalid")


def file_bundle(api: TestClient, path: Path) -> str:
    blueprint_id = file_blueprint(api, json.loads(path.read_text()))
    bundle_id: str = answered(api.post("/v1/bundles", json={"blueprint_id": blueprint_id}), 201)["id"]
    return bundle_id


def test_the_bundle_diff_of_two_filed_bundles_names_what_a_step_changes(api: TestClient) -> None:
    before = file_bundle(api, THREE_NODE)
    after = file_bundle(api, STEPS / "two-node.json")
    result = answered(api.get(f"/v1/bundles/{before}/diff/{after}"), 200)
    assert (result["from"], result["to"], result["unchanged"]) == (before, after, False)
    assert result["nodes"]["removed"] == ["n3"] and result["nodes"]["added"] == []
    assert [c["node"] for c in result["nodes"]["changed"]] == ["n1", "n2"]
    assert len(result["links"]["removed"]) == 2 and result["links"]["added"] == []


def test_the_bundle_diff_of_a_bundle_with_itself_is_unchanged(api: TestClient) -> None:
    only = file_bundle(api, THREE_NODE)
    result = answered(api.get(f"/v1/bundles/{only}/diff/{only}"), 200)
    assert result["unchanged"] is True and result["nodes"]["changed"] == []


def test_the_bundle_diff_of_a_bundle_never_filed_is_not_found(api: TestClient) -> None:
    only = file_bundle(api, THREE_NODE)
    assert "e" * 64 in refused(api.get(f"/v1/bundles/{only}/diff/{'e' * 64}"), 404, "bundle.not_found")["detail"]
    assert "e" * 64 in refused(api.get(f"/v1/bundles/{'e' * 64}/diff/{only}"), 404, "bundle.not_found")["detail"]
    both = refused(api.get(f"/v1/bundles/{'d' * 64}/diff/{'e' * 64}"), 404, "bundle.not_found")["detail"]
    assert "d" * 64 in both and "e" * 64 not in both
    refused(api.get(f"/v1/bundles/{only}/diff/not-an-id"), 404, "bundle.not_found")
    refused(api.get(f"/v1/bundles/not-an-id/diff/{only}"), 404, "bundle.not_found")


# Packages.


def test_a_shipped_package_validates_ok(api: TestClient) -> None:
    package = yaml.safe_load((ROOT / "psp" / "arista_eos.yaml").read_text())
    verdict = answered(api.post("/v1/packages:validate", json={"package": package}), 200)
    assert (verdict["operation"], verdict["status"], verdict["findings"]) == ("packages.validate", "ok", [])
    probe = yaml.safe_load((ROOT / "probes" / "ping.yaml").read_text())
    assert answered(api.post("/v1/packages:validate", json={"package": probe}), 200)["status"] == "ok"


@pytest.mark.parametrize("path", ["platform/rename-missing.yaml", "probe/several.yaml"])
def test_an_invalid_package_is_a_rejected_verdict_with_the_loaders_problems(api: TestClient, path: str) -> None:
    from fylgja_core import platform_package, probe_package

    package = yaml.safe_load((ROOT / "testdata/packages/invalid" / path).read_text())
    validate = platform_package.validate if path.startswith("platform") else probe_package.validate
    expected = sorted((p.rule, p.pointer or "/", p.detail) for p in validate(package))
    verdict = answered(api.post("/v1/packages:validate", json={"package": package}), 200)
    assert verdict["status"] == "rejected"
    assert sorted((f["rule"], f["object"], f["message"]) for f in verdict["findings"]) == expected and expected


def test_a_package_of_no_kind_is_refused(api: TestClient) -> None:
    refused(api.post("/v1/packages:validate", json={"package": {"id": "x"}}), 400, "request.invalid")
    refused(api.post("/v1/packages:validate", json={"package": []}), 400, "request.invalid")
    refused(api.post("/v1/packages:validate", json={"package": {}, "more": 1}), 400, "request.invalid")


# What API 1 does not have, and a fault.


def test_a_path_api_1_does_not_have_is_not_found(api: TestClient) -> None:
    assert stray(api.get("/v1/nothing"), 404, "request.not_found")["instance"] == "/v1/nothing"


def test_a_path_with_a_slash_too_many_is_not_found_and_not_redirected(api: TestClient) -> None:
    r = api.get("/v1/version/", follow_redirects=False)
    stray(r, 404, "request.not_found")
    assert "location" not in r.headers
    stray(api.get("/v1/twins/", follow_redirects=False), 404, "request.not_found")


def test_a_method_a_path_does_not_take_is_refused(api: TestClient) -> None:
    r = api.delete("/v1/version")
    stray(r, 405, "request.method")
    assert "GET" in r.headers["allow"]


def test_a_fault_is_a_500_that_names_nothing_of_it_and_is_logged(
    api: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(blueprint_id: str) -> dict[str, Any]:
        raise RuntimeError("the disk is on fire")

    monkeypatch.setattr(core.store, "get_blueprint", boom)
    with caplog.at_level(logging.ERROR, logger="fylgja.server"):
        problem = stray(api.get(f"/v1/blueprints/{'a' * 64}"), 500, "server.error")
    assert "fire" not in json.dumps(problem)
    (record,) = [r for r in caplog.records if r.name == "fylgja.server"]
    assert record.exc_info is not None and "fire" in str(record.exc_info[1])


# Twins: polling the loop's work.


def wait_for[T](read: Callable[[], T | None], timeout_s: float = 10.0) -> T:
    """`read()` once it answers something, polled while the loop works."""
    deadline = time.monotonic() + timeout_s
    while (value := read()) is None:
        assert time.monotonic() < deadline, "the loop did not get there in time"
        time.sleep(0.01)
    return value


def settled(api: httpx2.Client, name: str) -> dict[str, Any]:
    """The twin's record once the loop has acted on its generation."""

    def read() -> dict[str, Any] | None:
        record: dict[str, Any] = answered(api.get(f"/v1/twins/{name}"), 200)
        return record if record["status"]["observed_generation"] == record["generation"] else None

    return wait_for(read)


def gone(api: httpx2.Client, name: str) -> None:
    """Return once the twin's record is deleted."""
    wait_for(lambda: True if api.get(f"/v1/twins/{name}").status_code == 404 else None)


def ready(record: dict[str, Any]) -> tuple[str, str | None]:
    (condition,) = [c for c in record["status"]["conditions"] if c["type"] == "Ready"]
    return condition["status"], condition.get("reason")


def runs_of(api: httpx2.Client, name: str) -> list[dict[str, Any]]:
    listed: list[dict[str, Any]] = answered(api.get("/v1/runs", params={"twin": name}), 200)["runs"]
    return listed


def put(api: httpx2.Client, name: str, spec: dict[str, Any], **headers: str) -> httpx2.Response:
    response: httpx2.Response = api.put(f"/v1/twins/{name}", json={"spec": spec}, headers=headers)
    return response


def create(api: httpx2.Client, name: str = "t", blueprint_id: str | None = None) -> dict[str, Any]:
    """A twin made by PUT and settled by the loop."""
    answered(put(api, name, {"blueprint_id": blueprint_id or file_blueprint(api)}), 201)
    return settled(api, name)


def audited(caplog: pytest.LogCaptureFixture, action: str) -> list[dict[str, Any]]:
    return [fields for r in caplog.records if r.name == "fylgja.audit"
            and (fields := getattr(r, "fields", {})).get("action") == action]


# Twins: create, read, the same spec again.


def test_a_put_creates_the_twin_and_the_loop_makes_it_ready(api: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    blueprint_id = file_blueprint(api)
    with caplog.at_level(logging.INFO, logger="fylgja.audit"):
        r = put(api, "t", {"blueprint_id": blueprint_id})
        record = answered(r, 201)
    assert r.headers["location"] == "/v1/twins/t" and r.headers["etag"] == '"1"'
    assert record["spec"] == {"blueprint_id": blueprint_id, "driver": "fake", "allow_restart": False}
    assert (record["revision"], record["generation"], record["status"]["observed_generation"]) == (1, 1, 0)
    (line,) = audited(caplog, "put")
    assert (line["principal"], line["twin"], line["revision"]) == ("alice", "t", 1)

    done = settled(api, "t")
    assert ready(done) == ("True", "twin.ready") and done["status"]["observed_generation"] == 1
    (run,) = runs_of(api, "t")
    assert (run["operation"], run["state"], run["principal"], run["verdict"]["status"]) == ("create", "ended", "alice",
                                                                                            "ok")
    assert run["id"] == line["run"]
    assert answered(api.get(f"/v1/runs/{run['id']}"), 200) == run


def test_a_twin_reads_with_its_revision_as_etag(api: TestClient) -> None:
    record = create(api)
    r = api.get("/v1/twins/t")
    assert answered(r, 200) == record and r.headers["etag"] == f'"{record["revision"]}"'


def test_a_twin_of_a_bundle_is_made_with_no_compile(api: TestClient) -> None:
    built = answered(api.post("/v1/bundles", json={"blueprint_id": file_blueprint(api)}), 201)
    answered(put(api, "u", {"bundle_id": built["id"], "allow_restart": True}), 201)
    record = settled(api, "u")
    assert ready(record) == ("True", "twin.ready") and record["status"]["bundle_id"] == built["id"]
    assert record["spec"]["allow_restart"] is True


def test_the_same_put_again_changes_nothing(api: TestClient) -> None:
    record = create(api)
    again = put(api, "t", {"blueprint_id": record["spec"]["blueprint_id"]})
    assert answered(again, 200) == record and again.headers["etag"] == f'"{record["revision"]}"'
    assert len(runs_of(api, "t")) == 1


def test_twins_are_listed_by_name(api: TestClient) -> None:
    blueprint_id = file_blueprint(api)
    for name in ("b", "a"):
        answered(put(api, name, {"blueprint_id": blueprint_id}), 201)
    assert [t["name"] for t in answered(api.get("/v1/twins"), 200)["twins"]] == ["a", "b"]


# Twins: refused writes.


def test_if_none_match_refuses_a_twin_that_exists(api: TestClient) -> None:
    record = create(api)
    refused(put(api, "t", {"blueprint_id": record["spec"]["blueprint_id"]}, **{"If-None-Match": "*"}), 412,
            "twin.exists")
    refused(put(api, "t", {"blueprint_id": record["spec"]["blueprint_id"]}, **{"If-None-Match": '"1"'}), 400,
            "request.invalid")


def test_if_match_refuses_a_revision_the_record_has_moved_past(api: TestClient) -> None:
    record = create(api)
    assert record["revision"] > 1
    spec = {"blueprint_id": record["spec"]["blueprint_id"]}
    refused(put(api, "t", spec, **{"If-Match": '"1"'}), 412, "twin.conflict")
    assert answered(put(api, "t", spec, **{"If-Match": f'"{record["revision"]}"'}), 200) == record
    refused(put(api, "new", spec, **{"If-Match": '"1"'}), 412, "twin.conflict")
    refused(api.delete("/v1/twins/t", headers={"If-Match": '"1"'}), 412, "twin.conflict")


def test_another_driver_than_the_twins_is_refused(api: TestClient, core: Core) -> None:
    blueprint_id = file_blueprint(api)
    spec = Spec(blueprint_id=blueprint_id, driver="spare", allow_restart=False)
    core.store.create_twin(TwinRecord(name="t", revision=1, generation=1, spec=spec,
                                      status=Status(observed_generation=0, conditions=(), nodes=())))
    refused(put(api, "t", {"blueprint_id": blueprint_id, "driver": "fake"}), 409, "twin.driver.fixed")


# Twins: a new spec on a twin that runs is a step (D-050).


def target_of(api: httpx2.Client, core: Core, path: Path, name: str = "t") -> str:
    """The blueprint at `path` filed and built, and the reader seeded with the facts of `name`
    built to it, so verify holds on the twin a step to it leaves; the blueprint's id."""
    blueprint_id = file_blueprint(api, a_blueprint(path))
    built = api.post("/v1/bundles", json={"blueprint_id": blueprint_id})
    assert built.status_code in (200, 201), built.text
    core.reader.seed(name, bundle.decode(built.json()["manifest"]), core.loaded.platforms)
    return blueprint_id


def test_a_new_spec_on_a_ready_twin_queues_a_step_the_loop_runs_to_ready(
    api: TestClient, core: Core, caplog: pytest.LogCaptureFixture
) -> None:
    record = create(api)
    target = target_of(api, core, STEPS / "three-node-unlinked.json")
    with caplog.at_level(logging.INFO, logger="fylgja.audit"):
        r = put(api, "t", {"blueprint_id": target})
        written = answered(r, 200)
    assert (written["revision"], written["generation"]) == (record["revision"] + 1, 2)
    assert written["spec"] == {"blueprint_id": target, "driver": "fake", "allow_restart": False}
    assert written["status"] == record["status"]  # the API never writes status
    assert r.headers["etag"] == f'"{written["revision"]}"'
    (line,) = [line for line in audited(caplog, "put") if line.get("generation") == 2]
    assert (line["principal"], line["revision"]) == ("alice", written["revision"])

    done = settled(api, "t")
    assert done["status"]["observed_generation"] == 2 and ready(done) == ("True", "twin.ready")
    step, _ = runs_of(api, "t")
    assert (step["id"], step["operation"], step["principal"]) == (line["run"], "step", "alice")
    assert (step["state"], step["verdict"]["status"], step["verdict"]["wait"]["outcome"]) == ("ended", "ok", "settled")
    last = done["status"]["last_step"]
    assert (last["outcome"], last["from"], last["to"], last["phase"], last["run_id"]) == (
        "stepped", record["status"]["bundle_id"], done["status"]["bundle_id"], "flows", step["id"])


def test_a_new_spec_on_a_twin_whose_create_never_applied_queues_a_create(api: TestClient, core: Core) -> None:
    core.driver.refuse = Refusal("admission.capacity", "The host has no room.")
    record = create(api)
    assert "deployment_id" not in record["status"]  # its cleanup cleared it
    core.driver.refuse = None
    answered(put(api, "t", {"blueprint_id": record["spec"]["blueprint_id"], "allow_restart": True}), 200)
    done = settled(api, "t")
    assert ready(done) == ("True", "twin.ready")
    again, _ = runs_of(api, "t")
    assert (again["operation"], again["principal"], again["verdict"]["status"]) == ("create", "alice", "ok")


def test_a_new_spec_under_an_if_match_the_record_moved_past_is_refused(api: TestClient) -> None:
    record = create(api)
    other = file_blueprint(api, a_blueprint(STEPS / "two-node.json"))
    refused(put(api, "t", {"blueprint_id": other}, **{"If-Match": '"1"'}), 412, "twin.conflict")
    assert answered(api.get("/v1/twins/t"), 200) == record and len(runs_of(api, "t")) == 1
    written = answered(put(api, "t", {"blueprint_id": other}, **{"If-Match": f'"{record["revision"]}"'}), 200)
    assert written["generation"] == 2


def test_a_new_spec_whose_write_is_lost_withdraws_its_step_run(
    api: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = create(api)
    other = file_blueprint(api, a_blueprint(STEPS / "two-node.json"))

    def lost(record: TwinRecord, expected_revision: int) -> TwinRecord:
        raise Conflict("twin t moved")

    monkeypatch.setattr(core.store, "update_twin", lost)
    refused(put(api, "t", {"blueprint_id": other}), 412, "twin.conflict")
    withdrawn, _ = runs_of(api, "t")
    assert (withdrawn["operation"], withdrawn["state"], withdrawn["verdict"]["status"]) == ("step", "ended", "failed")
    assert [f["rule"] for f in withdrawn["verdict"]["findings"]] == ["run.cancelled"]
    assert answered(api.get("/v1/twins/t"), 200) == record


def condition_set(kind: Any, status: Any, reason: str) -> Callable[[Status], Status]:
    """A write of the loop's to a status: the condition `kind` set to `status` for `reason`."""
    return lambda s: dataclasses_replace(s, conditions=set_condition(s.conditions, kind, status, reason))


def beaten_by_the_loop(
    monkeypatch: pytest.MonkeyPatch, store: LocalStore, *writes: Callable[[Status], Status]
) -> list[int]:
    """Make the next twin record writes lose their compare-and-set, each to the loop's write of the
    status by `writes` in turn, landing between the handler's read and its write; the revision each
    of the loop's writes left."""
    real = store.update_twin
    left = list(writes)
    beaten: list[int] = []

    def update_twin(record: TwinRecord, expected_revision: int) -> TwinRecord:
        if left:
            current = store.get_twin(record.name)
            beaten.append(real(dataclasses_replace(current, status=left.pop(0)(current.status)),
                               current.revision).revision)
        return real(record, expected_revision)

    monkeypatch.setattr(store, "update_twin", update_twin)
    return beaten


def ready_and_idle(idle: TestClient, core: Core) -> tuple[dict[str, Any], str]:
    """A Ready twin `t`, made by one pass of the loop, which is not started, and another blueprint filed."""
    answered(put(idle, "t", {"blueprint_id": file_blueprint(idle)}), 201)
    asyncio.run(core.reconciler.reconcile("t"))
    return answered(idle.get("/v1/twins/t"), 200), file_blueprint(idle, a_blueprint(STEPS / "two-node.json"))


@pytest.mark.parametrize("if_match", [None, "*"])
def test_a_new_spec_whose_write_the_loop_beat_is_written_again_over_the_loops_status(
    idle: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch, if_match: str | None
) -> None:
    record, other = ready_and_idle(idle, core)
    beaten = beaten_by_the_loop(monkeypatch, core.store, condition_set("Stepping", "False", "twin.ready"))
    headers = {} if if_match is None else {"If-Match": if_match}
    written = answered(put(idle, "t", {"blueprint_id": other}, **headers), 200)
    assert len(beaten) == 1 and written["revision"] == beaten[0] + 1  # written over the loop's write
    assert (written["generation"], written["spec"]["blueprint_id"]) == (record["generation"] + 1, other)
    assert [c["type"] for c in written["status"]["conditions"]] == ["Ready", "Stepping"]  # the loop's status kept
    (step, _) = runs_of(idle, "t")  # the run queued for the first try, never withdrawn
    assert (step["operation"], step["state"], step["principal"]) == ("step", "queued", "alice")
    assert core.store.events(step["id"]) == []


@pytest.mark.parametrize("why", ["lost twice", "If-Match named a revision"])
def test_a_new_spec_whose_write_the_loop_beat_is_refused_when_it_cannot_be_made_again(
    idle: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch, why: str
) -> None:
    record, other = ready_and_idle(idle, core)
    writes = [condition_set("Stepping", "False", "twin.ready")]
    if why == "lost twice":
        writes.append(condition_set("Stepping", "False", "twin.stepping"))
    beaten = beaten_by_the_loop(monkeypatch, core.store, *writes)
    headers = {} if why == "lost twice" else {"If-Match": f'"{record["revision"]}"'}
    refused(put(idle, "t", {"blueprint_id": other}, **headers), 412, "twin.conflict")
    assert len(beaten) == len(writes)
    stored = answered(idle.get("/v1/twins/t"), 200)
    assert (stored["generation"], stored["spec"]) == (record["generation"], record["spec"])  # no spec written
    (withdrawn, _) = runs_of(idle, "t")  # one run, withdrawn once
    assert (withdrawn["operation"], withdrawn["state"], withdrawn["verdict"]["status"]) == ("step", "ended", "failed")
    assert [f["rule"] for f in withdrawn["verdict"]["findings"]] == ["run.cancelled"]


def test_a_new_spec_whose_write_the_loop_beat_meets_the_refusals_again(
    idle: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, other = ready_and_idle(idle, core)
    beaten_by_the_loop(monkeypatch, core.store, condition_set("Diverged", "True", "step.diverged"))
    refused(put(idle, "t", {"blueprint_id": other}), 409, "twin.diverged")  # the loop's write diverged the twin
    assert answered(idle.get("/v1/twins/t"), 200)["spec"] == record["spec"]
    (withdrawn, _) = runs_of(idle, "t")
    assert (withdrawn["operation"], withdrawn["state"], withdrawn["verdict"]["status"]) == ("step", "ended", "failed")


def stepping_into_apply(api: httpx2.Client, core: Core, path: Path) -> dict[str, Any]:
    """A step of the Ready twin `t` to the blueprint at `path`, held in its apply, which never
    answers until cancelled: the step run once its `apply started` is recorded."""
    core.driver.block = "apply"
    answered(put(api, "t", {"blueprint_id": file_blueprint(api, a_blueprint(path))}), 200)

    def applying() -> dict[str, Any] | None:
        listed = [r for r in runs_of(api, "t") if r["operation"] == "step"]
        if not listed:
            return None
        events = answered(api.get(f"/v1/runs/{listed[0]['id']}/events"), 200)["events"]
        return listed[0] if events and (events[-1]["phase"], events[-1]["outcome"]) == ("apply", "started") else None

    return wait_for(applying)


def test_a_diverged_twin_accepts_only_deletion(api: TestClient, core: Core) -> None:
    create(api)
    step = stepping_into_apply(api, core, STEPS / "two-node.json")
    answered(api.post(f"/v1/runs/{step['id']}/cancel"), 202)
    diverged = settled(api, "t")
    core.driver.block = None
    assert [(c["type"], c["status"]) for c in diverged["status"]["conditions"]] == [
        ("Ready", "False"), ("Stepping", "False"), ("Diverged", "True")]
    assert answered(api.get(f"/v1/runs/{step['id']}"), 200)["verdict"]["status"] == "diverged"

    other = file_blueprint(api, a_blueprint(STEPS / "three-node-unlinked.json"))
    problem = refused(put(api, "t", {"blueprint_id": other}), 409, "twin.diverged")
    assert problem["detail"] == "Twin t is diverged; it accepts only deletion."
    dry = api.put("/v1/twins/t", params={"dry_run": "true"}, json={"spec": {"blueprint_id": other}})
    refused(dry, 409, "twin.diverged")
    assert answered(put(api, "t", {"blueprint_id": diverged["spec"]["blueprint_id"]}), 200) == diverged
    assert answered(api.get("/v1/twins/t"), 200) == diverged and len(runs_of(api, "t")) == 2
    answered(api.delete("/v1/twins/t"), 202)
    gone(api, "t")


def test_a_delete_during_a_step_cancels_it_and_the_twin_is_gone(api: TestClient, core: Core) -> None:
    create(api)
    step = stepping_into_apply(api, core, STEPS / "two-node.json")
    answered(api.delete("/v1/twins/t"), 202)  # marks the step cancelling: its apply, which never answers, stops
    gone(api, "t")
    destroy, ended, _ = runs_of(api, "t")
    assert (ended["id"], ended["verdict"]["status"]) == (step["id"], "diverged")  # its apply had begun (D-029)
    assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok")
    assert "t" not in core.driver.labs


def test_a_delete_during_a_restore_cancels_it_and_the_twin_is_gone(api: TestClient, core: Core) -> None:
    probed = ROOT / "testdata" / "blueprint" / "three-node-probed.json"
    created = create(api, blueprint_id=file_blueprint(api, a_blueprint(probed)))
    core.driver.block = "exec"  # a restore calls no apply: it readies the probe hosts through exec, held here
    core.driver.replace("t", "n2")  # behind the loop's back
    core.reconciler.kick("t")

    def readying_a_host() -> dict[str, Any] | None:
        run = runs_of(api, "t")[0]
        if run["operation"] != "restore" or not any(call[0] == "exec" for call in list(core.driver.calls)):
            return None
        events = answered(api.get(f"/v1/runs/{run['id']}/events"), 200)["events"]
        last = (events[-1]["phase"], events[-1]["outcome"], events[-1].get("node")) if events else None
        return run if last == ("ready", "started", "n1-loop-a") else None

    restore = wait_for(readying_a_host)
    answered(api.delete("/v1/twins/t"), 202)  # marks the restore cancelling: the exec it waits on stops
    gone(api, "t")
    destroy, ended, _ = runs_of(api, "t")
    assert (ended["id"], ended["operation"], ended["verdict"]["status"]) == (restore["id"], "restore", "failed")
    assert [f["rule"] for f in ended["verdict"]["findings"]] == ["run.cancelled"]
    assert "where it stood" in ended["verdict"]["findings"][0]["message"]  # the restore's cancel path, not a create's
    assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok")
    assert destroy["verdict"]["subject"]["deployment_id"] == created["status"]["deployment_id"]  # found it kept
    assert core.driver.calls.count(("destroy", "t")) == 1  # the restore's cancel tore nothing down: the destroy run did
    assert "t" not in core.driver.labs


def test_a_driver_this_core_does_not_serve_is_refused(api: TestClient) -> None:
    problem = refused(put(api, "t", {"blueprint_id": file_blueprint(api), "driver": "nope"}), 400,
                      "twin.driver.unknown")
    assert "fake" in problem["detail"]
    assert api.get("/v1/twins/t").status_code == 404 and runs_of(api, "t") == []


def test_an_id_never_filed_is_not_found(api: TestClient) -> None:
    refused(put(api, "t", {"blueprint_id": "d" * 64}), 404, "blueprint.not_found")
    refused(put(api, "t", {"bundle_id": "d" * 64}), 404, "bundle.not_found")


def test_a_malformed_name_or_body_is_refused(api: TestClient) -> None:
    blueprint_id = file_blueprint(api)
    refused(put(api, "Twin_1", {"blueprint_id": blueprint_id}), 400, "request.invalid")
    r = api.put("/v1/twins/t", json={"spec": {"blueprint_id": blueprint_id}, "extra": 1})
    assert refused(r, 400, "request.invalid")["findings"][0]["object"] == "/"
    problem = refused(put(api, "t", {"blueprint_id": blueprint_id, "mode": "x"}), 400, "request.invalid")
    assert problem["findings"][0]["object"] == "/spec"
    refused(put(api, "t", {"blueprint_id": blueprint_id, "bundle_id": blueprint_id}), 400, "request.invalid")
    refused(put(api, "t", {}), 400, "request.invalid")
    refused(api.put("/v1/twins/t", params={"dry_run": "yes"}, json={"spec": {"blueprint_id": blueprint_id}}), 400,
            "request.invalid")
    refused(api.get("/v1/twins/Twin_1"), 404, "twin.not_found")
    refused(api.get("/v1/runs", params={"twin": "Twin_1"}), 400, "request.invalid")
    refused(api.get("/v1/runs/not-a-ulid"), 404, "run.not_found")


def seed_reader(core: Core, name: str = "t") -> None:
    """Facts consistent with the bundle the twin was built to, as the nodes would report them."""
    bundle_id = core.store.get_twin(name).status.bundle_id
    assert bundle_id is not None
    manifest = bundle.decode(json.loads(core.store.get_bundle(bundle_id)["manifest.json"]))
    core.reader.seed(name, manifest, core.loaded.platforms)


def test_a_ready_twin_verifies_ok_through_the_route(api: TestClient, core: Core) -> None:
    record = create(api)
    seed_reader(core)
    verdict = answered(api.post("/v1/twins/t/verifications"), 200)
    assert verdict["operation"] == "verify" and verdict["status"] == "ok"
    assert {f["severity"] for f in verdict["findings"]} <= {"info"}
    assert verdict["subject"] == {"twin": "t", "bundle_id": record["status"]["bundle_id"],
                                  "deployment_id": record["status"]["deployment_id"]}
    assert verdict["counts"]["held"] > 0 and verdict["counts"]["failed"] == 0
    assert answered(api.get("/v1/twins/t"), 200) == record


def test_a_node_that_reports_nothing_is_a_nonconforming_verdict(api: TestClient, core: Core) -> None:
    create(api)
    seed_reader(core)
    core.reader.facts[("t", "n1")] = {}
    verdict = answered(api.post("/v1/twins/t/verifications"), 200)
    assert verdict["status"] == "nonconforming" and verdict["counts"]["failed"] > 0


def test_an_unreadable_node_fails_the_verdict(api: TestClient, core: Core) -> None:
    create(api)
    seed_reader(core)
    core.reader.unreadable.add(("t", "n1"))
    verdict = answered(api.post("/v1/twins/t/verifications"), 200)
    assert verdict["status"] == "failed"


def test_a_twin_with_no_applied_deployment_is_not_running(api: TestClient, core: Core) -> None:
    core.driver.refuse = Refusal("admission.capacity", "The host has no room.")
    answered(put(api, "t", {"blueprint_id": file_blueprint(api)}), 201)
    settled(api, "t")
    assert core.store.get_twin("t").status.deployment_id is None
    problem = refused(api.post("/v1/twins/t/verifications"), 409, "twin.not_running")
    assert problem["detail"] == "Twin t has no applied deployment to read."
    assert core.reader.calls == []


def test_a_create_between_planned_and_applied_is_not_running(idle: TestClient, core: Core) -> None:
    # The deployment id is written at `planned`, the nodes only at `applied`: the hosts are still being deployed.
    spec = Spec(blueprint_id=file_blueprint(idle), driver="fake", allow_restart=False)
    status = Status(observed_generation=0, conditions=(), nodes=(), phase="planned", blueprint_id=spec.blueprint_id,
                    bundle_id="b" * 64, deployment_id="d" * 64)
    core.store.create_twin(TwinRecord(name="t", revision=1, generation=1, spec=spec, status=status))
    problem = refused(idle.post("/v1/twins/t/verifications"), 409, "twin.not_running")
    assert problem["detail"] == "Twin t has no applied deployment to read."
    assert core.reader.calls == [] and [c for c in core.driver.calls if c[0] == "exec"] == []


def test_an_unknown_twin_cannot_be_verified(api: TestClient) -> None:
    refused(api.post("/v1/twins/t/verifications"), 404, "twin.not_found")


# Twins: the dry run.


def stored(store: LocalStore) -> dict[str, str]:
    """Every file the store holds, by path, with its content's hash."""
    return {p.relative_to(store.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(store.root.rglob("*")) if p.is_file()}


def test_a_dry_run_answers_the_plan_and_writes_nothing(api: TestClient, core: Core) -> None:
    blueprint_id = file_blueprint(api)
    before = stored(core.store)
    r = api.put("/v1/twins/t", params={"dry_run": "true"}, json={"spec": {"blueprint_id": blueprint_id}})
    assert stored(core.store) == before  # no bundle, deployment, record or run, and nothing changed
    plan = answered(r, 200)
    assert set(plan) == {"deployment", "verdict"} and deployment.validate(plan["deployment"]) == []
    assert (plan["verdict"]["operation"], plan["verdict"]["status"], plan["verdict"]["findings"]) == ("plan", "ok", [])
    assert plan["deployment"]["twin"] == "t" and plan["deployment"]["driver"] == "fake"
    assert "etag" not in r.headers
    refused(api.get("/v1/twins/t"), 404, "twin.not_found")
    assert runs_of(api, "t") == []


def test_a_dry_run_admission_refuses_is_a_problem_with_the_refusal(api: TestClient, core: Core) -> None:
    core.driver.refuse = Refusal("admission.capacity", "The host has no room.")
    r = api.put("/v1/twins/t", params={"dry_run": "true"}, json={"spec": {"blueprint_id": file_blueprint(api)}})
    problem = refused(r, 422, "admission.capacity")
    assert problem["findings"] == [{"rule": "admission.capacity", "severity": "error", "object": "t",
                                    "message": "The host has no room."}]


def test_a_dry_run_the_driver_cannot_plan_is_a_problem_with_its_findings(
    api: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = Finding(rule="interface.port.shared", severity="error", object="n1:ethernet-1/1",
                     message="Port ethernet-1/1 is the runtime port of two cabled interfaces.")

    def unplannable(*args: object, **kwargs: object) -> Planned:
        raise Unplannable([shared])

    monkeypatch.setattr(core.driver, "plan", unplannable)
    r = api.put("/v1/twins/t", params={"dry_run": "true"}, json={"spec": {"blueprint_id": file_blueprint(api)}})
    problem = refused(r, 422, "plan.rejected")
    assert [(f["rule"], f["object"]) for f in problem["findings"]] == [("interface.port.shared", "n1:ethernet-1/1")]


def test_a_dry_run_of_an_uncompilable_blueprint_is_a_problem(api: TestClient) -> None:
    rejected = file_blueprint(api, a_blueprint(ROOT / "testdata/compiler/rejected/network-empty.json"))
    r = api.put("/v1/twins/t", params={"dry_run": "true"}, json={"spec": {"blueprint_id": rejected}})
    refused(r, 422, "bundle.rejected")


def dry_run(api: httpx2.Client, spec: dict[str, Any], name: str = "t") -> httpx2.Response:
    response: httpx2.Response = api.put(f"/v1/twins/{name}", params={"dry_run": "true"}, json={"spec": spec})
    return response


def test_a_dry_run_on_a_twin_that_runs_answers_its_steps_changes_and_writes_nothing(
    api: TestClient, core: Core
) -> None:
    record = create(api)
    other = file_blueprint(api, a_blueprint(STEPS / "three-node-unlinked.json"))
    before = stored(core.store)
    plan = answered(dry_run(api, {"blueprint_id": other}), 200)
    assert stored(core.store) == before  # no run, bundle or deployment, and the record as it was
    assert set(plan) == {"deployment", "verdict", "changes"}
    fake_api.check_component("Changes", plan["changes"])
    assert plan["changes"] == {
        "nodes": [{"node": "n1", "action": "kept", "reasons": []},
                  {"node": "n2", "action": "recabled", "reasons": ["links"]},
                  {"node": "n3", "action": "recabled", "reasons": ["links"]}],
        "links_added": [], "links_removed": [["n2:ethernet-1/2", "n3:ethernet-1/1"]]}
    assert (plan["verdict"]["operation"], plan["verdict"]["status"], plan["verdict"]["findings"]) == ("plan", "ok", [])
    assert plan["deployment"]["allocation"] == record["status"]["allocation"]
    assert plan["verdict"]["subject"]["deployment_id"] == plan["deployment"]["id"] != record["status"]["deployment_id"]
    assert answered(api.get("/v1/twins/t"), 200) == record and len(runs_of(api, "t")) == 1
    rejected = file_blueprint(api, a_blueprint(ROOT / "testdata/compiler/rejected/network-empty.json"))
    refused(dry_run(api, {"blueprint_id": rejected}), 422, "bundle.rejected")


def test_a_dry_run_of_a_step_needing_a_restart_the_spec_does_not_allow_is_rejected(api: TestClient, core: Core) -> None:
    create(api)
    core.driver.recreates = {"n3"}
    other = file_blueprint(api, a_blueprint(STEPS / "three-node-n3-eos.json"))
    plan = answered(dry_run(api, {"blueprint_id": other}), 200)
    assert plan["verdict"]["status"] == "rejected"
    assert [(f["rule"], f["object"]) for f in plan["verdict"]["findings"]] == [("step.restart.required", "n3")]
    assert {c["node"]: c["action"] for c in plan["changes"]["nodes"]}["n3"] == "recreated"
    allowed = answered(dry_run(api, {"blueprint_id": other, "allow_restart": True}), 200)
    assert (allowed["verdict"]["status"], allowed["changes"]) == ("ok", plan["changes"])
    assert len(runs_of(api, "t")) == 1


# Twins: deletion.


def test_a_delete_asks_for_deletion_and_the_loop_tears_the_twin_down(
    api: TestClient, core: Core, caplog: pytest.LogCaptureFixture
) -> None:
    record = create(api)
    with caplog.at_level(logging.INFO, logger="fylgja.audit"):
        asked = answered(api.delete("/v1/twins/t"), 202)
        gone(api, "t")
    assert asked["deletion_requested_at"] and asked["generation"] == 2 and asked["revision"] == record["revision"] + 1
    assert asked["status"] == record["status"]  # the API never writes status
    destroy, _ = runs_of(api, "t")
    assert (destroy["operation"], destroy["state"], destroy["principal"]) == ("destroy", "ended", "alice")
    assert destroy["verdict"]["status"] == "ok"
    asked_line = [line for line in audited(caplog, "delete") if line.get("generation") == 2]
    assert [(line["principal"], line["run"]) for line in asked_line] == [("alice", destroy["id"])]
    assert "t" not in core.driver.labs
    refused(api.delete("/v1/twins/t"), 404, "twin.not_found")


def test_a_delete_during_a_create_cancels_it_and_the_twin_is_gone(api: TestClient, core: Core) -> None:
    core.driver.block = "apply"
    answered(put(api, "t", {"blueprint_id": file_blueprint(api)}), 201)
    wait_for(lambda: True if answered(api.get("/v1/twins/t"), 200)["status"].get("phase") == "planned" else None)
    answered(api.delete("/v1/twins/t"), 202)
    gone(api, "t")
    destroy, create_run = runs_of(api, "t")
    assert (create_run["operation"], create_run["verdict"]["status"]) == ("create", "failed")
    assert [f["rule"] for f in create_run["verdict"]["findings"]] == ["run.cancelled"]
    assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok")
    assert "t" not in core.driver.labs


def test_a_second_delete_queues_no_second_destroy(api: TestClient, core: Core) -> None:
    create(api)
    core.driver.block = "destroy"
    first = answered(api.delete("/v1/twins/t"), 202)
    again = answered(api.delete("/v1/twins/t"), 202)
    assert again["generation"] == first["generation"] == 2
    assert [r["operation"] for r in runs_of(api, "t")] == ["destroy", "create"]


def test_a_put_on_a_twin_being_deleted_is_refused(api: TestClient, core: Core) -> None:
    record = create(api)
    core.driver.block = "destroy"
    answered(api.delete("/v1/twins/t"), 202)
    refused(put(api, "t", {"blueprint_id": record["spec"]["blueprint_id"]}), 409, "twin.deleting")


# Twins: two clients at once.


def race(*requests: Callable[[], httpx2.Response]) -> list[httpx2.Response]:
    """Each request from a thread of its own, started together; the answers in request order."""
    answers: list[httpx2.Response | None] = [None] * len(requests)
    start = threading.Barrier(len(requests))

    def send(i: int) -> None:
        start.wait()
        answers[i] = requests[i]()

    threads = [threading.Thread(target=send, args=(i,)) for i in range(len(requests))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(a is not None for a in answers)
    return [a for a in answers if a is not None]


def test_two_creates_of_one_twin_make_one(api: TestClient) -> None:
    blueprint_id = file_blueprint(api)
    answers = race(*[lambda: put(api, "t", {"blueprint_id": blueprint_id}, **{"If-None-Match": "*"})] * 2)
    assert sorted(r.status_code for r in answers) == [201, 412]
    winner, loser = sorted(answers, key=lambda r: r.status_code)
    answered(winner, 201)
    refused(loser, 412, "twin.exists")
    settled(api, "t")
    assert len(runs_of(api, "t")) == 1


def test_two_writes_from_one_revision_and_one_wins(api: TestClient, core: Core) -> None:
    record = create(api)
    core.driver.block = "destroy"  # the twin stays, being deleted, so the loser meets the moved record
    etag = f'"{record["revision"]}"'
    answers = race(*[lambda: api.delete("/v1/twins/t", headers={"If-Match": etag})] * 2)
    assert sorted(r.status_code for r in answers) == [202, 412]
    winner, loser = sorted(answers, key=lambda r: r.status_code)
    assert answered(winner, 202)["generation"] == record["generation"] + 1
    refused(loser, 412, "twin.conflict")
    assert [r["operation"] for r in runs_of(api, "t")] == ["destroy", "create"]


def test_two_puts_of_the_spec_a_twin_has_both_change_nothing(api: TestClient) -> None:
    record = create(api)
    spec, etag = {"blueprint_id": record["spec"]["blueprint_id"]}, f'"{record["revision"]}"'
    answers = race(*[lambda: put(api, "t", spec, **{"If-Match": etag})] * 2)
    assert [answered(r, 200) for r in answers] == [record, record]


def test_a_create_whose_write_is_lost_withdraws_its_run(
    api: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    def lost(record: TwinRecord) -> TwinRecord:
        raise Conflict("twin t exists")

    blueprint_id = file_blueprint(api)
    monkeypatch.setattr(core.store, "create_twin", lost)
    refused(put(api, "t", {"blueprint_id": blueprint_id}), 412, "twin.exists")
    (run,) = runs_of(api, "t")
    assert (run["state"], run["verdict"]["status"]) == ("ended", "failed")
    assert [f["rule"] for f in run["verdict"]["findings"]] == ["run.cancelled"]
    assert [(e.phase, e.outcome, e.rule) for e in core.store.events(run["id"])] == [
        ("cancel", "started", None), ("cancel", "done", "run.cancelled")]


def test_a_delete_whose_write_is_lost_withdraws_its_run(
    api: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = create(api)

    def lost(record: TwinRecord, expected_revision: int) -> TwinRecord:
        raise Conflict("twin t moved")

    monkeypatch.setattr(core.store, "update_twin", lost)
    refused(api.delete("/v1/twins/t"), 412, "twin.conflict")
    destroy, _ = runs_of(api, "t")
    assert (destroy["operation"], destroy["state"], destroy["verdict"]["status"]) == ("destroy", "ended", "failed")
    assert answered(api.get("/v1/twins/t"), 200) == record


# Runs: events by cursor and as a stream.


def streamed(response: httpx2.Response) -> list[Message]:
    """The server-sent events of an answer the operation declares as text/event-stream."""
    assert response.status_code == 200, response.read()
    fake_api.check_response(*fake_api.operation(response.request), response)
    assert response.headers["content-type"].partition(";")[0] == SSE
    return list(messages(response.iter_lines()))


def run_events(api: TestClient, run_id: str, **headers: str) -> list[Message]:
    with api.stream("GET", f"/v1/runs/{run_id}/events", headers={"Accept": SSE, **headers}) as r:
        sent = streamed(r)
    for message in sent:
        fake_api.check_component("Event", json.loads(message.data))
    return sent


def test_an_ended_runs_event_page_lists_every_event_and_a_cursor_skips(api: TestClient) -> None:
    create(api)
    (run,) = runs_of(api, "t")
    page = answered(api.get(f"/v1/runs/{run['id']}/events"), 200)
    seqs = [e["seq"] for e in page["events"]]
    assert seqs == list(range(1, len(seqs) + 1)) and len(seqs) > 3
    assert (page["next"], page["ended"]) == (seqs[-1], True)
    later = answered(api.get(f"/v1/runs/{run['id']}/events", params={"after": 3}), 200)
    assert later == {"events": page["events"][3:], "next": seqs[-1], "ended": True}
    none = answered(api.get(f"/v1/runs/{run['id']}/events", params={"after": seqs[-1]}), 200)
    assert none == {"events": [], "next": seqs[-1], "ended": True}
    refused(api.get(f"/v1/runs/{run['id']}/events", params={"after": "-1"}), 400, "request.invalid")
    refused(api.get(f"/v1/runs/{'0' * 26}/events"), 404, "run.not_found")


def test_a_run_in_flight_has_not_ended(api: TestClient, core: Core) -> None:
    core.driver.block = "apply"
    answered(put(api, "t", {"blueprint_id": file_blueprint(api)}), 201)
    wait_for(lambda: True if answered(api.get("/v1/twins/t"), 200)["status"].get("phase") == "planned" else None)
    (run,) = runs_of(api, "t")
    page = answered(api.get(f"/v1/runs/{run['id']}/events"), 200)
    assert page["ended"] is False and page["next"] == page["events"][-1]["seq"]
    assert page["events"][-1]["phase"] == "apply" and page["events"][-1]["outcome"] == "started"


def test_a_runs_event_stream_sends_each_event_by_its_seq_and_ends_with_the_run(api: TestClient) -> None:
    answered(put(api, "t", {"blueprint_id": file_blueprint(api)}), 201)
    (run,) = runs_of(api, "t")
    sent = run_events(api, run["id"])  # answered once the run has ended and every event is sent
    assert [m.id for m in sent] == [str(json.loads(m.data)["seq"]) for m in sent]
    assert [int(m.id or 0) for m in sent] == list(range(1, len(sent) + 1))
    assert answered(api.get(f"/v1/runs/{run['id']}"), 200)["state"] == "ended"
    assert [json.loads(m.data) for m in sent] == answered(api.get(f"/v1/runs/{run['id']}/events"), 200)["events"]
    resumed = run_events(api, run["id"], **{"Last-Event-ID": "3"})
    assert [m.id for m in resumed] == [m.id for m in sent[3:]]
    with api.stream("GET", f"/v1/runs/{run['id']}/events", headers={"Accept": SSE, "Last-Event-ID": "x"}) as r:
        r.read()
        refused(r, 400, "request.invalid")


def test_a_run_is_cancelled_by_id(api: TestClient, core: Core, caplog: pytest.LogCaptureFixture) -> None:
    core.driver.block = "admit"
    answered(put(api, "t", {"blueprint_id": file_blueprint(api)}), 201)
    (run,) = runs_of(api, "t")
    with caplog.at_level(logging.INFO, logger="fylgja.audit"):
        cancelling = answered(api.post(f"/v1/runs/{run['id']}/cancel", headers={"Authorization": f"Bearer {BOB}"}),
                              202)
    assert (cancelling["id"], cancelling["state"], cancelling["principal"]) == (run["id"], "cancelling", "alice")
    assert [(line["principal"], line["run"]) for line in audited(caplog, "cancel")] == [("bob", run["id"])]
    record = settled(api, "t")
    assert ready(record) == ("False", "run.cancelled")
    ended = answered(api.get(f"/v1/runs/{run['id']}"), 200)
    assert (ended["state"], ended["verdict"]["status"]) == ("ended", "failed")
    assert [f["rule"] for f in ended["verdict"]["findings"]] == ["run.cancelled"]
    last = answered(api.get(f"/v1/runs/{run['id']}/events"), 200)["events"][-1]
    assert (last["phase"], last["outcome"], last["rule"]) == ("cancel", "done", "run.cancelled")
    refused(api.post(f"/v1/runs/{run['id']}/cancel"), 409, "run.ended")
    refused(api.post(f"/v1/runs/{'0' * 26}/cancel"), 404, "run.not_found")


def test_a_restore_run_is_served_as_a_run_of_operation_restore(api: TestClient, core: Core) -> None:
    create(api, blueprint_id=target_of(api, core, THREE_NODE))  # verify holds: the restore's wait settles
    core.driver.replace("t", "n2")  # behind the loop's back
    core.reconciler.kick("t")

    def restored() -> dict[str, Any] | None:
        run = runs_of(api, "t")[0]
        return run if run["operation"] == "restore" and run["state"] == "ended" else None

    run = wait_for(restored)
    assert (run["operation"], run["principal"]) == ("restore", "core")
    assert (run["verdict"]["operation"], run["verdict"]["status"]) == ("restore", "ok")
    assert run["verdict"]["wait"]["outcome"] == "settled" and "loss" not in run["verdict"]
    assert answered(api.get(f"/v1/runs/{run['id']}"), 200) == run


# Twins: watches, read as they stream.


@contextlib.contextmanager
def watching(client: httpx2.Client, path: str, **params: str) -> Iterator[Iterator[dict[str, Any]]]:
    """A watch's WatchEvents as they come, each held to WatchEvent and named by its message."""
    with client.stream("GET", path, params={"watch": "true", **params}, headers={"Accept": SSE}) as r:
        assert r.status_code == 200, r.read()
        fake_api.check_response(*fake_api.operation(r.request), r)

        def events() -> Iterator[dict[str, Any]]:
            for message in messages(r.iter_lines()):
                event: dict[str, Any] = json.loads(message.data)
                fake_api.check_component("WatchEvent", event)
                assert message.event == event["type"] and message.id is None
                yield event

        yield events()


def revisions(events: list[dict[str, Any]]) -> list[int]:
    return [e["object"]["revision"] for e in events]


def test_a_watch_from_before_a_put_sees_each_write_once_in_order(served: httpx2.Client) -> None:
    blueprint_id = file_blueprint(served)
    seen = []
    with watching(served, "/v1/twins") as events:
        answered(put(served, "t", {"blueprint_id": blueprint_id}), 201)
        for event in events:
            seen.append(event)
            if event["object"]["status"]["observed_generation"] == event["object"]["generation"]:
                break
    assert [e["type"] for e in seen] == ["ADDED"] + ["MODIFIED"] * (len(seen) - 1)
    assert revisions(seen) == list(range(1, len(seen) + 1)) and len(seen) > 3
    assert ready(seen[-1]["object"]) == ("True", "twin.ready")


def test_a_watch_resumed_from_the_last_revision_seen_misses_nothing_and_repeats_nothing(served: httpx2.Client) -> None:
    blueprint_id = file_blueprint(served)
    with watching(served, "/v1/twins") as events:
        answered(put(served, "t", {"blueprint_id": blueprint_id}), 201)
        first = [next(events) for _ in range(3)]
    last = revisions(first)[-1]
    record = settled(served, "t")
    assert record["revision"] > last
    with watching(served, "/v1/twins/t", since_revision=str(last)) as events:
        now = next(events)
        answered(served.delete("/v1/twins/t"), 202)
        rest = list(events)  # the server ends the stream after DELETED
    assert now == {"type": "MODIFIED", "object": record}  # the record as it stands: the store keeps no history
    assert [e["type"] for e in rest][-1] == "DELETED" and {e["type"] for e in rest[:-1]} == {"MODIFIED"}
    changed = revisions([now, *rest[:-1]])
    assert changed == list(range(record["revision"], record["revision"] + len(changed)))
    assert rest[-1]["object"]["revision"] == changed[-1]


def test_a_watch_from_the_revision_a_twin_is_at_begins_with_its_next_write(served: httpx2.Client) -> None:
    record = create(served)
    with watching(served, "/v1/twins/t", since_revision=str(record["revision"])) as events:
        answered(served.delete("/v1/twins/t"), 202)
        first = next(events)
    assert first["type"] == "MODIFIED" and first["object"]["revision"] == record["revision"] + 1
    assert first["object"]["deletion_requested_at"]


def test_a_watch_of_every_twin_sends_each_current_record_first(served: httpx2.Client) -> None:
    blueprint_id = file_blueprint(served)
    a, b = create(served, "a", blueprint_id), create(served, "b", blueprint_id)
    with watching(served, "/v1/twins") as events:
        current = [next(events), next(events)]
    assert current == [{"type": "MODIFIED", "object": a}, {"type": "MODIFIED", "object": b}]
    # Revisions are each twin's own: the list's since_revision skips the current records it reaches, and
    # every change after the watch begins is sent, a new twin's first write too.
    with watching(served, "/v1/twins", since_revision=str(max(a["revision"], b["revision"]))) as events:
        answered(put(served, "c", {"blueprint_id": blueprint_id}), 201)
        first = next(events)
    assert (first["type"], first["object"]["name"], first["object"]["revision"]) == ("ADDED", "c", 1)


def test_an_accept_of_server_sent_events_asks_for_a_watch(served: httpx2.Client) -> None:
    record = create(served)
    with served.stream("GET", "/v1/twins/t", headers={"Accept": SSE}) as r:
        first = json.loads(next(messages(r.iter_lines())).data)
    assert first == {"type": "MODIFIED", "object": record}
    r = served.get("/v1/twins/t", params={"watch": "false"}, headers={"Accept": SSE})
    assert answered(r, 200) == record


def test_a_watch_of_a_twin_that_does_not_exist_is_not_found(served: httpx2.Client) -> None:
    refused(served.get("/v1/twins/nope", params={"watch": "true"}, headers={"Accept": SSE}), 404, "twin.not_found")
    refused(served.get("/v1/twins", params={"watch": "true", "since_revision": "x"}), 400, "request.invalid")
    refused(served.get("/v1/twins/t", params={"watch": "maybe"}), 400, "request.invalid")


def test_a_watch_the_client_closes_releases_what_it_held(served: httpx2.Client, core: Core) -> None:
    create(served)
    with watching(served, "/v1/twins/t") as events:
        next(events)
        assert len(core.store._subscribers) == 1
    wait_for(lambda: True if len(core.store._subscribers) == 0 else None)


def test_the_servers_shutdown_ends_every_open_stream(served: httpx2.Client, core: Core) -> None:
    record = create(served)
    core.driver.block = "apply"
    answered(put(served, "u", {"blueprint_id": record["spec"]["blueprint_id"]}), 201)
    (run,) = runs_of(served, "u")
    with watching(served, "/v1/twins/t") as twin, \
            served.stream("GET", f"/v1/runs/{run['id']}/events", headers={"Accept": SSE}) as events:
        run_events = messages(events.iter_lines())
        next(twin), next(run_events)
        core.closing.set()
        list(run_events)  # each stream ends, and is not cut: a cut one raises
        assert list(twin) == []


def test_the_thin_cli_creates_shows_and_destroys_a_twin_through_the_served_api(
    served: httpx2.Client, core: Core, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from fylgja_core import cli

    monkeypatch.setenv("FYLGJA_API_ADDRESS", str(served.base_url))
    monkeypatch.setenv("FYLGJA_API_TOKEN", ALICE)
    assert cli.main(["twin", "create", "t", "--blueprint", str(THREE_NODE)]) == 0
    capsys.readouterr()
    assert cli.main(["twin", "show", "t", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert schemas.validator("twin-record-1").is_valid(shown) and ready(shown) == ("True", "twin.ready")
    assert cli.main(["twin", "destroy", "t"]) == 0
    out = capsys.readouterr().out
    assert "twin t deleted" in out and ALICE not in out
    assert core.store.list_twins() == [] and "t" not in core.driver.labs


def test_the_thin_cli_steps_a_twin_through_the_served_api(
    served: httpx2.Client, core: Core, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from fylgja_core import cli

    monkeypatch.setenv("FYLGJA_API_ADDRESS", str(served.base_url))
    monkeypatch.setenv("FYLGJA_API_TOKEN", ALICE)
    assert cli.main(["twin", "create", "t", "--blueprint", str(THREE_NODE)]) == 0
    capsys.readouterr()
    before = core.store.get_twin("t").status.bundle_id
    assert before is not None
    target = STEPS / "three-node-unlinked.json"
    target_of(served, core, target)
    assert cli.main(["twin", "step", "t", "--blueprint", str(target), "--dry-run"]) == 0
    planned = capsys.readouterr().out.splitlines()
    assert [line for line in planned if "n2:" in line] == [
        "  n2: recabled (links)", "  link removed: n2:ethernet-1/2 -- n3:ethernet-1/1"]
    assert cli.main(["twin", "step", "t", "--blueprint", str(target)]) == 0
    out = capsys.readouterr().out
    after = core.store.get_twin("t").status.bundle_id
    assert after is not None and after != before
    assert f"last step: stepped {before[:12]} -> {after[:12]} at flows" in out.splitlines()
    assert "verdict: ok" in out.splitlines() and ALICE not in out
    (step, _) = runs_of(served, "t")
    assert (step["operation"], step["principal"]) == ("step", "alice")


# A write that fails between the run it queues and the record: the run is withdrawn.


def test_a_create_whose_record_cannot_be_written_withdraws_its_run(
    api: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(record: TwinRecord) -> TwinRecord:
        raise OSError(28, "No space left on device")

    blueprint_id = file_blueprint(api)
    monkeypatch.setattr(core.store, "create_twin", failing)
    stray(put(api, "t", {"blueprint_id": blueprint_id}), 500, "server.error")
    (withdrawn,) = runs_of(api, "t")
    assert (withdrawn["state"], withdrawn["verdict"]["status"]) == ("ended", "failed")
    assert [f["rule"] for f in withdrawn["verdict"]["findings"]] == ["run.cancelled"]


def test_a_delete_whose_record_cannot_be_written_withdraws_its_run(
    api: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = create(api)

    def failing(record: TwinRecord, expected_revision: int) -> TwinRecord:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(core.store, "update_twin", failing)
    stray(api.delete("/v1/twins/t"), 500, "server.error")
    destroy, _ = runs_of(api, "t")
    assert (destroy["operation"], destroy["state"], destroy["verdict"]["status"]) == ("destroy", "ended", "failed")
    assert answered(api.get("/v1/twins/t"), 200) == record


# A cancelling mark that loses its compare-and-set is read again once. These run with no lifespan,
# so the loop never takes the runs and each answer is the API's alone.


@pytest.fixture
def idle(core: Core) -> TestClient:
    """A client as alice of the application with its lifespan not run: the loop is not started."""
    return TestClient(core.app, headers={"Authorization": f"Bearer {ALICE}"})


def lose_the_first_mark(
    monkeypatch: pytest.MonkeyPatch, store: LocalStore, meanwhile: Callable[[], None] | None = None
) -> list[tuple[RunState, bool]]:
    """Make the first write of a `cancelling` mark lose its compare-and-set (after `meanwhile`
    makes the write that beat it); each mark's expected state and whether it was written."""
    real = store.update_run
    marks: list[tuple[RunState, bool]] = []

    def update_run(r: Run, expected_state: RunState) -> None:
        if r.state == "cancelling":
            if not marks:
                marks.append((expected_state, False))
                if meanwhile is not None:
                    meanwhile()
                raise Conflict(f"run {r.id} moved")
            marks.append((expected_state, True))
        real(r, expected_state)

    monkeypatch.setattr(store, "update_run", update_run)
    return marks


def ended_ok(r: Run) -> Run:
    return run.ended(r, Verdict(operation=r.operation, status="ok", subject=Subject(twin=r.twin, run_id=r.id),
                                findings=()))


def test_a_cancel_that_loses_its_write_reads_the_run_again_and_marks_it(
    idle: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued = run.queued("t", "create", "alice")
    core.store.create_run(queued)
    marks = lose_the_first_mark(monkeypatch, core.store)
    assert answered(idle.post(f"/v1/runs/{queued.id}/cancel"), 202)["state"] == "cancelling"
    assert marks == [("queued", False), ("queued", True)]


def test_a_cancel_of_a_run_that_ended_meanwhile_is_refused(
    idle: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued = run.queued("t", "create", "alice")
    core.store.create_run(queued)
    real = core.store.update_run
    marks = lose_the_first_mark(monkeypatch, core.store, lambda: real(ended_ok(queued), "queued"))
    refused(idle.post(f"/v1/runs/{queued.id}/cancel"), 409, "run.ended")
    assert marks == [("queued", False)] and core.store.get_run(queued.id).state == "ended"


def in_flight(core: Core, blueprint_id: str) -> Run:
    """A twin `t` whose record names a create run that is running, as the loop leaves it mid-create."""
    running = run.queued("t", "create", "alice")
    core.store.create_run(running)
    core.store.update_run(running := dataclasses_replace(running, state="running"), "queued")
    spec = Spec(blueprint_id=blueprint_id, driver="fake", allow_restart=False)
    core.store.create_twin(TwinRecord(name="t", revision=1, generation=1, spec=spec,
                                      status=Status(observed_generation=0, conditions=(), nodes=(),
                                                    run_id=running.id, phase="compiled")))
    return running


def test_two_specs_written_before_the_loop_takes_either_supersede_the_older_run(idle: TestClient, core: Core) -> None:
    # The loop is not started: each pass is run here, so both specs are written before one takes a run.
    answered(put(idle, "t", {"blueprint_id": file_blueprint(idle)}), 201)
    asyncio.run(core.reconciler.reconcile("t"))
    answered(put(idle, "t", {"blueprint_id": file_blueprint(idle, a_blueprint(STEPS / "two-node.json"))}), 200)
    target = target_of(idle, core, STEPS / "three-node-unlinked.json")
    answered(put(idle, "t", {"blueprint_id": target}), 200)
    newer, older, _ = runs_of(idle, "t")
    assert [(r["operation"], r["state"]) for r in (newer, older)] == [("step", "queued")] * 2
    asyncio.run(core.reconciler.reconcile("t"))

    superseded = answered(idle.get(f"/v1/runs/{older['id']}"), 200)
    assert (superseded["state"], superseded["verdict"]["status"]) == ("ended", "failed")
    assert [(f["rule"], f["message"]) for f in superseded["verdict"]["findings"]] == [
        ("run.cancelled", f"The run was superseded before it started by run {newer['id']}.")]
    page = answered(idle.get(f"/v1/runs/{older['id']}/events"), 200)
    assert [(e["phase"], e["outcome"], e.get("rule")) for e in page["events"]] == [
        ("cancel", "started", None), ("cancel", "done", "run.cancelled")]
    assert page["ended"] is True  # so a watch of it ends
    taken = answered(idle.get(f"/v1/runs/{newer['id']}"), 200)
    assert (taken["state"], taken["verdict"]["status"], taken["principal"]) == ("ended", "ok", "alice")
    record = answered(idle.get("/v1/twins/t"), 200)
    assert record["status"]["observed_generation"] == record["generation"] == 3
    assert record["spec"]["blueprint_id"] == target and record["status"]["last_step"]["run_id"] == newer["id"]


def test_a_delete_whose_cancelling_mark_loses_reads_the_run_again_and_marks_it(
    idle: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    running = in_flight(core, file_blueprint(idle))
    marks = lose_the_first_mark(monkeypatch, core.store)
    answered(idle.delete("/v1/twins/t"), 202)
    assert marks == [("running", False), ("running", True)]
    assert core.store.get_run(running.id).state == "cancelling"


def test_a_delete_leaves_a_run_that_ended_meanwhile_as_it_ended(
    idle: TestClient, core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    running = in_flight(core, file_blueprint(idle))
    real = core.store.update_run
    marks = lose_the_first_mark(monkeypatch, core.store, lambda: real(ended_ok(running), "running"))
    answered(idle.delete("/v1/twins/t"), 202)
    assert marks == [("running", False)] and core.store.get_run(running.id).state == "ended"



def test_the_thin_cli_destroying_a_twin_mid_create_waits_until_it_is_gone(
    served: httpx2.Client, core: Core, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from fylgja_core import cli

    core.driver.block = "apply"
    answered(put(served, "t", {"blueprint_id": file_blueprint(served)}), 201)
    wait_for(lambda: True if answered(served.get("/v1/twins/t"), 200)["status"].get("phase") == "planned" else None)
    monkeypatch.setenv("FYLGJA_API_ADDRESS", str(served.base_url))
    monkeypatch.setenv("FYLGJA_API_TOKEN", ALICE)
    assert cli.main(["twin", "destroy", "t"]) == 0
    assert "twin t deleted" in capsys.readouterr().out
    assert core.store.list_twins() == []
