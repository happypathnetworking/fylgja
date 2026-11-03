"""API 1 served over a local store in a temporary directory, the shipped packages and the reconcile
loop on a fake driver (formats/api-1.openapi.yaml, D-025, D-039). Every answer is held to the
operation its request names in the OpenAPI document (its status, media type and body), or, for a
path API 1 does not have, to problem-1."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import fake_api
import httpx
import pytest
import yaml
from fakes import FakeDriver, fake_push, fake_ready
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fylgja_core import blueprint, bundle, deployment, packages, schemas
from fylgja_core.credentials import Provider
from fylgja_core.driver import Planned, Refusal, Unplannable
from fylgja_core.findings import Finding
from fylgja_core.local_store import LocalStore
from fylgja_core.reconcile import Reconciler
from fylgja_core.server import auth
from fylgja_core.server.app import create_app
from fylgja_core.store import Conflict
from fylgja_core.twin_record import Spec, Status, TwinRecord

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


@dataclass
class Core:
    """What the application is built over, for a test to arrange and to look into."""

    app: Starlette
    store: LocalStore
    driver: FakeDriver
    reconciler: Reconciler


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Core]:
    store = LocalStore.open(tmp_path / "store")
    tokens = tmp_path / "tokens"
    tokens.write_text(f"# the test's clients\n{auth.hash_token(ALICE)} alice\n{auth.hash_token(BOB)} bob\n")
    loaded = packages.load([ROOT / "psp", ROOT / "probes"])
    driver = FakeDriver()
    reconciler = Reconciler(store, {driver.name: driver}, loaded.platforms, loaded.probes, Provider(ENVIRON),
                            workers=1, pusher=fake_push(driver=driver), readiness=fake_ready(driver=driver),
                            cancel_poll_s=0.01)
    app = create_app(store=store, loaded=loaded, drivers={driver.name: driver}, default_driver=driver.name,
                     reconciler=reconciler, tokens=auth.Tokens.load(tokens), build=version("fylgja-core"))
    yield Core(app=app, store=store, driver=driver, reconciler=reconciler)
    store.close()


@pytest.fixture
def api(core: Core) -> Iterator[TestClient]:
    """A client as alice, with the application's lifespan (and so the loop) running."""
    with TestClient(core.app, headers={"Authorization": f"Bearer {ALICE}"}) as client:
        yield client


def answered(response: httpx.Response, status: int) -> Any:
    """The answer's document, once its status is `status` and the operation its request names
    declares that status, its media type and its body's shape."""
    assert response.status_code == status, response.text
    template, method = fake_api.operation(response.request)
    fake_api.check_response(template, method, response)
    return response.json()


def refused(response: httpx.Response, status: int, rule: str) -> dict[str, Any]:
    """The problem document an operation answered, once its status and rule are these."""
    doc: dict[str, Any] = answered(response, status)
    assert response.headers["content-type"] == "application/problem+json"
    assert doc["rule"] == rule, doc
    assert doc["instance"] == response.request.url.path
    return doc


def stray(response: httpx.Response, status: int, rule: str) -> dict[str, Any]:
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


def file_blueprint(api: TestClient, doc: dict[str, Any] | None = None) -> str:
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
        "nodes": "provisions", "relink": False, "forwarding": "software", "access": "direct", "isolation": "names"}}]}


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


def test_the_bundle_diff_is_not_built_in_this_phase(api: TestClient) -> None:
    problem = refused(api.get(f"/v1/bundles/{'a' * 64}/diff/{'b' * 64}"), 501, "api.unbuilt")
    assert "phase 5" in problem["detail"]


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


def settled(api: TestClient, name: str) -> dict[str, Any]:
    """The twin's record once the loop has acted on its generation."""

    def read() -> dict[str, Any] | None:
        record: dict[str, Any] = answered(api.get(f"/v1/twins/{name}"), 200)
        return record if record["status"]["observed_generation"] == record["generation"] else None

    return wait_for(read)


def gone(api: TestClient, name: str) -> None:
    """Return once the twin's record is deleted."""
    wait_for(lambda: True if api.get(f"/v1/twins/{name}").status_code == 404 else None)


def ready(record: dict[str, Any]) -> tuple[str, str | None]:
    (condition,) = [c for c in record["status"]["conditions"] if c["type"] == "Ready"]
    return condition["status"], condition.get("reason")


def runs_of(api: TestClient, name: str) -> list[dict[str, Any]]:
    listed: list[dict[str, Any]] = answered(api.get("/v1/runs", params={"twin": name}), 200)["runs"]
    return listed


def put(api: TestClient, name: str, spec: dict[str, Any], **headers: str) -> httpx.Response:
    response: httpx.Response = api.put(f"/v1/twins/{name}", json={"spec": spec}, headers=headers)
    return response


def create(api: TestClient, name: str = "t", blueprint_id: str | None = None) -> dict[str, Any]:
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


def test_a_change_of_spec_is_a_step_which_is_not_built_yet(api: TestClient) -> None:
    record = create(api)
    other = file_blueprint(api, a_blueprint(ROOT / "testdata/blueprint/mixed.json"))
    problem = refused(put(api, "t", {"blueprint_id": other}), 501, "api.unbuilt")
    assert "phase 5" in problem["detail"]
    refused(put(api, "t", {"blueprint_id": record["spec"]["blueprint_id"], "allow_restart": True}), 501, "api.unbuilt")
    assert answered(api.get("/v1/twins/t"), 200) == record


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


def test_verify_is_not_built_yet(api: TestClient) -> None:
    refused(api.post("/v1/twins/t/verifications"), 501, "api.unbuilt")


# Twins: the dry run.


def test_a_dry_run_answers_the_plan_and_writes_nothing(api: TestClient) -> None:
    blueprint_id = file_blueprint(api)
    r = api.put("/v1/twins/t", params={"dry_run": "true"}, json={"spec": {"blueprint_id": blueprint_id}})
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


def race(*requests: Callable[[], httpx.Response]) -> list[httpx.Response]:
    """Each request from a thread of its own, started together; the answers in request order."""
    answers: list[httpx.Response | None] = [None] * len(requests)
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
