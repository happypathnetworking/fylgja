"""Tokens map to principals, and the middleware lets only a known token through."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from fylgja_core import schemas
from fylgja_core.server import auth

ALPHA = "alpha-test-token"
BETA = "beta-test-token"


@pytest.fixture
def tokens(tmp_path: Path) -> auth.Tokens:
    path = tmp_path / "tokens"
    path.write_text(
        f"# clients\n{auth.hash_token(ALPHA)} alice\n\n{auth.hash_token(BETA)}  ci-bot\n"
    )
    return auth.Tokens.load(path)


@pytest.fixture
def client(tokens: auth.Tokens) -> TestClient:
    async def who(request: Request) -> Response:
        return JSONResponse({"principal": request.state.principal})

    async def version(request: Request) -> Response:
        return JSONResponse({"version": "1"})

    app = Starlette(routes=[Route("/v1/whoami", who), Route("/v1/version", version)])
    app.add_middleware(auth.AuthMiddleware, tokens=tokens)
    return TestClient(app)


def test_two_tokens_map_to_their_principals(tokens: auth.Tokens) -> None:
    assert tokens.principal(ALPHA) == "alice"
    assert tokens.principal(BETA) == "ci-bot"
    assert tokens.principal("unknown-token") is None


def test_the_file_never_holds_a_token(tmp_path: Path) -> None:
    path = tmp_path / "tokens"
    path.write_text(f"{auth.hash_token(ALPHA)} alice\n")
    assert ALPHA not in path.read_text()
    assert len(auth.hash_token(ALPHA)) == 64


def test_a_malformed_line_is_refused_naming_its_number(tmp_path: Path) -> None:
    path = tmp_path / "tokens"
    path.write_text("# c\nonlyonefield\n")
    with pytest.raises(ValueError, match="line 2"):
        auth.Tokens.load(path)


def test_no_header_is_401_token_missing(client: TestClient) -> None:
    r = client.get("/v1/whoami")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["rule"] == "auth.token.missing"
    assert list(schemas.validator("problem-1").iter_errors(r.json())) == []


def test_a_non_bearer_header_is_401_token_missing(client: TestClient) -> None:
    r = client.get("/v1/whoami", headers={"Authorization": "Basic abc"})
    assert (r.status_code, r.json()["rule"]) == (401, "auth.token.missing")


def test_a_wrong_token_is_401_token_unknown_and_never_echoed(client: TestClient) -> None:
    r = client.get("/v1/whoami", headers={"Authorization": "Bearer wrong-test-token"})
    assert (r.status_code, r.json()["rule"]) == (401, "auth.token.unknown")
    assert "wrong-test-token" not in r.text
    assert r.json()["instance"] == "/v1/whoami"


def test_a_right_token_sets_the_principal(client: TestClient) -> None:
    r = client.get("/v1/whoami", headers={"Authorization": f"Bearer {BETA}"})
    assert (r.status_code, json.loads(r.text)) == (200, {"principal": "ci-bot"})


def test_version_needs_no_token(client: TestClient) -> None:
    assert client.get("/v1/version").status_code == 200
