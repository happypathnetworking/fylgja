"""Tier 1's Infrahub: recorded answers served through the SDK's own transport hook
(`sync_requester`), so the adapter's client runs whole, the SDK included, with no server."""

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest

DATA = Path(__file__).resolve().parents[1] / "data"
TOKEN = "sentinel-token"
ADDRESS = "http://infrahub.test"


class FakeInfrahub:
    """One Infrahub holding branches, each answering the recorded schema document (which a
    test may change) and whatever GraphQL answer a test sets. Every request is kept, its
    path, its query and its headers."""

    def __init__(self):
        self.schema = json.loads((DATA / "schema" / "schema-26336e9.json").read_text())
        self.branches = {"main", "fylgja-fixture"}
        self.graphql = {"data": {}}
        self.graphql_status = 200
        self.schema_status = None
        self.schema_body = None
        self.requests: list[dict] = []

    def count(self, path: str) -> int:
        return sum(1 for r in self.requests if r["path"] == path)

    def __call__(self, url, method, headers, timeout, payload=None):
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        self.requests.append(
            {"url": url, "path": unquote(parts.path), "raw_path": parts.path, "query": query,
             "headers": dict(headers), "payload": copy.deepcopy(payload)}
        )
        request = httpx.Request(method.value, url)

        def answer(status, body):
            return httpx.Response(status, content=json.dumps(body).encode(), request=request)

        if headers.get("X-INFRAHUB-KEY") != TOKEN:
            return answer(401, {"errors": [{"message": "Invalid token", "extensions": {"code": 401}}]})
        if parts.path == "/api/schema":
            branch = query.get("branch", ["main"])[0]
            if self.schema_status is not None:
                return httpx.Response(self.schema_status, content=self.schema_body, request=request)
            if branch not in self.branches:
                return answer(400, {"data": None, "errors": [{"message": f"Branch: {branch} not found.",
                                                              "extensions": {"code": 400}}]})
            return answer(200, self.schema)
        if parts.path.startswith("/graphql/"):
            branch = unquote(parts.path.removeprefix("/graphql/"))
            if branch not in self.branches:
                return answer(404, {"errors": [f"Branch: {branch} not found."]})
            return answer(self.graphql_status, self.graphql)
        return answer(404, {"errors": ["no route"]})


@pytest.fixture
def infrahub():
    return FakeInfrahub()


@pytest.fixture
def client_for(infrahub):
    """A client of the fake, for a branch and an `at`, with the fake's token or another."""
    from fylgja_orchestrator.adapters.infrahub.client import Client, Config

    def make(branch="fylgja-fixture", at="", token=TOKEN):
        return Client(Config(address=ADDRESS, token=token, branch=branch, at=at), requester=infrahub)

    return make
