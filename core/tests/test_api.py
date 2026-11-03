"""API 1 served over a local store in a temporary directory, the shipped packages and the reconcile
loop on a fake driver (formats/api-1.openapi.yaml, D-025, D-039). Every answer is held to the
operation its request names in the OpenAPI document (its status, media type and body), or, for a
path API 1 does not have, to problem-1."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
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

from fylgja_core import blueprint, bundle, packages, schemas
from fylgja_core.credentials import Provider
from fylgja_core.local_store import LocalStore
from fylgja_core.reconcile import Reconciler
from fylgja_core.server import auth
from fylgja_core.server.app import create_app

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
